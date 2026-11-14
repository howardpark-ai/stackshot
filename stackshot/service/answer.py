"""answer.py: the owner's answer from the board: its record, its delivery, the settle of a pending one and the escalation.

`_answer` records one answer (a decision, a comment, a Done or a note on his step) on the item under the item lock and then the answer lock, in the order every writer takes them, and hands the item over; `_answer_deliver` tells the item's mover and every
session named in its needs, one line each, through the owner-notice path; `_answer_ack` settles the answer pending on an item when a session that was told of it writes to the item; `_answer_tick` is the escalation pass of the minute set: a decision
answer that no session it was sent to has followed with a write within `_ANSWER_ESCALATE_S` goes to the project's keeper, once. The hand-over after an answer is service/answer_handover.py's.

A service module: it reads the store and writes an item through `writes.save`, under the locks it takes itself. The answer form's lock, its limits, the file of pending answers and its words (web/answers.py), the renderer's reader of the
options, its words for a time and the board's time zone, the debounced publish and the session id of a name are the surface's, reached through service/save_hooks.py; the lock is looked up on web/answers.py each time it is taken, so a suite that
puts a spy in its place sets it there (`answers._ANSWER_LOCK = ...`). A suite that replaces one of these functions sets it on this module (and `time` here, since this module reads its own).

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import datetime as dt
import sys
import time
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core import config as _cfg
from stackshot.core.instance import NAME, OWNER
from stackshot.fleet import sessions_registry as _sr
from stackshot.github import ghsync as _gh
from stackshot.model import ask_leaves as _askl
from stackshot.model import holders as _holders
from stackshot.model import model as _model
from stackshot.model import note_read as _noteread
from stackshot.model import owner_steps as _hs
from stackshot.model import states as _states
from stackshot.model.bullet_text import _clip_line
from stackshot.model.ids import _item_url
from stackshot.model.needs import _canon_needs, _needs_kinds, _needs_of, _needs_sessions, _needs_store
from stackshot.projects import pages as _pages
from stackshot.service import answer_handover as _handover
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


def _answer_deliver(gid: str, item: dict[str, Any], rec: dict[str, Any], then: str = "", handed: str = "") -> list[str]:
    """Push the answer to the item's mover (holder, never the creator) and to every session named in its needs, one line each, through the owner-notice
    path (tell_woken). A front-agent mover's line carries the mark a front agent takes. After a Done or a note on his step (`then` is who the item moved to) the then-mover is told too,
    in its own line: the step he did and "it's yours now". After a decision that handed the item to its stored then-mover (`handed`) the same: its line ends "It's yours now". → the session ids told."""
    meta = item.get("metadata") or {}
    owner, project = _telling.holder(item), str(meta.get("project") or "")
    verb = "answered" if rec.get("kind") == "decision" else "commented on"
    url = _item_url(gid) or _telling.notice_link(gid)
    done = f"; on hold with a wake on {rec['parked']}, set by the server" if rec.get("parked") else ""   # a stored raise's park, applied
    line = f"[stackshot] {OWNER} {verb} {_gh.shown(gid)} on the board: {_answers()._answer_words(rec)}{done} → {url}"
    thenid = _session_id(then or handed) if (then or handed) else ""
    if then:      # a Done: the step he did, then who has the item now and his note
        step = _states.clean(rec.get("step"))
        step = step if len(step) <= 240 else step[:240].rstrip() + " …"
        note = f", with his note: “{_answers()._answer_words({'text': rec.get('text')}, 300)}”" if rec.get("text") else ""
        line = f"[stackshot] {OWNER} did his step on {_gh.shown(gid)}: {step}. It goes to {_sr._session_label(then)} now{note} → {url}"
    judge = ""
    if then and rec.get("kind") == "step-reply":      # his note on the step, sent with no Done: the session that takes the item judges it (only its own line says so)
        line = (f"[stackshot] {OWNER} sent a note on his step on {_gh.shown(gid)}: {step}. It goes to {_sr._session_label(then)} now with his note: "
                f"“{_answers()._answer_words({'text': rec.get('text')}, 300)}” → {url}")
        judge = (f". Judge the note: if it finishes the step, carry on as after a Done; if it is a question or a request, answer it or do it, then hand the item back to {OWNER} "
                 f"with a new step (step=…); if it says he will do the step at a later time, put the item on hold until then "
                 f"(update hold=true, until=<that time, YYYY-MM-DDTHH:MM {_cfg.tz_abbr()}>, wait_reason=<what it waits on, at least {_cfg.WAIT_GUARD_REASON_MIN} characters>), "
                 f"leave his step open and hand no new step back.")
    yours = ("" if _answers()._answer_words(rec).rstrip()[-1:] in (".", "!", "?", ")") else ".") + " It's yours now" if handed and not then else ""      # a decision handed over: the mover's line plus the tail
    to_then = lambda t: t.replace(f"It goes to {_sr._session_label(then)} now", "It's yours now", 1).replace(f" → {url}", f"{yours}{judge} → {url}", 1)      # the then-mover's own line: "It's yours now", and for a note the instruction to judge it
    told: list[str] = []
    if judge and rec.get("applied"):      # the server read his note and applied it (note_read.py): the then-mover is told what was done instead of being asked to judge the note
        judge = ". " + str(rec["applied"])
    def tell(sid: str, text: str) -> None:
        _telling.tell_woken(gid, sid, text, tag="answer")
        told.append(sid)
    if owner:
        oid = _session_id(owner)
        front = _telling.front_keeper(owner, project)[0]
        mine = oid == thenid
        base = to_then(line) if mine else line
        tell(oid, f"{_FOR_OWNER} {base}" if front else base)
    for s in _needs_sessions(meta):
        sid = _session_id(s)
        if sid and sid not in told:
            tell(sid, to_then(line) if sid == thenid else line)
    if thenid and thenid not in told:          # the then-mover is neither the mover nor in needs (a stored `then`): it is told, and its write settles the answer
        tell(thenid, to_then(line))
    if not told:
        print(f"answer: {gid} has no mover and names no session to tell", file=sys.stderr, flush=True)
    return told


def _answer(gid: str, choice: str, text: str, act: str) -> str:
    """Record one answer from the board → what happened, the code the page's notice reads: decision | comment | done (sent), askedback (a date button whose note held no date it could read: the note is kept
    and the item asks him back with dates), closednote | stalenote (a note he wrote on a closed item, or on a question that changed, is kept as a comment), closed | stale (no note: nothing written), or empty | emptynote | toolong | nostep | nomover (nothing written; `emptynote` is a Send note on a blank box). A step form has two buttons and an optional note box.
    Done (act=done) is his word that the step is finished (`done`: the item goes to its then-mover, recorded as his answer "Done"); a note in the box stays on that record (`text`) and goes with the Done to the then-mover,
    which is told the step is done and shown the note (`donenote`: the same, and the notice says the note went along). Send note (act=note, text required) is his note on a step that stays open (`stepreply`: kind step-reply, and the item goes to its then-mover too, which judges whether the note finishes the step);
    on an item with no step any more it is a comment, and with no text nothing is written (`emptynote`). A page loaded before this form posts act=send (an empty box is a Done, a note is a step-reply, as ever) or act=comment (a comment only, the step stands).
    """
    choice, text, act = str(choice or "").strip(), str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip(), str(act or "").strip()
    if len(text) > _answers()._ANSWER_TEXT_MAX:
        return "toolong"
    with _writes.ITEM_LOCK, _answers()._ANSWER_LOCK:      # the order every writer takes (an update holds the item lock and then acks here): the item first, the pending answers second
        item = _svcstore._load(gid)
        if item.get("status") != "open":
            return _handover._keep_note(gid, item, text, "closednote", choice, "the item is closed") if text else "closed"      # a note on a closed item is kept as his comment
        meta = dict(item.get("metadata") or {})
        stepped, then, handed, letter, until = False, "", "", "", ""
        if choice:
            choice, letter = _answers()._split_letter(item, choice)      # the board's box posts "B · <label>": the label is the choice, the letter is kept beside it
        if choice:                      # an option's button: only while the item needs his decision, and only one of the item's stored options (Approve and Decline are no fallback); with none stored, Yes or No (the same two the page draws)
            valid = [f[0] for f in _answers()._option_forms(item)] or [o["label"] for o in _hooks().yesno_options(item)]
            if "decision" not in _needs_kinds(meta) or choice not in valid:
                if "decision" in _needs_kinds(meta) or not isinstance(meta.get(_askl.LEFT), dict):
                    return _handover._keep_note(gid, item, text, "stalenote", choice, "late, the item no longer asks this") if text else "stale"      # his note is kept as a comment; a bare pick on a question that changed is not an answer to the new one
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
        rec["via"] = "board"
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
            if not then or _model.is_owner(then):      # no default mover and no session in needs: a project with no builder hands it to the session its next open step names, else its contact; else the item goes to its project's keeper at once, as mover
                then = _holders._builderless_answer_to(meta, str(meta.get("project") or "")) or _telling.auto_mover(_telling.project_keeper(str(meta.get("project") or ""), ""), str(meta.get("project") or ""))      # never a front agent when the project has a builder
            if not then or _model.is_owner(then):      # nobody to take it (no default mover, no session in needs, no keeper): not recorded, nothing written
                return "nomover"
            if kind == "decision":          # his word that the step is done checks it on the item's checklist (a note leaves it open: the session that takes the item judges it)
                _handover._check_his_step(meta, rec["step"], now)
            else:                           # N4: his note on the step is his answer too: the server's step is ticked with his words (`→ "…"`); the lines a session wrote stay open for the session that judges them
                said = _noteread.read(text, _pages.zone_now(), _watch.parse_date)      # what the note says, applied by the server (note_read.py): a note that says he did it, or names a later time
                if said["until"]:           # "tomorrow evening": his step stays open and the item waits until then, on his words (the park path below); the then-mover is told it is held
                    until = said["until"]
                    rec["applied"] = f"The server read the note as a later time and put the item on hold until {until} {_cfg.tz_abbr()}: nothing is asked of you before then."
                else:
                    _hs.tick(meta, str(meta.get("owner") or ""), OWNER, now, _hs.answer_words("", text), make=_holders._owner_want(meta), writer=NAME, add=False)
                    if said["done"]:        # "ran it": his step is ticked as a Done ticks it (every open line of his), the then-mover is told
                        _handover._check_his_step(meta, rec["step"], now)
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
                _owner_words._cap_ok_put(meta, "wake", until, "a board note", quote=text, source=f"{OWNER}'s note on his step, {_hooks().when_words(dt.datetime.fromtimestamp(now, _hooks().zone()))}")
            item["state_updated"] = item["confirmed"] = now
        if kind == "decision" and not stepped:          # his call is in: off his queue at once; the sessions named in needs stay named
            mover_in, then_in = _model.norm_who(meta.get("mover")), _model.norm_who(meta.get("then"))      # as stored before the call: read now, for the hand-over below
            beside = meta.get("state") == "your-step" and bool(_states.clean(meta.get("step")))      # the ask stands beside a your-step: his answer to it is not his word that the step is done
            _hs.tick(meta, str(meta.get("owner") or ""), OWNER, now, _hs.answer_words(choice, text), make=(_hs.decide_of(meta.get("ask")) or _holders._OWNER_STEP_NONE) if beside else _holders._owner_want(meta), writer=NAME, apart=beside)      # N4: his answer ticks his step, shown on it (`→ the option`); an item that asked before the server made his steps gets the step now, done
            _needs_store(meta, _canon_needs([x for x in _needs_of(meta) if x.lower() != "decision"]))
            if meta.get("ask"):
                rec["ask"] = str(meta["ask"])   # the ask he answered stays with his answer: the item drops it, and a decision asked again within an hour with that same ask is refused (gates.gate_decision_again)
            meta.pop("ask", None)
            meta.pop(_askl.LEFT, None)      # an answered ask leaves no "taken off" record: a late pick on an older ask reads stale
            _holders._state_end(meta, "your-call")   # the call is made: a stored your-call no longer stands (a park picked below reads as derived)
            if matched:                 # a pick among the options settles the question: ask and options go, his answer keeps the label and line
                meta.pop("options", None)
            meta.pop("idle", None)
            if parked:                  # on hold until that day, as update(hold=true, until=…) would leave it; "Owner acts now" leaves it on agent
                _holders._state_end(meta)        # a hold ends a stored state of any kind (it reads as derived: parked)
                meta["until"] = parked          # the one date the wait ends on (until_write.py); no hold and no wake are stored
                _owner_words._cap_ok_put(meta, "wake", parked, "a board answer", quote=text or str(rec.get("choice_line") or ""),
                            source=f"{OWNER}'s answer on the board, {_hooks().when_words(dt.datetime.fromtimestamp(now, _hooks().zone()))}")   # "Park until <date>" is his own word for that date
            item["state_updated"] = item["confirmed"] = now
            effect = _wait_gates._watch_answer(item, meta, eff, now) if eff["do"] else ""     # arrived, not yet (the date he gave), drop
            if not eff["do"]:           # the watcher asks above move the item themselves (arrived, words, wait, drop); any other call is handed over here
                handed = _handover._decision_hand_over(meta, mover_in, then_in, parked=bool(parked),
                                    waiting=_item_read._model_of({**item, "gid": gid, "metadata": meta}).state == _model.WAITING, now=now)
        if askback:                     # the question put back: three days to pick from (watchers.ask_back); the item stays his, needs still names his decision
            meta["ask"], meta["options"] = _watch.ask_back(meta, asked_note, _pages.zone_now().date())
        item["metadata"] = meta
        item["updated"] = now
        _writes.save(gid, item, note=_answers()._answer_note(rec) + (f"\n\n(effect: {effect})" if kind == "decision" and eff["do"] and effect else ""), author=(OWNER, "board"))
        if parked or until or (kind == "decision" and eff["do"] == "wait"):
            _runner.WAKE_EVENT.set()           # the minute loop takes the new wake in
        if kind == "decision" and eff["do"] == "drop":
            try:
                _wakes.release_after(gid, "dropped", "", "")      # the items that waited on this one
            except Exception as e:  # noqa: BLE001
                print(f"answer: {gid} dropped but its after releases failed: {e}", file=sys.stderr, flush=True)
        item["gid"] = gid
        told = [t for t in _answer_deliver(gid, item, rec, then if stepped else "", handed) if t]
        if kind in ("decision", "step-reply") and not parked and eff["do"] != "wait" and item.get("status") == "open":   # a park is acted on here, and so is a wait put back; any other decision waits for a session's write
            st = _answers()._answers_load()
            st[gid] = {"ts": now, "owner": _session_id(_telling.holder(item)), "project": str(meta.get("project") or ""),
                       "told": told, "words": _answers()._answer_words(rec, 300)}
            _answers()._answers_save(st)
    kind = ("stepreply" if kind == "step-reply" else "donenote" if text else "done") if stepped else kind      # Done with a note in the box says the note went along
    print(f"answer: {gid} {kind} from the board" + (f", parked until {parked}" if parked else "") + f", told {', '.join(told) or 'nobody'}", file=sys.stderr, flush=True)
    _hooks().publish()
    return "askedback" if askback else kind


def _answer_tick(now: float | None = None) -> list[str]:
    """The escalation pass (on the runner): a decision answer that no session it was sent to has followed with a write to
    the item within _ANSWER_ESCALATE_S goes to the project's keeper (page_keeper: the project's keeper), once; then it is dropped. A closed
    or missing item drops it silently, and so does a keeper that is the mover itself. → the gids escalated."""
    now = time.time() if now is None else now
    out: list[str] = []
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
            _telling.tell_woken(gid, sid, f"[stackshot] {OWNER} answered {_gh.shown(gid)} on the board at {at} and its mover {olabel} has not written to the item "
                                  f"in {_answers()._ANSWER_ESCALATE_S / 60:g} min: {e.get('words') or ''}. As {_telling.keeper_words(project, stew)}: see that his answer is acted on "
                                  f"(by {olabel}, or the session named in its needs). → {_item_url(gid) or _telling.notice_link(gid)}", tag="answer")
            out.append(gid)
        _answers()._answers_save(st)
    for gid in out:
        print(f"answer: {gid} unacted after {_answers()._ANSWER_ESCALATE_S / 60:g} min, its keeper told", file=sys.stderr, flush=True)
    return out
