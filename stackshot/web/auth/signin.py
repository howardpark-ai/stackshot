"""signin.py: the board's own sign-in: [auth] ui_open and ui_session_days, the signed session and flow cookies (key, signature, renewal), who is signed in, the guard a page asks, the board's
own OAuth client (its registration, its callback, how it is told apart from any other client), the files a signed-out page may fetch, and the three routes /ui/login, /ui/callback and
/ui/logout (with `_ui_exchange`, which verifies the token with the server's `mcp.auth`). `_auth_mode`, which the guard and the server both read, is here too.

The module cannot import server.py, which imports it, so it has no `mcp` of its own: `register(mcp)` is called once by server.py, where the routes were declared, and adds the three routes in
that order. A suite that pins the sign-in's clock (`_ui_now`), replaces its call to the server's own OAuth endpoints (`_ui_http`, `_ui_client_id`) or the token exchange (`_ui_exchange`), or sets the
auth mode (`_auth_mode`) sets it on this module, the one place the readers look it up. What server.py's own routes read (`_ui_guard`, `_ui_email`, `_ui_open`, `_ui_renewed`, `_ui_key`, the public
files) it imports from here."""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

from starlette.requests import Request
from starlette.responses import PlainTextResponse

from stackshot import paths as _paths
from stackshot.core import config as _cfg
from stackshot.web import render as _rmod
from stackshot.core.instance import NAME


def _auth_mode() -> str:
    return os.environ.get("STACKSHOT_AUTH") or os.environ.get("BOARD_MCP_AUTH") or str(_cfg.CFG["auth"]["mode"])


# ----------------------------------------------------------------------------- the board's own sign-in, step e)
# [auth] ui_open = true (today): the web UI is served to whoever reaches it, and the edge decides who that is (Cloudflare
# Access in front of the hostname). ui_open = false: the server asks for a sign-in itself, with the OAuth it already runs
# for /mcp — the board is one more client of its own /authorize, so no second OAuth app and no new redirect URI at Google.
# The signed-in address is kept in a signed cookie; only [auth] allowed_emails get in.
def _ui_open() -> bool:
    return bool(_cfg.get("auth", "ui_open", default=True))


def _ui_days() -> int:
    return int(_cfg.get("auth", "ui_session_days") or 30)


_UI_COOKIE, _UI_FLOW = "stackshot_ui", "stackshot_ui_flow"
# The installed app's PNG icons, committed in the checkout's icons/ (rebuilt from _ICON by tools/make_icons.py): name → (px, purpose)
_APP_ICONS = {"icon-192.png": (192, "any"), "icon-512.png": (512, "any"), "icon-maskable-512.png": (512, "maskable"), "apple-touch-icon.png": (180, "any")}
_APP_ICON_DIR = _paths.ROOT / "icons"
_FONT_PATH = "fonts/" + _rmod.FONT_FILE                          # a bundled monospace font (OFL), from the checkout like the icons
_UI_PUBLIC = {"healthz", "healthz.json", "robots.txt", "favicon.svg", "favicon.ico", "manifest.webmanifest", *_APP_ICONS, _FONT_PATH}   # never behind the sign-in (a signed-out page that shows code asks for it too)
_UI_CLIENT: dict[str, str] = {}                                             # the board's own OAuth client, registered once per run


def _ui_key() -> bytes:
    """The cookie-signing key, <secrets>/ui-session.key (made on first use, 0600)."""
    p = _cfg.secrets("ui-session.key")
    try:
        return p.read_bytes()
    except Exception:
        import secrets as _s
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(_s.token_bytes(32))
        return p.read_bytes()


def _ui_sign(payload: str) -> str:
    import base64, hashlib, hmac
    b = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return b + "." + hmac.new(_ui_key(), b.encode(), hashlib.sha256).hexdigest()


def _ui_unsign(value: str) -> str:
    """The payload of a cookie this server signed, '' for anything else."""
    import base64, hashlib, hmac
    b, _, sig = str(value or "").partition(".")
    if not b or not hmac.compare_digest(sig, hmac.new(_ui_key(), b.encode(), hashlib.sha256).hexdigest()):
        return ""
    try:
        return base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)).decode()
    except Exception:
        return ""


def _ui_now() -> float:
    """The clock the board's sign-in reads (a test pins it)."""
    return time.time()


def _ui_session(request: Request) -> dict[str, Any]:
    """The board's session cookie as it stands: its payload when this server signed it, the address is still allowed and it has not run out, else {}."""
    try:
        d = json.loads(_ui_unsign(request.cookies.get(_UI_COOKIE, "")) or "{}")
    except Exception:
        return {}
    if not isinstance(d, dict):
        return {}
    email = str(d.get("email") or "")
    return d if email in _cfg.CFG["auth"]["allowed_emails"] and float(d.get("exp") or 0) > _ui_now() else {}


def _ui_email(request: Request) -> str:
    """Who is signed in to the board, '' when nobody (no cookie, a forged or expired one, an address no longer allowed)."""
    return str(_ui_session(request).get("email") or "")


def _ui_set_session(resp, email: str) -> None:
    """Put the board's session cookie on a response: signed, for [auth] ui_session_days from now."""
    secs = 86400 * _ui_days()
    resp.set_cookie(_UI_COOKIE, _ui_sign(json.dumps({"email": email, "exp": _ui_now() + secs})), max_age=secs,
                    httponly=True, secure=str(_cfg.CFG["auth"]["base_url"]).startswith("https"), samesite="lax", path="/")


def _ui_is_navigation(request: Request) -> bool:
    """True when a person's browser is opening the page (Sec-Fetch-Mode: navigate), or the client says nothing about it (a tool); False for a script's fetch() or a
    sub-resource. A navigation can be sent to the sign-in; a script's request cannot use that, it needs the plain 401."""
    mode = request.headers.get("sec-fetch-mode")
    return not mode or mode == "navigate"


# A visit restarts the session's days. The cookie is written again only when it has used up an hour of them, so a burst of page loads does not set a cookie on each.
_UI_RENEW_AFTER = 3600


def _ui_renewed(request: Request, resp):
    """The response with the session cookie renewed when the request is a visit by someone signed in: a GET that a browser opens as a page (not a script's fetch, so a tab left polling
    does not keep a session alive on its own), with a session that is still good (an expired one never comes back; a removed address is not renewed). Not on /ui/ (the sign-in's own routes:
    logout deletes the cookie), not on a failed answer, not on a public cacheable file."""
    try:
        if (request.method != "GET" or _ui_open() or _auth_mode() == "off" or request.url.path.startswith("/ui/")
                or request.url.path.strip("/") in _UI_PUBLIC or not _ui_is_navigation(request) or getattr(resp, "status_code", 200) >= 400
                or "public" in str(resp.headers.get("cache-control") or "")):
            return resp
        d = _ui_session(request)
        if d and float(d["exp"]) - _ui_now() <= 86400 * _ui_days() - _UI_RENEW_AFTER:
            _ui_set_session(resp, str(d["email"]))
    except Exception as e:  # noqa: BLE001
        print(f"sign-in not renewed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return resp


def _ui_guard(request: Request):
    """None when the request may see the board, else the way to the sign-in: a redirect for a page the browser is opening, a plain 401 for a script's request (a page's script
    that follows a redirect would run the sign-in again and again from a tab nobody is looking at)."""
    if _ui_open() or _auth_mode() == "off" or _ui_email(request):
        return None
    if not _ui_is_navigation(request):
        return PlainTextResponse("signed out: open the board in the browser to sign in again", status_code=401, headers={"Cache-Control": "no-store"})
    from urllib.parse import quote
    from starlette.responses import RedirectResponse
    nxt = request.url.path + (("?" + request.url.query) if request.url.query else "")
    return RedirectResponse("/ui/login?next=" + quote(nxt, safe=""), status_code=302)       # the path as asked: sign-in comes back to the page it started from

def _ui_http(method: str, path: str, data: dict[str, Any], form: bool = False) -> tuple[int, dict[str, Any]]:
    """One call to this server's own OAuth endpoints, over its local port."""
    import urllib.error, urllib.parse, urllib.request
    url = f"http://{_cfg.CFG['server'].get('host', '127.0.0.1')}:{_cfg.CFG['server'].get('port', 8020)}{path}"
    body = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/x-www-form-urlencoded" if form else "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)[:160]}


def _ui_redirect_uri() -> str:
    return str(_cfg.CFG["auth"]["base_url"]).rstrip("/") + "/ui/callback"


def _ui_client_id() -> str:
    """The board's own OAuth client at this server (dynamic registration, once per run)."""
    if not _UI_CLIENT.get("id"):
        status, d = _ui_http("POST", "/register", {"client_name": f"{NAME} board", "redirect_uris": [_ui_redirect_uri()], "grant_types": ["authorization_code", "refresh_token"],
                                                    "response_types": ["code"], "token_endpoint_auth_method": "none"})
        if status not in (200, 201) or not d.get("client_id"):
            raise RuntimeError(f"the board could not register with its own sign-in service [{status}]: {str(d)[:160]}")
        _UI_CLIENT["id"] = str(d["client_id"])
    return _UI_CLIENT["id"]


def _ui_is_board_client(client_id: str, redirect_uri: str) -> bool:
    """True for the one client the board registered for its own sign-in in this run, asking for its own callback; a client that merely looks like it is not."""
    cid = _UI_CLIENT.get("id")
    return bool(cid) and str(client_id) == cid and str(redirect_uri) == _ui_redirect_uri()


_SERVER: dict[str, Any] = {}                                                # the server's `mcp`, set once by register(): _ui_exchange verifies the token with its `auth`


def _ui_exchange(code: str, verifier: str) -> str:
    """An authorization code → the address that signed in ('' when the exchange or the token does not hold)."""
    import asyncio
    status, d = _ui_http("POST", "/token", {"grant_type": "authorization_code", "code": code, "redirect_uri": _ui_redirect_uri(),
                                             "client_id": _ui_client_id(), "code_verifier": verifier}, form=True)
    tok = str(d.get("access_token") or "") if status == 200 else ""
    if not tok:
        return ""
    at = asyncio.run(_SERVER["mcp"].auth.verify_token(tok))
    return str((getattr(at, "claims", None) or {}).get("email") or "")


async def ui_login(request: Request):
    """Start the board's sign-in: send the browser to this server's own /authorize (which hands on to Google)."""
    import base64, hashlib, secrets as _s
    from urllib.parse import urlencode
    from starlette.concurrency import run_in_threadpool
    from starlette.responses import RedirectResponse
    if _ui_open() or _auth_mode() == "off":
        return RedirectResponse("/", status_code=302)
    if not _ui_is_navigation(request):          # a script's request starts nothing: no OAuth transaction, and no flow cookie that would replace the one of a sign-in under way in another tab
        return PlainTextResponse("signed out: open the board in the browser to sign in again", status_code=401, headers={"Cache-Control": "no-store"})
    nxt = str(request.query_params.get("next") or "/")
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/"
    try:
        cid = await run_in_threadpool(_ui_client_id)
    except Exception as e:  # noqa: BLE001
        return PlainTextResponse(f"sign-in is not available: {e}", status_code=503)
    verifier = _s.token_urlsafe(48); state = _s.token_urlsafe(16)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    q = urlencode({"response_type": "code", "client_id": cid, "redirect_uri": _ui_redirect_uri(), "code_challenge": challenge, "code_challenge_method": "S256",
                   "state": state, "scope": "openid https://www.googleapis.com/auth/userinfo.email"})
    r = RedirectResponse(str(_cfg.CFG["auth"]["base_url"]).rstrip("/") + "/authorize?" + q, status_code=302)
    r.set_cookie(_UI_FLOW, _ui_sign(json.dumps({"state": state, "verifier": verifier, "next": nxt, "exp": _ui_now() + 600})), max_age=600,
                 httponly=True, secure=str(_cfg.CFG["auth"]["base_url"]).startswith("https"), samesite="lax", path="/ui")
    return r


async def ui_callback(request: Request):
    """Finish the board's sign-in: the code this server's /authorize sent back becomes a signed session cookie."""
    from starlette.concurrency import run_in_threadpool
    from starlette.responses import RedirectResponse
    try:
        flow = json.loads(_ui_unsign(request.cookies.get(_UI_FLOW, "")) or "{}")
    except Exception:
        flow = {}
    code, state = str(request.query_params.get("code") or ""), str(request.query_params.get("state") or "")
    if not code or not flow or state != flow.get("state") or float(flow.get("exp") or 0) < _ui_now():
        return PlainTextResponse("sign-in failed: this link is not part of a sign-in that started here (or it took longer than ten minutes). Open the board again.", status_code=400)
    email = await run_in_threadpool(_ui_exchange, code, str(flow.get("verifier") or ""))
    if email not in _cfg.CFG["auth"]["allowed_emails"]:
        return PlainTextResponse(f"{email or 'this account'} is not allowed on this board", status_code=403)
    r = RedirectResponse(str(flow.get("next") or "/"), status_code=302)
    _ui_set_session(r, email)
    r.delete_cookie(_UI_FLOW, path="/ui")
    return r


async def ui_logout(request: Request):
    r = PlainTextResponse("signed out")
    r.delete_cookie(_UI_COOKIE, path="/")
    return r


def register(mcp) -> None:
    """Add the three sign-in routes to the server's `mcp`, in the order they were declared in server.py. Called once."""
    _SERVER["mcp"] = mcp
    mcp.custom_route("/ui/login", methods=["GET"])(ui_login)
    mcp.custom_route("/ui/callback", methods=["GET"])(ui_callback)
    mcp.custom_route("/ui/logout", methods=["GET"])(ui_logout)
