"""audit_ticks.py: the ten-minute audit ticks and the minute balancer, the server's own half of the audit.

The audit decides in audit/ (the pure halves: audit_checks, audit_run, hourly, busy_tell, hand_idle, silence, subagent_tie) and the server writes and sends: this module is the writing half, run by the minute set
(service/runner.py) through its table. The ten-minute filing pass (`_filing_tick`), the dates pass (`_dates_tick`, with the expected-time look `_dates_expected_tick` and the For you list's due-date look it opens),
the archive sweep (`_archive_tick`) and the audit tick (`_silence_tick`: the hourly audit line `_hourly_tick`, the idle hand-over `_hand_idle_tick`, the long-busy message `_busy_tell_tick`) are here, and the
balancer (`_balance_tick`, its own minute tick) with the reads it shares: `_silence_env`, the environment every audit pass is built with; `_queue_map`, who is queued behind another item, kept `_QUEUE_TTL` seconds in
`_QUEUE_CACHE`; `_mover_subagents`, the running subagents of a mover; and `_BALANCE_LOGGED`, the stderr lines the balancer throttles.

A service module: it reads the store and writes an item only through `writes.save`, under the item lock. The debounced publish of the board, the session id of a name, the audit's modules and the open items'
reader of tools/ (audit/ and tools/ sit outside the layers) are the surface's or the audit's, reached through service/save_hooks.py when a pass runs. A suite that replaces one of these sets it on this module
(and `time` here, since this module reads its own; the module state `_QUEUE_CACHE` and `_BALANCE_LOGGED` is reset here too).

Imports point down only: this module imports the domain, core and the services beside it, never web/, audit/ and tools/."""
from __future__ import annotations

import datetime as dt
import sys
import time
from typing import Any, Callable

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core import instance as _inst
from stackshot.core import readonly as _ro
from stackshot.core.instance import OWNER
from stackshot.fleet import liveness as _lv
from stackshot.fleet import sessions_registry as _sr
from stackshot.github import ghsync as _gh
from stackshot.model import model as _model
from stackshot.model import queued as _queued
from stackshot.model import said as _said
from stackshot.projects import project_archive as _archive
from stackshot.projects import projects as _prj
from stackshot.projects.project_registry import _registry
from stackshot.router import router as _router
from stackshot.service import agents as _agents
from stackshot.service import foryou_events as _fyev
from stackshot.service import handoff as _handoff
from stackshot.service import item_read as _item_read
from stackshot.service import ladder as _laddersvc
from stackshot.service import released_live as _rlive
from stackshot.service import store as _svcstore
from stackshot.service import telling as _telling
from stackshot.service import wait_fixes as _wait_fixes
from stackshot.service import wait_gates as _wait_gates
from stackshot.service import writes as _writes
from stackshot.service.messaging import _FOR_OWNER
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


def _silence_tick() -> "dict[str, Any] | None":
    """The ten-minute audit tick (the name is the runner's key and stays): the hourly audit line (`_hourly_tick`), then the hand-over of the items it found idle (`_hand_idle_tick`), then the one message about an item whose lines have only said "busy" for hours (`_busy_tell_tick`). Each is switched by
    its own `[audit]` key and stands still when off. Stands still when the audit is off or runs in agent mode. One that raises never stops the other; the first error is printed."""
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
    try:
        _busy_tell_tick()
    except Exception as e:  # noqa: BLE001  — the lines above have run
        print(f"audit: long busy stretches not told: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return None


def _mover_subagents(who: str, idx: "dict[str, Any] | None" = None, now: float | None = None) -> "list[dict[str, Any]]":
    """The running subagents of the session `who` on this box (audit/subagent_tie.running, read from the transcript Claude Code keeps: its `subagents/` folder beside the session's transcript, in the roots `[said] transcripts`), the one
    the hourly audit ties to an item. Only a pane that is in a turn right now has any (a subagent keeps its pane busy; one left by a recycled pane is not running), so a pane that is idle or showing a shell and a session this box does not
    run give []: nothing is claimed there. A session registered on this box but not as an interactive pane (a headless session), a registry status this server does not know, a pane in a turn whose transcript this box does not hold, or one
    whose registry row names no session raise `subagent_tie.Unreadable`: the audit reads that as unknown, never as idle. So does a session with no row on this box that the fleet's heartbeat holds running (it is on another machine: a mover
    there must not read idle and be handed on), a sessions index that cannot be read, one that is empty, and one that is partial (a machine's sessions.json that could not be read: `fleet.sessions_unreadable`). Only a session with no row anywhere in a whole index (the heartbeat marks it gone, or holds none) gives []."""
    _tie = _hooks().audit_mod("subagent_tie")
    try:
        idx = _sr._sessions_index() if idx is None else idx
    except Exception as e:  # noqa: BLE001
        raise _tie.Unreadable(f"the fleet's sessions index cannot be read ({e.__class__.__name__})") from e
    row = _handoff.handoff_pane_row(who, idx)
    if row is None:
        if _handoff.handoff_registered(who, idx):      # a row is there but it is no interactive pane (a headless session, say): this server cannot look into it, which is not the same as the session being gone
            raise _tie.Unreadable("the session is registered here but is no interactive pane this server can look into")
        w = str(who or "").strip()
        names = {x for x in (w, _sr._session_label(w)) if x}
        rows = [r for r in dict.values(idx) if isinstance(r, dict) and r.get("name") in names]
        byid = idx.get(w) if w else None
        if isinstance(byid, dict) and not any(byid is r for r in rows):
            rows.append(byid)
        if any(_lv.running(r) for r in rows):      # no row on this box, but the fleet's heartbeat holds the session running: it is on another machine (or its row here is not yet written), and its subagents cannot be read from here
            raise _tie.Unreadable("the session runs on another machine, whose subagents this server cannot read")
        if not len(idx):      # an empty index says nothing about this session (the heartbeat was not read, or holds nothing yet): "no row" is not "gone" then
            raise _tie.Unreadable("the fleet's sessions index is empty")
        if getattr(idx, "unreadable", None):      # a machine's sessions.json that could not be read leaves its sessions out: this one may be on it
            raise _tie.Unreadable(f"the fleet's sessions index is partial (machine {', '.join(str(x) for x in idx.unreadable)} not read)")
        return []      # no row of a live process anywhere in a whole index (local registry or heartbeat; one the heartbeat marks gone is no live session): nothing is claimed for it (idle, as before; the orphan hand-over and the idle hand-over are right to act)
    st = str(row[1].get("status") or "")
    if st in ("idle", "shell"):
        return []      # a pane that is not in a turn has no subagent running (a subagent keeps its pane busy)
    if st != "busy":
        raise _tie.Unreadable(f"the pane's registry status is {st or 'missing'}, not one this server knows")
    sid = str(row[1].get("sessionId") or "")
    if not sid:
        raise _tie.Unreadable("the pane's registry row names no session")
    return _tie.running(sid, _said.roots_of(_cfg.get("said", "transcripts")), time.time() if now is None else now)


def _hourly_tick(now: float | None = None, items: "dict[str, dict[str, Any]] | None" = None, env: Any = None, pane: "Callable[[str], str] | None" = None,
                 subagents: "Callable[[str], list[dict[str, Any]]] | None" = None, anchored: "dict[str, Any] | None" = None) -> list[str]:
    """The hourly audit line (audit/hourly.py, `[audit] hourly_line`, on by default), run from the ten-minute audit tick: an open item on an agent with no activity for 45 minutes (`hourly.EVERY`, so the line lands inside the hour), and no audit line in the last
    45 minutes, gets ONE History line, `Audit hh:mm: verified …` or `Audit hh:mm: idle, nothing verified`, one every 45 minutes (`hourly.FAST_GAP`) for the first 24 hours of silence and then one every 6 hours (an entry of `metadata.hourly_audit.log`, kept apart from the stall ladder's
    `metadata.stall.log`; kind `audit`, `audit_idle` or `audit_unknown`: a line for an item the audit could not tell about, because a running subagent of the mover is tied to no item or the mover's subagents could not be read).
    What is verified is recorded data: the mover's pane `busy` in the CLI's registry on this box (`_handoff.handoff_status`, the stall pass's own read), a running subagent of the mover whose description or brief names THIS item or a pull request anchored to it (`_mover_subagents`, audit/subagent_tie.py: a step status in progress is only the mover's claim and is not read), and a tied pull
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
    try:
        idx = _sr._sessions_index() if (pane is None or subagents is None) else {}
        idx_ok = True
    except Exception as e:  # noqa: BLE001  — the pane reads then see this box's registry alone; the subagents read tries the index again and is unknown when it still fails
        idx, idx_ok = {}, False
        print(f"audit: sessions index not read for the hourly line: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    if pane is None:
        pane = lambda who: _handoff.handoff_status(who, idx)[0]      # noqa: E731  — a pane on another box shows nothing: unknown, so not verified
    if subagents is None:
        seen: dict[str, Any] = {}      # a mover's subagents are read once a pass, not once an item: a read that failed is kept too (as the exception), so the transcript lookup is not repeated for every item and again under the item lock
        def subagents(who: str) -> "list[dict[str, Any]]":
            if who not in seen:
                try:
                    seen[who] = _mover_subagents(who, idx if idx_ok else None, now)
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
            _telling.tell_woken(",".join(gids), _hooks().session_id(to) or to, f"{_FOR_OWNER}\n[stackshot] {body}\nNo reply is owed to the audit; nothing here is for {OWNER}. → "
                                + (_telling.notice_link(gids[0]) if len(gids) == 1 else _inst.BOARD_URL), tag="stall")
        except Exception as e:  # noqa: BLE001
            print(f"audit: {to} not told of the busy stretches: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return done


def _hand_idle_builders(project: str) -> list[str]:
    """The sessions an idle item of `project` may be handed to, best first: the project's own background agents (`_handoff.handoff_background`) and no other project's. A project's work is built, reviewed and released by its
    own builder, so a builder of an unrelated project is never a candidate, however idle. A project with no free background agent of its own keeps the item, and `_hand_idle_tick` says so to its -main agent."""
    return list(_handoff.handoff_background(project))


def _hand_idle_tick(now: float | None = None, items: "dict[str, dict[str, Any]] | None" = None, env: Any = None, status: "Callable[[str], str] | None" = None,
                    dead: "Callable[[str], str] | None" = None) -> list[str]:
    """Idle items go to a free builder (audit/hand_idle.py, `[audit] hand_idle`, on by default), run from the ten-minute audit tick right after the hourly line: an open item on an agent whose newest audit line is
    `idle, nothing verified` and that nothing has moved since goes to the first free builder (a background agent of its own project, never another project's; one whose pane is in no turn on this box and
    that moves no open item on an agent), by the minute hand-off pass's own write (`_handoff.handoff_exec` → `_handoff.handoff_write_move`, as the audit's orphan hand-over does): the builder heads `needs`, the hand-off record is made
    from the server and the builder is told. One History line says why and names the mover it left. The project's -main agent gets one message that asks nothing. With no builder free nothing moves: a History
    line says so and -main is told once per item per 24 hours. No message goes to the owner and no step is made for him. At most `hand_idle.MAX_PER_TICK` items are handed on per pass and one per item per 24 hours.
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
    if status is None or dead is None:
        idx = _sr._sessions_index()
        status = status or (lambda who: _handoff.handoff_status(who, idx)[0])
        dead = dead or (lambda who: _handoff.handoff_pane(who, idx))
    busy = _hi.busy_movers(items, now)
    handed: list[str] = []
    told: dict[str, list[tuple[str, str]]] = {}      # -main agent -> (item, line) of its message
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
            elif not row["told_none"]:
                with _writes.ITEM_LOCK:
                    item = _svcstore._load(gid)
                    cur = _hi.due({**items, gid: item}, gid, now, front)
                    if cur is None or cur["told_none"] or not _handoff.ho_same(cur["mover"], row["mover"]):
                        continue
                    meta = item.setdefault("metadata", {})
                    _hi.mark_none(meta, now)
                    _stall.note(meta, now, "no activity for an hour and nothing verified, but no builder was free to take it: " + (f"{_sr._session_label(main)} was told" if main else "the project has no -main agent to tell"))
                    _writes.save(gid, item, note="audit: idle, no builder free")
                if main:
                    told.setdefault(main, []).append((gid, f"{lead}: no activity for an hour and nothing the audit could verify, and no builder was free to take it, so it stays with {_sr._session_label(row['mover'])}"))
                print(f"audit: {gid} idle, no builder free", file=sys.stderr, flush=True)
        except Exception as e:  # noqa: BLE001  — one item never stops the others
            print(f"audit: {gid} idle item not handed on: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    for main, pairs in told.items():
        try:
            gids, lines = [g for g, _l in pairs], [l for _g, l in pairs]
            body = lines[0] + "." if len(lines) == 1 else f"{len(lines)} items had no activity for an hour and nothing the audit could verify:\n" + "\n".join("- " + x for x in lines)
            _telling.tell_woken(",".join(gids), _hooks().session_id(main) or main, f"{_FOR_OWNER}\n[stackshot] {body}\nNothing is asked of you and no reply is owed; nothing here is for {OWNER}. → "
                        + (_telling.notice_link(gids[0]) if len(gids) == 1 else _inst.BOARD_URL), tag="stall")
        except Exception as e:  # noqa: BLE001
            print(f"audit: {main} not told of the idle items: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return handed


_BALANCE_LOGGED: dict[tuple[str, str], float] = {}   # (item, reason) -> when the balancer last logged it: a stay that lasts is one stderr line an hour, not one a minute
BALANCE_LOG_EVERY = 3600.0


def _balance_log_once(gid: str, key: str, now: float, line: str) -> None:
    """One stderr line for an item the balancer leaves where it is, at most once per `BALANCE_LOG_EVERY` per item and reason (the pass looks at the item every minute for as long as it waits)."""
    last = _BALANCE_LOGGED.get((gid, key))
    if last is not None and 0 <= now - last < BALANCE_LOG_EVERY:
        return
    if len(_BALANCE_LOGGED) > 2000:
        _BALANCE_LOGGED.clear()
    _BALANCE_LOGGED[(gid, key)] = now
    print(line, file=sys.stderr, flush=True)


def _balance_builders(project: str) -> list[str]:
    """The sessions the balancer may move an item of `project` to, best first: the project's own BUILDERS only (the mandate says build, maintain, merge or engineer: `_handoff.handoff_ranked` classes them 0 and 1). Never another
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
    why. The mover it left is told ONCE, by `tell_woken` (not the message tool, which would name it in `needs` again), to disregard the item. An item its mover started (a taken hand-off, a step status in progress or done, a
    subagent, an anchor, a pull request event) is never moved. `metadata.balance` ({at, from, to, count}) keeps the limits and is written in the save of the move, before anything is sent: one move per item per 24 hours, two
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
    if status is None or dead is None:
        idx = _sr._sessions_index()
        status = status or (lambda who: _handoff.handoff_status(who, idx)[0])
        dead = dead or (lambda who: _handoff.handoff_pane(who, idx))
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
                    _stall.note(meta, now, f"already moved {_hi.BALANCE_LIFETIME} times by the balancer, so it stays with {_sr._session_label(row['mover'])} and the ladders have it: " + (f"{_sr._session_label(main)} was told" if main else "the project has no -main agent to tell"))
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
                    _stall.note(meta, now, f"not started or queued for {minutes:g} min, but no live builder could take it, so it stays with {_sr._session_label(row['mover'])}: " + (f"{_sr._session_label(main)} was told" if main else "the project has no -main agent to tell"))
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
            _telling.tell_woken(",".join(gids), _hooks().session_id(main) or main, f"{_FOR_OWNER}\n[stackshot] {body}\nNothing is asked of you and no reply is owed; nothing here is for {OWNER}. → "
                        + (_telling.notice_link(gids[0]) if len(gids) == 1 else _inst.BOARD_URL), tag="stall")
        except Exception as e:  # noqa: BLE001
            print(f"balance: {main} not told: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return moved
