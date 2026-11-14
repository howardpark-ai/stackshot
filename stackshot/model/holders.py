"""holders.py: who holds an item and who may be named to move it: the stored hold flag, the role a project page gives a session, the front-agent pair rule, the background test the hand-off gate uses, and the end of a stored
state when the server's own act ends the wait it stood on; and the pure rules of a save that settles whose move it is: who takes a front-only project's answered step, a write that only finishes the writer's own step, the model
fields a write stores, what a settle decided, what the item waits on him for, and the words a stored state stands on.

A domain module: it reads an item's metadata dict, and the project registry through `anchors`, and nothing else (no store, no clock, no message). What reads the store (the items an `after` names, one item by id) is
service/item_read.py's; the board's own rule for what counts as parked (the renderer's) is read there too. The save steps that read the store or the clock (the mover settle, the owner's step on the checklist, the stored state) are
service/mover_steps.py's."""
from __future__ import annotations

import sys
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.anchors import anchors as _anc
from stackshot.fleet.sessions_registry import _role_name
from stackshot.model import model as _model
from stackshot.model import model_guards as _mg
from stackshot.model import owner_steps as _hs
from stackshot.model import states as _states
from stackshot.model import steps as _steps
from stackshot.model import work as _work
from stackshot.model.needs import _waits_decision
from stackshot.waits import builderless as _bl


def _hold_flag(item: dict[str, Any]) -> bool:
    """The stored hold flag: an open item with metadata.hold, whatever its needs. The wake pass reads it (a held item's wake
    releases the flag, a backstop's leaves it alone); everything that shows or counts the hold reads _is_held."""
    return item.get("status") == "open" and bool((item.get("metadata") or {}).get("hold"))


def _is_held(item: dict[str, Any]) -> bool:
    """On hold (its lane stays 'on agent' and a secondary property renders it as 'on hold'):
    an open item with metadata.hold, optionally metadata.wake. needs, due and next stay as they are.
    An item whose needs hold decision is never on hold, whatever its
    stored flag says (render.is_held, the same rule for the flag): it waits on the owner's call, and the update tool drops such a flag on
    the item's next write. The flag only: a wait on a date alone is parked too, as _is_parked reads it."""
    return _hold_flag(item) and not _waits_decision(item.get("metadata") or {})


def _role_of(name: str, nm: dict[str, str] | None = None) -> tuple[dict[str, Any], str]:
    """→ (anchors.session_roles(), the name a project page lists `name` under: as given, by its fleet label, its name now or an old name; "" when no page lists it).
    roles[key]["role"] is "front" for a user-facing agent and "back" for a background agent. The needs gate and the front-mover gate read a name through this."""
    name = str(name or "").strip()
    nm = _anc.names() if nm is None else nm
    roles = _anc.session_roles()
    label = nm.get(_anc.canonical(name, nm), "") or name
    return roles, _role_name(roles, name, label)


def _front_pair_ok(sender: str, key: str, project: str) -> bool:
    """May `sender` hand an item of `project` to the front agent `key` (builderless.pair_allowed): both are live front agents of the project the item is filed under (one page), and the project is front-only (anchors.front_only). A project with no agents map has no front agent to name."""
    try:
        s = str(sender or "").strip()
        if not s:
            return False
        nm = _anc.names()
        roles, skey = _role_of(s, nm)
        return _bl.pair_allowed(roles.get(skey) if skey else None, roles.get(key), _anc.front_only(project), project)
    except Exception:  # noqa: BLE001  — the relaxation is an extra: a failed read keeps the refusal
        return False


def _is_background(who: str, project: str) -> bool:
    """Is `who` a background agent of the project's hub? False for a front agent, the owner, a session no page lists and "" (the test the hand-off gate uses, model_guards.Ctx)."""
    w = _model.norm_who(who)
    if not w or _model.is_owner(w):
        return False
    try:
        return bool(_mg.Ctx().background_of(w, project))
    except Exception:  # noqa: BLE001  — a registry that cannot be read names nobody
        return False


def _state_end(meta: dict[str, Any], *states: str) -> None:
    """The server's own act (a wake that fired, an after link released, an anchor's notice) ends the wait a stored state stood
    on: the state and its carry fields go when the state is one of `states` (none given: whatever it is), and the item reads as derived from its fields."""
    if meta.get("state") in (states or (*_states.STATES, *_states.LEGACY_STATES)):
        for k in _states.DROP_ON_CLOSE:
            meta.pop(k, None)


def _builderless_answer_to(meta: dict[str, Any], project: str) -> str:
    """Who takes an item of a front-only project (anchors.front_only) when the owner's step is answered and the item stores no `then` (builderless.answer_target): the session its next open step names, else its
    contact; "" when the project has a background agent, neither names a session, or a read fails (the caller then keeps the project's keeper, as before)."""
    try:
        if not project or not _anc.front_only(project):
            return ""
        nm = _anc.names()
        def usable(who: str) -> bool:      # a front agent of this item's project, as mover= may name one (a step line does no more)
            roles, key = _role_of(who, nm)
            return bool(key) and _bl.front_of(roles[key], project)
        return _bl.answer_target(meta, usable)
    except Exception as e:  # noqa: BLE001  — the choice is an extra: a failed read keeps the old fallback
        print(f"answer: next session of {project} not read ({e.__class__.__name__}: {e}); the keeper takes it", file=sys.stderr, flush=True)
        return ""


def _finishes_own_line(work: Any, meta: dict[str, Any], writer: str, open_item: bool = True) -> bool:
    """Does this `work` argument only finish the writer's own step (state done, no other change)? Such a write is the writer closing out its own part: it is no new work on the item, so it
    names the writer in no needs (update_unlocked in service/update.py). Only on an open item; the spec carries no other session (`agent` is the writer or absent) and no remove; the writer has an open step
    (the first open step that opens with its name is the one the write ticks)."""
    if not open_item or not writer or work is None or (isinstance(work, str) and not work.strip()):
        return False
    try:
        spec = _work.parse(work)
    except ValueError:
        return False
    if spec["state"] != "done" or spec["remove"]:
        return False
    nm = _anc.names()
    same = lambda x, y: bool(x) and bool(y) and (x == y or _anc.canonical(x, nm) == _anc.canonical(y, nm))
    if spec["agent"] and not same(spec["agent"], writer):      # another session's step is not the writer's own part
        return False
    return _work.step_of(_steps.view(meta, keeper=str(meta.get("owner") or "")), writer, same) >= 0


_STATE_STANDS_ON = {"your-call": "needs decision and the ask", "blocked": "after, and supplies",
                    "parked": "the wake and the owner's words or the wait_basis", "doing": "", "your-step": "", "outside": "", "verifying": ""}


def _model_apply(meta: dict[str, Any], status: str, setv: dict[str, str], drop: set[str]) -> None:
    """Store or drop the model fields on `meta` (the metadata as this write leaves it). A completed item has no mover and waits on nothing: only its goal can be set."""
    if status == "completed":
        late = [k for k in setv if k != "goal"]
        if late:
            raise ToolError(f"Refused: a completed item has no mover and waits on nothing; {', '.join(late)} go with an open item (goal alone can be set)")
    for k in drop:
        meta.pop(k, None)
    meta.update(setv)


def _settle_apply(meta: dict[str, Any], ch: dict[str, str]) -> None:
    """Store what model.settle decided on `meta`: a value stores, "" drops the field."""
    for k, v in ch.items():
        if v:
            meta[k] = v
        else:
            meta.pop(k, None)


_OWNER_STEP_NONE = "answer the ask on the item"      # his step's text when the item waits on him with no ask line and no step summary (the cold call writes the same words)


def _owner_want(meta: dict[str, Any]) -> str:
    """What the item waits on him for, as his step reads: the step's one line for a your-step, else the Decide part of the ask, else the step summary, else the plain words."""
    step, ask = _states.clean(meta.get("step")), _states.clean(meta.get("ask"))
    if meta.get("state") == "your-step" and step:
        return step
    return _hs.decide_of(ask) or step or _OWNER_STEP_NONE
