"""next_rules.py — the write checks of Next.

The rules of the Next design this module serves (N1, N3, N6 and N7; N2, N4 and N5 are owner_steps.py):

  N1  one step, one action, one named actor: a line of next that opens with no `<actor>:` is refused when a session writes it (it used to count as the owner's without a word)
  N3  nothing leaves the list: a step is marked done or dropped, or kept; a reworded open step drops the old and adds the new, so the text is never rewritten to carry progress
      (the old text plus added words is refused: that is the rewrite)
  N6  an open item has an open step: a session write that leaves no open step on an item that stays open is refused (his server-made step counts; a close is exempt)
  N7  a step is an action, never a status: results, commit hashes, test counts and "at work since" stamps are noted, never refused (server._report_note carries the matcher)

Pure text functions, no server import. Only a session's write through the create and update tools is judged (server._SESSION_NEXT); a script's, the router's and the server's own writes are not,
and a line already stored is read as it is (a line naming no one still counts as his in steps.is_his): no data is changed here."""
from __future__ import annotations

import re
from typing import Any, Callable

from stackshot.core import config as _cfg
from stackshot.model import model_guards as _mg
from stackshot.model import nextlines as _nl
from stackshot.model import steps as _steps

NO_STEP_FIX = f"add the next step in next, opening with who takes it (`<session>:`, `{_cfg.owner()}:` or the outside party's name), or keep one open step (for a parked item, who looks again at the wake), or close the item (complete); an open item always has an open step"
NO_STEP_FIX_HELD = "a parked item needs a step too, the one its wake leads to: write it in the same call, opening with who looks again (`<session>: look again at … on the wake`), or complete the item; the hold keeps the item out of sight, it does not take the step away"
FIX = f"open the line with who takes it: `<session>:`, `{_cfg.owner()}:` or the outside party's name"      # the fix N1's refusal names (the tool text says the same)

hint = _mg.line_hint      # why a refused line names no one, when it can be said (a label such as `Status:`, a missing space after the colon)

_MARKER = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+")
_PAREN = re.compile(r"\s*\([^)]*\)")
_TAIL = " .,;:"


def first_of(entry: str) -> str:
    """The first non-blank line of a next entry, as written."""
    return next((ln for ln in str(entry or "").splitlines() if ln.strip()), "")


def unnamed(text: Any, skip_first: Callable[[str], bool] | None = None) -> list[str]:
    """N1: the entries of a next text whose first line names no one (`<actor>:` after an optional list marker and bold marks). Not counted: the words none, clear and `-` that remove a session's lines;
    a sub-line (a bullet or number with no name, `- check the log`) that follows a step above it, since it belongs to that step (one with no step above it is counted); an entry `skip_first` accepts when it
    is the first (the ask line a client without the ask parameter writes there, which the server lifts). Returns the first lines, in order."""
    t = str(text or "")
    if t.strip().lower() in _nl.NONE_WORDS:
        return []
    out: list[str] = []
    stepped = False                         # a step with a name stands above
    for i, entry in enumerate(_nl.split(t)):
        first = first_of(entry)
        if i == 0 and skip_first is not None and skip_first(first.strip()):
            stepped = True
            continue
        nm = _steps.opener(first)
        if nm and not _mg.not_actor(nm):      # `Status:` and the like open a line without naming anyone
            stepped = True
        elif _MARKER.match(first) and stepped:
            continue                        # a sub-step of the step above
        else:
            out.append(first.strip())
    return out


def _key(text: Any) -> str:
    return _nl.norm(text).lower().rstrip(_TAIL)


def grows(old: Any, new: Any) -> bool:
    """N3: is `new` the text of `old` with words added, the rewrite that carries progress ("my-x: wait for CI" → "my-x: wait for CI (builder at work since 09:30)")? Yes when old is a proper prefix of new
    that ends at a word boundary, or when new reads as old once its parentheticals are taken out. A different action (a new text that is not old plus words) is a genuine rewording and is not caught."""
    o, n = _key(old), _key(new)
    if not o or o == n:
        return False
    if n.startswith(o) and not n[len(o)].isalnum():
        return True
    return _key(_PAREN.sub("", n)) == _key(_PAREN.sub("", o)) and _PAREN.sub("", n) != n


def growths(leaving: list[str], arriving: list[str]) -> list[tuple[str, str]]:
    """N3: [(the old step, the new one)] for each new step that is an old step's text plus words, among the open steps leaving the list unmarked (`leaving`, left out of next with neither done=[n] nor dropped=[n]; a step marked done or dropped is no
    reword, the caller leaves it out) and the steps arriving (`arriving`, the new text's lines that no open step already reads). One pair per new step."""
    out = []
    for new in arriving:
        for old in leaving:
            if grows(_steps.first_line(old) if "\n" in old else old, _steps.first_line(new) if "\n" in new else new):
                out.append((old, new))
                break
    return out


def moves(old_steps: list[dict[str, Any]], done_ix: list[int], drop_ix: list[int], new_text: str) -> tuple[list[tuple[int, str]], list[str]]:
    """What a write does to the open steps, lined up the way steps.apply lines them up (a step stays when an unused line of the new next reads the same): ([(position, text)] of the open steps that leave,
    not counting the ones marked done; [the new next's lines no open step already reads]). `old_steps` is steps.view of the item before the write, `done_ix` and `drop_ix` the marked indexes."""
    chunks = _nl.split(new_text)
    pool = [_steps.key(c) for c in chunks]
    leaving: list[tuple[int, str]] = []
    for i, st in enumerate(old_steps):
        if st["status"] != _steps.OPEN or i in done_ix:
            continue
        k = _steps.key(st["text"])
        if i not in drop_ix and k in pool:
            pool.remove(k)
        else:
            leaving.append((i, st["text"]))
    arriving = []
    for c in chunks:
        k = _steps.key(c)
        if k in pool:
            pool.remove(k)
            arriving.append(c)
    return leaving, arriving


# ---------------------------------------------------------------------------------------------------------------- N7: a step is an action, never a status
# The matchers of the report note (server._report_note), kept here so that the daily audit's tool (tools/next_report.py) reads a step with the same eyes and imports no server.
# A markdown link's URL and a naked URL are cut out by the caller (link_free) before a line is read.
RX_LINK_URL = re.compile(r"\[([^\]]*)\]\([^)\s]*\)")
_RX_NAKED = re.compile(r"(?<!\]\()https?://[^\s)\]>]+")
RX_HASH = re.compile(r"(?<![\w/#.-])(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}(?![\w/-])")
RX_COUNT = re.compile(
    r"(?<!add )(?<!adds )(?<!write )(?<!run )(?<!need )(?<!needs )(?<!with )(?<!more )(?<!enough )\b\d+\s+(?:tests?|checks?|passed|passing)\b"
    r"|\ball\s+(?:the\s+)?(?:(?:suites?|tests?|checks?)\s+(?:are\s+)?(?:green|pass(?:ed|ing)?)|passed)\b"
    r"|\b(?:tests?|suites?|checks?|CI)\s+(?:all\s+)?passed\b(?<!after tests passed)(?<!once tests passed)(?<!when tests passed)(?<!until tests passed)", re.I)
_PAST = r"(?:merged|done at|live since|deployed|released)\b"
RX_PAST = re.compile(rf"^(?:[\w.@-]+:\s*)?{_PAST}|\bPR\s*#?\d+\s*(?:\([^)]*\))?\s*[,:;\u2013\u2014-]?\s*{_PAST}", re.I)
# A stamp of when work began ("since 09:30", "at work since"), and a status word in the middle of a line ("PR #12 is live", "it was merged", "already deployed"). A status word after a word that makes it a condition or a thing
# to look for (once, when, until, after, if, wait, check, verify …) is quiet: that line is an action on the state to come, not the state. "release PR #123" and "merge PR #12 after green CI" carry no status.
RX_STAMP = re.compile(r"\b(?:at work |working |in progress )?since \d{1,2}[:.]\d{2}\b|\bat work since\b", re.I)
RX_STATUS = re.compile(r"\b(?:(?:is|was|now|already|got|been)\s+(?:now\s+|already\s+)?(?:live|merged|deployed|released)\b|PR\s*#?\d+\s+(?:is\s+)?(?:merged|live|deployed|released)\b)", re.I)
RX_COND = re.compile(r"\b(?:once|when|whenever|until|till|after|before|if|unless|wait|waits|waiting|check|verify|confirm|whether|that|so)\b", re.I)


def _status_hit(ln: str) -> "re.Match[str] | None":
    m = RX_STATUS.search(ln)
    return m if m and not RX_COND.search(ln[:m.start()]) else None


# A hash that names the thing waited on is no report: "when GitHub removes commit 0201c0d", "until 0204c0d lands". It is left alone only when the NEAREST wait or
# condition word before it in the same clause sits right on it: nothing between the two but "commit" or an article ("once 0202c0d", "wait until 0203c0d", "after the
# 0204c0d"), and no state word ahead of that wait word ("tests pass after 0202c0d" reports). A copula or any other words in between ("after the rebase the fix is
# 0202c0d", "once CI is green the fix is 0202c0d") make it a report. "removes" and "deletes" count as waiting only after a condition word ("when GitHub removes commit
# 0201c0d"); "reverts" never does ("this PR reverts 0204c0d"). A word right before the hash that reports finished work ("merged at 0202c0d", "landed in 0204c0d",
# "pushed 0205c0d", "head 0205c0d", "is 0202c0d", "fix is 0202c0d", "reverts 0204c0d") flags it whatever came first.
_RX_CLAUSE = re.compile(r"[,;:()\[\]\u2013\u2014]|\.\s|\s-\s")
_HASH_COND = r"once|when|whenever|until|till|after|before|if|unless"
RX_HASH_WAIT = re.compile(rf"\b(?:{_HASH_COND}|wait|waits|waiting|awaits?|awaiting|expect|expects)\b", re.I)
RX_HASH_WAIT_VERB = re.compile(r"\b(?:removes?|removed|deletes?)\b", re.I)
RX_HASH_COND = re.compile(rf"\b(?:{_HASH_COND})\b", re.I)
RX_HASH_GAP = re.compile(r"^\s*(?:(?:the|a|an|commit|revision)\s+){0,2}$", re.I)
RX_HASH_STATE = re.compile(r"\b(?:pass|passes|passed|passing|green|ok|fail|fails|failed|work|works|worked|fixed|broke|broken|is|are|was|were|done|ready|live)\s+$", re.I)
RX_HASH_DONE = re.compile(r"\b(?:merged?|landed|pushed|committed|shipped|deployed|released|reviewed|in|at|head|as|is|are|was|were|reverts?|reverted)\s+(?:commit\s+)?$", re.I)


def _hash_waited_on(clause: str) -> bool:
    """True when the clause (the text before a hash, cut at the last clause break) ends in a wait word that sits right on the hash."""
    last = None
    for m in RX_HASH_WAIT.finditer(clause):
        last = m
    for m in RX_HASH_WAIT_VERB.finditer(clause):
        if RX_HASH_COND.search(clause[:m.start()]) and (last is None or m.start() > last.start()):
            last = m
    if last is None or not RX_HASH_GAP.match(clause[last.end():]):
        return False
    return not RX_HASH_STATE.search(clause[:last.start()])


def _hash_hit(ln: str) -> "re.Match[str] | None":
    """N7's commit hash: the first hash in a line that reports work (not one that is the object of a wait or a condition)."""
    for m in RX_HASH.finditer(ln):
        before = ln[:m.start()]
        if RX_HASH_DONE.search(before) or not _hash_waited_on(_RX_CLAUSE.split(before)[-1]):
            return m
    return None


def link_free(ln: str) -> str:
    """A line with its markdown links cut to their text and its naked URLs removed, as the report note reads it."""
    return _RX_NAKED.sub("", RX_LINK_URL.sub(r"\1", ln))


def report_signals(ln: str) -> dict[str, str]:
    """N7: what in one (link-free) line reads like a report rather than an action: {kind: the matched words (40 characters at most)} for a commit hash, a test count, a past-tense report and a since-time stamp; {} for an action."""
    out: dict[str, str] = {}
    for kind, m in (("a commit hash", _hash_hit(ln)), ("a test count", RX_COUNT.search(ln)), ("a past-tense report", RX_PAST.search(ln) or _status_hit(ln)), ("a since-time stamp", RX_STAMP.search(ln))):
        if m:
            out[kind] = m.group(0).strip()[:40]
    return out
