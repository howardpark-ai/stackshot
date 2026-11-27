"""boardtoken.py: copy the board's machine token into the front door's token file for that board.

    python -m stackshot.frontdoor.boardtoken [--board NAME]            write the file when it does not hold the board's token
    python -m stackshot.frontdoor.boardtoken [--board NAME] --check    say whether it does, and write nothing
    stackshot frontdoor-token ...                                      the same

The front door reaches a board with a token of its own (`[[frontdoor.backends]] token_file`). For a board on this machine that is the board's machine token,
`STACKSHOT_PORTAL_TOKEN` (or the older `BOARD_MCP_PORTAL_TOKEN`) of `<paths.secrets>/oauth.env`, so after a new token there the copy has to be made again.

The order of a rotation: put the new token into oauth.env, restart the board (it reads the file at its start only), run this command at once (the front door
reads its token file at each request, so it needs no restart; between the restart and this command its calls to that board are refused), then try a call:
`python -m stackshot.frontdoor.check`.

The token is read from oauth.env as the board reads it, and written to a new file beside the target, readable by its owner only, which then takes the target's
place in one step: a reader sees the old file or the new one, never a part. The value is never printed, never an argument of a program and never in a message.

--board names the [[frontdoor.backends]] board. Left out, it is the one whose url is this machine's own board (a loopback address on [server] port). A named board
whose url is not such an address is refused before anything is read or written: the token of this oauth.env is this machine's board's, and no other's.

Exit 0: the file holds the board's token (written now, or already). 1: --check found that it does not. 2: nothing was done, and the line says why.
"""
from __future__ import annotations

import argparse
import hmac
import os
import sys
import tempfile
from typing import Any

from stackshot.core import config as _cfg
from stackshot.core import frontdoor_config as _fc
from stackshot.frontdoor import config as _config

NAMES = ("STACKSHOT_PORTAL_TOKEN", "BOARD_MCP_PORTAL_TOKEN")      # the board prefers the first (web/auth/oauth.py)
MIN_LEN = 32                                                      # a shorter machine token is one the board does not accept
OTHER_FILES = (("frontdoor", "identity_secret_file"), ("frontdoor", "members_file"), ("behind_frontdoor", "identity_secret_file"), ("behind_frontdoor", "members_file"),
               ("behind_frontdoor", "verify_secret_file"), ("frontdoor_signin", "identity_secret_file"), ("frontdoor_signin", "members_file"), ("frontdoor_signin", "verify_secret_file"))


class Refused(Exception):
    """Nothing is done: the message says why, and names no value."""


def board_token(env_file: str) -> str:
    """The board's machine token as its oauth.env names it, read as the board reads it: the first line of a name counts, quotes around a value are taken off."""
    try:
        with open(env_file, encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeError) as e:
        raise Refused(f"{env_file} cannot be read ({getattr(e, 'strerror', None) or e.__class__.__name__})") from None
    found: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            found.setdefault(k.strip(), v.strip().strip('"'))
    token = (found.get(NAMES[0]) or found.get(NAMES[1]) or "").strip()
    if not token:
        raise Refused(f"{env_file} names no machine token ({' or '.join(NAMES)})")
    if len(token) < MIN_LEN or not token.isprintable() or any(c.isspace() for c in token):
        raise Refused(f"the machine token in {env_file} cannot be used: the board takes one of {MIN_LEN} characters or more, with no space in it")
    return token


def backend(settings: _fc.Settings, name: str) -> _fc.Backend:
    """The board whose token file is meant: one of this machine's own, since the token copied is the one of this machine's oauth.env."""
    boards = settings.boards()
    if name:
        found = [b for b in boards if b.name == name]
        if not found:
            raise Refused(f"no [[frontdoor.backends]] board is named {name!r} (the boards: {', '.join(b.name for b in boards) or 'none'})")
    else:
        found = _config.own_boards(settings)
        if len(found) != 1:
            raise Refused(("no" if not found else "more than one") + " [[frontdoor.backends]] board is this machine's own (a loopback url on [server] port): name one with --board")
    b = found[0]
    if b.oauth:
        raise Refused(f"board {b.name} is reached with OAuth client credentials, so the front door has no token file for it")
    if not _config.is_own_board(b.url):
        raise Refused(f"board {b.name} is not this machine's own board (its url is no loopback address on [server] port), and the token in oauth.env is this machine's board's: "
                      f"if {b.name} is this machine's board, give its entry such a url")
    return b


def _same_file(a: str, b: str) -> bool:
    if os.path.realpath(a) == os.path.realpath(b):
        return True
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def target_of(settings: _fc.Settings, b: _fc.Backend, env_file: str, cfg: dict[str, Any] | None = None) -> str:
    """The token file of `b`, refused when the config names that file for something else too: writing the token there would destroy it."""
    target = os.path.expanduser(b.token_file)
    others = [("the board's oauth.env", env_file)]
    others += [(f"[{t}] {k}", v) for t, k in OTHER_FILES for v in [_cfg.get(t, k, cfg=cfg)] if isinstance(v, str) and v.strip()]
    others += [(f"backend {o.name}'s {k}", v) for o in settings.backends for k, v in (("token_file", o.token_file), ("client_id_file", o.client_id_file),
                                                                                    ("client_secret_file", o.client_secret_file)) if v and o.name != b.name]
    for what, path in others:
        if _same_file(target, os.path.expanduser(path.strip())):
            raise Refused(f"backend {b.name}'s token_file {target} is also {what}: give the token a file of its own")
    return target


def holds(path: str, token: str) -> tuple[bool, str]:
    """(whether the front door reads `token` from the file at `path`, why it does not)."""
    try:
        have = _config.read_secret(path, "token_file")
    except _config.FileError as e:
        return False, str(e)
    if hmac.compare_digest(have.encode(), token.encode()):
        return True, ""
    return False, f"token_file {path} does not hold the board's machine token"


def write(path: str, token: str) -> None:
    """Put `token` at `path` in one step, readable by the owner only. A link at `path` stays a link: the file it leads to is replaced."""
    real = os.path.realpath(path)
    folder = os.path.dirname(real)
    try:
        os.makedirs(folder, mode=0o700, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".token-", dir=folder)
        try:
            try:
                os.fchmod(fd, 0o600)
                data = (token + "\n").encode()
                while data:
                    data = data[os.write(fd, data):]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp, real)
        finally:
            if os.path.lexists(tmp):
                os.unlink(tmp)
    except OSError as e:
        raise Refused(f"{path} cannot be written: {e.strerror or e.__class__.__name__}") from None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m stackshot.frontdoor.boardtoken", description="Copy the board's machine token into the front door's token file for that board.")
    ap.add_argument("--board", default="", metavar="NAME", help="the [[frontdoor.backends]] board (default: this machine's own)")
    ap.add_argument("--check", action="store_true", help="say whether the file holds the board's token, and write nothing")
    a = ap.parse_args(argv)
    try:
        settings, _ = _fc.parse()
        if not settings.present:
            raise Refused(f"the config has no [frontdoor] table (config {_cfg.PATH})")
        b = backend(settings, a.board)
        env_file = str(_cfg.secrets("oauth.env"))
        target = target_of(settings, b, env_file)
        token = board_token(env_file)
        same, why = holds(target, token)
        if a.check:
            if same:
                print(f"board {b.name}: {target} holds the board's machine token")
                return 0
            print(f"board {b.name}: {why}")
            return 1
        if same:
            print(f"board {b.name}: unchanged, {target} already holds the board's machine token")
            return 0
        write(target, token)
        same, why = holds(target, token)
        if not same:
            raise Refused(f"written, and read back wrong: {why}")
    except Refused as e:
        print(f"nothing copied: {e}", file=sys.stderr)
        return 2
    print(f"board {b.name}: wrote the board's machine token of {env_file} to {target} (mode 600)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
