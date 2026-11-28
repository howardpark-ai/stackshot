"""step_split.py: a long step of the owner's put into the shape the board draws, a short summary and one line per action.

The board shows what the owner does as a list: the step is a one-line summary (the tab title and the notice read it), and what he does is the lines of `next` that start with his name, drawn as a
numbered list (step_commands.py, render.step_nexts_html). A step written as one long sentence chain, several actions in one line, reads badly there. This module turns such a text into the shape
the board draws; it never refuses and never drops a word.

WHEN A TEXT IS SPLIT (`actions`). SPLIT_OVER characters, one line and not already structured (a numbered or fenced step is the writer's own shape and is kept), with at least two clauses. An action is a
clause cut at the end of a sentence or at a semicolon (bullet_text._clauses: never inside a link, a naked URL, a code span or a parenthesis, nor after an abbreviation or a number), at the
numbered items written inline (`1) … 2) …`, the numbers dropped, the list draws its own), and, for a clause still over the line limit on its own, at its last comma or colon that leaves the piece within
it (bullet_text._soft_units), else at a space. A text under SPLIT_OVER, or one action, is left as written, and so is one with a piece no cut brings within the line limit (a word, a link's words or a code span
longer than a line; a naked URL is no such piece), and one that is no step but a document: a text over SPLIT_MAX characters, or one that would
make more than MAX_ACTIONS actions, is never split (the old limits then judge it as they did before; a split of a page of text into hundreds of lines is no help to a reader and costs the item lock its time).
An inline `1)` is an item only where a list can start: at the start of the text or after the end of a sentence or a colon (`Pick plan 1) basic or 2) pro` is no list), and a clause with no letter or digit in it (a stray `;` or `.`)
is no action.

A LIST UNDER A LEAD-IN. When the words before the first inline item end with a colon (`Do these in order: 1) a 2) b 3) c. Then report back.`), the last sentence of them (the one with the colon) is ONE action and the items are
the sub-lines under it, drawn as a list inside that step (`<owner>: Do these in order:` with `  - a`, `  - b`, `  - c` indented under it); a sentence after the last item is an action of its own, at the top level, and
a sentence before the lead-in sentence stays a top-level action. Of an item that is not the last, every word stays in its sub-line; of the last, the first sentence is the item and the sentences after it are top-level. Items with
no colon lead-in (no words before them, or words that do not end with a colon) are top-level actions, one each. The summary's `(+N more)` counts top-level actions only; the cap MAX_ACTIONS counts every line made, sub-lines included.

WHAT IT MAKES (`split_step`). The summary: the first action cut at a word to fit SUMMARY_MAX, with `(+N more)` after it (nothing after it when it is the only top-level action: one lead-in with its list), so the summary says there is a list and is never the same words as the
first line (the board skips a line of his that reads as the summary). The lines: every action, each opening with his name (`<owner>: <action>`), each within the line limit, the full stop or semicolon
that ended a clause dropped and nothing else changed. Fed back, the output changes nothing (the summary and every line are under SPLIT_OVER or hold one action, and a line with sub-lines is never split again).

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
SUB = "  - "                       # how a sub-line stands under its action in a line of next: indented, so the line above keeps it (nextlines.split), a bullet, so the board draws a list


def inline_run(text: str, paren_only: bool = False) -> list[Any]:
    """The matches of the numbered items in a row from 1 that `text` writes inline (`Do: 1) a 2) b`), two or more, else []: the first one at the start of the text, after the end of a sentence or a colon, or after a lone
    dash (`- 1) a 2) b`); a number in a sentence, `Pick plan 1) basic or 2) pro`, is no list, and none inside a link, a URL or a code span is one. `paren_only`: only the `1)` form counts, not `1.` or `(1)`."""
    starts, ends = _bt._merged(_bt._spans(text) + [m.span() for m in _bt._RX_CODE_SPAN.finditer(text)])
    seq: list[Any] = []
    for m in _RX_INLINE_NUM.finditer(text):
        k = bisect.bisect_right(starts, m.start()) - 1
        if k >= 0 and m.start() < ends[k]:       # inside a link, a URL or a code span
            continue
        if int(m.group(1)) != len(seq) + 1:
            continue
        if paren_only and (m.group(0).startswith("(") or m.group(0).strip()[-1] != ")"):
            continue
        before = text[:m.start()].rstrip()
        if not seq and before and before[-1] not in _LIST_OPENERS and before.strip("-") != "":
            continue
        seq.append(m)
    return seq if len(seq) >= 2 else []


def _inline_list(text: str) -> tuple[str, list[str]]:
    """(the words before the list, the items) when `text` holds two or more inline numbered items in a row from 1 (`inline_run`): the words before the first item ("" when there are none), then each item, its number off,
    the last one with whatever follows it. Else (text, [])."""
    seq = inline_run(text)
    if not seq:
        return text, []
    items = [text[m.end():seq[k + 1].start() if k + 1 < len(seq) else len(text)].strip() for k, m in enumerate(seq)]
    lead = text[:seq[0].start()].strip()
    return ("" if lead.strip("-") == "" else lead), [x for x in items if x]


def _clause_list(part: str) -> list[str]:
    """The clauses of a text as actions: cut at sentence ends and semicolons (bullet_text._clauses), the closing full stop or semicolon off, a clause with no letter or digit in it left out."""
    out: list[str] = []
    for clause, _gap in _bt._clauses(part):
        c = clause.strip()
        c = c.rstrip(_TRIM).strip() or c
        if c and _RX_WORD.search(c):
            out.append(c)
    return out


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


Entry = tuple[str, list[str]]       # an action of the top level and the sub-lines under it ([] for a plain action)


def _entries(t: str) -> list[Entry]:
    """The clauses of a text as top-level actions, each with its sub-lines, before any is cut to the line limit: the inline items under a lead-in that ends with a colon are the sub-lines of that action (see the module
    doc), any other text is plain actions, one per clause."""
    lead, items = _inline_list(t)
    if items:
        before = _clause_list(lead)
        if before and before[-1].endswith(":"):
            subs: list[str] = []
            for x in items[:-1]:
                c = x.rstrip(_TRIM).strip() or x
                if _RX_WORD.search(c):
                    subs.append(c)
            last = _clause_list(items[-1])
            if len(subs) + bool(last) >= 2:
                return [(c, []) for c in before[:-1]] + [(before[-1], subs + last[:1])] + [(c, []) for c in last[1:]]
        return [(c, []) for part in ([lead] if lead else []) + items for c in _clause_list(part)]
    return [(c, []) for c in _clause_list(t)]


def _plan(text: Any, line_max: int) -> tuple[list[Entry], str]:
    """(the actions with their sub-lines, why none): the actions of `actions`, or [] with the reason when the text is left as written for its size (a sentence for a person: `skipped`); "" when it is short, structured or one action."""
    t = _steps.clean(text)
    raw = str(text or "")
    one_line_run = "\n" not in raw.strip() and bool(inline_run(t))      # `1) a 2) b 3) c` on one line is no numbered list of lines: it is the run to cut at its items
    if len(t) <= SPLIT_OVER or (_sc.structured(raw) and not one_line_run) or line_max < 20:
        return [], ""
    if len(t) > SPLIT_MAX:
        return [], f"the server splits a step into lines only up to {SPLIT_MAX} characters, and this one runs {len(t)}"
    entries = _entries(t)
    if len(entries) < 2 and not any(subs for _, subs in entries):            # one sentence is one action however long: it is never cut mid-sentence (a line over the limit is judged by the next-line rules as before); a lead-in with its list is a step of its own
        return [], ""
    out: list[Entry] = []
    made = 0
    for head, subs in entries:
        pieces = _wrap(head, line_max)
        out.extend((p, []) for p in pieces[:-1])
        out.append((pieces[-1], [q for s_ in subs for q in _wrap(s_, line_max)]))      # the sub-lines hang under the last piece of the lead-in, the one that ends with the colon
        made += len(pieces) + len(out[-1][1])
        if made > MAX_ACTIONS:      # past the cap: left as written (cheap to say early: a long text never gets the whole of its pieces made)
            return [], f"the server splits a step into at most {MAX_ACTIONS} lines, and this one would make more"
    if any(_bt.visible_len(x) > line_max for h, subs in out for x in (h, *subs)):      # a word, a link's words or a code span that no cut can bring within a line (a naked URL reads as nothing, so it never counts): the lines would be refused, naming a line the writer did not write
        return [], f"a word, a link or a code span in it is longer than a line of next ({line_max} characters), so the server could not cut it into lines"
    return out, ""


def _text_of(entry: Entry) -> str:
    """An action with its sub-lines as one text: the action, then each sub-line on a line of its own, indented under it."""
    return entry[0] + "".join("\n" + SUB + s for s in entry[1])


def actions(text: Any, line_max: int) -> list[str]:
    """The actions of a text read as one line: [] when it is to be left as written (under SPLIT_OVER, over SPLIT_MAX, structured, one action, more than MAX_ACTIONS lines, or with a piece that cannot be
    brought within `line_max`), else the actions in order, each at most `line_max` characters, every word of the text in them (only a closing full stop or semicolon, an inline item's number and the
    spaces between clauses are gone). An action that opens a list (a lead-in that ends with a colon, followed by inline items) comes as its words, then each item on a line of its own, indented under it (`SUB`)."""
    return [_text_of(e) for e in _plan(text, line_max)[0]]


def skipped(text: Any, line_max: int) -> str:
    """Why a text over SPLIT_OVER was left as written for its size or for a piece that cannot be cut ("" when it is split, short, structured or one action): said beside the refusal of the text."""
    return _plan(text, line_max)[1]


def summary_of(first: str, more: int) -> str:
    """The summary: `first` cut at a word so that with ` (+N more)` it reads within SUMMARY_MAX characters (an ellipsis when cut); with nothing more, `first` alone."""
    tail = MORE_FORM.format(n=more) if more else ""
    room = SUMMARY_MAX - len(tail)
    head = _bt.cut_words(first, room) or first[:max(room - 1, 1)].rstrip() + "…"
    return head + tail


def _line(entry: Entry) -> str:
    """The line of next for an action: his name and the action, the sub-lines indented under it."""
    return _os.line_of(entry[0]) + "".join("\n" + SUB + s for s in entry[1])


def split_step(text: Any, line_max: int) -> tuple[str, list[str]] | None:
    """A long step as (the summary, the lines of next that carry the actions, each opening with his name; an action with a list is one line with its sub-lines indented under it), None when the text is left as written (`actions`)."""
    acts = _plan(text, line_max)[0]
    if not acts:
        return None
    return summary_of(acts[0][0], len(acts) - 1), [_line(a) for a in acts]


def split_line(line: Any, line_max: int) -> list[str] | None:
    """One line of next that opens with his name, as one line per action (each opening with his name, a list's items indented under its lead-in), None when it is left as written: it has no first line only, or holds under two
    actions (`actions`), or is no line of his. A line with sub-lines under it is the writer's own shape and is never split."""
    raw = str(line or "")
    if "\n" in raw.strip() or not _os.is_named(raw):
        return None
    acts = _plan(_steps.without_owner(raw), line_max)[0]
    return [_line(a) for a in acts] or None
