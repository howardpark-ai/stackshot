"""wait_loop.py: a loop of waits (item A waits on item B, B waits on A, or a longer ring) and how it is found.

The write path refuses an `after` that would close a ring (service/mover_steps.py `_after_reaches`), but a ring can still form: a wait written only in a step's words ("once board#N closes") is no link the write
test reads, two writes can cross, and an older item can carry a link the test never saw. Nothing then moves either side until the backstop day of one of them. This module reads every wait one open item has
on another open item and finds the rings. It is pure: functions of dicts and strings, no store, no clock, no message. The walk that feeds it and the notice that follows are audit/wait_loops.py's.

What counts as a link (`reads`):

  after   an id the item's `after` names, and an item line of its list of waits that has not arrived (the two sources the write test walks, wait_list.item_ids) when the list is mode `all`; a parked item's
          `until` with an `after` is the same `after` link, the date is only its backstop. A list in mode `any` is no link at all, whatever its lines: it ends when ANY line arrives, so it always has another
          way out (a time, an anchor, another item) and is no wait that none of the items can break. (The simpler of the two rules: one test of the mode, no weighing of which lines could arrive.)
  words   an open step of the item whose words wait ON another item: `waits_on` below. The wait-end rule (wait_end.py `_item_refs`) reads any clause with a time word before an id ("after merging, post the
          result on board#N", "when done, tell board#N") because it only asks a mover to state the wait; a ring told to two movers and told again must be a wait for certain, so this reader keeps only the
          clauses where the item is the thing waited for, and skips an ambiguous one (a ring missed is cheaper than a false alarm that is told again and again). A wait the server later turns into an `after`
          (the wait-end rule) is the same link under its other name, so it keeps its place in the ring and its age

A link counts only between two OPEN items. A link to a closed item or to an id no item has ends nothing and loops nothing (the target closed: the wait is over; no such item: nothing to wait for), and a step that
names its own item is no wait. An item that names itself in `after` is a ring of one.

The rings (`loops`) are the strongly connected parts of the graph of those links (Tarjan), so a ring of two, of three or longer, and a ring with a chord, are each one finding. For a part with more than one
ring in it the loop told is the shortest ring through the newest link (`cycle`), which is also the link to break: the link written last is the one a writer added to a graph that worked, so cutting it
restores what held before. The age of a link is what the caller knows of when it was written (`stamp`); a tie is settled by the higher item number, so the answer never depends on the order the items were read.
The fingerprint of a loop is a short digest of its links, so a ring that stands is the same ring minute after minute and a ring that gained or lost a link, or moved to other items, is a new one.

Imports the domain only (model, waits)."""
from __future__ import annotations

import collections
import hashlib
import re
from typing import Any, Callable, NamedTuple

from stackshot.model import model_guards as _mg
from stackshot.model import steps as _steps
from stackshot.waits import wait_list as _wl
from stackshot.waits import waiting as _wt

AFTER, WORDS = "after", "words"
FORMS = (AFTER, WORDS)
_NUM = re.compile(r"\D+")


class Link(NamedTuple):
    """One wait of an open item on another: `src` waits on `dst` (item ids as the store keeps them), `form` is AFTER or WORDS."""
    src: str
    dst: str
    form: str


class Loop(NamedTuple):
    """One ring: `links` in order (each link's dst is the next link's src, the last one's dst the first's src), starting with the newest link; `newest` is that link (`links[0]`); `fingerprint` names the ring."""
    links: tuple[Link, ...]
    newest: Link
    fingerprint: str


def num(gid: str) -> int:
    """The number in an item id (a12 → 12), 0 when it has none."""
    return int(_NUM.sub("", str(gid)) or 0)


_STRONG = re.compile(r"\b(?:wait(?:s|ing|ed)?\s+(?:for|on|until|till)|await(?:s|ing|ed)?|blocked\s+(?:on|by)|pending)\s+(?:(?:the|item|ticket|issue)\s+)*$", re.I)     # right before the id: the id is waited for
_TIME = re.compile(r"\b(?:until|till|once|after|when)\s+(?:(?:the|item|ticket|issue)\s+)*$", re.I)                                                                   # right before the id: a time word, the id then must be what completes
_DONE = re.compile(r"\s*(?:(?:is|are|was|has|have|gets|get|been|being)\s+)*(?:closed?|closes|done|merged?|merges|lands?|landed|ships?|shipped|live|resolved|answered|finish(?:ed|es)?|complete[sd]?|released?|ready|approved)\b", re.I)   # right after it
_ALT = re.compile(r"\b(?:or|either|unless)\b", re.I)
_END = re.compile(r"[.;!?\n]")


def _clauses(text: Any) -> list[str]:
    """The lines of a step's text that can be read as prose: a fenced block, a code span and a link target blanked, a line the server appends in parentheses left out (the way wait_end.py reads a step)."""
    out: list[str] = []
    for raw in _mg._FENCE_RX.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), str(text or "")).splitlines():
        line = _mg.clean(raw)
        if line and not line.startswith("(") and not _mg._MARK_RX.sub("", line).startswith("("):
            out.append(_mg._plain(line))
    return out


def waits_on(text: Any) -> list[str]:
    """The `board#N` ids a step waits ON, in the order written, each once. An id counts only where it is the thing waited for: right after a waiting phrase ("wait for", "waiting on", "awaiting", "blocked
    on/by", "pending"), or right after a time word ("until", "once", "after", "when") with the id itself completing ("board#N closes", "is done", "is merged", "lands", "is live", "is answered"). An id that is the
    object of what the step's own actor does afterward ("after merging, post the result on board#N", "when done, tell board#N", "once shipped, close board#N", "once I finish, board#N can start") is no
    wait on it, and neither is an id in a sentence with an alternative ("or", "either", "unless") or after a negation ("do not wait for"); an ambiguous clause is skipped."""
    out: list[str] = []
    for plain in _clauses(text):
        for m in _mg._BOARD_REF_RX.finditer(plain):
            ref = f"board#{m.group(1)}"
            if ref in out:
                continue
            start = max((e.end() for e in _END.finditer(plain, 0, m.start())), default=0)
            before = plain[start:m.start()]
            stop = _END.search(plain, m.end())
            sentence = plain[start:stop.start() if stop else len(plain)]
            if _ALT.search(sentence):
                continue
            hit = _STRONG.search(before) or (_TIME.search(before) if _DONE.match(plain, m.end()) else None)
            if hit and not _mg._negated(before, hit.start()):
                out.append(ref)
    return out


def reads(item: dict[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(the ids the item's `after` and its list of waits name, the `board#N` ids its open steps wait on in words), both in the order written and each id once. A closed item reads as nothing: it waits on nothing.
    Reads only; an item whose steps cannot be read has no words."""
    if not isinstance(item, dict) or item.get("status") != "open":
        return (), ()
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    after: list[str] = []
    for g in [*_wt.after_of(meta), *(_wl.item_ids(meta) if _wl.mode(meta) == "all" else [])]:      # a list in mode any has a way out: no link
        if g and g not in after:
            after.append(g)
    words: list[str] = []
    try:
        for s in _steps.view(meta):
            if s.get("status") != _steps.OPEN:
                continue
            for r in waits_on(s.get("text")):
                if r not in words:
                    words.append(r)
    except Exception:  # noqa: BLE001  (steps that cannot be read say nothing in words)
        pass
    return tuple(after), tuple(words)


def links(raw: dict[str, tuple[Any, ...]], by_shown: dict[str, str]) -> dict[tuple[str, str], str]:
    """The links between open items: {(src, dst): form}. `raw` is {id: (status, after ids, words ids, ...)} for every item of the store (`reads` of each, with its status; closed ones may be left out), `by_shown` maps the
    shown id (`board#N`) to the item id. A link whose target is closed or not in `raw` is dropped; a words link to the item itself is dropped (a step may name its own item), an `after` on itself is kept (a ring of
    one). Where an item reaches the same target both ways the `after` form is kept."""
    out: dict[tuple[str, str], str] = {}
    for src, row in raw.items():
        status, after, words = row[0], row[1], row[2]      # a row may carry more after these (the caller's last-write time)
        if status != "open":
            continue
        for g in after:
            if raw.get(g, ("",))[0] == "open":
                out[(src, g)] = AFTER
        for ref in words:
            g = by_shown.get(ref, "")
            if g and g != src and raw.get(g, ("",))[0] == "open" and (src, g) not in out:
                out[(src, g)] = WORDS
    return out


def _parts(adj: dict[str, list[str]]) -> list[list[str]]:
    """The strongly connected parts of the graph (Tarjan, iterative: a long chain never reaches the recursion limit), each as a sorted list of ids, in the order of their lowest id."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on: set[str] = set()
    stack: list[str] = []
    out: list[list[str]] = []
    counter = 0
    for root in sorted(adj, key=lambda g: (num(g), g)):
        if root in index:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            v, i = work.pop()
            if i == 0:
                index[v] = low[v] = counter
                counter += 1
                stack.append(v)
                on.add(v)
            nxt = adj.get(v, [])
            descended = False
            while i < len(nxt):
                w = nxt[i]
                i += 1
                if w not in index:
                    work.append((v, i))
                    work.append((w, 0))
                    descended = True
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            if descended:
                continue
            if low[v] == index[v]:
                part: list[str] = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    part.append(w)
                    if w == v:
                        break
                out.append(sorted(part, key=lambda g: (num(g), g)))
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[v])
    return sorted(out, key=lambda p: (num(p[0]), p[0]))


def _ring_through(edge: tuple[str, str], adj: dict[str, list[str]], part: frozenset[str]) -> list[str]:
    """The ids of the shortest ring through the link `edge` = (a, b) inside `part`, in the order of its links: a, b, … and the id whose link comes back to a (breadth first from b to a, neighbours in id order, so the answer is fixed)."""
    a, b = edge
    if a == b:
        return [a]
    prev: dict[str, str] = {b: ""}
    queue = collections.deque([b])
    while queue and a not in prev:
        v = queue.popleft()
        for w in adj.get(v, []):
            if w in part and w not in prev:
                prev[w] = v
                queue.append(w)
    chain: list[str] = []
    v = a
    while v != b:
        v = prev[v]
        chain.append(v)
    return [a, *reversed(chain)]


def fingerprint(ring: tuple[Link, ...]) -> str:
    """Six hex digits that name a ring: a digest of its links as item ids only, sorted, so the wait-end rule turning a step's words into an `after` is still the same ring."""
    body = "|".join(sorted(f"{lk.src}>{lk.dst}" for lk in ring))
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:6]


def loops(edges: dict[tuple[str, str], str], stamp: Callable[[str, str], float] = lambda s, d: 0.0) -> list[Loop]:
    """Every ring of `edges` ({(src, dst): form}), one per strongly connected part, the lowest item numbers first. `stamp(src, dst)` is when the link was written (0 when unknown): the newest link of a part, the
    higher item numbers settling a tie, is the one the loop starts with and the one to break. Pure: the same links give the same rings in the same order."""
    adj: dict[str, list[str]] = {}
    for (s, d) in edges:
        adj.setdefault(s, []).append(d)
        adj.setdefault(d, [])
    for k in adj:
        adj[k].sort(key=lambda g: (num(g), g))
    out: list[Loop] = []
    for part in _parts(adj):
        inside = frozenset(part)
        here = [(s, d) for (s, d) in edges if s in inside and d in inside]
        if len(part) == 1 and (part[0], part[0]) not in edges:
            continue
        newest = max(here, key=lambda e: (stamp(*e), num(e[0]), num(e[1]), e))
        ring_ids = _ring_through(newest, adj, inside)
        ring = tuple(Link(ring_ids[i], ring_ids[(i + 1) % len(ring_ids)], edges[(ring_ids[i], ring_ids[(i + 1) % len(ring_ids)])]) for i in range(len(ring_ids)))
        out.append(Loop(ring, ring[0], fingerprint(ring)))
    return out
