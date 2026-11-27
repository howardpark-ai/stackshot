"""page_upstream.py — the page edits that the remote of a pages checkout holds and the checkout has not pulled yet.

The server reads a page's time from a local copy of the pages ([paths] brain, or a second brain's own copy). Where another job pulls that copy only every few
minutes, an edit is seen that much late, and the reminder keeps saying the page is owed. So when the local copy leaves a page debt open, the server fetches
that copy's upstream and reads the fetched commit too (web/page_debts._owed_settle, and the client API's page-ts when the caller says since when it needs
an edit).

    edit_ts(key, since, wait=0)   begin a fetch for the page's copy, wait for it at most `wait` s, and give the time of the newest fetched, not yet pulled,
                                  commit that edits the page at or after `since`; 0 = none
    ct_changed(key, since)        whether the page's compiled truth at the fetched commit differs from its version at `since`
    refresh(base, wait=0)         begin a fetch for the copy at `base`, and wait for it at most `wait` s

What a fetch touches: the repository's objects and one ref of its own, REF. Never the working tree, the index, HEAD, a branch, a remote-tracking ref or
FETCH_HEAD: whatever pulls the copy or writes in it carries on as before, and a second brain's copy does not read as synced. The upstream is the one git
already has for the checked-out branch, reached with the account the server runs as, so there is nothing to set up.
Bounds: one fetch a copy at a time, begun at most every EVERY s and ended after LIMIT s. After a failed fetch the time to the next doubles with each failure
in a row, up to BACKOFF s; one that works sets it back. So an edit that reaches the remote after a fetch began is seen by the first fetch after that time,
and a read until then answers as the copy does. A caller waits at most `wait` s counted from the fetch's start, so many callers together wait no longer than
one; a board write never waits (wait 0). A branch with no upstream, a remote that cannot be reached and a fetch that fails or is slow leave the answer the
local copy gives, and so does a read of the repository that fails: a debt is settled only on what was read. A read-only standby never fetches.
A fetch ended outright can leave git's lock file on REF, which stops every later fetch; one older than STALE s is removed (nothing else writes REF).
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time

from stackshot.core import readonly as _ro
from stackshot.projects import pages as _pages

REF = "refs/stackshot/page-upstream"
EVERY = 20.0        # seconds from the start of one fetch of a copy to the earliest start of the next
BACKOFF = 300.0     # the longest that time grows to while fetches fail
WAIT = 3.0          # the most a client's page-time read waits for a fetch; that client gives the whole read 6 s (pages._api)
LIMIT = 30.0        # a fetch still running after this is ended
END_GRACE = 2.0     # seconds an ended fetch has to remove its lock files before it is ended outright
STALE = 300.0       # a lock file on REF this old was left behind: no fetch lives past LIMIT and two END_GRACE
READ_LIMIT = 5      # seconds one read of the local repository may take

_LOCK = threading.Lock()
_RUNS: dict[str, tuple[float, threading.Event]] = {}     # copy -> (when its last fetch began, set when that fetch is over)
_FAILS: dict[str, int] = {}                              # copy -> fetches that failed in a row: said at the first, and the next comes later with each


def _read(base: str, *args: str) -> str | None:
    """One read of the local repository: its output, None when git fails or takes too long."""
    try:
        r = subprocess.run(["git", "-C", base, *args], capture_output=True, text=True, timeout=READ_LIMIT)
        return r.stdout if r.returncode == 0 else None
    except Exception:  # noqa: BLE001
        return None


def _git(base: str, *args: str) -> str:
    """The same read as one word or line: "" when it cannot be had."""
    return (_read(base, *args) or "").strip()


def _end(p: subprocess.Popen) -> None:
    """End a fetch and whatever it started (ssh, a helper): asked first, so that git removes its lock files, then outright."""
    for sig in (signal.SIGTERM, getattr(signal, "SIGKILL", signal.SIGTERM)):
        try:
            os.killpg(p.pid, sig)               # its own process group (start_new_session)
        except (AttributeError, OSError):
            p.kill()
        try:
            p.wait(END_GRACE)
        except subprocess.TimeoutExpired:
            pass


def _drop_stale_lock(base: str) -> None:
    """Remove the lock file on REF when it is older than STALE: no fetch begun here can still hold it, and git refuses to move REF while it is there."""
    path = _git(base, "rev-parse", "--path-format=absolute", "--git-path", f"{REF}.lock")
    if not path:
        return
    try:
        if time.time() - os.stat(path).st_mtime < STALE:
            return
        os.remove(path)
    except FileNotFoundError:
        return
    except OSError as e:
        print(f"page upstream: the old lock file {path} could not be removed ({type(e).__name__})", file=sys.stderr)
        return
    print(f"page upstream: removed a lock file left behind, {path}", file=sys.stderr)


def _failed(base: str, why: str) -> None:
    """Count a failed fetch of the copy; the first of a row is said."""
    n = _FAILS.get(base, 0)
    _FAILS[base] = n + 1
    if not n:
        print(f"page upstream: {why} in {base}; page debts are judged by that copy alone until a fetch works", file=sys.stderr)


def _fetch(base: str, done: threading.Event) -> None:
    try:
        branch = _git(base, "symbolic-ref", "--quiet", "--short", "HEAD")
        remote = _git(base, "config", "--get", f"branch.{branch}.remote") if branch else ""
        upstream = _git(base, "config", "--get", f"branch.{branch}.merge") if remote else ""
        if not upstream:
            return
        _drop_stale_lock(base)
        # --refmap= and --no-write-fetch-head: only REF moves. No housekeeping of the repository is started from here, and git never asks for a password
        p = subprocess.Popen(["git", "-C", base, "-c", "gc.auto=0", "-c", "maintenance.auto=false", "fetch", "--quiet", "--no-tags", "--no-recurse-submodules",
                              "--no-write-fetch-head", "--refmap=", remote, f"+{upstream}:{REF}"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                             env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        try:
            why = f"git fetch ended with status {p.wait(LIMIT)}"
        except subprocess.TimeoutExpired:
            _end(p)
            why = f"git fetch was still running after {LIMIT:g} s"
        if p.returncode == 0:
            _FAILS.pop(base, None)
        else:
            _failed(base, why)
    except Exception as e:  # noqa: BLE001  — fail-open: the local copy answers as before
        _failed(base, f"no fetch could be run ({type(e).__name__})")
    finally:
        done.set()


def _gap(base: str) -> float:
    """Seconds from the start of the copy's last fetch to the earliest start of the next."""
    return min(EVERY * 2 ** min(_FAILS.get(base, 0), 20), max(BACKOFF, EVERY))


def refresh(base: str, wait: float = 0.0) -> None:
    """Begin a fetch of the copy's upstream unless one is running or the last began too recently (_gap); then wait for it, at most until `wait` s after it began."""
    if _ro.is_read_only() or not os.path.isdir(base):
        return
    with _LOCK:
        run = _RUNS.get(base)
        if run is None or (run[1].is_set() and time.monotonic() - run[0] >= _gap(base)):
            run = _RUNS[base] = (time.monotonic(), threading.Event())
            threading.Thread(target=_fetch, args=(base, run[1]), name="page-upstream", daemon=True).start()
    left = run[0] + wait - time.monotonic()
    if wait > 0 and left > 0:
        run[1].wait(left)


def edit_ts(key: str, since: float, wait: float = 0.0) -> int:
    """The commit time of the newest fetched commit that the copy does not hold yet and that edits the page, when it is at or after `since`; else 0.
    Begins a fetch first (refresh): with `wait` 0 what is read is what an earlier fetch brought."""
    base = _pages._base(key)
    refresh(base, wait)
    out = _git(base, "log", "-1", "--format=%ct", "--diff-filter=d", f"HEAD..{REF}", "--", f"./{key}.md")
    ts = int(out) if out.isdigit() else 0
    return ts if ts and ts >= since else 0


def ct_changed(key: str, since: float) -> bool:
    """True when the page's compiled truth at the fetched commit differs from its version at `since`; a page that had no version by then counts any put.
    False when a read fails or takes too long: what cannot be told settles nothing."""
    base, path = _pages._base(key), f"./{key}.md"      # ./ = relative to the pages directory, which may sit inside a larger repository
    now = _read(base, "show", f"{REF}:{path}")
    last = _read(base, "log", "-1", f"--before={int(since)}", "--format=%H", REF, "--", path)
    if now is None or last is None:
        return False
    last = last.strip()
    if not last:
        return True
    held = _read(base, "ls-tree", "--name-only", last, "--", path)
    if held is None:
        return False
    if not held.strip():
        return True        # the last commit by then removed the page
    before = _read(base, "show", f"{last}:{path}")
    return before is not None and _pages.compiled_truth(before) != _pages.compiled_truth(now)
