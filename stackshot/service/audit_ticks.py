"""audit_ticks.py: the ten-minute audit ticks and the minute balancer, the server's own half of the audit.

The audit decides in audit/ (the pure halves: audit_checks, audit_run, hourly, busy_tell, hand_idle, front_handon, front_pickup, silence, subagent_tie) and the server writes and sends: this module is the writing half, run by the minute set
(service/runner.py) through its table. The ten-minute filing pass (`_filing_tick`), the dates pass (`_dates_tick`, with the expected-time look `_dates_expected_tick` and the For you list's due-date look it opens),
the minute wait-loop walk (`_loop_tick`), the archive sweep (`_archive_tick`) and the audit tick (`_silence_tick`: the hourly audit line `_hourly_tick`, the idle hand-over `_hand_idle_tick`, the hand-on of an idle front agent's item to a free background agent `_front_handon_tick`, its fallback, the idle front agent's turn `_front_pickup_tick`, the long-busy message `_busy_tell_tick`, the anchors' daily pass `_anchor_daily_tick`) are here, and the
balancer (`_balance_tick`, its own minute tick) with the reads it shares: `_silence_env`, the environment every audit pass is built with; `_queue_map`, who is queued behind another item, kept `_QUEUE_TTL` seconds in
`_QUEUE_CACHE`; `_agent_state` and `_mover_subagents`, a mover's busy or idle and its running subagents as the fleet's session manager last pushed them (service/agent_state.py); and `_BALANCE_LOGGED`, the stderr lines the balancer throttles.

A service module: it reads the store and writes an item only through `writes.save`, under the item lock. The debounced publish of the board, the session id of a name, the audit's modules and the open items'
reader of tools/ (audit/ and tools/ sit outside the layers) are the surface's or the audit's, reached through service/save_hooks.py when a pass runs. A suite that replaces one of these sets it on this module
(and `time` here, since this module reads its own; the module state `_QUEUE_CACHE` and `_BALANCE_LOGGED` is reset here too).

Imports point down only: this module imports the domain, core and the services beside it, never web/, audit/ and tools/."""
from __future__ import annotations

import datetime as dt
import sys
import threading
import time
from typing import Any, Callable, Iterable

from stackshot.anchors import anchors as _anc
from stackshot.anchors import groundskeeper as _gk
from stackshot.core import agentbox as _ab
from stackshot.core import config as _cfg
from stackshot.core import instance as _inst
from stackshot.core import readonly as _ro
from stackshot.core.instance import OWNER
from stackshot.fleet import sessions_registry as _sr
from stackshot.github import ghsync as _gh
from stackshot.model import model as _model
from stackshot.model import queued as _queued
from stackshot.projects import project_archive as _archive
from stackshot.projects import projects as _prj
from stackshot.projects.project_registry import _registry
from stackshot.router import router as _router
from stackshot.service import agents as _agents
from stackshot.service import fleet_events as _fleetev
from stackshot.service import foryou_events as _fyev
from stackshot.service import front_turn as _front_turn
from stackshot.service import handoff as _handoff
from stackshot.service import item_read as _item_read
from stackshot.service import ladder as _laddersvc
from stackshot.service import released_live as _rlive
from stackshot.service import store as _svcstore
from stackshot.service import telling as _telling
from stackshot.service import wait_fixes as _wait_fixes
from stackshot.service import wait_gates as _wait_gates
from stackshot.service import writes as _writes
from stackshot.service.projects import _page_io
from stackshot.service.save_hooks import hooks as _hooks
from stackshot.waits import handoff as _ho
from stackshot.waits import stall as _stall


def _filing_tick() -> "dict[str, Any] | None":
    """The ten-minute filing pass (audit_run.filing_pass over audit_checks.filing_findings): is each open item filed in the right state? A finding goes to its mover once, as the daily
    audit sends one. Stands still when the audit is off or runs in agent mode (the rollback), like the daily run. The pass also carries the front-step rule (front_step.py): a stuck-elsewhere step held by a front
    agent moves to the item's mover after `[audit] front_step_move_hours`, through `_front_step_mark` (the clock) and `_front_step_move` (the reword)."""
    if not _cfg.audit_enabled() or _cfg.audit_mode() != "script":
        return None
    _ar = _hooks().audit_mod("audit_run")
    return _ar.filing_pass(env=_ar.Env(deliver=_wait_gates._filing_deliver, step_mark=_wait_gates._front_step_mark, step_move=_wait_gates._front_step_move, wake_park=_wait_fixes._wake_park, wait_end=_wait_fixes._wait_end_fix, wait_facts=_wait_fixes._wait_end_facts))


def _loop_tick() -> "dict[str, Any] | None":
    """The minute wait-loop walk (audit/wait_loops.py): every link of every open item is read for a ring of items that wait on each other, and the movers of the items of a ring found are told once (and again only on the audit's
    re-tell cadence). Read only on the board; stands still when the audit is off or runs in agent mode (the rollback), like the filing pass, and while a daily run is in progress."""
    if not _cfg.audit_enabled() or _cfg.audit_mode() != "script":
        return None
    _ar = _hooks().audit_mod("audit_run")
    return _hooks().audit_mod("wait_loops").loop_pass(env=_ar.Env(deliver=_wait_gates._filing_deliver))


def _dates_expected_tick() -> "dict[str, Any] | None":
    """The wake half of the dates pass (audit_run.dates_pass over audit_checks.dates_findings): an item whose own wake has passed with no write since goes to
    its mover once, as the daily audit sends a stale one. Stands still when the audit is off or runs in agent mode (the rollback), like the filing pass."""
    if not _cfg.audit_enabled() or _cfg.audit_mode() != "script":
        return None
    _ar = _hooks().audit_mod("audit_run")
    return _ar.dates_pass(env=_ar.Env(deliver=_wait_gates._filing_deliver), entered=_laddersvc.ladder_enter_quiet if _laddersvc.ladder_on() else None)


def _dates_tick() -> "list[str]":
    """The ten-minute dates pass: the For you list's due-date look (_foryou_tick), whose own gate it opens, since the set's pace is the gate here; then the expected-time look
    (_dates_expected_tick). One that raises never stops the other; the first error is raised after both have run, so the runner records it."""
    made: list[str] = []
    failed: Exception | None = None
    try:
        _fyev._FORYOU_LAST[0] = 0.0
        made = _fyev._foryou_tick()
    except Exception as e:  # noqa: BLE001  — the expected-time look still runs; the runner records this error after it
        failed = e
    try:
        _dates_expected_tick()
    except Exception as e:  # noqa: BLE001
        failed = failed or e
    if failed is not None:
        raise failed
    return made


def _archive_tick() -> "list[tuple[str, str]]":
    """The ten-minute archive sweep (project_archive.sweep): a project whose last agent was retired while it still had open items waits on a list; this archives the
    ones whose items are gone since (completed, or handed to another project). Nothing is read when the list is empty."""
    if not _archive.waiting():
        return []
    today = dt.datetime.now(_cfg.tz()).strftime("%Y-%m-%d")
    return _archive.sweep(_page_io(), today, _prj.with_made(_registry("projects")), _prj._pending_all())


def _silence_env() -> Any:
    """The audit passes' environment, built in one place for the hourly line, the idle hand-over, the balancer and the queue reading: sends through the filing deliver, and `front` is the server's own answer to who is a front agent (`front_keeper` of `stackshot/service/telling.py`), which is stricter than the
    role map (a project's keeper is not front for its own project; a transcript id resolves). Every pass judges a hand-off by the very answer the others do."""
    _ar = _hooks().audit_mod("audit_run")
    return _ar.Env(deliver=_wait_gates._filing_deliver, front=lambda who, project: _telling.front_keeper(who, project)[0], front_strict=lambda who, project: _telling.front_keeper(who, project, True)[0],
                    front_or_unread=lambda who, project: _telling.front_keeper(who, project, unread_front=True)[0])


_QUEUE_CACHE: "dict[str, Any]" = {"at": 0.0, "map": {}}
_QUEUE_TTL = 30.0


def _queue_map(now: "float | None" = None, items: "dict[str, dict[str, Any]] | None" = None) -> "dict[str, str]":
    """{item: the item it is queued behind} for a mover busy on another item (silence.queued, model/queued.py), {} while `[model] queued_behind` is off or when the store cannot be read. Without `items` the
    answer is kept for `_QUEUE_TTL` seconds, so a page or a pass that asks about many items reads the store once. Derived, never stored."""
    if not _queued.enabled():
        return {}
    _silence = _hooks().audit_mod("silence")
    now = time.time() if now is None else now
    if items is None and 0 <= now - _QUEUE_CACHE["at"] < _QUEUE_TTL:
        return _QUEUE_CACHE["map"]
    try:
        out = _silence.queued(items if items is not None else _hooks().next_report_all(None), now, _silence_env())
    except Exception as e:  # noqa: BLE001  — an extra reading: a failure leaves every item as it was
        print(f"queued: not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return {}
    if items is None:
        _QUEUE_CACHE.update(at=now, map=out)
    return out


def _anchor_daily_tell(text: str) -> None:
    """The daily anchor pass's one line to the audit's builder (`[audit] builder`, the session the runner's watchdog tells too), through the inbox flag's sender. Nobody is named here: with no builder set, a stderr line."""
    to = _cfg.audit_builder()
    if not to:
        print("audit: the daily anchor pass removed anchors and no builder is set to be told", file=sys.stderr, flush=True)
        return
    _fleetev.inbox_flag_send(to, text)


def _anchor_daily_tick(now: float | None = None) -> "dict[str, Any] | None":
    """The anchors' daily pass (anchors/groundskeeper.py: the sweep over the whole store with a daily cap, a report of what looks wrong, the files kept within bounds), at most once a calendar day of the instance's timezone; the builder is told only when it removed
    something, and the board is published then. → the pass's result, None when it did nothing."""
    out = _gk.run(now, tell=_anchor_daily_tell)
    if out and out.get("removed"):
        _hooks().publish()
    return out


def _silence_tick() -> "dict[str, Any] | None":
    """The ten-minute audit tick (the name is the runner's key and stays): the hourly audit line (`_hourly_tick`), then the hand-over of the items it found idle (`_hand_idle_tick`), then the hand-on of an idle front agent's item with an open step of its own to a free background agent (`_front_handon_tick`; `[audit] hand_idle` and it rides `[audit] hourly_line`), then, for the items that went to none, the turn started for the idle front agent (`_front_pickup_tick`, its fallback, which rides `[audit] hourly_line`), then the one message about an item whose lines have only said "busy" for hours (`_busy_tell_tick`), then the anchors' daily pass (`_anchor_daily_tick`, once a day). Each is switched by
    its own `[audit]` key and stands still when off (the daily pass has no key of its own: it follows the audit's own switch and mode). Stands still when the audit is off or runs in agent mode. One that raises never stops the other; the first error is printed."""
    if not _cfg.audit_enabled() or _cfg.audit_mode() != "script":
        return None
    try:
        _hourly_tick()
    except Exception as e:  # noqa: BLE001  — the idle hand-over below still runs
        print(f"audit: hourly line not run: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    try:
        _hand_idle_tick()
    except Exception as e:  # noqa: BLE001  — handing an idle item on is its own pass: the line above has run
        print(f"audit: idle items not handed on: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    acted: set[str] = set()      # the items the front hand-on acted on at this tick (handed on or tried): the pick-up, its fallback, leaves them alone
    try:
        _front_handon_tick(acted=acted)
    except Exception as e:  # noqa: BLE001  — the pick-up below is its own pass
        print(f"audit: idle front agents' items not handed on: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    try:
        _front_pickup_tick(skip=acted)
    except Exception as e:  # noqa: BLE001  — the busy-stretch tell below is its own pass
        print(f"audit: idle front agents not picked up: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    try:
        _busy_tell_tick()
    except Exception as e:  # noqa: BLE001  — the lines above have run
        print(f"audit: long busy stretches not told: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    try:
        _anchor_daily_tick()
    except Exception as e:  # noqa: BLE001  — the lines above have run
        print(f"audit: the daily anchor pass not run: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return None


def _agent_state(who: str, now: float | None = None, snap: Any = None) -> Any:
    """The state of the agent `who` as the fleet's session manager last pushed it (audit/agent_state.py `state_of`: busy, idle or unknown with the reason), the one read of a mover's busy or idle the audit makes. The name is tried
    as written and then as the sessions index labels it (`_sr._session_label`: a session id or an old name; a lookup in the index only). `snap` is a snapshot already read (None reads the file). It reads no pane and no transcript of this box."""
    _as = _hooks().audit_mod("agent_state")
    try:
        label = _sr._session_label(str(who or ""))
    except Exception:  # noqa: BLE001  — no label is no alias: the name as written is tried alone
        label = ""
    return _as.state_of(who, time.time() if now is None else now, _as.snapshot() if snap is None else snap, (label,) if label else ())


def _state_word(who: str, now: float, snap: Any = None) -> str:
    """"busy" or "idle" when the agent-state snapshot (fresh, naming the agent, read) says so, "" for everything else (no fresh snapshot, the agent not in it, its state not read or unknown): the word a builder's freedom is judged by
    (audit/hand_idle.py `pick_free`: free only when it says idle; `pick_least`: an idle one wins a tie). It is the snapshot's, never a pane registry's, which this server does not hold for an agent on another box."""
    st = _agent_state(who, now, snap)
    return st.state if st.state in ("busy", "idle") else ""


def _mover_subagents(who: str, now: float | None = None, snap: Any = None) -> "list[dict[str, Any]]":
    """The running subagents of the agent `who`, the ones the hourly audit ties to an item (audit/subagent_tie.py), from the last agent-state snapshot (audit/agent_state.py, `POST /client/agent-state`): [] for an agent
    the snapshot says is idle, the subagents it lists for one it says is busy. An agent that is busy with no pane in a turn and no subagent listed, or whose state the snapshot cannot give (no fresh snapshot, the agent
    missing from it, its state not read or unknown) raises `subagent_tie.Unreadable` with the reason: the audit reads that as unknown, never as idle. `snap` is a snapshot read already (a pass reads the file once)."""
    _tie = _hooks().audit_mod("subagent_tie")
    _as = _hooks().audit_mod("agent_state")
    st = _agent_state(who, now, snap)
    if st.state == _as.UNKNOWN:
        raise _tie.Unreadable(st.why)
    subs = _as.subagents_of(st)
    if st.state == _as.BUSY and not subs and st.pane != _as.TURN:
        raise _tie.Unreadable("the agent is busy but no pane in a turn and no subagent says why")
    return subs


def _move_hold(items: "dict[str, dict[str, Any]]", now: float, snap: Any, dead: "Callable[[str], str]") -> "Callable[[str, str], str]":
    """For the two passes that take an item from a mover that did not hand it back, the idle hand-over and the balancer: `hold(gid, mover)` → why a running subagent keeps the item there, "" when none does
    (audit/hand_idle.py `subagent_hold`). The subagents are those of `snap`, the pass's one read of the last agent-state push (`_mover_subagents`). A mover with no pane (`dead`) whose subagents cannot be read runs none.
    With the anchors unread, a subagent is tied by an item's own id alone, so one that names only a pull request is tied to nothing and holds the item."""
    _hi = _hooks().audit_mod("hand_idle")
    _tie = _hooks().audit_mod("subagent_tie")
    try:
        prs = _rlive.released_anchors()
    except Exception as e:  # noqa: BLE001
        prs = {}
        print(f"audit: anchors not read for the subagents of a mover: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)

    def subagents(who: str) -> "list[dict[str, Any]]":
        try:
            return _mover_subagents(who, now, snap)
        except _tie.Unreadable:
            if dead(who):
                return []
            raise
    return lambda gid, mover: _hi.subagent_hold(items, gid, mover, _handoff.ho_same, subagents, prs)


def _hourly_tick(now: float | None = None, items: "dict[str, dict[str, Any]] | None" = None, env: Any = None, pane: "Callable[[str], str] | None" = None,
                 subagents: "Callable[[str], list[dict[str, Any]]] | None" = None, anchored: "dict[str, Any] | None" = None) -> list[str]:
    """The hourly audit line (audit/hourly.py, `[audit] hourly_line`, on by default), run from the ten-minute audit tick: an open item on an agent with no activity for 45 minutes (`hourly.EVERY`, so the line lands inside the hour), and no audit line in the last
    45 minutes, gets ONE History line, `Audit hh:mm: verified …` or `Audit hh:mm: idle, nothing verified`, one every 45 minutes (`hourly.FAST_GAP`) for the first 24 hours of silence and then one every 6 hours (an entry of `metadata.hourly_audit.log`, kept apart from the stall ladder's
    `metadata.stall.log`; kind `audit`, `audit_idle` or `audit_unknown`: a line for an item the audit could not tell about, because a running subagent of the mover is tied to no item or the mover's subagents could not be read).
    What is verified is recorded data: the mover's pane in a turn and the subagents it has running, as the fleet's session manager last pushed them (audit/agent_state.py, `POST /client/agent-state`; this server reads no pane registry and no transcript of its own: a mover the snapshot cannot give, because it is stale, missing or unread, is unknown), a running subagent of the mover whose description or brief names THIS item or a pull request anchored to it (`_mover_subagents`, audit/subagent_tie.py: a step status in progress is only the mover's claim and is not read), and a tied pull
    request's CI result, review, comment, merge or commit in `metadata.last_activity`; nothing is read from GitHub. A line that rests on live states alone (a busy pane, a subagent) says so. A line that verified something is stamped as the item's last-activity record (kind `audit`, `hourly.stamp_signal`: it is the hourly update, so the On agent row shows it;
    newest wins), one that verified nothing is not, and neither is one that rests on a recorded event alone (the event is in the record already). The save is
    the server's own bookkeeping (no writer): it does not move the activity clock, sends nobody anything and so spares no front agent. Each item is read again under the lock, so two
    passes within 45 minutes write one line. `now`, `items`, `env`, `pane` are for tests and the tick. → the ids written."""
    _hourly = _hooks().audit_mod("hourly")
    _hlog = _hooks().audit_mod("hourly_log")
    if not _hourly.enabled() or _ro.is_read_only():
        return []
    now = time.time() if now is None else now
    items = items if items is not None else _hooks().next_report_all(None)
    env = env if env is not None else _silence_env()
    snap: dict[str, Any] = {}
    if pane is None or subagents is None:
        snap = _hooks().audit_mod("agent_state").snapshot() or {}      # the fleet's last agent-state push, read once for the pass: no snapshot is {}, which reads every agent unknown
    if pane is None:
        _as = _hooks().audit_mod("agent_state")
        pane = lambda who: _as.pane_of(_agent_state(who, now, snap))      # noqa: E731  — an agent the snapshot cannot give shows nothing: unknown, so not verified
    if subagents is None:
        seen: dict[str, Any] = {}      # a mover's subagents are read once a pass, not once an item: a read that failed is kept too (as the exception), so the lookup is not repeated for every item and again under the item lock
        def subagents(who: str) -> "list[dict[str, Any]]":
            if who not in seen:
                try:
                    seen[who] = _mover_subagents(who, now, snap)
                except Exception as e:  # noqa: BLE001
                    seen[who] = e
            if isinstance(seen[who], Exception):
                raise seen[who]
            return seen[who]
    if anchored is None:
        try:
            anchored = _rlive.released_anchors()      # {item id: the pull requests anchored to it}: a subagent whose brief names one of them is tied to the item
        except Exception as e:  # noqa: BLE001  — without the anchors a subagent is tied by the item's own id alone
            anchored = {}
            print(f"audit: anchors not read for the hourly line: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    written: list[str] = []
    for gid, _line in _hourly.pass_(items, now, env, pane, _handoff.ho_same, subagents, anchored):
        try:
            with _writes.ITEM_LOCK:
                item = _svcstore._load(gid)
                line = _hourly.due({**items, gid: item}, gid, now, env, pane, _handoff.ho_same, subagents, anchored)      # read again under the lock: the item may have been written, held or closed since
                if line is None:
                    continue
                _hlog.note(item.setdefault("metadata", {}), now, line["text"], line["kind"], pane_only=_hourly.pane_only(line))
                _hourly.stamp(item, line, now)      # a line that verified something is the hourly update: it is the item's last activity too, newest wins and never backwards (an idle line stamps nothing)
                _writes.save(gid, item, note="audit: hourly line")
            written.append(gid)
            print(f"audit: {gid} hourly line: {line['text']}", file=sys.stderr, flush=True)
        except Exception as e:  # noqa: BLE001  — one item never stops the others
            print(f"audit: {gid} hourly line not written: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    if written:
        _hooks().publish()
    return written


def _busy_tell_tick(now: float | None = None, items: "dict[str, dict[str, Any]] | None" = None, env: Any = None) -> list[str]:
    """A long busy stretch tells the right agent once (audit/busy_tell.py, `[audit] busy_tell`, on by default; `[audit] busy_tell_hours`, 4), run from the ten-minute audit tick after the idle hand-over. An open item on an agent whose hourly audit lines since its last
    real activity have verified only that the mover's pane is in a turn, for that long, gets ONE message to its project's -main agent (the mover has looked busy for about that long with no other sign of progress on the item; please look). An item a FRONT agent
    holds that has had no write but the hourly lines for that long tells that front agent ITSELF, never its -main agent. The message is the same as the idle hand-over's to -main: `[for <owner>]` on its first line (a message to a front agent), through `tell_woken`
    (tag `stall`, the kind that asks the agent to act), one message per agent per pass. The owner is never told, and no step is made for him. `metadata.busy_tell` is written in the save, before anything is sent (at most once: a crash between the save and the send loses
    the message), one History line says who was told; a stretch is told of once, and a new one (real activity, or a line that verified something else) can be told again. A project with no -main agent logs it (once an hour per item) and tells nobody, and is looked at again at the next tick.
    Stands still while the hourly line is off, in a read-only copy and while the board is paused. `now`, `items`, `env` are for tests and the tick. → the ids told."""
    _bt = _hooks().audit_mod("busy_tell")
    _hourly = _hooks().audit_mod("hourly")
    _silence = _hooks().audit_mod("silence")
    if not _bt.enabled() or not _hourly.enabled() or _ro.is_read_only() or _handoff.handoff_paused():
        return []
    now = time.time() if now is None else now
    items = items if items is not None else _hooks().next_report_all(None)
    env = env if env is not None else _silence_env()
    front = getattr(env, "is_front_or_unread", None) or getattr(env, "is_front", None)      # as the hourly line: a registry that cannot be read says front, so the agent holding the item is told, never a guess at its -main agent
    hrs = _bt.hours()
    rows = _bt.due_all(items, now, front, _silence.queued(items, now, env), hrs)
    if not rows:
        return []
    done: list[str] = []
    told: dict[str, list[tuple[str, str, str]]] = {}      # recipient -> (item, kind, line) of its message
    mains: dict[str, str] = {}
    for gid, row in rows:
        try:
            mover, kind = row["mover"], row["kind"]
            if kind == _bt.KIND_FRONT:
                to = mover
            else:
                if row["project"] not in mains:
                    mains[row["project"]] = _agents._main_agent(row["project"])
                to = mains[row["project"]]
                if to and _handoff.ho_same(to, mover):
                    kind = _bt.KIND_FRONT      # the mover is the project's -main agent itself: the front wording, to the same session
            if not to or _model.is_owner(to):
                _balance_log_once(gid, "busy-tell-no-main", now, f"audit: {gid} busy stretch not told: no -main agent to tell")
                continue
            with _writes.ITEM_LOCK:
                item = _svcstore._load(gid)
                cur = _bt.due({**items, gid: item}, gid, now, front, None, hrs)      # read again under the lock: the item may have been written, held, closed or told of since
                if cur is None or not _handoff.ho_same(cur["mover"], mover):
                    continue
                meta = item.setdefault("metadata", {})
                span = _bt.span(cur["shown"], now, hrs)      # the real length of the stretch (whole hours, never under the threshold), not the threshold: a front agent's item counts from its last real activity, which can be days back; a background mover's stretch is measured only as far back as its audit lines show (`shown`)
                _bt.mark(meta, now, to, kind, cur["since"])
                _stall.note(meta, now, f"{_sr._session_label(mover)}'s item has had {'no write but the hourly audit lines' if kind == _bt.KIND_FRONT else 'only a busy pane for its hourly audit lines'} for about {span}: {_sr._session_label(to)} was told")
                _writes.save(gid, item, note="audit: busy stretch told")
            lead = f"{_gh.shown(gid)} \"{items[gid].get('subject') or ''}\" ({row['project']})"
            line = (f"{lead}: no write on it but the hourly audit lines for about {span}. If you are at work on it, write a line on it; if you are not, say what blocks it or hand it on" if kind == _bt.KIND_FRONT else
                    f"{lead}: {_sr._session_label(mover)} has looked busy for about {span} (every audit line since said only that its pane is in a turn) with no step change, pull request event or other sign of progress on this item. Please look at what it is doing")
            told.setdefault(to, []).append((gid, kind, line))
            done.append(gid)
            print(f"audit: {gid} busy stretch told to {to} ({kind})", file=sys.stderr, flush=True)
        except Exception as e:  # noqa: BLE001  — one item never stops the others
            print(f"audit: {gid} busy stretch not told: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    for to, rows_ in told.items():
        try:
            gids, lines = [g for g, _k, _l in rows_], [l for _g, _k, l in rows_]
            body = lines[0] + "." if len(lines) == 1 else f"{len(lines)} items had only the audit's lines for hours:\n" + "\n".join("- " + x for x in lines)
            _telling.tell_woken(",".join(gids), _hooks().session_id(to) or to, f"[stackshot] {body}\nNo reply is owed to the audit; nothing here is for {OWNER}. → "
                                + (_telling.notice_link(gids[0]) if len(gids) == 1 else _inst.BOARD_URL), tag="stall")
        except Exception as e:  # noqa: BLE001
            print(f"audit: {to} not told of the busy stretches: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return done


def _front_of_project(who: str, project: str) -> bool:
    """Is `who` a front agent of `project`: a front agent by the server's own answer (`telling.front_keeper`, the one the hourly line, the idle hand-over and the busy-stretch tell use, which is no for the project's own keeper and for a
    role map that cannot be read) and, by the role map, one listed (role front, not retired) on that very project? Raises when the roles cannot be read: the pick-up reads that as no."""
    if not _telling.front_keeper(who, project)[0]:
        return False
    roles = _anc.session_roles()
    row = roles.get(_sr._role_name(roles, who) or "") or {}
    return row.get("role") == "front" and not row.get("retired") and bool(project) and str(row.get("project") or "").strip("/") == str(project).strip("/")


class _PresenceUnreadable(Exception):
    """The owner's presence cannot be told (the fleet's index is partial): the pass that asked starts nothing."""


def _owner_present_reader(now: float) -> "Callable[[str], bool]":
    """`present(who)` for the front pick-up and the front hand-on: is the owner in that conversation now? The fleet's index and the stamp folder (the prompt hook's files, or the copy of them from the agents' box) are read once for the pass and
    raise when they cannot be read, and so does an index that is partial (`idx.unreadable`: a machine's sessions.json could not be read, so a pane on it has no row to find its stamp by): the pass then starts nothing, so nothing is started on a guess. The pane's stamp is found by its session id in the fleet's index (a pane on another box than the server's counts), and
    `front_turn.present` (the notices' own test, which needs the pane on this box) is asked too: either one saying present is present."""
    idx = _sr._sessions_index()
    if getattr(idx, "unreadable", None):      # a machine's sessions.json could not be read: a pane on it has no row, so "no stamp found" would read as absent while the owner may be typing there
        raise _PresenceUnreadable(f"the fleet's sessions index is partial (machine {', '.join(str(x) for x in idx.unreadable)} not read)")
    stamps = {f.name for f in _ab.prompts_dir().iterdir() if f.is_file()}
    limit = _telling.presence_minutes() * 60.0

    def present(who: str) -> bool:
        ids = {str(k) for k, r in idx.items() if isinstance(r, dict) and _anc.same_session(r.get("name"), who)}
        own = _hooks().session_id(who)
        if own:
            ids.add(str(own))
        for sid in sorted(ids & stamps):
            try:
                ts = float((_ab.prompts_dir() / sid).read_text(encoding="utf-8").strip().split()[0])
            except (OSError, ValueError, IndexError):
                continue      # a stamp that cannot be read says nothing here; the notices' own test below still asks
            if now - ts <= limit:      # a stamp dated ahead of the clock (clocks a few seconds apart) is the owner just now: present, never absent
                return True
        return _front_turn.present(who)
    return present


_PANE_IDLE = "idle"      # the snapshot's pane word of a pane that is not in a turn and takes a message at once; `shell` and `sleeping` are idle states too, but a notice sent to one of them is queued, not read


def _pane_idle(who: str, now: float, snap: Any) -> bool:
    """Does the last agent-state snapshot say, fresh and read, that the agent `who` is idle AND its pane word is `idle`? Busy, unknown, stale, missing, and a pane that reads `shell` or `sleeping` are all no: a line sent to such a pane is
    queued or held, so it would not be the started turn the passes count it as."""
    _as = _hooks().audit_mod("agent_state")
    st = _agent_state(who, now, snap)
    return st.state == _as.IDLE and st.pane == _PANE_IDLE


def _other_passes_skip(items: "dict[str, dict[str, Any]]", now: float, env: Any) -> "set[str]":
    """The items the idle hand-over and the busy-stretch tell act on at this tick: another pass of the same tick leaves them alone (one action per item per tick). Raises when either cannot be read: the caller then acts on nothing."""
    skip: set[str] = set()
    _hi, _bt, _silence = _hooks().audit_mod("hand_idle"), _hooks().audit_mod("busy_tell"), _hooks().audit_mod("silence")
    if _hi.enabled() and not _handoff.handoff_paused():
        skip |= {g for g, _r in _hi.due_all(items, now, getattr(env, "is_front", None))}
    if _bt.enabled():
        isf = getattr(env, "is_front_or_unread", None) or getattr(env, "is_front", None)
        skip |= {g for g, _r in _bt.due_all(items, now, isf, _silence.queued(items, now, env), _bt.hours())}
    return skip


def _front_pickup_tick(now: "float | None" = None, items: "dict[str, dict[str, Any]] | None" = None, env: Any = None, snap: Any = None,
                       front: "Callable[[str, str], bool] | None" = None, present: "Callable[[str], bool] | None" = None, skip: "Iterable[str]" = ()) -> list[str]:
    """An idle front agent with an open step of its own gets its turn started (audit/front_pickup.py; no key of its own, it rides `[audit] hourly_line`), run from the ten-minute audit tick after the idle hand-over and the front hand-on and before the
    busy-stretch tell. It is the FALLBACK of the hand-on (`_front_handon_tick`): the hand-on gives such an item to a free background agent, and this starts the front agent's own turn for an item that went to none (no background agent free, or
    none in the project); an item the hand-on acted on at this tick is in `skip`. An open item a front agent of its project moves, whose first open step opens with that agent, that the board shows on an agent (no hold, until, open after, anchor wait
    or decision), that has been quiet for 45 minutes (`front_pickup.QUIET`), whose agent the last agent-state snapshot says is idle (fresh, read, state and pane word both `idle`) and whose pane the owner is not in, gets ONE line to that agent naming the item
    and its open steps, through `tell_woken` (tag `stall`, the kind that asks the agent to act and is a turn for a front agent, as the busy-stretch tell sends it): never more than once an hour per item (`<paths.state>/front-pickup.json`, written
    before the line is sent; a delivery that fails turns the mark into a half-hour backoff, so a push that keeps failing is tried every half hour, not every ten minutes), one turn per agent and at most `front_pickup.MAX_TURNS_PER_TICK` turns per
    tick. The idle hand-over and the busy-stretch tell win over it for an item they act on this tick. The item is read again before the send. Any read that fails (the roles, the snapshot, the fleet's index (a partial one included), the stamp
    folder, the record) logs one line and starts nothing; a record that cannot be read for now (an OSError) is left where it is, only one that is no record is set aside. Stands still while the hourly line is off, in a read-only copy and while
    the board is paused. The tick waits for every delivery's outcome before it returns. `now`, `items`, `env`, `snap`, `front`, `present`, `skip` are for tests and the tick. → the ids a turn was started for AND delivered."""
    _fp = _hooks().audit_mod("front_pickup")
    _hourly = _hooks().audit_mod("hourly")
    _as = _hooks().audit_mod("agent_state")
    if not _hourly.enabled() or _ro.is_read_only() or _handoff.handoff_paused():
        return []
    now = time.time() if now is None else now
    try:
        items = items if items is not None else _hooks().next_report_all(None)
        env = env if env is not None else _silence_env()
        snap = snap if snap is not None else (_as.snapshot() or {})
        front = front or _front_of_project
        present = present or _owner_present_reader(now)
        marks = _fp.read_marks()
    except _fp.Unreadable as e:
        _fp.set_aside()      # a record that is torn is set aside so the next tick starts a clean one (an item may be started for once more)
        print(f"audit: front pick-up stands still, its record is unreadable ({e}); it was set aside", file=sys.stderr, flush=True)
        return []
    except Exception as e:  # noqa: BLE001  — nothing is read, nothing is started
        print(f"audit: front pick-up stands still, a read failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return []
    idle = lambda who: _pane_idle(who, now, snap)      # noqa: E731  — busy, unknown, stale, missing and a pane that is no plain idle one are all "not idle"
    try:
        skip = set(skip) | _other_passes_skip(items, now, env)      # the items another pass of this tick acts on: one action per item per tick
    except Exception as e:  # noqa: BLE001  — what the other passes act on is not known: nothing is started
        print(f"audit: front pick-up stands still, the other passes could not be read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return []
    errors: list[str] = []
    rows = _fp.pick(_fp.due_all(items, now, front, idle, present, _handoff.ho_same, marks, skip, errors), _handoff.ho_same)
    if errors:      # one line however many items could not be read
        print(f"audit: front pick-up: {errors[0]}" + (f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""), file=sys.stderr, flush=True)
    sent_: list[tuple[str, "threading.Thread | None", "dict[str, Any]", str]] = []      # (item, the sending thread, its result, the agent) of every line that went out
    for gid, row in rows:
        try:
            item = _svcstore._load(gid)
            cur = _fp.due({**items, gid: {**item, "gid": gid}}, gid, now, front, idle, present, _handoff.ho_same, marks, skip)      # read again: the item may have been written, held, closed or handed on since
            if cur is None or not _handoff.ho_same(cur["mover"], row["mover"]):
                continue
            lead = f"{_gh.shown(gid)} \"{items[gid].get('subject') or ''}\" ({row['project']})"
            text = f"[stackshot] {_fp.words(cur, lead)}.\nNo reply is owed to the audit; nothing here is for {OWNER}. → {_telling.notice_link(gid)}"
            _fp.mark(gid, now, items)      # before the send, so it is at most once an hour; a delivery that fails turns it into a half-hour backoff below
            res: dict[str, Any] = {}
            try:
                th = _telling.tell_woken(gid, _hooks().session_id(row["mover"]) or row["mover"], text, tag="stall", result=res)
            except Exception:
                _fp.unmark(gid, now)
                raise
            sent_.append((gid, th, res, row["mover"]))
        except Exception as e:  # noqa: BLE001  — one item never stops the others
            print(f"audit: {gid} front pick-up not made: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    started: list[str] = []
    for gid, th, res, who in sent_:      # the lines went out together; each is counted once its delivery is known
        if th is not None:
            th.join()
        if th is None or not res.get("ok"):
            _fp.unmark(gid, now)      # the mark becomes the half-hour backoff: a push that keeps failing is not tried every ten minutes
            print(f"audit: {gid} front pick-up not delivered to {who}: {res.get('why') or 'no result'}", file=sys.stderr, flush=True)
            continue
        started.append(gid)
        print(f"audit: {gid} idle front agent {who} told of its own step", file=sys.stderr, flush=True)
    return started


def _front_handon_tick(now: "float | None" = None, items: "dict[str, dict[str, Any]] | None" = None, env: Any = None, snap: Any = None,
                       front: "Callable[[str, str], bool] | None" = None, present: "Callable[[str], bool] | None" = None, dead: "Callable[[str], str] | None" = None,
                       acted: "set[str] | None" = None) -> list[str]:
    """An idle front agent's item with an open step of its own goes to a free background agent of its project (audit/front_handon.py; `[audit] hand_idle` must be on, and it rides `[audit] hourly_line` like the pick-up), run from the ten-minute
    audit tick right after the idle hand-over and before the pick-up (`_front_pickup_tick`, its fallback). The item must pass the pick-up's own test (`front_pickup.eligible`: the board shows it on an agent, a front agent of its project moves it, its leading
    open step is that agent's own, the snapshot says the agent is idle, nobody is in that conversation, 45 minutes of quiet) and not have been handed on by the idle pass in the last 24 hours (`metadata.hand_idle`, the hand-over's own guard, written
    by this move too). The new mover is the first free background agent of the item's own project (`hand_idle.pick_free` over `_handoff.handoff_background`, the builder first, `[audit] no_handoff` left out): not the mover of any open item on an agent, and the snapshot says it is
    idle (fresh, read, state `idle`, as the idle hand-over reads it; busy, unknown, stale, missing are not free), and its pane may exist (`handoff_pane`). The move is the idle hand-over's own write (`_handoff.handoff_exec` -> `handoff_write_move`, `via` orphan): the background
    agent heads `needs`, the hand-off record is made from the server and it is told by the hand-off notice; the front agent stays named in `needs` (`Step.keep_frm`) and the item's contact is not touched. One History line says why and names the mover it left.
    Nobody else is told, and never the owner. With none free (or no background agent in the project) nothing is written and the pick-up has the item. `acted` (an out-set the tick gives) receives every item this pass looked at as handed on or tried to
    be, so the pick-up leaves it alone in the same tick: never both on one item. At most `hand_idle.MAX_PER_TICK` items per pass; an item over that cap that a free background agent could take is in `acted` too (left for the next tick, not the pick-up's). A read that fails (roles, snapshot, fleet index (a partial one included), stamp folder) logs one line and hands nothing on.
    `now`, `items`, `env`, `snap`, `front`, `present`, `dead` are for tests and the tick. → the ids handed on."""
    _fh = _hooks().audit_mod("front_handon")
    _hi = _hooks().audit_mod("hand_idle")
    _hourly = _hooks().audit_mod("hourly")
    _as = _hooks().audit_mod("agent_state")
    if not (_hourly.enabled() and _hi.enabled()) or _ro.is_read_only() or _handoff.handoff_paused():
        return []
    now = time.time() if now is None else now
    acted = acted if acted is not None else set()
    try:
        items = items if items is not None else _hooks().next_report_all(None)
        env = env if env is not None else _silence_env()
        snap = snap if snap is not None else (_as.snapshot() or {})
        front = front or _front_of_project
        present = present or _owner_present_reader(now)
        skip = _other_passes_skip(items, now, env)
    except Exception as e:  # noqa: BLE001  — nothing is read, nothing is handed on
        print(f"audit: front hand-on stands still, a read failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return []
    idle = lambda who: _pane_idle(who, now, snap)      # noqa: E731  — busy, unknown, stale, missing and a pane that is no plain idle one are all "not idle"
    errors: list[str] = []
    rows = _fh.due_all(items, now, front, idle, present, _handoff.ho_same, skip, errors)
    if errors:      # one line however many items could not be read
        print(f"audit: front hand-on: {errors[0]}" + (f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""), file=sys.stderr, flush=True)
    if not rows:
        return []
    try:
        if dead is None:
            idx = _sr._sessions_index()
            dead = lambda who: _handoff.handoff_pane(who, idx)      # noqa: E731
    except Exception as e:  # noqa: BLE001  — whether a name may have a pane is not known: nothing is handed on
        print(f"audit: front hand-on stands still, the fleet's index was not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return []
    status = lambda who: _state_word(who, now, snap)      # noqa: E731  — the idle hand-over's own free test: the snapshot's word, "" for anything it cannot say, which `pick_free` leaves out
    busy = _hi.busy_movers(items, now)
    handed: list[str] = []
    builders: dict[str, list[str]] = {}      # per project, read once a pass
    for gid, row in rows:
        try:
            if row["project"] not in builders:
                builders[row["project"]] = _hand_idle_builders(row["project"])
            to = _hi.pick_free(builders[row["project"]], busy, status, dead, _handoff.ho_same, row["mover"])
            if not to:
                continue      # none free: the item is the pick-up's
            acted.add(gid)      # from here the item is this pass's, whatever happens: the pick-up leaves it alone at this tick
            if len(handed) >= _hi.MAX_PER_TICK:
                busy.append(to)      # over the cap: left for the next tick, which hands it on; the agent it would take is spoken for, so a later item with none left free still falls to the pick-up
                continue

            def still(item: dict[str, Any], st: "_ho.Step") -> bool:      # under the item lock, on the fresh read: still due, and still with the front agent it was found with; the stamp goes on the metadata the move saves
                cur = _fh.due({**items, st.gid: item}, st.gid, now, front, idle, present, _handoff.ho_same, skip)
                if cur is None or not _handoff.ho_same(cur["mover"], st.frm):
                    return False
                _hi.mark_handed(item.setdefault("metadata", {}), now, st.frm, st.to)
                return True
            st = _ho.Step("move", gid, _fh.why(_sr._session_label(row["mover"])), row["mover"], to, via="orphan", keep_frm=True)
            if not _handoff.handoff_exec([st], now, verify=False, recheck=still):
                continue
            handed.append(gid)
            busy.append(to)
            print(f"audit: {gid} idle front agent {row['mover']}'s own step, handed to {to}", file=sys.stderr, flush=True)
        except Exception as e:  # noqa: BLE001  — one item never stops the others
            acted.add(gid)
            print(f"audit: {gid} front hand-on not made: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return handed


def _hand_idle_builders(project: str) -> list[str]:
    """The sessions an idle item of `project` may be handed to, best first: the project's own background agents less those `[audit] no_handoff` names (`_handoff.handoff_background`) and no other project's. A project's work is
    built, reviewed and released by its own builder, so a builder of an unrelated project is never a candidate, however idle. A project with no free background agent of its own keeps the item, and `_hand_idle_tick` says so
    to its -main agent."""
    return list(_handoff.handoff_background(project))


def _hand_idle_tick(now: float | None = None, items: "dict[str, dict[str, Any]] | None" = None, env: Any = None, status: "Callable[[str], str] | None" = None,
                    dead: "Callable[[str], str] | None" = None) -> list[str]:
    """Idle items go to a free builder (audit/hand_idle.py, `[audit] hand_idle`, on by default), run from the ten-minute audit tick right after the hourly line: an open item on an agent whose newest audit line is
    `idle, nothing verified` and that nothing has moved since goes to the first free builder (a background agent of its own project, never another project's; one the fleet's last agent-state push says is idle, and
    that moves no open item on an agent: a builder that is busy, missing from the push or not read is not free), by the minute hand-off pass's own write (`_handoff.handoff_exec` → `_handoff.handoff_write_move`, as the audit's orphan hand-over does): the builder heads `needs`, the hand-off record is made
    from the server and the builder is told. One History line says why and names the mover it left. The project's -main agent gets one message that asks nothing. With no builder free nothing moves: a History
    line says so and -main is told once per item per 24 hours. No message goes to the owner and no step is made for him. At most `hand_idle.MAX_PER_TICK` items are handed on per pass and one per item per 24 hours.
    An item a running subagent of its mover may be working on is not moved, a log line only (`_move_hold`).
    `now`, `items`, `env`, `status`, `dead` are for tests and the tick. → the ids handed on."""
    _hi = _hooks().audit_mod("hand_idle")
    if not _hi.enabled() or _ro.is_read_only() or _handoff.handoff_paused():
        return []
    now = time.time() if now is None else now
    items = items if items is not None else _hooks().next_report_all(None)
    env = env if env is not None else _silence_env()
    front = env.is_front if hasattr(env, "is_front") else None
    rows = _hi.due_all(items, now, front)
    if not rows:
        return []
    snap = _hooks().audit_mod("agent_state").snapshot() or {}      # the fleet's last agent-state push, read once for the pass: none is {}, which reads every agent unknown
    if status is None or dead is None:
        idx = _sr._sessions_index()
        status = status or (lambda who: _state_word(who, now, snap))
        dead = dead or (lambda who: _handoff.handoff_pane(who, idx))
    hold = _move_hold(items, now, snap, dead)
    busy = _hi.busy_movers(items, now)
    handed: list[str] = []
    told: dict[str, list[tuple[str, str]]] = {}      # -main agent -> (item, line) of its message
    told_mover: dict[str, list[tuple[str, str]]] = {}      # mover -> (item, line) of its message: an idle item with no builder free tells the session that holds it
    builders: dict[str, list[str]] = {}      # per project, read once a pass (the role map is not read again for every item)
    mains: dict[str, str] = {}
    for gid, row in rows:
        if len(handed) >= _hi.MAX_PER_TICK:
            break
        try:
            if row["project"] not in builders:
                builders[row["project"]] = _hand_idle_builders(row["project"])
                mains[row["project"]] = _agents._main_agent(row["project"])
            to = _hi.pick_free(builders[row["project"]], busy, status, dead, _handoff.ho_same, row["mover"])
            main = mains[row["project"]]
            if main and _model.is_owner(main):
                main = ""      # the owner is told nothing by this pass, whatever the page names as -main
            lead = f"{_gh.shown(gid)} \"{items[gid].get('subject') or ''}\" ({row['project']})"
            if to:
                why = hold(gid, row["mover"])
                if why:
                    _balance_log_once(gid, "idle-subagent", now, f"audit: {gid} idle, left with {row['mover']}: {why}")
                    continue

                def still(item: dict[str, Any], st: "_ho.Step") -> bool:      # under the item lock, on the fresh read: still due, and still with the mover it was found with; the stamp goes on the metadata the move saves
                    cur = _hi.due({**items, st.gid: item}, st.gid, now, front)
                    if cur is None or not _handoff.ho_same(cur["mover"], st.frm):
                        return False
                    _hi.mark_handed(item.setdefault("metadata", {}), now, st.frm, st.to)
                    return True
                st = _ho.Step("move", gid, f"{_hi.WHY} (it was with {_sr._session_label(row['mover'])})", row["mover"], to, via="orphan")
                if not _handoff.handoff_exec([st], now, verify=False, recheck=still):
                    continue
                handed.append(gid)
                busy.append(to)
                if main:
                    told.setdefault(main, []).append((gid, f"{lead}: no activity for an hour and nothing the audit could verify, so it went from {_sr._session_label(row['mover'])} to {_sr._session_label(to)}"))
                print(f"audit: {gid} idle, handed from {row['mover']} to {to}", file=sys.stderr, flush=True)
            elif not row["told_none"] or row["mover_due"]:
                with _writes.ITEM_LOCK:
                    item = _svcstore._load(gid)
                    cur = _hi.due({**items, gid: item}, gid, now, front)
                    if cur is None or not _handoff.ho_same(cur["mover"], row["mover"]):
                        continue
                    first_none, tell_mover = not cur["told_none"], cur["mover_due"] and not _model.is_owner(cur["mover"])      # under the lock, on the fresh read: what is still owed
                    if not first_none and not tell_mover:
                        continue
                    meta = item.setdefault("metadata", {})
                    tell_main = bool(main) and not _handoff.ho_same(main, row["mover"])      # a -main agent that is the mover itself is told once, as the mover
                    if first_none:
                        _hi.mark_none(meta, now)
                    if tell_mover:
                        _hi.mark_mover_told(meta, now)
                    if first_none or cur["mover_first"]:      # one History line for the first tell of a stretch; the hourly repeats write none
                        parts = ([f"a summary goes to {_sr._session_label(main)}" if tell_main else "the project has no -main agent to tell" if not main else ""] if first_none else [])
                        parts += [f"the audit tells {_sr._session_label(row['mover'])} every hour while it stays idle"] if tell_mover else []
                        if any(parts):
                            _stall.note(meta, now, "no activity for an hour and nothing verified, but no builder was free to take it: " + ", and ".join(x for x in parts if x))
                    _writes.save(gid, item, note="audit: idle, no builder free")
                if first_none and tell_main:
                    told.setdefault(main, []).append((gid, f"{lead}: no activity for an hour and nothing the audit could verify, and no builder was free to take it, so it stays with {_sr._session_label(row['mover'])}"))
                if tell_mover:
                    hours = _hi.idle_hours(cur["since"], now)
                    told_mover.setdefault(row["mover"], []).append((gid, f"{lead}: no activity on it for about {hours} hour{'s' if hours != 1 else ''} and nothing the audit could verify, and no builder was free to take it. If you are at work on it, write a line on it; if you are not, say what blocks it or hand it on. The audit tells you again every hour while it stays idle"))
                print(f"audit: {gid} idle, no builder free" + (", mover told" if tell_mover else ""), file=sys.stderr, flush=True)
        except Exception as e:  # noqa: BLE001  — one item never stops the others
            print(f"audit: {gid} idle item not handed on: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    for main, pairs in told.items():
        try:
            gids, lines = [g for g, _l in pairs], [l for _g, l in pairs]
            body = lines[0] + "." if len(lines) == 1 else f"{len(lines)} items had no activity for an hour and nothing the audit could verify:\n" + "\n".join("- " + x for x in lines)
            _telling.tell_news(dict(pairs), ",".join(gids), _hooks().session_id(main) or main, f"[stackshot] {body}\nNothing is asked of you and no reply is owed; nothing here is for {OWNER}. → "
                        + (_telling.notice_link(gids[0]) if len(gids) == 1 else _inst.BOARD_URL), tag="stall_summary")
        except Exception as e:  # noqa: BLE001
            print(f"audit: {main} not told of the idle items: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    for mover, pairs in told_mover.items():
        try:
            gids, lines = [g for g, _l in pairs], [l for _g, l in pairs]
            body = lines[0] + "." if len(lines) == 1 else f"{len(lines)} items of yours have had no activity and no builder was free to take them:\n" + "\n".join("- " + x for x in lines)
            _telling.tell_woken(",".join(gids), _hooks().session_id(mover) or mover, f"[stackshot] {body}\nNo reply is owed to the audit; nothing here is for {OWNER}. → "
                                + (_telling.notice_link(gids[0]) if len(gids) == 1 else _inst.BOARD_URL), tag="stall")
        except Exception as e:  # noqa: BLE001
            print(f"audit: {mover} not told of its idle items: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return handed


_BALANCE_LOGGED: dict[tuple[str, str], float] = {}   # (item, reason) -> when a stay was last logged (the balancer's, and the idle hand-over's for a subagent): a stay that lasts is one stderr line an hour, not one a pass
BALANCE_LOG_EVERY = 3600.0


def _balance_log_once(gid: str, key: str, now: float, line: str) -> None:
    """One stderr line for an item the balancer or the idle hand-over leaves where it is, at most once per `BALANCE_LOG_EVERY` per item and reason (the balancer looks at the item every minute for as long as it waits)."""
    last = _BALANCE_LOGGED.get((gid, key))
    if last is not None and 0 <= now - last < BALANCE_LOG_EVERY:
        return
    if len(_BALANCE_LOGGED) > 2000:
        _BALANCE_LOGGED.clear()
    _BALANCE_LOGGED[(gid, key)] = now
    print(line, file=sys.stderr, flush=True)


def _balance_builders(project: str) -> list[str]:
    """The sessions the balancer may move an item of `project` to, best first: the project's own BUILDERS only (the mandate says build, maintain, merge or engineer: `_handoff.handoff_ranked` classes them 0 and 1, and leaves out those `[audit] no_handoff` names). Never another
    project's builder: a project's code is built, reviewed and released by its own builder, and a builder of an unrelated project has a different mandate. With no other builder here the item stays where it is. A reviewer or any
    other background agent is no candidate."""
    return [n for c, _o, n in _handoff.handoff_ranked(project) if c < 2]


def _balance_builder_names() -> list[str]:
    """Every background agent, of any project, whose mandate says build, maintain, merge or engineer and that is not retired (raises when the registry cannot be read): who counts as a builder whose item may be balanced.
    Only the item's mover is judged by this; where an item may go is `_balance_builders` (its own project's builders)."""
    reg = _anc.registry()
    return [n for n, r in _anc.session_roles(reg).items()
            if r.get("role") == "back" and not r.get("retired") and _router._BUILDER.search(str(((reg.get(r.get("project", "")) or {}).get("agents") or {}).get(n) or ""))]


def _balance_tick(now: float | None = None, items: "dict[str, dict[str, Any]] | None" = None, env: Any = None, status: "Callable[[str], str] | None" = None,
                  dead: "Callable[[str], str] | None" = None, anchored: "Callable[[str, dict[str, Any]], bool] | None" = None) -> list[str]:
    """The balancer (audit/hand_idle.py, `[audit] balance`, on by default), its own minute tick ahead of the hand-off tick, so a move at `balance_minutes` (10) comes before that tick's reminder: an item NOT STARTED (an
    untaken hand-off to a builder) or QUEUED BEHIND its mover's other item (the queue rule over the balancer's own window, whatever `[model] queued_behind` says) that has waited that long goes to the builder of its own project with the fewest open
    items, by the same write as the idle hand-over (`_handoff.handoff_exec` → `_handoff.handoff_write_move`): the builder heads `needs`, the hand-off record is made from the server, the builder is told by the hand-off notice, one History line says
    why. The mover it left is told ONCE, by `tell_woken` (not the message tool, which would name it in `needs` again), to disregard the item. An item its mover started (a taken hand-off, a step status in progress or done or one
    that says a subagent is running, an anchor, a pull request event) is never moved, and neither is one a running subagent of the mover may be working on, whatever its record says: a subagent of the last agent-state push tied
    to it or to none of the mover's open items, or subagents that cannot be read for a mover with a pane (`_move_hold`; a log line only). `metadata.balance` ({at, from, to, count}) keeps the limits and is written in the save of the move, before anything is sent: one move per item per 24 hours, two
    in all (then the existing ladders have it and -main is told once), three per pass. With NO live builder to take it (another builder than its mover is in the role map and none is usable) the item stays, one History line says so and -main is told once per item per 24 hours, and the pass looks again every minute; with no other builder, or a builder that is no improvement, it is a log line only.
    Only an item whose mover is itself a builder is balanced, and only to builders. The notice to the mover it left is at-most-once (a crash between the save and the send loses it) and is not sent to a pane that is gone. An item the idle
    hand-over moved in the last 24 hours is left alone. Stands still while the audit is off (`[audit] enabled`) or runs in agent mode, while the board is paused, with `[model] handoff` off, and in a read-only copy. `now`, `items`, `env`, `status`, `dead`, `anchored` are for tests and the tick. → the ids moved."""
    _hi = _hooks().audit_mod("hand_idle")
    if not _hi.balance_enabled() or not _cfg.audit_enabled() or _cfg.audit_mode() != "script" or _ro.is_read_only() or _handoff.handoff_paused() or not _handoff.handoff_on():
        return []
    now = time.time() if now is None else now
    items = items if items is not None else _hooks().next_report_all(None)
    env = env if env is not None else _silence_env()
    front = getattr(env, "is_front_safe", None) or env.is_front      # a front test that cannot answer counts as front: nothing moves on a guess
    minutes = _hi.balance_minutes()
    cells: dict[str, Any] = {}

    def anchors_of(gid: str, item: dict[str, Any]) -> bool:      # an anchor scoped to the item says a build is in flight; an anchor store that cannot be read counts as one
        try:
            if "anchors" not in cells:
                cells["anchors"] = _anc.load()
            return bool(_item_read._scoped_anchors(str((item.get("metadata") or {}).get("project") or ""), gid, cells["anchors"]))
        except Exception:  # noqa: BLE001
            return True
    anchored = anchored or anchors_of
    try:
        names = _balance_builder_names()
    except Exception as e:  # noqa: BLE001  — with no view of who builds, nothing is judged a builder: nothing moves on a guess
        print(f"balance: builders not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return []
    is_builder = lambda who: any(_handoff.ho_same(who, n) for n in names)      # noqa: E731
    behind = _hi.balance_queue(items, now, minutes * 60.0, front)
    rows = _hi.balance_all(items, now, minutes, front, behind, _handoff.ho_same, anchored, is_builder)
    if not rows:
        return []
    snap = _hooks().audit_mod("agent_state").snapshot() or {}      # the fleet's last agent-state push, read once for the pass: none is {}, which reads every agent unknown
    if status is None or dead is None:
        idx = _sr._sessions_index()
        status = status or (lambda who: _state_word(who, now, snap))
        dead = dead or (lambda who: _handoff.handoff_pane(who, idx))
    hold = _move_hold(items, now, snap, dead)
    load = _hi.load_counts(_hi.busy_movers(items, now), _handoff.ho_same)
    moved: list[str] = []
    gone: list[tuple[str, str, str]] = []      # (the mover it left, the item, who has it now): the former mover's notice
    told: dict[str, list[tuple[str, str]]] = {}      # -main agent -> (item, line) of its message
    builders: dict[str, list[str]] = {}      # per project, read once a pass
    mains: dict[str, str] = {}
    for gid, row in rows:
        if len(moved) >= _hi.BALANCE_MAX_PER_TICK:
            break
        try:
            why = hold(gid, row["mover"])
            if why:      # the mover may be at work on it: no move, no History line, nobody told
                _balance_log_once(gid, "subagent", now, f"balance: {gid} stays with {row['mover']}: {why}")
                continue
            project = row["project"]
            if project not in builders:
                builders[project] = _balance_builders(project)
                mains[project] = _agents._main_agent(project)
            main = mains[project]
            if main and _model.is_owner(main):
                main = ""      # the owner is told nothing by this pass
            lead = f"{_gh.shown(gid)} \"{items[gid].get('subject') or ''}\" ({project})"
            if row["capped"]:
                with _writes.ITEM_LOCK:
                    item = _svcstore._load(gid)
                    cur = _hi.balance_due({**items, gid: {**item, "gid": gid}}, gid, now, minutes, front, behind, _handoff.ho_same, anchored, is_builder)
                    if cur is None or not cur["capped"] or not _handoff.ho_same(cur["mover"], row["mover"]):
                        continue
                    meta = item.setdefault("metadata", {})
                    _hi.mark_balance_capped(meta, now)
                    _stall.note(meta, now, f"already moved {_hi.BALANCE_LIFETIME} times by the balancer, so it stays with {_sr._session_label(row['mover'])} and the ladders have it: " + (f"a summary goes to {_sr._session_label(main)}" if main else "the project has no -main agent to tell"))
                    _writes.save(gid, item, note="balance: at its lifetime cap")
                if main:
                    told.setdefault(main, []).append((gid, f"{lead}: it was moved {_hi.BALANCE_LIFETIME} times to balance the builders and is still not started, so the balancer leaves it with {_sr._session_label(row['mover'])} to the ladders"))
                print(f"balance: {gid} at its lifetime cap", file=sys.stderr, flush=True)
                continue
            to = _hi.pick_least(builders[project], load, status, dead, _handoff.ho_same, row["mover"], row["tried"], front, project)
            if to and not _hi.balance_ok(row["kind"], _hi.load_of(load, to, _handoff.ho_same), _hi.load_of(load, row["mover"], _handoff.ho_same)):
                _balance_log_once(gid, "load", now, f"balance: {gid} stays with {row['mover']}: no builder has few enough open items")      # silent otherwise: a spread that is as good as it can be is no news
            elif to:
                def still(item: dict[str, Any], st: "_ho.Step") -> bool:      # under the item lock, on the fresh read: still due and still with the mover it was found with; the record goes on the metadata the move saves
                    cur = _hi.balance_due({**items, st.gid: item}, st.gid, now, minutes, front, behind, _handoff.ho_same, anchored, is_builder)
                    if cur is None or cur["capped"] or not _handoff.ho_same(cur["mover"], st.frm):
                        return False
                    _hi.mark_balanced(item.setdefault("metadata", {}), now, st.frm, st.to)
                    return True
                st = _ho.Step("move", gid, _hi.balance_why(row["kind"], minutes) + f" (it was with {_sr._session_label(row['mover'])})", row["mover"], to, via="orphan")
                try:
                    ok = bool(_handoff.handoff_exec([st], now, verify=False, recheck=still))
                except Exception as e:  # noqa: BLE001  — a send after the save failed: the move itself was made when the item carries this pass's record
                    print(f"balance: {gid} sending after the move failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
                    ok = (((_svcstore._load(gid).get("metadata") or {}).get(_hi.BALANCE_KEY) or {}).get("at") == now)
                if not ok:
                    continue
                moved.append(gid)
                _hi.shift(load, row["mover"], to, _handoff.ho_same)
                gone.append((row["mover"], gid, to))
                print(f"balance: {gid} {row['kind']}, moved from {row['mover']} to {to}", file=sys.stderr, flush=True)
            elif not _hi.balance_others(builders[project], row["mover"], row["tried"], _handoff.ho_same, front, project):
                _balance_log_once(gid, "alone", now, f"balance: {gid} stays with {row['mover']}: no other builder to move it to")      # a mover that is the only builder has nobody to lose: no note, no message
            else:
                with _writes.ITEM_LOCK:
                    item = _svcstore._load(gid)
                    cur = _hi.balance_due({**items, gid: {**item, "gid": gid}}, gid, now, minutes, front, behind, _handoff.ho_same, anchored, is_builder)
                    if cur is None or cur["capped"] or cur["told_none"] or not _handoff.ho_same(cur["mover"], row["mover"]):
                        continue
                    meta = item.setdefault("metadata", {})
                    _hi.mark_balance_none(meta, now)
                    _stall.note(meta, now, f"not started or queued for {minutes:g} min, but no live builder could take it, so it stays with {_sr._session_label(row['mover'])}: " + (f"a summary goes to {_sr._session_label(main)}" if main else "the project has no -main agent to tell"))
                    _writes.save(gid, item, note="balance: no live builder")
                if main:
                    told.setdefault(main, []).append((gid, f"{lead}: not started or queued for {minutes:g} min, and no live builder could take it, so it stays with {_sr._session_label(row['mover'])}"))
                print(f"balance: {gid} no live builder", file=sys.stderr, flush=True)
        except Exception as e:  # noqa: BLE001  — one item never stops the others
            print(f"balance: {gid} not balanced: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    for frm in dict.fromkeys(f for f, _g, _t in gone):      # the former mover is told once per item it left, in one message however many: only for an item this pass moved
        try:
            if _telling.front_keeper(frm, "")[0] or _model.is_owner(frm) or not _ho.is_session_name(frm) or dead(frm):
                continue      # a front agent is never sent it unmarked; a pane that is gone cannot take it (and a failed send would leave an `undelivered` note on the item that just moved)
            mine = [(g, t) for f, g, t in gone if f == frm]
            if len(mine) == 1:
                text = f"Disregard: {_gh.shown(mine[0][0])} is now with {_sr._session_label(mine[0][1])}. Drop it, stop any work or subagent on it, and write nothing to it. No reply is owed."
            else:
                text = (f"Disregard: {len(mine)} items are now with other sessions:\n" + "\n".join(f"- {_gh.shown(g)} is now with {_sr._session_label(t)}" for g, t in mine)
                        + "\nDrop them, stop any work or subagent on them, and write nothing to them. No reply is owed.")
            _telling.tell_woken(",".join(g for g, _t in mine), _hooks().session_id(frm) or frm, text, tag="balance")
        except Exception as e:  # noqa: BLE001
            print(f"balance: {frm} not told to disregard: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    for main, pairs in told.items():
        try:
            gids, lines = [g for g, _l in pairs], [l for _g, l in pairs]
            body = lines[0] + "." if len(lines) == 1 else f"{len(lines)} items stay where they are:\n" + "\n".join("- " + x for x in lines)
            _telling.tell_news(dict(pairs), ",".join(gids), _hooks().session_id(main) or main, f"[stackshot] {body}\nNothing is asked of you and no reply is owed; nothing here is for {OWNER}. → "
                        + (_telling.notice_link(gids[0]) if len(gids) == 1 else _inst.BOARD_URL), tag="stall_summary")
        except Exception as e:  # noqa: BLE001
            print(f"balance: {main} not told: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return moved
