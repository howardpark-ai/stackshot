## description message
Send a message to another Claude session through {{NAME}}, only where Claude's own cross-session messaging cannot
reach (cloud → pane, cloud → cloud, another machine → the server box); on the same machine use the native SendMessage.
Right calls (to = the target's session id (cse_… for a cloud/Cowork
session, the transcript UUID for a pane), its pane name, or projects/<slug>): ask a front agent (a session {{OWNER}}
talks to; the sessions tool shows each role) for input {{OWNER}} must give: message(to="widgets-main", sender="my-x",
text="{{FOR_OWNER}}\nboard#N: decide whether the export ships on Friday; I would ship it."); a plain result (a build is done,
it is live, an FYI): message(to="projects/widgets", sender="my-x", text="PR 12 is live", fyi=true), or put it on the
item (update, complete); a question to a background agent, the id cited only for context:
message(to="widgets-builder", sender="my-x", text="Does `board#N` need the export in the nightly run?"); a hand-off of
an item's done step, which names the item id, written as a plain word, not in backticks or quotes:
message(to="widgets-builder", sender="my-x", text="board#N: the design is done, build the export"), and the server
then names that agent in the item's needs, unless that would leave the item with a second mover (another session
already moves it, or it waits on a decision): the reply says so in one line: hand the item over with
update(mover=<agent>), which tells the new mover itself. An item id cited only for context, not handed over, goes in backticks, since a plain-word id names the receiver on that item. A front agent is given a turn only by what {{OWNER}} has to do: its
message carries {{FOR_OWNER}} on its first line (except fyi=true, below) and names, as a plain word, an open item of his (needs hold decision, or the step is his, or he asked it to tell him about it); naming none, it is held for the agent's next turn and starts none: put his step on an item and name it. It starts a turn only while he talks with that agent or has it in tell_him of an item it names; else it is written onto the open items of his it names (three at most), the reply naming them, any it left out and a History line cut to 360 characters, or held for the next turn when none can take it; a sibling front agent that quotes his words on a line `Acked-by: "<verbatim>" (time, session <name>)`, checked as said is, has it held. One exception, off unless the instance lists the front agent in `[front] result_turn_agents`: a message from a session that agent handed work to is the result coming back and starts the agent's turn, marked or not, whether or not he is there, and is not tested as a status report. A session was handed work when the agent wrote to it within the configured period (any message that reached it), or when the message names an open item the session moves now that the agent itself handed it (the item's hand-off record; having made the item or being its contact is not enough); a script, the person's own message, a peer front agent and fyi=true never qualify, and one session starts at most the configured number of such turns an hour in one agent (`[front] result_turn_cap_per_hour`; past that, or when the cap cannot be counted, the message is handled as below, held for the agent's next turn; two messages at the same moment can exceed it by a few). The result is also written onto the one to three open items it names, as a History line. The agent's reply to the session is itself a hand-over, so two sessions can wake each other: send fyi=true when a message needs no reply. A background agent's hand-back, a done, taken or no-action note, is tested first and is never an answer: written onto the item it names, else held. Any other unmarked message is delivered only as
the answer to a question it wrote to you, while he is in that conversation (30 minutes); later
it goes onto the item it names, else is held; so is a front peer's or a background agent's own. Any other goes to the project's
background agent (none: held). A front agent marks a question with question=true; only a reply to it, within a day, is an answer; a `?` marks nothing. A done, taken or
no-action note (a plain status report, nothing needed from {{OWNER}}, FYI, no reply needed, …), marked or not, is held. A phrase is a note only as its own statement: opening a sentence or line, or ending a clause after , ; ( or a dash; not mid-sentence or asked. A marked one naming an open item of his is delivered anyway. A background agent's
message to a front agent (marked, or a project message that opens For <front agent>) that names one to three board
items is held back only when it clearly reads as a plain status report: the reply then begins 'Not
delivered: written onto <item> as a History line ...' and the message sits on the item. It reads as a plain status report only when every sentence says done, live, merged, released, deployed, closed, opened, fixed, passes, green, recorded, unchanged, complete, finished, removed or retired (taken only as a sentence of its own, stopped only as 'is stopped'), and the text has no question mark (a URL's included), no prose in a code span, no plan (will, if, when, then), no person or front agent named to act, no opening yes or no and no word of trouble, lack, negation, waiting or asking (failed, blocked, need, must, review, ready, decide, please, not, yet, still, nothing, none, except, only, partly ...). A fixed no-action phrase skips only the status words. Everything else is delivered (the reply begins 'delivered'), and so is a
message whose item waits on a decision (needs: decision) or names the front agent in its needs. A move to
needs=decision reaches {{OWNER}} on the board, not through a message. A merge-queue group number ("group g7",
"[g7]") names no item.
A message that asks nothing of its recipient is sent with fyi=true (news, a result, a status it need not act on): a
background agent gets it with the first turn it takes, once (the reply begins 'held for <agent>'s next turn'), and it
names the agent in no item's needs, so send it again without fyi if it does ask; to a project it is held the same way
when the router passes it to an agent; to a front agent it is held for that agent's next
turn (a listed one too), needs no {{FOR_OWNER}} and starts no turn ('not passed on' when its hook cannot fetch held lines); a message that carries {{FOR_OWNER}} or needs: decision is delivered, written onto its item or held whatever the
flag says. A message to a retired session goes to its project for the router to rule, the reply beginning
`'<name>' is retired (<why>), so this went to its project …`; it is refused only when no other agent of a project can take it. A page key spelled another way (case, - for /, projects/infra-x for infra/x) is read as the one page it matches, the reply saying so; none or two, refused with the nearest keys. A message to
a project is answered `held for the router — the router rules notice <id> …`, ending `get(item_id="<id>") shows its
ruling`: call get. The reply adds NOT PASSED ON when you move the item it names: write
the item to hand a step on. A reply that begins `inbox` means the line waits in the server's inbox for the session's
machine to fetch it (about a minute){{INBOX_FLAG}}. The receiver sees a labelled [stackshot
message] turn framed as a teammate's request, never as {{OWNER}}'s instruction or approval.{{OFF_MAP_NOTE}}.

## text INBOX_FLAG_TEXT
; if the session is running and the line is still there after {{INBOX_FLAG_MINUTES}} minutes, the fleet's keeper is
told why, and so is the running pane that sent it (not a cloud or Cowork sender); a line held on purpose, by a
relaunch hold or a pause, is not reported

## param to
Who gets it: a session name or id, or projects/<slug>, which the router rules.

## param text
The message, at most {{MSG_MAX}} characters. To a front agent its first line is {{FOR_OWNER}}, then the item's plain id and what is needed; a
plain result goes to projects/<slug> or onto the item.

## param sender
Your own session name or id.

## param fyi
True when the message asks nothing of its receiver (news, a result, a status). A background agent or a front agent
then gets it with its next turn instead of a turn of its own. Default false.

## param question
True when a front agent asks the session it writes to a question: only a reply to it is an answer. Not with fyi or in {{OWNER}}'s own name. Default false.
