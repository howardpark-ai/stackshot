"""nextlines.py — whose lines are in an item's next.

An item's `next` is one text of lines, each naming who takes the step. Before per-writer lines every update(next=...) replaced the whole text, so when two
sessions both had lines on one item each update wiped the other's. Now every line has a WRITER: the session whose update wrote it (the sender, or the
item's creator when the call names none). That is not the name the line starts with: a line may name another session as the one taking the step.

  * update(next=<text>) replaces only the lines whose writer is the sender. Other writers' lines stay where they are; the sender's new lines take the
    place of its old ones (all of them at the position of the first old line), or go at the end when it had none.
  * update(next="none") (or "clear", "-") removes only the sender's lines; update(clear_next=true) wipes every line, then sets the sender's when next is
    also given.

STORAGE. `metadata.next` stays the text it always was, so every reader of it (get, the board, the item page, the guards, the mirror) is unchanged. The writers
sit beside it in `metadata.next_by`, a list of [writer, key] pairs in the order of the lines, where key is a short hash of the line's text and writer the
writer's canonical session id (a /rename does not change it). A line is found by its text, not by its position, so a write that edits `next` without knowing
about writers (a migration naming the lines, the ask lifted out of next) leaves the other lines' writers right; a line with no pair, which is every line
stored before an earlier change, has no writer and is the item's creator's (metadata.owner). Nothing is migrated: the writers are resolved when read, and written for every line on
the next save that touches `next`.

A "line" here is a top-level line with whatever hangs under it: an indented line, a server note in parentheses, a blank line and a fenced block stay with the
line above. Pure functions on the metadata dict; the identity comparison (`same`) is the server's."""
from __future__ import annotations

import hashlib
import re
from typing import Any, Callable

import model_guards as _mg

NONE_WORDS = ("none", "clear", "-")      # next="none" removes the sender's lines, as it does for due, wake, needs and ask
_MARKER = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+")


def norm(text: Any) -> str:
    """A line as compared (steps.key is this): its text on one line, the list marker of its first line and the bold marks left out."""
    return " ".join(_MARKER.sub("", str(text or "").strip(), count=1).replace("**", "").split())


def key_of(entry: str) -> str:
    """A short hash of one line's text (whitespace around it ignored): how a stored writer finds its line."""
    return hashlib.sha1(entry.strip().encode("utf-8")).hexdigest()[:10]


def split(text: Any) -> list[str]:
    """The lines of a next text, each with what hangs under it (see the module doc); blank lines at the end of a line are dropped. [] for an empty text."""
    raw_all = str(text or "")
    if not raw_all.strip():
        return []
    masked = _mg._FENCE_RX.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), raw_all).splitlines()
    raws = raw_all.splitlines()
    out: list[list[str]] = []
    for i, raw in enumerate(raws):
        mk = masked[i] if i < len(masked) else raw
        top = bool(mk.strip()) and mk[:1] not in (" ", "\t") and not mk.lstrip().startswith("(")
        fenced = bool(raw.strip()) and not mk.strip()           # a line the fence mask blanked: inside a fenced block (the fence lines included)
        if (top and not fenced) or not out:
            if not raw.strip():
                continue
            out.append([raw])
        else:
            out[-1].append(raw)
    ents = []
    for lines in out:
        while lines and not lines[-1].strip():
            lines.pop()
        ents.append("\n".join(lines))
    return [e for e in ents if e.strip()]


def stored(meta: dict[str, Any]) -> list[list[str]]:
    """The writer pairs on the metadata, [[writer, key], …], tolerating anything else a store might hold."""
    v = meta.get("next_by")
    return [[str(p[0]), str(p[1])] for p in v if isinstance(p, (list, tuple)) and len(p) == 2] if isinstance(v, list) else []


def resolve(meta: dict[str, Any], keeper: str) -> list[tuple[str, str]]:
    """[(line, writer)] for the lines of metadata.next, in order: the writer stored for the line's text, else the item's creator's (a line stored before writers were recorded, or one a write that knows nothing of writers put there)."""
    pairs = stored(meta)
    used = [False] * len(pairs)
    out: list[tuple[str, str]] = []
    for e in split(meta.get("next")):
        k = key_of(e)
        w = keeper
        for j, (pw, pk) in enumerate(pairs):
            if not used[j] and pk == k:
                used[j], w = True, pw
                break
        out.append((e, w))
    return out


def _put(meta: dict[str, Any], rows: list[tuple[str, str]], text: str | None) -> None:
    """Store `rows` as the item's next: the text as given when `text` is not None (the sender's call text, verbatim, when the lines are all its own), else the lines joined."""
    if not rows:
        meta.pop("next", None)
        meta.pop("next_by", None)
        return
    meta["next"] = text if text is not None else "\n".join(e for e, _ in rows)
    meta["next_by"] = [[w, key_of(e)] for e, w in rows]


class NextFormError(ValueError):
    """A next text that cannot be stored beside other writers' lines without changing which lines there are."""


def write(meta: dict[str, Any], text: str, writer: str, keeper: str, same: Callable[[str, str], bool], *, wipe: bool = False, drop_own: bool = False) -> list[tuple[str, str]]:
    """The one place a session's next lands on the metadata. `writer` is the canonical id of the session whose call it is. `wipe` removes every line first
    (clear_next); `drop_own` removes the writer's lines and adds none (next="none"); otherwise the writer's lines are replaced by those of `text` (none
    when it is empty, which leaves everything as it is). `same(a, b)` says whether two session references are one session. A line whose writer is empty (a legacy
    line of an item with no keeper, or a pair stored with none) goes to the keeper when there is one; with none, any sender's write replaces it.
    A line of the text that the writer has no open line of already, and that another writer's open line reads the same (norm), is not added a second time (the sender
    keeps a step on its list by writing it again, and it was another session's line): that step stays as it is, its writer's; each of their lines takes up one copy. A line the writer
    already has stays its own, so an update never collapses duplicates that are there. → the lines left out that way, [(line, the writer whose line it is)].
    Raises NextFormError, storing nothing, when the lines built would not read back as the same lines (an indented, note or fence first line that would glue onto the
    entry of another writer above it)."""
    cur = [] if wipe else [(e, w or keeper) for e, w in resolve(meta, keeper)]
    new = [] if drop_own else split(text)
    if not new and not drop_own and not wipe:
        return []
    theirs = [(norm(e), w) for e, w in cur if w and not same(w, writer)]
    mine = [norm(e) for e, w in cur if not w or same(w, writer)]
    merged: list[tuple[str, str]] = []
    kept = []
    for n in new:
        k = norm(n)
        if k in mine:
            mine.remove(k)
            kept.append(n)
            continue
        j = next((j for j, (tk, _) in enumerate(theirs) if tk == k), -1)
        if j >= 0:
            merged.append((n, theirs.pop(j)[1]))
        else:
            kept.append(n)
    new = kept
    out: list[tuple[str, str]] = []
    placed = False
    for e, w in cur:
        if not w or same(w, writer):
            if not placed:
                out += [(n, writer) for n in new]
                placed = True
            continue
        out.append((e, w))
    if not placed:
        out += [(n, writer) for n in new]
    if new and any(w != writer for _, w in out):
        if split("\n".join(e for e, _ in out)) != [e for e, _ in out]:
            raise NextFormError("next must start with a line naming who takes the step, not an indented, parenthesised or fenced line: written after another session's line it would read as part of that line")
    verbatim = str(text) if new and all(w == writer for _, w in out) else None      # nobody else has a line: the text stays exactly as the sender wrote it
    _put(meta, out, verbatim)
    return merged


def lift_first(meta: dict[str, Any], is_ask: Callable[[str], bool], writer: str | None = None, keeper: str = "", same: Callable[[str, str], bool] | None = None) -> str:
    """The ask-shaped first line of the writer's first line of next (with `writer` None: of the first line of next), taken out of next together with the indented lines under
    it, the other lines keeping their writers. → the line (stripped), or "" when the first line is not `is_ask`."""
    rows = resolve(meta, keeper)
    idx = next((k for k, (_, w) in enumerate(rows) if writer is None or not w or (same and same(w, writer))), None)
    if idx is None:
        return ""
    first = next((ln for ln in rows[idx][0].splitlines() if ln.strip()), "")
    if not first.strip() or not is_ask(first.strip()):
        return ""
    rest = rows[:idx] + rows[idx + 1:]
    _put(meta, rest, None)
    return first.strip()


def carry(old_meta: dict[str, Any], meta: dict[str, Any], keeper: str) -> None:
    """After a write that set metadata.next without knowing writers (the migration naming lines): the lines keep the writers they had by position when the
    count is the same, else they are the keeper's. Rewrites next_by; metadata.next is left as it is."""
    was = resolve(old_meta, keeper)
    now = split(meta.get("next"))
    if not now:
        meta.pop("next_by", None)
        return
    ws = [w for _, w in was] if len(was) == len(now) else [keeper] * len(now)
    meta["next_by"] = [[w, key_of(e)] for e, w in zip(now, ws)]


def text_of(meta: dict[str, Any], writer: str, keeper: str, same: Callable[[str, str], bool]) -> str:
    """The lines of next that `writer` wrote, as one text: what a write by that session sets, and so what the guards on next's text judge of it (the lines of other writers stand
    as they were and are not this write's to answer for)."""
    return "\n".join(e for e, w in resolve(meta, keeper) if not w or same(w, writer))


def writers_of(meta: dict[str, Any], keeper: str) -> list[str]:
    """The writer of each line of next, in order (the creator's for a line with none stored)."""
    return [w for _, w in resolve(meta, keeper)]


def prune(meta: dict[str, Any], texts: list[str], keeper: str) -> int:
    """Take the lines `texts` out of next, each text the first line that reads the same (key_of), with its writer pair; the other lines keep their writers. → how many were taken. A step marked
    done or dropped leaves next this way, whoever wrote it."""
    rows = resolve(meta, keeper)
    gone = 0
    for t in texts:
        k = key_of(t)
        j = next((j for j, (e, _) in enumerate(rows) if key_of(e) == k), None)
        if j is not None:
            del rows[j]
            gone += 1
    if gone:
        _put(meta, rows, None)
    return gone


def reword(meta: dict[str, Any], old: str, new: str, keeper: str, writer: str | None = None, new_writer: str | None = None) -> bool:
    """Change the text of one line of next in place: the first line that reads `old` (key_of; with `writer`, the first of that writer's), its position and its writer pair kept (with `new_writer`, the line
    becomes that session's: a step the server hands to another session). → whether a line was found. The lines are stored joined (the text a sole writer wrote verbatim keeps its other lines as they were)."""
    rows = resolve(meta, keeper)
    k = key_of(old)
    j = next((j for j, (e, w) in enumerate(rows) if key_of(e) == k and (writer is None or w == writer)), None)
    if j is None:
        return False
    rows[j] = (str(new).strip(), rows[j][1] if new_writer is None else new_writer)
    _put(meta, rows, None)
    return True


def append(meta: dict[str, Any], line: str, writer: str, keeper: str) -> None:
    """Add one line at the end of next, written by `writer` (a line the server makes: its writer is the server's, so no session's update replaces it). The other lines keep their writers."""
    rows = resolve(meta, keeper)
    rows.append((str(line).strip(), writer))
    _put(meta, rows, None)
