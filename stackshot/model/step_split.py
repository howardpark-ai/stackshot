"""step_split.py: a long step of the owner's put into the shape the board draws, a short summary and one line per action.

The board shows what the owner does as a list: the step is a one-line summary (the tab title and the notice read it), and what he does is the lines of `next` that start with his name, drawn as a
numbered list (step_commands.py, render.step_nexts_html). A step written as one long sentence chain, several actions in one line, reads badly there. This module turns such a text into the shape
the board draws; it never refuses and never drops a word.

WHEN A TEXT IS SPLIT (`actions`). SPLIT_OVER characters, one line and not already structured (a numbered or fenced step is the writer's own shape and is kept), with at least two clauses. An action is a
clause cut at the end of a sentence or at a semicolon (bullet_text._clauses: never inside a link, a naked URL, a code span or a parenthesis, nor after an abbreviation or a number), at the
numbered items written inline (`1) … 2) …`, the numbers dropped, the list draws its own), and, for a clause still over the line limit on its own, at its last comma or colon that leaves the piece within
it (bullet_text._soft_units), else at a space. A text under SPLIT_OVER, or one action, is left as written, and so is one that is no step but a document: a text over SPLIT_MAX characters, or one that would
make more than MAX_ACTIONS actions, is never split (the old limits then judge it as they did before; a split of a page of text into hundreds of lines is no help to a reader and costs the item lock its time).
An inline `1)` is an item only where a list can start: at the start of the text or after the end of a sentence or a colon (`Pick plan 1) basic or 2) pro` is no list), and a clause with no letter or digit in it (a stray `;` or `.`)
is no action.

WHAT IT MAKES (`split_step`). The summary: the first action cut at a word to fit SUMMARY_MAX, with `(+N more)` after it, so the summary says there is a list and is never the same words as the
first line (the board skips a line of his that reads as the summary). The lines: every action, each opening with his name (`<owner>: <action>`), each within the line limit, the full stop or semicolon
that ended a clause dropped and nothing else changed. Fed back, the output changes nothing (the summary and every line are under SPLIT_OVER or hold one action).

`split_line` does the same for one long line of next that opens with his name: the lines, one per action, with no summary (the item's step or ask is the summary).

Pure functions of a text and the owner's name: no store, no config (the line limit is the caller's)."""
from __future__ import annotations

import bisect
import re
from typing import Any

from stackshot.model import bullet_text as _bt
from stackshot.model import owner_steps as _os
from stackshot.model import step_commands as _sc
from stackshot.model import steps as _steps

SPLIT_OVER = 110          # a one-line step or line of his longer than this, with two or more actions, is split
SPLIT_MAX = 2000          # …and one longer than this is left as written (the old limits judge it): a step is a summary, and past this it is a page of text, not a chain of actions
MAX_ACTIONS = 20          # …and one that would make more actions than this is left as written (a board list of more than a screen is no help); the same as the lines a step of the board may hold
SUMMARY_MAX = 90          # the summary a split leaves: the first action and `(+N more)`, at most this many characters
MORE_FORM = " (+{n} more)"
_RX_INLINE_NUM = re.compile(r"(?:(?<=\s)|^)\(?(\d{1,2})[.)]\s+(?=\S)")      # `1)`, `2.` or `(3)` that opens an item inside a line
_RX_WORD = re.compile(r"\w")        # an action holds at least one letter or digit: a clause of marks only is no action
_LIST_OPENERS = ".;:!?"           # what may stand before an inline `1)` that starts a list (the end of a sentence, a semicolon, a colon): after any other word it is a number in a sentence
_TRIM = " .;"                      # what ends a clause and is no part of the action's words


def _inline_items(text: str) -> list[str]:
    """`text` cut at inline numbered items when it holds two or more in a row from 1 (`Do: 1) a 2) b`), the first one at the start of the text or after the end of a sentence or a colon (a number in a sentence,
    `Pick plan 1) basic or 2) pro`, is no list): the words before the first item (when there are some), then each item, its number off. Else [text]."""
    starts, ends = _bt._merged(_bt._spans(text) + [m.span() for m in _bt._RX_CODE_SPAN.finditer(text)])
    seq: list[Any] = []
    for m in _RX_INLINE_NUM.finditer(text):
        k = bisect.bisect_right(starts, m.start()) - 1
        if k >= 0 and m.start() < ends[k]:       # inside a link, a URL or a code span
            continue
        if int(m.group(1)) != len(seq) + 1:
            continue
        before = text[:m.start()].rstrip()
        if not seq and before and before[-1] not in _LIST_OPENERS:
            continue
        seq.append(m)
    if len(seq) < 2:
        return [text]
    out = [text[:seq[0].start()]] if text[:seq[0].start()].strip() else []
    for k, m in enumerate(seq):
        out.append(text[m.end():seq[k + 1].start() if k + 1 < len(seq) else len(text)])
    return [x.strip() for x in out if x.strip()]


def _wrap(clause: str, limit: int) -> list[str]:
    """One clause as pieces of at most `limit` characters: at its last comma or colon (bullet_text._soft_units), else at spaces outside a link, a URL or a code span. Every word kept; a word longer than
    the limit stays whole on a piece of its own. Linear in the clause: one pass over its spaces, the spans looked up by bisection."""
    if len(clause) <= limit:
        return [clause]
    soft = _bt._soft_units(clause, "", limit, 40)
    if soft:
        return [u.strip() for u, _ in soft if u.strip()]
    starts, ends = _bt._merged(_bt._spans(clause) + [m.span() for m in _bt._RX_CODE_SPAN.finditer(clause)])

    def free(x: int) -> bool:        # x is no place strictly inside a link, a URL or a code span
        k = bisect.bisect_left(starts, x) - 1
        return not (k >= 0 and starts[k] < x < ends[k])

    gaps = [m.start() for m in re.finditer(r"\s+", clause) if free(m.start())]      # where a cut may fall: the start of a run of spaces outside every span
    out: list[str] = []
    pos = 0                          # the start of the piece being cut
    g = 0                            # the first gap not yet passed (the gaps only move forward)
    while len(clause) - pos > limit:
        while g < len(gaps) and gaps[g] <= pos:
            g += 1
        at, h = -1, g
        while h < len(gaps) and gaps[h] - pos <= limit:      # the last gap that leaves the piece within the limit
            at, h = gaps[h], h + 1
        if at < 0:                   # a word (or a link) longer than the limit: the piece ends at the next gap, whole
            if g >= len(gaps):
                break
            at = gaps[g]
        if piece := clause[pos:at].strip():
            out.append(piece)
        pos = at
        while pos < len(clause) and clause[pos].isspace():
            pos += 1
    rest = clause[pos:].strip()
    return [*out, rest] if rest else out


def actions(text: Any, line_max: int) -> list[str]:
    """The actions of a text read as one line: [] when it is to be left as written (under SPLIT_OVER, structured, or one action), else the actions in order, each at most `line_max`
    characters, every word of the text in them (only a closing full stop or semicolon, an inline item's number and the spaces between clauses are gone)."""
    t = _steps.clean(text)
    if len(t) <= SPLIT_OVER or len(t) > SPLIT_MAX or _sc.structured(str(text or "")) or line_max < 20:
        return []
    clauses: list[str] = []
    for part in _inline_items(t):
        for clause, _gap in _bt._clauses(part):
            c = clause.strip()
            c = c.rstrip(_TRIM).strip() or c
            if c and _RX_WORD.search(c):
                clauses.append(c)
    if len(clauses) < 2:            # one sentence is one action however long: it is never cut mid-sentence (a line over the limit is judged by the next-line rules as before)
        return []
    out: list[str] = []
    for c in clauses:
        out.extend(_wrap(c, line_max))
        if len(out) > MAX_ACTIONS:      # past the cap: left as written (cheap to say early: a long text never gets the whole of its pieces made)
            return []
    return out


def summary_of(first: str, more: int) -> str:
    """The summary: `first` cut at a word so that with ` (+N more)` it reads within SUMMARY_MAX characters (an ellipsis when cut)."""
    tail = MORE_FORM.format(n=more)
    room = SUMMARY_MAX - len(tail)
    head = _bt.cut_words(first, room) or first[:max(room - 1, 1)].rstrip() + "…"
    return head + tail


def split_step(text: Any, line_max: int) -> tuple[str, list[str]] | None:
    """A long step as (the summary, the lines of next that carry the actions, each opening with his name), None when the text is left as written (`actions`)."""
    acts = actions(text, line_max)
    if not acts:
        return None
    return summary_of(acts[0], len(acts) - 1), [_os.line_of(a) for a in acts]


def split_line(line: Any, line_max: int) -> list[str] | None:
    """One line of next that opens with his name, as one line per action (each opening with his name), None when it is left as written: it has no first line only, or holds under two actions
    (`actions`), or is no line of his."""
    raw = str(line or "")
    if "\n" in raw.strip() or not _os.is_named(raw):
        return None
    acts = actions(_steps.without_owner(raw), line_max)
    return [_os.line_of(a) for a in acts] or None
