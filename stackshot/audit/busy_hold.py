"""busy_hold.py: what of the mover's own is running on an item right now, for the refusal of a hold on an item that is being moved (service/gates.py `gate_busy_hold`).

An item its mover is moving is not paused: a hold says "nothing happens here until ...", which is false while a subagent of the mover builds it. The gate asks this module one question,
`live_work(gid, mover, ...)`: is a running subagent of `mover` tied to THIS item? It answers with the words the refusal uses (`your subagent "<description>"`), or "" for nothing.

The proof is the one the hourly audit uses (audit/hourly.py, audit/subagent_tie.py): the subagent's own record on this box, a running one whose description (else its brief) names the item or a pull request
anchored to it, read against every open item the mover has, so a subagent that works on another item of the mover is not tied to this one. Nothing is read from GitHub. A release queue run or a main CI run of an
anchored pull request is NOT read: the server records the events of a pull request when they end (a CI result, a merge: model/last_activity.py), never that a run is in flight, and an event record is no proof
of one running, so a refusal on it would rest on a guess.

Unknown is never a refusal: a mover whose subagents cannot be read (`subagent_tie.Unreadable`, a transcript this box does not hold, a sessions index that cannot be read), a subagent whose files cannot be read,
a running subagent that names no item, and any failure of the check itself all answer "". The callers are injected (`subagents`, `anchored`, `items`) so this module reads no server state and a suite can give
fakes. Stdlib plus the repo's modules."""
from __future__ import annotations

from typing import Any, Callable

from stackshot.audit import audit_checks as _ac
from stackshot.audit import subagent_tie as _tie

DESC_MAX = 80      # characters of a subagent's description the refusal quotes


def _quoted(sub: dict[str, Any]) -> str:
    """The subagent as the refusal names it: its description in quotes, one line, clipped; "" when it has none (its brief alone tied it)."""
    d = " ".join(str(sub.get("description") if "description" in sub else sub.get("text") or "").split())
    if not d:
        return "your subagent"
    d = d if len(d) <= DESC_MAX else d[: DESC_MAX - 1].rstrip() + "…"
    return f'your subagent "{d}"'


def live_work(gid: str, mover: str, *, subagents: Callable[[str], list[dict[str, Any]]], items: Callable[[], dict[str, dict[str, Any]]],
              anchored: Callable[[], dict[str, Any]], same: Callable[[Any, Any], bool], shown: Callable[[str], str]) -> str:
    """The words for what is running on item `gid` that `mover` runs ("your subagent "<description>"" ), "" when nothing is or nothing can be told.
    `subagents(mover)` → the mover's running subagents (`service/audit_ticks.py` `_mover_subagents`: raises `subagent_tie.Unreadable` or anything else when they cannot be read); `items()` → every stored item by id;
    `anchored()` → {item id: the pull requests ("owner/repo#n") anchored to it}; `same(a, b)` → whether two names are one session; `shown(id)` → the id as the board writes it."""
    try:
        subs = [s for s in (subagents(mover) or []) if isinstance(s, dict) and not s.get("unreadable")]
        if not subs:
            return ""      # none running (or none that can be read): nothing is claimed, and the items are not even loaded
        all_items = items()
        anch = anchored() or {}
        cands = {gid: (shown(gid), anch.get(gid, ()))}
        for g, it in all_items.items():      # the mover's other open items: a subagent that names one of them (its description first) is at work on that one, not on this
            if g == gid or (it or {}).get("status") != "open":
                continue
            try:
                _it, _meta, _after, mover2 = _ac._item_view(all_items, g)
                if mover2 and same(mover2, mover):
                    cands[g] = (shown(g), anch.get(g, ()))
            except Exception:  # noqa: BLE001  — an item that cannot be read is no other item of the mover's
                continue
        for s in subs:
            if gid in _tie.tied_to(s, cands):
                return _quoted(s)
        return ""
    except Exception:  # noqa: BLE001  — unknown (Unreadable included) is never a refusal
        return ""
