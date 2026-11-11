"""until_write.py: the write side of the one `until` date of a wait.

A wait is one stored date, `until` (YYYY-MM-DD, or YYYY-MM-DDTHH:MM where a time of day is allowed), with an optional `wait_kind` beside it (what the wait stands on: time | anchor |
item | relay | event; no kind = the wait stands on the date alone). The old wake, ask_by and hold are retired as stored fields: a write that passes one of them is read as the date it
gives and stores `until` (and no old field). The readers of a stored `until` are in waiting.py; this module is the way in.

The update path keeps its gates (the cap, the renewal guard, the wait_basis rules, the model guards) in the words of the old fields, so they judge every write the way they always did:
`unfold` turns a stored `until` into the old working fields for the length of one update (kind relay or event: ask_by; kind anchor or item: wake, the backstop; no kind or time: wake with a
hold), and `fold` turns the working fields back into `until` just before the item is saved. An item that stores the old fields and is not written to a wait stays as it is (the data
migration of stored items is a later change).

A kind with no date is never refused: `fallback_date` takes a date the item's own words give, else one its deadline or the item it waits after suggests, else tomorrow.

Pure functions of a metadata dict, dates and callbacks: no server import."""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable

from stackshot.waits import waiting as _wt

KINDS = _wt._WAIT_KINDS
LEGACY_FIELDS = ("wake", "ask_by", "hold", "hold_set")      # the stored fields a wait no longer writes: `until` takes their date
# The old parameters wake, ask_by and hold stay accepted as aliases of `until` for 14 days after the release that stores `until` (the day they are refused after is
# [model] wait_alias_until, read at the call, so moving it needs no release). The window as first set ends Wed Nov 25th 2026 (14 days after Wed Nov 11th 2026).
ALIAS_UNTIL = "2026-11-25"


def kind_of(m: dict[str, Any]) -> str:
    """The wait_kind an item stores, "" when it stores none or a word that is not one of the five."""
    k = " ".join(str(m.get("wait_kind") or "").split()).lower()
    return k if k in KINDS else ""


def _one(v: Any) -> str:
    return " ".join(str(v or "").split())


def slot_of(kind: str) -> str:
    """The one working field the date of a kind of wait stands in while the gates judge a write: a relay's or an event wait's ask_by (the event-wait form's own backstop day), else the wake
    (a wait on the date alone, an anchor or an item wait's backstop)."""
    return "ask_by" if kind in ("relay", "event") else "wake"


def unfold(meta: dict[str, Any]) -> bool:
    """Turn a stored `until` into the old working fields, in place, for one update's gates: the date is the relay's ask_by, the backstop wake of an anchor, item or event wait, or the
    wake of a wait on the date alone (kind time or none), which also stands as a hold when the item states a reason for it (a wait_basis) or stores the kind time, as a park with a reason does; a bare date is a wait on that date alone. `until` itself goes from the working copy; `fold` puts it back.
    → True when the item stored an `until` (the caller folds it again after the write)."""
    u = _wt.stored_until(meta)
    if not u:
        meta.pop("until", None)
        return False
    meta.pop("until", None)
    k = kind_of(meta)
    if slot_of(k) == "ask_by":
        meta["ask_by"] = u
    elif k in ("anchor", "item"):
        meta["wake"] = u
    else:
        meta["wake"] = u
        if str(meta.get("wait_kind") or "").strip().lower() == "time" or _wt.basis_of(meta):
            meta["hold"] = True            # a park with a reason of its own (a basis) or a stored kind time is judged as the hold it was; a bare date is a wait on that date alone, never a hold
    return True


def unfolded(meta: dict[str, Any]) -> dict[str, Any]:
    """A copy of `meta` with a stored until standing as the old working fields (for a note that reads the wake as the mover wrote it)."""
    m = dict(meta)
    unfold(m)
    return m


def unfold_item(item: dict[str, Any]) -> bool:
    """unfold on an item's metadata (an item that has none is left alone)."""
    m = item.get("metadata")
    return unfold(m) if isinstance(m, dict) else False


def _dated(value: Any) -> str:
    v = _one(value)
    return v if v and _wt.wake_epoch(v) is not None else ""


def date_of(meta: dict[str, Any]) -> str:
    """The one date the working fields give for the wait the item stands in: a relay's ask_by (else its wake), the earlier of ask_by and wake for an anchor, item or event wait (whose date
    is the backstop), the wake (else ask_by) for a wait on a time or on no kind. "" when none is a date."""
    wake, ask = _dated(meta.get("wake")), _dated(meta.get("ask_by"))
    k = kind_of(meta)
    if k == "relay":
        return ask or wake
    if k in ("anchor", "item", "event"):
        both = [(_wt.wake_epoch(v), v) for v in (ask, wake) if v]
        return min(both)[1] if both else ""
    return wake or ask


def to_slot(meta: dict[str, Any]) -> None:
    """A wait whose kind this write changed carries its date in the working field of the NEW kind (`slot_of`): a date the item held for another kind moves there, so the new kind's gates find it
    (a relay or event wait reads ask_by; a time wait reads its wake, and a time wait stands as a hold). An anchor or item wait reads either, so it stays as it is."""
    k = kind_of(meta)
    if not k or k in ("anchor", "item"):
        return
    wake, ask = _dated(meta.get("wake")), _dated(meta.get("ask_by"))
    if slot_of(k) == "ask_by":
        if wake and not ask:
            meta["ask_by"] = meta.pop("wake")
    elif ask and not wake:
        meta["wake"] = meta.pop("ask_by")
    if k == "time" and _dated(meta.get("wake")):
        meta["hold"] = True


def fold(meta: dict[str, Any]) -> str:
    """Turn the working wake, ask_by and hold into `until`, in place: the item is saved with the one date and none of the old fields. With no date among them nothing changes (a hold
    that waits on an `after` item or a pane recycle keeps its flag: it has no date of its own to fold). → the date stored, "" when none was."""
    u = date_of(meta)
    if not u:
        return ""
    meta["until"] = u
    for k in LEGACY_FIELDS:
        meta.pop(k, None)
    return u


def fold_item(item: dict[str, Any]) -> str:
    m = item.get("metadata")
    return fold(m) if isinstance(m, dict) and item.get("status") == "open" else ""


def needs_date(meta: dict[str, Any]) -> bool:
    """Does the item stand in a wait kind and have no date for it (no until, wake or ask_by)? The case `fallback_date` fills."""
    return bool(kind_of(meta)) and not _wt.stored_until(meta) and not date_of(meta)


# ---------------------------------------------------------------------------------------------------------------- a kind with no date
TOMORROW = "day"
TEXT = "text"
SUGGESTED = "suggested"


def fallback_date(texts: list[str], today: dt.date, parse_date: Callable[[str, dt.date], str], cap_days: float, due: str = "", other: list[str] | None = None) -> tuple[str, str, str]:
    """The date for a wait that came with a kind and no date → (YYYY-MM-DD, how, the words that gave it); how is "text", "suggested" or "day".
    1. a date the item's own words give: each line of `texts` (the item's open steps first, then its description) read by `parse_date` (watchers.parse_date: absolute dates, tomorrow, weekday
       names, small relative phrases); the earliest that lies after today and within `cap_days`.
    2. a date suggested from the item and its current step: its deadline (`due`), else the earliest wake or until of an item it waits after (`other`), the same window.
    3. tomorrow: the date that is at most a day away, said so in the reply.
    A date past the cap is not taken from words (the cap is the owner's rule for a wait; the caller's gate lifts it only on his words)."""
    last = today + dt.timedelta(days=max(1.0, float(cap_days)))
    found: list[tuple[dt.date, str]] = []
    for line in texts:
        t = " ".join(str(line or "").split())
        if not t:
            continue
        try:
            d = dt.date.fromisoformat(parse_date(t, today) or "")
        except ValueError:
            continue
        if today < d <= last:
            found.append((d, t))
    if found:
        d, t = min(found)
        return d.isoformat(), TEXT, t
    cands: list[tuple[dt.date, str]] = []
    for label, v in (("its due date", due), *(("the item it waits after", x) for x in (other or []))):
        s = _one(v)[:10]
        try:
            d = dt.date.fromisoformat(s)
        except ValueError:
            continue
        if today < d <= last:
            cands.append((d, label))
    if cands:
        d, label = min(cands)
        return d.isoformat(), SUGGESTED, label
    return (today + dt.timedelta(days=1)).isoformat(), TOMORROW, ""


def fallback_note(kind: str, date: str, how: str, said: str) -> str:
    """The reply line for a date the server took because the write gave a kind and none: where it came from, and how to change it."""
    src = {TEXT: f"read from the item's own words (\"{said[:90]}\")", SUGGESTED: f"suggested by {said}", TOMORROW: "set to tomorrow, since the item's words give no date and nothing else suggests one"}[how]
    return f"\n(note: wait_kind={kind} came with no date, so until={date}, {src}; change it with until=<date>, or clear_wait=true if the item should not wait)"


# ---------------------------------------------------------------------------------------------------------------- the old parameters, as aliases
def alias_note(used: list[str], until: str, ends: dt.date) -> str:
    """The short reply line that names `until` when a write passed an old parameter (wake, ask_by, hold), with the last day it is accepted."""
    names = " and ".join(used)
    return (f"\n(note: {names} {'is' if len(used) == 1 else 'are'} now written as until: the date is stored as until={until or '<date>'} and no old field. "
            f"Pass until=<date> instead; {names} {'is' if len(used) == 1 else 'are'} accepted until {ends:%Y-%m-%d} and refused after)")
