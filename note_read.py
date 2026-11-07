"""note_read.py — what the owner's note on his step says, read by the server so it can apply it (a pure module, no config and no store).

The owner's Send box on a step takes a note. Two kinds of note say what the owner did or will do, and the server applies them itself instead of leaving the session that takes the item to
read them:

  done   the whole note says he did the step ("ran it", "done", "I did it"; "I ran it and will check tomorrow" too, which ticks and holds nothing): his step is ticked as an empty Send ticks it. A
         bare imperative ("run it") is no `done`. A note that goes on to say more ("ran it but it says forbidden"), asks something ("did it work?") or says he did not ("didn't run it") is no `done`:
         it goes to the session to judge, as before.
  until  the note is a first-person future with a later time ("I'll do it tomorrow evening", "I will look at it next week", "I'm going to do it in 3 days", "I'll do it on Friday"): the item goes on hold
         until then, with his words behind the wake (the hold and wake machinery is the answer path's own: a park). Anything else is no `until`: a note that asks something, speaks of a past time, is
         negated ("not tomorrow", "can't do it tomorrow"), is a deadline ("by tomorrow evening", "need this by next week"), says "go ahead", is conditional ("if", "unless", "maybe"), does the step now ("I'll do it now, then check tomorrow"), is no action of the step ("I'll let you know tomorrow", "I'll be traveling tomorrow") or names no time cue.

`read(text, now, parse_date)` answers {"done": bool, "until": ""}; `until` is YYYY-MM-DDTHH:MM (a day alone gets 09:00, a part of the day its hour). `parse_date(text, today)` is
watchers.parse_date, passed in so this module needs no config. In doubt nothing is found: a note the server does not read is a note the session judges, which is today's behaviour.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Callable

_DONE_VERBS = r"(?:ran|did|done|finished|completed|executed|applied|deleted|merged|pasted|posted|sent)"      # no bare "run": "run it" asks for the step, it does not say it was done
_DONE_RX = re.compile(
    rf"^\W*(?:(?:ok(?:ay)?|yes|yep|yeah)\W+)?(?:(?:i(?:'ve|’ve| have| just)?\s+)?{_DONE_VERBS}|i(?:'ve|’ve| have)\s+run)\b"
    r"(?:\s+(?:it|them|that|this|both|those|these|all(?:\s+of\s+(?:it|them))?))?"
    r"(?:\s+(?:already|now|just now|earlier|today|successfully|a (?:minute|moment) ago))*"
    r"(?:\s*(?:,|and|then|;)\s*(?:i\s*)?(?:will|'ll|’ll|am going to|'m going to|’m going to)\s+(?:check|look|verify|see|confirm|report|tell you|let you know|follow up|test)\b[^?!.]*)?\W*$", re.I)      # "ran it and will check tomorrow": done, and no hold
_DONE_ITS_RX = re.compile(r"^\W*(?:it(?:'s|’s| is)|that(?:'s|’s| is)|all)\s+(?:all\s+)?done\W*$", re.I)
_CUE_RX = re.compile(
    r"\b(?:tomorrow|tonight|next week|this (?:evening|afternoon|morning|weekend)|next (?:mon|tues|wednes|thurs|fri|satur|sun)day|on (?:mon|tues|wednes|thurs|fri|satur|sun)day"
    r"|in\s+\d{1,3}\s+(?:days?|weeks?|hours?)|\d{4}-\d{2}-\d{2})\b", re.I)
_FUTURE_RX = re.compile(      # a first-person future at the start of the note: "I will …", "I'll …", "I'm going to …", "we will …"
    r"^\W*(?:(?:ok(?:ay)?|yes|yep|yeah|sure|thanks?|thank you)\W+)*(?:i|we)(?:\s+will|\s*'ll|\s*’ll|\s+am\s+going\s+to|\s*'m\s+going\s+to|\s*’m\s+going\s+to|\s+plan\s+to|\s+am\s+planning\s+to)\b", re.I)
_NEG_RX = re.compile(r"\b(?:not|never|no|can['’]?t|cannot|can\s+not|won['’]?t|don['’]?t|doesn['’]?t|didn['’]?t|isn['’]?t|unable|without|except|instead)\b|n['’]t\b", re.I)
_DEADLINE_RX = re.compile(r"\b(?:by|before|due|deadline|within|no later than|at the latest|need(?:s|ed)?\s+(?:this|it|that)|go ahead|proceed|carry on)\b", re.I)
_NOW_RX = re.compile(r"\b(?:now|today|right away|right now|straight away|immediately|this (?:minute|moment)|asap)\b", re.I)      # the action is for now, the later time is only a follow-up
_NONACT_RX = re.compile(r"\b(?:let (?:you|us|me) know|get back to you|update you|tell you|report back|travel\w*|out of (?:the )?office|ooo|vacation|holiday|on leave|away|sick|unavailable|offline)\b", re.I)      # a later time that is not the step being done
_COND_RX = re.compile(r"\b(?:if|unless|maybe|perhaps|might|depends?|assuming|provided)\b", re.I)
_PAST_RX = re.compile(r"\b(?:yesterday|last night|last week|earlier|already|ago)\b", re.I)
_PARTS = (("morning", "09:00"), ("afternoon", "14:00"), ("evening", "19:00"), ("night", "21:00"), ("noon", "12:00"))
_TEXT_MAX = 240          # a longer note is a message to read, not a one-line statement of when


def is_done(text: str) -> bool:
    """The whole note says he did the step."""
    t = " ".join(str(text or "").split())
    return bool(t) and len(t) <= 80 and "?" not in t and bool(_DONE_RX.match(t) or _DONE_ITS_RX.match(t))


def _part(low: str) -> str:
    for word, hhmm in _PARTS:
        if re.search(rf"\b{word}\b", low):
            return hhmm
    return ""


def until(text: str, now: dt.datetime, parse_date: Callable[[str, dt.date], str]) -> str:
    """The later time the note names, "" when it is not a first-person future with one: it names none, asks something, speaks of the past, is negated, is a deadline, says "go ahead" or is conditional."""
    t = " ".join(str(text or "").split())
    low = t.lower()
    if not t or len(t) > _TEXT_MAX or "?" in t or _PAST_RX.search(t) or is_done(t) or not _CUE_RX.search(t):
        return ""
    if not _FUTURE_RX.search(t) or _NEG_RX.search(t) or _DEADLINE_RX.search(t) or _COND_RX.search(t) or _NOW_RX.search(t) or _NONACT_RX.search(t):
        return ""
    stamp = lambda d: d.strftime("%Y-%m-%dT%H:%M")
    if m := re.search(r"\bin\s+(\d{1,3})\s+hours?\b", low):
        return stamp(now + dt.timedelta(hours=int(m[1])))
    if re.search(r"\btonight\b|\bthis (?:evening|afternoon)\b", low):      # today at the part's hour, while that is still ahead
        hh = "21:00" if "tonight" in low else _part(low)
        cand = dt.datetime.combine(now.date(), dt.time.fromisoformat(hh), tzinfo=now.tzinfo)
        return stamp(cand) if cand > now else ""
    day = parse_date(t, now.date())
    if not day:
        return ""
    return f"{day}T{_part(low) or '09:00'}"


def read(text: str, now: dt.datetime, parse_date: Callable[[str, dt.date], str]) -> dict[str, Any]:
    """What the note says: {"done": it says he did the step, "until": the later time it names or ""}; never both."""
    if is_done(text):
        return {"done": True, "until": ""}
    return {"done": False, "until": until(text, now, parse_date)}
