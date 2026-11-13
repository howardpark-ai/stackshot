"""silence.py: the shared readings of an item's quiet time, kept for the hourly audit line (audit/hourly.py), the idle hand-over (audit/hand_idle.py), the stall ladder and the dates pass's ladder entry (server.py).

This file once held the ten-minute silence pass, the 45-minute news ask. The hourly audit line and the idle hand-over replace it, and the file keeps its name so the passes that import it keep working. What stays:

  reading(item, mover, after_open, now, behind)   how the board stands toward an open item: "agent", "unreadable" or "" (not on an agent: no session mover, the owner's move, or the board shows it waiting)
  clock(item, mover)                              where the item's quiet time is counted from: its last activity, or the moment it left a hold, a wait or an after link, or the moment a front-step move made the step its mover's
  queued(items, now, env)                         {item: the item it is queued behind} for a mover busy on another of its items (model/queued.py)
  subagent_running(item, now, mover, same)        is a build subagent running on the item, by its own step statuses (a status in progress, changed within `SUBAGENT_S`)
  minutes(secs)                                   a span for an evidence line

An item is on an agent when it is open, a session is its mover, its state is not the owner's move and the board's own phase, `model.shown_waiting`, is not waiting. What the board shows as waiting (a hold with a dated wake, an open `after` item, a stored wait: a release, a CI run or any other event, a relay, an outside party, a wake that carries a wait_basis) is not on an agent; a wake kept as a hand-off's backstop (no until, no basis) leaves the item on agent. An item whose record the board's model cannot read is on an agent as the board lists it (`home.classify`). An item whose mover is busy on another of its items is queued behind that item, which the board lists under Waiting. Quiet time is judged per item, never per pane: what counts as activity is the clock's (`activity.at`: a step done or added, a state change, the owner's answer, a message written onto the item, an event on one of its anchors); an audit's own write and a bare confirm do not move it. A subagent's work that writes nothing to the item is not activity, so a builder keeps a long job visible by writing it onto the item (a step status, an update). Stdlib plus the repo's modules."""
from __future__ import annotations

from typing import Any

from stackshot.model import activity as _act  # noqa: E402
from stackshot.audit import audit_checks as _ac  # noqa: E402
from stackshot.audit import audit_run as _ar  # noqa: E402
from stackshot.audit import front_step as _fs  # noqa: E402
from stackshot.model import model as _model  # noqa: E402
from stackshot.model import queued as _queued  # noqa: E402
from stackshot.model import states as _states  # noqa: E402
from stackshot.model import work as _work  # noqa: E402

SUBAGENT_S = 90 * 60.0    # a step status in progress counts as a running build subagent for this long after it was last changed (a pane recycle stops subagents and leaves the line behind)


def minutes(secs: float) -> str:
    """A span for the evidence line: minutes up to four hours, past that hours and minutes ("30 hours 5 minutes")."""
    m = int(secs // 60)
    if m < 240:
        return f"{m} minutes"
    h, r = divmod(m, 60)
    return f"{h} hours" + (f" {r} minute{'s' if r != 1 else ''}" if r else "")


def _step_mover(item: dict[str, Any], mover: str) -> tuple[dict[str, Any], str]:
    """(the item's metadata, its first open step) for the front-step record's checks."""
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return meta, _ac.first_open_step(meta) or ""


def clock(item: dict[str, Any], mover: str = "") -> float:
    """Where the item's quiet time is counted from: its last activity, or the moment it left a hold, a wait or an after link if that is later. Those releases are saved by the server with no writer, which
    the activity clock counts as bookkeeping, so an item parked for a day would read as long quiet the round it wakes; its time counts from when it is due again. A step the front-step rule moved to `mover`
    counts from the move too (front_step.landed_at): the server's move is no activity, and the mover is given its time from the moment the step became its own."""
    try:
        left = float(item.get("state_updated") or 0)
    except (TypeError, ValueError):
        left = 0.0
    meta, step = _step_mover(item, mover)
    return max(_act.at(item), left, _fs.landed_at(meta, step, mover, _act.at(item)) or 0.0)


def reading(item: dict[str, Any], mover: str, after_open: Any, now: float, behind: str = "") -> str:
    """How the board stands toward the open item: "agent" (it shows the item on an agent), "unreadable" (the board's model raises on the item, and `home.classify` puts such an item on an agent rather than drop it),
    or "" (not on an agent: the mover is no session, the state is the owner's move, or the board shows it waiting). `behind` is the item this one is queued behind when its mover is busy on that one (`queued`,
    model/queued.py): the board lists it under Waiting, so it is not on an agent here either."""
    try:
        if _ac._no_session(mover) or _states.of(item, after_open)[0] in _model.OWNER_STATES:
            return ""
        return "" if behind or _model.shown_waiting(item, now, after_open) else "agent"
    except Exception:  # noqa: BLE001
        return "" if _ac._no_session(mover) else "unreadable"


def queued(items: dict[str, dict[str, Any]], now: float, env: Any = None) -> dict[str, str]:
    """{item: the item it is queued behind} over the open items (model/queued.py), {} when `[model] queued_behind` is off. The candidates are the items the board shows on an agent (`reading`); `env.is_front` says who
    is a front agent. The passes read it once per round and hand each item's answer to `reading`; reads only."""
    if not _queued.enabled():
        return {}
    e = env if hasattr(env, "is_front") else _ar.Env()
    front = getattr(e, "is_front_safe", e.is_front)      # a front test that cannot answer counts as front: nothing is queued on a guess
    cands = []
    for gid in sorted(items, key=_ac._num):
        if items[gid].get("status") != "open":
            continue
        it, _meta, after_open, mover = _ac._item_view(items, gid)
        if reading(it, mover, after_open, now) == "agent":
            cands.append(_queued.candidate(gid, it, mover, now))
    return _queued.queue(cands, now, front)


def subagent_running(item: dict[str, Any], now: float, mover: str = "", same: Any = None) -> bool:
    """Is a build subagent running on this item, by the item's own step statuses? A status in progress, last changed within `SUBAGENT_S`, is a build subagent the mover started on it. The hand-over and the stall ladder
    ask it of an item whose mover is a builder; a status that is only defined or assigned, a done one, and one older than the bound are not a subagent running.
    With `mover` given (the stall pass's hold of a background agent's ladder), only a status on a step that opens with that session's name counts, `same(a, b)` saying whether two names are one session: a stale status
    another agent left in progress says nothing about the mover being chased. The agent of a status is the session its step opens with."""
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    own = (lambda l: bool(same(l["agent"], mover)) if same else str(l["agent"]).casefold() == str(mover).casefold()) if mover else (lambda l: True)
    return any(0 < now - l["ts"] <= SUBAGENT_S for l in _work.in_progress(meta) if l["ts"] > 0 and own(l))
