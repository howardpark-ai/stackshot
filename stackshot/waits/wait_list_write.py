"""wait_list_write.py: the write side of a wait on a list of waits (pure functions: no I/O, no server import; the gates that need the store are in service/gates.py `gate_waits`).

A caller writes a list with `waits` (2 to 8 lines, each an object `{"kind": ..., ...}` with the fields of its kind, the same as the stored shape of waits/wait_list.py), `wait_mode` (`all` or `any`) and `until`
(the backstop day, the same parameter a single wait uses). This module turns what was passed into lines, never a second parser: every line goes through `wait_list.write_line` (the read rules of a stored line,
and the 300-character limit as a refusal). It also decides what an update that edits a list leaves: a list (2 to 8 lines), ONE line (stored as the single wait it is, so no list of one is ever stored) or none
(the wait ends, as `clear_wait` ends it).

    waits=[{"kind": "anchor", "anchor": "<url>", "event": "<what is expected there>"}, {"kind": "item", "after": "board#N"}, {"kind": "time", "until": "YYYY-MM-DD"},
           {"kind": "relay", "event": "<what the owner relays>"}, {"kind": "event", "event": "<a fleet event>"}], wait_mode="all", until="YYYY-MM-DD"

`waits` may also be a JSON string of that list (a client that sends a list as text), as `said` may. `waits=[]`, its text `[]` and `waits="none"` clear a stored list. A value of a line is text, a line holds the fields of
its kind only (a field of another kind with a value is refused; a null or an empty one is left out) and an anchor, an event or an item id is at most 300 characters."""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from stackshot.waits import wait_list as _wl, waiting as _wt

FORM = ('waits=[{"kind": "anchor", "anchor": "<url>", "event": "<what is expected there>"}, {"kind": "item", "after": "board#N"}], wait_mode="all", until="YYYY-MM-DD" '
        f"(kinds {' | '.join(_wl.KINDS)}; {_wl.MIN_LINES} to {_wl.MAX_LINES} lines; until is the backstop day)")
CLEAR_WORDS = ("none", "clear", "-")
KEYS = ("kind", "until", "anchor", "event", "after")      # what a caller may put in a line; `arrived` is the server's alone
# The single-wait parameters (and the clears that go with them) a list does not go with: one way to say a wait. `until` is the list's backstop and goes beside it.
SINGLE = ("wait_kind", "wait_anchor", "wait_event", "after", "wake", "ask_by", "hold", "wait_basis", "clear_wake", "clear_hold", "clear_after", "clear_wait_basis", "clear_wait")


_EMPTY_JSON_LIST = re.compile(r"\[\s*\]")


def _is_clear(spec: Any) -> bool:
    """A clear of a list: [] or a word (none, clear, -), and the text of an empty list ("[]"), the same as the empty list itself."""
    if isinstance(spec, list):
        return not spec
    return isinstance(spec, str) and (spec.strip().lower() in CLEAR_WORDS or bool(_EMPTY_JSON_LIST.fullmatch(spec.strip())))


def passed(spec: Any) -> bool:
    """Did the call pass `waits` (lines, or a clear)? An empty text or none at all is not passed."""
    return spec is not None and not (isinstance(spec, str) and not spec.strip())


def clearing(spec: Any) -> bool:
    """Is it the clear of a list: [] or the text none?"""
    return passed(spec) and _is_clear(spec)


def judged_as(spec: Any) -> str:
    """What the check on a self-set wait (gates.gate_self_wait) takes the wait of a call for: "list" when the call writes a list in which some line is not a time line (the lines name what the item waits on, so the check
    is not made), "" for nothing, a clear, and a list of time lines only (a date alone is no blocker: it is judged as a plain date wait is). A `waits` that does not parse is "list" too: the write refuses it with its
    own reason, which the check on the wait must not hide."""
    if not passed(spec) or clearing(spec):
        return ""
    try:
        lines = parse(spec) or []
    except ValueError:
        return "list"
    return "list" if any(ln["kind"] != "time" for ln in lines) else ""


def parse(spec: Any) -> list[dict[str, Any]] | None:
    """What a call passed as `waits` → the lines to store (each kind and its fields, as `wait_list.write_line` reads them; item ids as written, for the gate to resolve), [] for a clear, None when nothing
    was passed. ValueError, with the reason, for anything else; the reason names the line (waits[2])."""
    if not passed(spec):
        return None
    if _is_clear(spec):
        return []
    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except (ValueError, RecursionError):      # RecursionError: a text nested too deep for the parser to read is no list either
            raise ValueError(f"waits is not valid JSON; pass a list of lines, {FORM}")
    if not isinstance(spec, list):
        raise ValueError(f"waits is a list of lines, {FORM}")
    if len(spec) > _wl.MAX_LINES:      # the count first: a list over the limit is refused without a line of it being read (what `shape` says of it, in the same words)
        raise ValueError(f"a list holds {_wl.MIN_LINES} to {_wl.MAX_LINES} lines (got {len(spec)})")
    out: list[dict[str, Any]] = []
    for i, raw in enumerate(spec, 1):
        if isinstance(raw, dict):
            if "arrived" in raw:
                raise ValueError(f"waits[{i}]: arrived is set by the server when a line arrives and is never passed; leave it out")
            bad = [str(k) for k in raw if k not in KEYS]
            if bad:
                raise ValueError(f"waits[{i}]: unknown key{'s' if len(bad) > 1 else ''} {', '.join(bad)}; a line has kind and the fields of its kind ({', '.join(KEYS[1:])})")
            kind = _wl.kind_of(raw)
            own = _wl.fields_of(kind)
            foreign = [k for k in KEYS[1:] if own and k not in own and raw.get(k) not in (None, "")]      # a field of another kind with a value (a null or empty one says nothing)
            if foreign:
                raise ValueError(f"waits[{i}]: {'an' if kind[0] in 'aeiou' else 'a'} {kind} line takes {' and '.join(own)}, not {', '.join(foreign)}; leave {'it' if len(foreign) == 1 else 'them'} out")
        line, why = _wl.write_line(raw)
        if line is None:
            raise ValueError(f"waits[{i}]: {why}")
        out.append(line)
    return out


def event_phrases(spec: Any) -> list[str]:
    """The event lines' phrases of a `waits` argument, [] when it does not parse (the write refuses it with its reason): what is read before the item lock."""
    try:
        return [ln["event"] for ln in (parse(spec) or []) if ln["kind"] == "event"]
    except ValueError:
        return []      # (parse refuses with a ValueError whatever it cannot read: a text nested too deep included)


def mode_of(wait_mode: Any, stored: dict[str, Any]) -> str:
    """The mode of the list a call writes: the one it passes (all or any), else the mode of the list the item already stores, else all. ValueError for a word that is neither."""
    m = " ".join(str(wait_mode or "").split()).lower()
    if m and m not in _wl.MODES:
        raise ValueError(f"wait_mode is all or any (got {m!r})")
    return m or _wl.mode(stored) or "all"


def duplicate(lines: list[dict[str, Any]], held: "Counter[tuple[str, ...]] | None" = None) -> tuple[int, int] | None:
    """The 1-based positions of the first line that repeats an earlier one (same kind, same fields), None when no line does. `held` counts the lines of the stored list by their key: a line the item already
    stores that many times is no repeat when the list is sent again (resending a stored list is never refused as a repeat of itself)."""
    seen: dict[tuple[str, ...], list[int]] = {}
    for i, ln in enumerate(lines, 1):
        k = _wl.line_key(ln)
        at = seen.setdefault(k, [])
        at.append(i)
        if len(at) > max(1, (held or {}).get(k, 0)):
            return at[0], i
    return None


def carry_arrived(lines: list[dict[str, Any]], stored: dict[str, Any]) -> list[dict[str, Any]]:
    """The lines with the arrival the stored list recorded for the same line (same kind and fields), so that editing a list never loses what has arrived. Nothing the caller passes sets it."""
    have = {_wl.line_key(ln): ln for ln in _wl.lines(stored)}
    out = []
    for ln in lines:
        old = have.get(_wl.line_key(ln))
        out.append({**ln, "arrived": {"at": old["arrived_at"], "what": old["arrived_what"]}} if old and _wl.arrived(old) else dict(ln))
    return out


def shape(lines: list[dict[str, Any]], stored_holds: bool) -> tuple[str, str]:
    """What a call that passes `lines` leaves → ("list", "") for 2 to 8 lines; ("one", "") for ONE line of a list the item already stores (it is stored as the single wait it is); ("none", "") for one line
    that has already arrived (the group is over); else ("", why it is refused)."""
    n = len(lines)
    if n > _wl.MAX_LINES:
        return "", f"a list holds {_wl.MIN_LINES} to {_wl.MAX_LINES} lines (got {n})"
    if n >= _wl.MIN_LINES:
        return "list", ""
    if n == 1 and stored_holds:
        return ("none" if lines[0].get("arrived") else "one"), ""
    return "", f"a list holds {_wl.MIN_LINES} to {_wl.MAX_LINES} lines (got {n}); one wait is written with wait_kind and its fields, not with waits"


def single(line: dict[str, Any]) -> dict[str, Any]:
    """The single-wait parameters a lone line stands for: the same call as if the caller had passed that one wait (wait_kind, wait_anchor, wait_event, after; a time line is a date alone, `until`)."""
    k = line["kind"]
    if k == "time":
        return {"until": line["until"]}
    if k == "anchor":
        return {"wait_kind": "anchor", "wait_anchor": line["anchor"], "wait_event": line["event"]}
    if k == "item":
        return {"wait_kind": "item", "after": [line["after"]]}
    return {"wait_kind": k, "wait_event": line["event"]}


def time_before(date: str, other: str) -> bool:
    """Is `date` (a stored date or time) strictly before `other`? False when either is no date."""
    a, b = _wt.wake_epoch(date), _wt.wake_epoch(other)
    return a is not None and b is not None and a < b
