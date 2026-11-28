## text RANK_RETIRED
Refused: ranks are retired. A builder starts every item handed to it at its next turn and releases go out in
merge-queue order; drop rank and clear_rank from the call (an item handed to a builder needs the builder in needs and
a next).

## text STALL_SHORT lead
A wrong `stall:` step is undone with update (mover, next, clear_needs); the whole path, and why a pause needs
{{OWNER}}'s own answer, is in get.

## text WAIT_FORM lead trail
A wait is one stored date, until, with wait_kind beside it when it stands on more than the date. An item with an until
is waiting; the server clears both when the wait ends. wake and ask_by, and hold beside a date, are retired parameters: a call that passes
one is refused, and the date goes in until. A wait_kind with no date is never refused: the server takes a date from the
item's words, else a suggested one, else tomorrow, and says which; a park with a wait_kind and no date takes the same
date, marked as set by the server. A wait this write would leave with no end day (an after link, a wait stored earlier,
needs=external, a park, or a wait on a time with no date) is not refused either: the server stores its default backstop
day, 14 days from today, marks it as set by the server and
says so in the reply; a park sent with no date and a wait_basis that names a date ahead ends on that date instead (a
basis that names none is refused as before). Its mover
replaces that day with the real one (until). None of this while
the item waits on {{OWNER}} in any form, as it stands or as the write leaves it (needs=decision or his name, an ask,
options he has not answered, a your-call or your-step, mover={{OWNER}}, a step line of his still open), nor when the
item already holds an end in any field (an old ask_by included, past or ahead), nor beside a date of your own or "none"
for one, nor in a write that clears or drops a wait or its end: the wait is judged as before, so one with no end is
refused, and an end the item holds is never replaced. A list of waits still needs its until.
The dates you give yourself keep the cap rules. Every open item has a mover (the one party whose
move it is now: a session, {{OWNER}}, an outside party, or the item it waits `after`). An open item waits on its real
dates only (until, due): no expected time is derived for any item, and a parked item waits until its date or its
blocker closes, with no stale mark. A date a session sets runs at most {{CAP_DAYS}} days from the item's last move: a
date further out, an anchored thread's included, is refused without {{OWNER}}'s words (said=[Acked-by …] checked
against a transcript, a message from those days; or his answer on the item, given since its last move: ask him to
answer there) or a wait_basis. A due date is a deadline and is not refused. Which wait to write: own work waiting on a
date within {{CAP_DAYS}} days: until="<tomorrow or later, within {{CAP_DAYS}} days, YYYY-MM-DD>T04:00" with
wait_reason="the nightly run finishes at 03:00"; a park for a window the work itself needs, or a date past the cap:
until="<last day of the window, YYYY-MM-DD>", wait_kind="time", wait_basis="error-log soak ends <that day,
YYYY-MM-DD>" (parameter wait_basis has the form; it goes with a date past the cap and with a stored verifying item's
date, and lifts the cap for that date alone; clear_wait_basis=true drops it; a park of
{{CAP_DAYS}} days or less carries his recorded words instead, said=[Acked-by …] or his answer on the item, and
a basis sent with such a date is dropped, the reply saying so). A bare date within the cap is a wait on its own and
needs no basis; a date does not leave the item active as a reminder (outside a hand-off's backstop): set no date to
keep an item moving. A wait that can no longer end (a check whose pull request was closed unmerged) fails at once and
tells the item's mover. clear_wait=true is how an update drops a stored wait (wait_kind and its fields); wait_anchor or
wait_event of none and clear_wait_basis do not. To change a wait send the new wait_kind without clear_wait (the two
do not go in one call); a stored wait_anchor or wait_event stays beside it unless the call sends another or "none". An update that newly adds needs=decision to an item that stores a wait is refused unless it
also passes clear_wait=true: the wait would otherwise win and get would list a model conflict. clear_after=true clears
the after list, as after=[] or after="none" do; some clients drop an empty list, so the flag always arrives. Whose move it is goes in mover; {{OWNER}}'s call is
needs=["decision"] with an ask; his own step is step=<one line, no command, of the single thing only {{OWNER}} does;
what he runs goes in a next line that starts `{{OWNER}}:`; a step that asks him to open or check something carries the link itself, [words](url), never "the link above" or "the mockup I sent"> (the board ticks it when he says it is done; never ask him
"have you done it?" as a decision); a wait on another item is after=["board#N"] (supplies=<one line: what that item's
output gives this one> says what it takes from it); a park is until=<date> with wait_kind="time" and either his recorded
words for it (cap_ok) or a wait_basis (the end of a window the work needs, or a date past the cap); a wait on someone
outside is wait_kind="relay" with wait_event=<who>, until=<the day to chase>, mover=<who takes it then> and needs=["external"].
Work in hand needs next and its mover and carries no expected time (the item shows how long it has run); expected_by
and expected_reason, which older calls pass, are accepted and not kept (the reply says so). Work in hand is not a
wait: a wait (a date, a timer, someone else's step or release) is parked the turn it starts, with
update(until="YYYY-MM-DD" or "YYYY-MM-DDTHH:MM", wait_kind="time", wait_basis="<what the date is, with its date YYYY-MM-DD>"),
update(after=["board#N"]) for another item, or the relay wait above for someone outside (a write that leaves wait
wording in next, such as overnight or once the vendor replies, gets a note saying to park it). No
clock renewal without progress: a write that moves an until to a later time while the item's reason
(description, wait_basis text) and its open steps are as they were is refused (a wait_reason does not count: it is not
stored); in the same write mark a step done or dropped, write the next step or state a new reason (or send
{{OWNER}}'s own words in said), or change what the wait stands on to a shape the item never held (wait_kind,
wait_event, wait_anchor, after: a flip back to an earlier one does not count; such a shape change alone lets a clock
push through twice and the third is refused, until a step, the reason, his new words or a hand-off resets the
count); or, if the item now waits, park it (until, wait_kind="time", wait_basis) or use the event-wait form
(wait_kind="event", wait_event, until, mover). Setting a first clock, pulling one in, clearing
it and handing the item on are not renewals. On a parked item give a new wait_basis; an item on his
decision cannot be parked. Take a date from the wait's real schedule (a timer, watch tick, catch-up run) or
check it live, never a guessed round time. step=<one line> sets the item in his step and makes him the mover (then, or
the agent that had it, takes it after his Done); step is a short summary, and a long one is put right for you: a step over
{{STEP_SPLIT_OVER}} characters with several actions (sentences, semicolons, `1) … 2) …`) is split into a summary of at most {{STEP_SUMMARY_MAX}}
characters and one line of next per action that opens with `{{OWNER}}:`, which the board draws as his list (a lead-in that ends with a colon before `1) … 2) …` is one line with its items as indented `- ` lines under it; the reply says
so, no word is lost; send the summary and the lines yourself to choose the words); a long `{{OWNER}}:` line of next with
several actions is split the same way (never over {{STEP_SPLIT_MAX}} characters or {{STEP_SPLIT_ACTIONS}} actions, or with a word or code span longer than a line: a step over its limit is refused, saying why); a new step or step="none" drops the old split's open lines; step="none" withdraws it; supplies=<one line: what the item it waits
after gives this one>, with after=["board#N"], sets the item blocked on that item. Each is refused without what it
needs, with what to add; a close drops both. Checks: a next that opens with {{OPEN_LIST}} under an agent's state is
noted; the third bare re-park in a row is refused; a next may be marked stale; needs=decision again within 60 min of
his answer is refused unless the ask changed. A reply names his answer given since your last write, unless told of it.

## text CHECKLIST_FORM lead trail
next is a checklist: the item keeps every step in the order written, open, done or dropped, and next holds the open
steps. A step of yours leaves next only by being marked in the same update: done=[…] when the work was finished,
dropped=[…] when it is no longer wanted, each entry a step's 1-based position (marked steps count; get lists them
under `checklist:`) or the exact text of its first line (the call example is in the description above). An update that
replaces or removes (next="none") your lines of next and leaves one out unmarked keeps that step open as written and the reply names it (end it with done=[n] or dropped=[n]); another session's lines are never touched by your next. Parameter reword (map, position or
first-line text → new text) gives an open step of yours new words and keeps its number, place and open state (leave
next out and the line is changed for you); a line reworded in next alone is a new step, and the old one stays open. A reword is the same action in other words, never the old text with progress added. A reword of a step of his
(a line opening with `{{OWNER}}:`) is done as drop plus add, and the reply says so: the old step is dropped and shows as
dropped, and the new words are a new step at the end (a long text is split into one line per action, as for step=); a reword of the
line the server made from step= is taken as the new step text, and one of the line made from an ask is refused with the field to change (ask=). Refused: a step of
another session, one already done or dropped, one also in done or dropped, a text of several steps or one
another open step reads; a different action is a new line of next. done and dropped mark any open step, whoever wrote
it, except a step of his (a line opening with his name) while the item asks him: that one is ticked when he answers,
and done on it is refused (dropped on it is undone while the item still asks him). The server makes his step itself:
when an item asks him for a decision (needs=decision with an ask) or a step (your-step), it adds the open step `<his
name>: <what to decide>` at the end (a line you wrote that says the same is adopted), shows his answer on it, and
drops it when you withdraw the ask or the step; a step he already answered stays done. clear_next=true is a deliberate
wipe: every line it removes becomes a dropped step, by you. A marked step stays on the page with who marked it and
when; History says `step done: …` or `step dropped: …`. done or dropped alone, with no next, takes the step out of
next; when two open steps read the same, the position names the one marked. A step written again after it was marked
is a new step. {{OWNER}}'s word that his step is done checks every open step of his (each next line that starts
`{{OWNER}}:`); a note he sends ticks the step the server made and leaves your lines open for the session that takes
the item to mark done.

## param REWORD
New words for open steps of your own next: a mapping from a step (1-based position, or the exact text of its first
line, as done takes them) to its new text, e.g. {"3": "my-x: wait for the new build"}; the step keeps its number and
stays open, and the new text is one step that opens with who takes it (the rules are under Parameter reword in the
description). A step of his is reworded as drop plus add, and the reply says so.

## param WORK
The status of your open step, one line per call: {"text": "PR 83 up", "state": "in progress"}. It replaces the status
of your first open step in place (the step is the stage, such as "stage 11: auth and who", and the status says where
you are in it; the page keeps one line per step, so a night of updates is one line). text is at most {{WORK_TEXT_MAX}}
characters (details go on the project page). state: in progress (the default) | done; done also ticks your first open step, as
done=[n] does, unless the same call has done=[...]: then only the steps done names are ticked and the work line is not recorded. A status has no waiting state: a wait is until, after or wait_kind. With no open step of yours, one is made from the text. {"remove": true} clears the status. Written by
the mover or a session named in needs; it changes no needs and owes no page. A project builder's step with a status in
progress (changed within 90 minutes) tells the stall pass and the balancer that a build subagent is running on the
item, so the item is not handed on meanwhile; a status left in progress stops hiding the item after that, and a status
sent again unchanged keeps its old time, so a long job changes the words or marks the step done when the subagent
ends.

## param DONE
Open steps you finished: positions (1-based, marked steps count) or the exact first line: done=[1] or done=["my-x:
build it"]. A step of yours that next leaves out must be here or in dropped.

## param DROPPED
Open steps that are no longer wanted, named like done: dropped=[2]. A different action is a new line of next, not a
reword.

## param WAKE
Retired: a call that passes it is refused. The date a wait ends on is until.

## param ASK_BY
Retired: a call that passes it is refused. The day a wait on another item, a relay or an event comes back to someone
if it has not ended is until, YYYY-MM-DD, tomorrow at the earliest: until="<day, within {{CAP_DAYS}} days>".

## param UNTIL
The one date a wait ends on, in the future: YYYY-MM-DD, or YYYY-MM-DDTHH:MM, in the board timezone (a relay or event
wait takes the day alone, YYYY-MM-DD: the day it comes back to someone. Left out, a wait_kind passed in the call takes the
next day or the day the item's words give; a wait with no end and no wait_kind in the call (on an item, an anchor, a relay
or event, a park) takes the server's backstop day, 14 days from today, and the reply says so; never while the item waits on
{{OWNER}}). Alone it is a wait; a wait on your own item
also needs wait_reason (at least {{WAIT_GUARD_REASON_MIN}} characters), a date more than {{CAP_DAYS}} days out needs a
wait_basis, and a park (wait_kind="time") within the cap needs his recorded words. An item with an until is waiting
(outside a hand-off: in an update that hands the item to another session the date parks nothing, it is the hand-off's
backstop and the item stays active in the new mover's lane (unless the item is parked or carries wait_kind, wait_basis
or an after link, in this call or stored by an earlier one: then the date stays a wait)); wait_kind goes only beside
it (none: it waits on the date alone). until="none" drops it. Moving it later with nothing else changed is refused, as
a clock renewal (see the wait text in the description). Beside waits it is the list's backstop day.

## param NEXT
Your lines of the checklist, one step per line, each opening with who takes it, then a space (a label such as
`Status:` names no one). It replaces only your own lines: write again every open step of yours that stays and mark the
others in done or dropped (or reword) in the same call. Steps 1 and 2 open, step 1 finished: done=[1], next="my-x:
test it\nmy-x: open the PR". An item that stays open keeps one open step, a parked one the step its date leads to. Never
reword an open step to add progress. next="none" removes your open lines; an empty next is next not passed.

## param ASK
The one line a needs=decision item carries, all four parts in this order, each opening with its label and a colon,
joined by " · ", no line break, at most 240 characters in all, every one counted, a link's address too: ask="Decide: whether to approve the sample schema · Recommend: Approve · Stakes: waiting a week
delays the demo · By: Mon Jun 8th 2099" (By is a date in words, or no date). A real choice, not "have you done X?";
one question per ask, whose answers are the options (no ";" between decisions, no second question joined by "and say if",
"and tell me whether", "and decide whether" or "and, if so, …" when the clause ends there; a bundled action such as
"retire the queue and also allow its jobs to drain" or a conditional such as "merge now and, if green, release" or "approve
it and, if so, start Monday" is one decision and passes). An ask that approves or picks a design, plan, proposal, draft or spec
links it in the ask itself, [design](https://…), never a path on a machine or a summary alone; a short link text keeps room under
the limit (a subscription or payment plan, software package or compound such as "the design system rollout" needs none).
A link in the ask goes to a short decision page made for it (an artifact, a document or a mockup page), never a long project or notes page.
With no options listed the Recommend is a yes or a no. The ask line never says I, you or me. "none"
or clear_ask=true withdraws it.

## param HOLD
Retired beside a date: a call that passes hold with a date is refused. A park is until=<date> with wait_kind="time"
and wait_basis (the form is under wait_basis). It reads as waiting, not on agent; clear_hold=true ends a park the item
stores. On a relay or event wait no flag is stored (the wait is the park until its day) and the park ends a stored
work-in-hand state.

## text STEP_FORM lead trail
step (update only; create sets no step): a ONE-LINE summary of what the person whose step it is does, for an item that
is his step, at most {{STATE_LINE_MAX}} characters. It points at his Next lines and never holds a command: every shell
command he runs goes in a next line that starts `{{OWNER}}:`, whole in backticks (or a ``` block), {{P_PLACE_STEP}}A
step that carries a command (a backticked span with a space in it that reads as a shell command, a `! ` line, a ```
block) is refused, and the refusal says to put the command in a next line that starts `{{OWNER}}:` (a step stored with
a command before keeps the older checks on a write that leaves it alone{{P_OLD}}). A button or menu label is not a
command: put it in bold or quotes, not backticks ("Make a copy", **Sort by date**). A bare command
with a flag, path or quoted argument, written outside backticks or a fence after a run cue or a place phrase
({{P_EX2}}), is a command too: the step carries none, and a next line gets it in backticks, whatever the item's state, so the board shows a copy
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
The reason an until (on a relay or event wait, its day) carries when it lies past the cap or parks the item: one line of 12 to 300 characters that names the
real date it stands on as YYYY-MM-DD, from the until day to 30 days after it: wait_basis="error-log soak ends <that day, YYYY-MM-DD>"; a date outside the board reads the same way, wait_basis="vendor
reply due <YYYY-MM-DD>" (a basis with no date is refused). Three
dates take it, each basis bound to the date it was given for: a park's, a verifying item's, and an until more than
{{CAP_DAYS}} days out (it lifts the cap for that date alone, up to {{BASIS_MAX_WAKE_DAYS}} days: a date
further out is refused whatever the basis). A bare date within the cap takes wait_reason on your own item and a basis
there is dropped, the reply saying so; a new park within the cap takes his recorded words, not a basis. A park with a date and no basis takes the line of next or the description that says
what the work waits for.

## text NEXT_FORM trail
next replaces only your own lines: every line of next remembers the session whose update wrote it (the sender, or the
item's creator when the call names none; not the name the line starts with). next=<lines> takes the place of the lines
you wrote before, where the first of them stood (at the end when you had none) and leaves every other session's lines
where they are; a step of yours that it leaves out stays open unless marked (done, dropped, reword).
next="none" removes only your own lines; clear_next=true wipes every line, whoever wrote it, and with next given the
wipe comes first and your lines are then set. A line of yours that another session's open line already reads the same
is not added a second time. A close clears next whoever wrote it.

## text UPDATE_DESC trail
Update an item; only the fields you pass change.{{OFF_MAP}} Right calls (sender = you): steps 1 "my-x: build it" and 2
"my-x: test it" open, step 1 done: update(item_id="board#N", sender="my-x", done=[1], next="my-x: test it\nmy-x: open
the PR") (next lists every open step of yours that stays); reword an
open step: reword={"2": "my-x: ship the export"}; drop a step: dropped=[2]; work: the status of your open step, one line per call: work={"text":
"PR 83 up", "state": "in progress"}; park for a work window: until="<last day of the window, YYYY-MM-DD>",
wait_kind="time", wait_basis="soak ends <that day>" (the basis names its date, YYYY-MM-DD; it goes with a date past
{{CAP_DAYS}} days; within them his recorded words stand in); a wait until a date on your own
item: until="<tomorrow or later, within {{CAP_DAYS}} days, YYYY-MM-DD>T04:00", wait_reason="the nightly run finishes
at 03:00"; wait on another item: after=["board#N"], until="<day, within {{CAP_DAYS}} days>"; description="- Goal: the export finishes in under a minute\n- Problem:
the nightly run takes 9 minutes" (short `- ` bullets, never a paragraph; every line, `- ` included, at most {{DESC_LINE_MAX}} characters, at most
{{DESC_MAX_LINES}} lines); close: the complete tool. status: open | completed (`needs` says whose move it is).
{{CLOSE_FORM}}A new or reworded open step that opens with a front agent is refused on an item another session moves:
open it with the mover's name, or send `For <agent>,` to its project page (a step it already holds stays). With no
builder there, its front agents may take the item by mover= or a step behind an open step
(the item moves to it, told, when the step before is done). A date alone is a wait: the item waits until that date. Work: Written by the mover or a session named in needs. A plain write by a background agent that is not in needs adds it there, and `then` follows the first session in needs; a write that sets needs itself, parks the item or only files it does not, nor does one on an item left for him to move before and after it: to leave an item again, pass needs without yourself. {{ITEM_FORM}} A new subject, a changed Goal sentence or a first Goal that leaves an open item titled as a question, a statement or a should sentence gets one reply line: send subject= as the task. {{NEXT_FORM}}
ask="none" clears it (so does clear_ask=true). An ask or options written alone (no needs, mover, wait, status or step in the
same call) on an open item that is not on his call is accepted and adds the decision need itself, as needs=["decision"]
beside the ask would: he becomes the mover, and the reply says "added the decision need; the question is on his move
now". On a parked item (a wait is set) the ask and options are stored, no need is added and the wait stays;
the reply says he does not have the question, which does not reach his move while the item is parked; to put it
on his move, unpark with clear_wait=true (and clear_hold=true if it holds) and needs=["decision"] in one write.
A write that leaves an ask standing on an item you move or wrote ends
with a one-line reminder to withdraw the ask if it is wrong or moot; a write that sets an ask shows {{OWNER}}'s
comments and notes since the item's last ask, so one that already answers it is seen before you ask again. His note on
a step that only says he did it ("ran it"; "run it" is a request and ticks nothing) ticks the step, and one in which
he says he will do it later ("I'll do it tomorrow evening") parks the item until then; any other note (a question, a
negation, a deadline, more than that) goes to the session to judge. The ask's mockup rule above also holds on an
update that sets the ask, description, next, needs or options or puts the item on needs=decision. options=[] (or
"none", or clear_options=true) clears the options, which need no recommended one then (refused while the ask is an
open question; a non-empty list still takes 2 to 6 entries, exactly one recommended). When {{OWNER}} answers by
picking an option, the server clears the ask and the options itself and keeps his answer with the option's label and
line. A client whose tool has no ask parameter refreshes the ask by writing the new line, in the ask's form, as the
first line of next. When this work settles or changes a premise of another open item, update that one too, in the same
turn. item_id: board#N; a bare number N or #N is read as board#N (the reply says so), in a close too; the same for after and superseded_by. until takes YYYY-MM-DD, or YYYY-MM-DDTHH:MM for a time of day, {{TZ_ABBR}}; a full ISO time with
seconds or a UTC offset is converted to that minute in {{TZ_ABBR}}, and the reply says so. At that moment the server
tells the item's mover and the sessions in its needs once and drops the date. A doing item whose date is over an hour away and whose every open step waits for a later date ("after Mar 2", "until
Mar 2"; a deadline such as "by Mar 2" or "due Mar 2" is no wait) is listed as waiting, and the audit asks why the step
cannot run now. Parked
= an open item waiting until its next move is due: until with wait_kind="time", with what it waits for;
at its date the server releases it, tells the sessions in its needs (else its mover; refresh the ask
then) and returns it to the lane its needs give it. Meanwhile it reads as parked (a waiting state), not as work moving
on agent; needs and due stay as they are. A write to an item whose needs hold decision drops its park (its date stays).
Park his call instead, from a decision item or a doing item: needs=["<session>"] (the session that picks it up at the date; a front agent will do), until=<YYYY-MM-DD or YYYY-MM-DDTHH:MM>, wait_kind="time" (or event, relay, item where the wait stands on more than the date), wait_basis="<what the date is,
with its date YYYY-MM-DD>" and mover={{OWNER}}; the ask and options stay on the item, and at the date they come back to him: a decision item returns with its ask and options, a doing item with its ask if it had one. Without wait_kind an
item with him as mover and a date is refused as having nothing for him to do. A park of {{CAP_DAYS}} days or less needs his recorded words (said=[Acked-by …], or his answer on the item); a longer one needs a wait_basis. {{OWNER}} parks on his word. A park always names what it
waits for: {{OWNER}}'s words, the items that must close first (after), a notice from an anchor scoped to the item, a
pane recycle (recycle=true), or the end of a window the work itself needs; a park with a date and none of these is
refused. A park with no date is not refused: the server stores a backstop day 14 days out (with a wait_basis that names a
date ahead, that date; with a wait_kind, that kind's date as above), marked as set by the server and said in the reply, and its
mover replaces it with the real day; never while the item waits on {{OWNER}} in any form (the wait text above), so a park
of his call always gives its date. Work moving in real time stays on agent however long it takes (a build, tests, a review, a release or its
queue, a run or subagent of yours): do not park it: its mover's park is refused while its subagent runs on it. A
session parks its own item when the work itself needs a wait-and-see window (a soak, a log or data collection window,
a trial week, a timer it started): until=<when the window ends>, wait_kind="time", wait_basis="<what the window collects>
ends <YYYY-MM-DD>" (a window of {{CAP_DAYS}} days or less on your own item is a bare until with wait_reason). A session does not park to defer work it could do now: an item not parked is one its mover can
move now, so work it in your next free turn. When your write sets or keeps a date with no park over an hour ahead, you are the
item's mover and every open step opens with a time at the date's hour or day ("at 03:00", "on <that day>", "tomorrow
at 9"), the server parks it itself (parked, wait_basis from your wait_reason; the reply says `(parked: …)`); to work
a step now, write it as the action and pass clear_hold=true. A next line that says in words it waits for an open item,
a pull request's merge or release, a machine coming back online or a link, while the item stores no wait for it, is
set by the ten-minute pass when the line is the item's only open step and one thing is named (after, an event wait, an
anchor wait, or a step proof): clear_after=true, clear_wait=true or step_proof="none" sends it back and the server
leaves that line alone. Neither of these applies to
an action to take now, another party's step in flight, or an item not on agent (parked, waiting on {{OWNER}}'s
decision or an open after item, needs=external, outside, verifying, blocked). An item that waits on another item is
not parked but names it: after=["board#N"]. Nor is one that waits on {{OWNER}}: needs=decision with its ask, after=<the item that carries the ask>, or his call parked as above. An item that waits on a named person outside (needs=external) is not parked,
unless the thread it waits on is anchored to it (anchors(project, add=[url], items=[its id])) and named in next: park
that one with a backstop date (until, at most [waiting] cap_days out unless his words are on the item), since the notice may
never come; the server releases the park when the project's router (or the project's builder, else its -main agent)
passes or merges a notice from that anchor (never when it drops one; in a project nobody rules, when any notice from
it arrives), and tells the sessions in its needs (else the project's builder, else its -main agent). clear_hold=true
releases it now (its date goes with it); until="none" drops the date: an item that waits on
nothing else is active again, and a park stays only when an after, an anchor or a recycle still holds it. mover hands
the item over: set mover=<session> (then=<who takes it after {{OWNER}}'s answer or step>, kept only while he is the
mover; on an item a session moves it is dropped with a note) and the new mover is told; a
front agent gets no hand-off notice, so an update from another session that sets mover or then to a front agent gets the project's builder instead (the reply and History say so; send it again to keep it as
sent; the one exception is a hand-back: the front agent holds the item's first open named step as the item stands before this write (a step
line this call adds does not count, and the call leaves that step open), the front agent is a live front agent of the item's project, and the sender is
the project's builder or the item's mover when that is no front agent: it is kept as sent at once, and a mover is told it is handed back, as a turn; with no builder it is refused, except from a listed session to a front agent of the item's project; a sibling
front agent is kept on {{OWNER}}'s words in said, see mover); take over another session's item only when
asked; a session about to be retired first hands over or completes its open items. mover={{OWNER}} alone is refused on
an item that is doing: it needs step=… or needs=decision with ask=… in the same write (the refusal says so). An update
that leaves an open item in a state that is {{OWNER}}'s (his step, or needs holding decision) and names no mover sets
mover={{OWNER}} itself and moves the stored session mover into then (set then=<you> to have the item come back to
you), and the reply ends with a `(mover: <session> → …)` note; when a save ends his state the mover he held goes back
to then; a write that names the mover or clears it (clear_mover), a rename, priority or project write, a re-bullet and
a close are left alone. When an item's work moves to another project's session, hand the item over in the same turn:
mover = that project's user-facing agent (or the background agent doing the work), project = its page. The creator is
not moved with it. owner, the old name of mover, is accepted for a few more days with a note in the reply and then
refused: say mover. sender = your own session (name or cse_… id) when you edit an item you are not the mover of (a
session named in needs always passes sender=<itself>): the page update the edit owes is then yours, not the mover's (a
create, a complete, or an update to description, next, needs, status, due, after, or the park and its date owes one).
{{SENDER_MIRROR}}Pass clear_needs=true (or needs="none") to remove the needs badge, clear_check=true (or check="none")
to remove the done check, clear_due=true (or due="none") to remove a date that no longer holds (a postponement with no
new date). priority: p1 | p2 | p3, shown but not sorted. project re-files the item under another page (projects/<slug>
or infra/<slug>; pass the page `(filed on X)` names, never the shown top-level key). A state change also confirms the
item (it reads fresh again); the confirm tool says it is still true without changing it. recycle=true: the item's work
waits for the panes to be relaunched (a connector re-login, a settings, hook or plugin change, a CLI update; not a
change to a connector's tools, which claude.ai refreshes on its own within about a day); set it only once the change
it waits for is installed (merged and deployed, or provisioned), never before: an early flag recycles the panes too
soon, for nothing (a flag set before the provision recycled the box too early). Set it on the item the change serves:
a recycle is never an item of its own (create refuses one), and for a change no item covers, {{WHEN_IDLE}};
{{FLEET_TOOL}} runs a flagged recycle itself, the board shows one "Pane recycle pending for … ({{FLEET_TOOL}} runs
it)" status line while an open item not parked carries it, and when {{FLEET_TOOL}} reports the recycle done the
server clears it and tells you to re-read the item and resume. clear_recycle=true takes it off by hand. A question {{OWNER}} asks on an item (in his answer, a note on his step or a comment on it) is
answered by the mover on the item itself, not only in its own pane: rewrite the description, and the options where it is
a pick, the description saying it answers his question. A result he asks for there belongs on the item too. His question is never posted with said and never taken as his call; only his
conclusions are. An answer or comment he types with no option picked that is nothing but a question is marked as one by the server. Typed in place of a decision it takes the item off his call with nothing decided:
answer it as above, then put the decision back (needs=decision with its ask); the same ask line is accepted at once after the description is rewritten, and refused before. A pick, and words that open with a yes or a
no, or hold a sentence that asks nothing (or a part set off by a semicolon or a dash), are his decision; a statement joined to its question by a comma alone, with no yes or no in front, reads as a question. {{NEEDS_FORM}} {{CHECK_FORM}}check="" changes nothing, and a new check passed replaces the old one.

## param project
Re-files the item under this page, as `(filed on X)` shows it, never the shown top-level key.

## param wait_reason
What the step waits on that is not available now (a reply, a build or test still running, a window the work needs, a
resource that is down), at least {{WAIT_GUARD_REASON_MIN}} characters: wait_reason="the nightly run finishes at
03:00". Required when this write sets an until, or a line of your own next dated later than today, on an item you move,
or it is refused (a model may refuse it too when the step could be done now). Not stored on the item. A park
(wait_kind="time" with wait_basis), a wait on another item (after) and needs decision or external need none.
A new wait_kind="time" within {{CAP_DAYS}} days is a park, which needs {{OWNER}}'s words (said) unless the item is
already parked, on a time wait or verifying (a wait_basis does there): to check back on your own work send until and
wait_reason with no wait_kind. A date after by, due or before is a deadline, not a wait.

## description update
{{UPDATE_DESC}}{{CONTACT_FORM}}{{GLOSSARY_FORM}}{{MODEL_FORM}}{{CHECKLIST_FORM}}{{STEP_PROOF_FORM}}{{DRAFT_FORM}}{{STEP_FORM}}{{STALL_SHORT}}{{SELF_WAIT_FORM}}{{WAIT_FORM}}
