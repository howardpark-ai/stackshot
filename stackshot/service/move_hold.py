"""move_hold.py: the one question every pass asks before it takes an item from its mover, and what is told when the answer keeps it there for long.

An item whose mover is working on it is never moved. The item does not always say so: a subagent writes nothing until it reports. So a pass asks `held(gid, mover)` first (`checker()` for a pass over many items), which reads
the fleet's last agent-state push (audit/hand_idle.py `subagent_hold` over audit_ticks `_mover_subagents`): a running subagent tied to the item, one tied to none of the mover's open items, or subagents that cannot be
read (no fresh push, the agent not in it, its state not read) keep the item with its mover. A mover with no pane runs nothing, and an item with no agent mover has nobody to take it from.

Who asks, one line each (tests/move_hold_scenario.py fails when a module writes a mover or needs and is not accounted for):
  service/handoff.py `handoff_exec`        every `move` step: the hand-off ladder, the project's builder step of the stall ladder and of the one ladder, a failed push's or cold call's next step, the orphan
                                           hand-over, the front hand-on, the idle hand-over and the balancer
  service/stall.py `stall_builder`         before it writes that the item is handed to the builder
  service/handoff_cold.py `handoff_cold`   before the cold call's answer (hand over, close, ask the owner) is written
  service/watching.py `watch_fire`         before a wait's end gives the item to another session than the one that holds it
  service/proofs.py `handover`             before a proof pass's tick moves the item to the next step's session
  service/audit_ticks.py                   the idle hand-over and the balancer, ahead of the step, for their own log line
No session's own write asks, nor the owner's answer, a question a wait turns to the owner, or a one-time migration: none of those is a pass taking work from a session.

A hold for an unreadable state or an untied subagent can last for good, so it is not kept quiet: <state>/move-hold.json holds one record per held item ({mover, kind, why, since, seen, told}), and `report` (the minute
hand-off tick) writes one History line on each item held for UNREAD_AFTER (an unreadable state) or UNTIED_AFTER (an untied subagent) and sends its project's -main agent one summary, each at most once in AGAIN. The
record goes when the item reads as free again, and when no pass has asked about it for GAP; a hold of a step that no pass retries (`once`: a wait's end, a cold answer, a step hand-over) is read again by `report` itself.
A subagent tied to the item itself is work in progress: it is held and nothing is reported.

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/ (reached through the save hooks)."""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from typing import Any, Callable

from stackshot.core import config as _cfg
from stackshot.core import instance as _inst
from stackshot.core import readonly as _ro
from stackshot.core import xlock as _xlock
from stackshot.core.instance import OWNER
from stackshot.fleet import sessions_registry as _sr
from stackshot.github import ghsync as _gh
from stackshot.model import model as _model
from stackshot.model.bullet_text import _clip_line
from stackshot.projects import projects as _prj
from stackshot.service import agents as _agents
from stackshot.service import store as _store
from stackshot.service import telling as _telling
from stackshot.service import writes as _writes
from stackshot.service.handoff_hooks import hooks as _handoff_hooks
from stackshot.service.save_hooks import hooks as _hooks
from stackshot.waits import stall as _stall


UNREAD_AFTER = 3600.0       # the mover's subagents cannot be read: told after this long
UNTIED_AFTER = 7200.0       # a subagent tied to none of the mover's open items: told after this long (a subagent at work for an hour is ordinary)
AGAIN = 86400.0             # one History line per held item and one summary per project in this long
GAP = 1800.0                # a hold no pass has asked about for this long is over (the ten-minute passes ask well inside it): the next starts its own clock
LOCK = _xlock.XLock("move-hold")


def path():
    return _cfg.state("move-hold.json")


def load() -> dict[str, Any]:
    """{"items": {gid: record}, "projects": {project: when its -main agent was last told}}; empty when there is no file or it cannot be read."""
    try:
        d = json.loads(path().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        d = {}
    d = d if isinstance(d, dict) else {}
    return {k: d[k] if isinstance(d.get(k), dict) else {} for k in ("items", "projects")}


def _save(d: dict[str, Any]) -> None:
    try:
        _prj.write_atomic(path(), json.dumps(d, indent=1) + "\n")
    except Exception as e:  # noqa: BLE001  — the record is for the report: the hold itself stands without it
        print(f"move hold: record not saved: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


def _reader(now: float, snap: Any, items: "dict[str, dict[str, Any]] | None", dead: "Callable[[str], str] | None") -> "Callable[[str, str], str]":
    """`ask(gid, mover)` → why the mover keeps the item, "" when nothing does. The open items, the agent-state push and the pane rows are read at the first question, once."""
    made: list[Callable[[str, str], str]] = []

    def ask(gid: str, mover: str) -> str:
        if not mover or _model.is_owner(mover):
            return ""
        if not made:
            from stackshot.service import audit_ticks as _ticks      # noqa: PLC0415  — it imports the services that import this one
            from stackshot.service import handoff as _handoff        # noqa: PLC0415
            seen = _hooks().audit_mod("agent_state").snapshot() or {} if snap is None else snap      # none is {}, which reads every agent unknown
            idx = _sr._sessions_index() if dead is None else None
            made.append(_ticks._move_hold(_hooks().next_report_all(None) if items is None else items, now, seen, dead or (lambda who: _handoff.handoff_pane(who, idx))))
        return made[0](gid, mover)
    return ask


def checker(now: float | None = None, snap: Any = None, items: "dict[str, dict[str, Any]] | None" = None, dead: "Callable[[str], str] | None" = None, once: bool = False) -> "Callable[[str, str], str]":
    """`hold(gid, mover)` for one pass: `_reader`'s answer, noted for the report. `once`: the caller does not try again, so the report reads the item itself."""
    now = time.time() if now is None else now
    ask = _reader(now, snap, items, dead)

    def hold(gid: str, mover: str) -> str:
        why = ask(gid, mover)
        _note(gid, mover, why, now, once)
        return why
    return hold


def held(gid: str, mover: str, now: float | None = None, once: bool = False) -> str:
    """Why `mover` keeps the item `gid`, "" when nothing stops a pass from taking it."""
    return checker(now, once=once)(gid, mover)


def _note(gid: str, mover: str, why: str, now: float, once: bool) -> None:
    """Keep the record of one answer: a new stretch of holding starts its clock, a free answer ends it. One stderr line per stretch."""
    kind = _hooks().audit_mod("hand_idle").hold_kind(why) if why else ""
    with LOCK:
        d = load()
        old = d["items"].get(gid)
        if not kind:      # free, or held by work on the item itself: nothing to tell, and the clock of an earlier hold ends
            if old is not None:
                del d["items"][gid]
                _save(d)
            return
        goes_on = bool(old) and old.get("kind") == kind and old.get("mover") == mover and (old.get("once") or now - float(old.get("seen") or 0) <= GAP)
        rec = dict(old) if goes_on else {"mover": mover, "kind": kind, "since": now, "told": float((old or {}).get("told") or 0)}
        rec.update(why=why, seen=now, once=once)
        d["items"][gid] = rec
        _save(d)
    if not goes_on:
        print(f"move hold: {gid} stays with {mover}: {why}", file=sys.stderr, flush=True)


def say(gid: str, text: str, now: float) -> None:
    """One History line on the item `gid` (metadata.stall.log, which History shows); no clock moves."""
    with _writes.ITEM_LOCK:
        item = _store._load(gid)
        _stall.note(item.setdefault("metadata", {}), now, text)
        _writes.save(gid, item, note="move hold")


def _when(at: float) -> str:
    return dt.datetime.fromtimestamp(at, _cfg.tz()).strftime("%m-%d %H:%M")


def report(now: float | None = None) -> list[str]:
    """Tell the holds that have lasted: a History line on each item and one message per project to its -main agent (never the owner), each at most once in AGAIN. A record whose item is closed, or reads as free or as
    held for another reason, or that no pass has asked about for GAP (a `once` record aside), is dropped first. → the ids told. Never raises."""
    try:
        if _ro.is_read_only():
            return []
        now = time.time() if now is None else now
        recs = load()["items"]
        if not recs:
            return []
        items = _hooks().next_report_all(None)
        ask = _reader(now, None, items, None)
        kind_of = _hooks().audit_mod("hand_idle").hold_kind
        gone: dict[str, float] = {}      # gid -> the `seen` the record was judged on: one asked about again meanwhile is kept
        due: list[tuple[str, dict[str, Any]]] = []
        for gid, rec in recs.items():
            item = items.get(gid)
            quiet = not rec.get("once") and now - float(rec.get("seen") or 0) > GAP
            if quiet or not item or item.get("status") != "open" or (rec.get("once") and not _handoff_same(_telling.holder(item), rec.get("mover"))):
                gone[gid] = rec.get("seen")
                continue
            why = ask(gid, str(rec.get("mover") or ""))
            if (kind_of(why) if why else "") != rec.get("kind"):
                gone[gid] = rec.get("seen")
                continue
            limit = UNREAD_AFTER if rec.get("kind") == "unread" else UNTIED_AFTER
            if now - float(rec.get("since") or now) >= limit and now - float(rec.get("told") or 0) >= AGAIN:
                due.append((gid, {**rec, "why": why}))
        projects: dict[str, list[tuple[str, str]]] = {}      # project -> (item, its line of the summary)
        for gid, rec in sorted(due):
            item = items[gid]
            project = str((item.get("metadata") or {}).get("project") or "")
            who = _sr._session_label(rec["mover"]) or rec["mover"]
            say(gid, f"held with {who} since {_when(rec['since'])}: {rec['why']}; no pass moves it until that clears", now)
            projects.setdefault(project, []).append((gid, f"{_gh.shown(gid)} \"{_clip_line(str(item.get('subject') or ''), 80)}\" with {who} since {_when(rec['since'])}: {rec['why']}"))
        with LOCK:
            d = load()
            for gid, seen in gone.items():
                if (d["items"].get(gid) or {}).get("seen") == seen:
                    del d["items"][gid]
            for gid, _rec in due:
                if gid in d["items"]:
                    d["items"][gid]["told"] = now
            tell = {p: rows for p, rows in projects.items() if now - float(d["projects"].get(p) or 0) >= AGAIN}
            for p in tell:
                d["projects"][p] = now
            _save(d)
        for project, rows in tell.items():
            _tell(project, rows)
        return [gid for gid, _rec in sorted(due)]
    except Exception as e:  # noqa: BLE001  — a report that fails stops no pass
        print(f"move hold: report not made: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return []


def _handoff_same(a: Any, b: Any) -> bool:
    from stackshot.service import handoff as _handoff      # noqa: PLC0415
    return _handoff.ho_same(a, b)


def _tell(project: str, rows: list[tuple[str, str]]) -> None:
    """The one summary of a project's held items to its -main agent; nothing when it names none (the History lines stand)."""
    try:
        main = _agents._main_agent(project)
        if not main or _model.is_owner(main):
            return
        gids = [g for g, _line in rows]
        body = (f"moves are held on {len(rows)} item{'s' if len(rows) != 1 else ''} of {project}: a subagent of the mover may be at work, so no pass hands them on.\n"
                + "\n".join("- " + line for _g, line in rows)
                + "\nSubagents that cannot be read: see that the fleet's agent-state push reaches stackshot. A subagent tied to none of its mover's items: name the item in its description, or let it end. "
                  f"No reply is owed; nothing here is for {OWNER}. → ")
        _telling.tell_news(dict(rows), ",".join(gids), _handoff_hooks().session_id(main) or main, f"[stackshot] {body}" + (_telling.notice_link(gids[0]) if len(gids) == 1 else _inst.BOARD_URL), tag="stall_summary")
    except Exception as e:  # noqa: BLE001
        print(f"move hold: the -main agent of {project} not told: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
