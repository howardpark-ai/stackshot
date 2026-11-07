"""ask_read.py: how an ask line and its options are read, in one copy for the server's write gates and the audit's ten-minute check.

An item that needs a decision shows its options as cards; with none stored the item page draws a bare Yes / No (render.yesno_options). So an ask is readable only when its Decide part is a yes/no
question, or its options are the answers. These functions read an item's metadata and write nothing:

  open_question(meta)        the Decide part when it opens with an interrogative word (what, which, how, who, whom, whose, when, where, why), else ""
  alternatives(meta, text)   the words in the ask (or `text`, the description) that name alternatives, else ""
  yes_no_options(meta) / labels_in(meta, labels)   the stored options are a Yes/No pair (or the labels given)
  recommend_missing(meta)    the recommended option's label when the ask's Recommend part does not name it, else ""
  yes_no_buttons(meta)       the page draws a Yes/No (or Approve/Decline) pair under the ask: no options stored, or options that are only such a pair

Stdlib plus render.py (the ask's shape) and config.py ([keywords.ask_options])."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

import config as _cfg  # [keywords.ask_options]: the refusal words and particles of the instance's own language
import option_labels as _ol  # the letter an option's label repeats from its badge, dropped on read
import render


# Words that name alternatives. Narrow on purpose: a yes/no ask ("Decide: whether to ship · Recommend: ship …") must pass. The
# keyword forms are read in the ask and the description; the bare list form ("A, B or C", "x vs y") only in the ask's Decide part.
ALT_RX = re.compile(r"\b[Oo]ptions? (?:(?-i:[A-F1-6])|one|two|three)\b(?!-)|\b(?:two|three|four|five|six|[2-6]) (?:options|alternatives|choices)\b|"
                    r"\b[Oo]ptions?:|\bpick (?:one|between|among)\b|\bchoose (?:between|among|one of)\b|\bwhich of (?:the|these|those) "
                    r"(?:two|three|options|alternatives)\b|\(a\)[^()\n]{1,200}\(b\)", re.I)
ALT_LIST_RX = re.compile(r"[\w-]+(?: [\w-]+){0,2}, [\w-]+(?: [\w-]+){0,2},? or [\w-]+|\b\S+ (?:vs\.?|versus) \S+", re.I)


# Labeled alternatives in the ask's Decide part, case-sensitive so that the article "a" and the word "or" never count: two capital letters A-F joined by "or" / "vs" / "/", each
# bare or followed by one parenthesis of words ("A or B", "A (full height, as now) or B (starts below the cards)"), and the colon form ("A: wider, or B: narrower"). One letter alone
# ("plan A"), a plain yes/no ("ship it?"), quoted words ("accept "yes" or "no"?") and an "or" between unlabeled words pass. A pair counts only when the second letter comes after the
# first (A or B, B or C), which leaves out "I or A"-style chance matches. The second letter is read ahead, not consumed, so it can start the next pair ("D or A or B" finds A or B).
LABEL_PAREN = r"(?: \((?:[^()\n]|\([^()\n]*\)){1,200}\))?"
ALT_LETTERS_RX = re.compile(r"(?<![\w#$.\-/])(?-i:([A-F]))(?![\w-])" + LABEL_PAREN + r"[,;]? (?:or|vs\.?|versus|/) (?=(?-i:([A-F]))(?![\w-]))", re.S)
ALT_COLON_RX = re.compile(r"(?<![\w#$.\-/])(?-i:([A-F])):[^·\n]{1,200}?\bor (?=(?-i:([A-F])):)")


def lettered_alternatives(decide: str) -> str:
    """The labeled pair of alternatives in an ask's Decide part ("A (…) or B", "A: … or B:"), "" when it holds none."""
    for rx in (ALT_LETTERS_RX, ALT_COLON_RX):
        for m in rx.finditer(decide):
            if m.group(1) < m.group(2):
                return m.group(0) + m.group(2) + (":" if rx is ALT_COLON_RX else "")
    return ""


def alternatives(meta: dict[str, Any], description: str) -> str:
    """The words in an item's ask or description that name alternatives, "" when none do."""
    ask = str(meta.get("ask") or "")
    for text in (ask, description):
        m = ALT_RX.search(text or "")
        if m:
            return m.group(0)
    pa = render.parse_ask(ask)
    m = ALT_LIST_RX.search(pa["decide"]) if pa else None
    if m:
        return m.group(0)
    return lettered_alternatives(pa["decide"]) if pa else ""


OPEN_Q_LEAD_RX = re.compile(r"[\s\"'`“”‘’(\[{<«]*(?:what|which|how|who|whom|whose|when|where|why)\b", re.I)


def decide_of(meta: dict[str, Any]) -> str:
    """The Decide part of the item's ask without its "Decide:" head; a misshaped ask is read up to its first " · "."""
    ask = str(meta.get("ask") or "")
    pa = render.parse_ask(ask)
    decide = pa["decide"] if pa else ask.split(" · ", 1)[0]
    return re.sub(r"^\s*decide\s*:\s*", "", decide, flags=re.I).strip()


def open_question(meta: dict[str, Any]) -> str:
    """The Decide part of an ask that opens with an interrogative word (what, which, how, who, whom, whose, when, where, why), "" when it does not."""
    decide = decide_of(meta)
    return decide if OPEN_Q_LEAD_RX.match(decide) else ""


YESNO_LABELS = frozenset({"yes", "no", "y", "n", "yep", "nope", "done", "not done", "not yet", "done it", "did it", "yes, done", "no, not yet"})
GOAHEAD_LABELS = frozenset({"approve", "approved", "decline", "declined", "reject", "go", "no go", "no-go", "go ahead", "hold", "ok", "okay"})


def labels_in(meta: dict[str, Any], labels: frozenset[str]) -> bool:
    opts = [o for o in meta.get("options") or [] if isinstance(o, dict)]
    return bool(opts) and all(re.sub(r"[.!]+$", "", str(o.get("label") or "").strip().lower()) in labels for o in opts)


def yes_no_options(meta: dict[str, Any]) -> bool:
    """The item's options are a yes/no pair (Yes/No, Done/Not yet …), which name no alternatives."""
    return labels_in(meta, YESNO_LABELS)


def valid_options(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """The item's options as the page reads them (render.options_of): [] when none are stored or the list is misshaped (one option, no single recommended one, a recommended that is not a boolean, a label or line missing)."""
    return render.options_of({"metadata": meta})


def yes_no_buttons(meta: dict[str, Any]) -> bool:
    """The page offers only a Yes / No (or Approve / Decline) pair under this item's ask, or nothing usable: it stores no options, options it cannot read (valid_options is empty) or only such a pair."""
    return not valid_options(meta) or yes_no_options(meta) or labels_in(meta, GOAHEAD_LABELS)


_WORD_RX = re.compile(r"[^\W_]+")      # a word is letters and digits of any script; underscore is not one, as before
_LEAD_STOP = frozenset({"the", "a", "an", "to", "and", "of", "it", "this", "that", "do", "not"})      # words that open many labels and recommendations: no match on their own
_ORDINALS = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3, "fifth": 4, "5th": 4, "sixth": 5, "6th": 5}
# A word that turns the option after it away ("Wide, not Narrow", "Avoid Wait; Close", "instead of B"): the option it precedes is not the one named. Only when it sits right before it (no comma between).
# [keywords.ask_options] `refusals` adds the instance's own words to these, and `particles` the suffixes that may follow a label's last word (a language that glues them on); empty adds nothing.
# `refusals_after` is the mirror of `refusals` for a language that puts the refusing word after the label ("<label> <word> <other label>"): it turns away the label standing right before it (an optional particle and spaces between; no word boundary after the word, as its endings vary).
_NEG_BASE = r"not|no|avoid|never|skip|except|don['’]?t|instead of|rather than"
_PLACE = r"(?:(?-i:(?P<l>[A-F]))|(?P<d>[1-6]))"
_NO_PICK_RX = re.compile(r"^\W*(?:none|either|neither|no (?:preference|recommendation|pick)|your call|up to you|no view)\b", re.I)


class _Rx:
    """The matchers that depend on the configured refusal words and particles, compiled once per set of words (so a config reload is seen)."""

    def __init__(self, refusals: str, particles: str, refusals_after: str = "") -> None:
        self.after = refusals_after
        self.gap = rf"\s*(?:(?:{particles})\s*)?(?:{refusals_after})" if refusals_after and particles else (rf"\s*(?:{refusals_after})" if refusals_after else "")      # what follows a turned-away label: an optional particle, spaces, then the word
        self.neg = rf"(?:{_NEG_BASE}{'|' + refusals if refusals else ''})"
        self.particle = rf"(?:{particles})?" if particles else ""
        self.neg_any = re.compile(rf"\b{self.neg}\b", re.I)
        self.pos_lead = re.compile(rf"^\W*(?P<n>{self.neg}\s+)?(?:(?:option|choice|alternative|pick|plan)\s+)?(?:#\s*)?{_PLACE}(?=\s*(?:$|[,:;.)(—-]))", re.I)      # "B", "B, Beta", "option 2", "#2", "Not B" (a bare letter or digit that ends the phrase or opens a note: "A new column" is no place)
        self.pos_option = re.compile(rf"\b(?P<n>{self.neg}\s+)?(?:option|choice|alternative)\s+#?{_PLACE}(?![\w-])", re.I)
        self.pos_ordinal = re.compile(rf"\b(?P<n>{self.neg}\s+(?:the\s+)?)?(?P<o>{'|'.join(_ORDINALS)})\b", re.I)


_RX_CACHE: dict[tuple[str, str, str], _Rx] = {}


def _rx() -> _Rx:
    key = (_cfg.kw_alt("ask_options", "refusals"), _cfg.kw_alt("ask_options", "particles"), _cfg.kw_alt("ask_options", "refusals_after"))
    if key not in _RX_CACHE:
        _RX_CACHE[key] = _Rx(*key)
    return _RX_CACHE[key]


def _norm(text: Any) -> str:
    """NFC (an accented letter typed as a base letter plus a separate mark is one word character), as the options and the Recommend text are compared."""
    return unicodedata.normalize("NFC", str(text or ""))


def _words(text: str) -> list[str]:
    return _WORD_RX.findall(_norm(text).casefold())


def _mention(label: str, text: str, neg: str | None = None) -> tuple[bool, bool]:
    """(named, turned away) for an option's whole label in the Recommend text: named when the label's words stand in it in order (case and punctuation aside), a configured particle allowed right after the last word;
    turned away when every such place has a "not" word right before it (`neg`: the pattern of those words, by default the built-in and configured ones) or a word of `refusals_after` right after it."""
    lw = _words(label)
    if not lw:
        return False, False
    x = _rx()
    end = rf"(?:(?=(?P<a>{x.gap}))|(?![^\W_]))" if x.gap else r"(?![^\W_])"      # a refusal word after the label needs no word boundary of its own
    rx = re.compile(rf"(?<![^\W_])(?P<n>{neg or x.neg}\s+(?:(?:the|pick|choose|take|use|go with|go)\s+)?)?{r'[\W_]+'.join(map(re.escape, lw))}{x.particle}{end}", re.I)
    hits = [bool(m.group("n")) or m.groupdict().get("a") is not None for m in rx.finditer(_norm(text).casefold())]
    return bool(hits), bool(hits) and all(hits)


def recommend_mismatch(meta: dict[str, Any]) -> str:
    """For the audit, where a note in a reply is not enough: "" when the ask's Recommend part agrees with the item's options or cannot be shown to disagree; else "none" (it names no option by any form below) or
    the label of the other option it plainly names. Forms that name an option: its whole label (case and punctuation aside; a word of [keywords.ask_options] `particles` may follow its last word), a letter or a place that resolves to it ("B", "B, Beta", "option 2", "the second"; with two
    options, which the page draws without letters and with the recommended one first, any letter or place counts), and, when no label is named, a leading word shared with the recommended label alone (not with any other
    option's label: "ship" for "Yes, ship", but not "Ship later" for "Ship now"). A label, letter or place right after not, no, avoid, never, skip, except, don't, instead of or rather than (or a word of [keywords.ask_options] `refusals`; a label right before a word of `refusals_after` too) is turned away and names nothing:
    "Wide, not Narrow" names Wide. A Recommend that names the recommended option and another with no "not" between ("Narrow over Wide") is left alone, and so is one that says there is no pick ("none, your call",
    "either"). No valid options, a yes/no pair or no ask in form: "" (not this check's)."""
    opts = valid_options(meta)
    pa = render.parse_ask(str(meta.get("ask") or ""))
    if not opts or not pa or yes_no_buttons(meta):
        return ""
    text = pa["recommend"]
    if _NO_PICK_RX.match(text):
        return ""
    ri = next(i for i, o in enumerate(opts) if o["recommended"])
    named = [i for i, o in enumerate(opts) if _mention(o["label"], text)[0] and not _mention(o["label"], text)[1]]      # whole labels named, not turned away
    if ri in named:
        return ""
    if named:
        return opts[named[0]]["label"]
    x = _rx()
    places: set[int] = set()      # letters, numbers and places that are named, not turned away
    for rx in (x.pos_lead, x.pos_option):
        m = rx.search(text)
        if m and (m.group("n") is None or len(opts) == 2):
            places.add(ord(m.group("l")) - 65 if m.group("l") else int(m.group("d")) - 1)
    places |= {_ORDINALS[m.group("o").lower()] for m in x.pos_ordinal.finditer(text) if m.group("n") is None or len(opts) == 2}
    if places and (len(opts) == 2 or ri in places):
        return ""                      # a place on two options is ambiguous (the page draws no letters there); on more, the stored order
    other = [p for p in sorted(places) if p < len(opts)]
    if other:
        return opts[other[0]]["label"]
    if places:
        return ""                      # a place the options do not have: not shown to disagree
    if x.neg_any.search(text) or (x.after and any(_mention(o["label"], text)[1] for o in opts)):
        return "none"                  # a turned-away option or place and nothing else: it names no option
    rw = _words(text)
    lw = _words(opts[ri]["label"])
    elsewhere = {w for i, o in enumerate(opts) if i != ri for w in _words(o["label"])}      # a shared leading word counts only when it picks the recommended label out from the others
    if rw and lw and ((rw[0] in lw and rw[0] not in _LEAD_STOP and rw[0] not in elsewhere) or (lw[0] in rw and lw[0] not in _LEAD_STOP and lw[0] not in elsewhere)):
        return ""
    return "none"


def recommend_missing(meta: dict[str, Any]) -> str:
    """The recommended option's label when the ask's Recommend part does not name it (substring, case-insensitive and NFC-normalized as recommend_mismatch reads it), "" when it does, or when there is no option, no recommended one or no ask in form.
    A label that stands in the text only right after a word of [keywords.ask_options] `refusals`, or right before a word of `refusals_after`, is not named (with none set, nothing changes: the substring alone decides; a particle after the label is a substring match already)."""
    shown = valid_options(meta)      # the labels as the card shows them (a letter its badge draws is not part of the name), a letter-only label by that letter
    rec = next((_ol.listed(o["label"], i) for i, o in enumerate(shown) if o["recommended"]), "") or next((o["label"] for o in meta.get("options") or [] if isinstance(o, dict) and o.get("recommended") is True), "")
    pa = render.parse_ask(str(meta.get("ask") or ""))
    if not rec or not pa or (_norm(rec).casefold() in _norm(pa["recommend"]).casefold() and not _refused_only(rec, pa["recommend"])):
        return ""
    return rec


def _refused_only(label: str, text: str) -> bool:
    """The label stands in the text, and every place it does is right after a configured refusal word or right before a configured `refusals_after` word (the instance's own, not the built-in English ones)."""
    extra = _cfg.kw_alt("ask_options", "refusals")
    if not extra and not _rx().after:
        return False
    named, away = _mention(label, text, neg=rf"(?:{extra})" if extra else _cfg._NEVER)
    return named and away
