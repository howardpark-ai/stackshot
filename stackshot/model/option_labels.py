"""option_labels.py: the one rule for the letter an option's label may repeat, shared by both renderers, the server's pick reader and the History.

A question with three or more options is drawn with a letter badge on each card (A, B, C by place in the stored order). Sessions sometimes write the letter into
the label too ("A Report"), and the card then reads "[A] A Report". The label is fixed on read, never in the store:

  strip_letters(labels)    the labels as a card shows them: the same list, with the leading letter dropped from each label when the rule below holds, else unchanged
  listed(label, place)     the label for a plain list that draws no badge: the letter itself when the strip left nothing
  pick_names(raw, shown)   the text a pick of each option is stored under: the shown label, or the label as stored when the strip left nothing (a label that was only the letter)
  pick_words(choice, letter)  a picked option as a person reads it: "B · Plan", or just "B" when the option's name is its letter

The rule: it fires only with three or more options (two draw no badge) and only when EVERY label opens with its own place's letter, in order (option 1 with A, option 2 with B,
option 3 with C ...), and only when the stripped labels stay apart (no two of the names a pick is stored under equal, letter case aside: "A Report" and "B Report" are kept whole, and so are "A", "B A", "C X", since a pick is stored under the label it
names, and a label that is only its letter is stored as it stands). That order test is what keeps "A wake alone" and "A dropped step" whole: they are words, not letters. A label opens with its letter in one of the forms
`A Report`, `A. Report`, `A: Report`, `A) Report`, `(A) Report`, `A - Report`, `A · Report` or `Option A: Report` (case-insensitive, one separator at most); a label that is only the
letter strips to "". Stdlib only."""
from __future__ import annotations

import re

MIN_LETTERED = 3      # the number of options from which a card carries a letter badge (ui/render.py _cards_html)


def _lead(letter: str) -> "re.Pattern[str]":
    """The label's opening for `letter`: an optional "Option", the letter alone or in parentheses, and at most one separator; what follows is the rest."""
    L = re.escape(letter)
    return re.compile(r"(?:option\s+)?(?:\(" + L + r"\)\s*|" + L + r"(?:\s*[:)·]\s*|\.(?:\s+|$)|\s+[-–—]\s+|\s+|$))(?P<rest>.*)", re.I | re.S)


_LEADS = [_lead(chr(65 + i)) for i in range(26)]


def strip_letters(labels: list[str]) -> list[str]:
    """The labels as the card shows them (see the module docstring); the list itself when the rule does not fire."""
    if len(labels) < MIN_LETTERED or len(labels) > len(_LEADS):
        return list(labels)
    rests = []
    for i, label in enumerate(labels):
        m = _LEADS[i].fullmatch(str(label).strip())
        if not m:
            return list(labels)
        rests.append(m.group("rest").strip())
    # the names a pick is stored under (pick_names): the stripped label, or the label as stored when the strip left nothing; two equal names (case aside) would land a pick on the first of them
    names = [(r or str(label)).strip().lower() for r, label in zip(rests, labels)]
    if len(set(names)) != len(names):
        return list(labels)
    return rests


def listed(label: str, place: int) -> str:
    """The label of the option at `place` (0 for the first) for a plain list, which draws no badge: the letter itself when the strip left nothing."""
    return label or chr(65 + place)


def pick_names(raw: list[str], shown: list[str]) -> list[str]:
    """For each option, the text a pick is stored under: its shown label, else (a label that was only the letter) the label as stored."""
    return [s or r for r, s in zip(raw, shown)]


def pick_words(choice: str, letter: str = "") -> str:
    """A picked option as a person reads it: "B · <label>" when the box lettered it, the letter alone when the option's name is that letter, else the label."""
    choice, letter = str(choice or ""), str(letter or "")
    if not choice or not letter:
        return choice
    return letter if choice.strip().upper() == letter.upper() else f"{letter} · {choice}"
