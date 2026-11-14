"""wait_fixes.py: the server's own corrections of a wait, and the window of the old wait parameters.

A wake that is the whole of a wait is parked by the write itself (`_date_only_wait`) or, for what is already stored, by the ten-minute filing pass (`_wake_park`); a next line that states a wait in words is turned
into the wait by the same pass (`_wait_end_fix`, with the facts it reads in `_wait_end_facts`; `_wait_end_sent_back` is the mover's own refusal of one). The two notes a wake with no hold draws on the reply
(`_wake_window_note`, `_wake_step_note`) and what they read (`_wake_alone_on_agent`, `_wake_step_found`) are here too, with the readers of what holds an item on hold (`_hold_held_by`, `_hold_set`: the update and the
until pass share them), the note a hold on an anchored thread owes (`_anchored_wait`), the date a wait that came with a kind and no date gets (`_fallback_wait_date`), the mark of a fix on the item
(`_record_fixes`) and the window in which the old parameters wake, ask_by and hold are still accepted as aliases of `until` (`_wait_alias_until`, `_wait_alias_check`, `_wait_alias_gate`).

A service module: it reads the store and writes an item only through `writes.save`, under the item lock. The debounced publish and the board's time zone are the surface's, reached through service/save_hooks.py.
A suite that replaces one of these sets it on this module (and `time` here, since this module reads its own).

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.anchors import anchor_scope as _ascope
from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core.instance import NAME, OWNER
from stackshot.fleet import liveness as _lv
from stackshot.fleet import sessions_registry as _sr
from stackshot.model import holders as _holders
from stackshot.model import model as _model
from stackshot.model import model_guards as _mg
from stackshot.model import states as _states
from stackshot.model import steps as _steps
from stackshot.model.bullet_text import _clip_line
from stackshot.model.needs import _needs_kinds, _waits_decision
from stackshot.projects import pages as _pages
from stackshot.service import event_waits as _evwaits
from stackshot.service import gates as _gates
from stackshot.service import handoff as _handoff
from stackshot.service import item_read as _item_read
from stackshot.service import mover_steps as _mover_steps
from stackshot.service import owner_words as _owner_words
from stackshot.service import proofs as _proofs
from stackshot.service import released as _relsvc
from stackshot.service import store as _svcstore
from stackshot.service import wait_gates as _wait_gates
from stackshot.service import wakes as _wakes
from stackshot.service import watching as _watching
from stackshot.service import writes as _writes
from stackshot.service.save_hooks import hooks as _hooks
from stackshot.waits import dated_wait as _dw
from stackshot.waits import server_fixes as _sf
from stackshot.waits import until_write as _uw
from stackshot.waits import wait_end as _we
from stackshot.waits import waiting as _wt
from stackshot.waits import watchers as _watch


def _wake_alone_on_agent(meta: dict[str, Any]) -> bool:
    """A wake with no hold on an item that is on agent: what the two wake notes (_wake_window_note, _wake_step_note) share. False for an item on hold or with no wake, one waiting on his decision
    or on an open `after`, one with needs=external, one whose wake carries a wait_basis and is still ahead (the board lists it as waiting until the wake: model.view), and one stored as outside, verifying or blocked
    (none of those is on agent)."""
    if meta.get("hold") or _wt.stored_until(meta) or not _wt.wake_value(meta) or _waits_decision(meta) or _item_read._after_open(meta) or (_wt.basis_of(meta) and (_wt.wake_epoch(_wt.wake_value(meta)) or 0.0) > time.time()):
        return False
    return not ("external" in [str(x).lower() for x in _wt.needs_of(meta)] or str(meta.get("state") or "").lower() in ("outside", "verifying", "blocked"))


def _wake_window_note(meta: dict[str, Any]) -> str:
    """Work moving in real time is on agent, however long it takes; a wait-and-see window the work itself needs is waiting (parked). A note on the
    reply (never a refusal) when a write sets a wake without hold and the item's next, as it now stands (this call's lines and the stored ones), waits for that wake's day
    (model_guards.reads_as_window): a wake alone is a wait until that date, and the item is parked till then. Not for an item that is not on agent: one on hold, waiting on his decision, waiting
    on an open `after`, with needs=external, or stored as outside, verifying or blocked."""
    if not _wake_alone_on_agent(meta):
        return ""
    found = _mg.reads_as_window(meta.get("next"), _wt.wake_value(meta))
    if not found:
        return ""
    return (f"\n(note: wake {_wt.wake_value(meta)} alone is a wait until that date, and this item's next waits for that date (\"{found}\"), so the item waits until then, listed as waiting. "
            "To move the date: update(until=\"<when the window ends>\"); "
            "if you keep moving the work and a step can run now, drop the date with until=\"none\")")


def _wake_step_found(item: dict[str, Any], senders: tuple[str, ...], dated_only: bool = False, legacy_wake: bool = False) -> list[str]:
    """What makes the open next lines of an item wait (dated_wait.timed_wait_lines) when its wake stands alone on agent (_wake_alone_on_agent), the writer is its mover and every open line is the mover's
    (or names nobody) and reads as a wait for a time or an event; [] otherwise. `dated_only` keeps the wake's own hour or day and drops the outside event."""
    meta = item.get("metadata") or {}
    if legacy_wake and _wt.stored_until(meta) and not str(meta.get("wait_kind") or "").strip():      # a wake an older write stored, folded into until by this write: it is read as the wake it was (a date this write sets is the wait)
        meta = dict(meta); _uw.unfold(meta); item = {**item, "metadata": meta}
    if not _wake_alone_on_agent(meta) or not any(str(x or "").strip() for x in senders):
        return []
    mod = _item_read._model_of(item)
    if mod.state != _model.ALIVE or not mod.mover or _model.is_owner(mod.mover) or not any(_handoff.ho_same(mod.mover, x) for x in senders):
        return []
    return _dw.timed_wait_lines(meta.get("next"), _wt.wake_value(meta), _pages.zone_now().date(),
                                lambda who: _handoff.ho_same(mod.mover, who) or _sr._session_label(mod.mover).casefold() == who.casefold(), dated_only)


def _date_only_wait(item: dict[str, Any], meta: dict[str, Any], next_after: Any, wake_in: str, senders: tuple[str, ...], reason: str) -> tuple[str, str]:
    """The write's own correction of a wake that is the whole of a wait: (the wait_basis to park it with, the reply line), or ("", "") when the date is no wait, as on work in hand. It is a wake alone
    (_wake_alone_on_agent) more than [waiting] dated_wait_min_hours ahead, set or kept by the item's mover, whose every open next line, as this write leaves it (`next_after`), is the mover's and
    reads as a wait for the wake's own hour or day (dated_wait.timed_wait_lines): nothing is left to do before it, so the item is stored waiting on a time from this write, as the park the note
    used to ask for (the caller sets hold=true with this basis and the usual gates read it). The basis is the call's wait_reason with the wake day; with none (a stored wake, a next written alone) the
    step's own words. ("", "") when the basis would not pass the gate or the wake cannot be read: the note stands."""
    try:
        w = {**meta, "next": next_after}
        if wake_in:
            w["wake"] = _wakes.parse_wake(wake_in)
        at = _wt.wake_epoch(w.get("wake")) if w.get("wake") else None
        if at is None or at <= time.time() + _wt.dated_wait_min_hours() * 3600.0:
            return "", ""
        found = _wake_step_found({**item, "metadata": w}, senders, dated_only=True)
        if not found:
            return "", ""
        day = _wakes.wake_at(w["wake"]).date().isoformat()
        why = " ".join(str(reason or "").split())
        for text in ((f"{why[:240]} (wake {day})" if why else ""), f"the only open step is timed ({found[0]}), wake {day}"):
            if not text:
                continue
            try:
                _gates.gate_wait_basis({**item, "metadata": w}, text, w["wake"], held=True)
            except ToolError:
                continue
            return text, (f"\n(parked: wake {w['wake']} alone is a wait until that date (outside a hand-off), and your only open next line{'s' if len(found) > 1 else ''} wait{'' if len(found) > 1 else 's'} for it (\"{found[0]}\"), "
                          f"so the item waits until then, stored as waiting on a time (reason: {_clip_line(text, 120)}); History has a line. If a step can run now, write it as the action and pass clear_hold=true: the server then leaves this wake alone)")
    except Exception as e:  # noqa: BLE001  — the correction is an extra: a failure leaves the write as it was, with the note
        print(f"date-only wait: not judged: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return "", ""


def _wake_park_line(wake: str, basis: str) -> str:
    """The History line of a park the server made (server_fixes.WAKE_PARK): what it did, the reason it kept, and how the mover sends it back."""
    return (f"parked: wake {wake} alone is a wait until that date (outside a hand-off) and the only open next line waits for it; the item waits until then (reason: {_clip_line(basis, 70)}). "
            "clear_hold=true sends it back and the server leaves that wake alone")


def _wake_park(gid: str, now: float) -> "dict[str, Any]":
    """The ten-minute filing pass's park of a wake that is the whole of a wait (audit_run.wake_park_pass; server_fixes.WAKE_PARK): the same park a write makes (hold, the basis `_date_only_wait`
    builds from the step's own words, the wake as stored), made as the server's own save: no writer, so the item's author, its activity clock and a pending decision answer are untouched
    (the model is `_front_step_move`). Read again under the lock. Nothing for an item that is not open or that the owner moves, a wake the mover sent back, or one `_date_only_wait` does not park
    (the finding stands then). Never closes an item and writes no ask. → {"parked": bool, "wake": str, "why": str}."""
    with _writes.ITEM_LOCK:
        item = _svcstore._load(gid)
        meta = item.get("metadata")
        if not isinstance(meta, dict) or item.get("status") != "open" or not _wt.wake_value(meta) or meta.get("hold"):
            return {"parked": False, "why": "not an open item with a wake and no hold"}
        mod = _item_read._model_of(item)
        if not mod.mover or _model.is_owner(mod.mover) or _waits_decision(meta):
            return {"parked": False, "why": f"{OWNER} moves it"}
        wake = str(_wt.wake_value(meta))
        if _sf.declined(meta, _sf.WAKE_PARK, wake):
            return {"parked": False, "why": "the mover sent this wake back"}
        basis, _note = _date_only_wait(item, meta, meta.get("next"), "", (mod.mover,), "")
        if not basis:
            return {"parked": False, "why": "not a wake that is the whole of a wait"}
        try:
            basis_ok = _gates.gate_wait_basis(item, basis, wake, held=True)
            _gates.gate_cap(item, [], "wake", wake, _wakes.wake_at(wake).timestamp(), basis_ok)
        except ToolError as e:
            return {"parked": False, "why": str(e)[:200]}
        meta["hold"] = True
        _hold_set(meta, NAME, now)
        _owner_words._cap_ok_drop(meta, "wake")
        if meta.get("state") in _states.STATES and meta["state"] != "parked":      # a hold makes the item read parked: the stored state of another kind goes, as in the write's own park
            _holders._state_end(meta)
        _mover_steps._state_apply(meta, "open", "", {}, frozenset({"wake", "hold", "wait_basis"}))
        _owner_words._basis_put(meta, basis_ok, wake, NAME)
        _sf.record(meta, _sf.WAKE_PARK, wake, _wake_park_line(wake, basis_ok), now)
        _writes.save(gid, item, note="wake parked")
        return {"parked": True, "wake": wake, "why": ""}


def _wait_end_facts() -> "_we.Facts":
    """What the wait-end rule (wait_end.py) reads of the world: the fleet's machines and which are online, this repository and [released.repos], and, per item, the pull requests and links its anchors
    name. Read from files, no network (the anchors file is read once per call of the factory)."""
    boxes = _evwaits.evw_boxes()
    store = _anc.load()

    def scoped(gid: str) -> list[str]:
        try:
            project = str((_svcstore._load(gid).get("metadata") or {}).get("project") or "")
        except Exception:  # noqa: BLE001
            return []
        return [str(e["url"]) for e in _item_read._scoped_anchors(project, gid, store)]

    def prs(gid: str) -> list[str]:
        out = []
        for u in scoped(gid):
            m = _we._PR_URL.match(u)
            if m:
                out.append(f"{_cfg.canon_repo(m.group(1))}#{int(m.group(2))}")
        return out

    def takes(url: str) -> bool:
        try:
            return bool(_anc.anchor_id(_anc.split_fragment(url)[0])) and not _anc.gmail_query_problem(url)
        except Exception:  # noqa: BLE001
            return False
    return _we.Facts(machines={k: f for k, (f, _r) in boxes.items()}, online=frozenset(f.lower() for f, r in boxes.values() if r and _lv.puller_online(r)),
                     own_repo=_cfg.canon_repo(_relsvc._own_repo()), released=frozenset(a.lower() for r in _cfg.released_repos() for a in _cfg.repo_aliases(r)),
                     item_prs=prs, item_anchors=scoped, anchor_url=takes)


def _wait_end_sent_back(meta: dict[str, Any], kinds: "tuple[str, ...]") -> None:
    """The mover sends a wait the server set back (clear_after, clear_wait, step_proof "none"): each token of the given kinds that server_fixes marks for WAIT_END is unmarked and declined, so the
    server leaves that line alone until its words change."""
    for tok in _sf.mark_tokens(meta, _sf.WAIT_END):
        if _we.kind_of_token(tok) in kinds:
            _sf.unmark(meta, _sf.WAIT_END, tok)
            _sf.decline(meta, _sf.WAIT_END, tok)


def _wait_end_fix(gid: str, plan: "dict[str, Any]", now: float) -> "dict[str, Any]":
    """The ten-minute filing pass's fix of a wait a next line states in words (audit_run.wait_end_pass; server_fixes.WAIT_END; wait_end.py): the item is read again under the lock and the gap found again
    from its words (a line that changed, a wait the mover sent back, a decision on the owner, a held item: nothing is written), then the plan is set through the gates a write passes: `after`
    (gates.gate_after), an event wait (_evwait_gate), an anchor wait (the link is added to the anchors scoped to the item, _anchor_wait_gate) or a step proof (proofs.step_proof_set), a backstop day (the wake or ask_by it
    has, else now plus [waiting] cap_days), and a History line (server_fixes.record). A waiting item takes its mover as post_wake_mover. The server's own save: no writer. A gate's refusal leaves the item as
    it was. Never closes an item and writes no ask. -> {"fixed": bool, "what": str, "why": str}."""
    tok, op = str(plan.get("token") or ""), str(plan.get("op") or "")

    def no(why: str) -> "dict[str, Any]":
        return {"fixed": False, "what": "", "why": why}
    if not tok or op not in ("after", "event", "anchor", "proof", "backstop", "anchor_pick"):
        return no("no plan")
    facts = _wait_end_facts()
    if op == "event":
        _wait_gates._evwait_preread("event", plan.get("phrase"))
    with _writes.ITEM_LOCK:
        item = _svcstore._load(gid)
        meta = item.get("metadata")
        if not isinstance(meta, dict) or item.get("status") != "open" or meta.get("hold") or _waits_decision(meta):
            return no("not an open item the mover moves")
        mod = _item_read._model_of(item)
        alive = mod.state == _model.ALIVE
        mover = mod.mover if alive else (mod.wait.mover if mod.wait else "")
        if not mover or _model.is_owner(mover):
            return no(f"{OWNER} moves it")
        if _sf.declined(meta, _sf.WAIT_END, tok) or _sf.marked(meta, _sf.WAIT_END, tok):
            return no("this line was fixed or sent back already")
        gap = next((g for g in _we.item_gaps(gid, meta, mover, "alive" if alive else "waiting", facts, _item_read._open_item_named, _handoff.ho_same, now,
                                             pending=lambda t: _sf.declined(meta, _sf.WAIT_END, t)) if g.token == tok and g.plan.get("op") == op), None)
        if gap is None:
            return no("the line or the wait changed")
        was = json.loads(json.dumps(item))
        # a backstop day is a date (watchers.day_epoch): a stored until, ask_by or wake that is no date is no backstop, and the cap day takes its place
        dated = [str(v) for v in (_wt.stored_until(meta), meta.get("ask_by"), meta.get("wake")) if _watch.day_epoch(v) is not None]
        has_back = bool(dated)
        back = dated[0] if dated else _we.backstop_day(now, _wt.cap_days(), _hooks().zone())
        anchor_undo: "tuple[Any, Any] | None" = None
        saved = False

        def undo_anchor() -> None:
            """A gate refused after the anchor was added to the list: the list goes back as it was, unless someone else changed it since."""
            if anchor_undo is None:
                return
            try:
                if _anc.load() == anchor_undo[1]:
                    _anc.save(anchor_undo[0])
            except Exception as e:  # noqa: BLE001
                print(f"wait end: {gid} anchor not taken back: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)

        def waiting_as(kind: str) -> None:
            meta.pop("mover", None)
            meta["post_wake_mover"] = mover
            meta["wait_kind"] = kind
            if not has_back:
                meta["until"] = back        # the one date the wait ends on (until_write.py); an item that stores its date as wake or ask_by keeps it as it is
            _holders._state_end(meta)

        try:
            if op == "after":
                meta["after"] = _gates.gate_after(plan.get("ids"), gid)
                waiting_as("item")
                what = f"after={', '.join(str(x) for x in plan.get('shown') or ())}"
            elif op == "event":
                meta["wait_event"] = str(plan.get("phrase") or "")
                waiting_as("event")
                what = f"wait_event={plan.get('phrase')}"
            elif op == "anchor":
                url = str(plan.get("url") or "")
                project = str(meta.get("project") or "")
                store = _anc.load()
                if not any(_watching.same_anchor(e["url"], url) for e in _ascope.anchor_scope(store, gid, project)):
                    before = json.loads(json.dumps(store))
                    _anc.add(store, project, [url], [gid], by=NAME)
                    _anc.save(store)
                    anchor_undo = (before, json.loads(json.dumps(_anc.load())))
                meta["wait_anchor"] = url
                meta["wait_event"] = _clip_line(plan.get("event"), _model.LINE_MAX)
                waiting_as("anchor")
                _wait_gates._anchor_wait_gate(was["metadata"], meta, gid)
                what = f"anchor wait on {_clip_line(url, 50)}"
            elif op == "proof":
                if _we.line_hash(_steps.view(meta)[int(plan["pos"]) - 1]["text"]) != tok.rpartition("|")[2]:
                    return no("the step changed")
                _proofs.step_proof_set(meta, _steps.view(meta), [{"step": int(plan["pos"]), "proof": str(plan["proof"])}])
                what = f"step {plan['pos']} proof {plan['proof']}"
            elif op == "backstop":
                if not has_back:
                    meta["until"] = back
                if not _watch.can_end(meta):
                    return no("a backstop day does not end this wait")
                what = f"until={back}"
            else:
                meta["wait_anchor"] = str(plan.get("url") or "")
                _wait_gates._anchor_wait_gate(was["metadata"], meta, gid)
                what = f"wait_anchor={_clip_line(plan.get('url'), 50)}"
            _wait_gates._watch_on_write(gid, was, meta, {}, set(), "", False)       # the wait's stamp, and the event wait's gate (a wait for what has already happened is refused)
            _sf.record(meta, _sf.WAIT_END, tok, _we.history({**plan, "pos": gap.pos}, gap.line, gap.pos, back, _sr._session_label(mover) or mover), now)
            _writes.save(gid, item, note="wait set")
            saved = True
        except ToolError as e:
            return no(str(e)[:200])
        except Exception as e:  # noqa: BLE001  — one item's failure never stops the pass
            print(f"wait end: {gid} not fixed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
            return no(f"{e.__class__.__name__}")
        finally:
            if not saved:
                undo_anchor()       # a refusal leaves the item as it was, the anchors list too
    _hooks().publish()
    return {"fixed": True, "what": what, "why": ""}


def _wake_step_note(item: dict[str, Any], senders: tuple[str, ...], legacy_wake: bool = False) -> str:
    """A mover set a wake with no hold on a step that only waits, and the item sat on agent while nobody worked it. A note on the reply (never a refusal) when a write
    ends with a wake and no hold (set now or stored), the writer is the item's mover, and every open line of next is the mover's (or names nobody) and reads as a wait for a time or an event
    (model_guards.reads_as_timed_step: timed at the wake's own hour or day, or started by an outside event). Not when a line is an action to take now, when another party's step is in flight
    (a line that opens with another name, the owner included), when the wake is not alone (the cases _wake_alone_on_agent skips), or when the writer is not the mover. A wait for the wake's own
    hour or day more than an hour away is parked by the write itself (_date_only_wait), so it reaches this note only inside the hour."""
    meta = item.get("metadata") or {}
    found = _wake_step_found(item, senders, legacy_wake=legacy_wake)
    if not found:
        return ""
    return (f"\n(note: wake {_wt.wake_value(meta)} alone is a wait until that date, and this item's only open next line{'s' if len(found) > 1 else ''} of yours wait{'' if len(found) > 1 else 's'} for a time or an event (\"{found[0]}\"), "
            "so the item waits until then, listed as waiting. To move the date: update(until=\"<when the wait ends>\"), "
            "with wait_reason=<what the step waits on> when you set the date"
            + ("; when it waits on a named person outside answering, park it as an outside wait instead of a plain hold: needs=[\"external\"] with wait_kind=\"relay\", wait_event=<who> and ask_by=YYYY-MM-DD" if any(_mg.is_reply_trigger(f) for f in found) else "")
            + "; if the step can run now, write it as the action and drop the date with until=\"none\")")


def _anchored_wait(gid: str, meta: dict[str, Any]) -> str:
    """An item that waits on someone outside may be parked when the thread it waits on is
    anchored to it and named in its next, since the anchor's notice wakes the mover; its wake is then a backstop at most
    [waiting] cap_days out (the same cap as any wait; a longer one needs the owner's words). → the note a hold on an item that waits on someone outside owes, "" when it owes none."""
    try:
        scoped = _item_read._scoped_anchors(str(meta.get("project") or ""), gid)
    except Exception:
        scoped = []
    if not any(e["url"] in str(meta.get("next") or "") for e in scoped):
        return (f"on hold while it waits on someone outside: such an item is not parked but stays with needs=external, unless {OWNER} "
                f"parked it or the thread it waits on is anchored to it (anchors(project, add=[url], items=[{gid or 'its id'}])) and named in next")
    cap = _wt.cap_days()
    try:
        far = _wakes.wake_at(_wt.wake_value(meta)) - _pages.zone_now() > dt.timedelta(days=cap + 1) and not _wt.cap_words(meta, "wake")
    except ValueError:
        far = False
    return (f"on hold on an anchored thread with a wake more than {cap:g} days out: the wake is only a backstop, "
            f"at most {cap:g} days away (a longer one needs {OWNER}'s words), since the anchor's notice wakes you sooner") if far else ""


# The hold investigation (many holds on many items, he asked for few): who set a hold is recorded
# (metadata.hold_set {at, by}), and a hold counts as explained only by what holds the item NOW (never by a stored reason): an open
# after, a pane recycle, needs external, an anchor scoped to the item. The unexplained-holds report and the briefings read this.
def _hold_held_by(gid: str, meta: dict[str, Any]) -> list[str]:
    """What holds an item on hold now, as render.HOLD_WHY keys: `after` an open item it waits on, `recycle` a pane recycle,
    `external` needs external, `anchor` an anchor scoped to the item. [] when none does."""
    out = []
    if _item_read._after_open(meta):
        out.append("after")
    if meta.get("recycle"):
        out.append("recycle")
    if "external" in _needs_kinds(meta):
        out.append("external")
    if _item_read._scoped_anchors(str(meta.get("project") or ""), gid):
        out.append("anchor")
    return out


def _hold_set(meta: dict[str, Any], by: str, now: float | None = None) -> None:
    """Record who set a hold and when (metadata.hold_set), for the unexplained-holds report and the briefings."""
    meta["hold_set"] = {"at": time.time() if now is None else now, "by": " ".join(str(by).split())[:80]}


# The one `until` date of a wait (until_write.py). The old parameters wake, ask_by and hold are aliases of it: a write that passes one stores `until` (and no old field) and its reply names `until`.
# They are accepted for 14 days after the release that stores `until`, then refused with a pointer to `until`: [model] wait_alias_until (YYYY-MM-DD, read at the call, so moving it needs no release)
# is the last day they are accepted; the code's own default, until_write.ALIAS_UNTIL, is Wed Nov 25th 2026 (14 days after Wed Nov 11th 2026).
def _wait_alias_until() -> dt.date:
    """[model] wait_alias_until (YYYY-MM-DD, default the code's): the last day wake, ask_by and hold are still accepted as aliases of until. A value that is not a date reads as the default."""
    v = str(_cfg.get("model", "wait_alias_until", default=_uw.ALIAS_UNTIL) or _uw.ALIAS_UNTIL).strip()
    try:
        return dt.date.fromisoformat(v)
    except ValueError:
        return dt.date.fromisoformat(_uw.ALIAS_UNTIL)


def _wait_alias_check() -> None:
    """At the server's start: one stderr warning when [model] wait_alias_until is missing or not a date, so the code's own default end of the alias window (until_write.ALIAS_UNTIL) never stands in silently."""
    v = str(_cfg.get("model", "wait_alias_until", default="") or "").strip()
    try:
        dt.date.fromisoformat(v)
    except ValueError:
        print(f"config: [model] wait_alias_until is {'missing' if not v else 'not a date (' + v + ')'}: the old wait parameters (wake, ask_by, hold) stay accepted to the code's default, {_uw.ALIAS_UNTIL}", file=sys.stderr, flush=True)


def _wait_alias_gate(used: list[str]) -> dt.date:
    """The old wait parameters a call passed (`used`: wake, ask_by, hold) → the last day they are accepted; a ToolError naming `until` from the day after it."""
    ends = _wait_alias_until()
    if used and dt.datetime.now(_cfg.tz()).date() > ends:
        raise ToolError(f"Refused: {', '.join(used)} {'is' if len(used) == 1 else 'are'} not a parameter any more (accepted until {ends:%Y-%m-%d}). The date a wait ends on is until=<YYYY-MM-DD, or YYYY-MM-DDTHH:MM> "
                        "(with wait_kind beside it when the wait stands on more than the date); until=\"none\" drops it.")
    return ends


def _fallback_wait_date(meta: dict[str, Any], next_text: Any, description: Any, due: Any) -> tuple[str, str, str]:
    """The date for a wait that came with a kind and no date → (YYYY-MM-DD, how it was found, the reply line). Never raises: a failure reading the item's words or the items it waits after
    leaves tomorrow (until_write.fallback_date)."""
    today = _pages.zone_now().date()
    texts: list[str] = []
    try:
        for ln in str(next_text or "").splitlines():
            t = ln.strip().lstrip("-* ").strip()
            if t and not _model.is_owner(_steps.opener(t) or ""):
                texts.append(t.split(": ", 1)[1] if _steps.opener(t) and ": " in t else t)
        texts += [ln.strip().lstrip("-* ").strip() for ln in str(description or "").splitlines()]
    except Exception:  # noqa: BLE001  — the words only help to find a date
        texts = []
    other: list[str] = []
    for g in _wt.after_of(meta):
        try:
            other.append(_wt.until_of((_svcstore._load(g).get("metadata") or {})))
        except Exception:  # noqa: BLE001  — an item that cannot be read gives no date
            continue
    d, how, said = _uw.fallback_date(texts, today, _watch.parse_date, _wt.cap_days(), str(due or meta.get("due") or ""), other)
    return d, how, _uw.fallback_note(_uw.kind_of(meta), d, how, said)


def _record_fixes(meta: dict[str, Any], fixes: "list[tuple[str, str, str]] | None") -> None:
    """Put what a tool wrapper fixed onto the item's metadata (server_fixes.record): (fix, token, History line); a line of "" takes the mark off instead (the mover sent the value again)."""
    for fix, token, line in fixes or ():
        if line:
            _sf.record(meta, fix, token, line, time.time())
        else:
            _sf.unmark(meta, fix, token)
