"""frame_guard.py (web): which sites may show the server's answers in a frame, as a pure ASGI wrapper around the HTTP app.

Only the server's own origin may. Every HTTP response leaves with `X-Frame-Options: SAMEORIGIN` and `Content-Security-Policy: frame-ancestors 'self'`: the pages, the routes a page posts to, the files and the
refusals, and the JSON and MCP answers too, where the two headers mean nothing. One place, so a new route has them with no line of its own. No other policy is added.

A response that already says who may frame it (an `X-Frame-Options`, or a policy with `frame-ancestors`) is left as it is: a browser that reads `frame-ancestors` ignores `X-Frame-Options`, so adding
'self' to a page that says DENY (the sign-in library's consent page does) would loosen it. One page of the board states a wider policy of its own, and only when the instance lists origins for it: the answer
frame (web/routes/answer_frame.py, docs/answer-frame.md).

The wrapper reads no body and buffers nothing. Unlike the request log's it is installed on a warm standby copy too, which serves the same pages.
"""
from __future__ import annotations

from typing import Any

HEADERS = ((b"x-frame-options", b"SAMEORIGIN"), (b"content-security-policy", b"frame-ancestors 'self'"))


def _says_who_may_frame(headers: list[tuple[bytes, bytes]]) -> bool:
    return any(name.lower() == b"x-frame-options" or (name.lower() == b"content-security-policy" and b"frame-ancestors" in value.lower()) for name, value in headers)


class FrameGuard:
    def __init__(self, app: Any):
        self.app = app

    def __getattr__(self, name: str) -> Any:      # what the guard does not have itself (`state`, `router`, `routes` ...) is the app's, as the other wrappers do
        return getattr(self.__dict__["app"], name)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers") or [])
                if not _says_who_may_frame(headers):
                    message = {**message, "headers": [*headers, *HEADERS]}
            await send(message)

        await self.app(scope, receive, send_with_headers)


def install(mcp: Any) -> None:
    """Make `mcp.http_app(...)` (what `run_async` serves) return the app inside the wrapper."""
    plain = mcp.http_app

    def http_app(*a: Any, **kw: Any) -> Any:
        return FrameGuard(plain(*a, **kw))

    mcp.http_app = http_app
