"""wait_list.py — a wait on a LIST of waits (pure functions of an item's metadata, no I/O, no model import; the one module that reads `waits`).

An item can wait on several things at once, of any kind (time, anchor, item, relay, event), and the list has a mode: `all` (the item comes back when every line has arrived) or `any`
(when the first does). Either way it comes back on its backstop day at the latest. An item with ONE wait is not a list: it keeps its single-wait fields (wait_kind, wait_anchor, wait_event, after,
until) and nothing here reads it. Mixed groups such as A and (B or C) are not supported.

The stored shape (a contract):
  wait_kind   "list" (the sixth kind)
  wait_mode   "all" | "any"
  until       the backstop day (required): the one date of the item, in the stored `until` format (YYYY-MM-DD or YYYY-MM-DDTHH:MM)
  waits       2 to 8 dicts, each {"kind": time | anchor | item | relay | event, ...} with the fields of its kind:
                time    until (a date or date-time in the stored `until` format)
                anchor  anchor (the url) and event (the text of what is expected there)
                item    after (ONE item id, a string)
                relay   event (what the owner relays, text)
                event   event (a fleet event spec: event_waits.py)
              and, set by the server only, "arrived": {"at": <epoch seconds>, "what": <short text>}

A list that does not hold (fewer than two lines or more than eight, an unknown kind, a missing field, a mode that is not all or any, no backstop day) is not a list: `valid` is false, `lines` is
empty and the item reads as it would without it. Every caller goes through this module; nothing else reads `waits` by hand."""
from __future__ import annotations

import time
from typing import Any, Callable

from stackshot.waits import waiting as _wt

LIST = "list"
KINDS = ("time", "anchor", "item", "relay", "event")       # the kinds a line may be (the five single waits)
MODES = ("all", "any")
MIN_LINES, MAX_LINES = 2, 8
LINE_MAX = 300                                              # the most a line's free text (an anchor, an event) and an arrival's words keep: longer is clipped
MALFORMED: dict[str, int] = {"count": 0}                   # reads of an item that stores wait_kind=list with a list that does not hold (the model counts each one it ignores)

_FIELDS = {"time": ("until",), "anchor": ("anchor", "event"), "item": ("after",), "relay": ("event",), "event": ("event",)}


def _one(v: Any) -> str:
    return " ".join(str(v or "").split())


def stored(meta: dict[str, Any]) -> bool:
    """Does the item say it waits on a list (wait_kind=list)? True whether or not the list holds; `valid` says that."""
    return _one((meta or {}).get("wait_kind")).lower() == LIST


def mode(meta: dict[str, Any]) -> str:
    """The list's mode, all or any; "" when it is neither."""
    m = _one((meta or {}).get("wait_mode")).lower()
    return m if m in MODES else ""


def backstop(meta: dict[str, Any]) -> str:
    """The backstop day: the item's stored `until`, "" when it has none."""
    return _wt.stored_until(meta or {})


def backstop_epoch(meta: dict[str, Any]) -> float | None:
    """The backstop day as the moment it falls due (the start of that day, or the time given), None when it is not a date."""
    b = backstop(meta)
    return _wt.wake_epoch(b) if b else None


def _line(raw: Any) -> tuple[dict[str, Any] | None, str]:
    """One stored line → (the line as read, "") or (None, why it is no line)."""
    if not isinstance(raw, dict):
        return None, "a line is an object"
    kind = _one(raw.get("kind")).lower()
    if kind not in KINDS:
        return None, f"a line's kind is one of {' | '.join(KINDS)} (got {kind!r})"
    out: dict[str, Any] = {"kind": kind, "until": "", "anchor": "", "event": "", "after": "", "arrived_at": 0.0, "arrived_what": ""}
    for f in _FIELDS[kind]:
        v = raw.get(f)
        if f == "after" and not isinstance(v, str):
            return None, "an item line names ONE item id, a string"
        v = _one(v)
        if not v:
            return None, f"a {kind} line needs {f}"
        if f == "until" and _wt.wake_epoch(v) is None:
            return None, f"a time line's until is YYYY-MM-DD or YYYY-MM-DDTHH:MM, a real date (got {v!r})"
        out[f] = v[:LINE_MAX] if f in ("anchor", "event") else v      # free text is clipped (a stored line can be long; what a reader sees never is)
    arr = raw.get("arrived")
    if isinstance(arr, dict):
        at_raw = arr.get("at")
        try:
            at = 0.0 if isinstance(at_raw, bool) else float(at_raw)      # float(True) is 1.0: a bool is no time
        except (TypeError, ValueError):
            at = 0.0
        if at > 0:                                              # a torn record (no usable time) is no arrival
            out["arrived_at"], out["arrived_what"] = at, _one(arr.get("what"))[:LINE_MAX]
    return out, ""


def problem(meta: dict[str, Any]) -> str:
    """Why the stored list does not hold, "" when it does (or when the item stores no list at all)."""
    m = meta or {}
    if not stored(m):
        return ""
    raw = m.get("waits")
    if not isinstance(raw, list):
        return "waits is a list of 2 to 8 lines"
    if not MIN_LINES <= len(raw) <= MAX_LINES:
        return f"waits holds {MIN_LINES} to {MAX_LINES} lines (got {len(raw)})"
    for r in raw:
        got, why = _line(r)
        if got is None:
            return why
    if not mode(m):
        return f"wait_mode is all or any (got {_one(m.get('wait_mode'))!r})"
    b = backstop(m)
    if not b or _wt.wake_epoch(b) is None:
        return "a list needs its backstop day: until=YYYY-MM-DD"
    return ""


def valid(meta: dict[str, Any]) -> bool:
    """Does the item store a list that holds? (wait_kind=list and every rule of the stored shape met.)"""
    return stored(meta) and not problem(meta)


def lines(meta: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """The validated lines (kind, until, anchor, event, after, arrived_at, arrived_what), in stored order; () when the item stores no list or the list does not hold."""
    if not valid(meta):
        return ()
    return tuple(_line(r)[0] for r in meta["waits"])            # type: ignore[misc]  (valid() read every one)


def note_malformed(meta: dict[str, Any]) -> str:
    """For the model: "" when there is nothing to ignore; else the model note for a stored list that does not hold, and the count goes up (MALFORMED)."""
    why = problem(meta)
    if why:
        MALFORMED["count"] += 1
        return f"wait_kind=list is stored with a list that does not hold ({why}): the list is ignored and the item reads as it would without it"
    return ""


# ---------------------------------------------------------------------------------------------------------------- what has arrived
def arrived(line: dict[str, Any]) -> bool:
    return float(line.get("arrived_at") or 0) > 0


def open_lines(meta: dict[str, Any]) -> list[int]:
    """The indexes of the lines that have not arrived."""
    return [i for i, ln in enumerate(lines(meta)) if not arrived(ln)]


def arrived_lines(meta: dict[str, Any]) -> list[int]:
    """The indexes of the lines that have arrived, in the order they did."""
    return [i for _at, i in sorted((ln["arrived_at"], i) for i, ln in enumerate(lines(meta)) if arrived(ln))]


def done(meta: dict[str, Any]) -> bool:
    """Is the group over by what has arrived: `all` when every line has, `any` when one has. False for an item with no list that holds."""
    ls = lines(meta)
    if not ls:
        return False
    n = sum(1 for ln in ls if arrived(ln))
    return n == len(ls) if mode(meta) == "all" else n >= 1


def completing_kind(meta: dict[str, Any]) -> str:
    """The kind of the line that arrived last (the one that completed the group), "" when none has."""
    got = arrived_lines(meta)
    return lines(meta)[got[-1]]["kind"] if got else ""


def mark_arrived(meta: dict[str, Any], idx: int, what: str, at: float) -> bool:
    """Record that line `idx` arrived, in place on `meta` (the list and the line are copied, so a shallow copy of the metadata is never shared with its source). Idempotent: a line that
    has arrived keeps its first time and its words, and a second call changes nothing. → True when it changed."""
    ls = lines(meta)
    if not 0 <= idx < len(ls) or arrived(ls[idx]):
        return False
    raw = [dict(r) for r in meta["waits"]]
    raw[idx]["arrived"] = {"at": float(at), "what": _one(what)[:LINE_MAX]}
    meta["waits"] = raw
    return True


# ---------------------------------------------------------------------------------------------------------------- which lines an arrival is for
def lines_for_item(meta: dict[str, Any], item_id: str, open_only: bool = True) -> list[int]:
    """The lines (indexes) of the item kind that wait on `item_id`; open ones only unless open_only is false. Two lines on the same item are both found."""
    return [i for i, ln in enumerate(lines(meta)) if ln["kind"] == "item" and ln["after"] == item_id and not (open_only and arrived(ln))]


def lines_for_anchor(meta: dict[str, Any], url: str, same: Callable[[str, str], bool], open_only: bool = True) -> list[int]:
    """The anchor lines that watch `url` (`same` compares two anchors the way the server does); open ones only unless open_only is false. Two lines on one anchor are both found."""
    return [i for i, ln in enumerate(lines(meta)) if ln["kind"] == "anchor" and same(ln["anchor"], url) and not (open_only and arrived(ln))]


def lines_for_event(meta: dict[str, Any], matches: Callable[[str], bool], open_only: bool = True) -> list[int]:
    """The event lines whose event phrase `matches` (a callable the server gives: the event waits' matcher on the phrase; it may raise for a phrase that is no event, which no line matches)."""
    out = []
    for i, ln in enumerate(lines(meta)):
        if ln["kind"] != "event" or (open_only and arrived(ln)):
            continue
        try:
            if matches(ln["event"]):
                out.append(i)
        except Exception:  # noqa: BLE001  — a phrase the matcher cannot read is a line that does not match
            continue
    return out


def lines_by_kind(meta: dict[str, Any], kind: str, open_only: bool = True) -> list[int]:
    return [i for i, ln in enumerate(lines(meta)) if ln["kind"] == kind and not (open_only and arrived(ln))]


def lines_for_time(meta: dict[str, Any], now: float) -> list[int]:
    """The open time lines whose date has come."""
    out = []
    for i in lines_by_kind(meta, "time"):
        ep = _wt.wake_epoch(lines(meta)[i]["until"])
        if ep is not None and ep <= now:
            out.append(i)
    return out


def relay_event(meta: dict[str, Any]) -> str:
    """What the owner relays on the first open relay line ("" when none is open): the subject of the question he is asked at the backstop day."""
    ls = lines(meta)
    return next((ls[i]["event"] for i in lines_by_kind(meta, "relay")), "")


# ---------------------------------------------------------------------------------------------------------------- the scheduler
def next_moment(meta: dict[str, Any], now: float | None = None) -> float | None:
    """The moment the scheduler next has to look at the list: the earliest of the backstop day and the open time lines (an item, anchor or event line arrives by an event, not by the clock). A list whose
    group is already over by what has arrived (a decision a pause, a crash or an edit left unacted on) is due now. None for an item with no list that holds."""
    if not valid(meta):
        return None
    if done(meta):
        return time.time() if now is None else float(now)
    eps = [backstop_epoch(meta)]
    ls = lines(meta)
    eps += [_wt.wake_epoch(ls[i]["until"]) for i in lines_by_kind(meta, "time")]
    eps = [e for e in eps if e is not None]
    return min(eps) if eps else None


# ---------------------------------------------------------------------------------------------------------------- words
def line_text(line: dict[str, Any], shown: Callable[[str], str] = str) -> str:
    """What a line waits on, as a short phrase; `shown` writes an item id as people read it."""
    k = line["kind"]
    if k == "time":
        return f"the date {line['until']}"
    if k == "anchor":
        return f"a notice at {line['anchor']} ({line['event']})"
    if k == "item":
        return f"the close of {shown(line['after'])}"
    if k == "relay":
        return f"news of {line['event']}"
    return f"a fleet event ({line['event']})"


def _join(parts: list[str]) -> str:
    return "; ".join(parts)


def outcome_text(meta: dict[str, Any], cause: str, shown: Callable[[str], str] = str) -> str:
    """What the list's end says, from the record of what arrived (read BEFORE the wait's fields are dropped):
      all     "all 3 arrived: a; b; c"
      any     "any of 3 arrived: a; not needed: b; c"
      the backstop day passing with the group not over   "backstop day 2026-11-20: arrived a; b; still open: c; d"   (none arrived: "backstop day 2026-11-20: nothing had arrived; still open: c; d")
    where a, b, c are the words each arrival came with (what was recorded) and, for a line still open, what it waits on. Lines are joined with "; " everywhere."""
    ls = lines(meta)
    n = len(ls)
    got = [ls[i]["arrived_what"] or line_text(ls[i], shown) for i in arrived_lines(meta)]
    left = [line_text(ls[i], shown) for i in open_lines(meta)]
    if cause == "backstop" and not done(meta):
        return f"backstop day {backstop(meta)}: " + (f"arrived {_join(got)}" if got else "nothing had arrived") + (f"; still open: {_join(left)}" if left else "")
    if mode(meta) == "all":
        return f"all {n} arrived: {_join(got)}"
    return f"any of {n} arrived: {_join(got)}" + (f"; not needed: {_join(left)}" if left else "")


def summary(meta: dict[str, Any], shown: Callable[[str], str] = str) -> str:
    """The list as one phrase for a message or the History: "3 waits, all: a (arrived); b; c"."""
    ls = lines(meta)
    if not ls:
        return ""
    bits = [line_text(ln, shown) + (" (arrived)" if arrived(ln) else "") for ln in ls]
    return f"{len(ls)} waits, {mode(meta)}: {_join(bits)}; backstop day {backstop(meta)}"
