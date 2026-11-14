"""passes_hooks.py: what the page-debt call, the migrations, the fleet events, the client reads and the recycle bookkeeping still reach in web/server.py.

The page-debt call and its fallback to the page's keeper (`_pilot_fallback_tick`) live in service/page_debt.py, the start-up migrations and the migration route's passes in service/migrations.py, the inbox flag and the fleet helpers in service/fleet_events.py, the reads of the client API in
service/client_reads.py and the recycle bookkeeping in service/recycle.py (the merge-progress pass, service/merge_progress.py, reaches nothing here). A few
things they use are still the surface's, because other code on the surface shares them: the ledger of the page debts and its lock, the grace minutes, the session ids, the project's -main and builder agents, the item
model's readers, the write path's flags, the stamp, retire and project-id passes the migration route dispatches to, the publish, the time zone, the renderer's words and tests (the brief, a time in words, when an item was confirmed, a recycle wait and a hold for the recycle alone), the home page's list rule, the rulebook text, the notice's ruling and the report of holds, the page's time, the queue map and the board's ids as shown. They are reached through `Hooks`, which server.py fills once
with `install` (these modules cannot import server.py: the surface sits above them). A hook is looked up on server.py when it runs, so a suite that replaces one there reaches the passes; a suite that replaces a
function of the passes sets it on the module that owns it. A hook leaves this table when the area that holds it moves under service/.

Imports point down only: this module imports nothing of the package."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Hooks:
    """What the page-debt call, the migrations, the fleet events, the client reads and the recycle bookkeeping still reach outside service/, by the names they have there without the leading underscore. server.py builds one and gives it to `install`. A hook that reads a value is a function with no argument."""
    after_open: Callable[..., Any]  # item_read._after_open
    builder_agent: Callable[..., Any]  # agents._builder_agent
    grace_min: Callable[..., Any]  # server._grace_min
    holds_report: Callable[..., Any]  # server._holds_report
    home_agents: Callable[[], Any]  # web.home.AGENTS
    home_list_of: Callable[..., Any]  # web.home.list_of
    main_agent: Callable[..., Any]  # agents._main_agent
    model_guards_on: Callable[..., Any]  # item_read._model_guards_on
    model_of: Callable[..., Any]  # item_read._model_of
    notice_asked: Callable[..., Any]  # server._notice_asked
    notice_report: Callable[..., Any]  # server._notice_report
    outcomes: Callable[[], Any]  # owner_words.OUTCOMES
    owed_brain_skip: Callable[..., Any]  # server._owed_brain_skip
    owed_lock: Callable[[], Any]  # server._OWED_LOCK
    owed_load: Callable[..., Any]  # server._owed_load
    owed_readable: Callable[..., Any]  # server._owed_readable
    owed_save: Callable[..., Any]  # server._owed_save
    owed_settle: Callable[..., Any]  # server._owed_settle
    page_ts: Callable[..., Any]  # web.page_debts._page_ts
    pid_write_op: Callable[..., Any]  # server._pid_write_op
    publish: Callable[..., Any]  # web.publish._publish
    queue_map: Callable[..., Any]  # server._queue_map
    retire_write_op: Callable[..., Any]  # server._retire_write_op
    rmod_confirmed_at: Callable[..., Any]  # web.render.confirmed_at
    rmod_held_only_for_recycle: Callable[..., Any]  # web.render.held_only_for_recycle
    rmod_recycle_due: Callable[..., Any]  # web.render.recycle_due
    rmod_render: Callable[..., Any]  # web.render.render
    rmod_waits_recycle: Callable[..., Any]  # web.render.waits_recycle
    rmod_when_words: Callable[..., Any]  # web.render.when_words
    rules_text: Callable[..., Any]  # server._rules_text
    scoped_anchors: Callable[..., Any]  # item_read._scoped_anchors
    script_sender: Callable[..., Any]  # owner_words._script_sender
    sender_not_owner: Callable[..., Any]  # owner_words._sender_not_owner
    server_module: Callable[[], Any]  # the server module itself
    session_id: Callable[..., Any]  # server._session_id
    settle_apply: Callable[..., Any]  # holders._settle_apply
    shown_needs: Callable[..., Any]  # server._shown_needs
    shown_ref: Callable[..., Any]  # web.page_debts._shown_ref
    stamp_write_op: Callable[..., Any]  # server._stamp_write_op
    switchover_on: Callable[..., Any]  # item_read._switchover_on
    watch_on_write: Callable[..., Any]  # service.wait_gates._watch_on_write
    zone: Callable[[], Any]  # server.ZONE

_hooks_: Hooks | None = None


def install(hooks: Hooks) -> None:
    """Server.py gives the page-debt call, the migrations, the fleet events, the client reads and the recycle bookkeeping what they still reach outside service/ (once, at its import)."""
    global _hooks_
    _hooks_ = hooks


def hooks() -> Hooks:
    if _hooks_ is None:
        raise RuntimeError("the page-debt call, the migrations, the fleet events, the client reads and the recycle bookkeeping have no hooks installed (server.py installs them at its import)")
    return _hooks_
