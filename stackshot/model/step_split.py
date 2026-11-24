"""step_split.py: a long step of the owner's put into the shape the board draws, a short summary and one line per action.

The board shows what the owner does as a list: the step is a one-line summary (the tab title and the notice read it), and what he does is the lines of `next` that start with his name, drawn as a
numbered list (step_commands.py, render.step_nexts_html). A step written as one long sentence chain, several actions in one line, reads badly there. This module turns such a text into the shape
the board draws; it never refuses and never drops a word.

WHEN A TEXT IS SPLIT (`actions`). SPLIT_OVER characters, one line and not already structured (a numbered or fenced step is the writer's own shape and is kept), with at least two clauses. An action is a
clause cut at the end of a sentence or at a semicolon (bullet_text._clauses: never inside a link, a naked URL, a code span or a parenthesis, nor after an abbreviation or a number), at the
numbered items written inline (`1) … 2) …`, the numbers dropped, the list draws its own), and, for a clause still over the line limit on its own, at its last comma or colon that leaves the piece within
it (bullet_text._soft_units), else at a space. A text under SPLIT_OVER, or one action, is left as written.

WHAT IT MAKES (`split_step`). The summary: the first action cut at a word to fit SUMMARY_MAX, with `(+N more)` after it, so the summary says there is a list and is never the same words as the
first line (the board skips a line of his that reads as the summary). The lines: every action, each opening with his name (`<owner>: <action>`), each within the line limit, the full stop or semicolon
that ended a clause dropped and nothing else changed. Fed back, the output changes nothing (the summary and every line are under SPLIT_OVER or hold one action).

`split_line` does the same for one long line of next that opens with his name: the lines, one per action, with no summary (the item's step or ask is the summary).

Pure functions of a text and the owner's name: no store, no config (the line limit is the caller's)."""
from __future__ import annotations

import re
from typing import Any

from stackshot.model import bullet_text as _bt
from stackshot.model import owner_steps as _os
from stackshot.model import step_commands as _sc
from stackshot.model import steps as _steps

SPLIT_OVER = 110          # a one-line step or line of his longer than this, with two or more actions, is split
SUMMARY_MAX = 90          # the summary a split leaves: the first action and `(+N more)`, at most this many characters
MORE_FORM = " (+{n} more)"
_RX_INLINE_NUM = re.compile(r"(?:(?<=\s)|^)\(?(\d{1,2})[.)]\s+(?=\S)")      # `1)`, `2.` or `(3)` that opens an item inside a line
_TRIM = " .;"                      # what ends a clause and is no part of the action's words


def _inline_items(text: str) -> list[str]:
    """`text` cut at inline numbered items when it holds two or more in a row from 1 (`Do: 1) a 2) b`): the words before the first item (when there are some), then each item, its number off. Else [text]."""
    spans = _bt._merged(_bt._spans(text) + [m.span() for m in _bt._RX_CODE_SPAN.finditer(text)])
    starts, ends = spans
    marks = [m for m in _RX_INLINE_NUM.finditer(text) if not any(a <= m.start() < b for a, b in zip(starts, ends))]
    seq: list[Any] = []
    for m in marks:
        if int(m.group(1)) == len(seq) + 1:
            seq.append(m)
    if len(seq) < 2:
        return [text]
    out = [text[:seq[0].start()]] if text[:seq[0].start()].strip() else []
    for k, m in enumerate(seq):
        out.append(text[m.end():seq[k + 1].start() if k + 1 < len(seq) else len(text)])
    return [x.strip() for x in out if x.strip()]


def _wrap(clause: str, limit: int) -> list[str]:
    """One clause as pieces of at most `limit` characters: at its last comma or colon (bullet_text._soft_units), else at spaces outside a link, a URL or a code span. Every word kept; a word longer than
    the limit stays whole on a piece of its own."""
    if len(clause) <= limit:
        return [clause]
    soft = _bt._soft_units(clause, "", limit, 40)
    if soft:
        return [u.strip() for u, _ in soft if u.strip()]
    starts, ends = _bt._merged(_bt._spans(clause) + [m.span() for m in _bt._RX_CODE_SPAN.finditer(clause)])
    out: list[str] = []
    rest = clause
    while len(rest) > limit:
        at = -1
        for m in re.finditer(r"\s+", rest[:limit + 1]):
            abs_pos = len(clause) - len(rest) + m.start()
            if not any(a < abs_pos < b for a, b in zip(starts, ends)):
                at = m.start()
        if at <= 0:
            m = re.search(r"\s+", rest)
            if m is None:
                break
            at = m.start()
        out.append(rest[:at].strip())
        rest = rest[at:].strip()
    return [*out, rest] if rest else out


def actions(text: Any, line_max: int) -> list[str]:
    """The actions of a text read as one line: [] when it is to be left as written (under SPLIT_OVER, structured, or one action), else the actions in order, each at most `line_max`
    characters, every word of the text in them (only a closing full stop or semicolon, an inline item's number and the spaces between clauses are gone)."""
    t = _steps.clean(text)
    if len(t) <= SPLIT_OVER or _sc.structured(str(text or "")) or line_max < 20:
        return []
    clauses: list[str] = []
    for part in _inline_items(t):
        for clause, _gap in _bt._clauses(part):
            c = clause.strip()
            c = c.rstrip(_TRIM).strip() or c
            if c:
                clauses.append(c)
    if len(clauses) < 2:            # one sentence is one action however long: it is never cut mid-sentence (a line over the limit is judged by the next-line rules as before)
        return []
    out: list[str] = []
    for c in clauses:
        out.extend(_wrap(c, line_max))
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
