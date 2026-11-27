"""behind_door.py: a board that sits behind a front door: what it reads from its own config and what it does with it.

A front door (`stackshot/frontdoor/`, docs/front-door.md) calls a board with its own credential and adds the caller's identity as a signed header
(`frontdoor_identity.HEADER`). A board that is told so by its config does two things with what the door holds, and nothing when it is not told:

  * it checks the signed identity of every call to its MCP endpoint: `check(value)` says who the call is for, or why it is refused; a call with no identity, or one that
    does not verify under the shared secret inside the replay window, is refused (`web/door_guard.py` is the ASGI wrapper that asks, `web/auth/oauth.py: _who` asks again
    where a tool needs the caller);
  * it reads its members from the front door's members file (one source): `members(cfg)` is the identities the file lists for this board, read at each call,
    which `core/members.py` turns into the board's people.

The `[behind_frontdoor]` table of the config:

    identity_secret_file      the secret the front door signs with. Set: the board takes calls to /mcp through the front door only. Unset: no call is checked (the board as it was)
    identity_max_age_seconds  the replay window: how old a signed identity may be (1 to 3600, default 300)
    members_file              the front door's members file ({"alice": ["main", "side"]}, member -> the backends the member is on). Set: this file is the board's list of members
    board_name                the name this board has in the front door's [[frontdoor.backends]] and in that file (required with members_file)
    verify_secret_file        the secret the sign-in service signs a token check with. Set: the board answers `GET /frontdoor/verify` (web/routes/door_verify.py) for a request that carries that signed
                              header and a bearer token: who the board's own sign-in says the token is for. Unset: the route does not exist. Independent of the other keys (a board can offer the check before it
                              takes calls through the door only). Its value must differ from identity_secret_file's: a board whose two files hold the same value answers no check

Absent table: `settings()` is all off and every function here answers "not behind a front door". A key that is present but wrong is not read as absent: a board that was told to check
identities and cannot read its secret refuses every call, and a board that was told to read its members and cannot refuses everyone (never the other way: an unreadable file lets nobody in).
`notes` says what is wrong, as every other table's notes do.

The module reads files and the config and imports nothing of fastmcp or the web layer (the board server does not import `stackshot/frontdoor/`; the shared code is in core/).
"""
from __future__ import annotations

import hmac
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

from stackshot.core import config as _cfg
from stackshot.core import frontdoor_files as _files
from stackshot.core import frontdoor_identity as _ident
from stackshot.core.frontdoor_config import NAME

TABLE = "behind_frontdoor"
SCOPE_KEY = "stackshot.door_identity"        # the key of the request's ASGI scope the guard puts the verified identity on (a client cannot write a scope)
MAX_AGE_LIMIT = 3600.0
RACY_SECONDS = 2.0                           # a members file younger than this when it was read is read again next time, whatever its stamp says (a rewrite inside the clock's tick)

# What a refused call is told. HTTP 403 with one of these as plain text: never 401, which would make a front door whose backend credential is an OAuth client ask for a new token and retry.
NO_IDENTITY = "refused: this board takes calls through its front door only, and this call carries no signed identity."
BAD_IDENTITY = ("refused: the signed identity of this call is not accepted (it is altered, signed with another secret, older than this board's replay window, "
                "or dated ahead of its clock).")
NO_SECRET = "refused: this board cannot read the secret that checks a signed identity, so it accepts no call until that is fixed (the board's log says why)."
NO_VERIFY = "refused: this check takes a request from the sign-in service only, and this request carries no signed header."
BAD_VERIFY = "refused: the signed header of this request is not accepted (it is altered, signed with another secret, older than this board's replay window, or dated ahead of its clock)."
NO_VERIFY_SECRET = "refused: this board cannot read the secret that checks the sign-in service's header, so it answers no check until that is fixed (the board's log says why)."
SAME_SECRET = "refused: this board's secret for the sign-in service's header is the same as its identity secret, so it answers no check until the two differ (the board's log says why)."
VERIFY_HEADER = "x-stackshot-verify"   # the header the sign-in service signs a token check with (frontdoor_identity.sign of VERIFY_WHO under verify_secret_file)
VERIFY_WHO = "token-check"             # what the signature covers: the header proves the sender holds the secret, and carries no person


@dataclass(frozen=True)
class Settings:
    identity: bool = False          # check the signed identity of every call (the key identity_secret_file is present, whatever its value)
    secret_file: str = ""
    max_age: float = _ident.MAX_AGE
    members: bool = False           # read the members from the front door's file (the key members_file is present, whatever its value)
    members_file: str = ""
    board: str = ""
    verify: bool = False            # offer the token check to the sign-in service (the key verify_secret_file is present, whatever its value)
    verify_file: str = ""


@dataclass(frozen=True)
class Check:
    who: str = ""                   # the identity the call is for ("" when refused)
    refusal: str = ""               # the text the caller is told ("" when accepted)


def _text(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def parse(cfg: dict[str, Any] | None = None, files: bool = False) -> tuple[Settings, list[str]]:
    """(the settings, the problems) of the config `cfg` (the running one when None). Never raises. `files`: also stat the secret file for the problems (the notes do; a call never does)."""
    t = _cfg.get(TABLE, cfg=cfg)
    if t is None:
        return Settings(), []
    if not isinstance(t, dict):
        return Settings(identity=True, members=True, verify=True), [f"[{TABLE}] is not a table, so this board accepts no call, answers no token check and has no members until it is fixed: write [{TABLE}] with identity_secret_file, members_file and board_name"]
    out: list[str] = []
    identity, secret_file = "identity_secret_file" in t, _text(t.get("identity_secret_file"))
    if identity:
        if not secret_file:
            out.append(f"[{TABLE}] identity_secret_file is not a path, so this board accepts no call until it is fixed: set it to the file that holds the secret the front door signs with")
        elif files:
            bad = _cfg.secret_file_mode_problem(os.path.expanduser(secret_file))
            if bad:
                out.append(f"[{TABLE}] identity_secret_file {os.path.expanduser(secret_file)} {bad}")
    verify, verify_file = "verify_secret_file" in t, _text(t.get("verify_secret_file"))
    if verify:
        if not verify_file:
            out.append(f"[{TABLE}] verify_secret_file is not a path, so this board answers no token check until it is fixed: set it to the file that holds the secret the sign-in service signs a check with")
        elif files:
            bad = _cfg.secret_file_mode_problem(os.path.expanduser(verify_file))
            if bad:
                out.append(f"[{TABLE}] verify_secret_file {os.path.expanduser(verify_file)} {bad}")
    age = t.get("identity_max_age_seconds", _ident.MAX_AGE)
    if isinstance(age, bool) or not isinstance(age, (int, float)) or not 1 <= age <= MAX_AGE_LIMIT or age != age:
        out.append(f"[{TABLE}] identity_max_age_seconds = {str(age)[:60]!r} is not a number from 1 to {MAX_AGE_LIMIT:g}, so {_ident.MAX_AGE:g} is used")
        age = _ident.MAX_AGE
    members, members_file = "members_file" in t, _text(t.get("members_file"))
    board = _text(t.get("board_name"))
    if members:
        if not members_file:
            out.append(f"[{TABLE}] members_file is not a path, so this board has no members until it is fixed: set it to the front door's members file")
        if not NAME.fullmatch(board):
            out.append(f"[{TABLE}] board_name is {'missing' if not board else repr(board[:40])}, so this board has no members until it is fixed: set it to this board's name in the front door's "
                       f"[[frontdoor.backends]] (letters, digits, '.', '_' and '-')")
        if _cfg.get("members", cfg=cfg) is not None:
            out.append(f"[[members]] is not read while [{TABLE}] members_file is set: the front door's list is the board's one list of members (the older "
                       f"single-person keys of [instance] and [auth] allowed_emails name nobody to sign in either)")
    elif "board_name" in t:
        out.append(f"[{TABLE}] board_name is used only with members_file, which is not set")
    return Settings(identity, secret_file, float(age), members, members_file, board, verify, verify_file), out


def settings(cfg: dict[str, Any] | None = None) -> Settings:
    return parse(cfg)[0]


def notes(cfg: dict[str, Any] | None = None) -> list[str]:
    """The `[behind_frontdoor]` lines of the config notes: [] when the config has no such table."""
    return parse(cfg, files=True)[1]


_told: set[str] = set()


def _tell(msg: str) -> None:
    """One line on standard error for each distinct message (a members file that stays unreadable is said once, not at every call)."""
    if msg not in _told and len(_told) < 50:
        _told.add(msg)
        print(f"board behind a front door: {msg}", file=sys.stderr, flush=True)


# ------------------------------------------------------------------------------------------------ the signed identity

def check(value: str | None, cfg: dict[str, Any] | None = None, now: float | None = None) -> Check:
    """Who the signed identity `value` (the header's text) is for, or the refusal text. Call it only for a board that checks (`settings().identity`): the secret is read now, so a rotated one applies to the next call."""
    s = settings(cfg)
    if not value or not value.strip():
        return Check(refusal=NO_IDENTITY)
    try:
        secret = _files.read_secret(s.secret_file, "identity_secret_file")
    except _files.FileError as e:
        _tell(str(e))
        return Check(refusal=NO_SECRET)
    who = _ident.verify(secret.encode("utf-8"), value, now=now, max_age=s.max_age)
    return Check(who=who) if who else Check(refusal=BAD_IDENTITY)


def caller_of(scope: Any) -> str:
    """The identity the guard verified for the request whose ASGI scope this is; "" when it verified none."""
    v = scope.get(SCOPE_KEY) if hasattr(scope, "get") else None
    return v if isinstance(v, str) else ""


# ------------------------------------------------------------------------------------------------ the token check

def _holds(path: str, secret: str) -> bool:
    """Whether the identity secret file `path` holds `secret`. A file that cannot be used holds nothing: the identity check then refuses every call by itself."""
    try:
        other = _files.read_secret(path, "identity_secret_file")
    except _files.FileError:
        return False
    return hmac.compare_digest(other.encode("utf-8"), secret.encode("utf-8"))


def check_verify(value: str | None, cfg: dict[str, Any] | None = None, now: float | None = None) -> Check:
    """Whether `value` (the header's text) was signed by the sign-in service: `Check(who=VERIFY_WHO)` or the refusal text. Call it only for a board that offers the check (`settings().verify`):
    the secret is read now, so a rotated one applies to the next request. The same window as the signed identity's (`identity_max_age_seconds`). A board that also checks identities and whose two
    secret files hold the same value answers no check (the service holds the verify secret, and with the identity secret it could sign a call as anyone); only a correctly signed request is told that."""
    s = settings(cfg)
    if not value or not value.strip():
        return Check(refusal=NO_VERIFY)
    try:
        secret = _files.read_secret(s.verify_file, "verify_secret_file")
    except _files.FileError as e:
        _tell(str(e))
        return Check(refusal=NO_VERIFY_SECRET)
    who = _ident.verify(secret.encode("utf-8"), value, now=now, max_age=s.max_age)
    if who != VERIFY_WHO:
        return Check(refusal=BAD_VERIFY)
    if s.identity and _holds(s.secret_file, secret):
        _tell("verify_secret_file and identity_secret_file hold the same value, so this board answers no token check until they differ: give the sign-in service a secret of its own")
        return Check(refusal=SAME_SECRET)
    return Check(who=who)


# ------------------------------------------------------------------------------------------------ the members

_cache: dict[str, tuple[tuple[int, int, int, int], bool, dict[str, _files.Member]]] = {}


def _read_members(path: str) -> dict[str, _files.Member]:
    """The front door's members file, `{member: Member}` (`frontdoor_files.read_member_records`), read again only when its stamp changed (one stat per call), and always when it was written within RACY_SECONDS of being read.
    A file that cannot be read is nobody (said once in the log), never everybody."""
    p = os.path.expanduser(path)
    try:
        st = os.stat(p)
        sig = (st.st_mtime_ns, st.st_ctime_ns, st.st_size, st.st_ino)
    except OSError:
        st, sig = None, (0, 0, 0, 0)
    have = _cache.get(p)
    if have is not None and st is not None and have[0] == sig and have[1]:
        return have[2]
    try:
        said: list[str] = []
        data = _files.read_member_records(p, said)
        for line in said:
            _tell(line)
    except _files.FileError as e:
        _tell(str(e))
        _cache.pop(p, None)
        return {}
    if st is not None:
        _cache[p] = (sig, time.time() - st.st_mtime > RACY_SECONDS, data)
    return data


def people(cfg: dict[str, Any] | None = None) -> tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] | None:
    """The members the front door's members file lists for this board, in the file's order, each as (name, aliases, sign-in addresses); () when it lists none or cannot be read; None when this board does not
    read its members from a front door. The name is the member's key in the file, which is also the identity the front door signs for the member's calls."""
    s = settings(cfg)
    if not s.members:
        return None
    if not s.members_file or not NAME.fullmatch(s.board):
        return ()
    return tuple((m, rec.aliases, rec.emails) for m, rec in _read_members(s.members_file).items() if s.board in rec.boards)


def members_file_absent(cfg: dict[str, Any] | None = None) -> bool:
    """Whether this board reads its members from a front door's file (`[behind_frontdoor]` members_file and board_name, both usable) and nothing at all is at that
    path: a machine that only reads the board's text and never held the file. A file that is there and cannot be read or is not valid, a link that leads nowhere, a
    folder, or a path that cannot be looked at is not absent. For naming only (`members.naming`): who is a member and who may sign in never asks this."""
    s = settings(cfg)
    if not s.members or not s.members_file or not NAME.fullmatch(s.board):
        return False
    try:
        os.lstat(os.path.expanduser(s.members_file))
    except FileNotFoundError:
        return True
    except (OSError, ValueError):
        return False
    return False


def members(cfg: dict[str, Any] | None = None) -> tuple[str, ...] | None:
    """The identities the front door's members file lists for this board, in the file's order; () when it lists none or cannot be read; None when this board does not read its members from a front door."""
    p = people(cfg)
    return None if p is None else tuple(name for name, _a, _e in p)
