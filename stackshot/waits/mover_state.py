"""mover_state.py — one engine for "who moves this item, and has that session had a turn running".

The stall pass (stall.py, service/stall_tick.py) and the audit (audit_run.py) ask the same two questions of an open item: which session moves it,
and is that session idle, for how long. This module answers them in one place, so the two never disagree. Through liveness.py it reads the CLI's own registry (`~/.claude/sessions/<pid>.json`, the files
push.py reads too) and decides nothing about what to do next; the stall pass acts on the answer, the audit reports it.

    (pane_row, status, is_idle, idle_since and idle_seconds below are defined in liveness.py and re-exported here; mover() is this module's own.)

    mover(item, derive)                 the item's effective mover ("" for a closed or waiting item): the item model's reading (handoff.mover_of)
    pane_row(names, ids, sessions_dir)  (epoch its status last changed, the row) of the interactive pane of a session on this box, else None
    status(row)                         (busy | idle | shell | "", epoch) for a row from pane_row (or None)
    is_idle(status, at)                 a turn is over: `idle`, or `shell` (turn over, a run_in_background Bash task still running: the CLI writes `shell` instead of `idle` then)
    idle_since(status, at, *floors)     when the idle time counts from: the latest of the status change and the floors (the item reaching its mover, the previous step); 0.0 when not idle
    idle_seconds(status, at, now, *floors)   how long the session has had no turn, counting from idle_since (0.0 when it is busy, unknown or not on this box)

A pane showing `busy` (a turn, or a background subagent, running) is never idle. A session this box does not run gives ("", 0.0): nothing can be told, and callers leave the item to
the rule that needs no pane (the audit's six-hour write rule). The server keeps the name and id resolution (it knows the sessions index) and passes the sessions folder at call time.

The pane half is liveness.py's (one clock, one answer for every liveness reading); this module keeps the mover and re-exports the pane names. Stdlib and config.py only."""
from __future__ import annotations

from typing import Any, Callable

from stackshot.fleet import liveness as _lv

# The pane half (what the CLI's registry says of a pane on this box, and for how long it has had no turn) is liveness.py's: one clock, one answer. These names stay so a reader
# and a test that name them through mover_state resolve to the same functions.
IDLE = _lv.IDLE
pane_row = _lv.pane_row
status = _lv.status
is_idle = _lv.is_idle
idle_since = _lv.idle_since
idle_seconds = _lv.idle_seconds
idle_for = _lv.idle_for


def mover(item: dict[str, Any] | None, derive: Callable[[dict[str, Any]], Any]) -> str:
    """The item's effective mover ("" for a closed one, a waiting one, or a reading that fails): the item model's, through handoff.mover_of."""
    from stackshot.waits import handoff as _ho  # noqa: PLC0415 — kept out of the module's import time: the pure helpers below need nothing
    return _ho.mover_of(item, derive)
