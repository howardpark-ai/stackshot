"""brief.py: the route of GET /items/{key}/brief, one item's brief: the short view for deciding (the page itself is ui/brief.py).

The home page's panel reads this same page and takes the brief out of it. It is behind the board's sign-in exactly as the item's page is, and takes the same answer box for the viewer;
who may answer is not decided here: the form posts to the item's own answer route (routes/answers.py) with its own gates. A GET writes nothing.

`register(mcp, *, contact_label)` adds the route to the server's `mcp`; it goes before the catch-all."""
from __future__ import annotations

import re

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from stackshot.core import store as _store
from stackshot.github import ghsync as _gh
from stackshot.model.ids import _ITEM_KEY, _item_gid
from stackshot.web.auth import signin as _signin
from stackshot.web.auth.signin import _ui_guard
from stackshot.web.routes.board_pages import _answer_box
from stackshot.web.ui import under


_contact_label = None      # the server's own, set by register(): who an item's row names, so the brief's head reads as the home row does


def _draw(gid: str, box: dict | None) -> str:
    """The page. KeyError for an id the store does not hold."""
    from stackshot.web.ui import brief, render
    return brief.page(render.Board(str(_store.STORE), contact_of=_contact_label), gid, box)


async def item_brief(request: Request) -> Response:
    raw = str(request.path_params.get("key") or "")
    gid = _item_gid(raw) if re.fullmatch(_ITEM_KEY, raw) else ""
    if not gid:
        return PlainTextResponse("no such item", status_code=404)
    at = _gh.href_id(gid)      # one address per item, the item page's: an old form of an id goes to it, the query kept
    if at != raw:
        q = request.url.query
        return RedirectResponse(under(f"/items/{at}/brief") + (f"?{q}" if q else ""), status_code=301)
    g = _ui_guard(request)
    if g is not None:
        return g
    box = _answer_box(request, _signin._ui_email(request), gid)
    try:
        page = await run_in_threadpool(_draw, gid, box)
    except KeyError:
        return PlainTextResponse("no such item", status_code=404)
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


def register(mcp, *, contact_label) -> None:
    global _contact_label
    _contact_label = contact_label
    mcp.custom_route("/items/{key}/brief", methods=["GET"])(item_brief)
