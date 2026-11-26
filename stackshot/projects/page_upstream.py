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
Bounds: one fetch a copy at a time, begun at most every EVERY s and ended after LIMIT s. A caller waits at most `wait` s counted from the fetch's start, so
many callers together wait no longer than one; a board write never waits (wait 0). A branch with no upstream, a remote that cannot be reached and a fetch
that fails or is slow leave the answer the local copy gives. A read-only standby never fetches.
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
WAIT = 3.0          # the most a client's page-time read waits for a fetch; that client gives the whole read 6 s (pages._api)
LIMIT = 30.0        # a fetch still running after this is ended
END_GRACE = 2.0     # seconds an ended fetch has to remove its lock files before it is ended outright
READ_LIMIT = 5      # seconds one read of the local repository may take

_LOCK = threading.Lock()
_RUNS: dict[str, tuple[float, threading.Event]] = {}     # copy -> (when its last fetch began, set when that fetch is over)
_FAILED: set[str] = set()                                # copies whose last fetch failed: said once, until one works again


def _git(base: str, *args: str) -> str:
    """One read of the local repository: its output, "" when git fails or takes too long."""
    try:
        r = subprocess.run(["git", "-C", base, *args], capture_output=True, text=True, timeout=READ_LIMIT)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


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


def _fetch(base: str, done: threading.Event) -> None:
    try:
        branch = _git(base, "symbolic-ref", "--quiet", "--short", "HEAD")
        remote = _git(base, "config", "--get", f"branch.{branch}.remote") if branch else ""
        upstream = _git(base, "config", "--get", f"branch.{branch}.merge") if remote else ""
        if not upstream:
            return
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
            _FAILED.discard(base)
        elif base not in _FAILED:
            _FAILED.add(base)
            print(f"page upstream: {why} in {base}; page debts are judged by that copy alone until a fetch works", file=sys.stderr)
    except Exception as e:  # noqa: BLE001  — fail-open: the local copy answers as before
        print(f"page upstream: no fetch in {base} ({type(e).__name__})", file=sys.stderr)
    finally:
        done.set()


def refresh(base: str, wait: float = 0.0) -> None:
    """Begin a fetch of the copy's upstream unless one is running or began less than EVERY s ago; then wait for it, at most until `wait` s after it began."""
    if _ro.is_read_only() or not os.path.isdir(base):
        return
    with _LOCK:
        run = _RUNS.get(base)
        if run is None or (run[1].is_set() and time.monotonic() - run[0] >= EVERY):
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
    """True when the page's compiled truth at the fetched commit differs from its version at `since`; a page with no version by then counts any put."""
    now = _pages.ct_in(key, REF)
    if now is None:
        return False
    before = _pages.ct_at(key, since, REF)
    return before is None or before != now
