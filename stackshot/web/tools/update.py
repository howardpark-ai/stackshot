"""update.py: the `update` tool: the change of an existing item, its text, parameters and form pieces."""
from __future__ import annotations

from typing import Annotated, Any

from fastmcp.exceptions import ToolError
from pydantic import Field

from stackshot.core import config as _cfg
from stackshot.core.instance import OWNER
from stackshot.model import ask_leaves as _askl, model as _model, states as _states, work as _work
from stackshot.model.ids import _bare_id_ok, _norm_id
from stackshot.service import gates as _gates, wait_fixes as _wait_fixes, writes as _writes
from stackshot.service.store import _load
from stackshot.waits import until_write as _uw, wait_list_write as _wlw, waiting as _wt
from stackshot.web.auth import oauth as _oauth
from stackshot.model.field_gates import _fleet_tool, _when_idle
from stackshot.web.tools.notes import _off_map_note_item, _owner_param, _sender_required
from stackshot.web.tools.text import _AFTER_PARAM, _ALIASES, _ASK_NONE, _CHECK_PARAM, _CONTACT_PARAM, _DESCRIPTION_PARAM, _MOVER_PARAM, _OPTIONS_PARAM, _OUTCOME_PARAM, _OUTCOME_TEXT_PARAM, _POST_WAKE_PARAM, _P_BARE, _P_EX2, _P_OLD, _P_PLACE_STEP, _REASON_PARAM, _SAID_PARAM, _SELF_WAIT_FORM, _STEP_PROOF_PARAM, _THEN_PARAM, _WAIT_EVENT_PARAM, _WAIT_KIND_PARAM, _WAIT_MODE_PARAM, _WAITS_PARAM, _lead, load_text

_ask_after_write = None      # set by register: the server's own, looked up at each call
_sender_not_owner = None      # set by register: the server's own, looked up at each call
_update = None      # set by register: the server's own, looked up at each call
_busy_live = None      # set by register: the server's proof of what of a mover's own runs on an item (gates.gate_busy_hold); None passes every write


_OPEN_ITEMS = [OWNER, *_ALIASES[:1], "you"]
_OPEN_LIST = ", ".join(f"{i}:" for i in _OPEN_ITEMS[:-1]) + f" or {_OPEN_ITEMS[-1]}:"
_T = load_text("update", {
    "OPEN_LIST": _OPEN_LIST, "WORK_TEXT_MAX": str(_work.TEXT_MAX), "STATE_LINE_MAX": str(_states.LINE_MAX), "P_PLACE_STEP": _P_PLACE_STEP, "P_OLD": _P_OLD,
    "P_BARE": _P_BARE, "P_EX2": _P_EX2, "BASIS_MAX_WAKE_DAYS": str(_wt.BASIS_MAX_WAKE_DAYS), "TZ_ABBR": str(_cfg.tz_abbr()), "WHEN_IDLE": str(_when_idle()),
    "FLEET_TOOL": str(_fleet_tool())})


def _backstop_field(item_id: str, status: str) -> str:
    """The working field a hand-off kept its date in ("wake" or "ask_by"), "" when the item a write has just saved stores its date as until (or none)."""
    try:
        m = _load(_norm_id(item_id, bare=_bare_id_ok(status))).get("metadata") or {}
    except Exception:  # noqa: BLE001
        return ""
    if _wt.stored_until(m):
        return ""
    return "wake" if _model.clean(m.get("wake")) else "ask_by" if _model.clean(m.get("ask_by")) else ""


RANK_RETIRED = _T.piece("RANK_RETIRED")


# The update parameters whose text is read as the write's new text (ask_leaves.author_says_wrong): the sentence that takes an ask off his move must be ALL the new text of the call, so every
# parameter that can carry free text is listed here, and every other parameter says why it carries none. A test keeps the two lists equal to the update signature, so a parameter added
# later has to be placed in one of them.
_ASK_TEXT_PARAMS = ("subject", "description", "next", "options", "said", "work", "check", "wait_basis", "reason", "expected_reason", "step", "supplies", "goal", "wait_event", "draft", "watch_reason",
                    "outcome_text", "wait_reason", "reword", "waits",                                         # free text (a list's lines carry anchors, events and item ids)
                    "owner_name", "owner", "agent", "observers", "step_proof",                                # stored as written, with no check against a closed set: counted as text too
                    "wait_anchor", "post_wake_mover", "then")                                                 # a stored string a session names, accepted as written (found by a real update call with a hedge in it)
_ASK_NONTEXT_PARAMS = (
    "item_id", "status", "priority", "outcome", "wait_kind",                                                 # a fixed word, or the item's own id
    "due", "wake", "until", "expected_by", "ask_by",                                                                  # a date or a time
    "needs", "mover", "contact", "sender", "project",                                                        # a kind, or a session, a front agent or a page: a string with words in it is refused or not stored (a test sends one through the real update)
    "anchors", "after", "superseded_by",                                                                     # a link or an item id: the same test
    "done", "dropped", "rank",                                                                               # step numbers; a retired field
    "wait_mode",                                                                                             # all or any
    "ask", "clear_ask",                                                                                      # the ask itself: a write that sets one takes the ask-time check, not this
    "clear_needs", "clear_due", "clear_wake", "hold", "clear_hold", "recycle", "clear_recycle", "clear_options", "clear_after", "clear_wait_basis", "clear_rank", "clear_goal", "clear_mover",
    "clear_then", "clear_wait", "clear_draft", "clear_next", "clear_check")                                   # switches


def _ask_write_texts(params: "dict[str, Any]") -> "list[str]":
    """Every string a write carries in a text parameter (_ASK_TEXT_PARAMS; a mapping or list parameter gives each string inside it), for ask_leaves.new_lines and author_says_wrong."""
    return [x for n in _ASK_TEXT_PARAMS for x in _askl.text_leaves(params.get(n))]


_WAIT_FORM = _T.piece("WAIT_FORM")
_CHECKLIST_FORM = _T.piece("CHECKLIST_FORM")

_REWORD_PARAM = Annotated[dict[Any, str] | str | None, Field(description=_T.param("REWORD"))]

_WORK_PARAM = Annotated[dict[str, Any] | str | None, Field(description=_T.param("WORK"))]

_DONE_PARAM = Annotated[list[int | str] | int | str | None, Field(description=_T.param("DONE"))]

_DROPPED_PARAM = Annotated[list[int | str] | int | str | None, Field(description=_T.param("DROPPED"))]

_WAKE_PARAM = Annotated[str, Field(description=_T.param("WAKE"))]


_ASK_BY_PARAM = Annotated[str, Field(description=_T.param("ASK_BY"))]


_UNTIL_PARAM = Annotated[str, Field(description=_T.param("UNTIL"))]


_NEXT_PARAM = Annotated[str, Field(description=_T.param("NEXT"))]


_ASK_PARAM = Annotated[str, Field(description=_T.param("ASK"))]


_HOLD_PARAM = Annotated[bool, Field(description=_T.param("HOLD"))]


_WAIT_BASIS_PARAM = Annotated[str, Field(description=_T.param("WAIT_BASIS"))]


_RANK_PARAM = Annotated[int, Field(description=_T.param("RANK"))]
_CLEAR_RANK_PARAM = Annotated[bool, Field(description=_T.param("CLEAR_RANK"))]


_UPDATE_DESC = _T.piece("UPDATE_DESC")


def stackshot_update(
    item_id: str,
    subject: str = "",
    description: _DESCRIPTION_PARAM = "",
    status: str = "",
    next: _NEXT_PARAM = "",
    needs: list[str] | str = "",
    priority: str = "",
    due: str = "",
    anchors: list[str] | None = None,
    owner: str = "",
    owner_name: str = "",
    clear_needs: bool = False,
    project: Annotated[str, Field(description=_T.param("project"))] = "",
    sender: str = "",
    clear_due: bool = False,
    wake: _WAKE_PARAM = "",
    clear_wake: bool = False,
    hold: _HOLD_PARAM = False,
    clear_hold: bool = False,
    ask: _ASK_PARAM = "",
    recycle: bool = False,
    clear_recycle: bool = False,
    outcome: _OUTCOME_PARAM = "",
    reason: _REASON_PARAM = "",
    superseded_by: str = "",
    options: _OPTIONS_PARAM = None,
    agent: str = "",
    observers: list[str] | str | None = None,
    after: _AFTER_PARAM = None,
    work: _WORK_PARAM = None,
    said: Annotated[list[dict[str, Any]] | str | None, Field(description=_SAID_PARAM)] = None,
    check: _CHECK_PARAM = "",
    clear_options: bool = False,
    clear_ask: bool = False,
    clear_after: bool = False,
    wait_basis: _WAIT_BASIS_PARAM = "",
    clear_wait_basis: bool = False,
    rank: _RANK_PARAM = 0,
    clear_rank: _CLEAR_RANK_PARAM = False,
    expected_by: str = "",
    expected_reason: str = "",
    step: str = "",
    supplies: str = "",
    goal: str = "",
    mover: _MOVER_PARAM = "",
    then: _THEN_PARAM = "",
    wait_kind: _WAIT_KIND_PARAM = "",
    wait_anchor: str = "",
    wait_event: _WAIT_EVENT_PARAM = "",
    ask_by: _ASK_BY_PARAM = "",
    until: _UNTIL_PARAM = "",
    post_wake_mover: _POST_WAKE_PARAM = "",
    clear_goal: bool = False,
    clear_mover: bool = False,
    clear_then: bool = False,
    clear_wait: bool = False,
    draft: str = "",
    clear_draft: bool = False,
    clear_next: bool = False,
    clear_check: bool = False,
    done: _DONE_PARAM = None,
    dropped: _DROPPED_PARAM = None,
    step_proof: _STEP_PROOF_PARAM = None,
    watch_reason: str = "",
    outcome_text: _OUTCOME_TEXT_PARAM = "",
    wait_reason: Annotated[str, Field(description=_T.param("wait_reason"))] = "",
    contact: _CONTACT_PARAM = "",
    reword: _REWORD_PARAM = None,
    waits: _WAITS_PARAM = None,
    wait_mode: _WAIT_MODE_PARAM = "",
) -> str:
    """The update tool; its description is _UPDATE_DESC + _SELF_WAIT_FORM + _WAIT_FORM."""
    if rank or clear_rank:
        raise ToolError(RANK_RETIRED)       # a stale caller is told, never silently ignored
    _oauth._who()
    _sender_required(sender)
    _sender_not_owner(sender)
    note = _owner_param("update", owner)           # step 4b: owner is accepted with a note until [model] owner_param_until, then refused
    fixes: list[tuple[str, str, str]] = []; fix_note = ""
    if _model.clean(mover) or _model.clean(then) or _model.clean(post_wake_mover):
        try:
            meta_ = (_load(_norm_id(item_id, bare=_bare_id_ok(status))).get("metadata") or {})
        except Exception:  # noqa: BLE001
            meta_ = {}      # an unknown item is _update's to refuse
        proj_ = project or str(meta_.get("project") or "")
        vals = {"mover": mover, "then": then, "post_wake_mover": post_wake_mover}
        for f_, v_ in list(vals.items()):
            vals[f_], n_, fx_ = _gates.fix_front_mover(f_, v_, sender, proj_, str(meta_.get(f_) or ""), meta_)    # a front agent gets no hand-off notice: another session's value becomes the project's builder and the reply says so; the value the item already holds changes nothing; the same value sent again is kept as sent
            fix_note += n_; fixes += fx_
        mover, then, post_wake_mover = vals["mover"], vals["then"], vals["post_wake_mover"]
    list_in = _wlw.passed(waits) and not _wlw.clearing(waits)      # a wait on a list: its date is the backstop, read as an anchor or item wait's is, and it names its blockers (the lines)
    if list_in:
        old_ = [n for n, v in (("wake", wake), ("ask_by", ask_by), ("hold", hold)) if v and str(v).strip().lower() not in _ASK_NONE]
        if old_:
            raise _gates.waits_clash(old_)
    wake, ask_by, until_wait, alias_used, alias_date = _gates.until_in(item_id, status, until, wake, ask_by, hold, "list" if list_in else wait_kind)     # the date as the gates below read it; wake, ask_by and hold are aliases of until
    alias_ends = _wait_fixes._wait_alias_gate(alias_used)
    _gates.gate_self_wait(_norm_id(item_id, bare=_bare_id_ok(status)), sender, next_text=next, wake=wake, mover=mover, needs=needs, after=after or "", wait_kind=_wlw.judged_as(waits) if list_in else wait_kind, hold=hold, wait_basis=wait_basis, state="your-step" if step.strip() else "blocked" if supplies.strip() else "",
                    status=status, wait_reason=wait_reason, clear_next=clear_next, clear_wake=clear_wake, clear_needs=clear_needs, clear_after=clear_after, clear_wait=clear_wait, clear_hold=clear_hold)   # before the item lock: it may ask a model
    gid_ = _norm_id(item_id, bare=_bare_id_ok(status))
    live_ = (lambda g_, who_: _busy_live(g_, who_)) if _busy_live is not None else None
    _gates.gate_busy_hold(gid_, sender, hold=hold, wake=wake, ask_by=ask_by, wait_kind="list" if list_in else wait_kind, needs=needs, after=after or "",
                          mover=mover, next_text=next, status=status, done=done, clear_hold=clear_hold, clear_wake=clear_wake, clear_wait=clear_wait, clear_needs=clear_needs, clear_after=clear_after,
                          clear_next=clear_next, live=live_)      # before the item lock: an item its mover is moving is not paused
    busy_note = _gates.busy_note_answer(gid_, hold=hold, next_text=next, reword=reword, mover=mover, live=live_)      # …and the proof for the reply note of a doing item whose next reads as a wait, read here, never under the item lock
    ask_pre = _gates.ask_pre(item_id)      # the ask that stands before this write, for its tail (the reminder, the ask-time check, an ask the author calls wrong)
    with _writes.session_write():
        out = _update(item_id, subject, description, status, next, needs, priority, due, anchors, owner, owner_name, clear_needs, project, sender, clear_due, wake, clear_wake,
                       hold, clear_hold, ask, recycle, clear_recycle, outcome, reason, superseded_by, options=options, agent=agent, observers=observers, after=after, work=work, said=said, check=check,
                       clear_options=clear_options, clear_ask=clear_ask, clear_after=clear_after, wait_basis=wait_basis, clear_wait_basis=clear_wait_basis,
                       expected_by=expected_by, expected_reason=expected_reason, step=step, supplies=supplies,
                       goal=goal, mover=mover, then=then, wait_kind=wait_kind, wait_anchor=wait_anchor, wait_event=wait_event, ask_by=ask_by, post_wake_mover=post_wake_mover, until_wait=until_wait,
                       clear_goal=clear_goal, clear_mover=clear_mover, clear_then=clear_then, clear_wait=clear_wait, draft=draft, clear_draft=clear_draft, clear_next=clear_next, clear_check=clear_check,
                       done=done, dropped=dropped, step_proof=step_proof, watch_reason=watch_reason, wait_reason=wait_reason, outcome_text=outcome_text, contact=contact, reword=reword, fixes=fixes, waits=waits, wait_mode=wait_mode,
                       **({"busy_note": busy_note} if busy_note is not None else {})) + fix_note
        if alias_used:
            out += _uw.alias_note(alias_used, _model.clean(alias_date), alias_ends, _backstop_field(item_id, status))
        return out + note + _off_map_note_item(sender, item_id, project) + _ask_after_write(ask_pre, sender, ask, clear_ask or ask.strip().lower() in _ASK_NONE, _ask_write_texts(locals()))


def register(mcp, *, ask_after_write, sender_not_owner, update, busy_live=None) -> None:
    """Adds the tool of this module to `mcp`, and takes the server's callables the bodies use."""
    global _ask_after_write, _sender_not_owner, _update, _busy_live
    _busy_live = busy_live
    _ask_after_write = ask_after_write
    _sender_not_owner = sender_not_owner
    _update = update
    mcp.tool(name="update", description=_lead(_T.description("update")))(stackshot_update)
