"""middleware.py: the tool middleware of the server, in the order app.build adds them: the tool-set fingerprint (`_Fingerprint`), the board links (`_LinkIds`, with `_link_ids` and `_unlink_ids`: every item id in a tool's text reply is a link to its page, a write's text arguments are unlinked first), the refusal log (`_RefusalLog`: one stderr line for every ToolError a tool call ends in, the call count
and the one reply line for a correction the server made itself), the gate that answers lists, reads, calls and the instructions text to members only (`_MembersOnly`), the read-only refusal of a warm standby copy (`_ReadOnly`, with `_RO_WRITE_TOOLS` and `_ro_tool_changes`), and the refusal of the
retired item-state inputs (`_RetiredInputs`).

web/app.py makes the FastMCP instance and adds these to it; the order of the `mcp.add_middleware(...)` calls is there."""
from __future__ import annotations

import json
import re
import sys
import time
from typing import Any, Iterator

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from fastmcp.server.middleware import Middleware as _MW
from mcp.shared.exceptions import MCPError

from stackshot.core import call_log as _calls
from stackshot.core import frontdoor_identity as _ident
from stackshot.core import instance as _inst
from stackshot.core import readonly as _ro
from stackshot.core import retired_inputs as _retired
from stackshot.core.instance import OWNER
from stackshot.github import ghsync as _gh
from stackshot.model.ids import _item_url, _norm_id
from stackshot.service.store import _path
from stackshot.web.auth import oauth as _oauth

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


ZERO_ID = "board" + "#" + "0"          # what the log keeps in place of an item id a refusal quotes
_ID_LIKE = re.compile(r"(?:board(?:-tmp-[\w-]+)?)?#?\d+|[a-z]\d+", re.I)


def _strings(v: Any) -> Iterator[str]:
    if isinstance(v, str):
        yield v
    elif isinstance(v, (list, tuple)):
        for x in v:
            yield from _strings(x)


_QUOTED = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
_MAILBOX = re.compile(r"[\w.+-]+@[\w.-]+")


def _spellings(x: str) -> set[str]:
    """The ways a refusal can quote a string argument: as it is, and as repr() or JSON write it (newlines, tabs, backslashes and a quote of either kind escaped)."""
    return {x, repr(x)[1:-1], json.dumps(x, ensure_ascii=False)[1:-1]}


def _scrub(text: str, a: dict[str, Any], writes: bool, tool: str = "") -> str:
    """A refusal's text for the call log without the arguments it echoes: a refused read or write can quote the item it was given, a project or an anchor's text, and the log keeps the kind of refusal, never what the caller sent. Every string argument of a tool that is
    no counted write (`writes` false) is replaced where it stands in the text; for a counted write only an item_id that is no id at all is (a valid id stays: the weekly kinds fold it anyway). A real id is replaced by ZERO_ID (an item id of 0), anything else by `<arg>`."""
    out = text
    pairs = []
    for k, v in a.items():
        if k == "sender" or (writes and k != "item_id"):
            continue
        for x in _strings(v):
            x = x.strip()
            if len(x) >= 2 and not (k == "item_id" and writes and _ID_LIKE.fullmatch(x)):
                pairs += [(s, ZERO_ID if k == "item_id" and _ID_LIKE.fullmatch(x) else "<arg>") for s in _spellings(x) if len(s) >= 2]
    for x, to in sorted(set(pairs), key=lambda p: -len(p[0])):
        out = out.replace(x, to)
    if tool == "anchors":          # an anchors refusal quotes a part of an address (the mailbox of gmail:q@<mailbox>:<query>, a name): any quoted or mailbox-looking part goes, the kind stays
        out = _MAILBOX.sub("<arg>", _QUOTED.sub("'<arg>'", out))
    return out


def _read_target(a: dict[str, Any]) -> str:
    """What a call is about, for the call log: its item_id when that is an id ("" otherwise: a project, a session name or an item_id that is no id is the caller's text and is not kept). A retry is a repeat on this."""
    v = str(a.get("item_id") or "").strip()
    return v if _ID_LIKE.fullmatch(v) else ""


def _message_fields(args: dict[str, Any], err: BaseException) -> dict[str, str]:
    """call_log.record's `to`, `kind` and `text` for a refused message call (service/messaging.py `refusal_fields`); {} when they cannot be read, so the refusal is still counted."""
    try:
        from stackshot.service import messaging as _messaging  # noqa: PLC0415 — only a refused message needs it
        return _messaging.refusal_fields(args.get("to"), args.get("text"), err)
    except Exception:  # noqa: BLE001
        return {}


def _written_item(tool: str, args: dict[str, Any], result: Any) -> str:
    """The store id of the item a counted write was about: its item_id argument, or for a create the id the reply names ("created board#N …"); "" when there is none."""
    try:
        raw = str(args.get("item_id") or "")
        if not raw and tool == "create":
            text = next((c.text for c in getattr(result, "content", None) or [] if getattr(c, "type", "") == "text" and isinstance(getattr(c, "text", None), str)), "")
            m = re.match(r"created (\S+)", text)
            raw = m.group(1) if m else ""
        return _norm_id(raw, bare=True) if raw.strip() else ""
    except Exception:  # noqa: BLE001 — an id that does not read is no item
        return ""


class _RefusalLog(_MW):
    """a write refused inside a Code Mode script shows its reason only if the script returns it, so the server keeps it too: one stderr line (the journal)
    for every ToolError a tool call ends in, innermost of the middleware so the reason is the tool's own text, before _LinkIds rewrites its ids. The same
    middleware counts the call (call_log.py: one line for every tool's call, went through or refused, a read that errors included, with the size of its arguments; the weekly refused count reads the five writes, the daily analysis all of them) and adds the one reply line
    for a correction the server made itself instead of refusing (call_log.fixed)."""
    async def on_call_tool(self, context, call_next):  # type: ignore[override]
        msg = context.message
        name = str(getattr(msg, "name", "") or "?")
        counted = name in _calls.COUNTED
        token = _calls.begin() if counted else None
        began = time.time()          # when this call began: a fix made after it is none this call could have read
        try:
            result = await call_next(context)
        except ToolError as e:
            if token is not None:
                _calls.end(token)             # a refused write stored nothing: no correction stands
            try:
                args = getattr(msg, "arguments", None)
                print(_refusal_line(name, args, e), file=sys.stderr, flush=True)
                a = args if isinstance(args, dict) else {}
                item_ = a.get("item_id")
                more = _message_fields(a, e) if name == "message" else {}          # a refused message keeps its target, the refusal's kind and its text (the one call whose arguments are logged)
                _calls.record(name, False, item=_read_target({"item_id": item_}) if counted else _read_target(a), sender=a.get("sender"), why=_scrub(str(e), a, counted, name), call=_calls._h(a.get("subject"))[:8] if name == "create" and not str(item_ or "").strip() else "", req=_calls.size_of(a), rlen=len(str(e)), **more)
            except Exception as le:  # noqa: BLE001  — a log line is never worth losing the refusal
                print(f"mcp refusal log failed: {le}", file=sys.stderr, flush=True)
            raise
        except Exception as e:          # an error that is no ToolError: a counted write is left to its own path as before; any other tool's call is logged as refused (a read that errors counts as a refusal)
            if token is not None:
                _calls.end(token)
            else:
                try:
                    a = getattr(msg, "arguments", None)
                    a = a if isinstance(a, dict) else {}
                    _calls.record(name, False, item=_read_target(a), sender=a.get("sender"), why=type(e).__name__, req=_calls.size_of(a), rlen=len(str(e)))
                except Exception as le:  # noqa: BLE001
                    print(f"mcp call log failed: {le}", file=sys.stderr, flush=True)
            raise
        except BaseException:
            if token is not None:
                _calls.end(token)
            raise
        if token is None:          # a tool that is no counted write (get, brief, sessions, anchors, rules …): one line with the size of its arguments, and nothing else
            try:
                a = getattr(msg, "arguments", None)
                a = a if isinstance(a, dict) else {}
                _calls.record(name, True, item=_read_target(a), sender=a.get("sender"), req=_calls.size_of(a))
            except Exception as le:  # noqa: BLE001  — a log line is never worth a lost reply
                print(f"mcp call log failed: {le}", file=sys.stderr, flush=True)
        if token is not None:
            fixes, detail = _calls.end_detail(token)
            try:
                a = getattr(msg, "arguments", None)
                a = a if isinstance(a, dict) else {}
                gid, who = _written_item(name, a, result), re.sub(r"\s+", " ", str(a.get("sender") or "")).strip()[:80]
                made = {k for k, _ in fixes}
                back = dict.fromkeys(_calls.bounces(gid, who, a, since=began))          # a fix this writer left open on this item, made before this call began, that this write undoes or redoes: each kind once, even where the store holds two of it
                fixes = fixes + [(_calls.BOUNCE + k, "") for k in back if _calls.BOUNCE + k not in made]      # …and not again when the call already counted it itself
                _calls.remember(gid, who, detail)
                note = _calls.reply_note(fixes)
                if note:
                    for c in getattr(result, "content", None) or []:
                        if getattr(c, "type", "") == "text" and isinstance(getattr(c, "text", None), str):
                            c.text += note
                            break
                    sc = getattr(result, "structured_content", None)
                    if isinstance(sc, dict) and isinstance(sc.get("result"), str):
                        sc["result"] += note
                _calls.record(name, True, item=gid, sender=who, fixes=fixes, to=str(a.get("to") or "") if name == "message" else "", req=_calls.size_of(a))      # a message the relay handled where it once refused keeps its target with the kind
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


# the requests that are not refused up front to someone who is no member: the first two are answered without the instructions text, ping carries nothing,
# and a tool call is refused in `_MembersOnly.on_call_tool`
_ASKED_BY_ANYONE = ("initialize", "server/discover", "ping", "tools/call")


def _refusal() -> str:
    """"" for a caller who may read the board (`oauth._who` answers: a member, or anyone with auth off), else the sentence it refuses with."""
    try:
        _oauth._who()
    except ToolError as e:
        return str(e)
    return ""


def _within_a_call() -> bool:
    """True when the request in hand names itself a tool call (the `Mcp-Method` header). The MCP library lists the tools inside such a request, to read the called tool's schema, before the call."""
    try:
        return get_http_request().headers.get("mcp-method") == "tools/call"
    except RuntimeError:      # no HTTP request in hand
        return False


class _MembersOnly(_MW):
    """Lists and reads answer members only. Whoever `oauth._who` refuses is refused every list, every read and every other request (`_ASKED_BY_ANYONE` aside), and gets no instructions text from
    `initialize` and `server/discover`. A tool call of theirs ends in the ToolError `_who` raises, before the standby copy's and the retired inputs' refusals, and inside _RefusalLog, which logs it.
    The one listing the library makes inside a tool call (`_within_a_call`) gets an empty list instead of a refusal: the call is refused next, and a refused listing there would put a traceback in
    the log for every such call."""
    async def on_request(self, context, call_next):  # type: ignore[override]
        if context.method not in _ASKED_BY_ANYONE and (why := _refusal()):
            if context.method == "tools/list" and _within_a_call():
                return []
            raise MCPError(code=_ident.NOT_MEMBER_CODE, message=why)
        return await call_next(context)

    async def on_call_tool(self, context, call_next):  # type: ignore[override]
        _oauth._who()
        return await call_next(context)

    async def on_initialize(self, context, call_next):  # type: ignore[override]
        result = await call_next(context)
        if result is None or not _refusal():
            return result
        return result.model_copy(update={"instructions": None})

    on_discover = on_initialize


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
        if not (result.get("instructions") if isinstance(result, dict) else getattr(result, "instructions", None)):
            return result      # a caller who is no member gets no instructions (_MembersOnly): nothing is added to none
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
