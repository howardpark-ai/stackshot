"""splitter.py: the check systemd runs before every start of the splitter (stackshot-splitter.service, ExecStartPre).

    python3 -m stackshot.frontdoor.splitter check --listen N --board A --door B --signin C --header H --caddy PATH

The unit and its Caddyfile were rendered from the config of the day `./install.sh units` ran. This command passes (exit 0) only when the values the unit
was rendered with are still what the config says now, the config allows a splitter at all (never on the port `[server] port` gives the board:
core/frontdoor_splitter_config.py) and the Caddy at PATH is new enough. Anything else is one line on stderr and exit 1, so the splitter does not start.
That is what keeps the board's port safe after a switch is undone: once the config gives the port back to the board, no start of the splitter passes,
a reboot's included.

Standard library only: the unit runs it with the system's python3.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

MIN_CADDY = (2, 11, 8)       # why this one: docs/front-door.md, "Caddy in front"
_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)(-[0-9A-Za-z][0-9A-Za-z.+~-]*)?")
CADDY_TIMEOUT = 20.0


def caddy_problem(path: str) -> str:
    """Why the Caddy at `path` cannot run the splitter ("" when it can): it does not run, its version cannot be read, or it is older than MIN_CADDY
    (a pre-release of MIN_CADDY counts as older)."""
    need = ".".join(map(str, MIN_CADDY))
    try:
        r = subprocess.run([path, "version"], capture_output=True, text=True, timeout=CADDY_TIMEOUT)
    except (OSError, subprocess.SubprocessError, UnicodeError) as e:
        return f"{path} could not be run ({e.__class__.__name__}): the splitter needs Caddy {need} or later"
    words = (r.stdout or "").split()
    m = _VERSION.fullmatch(words[0]) if r.returncode == 0 and words else None
    if m is None:
        return f"`{path} version` gave no version that can be read (exit {r.returncode}): the splitter needs Caddy {need} or later"
    found = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if found < MIN_CADDY or (found == MIN_CADDY and m.group(4)):
        return f"{path} is Caddy {words[0][:40]}: the splitter needs {need} or later"
    return ""


def problems(rendered: dict[str, str]) -> list[str]:
    """Why a splitter rendered with `rendered` (the names of frontdoor_splitter_config.values) must not start now ([] when it may)."""
    from stackshot.core import frontdoor_splitter_config as sp
    settings = sp.parse()[0]
    why = sp.blocking(settings)
    if why:
        return why
    now = sp.values(settings)
    changed = [f"{k.lower()} was {rendered.get(k)!r} and is {v!r} now" for k, v in now.items() if rendered.get(k) != v]
    if changed:
        return [f"the installed unit is older than the config ({'; '.join(changed)}): run ./install.sh units, then start it again"]
    bad = caddy_problem(now["CADDY"])
    return [bad] if bad else []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m stackshot.frontdoor.splitter",
                                 description="The check before the splitter starts: exit 0 when the unit's values are what the config says and allows.")
    ap.add_argument("verb", choices=["check"])
    for name, what in (("listen", "the splitter's port"), ("board", "the board's host:port"), ("door", "the front door's host:port"),
                       ("signin", "the sign-in service's host:port"), ("header", "the identity header"), ("caddy", "the path of the Caddy the unit runs")):
        ap.add_argument("--" + name, required=True, help=what + " the unit was rendered with")
    a = ap.parse_args(argv)
    rendered = {"LISTEN_PORT": a.listen, "BOARD_ADDR": a.board, "DOOR_ADDR": a.door, "SIGNIN_ADDR": a.signin, "IDENTITY_HEADER": a.header, "CADDY": a.caddy}
    why = problems(rendered)
    if why:
        print(f"splitter: not started: {'; '.join(why)}", file=sys.stderr)
        return 1
    print(f"splitter: the config allows it to listen on port {a.listen}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
