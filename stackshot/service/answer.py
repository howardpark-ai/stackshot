"""answer.py: the owner's answer from the board: its record, its delivery, the settle of a pending one and the escalation.

`_answer` records one answer (a decision, a comment, a Done or a note on his step) on the item under the item lock and then the answer lock, in the order every writer takes them, and hands the item over; `_answer_deliver` tells the item's mover and every
session named in its needs, one line each, through the notice path, and then the item's contact and the front agents he is talking to now, the same line once each (a front agent's as a held line for its next turn); `_answer_ack` settles the answer pending on an item when a session that was told of it writes to the item; `_answer_tick` is the escalation pass of the minute set: a decision
answer that no session it was sent to has followed with a write within `_ANSWER_ESCALATE_S` goes to the project's keeper, once. The hand-over after an answer is service/answer_handover.py's.

A service module: it reads the store and writes an item through `writes.save`, under the locks it takes itself. The answer form's lock, its limits, the file of pending answers and its words (web/answers.py), the renderer's reader of the
options, its words for a time and the board's time zone, the debounced publish and the session id of a name are the surface's, reached through service/save_hooks.py; the lock is looked up on web/answers.py each time it is taken, so a suite that
puts a spy in its place sets it there (`answers._ANSWER_LOCK = ...`). A suite that replaces one of these functions sets it on this module (and `time` here, since this module reads its own).

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import contextlib
import datetime as dt
import sys
import time
from typing import Any, Iterator

from fastmcp.exceptions import ToolError

from stackshot.core import config as _cfg
from stackshot.core import members as _members
from stackshot.core.instance import NAME, OWNER
from stackshot.fleet import sessions_registry as _sr
from stackshot.github import ghsync as _gh
from stackshot.model import ask_leaves as _askl
from stackshot.model import holders as _holders
from stackshot.model import model as _model
from stackshot.model import note_read as _noteread
from stackshot.model import owner_steps as _hs
from stackshot.model import states as _states
from stackshot.model import steps as _steps
from stackshot.model.bullet_text import _clip_line
from stackshot.model.ids import _item_url
from stackshot.model.needs import _canon_needs, _needs_kinds, _needs_of, _needs_sessions, _needs_store
from stackshot.projects import pages as _pages
from stackshot.service import answer_handover as _handover
from stackshot.service import contacts as _contacts
from stackshot.service import item_read as _item_read
from stackshot.service import owner_words as _owner_words
from stackshot.service import pane_recovery as _pane_recovery
from stackshot.service import runner as _runner
from stackshot.service import store as _svcstore
from stackshot.service import telling as _telling
from stackshot.service import wait_gates as _wait_gates
from stackshot.service import wakes as _wakes
from stackshot.service import writes as _writes
from stackshot.service.save_hooks import hooks as _hooks
from stackshot.waits import held as _held
from stackshot.waits import watchers as _watch

_FOR_OWNER = f"[for {OWNER}]"      # the mark a message to a front agent carries on its first line ("[for <owner>]" on the owner's instance), as web/tools/text.py holds it


def _session_id(value: str) -> str:
    """The session id of a name, as the server reads it (service/save_hooks.py's `session_id` hook)."""
    return _hooks().session_id(value)


def _answers() -> Any:
    """web/answers.py, looked up when it is read (service/save_hooks.py's `answers_mod` hook): the answer form's lock, its limits, the file of pending answers and its words."""
    return _hooks().answers_mod()


def _answer_ack(gid: str, writer: str) -> None:
    """A session's write to an item settles the decision answer pending on it when that session was told of the answer (its
    mover, or a session named in its needs): the keeper is then not told."""
    with _answers()._ANSWER_LOCK:
        st = _answers()._answers_load()
        e = st.get(gid)
        if not e or _session_id(writer) not in (e.get("told") or []):
            return
        st.pop(gid, None)
        _answers()._answers_save(st)


def _tell_aside(gid: str, sid: str, line: str, tail: str, contact: bool = False) -> bool:
    """His answer for a session that only keeps up with the item (its contact, a front agent he is talking to): a front agent gets it through the front gate as a held line, which rides its next turn, starts none and carries no
    mark (`telling.front_fyi`; where the gate holds it back, because its hook cannot fetch held lines, the gate says so in the routing log and, for the contact, the board's History line stays). Only the contact leaves a History line on the
    item: a front agent of another project that he happens to be talking to keeps the routing-log line alone. It fails closed: a session that is a front agent, or whose role could not be read, is never sent the plain push; when the gate does not handle
    it (it failed) the line goes onto the item's History for the contact and nobody is told. Any other session gets the plain send, as the sessions in the needs do. A held line is cut at `held.LINE_MAX`: the item's link, the tail, is kept and his words are cut.
    → whether the session was handed the line (sent, or filed for its next turn)."""
    if _telling.front_role(sid) is False:
        _telling.tell_woken(gid, sid, line, tag="answer")
        return True
    fyi = line if len(line) <= _held.LINE_MAX or not line.endswith(tail) else line[:-len(tail)][:max(0, _held.LINE_MAX - len(tail) - 2)].rstrip() + " …" + tail
    res = _telling.front_fyi(sid, fyi, gid=gid, board=contact)
    if res != ("", ""):
        return res[0] == "fyi"
    why = "the front gate could not file it"
    if contact:
        _telling._front_board_line(gid, sid, False, why, line)
    _telling._front_held_log(gid, sid, "message", f"archived: front agent, {why} (message)", line)
    return False


def _record_told(gid: str, rec: dict[str, Any], ids: list[str]) -> None:
    """Keep the sessions his answer was handed to on the answer's own record (`metadata.answers[].told`, the session ids), so an update by one of them is not told his answer again, whatever came of the pending
    answer since (a first told session's write settles it, the escalation drops it, and a comment or a Done has none). A server save like the front gate's History line: no writer, no clock moves, nothing posted
    to the issue. The caller holds the item lock. Never raises."""
    if not ids:
        return
    try:
        it = _svcstore._load(gid)
        meta = dict(it.get("metadata") or {})
        recs = [dict(a) if isinstance(a, dict) else a for a in (meta.get("answers") or [])]
        mine = next((a for a in reversed(recs) if isinstance(a, dict) and a.get("ts") == rec.get("ts")), None)
        if mine is None:
            return
        mine["told"] = list(ids)
        meta["answers"] = recs
        it["metadata"] = meta
        _writes.save(gid, it, note="who his answer was handed to")
    except Exception as e:  # noqa: BLE001  — a record kept for a reply line: the answer stands without it
        print(f"answer: {gid} told names not kept: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


def _also_reached(meta: dict[str, Any]) -> list[tuple[str, bool]]:
    """The sessions beside the item's mover, its needs and its then-mover that hear his answer: the item's contact (`_contact_of`: the stored one while it is a front agent, else the project's -main agent) and every front
    agent he is in conversation with now (`telling.present_fronts`: his last message in its pane within the presence window), whether or not the item names it. (name, is the item's contact), contact first. Never raises."""
    out: list[tuple[str, bool]] = []
    try:
        c = _contacts._contact_of(meta)
        if c:
            out.append((c, True))
    except Exception as e:  # noqa: BLE001  — a contact that cannot be read leaves that line out; the answer is saved
        print(f"answer: contact not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    try:
        out += [(n, False) for n in _telling.present_fronts()]
    except Exception as e:  # noqa: BLE001
        print(f"answer: front agents in conversation not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return out


def _shared_line(gid: str, rec: dict[str, Any], stays: str, done: bool, moved: bool) -> str:
    """The line the sessions get for an answer on a step that more than one member has a part in (a board of several members): who answered, the step, and who it is with now, whether it passed on
    (`moved`) or stayed. A note that does not finish the step (`done` false) is quoted."""
    step = _states.clean(rec.get("step"))
    step = step if len(step) <= 240 else step[:240].rstrip() + " …"
    head = f"[stackshot] {_members.recorded_by(rec)}"
    note = _answers()._answer_words({"text": rec.get("text")}, 300) if rec.get("text") else ""
    if not done:
        return f"{head} sent a note on their step on {_gh.shown(gid)}: {step}. The item stays with {stays}: “{note}”"
    where = f"It goes to {stays} for their step now" if moved else f"The item stays with {stays}"
    return f"{head} did their step on {_gh.shown(gid)}: {step}. {where}" + (f", with their note: “{note}”" if note else "")


def _answer_deliver(gid: str, item: dict[str, Any], rec: dict[str, Any], then: str = "", handed: str = "", also: str = "", said: str = "") -> list[str]:
    """Push the answer to the item's mover (holder, never the creator) and to every session named in its needs, one line each, through the owner-notice
    path (tell_woken). A front-agent mover's line carries the mark a front agent takes. A front agent that is named in needs but neither moves the item nor takes it after the answer (the project's builder does) gets the line held for its
    next turn (_tell_aside), never the plain send that starts one. After a Done or a note on his step (`then` is who the item moved to) the then-mover is told too,
    in its own line: the step he did and "it's yours now". After a decision that handed the item to its stored then-mover (`handed`) the same: its line ends "It's yours now". A line that carries his words (a pick, a note, a Done with
    its note) is pushed to a front agent as ever; the bare hand-over of a Done with no note is a progress notice (telling.tell_own_move) when the item holds nothing for him and the front agent's own named step is not the next one: filed for its next turn, or archived with him away; a front agent whose own step is the item's first open named step is given a turn (`named=True`).
    A line that takes words he typed alone (a comment, an answer with no button) or his note on a step to a session that acts on it also says an answer or result belongs on the item (telling.ON_ITEM); a note the server applied itself and a held
    line for a session that only keeps up (_tell_aside) do not.
    `said` (with it no `then`): the line in place of the ones above, for an answer on a step more than one member has a part in (_shared_line); `also` is the session that takes the item once the members are through, told that line as the then-mover is.
    → the session ids told: one the front gate archived is left out, so its next write is still told his answer."""
    meta = item.get("metadata") or {}
    owner, project = _telling.holder(item), str(meta.get("project") or "")
    verb = "answered" if rec.get("kind") == "decision" else "commented on"
    url = _item_url(gid) or _telling.notice_link(gid)
    done = f"; parked with a wake on {rec['parked']}, set by the server" if rec.get("parked") else ""   # a stored raise's park, applied
    by = _members.recorded_by(rec)      # who answered (the item's member may be another once the answer has moved it)
    line = f"[stackshot] {by} {verb} {_gh.shown(gid)} on the board: {_answers()._answer_words(rec)}{done} → {url}"
    thenid = _session_id(then or handed or also) if (then or handed or also) else ""
    if then:      # a Done: the step he did, then who has the item now and his note
        step = _states.clean(rec.get("step"))
        step = step if len(step) <= 240 else step[:240].rstrip() + " …"
        note = f", with his note: “{_answers()._answer_words({'text': rec.get('text')}, 300)}”" if rec.get("text") else ""
        line = f"[stackshot] {by} did his step on {_gh.shown(gid)}: {step}. It goes to {_sr._session_label(then)} now{note} → {url}"
    judge = ""
    if then and rec.get("kind") == "step-reply":      # his note on the step, sent with no Done: the session that takes the item judges it (only its own line says so)
        line = (f"[stackshot] {by} sent a note on his step on {_gh.shown(gid)}: {step}. It goes to {_sr._session_label(then)} now with his note: "
                f"“{_answers()._answer_words({'text': rec.get('text')}, 300)}” → {url}")
        judge = (f". Judge the note: if it finishes the step, carry on as after a Done; if it is a question or a request, answer it or do it, then hand the item back to {by} "
                 f"with a new step (step=…); if it says he will do the step at a later time, park the item until then "
                 f"(update until=<that time, YYYY-MM-DDTHH:MM {_cfg.tz_abbr()}>, wait_reason=<what it waits on, at least {_cfg.WAIT_GUARD_REASON_MIN} characters>), "
                 f"leave his step open and hand no new step back. {_telling.ON_ITEM}")
    if said:
        line = f"{said} → {url}"
    typed = bool(rec.get("text")) and not rec.get("choice") and not rec.get("applied") and not (rec.get("kind") == "step-reply" and then)      # words alone: a comment, an answer typed with no button, a note on a step the item did not move on from (a note he sends the then-mover says it in `judge`)
    def acting(t: str) -> str:      # the line for a session that acts on his words: typed words alone also say where an answer goes
        body = t.removesuffix(f" → {url}")
        return f"{body}{_telling.on_item(body)} → {url}" if typed else t
    yours = ("" if _answers()._answer_words(rec).rstrip()[-1:] in (".", "!", "?", ")") else ".") + " It's yours now" if handed and not then else ""      # a decision handed over: the mover's line plus the tail
    to_then = lambda t: t.replace(f"It goes to {_sr._session_label(then)} now", "It's yours now", 1).replace(f" → {url}", f"{yours}{judge} → {url}", 1)      # the then-mover's own line: "It's yours now", and for a note the instruction to judge it
    told: list[str] = []
    if judge and rec.get("applied"):      # the server read his note and applied it (note_read.py): the then-mover is told what was done instead of being asked to judge the note
        judge = ". " + str(rec["applied"])
    bare = bool(then or said) and not str(rec.get("text") or "").strip()      # a Done with no note: the hand-over line carries none of his words, only that the item is the then-mover's now
    tried: list[str] = []      # every session a line was sent to, held or not: one line each, and the ones he is in conversation with (below) are not sent it twice
    def tell(sid: str, text: str, yours: bool = False) -> None:
        if yours and bare:      # the bare hand-over ("It's yours now" and nothing of his): to a front agent it is a progress notice when the item holds nothing for him (telling.own_move_kind), filed for its next turn, unless the item's first open named step is that agent's own (`named=True`): its step is the work, and the line starts its turn. A line that carries his words (a pick, a note, a Done with its note) keeps its kind and starts a turn as ever
            _telling.tell_own_move(gid, sid, text, tag="answer", items={gid: item}, named=True)
        else:
            _telling.tell_kind("", gid, sid, text, tag="answer")      # the tag's own kind (exempt); tell_kind also clears the gate's last verdict, read just below
        tried.append(sid)
        if _telling.gate_result()[0] != "held":      # the front gate archived it: nobody was told, so the session is not on the answer's record (it is told his answer at its next write) and the reply does not name it
            told.append(sid)
    if owner:
        oid = _session_id(owner)
        front = _telling.front_keeper(owner, project)[0]
        mine = oid == thenid
        base = acting(to_then(line) if mine else line)
        tell(oid, f"{_FOR_OWNER} {base}" if front else base, yours=mine)
    held: list[str] = []      # front agents named in needs that neither move the item nor take it after this answer: a held line for their next turn (below), never the exempt tell that starts one
    for s in _needs_sessions(meta):
        sid = _session_id(s)
        if sid and sid not in tried:
            if sid != thenid and _handover._builder_for_front(s, meta):      # a front agent of a project whose live builder can take the item; a builderless project, a dead builder and every other session are told as ever
                held.append(s)
                continue
            tell(sid, acting(to_then(line) if sid == thenid else line), yours=sid == thenid)
    if thenid and thenid not in tried:          # the then-mover is neither the mover nor in needs (a stored `then`): it is told, and its write settles the answer
        tell(thenid, acting(to_then(line)), yours=True)
    if not tried and not held:
        print(f"answer: {gid} has no mover and names no session to tell", file=sys.stderr, flush=True)
    seen, handed_to = list(tried), list(told)
    reached = _also_reached(meta)
    reached += [(h, False) for h in held if _session_id(h) not in {_session_id(r) for r, _c in reached}]      # a front agent named in needs hears of it the same way, whether or not it is the contact or present
    for s, is_contact in reached:     # the item's contact and the front agents he is talking to now: his answer is a held line for their next turn, never a turn of its own
        sid = _session_id(s)
        if sid and sid not in seen:
            seen.append(sid)
            if _tell_aside(gid, sid, line, f" → {url}", is_contact):      # not in `told`: a front agent's write must not settle an answer the sessions that hold the item have not acted on
                handed_to.append(sid)
    _record_told(gid, rec, handed_to)
    return told


def _mail_deliver(gid: str, item: dict[str, Any], rec: dict[str, Any], then: str, stays: str = "") -> list[str]:
    """The notice after the server ticked his send step on a mail he sent (`_answer` with via "mail"): a plain line to each session that now has the item, in its own words (the server did it, from a mail: it is not his
    answer and not his note), and only to a background agent. A front agent is told nothing: the board shows the step ticked, and a front turn is for what he must do. A session whose role cannot be read counts as front. `stays`: the member the
    item passed to for their own step (a board of several members), which every line then names. → the session ids told."""
    meta = item.get("metadata") or {}
    project = str(meta.get("project") or "")
    url = _item_url(gid) or _telling.notice_link(gid)
    step = _states.clean(rec.get("step"))
    step = step if len(step) <= 240 else step[:240].rstrip() + " …"
    thenid = _session_id(then) if then else ""
    head = f"[stackshot] The server saw a mail {_members.recorded_by(rec)} sent that fits his step on {_gh.shown(gid)}: {step}. It ticked the step"
    told: list[str] = []
    names = [n for n in (_telling.holder(item), *_needs_sessions(meta), then) if n]
    for n in names:
        sid = _session_id(n)
        if not sid or sid in told or _telling.front_keeper(n, project, strict=True)[0]:
            continue
        goes = f"It goes to {stays} for their step now" if stays else "It's yours now" if sid == thenid else f"It goes to {_sr._session_label(then)} now"
        _telling.tell_woken(gid, sid, f"{head}. {goes} → {url}", tag="answer")
        told.append(sid)
    return told


@contextlib.contextmanager
def _release_dropped(gid: str, drop: list[bool]) -> Iterator[None]:
    """The outermost of `_answer`'s locks: when the body that held them saved the drop of `gid` (`drop` is then not empty), the items that waited on it are released as the body is left, whatever way it is left: a delivery or a
    bookkeeping step that raised after the close was saved must not keep its dependents blocked, and the error goes on up. The release takes the item lock itself and tells the waiters once it is let go: here, no lock is held.
    A release that fails is a stderr line (the close is saved; the error already on its way up is the one the caller sees)."""
    try:
        yield
    finally:
        if drop:
            try:
                _wakes.release_after(gid, "dropped", "", "")
            except Exception as e:  # noqa: BLE001
                print(f"answer: {gid} dropped but its after releases failed: {e}", file=sys.stderr, flush=True)


def _answer(gid: str, choice: str, text: str, act: str, via: str = "board", mail: dict[str, Any] | None = None, by: str = "", ref: str = "") -> str:
    """Record one answer from the board → what happened, the code the page's notice reads: decision | comment | done (sent), askedback (a date button whose note held no date it could read: the note is kept
    and the item asks him back with dates), closednote | stalenote (a note he wrote on a closed item, or on a question that changed, is kept as a comment), closed | stale (no note: nothing written), or empty | emptynote | toolong | nostep | nomover (nothing written; `emptynote` is a Send note on a blank box). A step form has two buttons and an optional note box.
    Done (act=done) is his word that the step is finished (`done`: the item goes to its then-mover, recorded as his answer "Done"); a note in the box stays on that record (`text`) and goes with the Done to the then-mover,
    which is told the step is done and shown the note (`donenote`: the same, and the notice says the note went along). `via` is where the answer came from: "board" for his click, "mail" when the server settles
    his send step because a mail he sent fits it (service/sent_match.py; the answer then reads Done by a mail, and is no word of his for a wait or a date). A mail tick passes `mail` = {"step": the step it was asked about, "since": the item's state clock then, "note": the server's
    own sentence} and no text: under the lock it is dropped, nothing written, unless the item is open, in your-step with that very step and clock (else `changed`, `closed`) and asks nothing beside it (an ask, options or a decision need: `beside`);
    the sentence is kept as `server_note`, never as his `text`; nobody is told it as his answer, a background agent is told plainly what the server did and a front agent nothing; no answer is left pending for escalation. Send note (act=note, text required) is his note on a step that stays open (`stepreply`: kind step-reply, and the item goes to its then-mover too, which judges whether the note finishes the step);
    on an item with no step any more it is a comment, and with no text nothing is written (`emptynote`). `ref` is the reference of the question the form showed (model/ask_ref.py): while the item needs a decision, a pick or an
    answer in the box sent with a reference other than the standing question's is no answer to it (`stale`, nothing written; with a note `stalenote`, the note kept as a comment, as for any answer to a question that changed,
    the pick named without its card letter); with no reference nothing is compared. `by` is the name of the person who answered (the route's signed-in person): it is stored on the answer as `by` (when it is not the first person, whose answers carry none), ticks his
    step and is the save's author; none stands for the first person, and a mail tick records no `by`. A page loaded before this form posts act=send (an empty box is a Done, a note is a step-reply, as ever) or act=comment (a comment only, the step stands).
    On a board of several members a step two members have had a part in (steps.several_hold) is answered member by member. Done ticks the steps that are the answering member's or no one's, never another member's; a member with no part
    left in it (steps.takes_part) gets `nostep`. So does anyone while a question stands on such an item (a page drawn before the question was added: a Done passed on would take the question to the next
    member), on any other item anyone but the member asked while one stands, and a mail tick on a step asked of anyone but the first person. What such a person wrote is kept as a comment.
    An item only one member has had a part in is answered by another member as by that one, recorded under the sender's name. While another member has a part in the step too (_handover._share_step): a Done on the member's own step passes the item to the member of the next open step
    (`done`, `donenote`, `stepreply`), a Done on another's step ticks only theirs and the item stays (`partdone`), a note that does not say done ticks and moves nothing (`comment`), and no session has to be set to take the item.
    """
    choice, text, act = str(choice or "").strip(), str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip(), str(act or "").strip()
    who = " ".join(str(by or "").split()) or OWNER      # the person the answer is recorded under: the route passes the signed-in person's name (`by`); a server tick on a mail, and a caller that names none, stand for the first person
    if len(text) > _answers()._ANSWER_TEXT_MAX:
        return "toolong"
    drop: list[bool] = []       # set once the drop is saved: the release below then runs on every way out of the locks, a delivery or a bookkeeping step that raised included
    with _release_dropped(gid, drop), _writes.ITEM_LOCK, _answers()._ANSWER_LOCK:      # the order every writer takes (an update holds the item lock and then acks here): the item first, the pending answers second; the release is the outermost, so it runs with both let go
        item = _svcstore._load(gid)
        if item.get("status") != "open":
            return _handover._keep_note(gid, item, text, "closednote", choice, "the item is closed", by=who) if text else "closed"      # a note on a closed item is kept as his comment
        meta = dict(item.get("metadata") or {})
        if via == "mail":               # the server's tick: checked again here, under the lock, against the step it was asked about; anything else dropped, nothing written
            if not mail or text or act != "done":
                return "empty"
            try:
                clock_ok = float(item.get("state_updated") or 0) == float(mail.get("since"))
            except (TypeError, ValueError):
                clock_ok = False
            if meta.get("state") != "your-step" or _states.clean(meta.get("step")) != mail.get("step") or not clock_ok:
                return "changed"
            if meta.get("ask") or meta.get("options") or "decision" in _needs_kinds(meta):
                return "beside"         # a question for him stands beside the step: a mail is no answer to it, and a Done would take his decision need off
        if ref and "decision" in _needs_kinds(meta) and (choice or (act == "answer" and text)) and ref != _answers()._question_ref(item):      # the question was rewritten after the page showed it: a label it kept is no pick of the new one
            late = "late, the question was rewritten after the page showed it"      # said in front of a note with no pick too: its reader must not take it for an answer to the new question
            pick = _answers()._posted_name(choice)      # never split against the item's options: they may stand in another order now
            return _handover._keep_note(gid, item, text if pick else f"({late}) {text}", "stalenote", pick, late, by=who) if text else "stale"
        stepped, then, handed, letter, until = False, "", "", "", ""
        if choice:
            choice, letter = _answers()._split_letter(item, choice)      # the board's box posts "B · <label>": the label is the choice, the letter is kept beside it
        if choice:                      # an option's button: only while the item needs his decision, and only one of the item's stored options (Approve and Decline are no fallback); with none stored, Yes or No (the same two the page draws)
            valid = [f[0] for f in _answers()._option_forms(item)] or [o["label"] for o in _hooks().yesno_options(item)]
            if "decision" not in _needs_kinds(meta) or choice not in valid:
                if "decision" in _needs_kinds(meta) or not isinstance(meta.get(_askl.LEFT), dict):
                    return _handover._keep_note(gid, item, text, "stalenote", choice, "late, the item no longer asks this", by=who) if text else "stale"      # his note is kept as a comment; a bare pick on a question that changed is not an answer to the new one
                text, choice, kind = f"(late, on the ask the server took off his move: {_clip_line(str(meta[_askl.LEFT].get('ask') or ''), 120)}) {choice}" + (f" — {text}" if text else ""), "", "comment"      # his pick is kept as his comment, never lost
            else:
                kind = "decision"
        elif act == "done":             # the Done button of a step form (his note in the box, if any, stays on the record as `text`). Only an item that stands in your-step with its step line has one: any other is refused, nothing written
            if meta.get("state") != "your-step" or not _states.clean(meta.get("step")):
                return "nostep"
            kind, choice, stepped = "decision", "Done", True
        elif act == "note":             # the Send note button of a step form: only with text (an empty box is no Done); his note on the step, handed to the then-mover to judge; an item that has no step any more: a comment
            if not text:
                return "emptynote"
            if meta.get("state") == "your-step" and _states.clean(meta.get("step")):
                kind, choice, stepped = "step-reply", "", True
            else:
                kind = "comment"
        elif act == "send":             # the one button of a step form before the two-button form (a page loaded earlier posts it). Empty box = the step is done; a note = his note on the step, handed to the then-mover to judge. An item that has no step any more: a note is a comment, an empty box nothing
            if meta.get("state") == "your-step" and _states.clean(meta.get("step")):
                kind, choice, stepped = ("step-reply", "", True) if text else ("decision", "Done", True)
            elif text:
                kind = "comment"
            else:
                return "nostep"
        elif act in ("answer", "comment") and text:
            kind = "decision" if act == "answer" and "decision" in _needs_kinds(meta) else "comment"      # a stale tab's Send as an answer, after the decision is gone, is a comment: nothing he wrote is lost
        else:
            return "empty"
        member = _model.norm_who(OWNER if via == "mail" else who) if stepped and len(_members.members()) > 1 else ""      # several members: the step is answered member by member (a mail is the first person's)
        asked_of = _steps.member_for(_hs.decide_of(meta.get("ask")), meta) if member and meta.get("ask") and "decision" in _needs_kinds(meta) else ""      # whose question stands on the item
        outsider = bool(member) and not _steps.takes_part(meta, member)
        several = bool(member) and _steps.several_hold(meta)
        if member and (asked_of not in ("", member) or (asked_of and several) or (via == "mail" and member != _steps.member_for(meta.get("step"), meta)) or (outsider and several)):
            if not text:
                return "nostep"
            kind, choice, stepped, member = "comment", "", False, ""      # not theirs to finish (a page drawn before the item changed): what they wrote is kept as a comment
        elif outsider:
            member = ""      # only one member has had a part in the item: another's answer stands for theirs, under the sender's name
        if member:
            _steps.settle_members(meta, meta)      # whose each bare step is, read before this answer takes any line out
        shared = bool(member) and (member != _steps.member_for(meta.get("step"), meta) or any(m != member for m in _steps.open_members(meta)))      # another member has a part in it too
        stays, done, moved = "", False, False      # of a shared step: who it is with after this answer, whether the answer finished the member's part, and whether the step passed on
        eff = _watch.answer_effect(meta, choice, text, _pages.zone_now().date()) if kind == "decision" and not stepped else {"do": ""}     # a pick on a watcher ask, or his words in the box, acts on the item
        askback = eff["do"] == _watch.NEEDS_DATE      # a date button, and no date he gave can be read: the answer and the note are kept below, and the item asks him back with dates
        if askback:
            asked_note, kind, text, choice, eff = text, "comment", text or f"(pressed: {choice})", "", {"do": ""}      # `asked_note`: the note as he wrote it
        now = time.time()
        rec: dict[str, Any] = {"ts": now, "kind": kind}
        if choice:
            rec["choice"] = choice
        if text:
            rec["text"] = text
        rec["via"] = via
        if via != "mail":
            _members.stamp(rec, who)     # whose answer it is (the board's sign-in), written when it is not the first person's: a record with no `by` reads as the first person's, and a server tick on a mail names no one
        if via == "mail":
            rec["server_note"] = _clip_line(str((mail or {}).get("note") or ""), 300)
        forms = _answers()._option_forms(item)         # the item's valid options, as the page drew them: (the name a pick is stored under, the label shown, the label stored)
        names = [f[0] for f in forms]
        if choice and not stepped and choice in names:      # the option picked, by the name it is stored under (the list is valid, so its places are the stored list's)
            picked = meta["options"][names.index(choice)]
        else:
            picked = next((o for o in meta.get("options") or [] if isinstance(o, dict) and str(o.get("label") or "").strip() == choice), {}) if choice and not stepped else {}     # a Done is no option: a stale option named Done (with a wake) is not his pick
        matched = bool(choice) and not stepped and choice in names   # his pick is one of the item's (valid) options, by label
        if kind == "decision" and not stepped and forms:      # the options he was shown stay on his answer (the History lists them whole, the picked one marked, though a pick takes them off the item); as stored, the card's letter is dropped again on read
            rec["options"] = _hooks().options_of(item, raw=True)
        if matched:                     # the record keeps what he chose: the clear below takes the options off the item
            rec["choice_line"] = str(picked.get("line") or "").strip()
            if letter:
                rec["letter"] = letter      # the letter the box drew beside it (three or more options): a note that names a letter still reads right later
        parked = ""                     # an option that carries a wake (a stored raise's "Park until …"): the server applies his choice itself
        if kind == "decision" and picked.get("wake"):
            parked = rec["parked"] = _pane_recovery._idle_park_at(str(picked["wake"]), text)
        prior = meta.get("answers") if isinstance(meta.get("answers"), list) else []
        meta["answers"] = [*prior, rec]
        if stepped:                     # the step is done: the state and its step go, and the item moves to its then-mover with his words (the answer) on it, recorded as his
            rec["step"] = _states.clean(meta.get("step"))
            _pm = dict(meta); _watch.end_wait(_pm)      # who takes it is read with any leftover wait already ended (a stored wait would make the item read as waiting, with no then)
            then = _model.derive({**item, "metadata": _pm}).then
            if then and not _model.is_owner(then) and not _model.norm_who(meta.get("then")):      # no stored `then`: the default is the first session in needs; a front agent there is not who takes the item after his step, the project's builder is (a builderless project keeps the front agent)
                then = _handover._builder_for_front(then, meta) or then
            if not then or _model.is_owner(then):      # no default mover and no session in needs: the front agent that holds the item's next open named step when the project has a builder; a project with no builder hands it to the session its next open step names, else its contact; else the item goes to its project's keeper at once, as mover
                then = _handover._front_step_holder(meta) or _holders._builderless_answer_to(meta, str(meta.get("project") or "")) or _telling.auto_mover(_telling.project_keeper(str(meta.get("project") or ""), ""), str(meta.get("project") or ""))      # never a front agent when the project has a builder
            if not shared and (not then or _model.is_owner(then)):      # nobody to take it (no default mover, no session in needs, no keeper): not recorded, nothing written
                return "nomover"
        if shared:                      # another member has a part in the step: it stays a step, with one of them
            done = kind == "decision" or bool(_noteread.read(text, _pages.zone_now(), _watch.parse_date)["done"])
            was = _steps.member_for(meta.get("step"), meta)
            stays = rec["left_with"] = _handover._share_step(meta, rec, member, done, now)      # the item is still on a step, and whose: the answer line says so whenever it is read
            moved = stays != was
            if moved:
                item["state_updated"] = item["confirmed"] = now
        elif stepped:
            if kind == "decision":          # his word that the step is done checks it on the item's checklist (a note leaves it open: the session that takes the item judges it)
                _handover._check_his_step(meta, rec["step"], now, by=who, member=member)
            else:                           # N4: his note on the step is his answer too: the server's step is ticked with his words (`→ "…"`); the lines a session wrote stay open for the session that judges them
                said = _noteread.read(text, _pages.zone_now(), _watch.parse_date)      # what the note says, applied by the server (note_read.py): a note that says he did it, or names a later time
                if said["until"]:           # "tomorrow evening": his step stays open and the item waits until then, on his words (the park path below); the then-mover is told it is held
                    until = said["until"]
                    rec["applied"] = f"The server read the note as a later time and parked the item until {until} {_cfg.tz_abbr()}: nothing is asked of you before then."
                else:
                    _hs.tick(meta, str(meta.get("owner") or ""), who, now, _hs.answer_words("", text), make=_holders._owner_want(meta), writer=NAME, add=False)
                    if said["done"]:        # "ran it": his step is ticked as a Done ticks it (every open line of his), the then-mover is told
                        _handover._check_his_step(meta, rec["step"], now, by=who, member=member)
                        rec["applied"] = "The server read the note as done and ticked his step: carry on as after a Done."
            _holders._state_end(meta, "your-step")
            meta.pop("draft", None)         # the step is done: the text he was to post is posted
            meta.pop("mover", None); meta.pop("then", None)
            _watch.end_wait(meta)           # a hold, its wake and any wait end with his step, as at the watcher's arrival (one list, watchers.LIVE_DROP; the owner's words for the wake go with it)
            _needs_store(meta, _canon_needs([x for x in _needs_of(meta) if x.lower() != "decision"]))      # a needs that named him would read the item as his call again
            if then and not _model.is_owner(then):
                _handover._hand_to_mover(meta, then)      # mover = then and named first in needs, as the decision path does (else notice_to falls back to the page's keeper)
            if until:                       # a note that names a later time: on hold until then, as a park leaves it; his words are the ones behind the wake (they let it stand past the usual cap)
                until = _wakes.parse_wake(until)
                meta["until"] = until           # the one date the wait ends on (until_write.py); no hold and no wake are stored
                _owner_words._cap_ok_put(meta, "wake", until, "a board note", quote=text, source=f"{_model.owner_display(meta)}'s note on his step, {_hooks().when_words(dt.datetime.fromtimestamp(now, _hooks().zone()))}")
            item["state_updated"] = item["confirmed"] = now
        if kind == "decision" and not stepped:          # his call is in: off his queue at once; the sessions named in needs stay named
            mover_in, then_in = _model.norm_who(meta.get("mover")), _model.norm_who(meta.get("then"))      # as stored before the call: read now, for the hand-over below
            beside = meta.get("state") == "your-step" and bool(_states.clean(meta.get("step")))      # the ask stands beside a your-step: his answer to it is not his word that the step is done
            _hs.tick(meta, str(meta.get("owner") or ""), who, now, _hs.answer_words(choice, text), make=(_hs.decide_of(meta.get("ask")) or _holders._OWNER_STEP_NONE) if beside else _holders._owner_want(meta), writer=NAME, apart=beside)      # N4: his answer ticks his step, shown on it (`→ the option`); an item that asked before the server made his steps gets the step now, done
            _needs_store(meta, _canon_needs([x for x in _needs_of(meta) if x.lower() != "decision"]))
            if meta.get("ask"):
                rec["ask"] = str(meta["ask"])   # the ask he answered stays with his answer: the item drops it, and a decision asked again within an hour with that same ask is refused (gates.gate_decision_again)
            meta.pop("ask", None)
            meta.pop(_askl.LEFT, None)      # an answered ask leaves no "taken off" record: a late pick on an older ask reads stale
            _holders._state_end(meta, "your-call")   # the call is made: a stored your-call no longer stands (a park picked below reads as derived)
            if matched:                 # a pick among the options settles the question: ask and options go, his answer keeps the label and line
                meta.pop("options", None)
            meta.pop("idle", None)
            if parked:                  # on hold until that day, as a time park by update(until=…, wait_kind="time") would leave it; "Owner acts now" leaves it on agent
                _holders._state_end(meta)        # a hold ends a stored state of any kind (it reads as derived: parked)
                meta["until"] = parked          # the one date the wait ends on (until_write.py); no hold and no wake are stored
                _owner_words._cap_ok_put(meta, "wake", parked, "a board answer", quote=text or str(rec.get("choice_line") or ""),
                            source=f"{_model.owner_display(meta)}'s answer on the board, {_hooks().when_words(dt.datetime.fromtimestamp(now, _hooks().zone()))}")   # "Park until <date>" is his own word for that date
            item["state_updated"] = item["confirmed"] = now
            effect = _wait_gates._watch_answer(item, meta, eff, now) if eff["do"] else ""     # arrived, not yet (the date he gave), drop
            if not eff["do"]:           # the watcher asks above move the item themselves (arrived, words, wait, drop); any other call is handed over here
                handed = _handover._decision_hand_over(meta, mover_in, then_in, parked=bool(parked),
                                    waiting=_item_read._model_of({**item, "gid": gid, "metadata": meta}).state == _model.WAITING, now=now)
        if askback:                     # the question put back: three days to pick from (watchers.ask_back); the item stays his, needs still names his decision
            meta["ask"], meta["options"] = _watch.ask_back(meta, asked_note, _pages.zone_now().date())
        item["metadata"] = meta
        item["updated"] = now
        _writes.save(gid, item, note=_answers()._answer_note(rec) + (f"\n\n(effect: {effect})" if kind == "decision" and eff["do"] and effect else ""), author=(NAME, "mail") if via == "mail" else (who, "board"))
        if parked or until or (kind == "decision" and eff["do"] == "wait"):
            _runner.wake()                     # the minute loop takes the new wake in (the event, and the wake file for a runner in another process)
        if kind == "decision" and eff["do"] == "drop":      # the items that waited on this one are released after both locks are let go (_release_dropped): a release tells the waiters
            drop.append(True)
        item["gid"] = gid
        took = then if then and not _model.is_owner(then) else ""      # the session that takes the item after the step
        if shared:
            told = _mail_deliver(gid, item, rec, took, stays) if via == "mail" else _answer_deliver(gid, item, rec, also=took, said=_shared_line(gid, rec, stays, done, moved))
        else:
            told = _mail_deliver(gid, item, rec, then) if via == "mail" else _answer_deliver(gid, item, rec, then if stepped else "", handed)
        told = [t for t in told if t]
        ticked = shared and done and not rec.get("text")      # a bare Done on a shared step asks no session for anything
        if via != "mail" and kind in ("decision", "step-reply") and not ticked and not parked and eff["do"] != "wait" and item.get("status") == "open":   # a park is acted on here, and so is a wait put back; any other decision waits for a session's write
            st = _answers()._answers_load()
            st[gid] = {"ts": now, "owner": _session_id(_telling.holder(item)), "project": str(meta.get("project") or ""),
                       "told": told, "words": _answers()._answer_words(rec, 300)}
            _answers()._answers_save(st)
    kind =("stepreply" if kind == "step-reply" else "donenote" if text else "done") if stepped else kind      # Done with a note in the box says the note went along
    if shared and not moved:      # the item is where it was: the notices that say it moved on do not fit
        kind = "partdone" if done else "comment"
    print(f"answer: {gid} {kind} from {'a sent mail' if via == 'mail' else 'the board'}" + (f", parked until {parked}" if parked else "") + f", told {', '.join(told) or 'nobody'}", file=sys.stderr, flush=True)
    _hooks().publish()
    return "askedback" if askback else kind


def _answer_tick(now: float | None = None) -> list[str]:
    """The escalation pass (on the runner): a decision answer that no session it was sent to has followed with a write to
    the item within _ANSWER_ESCALATE_S goes to the project's keeper (page_keeper: the project's keeper), once; then it is dropped. A closed
    or missing item drops it silently, and so does a keeper that is the mover itself. → the gids escalated."""
    now = time.time() if now is None else now
    out: list[str] = []
    tells: list[tuple[str, str, str, dict[str, Any]]] = []      # (gid, the keeper's session id, the notice, its pending record): sent after the lock is let go (a send that fails records itself on the item, and the item lock is taken before the pending answers, never after); the record is put back when its send raised
    with _answers()._ANSWER_LOCK:
        st = _answers()._answers_load()
        due = [g for g, e in st.items() if now - float(e.get("ts") or 0) >= _answers()._ANSWER_ESCALATE_S]
        if not due:
            return out
        for gid in due:
            e = st.pop(gid)
            try:
                it = _svcstore._load(gid)
            except ToolError:
                continue
            if it.get("status") != "open":
                continue
            meta = it.get("metadata") or {}
            owner, project = _telling.holder(it), str(e.get("project") or meta.get("project") or "")
            stew = _telling.page_keeper(project) or _telling.project_keeper(project)
            sid = _session_id(stew) if stew else ""
            if not sid or sid == _session_id(owner):
                print(f"answer: {gid} unacted after {_answers()._ANSWER_ESCALATE_S / 60:g} min, but no keeper other than its mover to tell", file=sys.stderr, flush=True)
                continue
            at = _hooks().when_words(dt.datetime.fromtimestamp(float(e.get("ts") or now), _hooks().zone()))
            olabel = _sr._session_label(owner) if owner else "none"
            tells.append((gid, sid, f"[stackshot] {_model.owner_display(meta)} answered {_gh.shown(gid)} on the board at {at} and its mover {olabel} has not written to the item "
                                  f"in {_answers()._ANSWER_ESCALATE_S / 60:g} min: {e.get('words') or ''}. As {_telling.keeper_words(project, stew)}: see that his answer is acted on "
                                  f"(by {olabel}, or the session named in its needs). → {_item_url(gid) or _telling.notice_link(gid)}", e))
            out.append(gid)
        _answers()._answers_save(st)
    failed: Exception | None = None
    unsent: list[tuple[str, dict[str, Any]]] = []
    for gid, sid, text, rec in tells:       # each send is tried, whatever the one before it did; a record whose send raised goes back, so the next tick sends it again (one that was sent is not put back: nothing is sent twice)
        try:
            _telling.tell_woken(gid, sid, text, tag="answer")
        except Exception as e:  # noqa: BLE001
            unsent.append((gid, rec))
            out.remove(gid)
            if failed is None:
                failed = e
            else:
                print(f"answer: {gid} unacted, its keeper not told: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    if unsent:
        with _answers()._ANSWER_LOCK:       # the pending answers alone (the item lock is not held): the records come back unless an answer was recorded for the item meanwhile
            st = _answers()._answers_load()
            for gid, rec in unsent:
                st.setdefault(gid, rec)
            _answers()._answers_save(st)
    for gid in out:
        print(f"answer: {gid} unacted after {_answers()._ANSWER_ESCALATE_S / 60:g} min, its keeper told", file=sys.stderr, flush=True)
    if failed is not None:
        raise failed
    return out
