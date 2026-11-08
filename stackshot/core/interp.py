"""interp.py — start a stackshot script as a child process even when the interpreter this process runs on is gone.

stackshot.service, anchor-hub.service and the audit timer run `uv run --locked --script <script>`, so `sys.executable` is
~/.cache/uv/environments-v2/<name>-<hash>/bin/python. A clean-up of that cache deletes the environment under a running
process: the process keeps going (its interpreter is loaded), but every child started as [sys.executable, "push.py", …]
fails with "[Errno 2] No such file or directory: '…/bin/python'", and the notice is not delivered.

`resilient(argv)` takes the argv of such a child, [interpreter, script, *args], and returns it unchanged while the
interpreter exists (the fast path: one os.path.exists, no process). When it is gone it returns the way the unit runs the
script instead, `uv run --quiet --no-project --script <script> *args` (no --locked: push.py has no lock file, and uv warns on stderr then) (uv found on PATH or at ~/.local/bin/uv), or, with no uv, the
system python3 (every script started this way, push.py, is standard-library only). With neither, argv comes back unchanged
and the child fails as before: the callers already turn a failed start into their undelivered / queued record.
`interpreter_status()` is the cheap self-check for /healthz. Standard library only."""
from __future__ import annotations

import os
import shutil
import sys

from stackshot.core import readonly as _ro  # noqa: E402

_warned: set[str] = set()


def _uv() -> str | None:
    for c in (shutil.which("uv"), os.path.expanduser("~/.local/bin/uv")):
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def _python3() -> str | None:
    for c in (shutil.which("python3"), "/usr/bin/python3"):
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def fallback_argv(argv: list[str]) -> list[str] | None:
    """The argv that runs the same script when argv[0] is gone → None when there is no way to (no script, no uv, no python3)."""
    if len(argv) < 2 or not os.path.isfile(argv[1]):
        return None
    uv = _uv()
    if uv:
        return [uv, "run", "--quiet", "--no-project", "--script", argv[1], *argv[2:]]
    py = _python3()
    return [py, *argv[1:]] if py else None


def resilient(argv: list[str], exists=os.path.exists) -> list[str]:
    """argv as given while its interpreter exists, else the fallback command (see the module doc). `exists` is for a test.
    every child the server starts through here delivers a message (push.py) or runs the audit, so a warm standby copy refuses it."""
    _ro.guard("start a child process")
    argv = list(argv)
    exe = argv[0] if argv else ""
    if not exe or not os.path.isabs(exe) or exists(exe):
        return argv
    fb = fallback_argv(argv)
    if fb is None:
        return argv
    if exe not in _warned:             # once per missing path: the journal says why children now start through uv
        _warned.add(exe)
        print(f"interp: interpreter {exe} is gone; starting children with {fb[0]}", file=sys.stderr, flush=True)
    return fb


def interpreter_status() -> dict:
    """{"path": sys.executable, "exists": bool, "fallback": the command that stands in for it, or None} — one stat, no process."""
    exe = sys.executable
    ok = bool(exe) and os.path.exists(exe)
    fb = None if ok else (_uv() or _python3())
    return {"path": exe, "exists": ok, "fallback": fb}
