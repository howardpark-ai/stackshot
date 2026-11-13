"""board_pages.py: the board at the root: /, /index.html, /render-stamp and the catch-all /{name:path} that serves the page files, the icons, the manifest and the details pages, with the helpers only they read
(the healthz body and the checkout's commit, the page at a path, the receivers' response).

`register(mcp, *, contact_label)` adds the routes to the server's `mcp` in the order they were declared in server.py, the catch-all last. `contact_label` is the server's own, looked up when a call is made."""
from __future__ import annotations

import datetime as dt
import inspect
import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from stackshot import paths as _paths
from stackshot.anchors import receiver_health as _rh
from stackshot.core import config as _cfg, readonly as _ro, store as _store, interp as _interp
from stackshot.github import ghsync as _gh
from stackshot.model.ids import _ITEM_PATH, _item_gid
from stackshot.service.store import _load
from stackshot.web import i18n as _i18n, render as _rmod
from stackshot.web.answers import _answer_token
from stackshot.web.auth import signin as _signin
from stackshot.web.auth.signin import _APP_ICON_DIR, _APP_ICONS, _FONT_PATH, _UI_PUBLIC, _ui_guard
from stackshot.web.board_home import _BOARD_GEN_LOCK, _board_home_slot
from stackshot.web.routes.answers import _watch_box


ZONE = _cfg.tz()
_HERE = _paths.ROOT
_contact_label = None      # the server's own, set by register()


def _healthz_body() -> str:
    """/healthz: "ok" always (the status is what a unit and deploy.sh read); a second line when the interpreter this server runs on
    is gone (a cache clean-up deleted its uv environment): children still start through uv, and the line says so.
    One stat, no process."""
    st = _interp.interpreter_status()
    body = "ok" if st["exists"] else f"ok\ndelivery interpreter missing: {st['path']} (children start with {st['fallback'] or 'nothing: deliveries fail'})"
    return body + "\n" + _ro.healthz_line(_store.STORE) if _ro.is_read_only() else body      # a standby adds `read-only: yes; data age: <s>s`; the first line stays "ok"


def _head_commit() -> str | None:
    """The short commit this server's checkout is at, read from its .git directory (file reads: no process, no lock); None when it cannot be read.
    For /healthz?format=json."""
    try:
        g = _HERE / ".git"
        if g.is_file():                                         # a worktree: `gitdir: <path>`
            g = Path(g.read_text().split("gitdir:", 1)[1].strip())
        head = (g / "HEAD").read_text().strip()
        if not head.startswith("ref:"):
            return head[:12]
        ref = head.split(None, 1)[1]
        common = g / "commondir"
        for base in (g, (g / common.read_text().strip()).resolve() if common.is_file() else g):
            if (base / ref).is_file():
                return (base / ref).read_text().strip()[:12]
            packed = base / "packed-refs"
            if packed.is_file():
                for line in packed.read_text().splitlines():
                    if line.endswith(" " + ref):
                        return line.split()[0][:12]
        return None
    except Exception:  # noqa: BLE001
        return None


_SITE_DIR = _cfg.state("site")
_SITE_TYPES = {".html": "text/html", ".svg": "image/svg+xml", ".txt": "text/plain", ".json": "application/json", ".md": "text/markdown", ".css": "text/css", ".png": "image/png"}


def _ui_mods():
    """The page renderers: (render, search, runners) of the board (ui/render.py, ui/search.py, ui/runners.py)."""
    from stackshot.web.ui import render as r2, runners as n2, search as s2
    return r2, s2, n2


_RO_BOARD: dict[str, Any] = {"at": 0.0, "r": None}


def _ro_board() -> dict[str, Any] | None:
    """The board's two renders (full, brief) made in memory from the copy's store, for a standby: the publisher is off there, so
    board.md never exists and nothing may be written to make it. Kept 60 s; the last good one is served if a render fails."""
    now = time.time()
    if _RO_BOARD["r"] is None or now - _RO_BOARD["at"] > 60:
        try:
            _RO_BOARD["r"] = _rmod.render_all(str(_store.STORE))
            _RO_BOARD["at"] = now
        except Exception as e:  # noqa: BLE001
            print(f"standby render failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return _RO_BOARD["r"]


_STAMP_RE = re.compile(rb'<meta name="stackshot-rendered" content="([0-9]+)">')   # the stamp the page carries: when it was drawn


def _details_key(path: str) -> str:
    """A project details page's key from a request path ("projects/x", "projects/x.html", "projects/x/"), '' when the path
    is not a page key. The pattern is the page dirs + a slug path; nothing is looked up here."""
    key = str(path or "").strip("/")
    if key.endswith(".html"): key = key[:-5]
    return key if re.fullmatch(_cfg.page_dirs_re() + r"/[\w./-]+", key) and ".." not in key else ""


def _item_page(request: Request, gid: str):
    """An item's own page at /items/<gid>: its fields, scoped anchors and its history from the store's
    git, rendered on request so it is always current. Behind the board's sign-in; an id the store does not hold is 404.
    for a signed-in viewer (_ui_email) the page carries the answer box, with the form's token for this item."""
    g = _ui_guard(request)
    if g is not None:
        return g
    email = _signin._ui_email(request)
    rmod = _ui_mods()[0]
    box = {"action": f"/items/{_gh.href_id(gid)}/answer", "token": _answer_token(email, gid),
           "sent": str(request.query_params.get("sent") or "")} if email else None
    try:
        try:
            watch = _watch_box(email, gid, _load(gid))
        except Exception:  # noqa: BLE001  — the control is an extra; the page never fails for it
            watch = None
        board = rmod.Board(str(_store.STORE))
        kw: dict[str, Any] = {}
        if "contact" in inspect.signature(board.item_html).parameters:     # chosen by the renderer, not the URL prefix: the one that draws the side column's first row takes the derived contact (an open item's live one)
            try:
                kw["contact"] = _contact_label(_load(gid))
            except Exception:  # noqa: BLE001  — an extra; the row then reads the stored contact
                pass
        return HTMLResponse(board.item_html(gid, answer=box, watch=watch, **kw), headers={"Cache-Control": "no-store"})
    except KeyError:
        return PlainTextResponse("no such item", status_code=404)


def _details_page(request: Request, key: str):
    """The details page of one board row (a top-level project and its sub-pages: sessions, anchors, the routing log),
    rendered on request: the hub appends between publishes, so this page is always current. Behind the board's sign-in."""
    g = _ui_guard(request)
    if g is not None:
        return g
    try:
        return HTMLResponse(_ui_mods()[0].Board(str(_store.STORE), contact_of=_contact_label).routing_html(key), headers={"Cache-Control": "no-store"})
    except KeyError:
        return PlainTextResponse("no such project", status_code=404)


# The web app manifest, so the board installs as an app window (Chrome "Install page as app"). render.py's _APP_HEAD links it
# with crossorigin="use-credentials" so Chrome's fetch carries the Cloudflare Access cookie; in the server's own sign-in it is
# public like the icons it names: the favicon (<state>/site/favicon.svg, sizes "any") and the PNGs of _APP_ICONS (a launcher
# or splash screen that rasterises the SVG at a small size and scales it up looks soft). theme_color
# is the light theme's --bg token, the background of the board's sticky header; background_color, the splash screen's, is the
# mark's tile colour (#1f1f21), the full-bleed background of every PNG icon, so the splash is the icon's own dark.
# Each icon's src carries its version (render.py icon_href, read at the start), so a new icon is a new URL to the installer;
# the manifest itself is no-cache, so the next fetch sees the new src.
_MANIFEST = {"id": "/", "name": "stackshot", "short_name": "stackshot", "start_url": "/", "scope": "/", "display": "standalone",
             "theme_color": "#fafaf8", "background_color": "#1f1f21",
             "icons": [{"src": _rmod.icon_href("favicon.svg"), "type": "image/svg+xml", "sizes": "any", "purpose": "any"}]
                      + [{"src": _rmod.icon_href(n), "type": "image/png", "sizes": f"{px}x{px}", "purpose": p} for n, (px, p) in _APP_ICONS.items()]}
_IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}


def _icon_file(request: Request, p: Path, media_type: str) -> FileResponse:
    """An icon from disk. A request whose ?v= is the version of the bytes on disk now (render.py asset_version) may be kept a
    year and never revalidated: that URL can only ever name these bytes. Any other request, the unversioned URL and a stale
    version included, is served exactly as before (no Cache-Control of its own)."""
    v = request.query_params.get("v")
    return FileResponse(str(p), media_type=media_type, headers=_IMMUTABLE if v and v == _rmod.asset_version(p) else None)


def _page_at(request: Request, name: str):
    """The page a path names (`name` is the path with the first slash off): an item's page at items/<gid>, a project's details page at <page key>; None when the
    path names neither. The redirects (items/<gid>.html, items/<gid>/ and an id's old form to its address now, <key>.html and <key>/ to <key>) go to the page."""
    m = _ITEM_PATH.fullmatch(name)
    if m:                                 # /items/<gid>: the item's page; /items/<gid>.html and /items/<gid>/ → 301 to /items/<gid>
        raw = m.group(1)
        gid = _item_gid(raw)              # a temporary id's address → l<n>, /items/<n> → g<n>, an old id → its id now
        if not gid:
            return PlainTextResponse("no such item", status_code=404)
        at = _gh.href_id(gid)             # where the page lives: the id, an issue-numbered one at its number (/items/g<n> redirects to /items/<n>),
                                          # a temporary one at board-tmp-<machine>-<n> (/items/l<n> redirects there)
        if m.group(2) or at != raw:
            return RedirectResponse("/items/" + at, status_code=301)
        return _item_page(request, gid)
    key = _details_key(name)
    if key:                               # /<page key>: the project's details page; /<key>.html and /<key>/ → 301 to /<key>
        if name != key:
            return RedirectResponse("/" + key, status_code=301)
        return _details_page(request, key)
    return None


def _receivers_response():
    """anchor-hub's live receiver checks (receivers.json), read on each request: no render, no git."""
    try:
        ast = json.load(open(_cfg.state("anchor-hub", "status.json"), encoding="utf-8"))
        out = {}
        for k, v in (ast.get("receivers") or {}).items():
            try: ts = int(dt.datetime.strptime(str(v.get("checked", "")), "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZONE).timestamp())
            except Exception: ts = 0
            late = _rh.stale_age(k, bool(v.get("ok")), ts, time.time(), (ast.get("hold") or {}).get(k, 0))      # seconds since a healthy receiver's last check when that is over twice its beat (an announced wait counted out), else 0
            out[k] = {"ok": bool(v.get("ok")), "error": v.get("error"), "checked": v.get("checked", ""), "ts": ts, "type": _rmod.receiver_type(ast, k),
                      "stale": late, "stale_note": _rh.stale_note(k, late) if late else ""}
        return JSONResponse(out, headers={"Cache-Control": "no-store"})
    except Exception:
        return PlainTextResponse("unavailable", status_code=503)


# ----------------------------------------------------------------------------- the board at the root
# The board is drawn by the page renderers in ui/ (ui/render.py, ui/search.py, ui/runners.py), on request, from the store, behind the sign-in. The home is drawn on request and kept for
# _BOARD_HOME_TTL_S, and dropped at once by a publish and by a write from a page of the board.
_BOARD_HOME_LOCK = threading.Lock()         # one render at a time: a burst of requests after a drop makes one
_BOARD_HOME_TTL_S = 30.0
_BOARD_FAIL_BACKOFF_S = 10.0                # after a failed draw no other is tried for this long: the last good copy (or the plain 503) is served meanwhile


def _board_home_draw_locked() -> None:
    """Draw the root home if none is held or the held one is older than _BOARD_HOME_TTL_S, and no draw failed within _BOARD_FAIL_BACKOFF_S. The caller holds _BOARD_HOME_LOCK. Each language has its own
    kept draw (the request's, i18n.current(); English is _BOARD_HOME)."""
    now = time.time()
    slot = _board_home_slot(_i18n.current())
    sig = _i18n.signature()      # a catalog added, removed or edited makes the held draws stale at once (the switch and the words are in them)
    if slot["html"] is not None and now - slot["at"] <= _BOARD_HOME_TTL_S and slot.get("sig") == sig:
        return
    if now - slot["failed"] < _BOARD_FAIL_BACKOFF_S:
        return
    with _BOARD_GEN_LOCK:
        gen = slot["gen"]
    try:
        from stackshot.web.ui import render as r2
        page = r2.Board(str(_store.STORE), contact_of=_contact_label).html()
        slot["drawn"] = int(now)
        slot["sig"] = sig
        slot["html"] = page
        slot["failed"] = 0.0
        with _BOARD_GEN_LOCK:                # a drop between the start of the draw and here is not overwritten: the next read draws again
            slot["at"] = now if slot["gen"] == gen else 0.0
    except Exception as e:  # noqa: BLE001
        slot["failed"] = time.time()  # when it failed, not when it started: a slow failing draw still backs off
        print(f"home render failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


def _board_home() -> str | None:
    """The root home page as HTML: the kept one while it is younger than _BOARD_HOME_TTL_S, else drawn now; the last good one if a draw fails (and for _BOARD_FAIL_BACKOFF_S after it, with no new draw); None before the first."""
    with _BOARD_HOME_LOCK:
        _board_home_draw_locked()
        return _board_home_slot(_i18n.current())["html"]


def _board_home_kick() -> None:
    """Start one background draw of the root home when none is held or the held one is expired (and no draw failed within _BOARD_FAIL_BACKOFF_S). It never waits: with a draw already running (the
    lock is taken) or nothing to draw it returns at once, so a burst of polls makes at most one thread."""
    if not _BOARD_HOME_LOCK.acquire(blocking=False):
        return
    started = False
    try:
        now = time.time()
        lang = _i18n.current()
        slot = _board_home_slot(lang)
        if (slot["html"] is None or now - slot["at"] > _BOARD_HOME_TTL_S or slot.get("sig") != _i18n.signature()) and now - slot["failed"] >= _BOARD_FAIL_BACKOFF_S:
            def run() -> None:
                try:
                    with _i18n.use(lang):       # a new thread has no request language: the draw is the one asked for
                        _board_home_draw_locked()
                finally:
                    _BOARD_HOME_LOCK.release()
            threading.Thread(target=run, name="home-draw", daemon=True).start()
            started = True
    finally:
        if not started:
            _BOARD_HOME_LOCK.release()


def _board_home_stamp() -> int | None:
    """When the root home the server holds was drawn (epoch seconds): the stamp the page carries, else the time of the draw; None while nothing has been drawn. It only reads: it never draws and
    never waits for a draw, and a drop does not change it (the copy held is the one the stamp tells). Never 0."""
    slot = _board_home_slot(_i18n.current())
    page = slot["html"]
    if page is None:
        return None
    m_ = _STAMP_RE.search(page.encode("utf-8", "replace")[:4096])
    ts = int(m_.group(1)) if m_ else int(slot["drawn"])
    return ts if ts > 0 else None


async def board_home(request: Request):
    """The board: the home drawn by the page renderer (ui/render.py), on request, behind the sign-in."""
    g = _ui_guard(request)
    if g is not None:
        return g
    from starlette.concurrency import run_in_threadpool
    page = await run_in_threadpool(_board_home)
    if page is None:
        return PlainTextResponse("board not rendered yet", status_code=503)
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


async def board_render_stamp(request: Request):
    """{"ts": the draw time of the home the server holds}: its staleness and reachability poll. It never waits for a draw: when the held copy is expired or
    absent it starts one in the background (at most one at a time, not within the back-off after a failure) and answers at once with the stamp held, so an open page sees the new stamp at its next
    poll. With none held it answers 503 JSON (the page's script reads that as unreachable and asks again in 15 s), never a ts of 0."""
    g = _ui_guard(request)
    if g is not None:
        return g
    _board_home_kick()
    ts = _board_home_stamp()
    if ts is None:
        return JSONResponse({"error": "board not rendered yet"}, status_code=503, headers={"Cache-Control": "no-store"})
    return JSONResponse({"ts": ts}, headers={"Cache-Control": "no-store"})


async def site_file(request: Request):
    """Static files next to the board (favicon, robots.txt, versions.json), a project's details page at /<page key>
    (projects/x, projects/hub, projects/x/sub), and an item's page at /items/<gid>. Anything else is 404; /mcp, the OAuth, /client, /routing and /audit routes are matched first.
    The page dirs ([pages] dirs: projects/, infra/) are thereby reserved in the site's URL namespace: no static file is served under them."""
    name = request.path_params.get("name", "")
    if name == "healthz":
        if str(request.query_params.get("format") or "").lower() == "json":       # {ok, read_only, data_age_s, commit}, public like the plain one
            return JSONResponse(_ro.healthz_json(_store.STORE, _head_commit()), headers={"Cache-Control": "no-store"})
        return PlainTextResponse(_healthz_body())
    if name == "healthz.json":
        return JSONResponse(_ro.healthz_json(_store.STORE, _head_commit()), headers={"Cache-Control": "no-store"})
    r = _page_at(request, name)
    if r is not None:
        return r
    if name not in _UI_PUBLIC:
        g = _ui_guard(request)
        if g is not None:
            return g
    if name == "manifest.webmanifest":
        return JSONResponse(_MANIFEST, media_type="application/manifest+json", headers={"Cache-Control": "no-cache"})
    if name == _FONT_PATH:                # /fonts/<the bundled font file>, versioned by ?v= like the icons (immutable when the version is current)
        p = _rmod.FONT_DIR / _rmod.FONT_FILE
        return _icon_file(request, p, "font/woff2") if p.is_file() else PlainTextResponse("not found", status_code=404)
    if name in _APP_ICONS:                # from the checkout, not <state>/site: they ship with the code that names them
        p = _APP_ICON_DIR / name
        return _icon_file(request, p, "image/png") if p.is_file() else PlainTextResponse("not found", status_code=404)
    if name == "board.md" and _ro.is_read_only():       # standby: from the in-memory render (_ro_board), no file
        from starlette.concurrency import run_in_threadpool
        r = await run_in_threadpool(_ro_board)
        if not r:
            return PlainTextResponse("board not rendered yet", status_code=503)
        return PlainTextResponse(r["full"], media_type="text/markdown")
    if name == "receivers.json":          # anchor-hub's live receiver checks, read on each request (no render, no git)
        return _receivers_response()
    if name == "board.md":
        md = _cfg.path("paths", "markdown")
        return FileResponse(str(md), media_type="text/markdown") if md.exists() else PlainTextResponse("board.md not rendered yet", status_code=503)
    if "/" in name or name.startswith(".") or not name:
        return PlainTextResponse("not found", status_code=404)
    p = _SITE_DIR / name
    if p.is_file() and p.suffix in _SITE_TYPES:
        if name == "favicon.svg":         # linked with its version like the app icons (render.py icon_href)
            return _icon_file(request, p, _SITE_TYPES[p.suffix])
        return FileResponse(str(p), media_type=_SITE_TYPES[p.suffix])
    return PlainTextResponse("not found", status_code=404)


def register(mcp, *, contact_label) -> None:
    """Add the routes to the server's `mcp`, in the order they were declared in server.py. Called once."""
    global _contact_label
    _contact_label = contact_label
    mcp.custom_route("/index.html", methods=["GET"])(board_home)
    mcp.custom_route("/", methods=["GET"])(board_home)
    mcp.custom_route("/render-stamp", methods=["GET"])(board_render_stamp)
    mcp.custom_route("/{name:path}", methods=["GET"])(site_file)
