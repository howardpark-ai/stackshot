"""runner.py: the minute tick table and the background threads.

The clocks that end a wait and move work along run in one thread, `core/runner.py`'s `Runner` (one thread, one lock, paced rounds; its own docstring says how a round runs). This module holds what
the server builds around it: the table (`ticks()`: which tick runs, in which order, in which group, at which pace, under which gate), the one runner of the process and its status, the wake event
that `update` sets when a wake or a hold changes, the fleet publish step, the watchdog that tells the builder once when a round stops completing, the periodic publish loop, and `start()`, which
starts the three threads the server keeps for them (the runner's, the publish loop's and the watchdog's).

The order of the table is the order of the work: (1) the events that end a wait, then the phase sweep (the stored phase brought up to the clock), (2) the balancer (an item not started or queued for ten
minutes moves before the hand-off tick would remind its mover) and the hand-off tick, (3) the answers, (4) the fleet's clocks; then the ten-minute set: (5) the filing pass, the dates pass, the wake
catch-up, the silence tick and the archive tick. `board=True` marks a tick that reads items: it is skipped while the migration's pass holds the board.

The wake pass, the anchor pass, the wake catch-up, the wake wait and the event waits are imported from service/wakes.py and service/event_waits.py, the hand-off tick from service/handoff.py, the clients' tick and the inbox flag from service/fleet_events.py and the stall pass from service/stall_tick.py,
and called directly. What stays in server.py is the other tick functions (the phase sweep, the done check, the step proof, the balancer, the answers, the registry sync, the page-debt fallback, the filing, dates, silence and
archive passes) and the publish. The table calls each of them through `Hooks`, which server.py fills once with `install` (this module cannot import server.py: the surface sits above it). A hook is looked
up when its tick runs, so a suite that replaces the function on server.py is the one called; a suite that replaces a name of this module (`WAKE_EVENT`, `RUNNER`, `fleet_stamp`, `watchdog`) sets it here, and
one that replaces a wake, event-wait, hand-off or stall function sets it on the module that holds it.

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import datetime as dt
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from stackshot.core import config as _cfg
from stackshot.core import runner as _minute
from stackshot.core.instance import OWNER
from stackshot.fleet import fleet as _fl
from stackshot.projects import pages as _pages
from stackshot.router import routing as _routing
from stackshot.service import checks as _checks
from stackshot.service import event_waits as _evwaits
from stackshot.service import fleet_events as _fleetev
from stackshot.service import handoff as _handoff
from stackshot.service import proofs as _proofs
from stackshot.service import stall_tick as _stalltick
from stackshot.service import telling as _telling
from stackshot.service import wakes as _wakes
from stackshot.waits import watchers as _watch


@dataclass(frozen=True)
class Hooks:
    """What the minute set still reaches in server.py: the tick functions and the publish, in the names they have there without the leading underscore. server.py builds one and gives it to `install`."""
    phase_tick: Callable[[], Any]  # server._phase_tick
    balance_tick: Callable[[], Any]  # server._balance_tick
    answer_tick: Callable[[], Any]  # server._answer_tick
    roles_sync_safe: Callable[[], Any]  # server._roles_sync_safe
    pilot_fallback_tick: Callable[[], Any]  # service/page_debt.py _pilot_fallback_tick
    filing_tick: Callable[[], Any]  # server._filing_tick
    dates_tick: Callable[[], Any]  # server._dates_tick
    silence_tick: Callable[[], Any]  # server._silence_tick
    archive_tick: Callable[[], Any]  # server._archive_tick
    publish: Callable[[], Any]  # web.publish._publish
    publish_now: Callable[..., Any]  # web.publish._publish_now
    publish_every: Callable[[], float]  # web.publish._publish_every


_hooks_: Hooks | None = None


def install(hooks: Hooks) -> None:
    """Server.py gives the minute set what it still reaches there (once, at its import)."""
    global _hooks_
    _hooks_ = hooks


def _hooks() -> Hooks:
    if _hooks_ is None:
        raise RuntimeError("the minute set has no hooks installed (server.py installs them at its import)")
    return _hooks_


RUNNER: "list[_minute.Runner]" = []        # the running runner (at most one), for the status
MINUTE_STAMP: "list[float | None]" = [None]    # the fleet stamp at the last look, for the runner's publish step
WAKE_EVENT = threading.Event()     # set by update when a wake or a hold changes: the minute loop recomputes its next wake at once
RUNNER_STALL = [False]     # True while a stall episode is told: set when the builder is messaged, cleared by the first look that finds the runner current again
WATCHDOG_EVERY = 60.0      # seconds between the watchdog's looks


def fleet_stamp() -> float:
    """The newest change in the fleet's files (and the routing log: a delivered notice or a ruling moves a row's count); the runner publishes when it moves."""
    return max(max((p.stat().st_mtime for p in _fl.FLEET_DIR.glob("*/*.json")), default=0.0), _routing.stamp())


def fleet_publish() -> None:
    """The runner's last step: the board is republished when the fleet files (or the routing log) moved since the last look."""
    now = fleet_stamp()
    last = MINUTE_STAMP[0]
    if last is None or now > last:
        MINUTE_STAMP[0] = now          # taken before the publish, as an earlier look took it (last = now first), and never lowered: a publish that keeps raising is tried once per change, not every round
        if last is not None:
            _hooks().publish()


def ticks() -> "list[_minute.Tick]":
    """The minute set in its order (the module docstring says what each step is). Each lambda names its function when it runs, so a replaced function is the one called. `board=True`: skipped while the
    migration's pass holds the board (the registry sync and the clients' tick go on; the two wake passes have their own check)."""
    T = _minute.Tick
    return [
        T("wake_pass", lambda: _wakes.minute_wake_pass(), "settle", "event"),
        T("anchor_pass", lambda: _wakes.minute_anchor_pass(), "settle", "event"),
        T("phase_sweep", lambda: _hooks().phase_tick(), "settle", board=True),
        T("evwait_tick", lambda: _evwaits.evwait_tick(), "settle", board=True),
        T("check_tick", lambda: _checks.check_tick(), "settle", board=True),
        T("proof_tick", lambda: _proofs.proof_tick(), "settle", board=True),
        T("balance_tick", lambda: _hooks().balance_tick(), "handoff", board=True),
        T("handoff_tick", lambda: _handoff.handoff_tick(), "handoff", board=True),
        T("answer_tick", lambda: _hooks().answer_tick(), "answers", board=True),
        T("roles_sync_safe", lambda: _hooks().roles_sync_safe(), "fleet"),
        T("clients_tick", lambda: _fleetev.clients_tick(), "fleet"),
        T("pilot_fallback_tick", lambda: _hooks().pilot_fallback_tick(), "fleet", board=True),
        T("stall_tick", lambda: _stalltick.stall_tick(), "fleet", board=True),
        T("handback_tick", lambda: _telling.handback_tick(), "fleet", board=True),
        T("fleet_publish", lambda: fleet_publish(), "fleet"),
        T("filing_tick", lambda: _hooks().filing_tick(), "tenmin", "tenmin", board=True),
        T("dates_tick", lambda: _hooks().dates_tick(), "tenmin", "tenmin", board=True),
        T("wake_catchup", lambda: _wakes.minute_wake_catchup(), "tenmin", "tenmin", board=True),
        T("silence_tick", lambda: _hooks().silence_tick(), "tenmin", "tenmin", board=True),
        T("archive_tick", lambda: _hooks().archive_tick(), "tenmin", "tenmin", board=True),
    ]


def _new() -> "_minute.Runner":
    return _minute.Runner(ticks(), holding=lambda: _watch.holding(), wake_wait=lambda: _wakes.minute_wake_wait(), event=WAKE_EVENT)


def make() -> "_minute.Runner":
    """The runner over the table, on the wake event `update` sets; the fleet stamp is read once now."""
    try:
        MINUTE_STAMP[0] = fleet_stamp()
    except Exception as e:  # noqa: BLE001
        print(f"runner: fleet stamp not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return _new()


def status() -> dict[str, Any]:
    """The runner's record for `GET /audit/status`: per tick its last run and last error (a process that has not run the start reports a runner that has not started)."""
    return (RUNNER[0] if RUNNER else _new()).status()


def watchdog(now: float | None = None) -> str:
    """The runner's watchdog, asked by its own thread (`watchdog_loop`) every minute. A runner whose last completed round is older than runner.STALL_AFTER (3 minutes) is hung inside a tick: ONE stderr
    line and ONE message to the builder per stall (the episode is marked before the send, so a failed send is not retried every minute); the next look that finds a round completed again
    re-arms it. The message asks nothing of the owner and no board item is made. → "" (runner current, or no runner started), "told" (the message was started), "noted" (stalled, already told),
    "nobody" (no builder configured). `now` is for tests."""
    rn = RUNNER[0] if RUNNER else None
    if rn is None:
        return ""
    now = rn.clock() if now is None else now
    if not rn.stalled(now):
        RUNNER_STALL[0] = False
        return ""
    if RUNNER_STALL[0]:
        return "noted"
    RUNNER_STALL[0] = True
    ref = rn.last_round if rn.last_round is not None else rn.started
    mins = max(0.0, now - float(ref or now)) / 60.0
    cur = rn.current
    print(f"{rn.label}: stalled: no round has completed for {mins:.0f} min (a tick is blocking the one thread); the builder is told once", file=sys.stderr, flush=True)
    to = _cfg.audit_builder()
    if not to:
        return "nobody"
    _fleetev.inbox_flag_send(to, f"[stackshot] The minute set's runner has completed no round for {mins:.0f} min (its last round ended at {dt.datetime.fromtimestamp(float(ref), _pages.zone_now().tzinfo):%a %H:%M %Z}): "
                                 f"{('it is stuck in the tick ' + cur) if cur else 'no tick is running, so the loop itself is stuck'}, and no wake, anchor, event wait or hand-off runs meanwhile (GET /audit/status has each tick's last_run). "
                                 f"Sent once for this stall; nothing here is for {OWNER} and no reply is owed.")
    return "told"


def watchdog_loop(stop: "threading.Event | None" = None, every: float = WATCHDOG_EVERY) -> None:
    """The watchdog's thread, started beside the runner by `start`: a look every `every` seconds, in a thread of its own so that a stuck publish (git push, ssh probes) or a stuck
    runner never silences it. A look that raises is a stderr line. `stop` ends the loop (a test passes an Event whose wait it controls)."""
    stop = stop or threading.Event()
    while not stop.wait(every):
        try:
            watchdog()
        except Exception as e:  # noqa: BLE001
            print(f"runner watchdog failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


def publish_loop() -> None:
    """The server's own periodic publish: picks up other machines' heartbeats and the version tracker's cache expiry. It runs no wake pass of its own: the runner's ten-minute set does (`wake_catchup`), and the runner's watchdog has a thread of its own."""
    # On the dot: fire at the wall-clock multiples of [publish] every_minutes (:00 :10 :20 … for 10 min),
    # 20 s after the mark so the quarter-hour receiver check has written status.json first.
    while True:
        now = time.time()
        every = _hooks().publish_every()
        time.sleep(every - (now - 20) % every)
        _hooks().publish_now(force_versions=True)   # the timer publish always probes the fleet's versions; the version cache only serves the write-triggered publishes in between


def start() -> list[str]:
    """Start the minute set's runner and, beside it, the publish loop and the watchdog; → the names of the threads started. The timer publish starts here with the runner, never at import: a test that
    imported the module fired a publish at a 10-min mark and rebuilt its fixture registry."""
    print(f"stackshot: minute set: runner (one thread, one lock, paced rounds every {_minute.PACE:g} s)", file=sys.stderr, flush=True)
    if not RUNNER:                         # a second start in the same process reuses the runner it has (start() is a no-op while its thread lives): never a second one, never an overwritten one
        RUNNER[:] = [make()]
    RUNNER[0].start()                      # the watchers' and anchor passes at their minute, the settle events, hand-off, answers and the fleet's clocks, in that order (core/runner.py)
    threading.Thread(target=publish_loop, daemon=True).start()
    threading.Thread(target=watchdog_loop, name="runner-watchdog", daemon=True).start()   # the runner's watchdog: a look a minute, in a thread of its own (a stuck publish never silences it)
    return ["runner", "publish", "watchdog"]
