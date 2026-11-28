"""step_howto.py — which bullets of an item's description say HOW to do the owner's step, for drawing under it. A pure function: it reads a description and a step and returns text; it
stores nothing and no write path calls it.

A how-to bullet is only (a) a click path: two or more arrows (`->` or the arrow sign), or (b) a line that opens with attach or upload and holds a link. It is never a label (`Goal: ...`), a
date, a warning, a negation, a past event or a fact (is, shows, removes ...), and a bullet the step already says is left out. When in doubt it is not a how-to bullet.

  howto_bullets   (description, step) -> the how-to bullets, in order, as text without the dash; [] with no open step
"""
from __future__ import annotations

import re
from typing import Any

MAX_BULLETS = 5
_BULLET = re.compile(r"^[ \t]*-[ \t]+(\S.*)$")
_FENCE = re.compile(r"^[ \t]*(?:```|~~~)")
_ARROW = re.compile(r"→|->")
_LINK = re.compile(r"https?://\S|\]\(\s*https?://")
_ATTACH = re.compile(r"(?i)^(?:attach|upload)\b")
_LABEL = re.compile(r"^[^:→>]{1,24}:(?:\s|$)")                              # `Goal: ...`, `Problem: ...`: a label, not an action
_DATE = re.compile(r"(?i)\d{4}-\d{2}-\d{2}|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? \d{1,2}\b|\b(?:mon|tues?|wed(?:nes)?|thu(?:rs)?|fri|sat(?:ur)?|sun)(?:day)?\b")
_WARNING = re.compile(r"(?i)\b(?:warning|caution|careful|beware|danger|note|important|avoid|mind)\b")
_NEGATION = re.compile(r"(?i)\b(?:not|no|never|none|nothing|nor|cannot|without)\b|n't\b")
_FACT = re.compile(r"(?i)\b(?:is|are|was|were|be|been|being|has|have|had|did|does|shows?|showed|removes?|removed|returns?|means|gives?|because|since|already|when|if|which|that)\b")
_PAST = re.compile(r"(?i)^\w+ed\b")                                         # a line that opens with a past-tense verb tells what happened


def _norm(text: Any) -> str:
    return " ".join(str(text or "").lower().split())


def is_howto(text: str) -> bool:
    """Is this one bullet's text (no dash) a how-to bullet? The two shapes above, and none of the shapes that tell something else."""
    if _LABEL.match(text) or _DATE.search(text) or _WARNING.search(text) or _NEGATION.search(text) or _FACT.search(text) or _PAST.match(text):
        return False
    if len(_ARROW.findall(text)) >= 2:
        return True
    return bool(_ATTACH.match(text) and _LINK.search(text))


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
    return out[:MAX_BULLETS]
