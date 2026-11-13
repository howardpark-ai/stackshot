"""complete.py: the `complete` and `confirm` tools: closing an item with its outcome, and confirming one is still current."""
from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from stackshot.core import config as _cfg
from stackshot.core.instance import OWNER
from stackshot.service import update as _update_svc
from stackshot.web.auth import oauth as _oauth
from stackshot.web.tools.notes import _SENDER_MIRROR, _sender_required
from stackshot.web.tools.text import _CLOSE_FORM, _DESC_LINE_MAX, _OUTCOME_PARAM, _OUTCOME_TEXT_PARAM, _REASON_PARAM, _SAID_PARAM, _lead

_sender_not_owner = None      # set by register: the server's own, looked up at each call


_COMPLETE_DESC = (
    "Close an item; it works on an item on hold too. Right call: complete(item_id=\"board#N\", sender=\"my-x\", outcome=\"done\", reason=\"Export shipped in PR 12\", outcome_text=\"- PR 12 merged\\n- live on the box\") "
    f"(every outcome_text line is a `- ` bullet of at most {_DESC_LINE_MAX} characters); "
    "not planned: complete(item_id=\"board#N\", sender=\"my-x\", outcome=\"dropped\", reason=\"No longer needed\", outcome_text=\"- The export moved to another team\"); "
    "replaced: complete(item_id=\"board#N\", sender=\"my-x\", outcome=\"superseded\", superseded_by=\"board#M\", reason=\"Merged into board#M\", outcome_text=\"- Scope moved to board#M\"); "
    "outcome, reason and outcome_text are all required. " + _CLOSE_FORM + "A close settles no mover and ends no hand-off line: it drops the mover, then and any wait, and a closed item shows no hand-off. Never delete items; completed ones are pruned from the "
    "live list by the publisher, the git mirror keeps the history. The reply shows the closed item and lists the project anchors that were scoped to this item "
    "and now have no open item left, for the project's builder, else its -main agent, to keep (project-wide) or drop — nothing is removed by a completion. "
    "sender = your own session (name or cse_… id) when you close an item you do not own; a session named in the item's needs always passes "
    "sender=<itself>, so that the mover is told of the close. "
    + _SENDER_MIRROR.strip()
)


def stackshot_complete(item_id: str, outcome: _OUTCOME_PARAM = "", reason: _REASON_PARAM = "",
                       description: Annotated[str, Field(description="Deprecated, pass outcome_text. Still accepted for callers that predate it: what is passed here with a close is stored as the outcome text and never replaces the item's description (a text equal to the stored description is ignored).")] = "",
                       superseded_by: str = "", sender: str = "",
                       said: Annotated[list[dict[str, Any]] | str | None, Field(description=_SAID_PARAM)] = None,
                       outcome_text: _OUTCOME_TEXT_PARAM = "") -> str:
    """Close an item with how it ended; its description is _COMPLETE_DESC. The fields default to empty so that a pane with
    an older cached schema gets the refusal that says what is missing and how to close through the portal, not a schema error."""
    _oauth._who()
    _sender_required(sender)
    _sender_not_owner(sender)
    return _update_svc.complete_item(item_id, outcome=outcome, reason=reason, description=description, superseded_by=superseded_by, sender=sender, said=said, outcome_text=outcome_text)


_FD = _cfg.freshness_days()


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
    mcp.tool(name="confirm", description=_lead(f"Mark an item still true, as it stands: confirm(item_id=\"board#N\", sender=\"my-x\") and it reads fresh again. An active item reads stale after {_FD['call_days']:g} d "
                                             f"without a state change or a confirm when it needs {OWNER}'s call, {_FD['agent_days']:g} d on agent, {_FD['external_days']:g} d "
                                             "when it waits on others; an item on hold never does. Changes nothing else: no field, no state clock, no page owed, nobody "
                                             "told. Stale means unverified, not wrong: re-read the item against its project page, then confirm, update or complete it. "
                                             "sender = your own session (name or cse_… id). item_id = board#N (a bare number N is read as board#N). " + _SENDER_MIRROR.strip()))(stackshot_confirm)
