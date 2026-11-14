"""close_repair.py — the pure half of tools/restore_close_descriptions.py: finding the descriptions that a close replaced.

Until a close kept the description, `complete` told the closing session to rewrite the description to the end state, so a closed item's description stopped saying what the
item was about (the old text survived only in the History). A close now stores its summary in `metadata.outcome_text` and leaves the description alone. This module reads an item's
revisions from the store's git (one commit per saved revision, as the item page's History reads them) and says, for an item closed in the last N days, what its description was
just before the close and whether it has changed since.

    versions(store_dir, path)                       the item's file at every commit that touched it, oldest first, then the file on disk when it differs from the last commit
    row_for(gid, cur, vers, now, days)              (row, "") for an item to repair, (None, why) for one to leave: the reasons are in SKIP_WHY

Nothing here writes; migrations._close_description_repair saves the rows. Reads only: `git log`, `git cat-file`, the item file."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

DAY = 86400.0

SKIP_WHY = {
    "open": "not closed",
    "old": "closed before the window",
    "no_history": "the store's git has no earlier revision",
    "no_close": "no revision shows the close",
    "kept": "the description is already what it was before the close",
    "empty": "the revision before the close has no description",
    "edited": "the description was edited after the close",
    "has_outcome": "has outcome text",
}


def versions(store_dir: str | os.PathLike[str], path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """The item's JSON at every commit of the store's git that touched its file, oldest first, then the file on disk when it differs from the last commit (the server commits on a
    debounce, so the newest write may not be in git yet). A store outside git, or git failing → just the file on disk (or [])."""
    d = str(store_dir)
    rel = os.path.relpath(str(path), d)

    def git(*args: str, inp: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(["git", "-C", d, *args], input=inp, capture_output=True, timeout=30, check=False)

    out: list[dict[str, Any]] = []
    try:
        lg = git("log", "--follow", "--name-only", "--format=%x01%H", "--", rel)
        if lg.returncode == 0:
            commits: list[tuple[str, str]] = []
            for chunk in lg.stdout.decode("utf-8", "replace").split("\x01")[1:]:
                head, _, rest = chunk.partition("\n")
                at = next((x.strip() for x in rest.splitlines() if x.strip()), "")      # the file's path at that commit (a rename is followed)
                if head.strip() and at:
                    commits.append((head.strip(), at))
            commits.reverse()
            if commits:
                buf = git("cat-file", "--batch", inp="".join(f"{sha}:{at}\n" for sha, at in commits).encode()).stdout
                i = 0
                for _sha, _at in commits:
                    nl = buf.find(b"\n", i)
                    if nl < 0:
                        break
                    hdr = buf[i:nl].split()
                    i = nl + 1
                    if len(hdr) < 3 or hdr[1] != b"blob":      # "<name> missing"
                        continue
                    n = int(hdr[2])
                    body = buf[i:i + n]
                    i += n + 1
                    try:
                        v = json.loads(body)
                    except ValueError:
                        continue
                    if isinstance(v, dict):
                        out.append(v)
    except (OSError, subprocess.SubprocessError):
        out = []
    try:
        with open(path, encoding="utf-8") as f:
            cur = json.load(f)
    except (OSError, ValueError):
        cur = None
    if isinstance(cur, dict) and (not out or out[-1] != cur):
        out.append(cur)
    return out


def _stamp(v: dict[str, Any]) -> float:
    """When a revision was written: its state clock, else its item clock."""
    try:
        return float(v.get("state_updated") or v.get("updated") or 0)
    except (TypeError, ValueError):
        return 0.0


def close_index(vers: list[dict[str, Any]]) -> int:
    """The index of the revision that closed the item the last time: the first of the run of completed revisions that ends the list. -1 when the item is not completed at the end,
    or has no revision before that run (nothing to restore from)."""
    if not vers or vers[-1].get("status") != "completed":
        return -1
    i = len(vers) - 1
    while i > 0 and vers[i - 1].get("status") == "completed":
        i -= 1
    return i


def row_for(gid: str, cur: dict[str, Any], vers: list[dict[str, Any]], now: float, days: float) -> tuple[dict[str, Any] | None, str]:
    """For an item (its file as stored now, its revisions): (the row to repair, "") or (None, the key of SKIP_WHY). The row: {gid, closed_at, before (the description now, which
    the close wrote), after (the description of the revision before the close), outcome_text (what the outcome text becomes: `before`)}.

    Left alone: an item not closed, one closed before the window, one with no revision before its close, one whose description already equals the earlier one (a close that
    did not rewrite it, or an item already repaired), one whose description is not the one the close wrote (somebody edited it afterwards: that edit stays), and one whose earlier
    description is empty, and one that already has an outcome text (it would be overwritten or its text lost)."""
    if cur.get("status") != "completed":
        return None, "open"
    c = close_index(vers)
    if c < 0:
        return None, "no_close"
    if c == 0:
        return None, "no_history"
    at = _stamp(vers[c]) or _stamp(cur)
    if now - at > days * DAY:
        return None, "old"
    before, after = str(cur.get("description") or ""), str(vers[c - 1].get("description") or "")
    if not after.strip():
        return None, "empty"
    if before.strip() == after.strip():
        return None, "kept"
    if before.strip() != str(vers[c].get("description") or "").strip():
        return None, "edited"
    if str((cur.get("metadata") or {}).get("outcome_text") or "").strip():
        return None, "has_outcome"      # its close already wrote an outcome text: moving the description into it would drop that one, so the item is left to be looked at by hand
    return {"gid": gid, "closed_at": at, "before": before, "after": after, "outcome_text": before.strip()}, ""


def scan(store_dir: str | os.PathLike[str], files: list[tuple[str, Path]], now: float, days: float) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Every file of `files` ((gid, path), as server._item_files lists them) read against its history → (the rows to repair, a count per SKIP_WHY key). An item that was not
    touched since the window opened is not read from git at all: a close is a write, so its clock is inside the window."""
    rows: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}

    def skip(why: str) -> None:
        skipped[why] = skipped.get(why, 0) + 1

    for gid, p in files:
        try:
            with open(p, encoding="utf-8") as f:
                cur = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(cur, dict):
            continue
        if cur.get("status") != "completed":
            skip("open")
            continue
        if now - max(_stamp(cur), 0.0) > days * DAY and _stamp(cur):
            skip("old")
            continue
        row, why = row_for(gid, cur, versions(store_dir, p), now, days)
        if row is None:
            skip(why)
        else:
            rows.append(row)
    return rows, skipped
