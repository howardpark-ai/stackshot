"""watching.py: the waits' watchers: a watched wait that ends turns its item, and the anchor notices that end an anchor wait.

An item that stores a wait kind (time, item, anchor, relay, event, or a list of them) is watched here and by nothing else: the wake pass and the close's release skip it (`watchers.watches`), so no item is moved by two
mechanisms. When its wait ends the item turns alive with its post-wake mover (the hold, the wake, `after` and the wait's fields go and the mover is told in one line), or, for a relay wait's ask-by day and for a wait chased
twice, it turns to the owner with a ready question. `watch_fire` is the one place an item turns; `watch_pass` is the clock's half (a date that came, an item that closed while nobody saw), `watch_item_closed` the close's
half, `watch_mark` and `watch_anchor_notice` the half an arrival (a line of a list, a notice) takes. The ids an anchor is compared by (`anchor_key`, `same_anchor`) and the test of a routine line (`auto_line`) live here
because the anchor wait and the anchor release both read them; `event_spec` is the event phrase as a wait stores it, which `watch_fire` matches an event against and the event waits read.

A switch in the model settings turns the watchers off (the items fall back to the wake pass and the close's release), and a pause setting holds them and the wake pass until it is lifted. Imports point down only:
this module imports the domain, core and the services beside it, never web/ and never audit/. What it still reaches in server.py comes through `Hooks` in service/wake_hooks.py."""
from __future__ import annotations

import datetime as dt
import sys
import time
from typing import Any, Callable

from stackshot.anchors import anchor_scope as _ascope
from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core.instance import OWNER
from stackshot.core.store import _item_files
from stackshot.fleet.sessions_registry import _session_label
from stackshot.github import ghsync as _gh
from stackshot.model import model as _model
from stackshot.model.bullet_text import _clip_line
from stackshot.model.needs import _after_of
from stackshot.router import routing as _routing
from stackshot.service import telling as _telling
from stackshot.service import writes as _writes
from stackshot.service.store import _legacy_hold, _load
from stackshot.service.wake_hooks import hooks as _hooks
from stackshot.waits import event_waits as _ew
from stackshot.waits import wait_list as _wl
from stackshot.waits import waiting as _wt
from stackshot.waits import watchers as _watch


_FOR_OWNER = f"[for {OWNER}]"      # the mark a message to a front agent carries on its first line ("[for <owner>]" on the owner's instance)


def anchor_key(url: str) -> str:
    """An anchor's URL or id → the id the anchor receiver keys it by (anchors.anchor_id, a #mention fragment left out); a shape it does
    not know stays as given."""
    u = str(url or "").strip()
    try:
        return _anc.anchor_id(_anc.split_fragment(u)[0]) or u
    except Exception:  # noqa: BLE001
        return u


def same_anchor(a: str, b: str) -> bool:
    return bool(a) and bool(b) and (a == b or anchor_key(a) == anchor_key(b))


def auto_line(n: dict[str, Any]) -> bool:
    """A routing line logged without delivery and ruled passed or merged by _routing.AUTO_RULER, not overruled since: the fleet's own
    routine PR event (the anchor receiver logs it, no recipient). A log-only direct anchor's line (the receiver's direct setting "none")
    carries no `log_only` mark and no ruling, so it never counts."""
    return bool(n.get("log_only")) and n.get("ruled_by") == _routing.AUTO_RULER and n.get("ruling") in ("passed", "merged")


# ----------------------------------------------------------------------------- the waits' watchers (watchers.py)
# A waiting item that stores a wait_kind (time | item | anchor | relay | event) is watched here, and by nothing else: today's wake pass and `after` release skip it
# (watchers.watches), so no item is moved by two mechanisms. When its wait ends it turns alive with its post-wake mover (the hold, the wake, `after` and the wait's fields go, the mover
# is told in one line), or, for a relay wait's ask-by day and for a wait chased twice, it turns to the owner with a ready question. [model] watchers = false turns all of this off
# (the items fall back to today's machinery), [model] pause = true holds it (the wake pass too) until it is false again.

def watch_label(who: str) -> str:
    return OWNER if _model.is_owner(who) else (_session_label(who) or who)


def watch_ask(gid: str, meta: dict[str, Any], what: str) -> tuple[str, list[dict[str, Any]]]:
    """The question the owner gets when HE is the post-wake mover of a time, item or anchor wait: the ask and options the item already carries when they are valid, else one in the
    ask's shape with two buttons (take it up, drop it)."""
    ask, opts = str(meta.get("ask") or ""), _hooks().rmod_options_of({"metadata": meta}, raw=True)
    if _hooks().rmod_parse_ask(ask) is not None and opts:
        return ask, opts
    ask = (f"Decide: what to do with {_gh.shown(gid)}, whose wait ended · Recommend: Take it up · Stakes: {_clip_line(what, 90)} · By: no date")
    if _hooks().rmod_parse_ask(ask) is None:
        ask = f"Decide: what to do with {_gh.shown(gid)}, whose wait ended · Recommend: Take it up · Stakes: it was waiting · By: no date"
    return ask, [{"label": "Take it up", "line": "The item's mover picks it up now; the sessions named in its needs are told with it.", "recommended": True},
                 {"label": "Drop it", "line": "It is no longer wanted: its mover closes it as not planned.", "recommended": False}]


WATCH_BACKOFF: dict[str, float] = {}        # gid → the epoch before which the watchers leave it alone (a failed turn); in memory, so a save that fails too cannot make the loop run hot


class _WatchStuck(RuntimeError):
    """A due wait that cannot turn (the pass backs the item off, watch_failed)."""


def watch_failed(gid: str, now: float) -> None:
    """The turn of a due wait failed: the item is left alone for watchers.BACKOFF seconds, kept in memory first (WATCH_BACKOFF) and then noted on the item (a filing save, no clock moves; the note
    survives a restart), so the runner does not spin on it even when the save fails too."""
    WATCH_BACKOFF[gid] = now + _watch.BACKOFF
    for g in [g for g, t in WATCH_BACKOFF.items() if t < now - _watch.BACKOFF]:      # the dict stays small
        WATCH_BACKOFF.pop(g, None)
    try:
        with _writes.ITEM_LOCK:
            it = _load(gid)
            m = dict(it.get("metadata") or {})
            w = dict(m.get("watch") or {}) if isinstance(m.get("watch"), dict) else {}
            w["failed_at"] = now
            m["watch"] = w
            it["metadata"] = m
            _writes.save(gid, it)
    except Exception as e:  # noqa: BLE001
        print(f"watch: {gid} failure not recorded: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


def watch_fire(gid: str, cause: str, now: float, out: dict[str, list[tuple[str, dict[str, Any], str]]], detail: dict[str, str] | None = None, recheck: bool = False, ev: dict[str, Any] | None = None,
                legacy: bool = False) -> bool:
    """The wait of `gid` is over (`cause`: time | item | backstop | relay | anchor | event): turn the item, save it, and collect the message its new mover is owed in `out` (recipient
    session id → [(gid, item, what arrived)]; the caller sends one message per recipient). Under the item lock, re-read: an item that is no longer watched, or no longer waits on this,
    is left alone. `recheck` (the clock's pass): the cause is read again under the lock and the item turns only if it is still due. → True when it turned; _WatchStuck when the wait is due and cannot turn.
    `detail["what"]` replaces the words of the arrival (the caller knows what closed or arrived). `legacy` (the wake pass, with the watchers off): a wait on a list that holds is ended at its
    backstop day all the same, by this one path, so its words, its mover and the question for an open relay line are the watchers' (nothing else of the watchers runs: no line is marked)."""
    detail = detail or {}
    with _writes.ITEM_LOCK:
        it = _load(gid)
        if not (_watch.watches(it) or (legacy and it.get("status") == "open" and _wl.valid(it.get("metadata") or {}))):
            return False
        if recheck and _watch.due(it, now, _hooks().after_open(it.get("metadata") or {})) != cause:
            return False
        if ev is not None and cause == "event":          # the event is matched again against the wait as it stands under the lock: an update that landed since the caller read the item is respected
            try:
                if _watch.stored_kind(it.get("metadata") or {}) != "event" or not _ew.matches(event_spec((it.get("metadata") or {}).get("wait_event")), ev):
                    return False
            except _ew.EventWaitError:
                return False
            if ev.get("kind") in _ew.REPORTED and now <= watch_floor(it):
                return False
        meta = dict(it.get("metadata") or {})
        kind = _watch.stored_kind(meta)
        mod = _hooks().model_of({**it, "gid": gid})
        if mod.state != _model.WAITING or mod.wait is None:
            raise _WatchStuck(f"{gid} reads as {mod.state}, not as a wait")
        post = mod.wait.mover or _telling.auto_mover(_telling.fallback_mover(str(meta.get("project") or "")), str(meta.get("project") or ""))      # a fallback is never a front agent when the project has a builder
        until = _watch.backstop_epoch(meta)
        date = (dt.datetime.fromtimestamp(until, _hooks().zone()).strftime("%Y-%m-%d") if until else "")
        url = str(meta.get("wait_anchor") or "")
        if kind == _wl.LIST:                            # what arrived and what did not, from the record the wait's fields carry (read before they are dropped below)
            what = _watch.what_list(meta, cause, _gh.shown)
        elif cause == "time":
            what = detail.get("what") or (_watch.what_until(_wt.stored_until(meta)) if _wt.stored_until(meta) else _watch.what_time(str(meta.get("wake"))) if meta.get("wake") else f"its end date {meta.get('end')} came")
        elif cause == "item":
            what = detail.get("what") or f"every item it waited on has closed ({', '.join(_gh.shown(g) for g in _after_of(meta))})"
        elif cause == "anchor":
            what = detail.get("what") or _watch.what_anchor(url, "", "arrived")
        elif cause == "event":
            what = detail.get("what") or _watch.what_event(_ew.event(_ew.parse(meta.get("wait_event")).kind))
        elif cause == "backstop" and kind == "event":
            what = _watch.what_event_silent(meta.get("wait_event"), date)
        elif cause == "backstop" and kind == "anchor":
            what = _watch.what_anchor_silent(url, date)
        elif cause == "backstop":
            what = _watch.what_item_backstop(date, [_gh.shown(g) for g in _hooks().after_open(meta)])
        else:
            what = f"its ask-by day {_watch.relay_day(meta)} came"
        chased = _watch.chased_out(meta)
        list_relay = kind == _wl.LIST and cause == "backstop" and bool(_wl.lines_by_kind(meta, "relay"))      # the backstop day with a relay line still open asks the owner, as a relay's ask-by day does
        ask_him = (cause == "relay" and kind != _wl.LIST) or (cause == "backstop" and chased) or list_relay      # a relay LINE that arrived (the owner relayed it) is an arrival, not a question
        if ask_him:
            asked = "dropit" if chased else "relay"
            ask = _watch.drop_ask(meta) if chased else _watch.relay_ask(meta)
            opts = _watch.drop_options() if chased else _watch.relay_options()
            _watch.remember(meta, asked, now)
            _watch.turn_to_owner(meta, mod.then if _model.is_owner(post) else post, ask, opts, what if (chased or kind == _wl.LIST) else f"{_watch.subject_of(meta)} is due: its ask-by day {_watch.relay_day(meta)} came", now)
            mover = OWNER
        elif _model.is_owner(post):
            ask, opts = watch_ask(gid, meta, what)
            _watch.turn_to_owner(meta, mod.then, ask, opts, what, now)      # he picks it up: the `then` that stands beside him survives the wake
            mover = OWNER
        elif cause == "time" and not str(meta.get("wait_kind") or "").strip() and not mod.wait.mover_explicit:
            _watch.end_date(meta, what, post, now)       # a wait on the date alone ends with the date: needs, the open after link and the mover stay as stored
            mover = post
        else:
            _watch.turn_alive(meta, post, what, now)
            mover = post
        _hooks().state_end(meta)                                # a stored state of the old wait is over with it: the item reads from its fields
        if "confirmed" not in it:                       # as the wake pass: `confirmed` stays, so the item reads stale until its mover refreshes it
            it["confirmed"] = _hooks().rmod_confirmed_at(it)
        it["metadata"] = meta
        it["updated"] = it["state_updated"] = now
        _writes.save(gid, it, note=(f"woke: {what} → {watch_label(mover)}" if mover != OWNER else f"the wait ended: {what}; asks {OWNER}: {meta.get('ask')}"))
        print(f"watch: {gid} {kind} wait over ({cause}) → {mover} — {it.get('subject')}", file=sys.stderr, flush=True)
        if mover != OWNER:
            out.setdefault(_hooks().session_id(mover), []).append((gid, it, what))
        return True


def watch_text(sid: str, rows: list[tuple[str, dict[str, Any], str]]) -> tuple[str, str, list[str]] | None:
    """The message to one session about the items whose wait ended and are now its move: (the text, the mark a front agent takes or "", the item ids), None for no rows."""
    if not rows:
        return None
    msg_rows = [(_gh.shown(g), what, f"{it.get('subject') or ''} ({(it.get('metadata') or {}).get('project') or 'no project'})", _telling.notice_link(g)) for g, it, what in rows]
    project = str((rows[0][1].get("metadata") or {}).get("project") or "")
    return _watch.message(msg_rows), (_FOR_OWNER if _telling.front_keeper(sid, project)[0] else ""), [g for g, *_ in rows]


def watch_tell(sid: str, rows: list[tuple[str, dict[str, Any], str]]) -> None:
    """One message to one session about every item whose wait ended and is now its move (several items for one recipient in one pass are one message, a single one a single line).
    A front agent gets the mark a front agent takes. A delivery that fails is recorded on the items (tell_woken)."""
    if not sid:
        print(f"watch: {', '.join(g for g, *_ in rows)} woke with nobody to tell", file=sys.stderr, flush=True)
        return
    x = watch_text(sid, rows)
    if x:
        _telling.tell_woken(",".join(x[2]), sid, (x[1] + " " if x[1] else "") + x[0], tag="watch")


def watch_pass(now: float | None = None, wout: dict[str, list[tuple[str, dict[str, Any], str]]] | None = None) -> list[str]:
    """The scheduler's half of the watchers: every watched wait the clock has ended (a time wait's wake, a relay's ask-by day, an item or anchor wait's backstop, and an item wait whose
    `after` items all closed while nobody saw the close) turns, one message per recipient. Nothing while paused or switched off. Run by the wake pass (so by the runner's watchers' tick and its ten-minute catch-up, at start
    and at the end of a migration pass). `wout` = where the messages are collected for the caller to send (the wake pass merges them with its own, one message per recipient); without it they go out here.
    An item whose turn fails is noted and left alone for a while (watch_failed), so a wait that cannot turn never keeps the loop busy. → the gids that turned."""
    if not _watch.enabled() or _watch.paused():
        return []
    now = time.time() if now is None else now
    out: dict[str, list[tuple[str, dict[str, Any], str]]] = {} if wout is None else wout
    moved: list[str] = []
    for gid, _p in _item_files():
        try:
            if WATCH_BACKOFF.get(gid, 0.0) > now:
                continue
            it = _load(gid)
            if not _watch.watches(it):
                continue
            meta = it.get("metadata") or {}
            if _wl.valid(meta):                       # a wait on a list: the lines the clock ends (a date that came, an item that closed unseen) are marked first, then the group is judged
                if _watch_list_clock(gid, now, out):
                    moved.append(gid)
                    WATCH_BACKOFF.pop(gid, None)
                continue
            cause = _watch.due(it, now, _hooks().after_open(meta))
            if cause and watch_fire(gid, cause, now, out, recheck=True):
                moved.append(gid)
                WATCH_BACKOFF.pop(gid, None)
        except Exception as e:  # noqa: BLE001  — one bad item never stops the pass
            print(f"watch: {gid} skipped this pass: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
            watch_failed(gid, now)
    if wout is None:
        for sid, rows in out.items():
            watch_tell(sid, rows)
    return moved


def watch_item_closed(g: str, it: dict[str, Any], closed: str, outcome: str, rep: str, writer: str, wout: dict[str, list[tuple[str, dict[str, Any], str]]], superseded_by: str = "") -> bool:
    """`closed` just closed and the watched item `g` waits after it (_wakes.release_after). A superseded one is followed to its open replacement (the item then waits on that); the closed ones stay
    in `after` as the record of what it waited on. When no `after` item is open any more the wait is over: the item turns (a message is collected in `wout`). While paused it stays as it is
    and the next pass after the pause finds every `after` item closed. A watched wait of another kind keeps its `after` as it was. → True when it turned."""
    with _writes.ITEM_LOCK:
        it = _load(g)
        meta = dict(it.get("metadata") or {})
        if _wl.valid(meta):
            return _watch_list_item_closed(g, closed, outcome, rep, writer, wout, superseded_by)
        if _watch.stored_kind(meta) != "item":
            return False
        after = _after_of(meta)
        if rep and rep not in after and rep != g:
            meta["after"] = [rep if x == closed else x for x in after]
            it["metadata"] = meta; it["updated"] = time.time()
            _writes.save(g, it, note=f"{_gh.ref(closed)} was superseded, followed to {_gh.ref(rep)}")
        left = _hooks().after_open(meta)
        if left:
            print(f"after: {g} (watched) still waits on {', '.join(left)} ({closed} closed as {outcome})", file=sys.stderr, flush=True)
            return False
        if _watch.paused() or not _watch.enabled():
            return False
        how = ("was dropped" if outcome == "dropped" else f"was superseded by {_gh.shown(rep or superseded_by)}, which is closed too" if outcome == "superseded" else "closed (done)") + (f" by {_session_label(writer)}" if writer else "")
        try:
            return watch_fire(g, "item", time.time(), wout, {"what": _watch.what_item(_gh.shown(closed), how)})
        except _WatchStuck as e:
            print(f"watch: {e}", file=sys.stderr, flush=True)
            watch_failed(g, time.time())
            return False


def _wl_mark_save(gid: str, it: dict[str, Any], meta: dict[str, Any], marks: list[tuple[int, str]], now: float, notes: list[str] | None = None) -> bool:
    """Mark the lines of a wait on a list that arrived (`marks` = [(line index, the words of its arrival)]) on `meta` and save the item, under the item lock the caller holds: a filing save of the item's own
    clock (the state clock and the confirm stay: the item is still waiting), with a History line `arrived: <what> (<k> of <n>)` for each line marked and `notes` (a followed replacement) before them.
    Idempotent: a line that has arrived is left as it was and costs no write. → True when something was written."""
    said = list(notes or [])
    floor = watch_floor(it)                      # the oldest notice an anchor line may still count, read before this save moves the item's clock
    for i, what in marks:
        if _wl.mark_arrived(meta, i, what, now):
            said.append(f"arrived: {_clip_line(what, _wl.LINE_MAX)} ({len(_wl.arrived_lines(meta))} of {len(_wl.lines(meta))})")      # the words are free text (a notice's, an event's): the History keeps a line's worth
    if not said:
        return False
    w = dict(meta.get("watch") or {}) if isinstance(meta.get("watch"), dict) else {}
    if not w.get("set_at") and floor:             # an unstamped list stamps its floor first: the save below moves `updated`, and a second notice dated between the old floor and this save would be dropped
        w["set_at"] = floor
        meta["watch"] = w
    it["metadata"] = meta
    it["updated"] = now
    _writes.save(gid, it, note="; ".join(said))
    print(f"watch: {gid} list: {'; '.join(said)}", file=sys.stderr, flush=True)
    return True


def watch_mark(gid: str, cause: str, now: float, out: dict[str, list[tuple[str, dict[str, Any], str]]], pick: Callable[[dict[str, Any]], list[int]], what: str, ev: dict[str, Any] | None = None) -> bool:
    """A line of the wait on a list that `gid` stands in arrived (`cause`: the kind of that line: time | item | anchor | relay | event): mark the lines `pick` finds in the list as it stands UNDER THE ITEM LOCK
    (so an arrival delivered twice, or one another path has just recorded, marks nothing and changes nothing) and save the item; when the group is then over (`any`: this arrival; `all`: every line has arrived)
    turn the item (watch_fire, which reads the item again under the same lock), else it stays waiting and nothing is sent. `ev`: a reported event (recycle, fleet op, job run) counts only when it is newer
    than the wait, as for a single event wait. Nothing while paused or switched off: the clock's pass finds the arrival then. → True when the item turned."""
    if not _watch.enabled() or _watch.paused():
        return False
    with _writes.ITEM_LOCK:
        it = _load(gid)
        if not _watch.watches(it) or _watch.stored_kind(it.get("metadata") or {}) != _wl.LIST:
            return False
        if ev is not None and ev.get("kind") in _ew.REPORTED and now <= watch_floor(it):
            return False
        meta = dict(it.get("metadata") or {})
        if not _wl_mark_save(gid, it, meta, [(i, what) for i in pick(meta)], now):
            return False
        if not _wl.done(meta):
            return False
        try:
            return watch_fire(gid, cause, now, out, recheck=True)
        except _WatchStuck as e:
            print(f"watch: {e}", file=sys.stderr, flush=True)
            watch_failed(gid, now)
            return False


def _wl_item_closed(meta: dict[str, Any], closed: str, outcome: str, rep: str, writer: str, g: str, superseded_by: str = "") -> tuple[list[tuple[int, str]], list[str]]:
    """The lines of a wait on a list that wait on `closed`, which just closed (or is found closed): a superseded one is followed to its open replacement `rep` (the id in the line becomes the replacement's and the
    line has not arrived: the list waits on that now), any other closing marks the line. Done on `meta` in place; → ([(index, words) of the lines to mark], History notes of the lines followed)."""
    marks: list[tuple[int, str]] = []
    notes: list[str] = []
    how = ("was dropped" if outcome == "dropped" else f"was superseded by {_gh.shown(rep or superseded_by)}, which is closed too" if outcome == "superseded" else "closed (done)") + (f" by {_session_label(writer)}" if writer else "")
    for i in _wl.lines_for_item(meta, closed):
        if rep and rep != g:
            raw = [dict(r) for r in meta["waits"]]
            raw[i]["after"] = rep
            meta["waits"] = raw
            notes.append(f"{_gh.ref(closed)} was superseded, followed to {_gh.ref(rep)}")
        else:
            marks.append((i, f"{_gh.shown(closed)} {how}"))
    return marks, notes


def _watch_list_item_closed(g: str, closed: str, outcome: str, rep: str, writer: str, wout: dict[str, list[tuple[str, dict[str, Any], str]]], superseded_by: str = "") -> bool:
    """`closed` just closed and the item `g`, which waits on a list, has an item line on it (_wakes.release_after, under the item lock): a superseded one is followed to its open replacement (the id in the line is
    replaced), any other close marks every line that waits on it (two lines on one item are both marked) and the group is judged (watch_mark). While paused the follow is made and the marks wait: the clock's
    pass finds a closed item. → True when the item turned."""
    now = time.time()
    with _writes.ITEM_LOCK:
        it = _load(g)
        meta = dict(it.get("metadata") or {})
        marks, notes = _wl_item_closed(meta, closed, outcome, rep, writer, g, superseded_by)
        if notes:
            _wl_mark_save(g, it, meta, [], now, notes)
        if not marks:
            return False
        return watch_mark(g, "item", now, wout, lambda m: [i for i, _w in marks if i in _wl.lines_for_item(m, closed)], marks[0][1])


def _watch_list_clock(gid: str, now: float, out: dict[str, list[tuple[str, dict[str, Any], str]]]) -> bool:
    """The clock's half of a wait on a list (watch_pass): a time line whose date has come arrives, and an item line whose item closed while nobody saw (a missing item file counts as closed, as for an item
    wait) arrives, a superseded item being followed to its open replacement first; then the group is judged: over by what has arrived (the cause is the kind of the line that completed it), or the backstop
    day has come (cause backstop, whatever has arrived). → True when the item turned."""
    with _writes.ITEM_LOCK:
        it = _load(gid)
        if not _watch.watches(it):
            return False
        meta = dict(it.get("metadata") or {})
        if not _wl.valid(meta):
            return False
        marks = [(i, f"its date {_wl.lines(meta)[i]['until']} came") for i in _wl.lines_for_time(meta, now)]
        notes: list[str] = []
        for i in _wl.lines_by_kind(meta, "item"):
            after = _wl.lines(meta)[i]["after"]
            if after not in _hooks().after_open({"after": [after]}):        # closed, or no file: closed as the wait treats it
                c = (_hooks().load_or_none(after) or {}).get("metadata") or {}
                outcome = str(c.get("outcome") or "done")
                rp = _hooks().follow_superseded(str(c.get("superseded_by") or "")) if outcome == "superseded" and c.get("superseded_by") else ""
                m_, n_ = _wl_item_closed(meta, after, outcome, rp if rp and (_hooks().load_or_none(rp) or {}).get("status") == "open" else "", "", gid, str(c.get("superseded_by") or ""))
                marks += m_
                notes += n_
        _wl_mark_save(gid, it, meta, marks, now, notes)
        it = _load(gid)
        cause = _watch.due(it, now, _hooks().after_open(it.get("metadata") or {}))
        if not cause:
            return False
        try:
            return watch_fire(gid, cause, now, out, recheck=True)
        except _WatchStuck as e:
            print(f"watch: {e}", file=sys.stderr, flush=True)
            watch_failed(gid, now)
            return False


def watch_anchor_notice(project: str, url: str, n: dict[str, Any], at: float, how: str) -> list[str]:
    """A notice for `url` reached the server (_wakes.anchor_release: the keeper passed or merged it, or nobody rules the project, or it is the fleet's own routine line): every open item of the project
    whose stored wait is an anchor event on that anchor turns, with the notice's gist on it. Only a notice newer than the item's last move and than its wait counts; the router keeps ruling
    the notice as before, and the post-wake mover judges a false hit. A routine line of the fleet's own PR (a push, CI passing) does not end a wait for a merge or a close. → the gids turned."""
    if not _watch.enabled() or _watch.paused():
        return []
    out: dict[str, list[tuple[str, dict[str, Any], str]]] = {}
    fired: list[str] = []
    try:
        held_by = _ascope.holders(_anc.load(), url, same_anchor)      # the notice is the page's that holds the anchor; an item of another project may wait on it
    except Exception:  # noqa: BLE001
        held_by = []
    for gid, _p in _item_files():
        try:
            it = _load(gid)
            m = it.get("metadata") or {}
            if _watch.watches(it) and _watch.stored_kind(m) == _wl.LIST:          # a wait on a list: every open anchor line on this anchor that the notice answers is marked (a notice that does not answer the line's event, as for a single wait, is not its arrival)
                if not _wl.lines_for_anchor(m, url, same_anchor) or (str(m.get("project") or "") != project and project not in held_by) or at <= watch_floor(it):
                    continue
                answers = lambda meta: [i for i in _wl.lines_for_anchor(meta, url, same_anchor) if _watch.anchor_hit(_wl.lines(meta)[i]["event"], n.get("text"), auto_line(n))]
                if answers(m) and watch_mark(gid, "anchor", time.time(), out, answers, _watch.what_anchor(url, str(n.get("text") or ""), how)):
                    fired.append(gid)
                    print(f"anchor wait: {gid} turned ({project}, notice {n.get('id')})", file=sys.stderr, flush=True)
                continue
            if not _watch.watches(it) or _watch.stored_kind(m) != "anchor" or not same_anchor(str(m.get("wait_anchor") or ""), url):
                continue
            if str(m.get("project") or "") != project and project not in held_by:
                continue
            if at <= watch_floor(it) or not _watch.anchor_hit(m.get("wait_event"), n.get("text"), auto_line(n)):
                continue
            if watch_fire(gid, "anchor", time.time(), out, {"what": _watch.what_anchor(str(m.get("wait_anchor") or url), str(n.get("text") or ""), how)}):
                fired.append(gid)
                print(f"anchor wait: {gid} turned ({project}, notice {n.get('id')})", file=sys.stderr, flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"watch: {gid} not read for a notice: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    for sid, rows in out.items():
        watch_tell(sid, rows)
    return fired


def watch_floor(it: dict[str, Any]) -> float:
    """The oldest notice an anchor wait may count: after the item's last move and after its wait was set (`watch.set_at`; a wait stored before the stamp existed reads its last write)."""
    w = (it.get("metadata") or {}).get("watch")
    try:
        set_at = float(w.get("set_at") or 0) if isinstance(w, dict) else 0.0
    except (TypeError, ValueError):
        set_at = 0.0
    return max(float(it.get("state_updated") or 0), set_at or float(it.get("updated") or 0))


def watch_stamp(gid: str) -> None:
    """Give an anchor wait that has no `watch.set_at` one, now (a filing save: no clock moves): the minute pass does it on first sight, so a wait stored before this deploy is not woken by a
    notice from the days it already waited through."""
    with _writes.ITEM_LOCK:
        it = _load(gid)
        m = dict(it.get("metadata") or {})
        w = dict(m.get("watch") or {}) if isinstance(m.get("watch"), dict) else {}
        if w.get("set_at") or it.get("status") != "open":
            return
        w["set_at"] = time.time()
        m["watch"] = w
        it["metadata"] = m
        _writes.save(gid, it)


def event_spec(phrase: Any) -> "_ew.Spec":
    """A stored or passed event phrase → its Spec with the pull request's repository filled in and run through [github.moved]; EventWaitError when it is no event."""
    return _ew.resolved(_ew.parse(phrase), _hooks().own_repo(), _cfg.canon_repo)
