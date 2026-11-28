"""step_howto.py — which bullets of an item's description say HOW to do the owner's step, for drawing under it. A pure function: it reads a description and a step and returns text; it
stores nothing and no write path calls it.

A how-to bullet is a line that tells the person to DO something: it opens with an action verb (open, click, go to, visit, sign in, download, upload, attach, copy, paste, select, choose, press, tap,
run, check, enable, install, share, send, fill, review ...), with or without a link, or it is a click path (two or more arrows between short names). It is never a label (`Goal: ...`), a date, a
warning, a negation, a past event or a fact (is, shows, removes ...), and a bullet the step already says is left out. When in doubt it is not a how-to bullet.

  howto_bullets   (description, step) -> the how-to bullets, in order, as text without the dash; [] with no open step
"""
from __future__ import annotations

import re
from typing import Any

MAX_BULLETS = 5
_BULLET = re.compile(r"^[ \t]*(?:[-*\u2022]|\d{1,3}[.)])[ \t]+(\S.*)$")
_FENCE = re.compile(r"^[ \t]*(?:```|~~~)")
_SEP = re.compile(r"\s*(?:\u2192|->|\u203a|\u00bb)\s*|\s+>\s+")                    # a click path's separators: an arrow, a chevron, a spaced >
_LETTER = re.compile(r"[^\W\d_]|^\s*(?:19|20)\d\d\s*$")        # a name has a letter; a year is a name too ("... -> 2025")
_LABEL = re.compile(r"^[^:\u2192>]{1,24}:(?:\s|$)")                              # `Goal: ...`, `Problem: ...`: a label, not an action
_DATE = re.compile(r"(?i)\d{4}-\d{2}-\d{2}|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? \d{1,2}\b|\b(?:mon|tues?|wed(?:nes)?|thu(?:rs)?|fri|sat(?:ur)?|sun)(?:day)?\b")
_WARNING = re.compile(r"(?i)\b(?:warning|caution|careful|beware|danger|note|important|avoid|mind)\b")
_NEGATION = re.compile(r"(?i)\b(?:not|no|never|none|nothing|nor|cannot|without)\b|n't\b")
_FACT = re.compile(r"(?i)\b(?:is|are|was|were|be|been|being|has|have|had|did|does|shows?|showed|removes?|removed|returns|returned|means|gives?|because|since|already|which|that)\b")
_COND = re.compile(r"(?i)\b(?:when|if)\b")                                    # a fact word unless the line opens with an imperative verb ("Upload [the drive](...) when ready")
_LEAD = r"(?:(?:please|then|first|next|finally|also|now)\b[ ,]*|\(?optional\)?[:, ]*)*"      # words that may come before the action verb
_VERBS = (r"open|click|go|head|navigate|visit|download|upload|attach|copy|paste|select|choose|pick|press|tap|run|check|enable|disable|install|share|send|fill|review|type|enter|scroll|search|find|"
          r"look|submit|save|export|import|add|create|confirm|verify|request|apply|print|forward|switch|turn|toggle|drag|hover|follow|call|email|read|sign up|"
          r"(?:log|sign) ?in(?:to)?(?= (?:to|at|with|on|using|via|as|the|your|https?)|\W*$)")
_IMPERATIVE = re.compile(r"(?i)^" + _LEAD + r"(?:" + _VERBS + r")\b(?P<rest>.*)$")
_NOUNY = re.compile(r"(?i)^(?:items?|questions?|issues?|tasks?|tickets?|steps?|status|results?|rate|count|queue|history|summary|requests?|pending|needed|required|failed|passed|complete|completed|done|ok|okay|expected)\b")
_QUOTED = re.compile(r"\"[^\"]*\"|\u201c[^\u201d]*\u201d|`[^`]*`|\]\(\s*https?://[^)]*\)|https?://\S+")
_PAST = re.compile(r"(?i)^(?:\w+ed|went|ran|sent|got|made|took|did|found|wrote|built|came|saw|gave|left)\b")   # a line that opens with a past-tense verb tells what happened


def _norm(text: Any) -> str:
    return " ".join(str(text or "").lower().split())


def _path(text: str) -> bool:
    """A click path: two or more separators, so three or more parts, each a short name that holds a letter or is a year ("Refund -> 360 -> paid" is not one)."""
    parts = _SEP.split(text)
    return len(parts) >= 3 and all(_LETTER.search(p) and len(p) <= 80 for p in parts)


def _action(text: str) -> bool:
    """The line opens with an action verb and says more than the verb ("Open" alone, "Open questions", "Upload failed" are not instructions)."""
    m = _IMPERATIVE.match(text)
    if not m:
        return False
    rest = m.group("rest").strip()
    return bool(rest) and not _NOUNY.match(rest)


def is_howto(text: str) -> bool:
    """Is this one bullet's text (no dash) a how-to bullet? An instruction or a click path, and none of the shapes that tell something else. What the line quotes, a code span and a link's address
    are names, not the line's own words, so the date, warning, negation and fact words are looked for outside them."""
    own = _QUOTED.sub(" ", text)
    if _LABEL.match(own) or _PAST.match(text) or any(r.search(own) for r in (_DATE, _WARNING, _NEGATION, _FACT)):
        return False
    if _COND.search(text) and not _IMPERATIVE.match(text):
        return False
    return _path(text) or _action(text)


def howto_bullets(description: Any, step: Any) -> list[str]:
    """The how-to bullets of `description`, in order, for an open step of the owner's (`step`, its text); [] when `step` is empty (the step ended: nothing is drawn). A bullet whose
    words the step already holds is left out. At most MAX_BULLETS."""
    if not str(step or "").strip():
        return []
    said, out, fenced = _norm(step), [], False
    for line in str(description or "").splitlines():
        if _FENCE.match(line):
            fenced = not fenced
            continue
        m = None if fenced else _BULLET.match(line)
        if not m:
            continue
        text = m.group(1).strip()
        if is_howto(text) and _norm(text) not in said and text not in out:
            out.append(text)
            if len(out) >= MAX_BULLETS:
                break
    return out
