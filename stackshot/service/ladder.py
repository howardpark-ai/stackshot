"""ladder.py: the one ladder of the stall pass and the hand-off audit.

With `[ladder] enabled = true` an item whose mover went quiet has ONE record, its entry in <state>/stall.json (`via` says which audit brought it: "handoff" for an untaken hand-off, "stall" for a pane with no turn
running), and one order: ask the mover, look at its pane `[ladder] look_minutes` (30) later, the cold call, the project's builder, then the fleet's builder asked once. The hand-off tick brings an untaken hand-off
to it (`ladder_enter`); the stall tick brings a silent pane and takes every rung after the first of both. With it off (the default) both passes run as they did, each on its own record. The pure rules (which rung
is due, what ends an entry) are waits/ladder.py.

This module holds the switches and the settings of the ladder, the entry the dates pass makes (`ladder_enter_quiet`) and the one the hand-off audit makes (`ladder_enter`), the rungs that are the ladder's own (the
ask, the look, and the hand-up of a silent live background mover's item to the project's -main agent), and `ladder_do`, which takes one rung (the steps it shares with the stall pass are in service/stall.py).
The pass that walks the items is service/stall_tick.py.

What it still reaches in server.py comes through `Hooks` in service/stall_hooks.py, looked up when it runs, so a suite that replaces one on its owner module is the one called. A suite that replaces a function of this
module sets it here.

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import datetime as dt
import sys
from typing import Any

from stackshot.core import config as _cfg
from stackshot.core import instance as _inst
from stackshot.core.instance import OWNER
from stackshot.fleet.sessions_registry import _session_label, _sessions_index
from stackshot.github import ghsync as _gh
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


def ladder_no_main(gid: str, who: str) -> tuple[bool, str]:
    """Why nobody is told when `ladder_main_to` is empty → (itself, why): `itself` is True when the mover is itself the project's -main agent (nobody above it to tell), False when the project has none;
    `why` is the same thing in words for the History line. Callers branch on `itself`, never on the words."""
    try:
        main = _hooks().main_agent(str((_load(gid).get("metadata") or {}).get("project") or ""))
    except Exception:  # noqa: BLE001
        main = ""
    itself = bool(main) and _hooks().session_id(main) == _hooks().session_id(who)
    return itself, ("its mover is the project's -main agent, so there is no one above it to tell" if itself else "the project has no -main agent to tell")


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
        itself, why = (False, "") if to else ladder_no_main(gid, who)      # nobody to tell: the mover is the -main agent itself, or the project has none
        span = _hooks().silence_minutes(now - last) if last > 0 else "a long time"
        since = _hooks().when_words(dt.datetime.fromtimestamp(last, _hooks().zone())) if last > 0 else "it was handed over"
        before = float(rec.get("main_at") or 0)      # when -main was told about this silence last, if it was
        told = _hooks().when_words(dt.datetime.fromtimestamp(before, _hooks().zone())) if before else ""
        data = {"subject": str(item.get("subject") or ""), "project": str(meta.get("project") or ""), "mover": _session_label(who), "since": since, "span": span, "told": told}
        _stall.note(meta, now, f"{_session_label(who)} is live but wrote nothing to it for {span}: " + (f"{_session_label(to)} was told to decide on a nudge or a different mover" if to else why))
        _writes.save(gid, item, note="ladder: " + (f"{_session_label(to)} told that its mover is silent" if to else "its mover is silent, " + ("it is the -main agent itself" if itself else "no -main agent to tell")))
    if to:
        line = f"{_gh.shown(gid)} \"{data['subject']}\" ({data['project']}): mover {data['mover']}, no write since {since} ({span})" + (f", told before {told}" if told else "")
        if rows is not None and info is not None:
            rows.append((to, gid, line)); info[gid] = data
        else:
            ladder_main_tell(to, [(gid, line)], {gid: data})
    print(f"ladder: {gid} {who} is live and silent after the look: " + (f"{to} told" if to else "it is the -main agent itself, so no one above it is told" if itself else "no -main agent to tell"), file=sys.stderr, flush=True)
    return _ladder.MAIN


def ladder_main_tell(to: str, items: "list[tuple[str, str]]", info: "dict[str, dict[str, str]]") -> None:
    """ONE notice to the -main agent `to` for the items (gid, line) of silent live background movers that came due together. It goes through the gate as a notice that asks a front agent to act (tag
    "stall", kind exempt), marked for the owner as every message a front agent takes is, and says how to stop the repeats. A lone item reads as a sentence about that item, several as a list."""
    gids = [g for g, _l in items]
    every = f"{_ladder.MAIN_EVERY / 3600.0:g} hours"
    stop = f"To stop the repeats, write to the item, hold it or set its wait; it comes again in {every} while the item stays silent. "
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
