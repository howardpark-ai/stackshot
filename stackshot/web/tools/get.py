"""get.py: the `get` tool: one item, or the items of a project, with what the server shows about them."""
from __future__ import annotations

from typing import Annotated

from pydantic import Field

from stackshot.model.ids import _norm_id
from stackshot.service.store import _load
from stackshot.web.auth import oauth as _oauth
from stackshot.web.page_debts import _nag
from stackshot.web.tools.text import _lead, load_text

_T = load_text("get")

_fmt = None      # set by register: the server's own, looked up at each call
_notice_asked = None      # set by register: the server's own, looked up at each call
_notice_report = None      # set by register: the server's own, looked up at each call


# What an agent does when the stall pass takes a wrong step; the same path is in stall.py's docstring and docs/stall-and-ladder.md.
_STALL_FORM = _T.piece("STALL_FORM")


def stackshot_get(item_id: Annotated[str, Field(description=_T.param("item_id"))]) -> str:
    """Read one item by id as shown (board#N, or the older letter-and-number form for an older item). It shows `needs:` (whose move it is: decision, external and the sessions named), `after:` (the items that must close first, each with its state), and `observers:`. It leads with `mover:` (who moves the item now) and `then:` (who takes it after the answer or the wait); History says who created it. `model:` says alive or waiting, the mover and what it waits on (a time, the close of other items, an anchor, an answer relayed to a person, or a fleet event, shown as `a fleet event (<the event>; backstop <day>)`); on a doing item the board lists as waiting it ends with `· the board lists it as waiting until <time> (<why>)` (stored as doing, but its wake is more than an hour away and every open step is dated for that day or later, or its wake carries a wait_basis and is still ahead; a wake kept as a hand-off's backstop, with no wait_basis, is no wait; a date alone is a wait until it), so it is listed as waiting until then. After `next:` a `named in next:` block gives each board#N the next names with its live state (closed with the time and outcome, open with its mover, waiting, or not found), so a status is never relayed from the words of next. The item model is on docs/design. item_id can also be a notice id (the six hex characters a message to a project returns): it then shows who sent the notice and when, its project, a one-line excerpt, the router's ruling with its reason, rule and item, when it was ruled, or that it is still held and when the router rules it."""
    _oauth._who()
    nid = _notice_asked(item_id)
    if nid:
        return _notice_report(nid)
    gid = _norm_id(item_id, bare=True); it = _load(gid); it["gid"] = gid
    return _fmt(it) + _nag()


def register(mcp, *, fmt, notice_asked, notice_report) -> None:
    """Adds the tool of this module to `mcp`, and takes the server's callables the bodies use."""
    global _fmt, _notice_asked, _notice_report
    _fmt = fmt
    _notice_asked = notice_asked
    _notice_report = notice_report
    mcp.tool(name="get", description=_lead(_T.description("get")))(stackshot_get)
