"""app.py: the front door's MCP application.

    front, door = build(settings)       the FastMCP instance (the provider, the middleware, the /healthz route) and the Door it runs with
    app = asgi_app(front, door)         its ASGI application (path /mcp), with the identity gate in front of everything but /healthz
    serve(settings)                     build, then run it on settings.host:settings.port until stopped

The identity gate is plain ASGI, so a streamed answer is never held back. A request to /mcp with no identity header is refused with HTTP 401 before it
reaches the MCP layer: the reverse proxy sets the header after its sign-in check, so a request without it did not come through the proxy. A caller
who is a member of no board gets an MCP answer in words instead (`you are not a member of any board.`), which a client shows, where it shows an HTTP
error only as "Server returned an error response".
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import NotFoundError, ToolError
from fastmcp.server.middleware import Middleware
from mcp import types as mt
from mcp.shared.exceptions import MCPError
from starlette.middleware import Middleware as AsgiMiddleware
from starlette.responses import JSONResponse

from stackshot.core.frontdoor_config import Settings
from stackshot.frontdoor.backend import log
from stackshot.frontdoor.instructions import Instructions
from stackshot.frontdoor.provider import Door, DoorProvider, did_not_answer, not_offered

NAME = "stackshot-front-door"


class IdentityGate:
    """Pure ASGI: no identity header is HTTP 401; /healthz is open."""

    def __init__(self, app: Any, door: Door):
        self.app = app
        self.header = door.settings.identity_header.encode("ascii")

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope["path"] == "/healthz":
            return await self.app(scope, receive, send)
        for k, v in scope["headers"]:
            if k.lower() == self.header and v.strip():
                return await self.app(scope, receive, send)
        log.warning("401 %s %s: no identity header", scope["method"], scope["path"])
        body = b"no identity: this endpoint is reached through the sign-in proxy"
        await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"text/plain"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


class DoorMiddleware(Middleware):
    """What the front door adds around the MCP layer: its own instructions text, and a refusal in words for a tool that is not offered."""

    def __init__(self, door: Door):
        self.door = door
        self.instructions = Instructions(door)

    async def _text(self) -> str:
        try:
            return await self.instructions.compose(self.door.caller())
        except Exception as e:      # noqa: BLE001  (instructions are help: a failure to build them never fails the connection)
            log.warning("instructions: %s: %s", type(e).__name__, str(e)[:160])
            return self.door.settings.preface

    async def on_initialize(self, context: Any, call_next: Any) -> Any:
        result = await call_next(context)
        if result is None:
            return None
        return result.model_copy(update={"instructions": await self._text()})

    async def on_discover(self, context: Any, call_next: Any) -> Any:
        result = await call_next(context)
        if isinstance(result, mt.DiscoverResult):
            return result.model_copy(update={"instructions": await self._text()})
        return result

    async def on_list_tools(self, context: Any, call_next: Any) -> Any:
        try:
            return await call_next(context)
        except ToolError as e:      # a refused listing: a client of the stateless protocol is told "Internal server error" for any exception but the protocol's own, and never sees why
            raise MCPError(mt.INVALID_REQUEST, str(e)) from None

    async def on_call_tool(self, context: Any, call_next: Any) -> Any:
        try:
            return await call_next(context)
        except NotFoundError:
            pass
        name, d = context.message.name, self.door
        user = d.caller()
        if name in d.board_tools and d.boards_of(user):
            # A board tool that is not in this caller's list because the caller's boards did not answer the listing (the brain's tools alone were listed):
            # the board is named, as for a call that fails on a board that is down.
            board = d.resolve(user, (context.message.arguments or {}).get("board"))
            h = await d.backends.health(board, force=True)
            if not h["ok"]:
                raise ToolError(did_not_answer("board", board, True, ""))
        raise ToolError(not_offered(name))


def build(settings: Settings, door: Door | None = None) -> tuple[FastMCP, Door]:
    door = door or Door(settings)
    front = FastMCP(NAME)
    front.add_provider(DoorProvider(door))
    front.provider_error_strategy = "raise"      # a provider that fails while listing fails the list; the default ("warn") answers with no tools and a log line
    mw = DoorMiddleware(door)
    door.instructions = mw.instructions      # the composed-text cache, where a test or a restart-free reload can reach it
    front.add_middleware(mw)

    @front.custom_route("/healthz", methods=["GET"])
    async def healthz(request: Any) -> JSONResponse:
        backends = await asyncio.gather(*(door.backends.health(n) for n in door.backends.by_name))
        st = dict(zip(door.backends.by_name, backends))
        ok = all(r["ok"] for r in st.values())
        return JSONResponse({"status": "ok" if ok else "degraded", "backends": st}, status_code=200 if ok else 503)

    return front, door


def asgi_app(front: FastMCP, door: Door) -> Any:
    return front.http_app(path="/mcp", middleware=[AsgiMiddleware(IdentityGate, door=door)])


def serve(settings: Settings) -> None:
    front, door = build(settings)
    front.run(transport="http", host=settings.host, port=settings.port, path="/mcp", show_banner=False, middleware=[AsgiMiddleware(IdentityGate, door=door)])
