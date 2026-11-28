"""config.py — the instance config of this stackshot: every path, identity, rule and label that belongs to the setup rather
than to the code). The instance's file lives outside the code: it is found, in
order, at $STACKSHOT_CONFIG, ~/.config/stackshot/stackshot.toml, a stackshot.toml next to this file, and last the shipped
stackshot.example.toml next to this file — the defaults, enough for a client box that only needs [client] and the secrets
dir, and for the tests, which patch what they need. Stdlib only (tomllib), so the pane gate on every box reads it.

    from stackshot.core.config import CFG, get, path, state, secrets
    get("instance", "owner")            → "the owner"
    path("paths", "store")              → Path, ~ expanded
    state("site", "robots.txt")         → <paths.state>/site/robots.txt
    secrets("oauth.env")                → <paths.secrets>/oauth.env

CLI (for shell scripts; `bin/stackshot config ...`, or `python3 <checkout>/stackshot/core/config.py ...` where there is no uv):
                          stackshot config get instance.owner | path paths.store | state anchor-hub | secrets oauth.env
                          stackshot config file   → the config file in use
                          stackshot config check  → exit 0 when the file names no removed mode; otherwise the refusal line(s), exit 1
                                                     (importing this module does the same: see REMOVED)

Live reload: a long-running process calls reload(). The server does on SIGHUP, which systemd sends on
`systemctl --user reload` when stackshot-reload.path sees the file change; the client box's puller (fleet/puller.py) has no signal
and no unit: once per poll cycle it stats the file (a link followed, so a stackshot.toml that links into another repository counts)
and calls reload() when signature() differs from SIG, the file's signature as of the last read of it (set here, at import and in reload(), so a puller re-run in the same process, which keeps this module, still sees a change made since the config was loaded). A valid file replaces CFG at once and every reader
sees it at its next get(); a broken one is logged and the running config kept. The keys of RESTART_ONLY keep their running
value until the next restart. So a reader must never copy a setting into a module constant: read it where it is used.
"""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import math
import os
import re
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from stackshot import paths as _paths

HERE = _paths.ROOT      # the checkout: stackshot.example.toml and a stackshot.toml sit at its root
EXAMPLE = HERE / "stackshot.example.toml"


def _find() -> Path:
    env = os.environ.get("STACKSHOT_CONFIG") or os.environ.get("BOARD_MCP_CONFIG")
    if env:
        return Path(os.path.expanduser(env))
    for p in (Path(os.path.expanduser("~/.config/stackshot/stackshot.toml")), HERE / "stackshot.toml", EXAMPLE):
        if p.is_file():
            return p
    return EXAMPLE


PATH = _find()


def signature(p: Path | None = None) -> tuple | None:
    """What identifies the config file's content on disk: the resolved path and the device, inode, size and mtime of the file the path leads to (os.stat follows a link,
    so a stackshot.toml that links into another repository is watched at its target; a link pointed at another file changes the resolved path). None when it cannot be
    stat'ed (the file vanished for a moment)."""
    p = PATH if p is None else p
    try:
        st = os.stat(p)
        return (os.path.realpath(p), st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
    except OSError:
        return None


SIG: tuple | None = signature()      # the file's signature as of the last read of it (taken just BEFORE the read, so a change during it is seen at the next look); load() below at import, reload() after


def load(p: Path = PATH) -> dict[str, Any]:
    with open(p, "rb") as f:
        return tomllib.load(f)


CFG: dict[str, Any] = load()


def tz():
    """The instance's timezone (instance.timezone, default UTC as in the example): every time the board, the hub or a notice prints."""
    import zoneinfo
    return zoneinfo.ZoneInfo(str(get("instance", "timezone") or "UTC"))


def tz_abbr(when: Any = None) -> str:
    """The instance timezone's abbreviation (strftime %Z) at `when` (a datetime; a naive one is read in the instance zone), or
    now: the zone's abbreviation ("UTC" for UTC, "CET" for a zone that has one), the zone's own offset label where it has no abbreviation."""
    import datetime
    z = tz()
    when = datetime.datetime.now(z) if when is None else when.replace(tzinfo=z) if when.tzinfo is None else when.astimezone(z)
    return when.strftime("%Z") or str(z)


def tz_labels() -> list[str]:
    """Every abbreviation (strftime %Z) the instance timezone shows over a year (["CET", "CEST"]; ["UTC"]; ["+04"] for a zone with no abbreviation), for a text
    that may name the zone after a clock time ("at 03:00 CET")."""
    import datetime
    z = tz()
    out: list[str] = []
    for month in (1, 7):
        lab = datetime.datetime(2026, month, 1, 12, tzinfo=z).strftime("%Z") or str(z)
        if lab not in out:
            out.append(lab)
    return out


def get(*keys: str, default: Any = None, cfg: dict[str, Any] | None = None) -> Any:
    d: Any = CFG if cfg is None else cfg     # CFG read once: a reload in between never mixes two files in one answer
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return _hosts_leaf(d)      # a `host:<role>` word at the leaf (a string, or an item of a list) is the host it names now; see "host words" below


# ---------------------------------------------------------------- host words
# A setting that names a machine can name a ROLE instead: the string `host:<role>` (the role: letters, digits, `-`, `_`, `.`; a real host name never holds a colon, so
# nothing written before collides). The instance says how a role is looked up, so a machine that moves between boxes changes one record, not the config:
#     [hosts]
#     lookup = "/usr/local/bin/where-is {role}"   # a command, run WITHOUT a shell (shlex words, each `~`-expanded, {role} replaced inside the word); it prints the host on its first line
#     timeout = 5                                  # seconds one lookup may take
#     cache_seconds = 30                           # an answer is trusted this long
# `get()` resolves a word at the leaf it returns (a string, or each string of a list); `host(value)` resolves one value for a reader that took a whole section first.
# The lookup settings are read from the raw CFG, never through get(): resolving them cannot recurse. Nothing here raises. A role with no good answer (no lookup set, or the
# first lookup failed) leaves the word itself in place, never "" and never a guess: an unresolved word must fail where it is used (ssh to it fails, a machine list never
# matches it) rather than read as "this box" or "no host". After a good answer a later failed lookup keeps the last good value standing, and is tried again after 5 seconds.
HOST_RETRY_SECONDS = 5.0          # a failed lookup of a role is not tried again for this long (the last good value, if any, answers meanwhile)
_HOST_WORD = re.compile(r"host:([A-Za-z0-9_.][A-Za-z0-9._-]*)")       # the whole value; the role does not start with "-" (it becomes a word of the lookup's argv)
_HOST_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@-]*")      # what a lookup may print: one word of letters, digits and . _ @ - (a name, an alias, user@host), never starting with "-" (an ssh option); it reaches ssh and tool text
_HOST_MAX_OUT = 4096              # the most of a lookup's output that is read; more is a failure
_host_clock = time.monotonic      # tests patch this
_HOST_LOCK = threading.Lock()     # guards the three tables below, never held across a lookup
_HOST_GOOD: dict[tuple[str, str], tuple[str, float]] = {}      # (lookup, role) -> (host, when it was got)
_HOST_FAILED: dict[tuple[str, str], float] = {}                # (lookup, role) -> when its last lookup failed (a failure streak, until one succeeds)
_HOST_ROLE_LOCKS: dict[str, threading.Lock] = {}               # role -> the lock one lookup of that role runs under


def _host_role(value: Any) -> str | None:
    """The role of a host word (`host:<role>`, surrounding whitespace ignored), or None for any other value."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s.startswith("host:"):
        return None
    m = _HOST_WORD.fullmatch(s)
    return m.group(1) if m else None


def _hosts_leaf(d: Any) -> Any:
    """`d` with its host words resolved: a string, or the strings of a list; any other value (a table too) as it is."""
    if isinstance(d, str):
        return host(d)
    if isinstance(d, list) and any(_host_role(x) is not None for x in d):
        return [host(x) for x in d]
    return d


def _hosts_number(sec: dict[str, Any], key: str, default: float, zero: bool) -> float:
    v = sec.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")) or v < 0 or (v == 0 and not zero):
        return default
    return float(v)


def _host_lookup(tpl: str, role: str, timeout: float) -> tuple[str | None, str]:
    """Run the lookup once: (the host, "") or (None, why it failed). No shell: the command's words are split here, `~` expanded, and `{role}` is replaced inside the
    word, so the role (made of safe characters only) never reaches a shell. Bounded in time and in size: a lookup that outlasts `timeout` is killed with its process group,
    and at most _HOST_MAX_OUT bytes of its output are read (more is a failure)."""
    p = None
    reader = None
    try:
        words = shlex.split(tpl)
        if not any("{role}" in w for w in words):
            return None, "the lookup has no {role} in it"
        argv = [os.path.expanduser(w).replace("{role}", role) for w in words]
        p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
        got: list[bytes] = []
        stdout = p.stdout
        assert stdout is not None
        reader = threading.Thread(target=lambda: got.append(stdout.read(_HOST_MAX_OUT + 1)), daemon=True)
        t0 = time.monotonic()
        reader.start()
        reader.join(timeout)
        if reader.is_alive():                   # no end of output in time (a child may hold the pipe open too)
            return None, f"no answer in {timeout:g} s"
        out = got[0] if got else b""
        if len(out) > _HOST_MAX_OUT:
            return None, f"more than {_HOST_MAX_OUT} bytes of output"
        try:
            p.wait(timeout=max(0.05, timeout - (time.monotonic() - t0)))
        except subprocess.TimeoutExpired:
            return None, f"no answer in {timeout:g} s"
        if p.returncode != 0:
            return None, f"exit {p.returncode}"
        lines = out.decode("utf-8", "replace").splitlines()
        name = lines[0].strip() if lines else ""
        if not name or _HOST_NAME.fullmatch(name) is None:
            return None, "the first line is not one host name"
        return name, ""
    except Exception as e:                  # a command not found, an unreadable template, anything else: a failure, never an exception
        return None, type(e).__name__
    finally:
        if p is not None:
            _host_end(p, reader)


def _host_end(p: "subprocess.Popen[bytes]", reader: "threading.Thread | None") -> None:
    """End the lookup we started, whatever came of it: its own process group (it was made with start_new_session), so a child it left behind goes too; never a process found by name.
    Only a lookup still running, or one whose output a child still holds open, is ended: a finished and reaped one has no group to signal (its pid may be another process's by now).
    Then the reader is joined and the pipe closed."""
    if p.poll() is None or (reader is not None and reader.is_alive()):
        try:
            if hasattr(os, "killpg"):
                os.killpg(p.pid, signal.SIGKILL)
            else:
                p.kill()
        except OSError:
            pass
    try:
        p.wait(timeout=2)
    except Exception:
        pass
    if reader is not None:
        reader.join(2)
    for f in (p.stdout, p.stdin, p.stderr):
        try:
            if f: f.close()
        except Exception:
            pass


def _host_resolve(role: str) -> str | None:
    """The host a role names now, or None when there is no good answer: no lookup set, or no lookup of it has worked yet. Cached per role for `cache_seconds`; a failed
    lookup keeps the last good value and is not repeated for HOST_RETRY_SECONDS; one lookup of a role at a time, and no lock is held across it but that role's."""
    sec = CFG.get("hosts") if isinstance(CFG, dict) else None
    sec = sec if isinstance(sec, dict) else {}
    tpl = sec.get("lookup")
    if not isinstance(tpl, str) or not tpl.strip():
        return None
    key = (tpl, role)
    ttl = _hosts_number(sec, "cache_seconds", 30.0, True)

    def peek() -> tuple[bool, str | None]:
        """(settled, the answer): settled = no lookup is due, the answer is the cached value, or the last good one while a failed lookup rests."""
        now = _host_clock()
        with _HOST_LOCK:
            good, failed = _HOST_GOOD.get(key), _HOST_FAILED.get(key)
        if good is not None and 0 <= now - good[1] < ttl:
            return True, good[0]
        if failed is not None and 0 <= now - failed < HOST_RETRY_SECONDS:
            return True, good[0] if good else None
        return False, good[0] if good else None

    done, val = peek()
    if done:
        return val
    with _HOST_LOCK:
        lock = _HOST_ROLE_LOCKS.setdefault(role, threading.Lock())
    with lock:
        done, val = peek()              # another thread may have asked while this one waited
        if done:
            return val
        got, why = _host_lookup(tpl, role, _hosts_number(sec, "timeout", 5.0, False))
        with _HOST_LOCK:
            if got is not None:
                _HOST_GOOD[key] = (got, _host_clock())
                _HOST_FAILED.pop(key, None)
                return got
            first = key not in _HOST_FAILED
            _HOST_FAILED[key] = _host_clock()
        if first:                       # one line a failure streak, the role and the reason, never the lookup's output
            print(f"config hosts: the lookup of role {role!r} failed ({why}); " + ("the last good host stays" if val else "the word stays as written"), file=sys.stderr, flush=True)
        return val


def _host_reset() -> None:
    """A reload: every cached answer is due again (a lookup runs at the next read), and the failure marks go; the last good hosts stay, so a lookup that fails after a reload still has one
    to answer with. The cache key holds the lookup command, so a changed command never reuses another command's answer."""
    with _HOST_LOCK:
        for k, (v, _) in list(_HOST_GOOD.items()):
            _HOST_GOOD[k] = (v, float("-inf"))
        _HOST_FAILED.clear()


def host(value: Any) -> Any:
    """`value` as the host it names: a `host:<role>` word is looked up per [hosts] (cached); any other value, and a word with no good answer, comes back unchanged. Never raises."""
    role = _host_role(value)
    if role is None:
        return value
    try:
        got = _host_resolve(role)
    except Exception:
        got = None
    return got if got else value


def path(*keys: str, default: str | None = None) -> Path:
    v = get(*keys, default=default)
    if v is None:
        raise KeyError(".".join(keys))
    return Path(os.path.expanduser(str(v)))


def paths(*keys: str) -> list[Path]:
    """A config key holding a list of paths (a bare string counts as a one-item list), each `~`-expanded; absent or empty = []."""
    v = get(*keys)
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        return []
    return [Path(os.path.expanduser(x)) for x in v if isinstance(x, str) and x.strip()]


def state(*parts: str) -> Path:
    return path("paths", "state").joinpath(*parts)


def secrets(*parts: str) -> Path:
    return path("paths", "secrets").joinpath(*parts)


def page_dirs() -> list[str]:
    """[pages] dirs: the sub-directories of the pages checkout (paths.brain) that hold project pages, in order; a bare slug
    names a page in the FIRST one. Default ["projects"]; an instance with more lists them (the example file)."""
    v = get("pages", "dirs")
    if isinstance(v, str):
        v = [v]
    out = [str(d).strip().strip("/") for d in (v or []) if str(d).strip().strip("/")]
    return out or ["projects"]


def page_dirs_re() -> str:
    """The page dirs as one non-capturing regex alternation, e.g. (?:projects|infra)."""
    import re
    return "(?:" + "|".join(re.escape(d) for d in page_dirs()) + ")"


def gbrain_bin() -> str:
    """[gbrain] bin: the gbrain command line (rename_page.py, page_debt.GbrainIO, the router's timeline notes). "gbrain" (a name found on PATH)
    by default; a path may start with ~. Read at import by rename_page.py: a change takes a restart. Only a "gbrain" flavor of pages uses it."""
    v = str(get("gbrain", "bin") or "").strip()
    return os.path.expanduser(v) if v else "gbrain"


def copy_project_lines() -> bool:
    """[pages] copy_project_lines: whether stackshot copies a project's record (name, status, agents) onto its page's `display-name:`, `status:` and `agents:`
    lines after a project verb. True unless the key is the boolean false: the one switch that retires the copy on every brain (a shared brain's pages never get
    it, whatever this says: brains.shared_refusal). It stops the copied lines only: a new project's page is still made (`make_page`) on a brain that is not marked shared."""
    return get("pages", "copy_project_lines") is not False


def page_flavor() -> str:
    """[pages] flavor: how a session is told to update its page. "gbrain" = through gbrain's tools (add_timeline_entry,
    get_page/edit_page/put_page); "plain" (default) = edit the markdown file in the pages checkout, commit and push."""
    v = str(get("pages", "flavor") or "plain").strip().lower()
    return v if v in ("plain", "gbrain") else "plain"


def ask_leaves_on() -> bool:
    """[ask] leaves: true (the default) lets the server take an ask off the owner's move when its author's write is, whole, one plain sentence saying it is wrong (ask_leaves.py); a dropped dependency only reminds its author. false = never removes: the
    reminder and the ask-time check on the owner's notes still show, nothing is taken off his move."""
    return get("ask", "leaves", default=True) is not False


def ask_refuse_after() -> str:
    """[ask] refuse_after: the date (YYYY-MM-DD in the instance timezone) from which a needs=decision item without an ask
    line is refused rather than nagged. "" (the default) = never refuse, nag only. A value
    that is not a date reads as "" (nag)."""
    import datetime
    v = get("ask", "refuse_after")
    if not v:
        return ""
    try:
        return datetime.date.fromisoformat(str(v).strip()).isoformat()
    except ValueError:
        return ""


def ask_refuse_link_prefixes() -> tuple[str, ...]:
    """[ask] refuse_link_prefixes: URL prefixes whose pages are too long to decide from. A write that sets an ask (or an option) holding a link that starts with one is refused (model/decision_gates.py
    `_gate_ask_links`). A list, or one string; an entry that is not an http(s) URL is ignored, so is anything else. Empty (the default) = nothing refused. Read at each use: a reload is live."""
    v = get("ask", "refuse_link_prefixes")
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        return ()
    return tuple(t for t in (x.strip() for x in v if isinstance(x, str)) if re.match(r"(?i)https?://[^\s/]+", t) and not re.search(r"\s", t))


def board_check_mode() -> str:
    """[board_check] mode: the end-of-turn board check (pages.py check). "block" = a turn that
    did real work while its session owns open items it did not touch is asked once, at its Stop, to update or confirm them or
    to say `Board: no change, <reason>`; "note" = the same question kept for the next prompt instead of holding the turn (the later phase); "off" (the default) = never. Any other value reads as "off"."""
    v = str(get("board_check", "mode") or "off").strip().lower()
    return v if v in ("off", "block", "note") else "off"



# The temporary-directory prefix of the router's own `claude -p` call (router.run_call; the page-debt call shares it). The
# puller (puller.sessions) skips a registry record that lives in such a directory, so the call is never a client session.
ROUTER_CWD_PREFIX = "stackshot-router-"

AUDIT_AGENT = "my-audit"
AUDIT_SENDER = "stackshot audit"      # the label the audit's cue, findings and held notes are sent as (audit_run.SENDER)
AUDIT_PROJECT = "demo/board"
AUDIT_AT = "05:00"


def audit_enabled() -> bool:
    """[audit] enabled: the daily board audit (audit.py). true = install.sh installs its timer and
    the server answers POST /audit/now with a cue to [audit] agent; false (the default) = no timer, and a cue is refused (404)."""
    v = get("audit", "enabled")
    return v is True or str(v).strip().lower() in ("true", "1", "yes")


def background_agent_enabled() -> bool:
    """[background_agent] enabled: off by default (an instance whose fleet tool creates no agents leaves it off); read at each use. The one reading: the want for a background agent (service/background_want.enabled)
    and the router's call to it ask it first, so a switch that is off costs no lookup."""
    v = get("background_agent", "enabled")
    return v is True or str(v).strip().lower() in ("true", "1", "yes", "on")


def is_audit_sender(who: Any) -> bool:
    """Is this sender label the audit's own: AUDIT_SENDER, or the [audit] agent's name? A label may carry a uuid suffix or a script's "(a script on <machine>)" (`name (…)`) or a bracketed tag (`name [abc]`):
    only the name before it counts, and it must equal one of the two exactly (a label that merely contains them is not the audit's). A session id is no label: the caller resolves it to the session's name first
    and asks again. The router's want for a background agent and the message tool's both ask this, on the raw label (a script's label is blanked for other tests), so the two cannot drift."""
    name = re.split(r"\s*[(\[]", str(who or "").strip(), maxsplit=1)[0].strip().casefold()
    return bool(name) and name in {AUDIT_SENDER.casefold(), audit_agent().casefold()}


def audit_agent() -> str:
    """[audit] agent: the Claude Code session that runs the audit and writes its run record; a cue is pushed to it.
    Default "my-audit"."""
    return str(get("audit", "agent") or "").strip() or AUDIT_AGENT


def audit_project() -> str:
    """[audit] project: the project sala's Agents tab files the audit timer under (<scope>/<project>; install.sh puts it in the unit's X-Project line). Default "demo/board"."""
    return str(get("audit", "project") or "").strip() or AUDIT_PROJECT


def audit_at() -> list[str]:
    """[audit] at: the times of day of the scheduled audit, each "HH:MM" in the [instance] timezone, sorted and without repeats (the timer's
    OnCalendar lines and audit.next_run). The key takes one "HH:MM" string (a run a day, as it always did) or a list of them (a run at each
    time). An entry that is not a time of day is left out; with none left, the default ["05:00"]."""
    v = get("audit", "at")
    out = set()
    for x in (v if isinstance(v, (list, tuple)) else [v]):
        m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", str(x or "").strip())
        if m:
            out.add(f"{int(m.group(1)):02d}:{m.group(2)}")
    return sorted(out) or [AUDIT_AT]


AUDIT_MODES = ("script", "agent")
AUDIT_ORPHAN_MODES = ("apply", "report", "off")
AUDIT_WAIT_END_MODES = ("fix", "ask", "off")
AUDIT_WAIT_END_SETTLE_MINUTES = 60.0      # an item last written less than this long ago is left to its mover before the wait-end rule fixes anything (wait_end.py)
AUDIT_MAX_CALLS = 40
AUDIT_MAX_MINUTES = 100
AUDIT_MAX_MINUTES_CEIL = 110      # the unit's TimeoutStartSec is 2 h; a longer setting reads as this
AUDIT_THRESHOLD = 5
AUDIT_REMIND_HOURS = 6.0               # a ten-minute finding nobody answered is sent again this long after its last send (audit_run.split_sent)
AUDIT_FRONT_STEP_MOVE_HOURS = 3.0      # a front agent's step that stays stuck-elsewhere this long moves to the item's mover (front_step.py)
AUDIT_BUILDER = "my-engineer"
AUDIT_MAIN = "my-main"
REPORT_TO = "projects/example"        # the stand-in page the audit's summary and a release's report go to until an instance names its own


def audit_mode() -> str:
    """[audit] mode: who runs the audit. "script" (the default) = audit_run.py reads the board in code and makes one `claude -p` call per suspect item; "agent" = the old way,
    one cue line pushed to the audit agent ([audit] agent). Switching back to "agent" is the rollback; a value that is neither reads as the default."""
    v = str(get("audit", "mode") or "").strip().lower()
    return v if v in AUDIT_MODES else "script"


def _audit_int(key: str, default: int, low: int = 0) -> int:
    v = get("audit", key)
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return n if isinstance(v, (int, str)) and not isinstance(v, bool) and n >= low else default


def audit_max_calls() -> int:
    """[audit] max_calls: the most model calls one script run makes (one per suspect item, one at a time); the suspects past it wait for the next run. Default 40; 0 = no call."""
    return _audit_int("max_calls", AUDIT_MAX_CALLS)


def audit_max_minutes() -> int:
    """[audit] max_minutes: the wall-clock a script run may spend on model calls; once this many minutes have passed since the run started, no new call is begun (the suspects left wait for the
    next run) and the record says so. Default 100, kept under the audit unit's 2 h TimeoutStartSec: a value above 110 reads as 110, one below 1 as the default."""
    return min(_audit_int("max_minutes", AUDIT_MAX_MINUTES, 1), AUDIT_MAX_MINUTES_CEIL)


def audit_threshold() -> int:
    """[audit] threshold: a run that finds at least this many findings of one check sends the builder one message naming the check and the items. Default 5; a value below 1 reads as the default."""
    return _audit_int("threshold", AUDIT_THRESHOLD, 1)


def audit_front_step_move_hours() -> float:
    """[audit] front_step_move_hours: how many hours a step held by a front agent (or a retired session) may stay the first open step of an item another session moves, with the stuck-elsewhere finding up, before the
    ten-minute filing pass rewords it to the item's mover (front_step.py). Default 3; 0 = never moves one (the clocks are not kept either). A number (an integer or a decimal); anything else, a negative number or a boolean reads as the default."""
    v = get("audit", "front_step_move_hours")
    if isinstance(v, bool) or v is None or v == "":
        return AUDIT_FRONT_STEP_MOVE_HOURS
    try:
        n = float(v)
    except (TypeError, ValueError):
        return AUDIT_FRONT_STEP_MOVE_HOURS
    return n if n >= 0 and n == n and n != float("inf") else AUDIT_FRONT_STEP_MOVE_HOURS


def audit_remind_hours() -> float:
    """[audit] remind_hours: how many hours a finding of the ten-minute passes that its item has not answered (no write since) waits before it is sent again, in words that mark it as a later try, up to
    audit_run.REMIND_TRIES sends and then once to the project's builder as unmoved. Default 6; 0 = once only, as before. A number; anything else, a negative number or a boolean reads as the default."""
    v = get("audit", "remind_hours")
    if isinstance(v, bool) or v is None or v == "":
        return AUDIT_REMIND_HOURS
    try:
        n = float(v)
    except (TypeError, ValueError):
        return AUDIT_REMIND_HOURS
    return n if n >= 0 and n == n and n != float("inf") else AUDIT_REMIND_HOURS


def audit_wait_end() -> str:
    """[audit] wait_end: what the ten-minute filing pass does with an open item whose next line waits for something nothing tells the item has happened (wait_end.py): "fix" (the default) sets the wait the
    line names where the server can (after, an event wait, an anchor wait, a step proof) and asks the mover about the rest, "ask" only asks the mover, "off" makes no such check. Anything else reads as the default."""
    v = str(get("audit", "wait_end") or "").strip().lower()
    return v if v in AUDIT_WAIT_END_MODES else "fix"


def audit_wait_end_settle_minutes() -> float:
    """[audit] wait_end_settle_minutes: minutes since an item's last write before the wait-end rule fixes anything on it (a mover still at work on its next is left alone). Default 60; 0 = no wait. A number;
    anything else, a negative number or a boolean reads as the default."""
    v = get("audit", "wait_end_settle_minutes")
    if isinstance(v, bool) or v is None or v == "":
        return AUDIT_WAIT_END_SETTLE_MINUTES
    try:
        n = float(v)
    except (TypeError, ValueError):
        return AUDIT_WAIT_END_SETTLE_MINUTES
    return n if n >= 0 and n == n and n != float("inf") else AUDIT_WAIT_END_SETTLE_MINUTES


def audit_hourly_line() -> bool:
    """[audit] hourly_line: the hourly audit line (audit/hourly.py): an item on an agent with no activity for 45 minutes gets one line saying what the audit verified. Default true (it replaces the 45-minute news ask); a TOML false, or any value that is not a TOML true, switches it off, read at use."""
    return get("audit", "hourly_line", default=True) is True


def model_busy_hold_guard() -> bool:
    """[model] busy_hold_guard (default true): the refusal of a hold an item's mover sets while one of its own running subagents, or a running release of a pull request tied to the item, is tied to that item (gates.gate_busy_hold). false = the check never runs. Read live, as `wait_guard_on` is."""
    v = get("model", "busy_hold_guard")
    return True if v is None else (v not in (False, 0) and str(v).strip().lower() not in ("false", "no", "off", "0"))


def model_queued_behind() -> bool:
    """[model] queued_behind: a mover busy on another item reads waiting, queued behind that item, not on agent (model/queued.py). Default false; only a TOML true switches it on, read at use."""
    return get("model", "queued_behind", default=False) is True


def audit_hand_idle() -> bool:
    """[audit] hand_idle: an item the hourly audit marked idle (nothing verified) goes to a free builder and the project's -main agent is told (audit/hand_idle.py). Default true (it is the net under the hourly line); a TOML false, or any value that is not a TOML true, switches it off, read at use."""
    return get("audit", "hand_idle", default=True) is True


AUDIT_BUSY_TELL_HOURS = 4.0


def audit_busy_tell() -> bool:
    """[audit] busy_tell: an item on an agent whose hourly audit lines have said only "the mover's pane is in a turn" for `busy_tell_hours` with no other sign of progress tells the project's -main agent once (audit/busy_tell.py); an item a front agent holds
    that has had only hourly lines for that long tells that front agent itself once. Never the owner. Default true; a TOML false, or any value that is not a TOML true, switches it off, read at use."""
    return get("audit", "busy_tell", default=True) is True


def audit_busy_tell_hours() -> float:
    """[audit] busy_tell_hours: how long a busy stretch lasts before it is told. Default 4, never under 1; a number is taken, anything else (a boolean, text, a non-finite number) reads as the default. Read at use."""
    v = get("audit", "busy_tell_hours")
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
        return AUDIT_BUSY_TELL_HOURS
    return max(1.0, float(v))


AUDIT_BALANCE_MINUTES = 10.0


def audit_balance() -> bool:
    """[audit] balance: an item not started, or queued behind its mover's other item, that has waited `balance_minutes` goes to the builder of its own project with the fewest open items (never another project's), and the mover it left is told to disregard it
    (audit/hand_idle.py, audit_ticks._balance_tick). Default true; a TOML false, or any value that is not a TOML true, switches it off, read at use."""
    return get("audit", "balance", default=True) is True


def audit_balance_minutes() -> float:
    """[audit] balance_minutes: how long an item waits, not started or queued, before the balancer moves it. Default 10, never under 1; a number is taken, anything else (a boolean, text, a non-finite number) reads as the default. Read at use."""
    v = get("audit", "balance_minutes")
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
        return AUDIT_BALANCE_MINUTES
    return max(1.0, float(v))


def audit_orphan_handover() -> str:
    """[audit] orphan_handover: what the audit does with an open item whose mover is gone (successor.py): "report" (the default for the first week of use) only lists it, "apply" hands it to the closest live agent, "off" makes no check.
    A value that is none of these reads as the default."""
    v = str(get("audit", "orphan_handover") or "").strip().lower()
    return v if v in AUDIT_ORPHAN_MODES else "report"


def registry_audit_send() -> bool:
    """[registry_audit] send: whether the daily run sends the project registry check's findings (tools/registry_report.py) to the agents they are for, one message per agent a day. False (the default, and the
    reading of any value that is not the boolean true): the findings are on the run record and `audit.py registry` prints them, nobody is messaged."""
    return get("registry_audit", "send") is True


def registry_keeper_debts() -> bool:
    """[registry_audit] keeper_debts: whether the project registry check also reports the keeper-mark debts (keeper-not-listed, keeper-two-marks, keeper-retired, keeper-not-derived, keeper-page-ignored for a sub-page mark:
    tools/registry_report.py). False (the default, and the reading of any value that is not the boolean true): the check reports none of them, so nobody who edits a page is told of a mark's problem
    before the mark is put on projects on purpose (the stage that sets marks turns it on)."""
    return get("registry_audit", "keeper_debts") is True


def audit_builder() -> str:
    """[audit] builder: the session a tripped threshold, and an unmoved finding or the unmoved digest of a project with no builder of its own, is sent to. A front-only project (anchors.front_only) is the exception: its -main agent takes those (audit_run.Env.chase_of), and this session only when that agent cannot be named. Default "my-engineer"."""
    return str(get("audit", "builder") or "").strip() or AUDIT_BUILDER


def audit_main() -> str:
    """[audit] main: the -main agent that receives the findings addressed to the owner (marked `[for <owner>]`) and the run's summary. Default "my-main"."""
    return str(get("audit", "main") or "").strip() or AUDIT_MAIN


_REPORT_SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*")


def _report_slug(section: str, key: str) -> str:
    """The page key (or session name) set at [section] key, or REPORT_TO when the key is absent, empty or not shaped like one (letters, digits, dots, hyphens and underscores, "/" between the parts)."""
    v = get(section, key)
    v = v.strip() if isinstance(v, str) else ""
    return v if _REPORT_SLUG.fullmatch(v) else REPORT_TO


def audit_summary_to() -> str:
    """[audit] summary_to: the page key (or session name) the summary of each audit run is sent to (audit_run). Default "projects/example", the stand-in; a value that is not
    a page key or session name reads as the default (notes() says so)."""
    return _report_slug("audit", "summary_to")


def publish_host_refusal(argv: list[str], address: Callable[[], str] | None = None, cfg: dict[str, Any] | None = None) -> str:
    """The refusal line of the publisher on a box that is not the server host, or "" when it may publish here: on the server host, on an install whose config names no server host (a one-box or a fresh
    install), and when the check itself cannot run. The publisher renders the board from this box's own copy of the store and its own state, commits it and pushes it, so a copy on another box would go
    out over the live board. The decision is `server_host_refusal`'s (an unresolved host word refuses: it is never read as this box). `argv`: the publisher's words, said back as the command to run on
    the server (`record_host_where`); `address`: asked only on a refusal that has no host name to give, for the address the server answers at ("" = none known)."""
    try:
        why, h = _server_host_decision(cfg)
    except Exception:  # noqa: BLE001
        return ""
    if not why:
        return ""
    command = "~/stackshot/bin/stackshot publish"
    where = record_host_where(command, argv, cfg)
    how = f"run it there: `{where}`" if where.startswith("ssh ") else f"run it on the server host: `{command} {shlex.join(argv)}`"
    if why == "other":
        says = f"[release] deploy_ssh says the server runs on {h} (if that is another name for this box, set deploy_ssh to this box's hostname)"
    elif why == "unresolved":
        says = f"[release] deploy_ssh is the host word {h} and its [hosts] lookup did not resolve, so it names no box this one can be (fix the lookup, or name the host)"
    else:
        says = "[server] box = false says the server runs on another box"
    at = address() if address and why != "other" else ""
    return (f"publish: refused on {socket.gethostname()}, which is not the server host: {says}{f'; the server answers at {at}' if at else ''}. "
            f"Nothing was fetched, written, committed or pushed; {how}")


def release_report_to() -> str:
    """[release] report_to: the page key (or session name) release.sh sends its report of each release to (green or red, the PR, the commit, what was restarted), and names in the line it prints when
    a release starts. Default "projects/example", the stand-in; a value that is not a page key or session name reads as the default (notes() says so)."""
    return _report_slug("release", "report_to")


def release_codex_review() -> bool:
    """[release] codex_review (default true): whether release.sh starts `salamander codex-review <repo> <pr>`, a read-only review of the PR by another model that is posted on the PR as a comment, for each single-PR release
    (started in a user unit of its own, never waited for, never able to fail or delay a release). false, "false", "no", "off" or "0" = not started. SALA_CODEX_REVIEW (the same words, any case, surrounding whitespace ignored) in the environment of a direct
    `release.sh --run` call turns it off as well. Read by release.sh at each release."""
    v = get("release", "codex_review")
    return True if v is None else (v not in (False, 0) and str(v).strip().lower() not in ("false", "no", "off", "0"))


def release_suitemap_warm() -> list[str]:
    """[release] suitemap_warm_cmd: the command, as words, that release.sh starts (detached, never waited for) after it deploys a merge: run in a checkout of the merge commit, it builds the
    suite picker's index of that commit where picks are made (see tests/suitemap.py warm), so the first pick after the merge loads it. "" (the default) = nothing is started. Never able to fail or delay a release."""
    import shlex
    try:
        return shlex.split(str(get("release", "suitemap_warm_cmd") or ""))
    except ValueError:
        return []


def release_deploy_ssh() -> str:
    """[release] deploy_ssh: the ssh host (an alias of ~/.ssh/config, or [user@]host) release.sh runs deploy.sh on, over `ssh -o BatchMode=yes <host>`, in the checkout `~/stackshot` there, for the box that runs release.sh
    while the server runs on another box. After a deploy there release.sh moves its own checkout to the same commit (a fast-forward, or a reset for a rollback) and restarts only the puller; a checkout that cannot follow (local changes) pauses the release queue and reports the release red. "" (the default) = the deploy runs
    here, as on a one-box install. A value that names this box (its own name, short name or a loopback name or address; a host word that resolves to it) reads as "" too: the box that runs release.sh is the one
    the deploy runs on already, unless the value has a user@ part that is not the user running release.sh (then the deploy goes over ssh as that user). `~/.ssh/config` is not read for this: this box's name wins over an ssh alias spelled the same. A value that cannot be checked (the
    agentbox check fails to import or run) is kept: the deploy goes over ssh rather than locally. release.sh checks the value is a host name and refuses the deploy otherwise."""
    try:
        why, h = _server_host_decision()
    except Exception:
        h = get("release", "deploy_ssh")
        return h.strip() if isinstance(h, str) and h.strip() else ""
    if why:
        return h
    if h and "@" in h:
        import getpass
        try:
            me = getpass.getuser()
        except Exception:
            return h
        if h.rsplit("@", 1)[0] != me:
            return h
    return ""


def _server_host_decision(cfg: dict[str, Any] | None = None) -> tuple[str, str]:
    """Whether this box is the server host, as (reason, deploy_ssh): reason "" when it is (or when the config names no server host at all), "unresolved" (deploy_ssh is a host word whose [hosts] lookup
    did not resolve), "other" (deploy_ssh names another box) or "box_false" (`[server] box = false` and no host named). The rules are `server_host_refusal`'s; the callers build their own wording from the reason."""
    from stackshot.core import agentbox
    h = get("release", "deploy_ssh", cfg=cfg)
    h = h.strip() if isinstance(h, str) else ""
    if h and _host_role(h) is not None:
        return "unresolved", h
    if h and not agentbox.is_this_box(h):
        return "other", h
    if not h and server_box(cfg) is False:
        return "box_false", h
    return "", h


def server_host_refusal(cfg: dict[str, Any] | None = None) -> str:
    """Why this box is not the instance's server host, as one line, or "" when it is (or when the config names no server host at all, so a fresh install is not refused). install.sh `units`
    asks it once, before it touches a unit. The config names the server host in two places: `[release] deploy_ssh` (the host the server runs on, for a box that only runs release.sh; a host
    word resolves to the host it names now) and `[server] box = false` (this box was told it is not the server box, as INSTALL.md's "Moving the server to another box" sets on a box that
    only runs sessions). A host that names this box (its own name or short name, a loopback name or address) is the server host; any other is not, an alias of ~/.ssh/config or an address of this box
    included (the check makes no lookup of its own). A host word whose lookup does not resolve stays a word, so it names no box this one can be: refused, and the line says the lookup did not resolve.
    `deploy_ssh` naming another box wins over `[server] box = true`. `[server] box = true` and no host named both leave the box alone. The caller treats a check that cannot run at all (a config that cannot be read)
    as no refusal."""
    why, h = _server_host_decision(cfg)
    me = socket.gethostname()
    if why == "unresolved":
        return f"this box ({me}) is not the server host: [release] deploy_ssh is the host word {h} and its [hosts] lookup did not resolve, so it names no box this one can be (fix the lookup, or name the host)"
    if why == "other":
        return f"this box ({me}) is not the server host: [release] deploy_ssh names {h}, so the server's units belong there (an alias or an address of this box is not recognized: name this box by its hostname)"
    if why == "box_false":
        return f"this box ({me}) is not the server host: [server] box = false says the server runs on another box"
    return ""


def record_host_where(command: str, argv: list[str], cfg: dict[str, Any] | None = None) -> str:
    """Where a tool that reads or writes the project record must run when this box may not run it, or "" when it may run here (the server host, an install whose config names no server host, or a check
    that cannot run: a config that cannot be read). The ssh form `ssh <host> '<command> <argv>'`, the host being [release] deploy_ssh when that is a plain host word, else "on the server box".
    `command` is the program as the record host runs it (`python3 ~/stackshot/stackshot/tools/project.py`, `~/stackshot/bin/stackshot keeper-mark`)."""
    try:
        why, h = _server_host_decision(cfg)
    except Exception:  # noqa: BLE001
        return ""
    if not why:
        return ""
    ok = bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._@-]*", h)) and _host_role(h) is None
    return f"ssh {h} " + shlex.quote(f"{command} {shlex.join(argv)}".strip()) if ok else "on the server box"


def record_host_refusal(command: str, argv: list[str], cfg: dict[str, Any] | None = None) -> str:
    """The refusal line of a tool that reads or writes the project record, off the server box, or "" when it may run here. The record lives on the server box; a copy on another box (a client's
    checkout of the store) can be hundreds of commits behind, so a dry run there plans from old state and an --apply writes the old copy over the live record. The line names where to run it
    (`record_host_where`). The decision is `server_host_refusal`'s, the wording is not: install.sh `units` words it for the server's units, this for the record. The caller skips this check when it was
    pointed at a copy on purpose (--store DIR, a rehearsal)."""
    try:
        why, h = _server_host_decision(cfg)
    except Exception:  # noqa: BLE001
        return ""
    if not why:
        return ""
    me = socket.gethostname()
    if why == "other":
        head = f"this box ({me}) is not the server host: [release] deploy_ssh names {h}, where the project record lives (if {h} is another name for this box, set deploy_ssh to this box's hostname)"
    else:
        head = server_host_refusal(cfg)
    return (f"{head}; its copy of the project record may be behind the live one, so nothing is read or written here (a dry run would plan from old state, an --apply would write it over the live record). "
            f"Run it where the record is: {record_host_where(command, argv, cfg)}")


def report_notes(cfg: dict[str, Any] | None = None) -> list[str]:
    """Lines for a [audit] summary_to or [release] report_to that is set and cannot be used (see _report_slug): the default stands in its place, so the reports would go to the stand-in page."""
    out: list[str] = []
    for section, key in (("audit", "summary_to"), ("release", "report_to")):
        v = get(section, key, cfg=cfg)
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        if not isinstance(v, str) or not _REPORT_SLUG.fullmatch(v.strip()):
            out.append(f"[{section}] {key} = {v!r} is not a page key or session name (letters, digits, \".\", \"-\" and \"_\", with \"/\" between the parts), so {REPORT_TO} is used: set a page key such as \"projects/example-reports\"")
    return out


def audit_model() -> str:
    """[audit] model: the model of the script's per-suspect calls; "" (the default) = the [router] model."""
    return str(get("audit", "model") or "").strip()


def audit_lane() -> str:
    """[audit] lane: the sala lane the script's per-suspect `claude -p` calls run on (`salamander lane exec <lane> -- claude …`, for example "bedrock"); "" (the default) = the [router]
    command as it is, the lane every other router call uses. Only the audit's calls take it. A value that is not a lane name (lowercase letters, digits and hyphens) reads as the default."""
    import re
    v = str(get("audit", "lane") or "").strip()
    return v if re.fullmatch(r"[a-z][a-z0-9-]*", v) else ""


AUDIT_PATTERN_REVIEWS = ("off", "shadow")


def audit_pattern_review() -> str:
    """[audit] pattern_review: the pattern review, the last stage of a model run (audit_run.pattern_stage): it reads the findings the audits made since the review before it, groups the repeats by kind, agent and
    project, and makes ONE model call (on the audit's lane and model, inside max_minutes and max_calls) that drafts one guardrail per pattern. "shadow" (the default) = the drafts are logged on the run record and
    named in the summary line, and nothing is sent or opened; "off" = no review, no call, and no findings log is kept. A value that is neither reads as the default."""
    v = str(get("audit", "pattern_review") or "").strip().lower()
    return v if v in AUDIT_PATTERN_REVIEWS else "shadow"


RUNNER_PROCESSES = ("inline", "unit")
RUNNER_PROCESS_DEFAULT = "unit"


def runner_process_is_default() -> bool:
    """True when [runner] process is not set (missing, empty or blank): the default, "unit", applies. A value that is set always wins, a misspelt one included (it reads as "inline", see `runner_process`)."""
    return not str(get("runner", "process") or "").strip()


def runner_process() -> str:
    """[runner] process: where the minute set's runner runs. "unit" (the default, when the setting is not set) = the server starts no runner and the separate process `stackshot minute` runs it (stackshot-minute.service,
    which `./install.sh units` installs and `deploy.sh` restarts). "inline" = a thread of the server, started by `server._start_background`: the choice for a host with no minute unit. A value that is set and is neither
    reads as "inline" (`notes` says so): a misspelt value never leaves a box with no runner. Restart-only (RESTART_ONLY): a reload keeps the running value in CFG, so a process reads it once, at its start."""
    v = str(get("runner", "process") or "").strip().lower()
    if not v:
        return RUNNER_PROCESS_DEFAULT
    return v if v in RUNNER_PROCESSES else "inline"


WAIT_GUARD_MAX_CALLS = 30         # model calls per rolling hour
WAIT_GUARD_TIMEOUT = 30.0         # seconds one call may take before the write goes through unjudged
WAIT_GUARD_REASON_MIN = 15        # characters a wait_reason needs


def wait_guard_on() -> bool:
    """[wait_guard] enabled (default true): the check on a wait a session sets on its own item (self_wait.py). false = no refusal for a missing reason and no model call. Live."""
    v = get("wait_guard", "enabled")
    return True if v is None else (v not in (False, 0) and str(v).strip().lower() not in ("false", "no", "off", "0"))


def wait_guard_max_calls() -> int:
    """[wait_guard] max_calls: the most model calls in any rolling hour; a write past it goes through unjudged and is logged. Default 30; 0 = no call (the missing-reason refusal still applies)."""
    v = get("wait_guard", "max_calls")
    try:
        n = int(v)
    except (TypeError, ValueError):
        return WAIT_GUARD_MAX_CALLS
    return n if isinstance(v, (int, str)) and not isinstance(v, bool) and n >= 0 else WAIT_GUARD_MAX_CALLS


def wait_guard_timeout() -> float:
    """[wait_guard] timeout_seconds: how long one call may take before the write goes through unjudged. Default 30; below 1 reads as the default."""
    try:
        v = float(get("wait_guard", "timeout_seconds"))
    except (TypeError, ValueError):
        return WAIT_GUARD_TIMEOUT
    return v if v >= 1 else WAIT_GUARD_TIMEOUT


def wait_guard_model() -> str:
    """[wait_guard] model: the model of the call; "" (the default) = the [router] model."""
    return str(get("wait_guard", "model") or "").strip()


FRESHNESS_DAYS = {"call_days": 1.0, "agent_days": 1.0, "external_days": 3.0}


def freshness_days() -> dict[str, float]:
    """[freshness] call_days · agent_days · external_days: how long an active open item may go unconfirmed in its lane
    (your call · on agent · on others) before it reads stale. Defaults 1, 1 and 3; a value that is not a positive
    number keeps its default."""
    out = dict(FRESHNESS_DAYS)
    for k in out:
        try:
            v = float(get("freshness", k))
            if v > 0:
                out[k] = v
        except (TypeError, ValueError):
            pass
    return out


def fleet_dir() -> Path:
    """Where every reader finds <letter>/{machine,sessions}.json: the view the server materialises from its own clients
    (clients.py, <state>/clients/fleet); STACKSHOT_FLEET_DIR points the readers elsewhere (tests)."""
    if os.environ.get("STACKSHOT_FLEET_DIR"):
        return Path(os.environ["STACKSHOT_FLEET_DIR"])
    return state("clients", "fleet")


def fleet_tool() -> str:
    """[fleet] tool_name: the name the prose gives the fleet tool that relaunches panes and keeps the session view ("the board
    shows … (<name> runs it)", "open this session in <name>"). "" (the default) = "the fleet tool": stackshot names no tool of
    its own and runs with none installed."""
    return str(get("fleet", "tool_name") or "").strip()


def _members():
    """The one reader of who the members are (members.py), imported at call time: it reads this module."""
    from stackshot.core import members
    return members


def owner() -> str:
    """How the prose names the person this board is for: [instance] owner, or the first of [[members]] ("the owner" when the config names nobody; notes() says so at the start)."""
    return _members().first().name


OWNER_KIND = "owner"          # the generic word for the owner's mover kind (the kind the code uses inside, and what [items_api] owner_mover_kind = "owner" emits)


def owner_mover_kind() -> str:
    """The `mover.kind` the items API emits for an item that is the owner's move: [items_api] owner_mover_kind. "legacy" (the default) is a legacy owner label that stays supported: the
    owner's first name in lower case ([instance] owner; "owner" when the instance names no one), the word a reader of the API may match exactly; "owner" is the generic word."""
    if str(get("items_api", "owner_mover_kind", default="legacy") or "").strip().lower() == OWNER_KIND:
        return OWNER_KIND
    name = owner().lower()
    words = re.findall(r"[^\W_]+", name) if name != "the owner" else []      # the placeholder names no one
    return words[0] if words else OWNER_KIND


def owner_shell_mode() -> str:
    """Where the owner runs the commands of a board step ([steps] owner_shell): "powershell" (also written pwsh), "sala-shell" (also sala_shell, salashell), or "" for anything else (no place is asked for)."""
    return _shell_mode_of(get("steps", "owner_shell", default=""))


def _shell_mode_of(v: Any) -> str:
    v = str(v or "").strip().lower()
    return "powershell" if v in ("powershell", "pwsh") else "sala-shell" if v in ("sala-shell", "sala_shell", "salashell") else ""


def shell_url_ok(v: Any) -> bool:
    """Is `v` a page address a link may point at: an http(s) URL with a host (no user name or password in it, a port from 1 to 65535 when one is written), or a path that starts with one "/" (not "//", which names
    another host)? No space or control character in it."""
    from urllib.parse import urlsplit
    if not isinstance(v, str) or not v or re.search(r"[\s\x00-\x1f\x7f\\]", v):
        return False
    if v.startswith("/"):
        return not v.startswith("//")
    try:
        u = urlsplit(v)
    except ValueError:
        return False
    if u.scheme.lower() not in ("http", "https") or not u.netloc or not u.hostname or "@" in u.netloc:
        return False
    try:
        port = u.port
    except ValueError:
        return False
    return port is None or 1 <= port <= 65535


def shell_url() -> str:
    """[steps] shell_url: the page that opens the owner's shell, which a command's box links to as "Open shell"; "" when it is unset or is not an http(s) URL or a path starting with "/" (notes() says so)."""
    v = get("steps", "shell_url", default="")
    v = v.strip() if isinstance(v, str) else ""
    return v if shell_url_ok(v) else ""


# [ui] answer_frame_origins: the origins whose pages may show the answer frame (GET /items/<key>/answer-frame) in a frame. An entry is written into a response header and
# into the frame's page as a postMessage target, so it is accepted only as exactly https://<host>[:<port>] with an ASCII host name or IPv4 address: no path (not even "/"),
# query, fragment, user name, wildcard, IPv6 literal, space or punctuation a header would read as more than one origin.
_FRAME_ORIGIN = re.compile(r"https://((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?::([1-9][0-9]{0,4}))?", re.I | re.A)


def frame_origin(v: Any) -> str:
    """The origin `v` names, written as a browser writes one (lower case, port 443 left out); "" when `v` is not exactly an https origin."""
    m = _FRAME_ORIGIN.fullmatch(v) if isinstance(v, str) else None
    if not m or len(m[1]) > 253 or (m[2] and int(m[2]) > 65535):
        return ""
    port = "" if m[2] in (None, "443") else ":" + m[2]
    return f"https://{m[1].lower()}{port}"


def answer_frame_origins(cfg: dict[str, Any] | None = None) -> list[str]:
    """The origins that may frame the answer frame ([ui] answer_frame_origins), read live; [] (the default: the page does not exist) when unset or not a list. A bad
    entry is left out (answer_frame_notes says so)."""
    v = get("ui", "answer_frame_origins", default=[], cfg=cfg)
    return list(dict.fromkeys(o for o in map(frame_origin, v if isinstance(v, list) else []) if o))


def answer_frame_notes(cfg: dict[str, Any] | None = None) -> list[str]:
    """notes()'s lines for [ui] answer_frame_origins: a value that is not a list, and each entry that is ignored."""
    v = get("ui", "answer_frame_origins", default=None, cfg=cfg)
    if v is None:
        return []
    if not isinstance(v, list):
        return ['[ui] answer_frame_origins is not a list, so no other site may frame the answer frame: write it as answer_frame_origins = ["https://chat.example.com"]']
    return [f"[ui] answer_frame_origins entry {i} ({repr(x)[:80]}) is not an https origin, so it is ignored: write https://<host> or https://<host>:<port>, with nothing after it"
            for i, x in enumerate(v, 1) if not frame_origin(x)]


def owner_aliases() -> list[str]:
    """The other names a session may open a line of next with for the owner's step (the owner's initials, a name in another language): [instance] owner_aliases, or the first person's aliases; [] by default.
    The name `you` is always one (a line `you: …` is the owner's) and is not listed here."""
    return list(_members().first().aliases)


def owner_names() -> list[str]:
    """The owner's name and every alias, the name first; with no owner named, only the aliases."""
    return _members().names()


def owner_openers() -> list[str]:
    """What a line of next may open with, as the tool text lists it: the aliases with `you` after the first one (`<alias>`, `you`, `<alias>`), or just `you` when none is set."""
    al = owner_aliases()
    return al[:1] + ["you"] + al[1:]


def owner_opener_rx(to: bool = True):
    """A compiled regex for a who-takes-it opener of a line of next that names the owner: `<name>:` (name, alias or `you`, any case for `you`), and with `to` also `<name> to …` for the names
    (never `the owner's`, `ACME-1` or "the owner approved …"). Cached per set of names, so a reload is read at once."""
    return _members().opener_rx(to)


# ---------------------------------------------------------------------------------------------------------------- [keywords]: the words of another language
# The matchers that read free text (a step, a notice, an owner's answer) ship with English words only. A language the instance writes in adds its own words under
# [keywords.<feature>] in stackshot.toml; each list ADDS to the English defaults, and a missing section or key is an empty list (the English behavior, exactly).
# A "words" key holds literal words or phrases (matched as written, case-insensitive for scripts that have case; a space inside a phrase stands for any run of white
# space); a "patterns" key holds regular expressions (Python `re` syntax, matched case-insensitively), for a construct that words alone cannot spell.
# KEYWORDS is the one list of the keys: the example file and the docs/configuration*.md pages document each, and notes() names a key that is not here or a value that is not a list of strings.
KEYWORDS: dict[str, dict[str, tuple[str, str]]] = {
    "step_commands": {
        "shell_names": ("words", "other-language names of a shell (the English ones are PowerShell, pwsh, WSL, terminal, shell, console): a text that names one asks the owner to run something there"),
        "windows_words": ("words", "other-language names of Windows or PowerShell: a command with one of them says where it runs"),
        "run_commands": ("words", "other-language imperative phrases that ask the owner to run, type or paste something (run it, type it, paste it)"),
        "after_command": ("words", "words that right after a command's closing backtick make it a command for the owner to run (the verb that follows its object; a particle may be part of the phrase)"),
        "subject_markers": ("words", "the particles that mark a subject right before a backticked command: a session named as the subject runs it, not the owner"),
        "pointer_patterns": ("patterns", "other-language regular expressions for a step that points elsewhere (\"see the description\", \"see below\")"),
        "pane_cues": ("words", "other-language run cues that may stand before a pane-form `! command` (the English ones are type, run, enter, execute, paste)"),
    },
    "router": {
        "decision": ("words", "other-language words for a decision: a notice with one needs the owner (weak signal)"),
        "urgent": ("words", "other-language words for urgent: a notice with one passes the quiet hours"),
    },
    "model_guards": {
        "wait_words": ("words", "other-language words that say an item waits (waiting, wait for): a next line with one reads as a wait"),
        "overnight_words": ("words", "other-language words for overnight: a doing item whose next line says so reads as a wait"),
        "defer_after_id": ("words", "other-language phrases that follow a board id and defer on it (closes, is done, after, until, before)"),
    },
    "dates": {
        "month_suffix": ("words", "the word written right after a month number in a month-and-day date (\"<month number> <this word> <day number> <day_suffix word>\")"),
        "day_suffix": ("words", "the word written right after a day-of-month number (and after a number of days)"),
        "week_suffix": ("words", "the word written right after a number of weeks"),
        "later_words": ("words", "the words after a number of days or weeks that mean \"from now\""),
        "tomorrow": ("words", "other-language words for tomorrow"),
        "day_after_tomorrow": ("words", "other-language words for the day after tomorrow"),
        "next_week": ("words", "other-language words for next week"),
        "next_month": ("words", "other-language words for next month"),
    },
    "pages": {
        "board_label": ("words", "other-language words for the Board label of a turn's closing board line"),
        "no_change": ("words", "other-language words for 'no change' in that line"),
    },
    "rebullet": {
        "pronouns": ("words", "other-language pronouns a rewrite must not resolve into a name (matched as whole words)"),
        "negations": ("words", "other-language negation words or endings a rewrite must not lose (matched anywhere in a word)"),
        "negation_words": ("words", "other-language negation words matched only as whole words"),
    },
    "reports": {
        "ask_words": ("words", "other-language words that make a report an ask (needs, please review, decide, approve)"),
    },
    "draft": {
        "stems": ("words", "other-language words that say a step posts, sends or pastes a text (matched anywhere in the step)"),
        "stem_patterns": ("patterns", "regular expressions for such words that need a condition after them (found anywhere in the step)"),
        "standalone_stems": ("words", "such words that count only as a whole word, with at most one particle after them"),
        "particles": ("words", "the particles that may follow a standalone stem"),
        "ignore_phrases": ("words", "phrases that contain a stem but are not about posting a text (a screen share)"),
    },
    "waiting": {
        "park_words": ("words", "other-language words for park, postpone or hold: the owner's answer with one parks the item"),
    },
    "ask_options": {
        "particles": ("words", "the suffixes that may follow the last word of an option's label in a Recommend sentence (a language that glues them on): the label still counts as named"),
        "refusals": ("words", "other-language words or phrases that say 'not this option' right before a label, letter or place (the English ones are not, no, avoid, never, skip, except, don't, instead of, rather than): the option after one is turned away"),
        "refusals_after": ("words", "other-language words that say 'not this option' right after a label (a language that puts the refusing word after it): the option right before one is turned away"),
        "yes_no_words": ("words", "other-language words for yes, no, approve, decline, go and hold: a decision with no options is accepted only when its Recommend part opens with one of these or an English one; a `particles` suffix may follow"),
    },
    "server": {
        "command_cues": ("words", "other-language words that say an item waits on the owner running or pasting a command"),
    },
}


def keywords(feature: str, key: str, cfg: dict[str, Any] | None = None) -> tuple[str, ...]:
    """[keywords.<feature>] <key>: the extra words or patterns of that key, in file order, trimmed, without blanks and repeats. A missing section, a missing key and a value that is not a list of strings
    (a bare string counts as a one-item list) are () : the English behavior. Read where it is used, so a reload is seen at once."""
    v = get("keywords", feature, key, cfg=cfg)
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        return ()
    out: list[str] = []
    for x in v:
        if isinstance(x, str) and x.strip() and x.strip() not in out:
            out.append(x.strip())
    return tuple(out)


def _kw_one(word: str, kind: str, ws: str) -> str | None:
    if kind == "patterns":
        try:
            re.compile(word)
        except re.error:
            return None
        return "(?:" + word + ")"
    return ws.join(re.escape(p) for p in word.split())


def kw_alt(feature: str, key: str, ws: str = r"\s*") -> str:
    """The configured words of a key as one regex alternation (longest first; a space inside a phrase becomes `ws`), "" when the key is empty. A pattern that does not compile is left out."""
    kind = KEYWORDS.get(feature, {}).get(key, ("words", ""))[0]
    parts = [p for p in (_kw_one(w, kind, ws) for w in sorted(keywords(feature, key), key=len, reverse=True)) if p]
    return "|".join(parts)


def kw_or(feature: str, key: str, ws: str = r"\s*") -> str:
    """`|` + the alternation of a key, or "" when it is empty: appended to an English alternation, so an empty key leaves the pattern as it was."""
    a = kw_alt(feature, key, ws)
    return "|" + a if a else ""


def kw_pipe(alt: str) -> str:
    """`|` + an alternation, or "" when it is empty (a key with no words leaves the pattern it is appended to as it was)."""
    return "|" + alt if alt else ""


_NEVER = r"(?!x)x"      # a pattern nothing matches: a key with no words


_KW_RX: dict[tuple, Any] = {}


def kw_rx(name: str, build, specs: tuple[tuple[str, str], ...], flags: int = 0):
    """re.compile(build(*alts), flags), where alts[i] is kw_alt(*specs[i]) for each (feature, key) of specs; compiled once per set of words (a reload that changes a list builds a new one).
    `name` tells the patterns of different callers apart."""
    alts = tuple(kw_alt(f, k) for f, k in specs)
    key = (name, flags, alts)
    if key not in _KW_RX:
        _KW_RX[key] = re.compile(build(*alts), flags)
    return _KW_RX[key]


GMAIL_LABEL = re.compile(r"[A-Za-z0-9._-]+$")       # a mailbox name a Gmail anchor can scope itself to ([anchor_hub] gmail_names): no space, "@", "," or ":"
GMAIL_ADDR = re.compile(r"[^@\s,:]+@[^@\s,:]+$")


def gmail_names_notes(cfg: dict[str, Any] | None = None) -> list[str]:
    """notes() lines for [anchor_hub] gmail_names ({ work = "user@example.com" }): an entry the Gmail reader skips without a word is said here, at
    the start and on a reload (the key itself is read when the Google receiver starts): an address that is no email address, a name with a
    space, "@", "," or ":" (or none), two names that differ only in case (a scope matches the exact spelling first, then any case, and another case of the two is the one that sorts first), and two names
    for one address (the last one wins)."""
    gn = get("anchor_hub", "gmail_names", cfg=cfg)
    if gn is None or gn == {}:
        return []
    if not isinstance(gn, dict):
        return ["[anchor_hub] gmail_names is not a table, so no mailbox has a name: write gmail_names = { work = \"user@example.com\" }"]
    out: list[str] = []
    names: dict[str, str] = {}
    addrs: dict[str, str] = {}
    for k, v in gn.items():
        name, addr = str(k).strip(), str(v).strip()
        if not GMAIL_LABEL.match(name):
            out.append(f"[anchor_hub] gmail_names name {name!r} is skipped: a mailbox name is letters, digits, \".\", \"_\" and \"-\" only (no space or \"@\")")
            continue
        if not GMAIL_ADDR.match(addr):
            out.append(f"[anchor_hub] gmail_names {name} = {addr!r} is skipped: the value is the mailbox's email address, user@example.com")
            continue
        if name.lower() in names:
            first, second = sorted((names[name.lower()], name))
            out.append(f"[anchor_hub] gmail_names names {first!r} and {second!r} differ only in case: a scope that spells one exactly reads that mailbox, any other case of them reads {first!r}; give each mailbox a name that differs by more than case")
        if addr.lower() in addrs:
            out.append(f"[anchor_hub] gmail_names gives {addr!r} two names, {addrs[addr.lower()]!r} and {name!r}: the last one wins, give each mailbox one name")
        names[name.lower()] = name
        addrs[addr.lower()] = name
    return out


def keyword_notes(cfg: dict[str, Any] | None = None) -> list[str]:
    """notes() lines for [keywords]: a section or key this version does not read, a value that is not a list of strings, a pattern that does not compile."""
    kw = get("keywords", cfg=cfg)
    if kw is None:
        return []
    if not isinstance(kw, dict):
        return ["[keywords] is not a table, so no extra words are used: write each list under [keywords.<feature>] (the example config shows them)"]
    out: list[str] = []
    for feat, sec in kw.items():
        known = KEYWORDS.get(feat)
        if known is None:
            out.append(f"[keywords.{feat}] is not read by this version, so its words are unused: the features are {', '.join(sorted(KEYWORDS))}")
            continue
        if not isinstance(sec, dict):
            out.append(f"[keywords.{feat}] is not a table, so its words are unused: write the lists under it")
            continue
        for key, val in sec.items():
            if key not in known:
                out.append(f"[keywords.{feat}] {key} is not read by this version, so it is unused: the keys are {', '.join(sorted(known))}")
                continue
            vals = [val] if isinstance(val, str) else val
            if not isinstance(vals, (list, tuple)) or not all(isinstance(x, str) for x in vals):
                out.append(f"[keywords.{feat}] {key} is not a list of strings, so no extra words are used: write {key} = [\"word\", \"another\"]")
                continue
            if known[key][0] == "patterns":
                for p in vals:
                    try:
                        re.compile(p)
                    except re.error as e:
                        out.append(f"[keywords.{feat}] {key}: the pattern {p!r} does not compile ({e}), so it is left out")
    return out


def recycle_when_idle() -> list[str]:
    """[fleet] recycle_when_idle: the command, as words, that asks the fleet tool for a pane recycle once the box is idle; the
    reason is appended as its last argument. Sessions are told to run it when no item covers a change (the recycle gate and
    recycle-due), and release.sh runs it on a recycle (picked from the PR's files, or --recycle) when no item was flagged. "" (the default) = no such command: nothing
    is run and no session is told to run one."""
    import shlex
    try:
        return shlex.split(str(get("fleet", "recycle_when_idle") or ""))
    except ValueError:
        return []


def notice_cmd() -> list[str]:
    """[fleet] notice_cmd: the command, as words, that tells the running sessions about a change they should know but need not
    reload (a rule, a tool's wording). release.sh runs it after a green deploy whose session pick is a notice, one argument
    appended, "<title> — <summary>" (newlines and tabs as spaces, cut to 400 characters). "" (the default) = no such command: the release logs that none is
    set and goes on."""
    import shlex
    try:
        return shlex.split(str(get("fleet", "notice_cmd") or ""))
    except ValueError:
        return []


_REPO_NAME = re.compile(r"[\w.-]+/[\w.-]+")


def moved_repos() -> dict[str, str]:
    """[github.moved]: the repositories transferred to another owner, old "owner/repo" → new "owner/repo", both lower-cased. Empty (the
    default) = nothing moved. An entry whose key or value is not in owner/repo form, is not text, or maps a name to itself is ignored, and
    so is a table that is not a table, so a malformed table changes nothing. Every entry on a cycle (a → b with b → a, or a longer one) is dropped too: such a pair has no current name. Read at each call (CFG is swapped whole on a reload), so
    adding the entries on the day of a transfer needs a config reload (SIGHUP), not a restart."""
    m = get("github", "moved")
    out: dict[str, str] = {}
    for k, v in (m.items() if isinstance(m, dict) else ()):
        if not isinstance(k, str) or not isinstance(v, str):
            continue
        a, b = k.strip().lower(), v.strip().lower()
        if a != b and _REPO_NAME.fullmatch(a) and _REPO_NAME.fullmatch(b):
            out[a] = b
    loops: set[str] = set()                         # a → b and b → a, or any longer cycle: no repository has "moved" to where it came from, so every entry on one is dropped
    for start in out:
        path, r = [], start
        while r in out and r not in path:
            path.append(r); r = out[r]
        if r in path: loops.update(path[path.index(r):])
    return {k: v for k, v in out.items() if k not in loops}


def canon_repo(name: Any) -> str:
    """A repository name through [github.moved]: "owner/repo" (any case) → its current name, lower-cased; a name not in the table is only
    lower-cased and stripped, and what is not owner/repo is returned that way unchanged. Chains are followed (a → b → c gives c), so an
    old and a new name of one repository compare equal (moved_repos leaves no cycle, the seen set is only a guard). Every comparison of two repository names goes through this on both sides;
    stored names are never rewritten."""
    r = str(name or "").strip().lower()
    moved = moved_repos()
    seen = {r}
    while r in moved and moved[r] not in seen:      # the seen set ends a loop (a → b → a) after one hop
        r = moved[r]
        seen.add(r)
    return r


@dataclass(frozen=True)
class RemoteCheckout:
    """A [released.repos] checkout that is on another machine, read over ssh (released_live.git): `ssh` is the entry's host as written (a name ssh takes, or a role word "host:<role>", looked up each time git
    runs), `path` the checkout there, absolute or "~/..." (the home folder over there)."""
    ssh: str
    path: str


def ssh_target(value: str) -> str:
    """`value` (a host name, or a role word looked up now) as the one word ssh takes as a host, for the read of another repository's live checkout; "" when there is none. Unlike host(), a role whose lookup
    does not answer gives none, whatever it answered before: the role may have moved, and the checkout it left is not the live one. An answer is trusted for [hosts] cache_seconds, as everywhere."""
    h = str(host(value))      # for a role word: runs the lookup when one is due
    role = _host_role(value)
    if role is not None:
        sec = CFG.get("hosts") if isinstance(CFG, dict) else None
        key = (str((sec if isinstance(sec, dict) else {}).get("lookup")), role)
        with _HOST_LOCK:
            good = None if key in _HOST_FAILED else _HOST_GOOD.get(key)      # with the latest lookup failed, what host() gave is an old answer
        h = good[0] if good else ""
    return h if _HOST_NAME.fullmatch(h) else ""


def _released_checkout(v: Any) -> "Path | RemoteCheckout | None":
    """One [released.repos] value → where its checkout is, or None for a value that is ignored. With `ssh` present the checkout is another machine's and is never looked for here instead, so a bad `ssh`
    drops the whole entry, and so does any other key (a misspelled `ssh` would read the path on this machine)."""
    co = v.get("checkout") if isinstance(v, dict) and not set(v) - {"checkout", "ssh"} else None
    co = co.strip() if isinstance(co, str) else ""
    if not co:
        return None
    if "ssh" not in v:
        local = os.path.expanduser(co)
        return Path(local) if os.path.isabs(local) else None
    h = v["ssh"].strip() if isinstance(v["ssh"], str) else ""
    if not (_HOST_NAME.fullmatch(h) or _host_role(h)) or not co.startswith(("/", "~/")):
        return None
    return RemoteCheckout(h, co)


def released_repos() -> "dict[str, Path | RemoteCheckout]":
    """[released.repos]: the other repositories whose pull requests count as released here, "owner/repo" (lower-cased, through [github.moved]) → the checkout that holds their live copy: a Path on this
    machine (`"owner/repo" = { checkout = "/abs/path" }`; ~ expanded, absolute), or a RemoteCheckout for one on another machine (`{ checkout = "/abs/path", ssh = "host" }`). A pull request of such a
    repository is live when its merge commit is an ancestor of that checkout's HEAD. Absent (no defaults are merged) = none: only this repository's pull requests are released. An entry whose key is not
    owner/repo or whose value is neither of those forms (one with any other key included) is ignored, and so is a table that is not a table (released_notes says so). Read at each call: a reload applies it."""
    t = get("released", "repos")
    out: "dict[str, Path | RemoteCheckout]" = {}
    for k, v in (t.items() if isinstance(t, dict) else ()):
        co = _released_checkout(v)
        a = str(k).strip().lower()
        if isinstance(k, str) and _REPO_NAME.fullmatch(a) and co is not None:
            out[canon_repo(a)] = co
    return out


def released_notes(cfg: dict[str, Any] | None = None) -> list[str]:
    """Lines for the entries of [released.repos] that are ignored (see released_repos): said at the start and on a reload, since an ignored entry leaves its repository refused without a word."""
    t = get("released", "repos", cfg=cfg)
    if t is None:
        return []
    if not isinstance(t, dict):
        return ["[released.repos] is not a table, so no other repository's pull requests are read as released: write each as \"owner/repo\" = { checkout = \"/abs/path\" }"]
    out = []
    for k, v in t.items():
        if not (_REPO_NAME.fullmatch(str(k).strip().lower()) and _released_checkout(v) is not None):
            out.append(f"[released.repos] {k!r} is ignored: it needs the form \"owner/repo\" = {{ checkout = \"/absolute/path\" }}; a checkout on another machine adds ssh = \"<host>\" (its path may then start with ~/); no other key is read")
    return out


def canon_name(name: Any) -> str:
    """canon_repo for a name that [github.moved] knows (an old or a current name of a transferred repository), the name exactly as given
    for any other: a stored id keeps its case, and an empty table changes nothing. For code that builds a key from a stored name."""
    r = str(name or "").strip().lower()
    moved = moved_repos()
    return canon_repo(r) if r in moved or r in moved.values() else str(name or "")


def repo_aliases(name: Any) -> set[str]:
    """Every name [github.moved] gives the repository `name` is (it, its current name and each earlier one), lower-cased. For the matching of an
    "owner/*" entry, which has to see the owner a repository used to have."""
    c = canon_repo(name)
    out = {c, str(name or "").strip().lower()}
    out.update(k for k in moved_repos() if canon_repo(k) == c)
    return out


# [units] scope and the four [client] mode keys: one value each is left, the others were
# removed. A file that still carries a key at that value loads as before (the line can go; doctor lists it); any other value
# stops every reader of this module with the line below, never a silent remap: a system-scope instance is never installed
# over with user units, and no box runs a mode the code no longer has. What the removed modes did is described in the last release
# that had them (its stackshot.example.toml, [units] and [client]), which this repository does not keep.
REMOVED = {
    ("units", "scope"): ("user", "the units are user units, systemctl --user; an instance still installed under /etc/systemd/system moves first: "
                                 "https://github.com/howardpark-ai/stackshot/blob/main/INSTALL.md#an-instance-installed-in-the-system-scope"),
    ("client", "reads"): ("api", "a machine that is not the server box reads the page registry and page times through the server's client API"),
    ("client", "sessions"): ("client", "the server learns its sessions and machines from its own clients, the pullers and the hooks"),
    ("client", "delivery"): ("inbox", "a line for a pane on another machine waits in the server's inbox for that machine's puller"),
    ("client", "liveness"): ("puller", "a machine is online while its puller checks in, within online_minutes"),
}


def refused(cfg: dict[str, Any] | None = None) -> list[str]:
    """One line per key of REMOVED whose value in the file (or in `cfg`) is not the one left, and per fault of the [[members]] table (members.problems); [] when the file is fine."""
    out = []
    for (sec, key), (keep, what) in REMOVED.items():
        v = get(sec, key, cfg=cfg)
        if v is None or str(v).strip().lower() == keep:
            continue
        out.append(f'[{sec}] {key} = "{v}" in {PATH}: removed; "{keep}" is the one value left ({what}) '
                   f'— set {key} = "{keep}" or drop the line')
    return out + _members().problems(cfg)


def obsolete() -> list[str]:
    """The keys of REMOVED still in the file (at their one value, or refused() would have stopped the import): doctor lists them."""
    return [f"[{sec}] {key}" for (sec, key) in REMOVED if get(sec, key) is not None]


def secret_file_mode_problem(path: str) -> str:
    """"" when the file at `path` (a `[[brains]]` or `[gbrain]` secret_file) is not readable by group or others (mode & 0o077 == 0), or does not exist (the
    read says so); else a few words saying it is, with the mode. Never reads the file."""
    try:
        mode = os.stat(path).st_mode
    except OSError:
        return ""
    return secret_mode_text(mode)


def secret_mode_text(mode: int) -> str:
    """"" when a secret file's mode is private to its owner (mode & 0o077 == 0); else the few words saying it is not, with the mode. The one wording,
    used by the load-time note (by the path's stat) and by the call (by the opened descriptor's mode)."""
    return f"is readable by group or others (mode {mode & 0o777:04o}), so it is not used: chmod 600 it" if mode & 0o077 else ""


def prefix_folder(prefix: str) -> str:
    """The page folder a [[brains]] prefix points into: everything before its last "/" ("projects/beta-" -> "projects"; "projects/beta/" -> "projects/beta");
    "" when the prefix has no "/" (a page key always starts with a folder, so such a prefix matches no page)."""
    p = str(prefix).strip().lstrip("/")
    return p.rsplit("/", 1)[0] if "/" in p else ""


def _copy_readable(path: str) -> bool:
    """True when a brain's local copy is there to look into: a git copy that holds a page in some page folder. A missing, unmounted or half-cloned
    copy is not judged (the readers already say so). The look costs a few directory reads and no network."""
    root = Path(path)
    if not (root / ".git").exists():
        return False
    for sub in page_dirs():
        try:
            if next((root / sub).rglob("*.md"), None) is not None:
                return True
        except OSError:
            pass
    return False


def _prefix_folder_notes(name: str, b: dict[str, Any], prefixes: Any) -> list[str]:
    """One line for each [[brains]] prefix that names no folder in the brain's local copy: every page under such a prefix reads as missing."""
    path = os.path.expanduser(str(b.get("path") or "").strip())
    if not path or not _copy_readable(path):
        return []
    out: list[str] = []
    for p in [prefixes] if isinstance(prefixes, str) else prefixes:
        if not isinstance(p, str) or not p.strip():
            continue
        folder = prefix_folder(p)
        if folder and (Path(path) / folder).is_dir():
            continue
        what = f"no folder {folder!r} in its local copy {path}" if folder else f"no folder part in it (a page key starts with its folder, as in projects/beta-) to look for in {path}"
        out.append(f"[[brains]] {name} prefix {p.strip()!r} has {what}, so every page under it reads as missing: "
                   f"fix the prefix, or bring the copy up to date if the folder is new there")
    return out


def _strs_ok(v: Any) -> bool:
    """True when a list-of-strings key holds at least one usable (non-empty string) item."""
    return any(isinstance(x, str) and x.strip() for x in ([v] if isinstance(v, str) else v if isinstance(v, (list, tuple)) else []))


def _new_page_notes(name: str, b: dict[str, Any]) -> list[str]:
    """One line for each bad value of a [[brains]] entry's `new_prefixes` or `keep`. A bad value is ignored (brains.extra), never an error:
    a key that is not a string or a list of strings is left out whole, a non-string item or an empty one is skipped, a `new_prefixes` entry
    without a "/" after its folder part matches no page key, one that does not end in "-" or "/" also catches longer names, and a `keep`
    with no `new_prefixes` changes nothing."""
    out: list[str] = []
    for key in ("new_prefixes", "keep"):
        v = b.get(key)
        if v is None:
            continue
        if not isinstance(v, (str, list, tuple)):
            out.append(f"[[brains]] {name} {key} is not a list of strings, so it is ignored: write {key} = [\"projects/beta-\"]" if key == "new_prefixes"
                       else f"[[brains]] {name} {key} is not a list of strings, so it is ignored: write {key} = [\"beta-old\"]")
            continue
        for x in [v] if isinstance(v, str) else v:
            if not isinstance(x, str) or not x.strip():
                out.append(f"[[brains]] {name} {key} holds {x!r}, which is not a non-empty string, so it is skipped")
            elif key == "new_prefixes" and "/" not in x.strip().lstrip("/"):
                out.append(f"[[brains]] {name} new_prefixes {x.strip()!r} has no \"/\" (a page key starts with its folder, as in projects/beta-), so it matches no page")
            elif key == "new_prefixes" and not x.strip().endswith(("-", "/")):
                out.append(f"[[brains]] {name} new_prefixes {x.strip()!r} does not end in \"-\" or \"/\", so it also catches longer names: end it with the separator, for example {x.strip() + '-'!r}")
    if b.get("keep") and not _strs_ok(b.get("new_prefixes")):
        out.append(f"[[brains]] {name} has keep but no new_prefixes, so keep changes nothing: add new_prefixes or remove keep")
    return out


def server_box(cfg: dict[str, Any] | None = None) -> bool | None:
    """[server] box: True = this machine is the server box and reads the page registry and page times from its own checkouts; False = it never does (a pane
    hook always asks the server's client API, whatever clones it holds); None = unset, the older rule: a machine that has the pages checkout is the server box
    (pages.py decides from the checkout). Anything but a boolean or a string that is "true" or "false" (any case, spaces around it left off) reads as unset; `notes` says so."""
    v = get("server", "box", cfg=cfg)
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().lower() in ("true", "false"):
        return v.strip().lower() == "true"
    return None


def notes(cfg: dict[str, Any] | None = None) -> list[str]:
    """Settings problems that do not stop the start but change behaviour silently: one line each, [] when the file is fine. The config
    is exactly one file with no defaults merged in (see the head), so a [page_gate] without keeper_currency means the page rules
    are off. the old key steward_currency is no longer read, so a file holding only that one lands here too. a file that still carries the retired [runner] enabled, [model] watchers, [page_rule] mode or [router] page_debt_hour is told it can go; the key changes nothing. a [presence] minutes that is
    not a number above 0 is read as 30 (the default), so it is said here, at the start and on a reload, instead of changing silently. a paused stall pass is named first."""
    out: list[str] = stall_notes(cfg)
    out += keyword_notes(cfg)
    out += gmail_names_notes(cfg)
    out += answer_frame_notes(cfg)
    if behind_door_settings(cfg).members:       # the front door's list is the board's members: the keys below name nobody (behind_door.notes says so)
        pass
    elif not _members().build(cfg)[0].declared:
        out.append('[instance] has no owner, so the board names its person by a placeholder: set owner = "<first name>" (the example config has it)')
    elif get("members", cfg=cfg):
        pe = _members()
        owned = {e for p in pe.build(cfg) for e in p.emails}
        old_owner = str(get("instance", "owner", cfg=cfg) or "").strip()
        old_mail = get("auth", "allowed_emails", default=[], cfg=cfg)
        if (old_owner and old_owner != pe.PLACEHOLDER) or get("instance", "owner_aliases", cfg=cfg) or (isinstance(old_mail, list) and any(e not in owned for e in old_mail)):
            out.append("[[members]] is set, so [instance] owner, owner_aliases and [auth] allowed_emails are not read for a person: move what they hold into it, and drop them")
        listed = get("members", cfg=cfg)
        if isinstance(listed, list) and len(listed) > 1 and not any(isinstance(t, dict) and "agents" in t for t in listed):
            out.append('[[members]] names several members and none lists agents, so no row of Home says an agent acts for a person: add agents = ["<session name>"] to the member a session acts as '
                       "(agents = [] on a member says there is none)")
    pg = get("page_gate", cfg=cfg)
    pg = pg if isinstance(pg, dict) else {}
    if "keeper_currency" in pg:
        pass
    elif "steward_currency" in pg:
        out.append('[page_gate] steward_currency is no longer read, so the page rules are off: rename it to keeper_currency = "keepers"')
    else:
        out.append('[page_gate] has no keeper_currency, so the page rules are off: set keeper_currency = "keepers" (the example config has it)')
    rn = get("runner", cfg=cfg)
    if isinstance(rn, dict) and "enabled" in rn:
        out.append("[runner] enabled is retired and read by nothing: the minute set's runner is the only path and always starts; drop the line")
    if isinstance(rn, dict) and str(rn.get("process") or "").strip() and str(rn["process"]).strip().lower() not in RUNNER_PROCESSES:     # an empty value is "not set": the default applies, and there is nothing to say
        out.append(f'[runner] process = {rn["process"]!r} is neither "inline" nor "unit", so it is read as "inline": the server runs the minute set\'s runner itself')
    mo = get("model", cfg=cfg)
    if isinstance(mo, dict) and "watchers" in mo:
        out.append("[model] watchers is retired and read by nothing: the waits' watchers always run (a wait with a stored kind is ended by them, never by the old wake pass); drop the line")
    pr_ = get("page_rule", cfg=cfg)
    if isinstance(pr_, dict) and "mode" in pr_:
        out.append("[page_rule] mode is retired and read by nothing: a board write is never refused or held for a page debt (the reply says the page is still owed); drop the line")
    ro = get("router", cfg=cfg)
    if isinstance(ro, dict) and "page_debt_hour" in ro:
        out.append("[router] page_debt_hour is retired and read by nothing: the page-debt call runs with each audit run ([audit] at), no longer from an hour of its own; drop the line")
    if isinstance(ro, dict) and (ro.get("page_debt") is True or str(ro.get("page_debt")).strip().lower() in ("true", "1", "yes", "on")):
        au = get("audit", cfg=cfg)
        au = au if isinstance(au, dict) else {}
        if not (au.get("enabled") is True or str(au.get("enabled")).strip().lower() in ("true", "1", "yes")) or str(au.get("mode") or "").strip().lower() == "agent":
            out.append('[router] page_debt is on, but the page-debt call is made by the audit run\'s pages stage: with [audit] enabled off or mode = "agent" no pass runs and the page debts wait; turn the audit on in script mode')
    sv = get("server", cfg=cfg)
    if isinstance(sv, dict) and "box" in sv and server_box(cfg) is None:
        out.append(f'[server] box = {sv["box"]!r} is neither true nor false, so it is read as unset: a machine that holds the pages checkout is taken for the server box; write box = true or box = false')
    br = get("brains", cfg=cfg)
    if br is not None and not isinstance(br, list):
        out.append("brains is not a list of [[brains]] tables, so no second brain is used: write each one as a [[brains]] table (the example config has one)")
    seen: set[str] = set()
    second_here = False      # a second brain whose CLI this box runs (a client's entry is marked remote: it runs none, so it gets no note; brains.prepare
                             # counts every entry, remote ones too, which is harmless: a client box makes no gbrain CLI call)
    for i, b in enumerate(br if isinstance(br, list) else [], 1):
        if not isinstance(b, dict) or not str(b.get("name") or "").strip() or not str(b.get("path") or "").strip() or str(b.get("name")).strip() == "default":
            out.append(f"[[brains]] entry {i} has no name or path (or is named \"default\"), so it is skipped and its pages are read from the default brain: give it a name and its local copy's path")
            continue
        name = str(b.get("name")).strip()
        if name in seen:
            out.append(f"[[brains]] entry {i} repeats the name {name!r}: a warning and a lookup by that name reach the first entry only; give each brain its own name")
        seen.add(name)
        second_here = second_here or not b.get("remote")
        if not (b.get("slugs") or b.get("prefixes") or b.get("new_prefixes")):
            out.append(f"[[brains]] {name} names no slugs and no prefixes, so no page is read from it: list the page keys it holds")
        pf = b.get("prefixes") or []
        for p in [pf] if isinstance(pf, str) else pf:
            if isinstance(p, str) and p.strip() and not p.strip().endswith(("-", "/")):
                out.append(f"[[brains]] {name} prefix {p.strip()!r} does not end in \"-\" or \"/\", so it also catches longer names (projects/beta also takes projects/betamax): end it with the separator, for example {p.strip() + '-'!r}")
        out.extend(_prefix_folder_notes(name, b, pf))
        out.extend(_new_page_notes(name, b))
        if "shared" in b and not isinstance(b["shared"], bool):
            out.append(f"[[brains]] {name} shared = {b['shared']!r} is not true or false, so the brain is not marked shared and stackshot still writes its pages: write shared = true or shared = false (no quotes)")
        sf = b.get("secret_file")
        if sf is not None and not isinstance(sf, str):
            out.append(f"[[brains]] {name} secret_file is not a path, so no client secret is passed to its gbrain CLI: set secret_file = \"<path of the file holding the client_secret>\" or remove the key")
        elif isinstance(sf, str) and sf.strip():
            full = os.path.expanduser(sf.strip())
            bad = secret_file_mode_problem(full)
            if bad:
                out.append(f"[[brains]] {name} secret_file {full} {bad}")
        if not str(b.get("home") or "").strip() and not b.get("remote"):
            out.append(f"[[brains]] {name} has no home, so its pages are neither read nor written through the gbrain CLI (the CLI would run on the default brain): set home = \"<its GBRAIN_HOME folder>\" on that entry")
    gb = get("gbrain", cfg=cfg)
    plain = str(get("pages", "flavor", cfg=cfg) or "plain").strip().lower() != "gbrain"      # the plain flavor never reaches the default brain's CLI
    if second_here and not plain and not str((gb.get("home") if isinstance(gb, dict) else "") or "").strip():
        out.append("[gbrain] home is not set while a second brain is configured, so the default brain's gbrain CLI calls are refused (the CLI would run on whichever brain its own home holds): set home = \"<its GBRAIN_HOME folder>\" under [gbrain]")
    if isinstance(gb, dict) and "shared" in gb and not isinstance(gb["shared"], bool):
        out.append(f"[gbrain] shared = {gb['shared']!r} is not true or false, so the default brain is not marked shared and stackshot still writes its pages: write shared = true or shared = false (no quotes)")
    sf = gb.get("secret_file") if isinstance(gb, dict) else None
    if sf is not None and not isinstance(sf, str):
        out.append("[gbrain] secret_file is not a path, so no client secret is passed to the default brain's gbrain CLI: set secret_file = \"<path of the file holding the client_secret>\" or remove the key")
    elif isinstance(sf, str) and sf.strip():
        full = os.path.expanduser(sf.strip())
        bad = secret_file_mode_problem(full)
        if bad:
            out.append(f"[gbrain] secret_file {full} {bad}")
    pgs = get("pages", cfg=cfg)
    if isinstance(pgs, dict) and "copy_project_lines" in pgs and not isinstance(pgs["copy_project_lines"], bool):
        out.append(f"[pages] copy_project_lines = {pgs['copy_project_lines']!r} is not true or false, so the copy stays on (true): write copy_project_lines = false to stop writing project lines onto pages")
    su = get("steps", "shell_url", cfg=cfg)
    if su is not None and (not isinstance(su, str) or (su.strip() and not shell_url_ok(su.strip()))):
        out.append(f"[steps] shell_url = {su!r} is not an http(s) URL with a host (no user name or password in it, a port from 1 to 65535 if any) or a path starting with \"/\", so no Open shell link is drawn: write shell_url = \"https://shell.example.com/terminal\" or \"/shell\", or remove the key")
    elif isinstance(su, str) and su.strip() and _shell_mode_of(get("steps", "owner_shell", cfg=cfg)) != "sala-shell":
        out.append('[steps] shell_url only applies with owner_shell = "sala-shell", so no Open shell link is drawn: set owner_shell = "sala-shell" or remove shell_url')
    out.extend(released_notes(cfg))
    out.extend(report_notes(cfg))
    pm = get("presence", "minutes", cfg=cfg)
    if pm is not None:
        try:
            ok = not isinstance(pm, bool) and float(pm) > 0
        except (TypeError, ValueError):
            ok = False
        if not ok:
            out.append(f"[presence] minutes = {pm!r} is not a number above 0, so 30 minutes is used: set a number of minutes above 0")
    fa = get("front", "result_turn_agents", cfg=cfg)
    if fa is not None and not isinstance(fa, list):
        out.append(f"[front] result_turn_agents = {repr(fa)[:60]} is not a list of front agent names, so no agent is listed and nothing changes: write result_turn_agents = [\"my-front-agent\"]")
    elif isinstance(fa, list) and any(not isinstance(x, str) or not x.strip() for x in fa):
        bad_ = [x for x in fa if not isinstance(x, str) or not x.strip()]
        out.append(f"[front] result_turn_agents has {len(bad_)} entr{'y' if len(bad_) == 1 else 'ies'} that {'is' if len(bad_) == 1 else 'are'} no front agent name ({', '.join(repr(x)[:40] for x in bad_[:5])}), ignored: the names that are valid stay listed")
    fh = get("front", "result_turn_hours", cfg=cfg)
    if fh is not None:
        try:
            ok = isinstance(fh, (int, float)) and not isinstance(fh, bool) and math.isfinite(float(fh)) and float(fh) > 0
        except (TypeError, ValueError, ArithmeticError):      # OverflowError: an integer of hundreds of digits
            ok = False
        if not ok:
            out.append(f"[front] result_turn_hours = {repr(fh)[:60]} is not a number above 0, so 24 hours is used: set a number of hours above 0")
    ft = get("front", "to_background_senders", cfg=cfg)
    if ft is not None and not isinstance(ft, list):
        out.append(f"[front] to_background_senders = {repr(ft)[:60]} is not a list of front agent names, so no agent is listed and nothing changes: write to_background_senders = [\"my-front-agent\"]")
    elif isinstance(ft, list) and any(not isinstance(x, str) or not x.strip() for x in ft):
        bad_ = [x for x in ft if not isinstance(x, str) or not x.strip()]
        out.append(f"[front] to_background_senders has {len(bad_)} entr{'y' if len(bad_) == 1 else 'ies'} that {'is' if len(bad_) == 1 else 'are'} no front agent name ({', '.join(repr(x)[:40] for x in bad_[:5])}), ignored: the names that are valid stay listed")
    fi = get("front", "idle_peers_to_background", cfg=cfg)
    if fi is not None and not isinstance(fi, bool):
        out.append(f"[front] idle_peers_to_background = {repr(fi)[:60]} is not true or false, so it stays off and nothing changes: write idle_peers_to_background = true to turn it on")
    fc = get("front", "result_turn_cap_per_hour", cfg=cfg)
    if fc is not None and (not isinstance(fc, int) or isinstance(fc, bool) or fc < 0):
        out.append(f"[front] result_turn_cap_per_hour = {repr(fc)[:60]} is not a whole number from 0, so 6 is used: set a whole number (0 turns the case off)")
    ao = get("anchors", "offers", cfg=cfg)
    if ao is not None and not isinstance(ao, bool):
        out.append(f"[anchors] offers = {repr(ao)[:60]} is not true or false, so the anchor offers stay on (true): write offers = false to stop the replies offering an anchors call")
    out.extend(frontdoor_notes(cfg))
    out.extend(frontdoor_signin_notes(cfg))
    out.extend(frontdoor_splitter_notes(cfg))
    out.extend(behind_door_notes(cfg))
    return out


def behind_door_settings(cfg: dict[str, Any] | None = None) -> Any:
    """The `[behind_frontdoor]` settings (core/behind_door.py: a board that checks a front door's signed identity and reads its members from the door's file). Imported at call time: that module reads this one."""
    from stackshot.core import behind_door
    return behind_door.settings(cfg)


def behind_door_notes(cfg: dict[str, Any] | None = None) -> list[str]:
    """The lines for the `[behind_frontdoor]` table: [] when the config has no such table."""
    from stackshot.core import behind_door
    return behind_door.notes(cfg)


def frontdoor_notes(cfg: dict[str, Any] | None = None) -> list[str]:
    """The lines for the `[frontdoor]` table and its `[[frontdoor.backends]]` entries (core/frontdoor_config.py judges them): [] when the config has no such table.
    Imported at call time: that module reads this one."""
    from stackshot.core import frontdoor_config
    return frontdoor_config.notes(cfg)


def frontdoor_signin_notes(cfg: dict[str, Any] | None = None) -> list[str]:
    """The lines for the `[frontdoor_signin]` table (core/frontdoor_signin_config.py judges it): [] when the config has no such table. Imported at call time: that module reads this one."""
    from stackshot.core import frontdoor_signin_config
    return frontdoor_signin_config.notes(cfg)


def frontdoor_splitter_notes(cfg: dict[str, Any] | None = None) -> list[str]:
    """The lines for the `[frontdoor_splitter]` table (core/frontdoor_splitter_config.py judges it): [] when the config has no such table. Imported at call time: that module reads this one."""
    from stackshot.core import frontdoor_splitter_config
    return frontdoor_splitter_config.notes(cfg)


def stall_item_answers(item: str) -> list[dict[str, Any]] | None:
    """The owner's answers (metadata.answers) on the board item `item` names (board#N, #N, a stored id such as g7, an old id), read from the store; None when `item` is no item the store holds.
    Lazy import: ghsync imports this module."""
    import json
    import re
    from stackshot.github import ghsync as _gh
    t = str(item or "").strip().lower()
    g = _gh.norm(t) or (t if re.fullmatch(r"[a-z][1-9]\d*", t) else "")
    if not g:
        return None
    g = _gh.resolve(g)
    try:
        it = json.loads(path("paths", "store").joinpath(g[0], f"{g[1:]}.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    v = (it.get("metadata") or {}).get("answers") if isinstance(it, dict) else None
    return [a for a in v if isinstance(a, dict)] if isinstance(v, list) else []


def stall_auth(st: dict[str, Any] | None):
    """the rule for a pause of the stall pass, as `stall.pause` takes it: `auth(since)` → "" when [stall] pause_item names a board item that carries the owner's own answer approving a pause (stall.authorize) dated within
    stall.ANSWER_HOURS of `since` (when the server first saw the pause), else why not. Never raises: a failure reads as no answer, so the pause is refused and the pass runs."""
    from stackshot.waits import stall as _stall
    item = str((st or {}).get("pause_item") or "").strip()

    def auth(since: float) -> str:
        try:
            return _stall.authorize(item, stall_item_answers(item) if item else None, since)
        except Exception as e:
            return f"[stall] pause_item {item or '(none)'} could not be read ({e.__class__.__name__}): the pause is not honored"
    return auth


def stall_notes(cfg: dict[str, Any] | None = None) -> list[str]:
    """a pause of the stall pass ([stall] enabled = false, or a paused_until still ahead) is a setting that changes behaviour, so doctor, the server's start and a reload name it with its end time.
    The end is the one the server keeps (<state>/stall_pause.json, from when it first saw the pause); a pause it has not read yet counts from now. A paused_until that is not a time is named and ignored.
    a pause the owner has not answered for (`stall_auth`) is named as refused, with the reason: the pass keeps running.
    [] when nothing is paused or the end cannot be told."""
    try:
        st = get("stall", cfg=cfg)
        if not isinstance(st, dict) or (st.get("enabled", True) and st.get("paused_until") in (None, "")):
            return []
        import datetime
        import json
        import time
        from stackshot.waits import stall as _stall
        now = time.time()
        bad = []
        if st.get("paused_until") not in (None, "") and _stall.parse_until(st.get("paused_until"), tz()) is None:
            bad = [f'[stall] paused_until = {str(st.get("paused_until"))!r} is not an ISO-8601 time (like "2099-03-14T21:00+00:00"): ignored']
        rec = None
        if cfg is None or cfg is CFG:                    # the running config (a reload's notes(new) is called with it, after CFG is swapped): the server's record of the pause is the truth; any other dict is a what-if
            try:
                d = json.loads(state("stall_pause.json").read_text(encoding="utf-8"))
                rec = d if isinstance(d, dict) else None
            except Exception:
                rec = None
        hours = _stall.pause_hours(st.get("max_pause_hours", _stall.PAUSE_HOURS))
        new, end, why, _ev = _stall.pause(st.get("enabled", True), st.get("paused_until", ""), tz(), hours, rec, now, stall_auth(st))
        if "refuse" in _ev:
            return bad + [f"{why}; the pause setting is refused and the stall pass keeps running"]
        if end is None:
            return bad
        t = datetime.datetime.fromtimestamp(end, tz())
        d = t.day
        shown = f"{t:%a %b} {d}{'th' if 11 <= d % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(d % 10, 'th')} {t:%H:%M} {t:%Z}"
        seen = bool(rec) and rec.get("sig") == new.get("sig") if new else False
        return bad + [f"[stall] the stall pass is paused ({why}) and takes no step until {shown}"
                      + ("" if seen else " (counted from now: the server has not read this pause yet)") + "; it runs again on its own then, with no edit"]
    except Exception:
        return []


_bad = refused()
if _bad:
    raise SystemExit("\n".join(_bad))


# Settings a reload does not apply: what the running process wired in at its start. A reload that changes one logs
# "<key> changed: takes effect at the next restart" and keeps the running value in CFG, so every reader still agrees with
# what is wired. A section name covers all its keys. The note says what else the change needs.
RESTART_ONLY: dict[str, str] = {
    "server": "",                                 # host, port, path: uvicorn binds and mounts them at start
    "server.port": "after ./install.sh units",    #   (anchor-hub's unit waits for the server on its port)
    "auth.mode": "",                              # the OAuth provider is built at import (_auth): Google client, base URL,
    "auth.base_url": "",                          #   redirect URIs, the portal token's identity
    "auth.allowed_client_redirect_uris": "",
    "auth.portal_identity": "",
    "behind_frontdoor": "",                       # the guard of the MCP endpoint is put around the HTTP app at start (web/door_guard.py), and the members the front door lists are read from the first call on
    "runner.process": "",                         # where the minute set's runner runs (a thread of the server, or `stackshot minute`): read once at a start, by the server and by that process
    "locks": "",                                  # the store locks are made at import and each holds or skips its flock for a whole hold
    "paths": "",                                  # the store, state and secrets dirs hold the running process's files, ids and locks,
                                                  #   and anchor-hub watches them; the others are tied to them (a path move is a restart)
    "ids.letter": "",                             # its store dir is made at import; named in the connector's instructions
    "github.issues_letter": "",                   # the store letter of issue-numbered items: the files already written under it stay
    "github.local_letter": "",                    # the same for the items created while GitHub was down
    "instance.name": "",                          # these are written into the MCP tool descriptions and the connector's
    "instance.owner": "",                         #   instructions when the tools are registered at start
    "instance.owner_aliases": "",
    "members": "",                                # the members are read into the tool texts at start (and a sign-in address is a person's: the list is as restart-only as the keys it replaces)
    "steps": "",                                  # the shell rule is written into the create and update descriptions at start
    "instance.board_url": "",
    "instance.machine": "",                       # written into a temporary id (board-tmp-<machine>#<n>) and its page address
    "instance.timezone": "after ./install.sh units",   # (and anchor-hub's unit TZ)
    "subject.prefixes": "",
    "fleet.operator_label": "",
    "fleet.tool_name": "",                        # these two are written into the update tool's description at start
    "fleet.recycle_when_idle": "",
    "freshness": "",
    "anchor_hub.hook_url": "",                    # anchor-hub's webhook receiver is bound at start and the Drive/Gmail watch
    "anchor_hub.hook_port": "",                   #   channels are registered with Google at that address
    "anchor_hub.slack_team": "",                  # read when the receivers start (Slack's permalink host, the owner's Notion ids)
    "anchor_hub.self_emails": "",
    "anchor_hub.github_login": "",                # read when the GitHub receiver starts (the login whose own activity is not news, for a token that cannot say it)
    "anchor_hub.gmail_topics": "",                # a Gmail watch keeps the topic it was registered with; a restart re-registers it
    "anchor_hub.gmail_names": "",                 # the mailbox names a Gmail anchor can scope itself to are read when the Google receiver starts
    "anchor_hub.enabled": "after ./install.sh units",   # these four decide which units install.sh installs, and when
    "audit.enabled": "after ./install.sh units",
    "audit.at": "after ./install.sh units",
    "portal": "after ./install.sh units",
}


def _restart_only(key: str) -> str | None:
    """The RESTART_ONLY entry covering a dotted key (its note), or None when the key is live."""
    sec = key.split(".", 1)[0]
    return RESTART_ONLY.get(key, RESTART_ONLY.get(sec))


def _flat(cfg: dict[str, Any]) -> dict[str, Any]:
    """{"section.key": value} for every key of every section (a top-level value that is not a section: "key")."""
    out: dict[str, Any] = {}
    for s, v in cfg.items():
        if isinstance(v, dict):
            out.update({f"{s}.{k}": x for k, x in v.items()} or {s: {}})
        else:
            out[s] = v
    return out


def _say(line: str) -> None:
    print(f"config reload: {line}", file=sys.stderr, flush=True)


_MISSING = object()
PENDING: list[str] = []      # the RESTART_ONLY keys whose value in the file differs from the running one, after the last reload


def reload() -> list[str] | None:
    """Re-read the file (PATH) and check it as `config.py check` does. Valid: swap CFG at once and → the live keys that changed
    ([] for none); a changed RESTART_ONLY key keeps its running value and is logged, never applied. Invalid (a TOML syntax
    error, a missing file, a refused key): log why, keep CFG as it is and → None. Never raises."""
    global CFG, PENDING, SIG
    SIG = signature()                                   # before the read, and kept when the file then fails to load: a broken file is looked at (and said) once, not at every look
    try:
        new = load(PATH)
        bad = refused(new)
        if bad:
            _say("refused, the running config is kept:\n" + "\n".join(bad)); return None
        old = CFG
        fo, fn = _flat(old), _flat(new)
        changed = sorted(k for k in fo.keys() | fn.keys() if fo.get(k, _MISSING) != fn.get(k, _MISSING))
        held = [k for k in changed if _restart_only(k) is not None]
        for k in held:                                  # keep what is wired: the running value (or its absence) stays in CFG
            sec, _, key = k.partition(".")
            if not key:
                if k in fo: new[sec] = fo[k]
                else: new.pop(sec, None)
                continue
            if not isinstance(new.get(sec), dict):
                new[sec] = {}
            if k in fo: new[sec][key] = fo[k]
            else: new[sec].pop(key, None)
        CFG = new
        PENDING = held
        _host_reset()                                   # the lookup may be another command now
        for n in notes(new):
            _say(n)
        for k in held:
            note = _restart_only(k)
            _say(f"{k} changed: takes effect at the next restart" + (f" ({note})" if note else ""))
        return [k for k in changed if k not in held]
    except Exception as e:                              # tomllib.TOMLDecodeError, OSError, anything else: the old config stays
        _say(f"{PATH} not loaded, the running config is kept: {type(e).__name__}: {e}")
        return None


if __name__ == "__main__":
    a = sys.argv[1:]
    if a == ["file"]:
        print(PATH); sys.exit(0)
    if a == ["check"]:                # a removed mode in the file already stopped the import above with its line; here: nothing to say
        sys.exit(0)
    if a == ["server-box"]:           # [server] box as server_box() reads it: true, false, or nothing when unset or not a boolean (the SessionStart hook asks)
        v = server_box(); print("" if v is None else "true" if v else "false"); sys.exit(0)
    if len(a) < 2 or a[0] not in ("get", "path", "state", "secrets"):
        sys.exit("usage: config.py get a.b.c | path a.b | state <parts…> | secrets <parts…> | server-box | file | check")
    if a[0] == "get":
        v = get(*a[1].split("."))
        print("" if v is None else v if isinstance(v, str) else __import__("json").dumps(v))
    elif a[0] == "path":
        print(path(*a[1].split(".")))
    elif a[0] == "state":
        print(state(*a[1:]))
    else:
        print(secrets(*a[1:]))
