"""runner.py: the minute set's one thread and one lock.

The clocks that end waits and move work along run in one thread, the server's `Runner`, which `server._start_background` always starts. They used to run in two
threads of their own, a wake loop (the watchers' pass and the anchor pass, each at its minute) and a 20-second fleet watch; those shared nothing but the board and
ran in no order the code could state: a done check could run before the event wait that would have ended it, and a hand-off tick before the pull-request wait it
depends on. The ticks run in this order, each in its own try so that one that raises never stops the next:

  1. settle   the events that end a wait: the watchers' pass, the anchor pass, the phase sweep (the stored phase and waits_on brought up to the clock), the event waits, the done check, the step proof
  2. handoff  the hand-off tick
  3. answers  a decision answer nobody acted on goes to its keeper
  4. fleet    the fleet's clocks (registry sync, clients, pilot fallback, stall, hand-back), then the publish
              when the fleet files changed
  5. tenmin   the ten-minute set, right after the minute set in the same round: the filing pass (is each item filed in the right state?), the dates pass
              (the For you list's due-date look, and items whose wake has passed with no write since), the wake catch-up (the watchers' pass without its due-wake gate) and the audit tick
              (the hourly audit line, then the idle hand-over)

A tick is the existing server function, called as it is; its own interval gate (the done check's minute, the stall pass's `every_seconds`, the for-you
list's five minutes) is still its own, so what a tick does is unchanged. What the runner owns is the order, the one thread, the one lock and the record of
what ran.

The pace is one minute. A tick is either `paced` (the fleet's clocks: one round every `PACE` seconds, the pause measured from the end of the last paced
round) or `event` (the watchers' and the anchor pass: a round when the wake event is set, when the wake wait ended (until the
earliest wake, at most 60 s), or in every paced round). The last part is what keeps the order whole at the minute: a paced round always starts with the
watchers' and anchor passes, so the done check, the step proof and the hand-off tick never look at the board before the passes that end a wait have. A wake
event or a wake that falls due between two minutes runs the two event ticks alone, so a wake still fires at its minute. The loop wakes at the earliest of the two.
`PACE` is the runner's only cadence knob.
The ten-minute set runs in the first paced round after the start (so a restart never delays it), then in the first paced round after each tenth minute (`TEN_PACE`), right after the minute set in that round; a late round runs the set once and the next one is the next tenth minute, so the set never drifts and never runs twice to catch up.

`stalled(now)` says whether the last completed round is older than `STALL_AFTER` (3 minutes): the server's watchdog thread asks it every minute and tells the builder once per stall. `current` names the tick running now.

Pure standard library; the server builds the tick table (it owns the functions) and passes in what the runner must ask it: whether the board is held by the
migration's pass (`holding`) and how long the runner may sleep between event rounds (`wake_wait`)."""
from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

PACE = 60.0          # seconds between paced rounds: the minute pace
WAKE_MAX = 60.0      # the longest the runner sleeps between event rounds
SLOW_TICK = 30.0     # a tick that takes this many seconds is logged by name: with one thread everything behind it, a due wake included, waited
WAKE_MIN = 1.0       # the shortest wait the runner takes between two event rounds (the old loop could spin when a due wake could not be fired)
TEN_PACE = 600.0     # seconds between runs of the ten-minute set
STALL_AFTER = 180.0  # a runner whose last completed round is older than this many seconds is stalled (a blocking call inside a tick): the publish loop's watchdog reads it
GROUPS = ("settle", "handoff", "answers", "fleet", "tenmin")
PACES = ("event", "paced", "tenmin")


@dataclass(frozen=True)
class Tick:
    """One step of the minute set. `fn` takes no arguments (the server binds it late, so a test's replacement of the function is the one called)."""
    name: str
    fn: Callable[[], Any]
    group: str                  # one of GROUPS: the order is the table's, the group is its label in the status
    pace: str = "paced"         # "paced": runs in a paced round · "event": runs in a round the wake event or the wake wait started · "tenmin": runs in the paced round that finds the ten-minute set due, after the rest
    board: bool = False         # True: skipped while the migration's pass holds the board (every clock that reads items)


class Runner:
    """The minute set. `ticks` run in the order given. `holding()` says the board is held; `wake_wait()` says how many seconds the runner may sleep before the next event round (called after
    each event round). `event` is the wake event `server._update` sets (a fresh one when not given). `clock` is for tests."""

    def __init__(self, ticks: list[Tick], *, holding: Callable[[], bool] | None = None, wake_wait: Callable[[], float] | None = None,
                 event: threading.Event | None = None, pace: float = PACE, ten_pace: float = TEN_PACE, clock: Callable[[], float] = time.time, label: str = "runner") -> None:
        names = [t.name for t in ticks]
        if len(set(names)) != len(names):
            raise ValueError(f"a tick listed twice: {sorted({n for n in names if names.count(n) > 1})}")
        for t in ticks:
            if t.group not in GROUPS or t.pace not in PACES:
                raise ValueError(f"tick {t.name}: group {t.group!r} / pace {t.pace!r} is not one of {GROUPS} / {PACES}")
        self.ticks = list(ticks)
        self.holding = holding or (lambda: False)
        self.wake_wait = wake_wait or (lambda: WAKE_MAX)
        self.wake = event if event is not None else threading.Event()
        self.pace = float(pace)
        self.ten_pace = float(ten_pace)
        self.clock = clock
        self.label = label
        self.lock = threading.Lock()                 # held for the whole of a round: two rounds, and so two ticks, never overlap
        self._status_lock = threading.Lock()         # the status is read from a request thread while a round runs; this lock is held for a dict copy only
        self._stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.started: float | None = None
        self.rounds = 0
        self.last_round: float | None = None
        self.current: str = ""                       # the name of the tick running now ("" between ticks): the watchdog's message says where a stall sits
        self._pace_end: float | None = None          # the end of the last paced round; the first paced round comes one pace after the start, as the old loop's first sleep
        self._ten_at: float | None = None            # when the ten-minute set is next due; None = at the next paced round (a runner driven by hand, or just started)
        self._wake_at: float | None = None           # when the next event round is due; None = at once: the old loop slept first (up to 60 s) and then ran its pass, the runner runs its first event round at start (the start has just run a wake pass, so it finds nothing new)
        self._state = {t.name: {"runs": 0, "errors": 0, "skipped": 0, "last_run": None, "last_ms": None, "last_error": None, "last_error_at": None} for t in self.ticks}

    # ---- one round
    def run_round(self, event: bool = False) -> list[str]:
        """Run the ticks that are due, in the table's order, under the lock. `event`: the wake event was set. A round that is due for its pace runs the event ticks as well, in front of
        the paced ones the table lists after them. → the names of the ticks run."""
        with self.lock:
            now = self.clock()
            paced = self._pace_end is None or now - self._pace_end >= self.pace
            wake_round = event or paced or self._wake_at is None or now >= self._wake_at     # a paced round carries the event ticks too: the passes that end a wait come first in every minute
            ten = paced and (self._ten_at is None or now >= self._ten_at)
            if not paced and not wake_round:
                return []
            ran: list[str] = []
            for t in self.ticks:
                if (t.pace == "paced" and not paced) or (t.pace == "event" and not wake_round) or (t.pace == "tenmin" and not ten):
                    continue
                if t.board and self._held():
                    with self._status_lock:
                        self._state[t.name]["skipped"] += 1
                    continue
                self._run_one(t)
                ran.append(t.name)
            end = self.clock()
            if wake_round:
                try:
                    w = float(self.wake_wait())
                except Exception as e:  # noqa: BLE001
                    print(f"{self.label}: wake wait not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
                    w = WAKE_MAX
                self._wake_at = end + min(max(w, WAKE_MIN), WAKE_MAX)
            if paced:
                self._pace_end = end
            if ten:
                base = now if self._ten_at is None else self._ten_at
                self._ten_at = base + self.ten_pace * (1 + int((now - base) // self.ten_pace))      # the next tenth minute after now
            with self._status_lock:
                self.rounds += 1
                self.last_round = end
            return ran

    def stalled(self, now: float | None = None) -> bool:
        """Is the runner hung: its last completed round (else its start, while no round has ended yet) is more than `STALL_AFTER` seconds old at `now` (the runner's clock when not given)?
        A runner that was never started is not stalled. A round that ends makes it False again at once. Pure reads, no lock held for long."""
        with self._status_lock:
            ref = self.last_round if self.last_round is not None else self.started
        if ref is None:
            return False
        return (self.clock() if now is None else now) - ref > STALL_AFTER

    def _held(self) -> bool:
        try:
            return bool(self.holding())
        except Exception:  # noqa: BLE001  — a hold that cannot be read does not stop the clocks
            return False

    def _run_one(self, t: Tick) -> None:
        t0 = self.clock()
        err: str | None = None
        self.current = t.name
        try:
            t.fn()
        except BaseException as e:  # noqa: BLE001  — one tick that raises never stops the next; a SystemExit or KeyboardInterrupt out of a tick is a failure of that tick too (the loop ends only by stop())
            err = f"{e.__class__.__name__}: {e}"
            print(f"{self.label}: {t.name} failed: {err}", file=sys.stderr, flush=True)
        self.current = ""
        ms = max(0.0, (self.clock() - t0) * 1000.0)
        if ms >= SLOW_TICK * 1000.0:
            print(f"{self.label}: {t.name} took {ms / 1000.0:.0f} s (one thread: every later tick and a due wake waited for it)", file=sys.stderr, flush=True)
        with self._status_lock:
            s = self._state[t.name]
            s["runs"] += 1
            s["last_run"], s["last_ms"] = t0, round(ms, 1)
            if err is not None:
                s["errors"] += 1
                s["last_error"], s["last_error_at"] = err[:300], t0

    # ---- the thread
    def seconds_to_next(self) -> float:
        """How long the loop may sleep: until the earlier of the next paced round and the next event round (never negative)."""
        if self._wake_at is None or self._pace_end is None:
            return 0.0                            # the first event round (and the first paced one, if the runner was never started) is due at once
        now = self.clock()
        return max(min(self._pace_end + self.pace - now, self._wake_at - now), 0.0)

    def loop(self) -> None:
        """The thread's body. Never dies on its own: a round that raises (not a tick: those are guarded) is a stderr line and the loop goes on; only stop() ends it."""
        while not self._stop.is_set():
            try:
                fired = self.wake.wait(self.seconds_to_next())
                if self._stop.is_set():
                    break
                self.wake.clear()                 # cleared before the round: a wake set while it runs brings the loop round again
                self.run_round(event=fired)
            except BaseException as e:  # noqa: BLE001  — as in _run_one: logged, and the loop goes on unless stop() was asked
                print(f"{self.label}: round failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
                if self._stop.is_set():
                    break
                self._stop.wait(WAKE_MIN)

    def start(self) -> threading.Thread:
        """Start the one thread (daemon). The first paced round comes one pace from now; the first event round at once."""
        if self.thread is not None and self.thread.is_alive():
            return self.thread
        self._stop.clear()
        now = self.clock()
        self._pace_end = now
        self._ten_at = None                          # the first paced round runs the ten-minute set, so a restart never delays it
        self._wake_at = None
        self.started = now
        self.thread = threading.Thread(target=self.loop, name=self.label, daemon=True)
        self.thread.start()
        return self.thread

    def stop(self, timeout: float = 5.0) -> bool:
        """Ask the thread to end, wake it, and wait up to `timeout` s. → True when no thread is left running. A round in progress finishes first (a tick is never cut off)."""
        self._stop.set()
        self.wake.set()
        th = self.thread
        if th is not None and th is not threading.current_thread():
            th.join(timeout)
        return th is None or not th.is_alive()

    # ---- what ran
    def status(self) -> dict[str, Any]:
        """The runner's record, for `GET /audit/status`: per tick the last run time (epoch seconds), the last error with its time, and the counts."""
        with self._status_lock:
            ticks = [{"name": t.name, "group": t.group, "pace": t.pace, **self._state[t.name]} for t in self.ticks]
            return {"enabled": True, "mode": "runner", "running": bool(self.thread is not None and self.thread.is_alive()), "started": self.started,
                    "pace_seconds": self.pace, "ten_pace_seconds": self.ten_pace, "rounds": self.rounds, "last_round": self.last_round, "ticks": ticks}
