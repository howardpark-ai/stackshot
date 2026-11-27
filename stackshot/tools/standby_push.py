"""standby_push.py: `stackshot standby-push`, one push of the server's data to a standby over ssh (docs/standby-copy.md describes it).

    stackshot standby-push [--lock-timeout SECONDS] [--max-hold SECONDS] [--output-timeout SECONDS] [--extra DIR]...

It runs `stackshot standby-copy` (the same python and package) as one child with its standard output piped into `ssh` as a second child, with no remote command: the receiver on the other
box is the key's forced command and takes the stream on its standard input. The copy's own flags are passed through. The settings are in `[standby_copy]`: `push_to` (`user@host`), `push_key`
(the private key file), `push_known_hosts` (a known_hosts file; the host key is always checked against it and nothing else) and `push_timeout` (seconds for the whole push, at most 540).

The two children share one process group that this process can stop: when `push_timeout` runs out, or a SIGTERM, SIGINT, SIGHUP or SIGQUIT arrives, both get SIGTERM and, 5 seconds later, SIGKILL.
When ssh ends with 0 first, the copy gets GRACE seconds to end by itself (it may still be removing its staging folder); when ssh ends non-zero, the copy is stopped at once.
Exit codes: 0 both sides exited 0; 1 failed (a side failed, could not be started, the time ran out, an earlier run is still live), with one line that names the side and its exit code; 3 refused (no `push_to`, a key
or known_hosts file that is not there, a push_timeout above 540), nothing is run; 128 + n stopped by signal n. A run that took place writes `<paths.state>/standby-push.json` (see `write_state`); a refusal and a run that
found an earlier one live write nothing. Standard output stays empty; the copy's and ssh's own standard error is passed through, and the stream is never printed."""
from __future__ import annotations

import argparse
import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any

try:
    import fcntl
except ModuleNotFoundError:      # Windows: no flock, and the server does not run there
    fcntl = None  # type: ignore[assignment]

from stackshot.tools.standby_copy import _seconds

STATE_FILE = "standby-push.json"
LOCK_FILE = "standby-push.lock"
DEFAULT_TIMEOUT = 300.0
GRACE = 5.0                       # seconds between SIGTERM and SIGKILL, and the copy's time to end after a clean ssh
MAX_TIMEOUT = 540.0               # the most push_timeout may be: the unit's start timeout (10 minutes) leaves room for it
SSH = "ssh"
SIGNALS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGQUIT)
POLL = 0.05


class Refused(Exception):
    """The settings do not allow a push: the message is the one line printed."""


def _say(text: str) -> None:
    print("standby-push: " + text.encode("utf-8", "backslashreplace").decode("utf-8"), file=sys.stderr, flush=True)


def copy_command(flags: list[str]) -> list[str]:
    """The copy: this python, this package, the command `standby-copy` and the flags the timer passes through."""
    return [sys.executable, "-m", "stackshot", "standby-copy", *flags]


def ssh_command(target: str, key: str, known_hosts: str) -> list[str]:
    """ssh with no remote command: the key's forced command on the other side is the receiver. No ssh config file is read (-F /dev/null), only the given known_hosts file is trusted, and nothing is asked."""
    return [SSH, "-F", "/dev/null", "-i", key, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={known_hosts}", "-o", "GlobalKnownHostsFile=/dev/null", "-o", "ConnectTimeout=15",
            "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4", "-o", "ControlMaster=no", "-o", "ControlPath=none", target]


def settings(cfg: Any) -> tuple[str, str, str, float]:
    """(push_to, key, known_hosts, timeout) from `[standby_copy]`, or Refused with the one line that says what is wrong."""
    target = str(cfg.get("standby_copy", "push_to", default="") or "").strip()
    if not target:
        raise Refused("refused: [standby_copy] push_to is empty, so there is nowhere to push")
    if target.startswith("-") or any(c.isspace() for c in target):
        raise Refused("refused: [standby_copy] push_to is not a user@host")
    files = []
    for name in ("push_key", "push_known_hosts"):
        raw = str(cfg.get("standby_copy", name, default="") or "").strip()
        if not raw:
            raise Refused(f"refused: [standby_copy] {name} is not set")
        path = os.path.expanduser(raw)
        if not os.path.isfile(path):
            raise Refused(f"refused: [standby_copy] {name} is not a file")
        files.append(path)
    if any(c.isspace() for c in files[1]):
        raise Refused("refused: [standby_copy] push_known_hosts has a space in its path")
    raw_timeout = cfg.get("standby_copy", "push_timeout", default=DEFAULT_TIMEOUT)
    try:
        if isinstance(raw_timeout, bool):
            raise ValueError
        timeout = float(raw_timeout)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError
    except (TypeError, ValueError):
        raise Refused("refused: [standby_copy] push_timeout is not a finite number of seconds above 0") from None
    if timeout > MAX_TIMEOUT:
        raise Refused(f"refused: [standby_copy] push_timeout is above {MAX_TIMEOUT:g} seconds, the most the unit's start timeout of 10 minutes leaves room for")
    return target, files[0], files[1], timeout


def write_state(directory: str, ok: bool, started: float, seconds: float, error: str) -> None:
    """`standby-push.json`: {"at", "ok", "seconds", "error", "last_ok_at"}, written to a temporary file in the same directory (0600) and renamed over the old one, so a reader sees a whole file.
    `last_ok_at` is kept from the file that was there until a run is ok."""
    final = os.path.join(directory, STATE_FILE)
    last_ok = 0
    try:
        with open(final, encoding="utf-8") as f:
            old = json.load(f)
        if isinstance(old, dict) and isinstance(old.get("last_ok_at"), (int, float)) and not isinstance(old.get("last_ok_at"), bool):
            last_ok = int(old["last_ok_at"])
    except (OSError, ValueError):
        pass
    at = int(started + seconds)
    doc = {"at": at, "ok": ok, "seconds": round(seconds, 3), "error": error, "last_ok_at": at if ok else last_ok}
    fd, tmp = tempfile.mkstemp(prefix=".standby-push-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            os.fchmod(f.fileno(), 0o600)
            json.dump(doc, f)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, final)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _describe(code: int | None) -> str:
    if code is None:
        return "did not exit"
    if code < 0:
        return f"was stopped by signal {-code}"
    return f"exited {code}"


def _stop(procs: list[subprocess.Popen], pgid: int) -> None:
    """SIGTERM to the group, SIGKILL to it GRACE seconds later; every child is reaped."""
    def signal_group(sig: int) -> None:
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError):
            pass
    signal_group(signal.SIGTERM)
    end = time.monotonic() + GRACE
    while any(p.poll() is None for p in procs) and time.monotonic() < end:
        time.sleep(POLL)
    if any(p.poll() is None for p in procs):
        signal_group(signal.SIGKILL)
    for p in procs:
        p.wait()


def push(copy_cmd: list[str], ssh_cmd: list[str], timeout: float) -> tuple[int, str]:
    """Run the pipeline. Returns (exit code of this command, the one line that says what failed or "")."""
    got: list[int] = []
    old = {s: signal.signal(s, lambda n, _f: got.append(n)) for s in SIGNALS}
    reader, writer = os.pipe()
    procs: list[subprocess.Popen] = []
    try:
        # ssh first: it waits for input, so the group (its pid) is there when the copy joins it, whatever the copy does at once
        try:
            ssh = subprocess.Popen(ssh_cmd, stdin=reader, stdout=2, process_group=0)
        except OSError as e:
            return 1, f"failed: ssh could not be started: {e.strerror or e.__class__.__name__}"
        procs.append(ssh)
        os.close(reader)
        reader = -1
        try:
            copy = subprocess.Popen(copy_cmd, stdin=subprocess.DEVNULL, stdout=writer, process_group=ssh.pid)
        except OSError as e:
            return 1, f"failed: the copy could not be started: {e.strerror or e.__class__.__name__}"
        procs.append(copy)
        os.close(writer)
        writer = -1
        deadline = time.monotonic() + timeout
        stopped = False
        grace_end: float | None = None
        while True:
            if got:
                _stop(procs, ssh.pid)
                return 128 + got[0], f"stopped by signal {got[0]}"
            if time.monotonic() >= deadline:
                _stop(procs, ssh.pid)
                return 1, f"timed out after {timeout:g} seconds; the copy and ssh were stopped"
            ssh_done, copy_done = ssh.poll() is not None, copy.poll() is not None
            if ssh_done and copy_done:
                break
            if ssh_done:
                if ssh.returncode != 0:
                    # nothing reads the stream any more: the copy has no use for the time it would take on
                    stopped = True
                    _stop(procs, ssh.pid)
                    break
                # ssh sent all of it: the copy may still be removing its staging folder, so it gets GRACE seconds to end by itself
                if grace_end is None:
                    grace_end = time.monotonic() + GRACE
                elif time.monotonic() >= grace_end:
                    stopped = True
                    _stop(procs, ssh.pid)
                    break
            time.sleep(POLL)      # a copy that is done (or failed) leaves ssh to send what it has and end
        bad = []
        if copy.returncode != 0 and not (stopped and copy.returncode in (-signal.SIGTERM, -signal.SIGKILL, 128 + signal.SIGTERM)):      # the last: standby-copy catches the signal and exits so
            bad.append(f"the copy {_describe(copy.returncode)}")
        if ssh.returncode != 0:
            bad.append(f"ssh {_describe(ssh.returncode)}")
        if not bad and stopped:
            bad.append("ssh ended before the copy did")
        if not bad:
            return 0, ""
        return 1, "failed: " + " and ".join(bad)
    finally:
        for fd in (reader, writer):
            if fd >= 0:
                os.close(fd)
        if any(p.poll() is None for p in procs):      # an exception on the way: nothing is left running
            _stop(procs, procs[0].pid)
        for s, handler in old.items():
            signal.signal(s, handler)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Push one consistent copy of the server's data to a standby over ssh: `standby-copy` into ssh, on the settings of [standby_copy]. See docs/standby-copy.md.")
    ap.add_argument("--extra", metavar="DIR", action="append", default=[], help="a further directory to copy (passed to standby-copy); may be given again")
    ap.add_argument("--lock-timeout", metavar="SECONDS", type=_seconds, help="passed to standby-copy")
    ap.add_argument("--max-hold", metavar="SECONDS", type=_seconds, help="passed to standby-copy")
    ap.add_argument("--output-timeout", metavar="SECONDS", type=_seconds, help="passed to standby-copy")
    a = ap.parse_args(argv)
    flags: list[str] = []
    for name in ("lock_timeout", "max_hold", "output_timeout"):
        if getattr(a, name) is not None:
            flags += [f"--{name.replace('_', '-')}", repr(getattr(a, name))]
    for d in a.extra:
        flags += ["--extra", d]
    try:
        from stackshot.core import config as cfg
        target, key, known_hosts, timeout = settings(cfg)
        directory = str(cfg.state())
    except Refused as e:
        _say(str(e))
        return 3
    except (OSError, KeyError, ValueError) as e:
        _say(f"refused: the config cannot be read: {e.__class__.__name__}")
        return 3
    try:
        os.makedirs(directory, exist_ok=True)
        lock = os.open(os.path.join(directory, LOCK_FILE), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as e:
        _say(f"failed: {e.strerror or e.__class__.__name__}: {e.filename}")
        return 1
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            _say("failed: an earlier push is still running")
            return 1
        started = time.time()
        t0 = time.monotonic()
        code, line = push(copy_command(flags), ssh_command(target, key, known_hosts), timeout)
        try:
            write_state(directory, code == 0, started, time.monotonic() - t0, line)
        except OSError as e:
            _say(f"state not written: {e.strerror or e.__class__.__name__}")
        if code:
            _say(line)
        return code
    finally:
        os.close(lock)


if __name__ == "__main__":
    sys.exit(main())
