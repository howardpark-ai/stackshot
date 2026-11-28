"""cue_note.py: the reply line of a write that lifts a relay or cue wait, naming the same mover's other open items that sit on a relay wait or on the same cue wording.

A cue (what an outside party relays, or an event named in wait_event) usually arrives once for every item of a mover that waits on it. The write that lifts one item's wait is the moment the writer
knows the cue came, so the reply lists the others, and the writer lifts or rewrites each in the same turn. Read-only: nothing is lifted here, and no notice goes to anyone.

Matching is narrow on purpose: another item counts when it is open, has the same stored mover, and either waits on a relay (its own wait_kind, or a relay line in a wait list) or carries a wait_event
whose normalized text (case, spacing and edge punctuation folded) equals the lifted one. A cue worded differently is not matched, so a real wait is never named as lifted by chance, and an item
that is not named stays as it was."""
from __future__ import annotations

import re
from typing import Any

from stackshot.core.store import _item_files
from stackshot.github import ghsync as _gh
from stackshot.model import model as _model
from stackshot.service.store import _load_open
from stackshot.waits import wait_list as _wl

LIST_MAX = 10
_WORD_MAX = 80


def norm(text: Any) -> str:
    """A wait_event as compared: lower case, runs of space as one, punctuation at either edge off."""
    return re.sub(r"\s+", " ", str(text or "")).strip(" \t.,;:!?\"'()[]").casefold()


def _waits(meta: dict[str, Any]) -> list[tuple[str, str]]:
    """The waits an item's metadata holds that a cue can lift, as (kind, wait wording): its single wait (relay, or any wait_event), and the relay and event lines of a wait list."""
    out: list[tuple[str, str]] = []
    kind = str(meta.get("wait_kind") or "").strip().lower()
    event = str(meta.get("wait_event") or "").strip()
    if kind == "relay" or event:
        out.append((kind or "event", event))
    if _wl.valid(meta):
        for ln in _wl.lines(meta):
            if ln.get("kind") in ("relay", "event") and not _wl.arrived(ln):
                out.append((str(ln["kind"]), str(ln.get("event") or "").strip()))
    return out


def _lifted(was: dict[str, Any], now: dict[str, Any], open_now: bool) -> list[tuple[str, str]]:
    """The waits of `was` that the write lifted: the item closed, or the wait is no longer held as it was (cleared, or its kind or normalized wording changed). A re-dated wait is not lifted."""
    held = {(k, norm(e)) for k, e in _waits(now)} if open_now else set()
    return [(k, e) for k, e in _waits(was) if (k, norm(e)) not in held]


def _clip(text: str) -> str:
    t = " ".join(text.split())
    return t if len(t) <= _WORD_MAX else t[:_WORD_MAX].rsplit(" ", 1)[0].rstrip(" ,;:") + " …"


def note(gid: str, item_was: dict[str, Any], item: dict[str, Any]) -> str:
    """The reply line (with its leading newline) for a write that lifted a relay or cue wait of `gid`, "" when it lifted none or the mover has no other item on one. At most LIST_MAX items are named,
    each as `board#N (wording)`, then a count of the rest. The matching rules are in the module text."""
    was_m, now_m = item_was.get("metadata") or {}, item.get("metadata") or {}
    lifted = _lifted(was_m, now_m, item.get("status") == "open")
    if not lifted:
        return ""
    mover = _model.pick_who(was_m.get("mover")) or _model.pick_who(now_m.get("mover"))
    if not mover:
        return ""
    cues = {norm(e) for _k, e in lifted if norm(e)}
    hits: list[str] = []
    for other, _p in _item_files():
        if other == gid:
            continue
        try:
            it = _load_open(other)
            if it is None:
                continue
            m = it.get("metadata") or {}
            if _model.pick_who(m.get("mover")) != mover:
                continue
            ws = [(k, e) for k, e in _waits(m) if k == "relay" or norm(e) in cues]
            if ws:
                k, e = ws[0]
                hits.append(f"{_gh.shown(other)} ({'relay' if k == 'relay' else 'cue'}: {_clip(e) or 'no wording'})")
        except Exception:  # noqa: BLE001  — an item that cannot be read is left out; the write is saved
            continue
    if not hits:
        return ""
    shown = hits[:LIST_MAX]
    more = f"; {len(hits) - LIST_MAX} more" if len(hits) > LIST_MAX else ""
    return (f"\n(note: {mover} has {len(hits)} other open item{'s' if len(hits) != 1 else ''} on a relay wait or the same cue: " + ", ".join(shown) + more
            + ". If the cue came for them too, lift or rewrite each now, in this turn; this write lifted none of them)")
