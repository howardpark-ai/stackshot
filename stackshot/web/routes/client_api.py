"""client_api.py: the client API, /client/...: what a machine's puller and a session's hooks call (write, for-you seen, item watch and the read calls of /client/{what}).

`register(mcp, *, client_get, client_post, recycle_wanted_tokens)` adds the routes to the server's `mcp` in the order they were declared in server.py. The three callables are the server's own
(`_client_get` and `_client_post` serve the read and write calls, `_recycle_wanted_tokens` the tokens a poll hands out) and are looked up when a call is made, never when the routes are added."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from fastmcp.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from stackshot.core import config as _cfg
from stackshot.fleet import clients as _clients, inbox as _inbox
from stackshot.fleet.clients import POLL_MAX as _POLL_MAX
from stackshot.github import ghsync as _gh
from stackshot.model.ids import _norm_id
from stackshot.projects import brains as _brains
from stackshot.service.store import _load
from stackshot.service import foryou as _fy
from stackshot.service.projects import _form_call
from stackshot.web.publish import _publish


_client_get, _client_post, _recycle_wanted_tokens = None, None, None      # the server's own, set by register()


_CLIENTS = _cfg.secrets("clients.json")     # {machine: {"sha256": <hex of its token>, "created": <iso>}}, written by client.py mint


def _client_machine(authorization: str) -> str:
    """The machine a client token belongs to, "" when it belongs to none. The server keeps the token's SHA-256, never the token."""
    import hashlib
    import hmac
    tok = authorization[7:].strip() if authorization[:7].lower() == "bearer " else ""
    if len(tok) < 32:
        return ""
    h = hashlib.sha256(tok.encode()).hexdigest()
    try:
        d = json.loads(Path(_CLIENTS).read_text(encoding="utf-8"))
    except Exception:
        return ""
    hit = ""
    for name, v in d.items():       # no early exit: the same work whichever entry matches
        if isinstance(v, dict) and hmac.compare_digest(str(v.get("sha256") or ""), h):
            hit = str(name)
    return hit


def _client_config() -> dict[str, Any]:
    """The instance's settings a client box's hooks need, and nothing secret: `stackshot client install --url` writes
    them into that box's config, so its nag speaks in the instance's timezone and page flavor. Values as the hooks read them."""
    def plain(v: Any) -> Any:           # what TOML may hold that JSON cannot (a bare date) goes as its text
        return v if isinstance(v, (str, int, float, bool)) else [plain(x) for x in v] if isinstance(v, list) else str(v)
    out: dict[str, Any] = {
        "instance": {k: str(_cfg.get("instance", k) or "") for k in ("name", "title", "owner", "timezone", "board_url")},
        "pages": {"flavor": _cfg.page_flavor(), "dirs": _cfg.page_dirs()},
        "paths": {"brain": str(_cfg.get("paths", "brain") or "")},
        "subject": {"prefixes": [str(p) for p in (_cfg.get("subject", "prefixes") or [])]},
        "page_gate": {str(k): plain(v) for k, v in (_cfg.get("page_gate") or {}).items()},
        "board_check": {"mode": _cfg.board_check_mode()},
        "gbrain": {"mirror_url": str(_cfg.get("gbrain", "mirror_url") or "")},
        "server": {"path": str(_cfg.get("server", "path") or "/mcp")},
    }
    if _brains.configured():    # each second brain's page rules and mirror, so a client box links its pages to the right mirror (no gbrain home: a client writes nothing)
        out["brains"] = _brains.client_entries()
    return out


async def client_write(request: Request):
    """The client API's writes: what a machine's hooks and its puller send, each proved by the machine's token.
    `poll` is the puller's long poll: it reports the sessions live on the machine (the machine's sign of life), and is held
    open until a line waits for one of them or `wait` seconds pass."""
    import asyncio
    from starlette.concurrency import run_in_threadpool
    machine = _client_machine(request.headers.get("authorization", ""))
    if not machine:
        return PlainTextResponse("unauthorized: a machine token is required (Authorization: Bearer …)", status_code=401)
    what = str(request.path_params.get("what", ""))
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError
    except Exception:
        return JSONResponse({"error": "the body is a JSON object"}, status_code=400)
    nocache = {"Cache-Control": "no-store"}
    if what == "poll":
        sessions = [x for x in (body.get("sessions") or []) if isinstance(x, dict)]
        try:
            wait = min(_POLL_MAX, max(0.0, float(body.get("wait") or 0)))
        except Exception:
            wait = 0.0
        await run_in_threadpool(_clients.checkin, machine, sessions, body.get("facts") if isinstance(body.get("facts"), dict) else {}, bool(body.get("partial")))
        current = await run_in_threadpool(_clients.current, machine)        # what is current, so a box behind it updates itself when idle (puller 9)
        live = {str(x.get("uuid") or x.get("sessionId") or "").lower(): str(x.get("name") or "") for x in sessions}
        mine = await run_in_threadpool(_clients.sessions_on, machine)        # only what the server holds for THIS machine is served
        # the name a line is matched by is the one the server kept for the session (checkin has just applied the report), never the CLI's placeholder
        # a relaunched pane reports ("pane-x": its lines then matched nobody); the newest registration settles namesakes
        live = {u: str(mine[u].get("name") or n) for u, n in live.items() if u in mine}
        rank = {u: _clients._ts(mine[u].get("registered")) for u in live}
        deadline = time.time() + wait
        try:
            while True:
                deliveries = await run_in_threadpool(lambda: _inbox.take(live, rank=rank)) if live else []
                if deliveries or time.time() >= deadline:
                    break
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:      # the server is stopping while it holds this poll: answer empty, no traceback, no 500;
            deliveries = []                 # a line taken in that moment is leased, and returns to the inbox when its lease runs out
        return JSONResponse({"deliveries": deliveries, "machine": machine, "current": current}, headers=nocache)
    status, out = await run_in_threadpool(_client_post, machine, what, body)      # delivery can take seconds: off the event loop
    return JSONResponse(out, status_code=status, headers=nocache)


# The For you list's two writes for the fleet tool's web server, which holds the machine token and has no board cookie or page token. Sub-paths of
# /client, so their own routes (the generic one takes a single segment). Only the New session form's caller may (_form_call: `sender` in
# [project_agent] form_senders AND the token's machine in form_machines; defaults: no sender label, no machine): a session that holds the machine
# token must not be able to mute his items or clear his list. Any other caller: 403 with the reason.
_FORYOU_NOT_FORM = ("refused: only the web form may change the For you list: `sender` must be a label in [project_agent] form_senders "
                    "and the token must be a machine in form_machines")


def _foryou_form_gate(machine: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]] | str:
    """The checks both routes share -> the sender label to log, or (status, JSON) to answer: 400 for a sender that is no label, 403 unless _form_call."""
    sender = body.get("sender")
    if not isinstance(sender, str) or not sender.strip() or len(sender.strip()) > 80 or any(ord(c) < 32 or ord(c) == 127 for c in sender.strip()):
        return 400, {"error": "sender = the caller's own label: one line of at most 80 characters"}
    sender = sender.strip()
    if not _form_call(machine, sender):
        return 403, {"error": _FORYOU_NOT_FORM}
    return sender


def _client_foryou_seen(machine: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """`POST /client/for-you/seen` body {id: <row id int> | "all", sender} -> 200 {ok, seen: [ids marked], rows: the unseen rows as GET /client/for-you
    serves them}; 400 a bad body, 403 not the web form, 404 a row that is not on the list."""
    gate = _foryou_form_gate(machine, body)
    if not isinstance(gate, str):
        return gate
    rid = body.get("id")
    if not ((isinstance(rid, int) and not isinstance(rid, bool) and rid >= 1) or rid == "all"):
        return 400, {"error": 'id = a row\'s number (a whole number from 1), or "all"'}
    gone = _fy.mark_seen(rid)
    if gone is None:
        return 404, {"error": f"no row {rid} on the For you list (never made, or already seen)"}
    if gone:
        print(f"for-you: seen {'all rows' if rid == 'all' else 'row'} {gone} by {gate} (machine {machine})", file=sys.stderr, flush=True)
        _publish()
    return 200, {"ok": True, "seen": gone, "rows": _fy.payload(_gh.shown)["rows"]}


def _client_item_watch(machine: str, key: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """`POST /client/items/{key}/watch` body {state: watch | mute | default, sender} -> 200 {ok, item: board#N, state, flags: the whole map as
    GET /client/for-you serves it}; 400 a bad state, 403 not the web form, 404 an unknown item."""
    gate = _foryou_form_gate(machine, body)
    if not isinstance(gate, str):
        return gate
    state = body.get("state")
    if state not in ("watch", "mute", "default"):
        return 400, {"error": "state = watch | mute | default"}
    try:
        gid = _norm_id("board#" + key if key.isdigit() else key)
        _load(gid)
    except ToolError:
        return 404, {"error": f"no item {key!r}: an id as shown, board#<n>, or its store id"}
    _fy.set_flag(gid, state)
    print(f"for-you: {_gh.shown(gid)} set to {state} by {gate} (machine {machine})", file=sys.stderr, flush=True)
    _publish()
    return 200, {"ok": True, "item": _gh.shown(gid), "state": state, "flags": _fy.payload(_gh.shown)["flags"]}


async def _client_foryou_call(request: Request, fn: Any, *args: Any):
    from starlette.concurrency import run_in_threadpool
    machine = _client_machine(request.headers.get("authorization", ""))
    if not machine:
        return PlainTextResponse("unauthorized: a machine token is required (Authorization: Bearer …)", status_code=401)
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError
    except Exception:
        return JSONResponse({"error": "the body is a JSON object"}, status_code=400)
    status, out = await run_in_threadpool(fn, machine, *args, body)
    return JSONResponse(out, status_code=status, headers={"Cache-Control": "no-store"})


async def client_foryou_seen(request: Request):
    return await _client_foryou_call(request, _client_foryou_seen)


async def client_item_watch(request: Request):
    return await _client_foryou_call(request, _client_item_watch, str(request.path_params.get("key", "")))


async def client_api(request: Request):
    machine = _client_machine(request.headers.get("authorization", ""))
    if not machine:
        return PlainTextResponse("unauthorized: a machine token is required (Authorization: Bearer …)", status_code=401)
    what = str(request.path_params.get("what", ""))
    if what == "whoami":
        return JSONResponse({"machine": machine}, headers={"Cache-Control": "no-store"})
    if what == "config":
        return JSONResponse(_client_config(), headers={"Cache-Control": "no-store"})
    if what == "recycle-wanted":   # the fleet tool's watchdog: "<count> <id>[@<epoch>][~<repo>:pr<N>]…" of what a recycle of this machine would serve now
        from starlette.concurrency import run_in_threadpool
        ids = await run_in_threadpool(_recycle_wanted_tokens, machine)
        return PlainTextResponse(" ".join([str(len(ids)), *ids]), headers={"Cache-Control": "no-store"})
    if what == "puller-lag":       # the fleet tool's watchdog: "<hostname> <reported> <current>" per box whose puller is behind
        from starlette.concurrency import run_in_threadpool
        rows = await run_in_threadpool(_clients.puller_lag)
        return PlainTextResponse("".join(f"{h} {r} {c}\n" for h, r, c in rows), headers={"Cache-Control": "no-store"})
    status, ctype, body = _client_get(what, dict(request.query_params))
    return PlainTextResponse(body, status_code=status, media_type=ctype, headers={"Cache-Control": "no-store"})


def register(mcp, *, client_get, client_post, recycle_wanted_tokens) -> None:
    """Add the routes to the server's `mcp`, in the order they were declared in server.py. Called once."""
    global _client_get, _client_post, _recycle_wanted_tokens
    _client_get, _client_post, _recycle_wanted_tokens = client_get, client_post, recycle_wanted_tokens
    mcp.custom_route("/client/{what}", methods=["POST"])(client_write)
    mcp.custom_route("/client/for-you/seen", methods=["POST"])(client_foryou_seen)
    mcp.custom_route("/client/items/{key}/watch", methods=["POST"])(client_item_watch)
    mcp.custom_route("/client/{what}", methods=["GET"])(client_api)
