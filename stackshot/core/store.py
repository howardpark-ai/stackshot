"""store.py: the one store at the bottom layer: where it is (`STORE`, [paths] store), every item file in it, the next item id, and the write of one item file.

What reads an item (`_path`, `_load`) is service/store.py's: it resolves a moved item's old id through github/ghsync and reads the item through model/, both layers above this one, and an import
upward is what tests/layers_scenario.py refuses. `save`, the one writer, is service/writes.py's, with the item lock; the write of the file it ends with is `_write_item` here.
A suite that points the server at a copy of the store sets `STORE` on this module (`core_store.STORE = ...`), the one place it is read from: the readers in service/store.py and the server's own
reads (`_store.STORE`) see the same value. `NEXT_ID` is read where this module was imported, as it was when it lived in server.py."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg
from stackshot.core import readonly as _ro

STORE = _cfg.path("paths", "store")
LETTER = str(_cfg.get("ids", "letter") or "s")
NEXT_ID = STORE / "next-id"


def _item_files() -> list[tuple[str, Path]]:
    """Every item file in the store as (gid, path), across all letter dirs."""
    out = []
    for d in sorted(STORE.iterdir()):
        if not (d.is_dir() and len(d.name) == 1 and d.name.isalpha()):
            continue
        for p in d.glob("*.json"):
            if p.name.startswith(".") or not p.stem.isdigit():
                continue
            out.append((f"{d.name}{p.stem}", p))
    return sorted(out, key=lambda t: (t[0][0], int(t[0][1:])))


def _next_id() -> str:
    """Allocate the next global id. The file is the single counter; seeded from the highest id in the store."""
    import fcntl
    _ro.guard("id allocation")                # next-id is part of the store
    NEXT_ID.parent.mkdir(parents=True, exist_ok=True)
    with open(NEXT_ID, "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        raw = f.read().strip()
        cur = int(raw) if raw.isdigit() else 0
        if cur == 0:
            cur = max([int(g[1:]) for g, _ in _item_files()] or [0])
        nxt = cur + 1
        f.seek(0); f.truncate(); f.write(str(nxt)); f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)
    return f"{LETTER}{nxt}"


def _write_item(p: Path, item: dict[str, Any]) -> None:
    """Write one item's file whole: a temp file beside it, then a rename over it, so a reader never sees half of it."""
    tmp = p.with_name(f".{p.name}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(item, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
