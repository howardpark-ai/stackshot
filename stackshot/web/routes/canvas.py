"""canvas.py (web/routes): the read routes of a canvas (docs/canvas.md).

    /canvas/<n>                       the shell on the current page
    /canvas/<n>/versions/<id>         the shell on one version
    …/raw after either                the page itself, the stored bytes and nothing else: what the shell's frame loads

All behind the board's sign-in. The shell sends a browser to sign in, as every page does; the page's own address answers a signed-out request with a plain 401, never a redirect, because it is read inside a
frame. GET and HEAD only: creating and editing a canvas through the board is refused (405) until the board takes over from the store the pages come from. What keeps a page apart from the board is the headers
web/canvas_guard.py puts on every answer under these addresses, not anything here."""
from __future__ import annotations

import re
from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, Response

from stackshot.service import canvas as _canvas
from stackshot.web.auth.signin import _ui_guard
from stackshot.web.ui import canvas as _ui_canvas

_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]      # every one answered here, so a refusal says why
NOT_YET = "refused: canvases are not created or edited through the board before the cutover; this address reads them"


def _refused(request: Request) -> Response | None:
    if request.method not in ("GET", "HEAD"):
        return PlainTextResponse(NOT_YET, status_code=405, headers={"Allow": "GET, HEAD"})
    return None


def _found(request: Request) -> tuple[dict[str, Any], str | None, dict[str, Any]] | None:
    """The record, the version id (None: the current page) and the page entry the path names; None when the store has no such page, or the canvas has no current page yet."""
    number, version = str(request.path_params.get("n") or ""), request.path_params.get("id")
    if not re.fullmatch(_canvas.NUMBER, number) or (version is not None and _canvas.version_time(str(version)) is None):
        return None
    rec = _canvas.read(int(number))
    if rec is None or rec["current"] is None:
        return None
    entry = rec["current"] if version is None else next((v for v in rec["versions"] if v["id"] == version), None)
    return None if entry is None else (rec, version, entry)


def _not_found() -> Response:
    return PlainTextResponse("not found", status_code=404)


async def canvas_shell(request: Request):
    """The shell of a canvas or of one of its versions."""
    no = _refused(request)
    if no is not None:
        return no
    g = _ui_guard(request)
    if g is not None:
        return g
    got = _found(request)
    if got is None:
        return _not_found()
    return HTMLResponse(_ui_canvas.shell(got[0], got[1]))


async def canvas_raw(request: Request):
    """The page itself, byte for byte. No media_type is set on the response, so no pass over the board's own pages (the panel, the language, the standby's banner) touches it."""
    no = _refused(request)
    if no is not None:
        return no
    if _ui_guard(request) is not None:
        return PlainTextResponse("signed out: open the board in the browser to sign in again", status_code=401)
    got = _found(request)
    data = None if got is None else _canvas.page(got[0]["number"], got[2])
    if data is None:
        return _not_found()
    return Response(data, headers={"Content-Type": "text/html; charset=utf-8"})


def register(mcp) -> None:
    """Add the routes to the server's `mcp`, before the catch-all of board_pages. Called once."""
    one = _canvas.PATH + "/{n}"
    version = one + "/versions/{id}"
    for path, handler in ((one, canvas_shell), (version, canvas_shell), (one + "/raw", canvas_raw), (version + "/raw", canvas_raw)):
        mcp.custom_route(path, methods=_METHODS)(handler)
