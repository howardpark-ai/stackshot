"""item_project.py — an item's project by its permanent id: the id an item stores, and the page key it reads through that id.

An item has always stored the page key of its project (`metadata.project`). A page key is not permanent: the project's page moves, and the registry derived everything from the page. The
project record (project_registry.py, projects.py) gives every project a permanent id and holds, per project, the page it points at and the keys the page had before. An item now stores that id
too (`metadata.project_id`), and every reader that groups, filters or labels items by project reads the page through it:

    metadata.project_id   the permanent id (`prj_<8 hex>`) of the TOP-LEVEL project the item belongs to. A sub-page is no project (the record has entries for top-level projects only), so an item
                          filed on a sub-page stores the id of the project that owns the sub-page.
    metadata.project      still stored, as before: the page the item is filed on. It is the item's plain link to its detail page when that is a sub-page, and a copy of the project's own page key
                          otherwise. The copy is never trusted over the id: key_of() reads the project's page through the id.

The functions, all stdlib plus project_registry and config, none of them writing a file:

    key_of(meta)        the page key the item is filed under now, as every reader wants it: the project's current page when the stored key is that page or one of the project's former keys
                        (the page moved or was renamed); the stored key itself when it is a sub-page of the project (the plain detail link), or names another project or a page no project owns (the id is stale: the key wins),
                        or the item has no id; the stored value as it is when nothing is known about the id.
    id_of(meta)         the stored id, else the id the stored key derives to ("" when it names no project)
    derive(key)         the id of the top-level project that a page key, a former key, a bare slug or a sub-page's key names ("" for none): through the record's entries first, then through its id table
                        (a project that has no entry yet is known by the id table alone)
    stamp(meta)         the write path: set `project_id` from the stored key when the key names a project whose id the item does not carry → True when it changed
    read_through(item)  the item as a reader sees it: `metadata.project` replaced by key_of() in the in-memory dict (a file is never written by it)
    project_of(meta)    the page key of the item's TOP-LEVEL project: what a reader that SHOWS, groups or counts an item by its project writes. An item filed on a sub-page reads as the project that owns the sub-page; one on a
                        top-level page, or on a key that names no project, reads as key_of() does. Display only: a reader that needs the PAGE (page debt, the keeper, anchors scoped to a page, the page-update gate, a move or rename of
                        a page) keeps reading key_of(), the page the item is filed on, which is also the item's plain link to its detail page.
    line_of(meta)       the `project:` line's value in get and brief: the top-level key, with `(filed on <sub-page>)` after it for an item on a sub-page
    top_of(key)         the same for a page key: the top-level project's page key, or `key` itself when it names no project

Reads the record file and the page registry file through caches that look at their size and time (one `stat` each per call); an unreadable file reads as empty, so key_of() gives the stored key.
Nothing here raises."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg
from stackshot.projects import project_registry as pr

FIELD = "project_id"
_ID_RE = pr.ID_RE

_RECORD: dict = {"sig": None, "by_id": {}, "by_key": {}}
_REG: dict = {"sig": None, "pages": {}}


def _sig(p: Path) -> Any:
    try:
        st = os.stat(p)
        return (str(p), st.st_mtime_ns, st.st_size, st.st_ino)
    except OSError:
        return (str(p), None)


def _tables() -> tuple[dict, dict]:
    """(id → page key, page key → id) from the record file's id table, parsed again only when the file changed; ({}, {}) when it cannot be read."""
    p = pr.record_path(); sig = _sig(p)
    if _RECORD["sig"] != sig:
        by_id: dict = {}; by_key: dict = {}
        try:
            ids = json.loads(p.read_text(encoding="utf-8")).get("ids") or {}
            if isinstance(ids, dict):
                for i, k in sorted(ids.items()):
                    if pr.is_id(i) and isinstance(k, str) and k:
                        by_id[i] = k; by_key.setdefault(k, i)
        except (OSError, ValueError, AttributeError):
            by_id, by_key = {}, {}
        _RECORD.update(sig=sig, by_id=by_id, by_key=by_key)
    return _RECORD["by_id"], _RECORD["by_key"]


def _pages() -> dict:
    """The page registry file's rows (key → row), as the publisher wrote it; {} when it cannot be read. Only the key tree and the `hub:` lines are read from it."""
    p = _cfg.path("paths", "store") / "projects.json"; sig = _sig(p)
    if _REG["sig"] != sig:
        pages: dict = {}
        try:
            d = json.loads(p.read_text(encoding="utf-8")).get("pages") or {}
            pages = d if isinstance(d, dict) else {}
        except (OSError, ValueError, AttributeError):
            pages = {}
        _REG.update(sig=sig, pages=pages)
    return _REG["pages"]


def _norm(x: Any) -> str:
    return pr._norm_key(x)


def _first_dir() -> str:
    try:
        return (_cfg.page_dirs() or ["projects"])[0]
    except Exception:  # noqa: BLE001
        return "projects"


def _cands(k: str) -> list:
    pats = ((_cfg.CFG.get("registries", {}) or {}).get("projects", {}) or {}).get("match") or ["{value}"]
    try:
        return list(dict.fromkeys([k] + [p.format(value=k) for p in pats]))
    except Exception:  # noqa: BLE001
        return [k]


def _owner(key: str, ents: dict) -> str:
    """The top-level page that owns the sub-page `key` (the nearest page above it, or the page its `hub:` line names, and so on up); "" for a key that is no sub-page."""
    reg = _pages()
    pages = {**pr.by_page(ents), **pr.by_former_key(ents), **reg}
    hub = lambda x: _norm((reg.get(x) or {}).get("hub")) if isinstance(reg.get(x), dict) else ""      # noqa: E731
    up, seen = "", {key}
    while True:
        nxt = pr.top_page(up or key, pages, hub)
        if not nxt or nxt in seen:
            return up
        up = nxt; seen.add(nxt)


def derive(key: Any) -> str:
    """The id of the top-level project the page key `key` names, "" when it names none. An id is its own answer when the record knows it."""
    try:
        k = _norm(key)
        if not k:
            return ""
        by_id, by_key = _tables()
        ents = pr.entries()
        if pr.is_id(k):
            return k if (k in ents or k in by_id) else ""
        try:
            hit = pr.resolve(k, lambda x: _norm((_pages().get(x) or {}).get("hub")) if isinstance(_pages().get(x), dict) else "")
        except KeyError:                  # a `hub:` line that names a page no entry points at: the id table answers below
            hit = None
        if hit:
            return hit["id"]
        for c in _cands(k):
            up = _owner(c, ents)
            if up:
                return pr.by_page(ents).get(up) or pr.by_former_key(ents).get(up) or by_key.get(up, "")
            if c in by_key:
                return by_key[c]
        return ""
    except Exception:  # noqa: BLE001
        return ""


def _current(pid: str) -> str:
    """The page key the project with id `pid` has now: the entry's pointer, else the id table's key ("" when it has none)."""
    k = pr.page_key_of(pid)
    return k or _tables()[0].get(pid, "")


def key_of(meta: Any) -> str:
    """The page key the item with metadata `meta` is filed under now (see the module text). The stored value, unchanged, whenever the id adds nothing."""
    try:
        if not isinstance(meta, dict):
            return ""
        raw = meta.get("project")
        stored = _norm(raw)
        pid = str(meta.get(FIELD) or "").strip()
        if not pr.is_id(pid) or pr.is_id(stored):
            return str(raw or "")
        cur = _current(pid)
        if not cur:
            return str(raw or "")
        if not stored:
            return cur
        if stored == cur:
            return str(raw)
        other = derive(stored)
        if other == pid:
            former = [_norm(x) for x in (pr.entries().get(pid, {}).get("former_keys") or [])]
            return cur if stored in former else str(raw)    # a former key of the project follows the page; a sub-page (the plain detail link) and a bare slug (the legacy form) stay as stored
        if other or stored in _pages():                                                       # a key another project owns wins, and so does a page that exists but no project owns (the id is stale)
            return str(raw)
        return cur                                                                           # a key that is no page and no project's follows the id (the page it names moved)
    except Exception:  # noqa: BLE001
        return str((meta or {}).get("project") or "") if isinstance(meta, dict) else ""


def top_of(key: Any) -> str:
    """The page key of the top-level project that the page key `key` names (a sub-page, a page with a `hub:` line, a former key, a bare slug: the project's current page). `key` as it is, unchanged,
    when it names no project, has no page to name (a project stored by its id), or already is the project's page (a trailing slash or `.md` is left as it was written)."""
    try:
        k = _norm(key)
        if not k or pr.is_id(k):
            return str(key or "")
        pid = derive(k)
        top = _current(pid) if pid else ""
        return str(key) if (not top or _norm(top) == k) else top
    except Exception:  # noqa: BLE001
        return str(key or "")


def project_of(meta: Any) -> str:
    """The page key of the top-level project the item with metadata `meta` belongs to (see the module text): key_of() followed up to the project that owns the page. Works with a stored project_id and
    without one (key_of() reads the id when there is one, and derive() the stored key when there is not); a key that names no project reads as stored. Never writes."""
    try:
        return top_of(key_of(meta)) if isinstance(meta, dict) else ""
    except Exception:  # noqa: BLE001
        return str((meta or {}).get("project") or "") if isinstance(meta, dict) else ""


def line_of(meta: Any) -> str:
    """The value of the `project:` line the get and brief tools print for an item: the top-level project's page key, and for an item filed on a sub-page, or on a page that hangs off the project by a `hub:`
    line, the page it is filed on after it, `projects/x (filed on projects/x/sub)`, so the text line keeps the plain link to the detail page that the board's markdown keeps as a link. The page is the one
    key_of() reads (so a project that moved, or an id the item stores, never gives a false `filed on`); a key that is no page of the registry (a former key of the project, a bare slug) reads as the project
    alone. The stored value as it is for an item on a top-level page or one that names no project."""
    try:
        if not isinstance(meta, dict): return ""
        stored = str(meta.get("project") or "")
        page = key_of(meta)
        if not page: return ""
        top = top_of(page)
        if not top or _norm(top) == _norm(page): return stored if _norm(stored) == _norm(page) else page
        return f"{top} (filed on {page})" if _norm(page) in _pages() else top
    except Exception:  # noqa: BLE001
        return str((meta or {}).get("project") or "") if isinstance(meta, dict) else ""


def id_of(meta: Any) -> str:
    """The item's project id: the stored one, else the one its stored key derives to; "" when none."""
    if not isinstance(meta, dict):
        return ""
    pid = str(meta.get(FIELD) or "").strip()
    return pid if pr.is_id(pid) else derive(meta.get("project"))


def stamp(meta: Any) -> bool:
    """Write path: make `meta[project_id]` agree with the stored key, which is what the writer set last. A key that names a project sets the id (a different one replaces it); a key that names
    none removes the id the item carried (a re-file to a page the record has no project for must not leave the old project's id behind: the item then reads as its key). An item with no key keeps
    its id. → True when it changed."""
    try:
        if not isinstance(meta, dict) or not str(meta.get("project") or "").strip():
            return False
        pid = derive(meta.get("project"))
        if pid and meta.get(FIELD) != pid:
            meta[FIELD] = pid
            return True
        if not pid and FIELD in meta:
            del meta[FIELD]
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def read_through(item: Any) -> Any:
    """`item` with its `metadata.project` read through the id (in memory only), and returned. An item with no metadata, no id or nothing to change is returned as it is."""
    try:
        meta = item.get("metadata") if isinstance(item, dict) else None
        if isinstance(meta, dict) and meta.get(FIELD):
            k = key_of(meta)
            if k and k != str(meta.get("project") or ""):
                meta["project"] = k
    except Exception:  # noqa: BLE001
        pass
    return item


def plan(meta: Any) -> dict:
    """What the migration does for one item's metadata: {"action": "set" | "same" | "drop" | "none", "id": the id it would store, "key": the stored key, "had": the id it stores}.
    `same`: the item stores that id already. `drop`: its key is a page no project owns and it stores an id (a stale one, left by a re-file): the id is taken out and the item reads as its key.
    `none`: its key names no project (nothing is written; the key stays as it is)."""
    stored = _norm((meta or {}).get("project")) if isinstance(meta, dict) else ""
    have = str((meta or {}).get(FIELD) or "").strip() if isinstance(meta, dict) else ""
    pid = derive(stored)
    if not pid:
        if stored and pr.is_id(have) and not pr.is_id(stored) and stored in _pages():
            return {"action": "drop", "id": "", "key": stored, "had": have}
        return {"action": "none", "id": "", "key": stored, "had": have}
    return {"action": "same" if have == pid else "set", "id": pid, "key": stored, "had": have}
