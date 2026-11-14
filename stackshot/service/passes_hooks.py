"""passes_hooks.py: what the page-debt call, the migrations and the fleet events still reach in web/server.py.

The page-debt call and its fallback to the page's keeper (`_pilot_fallback_tick`) live in service/page_debt.py, the start-up migrations and the migration route's passes in service/migrations.py, and the inbox flag and the fleet helpers in service/fleet_events.py. A few
things they use are still the surface's, because other code on the surface shares them: the ledger of the page debts and its lock, the grace minutes, the session ids, the project's -main and builder agents, the item
model's readers, the write path's flags, the stamp, retire and project-id passes the migration route dispatches to, the publish, and the time zone. They are reached through `Hooks`, which server.py fills once
with `install` (these modules cannot import server.py: the surface sits above them). A hook is looked up on server.py when it runs, so a suite that replaces one there reaches the passes; a suite that replaces a
function of the passes sets it on the module that owns it. A hook leaves this table when the area that holds it moves under service/.

Imports point down only: this module imports nothing of the package."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Hooks:
    """What the page-debt call, the migrations and the fleet events still reach outside service/, by the names they have there without the leading underscore. server.py builds one and gives it to `install`. A hook that reads a value is a function with no argument."""
    after_open: Callable[..., Any]  # item_read._after_open
    builder_agent: Callable[..., Any]  # agents._builder_agent
    grace_min: Callable[..., Any]  # server._grace_min
    main_agent: Callable[..., Any]  # agents._main_agent
    model_guards_on: Callable[..., Any]  # item_read._model_guards_on
    model_of: Callable[..., Any]  # item_read._model_of
    outcomes: Callable[[], Any]  # owner_words.OUTCOMES
    owed_brain_skip: Callable[..., Any]  # server._owed_brain_skip
    owed_lock: Callable[[], Any]  # server._OWED_LOCK
    owed_load: Callable[..., Any]  # server._owed_load
    owed_readable: Callable[..., Any]  # server._owed_readable
    owed_save: Callable[..., Any]  # server._owed_save
    owed_settle: Callable[..., Any]  # server._owed_settle
    pid_write_op: Callable[..., Any]  # server._pid_write_op
    publish: Callable[..., Any]  # web.publish._publish
    retire_write_op: Callable[..., Any]  # server._retire_write_op
    scoped_anchors: Callable[..., Any]  # item_read._scoped_anchors
    script_sender: Callable[..., Any]  # owner_words._script_sender
    sender_not_owner: Callable[..., Any]  # owner_words._sender_not_owner
    server_module: Callable[[], Any]  # the server module itself
    session_id: Callable[..., Any]  # server._session_id
    settle_apply: Callable[..., Any]  # holders._settle_apply
    shown_needs: Callable[..., Any]  # server._shown_needs
    stamp_write_op: Callable[..., Any]  # server._stamp_write_op
    switchover_on: Callable[..., Any]  # item_read._switchover_on
    watch_on_write: Callable[..., Any]  # server._watch_on_write
    zone: Callable[[], Any]  # server.ZONE

_hooks_: Hooks | None = None


def install(hooks: Hooks) -> None:
    """Server.py gives the page-debt call, the migrations and the fleet events what they still reach outside service/ (once, at its import)."""
    global _hooks_
    _hooks_ = hooks


def hooks() -> Hooks:
    if _hooks_ is None:
        raise RuntimeError("the page-debt call, the migrations and the fleet events have no hooks installed (server.py installs them at its import)")
    return _hooks_
