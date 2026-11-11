"""foryou_events.py: the rows the For you list makes, the part of the list's code that reads an item: whether the owner watches it (`_foryou_watched`), the key of one event (`_foryou_key`), the row a save
makes (`_foryou_on_save`, `_foryou_make`), the Landed list's record beside it (`_landed_on_save`) and the due-date pass (`_foryou_tick`).

server.py is being split into one module per area (CONTRIBUTING.md, Layout). The list's rows are foryou.py's, its one Slack hook foryou_slack.py's; what a change of an item makes of them is here, and
what it reads of server.py (a session's name, an item's page, the owner's words, whether an item waits on his decision, the debounced publish) is in shared.py. server.py imports the names the saves, the tick
and the close fallback call back from here, so `server._foryou_on_save`, `server._foryou_tick` and the others stay the names the suites use; `_FORYOU_LAST` and `_FORYOU_FAILED` are mutated in place, never rebound,
so the name on `server` and the one here are one object. A suite that stubs the publish for the due-date pass sets it on this module (`server._fyev._publish = ...`), the one place `_foryou_tick` looks it up."""
from __future__ import annotations

import datetime as dt
import sys
import time
from typing import Any

from stackshot.github import ghsync as _gh
from stackshot.model import model as _model
from stackshot.model.needs import _waits_decision
from stackshot.waits import waiting as _wt
from stackshot.web import foryou as _fy
from stackshot.web import foryou_slack as _fyslack
from stackshot.web import landed as _ld
from stackshot.web import render as _rmod
from stackshot.web.common import _clip_line
from stackshot.web.foryou_slack import _foryou_slack
from stackshot.web.shared import _item_url, _owner_words, _publish, _session_label
from stackshot.web.store import _item_files, _load


# A notice for the owner is a row in the For you list (foryou.py: the board's section, `client.py get for-you` for the fleet tool's web server), never a front
# agent's turn. A row is made for a WATCHED item's state change he should see: a close, a reopen, a move to needs=decision, a done check
# that can never pass, and a due date within 24 h (the pass below). A failed release makes no row (_client_post `message`). Watched by default: an item with
# his words on it (a `said` entry, a board or GitHub answer, a quote in the text; there is no separate creator field, and an item he asked
# for carries his words) and an item that needs his decision. His own setting on the item's page wins: Mute stops its rows, Watch adds an
# item that is not watched. The rows are made where the change is saved (`_save` compares the file before and after, so every path that
# changes an item counts: a session's write, the server's own pass, his board answer), never where a session's message is sent: a message a
# session sends on purpose with [for <owner>] (a decision or a go-ahead asked for) is not touched. A decision row goes when the decision
# leaves the item's needs (answered, or closed). The urgent rows (a due date within 24 h) are also posted once to Slack
# through _for_you_slack_post, the one hook (foryou_slack.py, with the queue and the worker thread that post it).
_FORYOU_EVERY = 300.0        # seconds between passes of the due-date look; the dates pass opens the gate itself, every ten minutes
_FORYOU_LAST = [0.0]
_FORYOU_DUE_S = 24 * 3600.0  # "within 24 h": a due date whose end is at most this far ahead, or past by less than this
_FORYOU_WHAT = 300           # characters of a row's line


def _foryou_watched(gid: str, item: dict[str, Any]) -> tuple[bool, str]:
    """Is this item one he watches, and why: his own flag first (mute / watch), then the defaults. → (watched, the reason in words)."""
    mode = _fy.flag(gid)
    if mode == "mute":
        return False, "muted by him"
    if mode == "watch":
        return True, "watched by him"
    meta = item.get("metadata") or {}
    if item.get("status") == "open" and _waits_decision(meta):
        return True, "it needs his decision"
    if _owner_words(item):
        return True, "his words are on it"
    if any(isinstance(a, dict) for a in (meta.get("answers") if isinstance(meta.get("answers"), list) else [])):
        return True, "he answered on it"
    return False, "not watched"


def _foryou_stamp(item: dict[str, Any]) -> int:
    try:
        return int(float(item.get("state_updated") or item.get("updated") or 0))
    except (TypeError, ValueError):
        return 0


def _foryou_key(gid: str, kind: str, item: dict[str, Any]) -> str:
    """The key of one event on an item: the same event never makes two rows (foryou.add). The state clock tells one close from the next."""
    return f"{gid}:{kind}:{_foryou_stamp(item)}"


_FORYOU_FAILED: set[str] = set()         # keys of closes whose row could not be written (the fallback in _tell_close_owner reads it)


def _foryou_make(gid: str, item: dict[str, Any], kind: str, what: str, disc: Any, urgent: bool = False) -> dict[str, Any] | None:
    """One row for a watched item's event (None when the item is not watched or the event already has its row). A write that fails is
    raised after a close's key is noted in _FORYOU_FAILED, so the close can still reach someone (_tell_close_owner)."""
    watched, _why = _foryou_watched(gid, item)
    if not watched:
        return None
    meta = item.get("metadata") or {}
    try:
        row = _fy.add(key=f"{gid}:{kind}:{disc}", kind=kind, gid=gid, item=_gh.shown(gid), project=str(meta.get("project") or ""),
                      what=_clip_line(what, _FORYOU_WHAT), url=_item_url(gid), urgent=urgent)
    except Exception:
        if kind == "closed":
            if len(_FORYOU_FAILED) > 500:
                _FORYOU_FAILED.clear()
            _FORYOU_FAILED.add(f"{gid}:{kind}:{disc}")
        raise
    if row and urgent:
        _foryou_slack(row)
    return row


def _foryou_on_save(gid: str, before: dict[str, Any] | None, item: dict[str, Any], writer: str = "", own: bool = False) -> None:
    """Called by _save with the item as the file held it (`before`, None for a create) and as it is now: the rows for what changed.
    `own` = his own answer from the board, which makes no row (he did it) but still takes a decision row off the list."""
    b = before or {}
    bm, am = b.get("metadata") or {}, item.get("metadata") or {}
    bs, as_ = b.get("status"), item.get("status")
    was_dec = bs == "open" and _waits_decision(bm)
    is_dec = as_ == "open" and _waits_decision(am)
    if was_dec and not is_dec:
        try:
            _fy.resolve(gid, "decision")
        except Exception as e:  # noqa: BLE001  — the close below must still be tried
            print(f"for-you: {gid} decision row not taken off: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    if own:
        return
    subject, who = str(item.get("subject") or ""), (_session_label(writer) if writer else "") or "the server"
    if as_ == "completed" and bs == "open":
        outcome, sup, reason = str(am.get("outcome") or "done"), str(am.get("superseded_by") or ""), str(am.get("reason") or "").strip()
        _foryou_make(gid, item, "closed", f"closed by {who} ({outcome}{' by ' + _gh.shown(sup) if sup else ''}): {subject}" + (f" — {reason}" if reason else ""),
                     _foryou_stamp(item))
    elif as_ == "open" and bs == "completed":
        _foryou_make(gid, item, "reopened", f"reopened by {who}: {subject}", _foryou_stamp(item))
    if is_dec and not was_dec:
        pa = _rmod.parse_ask(str(am.get("ask") or ""))
        _foryou_make(gid, item, "decision", "needs your decision: " + (pa["decide"] if pa else subject), _foryou_stamp(item))
    wf, wb = am.get("wait_failed"), bm.get("wait_failed")
    if as_ == "open" and isinstance(wf, dict) and wf and wf != wb:
        _foryou_make(gid, item, "check_failed", f"{wf.get('what') or 'a wait'} can no longer end: {wf.get('why') or 'it failed'} ({subject})",
                     int(float(wf.get("at") or 0)) or _foryou_stamp(item))


def _landed_on_save(gid: str, before: dict[str, Any] | None, item: dict[str, Any], writer: str = "", own: bool = False) -> None:
    """The Landed list (every close is a count to a page), called by _save beside _foryou_on_save. A close of an open item to outcome done
    or dropped that the owner did not make is a record, unseen: whoever the writer is (a session, or no one for the server's own done check). The owner's own close is
    `own` (his answer on the board, e.g. "drop it" on a watcher's ask) or a write whose sender is he (the tools refuse that sender, _sender_not_owner, but a server path may
    write as him); it lands nothing and takes any record of the item off. A reopen takes the record off too: the item has not landed any more, and its next close is a new record."""
    bs, as_ = (before or {}).get("status"), item.get("status")
    if as_ == "completed" and bs == "open":
        am = item.get("metadata") or {}
        if own or (writer and (_model.is_owner(writer) or _model.is_owner(_session_label(writer)))):
            _ld.forget(gid)
        else:
            _ld.record(gid, _foryou_stamp(item) or time.time(), str(am.get("outcome") or "done"), by=writer, project=str(am.get("project") or ""))
    elif as_ == "open" and bs == "completed":
        _ld.forget(gid)


def _foryou_tick(now: float | None = None) -> list[str]:
    """The due-date look (every ten minutes, the dates pass opening the gate): an open watched item whose due date ends
    within 24 h, or ended less than 24 h ago, gets one URGENT row per due date (also posted to Slack once). A due date longer past is
    not looked at: the first pass after a deploy must not raise every old overdue item. The same pass hands an urgent row whose Slack post
    failed (or never went, a command named later) to the worker again: under 24 h old, at most _fy.SLACK_TRIES tries in all. The board is
    republished (debounced) when a row was made. → the gids that got a row."""
    now = time.time() if now is None else now
    if now - _FORYOU_LAST[0] < _FORYOU_EVERY:
        return []
    _FORYOU_LAST[0] = now
    made: list[str] = []
    for gid, _p in _item_files():
        try:
            it = _load(gid)
            meta = it.get("metadata") or {}
            due = str(meta.get("due") or "")
            if it.get("status") != "open" or not due:
                continue
            end = _wt.due_epoch(due)
            if end is None or not -_FORYOU_DUE_S < end - now <= _FORYOU_DUE_S:
                continue
            when = "overdue since" if end <= now else "due"       # the due date is a day: its end is when it is due
            if _foryou_make(gid, it, "due", f"{when} {_rmod.when_words(dt.date.fromisoformat(due[:10]))}: {it.get('subject') or ''}", due, urgent=True):
                made.append(gid)
        except Exception as e:  # noqa: BLE001  — one item never stops the pass
            print(f"for-you: {gid} due-date look failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    try:
        if _fyslack._for_you_slack_on():
            for r in _fy.slack_pending(now):
                _foryou_slack(r)
    except Exception as e:  # noqa: BLE001
        print(f"for-you: Slack retry pass failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    if made:
        _publish()
    return made
