"""invite.py: the `invite` tool: an admin lets a Google address in to the board, or takes that back (core/invites.py). The tool is there only on a board whose
[invites] table names an admin; the server sends no mail: the reply carries the setup link and the invite mail for the admin's own agent to draft."""
from __future__ import annotations

from typing import Annotated

from fastmcp.exceptions import ToolError
from pydantic import Field

from stackshot.core import behind_door as _door
from stackshot.core import invites as _invites
from stackshot.core import members as _members
from stackshot.web import i18n as _i18n
from stackshot.web import uiprefs as _uiprefs
from stackshot.web.auth import oauth as _oauth
from stackshot.web.tools.text import _lead, load_text

_T = load_text("invite")

BAD_ADDRESS = "Refused: give one plain Google sign-in address, such as name@example.com."
NOT_ADMIN = "Refused: only an admin of this board ([invites] admins) invites or removes a person."
MACHINE = "Refused: this board takes no invite from its machine token. An admin does this from a connection signed in with their own Google account."


def _admin(s: _invites.Settings) -> str:
    """The member name of the admin this call is signed in as; ToolError for anyone else."""
    who = _oauth._who()
    if not _door.settings().identity:      # behind a front door the caller is the identity the door signed, and the token is the door's own
        from fastmcp.server.dependencies import get_access_token
        if (getattr(get_access_token(), "claims", None) or {}).get("via") == "portal":
            raise ToolError(MACHINE)
    person = _members.person_of_email(who) or next((p for p in _members.members() if p.name == who), None)
    if person is None or not person.declared or person.name not in s.admins:
        raise ToolError(NOT_ADMIN)
    return person.name


def _mail(address: str, link: str, admin_address: str) -> tuple[str, str]:
    """The invite mail (subject, body), in the language the admin reads the board in."""
    with _i18n.use(_uiprefs.lang_of(admin_address)):
        return _i18n.t("invite.mail.subject"), _i18n.t("invite.mail.body", link=link, address=address)


def _registered(address: str, s: _invites.Settings, admin: str) -> str:
    changed, joined = _invites.register(address, admin, s)
    if changed:
        first = f"Registered {address} on board {s.board}."
    else:
        first = f"{address} is already registered on board {s.board} ({'has signed in' if joined else 'has not signed in yet'}); nothing changed."
    subject, body = _mail(address, s.link, _oauth._who())
    warn = ((f"Note: an earlier Google account of {address} was kept when it was taken off its last board, and is refused on this registration. "
             f"To let that earlier account in again, remove this registration (invite(address=\"{address}\", remove=true)) and invite again, but only while the new person has not signed in. "
             f"Once they have, the earlier account stays refused: the admin must delete the entry from the members file, then invite again.",)
            if changed and _invites.has_former(address, s) else ())
    return "\n".join((
        first,
        *warn,
        f"setup link: {s.link}",
        f"Now create this mail as a draft to {address} with your own mail connector, and do not send it: it goes only when the admin sends it. "
        f"With no mail connector, show the admin the text below to copy. The board sent nothing.",
        f"subject: {subject}",
        "body:",
        body,
        "",
        f'To take it back: invite(address="{address}", remove=true).',
    ))


def _removed(address: str, s: _invites.Settings) -> str:
    left, listed = _invites.remove(address, s)
    out = [f"Removed the registration of {address} from board {s.board}."]
    if listed:
        out.append("The address is still let in by another entry of the members file, which was not registered this way: change that entry in the file.")
    else:
        out.append("From its next request on, that address gets no list, read or call of this board through a connector, with sign-in tokens already issued too.")
    out.append("Machine tokens and enrolled keys are not part of a registration: revoke separately any this person holds.")
    if left:
        out.append(f"Still registered on: {', '.join(left)} (an admin of that board removes it there).")
    return "\n".join(out)


def stackshot_invite(address: Annotated[str, Field(description=_T.param("address"))],
                     remove: Annotated[bool, Field(description=_T.param("remove"))] = False) -> str:
    s, problems = _invites.parse()
    if not s.on:
        raise ToolError("Refused: inviting is not set up on this board. " + " ".join(problems))
    admin = _admin(s)
    plain = _invites.address_of(address)
    if not plain:
        raise ToolError(BAD_ADDRESS)
    try:
        return _removed(plain, s) if remove else _registered(plain, s, admin)
    except _invites.InviteError as e:
        raise ToolError(f"Refused: {e}") from None


def first_use() -> str:
    """What the connector's instructions add on a board that can invite: where a newcomer's agent reads how to start them off."""
    return _T.piece("FIRST_USE") if _invites.wanted() else ""


def register(mcp) -> None:
    """Adds the tool of this module to `mcp`, on a board whose [invites] names an admin."""
    if _invites.wanted():
        mcp.tool(name="invite", description=_lead(_T.description("invite")))(stackshot_invite)
