"""provider.py: the one tool set of the front door, and the routing of a call to a board or the brain.

A FastMCP `Provider` lists the tools of the caller's own backends and hands out tools that carry each call to the backend it belongs to:

  * The tool list is ONE board's tool list, whichever boards the caller is on, plus the brain's tools when the caller is a member of the brain. Every board
    tool has its schema as the board gives it with one more property, `board` (optional: left out, the call goes to the caller's only board). The list
    shows only the caller's own backends, each listed and health-checked at the time; a backend that does not answer is named in a warning to the client
    and left out, and the list fails (`none of your boards answered ...`) only when none answers.
  * A call names its board (`board`) or defaults to the caller's only one. The refusals are `ToolError` text a client shows as it is (REFUSALS below).
  * A tool that is not in the caller's list is not offered: a brain credential limited to read and write lists no admin tool, so the call is refused as one
    the connection does not have (`app.py` maps the NotFoundError FastMCP raises for it).

The backend of a call travels in a `ContextVar` that `DoorTool.run` sets for the length of the call; the client factory the proxy tool is built with reads it,
so two concurrent calls of one session, or of two, never share a backend or a caller.
"""
from __future__ import annotations

import asyncio
import contextvars
import copy
import time
from typing import Any

from fastmcp.exceptions import NotFoundError, ToolError
from fastmcp.server.dependencies import get_context, get_http_headers
from fastmcp.server.providers import Provider
from fastmcp.server.providers.proxy import ProxyTool

from stackshot.core.frontdoor_config import Settings
from stackshot.frontdoor import config as _config
from stackshot.frontdoor.backend import Backends, log

LIST_CACHE_SECONDS = 60.0        # how long a caller's tool objects are reused by the calls that follow a listing
MISS_RECHECK_SECONDS = 5.0       # a call to a tool the caller's last listing did not have lists again only when that listing is older than this
LIST_CACHE_MAX = 256             # callers kept; the oldest are dropped past it
BOARD_PARAM = {"type": "string", "title": "Board",
               "description": "The board this call is for. Optional when you are on only one board; required when you are on several (the refusal names them)."}


# The text a client shows for each refusal. A refusal is a ToolError: the connection stays usable and the other boards are unaffected.
def board_required(mine: list[str]) -> str:
    return f"board required: you are on {len(mine)} boards ({', '.join(mine)}); pass board='<name>' on this call."


def not_your_board(board: str, mine: list[str]) -> str:
    return f"board '{board}' is not one of your boards. You are on: {', '.join(mine)}."


NOT_A_MEMBER = "you are not a member of any board."


def none_answered(names: list[str]) -> str:
    return f"none of your boards answered ({', '.join(names)}). Check /healthz."


def did_not_answer(kind: str, name: str, unreachable: bool, detail: str) -> str:
    how = "unreachable" if unreachable else "error: " + detail
    return (f"board '{name}' did not answer ({how}). Other boards you are on are unaffected." if kind == "board"
            else f"brain '{name}' did not answer ({how}). Your boards are unaffected.")


def not_offered(tool: str) -> str:
    return (f"tool '{tool}' is not offered to this connection (its credential is limited to what the tool list shows; "
            f"admin-scoped tools are not part of it).")


def with_board(schema: dict[str, Any]) -> dict[str, Any] | None:
    """`schema` (a board tool's input schema) with the optional `board` property added; None when the tool already has a property of that name."""
    s = copy.deepcopy(schema)
    props = s.setdefault("properties", {})
    if "board" in props:
        return None
    props["board"] = dict(BOARD_PARAM)
    return s


class Door:
    """The runtime of one front door: its settings, its backends and who the caller of the request in hand is."""

    def __init__(self, settings: Settings, backends: Backends | None = None):
        self.settings = settings
        self.backends = backends or Backends(settings)
        self.backend: contextvars.ContextVar[str] = contextvars.ContextVar("frontdoor_backend")
        self.caller_var: contextvars.ContextVar[str] = contextvars.ContextVar("frontdoor_caller")
        self.instructions: Any = None      # set by app.build: the Instructions of this door
        self.board_tools: set[str] = set()      # the names of the board tools the last successful board listing had

    def caller(self) -> str | None:
        """The caller of the request in hand: the value of the identity header the reverse proxy set; None with no request, or no such header."""
        v = get_http_headers(include={self.settings.identity_header}).get(self.settings.identity_header, "")
        return v.strip() or None

    def members(self) -> dict[str, list[str]]:
        """{member: [backend names]}, read now. A members file that cannot be read makes nobody a member (and is said in the log), never everybody."""
        try:
            return _config.read_members(self.settings.members_file)
        except _config.FileError as e:
            log.error("members: %s", e)
            return {}

    def backends_of(self, user: str | None) -> list[str]:
        """The backends `user` is a member of, in the order the config lists them; a name in the members file that no backend has is left out."""
        mine = self.members().get(user or "", []) if user else []
        return [b.name for b in self.settings.backends if b.name in mine]

    def boards_of(self, user: str | None) -> list[str]:
        return [n for n in self.backends_of(user) if self.backends.by_name[n].kind == "board"]

    def brain_of(self, user: str | None) -> str | None:
        return next((n for n in self.backends_of(user) if self.backends.by_name[n].kind == "brain"), None)

    def resolve(self, user: str | None, board: Any) -> str:
        """The board a call goes to, or a ToolError whose text the client shows as it is."""
        mine = self.boards_of(user)
        if not mine:
            raise ToolError(NOT_A_MEMBER)
        if board is None or board == "":
            if len(mine) == 1:
                return mine[0]
            raise ToolError(board_required(mine))
        if not isinstance(board, str) or board not in mine:
            raise ToolError(not_your_board(str(board)[:60], mine))
        return board

    async def warn(self, msg: str) -> None:
        """Tell the client (a log message of the request in hand) and the log."""
        log.warning("%s", msg)
        try:
            await get_context().warning(msg)
        except Exception:      # noqa: BLE001  (no request in hand, or a client that takes no log messages: the log line is what is left)
            pass


class DoorTool(ProxyTool):
    """A backend's tool as the front door lists it: a call is routed by `board` (a board's tool) or goes to the brain (a brain's tool)."""
    _door: Any = None
    _brain: str | None = None        # the brain a brain tool belongs to; None for a board's tool

    async def run(self, arguments: dict[str, Any], context: Any = None) -> Any:
        door: Door = self._door
        user = door.caller()
        args = dict(arguments)
        if self._brain is None:
            name = door.resolve(user, args.pop("board", None))
        else:
            name = self._brain
            if name not in door.backends_of(user):
                raise ToolError(NOT_A_MEMBER if not door.backends_of(user) else not_offered(self.name))
        t_b, t_c = door.backend.set(name), door.caller_var.set(user or "")
        try:
            return await super().run(args, context)
        except ToolError:
            raise
        except NotFoundError:
            raise ToolError(f"board '{name}' has no tool '{self.name}'." if self._brain is None else not_offered(self.name)) from None
        except Exception as e:      # noqa: BLE001  (a backend's own tool error is a ToolError above: this is the transport, the credential or the backend failing)
            h = await door.backends.health(name, force=True)
            log.warning("call %s backend=%s: %s: %s; health=%s", self.name, name, type(e).__name__, str(e)[:120], h)
            raise ToolError(did_not_answer(door.backends.by_name[name].kind, name, not h["ok"], str(e)[:160])) from e
        finally:
            door.backend.reset(t_b)
            door.caller_var.reset(t_c)


class DoorProvider(Provider):
    def __init__(self, door: Door):
        super().__init__()
        self.door = door
        self._cache: dict[str, tuple[float, dict[str, DoorTool]]] = {}

    def _factory(self) -> Any:
        d = self.door
        return lambda: d.backends.client(d.backend.get(), d.caller_var.get())

    async def _tools(self, warn: bool) -> dict[str, DoorTool]:
        d = self.door
        user = d.caller()
        if user is None:      # the server's own start-up listing has no caller: nothing to list
            return {}
        mine = d.backends_of(user)
        if not mine:
            raise ToolError(NOT_A_MEMBER)

        async def one(n: str) -> Any:
            async with d.backends.client(n, user) as c:
                return await c.list_tools()
        res, _ = await asyncio.gather(asyncio.gather(*(one(n) for n in mine), return_exceptions=True), asyncio.gather(*(d.backends.health(n) for n in mine)))
        ok = {n: r for n, r in zip(mine, res) if not isinstance(r, BaseException)}
        for n, r in zip(mine, res):
            if isinstance(r, BaseException):
                h = await d.backends.health(n, force=True)
                msg = (f"{d.backends.by_name[n].kind} '{n}' did not list its tools ({type(r).__name__}: {str(r)[:200]}); health={h}. "
                       f"Its tools are not missing, the {d.backends.by_name[n].kind} is down.")
                if warn:
                    await d.warn(msg)
                else:
                    log.warning("%s", msg)
        if not ok:
            raise ToolError(none_answered(mine))
        out: dict[str, DoorTool] = {}
        boards = [n for n in ok if d.backends.by_name[n].kind == "board"]
        if boards:
            sets = {n: sorted(t.name for t in ok[n]) for n in boards}
            if len({tuple(v) for v in sets.values()}) > 1:
                log.warning("the tool sets of the boards differ: %s; the list is the first answering board's", sets)
            d.board_tools = {t.name for t in ok[boards[0]]}
            for t in ok[boards[0]]:
                pt = DoorTool.from_mcp_tool(self._factory(), t)
                schema = with_board(pt.parameters)
                if schema is None:
                    log.error("board tool %s has a `board` parameter of its own, so it is not offered: the front door routes by that name", t.name)
                    continue
                pt._door, pt._brain = d, None
                out[pt.name] = pt.model_copy(update={"parameters": schema})
        brain = d.brain_of(user)
        if brain in ok:
            for t in ok[brain]:
                if t.name in out:
                    log.warning("brain tool %s has the name of a board tool, so it is not offered", t.name)
                    continue
                pt = DoorTool.from_mcp_tool(self._factory(), t)
                pt._door, pt._brain = d, brain
                out[pt.name] = pt
        self._cache[user] = (time.monotonic(), out)
        if len(self._cache) > LIST_CACHE_MAX:
            for k, _ in sorted(self._cache.items(), key=lambda kv: kv[1][0])[:len(self._cache) - LIST_CACHE_MAX]:
                del self._cache[k]
        return out

    async def _list_tools(self) -> list[DoorTool]:
        return list((await self._tools(warn=True)).values())

    async def _get_tool(self, name: str, version: Any = None) -> DoorTool | None:
        user = self.door.caller()
        have = self._cache.get(user or "")
        age = time.monotonic() - have[0] if have else LIST_CACHE_SECONDS + 1
        if have is None or age > LIST_CACHE_SECONDS or (name not in have[1] and age > MISS_RECHECK_SECONDS):
            tools = await self._tools(warn=False)
        else:
            tools = have[1]
        return tools.get(name)
