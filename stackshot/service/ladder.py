"""ladder.py: the one ladder of the stall pass and the hand-off audit.

With `[ladder] enabled = true` an item whose mover went quiet has ONE record, its entry in <state>/stall.json (`via` says which audit brought it: "handoff" for an untaken hand-off, "stall" for a pane with no turn
running), and one order: ask the mover, look at its pane `[ladder] look_minutes` (30) later, the cold call, the project's builder, then the fleet's builder asked once. The hand-off tick brings an untaken hand-off
to it (`ladder_enter`); the stall tick brings a silent pane and takes every rung after the first of both. With it off (the default) both passes run as they did, each on its own record. The pure rules (which rung
is due, what ends an entry) are waits/ladder.py.

This module holds the switches and the settings of the ladder, the entry the dates pass makes (`ladder_enter_quiet`) and the one the hand-off audit makes (`ladder_enter`), the rungs that are the ladder's own (the
ask, the look, and the hand-up of a silent or a not moving item to the project's -main agent), `ladder_do`, which takes one rung (the steps it shares with the stall pass are in service/stall.py), and the record of
when an item was first seen alive (<state>/progress_alive.json). The pass that walks the items is service/stall_tick.py.

What it still reaches in server.py comes through `Hooks` in service/stall_hooks.py, looked up when it runs, so a suite that replaces one on server.py is the one called. A suite that replaces a function of this
module sets it here.

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import sys
from typing import Any

from stackshot.core import config as _cfg
from stackshot.core import instance as _inst
from stackshot.core.instance import OWNER
from stackshot.core.store import _item_files
from stackshot.fleet.sessions_registry import _session_label, _sessions_index
from stackshot.github import ghsync as _gh
from stackshot.model import progress as _progress
from stackshot.model.bullet_text import _clip_line
from stackshot.service import handoff as _handoff
from stackshot.service import stall as _stallsvc
from stackshot.service import telling as _telling
from stackshot.service import writes as _writes
from stackshot.service.stall_hooks import hooks as _hooks
from stackshot.service.store import _load
from stackshot.waits import handoff as _ho
from stackshot.waits import ladder as _ladder
from stackshot.waits import stall as _stall

_FOR_OWNER = f"[for {OWNER}]"      # the mark a message to a front agent carries on its first line ("[for <owner>]" on the owner's instance), as server.py holds it


def ladder_on() -> bool:
    """`[ladder] enabled` (default false): the hand-off ladder and the stall ladder are one. True only for a TOML true. Read at use, so a reload turns it on or off."""
    return _cfg.get("ladder", "enabled", default=False) is True


def ladder_look() -> float:
    """`[ladder] look_minutes` (30): how long after the ask the mover's pane is looked at."""
    try:
        v = float(_cfg.get("ladder", "look_minutes", default=_ladder.LOOK))
        return v if v > 0 else _ladder.LOOK
    except (TypeError, ValueError):
        return _ladder.LOOK


def alive_path() -> Path:
    return _cfg.state("progress_alive.json")


def alive_load() -> dict[str, float]:
    """When the stall pass first saw each open item due (not waiting, not the owner's move) in its current stretch of being alive: {gid: epoch}. The hand-up of an item that is not moving counts from the
    later of its last progress and this (`progress.due`), so an item parked for a day and then alive again is not handed up for the park. The pass keeps it: the phase sweep writes the stored phase around
    `writes.save` and writes the two keys only, so it cannot restart the progress clock itself."""
    try:
        with open(alive_path(), encoding="utf-8") as f:
            d = json.load(f)
        return {str(k): float(v) for k, v in d.items()} if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def alive_save(d: dict[str, float]) -> None:
    try:
        p = alive_path(); p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(d, indent=1) + "\n", encoding="utf-8"); os.replace(tmp, p)
    except Exception as e:  # noqa: BLE001
        print(f"progress: alive record not saved: {e}", file=sys.stderr, flush=True)


def ladder_main_hours() -> float:
    """`[ladder] main_hours` (4): how long an alive item may go without progress before it is handed up to the project's -main agent, and how long before the same item is handed up again; also the
    interval of the silent-mover notice. A value that is not a positive number is 4."""
    try:
        v = float(_cfg.get("ladder", "main_hours", default=_ladder.MAIN_EVERY / 3600.0))
        return v if v > 0 else _ladder.MAIN_EVERY / 3600.0
    except (TypeError, ValueError):
        return _ladder.MAIN_EVERY / 3600.0


def ladder_enter_quiet(gid: str, who: str, now: float, detail: str = "") -> bool:
    """The dates pass has sent its message to the mover, which is the ask: the item goes on the ladder at its next rung, the look (`[ladder] look_minutes` from now). The entry
    is for this quiet stretch alone (`act`, the item's activity clock now): activity ends it. → whether an entry was written (False: the item is not open, not the mover's, not due, or already on the ladder
    for this stretch). A History line says it; nothing is sent here."""
    with _writes.ITEM_LOCK:
        item = _load(gid)
        if item.get("status") != "open" or not _handoff.ho_same(_stallsvc.stall_mover(gid, item), who) or _stall.not_due(item, now, lambda i_: _hooks().after_open(i_.get("metadata") or {})):
            return False
        clock = _hooks().silence_clock(item, who)
        _stall.note(item.setdefault("metadata", {}), now, f"{_session_label(who)} was asked for news ({_clip_line(detail, 120) or 'no activity'}): the ladder goes on from here")
        _writes.save(gid, item, note="ladder: asked for news")
        ver, conf = _stallsvc.stall_ver(item), _stallsvc.stall_confirm(item, who)
    with _stallsvc.STALL_LOCK:
        cur = _stallsvc.stall_load()
        old = cur.get(gid)
        if old and _ladder.quiet(old) and _handoff.ho_same(old.get("mover"), who) and float(old.get("act") or 0) == clock:
            return False
        cur[gid] = _ladder.enter_quiet(old, who, ver, conf, clock, now)
        _stallsvc.stall_save(cur)
    print(f"ladder: {gid} {who} asked for news: {_clip_line(detail, 120)}", file=sys.stderr, flush=True)
    return True


def ladder_quiet_look(gid: str, who: str, now: float, minutes: float) -> bool:
    """The look of an item the dates pass brought: the item still has no activity, so the mover is told once more (a front agent gets the History line alone: no item notice wakes one). The pane is
    not described: a background agent's is busy or showing a background shell nearly always, so the notice says what the item shows (nothing written for N minutes, N from its last write) and no more.
    → whether the rung was taken."""
    with _writes.ITEM_LOCK:
        item = _load(gid)
        if item.get("status") != "open" or not _handoff.ho_same(_stallsvc.stall_mover(gid, item), who):
            return False
        meta = item.setdefault("metadata", {})
        front = _telling.front_keeper(who, str(meta.get("project") or ""))[0]
        span = _hooks().silence_minutes(now - _hooks().silence_clock(item, who))
        _stall.note(meta, now, f"{_session_label(who)}: nothing was written to it for {span}" + (": no notice is sent to a front agent, the next rung follows" if front else ": the notice was sent to it again"))
        _writes.save(gid, item, note="ladder: " + ("no notice to a front agent" if front else "the notice was sent again"))
        subject = str(item.get("subject") or "")
    if not front:
        tail = "" if _stallsvc.stall_background(who) else (f" If nothing is written to it and your pane stays quiet for {minutes:g} more minutes, a fresh session is asked who takes it.")
        _telling.tell_woken(gid, _hooks().session_id(who) or who,
                    f"[stackshot] {_gh.shown(gid)} \"{subject}\" is still yours: nothing written for {span}. Work it, hand it on (update sender=<you>) or close it. "
                    f"If you are waiting on something to happen, store the wait so the server watches it.{tail} → {_telling.notice_link(gid)}", tag="stall")
    print(f"ladder: {gid} {who} still silent after the ask: " + ("front agent, history line only" if front else "notice sent again"), file=sys.stderr, flush=True)
    return True


def ladder_main_to(gid: str, who: str) -> str:
    """Who the ladder's notice about a silent live background mover goes to: the item's project's -main agent (`_main_agent`, a front agent), "" when the project has none or when it is the mover itself."""
    try:
        to = _hooks().main_agent(str((_load(gid).get("metadata") or {}).get("project") or ""))
    except Exception:  # noqa: BLE001
        return ""
    return "" if not to or _hooks().session_id(to) == _hooks().session_id(who) else to


def ladder_no_main(gid: str, who: str) -> str:
    """Why nobody is told when `ladder_main_to` is empty, in words for the History line: the mover is itself the project's -main agent (nobody above it to tell), or the project has none."""
    try:
        main = _hooks().main_agent(str((_load(gid).get("metadata") or {}).get("project") or ""))
    except Exception:  # noqa: BLE001
        main = ""
    return "its mover is the project's -main agent, so there is no one above it to tell" if main and _hooks().session_id(main) == _hooks().session_id(who) else "the project has no -main agent to tell"


def ladder_main(gid: str, who: str, rec: dict[str, Any], now: float, rows: "list[tuple[str, str, str]] | None" = None, info: "dict[str, dict[str, str]] | None" = None) -> str:
    """The rung a live background mover's silence climbs to after the look (ladder.MAIN): a notice to the project's -main agent, which asks it to decide whether the item needs a nudge or a
    different mover, because the cold call and the builder replace a mover that cannot answer and this one can, so without it the item would sit unseen. A History line on the item says it. Taken
    with a History line alone when the project has no -main agent to tell.
    With `rows` (the stall tick gives it) the notice is not sent here: the item's (-main agent, gid, line) is added to `rows` and the tick sends ONE notice per -main agent for all its items due in the pass
    (`ladder_main_tell`, as the resend path batches with `_ho.batch`), `info` keeping what a lone item's wording needs; without it the notice for this one item goes at once. → the rung taken."""
    with _writes.ITEM_LOCK:
        item = _load(gid)
        if item.get("status") != "open" or not _handoff.ho_same(_stallsvc.stall_mover(gid, item), who):
            return ""
        last = _hooks().silence_clock(item, who)
        meta = item.setdefault("metadata", {})
        to = ladder_main_to(gid, who)
        span = _hooks().silence_minutes(now - last) if last > 0 else "a long time"
        since = _hooks().when_words(dt.datetime.fromtimestamp(last, _hooks().zone())) if last > 0 else "it was handed over"
        before = float(rec.get("main_at") or 0)      # when -main was told about this silence last, if it was
        told = _hooks().when_words(dt.datetime.fromtimestamp(before, _hooks().zone())) if before else ""
        data = {"subject": str(item.get("subject") or ""), "project": str(meta.get("project") or ""), "mover": _session_label(who), "since": since, "span": span, "told": told}
        meta[PROGRESS_UP] = now      # one hand-up per stretch: the no-progress path (`ladder_stuck`) leaves the item alone for its interval after this notice too
        _stall.note(meta, now, f"{_session_label(who)} is live but wrote nothing to it for {span}: " + (f"{_session_label(to)} was told to decide on a nudge or a different mover" if to else ladder_no_main(gid, who)))
        _writes.save(gid, item, note="ladder: " + (f"{_session_label(to)} told that its mover is silent" if to else "its mover is silent, " + ("it is the -main agent itself" if "is the project" in ladder_no_main(gid, who) else "no -main agent to tell")))
    if to:
        line = f"{_gh.shown(gid)} \"{data['subject']}\" ({data['project']}): mover {data['mover']}, no write since {since} ({span})" + (f", told before {told}" if told else "")
        if rows is not None and info is not None:
            rows.append((to, gid, line)); info[gid] = data
        else:
            ladder_main_tell(to, [(gid, line)], {gid: data})
    print(f"ladder: {gid} {who} is live and silent after the look: " + (f"{to} told" if to else "no -main agent to tell"), file=sys.stderr, flush=True)
    return _ladder.MAIN


PROGRESS_UP = "progress_up_at"      # metadata: when the item was last handed up to its -main agent (either way in); the server's own key, no session writes it


def hand_up_others(gid: str, who: str, now: float, limit: int = 5) -> str:
    """What the item is queued behind, in words for the -main agent: the mover's other open items that are alive (not waiting, not the owner's move), by priority and then by age (the older id
    first), at most `limit` of them. "no other item of its mover" when there is none, "unknown" when the store cannot be read. Read only for an item that is being handed up."""
    try:
        rows: list[tuple[str, int, str]] = []
        for g, _p in _item_files():
            if g == gid:
                continue
            it = _load(g)
            if it.get("status") != "open" or _stall.not_due(it, now, lambda i_: _hooks().after_open(i_.get("metadata") or {})) or not _handoff.ho_same(_stallsvc.stall_mover(g, it), who):
                continue
            pr = str((it.get("metadata") or {}).get("priority") or "p2")
            rows.append((pr, int(g[1:]) if g[1:].isdigit() else 10 ** 9, g))
        if not rows:
            return "no other item of its mover"
        rows.sort()
        shown = ", ".join(f"{_gh.shown(g)} ({pr})" for pr, _n, g in rows[:limit])
        return shown + (f" and {len(rows) - limit} more" if len(rows) > limit else "")
    except Exception as e:  # noqa: BLE001  — the line is context for -main; an item is never held back for it
        print(f"ladder: {gid} queue not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return "unknown"


def ladder_stuck(gid: str, who: str, now: float, rows: "list[tuple[str, str, str]]", info: "dict[str, dict[str, str]]", alive_at: float = 0.0) -> str:
    """The second way into the ladder's hand-up (ladder.MAIN): an alive item whose mover has not moved it for `[ladder] main_hours` (4) goes to the project's -main agent, however much the mover has
    written meanwhile (a status line, a note and a reply are no progress: model/progress.py), in the same message as a silent live mover's item (`rows`, `info`, sent once per -main agent per pass by the
    tick). A History line on the item says it, and `metadata.progress_up_at` keeps the item from going up again until it has made progress and not moved for the interval again, or the interval
    has passed. Not taken ("" so it is tried again at the next tick) when the item is no longer open, alive and its mover's, or has moved or been handed up since the tick read it; taken with a History line
    alone when the project has no -main agent to tell. → "main" when the item was handed up (or the History line written), else ""."""
    hours = ladder_main_hours()
    behind = hand_up_others(gid, who, now)
    with _writes.ITEM_LOCK:
        item = _load(gid)
        meta = item.setdefault("metadata", {})
        if item.get("status") != "open" or not _handoff.ho_same(_stallsvc.stall_mover(gid, item), who) or _stall.not_due(item, now, lambda i_: _hooks().after_open(i_.get("metadata") or {})):
            return ""
        handed = float(meta.get(PROGRESS_UP) or 0)
        if not _progress.due(item, now, hours, handed, alive_at):
            return ""
        to = ladder_main_to(gid, who)
        last = max(_progress.at(item), alive_at)      # counted from when the item last became alive, if that is later (the notice says how long it has been alive and not moving)
        span = _hooks().silence_minutes(now - last)
        since = _hooks().when_words(dt.datetime.fromtimestamp(last, _hooks().zone()))
        told = _hooks().when_words(dt.datetime.fromtimestamp(handed, _hooks().zone())) if handed else ""
        data = {"kind": "progress", "subject": str(item.get("subject") or ""), "project": str(meta.get("project") or ""), "mover": _session_label(who), "since": since, "span": span, "told": told, "behind": behind}
        meta[PROGRESS_UP] = now
        _stall.note(meta, now, f"{_session_label(who)} has not moved it for {span} (no step done or dropped, no state change, no merge): " + (f"{_session_label(to)} was told to decide on a nudge or a different mover" if to else ladder_no_main(gid, who)))
        _writes.save(gid, item, note="ladder: " + (f"{_session_label(to)} told that it is not moving" if to else "it is not moving, " + ("its mover is the -main agent itself" if "is the project" in ladder_no_main(gid, who) else "no -main agent to tell")))
    if to:
        line = f"{_gh.shown(gid)} \"{data['subject']}\" ({data['project']}): mover {data['mover']}, no progress since {since} ({span}), queued behind {behind}" + (f", told before {told}" if told else "")
        rows.append((to, gid, line)); info[gid] = data
    print(f"ladder: {gid} {who} has not moved it for {span}: " + (f"{to} told" if to else "no -main agent to tell"), file=sys.stderr, flush=True)
    return _ladder.MAIN


def ladder_main_tell(to: str, items: "list[tuple[str, str]]", info: "dict[str, dict[str, str]]") -> None:
    """ONE notice to the -main agent `to` for the items (gid, line) of silent live background movers that came due together. It goes through the gate as a notice that asks a front agent to act (tag
    "stall", kind exempt), marked for the owner as every message a front agent takes is, and says how to stop the repeats. A lone item reads as a sentence about that item, several as a list."""
    gids = [g for g, _l in items]
    every = f"{ladder_main_hours():g} hours"
    stop = f"To stop the repeats, write to the item, hold it or set its wait; it comes again in {every} while the item stays silent. "
    if any(info[g].get("kind") == "progress" for g in gids):      # an item that is not moving (`ladder_stuck`) is in the notice: its wording, for the silent movers' items too
        stop_p = f"To stop the repeats, get the item moving (mark a step done or dropped, change its state, set its wait); it comes again in {every} while it does not move. "
        if len(items) == 1:
            d = info[gids[0]]
            again = f" {_session_label(to)} was told about this at {d['told']} and it has not moved since." if d["told"] else ""
            text = (f"{_FOR_OWNER}\n[stackshot] {_gh.shown(gids[0])} \"{d['subject']}\" has not moved for {d['span']} (since {d['since']}): its mover {d['mover']} has marked no step done or dropped, changed no state and merged nothing in that time; "
                    f"a status line, a note or a reply does not count. It is queued behind: {d['behind']}.{again} "
                    f"Decide whether it needs a nudge or a different mover: message {d['mover']}, or hand the item on (update mover=<session>). If you do nothing it stays with {d['mover']}. {stop_p}→ {_telling.notice_link(gids[0])}")
        else:
            head = (f"{_FOR_OWNER}\n[stackshot] {len(items)} items have not moved (no step done or dropped, no state change, no merge; a status line, a note or a reply does not count), "
                    "or have had no write from live background movers, and the ladder asks no one else:")
            tail = (f"\nDecide for each whether it needs a nudge or a different mover: message its mover, or hand the item on (update mover=<session>). If you do nothing each stays with its mover. "
                    f"To stop the repeats, get the item moving (mark a step done or dropped, change its state, set its wait) or write to it if it is silent; each comes again in {every} while it stays as it is. → {_inst.BOARD_URL}")
            text = head + "\n" + "\n".join("- " + l for _g, l in items) + tail
        _telling.tell_woken(",".join(gids), _hooks().session_id(to) or to, text, tag="stall")
        return
    if len(items) == 1:
        d = info[gids[0]]
        again = f" {_session_label(to)} was told about this at {d['told']} and nothing has been written since." if d["told"] else ""
        text = (f"{_FOR_OWNER}\n[stackshot] {_gh.shown(gids[0])} \"{d['subject']}\" has had no write from its background mover {d['mover']} since {d['since']} ({d['span']}), and that session is live, so the ladder asks no one else.{again} "
                f"Decide whether it needs a nudge or a different mover: message {d['mover']}, or hand the item on (update mover=<session>). If you do nothing it stays with {d['mover']}. {stop}→ {_telling.notice_link(gids[0])}")
    else:
        head = f"{_FOR_OWNER}\n[stackshot] {len(items)} items have had no write from their background movers, and those sessions are live, so the ladder asks no one else:"
        tail = (f"\nDecide for each whether it needs a nudge or a different mover: message its mover, or hand the item on (update mover=<session>). If you do nothing each stays with its mover. {stop}"
                f"→ {_inst.BOARD_URL}")
        text = head + "\n" + "\n".join("- " + l for _g, l in items) + tail
    _telling.tell_woken(",".join(gids), _hooks().session_id(to) or to, text, tag="stall")


def laddered(gid: str, who: str, now: float, at: float | None = None) -> bool:
    """Is the item on the one ladder for this mover and this hand-off (`at`: the record's) already (an entry the hand-off audit made, within its bounds)? Then the hand-off audit leaves it."""
    rec = _stallsvc.stall_load().get(gid)
    return bool(rec) and _handoff.ho_same(rec.get("mover"), who) and _ladder.on_ladder(rec, now, at)


def ladder_enter(item: dict[str, Any], st: "_ho.Step", now: float) -> dict[str, Any] | None:
    """The hand-off audit brings an item to the ladder: its entry is written to <state>/stall.json (a new episode, `via` = "handoff"). → the entry, or None when the item is not due (a wait, a hold, an
    `after` link: the stall pass's own `not_due`) or is on the ladder already for this mover. The first rung is taken by the caller, once the item lock is let go (`ladder_first`)."""
    who = st.frm
    if _stall.not_due(item, now, lambda i_: _hooks().after_open(i_.get("metadata") or {})):
        return None
    with _stallsvc.STALL_LOCK:
        cur = _stallsvc.stall_load()
        old = cur.get(st.gid)
        ver = _stallsvc.stall_ver(item)
        r_ = _ho.record_of(item)
        at = float((r_ or {}).get("at") or 0) if r_ and _handoff.ho_same(r_.get("to"), who) else 0.0
        if old and _handoff.ho_same(old.get("mover"), who) and _ladder.on_ladder(old, now, at) and list(old.get("ver") or []) == ver:
            return None
        rec = _ladder.enter(old, who, ver, _stallsvc.stall_confirm(item, who), gone=st.via == "gone", at=at)
        cur[st.gid] = rec
        _stallsvc.stall_save(cur)
    return rec


def ladder_ask(gid: str, who: str, now: float, act: str) -> str:
    """The ask (and the look) of an item the hand-off audit brought: the hand-off's own notice goes to the mover once more, as it was worded (a front agent gets the History line alone: no item notice wakes one)."""
    with _writes.ITEM_LOCK:
        item = _load(gid)
        r = _ho.record_of(item)
        if item.get("status") != "open" or not r or not _handoff.ho_same(_stallsvc.stall_mover(gid, item), who):
            return ""
        meta = item.setdefault("metadata", {})
        front = _telling.front_keeper(who, str(meta.get("project") or ""))[0]
        _stall.note(meta, now, f"{_session_label(who)} has not taken it" + (": no notice is sent to a front agent, the next rung follows" if front else ": the notice was sent to it again"))
        _writes.save(gid, item, note="ladder: " + ("no notice to a front agent" if front else "the notice was sent again"))
        text = "" if front else _handoff.handoff_text(gid, item, r)
    if text:
        _telling.tell_woken(gid, _hooks().session_id(who) or who, text, tag="handoff")
    print(f"ladder: {gid} {who} has not taken it: " + ("front agent, history line only" if front else "notice sent again"), file=sys.stderr, flush=True)
    return act


def ladder_do(act: str, gid: str, who: str, rec: dict[str, Any], now: float, minutes: float, lines: list[tuple[str, str, str]]) -> str:
    """Take one rung. → the rung taken ("" when it could not be taken now: it is tried again at the next tick)."""
    if act in ("ask", "look"):
        if _ladder.via_of(rec) == "handoff":
            return ladder_ask(gid, who, now, act)
        if _ladder.quiet(rec) or (act == "look" and _stallsvc.stall_background(who)):      # a background agent's look says what the item shows, never what its pane does
            return act if ladder_quiet_look(gid, who, now, minutes) else ""
        return act if _stallsvc.stall_resend(gid, who, now, minutes, lines) else ""
    if act == _ladder.MAIN:
        return ladder_main(gid, who, rec, now)
    if act == "cold":
        return _stallsvc.stall_cold(gid, who, now, minutes)
    return _stallsvc.stall_builder(gid, who, now, minutes)


def ladder_commit(gid: str, rec: dict[str, Any]) -> None:
    with _stallsvc.STALL_LOCK:
        cur = _stallsvc.stall_load()
        cur[gid] = rec
        _stallsvc.stall_save(cur)


def ladder_first(gid: str, who: str, rec: dict[str, Any], now: float) -> None:
    """The first rung of an item the hand-off audit just brought (its ask, or the cold call of a mover whose pane is gone). Never raises."""
    try:
        minutes = _stallsvc.stall_minutes()
        status, at = _handoff.handoff_status(who, _sessions_index())
        act = _ladder.action(rec, status, at, 0.0, now, minutes, ladder_look())
        if act == "cold" and not _handoff.cold_call_on():
            act = "builder"
        if not act:
            return
        did = ladder_do(act, gid, who, rec, now, minutes, [])
        if did:
            _ladder.advance(rec, did, now)
            ladder_commit(gid, rec)
    except Exception as e:  # noqa: BLE001
        print(f"ladder: {gid} first rung failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
