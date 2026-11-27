"""frontdoor_splitter_config.py: the `[frontdoor_splitter]` table, read and judged in one place.

The splitter is a Caddy reverse proxy on the board's machine that takes the port the board listened on before it moved behind the front door: a call to
the MCP path is checked by the sign-in service (`forward_auth`) and goes to the front door, everything else goes to the board. `install.sh units`
renders its unit and its Caddyfile (`units/stackshot-splitter.*.in`) from these settings, and `stackshot/frontdoor/splitter.py` holds the unit to
them at every start.

    settings, problems = parse(cfg)
    why = blocking(settings, cfg)       # why the splitter is neither rendered nor started ([] when it is)
    fill = values(settings, cfg)        # what the two templates are filled with; call it only when `why` is empty

The one thing these checks protect is the board's port: a splitter whose port is the one `[server] port` gives the board is never rendered and never
started, so a config that was put back after a switch cannot let the splitter take that port again, after a reboot either.

The values are text and numbers only: this module opens no file and no network connection, and imports nothing but the config modules.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from stackshot.core import config as _cfg
from stackshot.core import frontdoor_config as _door, frontdoor_signin_config as _signin

TABLE = "frontdoor_splitter"
DEFAULT_CADDY = "/usr/bin/caddy"
MCP_PATH = "/mcp"                               # the front door serves this path and no other, so the splitter sends this one to it
_HOST = re.compile(r"[A-Za-z0-9.:-]+")          # a listen host that can be written into a unit and a Caddyfile as it is
_PROGRAM = re.compile(r"/[A-Za-z0-9._+/-]+")    # a program's path that a unit can name as it is: absolute, no space, quote or %


@dataclass(frozen=True)
class Settings:
    present: bool                    # the config has a [frontdoor_splitter] table
    port: int = 0                    # 0: no usable listen_port
    caddy: str = DEFAULT_CADDY       # the Caddy the unit runs


def parse(cfg: dict[str, Any] | None = None) -> tuple[Settings, list[str]]:
    """(the settings, the problems) of the config `cfg` (the running one when None). Never raises. No `[frontdoor_splitter]` table: (Settings(present=False), [])."""
    t = _cfg.get(TABLE, cfg=cfg)
    if t is None:
        return Settings(present=False), []
    if not isinstance(t, dict):
        return Settings(present=True), [f"[{TABLE}] is not a table, so no splitter is installed: write [{TABLE}] with listen_port"]
    out: list[str] = []
    port = t.get("listen_port")
    if port is None:
        out.append(f"[{TABLE}] has no listen_port, so no splitter is installed: set it to the port the clients of the board connect to")
        port = 0
    elif isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        out.append(f"[{TABLE}] listen_port = {str(port)[:60]!r} is not a whole number from 1 to 65535, so no splitter is installed")
        port = 0
    if "listen_host" in t:
        out.append(f"[{TABLE}] listen_host is not a key: the splitter listens on the loopback address only, behind the tunnel or the proxy on this machine")
    caddy = t.get("caddy", DEFAULT_CADDY)
    if isinstance(caddy, str):
        caddy = os.path.expanduser(caddy.strip())
    if not isinstance(caddy, str) or not _PROGRAM.fullmatch(caddy):
        out.append(f"[{TABLE}] caddy = {str(t.get('caddy'))[:60]!r} is not the absolute path of a program (no spaces or quotes in it), so {DEFAULT_CADDY} is used")
        caddy = DEFAULT_CADDY
    return Settings(True, port, caddy), out


def _board(cfg: dict[str, Any] | None) -> tuple[str, int, str]:
    """(host, port, path) of `[server]`: port 0 when it is not a number."""
    host = str(_cfg.get("server", "host", cfg=cfg) or "127.0.0.1").strip()
    try:
        port = int(_cfg.get("server", "port", cfg=cfg))
    except (TypeError, ValueError):
        port = 0
    return host, port, str(_cfg.get("server", "path", cfg=cfg) or MCP_PATH)


def address(host: str, port: int) -> str:
    """host:port to connect to a service that listens on `host`: the loopback address for a wildcard one, brackets around an IPv6 address."""
    h = host.strip().strip("[]")
    h = {"0.0.0.0": "127.0.0.1", "": "127.0.0.1", "::": "::1", "*": "127.0.0.1"}.get(h, h)
    return f"[{h}]:{port}" if ":" in h else f"{h}:{port}"


def blocking(settings: Settings, cfg: dict[str, Any] | None = None) -> list[str]:
    """Why the splitter is neither rendered nor started with this config ([] when it is)."""
    if not settings.present:
        return [f"the config has no [{TABLE}] table"]
    out = []
    if not settings.port:
        out.append("no usable listen_port")
    door, _ = _door.parse(cfg)
    signin, _ = _signin.parse(cfg)
    if not door.present:
        out.append("no [frontdoor] table: the splitter sends the MCP path to the front door")
    elif not door.identity_header:
        out.append("[frontdoor] names no usable identity_header")
    if not signin.present:
        out.append(f"no [{_signin.TABLE}] table: the splitter asks the sign-in service about every call of the MCP path")
    host, port, path = _board(cfg)
    if path != MCP_PATH:
        out.append(f"[server] path is {path[:60]!r}: the front door serves {MCP_PATH}, so the board's MCP path has to be {MCP_PATH}")
    if not port:
        out.append("[server] port is not a number")
    for label, h in (("[server] host", host),) + ((("[frontdoor] listen_host", door.host),) if door.present else ()):
        if not _HOST.fullmatch(h.strip().strip("[]")):
            out.append(f"{label} = {h[:60]!r} is not a host name or address the splitter can connect to")
    if settings.port and settings.port == port:
        out.append(f"listen_port {settings.port} is the port [server] port gives the board: the splitter takes a port only after the board's settings moved the board to another one")
    elif settings.port and door.present and signin.present:
        taken = [port, door.port, signin.port, settings.port]
        if len(set(taken)) != len(taken):
            out.append(f"the board, the front door, the sign-in service and the splitter need four different ports (now {', '.join(map(str, taken))})")
    return out


def values(settings: Settings, cfg: dict[str, Any] | None = None) -> dict[str, str]:
    """What `units/stackshot-splitter.*.in` are filled with, by the name of the placeholder without its @ signs. Only for settings `blocking` has nothing against."""
    door, _ = _door.parse(cfg)
    signin, _ = _signin.parse(cfg)
    host, port, _path = _board(cfg)
    return {"LISTEN_PORT": str(settings.port), "BOARD_ADDR": address(host, port), "DOOR_ADDR": address(door.host, door.port),
            "SIGNIN_ADDR": address(_signin.HOST, signin.port), "IDENTITY_HEADER": door.identity_header, "CADDY": settings.caddy}


def notes(cfg: dict[str, Any] | None = None) -> list[str]:
    """The `[frontdoor_splitter]` lines of the config notes: [] when the config has no such table, else what `parse` found wrong and why no splitter would run."""
    settings, out = parse(cfg)
    if not settings.present:
        return []
    why = [w for w in blocking(settings, cfg) if w != "no usable listen_port"]
    return out + ([f"[{TABLE}] the splitter is neither installed nor started with this config: {'; '.join(why)}"] if why else [])
