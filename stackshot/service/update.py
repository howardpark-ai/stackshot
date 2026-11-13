"""update.py: updating, completing and confirming an item: every gate and every write of the update tool, in the order they ran in server.py.

`update_item` is the one place an item is updated: the update tool (`stackshot_update`, which stays on the surface and only parses its input, runs the checks that come before the item lock and shapes the reply), the complete
tool (`complete_item`: a close is an update with status=completed) and every write of an item that the server makes itself (a wake, a cold call, a script's row, the re-bullet route) come through it. It takes the item lock,
reads the item, runs the gates, applies the fields, the checklist, the wait, the hand-off and the close, saves the item through the write path (`writes.save`, with the write context its fields need: PLAIN, NAMED when the
write names the mover itself, QUIET when it only files or re-bullets), charges the page debt, tells the sessions the write concerns, publishes, and builds the reply. The order of those steps is part of what an update means and
is kept as it was in server.py. `confirm_item` only sets the `confirmed` clock (a QUIET save).

The gates and notices an update runs are still server.py's, because the create tool, the close and the telling run the same ones; they are reached through `Hooks`, which server.py fills once with `install` (this module cannot import
server.py: the surface sits above it), and each of them leaves `Hooks` when its area moves under service/ (the gates, then the telling). A hook is looked up on server.py when an update runs, so a suite that replaces a gate there
still reaches the update. The per-write flags of server.py that an update reads or sets stay thread-locals there until the areas that share them move, and are reached through `Hooks` too: `session_next` (the create or update tool's
own call), `reformat` (the re-bullet route), `terminal_row` (the terminal prompt's and the job-gap routes' row), `close_was_set` (the item as it stood before the close, for the telling) and `wake_event_set` (the minute loop).

Imports point down only: this module imports the domain and core and the store's readers beside it (service/store.py), never web/."""
from __future__ import annotations

import datetime as dt
import json
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from fastmcp.exceptions import ToolError

from stackshot.anchors import anchor_scope as _ascope
from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core.instance import OWNER
from stackshot.fleet.sessions_registry import _session_label
from stackshot.github import ghsync as _gh
from stackshot.model import activity as _activity
from stackshot.model import model as _model
from stackshot.model import model_guards as _mg
from stackshot.model import next_rules as _nr
from stackshot.model import nextlines as _nl
from stackshot.model import owner_steps as _hs
from stackshot.model import states as _states
from stackshot.model import step_commands as _sc
from stackshot.model import steps as _steps
from stackshot.model import work as _work
from stackshot.model.bullet_text import _clip_line
from stackshot.model.ids import _bare_id_ok, _norm_id
from stackshot.model.needs import _canon_needs, _needs_kinds, _needs_list, _needs_of, _needs_sessions, _needs_store, _waits_decision
from stackshot.projects import pages as _pages
from stackshot.service import writes as _writes
from stackshot.service.store import _load, _shown_ids
from stackshot.waits import handoff as _ho
from stackshot.waits import server_fixes as _sf
from stackshot.waits import until_write as _uw
from stackshot.waits import wait_end as _we
from stackshot.waits import waiting as _wt
from stackshot.waits import watchers as _watch


RETIRED_NOTE = ("\n(note: expected_by and expected_reason are no longer kept: a doing item carries no expected time and shows how long it has run. "
                "If it waits on a date or a person, park it: update(hold=true, until=\"YYYY-MM-DD\", wait_basis=\"<what it waits for, with its date YYYY-MM-DD>\"), or after=[\"board#N\"], "
                "or wait_kind=\"relay\" with wait_event=<who> and ask_by=<the day to chase>.)")

_STALE_WAIT_NOTE_MAX = 5

# A write whose every argument is one of these is bookkeeping on the item, not work on it: it names no background agent in needs
# (_name_on_write). A page rename moves many items with update(project=<new key>), and the mover, a background agent, must not be
# named in each one's needs as if it had begun working on it.
_FILING_ONLY = frozenset({"project", "subject", "priority", "owner_name", "observers", "contact", *_model.MODEL_FIELDS, "clear_goal", "clear_mover", "clear_then", "clear_wait"})


@dataclass(frozen=True)
class Hooks:
    """What an update still reaches in server.py (the gates and notices it shares with the create tool, the close and the telling, the per-write flags and a few constants), in the names they have there without the leading underscore;
    server.py builds one and gives it to `install`. A gate raises `ToolError` itself; a flag is a function that reads (or, `close_was_set`, writes) the thread-local."""
    actor_note: Callable[..., Any]
    after_open: Callable[..., Any]
    anchor_wait_gate: Callable[..., Any]
    ask_none: tuple[str, ...]      # the words that mean no ask, no observers, no check (server._ASK_NONE)
    ask_owed: Callable[..., Any]
    basis_put: Callable[..., Any]
    basis_words: str                  # how the wait_basis gate names what a park waits on (server._BASIS_WORDS)
    cap_ok_drop: Callable[..., Any]
    cap_ok_put: Callable[..., Any]
    check_how: str                    # the forms of a done check (server._CHECK_HOW)
    close_was_set: Callable[[Any], None]    # remember on this thread the item as it stood before the close being saved (server._CLOSE_WAS.item), None when it ends: the close is told to the mover it dropped
    contact_alive: Callable[..., Any]
    contact_fronts: Callable[..., Any]
    contact_same: Callable[..., Any]
    date_only_wait: Callable[..., Any]
    date_parked: Callable[..., Any]
    eff_state: Callable[..., Any]
    evwait_preread: Callable[..., Any]
    fallback_wait_date: Callable[..., Any]
    finishes_own_line: Callable[..., Any]
    fmt: Callable[..., Any]
    form_notes: Callable[..., Any]
    front_sender: Callable[..., Any]
    gate_after: Callable[..., Any]
    gate_alternatives: Callable[..., Any]
    gate_ask: Callable[..., Any]
    gate_ask_on_wait: Callable[..., Any]
    gate_bare_urls: Callable[..., Any]
    gate_cap: Callable[..., Any]
    gate_clock_renewal: Callable[..., Any]
    gate_close: Callable[..., Any]
    gate_contact: Callable[..., Any]
    gate_decision_again: Callable[..., Any]
    gate_description: Callable[..., Any]
    gate_draft: Callable[..., Any]
    gate_draft_args: Callable[..., Any]
    gate_front_step: Callable[..., Any]
    gate_goal: Callable[..., Any]
    gate_handoff: Callable[..., Any]
    gate_metadata: Callable[..., Any]
    gate_mockup: Callable[..., Any]
    gate_model: Callable[..., Any]
    gate_model_args: Callable[..., Any]
    gate_needs: Callable[..., Any]
    gate_needs_session: Callable[..., Any]
    gate_next: Callable[..., Any]
    gate_observers: Callable[..., Any]
    gate_one_decision: Callable[..., Any]
    gate_open_question: Callable[..., Any]
    gate_options: Callable[..., Any]
    gate_own_action: Callable[..., Any]
    gate_owner_step: Callable[..., Any]
    gate_recommend_stance: Callable[..., Any]
    gate_repark: Callable[..., Any]
    gate_said: Callable[..., Any]
    gate_sender_watch: Callable[..., Any]
    gate_state_args: Callable[..., Any]
    gate_step: Callable[..., Any]
    gate_step_gap: Callable[..., Any]
    gate_subject: Callable[..., Any]
    gate_wait_basis: Callable[..., Any]
    gate_work_writer: Callable[..., Any]
    handoff_notify: Callable[..., Any]
    handoffs_in: Callable[..., Any]
    handover: Callable[..., Any]
    ho_derive: Callable[..., Any]
    ho_same: Callable[..., Any]
    hold_held_by: Callable[..., Any]
    hold_set: Callable[..., Any]
    holder: Callable[..., Any]
    is_held: Callable[..., Any]
    lift_ask: Callable[..., Any]
    machine_note: Callable[..., Any]
    main_agent: Callable[..., Any]
    marks_given: Callable[..., Any]
    mentions_reply: Callable[..., Any]
    model_apply: Callable[..., Any]
    model_guards_on: Callable[..., Any]
    model_of: Callable[..., Any]
    nag: Callable[..., Any]
    name_on_write: Callable[..., Any]
    next_put: Callable[..., Any]
    nl_text_without: Callable[..., Any]
    options_note: Callable[..., Any]
    owed_mark: Callable[..., Any]
    owner_quote_on: Callable[..., Any]
    owner_reached: Callable[..., Any]
    owner_state_mover: Callable[..., Any]
    owner_then_default: Callable[..., Any]
    owner_want: Callable[..., Any]
    page_keeper: Callable[..., Any]
    parse_check: Callable[..., Any]
    parse_wake: Callable[..., Any]
    pilot_charge: Callable[..., Any]
    pilot_relay: Callable[..., Any]
    publish: Callable[..., Any]
    push_noted: Callable[..., Any]
    quiet: Callable[..., Any]
    record_fixes: Callable[..., Any]
    reformat: Callable[[], bool]          # the re-bullet route's update (server._REFORMAT): a description in bullets with the same content is a filing edit
    refuse_if_owing: Callable[..., Any]
    release_after: Callable[..., Any]
    render_hold_at: Callable[..., Any]     # web/render.py's hold_at, option_lines, same_ref and when_words (web/ sits above this module)
    render_option_lines: Callable[..., Any]
    render_same_ref: Callable[..., Any]
    render_when_words: Callable[..., Any]
    require_marks: Callable[..., Any]
    said_note: Callable[..., Any]
    scoped_anchors: Callable[..., Any]
    session_id: Callable[..., Any]
    session_next: Callable[[], bool]      # the create or update tool's own call (field_gates._SESSION_NEXT): only a session's write is judged by the write checks of Next
    session_roster: Callable[..., Any]
    state_apply: Callable[..., Any]
    state_end: Callable[..., Any]
    step_proof_prune: Callable[..., Any]
    step_proof_set: Callable[..., Any]
    store_ref: Callable[..., Any]
    switchover_on: Callable[..., Any]
    tell_decided: Callable[..., Any]
    tell_handback: Callable[..., Any]
    tell_needed: Callable[..., Any]
    tell_observers: Callable[..., Any]
    tell_owner: Callable[..., Any]
    tell_owner_change: Callable[..., Any]
    tell_owner_close: Callable[..., Any]
    terminal_row: Callable[[], bool]      # the terminal prompt's and the job-gap routes' row (server._TERMINAL_ROW): it owes no page and no session is told
    update: Callable[..., Any]
    wait_end_sent_back: Callable[..., Any]
    wake_at: Callable[..., Any]
    wake_event_set: Callable[[], None]     # wake the minute loop at once (server._WAKE_EVENT.set()) when a wake or a hold changed
    wake_park_line: Callable[..., Any]
    wake_step_note: Callable[..., Any]
    wake_window_note: Callable[..., Any]
    watch_on_write: Callable[..., Any]
    writer_charge: Callable[..., Any]
    writer_owes: Callable[..., Any]
    zone: Callable[..., Any]               # the board's time zone as server.py holds it (ZONE, read when the reply is made): the confirm reply says when in it


_hooks_: Hooks | None = None


def install(hooks: Hooks) -> None:
    """Give the update the gates and notices that are still server.py's (once, at its import)."""
    global _hooks_
    _hooks_ = hooks


def _hooks() -> Hooks:
    if _hooks_ is None:
        raise RuntimeError("the update has no hooks installed (server.py installs them at its import)")
    return _hooks_


def _wait_is_bare(m: dict[str, Any]) -> bool:
    """A date with nothing else stated beside it: no hold, no kind, no basis, no after link (the date is then a wait on that date alone, outside a hand-off)."""
    return _uw.is_bare(m)


def _hands_on(gid: str, was: dict[str, Any], now_item: dict[str, Any], handed: Any, writer: str, failed: list[bool] | None = None) -> bool:
    """Does this write hand the item on to a session: a hand-off line in next, or a change of the DERIVED mover (what the hand-off record reads, handoff.detect): a mover argument, needs naming a
    session, a reopen with one. The date a bare wait carries is left out of both readings (an item with it reads as waiting and has no mover), so the question is the write's own: with the date
    it gives (or already held) set aside, did the mover change to a session other than the writer? A hand-off to the owner is none here (his step with a date is a park of its own). A reading that fails counts as a hand-off (fail closed), and says so in `failed` when the caller passes a list."""
    h = _hooks()
    if handed:
        return True
    try:
        def undated(it: dict[str, Any]) -> dict[str, Any]:
            m = it.get("metadata") or {}
            return {**it, "gid": gid, "metadata": {k: v for k, v in m.items() if k not in ("wake", "until", "ask_by")}} if _wait_is_bare(m) else {**it, "gid": gid}
        to = _ho.detect(undated(was), undated(now_item), _session_label(writer) or writer, writer if _anc.is_id(writer) else "", h.ho_derive, h.ho_same)
        return bool(to) and not _model.is_owner(to)
    except Exception as e:  # noqa: BLE001  — the reading is an extra: a failure fails closed, the date stays the hand-off's backstop and the item stays active (a park that hides a hand-off costs more than a date left as a wake)
        print(f"handoff: {gid} backstop not judged: {e.__class__.__name__}: {e}; the date stays a backstop and the item stays active", file=sys.stderr, flush=True)
        if failed is not None:
            failed.append(True)
        return True


def _retired_note(*vals: Any) -> str:
    """The reply note for a write that passes expected_by or expected_reason (accepted and dropped), "" when it passes neither."""
    return RETIRED_NOTE if any(str(v or "").strip() for v in vals) else ""


def _next_names_session(next_text: str, who: str) -> bool:
    """Does a line of next start with `<session>:` for this session (a hand-off line)?"""
    h = _hooks()
    if not who or not str(next_text or "").strip():
        return False
    nm = _anc.names()
    cw = _anc.canonical(who, nm)
    return any(s == who or _anc.canonical(s, nm) == cw for s in h.handoffs_in(next_text, h.session_roster()))


def _wait_refs(meta: dict[str, Any], names: tuple[str, ...]) -> set[str]:
    """The store ids of the items a wait's free-text fields name as `board#N` (wait_anchor, wait_event)."""
    out: set[str] = set()
    for k in names:
        for r in _mg._BOARD_REF_RX.finditer(str(meta.get(k) or "")):
            try:
                out.add(_norm_id(f"board#{r.group(1)}"))
            except Exception:  # noqa: BLE001
                continue
    return out


def _stale_wait_notes(item_was: dict[str, Any], item: dict[str, Any], keeper: str = "") -> str:
    """The reply lines of a write that cleared a wait while the item's open next lines still defer on what it cleared: the items the wait named before (the after list, and the
    board#N its wait_anchor or wait_event named) and no longer names, then every open next line that defers on one of them in words (model_guards.deferral_refs, the matcher of the
    next_defers guard) → one `(note: next line N still waits on board#X, …)` line each, at most five and then a count; N is the line's position in the checklist (the one done= and reword= take).
    No refusal: the write has gone through, and the writer fixes the lines in the same turn. "" when nothing was cleared or no line is stale."""
    if item.get("status") != "open":
        return ""
    old, new = item_was.get("metadata") or {}, item.get("metadata") or {}
    ids = lambda m_: {str(x) for x in (m_.get("after") or []) if str(x).strip()}
    refs = lambda m_: _wait_refs(m_, ("wait_anchor", "wait_event"))
    gone = (ids(old) | refs(old)) - (ids(new) | refs(new))      # an item that moves from one store of the wait to the other is still waited on
    if not gone:
        return ""
    lines: list[str] = []
    for i, st in enumerate(_steps.view(new, keeper=keeper), 1):
        if st["status"] != _steps.OPEN:
            continue
        hit: list[str] = []
        for _ln, refs in _mg.deferral_refs(st["text"]):
            for r in refs:
                try:
                    g = _norm_id(r)
                except Exception:  # noqa: BLE001
                    continue
                if g in gone and r not in hit:
                    hit.append(r)
        if hit:
            lines.append(f"(note: next line {i} still waits on {', '.join(hit)}, whose wait was just cleared: reword it)")
    if len(lines) > _STALE_WAIT_NOTE_MAX:
        lines = lines[:_STALE_WAIT_NOTE_MAX] + [f"(note: {len(lines) - _STALE_WAIT_NOTE_MAX} more next lines still wait on an item whose wait was just cleared)"]
    return "".join("\n" + ln for ln in lines)


def _mark_next_stale(item_was: dict[str, Any], item: dict[str, Any], meta: dict[str, Any], writer: str, naming_added: list[str], next_passed: bool) -> None:
    """A write by a session that is neither the item's mover nor named by its next, which changes needs, state, hold, wake or after and not next, marks next
    as needing a rewrite (metadata.next_stale {by, fields, at}), until a write passes next."""
    h = _hooks()
    if next_passed:
        meta.pop("next_stale", None)
        return
    m0 = item_was.get("metadata") or {}
    chg = []
    if sorted(x for x in _needs_of(meta) if x not in naming_added) != sorted(_needs_of(m0)):
        chg.append("needs")
    if m0.get("state") != meta.get("state") and h.eff_state(item_was) != h.eff_state(item):      # a stored state that moved the state read (a hold or an after link changes the derived one by itself: that is hold, after)
        chg.append("state")
    for k in ("hold", "wake", "after"):
        if (bool(m0.get(k)) if k == "hold" else m0.get(k) or None) != (bool(meta.get(k)) if k == "hold" else meta.get(k) or None):
            chg.append(k)
    if not chg:
        return                                             # nothing it watches changed: no roster or fleet read
    if not writer or h.session_id(writer) in {h.session_id(h.holder(item_was)), h.session_id(h.holder(item))}:
        return
    if _next_names_session(str(m0.get("next") or ""), writer):
        return
    old = meta.get("next_stale") if isinstance(meta.get("next_stale"), dict) else {}
    meta["next_stale"] = {"by": _session_label(writer) or writer, "fields": list(dict.fromkeys([*(old.get("fields") or []), *chg])), "at": time.time()}


def _handoff_to(was: dict[str, Any], meta: dict[str, Any], next_: str, writer: str) -> list[str]:
    """The sessions an update hands the item to, the gate's trigger: a `<session>: <action>` line of the next this write passes
    (_handoffs_in); never the mover or the writer, and never one the stored next or needs already named (that hand-off was made
    earlier, by a write this rule saw or did not see; a session in needs is asked about the item at each of its turn ends anyway,
    so a write that only names one there is not gated). → their names, [] when the write creates no hand-off."""
    h = _hooks()
    if not str(next_ or "").strip():
        return []
    nm = _anc.names()
    roster = h.session_roster()
    skip: set[str] = set()
    for who in (h.holder({"status": "open", "metadata": meta}), h.holder({"status": "open", "metadata": was}), str(writer or "")):
        if who:
            sid = _anc.canonical(who, nm)
            skip |= {who, sid, str(nm.get(sid) or ""), _session_label(who)}
    skip.discard("")
    now_named = set(h.handoffs_in(next_, roster))
    before = set(_needs_sessions(was)) | set(_needs_sessions(meta)) | set(h.handoffs_in(str(was.get("next") or ""), roster))
    before |= {_anc.canonical(s, nm) for s in before}
    return [s for s in sorted(now_named) if s not in skip and _anc.canonical(s, nm) not in skip and s not in before and _anc.canonical(s, nm) not in before]


def _contact_after_move(meta: dict[str, Any], new_project: str) -> str:
    """The contact an item has once it is filed under `new_project`: the stored one when it is a front agent of that project (a page rename moves the keys of a project that
    keeps its agents) or the item's creator while that is a front agent of any project, else the new project's -main agent. "" when neither can be named."""
    h = _hooks()
    c = str(meta.get("contact") or "").strip()
    if c and (any(h.contact_same(f, c) for f in h.contact_fronts(new_project)) or (h.contact_same(c, str(meta.get("owner") or "")) and h.contact_alive(c))):
        return c                                  # a front agent there too, or the creator that is a front agent (of any project): the front agent that made the item stays its contact
    main = h.main_agent(new_project)
    return h.store_ref(main) if main else ""


def _doing_wait_note(meta: dict[str, Any], next_: str = "") -> str:
    """A valid reason to wait on an item does not warrant marking it as on agent and letting it sit there for hours: it should be marked waiting.
    A note on the reply (never a refusal) when the item ends the write in the stored state doing, not on hold, and a line of next this write set reads as a wait on a time or an event
    rather than work in hand (model_guards.reads_as_wait)."""
    if meta.get("state") != "doing" or meta.get("hold"):
        return ""
    found = _mg.reads_as_wait(next_) if next_ else ""
    if not found:
        return ""
    return (f"\n(note: this item is doing, but its next reads as a wait ({found}), not work in hand; a doing item that waits shows as on an agent while nobody works it. "
            "Park it this turn with update(hold=true, until=\"<the time it waits for>\", wait_basis=\"<what it waits on, with its date YYYY-MM-DD>\"))")


def _fix_loose_reason(item: dict[str, Any], meta: dict[str, Any], next_after: Any, description: str, wake_in: str) -> "tuple[str, tuple[str, str, str]]":
    """The write's own fix of a hold that has a wake and no reason (server_fixes.WAIT_REASON): the item's own next, as this write leaves it, or its description says the work waits for the wake's own
    day ("collect the logs until 2099-03-02, then review"), so that line is the wait_basis (the reply and History say so) in place of the refusal the model guard would give for a time wait with no
    reason. Nothing for an item that waits on the owner or that he moves (the hold is refused as before), an item that already carries a basis for this wake, a wake the reader cannot parse, or a line the basis gate
    would not pass. → (the wait_basis, (the reply note, the wake, the History line)), ("", ("", "", "")) when there is none."""
    h = _hooks()
    none = ("", ("", "", ""))
    try:
        if _waits_decision(meta) or _wt.basis_of(meta) or str(_wt.words_of(meta).get("quote") or "").strip() or not (wake_in or _wt.wake_value(meta)):
            return none
        mod = h.model_of(item)
        if mod.state != _model.ALIVE or not mod.mover or _model.is_owner(mod.mover):      # an item the owner moves (or in any owner state) is his: the hold stays refused as before
            return none
        wk = h.parse_wake(wake_in) if wake_in else str(_wt.wake_value(meta) or "")
        where, line = "", ""
        for where_, text in (("next", next_after), ("description", description)):
            line = _mg.window_line(text, wk)
            if line:
                where = where_
                break
        if not line:
            return none
        day = h.wake_at(wk).date().isoformat()
        words = " ".join(_steps.strip_opener(line).split())
        basis = f"{words[:240]} (wake {day})" if day not in words else words[:260]
        h.gate_wait_basis({**item, "metadata": {**meta, "wake": wk}}, basis, wk, held=True)
        note = (f"\n(fixed: this hold had a wake and no wait reason, and your {where} says what it waits for (\"{_clip_line(words, 90)}\"), so that line is the wait_basis. "
                "Send wait_basis=\"<what it waits on, with its date YYYY-MM-DD>\" to use other words: the server then leaves the field alone)")
        return basis, (note, wk, f"wait reason: the hold had a wake and no reason; the {where} line \"{_clip_line(words, 80)}\" is its wait_basis. A wait_basis sent in a later write replaces it")
    except Exception as e:  # noqa: BLE001  — the fix is an extra: a failure leaves the write as it was, with the refusal
        if not isinstance(e, ToolError):
            print(f"loose wait reason: not judged: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return none


def _reads_time_wait(item: dict[str, Any]) -> bool:
    """The model reads the open item as a wait on a time with no hold flag: a verifying item (its end date is its wait), or any item the model reads as a time wait (wait_kind=time). The snooze guard
    (model_guards) asks such a wait for its reason like a hold's, so update takes a wait_basis for its wake at any length, as it does for a held item; a wake an alive item
    carries as a hand-off's backstop (no until) is not a wait and reads False."""
    h = _hooks()
    if item.get("status") != "open":
        return False
    try:
        mod = h.model_of(item)
    except Exception:  # noqa: BLE001
        return False
    return mod.state == _model.WAITING and mod.wait is not None and mod.wait.kind == "time"


def update_unlocked(
    item_id: str,
    subject: str = "",
    description: str = "",
    status: str = "",
    next: str = "",
    needs: list[str] | str = "",
    priority: str = "",
    due: str = "",
    anchors: list[str] | None = None,
    owner: str = "",
    owner_name: str = "",
    clear_needs: bool = False,
    project: str = "",
    sender: str = "",
    clear_due: bool = False,
    wake: str = "",
    clear_wake: bool = False,
    hold: bool = False,
    clear_hold: bool = False,
    ask: str = "",
    recycle: bool = False,
    clear_recycle: bool = False,
    outcome: str = "",
    reason: str = "",
    superseded_by: str = "",
    options: list[dict[str, Any]] | str | None = None,
    agent: str = "",
    observers: list[str] | str | None = None,
    after: list[str] | str | None = None,
    work: dict[str, Any] | str | None = None,
    said: list[dict[str, Any]] | str | None = None,
    check: str = "",
    clear_options: bool = False,
    clear_ask: bool = False,
    clear_after: bool = False,
    wait_basis: str = "",
    clear_wait_basis: bool = False,
    expected_by: str = "",
    expected_reason: str = "",
    step: str = "",
    supplies: str = "",
    goal: str = "",
    mover: str = "",
    then: str = "",
    wait_kind: str = "",
    wait_anchor: str = "",
    wait_event: str = "",
    ask_by: str = "",
    post_wake_mover: str = "",
    clear_goal: bool = False,
    clear_mover: bool = False,
    clear_then: bool = False,
    clear_wait: bool = False,
    draft: str = "",
    clear_draft: bool = False,
    clear_next: bool = False,
    clear_check: bool = False,
    done: list[int | str] | int | str | None = None,
    dropped: list[int | str] | int | str | None = None,
    step_proof: list[dict[str, Any]] | str | None = None,
    watch_reason: str = "",
    wait_reason: str = "",
    outcome_text: str = "",
    contact: str = "",
    reword: dict[Any, str] | str | None = None,
    fixes: "list[tuple[str, str, str]] | None" = None,
    until_wait: bool = False,
) -> str:
    """The update tool; its description is _UPDATE_DESC (+ _WAIT_FORM). The caller checks the identity (_who): the update and
    complete tools do, the client API's recycle-due write is proved by its machine token instead."""
    if not _steps.reword_given(reword):
        reword = None             # {} and "{}" name no step: the call is as if it passed none
    given = {k: v for k, v in locals().items() if k not in ("item_id", "sender", "wait_reason", "fixes", "until_wait") and v not in (None, "", False, 0)}      # what the call passes, before any default or rewrite below
    h = _hooks()
    filing_only = bool(given) and set(given) <= _FILING_ONLY      # a bookkeeping write (a page rename's update(project=<new key>)): no work was done, so no agent is named for it
    subject, description, next, ask, reason, outcome_text = (_shown_ids(x) for x in (subject, description, next, ask, reason, outcome_text))   # g7 →
    next_drop = next.strip().lower() in _nl.NONE_WORDS   # next="none" (or clear, -) removes the sender's own lines, as "none" clears due, wake and needs; an empty next is "not passed"
    if next_drop:
        next = ""
    next_touch = bool(next.strip()) or clear_next or next_drop   # this call writes next: lines added or replaced, the sender's removed, or all of them wiped
    if due.strip().lower() in ("none", "clear", "-"):   # works from any cached tool schema, where clear_due may not exist yet
        due, clear_due = "", True
    if wake.strip().lower() in ("none", "clear", "-"):  # the same for wake
        wake, clear_wake = "", True
    if isinstance(needs, str) and needs.strip().lower() in ("none", "clear", "-"):  # and for needs: an older tool list may lack clear_needs
        needs, clear_needs = "", True
    needs_set = bool(needs) if isinstance(needs, list) else bool(needs.strip())   # needs= replaces the whole list; [] clears like "none"
    if isinstance(needs, list) and not needs:
        clear_needs = True
    wake = wake.strip()
    if clear_ask and ask.strip() and ask.strip().lower() not in h.ask_none:
        raise ToolError("Refused: clear_ask drops the ask; it does not go with a new ask")
    clear_ask = clear_ask or ask.strip().lower() in h.ask_none       # ask="none" or clear_ask=true clears it, like due and wake
    ask = "" if clear_ask else (h.gate_ask(ask) if ask else "")
    opts = h.gate_options(options)                     # None: not passed; []: clear
    if clear_options:                                 # the flag, like clear_wake: the same as options=[] / "none"
        if opts:
            raise ToolError("Refused: clear_options drops the options; it does not go with a new list")
        opts = []
    gid = _norm_id(item_id, bare=_bare_id_ok(status))
    item = _load(gid)
    had_hold = bool((item.get("metadata") or {}).get("hold"))      # read before the unfold, which stands a basis or the kind time in as a hold
    was_until = _uw.unfold_item(item)                    # a stored until stands as the old working fields for this write's gates (until_write.py); it is folded back just before the save
    if was_until and clear_wake and _uw.kind_of(item["metadata"]) in ("", "time") and not had_hold:
        clear_hold = True                                # the date of a wait on the date alone is the whole wait: dropping it ends the wait, the hold it stands as goes with it
    item_was = json.loads(json.dumps(item))             # the item as it stood, for the state checks (a re-park, a decision asked again, a stale next)
    meta = dict(item.get("metadata") or {})
    before = json.loads(json.dumps({k: meta.get(k) for k in ("next", "needs", "check", "after")}))   # what the mover is told of, as it stood
    ask_was = meta.get("ask")
    meta.pop("refiled", None)                          # the last refile's record is its History line; only a write that refiles carries it
    was_needs = _needs_of(meta)
    proj_for = project or str(meta.get("project") or "")
    own_for = owner or h.holder(item)       # the session the item is held by (its mover), which needs may name and which writes step statuses; the creator holds no part
    contact_new = ""
    if contact.strip():                    # the contact: a front agent of the project the item will be filed under; refused before anything is written
        if (status or item.get("status")) == "completed":
            raise ToolError(f"Refused: {_gh.shown(gid)} is completed and keeps the contact it had as its record; reopen it (status=open with a next) before changing the contact")
        contact_new = h.gate_contact(contact, proj_for, (str(meta.get("owner") or ""), str(meta.get("contact") or "")))
    if needs_set:
        _needs_store(meta, h.gate_needs(needs, proj_for, own_for, _model.norm_who(meta.get("then"))))
    if agent.strip():                                  # the older form: that session becomes the one named in needs; "none" takes the sessions out
        kinds = _needs_kinds(meta)
        if agent.strip().lower() in h.ask_none:
            _needs_store(meta, _canon_needs(kinds))
        else:
            _needs_store(meta, _canon_needs([*kinds, h.gate_needs_session(agent, proj_for, own_for, _model.norm_who(meta.get("then")))], _anc.names()))
    state_st, state_given, step_withdrawn = h.gate_state_args({"expected_by": expected_by, "expected_reason": expected_reason, "step": step, "supplies": supplies})   # a bad value is refused before anything is written
    draft_set, clear_draft = h.gate_draft_args(draft, clear_draft)   # a bad draft is refused before anything is written
    model_set, model_drop = h.gate_model_args({"goal": goal, "mover": mover, "then": then, "wait_kind": wait_kind, "wait_anchor": wait_anchor, "wait_event": wait_event,
                                              "ask_by": ask_by, "post_wake_mover": post_wake_mover},
                                             {"goal": clear_goal, "mover": clear_mover, "then": clear_then, "wait": clear_wait})   # a bad value is refused before anything is written
    clear_obs = observers is not None and (observers == [] or (isinstance(observers, str) and observers.strip().lower() in h.ask_none))
    if clear_obs:
        meta.pop("observers", None)
    elif observers is not None and (observers if isinstance(observers, list) else observers.strip()):
        meta["observers"] = h.gate_observers(observers)
    # after=[] and after="none" clear it, and so does clear_after=true: a client (claude.ai's connector, found once) drops
    # an empty list before it reaches the server, so the flag is the form that survives it, like clear_needs and clear_due
    clear_after = clear_after or (after is not None and (after == [] or (isinstance(after, str) and after.strip().lower() in h.ask_none)))
    after_set = after is not None and not clear_after and bool(after if isinstance(after, list) else after.strip())
    if clear_after and after is not None and (after if isinstance(after, list) else str(after).strip()) and not (isinstance(after, str) and after.strip().lower() in h.ask_none):
        raise ToolError("Refused: clear_after drops the after list; it does not go with a new one")
    if clear_after:
        meta.pop("after", None)
        if _uw.kind_of(meta) == "item" and not wait_kind.strip() and not clear_wait and was_until and _uw.date_of(meta):
            meta.pop("wait_kind", None)                  # the wait on the item ended with its link; the date it carried stays as a wait on the date alone
        h.wait_end_sent_back(meta, (_we.ITEM,))          # a wait the server set from the line's words, sent back: the server leaves that line alone
    elif after_set:
        meta["after"] = h.gate_after(after, gid)
    nm = _anc.names() if owner else {}                 # the fleet's names, read once for the owner and its name
    raw, owner = owner.strip(), (_anc.canonical(owner, nm) if owner else "")   # = _session_id: a pane name → its transcript id
    if owner and not owner_name and owner != _anc.canonical(str(meta.get("owner") or ""), nm):
        # A new owner without owner_name: the name follows it, else the old owner's name stayed and its session's board check
        # (_client_items, by owner or owner_name) kept asking about the item it handed over. The name
        # the fleet knows for the new owner; the name it was given as when the fleet knows none; else no name (a stale one is
        # worse than none: the board falls back to the fleet, the cloud title or the id).
        owner_name = nm.get(owner, "") or ("" if _anc.is_id(raw) else raw)
        if not owner_name:
            meta.pop("owner_name", None)
    debtor = h.session_id(sender or owner or h.holder(item))     # the writer owes the page; without a sender, the item's mover is the writer by rule
    keeper_was = str((item_was.get("metadata") or {}).get("owner") or "")      # the creator as it stood: the writer of the legacy lines
    next_writer = keeper_was if keeper_was and (sender.strip() == _ho.COLD or sender.strip().startswith("a script on ")) else debtor      # a line the server writes (the cold call's, a script's) is the keeper's, which a session can replace; a sender label is no session
    # a background agent's first write names it, before any gate on who may write (a step status) reads the needs list
    # only plain work names it: a write that sets needs (none included, or agent=), a hold or wake, or a recycle leaves needs as it says
    # finishing your own step (work with state done, nothing else that does work) is no new work either, also when the
    # line was already done: it named the finisher in needs each time
    finishing = bool(sender.strip()) and set(given) <= {"work", "said"} and h.finishes_own_line(work, meta, _session_label(h.session_id(sender.strip())), str(item.get("status") or "") == "open")
    plain = not (needs_set or clear_needs or agent.strip() or hold or clear_hold or wake or clear_wake or recycle or clear_recycle or filing_only or finishing)
    pre_named = _needs_of(meta)
    name_commit = h.name_on_write(gid, item, meta, sender, str(item.get("status") or ""), was_needs, status == "completed", plain)      # carried into meta now, stored just before the write's own save
    naming_added = [s for s in _needs_of(meta) if s not in pre_named]       # the sessions the server itself named (the writer, a background agent): not a change the writer made
    before["needs"] = _needs_list(before.get("needs")) + naming_added   # the server's own naming of the writer is no change of the writer's to tell the mover of
    work_spec = None            # the status of the sender's open step set or cleared; a filing edit (no page owed, the state clock and the confirm stay) unless it ticks or makes a step
    work_tick, work_who, work_made, work_skip = -1, "", "", ""
    if work is not None and (work if isinstance(work, (dict, list)) else str(work).strip()):
        try:
            work_spec = _work.parse(work)
        except ValueError as e:
            raise ToolError(f"Refused: {e}")
        work_spec["text"] = _shown_ids(work_spec.get("text") or "")   # g7 → board#N, after the length check
        work_writer = _session_label(h.session_id(sender.strip() or own_for))   # the writer by name; the session whose step it is, unless the spec names another
        h.gate_work_writer(gid, work_writer, h.holder({"status": "open", "metadata": meta}), meta, finishing)                      # the needs list as this call leaves it
        if work_spec.get("agent"):
            work_spec["agent"] = _session_label(h.session_id(work_spec["agent"]))
        work_who = work_spec.get("agent") or work_writer
        if str(item.get("status") or "") != "open":
            work_skip = "the item is closed: its checklist is the record, and a status is written on an open step"
        else:
            nm_w = _anc.names()
            same_w = lambda x, y: bool(x) and bool(y) and (x == y or _anc.canonical(x, nm_w) == _anc.canonical(y, nm_w))
            ti_w = _work.step_of(_steps.view(item_was.get("metadata"), keeper=keeper_was), work_who, same_w)       # the sender's first open step, as the item stood
            in_next_w = any(same_w(_steps.opener(c), work_who) for c in _steps.split(next))                       # …or a step of the sender's this call writes
            if work_spec["remove"]:
                if ti_w < 0 and not in_next_w:
                    work_skip = f"{work_who} has no open step on the item, so there is no status to clear"
            elif work_spec["state"] == "done":
                if ti_w >= 0:
                    work_tick = ti_w                                   # the status done ticks the step, as done=[n] does
                elif not in_next_w:
                    work_skip = f"{work_who} has no open step on the item to finish; the stage you finished is marked with done=[n] on the step, or not a step of the item"
            elif ti_w < 0 and not in_next_w:                           # no open step: one is made from the text, for the sender, at the end of its lines
                if not work_spec["text"]:
                    raise ToolError(f"Refused: work: {work_who} has no open step on {_gh.shown(gid)}, so the status needs its text: it makes the step. {_work.FORM}")
                work_made = f"{work_who}: {work_spec['text']}"
                kept_own = _nl.text_of(meta, next_writer, keeper_was, h.ho_same)                     # the sender's lines stay: next replaces them as a whole
                next = (next.rstrip() + "\n" if next.strip() else (kept_own.rstrip() + "\n" if kept_own.strip() else "")) + work_made
                next_touch = True
    said_l = h.gate_said(said, sender.strip() or own_for, debtor)   # the trailers: his words checked against the transcript; a failed check refuses the write here
    reformat = bool(description) and bool(h.reformat())   # a re-bullet changes the form of the description, never what it says: the state clock and the confirm stay, no page is owed
    rewording = _steps.reword_given(reword)      # reword={position: new text}: an open step's words change; an empty mapping ({} or "{}") is not given
    marks = h.marks_given(done) or h.marks_given(dropped) or rewording or work_tick >= 0      # a step checked, dropped or reworded is a change of next; so is the step a status done ticks
    state_change = bool((description and not reformat) or next_touch or marks or needs_set or clear_needs or status or due or clear_due or wake or clear_wake or hold or clear_hold or after_set or clear_after)   # _STATE_FIELDS (+ the hold and its wake, and after); the rest is filing
    was, was_held = item.get("status"), h.is_held(item)
    was_parked = was_held or h.date_parked(item, was_until)      # (the relay line and the minute loop read a wait on a date as the park it replaces; the reply notes read the hold flag alone)
    outcome, reason, superseded_by = outcome.strip().lower(), reason.strip(), superseded_by.strip()
    closing, reopening = status == "completed" and was != "completed", status == "open" and was == "completed"
    outcome_text = outcome_text.strip()
    if closing and description.strip():      # a caller that predates outcome_text still sends the end state as the description: it is the outcome text now, and the description stays as it was
        if description.strip() == str(item.get("description") or "").strip():
            description = ""      # the description passed is the stored one (a caller that sends the item back whole): nothing to change, the outcome text is what the close says
        elif outcome_text:
            raise ToolError(f"Refused: a close takes the end state as outcome_text and never changes the description; this call passes both. Pass the end state as outcome_text alone; "
                            f"to change what {gid} is about, update its description before or after the close.")
        else:
            outcome_text, description = description.strip(), ""
    if closing:                   # a close says how the item ended
        superseded_by = h.gate_close(gid, item, outcome, reason, superseded_by, outcome_text)
    elif outcome or reason or superseded_by or outcome_text:
        raise ToolError(f"Refused: outcome, outcome_text, reason and superseded_by go with a close (status=completed on an open item, or the complete tool)"
                        + (f"; {gid} is already completed: to correct its close, reopen it (status=open with a next) and close it again"
                           if was == "completed" else ""))
    if reopening and not next.strip():
        raise ToolError(f"Refused: reopening {gid} needs a new next: the step that comes now")
    if draft_set and (status or item.get("status")) == "completed":
        raise ToolError("Refused: a completed item keeps no draft (a close drops it); draft goes with an open item")
    if state_change:
        h.refuse_if_owing(debtor)
    h.gate_bare_urls({"description": description, "next": next, "ask": ask}, {"description": item_was.get("description"), "next": meta.get("next"), "ask": ask_was})   # only the fields this call sets; a stored bare URL is no reason to refuse
    if subject:
        h.gate_subject(subject, str(item.get("subject") or ""))
        item["subject"] = subject
    if description:
        h.gate_description(description)
        if (h.session_next() and not reformat and not sender.strip().startswith("a script on ")
                and description.strip() != str(item_was.get("description") or "").strip()):     # a replacement of the text by a session, not the stored text sent back
            h.gate_goal(description)
        item["description"] = description
    if next:
        h.gate_next(next, has_ask=bool(ask.strip()) and ask.strip().lower() not in h.ask_none)
    steps_on = was != "completed" or reopening          # a closed item's checklist is its record: no write touches it until the item is reopened
    if marks and not steps_on:
        raise ToolError(f"Refused: {_gh.shown(gid)} is closed and its checklist is the record of what was done; reopen it (status=open with a next) before marking or rewording a step")
    if rewording and (closing or clear_next):
        raise ToolError("Refused: reword changes the words of a step that stays open; " + ("a close marks every open step, so reword goes with a call that keeps the item open" if closing else "clear_next=true wipes every line, so reword goes with a call that keeps them"))
    steps_old = _steps.view(item_was.get("metadata"), keeper=keeper_was) if steps_on else []          # the checklist as it stood: the stored steps lined up with the lines of next, each open one with its writer
    steps_before = list(steps_old)          # …as the write found it: a reword below replaces entries of steps_old, and the front-agent step check judges the new words against these
    steps_by = _session_label(debtor) or debtor or "unknown"
    try:
        done_ix, drop_ix = _steps.resolve(steps_old, done, "done"), _steps.resolve(steps_old, dropped, "dropped")
        reword_ix = _steps.resolve_reword(steps_old, reword) if rewording else {}
        if work_tick >= 0 and work_tick not in done_ix and work_tick not in drop_ix:
            done_ix.append(work_tick)
        if both := sorted(set(reword_ix) & {*done_ix, *drop_ix}):
            raise _steps.StepError(f"step {both[0] + 1} is in reword and in done or dropped ({_steps.first_line(steps_old[both[0]]['text'])[:90]}); pick one")
    except _steps.StepError as e:
        raise ToolError(f"Refused: {e}")
    reword_note = ""
    if reword_ix:                  # the step keeps its number, its place and its open state; its text (and its line of next, its proof) become the new words before anything below lines the checklist up with next
        for i, text in reword_ix.items():
            w = str(steps_old[i].get("writer") or "")
            if _steps.is_his(steps_old[i]["text"], unnamed_is_his=False):
                raise ToolError(f"Refused: reword: step {i + 1} is {OWNER}'s own step, made by the server from the ask and the step and ticked by his answer; it is never reworded")
            if w and not h.ho_same(w, next_writer):
                raise ToolError(f"Refused: reword: step {i + 1} is a line of {_session_label(w) or w}, not of this write's sender; only the session that wrote a step rewords it (ask it, or mark the step done or dropped)")
            if h.session_next() and _nr.grows(_steps.first_line(steps_old[i]["text"]), _steps.first_line(text)):       # N3 holds for a reword as for a rewritten line: the old text plus added words is progress, which goes on the page
                raise ToolError(f"Refused: reword: the new text of step {i + 1} is its old text with words added (\"{_clip_line(_steps.first_line(text), 90)}\"): a step is never rewritten to add progress, so progress, results and what was tried go on the project page "
                                f"(Current state or a timeline line). Reword the step to a different action, or mark it dropped=[{i + 1}] and write the longer one as a new line of next")
            h.gate_next(text, has_ask=True)
        h.gate_bare_urls({"next": "\n".join(reword_ix.values())}, {"next": "\n".join(steps_old[i]["text"] for i in reword_ix)})
        proofs = dict(meta["step_proof"]) if isinstance(meta.get("step_proof"), dict) else {}
        for i, text in reword_ix.items():
            old_text = steps_old[i]["text"]
            _nl.reword(meta, old_text, text, keeper_was, writer=steps_old[i].get("writer") or None)
            if (pv := proofs.pop(_steps.key(old_text), None)) is not None:
                proofs[_steps.key(text)] = pv                       # an event that finishes the step still finishes it
            steps_old[i] = {**steps_old[i], "text": text}
            reword_note += f"\n(step {i + 1} reworded: {_steps.first_line(old_text)[:120]} → {_steps.first_line(text)[:120]})"
        if proofs:
            meta["step_proof"] = proofs
        next_touch = True
    next_judged = "\n".join(x for x in (next, *reword_ix.values()) if x)       # the text this call sets, for the item model's guards: the lines of next and the new words of the steps reworded
    merged_note = ""
    next_after = meta.get("next")                # next as this write leaves it
    if next_touch:
        dry_meta = json.loads(json.dumps(meta))
        h.next_put(dry_meta, next, next_writer, keeper_was, wipe=clear_next, drop_own=next_drop)      # a dry run: a refusal comes before anything is written or told
        next_after = dry_meta.get("next")
    if status:
        if status == "on_hold":   # a retired status: on hold is a property of an open item
            raise ToolError("Refused: status must be open | completed; on hold is a property of an open item: hold=true (with an optional wake); clear_hold=true releases it")
        if status not in ("open", "completed"):
            raise ToolError("Refused: status must be open | completed")
        item["status"] = status
    if clear_hold and (hold or wake):
        raise ToolError("Refused: clear_hold releases the item and drops its wake; it does not go with hold or wake")
    if hold and item.get("status") == "completed":
        raise ToolError("Refused: a completed item does not go on hold; set it open first")
    if wake and item.get("status") == "completed":
        raise ToolError("Refused: a completed item takes no wake; set it open first")
    if recycle and clear_recycle:
        raise ToolError("Refused: recycle and clear_recycle do not go together")
    if recycle and item.get("status") == "completed":
        raise ToolError("Refused: a completed item does not wait for a recycle; set it open first")
    if recycle:                   # waits for a pane recycle: the moment it was set decides whether a later recycle covers it
        meta["recycle"], meta["recycle_at"] = True, time.time()
    if clear_recycle or item.get("status") == "completed":   # cleared by hand, or completed: the field goes (a recycle clears it in _recycled)
        meta.pop("recycle", None); meta.pop("recycle_at", None)
    # Items kept showing "on hold" while their work was live, so everywhere:
    # a date with nothing beside it is a wait on that date alone (outside a hand-off it is folded into until below, and the item waits until then); in a write that hands the item on it stays the wake it was,
    # the hand-off's backstop: the item stays in its lane, and at that moment the wake pass tells the mover and the sessions in its needs once and drops it (a notice, not a wait).
    # hold=true parks with its wake (the pass releases it), and an item whose needs hold decision is never on hold (_is_held). A stored
    # item keeps the meaning it was written with: held + wake still releases at its wake.
    h.record_fixes(meta, fixes)      # what the tool fixed in this call (server_fixes.py): the mark and a History line, or the mark taken off when the mover sent the value again
    wait_fixed = ""
    if (wake or next_touch) and not (hold or clear_hold or clear_wake or filing_only or wait_basis or clear_wait_basis) and item.get("status") == "open":      # a wake alone that is the whole of the wait: parked by this write (_date_only_wait)
        try:
            park_wake = str(h.parse_wake(wake) if wake else meta.get("wake") or "")
        except ToolError:
            park_wake = ""
        if park_wake and not _sf.declined(meta, _sf.WAKE_PARK, park_wake):      # a wake the mover sent back (clear_hold on the server's park) is left alone
            fixed_basis, wait_fixed = h.date_only_wait(item, meta, next_after, wake, (sender, debtor), wait_reason)
            if fixed_basis:
                hold, wait_basis = True, fixed_basis
                _sf.record(meta, _sf.WAKE_PARK, park_wake, h.wake_park_line(park_wake, fixed_basis), time.time())
    if hold and not (clear_hold or clear_wake or clear_wait_basis or filing_only or said_l or str(wait_basis or "").strip()) and item.get("status") == "open":      # a hold with a wake and no reason, whose own words give it: the server takes them as the wait_basis
        loose_basis, reason_fixed = _fix_loose_reason(item, meta, next_after, description or str(item.get("description") or ""), wake)
        if loose_basis:
            wait_basis, wait_fixed = loose_basis, wait_fixed + reason_fixed[0]
            _sf.record(meta, _sf.WAIT_REASON, reason_fixed[1], reason_fixed[2], time.time())
    basis_txt = " ".join(str(wait_basis or "").split())
    if basis_txt.lower() in h.ask_none:
        clear_wait_basis, basis_txt = True, ""
    basis_ok = ""
    if basis_txt:                 # a wake past the cap that stands on a real-world date: checked before the wake gate reads it
        if clear_wait_basis:
            raise ToolError("Refused: clear_wait_basis drops the basis; it does not go with a new one")
        if clear_wake or clear_hold:
            raise ToolError("Refused: wait_basis goes with a wake; this call drops the wake")
        basis_ok = h.gate_wait_basis({**item, "status": status or item.get("status")}, basis_txt, h.parse_wake(wake) if wake else str(meta.get("wake") or ""), held=h.model_guards_on() and bool(hold or h.is_held(item) or _reads_time_wait(item) or state_st == "verifying") and not clear_hold)
    if wake:                      # a moment to come
        stored = h.parse_wake(wake)
        if h.wake_at(stored) <= _pages.zone_now():      # for a date-only wake the same as "after today"
            raise ToolError(f"Refused: wake must be in the future ({_cfg.tz_abbr()})")
        words = h.gate_cap(item, said_l, "wake", stored, h.wake_at(stored).timestamp(), basis_ok)    # The owner's one rule: no wait runs past the cap without his words
        meta["wake"] = stored
        if words and words != h.basis_words:   # recorded for this wake: the cap is lifted for it, with his sentence (the reason a time wait carries)
            _, q_text, q_src = h.owner_quote_on(item, said_l, _wt.cap_days())
            h.cap_ok_put(meta, "wake", stored, words, quote=q_text, source=q_src)
        else:                     # (a real-world date is its own record, wait_basis, below)
            h.cap_ok_drop(meta, "wake")
    if hold:
        meta["hold"] = True
        if not (was_held and h.render_hold_at(item)):   # who set it and when: the unexplained-holds report and the briefings read it; a hold already held keeps its stamp
            h.hold_set(meta, _session_label(debtor) or debtor or "unknown")
    time_kind = _watch.stored_kind(meta) == "time"       # read before the dates go: a stored until with no kind reads as a time wait only while the until stands
    if clear_wake:                # the wake goes; a hold stays only while something else holds it (the item rule below)
        meta.pop("wake", None); h.cap_ok_drop(meta, "wake")
        if _watch.stored_kind(meta) != "relay":      # a relay's until is its ask-by day, which clear_wake never dropped
            meta.pop("until", None)
    if clear_hold:                # released now: the hold and its wake go together
        if meta.get("wake") and _sf.marked(meta, _sf.WAKE_PARK, str(meta["wake"])):      # the server parked this wake and the mover sends it back: the server leaves that wake alone from here
            _sf.unmark(meta, _sf.WAKE_PARK, str(meta["wake"])); _sf.decline(meta, _sf.WAKE_PARK, str(meta["wake"]))
        if meta.pop("hold", None) or (was_until and _uw.kind_of(meta) in ("", "time")):      # a hold, or a wait on the date alone (stored as until, with no hold of its own to drop)
            meta.pop("wake", None); meta.pop("until", None); h.cap_ok_drop(meta, "wake")
            if time_kind or (was_until and _uw.kind_of(meta) in ("", "time")):      # the time wait the hold stood on (a park with a then stores one) goes with it: wait_kind, post_wake_mover and the watcher's stamps
                for k in (*_model.WAIT_GROUP, "chases", "watch"):
                    meta.pop(k, None)
        meta.pop("hold_set", None)
    if item.get("status") == "completed":   # completed: nothing is held or due any more
        meta.pop("hold", None); meta.pop("wake", None); meta.pop("until", None); meta.pop("hold_set", None); meta.pop("cap_ok", None)
    if basis_ok:                  # the basis is bound to the wake it was given for; a different wake, no wake or a closed item drops it
        h.basis_put(meta, basis_ok, str(meta.get("wake") or ""), _session_label(debtor) or debtor or "unknown")
    elif clear_wait_basis or (isinstance(meta.get("wait_basis"), dict) and meta["wait_basis"].get("wake") != _wt.wake_value(meta)):      # the basis stands for the date the wait ends on: the stored until, else the wake
        meta.pop("wait_basis", None)
    if h.model_guards_on() and meta.get("hold") and meta.get("wake") and (hold or wake) and not basis_ok and not _wt.basis_of(meta) and not str(_wt.words_of(meta).get("quote") or "").strip():
        q_why, q_text, q_src = h.owner_quote_on(item, said_l, _wt.cap_days())     # a hold with a wake is a time wait, which carries his words: record them, within the cap too
        if q_why and q_text:
            h.cap_ok_put(meta, "wake", str(meta["wake"]), q_why, quote=q_text, source=q_src)
    hold_pre = bool(meta.get("hold"))     # the hold as this write leaves it, before the old rule below drops it beside a decision (the model guards refuse that pair instead)
    dropped_hold = item.get("status") == "open" and bool(meta.get("hold")) and _waits_decision(meta)
    if dropped_hold:              # an item waiting on the owner's call is never on hold: any write drops a stored flag (its date stays, and no date parks an item on his call)
        meta.pop("hold", None); meta.pop("hold_set", None)
        h.state_end(meta, "parked")    # the park it stood in is gone with the hold (needs is not something parked stands on: the hold would only be stripped again)
    # A hold names what it waits for, a wake, open after
    # items or a pane recycle; an anchor scoped to the item is a condition too, but one that still carries a backstop wake (the notice may never
    # come). Checked when the call touches the hold, its wake, its after or its recycle, so a park stored before the rule is read as it is.
    if meta.get("hold") and not meta.get("wake") and (hold or clear_wake or after_set or clear_after or clear_recycle) and not h.after_open(meta) and not meta.get("recycle"):
        if h.scoped_anchors(str(meta.get("project") or ""), gid):
            raise ToolError(f"Refused: a hold that waits on a notice from the anchor scoped to {gid} still carries a backstop wake, at most {_wt.cap_days():g} "
                            f"days out unless {OWNER}'s words are on the item (wake=YYYY-MM-DD): the notice may never come")
        raise ToolError("Refused: a hold names what it waits for; an unconditional or indefinite park is refused. Give it a date (hold=true with wake=YYYY-MM-DD or "
                        f"YYYY-MM-DDTHH:MM: the date {OWNER} gave, the date the outside party or event it waits on is due, or the end of a window the work itself needs, with wait_basis=\"<what the window collects> ends <YYYY-MM-DD>\"), the items that must close first (`after=[\"board#N\"]`), "
                        f"a notice from an anchor scoped to it (`anchors(project, add=[url], items=[\"{_gh.shown(gid)}\"])`, with a backstop wake at most {_wt.cap_days():g} "
                        f"days out), or a pane recycle (recycle=true). An item waiting on {OWNER} is never parked: needs=decision with its ask, "
                        "or after=[<the item that carries the ask>], which releases it when that item closes. To check back on work you keep moving while the "
                        "item stays active, set no date: a date with no hold is a wait until it (outside a hand-off)")
    # The done check: set or cleared by this write (a filing edit: no page owed), then the hand-off gate: a write
    # that hands the item to another session (a `<session>: <action>` line of next) leaves it with a check or a wake
    chk = " ".join(str(check or "").split())
    chk_new = bool(chk) and chk.lower() not in h.ask_none
    clear_check = clear_check or chk.lower() in h.ask_none      # check="none" or clear_check=true removes it, like needs, due and wake (an older tool list may lack clear_check); check="" is "not passed", as needs="" is
    if chk_new:                                                # a new check beside clear_check replaces the old one, as a new needs beside clear_needs does
        meta["check"] = h.parse_check(chk, gid)
    elif clear_check:
        meta.pop("check", None)
    handed: list[str] = []
    if item.get("status") == "open" and not closing:
        handed = _handoff_to(item.get("metadata") or {}, meta, next, sender.strip() or own_for)
        if handed and not meta.get("check") and not meta.get("wake") and not h.front_sender(sender):     # a front agent's hand-off asks for neither: the mover's close lands the result, and its own wake or check is refused below
            raise ToolError(f"Refused: this update hands {_gh.shown(gid)} to {', '.join(handed)} (a line of next in the form `<session>: <action>`) and nothing "
                            f"would close the item once that work is done. Add check=<what closes it> ({h.check_how}): the server then closes it when the check passes, no session turn spent. "
                            f"Only when no check fits, add a date, wake=YYYY-MM-DD (or until=, YYYY-MM-DDTHH:MM, {_cfg.tz_abbr()}), as the backstop of this hand-off: because the write hands the item on, the date is no wait, the item stays active in the new mover's lane and the hand-off is recorded (the same date with no hand-off is a wait, and the item waits until then). "
                            "(A front agent's hand-off is not asked for either: its mover's close or hand-back lands the result through stackshot.) "
                            "Pass the same update again with the check, or with the date alone if none fits. "
                            "If this tool shows no check parameter, this session's cached tool list predates it: pass the date, or call the update through the "
                            "MCP Portal's Code Mode (portal_codemode_execute with codemode.stackshot_update({item_id, sender, next, check})), which reads the live schema.")
    old_due = meta.get("due")
    for k, v in (("ask", ask), ("priority", priority), ("due", due), ("owner", owner), ("owner_name", owner_name), ("project", project)):
        if v:
            meta[k] = v
    if contact_new:
        meta["contact"] = contact_new
    elif project and item.get("status") == "open" and project.strip().strip("/") != str((item_was.get("metadata") or {}).get("project") or "").strip().strip("/"):
        moved_c = _contact_after_move(meta, project)           # re-filed under another project: the new project's -main agent, unless the contact is a front agent there too
        if moved_c:
            meta["contact"] = moved_c
        else:
            meta.pop("contact", None)
    if next_touch:                # the sender's lines are replaced (or removed), everyone else's stay; a line stored with no writer is the creator's as it stood before this write
        merged = h.next_put(meta, next, next_writer, keeper_was, wipe=clear_next, drop_own=next_drop)
        merged_note = "".join(f"\n(next: \"{_steps.first_line(e)[:120]}\" is already an open step of {_session_label(w) or w or 'another session'}: it stays as it is, not added a second time)" for e, w in merged)
    if state_change:              # an update, a park or a completion ends the idle record an earlier version stored
        meta.pop("idle", None)
        for k in ("waiting", "wait_failed", "undelivered"):   # the item moved: a failed wait is the mover's to fix, a lost notice is stale, and a `waiting` record an earlier version wrote goes
            meta.pop(k, None)
    if wake or clear_wake or hold or clear_hold or after_set or clear_after or needs_set or clear_needs or recycle or clear_recycle or chk or clear_check:
        for k in ("waiting", "wait_failed"):      # what it waits on changed (a check alone is a filing edit, so it does not reach the line above): the old failure (and any `waiting` record) is about the old wait
            meta.pop(k, None)
    if opts is not None:          # a filing edit like the ask; [] clears
        if opts: meta["options"] = opts
        else: meta.pop("options", None)
    if closing:                   # the end state is the record; nothing is left to do, ask or wait on (due stays as a record)
        if steps_old:             # a close marks every step still open, by the closer: done when the outcome is done, dropped otherwise; a mark passed with the close counts first
            try:
                meta["steps"] = _steps.stored(_steps.mark_open(_steps.apply(steps_old, None, done_ix, drop_ix, steps_by, time.time()), outcome, steps_by, time.time()))
            except _steps.StepError as e:
                raise ToolError(f"Refused: {e}")
        for k in ("next", "next_by", "owner_step", "ask", "needs", "options", "after", "check", "watch_reason", "waiting", "wait_failed", "undelivered", "cap_ok", "wait_basis", "model_flags", *_states.DROP_ON_CLOSE, *_states.CLOSE_EXTRA, *_model.DROP_ON_CLOSE, *_watch.DROP_ON_CLOSE):
            meta.pop(k, None)
        meta["outcome"], meta["reason"] = outcome, reason
        meta["outcome_text"] = outcome_text      # the close's summary has its own field: the description stays what the item was about
        if superseded_by:
            meta["superseded_by"] = superseded_by
    if reopening:                 # the close's record leaves the live item; the store's git history keeps it
        for k in ("outcome", "outcome_text", "reason", "superseded_by"):
            meta.pop(k, None)
    if clear_ask:
        meta.pop("ask", None)
    if clear_needs and not needs_set and not agent.strip():
        meta.pop("needs", None)
    if clear_due and not due:     # a postponement with no new date (an item with a due date had no way off)
        meta.pop("due", None); h.cap_ok_drop(meta, "due")
    if anchors is not None:
        raise ToolError("Refused: anchors belong to the project, not the item — use anchors(project=<its project>, add=[url…], items=[<this id>]) or remove=[url…]")
    work_note = ""
    if said_l:                    # appended, never replaced: every entry keeps its position (the anchor the issue's trailer links)
        meta["said"] = [*(meta.get("said") if isinstance(meta.get("said"), list) else []), *said_l]
        work_note += h.said_note(said_l)
    if clear_draft:                                                            # the draft: a filing edit like the ask (no clock moves, no page is owed)
        meta.pop("draft", None)
    elif draft_set:
        meta["draft"] = draft_set
    if (needs_set or agent.strip()) and "mover" not in model_set and "mover" not in model_drop:    # a hand-off by needs moves the item: a stored mover that is not among the sessions now named is the old holder, so it goes
        stored_mv = _model.norm_who(meta.get("mover"))
        named_now = _needs_sessions(meta)
        nm_mv = _anc.names()
        if stored_mv and named_now and not _model.is_owner(stored_mv) and not any(x == stored_mv or _anc.canonical(x, nm_mv) == _anc.canonical(stored_mv, nm_mv) or h.render_same_ref(x, stored_mv) for x in named_now):
            meta.pop("mover", None)
    h.model_apply(meta, str(item.get("status") or ""), model_set, model_drop)   # goal, mover, then and the wait's fields: a filing edit
    if "wait_kind" in model_drop:
        h.wait_end_sent_back(meta, (_we.PR, _we.BOX, _we.URL, _we.STORED))      # clear_wait on a wait the server set from the line's words
        if was_until and not (wake or hold):
            for k_ in _uw.LEGACY_FIELDS:                # clear_wait drops the stored until (model.WAIT_GROUP); the old working fields it stood as go with it
                meta.pop(k_, None)
    wait_note = ""
    gave_ask = bool(ask_by.strip()) and ask_by.strip().lower() not in h.ask_none
    if was_until and bool(wake) != gave_ask and item.get("status") == "open":      # one date given: the date the item held before (unfolded into the other working field) does not outlive it
        meta.pop("ask_by" if wake else "wake", None)
    if item.get("status") == "open" and "wait_kind" in model_set:
        _uw.to_slot(meta)                                       # a date held for another kind moves to the field the new kind reads
    if item.get("status") == "open" and "wait_kind" in model_set and _uw.needs_date(meta) and not meta.get("recycle") and not (meta.get("state") == "verifying" and meta.get("end")):
        fb_d, _fb_how, fb_note = h.fallback_wait_date(meta, next_after, description or item.get("description"), meta.get("due"))      # a kind with no date is never refused: the item's own words, else a suggestion, else tomorrow
        meta[_uw.slot_of(_uw.kind_of(meta))] = fb_d
        if _uw.kind_of(meta) == "time":
            meta["hold"] = True                                 # a wait on a time stands as a hold with its wake
        until_wait = True
        wait_note += fb_note
    h.gate_ask_on_wait(gid, item, meta, was_needs, closing)           # a decision asked of the owner on an item that still waits: the clear_wait hint
    watch_note = h.watch_on_write(gid, item_was, meta, model_set, model_drop, debtor, sender.strip())   # the wait's record, the arrival that was shown
    h.gate_metadata(meta, creating=False)
    lifted = "" if (ask or clear_ask or item.get("status") == "completed") else h.lift_ask(meta, refresh=bool(next), writer=next_writer, keeper=keeper_was)   # a client without the ask parameter
    steps_note = merged_note + reword_note
    steps_new = None                                            # the checklist this write leaves (set below when the write touches it): reads it
    if steps_on and not closing and (next_touch or marks):      # the checklist follows next, and next follows a mark: a marked line leaves next with its writer
        marked_text = [steps_old[i]["text"] for i in (*done_ix, *drop_ix)]
        if h.session_next():                 # N3: nothing leaves the list; a reworded open step is no rewrite of its text to add words to it (a session's write only)
            leaving, arriving = _nr.moves(steps_old, done_ix, drop_ix, h.nl_text_without(meta, marked_text, keeper_was))
            leaving = [(i, t) for i, t in leaving if i not in drop_ix]      # a step marked dropped stays on the list as dropped: the extended line that replaces it is a new action, not a rewrite (reviewer note d)
            if grown := _nr.growths([t for _, t in leaving], arriving):
                old_s, new_s = grown[0]
                pos = [i + 1 for i, t in leaving if t == old_s][0]
                raise ToolError(f"Refused: the step \"{_clip_line(_steps.first_line(new_s), 90)}\" is the open step \"{_clip_line(_steps.first_line(old_s), 90)}\" with words added: a step is never rewritten to add progress, "
                                f"so nothing leaves the list that way: the old step is left without a mark. Keep the step as it is, or mark it (done=[{pos}] when the work is finished, dropped=[{pos}] when it is no longer wanted) and write the next step as a new action; "
                                "progress, results and what was tried go on the project page (Current state or a timeline line)")
        try:
            steps_new = _steps.apply(steps_old, h.nl_text_without(meta, marked_text, keeper_was), done_ix, drop_ix, steps_by, time.time(),
                                     written=next, own=lambda w: not w or h.ho_same(w, next_writer), wipe=clear_next, strict=h.require_marks(), reworded=reword_ix)
        except _steps.StepError as e:
            raise ToolError(f"Refused: {e}")
        _nl.prune(meta, marked_text, keeper_was)
        meta["steps"] = _steps.stored(steps_new)
        steps_note += "".join(f"\n(step {i + 1} done: {_steps.first_line(steps_new[i]['text'])[:120]})" for i in done_ix) + "".join(f"\n(step {i + 1} dropped: {_steps.first_line(steps_new[i]['text'])[:120]})" for i in drop_ix)
    if work_spec is not None:      # the status of the sender's open step, one line in the reply as History says it
        if work_skip or closing or not steps_on:
            work_note += f"\n(work: not recorded, {work_skip or 'the item is closed with this call'})"
        else:
            cl_w = steps_new if steps_new is not None else steps_old
            nm_w = _anc.names()
            ti_w = work_tick if work_tick >= 0 else _work.step_of(cl_w, work_who, lambda x, y: bool(x) and bool(y) and (x == y or _anc.canonical(x, nm_w) == _anc.canonical(y, nm_w)))
            if ti_w < 0:
                work_note += f"\n(work: not recorded, {work_who} has no open step on the item after this write)"
            else:
                cl_w = list(cl_w)
                spec_w = {**work_spec, "state": "done"} if work_tick >= 0 else work_spec
                cl_w[ti_w] = _work.apply(cl_w[ti_w], spec_w, time.time())
                meta["steps"] = _steps.stored(cl_w)
                work_note += "".join("\n" + w for w in _work.changes({"steps": (item_was.get("metadata") or {}).get("steps")}, meta)) or f"\n(work: \"{work_spec.get('text') or 'the status'}\" unchanged, already so)"
                if work_made:
                    work_note += f"\n(step added for {work_who}: {work_made})"
    if closing and step_proof is not None:
        raise ToolError(f"Refused: {_gh.shown(gid)} is being closed, and a close leaves no open step to give a proof: send step_proof on a call that keeps the item open")
    if closing:                                                 # a close leaves no open step, so no proof
        meta.pop("step_proof", None)
    elif steps_on:                                              # the proofs of this checklist's open steps: a call's step_proof sets them, a step that left the list takes its proof along
        if step_proof is not None:
            steps_note += h.step_proof_set(meta, steps_new if steps_new is not None else steps_old, step_proof)
        elif steps_new is not None:
            steps_note += h.step_proof_prune(meta, steps_new)
        if steps_new is not None:
            h.gate_step_gap(meta, steps_new, steps_old)         # a step that delivers a pull request, followed by another session's step, needs its proof
    elif step_proof is not None:
        raise ToolError(f"Refused: {_gh.shown(gid)} is closed and its checklist is the record of what was done; reopen it (status=open with a next) before giving a step a proof")
    asked = lifted + ("" if item.get("status") == "completed" else h.ask_owed(meta))   # a needs=decision item left without an ask (a completion never needs one)
    if item.get("status") != "completed" and not closing and (ask or meta.get("ask") != ask_was):   # only a call that writes or changes the ask
        h.gate_one_decision(meta, item.get("description") or "", bool(lifted) and not ask)
    if item.get("status") != "completed" and (ask or (description and not reformat) or needs_set or opts is not None):   # only a call that writes what it reads
        h.gate_alternatives(meta, item.get("description") or "")
    if item.get("status") != "completed" and not closing and (ask or meta.get("ask") != ask_was or opts is not None
                                                               or (needs_set and "decision" not in [str(x).lower() for x in was_needs])):   # a write that sets the ask or the options, or puts the item on his call: an open question needs options
        h.gate_open_question(meta)
        h.gate_recommend_stance(meta)       # the same writes: no options and a Recommend that is no yes or no
    if item.get("status") != "completed" and not closing and (ask or (description and not reformat) or next_touch or needs_set or opts is not None):   # a write that sets the ask or the text it is read against
        h.gate_mockup(meta, item.get("description") or "")
    if item.get("status") != "completed" and not closing and (ask or needs_set or opts is not None or next_touch):   # his own action asked as a decision: only a call that writes what it reads
        h.gate_own_action(meta, next_only=not (ask or needs_set or opts is not None))
    if item.get("status") != "completed" and (ask or opts):
        asked += h.options_note(meta) + h.actor_note(meta, options=bool(opts), ask=bool(ask))
    hold_note = ""
    if hold and meta.get("hold") and not state_st and meta.get("state") in _states.STATES and meta["state"] != "parked":     # a hold makes the item read parked: a state of another kind cannot stand beside it
        hold_note = f"\n(stored state {meta['state']} dropped: a hold ends it; the item reads parked)"
        h.state_end(meta)
    state_touched = frozenset(k for k, v in (("needs", needs_set or clear_needs or agent.strip()), ("after", after_set or clear_after),
                                              ("wake", wake or clear_wake), ("hold", hold or clear_hold), ("ask", ask or clear_ask), ("next", next_touch),
                                              ("wait_basis", basis_txt or clear_wait_basis)) if v)
    work_note += hold_note + h.state_apply(meta, str(item.get("status") or ""), state_st, state_given, state_touched, step_withdrawn)   # the state last: it reads the item as every gate above left it
    desc_note = ""
    mover_named = "mover" in model_set or "mover" in model_drop or filing_only or h.reformat()      # a write that names the mover, or only files (rename, priority, re-bullet): the server flips nothing for it
    if item.get("status") == "open":      # the state checks, on the item as this write leaves it (they refuse, or mark, before anything is saved)
        item_now = {**item, "metadata": meta}
        if done_ix and steps_on and _model.stood_his(item_now, lambda i_: h.after_open(i_.get("metadata") or {})):      # N4: while the item, as this write leaves it, waits on him, only his answer ticks his step (a call that also ends what asks him is no refusal: it withdraws the ask and the step goes with it)
            _why = _hs.refuse_done(steps_old, done_ix, _hs.recorded(item_was.get("metadata") or {}), h.owner_want(meta))
            if _why:
                raise ToolError(f"Refused: {_why}")
        if h.session_next() and steps_new is not None and any(x["status"] == _steps.OPEN for x in steps_old) and not any(x["status"] == _steps.OPEN for x in steps_new) \
                and not _model.stood_his(item_now, lambda i_: h.after_open(i_.get("metadata") or {})):      # N6: a session's write that takes the last open step off an item that stays open (his server-made step counts; a close is exempt)
            raise ToolError(f"Refused: this write leaves {_gh.shown(gid)} open with no open step in next: {_nr.NO_STEP_FIX_HELD if meta.get('hold') else _nr.NO_STEP_FIX}")
        mover_note = h.owner_state_mover(item_now, meta, mover_named, item_was)      # a bookkeeping write (rename, priority, re-bullet) flips nothing; his state makes him the mover: before the guards read the item
        if not (filing_only or h.reformat()):
            mover_note += h.owner_then_default(item_was, meta, str(item.get("status") or ""), sender.strip(), "then" in model_set or "then" in model_drop, mover.strip())      # D9: then defaults to the agent doing the work, not to the front agent that relayed the ask
        wake_changed = bool(wake) and meta.get("wake") != (item_was.get("metadata") or {}).get("wake")      # re-sending the wake the item carries sets nothing
        watch_ok = h.gate_sender_watch(gid, item_now, sender.strip(), handed=handed, watch_reason=watch_reason) if wake_changed else ""   # a front agent's own wake or until date on an alive item another session moves
        if watch_ok:
            meta["watch_reason"] = watch_ok[:300]
        elif wake_changed or not meta.get("wake"):
            meta.pop("watch_reason", None)      # a reason belongs to the wake it was given for: another wake without one, or no wake, drops it
        h.gate_decision_again(item_was, meta, was_needs, ask_was, gid)
        if h.session_next() and h.model_guards_on() and not (reopening or h.reformat()) and item_was.get("status") == "open":
            h.gate_clock_renewal(item_was, meta, gid, steps_old, steps_new, description, said_l, sender)      # no clock renewal without progress: a session's write only
        h.gate_repark(item_was, item_now, meta, gid, said_l)
        _mark_next_stale(item_was, item_now, meta, debtor, naming_added, next_touch)
        touched_m = {k for k, v in (("next", next_touch), ("ask", ask), ("subject", subject), ("description", description.strip()),("needs", needs_set or clear_needs or agent.strip()), ("hold", hold or clear_hold),
                                    ("wake", wake or clear_wake), ("after", after_set or clear_after), ("state", state_st), ("wait_basis", basis_txt or clear_wait_basis)) if v}
        touched_m |= set(model_set) | set(model_drop)           # goal, mover, then and the wait's fields this write sets or clears
        if wake:
            touched_m.add("cap_ok")                             # a wake records his words for it
        full_judgement = reopening or (h.switchover_on() and not filing_only)     # step 4's switchover: every write is judged whole, old items included; a bookkeeping write (a page rename) still only by what it touches
        desc_note = h.gate_model(item_now, None if full_judgement else touched_m, gid, needs=[x for x in _needs_of(meta) if x not in naming_added], hold=hold_pre, desc_set=bool(description.strip()),
                               next_text=next_judged if next_touch else None, windows_text=next_judged if next_touch else "", defers_text=next_judged if next_touch else "",
                               until_wait=until_wait or (was_until and not (wake or hold or clear_wait_basis or str(wait_basis or "").strip())), date_given=bool(wake), hold_given=bool(hold))   # the write guards of the item model; his lines' Windows check judges only the lines this write sets; a wait on an until carries no snooze reason
        desc_note += mover_note
        h.anchor_wait_gate(item_was.get("metadata") or {}, meta, gid)      # an anchor wait newly set or moved: its anchor must be on the project's list already (after the model guards)
        if next_touch or state_st or state_given.get("step") or needs_set or clear_needs or agent.strip():      # only a write that touches next, the state, needs or the step; any other keeps the note. After the model guards, so their more specific refusals (a command in his line) come first
            if not h.terminal_row():      # the terminal prompt's repair path (a script's own row, orphan case) is exempt as on create
                h.gate_owner_step(item_now, gid, sender=next_writer, keeper=keeper_was)
        if state_st or state_given.get("step") or "mover" in model_set or "mover" in model_drop or draft_set or clear_draft:      # the draft guard reads a write that sets the state, the step, the mover or the draft, never an unrelated one
            h.gate_draft(item_now, gid)
        if state_st or state_given.get("step") or "mover" in model_set or "mover" in model_drop or draft_set or clear_draft or description.strip():      # the step guards read the same writes, and a new description
            h.gate_step(item_now, gid, item_was.get("description") if description.strip() and _sc.owner_facing(item_was) else None, step_set=bool(state_given.get("step")))      # only an item already his to move (mover the owner, your-step, your-call) keeps the old lines out of the judgement
        h.gate_handoff(gid, item_was, item_now, debtor)     # step 2: a hand-off to a session with no pane is refused, the background agent named
        if h.session_next() and h.model_guards_on() and steps_new is not None and not (filing_only or h.reformat() or sender.strip().startswith("a script on ")):
            h.gate_front_step(gid, item_now, steps_before, steps_new, sender.strip() or debtor)     # a new or reworded step that opens with a front agent on an item another session moves: nothing could wake it for the step
    kept_legacy_wake = False
    backstop = False                       # a bare date beside a hand-off, kept as the wake it was (below)
    if item.get("status") == "open" and (was_until or wake or hold or ask_by.strip() or until_wait):
        if _wt.after_of(meta) and not _uw.kind_of(meta) and not clear_after and (after_set or had_hold or bool(h.after_open(meta))) and _uw.date_of(meta):
            meta["wait_kind"] = "item"                   # a date beside an after link with no kind is that wait's backstop (as ask_by was); create does the same
        kept_legacy_wake = bool(meta.get("wake")) and not until_wait and (bool(wake) or not was_until)      # the wake as the old parameter (or an older write) gave it keeps the legacy-wake note; a date passed as until never does
        keep_hold = bool(meta.get("hold")) and bool(_wt.wake_value(meta)) and bool({"anchor", "recycle"} & set(h.hold_held_by(gid, meta)))      # a hold that waits on an anchor scoped to the item or on a pane recycle keeps its flag and record (the anchor release, the backstop gate and the recycle read them); the date is its backstop
        kept_hold_set = meta.get("hold_set")
        read_failed: list[bool] = []
        backstop = bool(_uw.date_of(meta)) and _wait_is_bare(meta) and _hands_on(gid, item_was, {**item, "metadata": meta}, handed, sender.strip() or debtor or "", read_failed)
        could_hand_on = bool(wake or hold or ask_by.strip() or until_wait or next_touch or needs_set or clear_needs or "mover" in model_set or "mover" in model_drop or agent.strip())      # a write that names a date or could hand the item on (next, needs, the mover, an agent); a write of anything else (a description, a contact) cannot, so a failed reading changes nothing it must say
        if backstop and read_failed and was_until and _wait_is_bare(item_was.get("metadata") or {}):
            backstop = False               # the reading failed on an item a bare until already parks: that wait is left untouched (not ended by a hand-off nobody could read), and the reply says so
            old_d, new_d = _uw.date_of(item_was.get("metadata") or {}), _uw.date_of(meta)
            if could_hand_on:
                wait_note += (f"\n(the hand-off reading failed, so the wait until {old_d} is kept as it was; if this write hands the item on, send it again)" if new_d == old_d
                              else f"\n(the hand-off reading failed, so the date is stored as the wait until {new_d}, not as a backstop (it was until {old_d}); if this write hands the item on, send it again)")
        elif backstop and read_failed and could_hand_on:
            wait_note += "\n(the hand-off reading failed, so the date is kept as it was given: a backstop, no wait, and the item stays active)"
        if backstop:
            meta.pop("until", None)        # a write that hands the item on never parks it: a bare date beside the hand-off (a wake, an until or an ask_by) stays the date it was, the backstop of the hand-off, and the item stays alive in the new mover's lane (the hand-off record needs a mover)
            kept_legacy_wake = False
            if was_until and _wait_is_bare(item_was.get("metadata") or {}):
                wait_note += (f"\n(the item was waiting until {_uw.date_of(item_was.get('metadata') or {})}: this hand-off ends that wait. The date stays as the hand-off's backstop, and the item is active in the new mover's lane)")
        else:
            _uw.fold(meta)                 # every gate above judged the wait in the words of the old fields; it is stored as the one date, until, and none of them
        if keep_hold:
            meta["hold"] = True
            if kept_hold_set:
                meta["hold_set"] = kept_hold_set
    item["metadata"] = meta
    item["updated"] = time.time()          # the item's own clock (the renderer used to trust the file's mtime, which a migration rewrites)
    if state_change:
        item["state_updated"] = item["updated"]   # filing edits (owner/project/priority/subject, and the ask line) leave the state clock alone
        item["confirmed"] = item["updated"]       # a state change confirms the item; a filing edit does not
    named = name_commit()                  # every gate has passed: the naming is stored as its own save, then this write's
    _writes.save(gid, item, writer=debtor, ctx=_writes.QUIET if (filing_only or h.reformat()) else (_writes.NAMED if mover_named else _writes.PLAIN))
    now_held = h.is_held(item)
    now_parked = now_held or h.date_parked(item)
    if wake or clear_wake or hold or clear_hold or item.get("status") != was or now_parked != was_parked:
        h.wake_event_set()         # the minute loop recomputes its next wake now, so a wake set a minute ahead still fires on time
    told = ""
    relayed = False               # this write already went to the project's keeper or router (_pilot_relay): one event makes one inbound there
    if state_change and not h.terminal_row():     # a terminal-prompt row owes the page nothing: no debt for the script or the keeper, no notice to the router
        stew, role = h.pilot_charge(meta.get("project", ""), debtor)
        moved = bool(stew) and role == "name" and h.writer_owes()     # the writer owes it; the keeper only past the grace
        if not moved:
            h.owed_mark(meta.get("project", ""), stew or debtor, gid)
        if stew:
            what = (f"completed ({outcome}{' by ' + _gh.shown(superseded_by) if superseded_by else ''})" if closing else "reopened" if reopening else "completed" if status == "completed" else "put on hold" if now_parked and not was_parked else "released from hold" if clear_hold and was_parked
                    else "changed (" + ", ".join(k for k, v in (("description", description), ("next", next_touch), ("needs", needs_set or clear_needs), ("status", status), ("due", due or clear_due),
                                                                 ("hold", hold or clear_hold), ("wake", wake or clear_wake), ("after", after_set or clear_after)) if v) + ")")
            if not moved:
                told = h.pilot_relay(meta.get("project", ""), gid, item, what, debtor, stew, role)
                relayed = bool(told)
            else:
                loose = not (description or needs_set or clear_needs or status or due or clear_due)   # only next, after, or the hold and its wake
                told = h.writer_charge(meta.get("project", ""), gid, debtor, stew, what, loose)
                if item.get("status") == "completed" and was != "completed" and h.scoped_anchors(meta.get("project", ""), gid):
                    relayed = bool(h.pilot_relay(meta.get("project", ""), gid, item, what, debtor, stew, role,   # the keeper's anchor bullet keeps its cue
                                                tail=f"no page update is owed by you ({_session_label(debtor)} writes it); this notice is for the anchors scoped to {_gh.shown(gid)}"))
    h.publish()
    item["gid"] = gid
    hint = ("\nstill on hold: pass clear_hold=true to release it"
            if status == "open" and was_held and now_held and not (hold or wake) else "")   # a session with the old rulebook in context learns the new form
    heard: list[str] = []         # the mover, when a notice below reached it as mover: its "now needs you" line would double it
    owner_told = h.owner_reached(named, relayed)   # _tell_owner (the server's naming of the writer above, or a notice below) already told the mover this write: _tell_owner_change then adds nothing
    h.close_was_set(item_was if closing else None)      # a close is told to the mover, which the close dropped from the item
    if closing:                   # the item's mover hears what another session did that it must know
        what_ = f"was completed ({outcome}{' by ' + _gh.shown(superseded_by) if superseded_by else ''}{': ' + reason if reason else ''})"
        t_ = h.tell_owner(gid, item, what_, debtor, close=True); told += t_; owner_told = owner_told or h.owner_reached(t_, relayed)
        told += h.tell_observers(gid, item, what_, debtor)                      # observers hear a close
        rel = h.release_after(gid, outcome, superseded_by, debtor, reason)      # the items that waited on this one: and the movers of the items that name it
        if rel:
            told += f"\n({', '.join(rel)} waited on {gid} and {'is' if len(rel) == 1 else 'are'} released: the sessions in {'its' if len(rel) == 1 else 'their'} needs, else the page keeper, have been told)"
        told += h.mentions_reply(gid)
    elif reopening:
        what_ = "was reopened (next: " + (next.strip().splitlines() or [""])[0][:160] + ")"
        t_ = h.tell_owner(gid, item, what_, debtor, heard=heard); told += t_; owner_told = owner_told or h.owner_reached(t_, relayed)
        told += h.tell_observers(gid, item, what_, debtor)                      # observers hear a reopen
    elif "decision" in _needs_kinds(meta) and "decision" not in was_needs and item.get("status") == "open":
        t_ = h.tell_owner(gid, item, f"now needs {OWNER}'s call" + (f" (ask: {meta['ask']})" if meta.get("ask") else "")
                         + "".join(f"; {ln}" for ln in h.render_option_lines(item)) + ", set", debtor, decision=True, heard=heard)
        told += t_; owner_told = owner_told or bool(t_)    # a move to decision is never pushed to a front agent mover (the board shows it), so its quiet line counts
    if item.get("status") == "open":   # a session newly named in needs gets one notice
        if not (closing or reopening):
            try:
                told += h.tell_handback(gid, item, was_needs, debtor, heard)   # a front agent mover hears an item handed back to it alone; nothing else wakes it
            except Exception as e:  # noqa: BLE001  — the write is saved and published; a notice that fails is a stderr line, never a failed write
                print(f"owner: {gid} hand-back not told: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        new_s = [s for s in _needs_sessions(meta) if h.session_id(s) not in {h.session_id(x) for x in was_needs}]
        told += h.tell_needed(gid, item, new_s, debtor, heard)
        if "decision" in [str(x).lower() for x in was_needs] and "decision" not in _needs_kinds(meta):   # he has decided; the sessions still named move now
            told += h.tell_decided(gid, item, [s for s in _needs_sessions(meta) if s not in new_s], debtor, heard)
    try:
        step = h.tell_owner_close(gid, item, debtor, closing, heard)   # the front agent mover hears a close by another session at once; a builder's step is never pushed to it
    except Exception as e:  # noqa: BLE001  — the write is saved and published; a notice that fails is a stderr line, never a failed write
        print(f"owner: {gid} step not told: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        step = ""
    if step:
        owner_told = True
        told, named = told.replace(h.quiet(item), ""), named.replace(h.quiet(item), "")   # the mover was told after all
        told += step
    if h.session_id(h.holder(item)) in heard:
        owner_told = True
    try:
        chg = h.tell_owner_change(gid, item, before, debtor, closing, owner_told, relayed, reopening)   # the defect fix: another session's next, needs, check or after change, or its close or reopen
    except Exception as e:  # noqa: BLE001  — the write is saved and published; a notice that fails is a stderr line, never a failed write
        print(f"owner: {gid} change not told: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        chg = ""
    quiet_ = h.quiet(item)
    if "the notice went to" in chg:       # a front agent mover's "not told" line above was true of the mover, not of the write: the notice went to the page
        told, named = told.replace(quiet_, ""), named.replace(quiet_, "")
    elif chg == quiet_ and quiet_ in told + named:
        chg = ""                          # the reply already says it once
    told += chg
    told += h.handoff_notify(gid, item)     # step 2: the new mover of a hand-off this write recorded is told, unless a notice above did
    if done_ix and steps_new is not None and item.get("status") == "open" and not (closing or reopening or needs_set or agent.strip() or "mover" in model_set or "mover" in model_drop):
        told += _handover_by_hand(gid, [_steps.first_line(steps_new[i]["text"]) for i in done_ix])      # a step marked done by hand: the session the next step names is handed the item, as a ticked step does
        item = {**_load(gid), "gid": gid}
    try:
        stale_wait = _stale_wait_notes(item_was, item, keeper_was)      # a wait cleared while an open next line still defers on it: named, so the writer rewords the line now
    except Exception as e:  # noqa: BLE001  — the write is saved and published; a note that fails is a stderr line, never a failed write
        print(f"update: {gid} stale-wait notes not made: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        stale_wait = ""
    machine_note = h.machine_note(gid, item, keeper_was)      # an open step names an offline machine and no machine anchor tells the mover when it is back: a note, never a refusal
    if dropped_hold:
        hint += (f"\n(note: {_gh.shown(gid)} waits on {OWNER}'s call (needs decision), so it is never on hold: the hold is dropped"
                 + (f"; its date {_wt.wake_value(meta)} stays, and no date parks an item on his call" if _wt.wake_value(meta) else "") + ")")
    return (f"updated {_gh.shown(gid)}.\n" + h.fmt(item) + hint + wait_fixed + work_note + steps_note + asked + watch_note + h.form_notes(description, next_judged, bool(hold or wake) and now_parked, meta, gid,
                                                                 cmd=item.get("status") == "open" and bool(ask or next_judged or needs_set),
                                                                 ext="external" in _needs_kinds(meta) and "external" not in [str(x).lower() for x in was_needs]) + desc_note + stale_wait + wait_note + machine_note + (_doing_wait_note(meta, next_judged) if item.get("status") == "open" else "") + _retired_note(expected_by, expected_reason) + ((h.wake_window_note(_uw.unfolded(meta) if kept_legacy_wake else meta) if wake and not backstop else "") or (h.wake_step_note({**item, "gid": gid}, (sender, debtor), legacy_wake=kept_legacy_wake) if wake or next_touch else "") if item.get("status") == "open" else "")
            + named + told + h.nag(debtor))


def _completion_anchor_prompt(gid: str, item: dict[str, Any]) -> str:
    """Completion is the keeper's cue to judge relevance: list the anchors scoped to this item, on whichever project's page holds them, whose other listed items
    are all closed (anchor_scope.completion_due); each page's keeper is asked about the anchors its own page holds, and told when the completing session is not that keeper."""
    h = _hooks()
    m = item.get("metadata") or {}
    project = str(m.get("project") or "")
    due = _ascope.completion_due(_anc.load(), gid, _anc.items())
    if not due:
        return ""
    text = ""
    for page in sorted({p for p, _e in due}, key=lambda p: (p != project, p)):          # the item's own project first
        urls = [e["url"] for p, e in due if p == page]
        text += (f"\n[anchors] {gid} was the last open item these {page} anchors were scoped to:\n" + "\n".join(f"- {u}" for u in urls)
                 + f"\nStill relevant? make one project-wide: anchors(project={page!r}, add=[url]); done with it: anchors(project={page!r}, remove=[url]). Nothing was removed.")
        stew = h.page_keeper(page)          # the page's keeper: a one-session page's own session, not the general -main agent
        mine = {h.session_id(h.holder(item))}
        if stew and h.session_id(stew) not in mine:          # a keeper completing its own item is not notified (one identity per pane)
            note = (f"[stackshot] {_gh.shown(gid)} completed by {_session_label(h.holder(item)) or 'a session'}; {page} anchors scoped to it with no open item left: "
                    + ", ".join(urls) + f" — keep one with anchors(project={page!r}, add=[url]) (project-wide) or drop it with remove=[url].")
            threading.Thread(target=h.push_noted, args=(stew, note), daemon=True).start()
            text += f"\n(keeper {stew} notified)"
    return text


def _handover_by_hand(gid: str, done: list[str]) -> str:
    """The reply line of an update that marked steps done: _handover for the item, a failure a stderr line and no line. A write that names the mover or needs itself makes its own hand-off and never reaches this."""
    h = _hooks()
    try:
        ho = h.handover(gid, time.time(), done)
    except Exception as e:  # noqa: BLE001  — the write is saved: a hand-over that fails is a stderr line, and the audit finds the next session unreached
        print(f"handover: {gid} not made: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return ""
    if not ho or ho["action"] not in ("moved", "fallback"):
        return ""
    h.publish()
    to = _session_label(ho["to"])
    return (f"\n(the next step is {to}'s: {_gh.shown(gid)} is handed to {to}, who is told)" if ho["action"] == "moved"
            else f"\n(the next step is {to}'s, but {to} cannot take the item now ({_clip_line(ho['why'], 80)}): it stays with you)")


def update_item(*args: Any, **kwargs: Any) -> str:
    """update_unlocked under the item lock (a failed delivery's record writes items from another thread; an
    update reads, changes and saves, so they take turns). The one entry of the update write: the update and complete tools, and every write of an item that the server makes (a wake, a cold call, a script's row)
    come through it (server.py's `_update` calls it)."""
    h = _hooks()
    h.evwait_preread(kwargs.get("wait_kind"), kwargs.get("wait_event"))      # an event wait's facts (GitHub, git) are read before the lock, not under it
    with _writes.ITEM_LOCK:
        try:
            return update_unlocked(*args, **kwargs)
        finally:
            h.close_was_set(None)


def complete_item(item_id: str, outcome: str = "", reason: str = "", description: str = "", superseded_by: str = "", sender: str = "", said: list[dict[str, Any]] | str | None = None,
                  outcome_text: str = "") -> str:
    """Close an item with how it ended: the complete tool without its identity and sender checks (the tool's own). It makes the update with status=completed, through server.py's `_update` (reached by its hook, so a suite
    that replaces it there still reaches the close), then adds the prompt about the anchors that were scoped to the item. The fields default to empty so that a pane with an older cached schema gets the refusal
    that says what is missing and how to close through the portal, not a schema error."""
    h = _hooks()
    gid = _norm_id(item_id)
    before = _load(gid)
    out = h.update(item_id, description=description, status="completed", sender=sender, outcome=outcome, reason=reason, superseded_by=superseded_by, said=said, outcome_text=outcome_text)
    try:
        out += _completion_anchor_prompt(gid, before)
    except Exception as e:  # never fail a completion over the prompt
        out += f"\n[anchors] prompt failed: {e}"
    return out


def confirm_item(item_id: str, sender: str = "") -> str:
    """Mark an item still true: sets its `confirmed` clock only (the confirm tool without its identity and sender checks). item_id: board#N (a bare number N is read as board#N)."""
    h = _hooks()
    gid = _norm_id(item_id, bare=True)
    item = _load(gid)
    item["confirmed"] = time.time()
    # a bare confirm moves `confirmed` only, never `activity`
    # a confirm changes nothing but its clock: no mover is settled and no hand-off record ended by it
    _writes.save(gid, item, writer=h.session_id(sender) if sender.strip() else h.holder(item), activity=_activity.CONFIRM, ctx=_writes.QUIET)
    h.publish()
    item["gid"] = gid
    at = h.render_when_words(dt.datetime.fromtimestamp(item["confirmed"], h.zone()))
    return f"confirmed {_gh.shown(gid)} at {at}.\n" + h.fmt(item) + h.nag(sender)
