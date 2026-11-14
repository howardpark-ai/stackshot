"""wiring.py: the server's wiring, what web/server.py hands every other area at its import: the hook tables of the service areas, the switches of the router and the queue, the GitHub mirror's hooks, the build of the MCP application.

The areas under service/ cannot import the surface, so each holds a `Hooks` table that this module fills once with `install`; the tables look up what they reach on the owner module when a hook runs, so a suite that replaces
a function on its owner reaches the passes. Three steps, called once each by web/server.py at its import, in this order (the order is part of what the server is, and tests/phase_sweep_scenario.py pins it):

  install_early(host)   the write path's steps, the GitHub mirror's two hooks, the default mover, the page gate's local-only switch, the router's and the queue's switches
  build()               the MCP application (web/app.py): FastMCP, the middleware, the tools and the routes, which take their callables from here, late-bound
  install_late()        the hand-off clock's name and the thirteen other hook tables

`server.py` runs as `__main__`, so this module cannot import it: `install_early` is handed the server module, which is the first owner of the `S` the passes written against it read (`pass_host` in the runner's table). Every hook of a table is looked up on the module that owns it
(`_late_in(module, "name")`, a `getattr` when the hook runs), never on the server module: a suite that replaces `_session_id`, `_owed_mark` and the like sets them on `stackshot.web.page_debts`, `_roles_sync_safe` on `stackshot.projects.project_registry`.
The comments above each table are the server's own, from where the tables were written: "this module" in them is the server module."""
from __future__ import annotations
import importlib
import time             # the clock `_busy_live` reads (`time.time`): a suite that pins the clock sets `time` on this module too
from types import SimpleNamespace
from typing import Any, Callable

from stackshot.core import config as _cfg
from stackshot.github import ghsync as _gh
from stackshot.waits import waiting as _wt
from stackshot.model import queued as _queued
from stackshot.model import holders as _holders
from stackshot.waits import handoff as _ho
from stackshot.service import runner as _runner
from stackshot.service import wakes as _wakes
from stackshot.service import watching as _watching
from stackshot.service import event_waits as _evwaits
from stackshot.service import wake_hooks as _wake_hooks
from stackshot.service import handoff as _handoff
from stackshot.service import handoff_hooks as _handoff_hooks
from stackshot.service import stall as _stallsvc
from stackshot.service import ladder as _laddersvc
from stackshot.service import stall_hooks as _stall_hooks
from stackshot.service import checks as _checks
from stackshot.service import released_live as _rlive
from stackshot.service import proofs as _proofs
from stackshot.service import released as _relsvc
from stackshot.service import checks_hooks as _checks_hooks
from stackshot.service import fleet_events as _fleetev
from stackshot.service import github_events as _github_events
from stackshot.service import retire_passes as _retire_passes
from stackshot.service import stamp as _stamp_svc
from stackshot.service import page_debt as _pdsvc
from stackshot.service import passes_hooks as _passes_hooks
from stackshot.service import client_reads as _client_reads
from stackshot.service import recycle as _recycle_svc
from stackshot.service import merge_progress as _merge_progress
from stackshot.web import home as _home
from stackshot.web import search as _search
from stackshot.web.tools import get as _tool_get
from stackshot.web.tools import notes as _tool_notes
from stackshot.web.tools import text as _wttext
from stackshot.web.tools.text import _ANCHOR_SHAPES, _ASK_NONE, _CLOSE_REFUSAL, _GMAIL_TERMS, _MODEL_PAGE
from stackshot.web.tools import rules as _rules_tool
from stackshot.core.instance import NAME
from stackshot.service import writes as _writes
from stackshot.service import telling as _telling
from stackshot.service import store as _svcstore
from stackshot.service import create as _create_svc
from stackshot.service import gates as _gates
from stackshot.service import update as _update_svc
from stackshot.service import item_read as _item_read
from stackshot.service import agents as _agents
from stackshot.service import contacts as _contacts
from stackshot.service import pane_recovery as _pane_recovery
from stackshot.service import mover_steps as _mover_steps
from stackshot.service import owner_words as _owner_words
from stackshot.service.owner_words import _BASIS_WORDS, _RELAUNCH, OUTCOMES
from stackshot.service import save_hooks as _save_hooks
from stackshot.service import agent_names as _agent_names
from stackshot.service import messaging as _messaging
from stackshot.service import asks as _asks
from stackshot.service import wait_fixes as _wait_fixes
from stackshot.service import wait_gates as _wait_gates
from stackshot.service import audit_ticks as _audit_ticks
from stackshot.service import answer_handover as _handover
from stackshot.service import answer as _answer_svc
from stackshot.web import answers as _answers_mod
from stackshot.web import page_debts as _pdebts
from stackshot.web.page_debts import _OWED_LOCK
from stackshot.web import render as _rmod
from stackshot.router import router_live as _router_live
from stackshot.projects import pages as _pages
from stackshot.anchors import event_log as _elog
from stackshot.fleet import sessions_registry as _sr
from stackshot.web import publish as _pubmod
from stackshot.web import middleware as _middleware
from stackshot.projects import project_registry as _project_registry
from stackshot.service import projects as _projects_svc
from stackshot.service import foryou_hooks as _foryou_hooks
from stackshot.service import event_activity as _event_activity
from stackshot.audit import audit_checks as _ac

_HOST: Any = None       # the server module, set by `install_early`: the first owner of the passes' `S` (`pass_host` below)

# The names the passes written against the server module (model/item_project_pass.py, model/last_activity_pass.py, waits/until_pass.py) read off their `S` that neither the server module nor service/stamp.py,
# service/retire_passes.py or service/merge_progress.py carries: the owners of the renderer, the pull-request event log and the merge pass. A suite or a tool that builds its own `stamp.PassHost` names this
# namespace as its last owner.
PASS_NAMES = SimpleNamespace(_rmod=_rmod, _elog=_elog, _merge_progress=_merge_progress)


def _late_in(module: Any, name: str) -> Callable[..., Any]:
    """A function of its owner module looked up when it is called (not when the table below is built), so a suite that replaces it on the owner reaches the create."""
    return lambda *a, **k: getattr(module, name)(*a, **k)


def _router_live_after(project: str, n: dict[str, Any]) -> None:
    """After the live router ruled a notice (router_live._act): what _route does after a keeper's ruling. A hold that waited on the
    notice's anchor is released on a passed or merged ruling (never a dropped or held one, as for a keeper's), and the board is
    republished."""
    if n.get("ruling") in ("passed", "merged"):
        _wakes.anchor_release(project, n, by=_router_live.BY)
    _pubmod._publish()


def _busy_live(gid: str, mover: str) -> str:
    """What of `mover`'s own runs on the item `gid` right now, in the words of the refusal of a hold on it (audit/busy_hold.py, service/gates.py `gate_busy_hold`): a running subagent of the mover tied to the item as the hourly audit
    ties one (`_audit_ticks._mover_subagents`, the anchors `_rlive.released_anchors`), else a release of a pull request tied to the item that is running (its unit `stackshot-release-<n>` active and its log written within 15 minutes: `release_units`,
    the anchors, the item's open steps and their status lines). "" when none is, or when it cannot be told (a mover whose subagents cannot be read is unknown, never a refusal)."""
    from stackshot.audit import busy_hold as _bh
    from stackshot.tools import next_report as _nr
    from stackshot.web.ui import releasing as _relu
    what = _bh.live_work(gid, mover, subagents=lambda who: _audit_ticks._mover_subagents(who), items=lambda: _nr.load_all(None), anchored=_rlive.released_anchors, same=_handoff.ho_same, shown=_nr.shown)
    return what or _bh.live_release(gid, units=_relu.release_units, anchored=_rlive.released_anchors, item=lambda g: _svcstore._load(g), own_repo=_relu.own_repo, canon=_cfg.canon_repo,
                                    step_prs=_relu.step_prs, log=_bh.release_log, now=time.time)


def _silence_mod() -> Any:
    """audit/silence.py, imported when a hook runs (as the passes of this module import it: the audit modules load lazily)."""
    from stackshot.audit import silence as _silence
    return _silence


def _next_report_mod() -> Any:
    """tools/next_report.py, imported when a hook runs."""
    from stackshot.tools import next_report as _nrep
    return _nrep


def _front_held(*a: Any, **k: Any) -> Any:
    """audit/front_step.held, imported when it is called: the gates are service/ and import no audit/."""
    from stackshot.audit import front_step as _fs  # noqa: PLC0415
    return _fs.held(*a, **k)


def install_early(host: Any) -> None:
    """The first step: the write path's steps, the GitHub mirror's hooks, the default mover, the page gate's switch and the router's and queue's switches. `host` is the server module, the first owner of the passes' `S` (`pass_host`)."""
    global _HOST
    _HOST = host

    # The steps of a save whose code is still on this module (service/writes.py runs them in its order). Each is looked up when a save runs, so a suite that replaces one on this module reaches the save;
    # one leaves this table when the area that holds it moves under service/.
    _writes.install(_writes.Steps(
        settle_mover=lambda item, before: _mover_steps._settle_mover_on_save(item, before),
        owner_steps=lambda item, before, writer, author: _mover_steps._owner_steps_on_save(item, before, writer, author),
        ask_stamp=lambda item, before, writer: _asks._ask_stamp(item, before, writer),
        handoff_on_save=lambda gid, before, item, writer, author: _handoff.handoff_on_save(gid, before, item, writer, author),
        handoff_his_over=lambda gid, item, author, quiet: _handoff.handoff_his_over(gid, item, author, quiet),
        handoff_follow=lambda gid, before, item, writer, author, quiet: _handoff.handoff_follow(gid, before, item, writer, author, quiet),
        phase_stamp=lambda gid, item: _stamp_svc._phase_stamp(gid, item),
        search_touch=lambda gid: _search.touch(gid),
        handback_drop=lambda gid, why: _telling.handback_drop(gid, why),
        answer_ack=lambda gid, writer: _answer_svc._answer_ack(gid, writer),
    ))

    _gh.on_rekey = _github_events._rekeyed

    _gh.on_comment = _github_events._github_comment

    _wt.FALLBACK_MOVER = _telling.fallback_mover        # model.derive and waiting.mover_of read the default mover through this (the server alone can read the project registry)

    _pages.LOCAL_ONLY = True   # the server answers the client API, so pages._api must never call it (a request to itself from the event loop stalls every request until its timeout)

    # the router's live mode reaches the server only through these three (router_live.configure): which agents are front ones, the push,
    # and the call after a ruling. `PUSH` is read at each call, so a test's fake push is the one used.
    _router_live.configure(is_front=lambda who, project: _telling.front_keeper(who, project)[0],
                           deliver=lambda target, text: _agent_names._router_delivered(target, text, _router_live.deliver_via(_telling.PUSH, target, text)),
                           after_rule=_router_live_after)

    _queued.configure(is_front=lambda who, project: _telling.front_keeper(who, project, True)[0])      # the board's rendering asks the same question the passes' environment answers


def build() -> Any:
    """The second step: the MCP application (web/app.py). The tools and the routes take these callables, each looked up on its owner when it is called."""
    from stackshot.web import app as _app  # noqa: PLC0415  — imported here, as the server imported it just before the build
    return _app.build(
        handoff_brief=lambda *a, **k: _handoff.handoff_brief(*a, **k),
        is_parked=lambda *a, **k: _item_read._is_parked(*a, **k),
        evwait_preread=lambda *a, **k: _wait_gates._evwait_preread(*a, **k),
        sender_not_owner=lambda *a, **k: _owner_words._sender_not_owner(*a, **k),
        ask_after_write=lambda *a, **k: _asks._ask_after_write(*a, **k),
        update=lambda *a, **k: _update_svc._update(*a, **k),
        busy_live=lambda *a, **k: _busy_live(*a, **k),
        fleet_names=lambda *a, **k: _fleetev.fleet_names(*a, **k),
        inbox_flag_minutes=lambda *a, **k: _fleetev.inbox_flag_minutes(*a, **k),
        message=lambda *a, **k: _messaging._message(*a, **k),
        anchor_release=lambda *a, **k: _wakes.anchor_release(*a, **k),
        watch_label=lambda *a, **k: _watching.watch_label(*a, **k),
        evw_boxes=lambda *a, **k: _evwaits.evw_boxes(*a, **k),
        machine_state=lambda *a, **k: _evwaits.machine_state(*a, **k),
        main_agent=lambda *a, **k: _agents._main_agent(*a, **k),
        client_get=lambda *a, **k: _client_reads._client_get(*a, **k),
        recycle_wanted_tokens=lambda *a, **k: _recycle_svc._recycle_wanted_tokens(*a, **k),
        answer=lambda *a, **k: _answer_svc._answer(*a, **k),
        contact_label=lambda *a, **k: _contacts._contact_label(*a, **k),
        runner_status=lambda *a, **k: _runner.status(*a, **k),
        phase_sweep_status=lambda *a, **k: _stamp_svc._phase_sweep_status(*a, **k),
    )


def install_late() -> None:
    """The third step: the hand-off clock's name and the hook tables of the service areas, in the order they were installed."""
    # ----------------------------------------------------------------------------- the hand-off machinery (service/handoff.py, service/handoff_cold.py)
    # The hand-off record, its delivery, the minute pass, the cold call and the display are service/handoff.py's and service/handoff_cold.py's. What stays here is the item model's switch
    # and the reader of one item the hooks of those modules and of the wake passes share.
    _ho.SERVER = NAME

    # What the item readers still reach (service/item_read.py): the board renderer's two rules, which a service module cannot import. A hook leaves this table when the renderer's rule moves under model/.
    _item_read.install(_item_read.Hooks(
        is_held=_late_in(_rmod, "is_held"),
        needs_kind=_late_in(_rmod, "needs_kind"),
    ))

    # What the telling still reaches (service/telling.py tells the sessions a write concerns): the hand-off record's own functions (service/handoff.py imports the telling, so the telling cannot import it back: each
    # is looked up on that module when it runs), the page keepers of a project's agents, the page debt's marks and the time zone. A hook leaves this table when the area that holds it
    # moves under service/ and does not import the telling.
    _telling.install(_telling.Hooks(
        back_agent=_late_in(_agent_names, "_back_agent"),
        builder_for=_late_in(_agents, "_builder_for"),
        check_changed=lambda *a, **k: _checks.check_changed(*a, **k),
        check_lane_shown=lambda *a, **k: _checks.check_lane_shown(*a, **k),
        debt_mover=_late_in(_pdebts, "_debt_mover"),
        front_handed_by_peer=lambda *a, **k: _handoff.front_handed_by_peer(*a, **k),
        grace_min=_late_in(_pdebts, "_grace_min"),
        handoff_builder=lambda *a, **k: _handoff.handoff_builder(*a, **k),
        handoff_on=lambda *a, **k: _handoff.handoff_on(*a, **k),
        handoff_pane_row=lambda *a, **k: _handoff.handoff_pane_row(*a, **k),
        handoff_pushed=lambda *a, **k: _handoff.handoff_pushed(*a, **k),
        handoff_text=lambda *a, **k: _handoff.handoff_text(*a, **k),
        handoff_told_text=lambda *a, **k: _handoff.handoff_told_text(*a, **k),
        ho_same=lambda *a, **k: _handoff.ho_same(*a, **k),
        main_agent=_late_in(_agents, "_main_agent"),
        model_of=_late_in(_item_read, "_model_of"),
        owed_mark=_late_in(_pdebts, "_owed_mark"),
        rmod_outcome_word=lambda *a, **k: _rmod.outcome_word(*a, **k),
        role_name=_late_in(_sr, "_role_name"),
        same_sess=_late_in(_sr, "_same_sess"),
        session_id=_late_in(_pdebts, "_session_id"),
        shown_needs=_late_in(_pdebts, "_shown_needs"),
        zone=lambda: _wttext.ZONE,
    ))

    # What the minute set still reaches on this module (service/runner.py holds the tick table and the background threads): the tick functions that have not moved yet and the publish. A hook leaves this table when the area
    # that holds it moves under service/ (the wake, anchor and event wait ticks are service/wakes.py's and service/event_waits.py's, imported by the table).
    _runner.install(_runner.Hooks(
        phase_tick=_late_in(_stamp_svc, "_phase_tick"),
        balance_tick=_late_in(_audit_ticks, "_balance_tick"),
        answer_tick=_late_in(_answer_svc, "_answer_tick"),
        roles_sync_safe=_late_in(_project_registry, "_roles_sync_safe"),
        pilot_fallback_tick=_late_in(_pdsvc, "_pilot_fallback_tick"),
        filing_tick=_late_in(_audit_ticks, "_filing_tick"),
        dates_tick=_late_in(_audit_ticks, "_dates_tick"),
        silence_tick=_late_in(_audit_ticks, "_silence_tick"),
        archive_tick=_late_in(_audit_ticks, "_archive_tick"),
        publish=_late_in(_pubmod, "_publish"),
        publish_now=_late_in(_pubmod, "_publish_now"),
        publish_every=_late_in(_pubmod, "_publish_every"),
    ))

    # What the wake passes, the watchers and the event waits still reach on this module (service/wakes.py, service/watching.py and service/event_waits.py): the item model's readers that other areas share, the
    # proof and release readers, the renderer's answers, the publish and the time zone. A hook leaves this table when the area that holds it moves under service/.
    _wake_hooks.install(_wake_hooks.Hooks(
        after_open=_late_in(_item_read, "_after_open"),
        event_activity_tick=_late_in(_event_activity, "_event_activity_tick"),
        follow_superseded=_late_in(_mover_steps, "_follow_superseded"),
        hand_stored_then=_late_in(_handover, "_hand_stored_then"),
        hold_flag=_late_in(_holders, "_hold_flag"),
        is_held=_late_in(_holders, "_is_held"),
        item_mover_model=_late_in(_client_reads, "_item_mover_model"),
        load_or_none=_late_in(_item_read, "_load_or_none"),
        merge_progress_tick=_late_in(_merge_progress, "_merge_progress_tick"),
        merge_tied=_late_in(_merge_progress, "_merge_tied"),
        model_of=_late_in(_item_read, "_model_of"),
        old_wait_off=_late_in(_item_read, "_old_wait_off"),
        own_repo=_late_in(_relsvc, "_own_repo"),
        publish=_late_in(_pubmod, "_publish"),
        rmod_confirmed_at=lambda *a, **k: _rmod.confirmed_at(*a, **k),
        rmod_needs_kind=lambda *a, **k: _rmod.needs_kind(*a, **k),
        rmod_options_of=lambda *a, **k: _rmod.options_of(*a, **k),
        rmod_parse_ask=lambda *a, **k: _rmod.parse_ask(*a, **k),
        rmod_whose=lambda: _rmod.WHOSE,
        session_id=_late_in(_pdebts, "_session_id"),
        state_end=_late_in(_holders, "_state_end"),
        zone=lambda: _wttext.ZONE,
    ))

    # What the hand-off passes still reach on this module (service/handoff.py and service/handoff_cold.py): the write gates and limits, the item model's reader and its switch, the stall pass and the one ladder,
    # the recovery request, the page store, the publish and the session ids. A hook leaves this table when the area that holds it moves under service/.
    _handoff_hooks.install(_handoff_hooks.Hooks(
        after_open=_late_in(_item_read, "_after_open"),
        front_pair_ok=_late_in(_holders, "_front_pair_ok"),
        item_refs=_late_in(_agent_names, "_item_refs"),
        ladder_enter=lambda *a, **k: _laddersvc.ladder_enter(*a, **k),
        ladder_first=lambda *a, **k: _laddersvc.ladder_first(*a, **k),
        ladder_on=lambda *a, **k: _laddersvc.ladder_on(*a, **k),
        laddered=lambda *a, **k: _laddersvc.laddered(*a, **k),
        load_or_none=_late_in(_item_read, "_load_or_none"),
        model_of=_late_in(_item_read, "_model_of"),
        old_wait_off=_late_in(_item_read, "_old_wait_off"),
        page_io=_late_in(_projects_svc, "_page_io"),
        publish=_late_in(_pubmod, "_publish"),
        recovery_role=lambda: _pane_recovery._RECOVERY_ROLE,
        recovery_target=_late_in(_pane_recovery, "_recovery_target"),
        recovery_tell=_late_in(_pane_recovery, "_recovery_tell"),
        role_name=_late_in(_sr, "_role_name"),
        role_of=_late_in(_holders, "_role_of"),
        scoped_anchors=_late_in(_item_read, "_scoped_anchors"),
        session_id=_late_in(_pdebts, "_session_id"),
        stall_confirm=lambda *a, **k: _stallsvc.stall_confirm(*a, **k),
        stall_load=lambda *a, **k: _stallsvc.stall_load(*a, **k),
        stall_lock=lambda: _stallsvc.STALL_LOCK,
        stall_save=lambda *a, **k: _stallsvc.stall_save(*a, **k),
        stall_ver=lambda *a, **k: _stallsvc.stall_ver(*a, **k),
        switchover_on=_late_in(_item_read, "_switchover_on"),
        update=_late_in(_update_svc, "_update"),
    ))

    # What the stall pass and the one ladder still reach outside service/ (service/stall.py, service/ladder.py and service/stall_tick.py): the open-item and wait reader, the project's -main agent, the queue map, the publish,
    # the session ids and names, the time zone and the words for a time, and the activity clock and the step status of the audit (audit/ and tools/ are imported when a hook runs). A hook leaves this table when the area that
    # holds it moves under service/.
    _stall_hooks.install(_stall_hooks.Hooks(
        after_open=_late_in(_item_read, "_after_open"),
        main_agent=_late_in(_agents, "_main_agent"),
        next_report_all=lambda *a, **k: _next_report_mod().load_all(*a, **k),
        publish=_late_in(_pubmod, "_publish"),
        queue_map=_late_in(_audit_ticks, "_queue_map"),
        role_name=_late_in(_sr, "_role_name"),
        session_id=_late_in(_pdebts, "_session_id"),
        silence_clock=lambda *a, **k: _silence_mod().clock(*a, **k),
        silence_minutes=lambda *a, **k: _silence_mod().minutes(*a, **k),
        silence_subagent_running=lambda *a, **k: _silence_mod().subagent_running(*a, **k),
        when_words=lambda *a, **k: _rmod.when_words(*a, **k),
        zone=lambda: _wttext.ZONE,
    ))

    # What the done check, the release settle and the step proofs still reach outside service/ (service/checks.py, service/released_live.py, service/released.py and service/proofs.py): this checkout's repository and
    # the pull-request key, the hold readers of the item model, the publish, the session ids and rosters, the write gates' field limits, the renderer's answer for whose move it is and the mark of a wait the server set
    # back. A hook leaves this table when the area that holds it moves under service/.
    _checks_hooks.install(_checks_hooks.Hooks(
        date_parked=_late_in(_item_read, "_date_parked"),
        hold_flag=_late_in(_holders, "_hold_flag"),
        is_held=_late_in(_holders, "_is_held"),
        own_repo=_late_in(_relsvc, "_own_repo"),
        pr_key=_late_in(_relsvc, "_pr_key"),
        pr_url=lambda: _relsvc._PR_URL,
        publish=_late_in(_pubmod, "_publish"),
        rmod_needs_kind=lambda *a, **k: _rmod.needs_kind(*a, **k),
        role_name=_late_in(_sr, "_role_name"),
        same_sess=_late_in(_sr, "_same_sess"),
        session_down=_late_in(_pane_recovery, "_session_down"),
        session_id=_late_in(_pdebts, "_session_id"),
        session_roster=_late_in(_agents, "_session_roster"),
        wait_end_sent_back=_late_in(_wait_fixes, "_wait_end_sent_back"),
    ))

    # What the page-debt call, the migrations, the fleet events, the client reads and the recycle bookkeeping still reach on this module (service/page_debt.py, service/migrations.py, service/fleet_events.py,
    # service/client_reads.py, service/recycle.py): the ledger of the page debts, the grace minutes, the session ids, the project's agents, the item model's readers, and for the client reads and the recycle the
    # renderer's words and tests, the home page's list rule, the rulebook text, the notice's ruling and the holds report, the page's time and the queue map. A hook leaves this table when the area that holds it moves under service/.
    _passes_hooks.install(_passes_hooks.Hooks(
        after_open=_late_in(_item_read, "_after_open"),
        builder_agent=_late_in(_agents, "_builder_agent"),
        grace_min=_late_in(_pdebts, "_grace_min"),
        holds_report=lambda *a, **k: _tool_notes._holds_report(*a, **k),
        home_agents=lambda: _home.AGENTS,
        home_list_of=lambda *a, **k: _home.list_of(*a, **k),
        main_agent=_late_in(_agents, "_main_agent"),
        model_guards_on=_late_in(_item_read, "_model_guards_on"),
        model_of=_late_in(_item_read, "_model_of"),
        notice_asked=lambda *a, **k: _tool_get._notice_asked(*a, **k),
        notice_report=lambda *a, **k: _tool_get._notice_report(*a, **k),
        outcomes=lambda: OUTCOMES,
        owed_brain_skip=_late_in(_pdebts, "_owed_brain_skip"),
        owed_lock=lambda: _OWED_LOCK,
        owed_load=_late_in(_pdebts, "_owed_load"),
        owed_readable=_late_in(_pdebts, "_owed_readable"),
        owed_save=_late_in(_pdebts, "_owed_save"),
        owed_settle=_late_in(_pdebts, "_owed_settle"),
        page_ts=lambda *a, **k: _pdebts._page_ts(*a, **k),      # the owner module's own function, looked up at each call: a suite that puts a page's time in place of the real one sets it on page_debts
        pass_host=lambda: _stamp_svc.PassHost(_HOST, _stamp_svc, _retire_passes, _merge_progress, PASS_NAMES),
        pid_write_op=_late_in(_stamp_svc, "_pid_write_op"),
        publish=_late_in(_pubmod, "_publish"),
        queue_map=_late_in(_audit_ticks, "_queue_map"),
        retire_write_op=_late_in(_retire_passes, "_retire_write_op"),
        rmod_confirmed_at=lambda *a, **k: _rmod.confirmed_at(*a, **k),
        rmod_held_only_for_recycle=lambda *a, **k: _rmod.held_only_for_recycle(*a, **k),
        rmod_recycle_due=lambda *a, **k: _rmod.recycle_due(*a, **k),
        rmod_render=lambda *a, **k: _rmod.render(*a, **k),
        rmod_waits_recycle=lambda *a, **k: _rmod.waits_recycle(*a, **k),
        rmod_when_words=lambda *a, **k: _rmod.when_words(*a, **k),
        rules_text=_late_in(_rules_tool, "_rules_text"),
        scoped_anchors=_late_in(_item_read, "_scoped_anchors"),
        script_sender=_late_in(_owner_words, "_script_sender"),
        sender_not_owner=_late_in(_owner_words, "_sender_not_owner"),
        session_id=_late_in(_pdebts, "_session_id"),
        settle_apply=_late_in(_holders, "_settle_apply"),
        shown_needs=lambda *a, **k: _pdebts._shown_needs(*a, **k),
        shown_ref=lambda *a, **k: _pdebts._shown_ref(*a, **k),
        stamp_write_op=_late_in(_stamp_svc, "_stamp_write_op"),
        switchover_on=_late_in(_item_read, "_switchover_on"),
        watch_on_write=_late_in(_wait_gates, "_watch_on_write"),
        zone=lambda: _wttext.ZONE,
    ))

    # What the For you rows still reach on this module (service/foryou_events.py): the debounced publish of the board, the page's parser of an ask line and the words for a date. A hook leaves this table when the
    # area that holds it moves under service/.
    _foryou_hooks.install(_foryou_hooks.Hooks(
        parse_ask=lambda *a, **k: _rmod.parse_ask(*a, **k),
        publish=_late_in(_pubmod, "_publish"),
        when_words=lambda *a, **k: _rmod.when_words(*a, **k),
    ))

    # What the save steps and the owner's words still reach outside service/ (service/mover_steps.py and service/owner_words.py): the debounced publish of the board, the session id of a name, the audit's broad wait words, the words
    # for a time and the time zone. A hook leaves this table when the area that holds it moves under service/.
    _save_hooks.install(_save_hooks.Hooks(
        anchor_shapes=lambda: _ANCHOR_SHAPES,
        answer_deliver=_late_in(_answer_svc, "_answer_deliver"),
        answer_note=_late_in(_answers_mod, "_answer_note"),
        answers_mod=lambda: _answers_mod,
        answers_of=lambda *a, **k: _rmod.answers_of(*a, **k),
        ask_form=lambda: _rmod.ASK_FORM,
        ask_max=lambda: _rmod.ASK_MAX,
        ask_none=lambda: _ASK_NONE,
        audit_mod=lambda name: importlib.import_module(f"stackshot.audit.{name}"),
        gmail_terms=lambda: _GMAIL_TERMS,
        msg_max=lambda: _wttext.MSG_MAX,
        next_report_all=lambda *a, **k: _next_report_mod().load_all(*a, **k),
        option_label_max=lambda: _rmod.OPTION_LABEL_MAX,
        option_line_max=lambda: _rmod.OPTION_LINE_MAX,
        options_max=lambda: _rmod.OPTIONS_MAX,
        options_min=lambda: _rmod.OPTIONS_MIN,
        options_of=lambda *a, **k: _rmod.options_of(*a, **k),
        parse_ask=lambda *a, **k: _rmod.parse_ask(*a, **k),
        publish=_late_in(_pubmod, "_publish"),
        session_id=_late_in(_pdebts, "_session_id"),
        unlink_ids=_late_in(_middleware, "_unlink_ids"),
        wait_words=lambda *a, **k: _ac.wait_words(*a, **k),
        when_words=lambda *a, **k: _rmod.when_words(*a, **k),
        yesno_options=lambda *a, **k: _rmod.yesno_options(*a, **k),
        zone=lambda: _wttext.ZONE,
    ))

    # What a create still reaches on this module (service/create.py runs the create in its order): the gates and notices the update tool, the close and the telling share, the three thread-local flags
    # and two constants. A hook leaves this table when the area that holds it moves under service/.
    _create_svc.install(_create_svc.Hooks(
        after_open=_late_in(_item_read, "_after_open"),
        anchor_wait_gate=_late_in(_wait_gates, "_anchor_wait_gate"),
        ask_owed=_late_in(_asks, "_ask_owed"),
        contact_default=_late_in(_contacts, "_contact_default"),
        evwait_gate=_late_in(_wait_gates, "_evwait_gate"),
        fallback_wait_date=_late_in(_wait_fixes, "_fallback_wait_date"),
        fmt=_late_in(_tool_get, "_fmt"),
        form_notes=_late_in(_tool_notes, "_form_notes"),
        gate_ask=_late_in(_asks, "_gate_ask"),
        gate_options=_late_in(_wait_gates, "_gate_options"),
        lift_ask=_late_in(_asks, "_lift_ask"),
        machine_note=_late_in(_wait_gates, "_machine_note"),
        model_guards_on=_late_in(_item_read, "_model_guards_on"),
        nag=lambda *a, **k: _pdebts._nag(*a, **k),      # the owner module's own function, looked up at each call: a suite that replaces it in page_debts reaches the create and the update
        next_put=_late_in(_asks, "_next_put"),
        owed_mark=_late_in(_pdebts, "_owed_mark"),
        owner_then_default=_late_in(_mover_steps, "_owner_then_default"),
        parse_wake=lambda *a, **k: _wakes.parse_wake(*a, **k),
        publish=_late_in(_pubmod, "_publish"),
        record_fixes=_late_in(_wait_fixes, "_record_fixes"),
        refuse_if_owing=_late_in(_pdebts, "_refuse_if_owing"),
        said_note=_late_in(_owner_words, "_said_note"),
        session_id=_late_in(_pdebts, "_session_id"),
        wait_alias_gate=_late_in(_wait_fixes, "_wait_alias_gate"),
        wake_at=lambda *a, **k: _wakes.wake_at(*a, **k),
        writer_owes=_late_in(_pdebts, "_writer_owes"),
        ask_none=_ASK_NONE,
    ))

    # What the write gates still reach on this module (service/gates.py holds them): the helpers of the areas still here (the hand-off machinery, the roster and the contact lookups, the effective state, the wake parser,
    # the anchors scoped to an item), the checks that sit in web/ and the per-write flags. A hook leaves this table when the area that holds it moves under service/.
    _gates.install(_gates.Hooks(
        after_open=_late_in(_item_read, "_after_open"),
        after_reaches=_late_in(_mover_steps, "_after_reaches"),
        answers_of=lambda *a, **k: _rmod.answers_of(*a, **k),
        ask_none=_ASK_NONE,
        ask_stands=_late_in(_asks, "_ask_stands"),
        basis_words=_BASIS_WORDS,
        close_refusal=_CLOSE_REFUSAL,
        contact_alive=_late_in(_contacts, "_contact_alive"),
        contact_fronts=_late_in(_contacts, "_contact_fronts"),
        contact_same=_late_in(_contacts, "_contact_same"),
        eff_state=_late_in(_mover_steps, "_eff_state"),
        follow_superseded=_late_in(_mover_steps, "_follow_superseded"),
        front_held=lambda *a, **k: _front_held(*a, **k),      # this module's own function, looked up at each call (it was the server's, looked up on it at each call)
        front_pair_ok=_late_in(_holders, "_front_pair_ok"),
        handoffs_in=_late_in(_agents, "_handoffs_in"),
        handover_kind=lambda *a, **k: _proofs.handover_kind(*a, **k),
        hub_sessions=_late_in(_item_read, "_hub_sessions"),
        item_mover=_late_in(_client_reads, "_item_mover"),
        main_agent=_late_in(_agents, "_main_agent"),
        model_guards_on=_late_in(_item_read, "_model_guards_on"),
        model_page=_MODEL_PAGE,
        open_item_named=_late_in(_item_read, "_open_item_named"),
        outcomes=OUTCOMES,
        own_repo=_late_in(_relsvc, "_own_repo"),
        owner_words_on=_late_in(_owner_words, "_owner_words_on"),
        parse_wake=lambda *a, **k: _wakes.parse_wake(*a, **k),
        relaunch=_RELAUNCH,
        role_of=_late_in(_holders, "_role_of"),
        same_sess=_late_in(_sr, "_same_sess"),
        scoped_anchors=_late_in(_item_read, "_scoped_anchors"),
        session_id=_late_in(_pdebts, "_session_id"),
        session_roster=_late_in(_agents, "_session_roster"),
        shown_ref=_late_in(_pdebts, "_shown_ref"),
        store_ref=_late_in(_sr, "_store_ref"),
        wake_at=lambda *a, **k: _wakes.wake_at(*a, **k),
        when_words=lambda *a, **k: _rmod.when_words(*a, **k),
        zone=lambda: _wttext.ZONE,
    ))

    # What an update still reaches on this module (service/update.py runs the update in its order): the gates and notices the create tool, the close and the telling share, the per-write flags and a few constants.
    # A hook leaves this table when the area that holds it moves under service/.
    _update_svc.install(_update_svc.Hooks(
        after_open=_late_in(_item_read, "_after_open"),
        anchor_wait_gate=_late_in(_wait_gates, "_anchor_wait_gate"),
        ask_none=_ASK_NONE,
        ask_owed=_late_in(_asks, "_ask_owed"),
        basis_put=_late_in(_owner_words, "_basis_put"),
        basis_words=_BASIS_WORDS,
        cap_ok_drop=_late_in(_owner_words, "_cap_ok_drop"),
        cap_ok_put=_late_in(_owner_words, "_cap_ok_put"),
        contact_alive=_late_in(_contacts, "_contact_alive"),
        contact_fronts=_late_in(_contacts, "_contact_fronts"),
        contact_same=_late_in(_contacts, "_contact_same"),
        date_only_wait=_late_in(_wait_fixes, "_date_only_wait"),
        date_parked=_late_in(_item_read, "_date_parked"),
        eff_state=_late_in(_mover_steps, "_eff_state"),
        evwait_gate=_late_in(_wait_gates, "_evwait_gate"),
        evwait_preread=_late_in(_wait_gates, "_evwait_preread"),
        fallback_wait_date=_late_in(_wait_fixes, "_fallback_wait_date"),
        finishes_own_line=_late_in(_holders, "_finishes_own_line"),
        fmt=_late_in(_tool_get, "_fmt"),
        form_notes=_late_in(_tool_notes, "_form_notes"),
        gate_ask=_late_in(_asks, "_gate_ask"),
        gate_options=_late_in(_wait_gates, "_gate_options"),
        handoffs_in=_late_in(_agents, "_handoffs_in"),
        hold_held_by=_late_in(_wait_fixes, "_hold_held_by"),
        hold_set=_late_in(_wait_fixes, "_hold_set"),
        is_held=_late_in(_holders, "_is_held"),
        lift_ask=_late_in(_asks, "_lift_ask"),
        machine_note=_late_in(_wait_gates, "_machine_note"),
        main_agent=_late_in(_agents, "_main_agent"),
        model_apply=_late_in(_holders, "_model_apply"),
        model_guards_on=_late_in(_item_read, "_model_guards_on"),
        model_of=_late_in(_item_read, "_model_of"),
        nag=lambda *a, **k: _pdebts._nag(*a, **k),      # the owner module's own function, looked up at each call: a suite that replaces it in page_debts reaches the create and the update
        name_on_write=_late_in(_agent_names, "_name_on_write"),
        next_put=_late_in(_asks, "_next_put"),
        owed_mark=_late_in(_pdebts, "_owed_mark"),
        owner_quote_on=_late_in(_owner_words, "_owner_quote_on"),
        owner_state_mover=_late_in(_mover_steps, "_owner_state_mover"),
        owner_then_default=_late_in(_mover_steps, "_owner_then_default"),
        owner_want=_late_in(_holders, "_owner_want"),
        parse_wake=lambda *a, **k: _wakes.parse_wake(*a, **k),
        publish=_late_in(_pubmod, "_publish"),
        record_fixes=_late_in(_wait_fixes, "_record_fixes"),
        refuse_if_owing=_late_in(_pdebts, "_refuse_if_owing"),
        release_after=lambda *a, **k: _wakes.release_after(*a, **k),
        render_hold_at=lambda *a, **k: _rmod.hold_at(*a, **k),
        render_option_lines=lambda *a, **k: _rmod.option_lines(*a, **k),
        render_same_ref=lambda *a, **k: _rmod.same_ref(*a, **k),
        render_when_words=lambda *a, **k: _rmod.when_words(*a, **k),
        said_note=_late_in(_owner_words, "_said_note"),
        scoped_anchors=_late_in(_item_read, "_scoped_anchors"),
        session_id=_late_in(_pdebts, "_session_id"),
        session_roster=_late_in(_agents, "_session_roster"),
        state_apply=_late_in(_mover_steps, "_state_apply"),
        state_end=_late_in(_holders, "_state_end"),
        store_ref=_late_in(_sr, "_store_ref"),
        switchover_on=_late_in(_item_read, "_switchover_on"),
        update=_late_in(_update_svc, "_update"),
        wait_end_sent_back=_late_in(_wait_fixes, "_wait_end_sent_back"),
        wake_at=lambda *a, **k: _wakes.wake_at(*a, **k),
        wake_event_set=lambda: _runner.WAKE_EVENT.set(),
        wake_park_line=_late_in(_wait_fixes, "_wake_park_line"),
        wake_step_note=_late_in(_wait_fixes, "_wake_step_note"),
        wake_window_note=_late_in(_wait_fixes, "_wake_window_note"),
        watch_on_write=_late_in(_wait_gates, "_watch_on_write"),
        writer_owes=_late_in(_pdebts, "_writer_owes"),
        zone=lambda: _wttext.ZONE,      # looked up when the reply is made, as the confirm tool did before the move
    ))
