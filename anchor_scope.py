"""anchor_scope.py: which anchors count for an item. The one reader, shared by the server, the board's markdown and brief (render.py), the web pages
(ui/render.py), the model guards, the migration pass and tools/board_report.py.

An anchor is held by one project's page (anchors.json: {"<page key>": [{"url", "items": [ids] | None, "added", "by"}, …]}), and that page keeps it:
the keeper who is asked about it, the receivers anchor-hub binds, the Anchors list of that page. What an anchor is ABOUT is another matter: its
`items` name items of any project, and an anchor counts for such an item wherever the page that holds it is (an anchor to a Slack DM has
receivers in several projects). A project-wide anchor (`items` None) counts for no item: it is about its page's project, and only a listing of
that project's own items (`wide=True`) names it.

The same anchor held by two pages (the same URL, [github.moved] names read as one) is one anchor for the item: counted once, with the page that
comes first (the item's own project's page, then the others by key) in `page`, every page that holds it in `pages`, the latest `added` of the copies
and the union of the item lists that name it.

Stdlib and anchors.py only. A store that is no dict, a page that is no list and an entry that is no dict with a text url are skipped: the file is
edited by hand now and then, and none of that may fail a page or a write.
"""
from __future__ import annotations

from typing import Any

import anchors as _anc  # noqa: E402  (same_url_key: the identity of an anchor URL)


def clean_entries(es: Any) -> list[dict[str, Any]]:
    """One page's anchors from the anchors file's list, as clean dicts: an entry that is no dict or has no text url is left out, `items` is a list of
    strings or None, `added` a number or None, and a page's value that is no list holds nothing."""
    out = []
    for e in (es if isinstance(es, list) else []):
        if not isinstance(e, dict) or not isinstance(e.get("url"), str) or not e["url"]:
            continue
        try:
            added = float(e.get("added")) if e.get("added") else None
        except (TypeError, ValueError):
            added = None
        out.append({**e, "items": [str(g) for g in e["items"]] if isinstance(e.get("items"), list) and e["items"] else None, "added": added})
    return out


def _pages(store: Any, project: str = "") -> list[str]:
    """The store's page keys in the order a reader meets them: the item's own project first, then the others by key."""
    if not isinstance(store, dict):
        return []
    return ([project] if project in store else []) + sorted(str(k) for k in store if k != project)


def _add(found: dict[str, dict[str, Any]], page: str, e: dict[str, Any], scoped: bool) -> None:
    """Count entry `e` of `page` for the item once: a second copy of the same anchor joins the first (pages, latest added, items)."""
    key = _anc.same_url_key(e["url"])
    cur = found.get(key)
    if cur is None:
        found[key] = {**e, "items": list(e["items"]) if scoped else None, "page": page, "pages": [page], "scoped": scoped}
        return
    if page not in cur["pages"]:
        cur["pages"].append(page)
    if e["added"] is not None and (cur["added"] is None or e["added"] > cur["added"]):
        cur["added"] = e["added"]
    if scoped:
        cur["items"] = sorted(set(cur["items"] or []) | set(e["items"] or []))
        cur["scoped"] = True


def anchor_scope(store: Any, gid: str, project: str = "", *, wide: bool = False) -> list[dict[str, Any]]:
    """The anchors that count for item `gid`, from every project's page, each once: a copy of the entry with `page` (the page that holds it; the item's own
    `project` first), `pages` (every page that holds it), `scoped` (named by an `items` list; False only for a project-wide anchor of `project`'s own page that
    `wide=True` lists) and `items`. Without `wide` only the anchors that name the item come back: those are what makes an outside item an anchor wait, what
    holds a hold and what a completion asks the keeper about; with `wide` the project's project-wide anchors are listed too (a reading of the item, not a test)."""
    gid, project = str(gid or "").strip(), str(project or "").strip()
    found: dict[str, dict[str, Any]] = {}
    if not gid:
        return []
    for page in _pages(store, project):
        for e in clean_entries(store.get(page)):
            if gid in (e["items"] or []):
                _add(found, page, e, True)
            elif wide and e["items"] is None and page == project:
                _add(found, page, e, False)
    return list(found.values())


def holders(store: Any, url: str, same: Any = None) -> list[str]:
    """The pages that hold the anchor `url`, in any scope (the page keeps its anchor and receives its notices), by key. `same(a, b)` says two URLs are one anchor
    (the server passes its anchor-id comparison); the default is anchors.same_url_key equality."""
    same = same or (lambda a, b: _anc.same_url_key(a) == _anc.same_url_key(b))
    return [page for page in _pages(store) if any(same(e["url"], url) for e in clean_entries(store.get(page)))]


def scoped_map(store: Any) -> dict[str, list[str]]:
    """{item id: [the URLs of the anchors that count for it]} for the whole board in one pass, each URL once, in the order the anchors were added (an `added` that is
    no number sorts as the oldest). The same rule as anchor_scope, drawn for every item at once: what a page that asks about many items reads."""
    rows: list[tuple[float, int, str, str]] = []      # (added, order met, item id, url): sorted, then deduplicated per item
    n = 0
    for page in _pages(store):
        for e in clean_entries(store.get(page)):
            for g in (e["items"] or []):
                rows.append((e["added"] or 0.0, n, g, e["url"]))
                n += 1
    out: dict[str, list[str]] = {}
    keys: dict[str, set[str]] = {}
    for _a, _n, g, url in sorted(rows):
        k = _anc.same_url_key(url)
        if k in keys.setdefault(g, set()):
            continue
        keys[g].add(k)
        out.setdefault(g, []).append(url)
    return out


def completion_due(store: Any, gid: str, all_items: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """[(page, entry)] of the anchors scoped to `gid` whose other listed items are all completed (or gone): the ones the keeper of the page that holds each should
    judge now that `gid` closed. Per page, not merged: the page keeps its anchor, so each page's keeper is asked about its own."""
    open_ids = {t["gid"] for t in all_items if t.get("status") != "completed"}
    gid = str(gid or "").strip()
    out = []
    for page in _pages(store):
        for e in clean_entries(store.get(page)):
            scope = e["items"] or []
            if gid in scope and not (set(scope) - {gid}) & open_ids:
                out.append((page, e))
    return out
