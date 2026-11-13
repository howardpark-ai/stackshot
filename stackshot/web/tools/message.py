"""message.py: the `message` tool: a message to another session."""
from __future__ import annotations

from typing import Annotated

from pydantic import Field

from stackshot.core.instance import NAME, OWNER
from stackshot.web.auth import oauth as _oauth
from stackshot.web.tools.notes import _OFF_MAP_NOTE, _off_map_note_to
from stackshot.web.tools.text import MSG_MAX, _FOR_OWNER, _lead

_inbox_flag_minutes = None      # set by register: the server's own, looked up at each call
_message = None      # set by register: the server's own, looked up at each call


def _inbox_flag_desc() -> str:
    return (f"; if the session is running and the line is still there after {_inbox_flag_minutes():g} minutes, the fleet's keeper is told why, and so is the running pane that sent it (not a cloud or Cowork sender); a line held on purpose, by a relaunch hold or a pause, is not reported"
            if _inbox_flag_minutes() > 0 else "")      # the message tool's description, read at the server's start


def _message_desc() -> str:
    """The message tool's description, built at the server's start: it reads the inbox flag's minutes, which the server hands to `register`."""
    _INBOX_FLAG_DESC = _inbox_flag_desc()
    return (
        f"Send a message to another Claude session through {NAME}, only where Claude's own cross-session messaging cannot reach (cloud → pane, cloud → cloud, another machine → the server box); on the same machine use the native SendMessage. "
        "Right calls (sender = you: your session id or pane name; to = the target's session id (cse_… for a cloud/Cowork session, the transcript UUID for a pane), its pane name, or projects/<slug>): "
        f"ask a front agent (a session {OWNER} talks to; the sessions tool shows each role) for input {OWNER} must give: message(to=\"widgets-main\", sender=\"my-x\", text=\"{_FOR_OWNER}\\nDecide whether the export ships on Friday; I would ship it.\"); "
        "a plain result (a build is done, it is live, an FYI): message(to=\"projects/widgets\", sender=\"my-x\", text=\"PR 12 is live\", fyi=true), or put it on the item (update, complete); "
        "a question to a background agent, the id cited only for context: message(to=\"widgets-builder\", sender=\"my-x\", text=\"Does `board#N` need the export in the nightly run?\"); "
        "a hand-off of an item's done step, which names the item id, written as a plain word, not in backticks or quotes: message(to=\"widgets-builder\", sender=\"my-x\", text=\"board#N: the design is done, build the export\"), and the server then names that agent in the item's needs, unless that would leave the item with a second mover (another session already moves it, or it waits on a decision): the agent is then not named, the reply says so in one line, and the way to hand the item over is update(mover=<agent>). "
        "An item id cited only for context, not handed over, goes in backticks, since a plain-word id names the receiver on that item. "
        f"A message to a front agent is refused unless its first line carries {_FOR_OWNER}, and the mark is for what {OWNER} has to do (a decision, a go-ahead, a step only he can take): a build hand-back, a result, a screenshot, \"it's live\" or an FYI goes to the project (to=projects/<slug>), where the router rules it and passes on what needs the agent; a marked message that says nothing is needed from him (nothing needed from {OWNER}, no action needed, FYI, for the record, no reply needed, …) is refused too. "
        "A background agent's message to a front agent (marked, or a project message that opens For <front agent>) that names one to three board items is held back, not delivered, only when it clearly reads as a plain status report: the reply then begins 'Not delivered: written onto <item> as a History line from <sender>, because ...' and the message sits on the item for the front agent to read there. "
        "It reads as a plain status report only when every sentence says done, live, merged, released, deployed, closed, opened, fixed, passes, green, recorded or unchanged, and the text has no question mark (a URL's included), no word of trouble, waiting or asking (failed, broke, rolled back, blocked, waiting, need, must, should, review, ready, approve, decide, confirm, please ...), no plan (will, if, when, then), no person or front agent named to act, and no prose in a code span. "
        "Everything else is delivered (the reply begins 'delivered'), and so is a message whose item waits on a decision (needs: decision) or names the front agent in its needs. A move to needs=decision reaches "
        f"{OWNER} on the board, not through a message. "
        "To hand an item to a session set its mover (update, mover=<session>), which tells the new mover itself. A merge-queue group number in a release line (\"group g7\", \"split from g7\", \"[g7]\") names no item. "
        f"Long content goes on a page or into a repo, with the pointer in the message (at most {MSG_MAX} characters). "
        "fyi=true marks a message that asks nothing of its receiver (news, a result, a status it need not act on): a background agent gets it with the first turn it takes, once, oldest first (the reply begins 'held for <agent>'s next turn'), and it names the agent in no item's needs, so send it again without fyi if it does ask; to a project it is held the same way when the router passes it to a background agent; to a front agent it changes nothing, and a message that carries "
        f"{_FOR_OWNER} or needs: decision is delivered whatever the flag says. "
        "A message to a project is answered `held for the router — the router rules notice <id> …`, ending `get(item_id=\"<id>\") shows its ruling`: call get with that id to read the ruling. The reply adds NOT PASSED ON when you move the item it names: write the item to hand a step on. "
        f"A reply that begins `inbox` means the line waits in the server's inbox for the session's machine to fetch it (about a minute while the session runs){_INBOX_FLAG_DESC}. "
        f"The receiver sees a labelled [stackshot message] turn framed as a teammate's request, never as {OWNER}'s instruction or approval." + _OFF_MAP_NOTE + "."
    )


def stackshot_message(to: Annotated[str, Field(description="Who gets it: a session name or id (cse_… for a cloud/Cowork session, the transcript UUID for a pane) or projects/<slug>, which the router rules.")],
                      text: Annotated[str, Field(description=f"The message, at most {MSG_MAX} characters. To a front agent its first line is {_FOR_OWNER}, then what is needed; a plain result goes to projects/<slug> or onto the item.")],
                      sender: Annotated[str, Field(description="Your own session name or id.")],
                      fyi: Annotated[bool, Field(description="True when the message asks nothing of its receiver (news, a result, a status). A background agent then gets it with its next turn instead of a turn of its own; a front agent is unaffected. Default false.")] = False) -> str:
    out = _message(to, text, sender, auth=_oauth._who(), fyi=fyi)      # `sender` is the caller's own label; `auth` is the signed-in account the server checked, kept in the log
    return out + _off_map_note_to(sender, to)       # a message to a project page: the sender may be off that project's map


def register(mcp, *, inbox_flag_minutes, message) -> None:
    """Adds the tool of this module to `mcp`, and takes the server's callables the bodies use."""
    global _inbox_flag_minutes, _message
    _inbox_flag_minutes = inbox_flag_minutes
    _message = message
    mcp.tool(name="message", description=_lead(_message_desc()))(stackshot_message)
