"""door_verify.py (web/routes): the board's answer to the sign-in service's token check, `GET /frontdoor/verify`.

A front door's reverse proxy asks a sign-in service who a connector's bearer token is for before it lets a call reach the door (docs/front-door.md, *The sign-in service*). The service does not hold the board's Google
client or read the board's token store: it asks the board, which already knows how to check its own tokens (`mcp.auth.verify_token`, the call `web/auth/signin.py: _ui_exchange` makes for the browser's sign-in:
the token's signature, the stored mapping, then Google's own check of the grant, so a grant that was revoked is refused at once; the portal's machine token is compared in constant time).

The route exists only on a board whose `[behind_frontdoor]` table names a `verify_secret_file` (`core/behind_door.py`), and answers only a request that carries the sign-in service's signed header
(`behind_door.VERIFY_HEADER`): the route is reachable wherever the board is (the tunnel and the proxy deliver to the same address), so the header is the gate, not the address. A request with no valid header
is HTTP 403 and the token is never looked at. With the header:
  * the token is the board's: 200 `{"email": <lower case>, "via": "portal" | "google"}`; the answer holds no token and no claim beyond these two;
  * it is not (unknown, expired, revoked, signed by another key, no `Authorization: Bearer` at all): 401 `{"error": "invalid_token"}`, which the service turns into the 401 a connector needs;
  * the board has no auth object (`[auth] mode` off): 404, so a board that signs nobody in says nothing about tokens.
Every answer is `Cache-Control: no-store`. A check that raises is 503 `{"error": "unavailable"}`, never 401. What FastMCP's own Google check swallows (it reads a network failure as "no such token", as it does for a direct call to the
board today) arrives here as 401: the route adds no distinction the library does not make.
"""
from __future__ import annotations

import sys
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response

from stackshot.core import behind_door as _door

PATH = "/frontdoor/verify"
_NO_STORE = {"Cache-Control": "no-store"}


def _text(status: int, body: str) -> Response:
    return PlainTextResponse(body, status_code=status, headers=_NO_STORE)


def _json(status: int, body: dict[str, Any]) -> Response:
    return JSONResponse(body, status_code=status, headers=_NO_STORE)


def _bearer(request: Request) -> str:
    h = request.headers.get("authorization") or ""
    kind, _, value = h.partition(" ")
    return value.strip() if kind.lower() == "bearer" else ""


def make(mcp: Any):
    async def verify(request: Request) -> Response:
        res = _door.check_verify(request.headers.get(_door.VERIFY_HEADER))
        if not res.who:
            return _text(403, res.refusal)
        auth = getattr(mcp, "auth", None)
        if auth is None:
            return _text(404, "not found")
        token = _bearer(request)
        if not token:
            return _json(401, {"error": "invalid_token"})
        try:
            at = await auth.verify_token(token)
        except Exception as e:  # noqa: BLE001  — a check that could not be made is not a verdict on the token
            print(f"board token check failed: {e.__class__.__name__}", file=sys.stderr, flush=True)
            return _json(503, {"error": "unavailable"})
        claims = getattr(at, "claims", None) or {}
        email = str(claims.get("email") or "").strip().lower()
        if at is None or not email:
            return _json(401, {"error": "invalid_token"})
        return _json(200, {"email": email, "via": "portal" if claims.get("via") == "portal" else "google"})
    return verify


def register(mcp: Any) -> None:
    """Add the route when this board offers the check (`[behind_frontdoor] verify_secret_file`); otherwise the board has no such route."""
    if not _door.settings().verify:
        return
    mcp.custom_route(PATH, methods=["GET"])(make(mcp))
