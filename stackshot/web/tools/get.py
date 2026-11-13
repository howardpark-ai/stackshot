"""get.py: the `get` tool: one item, or the items of a project, with what the server shows about them."""
from __future__ import annotations

from typing import Annotated

from pydantic import Field

from stackshot.core.instance import NAME, OWNER
from stackshot.model.ids import _norm_id
from stackshot.service.store import _load
from stackshot.web.auth import oauth as _oauth
from stackshot.web.page_debts import _nag
from stackshot.web.tools.text import _lead

_fmt = None      # set by register: the server's own, looked up at each call
_notice_asked = None      # set by register: the server's own, looked up at each call
_notice_report = None      # set by register: the server's own, looked up at each call


# What an agent does when the stall pass takes a wrong step; the same path is in stall.py's docstring and docs/stall-and-ladder.md.
_STALL_FORM = (
    f" A `stall:` line is a step the stall pass took because the item's mover had no turn running (for a background agent as mover, follow-ups after the first notice go by the item's step status, not its pane): resend (the notice again), cold (a call named who takes it, or closed it), builder (handed to the project's builder), "
    f"recovery (nobody could take it: one message goes to the project's -main agent when the project lists no background agent, to the fleet's builder otherwise, and the item stays with its mover). When a step is wrong: (1) undo it on the item with update: mover and next back; status=open with a new next for a close; "
    f"a notice or a recovery message already sent cannot be unsent and needs nothing; (2) fix the cause through a normal PR to {NAME} (hand it to the project's builder); (3) if wrong steps keep reaching {OWNER}'s call before the fix lands, ask him for a pause that ends by itself. "
    f"Never switch the pass off: {NAME} refuses `[stall] enabled = false` and a `paused_until` unless `[stall] pause_item` names a board item that carries {OWNER}'s own answer approving a pause (it says pause) from the 4 hours before it saw the setting, "
    f"and no pause lasts longer than 24 hours. "
    f"An `audit:` line is the newest hourly audit line the server wrote on the item (`Audit hh:mm: verified …`, `Audit hh:mm: idle, nothing verified`, or, when the server could not tell and the item is not idle, `Audit hh:mm: a subagent of the mover is running, not tied to an item, nothing verified` or `Audit hh:mm: the mover's subagents could not be read, nothing verified`), about every 50 minutes for the first 24 hours the item is silent and then every 6 hours; it is the server's own record of what it saw, not a step of the stall pass and not a write by the mover."
)


def stackshot_get(item_id: Annotated[str, Field(description="An item id (board#N; a bare number N is read as board#N; <letter><n> for an older item), or a notice id: the six hex characters a message to a project returns (\"notice a1b2c3\"), which shows the router's ruling of that notice.")]) -> str:
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
    mcp.tool(name="get", description=_lead("Read one item by id as shown (board#N, or the older letter-and-number form for an older item). It shows `needs:` (whose move it is: decision, external and the sessions named), "
                                         "`after:` (the items that must close first, each with its state), `observers:` and `contact:` (the front agent the person talks to about the item). `project:` is the item's top-level project; `(filed on <page>)` is the page it is filed on, the one update(project=) takes. "
                                         "It leads with `mover:` (who moves the item now) and `then:` (who takes it after "
                                         "the answer or the wait); History says who created it. A `state:` line (with the fields that state carries) shows only for an item that stores a state; an item that stores none shows no state line and no derived one, and its `model:` line says alive or waiting and who moves it. `model:` says alive or waiting, the mover and what it waits on (a time, the close of other items, an anchor, an answer relayed to a person, or a fleet event, shown as `a fleet event (<the event>; backstop <day>)`); on a doing item the board lists as waiting it ends with `· the board lists it as waiting until <time> (<why>)`: the item is stored as doing, but its wake is more than an hour away (`[waiting] dated_wait_min_hours`) and every open step is dated for that day or later, so it is listed as waiting until then; a date alone (an until, or a wake sent as its old name) is a wait until it and the item is listed as waiting, except in a write that hands the item to another session, where the date is only that hand-off's backstop and is no wait (unless the item carries hold, wait_kind, wait_basis or an after link, in this call or stored by an earlier one: then the date stays a wait); for a wake an item still carries with no until: on a stored doing item that is on hold, with a wake more than that hour away it is listed as waiting until the wake (`on hold until its wake`), and on a stored doing item that is not on hold whose wake is still ahead and carries a wait_basis: it is listed as waiting until the wake with the basis text as the reason (an item on hold keeps `on hold until its wake` as the reason, a basis or not; a wake with no wait_basis there is a backstop and the item stays active). An item shows only its real dates (wake, due, ask by) and no expected time: nothing is sent when a date passes, so whoever reads it closes the item or moves it through update. `next:` holds the open steps (the first open step first), followed by a `named in next:` block with one line for each board#N the next names (up to 8, the item itself left out) and that item's live state, so nobody relays a stale status: `board#N: closed Tue Feb 3rd 2099 14:10 (done)`, `board#N: open, mover my-engineer`, `board#N: open, waiting after board#N`, `board#N: not found`; and once a step is done or dropped a `checklist:` block lists every step in order with its position, status, who marked it and when: the positions `update` takes in done=[…] and dropped=[…]. What a write recorded with `said` shows as one line each: `Acked-by:`, `Suggested-by:`, `Reported-by:` or `Done-by:` (a pasted result that proves a step, not his words) with the session, the time, checked or unchecked, and the quote. The item model is on docs/design. "
                                         "item_id can also be a notice id, the six hex characters a message to a project returns (\"notice a1b2c3\"): get then shows the notice instead of an item, with its `sender:`, `sent:` and `project:`, a one-line `text:` excerpt, "
                                         "the router's `ruling:` (passed to whom, merged, held or dropped) with its `reason:`, its `rule:` (a rule in code, or the router's call) and who it was `ruled by:`, the `item:` it went onto and when it was `ruled:`; a repeat dropped by the rule in code also names the notice it repeats on a `repeat of:` line; "
                                         "a notice not ruled yet shows that it is still held for the router and when that is `expected:`, and a `last try:` line when the router's last judgment of it failed (a notice the router gave up on shows `ruling: none, stuck` and its `reason:`); an id no routing log holds answers \"no notice <id>\"." + _STALL_FORM))(stackshot_get)
