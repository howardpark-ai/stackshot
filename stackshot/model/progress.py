"""progress.py — the item's `progress` clock: when the work last moved, as opposed to when anyone last said something about it.

The pure half: no server import, no clock read, no file. server._save asks `moved` once per save and stamps the item (`item["progress"]`, epoch seconds, top level beside
`activity`); the hand-up of an item that is not moving (server._stall_tick, ladder.py) reads `at`.

Why a clock of its own. `activity` (activity.py) answers "has anyone written to this item": a status line, a note, a reply and a message all move it, which is right for a silence check and
wrong for a stuck one, since a busy mover that answers "no change" every hour keeps it fresh. `progress` moves only for what is movement:

  counts   a step marked done or dropped, a state change (the item's status, its phase, the kind of its wait, its mover, its state or its needs), a pull request merged for the item
           (the "merged <ref>" entry of `metadata.released_told` the server adds when the merge settles the item; and a key of `metadata.merged_seen`, which the server adds when the
           hub saw a pull request tied to the item merge: scoped to it by an anchor, its body naming the item, or the item's own words naming it; `server._merge_progress_tick`, the hub's
           merge log), the item being created
  does not a status line (`work`), a note, a reply, a message, a bare confirm, a new or reworded step, a description edit; and a save that is no one's write about the work (an audit's, a migration's,
           the server's own bookkeeping) moves the clock only by a status or phase change (a wake, a close), never by a step mark, a merge note, a mover, a state or needs

An item saved before the field existed has none: `at` reads the latest of its last write, its last state change, its last activity and the time its latest step was marked, so a deploy does
not hand up every item that merely lacks the field; the first save that is no progress seeds the field from what the item read as before it. No pass rewrites the store for this."""
from __future__ import annotations

from typing import Any

FIELD = "progress"
DONE, DROPPED = "done", "dropped"
MERGED = "merged "          # the prefix of an entry of `metadata.released_told` for a merge (a bare ref there is a release)
TOLD = "released_told"
SEEN = "merged_seen"        # metadata: the keys ("owner/repo#n") of the pull requests the hub saw merge that are tied to the item (the server's merge pass); a separate list from `released_told`, whose entries tell the mover and settle a step


def _meta(item: dict[str, Any] | None) -> dict[str, Any]:
    m = (item or {}).get("metadata")
    return m if isinstance(m, dict) else {}


def _norm(v: Any) -> str:
    return " ".join(str(v or "").split())


def _num(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


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


def at(item: dict[str, Any] | None) -> float:
    """When the item last made progress: its `progress` stamp, else (an item from before the field) the latest of its last write, its last state change, its last activity and the time its
    latest step was marked, else 0."""
    it = item or {}
    v = _num(it.get(FIELD))
    if v > 0:
        return v
    out = max(_num(it.get("updated")), _num(it.get("state_updated")), _num(it.get("activity")))
    for s in _meta(it).get("steps") or []:
        if isinstance(s, dict) and s.get("status") in (DONE, DROPPED):
            out = max(out, _num(s.get("at")))
    return out


def stamp(item: dict[str, Any], before: dict[str, Any] | None, now: float, real: bool = True) -> bool:
    """Apply one save to the item: progress sets the clock to `now`; any other save leaves it, and an item with no clock yet gets one seeded from what it read as before this save, so the save
    that was no progress is not its first progress. Only an open item has a clock. → True when the item's field changed."""
    if item.get("status") != "open":
        return False      # the clock is for items that can be handed up: a closed item gets none (a repair pass that marks the steps of a closed item writes nothing new), and a reopened one is stamped by the state change
    old = item.get(FIELD)
    if moved(before, item, real):
        item[FIELD] = now
    elif not old:
        seed = at(before if before is not None else item)
        if seed > 0:
            item[FIELD] = seed
    return item.get(FIELD) != old


def due(item: dict[str, Any], now: float, hours: float, handed_at: float = 0.0, alive_at: float = 0.0) -> bool:
    """Is the item to be handed up for not moving: its last progress is `hours` or more behind, and it was not handed up for that stretch already (the last hand-up, `handed_at`, is `hours` or
    more behind too). Progress after a hand-up starts a stretch of its own, which `hours` after it can end in another hand-up. `alive_at`: when the item last became alive (the server's record of
    when it first saw the item due after a park or a wait): the time is counted from the later of that and the last progress, so a parked item is not handed up for the park."""
    last = max(at(item), float(alive_at or 0))
    if last <= 0:
        return False
    span = hours * 3600.0
    return now - last >= span and now - float(handed_at or 0) >= span
