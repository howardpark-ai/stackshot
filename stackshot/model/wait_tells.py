"""wait_tells.py: the words of two tells a write that sets a wait gets, when the wait is on something the writer can settle now.

A wait is for what cannot be had now: an outside party, a vendor, a date, or a park the user asked for. Two kinds of wait name something that can:

  own read     a wait on stackshot's own count, dry run or watch (`wait_basis="the dry-run count can be read <day>"`): the writing session reads that count, or stages that run, itself
  front answer a wait on a front agent's answer, set by a back or builder session: a call that is not the user's is the writer's to decide, and one that is the user's goes to the user as options

Pure text functions, no server import. `service/update.py` (`_wait_tells`) reads the roles and the items and puts each answer on the write's reply as a note, never a refusal."""
from __future__ import annotations

import re
from typing import Any, Iterable

# What a wait on stackshot's own count, dry run or watch reads like: the dry run, the dry-run / watch / server's count, the sent-mail watch, a count the server keeps, the watch's result.
# A bare "count", a bare "watch" or a soak window is no match: those are as often an outside party's (a vote count, a word count) or a window the work itself needs.
OWN_READ = re.compile(r"\bdry[- ]?runs?\b|\b(?:stackshot'?s?|server'?s?|own|watch(?:es)?|dry[- ]?run)\s+(?:own\s+)?counts?\b|\bcounts?\s+(?:the\s+)?(?:server|stackshot)\s+keeps\b"
                      r"|\bsent[- ]mail\s+watch\b|\b(?:stackshot'?s?|the)\s+(?:own\s+)?watch\s+(?:pass|reads?|shows?|result|output)\b", re.I)
# a word that puts the reason's count or dry run with someone else (their site, a vendor's run, an auditor's vote count): the wait is on that party, and stays
OUTSIDE = re.compile(r"\b(?:vendor|auditor|partner|customer|supplier|translator|contractor|their|outside|external)", re.I)
# a front agent is the one to answer: it must be named in the clause a waiting lead opens, or be the subject of an answering verb, or an answer of it be waited for
_ANS = r"(?:answers?|repl(?:y|ies)|decisions?|verdicts?|calls?|go-ahead|sign[- ]?off|responses?|word)"
_NAME = r"(?P<name>[\w-]+)"
_WAIT_ON = re.compile(rf"\b(?:wait(?:s|ing|ed)?\s+(?:on|for)|pending|blocked\s+(?:on|by))\s+{_NAME}(?:['\u2019]s)?(?P<rest>[^.;,\n]*)", re.I)
_WAIT_UNTIL = re.compile(rf"\b(?:until|once|after|when)\s+{_NAME}\s+(?:answers?|repl(?:y|ies|ied)|decides?|decided|responds?|responded|confirms?|confirmed|signs\s+off|says)\b", re.I)
_ASKED = re.compile(rf"\bask(?:s|ed|ing)?\s+{_NAME}\s+(?:for|whether|if|which|what|to\s+(?:decide|answer|confirm|pick|choose))\b", re.I)
_ANSWER_OF = re.compile(rf"{_NAME}['\u2019]s\s+{_ANS}\b", re.I)
_ANSWER_WORD = re.compile(rf"\b{_ANS}\b|\b(?:decide|reply|respond|confirm)", re.I)
_TOLD = re.compile(r"\s*to\s+(?:be\s+)?(?:told|notified|informed|hear)\b", re.I)
_DATE_TAIL = re.compile(r"\s*(?:on|by|until|due)\s+\d", re.I)
_WAIT = re.compile(r"\b(?:wait(?:s|ing|ed)?|until|pending|blocked|due|expect(?:ed|s)?)\b", re.I)

OWN_READ_NOTE = ("\n(note: this wait is on stackshot's own count, dry run or watch, and you can read or stage that now: do it, and park only for what is left, "
                 "an outside party, a vendor or a date)")
FRONT_ANSWER_NOTE = ("\n(note: this wait is on the answer of {who}, a front agent. A call that is not {him}'s is yours to decide; one that is {him}'s goes to "
                     "{him} as a decision with options and your recommendation. A front agent's answer is no wait)")


def own_read(*reasons: Any) -> str:
    """The first words by which one of these reason texts (the wait_basis, the wait_event and the wait reason a write gives, never its next or its status line) says the wait is on stackshot's own count,
    dry run or watch, else "". A reason that also names an outside party (a vendor, an auditor, their site) is that party's wait, and says "" here."""
    for t in reasons:
        t = str(t or "")
        m = OWN_READ.search(t)
        if m and not OUTSIDE.search(t):
            return m.group(0)
    return ""


def front_named(texts: Iterable[Any], fronts: Iterable[str]) -> str:
    """The front agent (from `fronts`, the names the project pages list as front) a line of these texts waits on for an answer, else "": a line that waits on it ("waiting on quill's answer", "waiting for quill"),
    waits until it answers or decides, asks it for a decision, or waits for its answer. A front agent only told or notified of something, named with no wait, or named by a longer name (`old-quill`) is not it."""
    names = {str(f).strip().lower(): str(f).strip() for f in fronts if str(f or "").strip()}
    for t in texts:
        for line in str(t or "").splitlines():
            for m in _WAIT_ON.finditer(line):
                if m.group("name").lower() in names and not _TOLD.match(m.group("rest")) and (not m.group("rest").strip() or _ANSWER_WORD.search(m.group("rest")) or _DATE_TAIL.match(m.group("rest"))):
                    return names[m.group("name").lower()]
            for rx in (_WAIT_UNTIL, _ASKED):
                for m in rx.finditer(line):
                    if m.group("name").lower() in names:
                        return names[m.group("name").lower()]
            if _WAIT.search(line):
                for m in _ANSWER_OF.finditer(line):
                    if m.group("name").lower() in names:
                        return names[m.group("name").lower()]
    return ""
