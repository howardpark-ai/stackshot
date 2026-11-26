"""release_running.py: a release that runs on one box, told to the box the server runs on ([release] deploy_ssh).

The server reads a running release in two places: audit/busy_hold.py (a hold on an item is refused while a release tied to it runs) and web/ui/releasing.py (the board's Queued for release label). release.sh's own signs of
one, its user unit and its log, are on the box release.sh runs on. With [release] deploy_ssh set that is not the server's box, so the release says it runs, over the same ssh:

    release.sh --run    `beat`, in the background: one entry now and one every --every s, `ssh <host> '... release_running.py put <n>'` with the entry on standard input
    release.sh's exit   `end`: the same call once, the entry marked ended

An entry (JSON) is {"stamp": nanoseconds on the sending box, "ended": bool, "age": seconds since the release's log was written, or null when it cannot be read, "tail": the end of that log}. On the server box it is the file
<state>/releases/running/pr-<n>:
  - one file a release, so no release writes over another's;
  - it counts for EXPIRE_S after it was written there, by that box's clock, so a release that died without a word holds nothing for long;
  - it replaces an entry that still counts only with a newer stamp: a beat that arrives after the release said it ended (a connection given up and finished late) changes nothing;
  - the log's age travels instead of its time, so the two boxes' clocks are never compared: the log was written `age` before the file was.
A box whose config leaves deploy_ssh unset is sent nothing and has no such folder: its readers see its own units and logs only.

Run by path from release.sh (standard library only):
    release_running.py beat <pr> <log> <host> --parent PID --every S --limit S    send for as long as the process PID is this one's parent
    release_running.py end <pr> <log> <host> --limit S                            send the ended entry once; exit 1 and one line when it was not stored
    release_running.py put <pr>                                                   on the server box: store the entry on standard input
"""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import argparse
import fcntl
import json
import math
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from stackshot.core import config as _cfg

EXPIRE_S = 300.0       # an entry counts this long after it was written. release.sh sends one every 60 s and a send is cut at 20 s, so a running release drops out only after three or more in a row were lost
TAIL_BYTES = 8192      # of the release log's end an entry carries (audit/busy_hold.py reads the stage from its last lines)
ENTRY_MAX = 128 * 1024 # characters `put` reads at most: more than any entry (the tail, every byte of it escaped, fits)
CONNECT_S = 10         # ssh's connect timeout
_NAME = re.compile(r"pr-(\d+)")


# ---------------------------------------------------------------- the sending box

def entry(log: str, ended: bool = False) -> str:
    """The entry for the release whose log is `log`, as it stands now."""
    age, tail = None, ""
    try:
        with open(log, "rb") as f:
            size = f.seek(0, 2)
            f.seek(max(0, size - TAIL_BYTES))
            tail = f.read().decode("utf-8", errors="replace")
            age = max(0.0, time.time() - os.fstat(f.fileno()).st_mtime)
    except OSError:
        pass       # a log that cannot be read: the release still runs, the server learns nothing of its log
    return json.dumps({"stamp": time.time_ns(), "ended": ended, "age": age, "tail": tail})


def command(n: int, limit: float) -> str:
    """The command run on the server box, bounded there too: what is left of `limit` after the connect, so a command whose ssh was given up does not stay."""
    return f"cd ~/stackshot && exec timeout -k 2 {max(1, int(limit) - CONNECT_S - 2)} python3 stackshot/core/release_running.py put {int(n)}"


def send(host: str, n: int, log: str, *, ended: bool, limit: float) -> str:
    """One entry to the server box. "" when that box stored it, else why not. Never longer than `limit` seconds."""
    argv = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={CONNECT_S}", host, command(n, limit)]
    with tempfile.TemporaryFile() as said:      # a file, not a pipe: a process ssh leaves behind that holds the output open (a connection master) never makes a send that was answered look unanswered
        try:
            rc = subprocess.run(argv, input=entry(log, ended).encode("utf-8"), stdout=said, stderr=said, timeout=limit).returncode
        except subprocess.TimeoutExpired:
            return f"no answer within {limit:g} s"
        except OSError as e:
            return f"ssh did not start ({e.strerror or e})"
        if rc == 0:
            return ""
        said.seek(0)
        lines = said.read()[-2000:].decode("utf-8", errors="replace").strip().splitlines()
    return f"exit status {rc}" + (f": {lines[-1]}" if lines else "")


def _stop(signum: int, frame: object) -> None:
    raise SystemExit(0)      # raised inside a send too, so the ssh in flight is stopped with this process (subprocess.run kills its child on the way out)


def beat(host: str, n: int, log: str, *, parent: int, every: float, limit: float) -> None:
    """Send the release's entry now and every `every` seconds while the process `parent` is this one's parent: a release whose process is gone says nothing more, and its last entry expires."""
    signal.signal(signal.SIGTERM, _stop)
    last = ""
    while os.getppid() == parent:
        why = send(host, n, log, ended=False, limit=limit)
        if why != last:       # a failure and the recovery are said once each
            print(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} PR #{n}: " + (f"{host} was not told that the release runs: {why}" if why else f"{host} is told again that the release runs"), flush=True)
        last = why
        time.sleep(every)


# ---------------------------------------------------------------- the server box

def folder() -> Path:
    return Path(_cfg.state("releases", "running"))


def parse(raw: str) -> "dict | None":
    """The entry `raw` holds, None when it is not one (a send that was cut off, another version's shape)."""
    try:
        e = json.loads(raw)
    except ValueError:
        return None
    if not (isinstance(e, dict) and type(e.get("stamp")) is int and isinstance(e.get("ended"), bool) and isinstance(e.get("tail"), str)):
        return None
    age = e.get("age")
    if age is not None and not (type(age) in (int, float) and math.isfinite(age) and age >= 0):
        return None
    return e


def _counting(p: Path, now: float) -> "tuple[float, dict] | None":
    """(when it was written, the entry) of a stored entry that still counts, None when there is none, it has expired or it cannot be read."""
    try:
        written = p.stat().st_mtime
        if now - written >= EXPIRE_S:
            return None
        e = parse(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return None if e is None else (written, e)


def put(n: int, raw: str) -> str:
    """Store the entry `raw` of the release of PR `n`. "" when it stands, or a newer one that still counts does; else why it was refused."""
    new = parse(raw)
    if new is None:
        return "what came in is not a release entry"
    d = folder()
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"pr-{int(n)}"
    with open(d / ".lock", "a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)      # bounded by the time limit of the command that runs this
        old = _counting(p, time.time())
        if old is not None and old[1]["stamp"] >= new["stamp"]:
            return ""
        part = d / f".pr-{int(n)}.part"       # one writer at a time (the lock), so one name; a reader never sees half an entry
        part.write_text(raw, encoding="utf-8")
        os.replace(part, p)
        for other in d.glob("pr-*"):          # what has expired is read by nobody
            try:
                if time.time() - other.stat().st_mtime >= EXPIRE_S:
                    other.unlink()
            except OSError:
                continue
    return ""


def running() -> "dict[int, tuple[float, str] | None]":
    """The releases another box says are running: {PR number: (when its log was written, by this box's clock, and the end of that log), or None when the entry carries no log}. Empty when none is, or nothing can be read."""
    try:
        d = folder()
        names = os.listdir(d)
    except Exception:  # noqa: BLE001  — no folder (a one-box install), or no state folder to read: nothing is told
        return {}
    now = time.time()
    out: "dict[int, tuple[float, str] | None]" = {}
    for name in names:
        m = _NAME.fullmatch(name)
        got = _counting(d / name, now) if m else None
        if got is None or got[1]["ended"]:
            continue
        written, e = got
        out[int(m.group(1))] = None if e["age"] is None else (written - e["age"], e["tail"])
    return out


# ---------------------------------------------------------------- the command line

def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(prog="release_running.py", description="tell the server box that a release runs on this one (release.sh does; [release] deploy_ssh)")
    sub = ap.add_subparsers(dest="verb", required=True)
    for verb in ("beat", "end"):
        s = sub.add_parser(verb)
        s.add_argument("pr", type=int)
        s.add_argument("log")
        s.add_argument("host")
        s.add_argument("--limit", type=float, required=True)
        if verb == "beat":
            s.add_argument("--parent", type=int, required=True)
            s.add_argument("--every", type=float, required=True)
    sub.add_parser("put").add_argument("pr", type=int)
    a = ap.parse_args(argv)
    if a.verb == "beat":
        beat(a.host, a.pr, a.log, parent=a.parent, every=a.every, limit=a.limit)
        return 0
    why = put(a.pr, sys.stdin.read(ENTRY_MAX)) if a.verb == "put" else send(a.host, a.pr, a.log, ended=True, limit=a.limit)
    if why:
        print(why)
    return 1 if why else 0


if __name__ == "__main__":
    sys.exit(main())
