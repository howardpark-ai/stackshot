"""tools/frontdoor_switch.py: what the four scripts of a live switch to the front door share. Standard library only (Python 3.11+). Not a command.

The commands, all described in docs/front-door.md, "The live switch scripts":
  tools/frontdoor_preflight.py   the list that has to hold before the first step; read-only
  tools/frontdoor_snapshot.py    the snapshot (the way back) and the front door's secrets and members file
  tools/frontdoor_cutover.py     the cut-over as one run: it stops at the first failed check, and from the board's restart on it brings the board back by itself
  tools/frontdoor_undo.py        the way back to the single-user board on its old port

Every script that writes is a dry run unless it is given --apply, and none asks a question: what a person has to look at is printed as MANUAL lines, and
the exit code says so. No script commits or pushes anything. A secret value is never printed, never an argument of a program and never part of a message.

Environment:
  STACKSHOT_CONFIG              the instance's stackshot.toml (required)
  FRONTDOOR_PUBLIC_URL          the public address of the board (https://...); required by --apply of the cut-over and the undo
  FRONTDOOR_BACKUP_DIR          the folder of the board's daily backups (pre-flight, when --backup-dir is not given)
  FRONTDOOR_SNAPSHOT_ROOT       the folder the snapshots go into (default ~/.local/share/stackshot-runs/frontdoor-switch)
  FRONTDOOR_SECRETS_DIR         the folder of the front door's secrets (default ~/.config/stackshot/frontdoor)
  FRONTDOOR_SWITCH_CHECKOUT     the checkout whose install.sh, release.sh, git history and Python are used (default: the one this file is in)
  FRONTDOOR_SWITCH_PYTHON       the command that runs the front door's Python (default: uv run in that checkout with the server extra)
  FRONTDOOR_SWITCH_WINDOW       seconds the cut-over's checks have from the board's restart (default 300)
  FRONTDOOR_SWITCH_CHECK        seconds one check of the cut-over is asked again before it counts as failed (default 30)
  FRONTDOOR_SWITCH_UNDO_WINDOW  seconds the undo waits for the board's answers (default 120)
  FRONTDOOR_SWITCH_POLL         seconds between two asks (default 1)
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

TOOLS = Path(__file__).resolve().parent

# exit codes, the same for all four scripts
OK = 0              # passed, nothing left to look at (a dry run included)
FAILED = 1          # a check failed or the script refused; the board was not restarted by this run
CANNOT = 2          # the call cannot be run as asked
PENDING = 3         # every automated check passed; MANUAL checks are left for a person
ROLLED_BACK = 4     # the board is back on its old port on the saved config; the config revert is still a person's step
INCOMPLETE = 5      # the way back did not complete: a person is needed now

OLD_BOARD_PORT = 8020           # the board before the switch; the splitter takes this port at the cut-over
NEW_BOARD_PORT = 8021           # the board behind the front door
TEST_SPLITTER_PORT = 8025
DOOR_PORT = 8030
SIGNIN_PORT = 8031
PRE_FLIGHT_PORTS = (NEW_BOARD_PORT, TEST_SPLITTER_PORT, DOOR_PORT, SIGNIN_PORT)

WINDOW_SECONDS = 300            # from the board's restart, every check of the cut-over is green within this
CHECK_SECONDS = 30              # one check is asked again for at most this long
UNDO_WINDOW_SECONDS = 120
MIN_HOLD_MINUTES = 15           # the release hold has to outlast the cut-over's checks and a way back

BOARD_UNIT = "stackshot.service"
MINUTE_UNIT = "stackshot-minute.service"
SYNC_UNIT = "stackshot-portal-sync.service"
SPLITTER_UNIT = "stackshot-splitter.service"
FRONT_UNITS = ("stackshot-frontdoor.service", "stackshot-signin.service")
RESTORE_UNITS = (BOARD_UNIT, MINUTE_UNIT, SYNC_UNIT)          # the units the way back restarts, and the ones that get the override
OVERRIDE_NAME = "zz-frontdoor-rollback.conf"                  # a drop-in that points one of those units at the saved config

SNAPSHOT_ARCHIVE = "board.tar.gz"
SNAPSHOT_HEAD = "stackshot-head"
SNAPSHOT_NOTES = "config-notes.txt"

SWITCH_TABLES = ("behind_frontdoor", "frontdoor", "frontdoor_signin", "frontdoor_splitter")


class Usage(Exception):
    """A call that cannot be run as asked: the message says what to change. The scripts exit CANNOT with it."""


# ---------------------------------------------------------------- output

def emit(line: str = "") -> None:
    """Print a line. A reader that went away (a closed pipe, a dropped terminal) never stops a run that has the board in its middle."""
    try:
        print(line, flush=True)
    except (OSError, ValueError):
        sys.stdout = open(os.devnull, "w", encoding="utf-8")


def say(tag: str, name: str, detail: str = "") -> None:
    emit(f"{tag:<7} {name}" + (f": {detail}" if detail else ""))


def cannot(why: Exception) -> int:
    print(f"cannot run: {why}", file=sys.stderr, flush=True)
    return CANNOT


# ---------------------------------------------------------------- the environment

def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    return Path(os.path.expanduser(raw)).resolve() if raw else default


def _env_seconds(name: str, default: float) -> float:
    return float(os.environ.get(name) or default)


def checkout() -> Path:
    return _env_path("FRONTDOOR_SWITCH_CHECKOUT", TOOLS.parent)


def secrets_dir() -> Path:
    return _env_path("FRONTDOOR_SECRETS_DIR", Path.home() / ".config/stackshot/frontdoor")


def window_seconds() -> float:
    return _env_seconds("FRONTDOOR_SWITCH_WINDOW", WINDOW_SECONDS)


def check_seconds() -> float:
    return _env_seconds("FRONTDOOR_SWITCH_CHECK", CHECK_SECONDS)


def undo_window_seconds() -> float:
    return _env_seconds("FRONTDOOR_SWITCH_UNDO_WINDOW", UNDO_WINDOW_SECONDS)


def poll_seconds() -> float:
    return _env_seconds("FRONTDOOR_SWITCH_POLL", 1)


def public_url() -> str:
    return os.environ.get("FRONTDOOR_PUBLIC_URL", "").strip().rstrip("/")


def need_public_url() -> str:
    url = public_url()
    if not url:
        raise Usage("FRONTDOOR_PUBLIC_URL is not set: the public checks need the board's public address (https://...)")
    return url


def command(script: str, *args: str) -> str:
    """A shell line that runs one of these scripts with this run's environment: what a person (or a session) pastes."""
    names = ("STACKSHOT_CONFIG", "FRONTDOOR_PUBLIC_URL", "FRONTDOOR_SWITCH_CHECKOUT", "FRONTDOOR_SWITCH_PYTHON")
    env = [f"{n}={os.environ[n]}" for n in names if os.environ.get(n)]
    return shlex.join(["env", *env, "python3", str(TOOLS / script), *args])


# ---------------------------------------------------------------- programs

def run(argv: list[str], *, cwd: str | os.PathLike | None = None, timeout: float = 120, stderr: bool = True) -> tuple[int, str]:
    """(exit code, stdout + stderr). A program that is missing or cannot be started is 127, a timeout 124. Nothing is printed here.
    stderr=False: a program that succeeds gives its stdout alone (a failed one still gives both)."""
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return 124, f"no end within {timeout:.0f} s"
    except OSError as e:
        return 127, f"{argv[0]}: {e.strerror or e.__class__.__name__}"
    return p.returncode, (p.stdout or "") + ((p.stderr or "") if stderr or p.returncode != 0 else "")


def last_line(text: str) -> str:
    lines = [x.strip() for x in text.strip().splitlines() if x.strip()]
    return lines[-1] if lines else ""


def outcome(rc: int, out: str) -> tuple[bool, str]:
    return rc == 0, last_line(out) or f"exit {rc}"


def py_cmd() -> list[str]:
    """The Python the front door's own code runs with: the checkout's environment with the server extra."""
    raw = os.environ.get("FRONTDOOR_SWITCH_PYTHON", "").strip()
    if raw:
        return shlex.split(raw)
    return ["uv", "run", "--project", str(checkout()), "--locked", "--extra", "server", "python"]


def systemctl(*args: str, timeout: float = 120) -> tuple[bool, str]:
    return outcome(*run(["systemctl", "--user", *args], timeout=timeout))


def unit_enabled(unit: str) -> tuple[bool, str]:
    rc, out = run(["systemctl", "--user", "is-enabled", unit])
    state = last_line(out) or f"exit {rc}"
    return state in ("enabled", "enabled-runtime"), state


def unit_active(unit: str) -> tuple[bool, str]:
    rc, out = run(["systemctl", "--user", "is-active", unit])
    state = last_line(out) or f"exit {rc}"
    return state in ("active", "activating", "reloading"), state


def splitter_off(timeout: float = 120) -> tuple[bool, str]:
    """Disable and stop the splitter. What counts is the state afterwards: not running and not enabled (a unit that was never installed is both)."""
    _, line = systemctl("disable", "--now", SPLITTER_UNIT, timeout=timeout)
    running, state = unit_active(SPLITTER_UNIT)
    enabled, was = unit_enabled(SPLITTER_UNIT)
    ok = not enabled and not running and state in ("inactive", "failed", "unknown")
    return ok, f"{state}, {was}" if ok else f"{state}, {was} ({line})"


def install_units(co: Path) -> tuple[bool, str]:
    return outcome(*run([str(co / "install.sh"), "units"], cwd=co, timeout=300))


def config_repo(path: Path) -> Path | None:
    """The git checkout the config file lives in (the nearest folder above the file it leads to with a .git), or None."""
    real = path.resolve()
    for d in real.parents:
        if (d / ".git").exists():
            return d
    return None


def pull_config(path: Path) -> tuple[bool, str]:
    repo = config_repo(path)
    if repo is None:
        return False, "no git checkout holds the config"
    return outcome(*run(["git", "-C", str(repo), "pull", "--ff-only"], timeout=300))


def config_notes(co: Path) -> tuple[bool, list[str]]:
    """(whether they could be read, the config notes of the config as it is on disk now, one a line)."""
    # stdout alone: what uv or an import says on stderr is no note
    rc, out = run([*py_cmd(), "-c", 'from stackshot.core import config; print(*config.notes(), sep="\\n")'], cwd=co, timeout=300, stderr=False)
    if rc != 0:
        return False, [last_line(out) or f"exit {rc}"]
    return True, [x.rstrip() for x in out.splitlines() if x.strip()]


# ---------------------------------------------------------------- releases

def hold_state(co: Path) -> tuple[str, int, str]:
    """('active' | 'none' | 'unknown', minutes left, the line), from `release.sh hold --status`."""
    rc, out = run([str(co / "release.sh"), "hold", "--status"], cwd=co)
    lines = [x.strip() for x in out.splitlines() if x.strip()]
    for line in lines:
        if rc == 0 and line.startswith("releases are held"):
            m = re.search(r"\((\d+) min left\)", line)
            return "active", int(m.group(1)) if m else 0, line
        if rc == 0 and line.startswith("no hold on releases"):
            return "none", 0, line
    return "unknown", 0, last_line(out) or f"exit {rc}"


def queue_state(co: Path) -> tuple[str, str]:
    """('empty' | 'waiting' | 'unknown', the line), from `release.sh queue --list`."""
    rc, out = run([str(co / "release.sh"), "queue", "--list"], cwd=co)
    if rc != 0:
        return "unknown", last_line(out) or f"exit {rc}"
    lines = [x.strip() for x in out.splitlines() if x.strip()]
    if "release queue: empty" in lines and not any(x.startswith("paused:") for x in lines):
        return "empty", "release queue: empty"
    return "waiting", " | ".join(lines[:3]) or "no answer"


def release_running() -> tuple[bool | None, str]:
    """(True when a release unit runs, False when none does, None when it cannot tell), with the line."""
    rc, out = run(["systemctl", "--user", "list-units", "--state=active,activating", "--no-legend", "--plain", "stackshot-release-*"])
    if rc != 0:
        return None, f"systemctl exit {rc}"
    names = [x.split()[0] for x in out.splitlines() if x.strip()]
    return bool(names), (", ".join(names) if names else "none running")


# ---------------------------------------------------------------- the config

def config_path() -> Path:
    raw = os.environ.get("STACKSHOT_CONFIG", "").strip()
    if not raw:
        raise Usage("STACKSHOT_CONFIG is not set: point it at the instance's stackshot.toml")
    p = Path(os.path.abspath(os.path.expanduser(raw)))
    if not p.is_file():
        raise Usage(f"STACKSHOT_CONFIG names no file: {p}")
    os.environ["STACKSHOT_CONFIG"] = str(p)           # the programs run from the checkout: a path relative to here must reach them whole
    return p


def read_toml(path: Path) -> dict | None:
    """The config in `path`, or None when it cannot be read as one."""
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, ValueError):
        return None


def setting(cfg: dict | None, *keys: str):
    cur = cfg
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def zone(cfg: dict | None) -> ZoneInfo:
    """[instance] timezone, UTC without a usable one: the zone of a snapshot's name, of "today" and of a printed time."""
    try:
        return ZoneInfo(str(setting(cfg, "instance", "timezone") or "UTC"))
    except (ValueError, KeyError, OSError):
        return ZoneInfo("UTC")


def clock(cfg: dict | None, epoch: float) -> str:
    return datetime.fromtimestamp(epoch, zone(cfg)).strftime("%H:%M:%S %Z")


def backend(cfg: dict | None, name: str) -> dict:
    for b in setting(cfg, "frontdoor", "backends") or []:
        if isinstance(b, dict) and b.get("name") == name:
            return b
    return {}


def switched_checks(cfg: dict | None) -> list[tuple[str, bool]]:
    """What the one config save of the cut-over holds. Whether the sign-in service takes the portal's machine token is the owner's choice: only that it is answered."""
    door_id = setting(cfg, "frontdoor", "identity_secret_file")
    door_members = setting(cfg, "frontdoor", "members_file")
    return [
        (f"[server] port is {NEW_BOARD_PORT}", setting(cfg, "server", "port") == NEW_BOARD_PORT),
        ("[behind_frontdoor] identity_secret_file is the front door's", bool(door_id) and setting(cfg, "behind_frontdoor", "identity_secret_file") == door_id),
        ("[behind_frontdoor] members_file is the front door's", bool(door_members) and setting(cfg, "behind_frontdoor", "members_file") == door_members),
        ("[behind_frontdoor] board_name is main", setting(cfg, "behind_frontdoor", "board_name") == "main"),
        (f"[[frontdoor.backends]] main is the board on {NEW_BOARD_PORT}", backend(cfg, "main").get("url") == f"http://127.0.0.1:{NEW_BOARD_PORT}/mcp"),
        (f"[frontdoor_signin] board_verify_url is the board on {NEW_BOARD_PORT}",
         setting(cfg, "frontdoor_signin", "board_verify_url") == f"http://127.0.0.1:{NEW_BOARD_PORT}/frontdoor/verify"),
        ("[frontdoor_signin] accept_portal_token is answered (true or false)", isinstance(setting(cfg, "frontdoor_signin", "accept_portal_token"), bool)),
        (f"[frontdoor_splitter] listen_port is {OLD_BOARD_PORT}", setting(cfg, "frontdoor_splitter", "listen_port") == OLD_BOARD_PORT),
    ]


def single_user_checks(cfg: dict | None) -> list[tuple[str, bool]]:
    """What a config of the single-user board holds: a config before the switch, one with the cut-over reverted, and the saved config the way back may run on."""
    if cfg is None:
        return [("the config can be read", False)]
    return [
        (f"[server] port is {OLD_BOARD_PORT}", setting(cfg, "server", "port") == OLD_BOARD_PORT),
        (f"[frontdoor_splitter] listen_port is not {OLD_BOARD_PORT}", setting(cfg, "frontdoor_splitter", "listen_port") != OLD_BOARD_PORT),
        ("[behind_frontdoor] names no identity_secret_file and no members_file",
         setting(cfg, "behind_frontdoor", "identity_secret_file") is None and setting(cfg, "behind_frontdoor", "members_file") is None),
    ]


def failed(rows: list[tuple[str, bool]]) -> list[str]:
    return [name for name, ok in rows if not ok]


def other_differences(saved: dict | None, now: dict | None) -> list[str]:
    """The names (never the values) of the settings that differ between two configs outside what the switch itself changes."""
    out: list[str] = []
    a, b = saved or {}, now or {}
    for table in sorted(set(a) | set(b)):
        if table in SWITCH_TABLES or a.get(table) == b.get(table):
            continue
        x, y = a.get(table), b.get(table)
        if isinstance(x, dict) and isinstance(y, dict):
            out += [f"[{table}] {k}" for k in sorted(set(x) | set(y)) if x.get(k) != y.get(k) and (table, k) != ("server", "port")]
        else:
            out.append(f"[{table}]")
    return out


# ---------------------------------------------------------------- the way back's own files

def unit_dir() -> Path:
    return Path.home() / ".config/systemd/user"


def override_path(unit: str) -> Path:
    return unit_dir() / f"{unit}.d" / OVERRIDE_NAME


def overrides_present() -> list[Path]:
    return [p for p in map(override_path, RESTORE_UNITS) if os.path.lexists(p)]


def rollback_copy() -> Path:
    """Where the saved config is put for the board to run on: apart from the snapshot, so deleting a snapshot never takes the running board's config."""
    return Path.home() / ".config/stackshot/frontdoor-rollback/stackshot.toml"


def snapshot_config(snapshot: Path, cfg_path: Path) -> Path:
    return snapshot / cfg_path.name


# ---------------------------------------------------------------- HTTP

def http_code(url: str, method: str = "GET", timeout: float = 5) -> str:
    """The HTTP status of a request by curl, or "000" when none came (refused, timed out)."""
    _, out = run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", f"{max(1.0, timeout):.0f}", "-X", method, url], timeout=max(1.0, timeout) + 2)
    m = re.match(r"\d{3}", out.strip())
    return m.group(0) if m else "000"


def not_answering(code: str) -> bool:
    return code in ("000", "502", "503", "504")


def wait_code(url: str, want: str, seconds: float, *, method: str = "GET", again: Callable[[str], bool] = lambda code: True) -> tuple[bool, str]:
    """Ask until the answer is `want` (True) or `seconds` are over (False). An answer that `again` does not accept is final at once. → (passed, the last code)."""
    end = time.monotonic() + seconds
    while True:
        code = http_code(url, method, timeout=min(5.0, end - time.monotonic()))
        if code == want:
            return True, code
        if not again(code) or time.monotonic() >= end:
            return False, code
        time.sleep(max(0.0, min(poll_seconds(), end - time.monotonic())))


class Window:
    """A length of time from the moment it is made."""

    def __init__(self, seconds: float):
        self.seconds = seconds
        self.end = time.monotonic() + seconds
        self.end_epoch = time.time() + seconds

    def left(self) -> float:
        return self.end - time.monotonic()


# ---------------------------------------------------------------- files

def write_private(path: Path, data: bytes) -> None:
    """Put `data` at `path` in one step at mode 600: a reader sees the old file or the new one, never a part. Its folder must exist."""
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        try:
            os.fchmod(fd, 0o600)
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)


def new_private(path: Path, data: bytes) -> None:
    """Create `path` at mode 600 only when nothing is there (O_EXCL): an existing file is never replaced."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def mode_of(path: Path) -> int:
    return path.stat().st_mode & 0o777
