## text NEEDS_FORM
needs: whose move it is now, a list: "decision" ({{OWNER}}'s: decide, judge, review, give the go-ahead), "external"
(someone outside, named in next) and session names (a background agent of any project, or the item's one mover; a
user-facing agent that is not the mover is refused: its part becomes its own item, linked with after=), e.g.
needs=["decision", "my-engineer"] or one comma-separated string. An item has one mover: a session named that is not a
background agent of the item's project counts as a mover, and two of them, or decision beside one, are refused (name
the one who moves it now, and who takes it after his answer in then=); a background agent of this project never counts
as a second mover; empty means the item's mover (mover=, else the project's builder, else its -main agent) moves it.
The lane follows the first of decision, external, a session (your call · on others · on agent). A session named is
told when added, is asked about the item at each turn end and hears its wake, recycle and after notices; it passes
sender=<its name> on its writes, so that they reach the mover as another session's. needs= replaces the whole list
(name again what should stay); needs="none" or clear_needs=true empties it. decision vs your-step: needs=decision is
{{OWNER}}'s call, a choice between options; a thing that is {{OWNER}}'s own to do is step=<his action> (update; a
create has no step), and the board ticks it when he says it is done, so an ask that only asks whether he has done it
is refused. agent=<session> is the older form: it makes that session the one named in needs (the decision and external
entries stay); agent="none" takes the sessions out. observers: sessions that hear only a close or a reopen;
observers="none" clears. after: items of any project that must close first (after=["board#N"]); while one is open the
item counts as waiting without a hold, and when the last one closes it wakes and the sessions in its needs (else its
mover) are told; a dropped one releases it too, a superseded one is followed to its replacement; a loop is refused;
after="none" clears. after is for a real dependency (this item needs that one's output), never for the order a builder
takes its items in. A hold (hold=true) names what it waits for (a wake, after items, a notice from an anchor scoped to
the item, a recycle, or a wait_basis window the work itself needs); one with none is refused. A wake (or until)
without hold=true is a wait: the item is listed as waiting until that date (a wake past the cap takes a wait_basis);
in an update that hands the item to another session it is only the hand-off's backstop and the item stays active
(unless the item carries hold, wait_kind, wait_basis or an after link, in this call or stored by an earlier one: then
the date stays a wait). An item waiting on {{OWNER}} is never on hold: it carries needs=decision with its ask, or
after=<the item that carries the ask>. needs names only who can move now. An item that waits on {{OWNER}} and on a
session at once: where his answer could change with the session's work, or its work with his answer, the session goes
first and adds decision when it is done (or the decision is its own item, linked with after=); decision sits beside
this project's background agents only when the two are independent (beside any other session it is refused), and when
unsure, in sequence. When decision leaves needs (he has decided), the sessions still named are told at once; a session
whose work changes the question rewrites the ask. The server never hands an item to a front agent on its own motion:
when the item is back with its front agent mover alone, the project's builder is told instead.

## text ANCHOR_SHAPES
Slack channel/DM, Drive file/folder, Gmail thread, gmail:q:<query> or gmail:q@<mailbox>:<query>, Notion page or
database, GitHub issue/PR, …/releases or a repo root

## text NEXT_WORDS
the item's checklist: one step per line, in order, opening with who takes it (`<session>:`, `{{OWNER}}:` or the
outside party's name; a role may follow the name, `my-x (builder):`; a space follows the colon); a line naming no one
(`Status:`) is refused, and a `- ` line under a named step belongs to it. {{OWNER}}'s steps are made by the server
from the ask and the step and ticked by his answer: never write or mark them. Mark your step done=[n] when it is done
and dropped=[n] when it is no longer wanted; never reword an open step to add progress, and a parked item still has
the open step its wake leads to. Results, PRs, commit ids and test counts go on the project page, never in next.

## text NEXT_REFUSALS trail
A session's writes are refused: (1) a line of next that opens with no `<actor>:` (right: `my-x: open the PR`, or an
outside party, `Acme support: reply on the invoice`; `Status:` and `Note:` are no actor, `my-x:do` with no space after
the colon is refused); (2) on an update, an open step reworded in next alone (its text with words added, the old step
left unmarked): keep the step as it is, mark it done=[n] when the work is finished, or write a different action as a
new line (a step marked dropped=[n] may be replaced by a longer one); progress goes on the project page, never in a
step (to give an open step other words, pass reword={n: "<new text>"}); (3) a write that leaves an item that stays
open with no open step in next: name who takes the next step, keep one open step (a held item's is the one its wake
leads to), or close the item with complete, which is exempt; {{OWNER}}'s server-made step counts. A step with a commit
id, a test count, a merged, live or deployed status or a "since 09:30" stamp is written all the same and the reply
notes it.

## text ITEM_FORM
subject (a create's, or one an update sets): the outcome wanted ("Make X work when Y"), never the symptom ("X fails
when Y"); at most {{SUBJECT_MAX}} characters, the scope prefix counted; a longer one is refused: the rest goes in the
description bullets. An update that leaves subject out, or sets the one it has, is never refused for a stored long
subject. description: the item's background as short `- ` bullets of live state, one fact each, at most
{{DESC_MAX_LINES}} lines of {{DESC_LINE_MAX}} characters each (a link counts by its text); the server refuses prose, a
longer line and more lines; never a paragraph. The first bullet opens `Goal:` (case-sensitive) with the outcome wanted
in a sentence (the subject names the same outcome); a symptom, cause or trigger goes in a later bullet that opens
`Problem:`. Then what the item is and where it lives (his words as a bullet such as `- {{OWNER}}: …`; parallel bullets
go under one parent bullet, indented two spaces); never steps or commands for {{OWNER}} (those go in step, below), no
working notes, status or history; prune what is no longer live; details go on the project page. A create, or an update
that replaces the description, whose first bullet does not open `Goal:` is refused; an update that leaves description
out is never judged. Example: description="- Goal: the export finishes in under a minute\n- Problem: the nightly run
takes 9 minutes\n- Lives in export.py". Item text renders as markdown (nested `- ` lists, **bold**, `code`, > quotes;
no raw HTML, headings or tables). next: {{NEXT_WORDS}} {{NEXT_REFUSALS}}A line of next is refused unless it is <=
{{NEXT_LINE_MAX}} characters after its `<actor>: ` prefix, and <= {{NEXT_LINE_FULL}} in all (a link counts by its
text); only the text you write in a call is checked. Each line remembers the session whose write put it there, and a
later update changes only its own sender's lines. A command {{OWNER}} runs goes in a next line that starts
`{{OWNER}}:`, whole in backticks, never in the description or in the step (step=…: a one-line summary, see step
below); his item page shows it in Your step as its own block with a copy button. A next line that starts
`{{OWNER}}:`{{ALIAS_PAREN}} and asks him to run something (an imperative run cue such as run, type, execute, enter, or
a place phrase such as {{P_EX}}; a line where someone else runs it, "say go and I will run …", is not a cue) gets the
command check{{P_CHK}} on create and update, refused as `next line: …`, and only for the lines the call sets: the
command goes in backticks or a fence{{P_RUN}}. A line that only mentions a command, and lines for other sessions, are
not checked. A `! ` line (a command typed into a pane) in a line that starts `{{OWNER}}:`, bare, in backticks or after
a colon or a run cue ("type ! cmd"), is refused whether or not the line asks him to run it: {{P_BANG}}; "done!" is not
a `! ` line. A first line of next that starts `{{OWNER}}:` (or {{OPENERS_TXT}}, "{{OWNER}} to …") on an item that is
doing, blocked or verifying is refused when the call sets next, needs or the step: set step=<his step in one line>, or
needs=decision with an ask (a create has no step). A next line that defers on another item in words (once, after,
when, until or before, then a board#N; the words of [keywords.model_guards] defer_after_id also count) is refused
unless after=["board#N"] names that item in the same item, since a wait written only in words wakes nobody when the
item closes; give the wait its end too, ask_by=YYYY-MM-DD, the day it comes back to someone if board#N is still open
(supplies=<what that item's output gives this one>). Right: next="my-x: ship the export once board#N closes",
after=["board#N"], ask_by="2099-03-02". Only the lines the call sets are checked; a line that only mentions an item
("see board#N") is not a deferral; on an item waiting on his call (needs=decision) write "see board#N", not after=;
wake=YYYY-MM-DD is the way to be reminded on a day. Links sit on the words (`blocked on [#7](url)`), never a naked URL
or a bare id: a naked http(s) URL in description, next or ask is refused, write `[words](url)` (a code span or fence
is fine). needs: whose move it is now (the list is described below). due: YYYY-MM-DD {{TIMEZONE}}, set only from a
real deadline ({{OWNER}}'s word, an outside date, or a date a dependency fixes), otherwise left empty: a made-up date
reads to {{OWNER}} as their own deadline (to expect something back by a date, use a wake). ask: the line a
needs=decision item carries, written so {{OWNER}} can decide from it alone and refreshed whenever the question moves,
one line of at most 240 characters, "Decide: <what to decide> · Recommend: <your recommendation> · Stakes: <what
happens either way> · By: <a date in words such as Mon Jun 8th 2099, or no date>"; example: ask="Decide: whether to
approve the sample schema · Recommend: Approve · Stakes: waiting a week delays the demo · By: Mon Jun 8th 2099",
options=[{"label": "Approve", "line": "Approve the schema", "recommended": true}, {"label": "Decline", "line": "Wait a
week", "recommended": false}]. An ask that only confirms {{OWNER}}'s own action is refused ("have you done X?", a bare
"is it done?", or a Decide part that names the action of his own `{{OWNER}}:` next lines, such as "Decide: install the
apps and delete the test repo?"): use step="<his action>" instead (on a create, set it by update after); a real choice
between alternatives, a judgement ("have you decided …", "does it work for you?") and an Approve/Decline go-ahead stay
decisions. One decision per item: an ask that packs several decisions, or points at choices by a number or letter code
the item does not spell out (“choices 2-3”, “2b”), is refused. Split it into one item per decision and write each
option out in words in the ask or the description, so that {{OWNER}} can decide from the item page alone. A decision
to change wording quotes the current and the proposed text, labeled before and after, in the description or the
options' lines. A needs=decision item whose description or next links a mockup (a https://claude.ai/artifact/… page,
or a /mockup/<n> page of the fleet tool's web UI (host set in the instance config)) puts [mockup](<that link>) in the
ask's Decide part too, or the write is refused: the home row and the item page show it as Mockup ↗ beside the
question. A mockup link goes in the ask only, never in an option: an option label or line holding a markdown link or
an http(s) URL is refused. A command for {{OWNER}} to run, or a paste, belongs on the item: in next when it is short
(a code span), otherwise on the project page, with next linking to it. options: when the decision is a pick between
alternatives, list them, each on one line, {{OPT_FORM}}; the ask's Recommend names the recommended one's label. The
server refuses a needs=decision item whose ask or description names alternatives while it lists none: words such as
"which of the two", "pick one", "x, y or z", "x vs y", "Option A", and labeled choices in the Decide part ("A or B",
"A (…) or B (…)", "A: … or B: …"); put each alternative in as one option, or the page draws only Yes / No for it. A
needs=decision item with no options whose Decide part opens with what, which, how, who, when, where or why is refused
(create; an update that sets the ask or options or puts it on his call), since Yes / No cannot answer it: list its
answers as options or reword it as a yes/no ("Decide: whether to …"). The same goes for a needs=decision item with no
options whose Recommend part is not a yes or a no (it names a person, a topic, a date, whatever the Decide part's
wording or language), since the page draws only Yes / No under it: put the choices as options, or make it a yes/no
question with a Recommend of yes or no. Name who acts in every option label and line ({{OWNER}}, a session's name, a
role), never "I", "you", "we", "us" or "me"; the ask line likewise never says "I", "you" or "me" (the reply notes one;
write "Pat unpublishes", not "I unpublish"). A yes/no decision lists two options, "Approve" and "Decline" (the one you
recommend marked recommended: true), so {{OWNER}} gets one-click buttons. options="none" clears them (refused while
the ask is an open question). Write the project page first, then the board: a page write up to five minutes before the
change counts.

## text SAID_PARAM
A list of entries, two kinds. (1) His own words {tag: Acked-by (his decision) | Suggested-by (his idea or request) |
Reported-by (a problem he reported), quote: his words verbatim, msg: the uuid of his message's transcript entry,
session: the session that heard him (default: you)}; it is checked against that transcript and the write is refused
when it does not match. Post his conclusions, never his questions. (2) Proof he did a step {kind: "acted", quote, msg,
session} with no tag: a message he sends while your session is working is an attachment entry (type queued_command,
origin human): msg is that entry's uuid, quote a piece of its attachment.prompt verbatim; any other entry is refused.
It is stored as Done-by, kind acted, and counts only as proof of steps he did within 24 hours after its date, never as
his words or his decision.

## text CHECK_FORM trail
check: what closes this item once the work handed to another session is done, a check the server runs itself every
minute and, when it passes, closes the item with outcome done and a reason naming the check: pr_merged
<owner>/<repo>#<n> (the pull request is merged), item_closed <id> (that board item is completed), lane <session>
<lane> (the fleet tool's lane record puts that pane on that lane; only where one is configured), unit_active
<unit>.service (the systemd user unit is active on the server box); nothing else, never a command. A check the server
cannot read (GitHub down, a unit not found) never closes. A release of a pull request of the board's own repository
needs no check: once main's full run passed on its merge and that merge is in the last-good commit and the live
checkout, the server ticks a step that says it releases that PR (`release PR #<n>`, `release #<n>`, or `release`
before the PR's URL; the step events, below, say what counts), only on an item anchored to that PR or naming its URL.
An item whose only open steps are that release is completed, outcome done; on an item with any other open step the
release step is ticked done and the mover told once. A step that only mentions the PR (investigate, review, verify) is
never ticked and never closes the item. An item on hold, or whose needs name his decision or a session other than its
mover, is left alone; a check that passes while the item waits on his decision does not close it until the decision is
cleared. An update whose next hands the work to another session (a line of next in the form `<session>: <action>`, a
list marker before the name at most: any session but the item's mover and you, not one already in needs; a name
elsewhere, in a slug, a link or a sentence, hands nothing over) is refused unless the item carries a check or a wake
(or until), the hand-off's backstop: with a hand-off the date is no wait (unless the item carries hold, wait_kind,
wait_basis or an after link, in this call or stored by an earlier one: then the date stays a wait), the item stays
active in the new mover's lane; a write that leaves an existing hand-off as it was is not asked again. Right:
update(item_id="board#N", sender="my-x", next="other-x: build the export", check="pr_merged acme/widgets#12"). A front
agent is the exception: its hand-off needs neither (a check stays allowed to anyone), because a front agent does not
watch handed-off work itself: the result lands through stackshot when the mover closes the item or hands it back to
you, so a front agent's own wake or until date (no hold) on an alive item another session moves is refused (a done
check, a park with its wake and ask_by stay allowed). To watch anyway, pass watch_reason=<why no push reaches you> (at
least 15 characters) on update, in the same call; it is recorded on the item. check="none" clears it; a check alone
owes no page. A check does not set the item's due time.

## text MODEL_FORM lead trail
The item model (design: docs/design): an item is dead (closed), alive (someone in the perimeter is working: one mover)
or waiting (nothing happens until something outside arrives). mover is how an item says whose move it is (the sender
of a create is recorded as its creator). Optional fields, stored as given (each parameter says how it is set):
goal=<the end-state in one sentence, what {{OWNER}} would ask "is it done?" about>; mover=<who moves an alive item
now: {{OWNER}}, a session name or the project's background agent; a front agent (a session {{OWNER}} talks to) only by
itself: a create or update from another session that sets mover to one gets the project's builder instead, and the
reply and History say so (send the same mover again to keep it; with no builder it is refused)>; then=<who takes it
after {{OWNER}}'s answer or step; then=<front agent> from another session gets the builder the same way>;
wait_kind=time | anchor | item | relay | event; wait_anchor=<url of the anchor an anchor wait watches>, which must be
on the project's anchors list first (add it with the anchors tool, scoped to this item), else the write is refused;
wait_event=<what you expect there (an anchor wait), or the party or event {{OWNER}} relays (a relay wait), or the
fleet event an event wait watches: {{EVENT_FORMS}}>; ask_by=YYYY-MM-DD (a relay wait's end day; an event, item or
anchor wait's backstop day, as a wake is); post_wake_mover=<who moves it when the wait ends; a front agent only by
itself, as for mover>. An event wait is how an item whose mover waits in the background for something the fleet does
says so: update(wait_kind="event", wait_event="pr_released <n>" (this repository's pull request number), ask_by=<the
day it comes back anyway, required>, post_wake_mover=<who takes it then>). Live for now: pr_released, pr_merged,
box_online, recycle, and every fleet_op form (any verb, any, many); a job_run wait turns only on its backstop day.
box_online <machine> waits for a machine to be online (its puller checking in, within the minutes the server counts as
online): the server reads it itself and the item turns within a minute or two of the machine's return, so an item
waiting on a date for an offline machine says wait_event="box_online <machine>" with that date as ask_by instead; the
machine must be one the fleet knows (an unknown name is refused with the known ones). The backstop must be after now,
and a day (ask_by=YYYY-MM-DD) falls due at 00:00 of that day in the instance timezone, so today's date is already
past: give tomorrow at the earliest (a relay or event wait takes the day alone, with no time of day). A wait for
something that has already happened (a PR already merged or live, a machine already online) is refused; a recycle wait
never asks for a recycle (it waits for the next one). A step of his, or needs holding decision, makes him the mover: a
write that names a session as mover beside it is refused (leave mover out, or mover={{OWNER}}, and put the session in
then). The mirror is refused too: a write that leaves an open item with mover={{OWNER}} but in none of his states, so
it has no step and no ask, is refused: pass step=<one line>, or needs=["decision"] with ask=…, or give the item to a
session (mover=<session>) and write his part in a next line that starts `{{OWNER}}:`. A waiting item, a close, a
rename, a priority or project write and a re-bullet are not judged by it. A wait that replaces his state drops the
mover and keeps then as the post-wake mover. "none" clears a field; clear_goal, clear_mover and clear_then clear
theirs, clear_wait the wait's five (wait_kind, wait_anchor, wait_event, ask_by, post_wake_mover). A close drops the
mover and the wait and keeps the goal. The wait ends by itself when its kind's event comes: a time at its wake; an
item when the last `after` item closes; an anchor when the anchor watcher's notice for wait_anchor reaches the server,
and any new notice at the anchor that reaches the server and passes the project's keeper wakes the item; an event when
the server is told of it; a relay on its ask_by day, when it comes to {{OWNER}} as a question (arrived / not yet, ask
again on a date / drop); a date beside it is its backstop. The item then turns alive with its post_wake_mover. A moved
ask_by or wake resets the backstop. Several waits at once are a list: waits (2 to 8 lines), wait_mode all | any, until as its backstop day; the item is
back when every line has arrived (all) or the first has (any), at its until at the latest. Example:
update(waits=[{"kind": "item", "after": "board#N"}, {"kind": "event", "event": "pr_merged <n>"}], wait_mode="any",
until="2099-03-02"). Send the lines that remain to edit it: one left is a single wait, waits=[] ends it.

## text MACHINE_FORM trail
A step of next that names a machine of the fleet which is offline now (its fleet name or hostname as a whole word, an
open step only) gets one `(note: …)` line in the reply when the item has no machine anchor for it and no box_online
wait on it, naming the fix: anchors(project=<its project>, add=["machine:<name>"], items=[<its id>]) tells the item's
mover each time that machine checks in again, without parking the item. A note, never a refusal.

## text SELF_WAIT_FORM lead trail
A wait on your own item names its blocker: when the item's mover (you) sets a wake, or writes a line of its own next
whose step is dated later than today (a date, "next week", "until Monday", "retry tomorrow", "after the weekend", "at
the next nightly run"; a date after by, due, before, target or ETA is a deadline, no wait; a day named about the past
is none), pass wait_reason=<what the step waits on that is not available now, at least {{WAIT_GUARD_REASON_MIN}}
characters> in the same call, or the write is refused. With a reason, one model call judges whether the step could be
done now: if it could, the write is refused with the model's reason, so do the step now or name the real blocker (a
reply, a build or test still running, a window the work itself needs, a resource that is down; a preference for a
scheduled run is none). The check passes the write when the model is unavailable or slow. It does not apply to a wait
on another item (after), on a decision or an outside party (needs decision or external), a park (hold with
wait_basis), a stored wait (wait_kind), a hand-off to another session, or a step you leave as it was. wait_reason is
not stored on the item. Right: update(item_id="board#N", sender="my-x", until="<tomorrow or later, within {{CAP_DAYS}}
days, YYYY-MM-DD>T04:00", wait_reason="the nightly run finishes at 03:00").

## param AFTER
Items this one waits on: after=["board#N"], with ask_by=<YYYY-MM-DD> as the day it comes back if they are still open.
The wait ends when they close.

## param OUTCOME
How a close ended: done | dropped (won't do, no longer needed, or can't) | superseded (replaced by another item:
reworded, merged or split; send superseded_by=<the replacing item's id>). Passed on update with status=completed, or
on complete: outcome="done", reason="Export shipped in PR 12", outcome_text="- PR 12 merged"; all three are required.

## param REASON
One line, at most {{CLOSE_REASON_MAX}} characters (longer is refused): the end state reached and why. Goes with
outcome on a close.

## param DESCRIPTION
The item's background as short `- ` bullets, at most {{DESC_MAX_LINES}} lines of {{DESC_LINE_MAX}} characters, live
state only (never steps or commands): description="- Goal: the export finishes in under a minute\n- Problem: the
nightly run takes 9 minutes". The first bullet opens `Goal:` (case-sensitive), a symptom or cause goes in a later
`Problem:` bullet, {{OWNER}}'s words go in a bullet such as `- {{OWNER}}: …`, and parallel bullets go under one parent
bullet, indented two spaces.

## param OPTIONS
The alternatives of a decision, one per line: options=[{"label": "Approve", "line": "Approve the schema",
"recommended": true}, {"label": "Decline", "line": "Wait a week", "recommended": false}]
({{OPTIONS_MIN}}-{{OPTIONS_MAX}} entries, exactly one recommended, each line at most {{OPTION_LINE_MAX}} characters).
A yes/no decision lists Approve and Decline. Name who acts in every option, label and line: a person or a session
name, never I, you, we, us or me.

## param CHECK
What closes the item once work handed to another session is done; the server runs it every minute: check="pr_merged
acme/widgets#12" (also item_closed <item id>, lane <session> <lane>, unit_active <unit>.service). A next line that
hands the item to a session other than its mover and you needs a check or, instead, a date (wake or until) as the
hand-off's backstop: with a hand-off the date is no wait (unless the item carries hold, wait_kind, wait_basis or an
after link, in this call or stored by an earlier one: then the date stays a wait), the item stays active in the new
mover's lane and the hand-off is recorded; a front agent needs neither. check="none" clears it.

## text STEP_PROOF_FORM lead trail
A step can name the event that finishes it, and the server then ticks it done when the event happens: a pull request
merged (pr_merged), or released, i.e. merged and live (pr_released: this repository's with main's tests passed, or a
configured repository's). A step that is only `release PR #<n>`, `release #<n>` or `release <URL>` (or the same with
`merge`), with at most a short parenthetical (`(in its turn)`) and a closing full stop, is ticked when that pull
request is released, on an item anchored to the PR or naming its URL. Anything else after the phrase (`and verify the
pages`, `, restart x`, ` then …`) is a follow-up: the step stays open and its mover is told once; a condition (`once
#<n> is released, …`, `when PR #<n> is merged, …`, `release it after #<n>`) is never ticked either, and its mover is
told once it is met. A negated phrase (`do not release PR #<n>`), a step that only mentions the PR (review, verify,
investigate), another repository's #<n> without its URL, and a step of his never match. step_proof=[{"step": <position
or the step's exact first line>, "proof": "pr_merged <owner>/<repo>#<n>" | "pr_released <owner>/<repo>#<n>"}] states
the proof outright, whatever the step's words say (a bare #<n> is this repository's, a URL works too; "proof": "none"
clears one step's proof, step_proof="none" every one; the step must be open). When the event arrives the server marks
the step done and tells its mover the next open step once; with no open step left the item closes, outcome done. A
pull request closed without a merge ticks nothing. A done step whose next open step names another session makes that
session the mover and tells it. A step that delivers a PR (`release`, `merge`) and is followed by another session's
step must be only that phrase or carry step_proof, or the write is refused.

## text DRAFT_FORM lead trail
draft: the text exactly as it is to be posted, sent or pasted somewhere else by the person whose step it is (a channel
message, an email, a reply), as many lines as it has, stored and shown as written (no bullets, no line limit; at most
{{DRAFT_MAX}} characters). His item page draws it under the step as a block with a Copy button; a close drops it, and
so does his Done or Send note on the step. An item whose step is such a post, send or paste carries the text: a write
that sets the step or mover of an item so that it is his step, or that sets or clears its draft, with a step that
names a text to post, send or paste ({{DRAFT_STEMS}}, and the instance's own words of [keywords.draft]; a heuristic,
not a complete list), is refused unless the item has a draft or its step or description links the document that holds
the text (an https:// link to a doc, Drive file, Notion page or Slack thread; a GitHub issue, pull request or commit
link, or a link to the board, does not count). draft="none" (or update clear_draft=true) removes it; a create can
store one before the step exists.

## param STEP_PROOF
The event that finishes a step, so the server ticks it: [{step: its 1-based position or exact first line, proof:
pr_merged|pr_released <owner>/<repo>#<n> (or none to clear that step's)}], or the string none to clear them all; the
step must be open and not {{OWNER}}'s own.

## param WAIT_KIND
What a waiting item waits on: time | anchor | item | relay | event. A time wait is its wake; an item wait its after;
an anchor wait its wait_anchor (on the project's anchors list first: add it with the anchors tool) and wait_event (a
wake is the backstop); a relay wait its wait_event and ask_by; an event wait its wait_event (a fleet event) and a
backstop day (ask_by or a wake). An anchor wait wakes the item on any new notice at its anchor that reaches the server
and passes the project's keeper, not only on the awaited event, so it fits something quiet apart from that event (a
PR, a thread, a file) and not a busy channel or DM; for a busy channel use a relay wait (it is put to someone on a
day) or a time wait (check back on a date). "none" clears it.

## param WAITS
A wait on a list: 2 to 8 lines {"kind": time | anchor | item | relay | event, plus that kind's fields: until; anchor
and event; after; event}. Needs until (the backstop day) beside it, and no wait_kind, wait_anchor, wait_event, after,
wake, ask_by or hold. It replaces the stored list: send the lines that remain, [] ends it.

## param WAIT_MODE
With waits: all (the default, or the stored list's) = every line has arrived; any = the first has.

## param WAIT_EVENT
The event the wait expects. An anchor wait: what you expect at the anchor, which the post-wake mover checks, since any
new notice there that reaches the server and passes the project's keeper wakes the item; a wait_event naming a merge,
close, landing or completion is not woken by a routine push or CI line on the fleet's own PR (only by one that says
merged or closed). A relay wait: the party or event {{OWNER}} relays. An event wait: the fleet event, one of
{{EVENT_FORMS}} (live today: pr_released, pr_merged, box_online, recycle and every fleet_op form; job_run turns only
on the backstop day; box_online <machine> ends when that machine is online and is refused while it already is, or for
a machine the fleet does not know; an item waiting on a date for an offline machine says wait_event="box_online
<machine>" with that date as ask_by instead). "none" clears it.

## param MOVER
Who moves the item now: {{OWNER}}, a session name or id, or the project's background agent. A front agent (a session
{{OWNER}} talks to) only by itself: it gets no hand-off notice, so a create or update from another session that sets
mover=<front agent> gets the project's builder instead (the reply and History say so; send mover=<front agent> again
and it is kept as sent; with no builder it is refused unless sender and target are both front agents of the item's
project); message the front agent for a check or an answer only it can give. On an update that sets no needs, the
session needs names for the mover it replaces is swapped for the new one.

## param THEN
Who takes the item after {{OWNER}}'s answer or step (it becomes the mover then): a session name or id, or the
project's background agent. A front agent only by itself: a create or update from another session that sets
then=<front agent> gets the project's builder instead, as for mover.

## param POST_WAKE
Who moves the item when its wait ends (it becomes the mover then): {{OWNER}}, a session name or id, or the project's
background agent. A front agent only by itself: a create or update from another session that sets
post_wake_mover=<front agent> gets the project's builder instead, as for mover.

## param CONTACT
The item's contact: the front agent (a user-facing agent) that {{OWNER}} talks to about it, by its name. Leave it out
and the contact is the creator when that is a front agent, else the project's -main agent. A background agent that
creates an item may name one of the project's front agents here; any other name is refused, and the refusal lists the
project's front agents with their mandates. On an update it changes the contact with the same check; an update that
re-files the item under another project (project=) makes that project's -main agent the contact, unless contact is
passed too, the contact is a front agent of that project as well, or the contact is the item's creator and a front
agent of any project (it stays). The same fall to the -main agent happens when the contact retires.

## text CONTACT_FORM lead trail
Parameter contact (a filing field: it moves no state clock, changes no mover and sends no notice; get shows it as
`contact:`): the front agent that {{OWNER}} talks to about the item; the parameter says how it is set and when it
falls to the project's -main agent.

## text ASK_RULE trail
The server takes an ask off {{OWNER}}'s move in one case only: its author's own plain sentence. A write by the ask's
author whose whole new text, in every text parameter of the call (description, next, subject, goal and the others; a
line sent again whole from before is not new), is exactly one sentence, "The ask is wrong.", "My question is moot." or
"This ask is no longer needed." (also stale, void, obsolete, no longer valid; at most one "- " bullet before it, and
only "now", "anymore" or a full stop after it) removes the ask, its options and his stored your-call, hands the item
back to its author, says so in History and in the reply, and keeps his late answer as a comment. Any other new line or
sentence in that write (a hedge, a label such as Note:, a quote, a question, another language) means no word, and a
write with no sender counts for nothing. A dropped dependency removes nothing: a gate is a precondition, so a dropped
gate often makes the ask more live. When an ask whose text names an item after/once/when/until/waiting for/depends on
has that item closed as dropped after the ask was written, the ask's author is reminded on each of his writes to the
item while that item stays dropped and the ask stands (withdraw the ask with clear_ask=true if it is moot, otherwise
it stands). The server never writes an ask, closes an item or answers for {{OWNER}}.

## text CLOSE_REFUSAL
A close (complete, or update with status=completed) carries outcome: done | dropped (won't do, no longer needed, or
can't) | superseded (replaced by another item: reworded, merged or split), with superseded_by = the replacing item's
id (open or completed); reason: one line, the end state reached and why, at most {{CLOSE_REASON_MAX}} characters
(longer is refused); and outcome_text: how it ended, as short `- ` bullets (at most {{DESC_MAX_LINES}} lines of
{{DESC_LINE_MAX}} characters), shown in the Outcome block. A close leaves the description as it was (a description
passed with a close is stored as outcome_text) and clears next, ask and needs (and any hold, wake or recycle wait);
due stays as a record. Reopening (status=open on a completed item) takes a new next, and drops outcome, outcome_text,
reason and superseded_by. A close ticks only the steps that are still open and are yours (you wrote them, or they open
with your name), by the closer (done when the outcome is done, dropped otherwise; steps marked in the same call keep
their marks; this settles a step of his too, the one case where a session's call marks it, because the item is over).
A step that opens with another session's name stays open, so the close is refused, naming that step, and nothing
changes: ask that session to finish it, or mark it in the closing call itself (update with status=completed and
done=[n] or dropped=[n]). It tells the mover of every other open item whose next or description names the closed item
(board#N), one message per mover (the first 8 items, then a count); the items that wait on it through after get their
own wake, and the closer is not told. {{ASK_RULE}}

## text CLOSE_FORM
A close (complete, or update with status=completed) carries outcome: done | dropped (won't do or no longer needed) |
superseded (replaced by another item; superseded_by = its id), reason (one line, the end state reached and why, at
most {{CLOSE_REASON_MAX}} characters (longer is refused)) and outcome_text (short `- ` bullets, at most
{{DESC_MAX_LINES}} lines of {{DESC_LINE_MAX}} characters, shown as the Outcome); it leaves the description as it was
(one passed with a close is stored as outcome_text) and clears next, ask and needs (and any hold, wake or recycle
wait); due stays as a record. Reopening (status=open on a completed item) takes a new next, and drops outcome,
outcome_text, reason and superseded_by. A close ticks only the steps that are still open and are yours (you wrote
them, or they open with your name), by the closer (done when the outcome is done, dropped otherwise; this settles a
step of his too). A step that opens with another session's name stays open, so the close is refused, naming that step,
and nothing changes: ask that session to finish it, or mark it in the closing call with update (status=completed and
done=[n] or dropped=[n]; complete takes no marks). It tells the mover of every other open item whose next or
description names the closed item (board#N), one message per mover (the first 8 items, then a count); the items that
wait on it through after get their own wake, and the closer is not told. {{ASK_RULE}}

## param OUTCOME_TEXT
A close's summary: how the item ended, as short `- ` bullets (at most {{DESC_MAX_LINES}} lines of {{DESC_LINE_MAX}}
characters), stored in the item's Outcome field. A close does not change the item's description. Goes with a close
only.

## text GMAIL_TERMS
Terms are from:, to:, cc:, subject: and person: (or plain text, a subject term), joined by AND, OR and parentheses
(capitals), key:(a OR b) for one key over several values; put text that holds a parenthesis, a colon or the word OR in
quotation marks

## text OFF_MAP_NOTE lead
A sender off the project's agents map gets a note naming its -main agent

## text OFF_MAP
{{OFF_MAP_NOTE}}: ask it to list you.

## text SENDER_MIRROR trail
While the GitHub mirror is on, sender is required on every update, confirm and complete, the mover's own included.

## text LEAD trail
If your session did not load {{OWNER}}'s standing rulebook at start (a cloud or Cowork session), call the rules tool first and follow
it; it overrides defaults.
