"""wakes.py: the wake pass and the anchor pass, the release of the items that wait on a closed item or on an anchor, and the tick bodies the minute set runs for them.

An open item comes back on its own in four ways: a held item whose wake has come, a backstop day set beside a live item, an item that waited on another item that has since closed, and a held item whose anchor has been
ruled or has arrived. This module holds those passes and what they tell. `wake_pass` is the one pass: the watchers' own clock first (`watching.watch_pass`), then every item with a plain wake or hold, one message per
session for the whole pass (`wake_tell`). `release_after` is the close's half (the items that waited on the closed one wake, or follow its replacement). `anchor_release` and `anchor_pass` are the anchors' half (a ruling or
a routine line releases a hold scoped to the anchor, and the notice is replayed for the stored anchor waits). The four tick bodies at the end (`minute_wake_pass`, `minute_wake_catchup`, `minute_anchor_pass` and
`minute_wake_wait`) are what the table in service/runner.py calls.

The pass writes through service/writes.py and tells through service/telling.py: the domain decides, the service writes. What the passes still reach in server.py (the item model's shared readers, the proof readers, the
renderer's answers, the publish and the time zone) comes through `Hooks` in service/wake_hooks.py, looked up when it runs, so a suite that replaces one on its owner module is the one called. A suite that replaces a
function of the passes sets it on this module, or on service/watching.py and service/event_waits.py, which hold the watchers and the event waits.

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
from typing import Any, Callable

from fastmcp.exceptions import ToolError

from stackshot.anchors import anchor_scope as _ascope
from stackshot.anchors import anchors as _anc
from stackshot.core import call_log as _calls
from stackshot.core import config as _cfg
from stackshot.core.store import _item_files
from stackshot.fleet.sessions_registry import _session_label
from stackshot.github import ghsync as _gh
from stackshot.model import item_project as _ip
from stackshot.model.needs import _after_of
from stackshot.projects import pages as _pages
from stackshot.router import router_live as _router_live
from stackshot.router import routing as _routing
from stackshot.service import telling as _telling
from stackshot.service import watching as _watching
from stackshot.service import writes as _writes
from stackshot.service.store import _legacy_hold, _load
from stackshot.service.wake_hooks import hooks as _hooks
from stackshot.waits import until_write as _uw
from stackshot.waits import wait_list as _wl
from stackshot.waits import waiting as _wt
from stackshot.waits import watchers as _watch


_WAKE_RE = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})(?:[T ]([0-9]{2}:[0-9]{2}))?")
_WAKE_LOCK = threading.Lock()       # one wake pass at a time (the runner's watchers' tick and its ten-minute catch-up, the start's pass, the migration pass's end)


def wake_at(value: Any) -> dt.datetime:
    """A stored wake as the moment it falls due, in the instance timezone (the zone _pages.zone_now() reads): YYYY-MM-DD is
    the start of that day, YYYY-MM-DDTHH:MM that minute. ValueError on
    anything else (a hand edit the gate would have refused)."""
    m = _WAKE_RE.fullmatch(str(value).strip())
    if not m:
        raise ValueError(f"not a wake: {value!r}")
    at = dt.datetime.strptime(m[1] + "T" + (m[2] or "00:00"), "%Y-%m-%dT%H:%M")
    return at.replace(tzinfo=_pages.zone_now().tzinfo)


_WAKE_ISO_RE = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})[T ]([0-9]{2}:[0-9]{2})(?::([0-9]{2})(?:[.,][0-9]+)?)?(Z|[+-][0-9]{2}(?::?[0-9]{2})?)?", re.I)


def _wake_iso(text: str) -> str:
    """A full ISO 8601 time (seconds, a fraction, `Z` or a UTC offset, any of them) → the minute it falls on in the instance timezone, as YYYY-MM-DDTHH:MM; "" for anything else, and for
    a time that is already in the plain form (nothing to correct). Seconds are dropped, not rounded; a time with no offset is read as the instance's own. (The stored wake is a wall-clock minute with no
    offset, so a converted time in the hour a DST fall-back repeats is stored as that minute and later read as the hour's first pass.)"""
    m = _WAKE_ISO_RE.fullmatch(text.strip())
    if not m or (m[3] is None and m[4] is None):
        return ""
    try:
        at = dt.datetime.strptime(m[1] + "T" + m[2], "%Y-%m-%dT%H:%M")
        if m[4]:
            off = m[4].upper()
            if off == "Z":
                delta = dt.timedelta(0)
            else:
                digits = off[1:].replace(":", "")
                hours, minutes = int(digits[:2]), int(digits[2:4] or 0)
                if hours > 23 or minutes > 59:
                    return ""
                delta = dt.timedelta(hours=hours, minutes=minutes) * (-1 if off[0] == "-" else 1)
            at = at.replace(tzinfo=dt.timezone(delta)).astimezone(_pages.zone_now().tzinfo)
        return at.strftime("%Y-%m-%dT%H:%M")
    except ValueError:
        return ""


def parse_wake(text: str) -> str:
    """A wake as given (YYYY-MM-DD, or YYYY-MM-DDTHH:MM with a space allowed for the T) → its stored form, the T form for a time of day; ToolError naming the two forms otherwise. A full ISO
    time (seconds, a fraction, Z or a UTC offset) is read as the minute it falls on in the instance timezone, and the reply says so (call_log.fixed)."""
    m = _WAKE_RE.fullmatch(text.strip())
    try:
        if not m:
            iso = _wake_iso(text)
            if not iso:
                raise ValueError(text)
            wake_at(iso)                    # a real date and a real time of day
            _calls.fixed("wake", f"wake {text.strip()} read as {iso} {_cfg.tz_abbr()}")
            return iso
        stored = m[1] + ("T" + m[2] if m[2] else "")
        wake_at(stored)                     # a real date and a real time of day (2026-02-30 and 24:00 fail here)
        return stored
    except ValueError:
        raise ToolError(f"Refused: metadata.wake must be YYYY-MM-DD or YYYY-MM-DDTHH:MM ({_cfg.tz_abbr()}) — got {text!r}")


def wake_rows() -> list[tuple[str, Path, dict[str, Any], dt.datetime]]:
    """Every open item with a readable wake, on hold or not: (gid, path, item, the moment it falls due). A held item's wake
    releases the hold; a wake an item carries with no hold and no until (a hand-off's backstop, or one stored before until) is only a notice: the pass tells and drops it."""
    out = []
    for gid, p in _item_files():
        try:
            with open(p, encoding="utf-8") as f:
                it = json.load(f)
        except Exception:
            continue
        _legacy_hold(it)                    # a file from before the migration counts as held
        _ip.read_through(it)
        meta = it.get("metadata") or {}
        if it.get("status") != "open":
            continue
        if _watch.watches(it):               # a watched wait comes due at its own moment (a wake, a relay's ask-by day, a backstop), the watchers' pass acts on it
            ep = _watch.next_moment(meta)
            until = _watching.WATCH_BACKOFF.get(gid, 0.0)           # a turn that failed is not looked at again before its back-off ends, even when the failure could not be written to the item
            if ep is not None and until > time.time():
                ep = max(ep, until)
            if ep is not None:
                out.append((gid, p, it, dt.datetime.fromtimestamp(ep, _pages.zone_now().tzinfo)))
            continue
        if _wl.valid(meta):                  # a list is the watchers' alone, so with them off only its backstop day is looked at (the wake pass ends it there: _watching.watch_fire(legacy=True)); the date as a time wait's wake would drop half the list
            try:
                at = wake_at(_wl.backstop(meta))
            except ValueError:
                continue
            until = _watching.WATCH_BACKOFF.get(gid, 0.0)           # a list whose end failed is not due again before its back-off ends (as the watched branch above), so the runner does not spin on it
            if until > time.time():
                at = max(at, dt.datetime.fromtimestamp(until, _pages.zone_now().tzinfo))
            fa = _watch.failed_at(meta)                             # …and by the note on the item, which outlives a restart (the watched branch above reads it through next_moment): a failure within the back-off puts the moment after it
            if fa and at.timestamp() <= fa + _watch.BACKOFF:
                at = dt.datetime.fromtimestamp(fa + _watch.BACKOFF, _pages.zone_now().tzinfo)
            out.append((gid, p, it, at))
            continue
        if not _wt.wake_value(meta):
            continue
        try:
            out.append((gid, p, it, wake_at(_wt.wake_value(meta))))
        except ValueError:
            continue                        # a wake the gate would have refused (a hand edit): left for a person to see
    return out


def next_wake() -> dt.datetime | None:
    """The earliest moment an open item's wake falls due (a hold's or a backstop's), or None when no open item has one."""
    return min((at for *_, at in wake_rows()), default=None)


def wake_pass(now: dt.datetime | dt.date | None = None) -> list[str]:
    """On hold until a moment (hold is a property of an
    open item): every open item with metadata.hold whose metadata.wake has
    come ([instance] timezone; a date-only wake comes at the start of its day) is released, its hold and wake dropped and
    both clocks moved, as _update moves them; it is back in the lane its needs give it (your call, on others, on agent).
    A wake on an item not on hold, with no until, is a notice (items kept showing "on hold" while their work was
    live, because a wake set as a notice parked them): at its moment the sessions its notices go to (notice_to: the sessions in its needs, else its mover) are told once
    and the wake goes; status, hold, needs and the state clock stay as they were (the item never left its lane).
    The server's own act, not a session's: it owes no page and tells no keeper; it tells the item's mover, one line through
    push.py (the message tool's delivery: a pane by name or uuid, a cse_… session, queued when not live), and a delivery that
    fails is logged to stderr, never raised. Run by the runner (its watchers' tick when a wake is due, and the ten-minute catch-up), at start and at the end of a migration pass. `now` = an
    aware datetime (default now); a date stands for the whole of that day, as the date-only pass took it. The turn rule's
    fourth build (each wake cost its receiver a turn): a session gets one message per pass, listing every
    item woken or reminded for it (wake_tell); one item alone keeps its old line. Nothing waits for a batch: a pass tells at
    once what it woke. → the gids woken or reminded (the caller publishes when there are any)."""
    if now is None:
        now = _pages.zone_now()
    if _watch.paused():                     # [model] pause holds every wake; the due ones fire in one pass when it turns false
        return []
    if isinstance(now, dt.datetime):
        due = lambda at: at <= now
        epoch = now.timestamp()
    else:
        end = wake_at((now + dt.timedelta(days=1)).isoformat())
        due = lambda at: at < end
        epoch = end.timestamp() - 1
    woke = []
    out: dict[str, list[tuple[str, dict[str, Any], str, str, bool]]] = {}     # session → [(gid, item, what, why, reminder)]: one message each (wake_tell)
    with _WAKE_LOCK:
        wout: dict[str, list[tuple[str, dict[str, Any], str]]] = {}     # what the watchers turned, by recipient; sent below with the wake rows of the same session
        woke += _watching.watch_pass(epoch, wout)         # the waits the watchers own
        for gid, _p, it, at in wake_rows():
            if _watch.watches(it) or not due(at) or _hooks().old_wait_off():       # a watched wait is the watchers', above; after the switchover (fallback off) the old pass stands down
                continue
            meta = it.get("metadata") or {}
            if _wl.valid(meta):                # a list with the watchers off: its backstop day has come, so it ends as the watchers would end it there (the same words, an open relay line asks the owner)
                try:                           # a list whose turn failed is not due again before its back-off ends (wake_rows moves its moment, as it does for a watched wait)
                    cause = _watch.due(it, epoch)       # the backstop day, or (a list edited by hand so that every line has arrived) the kind of the line that completed the group
                    if cause and _watching.watch_fire(gid, cause, epoch, wout, recheck=True, legacy=True):
                        woke.append(gid)
                        _watching.WATCH_BACKOFF.pop(gid, None)
                except Exception as e:  # noqa: BLE001  — as _watching.watch_pass: one bad item never stops the pass, so the lists after it are still ended
                    print(f"watch: {gid} skipped this pass: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
                    _watching.watch_failed(gid, epoch)
                continue
            wake = _wt.wake_value(meta)
            had_u = bool(_wt.stored_until(meta))      # a date stored as until is a wait on it, not a backstop: its end releases the item like a hold's
            if had_u:
                meta.pop("wait_kind", None)   # the date has come: the wait is over, its date and its kind go together (a wait stored by the old fields keeps what it had: the stored items are migrated apart)
            meta.pop("wake", None); meta.pop("until", None)
            meta.pop("watch_reason", None)    # a front agent's reason for watching belonged to this wake
            meta.pop("wait_basis", None)      # a wait that stood on a real-world date: the wake is spent, so is its basis
            _hooks().state_end(meta, "parked")        # a park that stood on that wake is over with it
            if not (_hooks().hold_flag(it) or had_u):          # a notice: told once, the wake dropped, nothing else moves
                it["metadata"] = meta
                it["updated"] = time.time()  # the item's own clock; the state clock and the confirm stay (a filing edit, like a recycle done)
                what = f"backstop (wake {wake})"
                _writes.save(gid, it, note=f"{what}: still active, {_hooks().rmod_whose()[_hooks().rmod_needs_kind({'metadata': meta})]}")
                woke.append(gid)
                print(f"wake: {gid} backstop (wake {wake}) — {it.get('subject')}", file=sys.stderr, flush=True)
                wake_notify(gid, it, what, out=out, reminder=True)
                continue
            meta.pop("hold", None); meta.pop("hold_set", None)
            _hooks().hand_stored_then(gid, it, meta)       # a stored `then` takes the item when nothing else holds it (the notice below reaches it through needs)
            if "confirmed" not in it:      # `confirmed` never moves here, so the item reads stale until its mover refreshes it; one
                it["confirmed"] = _hooks().rmod_confirmed_at(it, _p)   # without it is pinned at the clock it read as, before the clocks below move
            it["status"] = "open"; it["metadata"] = meta
            it["updated"] = time.time()
            it["state_updated"] = it["updated"]
            what = f"woke (wake {wake})"
            _writes.save(gid, it, note=f"{what}: {back_words(meta, _gh.ref)}")   # phase 2 prep: the note is the History line, written by the server; another item as #N
            woke.append(gid)
            print(f"wake: {gid} back from hold (wake {wake}) — {it.get('subject')}", file=sys.stderr, flush=True)
            wake_notify(gid, it, what, out=out)
        for sid, rows in out.items():
            wake_tell(sid, rows, extra=_watching.watch_text(sid, wout.pop(sid, [])))     # one message per session for the whole pass
        for sid, rows in wout.items():
            _watching.watch_tell(sid, rows)
    return woke


def back_words(meta: dict[str, Any], sh: Callable[[str], str] = str) -> str:
    """Where a released item stands now, in words: back in its lane, or still after an open item. `sh` writes those ids:
    ghsync.shown in a notice to a session (board#N), ghsync.ref in a History note (#N; an item
    with no issue yet keeps its shown form, board-tmp-<machine>#n), str (the store id) by default."""
    lane = _hooks().rmod_whose()[_hooks().rmod_needs_kind({"metadata": meta})]
    still = _hooks().after_open(meta)
    return f"still after {', '.join(sh(g) for g in still)}, out of the queue until it closes" if still else f"back in its lane ({lane}, by its needs)"


def reminder_to(meta: dict[str, Any]) -> list[tuple[str, str]]:
    """Who a notice (a wake on an item not on hold) tells: the sessions its notices go to (notice_to: the sessions named in its needs, else its mover, else its
    `then`, else the project's builder, else its -main agent: never the creator). → [(session id, why)], each once."""
    return _telling.notice_to(meta)


def wake_notify(gid: str, it: dict[str, Any], what: str, out: dict[str, list[tuple[str, dict[str, Any], str, str, bool]]] | None = None,
                 reminder: bool = False) -> list[str]:
    """An item back in its lane (a wake, or its last `after` closed) tells the sessions its notices go to (notice_to:
    the sessions in its needs other than the mover, else the page's keeper). The mover itself, when it is the one, hears the
    short line as before; another session hears the item, its mover and what to do with it, and on a pilot project the line
    is a pilot notice (a routing-log line the keeper rules on) naming the mover. Still after an open item, the line
    says so. `reminder` (the flag's name): a backstop wake on an item not on hold (a hand-off's backstop, say) that came due, which never left its lane; it goes to the mover and
    the sessions in its needs (reminder_to) and says the item is still active. With `out` (the wake pass) nothing is sent
    here: each session's rows are collected there, for one message per session (wake_tell). → the session ids told."""
    meta = it.get("metadata") or {}
    told = []
    for sid, why in (reminder_to(meta) if reminder else _telling.notice_to(meta)):
        if out is not None:
            out.setdefault(sid, []).append((gid, it, what, why, reminder))
        else:
            wake_tell(sid, [(gid, it, what, why, reminder)])
        told.append(sid)
    if not told:
        print(f"wake: {gid} has nobody to tell", file=sys.stderr, flush=True)
    return told


def _hold_queue_row(sid: str, row: "tuple[str, dict[str, Any], str, str, bool]") -> bool:
    """A woken row whose item is still after an open item (not a reminder): held for a background session as a queue-place notice. True when held."""
    gid, it, what, _why, rem = row
    meta = it.get("metadata") or {}
    if rem or not _hooks().after_open(meta):
        return False
    return _telling.hold_notice(sid, f"[stackshot] {_gh.shown(gid)} {what}: {it.get('subject') or ''} ({meta.get('project') or ''}) — {back_words(meta, _gh.shown)} → {_telling.notice_link(gid)}", "queue", gid=gid)


def wake_tell(sid: str, rows: list[tuple[str, dict[str, Any], str, str, bool]], extra: tuple[str, str, list[str]] | None = None) -> None:
    """Tell one session about the items woken, or whose backstop came due, for it, rows = [(gid, item, what, why, reminder)]: one item alone in its
    line as before; several (the turn rule's fourth build) in one message, the count, then one line each,
    then what to do. A notice (a wake on an item not on hold) says the item is still active and asks to
    close it, refresh its next or set an until date, where a woken item asks to refresh its ask. A pilot notice is recorded for
    each item that is not the session's own, the lines of one message sharing a `batch` id. A row whose project the router is live for,
    and whose recipient is that project's keeper, is not told: it is recorded for the router to rule (router_live.holds)."""
    xtext, xmark, xgids = extra or ("", "", [])         # the watchers' rows for this session in the same pass, appended: one message
    keep = []
    for row in rows:
        gid, it, what, _why, rem = row
        meta = it.get("metadata") or {}
        project, owner = str(meta.get("project") or ""), _telling.holder(it)
        if not _router_live.holds(project, sid):      # the recipient is the item's mover, so there is no "its own item" to tell directly
            keep.append(row); continue
        thn, subject = _telling.then_part(it), str(it.get("subject") or "")
        try:
            nid = _routing.record(project, kind="board", to="", label=f"wake {_gh.shown(gid)}", who="stackshot", text=f"{what}{thn}: {subject}",
                                  url=_telling.notice_link(gid), target="for " + _session_label(sid), pilot=True, live=True)
        except Exception:
            keep.append(row); continue      # not recorded: told as before, never lost
        _router_live.stash(nid, f"[stackshot] {_gh.shown(gid)} {what}: {subject} ({project}){thn}"
                                + ("; the item is still active" if rem else f"; {back_words(meta, _gh.shown)}") + f" → {_telling.notice_link(gid)}")
    rows = [r for r in keep if not _hold_queue_row(sid, r)]       # a wake that leaves the item still after an open item is a place in the queue, nothing to do yet
    if not rows:
        if xtext:
            _telling.tell_woken(",".join(xgids), sid, (xmark + " " if xmark else "") + xtext, tag="watch")
        return
    batch = os.urandom(3).hex() if len(rows) > 1 else ""
    lines, mine, others = [], False, False
    for gid, it, what, why, rem in rows:
        meta = it.get("metadata") or {}
        project, owner = str(meta.get("project") or ""), _telling.holder(it)
        back = f"still active ({_hooks().rmod_whose()[_hooks().rmod_needs_kind({'metadata': meta})]}), check where it stands" if rem else back_words(meta, _gh.shown)
        subject, thn, oid = str(it.get("subject") or ""), _telling.then_part(it), (_hooks().session_id(owner) if owner else "")
        if sid == oid:
            mine = True
            lines.append(f"{_gh.shown(gid)} {what}: {back}")
            continue
        others = True
        nid = ""
        if _anc.pilot_root(project):
            try:
                nid = _routing.record(project, kind="board", to=sid, label=f"wake {_gh.shown(gid)}", who="stackshot", text=f"{what}{thn}: {subject}",
                                      url=_telling.notice_link(gid), target="for " + _session_label(sid), pilot=True, batch=batch)
            except Exception:
                nid = ""
            _telling.live_pass(project, nid, sid)
        if not batch:
            lines.append(f"{_gh.shown(gid)} {what}, {back}: {subject} ({project}){thn}. It comes to you {why}: act on it, "
                         f"or pass it to the session that does the work" + ("" if rem else "; refresh its ask if things moved")
                         + f". → {_telling.notice_link(gid)}" + (f" · notice {nid}" if nid else ""))
        else:
            lines.append(f"{_gh.shown(gid)} {what}, {back}: {subject} ({project}){thn}, to you {why} → {_telling.notice_link(gid)}" + (f" · notice {nid}" if nid else ""))
    gids = [g for g, *_ in rows]
    allrem = all(r[4] for r in rows)
    ask = "close it, refresh its next, or set an until date" if allrem else "refresh its ask if things moved"
    if not batch:
        _telling.tell_woken(", ".join([gids[0], *xgids]), sid, (xmark + " " if xmark else "") + f"[stackshot] {lines[0]}" + (f"; {ask}." if mine else "") + (f"\n{xtext}" if xtext else ""))
        return
    head = (f"{len(rows)} backstops came due for you:" if allrem else f"{len(rows)} items woke for you:" if not any(r[4] for r in rows)
            else f"{len(rows)} items came due for you (woken, or a backstop came due):")
    text = [f"[stackshot] {head}"] + [f"- {ln}" for ln in lines]
    if others:
        text.append("For an item that is not yours: act on it, or pass it to the session that does the work.")
    text.append(("Close each one, refresh its next, or set an until date." if allrem else "Refresh each one's ask if things moved."))
    _telling.tell_woken(", ".join([*gids, *xgids]), sid, (xmark + " " if xmark else "") + "\n".join(text) + (f"\n{xtext}" if xtext else ""))


def release_after(gid: str, outcome: str, superseded_by: str, writer: str, reason: str = "") -> list[str]:
    """`gid` just closed. Every open item that waits on it (after) drops it: a superseded one is followed to its
    replacement (the item then waits on that, when it is open), a done or dropped one simply goes. An item left with no open
    prerequisite wakes: after, hold and wake go, both clocks move, and the sessions its notices go to are told what closed
    and how (a dropped one says so). The server's own act: no page owed. Then every other open item whose next or description names the closed one, and that no `after` link just woke,
    tells its mover once (tell_close_mentions). → the gids released."""
    released = []
    waiting_on: set[str] = set()        # the open items that had the closed one in `after`: the wake above is their notice
    rep = _hooks().follow_superseded(superseded_by) if outcome == "superseded" and superseded_by else ""
    try:
        rep_open = bool(rep) and _load(rep).get("status") == "open"
    except ToolError:
        rep_open = False
    wout: dict[str, list[tuple[str, dict[str, Any], str]]] = {}       # the watched waits this close ended, by recipient (one message each, below)
    for g, _p in _item_files():
        try:
            it = _load(g)
        except Exception:
            continue
        meta = dict(it.get("metadata") or {})
        if it.get("status") != "open" or (gid not in _after_of(meta) and not _wl.lines_for_item(meta, gid, open_only=False)):      # a wait on a list is found by any of its item lines
            continue
        waiting_on.add(g)
        if _wl.valid(meta):             # a wait on a list is the watchers' alone, never today's release below (two mechanisms must not end the same item)
            if _watch.watches(it) and _watching.watch_item_closed(g, it, gid, outcome, rep if rep_open else "", writer, wout, superseded_by):
                released.append(g)
            continue
        if _watch.watches(it) and not (_wt.stored_until(meta) and not _uw.kind_of(meta) and _after_of(meta)):         # a watched wait is the watchers', not today's release below (a date with an after link and no kind is a park on the closing, released below)
            if _watching.watch_item_closed(g, it, gid, outcome, rep if rep_open else "", writer, wout, superseded_by):
                released.append(g)
            continue
        if _hooks().old_wait_off():            # the switchover without its fallback: only a watcher ends a wait
            continue
        after = [x for x in _after_of(meta) if x != gid]
        if rep_open and rep not in after and rep != g:
            after.append(rep)
        meta["after"] = after
        left = _hooks().after_open(meta)
        if left:                  # another blocker is still open: the wait goes on, on the ones left (a dropped one is simply no longer waited on)
            it["metadata"] = meta; it["updated"] = time.time()
            _writes.save(g, it, note=f"{_gh.ref(gid)} closed as {outcome}" + (f", followed to {_gh.ref(rep)}" if rep_open else "")   # the History note: other items as #N
                  + f"; still waits on {', '.join(_gh.ref(x) for x in left)}")
            print(f"after: {g} now waits on {', '.join(left)} ({gid} closed as {outcome}" + (f", followed to {rep}" if rep_open else "") + ")", file=sys.stderr, flush=True)
            continue
        had_until = bool(_wt.stored_until(meta))
        meta.pop("after", None); meta.pop("hold", None); meta.pop("hold_set", None); meta.pop("wake", None); meta.pop("until", None); meta.pop("wait_basis", None)
        if had_until and _watch.stored_kind(meta) == "item":
            meta.pop("wait_kind", None)           # the wait it stood on is over: its date and its kind go together
        _hooks().state_end(meta, "blocked", "parked")     # the item it waited on is closed: the wait is over
        meta.pop("wait_failed", None); meta.pop("waiting", None)   # released: nothing is waited on, so no failed wait stays, and a `waiting` record an earlier version wrote goes too (the wake notice below is the one the keeper gets)
        _hooks().hand_stored_then(g, it, meta)           # a `then` stored while the item waited (a decision answered on a held item) takes it now; the wake notice below reaches it through needs
        if "confirmed" not in it:
            it["confirmed"] = _hooks().rmod_confirmed_at(it, _p)
        it["metadata"] = meta; it["updated"] = time.time(); it["state_updated"] = it["updated"]
        how = lambda sh: ("was dropped" if outcome == "dropped" else f"was superseded by {sh(rep or superseded_by)}, which is closed too" if outcome == "superseded"
                          else "closed (done)")   # sh: ghsync.shown for the notice a session reads, ghsync.ref for a History note (#N), str for the stderr line
        what = lambda sh: f"woke: {sh(gid)}, the last item it waited on, {how(sh)}" + (f" by {_session_label(writer)}" if writer else "")
        _writes.save(g, it, note=f"{what(_gh.ref)}: {back_words(meta, _gh.ref)}"); released.append(g)   # phase 2 prep: the note is the History line, written by the server; other items as #N
        print(f"after: {g} released, {gid} {how(str)} — {it.get('subject')}", file=sys.stderr, flush=True)
        wake_notify(g, it, what(_gh.shown))
    for sid, rows in wout.items():
        _watching.watch_tell(sid, rows)
    try:
        _telling.tell_close_mentions(gid, outcome, reason, writer, waiting_on)
    except Exception as e:  # noqa: BLE001  — the close is saved and published; a notice that fails is a stderr line, never a failed close
        print(f"close: {gid} mentions not told: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return released


def anchor_release(project: str, n: dict[str, Any], by: str = "", only_watched: bool = False) -> list[str]:
    """A notice from an
    anchor scoped to a held open item releases its hold when the project's keeper passed or merged it (never when it dropped
    it), or, in a project with no keeper, when it arrived. Only a notice newer than the item's last state change counts: one
    that came before the park was in front of whoever parked it; and the release moves the clocks, so a notice releases once.
    The hold and its wake go, an open `after` stays (the item still waits on that). → the gids released.
    A routine event on the fleet's own PR (the turn rule's third build) is logged with no recipient and ruled
    `merged` by _routing.AUTO_RULER at once (_watching.auto_line): it releases exactly as the keeper's own `merged` would; only its delivery to a
    session is skipped. The minute loop finds it (anchor_pass). A notice names its anchor by id (github:<repo>#<n>, what
    the anchor receiver records) and the anchors store by URL: the two are compared as anchor ids (_watching.same_anchor)."""
    url = str(n.get("anchor") or "")
    if n.get("kind") != "anchor" or not url or not (n.get("to") or n.get("live") or _watching.auto_line(n)):
        return []      # no recipient: a log-only direct anchor's line (the receiver's direct setting "none"), which wakes nobody (a line the live router holds has none either, but it rules it: `live`)
    stew = _telling.page_keeper(project)
    if _watching.auto_line(n):
        at = float(n.get("ruled_at") or n.get("ts") or 0)
        how = f"was logged and ruled {n['ruling']} by {_routing.AUTO_RULER} (a routine event on the fleet's own pull request)"
    elif stew:
        if n.get("ruling") not in ("passed", "merged"):
            return []
        at = float(n.get("ruled_at") or n.get("ts") or 0)
        how = f"was {n['ruling']} by {_session_label(by) or _session_label(stew) or 'the project keeper'}"
    else:
        at = float(n.get("ts") or 0)
        how = "arrived (nobody rules this project's notices)"
    released = []
    try:
        entries = [e for e in _anc.load().get(project, []) if _watching.same_anchor(str(e.get("url") or ""), url) and e.get("items")]
    except Exception:
        entries = []
    for g in ([] if only_watched else dict.fromkeys(str(g) for e in entries for g in e["items"])):     # only_watched: the minute pass replays a notice for the watchers alone; today's held items got no release from it before
        try:
            it = _load(g)
        except Exception:
            continue
        date_wait = bool(_wt.stored_until(it.get("metadata") or {})) and not str((it.get("metadata") or {}).get("wait_kind") or "").strip()      # a wait on the date alone (until, no kind): what a hold with a wake was, released by the notice
        if it.get("status") != "open" or not (_hooks().is_held(it) or date_wait) or (_watch.watches(it) and not date_wait) or at <= float(it.get("state_updated") or 0):      # a watched wait is the watchers' (_watching.watch_anchor_notice below)
            continue
        meta = it["metadata"]
        had_until = bool(_wt.stored_until(meta))
        meta.pop("hold", None); meta.pop("hold_set", None); meta.pop("wake", None); meta.pop("until", None); meta.pop("wait_basis", None); meta.pop("idle", None)
        if had_until and _watch.stored_kind(meta) == "anchor":
            meta.pop("wait_kind", None)           # the wait it stood on is over: its date and its kind go together
        _hooks().state_end(meta, "parked")
        it["updated"] = it["state_updated"] = time.time()
        what = f"woke: a notice from {url}, the anchor it waited on, {how}"
        _writes.save(g, it, note=f"{what}: {back_words(meta, _gh.ref)}")   # phase 2 prep: the note is the History line, written by the server; another item as #N
        wake_notify(g, it, what)
        print(f"anchor wait: {g} released ({project}, notice {n.get('id')})", file=sys.stderr, flush=True)
        released.append(g)
    released += _watching.watch_anchor_notice(project, url, n, at, how)       # the items whose stored wait is an anchor event on this very anchor
    return released


def _watched_anchors(it: dict[str, Any]) -> list[str]:
    """The anchors a watched wait of this open item stands on: an anchor wait's wait_anchor, or the anchors of the anchor lines of a wait on a list that have not arrived; [] for anything else."""
    wm = it.get("metadata") or {}
    if not _watch.watches(it):
        return []
    k = _watch.stored_kind(wm)
    if k == "anchor":
        return [str(wm["wait_anchor"])]
    if k == _wl.LIST:
        ls = _wl.lines(wm)
        return [ls[i]["anchor"] for i in _wl.lines_by_kind(wm, "anchor")]
    return []


def anchor_pass() -> list[str]:
    """The minute loop's half of the anchor wait: in a project with no keeper nobody rules, so a held item scoped to an
    anchor is released by any notice from it that came after the park. In a project with a keeper the keeper's ruling
    releases (_route), and here only a line the anchor receiver logged and ruled itself (_watching.auto_line: the fleet's own routine PR event,
    the turn rule's third build), which no keeper rules. The page that holds the anchor is the one whose keeper rules and whose routing log has the notice, so the log is read for the
    pages that hold an anchor scoped to a held item (the item may be of another project), and only for those. The stored anchor waits of the watchers are not held items: the log is replayed for them too, a keeper's ruling included, but only
    to them (anchor_release only_watched), so a held item on the same anchor gets no release it did not get before; the log is read from the oldest floor of those waits. While the migration's pass
    holds the board nothing is released and the log is not read (the notices stay in the log: the pass after it finds them). → the gids released."""
    if _watch.holding():
        return []
    held: dict[str, list[str]] = {}            # page that holds an anchor scoped to a held item → those items (the page's routing log is where its notices are, whatever project the item is of)
    watched: dict[str, set[str]] = {}          # page → the anchors a stored anchor wait of an open item watches (the item's own page, and every page that holds the anchor)
    floors: dict[str, float] = {}              # page → the oldest notice any of those waits could count
    try:
        store = _anc.load()
    except Exception:  # noqa: BLE001
        store = {}
    for gid, _p in _item_files():
        try:
            it = _load(gid)
        except Exception:
            continue
        if it.get("status") != "open":
            continue
        wm = it.get("metadata") or {}
        proj = str(wm.get("project") or "")
        urls = _watched_anchors(it)
        if urls:
            try:
                _watching.watch_stamp(gid)              # a wait stored before this deploy has no stamp: it gets one now, and no older notice is its arrival
            except Exception as e:  # noqa: BLE001  — one bad stamp does not stop the pass (the floor falls back to the item's last write)
                print(f"watch: {gid} not stamped: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
            floor = _watching.watch_floor(_load(gid))
            for u in urls:                     # an anchor wait's one anchor, or every open anchor line of a wait on a list
                for page in dict.fromkeys([proj, *_ascope.holders(store, u, _watching.same_anchor)]):
                    watched.setdefault(page, set()).add(_watching.anchor_key(u))
                    floors[page] = min(floors.get(page, float("inf")), floor)
        elif _hooks().is_held(it):
            for e in _ascope.anchor_scope(store, gid, proj):
                for page in e["pages"]:
                    held.setdefault(page, []).append(gid)
    out = []
    for project in dict.fromkeys([*held, *watched]):
        if not project:
            continue
        stew = bool(_telling.page_keeper(project))
        try:
            scoped = {_watching.anchor_key(e["url"]) for e in _ascope.clean_entries(store.get(project)) if e["items"] and set(e["items"]) & set(held.get(project, []))}
        except Exception:
            scoped = set()
        keys = scoped | watched.get(project, set())
        if not keys:
            continue
        week = time.time() - 7 * 86400
        since = week if scoped else max(week, floors.get(project, week))
        for n in _routing.read(project, since=since):
            if n.get("kind") != "anchor":
                continue
            k = _watching.anchor_key(str(n.get("anchor") or ""))
            if k in scoped and (not stew or _watching.auto_line(n)):
                out += anchor_release(project, n)
            elif k in watched.get(project, ()):
                out += anchor_release(project, n, only_watched=True)
    return out


def minute_wake_pass() -> None:
    """The watchers' pass: it runs when a wake is due, and the board is published when it woke something. The wait for the next wake is the runner's (minute_wake_wait)."""
    nxt = next_wake()
    if nxt is not None and nxt <= _pages.zone_now() and wake_pass():
        _hooks().publish()


def minute_wake_catchup() -> None:
    """The ten-minute catch-up of the wake pass: the pass run without the due-wake gate of `minute_wake_pass`, because the watchers also end waits that `next_wake` does not count (an item wait
    whose `after` items all closed while nobody saw the close, with a far ask-by). The timer publish used to run it; the board is published when it released something."""
    if wake_pass():
        _hooks().publish()


def minute_anchor_pass() -> None:
    """The anchor pass, in a tick of its own so that a failure in it does not stop the next one; published when it released something. The merge pass (`_merge_progress_tick`) rides
    on it: it reads what the anchor receiver saw, as the anchor pass does, and a failure in either does not stop the other."""
    try:
        released = anchor_pass()
    except Exception as e:  # noqa: BLE001  — the merge pass below is not stopped for it
        released = []
        print(f"anchor pass: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    try:
        moved = _hooks().merge_progress_tick()
    except Exception as e:  # noqa: BLE001  — the anchor pass is not stopped for it
        moved = []
        print(f"merge progress: not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    try:
        _hooks().event_activity_tick()      # records only (metadata.last_activity), no publish for it: the home page is kept for 30 s, then drawn again, and the rows pick the record up
    except Exception as e:  # noqa: BLE001  — groundwork for a later part; the merge pass above is done and the next minute reads again
        print(f"last activity: not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    if released or moved:
        _hooks().publish()


def minute_wake_wait() -> float:
    """How long the runner sleeps after a pass: until the earliest wake, at most 60 s (60 s when none, or while [model] pause holds every wake)."""
    nxt = next_wake()
    return 60.0 if nxt is None or _watch.paused() else min(max((nxt - _pages.zone_now()).total_seconds(), 0.0), 60.0)
