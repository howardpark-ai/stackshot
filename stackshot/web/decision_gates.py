"""decision_gates.py: what the ask and the options of a needs=decision item may say. The write gates that refuse an ask naming alternatives while no options are listed, an open
question with no options, a mockup linked outside the ask, several decisions in one ask, and the owner's own action put as a decision, and the two notes a write's reply may end with
(the Recommend part that names no option, an option or ask that says "you" without naming who acts).

Each is a pure function of the item's metadata (and the description) that raises ToolError with the refusal, or returns the note; none reads the store or changes anything. server.py
imports every name from here and keeps it on its own module as well, so the writes and the tests reach them as `server.<name>`. `_gate_options`, the shape of options=[...], stays in
server.py: it also reads `_shown_ids`, which looks an item up in the store."""
from __future__ import annotations

import re
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core import config as _cfg
from stackshot.model import ask_read as _ar
from stackshot.model import nextlines as _nl
from stackshot.model import owner_steps as _hs
from stackshot.model import steps as _steps
from stackshot.waits import watchers as _watch
from stackshot.web import render as _rmod
from stackshot.web.common import OWNER, _clip_line, _needs_kinds

_OPT_FORM = (f'options=[{{"label": "<a short name>", "line": "<one sentence, at most {_rmod.OPTION_LINE_MAX} characters>", "recommended": true}}, '
             f'{{"label": …, "line": …, "recommended": false}}, …] ({_rmod.OPTIONS_MIN}–{_rmod.OPTIONS_MAX} entries, exactly one recommended)')
_OPT_RELAUNCH = (" If this tool shows no options parameter, this session's cached tool list predates it: claude.ai refreshes it on its own "
                 "within about a day, and a relaunch does not. Meanwhile write through the Portal connector: portal_codemode_execute with "
                 "codemode.stackshot_update({item_id, options, ask}) (or codemode.stackshot_create).")


# The matchers that name alternatives live in ask_read.py (the audit reads asks with the same ones).
_lettered_alternatives = _ar.lettered_alternatives
_alternatives = _ar.alternatives


def _gate_alternatives(meta: dict[str, Any], description: str) -> None:
    """Refuse a needs=decision item whose ask or description names alternatives while it lists no options."""
    if "decision" not in _needs_kinds(meta) or meta.get("options"):
        return
    hit = _alternatives(meta, description)
    if hit:
        raise ToolError(f"Refused: this needs=decision item names alternatives (\u201c{hit}\u201d) in its ask or description but lists no options. "
                        f"Put each alternative in as one option so {OWNER} reads them on the item and the page draws a card for each, not a bare Yes / No: {_OPT_FORM}, and name the recommended one's label in the ask's Recommend part, or reword the ask so it names no alternatives (a yes/no: \u201cDecide: whether to \u2026\u201d). "
                        f"A yes/no decision lists two options, \u201cApprove\u201d and \u201cDecline\u201d (the one you recommend marked recommended), so {OWNER} gets one-click buttons; an open question (what, which, how, who, when, where, why) lists its answers as options too, or is reworded as a yes/no." + _OPT_RELAUNCH)


# An open question as the Decide part of an ask with no options. The item page draws Yes / No when the item lists none, and Yes / No cannot answer "which layout the
# page uses": the owner would have to write the answer in a box, and a Recommend that answers a different question reads as a mistake. So a needs=decision item with no options
# is refused when its Decide part begins with an interrogative word (after "Decide:", ignoring a leading quote or bracket). The matcher is narrow: only the word that opens the
# question counts, so "whether", "should", "is", "do", "can" and "if" (yes/no frames) pass, and so does a Decide part that holds "what" later ("whether what we shipped is enough").
# A Decide part that names alternatives ("ship X now or hold") is _gate_alternatives's.
_decide_of = _ar.decide_of
_open_question = _ar.open_question


def _gate_open_question(meta: dict[str, Any]) -> None:
    """Refuse a needs=decision item that lists no options while the Decide part of its ask is an open question: the page would draw Yes / No under it."""
    if "decision" not in _needs_kinds(meta) or meta.get("options") or _watch.asked_of(meta):
        return
    decide = _open_question(meta)
    if not decide:
        return
    raise ToolError(f"Refused: this needs=decision item lists no options and its Decide part is an open question (\u201c{_clip_line(decide, 90)}\u201d). "
                    f"The item page would show Yes / No under it, which cannot answer it. "
                    f"Give {_rmod.OPTIONS_MIN}\u2013{_rmod.OPTIONS_MAX} options, each an answer {OWNER} could pick, exactly one recommended, and name the recommended option's label in the ask's Recommend part: {_OPT_FORM}. "
                    "Or reword the Decide part as a yes/no (pass ask=\u201cDecide: whether to \u2026 \u00b7 Recommend: yes or no \u00b7 Stakes: \u2026 \u00b7 By: \u2026\u201d on the update) with a Recommend part that answers yes or no." + _OPT_RELAUNCH)


# ----------------------------------------------------------------------------- a design decision's mockup rides on the ask
# A needs=decision item whose text links a mockup (a claude.ai artifact page or a fleet tool's /mockup/<n> page) carries that link on the ask, the line the owner answers, and not only in the
# background: the home row and the item page draw "Mockup \u2197" beside the question (render.mockup_url), and an ask with no link leaves him to hunt for it.
_MOCKUP_ASK = "[mockup](<the mockup link>)"


def _gate_mockup(meta: dict[str, Any], description: str) -> None:
    """Refuse a needs=decision item whose description, next or options name a mockup link (a claude.ai artifact page or a /mockup/<n> page) while its ask names none."""
    if "decision" not in _needs_kinds(meta) or _rmod.mockup_hit(meta.get("ask")):
        return
    opts = " ".join(f'{o.get("label") or ""} {o.get("line") or ""}' for o in meta.get("options") or [] if isinstance(o, dict))
    for where, text in (("description", description), ("next", str(meta.get("next") or "")), ("options", opts)):
        hit = _rmod.mockup_hit(text)
        if hit:
            raise ToolError(f"Refused: this needs=decision item links a mockup ({hit}) in its {where} but not in its ask. "
                            f"Put {_MOCKUP_ASK} in the ask's Decide part, so {OWNER} opens the design from the question he answers: "
                            f"ask=\"Decide: <what to decide> {_MOCKUP_ASK} \u00b7 Recommend: \u2026 \u00b7 Stakes: \u2026 \u00b7 By: \u2026\" (\u2264 {_rmod.ASK_MAX} chars, the link counted).")


# ----------------------------------------------------------------------------- one decision per item
# An item once carried three decisions in one ask, with the options only in a chat ("Decide: … and choices 2-3 · Recommend:
# …, 2b …, 3a …"). A decision ask is written so that he can decide from the item page alone, without hunting for what the choices are or asking a front agent:
# one decision per item, each option in words. _alternatives (above) only fires when the ask says "options"/"alternatives" outright, so
# an ask that pointed at "choices 2-3" or "2b" slipped through. Two refusals, applied only when an ask is being written or changed:
#   1. the ask packs several decisions: more than one Decide: or Recommend: label, a Decide part joined by " · " or ";", "and choices"
#      (also options, alternatives, decisions) followed by a number or code in the Decide part, or a Recommend part cut by " · " (a ";" in a Recommend is common in one decision). A single decision that merely says
#      "and" in its options ("A and B together, or C") passes.
#   2. the ask refers to choices by a code the item does not spell out: "choice(s) / option(s) / alternative(s) / variant(s)" followed by a
#      number or a capital letter A-F (2-3, 1/2, A and B), a bare single digit with a lowercase a-c ("2b", "3a"), or two "(a)" / "(1)" tags.
#      A code is spelled out when the ask, the description or an option has it followed by a colon, an equals sign, a spaced dash or a
#      bracket and words ("2b = plugins on one lane only", "A: …", "(a) Figma only").
# The bare-code form is kept to one digit and a, b or c on purpose, and not after a word character, #, $, a dot, a dash or a slash,
# nor after step, section, fig, room or at, nor before "model", so that dates, versions (1.2.3), ids (#7),
# sizes (2GB, 16px, 4K, 7b model), times (5m, 10am) and 2d/3d pass; after choice/option a code is a number with an optional a-c ("option 1 year",
# "options 2x faster", "choice 3D printer" pass). A ";" splits a Decide only when whitespace follows it (not in a URL, an &entity; or a quotation).
_CODE_ID = r"(?:\d{1,2}(?:[a-c]\b)?|(?-i:[A-F]))"
_CODE_REF_RX = re.compile(r"\b(?:choices?|options?|alternatives?|variants?)\s+#?(" + _CODE_ID + r"(?:\s*(?:[-–/,&]|\band\b|\bor\b|\bto\b)\s*" + _CODE_ID
                          + r")*)(?![\w-])", re.I)
_CODE_BARE_RX = re.compile(r"(?<![\w#$.\-/])(\d[a-c])(?!\w)(?!\.\d)(?!\s+(?:model|params?|parameters?|weights?)\b)")
_CODE_BARE_AFTER = re.compile(r"\b(?:steps?|sections?|figs?\.?|rooms?|at)\s+(?:\d[a-c]\s*(?:[,/&-]|\band\b|\bor\b)\s*)*$", re.I)   # "Step 2b", "section 3a", "Fig. 2a", "room 1a", "at 2b": not a choice
_CODE_UNIT_RX = re.compile(r"\s*(?:%|(?:years?|months?|weeks?|days?|hours?|minutes?|seconds?|mins?|secs?|percent|times?|points?|gb|mb|kb)\b)", re.I)   # "option 1 year"
_CODE_PAREN_RX = re.compile(r"\(\s*([a-fA-F]|[1-6])\s*\)")
_MANY_DECISIONS_RX = re.compile(r"\band\s+(?:the\s+)?(?:choices?|options?|alternatives?|decisions?)\s+(?:#?\d|\(|(?-i:[A-F]\b))", re.I)   # "and choices 2-3", not "and options stay"
_URL_ENTITY_RX = re.compile(r"https?://\S+|&#?\w+;|\"[^\"]*\"|“[^”]*”")


def _code_defined(code: str, text: str, listing: str = "") -> bool:
    """True when `text` (or `listing`, the description and the options, for a "1. words" line) spells the code out: "2b = …", "A: …", "(a) …",
    "A) …", "2b - …", "A (words", "A, words", "A is …", "A means …", "**A**: …", and in `listing` "A. words"."""
    c = re.escape(code)
    lb = r"(?<![\w#$.\-/(])(?:(?:choice|option|alternative|variant)s?\s+)?"
    if re.search(r"(?<![\w#$.\-/])\(" + c + r"\)(?=\s+(?!(?:or|and|vs)\b)[^\s/\u00b7])|"
                 + lb + c + r"\)(?=\s+[^\s/\u00b7])|" + lb + c + r"\s*[:=]|" + lb + c + r"\s+[-–—→]\s|"
                 + lb + c + r"\s*\(\s*(?![a-fA-F1-6]\s*\))[^\s)]|" + lb + c + r",\s+(?!(?:or|and)\b|[A-F]\b)(?=[^\W\d])|"
                 + lb + c + r"\s+(?:is|means)\b|\*\*" + c + r"\*\*\s*[:.\-–—)]?\s*\S", text, re.I):
        return True
    return bool(re.search(lb + c + r"\.\s+\S", listing, re.I))


def _one_decision_kind(meta: dict[str, Any], description: str) -> tuple[str, str]:
    """How an ask breaks "one decision per item, options in words": ("many", why) for several decisions, ("code", why) for choices pointed at by a
    code the item does not spell out, ("", "") when it does not."""
    ask = str(meta.get("ask") or "")
    if not ask.strip():
        return "", ""
    pa = _rmod.parse_ask(ask) or {}
    decide, rec = pa.get("decide", ask), pa.get("recommend", "")
    if len(re.findall(r"\bDecide:", ask)) > 1 or len(re.findall(r"\bRecommend:", ask)) > 1:
        return "many", "has more than one Decide or Recommend part, so it asks several decisions"
    for part, label, seps in ((decide, "Decide", (" · ", ";")), (rec, "Recommend", (" · ",))):   # a ";" in a Recommend is common in one decision ("run it; the wake keeps it fresh")
        bare = _URL_ENTITY_RX.sub("", part)      # a ";" inside a URL or an entity, or at the very end, is no split
        for sep in seps:
            if (re.search(r";\s+\S", bare) if sep == ";" else sep in part):
                return "many", f"has a {label} part split by “{sep.strip()}”, so it asks several decisions"
    m = _MANY_DECISIONS_RX.search(decide)
    if m:
        return "many", f"asks several decisions in one (“{m.group(0)}”)"
    opt_text = " ".join(f"{o.get('label', '')}: {o.get('line', '')}" for o in meta.get("options") or [] if isinstance(o, dict))
    known, listing = f"{ask}\n{description or ''}\n{opt_text}", f"{description or ''}\n{opt_text}"
    codes: dict[str, str] = {}
    for m in _CODE_REF_RX.finditer(ask):
        if _CODE_UNIT_RX.match(ask, m.end(1)):
            continue
        for cd in re.findall(_CODE_ID, m.group(1)):
            codes.setdefault(cd.lower() if cd[0].isdigit() else cd, m.group(0))
    for m in _CODE_BARE_RX.finditer(ask):
        if not _CODE_BARE_AFTER.search(ask[:m.start()]):
            codes.setdefault(m.group(1), m.group(0))
    tags = {t.lower(): t for t in _CODE_PAREN_RX.findall(ask)}
    if len(tags) >= 2:
        for t in tags:
            codes.setdefault(t, f"({tags[t]})")
    for cd, hit in codes.items():
        if not _code_defined(cd, known, listing):
            return "code", f"refers to its choices by a code the item does not spell out (“{hit}”)"
    return "", ""


def _one_decision(meta: dict[str, Any], description: str) -> str:
    """Why an ask breaks "one decision per item, options in words", as a phrase for the refusal; "" when it does not."""
    return _one_decision_kind(meta, description)[1]


def _gate_one_decision(meta: dict[str, Any], description: str, lifted: bool = False) -> None:
    """Refuse an ask that is being written when it asks more than one decision or points at choices by an undefined code.
    `lifted`: the ask came from the first line of next, which the reply says."""
    kind, why = _one_decision_kind(meta, description)
    if not kind:
        return
    src = " (lifted from next's first line)" if lifted else ""
    if kind == "many":
        raise ToolError(f"Refused: this ask{src} {why}. One decision per item, so that {OWNER} can decide from the item page alone: split it into one item "
                        "per decision, and write each option out in words in the ask or the description (or list them with options=[…]).")
    raise ToolError(f"Refused: this ask{src} {why}. {OWNER} must be able to decide from the item page alone: write each option out in words in the ask or the "
                    "description (or list them with options=[…]), or define each code in the ask or description, e.g. ‘A: …’ or ‘2b = …’.")


# ----------------------------------------------------------------------------- his own step is not a decision
# Sessions put the owner's own action to him as a decision: needs=decision with an ask such as "have you done the two GitHub steps?" and Yes/No
# options, and his Yes was then read as consent instead of as the step being done. The board has a step for that: step=<his
# action>, which the board ticks when he says it is done. A decision is a choice he makes; a step is something he does. The rule: refuse only when
# the ask's question is his own action, read from his own next lines; when in doubt, accept. Refused, when needs holds decision and its ask,
# options or next are being written:
#   1. an ask whose Decide part only confirms his own action: "did/have/has you (or he, or his name) done/run/set/…" with a doing verb (a judgement
#      such as decided, chosen, agreed, reviewed, changed, moved, accepted is not one, nor is "changed your mind", "moved on from", "run into",
#      "come up with"), or a bare "is it/that/this done?" / "are they/both done?" (also finished, complete, set up, in place) that ends right after
#      the match ("is this done to your liking", "is it complete enough to send" are judgements). Skipped when the item lists options that name
#      alternatives, when its options are Approve/Decline (a go-ahead is a decision), when the Decide part names an alternative anywhere ("or",
#      "should we", "may I", "which"), carries a judgement qualifier (enough, to your liking, right, good, fine, ok, look, work for you) or has a
#      second clause ("… and does it work", "… and is it fine");
#   2. options that are Yes/No (also Done/Not yet), Approve/Decline, or none, when the Decide part names one or more `<owner>:` lines of next a
#      session wrote (the server's own step for the ask does not count) and is mostly their words: a line is named when the ask holds its
#      leading verb and at least one more of its words ("Decide: install the apps and delete the test repo?" over "<owner>: install the apps" and
#      "<owner>: delete the test repo"; "Send the email to the vendor now?" over "<owner>: read the vendor draft email" is a decision: read is not send).
# A write that only changes next is judged by rule 2 alone: an ask left as it was is refused only when a next line is the action it confirms.
# A real choice is never refused: options that name alternatives, or an open question that lists its options ("which …", "should we …"; without options the open-question gate refuses it).
_OWN_VERBS = (r"(?:do(?:ne)?|run|ran|set|made|finish(?:ed)?|complete(?:d)?|create(?:d)?|add(?:ed)?|install(?:ed)?|enable(?:d)?|connect(?:ed)?|"
              r"click(?:ed)?|push(?:ed)?|sign(?:ed)?|sen[dt]|upload(?:ed)?|configure(?:d)?|appl(?:y|ied)|follow(?:ed)?|merge(?:d)?|turn(?:ed)?|"
              r"switch(?:ed)?|update(?:d)?|cop(?:y|ied)|paste(?:d)?|log(?:ged)?|register(?:ed)?|"
              r"put|restart(?:ed)?|rotate(?:d)?|revoke(?:d)?|delete(?:d)?|remove(?:d)?|"
              r"open(?:ed)?|check(?:ed)?|verif(?:y|ied)|test(?:ed)?|fill(?:ed)?|paid|pay|book(?:ed)?|order(?:ed)?|renew(?:ed)?)")
_OWN_DONE = r"(?:all\s+)?(?:done|finished|complete(?:d)?|set\s+up|in\s+place|through)"
_OWN_JUDGE_RX = re.compile(r"\benough\b|\bto\s+your\b|\bliking\b|\bright\b|\bgood\b|\bfine\b|\bok(?:ay)?\b|\blooks?\b|\bwork(?:s|ed)?\s+for\s+you\b|"
                           r"\band\s+(?:does|do|did|is|are|has|have|was|were)\b", re.I)   # a judgement qualifier or a second clause: rule 1 does not apply
_OWN_NOT_DO = r"(?!\s+(?:your\s+mind|on\s+from|into|up\s+with)\b)"   # "changed your mind", "moved on from", "run into", "come up with" are not steps
_OWN_END = r"\s*[?.!]*\s*$"                                        # "is it done?" ends right after the match
_OPEN_Q_RX = re.compile(r"\b(?:which|what|how|when|where|who)\b|\bshould\s+(?:we|i|it|they|the|this|that|[\w-]+)\b", re.I)
_OWN_ALT_RX = re.compile(_OPEN_Q_RX.pattern + r"|\bor\b|\bmay\s+i\b", re.I)   # an alternative named anywhere in the Decide part
_OWN_STOP = frozenset("the and for with from into onto over this that these those his her its our your their both all two three now yet then also "
                      "has have had did does you him she they them whether please today tonight first next new".split())
_OWN_MATCH_SHARE = 0.6   # rule 2: this share of the Decide part's words are words of the own lines it names


def _own_word(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def _own_words(text: str) -> set[str]:
    """The content words of a line, lowercased, a plural s cut off ("apps" and "app" match)."""
    return {_own_word(w) for w in re.findall(r"[a-z0-9]+", str(text or "").lower()) if len(w) >= 3 and w not in _OWN_STOP}


_YESNO_LABELS, _GOAHEAD_LABELS = _ar.YESNO_LABELS, _ar.GOAHEAD_LABELS


def _own_action_rx() -> "re.Pattern[str]":
    who = "|".join(re.escape(n) for n in dict.fromkeys(["you", "he", OWNER, *(_cfg.owner_names() or [])]) if n)
    return re.compile(rf"\b(?:did|have|has)\s+(?:{who})\s+(?:already\s+|now\s+|yet\s+|both\s+|all\s+)?{_OWN_VERBS}\b{_OWN_NOT_DO}|"
                      rf"\bis\s+(?:it|that|this)\s+(?:now\s+)?{_OWN_DONE}\b{_OWN_END}|"
                      rf"\bare\s+(?:they|both)\s+(?:now\s+)?{_OWN_DONE}\b{_OWN_END}", re.I)


_labels_in = _ar.labels_in
_yes_no_options = _ar.yes_no_options


def _own_action_lines(meta: dict[str, Any]) -> list[str]:
    """The `<owner>:` lines of next a session wrote: the server's own step for an ask or a your-step is left out."""
    mine = {_steps.owner_key(_hs.recorded(meta))}
    pa = _rmod.parse_ask(str(meta.get("ask") or ""))
    if pa:
        mine.add(_steps.owner_key(_hs.line_of(pa["decide"])))
    return [ln for ln in _nl.split(meta.get("next")) if _hs.is_named(ln) and _steps.owner_key(ln) not in mine]


def _own_line_named(words: set[str], line: str) -> bool:
    """The Decide part's words name this own line's action: its leading verb (when it has one of three letters or more) and one more of its words."""
    body = re.findall(r"[a-z0-9]+", _steps.first_line(line).split(":", 1)[-1].lower())
    if not body:
        return False
    verb = _own_word(body[0]) if len(body[0]) >= 3 and body[0] not in _OWN_STOP else ""
    hit = words & _own_words(" ".join(body))
    return (not verb or verb in words) and len(hit - {verb}) >= 1 and len(hit) >= 2


def _own_action_ask(meta: dict[str, Any], next_only: bool = False) -> str:
    """Why a needs=decision item only confirms the owner's own action, as a phrase for the refusal ("whose …"); "" when it is a real choice.
    next_only: the write changes next and nothing the ask reads, so only a next line that is the ask's own action refuses."""
    if "decision" not in _needs_kinds(meta) or _watch.asked_of(meta):
        return ""
    opts = [o for o in meta.get("options") or [] if isinstance(o, dict)]
    yes_no, go = _yes_no_options(meta), _labels_in(meta, _GOAHEAD_LABELS)
    if opts and not yes_no and not go:              # options that name alternatives: a real choice
        return ""
    ask = str(meta.get("ask") or "")
    pa = _rmod.parse_ask(ask)
    decide = pa["decide"] if pa else ask
    if _OWN_ALT_RX.search(decide):                   # an alternative or an open question anywhere: a real choice
        return ""
    m = None if _OWN_JUDGE_RX.search(decide) else _own_action_rx().search(decide)
    if m and not next_only and not go:
        return f"whose ask only asks whether {OWNER} has done his own step (“{m.group(0)}”)"
    words = _own_words(re.sub(r"^\s*decide\s*:\s*", "", decide, flags=re.I))
    named = [ln for ln in _own_action_lines(meta) if _own_line_named(words, ln)]
    if not named or not words:
        return ""
    hit = words & set().union(*(_own_words(ln.split(":", 1)[-1]) for ln in named))
    if len(hit) < _OWN_MATCH_SHARE * len(words):
        return ""
    shown = _clip_line(_steps.first_line(named[0]), 90)
    if yes_no and len(named) == 1:
        return f"whose options are Yes/No over {OWNER}'s own next line (“{shown}”), the action its Decide part names"
    what = "say Yes or No to" if yes_no else "approve or decline" if go else "answer"
    return f"whose Decide part only names {OWNER}'s own next lines as the thing to {what} (“{_clip_line(decide, 90)}”)"


def _gate_own_action(meta: dict[str, Any], create: bool = False, next_only: bool = False) -> None:
    """Refuse a needs=decision write whose ask only confirms the owner's own action: that is his step, not a decision."""
    why = _own_action_ask(meta, next_only=next_only)
    if not why:
        return
    how = ("create the item without needs=decision, then set step=\"<his action>\" on it by update (a create has no step)" if create
           else "use step=\"<his action>\" instead, and take decision out of needs")
    raise ToolError(f"Refused: this needs=decision item {why}. That is his step, not a decision: his Yes would be read as consent, not as the step done. "
                    f"For something {OWNER} does, {how}; the board ticks the step when he says it is done. "
                    "A real choice between options stays a decision (options that name the alternatives, or an open question that lists its answers as options). A step and a real choice are two items, linked with after=.")


_recommend_missing = _ar.recommend_missing


def _options_note(meta: dict[str, Any]) -> str:
    """A reply note when the ask's Recommend part does not name the recommended option's label, else ""."""
    rec = _recommend_missing(meta)
    if not rec:
        return ""
    return f"\n(note: the ask's Recommend part does not name the recommended option, \u201c{rec}\u201d; name it there so the two agree.)"


# Option labels and the ask line name who acts (the owner, a session's name, a role), never a bare "you" or "I" (an option
# such as "A: flag, you approve" can be read as the session approving).
# A note in the reply, never a refusal. English only; text inside quotes or backticks is skipped.
_QUOTED_RX = re.compile(r"`[^`]*`|\"[^\"]*\"|\u201c[^\u201d]*\u201d")
_BARE_PRONOUN_RX = re.compile(r"(?<![\w'\u2019/.-])(you|your|yours|yourself|i|me|my|mine|myself)(?:['\u2019](?:ll|re|ve|d|m))?(?![\w/'\u2019-])(?!\.\w)", re.I)


def _bare_pronoun(text: str) -> str:
    """The first bare you/your/I/I'll/me/my in `text` (quoted and backticked spans skipped), else ""."""
    m = _BARE_PRONOUN_RX.search(_QUOTED_RX.sub(" ", text))
    return m.group(0) if m else ""


def _actor_note(meta: dict[str, Any], options: bool = True, ask: bool = True) -> str:
    """Reply notes when an option label or the ask line says you/I/me/my without naming who acts, else ""; at most three lines."""
    out: list[str] = []
    if options:
        for o in meta.get("options") or []:
            label = str(o.get("label") or "") if isinstance(o, dict) else ""
            w = _bare_pronoun(label)
            if w:
                out.append(f'\n(note: option \u201c{label}\u201d says \u201c{w}\u201d: name who acts, e.g. {OWNER}.)')
    if ask:
        w = _bare_pronoun(str(meta.get("ask") or ""))
        if w:
            out.append(f'\n(note: the ask line says \u201c{w}\u201d: name who acts, e.g. {OWNER}.)')
    return "".join(out[:3])
