"""progress.py: what counts as the item having MOVED, as opposed to anyone having said something about it.

The pure half: no server import, no clock read, no file. The last-activity record (model/last_activity.py) asks `moved`, `marks`, `merges` and `state_of` for the signals it takes from a save: a step
marked done or dropped, a state change, a pull request recorded as merged. (The item's own `progress` clock and the hand-up that read it are gone: a long busy stretch now tells the project's -main
agent through `audit/busy_tell.py`, and a live background mover's silence through the ladder's `main` rung; a stored `progress` field on an old item is read by nothing.)

  counts   a step marked done or dropped, a state change (the item's status, its phase, the kind of its wait, its mover, its state or its needs), a pull request merged for the item
           (the "merged <ref>" entry of `metadata.released_told` the server adds when the merge settles the item; and a key of `metadata.merged_seen`, which the server adds when the
           hub saw a pull request tied to the item merge: scoped to it by an anchor, its body naming the item, or the item's own words naming it; `server._merge_progress_tick`, the hub's
           merge log), the item being created
  does not a status line (`work`), a note, a reply, a message, a bare confirm, a new or reworded step, a description edit; and a save that is no one's write about the work (an audit's, a migration's,
           the server's own bookkeeping) moves the item only by a status or phase change (a wake, a close), never by a step mark, a merge note, a mover, a state or needs"""
from __future__ import annotations

from typing import Any

DONE, DROPPED = "done", "dropped"
MERGED = "merged "          # the prefix of an entry of `metadata.released_told` for a merge (a bare ref there is a release)
TOLD = "released_told"
SEEN = "merged_seen"        # metadata: the keys ("owner/repo#n") of the pull requests the hub saw merge that are tied to the item (the server's merge pass); a separate list from `released_told`, whose entries tell the mover and settle a step


def _meta(item: dict[str, Any] | None) -> dict[str, Any]:
    m = (item or {}).get("metadata")
    return m if isinstance(m, dict) else {}


def _norm(v: Any) -> str:
    return " ".join(str(v or "").split())


def marks(item: dict[str, Any] | None) -> frozenset[tuple[str, str]]:
    """The checklist's steps that were marked done or dropped, as (text, status): a step joins the set when it is marked, and a reword of an open step does not."""
    out: set[tuple[str, str]] = set()
    for s in _meta(item).get("steps") or []:
        if isinstance(s, dict) and s.get("status") in (DONE, DROPPED):
            out.add((_norm(s.get("text")), str(s["status"])))
    return frozenset(out)


def merges(item: dict[str, Any] | None) -> frozenset[str]:
    """The pull requests the server recorded as merged for the item: the "merged <ref>" entries of `released_told` (a merge that settled a step) and the keys of `merged_seen` (a merge the hub saw
    that is tied to the item), as "merged <ref>" both, so a pull request in both lists is one."""
    m = _meta(item)
    told = m.get(TOLD)
    seen = m.get(SEEN)
    out = {str(x) for x in (told if isinstance(told, list) else []) if str(x).startswith(MERGED)}
    out |= {MERGED + str(x) for x in (seen if isinstance(seen, list) else []) if str(x)}
    return frozenset(out)


def state_of(item: dict[str, Any] | None, phase: bool = True, who: bool = True) -> tuple[str, ...]:
    """What a state change is, as one comparable value: the item's status, the phase the board shows it in (alive or waiting) and the kind of its wait, its mover, its state and its needs.
    `phase` False leaves the phase and the wait kind out (an item saved before the server stored them is not changed by the save that stores them); `who` False leaves the mover, the state and the
    needs out (a save that is no one's write, such as a migration renaming a session, does not move the item)."""
    it = item or {}
    m = _meta(it)
    needs = m.get("needs")
    needs_s = ",".join(sorted(_norm(n) for n in needs)) if isinstance(needs, (list, tuple)) else _norm(needs)
    return (_norm(it.get("status")), _norm(m.get("phase")) if phase else "", _norm(m.get("waits_on")) if phase else "",
            _norm(m.get("mover")) if who else "", _norm(m.get("state")) if who else "", needs_s if who else "")


def moved(before: dict[str, Any] | None, after: dict[str, Any], real: bool = True) -> list[str]:
    """What in this save is progress, as short words ([] when none): "created" (no item before it), "step" (a step newly marked done or dropped), "state" (see `state_of`), "merged" (a pull
    request newly recorded as merged). `real`: the save is someone's write about the work (a session's write, the owner's answer, an anchor's event: activity.counts); a save that is not (the server's
    bookkeeping, a migration, an audit) moves the item only by its status, its phase and the kind of its wait (a wake, a close), never by a step mark, a merge note, a mover, a state or needs."""
    if before is None:
        return ["created"]
    out: list[str] = []
    if real and marks(after) - marks(before):
        out.append("step")
    stored = "phase" in _meta(before)
    if state_of(after, stored, real) != state_of(before, stored, real):
        out.append("state")
    if real and merges(after) - merges(before):
        out.append("merged")
    return out
