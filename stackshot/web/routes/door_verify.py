"""door_verify.py (web/routes): the board's answer to the sign-in service's token check, `GET /frontdoor/verify`.

A front door's reverse proxy asks a sign-in service who a connector's bearer token is for before it lets a call reach the door (docs/front-door.md, *The sign-in service*). The service does not hold the board's Google
client or read the board's token store: it asks the board, which already knows how to check its own tokens (`mcp.auth.verify_token`, the call `web/auth/signin.py: _ui_exchange` makes for the browser's sign-in:
the token's signature, the stored mapping, then Google's own check of the grant, so a grant that was revoked is refused at once; the portal's machine token is compared in constant time).

The route exists only on a board whose `[behind_frontdoor]` table names a `verify_secret_file` (`core/behind_door.py`), and answers only a request that carries the sign-in service's signed header
(`behind_door.VERIFY_HEADER`): the route is reachable wherever the board is (the tunnel and the proxy deliver to the same address), so the header is the gate, not the address. A request with no valid header
is HTTP 403 and the route says nothing about its token: it does not ask the sign-in about it. The token is still read on such a request: FastMCP's bearer middleware wraps the whole app and calls the board's
`verify_token` on every request that carries a bearer, before any route runs. The bearer is read as that middleware reads it for `/mcp` (`_bearer`). With the header:
  * the token is the board's: 200 `{"email": <lower case>, "via": "portal" | "google"}`; the answer holds no token and no claim beyond these two;
  * it is not (unknown, expired, revoked, signed by another key, no `Authorization: Bearer` at all): 401 `{"error": "invalid_token"}`, which the service turns into the 401 a connector needs. The 401
    carries the `WWW-Authenticate` value the board's own `/mcp` answers the same `Authorization` header (or none) with, the `resource_metadata` address a connector discovers the sign-in by included
    (`_challenge`: taken from the library's guard on that route, nothing of it written here); no other answer carries one;
  * the board has no auth object (`[auth] mode` off): 404, so a board that signs nobody in says nothing about tokens.
Every answer is `Cache-Control: no-store`. A check that raises is 503 `{"error": "unavailable"}`, never 401. What FastMCP's own Google check swallows (it reads a network failure as "no such token", as it does for a direct call to the
board today) arrives here as 401: the route adds no distinction the library does not make.

What the service can rely on:
  * 200 says the token is valid, not that the account is a member of any board: the sign-in service checks membership;
  * the service treats any 5xx as a refusal;
  * the signed header is bound to neither the token nor the request, so whoever holds one can send it again, with any token, until it leaves the time window;
  * the verify secret and the identity secret must differ: a board whose two files hold the same value answers no check (403, `behind_door.SAME_SECRET`).
"""
from __future__ import annotations

import sys
from typing import Any

from mcp.server.auth.middleware.bearer_auth import RequireAuthMiddleware
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
    """The bearer token as the MCP library's bearer middleware reads it for `/mcp` (`mcp/server/auth/middleware/bearer_auth.py`, `BearerAuthBackend.authenticate`): a header that starts with
    `bearer ` in any case, and everything after those seven characters, trimmed of nothing. So a header `/mcp` refuses (two spaces before the token) is not accepted here. "" for any other header."""
    h = request.headers.get("authorization") or ""
    return h[len("bearer "):] if h.lower().startswith("bearer ") else ""


async def _challenge(request: Request) -> str:
    """The `WWW-Authenticate` value the board's own MCP path refuses a request with these headers by: the library's guard on that route of this app (`RequireAuthMiddleware`, FastMCP's subclass of it) is
    asked, with the request's headers and no signed-in user, so it can only refuse; it is the guard that tells a request with no `Authorization` header from one with a bearer it does not take, and that
    holds the `resource_metadata` address and the scopes. "" when the app has no such route or the guard cannot be asked (said on standard error): the 401 then goes without the header."""
    try:
        routes = getattr(request.scope.get("app"), "routes", ())
        guard = next((g for g in (getattr(r, "app", None) for r in routes) if isinstance(g, RequireAuthMiddleware)), None)
        if guard is None:
            raise LookupError("no guarded route")
        sent: list[Any] = []

        async def receive() -> dict[str, Any]:
            return {"type": "http.disconnect"}

        async def send(message: Any) -> None:
            sent.append(message)
        await guard({"type": "http", "method": request.method, "path": request.url.path, "headers": request.scope.get("headers", [])}, receive, send)
        return next(v.decode("latin-1") for k, v in sent[0]["headers"] if k.lower() == b"www-authenticate")
    except Exception as e:  # noqa: BLE001  — the header helps a connector find the sign-in; the verdict on the token stands without it
        print(f"board token check: no WWW-Authenticate for a 401: {e.__class__.__name__}", file=sys.stderr, flush=True)
        return ""


async def _refused(request: Request) -> Response:
    """401 `invalid_token`, with the challenge `/mcp` would send."""
    resp = _json(401, {"error": "invalid_token"})
    value = await _challenge(request)
    if value:
        resp.headers["www-authenticate"] = value
    return resp


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
            return await _refused(request)
        try:
            at = await auth.verify_token(token)
        except Exception as e:  # noqa: BLE001  — a check that could not be made is not a verdict on the token
            print(f"board token check failed: {e.__class__.__name__}", file=sys.stderr, flush=True)
            return _json(503, {"error": "unavailable"})
        claims = getattr(at, "claims", None) or {}
        email = str(claims.get("email") or "").strip().lower()
        if at is None or not email:
            return await _refused(request)
        return _json(200, {"email": email, "via": "portal" if claims.get("via") == "portal" else "google"})
    return verify


def register(mcp: Any) -> None:
    """Add the route when this board offers the check (`[behind_frontdoor] verify_secret_file`); otherwise the board has no such route."""
    if not _door.settings().verify:
        return
    mcp.custom_route(PATH, methods=["GET"])(make(mcp))
