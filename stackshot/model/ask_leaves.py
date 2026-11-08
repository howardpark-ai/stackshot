"""ask_leaves.py — a wrong ask leaves the owner's move on its own, a dropped dependency reminds its author (a pure module, no config and no store).

An ask that stands on an item is the owner's move. The server removes it from his move in ONE case: its author writes, alone, one plain sentence saying the ask is wrong or moot. A board item the ask
waits on being dropped only reminds the author, on his next write to the item: a gate is a precondition, not the thing asked, so a dropped gate often makes the ask more live, and only the author can
tell. Four things are read here, each from what the item already holds; the server's writes are in server.py (`_ask_leave`, `_ask_after_write`).

  the record of an ask   `metadata.ask_rec` = {by, at, text}: who wrote the ask, when, and its text. Stamped by `stamp` on every save that changes the ask (the author is the writing session; a
                         server save has none); a new ask also drops `ask_left`, the record of the one taken off. It counts only while its text is the ask's, so a stale record is never read.
  the author's word      `author_says_wrong(texts)`: the ENTIRE new text of a write by the ask's author (all its new lines, joined) is exactly one sentence of the closed shape, with at most one list bullet
                         ("- ") before it and a full stop after it: "the|this|my ask is wrong|moot|stale|void|obsolete|no longer needed|no longer valid" or "this|my question is ...", with "now" or
                         "anymore" at most after it. Any other new line or sentence in the write, a label ("Note:", "Fix:", "Pat's review:", "infra-reviewer:"), a quote, a hedge, a question or another
                         language leaves the ask standing. Only text that is new in the write is read (`new_lines`): a line that is, whole, a line the item already held (compared line by line, never as a
                         part of a longer line) is not the author's word again. The server acts on this and on nothing else a session writes.
  the dependency         `depends_on(ask)`: the board ids the ask's text names after a gate form, "after|once|when|until|following board#N lands|is merged|is live|is done|...", "waiting for|on board#N to
                         land|merge|finish|complete" or "depends on board#N landing|merging|finishing". `dropped_deps(ask, lookup, ask_at)`: those of them closed as DROPPED AFTER the ask was written (a
                         superseded item continues in its replacement, so it counts only when the chain ends in a dropped item, which `lookup` follows; with no ask time nothing is found). Only a
                         reminder reads them (`dropped_line`), never a removal.
  the owner's notes      `notes_since(meta, since)`: his comments and notes on a step since a time, for the author to read at an ask-time check and in the reminder.

The server only takes the ask off his move on the author's plain sentence (and keeps what he wrote as comments); it never writes an ask, closes an item or answers for him.
"""
from __future__ import annotations

import re
import time
from typing import Any, Callable

REC = "ask_rec"
LEFT = "ask_left"
NOTE_DAYS = 3.0        # an ask written on an item with no earlier ask looks back this many days for the owner's notes
_CORE_RX = re.compile(      # the whole sentence, nothing else: "the ask is wrong", "my question is moot", "this ask is no longer needed" (a bare "the question" is nobody's in particular)
    r"^(?:(?:the|this|my)\s+ask|(?:this|my)\s+question)\s+is\s+(?:wrong|moot|stale|void|obsolete|no\s+longer\s+(?:needed|valid))(?:\s+(?:now|anymore|any\s+more))?\.?$", re.I)
_CITE_RX = re.compile(r"(?<![\w#/&-])board#(\d+)(?!\d)", re.I)
_REF = r"board#\d+(?!\d)"
_REFS = rf"{_REF}(?:\s*(?:,|and|or|&)\s*(?:the\s+)?(?:items?\s+)?{_REF})*"      # "board#N", "board#N and board#M", "board#N, board#M"
_DONE = (r"(?:(?:is|are|has|have|gets?|get)\s+(?:been\s+)?)?(?:lands?|landed|merged|released|live|done|completes?|completed|ships?|shipped|ready|finish(?:es|ed)?|deployed)"      # a completion
        r"|go(?:es)?\s+live")
_GATE_RX = re.compile(      # the ask's own action is gated on the dependency finishing: "after|once|when|until|following board#N lands|is merged|is live|is done|completes|ships|is ready"
    rf"(?<![\w#/&-])(?:after|once|when|until|following)\s+(?:the\s+)?(?:items?\s+)?(?P<a>{_REFS})\s+(?:{_DONE})\b", re.I)
_WAIT_RX = re.compile(      # "waiting for|on board#N to land|merge|finish|complete"
    rf"(?<![\w#/&-])(?:waits?|waiting)\s+(?:on|for)\s+(?:the\s+)?(?:items?\s+)?(?P<a>{_REFS})\s+to\s+(?:land|merge|finish|complete|ship|release|go\s+live)\b", re.I)
_DEPLAND_RX = re.compile(      # "depends on board#N landing|merging|finishing|completing|shipping|being merged"
    rf"(?<![\w#/&-])depends?\s+on\s+(?:the\s+)?(?:items?\s+)?(?P<a>{_REFS})\s+(?:landing|merging|finishing|completing|shipping|releasing|being\s+(?:merged|done|released|shipped|completed))\b", re.I)
_DROPPED = "dropped"      # a superseded item continues in its replacement: the lookup follows it, and only a chain that ends in a dropped item reads as dropped


def author_says_wrong(texts: list[str]) -> str:
    """The sentence in which the author of a write says the ask is wrong or moot, "" when none does. `texts` is the NEW text of the write (see `new_lines`): all of it, taken together, must be exactly
    one sentence of the closed shape, "the|this|my ask is wrong|moot|stale|void|obsolete|no longer needed|no longer valid" or "this|my question is ..." (with "now" or "anymore" at most after it), with at
    most one list bullet ("- ") before it and a full stop after it. Any other new line or sentence, a label, a quote, a hedge, a question or another language leaves the ask standing."""
    lines = [" ".join(ln.split()) for t in texts for ln in str(t or "").splitlines() if ln.strip()]
    if len(lines) != 1:
        return ""
    body = re.sub(r"^-\s+", "", lines[0])
    return body if _CORE_RX.match(body) else ""


def _norm_line(x: Any) -> str:
    return " ".join(re.sub(r"^[\s\-*•]+", "", str(x or "")).lower().split())


def new_lines(texts: list[str], old: str) -> list[str]:
    """The lines of `texts` (every text parameter of a write) that are new in it. A line is held when it equals, whole, one line of `old` (the text the item held before the write: one line per line,
    however it is bulleted or cased); a line that only appears inside a longer old line ("Status: migration is not yet done" holds no "Not yet") is new. A stale line re-sent with a later write is not
    a new word of its author."""
    held = {n for n in (_norm_line(ln) for ln in str(old or "").splitlines()) if n}
    out = []
    for t in texts:
        for line in str(t or "").splitlines():
            n = _norm_line(line)
            if n and n not in held:
                out.append(line)
    return out


def text_leaves(value: Any) -> list[str]:
    """Every string inside a parameter or a stored value (a string, a mapping, a list, nested), one entry each, in order: the free text a write carries or an item holds."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [x for v in value.values() for x in text_leaves(v)]
    if isinstance(value, (list, tuple)):
        return [x for v in value for x in text_leaves(v)]
    return []


def standing(meta: dict[str, Any], decision_kinds: list[str], watcher_ask: bool) -> str:
    """The ask that stands on the owner's move now, "" when none does: an open item's ask line with a decision in needs, and not a watcher's own fixed ask (the watchers answer for those)."""
    ask = " ".join(str(meta.get("ask") or "").split())
    return ask if ask and "decision" in [k.lower() for k in decision_kinds] and not watcher_ask else ""


def rec_of(meta: dict[str, Any]) -> dict[str, Any]:
    """The record of the ask that stands: {by, at, text}, {} when none is kept or it is of another ask."""
    r = meta.get(REC)
    if isinstance(r, dict) and " ".join(str(r.get("text") or "").split()) == " ".join(str(meta.get("ask") or "").split()):
        return r
    return {}


def changed(meta: dict[str, Any], before_meta: dict[str, Any] | None) -> bool:
    """Does this save set an ask that differs from the one before it (whitespace aside)? Only then does `stamp` use its `who`, so a caller computes the writer's label only when this is true."""
    ask = " ".join(str(meta.get("ask") or "").split())
    return bool(ask) and ask != " ".join(str((before_meta or {}).get("ask") or "").split())


def stamp(meta: dict[str, Any], before_meta: dict[str, Any] | None, who: str, now: float) -> None:
    """Keep who wrote the ask and when, on a save that changes it (`who` "" for a server save). A save that leaves the ask as it was keeps the record; one that removes the ask drops it."""
    ask = " ".join(str(meta.get("ask") or "").split())
    if not ask:
        meta.pop(REC, None)
        return
    if changed(meta, before_meta):      # an ask stored before this record stays without one: its author is not guessed from a later save
        meta[REC] = {"by": who, "at": now, "text": ask}
        meta.pop(LEFT, None)      # a new ask is a new question: a late pick on the one taken off reads stale from now on


def depends_on(ask: str) -> list[str]:
    """The board ids the ask's text names after a gate, in order, each once: "after|once|when|until|following board#N lands|is merged|is released|is live|is done|completes|ships|is ready", "waiting
    for|on board#N to land|merge|finish|complete" or "depends on board#N landing|merging|finishing" (a list, "board#N and board#M", counts for each). A bare "after board#N", "blocked by" or a citation
    names no gate. It only informs the author's reminder: a wrong reading costs a line, never a removal."""
    hits = sorted((m for rx in (_GATE_RX, _WAIT_RX, _DEPLAND_RX) for m in rx.finditer(" ".join((ask or "").split()))), key=lambda m: m.start())
    return list(dict.fromkeys(c.group(1) for m in hits for c in _CITE_RX.finditer(m.group("a"))))


def dropped_deps(ask: str, lookup: Callable[..., tuple | None], ask_at: float | None = None) -> list[tuple[str, float, str]]:
    """The items the ask waits on (`depends_on`) that were closed as DROPPED AFTER the ask was written (`ask_at`, the epoch of its record): [(number, closed epoch, how it ended in words)]. None known
    ask time: nothing is found (a drop cannot be compared with a write nobody dated, and an ask written about a dependency that was already dropped is the fallout of it). `lookup(number)` → (status,
    outcome, closed epoch[, label]) of an item, a superseded one followed to the end of its replacement chain; None when it cannot be read (then it is left out)."""
    out = []
    if ask_at is None:
        return out
    for i in depends_on(ask):
        got = lookup(i)
        if got and got[0] == "completed" and got[1] == _DROPPED and float(got[2] or 0) > ask_at:
            out.append((i, float(got[2]), str(got[3]) if len(got) > 3 and got[3] else got[1]))
    return out


def dropped_line(found: list[tuple[str, float, str]], when: Callable[[float], str]) -> str:
    """The reminder's dropped-dependency fact, "" when there is none: each item as "board#N, which this ask waits on, was dropped on <date>", then the one instruction."""
    if not found:
        return ""
    return ("; ".join(f"board#{n}, which this ask waits on, was {how} on {when(ts)}" for n, ts, how in found)
            + "; if the ask is moot withdraw it now (clear_ask=true), otherwise it stands")


def notes_since(meta: dict[str, Any], since: float) -> list[dict[str, Any]]:
    """The owner's comments and notes on his step made after `since` (an epoch), oldest first: [{ts, kind, text}]. His answers to a decision are no notes (they closed the ask)."""
    out = []
    for a in meta.get("answers") if isinstance(meta.get("answers"), list) else []:
        if isinstance(a, dict) and a.get("kind") in ("comment", "step-reply") and float(a.get("ts") or 0) > since and str(a.get("text") or "").strip():
            out.append({"ts": float(a["ts"]), "kind": a["kind"], "text": " ".join(str(a["text"]).split())})
    return sorted(out, key=lambda x: x["ts"])


def look_back(meta: dict[str, Any], now: float | None = None) -> float:
    """Where the owner's notes are looked for when an ask is written: after the item's earlier ask was written (or taken off his move), else the last NOTE_DAYS."""
    now = time.time() if now is None else now
    prior = max([float((meta.get(REC) or {}).get("at") or 0) if isinstance(meta.get(REC), dict) else 0.0,
                 float((meta.get(LEFT) or {}).get("at") or 0) if isinstance(meta.get(LEFT), dict) else 0.0])
    return prior or now - NOTE_DAYS * 86400


def notes_line(notes: list[dict[str, Any]], clip: Callable[[str, int], str], when: Callable[[float], str], limit: int = 3) -> str:
    """His notes as one clause: “text” (when), the newest `limit`."""
    return "; ".join(f"“{clip(n['text'], 160)}” ({when(n['ts'])})" for n in notes[-limit:])


def reminder(shown_id: str, owner: str, notes_clause: str = "", dropped_clause: str = "") -> str:
    """The one line a write gets while an ask stands on an item its author moves or wrote. `dropped_clause` (`dropped_line`) is added for the ask's author only."""
    return (f"\n(reminder: an ask stands on {shown_id} for {owner}; if it is wrong or moot, withdraw it now: update(clear_ask=true) and name who has the item in needs"
            + (f". {dropped_clause}" if dropped_clause else "") + (f". His notes since the ask: {notes_clause}" if notes_clause else "") + ")")


def check_line(owner: str, notes_clause: str) -> str:
    """The ask-time check's line: the owner's notes on the item that may already answer the ask being written."""
    return (f"\n(check: {owner} has written on this item since its last ask: {notes_clause}. If a note already answers the ask, apply it and withdraw the ask "
            f"(update(clear_ask=true)) instead of asking again.)")
