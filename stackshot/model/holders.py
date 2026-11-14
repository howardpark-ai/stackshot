"""holders.py: who holds an item and who may be named to move it: the stored hold flag, the role a project page gives a session, the front-agent pair rule, the background test the hand-off gate uses, and the end of a stored
state when the server's own act ends the wait it stood on.

A domain module: it reads an item's metadata dict, and the project registry through `anchors`, and nothing else (no store, no clock, no message). What reads the store (the items an `after` names, one item by id) is
service/item_read.py's; the board's own rule for what counts as parked (the renderer's) is read there too."""
from __future__ import annotations

from typing import Any

from stackshot.anchors import anchors as _anc
from stackshot.fleet.sessions_registry import _role_name
from stackshot.model import model as _model
from stackshot.model import model_guards as _mg
from stackshot.model import states as _states
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
