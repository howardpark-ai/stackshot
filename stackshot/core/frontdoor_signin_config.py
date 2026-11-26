"""frontdoor_signin_config.py: the `[frontdoor_signin]` table, read and judged in one place.

The sign-in service (`stackshot/frontdoor/signin.py`) is a separate program: the target of the reverse proxy's `forward_auth`. It asks a board who a connector's bearer token is
for (the board's `GET /frontdoor/verify`), maps the address the board names to a member of the front door's members file and answers the proxy with the identity the front door
trusts. Its settings live in the instance's config file, in the table `[frontdoor_signin]`. Nothing else reads them, and an instance that does not run the service has no such
table and is told nothing.

    settings, problems = parse(cfg)

`settings` is what the service runs with (always a value: a key that is missing or wrong reads as its default, or as empty when it has none), `problems` is one line for each
thing a person should fix. The same lines are the config notes (`notes`, which the start and `doctor` print with every other note) and, for what the service cannot start
without, what it says when it refuses to start (`blocking`).

The values are text and numbers only: this module opens no file and no network connection (the files are read by the service), and imports nothing but the config module.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from stackshot.core import config as _cfg

TABLE = "frontdoor_signin"
DEFAULT_PORT = 8021
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_CACHE_SECONDS = 5.0
MAX_TIMEOUT_SECONDS = 60.0
MAX_CACHE_SECONDS = 60.0
HOST = "127.0.0.1"             # the service listens here and nowhere else: the reverse proxy on this machine is its only caller
_LOOPBACK = ("127.0.0.1", "::1", "localhost")


@dataclass(frozen=True)
class Settings:
    present: bool                                   # the config has a [frontdoor_signin] table
    port: int = DEFAULT_PORT
    board_verify_url: str = ""                      # the board's GET /frontdoor/verify
    verify_secret_file: str = ""                    # the secret the board's `verify_secret_file` holds too
    members_file: str = ""                          # the front door's members file (else the [frontdoor] one)
    identity_secret_files: tuple[str, ...] = ()     # every identity secret file the config names (its own, [frontdoor]'s, [behind_frontdoor]'s): the verify secret may be none of them
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    cache_seconds: float = DEFAULT_CACHE_SECONDS    # 0: no cache
    accept_portal_token: bool = False               # true: the board's own machine token is passed on as its person's sign-in (off: refused)


def _text(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def _http_url(v: Any) -> bool:
    if not isinstance(v, str) or not v.strip():
        return False
    try:
        u = urlsplit(v.strip())
        return u.scheme in ("http", "https") and bool(u.hostname) and not u.username and not u.password and u.port != 0 and not u.fragment
    except ValueError:
        return False


def _number(t: dict[str, Any], key: str, default: float, low_open: bool, high: float, out: list[str]) -> float:
    v = t.get(key, default)
    ok = not isinstance(v, bool) and isinstance(v, (int, float)) and v == v and (v > 0 if low_open else v >= 0) and v <= high
    if not ok:
        out.append(f"[{TABLE}] {key} = {str(v)[:60]!r} is not a number {'above 0' if low_open else 'from 0'} and up to {high:g}, so {default:g} is used")
        return default
    return float(v)


def parse(cfg: dict[str, Any] | None = None) -> tuple[Settings, list[str]]:
    """(the settings, the problems) of the config `cfg` (the running one when None). Never raises. No `[frontdoor_signin]` table: (Settings(present=False), [])."""
    t = _cfg.get(TABLE, cfg=cfg)
    if t is None:
        return Settings(present=False), []
    if not isinstance(t, dict):
        return Settings(present=True), [f"[{TABLE}] is not a table, so the sign-in service has no settings and does not start: write [{TABLE}] with board_verify_url, verify_secret_file and members_file"]
    out: list[str] = []
    port = t.get("listen_port", DEFAULT_PORT)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        out.append(f"[{TABLE}] listen_port = {str(port)[:60]!r} is not a whole number from 1 to 65535, so {DEFAULT_PORT} is used")
        port = DEFAULT_PORT
    if "listen_host" in t:
        out.append(f"[{TABLE}] listen_host is not a key: the sign-in service listens on {HOST} only, because the reverse proxy on this machine is its one caller")
    url = t.get("board_verify_url")
    verify_url = ""
    if url is None:
        out.append(f"[{TABLE}] has no board_verify_url, so the sign-in service cannot ask a board who a token is for and does not start: "
                   f"write board_verify_url = \"http://127.0.0.1:8010/frontdoor/verify\"")
    elif not _http_url(url):
        out.append(f"[{TABLE}] board_verify_url is not an http(s) URL with a host (no user name, password or fragment in it), so the sign-in service does not start")
    else:
        verify_url = url.strip()
        u = urlsplit(verify_url)
        if (u.hostname or "").lower() not in _LOOPBACK:
            out.append(f"[{TABLE}] board_verify_url names {u.hostname!r}, which is not the loopback address: the caller's bearer token goes there with every check"
                       f"{'' if u.scheme == 'https' else ' in clear text'}; point it at the board on this machine")
    sf = t.get("verify_secret_file")
    secret_file = ""
    if not _text(sf):
        out.append(f"[{TABLE}] has no verify_secret_file (a path), so the check the board is asked for cannot be signed and the service does not start: "
                   f"set it to the file the board's [behind_frontdoor] verify_secret_file names")
    else:
        secret_file = _text(sf)
        bad = _cfg.secret_file_mode_problem(os.path.expanduser(secret_file))
        if bad:
            out.append(f"[{TABLE}] verify_secret_file {os.path.expanduser(secret_file)} {bad}")
    mf = t.get("members_file")
    members_file = _text(mf)
    if mf is not None and not members_file:
        out.append(f"[{TABLE}] members_file is not a path, so the [frontdoor] members_file is used")
    if not members_file:
        members_file = _text(_cfg.get("frontdoor", "members_file", cfg=cfg))
    if not members_file:
        out.append(f"[{TABLE}] has no members_file and [frontdoor] has none either, so the service cannot map an address to a member and does not start: "
                   f"set members_file = \"<the front door's JSON file of members>\"")
    own = t.get("identity_secret_file")
    if own is not None and not _text(own):
        out.append(f"[{TABLE}] identity_secret_file is not a path, so it is not read")
    named = (_text(own), _text(_cfg.get("frontdoor", "identity_secret_file", cfg=cfg)), _text(_cfg.get("behind_frontdoor", "identity_secret_file", cfg=cfg)))
    identity_files = tuple(dict.fromkeys(x for x in named if x))
    if not identity_files:
        out.append(f"[{TABLE}] has no identity_secret_file and neither [frontdoor] nor [behind_frontdoor] names one, so the service cannot see that its verify secret is not the identity secret and does not start: "
                   f"set identity_secret_file = \"<the file the front door's identity_secret_file names>\"")
    timeout = _number(t, "timeout_seconds", DEFAULT_TIMEOUT_SECONDS, True, MAX_TIMEOUT_SECONDS, out)
    cache = _number(t, "cache_seconds", DEFAULT_CACHE_SECONDS, False, MAX_CACHE_SECONDS, out)
    portal = t.get("accept_portal_token", False)
    if not isinstance(portal, bool):
        out.append(f"[{TABLE}] accept_portal_token = {str(portal)[:60]!r} is not true or false, so the board's machine token is not accepted")
        portal = False
    return Settings(True, port, verify_url, secret_file, members_file, identity_files, timeout, cache, portal), out


def blocking(settings: Settings) -> list[str]:
    """Why the sign-in service will not start with these settings ([] when it can): what it cannot serve without."""
    if not settings.present:
        return [f"the config has no [{TABLE}] table"]
    out = []
    if not settings.board_verify_url:
        out.append("no usable board_verify_url")
    if not settings.verify_secret_file:
        out.append("no verify_secret_file")
    if not settings.members_file:
        out.append("no members_file")
    if not settings.identity_secret_files:
        out.append("no identity_secret_file")
    return out


def notes(cfg: dict[str, Any] | None = None) -> list[str]:
    """The `[frontdoor_signin]` lines of the config notes: [] when the config has no such table, else what `parse` found wrong."""
    return parse(cfg)[1]
