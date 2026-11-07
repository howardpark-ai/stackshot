#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["markdown-it-py>=4,<5"]
#
# [tool.uv]
# exclude-newer = "2026-10-03T04:00:00Z"
# ///
"""publish.py — the stackshot publisher.

publish()   refresh the version tracker + the project-page registry, render board.md from the
            store, commit board-data/ + board.md + projects.json when anything changed, fetch/rebase/push. One flock; safe to call often.
bump()      refresh the latest-version lookups (npm, gbrain releases), then publish; installed versions come from the
            fleet state the fleet tool writes before calling it. `--host` is accepted and ignored (the split).
brief()     the one-line brief + top items (session-start banner).
flush       (CLI) publish, then verify board-data is committed and pushed — the item reboot hook's stop step.

CLI:  publish.py publish | flush | bump [--host <fleet-name>] | brief | render [full|brief]
The server imports this and calls publish() after every write (debounced), on its timer and when the fleet state changes.
"""
from __future__ import annotations

import fcntl
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config as _cfg  # noqa: E402
import pages as _pages  # noqa: E402
import readonly as _ro  # noqa: E402  — a warm standby copy renders in memory only (server._ro_board), never here
import versions as _ver  # noqa: E402
from render import render, render_all  # noqa: E402

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
