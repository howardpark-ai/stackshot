"""answers.py: the routes a page posts an answer, a watch or a for-you mark to: /items/{key}/answer, /answer-tokens, /items/{key}/watch and /for-you/seen.

`register(mcp, *, answer)` adds them to the server's `mcp` in the order they were declared in server.py. `answer` is the server's own `_answer`, looked up when a call is made."""
from __future__ import annotations

import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse

from stackshot.fleet.sessions_registry import _session_label
from stackshot.github import ghsync as _gh
from stackshot.model import model as _model
from stackshot.model.ids import _GID, _ITEM_KEY, _item_gid
from stackshot.service import foryou as _fy
from stackshot.service.foryou_events import _foryou_watched
from stackshot.service.store import _load, _path
from stackshot.web.answers import _ANSWER_BODY_MAX, _answer_same_origin, _answer_token
from stackshot.web.auth import signin as _signin
from stackshot.web.auth.signin import _ui_guard, _ui_key, _ui_open
from stackshot.web.board_home import _board_home_drop
from stackshot.web.publish import _publish


_answer = None      # the server's own, set by register()


_BACK_PATH = re.compile(r"/|/index\.html|/projects/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*|/items/[A-Za-z0-9_.-]+")
_BACK_FRAG = re.compile(r"#[A-Za-z0-9_.-]{1,80}")


def _answer_back(v: str) -> tuple[str, str] | None:
    """Where an answer from the home page goes back to: (path, fragment) when `back` is a same-origin path of a known page of the board, else None (the item's page). It starts with a
    single `/` (so not `//` and not `/\\`), has no scheme, backslash, percent escape, control character or query, is `/`, `/index.html`, `/projects/...` or `/items/...`, has no `.` or `..`
    segment, and may end with one `#anchor` (the row's id)."""
    v = str(v or "")
    path, hash_, frag = v.partition("#")
    frag = hash_ + frag
    if not path.startswith("/") or path.startswith("//") or any(ord(c) < 33 or ord(c) > 126 for c in path + frag) or "\\" in v or "%" in v:
        return None
    if not _BACK_PATH.fullmatch(path) or any(seg in (".", "..") for seg in path.split("/")):
        return None
    if frag and not _BACK_FRAG.fullmatch(frag):
        return None
    return path, frag


async def item_answer(request: Request):
    """The owner's answer from an item's page. 403 unless signed in to the board, with the page's token, from the
    board's own origin; 404 for an address that names no item. Then 303 back to the item's page, ?sent=<what happened>."""
    raw = str(request.path_params.get("key") or "")
    if not re.fullmatch(_ITEM_KEY, raw):
        return PlainTextResponse("no such item", status_code=404)
    email = _signin._ui_email(request)
    if not email:
        return PlainTextResponse("sign in to the board to answer an item", status_code=403)
    if not _answer_same_origin(request):
        return PlainTextResponse("refused: this answer did not come from the board's own page", status_code=403)
    body = await request.body()
    if len(body) > _ANSWER_BODY_MAX:
        return PlainTextResponse("refused: the answer is too long", status_code=413)
    from urllib.parse import parse_qs, urlencode
    form = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)
    f = lambda k: (form.get(k) or [""])[0]
    gid = _item_gid(raw)
    if not gid or not _path(gid).exists():
        return PlainTextResponse("no such item", status_code=404)
    import hmac
    if not hmac.compare_digest(f("token"), _answer_token(email, gid)):
        return PlainTextResponse("refused: the form's token does not match; reload the item's page and send again", status_code=403)
    from starlette.concurrency import run_in_threadpool
    code = await run_in_threadpool(_answer, gid, f("choice"), f("text"), f("act"))
    back = _answer_back(f("back"))
    if back:      # from the home page's row: back to the page the form was on, with the item named for its notice
        path, frag = back
        q = {"sent": code, "item": _gh.href_id(gid)}      # the code and the id only: the page's own row names the item, so no text of anyone's rides in the address
        if code in ("done", "donenote", "stepreply"):     # and who takes it from here: a session name, which the page shows only when it is one of the fleet's it knows
            try: q["then"] = _session_label(str(_model.derive(_load(gid)).mover or ""))[:80]
            except Exception: pass
        return RedirectResponse(path + "?" + urlencode(q) + frag, status_code=303, headers={"Cache-Control": "no-store"})
    return RedirectResponse(f"/items/{_gh.href_id(gid)}?" + urlencode({"sent": code}), status_code=303, headers={"Cache-Control": "no-store"})


_ANSWER_TOKENS_MAX = 200


async def answer_tokens(request: Request):
    """The tokens of the answer forms on the home page's Your move rows: {gid: token} for `?ids=g7,g8` (store ids, comma-separated), the same token the item
    page puts in its own form (_answer_token), so the answer goes to the one route above with the one set of gates. The board is a static page for every viewer and carries no token; its
    script asks here and shows a row's form only for the ids it gets. Behind the board's sign-in like the item page; {} for a request that is not signed in (a viewer let in by
    [auth] ui_open, or with auth off, has no token anywhere, as on the item page); an id that names no item is left out."""
    g = _ui_guard(request)
    if g is not None:
        return g
    email = _signin._ui_email(request)
    out: dict[str, str] = {}
    if email:
        for raw in str(request.query_params.get("ids") or "").split(",")[:_ANSWER_TOKENS_MAX]:
            gid = raw.strip()
            if _GID.match(gid) and "#" not in gid and gid not in out and _path(gid).exists():
                out[gid] = _answer_token(email, gid)
    return JSONResponse(out, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


def _watch_token(email: str, gid: str) -> str:
    """The Watch / Mute form's token: an HMAC over the signed-in address and the item, as _answer_token, under its own label."""
    import hashlib, hmac
    return hmac.new(_ui_key(), f"watch\x00{email}\x00{gid}".encode(), hashlib.sha256).hexdigest()


def _watch_box(email: str, gid: str, item: dict[str, Any]) -> dict[str, Any] | None:
    """What the item page needs for its For you control (Watch / Mute / Default), for a signed-in viewer: the form's action and token,
    his stored flag and whether the item is watched now, with the reason."""
    if not email:
        return None
    watched, why = _foryou_watched(gid, item)
    return {"action": f"/items/{_gh.href_id(gid)}/watch", "token": _watch_token(email, gid), "flag": _fy.flag(gid), "watched": watched, "why": why}


async def item_watch(request: Request):
    """The owner's Watch / Mute / Default for one item, from its page (the For you list). The same gates as his answer:
    403 unless signed in to the board, with the page's token, from the board's own origin; 404 for an address that names no item. Then
    303 back to the item's page."""
    raw = str(request.path_params.get("key") or "")
    if not re.fullmatch(_ITEM_KEY, raw):
        return PlainTextResponse("no such item", status_code=404)
    email = _signin._ui_email(request)
    if not email:
        return PlainTextResponse("sign in to the board to watch or mute an item", status_code=403)
    if not _answer_same_origin(request):
        return PlainTextResponse("refused: this did not come from the board's own page", status_code=403)
    body = await request.body()
    if len(body) > 4096:
        return PlainTextResponse("refused: the form is too long", status_code=413)
    from urllib.parse import parse_qs
    form = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)
    f = lambda k: (form.get(k) or [""])[0]
    gid = _item_gid(raw)
    if not gid or not _path(gid).exists():
        return PlainTextResponse("no such item", status_code=404)
    import hmac
    if not hmac.compare_digest(f("token"), _watch_token(email, gid)):
        return PlainTextResponse("refused: the form's token does not match; reload the item's page and send again", status_code=403)
    try:
        _fy.set_flag(gid, f("mode"))
    except ValueError as e:
        return PlainTextResponse(str(e), status_code=400)
    _board_home_drop()                       # the flag is on the home's For you list at its next read
    return RedirectResponse(f"/items/{_gh.href_id(gid)}", status_code=303, headers={"Cache-Control": "no-store"})


async def for_you_seen(request: Request):
    """The owner marks a row of the For you list seen (id=<row id>, or id=all): it leaves the list. The board's page is one file for
    everyone allowed, so there is no per-page token: signed in to the board, from its own origin (the same origin check as his
    answer), the cookie is SameSite=Lax. Then 303 to the board; a fetch from the page's script reads the status only."""
    email = _signin._ui_email(request)
    if not email and not (_ui_open() or _signin._auth_mode() == "off"):
        return PlainTextResponse("sign in to the board", status_code=403)
    if not _answer_same_origin(request):
        return PlainTextResponse("refused: this did not come from the board's own page", status_code=403)
    body = await request.body()
    if len(body) > 4096:
        return PlainTextResponse("refused: the form is too long", status_code=413)
    from urllib.parse import parse_qs
    rid = (parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True).get("id") or [""])[0].strip()
    if not rid or not (rid == "all" or rid.isdigit()):
        return PlainTextResponse("id = a row's number, or all", status_code=400)
    _fy.seen(rid)
    _publish()
    return RedirectResponse("/#for-you", status_code=303, headers={"Cache-Control": "no-store"})


def register(mcp, *, answer) -> None:
    """Add the routes to the server's `mcp`, in the order they were declared in server.py. Called once."""
    global _answer
    _answer = answer
    mcp.custom_route("/items/{key}/answer", methods=["POST"])(item_answer)
    mcp.custom_route("/answer-tokens", methods=["GET"])(answer_tokens)
    mcp.custom_route("/items/{key}/watch", methods=["POST"])(item_watch)
    mcp.custom_route("/for-you/seen", methods=["POST"])(for_you_seen)
