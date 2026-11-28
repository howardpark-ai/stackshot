"""canvas.py: the `canvas` tool: the pages an agent shares with the board's owner, kept by the board (service/canvas_write.py, docs/canvas.md)."""
from __future__ import annotations

import time
from typing import Annotated

from fastmcp.exceptions import ToolError
from pydantic import Field

from stackshot.service import canvas as _store
from stackshot.service import canvas_page as _page
from stackshot.service import canvas_write as _w
from stackshot.web.auth import oauth as _oauth
from stackshot.web.tools.notes import _sender_required
from stackshot.web.tools.text import _lead, load_text

_T = load_text("canvas", {"CAP_MIB": str(_store.MAX_BYTES // (1024 * 1024)), "TITLE_MAX": str(_store.TITLE_MAX), "SCREEN_CHARS": str(_page.SCREEN_CHARS)})
ACTIONS = ("add", "update", "history", "undo", "list")


def _age(seconds: float) -> str:
    s = max(0, int(seconds))
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if s >= size:
            return f"{s // size}{unit}"
    return "now"


def _saved(number: int, result: str, notices: list[str]) -> str:
    """The reply of a write: the address alone on the first line (so it is the link), what happened, then a notice line for each thing worth fixing."""
    return "\n".join([_w.address(number), f"result: {result}", *(f"notice: {n}" for n in notices)])


def stackshot_canvas(action: Annotated[str, Field(description=_T.param("action"))],
                     number: Annotated[int, Field(description=_T.param("number"))] = 0,
                     page: Annotated[str, Field(description=_T.param("page"))] = "",
                     title: Annotated[str, Field(description=_T.param("title"))] = "",
                     sender: Annotated[str, Field(description=_T.param("sender"))] = "") -> str:
    _oauth._who()
    action = str(action or "").strip().lower()
    if action not in ACTIONS:
        raise ToolError(f"Refused: action is one of {' | '.join(ACTIONS)}")
    if action in ("add", "update", "undo"):
        _sender_required(sender)
    if action == "add":
        if number:
            raise ToolError("Refused: add takes no number (the board gives it); a revision of canvas N is update")
        return _saved(*_w.add(page, title, sender))
    if action == "update":
        return _saved(*_w.update(number, page, title, sender))
    if action == "undo":
        return _saved(*_w.undo(number, sender))
    if action == "history":
        rows = _w.history(number)
        return "\n".join(f"{v['id']} {v.get('bytes', 0)} bytes {v.get('session') or '-'}" for v in rows) or f"canvas {number} has no earlier version"
    rows = _w.listing()
    now = time.time()
    return "\n".join(f"{c['number']} {c['bytes']} bytes {_age(now - c['modified'])} {_w.address(c['number'])}" + (f" {c['title']}" if c["title"] else "") for c in rows) or "no canvases"


def register(mcp) -> None:
    """Adds the tool of this module to `mcp`."""
    mcp.tool(name="canvas", description=_lead(_T.description("canvas")))(stackshot_canvas)
