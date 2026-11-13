## text RANK_RETIRED
Refused: ranks are retired. A builder starts every item handed to it at its next turn and releases go out in
merge-queue order; drop rank and clear_rank from the call (an item handed to a builder needs the builder in needs and
a next).

## text STALL_SHORT lead
A wrong `stall:` step is undone with update (mover, next, clear_needs); the whole path, and why a pause needs
{{OWNER}}'s own answer, is in get.

## text WAIT_FORM lead trail
A wait is one stored date, until, with wait_kind beside it when it stands on more than the date. An item with an until
is waiting; the server clears both when the wait ends. wake, ask_by and hold with a wake are still accepted for now as
other names of until. A wait_kind with no date is never refused: the server takes a date from the item's words, else a
suggested one, else tomorrow, and says which. Every open item has a mover (the one party whose move it is now: a
session, {{OWNER}}, an outside party, or the item it waits `after`). An open item waits on its real dates only (wake,
due, ask by): no expected time is derived for any item, and a parked item is held until its wake or its blocker
closes, with no stale mark. A wake a session sets runs at most {{CAP_DAYS}} days from the item's last move: a wake
further out, an anchored thread's included, is refused without {{OWNER}}'s words (said=[Acked-by …] checked against a
transcript, a message from those days; or his answer on the item, given since its last move: ask him to answer there).
A due date is a deadline and is not refused. Parameter wait_basis: the reason a time wait's wake carries, one line
with its date (wait_basis="<what the window collects> ends <YYYY-MM-DD>"; a wait for a date outside the board, such as
a vendor's reply date or a release freeze, reads "<what happens> YYYY-MM-DD"). Three wakes take it: a hold's wake (it
parks the item, which reads as waiting, not on agent, until the wake), a stored verifying item's wake, and a wake past
the cap (it lifts the cap for that wake alone; clear_wait_basis=true drops it). A bare date within the cap (until, or
its old name wake) is a wait on its own, and a basis for it is refused as not needed unless the item is on hold
(hold=true) or verifying; a date no longer leaves the item active as a reminder (outside a hand-off's backstop): set
no date to keep an item moving. A hold with a wake and no basis, where the item's own next or its description says the
work waits for that wake's day ("collect the logs until 2099-03-02, then review"), takes that line as its wait_basis
(the reply says so); a basis needs a wake date (a hold with no date is refused) and names the date it waits for as
YYYY-MM-DD on or after the wake day. A wait that can no longer end (a check whose pull request was closed unmerged)
fails at once and tells the item's mover. clear_wait=true is how an update drops a stored wait (wait_kind and its
fields); wait_anchor or wait_event of none and clear_wait_basis do not. An update that newly adds needs=decision to an
item that stores a wait is refused unless it also passes clear_wait=true: the wait would otherwise win and get would
list a model conflict. clear_after=true clears the after list, as after=[] or after="none" do; some clients drop an
empty list, so the flag always arrives. A write that clears a wait while an open next line still defers on what it
cleared in words goes through, and its reply carries one line per stale next line (`(note: next line N still waits on
board#X, whose wait was just cleared: reword it)`): reword or drop those lines in the same turn. An item stores alive
or waiting directly; there is no state to set, and these are not parameters of this tool or of create: a call that
passes state, clear_state, party, chase, end, proof or chase_note is refused with what to pass instead. Whose move it
is goes in mover; {{OWNER}}'s call is needs=["decision"] with an ask; his own step is step=<one line, no command, of
the single thing only {{OWNER}} does; what he runs goes in a next line that starts `{{OWNER}}:`> (the board ticks it
when he says it is done; never ask him "have you done it?" as a decision); a wait on another item is after=["board#N"]
(supplies=<one line: what that item's output gives this one> says what it takes from it); a park is hold=true with a
wake and either his recorded words for it (cap_ok) or a wait_basis (the end of a window the work itself needs, or a
wake past the cap); a wait on someone outside is wait_kind="relay" with wait_event=<who>, ask_by=<the day to chase>,
post_wake_mover and needs=["external"]. Work in hand needs next and its mover, carries no expected time (the item
shows how long it has run), and expected_by and expected_reason, which older calls pass, are accepted and not kept
(the reply says so). Work in hand is not a wait: a wait (a date, a timer, another release, someone else's step) is
parked in the turn it starts, with update(hold=true, until="YYYY-MM-DD" or "YYYY-MM-DDTHH:MM", wait_basis="<what it
waits for, with its date YYYY-MM-DD>"), update(after=["board#N"]) for another item, or the relay wait above for
someone outside (a write that leaves an item with wait wording in its next, such as overnight, in the morning, once
the run finishes, gets a note saying to park it). No clock renewal without progress: a write that moves a wake or
ask_by to a later time while the item's reason (description, wait_basis text) and its open steps are as they were is
refused (a wait_reason does not count: it is not stored); in the same write mark a step done or dropped, write the
next step or state the new reason (or send {{OWNER}}'s own words in said), or change what the wait stands on to a
shape the item never held (wait_kind, wait_event, wait_anchor, after: a flip back to an earlier one does not count;
such a shape change alone lets a clock push through twice in a row and the third is refused, until a step, the reason,
his new words or a hand-off resets the count); or, if the item now waits, park it (hold=true, wake, wait_basis) or use
the event-wait form (wait_kind="event", wait_event, ask_by, post_wake_mover). Setting a clock for the first time,
pulling one in, clearing it and handing the item to another session are not renewals. On a parked item give a new
wait_basis; an item on his decision cannot be held. Take a wake from the real schedule of the wait (a timer, a watch
tick, a catch-up run), or check it live; never a guessed round time. step=<one line> sets the item in his step and
makes him the mover (then, or the agent that had it, takes it after his Done); step="none" withdraws it; supplies=<one
line: what the item it waits after gives this one>, with after=["board#N"], sets the item blocked on that item. Each
is refused without what it needs, with what to add; a close drops both. Checks: a next that opens with {{OPEN_LIST}}
under an agent's state is noted; the third bare re-park in a row is refused; a next may be marked stale;
needs=decision again within 60 min of his answer is refused unless the ask changed.

## text CHECKLIST_FORM lead trail
next is a checklist: each line of next is a step, and the item keeps every step in the order it was written, open,
done or dropped; next holds the open steps. A step of yours leaves next only by being marked in the same update:
done=[…] when the work was finished, dropped=[…] when it is no longer wanted, each entry a step's 1-based position in
the checklist (marked steps count; get lists the steps under `checklist:` with their positions) or the exact text of
its first line. An update that replaces or removes (next="none") your own lines of next and leaves one of them out
without marking it is refused, naming the step, its position and the call to retry with (done=[n], dropped=[n] or
reword={n: "<new text>"}); another session's lines are never touched by your next. Parameter reword (map, step
position or first-line text → new text, e.g. reword={3: "my-x: new words"}) gives an open step of yours new words: it
keeps its number, place and open state, and next lists the new text (leave next out and the line is changed for you);
a line reworded in next alone is a new step, and the old one is refused unmarked. A reword is the same action in other
words, never the old text with words added (progress goes on the project page). Refused: a step of another session or
of his, one that is done or dropped, or also in done or dropped, a text of several steps or one another open step
reads; a different action is a new line of next. done and dropped mark any open step, whoever wrote it, and the marked
line leaves next, except a step of his (a line opening with his name) while the item asks him: that one is ticked when
he answers, and done on it is refused (dropped on it is undone while the item still asks him). The server makes his
step itself: when an item asks him for a decision (needs=decision with an ask) or for a step (your-step), it adds the
open step `<his name>: <what to decide>` at the end of the checklist (a line you wrote that says the same is adopted,
never a second beside it), shows his answer on the step when he gives it, and drops the step when you withdraw the ask
or the step; a step he already answered stays done. clear_next=true is a deliberate wipe: every line it removes
becomes a dropped step, by you. A marked step stays on the page with who marked it and when; History says `step done:
…` or `step dropped: …`. done or dropped alone, with no next, takes the step out of next; when two open steps read the
same, the position names the one marked. A step written again after it was marked is a new step. {{OWNER}}'s word that
his step is done checks every open step of his, each next line that starts `{{OWNER}}:`; a note he sends ticks the
step the server made and leaves the lines you wrote open, and the session that takes the item marks them done when it
judges the step finished.

## param REWORD
New words for open steps of your own next: a mapping from a step (1-based position, or the exact text of its first
line, as done takes them) to its new text, e.g. {"3": "my-x: wait for the new build"}; the step keeps its number and
stays open, and the new text is one step that opens with who takes it (the rules are under Parameter reword in the
description).

## param WORK
The status of your open step, one line per call: {"text": "PR 83 up", "state": "in progress"}. It replaces the status
of your first open step in place (the step is the stage, the status says where you are in it; the page keeps one line
per step, not one per write). text is at most {{WORK_TEXT_MAX}} characters (details go on the project page). state: in
progress (the default) | done. state done also ticks the step, as done=[n] does. With no open step of yours, one is
made from the text. {"remove": true} clears the status. Keys: text, state, remove. A project builder's step with a
status in progress (changed within 90 minutes) tells the stall pass and the balancer that a build subagent is running
on the item; a status left in progress stops hiding the item after that, and a status sent again unchanged keeps its
old time, so a long job changes the words or marks the step done.

## param DONE
Open steps of the checklist you finished: positions (1-based, marked steps count) or the exact first line, e.g.
done=[1] or done=[1, "my-x: open the PR"]. A step of yours that next leaves out must be in done or dropped.

## param DROPPED
Open steps that are no longer wanted, named like done: dropped=[2]. A different action is a new line of next, not a
reword.

## param WAKE
The old name of until, accepted for now: when the item wakes, in the future: YYYY-MM-DD, or YYYY-MM-DDTHH:MM for a
time of day, in the board timezone (a relay or event wait takes the day alone, YYYY-MM-DD). Alone it is a wait: the
item waits until that date (outside a hand-off: in an update that hands the item to another session the date parks
nothing, it is the hand-off's backstop (unless the item carries hold, wait_kind, wait_basis or an after link, in this
call or stored by an earlier one: then the date stays a wait)). A window the work needs: wake="<last day of the
window, YYYY-MM-DD>", wait_basis="soak ends <that day>". A wait on your own item also needs wait_reason (at least
{{WAIT_GUARD_REASON_MIN}} characters); a wait with wait_basis needs none, and a wake more than {{CAP_DAYS}} days out
needs a wait_basis. Moving a wake (or ask_by) later with the item otherwise as it was is refused: in the same write
mark a step done or dropped, write the next step or a new reason, or change what the wait stands on (wait_kind,
wait_event, wait_anchor, after; a flip back to an earlier one does not count, and a wait_reason does not count).

## param ASK_BY
The old name of until, accepted for now: the day a wait on another item, a relay or an event comes back to someone if
it has not ended, YYYY-MM-DD, tomorrow at the earliest: ask_by="2099-03-02". Moving it later with nothing else changed
is refused (see wake).

## param UNTIL
The one date a wait ends on, in the future: YYYY-MM-DD, or YYYY-MM-DDTHH:MM, in the board timezone (a relay or event
wait takes the day alone, YYYY-MM-DD: its ask-by day). An item with an until is waiting (outside a hand-off: in an
update that hands the item to another session the date parks nothing, it is the hand-off's backstop and the item stays
active in the new mover's lane (unless the item carries hold, wait_kind, wait_basis or an after link, in this call or
stored by an earlier one: then the date stays a wait)); wait_kind goes only beside it (none: it waits on the date
alone). until="none" drops it. It replaces wake, ask_by and hold with a wake, still accepted for now. Moving it later
with nothing else changed is refused, as for wake. Beside waits it is the list's backstop day.

## param NEXT
Your lines of the checklist, one step per line, each opening with who takes it, then a space: next="my-x: open the PR"
(a label such as `Status:` names no one). It replaces only your own lines; a line of yours it leaves out must be
marked in done or dropped (or reword) in the same call. An item that stays open keeps one open step, a held one the
step its wake leads to. Never reword an open step to add progress. next="none" removes your open lines; an empty next
is next not passed.

## param ASK
The one line a needs=decision item carries, at most 240 characters: ask="Decide: whether to approve the sample schema
· Recommend: Approve · Stakes: waiting a week delays the demo · By: Mon Jun 8th 2099" (By is a date in words, or no
date). A real choice, not "have you done X?"; one decision per ask. With no options listed the Recommend is a yes or a
no. Name who acts (a person or a session name) in every option, never I, you, we, us or me; the ask line never says I,
you or me. "none" or clear_ask=true withdraws it.

## param HOLD
The old way to wait on a date, accepted for now (stored as until). True parks the item until its wake, for a window
the work itself needs: hold=true, until="<last day of the window, YYYY-MM-DD>", wait_basis="soak ends <that day>". It
reads as waiting, not on agent; clear_hold=true ends it. On a relay or event wait no flag is stored (the wait is the
park until its day) and the hold ends a stored work-in-hand state.

## text STEP_FORM lead trail
step (update only; create sets no step): a ONE-LINE summary of what the person whose step it is does, for an item that
is his step, at most {{STATE_LINE_MAX}} characters. It points at his Next lines and never holds a command: every shell
command he runs goes in a next line that starts `{{OWNER}}:`, whole in backticks (or a ``` block), {{P_PLACE_STEP}}A
step that carries a command (a backticked span with a space in it that reads as a shell command, a `! ` line, a ```
block) is refused, and the refusal says to put the command in a next line that starts `{{OWNER}}:` (a step stored with
a command before keeps the older checks on a write that leaves it alone{{P_OLD}}). A button or menu label is not a
command: put it in bold or quotes, not backticks ("Make a copy", **Sort by date**). A next line that starts with his
name (`{{OWNER}}:`) and asks him to run something gets the command check{{P_CHK}}, on create and update, whatever the
item's state, for the lines the call sets (the cue and the `! ` rule are under next above): a command outside
backticks{{P_BARE}} is refused as `next line: …`; a line that only mentions a command is not checked. A bare command
with a flag, path or quoted argument, written outside backticks or a fence after a run cue or a place phrase
({{P_EX2}}), is a command too: the step carries none, and a next line gets it in backticks so the board shows a copy
box{{P_BARE}}. A write that leaves an item for him to move (him as mover, in his step, or with his decision in needs)
is refused when its description adds a numbered line (`1.`, `2)`) or a `! ` line outside a fenced block: the
description is the background, never steps. A write that leaves an item in your-step for him is refused, in one line
naming the field, when the description holds a shell command (move it to a next line that starts `{{OWNER}}:`; a
description write is judged only on the commands it adds or changes, and a fence there counts only when tagged sh,
bash, shell, powershell, pwsh or console, and each command line of a tagged fence is judged; an untagged fence holds
pasted output), or when the step points elsewhere ("see the description", "see below", or a phrase of
[keywords.step_commands] pointer_patterns); a step that names his Next line passes. Only writes that set the state,
step, mover, description or draft are judged, and [model] guards = false skips these checks.

## param WAIT_BASIS
The reason a time wait's wake carries, one line that names its date: wait_basis="soak ends <that day, YYYY-MM-DD>"
(YYYY-MM-DD, on or after the wake day; a wake with no date is refused). Three wakes take it, each basis bound to the
wake it was given for: a hold's wake (the park), a verifying item's wake, and a wake more than {{CAP_DAYS}} days out
(it lifts the cap for that wake alone, up to {{BASIS_MAX_WAKE_DAYS}} days: a wake further out is refused whatever the
basis). A hold with a wake and no basis takes the line of next or the description that says what the work waits for.

## param RANK
Retired: refused. Ranks are retired; a call that carries this is refused.

## param CLEAR_RANK
Retired: refused. Ranks are retired; a call that carries this is refused.

## text NEXT_FORM trail
next replaces only your own lines: every line of next remembers the session whose update wrote it (the sender, or the
item's creator when the call names none; not the name the line starts with). next=<lines> takes the place of the lines
you wrote before, where the first of them stood (at the end when you had none) and leaves every other session's lines
where they are; an open step of yours that the new next leaves out must be marked in the same update, done=[n] or
dropped=[n] (a line reworded in next alone is a new step: mark the old one and write the new text, or pass reword).
next="none" removes only your own lines; clear_next=true wipes every line, whoever wrote it, and with next given the
wipe comes first and your lines are then set. A line of yours that another session's open line already reads the same
is not added a second time. A close clears next whoever wrote it.

## text UPDATE_DESC trail
Update an item; only the fields you pass change.{{OFF_MAP}} Right calls (sender = you): step done, next added:
update(item_id="board#N", sender="my-x", done=[1], next="my-x: open the PR") (next keeps your open steps; one you
leave out must be in done or dropped); reword an open step: reword={"2": "my-x: ship the export"}; drop a step:
dropped=[2]; status of your open step: work={"text": "PR 83 up", "state": "in progress"} (at most {{WORK_TEXT_MAX}}
characters; state done ticks the step); park for a work window: hold=true, until="<last day of the window,
YYYY-MM-DD>", wait_basis="soak ends <that day>"; a wait until a date on your own item: until="<tomorrow or later,
within {{CAP_DAYS}} days, YYYY-MM-DD>T04:00", wait_reason="the nightly run finishes at 03:00"; wait on another item:
after=["board#N"], ask_by="2099-03-02"; description="- Goal: the export finishes in under a minute\n- Problem: the
nightly run takes 9 minutes"; close: complete(item_id="board#N", sender="my-x", outcome="done", reason="Export shipped
in PR 12", outcome_text="- PR 12 merged"). status: open | completed (`needs` says whose move it is; complete rather
than delete). {{CLOSE_FORM}}A new or reworded open step that opens with a front agent is refused on an item another
session moves: open it with the mover's name, or message the front agent (a step it already holds stays).
{{ITEM_FORM}} {{NEXT_FORM}} ask="none" clears it (so does clear_ask=true). A write that leaves an ask standing on an
item you move or wrote ends with a one-line reminder to withdraw the ask if it is wrong or moot; a write that sets an
ask shows {{OWNER}}'s comments and notes since the item's last ask, so one that already answers it is seen before you
ask again. His note on a step that only says he did it ("ran it"; "run it" is a request and ticks nothing) ticks the
step, and one in which he says he will do it later ("I'll do it tomorrow evening") holds the item until then; any
other note (a question, a negation, a deadline, more than that) goes to the session to judge. The ask's mockup rule
above also holds on an update that sets the ask, description, next, needs or options or puts the item on
needs=decision. options=[] (or "none", or clear_options=true) clears the options, which need no recommended one then
(refused while the ask is an open question; a non-empty list still takes 2 to 6 entries, exactly one recommended).
When {{OWNER}} answers by picking an option, the server clears the ask and the options itself and keeps his answer
with the option's label and line. A client whose tool has no ask parameter refreshes the ask by writing the new line,
in the ask's form, as the first line of next. When this work settles or changes a premise of another open item, update
that one too, in the same turn. item_id: board#N; a bare number N is read as board#N, except in an update that closes
the item. wake (YYYY-MM-DD, or YYYY-MM-DDTHH:MM for a time of day, {{TZ_ABBR}}; a full ISO time with seconds or a UTC
offset is converted to that minute in {{TZ_ABBR}}, and the reply says so) alone is a wait: the item waits until that
date, listed as waiting, and at that moment the server tells its mover and the sessions in its needs once and drops
the date; in an update that hands the item to another session the date is no wait but the hand-off's backstop, and the
item stays active (unless the item carries hold, wait_kind, wait_basis or an after link, in this call or stored by an
earlier one: then the date stays a wait). Work moving in real time is not parked. A doing item whose wake is over an
hour away and whose every open step waits for a later date ("after Mar 2", "until Mar 2"; a deadline such as "by Mar
2" or "due Mar 2" is no wait) is listed as waiting, and the audit asks why the step cannot run now. A front agent's
own wake or until date (no hold) on an alive item another session moves is refused (the result lands through stackshot
when the mover closes the item or hands it back to you; watch_reason=<why no push reaches you> lets a real exception
through; a park's wake with hold=true is a wait of its own and stays allowed). On hold = an open item parked until its
next move is due: hold=true, always passed explicitly, with what it waits for; with a wake the server releases it at
that moment, tells the sessions in its needs (else its mover; refresh the ask then) and returns it to the lane its
needs give it. Meanwhile it reads as parked (a waiting state), not as work moving on agent; needs and due stay as they
are. An item whose needs hold decision is never on hold: a write to one drops its hold (its date stays, and no date
parks an item on his call). {{OWNER}} parks on his word. A hold always names what it waits for: {{OWNER}}'s words, the
items that must close first (after), a notice from an anchor scoped to the item, a pane recycle (recycle=true), or the
end of a window the work itself needs; an unconditional or indefinite park is refused. Work moving in real time stays
on agent however long it takes (a build, tests, a review, a release, a run in progress): do not park it. A session
parks its own item when the work itself needs a wait-and-see window (a soak, a log or data collection window, a trial
week, a timer it started): hold=true, until=<when the window ends>, wait_basis="<what the window collects> ends
<YYYY-MM-DD>" (update(item_id="board#N", sender="my-x", hold=true, until="<YYYY-MM-DD, a future day>",
wait_basis="error-log soak ends <that day, YYYY-MM-DD>")). A session does not park to defer work it could do now: an
item not on hold is one its mover can move now, so work it in your next free turn. A wake without hold whose next says
the work waits for that wake's day within a line ("collect logs until <that day>, then review") gets a note on the
reply, never a refusal: the wake is stored, the item stays on agent, the note gives the park form above. When your
write sets or keeps a wake with no hold over an hour ahead, you are the item's mover and every open step opens with a
time at the wake's hour or day ("at 03:00", "on <that day>", "after <that day>", "tomorrow at 9"), the server parks it
itself: on hold, wait_basis from your wait_reason; the reply says `(parked: …)`; to work a step now, write it as the
action and pass clear_hold=true: the server then leaves that wake alone. A next line that says in words it waits for
an open item, a pull request's merge or release, a machine coming back online or a link, while the item stores no wait
for it, is set by the ten-minute pass when the line is the item's only open step and one thing is named (after, an
event wait, an anchor wait, or a step proof): clear_after=true, clear_wait=true or step_proof="none" sends it back and
the server leaves that line alone. Steps started by an outside event ("when the next release lands") get a note
instead: park with hold=true, wake, wait_basis, wait_reason (needs=external for a named outside party's reply).
Neither applies to an action to take now, another party's step in flight, or an item not on agent (on hold, waiting on
{{OWNER}}'s decision or an open after item, needs=external, outside, verifying, blocked). An item that waits on
another item is not parked but names it: after=["board#N"]. Nor is one that waits on {{OWNER}}: needs=decision with
its ask, or after=<the item that carries the ask>. An item that waits on a named person outside (needs=external) is
not parked, unless the thread it waits on is anchored to it (anchors(project, add=[url], items=[its id])) and named in
next: park that one with a backstop wake (at most [waiting] cap_days out unless his words are on the item), since the
notice may never come; the server releases the hold when the project's router (or the project's builder, else its
-main agent) passes or merges a notice from that anchor (never when it drops one; in a project nobody rules, when any
notice from it arrives), and tells the sessions in its needs (else the project's builder, else its -main agent).
clear_hold=true releases it now (its date goes with it); until="none" (or clear_wake=true) drops the date: an item
that waits on nothing else is active again, and a hold stays only when an after, an anchor or a recycle still holds
it. mover hands the item over: set mover=<session> (then=<who takes it after {{OWNER}}'s answer or step>) and the new
mover is told; a front agent gets no hand-off notice, so an update from another session that sets mover, then or
post_wake_mover to a front agent gets the project's builder instead (the reply and History say so; send the same value
again to keep it as sent; with no builder it is refused, except a mover set by a front agent of the item's project to
another of its front agents; message the front agent for a check or answer only it can give); take over another
session's item only when asked; a session about to be retired first hands over or completes its open items.
mover={{OWNER}} alone is refused on an item that is doing: it needs step=… or needs=decision with ask=… in the same
write (the refusal says so). An update that leaves an open item in a state that is {{OWNER}}'s (his step, or needs
holding decision) and names no mover sets mover={{OWNER}} itself and moves the stored session mover into then (set
then=<you> to have the item come back to you), and the reply ends with a `(mover: <session> → …)` note; when a save
ends his state the mover he held goes back to then; a write that names the mover or clears it (clear_mover), a rename,
priority or project write, a re-bullet and a close are left alone. When an item's work moves to another project's
session, hand the item over in the same turn: mover = that project's user-facing agent (or the background agent doing
the work), project = its page. The creator is not moved with it. owner, the old name of mover, is accepted for a few
more days with a note in the reply and then refused: say mover. sender = your own session (name or cse_… id) when you
edit an item you are not the mover of (a session named in needs always passes sender=<itself>): the page update the
edit owes is then yours, not the mover's (a create, a complete, or an update to description, next, needs, status, due,
after, or the hold and its wake owes one). {{SENDER_MIRROR}}Pass clear_needs=true (or needs="none") to remove the
needs badge, clear_check=true (or check="none") to remove the done check, clear_due=true (or due="none") to remove a
date that no longer holds (a postponement with no new date). priority: p1 | p2 | p3, shown but not sorted. project
re-files the item under another page (projects/<slug> or infra/<slug>; pass the page `(filed on X)` names, never the
shown top-level key). A state change also confirms the item (it reads fresh again); the confirm tool says it is still
true without changing it. recycle=true: the item's work waits for the panes to be relaunched (a connector re-login, a
settings, hook or plugin change, a CLI update; not a change to a connector's tools, which claude.ai refreshes on its
own within about a day); set it only once the change it waits for is installed (merged and deployed, or provisioned),
never before: an early flag recycles the panes too soon, for nothing (a flag set before the provision recycled the box
too early). Set it on the item the change serves: a recycle is never an item of its own (create refuses one), and for
a change no item covers, {{WHEN_IDLE}}; {{FLEET_TOOL}} runs a flagged recycle itself, the board shows one "Pane
recycle pending for … ({{FLEET_TOOL}} runs it)" status line while an open item not on hold carries it, and when
{{FLEET_TOOL}} reports the recycle done the server clears it and tells you to re-read the item and resume.
clear_recycle=true takes it off by hand. work: the status of your open step, one line per call: work={"text": "PR 83
up", "state": "in progress"}, a few words (at most {{WORK_TEXT_MAX}} characters; the details stay on the project
page). A step is a stage of the work ("stage 11: auth and who"), not a status: what changes while it is under way goes
in this status, which replaces the status of your first open step in place, so a night of updates is one line on the
step, not one line each. state is in progress (the default) or done; done also ticks the step, as done=[n] does. With
no open step of yours the call makes one from the text; {"remove": true} clears the status. Written by the mover or a
session named in needs; it changes no needs, owes no page and, unless it ticks or makes a step, leaves the state clock
and the confirm alone. A project builder's step with a status in progress (changed within 90 minutes) tells the stall
pass and the balancer that a build subagent is running on the item, so the item is not handed on meanwhile; a status
left in progress stops hiding the item after that, and a status sent again unchanged keeps its old time, so a long job
changes the words or writes to the item; mark the step done when the subagent ends. A question {{OWNER}} asks on an
item (in his answer or a comment on it) is answered by the mover on the item itself: rewrite the description, and the
options where it is a pick, the description saying it answers his question. His question is never posted with said and
never taken as his call; only his conclusions are. {{NEEDS_FORM}} {{CHECK_FORM}}check="" changes nothing, and a new
check passed replaces the old one.

## param project
Re-files the item under this page, as `(filed on X)` shows it, never the shown top-level key.

## param wait_reason
What the step waits on that is not available now (a reply, a build or test still running, a window the work needs, a
resource that is down), at least {{WAIT_GUARD_REASON_MIN}} characters. Required when this write sets a wake, or a line
of your own next dated later than today, on an item you move: without it the write is refused, and a model may refuse
it when the step could be done now. Not stored on the item. A park (hold=true with wait_basis), a wait on another item
(after) and needs decision or external need none. A date after by, due or before is a deadline, not a wait.

## description update
{{UPDATE_DESC}}{{CONTACT_FORM}}{{MODEL_FORM}}{{CHECKLIST_FORM}}{{STEP_PROOF_FORM}}{{DRAFT_FORM}}{{STEP_FORM}}{{STALL_SHORT}}{{SELF_WAIT_FORM}}{{MACHINE_FORM}}{{WAIT_FORM}}
