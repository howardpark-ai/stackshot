"""step_howto.py — which bullets of an item's description say HOW to do the owner's step, for drawing under it. A pure function: it reads a description and a step and returns text; it
stores nothing and no write path calls it.

A how-to bullet is a line that tells the person to DO something: it opens with an action verb (open, click, go to, visit, sign in, download, upload, attach, copy, paste, select, choose, press, tap,
run, check, enable, install, share, send, fill, review ...), with or without a link, or it is a click path (two or more arrows between short names). A Korean line counts with an action verb and a request or plain-form ending. It is never a label (`Goal: ...`), a date, a
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
_LABEL = re.compile(r"^[^:\uff1a\u2192>]{1,24}[:\uff1a](?:\s|$)")                              # `Goal: ...`, `Problem: ...`: a label, not an action
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


# Korean. An instruction holds an action verb (open, click, go to, download, upload, attach, copy, select, confirm, submit, apply, issue, print ...) and ends in a request or a plain form (the polite imperative, the polite request, the formal statement, the plain present). The label, date, warning, negation, past-event and fact shapes are refused as in English. Written as escapes: the repository holds no Hangul.
_KO_ACTION = re.compile(r"\uc5f4[\uace0\uc5b4\uae30\uba74]|\uc5f0\ub2e4|\ud074\ub9ad|\ub204\ub974|\ub20c\ub7ec|\ub204\ub978|\uc774\ub3d9|\uc811\uc18d|\ub85c\uadf8\uc778|\ub2e4\uc6b4\ub85c\ub4dc|\ub0b4\ub824\s?\ubc1b|\uc5c5\ub85c\ub4dc|\uc62c\ub9ac|\uc62c\ub824|\uc62c\ub9b0|\ucca8\ubd80|\ubcf5\uc0ac|\ubd99\uc5ec|\ubd99\uc774|\ubd99\uc778|\uc120\ud0dd|\uace0\ub974|\uace0\ub978|\ud655\uc778|\uc81c\ucd9c|\uc2e0\uccad|\ubc1c\uae09|\ucd9c\ub825|\uc785\ub825|\uc800\uc7a5|\uac80\uc0c9|"
                        r"\ucc3e\uc544|\ucc3e\ub294|\ub4e4\uc5b4\uac00|\ub4e4\uc5b4\uac04|\ubc29\ubb38|\uc2e4\ud589|\uc124\uce58|\uacf5\uc720|\ubcf4\ub0b4|\ubcf4\ub0b8|\uc804\uc1a1|\uc791\uc131|\uc11c\uba85|\uacb0\uc81c|\ub0a9\ubd80|\uc778\uc1c4|\ucea1\ucc98|\uc2a4\uce94|\ucd94\uac00|\uccb4\ud06c|\ub0b8\ub2e4|\ub0b4\uc138\uc694|\ub0b4 ?\uc8fc|\ubcf8\ub2e4|\ubcf4\uc138\uc694|\ubd10 ?\uc8fc|\ub123")
_KO_END = re.compile(r"(?:\uc138\uc694|\uc2ed\uc2dc\uc624|\uc2dc\uc624|\ud569\ub2c8\ub2e4|\ud569\uc2dc\ub2e4|\ud558\uc790|\ud574\ub77c|\ud558\ub77c|\ud574\uc694|\uc8fc\uc138\uc694|\uc8fc\uc2ed\uc2dc\uc624)$")
_KO_PASSIVE = re.compile(r"\ub41c\ub2e4|\ub429\ub2c8\ub2e4|\ub418\uc5c8|\ub410|\ub3fc\uc694|\ub418\uc5b4\uc694")
_KO_DATE = re.compile(r"\d{1,2}\s?\uc6d4|\d{1,2}\s?\uc77c|\d{4}\s?[-./]\s?\d{1,2}|\d{1,2}:\d{2}|[\uc6d4\ud654\uc218\ubaa9\uae08\ud1a0\uc77c]\uc694\uc77c|\uc624\ub298|\ub0b4\uc77c|\uc5b4\uc81c|\ubaa8\ub808|\uc774\ubc88\s?\uc8fc|\ub2e4\uc74c\s?\uc8fc|\uc9c0\ub09c\s?\uc8fc")
_KO_WARNING = re.compile(r"\uc8fc\uc758|\uc720\uc758|\uc870\uc2ec|\uacbd\uace0|\ucc38\uace0|\uc911\uc694|\uc808\ub300")
_KO_NEGATION = re.compile(r"\ud558\uc9c0\s?(?:\ub9c8|\ub9d0)|\ub9d0\s?\uac83|\ub9c8\uc138\uc694|\ub9c8\uc2ed\uc2dc\uc624|\uc9c0\s?\uc54a|\uc9c0\s?\ubabb|\ubabb\s?(?:\ud55c|\ud569|\ud574)|\uc548\s?(?:\ub41c|\ub3fc|\ub429)|\ud558\uba74\s?\uc548|\uae08\uc9c0|\ubd88\uac00|\ud544\uc694\s?\uc5c6|\uc5c6(?:\ub2e4|\uc74c|\uc2b5\ub2c8\ub2e4|\uc5b4\uc694)|\uc544\ub2c8(?:\ub2e4|\uc5d0\uc694|\ubbc0\ub85c)")
_KO_PAST = re.compile(r"[\ud588\ub410\uc600\uc5c8\uc558\uac14\uc654\ubd24\ub0c8\uc92c\ub838\ub800\uc37c\ucf30\ub790\uacbc](?:\ub2e4|\uc2b5\ub2c8\ub2e4|\uc5b4\uc694|\uc544\uc694|\uc74c|\uc73c\uba70|\uace0|\ub294\ub370|\uc73c\ub098|\uc9c0\ub9cc)|(?:\ub428|\ud568|\uc784)[.)\s]*$")
_KO_FACT = re.compile(r"\uc785\ub2c8\ub2e4|\uc774\ub2e4|\uc774\uc5d0\uc694|\uc608\uc694|\uc774\ubbc0\ub85c|\ub54c\ubb38|\uc608\uc815|\uc608\uc0c1|\uc774\ub77c\uace0|\ub77c\uace0\s?\ud55c\ub2e4|[\uc774\uac00]\s?\uc788(?:\ub2e4|\uc2b5\ub2c8\ub2e4|\uc5b4\uc694)|\uc788\uc74c")
_KO_SUBJECT = re.compile(r"^\S*[\uc740\ub294\uc774\uac00]\s+\S")                          # a first word that is a subject or topic: the first word is a subject or topic, so the line tells what someone does; an instruction has no subject
_HANGUL = re.compile(r"[\uac00-\ud7a3]")
_TRAIL = re.compile(r"(?:\s*\([^()]*\))*[\s.!。'\"”’)]*$")      # what may follow the last verb: a note in parentheses, a full stop, a quote


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


def _plain_form(word: str) -> bool:
    """A plain-form verb ending: the letter da after a syllable that ends in the sound n."""
    return len(word) >= 2 and word[-1] == "\ub2e4" and "\uac00" <= word[-2] <= "\ud7a3" and (ord(word[-2]) - 0xAC00) % 28 == 4


def _korean_action(text: str) -> bool:
    """A Korean line that tells him to do something: no subject word, an action verb in it, and a request or plain-form ending on its last word."""
    if text.rstrip().endswith("?") or _KO_SUBJECT.match(text) or _KO_PASSIVE.search(text) or not _KO_ACTION.search(text):
        return False
    words = _TRAIL.sub("", text).split()
    return bool(words) and bool(_KO_END.search(words[-1]) or _plain_form(words[-1]))


def is_howto(text: str) -> bool:
    """Is this one bullet's text (no dash) a how-to bullet? An instruction or a click path, and none of the shapes that tell something else. What the line quotes, a code span and a link's address
    are names, not the line's own words, so the date, warning, negation and fact words are looked for outside them."""
    own = _QUOTED.sub(" ", text)
    korean = bool(_HANGUL.search(own))
    if _LABEL.match(own) or _PAST.match(text) or any(r.search(own) for r in (_DATE, _WARNING, _NEGATION, _FACT)):
        return False
    if korean and any(r.search(own) for r in (_KO_DATE, _KO_WARNING, _KO_NEGATION, _KO_PAST, _KO_FACT)):
        return False
    if _COND.search(text) and not _IMPERATIVE.match(text):
        return False
    return _path(text) or _action(text) or (korean and _korean_action(own))


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
