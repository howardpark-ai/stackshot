"""wake_hooks.py: what the wake passes still reach in web/server.py.

The wake pass, the anchor pass, the waits' watchers, the event waits and the anchor release live in service/wakes.py, service/watching.py and service/event_waits.py. Three things they use are still the
surface's, because other code on the surface shares them: the readers of the item model that other areas also call (the open `after` items, the hold flag, the effective model of an item, the
end of a stored state, the hand-over to a stored `then`), the renderer's answers, and the
publish, the time zone and the session ids. They are reached through `Hooks`, which server.py fills once with `install` (these modules cannot import server.py: the surface sits above them). A
hook is looked up on server.py when it runs, so a suite that replaces one there reaches the passes; a suite that replaces a function of the passes sets it on the module that owns it. A hook leaves
this table when the area that holds it moves under service/.

Imports point down only: this module imports nothing of the package."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Hooks:
    """What the wake passes still reach in server.py, in the names they have there without the leading underscore. server.py builds one and gives it to `install`. A hook that reads a value is a function with no argument."""
    after_open: Callable[..., Any]  # item_read._after_open
    event_activity_tick: Callable[..., Any]  # server._event_activity_tick
    follow_superseded: Callable[..., Any]  # mover_steps._follow_superseded
    hand_stored_then: Callable[..., Any]  # service.answer_handover._hand_stored_then
    hold_flag: Callable[..., Any]  # holders._hold_flag
    is_held: Callable[..., Any]  # holders._is_held
    item_mover_model: Callable[..., Any]  # service/client_reads._item_mover_model
    load_or_none: Callable[..., Any]  # item_read._load_or_none
    merge_progress_tick: Callable[..., Any]  # service/merge_progress._merge_progress_tick
    model_of: Callable[..., Any]  # item_read._model_of
    old_wait_off: Callable[..., Any]  # item_read._old_wait_off
    own_repo: Callable[..., Any]  # service.released._own_repo
    publish: Callable[..., Any]  # web.publish._publish
    rmod_confirmed_at: Callable[..., Any]  # server._rmod.confirmed_at
    rmod_needs_kind: Callable[..., Any]  # server._rmod.needs_kind
    rmod_options_of: Callable[..., Any]  # server._rmod.options_of
    rmod_parse_ask: Callable[..., Any]  # server._rmod.parse_ask
    rmod_whose: Callable[[], Any]  # server._rmod.WHOSE
    session_id: Callable[..., Any]  # server._session_id
    state_end: Callable[..., Any]  # holders._state_end
    zone: Callable[[], Any]  # server.ZONE


_hooks_: Hooks | None = None


def install(hooks: Hooks) -> None:
    """Server.py gives the wake passes what they still reach there (once, at its import)."""
    global _hooks_
    _hooks_ = hooks


def hooks() -> Hooks:
    if _hooks_ is None:
        raise RuntimeError("the wake passes have no hooks installed (server.py installs them at its import)")
    return _hooks_
