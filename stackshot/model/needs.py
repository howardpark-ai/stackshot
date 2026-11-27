"""needs.py: what an item's needs, after and observers lists hold, and the readers of them: the two kinds of need (`_NEEDS_KINDS`: decision, external) and the session names after them
(`_needs_sessions`), the list as stored and as written back (`_needs_list`, `_needs_of`, `_needs_kinds`, `_needs_store`), the stored order (`_canon_needs`), whether the item waits on the owner's
decision (`_waits_decision`), whether it holds any question or call for him still unanswered (`owner_question_open`), and the `after`, `observers` and `tell_him` lists (`_after_of`,
`_observers_of`, `_tell_him_of`).

An item relates to sessions five ways: its mover, metadata.needs (whose move it is now: a LIST of "decision" (the owner's), "external" (someone outside, named in next) and session names, several at once;
empty is the mover's move), metadata.observers (sessions that hear only a close or a reopen), metadata.tell_him (the front agents he asked to tell him about it: a turn each time, even while he is away) and metadata.after (items of any project that must close first). The stored needs list is canonical: decision,
external, then the sessions as given.

A domain module: it reads an item's metadata dict and nothing else (no store, no clock). What needs the store stays with it: `_after_open`, which reads each `after` item from the store, is server.py's still."""
from __future__ import annotations

from typing import Any

from stackshot.anchors import anchors as _anc

_NEEDS_KINDS = ("decision", "external")


def _needs_list(value: Any) -> list[str]:
    """metadata.needs as the list it is since an earlier change: a stored list, or the one word of the form before it ("decision")."""
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    v = str(value or "").strip()
    return [v] if v else []


def _needs_of(meta: dict[str, Any]) -> list[str]:
    return _needs_list(meta.get("needs"))


def _needs_kinds(meta: dict[str, Any]) -> list[str]:
    return [x.lower() for x in _needs_of(meta) if x.lower() in _NEEDS_KINDS]


def _needs_store(meta: dict[str, Any], needs: list[str]) -> None:
    """Write a needs list into an item's metadata (the key goes when the list is empty)."""
    if needs:
        meta["needs"] = list(needs)
    else:
        meta.pop("needs", None)


def _canon_needs(needs: list[str], nm: dict[str, str] | None = None) -> list[str]:
    """The stored order: decision, external, then the sessions as given, each once (a session by its canonical id)."""
    out, seen = [], set()
    for k in _NEEDS_KINDS:
        if any(x.lower() == k for x in needs):
            out.append(k)
    for x in needs:
        if x.lower() in _NEEDS_KINDS:
            continue
        key = _anc.canonical(x, nm) if nm is not None else x
        if key not in seen:
            seen.add(key); out.append(x)
    return out


def _needs_sessions(meta: dict[str, Any]) -> list[str]:
    """The session names in an item's needs (whatever is not decision or external)."""
    return [x for x in _needs_of(meta) if x.lower() not in _NEEDS_KINDS]


def _waits_decision(meta: dict[str, Any]) -> bool:
    """Its needs hold decision: the item is in the owner's queue, never on hold (render.is_held
    reads the lane the same way, needs_kind "call")."""
    return any(x.lower() == "decision" for x in _needs_of(meta))


def owner_question_open(meta: dict[str, Any]) -> bool:
    """Does the item hold a question or call for the owner that he has not answered: decision in needs (with or without an ask), a stored ask, options that no answer of his has
    settled (his pick drops them; an answer in his own words leaves them beside its record in `answers`), or a stored your-call; whoever the mover is, parked or not. The one test
    every default of the server reads (a close's outcome, a wait's end day): while it holds, none applies and the call is judged as it was before those defaults existed."""
    if _waits_decision(meta) or str(meta.get("state") or "").strip().lower() == "your-call":
        return True
    if " ".join(str(meta.get("ask") or "").split()):
        return True
    opts, answers = meta.get("options"), meta.get("answers")
    return isinstance(opts, list) and bool(opts) and not (isinstance(answers, list) and any(isinstance(a, dict) for a in answers))


def _after_of(meta: dict[str, Any]) -> list[str]:
    v = meta.get("after")
    return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []


def _observers_of(meta: dict[str, Any]) -> list[str]:
    v = meta.get("observers")
    return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []


def _tell_him_of(meta: dict[str, Any]) -> list[str]:
    """metadata.tell_him: the front agents he asked, in his own words, to tell him about the item (recorded only by a write that carries them: gates.gate_tell_him); never the observers."""
    v = meta.get("tell_him")
    return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []
