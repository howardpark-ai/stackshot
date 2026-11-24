"""front_handon.py: an idle front agent with an open step of its own on an item it moves hands the item to a free background agent of its project; the front agent stays the item's contact and stays named in its needs.

Part of the rule that no item an agent moves goes more than an hour without an update (audit/hourly.py is the line side, audit/hand_idle.py the hand-over of an idle builder's item, audit/front_pickup.py the turn started for the
front agent when no background agent can take its step). A front agent's step is work nothing wakes it for, so while a free background agent of the project can take the item, the item goes to it: the background agent
does the step, and the front agent, which the owner talks to, keeps the item as its contact. This module decides; the server writes (`audit_ticks._front_handon_tick`, run from the ten-minute audit tick right after the idle hand-over
and before the pick-up). It is the idle hand-over's own move: `[audit] hand_idle` must be on, and it rides `[audit] hourly_line` like the pick-up (no key of its own).

  due(items, gid, now, front, idle, present, same, skip)       {"mover", "project", "steps", "more"} when the item is to be handed on now, else None
  due_all(...)                                                 [(gid, row)] of every such item, in id order; reads only; an item that cannot be read is left out and its reason goes to `errors`
  why(label)                                                   the reason the History line and the new mover's notice carry

The item is picked by the pick-up's own test (`front_pickup.eligible`: an item the board shows on an agent, no hold, wait or decision; the mover a front agent of the item's own project, never its keeper; the first open step the
agent's own; the agent-state snapshot fresh and saying the agent is idle; the owner not in that conversation; the item quiet for 45 minutes), and was not handed on by the idle pass in the last 24 hours (`hand_idle.handed_recently`,
the hand-over's own guard, which the hand-on writes too: an item goes on once a day at most by either, so an item handed back to a front agent is not handed on again at once, and the pick-up has it). The new mover is
the first FREE background agent of the project, as `hand_idle.pick_free` reads it (the builder before the rest; not the mover of any open item on an agent; the snapshot says it is idle: busy, unknown, stale and missing are not free).
The move is the idle hand-over's own write (`handoff_exec` -> `handoff_write_move`) with the old mover left named in `needs` behind the new one, so the front agent still hears of the item; the item's contact is not touched.
With no background agent free, or none in the project, nothing is handed on and the pick-up (a turn for the front agent) has the item.

The step of the front agent keeps opening with its name until the front-step rule (audit/front_step.py) rewords it to the new mover. No step is read for what it asks (the model has no way to tell a step that brings work to the owner
from any other), so none is worded as a decision ask here.

A background mover is outside this rule (the test needs a front agent), so a handed item is never handed back by it, and the 24-hour guard keeps an item that comes back to a front agent from going on at once.

Pure: no server import, no file, no clock read. Stdlib plus the repo's modules."""
from __future__ import annotations

from typing import Any, Callable, Iterable

from stackshot.audit import audit_checks as _ac
from stackshot.audit import front_pickup as _fp
from stackshot.audit import hand_idle as _hi

WHY = "its front agent was idle with a step of its own open and nobody was typing to it"      # the reason the History line and the new mover's notice carry


def due(items: dict[str, dict[str, Any]], gid: str, now: float, front: Callable[[Any, str], bool], idle: Callable[[str], bool], present: Callable[[str], bool],
        same: Callable[[Any, Any], bool], skip: Iterable[str] = ()) -> dict[str, Any] | None:
    """The row of the open item `gid` when it is to be handed on now (see the module doc), else None. Each test is fail closed: one that raises reads as "no"."""
    row = _fp.eligible(items, gid, now, front, idle, present, same, skip)
    if row is None:
        return None
    meta = (items.get(gid) or {}).get("metadata")
    if _hi.handed_recently(meta if isinstance(meta, dict) else {}, now):
        return None      # handed on in the last 24 hours (by this or by the idle pass): the hand-over's own guard
    return row


def due_all(items: dict[str, dict[str, Any]], now: float, front: Callable[[Any, str], bool], idle: Callable[[str], bool], present: Callable[[str], bool],
            same: Callable[[Any, Any], bool], skip: Iterable[str] = (), errors: list[str] | None = None) -> list[tuple[str, dict[str, Any]]]:
    """[(gid, row)] of every item to be handed on now, in id order; reads only. An item that cannot be read is left out, and `errors` (when given) gets one line for it."""
    out: list[tuple[str, dict[str, Any]]] = []
    skip = set(skip)
    for gid in sorted(items, key=_ac._num):
        if items[gid].get("status") != "open":
            continue
        try:
            row = due(items, gid, now, front, idle, present, same, skip)
        except Exception as e:  # noqa: BLE001  — one item never stops the others
            if errors is not None:
                errors.append(f"{gid} not read: {e.__class__.__name__}: {e}")
            continue
        if row is not None:
            out.append((gid, row))
    return out


def why(label: str) -> str:
    """The reason the History line and the new mover's notice carry, naming the mover the item left (`label`, the name as the registry shows it)."""
    return f"{WHY} (it was with {label})"
