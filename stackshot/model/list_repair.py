"""list_repair.py: the two repairs the server makes to a messy list a writer put in a description or an outcome text, instead of refusing it. Pure, stdlib and step_split only; no state.

  repair   a text with (1) a run of numbered items written on one bullet line (`- Do: 1) a 2) b 3) c`, the dash before `1)` too) put on lines of their own, and (2) a doubled bullet mark (`- - x`) made one (`- x`).

Nothing else is touched: no line is re-nested, reordered or reworded, a numbered run keeps its numbers, and a text that holds neither shape comes back as the same string. A fenced block and a `>` quote line are never read.
A run is read only where a list can start (`step_split.inline_run`: after the start of the line, a colon, the end of a sentence or a lone dash; a number in a sentence is no list), and only in the `1)` form. A split that
would put the text over `max_lines` lines is not made (the doubled mark is still dropped): the line cap is judged on what the writer sent, never made worse by the repair."""
from __future__ import annotations

import re

from stackshot.model import bullet_text as _bt
from stackshot.model import step_split as _ss

_RX_DOUBLED = re.compile(r"^([ \t]*)-[ \t]+-[ \t]+(?=\S)")      # `- - x`: a bullet mark and a second one with text after it (`- - -` alone is a rule, not this)
_RX_BULLET_LINE = re.compile(r"^([ \t]*-[ \t]+)(\S.*)$")


def _undoubled(line: str) -> str:
    while (m := _RX_DOUBLED.match(line)) and line[m.end():].strip("- \t"):
        line = m.group(1) + "- " + line[m.end():]
    return line


def _split(line: str) -> list[str]:
    """One bullet line as its lines when it holds a numbered run (the words before the run, then each item with its number, each as a bullet at the line's own indent), else [line]."""
    m = _RX_BULLET_LINE.match(line)
    if not m:
        return [line]
    prefix, body = m.group(1), m.group(2)
    run = _ss.inline_run(body, paren_only=True)
    if not run:
        return [line]
    cuts = [r.start() for r in run] + [len(body)]
    items = [body[a:b].strip() for a, b in zip(cuts, cuts[1:])]
    lead = body[:cuts[0]].strip()
    if lead.strip("-") == "":
        lead = ""
    if any(len(i) <= len(f"{k}) ") for k, i in enumerate(items, 1)):      # an item with no words after its number: not a list the server can read
        return [line]
    return ([prefix + lead] if lead else []) + [prefix + i for i in items]


def repair(text: str, max_lines: int) -> tuple[str, int, int]:
    """(the text, how many doubled marks were dropped, how many numbered runs were put on lines of their own); the same text and (0, 0) when it holds neither."""
    lines = text.split("\n")
    skip = _bt._closed_fences(lines)
    out: list[list[str]] = []
    doubled = runs = 0
    for k, ln in enumerate(lines):
        if k in skip or _bt._RX_QUOTE.match(ln):
            out.append([ln])
            continue
        one = _undoubled(ln)
        doubled += one != ln
        parts = _split(one)
        runs += len(parts) > 1
        out.append(parts)
    made = sum(len(p) for p in out)
    if runs and made > max_lines:      # the split would pass the line cap: only the doubled marks are repaired
        out, runs = [[_undoubled(ln)] if k not in skip and not _bt._RX_QUOTE.match(ln) else [ln] for k, ln in enumerate(lines)], 0
    if not (doubled or runs):
        return text, 0, 0
    return "\n".join(x for p in out for x in p), doubled, runs
