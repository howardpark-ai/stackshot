"""create.py: the `create` tool: a new board item, its text, parameters and the call into the create service."""
from __future__ import annotations

from typing import Annotated, Any

from fastmcp.exceptions import ToolError
from pydantic import Field

from stackshot.core import config as _cfg
from stackshot.core.instance import OWNER
from stackshot.service import create as _create_svc, gates as _gates, writes as _writes
from stackshot.waits import wait_list_write as _wlw, waiting as _wt
from stackshot.web.auth import oauth as _oauth
from stackshot.web.tools.notes import _off_map_note, _owner_param
from stackshot.web.tools.text import _AFTER_PARAM, _CHECK_PARAM, _CONTACT_PARAM, _DESCRIPTION_PARAM, _MODEL_PAGE, _MOVER_PARAM, _OPTIONS_PARAM, _POST_WAKE_PARAM, _SAID_PARAM, _STEP_PROOF_PARAM, _THEN_PARAM, _WAIT_EVENT_PARAM, _WAIT_KIND_PARAM, _WAIT_MODE_PARAM, _WAITS_PARAM, _lead, load_text

_evwait_preread = None      # set by register: the server's own, looked up at each call
_sender_not_owner = None      # set by register: the server's own, looked up at each call


_PFX = " or ".join(f"'{p}…'" for p in _cfg.CFG["subject"]["prefixes"])
_PFX0 = str(_cfg.CFG["subject"]["prefixes"][0])      # the first scope prefix, for the worked example in create's text
_T = load_text("create", {"DATED_WAIT_MIN_HOURS": f"{_wt.dated_wait_min_hours():g}", "PFX0": _PFX0, "PFX": _PFX})


_CAP_FORM = _T.piece("CAP_FORM")      # what an item waits on (read by the waiting scenario)


_ASK_BY_PARAM_NEW = Annotated[str, Field(description=_T.param("ASK_BY_PARAM_NEW"))]      # create: nothing is stored yet to move later, and create has no wake


_UNTIL_PARAM_NEW = Annotated[str, Field(description=_T.param("UNTIL_PARAM_NEW"))]


_NEXT_CREATE_PARAM = Annotated[str, Field(description=_T.param("NEXT_CREATE"))]


_ASK_PARAM_NEW = Annotated[str, Field(description=_T.param("ASK_PARAM_NEW"))]      # create: no ask exists yet to withdraw, and create has no clear_ask


_CREATE_DESC = (
    _T.description("create")
)


def stackshot_create(
    subject: str,
    description: _DESCRIPTION_PARAM,
    project: str,
    owner: str = "",
    next: _NEXT_CREATE_PARAM = "",
    needs: list[str] | str = "",
    priority: str = "",
    due: str = "",
    anchors: list[str] | None = None,
    request_id: str = "",
    owner_name: str = "",
    ask: _ASK_PARAM_NEW = "",
    options: _OPTIONS_PARAM = None,
    agent: str = "",
    observers: list[str] | str = "",
    after: Annotated[list[str] | str, Field(description=_AFTER_PARAM.__metadata__[0].description)] = "",
    said: Annotated[list[dict[str, Any]] | str | None, Field(description=_SAID_PARAM)] = None,
    check: _CHECK_PARAM = "",
    goal: str = "",
    mover: _MOVER_PARAM = "",
    then: _THEN_PARAM = "",
    wait_kind: _WAIT_KIND_PARAM = "",
    wait_anchor: str = "",
    wait_event: _WAIT_EVENT_PARAM = "",
    ask_by: _ASK_BY_PARAM_NEW = "",
    until: _UNTIL_PARAM_NEW = "",
    post_wake_mover: _POST_WAKE_PARAM = "",
    sender: str = "",
    draft: str = "",
    step_proof: _STEP_PROOF_PARAM = None,
    wait_reason: Annotated[str, Field(description=_T.param("wait_reason"))] = "",
    contact: _CONTACT_PARAM = "",
    waits: _WAITS_PARAM = None,
    wait_mode: _WAIT_MODE_PARAM = "",
) -> str:
    _oauth._who()
    note = _owner_param("create", owner)           # step 4b: owner is accepted with a note until [model] owner_param_until, then refused
    _sender_not_owner(sender)
    owner = str(sender or "").strip() or str(owner or "").strip()    # the creator: the record's keeper
    if not owner:
        raise ToolError("Refused: pass sender=<your own session name or id>: the server records the sender as the item's creator. "
                        f"Say who moves the item with mover=<a session, {OWNER} or the project's background agent>. The item model: {_MODEL_PAGE}.")
    fixes: list[tuple[str, str, str]] = []; fix_note = ""
    vals = {"mover": mover, "then": then, "post_wake_mover": post_wake_mover}
    for f_, v_ in list(vals.items()):
        vals[f_], n_, fx_ = _gates.fix_front_mover(f_, v_, owner, project, "", None)       # a front agent gets no hand-off notice: another session's value becomes the project's builder, and the reply says so
        fix_note += n_; fixes += fx_
    mover, then, post_wake_mover = vals["mover"], vals["then"], vals["post_wake_mover"]
    _gates.gate_self_wait("", owner, next_text=next, mover=mover, needs=needs, after=after, wait_kind=_wlw.judged_as(waits) if _wlw.passed(waits) and not _wlw.clearing(waits) else wait_kind, wait_reason=wait_reason, creating={"subject": subject, "project": project})   # before the item lock: it may ask a model; a list names its blockers (its lines that are not dates)
    _evwait_preread(wait_kind, wait_event)      # an event wait's facts (GitHub, git) are read before the item lock, not under it
    for phrase_ in _wlw.event_phrases(waits):      # …and those of every event line of a list
        _evwait_preread("event", phrase_)
    with _writes.session_write():
        return _create(subject=subject, description=description, project=project, owner=owner, next=next, needs=needs, priority=priority, due=due, anchors=anchors, request_id=request_id, owner_name=owner_name, ask=ask, options=options, agent=agent, observers=observers, after=after, said=said, check=check, goal=goal, mover=mover, then=then, wait_kind=wait_kind, wait_anchor=wait_anchor, wait_event=wait_event, ask_by=ask_by, until=until, post_wake_mover=post_wake_mover, draft=draft, step_proof=step_proof, contact=contact, fixes=fixes, waits=waits, wait_mode=wait_mode) + fix_note + note + _off_map_note(owner, project)


def _create(
    subject: str,
    description: str,
    project: str,
    owner: str,
    next: str = "",
    needs: list[str] | str = "",
    priority: str = "",
    due: str = "",
    anchors: list[str] | None = None,
    request_id: str = "",
    owner_name: str = "",
    ask: str = "",
    options: list[dict[str, Any]] | str | None = None,
    agent: str = "",
    observers: list[str] | str = "",
    after: list[str] | str = "",
    said: list[dict[str, Any]] | str | None = None,
    check: str = "",
    goal: str = "",
    mover: str = "",
    then: str = "",
    wait_kind: str = "",
    wait_anchor: str = "",
    wait_event: str = "",
    ask_by: str = "",
    post_wake_mover: str = "",
    draft: str = "",
    step_proof: list[dict[str, Any]] | str | None = None,
    contact: str = "",
    fixes: "list[tuple[str, str, str]] | None" = None,
    until: str = "",
    waits: list[dict[str, Any]] | str | None = None,
    wait_mode: str = "",
) -> str:
    """The create tool without its identity check (_who): the reply text of service/create.py's create_item."""
    return _create_svc.create_item(subject=subject, description=description, project=project, owner=owner, next=next, needs=needs, priority=priority, due=due, anchors=anchors, request_id=request_id, owner_name=owner_name, ask=ask, options=options, agent=agent, observers=observers, after=after, said=said, check=check, goal=goal, mover=mover, then=then, wait_kind=wait_kind, wait_anchor=wait_anchor, wait_event=wait_event, ask_by=ask_by, until=until, post_wake_mover=post_wake_mover, draft=draft, step_proof=step_proof, contact=contact, fixes=fixes, waits=waits, wait_mode=wait_mode)[1]


def register(mcp, *, evwait_preread, sender_not_owner) -> None:
    """Adds the tool of this module to `mcp`, and takes the server's callables the bodies use."""
    global _evwait_preread, _sender_not_owner
    _evwait_preread = evwait_preread
    _sender_not_owner = sender_not_owner
    mcp.tool(name="create", description=_lead(_CREATE_DESC))(stackshot_create)
