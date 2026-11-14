"""foryou_events.py: the rows the For you list makes, the part that reads and writes: whether the owner watches an item (`_foryou_watched`, which reads his flag), the row a save makes (`_foryou_on_save`,
`_foryou_make`), the Landed list's record beside it (`_landed_on_save`) and the due-date pass (`_foryou_tick`).

The rules (which events make a row, what the line says, the key of an event, the due-date window) are notify/foryou_rows.py's, on the item as the file held it and as it is now; the list's file is service/foryou.py's,
the Landed list's service/landed.py's and the Slack hook service/foryou_slack.py's. What this module reads is the flag, the session's name, the item's page, the open items and the clock, and what it reaches in web/ (the
debounced publish, the page's parser of an ask line and the words for a date) is in service/foryou_hooks.py. `writes.save` calls `_foryou_on_save` and `_landed_on_save` on this module, the close fallback in
service/telling.py reads `_FORYOU_FAILED` and `_foryou_key` here, and the dates pass calls `_foryou_tick`; `_FORYOU_LAST` and `_FORYOU_FAILED` are mutated in place, never rebound. A suite that stubs a name sets it on this module."""
from __future__ import annotations

import sys
import time
from typing import Any

from stackshot.core.store import _item_files
from stackshot.fleet.sessions_registry import _session_label
from stackshot.github import ghsync as _gh
from stackshot.model import model as _model
from stackshot.model.ids import _item_url
from stackshot.notify import foryou_rows as _rows
from stackshot.service import foryou as _fy
from stackshot.service import foryou_slack as _fyslack
from stackshot.service import landed as _ld
from stackshot.service.foryou_hooks import hooks as _hooks
from stackshot.service.foryou_slack import _foryou_slack
from stackshot.service.store import _load

_FORYOU_LAST = [0.0]


def _foryou_watched(gid: str, item: dict[str, Any]) -> tuple[bool, str]:
    """Is this item one he watches, and why: his own flag first (mute / watch), then the defaults. → (watched, the reason in words)."""
    return _rows.watched(_fy.flag(gid), item)


def _foryou_key(gid: str, kind: str, item: dict[str, Any]) -> str:
    """The key of one event on an item: the same event never makes two rows (foryou.add). The state clock tells one close from the next."""
    return _rows.key(gid, kind, item)


_FORYOU_FAILED: set[str] = set()         # keys of closes whose row could not be written (the fallback in tell_close_owner reads it)


def _foryou_make(gid: str, item: dict[str, Any], kind: str, what: str, disc: Any, urgent: bool = False) -> dict[str, Any] | None:
    """One row for a watched item's event (None when the item is not watched or the event already has its row). A write that fails is
    raised after a close's key is noted in _FORYOU_FAILED, so the close can still reach someone (tell_close_owner)."""
    watched, _why = _foryou_watched(gid, item)
    if not watched:
        return None
    try:
        row = _fy.add(**_rows.row_fields(gid, item, kind, what, disc, _gh.shown(gid), _item_url(gid), urgent))
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
    """Called by writes.save with the item as the file held it (`before`, None for a create) and as it is now: the rows for what changed.
    `own` = his own answer from the board, which makes no row (he did it) but still takes a decision row off the list."""
    if _rows.decision_left(before, item):
        try:
            _fy.resolve(gid, "decision")
        except Exception as e:  # noqa: BLE001  — the close below must still be tried
            print(f"for-you: {gid} decision row not taken off: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    if own:
        return
    who = (_session_label(writer) if writer else "") or "the server"
    for kind, what, disc in _rows.changes(before, item, who, _gh.shown, _hooks().parse_ask):
        _foryou_make(gid, item, kind, what, disc)


def _landed_on_save(gid: str, before: dict[str, Any] | None, item: dict[str, Any], writer: str = "", own: bool = False) -> None:
    """The Landed list (every close is a count to a page), called by writes.save beside _foryou_on_save. A close of an open item to outcome done
    or dropped that the owner did not make is a record, unseen: whoever the writer is (a session, or no one for the server's own done check). The owner's own close is
    `own` (his answer on the board, e.g. "drop it" on a watcher's ask) or a write whose sender is he (the tools refuse that sender, _sender_not_owner, but a server path may
    write as him); it lands nothing and takes any record of the item off. A reopen takes the record off too: the item has not landed any more, and its next close is a new record."""
    what = _rows.landing(before, item)
    if what == "close":
        if own or (writer and (_model.is_owner(writer) or _model.is_owner(_session_label(writer)))):
            _ld.forget(gid)
        else:
            ts, outcome, project = _rows.close_record(item, time.time())
            _ld.record(gid, ts, outcome, by=writer, project=project)
    elif what == "reopen":
        _ld.forget(gid)


def _foryou_tick(now: float | None = None) -> list[str]:
    """The due-date look (every ten minutes, the dates pass opening the gate): an open watched item whose due date ends
    within 24 h, or ended less than 24 h ago, gets one URGENT row per due date (also posted to Slack once). A due date longer past is
    not looked at: the first pass after a deploy must not raise every old overdue item. The same pass hands an urgent row whose Slack post
    failed (or never went, a command named later) to the worker again: under 24 h old, at most SLACK_TRIES tries in all. The board is
    republished (debounced) when a row was made. → the gids that got a row."""
    now = time.time() if now is None else now
    if now - _FORYOU_LAST[0] < _rows.EVERY:
        return []
    _FORYOU_LAST[0] = now
    made: list[str] = []
    for gid, _p in _item_files():
        try:
            it = _load(gid)
            due = _rows.due_state(it, now)
            if due is None:
                continue
            when, stored = due
            if _foryou_make(gid, it, "due", _rows.due_what(when, _hooks().when_words(_rows.due_day(stored)), it.get("subject")), stored, urgent=True):
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
        _hooks().publish()
    return made
