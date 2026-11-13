"""handoff_hooks.py: what the hand-off passes still reach in web/server.py.

The hand-off record, its delivery, the minute pass, the cold call and the display live in service/handoff.py and service/handoff_cold.py. A few things they use are still the surface's, because other code on the
surface shares them: the checks and limits of the write gates, the item model's reader and its switch, the stall pass's state and the one ladder's rungs (service/stall.py and service/ladder.py import this module's passes, so they are looked up when the hook runs), the recovery request, the page store, the
publish and the session ids. They are reached through `Hooks`, which server.py fills once with `install` (these modules cannot import server.py: the surface sits above them). A hook is looked up on server.py
when it runs, so a suite that replaces one there reaches the passes; a suite that replaces a function of the passes sets it on the module that owns it. A hook leaves this table when the area that holds it
moves under service/.

Imports point down only: this module imports nothing of the package."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Hooks:
    """What the hand-off passes still reach in server.py, in the names they have there without the leading underscore. server.py builds one and gives it to `install`. A hook that reads a value is a function with no argument."""
    after_open: Callable[..., Any]  # server._after_open
    bullets_on: Callable[..., Any]  # server._bullets_on
    close_reason_max: Callable[..., Any]  # server._close_reason_max
    description_limits: Callable[..., Any]  # server._description_limits
    fit: Callable[..., Any]  # server._fit
    front_pair_ok: Callable[..., Any]  # server._front_pair_ok
    gate_description: Callable[..., Any]  # server._gate_description
    item_refs: Callable[..., Any]  # server._item_refs
    ladder_enter: Callable[..., Any]  # service/ladder.ladder_enter
    ladder_first: Callable[..., Any]  # service/ladder.ladder_first
    ladder_on: Callable[..., Any]  # service/ladder.ladder_on
    laddered: Callable[..., Any]  # service/ladder.laddered
    load_or_none: Callable[..., Any]  # server._load_or_none
    model_of: Callable[..., Any]  # server._model_of
    old_wait_off: Callable[..., Any]  # server._old_wait_off
    page_io: Callable[..., Any]  # server._page_io
    publish: Callable[..., Any]  # server._publish
    recovery_role: Callable[[], Any]  # server._RECOVERY_ROLE
    recovery_target: Callable[..., Any]  # server._recovery_target
    recovery_tell: Callable[..., Any]  # server._recovery_tell
    role_name: Callable[..., Any]  # server._role_name
    role_of: Callable[..., Any]  # server._role_of
    scoped_anchors: Callable[..., Any]  # server._scoped_anchors
    session_id: Callable[..., Any]  # server._session_id
    stall_confirm: Callable[..., Any]  # service/stall.stall_confirm
    stall_load: Callable[..., Any]  # service/stall.stall_load
    stall_lock: Callable[[], Any]  # service/stall.STALL_LOCK
    stall_save: Callable[..., Any]  # service/stall.stall_save
    stall_ver: Callable[..., Any]  # service/stall.stall_ver
    switchover_on: Callable[..., Any]  # server._switchover_on
    update: Callable[..., Any]  # server._update


_hooks_: Hooks | None = None


def install(hooks: Hooks) -> None:
    """Server.py gives the hand-off passes what they still reach there (once, at its import)."""
    global _hooks_
    _hooks_ = hooks


def hooks() -> Hooks:
    if _hooks_ is None:
        raise RuntimeError("the hand-off passes have no hooks installed (server.py installs them at its import)")
    return _hooks_
