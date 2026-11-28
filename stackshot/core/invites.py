"""invites.py: registrations: a Google address an admin lets in to a board behind a front door, kept as an entry of the front door's members file.

An entry the board writes carries `invited`:

    "new@example.com": {"boards": ["main"], "emails": ["new@example.com"],
                        "invited": {"by": "alice", "at": "2027-01-02T10:00:00+09:00", "google_sub": ""}}

The front door, the sign-in service and the board read it as any other member, so removing it refuses the next request. What only an invited entry asks for is
checked by the board, which is the sign-in server: the Google sign-in has to report the address as verified, the first one records the Google account's id
(`sub`), and every later one has to be that account (`admit`; the words for a refusal are `frontdoor_identity.REFUSALS`). A members entry without `invited` is not touched by anything here, and a board with no
`[behind_frontdoor] members_file` is not affected at all.

The check holds for any invited entry of the members file, whether or not this board registers people. Registering is on only with `[invites]`:

    admins    the members (their names in the members file) who may register and remove an address. Missing or empty: off, and the board has no `invite` tool
    mcp_url   the address an app adds as its MCP server (default: [auth] base_url followed by /mcp)

and only on a board that can enforce the above: `[auth] mode = "google"` with an https base_url, and `[behind_frontdoor]` members_file, board_name and
verify_secret_file (the board the sign-in service asks). `notes` says what is missing. Calling `invite` through the front door also needs [behind_frontdoor]
identity_secret_file, which is not checked here: without it the board takes the call as the account of the door's own credential. See docs/front-door.md, *Inviting a person*.

Every change of the members file is made under a lock, as one rename, and never one that loses part of the file (a name written twice) or makes it too large to read."""
from __future__ import annotations

import contextlib
import datetime
import fcntl
import json
import os
import re
import stat
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from stackshot.core import behind_door as _door
from stackshot.core import config as _cfg
from stackshot.core import frontdoor_files as _files
from stackshot.core import readonly as _ro
from stackshot.core.frontdoor_config import NAME

TABLE = "invites"
KEY = "invited"                       # the key of a members entry the board wrote
PIN = "google_sub"                    # inside it: the id of the Google account that joined first ("" until one has)
REMOVED = "removed_from"              # inside it: the boards taken off an entry that kept its recorded account for others; registering one of them again is refused until that account is let go
PAGE_PATH = "/join"                  # the setup page the link names (web/routes/join.py)
LOCK_SECONDS = 2.0                    # the longest a change waits for another change of the file

# The redirect URIs of the apps the setup page names, added to [auth] allowed_client_redirect_uris while registering is on. Each is the one its app documents:
# exact hosts and paths. (A loopback entry written with no port takes any port, as RFC 8252 section 7.3 asks of a native app that picks one at run time.)
APP_REDIRECT_URIS = (
    # ChatGPT, the stable callback it uses with a server that names itself in its authorization answers (RFC 9207), which this sign-in does.
    # https://developers.openai.com/apps-sdk/build/auth ; https://chatgpt.com/oauth/client.json
    "https://chatgpt.com/connector_platform_oauth_redirect",
    # Claude Code. https://claude.ai/oauth/claude-code-client-metadata ; https://code.claude.com/docs/en/mcp
    "http://localhost/callback",
    "http://127.0.0.1/callback",
    # Cursor, the desktop app and the web. https://cursor.com/docs/mcp
    "http://localhost:8787/callback",
    "https://www.cursor.com/agents/mcp/oauth/callback",
)

# Why a Google sign-in is refused by a registration: the keys of frontdoor_identity.REFUSALS.
UNVERIFIED, OTHER_ACCOUNT, UNRECORDED, UNREADABLE = "unverified", "other_account", "unrecorded", "unreadable"

_ADDRESS = re.compile(r"[a-z0-9._%+'-]{1,64}@(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")
_URL = re.compile(r"https://[A-Za-z0-9.-]+(?::[0-9]{1,5})?(?:/[A-Za-z0-9._~/-]*)?")      # nothing a shell, JSON or a page reads as more than text


class InviteError(Exception):
    """A registration that cannot be made or removed: the message is what the admin is told."""


@dataclass(frozen=True)
class Settings:
    on: bool = False
    admins: tuple[str, ...] = ()
    link: str = ""                    # the setup page's address
    mcp_url: str = ""
    board: str = ""                   # this board's name in the members file
    members_file: str = ""


def _auth_mode(cfg: dict[str, Any] | None) -> str:
    return os.environ.get("STACKSHOT_AUTH") or os.environ.get("BOARD_MCP_AUTH") or str(_cfg.get("auth", "mode", cfg=cfg) or "")


def _admins(t: Any) -> tuple[str, ...]:
    raw = t.get("admins") if isinstance(t, dict) else None
    return tuple(dict.fromkeys(a.strip() for a in raw if isinstance(a, str) and a.strip())) if isinstance(raw, list) else ()


def wanted(cfg: dict[str, Any] | None = None) -> bool:
    """Whether the config names an admin: the board then has the `invite` tool (which says what else is missing while `settings` is off)."""
    return bool(_admins(_cfg.get(TABLE, cfg=cfg)))


def parse(cfg: dict[str, Any] | None = None) -> tuple[Settings, list[str]]:
    """(the settings, the problems) of the config `cfg` (the running one when None). Off, with the reason, unless everything registering needs is there. Never raises."""
    t = _cfg.get(TABLE, cfg=cfg)
    if t is None:
        return Settings(), []
    if not isinstance(t, dict):
        return Settings(), [f"[{TABLE}] is not a table, so nobody can be invited: write [{TABLE}] with admins"]
    admins = _admins(t)
    missing: list[str] = []
    if not admins:
        missing.append(f"[{TABLE}] admins (a list of member names)")
    if _auth_mode(cfg) != "google":
        missing.append('[auth] mode = "google"')
    base = str(_cfg.get("auth", "base_url", cfg=cfg) or "").rstrip("/")
    if not _URL.fullmatch(base):
        missing.append("[auth] base_url (an https address)")
    door = _door.settings(cfg)
    if not door.members_file:
        missing.append(f"[{_door.TABLE}] members_file")
    if not NAME.fullmatch(door.board):
        missing.append(f"[{_door.TABLE}] board_name")
    if not door.verify_file:
        missing.append(f"[{_door.TABLE}] verify_secret_file")
    url = t.get("mcp_url")
    mcp_url = f"{base}/mcp"
    if url is not None:
        if isinstance(url, str) and _URL.fullmatch(url.strip()):
            mcp_url = url.strip()
        else:
            missing.append(f"[{TABLE}] mcp_url as an https address (or no mcp_url)")
    if missing:
        return Settings(), [f"[{TABLE}] is off, so nobody can be invited and there is no setup page; it needs: {'; '.join(missing)}"]
    out: list[str] = []
    if _cfg.get("frontdoor_signin", "accept_portal_token", cfg=cfg) is True:
        out.append(f"[{TABLE}] is on and [frontdoor_signin] accept_portal_token is true: whoever holds the board's machine token reaches the front door as its identity, "
                   f"and invites as that member where the member is an admin")
    return Settings(True, admins, base + PAGE_PATH, mcp_url, door.board, door.members_file), out


def settings(cfg: dict[str, Any] | None = None) -> Settings:
    return parse(cfg)[0]


def notes(cfg: dict[str, Any] | None = None) -> list[str]:
    return parse(cfg)[1]


def address_of(text: Any) -> str:
    """`text` as the address a registration is kept by (lower case), or "" when it is no plain address."""
    a = str(text or "").strip()
    if not a.isascii() or len(a) > 254:
        return ""
    a = a.lower()
    return a if _ADDRESS.fullmatch(a) else ""


# ------------------------------------------------------------------------------------------------ the members file

class _Object(dict):
    """A JSON object that keeps every pair as written, a name written twice included."""

    def __init__(self, pairs: list[tuple[str, Any]]):
        super().__init__(pairs)
        self.pairs = pairs


def _document(path: str) -> _Object:
    """The members file as parsed. FileError when it cannot be used."""
    raw = _files._read_text(path, "members_file")
    try:
        d = json.loads(raw, object_pairs_hook=_Object)
    except (ValueError, RecursionError):
        raise _files.FileError(f"members_file {os.path.expanduser(path)} is not valid JSON") from None
    if not isinstance(d, _Object):
        raise _files.FileError(f"members_file {os.path.expanduser(path)} is not a JSON object of member -> [boards]")
    return d


def _twice(value: Any) -> bool:
    """Whether an object anywhere in `value` writes a name twice: writing the file again would drop one of the two."""
    if isinstance(value, _Object):
        return len(value) != len(value.pairs) or any(_twice(v) for v in value.values())
    return isinstance(value, list) and any(_twice(v) for v in value)


def _holds(key: str, value: Any, address: str, aliases: bool = False) -> bool:
    """Whether the entry `key: value` is written with `address` (lower case) as its key or one of its sign-in addresses (or, with `aliases`, one of its aliases)."""
    texts = [key]
    if isinstance(value, dict):
        for name in ("emails", "aliases") if aliases else ("emails",):
            if isinstance(value.get(name), list):
                texts.extend(x for x in value[name] if isinstance(x, str))
    return any(x.strip().lower() == address for x in texts)


def _invitations(doc: _Object, address: str) -> list[Any]:
    """The values of the invited entries that hold `address`, every one the file writes."""
    return [v for k, v in doc.pairs if isinstance(v, dict) and KEY in v and _holds(k, v, address)]


def _pin_of(value: Any) -> str | None:
    """The account id an invited entry has recorded, "" for none yet, None when the entry's `invited` cannot be read."""
    inv = value.get(KEY)
    if not isinstance(inv, dict) or not isinstance(inv.get(PIN, ""), str):
        return None
    return inv.get(PIN, "")


def _members_path() -> str | None:
    """The members file this board checks registrations against: None when it reads no members file, "" when it was told to and the key names no file."""
    door = _door.settings()
    return door.members_file if door.members else None


@contextlib.contextmanager
def _locked(real: str) -> Iterator[None]:
    fd = os.open(real + ".lock", os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0), 0o600)
    try:
        until = time.monotonic() + LOCK_SECONDS
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= until:
                    raise InviteError("the members file is being changed by someone else: try again in a moment") from None
                time.sleep(0.02)
        yield
    finally:
        os.close(fd)


def _write(real: str, doc: _Object) -> None:
    """`doc` in the place of the file `real`, as one rename, with the file's mode."""
    data = (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if len(data) > _files.MAX_BYTES:
        raise InviteError(f"the members file would grow past {_files.MAX_BYTES} bytes, which no reader takes, so it is not changed")
    mode = stat.S_IMODE(os.stat(real).st_mode)
    fd, part = tempfile.mkstemp(dir=os.path.dirname(real), prefix=".members-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            os.fchmod(f.fileno(), mode)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(part, real)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(part)


def _change(path: str, edit: Callable[[_Object], tuple[Any, bool]]) -> Any:
    """Run `edit` on the members file read under the lock: it returns (the answer, whether it changed the document). InviteError when the file cannot be read or written."""
    if _ro.is_read_only():
        raise InviteError(_ro.REFUSAL)
    real = os.path.realpath(os.path.expanduser(path))
    try:
        with _locked(real):
            doc = _document(real)
            if _twice(doc):
                raise InviteError(f"the members file {real} writes a name twice, so changing it here would lose one: fix the file first")
            answer, changed = edit(doc)
            if changed:
                _write(real, doc)
            return answer
    except _files.FileError as e:
        raise InviteError(str(e)) from None
    except UnicodeError:
        raise InviteError(f"the members file {real} holds text that cannot be written back, so it is not changed") from None
    except OSError as e:
        raise InviteError(f"the members file {real} cannot be changed: {e.strerror or type(e).__name__}") from None


# ------------------------------------------------------------------------------------------------ the sign-in

def admit(email: Any, sub: Any, verified: Any) -> str:
    """Why the registrations refuse this Google sign-in (the address, the account's id and Google's `email_verified` of the token): a key of
    `frontdoor_identity.REFUSALS`, or "" when none holds it back:
    the address has no invited entry, or the account is the one that entry recorded. The first verified sign-in of an invited address records its account."""
    path = _members_path()
    if path is None:
        return ""
    address = str(email or "").strip().lower()
    account = sub if isinstance(sub, str) else ""
    try:
        held = _invitations(_document(path), address)
    except _files.FileError as e:
        _door._tell(str(e))
        return UNREADABLE
    if not held:
        return ""
    if not (verified is True or (isinstance(verified, str) and verified.lower() == "true")):      # Google's token check says it as text, and "false" is not empty
        return UNVERIFIED
    pins = [_pin_of(v) for v in held]
    if not account or None in pins:
        return UNREADABLE
    if any(p and p != account for p in pins):
        return OTHER_ACCOUNT
    if all(pins):
        return ""

    def pin(doc: _Object) -> tuple[str, bool]:
        changed = False
        for value in _invitations(doc, address):
            have = _pin_of(value)
            if have is None:
                return UNREADABLE, False
            if have and have != account:
                return OTHER_ACCOUNT, False
            if not have:
                value[KEY][PIN] = account
                changed = True
        return "", changed
    try:
        return _change(path, pin)
    except InviteError as e:
        _door._tell(f"a first sign-in was not recorded: {e}")
        return UNRECORDED


def invited(path: str, address: str) -> bool:
    """Whether the members file `path` holds an invited entry for `address`. FileError when the file cannot be used."""
    return bool(_invitations(_document(path), address.strip().lower()))


def session_account(email: str, sub: str) -> str:
    """What a browser session keeps of the account: its id for an invited address, "" for every other."""
    path = _members_path()
    try:
        return sub if path and invited(path, email) else ""
    except _files.FileError:
        return sub


def session_holds(email: str, sub: str) -> bool:
    """Whether a browser session of `email`, begun by the Google account `sub`, still holds: an invited address needs the very account its entry has recorded now."""
    path = _members_path()
    if path is None:
        return True
    try:
        held = _invitations(_document(path), email.strip().lower())
    except _files.FileError as e:
        _door._tell(str(e))
        return False
    return not held or (bool(sub) and all(_pin_of(v) == sub for v in held))


# ------------------------------------------------------------------------------------------------ registering and removing

def register(address: str, by: str, s: Settings) -> tuple[bool, bool]:
    """Register `address` (as `address_of` gives it) on this board, by the admin `by`. (whether the file changed, whether an account has joined with it already)."""
    def add(doc: _Object) -> tuple[tuple[bool, bool], bool]:
        holders = [(k, v) for k, v in doc.pairs if _holds(k, v, address, aliases=True)]
        if not holders:
            doc[address] = _Object([])
            doc[address].update({"boards": [s.board], "emails": [address],
                                 KEY: {"by": by, "at": datetime.datetime.now(_cfg.tz()).isoformat(timespec="seconds"), PIN: ""}})
            return (True, False), True
        key, value = holders[0]
        if (len(holders) != 1 or key.strip().lower() != address or not isinstance(value, dict) or _pin_of(value) is None
                or not isinstance(value.get("boards"), list)):
            raise InviteError(f"{address} is already written in the members file, in an entry that was not registered this way (or not only this way): "
                              f"change that entry in the file")
        joined = bool(_pin_of(value))
        if s.board in value["boards"]:
            return (False, joined), False
        gone = value[KEY].get(REMOVED)
        if joined and isinstance(gone, list) and s.board in gone:
            raise InviteError(f"{address} was removed from board {s.board}, and the entry still holds the Google account of the earlier registration (it is on other boards): "
                              f"remove {address} from every board first (or set google_sub to \"\" in the file), then register it again so the new registration is the new person's own")
        if isinstance(gone, list):
            value[KEY][REMOVED] = [b for b in gone if b != s.board]
        value["boards"].append(s.board)
        return (True, joined), True
    return _change(s.members_file, add)


def _listed_on(value: Any, board: str) -> bool:
    boards = value.get("boards") if isinstance(value, dict) else value
    return isinstance(boards, list) and board in boards


def remove(address: str, s: Settings) -> tuple[tuple[str, ...], bool]:
    """Take this board from the registration of `address`; an entry left on no board is deleted. (the boards the registration is still on, whether an entry
    that was not registered this way still lists the address on this board)."""
    def take(doc: _Object) -> tuple[tuple[tuple[str, ...], bool], bool]:
        holders = [(k, v) for k, v in doc.pairs if _holds(k, v, address)]
        mine = [(k, v) for k, v in holders if isinstance(v, dict) and KEY in v]
        if not mine:
            raise InviteError(f"{address} is listed in the members file by hand, not registered this way: change that entry in the file" if holders
                              else f"{address} is not registered")
        if any(k.strip() in s.admins for k, _v in mine):
            raise InviteError(f"{address} is an admin ([{TABLE}] admins): take the name out of that list first")
        here = [(k, v) for k, v in mine if _listed_on(v, s.board)]
        if not here:
            raise InviteError(f"{address} is not registered on board {s.board}")
        left: list[str] = []
        for key, value in here:
            value["boards"] = [b for b in value["boards"] if b != s.board]
            if value["boards"]:
                left.extend(b for b in value["boards"] if isinstance(b, str))
                if isinstance(value.get(KEY), dict) and _pin_of(value):      # the recorded account stays for the other boards: say this board was taken off
                    value[KEY][REMOVED] = list(dict.fromkeys([*(value[KEY].get(REMOVED) or []), s.board]))
            else:
                del doc[key]
        listed = any(_listed_on(v, s.board) for _k, v in holders if not (isinstance(v, dict) and KEY in v))
        return (tuple(dict.fromkeys(left)), listed), True
    return _change(s.members_file, take)
