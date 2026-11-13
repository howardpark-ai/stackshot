"""notes.py: the helpers more than one tool calls: the note a sender off its project's agents map gets, the owner and until parameter helpers, the sender check of the writes."""
from __future__ import annotations

import datetime as dt
import re
import sys

from fastmcp.exceptions import ToolError

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core.instance import OWNER
from stackshot.github import ghsync as _gh
from stackshot.model.ids import _norm_id
from stackshot.projects import projects as _prj
from stackshot.service.store import _load
from stackshot.web.tools.text import _MODEL_PAGE, _T

_main_agent = None      # set by register: the server's own, looked up at each call


def _off_map_note_item(sender: str, item_id: str, project: str = "") -> str:
    """_off_map_note for a write to an item: the project the write names, else the item's own."""
    try:
        proj = project or str((_load(_norm_id(item_id, bare=True)).get("metadata") or {}).get("project") or "")
    except Exception:  # noqa: BLE001  — an item that does not read had no write to note
        return ""
    return _off_map_note(sender, proj)


def _off_map_note_to(sender: str, to: str) -> str:
    """_off_map_note for a message: only a target that is a project page (`projects/<slug>` or its id) names a project; anything that raises here leaves the delivered message's reply as it was."""
    try:
        key = _prj.to_key(str(to or "").strip()).rstrip("/")
        return _off_map_note(sender, key) if re.match(_cfg.page_dirs_re() + "/", key) else ""
    except Exception as e:  # noqa: BLE001  — the note is an extra
        print(f"off-map note for {sender!r} to {to!r} not made: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return ""


def _off_map_note(sender: str, project: str) -> str:
    """The line a write's reply ends with when `sender` is a session the project's agents map has no line for (anchors.off_map, the rule the audit's finding uses): it says so and names the project's
    -main agent, so the sender can ask for a line. A note, never a refusal; "" for a session the map lists, a visitor listed on another project's map, the owner, a script or when the registry cannot be read."""
    try:
        project = _anc.project_of({"metadata": {"project": str(project or "")}})       # a bare slug is the page in the first [pages] dir
        who = _anc.off_map(sender, project)
        if not who:
            return ""
        main = _main_agent(project)
    except Exception as e:  # noqa: BLE001  — the note is an extra: a failure in it leaves the reply as it was
        print(f"off-map note for {sender!r} on {project!r} not made: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return ""
    return (f"\n(note: {str(project).strip('/')} has no agents-map line for {who}. "
            + (f"Its -main agent is {main}: ask it to list you or to take this work.)" if main else "The project names no -main agent.)"))


_OWNER_PARAM_UNTIL = "2099-03-03"


def _owner_param_until() -> dt.date:
    """[model] owner_param_until (YYYY-MM-DD, default the code's): the last day create and update still accept the old `owner` parameter. A value that is not a date reads as the default."""
    v = str(_cfg.get("model", "owner_param_until", default=_OWNER_PARAM_UNTIL) or _OWNER_PARAM_UNTIL).strip()
    try:
        return dt.date.fromisoformat(v)
    except ValueError:
        return dt.date.fromisoformat(_OWNER_PARAM_UNTIL)


def _owner_param(tool: str, owner: str) -> str:
    """The old `owner` parameter of create or update → "" when it was not passed, else the note the reply ends with while it is still accepted; a ToolError (naming `mover`)
    from the day after [model] owner_param_until."""
    if not str(owner or "").strip():
        return ""
    until = _owner_param_until()
    if dt.datetime.now(_cfg.tz()).date() > until:
        raise ToolError(f"Refused: owner is not a parameter of {tool} any more (it was accepted until {until:%Y-%m-%d}). "
                        + ("Pass sender=<your own session>: the server records it as the item's creator. " if tool == "create" else "")
                        + f"Say who moves the item with mover=<a session, {OWNER} or the project's background agent> (and then=<who takes it after {OWNER}'s answer or step>). To name the front agent the item page leads with, use contact=<a front agent of the project>. The item model: {_MODEL_PAGE}.")
    return (f"\n(note: owner is going away: it is accepted until {until:%Y-%m-%d} and refused after. "
            + ("Pass sender=<your own session> instead: the server records it as the item's creator. " if tool == "create" else "To hand the item to a session, set mover=<session>. ")
            + f"Say who moves the item with mover=, and who takes it after {OWNER}'s answer or step with then=. To name the front agent the item page leads with, use contact=<a front agent of the project>. The item model: {_MODEL_PAGE}.)")


_SENDER_MIRROR = _T.piece("SENDER_MIRROR")      # the sender rule's wording, read by the complete tool's text and a test


def _sender_required(sender: str) -> None:
    """The refusal of a tool write without a sender while the GitHub mirror is on."""
    if _gh.enabled() and not str(sender or "").strip():
        raise ToolError("Refused: pass sender=<your session name or id>, because with the GitHub mirror on every change must name "
                        "who made it (the board records the author of each change).")


def bind(*, main_agent) -> None:
    """Takes the server's callables the helpers use; app.build calls it before any tool is registered."""
    global _main_agent
    _main_agent = main_agent
