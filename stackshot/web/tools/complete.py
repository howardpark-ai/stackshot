"""complete.py: the `complete` and `confirm` tools: closing an item with its outcome, and confirming one is still current."""
from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from stackshot.core import config as _cfg
from stackshot.service import update as _update_svc
from stackshot.web.auth import oauth as _oauth
from stackshot.web.tools.notes import _SENDER_MIRROR, _sender_required
from stackshot.web.tools.text import _OUTCOME_PARAM, _OUTCOME_TEXT_PARAM, _REASON_PARAM, _SAID_PARAM, _lead, load_text

_FD = _cfg.freshness_days()
_T = load_text("complete", {"SENDER_MIRROR_STRIPPED": _SENDER_MIRROR.strip(), "CALL_DAYS": f"{_FD['call_days']:g}", "AGENT_DAYS": f"{_FD['agent_days']:g}",
                            "EXTERNAL_DAYS": f"{_FD['external_days']:g}"})

_sender_not_owner = None      # set by register: the server's own, looked up at each call


_COMPLETE_DESC = (
    _T.description("complete")
)


def stackshot_complete(item_id: str, outcome: _OUTCOME_PARAM = "", reason: _REASON_PARAM = "",
                       description: Annotated[str, Field(description=_T.param("description"))] = "",
                       superseded_by: str = "", sender: str = "",
                       said: Annotated[list[dict[str, Any]] | str | None, Field(description=_SAID_PARAM)] = None,
                       outcome_text: _OUTCOME_TEXT_PARAM = "") -> str:
    """Close an item with how it ended; its description is _COMPLETE_DESC. The fields default to empty so that a pane with
    an older cached schema gets the refusal that says what is missing and how to close through the portal, not a schema error."""
    _oauth._who()
    _sender_required(sender)
    _sender_not_owner(sender)
    return _update_svc.complete_item(item_id, outcome=outcome, reason=reason, description=description, superseded_by=superseded_by, sender=sender, said=said, outcome_text=outcome_text)


def stackshot_confirm(item_id: str, sender: str = "") -> str:
    """Mark an item still true: sets its `confirmed` clock only. item_id: board#N (a bare number N is read as board#N)."""
    _oauth._who()
    _sender_required(sender)
    _sender_not_owner(sender)
    return _update_svc.confirm_item(item_id, sender)


def register(mcp, *, sender_not_owner) -> None:
    """Adds the tools of this module to `mcp`, and takes the server's callables the bodies use."""
    global _sender_not_owner
    _sender_not_owner = sender_not_owner
    mcp.tool(name="complete", description=_lead(_COMPLETE_DESC))(stackshot_complete)
    mcp.tool(name="confirm", description=_lead(_T.description("confirm")))(stackshot_confirm)
