"""answer_frame.py: the route of GET /items/{key}/answer-frame, one item's answer block for another site of the instance to show in a frame (docs/answer-frame.md; the page itself is ui/answer_frame.py).

It exists only while [ui] answer_frame_origins names a site that may frame it; with the list empty the address is answered by the board's catch-all, as a path no route has. Its answers, and no
other route's, say who may frame them (Content-Security-Policy: frame-ancestors) and so leave out the X-Frame-Options every other answer gets (web/frame_guard.py). Who may answer is not
decided here: the form posts to the item's own answer route (routes/answers.py) with its own gates. A GET writes nothing.

`register(mcp)` adds the route to the server's `mcp`; it goes before the catch-all."""
from __future__ import annotations

import math
import re
import time

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from stackshot.core import config as _cfg, store as _store
from stackshot.model.ids import _ITEM_KEY, _item_gid
from stackshot.web import i18n as _i18n
from stackshot.web.answers import _answer_token
from stackshot.web.auth import signin as _signin
from stackshot.web.board_home import viewer as _viewer
from stackshot.web.routes.board_pages import site_file
from stackshot.web.ui import under


def _headers(origins: list[str]) -> dict[str, str]:
    """The frame page's headers. `origins` are the config's validated ones (core/config.py frame_origin): nothing else is ever written into the header."""
    return {"Content-Security-Policy": "frame-ancestors 'self' " + " ".join(origins), "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


def _since(v: str) -> float | None:
    """The time the frame reads against (ui/answer_frame.py state_of), None when it sends none; a value that is no time counts as never (no recorded answer is newer than it)."""
    if not v:
        return None
    try:
        x = float(v)
    except ValueError:
        return math.inf
    return x if math.isfinite(x) else math.inf


def _draw(raw: str, email: str, lang: str, theme: str, origins: list[str], was: str, since: str) -> tuple[str, int]:
    """(the page, its status). Without a board session nothing is looked up, so the page is the same for an item that exists and one that does not."""
    from stackshot.web.ui import answer_frame as frame, render
    common = {"key": raw, "origins": origins, "lang": lang, "theme": theme, "drawn": time.time()}      # the time is taken before the store is read: an answer recorded after it is newer than this drawing
    with _i18n.use(lang):
        if not email:
            href = under("/items/" + raw)
            return frame.page(frame.signed_out_body(href), state="signed_out", href=href, **common), 200
        gid = _item_gid(raw)
        board = render.Board(str(_store.STORE)) if gid else None
        try:
            r = board.item(gid) if board else None
        except KeyError:
            r = None
        if r is None:
            home = under("/")
            return frame.page(frame.closed_body(home), state="closed", href=home, **common), 404
        state, what = frame.state_of(board, r, _answer_token(email, gid), was, _since(since), member=_viewer())
        return frame.page(frame.item_body(board, r, state, what), state=state, href=render.id_href(gid), ref=render.question_ref(r) if state == "open" else "", channel=gid, **common), 200


async def answer_frame(request: Request):
    raw = str(request.path_params.get("key") or "")
    origins = _cfg.answer_frame_origins()
    if not origins:      # not set up: no such page. The catch-all answers, with its own sign-in and 404, as it did before the route was there
        request.scope["path_params"] = {"name": f"items/{raw}/answer-frame"}
        return await site_file(request)
    if not re.fullmatch(_ITEM_KEY, raw):
        return PlainTextResponse("no such item", status_code=404)
    q = request.query_params
    lang = str(q.get("lang") or "")
    if lang not in _i18n.available():
        lang = _i18n.current()
    page, status = await run_in_threadpool(_draw, raw, _signin._ui_email(request), lang, str(q.get("theme") or ""), origins, str(q.get("was") or ""), str(q.get("since") or ""))
    return Response(page, status_code=status, media_type="text/html", headers=_headers(origins))


def register(mcp) -> None:
    mcp.custom_route("/items/{key}/answer-frame", methods=["GET"])(answer_frame)
