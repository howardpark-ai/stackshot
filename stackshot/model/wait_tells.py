"""wait_tells.py: the words of two tells a write that sets a wait gets, when the wait is on something the writer can settle now.

A wait is for what cannot be had now: an outside party, a vendor, a date, or a park the user asked for. Two kinds of wait name something that can:

  own read     a wait on stackshot's own count, dry run or watch (`wait_basis="the dry-run count can be read <day>"`): the writing session reads that count, or stages that run, itself
  front answer a wait on a front agent's answer, set by a back or builder session: a call that is not the user's is the writer's to decide, and one that is the user's goes to the user as options

Pure text functions, no server import. `service/update.py` (`_wait_tells`) reads the roles and the items and puts each answer on the write's reply as a note, never a refusal."""
from __future__ import annotations

import re
from typing import Any, Iterable

# What a wait on stackshot's own count, dry run or watch reads like, in stackshot's own wording: the dry-run count, the watch count, a count the server keeps, the sent-mail watch, the watch's result, stackshot's own count.
# A bare "dry run", a bare "count" or "watch", and a standalone "own" or "server's" are no match: those are as often an outside party's (a bank's dry run, someone's own count of receipts, a web server's count at a CDN).
OWN_READ = re.compile(r"\b(?:dry[- ]?run|watch(?:es)?)\s+counts?\b|\bcounts?\s+(?:the\s+)?(?:server|stackshot)\s+keeps\b|\bstackshot'?s?\s+(?:own\s+)?(?:counts?|dry[- ]?runs?|watch(?:es)?)\b"
                      r"|\bsent[- ]mail\s+watch\b|\b(?:stackshot'?s?|the)\s+(?:own\s+)?watch\s+(?:pass|reads?|shows?|result|output)\b", re.I)
# a word that puts the reason's count or dry run with someone else (their site, a vendor's run, an auditor's vote count): the wait is on that party, and stays
OUTSIDE = re.compile(r"\b(?:vendor|auditor|partner|customer|supplier|translator|contractor|their|outside|external)", re.I)
# a word that says the reason's blocker is another thing (a soak, a window, a deadline): the count or run is named in passing, and the wait stays
OTHER_BLOCKER = re.compile(r"\b(?:soak|window|deadline|(?:release|launch|due|target)\s+date)", re.I)
# a front agent is the one to answer: it must be waited on, asked or expected for an answer in one clause (a clause ends at . ; , or a line end); a past tense is no wait
_ANS = r"(?:answers?|repl(?:y|ies)|decisions?|verdicts?|calls?|go-ahead|sign[- ]?off|responses?|word)"
_ANS_END = r"(?=\s*(?:$|[.,;:!?)]|\s(?:on|about|to|by|before|from|of|due|whether|if|and|so|then|today|tomorrow|is|will)\b))"      # the answer word ends its phrase ("the word count script", "the decision page" are no answer)
_NAME = r"(?<![\w-])(?P<name>[\w-]+)"      # a whole token: it starts at a boundary, so a long token is read once, not once per start position
_WAIT_ON = re.compile(rf"\b(?:wait(?:s|ing)?\s+(?:on|for)|pending|blocked\s+(?:on|by))\s+{_NAME}(?P<poss>['\u2019]s)?(?P<rest>[^.;,\n]*)", re.I)
_WAIT_ON_TAIL = re.compile(rf"\s+{_ANS}{_ANS_END}", re.I)                  # after "waiting on <front>'s": an answer word that ends its phrase
_WAIT_ON_ASK = re.compile(rf"\s+(?:to\s+(?:answer|decide|reply|respond|confirm|sign\s+off|say|pick|choose)\b|for\s+(?:(?:the|an?|its|his|her|their)\s+)?{_ANS}{_ANS_END})", re.I)      # after "waiting on <front>": it is asked to answer
_WAIT_UNTIL = re.compile(rf"\b(?:until|once|after|when)\s+{_NAME}\s+(?:answers?|repl(?:y|ies)|decides?|responds?|confirms?|signs\s+off|says)\b", re.I)
_ASKED = re.compile(rf"\bask(?:s|ing)?\s+{_NAME}\s+(?:for\s+(?:(?:the|an?|its)\s+)?{_ANS}{_ANS_END}|(?:whether|if|which|what)\b|to\s+(?:decide|answer|confirm|pick|choose)\b)", re.I)
_ANSWER_OF = re.compile(rf"{_NAME}['\u2019]s\s+{_ANS}{_ANS_END}", re.I)
_ANSWER_FROM = re.compile(rf"\b{_ANS}\s+(?:from|of|by)\s+{_NAME}", re.I)
_TOLD = re.compile(r"\s*to\s+(?:be\s+)?(?:told|notified|informed|hear)\b", re.I)
_DATE_TAIL = re.compile(r"\s*(?:on|by|until|due)\s+\d", re.I)
_WAIT_BEFORE = re.compile(r"\b(?:wait(?:s|ing)?|until|pending|blocked|expect(?:s|ing)?|(?<!no )(?<!not )(?<!n't )need(?:s|ing)?|await(?:s|ing)?)\b", re.I)      # a word, ahead of "<front>'s answer", that waits for it
_WAIT_AFTER = re.compile(r"\s+(?:(?:is|are|will\s+be)\s+)?(?:due|pending|expected|needed|awaited|outstanding)\b", re.I)      # a word, right after "<front>'s answer", that says it is waited for
_CLAUSE = re.compile(r"[.;,\n]")

OWN_READ_NOTE = ("\n(note: this wait is on stackshot's own count, dry run or watch, and you can read or stage that now: do it, and park only for what is left, "
                 "an outside party, a vendor or a date)")
FRONT_ANSWER_NOTE = ("\n(note: this wait is on the answer of {who}, a front agent. A call that is not {him}'s is yours to decide; one that is {him}'s goes to "
                     "{him} as a decision with options and your recommendation. A front agent's answer is no wait)")


def own_read(*reasons: Any) -> str:
    """The first words by which one of these reason texts (the wait_basis, the wait_event and the wait reason a write gives, never its next or its status line) says the wait is on stackshot's own count,
    dry run or watch, else "". A reason that also names an outside party (a vendor, an auditor, their site) is that party's wait, and one that names a soak, a window or a deadline waits on that: both say "" here."""
    for t in reasons:
        t = str(t or "")
        m = OWN_READ.search(t)
        if m and not OUTSIDE.search(t) and not OTHER_BLOCKER.search(t):
            return m.group(0)
    return ""


def _named(texts: Iterable[Any]) -> Iterable[str]:
    """The names (lowercase) that a clause of these texts waits on, asks or expects an answer of, in order: a clause is a stretch up to a `.`, `;`, `,` or a line end, and each way of waiting is read within one clause.
    Every token is read once, so a line of one very long token costs time in proportion to its length."""
    for t in texts:
        for clause in _CLAUSE.split(str(t or "")):
            for m in _WAIT_ON.finditer(clause):
                rest = m.group("rest")
                if m.group("poss"):
                    ok = bool(_WAIT_ON_TAIL.match(rest))
                else:
                    ok = not _TOLD.match(rest) and (not rest.strip() or bool(_WAIT_ON_ASK.match(rest)) or bool(_DATE_TAIL.match(rest)))
                if ok:
                    yield m.group("name").lower()
            for rx in (_WAIT_UNTIL, _ASKED):
                for m in rx.finditer(clause):
                    yield m.group("name").lower()
            first = _WAIT_BEFORE.search(clause)      # the answer of a front agent is waited for: a waiting word stands ahead of it, or "due", "pending", "expected" right after it
            for m in _ANSWER_OF.finditer(clause):
                if (first and first.start() < m.start()) or _WAIT_AFTER.match(clause, m.end()):
                    yield m.group("name").lower()
            for m in _ANSWER_FROM.finditer(clause):
                if first and first.start() < m.start():
                    yield m.group("name").lower()


def could_name_front(texts: Iterable[Any]) -> bool:
    """Does any clause of these texts wait on, ask or expect an answer of someone? A cheap read that needs no roles: when it is False, no front agent can be named, so the caller reads nothing else."""
    return any(True for _ in _named(texts))


def front_named(texts: Iterable[Any], fronts: Iterable[str]) -> str:
    """The front agent (from `fronts`, the names the project pages list as front) a clause of these texts waits on for an answer, else "": a clause that waits on it ("waiting on quill's answer", "waiting for quill"),
    waits until it answers or decides, asks it for a decision, waits for its answer ("expecting quill's answer", "waiting for the answer from quill", "need quill's answer by a date"). A front agent only told or notified of something,
    named with no wait, named by a longer name (`old-quill`), waited on for work ("waiting on quill to merge the page that adds the decision"), asked for something that is no answer, or one whose answer is in the past tense
    ("after quill confirmed", "asked quill yesterday") is not it."""
    names = {str(f).strip().lower(): str(f).strip() for f in fronts if str(f or "").strip()}
    for n in _named(texts):
        if n in names:
            return names[n]
    return ""
