"""door_guard.py (web): the board's check of the front door's signed identity, as a pure ASGI wrapper around the HTTP app.

A board that has `[behind_frontdoor] identity_secret_file` set takes calls to its MCP endpoint through a front door only (docs/front-door.md). For every request to the endpoint's path the
wrapper reads the signed identity header (`frontdoor_identity.HEADER`), asks `core/behind_door.py: check` whether it verifies under the shared secret and inside the replay window, and
  * accepts: puts the verified identity on the request's ASGI scope (`behind_door.SCOPE_KEY`, which a client cannot write: the scope is the server's) and passes the request on;
  * refuses: answers HTTP 403 with the one sentence of `behind_door` (no identity, an identity that does not verify, a secret the board cannot read), plain text, and the request goes no further.

`web/auth/oauth.py: _who` reads the identity from the scope, so a tool asks the same question of the same request and a request that never passed the wrapper has no identity (a tool refuses it).

Only the MCP endpoint's path is guarded. The board's other routes (its pages, the client API, the sign-in, the health route) are as they were: the front door calls the endpoint, and its health check
is an open route. A board with no `[behind_frontdoor] identity_secret_file` is not wrapped at all (`install` returns before it touches anything), so it serves exactly as it did.

The wrapper reads no body and buffers nothing: the MCP endpoint's streams run as they did. It is installed before the request log's, so the log (the outermost) sees a refusal too.
"""
from __future__ import annotations

from typing import Any

from stackshot.core import behind_door as _door
from stackshot.core import config as _cfg
from stackshot.core import frontdoor_identity as _ident

STATUS = 403         # not 401: a front door whose backend credential is an OAuth client would ask for a new token and retry a 401


class DoorGuard:
    def __init__(self, app: Any, path: str):
        self.app = app
        self.path = "/" + path.strip("/")

    def __getattr__(self, name: str) -> Any:      # what the guard does not have itself (`state`, `router`, `routes` ...) is the app's, as the request log's wrapper does
        return getattr(self.__dict__["app"], name)

    def _guarded(self, scope: dict[str, Any]) -> bool:
        return scope.get("type") == "http" and "/" + str(scope.get("path") or "").strip("/") == self.path

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if not self._guarded(scope):
            await self.app(scope, receive, send)
            return
        value = ""
        want = _ident.HEADER.encode("ascii")
        for k, v in scope.get("headers") or ():
            if k == want:
                value = v.decode("latin-1")
                break
        res = _door.check(value)
        if not res.who:
            body = res.refusal.encode("utf-8")
            await send({"type": "http.response.start", "status": STATUS,
                        "headers": [(b"content-type", b"text/plain; charset=utf-8"), (b"content-length", str(len(body)).encode("ascii")), (b"cache-control", b"no-store")]})
            await send({"type": "http.response.body", "body": body})
            return
        scope[_door.SCOPE_KEY] = res.who
        await self.app(scope, receive, send)


def install(mcp: Any) -> None:
    """Make `mcp.http_app(...)` return the app inside the guard, when this board checks a front door's identity; otherwise nothing is touched."""
    if not _door.settings().identity:
        return
    plain = mcp.http_app

    def http_app(*a: Any, **kw: Any) -> Any:
        path = kw.get("path") or (a[0] if a and isinstance(a[0], str) else None) or _cfg.get("server", "path") or "/mcp"
        return DoorGuard(plain(*a, **kw), str(path))
    mcp.http_app = http_app
