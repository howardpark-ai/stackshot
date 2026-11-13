"""writes.py: the one write path of an item: the item lock, the save and what a write must do differently (the write context).

`ITEM_LOCK` is the one lock every read-change-save of an item takes (a session's update, an answer, a wake, a pass that rewrites items); it is an RLock, so a writer that holds it may call another writer that
takes it again on the same thread (an update that saves twice, a pass that calls a write). `save` is the one writer of an item's file: it compares the item with the file it is about to replace,
brings the stored fields into agreement (the mover, his step on the checklist, the ask's record, the hand-off record, the phase), stamps who wrote the revision and the clocks, writes the file, and then
records the change where others read it (the For you list, the Landed list, the search index, the hand-back line, the GitHub mirror, the pending answer). The order of those steps is part of what a save
means and is kept as it was in server.py.

What a write must do differently from the usual one is the `WriteContext` passed to `save`: `settle`. It was a thread-local flag set around the save (`_NO_SETTLE`); it is an argument now, so
nothing a save does depends on what else the thread did before it. The per-write flags the gates read (`SESSION_NEXT`, `QUESTION`, `REFORMAT`, `TERMINAL_ROW`) live here too, as thread-locals the routes and tools set
with `.on` around a write (`session_write` is the create and update tools' own); they are read by the create and update tools and the gates, never by this save. The flags of the telling (`CLOSE_WAS`, `FRONT_HINT`,
`MENTIONED`, `HO_STATE`) are on service/telling.py.

The steps that still read server.py's own code (the mover's settling, his step, the ask record, the three hand-off steps, the phase, the For you and Landed lists, the search index, the
hand-back line, the pending answer) are reached through `Steps`, which server.py fills once with `install`: this module cannot import server.py (the surface sits above it), and each of those
functions leaves `Steps` when its area moves under service/. Steps are looked up when a save runs, so a suite that replaces one on server.py still reaches the save.

Imports point down only: this module imports the domain and core, and the store's readers beside it (service/store.py), never web/."""
from __future__ import annotations

import contextlib
import json
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core import readonly as _ro
from stackshot.core import store as _cstore
from stackshot.core.instance import NAME
from stackshot.fleet.sessions_registry import _session_label
from stackshot.github import ghsync as _gh
from stackshot.model import activity as _activity
from stackshot.model import item_project as _ip
from stackshot.model import last_activity as _lastact
from stackshot.model import migration as _mig
from stackshot.model import model as _model
from stackshot.model import progress as _progress
from stackshot.router import routing as _routing
from stackshot.service.store import _path

ITEM_LOCK = threading.RLock()      # a session's update and a failed delivery's record read, change and save an item under it

# The per-write flags: set (`.on`) by a route or a tool around its write, read by the gates and the create and update services while that write runs. A flag is never rebound, so a name taken from this module stays the flag.
SESSION_NEXT = threading.local()  # around the create and update tools' own calls: only a session's write is judged by the write checks of Next (N1, N3, N6; next_rules.py), and by the bare-URL check; a script's, the re-bullet route's and the minute loop's writes are not
TERMINAL_ROW = threading.local()  # set by the terminal-prompt and job-gap routes around their writes: the row is a script's notification of its own, so it owes no page and no session is told of it (create_item, _update, the tell_* notices; a job-gap item's builder is told by the needs notice of its create, which this does not stop)
QUESTION = threading.local()     # set by the script question route around its create: guard 11 (alarming words) does not judge a headless run's own question text, so it is never stranded on a wording refusal
REFORMAT = threading.local()    # set by the re-bullet route around its update: a description written in bullets with the same content is a filing edit, no state change


def session_next() -> bool:
    """Is this the create or update tool's own call (a session's write)?"""
    return bool(getattr(SESSION_NEXT, "on", False))


def question() -> bool:
    """Is this the script question route's create?"""
    return bool(getattr(QUESTION, "on", False))


def reformat() -> bool:
    """Is this the re-bullet route's update?"""
    return bool(getattr(REFORMAT, "on", False))


def terminal_row() -> bool:
    """Is this the terminal prompt's or the job-gap route's write?"""
    return bool(getattr(TERMINAL_ROW, "on", False))


@contextlib.contextmanager
def session_write():
    """Marks the create or update tool's own call as a session's write for the write checks of Next (SESSION_NEXT); restored on exit."""
    was = getattr(SESSION_NEXT, "on", False)
    SESSION_NEXT.on = True
    try:
        yield
    finally:
        SESSION_NEXT.on = was

SETTLE_NAMED = "named"      # settle: an update that names the mover itself: the save's mover settling leaves it as the write has it, and his step on the checklist still follows the stored fields
SETTLE_QUIET = "quiet"      # settle: a write that only files, re-bullets or confirms: no mover is settled and no hand-off record is ended


@dataclass(frozen=True)
class WriteContext:
    """What one save must do differently from the usual one, passed to `save` instead of set on the thread around it.

    settle: "" = a save settles the mover and his step and ends the hand-off records it should (every save that is not one of the two below, the server's own passes included);
    SETTLE_NAMED = the write names the mover itself, so the mover is left as written, but his step on the checklist follows the stored fields; SETTLE_QUIET = the write only files or confirms, so neither the
    mover nor the checklist is touched and no hand-off record is ended (unless the save carries an `author`, the owner's own answer)."""
    settle: str = ""

    def __post_init__(self) -> None:
        if self.settle not in ("", SETTLE_NAMED, SETTLE_QUIET):
            raise ValueError(f"WriteContext.settle must be '', {SETTLE_NAMED!r} or {SETTLE_QUIET!r}, not {self.settle!r}")


PLAIN = WriteContext()                          # the usual save
NAMED = WriteContext(settle=SETTLE_NAMED)       # an update that names the mover
QUIET = WriteContext(settle=SETTLE_QUIET)       # a write that only files, re-bullets or confirms


@dataclass(frozen=True)
class Steps:
    """The steps of a save whose code is still server.py's, in the order `save` calls them; server.py builds one and gives it to `install`. A step that fails inside is its own to catch (each one
    prints its failure and never fails the write), as before. `quiet` is True for a QUIET write."""
    settle_mover: Callable[[dict[str, Any], "dict[str, Any] | None"], Any]
    owner_steps: Callable[[dict[str, Any], "dict[str, Any] | None", str, "tuple[str, str] | None"], Any]
    ask_stamp: Callable[[dict[str, Any], "dict[str, Any] | None", str], Any]
    handoff_on_save: Callable[[str, "dict[str, Any] | None", dict[str, Any], str, "tuple[str, str] | None"], Any]
    handoff_his_over: Callable[[str, dict[str, Any], "tuple[str, str] | None", bool], Any]
    handoff_follow: Callable[[str, "dict[str, Any] | None", dict[str, Any], str, "tuple[str, str] | None", bool], Any]
    phase_stamp: Callable[[str, dict[str, Any]], Any]
    foryou_on_save: Callable[[str, "dict[str, Any] | None", dict[str, Any], str, bool], Any]
    landed_on_save: Callable[[str, "dict[str, Any] | None", dict[str, Any], str, bool], Any]
    search_touch: Callable[[str], Any]
    handback_drop: Callable[[str, str], Any]
    answer_ack: Callable[[str, str], Any]


_steps: Steps | None = None


def install(steps: Steps) -> None:
    """Give the save the steps that are still server.py's (once, at its import)."""
    global _steps
    _steps = steps


def record_writer(item: dict[str, Any], writer: str, author: tuple[str, str] | None) -> None:
    """Stamp the item with who is writing this revision (the store keeps every revision as a commit of the item's file, and until now none said who wrote it,
    every commit being the server's). `written_by` is the name: the session's name as the fleet tool shows it, the owner's name for his answer on the board (`author`) or a
    script's label; a server save (no writer: a wake, an idle mark, a migration) leaves the item untouched, so the hand-off clock reads the last real writer; `written_by_id` is the session's transcript or permanent id when the writer
    is one (the owner's board answer: `board`), absent otherwise, so a later step compares by id and shows by name. A revision with no field predates this."""
    if not author and not writer:      # the server's own bookkeeping (a wake, an idle mark, a check close, a migration): the item is left exactly as it is, the last real writer stays
        return
    if author:
        who, wid = author[0], author[1]
    else:
        who, wid = _session_label(writer) or writer, (writer if _anc.is_id(writer) else "")
    item["written_by"] = who
    item["written_at"] = time.time()      # when this stamp was written; `updated` also moves for a server save that leaves the stamp alone, so "did this session write the item since T" reads this
    if wid:
        item["written_by_id"] = wid
    else:
        item.pop("written_by_id", None)


def audit_writer_names() -> set[str]:
    """The names whose writes are an audit's own and never move an item's `activity` clock (activity.counts): the audit agent, the label the audit's cue is pushed as, the instance's own
    name and the router's ruling name, and the migration's label."""
    out = {NAME, _routing.AUTO_RULER, _mig.AUTHOR, "stackshot audit"}
    try:
        out.add(_cfg.audit_agent())
    except Exception:  # noqa: BLE001  — a config that does not read leaves the fixed names
        pass
    return out


def _stamp_activity(item: dict[str, Any], before: dict[str, Any] | None, writer: str, author: tuple[str, str] | None, kind: str, when: float | None = None) -> None:
    """Move the item's `activity` clock when this save is real activity, seed it for an item that has none (activity.stamp). A failure here never fails the write."""
    try:
        k = _activity.kind_of(writer, author, kind)
        who = [writer, _session_label(writer) if writer else "", author[0] if author else ""]
        _activity.stamp(item, before, time.time(), k, who, audit_writer_names(), when=when)
    except Exception as e:  # noqa: BLE001  — the clock is groundwork for a later pass; a write is never refused for it
        print(f"activity: {item.get('id')} clock not stamped: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


def _stamp_progress(item: dict[str, Any], before: dict[str, Any] | None, writer: str = "", author: tuple[str, str] | None = None, kind: str = "") -> None:
    """Move the item's `progress` clock when this save is progress (a step marked done or dropped, a state change, a merge recorded), seed it for an item that has none (progress.stamp). Called
    once the fields are final, after the phase is stamped. A save that is no one's write about the work (the same test as the activity clock's: a migration, an audit, the server's bookkeeping) moves the
    clock only by a status or phase change. A failure here never fails the write."""
    try:
        who = [writer, _session_label(writer) if writer else "", author[0] if author else ""]
        real = _activity.counts(_activity.kind_of(writer, author, kind), who, audit_writer_names())
        _progress.stamp(item, before, time.time(), real)
    except Exception as e:  # noqa: BLE001  — the clock is groundwork for the hand-up of a stuck item; a write is never refused for it
        print(f"progress: {item.get('id')} clock not stamped: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


def _is_mover(item: dict[str, Any], writer: str) -> bool:
    """Is `writer` (a session's name or id) the item's mover as the item stands now: the model's mover while it is alive, the post-wake mover while it waits, else the stored mover (the board's own reading,
    tools/board_report.mover_of)? A name, an alias and an id of one session are one mover (`anchors.canonical`: the registry's permanent id, else the fleet's). No writer, no mover or the owner as mover is no."""
    who = str(writer or "").strip()
    if not who:
        return False
    mod = _model.derive(item)
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    mover = (mod.mover if mod.state == _model.ALIVE else (mod.wait.mover if mod.wait else "")) or _model.clean(meta.get("mover"))
    if not mover or _model.is_owner(mover):
        return False
    nm = _anc.names()
    return bool({who.casefold(), _anc.canonical(who, nm).casefold()} & {mover.casefold(), _anc.canonical(mover, nm).casefold()})


def _update_signals(item: dict[str, Any], before: dict[str, Any] | None, writer: str, now: float) -> list[dict[str, Any]]:
    """The `update` signals of a save that is a session's real write as the item's mover: what `last_activity.update_signals` finds, kept only when `writer` is the mover (asked last: it reads the fleet's sessions).
    [] for anything else, and for a save whose item or earlier version is not what it should be; it never raises."""
    try:
        meta = item.get("metadata")
        sigs = _lastact.update_signals(before.get("metadata") if isinstance(before, dict) else None, meta if isinstance(meta, dict) else None, now)
        return sigs if sigs and _is_mover(item, writer) else []
    except Exception as e:  # noqa: BLE001  — never takes the step, state or merge stamp of the same save with it
        print(f"last activity: {item.get('id')} update not recorded: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return []


def _stamp_last_activity(item: dict[str, Any], before: dict[str, Any] | None, writer: str = "", author: tuple[str, str] | None = None, kind: str = "") -> None:
    """Record in `metadata.last_activity` what this save did that is visible activity (last_activity.stamp: the progress clock's own test, with the words for it); the events on a tied pull request come
    through `_event_activity_tick`. A session's own write as the item's mover that sets a status line (the update tool's `work`) to text different from the step's previous status is an `update`, the item's
    hourly update, counted here beside the audit's line (`last_activity.update_signals`): the same text again, a write by anyone else (a front agent relaying, the owner's answer, the audit) and the server's own
    save are none. It only records, with no publish of its own (the home page is kept for 30 s, then drawn again, and picks the record up); the On agent rows and the item page show it. A failure here never fails the write."""
    try:
        who = [writer, _session_label(writer) if writer else "", author[0] if author else ""]
        k = _activity.kind_of(writer, author, kind)
        real = _activity.counts(k, who, audit_writer_names())
        now = time.time()
        extra = _update_signals(item, before, writer, now) if real and k == _activity.WRITE and item.get("status") == "open" else []
        _lastact.stamp(item, before, now, real, extra)
    except Exception as e:  # noqa: BLE001  — groundwork for a later part; a write is never refused for it
        print(f"last activity: {item.get('id')} not recorded: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


def save(gid: str, item: dict[str, Any], writer: str = "", note: str = "", author: tuple[str, str] | None = None, mirror: bool = True, background: bool = False, activity: str = "", activity_at: float | None = None,
         ctx: WriteContext = PLAIN) -> None:
    """Write the item's file. `writer` is the session whose write this is (a name or id; '' = the server's own act: a wake,
    a release, a migration). `note` is the server's own line on one of its passes that is an event on the item
    (a wake, a release from hold, a recycle done) and `author` = (name, id) of a write that is neither a session's nor the server's
    own pass: only the owner's answer on the board, `(OWNER, "board")`. Neither reaches GitHub since an earlier change (the issue mirror carries the subject, open or
    closed and the description alone, with no comment); the arguments stay for the callers. `author` still stamps the revision (record_writer). A session's write to an item settles an answer it was told of (the pending answer's ack). `ctx`: what this write
    must do differently (WriteContext): an update that names the mover, or only files, passes NAMED or QUIET, and the save leaves the mover as the write has it (his step on the checklist is still made or dropped when the update names the mover; a filing save leaves it).
    `mirror` False: no job for the GitHub queue (the migration
    pass writes an item that has no issue so: a "changed" job for such an item would create one). `background` True: a bulk repair's save, whose description sync
    is queued behind every live job (ghsync.on_change) and stays inside the reserve a live write keeps. `activity` files the save under an activity kind (activity.py) when the writer
    alone does not say: the confirm tool (`confirm`), an anchor event (`event`), a message written onto the item (`message`), the owner's comment on GitHub (`answer`); left blank a session's
    write is a `write`, the owner's board answer an `answer`, and a save with no writer the server's own bookkeeping, which does not move the item's `activity` clock. `activity_at`: when the
    activity happened, for one the server reads later (the owner's GitHub comment): the clock takes that time, never later than now and never earlier than it already read (activity.stamp)."""
    steps = _steps
    if steps is None:
        raise RuntimeError("the write path has no steps installed (server.py installs them at its import)")
    _ro.guard("item write")                   # the lowest store-write layer; a warm standby copy never writes an item
    writer = str(writer or "").strip()        # a blank writer is the server's own act, never an author-less `[author: unknown · -]`
    p = _path(gid)
    p.parent.mkdir(parents=True, exist_ok=True)
    before = None
    if p.exists():                            # the version before, for the comment that says what changed; the For you list reads it too (a state change is an event)
        try:
            with open(p, encoding="utf-8") as f:
                before = json.load(f)
            _ip.read_through(before)              # read as `item` was: through the project's id, so a page that moved is no re-file of the item
        except Exception:  # noqa: BLE001
            before = None
    if not ctx.settle:
        steps.settle_mover(item, before)      # an item that waits on him has him as mover (the agent in then), and the mover he held goes back when it leaves his state: for every save, the server's own included
        steps.owner_steps(item, before, writer, author)      # N2/N4/N5: an item that waits on him has his open step on its checklist, and one that stops waiting on him by a session's write loses it: every save, the server's own included
    elif ctx.settle == SETTLE_NAMED:
        steps.owner_steps(item, before, writer, author)      # an update that names the mover leaves the mover as written, but his step still follows the stored fields (a step= with a named mover in one call must leave a step of his for his note to tick); only a write that merely files or confirms (QUIET) leaves the checklist alone
    quiet = ctx.settle == SETTLE_QUIET
    record_writer(item, writer, author)     # every revision names who wrote it (the hand-off clock reads it)
    _stamp_activity(item, before, writer, author, activity, activity_at)      # the activity clock: only a real write about the work moves it (an audit's write and a bare confirm do not)
    steps.ask_stamp(item, before, writer)      # who wrote the ask and when (metadata.ask_rec), on a save that changes it
    steps.handoff_on_save(gid, before, item, writer, author)      # step 2: the writer touches the item (a hand-off to it is taken); a new mover is a hand-off record
    steps.handoff_his_over(gid, item, author, quiet)     # his hand-off ends with his answer, or when the item is no longer his to move
    steps.handoff_follow(gid, before, item, writer, author, quiet)      # the record follows the mover whatever changed it: the server's own save, a script's, his answer; a stale open record ends
    steps.phase_stamp(gid, item)      # last, once the fields are final: the phase the board shows the item as (alive or waiting) is stored beside the fields it is read from
    _stamp_progress(item, before, writer, author, activity)      # the progress clock reads the phase just stored: only a step marked, a state change or a merge moves it
    _stamp_last_activity(item, before, writer, author, activity)      # the last-activity record takes the same signals, with the words for them
    _ip.stamp(item.get("metadata"))      # and the project's permanent id beside the page it is filed on (a key that names a project sets it)
    _cstore._write_item(p, item)
    try:
        steps.foryou_on_save(gid, before, item, writer, bool(author and author[1] == "board"))
    except Exception as e:  # noqa: BLE001  — the list never fails a write
        print(f"for-you: {gid} not recorded: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    try:
        steps.landed_on_save(gid, before, item, writer, bool(author and author[1] == "board"))
    except Exception as e:  # noqa: BLE001  — the list never fails a write
        print(f"landed: {gid} not recorded: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    steps.search_touch(gid)                       # step 3: the search index takes the item a moment later, in its own thread (never in this write's time)
    if item.get("status") == "completed":
        try:
            steps.handback_drop(gid, "the item closed")      # the keeper hears the close alone
        except Exception as e:  # noqa: BLE001  — never fails a write
            print(f"hand-back: {gid} held line not dropped: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    if mirror and _gh.enabled():
        try:
            _gh.on_change(gid, before, item, background=background)     # a job only when the subject, open or closed, or the description changed; no comment
        except Exception as e:  # noqa: BLE001  — the mirror never fails a write
            print(f"ghsync: {gid} not queued: {e}", file=sys.stderr, flush=True)
    if writer:
        try:
            steps.answer_ack(gid, writer)
        except Exception as e:  # noqa: BLE001  — the escalation's bookkeeping never fails a write
            print(f"answer: {gid} ack not recorded: {e}", file=sys.stderr, flush=True)
