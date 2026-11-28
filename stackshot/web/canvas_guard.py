"""canvas_guard.py (web): the isolation headers of everything under /canvas and /mockup, as a pure ASGI wrapper around the HTTP app (docs/canvas.md).

A canvas is a page somebody else wrote, served from the board's own address. What keeps it apart is what the browser is told with the answer, so the telling is not left to a route: every HTTP answer
whose path starts with one of the two prefixes leaves with the headers below, whoever made it: a page, a redirect to the sign-in, a 401, a 404, a 405, the standby's 503 or a 500. Whatever the answer said
for itself about these headers is replaced.

There are two policies. The shell (a 200 at /canvas/<number> or /canvas/<number>/versions/<id>, the board's own page with no script, holding the frame) may frame the board's own origin and nothing else.
Everything else gets the page's policy: sandboxed with scripts only (an opaque origin, even opened as its own tab), no request of any kind, no form, framed by the board only. So a path that is new or
mistyped gets the stricter one. Only the shell may set a cookie. `/mockup`, which serves nothing here, is covered so that whatever answers it is covered from its first day.

It sits outside the frame guard (whose two headers it replaces) and in front of every route and its sign-in guard, and, like the frame guard, it is installed on a standby copy too.
"""
from __future__ import annotations

import re
from typing import Any

from stackshot.service import canvas as _canvas

PREFIXES = (_canvas.PATH.strip("/"), "mockup")      # the first part of a path
PAGE_CSP = ("sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com data:; "
            "img-src data:; media-src data:; connect-src 'none'; frame-src 'none'; worker-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'")
SHELL_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; font-src 'self'; frame-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
_SHELL = re.compile(f"{_canvas.PATH}/{_canvas.NUMBER}(/versions/{_canvas.VERSION_ID})?")
_ALWAYS = ((b"x-frame-options", b"SAMEORIGIN"), (b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer"), (b"cache-control", b"no-store"))
_OURS = frozenset((b"content-security-policy", b"content-security-policy-report-only", *(name for name, _ in _ALWAYS)))


def covers(path: str) -> bool:
    return path.lstrip("/").split("/", 1)[0] in PREFIXES


class CanvasGuard:
    def __init__(self, app: Any):
        self.app = app

    def __getattr__(self, name: str) -> Any:      # what the guard does not have itself (`state`, `router`, `routes` ...) is the app's, as the other wrappers do
        return getattr(self.__dict__["app"], name)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        path = str(scope.get("path") or "")
        if scope.get("type") != "http" or not covers(path):
            await self.app(scope, receive, send)
            return
        started = False

        async def send_with_headers(message: dict[str, Any]) -> None:
            nonlocal started
            if message.get("type") == "http.response.start":
                started = True
                shell = message.get("status") == 200 and bool(_SHELL.fullmatch(path))
                drop = _OURS if shell else _OURS | {b"set-cookie"}
                headers = [(n, v) for n, v in message.get("headers") or [] if n.lower() not in drop]
                headers += [(b"content-security-policy", (SHELL_CSP if shell else PAGE_CSP).encode("ascii")), *_ALWAYS]
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:
            if not started:      # nothing answered yet: the server's own 500 would carry none of the headers
                await send_with_headers({"type": "http.response.start", "status": 500, "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
                await send({"type": "http.response.body", "body": b"Internal Server Error"})
            raise


def install(mcp: Any) -> None:
    """Make `mcp.http_app(...)` (what `run_async` serves) return the app inside the wrapper."""
    plain = mcp.http_app

    def http_app(*a: Any, **kw: Any) -> Any:
        return CanvasGuard(plain(*a, **kw))

    mcp.http_app = http_app
