"""message.py: the `message` tool: a message to another session."""
from __future__ import annotations

from typing import Annotated

from pydantic import Field

from stackshot.web.auth import oauth as _oauth
from stackshot.web.tools.notes import _off_map_note_to
from stackshot.web.tools.text import MSG_MAX, _lead, load_text

_T = load_text("message", {"MSG_MAX": str(MSG_MAX)}, late=("INBOX_FLAG", "INBOX_FLAG_MINUTES"))

_inbox_flag_minutes = None      # set by register: the server's own, looked up at each call
_message = None      # set by register: the server's own, looked up at each call


def _inbox_flag_desc() -> str:
    minutes = _inbox_flag_minutes()      # the message tool's description, read at the server's start
    return _T.piece("INBOX_FLAG_TEXT", INBOX_FLAG_MINUTES=f"{minutes:g}") if minutes > 0 else ""


def _message_desc() -> str:
    """The message tool's description, built at the server's start: it reads the inbox flag's minutes, which the server hands to `register`."""
    return _T.description("message", INBOX_FLAG=_inbox_flag_desc())


def stackshot_message(to: Annotated[str, Field(description=_T.param("to"))],
                      text: Annotated[str, Field(description=_T.param("text"))],
                      sender: Annotated[str, Field(description=_T.param("sender"))],
                      fyi: Annotated[bool, Field(description=_T.param("fyi"))] = False) -> str:
    out = _message(to, text, sender, auth=_oauth._who(), fyi=fyi)      # `sender` is the caller's own label; `auth` is the signed-in account the server checked, kept in the log
    return out + _off_map_note_to(sender, to)       # a message to a project page: the sender may be off that project's map


def register(mcp, *, inbox_flag_minutes, message) -> None:
    """Adds the tool of this module to `mcp`, and takes the server's callables the bodies use."""
    global _inbox_flag_minutes, _message
    _inbox_flag_minutes = inbox_flag_minutes
    _message = message
    mcp.tool(name="message", description=_lead(_message_desc()))(stackshot_message)
