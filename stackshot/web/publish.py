"""publish.py — the stackshot publisher.

publish()   refresh the version tracker + the project-page registry, render board.md from the
            store, commit board-data/ + board.md + projects.json when anything changed, fetch/rebase/push. One flock; safe to call often.
bump()      refresh the latest-version lookups (npm, gbrain releases), then publish; installed versions come from the
            fleet state the fleet tool writes before calling it. `--host` is accepted and ignored (the split).
brief()     the one-line brief + top items (session-start banner).
flush       (CLI) publish, then verify board-data is committed and pushed — the item reboot hook's stop step.

CLI:  publish.py publish | flush | bump [--host <fleet-name>] | brief | render [full|brief]
The server imports this and calls publish() after every write (debounced), on its timer and when the fleet state changes.
_publish()  the debounced call the server makes after a write (with `_publish_now`, `_publish_if_idle`, the timer `_PUB_TIMER` and its lock); a burst of writes publishes once, a few seconds after the first.
"""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import fcntl
import os
import subprocess
import sys
import threading
from pathlib import Path

from stackshot.core import config as _cfg  # noqa: E402
from stackshot.projects import pages as _pages  # noqa: E402
from stackshot.projects import project_registry as _preg  # noqa: E402  — roles.json and projects.json follow a publish
from stackshot.web.board_home import _board_home_drop  # noqa: E402  — a publish drops the board's kept home
from stackshot.core import readonly as _ro  # noqa: E402  — a warm standby copy renders in memory only (server._ro_board), never here
from stackshot.fleet import versions as _ver  # noqa: E402
from stackshot.web.render import render, render_all  # noqa: E402

REPO = _cfg.path("paths", "repo")
DATA = _cfg.path("paths", "store")
OUT = _cfg.path("paths", "markdown")
DATA_REL = str(DATA.relative_to(REPO))
OUT_REL = str(OUT.relative_to(REPO))
LOCK = _cfg.state("publish.lock")        # one publish at a time
# [paths] is restart-only (config.RESTART_ONLY); [publish] git is read at use, so a reload is live at once.


def _git_on() -> bool:      # false: render only, never fetch, commit or push (a staging instance)
    return bool(_cfg.get("publish", "git", default=True))


def _git(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=check)


def _gitsync(msg: str, *paths: str) -> None:
    """Commit the given paths and push. `--only` with the pathspecs: the server shares this checkout with every session on
    the host, and a plain commit swept in whatever a session had staged (a deletion went out under a board message)."""
    have = [p for p in paths if (REPO / p).exists()]
    for p in have:
        _git("add", "-A", "--", p)
    committed = False
    if have and _git("diff", "--cached", "--quiet", "--", *have).returncode != 0:
        _git("commit", "--quiet", "--only", "-m", msg, "--", *have); committed = True
    if not committed and _git("rev-list", "--count", "@{u}..HEAD").stdout.strip() in ("", "0"):
        return                                                   # a quiet publish: nothing to push, no fetch or rebase either
    if _git("fetch", "--quiet", "origin", "main").returncode != 0:
        return
    if _git("rebase", "--autostash", "--quiet", "origin/main").returncode != 0:
        _git("rebase", "--abort")
        return
    _git("push", "--quiet", "origin", "main")


def publish(force_versions: bool = False, host: str = "") -> str:
    """Render + commit + push. Returns the brief's first line."""
    _ro.guard("publish: files, versions, registry, commit and push")
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        # other writers' commits to the repo arrive through git (the fleet's heartbeats no longer do: fleet.py)
        if _git_on() and _git("fetch", "--quiet", "origin", "main").returncode == 0:
            _git("merge", "--ff-only", "--quiet", "origin/main")
        try: _ver.write(force=force_versions)                # installed vs latest for the Machines panel (versions.py; a host is not needed)
        except Exception as e: print(f"versions: {e}", file=sys.stderr)
        try: _pages.cmd_registry(quiet=True)                  # the page registry from the brain mirror, one git pass
        except Exception as e: print(f"registry: {e}", file=sys.stderr)
        r = render_all(str(DATA))                              # one load of the store, both renders
        md = r["full"]
        if len(md) < 200:                                # never overwrite the board with an empty render
            fcntl.flock(lf, fcntl.LOCK_UN)
            raise RuntimeError(f"render produced {len(md)} md chars — board left untouched")
        tmp = OUT.with_suffix(".md.tmp"); tmp.write_text(md, encoding="utf-8"); os.replace(tmp, OUT)
        first = r["brief"].splitlines()[0].replace("Board: ", "", 1) if md else "board"
        if _git_on(): _gitsync(f"board: {first}", OUT_REL, DATA_REL)
        fcntl.flock(lf, fcntl.LOCK_UN)
    return first


def bump(host: str = "") -> str:
    return publish(force_versions=True, host=host)


def brief() -> str:
    return render(str(DATA), "brief")


# ---------------------------------------------------------------------------- the debounced publish the server makes after a write
# The timer and the lock `_publish` and `_publish_if_idle` share live here; a suite that needs a live or a missing timer sets `_PUB_TIMER` on this module, and one that stubs the publish the Runners panel asks for sets
# `_publish` here too. Server.py calls the same names through its own imports.
_PUB_LOCK = threading.Lock()
_PUB_TIMER: threading.Timer | None = None


def _publish_debounce() -> float:
    return float(_cfg.get("publish", "debounce_seconds", default=5))


def _publish_every() -> float:
    return float(_cfg.get("publish", "every_minutes", default=10)) * 60   # default as in the example


def _publish_now(force_versions: bool = False, host: str = "") -> str:
    if _ro.is_read_only():                  # a standby copy renders in memory when asked (_ro_board), and publishes nothing
        return "(read-only standby: nothing published)"
    try:
        return publish(force_versions=force_versions, host=host)
    except Exception as e:  # never let a publish failure surface as a tool error
        return f"(publish failed: {e})"
    finally:
        _preg._roles_sync_safe()            # the publish rebuilt the registry; roles.json follows it


def _publish() -> None:
    """Debounced: a burst of writes in one turn publishes once, ~5 s after the first."""
    global _PUB_TIMER
    _board_home_drop()                         # the home is drawn per request: a write is on it at the next read, not at the publish
    if _ro.is_read_only():                  # no timer is started on a standby copy
        return
    with _PUB_LOCK:
        if _PUB_TIMER is not None and _PUB_TIMER.is_alive():
            return
        _PUB_TIMER = threading.Timer(_publish_debounce(), _publish_now)
        _PUB_TIMER.daemon = True
        _PUB_TIMER.start()


def _publish_if_idle() -> bool:
    """For the Runners panel (runners.ON_CHANGE): True when a publish was scheduled; False while the debounce timer's publish is still running (it stays alive through
    the whole _publish_now, git push included, and _publish returns silently then, so a request made in that time would be lost): the panel asks again a few seconds later."""
    if _ro.is_read_only():
        return True
    with _PUB_LOCK:
        if _PUB_TIMER is not None and _PUB_TIMER.is_alive():
            return False
    _publish()
    return True


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a else "publish"
    if cmd == "publish":
        print(publish())
    elif cmd == "bump":
        h = a[a.index("--host") + 1] if "--host" in a and a.index("--host") + 1 < len(a) else ""
        print(bump(h))
    elif cmd == "flush":            # reboot hook: last render + board-data commit, pushed; exit 0 only if nothing is left
        print(publish())
        if not _git_on(): print("git is off for this instance ([publish] git = false): nothing to flush"); sys.exit(0)
        dirty = _git("status", "--porcelain", "--", str(DATA)).stdout.strip()
        head = _git("rev-parse", "--short", "HEAD").stdout.strip()
        if "origin" not in _git("remote").stdout.split():      # a local-only data repository: committed is all there is
            if dirty:
                sys.exit(f"board-data not flushed: {len(dirty.splitlines())} uncommitted path(s) (no origin remote)")
            print(f"board-data committed (HEAD {head}); no origin remote, so nothing was pushed"); sys.exit(0)
        f = _git("fetch", "--quiet", "origin", "main")
        if f.returncode != 0:
            why = (f.stderr.strip().splitlines() or ["?"])[-1]
            sys.exit(f"board-data not flushed: cannot fetch main from origin ({why}); {len(dirty.splitlines())} uncommitted path(s)")
        ahead = _git("rev-list", "--count", "origin/main..HEAD").stdout.strip()
        if dirty or ahead not in ("", "0"):
            sys.exit(f"board-data not flushed: {len(dirty.splitlines())} uncommitted path(s), {ahead} commit(s) not pushed")
        print(f"board-data committed and pushed (HEAD {head})")
    elif cmd == "brief":
        sys.stdout.write(brief())
    elif cmd == "render":
        sys.stdout.write(render(str(DATA), a[1] if len(a) > 1 else "full"))
    else:
        sys.exit("usage: publish.py publish | flush | bump [--host H] | brief | render [full|brief]")
