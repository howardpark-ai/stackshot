"""middleware.py: the three tool middleware of the server that need nothing of server.py: the refusal log (`_RefusalLog`: one stderr line for every ToolError a tool call ends in, the call count
and the one reply line for a correction the server made itself), the read-only refusal of a warm standby copy (`_ReadOnly`, with `_RO_WRITE_TOOLS` and `_ro_tool_changes`), and the refusal of the
retired item-state inputs (`_RetiredInputs`).

server.py is being split into one module per area (CONTRIBUTING.md, Layout). What stays in server.py is the other two middleware, `_Fingerprint` and `_LinkIds` (they read `mcp`, the board's URL and the
store), and the registration of all of them: `mcp.add_middleware(...)` runs there, in the order the calls are made today, because `mcp` is the server's. server.py imports `_RefusalLog`, `_ReadOnly`,
`_RetiredInputs` and `REFUSAL_LOG_MAX` from here and keeps them on its own module as well, so the registration and the suites reach them as `server.<name>`."""
from __future__ import annotations

import re
import sys
from typing import Any

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware as _MW

from stackshot.core import call_log as _calls
from stackshot.core import readonly as _ro
from stackshot.core import retired_inputs as _retired
from stackshot.web.common import OWNER

REFUSAL_LOG_MAX = 300      # characters of a refusal's reason kept in the log line


def _refusal_line(tool: str, args: Any, err: BaseException) -> str:
    """the log line for a tool call the server refused: the tool, the item id and the sender as the call named them, and the reason (the ToolError's
    text, whitespace folded, clipped to REFUSAL_LOG_MAX). Only those four: never the call's other arguments, so a description, a draft or a said line stays out of the log."""
    a = args if isinstance(args, dict) else {}
    one = lambda v, n: re.sub(r"\s+", " ", str(v or "")).strip()[:n]
    item, sender = one(a.get("item_id"), 40), one(a.get("sender"), 80)
    reason = re.sub(r"\s+", " ", str(err)).strip()
    if len(reason) > REFUSAL_LOG_MAX:
        reason = reason[:REFUSAL_LOG_MAX - 1].rstrip() + "…"
    return f"refused: {tool} item={item or '-'} sender={sender or '-'}: {reason}"


class _RefusalLog(_MW):
    """a write refused inside a Code Mode script shows its reason only if the script returns it, so the server keeps it too: one stderr line (the journal)
    for every ToolError a tool call ends in, innermost of the middleware so the reason is the tool's own text, before _LinkIds rewrites its ids. The same
    middleware counts the call (call_log.py: one line per counted write, went through or refused, for the weekly refused count) and adds the one reply line
    for a correction the server made itself instead of refusing (call_log.fixed)."""
    async def on_call_tool(self, context, call_next):  # type: ignore[override]
        msg = context.message
        name = str(getattr(msg, "name", "") or "?")
        counted = name in _calls.COUNTED
        token = _calls.begin() if counted else None
        try:
            result = await call_next(context)
        except ToolError as e:
            if token is not None:
                _calls.end(token)             # a refused write stored nothing: no correction stands
            try:
                args = getattr(msg, "arguments", None)
                print(_refusal_line(name, args, e), file=sys.stderr, flush=True)
                a = args if isinstance(args, dict) else {}
                _calls.record(name, False, item=a.get("item_id"), sender=a.get("sender"), why=str(e))
            except Exception as le:  # noqa: BLE001  — a log line is never worth losing the refusal
                print(f"mcp refusal log failed: {le}", file=sys.stderr, flush=True)
            raise
        except BaseException:
            if token is not None:
                _calls.end(token)
            raise
        if token is not None:
            fixes = _calls.end(token)
            try:
                note = _calls.reply_note(fixes)
                if note:
                    for c in getattr(result, "content", None) or []:
                        if getattr(c, "type", "") == "text" and isinstance(getattr(c, "text", None), str):
                            c.text += note
                            break
                    sc = getattr(result, "structured_content", None)
                    if isinstance(sc, dict) and isinstance(sc.get("result"), str):
                        sc["result"] += note
                _calls.record(name, True, fixes=fixes)
            except Exception as le:  # noqa: BLE001
                print(f"mcp call log failed: {le}", file=sys.stderr, flush=True)
        return result


# on a warm standby copy (STACKSHOT_READ_ONLY=1) every tool that changes anything is refused here, before the tool runs, with the one
# sentence readonly.REFUSAL; get, brief, sessions and rules (and `anchors` that only lists) keep working. The store layer refuses a write too
# (_save, _next_id, anchors.save, projects._write): this is the explicit refusal, that is the backstop.
_RO_WRITE_TOOLS = ("create", "update", "complete", "confirm", "message", "route", "bump_versions")


def _ro_tool_changes(name: str, args: Any) -> bool:
    """True for a tool call that would change something: every write tool, and `anchors` with add or remove."""
    if name in _RO_WRITE_TOOLS:
        return True
    if name == "anchors":
        a = args if isinstance(args, dict) else {}
        return bool(a.get("add") or a.get("remove"))
    return False


class _ReadOnly(_MW):
    async def on_call_tool(self, context, call_next):  # type: ignore[override]
        if _ro.is_read_only():
            msg = context.message
            if _ro_tool_changes(str(getattr(msg, "name", "") or ""), getattr(msg, "arguments", None)):
                raise ToolError(_ro.REFUSAL)
        return await call_next(context)


class _RetiredInputs(_MW):
    """create and update no longer take the old item-state inputs (state, clear_state, chase, chase_note, party, end, proof; retired_inputs.py): a call that passes one is refused here, before the tool
    runs, with a ToolError naming what to pass instead (an unknown argument would only get a bare "unexpected argument"). One a client sends empty (a cached schema that fills every parameter
    with its default) is no call to refuse and is left out of the arguments. Nothing is written for a refused call."""
    async def on_call_tool(self, context, call_next):  # type: ignore[override]
        msg = context.message
        args = getattr(msg, "arguments", None)
        if str(getattr(msg, "name", "") or "") in _retired.TOOLS and isinstance(args, dict) and any(k in args for k in _retired.RETIRED):
            why = _retired.refusal(args, OWNER)
            if why:
                raise ToolError(why)
            msg.arguments = {k: v for k, v in args.items() if k not in _retired.RETIRED}
        return await call_next(context)
