"""runner_files.py: the files the server and the minute runner tell each other through, for the day the runner is a process of its own.

Today the runner is a thread of the server, and what the two share lives in memory: a wake is a `threading.Event`, the migration's hold on the board is a dict, the runner's record is the object itself, and the
server's start time is a module constant. A runner in another process sees none of that. Each of the four has a small file here, in `<paths.state>/minute/`, written by the side that knows and read by the side that
needs it; the in-memory form stays and is what the process that holds it reads, so nothing changes while the runner stays in the server.

  wake            one line, `<time_ns> <pid> <count>`, rewritten (a temp file and an atomic replace) on every wake. A runner that waits compares it with the line it saw last; a change ends its wait.
  hold.json       the migration pass's hold: its holder's pid, who began the pass, when it began and until when it holds. Read by every process but the holder's own (which has it in memory).
  status.json     the runner's record: its pid, its heartbeat, the tick it is in and the same record `Runner.status()` gives, so the server's watchdog and `GET /audit/status` can read a runner that is not theirs.
  server-start.json  the server's pid and start time, so a runner that restarts alone keeps the server's start for the inbox flag's first-pass delay instead of taking its own.
  runner.lock     the one lock that says which process runs the runner (a flock, not a signal): `lock_take` takes it without waiting and keeps it for the life of the process, the kernel frees it when the process dies; the file
                  holds the holder's pid for a message. Exactly one process runs the runner: the server when `[runner] process` is "inline", `stackshot minute` when it is "unit" (the default). The read-only standby takes none.

A file written by this very process is never read back as another process's: what a process holds in memory is the truth for it (a suite that resets the in-memory form never meets a file it left behind).
Every reader tolerates a missing, empty, torn or odd file (it reads as "nothing there") and never raises; a writer is a failed write and a stderr line, at most one a minute, never an exception. The read-only
standby (STACKSHOT_READ_ONLY=1) writes none of them. A write is a temp file with the writer's pid and thread in its name, then `os.replace`: a reader sees the old file or the new one, never half of one.

What a read costs: the wake line is one open and read of about 40 bytes (a runner makes it about once a second while it waits); the hold file is one stat when absent, and two stats when present and unchanged
(the parse is kept under the file's stamp, `filecache`); a pid check is one `kill(pid, 0)`. Pure standard library and the config and filecache beside it; imports point down only."""
from __future__ import annotations

import errno
import fcntl
import itertools
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, NamedTuple

from stackshot.core import config as _cfg
from stackshot.core import filecache as _fc
from stackshot.core import readonly as _ro

DIR = "minute"
WAKE, HOLD, STATUS, START, LOCK = "wake", "hold.json", "status.json", "server-start.json", "runner.lock"
SAY_EVERY = 60.0                 # seconds: one stderr line per kind of failed write, at most

_COUNT = itertools.count(1)      # the wake line's third field: two wakes of one process in one clock tick still differ
_SAID: dict[str, float] = {}


def _path(name: str) -> Path:
    return _cfg.state(DIR, name)


def _say(what: str, why: BaseException) -> None:
    now = time.monotonic()
    if now - _SAID.get(what, -SAY_EVERY) >= SAY_EVERY:
        _SAID[what] = now
        print(f"runner files: {what} not written: {why.__class__.__name__}: {why}", file=sys.stderr, flush=True)


def _write(name: str, text: str) -> bool:
    """The file `name`, replaced whole and atomically. → False when nothing was written: the read-only standby, or a failure (a stderr line says which, once a minute)."""
    if _ro.is_read_only():
        return False
    tmp: Path | None = None
    try:
        p = _path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, p)
        return True
    except Exception as e:  # noqa: BLE001  — a signal file never breaks the caller
        _say(name, e)
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass
        return False


def _unlink(name: str) -> None:
    if _ro.is_read_only():
        return
    try:
        _path(name).unlink()
    except Exception:  # noqa: BLE001  — absent, or not ours to remove: nothing to do
        pass


def _json(name: str) -> dict[str, Any] | None:
    """The file's JSON object, or None for a file that is missing, empty, torn, not an object or unreadable."""
    try:
        p = _path(name)
        if _fc.stamp(p) is None:
            return None
        d = _fc.read_json(p)
    except Exception:  # noqa: BLE001  — OSError, ValueError (torn or empty), an unset state path
        return None
    return d if isinstance(d, dict) else None


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def pid_alive(pid: Any) -> bool:
    """Is there a process with this pid? (`kill(pid, 0)`; a process of another user is alive too.)"""
    try:
        p = int(pid)
        if p <= 0:
            return False
        os.kill(p, 0)
        return True
    except PermissionError:
        return True
    except (OSError, ValueError, TypeError, OverflowError):
        return False


# ---------------------------------------------------------------------------------------------------------------- the wake line
def wake() -> bool:
    """Write the wake line: its content differs from every earlier one (time, pid, count), so a runner that compares it sees every wake. → whether it was written."""
    return _write(WAKE, f"{time.time_ns()} {os.getpid()} {next(_COUNT)}\n")


def wake_stamp() -> str | None:
    """The wake line as it stands now, None when the file is absent or empty. One open and read, about 40 bytes."""
    try:
        with open(_path(WAKE), encoding="utf-8") as f:
            return f.read(256).strip() or None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------------------------------------------- the hold
def hold_write(by: str, since: float, until: float) -> bool:
    return _write(HOLD, json.dumps({"pid": os.getpid(), "by": str(by), "since": float(since), "until": float(until), "written": time.time()}) + "\n")


def hold_clear() -> None:
    """Remove the hold file when this process wrote it (a hold of another process is not ours to lift)."""
    d = _json(HOLD)
    if d is not None and d.get("pid") == os.getpid():
        _unlink(HOLD)


def hold_read(now: float | None = None, ceiling: float = 3600.0) -> dict[str, Any] | None:
    """The hold of ANOTHER process that is still up, else None. It is up while its holder's pid is alive, `now` is before its `until`, and its `since` is less than `ceiling` s ago: a holder that crashed leaves
    a file that lapses by itself (a dead pid at once, an `until` that passed within the batch's renewal time, a `since` past the ceiling whatever it says). A hold of this process is in memory, never read from here."""
    d = _json(HOLD)
    if d is None:
        return None
    pid, since, until = d.get("pid"), _num(d.get("since")), _num(d.get("until"))
    if not isinstance(pid, int) or isinstance(pid, bool) or since is None or until is None or pid == os.getpid():
        return None
    t = time.time() if now is None else now
    if t >= until or t - since >= ceiling or not pid_alive(pid):
        return None
    return {"pid": pid, "by": str(d.get("by") or "migration"), "since": since, "until": until}


# ---------------------------------------------------------------------------------------------------------------- the status
def status_write(snapshot: dict[str, Any]) -> bool:
    return _write(STATUS, json.dumps(snapshot, default=str) + "\n")


def status_read(own: bool = False) -> dict[str, Any] | None:
    """The runner's record from its file: a dict with an int `pid`, a numeric `heartbeat` and a list `ticks`, else None. A record this process wrote is skipped unless `own` (the in-memory runner is its truth)."""
    d = _json(STATUS)
    if d is None:
        return None
    pid = d.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or _num(d.get("heartbeat")) is None or not isinstance(d.get("ticks"), list):
        return None
    if pid == os.getpid() and not own:
        return None
    return d


# ---------------------------------------------------------------------------------------------------------------- the server's start
def start_write(start: float) -> bool:
    return _write(START, json.dumps({"pid": os.getpid(), "start": float(start)}) + "\n")


def start_read() -> float | None:
    """The start of the server that wrote it, when that server is another process and still running; else None (no file, a torn one, this process's own, or a server that is gone: its start says
    nothing about the one that runs now)."""
    d = _json(START)
    if d is None:
        return None
    pid, start = d.get("pid"), _num(d.get("start"))
    if not isinstance(pid, int) or isinstance(pid, bool) or start is None or pid == os.getpid() or not pid_alive(pid):
        return None
    return start


# ---------------------------------------------------------------------------------------------------------------- the runner's one lock
class Lock(NamedTuple):
    """What `lock_take` found. `state`: "taken" (this process holds the lock now, or already did), "held" (another process holds it: `pid` is its pid when the file says one that is alive), "standby" (the read-only
    standby: no file is touched, nothing is taken) or "error" (the lock file could not be opened or locked: `why` says how)."""
    state: str
    pid: int | None = None
    why: str = ""


_LOCK_FD: list[int | None] = [None]    # the descriptor that holds the flock; a flock lives and dies with its open file description, so it is never closed while the process runs the runner


def _lock_pid(fd: int) -> int | None:
    """The pid the holder wrote into the lock file, when it is a process that is alive and not this one; else None (the holder has not written it yet, or the file is odd)."""
    try:
        pid = int(os.pread(fd, 32, 0).split()[0])
    except (OSError, ValueError, IndexError):
        return None
    return pid if pid != os.getpid() and pid_alive(pid) else None


def lock_holder() -> int | None:
    """The pid the lock file names when that process is alive and not this one, else None: a look that takes no lock (a process that has no runner uses it for its status, and for knowing whether a retry is worth making). A
    file that is missing, empty or odd, or a pid that is gone (a holder that died leaves its pid behind), names nobody. Never raises."""
    try:
        fd = os.open(_path(LOCK), os.O_RDONLY | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        return _lock_pid(fd)
    finally:
        os.close(fd)


def lock_take() -> Lock:
    """Take the runner's lock for the life of this process, without waiting: a flock on `<paths.state>/minute/runner.lock`. → `Lock`. A second call in a process that holds it is "taken" again (the descriptor is kept, never
    a second open). The descriptor is close-on-exec, so no child process of the holder keeps the lock after it dies. The holder writes its pid into the file after it has the lock, so a process that is refused can name it; the
    file is only a name to lock on, and a holder that dies leaves it behind and not the lock. Never raises."""
    if _ro.is_read_only():
        return Lock("standby")
    if _LOCK_FD[0] is not None:
        return Lock("taken", os.getpid())
    fd: int | None = None
    try:
        p = _path(LOCK)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(p, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                raise
            pid = _lock_pid(fd)
            os.close(fd)
            return Lock("held", pid)
        try:
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()}\n".encode())
        except OSError:
            pass                                       # the pid is for a message only: the lock is held all the same
        _LOCK_FD[0] = fd
        return Lock("taken", os.getpid())
    except Exception as e:  # noqa: BLE001  — an unset state path, a folder that cannot be made, a file of another user, no descriptor left
        if fd is not None and _LOCK_FD[0] != fd:
            try:
                os.close(fd)
            except OSError:
                pass
        return Lock("error", None, f"{e.__class__.__name__}: {e}")


def lock_release() -> bool:
    """Let go of the runner's lock (a process that stops its runner cleanly does; a process that dies is released by the kernel). → whether this process held it."""
    fd, _LOCK_FD[0] = _LOCK_FD[0], None
    if fd is None:
        return False
    try:
        os.ftruncate(fd, 0)                            # no pid is left in the file for a refused process to name: it is free before the descriptor closes
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass
    return True


def lock_held_here() -> bool:
    """Does this process hold the runner's lock?"""
    return _LOCK_FD[0] is not None
