"""busy_tell.py: a long busy stretch tells the right agent once. The hourly audit line (audit/hourly.py) can go on for hours saying only that the mover's pane is in a turn, with nothing real happening on the item and nobody told;
this rule tells someone, once per stretch, and never the owner.

Part of the same rule as the hourly line and the idle hand-over (audit/hand_idle.py): that one is for an item the audit could verify NOTHING about; this one is for an item whose only verification, hour after hour, is that a pane is busy. It decides and
the server writes and sends (`server._busy_tell_tick`, run from the ten-minute audit tick after the idle hand-over). On by default (`[audit] busy_tell`), after 4 hours (`[audit] busy_tell_hours`).

  enabled() / hours()                      `[audit] busy_tell` (on unless a TOML false) and `[audit] busy_tell_hours` (default 4, never under 1), both read at use
  stretch_start(it, meta, mover, now)      where the busy stretch of a background mover's item counts from, None when it has none
  due(items, gid, now, front, queue, hrs)   {"mover", "project", "kind", "since", "lines"} when the item is to be told of now, else None
  due_all(...)                             [(gid, row)] of every such item, in id order; reads only
  told_since(meta, since) / mark(meta, now, to, kind, since)   the record `metadata.busy_tell` ({"at", "to", "kind", "since"}) that keeps the once

Two cases, told apart by who moves the item (the server's own test of a front agent, as the hourly line uses it):

  - A BACKGROUND mover. The item's audit lines since its last real activity (`silence.clock`: a step done or added, a state change, the owner's answer, a message, an event on an anchor, a write by the mover; the audit's own lines are none of these) are read,
    oldest first. A line that verified ONLY that the mover's pane is in a turn (`hourly.pane_only`: the log entry carries `pane_only`) belongs to the stretch; a line that verified anything else (a subagent, a pull request event), nothing (idle) or could
    not tell (unknown) ends it, and the stretch counts from that line. The stretch is the time since its start, the last real activity or the last line that was not pane-only, whichever is later; the item must have at least one pane-only line in it and
    its newest line must be one. At `hours()` the project's -main agent is told ONCE that the mover has looked busy that long with no other sign of progress on the item, and asked to look. An item whose newest line is idle is no case of this rule: it is the idle
    hand-over's.
  - A FRONT mover (a session the owner talks to). Its items are never handed on and its busy pane verifies them, so a long run of hourly lines is all there is to see. With no real activity for `hours()` and an audit line written since, the front agent ITSELF is told once,
    whatever the lines said. The -main agent is not told of an item a front agent holds, and the owner never is.

The once: `metadata.busy_tell.at` is the time the agent was told; the item is told of again only when a NEW stretch starts after it (its start is later than `at`: any real activity moves the clock, a line that verified something else moves the start). It is written in the
save before anything is sent (at most once: a crash between the save and the send loses the message), so it survives a restart, and an audit line is no activity, so the pass's own lines never reset it. A line dated ahead of `now` is not read, and neither is
a stretch whose newest line is older than `hand_idle.FRESH`'s span (the hourly pass is off or the item was off the agent since). The audit log keeps its last eight lines (`hourly_log.KEEP`); a stretch is judged by the lines it has.

Pure: no server import, no file, no clock read. Stdlib plus the repo's modules."""
from __future__ import annotations

from typing import Any, Callable

from stackshot.audit import audit_checks as _ac
from stackshot.audit import hourly as _hourly
from stackshot.audit import hourly_log as _log
from stackshot.audit import silence as _silence
from stackshot.core import config as _cfg
from stackshot.model import model as _model
from stackshot.waits import waiting as _wt

KEY = "busy_tell"
KIND_MAIN, KIND_FRONT = "main", "front"      # who is told: the project's -main agent (a background mover's item), or the front agent that holds the item
FRESH = _hourly.SLOW_EVERY + 900.0      # the newest line of a stretch older than this is no news (as in audit/hand_idle.py): the hourly pass is off, or the item was off the agent since


def enabled() -> bool:
    """`[audit] busy_tell` (default true): a TOML false (or any value that is not a TOML true) switches the pass off. Read at use, so a reload turns it on or off."""
    return _cfg.audit_busy_tell()


def hours() -> float:
    """`[audit] busy_tell_hours`: 4 by default, never under 1. Read at use."""
    return _cfg.audit_busy_tell_hours()


def _record(meta: dict[str, Any] | None) -> dict[str, Any]:
    r = (meta or {}).get(KEY)
    return r if isinstance(r, dict) else {}


def _stamp(v: Any) -> float:
    """A stamp as a number, 0.0 for one that is not (a bool, text, nan, nothing): a torn value is no stamp."""
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else 0.0


def told_since(meta: dict[str, Any] | None, since: float) -> bool:
    """Was the agent told at or after `since` (the start of the stretch)? Then this stretch is told of. A torn record is no record."""
    at = _stamp(_record(meta).get("at"))
    return at > 0 and at >= since


def mark(meta: dict[str, Any], now: float, to: str, kind: str, since: float) -> None:
    """The agent was told of the stretch now. Written in the save, before anything is sent."""
    meta[KEY] = {"at": now, "to": str(to or "")[:80], "kind": kind, "since": since}


def _lines(meta: dict[str, Any], clock: float, now: float) -> list[dict[str, Any]]:
    """The audit lines written after the item's last real activity and not ahead of `now`, oldest first."""
    out = [e for e in _log.log_of(meta) if e.get("kind") in (_hourly.KIND_OK, _hourly.KIND_IDLE, _hourly.KIND_UNKNOWN) and clock < e["at"] <= now]
    return sorted(out, key=lambda e: e["at"])


def stretch_start(meta: dict[str, Any], clock: float, now: float) -> tuple[float, int] | None:
    """(where the busy stretch counts from, the pane-only lines in it) of a background mover's item, None when it has none: no pane-only line since the last real activity, or the newest line is not a pane-only one."""
    since, run = clock, 0
    for e in _lines(meta, clock, now):
        if e.get("kind") == _hourly.KIND_OK and e.get("pane_only") is True:
            run += 1
        else:
            since, run = e["at"], 0
    return (since, run) if run else None


def due(items: dict[str, dict[str, Any]], gid: str, now: float, front: Callable[[Any, str], bool] | None = None,
        queue: dict[str, str] | None = None, hrs: float | None = None) -> dict[str, Any] | None:
    """The row of the open item `gid` when its stretch is long enough to be told of now (see the module doc), else None: {"mover", "project", "kind", "since", "lines"}. `front(name, project)` says who is a front agent (None reads none as front; one that raises
    reads as front: the agent holding the item is then told itself, never a guess at the -main agent), `queue` is {item: the item it is queued behind} (`silence.queued`; None reads none), `hrs` the threshold in hours (None reads `[audit] busy_tell_hours`)."""
    item = items.get(gid) or {}
    if item.get("status") != "open":
        return None
    it, meta, after_open, mover = _ac._item_view(items, gid)
    if not mover or _model.is_owner(mover) or not _silence.reading(it, mover, after_open, now, (queue or {}).get(gid, "")) or _wt.is_held(it):
        return None      # not on an agent as the board shows it (a hold, a park, a stored wait, the owner's or an outsider's move)
    clock = _silence.clock(it, mover)
    if not clock > 0:
        return None
    project = str(meta.get("project") or "")
    try:
        is_front = bool(front(mover, project)) if front is not None else False
    except Exception:  # noqa: BLE001
        is_front = True
    lines = _lines(meta, clock, now)
    if not lines or now - lines[-1]["at"] > FRESH:
        return None      # no audit line since the last real activity, or none lately: nothing says the item is being watched
    if is_front:
        since, n, kind = clock, len(lines), KIND_FRONT
    else:
        got = stretch_start(meta, clock, now)
        if got is None:
            return None
        (since, n), kind = got, KIND_MAIN
    if now - since < (_hourly.HOUR * (_cfg.audit_busy_tell_hours() if hrs is None else hrs)) or told_since(meta, since):
        return None
    return {"mover": mover, "project": project, "kind": kind, "since": since, "lines": n}


def due_all(items: dict[str, dict[str, Any]], now: float, front: Callable[[Any, str], bool] | None = None,
            queue: dict[str, str] | None = None, hrs: float | None = None) -> list[tuple[str, dict[str, Any]]]:
    """[(gid, row)] of every item to be told of now, in id order; reads only. An item that cannot be read is left out."""
    out: list[tuple[str, dict[str, Any]]] = []
    for gid in sorted(items, key=_ac._num):
        if items[gid].get("status") != "open":
            continue
        try:
            row = due(items, gid, now, front, queue, hrs)
        except Exception:  # noqa: BLE001
            continue
        if row is not None:
            out.append((gid, row))
    return out
