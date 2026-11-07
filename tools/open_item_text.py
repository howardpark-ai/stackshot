#!/usr/bin/env python3
"""tools/open_item_text.py — the text of the open items, for a program that looks for a link in it (read only, fails closed).

Reads the config and the items in the store the way the other report tools do (next_report.load_all: `[paths] store`, or `--store DIR`) and, for each OPEN item
(status `open`, held and parked ones included; the test every report tool in this folder applies), prints the lines of its description, its next (the checklist: the stored next
text and each stored step) and its stored ask, one per line, prefixed by the item's id. Closed items print nothing. It writes nothing and makes no network or model call. Stdlib plus the repo's modules.

  tools/open_item_text.py                 `<id>: <line>` for every line of text of every open item
  tools/open_item_text.py --links         the distinct `/mockup/<n>` links found anywhere in an open item (every string of its whole JSON: description, next, steps, ask,
                                          wait basis, work, answers, said, options, subject, ...), one per line, sorted by number, lowercase, no leading zeros
  tools/open_item_text.py --store DIR     read the items from DIR (a copy of the store) instead of [paths] store

A caller that deletes a page nobody links needs the answer to fail closed, so a link is matched loosely on purpose: the match is case-insensitive, ASCII digits, and it is a prefix
match (`/mockup/120x` and `/mockup/120.png` count as `/mockup/120`), which can only keep a page longer, never drop one in use.

Exit 0 when the store was read whole (no output when nothing matches); 2 when the store (--store, or [paths] store of the config) is no folder or cannot be read, with one line on stderr and nothing on stdout;
3 when some item file could not be read or parsed: the count goes to stderr, and what was found in the other items is still printed, so the caller decides what to do with an incomplete answer."""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterator

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import config as _cfg  # noqa: E402  ([paths] store)
import next_report as _nr  # noqa: E402  (its load_all, shown and num: the store reader the report tools share)

LINK_RX = re.compile(r"/mockup/([0-9]+)", re.IGNORECASE | re.ASCII)    # ASCII digits only; a prefix match on purpose (fail-safe: an extra link only keeps a page longer)


def _lines(text: Any) -> Iterator[str]:
    for ln in str(text or "").splitlines():
        ln = ln.strip()
        if ln:
            yield ln


def item_lines(item: dict[str, Any]) -> list[str]:
    """The lines of text of one item that may carry a link: description, next, each stored step, ask. Duplicates (a step also written in next) are kept once."""
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    steps = meta.get("steps") if isinstance(meta.get("steps"), list) else []
    texts: list[Any] = [item.get("description"), meta.get("next")]
    texts += [s.get("text") for s in steps if isinstance(s, dict)]
    texts.append(meta.get("ask"))
    out: list[str] = []
    for t in texts:
        for ln in _lines(t):
            if ln not in out:
                out.append(ln)
    return out


def all_strings(value: Any) -> Iterator[str]:
    """Every string value anywhere in a parsed JSON value (dict values, list elements, nested), without recursion so a deep item cannot overflow the stack."""
    stack = [value]
    while stack:
        v = stack.pop()
        if isinstance(v, str):
            yield v
        elif isinstance(v, dict):
            stack.extend(v.values())
        elif isinstance(v, list):
            stack.extend(v)


def open_items(items: dict[str, dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """[(gid, item)] for the open items (status `open`; held and parked ones are open), in id order."""
    return [(gid, items[gid]) for gid in sorted(items, key=_nr.num) if items[gid].get("status") == "open"]


def open_text(items: dict[str, dict[str, Any]]) -> list[tuple[str, str]]:
    """[(shown id, line)] for the open items, in id order."""
    out: list[tuple[str, str]] = []
    for gid, it in open_items(items):
        out += [(_nr.shown(gid), ln) for ln in item_lines(it)]
    return out


def links(items: dict[str, dict[str, Any]]) -> list[str]:
    """The distinct `/mockup/<n>` links in any string of any open item, sorted by number, `/mockup/019` and `/mockup/19` being one. The number is compared as digits without leading zeros
    (an int() of a very long digit run would raise)."""
    found = {m.lstrip("0") or "0" for _, it in open_items(items) for s in all_strings(it) for m in LINK_RX.findall(s)}
    return [f"/mockup/{n}" for n in sorted(found, key=lambda n: (len(n), n))]


def unlistable(store: Path) -> list[Path]:
    """The folders under the store that cannot be listed (their items would be missed without a sound)."""
    bad: list[Path] = []
    for d in sorted(store.iterdir()):
        if d.is_dir() and not os.access(d, os.R_OK | os.X_OK):
            bad.append(d)
    return bad


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="The text of the open items, one line each, or only their /mockup/<n> links (read only). Exit 2: no store folder; 3: some item file could not be read.")
    ap.add_argument("--links", action="store_true", help="print only the distinct /mockup/<n> links found anywhere in an open item, sorted by number")
    ap.add_argument("--store", help="read the items from this folder (a copy of the store) instead of [paths] store")
    a = ap.parse_args(argv)
    try:
        store = Path(a.store).expanduser() if a.store else _cfg.path("paths", "store")
    except Exception as e:  # the config is missing or has no [paths] store: say so, print nothing
        print(f"store: cannot be found ({type(e).__name__}: {e})", file=sys.stderr)
        return 2
    if not store.is_dir():
        print(f"{'--store ' if a.store else '[paths] store '}{store}: not a folder", file=sys.stderr)
        return 2
    try:
        bad_dirs = unlistable(store)
    except OSError as e:
        print(f"store {store}: cannot be read ({e})", file=sys.stderr)
        return 2
    skipped: list[Path] = []
    items = _nr.load_all(store, skipped)
    for ln in (links(items) if a.links else [f"{i}: {t}" for i, t in open_text(items)]):
        print(ln)
    n = len(skipped) + len(bad_dirs)
    if n:
        print(f"{n} item file(s) or folder(s) of {store} could not be read or parsed; the output may miss text", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
