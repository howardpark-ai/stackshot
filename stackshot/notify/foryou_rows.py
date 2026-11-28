"""foryou_rows.py: the rows the For you list makes, the rules: whether the owner watches an item (`watched`), the key of one event (`key`, `key_of`), the rows a change of an item makes (`changes`), the Landed list's
record beside them (`landing`, `close_record`) and the due-date look (`due_state`, `due_what`), all on the item as the file held it and as it is now.

A notice for the owner is a row in the For you list (foryou.py: the board's section, `client.py get for-you` for the fleet tool's web server), never a front agent's turn. A row is made for a WATCHED
item's state change he should see: a close, a reopen, a move to needs=decision, a done check that can never pass, and a due date within 24 h (the due-date look). A failed release makes no row
(_client_post `message`). Watched by default: an item with his words on it (a `said` entry, a board or GitHub answer, a quote in the text; there is no separate creator field, and an item he asked for
carries his words) and an item that needs his decision. His own setting on the item's page wins: Mute stops its rows, Watch adds an item that is not watched. The rows are made where the change is saved
(`writes.save` compares the file before and after, so every path that changes an item counts: a session's write, the server's own pass, his board answer), never where a session's message is sent: a message
a session sends on purpose with [for <owner>] (a decision or a go-ahead asked for) is not touched. A decision row goes when the decision leaves the item's needs (answered, or closed). The urgent rows (a due
date within 24 h of an item that is his move) are also posted once to Slack (service/foryou_slack.py, with the queue and the worker thread that post it).

This module reads no store, no clock, no session and no page: the flag, the session's name, the page's ask parser and the words for a date come in as arguments, and the file, the saves and the pass that
make the rows are service/foryou_events.py's."""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable

from stackshot.model import title_label as _tl
from stackshot.model.bullet_text import _clip_line
from stackshot.model import member_gates as _mgates
from stackshot.model.needs import _waits_decision
from stackshot.model.said import _owner_words
from stackshot.waits import waiting as _wt

EVERY = 300.0        # seconds between passes of the due-date look; the dates pass opens the gate itself, every ten minutes
DUE_S = 24 * 3600.0  # "within 24 h": a due date whose end is at most this far ahead, or past by less than this
WHAT = 300           # characters of a row's line


def watched(mode: str, item: dict[str, Any]) -> tuple[bool, str]:
    """Is this item one he watches, and why: his own flag `mode` ("mute", "watch" or "") first, then the defaults. → (watched, the reason in words)."""
    if mode == "mute":
        return False, "muted by him"
    if mode == "watch":
        return True, "watched by him"
    meta = item.get("metadata") or {}
    if item.get("status") == "open" and _waits_decision(meta):
        return True, "it needs his decision"
    if _owner_words(item):
        return True, "his words are on it"
    if any(isinstance(a, dict) and a.get("via") != "mail" and _mgates.owners(a) for a in (meta.get("answers") if isinstance(meta.get("answers"), list) else [])):      # a step the server ticked on a mail is not an answer of his
        return True, "he answered on it"
    return False, "not watched"


def stamp(item: dict[str, Any]) -> int:
    """The state clock of an item, in whole seconds: what tells one close from the next (0 when it has none)."""
    try:
        return int(float(item.get("state_updated") or item.get("updated") or 0))
    except (TypeError, ValueError):
        return 0


def key(gid: str, kind: str, item: dict[str, Any]) -> str:
    """The key of one event on an item: the same event never makes two rows (foryou.add). The state clock tells one close from the next."""
    return f"{gid}:{kind}:{stamp(item)}"


def key_of(gid: str, kind: str, disc: Any) -> str:
    """The key a row is stored under: the item, the kind of event and what tells one event of that kind from the next (`disc`: a close's state clock, a due date as stored)."""
    return f"{gid}:{kind}:{disc}"


def row_fields(gid: str, item: dict[str, Any], kind: str, what: str, disc: Any, shown: str, url: str, urgent: bool = False) -> dict[str, Any]:
    """The fields of one row for an event on an item, for foryou.add: the item as a session reads it (`shown`), the item's page (`url`), the line cut to WHAT characters."""
    meta = item.get("metadata") or {}
    return {"key": key_of(gid, kind, disc), "kind": kind, "gid": gid, "item": shown, "project": str(meta.get("project") or ""),
            "what": _clip_line(what, WHAT), "url": url, "urgent": urgent}


def decision_left(before: dict[str, Any] | None, item: dict[str, Any]) -> bool:
    """Did the item stop waiting on his decision with this change (it was answered, or it closed)? Its decision row then leaves the list."""
    b = before or {}
    return b.get("status") == "open" and _waits_decision(b.get("metadata") or {}) and not (item.get("status") == "open" and _waits_decision(item.get("metadata") or {}))


def changes(before: dict[str, Any] | None, item: dict[str, Any], who: str, shown: Callable[[str], str], parse_ask: Callable[[str], Any],
            grp: Callable[[dict[str, Any]], str] | None = None, grp_prefix: Callable[[dict[str, Any]], str] | None = None) -> list[tuple[str, str, Any]]:
    """The rows a change of an item makes, in order: [(kind, line, discriminator)]. `before` is the item as the file held it (None for a create). `who` is the name of whoever wrote it, `shown` turns a store id
    into the id a session reads, `parse_ask` is the page's parser of an ask line (None when it is misshaped), `grp` is the item's title as a line shows it, group and all, with no tag
    (anchors.group_title; a caller with no project reading falls back to the stored subject with its tag taken off), and `grp_prefix` is the group alone, "<group> · " or ""
    (anchors.item_group), for the decision row's own decide text, which is not the title but still wants the group beside it."""
    b = before or {}
    bm, am = b.get("metadata") or {}, item.get("metadata") or {}
    bs, as_ = b.get("status"), item.get("status")
    was_dec = bs == "open" and _waits_decision(bm)
    is_dec = as_ == "open" and _waits_decision(am)
    _subj: list[str] = []
    def subject() -> str:                   # built only once a row is actually going to be made (grp may read the project files: never pay for a save that makes no row)
        if not _subj:
            _subj.append(grp(item) if grp else _tl.bare(item.get("subject")))
        return _subj[0]
    out: list[tuple[str, str, Any]] = []
    if as_ == "completed" and bs == "open":
        outcome, sup, reason = str(am.get("outcome") or "done"), str(am.get("superseded_by") or ""), str(am.get("reason") or "").strip()
        out.append(("closed", f"closed by {who} ({outcome}{' by ' + shown(sup) if sup else ''}): {subject()}" + (f" — {reason}" if reason else ""), stamp(item)))
    elif as_ == "open" and bs == "completed":
        out.append(("reopened", f"reopened by {who}: {subject()}", stamp(item)))
    if is_dec and not was_dec:
        pa = parse_ask(str(am.get("ask") or ""))
        decide = (grp_prefix(item) if grp_prefix else "") + pa["decide"] if pa else subject()
        out.append(("decision", "needs your decision: " + decide, stamp(item)))
    wf, wb = am.get("wait_failed"), bm.get("wait_failed")
    if as_ == "open" and isinstance(wf, dict) and wf and wf != wb:
        out.append(("check_failed", f"{wf.get('what') or 'a wait'} can no longer end: {wf.get('why') or 'it failed'} ({subject()})",
                    int(float(wf.get("at") or 0)) or stamp(item)))
    return out


def landing(before: dict[str, Any] | None, item: dict[str, Any]) -> str:
    """What a change of an item does to the Landed list: "close" (an open item was closed: a record, unless the owner made the close), "reopen" (a closed item is open again: its record goes) or ""."""
    bs, as_ = (before or {}).get("status"), item.get("status")
    if as_ == "completed" and bs == "open":
        return "close"
    if as_ == "open" and bs == "completed":
        return "reopen"
    return ""


def close_record(item: dict[str, Any], now: float) -> tuple[float, str, str]:
    """The Landed record of a close: (the close's clock, the outcome, the item's project); the clock is the item's state clock, else `now`."""
    am = item.get("metadata") or {}
    return stamp(item) or now, str(am.get("outcome") or "done"), str(am.get("project") or "")


def due_state(item: dict[str, Any], now: float) -> tuple[str, str] | None:
    """The due-date look at one item: an open item whose due date ends within 24 h, or ended less than 24 h ago → ("due" or "overdue since", the due date as stored); else None. A due date longer past is
    not looked at: the first pass after a deploy must not raise every old overdue item. The due date is a day: its end is when it is due."""
    due = str((item.get("metadata") or {}).get("due") or "")
    if item.get("status") != "open" or not due:
        return None
    end = _wt.due_epoch(due)
    if end is None or not -DUE_S < end - now <= DUE_S:
        return None
    return ("overdue since" if end <= now else "due"), due


def due_day(due: str) -> dt.date:
    """The day of a stored due date. ValueError when it is not one."""
    return dt.date.fromisoformat(due[:10])


def due_what(when: str, day_words: str, title: Any) -> str:
    """The line of a due-date row: "due Thu Mar 5th: <group · title, no tag>". `title` is the caller's group_title(item), not the raw subject."""
    return f"{when} {day_words}: {title or ''}"
