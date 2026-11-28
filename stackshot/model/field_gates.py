"""field_gates.py: the write-time checks of an item's fields: the subject (its scope prefix and length, `_gate_subject`), the description (short `- ` bullets, `_gate_description`, and its opening
goal, `_gate_goal`), `next` (a named actor and a length per line, `_gate_next`; the marks of a dropped step), a session's bare URLs (`_gate_bare_urls`), the small limits they read (`_subject_max`,
`_close_reason_max`, `_description_limits`, `_next_line_max`, `_bullets_on`, `_fit`) and the two sentences a refusal borrows from the fleet settings (`_when_idle`, `_fleet_tool`).

Each is a rule of the item's own text and the instance's settings: it raises ToolError with the refusal, or returns what it normalized, and reads nothing from the store and changes nothing. The two
checks that apply to a session's own write only (`_gate_next`'s actor check, `_gate_bare_urls`) take that as the `session` argument: the caller reads the per-write flag (`service/writes.py`) and passes it. The
metadata check, which looks a project's page up in the registry and may rebuild it, and the registry readers it uses are `service/gates.py`'s."""
from __future__ import annotations

import json
import re
import shlex
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core import call_log as _calls
from stackshot.core import config as _cfg
from stackshot.core.instance import OWNER
from stackshot.model import bullet_text as _bt
from stackshot.model import faults as _faults
from stackshot.model import list_repair as _lr
from stackshot.model import model_guards as _mg
from stackshot.model import next_rules as _nr
from stackshot.model import nextlines as _nl
from stackshot.model import step_split as _ss
from stackshot.model import steps as _steps
from stackshot.model.bullet_text import _clip_line
from stackshot.web import render as _rmod


# ----------------------------------------------------------------------------- gates (all deterministic)
SUBJECT_MAX_DEFAULT = 80          # a title is one short line (was 200 in code, 160 in the example config); the length of the whole subject, scope prefix included
CLOSE_REASON_MAX_DEFAULT = 120    # a close's reason is one short line ([close] reason_max)


def _subject_max() -> int:
    """[subject] max_length (default 80): the longest subject a create or an update that sets one takes, the scope prefix counted (len of the stored text, as before)."""
    return int(_cfg.CFG["subject"].get("max_length", SUBJECT_MAX_DEFAULT) or 0)


def _close_reason_max() -> int:
    """[close] reason_max (default 120): the longest reason a close (complete, or update with status=completed) takes; 0 = no limit."""
    return int((_cfg.CFG.get("close") or {}).get("reason_max", CLOSE_REASON_MAX_DEFAULT) or 0)


def _fit(text: str, limit: int) -> str:
    """Free text as one line of at most `limit` characters (0 = no limit): whitespace collapsed, cut at a word with an ellipsis that is counted. For what the server writes itself,
    where a gate must never refuse it (a close's reason, a subject it builds)."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if not limit or len(t) <= limit:
        return t
    room = max(limit - 2, 1)
    cut = t[:room].rsplit(" ", 1)[0] if " " in t[:room] else t[:room]
    return cut.rstrip(" ,;:") + " …"


# a subject that already opens with a bracketed tag or a "word:" (`[Work] x`, `[work]x`, ` [work] x`, `work: x`) is somebody's attempt at a prefix, not a missing one: it is refused as ever, the list named
_SUBJECT_TAGGED = re.compile(r"[\s​-‏⁠﻿]*(?:\[[^\]]*\]|\w+:)")


def subject_faults(subject: str, current: str | None = None) -> list[str]:
    """Every fault of a subject's form, each as the refusal it is alone: no scope prefix, over [subject] max_length. `current` is the stored subject of an update: a write that sets the very text
    it already has (a long one stored before the limit) is not a change and passes the length check."""
    s = _cfg.CFG["subject"]
    out: list[str] = []
    if not any(subject.startswith(pfx) for pfx in s["prefixes"]):
        out.append(f"Refused: subject must start with one of {s['prefixes']} — got {subject[:40]!r}")
    lim = _subject_max()
    if lim and len(subject) > lim and subject != current:
        out.append(f"Refused: the subject is {len(subject)} characters and the limit is {lim}, the scope prefix counted. Shorten it to the work that closes the item; "
                   "the detail goes in the description bullets (and the project page's timeline).")
    return out


def _gate_subject(subject: str, current: str | None = None) -> None:
    """Refuse a subject that does not start with a scope prefix, or is over [subject] max_length (every fault of it, together; `subject_faults` has them as a list)."""
    if got := subject_faults(subject, current):
        raise _faults.refusals(got)


# The rule of a title: it reads at a glance as the work that closes the item (in English an imperative, in Korean a verb noun in -hagi or a noun task). The reading names only what plainly is not that: a question,
# a "should" or "must" sentence, and a statement of state or symptom. A task title is never to be named, and a miss costs little (the daily audit's judge reads the titles the reading passes): a verb that is also a
# noun makes some symptoms read like tasks ("Search results are empty"), and they pass. Korean puts the verb last, so a Korean title is read by how it ends; its words are escapes (no Hangul in the repository).
_READ_MAX = 300      # a longer text is no title, and reading it is not worth what the patterns could take on it
_RX_ASKS = re.compile(r"(?:how|whether) to\s", re.I)
_RX_GOES_ON = re.compile(r"\b(?:no longer|again|shows|shown|appears|works|stays|runs|loads|opens|returns|answers|explains|goes|gets|reads|says|lists|tells|reaches|passes|live|written|is|are|was|were|has|can|will|\w{2,}ed)\b", re.I)      # a "how to" title that goes on to state something is not called a question
_RX_ASKS_END = re.compile("(?:\ud560\uc9c0| \ub9d0\uc9c0|\uc5ec\ubd80)$")      # whether to, "... or not", whether or not; "way" is not read: it also names a thing to build (a payment method)
_KO_KKA = ("\uae4c", "\uae4c\uc694")      # shall we: a question after a syllable closed by l
_RX_KO_ASKING = re.compile("(?<![^ ])(?:\uc5b4\ub5a4|\uc5b4\ub290|\ubb34\uc5c7|\ubb58|\ubb50|\uc5b4\ub514|\uc5b8\uc81c|\ub204\uad6c|\ub204\uac00|\uc5b4\ub5bb\uac8c|\uba87|\uc5bc\ub9c8)")      # a word that asks (which, what, where, when, who, how): with it, an l-closed syllable before \uc9c0 ends "whether to"
_RX_KO_SHOULD = re.compile("(?:\uc57c ?(?:\ud55c\ub2e4|\ud568|\ud569\ub2c8\ub2e4|\ub428|\ub41c\ub2e4|\ub429\ub2c8\ub2e4|\ud574|\ud574\uc694|\ud560 \uac83)|\ud544\uc694\uac00 (?:\uc788\ub2e4|\uc788\uc74c|\uc788\uc2b5\ub2c8\ub2e4)|\ud544\uc694\ud558\ub2e4|\ud544\uc694\ud569\ub2c8\ub2e4)$")      # must, has to, needs to
_KO_BEFORE_DA = "\uc54a\uc5c6\uac19\ub9ce\uc88b"      # the syllables before a final -da that close a statement, beside those that end in n or ss (read by their code)
_KO_DA_WORDS = ("\ub290\ub9ac\ub2e4", "\ub835\ub2e4", "\ub7fd\ub2e4", "\ud2c0\ub9ac\ub2e4", "\ub2e4\ub974\ub2e4", "\ub2a6\ub2e4", "\uc791\ub2e4", "\ud06c\ub2e4", "\ub192\ub2e4", "\ub0ae\ub2e4", "\ubd80\uc871\ud558\ub2e4", "\ubd88\ud3b8\ud558\ub2e4", "\uc774\uc0c1\ud558\ub2e4", "\ubd88\uac00\ub2a5\ud558\ub2e4", "\uc911\uc774\ub2e4")      # slow, hard, wrong, different, late, small, big, high, low, lacking, awkward, odd, impossible, under way
_KO_DA_NOUNS = ("\uc820\ub2e4", "\ubca0\ub780\ub2e4", "\ud310\ub2e4", "\ud63c\ub2e4", "\uc6b0\uac04\ub2e4", "\ub974\uc644\ub2e4", "\ud30c\uac04\ub2e4", "\uc544\ub9cc\ub2e4")      # loan words that end like a statement: agenda, veranda, panda, Honda, Uganda, Rwanda, propaganda, Amanda
# the words an English task title opens with
_TASK_VERBS = frozenset("""accept add adjust align allow always analyse analyze announce answer apply approve archive arrange ask assign attach audit automate avoid back backfill backport bake ban batch benchmark block book bring build
bump buy cache call cancel cap capture catch caulk change chase check choose clarify clean clear close collapse collect color combine commit compare compile complete compress confirm connect consider
consolidate containerize convert cook copy correct count cover create cut deactivate deal debounce decide declare declutter decouple dedupe default defer define defrost delay delete deliver deploy deprecate
descale describe design detect diagnose dim disable disallow discuss dismiss display do document dogfood double draft drop dump duplicate email embed emit enable encrypt end enforce enrol enroll ensure enter
escalate estimate evaluate exclude exempt expand expire explain export expose extend extract fail feed fetch file fill filter finalize find finish fit fix flag flatten fold follow force format forward free freeze
gate gather generate get give grant group guard handle harden have hide highlight hold hook host identify ignore implement import improve include increase index inform initialize inline insert inspect install
instrument integrate introduce investigate invite isolate issue join keep kill label launch learn leave let limit line link lint list load localize lock log look lower mail maintain make manage map mark mask
match measure meet mention merge migrate mirror mock move mow mute name narrow never normalize note notify nudge offer omit onboard only open optimize order organize overhaul package pad page paginate paint
parameterize parse pass patch pause pay persist phase pick pin ping pipe place plan play please point polish poll populate port post prefer prefetch prep prepare present preserve prevent preview print
prioritize probe produce profile promote prompt propose protect prove provide provision prune publish pull purge push put qualify query queue quiet quote raise rate reach reactivate read reattach rebalance
rebase rebuild recalculate recheck reconcile reconfigure reconnect record recover recycle redact redesign redirect redo reduce refactor refer refill refine reflect refresh refund regenerate register reimburse
reindex reinstall reject relabel release relink reload remind remove rename renegotiate renew reopen reorder reorganize repaint repair repeat replace replay reply repopulate report repot request require rerun
rescan reschedule research resend reserve reset resize resolve respect respond rest restart restock restore restrict resume retain retest retire retrain retry return reupload reuse revalidate revert review
revise revisit revoke rewire rework rewrite ride rip roll rotate round route run sample sanitize save scale scan schedule scope score scrub seal search secure see seed select sell send separate serialize serve
set settle shard share sharpen ship shop shorten show shrink shut sign silence simplify sit skip slim slow snapshot snooze solve sort source spec specify speed spell split spread squash stabilize stage stamp
standardize start state stay stop store stream streamline strengthen strip structure study style submit subscribe suggest summarize sunset supply support suppress surface suspend swap switch sync tag take talk
tally teach tear tell test thank throttle tidy tie tighten time toggle trace track train transfer translate trap treat triage trigger trim try tune turn type unblock undo unify unpin unsubscribe unwind update
upgrade upload upstream use vacuum validate vendor verify version view visit wait wake walk warm warn wash watch wire wrap write""".split())
_TASK_PREFIXES = ("re-", "un-", "de-", "pre-", "auto-")
_BEFORE_VERB = frozenset(("also", "please", "just", "then", "now", "first", "again"))      # these and an -ly word may stand before a task's verb
_RX_SHOULD = re.compile(r"(?<![\w-])(?:should(?:n['’]t)?|must(?:n['’]t)?|ought to|needs? to|has to|have to)(?![\w-])", re.I)
_RX_STATE = re.compile(r"(?<![\w-])(?:is|are|was|were|isn['’]t|aren['’]t|wasn['’]t|weren['’]t|fails|keeps|gets|goes|does not|doesn['’]t|do not|don['’]t|cannot|can['’]t|won['’]t|has no|have no|no longer \w+s|never \w+s|keep \w+ing)(?![\w-])", re.I)
# after a first word that is also a task verb ("Build fails on the phone"), only forms that cannot go on from that verb as its object
_RX_AFTER_NOUN = re.compile(r"(?:is|are|was|were|isn['’]t|aren['’]t|wasn['’]t|weren['’]t|doesn['’]t|does not|should|needs to|has to|fails (?:to|on|when|after|with|every|at)|keeps \w+ing)(?![\w-])", re.I)
_RX_NOT_MAIN = re.compile(r"[,;–—]| - |\b(?:that|which|who|whom|whose|when|where|while|whenever|wherever|if|whether|how|why|what|so|until|after|before|because|unless|as|once|than|to|like)\b", re.I)      # a verb after one of these may not be the title's own
_SUBJECT_WORDS = 6      # the most words that stand before the verb of a statement
_DETERMINERS = frozenset("a an the my our your his her their its this that these those each every any some no new old another one two".split())      # after one of these a listed word is a noun ("the gate")
_RX_PRONOUN = re.compile(r"\b(?:I|we|you|they|he|she|it)\b")      # past the first word, one opens a clause of its own: "... newsletters we don't read" is not the title's sentence
_RX_QUOTED = re.compile(r"\"[^\"]*\"|“[^”]*”|‘[^’]*’|`[^`]*`|(?<!\w)'[^']*'(?!\w)|\([^()]*\)")      # words a title quotes or brackets are not its own sentence
_SHOULD, _STATEMENT = "a should or must sentence", "a statement"


def _without_end_brackets(part: str) -> str:
    """`part` without the bracketed asides at its end ("... (2)"), read from the end in one pass, however long the text."""
    end = len(part)
    while True:
        while end and part[end - 1].isspace():
            end -= 1
        i = part.rfind("(", 0, end) if end and part[end - 1] == ")" else -1
        if i < 0 or part.find(")", i + 1, end - 1) >= 0:
            return part[:end]
        end = i


def _ko_final(ch: str) -> int:
    """The closing consonant of a Hangul syllable, by its place in the code table (4 is n, 8 is l, 17 is p, 20 is ss); -1 for any other character."""
    code = ord(ch) - 0xAC00
    return code % 28 if 0 <= code < 11172 else -1


def _ko_question(part: str) -> bool:
    """Whether `part` ends as a Korean question without its mark: _RX_ASKS_END; kka or kkayo after an l-closed syllable ("shall we move it"); or ji after one, in a part that also holds a word that asks ("which one
    to use"). Without such a word the ending is left alone, and so is ilji, a log, whatever stands before it."""
    if _RX_ASKS_END.search(part):
        return True
    for end in _KO_KKA:
        if part.endswith(end) and len(part) > len(end) and _ko_final(part[-len(end) - 1]) == 8:
            return True
    return len(part) > 1 and part.endswith("\uc9c0") and not part.endswith("\uc77c\uc9c0") and _ko_final(part[-2]) == 8 and bool(_RX_KO_ASKING.search(part))


def _ko_statement(part: str) -> bool:
    """Whether `part` ends as a Korean statement: -da after a syllable closed by n or ss (handa, doenda, itda, -eotda) or one of _KO_BEFORE_DA, "anida", or the polite -mnida. A noun that happens to end in -da
    (mada, boda, bada) has none of these before it."""
    if len(part) < 2 or part[-1] != "\ub2e4" or part.endswith(_KO_DA_NOUNS):
        return False
    if part.endswith(_KO_DA_WORDS):
        return True
    if part.endswith("\ub2c8\ub2e4"):
        return part.endswith("\uc544\ub2c8\ub2e4") or (len(part) > 2 and _ko_final(part[-3]) == 17)
    return part[-2] in _KO_BEFORE_DA or _ko_final(part[-2]) in (4, 20)


def _opens_as_task(part: str) -> bool:
    """Whether an English part opens with the verb of a task: a listed word (also as the last of a hyphenated one, `Double-check`, or after `re-`), unless what follows makes that word a noun (`Build fails on ...`)
    or the part opens as a "should" sentence (`Have to ...`)."""
    if _RX_SHOULD.match(part):
        return False
    first, _, rest = part.partition(" ")
    word = first.strip("*_[].,!").lower()
    while rest and (word in _BEFORE_VERB or word.endswith("ly")) and word not in _TASK_VERBS:
        first, _, rest = rest.lstrip().partition(" ")
        word = first.strip("*_[].,!").lower()
    if not (word in _TASK_VERBS or word.startswith(_TASK_PREFIXES) or ("-" in word and word.rsplit("-", 1)[1] in _TASK_VERBS)):
        return False
    return not _RX_AFTER_NOUN.match(rest.lstrip())


def _english_sentence(part: str) -> str:
    """What an English part that is no task reads as: a "should" sentence when it opens with one or has one as its own verb, a statement when it has a verb of state as its own, else ""."""
    if _RX_SHOULD.match(part):
        return _SHOULD
    for rx, kind in ((_RX_SHOULD, _SHOULD), (_RX_STATE, _STATEMENT)):
        if found := rx.search(part):
            head = part[:found.start()]
            words = head.split()
            gerund = len(words) > 1 and words[0].lower().endswith("ing") and words[1].lower() in ("a", "an", "the", "all", "every", "each", "our", "my", "this", "these")      # "Confirming the lamp ..." is work, "Ceiling light ..." a noun
            if 0 < len(words) <= _SUBJECT_WORDS and not gerund and not _RX_NOT_MAIN.search(head) and not _RX_PRONOUN.search(" ".join(words[1:])):
                return kind
    return ""


def _verb_after(text: str) -> bool:
    """Whether a "how to" or "whether to" text goes on to a verb of its own, so that it names a thing and says what it does ("How to videos load offline", "How to dialog closes on Escape"): past the third word, a
    task verb or its -s form that no determiner stands before. A word right after the infinitive verb is that verb's object ("How to share logs")."""
    words = re.findall(r"[a-z][a-z'’-]*", text.lower())
    for i in range(3, len(words)):
        w, before = words[i], words[i - 1]
        if before in _DETERMINERS or (i == 3 and before in _TASK_VERBS):
            continue
        if w in _TASK_VERBS or (w.endswith("s") and w[:-1] in _TASK_VERBS) or (w.endswith("es") and w[:-2] in _TASK_VERBS):
            return True
    return False


def subject_reads_as(subject: str) -> str:
    """"a question", "a should or must sentence" or "a statement" when the subject plainly is one and so does not read as work, else "". Read past the scope prefix. A question mark at the end is a question, as
    is a part that opens `how to` or `whether to` (the first part, or one after a label of at most five words) in a title that goes on to state nothing, and a Korean last part that asks by its ending
    (_ko_question). A Korean last part is a "should" sentence or a statement by its ending. An English title is neither when any part opens with a task's verb; else each part is read for a verb of its own. A
    subject that ends with " …", as the server's cut (fix_long_subject) leaves one, is not read: the cut may have taken the words that decide. An ellipsis or dots typed onto the last word are dropped."""
    s = next((subject[len(p):] for p in _cfg.CFG["subject"]["prefixes"] if subject.startswith(p)), subject).strip()
    if len(s) > _READ_MAX or s.endswith(" …"):
        return ""
    s = s.rstrip(" .…。")
    if s.endswith(("?", "\uff1f")):
        return "a question"
    colon = r"[:\uff1a]\s+"
    parts = re.split(colon, s)
    opens = [parts[0], *(p for label, p in zip(parts, parts[1:]) if len(label.split()) <= 5)]
    last = _without_end_brackets(parts[-1]).rstrip(" .!。")
    if _ko_question(last) or (not _RX_GOES_ON.search(s) and any(_RX_ASKS.match(p) and not _verb_after(s[s.index(p):]) for p in opens)):
        return "a question"
    if _RX_KO_SHOULD.search(last):
        return _SHOULD
    if _ko_statement(last):
        return _STATEMENT
    plain = [p.strip() for p in re.split(colon, _RX_QUOTED.sub(" x ", s))]
    if any(map(_opens_as_task, plain)):
        return ""
    return next(filter(None, map(_english_sentence, plain)), "")


def subject_form_note(subject: str, sent: str = "") -> str:
    """The reply line of a session's write that leaves an item titled as a question, a "should" sentence or a statement: the subject is quoted, with what to send instead. Counted in the call log
    (call_log.noted). Information only: nothing is refused or stored differently. "" for any other subject. `sent` is the
    subject as the call passed it, when it passed one: it is what is read, so a long title is judged by all its words and not by what the server's cut kept; the stored `subject` is what is quoted. Why: a title that reads as a symptom or a target leaves open what is to be done, and nothing reads
    the title at write time."""
    kind = subject_reads_as(sent or subject)
    if not kind:
        return ""
    line = (f'\n(note: the subject "{_clip_line(subject)}" reads as {kind}, not as the work that closes the item: send subject= as that task, an imperative such as "Keep hand-off times on closed items" '
            '(in Korean, ending in -hagi or a noun task); a symptom goes in a `Problem:` bullet)')
    _calls.noted("subject-form")      # counted once the line is made: a line that fails is no note
    return line


def fix_long_subject(subject: str, current: str | None = None) -> str:
    """A subject over [subject] max_length, put right instead of refused: cut at the last word that fits with " …" after it, the whole counted in the limit (bullet_text.cut_words: no word is cut in two, the kept
    words and the scope prefix are as written), and the reply says so (call_log.fixed). The subject as given when it fits, when it is the stored text sent back (a long one stored before the limit), when it
    has no scope prefix (the prefix check refuses it as before) or when no word after the prefix fits: the gate then refuses it as before."""
    lim = _subject_max()
    if not lim or len(subject) <= lim or subject == current:
        return subject
    pfx = next((p for p in _cfg.CFG["subject"]["prefixes"] if subject.startswith(p)), None)
    new = _bt.cut_words(subject, lim) if pfx is not None else None
    if not new or not new.startswith(pfx) or len(new) - 2 <= len(pfx.rstrip()):          # the cut fell inside the prefix, or left nothing after it
        return subject
    _calls.fixed("subject-cut", f"the subject was {len(subject)} characters and the limit is {lim}, the scope prefix counted: it was cut at the last word that fits and ends with an ellipsis; to change it, send a shorter subject",
                 fields=["subject"], stored=new, sent=subject)
    return new


def fix_bare_urls(description: str, stored: str | None = None, session: bool = False) -> str:
    """A session's description with a bare http(s) URL in it, put right instead of refused (_gate_bare_urls): each URL the stored description does not already hold is written as a link to itself,
    `[url](url)` (bullet_text.link_bare_urls: the address ends at its last URL character, one inside an angle autolink, a link, a reference definition, an attribute or code is left alone, nothing else changes), and the
    reply says so and shows the addresses (call_log.fixed). The text as given for a script's or the server's own write (not judged), when it holds no new bare URL, when it breaks the description's form for a reason other
    than a long bullet (the line cap, or a line that is no bullet: the gates refuse it, and it is not scanned), or when a URL would still be bare after the change (the gate then refuses it as before). next and ask keep
    their refusal: a link in a step or a question is the writer's to word."""
    if not session or not description:
        return description
    bad = _description_fault(description)
    if bad and bad[0] != "long":
        return description
    old = set(_bt.bare_urls(str(stored or "")))
    if not [u for u in _bt.bare_urls(description) if u not in old]:
        return description
    res = _bt.link_bare_urls(description, old)
    if res is None or res[0] == description:
        return description
    new, linked = res
    if stored is not None and new.strip() == str(stored).strip():          # the same text again, already stored as links: nothing is changed, so nothing is counted or told
        return new
    n = len(linked)
    shown = ", ".join(_clip_line(u, 60) for u in linked[:3]) + (f" and {n - 3} more" if n > 3 else "")
    _calls.fixed("description-url", f"{n} bare address{'' if n == 1 else 'es'} in the description {'was' if n == 1 else 'were'} written as a link to itself, the address as the link's text and target ({shown}): the page links a bare address by its own rule for where it ends, so the link stores the address exactly; "
                 "to give a link words, write `[words](address)`", fields=["description"], stored=new, sent=description)
    return new


def _when_idle() -> str:
    """What a session does about a recycle no item covers, read at use: run [fleet] recycle_when_idle with its reason (the fleet
    tool runs the recycle once the box is idle), or, with no such command configured, nothing: the change waits for the next one."""
    cmd = shlex.join(_cfg.recycle_when_idle())
    return f'run {cmd} "<reason>"' if cmd else "leave it for the next recycle (no idle-recycle command is configured)"


def _fleet_tool() -> str:
    """The fleet tool as the prose names it: [fleet] tool_name, else "the fleet tool"."""
    return _cfg.fleet_tool() or "the fleet tool"


# (a recycle is not an item, a flag does that): a subject whose task is only
# to relaunch or recycle panes or sessions. Its words: relaunch/recycle first, or relaunch/recycle/restart followed by panes,
# sessions or the fleet.
_RECYCLE_ONLY = re.compile(r"^\s*(?:re-?launch|recycle)\b|\b(?:re-?launch|recycle|restart)\s+(?:(?:the|every|all|each)\s+)?"
                           r"(?:claude\s+)?(?:panes?|sessions?|fleet|clis?)\b", re.I)


def _gate_recycle_item(subject: str) -> None:
    rest = subject
    for pfx in _cfg.CFG["subject"]["prefixes"]:
        if rest.startswith(pfx):
            rest = rest[len(pfx):]; break
    if _RECYCLE_ONLY.search(rest):
        raise ToolError("Refused: a recycle is not an item. Flag the item whose change needs it: update(<item>, recycle=true), with the "
                        f"after-recycle check as its next; when no item covers the change, {_when_idle()}")


_visible_len = _bt.visible_len       # what the length count cuts out of a line is bullet_text's (links in all their forms, naked URLs); _RX_LINK_URL, the report note's own, is unchanged


def _bullets_on() -> bool:
    """[description] require_bullets (default true): false switches all of the description strictness off (the bullet and length checks, the next-line refusal, the question route's
    bulleting and clipping, the cold call's re-bulleting) and leaves the line cap, forbid_tokens and [model] description_guard."""
    return bool(_cfg.CFG["description"].get("require_bullets", True))


def _description_limits() -> tuple[int, int]:
    d = _cfg.CFG["description"]
    return int(d.get("max_lines", 8)), int(d.get("line_max", 120))


def _next_line_max() -> int:
    """The longest line of next the write takes: [metadata.next] line_max (200); 0 when the refusal is off (line_max = 0, or require_bullets = false)."""
    return int(_cfg.CFG.get("metadata", {}).get("next", {}).get("line_max", 200)) if _bullets_on() else 0


def fix_list_shape(desc: str, stored: str | None = None, field: str = "description") -> tuple[str, str]:
    """A description (or a close's outcome text, `field="outcome_text"`) with a numbered run written on one bullet line, or a doubled bullet mark, put right instead of stored flat (list_repair.repair: the numbered items each on
    a line of their own, `- - x` as `- x`; nothing else is touched, no word changed), and the reply says so (call_log.fixed, kind list-shape). -> (the text, the History line for the item, "" when the server changed nothing).
    The text as given when it holds neither shape, when no bullet form is required, or (`stored`) when the repaired text is what the item holds already."""
    if not desc or not _bullets_on():
        return desc, ""
    new, doubled, runs = _lr.repair(desc, _description_limits()[0])
    if new == desc or (stored is not None and new.strip() == str(stored).strip()):
        return new, ""
    said = " and ".join(x for x in (f"{runs} numbered run{'' if runs == 1 else 's'} written on one line put on lines of its own" if runs else "",
                                    f"{doubled} doubled bullet mark{'' if doubled == 1 else 's'} made one" if doubled else "") if x)
    _calls.fixed("list-shape", f"the {field}: {said}, no word changed", fields=[field], stored=new, sent=desc)
    return new, f"{field}: {said} by the server"


def fix_long_bullets(desc: str, stored: str | None = None, field: str = "description") -> tuple[str, str]:
    """A description (or a close's outcome text, `field="outcome_text"`) whose bullets read over the limit, put right instead of refused: each long bullet is split at the gaps after its sentences into shorter bullets, a clause
    still over the limit on its own at its last comma, colon, spaced dash or opening parenthesis that leaves each piece within it, and a bullet no such cut splits at its last space that fits, the rest on an indented `- ` line under
    it (bullet_text.split_long_wrap: no word is dropped or cut, nothing is cut inside a link, a naked URL or a code span), and the reply says so (call_log.fixed: kind description-bullet or outcome-bullet for the first
    two cuts, bullet-wrap or outcome-wrap for the last). -> (the text, the History line the caller writes onto the item: the server changed it, "" when it did not). The text as given when it is within the form, when the fault is anything
    but a long bullet, or when the split cannot be made (a piece that is one unbroken token, a bullet with lines indented under it, more lines than the cap): the gate then refuses it as before. A text with no bullet form
    required ([description] require_bullets = false) is left alone. When the split text breaks the form some other way (a later line that is no bullet), the split text comes back with no note and no fix counted, so
    the gate refuses the fault that is left, not a long bullet the server would have put right. `stored` is the text the item holds already (an update passes it): when the split gives exactly that text, the same long
    text has been sent before and is stored as split, so the server changed nothing this time: no fix is counted, no reply line, no History line."""
    if not desc or not _bullets_on():
        return desc, ""
    max_lines, line_max = _description_limits()
    bad = _bt.judge(desc, max_lines, line_max)
    if not bad or bad[0] != "long":
        return desc, ""
    res = _bt.split_long_wrap(desc, max_lines, line_max)
    if not res:
        return desc, ""
    new, n, soft, wrapped = res
    if _bt.judge(new, max_lines, line_max):          # a split that still breaks the form (a later line not a bullet) is no fix: the gate refuses the fault that is left, and nothing is counted or told
        return new, ""
    if stored is not None and new.strip() == str(stored).strip():          # the same long text again, already stored as split: nothing is changed, so nothing is counted, told or noted
        return new, ""
    by_sentence = n - wrapped
    hist: list[str] = []
    if by_sentence:
        where, h_ = ("at the end of a sentence or at a comma, colon, dash or parenthesis", "at the end of a sentence or a comma, colon, dash or parenthesis") if soft else ("at the end of a sentence",) * 2
        kept = "no word changed; a spaced dash at a cut is dropped" if soft else "no word changed"
        _calls.fixed("description-bullet" if field == "description" else "outcome-bullet",
                     f"{by_sentence} {field} bullet{'' if by_sentence == 1 else 's'} over {line_max} characters {'was' if by_sentence == 1 else 'were'} split {where} into shorter bullets, {kept}", fields=[field], stored=new, sent=desc)
        hist.append(f"{field}: {by_sentence} long bullet{'' if by_sentence == 1 else 's'} split by the server {h_}")
    if wrapped:
        _calls.fixed("bullet-wrap" if field == "description" else "outcome-wrap", f"{wrapped} {field} bullet{'' if wrapped == 1 else 's'} over {line_max} characters {'was' if wrapped == 1 else 'were'} cut at a space, the rest on an indented `- ` line under it, no word changed",
                     fields=[field], stored=new, sent=desc)
        hist.append(f"{field}: {wrapped} long bullet{'' if wrapped == 1 else 's'} continued on an indented line by the server, cut at a space")
    return new, "; ".join(hist)


def _step_line_room() -> int:
    """The longest action a split puts on a line of next: [metadata.next] line_max (200), or 300 (the step's own line limit) when that refusal is off."""
    return _next_line_max() or 300


def fix_long_step(step: str) -> tuple[str, list[str]]:
    """A step of his that is a long chain of actions, put into the shape the board draws instead of refused or left unreadable: the step becomes a short summary and each action a line of next that opens with his name
    (step_split.split_step: split at sentence ends, semicolons and inline numbered items, every word kept; a text of more than SPLIT_MAX characters or more than MAX_ACTIONS actions is left as written).
    → (the step to store, the lines to add to next); the step as given and no lines when it is short, already structured, or holds one action. Writes nothing and says nothing: the caller says what it did
    (`say_long_step`) once it knows how many lines it added."""
    got = _ss.split_step(step, _step_line_room())
    if got is None:
        return step, []
    return got


def long_step_skipped(step: str) -> str:
    """Why a one-line step over the step limit was not split into lines ("" when it was, or it is no case for it): the words that go beside its refusal, so the writer knows the server tried."""
    return _ss.skipped(step, _step_line_room())


def say_long_step(step: str, lines: list[str], added: int, settled: int = 0) -> None:
    """The reply's line for a long step that was split into `lines` (call_log.fixed, kind step-split): what was done, or, when `added` is 0 (the summary and every one of its lines are on the item already: the same step
    sent again), that nothing was added. `settled`: how many of the lines were ticked done or dropped before and stay so (they are no open lines on the item, and the reply does not say they are)."""
    open_n = max(0, len(lines) - added - settled)
    acts, lns = (f"{len(lines)} action", f"{len(lines)} line") if len(lines) == 1 else (f"{len(lines)} actions", f"{len(lines)} lines")      # a lead-in with its list is one line
    was = [f"{open_n} of the lines {'was' if open_n == 1 else 'were'} on the item already" if open_n else "", f"{settled} {'was' if settled == 1 else 'were'} done or dropped before and stay so" if settled else ""]
    was_txt = " and ".join(x for x in was if x)
    if added:
        nested = sum(len(x.splitlines()) - 1 for x in lines)      # the items of a list that stand as sub-lines under their lead-in line
        _calls.fixed("step-split", f"the step ran {len(_steps.clean(step))} characters with {acts}, so it was split into a summary and {lns} of next that open with {OWNER}'s name, "
                     "which the board draws as his list; every word is in a line" + (f"; the {nested} items of a list stand as indented sub-lines under their lead-in line, ticked with it" if nested else "")
                     + ("" if added == len(lines) else f" ({was_txt}, so {added} were added)"), fields=["step", "next"])
    elif settled:
        _calls.fixed("step-split", f"the step ran {len(_steps.clean(step))} characters with {acts}: it is stored as a summary, and of its {lns} {was_txt}, so nothing was added", fields=["step"])
    else:
        _calls.fixed("step-split", f"the step ran {len(_steps.clean(step))} characters with {acts}: it is stored as a summary, and its {lns} of next {'is' if len(lines) == 1 else 'are'} on the item already, so nothing was added",
                     fields=["step"])


def fix_long_owner_lines(next_: str, known: set[str]) -> str:
    """The lines of next that open with the owner's name and run long with several actions, one line per action (step_split.split_line), the other lines as they are, and the reply says so (call_log.fixed).
    A line that is an open step already (`known`: its steps.key) or one whole command in backticks is left as it stands, and so is a line that has sub-lines under it (the writer's own shape). A lead-in that ends with
    a colon, followed by `1) … 2) …`, is one line with its items as indented sub-lines (step_split). The text as given when no line is split."""
    if not next_ or not str(next_).strip():
        return next_
    room, out, n_in, n_out = _step_line_room(), [], 0, 0
    for entry in _nl.split(next_):
        first = entry.split("\n", 1)[0]
        parts = None if _steps.key(entry) in known or _owner_command(first) else _ss.split_line(entry, room)
        if parts:
            out.extend(parts)
            n_in, n_out = n_in + 1, n_out + len(parts)
        else:
            out.append(entry)
    if not n_in:
        return next_
    _calls.fixed("step-split", f"{n_in} line{'' if n_in == 1 else 's'} of next that open{'s' if n_in == 1 else ''} with {OWNER}'s name held several actions, so {'it was' if n_in == 1 else 'they were'} split into {n_out} lines, "
                 "one per action; every word is in a line", fields=["next"])
    return "\n".join(out)


def _description_fault(desc: str) -> tuple[str, str, int] | None:
    """The first fault of a description's form (bullet_text.judge; with [description] require_bullets = false the line cap alone), None when it keeps it."""
    max_lines, line_max = _description_limits()
    return _bt.judge(desc, max_lines, line_max) if _bullets_on() else (("lines", "", n) if (n := len([ln for ln in desc.splitlines() if ln.strip()])) > max_lines else None)


def _lines_once_split(desc: str, max_lines: int, line_max: int) -> int:
    """The non-blank lines a description with a long bullet would have once the server split it, when that count alone is why it was not split (more than max_lines); else 0. Looked for up to three times the cap, which also bounds the work."""
    res = _bt.split_long_wrap(desc, 3 * max_lines, line_max)
    made = len([ln for ln in res[0].splitlines() if ln.strip()]) if res else 0
    return made if made > max_lines else 0


def description_faults(desc: str, field: str = "description") -> list[str]:
    """Every fault of a description's form, each as the refusal `_gate_description` raises for it alone: the form of its lines (the first bullet or line that breaks it) and, for a description, a forbidden word.
    A description is short `- ` bullets, one fact each, refused at write time and not only noted. Checks the text
    written in this call and nothing stored (the callers pass it only when the write carries a description, a close included). The judgement is
    bullet_text.judge, which the re-bullet pass uses too: at most [description] max_lines non-blank lines, each a `- ` bullet (a dash and spaces or a tab; an
    indented bullet is a bullet, an indented line that is not one is prose) of at most line_max characters as it reads (a link by its text, its destination in any
    form and a naked URL not at all). A `>` quote line is exempt from the marker but not the length, a fenced block (fence lines included) from both; all count toward
    max_lines. The question route and the cold call's close write bullets themselves and go through this gate like any create. [description] require_bullets = false
    leaves the line cap and the forbidden tokens only. `field` names the text in a refusal. The outcome text of a close (`outcome_text`) is held to the same form and length but may say
    what was resolved or done, so it skips the forbidden tokens, which keep a description from reading as a changelog."""
    d = _cfg.CFG["description"]
    max_lines, line_max = _description_limits()
    fix = f"write short `- ` bullets, one fact each (at most {max_lines} lines of {line_max} characters; parallel bullets such as batches, steps or parts go under one parent bullet, indented two spaces); details go on the project page"
    out: list[str] = []
    bad = _description_fault(desc)
    if bad:
        kind, ln, n = bad
        if kind == "lines":      # nested bullets count toward the cap too, so the way down is fewer facts or more per bullet, never a parent bullet
            out.append(f"Refused: {field} has {n} lines, the limit is {max_lines}: cut {n - max_lines} (merge related facts into one bullet, or move detail to the project page); "
                       f"accepted form: `- Goal: <the result you want>` then short `- ` bullets, one fact each, at most {line_max} characters, {max_lines} lines in all, nested ones counted")
        elif kind == "marker":
            out.append(f"Refused: {field} line is not a `- ` bullet: \"{_clip_line(ln, 60)}\"; {fix}")
        elif made := _lines_once_split(desc, max_lines, line_max):
            out.append(f"Refused: {field} bullet is {n} characters, the limit is {line_max} (a link's URL does not count): \"{_clip_line(ln, 60)}\"; the server splits a long bullet by itself while the result stays within "
                       f"{max_lines} lines, and here it would make {made}: cut {made - max_lines} line{'' if made - max_lines == 1 else 's'} (merge or drop facts, shorten the long bullets, or move detail to the project page) and send the call again; {fix}")
        else:
            out.append(f"Refused: {field} bullet is {n} characters, the limit is {line_max} (a link's URL does not count): \"{_clip_line(ln, 60)}\"; the server splits a long bullet at a sentence end or a space by itself, "
                       f"and could not split this one (no ordinary space to cut at within a line: a word or link longer than a line, or text spaced only with non-breaking or wide spaces; a bullet with lines indented under it, or more than {max_lines} lines once split); {fix}")
    if field != "description":
        return out
    low = desc.lower()
    for tok in d.get("forbid_tokens", []):
        if tok.lower() in low:
            at = next((ln for ln in desc.splitlines() if tok.lower() in ln.lower()), "")
            out.append(f"Refused: description contains {tok!r} — a description is the live state, never a changelog, so {tok!r} may not appear anywhere in it, in any case, even inside a longer word: \"{_clip_line(at, 60)}\". Write the state instead, e.g. `- PR 12 is merged and live`, not `- Done: PR 12 merged`")
            break
    return out


def _gate_description(desc: str, field: str = "description") -> None:
    """Refuse a description that breaks the form (every fault of it, together; `description_faults` has them as a list)."""
    if got := description_faults(desc, field):
        raise _faults.refusals(got)


_GOAL_RETRY = (" Retry the call with the description's first bullet changed; a session whose tool list was cached before this rule reads the live text through the MCP Portal "
               "(portal_codemode_execute with codemode.stackshot_create or codemode.stackshot_update), and a relaunch does not refresh it.")


def fix_goal_label(desc: str, stored: str = "") -> str:
    """A session's description whose first `- ` bullet opens with a goal word in another form (`goal: x`, `Goal - x`, `GOALS: x`, a bold label, the Korean word for it), put right instead of refused: the bullet is written
    `- Goal: x` (bullet_text.relabel_goal: the words after the label and every other line are as written) and the reply says so (call_log.fixed). The text as given when it opens with `Goal:` already, when its first bullet
    opens with anything else (the gate then refuses it and shows the description with that bullet as the goal) or holds a label and nothing after it. The callers run it where `_gate_goal` would judge the text.
    [description] require_bullets = false switches it off with the other form checks. `stored` is the description the item holds (an update): a text that is the stored one once relabelled is no fix."""
    if not desc or not _bullets_on():
        return desc
    res = _bt.relabel_goal(desc)
    if res is None:
        return desc
    new, label = res
    if stored.strip() and new.strip() == stored.strip():
        return new          # the stored text with only its label written otherwise: the write changes nothing, so no fix is counted or told
    _calls.fixed("description-goal", f"the description's first bullet opened with \u201c{label}\u201d and is stored as `- Goal: ...`, the words after it as you wrote them; to change the goal, send the description with the first bullet you want",
                 fields=["description"], stored=new, sent=desc)
    return new


def _sendable(desc: str) -> bool:
    """Would `desc` pass the form gate as sent: within the line cap and the bullet length, or after the bullet fix (`fix_long_bullets`) has split what it can. Nothing is counted or noted."""
    max_lines, line_max = _description_limits()
    if not _bt.judge(desc, max_lines, line_max):
        return True
    res = _bt.split_long_wrap(desc, max_lines, line_max)
    return bool(res) and not _bt.judge(res[0], max_lines, line_max)


def goal_fault(desc: str) -> str:
    """The refusal text `_gate_goal` raises for `desc`, "" when the description opens with its goal (or the form checks are off). A session's new description, or one it rewrites, opens with the goal: the first `- ` bullet starts `Goal:` (case-sensitive, right after the dash) and says the finished outcome;
    a symptom, cause or trigger goes in a later bullet that opens `Problem:`. Why: an item once carried a title and bullets that described the trouble and never said what result was wanted.
    Judged on the text written in the call only (the callers run it for a session's create and for an update that replaces the description with other text), after the form gate.
    The first bullet is the first `- ` line (bullet_text.first_bullet); a description with no bullet is refused the same way. [description] require_bullets = false switches it off with the other form checks."""
    if not _bullets_on() or _bt.goal_of(desc) is not None:
        return ""
    first = _bt.first_bullet(desc)
    saw = f"the first bullet starts “{_clip_line(' '.join(first.split()[:6]), 60)}”" if first is not None else "it has no `- ` bullet"
    ex = _bt.goal_example(desc)
    if ex is not None and not _sendable(ex):      # a corrected description the form gate would refuse again is no example to copy
        ex = None
    shown = (f" Send the description again with that bullet as the goal:\n{ex}\n" + "If that bullet names a symptom, a cause or a trigger, write the finished outcome as the goal and move the bullet to a later bullet that opens `Problem:`.") if ex else ""
    return (f"Refused: the description must open with its goal, and {saw}.{shown} The subject names the work that closes the item and the first bullet the finished outcome it reaches: `- Goal: <the result you want, in a sentence>`; "
                    "a symptom, a cause or a trigger goes in a later bullet that opens `Problem:`. "
                    "Example: the symptom title “X fails when Y” becomes the task title “Make X work when Y”, with `- Goal: X works when Y` as the first bullet "
                    "and `- Problem: X fails when Y` as the second. `Goal:` is case-sensitive and sits right after the dash." + _GOAL_RETRY)


def _gate_goal(desc: str) -> None:
    """Refuse a description that does not open with its goal (`goal_fault` has the rule and the text)."""
    if why := goal_fault(desc):
        raise ToolError(why)


def bare_url_faults(fields: dict[str, str], stored: dict[str, Any] | None = None, session: bool = False) -> list[str]:
    """One refusal text per field that holds a bare URL (the first in it), none when the write is no session's. A session's write through the create and update tools (`session`: the per-write flag the caller reads) may not put a bare http(s) URL in description, next or ask: the page does not always draw one as a
    link, so a reader sees plain text. A URL inside `[words](url)`, a code span or a fenced block is fine. Judges the text written in this call, `fields` by name, and of that only a URL
    the stored text of the field (`stored`, an update's) does not already hold, so an update that sets a field again with an old bare URL in it is not refused for that. Scripts and the
    server's own writes are not judged. How a page draws a bare URL is not changed here."""
    out: list[str] = []
    if not session:
        return out
    for field, text in fields.items():
        if not text:
            continue
        old = set(_bt.bare_urls(str((stored or {}).get(field) or "")))
        for url in _bt.bare_urls(text):
            if url not in old:
                out.append(f"Refused: {field} has a bare URL ({_clip_line(url, 80)}) and the page may not draw it as a link. Write it as `[words](url)`, the words saying what the link opens "
                           "(a URL in a code span or a fenced block is fine)")
                break
    return out


def _gate_bare_urls(fields: dict[str, str], stored: dict[str, Any] | None = None, session: bool = False) -> None:
    """Refuse a bare URL in a session's description, next or ask (every field that has one, together; `bare_url_faults` has them as a list)."""
    if got := bare_url_faults(fields, stored, session):
        raise _faults.refusals(got)


def _owner_command(line: str) -> bool:
    """`<owner>: `a command in backticks``: the line the owner runs, whole in one backtick span (the form docs/configuration.md shows); prose after the name is not one."""
    return re.fullmatch(rf"{re.escape(OWNER)}:\s*`[^`\n]+`[.,;]?", line.strip(), re.I) is not None


NEXT_LONG_SHOWN = 3         # a next with more long lines than this names the first few and counts the rest
NEXT_PREFIX_ROOM = 80       # a line of next may be this many characters longer than [metadata.next] line_max in all: room for its `<actor>: ` prefix (the whole-line cap is line_max + 80, 280 by default)


def _next_len(line: str) -> int:
    """The length a line of next counts for the limit ([metadata.next] line_max): the characters after its `<actor>: ` prefix (the text up to and including the first colon-space that names the
    actor, as the actor check reads it: `my-x (builder): `, a list marker or bold marks in front of it), so that a long session name costs the action no room; a link counts by its text and a naked
    URL not at all (_visible_len). A line with no recognizable prefix counts whole."""
    s = line.strip()
    c = _mg._MARK_RX.sub("", s.replace("**", ""))
    m = _mg._NAME_RX.match(c)
    if not m or _mg.not_actor(m.group("name")):         # `Status:` and the like name no one
        return _visible_len(line)
    target = len(s.replace("**", "")) - len(c) + m.end()        # the characters of s, bold marks aside, that the prefix (marker and spaces in front of it included) takes
    i, seen = 0, 0
    while i < len(s) and seen < target:
        if s.startswith("**", i):
            i += 2
            continue
        i += 1
        seen += 1
    return _visible_len(s[i:])


def next_faults(next_: str, has_ask: bool = False, session: bool = False) -> list[str]:
    """Every fault of the text of next, each as the refusal `_gate_next` raises for it alone: the lines that name no one (one fault for all of them) and each line over the limit. a `next` line over [metadata.next] line_max (200; 0 = off) characters is refused, where it used to be noted. Checks only the text written
    in this call. A link counts by its text and a naked URL not at all, as in a description. Not judged: a `<owner>: `command`` line (the
    whole command in one backtick span; any other line of his is prose and counts), and next's first non-blank line when it is an ask line and
    the call passes no `ask` (a client without the ask parameter writes the ask there; the server lifts it). Hashes, test counts and past
    tense stay notes (_report_note). (a session's write through the create and update tools only, `session`): a line that opens with no `<actor>:` is refused, naming the line and the fix; a sub-line under a named step is fine."""
    out: list[str] = []
    if session and (bad := _nr.unnamed(next_, skip_first=None if has_ask else (lambda ln: _rmod.parse_ask(ln) is not None))):
        out.append(f"Refused: a line of next names no one: \"{_clip_line(bad[0], 60)}\"" + (f" (and {len(bad) - 1} more)" if len(bad) > 1 else "") + (f" ({h})" if (h := _nr.hint(bad[0])) else "") + f". One step is one action with one named actor: {_nr.FIX}. "
                   "A line under a step that belongs to it starts with `- `; results go on the project page (Current state or a timeline line), never into next")
    limit = _next_line_max()
    if not limit:
        return out                   # off: [metadata.next] line_max = 0, or [description] require_bullets = false (then _report_note notes a long line again)
    first = True
    long_: list[str] = []
    long_more = 0
    for raw in str(next_ or "").splitlines():
        ln = re.sub(r"^\s*(?:[-*\u2022]\s+)?", "", raw)
        if not ln.strip():
            continue
        lifted, first = first and not has_ask and _rmod.parse_ask(ln.strip()) is not None, False
        if lifted or _owner_command(ln):
            continue
        fault = ""
        if (n := _next_len(ln)) > limit:
            fault = (f"Refused: a line of next is {n} characters after its `<actor>: ` prefix, the limit is {limit} (a link's URL does not count): \"{_clip_line(ln, 60)}\"; "
                     f"cut it by {n - limit} character{'' if n - limit == 1 else 's'}: next is one short line per next action, each naming who takes it, e.g. `my-x: merge PR 12 once CI is green`; results and detail go on the project page (Current state or a timeline line)")
        elif (whole := _visible_len(ln)) > limit + NEXT_PREFIX_ROOM:         # the prefix is a name of up to three words of any length: the line as a whole is capped too
            fault = (f"Refused: a line of next is {whole} characters in all, the limit for the whole line is {limit + NEXT_PREFIX_ROOM} (the {limit} counts after its `<actor>: ` prefix, which has {NEXT_PREFIX_ROOM} characters of room; "
                     f"a link's URL does not count): \"{_clip_line(ln, 60)}\"; next is one short line per next action, each naming who takes it, with a short name; results and detail go on the project page (Current state or a timeline line)")
        if fault and len(long_) < NEXT_LONG_SHOWN:
            long_.append(fault)
        elif fault:
            long_more += 1
    if long_more:
        long_[-1] += f" (and {long_more} more line{'s' if long_more > 1 else ''} over the limit)"
    return [*out, *long_]


def _gate_next(next_: str, has_ask: bool = False, session: bool = False) -> None:
    """Refuse a text of next that breaks its form (every fault of it, together; `next_faults` has them as a list)."""
    if got := next_faults(next_, has_ask, session):
        raise _faults.refusals(got)


def _require_marks() -> bool:
    """[metadata.next] require_marks (default true): a write of next that leaves out an open step of the writer's without marking it done, dropped or reworded keeps the step open (the update carries its line over and the reply says so; a line rewritten with words added is refused). false is the way back: the step reads as dropped, with nobody and no time."""
    return bool(_cfg.CFG.get("metadata", {}).get("next", {}).get("require_marks", True))


def _marks_given(v: Any) -> bool:
    """Does a `done` or `dropped` argument name a step? A list with an entry, a position (any number, so that 0 is refused as no step), or text."""
    if isinstance(v, bool) or v is None:
        return False
    if isinstance(v, int):
        return True
    return bool(v if isinstance(v, (list, tuple)) else str(v).strip())


def _nl_text_without(meta: dict[str, Any], texts: list[str], keeper: str) -> str:
    """The item's next as it reads once the lines `texts` are taken out of it (nextlines.prune on a copy): what the checklist is lined up with."""
    probe = json.loads(json.dumps(meta))
    _nl.prune(probe, texts, keeper)
    return str(probe.get("next") or "")
