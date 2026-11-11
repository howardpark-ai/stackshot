"""store.py: the one store, read by id: where it is (`STORE`, [paths] store), every item file in it, the file of one item, an item as `_load` reads it (an old stored form read as the current one),
and the text of a write with a bare store id (g7) written as the item's shown id (board#N).

server.py is being split into one module per area (CONTRIBUTING.md, Layout). This is the store's reading half: `_save`, the one writer, stays in server.py because it calls the hand-off, the
For you list, the landed list and the search, which are server.py's still (a module here cannot import server.py). A suite that points the server at a copy of the store sets `server._store.STORE`,
the one place `STORE` is read from: the server's own reads of it (`_store.STORE`) and the readers here see the same value. server.py imports each function back, so `server._load`, `server._path`,
`server._item_files`, `server._shown_ids`, `server._legacy_hold` and `server._legacy_needs` stay the names the writes, the tools and the tests use."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core import config as _cfg
from stackshot.github import ghsync as _gh
from stackshot.model import item_project as _ip
from stackshot.model.ids import _CODE_FENCE, _CODE_SPAN, _without_mq_groups
from stackshot.model.needs import _canon_needs, _needs_list, _needs_of, _needs_store

STORE = _cfg.path("paths", "store")


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


def _path(gid: str) -> Path:
    p = STORE / gid[0] / f"{gid[1:]}.json"
    if not p.exists():                       # an old id kept in a field (after, superseded_by) after its item moved
        alt = _gh.resolve(gid)
        if alt != gid:
            return STORE / alt[0] / f"{alt[1:]}.json"
    return p


def _load(gid: str) -> dict[str, Any]:
    p = _path(gid)
    if not p.exists():
        raise ToolError(f"no item {gid}")
    with open(p, encoding="utf-8") as f:
        it = json.load(f)
    _legacy_hold(it)                         # a file the start-time migration has not rewritten yet reads as it will be
    _legacy_needs(it)
    _ip.read_through(it)                     # metadata.project is the page the item's project id points at now (a moved or renamed page keeps its items)
    return it


def _legacy_needs(item: dict[str, Any]) -> bool:
    """An item stored before an earlier change (needs a word, the linked agent in metadata.agent) → in memory, needs a list with the agent
    in it, the agent key gone. → True when it was one. The migration and _load's tolerance only."""
    meta = item.get("metadata")
    if not isinstance(meta, dict):
        return False
    changed = False
    if isinstance(meta.get("needs"), str):
        _needs_store(meta, _needs_list(meta["needs"])); changed = True
    elif meta.get("needs") is not None and not isinstance(meta.get("needs"), list):
        meta.pop("needs", None); changed = True
    ag = str(meta.pop("agent", "") or "").strip()
    if ag:
        if item.get("status") == "open":          # a closed item's agent is a record, and a close carries no needs
            _needs_store(meta, _canon_needs(_needs_of(meta) + [ag]))
        changed = True
    return changed


def _legacy_hold(item: dict[str, Any]) -> bool:
    """An item stored before on hold became a property (status "on_hold", since retired) → in
    memory, status open + metadata.hold, its wake kept. → True when it was one. The migration and _load's tolerance only."""
    if item.get("status") != "on_hold":
        return False
    item["status"] = "open"
    item["metadata"] = {**(item.get("metadata") or {}), "hold": True}
    return True


# The store keys an issue-numbered item as g<n>, but a person
# reads it as board#N, and once a session has seen g<n> nothing kept it out of what it wrote. So every write that takes text in
# (create, update and complete: subject, description, next, ask, the options' label and line, the close's reason and a work
# line's text; the message tool's text) passes through _shown_ids, which writes a bare g<n> that names an item as it is shown.
# Bare means a whole word: not glued to a word, and not after # / \ - . : @ (board#g7, x/g7, x-g7, a path or a handle);
# not before a word character, - / \ or a dot-word (g7abc, g7-x, g7/, g7.json). Never inside code (a fenced block, an inline
# span), a markdown link (its [text] and its (url)) or a URL. An id that names no item stays as written; the other stored forms
# (s<n>, l<n>) are left as they are. The text a write stores and the reply that echoes it then show board#N; a gbrain page's
# timeline is not stackshot's to rewrite.
_SHOWN_SKIP = re.compile(r"!?\[[^\]\n]*\]\([^)\n]*\)|!?\[[^\]\n]*\]\[[^\]\n]*\]|<?https?://[^\s)>\]]+>?")


def _shown_ids(text: str) -> str:
    """Text a write takes in → the same, each bare store id of an issue-numbered item (g7) that names an item written as it is
    shown; code, links, URLs, unknown ids and every other form untouched (above)."""
    text = str(text or "")
    L = _gh.letter()
    if not text or L not in text:
        return text
    blank = lambda m: re.sub(r"[^\n]", "\0", m.group(0))
    masked = _without_mq_groups(_SHOWN_SKIP.sub(blank, _CODE_SPAN.sub(blank, _CODE_FENCE.sub(blank, text))))
    rx = re.compile(r"(?<![\w#/\\\-.:@])" + re.escape(L) + r"[1-9]\d*(?![\w\-/\\]|\.\w)")
    out, at = [], 0
    for m in rx.finditer(masked):
        gid = _gh.resolve(m.group(0))
        try:
            ok = _path(gid).exists()
        except Exception:  # noqa: BLE001
            ok = False
        label = _gh.shown(gid) if ok else ""
        if label and label != m.group(0):
            out += [text[at:m.start()], label]; at = m.end()
    return "".join(out) + text[at:] if out else text
