#!/usr/bin/env python3
"""tools/snapshot_regen.py — release.sh's mend for the one conflict that is no author's to resolve: tests/tool_text.snapshot.json, a generated file.

When two PRs both change tool text, merging main into the later one conflicts on the snapshot and on nothing else, and the by-hand fix is always the same: merge
main into the branch, take main's snapshot, run `python3 tools/tool_text.py update`, then `check`, commit and push. release.sh calls this when `gh pr update-branch`
(or GitHub's mergeable check) says the PR conflicts with main:

    python3 tools/snapshot_regen.py --repo DIR --branch NAME --head SHA [--base origin/main] [--remote origin]

It works in a temporary worktree of its own (a folder under $TMPDIR, locked with flock while it runs, removed with the worktree on every way out, a SIGTERM and a
SIGINT included), never in the checkout it is given:

    1. merge --base into --head (no commit). A clean merge, or a head that already contains the base, is not this tool's job: declined.
    2. the conflicted paths (git's unmerged entries) must be exactly tests/tool_text.snapshot.json. Any other path, too: declined, and the caller fails as it always did.
    3. take --base's snapshot (git checkout <base> -- <snapshot>), `python3 tools/tool_text.py update`, and nothing but the snapshot may differ from the index after it.
    4. `python3 tools/tool_text.py check` must pass on the result.
    5. commit the merge ("Merge main into <branch>; regenerate the tool-text snapshot") with no hooks, and push it to <remote> as refs/heads/<branch>: a plain push, never
       forced, so a branch that moved since --head (its author pushed) is refused and the caller fails as before. No GitHub API call is made: only git's own transport.

stdout: one line, `pushed <sha>` (exit 0) or `declined: <why>` (exit 1); the details go to stderr. Exit 2: a bug (the traceback is on stderr). The caller treats anything but 0
as "not mended". tool_text.py's `update` and `check` need fastmcp and re-execute themselves through the tests' uv environment, so uv must be on PATH (the release unit's is)."""
from __future__ import annotations

import argparse
import fcntl
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

SNAPSHOT_REL = "tests/tool_text.snapshot.json"
UPDATE = ["python3", "tools/tool_text.py", "update"]
CHECK = ["python3", "tools/tool_text.py", "check"]
STEP_TIMEOUT = int(os.environ.get("SNAPSHOT_REGEN_TIMEOUT", "900"))   # seconds for each of update and check (they start uv and import the server)
PUSH_TIMEOUT = 180
IDENT = ["-c", "user.name=stackshot release", "-c", "user.email=release@stackshot.invalid"]   # used only when the repo has no identity of its own


class Declined(Exception):
    pass


def log(msg: str) -> None:
    print(f"snapshot_regen: {msg}", file=sys.stderr, flush=True)


def git(cwd: str | Path, *args: str, timeout: int = 120, check: bool = False, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", **(extra_env or {})}
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=timeout, env=env)
    if check and r.returncode != 0:
        raise Declined(f"git {args[0]} failed: {tail(r)}")
    return r


def tail(r: subprocess.CompletedProcess) -> str:
    lines = [ln for ln in (r.stderr + "\n" + r.stdout).splitlines() if ln.strip()]
    return lines[-1][:300] if lines else f"exit {r.returncode}, no output"


def conflicted_paths(wt: Path) -> list[str]:
    r = git(wt, "diff", "--name-only", "--diff-filter=U", "-z")
    return sorted(p for p in r.stdout.split("\0") if p)


def regen(repo: str, branch: str, head: str, base_ref: str, remote: str) -> str:
    """Returns the pushed merge commit's sha, or raises Declined(why)."""
    if not re.fullmatch(r"[A-Za-z0-9._][A-Za-z0-9._/-]*", branch) or ".." in branch:
        raise Declined(f"the branch name {branch!r} is not one this tool pushes to")
    if not re.fullmatch(r"[0-9a-f]{7,64}", head):
        raise Declined(f"{head!r} is not a commit sha")
    if git(repo, "cat-file", "-e", f"{head}^{{commit}}").returncode != 0:
        raise Declined(f"the PR head {head[:7]} is not among the commits this checkout has")
    base = git(repo, "rev-parse", "--verify", "--quiet", f"{base_ref}^{{commit}}").stdout.strip()
    if not base:
        raise Declined(f"cannot read {base_ref}")
    if git(repo, "merge-base", "--is-ancestor", base, head).returncode == 0:
        raise Declined(f"the PR head {head[:7]} contains {base_ref} {base[:7]} already: there is nothing to merge")
    tmp = tempfile.mkdtemp(prefix="stackshot-regen-")
    lockfd = -1
    wt = Path(tmp) / "wt"
    added = False
    try:
        lockfd = os.open(tmp, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)   # systemd-tmpfiles ageing skips a folder that holds a flock
        fcntl.flock(lockfd, fcntl.LOCK_EX)
        r = git(repo, "worktree", "add", "--quiet", "--detach", str(wt), head)
        if r.returncode != 0:
            raise Declined(f"cannot make the temporary worktree: {tail(r)}")
        added = True
        ident = [] if git(wt, "config", "user.email").stdout.strip() else IDENT
        m = git(wt, *ident, "merge", "--no-commit", "--no-ff", "--quiet", base)   # a merge needs an identity even when it stops before the commit
        if m.returncode == 0:
            raise Declined(f"merging {base_ref} {base[:7]} into {head[:7]} locally has no conflict: not a snapshot conflict")
        paths = conflicted_paths(wt)
        if paths != [SNAPSHOT_REL]:
            raise Declined("the conflict is not only the snapshot: " + (", ".join(paths[:6]) + (f" and {len(paths) - 6} more" if len(paths) > 6 else "") if paths else f"git could not merge ({tail(m)})"))
        log(f"the only conflicted path is {SNAPSHOT_REL}: taking {base_ref} {base[:7]}'s copy and running tool_text.py update")
        git(wt, "checkout", base, "--", SNAPSHOT_REL, check=True)
        r = subprocess.run(UPDATE, cwd=wt, capture_output=True, text=True, timeout=STEP_TIMEOUT)
        if r.returncode != 0:
            raise Declined(f"tool_text.py update failed: {tail(r)}")
        stray = sorted(p for p in git(wt, "diff", "--name-only", "-z").stdout.split("\0") if p and p != SNAPSHOT_REL)
        if stray:
            raise Declined("tool_text.py update changed more than the snapshot: " + ", ".join(stray[:6]))
        git(wt, "add", "--", SNAPSHOT_REL, check=True)
        r = subprocess.run(CHECK, cwd=wt, capture_output=True, text=True, timeout=STEP_TIMEOUT)
        if r.returncode != 0:
            raise Declined(f"tool_text.py check fails on the regenerated snapshot: {tail(r)}")
        c = git(wt, *ident, "-c", "core.hooksPath=/dev/null", "commit", "--quiet", "--no-verify", "-m",
                f"Merge main into {branch}; regenerate the tool-text snapshot",
                "-m", f"release.sh: the only conflicted path was {SNAPSHOT_REL}; main's copy was taken and tools/tool_text.py update, then check, were run.")
        if c.returncode != 0:
            raise Declined(f"the merge commit failed: {tail(c)}")
        new = git(wt, "rev-parse", "HEAD", check=True).stdout.strip()
        log(f"update and check passed; committed the merge {new[:7]}; pushing it to {remote} {branch}")
        p = git(repo, "push", "--quiet", remote, f"{new}:refs/heads/{branch}", timeout=PUSH_TIMEOUT)   # plain: a branch that moved since --head is refused (not a fast-forward)
        if p.returncode != 0:
            raise Declined(f"the push to {remote} {branch} was refused or failed: {tail(p)}")
        return new
    finally:
        try:
            if added:
                git(repo, "worktree", "remove", "--force", str(wt))
            git(repo, "worktree", "prune")
        finally:
            if lockfd >= 0:
                os.close(lockfd)
            shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", required=True, help="the checkout (its object store and its remote are used; its files are never touched)")
    ap.add_argument("--branch", required=True, help="the PR's head branch on the remote")
    ap.add_argument("--head", required=True, help="the PR head the caller knows (full sha); the merge is made on it, so a later push to the branch refuses ours")
    ap.add_argument("--base", default="origin/main", help="main as the checkout knows it (default origin/main; the caller fetched it)")
    ap.add_argument("--remote", default="origin")
    a = ap.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))   # the finally above runs: the worktree and its folder go
    try:
        new = regen(a.repo, a.branch, a.head, a.base, a.remote)
    except Declined as e:
        print(f"declined: {e}")
        return 1
    except subprocess.TimeoutExpired as e:
        print(f"declined: {e.cmd[:3]} timed out after {e.timeout} s")
        return 1
    print(f"pushed {new}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
