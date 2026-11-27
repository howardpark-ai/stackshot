"""signin.py: the sign-in service, the target of the reverse proxy's `forward_auth` in front of the front door.

    python -m stackshot.frontdoor.signin            serve, with the settings of the config file's [frontdoor_signin] table
    python -m stackshot.frontdoor.signin --check    read the settings, print the config notes and what would run, exit (0: the service could start, and where this config
                                                    also holds its board's verify_secret_file, the two hold the same value; `board_secret`)

For each request the proxy asks `GET /verify`, carrying the original request's headers. The service
  * takes the caller's `Authorization: Bearer <token>`, and asks the board who the token is for: `GET <board_verify_url>` (the board's `/frontdoor/verify`, web/routes/door_verify.py)
    with the token and the signed header `x-stackshot-verify` (`frontdoor_identity.sign` of the word `token-check` under the secret in `verify_secret_file`; the board checks it first);
  * on the board's 200, which says who the token is for and never that the person is a member, it takes the address the board names, in lower case, and itself finds the member of the
    front door's members file whose sign-in addresses hold it (`frontdoor_files.member_of_address`: a person may have several addresses); it answers 200 with the header
    `X-Verified-User: <the member's key>`, which the proxy copies to the front door's identity header (`copy_headers X-Verified-User>X-Forwarded-User`). An address no member holds is
    not refused here: it goes on as the identity (lower case), and the front door answers the person in words that they are not a member. One case is refused, 403 with no identity: an
    address no member holds that is written as a key of the file, because the front door matches keys exactly and would take the caller for that member. A member the file lists
    under two keys that are one once surrounding spaces are dropped, with different boards, is 503: the member records (what a board reads) take the first entry, the front door's
    own reader (`read_members`) the last. An address that is not ASCII is no address. The 200 also says what kind of token it was (`via`): a person's own sign-in (`google`) goes on as said; the board's own machine token (`portal`) is 403
    with no identity unless `accept_portal_token` is true, because that token belongs to one board, and as its person's identity at the front door it would reach every board that
    person is a member of;
  * on the board's 401 (no bearer, a token the board does not know, expired or revoked) it answers 401 with the board's own `WWW-Authenticate` text when the board's answer has one,
    so a connector's discovery of the sign-in keeps working: nothing of that text is held here;
  * on the board's 403 that says a registration refuses the sign-in (`{"error": "not_admitted", ...}`, core/invites.py) it answers 200 with an identity that is a member of nothing and
    carries the reason and the address (`frontdoor_identity.barred`), so the front door tells the person in words; it is not cached;
  * on anything else it answers 503 with no identity header: any other 403 of the board (a secret that differs, the board's clock), 404 (a board with no sign-in), 5xx, a redirect, a
    body that is no address or names no kind of token, no answer in `timeout_seconds` (a total deadline), a board that cannot be reached, a secret or members file that cannot be
    read, or any fault of this service. Never 200, and never 401: a 401 makes a connector throw its token away, which is wrong for an outage.

A 200 of the board that the service accepts, for an address a member holds, is kept for `cache_seconds` (a short time, 5 by default), under a hash of the token, at most MAX_ENTRIES of them. Nothing else is
kept: a refusal or a failure is never remembered, so a token the board refused is asked again at the next request, and neither is an answer for an address no member holds, so that the next request
of an address registered a moment later is asked about. An entry can only repeat what the board said of that very token a moment ago (a token revoked at Google keeps working here for at most
`cache_seconds`). The members file and the secret are read at each request, cached or not. The board is reached directly (a proxy of the environment is ignored), no redirect of it is followed, and
no cookie it sets is kept: one caller's check carries nothing of another's.

Nothing the caller sent is echoed: the answer's only header of its own is `X-Verified-User`, whatever the request carried under that name. A token, a secret or an address is never
written to the log or to an answer: a request is logged by the first 8 hex digits of a hash of the token and of the address. There is no access log and no websocket protocol (a
websocket upgrade is answered as the plain request it also is): both would write a request's query string.

It does not start when the verify secret is the same file as an identity secret the config names (links resolved) or holds the same value, nor when one of them cannot be read
(`secret_clash`): whoever holds the identity secret can sign any caller's identity to a board, so the token check has a secret of its own.

The service listens on 127.0.0.1 only. See docs/front-door.md, *The sign-in service*.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import http.cookiejar
import json
import logging
import os
import re
import sys
import time
from collections import OrderedDict
from typing import Any

from stackshot.core import frontdoor_files as _files, frontdoor_identity as _ident, frontdoor_signin_config as _sc
from stackshot.core.behind_door import VERIFY_HEADER, VERIFY_WHO

log = logging.getLogger("stackshot.frontdoor.signin")

PATH = "/verify"
HEALTH_PATH = "/healthz"
IDENTITY_HEADER = "X-Verified-User"      # the header of the answer the proxy copies to the front door's identity header (`copy_headers X-Verified-User>X-Forwarded-User`)
MAX_ENTRIES = 1024                       # the most 200s kept
MAX_BEARER = 4096                        # a longer token is no token
MAX_BODY = 64 * 1024                     # the most of the board's answer that is read
MAX_WWW = 2048                           # the longest WWW-Authenticate text passed on
MAX_CONNECTIONS = 64                     # the most checks at the board at once; a further one waits for a free connection, within its own deadline
KINDS = ("google", "portal")             # what the board's 200 may say the token was (`via`): a person's own sign-in, or the board's machine token
CLOCK = time.monotonic                   # the cache's clock (a test moves it)
_TOKEN = re.compile(r"[\x21-\x7e]+")      # visible ASCII, no space: what a bearer token is made of
_TEXT = re.compile(r"[\x20-\x7e]+")       # printable ASCII: what may be put in a header of the answer
_ADDRESS = re.compile(r"[\x21-\x7e]+@[\x21-\x7e]+")

OUTAGE = "the sign-in service cannot check this token right now: try again in a moment."
NOT_THEIRS = "refused: this address is not one of a member's sign-in addresses, so it is not passed on. Ask whoever runs the front door to add it to your emails."
MACHINE_REFUSED = ("refused: this is a board's own machine token, not a person's sign-in, so it is not passed on. Sign in as yourself; whoever runs the front door can accept "
                   "this token instead (accept_portal_token).")


def tag(value: str) -> str:
    """The short, one-way name a request is logged by: the first 8 hex digits of the SHA-256 of `value`."""
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:8]


def bearer_of(header: str | None) -> str:
    """The token of an `Authorization: Bearer <token>` header, read as the board reads it: one space after the word and nothing trimmed. "" when there is none, it is another scheme,
    or what follows that space is empty, too long or not visible ASCII (a second space or a tab included)."""
    kind, _, v = (header or "").partition(" ")
    if kind.lower() != "bearer" or len(v) > MAX_BEARER or not _TOKEN.fullmatch(v):
        return ""
    return v


def _plain(status: int, text: str, headers: dict[str, str] | None = None) -> Any:
    from starlette.responses import PlainTextResponse
    return PlainTextResponse(text, status_code=status, headers={"cache-control": "no-store", **(headers or {})})


def outage() -> Any:
    return _plain(503, OUTAGE)


def secret_clash(s: _sc.Settings) -> str:
    """Why the service may not start with its secrets, "" when it may: the verify secret has to be another file (links resolved) with another value than every identity secret the config
    names, and each of them has to be read to see that. The message names paths and never a value."""
    try:
        verify = _files.read_secret(s.verify_secret_file, "verify_secret_file")
        for path in s.identity_secret_files:
            identity = _files.read_secret(path, "identity_secret_file")
            if os.path.samefile(os.path.expanduser(path), os.path.expanduser(s.verify_secret_file)):
                return f"verify_secret_file and identity_secret_file {os.path.expanduser(path)} are the same file: give the token check a secret of its own"
            if identity == verify:
                return f"verify_secret_file and identity_secret_file {os.path.expanduser(path)} hold the same value: give the token check a secret of its own"
    except _files.FileError as e:
        return f"{e} (both secrets are read at the start, to see that they differ)"
    except OSError as e:
        return f"the secret files cannot be compared: {e.strerror or type(e).__name__}"
    return ""


def board_secret(s: _sc.Settings) -> tuple[bool, str]:
    """(whether `--check` passes, what it says) about the verify secret and the board's. Only a config that holds both settings can tell: its `[behind_frontdoor]`
    verify_secret_file, with a board_verify_url that is this config's own board (the loopback address, `[server] port`). Never a value of either."""
    from stackshot.core import behind_door
    from stackshot.frontdoor import config as _door
    board = behind_door.settings()
    if not board.verify:
        return True, "not compared with a board's: this config has no [behind_frontdoor] verify_secret_file"
    if not _door.is_own_board(s.board_verify_url):
        return True, "not compared with a board's: board_verify_url is not the board of this config's [server] port"
    if not board.verify_file:
        return False, "[behind_frontdoor] verify_secret_file is not a path, so the board answers no token check"
    try:
        mine = _files.read_secret(s.verify_secret_file, "verify_secret_file")
        theirs = _files.read_secret(board.verify_file, "[behind_frontdoor] verify_secret_file")
    except _files.FileError as e:
        return False, str(e)
    if not hmac.compare_digest(mine.encode(), theirs.encode()):
        return False, (f"[{_sc.TABLE}] verify_secret_file {os.path.expanduser(s.verify_secret_file)} and [behind_frontdoor] verify_secret_file "
                       f"{os.path.expanduser(board.verify_file)} do not match: the board would refuse every token check")
    return True, "the same value as the board's"


def refused(www: str) -> Any:
    from starlette.responses import JSONResponse
    return JSONResponse({"error": "invalid_token"}, status_code=401, headers={"cache-control": "no-store", **({"www-authenticate": www} if www else {})})


def granted(identity: str) -> Any:
    from starlette.responses import Response
    return Response(b"", status_code=200, headers={IDENTITY_HEADER.lower(): identity, "cache-control": "no-store"})


class Service:
    def __init__(self, settings: _sc.Settings, client: Any = None):
        import httpx2 as httpx      # installed with the `server` extra. (A check given up on at its deadline leaves its connection free here; with `httpx` it can stay taken.)
        self.s = settings
        self.cache: OrderedDict[str, tuple[float, str]] = OrderedDict()      # sha256 of the token -> (when it stops counting, the address the board named)
        # The board is reached directly (never through a proxy of the environment), a redirect is not followed (its status is the answer), no cookie is kept (the jar's policy allows
        # no domain), and what is read of an answer is bounded below.
        self.client = client or httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=httpx.Timeout(settings.timeout_seconds),
                                                  cookies=http.cookiejar.CookieJar(policy=http.cookiejar.DefaultCookiePolicy(allowed_domains=[])),
                                                  limits=httpx.Limits(max_connections=MAX_CONNECTIONS, max_keepalive_connections=8))

    async def aclose(self) -> None:
        await self.client.aclose()

    # ------------------------------------------------------------------ the cache of the board's 200s

    def _cached(self, key: str) -> str:
        """The address the board named for this token less than `cache_seconds` ago; "" when there is none (or the cache is off)."""
        have = self.cache.get(key)
        if have is None:
            return ""
        if have[0] <= CLOCK():
            del self.cache[key]
            return ""
        return have[1]

    def _keep(self, key: str, email: str) -> None:
        if self.s.cache_seconds <= 0:
            return
        now = CLOCK()
        self.cache.pop(key, None)
        while self.cache and next(iter(self.cache.values()))[0] <= now:      # entries are in the order they were made, so the oldest end first
            self.cache.popitem(last=False)
        self.cache[key] = (now + self.s.cache_seconds, email)
        while len(self.cache) > MAX_ENTRIES:
            self.cache.popitem(last=False)

    # ------------------------------------------------------------------ the board

    async def _get(self, headers: dict[str, str]) -> tuple[int, str, bytes]:
        """(status, the WWW-Authenticate text, at most MAX_BODY bytes of the body) of one GET of the board's check."""
        async with self.client.stream("GET", self.s.board_verify_url, headers=headers) as r:
            body = b""
            async for chunk in r.aiter_bytes():
                body += chunk
                if len(body) > MAX_BODY:
                    break
            return r.status_code, ", ".join(r.headers.get_list("www-authenticate")), body[:MAX_BODY]

    async def ask(self, secret: str, token: str) -> tuple[str, str]:
        """Ask the board who `token` is for ("" for a request that carries none): ("ok", the address in lower case), ("machine", the address: the token is the board's own machine
        token and `accept_portal_token` is not on), ("barred", the identity that says a registration refuses this sign-in: `frontdoor_identity.barred`), ("refused", the board's
        WWW-Authenticate text, "" if none) or ("down", why: a word for the log)."""
        headers = {"accept": "application/json", VERIFY_HEADER: _ident.sign(secret.encode("utf-8"), VERIFY_WHO)}
        if token:
            headers["authorization"] = "Bearer " + token
        try:
            status, www, body = await asyncio.wait_for(self._get(headers), self.s.timeout_seconds)      # one deadline for the connection, the request and the whole (bounded) answer
        except asyncio.TimeoutError:
            return "down", "no answer in time"
        except Exception as e:      # noqa: BLE001  (a board that cannot be reached, a connection that breaks, an answer that is no HTTP: all are the board not answering)
            return "down", f"{type(e).__name__}"
        if status == 401:
            return "refused", www if len(www) <= MAX_WWW and _TEXT.fullmatch(www) else ""
        if status not in (200, 403):
            return "down", f"the board answered {status}"
        try:
            d = json.loads(body.decode("utf-8"))
        except (ValueError, RecursionError):
            return "down", "the board's answer is not JSON" if status == 200 else f"the board answered {status}"
        email = d.get("email") if isinstance(d, dict) else None
        email = email.strip().lower() if isinstance(email, str) and email.isascii() else ""      # ASCII first: lower() turns some other characters into ASCII ones
        named = bool(_ADDRESS.fullmatch(email)) and len(email) <= 254
        if status == 403:      # a refusal of the header or the board's clock is plain text; a refused registration says so by name
            why = d.get("why") if isinstance(d, dict) and d.get("error") == "not_admitted" else None
            if named and isinstance(why, str) and why in _ident.REFUSALS:
                return "barred", _ident.barred(why, email)
            return "down", f"the board answered {status}"
        if not named:
            return "down", "the board's answer names no address"
        kind = d.get("via")
        if kind not in KINDS:
            return "down", "the board's answer names no kind of token"
        return ("machine" if kind == "portal" and not self.s.accept_portal_token else "ok"), email

    # ------------------------------------------------------------------ the route

    def identity_of(self, email: str) -> tuple[str, bool]:
        """(the identity the proxy is told, whether a member holds the address), by the front door's members file read now: the identity is the key of the member whose sign-in addresses hold the address, else the address itself (lower case).
        "" when no member holds the address and it is written as a key of the file: the front door matches keys exactly, so passing it on would make this caller that member.
        FileError when the file cannot be used, or when the front door would give that member other boards than the records do."""
        records = _files.read_member_records(self.s.members_file)
        listed = _files.read_members(self.s.members_file)      # the front door's own reader: every key as it looks it up, a case duplicate too
        member = _files.member_of_address(records, email)
        if not member:
            return ("" if email in listed else email), False
        if set(listed.get(member, ())) != set(records[member].boards):      # two keys a surrounding space apart: the records take the first entry, the front door the last
            raise _files.FileError(f"members_file {os.path.expanduser(self.s.members_file)} lists the member {tag(member)} more than once with different boards: list one key with all its boards")
        return member, True

    async def verify(self, request: Any) -> Any:
        try:
            return await self._verify(request)
        except Exception as e:      # noqa: BLE001  (a fault of this service is an outage: never an accepted request, never a 401)
            log.error("verify: %s", type(e).__name__)
            return outage()

    async def _verify(self, request: Any) -> Any:
        try:
            secret = _files.read_secret(self.s.verify_secret_file, "verify_secret_file")
        except _files.FileError as e:
            log.error("503: %s", e)
            return outage()
        token = bearer_of(request.headers.get("authorization"))
        key = hashlib.sha256(token.encode("utf-8")).hexdigest() if token else ""
        via = "cache"
        email = self._cached(key) if token else ""
        if not email:
            via = "board"
            verdict, what = await self.ask(secret, token)
            if not token and verdict in ("ok", "machine"):      # the board must refuse a request with no token (its answer is asked for only to take its WWW-Authenticate text): a board that does not is not trusted
                verdict, what = "down", "the board accepted a check that carries no token"
            if verdict == "refused":
                log.info("401 token %s: refused by the board%s", tag(token) if token else "-", " (no token)" if not token else "")
                return refused(what)
            if verdict == "machine":
                log.warning("403 token %s: the board's machine token, which accept_portal_token does not switch on", tag(token))
                return _plain(403, MACHINE_REFUSED)
            if verdict == "barred" and token:      # not a member's request: the front door says why, with the address. Never cached
                log.info("200 token %s: a registration refuses this sign-in, said by the front door", tag(token))
                return granted(what)
            if verdict != "ok":
                log.warning("503 token %s: %s", tag(token) if token else "-", "the board refused a check that carries no token as a sign-in" if verdict == "barred" else what)
                return outage()
            email = what
        try:
            identity, held = self.identity_of(email)
        except _files.FileError as e:
            log.error("503: %s", e)
            return outage()
        if token and via == "board" and held:      # an address no member holds may be registered at any moment, and its next request has to be asked about (core/invites.py)
            self._keep(key, email)
        if not identity:
            log.warning("403 token %s: address %s is no member's sign-in address and is written as a member's key", tag(token), tag(email))
            return _plain(403, NOT_THEIRS)
        if not _TEXT.fullmatch(identity) or identity != identity.strip():
            log.error("503 token %s: the identity for address %s is not printable ASCII, so it cannot be put in a header", tag(token), tag(email))
            return outage()
        log.info("200 token %s -> %s (%s)", tag(token), tag(identity), via)
        return granted(identity)

    async def health(self, request: Any) -> Any:
        from starlette.responses import JSONResponse
        try:
            _files.read_secret(self.s.verify_secret_file, "verify_secret_file")
            _files.read_member_records(self.s.members_file)
        except Exception as e:      # noqa: BLE001  (whatever a file holds or its reader raises, the answer is "degraded")
            log.error("healthz: %s", e if isinstance(e, _files.FileError) else type(e).__name__)
            return JSONResponse({"status": "degraded"}, status_code=503, headers={"cache-control": "no-store"})
        return JSONResponse({"status": "ok"}, headers={"cache-control": "no-store"})


def build(settings: _sc.Settings, client: Any = None) -> tuple[Any, Service]:
    """(the ASGI application, its Service): `GET /verify` for the proxy, `GET /healthz`."""
    from starlette.applications import Starlette
    from starlette.routing import Route
    svc = Service(settings, client)

    @contextlib.asynccontextmanager
    async def lifespan(app: Any):
        yield
        await svc.aclose()
    return Starlette(routes=[Route(PATH, svc.verify, methods=["GET"]), Route(HEALTH_PATH, svc.health, methods=["GET"])], lifespan=lifespan), svc


def options(settings: _sc.Settings) -> dict[str, Any]:
    """What uvicorn serves with. No access log and no websocket protocol: each writes a request's whole path, and the proxy's check carries the caller's own query string, which may
    hold a token or an address. The service logs its answers itself."""
    return {"host": _sc.HOST, "port": settings.port, "log_level": "info", "access_log": False, "ws": "none"}


def load(settings: _sc.Settings) -> Any:
    """The application, once everything serving needs is imported: Starlette, the client of the board, uvicorn and what uvicorn imports when it loads its configuration. Raises when
    one of them cannot be."""
    import uvicorn
    app, _svc = build(settings)
    uvicorn.Config(app, **options(settings)).load()
    return app


def serve(settings: _sc.Settings, app: Any) -> None:
    import uvicorn
    uvicorn.run(app, **options(settings))


def main(argv: list[str]) -> int:
    check = "--check" in argv
    if [a for a in argv if a != "--check"]:
        print("usage: python -m stackshot.frontdoor.signin [--check]", file=sys.stderr)
        return 2
    from stackshot.core import config as _cfg
    settings, problems = _sc.parse()
    for line in problems:
        print(f"note: {line}", file=sys.stderr)
    why = _sc.blocking(settings)
    if not why:      # the files are opened only when the settings name them all
        clash = secret_clash(settings)
        why = [clash] if clash else []
    if why:
        print("the sign-in service does not start: " + "; ".join(why), file=sys.stderr)
        return 2
    try:      # `--check` too: it says the service could start only when what serving needs is there
        app = load(settings)
    except Exception as e:      # noqa: BLE001  (a module that is not installed, which uvicorn may report in its own words)
        print(f"the sign-in service does not start: what serving needs cannot be loaded ({type(e).__name__}: {e}): run it with the project's `server` extra (uv run --extra server)", file=sys.stderr)
        return 2
    if check:
        matches, about = board_secret(settings)
        if not matches:
            print(f"the sign-in service cannot work as set: {about}", file=sys.stderr)
            return 2
        print(f"sign-in service: {_sc.HOST}:{settings.port}, asks {settings.board_verify_url}, header {IDENTITY_HEADER}, timeout {settings.timeout_seconds:g}s, "
              f"cache {settings.cache_seconds:g}s, machine token {'accepted' if settings.accept_portal_token else 'refused'}, verify secret {about} (config {_cfg.PATH})")
        return 0
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    serve(settings, app)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
