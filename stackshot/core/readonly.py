"""readonly.py: the read-only mode of a warm standby copy.

A second stackshot runs warm on another machine. Its board store is a copy of the live one, copied again every few minutes, so it
must never change anything of its own: a write there would fork the board. This module is the one place that knows whether this
process is that copy, and what a copy may not do:

  is_read_only()      the one answer, read from the environment once at start (below)
  REFUSAL             the one sentence every refusal carries
  ReadOnlyError       raised by guard() and by the backstop; a PermissionError, so code that tolerates an unwritable disk tolerates it too
  guard(what)         called at the top of a write: raises ReadOnlyError on the standby, does nothing on the live instance
  install_backstop()  an audit hook that refuses any file write under the instance's own directories (store, repo, brain, state ...)
  data_age()          how old the copy is: now minus the newest mtime in the store's top level and its `.synced-at` marker
  healthz_json()      the body of /healthz?format=json
  banner()            the one-line notice every web page carries on the standby

Why an environment variable and not a key in stackshot.toml: the store and the config are copies of the live box's, so a key there
would travel with the copy and promote or demote the wrong machine. The switch must belong to the standby machine itself, so it is
set where only that machine's own files reach (a systemd drop-in: `[Service]` / `Environment=STACKSHOT_READ_ONLY=1`). Promotion is
removing the drop-in and restarting. docs/read-only-standby.md has the whole procedure.
"""
from __future__ import annotations

import html
import os
import sys
import time
from pathlib import Path
from typing import Any

REFUSAL = "stackshot here is a read-only standby copy (STACKSHOT_READ_ONLY); writes go to the live board."
MARKER = ".synced-at"          # the copy job touches <store>/.synced-at after every successful copy; its mtime is "data as of"


def _env_on() -> bool:
    return os.environ.get("STACKSHOT_READ_ONLY") == "1"      # exactly "1" is on; "0", unset, empty or anything else is off


_RO: bool = _env_on()           # read once, at import (start); the one source of is_read_only()


def is_read_only() -> bool:
    """True on the standby copy (STACKSHOT_READ_ONLY=1 in the environment at start), False on the live instance."""
    return _RO


def _reload_for_test(value: bool | None = None) -> bool:
    """Tests only: set the switch (or re-read the environment). The server never calls this."""
    global _RO
    _RO = _env_on() if value is None else bool(value)
    return _RO


class ReadOnlyError(PermissionError):
    """A write attempted on the standby copy. A PermissionError (an OSError) on purpose: code written to survive an unwritable
    disk (the state files' best-effort writes) survives this too, and nothing it was about to write is written."""

    def __init__(self, what: str = "") -> None:
        super().__init__(REFUSAL if not what else f"{REFUSAL} ({what})")


def guard(what: str = "") -> None:
    """Raise ReadOnlyError on the standby; the first line of every function that writes the store or sends something out."""
    if _RO:
        raise ReadOnlyError(what)


# ----------------------------------------------------------------------------- backstop: no file write under the instance's own directories
_ROOTS: list[str] = []
_HOOKED = False
_WRITE_EVENTS = {
    "os.rename": (0, 1), "os.remove": (0,), "os.rmdir": (0,), "os.mkdir": (0,), "os.truncate": (0,), "os.chmod": (0,),
    "os.utime": (0,), "os.symlink": (1,), "os.link": (1,), "shutil.copyfile": (1,), "shutil.copymode": (1,),
    "shutil.copystat": (1,), "shutil.rmtree": (0,), "shutil.move": (0, 1),
}
_GIT_WRITE = {"commit", "push", "add", "merge", "pull", "fetch", "checkout", "reset", "rebase", "tag", "rm", "mv", "stash", "cherry-pick", "revert", "clean", "apply", "am", "gc"}


def _under(p: Any) -> bool:
    try:
        s = os.fsdecode(p)
    except Exception:                # an fd or something odd: not a path under a root
        return False
    if not s:
        return False
    s = os.path.abspath(s)
    return any(s == r or s.startswith(r + os.sep) for r in _ROOTS)


def _is_write_open(mode: Any, flags: Any) -> bool:
    if isinstance(flags, int):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            return True
        return False
    if isinstance(mode, str):
        return any(c in mode for c in "wax+")
    return False


def _hook(event: str, args: tuple) -> None:
    if not _RO:
        return
    if event == "open":
        path, mode, flags = (args + (None, None, None))[:3]
        if isinstance(path, int) or not _is_write_open(mode, flags):
            return
        if _under(path):
            raise ReadOnlyError(f"open {os.fsdecode(path)} for writing")
        return
    idx = _WRITE_EVENTS.get(event)
    if idx is not None:
        for i in idx:
            if i < len(args) and args[i] is not None and _under(args[i]):
                raise ReadOnlyError(f"{event} {os.fsdecode(args[i])}")
        return
    if event == "subprocess.Popen" and len(args) >= 2:
        argv = args[1]
        try:
            names = [os.path.basename(os.fsdecode(a)) for a in argv]
        except Exception:
            return
        if names and names[0] == "git":
            # the sub-command is the first word that is not an option or an option's value
            raw = [os.fsdecode(a) for a in argv[1:]]
            sub = ""
            i = 0
            while i < len(raw):
                if raw[i] in ("-C", "-c", "--git-dir", "--work-tree"):
                    i += 2
                    continue
                if raw[i].startswith("-"):
                    i += 1
                    continue
                sub = raw[i]
                break
            if sub in _GIT_WRITE:
                raise ReadOnlyError(f"git {sub}")


def install_backstop(roots: list[Path | str]) -> None:
    """On the standby, refuse every file write under `roots` (the instance's own directories) and every git command that writes.
    An audit hook cannot be removed again, which suits a mode that lasts until the next restart; nothing is installed on the live
    instance. Safe to call more than once: the roots are added, the hook is installed once."""
    global _HOOKED
    if not _RO:
        return
    for r in roots:
        if r:
            s = os.path.abspath(os.path.expanduser(str(r)))
            if s not in _ROOTS:
                _ROOTS.append(s)
    if not _HOOKED:
        sys.addaudithook(_hook)
        _HOOKED = True


# ----------------------------------------------------------------------------- how old the copy is
def data_as_of(store: Path | str) -> float | None:
    """The epoch the copy's data is as of: the newest mtime among the store's top level (its files, its letter directories and
    the directory itself) and the `.synced-at` marker the copy job touches. None when the store cannot be read."""
    s = Path(store)
    best: float | None = None
    try:
        cands = [s]
        cands.extend(s.iterdir())
    except OSError:
        return None
    for p in cands:
        try:
            m = p.stat().st_mtime
        except OSError:
            continue
        if best is None or m > best:
            best = m
    return best


def data_age(store: Path | str, now: float | None = None) -> int | None:
    """Seconds since data_as_of(store), None when unknown."""
    t = data_as_of(store)
    if t is None:
        return None
    return max(0, int((time.time() if now is None else now) - t))


def healthz_line(store: Path | str) -> str:
    """The extra line /healthz carries on the standby: `read-only: yes; data age: <seconds>s` ('unknown' when it cannot be read)."""
    age = data_age(store)
    return f"read-only: yes; data age: {age}s" if age is not None else "read-only: yes; data age: unknown"


def healthz_json(store: Path | str, commit: str | None = None) -> dict[str, Any]:
    """The body of /healthz?format=json: {ok, read_only, data_age_s (null on the live instance's store without a readable mtime), commit}."""
    return {"ok": True, "read_only": _RO, "data_age_s": data_age(store), "commit": commit}


# ----------------------------------------------------------------------------- the notice on every page
def banner(store: Path | str, tz: Any = None) -> str:
    """One small line at the top of every web page on the standby: 'Read-only standby copy — data as of <time>'. Inline style on the
    board's own theme variables (with plain fallbacks for a page that defines none), so it needs no stylesheet of its own."""
    import datetime as dt
    t = data_as_of(store)
    if t is None:
        when = "unknown"
    else:
        d = dt.datetime.fromtimestamp(t, tz) if tz is not None else dt.datetime.fromtimestamp(t)
        when = d.strftime("%a %b %-d, %H:%M ") + (d.tzname() or "")
    return ('<div class="ro-banner" role="status" style="position:relative;z-index:50;margin:0;padding:.3rem .75rem;'
            'background:var(--card,#fff6df);color:var(--fg,#3a2d00);border-bottom:1px solid var(--warn,#c98a00);'
            'font:12px/1.4 system-ui,-apple-system,sans-serif;text-align:center">'
            f'Read-only standby copy &mdash; data as of {html.escape(when.strip())}</div>')


def with_banner(page: str, store: Path | str, tz: Any = None) -> str:
    """The page's HTML with the banner right after its <body ...> tag (at the very top when it has none)."""
    if "ro-banner" in page:
        return page
    b = banner(store, tz)
    low = page.lower()
    i = low.find("<body")
    if i < 0:
        return b + page
    j = page.find(">", i)
    if j < 0:
        return b + page
    return page[:j + 1] + b + page[j + 1:]


# ----------------------------------------------------------------------------- anchor-hub on the standby
STANDBY_HOOK_BODY = "standby (STACKSHOT_READ_ONLY)"


def standby_hook_server(port: int, host: str = "127.0.0.1"):
    """anchor-hub's whole life on the standby: bind its hook port and answer every request, any method and any path, with
    HTTP 503 and `standby (STACKSHOT_READ_ONLY)`; no receiver, no poller, no delivery, no state write. A per-minute port check gets
    its HTTP answer, and a vendor that posts a webhook here is told to try later (it retries), never that the hook does not exist.
    Returns the started server (daemon thread); `.shutdown()` stops it. Standard library only, so anchor-hub imports it before
    anything of its own."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def _any(self) -> None:
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                self.rfile.read(n)                      # drain the body so the sender sees the answer, not a reset
            body = STANDBY_HOOK_BODY.encode()
            self.send_response(503)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Retry-After", "60")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _any

        def log_message(self, *a: Any) -> None:
            pass

    srv = ThreadingHTTPServer((host, int(port)), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
