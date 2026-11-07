"""legacy_owner.py — the owner's first name as the old stored forms spelled it, and the one place that derives it.

A legacy owner label stays supported: older stored data may carry forms built from the owner's first name in lower case. The code does not write or act on them. A store's git may still hold commits with them, though, and the History of an item diffs those commits (render.Board.item_versions), so a read-only
step on that path maps the one old needs value to `decision` when it reads an old version. Nothing is ever written back.

The name is never spelled in code: it is the first word of `[instance] owner`, lower case (`name_from_owner`), the same rule `[items_api] owner_mover_kind = "legacy"` uses, so the two cannot drift.
Stdlib only."""
from __future__ import annotations

import re
from typing import Any

GENERIC = {"", "owner", "the", "the owner"}               # a "legacy name" that names no one (the placeholder when an instance sets no owner)


def name_from_owner(owner: Any) -> str:
    """The legacy name for an `[instance] owner` value: its first word in lower case; "" when the owner names no one (unset, the placeholder) or the word is not letters and digits."""
    words = re.findall(r"[^\W_]+", str(owner or "").strip().lower())
    name = words[0] if words else ""
    return "" if name in GENERIC or not re.fullmatch(r"[a-z0-9]+", name) else name


def normalize_needs(needs: Any, name: str) -> tuple[Any, int]:
    """A `needs` value (a list, or the one-word string of the form before) with every entry equal to the legacy `name` (any case, trimmed) read as `decision`: the first becomes `decision`,
    a later one, or one beside an existing `decision`, is dropped. → (the new value, how many entries were the legacy name); the value itself, 0 when none was."""
    if not name:
        return needs, 0
    if isinstance(needs, str):
        return ("decision", 1) if needs.strip().lower() == name else (needs, 0)
    if not isinstance(needs, list):
        return needs, 0
    has = any(isinstance(x, str) and x.strip().lower() == "decision" for x in needs)
    out: list[Any] = []
    n = 0
    for x in needs:
        if isinstance(x, str) and x.strip().lower() == name:
            n += 1
            if not has:
                out.append("decision")
                has = True
        else:
            out.append(x)
    return (out, n) if n else (needs, 0)


def history_version(version: dict[str, Any], name: str) -> dict[str, Any]:
    """An old version of an item (a commit of the store's git) as the current code reads it: `metadata.needs` holding the legacy `name` reads as `decision`. The version is not changed;
    a copy is returned when something differs, the same object when not. Only History uses it, to diff old versions with new ones."""
    meta = version.get("metadata") if isinstance(version, dict) else None
    if not name or not isinstance(meta, dict) or "needs" not in meta:
        return version
    needs, n = normalize_needs(meta["needs"], name)
    if not n:
        return version
    return {**version, "metadata": {**meta, "needs": needs}}
