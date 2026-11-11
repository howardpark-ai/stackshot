"""merge_tie.py: which open items a merged pull request is tied to, for the progress clock (progress.py; the server's `_merge_progress_tick` reads the hub's merge log and asks here).

The pure half: no server import, no file, no clock. A pull request is tied to an item when one of three things says so:

  anchored   an anchor scoped to the item names the pull request (a project-wide anchor names no item: every item of a project would be tied to every merge, and no clock would run)
  body       the pull request's body names the item (`board#N`; the hub reads it with the event, merge_log.refs)
  words      the item's own words (its description and its steps) name the pull request: its URL in any repository, or its number written `#n`, `PR n` or `PR #n` for a repository the item
             speaks of without a URL (this repository, or one the item has a pull request anchored in; a bare number in any other repository's item may be another repository's)

The first reason found is the one a History line gives (anchored, then body, then words)."""
from __future__ import annotations

import re
from typing import Any, Callable, Iterable

PR_URL = re.compile(r"https?://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)", re.I)
BARE = re.compile(r"(?<![\w/&#-])#(\d+)\b|\bPRs?\s+#?(\d+)\b", re.I)
ANCHORED, BODY, WORDS = "anchored", "body", "words"
HOW = {ANCHORED: "an anchor of the item names it", BODY: "the pull request's description names the item", WORDS: "the item's own words name it"}


def names(text: str, key: str, bare_repos: Iterable[str] = (), canon: Callable[[str], str] = str.lower) -> bool:
    """Does `text` name the pull request `key` ("owner/repo#n", lower-case, already in its current name)? By its URL always, by its number only when `key`'s repository is one of `bare_repos`."""
    repo, _, n = str(key).rpartition("#")
    for m in PR_URL.finditer(text or ""):
        if m.group(2) == n and canon(m.group(1)).lower() == repo:
            return True
    if repo in {canon(r).lower() for r in bare_repos if r}:
        for m in BARE.finditer(text or ""):
            if (m.group(1) or m.group(2)) == n:
                return True
    return False


def repo_of(key: str) -> str:
    return str(key).rpartition("#")[0]


def tied(key: str, body_items: Iterable[str], scoped: dict[str, set[str]], texts: dict[str, str], own: str = "", canon: Callable[[str], str] = str.lower) -> dict[str, str]:
    """→ {item id: why} for the pull request `key`: `body_items` the ids its body names (already resolved to the store's), `scoped` {item id: the pull requests anchored to it}, `texts` {item id: its
    description and steps, one string} of the items to search, `own` this repository ("owner/repo") for the numbers written without a URL. The caller passes open items only."""
    out: dict[str, str] = {}
    for gid, keys in scoped.items():
        if key in keys:
            out[gid] = ANCHORED
    for gid in body_items:
        out.setdefault(gid, BODY)
    for gid, text in texts.items():
        if gid in out:
            continue
        bare = {own, *(repo_of(k) for k in scoped.get(gid, ()))}
        if names(text, key, bare, canon):
            out[gid] = WORDS
    return out
