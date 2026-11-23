"""item_history.py: the commits of the store's git that touched one item's file, newest first, as the History of the item page and the search index read them.

`git log --follow` weighs every commit of the whole store for a rename, which takes over a second of CPU on a store of thousands of commits, and the search index asks for it each time an item changes. The answer
is kept per item with the HEAD it was read at. When HEAD is the same the answer is the one kept. When HEAD has moved, the commits since are asked for alone (a plain `git log` of `<kept HEAD>..HEAD`, a few commits, no
rename weighing) and put in front of the ones kept, but only when that is the answer the whole walk would give: the commits since form one straight chain of single-parent commits from the kept HEAD (a merge, a rebase or a
reset makes the order and the set of the walk another one), and every one of them only modified the file at its own path (a creation, a deletion or a rename of it is for the whole walk to follow). Anything else (no answer
kept, a path that is not the one kept, git failing) reads the whole history as before, so the answer is always the one `git log --follow` over everything gives.
Nothing is written to the store. The answer is a tuple of (sha, commit time, the file's path at that commit); git's failure is None (the page then shows no History)."""
from __future__ import annotations

import subprocess
import threading

_FORMAT = "--format=%x01%H%x09%ct"
_MAX = 4096                                  # items kept: the store's open and recent ones; the oldest kept goes first
_CACHE: dict[tuple[str, str], tuple[str, tuple[tuple[str, int, str], ...]]] = {}
_LOCK = threading.Lock()
CALLS = {"log": 0}                           # whole-history reads, counted for the suite that pins the cache


def _git(d: str, *args: str, timeout: int = 10) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", d, *args], capture_output=True, timeout=timeout)


def _parse(out: bytes) -> tuple[tuple[str, int, str], ...]:
    commits = []
    for chunk in out.decode("utf-8", "replace").split("\x01")[1:]:
        head, _, rest = chunk.partition("\n")
        sha, _, ct = head.partition("\t")
        path = next((x.strip() for x in rest.splitlines() if x.strip()), "")      # the file's path at that commit (a rename is followed)
        if sha and path:
            commits.append((sha, int(ct or 0), path))
    return tuple(commits)


def _parse_status(out: bytes, rel: str) -> tuple[tuple[str, int, str], ...] | None:
    """The commits of a plain `--name-status` log, or None when one of them did anything to `rel` but modify it."""
    commits = []
    for chunk in out.decode("utf-8", "replace").split("\x01")[1:]:
        head, _, rest = chunk.partition("\n")
        sha, _, ct = head.partition("\t")
        lines = [x for x in rest.splitlines() if x.strip()]
        if not sha or len(lines) != 1 or lines[0].split("\t") != ["M", rel]:
            return None
        commits.append((sha, int(ct or 0), rel))
    return tuple(commits)


def _straight(d: str, h0: str, head: str) -> bool:
    """Is `head` the end of a straight chain of single-parent commits that starts at `h0`?"""
    r = _git(d, "rev-list", "--parents", f"{h0}..{head}")
    rows = [x.split() for x in r.stdout.decode("ascii", "replace").splitlines() if x.strip()]
    if r.returncode or not rows or rows[0][0] != head or any(len(x) != 2 for x in rows):
        return False
    return all(rows[i][1] == rows[i + 1][0] for i in range(len(rows) - 1)) and rows[-1][1] == h0


def _head(d: str) -> str:
    try:
        r = _git(d, "rev-parse", "--verify", "--quiet", "HEAD")
    except Exception:  # noqa: BLE001
        return ""
    return r.stdout.decode("ascii", "replace").strip() if r.returncode == 0 else ""


def _keep(key: tuple[str, str], head: str, commits: tuple[tuple[str, int, str], ...]) -> None:
    with _LOCK:
        _CACHE.pop(key, None)
        _CACHE[key] = (head, commits)
        while len(_CACHE) > _MAX:
            _CACHE.pop(next(iter(_CACHE)))


def commits(d: str, rel: str) -> tuple[tuple[str, int, str], ...] | None:
    """The commits of the git repository at `d` that touched `rel` (a path under it), newest first, following renames; None when git failed. Raises what `subprocess` raises (a timeout): the caller's handler reads it as git failing."""
    head = _head(d)
    key = (d, rel)
    if head:
        with _LOCK:
            kept = _CACHE.get(key)
        if kept is not None:
            h0, old = kept
            if h0 == head:
                return old
            if old and old[0][2] == rel and _straight(d, h0, head):
                r = _git(d, "log", "--name-status", _FORMAT, f"{h0}..{head}", "--", rel)
                if r.returncode == 0:
                    new = _parse_status(r.stdout, rel)
                    if new is not None:
                        merged = new + old
                        _keep(key, head, merged)
                        return merged
    CALLS["log"] += 1
    r = _git(d, "log", "--follow", "--name-only", _FORMAT, head or "HEAD", "--", rel)
    if r.returncode:
        return None
    out = _parse(r.stdout)
    if head:
        _keep(key, head, out)
    return out
