"""runner_files.py: the files the server and the minute runner tell each other through, for the day the runner is a process of its own.

Today the runner is a thread of the server, and what the two share lives in memory: a wake is a `threading.Event`, the migration's hold on the board is a dict, the runner's record is the object itself, and the
server's start time is a module constant. A runner in another process sees none of that. Each of the four has a small file here, in `<paths.state>/minute/`, written by the side that knows and read by the side that
needs it; the in-memory form stays and is what the process that holds it reads, so nothing changes while the runner stays in the server.

  wake            one line, `<time_ns> <pid> <count>`, rewritten (a temp file and an atomic replace) on every wake. A runner that waits compares it with the line it saw last; a change ends its wait.
  hold.json       the migration pass's hold: its holder's pid, who began the pass, when it began and until when it holds. Read by every process but the holder's own (which has it in memory).
  status.json     the runner's record: its pid, its heartbeat, the tick it is in and the same record `Runner.status()` gives, so the server's watchdog and `GET /audit/status` can read a runner that is not theirs.
  server-start.json  the server's pid and start time, so a runner that restarts alone keeps the server's start for the inbox flag's first-pass delay instead of taking its own.

A file written by this very process is never read back as another process's: what a process holds in memory is the truth for it (a suite that resets the in-memory form never meets a file it left behind).
Every reader tolerates a missing, empty, torn or odd file (it reads as "nothing there") and never raises; a writer is a failed write and a stderr line, at most one a minute, never an exception. The read-only
standby (STACKSHOT_READ_ONLY=1) writes none of them. A write is a temp file with the writer's pid and thread in its name, then `os.replace`: a reader sees the old file or the new one, never half of one.

What a read costs: the wake line is one open and read of about 40 bytes (a runner makes it about once a second while it waits); the hold file is one stat when absent, and two stats when present and unchanged
(the parse is kept under the file's stamp, `filecache`); a pid check is one `kill(pid, 0)`. Pure standard library and the config and filecache beside it; imports point down only."""
from __future__ import annotations

import itertools
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg
from stackshot.core import filecache as _fc
from stackshot.core import readonly as _ro

DIR = "minute"
WAKE, HOLD, STATUS, START = "wake", "hold.json", "status.json", "server-start.json"
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
