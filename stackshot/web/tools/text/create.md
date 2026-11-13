## text SAID_FORM trail
said: {{OWNER}}'s own words {tag: Acked-by | Suggested-by | Reported-by, quote, msg, session} (quote verbatim, msg the
uuid of his message's transcript entry; checked against that transcript, refused when it does not match; post his
conclusions, never his questions), or proof he did a step {kind: acted, quote, msg, session} with no tag (a message he
sends while your session is working is an attachment entry, type queued_command, origin human: msg is that entry's
uuid, quote a piece of its attachment.prompt; stored as Done-by, kind acted, and counts only as proof of steps he did
within 24 hours after its date).

## text CAP_FORM lead trail
A wake runs at most {{CAP_DAYS}} days from the item's last move: a wake further out is refused without {{OWNER}}'s
words. A due date is a deadline and is accepted as it is.

## text AGENT_DUE_FORM lead trail
Agent work carries no expected time: a create sets none, and the item shows how long its work has run. Doing is work
in hand (a session building, running tests, reviewing, a release running); a wait on a date, a timer, another release
or someone else's step is not doing: park it with update(until="YYYY-MM-DD" or "YYYY-MM-DDTHH:MM"), adding
wait_basis="<what it waits for, with its date YYYY-MM-DD>" when the date is past the cap, or after=["board#N"], or
wait_kind="relay" with wait_event, ask_by and needs=["external"]. A bare date (until, or its old name wake) is a wait
until then and the board lists the item as waiting; the exception is a write that hands the item to another session,
where the date is only that hand-off's backstop and is no wait (unless the item carries hold, wait_kind, wait_basis or
an after link, in this call or stored by an earlier one: then the date stays a wait). A stored doing item whose wake
(one it still carries from before until) is more than {{DATED_WAIT_MIN_HOURS}} hour(s) away (`[waiting]
dated_wait_min_hours`) while every open step of its next is dated for that day or later is listed as waiting too (one
undated step means it can act now): date a step only when it really cannot run before then; the daily audit asks the
item's mover why such a step cannot run now.

## param ASK_BY_PARAM_NEW
The old name of until, accepted for now: the day a wait on another item, a relay or an event comes back to someone if
it has not ended, YYYY-MM-DD, tomorrow at the earliest: ask_by="2099-03-02".

## param UNTIL_PARAM_NEW
The one date the new item's wait ends on, in the future: YYYY-MM-DD, or YYYY-MM-DDTHH:MM, in the board timezone (a
relay or event wait takes the day alone, YYYY-MM-DD). wait_kind goes only beside it (none: the date alone). It
replaces ask_by, still accepted for now. Beside waits it is the list's backstop day, required.

## param NEXT_CREATE
The checklist, one step per line, each opening with who takes it: next="my-x: open the PR" (or several lines with \n).
Results and PRs go on the project page, never in next.

## param ASK_PARAM_NEW
The one line a needs=decision item carries, at most 240 characters: ask="Decide: whether to approve the sample schema
· Recommend: Approve · Stakes: waiting a week delays the demo · By: Mon Jun 8th 2099" (By is a date in words, or no
date). A real choice, not "have you done X?"; one decision per ask. With no options listed the Recommend is a yes or a
no. Name who acts (a person or a session name) in every option, never I, you, we, us or me; the ask line never says I,
you or me.

## param wait_reason
What the step waits on that is not available now (a reply, a build or test still running, a window the work needs, a
resource that is down), at least {{WAIT_GUARD_REASON_MIN}} characters. Required when this write sets a wake, or a line
of your own next dated later than today, on an item you move: without it the write is refused, and a model may refuse
it when the step could be done now. Not stored on the item. A park (hold=true with wait_basis), a wait on another item
(after) and needs decision or external need none. A date after by, due or before is a deadline, not a wait.

## description create
Create a board item: something {{OWNER}} would ask "is X done?" about (a deliverable a session owns, a decision or
input he must give, a blocker on someone outside, a handoff between sessions), never a working step.{{OFF_MAP_NOTE}}.
Right calls (sender = you, the creator, required; project = an existing gbrain page, projects/<slug> or infra/<slug>):
own work: create(project="projects/widgets", subject="{{PFX0}}Make the export finish in under a minute",
sender="my-x", mover="my-x", description="- Goal: the export finishes in under a minute\n- Problem: the nightly run
takes 9 minutes", next="my-x: profile the nightly run"); an item that needs {{OWNER}}'s call: the same call with no
mover (he moves it) and needs="decision", then="my-x" (who takes it after his answer), ask="Decide: whether to approve
the sample schema · Recommend: Approve · Stakes: waiting a week delays the demo · By: Mon Jun 8th 2099",
options=[{"label": "Approve", "line": "Approve the schema", "recommended": true}, {"label": "Decline", "line": "Wait a
week", "recommended": false}]; a step that waits on another item: next="my-x: ship the export once board#N closes",
after=["board#N"], ask_by="2099-03-02"; work for the project's builder: leave mover out. subject: {{PFX}}, then the
outcome wanted as a task, never a topic or a symptom (a subject with no scope prefix is given the one its project's
scope names, and the reply says so). project must exist (create the page first; a page in a second brain is looked up
in that brain's own copy, and taken unchecked while that copy cannot be read); a sub-page counts and shows on its
hub's row. sender: your own session (a cloud/Cowork session's cse_… id, or a pane's name or transcript UUID); the
server records it as the item's creator (a background agent may create items too). mover: who moves the item now (and
then= after his answer or step); a front agent gets no hand-off notice, so a create from another session that sets
mover, then or post_wake_mover to a front agent gets the project's builder instead (the reply and History say so; send
the same value again to keep it as sent; with no builder it is refused, except a mover set by a front agent of the
item's project to another of its front agents; message the front agent for a check or answer only it can give). With
no mover= an alive item is moved by the project's builder (for a page the instance maps to a builder, that one when
the project lists it), else its -main agent, never by its creator; an item that waits on {{OWNER}}'s call
(needs=decision with its ask) is taken after him by `then`, which defaults to the builder doing the work, not to the
front agent that relayed it (a builder that files its own decision item is its own `then`). An item created in his
state (his step, or needs holding decision) has him as mover, and naming a session as mover beside that state is
refused; mover={{OWNER}} on an item in none of his states is refused too (a create sets no state: he is the mover with
needs=decision and its ask, else name a session as mover and put his part in a next line that starts `{{OWNER}}:`). A
step of next that opens with a front agent (a session the owner talks to) is refused on an item another session moves:
open it with the mover's name, or message the front agent. owner is not a parameter any more: it is still accepted for
a few days with a note in the reply and then refused. owner_name: the sender's session title as claude.ai shows it,
nothing appended. priority: p1 | p2 | p3, shown but not sorted. {{ITEM_FORM}} {{NEEDS_FORM}}
{{SAID_FORM}}{{CHECK_FORM}}{{STEP_PROOF_FORM}}{{CAP_FORM}}{{AGENT_DUE_FORM}}{{MODEL_FORM}}{{DRAFT_FORM}}{{SELF_WAIT_FORM}}{{MACHINE_FORM}}{{CONTACT_FORM}}The
reply may end with a line listing up to 3 similar open or recently completed items: the create always goes through, so
check them for a duplicate before working the new item. request_id: any random string of yours; a retry with the same
one returns the item already created.
