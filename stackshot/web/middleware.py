"""middleware.py: the tool middleware of the server, in the order app.build adds them: the tool-set fingerprint (`_Fingerprint`), the board links (`_LinkIds`, with `_link_ids` and `_unlink_ids`: every item id in a tool's text reply is a link to its page, a write's text arguments are unlinked first), the refusal log (`_RefusalLog`: one stderr line for every ToolError a tool call ends in, the call count
and the one reply line for a correction the server made itself), the read-only refusal of a warm standby copy (`_ReadOnly`, with `_RO_WRITE_TOOLS` and `_ro_tool_changes`), and the refusal of the
retired item-state inputs (`_RetiredInputs`).

web/app.py makes the FastMCP instance and adds these to it; the order of the `mcp.add_middleware(...)` calls is there."""
from __future__ import annotations

import json
import re
import sys
from typing import Any

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware as _MW

from stackshot.core import call_log as _calls
from stackshot.core import instance as _inst
from stackshot.core import readonly as _ro
from stackshot.core import retired_inputs as _retired
from stackshot.core.instance import OWNER
from stackshot.github import ghsync as _gh
from stackshot.model.ids import _item_url
from stackshot.service.store import _path

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
# (writes.save, _next_id, anchors.save, projects._write): this is the explicit refusal, that is the backstop.
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


class _Fingerprint(_MW):
    """The server/discover reply carries a tool-set fingerprint `[tools: <n> · <hash>]` in its instructions. Tested: a cloud/Cowork session's "Refresh mcp tools" DOES take the new instructions but still does not
    re-list tools (it showed "tools: 9" in the text next to its cached list of 8) — so the fingerprint is kept as a
    tell-tale: a session whose tool count differs from the fingerprint knows its list is stale and can say so."""
    def __init__(self, mcp) -> None:
        self._mcp = mcp      # the instance whose tools are counted (app.build makes it, then adds this)

    async def on_discover(self, context, call_next):  # type: ignore[override]
        result = await call_next(context)
        try:
            import hashlib
            names = sorted(t.name for t in await self._mcp.list_tools(run_middleware=False))
            fp = f"{len(names)} · {hashlib.sha1(','.join(names).encode()).hexdigest()[:8]}"
            if isinstance(result, dict):
                result["instructions"] = (result.get("instructions") or "") + f"\n[tools: {fp}]"
            else:
                result.instructions = (result.instructions or "") + f"\n[tools: {fp}]"
            print(f"mcp discover fingerprint {fp}", file=sys.stderr, flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"mcp discover fingerprint failed: {e}", file=sys.stderr, flush=True)
        return result


# For all sessions, ever:
# every board id in a tool's text reply is written as a markdown link to its item page, so a cloud or Cowork
# session, which runs no pane mod, shows it linked too. Skipped: an id already inside a markdown link, a URL or inline code;
# an id-shaped token glued to a word, a hyphen, a slash or a dot-number (p1-x, /items/s1); and a token that is no item
# in the store (p1 is a priority, not an item). A reply that is JSON is left as it is.
_LINK_SKIP = r"\[[^\]\n]*\]\([^)\s]*\)|https?://[^\s)>\]]+|`[^`\n]*`"


_LINK_RX = re.compile(_LINK_SKIP + r"|(?<![\w\-/#.:@])(?P<tid>board-tmp-[a-z0-9-]*[a-z0-9]#[1-9]\d*)(?![\w\-/]|\.\d)"
                      r"|(?<![\w\-/#.:@])(?P<bid>board#[1-9]\d*)(?![\w\-/]|\.\d)|(?<![\w\-/#.:@])(?P<id>[a-z][1-9]\d*)(?![\w\-/]|\.\d)")


def _link_ids(text: str) -> str:
    """Tool text → the same, each item id that names an item in the store written as it is shown, linked to its page:
    [board#N](<board_url>/items/<n>) for g7 or board#N, [board-tmp-<machine>#3](<board_url>/items/board-tmp-<machine>-3) for a
    temporary id (l3), [s5](<board_url>/items/s5) for a letter id (a session copied the store id g7 to the owner)."""
    if not text or not _inst.BOARD_URL:
        return text
    if text.lstrip()[:1] in "{[":
        try:
            json.loads(text); return text
        except Exception:
            pass
    def sub(m: re.Match) -> str:
        gid, shown = m.group("id"), m.group("bid") or m.group("tid")
        if shown:                        # → the issue-numbered item's page; board-tmp-<machine>#3 → the temporary item's
            gid = _gh.norm(shown)
        if not gid:
            return m.group(0)
        try:
            ok = _path(gid).exists()
        except Exception:
            ok = False
        label = shown or _gh.shown(gid)      # the id as it is shown (g7 → board#N), never the store id
        return f"[{label}]({_item_url(gid)})" if ok else m.group(0)
    return _LINK_RX.sub(sub, text)


def _unlink_ids(text: str) -> str:
    """The reverse, for what a write stores: [s1](<board_url>/items/s1) → s1, so a reply copied back into a subject,
    description, next or reason keeps the store plain (the board links ids itself)."""
    base = _inst.BOARD_URL.rstrip("/")
    if not base or "](" not in text:
        return text
    text = re.sub(r"\[([a-z][1-9]\d*)\]\(" + re.escape(base) + r"/items/\1\)", r"\1", text)
    text = re.sub(r"\[(board-tmp-([a-z0-9-]*[a-z0-9])#([1-9]\d*))\]\(" + re.escape(base) + r"/items/board-tmp-\2-\3\)", r"\1", text)
    return re.sub(r"\[(board#([1-9]\d*))\]\(" + re.escape(base) + r"/items/[a-z]?\2\)", r"\1", text)   # /items/<n>, and the older /items/g<n>


_STORE_WRITES = ("create", "update", "complete")


class _LinkIds(_MW):
    """board ids in every tool's text reply are links to their item pages (_link_ids); a write's text arguments are
    unlinked first (_unlink_ids)."""
    async def on_call_tool(self, context, call_next):  # type: ignore[override]
        try:
            msg = context.message
            if getattr(msg, "name", "") in _STORE_WRITES and isinstance(getattr(msg, "arguments", None), dict):
                msg.arguments = {k: _unlink_ids(v) if isinstance(v, str) else v for k, v in msg.arguments.items()}
        except Exception as e:  # noqa: BLE001
            print(f"mcp unlink ids failed: {e}", file=sys.stderr, flush=True)
        try:
            result = await call_next(context)
        except ToolError as e:           # a refusal names items too ("closing a1 needs …")
            raise ToolError(_link_ids(str(e))) from e
        try:
            for c in getattr(result, "content", None) or []:
                if getattr(c, "type", "") == "text" and isinstance(getattr(c, "text", None), str):
                    c.text = _link_ids(c.text)
            sc = getattr(result, "structured_content", None)   # a `-> str` tool also sends {"result": <text>}, and claude.ai shows that copy
            if isinstance(sc, dict) and isinstance(sc.get("result"), str):
                sc["result"] = _link_ids(sc["result"])
        except Exception as e:  # noqa: BLE001  — a reply is never lost over its links
            print(f"mcp link ids failed: {e}", file=sys.stderr, flush=True)
        return result
