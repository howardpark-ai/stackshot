"""liveness.py — one clock and one answer for "is this session or machine up, unreachable, or idle-live".

Before this module the question was answered in several places, each with its own copy of the clock: clients.py (is a puller online, is a hook-registered session past its
TTL, is a gone record past the horizon), fleet.py (running, gone for how long, present within the grace, dead after how long), server.py (`_idle_live`,
`_machine_unreachable`, `_session_down`, `_pane_dead`) and mover_state.py (what a pane's registry row says, and for how long it has been idle). They now live here and the old
names are the same functions (fleet.running, clients.online, mover_state.is_idle … are aliases, kept so a reader and a test that name them still resolve), so there is one definition of
each answer and one place its threshold is read.

The windows, each read at call time so a config reload is live at once, and each its own named function because the callers need different ones (none is unified with another):

    online_window()   [client] online_minutes (10): a machine is online while its puller checked in within this. Also what clients.py calls its grace
    grace()           the same number, named for the callers that mean "a gone session is still expected back": present(), machine_unreachable()
    dead_after()      [client] dead_after_minutes (60), never less than grace(): a session gone this long takes no message (pane_dead); panes come back slowly after a reboot
    session_ttl()     [client] session_ttl_hours (12): a hook-registered session with no puller behind it, quiet this long, is marked gone
    horizon()         [client] session_horizon_days (30): a gone record is forgotten after this, unless an open item names it

The answers:

    running(row) / gone_for(row, now) / present(row, now)        presence of one session row (fleet.py's view)
    puller_online(m, now)                                         a machine's own record (clients state): its puller checked in within online_window()
    machine_online_ok(machine_json)                               the view's `online.ok` as a bool
    machine_unreachable(letter, now, started)                     why a machine cannot be reached now, "" when it can or nothing is known
    idle_live(row)                                                the session is running now (a cse_ session has no row: never)
    session_down(row, stuck, started, now)                        why a session cannot move an item now, "" when it can or nothing is known
    pane_dead(row, now)                                           why a session's row is no pane to send to, "" when it may be one
    pane_row / status / is_idle / idle_since / idle_seconds / idle_for   what the CLI's registry says of an interactive pane on this box

Two readers that give different answers on the same row are kept apart on purpose, by the name of the window each reads (see the Disagreements in the pull request that
added this module): a session gone 30 minutes is not present() (grace, 10), is "not running" to session_down(), and is still a pane to pane_dead() (dead_after, 60).

Reads files only through fleet.py (imported inside the function that needs it: fleet.py imports this module). No server import, no clock but `time.time()` when a caller passes no `now`."""
from __future__ import annotations

import datetime as dt
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from stackshot.core import config as _cfg

IDLE = ("idle", "shell")


# ---------------------------------------------------------------- the windows
def online_window() -> float:
    """Seconds a machine counts as online after its puller's last check-in: [client] online_minutes (default 10)."""
    return 60.0 * float(_cfg.get("client", "online_minutes") or 10)


def grace() -> float:
    """Seconds a gone session is still expected back under the same id (a pane between its /exit and its resume), and a silent puller is not yet called unreachable.
    The same number as online_window() today; a separate name because the two callers mean different things by it and may be given different settings."""
    return 60.0 * float(_cfg.get("client", "online_minutes") or 10)


def dead_after() -> float:
    """How long a session has to be gone before a message to it is refused as sent to a dead pane: [client] dead_after_minutes (default 60), never less than grace().
    Panes come back slowly after a reboot, so the grace alone is too short for a refusal."""
    return max(grace(), 60.0 * float(_cfg.get("client", "dead_after_minutes") or 60))


def session_ttl() -> float:
    """Seconds a hook-registered session with no puller behind it lives without a sign of life: [client] session_ttl_hours (default 12)."""
    return 3600.0 * float(_cfg.get("client", "session_ttl_hours") or 12)


def horizon() -> float:
    """Seconds after which a gone session's identity is forgotten, unless an open item names it as owner: [client] session_horizon_days (default 30)."""
    return 86400.0 * float(_cfg.get("client", "session_horizon_days") or 30)


def ts(iso: Any) -> float:
    """An ISO-8601 stamp as epoch seconds; 0.0 for one that is missing or unreadable."""
    try:
        return dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


# ---------------------------------------------------------------- presence of a session row
# A row keeps a session's identity as long as the server holds it; `gone` (an ISO time) says its puller stopped reporting it. running = not gone;
# present = running, or gone for less than grace(); anything older is an identity record, never mistaken for a live session.
def running(row: Any) -> bool:
    """Reported by its puller or its hooks now (not marked gone)."""
    return isinstance(row, dict) and not row.get("gone")


def gone_for(row: Any, now: float | None = None) -> float:
    """Seconds since the session was last known running; 0.0 while it runs (an unreadable stamp counts as long gone)."""
    if not isinstance(row, dict) or not row.get("gone"):
        return 0.0
    t = ts(row["gone"])
    return float("inf") if not t else max(0.0, (time.time() if now is None else now) - t)


def present(row: Any, now: float | None = None) -> bool:
    """Running, or gone for less than grace(): a session a line can still wait for, a name still taken."""
    return isinstance(row, dict) and gone_for(row, now) <= grace()


def idle_live(row: Any) -> bool:
    """Is that session running now (its puller or hooks report it, not marked gone)? `row` is its record in the sessions index; none (a cse_ session, whose state the server
    does not know) is never live: its time is never live time."""
    return bool(row) and running(row)


# ---------------------------------------------------------------- machines
def puller_online(m: dict[str, Any], now: float | None = None) -> bool:
    """A machine's own record (clients.py's state): its puller checked in within online_window(). A machine with no puller stamp is not online."""
    return bool(m.get("puller")) and (time.time() if now is None else now) - ts(m["puller"]) <= online_window()


def reported_lately(seen: Any, now: float) -> bool:
    """A session record's `seen` is within online_window() of `now`: the machine that holds a transcript id reported it lately (clients._upsert's claim guard)."""
    return now - ts(seen) <= online_window()


def machine_online_ok(machine_json: Any) -> bool:
    """The view's verdict on a machine: its machine.json `online.ok` as a bool (False when there is no `online` record: no puller vouches for it)."""
    return bool((machine_json.get("online") or {}).get("ok"))


def machine_unreachable(letter: Any, now: float | None = None, started: float = 0.0) -> str:
    """Why a machine cannot be reached now: its puller has not checked in (machine.json online.ok false) for grace(), counted from its last check-in or `started` (this server's
    start), whichever is later (after the server's own downtime every puller reads as late until it has had its chance to check in), else ""."""
    from stackshot.fleet import fleet as _fleet  # noqa: PLC0415 — fleet.py imports this module
    on = _fleet.read(str(letter or ""), "machine").get("online") if letter else None
    if not (isinstance(on, dict) and on.get("ok") is False):
        return ""
    now = time.time() if now is None else now
    basis = max(ts(on.get("since")), started)
    return "its machine's puller is not checking in" if now - basis >= grace() else ""


def session_down(row: Any, stuck: Callable[[], str] | None = None, started: float = 0.0, now: float | None = None) -> str:
    """Why this session cannot move an item now, "" when it can or when nothing is known (a cloud session, a name the fleet does not know: never down). `row` is its record in
    the sessions index. A running pane is down when its last turn ended in an API error (`stuck()`: the caller's reading of its transcript on this box, or the `stopped` its
    puller reports from another machine) or its machine's puller is not checking in (machine_unreachable, from `started`); a pane that is not running is down once it has been
    gone past grace() (a relaunch under way is not). Presence here is read against the clock, not `now` (as before): `now` times the machine's silence only."""
    if not isinstance(row, dict) or not row:
        return ""
    if running(row):
        why = stuck() if stuck is not None else ""
        if why:
            return f"is stopped on an error ({why})"
        off = machine_unreachable(row.get("machine"), now, started)
        return f"is unreachable ({off})" if off else ""
    return "" if present(row) else "is not running (its pane is gone)"


def pane_dead(row: Any, now: float | None = None) -> str:
    """Why a session's row is no pane to send to ("" when it may be one). A pane that runs, or has been gone for less than dead_after() (never less than grace(): panes come back
    slowly after a reboot), may be one. Gone for longer on a machine whose puller is checking in (machine.json online.ok true): its pane is gone and nothing will pick a line up.
    Gone on a machine that is asleep, or one with no puller to tell (online.ok not true): it cannot be told from a pane that is merely away, so it still takes a message (queued
    or inboxed, as before). An unreadable `gone` stamp counts as long gone, for a time not known."""
    from stackshot.fleet import fleet as _fleet  # noqa: PLC0415 — fleet.py imports this module
    gone = gone_for(row, now)
    if gone < dead_after():
        return ""
    on = _fleet.read(str((row or {}).get("machine") or ""), "machine").get("online")
    if not (isinstance(on, dict) and on.get("ok") is True):
        return ""
    return f"its pane has been gone for {'a time not known' if gone == float('inf') else str(int(gone // 60)) + ' min'} while its machine is online"


# ---------------------------------------------------------------- a record's age: expiry (clients.py)
def hook_session_expired(seen: Any, now: float) -> bool:
    """A hook-registered session on a machine with no puller behind it has shown no sign of life for session_ttl(): it is marked gone."""
    return now - ts(seen) > session_ttl()


def past_horizon(gone: Any, now: float) -> bool:
    """A gone record has been gone longer than horizon(): it is forgotten, unless an open item names it as owner."""
    return now - ts(gone) > horizon()


# ---------------------------------------------------------------- an interactive pane on this box (the CLI's registry)
# What a pane's registry row says, and for how long it has had no turn running. A pane showing `busy` (a turn, or a background subagent, running) is never idle. A session this
# box does not run gives ("", 0.0): nothing can be told, and callers leave the item to the rule that needs no pane (the audit's six-hour write rule).
def pane_row(names: Iterable[str], ids: Iterable[str], sessions_dir: Path) -> tuple[float, dict[str, Any]] | None:
    """(the epoch second its status last changed, the row) of a pane on this box, from the CLI's registry in `sessions_dir`: None for a session this box does not run. Only an interactive
    pane's row counts (`kind` == "interactive": a headless `claude -p` of the same session is no pane that holds a notice), its process must be alive, and the most recently updated row
    wins. The one place every reader of the registry goes through, so two readers never disagree about which row is the pane."""
    names, ids = {n for n in names if n}, {i for i in ids if i}
    best: tuple[float, dict[str, Any]] | None = None
    try:
        files = list(Path(sessions_dir).glob("*.json"))
    except OSError:
        return None
    for f in files:
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
            if r.get("kind") != "interactive":
                continue
            if not (r.get("sessionId") in ids or r.get("name") in names):
                continue
            os.kill(int(r.get("pid")), 0)                    # a row of a process that is gone says nothing
            at = float(r.get("statusUpdatedAt") or r.get("updatedAt") or 0) / 1000.0
            if best is None or at > best[0]:
                best = (at, r)
        except Exception:  # noqa: BLE001
            continue
    return best


def status(best: tuple[float, dict[str, Any]] | None) -> tuple[str, float]:
    """(busy | idle | shell | "", the epoch second the status last changed) of a row from `pane_row`; ("", 0.0) for None."""
    return (str(best[1].get("status") or ""), best[0]) if best else ("", 0.0)


def is_idle(st: str, at: float) -> bool:
    """A turn is over: the pane's status is `idle` or `shell` (turn over, a run_in_background Bash task still running: the CLI writes `shell` instead of `idle` then), and when it changed is known."""
    return st in IDLE and bool(at)


def idle_since(st: str, at: float, *floors: float) -> float:
    """The moment idle time counts from: the latest of the status change `at` and every floor (when the item reached its mover, the previous step). 0.0 when the pane is not idle."""
    if not is_idle(st, at):
        return 0.0
    return max(float(at), *(float(f or 0) for f in floors))


def idle_seconds(st: str, at: float, now: float, *floors: float) -> float:
    """How long the pane has had no turn running at `now`, counted from `idle_since` (0.0 when it is busy, unknown or not on this box)."""
    s = idle_since(st, at, *floors)
    return max(0.0, now - s) if s else 0.0


def idle_for(who: str, sessions_dir: Path, now: float, *floors: float, resolve: Callable[[str], tuple[set[str], set[str]]] | None = None) -> tuple[str, float]:
    """(the pane's status, seconds idle) for the session `who` on this box, in one call: the audit's way in. `resolve` maps a name to (names, ids) to match rows by (the server passes its
    sessions index); the default matches the name or id as given. ("", 0.0) when the pane is not on this box."""
    names, ids = resolve(who) if resolve else ({who}, {who})
    st, at = status(pane_row(names, ids, sessions_dir))
    return st, idle_seconds(st, at, now, *floors)
