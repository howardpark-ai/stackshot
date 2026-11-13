"""create.py: the `create` tool: a new board item, its text, parameters and the call into the create service."""
from __future__ import annotations

from typing import Annotated, Any

from fastmcp.exceptions import ToolError
from pydantic import Field

from stackshot.core import config as _cfg
from stackshot.core.instance import OWNER
from stackshot.service import create as _create_svc, gates as _gates, writes as _writes
from stackshot.waits import waiting as _wt
from stackshot.web.auth import oauth as _oauth
from stackshot.web.tools.notes import _OFF_MAP_NOTE, _off_map_note, _owner_param
from stackshot.web.tools.text import _AFTER_PARAM, _CHECK_FORM, _CHECK_PARAM, _CONTACT_FORM, _CONTACT_PARAM, _DESCRIPTION_PARAM, _DRAFT_FORM, _ITEM_FORM, _MACHINE_FORM, _MODEL_FORM, _MODEL_PAGE, _MOVER_PARAM, _NEEDS_FORM, _OPTIONS_PARAM, _POST_WAKE_PARAM, _SAID_PARAM, _SELF_WAIT_FORM, _STEP_PROOF_FORM, _STEP_PROOF_PARAM, _THEN_PARAM, _WAIT_EVENT_PARAM, _WAIT_KIND_PARAM, _lead

_evwait_preread = None      # set by register: the server's own, looked up at each call
_sender_not_owner = None      # set by register: the server's own, looked up at each call


_PFX = " or ".join(f"'{p}…'" for p in _cfg.CFG["subject"]["prefixes"])
_PFX0 = str(_cfg.CFG["subject"]["prefixes"][0])      # the first scope prefix, for the worked example in create's text


# The trailers: a session's write that carries his word on the item
# passes `said`, his sentences cut verbatim with a pointer to his message (the transcript entry's uuid and the session it is
# in), under the Linux kernel's tags. The server checks the quote against that transcript on the box (said.py) and refuses the
# write when a readable transcript fails it; a transcript it cannot read stores the entry unchecked. The item page shows the
# words, with "Acked-by: the owner <link>" and never the quote (no issue comment carries them since an earlier change). His questions are not
# posted: the board gets conclusions.
_SAID_FORM = (
    f"said: {OWNER}'s own words {{tag: Acked-by | Suggested-by | Reported-by, quote, msg, session}} (quote verbatim, msg the uuid of his message's transcript entry; checked against that transcript, refused when it does not match; post his conclusions, never his questions), "
    "or proof he did a step {kind: acted, quote, msg, session} with no tag (a message he sends while your session is working is an attachment entry, type queued_command, origin human: msg is that entry's uuid, quote a piece of its attachment.prompt; stored as Done-by, kind acted, and counts only as proof of steps he did within 24 hours after its date). "
)


# What an item waits on: every open item has a mover, whatever wait it is in (waiting.py); no date is derived for it.
_CAP_FORM = (
    f" A wake runs at most {_wt.cap_days():g} days from the item's last move: a wake further out is refused without {OWNER}'s words. A due date is a deadline and is accepted as it is. "
)
_AGENT_DUE_FORM = (
    " Agent work carries no expected time: a create sets none, and the item shows how long its work has run. "
    "Doing is work in hand (a session building, running tests, reviewing, a release running); a wait on a date, a timer, another release or someone else's step is not doing: park it with "
    "update(until=\"YYYY-MM-DD\" or \"YYYY-MM-DDTHH:MM\"), adding wait_basis=\"<what it waits for, with its date YYYY-MM-DD>\" when the date is past the cap, or after=[\"board#N\"], or wait_kind=\"relay\" with wait_event, ask_by and needs=[\"external\"]. "
    "A bare date (until, or its old name wake) is a wait until then and the board lists the item as waiting; the exception is a write that hands the item to another session, where the date is only that hand-off's backstop and is no wait (unless the item carries hold, wait_kind, wait_basis or an after link, in this call or stored by an earlier one: then the date stays a wait). "
    f"A stored doing item whose wake (one it still carries from before until) is more than {_wt.dated_wait_min_hours():g} hour(s) away (`[waiting] dated_wait_min_hours`) while every open step of its next is dated for that day or later is listed as waiting too "
    "(one undated step means it can act now): date a step only when it really cannot run before then; the daily audit asks the item's mover why such a step cannot run now. "
)


_ASK_BY_PARAM_NEW = Annotated[str, Field(description="The old name of until, accepted for now: the day a wait on another item, a relay or an event comes back to someone if it has not ended, YYYY-MM-DD, tomorrow at the earliest: ask_by=\"2099-03-02\".")]      # create: nothing is stored yet to move later, and create has no wake


_UNTIL_PARAM_NEW = Annotated[str, Field(description="The one date the new item's wait ends on, in the future: YYYY-MM-DD, or YYYY-MM-DDTHH:MM, in the board timezone (a relay or event wait takes the day alone, YYYY-MM-DD). wait_kind goes only beside it (none: the date alone). It replaces ask_by, still accepted for now.")]


_NEXT_CREATE_PARAM = Annotated[str, Field(description="The checklist, one step per line, each opening with who takes it: next=\"my-x: open the PR\" (or several lines with \\n). Results and PRs go on the project page, never in next.")]


_ASK_PARAM_NEW = Annotated[str, Field(description="The one line a needs=decision item carries, at most 240 characters: ask=\"Decide: whether to approve the sample schema · Recommend: Approve · Stakes: waiting a week delays the demo · By: Mon Jun 8th 2099\" (By is a date in words, or no date). A real choice, not \"have you done X?\"; one decision per ask. With no options listed the Recommend is a yes or a no. Name who acts (a person or a session name) in every option, never I, you, we, us or me; the ask line never says I, you or me.")]      # create: no ask exists yet to withdraw, and create has no clear_ask


_CREATE_DESC = (
    f"Create a board item: something {OWNER} would ask \"is X done?\" about (a deliverable a session owns, a decision or input he must give, a blocker on someone outside, a handoff between sessions), never a working step.{_OFF_MAP_NOTE}. "
    "Right calls (sender = you, the creator, required; project = an existing gbrain page, projects/<slug> or infra/<slug>): "
    f"own work: create(project=\"projects/widgets\", subject=\"{_PFX0}Make the export finish in under a minute\", sender=\"my-x\", mover=\"my-x\", description=\"- Goal: the export finishes in under a minute\\n- Problem: the nightly run takes 9 minutes\", next=\"my-x: profile the nightly run\"); "
    f"an item that needs {OWNER}'s call: the same call with no mover (he moves it) and needs=\"decision\", then=\"my-x\" (who takes it after his answer), ask=\"Decide: whether to approve the sample schema · Recommend: Approve · Stakes: waiting a week delays the demo · By: Mon Jun 8th 2099\", "
    "options=[{\"label\": \"Approve\", \"line\": \"Approve the schema\", \"recommended\": true}, {\"label\": \"Decline\", \"line\": \"Wait a week\", \"recommended\": false}]; "
    "a step that waits on another item: next=\"my-x: ship the export once board#N closes\", after=[\"board#N\"], ask_by=\"2099-03-02\"; "
    "work for the project's builder: leave mover out. "
    f"subject: {_PFX}, then the outcome wanted as a task, never a topic or a symptom (a subject with no scope prefix is given the one its project's scope names, and the reply says so). "
    "project must exist (create the page first; a page in a second brain is looked up in that brain's own copy, and taken unchecked while that copy cannot be read); a sub-page counts and shows on its hub's row. "
    "sender: your own session (a cloud/Cowork session's cse_… id, or a pane's name or transcript UUID); the server records it as the item's creator (a background agent may create items too). "
    "mover: who moves the item now (and then= after his answer or step); a front agent gets no hand-off notice, so a create from another session that sets mover, then or post_wake_mover to a front agent gets the project's builder instead (the reply and History say so; send the same value again to keep it as sent; with no builder it is refused, except a mover set by a front agent of the item's project to another of its front agents; message the front agent for a check or answer only it can give). "
    "With no mover= an alive item is moved by the project's builder (for a page the instance maps to a builder, that one when the project lists it), else its -main agent, never by its creator; "
    f"an item that waits on {OWNER}'s call (needs=decision with its ask) is taken after him by `then`, which defaults to the builder doing the work, not to the front agent that relayed it (a builder that files its own decision item is its own `then`). "
    f"An item created in his state (his step, or needs holding decision) has him as mover, and naming a session as mover beside that state is refused; mover={OWNER} on an item in none of his states is refused too (a create sets no state: he is the mover with needs=decision and its ask, else name a session as mover and put his part in a next line that starts `{OWNER}:`). "
    "A step of next that opens with a front agent (a session the owner talks to) is refused on an item another session moves: open it with the mover's name, or message the front agent. "
    "owner is not a parameter any more: it is still accepted for a few days with a note in the reply and then refused. owner_name: the sender's session title as claude.ai shows it, nothing appended. priority: p1 | p2 | p3, shown but not sorted. "
    + _ITEM_FORM + " " + _NEEDS_FORM + " " + _SAID_FORM + _CHECK_FORM + _STEP_PROOF_FORM + _CAP_FORM + _AGENT_DUE_FORM + _MODEL_FORM + _DRAFT_FORM + _SELF_WAIT_FORM + _MACHINE_FORM + _CONTACT_FORM
    + "The reply may end with a line listing up to 3 similar open or recently completed items: the create always goes through, so check them for a duplicate before working the new item. request_id: any random string of yours; a retry with the same one returns the item already created."
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
    wait_reason: Annotated[str, Field(description="What the step waits on that is not available now (a reply, a build or test still running, a window the work needs, a resource that is down), at least " + str(_cfg.WAIT_GUARD_REASON_MIN) + " characters. Required when this write sets a wake, or a line of your own next dated later than today, on an item you move: without it the write is refused, and a model may refuse it when the step could be done now. Not stored on the item. A park (hold=true with wait_basis), a wait on another item (after) and needs decision or external need none. A date after by, due or before is a deadline, not a wait.")] = "",
    contact: _CONTACT_PARAM = "",
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
    _gates.gate_self_wait("", owner, next_text=next, mover=mover, needs=needs, after=after, wait_kind=wait_kind, wait_reason=wait_reason, creating={"subject": subject, "project": project})   # before the item lock: it may ask a model
    _evwait_preread(wait_kind, wait_event)      # an event wait's facts (GitHub, git) are read before the item lock, not under it
    with _writes.session_write():
        return _create(subject=subject, description=description, project=project, owner=owner, next=next, needs=needs, priority=priority, due=due, anchors=anchors, request_id=request_id, owner_name=owner_name, ask=ask, options=options, agent=agent, observers=observers, after=after, said=said, check=check, goal=goal, mover=mover, then=then, wait_kind=wait_kind, wait_anchor=wait_anchor, wait_event=wait_event, ask_by=ask_by, until=until, post_wake_mover=post_wake_mover, draft=draft, step_proof=step_proof, contact=contact, fixes=fixes) + fix_note + note + _off_map_note(owner, project)


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
) -> str:
    """The create tool without its identity check (_who): the reply text of service/create.py's create_item."""
    return _create_svc.create_item(subject=subject, description=description, project=project, owner=owner, next=next, needs=needs, priority=priority, due=due, anchors=anchors, request_id=request_id, owner_name=owner_name, ask=ask, options=options, agent=agent, observers=observers, after=after, said=said, check=check, goal=goal, mover=mover, then=then, wait_kind=wait_kind, wait_anchor=wait_anchor, wait_event=wait_event, ask_by=ask_by, until=until, post_wake_mover=post_wake_mover, draft=draft, step_proof=step_proof, contact=contact, fixes=fixes)[1]


def register(mcp, *, evwait_preread, sender_not_owner) -> None:
    """Adds the tool of this module to `mcp`, and takes the server's callables the bodies use."""
    global _evwait_preread, _sender_not_owner
    _evwait_preread = evwait_preread
    _sender_not_owner = sender_not_owner
    mcp.tool(name="create", description=_lead(_CREATE_DESC))(stackshot_create)
