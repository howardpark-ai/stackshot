"""publish.py — the stackshot publisher.

publish()   refresh the version tracker + the project-page registry, render board.md from the
            store, commit board-data/ + board.md + projects.json when anything changed, fetch, then push, fast-forward or (diverged on disjoint files) merge off the live tree; never a rebase. One flock; safe to call often.
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
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from stackshot.core import config as _cfg  # noqa: E402
from stackshot.projects import pages as _pages  # noqa: E402
from stackshot.projects import project_registry as _preg  # noqa: E402  — roles.json and projects.json follow a publish
from stackshot.web.board_home import _board_home_drop  # noqa: E402  — a publish drops the board's kept home
from stackshot.core import readonly as _ro  # noqa: E402  — a warm standby copy renders in memory only (_ro_board in web/routes/board_pages.py), never here
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


_NOTED: dict[str, float] = {}      # kind of note -> when it was last printed (time.monotonic)
_NOTE_EVERY = 3600.0               # a note repeats at most hourly per process: the publish runs every few seconds after a write


def _note(kind: str, text: str) -> None:
    now = time.monotonic()
    if kind in _NOTED and now - _NOTED[kind] < _NOTE_EVERY:
        return
    _NOTED[kind] = now
    print(text, file=sys.stderr)


_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+|\S+@\S+:\S+")      # an address, whatever its scheme (an scp-style one included)


def _why(r: subprocess.CompletedProcess) -> str:
    """Why a push was refused, in the mirror's own words (its first `remote:` line) or the ref's rejection; a line that carries an address is skipped."""
    lines = [l.strip() for l in r.stderr.splitlines()]
    for pick in (lambda l: l.startswith("remote:"), lambda l: "rejected]" in l):
        for l in lines:
            if pick(l) and not _URL.search(l) and l.removeprefix("remote:").strip():
                return l
    return "no reason given"


def _refused(r: subprocess.CompletedProcess) -> str:
    """The line of a refused `git merge` that says why (a `fatal:` or `error:` line, else the first), with the file it names when git's next line does (a tab-indented path under "would be overwritten")."""
    lines = [l for l in r.stderr.splitlines() if l.strip()]
    if not lines:
        return "no reason given"
    at = next((i for i, l in enumerate(lines) if l.startswith(("fatal:", "error:"))), 0)
    files = [l.strip() for l in lines[at + 1:] if l.startswith(("\t", "    "))]
    return lines[at].strip() + (f" ({files[0]})" if files else "")


def _identity() -> dict[str, str]:
    """The environment a commit made off the live tree needs: the store clone's own configured identity, and where it has none the author of its last commit."""
    env = {}
    for key, cfg, fmt in (("NAME", "name", "an"), ("EMAIL", "email", "ae")):
        v = _git("config", f"user.{cfg}").stdout.strip() or _git("log", "-1", f"--format=%{fmt}").stdout.strip()
        if v:
            env[f"GIT_AUTHOR_{key}"] = env[f"GIT_COMMITTER_{key}"] = v
    return env


_MID = ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD")      # what git leaves in its directory while an operation of a session is unfinished


def _midway() -> str:
    """What the store clone is in the middle of, as a phrase, or "" when the publisher's git step may run: a session's rebase, merge, cherry-pick or revert that is
    not finished, a detached HEAD (a checkout of a commit, a rebase stopped at `edit`) or a branch with no commit yet. A commit, a merge or a push made then would land on that
    HEAD, not on the branch, and be lost or stranded. The git directory is asked for, not assumed: in a linked worktree `.git` is a file."""
    g = _git("rev-parse", "--git-dir")
    if g.returncode != 0 or not g.stdout.strip():
        return ""                                                                        # not a repository at all: the git step fails on its own, as it always did
    here = REPO / g.stdout.strip()
    found = next((m for m in _MID if (here / m).exists()), "")
    if found:
        return "in the middle of a " + {"rebase-merge": "rebase", "rebase-apply": "rebase", "MERGE_HEAD": "merge", "CHERRY_PICK_HEAD": "cherry-pick", "REVERT_HEAD": "revert"}[found]
    if _git("symbolic-ref", "-q", "HEAD").returncode != 0:
        return "on a detached HEAD"
    if _git("rev-parse", "--verify", "-q", "HEAD").returncode != 0:
        return "on a branch with no commit yet"
    return ""


def _gitsync(msg: str, *paths: str) -> None:
    """Commit the given paths and push. `--only` with the pathspecs: the server shares this checkout with every session on
    the host, and a plain commit swept in whatever a session had staged (a deletion went out under a board message).
    While a session has the clone midway through something (`_midway`) the whole step is skipped, with one note an hour, and the files stay as they are."""
    if (why := _midway()):
        _note("midway", f"publish: the store clone is {why}; the git step (commit, merge, push) waits until it is finished")
        return
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
    # Nothing here rebases, stashes or checks out: a rebase of a diverged clone rewrote the live working tree for seconds on every attempt and a write made
    # then was lost. Where origin stands decides the step. Other writers (an editor on a laptop, a session on the host) push pages to the same repository, so
    # the clone can diverge from origin on DISJOINT files, and that heals by a merge made off the live tree (`merge-tree` and `commit-tree` touch no file; the
    # fast-forward to the merge changes only files the origin side changed, and git refuses it where one has an uncommitted edit). A real conflict is left
    # alone and noted once an hour: it needs a manual fix.
    def push() -> None:
        r = _git("push", "--quiet", "origin", "main")
        if r.returncode != 0:
            _note("push", f"publish: git push was refused: {_why(r)}")
    def forward(target: str, was: str = "") -> bool:
        r = _git("merge", "--ff-only", "--no-autostash", "--quiet", target)
        if r.returncode != 0 and not (was and _git("rev-parse", "HEAD").stdout.strip() != was):    # a session that committed meanwhile is no failure: the next cycle makes the merge again
            _note("merge", f"publish: fast-forward to the mirror failed: {_refused(r)}")
        return r.returncode == 0
    # Both refs are read once, here: every step below works on these two commits, never on the names again. A name read twice can have moved between the reads
    # (a session commits in this checkout, a fetch moves origin/main), and a merge commit whose tree came from one pair of commits and whose parents are another
    # pair is accepted by the fast-forward and drops a file.
    heads = [_git("rev-parse", "--verify", ref) for ref in ("HEAD", "origin/main")]
    if any(h.returncode != 0 or not h.stdout.strip() for h in heads):
        _note("refs", f"publish: could not read the store's or the mirror's head (git exit {max(h.returncode for h in heads)}); nothing pushed")
        return
    mine, theirs = (h.stdout.strip() for h in heads)
    up = _git("merge-base", "--is-ancestor", theirs, mine).returncode                    # 0: origin is behind or equal; 1: not; more: git failed
    if up == 0:                                                                          # push what origin lacks
        if _git("rev-list", "--count", f"{theirs}..{mine}").stdout.strip() not in ("", "0"):
            push()
        return
    down = _git("merge-base", "--is-ancestor", mine, theirs).returncode if up == 1 else up
    if up > 1 or down > 1:
        _note("refs", f"publish: could not compare the store with its mirror (git exit {max(up, down)}); nothing pushed")
    elif down == 0:                                                                      # the store is behind: only adds the newer remote files
        forward(theirs, was=mine)                                                        # a session that commits between the read and the merge is no failure either
    else:                                                                                # diverged
        mt = _git("merge-tree", "--write-tree", mine, theirs)
        if mt.returncode == 0 and mt.stdout.split():
            c = subprocess.run(["git", "-C", str(REPO), "commit-tree", mt.stdout.split()[0], "-p", mine, "-p", theirs, "-m", "board: merge the mirror's commits"],
                               capture_output=True, text=True, env={**os.environ, **_identity()})
            if c.returncode != 0 or not c.stdout.strip():
                _note("merge", f"publish: could not make the merge with the mirror: {(c.stderr.strip().splitlines() or ['no reason given'])[0]}")
            elif forward(c.stdout.strip(), was=mine):                                    # refused where HEAD is no longer `mine`: nothing is lost, the next cycle merges again
                push()
        elif mt.returncode == 1:                                                         # a real conflict: left as it is
            n = _git("rev-list", "--left-right", "--count", f"{mine}...{theirs}").stdout.split()
            local, remote = (n + ["?", "?"])[:2]
            _note("diverged", f"publish: the store and its mirror have diverged and conflict; the live store is left as it is, and it needs a manual merge (local {local} ahead, origin {remote} ahead)")
        else:
            _note("mergetree", f"publish: could not check the store against its mirror (git exit {mt.returncode}); nothing pushed")


def publish(force_versions: bool = False, host: str = "") -> str:
    """Render + commit + push. Returns the brief's first line."""
    _ro.guard("publish: files, versions, registry, commit and push")
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        # other writers' commits to the repo arrive through git (the fleet's heartbeats no longer do: fleet.py)
        if _git_on() and not _midway() and _git("fetch", "--quiet", "origin", "main").returncode == 0:
            _git("merge", "--ff-only", "--no-autostash", "--quiet", "origin/main")
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
