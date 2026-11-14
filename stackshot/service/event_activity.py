"""event_activity.py: the last-activity pass on a tied pull request's events (the wake pass `_event_activity_tick`).

`metadata.last_activity` (model/last_activity.py) takes what each save did that is visible activity and, here, the events the hub saw on a pull request tied to the item: a CI result, a comment by a person, a
review, a merge, a commit (anchors/event_log.py). `_event_activity_tick` reads the hub's event log from the saved offset, ties each line to the open items it concerns and records it in the item's record.
The ties are merge_tied's, through the merge pass's `_merge_tied`, which is still the surface's (service/wake_hooks.py, hook `merge_tied`). The record only: the save is the server's own bookkeeping.

A service module: it reads the store and the event log and writes an item only through `writes.save`, under `ITEM_LOCK`. It reads the clock through its own `time` (a suite that fakes the clock sets `time` here),
and the wake pass reaches the tick through service/wake_hooks.py (`event_activity_tick`, looked up on this module when it runs).

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import sys
import time
from typing import Any

from stackshot.anchors import event_log as _elog
from stackshot.core import readonly as _ro
from stackshot.model import activity as _activity
from stackshot.model import holders as _holders
from stackshot.model import last_activity as _lastact
from stackshot.service import item_read as _item_read
from stackshot.service import store as _svcstore
from stackshot.service import writes as _writes
from stackshot.service.wake_hooks import hooks as _hooks
from stackshot.waits import stall as _stall
from stackshot.waits import watchers as _watch


# ----------------------------------------------------------------------------- the last-activity record: events on a tied pull request
# `metadata.last_activity` (model/last_activity.py) takes what each save did that is visible activity (`_stamp_last_activity` in `service/writes.py`, run by `writes.save`) and, here, the events the hub saw on a pull request
# tied to the item: a CI result, a comment by a person, a review, a merge (anchors/event_log.py: `Hub.emit` appends one line each, as it does for a merge, from what the event holds). The ties are
# merge_tie's, through `_merge_tied`, the same rules and the same items as the merge pass (anchored, the pull request's body, the item's own words; open items off the stall ladder, waiting and held
# ones left alone). The record only: the save is the server's own bookkeeping (no writer, activity kind `bookkeeping`), so it does not move the `activity` clock, adds no History line and
# is no publish (the home page is kept for 30 s, so the On agent rows and the item page pick the record up on their next draw). A commit to a tied pull request comes in the same way: the hub's GitHub receiver sees the head sha change and emits it at the time it saw it (after downtime, at the commit's committer date).
_EVENT_ACT_FLOOR_H = _elog.FLOOR_H       # an event older than this is not read (a day of downtime, or a shorter file read again from its start): the record would only fill with old news (the hub applies the same window to the event's own time when it writes the line)
_EVENT_ACT_AHEAD_S = _elog.AHEAD_S       # …nor one stamped more than this ahead of the server's clock (a skew of minutes is allowed and read as now)


def _event_rows(rows: list[dict[str, Any]], now: float) -> list[dict[str, Any]]:
    """The lines worth acting on: each parsed on its own (event_log.normal), a line of the wrong shape logged (bounded) and skipped, and only those younger than the floor."""
    out: list[dict[str, Any]] = []
    floor = now - _EVENT_ACT_FLOOR_H * 3600.0
    for row in rows:
        try:
            r = _elog.normal(row)
        except Exception as e:  # noqa: BLE001
            print(f"last activity: line skipped ({e.__class__.__name__}: {str(e)[:80]}): {_elog.shown(row)}", file=sys.stderr, flush=True)
            continue
        if floor <= r["ts"] <= now + _EVENT_ACT_AHEAD_S:      # a time far ahead of this clock is a torn line, not an event: it would otherwise read as now
            out.append(r)
    return out


def _event_item_live(it: dict[str, Any], now: float) -> bool:
    """Is the item still on the stall ladder: not waiting, not held, not in the owner's lane (the test `_merge_tied` makes when it ties)?"""
    return not (_stall.not_due(it, now, lambda i_: _item_read._after_open(i_.get("metadata") or {})) or _holders._is_held(it))


def _event_activity_tick(now: float | None = None) -> list[str]:
    """The pass: read the hub's event log from where it stopped, tie each line to the open items it concerns (`_merge_tied`) and record it in the item's `metadata.last_activity` when it is later than what
    the item holds (last_activity.apply: newest wins, a repeat writes nothing). One item that cannot be read or saved is logged and skipped; the offset is stored whatever happened to the items, but
    not when the items could not be read at all (the lines are read again next minute). Never raises. A held board and a read-only standby copy run nothing. → the ids saved."""
    try:
        if _watch.holding() or _ro.is_read_only():
            return []
        now = time.time() if now is None else now
        off = _elog.load_offset()
        rows, new = _elog.read(off or 0)      # an offset past the end of the file (replaced or shrunk) reads from its start
        rows = _event_rows(rows, now)
        saved: list[str] = []
        if rows:
            try:
                ties = _hooks().merge_tied(rows, now)
            except Exception as e:  # noqa: BLE001
                print(f"last activity: items not read: {e.__class__.__name__}: {str(e)[:120]}", file=sys.stderr, flush=True)
                return []
            per_item: dict[str, tuple[list[dict[str, Any]], str]] = {}      # item → (its signals, the pull request of the first), so many lines for one item are one save
            for row, key, tied in sorted(ties, key=lambda t: t[0]["ts"]):
                cand = _lastact.pr_candidate(row["kind"], row["n"], row["ts"], now)
                for gid in tied:
                    sigs, first = per_item.setdefault(gid, ([], key))
                    if cand is not None:
                        sigs.append(cand)
            for gid, (sigs, key) in per_item.items():
                newest = _lastact.record(None, sigs, now)      # the newest of the item's signals (the last given of those at the same time)
                try:
                    with _writes.ITEM_LOCK:
                        it = _svcstore._load(gid)
                        # read again under the lock: the item may have closed, been put on hold or begun a wait since the tie was made (the same test as _merge_tied)
                        if it.get("status") == "open" and _event_item_live(it, now) and newest is not None and _lastact.apply(it, [newest], now):
                            _writes.save(gid, it, activity=_activity.BOOKKEEPING)
                            saved.append(gid)
                except Exception as e:  # noqa: BLE001  — one item never stops the others
                    print(f"last activity: {gid} not saved for {key}: {e.__class__.__name__}: {str(e)[:120]}", file=sys.stderr, flush=True)
        if (new != off or rows) and not _elog.save_offset(new):
            print("last activity: offset not saved", file=sys.stderr, flush=True)
        return saved
    except Exception as e:  # noqa: BLE001  — groundwork for a later part: nothing raises out of the tick
        print(f"last activity: pass failed: {e.__class__.__name__}: {str(e)[:120]}", file=sys.stderr, flush=True)
        return []
