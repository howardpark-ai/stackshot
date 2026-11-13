"""hand_idle.py: an item on an agent that has sat an hour with nothing the audit could verify goes to a free builder, and the project's -main agent is told; the owner never is.

Part of the rule that no item an agent moves goes more than an hour without an update (audit/hourly.py is the line side). The hourly audit marks an item `idle, nothing verified` (kind `audit_idle`);
this module reads that mark and decides which items are handed on. It decides and the server writes (`server._hand_idle_tick`): the move is the minute pass's own write
(`_handoff_exec` → `_handoff_write_move`, the path of the audit's orphan hand-over), so the new mover is told by the hand-off notice and the hand-off audit then clocks it like any other. On by default
(`[audit] hand_idle`).

  enabled()                                     `[audit] hand_idle`, on unless a TOML false
  due(items, gid, now, front)                   {"mover", "project", "line_at", "told_none"} when the item is to be handed on now, else None
  due_all(items, now, front)                    [(gid, row)] of every such item, in id order; reads only
  busy_movers(items, now)                       the movers of the open items that are on an agent (a builder among them is not free)
  pick_free(candidates, busy, status, dead, same, frm)   the first candidate that is free, "" when none is
  mark_handed / mark_none                       the record `metadata.hand_idle` ({"handed_at", "from", "to", "none_at"}) that keeps the two limits
  handed_recently / none_told_recently          the 24-hour limits

An item is handed on when all of these hold:

  - the newest audit line on it is `idle, nothing verified` (`hourly.idle_marked`: kind `audit_idle` alone; a line that could not tell, kind `audit_unknown`, because a running subagent of the mover is tied to no item or the subagents could not be read, is no idle mark and the item stays), and not older than `FRESH` (the pass writes one at least every 6 hours while the item is on an agent and silent; an older
    line means the hourly pass is off or the item was off the agent since), and nothing has moved the item since that line (`silence.clock` is not later than it: a step done, a state change, the
    mover's own write, an event on an anchor, the owner's answer all count), and it has had no activity for a full hour (`hourly.HOUR`): the first audit line is owed after 45 minutes (`hourly.EVERY`), so an idle line can be younger than an hour of silence, and the item waits for the hour before it is handed on;
  - it is open and on an agent as the board shows it, not held, and its hand-off, if it has one, was taken (an untaken hand-off is the hand-off audit's);
  - its mover is not a front agent: an item a front agent moves is the owner's work and is left where it is;
  - it was not handed on by this pass in the last 24 hours (`DAY`). An item handed on once and idle again after that may be handed again.

A builder is free when it is not the mover of any open item that is on an agent (an item it is to take counts: an untaken hand-off names it as mover) and its pane is not in a turn on this box
(`status(who) != "busy"`; a pane this box does not run reads as not busy). A name that is known to have no pane (`dead`) or whose status cannot be read is not free. The candidates are the item's project's
background agents, best first; when none of them is free, the background agents of any project whose mandate says build. With none free nothing is handed on and -main is told that none was, once per
item per 24 hours. At most `MAX_PER_TICK` items are handed on in one pass.

THE BALANCER (`[audit] balance`, on by default; `server._balance_tick`, its own minute tick ahead of the hand-off tick). The same module decides, the server writes. An item that is NOT STARTED (an untaken hand-off to a
builder) or QUEUED BEHIND its mover's other item and has waited `[audit] balance_minutes` (default 10) goes to the builder of its OWN PROJECT with the FEWEST open items; the former mover is told to disregard it.

  balance_enabled() / balance_minutes()         `[audit] balance` (on unless a TOML false) and `[audit] balance_minutes` (default 10, floor 1), both read at use
  balance_queue(items, now, window, front)      the queue rule (model/queued.py) read over the balancer's own window, whatever `[model] queued_behind` says: {queued item: the item it waits behind}
  balance_due(items, gid, now, minutes, front, behind, same, anchored, builder)    the row of an item to move now, else None
  balance_all(...)                              [(gid, row)] in id order; reads only
  load_counts / load_of / shift                 open items per builder (`busy_movers`, names merged with `same`), updated as the pass moves items
  pick_least(...) / balance_ok(kind, to, frm)   the least-loaded builder, and whether moving to it is an improvement
  mark_balanced / mark_balance_none / mark_balance_capped    the record `metadata.balance` ({"at", "from", "to", "count"} and `none_at` / `capped_at`), apart from `metadata.hand_idle`

An item is moved when all of these hold:

  - it is open, on an agent as the board shows it (`silence.reading`), not held, and its mover is a BUILDER (`builder(name)`: a background agent whose mandate says build, maintain, merge or engineer; a reviewer's or any other
    session's item is never balanced) and no front agent;
  - it waited the whole time: its hand-off (when its latest one names the mover) was delivered, else made, at least `balance_minutes` ago, and `silence.clock` is that old too;
  - it is NOT STARTED (an untaken hand-off to a session, `handoff.awaiting_session`) or QUEUED (`balance_queue`: the mover has another item in hand with activity inside the window and this one has none);
  - the mover has NOT STARTED it: no `taken_at` (in the latest hand-off to it, nor in `handoff_history`), no step status in progress or done and no step marked done on a step that opens with the mover's name, no subagent running (`silence.subagent_running`), no anchor scoped to it, and
    no pull request event (a CI result, review, comment, merge or commit) as its last activity;
  - it was not moved by the idle hand-over (`metadata.hand_idle`) nor by the balancer in the last 24 hours and has been moved fewer than `BALANCE_LIFETIME` (2) times; one at the lifetime cap is left to the ladders, and -main is told once (`capped_at`).

Which builder: the candidates are the builders only (`server._balance_builders`: the item's own project's background agents whose mandate says build, maintain, merge or engineer, and no other project's) less any whose pane
is known dead, the item's own mover, every name in the hand-off record's `tried` and any front agent; the pick is the one with the fewest open items (a busy pane only breaks a tie: an idle one first; then the candidates' order).
The move must improve the spread, the mover's count including the item: an untaken hand-off moves when `to == 0 or to + 1 < from` (a lone item goes to an empty builder; a swap does not happen), a queued item only when
`to + 1 < from`. At most `BALANCE_MAX_PER_TICK` (3) items are moved in a pass. With NO eligible candidate (no live builder) the item stays, one History line says so and -main is told once per item per 24 hours (`none_at`; the pass looks again every minute, so a builder that comes back is used at once and its move ends the note) and ONLY when the role map holds another builder than the mover, which is dead or gone (`balance_others`): with no
other builder, or a pick that is no improvement, it is silent (a log line only). A project whose only builder is the mover therefore keeps its item, however idle another project's builders are.

Pure: no server import, no file, no clock read. Stdlib plus the repo's modules."""
from __future__ import annotations

from typing import Any, Callable, Iterable

from stackshot.audit import audit_checks as _ac
from stackshot.audit import hourly as _hourly
from stackshot.audit import silence as _silence
from stackshot.core import config as _cfg
from stackshot.model import last_activity as _la
from stackshot.model import model as _model
from stackshot.model import queued as _queued
from stackshot.model import steps as _steps
from stackshot.model import work as _work
from stackshot.waits import handoff as _ho
from stackshot.waits import waiting as _wt

KEY = "hand_idle"
DAY = 24 * 3600.0                 # an item is handed on by this pass once in this long; -main is told that no builder was free once in this long
MAX_PER_TICK = 3                  # items handed on in one pass of the ten-minute tick
FRESH = _hourly.SLOW_EVERY + 900.0      # an idle line older than this is no news (see the module doc)
BALANCE_KEY = "balance"
BALANCE_MAX_PER_TICK = 3          # items the balancer moves in one pass
BALANCE_LIFETIME = 2              # moves of one item by the balancer, ever: after that the existing ladders have it
PR_KINDS = (_la.CI_RESULT, _la.REVIEW, _la.COMMENT, _la.PR_MERGED, _la.COMMIT)      # the kinds of `last_activity` that are an event on a tied pull request: a build is in flight
WHY = "no activity for an hour, nothing verified"      # the reason the History line and the new mover's notice carry


def enabled() -> bool:
    """`[audit] hand_idle` (default true): a TOML false (or any value that is not a TOML true) switches the pass off. Read at use, so a reload turns it on or off."""
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
    if now - _silence.clock(it, mover) < _hourly.HOUR:
        return None      # the first audit line is owed after 45 minutes, inside the hour: an item is handed on only after a full hour without activity, as it was when the first line itself waited for the hour
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


# ---------------------------------------------------------------------------------------------------------------- the balancer
def balance_enabled() -> bool:
    """`[audit] balance`, on unless a TOML false. Read at use."""
    return _cfg.audit_balance()


def balance_minutes() -> float:
    """`[audit] balance_minutes`: 10 by default, never under 1. Read at use."""
    return _cfg.audit_balance_minutes()


def _brec(meta: dict[str, Any] | None) -> dict[str, Any]:
    r = (meta or {}).get(BALANCE_KEY)
    return r if isinstance(r, dict) else {}


def _num(v: Any) -> float:
    """A stamp as a number, 0.0 for one that is not (a bool, text, nothing): a torn value is no signal."""
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else 0.0


def balance_count(meta: dict[str, Any] | None) -> int:
    """How often the balancer moved the item (a torn count reads as 0)."""
    c = _brec(meta).get("count")
    return c if isinstance(c, int) and not isinstance(c, bool) and c > 0 else 0


def balanced_recently(meta: dict[str, Any] | None, now: float) -> bool:
    return _within(_brec(meta).get("at"), now)


def balance_none_told_recently(meta: dict[str, Any] | None, now: float) -> bool:
    return _within(_brec(meta).get("none_at"), now)


def balance_capped_told(meta: dict[str, Any] | None) -> bool:
    return _num(_brec(meta).get("capped_at")) > 0


def mark_balanced(meta: dict[str, Any], now: float, frm: str, to: str) -> None:
    """The item was moved by the balancer now: `count` goes up by one; the day's notes that no builder was found are over. Written in the save of the move itself, before anything is sent."""
    meta[BALANCE_KEY] = {"at": now, "from": str(frm or "")[:80], "to": str(to or "")[:80], "count": balance_count(meta) + 1}


def _kept(meta: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in _brec(meta).items() if k in ("at", "from", "to", "count", "capped_at")}


def mark_balance_none(meta: dict[str, Any], now: float) -> None:
    """No builder could take the item now and -main was told; the last move is kept."""
    meta[BALANCE_KEY] = {**_kept(meta), "none_at": now}


def mark_balance_capped(meta: dict[str, Any], now: float) -> None:
    """The item is at its lifetime cap, left to the ladders, and -main was told once."""
    meta[BALANCE_KEY] = {**_kept(meta), "capped_at": now}


def started_reason(item: dict[str, Any], mover: str, now: float, same: Callable[[Any, Any], bool], anchored: Callable[[dict[str, Any]], bool] | None = None) -> str:
    """Why the mover is taken to have STARTED the item ("" when it has not): the hand-off was taken, a step opening with the mover's name has a status in progress or done or is marked done, a subagent is running on it,
    an anchor is scoped to it, or a pull request event is its last activity. Such an item is never taken from its mover."""
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    r = _ho.record_of(item)
    if r and r.get("taken_at") and same(r.get("to"), mover):
        return "its hand-off was taken"
    hist = meta.get(_ho.HISTORY)
    if any(isinstance(h, dict) and h.get("taken_at") and same(h.get("to"), mover) for h in (hist if isinstance(hist, list) else [])):
        return "an earlier hand-off to it was taken"      # the latest record may be missing, torn or another session's: what the mover took before still counts
    if any(l["state"] in ("in progress", "done") and same(l["agent"], mover) for l in _work.lines_of(meta)):
        return "a step of the mover has a status in progress or done"
    if any(s["status"] == _steps.DONE and same(_steps.opener(s["text"]), mover) for s in _steps.view(meta)):
        return "a step of the mover is marked done"
    if _silence.subagent_running(item, now):
        return "a subagent is running"
    if anchored is not None and anchored(item):
        return "an anchor is scoped to it"
    la = _la.read(item, now)
    if la and la.get("kind") in PR_KINDS:
        return "a pull request event is its last activity"
    return ""


def balance_queue(items: dict[str, dict[str, Any]], now: float, window: float, front: Callable[[Any, str], bool] | None = None) -> dict[str, str]:
    """{queued item: the item it is queued behind} over the open items the board shows on an agent, by the queue rule of model/queued.py read over `window` seconds, whatever `[model] queued_behind` says (the balancer reads the
    queue itself; the board's reading stays at an hour). An item that cannot be read is no candidate."""
    cands = []
    for gid in sorted(items, key=_ac._num):
        if items[gid].get("status") != "open":
            continue
        try:
            it, _meta, after_open, mover = _ac._item_view(items, gid)
            if _silence.reading(it, mover, after_open, now) == "agent" and not _wt.is_held(it):
                cands.append(_queued.candidate(gid, it, mover, now))
        except Exception:  # noqa: BLE001
            continue
    return _queued.queue(cands, now, front, window)


def balance_due(items: dict[str, dict[str, Any]], gid: str, now: float, minutes: float, front: Callable[[Any, str], bool] | None, behind: dict[str, str], same: Callable[[Any, Any], bool],
                anchored: Callable[[str, dict[str, Any]], bool] | None = None, builder: Callable[[str], bool] | None = None) -> dict[str, Any] | None:
    """The row of the open item `gid` when the balancer is to move it now (see the module doc), else None: {"mover", "project", "kind" ("untaken" | "queued"), "tried", "told_none", "capped"}. `behind` is the queue
    (`balance_queue`); `anchored(gid, item)` says whether an anchor is scoped to the item; `builder(name)` says whether the mover is a builder (None reads every session as one). A row with `capped` true is an item at its lifetime cap whose -main agent is not yet told: it is not to be moved."""
    item = items.get(gid) or {}
    if item.get("status") != "open":
        return None
    it, meta, after_open, mover = _ac._item_view(items, gid)
    if not mover or _model.is_owner(mover) or _silence.reading(it, mover, after_open, now) != "agent" or _wt.is_held(it):
        return None
    project = str(meta.get("project") or "")
    if front is not None and front(mover, project):
        return None      # an item a front agent moves is the owner's work, never moved
    if builder is not None and not builder(mover):
        return None      # a reviewer's (or any non-builder's) item is not the balancer's to move
    window = max(_num(minutes), 0.0) * 60.0
    rec = _ho.record_of(it)
    if rec and not same(rec.get("to"), mover):
        rec = None      # an older hand-off, to someone else: it says nothing about this mover
    if rec:
        since = _num(rec.get("delivered_at")) or _num(rec.get("at"))
        if since <= 0 or now - since < window:
            return None      # a hand-off waits the whole time from its delivery
    if now - _silence.clock(it, mover) < window:
        return None
    if _ho.awaiting_session(it, mover, same):
        kind = "untaken"
    elif gid in behind:
        kind = "queued"
    else:
        return None
    if started_reason(it, mover, now, same, (lambda x: anchored(gid, x)) if anchored is not None else None):
        return None
    if balanced_recently(meta, now) or handed_recently(meta, now):
        return None      # moved by the balancer, or by the idle hand-over (`metadata.hand_idle`), in the last 24 hours: the balancer never moves an item the idle hand-over moved inside a day (`hand_idle.due` does not read `metadata.balance`)
    capped = balance_count(meta) >= BALANCE_LIFETIME
    if capped and balance_capped_told(meta):
        return None
    tried = [str(t) for t in ((rec or {}).get("tried") or []) if isinstance(t, str)]
    return {"mover": mover, "project": project, "kind": kind, "tried": tried, "told_none": balance_none_told_recently(meta, now), "capped": capped}


def balance_all(items: dict[str, dict[str, Any]], now: float, minutes: float, front: Callable[[Any, str], bool] | None, behind: dict[str, str], same: Callable[[Any, Any], bool],
                anchored: Callable[[str, dict[str, Any]], bool] | None = None, builder: Callable[[str], bool] | None = None) -> list[tuple[str, dict[str, Any]]]:
    """[(gid, row)] of every item the balancer is to deal with now, in id order; reads only. An item that cannot be read is left out."""
    out: list[tuple[str, dict[str, Any]]] = []
    for gid in sorted(items, key=_ac._num):
        if items[gid].get("status") != "open":
            continue
        try:
            row = balance_due(items, gid, now, minutes, front, behind, same, anchored, builder)
        except Exception:  # noqa: BLE001
            continue
        if row is not None:
            out.append((gid, row))
    return out


def load_counts(movers: Iterable[str], same: Callable[[Any, Any], bool]) -> dict[str, int]:
    """Open items per mover, from `busy_movers`: names that are one session (`same`) are one entry."""
    out: dict[str, int] = {}
    for m in movers:
        key = next((k for k in out if same(k, m)), m)
        out[key] = out.get(key, 0) + 1
    return out


def load_of(load: dict[str, int], who: str, same: Callable[[Any, Any], bool]) -> int:
    return sum(n for k, n in load.items() if same(k, who))


def shift(load: dict[str, int], frm: str, to: str, same: Callable[[Any, Any], bool]) -> None:
    """One item moved from `frm` to `to`: the counts follow, so the next item of the pass sees the new load."""
    for who, d in ((to, 1), (frm, -1)):
        key = next((k for k in load if same(k, who)), who)
        load[key] = max(load.get(key, 0) + d, 0)


def pick_least(candidates: list[str], load: dict[str, int], status: Callable[[str], str], dead: Callable[[str], str], same: Callable[[Any, Any], bool], frm: str = "",
               tried: Iterable[str] = (), front: Callable[[Any, str], bool] | None = None, project: str = "") -> str:
    """The candidate with the fewest open items, "" when none can take the item. Left out: a name with no pane (`dead` says why; one that raises is left out too), the item's own mover (`frm`), any name in `tried`, a front agent.
    A pane in a turn only breaks a tie between equal loads (an idle one first); then the candidates' order (the project's own first). Never an exclusion for being busy."""
    tried = [t for t in tried if t]
    best: tuple[int, int, int] | None = None
    pick = ""
    for i, c in enumerate(candidates):
        if not c or (frm and same(c, frm)) or any(same(c, t) for t in tried):
            continue
        try:
            if dead(c) or (front is not None and front(c, project)):
                continue
            busy = 1 if status(c) == "busy" else 0
        except Exception:  # noqa: BLE001
            continue
        key = (load_of(load, c, same), busy, i)
        if best is None or key < best:
            best, pick = key, c
    return pick


def balance_others(candidates: list[str], frm: str, tried: Iterable[str], same: Callable[[Any, Any], bool], front: Callable[[Any, str], bool] | None = None, project: str = "") -> list[str]:
    """The builders other than the item's own mover that could have taken it but for being unusable: `candidates` less `frm`, any name in `tried` and a front agent. Only when there is one of these and `pick_least` still found none is
    the item's stay worth a History line and a message to -main ("no live builder"); with a mover that is the only builder there is nobody to be unusable and the pass is silent."""
    tried = [t for t in tried if t]
    out = []
    for c in candidates:
        if not c or (frm and same(c, frm)) or any(same(c, t) for t in tried):
            continue
        try:
            if front is not None and front(c, project):
                continue
        except Exception:  # noqa: BLE001
            continue
        out.append(c)
    return out


def balance_ok(kind: str, to_load: int, from_load: int) -> bool:
    """Is a move to a builder with `to_load` open items an improvement of the spread for an item whose mover has `from_load` (the item itself counted)? The item will count for the builder it goes to, so `to + 1 < from`
    for a queued item; an untaken hand-off also moves to an empty builder (`to == 0`: the lone item goes, a swap of equals does not)."""
    return to_load + 1 < from_load or (kind != "queued" and to_load == 0)


def balance_why(kind: str, minutes: float) -> str:
    """The reason the History line and the new mover's notice carry."""
    return (f"not started in {minutes:g} min" if kind == "untaken" else f"queued behind another item for {minutes:g} min") + ", so it goes to the builder with the fewest open items"
