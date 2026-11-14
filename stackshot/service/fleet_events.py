"""fleet_events.py: what the fleet's own clocks do once a minute, and the helpers they share.

The runner's `clients_tick` (a puller that stopped checking in makes its machine offline, fleet/clients.py) and, in the same tick, the inbox flag: a line that waits in a session's inbox for [client]
inbox_flag_minutes (default 5; 0 turns it off) while the session shows a sign of life (not marked gone, on a machine whose puller checks in: inbox.alive) is reported once, to the session that sent it (a running
pane) and to the fleet's builder (`fleet_builder`: the fleet operator, else the keeper of its project when it is retired), with the likeliest reason (inbox.why). The journal gets the line too. `fleet_names` is the
letter to fleet name map the board's messages and the sessions tool use.

The only thing they still reach in server.py is the time zone, through `Hooks` in service/passes_hooks.py. A suite that replaces a function of the pass (`inbox_flag_send`, `fleet_builder`) or its state
(`INBOX_FLAG_LAST`, `INBOX_FLAG_START`) sets it here, and the runner's watchdog and the recovery rung call these names here as well.

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
import sys
import threading
import time
from typing import Any

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core import interp as _interp
from stackshot.core.instance import NAME
from stackshot.fleet import clients as _clients
from stackshot.fleet import fleet as _fleet
from stackshot.fleet import inbox as _inbox
from stackshot.fleet import liveness as _lv
from stackshot.fleet.sessions_registry import _sessions_index
from stackshot.service import telling as _telling
from stackshot.service.passes_hooks import hooks as _hooks


def clients_tick() -> None:
    """The server's own clients, as time passes: a puller that stopped checking in makes its machine offline (clients.py)."""
    _clients.tick()
    try:
        inbox_flag_tick()     # its own clock, below; it reads no item, so it goes on while a migration holds the board
    except Exception as e:  # noqa: BLE001  — the flag is an extra: the clients' tick above has run
        print(f"inbox: flag pass failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


# ----------------------------------------------------------------------------- a line that waits too long in the inbox
# A message can wait in a session's inbox while the pane runs and
# takes other lines; the sender was told "waits in the server's inbox: the session is away" and nothing said otherwise later. A line that waits for a session that shows
# a sign of life (not marked gone, on a machine whose puller checks in: inbox.alive) for [client] inbox_flag_minutes (default 5; 0 turns it off) is reported once: to the session that
# sent it (a running pane), and to the fleet's builder (fleet_builder: the fleet operator, else the keeper of its project when it is retired), with the likeliest reason (inbox.why). The journal gets the line too.
INBOX_FLAG_EVERY = 60.0     # seconds between passes; the runner calls it every 60 s
INBOX_FLAG_LAST = [0.0]
INBOX_FLAG_START = [time.time()]     # the server's start: the first pass waits one poll period (clients.POLL_MAX) and a margin
INBOX_FLAG_LINES = 5                 # at most this many lines in one sender's flag, then "+N more"


def inbox_flag_minutes() -> float:
    try:
        return float(_cfg.get("client", "inbox_flag_minutes", default=5))
    except (TypeError, ValueError):
        return 5.0


def inbox_flag_send(to: str, text: str) -> "threading.Thread":
    """One flag line to a session through push.py in the background (as the wake pass sends); a failure is a stderr line. → the thread (a test joins it)."""
    def run() -> None:
        try:
            r = subprocess.run([*_interp.resilient(_telling.PUSH), "--from", NAME, to, text], capture_output=True, text=True, timeout=110,
                               env={**os.environ, "ANCHOR_PUSH_SOURCE": "msg"})
            out = (r.stdout.strip().splitlines() or [""])[-1]
            if not out.startswith(("delivered", "queued", "inbox")):
                print(f"inbox: flag to {to} not delivered: {out or 'no result'}{(' — ' + r.stderr.strip().splitlines()[-1]) if r.stderr.strip() else ''}", file=sys.stderr, flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"inbox: flag to {to} failed: {e}", file=sys.stderr, flush=True)
    th = threading.Thread(target=run, daemon=True)
    th.start()
    return th


def inbox_flag_tick(now: float | None = None) -> list[str]:
    """One pass of the flag (see above). → the sessions told. `now` is for tests."""
    mins = inbox_flag_minutes()
    now = time.time() if now is None else now
    if mins <= 0 or now - INBOX_FLAG_LAST[0] < INBOX_FLAG_EVERY or now - INBOX_FLAG_START[0] < _clients.POLL_MAX + 15:
        return []        # not before every puller has polled again since the server started: the machines' rows come back at their next check-in
    INBOX_FLAG_LAST[0] = now
    late = _inbox.new_overdue(mins * 60.0, now, skip_from=(NAME,))     # the flag's own lines are sent from NAME: never flagged in their turn
    if not late:
        return []
    idx = _sessions_index()
    running = {str(r.get("name")) for r in idx.values() if r.get("name") and _lv.running(r)}
    keeper = fleet_builder()
    at = lambda ts: dt.datetime.fromtimestamp(ts, _hooks().zone()).strftime("%H:%M")
    groups: dict[str, list[dict[str, Any]]] = {}
    for it in late:
        groups.setdefault(str(it.get("name") or it.get("to")), []).append(it)
        print(f"inbox: line {it['id']} for {it.get('name') or it.get('to')} (from {it.get('from') or '?'}, put {at(float(it['ts']))} {_cfg.tz_abbr()}) has waited {int(it['age'] // 60)} min though the session runs: {it['why']}",
              file=sys.stderr, flush=True)
    told: list[str] = []
    senders: dict[str, list[str]] = {}
    for target, its in groups.items():
        for it in its:
            m = re.match(r"[A-Za-z0-9][\w.-]*", str(it.get("from") or ""))
            if m and m.group(0) in running and m.group(0) != target:
                senders.setdefault(m.group(0), []).append(f"to {target} ({at(float(it['ts']))} {_cfg.tz_abbr()}): {it['why']}")
    for who, lines in senders.items():
        shown = lines[:INBOX_FLAG_LINES] + ([f"+{len(lines) - INBOX_FLAG_LINES} more"] if len(lines) > INBOX_FLAG_LINES else [])
        inbox_flag_send(who, f"[stackshot] {len(lines)} of your message(s) {'is' if len(lines) == 1 else 'are'} still in the server's inbox after {mins:g} min, though the session {'runs' if len(lines) == 1 else 'run'}: "
                              + "; ".join(shown) + (f". {keeper} has been told." if keeper and keeper != who else "."))
        told.append(who)
    if keeper:
        parts = [f"{len(its)} line(s) for {target}, from " + ", ".join(sorted({str(i.get('from') or '?') for i in its})) + f" (the oldest put {at(min(float(i['ts']) for i in its))} {_cfg.tz_abbr()}): {its[0]['why']}" for target, its in groups.items()]
        parts = parts[:INBOX_FLAG_LINES] + ([f"+{len(parts) - INBOX_FLAG_LINES} more session(s)"] if len(parts) > INBOX_FLAG_LINES else [])
        inbox_flag_send(keeper, f"[stackshot] Lines are waiting in the server's inbox for running sessions (more than {mins:g} min): " + "; ".join(parts)
                                 + ". Usual causes: two sessions carrying one name, a puller that is not taking them (a line held on purpose, by a relaunch hold or a pause, is not reported). They are in the inbox until a puller takes them; nothing is lost.")
        told.append(keeper)
    else:
        print("inbox: nobody to tell about the waiting lines ([fleet] operator_session is unset or retired with no keeper)", file=sys.stderr, flush=True)
    return told


def fleet_builder() -> str:
    """The session a fleet recovery is asked of: the fleet operator ([fleet] operator_session, the session that runs the fleet: the builder of the fleet's tool), or, when that session
    is retired, the keeper of its project. "" when none resolves (then the History line and the journal say nobody was asked). A retired operator with no project is never sent to."""
    op = str(_cfg.get("fleet", "operator_session") or "").strip()
    if not op:
        return ""
    try:
        r = _anc.session_roles().get(op) or {}
    except Exception:  # noqa: BLE001
        r = {}
    if r.get("retired"):
        return _telling.page_keeper(str(r.get("project") or "")) if r.get("project") else ""
    return op


def fleet_names() -> dict[str, str]:
    """letter → fleet name, from each machine's live state (a letter with no state stays a letter)."""
    return {L: _fleet.read(L, "machine").get("fleet") or L for L in _fleet.letters()}
