"""memo_files_clean.py: `stackshot memo-files-clean [--dry-run]`, the daily pass over the memo-box files (docs/memo-files.md): the files of an item are removed 30 days after the item closed
(and when the newest of them is 30 days old too, so a note put on an old closed item is not removed the day it is sent), and an upload that was never sent with a note is removed after 24 hours.

The close time of an item is its `state_updated` stamp (the time of its last state change, which the closing write sets), else `updated`; an open item, an item that cannot be read and an item that is not in the store keep their
files (a file is never removed on a doubt). It prints one line, `memo files: removed N items, M pending uploads; K items keep files; <size> in use`, and exits 0, and 1 when the sweep itself failed. On a read-only standby (STACKSHOT_READ_ONLY=1, or a `.synced-at` marker in the store) it changes nothing and exits 0:
the standby's copy of the data is the server's to change. `--dry-run` says what it would remove and removes nothing. Run daily by units/stackshot-memo-files-clean.timer."""
from __future__ import annotations

import os
import sys
from typing import Any

from stackshot.service import memo_files as _memo
from stackshot.service import store as _svcstore


def closed_at(gid: str) -> float:
    """When item `gid` closed (epoch seconds); 0 while it is open, and for an item that cannot be read."""
    try:
        item: dict[str, Any] = _svcstore._load(gid)
    except Exception:       # noqa: BLE001 — a doubt keeps the files
        return 0.0
    if item.get("status") != "completed":
        return 0.0
    try:
        return float(item.get("state_updated") or item.get("updated") or 0)
    except (TypeError, ValueError):
        return 0.0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if any(a not in ("--dry-run",) for a in args):
        print("usage: stackshot memo-files-clean [--dry-run]", file=sys.stderr)
        return 2
    from stackshot.core import config as _cfg
    from stackshot.core import readonly as _ro
    if os.environ.get("STACKSHOT_READ_ONLY") == "1" or os.path.exists(os.path.join(str(_cfg.path("paths", "store")), _ro.MARKER)):      # a read-only standby (its environment says so, or its store carries the copy job's marker)
        print("memo files: a read-only standby changes nothing")
        return 0
    dry = "--dry-run" in args
    try:
        out = _memo.sweep(closed_at, dry_run=dry)
    except Exception as e:      # noqa: BLE001 — said, and the unit fails
        print(f"memo files: the sweep failed: {e.__class__.__name__}: {e}", file=sys.stderr)
        return 1
    verb = "would remove" if dry else "removed"
    print(f"memo files: {verb} {len(out['items'])} items, {len(out['pending'])} pending uploads; {out['kept']} items keep files; {_memo.size_words(out['bytes'])} in use")
    for g in out["items"]:
        print(f"  items: {g}")
    for p in out["pending"]:
        print(f"  pending: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
