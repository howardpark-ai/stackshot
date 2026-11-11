"""front_step.py: a step held by a front agent that stays stuck moves to the item's mover, by the system, with nobody asking.

A stuck-elsewhere finding about a front agent's step (or a retired session's) goes to the project's page key, never to the front agent (audit_run.recipient), and is sent once; nothing in it
changes the board, so such a step could stay open for as long as the item does. The ten-minute filing pass (audit_run.front_step_pass) now keeps a clock for it and, past the threshold,
rewords the step so it opens with the item's mover. This module is the part that reads and decides; the item is written by the server (server._front_step_mark, server._front_step_move),
which the pass reaches through two members of audit_run.Env, so a run without the server (the command line) changes nothing.

  hours()                           [audit] front_step_move_hours (default 3; 0 = off)
  step_hash(text)                   what identifies a step for the clock: a short hash of the step as the checklist compares it (steps.key)
  front_opener(name, roles)         is the step's opener a front agent (role front or keeper) or a retired session, by the role map
  candidates(findings, items, by_shown, roles)   the stuck-elsewhere findings the rule covers, each with its step, its hash and who it moves to
  reopen(text, name)                the step with its first line opening with `name` (the rest of the text as it was); "" when its first line has no opener
  clock(meta, h, mover), moved_before(meta, h)   the item's clock record for the step with hash h under that mover (the epoch it was first seen stuck), and whether that step moved already
  still_holds(gid, item, load, mover, now)   the server's recheck under its lock: the same opener, the same mover and the finding still holding
  fix_text(mover, due_at)           the finding's fix line for such a step: what will happen and when
  landed_at(meta, step, mover)      when the step was moved to `mover`, while it is still the item's first open step and still the mover's; None otherwise
  overdue(meta, step, mover, today) a step already overdue that names no date of its own (it was moved, or found stuck): a wake ahead does not cover it
  held(text, mover, is_front, same)  the front agent a step opens with when the write check refuses it: the item's mover is another session (server._gate_front_step; the same test counts the open ones in month_count)
  month_count(items, roles, now)    the monthly number: front-held steps closed in the last 30 days, how many by someone else, and how many open ones the write check would refuse now

The clock is `metadata.stuck_since = {"step": <hash>, "mover": <the item's mover>, "at": <epoch>}`: the first pass that sees the finding for a step stores it, a pass that no longer sees the finding for it (the
step is done, dropped, reworded, the opener changed) drops it, a new mover gets a clock of its own (the old one reads as none), and a write to the item by anyone does not touch it. `metadata.stuck_moved` lists the hashes of the steps already moved (the last five), so a step
the owner or a session worded back to the front agent is not moved a second time. Both are the server's bookkeeping: they are no write by a session and move no clock of the item.
`metadata.stuck_landed = {"step": <hash of the reworded step>, "mover": <the mover>, "at": <epoch of the move>}` is what the move leaves: the step is now the mover's and is chased again if the mover does not act (see
landed_at and overdue, which the silence pass reads: a wake no longer silences a step that is already overdue and carries no date of its own).
Stdlib plus the repo's modules."""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from typing import Any, Callable

from stackshot.audit import audit_checks as _ac
from stackshot.core import config as _cfg
from stackshot.waits import dated_wait as _dw
from stackshot.model import model as _model
from stackshot.model import steps as _steps

CLOCK = "stuck_since"
MOVED = "stuck_moved"
LANDED = "stuck_landed"
MOVED_KEEP = 5

# the opener of a step's first line, as model_guards reads it (a name of up to three words, an optional role in parentheses, a colon), with the list marker and bold marks kept apart so a reword changes the name alone
_NAME = r"[^\W_][\w.\-]*(?: [\w.\-]+){0,2}"
_OPEN_RX = re.compile(rf"^(?P<lead>\s*(?:[-*+•]|\d+[.)])?\s*)(?P<b1>\*{{0,2}})(?P<name>{_NAME})(?:\s*\([^)\n]{{1,40}}\))?\s*:(?P<b2>\*{{0,2}})(?P<sp>\s+|$)(?P<rest>.*)$")


COUNT_DAYS = 30


def hours() -> float:
    """The threshold in hours ([audit] front_step_move_hours): 0 is off."""
    return _cfg.audit_front_step_move_hours()


def step_hash(text: Any) -> str:
    """A step's identity for the clock: twelve hex digits of its text as the checklist compares it (steps.key: one line of text, list marker and bold marks off)."""
    return hashlib.sha1(_steps.key(text).encode("utf-8")).hexdigest()[:12]


def _role(name: str, roles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    r = roles.get(name)
    if isinstance(r, dict):
        return r
    want = _ac._norm(name)
    for k, v in roles.items():
        if _ac._norm(k) == want and isinstance(v, dict):
            return v
    return {}


def front_opener(name: str, roles: dict[str, dict[str, Any]], front_roles: tuple[str, ...]) -> bool:
    """Is `name` a front agent (a role in `front_roles`) or a retired session, by the role map? The owner never is: his steps are his."""
    if not name or _model.is_owner(name):
        return False
    r = _role(name, roles)
    return bool(r) and (bool(r.get("retired")) or r.get("role") in front_roles)


def candidates(findings: list[dict[str, Any]], items: dict[str, dict[str, Any]], by_shown: dict[str, str], roles: dict[str, dict[str, Any]],
               front_roles: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    """{gid: {finding, opener, mover, step, hash}} for the stuck-elsewhere findings this rule covers: the step's opener is a front agent or a retired session, and the item's mover is a session that is not
    retired itself (the owner, nobody and an outside party have no session to move it to). A finding about a background agent's step is not covered: that agent gets the finding itself and can answer it."""
    out: dict[str, dict[str, Any]] = {}
    for f in findings:
        if f.get("category") != "stuck-elsewhere":
            continue
        gid = by_shown.get(str(f.get("id") or ""))
        item = items.get(gid or "")
        if not item:
            continue
        mover, nm = str(f.get("mover") or "").strip(), str(f.get("to") or "").strip()
        if _ac._no_session(mover) or not front_opener(nm, roles, front_roles) or _role(mover, roles).get("retired"):
            continue
        step = _ac.first_open_step(item.get("metadata") or {})
        if not step or _steps.opener(step) != nm:
            continue
        out[gid] = {"finding": f, "opener": nm, "mover": mover, "step": step, "hash": step_hash(step)}
    return out


def reopen(text: str, name: str) -> str:
    """The step with the opener of its first line replaced by `name` (list marker and bold marks kept, the role in parentheses dropped, the rest of the line and every later line as they were); "" when the first
    line has no opener or the result would not read as `name`'s step."""
    lines = str(text or "").split("\n")
    i = next((k for k, ln in enumerate(lines) if ln.strip()), None)
    if i is None:
        return ""
    m = _OPEN_RX.match(lines[i])
    if not m:
        return ""
    lines[i] = f"{m['lead']}{m['b1']}{name}:{m['b2']}{m['sp'] or ' '}{m['rest']}".rstrip() if m["rest"] else f"{m['lead']}{m['b1']}{name}:{m['b2']}"
    out = "\n".join(lines)
    return out if _steps.opener(out) == name and _steps.key(out) != _steps.key(text) else ""


def clock(meta: dict[str, Any], h: str, mover: str | None = None) -> float | None:
    """When the item's clock for the step with hash `h` started (an epoch), None when it holds none for that step. With `mover` given, the clock must also have been started under that mover: a clock
    kept for another mover reads as none, so a new mover gets a clock of its own and is not handed the step minutes after it took the item."""
    rec = (meta or {}).get(CLOCK)
    if isinstance(rec, dict) and rec.get("step") == h:
        if mover is not None and _ac._norm(str(rec.get("mover") or "")) != _ac._norm(mover):
            return None
        at = rec.get("at")
        if isinstance(at, (int, float)) and not isinstance(at, bool) and at > 0:
            return float(at)
    return None


def still_holds(gid: str, item: dict[str, Any], load: Any, mover: str, now: float) -> str:
    """"" when, on the item as it is now, the first open step still opens with the same front agent (or retired session) and the stuck-elsewhere finding still holds against `mover`, the item's
    mover; else why not. Read under the server's lock before the clock is written or the step moved, so an item handed to the opener, parked, held or waiting since the pass read it is left alone.
    `load(gid)` reads another item (the ones this item waits behind)."""
    from stackshot.tools import board_report as _br  # noqa: PLC0415
    from stackshot.waits import waiting as _wt  # noqa: PLC0415
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    step = _ac.first_open_step(meta)
    opener = _steps.opener(step) if step else ""
    if not opener:
        return "the first open step has no opener"
    items = {gid: item}
    for g in _wt.after_of(meta):
        try:
            items[g] = load(g)
        except Exception:  # noqa: BLE001  (an item that cannot be read is not open for the check)
            pass
    it, meta, after_open, cur = _ac._item_view(items, gid)
    if _ac._norm(cur) != _ac._norm(mover):
        return f"the item's mover is now {cur or 'nobody'}, not {mover}"
    se = _ac.check_stuck_elsewhere(it, meta, cur, {opener.lower(), _ac._norm(opener)}, _br._last_write(it), after_open, now)
    if not se or _ac._norm(se[0]) != _ac._norm(opener):
        return "the stuck-elsewhere finding no longer holds (the item is parked, held, waiting or handed on)"
    return ""


def moved_before(meta: dict[str, Any], h: str) -> bool:
    """Has the step with hash `h` been moved by this rule before?"""
    v = (meta or {}).get(MOVED)
    return isinstance(v, list) and h in v


def fix_text(mover: str, due_at: float) -> str:
    """The finding's fix line for a front agent's step: the two ways out and what happens otherwise, with the time."""
    return f"take the step, or reword it to {mover}; if it is still open then, it moves to {mover} at {_ac._stamp(due_at)}"


def landed_at(meta: dict[str, Any], step: Any, mover: str, acted: float = 0.0) -> float | None:
    """When the step was moved to `mover` (an epoch), None unless the record is for this very step under this mover: a step reworded, done or handed on since reads as none. Also none when the rule is off
    (`front_step_move_hours` 0), and when the item has had real activity since the move (`acted`, the time of its last: the mover wrote the item), though the step still reads the same."""
    rec = (meta or {}).get(LANDED)
    if not (hours() > 0 and isinstance(rec, dict) and step and mover and rec.get("step") == step_hash(step) and _ac._norm(str(rec.get("mover") or "")) == _ac._norm(mover)):
        return None
    at = rec.get("at")
    return float(at) if isinstance(at, (int, float)) and not isinstance(at, bool) and at > 0 and not acted > at else None


def overdue(meta: dict[str, Any], step: Any, mover: str, today: dt.date, acted: float = 0.0) -> bool:
    """Is `step`, the first open step, one that is already overdue and carries no date of its own? Overdue is what the rule's records say: it was moved to `mover` and has not been acted on since (landed_at, `acted` as there), or
    its clock is running under `mover` (the finding was seen for it). A step that names a date (dated_wait.step_wait_day) is the wake's business, however long it has stood."""
    if not step or _dw.step_wait_day(_steps.first_line(step), today) is not None:
        return False
    return landed_at(meta, step, mover, acted) is not None or clock(meta, step_hash(step), mover) is not None


def held(text: Any, mover: str, is_front: Callable[[str], bool], same: Callable[[str, str], bool]) -> str:
    """The name a step opens with when the write check refuses it, "" when it passes: the opener is a front agent (`is_front`), which gets no work notice and whose own wake or until dates (with no hold) are refused, so nothing
    wakes it for the step, and the item's mover is a session other than it (`same`). Passes: a step that names no one or the owner, a step of the item's own mover, an item with no mover or one moved by the
    owner or an outside party, and any opener that is not a front agent (a background agent can be woken)."""
    nm, mv = _steps.opener(text), str(mover or "").strip()
    if not nm or _model.is_owner(nm) or _ac._no_session(mv) or same(mv, nm) or not is_front(nm):
        return ""
    return nm


def month_count(items: dict[str, dict[str, Any]], roles: dict[str, dict[str, Any]], now: float) -> dict[str, Any]:
    """The monthly number that shows whether front agents still take steps nothing can wake them for: over the last COUNT_DAYS days, `closed` = steps opening with a front agent that were closed (done or
    dropped, on an open or a closed item), `by_other` = of those, the ones a session other than the front agent closed (a server mark is no session); and `open` = the open steps the write check
    (held) would refuse now, with `ids` the items they sit on. The front agent test is the write check's: role front, not retired."""
    isf = lambda n: (lambda r: r.get("role") == "front" and not r.get("retired"))(_role(n, roles))
    same = lambda a, b: _ac._norm(a) == _ac._norm(b)
    since = now - COUNT_DAYS * 86400
    closed = by_other = n_open = 0
    ids: list[str] = []
    for gid, it in items.items():
        meta = it.get("metadata") if isinstance(it.get("metadata"), dict) else {}
        for s in _steps._valid(meta.get("steps")):
            at = s.get("at")
            if s["status"] == _steps.OPEN or not isinstance(at, (int, float)) or isinstance(at, bool) or at < since:
                continue
            nm = _steps.opener(s["text"])
            if not nm or _model.is_owner(nm) or not isf(nm):
                continue
            closed += 1
            by = str(s.get("by") or "").strip()
            if by and not by.lower().startswith("stackshot") and not same(by, nm):
                by_other += 1
        if it.get("status") != "open":
            continue
        mover = _ac._item_view(items, gid)[3]
        n = sum(1 for s in _steps.view(meta, keeper=str(meta.get("owner") or "")) if s["status"] == _steps.OPEN and held(s["text"], mover, isf, same))
        if n:
            n_open += n
            ids.append(gid)
    return {"days": COUNT_DAYS, "closed": closed, "by_other": by_other, "open": n_open, "ids": sorted(ids)}
