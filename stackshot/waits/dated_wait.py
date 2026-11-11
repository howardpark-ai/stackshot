"""dated_wait.py — a doing item that is only waiting for a later day (an item that something holds up is marked waiting, not alive).

A stored `doing` item carries no expected time, so a doing item that is really a wait is written one way: the item has a wake (one it still carries from before `until`) some hours or a day away, and every open step of its
next is dated for that day or later ("Mon Mar 2nd after the 09:00 run", "after 2099-03-02"). Nothing can happen before then, so the board shows it as waiting on a time until the wake, without a write; the stored state stays doing.

The rule, deterministic and conservative (a doubt keeps the item doing):

  * the item is open, its state is doing (stored, or read from its fields when none is stored: a wake and a mover with no stored state read as doing), it is not on hold and its mover is a session;
  * it has a readable wake, more than [waiting] dated_wait_min_hours (1) ahead of now;
  * it has at least one open step, and every open step names a date (states.named_dates: "Mon Mar 2nd", "Mar 2", "2099-03-02") that is a later calendar day than today and not before the day of
    that time and at most MAX_AHEAD_DAYS (60) after the day of that time (a yearless date that rolled a year forward is no wait). A date counts as a wait only when the step
    says it waits for it: a waiting word (after, once, until, till, when, following, wait, waiting) stands directly before it, or with one filler word (the, a, on) between, in the same clause, or it opens the step (line start, or right after its `<name>:` opener) with a waiting word right after it ("Mon Mar 2nd after the run"). A date right after
    by, due, before, deadline, closed, since, on, ended, finished, done, eta or target is a deadline or a reference, never a wait, and neither is one followed by deadline or due, or one after a
    comma, colon or dash behind other text ("deadline: Mar 3", "land the PR, Mar 3 at the latest", "Mar 3 - draft the notes"). A step with several waiting dates counts by its earliest. A step with no such date means the agent can act now: the item stays doing. A bare sub-bullet (a line with no `<name>:` opener) is part of
    the step above it, as the checklist draws it. A time of day in a step is not read: the day decides.

A doing item whose wake stands on a stated real-world reason (metadata.wait_basis, read for that very wake: `waiting.basis_of`) and is still ahead is a wait whether or not it is on hold (`basis_wait`): the basis
names what the item waits for, so the board lists it as waiting until the wake with that text as the reason, and nothing is read from its steps. A wake with no wait_basis and no until is a backstop and the item stays active. Once the wake has passed
the item reads as it is stored again.

A doing item that is ON HOLD with a wake more than that hour ahead is the other case (`held_wait`): the hold is the park, the wake the day it ends, and nothing is read from its steps. A hold with no wake, or a
wake already past or within the hour, is no wait here.

Pure functions of an item and a time, no server import; model.view and audit_run share this one copy."""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass
from typing import Any, Callable

from stackshot.model import model_guards as _mg
from stackshot.model import nextlines as _nl
from stackshot.model import states as _states
from stackshot.model import steps as _steps
from stackshot.waits import waiting as _wt


MAX_AHEAD_DAYS = 60          # a date further than this past the wake's day is no wait (a yearless date that rolled a year ahead: "Dec 28th the run finished" read in January)
_AFTER_WORDS = frozenset({"after", "once", "until", "till", "when", "following"})
_WAIT_WORDS = _AFTER_WORDS | {"wait", "waits", "waiting", "waited"}
_OPENER_RX = re.compile(r"^\s*(?:[-*]\s*)?(?:([\w.#@-]+):)?\s*$")      # what may stand before a date that opens the step: a bullet and the `<name>:` opener
_NOT_A_WAIT = frozenset({"by", "due", "before", "deadline", "closed", "since", "on", "ended", "finished", "done", "landed", "merged", "eta", "target"})     # a deadline or a reference date, never a wait for the day
_BREAK_RX = re.compile(r"[,;:\n()\[\]]|[.!?]\s")     # a clause ends at punctuation; a bracket does not continue it either way
_FILLER = frozenset({"the", "a", "on"})
_TOKEN_RX = re.compile(r"[\w'#/-]+")


def _waits_for(text: str, start: int, word: str) -> bool:
    """Does the step say it waits for the date written as `word` at `start`? Yes when a waiting word stands directly before it, or with one filler word (the, a, on) between ("after Mar 3",
    "until the 2099-03-03"), in the same clause; or when the date opens the step (line start, or right after its `<name>:` opener) and a waiting word follows it ("Mon Mar 2nd after the run").
    Conservative: a missed wait is fine, a false one is not, so a waiting word further back ("merge once CI is green (Mar 3)", "after lunch for the 2099-03-03 release") and a bracket around
    other words do not count. Never when deadline / due follows the date, or when it follows a comma, colon or dash behind other text ("deadline: Mar 3", "Mar 3 - draft the notes")."""
    nxt = _TOKEN_RX.match(text[start + len(word):].lstrip())
    nxt_w = nxt.group(0).lower() if nxt else ""
    if nxt_w in ("deadline", "due"):
        return False
    opener = _OPENER_RX.match(text[text.rfind("\n", 0, start) + 1:start])
    if opener:                                       # the date opens the step: a wait only when a waiting word follows it
        return (opener.group(1) or "").lower() not in _NOT_A_WAIT and nxt_w in _AFTER_WORDS
    toks = [t.lower() for t in _TOKEN_RX.findall(_BREAK_RX.split(text[:start])[-1])]
    if toks and toks[-1] in _FILLER and len(toks) > 1:
        toks.pop()                                   # one filler word may stand between the waiting word and the date ("until the 2099-03-03")
    return bool(toks) and toks[-1] in _WAIT_WORDS


def _wait_dates(entry: str, today: dt.date) -> list[tuple[str, dt.date]]:
    """The dates of a step that it waits for (named_dates, kept when _waits_for says so), as (as written, date)."""
    out: list[tuple[str, dt.date]] = []
    pos = 0
    for word, d in _states.named_dates(entry, today):
        i = entry.find(word, pos)
        if i < 0:
            continue
        pos = i + len(word)
        if _waits_for(entry, i, word):
            out.append((word, d))
    return out


def step_wait_day(text: Any, today: dt.date) -> dt.date | None:
    """The day a step says it waits for (its earliest waiting date, as `_waits_for` reads it), or None when it names none: a step with no waiting date, a deadline or a reference date is not dated."""
    days = [d for _w, d in _wait_dates(str(text or ""), today)]
    return min(days) if days else None


@dataclass(frozen=True)
class DatedWait:
    """A doing item that waits for a later day: `until` the epoch of its wake, `source` what gave it (wake), `at` that value as stored, `steps` each open step's first line with
    the date it is dated for (its earliest) and that date as the step wrote it."""
    until: float
    source: str
    at: str
    steps: tuple[tuple[str, dt.date, str], ...]
    reason: str = ""            # the wait's own reason when it has one (a wait_basis text); basis() words the others


def _entries(text: Any) -> list[str]:
    """The open steps of a next text: the lines of nextlines.split, a bare sub-bullet joined to the step above it."""
    out: list[str] = []
    for e in _nl.split(text):
        if out and _steps.is_bare(e):
            out[-1] += "\n" + e
        else:
            out.append(e)
    return out


def of(item: dict[str, Any], now: float) -> DatedWait | None:
    """The item's dated wait, or None when it has none (every condition in the module doc)."""
    m = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    if item.get("status") != "open" or _states.of(item)[0] != "doing" or _wt.is_held(item):      # no stored state reads as doing too (an after link reads as blocked: no wait here)
        return None
    if _wt.mover_of(m)["kind"] != "session":
        return None
    soon = now + _wt.dated_wait_min_hours() * 3600.0
    wake = _wt.wake_epoch(_wt.wake_value(m)) if _wt.wake_value(m) else None
    if wake is None:
        return None
    until, source, at = wake, "wake", str(_wt.wake_value(m)).strip()
    if until <= soon:
        return None
    zone = _wt._cfg.tz()
    today = dt.datetime.fromtimestamp(now, zone).date()
    from_day = dt.datetime.fromtimestamp(until, zone).date()
    rows: list[tuple[str, dt.date, str]] = []
    for e in _entries(m.get("next")):
        dates = [(w, d) for w, d in _wait_dates(e, today) if d <= from_day + dt.timedelta(days=MAX_AHEAD_DAYS)]
        if not dates:
            return None                         # no date it waits for (undated, a deadline, a reference, a rolled-over year): the agent can act now
        word, d = min(dates, key=lambda x: x[1])
        if d <= today or d < from_day:
            return None
        rows.append((_steps.first_line(e), d, word))
    return DatedWait(until, source, at, tuple(rows)) if rows else None


def held_wait(item: dict[str, Any], now: float) -> DatedWait | None:
    """The wait of a stored doing item that is on hold with a wake: `until` the wake, when it is more than [waiting] dated_wait_min_hours ahead; None for a hold with no readable wake, a wake already past or
    within the hour, an item that is not doing or whose mover is not a session. (An on-hold item with no stored state already reads as parked, so only a stored doing one needs this.)"""
    m = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    if item.get("status") != "open" or _states.stored(item) != "doing" or not _wt.is_held(item) or _wt.mover_of(m)["kind"] != "session":
        return None
    wake = _wt.wake_epoch(_wt.wake_value(m)) if _wt.wake_value(m) else None
    soon = now + _wt.dated_wait_min_hours() * 3600.0
    if wake is None or wake <= soon:
        return None
    return DatedWait(wake, "wake", str(_wt.wake_value(m)).strip(), ())


def basis_wait(item: dict[str, Any], now: float, after_open: Any = None) -> DatedWait | None:
    """The wait of a stored doing item (or one read as doing) whose wake carries a wait_basis: `until` the wake and `reason` the basis text, while the wake is still ahead of `now`; None once it has passed, for a wake with no
    wait_basis (a reminder: the item stays active), an item that is on hold (held_wait reads it), not doing, whose mover is not a session, or that names a decision or an outside party in needs or waits after another item
    (those say their own state). `after_open(item)` says which of the items it waits after are still open, as model.derive takes it (without it every `after` link counts as open): a closed link is no wait."""
    m = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    if item.get("status") != "open" or _states.of(item)[0] != "doing" or _wt.is_held(item) or _wt.mover_of(m)["kind"] != "session":
        return None
    if _states.kinds_of(m) or str(m.get("wait_kind") or "").strip():
        return None
    if _wt.after_of(m) and (after_open(item) if after_open else True):
        return None
    reason = _wt.basis_of(m)
    wake = _wt.wake_epoch(_wt.wake_value(m)) if reason and _wt.wake_value(m) else None
    if wake is None or wake <= now:
        return None
    return DatedWait(wake, "wake", str(_wt.wake_value(m)).strip(), (), reason)


def timed_wait_lines(next_text: Any, wake: Any, today: dt.date, mover_is: Callable[[str], bool], dated_only: bool = False) -> list[str]:
    """What makes each open line of `next_text` wait, as model_guards.reads_as_timed_step words it, when EVERY open line is the mover's (`mover_is(opener)`; a line with no opener is) and reads as a wait for
    the wake's own hour or day (with `dated_only` for nothing else, with it off an outside event too); [] when any line is an action to take now or another party's step: the date is then no wait, as work in hand.
    The server's write (the correction and the note) and the ten-minute audit pass read an item through this one function."""
    found: list[str] = []
    for chunk in _steps.split(str(next_text or "")):
        if _steps.is_bare(chunk):
            continue                                   # a bare bullet is a sub-step of the line above
        who = _steps.opener(chunk)
        if who and not mover_is(who):
            return []                                  # another party's step is in flight
        first = next((ln for ln in chunk.splitlines() if ln.strip()), "")
        why = _mg.reads_as_timed_step(_steps.strip_opener(first), wake, today, dated_only=dated_only)
        if not why:
            return []                                  # an action to take now
        found.append(why)
    return found


def signature(dw: DatedWait) -> str:
    """A short hash of what the wait stands on, the dated lines and the time: stable while neither changes (the audit's verdict is kept against it)."""
    raw = "|".join(_nl.norm(ln) for ln, _, _ in dw.steps) + "||" + dw.source + ":" + dw.at
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def basis(dw: DatedWait) -> str:
    """The wait's reason as the board words it: every open step is dated for a later day (or, for a held item with no steps read, the hold)."""
    if dw.reason:
        return dw.reason
    if not dw.steps:
        return "on hold until its wake"
    words = list(dict.fromkeys(w for _, _, w in dw.steps))[:2]
    return "every open step is dated for later (" + ", ".join(words) + ")"
