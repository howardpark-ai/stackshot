"""itempage.py — the words of the item page on the item model (the design: docs/design, section 8).

The item page (render.py, Board.item_html) says an item in the model's terms: the goal as the title, one state line (state · since; the wait block: waiting on · watched by · until · then;
done · date · outcome; the mover is the sidebar's first row), the ask when the owner is the mover, Next as numbered lines each naming its mover, the wait and its chases.
This module is the pure half: plain text in, plain text out, no HTML, no Board and no server import (it reads model.py, watchers.py, handoff.py and model_guards.py for the one
copy of the model's words). The renderer escapes and links what comes out. Nothing here is stored: every sentence is generated from fields the item already has.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from stackshot.waits import event_waits as _ew
from stackshot.web import home as _home
from stackshot.web.i18n import t as _t
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
    return _home.watcher_word(_WATCHERS.get(kind, "the server"))


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
def list_mode_words(mod: "_model.Model") -> str:
    """The mode of a wait on a list as the board says it: "all of 3" or "any of 3" ("" when the model carries no list)."""
    return _t(f"wait.list.{mod.wait_mode}_of", n=len(mod.waits)) if mod.waits and mod.wait_mode in ("all", "any") else ""


def list_watchers(mod: "_model.Model") -> list[str]:
    """Who notices the arrival of the lines of a wait on a list, in the English words watched_by maps (the scheduler, the anchor module, the server), each once, in the order the lines come: the lines
    still open first (an arrived line has no more to watch), every line when none is open."""
    ls = [ln for ln in mod.waits if not ln.arrived] or list(mod.waits)
    return list(dict.fromkeys(_WATCHERS.get(ln.kind, "the server") for ln in ls))


def wait_what(w: "_model.Wait", *, shown: Callable[[str], str] = str, party: str = "", words: str = "", mode: str = "") -> str:
    """What a wait waits on, as the state line says it: a time → his words or the basis, else "a date"; an item → the close of board#N; an anchor → the anchor's event; a relay → the
    party's news. `party` names who the relay waits on, `words` is the time wait's reason (the basis, or his recorded words)."""
    if w.kind == "time":
        return clean(words) or _t("wait.a_date")
    if w.kind == "list":
        return _t("wait.what.list", mode=mode)
    if w.kind == "item" and w.queued:
        return _t("wait.what.queued", items=", ".join(shown(x) for x in w.after) or _t("wait.what.an_item"))
    if w.kind == "item":
        return _t("wait.what.close_of", items=", ".join(shown(x) for x in w.after) or _t("wait.what.an_item"))
    if w.kind == "anchor":
        return clean(w.event) or _t("wait.what.anchor_event")
    if w.kind == "event":
        return _ew.words(w.event) if clean(w.event) else _t("wait.what.fleet_event")
    ev = clean(w.event)
    p = clean(party)
    if not ev:
        return _t("wait.what.news_from", party=p) if p else _t("wait.what.outside_news")
    return _t("wait.what.event_from", event=ev, party=p) if p and p.lower() not in ev.lower() else ev


def wait_end_label(w: "_model.Wait") -> str:
    """The word before a wait's end date: "until" for a time, "ask by" for a relay (the day it turns into a question), "backstop" for an event wait's fallback date; "until" whatever the kind
    when the date is the item's stored `until`."""
    if w.by_until:
        return _t("wait.end.until")
    if w.kind == "relay":
        return _t("wait.end.ask_by")
    if w.kind in ("anchor", "item", "event") and not w.until:
        return _t("wait.end.backstop")
    return _t("wait.end.until")


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
    the commands to copy (a link stays in `text`), `verbatim` a `! ...` line he types in a pane: the whole step, as written, is the one block and there is no text."""
    text: str
    blocks: list[str]
    verbatim: bool = False
    parts: "list[_sc.Part] | None" = None      # a step that is a numbered list or holds a fenced block (step_commands.parse): drawn part by part, `text` and `blocks` are empty


def step_block(item: dict[str, Any]) -> "StepBlock | None":
    """The step of an open item whose stored state is your-step (the single thing only the owner does: states.py), None for any other item or one with no step line. The one reading
    the home row (render.Board.home_row) and the item page (Board.item_html) share, so they cannot drift: a numbered list or a fenced block is drawn part by part (step_commands.parse); a `! ...` line stays verbatim in one block; a backticked command (a span with
    a space in it) leaves the line for a block of its own; else the step is text, a link in it staying inline."""
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


# ---------------------------------------------------------------------------------------------------------------- clipping markdown
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
