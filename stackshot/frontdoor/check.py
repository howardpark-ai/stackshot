"""check.py: a real tool call through the front door's parts, for a release's health check and for the steps of a switch.

    python -m stackshot.frontdoor.check --installed [--wait SECONDS]          what deploy.sh runs: every part whose unit this user has enabled or running
    python -m stackshot.frontdoor.check --door URL [--as MEMBER] [--board NAME]
    python -m stackshot.frontdoor.check --signin URL [--board NAME]
    python -m stackshot.frontdoor.check --splitter URL [--board NAME]

Run it with the project's `server` extra, from the checkout, with the instance's config (STACKSHOT_CONFIG):
    uv run --project <checkout> --locked --extra server python -m stackshot.frontdoor.check ...

A health route or an MCP initialize is not enough: the front door answers both with its board down. So each part is made to do its own work:

  door       a tool call on each board asked for, with the identity header naming a member of that board, as the splitter would send it
  sign-in    /healthz, then its token check: a request with no token is 401, and one with the board's machine token is what the settings say (200, or 403
             when accept_portal_token is off)
  splitter   /healthz (the board behind it); a request that carries the identity header and no token is 401 (a header the client sends is not believed); the
             board's token check path is 404; and a tool call with the board's machine token. With accept_portal_token off that token is refused with 403 by
             design, so no tool call can be made through the splitter: --installed says so and passes the rest, --splitter fails

The tool is `sessions`: a board's tool that only reads and needs no argument, and the board checks who is calling before it answers. The board's machine token
is read from the file the front door holds it in ([[frontdoor.backends]] token_file) and goes only into a request's Authorization header: it is never printed,
never an argument of a program, never part of a message, and it is not sent over plain http to another machine. Addresses are reached directly, never through a
proxy of the environment.

--board names one [[frontdoor.backends]] board. Left out: this machine's own board (a loopback url on [server] port), else the only one listed, and for --door every
board when none can be told to be it. The sign-in service and the splitter need one board for its machine token. By address, the check is refused without one (name it
with --board). --installed, which takes no --board, checks what needs no board's token, and the part's line says that the rest was not tried. With no board listed,
--installed asks the front door's /healthz alone and says so.

Exit 0: everything asked for passed. 1: something did not, and the last line says what. 2: the arguments or the config allow no check.
"""
from __future__ import annotations

import argparse
import asyncio
import http.client
import logging
import os
import subprocess
import sys
import time
from typing import Any, Callable
from urllib.parse import urlsplit

from stackshot.core import frontdoor_config as _fc
from stackshot.core import frontdoor_signin_config as _sc
from stackshot.core import frontdoor_splitter_config as _sp
from stackshot.frontdoor import config as _config

TOOL = "sessions"
STEP_TIMEOUT = 20.0          # one request, and the connection's handshake
CALL_TIMEOUT = 40.0          # a whole tool call
RETRY_SECONDS = 2.0
PROXY_VARS = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
PARTS = ("signin", "door", "splitter")
LABEL = {"signin": "sign-in service", "door": "front door", "splitter": "splitter"}
UNITS = {"signin": "stackshot-signin.service", "door": "stackshot-frontdoor.service", "splitter": "stackshot-splitter.service"}
INITIALIZE = (b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},'
              b'"clientInfo":{"name":"stackshot-front-door-check","version":"1"}}}')


UNTOLD = "none of the [[frontdoor.backends]] boards can be told to be this machine's own (to have it tried, give exactly one of them a loopback url on [server] port)"


class Failed(Exception):
    """A part did not do its work: the message is what a person reads."""


class Unusable(Exception):
    """The arguments or the config allow no check."""


# ---------------------------------------------------------------- one request, one tool call

def status(url: str, method: str = "GET", headers: dict[str, str] | None = None) -> int:
    """The HTTP status of one request to `url`, made directly (no proxy of the environment, no redirect followed). A POST sends an MCP initialize. Failed when nothing answers."""
    u = urlsplit(url)
    where = f"{method} {u.path or '/'}"
    try:
        make = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        c = make(u.hostname or "", u.port, timeout=STEP_TIMEOUT)
        try:
            h = {"Accept": "application/json, text/event-stream", **({"Content-Type": "application/json"} if method == "POST" else {}), **(headers or {})}
            c.request(method, u.path or "/", body=INITIALIZE if method == "POST" else None, headers=h)
            return c.getresponse().status
        finally:
            c.close()
    except Exception as e:      # noqa: BLE001  (only the class: a message of the HTTP library can quote a header, and a header here can hold the token)
        raise Failed(f"{where}: no answer ({e.__class__.__name__})") from None


async def _ignore(message: Any) -> None:
    """The log lines a server sends its client are not part of this check's output."""


def tool_call(url: str, headers: dict[str, str], board: str, secret: str = "") -> None:
    """One call of TOOL at the MCP endpoint `url` for `board`; Failed unless it is answered with a result. `secret` is cut out of whatever is quoted."""
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    async def go() -> Any:
        async with Client(StreamableHttpTransport(url, headers=headers), log_handler=_ignore, init_timeout=STEP_TIMEOUT) as c:
            return await c.call_tool(TOOL, {"board": board} if board else {}, raise_on_error=False)

    async def bounded() -> Any:
        return await asyncio.wait_for(go(), CALL_TIMEOUT)

    try:
        r = asyncio.run(bounded())
    except Exception as e:      # noqa: BLE001  (the class, and the HTTP status when there is one: never the library's own words, which can quote a header)
        code = getattr(getattr(e, "response", None), "status_code", None)
        what = f"HTTP {code}" if isinstance(code, int) else e.__class__.__name__
        raise Failed(f"the tool call {TOOL} on board {board} did not get through ({what})") from None
    text = " ".join(str(getattr(x, "text", "")) for x in (r.content or []))
    if r.is_error:
        said = text.replace(secret, "[token]") if secret else text
        raise Failed(f"the tool call {TOOL} on board {board} was answered with an error: {' '.join(said.split())[:200]}")
    if not text.strip():
        raise Failed(f"the tool call {TOOL} on board {board} was answered with nothing")


# ---------------------------------------------------------------- what the config says

class Setup:
    """What the config says about the parts; every file is read when a check needs it."""

    def __init__(self) -> None:
        self.door, _ = _fc.parse()
        self.signin, _ = _sc.parse()
        self.splitter, _ = _sp.parse()
        if not self.door.present:
            raise Unusable("the config has no [frontdoor] table, which names the boards, the identity header and the token files a check uses")

    def own(self) -> _fc.Backend | None:
        """The board meant when none is named: this machine's own, else the only one listed; None when that cannot be told."""
        found = _config.own_boards(self.door)
        if len(found) != 1:
            found = list(self.door.boards())
        return found[0] if len(found) == 1 else None

    def boards(self, name: str, every: bool) -> list[_fc.Backend]:
        """The boards a check calls: the one named, else `own`, else (only with `every`) all of them."""
        if name:
            found = [b for b in self.door.boards() if b.name == name]
            if not found:
                raise Unusable(f"no [[frontdoor.backends]] board is named {name!r} (the boards: {', '.join(b.name for b in self.door.boards()) or 'none'})")
            return found
        own = self.own()
        if own is not None:
            return [own]
        if every and self.door.boards():
            return list(self.door.boards())
        raise Unusable("none of the [[frontdoor.backends]] boards can be told to be this machine's own (a loopback url on [server] port): name one with --board")

    def member(self, board: str) -> str:
        """A member of `board` (of any board when "") by the front door's members file, whose key can be sent in a header."""
        if not self.door.members_file:
            raise Failed("[frontdoor] names no members_file, so no identity can be sent")
        try:
            members = _config.read_members(self.door.members_file)
        except _config.FileError as e:
            raise Failed(str(e)) from None
        fits = sorted(k for k, boards in members.items() if (not board or board in boards) and k == k.strip() and k.isascii() and k.isprintable())
        if not fits:
            raise Failed(f"the members file lists no member{f' of board {board}' if board else ''} whose key can be sent in a header")
        return next((k for k in fits if "@" in k), fits[0])

    def token(self, b: _fc.Backend) -> str:
        """The board's machine token, from the front door's token file for it."""
        if b.oauth:
            raise Failed(f"board {b.name} is reached with OAuth client credentials, so the front door holds no machine token to check with")
        try:
            return _config.credentials(b)["token"]
        except _config.FileError as e:
            raise Failed(str(e)) from None


def _base(url: str, carries_token: bool) -> str:
    """`url` without a trailing /mcp and slash; Unusable when it is no http(s) address, or would carry the token in clear text to another machine."""
    try:
        u = urlsplit(url.strip())
        ok = u.scheme in ("http", "https") and bool(u.hostname) and u.port != 0 and not u.username and not u.password and not u.query and not u.fragment
    except ValueError:
        ok = False
    if not ok:
        raise Unusable("an address is http(s)://host[:port], with no user name, query or fragment in it")
    if carries_token and u.scheme == "http" and (u.hostname or "").lower() not in ("127.0.0.1", "::1", "localhost"):
        raise Unusable(f"the board's machine token is not sent over plain http to {u.hostname}: use https, or the loopback address on that machine")
    base = url.strip().rstrip("/")
    return base[:-len("/mcp")] if base.endswith("/mcp") else base


# ---------------------------------------------------------------- the three parts

def check_door(s: Setup, base: str, boards: list[_fc.Backend], who: str = "") -> str:
    if not s.door.identity_header:
        raise Failed("[frontdoor] names no usable identity_header")
    for b in boards:
        tool_call(base + "/mcp", {s.door.identity_header: who or s.member(b.name)}, b.name)
    return f"tool call {TOOL} answered on board{'s' if len(boards) > 1 else ''} {', '.join(b.name for b in boards)}"


def check_signin(s: Setup, base: str, board: _fc.Backend | None, installed: bool) -> str:
    """`board`: whose machine token is asked about; None (--installed only) when that cannot be told."""
    got = status(base + "/healthz")
    if got != 200:
        raise Failed(f"/healthz answered {got}, not 200")
    if installed:
        from stackshot.core import behind_door
        if not behind_door.settings().verify_file:
            return "/healthz 200; its token check was not tried: this config's board has no [behind_frontdoor] verify_secret_file"
    got = status(base + "/verify")
    if got != 401:
        raise Failed(f"a token check that carries no token was answered {got}, not 401 (503: the board does not answer the check, or the verify secrets differ)")
    if board is None:
        return f"/healthz 200 and a request with no token refused; no board's machine token was tried: {UNTOLD}"
    token = s.token(board)
    want = 200 if s.signin.accept_portal_token else 403
    got = status(base + "/verify", headers={"Authorization": "Bearer " + token})
    if got != want:
        raise Failed(f"the token check of board {board.name}'s machine token was answered {got}, not {want}"
                     + (" (401: the board does not know the token in the front door's token file)" if got == 401 else ""))
    return f"the token check of board {board.name}'s machine token answered {got}" + ("" if want == 200 else " (refused as set: accept_portal_token is off)")


def check_splitter(s: Setup, base: str, board: _fc.Backend | None, installed: bool) -> str:
    """`board`: the board the tool call is made on; None (--installed only) when that cannot be told."""
    if not s.door.identity_header:
        raise Failed("[frontdoor] names no usable identity_header")
    got = status(base + "/healthz")
    if got != 200:
        raise Failed(f"/healthz answered {got}, not 200 (it is the board's, behind the splitter)")
    got = status(base + "/mcp", "POST", {s.door.identity_header: s.member(board.name if board else "")})
    if got != 401:
        raise Failed(f"a call that carries the identity header and no token was answered {got}, not 401")
    got = status(base + "/frontdoor/verify")
    if got != 404:
        raise Failed(f"the board's token check path /frontdoor/verify was answered {got}, not 404")
    if board is None:
        return f"routes as set; no tool call was tried: {UNTOLD}"
    if not s.signin.accept_portal_token:
        refusal = "no tool call can be made through the splitter with the board's machine token: [frontdoor_signin] accept_portal_token is off"
        if not installed:
            raise Failed(refusal)
        got = status(base + "/mcp", "POST", {"Authorization": "Bearer " + s.token(board)})
        if got != 403:
            raise Failed(f"a call with the board's machine token was answered {got}, not 403 (accept_portal_token is off)")
        return f"routes as set; {refusal} (the 403 came through)"
    token = s.token(board)
    tool_call(base + "/mcp", {"Authorization": "Bearer " + token}, board.name, secret=token)
    return f"tool call {TOOL} answered on board {board.name} through the sign-in check and the front door"


# ---------------------------------------------------------------- what is installed here

def _systemctl(*args: str) -> str:
    try:
        r = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        raise Failed(f"systemctl --user could not be run ({e.__class__.__name__}), so which parts run here is unknown") from None
    return (r.stdout or "").strip()


def installed_parts() -> list[str]:
    """The parts whose unit this user has turned on: enabled, or running now. A unit that is only installed is not checked: installing one turns nothing on. Nor is a
    failed unit that is not enabled: `disable --now` leaves the failed state behind, and its owner turned it off."""
    try:
        r = subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        raise Failed(f"systemctl --user could not be run ({e.__class__.__name__}), so which parts run here is unknown") from None
    if r.returncode != 0:
        raise Failed("systemctl --user cannot reach the user manager, so which parts run here is unknown")
    return [p for p in PARTS if _systemctl("is-enabled", UNITS[p]) in ("enabled", "enabled-runtime") or _systemctl("is-active", UNITS[p]) in ("active", "activating", "reloading")]


def installed_checks() -> list[tuple[str, Callable[[], str]]]:
    """(the part, its check) for each part turned on here."""
    parts = installed_parts()
    if not parts:
        return []
    try:
        s = Setup()
    except Unusable as e:
        raise Failed(f"{', '.join(UNITS[p] for p in parts)} turned on, but {e} (turn off what should not run: systemctl --user disable --now <unit>)") from None

    def part(p: str) -> Callable[[], str]:
        def run() -> str:
            if p == "door":
                base = "http://" + _sp.address(s.door.host, s.door.port)
                if not s.door.boards():
                    got = status(base + "/healthz")
                    if got != 200:
                        raise Failed(f"/healthz answered {got}, not 200")
                    return "/healthz 200; no tool call was tried: no [[frontdoor.backends]] board is listed"
                return check_door(s, base, s.boards("", every=True))
            if p == "signin":
                if not s.signin.present:
                    raise Failed("its unit is on, but the config has no [frontdoor_signin] table")
                return check_signin(s, "http://" + _sp.address(_sc.HOST, s.signin.port), s.own(), installed=True)
            why = _sp.blocking(s.splitter)
            if why:
                raise Failed(f"its unit is on, but the config allows no splitter: {'; '.join(why)} (turn it off: systemctl --user disable --now {UNITS['splitter']})")
            return check_splitter(s, "http://" + _sp.address(_sc.HOST, s.splitter.port), s.own(), installed=True)
        return run
    return [(p, part(p)) for p in parts]


def run_once(checks: list[tuple[str, Callable[[], str]]]) -> tuple[list[str], list[str]]:
    """(one line for each part that passed, one for each that failed): every part is tried."""
    good, bad = [], []
    for p, check in checks:
        try:
            good.append(f"{LABEL[p]}: {check()}")
        except (Failed, Unusable) as e:
            bad.append(f"{LABEL[p]}: {e}")
        except Exception as e:      # noqa: BLE001  (a fault of the check itself is a failed check, said by its class alone)
            bad.append(f"{LABEL[p]}: the check itself failed ({e.__class__.__name__})")
    return good, bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m stackshot.frontdoor.check", description="A real tool call through the front door's parts.")
    ap.add_argument("--installed", action="store_true", help="every part whose unit this user has enabled or running")
    ap.add_argument("--door", metavar="URL", help="the front door's address, e.g. http://127.0.0.1:8030")
    ap.add_argument("--signin", metavar="URL", help="the sign-in service's address, e.g. http://127.0.0.1:8031")
    ap.add_argument("--splitter", metavar="URL", help="the splitter's address, e.g. http://127.0.0.1:8020")
    ap.add_argument("--board", default="", metavar="NAME", help="the [[frontdoor.backends]] board to call (default: this machine's own)")
    ap.add_argument("--as", dest="who", default="", metavar="MEMBER", help="with --door: the identity to send (default: a member of the board)")
    ap.add_argument("--wait", type=float, default=0.0, metavar="SECONDS", help="try again until everything passes, for up to this long")
    a = ap.parse_args(argv)
    named = [p for p in PARTS if getattr(a, p)]
    if a.installed == bool(named):
        ap.error("give --installed, or one or more of --door, --signin and --splitter")
    if a.installed and (a.board or a.who):
        ap.error("--installed takes neither --board nor --as")
    if a.who and "door" not in named:
        ap.error("--as goes with --door")
    for k in PROXY_VARS:
        os.environ.pop(k, None)
    logging.disable(logging.CRITICAL)      # no library writes a request, with its headers, to this output
    say = lambda line: print(f"front door check: {line}", flush=True)      # noqa: E731
    try:
        if a.installed:
            checks = installed_checks()
            if not checks:
                say("nothing to check: no front door unit is enabled or running for this user")
                return 0
        else:
            s = Setup()
            bases = {p: _base(getattr(a, p), carries_token=p != "door") for p in named}      # every address is judged before a file is read
            one = {p: s.boards(a.board, every=False)[0] for p in named if p != "door"}
            doors = s.boards(a.board, every=True) if "door" in named else []
            make = {"door": lambda: check_door(s, bases["door"], doors, a.who), "signin": lambda: check_signin(s, bases["signin"], one["signin"], False),
                    "splitter": lambda: check_splitter(s, bases["splitter"], one["splitter"], False)}
            checks = [(p, make[p]) for p in named]
    except Unusable as e:
        say(f"not checked: {e}")
        return 2
    except Failed as e:
        say(f"FAILED: {e}")
        return 1
    deadline = time.monotonic() + max(0.0, a.wait)
    while True:
        good, bad = run_once(checks)
        if not bad or time.monotonic() >= deadline:
            break
        time.sleep(RETRY_SECONDS)
    for line in good:
        say(f"ok: {line}")
    if bad:
        for line in bad[:-1]:
            say(f"failed: {line}")
        say(f"FAILED: {'; '.join(bad)}")
        return 1
    say(f"passed ({', '.join(LABEL[p] for p, _ in checks)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
