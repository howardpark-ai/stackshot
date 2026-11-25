"""frontdoor_config.py: the `[frontdoor]` table, read and judged in one place.

The front door (`stackshot/frontdoor/`) is a separate program: one MCP endpoint over several boards and a brain, behind a reverse proxy that
tells it who is calling. Its settings live in the instance's config file, in the table `[frontdoor]` and one `[[frontdoor.backends]]` table per
board or brain. Nothing else reads them, and an instance that does not run the front door has no such table and is told nothing.

    settings, problems = parse(cfg)

`settings` is what the front door runs with (always a value: a key that is missing or wrong reads as its default, or as empty when it has none),
`problems` is one line for each thing a person should fix. The same lines are the front door's config notes (`notes`, which the start and
`doctor` print with every other note) and what it says when it refuses to start (`blocking`): a front door without an identity header, a members
file or a usable backend serves nobody, so it does not start; a backend entry that is wrong is left out and the others are served.

The values are text and numbers only: this module opens no file and no network connection (the files are read by `stackshot/frontdoor/config.py`),
and imports nothing but the config module, so the server and the clients that load the config do not import the front door.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from stackshot.core import config as _cfg

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8020
DEFAULT_HEALTH_CACHE_SECONDS = 5.0
DEFAULT_BACKEND_TIMEOUT_SECONDS = 10.0
DEFAULT_PREFACE = ("FRONT DOOR: one connection to the boards and the brain you are a member of, with this connector's own credential. "
                   "Tools that are not in your tool list are not available to this connection.")
KINDS = ("board", "brain")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")        # a backend's name: it is also the value of a call's `board` argument
HEADER = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*")        # an HTTP header name, as the proxy writes it
# The caller's own credentials and the hop-by-hop headers: the identity header can be none of them, or the front door would take a credential for a name.
NOT_AN_IDENTITY = frozenset({"authorization", "proxy-authorization", "cookie", "x-api-key", "host", "content-type", "content-length", "connection",
                             "transfer-encoding", "upgrade", "te", "keep-alive", "expect", "accept", "mcp-session-id"})
_LOOPBACK = ("127.0.0.1", "::1", "localhost")


@dataclass(frozen=True)
class Backend:
    name: str
    kind: str                     # "board" or "brain"
    url: str                      # the backend's MCP endpoint
    health_url: str               # the open route a health check reads (default: /healthz on the backend's own host)
    token_file: str = ""          # a static bearer, or ...
    client_id_file: str = ""      # ... OAuth client credentials (the three below), never both
    client_secret_file: str = ""
    scopes: str = ""              # the OAuth scopes, space separated ("" asks for none)

    @property
    def oauth(self) -> bool:
        return bool(self.client_id_file)


@dataclass(frozen=True)
class Settings:
    present: bool                 # the config has a [frontdoor] table
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    identity_header: str = ""     # lower-case; "" = none named (the front door does not start)
    identity_secret_file: str = ""
    members_file: str = ""
    health_cache_seconds: float = DEFAULT_HEALTH_CACHE_SECONDS
    backend_timeout_seconds: float = DEFAULT_BACKEND_TIMEOUT_SECONDS      # how long one call to a backend waits for it (its handshake, its tool list, its instructions)
    preface: str = DEFAULT_PREFACE
    backends: tuple[Backend, ...] = ()

    def boards(self) -> tuple[Backend, ...]:
        return tuple(b for b in self.backends if b.kind == "board")

    def brain(self) -> Backend | None:
        return next((b for b in self.backends if b.kind == "brain"), None)


def _table(cfg: dict[str, Any] | None) -> Any:
    return _cfg.get("frontdoor", cfg=cfg)


def _text(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def _http_url(v: Any) -> bool:
    if not isinstance(v, str) or not v.strip():
        return False
    try:
        u = urlsplit(v.strip())
        return u.scheme in ("http", "https") and bool(u.hostname) and not u.username and not u.password and u.port != 0
    except ValueError:
        return False


def _default_health(url: str) -> str:
    u = urlsplit(url)
    return f"{u.scheme}://{u.netloc}/healthz"


def _file_problems(label: str, path: str) -> list[str]:
    """The line for a secret file the mode of which lets group or others read it (the same check and words as a brain's secret_file)."""
    bad = _cfg.secret_file_mode_problem(os.path.expanduser(path))
    return [f"{label} {os.path.expanduser(path)} {bad}"] if bad else []


def _scopes(v: Any) -> tuple[str, bool]:
    """(the scopes as one space-separated string, whether the value was usable): a string, or a list of strings; anything else asks for none."""
    if v is None:
        return "", True
    if isinstance(v, str):
        return " ".join(v.split()), True
    if isinstance(v, list) and all(isinstance(x, str) and x.strip() and not any(c.isspace() for c in x) for x in v):
        return " ".join(x.strip() for x in v), True
    return "", False


def _backend(i: int, raw: Any, seen: set[str]) -> tuple[Backend | None, list[str]]:
    """One `[[frontdoor.backends]]` entry: the Backend, or None with the reason it is left out."""
    if not isinstance(raw, dict):
        return None, [f"[[frontdoor.backends]] entry {i} is not a table, so it is left out: write each backend as a [[frontdoor.backends]] table"]
    name = _text(raw.get("name"))
    label = f"[[frontdoor.backends]] {name!r}" if name else f"[[frontdoor.backends]] entry {i}"
    if not NAME.fullmatch(name):
        return None, [f"{label} has no usable name (letters, digits, '.', '_' and '-', starting with a letter or digit), so it is left out: it is the value of a call's board argument"]
    if name in seen:
        return None, [f"{label} repeats the name of an earlier entry, so it is left out: give each backend its own name"]
    kind = raw.get("kind", "board")
    if kind not in KINDS:
        return None, [f"{label} kind = {str(kind)[:40]!r} is neither \"board\" nor \"brain\", so it is left out"]
    url = raw.get("url")
    if not _http_url(url):
        return None, [f"{label} url is not an http(s) URL with a host (no user name or password in it), so it is left out: write url = \"http://127.0.0.1:8010/mcp\""]
    out: list[str] = []
    health = raw.get("health_url")
    if health is not None and not _http_url(health):
        out.append(f"{label} health_url is not an http(s) URL with a host, so {_default_health(url.strip())} is used")
        health = None
    token, oauth = raw.get("token_file"), raw.get("oauth")
    if token is not None and oauth is not None:
        return None, out + [f"{label} has both token_file and oauth, so it is left out: a backend gets one credential"]
    cid = csec = scopes = ""
    if token is not None:
        if not _text(token):
            return None, out + [f"{label} token_file is not a path, so it is left out: write token_file = \"<path of the file holding the bearer token>\""]
        token = _text(token)
        out += _file_problems(f"{label} token_file", token)
    elif oauth is not None:
        if not isinstance(oauth, dict) or not _text(oauth.get("client_id_file")) or not _text(oauth.get("client_secret_file")):
            return None, out + [f"{label} oauth needs client_id_file and client_secret_file (paths), so it is left out: "
                                f"write oauth = {{ client_id_file = \"...\", client_secret_file = \"...\", scopes = [\"read\", \"write\"] }}"]
        cid, csec = _text(oauth["client_id_file"]), _text(oauth["client_secret_file"])
        scopes, ok = _scopes(oauth.get("scopes"))
        if not ok:
            out.append(f"{label} oauth scopes is not a string or a list of words, so no scope is asked for")
        out += _file_problems(f"{label} oauth client_id_file", cid) + _file_problems(f"{label} oauth client_secret_file", csec)
        token = ""
    else:
        return None, out + [f"{label} has no token_file and no oauth, so it is left out: the front door calls a backend with its own credential"]
    return Backend(name, kind, url.strip(), _text(health) or _default_health(url.strip()), token or "", cid, csec, scopes), out


def parse(cfg: dict[str, Any] | None = None) -> tuple[Settings, list[str]]:
    """(the settings, the problems) of the config `cfg` (the running one when None). Never raises. No `[frontdoor]` table: (Settings(present=False), [])."""
    t = _table(cfg)
    if t is None:
        return Settings(present=False), []
    if not isinstance(t, dict):
        return Settings(present=True), ["[frontdoor] is not a table, so the front door has no settings and does not start: write [frontdoor] and one [[frontdoor.backends]] per board or brain"]
    out: list[str] = []
    host = t.get("listen_host", DEFAULT_HOST)
    if not _text(host):
        out.append(f"[frontdoor] listen_host = {str(host)[:60]!r} is not a host name or address, so {DEFAULT_HOST} is used")
        host = DEFAULT_HOST
    host = _text(host)
    if host not in _LOOPBACK:
        out.append(f"[frontdoor] listen_host = {host!r} is not the loopback address: a connection that did not come through the reverse proxy could send the identity header itself "
                   f"and be taken for any member; listen on {DEFAULT_HOST} and let the proxy connect to it")
    port = t.get("listen_port", DEFAULT_PORT)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        out.append(f"[frontdoor] listen_port = {str(port)[:60]!r} is not a whole number from 1 to 65535, so {DEFAULT_PORT} is used")
        port = DEFAULT_PORT
    ih = t.get("identity_header")
    ident_header = ""
    if ih is None:
        out.append("[frontdoor] has no identity_header, so the front door cannot tell who calls and does not start: "
                   "set identity_header = \"<the header the reverse proxy sets from its sign-in check>\"")
    elif not isinstance(ih, str) or not HEADER.fullmatch(ih.strip()) or ih.strip().lower() in NOT_AN_IDENTITY:
        out.append(f"[frontdoor] identity_header = {str(ih)[:60]!r} is not a header name the proxy can set for the caller's identity (letters, digits and '-'; "
                   f"never Authorization, Cookie, X-Api-Key or a transport header), so the front door does not start")
    else:
        ident_header = ih.strip().lower()
    isf = t.get("identity_secret_file")
    secret_file = ""
    if isf is None:
        out.append("[frontdoor] has no identity_secret_file, so the backends are sent no signed identity: set identity_secret_file = \"<path of the file holding the signing secret>\"")
    elif not _text(isf):
        out.append("[frontdoor] identity_secret_file is not a path, so the backends are sent no signed identity: set identity_secret_file = \"<path of the file holding the signing secret>\"")
    else:
        secret_file = _text(isf)
        out += _file_problems("[frontdoor] identity_secret_file", secret_file)
    mf = t.get("members_file")
    members_file = ""
    if not _text(mf):
        out.append("[frontdoor] has no members_file (a path), so nobody is a member of anything and the front door does not start: "
                   "set members_file = \"<a JSON file of member -> [boards]>\"")
    else:
        members_file = _text(mf)
    hc = t.get("health_cache_seconds", DEFAULT_HEALTH_CACHE_SECONDS)
    if isinstance(hc, bool) or not isinstance(hc, (int, float)) or not 0 <= hc <= 3600 or hc != hc:
        out.append(f"[frontdoor] health_cache_seconds = {str(hc)[:60]!r} is not a number from 0 to 3600, so {DEFAULT_HEALTH_CACHE_SECONDS:g} is used")
        hc = DEFAULT_HEALTH_CACHE_SECONDS
    bt = t.get("backend_timeout_seconds", DEFAULT_BACKEND_TIMEOUT_SECONDS)
    if isinstance(bt, bool) or not isinstance(bt, (int, float)) or not 0 < bt <= 300:
        out.append(f"[frontdoor] backend_timeout_seconds = {str(bt)[:60]!r} is not a number above 0 and up to 300, so {DEFAULT_BACKEND_TIMEOUT_SECONDS:g} is used")
        bt = DEFAULT_BACKEND_TIMEOUT_SECONDS
    pre = t.get("preface", DEFAULT_PREFACE)
    if not isinstance(pre, str) or not pre.strip():
        out.append("[frontdoor] preface is not text, so the built-in preface is used")
        pre = DEFAULT_PREFACE
    raw = t.get("backends")
    backends: list[Backend] = []
    if raw is None or raw == []:
        out.append("[frontdoor] lists no backends, so the front door has nothing to serve and does not start: add a [[frontdoor.backends]] table for each board or brain")
    elif not isinstance(raw, list):
        out.append("[frontdoor] backends is not a list of [[frontdoor.backends]] tables, so the front door has nothing to serve and does not start")
    else:
        seen: set[str] = set()
        for i, b in enumerate(raw, 1):
            be, why = _backend(i, b, seen)
            out += why
            if be is None:
                continue
            if be.kind == "brain" and any(x.kind == "brain" for x in backends):
                out.append(f"[[frontdoor.backends]] {be.name!r} is a second brain, so it is left out: a front door serves at most one brain (its tools carry no board argument to choose by)")
                continue
            seen.add(be.name)
            backends.append(be)
        if raw and not backends:
            out.append("[frontdoor] has no usable backend, so the front door does not start")
    return Settings(True, host, port, ident_header, secret_file, members_file, float(hc), float(bt), pre.strip(), tuple(backends)), out


def blocking(settings: Settings) -> list[str]:
    """Why the front door will not start with these settings ([] when it can): what it cannot serve without."""
    if not settings.present:
        return ["the config has no [frontdoor] table"]
    out = []
    if not settings.identity_header:
        out.append("no usable identity_header")
    if not settings.members_file:
        out.append("no members_file")
    if not settings.backends:
        out.append("no usable backend")
    return out


def notes(cfg: dict[str, Any] | None = None) -> list[str]:
    """The `[frontdoor]` lines of the config notes: [] when the config has no such table, else what `parse` found wrong."""
    return parse(cfg)[1]
