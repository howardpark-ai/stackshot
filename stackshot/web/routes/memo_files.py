"""memo_files.py: the routes of the files on a memo-box note: the upload `POST /items/{key}/files?name=`, the download `GET /items/{key}/files/{id}/{name}` and the machine token's fetch `GET /client/items/{key}/files/{id}/{name}`.

The upload has the answer's gates (signed in to the board, the page's token in `X-Answer-Token`, the board's own origin; 403/404 as the answer's) and streams the body to disk in pieces (service/memo_files.py):
it answers 201 {id, name, size, type}, or the limit's sentence (413 a file or image too big, 400 an empty file or too many waiting, 507 the server's 100 MB full) with nothing kept. A file is sent with a note: the answer form carries
`files=<ids>` (one field with ids separated by commas, or the field repeated; at most 4). The two downloads send the file only when its id is on one of the item's answers: always as an attachment with the type
`application/octet-stream`, `nosniff` and a sandbox policy, never shown by the browser itself, whatever the file is. `register(mcp)` adds the routes."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect, Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse

from stackshot.model.ids import _ITEM_KEY, _item_gid
from stackshot.service import memo_files as _memo
from stackshot.service.store import _load, _path
from stackshot.web.answers import _answer_same_origin, _answer_token
from stackshot.web.auth import signin as _signin
from stackshot.web.auth.signin import _ui_guard

_HEAD = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


def file_ids(values: list[str]) -> list[str]:
    """The ids of a send form's `files` fields: each value may hold several, separated by commas or spaces; empty ones are left out."""
    return [i for v in values for i in re.split(r"[,\s]+", v) if i]


def _item(request: Request) -> tuple[str, dict[str, Any]] | None:
    raw = str(request.path_params.get("key") or "")
    if not re.fullmatch(_ITEM_KEY, raw):
        return None
    gid = _item_gid(raw)
    if not gid or not _path(gid).exists():
        return None
    return gid, _load(gid)


async def upload(request: Request):
    """One file of a note, the request body (any type) with its name in `?name=`: stored as pending on the item until a note with its id is sent."""
    found = _item(request)
    if found is None:
        return PlainTextResponse("no such item", status_code=404)
    gid = found[0]
    email = _signin._ui_email(request)
    if not email:
        return PlainTextResponse("sign in to the board to attach a file", status_code=403)
    if not _answer_same_origin(request):
        return PlainTextResponse("refused: this did not come from the board's own page", status_code=403)
    import hmac
    if not hmac.compare_digest(request.headers.get("x-answer-token", "").encode("utf-8", "surrogatepass"), _answer_token(email, gid).encode("utf-8")):      # bytes: a non-ASCII token is a 403, not a TypeError
        return PlainTextResponse("refused: the page's token does not match; reload the item's page and send again", status_code=403)
    try:
        declared: int | None = int(request.headers.get("content-length", ""))
    except ValueError:
        declared = None
    try:
        up = await run_in_threadpool(_memo.Upload, gid, request.query_params.get("name") or "", declared)
    except _memo.Refused as e:
        return PlainTextResponse(str(e), status_code=e.status, headers=_HEAD)
    try:
        async for chunk in request.stream():
            await run_in_threadpool(up.write, chunk)
        rec = await run_in_threadpool(up.finish)
    except _memo.Refused as e:
        return PlainTextResponse(str(e), status_code=e.status, headers=_HEAD)
    except ClientDisconnect:
        return PlainTextResponse("the upload was cut off", status_code=400, headers=_HEAD)
    finally:
        await run_in_threadpool(up.abort)
    return JSONResponse(rec, status_code=201, headers=_HEAD)


def _send(found: tuple[str, dict[str, Any]] | None, fid: str):
    if found is None:
        return PlainTextResponse("no such file", status_code=404, headers=_HEAD)
    hit = _memo.path_of(found[0], found[1], fid)
    if hit is None:
        return PlainTextResponse("no such file (it may have been removed 30 days after the item closed)", status_code=404, headers=_HEAD)
    path, rec = hit
    name = path.name
    return FileResponse(
        path, media_type="application/octet-stream", filename=None,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name, safe='')}", "X-Content-Type-Options": "nosniff",
                 "Content-Security-Policy": "default-src 'none'; sandbox", "Cache-Control": "private, no-store"})


async def download(request: Request):
    """A file of an item, for a signed-in person (the board's own gate, as the item's page)."""
    g = _ui_guard(request)
    if g is not None:
        return g
    return _send(_item(request), str(request.path_params.get("id") or ""))


async def client_download(request: Request):
    """A file of an item, for a machine: `Authorization: Bearer <the machine's token>` (the client API's own check)."""
    from stackshot.web.routes.client_api import _client_machine
    if not _client_machine(request.headers.get("authorization", ""), request):
        return PlainTextResponse("a machine's token is needed", status_code=401, headers=_HEAD)
    return _send(_item(request), str(request.path_params.get("id") or ""))


def register(mcp) -> None:
    mcp.custom_route("/items/{key}/files", methods=["POST"])(upload)
    mcp.custom_route("/items/{key}/files/{id}/{name}", methods=["GET"])(download)
    mcp.custom_route("/client/items/{key}/files/{id}/{name}", methods=["GET"])(client_download)
