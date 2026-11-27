"""update.py: updating, completing and confirming an item: every gate and every write of the update tool, in the order they ran in server.py.

`update_item` is the one place an item is updated: the update tool (`stackshot_update`, which stays on the surface and only parses its input, runs the checks that come before the item lock and shapes the reply), the complete
tool (`complete_item`: a close is an update with status=completed) and every write of an item that the server makes itself (a wake, a cold call, a script's row, the re-bullet route) come through it. It takes the item lock,
reads the item, runs the gates, applies the fields, the checklist, the wait, the hand-off and the close, saves the item through the write path (`writes.save`, with the write context its fields need: PLAIN, NAMED when the
write names the mover itself, QUIET when it only files or re-bullets), charges the page debt, tells the sessions the write concerns, publishes, and builds the reply. The order of those steps is part of what an update means and
is kept as it was in server.py. `confirm_item` only sets the `confirmed` clock (a QUIET save).

The write gates an update runs are service/gates.py's (`_gates.gate_*`, called in the order they ran in server.py), the field and decision rules model/'s (`field_gates.py`, `decision_gates.py`), each called on its module. The notices an update runs
and the helpers of the areas that still sit in server.py are reached through `Hooks`, which web/wiring.py fills once with `install` (web/server.py calls it at its import) (this module cannot import server.py: the surface sits above it), and each of them leaves `Hooks` when its area moves
under service/ (the telling next). A hook is looked up on its owner module (by web/wiring.py) when an update runs, so a suite that replaces one there still reaches the update; a suite that replaces a gate or a rule patches it on its owner. The per-write flags of server.py that an update reads or sets stay thread-locals there until the areas that share them move, and are reached through `Hooks` too: `session_next` (the create or update tool's
own call), `reformat` (the re-bullet route), `terminal_row` (the terminal prompt's and the job-gap routes' row), `close_was_set` (the item as it stood before the close, for the telling) and `wake_event_set` (the minute loop).

Imports point down only: this module imports the domain and core and the store's readers beside it (service/store.py), never web/."""
from __future__ import annotations

import datetime as dt
import functools
import inspect
import json
import re
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable

from fastmcp.exceptions import ToolError

from stackshot.anchors import anchor_sweep as _asweep
from stackshot.anchors import anchors as _anc
from stackshot.core import agentbox as _ab
from stackshot.core import call_log as _calls
from stackshot.core import config as _cfg
from stackshot.core.instance import OWNER
from stackshot.fleet.sessions_registry import _role_name, _session_label
from stackshot.github import ghsync as _gh
from stackshot.model import activity as _activity
from stackshot.model import decision_gates as _dg
from stackshot.model import member_gates as _mgates
from stackshot.model import faults as _faults
from stackshot.model import field_gates as _fg
from stackshot.model import model as _model
from stackshot.model import model_guards as _mg
from stackshot.model import next_rules as _nr
from stackshot.model import nextlines as _nl
from stackshot.model import owner_steps as _hs
from stackshot.model import states as _states
from stackshot.model import step_commands as _sc
from stackshot.model import steps as _steps
from stackshot.model import wait_tells as _wtell
from stackshot.model import work as _work
from stackshot.model.bullet_text import RX_MD_LINK, RX_NAKED_URL, _clip_line, goal_of, goal_words, stated_goal
from stackshot.model.ids import _norm_id, name_read as _name_read
from stackshot.model.needs import _NEEDS_KINDS, _canon_needs, _needs_kinds, _needs_list, _needs_of, _needs_sessions, _needs_store, _waits_decision
from stackshot.projects import pages as _pages
from stackshot.service import anchor_offers as _anchor_offers
from stackshot.service import checks as _checks
from stackshot.service import gates as _gates
from stackshot.service import handoff as _handoff
from stackshot.service import proofs as _proofs
from stackshot.service import released_live as _rlive
from stackshot.service import step_settle as _settle
from stackshot.service import telling as _telling
from stackshot.service import writes as _writes
from stackshot.service.save_hooks import hooks as _save_hooks
from stackshot.service.store import _load, _shown_ids
from stackshot.waits import handoff as _ho
from stackshot.waits import server_fixes as _sf
from stackshot.waits import stall as _stall
from stackshot.waits import until_write as _uw
from stackshot.waits import wait_end as _we
from stackshot.waits import wait_list as _wl
from stackshot.waits import wait_list_write as _wlw
from stackshot.waits import waiting as _wt
from stackshot.waits import watchers as _watch


RETIRED_NOTE = ("\n(note: expected_by and expected_reason are no longer kept: a doing item carries no expected time and shows how long it has run. "
                "If it waits on a date or a person, park it: update(until=\"YYYY-MM-DD\", wait_kind=\"time\", wait_basis=\"<what the date is, with its date YYYY-MM-DD>\"), or after=[\"board#N\"], "
                "or wait_kind=\"relay\" with wait_event=<who> and until=<the day to chase>. A park of the wait cap's days or less needs his recorded words: there set a bare until with wait_reason.)")

_STALE_WAIT_NOTE_MAX = 5
_DROPPED_NOTE_MAX = 5           # the old description lines a dropped-lines note names, then "and N more"
_DROPPED_NOTE_LINE_MAX = 120    # the characters of each old line the note shows
_DROPPED_NOTE_LINK_MAX = 300    # a cut that would fall inside a link runs on to the link's end, up to this many characters; past it the line is cut plainly

# A write whose every argument is one of these is bookkeeping on the item, not work on it: it names no background agent in needs
# (_name_on_write). A page rename moves many items with update(project=<new key>), and the mover, a background agent, must not be
# named in each one's needs as if it had begun working on it.
_FILING_ONLY = frozenset({"project", "subject", "priority", "owner_name", "observers", "tell_him", "contact", *_model.MODEL_FIELDS, "clear_goal", "clear_mover", "clear_then", "clear_wait"})


@dataclass(frozen=True)
class Hooks:
    """What an update still reaches in server.py (the notices and helpers it shares with the create tool, the close and the telling, the per-write flags and a few constants), in the names they have there without the leading underscore;
    web/wiring.py builds one and gives it to `install`. A gate raises `ToolError` itself; a flag is a function that reads (or, `close_was_set`, writes) the thread-local."""
    after_open: Callable[..., Any]
    anchor_wait_gate: Callable[..., Any]
    ask_none: tuple[str, ...]      # the words that mean no ask, no observers, no check (server._ASK_NONE)
    ask_owed: Callable[..., Any]
    basis_put: Callable[..., Any]
    basis_words: str                  # how the wait_basis gate names what a park waits on (owner_words._BASIS_WORDS)
    cap_ok_drop: Callable[..., Any]
    cap_ok_put: Callable[..., Any]
    contact_alive: Callable[..., Any]
    contact_fronts: Callable[..., Any]
    contact_same: Callable[..., Any]
    date_only_wait: Callable[..., Any]
    date_parked: Callable[..., Any]
    eff_state: Callable[..., Any]
    evwait_gate: Callable[..., Any]
    evwait_preread: Callable[..., Any]
    fallback_wait_date: Callable[..., Any]
    finishes_own_line: Callable[..., Any]
    fmt: Callable[..., Any]
    form_notes: Callable[..., Any]
    gate_ask: Callable[..., Any]
    gate_options: Callable[..., Any]
    handoffs_in: Callable[..., Any]
    hold_held_by: Callable[..., Any]
    hold_set: Callable[..., Any]
    is_held: Callable[..., Any]
    lift_ask: Callable[..., Any]
    machine_note: Callable[..., Any]
    main_agent: Callable[..., Any]
    model_apply: Callable[..., Any]
    model_guards_on: Callable[..., Any]
    model_of: Callable[..., Any]
    nag: Callable[..., Any]
    name_on_write: Callable[..., Any]
    next_put: Callable[..., Any]
    owed_mark: Callable[..., Any]
    owner_quote_on: Callable[..., Any]
    owner_state_mover: Callable[..., Any]
    owner_then_default: Callable[..., Any]
    then_stands: Callable[..., Any]
    owner_want: Callable[..., Any]
    parse_wake: Callable[..., Any]
    publish: Callable[..., Any]
    record_fixes: Callable[..., Any]
    owing_note: Callable[..., Any]
    release_after: Callable[..., Any]
    render_hold_at: Callable[..., Any]     # web/render.py's hold_at, option_lines, same_ref and when_words (web/ sits above this module)
    render_option_lines: Callable[..., Any]
    render_same_ref: Callable[..., Any]
    render_when_words: Callable[..., Any]
    said_note: Callable[..., Any]
    scoped_anchors: Callable[..., Any]
    session_id: Callable[..., Any]
    session_roster: Callable[..., Any]
    state_apply: Callable[..., Any]
    state_end: Callable[..., Any]
    store_ref: Callable[..., Any]
    switchover_on: Callable[..., Any]
    update: Callable[..., Any]
    wait_end_sent_back: Callable[..., Any]
    wake_at: Callable[..., Any]
    wake_event_set: Callable[[], None]     # wake the minute loop at once (runner.wake(): the event and the wake file) when a wake or a hold changed
    wake_park_line: Callable[..., Any]
    wake_step_note: Callable[..., Any]
    wake_window_note: Callable[..., Any]
    watch_on_write: Callable[..., Any]
    writer_owes: Callable[..., Any]
    zone: Callable[..., Any]               # the board's time zone as server.py holds it (ZONE, read when the reply is made): the confirm reply says when in it


_hooks_: Hooks | None = None


def install(hooks: Hooks) -> None:
    """Give the update the gates and notices that are still server.py's (once, at its import)."""
    global _hooks_
    _hooks_ = hooks


def _hooks() -> Hooks:
    if _hooks_ is None:
        raise RuntimeError("the update has no hooks installed (web/wiring.py installs them, called from web/server.py at its import)")
    return _hooks_


def _wait_is_bare(m: dict[str, Any]) -> bool:
    """A date with nothing else stated beside it: no hold, no kind, no basis, no after link (the date is then a wait on that date alone, outside a hand-off)."""
    return _uw.is_bare(m)


def _old_holder_goes(meta: dict[str, Any]) -> bool:
    """Is the stored mover the old holder a hand-off by needs replaces: a session that is not among the sessions `needs` names now (and not the owner)? The write drops it then."""
    h = _hooks()
    stored_mv = _model.norm_who(meta.get("mover"))
    named_now = _needs_sessions(meta)
    nm_mv = _anc.names()
    return bool(stored_mv and named_now and not _model.is_owner(stored_mv) and not any(x == stored_mv or _anc.canonical(x, nm_mv) == _anc.canonical(stored_mv, nm_mv) or h.render_same_ref(x, stored_mv) for x in named_now))


def _hands_on(gid: str, was: dict[str, Any], now_item: dict[str, Any], handed: Any, writer: str, failed: list[bool] | None = None, picker_alias: bool = False) -> bool:
    """Does this write hand the item on to a session: a hand-off line in next, or a change of the DERIVED mover (what the hand-off record reads, handoff.detect): a mover argument, needs naming a
    session, a reopen with one. The date a bare wait carries is left out of both readings (an item with it reads as waiting and has no mover), so the question is the write's own: with the date
    it gives (or already held) set aside, did the mover change to a session other than the writer? A hand-off to the owner is none here (his step with a date is a park of its own). A reading that fails counts as a hand-off (fail closed), and says so in `failed` when the caller passes a list."""
    if handed:
        return True
    try:
        def undated(it: dict[str, Any], keep_mover_of: dict[str, Any] | None = None) -> dict[str, Any]:
            m = it.get("metadata") or {}
            if keep_mover_of is not None:      # the old parameter post_wake_mover stored as `mover` names the picker of a wait, never a hand-over: the mover is read as it was before the write
                m = {k: v for k, v in m.items() if k != "mover"} | ({"mover": keep_mover_of["mover"]} if keep_mover_of.get("mover") else {})
                it = {**it, "metadata": m}
            return {**it, "gid": gid, "metadata": {k: v for k, v in m.items() if k not in ("wake", "until", "ask_by")}} if _wait_is_bare(m) else {**it, "gid": gid}
        to = _ho.detect(undated(was), undated(now_item, (was.get("metadata") or {}) if picker_alias else None), _session_label(writer) or writer, writer if _anc.is_id(writer) else "", _handoff.ho_derive, _handoff.ho_same)
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


def _list_end_words(waits: Any, wake: str, clear_wake: bool, meta: dict[str, Any]) -> str:
    """The words of the clock-renewal refusal for `waits=[]` beside a later `until` on a stored list ("" when the write is no such one). It only names the case and judges nothing: whether the write moves
    the day out and carries progress is gates.gate_clock_renewal's own test, which takes these words as its refusal in place of its general ones (a write with progress goes through, as it does on a list-free item)."""
    if not (_wlw.clearing(waits) and wake.strip() and not clear_wake and _wl.valid(meta)):
        return ""
    old_, new_ = _uw.date_of(meta), str(_hooks().parse_wake(wake))
    if not old_:
        return ""
    return (f"Refused: waits=[] ends the list, and until={new_} beside it would be a later day than the list's backstop day {old_}: moving a date out is not progress. Send waits=[] alone to end the wait "
            f"(or until={old_} or earlier to wait on that date alone)")


def _list_plan(waits: Any, wait_mode: str, *, gid: str, meta: dict[str, Any], proj_for: str, wake: str, clear_wake: bool, status: str, others: dict[str, Any]) -> "_gates.WaitsPlan | None":
    """The `waits` and `wait_mode` of an update (gates.gate_waits, with the gates of the single waits as its callbacks), judged on the item's metadata as the write works on it (the stored `until` stands as the wake). The backstop
    day is the one this call gives (`wake`, which `until` came in as), else the one the item holds. None when the call passes neither."""
    h = _hooks()
    leaves_list = status != "completed" and not any(others.get(k) for k in ("wait_kind", "wait_anchor", "wait_event", "after", "clear_wait"))      # a write that keeps the stored list (a single wait, a clear or a close replaces it)
    if leaves_list and not _wlw.passed(waits) and wake.strip() and not clear_wake and _wl.valid(meta):      # a new backstop day alone (until=…) on a stored list: a time line later than it could never arrive, as when the list is sent again with it
        gate_dates = [(i, ln["until"]) for i, ln in enumerate(_wl.lines(meta), 1) if ln["kind"] == "time" and not _wl.arrived(ln)]
        _gates.gate_time_lines(gate_dates, str(h.parse_wake(wake)))
    if waits is None and not str(wait_mode or "").strip():
        return None
    if _wlw.passed(waits) and not _wlw.clearing(waits):
        if status == "completed":
            raise ToolError("Refused: a completed item waits on nothing; waits goes with an open item")
        if clear_wake:
            raise ToolError("Refused: a list needs its backstop day, so until cannot be none beside waits: pass until=<date>, or clear_wait=true to end the wait")
    backstop = (str(h.parse_wake(wake)) if wake.strip() else "") or _uw.date_of(meta)
    return _gates.gate_waits(waits, wait_mode, gid=gid, project=proj_for, creating=False, stored=meta, backstop=backstop, others=others,
                             anchor_gate=lambda tmp: h.anchor_wait_gate({}, tmp, gid), event_gate=lambda tmp: h.evwait_gate({}, tmp, creating=True))


def _list_note(plan: "_gates.WaitsPlan", meta: dict[str, Any], open_: bool) -> str:
    """The reply's line for a write of a list: what the item waits on now."""
    if not open_:
        return ""
    if plan.kind == "list":
        return "\n(wait list: " + _wl.summary({**meta, "until": _uw.date_of(meta)}, _gh.shown) + ")"
    if plan.kind == "one":
        return f"\n(the list is down to one wait, so it is stored as the single wait it is: {_wl.line_text(plan.lines[0], _gh.shown)})"
    day = _uw.date_of(meta)      # a clear beside a later `until` leaves the item waiting on that date, as a wait on a time
    return f"\n(the wait on a list is cleared: the item waits on the date {day} now)" if day else "\n(the wait on a list is cleared: the item waits on nothing now)"


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


def _server_step_reworded(item_was: dict[str, Any], reword: Any, step: str) -> tuple[Any, str]:
    """A reword of the line the server keeps from the item's step (metadata.owner_step of an item that stores a step) is the step's new words: → (the reword without that entry, None when nothing is left of it; the step
    to set, the new words with his name off), and the reply says so (call_log.fixed). A call that passes step= too, an item that stores no step (his step then comes from the ask: the reword loop refuses it,
    naming the ask) and a new text that opens with another actor are left as they are. The server then makes the line again from the new step and drops the old one, as every change of the step does."""
    m = item_was.get("metadata") or {}
    rec = _hs.recorded(m)
    if step.strip() or not rec or not str(m.get("step") or "").strip() or item_was.get("status") != "open" or not _steps.reword_given(reword):
        return reword, step
    spec = reword
    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except ValueError:
            return reword, step
    if not isinstance(spec, dict):
        return reword, step
    cl = _steps.view(m, keeper=str(m.get("owner") or ""))
    for ref, text in spec.items():
        try:
            (i,) = _steps.resolve(cl, [ref], "reword", "reworded")
        except _steps.StepError:
            continue
        if cl[i]["status"] == _steps.OPEN and _hs.same_line(cl[i]["text"], rec) and isinstance(text, str) and text.strip() and (not _steps.opener(text) or _hs.is_named(text)):
            rest = {k: v for k, v in spec.items() if k != ref}
            body = _steps.without_owner(text)
            _calls.fixed("step-reworded", f"the reword of {OWNER}'s own step {i + 1} was done as a new step text (the line comes from step=): the step now reads \"{_clip_line(body, 90)}\", and the old line shows as dropped",
                         fields=["reword", "step"])
            return (rest or None), body
    return reword, step


def _with_lines(next_text: str, own_text: str, lines: list[str], have: set[str], fresh: bool) -> str:
    """The text of next with `lines` (each a step) added at its end, the ones that read as a step already there left out (`have`: steps.key of every open step and every line of the text). `next_text` is what the call
    passes; when it passes none, `own_text` stands in for it: the lines of the sender's own that the write would otherwise replace (nextlines.write replaces the sender's lines as a whole). `fresh`: the call wipes or
    removes the sender's lines (clear_next, next="none"), so none stands in. `next_text` as it is when every line is there already."""
    mine = [ln for ln in lines if _steps.key(ln) not in have]
    if not mine:
        return next_text
    base = next_text.rstrip() if next_text.strip() else ("" if fresh else own_text.rstrip())
    return (base + "\n" if base else "") + "\n".join(mine)


def _left_out(dry_meta: dict[str, Any], steps_old: list[dict[str, Any]], done_ix: list[int], drop_ix: list[int], reword_ix: dict[int, str], keeper: str) -> tuple[list[int], bool]:
    """What a write of next (`dry_meta`: the item's metadata with the write put in) does to the open steps, lined up as steps.apply lines them (next_rules.moves): (the positions of the open steps it leaves out with no word on
    them, whether a new line is a leaving step's text with words added: the rewrite N3 refuses). A step this call marks done or dropped or rewords is not left out, and the new words of a reword are not a new line."""
    text = _fg._nl_text_without(dry_meta, [steps_old[i]["text"] for i in (*done_ix, *drop_ix)], keeper)
    leaving, arriving = _nr.moves(steps_old, done_ix, drop_ix, text)
    skip = {*drop_ix, *reword_ix}
    worded = {_steps.key(t) for t in reword_ix.values()}
    fresh = [c for c in arriving if _steps.key(c) not in worded]
    return [i for i, _t in leaving if i not in skip], bool(_nr.growths([t for i, t in leaving if i not in skip], fresh))


def _dropped_line_shown(text: str) -> str:
    """One old description line as the dropped-lines note shows it: whole when it is at most _DROPPED_NOTE_LINE_MAX characters, else cut at a word before that limit. A cut never falls inside a
    link or a naked URL (the address is the fact the writer would want back): it runs on to the end of the link, unless that is past _DROPPED_NOTE_LINK_MAX, where the line is cut plainly. A cut
    line ends with an ellipsis."""
    t = " ".join(str(text or "").split())
    if len(t) <= _DROPPED_NOTE_LINE_MAX:
        return t
    spans = [m.span() for rx in (RX_MD_LINK, RX_NAKED_URL) for m in rx.finditer(t)]
    lim = _DROPPED_NOTE_LINE_MAX
    cut = next((e for b, e in spans if b < lim < e), 0)      # the limit falls inside a link: run on to its end
    if not cut:
        cut = len(t[:lim].rsplit(" ", 1)[0]) if " " in t[:lim] else lim      # else a word boundary before the limit
        cut = next((e for b, e in spans if b < cut < e), cut)      # …which moves to the end of a link it falls inside
    cut = min(cut, max(_DROPPED_NOTE_LINK_MAX, lim))
    return t if cut >= len(t) else t[:cut].rstrip(" ,;:") + " …"


def _dropped_lines_note(old: Any, new: Any) -> str:
    """The reply line of a write that changed the description and left out lines the old one held: every old line (whitespace trimmed and collapsed, the leading `- ` off, so a line that is only
    re-indented, re-spaced, reordered or moved under another bullet is kept) that no line of the new one matches, at most _DROPPED_NOTE_MAX of them, each cut at _DROPPED_NOTE_LINE_MAX, then
    "and N more". A reworded line is one dropped and one new line: the note shows its old text, so the writer can put a fact back. No refusal and nothing stored differently. "" when no line is dropped."""
    key = lambda ln: " ".join(re.sub(r"^-[ \t]+", "", ln.strip()).split())
    kept = {key(ln) for ln in str(new or "").splitlines()}
    gone: list[str] = []
    for ln in str(old or "").splitlines():
        k = key(ln)
        if k and k not in kept and k not in gone:
            gone.append(k)
    if not gone:
        return ""
    shown = [f'"{_dropped_line_shown(k)}"' for k in gone[:_DROPPED_NOTE_MAX]]
    if len(gone) > _DROPPED_NOTE_MAX:
        shown.append(f"and {len(gone) - _DROPPED_NOTE_MAX} more")
    return (f"\n(note: this write dropped {len(gone)} line{'' if len(gone) == 1 else 's'} of the old description (a reworded line counts as dropped, its new wording as a new line); "
            f"put back any fact you meant to keep: {'; '.join(shown)})")


def _goal_moved_note(item_was: dict[str, Any], item: dict[str, Any], sent: str) -> str:
    """The reply line of a write that changed the words of the item's Goal sentence and left its subject as stored: the title and the `Goal:` bullet name one outcome, so the subject is quoted, with what to send when
    the outcome moved. Counted in the call log (call_log.noted). Information only: nothing is refused or stored differently. `sent` is the description as the call passed it: the words must differ both there and as
    stored, so neither the server's split of a long bullet nor a long Goal sent again and split the same way is a change. "" when the stored description opens with no `Goal:` bullet, the one it replaces gave no
    sentence, the words are the same (a re-formatting, a label put right) or the write stored another subject."""
    new, old, said = goal_of(item.get("description")), stated_goal(item_was.get("description")), stated_goal(sent)
    subject = str(item.get("subject") or "")
    if new is None or old is None or said is None or subject != str(item_was.get("subject") or "") or goal_words(old) in (goal_words(new), goal_words(said)):
        return ""
    _calls.noted("goal-moved")
    return f'\n(note: the Goal changed and the subject did not; the stored subject is "{_clip_line(subject)}": send subject= if the outcome moved)'


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
    if not writer or h.session_id(writer) in {h.session_id(_telling.holder(item_was)), h.session_id(_telling.holder(item))}:
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
    for who in (_telling.holder({"status": "open", "metadata": meta}), _telling.holder({"status": "open", "metadata": was}), str(writer or "")):
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


def _doing_wait_note(meta: dict[str, Any], next_: str = "", busy: str | None = None) -> str:
    """A valid reason to wait on an item does not warrant marking it as on agent and letting it sit there for hours: it should be marked waiting.
    A note on the reply (never a refusal) when the item ends the write in the stored state doing, not on hold, and a line of next this write set reads as a wait on a time or an event
    rather than work in hand (model_guards.reads_as_wait). Not when `busy` (the words for what of the holder's own runs on the item, asked by the update tool before the lock: gates.busy_note_answer, audit/busy_hold.py)
    is not empty: a running subagent of the holder, or a running release of a pull request tied to the item, is on the item, so the wait wording is about that run, which is work in hand, and the note's advice to park would be the hold the update refuses. None or
    "" (nothing running, or nothing could be told) leaves the note as it is."""
    if meta.get("state") != "doing" or meta.get("hold"):
        return ""
    found = _mg.reads_as_wait(next_) if next_ else ""
    if not found or busy:
        return ""
    return (f"\n(note: this item is doing, but its next reads as a wait ({found}), not work in hand; a doing item that waits shows as on an agent while nobody works it. "
            "Park it this turn with update(until=\"<the time it waits for>\", wait_kind=\"time\", wait_basis=\"<what it waits on, with its date YYYY-MM-DD>\"); a park of the wait cap's days or less needs his recorded words, so for a date within them set a bare until with wait_reason)")


def _wait_tells(sender: str, reasons: "list[str]", nexts: "list[str]", sets_wait: bool) -> str:
    """Two notes on the reply (never a refusal) of a write that sets a wait, both only for a back (background) or builder session: it waits on stackshot's own count, dry run or watch, which the writer can read or stage now
    (_wtell.own_read, read from the reason this write gives, its wait_basis, wait_event and wait reason, never its next or status line, and silent when the reason names an outside party or another blocker); or it waits on a front
    agent's answer, whose call is the writer's to decide or to put to the user (_wtell.front_named, read from the reason and the next: the front agent is the one waited on or asked, not one told something). Not judged: a write
    that sets no wait (a hand-off's backstop date is none), a front agent's own write, a writer no project page lists as back, an `after` on an item a front agent holds (a dependency on its work is a wait), and a wait on a front
    agent that nothing names (a `needs` naming one). The roles are read only when a text could be told at all. A failure of the check is a stderr line, never a failed write: the own-read note, which needs the roles only to
    leave out a writer that is no back session, then stands."""
    if not sets_wait or not sender.strip():
        return ""
    own = bool(_wtell.own_read(*reasons))
    front = _wtell.could_name_front([*reasons, *nexts])
    if not own and not front:
        return ""
    out = _wtell.OWN_READ_NOTE if own else ""
    try:
        roles = _anc.session_roles()
        me = roles.get(_role_name(roles, sender)) or {}
        if me.get("role") != "back":
            return ""
        fronts = [n for n, r in roles.items() if r.get("role") == "front" and not r.get("retired")]
        who = _wtell.front_named([*reasons, *nexts], fronts) if front else ""
        if who:
            out += _wtell.FRONT_ANSWER_NOTE.format(who=_session_label(who), him=OWNER)
    except Exception as e:  # noqa: BLE001  — the tell is an extra: a failure leaves the write as it was
        print(f"update: wait tells not made: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return out


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
        _gates.gate_wait_basis({**item, "metadata": {**meta, "wake": wk}}, basis, wk, held=True)
        note = (f"\n(fixed: this park had a wake and no wait reason, and your {where} says what it waits for (\"{_clip_line(words, 90)}\"), so that line is the wait_basis. "
                "Send wait_basis=\"<what it waits on, with its date YYYY-MM-DD>\" to use other words: the server then leaves the field alone)")
        return basis, (note, wk, f"wait reason: the park had a wake and no reason; the {where} line \"{_clip_line(words, 80)}\" is its wait_basis. A wait_basis sent in a later write replaces it")
    except Exception as e:  # noqa: BLE001  — the fix is an extra: a failure leaves the write as it was, with the refusal
        if not isinstance(e, ToolError):
            print(f"loose wait reason: not judged: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return none


def _answered_since_note(gid: str, item: dict[str, Any], sender: str) -> str:
    """The reply line for a write by a session whose picture of the item is older than his answer: the latest answer recorded on the item (`metadata.answers`) is newer than the sender's last write to it (`telling.touched_or_unknown`: one
    of the item's revisions since then names the sender as its writer). The server keeps no log of what a session read, so a write is the signal there is: a session that wrote after his answer has seen the item as it stands. The
    write itself is never refused; the line says the item has moved. "" for a write with no session behind it (the server's own, a script's), an item he never answered, a session the answer was handed to (its `told` list on the
    answer's own record: it holds the answer already, whether the pending answer is settled or not), a sender that wrote after his answer, and when the item's history could not be read in full (a store outside git, more than 60 newer
    revisions, a failed read): a missing line is better than a wrong one. Never raises: read before the write is saved, since that write is the sender's too."""
    who = sender.strip()
    try:
        if not who or who == _ho.COLD or who.startswith("a script on "):
            return ""
        recs = [a for a in ((item.get("metadata") or {}).get("answers") or []) if isinstance(a, dict) and isinstance(a.get("ts"), (int, float)) and not isinstance(a.get("ts"), bool)]
        if not recs:
            return ""
        rec = max(recs, key=lambda a: a["ts"])
        if _save_hooks().session_id(who) in (rec.get("told") or []):      # handed his answer already (kept on the record by service/answer.py `_record_told`)
            return ""
        if _telling.touched_or_unknown(gid, who, float(rec["ts"])):
            return ""
        at = _hooks().render_when_words(dt.datetime.fromtimestamp(float(rec["ts"]), _hooks().zone()))
        verb = "answered" if rec.get("kind") == "decision" else "commented on"
        words = _save_hooks().answers_mod()._answer_words(rec, 200)
        where = "on GitHub" if rec.get("via") == "github" else "on the board"
        return f"\n(note: {_model.owner_display(item.get('metadata'))} {verb} {_gh.shown(gid)} {where} at {at} {_cfg.tz_abbr()}{': ' + words if words else ''}. You have not written to the item since his answer, so what you hold of it may be out of date: read it again before you rely on it)"
    except Exception as e:  # noqa: BLE001  — the write goes on; a note that fails is a stderr line
        print(f"update: {gid} answer note not made: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return ""


def _reads_time_wait(item: dict[str, Any]) -> bool:
    """The model reads the open item as a wait on a time with no hold flag (the gate's `reads_time_wait`: one reading for the tool and the self-wait check)."""
    return _gates.reads_time_wait(item)


def _basis_frame(item: dict[str, Any], meta: dict[str, Any], status: str, wake: str, ask_by: str, wait_kind: str, hold: bool, state_st: str) -> tuple[dict[str, Any], str, bool]:
    """What a wait_basis is judged against, for the write that sends it → (the item with the status the write gives it, the wake it stands for, whether the item is a time wait held: a hold, a held or verifying
    item). Raises ToolError for a wake in no valid form. A relay or event wait keeps its end day, not a wake: its basis stands for that day."""
    h = _hooks()
    basis_day = ""
    if not wake and not meta.get("wake") and (wait_kind.strip().lower() or _uw.kind_of(meta)) in ("relay", "event"):
        basis_day = _uw._dated(ask_by) or _uw._dated(meta.get("ask_by"))
    held = _gates.basis_held(item, hold=hold, verifying=state_st == "verifying")
    return {**item, "status": status or item.get("status")}, (h.parse_wake(wake) if wake else str(meta.get("wake") or "") or basis_day), held


@_faults.collected
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
    tell_him: list[str] | str | None = None,
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
    waits: list[dict[str, Any]] | str | None = None,
    wait_mode: str = "",
    busy_note: str | None = None,
) -> str:
    """The update tool; its description is _UPDATE_DESC (+ _WAIT_FORM). The caller checks the identity (_who): the update and
    complete tools do, the client API's recycle-due write is proved by its machine token instead."""
    if not _steps.reword_given(reword):
        reword = None             # {} and "{}" name no step: the call is as if it passed none
    given = {k: v for k, v in locals().items() if k not in ("item_id", "sender", "wait_reason", "fixes", "until_wait", "busy_note") and v not in (None, "", False, 0)}      # what the call passes, before any default or rewrite below
    fc = _faults.current()          # the faults of the form this write finds are kept and refused together (model/faults.py): the gates up to the checkpoint below go on past a fault on stand-in values
    h = _hooks()
    filing_only = bool(given) and set(given) <= (_FILING_ONLY | ({"said"} if "tell_him" in given else set()))      # a bookkeeping write (a page rename's update(project=<new key>)): no work was done, so no agent is named for it
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
        fc.add("Refused: clear_ask drops the ask; it does not go with a new ask")
    clear_ask = clear_ask or ask.strip().lower() in h.ask_none       # ask="none" or clear_ask=true clears it, like due and wake
    own_links = not (_writes.question() or _writes.cold_ask())       # a script's question and the cold call's ask link what they link: a script cannot make a decision page; both are flags the server sets around its own write, never a label a caller passes (the sender is free text)
    ask = "" if clear_ask else (fc.call(h.gate_ask, ask, links=own_links, default="") if ask else "")
    opts = fc.call(h.gate_options, options, links=own_links)           # None: not passed; []: clear
    if clear_options:                                 # the flag, like clear_wake: the same as options=[] / "none"
        if opts:
            fc.add("Refused: clear_options drops the options; it does not go with a new list")
        opts = []
    gid = _norm_id(item_id, bare=True)
    item = _load(gid)
    if status == "completed":
        _name_read(gid, str(item.get("subject") or ""))          # a close read from a bare number or #N says which item it is: its subject's first words
    answered_note = _answered_since_note(gid, item, sender)      # read now: the write below is the sender's too
    had_hold = bool((item.get("metadata") or {}).get("hold"))      # read before the unfold, which stands a basis or the kind time in as a hold
    was_until = _uw.unfold_item(item)                    # a stored until stands as the old working fields for this write's gates (until_write.py); it is folded back just before the save
    if was_until and clear_wake and _uw.kind_of(item["metadata"]) in ("", "time") and not had_hold:
        clear_hold = True                                # the date of a wait on the date alone is the whole wait: dropping it ends the wait, the hold it stands as goes with it
    item_was = json.loads(json.dumps(item))             # the item as it stood, for the state checks (a re-park, a decision asked again, a stale next)
    meta = dict(item.get("metadata") or {})
    old_ask = bool(str(meta.get("ask_by") or "").strip()) and not _watch.stored_kind(meta)      # an ask_by with no wait_kind, as stored before this write
    gives_wait = bool(wake or hold or after or waits or any(str(v or "").strip() for v in (ask_by, wait_kind, wait_anchor, wait_event)))
    if gives_wait and item.get("status") == "open" and _watch.dead_ask_by(meta, time.time()):
        meta.pop("ask_by", None)                       # a passed ask_by with no kind was nobody's date: the wait this write gives never takes it as its own
    before = json.loads(json.dumps({k: meta.get(k) for k in ("next", "needs", "check", "after")}))   # what the mover is told of, as it stood
    ask_was = meta.get("ask")
    meta.pop("refiled", None)                          # the last refile's record is its History line; only a write that refiles carries it
    was_needs = _needs_of(meta)
    proj_for = project or str(meta.get("project") or "")
    own_for = owner or _telling.holder(item)       # the session the item is held by (its mover), which needs may name and which writes step statuses; the creator holds no part
    contact_new = ""
    if contact.strip():                    # the contact: a front agent of the project the item will be filed under; refused before anything is written
        if (status or item.get("status")) == "completed":
            fc.add(f"Refused: {_gh.shown(gid)} is completed and keeps the contact it had as its record; reopen it (status=open with a next) before changing the contact")
        else:
            contact_new = fc.call(_gates.gate_contact, contact, proj_for, (str(meta.get("owner") or ""), str(meta.get("contact") or "")), default="")
    if needs_set:
        if (got_needs := fc.call(_gates.gate_needs, needs, proj_for, own_for, _model.norm_who(meta.get("then")))) is not None:
            _needs_store(meta, got_needs)
    if agent.strip():                                  # the older form: that session becomes the one named in needs; "none" takes the sessions out
        kinds = _needs_kinds(meta)
        if agent.strip().lower() in h.ask_none:
            _needs_store(meta, _canon_needs(kinds))
        elif (got_agent := fc.call(_gates.gate_needs_session, agent, proj_for, own_for, _model.norm_who(meta.get("then")), sender.strip(), _gates.lazy_said(said, sender.strip()))) is not None:
            _needs_store(meta, _canon_needs([*kinds, got_agent], _anc.names()))
    reword, step = _server_step_reworded(item_was, reword, step)      # a reword of the line the server keeps from step= is the new step text, as the same call would give it
    step_lines: list[str] = []
    step_long = ""         # the step as the writer sent it, when it is split below
    split_note = ""        # why a long step was left as written (the refusal of it says so)
    if step.strip() and step.strip().lower() not in h.ask_none and _writes.session_next():      # a session's write only: a script's step (item sync, the terminal rows) is stored as it is made
        step_long = _states.step_text(step)
        step, step_lines = _fg.fix_long_step(step_long)      # a long chain of actions becomes a short summary and one line of next per action (the reply says so); a short, numbered or one-action step is as written
        if not step_lines:
            split_note = _fg.long_step_skipped(step_long)      # a step over the limit that stays as written is refused as ever: the refusal says why it was not split
            step_long = ""
    state_st, state_given, step_withdrawn = fc.call(_gates.gate_state_args, {"expected_by": expected_by, "expected_reason": expected_reason, "step": step, "supplies": supplies}, split_note=split_note, default=("", {}, False))   # a bad value is refused before anything is written
    draft_set, clear_draft = fc.call(_gates.gate_draft_args, draft, clear_draft, default=("", clear_draft))   # a bad draft is refused before anything is written
    list_end_words = _list_end_words(waits, wake, clear_wake, meta)      # read on the item as it stands, before the write changes it
    n_wait_args = fc.count
    list_plan = fc.call(_list_plan, waits, wait_mode, gid=gid, meta=meta, proj_for=project or str(meta.get("project") or ""), wake=wake, clear_wake=clear_wake, status=status or str(item.get("status") or ""),
                        others={"wait_kind": wait_kind.strip(), "wait_anchor": wait_anchor.strip(), "wait_event": wait_event.strip(), "after": after if after is not None and after != [] and str(after).strip() else "",
                                "ask_by": ask_by.strip(), "hold": hold, "wait_basis": str(wait_basis or "").strip(), "clear_hold": clear_hold, "clear_after": clear_after,
                                "clear_wait_basis": clear_wait_basis, "clear_wait": clear_wait and not _wlw.clearing(waits)})
    list_drop: set[str] = set()
    if list_plan is not None and list_plan.kind == "clear":
        clear_wait = True                       # a list cleared (waits=[]), or the one line left had arrived: the wait ends as clear_wait ends it
    elif list_plan is not None and list_plan.kind == "one":     # a list an edit leaves with one line is stored as the single wait that line is: the same call as if the writer had passed that wait
        one = _wlw.single(list_plan.lines[0])
        list_drop = {"waits", "wait_mode"}
        wait_kind, wait_anchor, wait_event = one.get("wait_kind", ""), one.get("wait_anchor", ""), one.get("wait_event", "")
        if "after" in one:
            after = one["after"]
        if "until" in one:                      # a date alone: the wait is the date (never later than the backstop the list had)
            back_ = _uw.date_of(meta) if not wake else str(h.parse_wake(wake))
            date_ = back_ if _wlw.time_before(back_, one["until"]) else one["until"]
            if h.wake_at(date_) <= _pages.zone_now():      # the date has come: the line has arrived, the wait is over
                clear_wait, list_plan = True, _gates.WaitsPlan("clear", [], note="\n(the one line left is a date that has come, so the wait is over and is cleared)")
            else:
                list_drop.add("wait_kind")
                wake, until_wait = date_, True
                list_plan.lines = [{**list_plan.lines[0], "until": date_}]      # the reply says the day the item waits until (the backstop when the line's own date is later), not the line's
        elif wait_kind in ("relay", "event"):   # a relay or event wait takes its ask-by day alone
            wake = wake.strip()[:10]
            if meta.get("wake") and len(str(meta["wake"])) > 10:
                meta["wake"] = str(meta["wake"])[:10]
    model_set, model_drop = fc.call(_gates.gate_model_args, {"goal": goal, "mover": mover, "then": then, "wait_kind": wait_kind, "wait_anchor": wait_anchor, "wait_event": wait_event,
                                                  "ask_by": ask_by, "post_wake_mover": post_wake_mover},
                                    {"goal": clear_goal, "mover": clear_mover, "then": clear_then, "wait": clear_wait}, default=({}, set()))   # a bad value is refused before anything is written
    wait_args_bad = fc.count > n_wait_args      # the wait's own arguments (the waits list, wait_kind, ask_by, the mover) are refused: the park's reason, which reads what they would have stored, is not judged
    model_drop |= list_drop
    list_set = list_plan is not None and list_plan.kind == "list"
    if list_set:                                 # a wait on a list: the lines, the mode, and the kind; a single wait the list replaces leaves nothing of its own behind
        model_set["wait_kind"], model_set["wait_mode"] = "list", list_plan.mode
        meta["waits"] = [dict(ln) for ln in list_plan.lines]
        model_drop |= {"wait_anchor", "wait_event"}
        if _watch.stored_kind(item_was.get("metadata") or {}) == "item":
            meta.pop("after", None)              # the wait on the item's close was the single wait this list replaces
        for k_ in ("hold", "hold_set", "wait_basis"):
            meta.pop(k_, None)
    clear_obs = observers is not None and (observers == [] or (isinstance(observers, str) and observers.strip().lower() in h.ask_none))
    if clear_obs:
        meta.pop("observers", None)
    elif observers is not None and (observers if isinstance(observers, list) else observers.strip()):
        if (got_obs := fc.call(_gates.gate_observers, observers)) is not None:
            meta["observers"] = got_obs
    # after=[] and after="none" clear it, and so does clear_after=true: a client (claude.ai's connector, found once) drops
    # an empty list before it reaches the server, so the flag is the form that survives it, like clear_needs and clear_due
    after_bad = False                         # the after list is refused: what reads it as stored is not judged
    clear_after = clear_after or (after is not None and (after == [] or (isinstance(after, str) and after.strip().lower() in h.ask_none)))
    after_set = after is not None and not clear_after and bool(after if isinstance(after, list) else after.strip())
    if clear_after and after is not None and (after if isinstance(after, list) else str(after).strip()) and not (isinstance(after, str) and after.strip().lower() in h.ask_none):
        fc.add("Refused: clear_after drops the after list; it does not go with a new one")
    if clear_after:
        meta.pop("after", None)
        if _uw.kind_of(meta) == "item" and not wait_kind.strip() and not clear_wait and was_until and _uw.date_of(meta):
            meta.pop("wait_kind", None)                  # the wait on the item ended with its link; the date it carried stays as a wait on the date alone
        h.wait_end_sent_back(meta, (_we.ITEM,))          # a wait the server set from the line's words, sent back: the server leaves that line alone
    elif after_set:
        if (got_after := fc.call(_gates.gate_after, after, gid)) is not None:
            meta["after"] = got_after
        else:
            after_bad = True
    if _wl.stored(item_was.get("metadata") or {}) and list_plan is None and (wait_kind.strip() or wait_anchor.strip() or wait_event.strip() or after_set):
        model_drop |= {"waits", "wait_mode"}     # a single wait written over a stored list replaces it, as a new list replaces a single wait: the lines and the mode go (what has arrived on them with them)
        if "wait_kind" not in model_set and "wait_kind" not in model_drop:
            meta.pop("wait_kind", None)          # …and so does its kind, list (popped here, not dropped as a clear of the wait is: the backstop day stays beside the new wait)
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
    debtor = h.session_id(sender or owner or _telling.holder(item))     # the writer owes the page; without a sender, the item's mover is the writer by rule
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
            fc.add(f"Refused: {e}")
        if work_spec is not None:
            if work_spec.get("cut"):
                _calls.fixed("work-cut", f"the status line was {work_spec['cut']} characters and the limit is {_work.TEXT_MAX}: it was cut at the last word that fits and ends with an ellipsis, as \"{work_spec['text']}\"; to change it, send a shorter one",
                             fields=["work"], stored=work_spec["text"], sent=str(work))
            work_spec["text"] = _shown_ids(work_spec.get("text") or "")   # g7 → board#N, after the length check
            work_writer = _session_label(h.session_id(sender.strip() or own_for))   # the writer by name; the session whose step it is, unless the spec names another
            fc.call(_gates.gate_work_writer, gid, work_writer, _telling.holder({"status": "open", "metadata": meta}), meta, finishing)                      # the needs list as this call leaves it
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
                        fc.add(f"Refused: work: {work_who} has no open step on {_gh.shown(gid)}, so the status needs its text: it makes the step. {_work.FORM}")
                    else:
                        work_made = f"{work_who}: {work_spec['text']}"
                        kept_own = _nl.text_of(meta, next_writer, keeper_was, _handoff.ho_same)                     # the sender's lines stay: next replaces them as a whole
                        next = (next.rstrip() + "\n" if next.strip() else (kept_own.rstrip() + "\n" if kept_own.strip() else "")) + work_made
                        next_touch = True
    n_said = fc.count
    said_l = fc.call(_gates.gate_said, said, sender.strip() or own_for, debtor, default=[])   # the trailers: his words checked against the transcript; a failed check refuses the write
    said_bad = fc.count > n_said          # the words of his that later checks read are not known: they are skipped, not judged on an empty list
    clear_tell = tell_him is not None and (tell_him == [] or (isinstance(tell_him, str) and tell_him.strip().lower() in h.ask_none))
    if clear_tell:
        meta.pop("tell_him", None)      # taking the ask back needs no words of his
    elif tell_him is not None and (tell_him if isinstance(tell_him, list) else tell_him.strip()):
        if said_bad:
            fc.skip("tell_him", "it is recorded only with his words in said, and said is refused")
        elif (got_tell := fc.call(_gates.gate_tell_him, tell_him, said_l)) is not None:
            meta["tell_him"] = got_tell      # his ask to a front agent, recorded only with his own words in this write
    reformat = bool(description) and bool(_writes.reformat())   # a re-bullet changes the form of the description, never what it says: the state clock and the confirm stay, no page is owed
    rewording = _steps.reword_given(reword)      # reword={position: new text}: an open step's words change; an empty mapping ({} or "{}") is not given
    marks = _fg._marks_given(done) or _fg._marks_given(dropped) or rewording or work_tick >= 0      # a step checked, dropped or reworded is a change of next; so is the step a status done ticks
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
            fc.add(f"Refused: a close takes the end state as outcome_text and never changes the description; this call passes both. Pass the end state as outcome_text alone; "
                   f"to change what {gid} is about, update its description before or after the close.")
            description = ""            # (judged as the close's outcome_text below, not as a description too)
        else:
            outcome_text, description = description.strip(), ""
    if closing:                   # a close says how the item ended
        outcome_text, ot_note = _fg.fix_long_bullets(outcome_text, None, "outcome_text")       # a bullet over the limit is split like a description's (a pure form fix; the reply says so, and History)
        if ot_note:
            _stall.note(meta, time.time(), ot_note)
        read_superseded = not outcome and bool(superseded_by)      # a replacing item names the outcome: superseded_by goes with no other (an outcome of done or dropped beside it is still refused)
        if read_superseded:
            outcome = "superseded"
        superseded_by = fc.call(_gates.gate_close, gid, item, outcome, reason, superseded_by, outcome_text, default="")
        if read_superseded and superseded_by:      # told only when the close passed its gate, with the item it read (a typo that is a real item would otherwise go unseen) and how to undo it
            _calls.fixed("outcome-superseded", f"no outcome was given, so {_gh.shown(gid)} closed as superseded by {_gh.shown(superseded_by)}; to undo: reopen with status=open and a next line, then close again with the outcome you mean")
    elif outcome or reason or superseded_by or outcome_text:
        fc.add(f"Refused: outcome, outcome_text, reason and superseded_by go with a close (status=completed on an open item, or the complete tool)"
               + (f"; {gid} is already completed: to correct its close, reopen it (status=open with a next) and close it again"
                  if was == "completed" else ""))
    if reopening and not next.strip():
        fc.add(f"Refused: reopening {gid} needs a new next: the step that comes now")
    if draft_set and (status or item.get("status")) == "completed":
        fc.add("Refused: a completed item keeps no draft (a close drops it); draft goes with an open item")
    owing = h.owing_note(debtor) if state_change else ""      # a write is never refused or held for a page debt: the reply says the write went through and the page is still owed (read here, before this write records its own debt)
    desc_sent = description      # as the call passed it, before the server's own form fixes (the Goal note compares it)
    description = _fg.fix_bare_urls(description, str(item_was.get("description") or ""), session=_writes.session_next())       # a bare address in a description becomes a link to itself (the reply says so); next and ask keep the refusal
    for f_ in _fg.bare_url_faults({"description": description, "next": next, "ask": ask}, {"description": item_was.get("description"), "next": meta.get("next"), "ask": ask_was}, session=_writes.session_next()):   # only the fields this call sets; a stored bare URL is no reason to refuse
        fc.add(f_, text=True)
    if subject:
        subject = _fg.fix_long_subject(subject, str(item.get("subject") or ""))       # a subject over the limit is cut at its last word that fits (the reply says so)
        for f_ in _fg.subject_faults(subject, str(item.get("subject") or "")):
            fc.add(f_, text=True)
        item["subject"] = subject
    if description:
        if (_writes.session_next() and not reformat and not sender.strip().startswith("a script on ") and description.strip() != str(item_was.get("description") or "").strip()):     # the text the goal gate judges below
            description = _fg.fix_goal_label(description, str(item_was.get("description") or ""))       # a goal word in another form opening the first bullet is written `Goal:` (a pure form fix; the reply says so)
        description, split_note = _fg.fix_long_bullets(description, str(item_was.get("description") or ""))       # a bullet over the limit is split at its sentences (a pure form fix; the reply says so, and History)
        if split_note:
            _stall.note(meta, time.time(), split_note)
        form_f = _fg.description_faults(description)
        for f_ in form_f:
            fc.add(f_, text=True)
        if (_writes.session_next() and not reformat and not sender.strip().startswith("a script on ")
                and description.strip() != str(item_was.get("description") or "").strip()):     # a replacement of the text by a session, not the stored text sent back
            if form_f:
                fc.skip("the check that the description opens with its goal", "it reads the first bullet, which the faults of the description's form above leave unread")
            elif f_ := _fg.goal_fault(description):
                fc.add(f_, text=True)
        item["description"] = description
    open_keys = {_steps.key(s["text"]) for s in _steps.view(item_was.get("metadata"), keeper=keeper_was) if s["status"] == _steps.OPEN} if (was != "completed" or reopening) else set()      # the open steps as the item stood
    was_meta = item_was.get("metadata") or {}
    group = {k for k in was_meta.get("step_lines") or [] if isinstance(k, str)} if str(was_meta.get("step") or "").strip() else set()      # the keys of the lines the stored step was split into: they belong to it only while it is stored
    step_same = bool(group) and not step_lines and bool(state_given.get("step")) and _states.clean(state_given.get("step")) == _states.clean(was_meta.get("step"))      # the stored summary sent again: not a new step, so nothing of its split goes
    gone_keys = (open_keys & group) - {_steps.key(x) for x in step_lines} if group and not closing and not step_same and (step_withdrawn or state_given.get("step")) else set()      # the step is replaced (by a long or a short one) or withdrawn: the open lines of its old split go with it (a done one stays)
    step_kept = step_same and not clear_next      # clear_next wipes every line of next, so the record of the split goes and nothing is said to be unchanged
    if step_kept and not closing:
        _calls.fixed("step-split", "the step is the one the item holds already: the lines of next it was split into stay as they are, nothing was changed", fields=["step"])
    if gone_keys and next.strip():      # a next sent back whole still lists the old split's lines: they leave with the step, so the call is not refused over them
        next = "\n".join(e for e in _steps.split(next) if _steps.key(e) not in gone_keys)
    if step_lines and not closing:      # the actions of a long step: lines of next that open with his name, at the end of the sender's own lines (the summary is the step)
        own_text = "\n".join(e for e in _steps.split(_nl.text_of(meta, next_writer, keeper_was, _handoff.ho_same)) if _steps.key(e) not in gone_keys)      # …and none of the old split's lines the write drops
        settled = {_steps.key(x["text"]) for x in _steps.view(item_was.get("metadata"), keeper=keeper_was) if x["status"] != _steps.OPEN} & group if {_steps.key(x) for x in step_lines} == group else set()      # the same long step sent again: an action of it that was ticked done or dropped stays so, it is not made open again (another step that holds the same words opens every one of its actions)
        have = (set() if clear_next else open_keys) | settled | {_steps.key(x) for x in _steps.split(next)}      # clear_next wipes every open line, so none counts as there already
        added = _with_lines(next, own_text, step_lines, have, next_drop or clear_next)
        _fg.say_long_step(step_long, step_lines, sum(1 for ln in step_lines if _steps.key(ln) not in have), sum(1 for ln in step_lines if _steps.key(ln) in settled))
        if added != next:
            next, next_drop, next_touch = added, False, True
            _stall.note(meta, time.time(), f"step: split by the server into a summary and {len(step_lines)} lines of next")
    if next.strip() and _writes.session_next() and not closing:      # a line of his that runs long with several actions: one line per action (the reply says so)
        next = _fg.fix_long_owner_lines(next, open_keys)
    if next:
        for f_ in _fg.next_faults(next, has_ask=bool(ask.strip()) and ask.strip().lower() not in h.ask_none, session=_writes.session_next()):
            fc.add(f_, text=True)
    steps_on = was != "completed" or reopening         # a closed item's checklist is its record: no write touches it until the item is reopened
    if marks and not steps_on:
        fc.add(f"Refused: {_gh.shown(gid)} is closed and its checklist is the record of what was done; reopen it (status=open with a next) before marking or rewording a step")
    if rewording and (closing or clear_next):
        fc.add("Refused: reword changes the words of a step that stays open; " + ("a close settles the open steps itself, so reword goes with a call that keeps the item open" if closing else "clear_next=true wipes every line, so reword goes with a call that keeps them"))
    steps_old = _steps.view(item_was.get("metadata"), keeper=keeper_was) if steps_on else []          # the checklist as it stood: the stored steps lined up with the lines of next, each open one with its writer
    steps_before = list(steps_old)          # …as the write found it: a reword below replaces entries of steps_old, and the front-agent step check judges the new words against these
    steps_by = _session_label(debtor) or debtor or "unknown"
    done_ix: list[int] = []
    drop_ix: list[int] = []
    reword_ix: dict[int, str] = {}
    marks_bad = False
    try:
        done_ix, drop_ix = _steps.resolve(steps_old, done, "done"), _steps.resolve(steps_old, dropped, "dropped")
        reword_ix = _steps.resolve_reword(steps_old, reword) if rewording else {}
        if work_tick >= 0 and work_tick not in done_ix and work_tick not in drop_ix:
            done_ix.append(work_tick)
        if both := sorted(set(reword_ix) & {*done_ix, *drop_ix}):
            raise _steps.StepError(f"step {both[0] + 1} is in reword and in done or dropped ({_steps.first_line(steps_old[both[0]]['text'])[:90]}); pick one")
    except _steps.StepError as e:
        if steps_on or not marks:      # on a closed item the checklist is not read at all (no steps above), and the refusal above already says that: its marks are not refused a second time for finding no step
            fc.add(f"Refused: {e}")
        done_ix, drop_ix, reword_ix, marks_bad = [], [], {}, True      # the marks of this call cannot be read: what depends on them is judged once they can
    if closing and steps_old and not marks_bad and (_writes.session_next() or _writes.close_tool()):      # a session's close ticks its own steps only: another session's open step is never settled by it
        fc.call(_gates.gate_close_steps, gid, steps_old, _steps.others_open(steps_old, lambda w: not w or _handoff.ho_same(w, next_writer), {*done_ix, *drop_ix}, lambda nm: _handoff.ho_same(nm, next_writer)))
    elif closing and steps_old and marks_bad and (_writes.session_next() or _writes.close_tool()):
        fc.skip("the check that a close leaves no other session's step open", "it reads the steps this call marks, which are refused above")
    if gone_keys and steps_on and not marks_bad:
        gone = [i for i, s_ in enumerate(steps_old) if s_["status"] == _steps.OPEN and _steps.key(s_["text"]) in gone_keys and i not in drop_ix and i not in done_ix]
        drop_ix.extend(gone)
        if gone:
            marks = state_change = True      # the lines leave next with their writers, as a dropped=[n] of the same lines would
            _calls.fixed("step-split-dropped", f"the {len(gone)} open line{'' if len(gone) == 1 else 's'} of next that the old step was split into {'was' if len(gone) == 1 else 'were'} dropped with it ({'withdrawn' if step_withdrawn else 'replaced'})", fields=["step"])
    if (step_withdrawn or state_given.get("step")) and not step_kept:
        if step_lines:
            meta["step_lines"] = [_steps.key(x) for x in step_lines]      # the lines this step was split into: replaced or withdrawn with it
        else:
            meta.pop("step_lines", None)
    if step_lines and steps_on and not closing and not marks_bad:      # the long step sent as a line of his already (a session wrote `<owner>: <the step>` before): its actions replace it, so it is dropped, never left open beside them
        long_k, rec_was = _steps.key(_hs.line_of(step_long, meta)), _hs.recorded(item_was.get("metadata") or {})
        for i, s_ in enumerate(steps_old):
            if s_["status"] == _steps.OPEN and _steps.key(s_["text"]) == long_k and not (rec_was and _hs.same_line(s_["text"], rec_was)) and i not in drop_ix and i not in done_ix:      # the server's own line for the old step is made again from the new step on every save
                drop_ix.append(i)
                marks = state_change = True
                _calls.fixed("step-split-dropped", f"step {i + 1} ({OWNER}'s line with the whole long step) was dropped: its {len(step_lines)} actions are lines of next now", fields=["step"])
    reword_note = ""
    bad_rw: set[int] = set()       # the steps whose new words are refused: they are not applied below
    his_rw: dict[int, str] = {}    # the steps of his this call rewords: done as drop plus add below, never in place
    if reword_ix:                 # the step keeps its number, its place and its open state; its text (and its line of next, its proof) become the new words before anything below lines the checklist up with next
        for i, text in reword_ix.items():
            w = str(steps_old[i].get("writer") or "")
            if _steps.is_his(steps_old[i]["text"], unnamed_is_his=False):
                if _hs.recorded(meta) and _hs.same_line(steps_old[i]["text"], _hs.recorded(meta)):      # the line the server keeps from the ask or the step: it is made again from them on every save, so new words go there
                    fc.add(f"Refused: reword: step {i + 1} is {OWNER}'s own step, which the server keeps from the item's ask or step and ticks by his answer; give it other words by changing that field "
                           "(step=<the new words> for a step of his, ask=<the new ask> for a decision) and the step follows")
                    bad_rw.add(i)
                else:                      # any other line of his, whoever wrote it: dropped, and the new words added as a new step (what done=/dropped= and a line of next do, as one reword)
                    his_rw[i] = text
                continue
            if w and not _handoff.ho_same(w, next_writer):
                fc.add(f"Refused: reword: step {i + 1} is a line of {_session_label(w) or w}, not of this write's sender; only the session that wrote a step rewords it (ask it, or mark the step done or dropped)")
                bad_rw.add(i)
                continue
            if _writes.session_next() and _nr.grows(_steps.first_line(steps_old[i]["text"]), _steps.first_line(text)):       # N3 holds for a reword as for a rewritten line: the old text plus added words is progress, which goes on the page
                fc.add(f"Refused: reword: the new text of step {i + 1} is its old text with words added (\"{_clip_line(_steps.first_line(text), 90)}\"): a step is never rewritten to add progress, so progress, results and what was tried go on the project page "
                       f"(Current state or a timeline line). Reword the step to a different action, or mark it dropped=[{i + 1}] and write the longer one as a new line of next")
                bad_rw.add(i)
                continue
            if got_ := _fg.next_faults(text, has_ask=True, session=_writes.session_next()):
                bad_rw.add(i)
                for f_ in got_:
                    fc.add(f_)
        for f_ in _fg.bare_url_faults({"next": "\n".join(reword_ix.values())}, {"next": "\n".join(steps_old[i]["text"] for i in reword_ix)}, session=_writes.session_next()):
            fc.add(f_)
        for i in bad_rw:
            reword_ix.pop(i, None)
        his_added: list[str] = []
        for i, text in his_rw.items():      # the old step is dropped by this write (its History line says so) and the new words are a step at the end of the sender's lines; the front-agent check reads them as any new step
            reword_ix.pop(i, None)
            new_lines = _fg.fix_long_owner_lines(text, open_keys) if _writes.session_next() else text
            if got_ := _fg.next_faults(new_lines, has_ask=True, session=_writes.session_next()):
                for f_ in got_:
                    fc.add(f_)
                continue
            drop_ix.append(i)
            his_added.extend(_steps.split(new_lines))
            _calls.fixed("step-reworded", f"the reword of {OWNER}'s step {i + 1} was done as drop plus add: the old step is dropped and shows as dropped, and the new words are a new step at the end "
                         f"(\"{_clip_line(_steps.first_line(steps_old[i]['text']), 70)}\" → \"{_clip_line(_steps.first_line(new_lines), 70)}\")", fields=["reword"])
        if his_added:
            gone_k = {_steps.key(steps_old[i]["text"]) for i in drop_ix}
            own_kept = "\n".join(e for e in _steps.split(_nl.text_of(meta, next_writer, keeper_was, _handoff.ho_same)) if _steps.key(e) not in gone_k)
            next = _with_lines(next, own_kept, his_added, (open_keys - gone_k) | {_steps.key(x) for x in _steps.split(next)}, next_drop or clear_next)
            next_drop = False
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
        dry_ok = fc.call(h.next_put, dry_meta, next, next_writer, keeper_was, wipe=clear_next, drop_own=next_drop, default=None) is not None      # a dry run: a refusal comes before anything is written or told
        if dry_ok and steps_on and not closing and not clear_next and _fg._require_marks():       # an open step of the writer's that next leaves out with no word on it stays open: its line is carried over unchanged, and the reply says so
            left_ix, grown = _left_out(dry_meta, steps_old, done_ix, drop_ix, reword_ix, keeper_was)
            if left_ix and grown and _writes.session_next():      # a line rewritten with words added is refused below as ever (N3), not carried over beside its longer twin
                left_ix = []
            if left_ix:
                one = len(left_ix) == 1
                _calls.fixed("step-kept", f"next no longer listed {'an open step' if one else 'open steps'} of yours and the call did not say what became of {'it' if one else 'them'}, so {'it stays' if one else 'they stay'} open as written: "
                             + "; ".join(f"{i + 1}. {_clip_line(_steps.first_line(steps_old[i]['text']), 90)}" for i in left_ix)
                             + f". Mark {'it' if one else 'each'} with done=[n] or dropped=[n] when it is finished or no longer wanted, or give it new words with reword={{n: \"new words\"}}")
                next, next_drop = _steps.carry(next, steps_old, left_ix), False
                dry_meta = json.loads(json.dumps(meta))
                fc.call(h.next_put, dry_meta, next, next_writer, keeper_was, wipe=clear_next, drop_own=next_drop)
        next_after = dry_meta.get("next")
    if status:
        if status == "on_hold":   # a retired status: on hold is a property of an open item
            fc.add("Refused: status must be open | completed; parked is a property of an open item: until=<date> with wait_kind=\"time\" and wait_basis (a park of the wait cap's days or less needs his recorded words); clear_hold=true releases it")
        elif status not in ("open", "completed"):
            fc.add("Refused: status must be open | completed")
        else:
            item["status"] = status
    if clear_hold and (hold or (wake and not (_wlw.passed(waits) and not _wlw.clearing(waits)))):      # (an until beside a list is the list's backstop day, no wake: the list's own refusal says the clear_hold, once)
        fc.add("Refused: clear_hold releases the item and drops its wake; it does not go with hold or wake")
    if hold and item.get("status") == "completed":
        fc.add("Refused: a completed item cannot be parked; set it open first")
    elif wake and item.get("status") == "completed" and not (_wlw.passed(waits) and not _wlw.clearing(waits)):      # (a park with its wake is one mistake, said by the park; a list beside its until on a closed item is one, said by the list)
        fc.add("Refused: a completed item takes no wake; set it open first")
    if recycle and clear_recycle:
        fc.add("Refused: recycle and clear_recycle do not go together")
    if recycle and item.get("status") == "completed":
        fc.add("Refused: a completed item does not wait for a recycle; set it open first")
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
    if str(wait_basis or "").strip() and not (clear_wait_basis or clear_wake or clear_hold) and " ".join(str(wait_basis).split()).lower() not in h.ask_none:      # a basis for a wake within the cap needs none: dropped here, before the date-only park below reads it, so the wake is parked as a wake sent alone is; the server says so and does not refuse
        try:
            e_item, e_wake, e_held = _basis_frame(item, meta, status, wake, ask_by, wait_kind, hold, state_st)
            e_days = _gates.basis_unneeded(e_item, e_wake, e_held)
        except ToolError:
            e_days = None      # a wake in no valid form: the wake check below refuses it with its own message
        if e_days is not None:
            _calls.fixed("wait-basis-dropped", f"wait_basis was dropped: the wake ({e_wake}) is {e_days:.0f} days out, within the {_wt.cap_days():g} days a wait may run, so the wake needs no basis; the wake is set as sent")
            wait_basis = ""
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
    basis_day = ""                # a relay or event wait keeps its date in ask_by, not in a wake: its basis stands for that day
    if not wake and not meta.get("wake") and (wait_kind.strip().lower() or _uw.kind_of(meta)) in ("relay", "event"):
        basis_day = _uw._dated(ask_by) or _uw._dated(meta.get("ask_by"))
    basis_bad = False             # the wait_basis is refused: the cap check, which a good basis lifts, cannot be judged
    if basis_txt:                 # a wake past the cap that stands on a real-world date: checked before the wake gate reads it
        n_basis = fc.count
        if clear_wait_basis:
            fc.add("Refused: clear_wait_basis drops the basis; it does not go with a new one")
        elif clear_wake or clear_hold:
            fc.add("Refused: wait_basis goes with a wake; this call drops the wake")
        elif (b_frame := fc.call(_basis_frame, item, meta, status, wake, ask_by, wait_kind, hold, state_st)) is not None:
            basis_ok = fc.call(_gates.gate_wait_basis, b_frame[0], basis_txt, b_frame[1], held=b_frame[2], default="")
        basis_bad = fc.count > n_basis
    wake_bad = False              # the wake is refused: what reads the wake as stored (the park's reason, the hand-off's date) is not judged
    if wake:                      # a moment to come
        stored = fc.call(h.parse_wake, wake, default="")
        if not stored:
            wake_bad = True
        elif h.wake_at(stored) <= _pages.zone_now():      # for a date-only wake the same as "after today"
            fc.add(f"Refused: wake must be in the future ({_cfg.tz_abbr()})")
            wake_bad = True
        else:
            words = fc.call_depending("the cap on how far out a wake may be", "it reads his words in said and the wait_basis, one of which is refused above", said_bad or basis_bad,
                                      _gates.gate_cap, item, said_l, "wake", stored, h.wake_at(stored).timestamp(), basis_ok, default="")    # The owner's one rule: no wait runs past the cap without his words
            meta["wake"] = stored
            if words and words != h.basis_words:   # recorded for this wake: the cap is lifted for it, with his sentence (the reason a time wait carries)
                _, q_text, q_src = h.owner_quote_on(item, said_l, _wt.cap_days())
                h.cap_ok_put(meta, "wake", stored, words, quote=q_text, source=q_src)
            else:                     # (a real-world date is its own record, wait_basis, below)
                h.cap_ok_drop(meta, "wake")
    relay_hold = False
    if hold and not (clear_hold or clear_wake or clear_wait) and (wait_kind.strip().lower() or _uw.kind_of(meta)) in ("relay", "event") and (_uw._dated(ask_by) or _uw._dated(meta.get("ask_by"))) and not meta.get("wake"):
        hold, relay_hold = False, True      # a relay or event wait is itself the park until its ask-by day (the date this call gave as wake or ask_by went there): no second wait, the hold flag is not stored
        if _uw._dated(ask_by):               # the date went to ask_by, which the wake cap above never sees: the cap judges it here as it judges a hold's wake (his words lift it the same way)
            rd = fc.call(h.parse_wake, _uw._dated(ask_by), default="")
            rwords = fc.call_depending("the cap on how far out a wake may be", "it reads his words in said and the wait_basis, one of which is refused above", said_bad or basis_bad,
                                       _gates.gate_cap, item, said_l, "wake", rd, h.wake_at(rd).timestamp(), basis_ok, default="") if rd else ""
            if rwords and rwords != h.basis_words:
                _, rq_text, rq_src = h.owner_quote_on(item, said_l, _wt.cap_days())
                h.cap_ok_put(meta, "wake", rd, rwords, quote=rq_text, source=rq_src)
    if hold:
        meta["hold"] = True
        if not (was_held and h.render_hold_at(item)):   # who set it and when: the unexplained-holds report and the briefings read it; a hold already held keeps its stamp
            h.hold_set(meta, _session_label(debtor) or debtor or "unknown")
    time_kind = _watch.stored_kind(meta) == "time"       # read before the dates go: a stored until with no kind reads as a time wait only while the until stands
    if clear_wake:                # the wake goes; a hold stays only while something else holds it (the item rule below)
        meta.pop("wake", None); h.cap_ok_drop(meta, "wake")
        if _watch.stored_kind(meta) != "relay":      # a relay's until is its ask-by day, which clear_wake never dropped
            meta.pop("until", None)
    relay_clear_hold = bool(clear_hold) and _uw.kind_of(meta) in ("relay", "event") and not meta.get("hold")      # clear_hold on a relay or event wait that holds no flag changes nothing: the reply says what ends the wait
    if clear_hold:                # released now: the hold and its wake go together
        if meta.get("wake") and _sf.marked(meta, _sf.WAKE_PARK, str(meta["wake"])):      # the server parked this wake and the mover sends it back: the server leaves that wake alone from here
            _sf.unmark(meta, _sf.WAKE_PARK, str(meta["wake"])); _sf.decline(meta, _sf.WAKE_PARK, str(meta["wake"]))
        if meta.pop("hold", None) or (was_until and _uw.kind_of(meta) in ("", "time")):      # a hold, or a wait on the date alone (stored as until, with no hold of its own to drop)
            meta.pop("wake", None); meta.pop("until", None); h.cap_ok_drop(meta, "wake")
            if time_kind or (was_until and _uw.kind_of(meta) in ("", "time")):      # the time wait the hold stood on (a park with a then stores one) goes with it: wait_kind, the old picker key and the watcher's stamps
                for k in (*_model.WAIT_GROUP, _model.LEGACY_PICKER_KEY, "chases", "watch"):
                    meta.pop(k, None)
        meta.pop("hold_set", None)
    if item.get("status") == "completed":   # completed: nothing is held or due any more
        meta.pop("hold", None); meta.pop("wake", None); meta.pop("until", None); meta.pop("hold_set", None); meta.pop("cap_ok", None)
    if basis_ok:                  # the basis is bound to the wake it was given for; a different wake, no wake or a closed item drops it
        h.basis_put(meta, basis_ok, str(meta.get("wake") or basis_day), _session_label(debtor) or debtor or "unknown")
    elif clear_wait_basis or (isinstance(meta.get("wait_basis"), dict) and meta["wait_basis"].get("wake") != _wt.wake_value(meta)):      # the basis stands for the date the wait ends on: the stored until, else the wake
        meta.pop("wait_basis", None)
    if h.model_guards_on() and meta.get("hold") and meta.get("wake") and (hold or wake) and not basis_ok and not _wt.basis_of(meta) and not str(_wt.words_of(meta).get("quote") or "").strip():
        q_why, q_text, q_src = h.owner_quote_on(item, said_l, _wt.cap_days())     # a hold with a wake is a time wait, which carries his words: record them, within the cap too
        if q_why and q_text:
            h.cap_ok_put(meta, "wake", str(meta["wake"]), q_why, quote=q_text, source=q_src)
    hold_pre = bool(meta.get("hold"))     # the hold as this write leaves it, before the old rule below drops it beside a decision (the model guards refuse that pair instead)
    dropped_hold = item.get("status") == "open" and bool(meta.get("hold")) and _waits_decision(meta)
    if dropped_hold:              # an item waiting on the owner's call is never on hold: any write drops a stored flag (its date stays)
        meta.pop("hold", None); meta.pop("hold_set", None)
        h.state_end(meta, "parked")    # the park it stood in is gone with the hold (needs is not something parked stands on: the hold would only be stripped again)
    # A hold names what it waits for, a wake, open after
    # items or a pane recycle; an anchor scoped to the item is a condition too, but one that still carries a backstop wake (the notice may never
    # come). Checked when the call touches the hold, its wake, its after or its recycle, so a park stored before the rule is read as it is.
    if meta.get("hold") and not meta.get("wake") and (hold or clear_wake or after_set or clear_after or clear_recycle) and not h.after_open(meta) and not meta.get("recycle") and (wake_bad or after_bad or wait_args_bad or basis_bad):
        fc.skip("the check that a park names what it waits for", "it reads the wake, the after list, the wait's arguments or the wait_basis, which are refused above")
    elif meta.get("hold") and not meta.get("wake") and (hold or clear_wake or after_set or clear_after or clear_recycle) and not h.after_open(meta) and not meta.get("recycle"):
        if h.scoped_anchors(str(meta.get("project") or ""), gid):
            fc.add(f"Refused: a park that waits on a notice from the anchor scoped to {gid} still carries a backstop date, at most {_wt.cap_days():g} "
                   f"days out unless {OWNER}'s words are on the item (until=YYYY-MM-DD): the notice may never come")
        else:
            fc.add("Refused: a park names what it waits for; an unconditional or indefinite park is refused. Give it a date (until=YYYY-MM-DD or "
                        f"YYYY-MM-DDTHH:MM with wait_kind=\"time\": the date {OWNER} gave, the date the outside party or event it waits on is due, or the end of a window the work itself needs, with wait_basis=\"<what the window collects> ends <YYYY-MM-DD>\"; a park of {_wt.cap_days():g} days or less needs {OWNER}'s recorded words), the items that must close first (`after=[\"board#N\"]`), "
                        f"a notice from an anchor scoped to it (`anchors(project, add=[url], items=[\"{_gh.shown(gid)}\"])`, with a backstop date at most {_wt.cap_days():g} "
                        f"days out), or a pane recycle (recycle=true). An item waiting on {OWNER}'s call is parked with needs=[<session>] and mover={OWNER} (his ask returns at the date); "
                        "to put it on his move instead, needs=decision with its ask, or after=[<the item that carries the ask>], which releases it when that item closes. To check back on work you keep moving while the "
                        "item stays active, set no date: a date with no park is a wait until it (outside a hand-off)")
    # The done check: set or cleared by this write (a filing edit: no page owed), then the hand-off gate: a write
    # that hands the item to another session (a `<session>: <action>` line of next) leaves it with a check or a wake
    chk = " ".join(str(check or "").split())
    chk_new = bool(chk) and chk.lower() not in h.ask_none
    clear_check = clear_check or chk.lower() in h.ask_none      # check="none" or clear_check=true removes it, like needs, due and wake (an older tool list may lack clear_check); check="" is "not passed", as needs="" is
    check_bad = False
    if chk_new:                                                # a new check beside clear_check replaces the old one, as a new needs beside clear_needs does
        if (got_check := fc.call(_checks.parse_check, chk, gid)) is not None:
            meta["check"] = got_check
        else:
            check_bad = True
    elif clear_check:
        meta.pop("check", None)
    handed: list[str] = []
    if item.get("status") == "open" and not closing:
        handed = _handoff_to(item.get("metadata") or {}, meta, next, sender.strip() or own_for)
        if handed and not meta.get("check") and not meta.get("wake") and not _telling.front_sender(sender) and (wake_bad or check_bad):
            fc.skip("the check that a hand-off carries a check or a date", "it reads the wake or the check of this call, which is refused above")
        elif handed and not meta.get("check") and not meta.get("wake") and not _telling.front_sender(sender):     # a front agent's hand-off asks for neither: the mover's close lands the result, and its own wake or check is refused below
            fc.add(f"Refused: this update hands {_gh.shown(gid)} to {', '.join(handed)} (a line of next in the form `<session>: <action>`) and nothing "
                            f"would close the item once that work is done. Add check=<what closes it> ({_checks.CHECK_HOW}): the server then closes it when the check passes, no session turn spent. "
                            f"Only when no check fits, add a date, until=YYYY-MM-DD (or YYYY-MM-DDTHH:MM, {_cfg.tz_abbr()}), as the backstop of this hand-off: because the write hands the item on, the date is no wait, the item stays active in the new mover's lane and the hand-off is recorded (the same date with no hand-off is a wait, and the item waits until then). "
                            "(A front agent's hand-off is not asked for either: its mover's close or hand-back lands the result through stackshot.) "
                            "Pass the same update again with the check, or with the date alone if none fits. "
                            "If this tool shows no check parameter, this session's cached tool list predates it: pass the date, or call the update through the "
                            "MCP Portal's Code Mode (portal_codemode_execute with codemode.stackshot_update({item_id, sender, next, check})), which reads the live schema.")
    if anchors is not None:
        fc.add("Refused: anchors belong to the project, not the item — use anchors(project=<its project>, add=[url…], items=[<this id>]) or remove=[url…]")
    if fc.state_bad:         # the checkpoint: a fault that leaves the stored state open (a wake, a needs, a mover, a wait that does not parse) ends the form's checks here; the ones below read the item as the call would store it
        fc.skip("the checks of the item as this call would store it (its mover, the wait's reason and end, the decision, the steps, the hand-off)", "they read what the faults above leave open")
        fc.raise_now()
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
        if steps_old:             # a close marks the steps still open (a session's close has refused above while another session's is one), by the closer: done when the outcome is done, dropped otherwise; a mark passed with the close counts first
            try:
                meta["steps"] = _steps.stored(_steps.mark_open(_steps.apply(steps_old, None, done_ix, drop_ix, steps_by, time.time()), outcome, steps_by, time.time()))
            except _steps.StepError as e:
                fc.add(f"Refused: {e}")
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
    work_note = ""
    if said_l:                    # appended, never replaced: every entry keeps its position (the anchor the issue's trailer links)
        meta["said"] = [*(meta.get("said") if isinstance(meta.get("said"), list) else []), *said_l]
        work_note += h.said_note(said_l)
    if clear_draft:                                                            # the draft: a filing edit like the ask (no clock moves, no page is owed)
        meta.pop("draft", None)
    elif draft_set:
        meta["draft"] = draft_set
    alias_note = ""
    alias_picker = False      # the `mover` this write sets came from post_wake_mover: it names who picks the item up when its wait ends, so it is no hand-over
    pw_given = post_wake_mover.strip()
    if pw_given and item.get("status") == "open":      # post_wake_mover is the old name of mover (model.fold_picker_alias): the value is the picker of a wait, else dropped with a note
        trial = dict(meta)      # the item as this write leaves it, without the alias: whether it waits is judged by the same readings the write itself uses below
        h.model_apply(trial, "open", {k: v for k, v in model_set.items() if k != _model.LEGACY_PICKER_KEY}, {k for k in model_drop if k != _model.LEGACY_PICKER_KEY})
        if (needs_set or agent.strip()) and "mover" not in model_set and "mover" not in model_drop and _old_holder_goes(trial):
            trial.pop("mover", None)
        if "wait_kind" in model_drop and was_until and not (wake or hold):      # clear_wait drops the stored until and the working fields it stood as (below)
            for k_ in _uw.LEGACY_FIELDS:
                trial.pop(k_, None)
        waits_after = _model.waits_stored(trial) or bool(until_wait) or bool(was_until and (trial.get("wake") or trial.get("ask_by")))
        if waits_after and not _model.waits_stored(trial) and _uw.date_of(trial) and _wait_is_bare(trial) and _hands_on(gid, item_was, {**item, "metadata": trial}, handed, sender.strip() or debtor or ""):
            waits_after = False      # a bare date beside a hand-off in this write is its backstop, and the item stays alive (the judgement of the backstop below)
        alias_note = _model.fold_picker_alias(model_set, model_drop, "none" if pw_given.lower() in h.ask_none else _model.norm_who(pw_given), waits_after, _gates.post_wake_alias_until())
        alias_picker = "is mover now" in alias_note and "mover" in model_set
    if (needs_set or agent.strip()) and "mover" not in model_set and "mover" not in model_drop and _old_holder_goes(meta):    # a hand-off by needs moves the item: a stored mover that is not among the sessions now named is the old holder, so it goes
        meta.pop("mover", None)
    needs_replaced: list[str] = []      # the session this write put into `needs` in place of the mover it came from: it hears the hand-off notice, not a second "now needs you"
    if "mover" in model_set and not alias_picker and not (needs_set or agent.strip() or clear_needs):      # a hand-over by `mover=` alone: the session `needs` names for the mover it came from is replaced by the new one, so a hand-back leaves no stale entry (a write that sets `needs` itself is taken as given)
        prev_mv, new_mv = _model.norm_who(meta.get("mover")), _model.norm_who(model_set.get("mover"))
        nm_now = _anc.names()
        if prev_mv and new_mv and not _model.is_owner(prev_mv) and not _model.is_owner(new_mv) and _anc.canonical(prev_mv, nm_now) != _anc.canonical(new_mv, nm_now):
            is_prev = lambda x: x.lower() not in _NEEDS_KINDS and _anc.canonical(x, nm_now) == _anc.canonical(prev_mv, nm_now)      # noqa: E731
            held = _needs_of(meta)
            if any(is_prev(x) for x in held):
                _needs_store(meta, _canon_needs([new_mv if is_prev(x) else x for x in held], nm_now))
                needs_replaced.append(new_mv)
    picker_waited = was_until or _model.waits_stored(item_was.get("metadata") or {})      # the item waited before this write: only then does the old pick-up stand for keep_picker (an alive item's mover is its live mover, a stale old key never beats it)
    h.model_apply(meta, str(item.get("status") or ""), model_set, model_drop)   # goal, mover, then and the wait's fields: a filing edit
    _model.settle_picker_keys(meta, model_set, model_drop, picker_waited,
                              _model.waits_stored(meta) or bool(was_until and (meta.get("wake") or meta.get("ask_by"))), _anc.same_session)      # the one save rule (a stored until is unfolded into a wake for this write): a new mover, clear_mover and clear_wait never leave the old key or his pick-up standing
    if item.get("status") == "open" and picker_waited and (clear_wait or clear_hold) and not (relay_clear_hold and not clear_wait) and not (needs_set or clear_needs or agent.strip()):
        if not any(x.lower() == "decision" or _model.is_owner(x) for x in _needs_of(meta)):
            _model.keep_picker(meta, _model.stored_picker(item_was.get("metadata") or {}), model_set, model_drop)      # clear_wait and clear_hold end the wait, never the hand-over: the picker the item read as before the write stays the mover, whichever key stored it
        elif "mover" not in model_set and "mover" not in model_drop and not _model.is_owner(_model.norm_who(meta.get("mover"))):
            meta.pop("mover", None)      # an item that waits on his answer is his move, whoever picked it up: the agent stored as the picker goes with the wait, so it is no second mover beside him
    if "wait_kind" in model_drop:
        h.wait_end_sent_back(meta, (_we.PR, _we.BOX, _we.URL, _we.STORED))      # clear_wait on a wait the server set from the line's words
        if was_until and not (wake or hold):
            for k_ in _uw.LEGACY_FIELDS:                # clear_wait drops the stored until (model.WAIT_GROUP); the old working fields it stood as go with it
                meta.pop(k_, None)
    wait_note = alias_note
    if list_plan is not None:
        wait_note += list_plan.note + _list_note(list_plan, meta, item.get("status") == "open")
    elif _wlw.clearing(waits) and not _wl.stored(item_was.get("metadata") or {}):
        wait_note += "\n(waits=[] clears a list of waits; this item stores none, so nothing was cleared and its wait is as it was)"
    if relay_clear_hold:
        wait_note += "\n(clear_hold releases a park, and this relay or event wait holds no flag: it goes on waiting; clear_wait=true ends the wait)"
    if relay_hold:
        wait_note += "\n(a relay or event wait stores no park flag: the wait is itself the park, until its day " + (_uw._dated(ask_by) or _uw._dated(meta.get("ask_by"))) + "; it ends when the notice arrives or on that day)"
    gave_ask = bool(ask_by.strip()) and ask_by.strip().lower() not in h.ask_none
    if bool(wake) != gave_ask and item.get("status") == "open":      # one date given: a date the item held before in the other working field (an unfolded until, or an older write's wake or ask_by) does not outlive it
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
    fc.call(_gates.gate_ask_on_wait, gid, item, meta, was_needs, closing)           # a decision asked of the owner on an item that still waits: the clear_wait hint
    watch_note = fc.call(h.watch_on_write, gid, item_was, meta, model_set, model_drop, debtor, sender.strip(), default="")   # the wait's record, the arrival that was shown
    fc.call(_gates.gate_metadata, meta, creating=False)
    lifted = "" if (ask or clear_ask or item.get("status") == "completed") else h.lift_ask(meta, refresh=bool(next), writer=next_writer, keeper=keeper_was)   # a client without the ask parameter
    if lifted and own_links and meta.get("ask") != ask_was:                  # the ask this call sets by the first line of next is judged as an ask given as a parameter is
        fc.call(_dg._gate_ask_links, meta.get("ask"))
    steps_note = merged_note + reword_note
    steps_new = None                                            # the checklist this write leaves (set below when the write touches it): reads it
    if steps_on and not closing and (next_touch or marks):      # the checklist follows next, and next follows a mark: a marked line leaves next with its writer
        marked_text = [steps_old[i]["text"] for i in (*done_ix, *drop_ix)]
        grown_bad = False
        if _writes.session_next():                 # N3: nothing leaves the list; a reworded open step is no rewrite of its text to add words to it (a session's write only)
            leaving, arriving = _nr.moves(steps_old, done_ix, drop_ix, _fg._nl_text_without(meta, marked_text, keeper_was))
            leaving = [(i, t) for i, t in leaving if i not in drop_ix]      # a step marked dropped stays on the list as dropped: the extended line that replaces it is a new action, not a rewrite (reviewer note d)
            if grown := _nr.growths([t for _, t in leaving], arriving):
                grown_bad = True
                old_s, new_s = grown[0]
                pos = [i + 1 for i, t in leaving if t == old_s][0]
                fc.add(f"Refused: the step \"{_clip_line(_steps.first_line(new_s), 90)}\" is the open step \"{_clip_line(_steps.first_line(old_s), 90)}\" with words added: a step is never rewritten to add progress, "
                                f"so nothing leaves the list that way: the old step is left without a mark. Keep the step as it is, or mark it (done=[{pos}] when the work is finished, dropped=[{pos}] when it is no longer wanted) and write the next step as a new action; "
                                "progress, results and what was tried go on the project page (Current state or a timeline line)")
        try:
            steps_new = _steps.apply(steps_old, _fg._nl_text_without(meta, marked_text, keeper_was), done_ix, drop_ix, steps_by, time.time(),
                                     written=next, own=lambda w: not w or _handoff.ho_same(w, next_writer), wipe=clear_next, strict=_fg._require_marks(), reworded=reword_ix)
        except _steps.StepError as e:
            if grown_bad:      # the step it names is the one refused above (its words with more added): it is judged once that is fixed
                fc.skip("the check that next leaves none of your open steps unmarked", "it reads the step refused above")
            else:
                fc.add(f"Refused: {e}")
        if steps_new is not None:
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
        fc.add(f"Refused: {_gh.shown(gid)} is being closed, and a close leaves no open step to give a proof: send step_proof on a call that keeps the item open")
    if closing:                                                 # a close leaves no open step, so no proof
        meta.pop("step_proof", None)
    elif steps_on:                                              # the proofs of this checklist's open steps: a call's step_proof sets them, a step that left the list takes its proof along
        if step_proof is not None:
            steps_note += _proofs.step_proof_set(meta, steps_new if steps_new is not None else steps_old, step_proof)
        elif steps_new is not None:
            steps_note += _proofs.step_proof_prune(meta, steps_new)
        if steps_new is not None:
            fc.call(_gates.gate_step_gap, meta, steps_new, steps_old)         # a step that delivers a pull request, followed by another session's step, needs its proof
    elif step_proof is not None:
        fc.add(f"Refused: {_gh.shown(gid)} is closed and its checklist is the record of what was done; reopen it (status=open with a next) before giving a step a proof")
    asked = lifted + ("" if item.get("status") == "completed" else h.ask_owed(meta))   # a needs=decision item left without an ask (a completion never needs one)
    if item.get("status") != "completed" and not closing and (ask or meta.get("ask") != ask_was):   # only a call that writes or changes the ask
        fc.call_family(*_faults.DECISION, _dg._gate_one_decision, meta, item.get("description") or "", bool(lifted) and not ask)
    if item.get("status") != "completed" and (ask or (description and not reformat) or needs_set or opts is not None):   # only a call that writes what it reads
        fc.call_family(*_faults.DECISION, _dg._gate_alternatives, meta, item.get("description") or "")
    if item.get("status") != "completed" and not closing and (ask or meta.get("ask") != ask_was or opts is not None
                                                               or (needs_set and "decision" not in [str(x).lower() for x in was_needs])):   # a write that sets the ask or the options, or puts the item on his call: an open question needs options
        fc.call_family(*_faults.DECISION, _dg._gate_open_question, meta)
        fc.call_family(*_faults.DECISION, _dg._gate_recommend_stance, meta)       # the same writes: no options and a Recommend that is no yes or no
        fc.call(_dg._gate_design_link, meta)                                     # the same writes: a design, plan or proposal asked about is linked in the ask (its own fault)
    if item.get("status") != "completed" and not closing and (ask or (description and not reformat) or next_touch or needs_set or opts is not None):   # a write that sets the ask or the text it is read against
        fc.call_family(*_faults.DECISION, _dg._gate_mockup, meta, item.get("description") or "")
    if item.get("status") != "completed" and not closing and (ask or needs_set or opts is not None or next_touch):   # his own action asked as a decision: only a call that writes what it reads
        fc.call_family(*_faults.DECISION, _dg._gate_own_action, meta, next_only=not (ask or needs_set or opts is not None))
    if item.get("status") != "completed" and (ask or opts):
        asked += _dg._options_note(meta) + _dg._actor_note(meta, options=bool(opts), ask=bool(ask))
    hold_note = ""
    if ((hold and meta.get("hold") and meta.get("state") in _states.STATES and meta["state"] != "parked")
            or (relay_hold and meta.get("state") in _model.ALIVE_STATES)) and not state_st:     # a hold makes the item read parked: a state of another kind cannot stand beside it; a relay or event wait stores no flag, so the hold ends only the alive states the model's conflict line names (a waiting state stands beside the wait and keeps its fields)
        hold_note = f"\n(stored state {meta['state']} dropped: a park ends it; the item reads " + ("as its relay or event wait" if relay_hold else "parked") + ")"
        h.state_end(meta)
    state_touched = frozenset(k for k, v in (("needs", needs_set or clear_needs or agent.strip()), ("after", after_set or clear_after),
                                              ("wake", wake or clear_wake), ("hold", hold or clear_hold), ("ask", ask or clear_ask), ("next", next_touch),
                                              ("wait_basis", basis_txt or clear_wait_basis)) if v)
    work_note += hold_note + h.state_apply(meta, str(item.get("status") or ""), state_st, state_given, state_touched, step_withdrawn)   # the state last: it reads the item as every gate above left it
    desc_note = ""
    mover_named = "mover" in model_set or "mover" in model_drop or filing_only or _writes.reformat()      # a write that names the mover, or only files (rename, priority, re-bullet): the server flips nothing for it
    if item.get("status") == "open":      # the state checks, on the item as this write leaves it (they refuse, or mark, before anything is saved)
        item_now = {**item, "metadata": meta}
        if done_ix and steps_on and _model.stood_his(item_now, lambda i_: h.after_open(i_.get("metadata") or {})):      # N4: while the item, as this write leaves it, waits on him, only his answer ticks his step (a call that also ends what asks him is no refusal: it withdraws the ask and the step goes with it)
            _why = _hs.refuse_done(steps_old, done_ix, _hs.recorded(item_was.get("metadata") or {}), h.owner_want(meta), item_was.get("metadata") or {})
            if _why:
                fc.add(f"Refused: {_why}")
        if _writes.session_next() and steps_new is not None and any(x["status"] == _steps.OPEN for x in steps_old) and not any(x["status"] == _steps.OPEN for x in steps_new) \
                and not _model.stood_his(item_now, lambda i_: h.after_open(i_.get("metadata") or {})):      # N6: a session's write that takes the last open step off an item that stays open (his server-made step counts; a close is exempt)
            fc.add(f"Refused: this write leaves {_gh.shown(gid)} open with no open step in next: {_nr.NO_STEP_FIX_HELD if meta.get('hold') else _nr.NO_STEP_FIX}")
        mover_note = h.owner_state_mover(item_now, meta, mover_named, item_was)      # a bookkeeping write (rename, priority, re-bullet) flips nothing; his state makes him the mover: before the guards read the item
        if "then" in model_set or not (filing_only or _writes.reformat()):
            mover_note += h.then_stands({**item, "metadata": meta}, meta)      # a `then` beside an agent is dropped with a note, also when the write names the mover itself (the mover step above leaves that write alone) and when the write only sets the `then` (a model field, so a filing write)
        if not (filing_only or _writes.reformat()):
            mover_note += h.owner_then_default(item_was, meta, str(item.get("status") or ""), sender.strip(), "then" in model_set or "then" in model_drop, mover.strip())      # D9: then defaults to the agent doing the work, not to the front agent that relayed the ask
        wake_changed = bool(wake) and meta.get("wake") != (item_was.get("metadata") or {}).get("wake")      # re-sending the wake the item carries sets nothing
        watch_ok = fc.call(_gates.gate_sender_watch, gid, item_now, sender.strip(), handed=handed, watch_reason=watch_reason, default="") if wake_changed else ""   # a front agent's own wake or until date on an alive item another session moves
        if watch_ok:
            meta["watch_reason"] = watch_ok[:300]
        elif wake_changed or not meta.get("wake"):
            meta.pop("watch_reason", None)      # a reason belongs to the wake it was given for: another wake without one, or no wake, drops it
        fc.call(_gates.gate_decision_again, item_was, meta, was_needs, ask_was, gid)
        if _writes.session_next() and h.model_guards_on() and not (reopening or _writes.reformat()) and item_was.get("status") == "open":
            fc.call_depending("the check that the clock is not renewed without progress", "it reads his words in said, which is refused above", said_bad,
                              _gates.gate_clock_renewal, item_was, meta, gid, steps_old, steps_new, description, said_l, sender, list_end_words)      # no clock renewal without progress: a session's write only
        fc.call_depending("the check that a park is not renewed without progress", "it reads his words in said, which is refused above", said_bad,
                          _gates.gate_repark, item_was, item_now, meta, gid, said_l)
        _mark_next_stale(item_was, item_now, meta, debtor, naming_added, next_touch)
        touched_m = {k for k, v in (("next", next_touch), ("ask", ask), ("subject", subject), ("description", description.strip()),("needs", needs_set or clear_needs or agent.strip()), ("hold", hold or clear_hold),
                                    ("wake", wake or clear_wake), ("after", after_set or clear_after), ("state", state_st), ("wait_basis", basis_txt or clear_wait_basis)) if v}
        touched_m |= set(model_set) | set(model_drop)           # goal, mover, then and the wait's fields this write sets or clears
        if list_plan is not None:
            touched_m |= {"waits", "wait_mode"}
        if wake:
            touched_m.add("cap_ok")                             # a wake records his words for it
        full_judgement = reopening or (h.switchover_on() and not filing_only)     # step 4's switchover: every write is judged whole, old items included; a bookkeeping write (a page rename) still only by what it touches
        desc_note = fc.call(_gates.gate_model, item_now, None if full_judgement else touched_m, gid, needs=[x for x in _needs_of(meta) if x not in naming_added], hold=hold_pre, desc_set=bool(description.strip()),
                            next_text=next_judged if next_touch else None, windows_text=next_judged if next_touch else "", defers_text=next_judged if next_touch else "",
                            until_wait=until_wait or (was_until and not (wake or hold or clear_wait_basis or str(wait_basis or "").strip())), date_given=bool(wake), hold_given=bool(hold), basis_kept=bool(wake) and not str(wait_basis or "").strip() and _gates.basis_held({**item, "status": status or item.get("status")}, hold=hold, verifying=state_st == "verifying"),
                            old_end_ok=gave_ask or not (reopening or touched_m & _mg.WAIT_SETTING), date_ends=old_ask and bool(wake), default="")   # the write guards of the item model; his lines' Windows check judges only the lines this write sets; a wait on an until carries no snooze reason
        desc_note += mover_note
        fc.call(h.anchor_wait_gate, item_was.get("metadata") or {}, meta, gid)      # an anchor wait newly set or moved: its anchor must be on the project's list already (after the model guards)
        if next_touch or state_st or state_given.get("step") or needs_set or clear_needs or agent.strip():      # only a write that touches next, the state, needs or the step; any other keeps the note. After the model guards, so their more specific refusals (a command in his line) come first
            if not _writes.terminal_row():      # the terminal prompt's repair path (a script's own row, orphan case) is exempt as on create
                try:
                    _gates.gate_owner_step(item_now, gid, sender=next_writer, keeper=keeper_was)
                except _gates.HisStepRefusal as e_step:
                    e_step.said = tuple(said_l)      # what this write stores as said: step_settle.py marks his step done only for a checked Acked-by among it
                    if not fc.found:
                        raise                        # alone it is the write's own settling (step_settle.py), which makes the write whole
                    fc.add(e_step)                   # beside other faults the write is refused whole: the writer sends it again with all of them fixed
        if next_touch or state_st or state_given.get("step") or needs_set or clear_needs or ask or "mover" in model_set or "mover" in model_drop:      # several members: a decision, a step or a `you:` line names which member (no check with one)
            fc.call(_mgates.gate_members, meta)
        if state_st or state_given.get("step") or "mover" in model_set or "mover" in model_drop or draft_set or clear_draft:      # the draft guard reads a write that sets the state, the step, the mover or the draft, never an unrelated one
            fc.call(_gates.gate_draft, item_now, gid)
        if state_st or state_given.get("step") or "mover" in model_set or "mover" in model_drop or draft_set or clear_draft or description.strip():      # the step guards read the same writes, and a new description
            fc.call(_gates.gate_step, item_now, gid, item_was.get("description") if description.strip() and _sc.owner_facing(item_was) else None, step_set=bool(state_given.get("step")))      # only an item already his to move (mover the owner, your-step, your-call) keeps the old lines out of the judgement
        fc.call_depending(*_faults.MOVER_HANDOFF, fc.marked(_faults.MOVER), _gates.gate_handoff, gid, item_was, item_now, debtor)     # step 2: a hand-off to a session with no pane is refused, the background agent named
        if _writes.session_next() and h.model_guards_on() and steps_new is not None and not (filing_only or _writes.reformat() or sender.strip().startswith("a script on ")):
            fc.call_depending(*_faults.MOVER_FRONT_STEP, fc.marked(_faults.MOVER), _gates.gate_front_step, gid, item_now, steps_before, steps_new, sender.strip() or debtor)     # a new or reworded step that opens with a front agent on an item another session moves: nothing could wake it for the step
    kept_legacy_wake = False
    backstop = False                       # a bare date beside a hand-off, kept as the wake it was (below)
    if item.get("status") == "open" and (was_until or wake or hold or ask_by.strip() or until_wait):
        if _wt.after_of(meta) and not _uw.kind_of(meta) and not clear_after and (after_set or had_hold or bool(h.after_open(meta))) and _uw.date_of(meta):
            meta["wait_kind"] = "item"                   # a date beside an after link with no kind is that wait's backstop (as ask_by was); create does the same
        kept_legacy_wake = bool(meta.get("wake")) and not until_wait and (bool(wake) or not was_until)      # the wake as the old parameter (or an older write) gave it keeps the legacy-wake note; a date passed as until never does
        keep_hold = bool(meta.get("hold")) and bool(_wt.wake_value(meta)) and bool({"anchor", "recycle"} & set(h.hold_held_by(gid, meta)))      # a hold that waits on an anchor scoped to the item or on a pane recycle keeps its flag and record (the anchor release, the backstop gate and the recycle read them); the date is its backstop
        kept_hold_set = meta.get("hold_set")
        read_failed: list[bool] = []
        backstop = bool(_uw.date_of(meta)) and _wait_is_bare(meta) and _hands_on(gid, item_was, {**item, "metadata": meta}, handed, sender.strip() or debtor or "", read_failed, picker_alias=alias_picker)
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
            if gave_ask and meta.get("ask_by") and not meta.get("wake") and not _uw.kind_of(meta) and h.model_of({**item, "gid": gid, "metadata": meta}).state == _model.WAITING:
                meta["wake"] = meta.pop("ask_by")      # the write leaves the item waiting (needs external), and the wake pass reads an ask_by only beside a relay or event kind: the backstop is stored where it is read
            if was_until and _wait_is_bare(item_was.get("metadata") or {}):
                wait_note += (f"\n(the item was waiting until {_uw.date_of(item_was.get('metadata') or {})}: this hand-off ends that wait. The date stays as the hand-off's backstop, and the item is active in the new mover's lane)")
        else:
            _uw.fold(meta)                 # every gate above judged the wait in the words of the old fields; it is stored as the one date, until, and none of them
            if str(meta.get("wait_kind") or "").strip().lower() == _wl.LIST and not _wl.valid(meta) and (list_set or _wl.valid(item_was.get("metadata") or {})):
                fc.add(f"Refused: this write would leave {_gh.shown(gid)} with a wait on a list that does not hold ({_wl.problem(meta) or 'no backstop day'}). A list needs its backstop day: "
                                "pass until=<date>, or clear_wait=true to end the wait")
            if _wl.valid(meta) and str(meta.get("until") or "") != _uw.date_of(item_was.get("metadata") or {}):      # the backstop day this write leaves a list (whichever parameter gave it: until, ask_by, a clear that let it through) is judged as until alone is: no open time line later than it
                fc.call(_gates.gate_time_lines, [(i, ln["until"]) for i, ln in enumerate(_wl.lines(meta), 1) if ln["kind"] == "time" and not _wl.arrived(ln)], str(meta["until"]))
        if keep_hold:
            meta["hold"] = True
            if kept_hold_set:
                meta["hold_set"] = kept_hold_set
    fc.raise_now()                         # every gate has run: what was found is refused together, nothing is stored
    item["metadata"] = meta
    item["updated"] = time.time()          # the item's own clock (the renderer used to trust the file's mtime, which a migration rewrites)
    if state_change:
        item["state_updated"] = item["updated"]   # filing edits (owner/project/priority/subject, and the ask line) leave the state clock alone
        item["confirmed"] = item["updated"]       # a state change confirms the item; a filing edit does not
    named = name_commit()                  # every gate has passed: the naming is stored as its own save, then this write's
    _writes.save(gid, item, writer=debtor, ctx=_writes.QUIET if (filing_only or _writes.reformat()) else (_writes.NAMED if mover_named else _writes.PLAIN), written=next if next_touch else "")
    now_held = h.is_held(item)
    now_parked = now_held or h.date_parked(item)
    if wake or clear_wake or hold or clear_hold or item.get("status") != was or now_parked != was_parked:
        h.wake_event_set()         # the minute loop recomputes its next wake now, so a wake set a minute ahead still fires on time
    told = ""
    relayed = False               # this write already went to the project's keeper or router (pilot_relay): one event makes one inbound there
    if state_change and not _writes.terminal_row():     # a terminal-prompt row owes the page nothing: no debt for the script or the keeper, no notice to the router
        stew, role = _telling.pilot_charge(meta.get("project", ""), debtor)
        moved = bool(stew) and role == "name" and h.writer_owes()     # the writer owes it; the keeper only past the grace
        if not moved:
            h.owed_mark(meta.get("project", ""), stew or debtor, gid)
        if stew:
            what = (f"completed ({outcome}{' by ' + _gh.shown(superseded_by) if superseded_by else ''})" if closing else "reopened" if reopening else "completed" if status == "completed" else "parked" if now_parked and not was_parked else "unparked" if clear_hold and was_parked
                    else "changed (" + ", ".join(k for k, v in (("description", description), ("next", next_touch), ("needs", needs_set or clear_needs), ("status", status), ("due", due or clear_due),
                                                                 ("hold", hold or clear_hold), ("wake", wake or clear_wake), ("after", after_set or clear_after)) if v) + ")")
            if not moved:
                told = _telling.pilot_relay(meta.get("project", ""), gid, item, what, debtor, stew, role)
                relayed = bool(told)
            else:
                loose = not (description or needs_set or clear_needs or status or due or clear_due)   # only next, after, or the hold and its wake
                told = _telling.writer_charge(meta.get("project", ""), gid, debtor, stew, what, loose)
                if item.get("status") == "completed" and was != "completed" and h.scoped_anchors(meta.get("project", ""), gid):
                    relayed = bool(_telling.pilot_relay(meta.get("project", ""), gid, item, what, debtor, stew, role,   # the keeper still gets this notice when anchors were scoped to the item; it owes nothing for them: the close's own reply lists the anchors the close ended (anchor_sweep.on_close)
                                                tail=f"no page update is owed by you ({_session_label(debtor)} writes it); this notice is for the anchors scoped to {_gh.shown(gid)}"))
    h.publish()
    item["gid"] = gid
    hint = ("\nstill parked: pass clear_hold=true to release it"
            if status == "open" and was_held and now_held and not (hold or wake) else "")   # a session with the old rulebook in context learns the new form
    heard: list[str] = []         # the mover, when a notice below reached it as mover: its "now needs you" line would double it
    owner_told = _telling.owner_reached(named, relayed)   # tell_owner (the server's naming of the writer above, or a notice below) already told the mover this write: tell_owner_change then adds nothing
    _telling.CLOSE_WAS.item = item_was if closing else None      # a close is told to the mover, which the close dropped from the item
    if closing:                   # the item's mover hears what another session did that it must know
        what_ = f"was completed ({outcome}{' by ' + _gh.shown(superseded_by) if superseded_by else ''}{': ' + reason if reason else ''})"
        t_ = _telling.tell_owner(gid, item, what_, debtor, close=True); told += t_; owner_told = owner_told or _telling.owner_reached(t_, relayed)
        told += _telling.tell_observers(gid, item, what_, debtor)                      # observers hear a close
        rel = h.release_after(gid, outcome, superseded_by, debtor, reason)      # the items that waited on this one: and the movers of the items that name it
        if rel:
            told += f"\n({', '.join(rel)} waited on {gid} and {'is' if len(rel) == 1 else 'are'} released: the sessions in {'its' if len(rel) == 1 else 'their'} needs, else the page keeper, have been told)"
        told += _telling.mentions_reply(gid)
        told += _asweep.on_close(gid, h.publish)      # the anchors scoped to this item that this close left with no open item in their scope end here (rule 1 of anchor_sweep.py), each logged with the call that puts it back
    elif reopening:
        what_ = "was reopened (next: " + (next.strip().splitlines() or [""])[0][:160] + ")"
        t_ = _telling.tell_owner(gid, item, what_, debtor, heard=heard); told += t_; owner_told = owner_told or _telling.owner_reached(t_, relayed)
        told += _telling.tell_observers(gid, item, what_, debtor)                      # observers hear a reopen
        told += _asweep.reopen_note(gid, str(meta.get("project") or ""))      # the anchors its close ended do not come back: the reply names the restore call on the routing log lines (anchor_sweep.reopen_note)
    elif "decision" in _needs_kinds(meta) and "decision" not in was_needs and item.get("status") == "open":
        t_ = _telling.tell_owner(gid, item, f"now needs {OWNER}'s call" + (f" (ask: {meta['ask']})" if meta.get("ask") else "")
                         + "".join(f"; {ln}" for ln in h.render_option_lines(item)) + ", set", debtor, decision=True, heard=heard)
        told += t_; owner_told = owner_told or bool(t_)    # a move to decision is never pushed to a front agent mover (the board shows it), so its quiet line counts
    if item.get("status") == "open":   # a session newly named in needs gets one notice
        if not (closing or reopening):
            try:
                told += _telling.tell_handback(gid, item, was_needs, debtor, heard)   # a front agent mover hears an item handed back to it alone; nothing else wakes it
            except Exception as e:  # noqa: BLE001  — the write is saved and published; a notice that fails is a stderr line, never a failed write
                print(f"owner: {gid} hand-back not told: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        new_s = [s for s in _needs_sessions(meta) if h.session_id(s) not in {h.session_id(x) for x in [*was_needs, *needs_replaced]}]
        told += _telling.tell_needed(gid, item, new_s, debtor, heard)
        if "decision" in [str(x).lower() for x in was_needs] and "decision" not in _needs_kinds(meta):   # he has decided; the sessions still named move now
            told += _telling.tell_decided(gid, item, [s for s in _needs_sessions(meta) if s not in new_s], debtor, heard)
    try:
        step = _telling.tell_owner_close(gid, item, debtor, closing, heard)   # the front agent mover hears a close by another session at once; a builder's step is never pushed to it
    except Exception as e:  # noqa: BLE001  — the write is saved and published; a notice that fails is a stderr line, never a failed write
        print(f"owner: {gid} step not told: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        step = ""
    if step:
        owner_told = True
        told, named = told.replace(_telling.quiet_line(item), ""), named.replace(_telling.quiet_line(item), "")   # the mover was told after all
        told += step
    if h.session_id(_telling.holder(item)) in heard:
        owner_told = True
    try:
        chg = _telling.tell_owner_change(gid, item, before, debtor, closing, owner_told, relayed, reopening)   # the defect fix: another session's next, needs, check or after change, or its close or reopen
    except Exception as e:  # noqa: BLE001  — the write is saved and published; a notice that fails is a stderr line, never a failed write
        print(f"owner: {gid} change not told: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        chg = ""
    quiet_ = _telling.quiet_line(item)
    if "the notice went to" in chg:       # a front agent mover's "not told" line above was true of the mover, not of the write: the notice went to the page
        told, named = told.replace(quiet_, ""), named.replace(quiet_, "")
    elif chg == quiet_ and quiet_ in told + named:
        chg = ""                          # the reply already says it once
    told += chg
    told += _telling.handoff_notify(gid, item)     # step 2: the new mover of a hand-off this write recorded is told, unless a notice above did
    if done_ix and steps_new is not None and item.get("status") == "open" and not (closing or reopening or needs_set or agent.strip() or "mover" in model_set or "mover" in model_drop):
        told += _handover_by_hand(gid, [_steps.first_line(steps_new[i]["text"]) for i in done_ix])      # a step marked done by hand: the session the next step names is handed the item, as a ticked step does
        item = {**_load(gid), "gid": gid}
    try:
        stale_wait = _stale_wait_notes(item_was, item, keeper_was)      # a wait cleared while an open next line still defers on it: named, so the writer rewords the line now
    except Exception as e:  # noqa: BLE001  — the write is saved and published; a note that fails is a stderr line, never a failed write
        print(f"update: {gid} stale-wait notes not made: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        stale_wait = ""
    dropped_note = ""
    if description.strip():
        try:
            dropped_note = _dropped_lines_note(item_was.get("description"), item.get("description"))      # lines of the old description the new one lacks: named with their old text, so the writer can put a fact back
        except Exception as e:  # noqa: BLE001  — the write is saved and published; a note that fails is a stderr line, never a failed write
            print(f"update: {gid} dropped-lines note not made: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    goal_note = ""
    if _writes.session_next() and not reformat and not sender.strip().startswith("a script on "):      # the writes the goal gate judges: a session's own words
        try:
            if description.strip():
                goal_note = _goal_moved_note(item_was, item, desc_sent)
            # a write that names the item anew, or says anew what it is (a title that asked the owner's choice outlives it so), is told when the open item's title is a question or an activity
            if item.get("status") == "open" and any(item.get(k) != item_was.get(k) for k in ("subject", "description")):
                goal_note += _fg.subject_form_note(str(item.get("subject") or ""))
        except Exception as e:  # noqa: BLE001  — the write is saved and published; a note that fails is a stderr line, never a failed write
            print(f"update: {gid} goal note not made: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    machine_note = h.machine_note(gid, item, keeper_was)      # an open step names an offline machine and no machine anchor tells the mover when it is back: a note, never a refusal
    offer_note = _anchor_offers.item_line(gid, item, item_was)      # a relay wait this write set, or a source link it put in the description, that no anchor watches: one line with the ready anchors call, never a refusal
    if dropped_hold:
        hint += (f"\n(note: {_gh.shown(gid)} waits on {OWNER}'s call (needs decision), so it is never parked: the park is dropped"
                 + (f"; its date {_wt.wake_value(meta)} stays" if _wt.wake_value(meta) else "") + ")")
    return (f"updated {_gh.shown(gid)}.\n" + h.fmt(item) + hint + wait_fixed + work_note + steps_note + asked + watch_note + h.form_notes(description, next_judged, bool(hold or wake) and now_parked, meta, gid,
                                                                 cmd=item.get("status") == "open" and bool(ask or next_judged or needs_set),
                                                                 ext="external" in _needs_kinds(meta) and "external" not in [str(x).lower() for x in was_needs]) + desc_note + stale_wait + dropped_note + goal_note + wait_note + machine_note + offer_note + (_doing_wait_note(meta, next_judged, busy=busy_note) if item.get("status") == "open" else "") + (_wait_tells(sender, [wait_basis, wait_event, wait_reason], [next_judged], bool(not backstop and (hold or wake or until_wait or after_set or wait_kind.strip() or str(wait_basis or "").strip() or waits))) if item.get("status") == "open" else "") + _retired_note(expected_by, expected_reason) + ((h.wake_window_note(_uw.unfolded(meta) if kept_legacy_wake else meta) if wake and not backstop else "") or (h.wake_step_note({**item, "gid": gid}, (sender, debtor), legacy_wake=kept_legacy_wake) if wake or next_touch else "") if item.get("status") == "open" else "")
            + answered_note + named + told + owing + h.nag(debtor))


def _handover_by_hand(gid: str, done: list[str]) -> str:
    """The reply line of an update that marked steps done: proofs.handover for the item, a failure a stderr line and no line. A write that names the mover or needs itself makes its own hand-off and never reaches this."""
    h = _hooks()
    try:
        ho = _proofs.handover(gid, time.time(), done)
    except Exception as e:  # noqa: BLE001  — the write is saved: a hand-over that fails is a stderr line, and the audit finds the next session unreached
        print(f"handover: {gid} not made: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return ""
    if not ho or ho["action"] not in ("moved", "fallback"):
        return ""
    h.publish()
    to = _session_label(ho["to"])
    return (f"\n(the next step is {to}'s: {_gh.shown(gid)} is handed to {to}, who is told)" if ho["action"] == "moved"
            else f"\n(the next step is {to}'s, but {to} cannot take the item now ({_clip_line(ho['why'], 80)}): it stays with you)")


def said_preread(args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
    """With [agents_box] ssh set, the lookups of the write's `said` that go over ssh (the copy of the session registry, the transcripts on the agents' box) are made here, BEFORE the item lock, and
    kept in the write's lookaside (`agentbox.lookaside`): under the lock nothing is sent to the box, because a slow or silent box would hold up every write of every item. The gate is run dry
    (no fix noted, the result thrown away, any refusal left for the real run under the lock to raise again from the same answers), with the session it will be given there: the sender, else the
    item's owner, else its mover. Nothing without that setting or without a `said`."""
    if not _ab.enabled():
        return
    try:
        got = inspect.signature(update_unlocked).bind_partial(*args, **kwargs).arguments
        said = got.get("said")
        if said is None or said == [] or (isinstance(said, str) and not said.strip()):
            return
        sess = str(got.get("sender") or "").strip()
        if not sess:
            sess = str(got.get("owner") or "").strip() or _telling.holder(_load(_norm_id(str(got.get("item_id") or ""), bare=True)))
        _gates.gate_said(said, sess, "", dry=True)
    except Exception:  # noqa: BLE001  — a lookup that failed is the write's own refusal, raised under the lock from the same (missing) answers
        pass


@_rlive.reading()      # one write: a [released.repos] checkout its waits name is read once, before the lock, and the gate under it uses that read
def update_item(*args: Any, **kwargs: Any) -> str:
    """update_unlocked under the item lock (a failed delivery's record writes items from another thread; an
    update reads, changes and saves, so they take turns). The one entry of the update write: the update and complete tools, and every write of an item that the server makes (a wake, a cold call, a script's row)
    come through it (`_update`, below, calls it)."""
    h = _hooks()
    h.evwait_preread(kwargs.get("wait_kind"), kwargs.get("wait_event"))      # an event wait's facts (GitHub, git) are read before the lock, not under it
    for phrase_ in _wlw.event_phrases(kwargs.get("waits")):      # …and those of every event line of a list
        h.evwait_preread("event", phrase_)
    with _ab.lookaside():
        said_preread(args, kwargs)          # …and the said gate's lookups on the agents' box: no ssh is made while the item lock is held (core/agentbox.py)
        with _writes.ITEM_LOCK:
            try:
                try:
                    return update_unlocked(*args, **kwargs)
                except _gates.HisStepRefusal as e:      # his step left first in next under an agent's state: the write itself may say what became of it (step_settle.py)
                    return _settle.run(e, args, kwargs, update_unlocked)
            finally:
                _telling.CLOSE_WAS.item = None


@functools.wraps(update_unlocked)      # the tool's own signature stays visible to anything that reads it
def _update(*args: Any, **kwargs: Any) -> str:
    """The update write (`update_item`) under the item lock; the update and complete tools and every write the server makes itself come through here: the name the hook tables look up (a suite that replaces it here reaches all of them)."""
    return update_item(*args, **kwargs)


def complete_item(item_id: str, outcome: str = "", reason: str = "", description: str = "", superseded_by: str = "", sender: str = "", said: list[dict[str, Any]] | str | None = None,
                  outcome_text: str = "") -> str:
    """Close an item with how it ended: the complete tool without its identity and sender checks (the tool's own). It makes the update with status=completed, through `_update` in service/update.py (reached by its hook, so a suite
    that replaces it there still reaches the close). The close ends the anchors it left with no open item in their scope and says so in the reply (update_unlocked, through anchor_sweep.on_close). The fields default to empty so that a pane with an older cached schema gets the refusal
    that says what is missing and how to close through the portal, not a schema error."""
    h = _hooks()
    _load(_norm_id(item_id, bare=True))          # an item that does not exist is refused here, before anything is written
    with _writes.close_write():      # the complete tool's own call: the close ticks the sender's own steps only (update_unlocked reads it, as it reads session_next for the update tool's)
        return h.update(item_id, description=description, status="completed", sender=sender, outcome=outcome, reason=reason, superseded_by=superseded_by, said=said, outcome_text=outcome_text)


def confirm_item(item_id: str, sender: str = "") -> str:
    """Mark an item still true: sets its `confirmed` clock only (the confirm tool without its identity and sender checks). item_id: board#N (a bare number N or #N is read as board#N)."""
    h = _hooks()
    gid = _norm_id(item_id, bare=True)
    with _writes.ITEM_LOCK:         # read, changed and saved under the item lock: a write that lands between (an update, a pass in another process) is kept
        item = _load(gid)
        item["confirmed"] = time.time()
        # a bare confirm moves `confirmed` only, never `activity`
        # a confirm changes nothing but its clock: no mover is settled and no hand-off record ended by it
        _writes.save(gid, item, writer=h.session_id(sender) if sender.strip() else _telling.holder(item), activity=_activity.CONFIRM, ctx=_writes.QUIET)
    h.publish()
    item["gid"] = gid
    at = h.render_when_words(dt.datetime.fromtimestamp(item["confirmed"], h.zone()))
    return f"confirmed {_gh.shown(gid)} at {at}.\n" + h.fmt(item) + h.nag(sender)
