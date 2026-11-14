"""reports.py — does a background agent's message to a front agent clearly only report?

the owner's rule: a front agent (a session he talks to) is woken by a message only when it has something to do or to tell him. A builder's
`[for <owner>]` message that only reports done work on a board item wakes the pane for nothing: the item already carries the state. So
the message tool (service/messaging.py `_builder_report`) writes such a message onto the item it names and delivers it to nobody.

A list of ask words always misses some ("awaits your merge", "Take X", a fact he must know that has no ask word in it), so the test
is turned around: **only what clearly reads as a status report is held back; everything else is delivered.** A text is a
report only when ALL of these hold, and `report_doubt` names the first that does not:

  1. no `?` anywhere (a URL's included) and no fenced block; a code span only when it is an id, sha, path or short command;
  2. no word of trouble, waiting, asking or deciding (TROUBLE: fail, broke, rolled back, cost, $, blocked, wait*, await*, pending, need*, must,
     should, require*, review*, ready, approve*, decid*, confirm*, please, option, plus the configured [keywords.reports] ask_words …);
  3. no word that puts the action on someone: the owner or one of his aliases, you, your, owner, keeper, a front agent's name (`avoid`);
  4. no future or conditional (will, once, when, if, then, until …): a plan is not a status;
  5. every sentence, once the mark, the `For <agent>,` address and the ids (items, PRs, shas, numbers) are taken out, is short and says one
     of the status shapes (STATUS): done, live, merged, released, deployed, closed, opened, fixed, passes, green, recorded, written, pushed,
     landed, unchanged, "is up", "no change".

Anything else is delivered, and so is a failure in the check (the caller's). Stdlib only."""
from __future__ import annotations

import re

from stackshot.core import config as _cfg

_MARK = re.compile(r"\[for [^\]\n]{1,40}\]", re.I)
_ADDRESS = re.compile(r"\A\s*for\s+[\w-]+\s*[,:]", re.I)
_FENCE = re.compile(r"```|~~~")
_SPAN = re.compile(r"`([^`\n]*)`")
_SPAN_OK = re.compile(r"[\w./#:@=~$+*-]+(?: [\w./#:@=~$+*\"'-]+){0,3}")           # an id, sha, path or short command: no prose
_IDS = re.compile(r"\bboard#\d+|\b[a-z]\d+\b|#\d+|\b(?:pr|pull request)s? #?\d+|\b(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b|\b\d[\d:.,/-]*\b", re.I)

TROUBLE = (
    r"fail\w*", r"broke\w*", r"broken", r"errors?", r"roll(?:ed)?[ -]?back", r"costs?", r"cost\w+", r"blocked?\w*", r"wait\w*", r"await\w*", r"pending",
    r"need\w*", r"must", r"should", r"require\w*", r"review\w*", r"merge-ready", r"ready", r"approv\w*", r"decid\w*", r"decision\w*", r"confirm\w*",
    r"please", r"ask\w*", r"options?", r"recommend\w*", r"propos\w*", r"questions?", r"choose", r"choice", r"stuck", r"unable", r"cannot", r"can't",
    r"offline", r"down", r"problem\w*", r"urgent", r"risk\w*", r"warn\w*", r"crash\w*", r"denied", r"refus\w*", r"missing", r"revert\w*", r"regress\w*",
)
PEOPLE = (r"you", r"you'?ll", r"your", r"yours", r"yourself", r"owner", r"keeper", r"front agents?", r"main agent", r"user")
FUTURE = (r"will", r"would", r"going to", r"once", r"when", r"if", r"unless", r"until", r"then", r"soon", r"later", r"next", r"follows?", r"after", r"before")
STATUS = (r"done", r"live", r"merged", r"released", r"deployed", r"closed", r"opened", r"fixed", r"pass", r"passes", r"passed", r"passing", r"green", r"recorded",
          r"written", r"unchanged", r"pushed", r"landed", r"is up", r"no changes?", r"nothing changed", r"no \w+ changed")

_word = lambda alts: re.compile(r"(?<![\w-])(?:" + "|".join(alts) + r")(?![\w-])", re.I)
_TROUBLE, _PEOPLE, _FUTURE, _STATUS = _word(TROUBLE), _word(PEOPLE), _word(FUTURE), _word(STATUS)


def _people():
    """The people and roles a report must not name: the fixed words and the owner's own names (his name and aliases from the config)."""
    names = [re.escape(n) for n in _cfg.owner_names() if n]
    return _word(list(PEOPLE) + names) if names else _PEOPLE


SENTENCE_WORDS = 30                      # a status sentence is short; a longer one is prose


def report_doubt(text: str, avoid: tuple[str, ...] | list[str] = ()) -> str:
    """"" when the text clearly only reports; else the first reason it is not taken for a report (a phrase for the log and the tests).
    `avoid` = names that must not appear (every front agent's name). Pure: the same text always gives the same answer."""
    t = str(text or "")
    if "?" in t or "？" in t:
        return "a question mark"
    if _FENCE.search(t):
        return "a fenced block"
    for m in _SPAN.finditer(t):
        if not _SPAN_OK.fullmatch(m.group(1).strip()):
            return "a code span with prose"
    t = _SPAN.sub(" X ", _ADDRESS.sub(" ", _MARK.sub(" ", t)))
    if "$" in t:
        return "a cost"
    for n in avoid:
        if n and n.lower() in t.lower():
            return f"the name {n}"
    for rx, what in ((_TROUBLE, "a word of trouble or waiting"), (_people(), "a person or role named"), (_FUTURE, "a plan, not a status")):
        m = rx.search(t)
        if m:
            return f"{what} ({m.group(0)!r})"
    if any(w in t for w in _cfg.keywords("reports", "ask_words")):
        return "a configured word of asking or waiting"
    sentences = [s.strip(" :-*•\t") for s in re.split(r"[.!;\n]+", _IDS.sub(" ", t))]
    sentences = [s for s in sentences if re.search(r"[^\W\d_]", s)]
    if not sentences:
        return "nothing said"
    for s in sentences:
        if len(s.split()) > SENTENCE_WORDS:
            return "a long sentence"
        if not _STATUS.search(s):
            return f"a sentence that is no status shape ({s[:40]!r})"
    return ""


def is_report(text: str, avoid: tuple[str, ...] | list[str] = ()) -> bool:
    """True when the text clearly only reports (report_doubt finds nothing)."""
    return not report_doubt(text, avoid)
