"""hand_idle.py: an item on an agent that has sat an hour with nothing the audit could verify goes to a free builder, and the project's -main agent is told; the owner never is.

Part of the rule that no item an agent moves goes more than an hour without an update (audit/hourly.py is the line side). The hourly audit marks an item `idle, nothing verified` (kind `audit_idle`);
this module reads that mark and decides which items are handed on. It decides and the server writes (`server._hand_idle_tick`): the move is the minute pass's own write
(`_handoff_exec` → `_handoff_write_move`, the path of the audit's orphan hand-over), so the new mover is told by the hand-off notice and the hand-off audit then clocks it like any other. Off by default
(`[audit] hand_idle`).

  enabled()                                     `[audit] hand_idle`, only a TOML true
  due(items, gid, now, front)                   {"mover", "project", "line_at", "told_none"} when the item is to be handed on now, else None
  due_all(items, now, front)                    [(gid, row)] of every such item, in id order; reads only
  busy_movers(items, now)                       the movers of the open items that are on an agent (a builder among them is not free)
  pick_free(candidates, busy, status, dead, same, frm)   the first candidate that is free, "" when none is
  mark_handed / mark_none                       the record `metadata.hand_idle` ({"handed_at", "from", "to", "none_at"}) that keeps the two limits
  handed_recently / none_told_recently          the 24-hour limits

An item is handed on when all of these hold:

  - the newest audit line on it is `idle, nothing verified` (`hourly.idle_marked`), and not older than `FRESH` (the pass writes one at least every 6 hours while the item is on an agent and silent; an older
    line means the hourly pass is off or the item was off the agent since), and nothing has moved the item since that line (`silence.clock` is not later than it: a step done, a state change, the
    mover's own write, an event on an anchor, the owner's answer all count);
  - it is open and on an agent as the board shows it, not held, and its hand-off, if it has one, was taken (an untaken hand-off is the hand-off audit's);
  - its mover is not a front agent: an item a front agent moves is the owner's work and is left where it is;
  - it was not handed on by this pass in the last 24 hours (`DAY`). An item handed on once and idle again after that may be handed again.

A builder is free when it is not the mover of any open item that is on an agent (an item it is to take counts: an untaken hand-off names it as mover) and its pane is not in a turn on this box
(`status(who) != "busy"`; a pane this box does not run reads as not busy). A name that is known to have no pane (`dead`) or whose status cannot be read is not free. The candidates are the item's project's
background agents, best first; when none of them is free, the background agents of any project whose mandate says build. With none free nothing is handed on and -main is told that none was, once per
item per 24 hours. At most `MAX_PER_TICK` items are handed on in one pass.

Pure: no server import, no file, no clock read. Stdlib plus the repo's modules."""
from __future__ import annotations

from typing import Any, Callable

from stackshot.audit import audit_checks as _ac
from stackshot.audit import hourly as _hourly
from stackshot.audit import silence as _silence
from stackshot.core import config as _cfg
from stackshot.waits import handoff as _ho
from stackshot.waits import waiting as _wt

KEY = "hand_idle"
DAY = 24 * 3600.0                 # an item is handed on by this pass once in this long; -main is told that no builder was free once in this long
MAX_PER_TICK = 3                  # items handed on in one pass of the ten-minute tick
FRESH = _hourly.SLOW_EVERY + 900.0      # an idle line older than this is no news (see the module doc)
WHY = "no activity for an hour, nothing verified"      # the reason the History line and the new mover's notice carry


def enabled() -> bool:
    """`[audit] hand_idle` (default false): only a TOML true switches the pass on. Read at use, so a reload turns it on or off."""
    return _cfg.audit_hand_idle()


def _record(meta: dict[str, Any] | None) -> dict[str, Any]:
    r = (meta or {}).get(KEY)
    return r if isinstance(r, dict) else {}


def _within(stamp: Any, now: float) -> bool:
    """Is `stamp` a time in the past that is less than `DAY` ago? A torn value (not a number, a bool, one dated ahead of now) is no stamp, so it blocks nothing."""
    return isinstance(stamp, (int, float)) and not isinstance(stamp, bool) and 0 <= now - stamp < DAY


def handed_recently(meta: dict[str, Any] | None, now: float) -> bool:
    return _within(_record(meta).get("handed_at"), now)


def none_told_recently(meta: dict[str, Any] | None, now: float) -> bool:
    return _within(_record(meta).get("none_at"), now)


def mark_handed(meta: dict[str, Any], now: float, frm: str, to: str) -> None:
    """The item was handed on now (`from` is who had it). The day's note that no builder was free is over."""
    meta[KEY] = {"handed_at": now, "from": str(frm or "")[:80], "to": str(to or "")[:80]}


def mark_none(meta: dict[str, Any], now: float) -> None:
    """No builder was free for the item now and -main was told; the last hand-over is kept."""
    meta[KEY] = {**{k: v for k, v in _record(meta).items() if k in ("handed_at", "from", "to")}, "none_at": now}


def due(items: dict[str, dict[str, Any]], gid: str, now: float, front: Callable[[Any, str], bool] | None = None) -> dict[str, Any] | None:
    """The row of the open item `gid` when it is to be handed on now (see the module doc), else None. `front(name, project)` says who is a front agent (None reads none as front)."""
    item = items.get(gid) or {}
    if item.get("status") != "open":
        return None
    it, meta, after_open, mover = _ac._item_view(items, gid)
    if _silence.reading(it, mover, after_open, now) != "agent" or _wt.is_held(it):
        return None      # not on an agent as the board shows it (a hold, a park, a stored wait, the owner's or an outsider's move), or on hold, or a record the board cannot read
    if _ho.awaiting_session(it):
        return None      # an untaken hand-off is the hand-off audit's, front agent or not
    project = str(meta.get("project") or "")
    if front is not None and front(mover, project):
        return None
    if not _hourly.idle_marked(meta, now):
        return None
    line = _hourly.last_line(meta, now)
    if line is None or now - line["at"] > FRESH or _silence.clock(it, mover) > line["at"]:
        return None      # an old line, or something moved the item after the line was written
    if handed_recently(meta, now):
        return None
    return {"mover": mover, "project": project, "line_at": line["at"], "told_none": none_told_recently(meta, now)}


def due_all(items: dict[str, dict[str, Any]], now: float, front: Callable[[Any, str], bool] | None = None) -> list[tuple[str, dict[str, Any]]]:
    """[(gid, row)] of every item that is to be handed on now, in id order; reads only. An item that cannot be read is left out."""
    out: list[tuple[str, dict[str, Any]]] = []
    for gid in sorted(items, key=_ac._num):
        if items[gid].get("status") != "open":
            continue
        try:
            row = due(items, gid, now, front)
        except Exception:  # noqa: BLE001
            continue
        if row is not None:
            out.append((gid, row))
    return out


def busy_movers(items: dict[str, dict[str, Any]], now: float) -> list[str]:
    """The movers of the open items that are on an agent as the board shows them (a hold and a stored wait are not), whatever else is true of them. An item that cannot be read is left out."""
    out: list[str] = []
    for gid in items:
        if items[gid].get("status") != "open":
            continue
        try:
            it, _meta, after_open, mover = _ac._item_view(items, gid)
            if mover and _silence.reading(it, mover, after_open, now) and not _wt.is_held(it):
                out.append(mover)
        except Exception:  # noqa: BLE001
            continue
    return out


def pick_free(candidates: list[str], busy: list[str], status: Callable[[str], str], dead: Callable[[str], str], same: Callable[[Any, Any], bool], frm: str = "") -> str:
    """The first of `candidates` that is free (see the module doc), "" when none is. `status(who)` → the pane's registry status ("busy", "idle", "shell", "" unknown); `dead(who)` → why the name has no
    pane ("" when it may have one); one that raises leaves the name out. `frm` (the item's present mover) is never picked."""
    for c in candidates:
        if not c or (frm and same(c, frm)) or any(same(c, m) for m in busy):
            continue
        try:
            if status(c) == "busy" or dead(c):
                continue
        except Exception:  # noqa: BLE001
            continue
        return c
    return ""
