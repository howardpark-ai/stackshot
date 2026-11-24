"""agentbox.py: reaching the box the agents run on, over ssh, when the server runs on another one.

By default the server and the agents' sessions share a box, and everything the server asks of the agents' side (the fleet tool's session list, the model calls, the CLI's
registry of live panes, the fleet tool's stores, the prompt stamps, the transcripts) is a local command or a local file. With `[agents_box] ssh = "<host>"` the server runs on
another box and this module is the one place that reaches the agents' side: no setting (the default) and every function here does what the caller did before, so nothing changes on
a single box.

Two ways in, both over non-interactive ssh (BatchMode, a connect timeout, no pty, every argument shell-quoted, anything with user text on standard input: the box's own script gets its request on standard input too, so a quoted word or a message id never shows in the remote command line), and a failure is a
`BoxError` with a plain reason and a line in the log, never a hang (every call has a time limit and a failed host is not tried again for `retry_seconds`):

  Commands   `argv(cmd)` is the argv to start instead of `cmd` (cmd itself when the setting is off): hand it to `subprocess.Popen` as before. `run(cmd, input=, timeout=)` is
             `subprocess.run` over it and raises `BoxError` when the box does not answer (ssh's own exit 255, a timeout, no ssh program).
  Files      `mirror_dir(path, patterns)` / `mirror_file(path, *beside)` copy the agents' files that match to a local mirror (one ssh call for all of them, repeated at most every
             `cache_seconds`) and return the path to read: the code that read the directory reads the mirror and is otherwise unchanged. When the box stops answering the last copy
             is served; a copy of what reads as unknown when absent (pane liveness, prompt stamps) is dropped after `stale_seconds`, so the caller reads a missing file as before, while
             a copy that must not vanish (`keep`: the session registry and links, the lane-names file) stays served, flagged stale, and `require_copy` is the test of a reader that must refuse
             when that copy is absent or older than `registry_max_age`. `pid_key` drops, on the agents' box, the rows whose process is gone (the registry of live panes). A path under
             the server's home is read under the agents' box's home (`~` means the agents' box there).
  Transcripts `glob(pattern)` and `grep_lines(file, ...)`: a transcript is too big to mirror, so a lookup lists the files on the box and a read brings back only the lines
             that can matter (the caller's own checks run on them unchanged).

Never under the item lock. A thread that holds the item lock (`xlock.holds("item")`: a write of an item) never makes an ssh call: a slow or silent box would stall every write of every item for the length of the call. `down()` is true for it (callers that
take a fallback when the box is down take it), a copy of files is served as held and never started, and a lookup of transcripts (`glob`, `grep_lines`) is answered only from the write's own lookaside: the write, before it takes the lock, runs the lookups inside
`lookaside()` (the `said` gate's `said_preread`), which keeps each answer for the write; a lookup the lookaside does not hold is a `BoxError` ("not looked up before the write"), never an ssh call.

Adding a site is one line: `agentbox.mirror_dir(path, ("*.json",))` where a directory was read, `agentbox.argv(cmd)` where a command was started.

One down-gate serves the whole mirror: once a call fails to connect (ssh's exit 255, a timeout) every other read and lookup is answered from what is held, at once, until
`retry_seconds` are over, and then one call (the probe) goes through for all of them.

The setting belongs to the server's configuration. The agents' box itself ignores it when it names this machine (a configuration shared by both boxes: the machine's own name or
short name, or a loopback address), and the puller sets `LOCAL_ONLY` so that a process that runs on the agents' box never reaches for itself. Standard library, config.py, lines.py and xlock.py only."""
from __future__ import annotations

import contextlib
import hashlib
import ipaddress
import json
import logging
import os
import re
import shlex
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

from stackshot.core import config as _cfg
from stackshot.core import xlock as _xlock
from stackshot.core.lines import newline_lines

log = logging.getLogger("stackshot.agentbox")

LOCAL_ONLY = False          # a process that runs on the agents' box (the puller) sets it: whatever the configuration says, nothing here goes over ssh
CONNECT_TIMEOUT = 5         # [agents_box] connect_timeout
TIMEOUT = 20                # [agents_box] timeout: seconds one call (a copy of files, a lookup, a read) may take
CACHE_SECONDS = 5           # [agents_box] cache_seconds: how long a copy of files, and a lookup of transcripts, is trusted
RETRY_SECONDS = 15          # [agents_box] retry_seconds: after a failed call the box is not asked again for this long (readers get the last copy meanwhile)
STALE_SECONDS = 120         # [agents_box] stale_seconds: how long the last copy of pane liveness and prompt stamps stands in for a box that no longer answers; then they read as absent
REGISTRY_MAX_AGE = 86400    # [agents_box] registry_max_age: the oldest copy of the session registry and links a check of someone's words goes by; older (or none) and it refuses
MAX_FILE_BYTES = 8 << 20    # [agents_box] max_file_bytes: a file larger than this is left out of a copy (and said)
MAX_LINE_BYTES = 64 << 20   # the most a transcript read brings back
DEFAULT_PATH = "~/.local/bin"            # [agents_box] path_prepend: added in front of PATH for a command run over ssh (a non-login shell has no ~/.local/bin)
DEFAULT_PROMPTS = "~/.local/state/stackshot/prompts"     # [agents_box] prompts_dir: where the prompt hook on the agents' box writes its stamps
_SAFE = re.compile(r"^[A-Za-z0-9_./+@:-]+$")


class BoxError(RuntimeError):
    """The agents' box could not be reached or did not do what was asked. `str(e)` is a plain reason (no ssh banner, one line). Not an OSError: a caller that treats a missing local
    file as "nothing there" must not treat an unreachable box that way."""


class RemoteFile:
    """A file on the agents' box (a transcript): only its path is held; read it with `grep_lines`. It has no local path on purpose: `open()` of it fails at once instead of reading a wrong file."""
    __slots__ = ("path",)

    def __init__(self, path: str) -> None:
        self.path = str(path)

    def __str__(self) -> str:
        return self.path

    def __repr__(self) -> str:
        return f"RemoteFile({self.path!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, RemoteFile) and other.path == self.path

    def __hash__(self) -> int:
        return hash(self.path)

    @property
    def name(self) -> str:
        return os.path.basename(self.path)


# ---------------------------------------------------------------- the setting
def _conf(key: str, default: Any = None) -> Any:
    v = _cfg.get("agents_box", key)
    return default if v is None or v == "" else v


def _num(key: str, default: float) -> float:
    try:
        v = float(_conf(key, default))
        return v if v > 0 else float(default)
    except (TypeError, ValueError):
        return float(default)


def host() -> str:
    """[agents_box] ssh, read at use (a reload is live): the host the agents run on, as ssh takes it (a name, an alias of ~/.ssh/config, user@host). "" = no such box: everything is local.
    "" too in a process that sets LOCAL_ONLY, and when the host is this machine (a configuration both boxes read): its own name or short name, or a name or address that is a loopback one."""
    if LOCAL_ONLY:
        return ""
    h = str(_cfg.get("agents_box", "ssh") or "").strip()
    if not h or h.startswith("-") or any(c.isspace() for c in h):
        return ""
    return "" if is_this_box(h) else h


def is_this_box(h: str) -> bool:
    """Does the host `h` (a name, an alias, `user@host`, an address) name this machine: its own name or short name (the domain may differ), or a loopback name or address?"""
    bare = h.rsplit("@", 1)[-1].strip("[]").lower()
    me = _ME[0] or _ME.__setitem__(0, socket.gethostname().lower()) or _ME[0]
    short = me.split(".")[0]
    return bare in (me, short) or bare.split(".")[0] == short or _loopback(bare)


_LOOP: dict[str, bool] = {}


def _loopback(name: str) -> bool:
    """Is `name` (an address, or a name) a loopback one: `127.0.0.0/8`, `::1`, `localhost`, or a name the system resolves to such an address? Looked up once per name (a name that does not resolve is not one)."""
    hit = _LOOP.get(name)
    if hit is not None:
        return hit
    out = False
    try:
        out = ipaddress.ip_address(name).is_loopback
    except ValueError:
        if name == "localhost" or name.endswith(".localhost") or name == "localhost.localdomain":
            out = True
        else:
            try:
                out = any(ipaddress.ip_address(i[4][0].split("%")[0]).is_loopback for i in socket.getaddrinfo(name, None))
            except (OSError, ValueError):
                out = False
    if len(_LOOP) > 64:
        _LOOP.clear()
    _LOOP[name] = out
    return out


def enabled() -> bool:
    return bool(host())


def _ssh_base() -> list[str]:
    extra = [str(x) for x in (_cfg.get("agents_box", "ssh_options") or []) if isinstance(x, str) and x.strip()]
    ct = int(_num("connect_timeout", CONNECT_TIMEOUT))
    # ours first: ssh keeps the first value it is given for an option, so no extra option can turn BatchMode off
    return ["ssh", "-T", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={ct}", "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=2", *extra]


def _path_prefix() -> str:
    out = []
    for e in str(_conf("path_prepend", DEFAULT_PATH)).split(":"):
        e = e.strip()
        if not e or not _SAFE.match(e.replace("~", "")):
            continue
        out.append("$HOME" + e[1:] if e.startswith("~") and (len(e) == 1 or e[1] == "/") else e)
    return ":".join(out)


def _remote_command(cmd: Sequence[str], scratch: str = "", remote_timeout: float | None = None) -> str:
    """The one string ssh hands the agents' box's shell: `sh -c '<script>'`, the script setting PATH, optionally making and entering a temporary working directory (removed when the command ends,
    whatever it did), and running `cmd` with every word quoted (under `timeout` when given, so the call ends on the box too when we give up)."""
    parts = []
    pre = _path_prefix()
    if pre:
        parts.append(f'PATH="{pre}:$PATH"; export PATH;')
    body = shlex.join([str(c) for c in cmd])
    if remote_timeout:
        body = f"timeout -k 5 {int(max(1, remote_timeout))} {body}"
    if scratch:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", scratch):
            raise ValueError(f"scratch prefix {scratch!r} is not a plain word")
        parts.append(f'd=$(mktemp -d "${{TMPDIR:-/tmp}}/{scratch}XXXXXX") || exit 1; trap \'rm -rf "$d"\' EXIT; cd "$d" || exit 1; {body}')
    else:
        parts.append(f"exec {body}")
    return "sh -c " + shlex.quote(" ".join(parts))


def argv(cmd: Sequence[str], *, scratch: str = "", remote_timeout: float | None = None) -> list[str]:
    """What to start instead of `cmd`: `cmd` itself (a new list) when no agents' box is set; otherwise ssh to the box running `cmd` there, with PATH extended ([agents_box] path_prepend),
    `scratch` (a plain word) an empty temporary working directory there named with it, `remote_timeout` seconds as the longest it may run there. Standard input, output and the exit
    status are the command's; an exit status of 255 is ssh's own (the box did not answer: `unreachable`)."""
    h = host()
    if not h:
        return [str(c) for c in cmd]
    return [*_ssh_base(), "--", h, _remote_command(cmd, scratch, remote_timeout)]


def unreachable(returncode: int | None, stderr: str = "") -> str:
    """"" unless a command started with `argv` ended because ssh could not reach the box (exit 255 with the setting on); then the plain reason, also logged, and the box counts as down."""
    if not enabled():
        return ""
    if returncode != 255:
        if returncode is not None:
            _mark_up()                      # the command ran on the box, whatever it exited with: the box answers
        return ""
    why = _first_line(stderr) or "ssh exited 255"
    _mark_down(f"the agents box does not answer over ssh: {why}")
    return f"the agents box does not answer over ssh ({why})"


def answered() -> None:
    """A command started with `argv` ran to its end on the box (the box answers): the box no longer counts as down. Nothing when no agents' box is set."""
    if enabled():
        _mark_up()


def failed(what: str, why: str) -> None:
    """Record that a command started with `argv` got no answer in time (`what` it was, `why` in a few words): the box counts as down. Nothing when no agents' box is set."""
    if enabled():
        _mark_down(f"{what}: {why}")


def _first_line(text: str, n: int = 160) -> str:
    for ln in str(text or "").splitlines():
        ln = ln.strip()
        if ln:
            return ln[:n]
    return ""


_ME = [""]                  # this machine's own name, read once
_SAID: dict[str, float] = {}                # message → monotonic time it was last logged (bounded)
_DOWN = [0.0]               # monotonic time until which the box counts as down (a call just failed to connect); 0 = not down. The first call after it is the probe for everyone
_STATE: dict[str, Any] = {"why": "", "logged": False, "stale_logged": False}     # why the box is down, and whether the outage is logged already (one line down, one line up)
_GATE = threading.Lock()


def _locked() -> bool:
    """Does this thread hold the item lock (a write of an item is under way)? Nothing is asked of the box then."""
    return _xlock.holds("item")


def _is_down() -> bool:
    return enabled() and time.monotonic() < _DOWN[0]


def down() -> bool:
    """True for `retry_seconds` after a call to the agents' box failed to connect (never with no box set), and for a thread that holds the item lock (the box is not asked then, whatever its state): a caller that
    would only wait out another timeout for an answer it does not need now takes its fallback at once."""
    return enabled() and (time.monotonic() < _DOWN[0] or _locked())


def _unasked(what: str) -> BoxError:
    """The error of a call made while this thread holds the item lock: nothing is sent to the box then (not an outage; the box stays as it was)."""
    _note(f"{what} was asked of the agents box while a write held the item lock: not asked (it is looked up before the write)")
    return BoxError(f"{what} was not looked up before the write, and the agents box is not asked while a write holds the item lock")


_LOOK = threading.local()           # the lookaside of the write this thread is making (see `lookaside`)


@contextlib.contextmanager
def lookaside():
    """Around a write that takes the item lock: the answers the box gives to `glob` and `grep_lines` outside the lock are kept for the write, and those inside the lock are answered from them (a lookup the write
    did not make beforehand is a BoxError there, never an ssh call). Nested: the outer one stays."""
    if getattr(_LOOK, "d", None) is not None:
        yield
        return
    _LOOK.d = {}
    try:
        yield
    finally:
        _LOOK.d = None


def _look(key: tuple, val: Any = None) -> Any:
    d = getattr(_LOOK, "d", None)
    if d is None:
        return None
    if val is not None:
        d[key] = val
    return d.get(key)


def _note(msg: str) -> None:
    """Log an error line that is no outage (a file left out, a script that failed), once a minute for the same text; the table of texts is bounded."""
    now = time.monotonic()
    with _GATE:
        if now - _SAID.get(msg, -1e9) < 60:
            return
        if len(_SAID) >= 64:
            for k in [k for k, t in _SAID.items() if now - t >= 60]:
                del _SAID[k]
            if len(_SAID) >= 256:
                _SAID.clear()
        _SAID[msg] = now
    log.error("agents box: %s", msg)


def _mark_down(why: str) -> None:
    """The box did not answer (ssh's exit 255, a timeout, no ssh): it counts as down for `retry_seconds`, for every reader. One log line per outage, however many readers meet it."""
    with _GATE:
        _DOWN[0] = time.monotonic() + _num("retry_seconds", RETRY_SECONDS)
        _STATE["why"] = why
        first = not _STATE["logged"]
        _STATE["logged"] = True
    if first:
        log.error("agents box: %s", why)


def _mark_up() -> None:
    with _GATE:
        was = _STATE["logged"]
        _DOWN[0] = 0.0
        _STATE.update(why="", logged=False, stale_logged=False)
    if was:
        log.info("agents box: answers again")


def _admit(limit: float) -> None:
    """The down-gate: BoxError at once while the box is known down and the retry time is not over. The first call after it is the probe: it takes the gate for as long as it may run, so the readers
    that come meanwhile are refused at once instead of each waiting out a timeout of their own."""
    with _GATE:
        until = _DOWN[0]
        if not until:
            return
        now = time.monotonic()
        if now < until:
            raise BoxError(f"the agents box does not answer ({_STATE['why'] or 'not asked again yet'})")
        _DOWN[0] = now + _num("retry_seconds", RETRY_SECONDS) + limit + 5


def run(cmd: Sequence[str], *, input: str | None = None, timeout: float | None = None, scratch: str = "") -> subprocess.CompletedProcess:
    """`subprocess.run(cmd, capture_output=True, text=True)` on the agents' box when one is set, here when not (then exactly that, with `timeout` and standard input from `input` or nothing).
    With the box set a call that cannot be made raises `BoxError` (a timeout, no ssh program, ssh's exit 255, or a box that is known down: then at once, nothing is started) with the reason logged
    once per outage; a command that ran and failed is a normal result."""
    limit = float(timeout) if timeout else _num("timeout", TIMEOUT)
    h = host()
    if not h:
        return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, timeout=limit, input=input, stdin=None if input is not None else subprocess.DEVNULL)
    if _locked():
        raise _unasked("a command")
    _admit(limit)
    full = argv(cmd, scratch=scratch, remote_timeout=limit)
    try:
        r = subprocess.run(full, capture_output=True, text=True, timeout=limit + 5, input=input, stdin=None if input is not None else subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        raise _down_err(f"no answer from the agents box within {limit:g} s") from e
    except OSError as e:
        raise _down_err(f"ssh could not be started ({e.__class__.__name__}: {e})") from e
    if r.returncode == 255:
        raise _down_err(f"the agents box does not answer over ssh: {_first_line(r.stderr) or 'ssh exited 255'}")
    _mark_up()
    return r


def _down_err(msg: str) -> BoxError:
    _mark_down(msg)
    return BoxError(msg)


def _err(msg: str) -> BoxError:
    """A failure that is no outage (the box answered, the script did not do its job): logged once a minute for the same text, the box stays up."""
    _note(msg)
    return BoxError(msg)


# ---------------------------------------------------------------- the box's own program: one script, three modes
_REMOTE = r'''
import glob, json, os, sys
mode = spec["mode"]               # `spec` is read from the first line of standard input by the command line that runs this
if mode == "mirror":
    root = os.path.expanduser(spec["root"]); cap = int(spec["cap"]); pk = spec.get("pid_key")
    files, skipped = {}, []
    for pat in spec["patterns"]:
        for f in sorted(glob.glob(os.path.join(glob.escape(root), pat))):
            rel = os.path.relpath(f, root)
            try:
                st = os.stat(f)
                if not os.path.isfile(f):
                    continue
                if st.st_size > cap:
                    skipped.append(rel); continue
                with open(f, "rb") as fh:
                    text = fh.read().decode("utf-8", "replace")
                if pk:
                    try:
                        os.kill(int(json.loads(text)[pk]), 0)
                    except PermissionError:
                        pass
                    except Exception:
                        continue
                files[rel] = [text, st.st_mtime_ns]
            except OSError:
                continue
    json.dump({"files": files, "skipped": skipped}, sys.stdout)
elif mode == "glob":
    out = []
    for f in sorted(glob.glob(os.path.expanduser(spec["pattern"]))):
        try:
            out.append([f, os.stat(f).st_mtime])
        except OSError:
            continue
    json.dump(out, sys.stdout)
elif mode == "lines":
    all_of, any_of, ci, cap, total = spec["all"], spec["any"], spec["ci"], int(spec["cap"]), 0
    try:
        fh = open(spec["path"], "rb")
    except OSError as e:
        sys.stderr.write("cannot open the file: %s\n" % e.__class__.__name__); sys.exit(3)
    with fh:
        for raw in fh:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            hay = line.lower() if ci else line
            if all(x in hay for x in all_of) and (not any_of or any(x in hay for x in any_of)):
                total += len(line) + 1
                if total > cap:
                    sys.stderr.write("more than the limit of matching text\n"); sys.exit(4)
                sys.stdout.write(line + "\n")
else:
    sys.exit(2)
'''


def _call(spec: dict[str, Any], what: str) -> str:
    """Run the box's script with `spec` → its standard output; BoxError (logged) when the box does not answer or the script fails."""
    r = run(["python3", "-c", "import sys, json; spec = json.loads(sys.stdin.readline()); exec(sys.stdin.read())"], input=json.dumps(spec) + "\n" + _REMOTE)      # the request and the script both on standard input: nothing of the request is in the remote command line
    if r.returncode != 0:
        raise _err(f"{what}: {_first_line(r.stderr) or 'the agents box returned exit ' + str(r.returncode)}")
    return r.stdout


# ---------------------------------------------------------------- files: a local copy of what the box holds
class _Spec:
    __slots__ = ("root", "patterns", "pid_key", "local", "at", "ok", "err", "files", "lock", "dropped", "keep", "skipped")

    def __init__(self, root: str, patterns: tuple[str, ...], pid_key: str, local: Path) -> None:
        self.root, self.patterns, self.pid_key, self.local = root, patterns, pid_key, local
        self.keep = False               # the copy is served beyond stale_seconds (the session registry and links, the lane files) instead of dropped
        self.at = -1e9                  # monotonic time of the last try
        self.ok: float | None = None    # monotonic time of the last good copy
        self.err = ""
        self.files: set[str] = set()    # what the copy holds now (relative to local)
        self.lock = threading.Lock()
        self.skipped: list[str] = []    # the files the last good copy left out as larger than max_file_bytes
        self.dropped = False            # past stale_seconds with the box silent: dropped (or, for a `keep` copy, flagged as stale), logged once


_SPECS: dict[tuple[str, str, tuple[str, ...], str], _Spec] = {}
_SPECS_LOCK = threading.Lock()


def remote_of(path: "str | os.PathLike[str]") -> str:
    """The path as the agents' box knows it: `~/…` for a path under this machine's home (the setting names paths as `~/…` and they are expanded here before they arrive), else as given."""
    p = str(path)
    home = os.path.expanduser("~")
    if p == home:
        return "~"
    if p.startswith(home.rstrip("/") + "/"):
        return "~/" + p[len(home.rstrip("/")) + 1:]
    return p


def _mirror_root() -> Path:
    v = str(_conf("mirror_dir", "") or "")
    return Path(os.path.expanduser(v)) if v else _cfg.state("agentbox")


def _spec(root: str, patterns: tuple[str, ...], pid_key: str) -> _Spec:
    h = host()
    key = (h, root, patterns, pid_key)
    s = _SPECS.get(key)
    if s is None:
        with _SPECS_LOCK:
            s = _SPECS.get(key)
            if s is None:
                rel = root.replace("~", "_home", 1) if root.startswith("~") else root
                hk = re.sub(r"[^A-Za-z0-9._-]", "_", h)
                local = _mirror_root() / hk / rel.lstrip("/")
                s = _SPECS[key] = _Spec(root, patterns, pid_key, local)       # a copy left by another run is not removed here: the folder is shared with every process of this box (a short-lived one starts at every push), and what one of them removed the others read as absent. See _unproven
    return s


def mirror_dir(path: "str | os.PathLike[str]", patterns: Iterable[str] = ("*",), *, pid_key: str = "", keep: bool = False) -> Path:
    """The directory to read instead of `path`: `path` itself, unchanged, when no agents' box is set. With one, a local copy of the files in the box's `path` that match `patterns` (globs
    relative to it: `*.json`, `*/sessions.json`), made now when the last copy is older than `cache_seconds`, and the copy's directory is returned. A failed copy is logged (one line per outage for the
    whole mirror) and the box is not asked again, for any directory, for `retry_seconds`: the last copy is served meanwhile. For a copy of something that reads as unknown when it is absent
    (pane liveness, prompt stamps) the copy is dropped `stale_seconds` after the last good one, and the files read as absent. `keep`: the copy is of something a reader cannot do without (the session
    registry and links, the lane-names file): it is served from the last good copy however long the box is silent, flagged stale in the log once, and a reader that must not go by an old one asks
    `require_copy`. `pid_key`: the files are JSON rows with a process id under that key, and a row whose process is gone on the box is left out."""
    if not host():
        return Path(path)
    s = _spec(remote_of(path), tuple(patterns), pid_key)
    s.keep = s.keep or keep
    _refresh(s)
    return s.local


def mirror_file(path: "str | os.PathLike[str]", *beside: str, keep: bool = False) -> Path:
    """`mirror_dir` for one file and, in the same call, the files named `beside` in its directory (a lane record and its default): the path of the file's copy; those beside it are in its directory."""
    if not host():
        return Path(path)
    p = Path(remote_of(path))
    return mirror_dir(p.parent, (p.name, *beside), keep=keep) / p.name


def require_copy(path: "str | os.PathLike[str]", patterns: Iterable[str] = ("*",), *, what: str = "the box's files", max_age: float | None = None, answering: bool = False) -> None:
    """For a check that must not go by a copy that is old or was never made (the `said` gate resolving a session's name): nothing with no agents' box set; otherwise the copy `mirror_dir(path, patterns,
    keep=True)` keeps is looked at (and refreshed when the box answers) and `BoxError` is raised, with a plain reason, when no good copy has been made since the server started, or the last
    one is older than `registry_max_age` (a day by default; `max_age` overrides). A box that answered with no such files is a good copy of nothing: no error. `answering`: the box must also be
    answering now (the check is of a name the copy may not hold yet, so a copy that stands in for a silent box is no ground): `BoxError` when the box is known down or the copy just failed, or when a copy
    is being made at this moment and has not ended (outside the item lock it is waited for, at most one call's limit, and its outcome counts; under the item lock nothing is waited for, and the box counts as
    answering only when this write's lookaside holds an answer the box gave it just before). A copy that left a file out as larger than `max_file_bytes` is no whole copy of the registry: `BoxError`."""
    if not host():
        return
    s = _spec(remote_of(path), tuple(patterns), "")
    s.keep = True
    _refresh(s)
    if s.ok is None:
        raise BoxError(f"no copy of {what} has been made, the agents box has not answered" + (f" ({s.err})" if s.err else ""))
    if s.skipped:
        raise BoxError(f"the copy of {what} is not whole: {', '.join(s.skipped[:3])} is larger than max_file_bytes and was left out")
    if answering:
        if s.lock.locked():                          # a refresh is under way: its outcome is what "answering now" means
            if _locked():
                if not getattr(_LOOK, "d", None):
                    raise BoxError("a copy of the box's files is being made, and the box was not asked in this write")
            elif s.lock.acquire(timeout=_num("timeout", TIMEOUT) + 6):
                s.lock.release()
            else:
                raise BoxError("a copy of the box's files has not ended")
        if _is_down() or s.err:
            raise BoxError(f"the agents box does not answer ({s.err or _STATE['why'] or 'not asked again yet'})")
    age = time.monotonic() - s.ok
    limit = float(max_age) if max_age is not None else _num("registry_max_age", REGISTRY_MAX_AGE)
    if age > limit:
        raise BoxError(f"the copy of {what} is {_age_text(age)} old and the agents box has not answered since")


def _age_text(seconds: float) -> str:
    return f"{seconds / 3600:.0f} h" if seconds >= 7200 else f"{seconds / 60:.0f} min" if seconds >= 120 else f"{seconds:.0f} s"


def _refresh(s: _Spec) -> None:
    now = time.monotonic()
    ttl = _num("cache_seconds", CACHE_SECONDS)
    if s.ok is not None and now - s.at < ttl and not s.err:
        return
    if down() or (s.err and now - s.at < _num("retry_seconds", RETRY_SECONDS)):
        _expire(s, now)                              # the box is known down (for any directory) or this copy just failed: what is held is served, nothing is waited for
        _unproven(s)
        return
    first = s.ok is None and not s.err
    if not s.lock.acquire(blocking=first, timeout=_num("timeout", TIMEOUT) + 6 if first else -1):
        return                                       # a copy is under way and readers have a last copy: they read that
    try:
        now = time.monotonic()
        if s.ok is not None and now - s.at < ttl and not s.err:
            return
        if down():                                   # the copy ahead of this one found the box down
            _drop(s, now)
            _unproven(s)
            return
        try:
            out = _call({"mode": "mirror", "root": s.root, "patterns": list(s.patterns), "pid_key": s.pid_key, "cap": int(_num("max_file_bytes", MAX_FILE_BYTES))}, f"cannot copy {s.root}")
            data = json.loads(out)
            files = data["files"]
            if not isinstance(files, dict):
                raise ValueError("files is not an object")
        except (BoxError, ValueError, KeyError, TypeError) as e:
            s.at = time.monotonic()
            s.err = str(e) if isinstance(e, BoxError) else str(_err(f"cannot copy {s.root}: the box's answer is not readable ({e.__class__.__name__})"))
            _drop(s, s.at)
            _unproven(s)
            return
        s.skipped = [str(r) for r in (data.get("skipped") or [])]
        for rel in s.skipped:
            _note(f"{s.root}/{rel} is larger than max_file_bytes and is left out of the copy")
        _store(s, files)
        s.err, s.ok, s.at, s.dropped = "", time.monotonic(), time.monotonic(), False
    finally:
        s.lock.release()


def _on_disk(s: _Spec) -> set[str]:
    """The files of the copy's folder this copy's patterns name now, relative to it (whoever wrote them: any process of this box shares the folder)."""
    out: set[str] = set()
    for pat in s.patterns:
        try:
            out.update(str(f.relative_to(s.local)) for f in s.local.glob(pat) if f.is_file())
        except OSError:
            pass
    return out


def _unproven(s: _Spec) -> None:
    """This process has made no good copy yet and cannot now (the box does not answer): a file another run left in the folder is of an age nobody knows, so a copy that reads as unknown
    when absent (pane liveness, prompt stamps, the lane record) is removed rather than read from. A `keep` copy (the registry, the links, the lane names) is served as it is, as it is from its last
    good copy for as long as the box is silent; a check that must not go by an old one asks `require_copy`, which counts only this process's own good copy. Once per copy."""
    if s.ok is not None or s.keep or s.dropped:
        return
    s.dropped = True
    for rel in sorted(_on_disk(s)):
        try:
            (s.local / rel).unlink()
        except OSError:
            pass


def _expire(s: _Spec, now: float) -> None:
    """`_drop` for a reader that does not hold the copy's lock: it takes it, or leaves the stale copy to the copy under way (which calls `_drop` itself when it fails)."""
    if s.ok is None or s.dropped or now - s.ok < _num("stale_seconds", STALE_SECONDS):
        return
    if not s.lock.acquire(blocking=False):
        return
    try:
        _drop(s, now)
    finally:
        s.lock.release()


def _drop(s: _Spec, now: float) -> None:
    """A silent box (the caller holds `s.lock`): the last copy stands for `stale_seconds` after the last good one. Past that a copy of what reads as unknown when absent (pane liveness, prompt stamps) goes,
    once, and the readers see no files, as they would for files that are not there; a `keep` copy (the registry, the links, the lanes) is served on and flagged stale, once per outage."""
    if s.ok is None or s.dropped or now - s.ok < _num("stale_seconds", STALE_SECONDS):
        return
    s.dropped = True
    if s.keep:
        with _GATE:
            first, _STATE["stale_logged"] = not _STATE["stale_logged"], True
        if first:
            log.warning("agents box: %s is served from a copy %s old while the box does not answer", s.root, _age_text(now - s.ok))
        return
    log.warning("agents box: %s has not been readable for %s: its files are treated as absent until the box answers", s.root, _age_text(now - s.ok))
    for rel in sorted(s.files):
        try:
            (s.local / rel).unlink()
        except OSError:
            pass
    s.files = set()


def _private_dir(p: Path) -> None:
    """Make `p` (the copy's directory, under the mirror folder) and the folders down to it, readable by this user alone (0700): the copies hold the box's registry and prompt data."""
    root = _mirror_root()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    cur = root
    try:
        parts = p.relative_to(root).parts
    except ValueError:
        parts = ()
        p.mkdir(mode=0o700, parents=True, exist_ok=True)
    for part in parts:
        cur = cur / part
        cur.mkdir(mode=0o700, exist_ok=True)


def _store(s: _Spec, files: dict[str, Any]) -> None:
    """Write the copy: a file whose time and size are those of the box's is left alone (its inode and a reader's cache stay), any other is written beside and moved in whole (mode 0600), a file the box no longer has is removed."""
    _private_dir(s.local)
    tmpd = _mirror_root() / ".tmp"
    _private_dir(tmpd)
    base = s.local.resolve()
    new: set[str] = set()
    for rel, val in files.items():
        try:
            text, mt = str(val[0]), int(val[1])
            dest = (s.local / rel).resolve()
            if base not in dest.parents:
                continue                                         # a name that climbs out of the copy is never written
            raw = text.encode("utf-8")
            try:
                st = dest.stat()
                if st.st_mtime_ns == mt and st.st_size == len(raw):
                    new.add(rel); continue
            except OSError:
                pass
            _private_dir((s.local / rel).parent)
            tmp = tmpd / f"{hashlib.sha1(str(dest).encode()).hexdigest()[:16]}.{os.getpid()}.{threading.get_ident()}"
            try:
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "wb") as fh:
                    fh.write(raw)
                os.utime(tmp, ns=(mt, mt))
                os.replace(tmp, dest)
            finally:
                tmp.unlink(missing_ok=True)
            new.add(rel)
        except (OSError, ValueError, TypeError, IndexError) as e:
            _note(f"{s.root}/{rel}: not written to the copy ({e.__class__.__name__})")
    for rel in (s.files | _on_disk(s)) - new:                    # what this copy held and what another run left: neither stays when the box no longer has it
        try:
            (s.local / rel).unlink()
        except OSError:
            pass
    s.files = new


def check_pid(pid: int) -> None:
    """`os.kill(pid, 0)` for a row of the CLI's registry: raises OSError when the process is gone. With the agents' box set the process is on the box, not here: the copy was made with `pid_key`, which left out
    the rows of dead processes there, so a row that is in the copy is alive (as of the last copy, `cache_seconds` ago) and nothing is asked of this machine."""
    pid = int(pid)
    if not host():
        os.kill(pid, 0)


def call_limit() -> float:
    """[agents_box] timeout: the seconds one call over ssh (handshake and command) may take; for a caller that sets a limit of its own for a command it starts with `argv`."""
    return _num("timeout", TIMEOUT)


def prompts_dir() -> Path:
    """The prompt stamps' directory: <paths.state>/prompts here (the prompt hook's own); with the agents' box set, a copy of the box's `[agents_box] prompts_dir`."""
    if not host():
        return _cfg.state("prompts")
    return mirror_dir(os.path.expanduser(str(_conf("prompts_dir", DEFAULT_PROMPTS))), ("*",))


# ---------------------------------------------------------------- transcripts: found and read on the box
_GLOB: dict[str, tuple[float, list[tuple[str, float]]]] = {}


def glob(pattern: str) -> list[tuple[str, float]]:
    """[(path, modified)] of the files on the agents' box that match `pattern` (a shell glob, `~/` the box's home), sorted; BoxError when the box does not answer. A found list is kept for `cache_seconds`.
    A box known to be down is not asked: BoxError at once. Not for use with the setting off (it has no local meaning): the caller tests `enabled()`."""
    key = ("glob", pattern)
    if _locked():
        got = _look(key)
        if got is None:
            raise _unasked("a list of files")
        return got
    now = time.monotonic()
    hit = _GLOB.get(pattern)
    if hit and now - hit[0] < _num("cache_seconds", CACHE_SECONDS):
        _look(key, hit[1])
        return hit[1]
    try:
        out = [(str(p), float(m)) for p, m in json.loads(_call({"mode": "glob", "pattern": pattern}, "cannot list files"))]
    except (ValueError, TypeError) as e:
        raise _err(f"cannot list files: the box's answer is not readable ({e.__class__.__name__})") from e
    if len(_GLOB) > 256:
        _GLOB.clear()
    _GLOB[pattern] = (now, out)         # an empty answer is kept too: a name the box has no file for is not asked again within cache_seconds
    _look(key, out)
    return out


def grep_lines(f: RemoteFile, *, all_of: Sequence[str] = (), any_of: Sequence[str] = (), ci: bool = False) -> list[str]:
    """The lines of a file on the box that hold every string of `all_of` and, when `any_of` is not empty, one of those (`ci`: compared lowercase; give the strings in lowercase). A superset of what the
    caller needs is fine: it checks each line itself. BoxError when the box does not answer or the file cannot be read there."""
    key = ("lines", f.path, tuple(all_of), tuple(any_of), bool(ci))
    if _locked():
        got = _look(key)
        if got is None:
            raise _unasked("a transcript")
        return got
    out = _call({"mode": "lines", "path": f.path, "all": list(all_of), "any": list(any_of), "ci": bool(ci), "cap": MAX_LINE_BYTES}, "cannot read the transcript")
    lines = newline_lines(out)
    _look(key, lines)
    return lines         # cut at newlines only: a transcript line may hold a raw U+2028 or U+0085 (see core/lines.py)
