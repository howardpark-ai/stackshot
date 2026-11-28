"""oauth.py: the MCP sign-in provider: `_env` (a secret read from the environment), `_auth` (the auth object the MCP server is built with, from `signin._auth_mode()`; None when the mode is off)
and `_who` (the signed-in identity, allow-listed).

The module needs nothing of server.py (a module here cannot import it, and it runs as `__main__`): it reads the config, the auth mode (`signin.py`) and the board's own client check
(`_ui_is_board_client`, signin.py's). web/app.py calls `_auth()` where it builds `mcp = FastMCP(..., auth=_auth())`, and every tool asks `oauth._who()` through the module, so a suite that
replaces `_who` sets it here. Nothing in this module calls `_who` or `_env` through a name a suite replaces."""
from __future__ import annotations

import os
import sys

from fastmcp.exceptions import ToolError

from stackshot.core import behind_door as _door
from stackshot.core import config as _cfg
from stackshot.core import frontdoor_identity as _ident
from stackshot.core import invites as _invites
from stackshot.core import members as _members
from stackshot.web.auth import signin as _signin
from stackshot.web.auth.signin import _ui_is_board_client


def _env(key: str) -> str:
    """A secret from the environment (secrets/oauth.env): STACKSHOT_<key>, or the older BOARD_MCP_ spelling."""
    return os.environ.get("STACKSHOT_" + key) or os.environ.get("BOARD_MCP_" + key) or ""


def _barred(claims: dict) -> str:
    """Why the registrations refuse the sign-in a verified token's claims describe (a key of `frontdoor_identity.REFUSALS`, "" when none does; core/invites.py). The
    board's machine token is no Google sign-in, so no registration speaks of it."""
    if claims.get("via") == "portal":
        return ""
    return _invites.admit(claims.get("email"), claims.get("sub"), claims.get("email_verified"))


def _redirect_uris() -> list[str]:
    """The redirect URIs a client may ask for: [auth] allowed_client_redirect_uris and the board's own callback, and on a board that can invite people those of the
    apps its setup page names (`invites.APP_REDIRECT_URIS`)."""
    out = list(_cfg.CFG["auth"].get("allowed_client_redirect_uris") or []) + [str(_cfg.CFG["auth"]["base_url"]).rstrip("/") + "/ui/callback"]
    if _invites.settings().on:
        out += [u for u in _invites.APP_REDIRECT_URIS if u not in out]
    return out


def _auth():
    mode = _signin._auth_mode()
    if mode == "off":
        return None
    if mode != "google":
        raise SystemExit(f"unknown auth mode {mode!r}")
    env_file = _cfg.secrets("oauth.env")
    if env_file.exists():
        for ln in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.lstrip().startswith("#"):
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))
    cid, sec = _env("GOOGLE_CLIENT_ID"), _env("GOOGLE_CLIENT_SECRET")
    if not (cid and sec):
        raise SystemExit(f"auth=google but STACKSHOT_GOOGLE_CLIENT_ID/SECRET not set (env file {env_file})")
    from fastmcp.server.auth import AccessToken
    from fastmcp.server.auth.providers.google import GoogleProvider
    scopes = ["openid", "https://www.googleapis.com/auth/userinfo.email"]
    machine = _env("PORTAL_TOKEN").strip()          # the MCP portal's machine token (Cloudflare) — optional
    identity = _cfg.CFG["auth"].get("portal_identity")
    if not identity:
        mine = _members.emails()
        identity = mine[0] if mine or not _door.settings().members else ""      # only a board that reads its members from a front door may list nobody at its start; any other still fails here as before

    class _Provider(GoogleProvider):
        """Google OAuth for every client (claude.ai, panes) PLUS one machine bearer token for the MCP portal:
        the portal's API sync only re-lists an upstream whose credential the portal holds itself, and a per-user OAuth
        grant is not that. The token stands for the owner (`auth.portal_identity`); the direct OAuth path is untouched."""
        async def verify_token(self, token: str):
            import hmac
            # compared as bytes: compare_digest raises TypeError on text with a non-ASCII character, which any client can send, and the app answered 500 instead of 401
            if machine and len(machine) >= 32 and hmac.compare_digest(token.encode("utf-8", "surrogatepass"), machine.encode("utf-8", "surrogatepass")):
                return AccessToken(token=token, client_id="mcp-portal", scopes=scopes, expires_at=None,
                                   claims={"email": identity, "via": "portal"})
            return await super().verify_token(token)

        async def _show_consent_page(self, request):
            """The Allow page is for a third-party client (claude.ai, a connector, anything that registered itself): it is the page that tells the person which client is asking.
            The board's own sign-in is this server asking itself, so it goes straight on to Google, and only for the one client the board registered for itself (_UI_CLIENT)
            with its own callback (/ui/callback). The rest of the protection stays: the consent binding cookie is set as the Allow page's approval sets it and is checked at the
            Google callback, and the code goes to /ui/callback, which takes it only from the browser that holds the signed flow cookie of a sign-in started by /ui/login
            (its state, and the PKCE verifier the code is exchanged with). Any other client, a board look-alike registered with the same callback included, still gets the Allow page."""
            try:
                txn_id = request.query_params.get("txn_id") or ""
                txn = await self._transaction_store.get(key=txn_id) if txn_id else None
                if txn is not None and _ui_is_board_client(txn.client_id, txn.client_redirect_uri):
                    import secrets as _s
                    from starlette.responses import RedirectResponse
                    txn.consent_token = _s.token_urlsafe(32)
                    await self._transaction_store.put(key=txn_id, value=txn, ttl=15 * 60)
                    resp = RedirectResponse(url=self._build_upstream_authorize_url(txn_id, txn.model_dump()), status_code=302)
                    self._set_consent_binding_cookie(request, resp, txn_id, txn.consent_token)
                    return resp
            except Exception as e:  # noqa: BLE001  — anything unexpected (a library that changed) falls back to the Allow page, never to no check
                print(f"board sign-in: Allow page kept: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
            return await super()._show_consent_page(request)

    p = _Provider(
        client_id=cid,
        client_secret=sec,
        base_url=_cfg.CFG["auth"]["base_url"],
        required_scopes=scopes,
        allowed_client_redirect_uris=_redirect_uris(),
    )
    from stackshot.web.auth.cimd import _harden_cimd   # retry claude.ai's metadata fetch and serve the last good document when it fails
    mgr = getattr(p, "_cimd_manager", None)
    f = getattr(mgr, "_fetcher", None)
    if f is not None:
        _harden_cimd(f, _cfg.state("cimd"))
    return p


def _who() -> str:
    """The signed-in identity, allow-listed; '' when auth is off.

    On a board behind a front door (`[behind_frontdoor] identity_secret_file`) the caller is the identity the front door signed for this request (the guard of web/door_guard.py verified it and
    put it on the request's scope), whatever the sign-in mode: a request the guard did not pass has none and is refused, and an identity the board's members do not list is refused. The identity is
    the member's key in the front door's file (an address, or a name), matched exactly; the answer is one of the person's sign-in addresses, which is what the rest of the board reads
    (the signed identity itself for a person the file gives no address)."""
    if _door.settings().identity:
        try:
            from fastmcp.server.dependencies import get_http_request
            who = _door.caller_of(get_http_request().scope)
        except RuntimeError:
            who = ""
        if not who:
            raise ToolError(_door.NO_IDENTITY)
        person = next((p for p in _members.members() if p.declared and p.name == who), None)      # the front door signs the member's key, exactly: never an alias or an address, which could be someone else's
        if not person:
            raise ToolError(f"Refused: {who} is not allowed on this board")
        return who if who in person.emails or not person.emails else person.emails[0]      # the address the rest of the board knows the person by (`signed_in` reads it)
    if _signin._auth_mode() == "off":
        return ""
    from fastmcp.server.dependencies import get_access_token
    tok = get_access_token()
    claims = getattr(tok, "claims", None) or {}
    email = claims.get("email", "")
    if not _members.person_of_email(email):
        raise ToolError(f"Refused: {email or 'unknown identity'} is not allowed on this board")
    why = _barred(claims)
    if why:
        raise ToolError(f"Refused: {email} is not let in. {_ident.REFUSALS[why]}")
    return email
