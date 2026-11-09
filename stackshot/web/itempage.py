"""itempage.py — the words of the item page on the item model (the design: docs/design, section 8).

The item page (render.py, Board.item_html) says an item in the model's terms: the goal as the title, one state line (state · since; the wait block: waiting on · watched by · until · then;
done · date · outcome; the mover is the sidebar's first row) with the latest change beside it, the ask when the owner is the mover, Next as numbered lines each naming its mover, the wait and its chases.
This module is the pure half: plain text in, plain text out, no HTML, no Board and no server import (it reads model.py, watchers.py, handoff.py and model_guards.py for the one
copy of the model's words). The renderer escapes and links what comes out. Nothing here is stored: every sentence is generated from fields the item already has.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from stackshot.waits import event_waits as _ew
from stackshot.web import home as _home
from stackshot.model import step_commands as _sc
from stackshot.model import model as _model
from stackshot.model import model_guards as _mg
from stackshot.model import states as _states
from stackshot.model import steps as _steps
from stackshot.waits import watchers as _wat

CLIP = 160                         # the longest an action or an entry is quoted inside a sentence
_WATCHERS = {"time": "the scheduler", "relay": "the scheduler", "item": "the server", "anchor": "the anchor module", "event": "the server"}   # who ends each kind of wait (design section 4)


def clean(v: Any) -> str:
    return " ".join(str(v or "").split())


_PAIRS = (("“", "”"), ("(", ")"), ("[", "]"), ("«", "»"))


def _unbalanced(t: str) -> int:
    """The position of the opener that is never closed in `t` (a quote, bracket or backtick), -1 when every one is."""
    for o, c in _PAIRS:
        if t.count(o) > t.count(c):
            return t.rfind(o)
    for q in ('"', "`"):
        if t.count(q) % 2:
            return t.rfind(q)
    return -1


def clip(text: Any, n: int = CLIP) -> str:
    """A text on one line, cut to at most `n` characters at a sentence end or else a word end, never inside a quote, bracket or code span, with "…" where it was cut."""
    t = clean(text)
    if len(t) <= n:
        return t
    cut = t[:n - 1]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if end >= n // 2:
        return cut[:end + 1]
    sp = cut.rfind(" ")
    cut = cut[:sp] if sp >= n // 3 else cut
    while True:
        i = _unbalanced(cut)
        if i < 0:
            break
        cut = cut[:i].rstrip()
    return cut.rstrip(" ,;:-—–(\"“`") + "…"


def watched_by(kind: str) -> str:
    """Who watches a wait of this kind: the scheduler (a date: a wake, an ask-by day), the server (another item's close), the anchor module (an outside event)."""
    return _WATCHERS.get(kind, "the server")


def age_text(seconds: float, age_words: Callable[[float], str]) -> str:
    return age_words(max(0.0, float(seconds)))


# ---------------------------------------------------------------------------------------------------------------- since when
def since_of(item: dict[str, Any], mod: "_model.Model") -> float:
    """When the item's present state began (epoch seconds; 0 when nothing says). An alive item: the latest of its state clock, its last hand-off and the time it woke (a wait that
    ended); a closed one: its state clock (the close), else its last update. The server's own saves leave `state_updated` alone, so a wake or an idle mark never moves it."""
    m = item.get("metadata") or {}

    def num(v: Any) -> float:
        try:
            x = float(v or 0)
        except (TypeError, ValueError):
            return 0.0
        return x if 0 < x < 4102444800 else 0.0

    base = num(item.get("state_updated")) or num(item.get("updated"))
    if mod.state == _model.DEAD:
        return base
    ho = m.get("handoff") if isinstance(m.get("handoff"), dict) else {}
    wk = m.get("woke") if isinstance(m.get("woke"), dict) else {}
    return max(base, num(ho.get("at")), num(wk.get("at")))


# ---------------------------------------------------------------------------------------------------------------- the wait, in words
def wait_what(w: "_model.Wait", *, shown: Callable[[str], str] = str, party: str = "", words: str = "") -> str:
    """What a wait waits on, as the state line says it: a time → his words or the basis, else "a date"; an item → the close of board#N; an anchor → the anchor's event; a relay → the
    party's news. `party` names who the relay waits on, `words` is the time wait's reason (the basis, or his recorded words)."""
    if w.kind == "time":
        return clean(words) or "a date"
    if w.kind == "item":
        return "the close of " + (", ".join(shown(x) for x in w.after) or "an item")
    if w.kind == "anchor":
        return clean(w.event) or "an anchor event"
    if w.kind == "event":
        return _ew.words(w.event) if clean(w.event) else "a fleet event"
    ev = clean(w.event)
    p = clean(party)
    if not ev:
        return f"news from {p}" if p else "outside news"
    return f"{ev} from {p}" if p and p.lower() not in ev.lower() else ev


def wait_end_label(w: "_model.Wait") -> str:
    """The word before a wait's end date: "until" for a time, "ask by" for a relay (the day it turns into a question), "backstop" for an event wait's fallback date."""
    if w.kind == "relay":
        return "ask by"
    if w.kind in ("anchor", "item", "event") and not w.until:
        return "backstop"
    return "until"


# ---------------------------------------------------------------------------------------------------------------- Next
@dataclass
class NextLine:
    """One line of next: its text (with its `<mover>: ` opener, added when the writer left it off) and the lines indented or bulleted under it."""
    text: str
    named: bool                       # the writer named the mover (False: the opener was filled in from the item's own mover)
    subs: list[str] = field(default_factory=list)


_MARKER = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+")
_FENCE_LINE = re.compile(r"^\s*(?:```|~~~)")


def is_fence(text: str) -> bool:
    """Is this sub-content a fenced code block (the renderer draws it as a block, not as a line)?"""
    return bool(_FENCE_LINE.match(str(text or "")))


def _fenced_lines(text: str) -> list[tuple[str, bool]]:
    """[(line, inside a fenced block)] by the write guards' fence rules (model_guards._FENCE_RX): a fence line and what it holds are code."""
    spans = [(m.start(), m.end()) for m in _mg._FENCE_RX.finditer(text)]
    out, pos = [], 0
    for raw in text.splitlines(keepends=True):
        out.append((raw.rstrip("\r\n"), any(a <= pos < b for a, b in spans)))
        pos += len(raw)
    return out


def next_lines(text: Any, mover: str) -> list[NextLine]:
    """The item's next as lines, counted as the write guards count them (model_guards.next_openers): a top-level line is a line of next, bulleted or numbered or not, when it opens with
    `<name>: ` (its marker is dropped from the shown text: no double numbering); an unnamed bullet or number, an indented line and a server note in parentheses belong to the line above;
    a fenced code block stays whole under the line above, never split into lines and never given a mover. A top-level line that opens with no name gets the item's own mover as its
    opener (`mover`: the mover of an alive item, the post-wake mover of a waiting one)."""
    out: list[NextLine] = []
    block: list[str] = []

    def flush() -> None:
        if block:
            if not out:
                out.append(NextLine("", True))
            out[-1].subs.append("\n".join(block))
            block.clear()

    for raw, fenced in _fenced_lines(str(text or "")):
        if fenced:
            block.append(raw)
            continue
        flush()
        if not raw.strip():
            continue
        s = raw.strip()
        marked = bool(_MARKER.match(raw))
        body = _MARKER.sub("", s, count=1) if marked else s
        named = bool(_mg._NAME_RX.match(_mg._MARK_RX.sub("", body.replace("**", ""))))
        if out and (raw[:1] in (" ", "\t") or s.startswith("(") or (marked and not named)):
            out[-1].subs.append(body)
            continue
        out.append(NextLine(_steps.collapse_owner(body) if named else body if not clean(mover) else f"{clean(mover)}: {body}", named))
    flush()
    return out


# ---------------------------------------------------------------------------------------------------------------- the step of a your-step item
@dataclass
class StepBlock:
    """The step of a your-step item as both the home row and the item page draw it: `text` is the step as written with each command taken out of it ("the command below"), `blocks`
    the commands (or the one link) to copy, `verbatim` a `! ...` line he types in a pane: the whole step, as written, is the one block and there is no text."""
    text: str
    blocks: list[str]
    verbatim: bool = False
    parts: "list[_sc.Part] | None" = None      # a step that is a numbered list or holds a fenced block (step_commands.parse): drawn part by part, `text` and `blocks` are empty


def step_block(item: dict[str, Any]) -> "StepBlock | None":
    """The step of an open item whose stored state is your-step (the single thing only the owner does: states.py), None for any other item or one with no step line. The one reading
    the home row (render.Board.home_row) and the item page (Board.item_html) share, so they cannot drift: a numbered list or a fenced block is drawn part by part (step_commands.parse); a `! ...` line stays verbatim in one block; a backticked command (a span with
    a space in it) leaves the line for a block of its own; with no command a link is the block; else the step is plain text."""
    if item.get("status") == "completed" or _states.stored(item) != "your-step":
        return None
    raw = str((item.get("metadata") or {}).get("step") or "").strip()
    if not clean(raw):
        return None
    if _sc.structured(raw):
        return StepBlock("", [], False, _sc.parse(raw))
    if raw.startswith("!"):
        return StepBlock("", [raw], True)
    text, blocks = _home.copyables(clean(raw))
    return StepBlock(text, blocks)


# ---------------------------------------------------------------------------------------------------------------- clipping markdown and the state line's latest change
_SPAN = re.compile(r"\[[^\]\n]*\]\([^)\s]*\)|`[^`\n]+`|\*\*[^*\n]+\*\*|(?<![\w*])\*[^*\s][^*\n]*\*(?![\w*])|(?<![\w_])_[^_\s][^_\n]*_(?![\w_])|https?://\S+")
_LINK = re.compile(r"\[([^\]\n]*)\]\([^)\s]*\)$")


def clip_md(text: Any, n: int = CLIP) -> str:
    """Item text that is markdown, cut to at most `n` characters on its source so that a cut never falls inside a link, a code span, a bold span or a bare address: a span the cut
    would split is dropped whole, except a link, which keeps its text (without the address) when that fits. Whole sentences and words as clip() has them; "…" where it was cut."""
    t = clean(text)
    if len(t) <= n:
        return t
    spans = [(m.start(), m.end()) for m in _SPAN.finditer(t)]
    inside = lambda i: any(a < i < b for a, b in spans)          # a position strictly inside a span
    limit = n - 1
    cut = t[:limit]
    end = max((i for i in range(len(cut)) if cut[i] in ".!?" and i + 1 < len(t) and t[i + 1] == " " and not inside(i)), default=-1)
    if end >= n // 2:
        return t[:end + 1]
    hit = next(((a, b) for a, b in spans if a < limit < b or (a < limit and b > limit)), None)
    if hit:                                                      # the cut falls in a span: before it, or a link's text alone
        a, b = hit
        m = _LINK.match(t[a:b])
        if m and a + len(m.group(1)) <= limit and clean(m.group(1)):
            return (t[:a] + m.group(1)).rstrip() + "…"
        cut = t[:a]
    else:
        sp = max((i for i in range(len(cut)) if cut[i] == " " and not inside(i)), default=-1)
        cut = cut[:sp] if sp >= n // 3 else cut
    while True:
        i = _unbalanced(_SPAN.sub(lambda m: "x" * len(m.group(0)), cut))
        if i < 0:
            break
        cut = cut[:i].rstrip()
    return cut.rstrip(" ,;:-—–(\"“") + "…"


UPDATED_CLIP = 80                  # the longest the latest change is on the state line: one short line


_MOVER_CLAUSE = re.compile(r"^mover: .+ → (?P<to>.+)$")
_DROPPED_CLAUSE = re.compile(r"^(?:model|expected_by)\b|^state: doing$")
_NEEDS_CLAUSE = re.compile(r"^needs: (?!(?:decision|external)\b)", re.I)
_CLEARED_CLAUSE = re.compile(r"^state cleared \(was .+\)$")
_KEPT_CLAUSE = re.compile(r"^(?:completed|woke|named)\b")
LAST_CLAUSES = 2                   # how many clauses of one History entry the state line shows
# A clause starts after "; " and a label the History writes (Board.item_log): `next: …`, `needs: …`, `next and ask edited`, `state cleared (…)`, `completed …`. A semicolon inside a
# field's value ("next: a; then b") is not followed by a label, so it never makes a clause.
_CLAUSE_START = re.compile(
    r";\s+(?=(?:(?:needs|after|rank|state|mover|model|due|priority|project|subject|observers|confirmed|wake|woke|goal|then|expected_by|step|party|chase|supplies|proof|end|work"
    r"|wait basis|whose move|the ask was|the options were|his words recorded)\s*:"
    r"|(?:next|ask|options|description)\b(?:\s*:|,| and | edited| cleared)"
    r"|(?:state|rank|due|after|step) (?:cleared|set to|moved|edited)\b|draft (?:set|edited|cleared)\b|refiled from\b|reminder (?:set|cleared)\b|wake (?:set|cleared)\b"
    r"|waits for a pane recycle|no longer waits|put on hold|back from hold|reopened\b|completed\b|created\b|confirmed\b|state [a-z-]+ →))", re.I)


def plain_change(what: Any) -> str:
    """A History entry (`a; b; c`, the clauses the log writes) in plain words for the owner, before it is clipped (the History keeps the full text); it splits only where "; " is followed by a label the History writes, so a semicolon inside a field's value stays in that clause: `mover: A → B` is "handed to B"; `needs: decision`
    together with `state: your-call` is "asked for your decision"; `state: your-step` is "gave you a step"; a clause that opens `next` (`next edited`, `next and ask edited`, `next: …`) is "changed what
    comes next"; `description …` is "updated the background"; `model: …`, `expected_by: …` and `state: doing` are dropped, and so is `needs: <session>` when a `mover:` clause is in the entry (the hand-over says it); `state cleared (was …)` is "took it back to work"; `completed …`, `woke: …` and `named …` and any clause not listed stay as written. The
    first LAST_CLAUSES clauses are joined with ", ". The text itself when no clause is left to show."""
    t = clean(what)
    clauses = [c.strip() for c in _CLAUSE_START.split(t) if c.strip()]
    if not clauses:
        return t
    asked = "needs: decision" in [c.lower() for c in clauses] and "state: your-call" in clauses
    moved = any(_MOVER_CLAUSE.match(c) for c in clauses)
    out: list[str] = []
    for c in clauses:
        m = _MOVER_CLAUSE.match(c)
        if _DROPPED_CLAUSE.match(c) or (moved and _NEEDS_CLAUSE.match(c) and not asked):
            continue
        if asked and c.lower() in ("needs: decision", "state: your-call"):
            if "asked for your decision" not in out:
                out.append("asked for your decision")
        elif m and clean(m.group("to")) not in ("", "no one"):
            out.append(f"handed to {clean(m.group('to'))}")
        elif _CLEARED_CLAUSE.match(c):
            out.append("took it back to work")
        elif c == "state: your-step":
            out.append("gave you a step")
        elif re.match(r"^next\b", c) and not _KEPT_CLAUSE.match(c):
            out.append("changed what comes next")
        elif re.match(r"^description\b", c):
            out.append("updated the background")
        else:
            out.append(c)                                   # completed …, woke: …, named … and anything unrecognised: as written
    return ", ".join(out[:LAST_CLAUSES]) if out else t


def last_change(who: Any, what: Any, esc: Callable[[str], str] = str) -> str:
    """The latest History entry as the tail of the state line's "updated <age>": ` by <who>: <what>`, `what` in plain words (plain_change) and cut to UPDATED_CLIP characters on a word
    with no closing stop, all of it through `esc` (plain text to HTML). "" when the entry has no `what`; no ` by` when it has no `who`."""
    t = clip(plain_change(what), UPDATED_CLIP).rstrip(".:")
    if not clean(t):
        return ""
    return (f" by {esc(clean(who))}" if clean(who) else "") + f": {esc(t)}"


# ---------------------------------------------------------------------------------------------------------------- the History's plain text
_TAG = re.compile(r"<[^>]+>")


def plain(html_text: str) -> str:
    """An escaped History line without its tags, as one clean line of text."""
    import html as _html
    return clean(_html.unescape(_TAG.sub("", str(html_text or ""))))


def is_comment(kind: str, line: str) -> bool:
    """Does a History entry belong in Comments (a person's words) rather than History (what changed)? A comment written on GitHub, or the owner's comment from the board's box."""
    return kind == "comment" or (kind == "answer" and clean(line).lower().startswith("comment:"))


def chase_rows(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """The chases logged on a waiting item (watchers.chases_of), oldest first: [{at, by, note}]."""
    return _wat.chases_of(meta)
