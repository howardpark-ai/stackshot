"""stall_tick.py: the stall pass, once a minute.

When the session that moves a live item has no turn running for [stall] minutes (10), stackshot moves the item on itself. The signal is the CLI's registry, read by `handoff_status` (service/handoff.py): the mover's
pane is idle (or `shell`: turn over, a background Bash task running) and its status changed that long ago. Every [stall] every_seconds (20), every open alive item whose mover is a session, a front agent included,
is looked at. After the minutes: (1) the notice goes to the mover once more; (2) the same minutes later, with no turn and no write: the hand-off's cold call (`handoff_cold`, service/handoff_cold.py) names who takes
it, or hands over to the builder when it names no one: it never asks the owner (`stall_cold_no_taker`); (3) the same minutes after that, the project's builder (`handoff_builder`, through `handoff_exec`); (4) when none
can take it, ONE message goes to the fleet's builder (`_recovery_tell` in server.py: the item, the quiet session, what was tried, asking it to take the fix through its usual path), or to the project's -main agent when
the project is front-only (anchors.front_only: no background agent on its map, so no builder was tried; `_recovery_target`), once for the hand-off record (recovery_at), with a History line; the item stays with its
mover and does not go to the owner. Not looked at: an item in a hold or on a wait, one the owner or an outside party moves (the model derives no session mover), a hand-off in flight to a session that is not a front
agent (the hand-off ladder has it), a cold call running, a pane the registry does not show (nothing can be told of it), and an item whose hand-off record already carries the recovery request. Each step is written onto
the item (metadata.stall.log, a History line) and the journal.

With the one ladder on (service/ladder.py) the same walk takes the ladder's rungs instead, and hands a silent live background mover's item up to its project's -main agent. The state and the steps are service/stall.py's; the
pure rules are waits/stall.py and waits/ladder.py. What the pass still reaches in server.py comes through `Hooks` in service/stall_hooks.py, looked up when it runs. A suite that replaces a function or a clock
of the pass sets it here (and `time` here, since this module reads its own).

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import json
import sys
import time
from typing import Any

from stackshot.core import instance as _inst
from stackshot.core.store import _item_files
from stackshot.fleet.sessions_registry import _sessions_index
from stackshot.model import queued as _queued
from stackshot.service import handoff as _handoff
from stackshot.service import ladder as _laddersvc
from stackshot.service import stall as _stallsvc
from stackshot.service import telling as _telling
from stackshot.service.stall_hooks import hooks as _hooks
from stackshot.service.store import _load
from stackshot.waits import handoff as _ho
from stackshot.waits import ladder as _ladder
from stackshot.waits import stall as _stall


def stall_tick(now: float | None = None) -> list[str]:
    """The stall pass (the runner calls it every 60 s; [stall] every_seconds gates it, so a value below 60 still runs once per round): the items it acted on, by gid."""
    now = time.time() if now is None else now
    if not _stallsvc.stall_on(now) or _handoff.handoff_paused():
        return []
    if now - _stallsvc.STALL_LAST[0] < _stallsvc.stall_num("every_seconds", _stall.EVERY):
        return []
    _stallsvc.STALL_LAST[0] = now
    minutes = _stallsvc.stall_minutes()
    ladder_on, look = _laddersvc.ladder_on(), _laddersvc.ladder_look()
    since = _stallsvc.stall_since(now)          # no clock starts before the pass first ran (a deploy must not step every long-idle pane at once)
    cap = max(1, int(_stallsvc.stall_num("max_per_tick", _stall.MAX_PER_TICK)))
    old_st = _stallsvc.stall_load()
    old_snap = json.loads(json.dumps(old_st))      # as loaded: the pass changes its entries in place, and the save below tells what was written meanwhile by comparing with this
    idx = _sessions_index()
    keep: dict[str, dict[str, Any]] = {}
    todo: list[tuple[str, str, str, dict[str, Any]]] = []
    queue = _hooks().queue_map(now, _hooks().next_report_all(None)) if _queued.enabled() else {}      # an item queued behind another of its mover's reads waiting: the ladder leaves it as it leaves a waiting one
    for gid, _p in _item_files():
        try:
            it = _load(gid)
            if it.get("status") != "open":
                continue
            if _stall.not_due(it, now, lambda i_: _hooks().after_open(i_.get("metadata") or {})) or gid in queue:
                continue                 # its work is not due now (the board shows it waiting, or it is the owner's or an outsider's move): no record is kept, so its clock starts when it is due
            old = old_st.get(gid)
            if not ladder_on:
                old = _ladder.unwind(old)      # the flag was turned off in the middle of a ladder: its steps are read in the old table (the builder rung stays reachable)
            if old and not _stall.expired(old, now):
                keep[gid] = old
            who = _stallsvc.stall_mover(gid, it)
            meta = it.get("metadata") or {}
            r = _ho.record_of(it)
            if not who or not _ho.is_session_name(who) or (r and r.get("recovery_at")):
                continue                 # no session mover, or the fleet's builder was asked already for this record
            if isinstance(r and r.get("cold"), dict) and r["cold"].get("state") == "running" and now - float(r["cold"].get("at") or 0) < _ho.COLD_STALE:
                continue                 # a cold call is out
            front = _telling.front_keeper(who, str(meta.get("project") or ""))[0]
            quiet = bool(ladder_on and old and _ladder.quiet(old))      # the dates pass's entry: it ends with activity on the item, a new mover, not with a write or a confirm that is no activity
            if quiet and _ladder.quiet_over(old, who, _handoff.ho_same, _hooks().silence_clock(it, who)):
                keep.pop(gid, None)
                if old.get("cold_at"):
                    keep[gid] = _stall.fresh(who, _stallsvc.stall_ver(it), old, 0.0)      # what outlives an episode (the cold call's 24-hour bound) stays
                continue
            if not front and _ho.awaiting_session(it, who, _handoff.ho_same) and not (ladder_on and old and _handoff.ho_same(old.get("mover"), who) and _ladder.on_ladder(old, now, float((r or {}).get("at") or 0))):
                continue                 # an untaken hand-off is the hand-off audit's alone (the dates pass does not start it); once that audit has brought it to the one ladder, the ladder takes its rungs here
            # review: the registry row shows background work in its status. A pane whose turn is over but which has a run_in_background Bash task running (a CI watch, a release) shows
            # `shell`, not `idle`, and stall.action counts `shell` as idle; a pane with a background subagent running shows `busy` and is left alone. A background agent's `shell` pane is
            # working on that job, so it is not quiet (with `[ladder] enabled` the pane is not read for a background agent at all: its item's own step status decides, below). A front agent does no background work of its own (it hands that to the builder), so its `shell` pane counts as idle. A doing item
            # carries no expected time: a mover with no background work running is chased by the minutes of its pane alone.
            status, at = _handoff.handoff_status(who, idx)
            back = bool(ladder_on and not front and _stallsvc.stall_background(who))
            if back:
                # the one ladder: a background agent's pane says nothing about this item (it is nearly always busy, or shows a background shell for a CI watch or a release), so the pane no longer holds
                # the rungs after the ask; the item's own step status does: a line in progress, changed within 90 minutes, is a subagent at work on it. A live pane gets no cold call or builder: its silence goes to the project's -main agent (ladder.action, `ladder_main`).
                if _hooks().silence_subagent_running(it, now, who, _handoff.ho_same):      # only the mover's own line: another agent's stale one holds nothing
                    continue
            elif not front and status == "shell" and _stallsvc.stall_background(who):
                continue
            mine = _stallsvc.stall_confirm(it, who)      # only the mover's own confirm says it still has the item
            rec = (old if quiet else
                   _ladder.episode(old, who, _stallsvc.stall_ver(it), _handoff.ho_same, mine, float(r.get("at") or 0) if r and _handoff.ho_same(r.get("to"), who) and not r.get("taken_at") else None) if ladder_on
                   else _stall.episode(old, who, _stallsvc.stall_ver(it), _handoff.ho_same, mine))
            keep[gid] = rec
            if ladder_on and not quiet and _ladder.via_of(rec) != "handoff":
                continue                 # a pane with no turn running starts no ladder here: the dates pass (a wake passed) does, and the hand-off audit its own
            if _stall.spent(rec, now):
                continue
            floor = max(float(it.get("state_updated") or it.get("updated") or 0), 0.0 if rec.get("capped") else float(rec.get("conf") or 0))      # the mover's own last confirm, kept in the entry (another session's later confirm does not erase it): the minutes count from it, up to stall.RESTARTS times
            if r and _handoff.ho_same(r.get("to"), who):
                floor = max(floor, float(r.get("at") or 0))
            floor = max(floor, _stall.due_at(it, now))    # an item whose wake has just passed has its minutes first
            if quiet:
                floor = 0.0              # the quiet entry's rungs count from the last rung taken and the pane going idle: a write or a confirm that is no activity moves nothing
            live = bool(back and (status or not idx or not _handoff.handoff_pane(who, idx)))      # a pane the registry shows, or one the heartbeat holds live (another machine's); a heartbeat that is empty or unreadable says nothing, so the pane is taken as live
            act = (_ladder.action(rec, status, at, max(floor, since), now, minutes, look, background=back, live=live) if ladder_on else _stall.action(rec, status, at, max(floor, since), now, minutes))
            if act == "cold" and not _handoff.cold_call_on():
                act = "builder"
            if act:
                todo.append((act, gid, who, rec))
        except Exception as e:  # noqa: BLE001  — one item's failure never stops the rest
            print(f"stall: {gid} not looked at: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    acted: list[str] = []
    lines: list[tuple[str, str, str]] = []
    sent = 0
    told: set[str] = set()      # background agents sent a notice this pass: one each, the next item's follows on the next pass
    main_rows: list[tuple[str, str, str]] = []      # (-main agent, gid, line) of the silent live background movers due this pass: one notice per -main agent lists them all (`ladder_main_tell`)
    main_info: dict[str, dict[str, str]] = {}
    for act, gid, who, rec in todo:
        try:
            if ladder_on and act in ("ask", "look") and who in told:
                continue             # one notice per agent per pass: its other items wait for the next
            if act in ("resend", "ask"):         # not the look: it comes 30 minutes after an ask that was counted, so it cannot pile up in one tick the way a deploy's first asks do
                if sent >= cap:
                    continue             # the rest of the first steps wait for the next tick (a deploy or a restart must not send a flood); their episodes are kept as they are
                sent += 1
            if ladder_on and act == _ladder.MAIN:
                did = _laddersvc.ladder_main(gid, who, rec, now, main_rows, main_info)
            elif ladder_on:
                did = _laddersvc.ladder_do(act, gid, who, rec, now, minutes, lines)
            elif act == "resend":
                did = _stallsvc.stall_resend(gid, who, now, minutes, lines)
            elif act == "cold":
                did = _stallsvc.stall_cold(gid, who, now, minutes)
            else:
                did = _stallsvc.stall_builder(gid, who, now, minutes)
            if did:
                acted.append(gid)
                (_ladder if ladder_on else _stall).advance(rec, did, now)
                keep[gid] = rec
                if ladder_on and did in ("ask", "look") and _stallsvc.stall_background(who):
                    told.add(who)
        except Exception as e:  # noqa: BLE001
            print(f"stall: {gid} step {act} failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    with _stallsvc.STALL_LOCK:
        cur = _stallsvc.stall_load()
        gone = {g for g in old_st if g not in cur}       # an entry forgotten while the pass ran (his answer) stays forgotten
        for g in list(keep):
            c = cur.get(g)
            if c and float(c.get("kept") or 0) > float((keep[g] or {}).get("kept") or 0):
                keep[g] = c                 # the cold call kept it with its mover while this pass ran: its entry (the mark and the version after that save) is the newer one
        for g, c in cur.items():
            if g in gone or not c or c == old_snap.get(g):
                continue                    # not written while this pass ran
            if g not in keep or keep[g] == old_snap.get(g):
                keep[g] = c                 # an entry made while the pass ran (the hand-off audit bringing an untaken hand-off to the one ladder, from the push-failure thread) that this pass did not itself change: kept, or the next hand-off tick would bring the item again and ask twice
        _stallsvc.stall_save({g: r for g, r in keep.items() if g not in gone})
    for who, ls in _ho.batch(lines).items():
        gids = ",".join(g for w, g, _l in lines if w == who)
        tail = (f" Work it, hand it on (update sender=<you>) or close it. If nothing is written to it and your pane has no turn running for {minutes:g} more minutes, a fresh session is asked who takes it. → "
                + (_telling.notice_link(gids) if len(ls) == 1 else f"{_inst.BOARD_URL}"))
        _telling.tell_woken(gids, _hooks().session_id(who) or who,
                    _ho.message(ls, f"[stackshot] you have had no turn running for {minutes:g} minutes and this is still yours:",
                                f"[stackshot] you have had no turn running for {minutes:g} minutes and these {{n}} items are still yours:", tail), tag="stall")
    for to in _ho.batch(main_rows):      # ONE notice per -main agent for every silent live background mover's item that came due in this pass
        mine = [(g, l) for t, g, l in main_rows if t == to]
        try:
            _laddersvc.ladder_main_tell(to, mine, main_info)
        except Exception as e:  # noqa: BLE001  — the History lines are written; the next interval tells again
            print(f"stall: the notice to {to} about {len(mine)} silent items failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    if acted:
        _hooks().publish()
    return acted
