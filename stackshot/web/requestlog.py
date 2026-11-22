"""requestlog.py (web): the request log's ASGI middleware, and the one tool-middleware hook that names a tool call's route.

`RequestLogMiddleware` is a pure ASGI wrapper around the whole HTTP app, outside every other layer (FastMCP's request context, the sign-in, the router, the tool middleware), so its `ms` is a request's whole time, from the
first byte in to the last byte out. It passes the request and every response message through as they come: it reads no body, buffers nothing and changes nothing, so the MCP endpoint's streams run as they did.
It keeps a status, a byte count and a clock, and writes one line when the request ends (core/requestlog.py has the file and its fields).

What a line never holds: the query string (the route is the path, with each path parameter's value replaced by its name), a header, a cookie, a token, a body, an address, a user agent, the text of an exception.
No free text of a visitor's reaches the file: a path that matched no route is `(unmatched)`, a path parameter is its name, a file the board does not have is `/{name}`, a client verb is kept only when the
client API's handler took it (`/client/<verb>`; any other is `/client/{other}`), the method is one of the standard seven or `OTHER`, and an exception is written as its type and the place it was raised (`err`), never its message.
The one label a caller supplies is the `sender` of an MCP tool call: it is the line's `caller` only for a tool the server has, after the call was accepted, and only in the strict shape a session name has; any other is `anon`.

The MCP endpoint is one path for every call, so its route comes from the tool layer, which has parsed the call anyway: `RequestRoute`, the outermost tool middleware, puts `mcp:<json-rpc method>` and, for a tool call,
`tool:<name>` (the name of a tool the server has; `tool:{other}` for any other) and the call's `sender` on a small dict that lives on the request's ASGI scope (`note`); the wrapper reads it when the request ends. The
client API's routes put the machine's name, and the verb they handled, there the same way (`note` in routes/client_api.py). A request nobody noted is `anon`.

`install(mcp)` makes `mcp.http_app` return the wrapped app. A warm standby copy (STACKSHOT_READ_ONLY) writes nothing under its state directory, so it keeps no log."""
from __future__ import annotations

import os
import re
import subprocess
import time
from typing import Any

from fastmcp.server.middleware import Middleware as _MW

from stackshot import paths as _paths
from stackshot.core import config as _cfg, readonly as _ro
from stackshot.core import requestlog as _log

KEY = "stackshot.requestlog"          # the scope key of the dict the tool layer and the routes note into
UNMATCHED = "(unmatched)"
METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})     # the methods a line names; the parser takes any token as a method, so any other is "OTHER"
_SENDER = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")         # the shape of a session name as a caller label; the tools check no shape themselves
OTHER = "{other}"                     # what a client verb or a tool name the server does not have is called
_RENAMED = {"what": "other"}          # the path parameter /client/{what} when no handler took its value: named by what it means, not by the value

_LOG: Any = None                      # the process's RequestLog, made on first use


def log() -> Any:
    """The process's request log under `<state>/requests`."""
    global _LOG
    if _LOG is None:
        _LOG = _log.RequestLog(_cfg.state("requests"))
    return _LOG


def note(scope_or_request: Any, **fields: Any) -> None:
    """Put `route` and/or `caller` on the request's line. Never raises; a request with no log holder (a test client without the wrapper) takes nothing."""
    try:
        scope = getattr(scope_or_request, "scope", scope_or_request)
        holder = scope.get(KEY)
        if holder is not None:
            holder.update({k: v for k, v in fields.items() if v})
    except Exception:  # noqa: BLE001
        pass


def _label(v: Any, n: int = 60) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def template(path: str, params: dict[str, Any], status: int, matched: bool) -> str:
    """The route of a request that nobody named: the path with each path parameter's value replaced by `{name}` (the client verb's by `{other}`), so one route groups and no value a visitor chose is kept;
    a catch-all is one `{name}` whatever its first folder; a path no route took is UNMATCHED. `status` is not used: the same path is the same route whatever the answer."""
    if not matched:
        return UNMATCHED
    out = path
    for k, v in sorted(params.items(), key=lambda kv: -len(str(kv[1]))):
        s = str(v)
        if not s:
            continue
        name = "{" + _RENAMED.get(k, k) + "}"
        if "/" in s or out.endswith("/" + s):                   # a `{name:path}` tail: the rest of the path
            i = out.rfind(s)
            out = out[:i] + name
            continue
        parts = out.split("/")
        for j, seg in enumerate(parts):
            if seg == s:
                parts[j] = name
                break
        out = "/".join(parts)
    return out or "/"


def _method(m: Any) -> str:
    """The request's method when it is one of METHODS, else "OTHER": a raw request line can carry any token, and a line must hold nothing a visitor chose."""
    return m if isinstance(m, str) and m in METHODS else "OTHER"


def _err(e: BaseException) -> str:
    """Where an exception came from, and nothing it says: its type name and the innermost frame's `module:function:line`. The message and the arguments are never read (they can hold a URL with a
    password, a header, a body); the server's own traceback, in its journal, has them."""
    tb = e.__traceback__
    while tb is not None and tb.tb_next is not None:
        tb = tb.tb_next
    where = ""
    if tb is not None:
        where = f" at {tb.tb_frame.f_globals.get('__name__', '?')}:{tb.tb_frame.f_code.co_name}:{tb.tb_lineno}"
    return f"{e.__class__.__name__}{where}"


class RequestLogMiddleware:
    """The pure ASGI wrapper. `app` is the whole HTTP application; the attributes the server reads off it (`state`, `router`, ...) come from it."""

    def __init__(self, app: Any, requests: Any = None, clock: Any = time.perf_counter) -> None:
        self.app = app
        self.requests = requests
        self.clock = clock

    def __getattr__(self, name: str) -> Any:      # only what the wrapper does not have itself: app.state.path and the like
        return getattr(self.__dict__["app"], name)

    def _sink(self) -> Any:
        return self.requests if self.requests is not None else log()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        kind = scope.get("type")
        if kind == "lifespan":
            await self._lifespan(scope, receive, send)
            return
        if kind != "http":
            await self.app(scope, receive, send)
            return
        t0 = self.clock()
        holder: dict[str, Any] = {}
        scope[KEY] = holder
        seen: dict[str, Any] = {"status": 0, "bytes": 0, "end": None, "length": None}

        async def send_logged(message: Any) -> None:
            t = message.get("type")
            if t == "http.response.start":
                seen["status"] = message.get("status", 0)
                for k, v in message.get("headers") or ():
                    if k.lower() == b"content-length":
                        try:
                            seen["length"] = int(v)
                        except ValueError:
                            pass
            elif t == "http.response.body":
                seen["bytes"] += len(message.get("body") or b"")
                if not message.get("more_body"):
                    seen["end"] = self.clock()
            elif t == "http.response.pathsend" and seen["end"] is None:
                seen["end"] = self.clock()
            await send(message)

        err = ""
        try:
            await self.app(scope, receive, send_logged)
        except BaseException as e:
            if isinstance(e, Exception):
                err = _err(e)
            raise
        finally:
            try:
                self._finish(scope, holder, seen, t0, err)
            except Exception:  # noqa: BLE001  — the line is lost, the request is not
                pass

    def _finish(self, scope: Any, holder: dict[str, Any], seen: dict[str, Any], t0: float, err: str) -> None:
        end = seen["end"] if seen["end"] is not None else self.clock()
        status = seen["status"] or (500 if err else 0)
        if not err and status >= 500:
            err = f"status {status}"                                   # an answer of the app's own: no exception, so no type or place
        route = holder.get("route") or template(str(scope.get("path") or ""), scope.get("path_params") or {}, status, scope.get("endpoint") is not None)
        size = seen["bytes"] or seen["length"] or 0
        rec: dict[str, Any] = {"method": _method(scope.get("method")), "route": route, "status": status, "ms": round((end - t0) * 1000.0, 1),
                               "bytes": size, "caller": _label(holder.get("caller")) or "anon"}
        if err:
            rec["err"] = err
        self._sink().write(rec)

    async def _lifespan(self, scope: Any, receive: Any, send: Any) -> None:
        async def send_logged(message: Any) -> None:
            t = message.get("type")
            try:
                if t == "lifespan.startup.complete":
                    self._sink().write({"kind": "start", "pid": os.getpid(), **_start_facts()})
                elif t == "lifespan.shutdown.complete":
                    self._sink().write({"kind": "stop", "pid": os.getpid()})
            except Exception:  # noqa: BLE001
                pass
            await send(message)
        await self.app(scope, receive, send_logged)


def _start_facts() -> dict[str, Any]:
    """What a start line says besides the pid: the checkout's short head and where the minute runner runs ("inline", or "unit")."""
    out: dict[str, Any] = {}
    try:
        head = subprocess.run(["git", "-C", str(_paths.ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=3).stdout.strip()
        if head:
            out["head"] = head
    except Exception:  # noqa: BLE001  — a start with no head is still a start
        pass
    try:
        out["mode"] = str(_cfg.get("runner", "process") or "inline").strip().lower()
    except Exception:  # noqa: BLE001
        pass
    return out


class RequestRoute(_MW):
    """The outermost tool middleware: names the request the call arrived in. A message gets `mcp:<json-rpc method>`; a tool call `tool:<name>` and its `sender` as the caller. It reads what the
    tool layer has parsed and changes nothing."""

    async def on_message(self, context, call_next):  # type: ignore[override]
        self._note(context, route="mcp:" + _label(getattr(context, "method", "") or "?", 40))
        return await call_next(context)

    async def on_call_tool(self, context, call_next):  # type: ignore[override]
        msg = context.message
        name = str(getattr(msg, "name", "") or "")
        args = getattr(msg, "arguments", None)
        sender = args.get("sender") if isinstance(args, dict) else ""
        known = False
        try:                                                             # a name the caller made up is not a route
            known = (await context.fastmcp_context.fastmcp.get_tool(name)) is not None
        except Exception:  # noqa: BLE001
            pass
        self._note(context, route="tool:" + (name if known else OTHER))
        out = await call_next(context)                                   # a call the tool layer refused (a made-up argument, a bad value) raises here and names no caller
        if known and isinstance(sender, str) and _SENDER.match(sender):
            self._note(context, caller=sender)
        return out

    @staticmethod
    def _note(context: Any, **fields: Any) -> None:
        try:
            from fastmcp.server.dependencies import get_http_request
            note(get_http_request(), **fields)
        except Exception:  # noqa: BLE001  — no HTTP request (an in-process call): nothing to name
            pass


def install(mcp: Any) -> None:
    """Make `mcp.http_app(...)` (what `run_async` serves) return the app inside the wrapper. Not on a warm standby copy."""
    if _ro.is_read_only():
        return
    plain = mcp.http_app

    def http_app(*a: Any, **kw: Any) -> Any:
        return RequestLogMiddleware(plain(*a, **kw))
    mcp.http_app = http_app

