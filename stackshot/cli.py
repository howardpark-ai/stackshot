#!/usr/bin/env python3
"""stackshot — set up, check and connect a stackshot instance, and the front door to the programs of the package. Stdlib only, Python 3.12+.

  stackshot setup            write the instance config, the data repository, the secrets and this box's client token,
                             install the systemd units, and print the two URIs the Google client and claude.ai need
  stackshot doctor           check the instance and start the server once its OAuth client is filled in; on another
                             machine (no oauth.env, no stackshot.service), check only its client
  stackshot client install   store a machine token, start the puller and add the four Claude Code hooks
  stackshot client mint NAME mint a token for another machine (on the server box); prints the token file's path

  stackshot <program> ...    run one of the package's programs with the arguments it takes: `stackshot pages clear <key>`,
                             `stackshot config get server.port`, `stackshot client get brief`, `stackshot push <session> <text>`,
                             `stackshot server`, `stackshot puller --once`, `stackshot audit run` ... (PROGRAMS below lists them; `stackshot client`
                             with anything but install or mint is the client program)

How to run it: `uv run stackshot ...` in the checkout (the package is installed by `uv sync`), `python3 -m stackshot ...` or `python3 stackshot ...` from the
checkout's root on a box with no uv, or `bin/stackshot ...`. The scripts at the checkout's root (pages.py, client.py, ...) still work: they forward to the package.
Each takes -h. INSTALL.md is the walk-through.
"""
from __future__ import annotations

import sys

if sys.version_info < (3, 11):
    sys.exit("stackshot needs Python 3.11 or later (tomllib); this is " + sys.version.split()[0])

import argparse
import datetime
import difflib
import getpass
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import time
import tomllib
import urllib.request
from pathlib import Path

if __package__ in (None, ""):     # started by its path (python3 stackshot/cli.py): the checkout must be importable
    sys.path[:] = [str(Path(__file__).resolve().parent.parent)] + [p for p in sys.path if os.path.abspath(p or ".") != str(Path(__file__).resolve().parent)]
from stackshot import paths as _paths  # noqa: E402

HERE = _paths.ROOT
EXAMPLE = HERE / "stackshot.example.toml"
HOOKS_DIR = HERE / "client" / "hooks"
CALLBACK_PATH = "/auth/callback"                                  # FastMCP's GoogleProvider default redirect path (server.py _auth)
METADATA_PATH = "/.well-known/oauth-authorization-server"         # the OAuth metadata FastMCP serves at the base URL
CONNECTOR_TOOLS = "mcp__.*"       # every MCP tool: pages.py tells a board write from the rest, on the direct connector or inside a portal script (connectors.py)
OAUTH_KEYS = ("STACKSHOT_GOOGLE_CLIENT_ID", "STACKSHOT_GOOGLE_CLIENT_SECRET")


# ---------------------------------------------------------------------------- small helpers
def say(msg: str = "") -> None:
    print(msg, flush=True)


def default_config() -> Path:
    env = os.environ.get("STACKSHOT_CONFIG")
    return Path(os.path.expanduser(env)) if env else Path.home() / ".config" / "stackshot" / "stackshot.toml"


def write_private(path: Path, text: str) -> None:
    """Write a 0600 file atomically; its directory is made 0700 when it does not exist."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def toml_str(v: str) -> str:
    return json.dumps(v, ensure_ascii=False)


def home_rel(p: Path) -> str:
    """A path as the config writes it: ~/… under the HOME (as the example does), absolute elsewhere."""
    h = Path.home().resolve()
    return "~/" + p.relative_to(h).as_posix() if p == h or h in p.parents else str(p)


def toml_list(vs: list[str]) -> str:
    return "[" + ", ".join(toml_str(v) for v in vs) + "]"


_STR = r'"(?:[^"\\]|\\.)*"|\'[^\']*\''
_VALUE = rf'{_STR}|\[(?:{_STR}|[^\]"\'])*\]|\{{(?:{_STR}|[^}}"\'])*\}}|[^#\s]+'


def patch(text: str, section: str, key: str, value: str) -> str:
    """Replace `key = …` inside `[section]` (up to the next header), keeping the line's trailing comment. Exactly one line
    must match: the example and this code have to agree."""
    lines = text.split("\n")
    start = next((i for i, ln in enumerate(lines) if ln.split("#", 1)[0].strip() == f"[{section}]"), None)
    assert start is not None, f"[{section}] not in the example"
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^\s*\[", lines[i])), len(lines))
    rx = re.compile(rf"^({re.escape(key)}\s*=\s*)({_VALUE})(.*)$")
    n = 0
    for i in range(start + 1, end):
        m = rx.match(lines[i])
        if m:
            lines[i] = m.group(1) + value + m.group(3)
            n += 1
    assert n == 1, f"[{section}] {key}: {n} matches in the example"
    return "\n".join(lines)


def run(cmd: list[str], env: dict | None = None, check: bool = False, quiet: bool = False, cwd: str | None = None) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=cwd)
    if check and r.returncode != 0:
        sys.exit(f"failed ({r.returncode}): {' '.join(shlex.quote(c) for c in cmd)}\n{(r.stdout + r.stderr).strip()[-1500:]}")
    if not quiet and (r.stdout or r.stderr):
        for ln in (r.stdout + r.stderr).rstrip().split("\n"):
            say("    " + ln)
    return r


RUNTIME_BASE = os.environ.get("STACKSHOT_RUNTIME_BASE") or "/run/user"      # where logind makes each user's runtime dir (tests point it elsewhere)
USER_MANAGER_UNREACHABLE = ("`systemctl --user` cannot reach your user manager: export XDG_RUNTIME_DIR=/run/user/$(id -u), "
                            "or log in (ssh, console, su -, sudo -i)")


def repair_xdg() -> None:
    """`systemctl --user` finds the user manager through XDG_RUNTIME_DIR, which only a login sets (pam_systemd): `sudo -u`,
    `lxc exec --user` and cron leave it unset. When it is unset and the user's runtime directory exists (the user manager
    runs: lingering, or a session elsewhere), point it there, as units/scope.sh does for install.sh and deploy.sh."""
    if os.name == "nt" or os.environ.get("XDG_RUNTIME_DIR"):
        return
    d = os.path.join(RUNTIME_BASE, str(os.getuid()))
    if os.path.isdir(d):
        os.environ["XDG_RUNTIME_DIR"] = d


def systemd_ok(no_systemd: bool) -> tuple[bool, str]:
    """Can this box run the unit step? → (yes, why not). The units are user units, so only the user manager is needed
    (never sudo: the system scope was removed in an earlier change)."""
    if no_systemd:
        return False, "--no-systemd"
    if not shutil.which("systemctl"):
        return False, "no systemctl on this box"
    if subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True).returncode != 0:
        return False, USER_MANAGER_UNREACHABLE
    return True, ""


def linger(user: str) -> str:
    """Is lingering on for this user (the user manager runs without a login session and starts at boot)? → yes | no | unknown."""
    if shutil.which("loginctl"):
        r = subprocess.run(["loginctl", "show-user", user, "-p", "Linger", "--value"], capture_output=True, text=True)
        v = r.stdout.strip()
        if r.returncode == 0 and v in ("yes", "no"):
            return v
    flags = Path("/var/lib/systemd/linger")         # loginctl knows no user that is neither logged in nor lingering: logind's own flag files
    if flags.is_dir():
        return "yes" if (flags / user).exists() else "no"
    return "unknown"


USER_UNITS = ("stackshot.service", "stackshot-reload.path", "stackshot-reload.service", "stackshot-portal-sync.service",
              "stackshot-puller.service", "anchor-hub.service")


def user_units_installed() -> list[str]:
    """The stackshot units installed for the user manager (~/.config/systemd/user), which is where every unit goes. Any of them
    needs lingering to run without a login session."""
    d = Path.home() / ".config" / "systemd" / "user"
    return [n for n in USER_UNITS if (d / n).is_file()]


LINGER_CMD = "sudo loginctl enable-linger {user}"


def env_with(cfg: Path) -> dict:
    return {**os.environ, "STACKSHOT_CONFIG": str(cfg)}


def load_config(cfg: Path) -> dict:
    with open(cfg, "rb") as f:
        return tomllib.load(f)


def cfg_path(c: dict, *keys: str, default: str = "") -> Path:
    d = c
    for k in keys:
        d = d.get(k, {}) if isinstance(d, dict) else {}
    return Path(os.path.expanduser(str(d or default)))


def oauth_values(p: Path) -> dict[str, bool]:
    """Which OAuth keys carry a value (never the values themselves)."""
    got = {k: False for k in OAUTH_KEYS}
    try:
        for ln in p.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.lstrip().startswith("#"):
                k, v = ln.split("=", 1)
                k = k.strip()
                if k in got or k.replace("BOARD_MCP_", "STACKSHOT_") in got:
                    got[k.replace("BOARD_MCP_", "STACKSHOT_")] |= bool(v.strip().strip('"').strip("'"))
    except OSError:
        pass
    return got


def local_tz() -> str:
    try:
        v = Path("/etc/timezone").read_text(encoding="utf-8").strip()
        if v:
            return v
    except OSError:
        pass
    try:
        v = subprocess.run(["timedatectl", "show", "-p", "Timezone", "--value"], capture_output=True, text=True, timeout=5).stdout.strip()
        if v:
            return v
    except Exception:
        pass
    return "UTC"


PROC_NET = os.environ.get("STACKSHOT_PROC_NET") or "/proc/net"        # (tests point it elsewhere)


def port_owner(port: int) -> int | None:
    """The uid that holds a listening TCP socket on this port (from /proc/net/tcp and tcp6), or None: nothing listens, or this
    is not Linux. Several people on one box each run their own server on a port of their own; this tells theirs from ours."""
    for name in ("tcp", "tcp6"):
        try:
            rows = Path(PROC_NET, name).read_text(encoding="ascii").splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            f = row.split()
            try:
                if len(f) > 7 and f[3] == "0A" and int(f[1].rsplit(":", 1)[1], 16) == port:
                    return int(f[7])
            except ValueError:
                continue
    return None


def someone_else(port: int) -> str:
    """The name of the other user whose process listens on this port, or "" (free, or ours)."""
    uid = port_owner(port)
    if uid is None or uid == os.getuid():
        return ""
    try:
        import pwd
        return pwd.getpwuid(uid).pw_name
    except (ImportError, KeyError):
        return f"uid {uid}"


def example_port() -> int:
    try:
        return int(load_config(EXAMPLE)["server"]["port"])
    except Exception:
        return 8020


# ---------------------------------------------------------------------------- setup
RULES_MD = """# {title}

The board is {owner}'s coordination board. Every Claude session reads and writes it through the connector; this file is
what the connector's `rules` tool serves.

## Items
- An item is human-level: a deliverable a session owns, a decision {owner} must make, a blocker on someone outside, or a handoff between sessions.
- Working steps (read, edit, run, check) never go on the board; a session tracks those itself.
- The subject starts with one of the prefixes ({prefixes}) and says what is to be done, not the area it is in.
- Description: what the item is, where it lives, what done means; short `- ` bullets, one fact each (at most {max_lines} lines of {line_max} characters, links by their text), live state only.

## Fields
- `sender`: your own session, required on every create; the server records it as the item's creator.
- `mover`: the session (or {owner}) that moves the item now; `then`: who takes it after.
- `project`: the item's page key, `projects/<slug>` (a page under {pages}).
- `needs`: `decision` (the next move is {owner}'s) or `external` (blocked on someone outside); empty means its mover can act.
- `due`: `YYYY-MM-DD` in {tz}, set only from a real deadline ({owner}'s word, an outside date, or a date a dependency fixes), otherwise left empty: a made-up date reads to {owner} as their own deadline (to expect something back by a date, use a wake).
- `priority`: `p1` to `p3`.
- `next`: the next concrete action, one per line.

## Pages
- Every item belongs to a project page: `{pages}/<key>.md`, markdown with a `## Current state` and a `## Timeline`.
- A board write that changes state (a create, a complete, or an update of description, next, needs, status or due) is followed in the same turn by an edit of that page.
- The edit rewrites its Current state where it changed and adds a dated line under its Timeline (`- **YYYY-MM-DD** | <session> — <what happened>`).
- Then the session commits and pushes the page; the hooks nag at the next prompt while the page is older than the board write.
- Read the page before acting on or advising about an item.

## Writing
- One thing per line, in the description and in `next` alike.
- Mark items completed; never delete them.
"""

PAGE_MD = """---
title: Getting started
type: project
status: active
display-name: {owner_slug}-getting-started
---

# Getting started

## Current state
- This is the first project page, made by `stackshot setup` so the first board item has a page to belong to.
- Items for it use `project = "projects/getting-started"`.
- Rename it, or add pages beside it under `projects/`, as real projects come along.

<!-- timeline -->

## Timeline
- **{date}** | stackshot setup — page created.
"""


def ask(prompt: str, default: str, interactive: bool) -> str:
    if not interactive:
        return default
    try:
        v = input(f"{prompt} [{default}]: ").strip()
    except EOFError:
        v = ""
    return v or default


def is_repo_root(d: Path) -> bool:
    r = subprocess.run(["git", "-C", str(d), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return r.returncode == 0 and Path(r.stdout.strip()).resolve() == d.resolve()


def inside_repo(d: Path) -> Path | None:
    r = subprocess.run(["git", "-C", str(d), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(r.stdout.strip()).resolve() if r.returncode == 0 else None


def ensure_identity(repo: Path, owner_user: str) -> None:
    have = all(subprocess.run(["git", "-C", str(repo), "config", k], capture_output=True, text=True).stdout.strip() for k in ("user.name", "user.email"))
    if not have:
        email = f"{owner_user}@{socket.gethostname()}"
        run(["git", "-C", str(repo), "config", "user.name", owner_user], check=True, quiet=True)
        run(["git", "-C", str(repo), "config", "user.email", email], check=True, quiet=True)
        say(f"  git has no identity here: set user.name={owner_user} and user.email={email} in {repo} only")


def cmd_setup(a: argparse.Namespace) -> int:
    cfg = default_config()
    if cfg.exists() and not a.force:
        say(f"{cfg} exists; setup leaves it alone. Rerun with --force to rewrite it, or run bin/stackshot doctor.")
        return 2
    if not a.yes and not sys.stdin.isatty():
        print("stdin is not a terminal, so setup cannot ask: pass the answers as flags and add --yes", file=sys.stderr)
        return 2
    interactive = not a.yes
    user = os.environ.get("USER") or getpass.getuser()
    port = a.port or example_port()
    if not 0 < port < 65536:
        say(f"not a TCP port: {port}")
        return 2
    if other := someone_else(port):
        say(f"port {port} is taken on this box by {other}: each person runs their own server on a port of their own; pass --port <a free port>")
        return 2
    owner = a.owner or ask("Your name, as the board should say it", user, interactive)
    tzname = a.tz or ask("Your timezone", local_tz(), interactive)
    try:
        import zoneinfo
        zoneinfo.ZoneInfo(tzname)
    except Exception:
        say(f"not a timezone this Python knows: {tzname!r}")
        return 2
    base = (a.base_url or ask("Public base URL", f"http://127.0.0.1:{port}", interactive)).rstrip("/")
    emails_s = a.emails if a.emails is not None else ask("Google emails allowed to sign in (comma-separated)", "", interactive)
    emails = [e.strip() for e in emails_s.split(",") if e.strip()]
    prefixes_s = a.prefixes if a.prefixes is not None else ask("Subject prefixes (comma-separated)", "[todo] ", interactive)
    prefixes = [p.strip() + " " for p in prefixes_s.split(",") if p.strip()] or ["[todo] "]
    data = Path(os.path.expanduser(a.data or ask("Data repository", "~/stackshot-data", interactive))).resolve()
    pages = Path(os.path.expanduser(a.pages or ask("Project pages directory", str(data / "pages"), interactive))).resolve()

    # 1. the config: the example, patched line by line
    say(f"1. config → {cfg}")
    t = EXAMPLE.read_text(encoding="utf-8")
    title = f"stackshot: {owner}"
    for sec, key, val in (
        ("instance", "title", toml_str(title)),
        ("instance", "owner", toml_str(owner)),
        ("instance", "timezone", toml_str(tzname)),
        ("instance", "board_url", toml_str(base)),
        ("paths", "repo", toml_str(home_rel(data))),
        ("paths", "store", toml_str(home_rel(data / "board-data"))),
        ("paths", "markdown", toml_str(home_rel(data / "board.md"))),
        ("paths", "rules", toml_str(home_rel(data / "RULES.md"))),
        ("paths", "brain", toml_str(home_rel(pages))),
        ("paths", "fleet_names", toml_str(home_rel(data / "session-names.tsv"))),
        ("subject", "prefixes", toml_list(prefixes)),
        ("auth", "base_url", toml_str(base)),
        ("auth", "allowed_emails", toml_list(emails)),
        ("client", "url", toml_str(base)),
        ("gbrain", "mirror_url", toml_str("")),
        ("server", "port", str(port)),
    ):
        t = patch(t, sec, key, val)
    t = re.sub(r"\A(# stackshot\.example\.toml)", f"# stackshot.toml — written by `stackshot setup` on {datetime.date.today().isoformat()} from stackshot.example.toml.\n\\1", t, count=1)
    tomllib.loads(t)                                         # never write a file the code cannot read
    cfg.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    cfg.write_text(t, encoding="utf-8")
    c = load_config(cfg)
    secrets = cfg_path(c, "paths", "secrets")
    env = env_with(cfg)

    # 2. the data repository and the pages
    say(f"2. data repository → {data}")
    data.mkdir(parents=True, exist_ok=True)
    if not is_repo_root(data):
        run(["git", "init", "-q", "-b", "main", str(data)], check=True, quiet=True)
        say("  git init (branch main)")
    ensure_identity(data, user)
    (data / "board-data").mkdir(exist_ok=True)
    (data / "RULES.md").write_text(RULES_MD.format(title=str(c.get("instance", {}).get("title") or title), owner=owner, tz=tzname, pages=str(pages),
                                                   prefixes=", ".join(f"`{p}`" for p in prefixes),
                                                   max_lines=int(c.get("description", {}).get("max_lines", 8)), line_max=int(c.get("description", {}).get("line_max", 120))), encoding="utf-8")
    slug = re.sub(r"[^a-z0-9]+", "-", user.lower()).strip("-") or "owner"
    page = pages / "projects" / "getting-started.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    if not page.exists():
        page.write_text(PAGE_MD.format(owner_slug=slug, date=datetime.datetime.now(__import__("zoneinfo").ZoneInfo(tzname)).date().isoformat()), encoding="utf-8")
        say(f"  first page → {page}")
    host = socket.gethostname()
    letter = str(c.get("fleet", {}).get("publisher_letter") or "a")
    (data / "session-names.tsv").write_text("# os hostname\tfleet name\tletter (stackshot setup)\n" + f"{host}\t{host}\t{letter}\n", encoding="utf-8")
    if data not in pages.parents and pages != data and inside_repo(pages) is None:
        # pages outside the data repository and in no repository: they get one of their own (the page rule commits pages)
        run(["git", "init", "-q", "-b", "main", str(pages)], check=True, quiet=True)
        ensure_identity(pages, user)
        run(["git", "-C", str(pages), "add", "-A"], check=True, quiet=True)
        run(["git", "-C", str(pages), "commit", "-q", "-m", "stackshot setup"], check=True, quiet=True)
        say(f"  pages are outside the data repository: git init {pages} and committed the first page there")
    run([sys.executable, _paths.program("projects", "pages"), "registry"], env=env, check=True)     # projects.json, so the first item has a page
    run(["git", "-C", str(data), "add", "-A"], check=True, quiet=True)
    if subprocess.run(["git", "-C", str(data), "diff", "--cached", "--quiet"]).returncode != 0:
        run(["git", "-C", str(data), "commit", "-q", "-m", "stackshot setup"], check=True, quiet=True)
        say("  committed: stackshot setup")
    if not subprocess.run(["git", "-C", str(data), "remote"], capture_output=True, text=True).stdout.strip():
        say("  no origin remote yet: add one (git -C %s remote add origin <url>) or set [publish] git = false" % shlex.quote(str(data)))

    # 3. the secrets
    say(f"3. secrets → {secrets}")
    secrets.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(secrets, 0o700)
    oauth = secrets / "oauth.env"
    if oauth.exists() and oauth.read_text(encoding="utf-8").strip():
        say("  oauth.env exists: left as it is")
    else:
        write_private(oauth, "# The Google OAuth client (Web application) for the connector and the board; fill both, then bin/stackshot doctor\n"
                             + "".join(f"{k}=\n" for k in OAUTH_KEYS))
        say("  oauth.env written (0600, both values empty)")
    say("  ui-session.key: the server makes it (0600) on its first start")

    # 4. this box's client token
    say(f"4. client token for this box ({host})")
    try:
        clients = json.loads((secrets / "clients.json").read_text(encoding="utf-8"))
    except Exception:
        clients = {}
    if (secrets / "client.token").exists() and host in clients:
        # the token stays; client.url follows [server] port, which a rerun with --force --port may have changed
        srv = c.get("server", {})
        write_private(secrets / "client.url", f"http://{srv.get('host') or '127.0.0.1'}:{srv.get('port') or port}\n")
        say("  already minted: kept; client.url → the local port")
    else:
        r = run([sys.executable, _paths.program("fleet", "client"), "mint", host], env=env, quiet=True)
        if r.returncode != 0:
            say((r.stdout + r.stderr).strip()); return 1
        say(f"  {secrets / 'client-tokens' / (host + '.token')} (0600), installed as client.token; client.url → the local port")

    # 5. the units
    ok, why = systemd_ok(a.no_systemd)
    linger_off = False
    if ok:
        say("5. systemd units (user units, systemctl --user)")
        if run([str(HERE / "install.sh"), "units", "--quiet-hint", "--config", str(cfg)]).returncode != 0:
            say("  install.sh units failed; fix the above, then bin/stackshot doctor"); return 1
        r = run([str(HERE / "install.sh"), "puller", "--start", "--config", str(cfg)])
        if r.returncode != 0:
            say("  the puller did not start; bin/stackshot doctor checks it again")
        say("  stackshot.service is installed and enabled, not started: it needs oauth.env (doctor starts it)")
        linger_off = linger(user) != "yes"       # install.sh tried to switch it on; what it could not do is repeated at the end
    else:
        say(f"5. systemd units: skipped ({why}); install them later with ./install.sh units --config {cfg}")

    say()
    say(f"Google OAuth redirect URI:   {base}{CALLBACK_PATH}")
    say(f"claude.ai connector URL:     {base}{c.get('server', {}).get('path') or '/mcp'}")
    say()
    if linger_off:
        say(f"lingering is off for {user}: the services stop at logout and do not start at boot. Run this once as root:  {LINGER_CMD.format(user=user)}")
    say(f"fill oauth.env ({oauth}), then run bin/stackshot doctor")
    return 0


# ---------------------------------------------------------------------------- doctor
def unit_active(name: str, user: bool) -> str:
    cmd = ["systemctl"] + (["--user"] if user else []) + ["is-active", name]
    return subprocess.run(cmd, capture_output=True, text=True).stdout.strip() or "unknown"


def http_ok(url: str, timeout: int = 10) -> bool:
    if shutil.which("curl"):
        return subprocess.run(["curl", "-sf", "-o", os.devnull, "-m", str(timeout), url], capture_output=True).returncode == 0
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


HOOK_SIGNS = {                     # event → what a stackshot hook command carries there (this checkout's or an older shim's)
    "SessionStart": ("session-start.sh", "keeper"),
    "UserPromptSubmit": ("nag",),
    "PostToolUse": ("touch",),
    "Stop": ("check",),
}


def plugin_hook_entries() -> dict[str, list]:
    """The hook entries of the enabled stackshot Claude Code plugin (`stackshot@<marketplace>` in the user settings'
    enabledPlugins), read from the hooks/hooks.json of each install path listed in plugins/installed_plugins.json.
    Empty when the plugin is not enabled, not installed or its hooks file does not read."""
    claude = Path.home() / ".claude"
    def load(path: Path) -> dict:
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return d if isinstance(d, dict) else {}
    enabled = load(claude / "settings.json").get("enabledPlugins")
    names = [k for k, v in (enabled if isinstance(enabled, dict) else {}).items() if v is True and str(k).startswith("stackshot@")]
    installed = load(claude / "plugins" / "installed_plugins.json").get("plugins")
    out: dict[str, list] = {}
    for name in names:
        recs = installed.get(name) if isinstance(installed, dict) else None
        for inst in recs if isinstance(recs, list) else []:
            where = inst.get("installPath") if isinstance(inst, dict) else None
            if not where:
                continue
            doc = load(Path(str(where)) / "hooks" / "hooks.json")
            hooks = doc.get("hooks") if isinstance(doc.get("hooks"), dict) else doc      # the file wraps its events in "hooks"
            for ev, entries in hooks.items():
                if isinstance(entries, list):
                    out.setdefault(ev, []).extend(e for e in entries if isinstance(e, dict))
    return out


def hooks_present(settings: dict, extra: dict | None = None) -> list[str]:
    """The events that carry a stackshot page hook, in the settings' hooks or in `extra` (the enabled plugin's, same shape)."""
    have = []
    own = settings.get("hooks") if isinstance(settings, dict) else None
    for ev, signs in HOOK_SIGNS.items():
        entries = []
        for src in (own, extra):
            got = src.get(ev) if isinstance(src, dict) else None
            entries += got if isinstance(got, list) else []
        for entry in entries:
            hs = entry.get("hooks") if isinstance(entry, dict) else None
            cmds = [str(h.get("command") or "") for h in (hs if isinstance(hs, list) else []) if isinstance(h, dict)]
            if any(("project-page" in c or "pages.py" in c or "client/hooks" in c) and any(s in c for s in signs) for c in cmds):
                have.append(ev); break
    return have


def hooks_line(settings: dict, sp: Path) -> tuple[bool, str]:
    """doctor's hooks line: (all four present, text). Hooks the stackshot plugin carries count when it is enabled."""
    own = hooks_present(settings)
    plug = plugin_hook_entries()
    have = hooks_present(settings, plug)
    via = [ev for ev in have if ev not in own]
    text = f"Claude Code hooks in {sp}: {len(have)} of 4"
    if via:
        text += f" ({len(via)} of them from the stackshot plugin)"
    return len(have) == 4, text


SERVER_UNIT = Path.home() / ".config" / "systemd" / "user" / "stackshot.service"          # the server's unit: a user unit, this box is the server box
SYSTEM_UNIT = Path(os.environ.get("STACKSHOT_SYSTEM_UNIT_DIR") or "/etc/systemd/system") / "stackshot.service"   # the removed system scope's; only noted (tests point it elsewhere)
WHOAMI_PY = "from stackshot.fleet import client; import json; st, b = client.get('whoami'); print(json.dumps([st, b, client.server_url()]))"


def cmd_doctor(a: argparse.Namespace) -> int:
    cfg = default_config()
    missing = 0
    skipped: list[str] = []

    def line(ok: bool, what: str, hint: str = "", warn: bool = False) -> None:
        nonlocal missing
        tag = "ok     " if ok else ("warn   " if warn else "missing")
        if not ok and not warn:
            missing += 1
        say(f"  {tag} {what}" + (f" — {hint}" if hint and not ok else ""))

    def skip(why: str) -> None:            # a check that could not run is a warning, and doctor never ends "all good" over it
        skipped.append(why)
        line(False, f"unit checks skipped: {why}", warn=True)

    def verdict() -> int:
        if missing:
            say(f"{missing} missing" + ("; the unit checks were skipped too" if skipped else ""))
        elif skipped:
            say("nothing missing among the checks that ran, but the unit checks were skipped (see the warning above)")
        else:
            say("all good")
        return 1 if missing or skipped else 0

    # the config through config.py, as the server and the hooks read it; with no config file, what they would fall back to
    env = env_with(cfg) if cfg.is_file() else {k: v for k, v in os.environ.items() if k not in ("STACKSHOT_CONFIG", "BOARD_MCP_CONFIG")}
    r = subprocess.run([sys.executable, "-c", "from stackshot.core import config; import json; print(json.dumps({'file': str(config.PATH), 'cfg': config.CFG, 'obsolete': config.obsolete(), 'notes': config.notes()}))"],
                       capture_output=True, text=True, env=env, cwd=str(HERE))
    loaded = json.loads(r.stdout) if r.returncode == 0 else {}
    c = loaded.get("cfg") or {}
    secrets = cfg_path(c, "paths", "secrets", default="~/.config/stackshot")
    token = secrets / "client.token"
    # a client machine: no OAuth client and no server unit here, only this machine's half
    client_box = r.returncode == 0 and not (secrets / "oauth.env").exists() and not SERVER_UNIT.is_file()

    if r.returncode != 0:
        say(f"stackshot doctor · mode unknown (the config does not load) · checkout {HERE}")
        errs = r.stderr.strip().splitlines() or ["?"]       # config.py's refusals, one line per removed value, all of them; a traceback: its last line
        line(False, f"config {cfg} loads through config.py", " | ".join(errs) if all("removed in stackshot" in e for e in errs) else errs[-1])
        return 1
    if client_box and not cfg.is_file() and not token.is_file():
        say(f"stackshot doctor · nothing installed here yet · checkout {HERE}")
        line(False, f"config {cfg}", "run bin/stackshot setup on the server box, or bin/stackshot client install --url <server> --token-file <file> "
                                     "on another machine")
        return 1
    if client_box:
        return doctor_client(a, cfg, c, env, secrets, line, skip, verdict)

    say(f"stackshot doctor · server box · checkout {HERE}")
    if not cfg.is_file():
        line(False, f"config {cfg}", "run bin/stackshot setup")
        return 1
    line(True, f"config {cfg}")
    if loaded.get("obsolete"):            # keys whose other values are no longer accepted, still in the file at the one value left: harmless, and they can go
        say(f"  note    {', '.join(loaded['obsolete'])} in {cfg}: the other values are no longer accepted and these lines can go (config.py REMOVED)")
    for n in loaded.get("notes") or []:   # a missing setting that turns a rule off without a word (keeper_currency)
        line(False, f"{cfg}: {n}", warn=True)
    if SYSTEM_UNIT.is_file():             # not this instance's: a unit of a system scope an older install left
        say(f"  note    {SYSTEM_UNIT} exists: the removed system scope's unit, not this instance's (harmless while disabled and stopped; remove its files when the user units have proven themselves)")
    oauth = oauth_values(secrets / "oauth.env")
    filled = sum(oauth.values())
    line(filled == 2, f"oauth.env: {filled} of 2 values set ({secrets / 'oauth.env'})", "put the Google client's id and secret into oauth.env")
    emails = list(c.get("auth", {}).get("allowed_emails") or [])
    line(bool(emails) or c.get("auth", {}).get("mode") == "off", f"auth.allowed_emails: {len(emails)} address(es)",
         f"add your Google email to [auth] allowed_emails in {cfg}: nobody can sign in, and the server will not start")
    line((secrets / "client.token").is_file(), "this box's client token", "run bin/stackshot client install (or setup)")
    port = int(c.get("server", {}).get("port") or 8020)
    base = str(c.get("auth", {}).get("base_url") or "").rstrip("/")
    hub = str(c.get("anchor_hub", {}).get("enabled", False)).lower() in ("true", "1", "yes")
    portal = bool(str(c.get("portal", {}).get("account_id") or "").strip())
    jflag = "--user "
    uu = user_units_installed()
    user = os.environ.get("USER") or getpass.getuser()      # every unit is a user unit, so lingering is always needed
    lg = linger(user)
    whose = f"user units: {', '.join(uu)}" if uu else "the units are user units"
    line(lg == "yes", f"lingering for {user}: {lg} ({whose})",
         f"they stop at logout and do not start at boot until root runs `{LINGER_CMD.format(user=user)}`", warn=lg == "unknown")

    sd, why = systemd_ok(a.no_systemd)
    started = False
    if sd:
        if filled == 2 and emails and unit_active("stackshot.service", True) != "active":
            say("  … stackshot.service is not active: install.sh units --start")
            run([str(HERE / "install.sh"), "units", "--start", "--config", str(cfg)])
            started = True
    else:
        skip(why)

    healthz = f"http://127.0.0.1:{port}/healthz"
    up = False
    for _ in range(30 if started else 1):
        if http_ok(healthz, 3):
            up = True; break
        if started:
            time.sleep(1)
    other = someone_else(port)
    if other:                              # what answers there is not this instance's server: another person's on this box, or another program
        line(False, f"port {port} belongs to {other}, not to you", "give this instance a port of its own ([server] port), then ./install.sh units --start")
    else:
        line(up, f"the server answers {healthz}", f"check `journalctl {jflag}-u stackshot.service -n 50`" if sd else "the server is not running")
    if hub and (other := someone_else(int(c.get("anchor_hub", {}).get("hook_port") or 8010))):
        line(False, f"anchor-hub's hook port belongs to {other}, not to you", "give this instance its own [anchor_hub] hook_port")
    meta = base + METADATA_PATH
    line(http_ok(meta, 10), f"OAuth metadata reachable at {meta}", "the HTTPS front does not reach the server yet, or the server is down")

    if sd:
        units = [("stackshot.service", True), ("stackshot-reload.path", True), ("stackshot-puller.service", True)]
        if hub:
            units.append(("anchor-hub.service", True))
        for name, user in units:
            st = unit_active(name, user)
            line(st == "active", f"{name}: {st}", "./install.sh units --start" if name != "stackshot-puller.service" else "./install.sh puller --start")
        if portal:
            st = unit_active("stackshot-portal-sync.service", True)           # a oneshot: inactive after a clean run, failed after a bad one
            line(st != "failed", f"stackshot-portal-sync.service: {st}", f"journalctl {jflag}-u stackshot-portal-sync.service")

    repo = cfg_path(c, "paths", "repo")
    if c.get("publish", {}).get("git", True):
        has_origin = "origin" in subprocess.run(["git", "-C", str(repo), "remote"], capture_output=True, text=True).stdout.split()
        line(has_origin, f"data repository {repo}: {'origin remote set' if has_origin else 'no origin remote'}",
             "the publisher commits but cannot push; add a remote or set [publish] git = false", warn=True)
    sp = Path.home() / ".claude" / "settings.json"
    try:
        settings = json.loads(sp.read_text(encoding="utf-8"))
    except Exception:
        settings = {}
    line(*hooks_line(settings, sp), "run bin/stackshot client install")
    if hub:
        line((secrets / "anchor-hub" / "env").is_file(), f"anchor-hub env {secrets / 'anchor-hub' / 'env'}", "create it with the receivers' tokens")
    return verdict()


def doctor_client(a: argparse.Namespace, cfg: Path, c: dict, env: dict, secrets: Path, line, skip, verdict) -> int:
    """doctor on a machine that only runs Claude Code sessions: its token, the server's answer to it, lingering and the puller
    when a puller unit is installed, and the four hooks. Nothing of the server's own (oauth.env, its units, healthz) is checked
    here, and nothing is started."""
    say(f"stackshot doctor · client machine (no oauth.env, no stackshot.service here: checking this machine's client) · checkout {HERE}")
    if cfg.is_file():
        line(True, f"config {cfg}")
    else:
        line(False, f"config: none at {cfg}, so the example's defaults apply (timezone UTC, plain pages)",
             "bin/stackshot client install --url <server> --token-file <file> writes one from the server's settings", warn=True)
    token = secrets / "client.token"
    line(token.is_file(), f"this machine's client token ({token})",
         "on the server box run bin/stackshot client mint <name>, carry the file here, then bin/stackshot client install --url <server> --token-file <file>")
    if token.is_file():
        r = subprocess.run([sys.executable, "-c", WHOAMI_PY], capture_output=True, text=True, env=env, cwd=str(HERE))
        try:
            st, body, url = json.loads(r.stdout)
        except Exception:
            st, body, url = "?", (r.stderr.strip().splitlines() or ["?"])[-1], ""
        machine = ""
        if st == 200:
            try:
                machine = str(json.loads(body).get("machine") or "")
            except Exception:
                pass
        hint = ("the server cannot be reached: is it up, and is the URL right (" + str(secrets / "client.url") + ")?" if st == 0 else
                "the server does not know this token: on the server box run bin/stackshot client mint <name> --rotate, then client install here again"
                if st == 401 else "see the server's journal")
        line(bool(machine), f"the server at {url or '(no URL)'} answers whoami for this machine: " + (machine or f"[{st}] {str(body)[:160]}"), hint)
    uu = user_units_installed()
    if uu:                                                 # a user unit runs without a login session only with lingering
        user = os.environ.get("USER") or getpass.getuser()
        lg = linger(user)
        line(lg == "yes", f"lingering for {user}: {lg} (user units: {', '.join(uu)})",
             f"they stop at logout and do not start at boot until root runs `{LINGER_CMD.format(user=user)}`", warn=lg == "unknown")
    if "stackshot-puller.service" in uu:
        sd, why = systemd_ok(a.no_systemd)
        if sd:
            st = unit_active("stackshot-puller.service", True)
            line(st == "active", f"stackshot-puller.service: {st}", "./install.sh puller --start")
        else:
            skip(why)
    sp = Path.home() / ".claude" / "settings.json"
    try:
        settings = json.loads(sp.read_text(encoding="utf-8"))
    except Exception:
        settings = {}
    line(*hooks_line(settings, sp), "run bin/stackshot client install")
    return verdict()


# ---------------------------------------------------------------------------- client install / mint
def hook_entries(no_puller: bool = False) -> dict[str, list[dict]]:
    """The four page hooks; with no_puller, also client.py's three verbs (register, seen, drain) for a machine whose sessions
    fetch their notices themselves at each prompt instead of through a puller."""
    h = HOOKS_DIR.as_posix()
    cmd = lambda script, *args: " ".join(["bash", shlex.quote(f"{h}/{script}"), *args])
    out = {
        "SessionStart": [{"hooks": [{"type": "command", "command": cmd("session-start.sh"), "timeout": 30}]}],
        "UserPromptSubmit": [{"hooks": [{"type": "command", "command": cmd("project-page.sh", "nag"), "timeout": 30}]}],
        "PostToolUse": [{"matcher": CONNECTOR_TOOLS, "hooks": [{"type": "command", "command": cmd("project-page.sh", "touch"), "timeout": 10}]}],
        "Stop": [{"hooks": [{"type": "command", "command": cmd("project-page.sh", "check"), "timeout": 30}]}],
    }
    if no_puller:
        for ev, verb in (("SessionStart", "register"), ("UserPromptSubmit", "drain"), ("Stop", "seen")):
            out[ev].append({"hooks": [{"type": "command", "command": cmd("client.sh", verb), "timeout": 10}]})
    return out


def merge_hooks(settings: dict, no_puller: bool = False) -> tuple[dict, int]:
    """settings with the hook entries added where their command is not already present → (new settings, entries added)."""
    out = json.loads(json.dumps(settings))
    hooks = out.setdefault("hooks", {})
    added = 0
    for ev, entries in hook_entries(no_puller).items():
        cur = hooks.setdefault(ev, [])
        present = {str(h.get("command") or "") for e in cur if isinstance(e, dict) for h in e.get("hooks") or [] if isinstance(h, dict)}
        for e in entries:
            if all(h["command"] in present for h in e["hooks"]):
                continue
            cur.append(e); added += 1
    return out, added


def toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    return toml_str(str(v))


CLIENT_KEYS = (("instance", ("name", "title", "owner", "timezone", "board_url")), ("pages", ("flavor", "dirs")), ("paths", ("brain",)),
               ("subject", ("prefixes",)), ("page_gate", ("keeper_currency",)), ("board_check", ("mode",)), ("gbrain", ("mirror_url",)),
               ("server", ("path",)))


def client_config_text(settings: dict, url: str) -> str:
    """A client box's config: the example, with the instance's non-secret settings (the server's `config` read) and the
    server's URL filled in. A key the server does not send keeps the example's value. The server sends the instance's whole
    [page_gate]; a key retired with the end-of-turn page question (mode, block_after) and still set in an
    instance's config is no CLIENT_KEY, so it is left out."""
    t = EXAMPLE.read_text(encoding="utf-8")
    for sec, keys in CLIENT_KEYS:
        got = dict(settings.get(sec) or {})
        for k in keys:
            if k in got:
                t = patch(t, sec, k, toml_value(got[k]))
    t = patch(t, "client", "url", toml_str(url))
    for b in settings.get("brains") or []:      # the instance's second brains ([[brains]]): their page rules and mirrors, so this box links their pages right
        if isinstance(b, dict) and b.get("name") and b.get("path"):
            t = t.rstrip("\n") + "\n\n[[brains]]\n" + "".join(f"{k} = {toml_value(b[k])}\n" for k in ("name", "path", "mirror_url", "slugs", "prefixes") if k in b) \
                + "remote = true                                      # this box holds no copy and no gbrain home of this brain: the server writes its pages\n"
    t = re.sub(r"\A(# stackshot\.example\.toml)", f"# stackshot.toml — written by `stackshot client install` on {datetime.date.today().isoformat()} "
               f"from the instance's settings at {url} and stackshot.example.toml.\n\\1", t, count=1)
    tomllib.loads(t)                                         # never write a file the code cannot read
    return t


def puller_hint() -> str:
    if os.name == "nt":
        return f"run `pythonw {HERE / 'puller.py'}` as a scheduled task at logon (docs/windows.md)"
    return f"run `python3 {HERE / 'puller.py'}` as a service or scheduled task"


def cmd_client_install(a: argparse.Namespace) -> int:
    if a.print:
        say(json.dumps({"hooks": hook_entries(a.no_puller)}, indent=2))
        return 0
    if bool(a.url) != bool(a.token_file):
        say("--url and --token-file go together"); return 2
    cfg = default_config()
    env = {**os.environ}
    if cfg.is_file():
        env["STACKSHOT_CONFIG"] = str(cfg)
    r = subprocess.run([sys.executable, "-c", "from stackshot.core import config; import json; print(json.dumps([str(config.secrets()), str(config.PATH) != str(config.EXAMPLE)]))"],
                       capture_output=True, text=True, env=env, cwd=str(HERE))
    if r.returncode != 0:
        say("cannot read the config: " + (r.stderr.strip().splitlines() or ["?"])[-1]); return 1
    sec_s, have_config = json.loads(r.stdout)
    secrets = Path(sec_s)
    if a.url:
        src = Path(os.path.expanduser(a.token_file))
        try:
            tok = src.read_text(encoding="utf-8").strip()
        except OSError as e:
            say(f"cannot read the token file: {e}"); return 1
        if not tok or len(tok.split()) != 1:
            say(f"{src} does not hold one token"); return 1
        secrets.mkdir(mode=0o700, parents=True, exist_ok=True)
        write_private(secrets / "client.token", tok + "\n")
        write_private(secrets / "client.url", a.url.rstrip("/") + "\n")
        say(f"token → {secrets / 'client.token'} (0600, not shown) · server → {a.url.rstrip('/')} ({secrets / 'client.url'})")
        if have_config or os.environ.get("STACKSHOT_CONFIG"):
            say("config: this machine has one; left as it is")
        else:                                                # a fresh client box: the instance's timezone, page flavor and gate
            g = subprocess.run([sys.executable, "-c", "from stackshot.fleet import client; import json, sys; st, b = client.get('config'); print(json.dumps([st, b]))"],
                               capture_output=True, text=True, env=env, cwd=str(HERE))
            try:
                st, body = json.loads(g.stdout)
                settings = json.loads(body) if st == 200 else None
            except Exception:
                st, settings = "?", None
            if isinstance(settings, dict):
                cfg = default_config()
                cfg.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                cfg.write_text(client_config_text(settings, a.url.rstrip("/")), encoding="utf-8")
                env["STACKSHOT_CONFIG"] = str(cfg)
                inst = settings.get("instance") or {}
                say(f"config → {cfg} (the instance's settings: timezone {inst.get('timezone') or '?'}, pages flavor "
                    f"{(settings.get('pages') or {}).get('flavor') or '?'})")
            else:
                say(f"config: could not read the instance's settings from the server [{st}]; this machine uses the example's "
                    "defaults (timezone UTC, plain pages) until client install runs again")
    elif (secrets / "client.token").is_file():
        say(f"token: {secrets / 'client.token'} (from setup or an earlier install)")
    else:
        say(f"no token at {secrets / 'client.token'}: on the server box run bin/stackshot setup; on another machine pass --url and --token-file")
        return 1
    if a.no_puller:
        say("puller: none (--no-puller); the sessions' hooks register them and fetch what waits at each prompt (client.py)")
    elif a.no_systemd or not shutil.which("systemctl"):
        say(f"puller: not installed ({'--no-systemd' if a.no_systemd else 'no systemd on this box'}); {puller_hint()}")
    else:
        rr = run([str(HERE / "install.sh"), "puller", "--start"] + (["--config", str(cfg)] if cfg.is_file() else []), env=env)
        if rr.returncode != 0:
            say("puller: install.sh puller failed (see above)")
    sp = Path.home() / ".claude" / "settings.json"
    try:
        old_text = sp.read_text(encoding="utf-8")
        settings = json.loads(old_text) if old_text.strip() else {}
    except FileNotFoundError:
        old_text, settings = "", {}
    except json.JSONDecodeError as e:
        say(f"{sp} is not valid JSON ({e}); fix it, or add the hooks by hand from bin/stackshot client install --print"); return 1
    new, added = merge_hooks(settings, a.no_puller)
    if not added:
        say(f"hooks: all {'seven' if a.no_puller else 'four'} already in {sp}")
        return 0
    new_text = json.dumps(new, indent=2, ensure_ascii=False) + "\n"
    old_cmp = json.dumps(settings, indent=2, ensure_ascii=False) + "\n" if settings else ""
    sys.stdout.writelines(difflib.unified_diff(old_cmp.splitlines(True), new_text.splitlines(True), str(sp), str(sp) + " (new)"))
    sp.parent.mkdir(parents=True, exist_ok=True)
    if sp.exists():
        bak = sp.with_name(f"settings.json.bak-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(sp, bak)
        say(f"backup → {bak}")
    tmp = sp.with_name(".settings.json.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, sp)
    say(f"hooks: {added} added to {sp}; start a new Claude Code session to load them")
    return 0


MINT_PY = """import json, os, sys
from stackshot.fleet import client
name, rotate = sys.argv[1].strip(), sys.argv[2] == "1"
path = os.path.join(client.TOKENS, name + ".token")
had = name in client._clients() or os.path.isfile(path)
if had and not rotate:
    print(json.dumps({"refused": path})); sys.exit(0)
try: print(json.dumps({"path": client.mint(name), "rotated": had}))
except ValueError as e: print(e, file=sys.stderr); sys.exit(1)
"""


def cmd_client_mint(a: argparse.Namespace) -> int:
    cfg = default_config()
    env = env_with(cfg) if cfg.is_file() else dict(os.environ)
    r = subprocess.run([sys.executable, "-c", MINT_PY, a.name, "1" if a.rotate else "0"], capture_output=True, text=True, env=env, cwd=str(HERE))
    if r.returncode != 0:
        sys.stderr.write(r.stderr); return 1
    d = json.loads(r.stdout)
    if "refused" in d:
        print(f"{a.name} already has a token ({d['refused']}); minting again would make the copy on that machine stop working. "
              "Rerun with --rotate to replace it.", file=sys.stderr)
        return 2
    say(d["path"])
    if d.get("rotated"):
        print(f"rotated: the old token for {a.name} no longer works, and any copy of the old file is now invalid; carry this file to "
              f"that machine and run client install there again", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------- the programs of the package
# `stackshot <program> ...` runs the module as `python3 -m` would, with the arguments after the program's name. The same modules still run by their old
# path at the checkout's root (pages.py, client.py ...): those files forward to these.
PROGRAMS = {
    "config": ("stackshot.core.config", "the instance config: get, path, state, secrets, file, check"),
    "client": ("stackshot.fleet.client", "one machine's half of stackshot: get, post, message ... (install and mint are the setup commands above)"),
    "push": ("stackshot.fleet.push", "deliver one notice line into a live session's inbox"),
    "puller": ("stackshot.fleet.puller", "one machine's fetcher"),
    "connectors": ("stackshot.fleet.connectors", "one name for every call to this instance's own connectors"),
    "session-ids": ("stackshot.fleet.session_ids", "the one-shot migration to permanent session ids"),
    "versions": ("stackshot.fleet.versions", "installed vs latest, for the Machines panel"),
    "pages": ("stackshot.projects.pages", "the project-page half of the board"),
    "page-keeper": ("stackshot.projects.page_keeper", "the one-time pass that renames a page's session line"),
    "projects": ("stackshot.projects.projects", "the project record"),
    "rename-page": ("stackshot.projects.rename_page", "move gbrain pages to new slugs (server box only)"),
    "anchors": ("stackshot.anchors.anchors", "project anchors"),
    "anchor-hub": ("stackshot.anchors.anchor_hub", "receive change events on a project's anchors and notify the bound sessions"),
    "anchor-hub-google-auth": ("stackshot.anchors.anchor_hub_google_auth", "one-time Google authorization for anchor-hub"),
    "audit": ("stackshot.audit.audit", "the server side of the daily board audit"),
    "audit-run": ("stackshot.audit.audit_run", "the daily board audit as a script"),
    "held": ("stackshot.waits.held", "notices held for a background agent until its next turn"),
    "router-live": ("stackshot.router.router_live", "the router that rules the notices"),
    "ghmigrate": ("stackshot.github.ghmigrate", "move a board store's open items onto GitHub Issues"),
    "server": ("stackshot.web.server", "the MCP connector and the board (needs the server extra: uv run --extra server stackshot server)"),
    "publish": ("stackshot.web.publish", "the stackshot publisher"),
    "render": ("stackshot.web.render", "the board's text renderer"),
}


def run_program(name: str, args: list[str]) -> int:
    """Run the package's module for `name` as __main__ with sys.argv = [its name, *args]; the module's own exit code is this one's."""
    import runpy
    sys.argv = [PROGRAMS[name][0], *args]
    try:
        runpy.run_module(PROGRAMS[name][0], run_name="__main__", alter_sys=True)
    except SystemExit as e:
        if e.code is None or isinstance(e.code, int):
            return e.code or 0
        print(e.code, file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """The `stackshot` command: the setup commands, or `stackshot <program> ...`."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in PROGRAMS and not (argv[0] == "client" and (argv[1:2] in (["install"], ["mint"]) or argv[1:2] in (["-h"], ["--help"]) or not argv[1:])):
        return run_program(argv[0], argv[1:])
    return setup_main(argv)


def setup_main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="stackshot", description="Set up, check and connect a stackshot instance. INSTALL.md walks through it. "
                                                              "Any other program of the package runs as `stackshot <program> ...`.",
                                epilog="programs:\n" + "\n".join(f"  {n:<24}{d}" for n, (_, d) in PROGRAMS.items()), formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup", help="write the config, the data repository, the secrets and the units",
                       description="Write the instance config (to $STACKSHOT_CONFIG or ~/.config/stackshot/stackshot.toml), the data "
                                   "repository with RULES.md and a first page, the secrets directory with an empty oauth.env, this box's "
                                   "client token, and the systemd units; then print the Google redirect URI and the connector URL.")
    s.add_argument("--owner", help="your name as the board says it (default $USER)")
    s.add_argument("--tz", help="your timezone (default /etc/timezone, timedatectl, else UTC)")
    s.add_argument("--base-url", help="the public base URL (default http://127.0.0.1:<server.port>)")
    s.add_argument("--port", type=int, help="the server's local port, [server] port (default 8020); a second person on the same "
                                            "box sets up under their own account with a port of their own")
    s.add_argument("--emails", help="Google emails allowed to sign in, comma-separated (default none)")
    s.add_argument("--prefixes", help='subject prefixes, comma-separated, e.g. "[work] ,[home] " (default "[todo] ")')
    s.add_argument("--data", help="the data repository (default ~/stackshot-data)")
    s.add_argument("--pages", help="the project pages directory (default <data>/pages)")
    s.add_argument("--yes", action="store_true", help="ask nothing: the defaults fill the gaps")
    s.add_argument("--force", action="store_true", help="rewrite an existing config")
    s.add_argument("--no-systemd", action="store_true", help="skip the unit step")
    s.set_defaults(fn=cmd_setup)

    d = sub.add_parser("doctor", help="check the instance; start the server once oauth.env is filled",
                       description="Print a checklist (exit 1 when anything is missing or a unit check could not run). With both "
                                   "oauth.env values set and the server not active, run install.sh units --start and wait for /healthz. "
                                   "On a client machine (no oauth.env and no stackshot.service installed) check only this machine's "
                                   "token, the server's whoami for it, lingering and the puller when its unit is installed, and the hooks.")
    d.add_argument("--no-systemd", action="store_true", help="skip the unit checks and the start")
    d.set_defaults(fn=cmd_doctor)

    c = sub.add_parser("client", help="this machine's client: install, or mint a token for another machine",
                       description="install: store a token, start the puller, add the hooks · mint NAME: a token for another machine")
    cs = c.add_subparsers(dest="ccmd", required=True)
    ci = cs.add_parser("install", help="store the token, start the puller, add the four hooks",
                       description="With --url and --token-file, store that token and URL under the secrets directory and, on a "
                                   "machine with no config yet (and no STACKSHOT_CONFIG), write ~/.config/stackshot/stackshot.toml with the "
                                   "instance's non-secret settings read from the server; without them, use the token setup made. Then "
                                   "install and start the puller (systemd user unit) and merge the four hooks into ~/.claude/settings.json "
                                   "(backup and diff first; an entry already present is not added twice).")
    ci.add_argument("--url", help="the server's public base URL (with --token-file)")
    ci.add_argument("--token-file", help="the token file minted on the server box (with --url)")
    ci.add_argument("--print", action="store_true", help="print the hooks fragment and write nothing")
    ci.add_argument("--no-systemd", action="store_true", help="do not install the puller unit")
    ci.add_argument("--no-puller", action="store_true", help="no puller on this machine: also wire client.py's register, seen and drain "
                                                             "hooks, so the sessions fetch what waits for them at each prompt")
    ci.set_defaults(fn=cmd_client_install)
    cm = cs.add_parser("mint", help="mint a token for another machine; prints the token file's path",
                       description="On the server box: a new token for NAME (letters, digits, - _ .). The server keeps its hash; the "
                                   "token is written to <secrets>/client-tokens/NAME.token (0600) and never printed. A NAME that already "
                                   "has a token is refused unless --rotate.")
    cm.add_argument("name")
    cm.add_argument("--rotate", action="store_true", help="replace the token NAME already has (the old file stops working)")
    cm.set_defaults(fn=cmd_client_mint)

    a = p.parse_args(argv)
    repair_xdg()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
