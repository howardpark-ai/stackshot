"""model_guards.py — the write guards of the item model (the design: docs/design, sections 1, 3, 4 and 6, layer 1).

model.py gave an item its model fields and a pure reading of them. This module judges a write by that reading: `check` says what a create or update would leave
wrong on an item, and the server refuses the write with those sentences (server.py `_gate_model`); `report` runs the same judgement over the items already in the store and
only counts, so the owner and the audit can see what the guards would refuse on today's board before the migration moves it. Pure of the server (it reads model.py, states.py and
waiting.py, and the session registry, the fleet heartbeats and the project registry through the same modules the server uses), so the server, tools/model_guard_report.py and
the tests share one copy.

The guards, each a key of GUARDS:
  mover          an alive item names a mover who is the owner, a live session or the project's background agent (model.derive's defaults fill an unnamed one)
  wait_input     a wait names its input: a time its wake, an anchor the anchor and the event, an item the items it waits after, a relay the event, an event wait the fleet event (event_waits.py)
  post_wake      …and a post-wake mover who passes the same test as a mover (defaults count)
  snooze         a time wait (a hold with a wake) carries the owner's words (cap_ok with a quote that parks, waits, says until or names a date) or a real date (wait_basis)
  filler         TBD, TBC, TBA, "?", dashes and "to be determined" are refused in goal, next, ask and wait_event
  no_end         a wait has an end: a relay's ask_by, an anchor's, an item's or an event's ask_by (or its backstop wake); a time wait's end is its wake
  decision_hold  needs decision together with a hold ("an ask for later is a time wait whose post-wake mover is the owner")
  mover_state    an agent stored as mover on an item in the owner's state (your-step, your-call, needs decision): he is its mover; the agent goes in `then`
  owner_mover   an alive item whose mover is the owner but which is not in his state: not your-step with a step, not your-call or needs decision (the ask is the ask rule's: [ask] refuse_after); the mirror of mover_state
  second_mover   more than one mover in needs (two sessions, or decision plus a session): the post-answer mover goes in `then`   [config: [model] one_mover]
  next_unnamed   every next line starts `<name>: `: any name passes (the owner, a session, the background agent or an outside party); a bare `- ` or numbered line under a named step is its sub-line. Who may be named is next_rules.unnamed's (N1),
                 which a session's write through the create and update tools meets first, with its own refusal; this guard still judges what N1 does not: the writes of scripts and of the server, and the report
  next_windows   a next line that starts with the owner's name (`<owner>:`, `<alias>:`, `you:`, "the owner to …") and asks him to run something (a run cue such as run, type, execute, enter, or a place phrase such as
                 "In PowerShell:") passes the same command check as the step (step_commands.command_problem): a command is in backticks or a fence, a command bash for the host is written
                 `ssh -t <host> '<command>'`, a shell command says where it runs (PowerShell); with [steps] owner_shell = "sala-shell" a command is bash as typed in sala's Shell or `ssh <host> '<command>'`, no place is
                 asked for, and a PowerShell or Windows-only command outside ssh is refused; a `! ` line (pane form) is refused whatever the line says. A line that only mentions a command, and lines for other sessions, are not judged; only the lines a write sets are
  next_wait      on an alive item a next line that reads as a wait (the precise list: wait for/on/until, waiting, blocked on/by, until <date or item>, once X lands/merges/replies,
                 on hold, and the instance's own [keywords.model_guards] wait_words) is refused; a negation passes; the broad list (when, once, after, until) is accepted and flagged (nothing is stored: audit_checks.wait_words reads the words from next)
  next_defers    a next line that defers on another open item in words (once / after / when / until / before, then a board#N) while `after` does not name that item: nothing would wake the mover when it
                 closes. Only the lines the write sets are judged (`defers_text`); the report and the brief do not count it
  alarm          an alarming word (the words in `ALARM`) in subject, ask or next, with the everyday word to use
  description    a description that is one thick block (a paragraph over 300 characters, or over 400 characters with no bullet): short `- ` bullets, one line each. Fenced code and
                 `>` quotes do not count. The server notes it in the reply, or refuses it: [model] description_guard = "note" | "refuse"

When a guard runs: a guard on a field runs when the write sets that field or creates the item; the state invariants (mover, wait_input, post_wake, snooze, no_end,
decision_hold, second_mover) run when the write creates the item or sets any field that defines the state or the wait (STATE_FIELDS). An old item's untouched fields never block
an unrelated update. A close is never judged. `touched=None` means every field is judged: a create, and the report."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from stackshot.anchors import anchors as _anc
from stackshot.anchors import anchor_scope as _ascope   # which anchors count for an item: from every project's page
from stackshot.waits import event_waits as _ew
from stackshot.core import config as _cfg
from stackshot.fleet import fleet as _fleet
from stackshot.model import model as _model
from stackshot.fleet import sessions_registry as _sr
from stackshot.model import states as _states
from stackshot.model import step_commands as _sc
from stackshot.waits import waiting as _wt

GUARDS = ("mover", "wait_input", "post_wake", "snooze", "filler", "no_end", "decision_hold", "mover_state", "owner_mover", "second_mover", "next_unnamed", "next_wait", "next_windows", "alarm", "description")
LABELS = {"mover": "mover", "wait_input": "wait input", "post_wake": "post-wake mover", "snooze": "snooze", "filler": "filler", "no_end": "wait with no end",
          "decision_hold": "decision with a hold", "mover_state": "agent mover on his state", "owner_mover": f"{_cfg.owner()} as mover with no step or ask", "second_mover": "second mover", "next_unnamed": "next line with no name", "next_wait": "wait in next", "next_windows": "his next line with a command that is not in backticks, does not say where it runs, runs on the wrong machine or is a `! ` line", "alarm": "alarming word", "description": "description not in bullets"}
CLOSED_NO_OUTCOME = "closed_no_outcome"
STATE_FIELDS = frozenset({"needs", "hold", "wake", "after", "state", "mover", "then", "wait_kind", "wait_anchor", "wait_event", "ask_by", "post_wake_mover", "cap_ok", "wait_basis"})
FIELD_GUARDS = frozenset({"subject", "goal", "next", "ask", "wait_event", "description"})       # the fields a text guard reads
_STATE_GUARDS = frozenset({"mover", "wait_input", "post_wake", "snooze", "no_end", "decision_hold", "mover_state", "owner_mover", "second_mover"})


@dataclass(frozen=True)
class Problem:
    """One thing a write would leave wrong: the guard that found it and its refusal sentence (what is wrong, and the fix)."""
    key: str
    text: str


def clean(v: Any) -> str:
    return " ".join(str(v or "").split())


# ---------------------------------------------------------------------------------------------------------------- the words
_FENCE_RX = re.compile(r"(?m)^[ \t]*(?:```|~~~)[^`\n]*\n(?:.*\n)*?[ \t]*(?:```|~~~)[ \t]*$")      # a fenced block, its fence lines included: a fence line holds only the marker and an optional info string (no second ```); an unclosed fence is no fence
_CODE_RX = re.compile(r"`[^`\n]*`|https?://\S+|\]\([^)\s]*\)")
_MARK_RX = re.compile(r"^\s*(?:[-*+•]|\d+[.)])?\s*")


def _plain(text: str) -> str:
    """The text with code spans and links blanked, so a command or a URL is not read as prose."""
    blank = lambda m: re.sub(r"[^\n]", " ", m.group(0))
    return _CODE_RX.sub(lambda m: " " * len(m.group(0)), _FENCE_RX.sub(blank, str(text or "")))


_FILLER_WORD_RX = re.compile(r"(?:tbd|tbc|tba|to be (?:determined|decided|confirmed|announced|defined))", re.I)


def is_filler(text: Any) -> bool:
    """Is this value only a placeholder: TBD, TBC, TBA, "to be determined", "?", "...", a dash. A sentence that merely contains one is not."""
    t = clean(text)
    if not t:
        return False
    if not re.search(r"\w", t):                       # only punctuation: "?", "—", "...", "…"
        return True
    return bool(_FILLER_WORD_RX.fullmatch(t.strip(" .!;:,()[]<>*_`\"'")))


def _line_content(line: str) -> str:
    """A next line without its list marker, its bold marks and its `<name>:` opener."""
    c = _MARK_RX.sub("", line.strip().replace("**", ""))
    m = _NAME_RX.match(c)
    return c[m.end():].strip() if m else c


_BARE_RX = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+\S")      # a bullet or numbered line (a sub-line when a named step stands above it)
_NAME_RX = re.compile(r"^(?P<name>[^\W_][\w.\-]*(?: [\w.\-]+){0,2})(?:\s*\([^)\n]{1,40}\))?\s*:(?:\s+|$)")      # an optional parenthetical after the name (`my-agent (builder):`) is a role, not part of the name
# Labels that open a line the way a name would but name nobody: a status or a note is not an actor. Used by the write checks only (next_rules.unnamed, the next_unnamed guard);
# a line already stored is read as it is (steps.opener), so no stored step changes hands.
NOT_ACTORS = frozenset({"status", "note", "notes", "result", "results", "progress", "update", "updates", "done", "summary", "fyi", "blocked", "todo", "to do", "tbd", "n/a"})
_NOSPACE_RX = re.compile(r"^(?P<name>[^\W_][\w.\-]*(?: [\w.\-]+){0,2}):(?P<rest>[^\s/:]\S*)")


def not_actor(name: Any) -> bool:
    """Is the opener a label (`Status`, `Note`, `Result`) and no one who can take a step? Write checks only."""
    return str(name or "").strip().lower() in NOT_ACTORS


def line_hint(line: Any) -> str:
    """Why a next line that names no one was refused, in one clause the refusal can add ("" when the line is just bare): a label such as `Status:` is not an actor; a missing space after the colon
    (`my-agent:do`) hides the name. A `://` link is no opener."""
    c = _MARK_RX.sub("", str(line or "").strip().replace("**", ""))
    m = _NAME_RX.match(c)
    if m and not_actor(m.group("name")):
        return f"`{m.group('name')}:` is a label, not someone who takes the step: name the actor first (the step's result belongs on the project page)"
    m = _NOSPACE_RX.match(c)
    if m and not_actor(m.group("name")):
        return f"`{m.group('name')}:` is a label, not someone who takes the step: name the actor first (the step's result belongs on the project page)"
    if m:
        return f"put a space after the colon (`{m.group('name')}: {m.group('rest')} …`): the name is read only when a space follows it"
    return ""


def filler_in(field_name: str, text: Any) -> str:
    """The placeholder this field holds ("" when none). goal and wait_event are one value; a next line is judged after its `<name>:` opener; an ask by its `·` parts."""
    t = str(text or "")
    if field_name == "next":
        for ln in t.splitlines():
            if ln.strip() and is_filler(_line_content(ln)):
                return clean(ln)
        return ""
    if field_name == "ask":
        for part in clean(t).split("·"):
            body = re.sub(r"^\s*[A-Za-z][A-Za-z ]{0,14}:\s*", "", part)
            if is_filler(body):
                return clean(part)
        return ""
    return clean(t) if is_filler(t) else ""


ALARM = {"leak": "leftover files", "breach": "access problem", "exposed": "visible", "quota": "limit or disk space", "credential": "sign-in", "kill": "stop"}
_ALARM_RX = re.compile(r"\b(leak(?:s|ed|ing)?|breach(?:es|ed|ing)?|exposed|quotas?|credentials?|kill(?:s|ed|ing)?)\b", re.I)


def alarm_in(text: Any) -> tuple[str, str]:
    """(the alarming word, the everyday word to write instead) the text uses, ("", "") when none. Code spans and links are not prose and are left out."""
    m = _ALARM_RX.search(_plain(text))
    if not m:
        return "", ""
    w = m.group(1)
    low = w.lower()
    for stem, repl in ALARM.items():
        if low.startswith(stem):
            if stem == "kill" and low != "kill":
                repl = {"killed": "stopped", "killing": "stopping", "kills": "stops"}.get(low, repl)
            return w, repl
    return w, ""


_MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_WEEKDAY = r"(?:mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)"      # the names and their abbreviations only: never monitor, thumbs, satisfied, money, thus
_DATE = (rf"(?:\d{{4}}-\d{{2}}-\d{{2}}|{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b|\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\b|\b{_WEEKDAY}\b|"
         rf"tomorrow|next\s+(?:week|month)|board#\d+|#\d+)")
_PRECISE: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("wait for / on / until", re.compile(r"\bwait\s+(?:for|on|until|till)\b|\bwait(?:s|ed)\s+(?:on|until|till)\b", re.I)),      # "waits for" is a verb of code and tests as often as of a person: not here
    ("waiting on / for / until / to hear", re.compile(r"\bwaiting\s+(?:on|for|until|till|to\s+hear)\b", re.I)),
    ("blocked on / by", re.compile(r"\bblocked\s+(?:on|by)\b", re.I)),
    ("until a date or item", re.compile(rf"\b(?:until|till)\s+{_DATE}", re.I)),
    ("once X lands / merges / replies", re.compile(r"\bonce\b[^.\n]{0,80}?\b(?:lands?|landed|merges?|merged|replies|replied|reply)\b", re.I)),
    ("on hold", re.compile(r"\bon\s+hold\b", re.I)),
)


def _precise() -> "tuple[tuple[str, re.Pattern[str]], ...]":
    """The precise wait patterns, with the instance's own wait words ([keywords.model_guards] wait_words) as one more."""
    extra = _cfg.kw_alt("model_guards", "wait_words")
    return _PRECISE + ((("wait word (configured)", _cfg.kw_rx("mg.wait", lambda a: a, (("model_guards", "wait_words"),), re.I)),) if extra else ())
_BROAD = (("when", re.compile(r"\bwhen\b", re.I)), ("once", re.compile(r"\bonce\b", re.I)), ("after", re.compile(r"\bafter\b", re.I)), ("until", re.compile(r"\b(?:until|till)\b", re.I)))
_NEG_RX = re.compile(r"\b(?:no|not|never|without|nothing|none|nor|cannot)\b|n't\b|\b(?:can't|cant|don't|dont|doesn't|isn't|aren't|won't)\b", re.I)
_NEG_WINDOW = 4          # words before the match that may carry the negation ("no need to wait for", "not blocked on")
_CLAUSE_RX = re.compile(r"[,;:.]|\sbut\s", re.I)
_ASIDE_ONLY = ("until a date or item", "once X lands / merges / replies")      # the patterns a parenthesised aside does not trigger ("(the free trial keeps running until Mar 20th)")


def _negated(plain: str, start: int) -> bool:
    """A negation within four words before the match, in the same clause: a comma, semicolon, colon, full stop or " but " ends the reach of one ("no change needed, wait for CI")."""
    before = _CLAUSE_RX.split(plain[:start])[-1].split()[-_NEG_WINDOW:]
    return bool(_NEG_RX.search(" ".join(before)))


def _unaside(plain: str) -> str:
    """The text with every parenthesised span blanked (same length), for the patterns an aside does not trigger."""
    prev = None
    while prev != plain:
        prev = plain
        plain = re.sub(r"\([^()]*\)", lambda m: " " * len(m.group(0)), plain)
    return plain


def wait_lines(text: Any) -> tuple[list[tuple[str, str]], list[str]]:
    """What a next text says about waiting: ([(the line, the precise pattern it matched)], the broad words found in lines the precise list did not catch). A negation before the
    match ("no waiting for a slot", "not blocked on") passes it; a code span or a link is not read. Lines the server appends in parentheses are not read."""
    hits: list[tuple[str, str]] = []
    broad: list[str] = []
    for raw in _FENCE_RX.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), str(text or "")).splitlines():      # a fenced block is code, not a line of next
        line = clean(raw)
        if not line or line.startswith("(") or _MARK_RX.sub("", line).startswith("("):
            continue
        plain = _plain(line)
        hit = ""
        bare = _unaside(plain)
        for name, rx in _precise():
            for m in rx.finditer(bare if name in _ASIDE_ONLY else plain):
                if not _negated(bare if name in _ASIDE_ONLY else plain, m.start()):
                    hit = name
                    break
            if hit:
                break
        if hit:
            hits.append((line, hit))
            continue
        for name, rx in _BROAD:
            if any(not _negated(plain, m.start()) for m in rx.finditer(plain)) and name not in broad:
                broad.append(name)
    return hits, broad


# ---------------------------------------------------------------------------------------------------------------- a doing item whose words are a wait
# A valid reason to wait on an item does not warrant marking it as on agent and letting it sit there for hours: it should be marked waiting.
# The words of a wait on a time or an event, read in a line of next of an item that ends a write in the state doing. They are a note on the reply, never a refusal.
_WHEN = (rf"(?:\d{{1,2}}:\d{{2}}|\d{{1,2}}\s*(?:am|pm)\b|\d{{4}}-\d{{2}}-\d{{2}}|{_MONTH}\.?\s+\d|tomorrow|tonight|midnight|noon|(?:the\s+)?(?:morning|evening)\b|{_WEEKDAY}\b)")      # a time or a day: what makes until / waiting on a wait on a time (a builder's wait on its own CI or review is work in hand)
_RUN_NOUN = r"(?:run|runs|batch|job|timer|cron|tick)"
_DOING_WAIT: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("overnight", re.compile(r"\bovernight\b", re.I)),
    ("in the morning", re.compile(r"\bin\s+the\s+(?:morning|evening)\b", re.I)),
    ("tomorrow / tonight", re.compile(r"\b(?:until|till|by)\s+(?:tomorrow|tonight)\b|\b(?:tomorrow|tonight)\s+(?:morning|evening|night|at\s+\d)|\b(?:ends?|ending|runs?|finish(?:es)?|lands?|completes?|due|ready)\s+(?:tomorrow|tonight)\b|\b(?:tomorrow|tonight)'s\s+" + _RUN_NOUN + r"\b", re.I)),
    ("nightly / next run", re.compile(r"\bnightly\b|\bnext\s+(?:run|runs|tick|cycle|night|batch)\b", re.I)),
    ("once / after the run", re.compile(r"\b(?:once|when|after)\s+(?:the|its|their|this|that)\s+(?:(?!(?:test|tests|ci|build|suite|review)\b)\w+\s+){0,2}?" + _RUN_NOUN + r"\b", re.I)),
    ("until a time or day", re.compile(rf"\b(?:until|till)\s+(?:the\s+|a\s+|an\s+|its\s+)?{_WHEN}", re.I)),
    ("waiting on a time or day", re.compile(rf"\bwait(?:s|ing|ed)?\s+(?:for|on)\s+(?:the\s+|a\s+|an\s+|its\s+)?{_WHEN}", re.I)),
)


def _doing_wait() -> "tuple[tuple[str, re.Pattern[str]], ...]":
    """_DOING_WAIT, with the instance's own words for overnight ([keywords.model_guards] overnight_words) added to its first pattern."""
    extra = _cfg.kw_alt("model_guards", "overnight_words")
    if not extra:
        return _DOING_WAIT
    return (("overnight", _cfg.kw_rx("mg.overnight", lambda a: r"\bovernight\b" + _cfg.kw_pipe(a), (("model_guards", "overnight_words"),), re.I)),) + _DOING_WAIT[1:]


def reads_as_wait(text: Any) -> str:
    """The name of the first pattern by which this text (a line of next) reads as a wait on a time or an event rather than work in hand ("ends overnight",
    "in the morning", "once the run finishes", "until 09:00", "waiting on the 09:00 timer", "nightly"), else "". until and waiting on count only with a time or a day after them. A negation
    before the match ("no need to wait for") passes it; a code span or a link is not read. The wording of work in hand matches none: building, running tests until green, reviewing, a release
    running, a builder waiting on its own CI or review, "preparing tomorrow's demo"."""
    for raw in _FENCE_RX.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), str(text or "")).splitlines():
        plain = _plain(clean(raw))
        for name, rx in _doing_wait():
            if any(not _negated(plain, m.start()) for m in rx.finditer(plain)):
                return name
    return ""


# ---------------------------------------------------------------------------------------------------------------- a bare date whose next waits for that date
# "Work moving in real time is on agent, however long it takes. A wait-and-see window the work itself needs is waiting (parked)." A bare date is a wait until it outside a hand-off (the board lists the
# item as waiting); a wake the item still carries as one (a hand-off's backstop, or one stored before `until`) leaves it on agent, and when the item's next says the work waits for that date, the window
# is a park. A note on the reply, never a refusal.
_WINDOW_WORDS = r"(?:after|once|wait(?:s|ing|ed)?|until|till|collect(?:s|ing|ed)?|soak(?:s|ing|ed)?|then\s+review)"
_DURATION = r"for\s+\d+\s+(?:more\s+)?(?:hours?|days?|weeks?|nights?)"
_DAY_NAMES = ("mon(?:day)?", "tue(?:s(?:day)?)?", "wed(?:nesday)?", "thu(?:r(?:s(?:day)?)?)?", "fri(?:day)?", "sat(?:urday)?", "sun(?:day)?")
_MONTH_NAMES = ("jan(?:uary)?", "feb(?:ruary)?", "mar(?:ch)?", "apr(?:il)?", "may", "jun(?:e)?", "jul(?:y)?", "aug(?:ust)?", "sep(?:t(?:ember)?)?", "oct(?:ober)?", "nov(?:ember)?", "dec(?:ember)?")
_NOT_A_WAIT = r"(?!(?:due|by|before|deadline)\b)"      # "after review due 2099-03-02" is a deadline, not a wait for the day


def _wake_date_alts(d: Any) -> str:
    """The ways a line can write the day `d` (a date), as regex alternatives: 2099-03-02, Mar 2 / March 2nd, 2 Mar / 2nd of March, 3/2, each with a leading word boundary."""
    mon, day, ord_ = _MONTH_NAMES[d.month - 1], f"0?{d.day}", r"(?:st|nd|rd|th)?"
    return "|".join(f"(?:{f})" for f in (rf"\b{re.escape(d.isoformat())}(?!\d)", rf"\b{mon}\.?\s+{day}{ord_}\b", rf"\b{day}{ord_}\s+(?:of\s+)?{mon}\b", rf"\b0?{d.month}/{day}\b"))


def _wake_window_rx(wake: Any) -> "re.Pattern[str] | None":
    """The ways a line of next can say the work waits for a wake's day, as one regex whose groups w1-w3 are the waiting word. None for a wake that is not YYYY-MM-DD[THH:MM].
    The day is its date, a month-day form (Mar 2, March 2nd, 2 Mar, 2nd of March) or 3/2, each with a leading word boundary, and it counts when
    a waiting word reaches it in the same clause: at most three words between, no comma, semicolon, colon or bracket, and none of due / by / before / deadline ("ship after review,
    due 2099-03-02" is a deadline). A weekday counts only right after the waiting word ("wait until Monday"), never as "demo on Monday". After a duration ("collect logs for 2 days,
    then review on Mar 2") the day may follow a comma."""
    import datetime as _dt
    try:
        d = _dt.date.fromisoformat(str(wake or "")[:10])
    except ValueError:
        return None
    date = _wake_date_alts(d)
    gap = rf"(?:\s+{_NOT_A_WAIT}[\w'-]+){{0,3}}"
    near = rf"\b(?P<w1>{_WINDOW_WORDS}){gap}\s+(?:on\s+)?(?:{date})"
    weekday = rf"\b(?P<w2>{_WINDOW_WORDS})\s+(?:on\s+)?(?:the\s+)?(?:{_DAY_NAMES[d.weekday()]})\b"
    after_duration = rf"\b(?P<w3>{_DURATION})\b[^;:()\n]{{0,60}}?(?:{date})"
    return re.compile("|".join((near, weekday, after_duration)), re.I)


def _window_hit(text: Any, wake: Any) -> "tuple[str, str]":
    """(the first line of `text` that says the work waits for the wake's own day, its waiting word) or ("", "")."""
    rx = _wake_window_rx(wake)
    if rx is None:
        return "", ""
    for raw in _FENCE_RX.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), str(text or "")).splitlines():
        line = clean(raw)
        if not line or line.startswith("(") or _MARK_RX.sub("", line).startswith("("):
            continue
        plain = _plain(line)
        for m in rx.finditer(plain):
            k = next(k for k in ("w1", "w2", "w3") if m.group(k))
            if not _negated(plain, m.start(k)):
                return line, clean(m.group(k)).lower()
    return "", ""


def reads_as_window(text: Any, wake: Any) -> str:
    """The waiting word of the first line of next that says the work waits for the wake's own day ("collect logs until 2099-03-02, then review", "after Mon Mar 2nd", "soak for 3 days, check Mar 2",
    "wait until Monday"; the rules for how near the day must be are in _wake_window_rx), else "". A negation before the word ("no need to wait") passes it; a code span, a link, a fenced block
    and the lines the server appends in parentheses are not read."""
    return _window_hit(text, wake)[1]


def window_line(text: Any, wake: Any) -> str:
    """The first line of `text` that says the work waits for the wake's own day (reads_as_window's line, not its word), else "": the wait reason a hold with a wake already carries in its words."""
    return _window_hit(text, wake)[0]


# ---------------------------------------------------------------------------------------------------------------- a bare date whose own step is timed
# The window note above reads a next that waits "until / after" the wake's day. Two more ways a mover's step waits and the item sits on agent with a wake alone: the step OPENS with a time at the
# wake's own hour or day ("at 03:00 install the config", "on Mar 3rd ...", "tomorrow at 9 ..."), or it starts on an outside event ("when the next release lands, check ...", "once the vendor
# replies ..."). Same kind of note on the reply, never a refusal; the server decides who the mover is and whether another party's step is in flight (server._wake_step_note). A time or day
# in the middle of a step ("the cron runs at 03:00 daily; fix the script now", "schedule the job at 03:00") is the step's content, not its trigger, so only the opening phrase (or the one after "then") counts.
_TZ_OTHER = r"(?!\s*(?:utc|gmt|z)\b)"        # a time said in another zone than the instance's is not the wake's hour
def _zone_label() -> str:
    """The instance zone's own abbreviation(s) after a clock time ("at 03:00 CET"), optional: the wake's zone is the instance's."""
    return r"(?:\s*(?:" + "|".join(re.escape(x) for x in _cfg.tz_labels()) + r")(?![A-Za-z0-9]))?"


def _clock_pattern() -> str:
    return rf"(?:(?:at|@)\s*(?:(?P<h1>\d{{1,2}}):(?P<m1>\d{{2}})\s*(?P<a1>am|pm)?|(?P<h2>\d{{1,2}})\s*(?P<a2>am|pm))\b{_TZ_OTHER}{_zone_label()})"
_EVENT_OPEN_RX = re.compile(r"^(?:then[,\s]+)?(?P<w>when|whenever|once|as\s+soon\s+as|upon|after)\b", re.I)
_EVENT_VERB_RX = re.compile(r"\b(?:lands?|landed|ships?|shipped|merges?|merged|released|replies|replied|reply|responds?|responded|arrives?|arrived|publish(?:es|ed)?|approves?|approved|"
                            r"answers?|answered|comes?\s+out|is\s+(?:out|live|available|published|released|cut)|goes?\s+(?:live|out)|appears?|appeared|rolls?\s+out|announces?|announced|"
                            r"opens?|opened|signs?|signed|confirms?|confirmed|posted|expires?|rotates?)\b", re.I)
_EVENT_NEXT_RX = re.compile(r"^(?:then[,\s]+)?after\s+(?:the\s+)?next\s+(?:(?:minor|major|patch|stable|beta|new)\s+)?(?:releases?|versions?|deploy(?:ment)?s?|windows?|rollouts?|patch(?:es)?|updates?|tags?|cycles?|runs?\s+of\s+\S+)\b", re.I)
_OWN_CI_RX = re.compile(r"\b(?:tests?|ci|builds?|suites?|checks?|pipeline|lint)\b", re.I)      # a builder waiting on its own CI is work in hand, as in reads_as_wait
_SELF_RX = re.compile(r"\b(?:i|we|you|me|us|my|our|your)\b|\b(?:i'm|we're|you're)\b", re.I)    # a clause whose subject is the writer's own side is the mover's own action, not an outside event
_REPLY_RX = re.compile(r"\b(?:repl(?:y|ies|ied)|respond\w*|approv\w*|answer\w*|confirm\w*|sign(?:s|ed)?)\b", re.I)
_QUOTED_RX = re.compile(r"(?<!\w)'[^'\n]+'(?!\w)")
_ANY_DATE_RX = re.compile(r"^(?:on|until|till)\s+(?:\d{4}-\d{2}-\d{2}|[a-z]{3,9}\.?\s+\d{1,2}|\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?[a-z]{3,9}|\d{1,2}/\d{1,2})", re.I)
_CLAUSE_SPLIT_RX = re.compile(r"[,;:]")


def is_reply_trigger(phrase: Any) -> bool:
    """Does a phrase reads_as_timed_step returned name a reply, approval, answer or confirmation (a named party outside answering) as the trigger?"""
    return bool(_REPLY_RX.search(str(phrase or "")))


def _wake_parts(wake: Any) -> "tuple[Any, str] | None":
    """(the wake's date, its "HH:MM" or "") for a wake of YYYY-MM-DD[THH:MM], else None."""
    import datetime as _dt
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}))?", str(wake or "").strip())
    if not m:
        return None
    try:
        return _dt.date.fromisoformat(m.group(1)), m.group(2) or ""
    except ValueError:
        return None


def _clock_value(m: "re.Match[str]") -> str:
    """The "HH:MM" (24-hour) of a _CLOCK match, "" for an hour that is no hour."""
    h, mi, ap = (m.group("h1"), m.group("m1"), m.group("a1")) if m.group("h1") else (m.group("h2"), "00", m.group("a2"))
    hh = int(h)
    if ap:
        if not 1 <= hh <= 12:
            return ""
        hh = hh % 12 + (12 if ap.lower() == "pm" else 0)
    return f"{hh:02d}:{mi}" if hh <= 23 and int(mi) <= 59 else ""


def _lead_time(plain: str, day: Any, hhmm: str, today: Any) -> str:
    """The time phrase that OPENS `plain` (a step without its opener), if it is the wake's: any run of "at <clock>", "on|until|after|once <the wake's day>" and "tomorrow [at …|morning …]",
    in either order. Every clock in the run must be the wake's own time of day (a wake with none matches no clock); "tomorrow" needs `today` and a wake the day after it; a run that is followed by
    another day ("at 03:00 on Mar 5th") does not match. "" when the text does not open with one."""
    import datetime as _dt
    wk, mon = "(?:" + "|".join(_DAY_NAMES) + ")", "(?:" + "|".join(_MONTH_NAMES) + ")"
    date = _wake_date_alts(day)
    day_rx = re.compile(rf"(?:(?:on|until|till|after|once)\s+(?:(?P<wd>{wk})\.?,?\s+)?(?:{date}))"                       # "on Mar 6th", "on Fri Mar 6th"
                        rf"|(?:on\s+(?P<wd2>{wk})\b(?!\.?,?\s+(?:\d|{mon}\b)))"                                             # "on Fri" alone, not "on Fri Mar 13th"
                        rf"|(?:(?:(?P<wd3>{wk})\.?,?\s+)?(?:{date})\s*:)", re.I)                                                # "Mar 6: run ...", "Fri Mar 6: run ..."
    wake_wd = day.strftime("%a").lower()
    in_week = today is None or 0 <= (day - today).days <= 6

    def day_match(rest: str) -> "re.Match[str] | None":
        m = day_rx.match(rest)
        if not m:
            return None
        named = m.group("wd") or m.group("wd3") or m.group("wd2")
        if named and named[:3].lower() != wake_wd:
            return None                                   # a weekday that is not the wake's
        if m.group("wd2") and not in_week:
            return None                                   # a bare weekday names the wake's day only within the week ahead
        return m
    tom_rx = re.compile(r"tomorrow(?=\s+(?:at\b|@|morning|afternoon|evening|night|noon|midnight))(?:\s+(?:morning|afternoon|evening|night|noon|midnight))?", re.I)
    clock_rx = re.compile(_clock_pattern(), re.I)
    bare_rx = re.compile(rf"(?:at|@)\s*(\d{{1,2}})\b(?![:/]|\s*(?:am|pm|min|minutes?|hours?|h|files?|times?)\b){_TZ_OTHER}{_zone_label()}", re.I)
    pos, got_clock, got_day = 0, [], False
    while True:
        rest = plain[pos:]
        skip = len(rest) - len(rest.lstrip(" ,"))
        rest = rest[skip:]
        if m := clock_rx.match(rest):
            got_clock.append(_clock_value(m))
        elif m := day_match(rest):
            got_day = True
        elif got_day and (m := bare_rx.match(rest)):          # "tomorrow at 9": a bare hour counts after a day word
            got_clock.append(f"{int(m.group(1)):02d}:00" if int(m.group(1)) <= 23 else "")
        elif m := tom_rx.match(rest):
            if today is None or day != today + _dt.timedelta(days=1):
                return ""
            got_day = True
        else:
            break
        pos += skip + m.end()
    if not got_clock and not got_day:
        return ""
    if any(c != hhmm for c in got_clock):
        return ""                                  # a written time that is not the wake's hour (or a wake with no time of day)
    if got_day and not got_clock and today is not None and day == today:
        return ""                                  # "on <today> run it" with the wake later today: it can run now, a clock time on today still counts
    if _ANY_DATE_RX.match(plain[pos:].lstrip(" ,")):
        return ""                                  # ... then on another day
    return clean(plain[:pos]).lower()


def reads_as_timed_step(text: Any, wake: Any, today: Any = None, dated_only: bool = False) -> str:
    """What makes this step (one line of next, its `<name>: ` opener already off) wait, as a short phrase, else "". The step must OPEN with it (or the phrase follows "then"):
    a time at the wake's own hour ("at 03:00 …" on a wake of ...T03:00; the wake needs a time of day, and a time said in UTC / GMT is not read), the wake's day ("on Mar 3rd", "on 2099-03-03",
    "after Mar 3rd"; by / before / due are no wait), or "tomorrow at …" / "tomorrow morning" (when `today`, a date, is given and the wake is the day after it); a written time must be the wake's
    time, and a day the wake's day. Or the step starts on an outside event: a trigger word (when, once, whenever, as soon as, upon, after) that opens the line and an event verb within its first
    clause ("when the next release lands, check …", "once the vendor replies …", with or without the comma), or "after the next release / version / deploy / window / run of <job>". Not read: a clause whose
    subject is you, I or we, or that is only a bare verb-noun ("upon merge"); a clause about tests, a build or CI (the builder's own wait); a negation before the word ("no need to wait"); a code
    span, a single-quoted span, a link or a fenced block. `dated_only` reads the time half alone (the wake's own hour or day), never the outside event, and only at the line's start, never after a \"then\" (\"build it now, then at 08:00 verify\" opens with work to do now). The wake's day is also \"on Fri Mar 6th\", \"on Fri\" (the wake's weekday within the week ahead) and \"Mar 6: …\"; a day-only step on today itself (the wake later today) is work to do now, no wait."""
    parts = _wake_parts(wake)
    if parts is None:
        return ""
    day, hhmm = parts
    first = next((ln for ln in _FENCE_RX.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), str(text or "")).splitlines() if ln.strip()), "")
    plain = _MARK_RX.sub("", _QUOTED_RX.sub(lambda m: " " * len(m.group(0)), _plain(clean(first))).replace("**", "")).strip()
    if not plain:
        return ""
    for st in [0] + ([] if dated_only else [m.end() for m in re.finditer(r"\bthen[,\s]+", plain, re.I)]):      # the step's start, and (the note's reading only) the text after each "then"
        if st and _negated(plain, st - 1):
            continue
        if why := _lead_time(plain[st:], day, hhmm, today):
            return why
    if dated_only:
        return ""
    m = _EVENT_OPEN_RX.match(plain)
    if m and not _negated(plain, m.start("w")):
        nx = _EVENT_NEXT_RX.match(plain)
        if nx:
            return clean(plain[:nx.end()]).lower()
        clause = " ".join(_CLAUSE_SPLIT_RX.split(plain[m.end():], 1)[0].split()[:9])      # the first clause, up to nine words (a comma is optional)
        v = _EVENT_VERB_RX.search(clause)
        if v:
            head = clause[:v.end()]
            if len(head.split()) >= 2 and not _SELF_RX.search(head) and not _OWN_CI_RX.search(head):
                return clean(f"{m.group('w')} {head}").lower()
    return ""


# ---------------------------------------------------------------------------------------------------------------- a next line that defers on another item in words
_DEFER_WORD_RX = re.compile(r"\b(?:once|after|when|until|till|before|as\s+soon\s+as)\b", re.I)
_BOARD_REF_RX = re.compile(r"\bboard#([1-9]\d*)", re.I)
_SENTENCE_END_RX = re.compile(r"[.;:!?\n]")
_DEFER_REACH = 8         # words after the deferring word that may hold the id ("once the owner's steps are done", "when the review in an earlier change lands")
# Another language puts the trigger after the id ("board#N closes", "after board#N", in a language where the word comes last): the instance's own phrases ([keywords.model_guards] defer_after_id:
# closes, is done, after, until, before) are looked for right after the id. None configured: no such check.
_AFTER_ID_REACH = 30     # characters after the id in which such a trigger may stand (within the same sentence, no comma or bracket between)


def _enclosed(window: str, start: int, end: int) -> bool:
    """Is the id set off from the sentence, "" or ",": a bracket or a comma right before it and a bracket or a comma right after?"""
    before = window[:start].rstrip()[-1:]
    after = window[end:].lstrip()[:1]
    return before in ("(", ",") and after in (")", ",")


def deferral_refs(text: Any) -> list[tuple[str, list[str]]]:
    """The next lines that defer on an item in words → [(the line, [board#N …])]. English: a deferring word (once, after, when, until, till, before, as soon as) followed, in the same sentence
    (a full stop, semicolon, colon, ! or ? ends it) and within eight words, by a `board#N`; a comma or a bracket between the word and the id breaks it ("After the review, board#N is next" is
    not a deferral) unless the id is set off by brackets or commas ("once the review lands", "once the review, board#N, lands"). Another language: a `board#N` followed within thirty characters,
    in the same sentence and with no comma or bracket between, by one of the instance's own phrases ([keywords.model_guards] defer_after_id), for a language that puts the trigger after the id. Every id in that reach counts.
    A negation before the English word ("not until", "no need to wait until") passes it; a code span, a link target and a fenced block are not read, and neither are the lines the server appends in
    parentheses. An id before an English word ("board#N is the review before the release") is not deferred on."""
    out: list[tuple[str, list[str]]] = []
    after_id = _cfg.kw_rx("mg.afterid", lambda a: a, (("model_guards", "defer_after_id"),), re.I) if _cfg.kw_alt("model_guards", "defer_after_id") else None
    for raw in _FENCE_RX.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), str(text or "")).splitlines():
        line = clean(raw)
        if not line or line.startswith("(") or _MARK_RX.sub("", line).startswith("("):
            continue
        plain = _plain(line)
        refs: list[str] = []
        def add(r: str) -> None:
            ref = f"board#{r}"
            if ref not in refs:
                refs.append(ref)
        for m in _DEFER_WORD_RX.finditer(plain):
            if _negated(plain, m.start()):
                continue
            tail = plain[m.end():]
            end = _SENTENCE_END_RX.search(tail)
            tail = tail[:end.start()] if end else tail
            cut, n = len(tail), 0                       # the reach: the first eight words
            for w in re.finditer(r"\S+", tail):
                n += 1
                if n > _DEFER_REACH:
                    cut = w.start(); break
            window = tail[:cut]
            for r in _BOARD_REF_RX.finditer(window):
                if not re.search(r"[,()]", window[:r.start()]) or _enclosed(window, r.start(), r.end()):
                    add(r.group(1))
        for r in _BOARD_REF_RX.finditer(plain):
            tail = plain[r.end():]
            end = re.search(r"[.;:!?\n,()、，。；：！？（）]", tail[:_AFTER_ID_REACH])      # the full-width marks of a language written without spaces end the phrase too
            seg = tail[:end.start()] if end else tail[:_AFTER_ID_REACH]
            if re.match(r"\d", seg[:1]):
                continue
            if after_id is not None and after_id.search(seg):
                add(r.group(1))
        if refs:
            out.append((line, refs))
    return out


def unwaited_deferrals(text: Any, after: Any, named_open: Callable[[str], str], canon: Callable[[str], str] | None = None, gid: str = "") -> list[tuple[str, list[str]]]:
    """The next lines in `text` that defer on an open item `after` does not name → [(the line, [board#N …])]. `named_open("board#N")` → the store id of that item when it exists and is
    open, else "" (a closed or unknown item is nothing to wait for); `canon(id)` → an id as `after` stores it; `gid` = the item itself (never a deferral on itself). The one test of the
    next_defers guard."""
    norm = canon or str
    stored = {norm(str(x)) for x in after if str(x).strip()} if isinstance(after, list) else set()
    bad: list[tuple[str, list[str]]] = []
    for line, refs in deferral_refs(text):
        miss = []
        for r in refs:
            g = named_open(r)
            if g and g != gid and norm(g) not in stored:
                miss.append(r)
        if miss:
            bad.append((line, miss))
    return bad


# ---------------------------------------------------------------------------------------------------------------- the description's form
DESC_PARA_MAX = 300      # a paragraph or a bullet longer than this (characters, links counted as their words) is a thick block
DESC_BLOCK_MAX = 400     # a description longer than this with no bullet at all is one too
_BULLET_RX = re.compile(r"^[ \t]*(?:[-*+\u2022]|\d+[.)])[ \t]+\S")
_MARKER_RX = re.compile(r"^[ \t]*(?:[-*+\u2022]|\d+[.)])[ \t]+")
_QUOTE_LINE_RX = re.compile(r"^[ \t]*>")
_MDLINK_RX = re.compile(r"\[([^\]\n]*)\]\([^)\s]*\)")
_BARE_URL_RX = re.compile(r"https?://\S+")


def description_units(text: Any) -> tuple[list[str], bool]:
    """([the prose units of a description], whether any is a bullet). A unit is one bullet (its marker line and its indented continuation lines) or one run of plain lines
    between blank lines and bullets. Fenced code blocks and `>` quoted lines are not prose and make no unit. A link counts as its words and a bare URL as four characters,
    so a long address is not read as a long paragraph."""
    units: list[tuple[str, bool]] = []
    cur: list[str] = []
    cur_bullet = False

    def flush() -> None:
        nonlocal cur, cur_bullet
        if cur:
            units.append((clean(" ".join(cur)), cur_bullet))
        cur, cur_bullet = [], False

    for raw in _FENCE_RX.sub("\n", str(text or "")).splitlines():
        if _QUOTE_LINE_RX.match(raw) or not raw.strip():
            flush()
            continue
        if _BULLET_RX.match(raw):
            flush()
            cur, cur_bullet = [_MARKER_RX.sub("", raw, count=1)], True
        elif cur_bullet and raw[:1] in (" ", "\t"):
            cur.append(raw)
        else:
            if cur_bullet:
                flush()
            cur.append(raw)
    flush()
    prose = [(_BARE_URL_RX.sub("link", _MDLINK_RX.sub(r"\1", u)), b) for u, b in units]
    return [u for u, _ in prose if u], any(b for _, b in prose)


def description_problem(text: Any) -> str:
    """"" when the description reads as short bullets (or is short); else the guidance: what is thick, and how to write it. A paragraph or a bullet over DESC_PARA_MAX
    characters, or more than DESC_BLOCK_MAX characters in all with no bullet, is a thick block."""
    units, bulleted = description_units(text)
    if not units:
        return ""
    longest = max(len(u) for u in units)
    total = sum(len(u) for u in units)
    if longest > DESC_PARA_MAX:
        why = f"has a paragraph of {longest} characters"
    elif total > DESC_BLOCK_MAX and not bulleted:
        why = f"is {total} characters with no bullet"
    else:
        return ""
    return (f"description {why}: {_owner_display()} reads it on the item page, so write it as short `- ` bullets, one line each (what it is, the links, his words), never a paragraph. "
            "A fenced code block or a `>` quote is not counted.")


def owner_names_cf() -> set[str]:
    """The names a line of next may open with for the owner, casefolded: [instance] owner and owner_aliases."""
    return {n.casefold() for n in _cfg.owner_names()} | {_owner_display().casefold()}


def next_openers(text: Any) -> list[tuple[str, str]]:
    """[(line, name)] for every top-level next line: the name before its colon ("" when it opens with none). Server notes in parentheses, indented continuation lines and
    blank lines are not lines of the item's own next."""
    out: list[tuple[str, str]] = []
    for raw in _FENCE_RX.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), str(text or "")).splitlines():      # a fenced block and its fence lines are code, not lines of next
        if not raw.strip() or raw[:1] in (" ", "\t"):
            continue
        c = _MARK_RX.sub("", raw.strip().replace("**", ""))
        if not c or c.startswith("("):
            continue
        m = _NAME_RX.match(c)
        out.append((clean(raw), m.group("name") if m else ""))
    return out


def owner_next_lines(text: Any, roster: "set[str] | None" = None) -> list[tuple[str, str]]:
    """[(line, text)] for every top-level next line that starts with the owner's name: the same lines that read as his in next_openers (`<owner>:` and the [instance] owner_aliases) and the
    opener states.next_names_owner knows (`you:`, "<owner> to …"). `line` is the opening line as written, `text` the line without its marker and opener plus its indented continuation lines and any
    closed fenced block under it (an unclosed fence is no fence, as in next_openers), the text the step's command check reads. An indented line that starts with another session's `<name>:` (`roster`,
    casefolded names) ends his line, and so does everything indented under it. Lines for other sessions, server notes in parentheses and the owner's name inside a line's body are not his lines."""
    owners = owner_names_cf()
    src = str(text or "")
    in_fence: set[int] = set()
    for fm in _FENCE_RX.finditer(src):
        first = src.count("\n", 0, fm.start())
        in_fence.update(range(first, first + fm.group(0).count("\n") + 1))
    out: list[tuple[str, list[str]]] = []
    cur: list[str] | None = None
    for idx, raw in enumerate(src.splitlines()):
        if idx in in_fence:                                   # a closed fenced block belongs to the line above, whoever's it is; its lines are no lines of next
            if cur is not None:
                cur.append(raw)
            continue
        if not raw.strip():
            continue
        if raw[:1] in (" ", "\t"):
            if cur is not None:
                nm = _NAME_RX.match(_MARK_RX.sub("", raw.strip().replace("**", "")))
                if nm and roster and nm.group("name").casefold() in roster and nm.group("name").casefold() not in owners:
                    cur = None                                # another session's line, indented under his: his line has ended
                else:
                    cur.append(raw)
            continue
        c = _MARK_RX.sub("", raw.strip().replace("**", ""))
        cur = None
        if not c or c.startswith("("):
            continue
        m = _NAME_RX.match(c)
        if m and m.group("name").casefold() in owners:
            body = c[m.end():].strip()
        elif _cfg.owner_opener_rx().match(c):
            body = c
        else:
            continue
        cur = [body]
        out.append((clean(raw), cur))
    return [(line, "\n".join(parts)) for line, parts in out]


def ask_to_run(body: str, roster: "set[str] | None" = None) -> str:
    """The text of his next line the Windows check judges ("" when the line does not ask him to run anything): a line with an imperative run cue (run, type, execute, enter, and the instance's own run_commands; paste only beside a
    terminal or shell; not "I will run", "to run", "the run", or a session's name before it) or a line, its continuation lines included, that opens with a place phrase ("In PowerShell:"). A command named before the cue ("decide whether `x y` …, then run `z w`") is only mentioned: its backticks are taken off so
    the check reads the commands from the cue on. A line that only mentions a command (approve `x y`, the fix is `z w`, paste this reply:) is not judged."""
    pos = _sc.run_cue(body, roster)
    if pos is None:
        return ""
    return _sc.SPAN_RX.sub(lambda m: m.group(1), body[:pos]) + body[pos:]


def _words_rx() -> "re.Pattern[str]":
    """The wait and date words of a stored quote; the instance's own ([keywords.dates]: tomorrow, next week, next month, and a number followed by a month or day word; [keywords.waiting] park_words) add to the English ones."""
    def build(tomorrow: str, next_week: str, next_month: str, month: str, day: str, park: str) -> str:
        num = "|".join(x for x in (month, day) if x)
        return (r"\bwait|\buntil\b|\btill\b|\bpark|postpone|defer|snooze|\bhold\b|put (?:it |this )?off|remind|\bresume\b|tomorrow|tonight|next\s+(?:week|month|year)|\bin\s+\d+\s+(?:day|week|month)s?\b|"
                rf"\b{_MONTH}\.?\s+\d|\b{_WEEKDAY}\b|\d{{4}}-\d{{2}}-\d{{2}}" + _cfg.kw_pipe(tomorrow) + _cfg.kw_pipe(next_week) + _cfg.kw_pipe(next_month) + _cfg.kw_pipe(park) + (rf"|\d(?:{num})" if num else ""))
    return _cfg.kw_rx("mg.words", build, tuple(("dates", k) for k in ("tomorrow", "next_week", "next_month", "month_suffix", "day_suffix")) + (("waiting", "park_words"),), re.I)


def has_wait_words(quote: Any) -> bool:
    """Does the owner's stored quote park, wait, say until or name a date (waiting.park_words, plus the wait and date words)?"""
    q = str(quote or "")
    return bool(q.strip()) and (_wt.park_words(q) or bool(_words_rx().search(q)))


# ---------------------------------------------------------------------------------------------------------------- who can move an item
class Ctx:
    """What a judgement reads that is not in the item: the clock, the shown form of an id and of a session, and a snapshot of the sessions and project pages (read once, on first
    use, and kept for this Ctx: a write or a whole report takes one)."""

    def __init__(self, now: float | None = None, label: Callable[[str], str] | None = None, shown: Callable[[str], str] | None = None) -> None:
        self.now = time.time() if now is None else now
        self.label = label or str
        self.shown = shown or str
        self._rows: dict[str, dict[str, Any]] | None = None
        self._roles: dict[str, dict[str, str]] | None = None
        self._reg: dict[str, dict[str, Any]] | None = None
        self._roster: set[str] | None = None

    def rows(self) -> dict[str, dict[str, Any]]:
        if self._rows is None:
            try:
                self._rows = _fleet.sessions()
            except Exception:  # noqa: BLE001
                self._rows = {}
        return self._rows

    def roles(self) -> dict[str, dict[str, str]]:
        if self._roles is None:
            try:
                self._roles = _anc.session_roles()
            except Exception:  # noqa: BLE001
                self._roles = {}
        return self._roles

    def reg(self) -> dict[str, dict[str, Any]]:
        if self._reg is None:
            try:
                self._reg = _anc.registry()
            except Exception:  # noqa: BLE001
                self._reg = {}
        return self._reg

    def roster(self) -> set[str]:
        """Every session name an item's next may start a line with (casefolded): the pages' agents, the fleet's names, the registry's names and aliases."""
        if self._roster is None:
            names = set(self.roles())
            names |= {str(r.get("name")) for r in self.rows().values() if isinstance(r, dict) and r.get("name")}
            try:
                names |= set(_sr.all_names().values())
                for sid in list(_sr.load().rows):
                    names |= set(_sr.names_of(sid))
            except Exception:  # noqa: BLE001
                pass
            self._roster = {n.casefold() for n in names if n}
        return self._roster

    def background_of(self, who: str, project: str) -> bool:
        """Is `who` a background agent of the project's hub (a `background:` entry of its page's agents map)?"""
        roles = self.roles()
        names = {who}
        try:
            names |= {_sr.display_name(who) or "", *_sr.names_of(who)}
        except Exception:  # noqa: BLE001
            pass
        key = next((n for n in names if n and n in roles and roles[n].get("role") == "back"), "")
        if not key or not project:
            return False
        reg = self.reg()
        try:
            return _anc.hub_of(roles[key].get("project", ""), reg) == _anc.hub_of(project, reg)
        except Exception:  # noqa: BLE001
            return False

    def session_state(self, who: str) -> str:
        """live | retired | gone | cloud | unknown | blind for a session reference. `live`: the session registry holds it and has not retired it, or a fleet heartbeat row
        carries its id or name and is present (running, or gone less than the grace). `cloud`: a cse_ id, which no registry holds and which is accepted. `blind`: there is no
        registry and no heartbeat at all, so nothing can be judged and nothing is refused."""
        try:
            sid = _sr.resolve(who)
            row = _sr.row(sid) if sid else None
        except Exception:  # noqa: BLE001
            row = None
        if row:
            return "live" if row.get("state") == "live" else "retired"
        rows = self.rows()
        mine = [r for k, r in rows.items() if isinstance(r, dict) and (k == who or str(r.get("name") or "") == who)]
        if mine:
            return "live" if any(_fleet.present(r, self.now) for r in mine) else "gone"
        if who.startswith("cse_"):
            return "cloud"
        try:
            registry_known = _sr.available()
        except Exception:  # noqa: BLE001
            registry_known = False
        return "unknown" if (rows or registry_known) else "blind"

    def mover_problem(self, who: Any, project: str) -> str:
        """"" when `who` can be a mover (or a post-wake mover): the owner, a background agent of the project, or a live session; else why not, in words."""
        w = clean(who)
        if not w:
            return "is no one"
        if _model.is_owner(w) or self.background_of(w, project):
            return ""
        st = self.session_state(w)
        if st in ("live", "cloud", "blind"):
            return ""
        return {"retired": "is a retired session", "gone": "is a session whose pane is gone", "unknown": "is no session the registry or the fleet knows"}.get(st, "is not a live session")


def owner_mover_gap(m: dict[str, Any], mod: "_model.Model") -> str:
    """"" when an alive item whose mover is the owner has what the owner acts on; else what is missing, in words (the mirror of mover_state, which refuses an agent beside his state,
    this refuses him beside an agent's). Only an alive item with him as the mover is judged: a waiting item (outside, blocked, parked, verifying) has no mover, a closed one is never judged.
    He acts on a step (state your-step with its step), an ask (state your-call or needs decision; the ask line itself is the ask rule's, [ask] refuse_after) and nothing else: an item that
    is doing or queued (stored or derived) with him as the mover shows him no Your step and no ask on its page."""
    if mod.state != _model.ALIVE or not _model.is_owner(mod.mover):
        return ""
    if not _model.owner_state(m, mod.today):
        return f"its state is {mod.today or 'doing'}, an agent's"
    if mod.today == "your-step" and not _states.carry_text("step", m.get("step")):
        return "state your-step carries no step"
    return ""


def _owner_display() -> str:
    return _model.owner_display()


# ---------------------------------------------------------------------------------------------------------------- the judgement
WAIT_DROP_HINT = " If the item should not wait, drop the wait with update clear_wait=true (wait_kind, wait_anchor, wait_event, ask_by and post_wake_mover go together)."


def _wait_text(w: "_model.Wait") -> str:
    return {"time": "a time", "anchor": "an anchor event", "item": "another item's close", "relay": f"news only {_owner_display()} relays", "event": "a fleet event"}.get(w.kind, w.kind)


def check(item: dict[str, Any], ctx: Ctx, *, touched: "frozenset[str] | set[str] | None" = None, gid: str = "", after_open: Callable[[dict[str, Any]], Any] | None = None,
          anchored: Callable[[dict[str, Any]], Any] | None = None, needs: list[str] | None = None, hold: bool | None = None, one_mover: bool = True, until_wait: bool = False, date_given: bool = False, hold_given: bool = False,
          next_text: str | None = None, windows_text: str | None = None, creating: bool = False, defers_text: str | None = None,
          named_open: Callable[[str], str] | None = None, canon: Callable[[str], str] | None = None) -> tuple[list[Problem], list[str]]:
    """(what the item, as the write leaves it, has wrong, the broad wait words its next uses). `item` is the open item after the write (a dict with status, subject, metadata);
    `touched` the fields the write sets (None: all of them: a create, a report); `needs` and `hold` override what the metadata says (the server's own naming of the writer in
    needs is not a mover the writer made; a hold the old rule drops silently is still a hold the write set). `next_text`: the lines of next the write itself set, when next is kept by writer and the write left
    other sessions' lines in place: the text guards on next judge these, not lines another session wrote and this write did not touch (None: all of next). `windows_text`: the same for the Windows-command guard on his next lines, which
    never rejudges a stored line: an update passes the lines it sets ("" when it leaves next alone, whatever else it judges whole), a create or the report None (all of next). `until_wait`: the wait stands on a stored `until` (a wait on the date alone carries no snooze reason: that guard judges a time wait stated as one). `date_given`, `hold_given`: this write gives the date, and hold=true beside it (the snooze guard judges only a date a write gives to a time wait stated as one). `creating`: the write is a create, whose refusals offer only the fixes a create can make (it takes no state and no clear_mover). `defers_text`, `named_open`, `canon`: the next_defers guard. `defers_text` = the lines of next the write sets ("" when it leaves next alone: a stored line is never rejudged; None, a create or the report, judges all of next);
    `named_open("board#N")` → the store id of that item when it exists and is open, else "" (the guard is off without it); `canon(id)` → an id as `after` stores it. A closed item is never judged."""
    if item.get("status") == "completed":
        return [], []
    m = item.get("metadata") or {}
    full = touched is None
    tch = frozenset(touched or ())
    runs = (lambda *names: full or bool(tch & set(names)))
    state_run = full or bool(tch & STATE_FIELDS)
    what = ctx.shown(gid) if gid else "this item"
    H = _owner_display()
    out: list[Problem] = []
    flags: list[str] = []
    add = lambda key, text: out.append(Problem(key, text))
    nds = _wt.needs_of(m) if needs is None else list(needs)
    held = bool(m.get("hold")) if hold is None else hold
    nxt = m.get("next") if next_text is None else next_text
    # ---- the text guards, on the fields the write sets
    for fname, text in (("subject", item.get("subject")), ("ask", m.get("ask")), ("next", nxt)):
        if text and runs(fname):
            w, repl = alarm_in(text)
            if w:
                add("alarm", f"{fname} uses \"{w}\": {H} reads this, so say what happened in everyday words ({repl or 'a plainer word'}), and write the line again. Put file names, commands and code in backticks.")
    if item.get("description") and runs("description"):
        why_ = description_problem(item.get("description"))
        if why_:
            add("description", why_)
    for fname, text in (("goal", m.get("goal")), ("next", nxt), ("ask", m.get("ask")), ("wait_event", m.get("wait_event"))):
        if text and runs(fname):
            f_ = filler_in(fname, text)
            if f_:
                add("filler", f"{fname} holds a placeholder ({f_!r}): write the real {fname}, or leave it out until it is known.")
    mod = None
    try:
        mod = _model.derive(item, ctx.now, after_open, anchored)
    except Exception:  # noqa: BLE001  — a reading that fails judges nothing
        mod = None
    wtext = m.get("next") if windows_text is None else windows_text
    if wtext and runs("next"):      # his lines that ask him to run something pass the step's Windows-command check: the same judgement, the same text, naming the next line; only the lines this write sets
        for _line, body in owner_next_lines(wtext, ctx.roster()):
            scoped = ask_to_run(body, ctx.roster())
            why_ = _sc.pane_problem(body, "next line") or (_sc.command_problem(scoped, "next line", ctx.roster()) if scoped else "")      # a `! ` line is refused with no run cue needed
            if why_:
                add("next_windows", why_)
                break
    if nxt and runs("next"):
        stepped = False      # a line with a name stands above: a bare `- ` or numbered line under it is a sub-line of that step
        for line, name in next_openers(nxt):
            if name and not not_actor(name):
                stepped = True      # any `<name>:` opens a step: a session, the owner or an outside party (next_rules.unnamed, N1, is the rule on who may be named)
                continue
            if stepped and _BARE_RX.match(line):
                continue
            shown_line = line if len(line) <= 90 else line[:87] + "..."
            hint = line_hint(line)
            add("next_unnamed", f"next line {shown_line!r} does not say who takes it" + (f" ({hint})" if hint else "") + f": start every line with `<name>: ` where name is {H}, a session, the project's background agent or the outside party who takes the step "
                                f"(for example `{H}: run …`, `<session>: …` or `Kim: …`); a name in the line's body is not enough. Put file names, commands and code in backticks.")
            break
        defer_lines: set[str] = set()
        dtxt = nxt if defers_text is None else defers_text
        if named_open is not None and dtxt:
            bad = unwaited_deferrals(dtxt, m.get("after"), named_open, canon, gid)
            if bad:
                defer_lines = {ln for ln, _r in bad}
                ids = list(dict.fromkeys(r for _l, rs in bad for r in rs))
                dl = bad[0][0]
                shown_dl = dl if len(dl) <= 90 else dl[:87] + "..."
                many = len(ids) > 1
                quoted = ", ".join(f'"{r}"' for r in ids)
                it_ = "them" if many else "it"
                head = f"next line {shown_dl!r} defers on {', '.join(ids)} in words (once, after, when, until or before, or the instance's own defer_after_id phrases after the id), but {what} does not wait after {it_}, so nothing wakes its mover when {'they close' if many else 'it closes'}. "
                plain_ = f"If the item does not wait on {it_}, write the line without the deferring word ahead of the id (\"see {ids[0]}\"). Put file names, commands and code in backticks."
                if "decision" in [str(x).lower() for x in nds]:      # his call is what the item waits on: it never waits after another item
                    add("next_defers", head + f"{what} is on {H}'s call (needs decision), and an item on his call does not wait after another item (after=… with ask_by=… is not for it): write the line without the deferring word ahead of the id (\"see {ids[0]}\"), "
                                       f"or, when the other item carries the question, move the ask there. Put file names, commands and code in backticks.")
                else:
                    add("next_defers", head + f"Set the wait: after=[{quoted}] with ask_by=YYYY-MM-DD, the day it comes back to someone if {'they are' if many else 'it is'} still open "
                                       f"(the item then waits for it and its post-wake mover, post_wake_mover=<session> or else the mover, is told when the last one closes"
                                       + ("" if creating else f"; add supplies=<one line: what {'their' if many else 'its'} output gives this item> to say what it takes from {it_}") + "). "
                                       f"When it only needs a look on a day and not another item's close, until=YYYY-MM-DD makes the item wait until then (outside a hand-off the date parks the item, and the board lists it as waiting). " + plain_)
        if mod is not None and mod.state == _model.ALIVE:
            hits, broad = wait_lines(nxt)
            hits = [h for h in hits if h[0] not in defer_lines]      # a line the new guard refuses is not refused twice
            if hits:
                line, why = hits[0]
                shown_line = line if len(line) <= 90 else line[:87] + "..."
                add("next_wait", f"next line {shown_line!r} reads as a wait ({why}) on an alive item, and next is only the action someone takes now. Either set the wait itself "
                                 f"(hold=true with wake=YYYY-MM-DD and its reason: {_cfg.owner()}'s words, or for a window the work itself needs wait_basis=\"<what the window collects> ends <YYYY-MM-DD>\"; or after=[…], or wait_kind with its input; for an event the fleet reports (a release, a recycle, a sala op, a job) wait_kind=event with wait_event=<the event> and ask_by=YYYY-MM-DD) or write the action; what happened goes on the page. Put file names, commands and code in backticks.")
            else:
                flags = broad
    if not state_run or mod is None:
        return out, flags
    # ---- the state invariants
    sess = [x for x in nds if x.lower() not in _states._KINDS]
    kinds = [x.lower() for x in nds if x.lower() in _states._KINDS]
    project = clean(m.get("project"))
    movers = [x for x in sess if not ctx.background_of(x, project)]      # a background agent of the project is named into needs by the server itself: never a second mover
    if one_mover and (len(movers) > 1 or ("decision" in kinds and movers)):
        who = ", ".join(ctx.label(x) for x in movers)
        add("second_mover", f"needs names more than one mover ({'decision plus ' if 'decision' in kinds else ''}{who}): an item has one mover, and a second one in needs is a second mover. "
                            f"Keep needs to the one who moves it now and name who takes it after {H}'s answer or step in then=<session>.")
    if "decision" in kinds and held:
        add("decision_hold", f"needs holds decision together with a hold: an ask for later is a time wait whose post-wake mover is {H}. Release the hold (clear_hold=true) and keep the ask, "
                             f"or drop decision from needs and wait with hold=true, until=YYYY-MM-DD, post_wake_mover={H} and the wait's reason.")
    if mod.state == _model.ALIVE:
        clash = next((c for c in mod.conflicts if c.startswith("mover=")), "")
        if clash and mod.mover_explicit and not _model.is_owner(mod.mover) and _model.owner_state(m, mod.today):
            who_ = ctx.label(mod.mover)
            add("mover_state", f"{what} has {clash}. An item that is {H}'s makes him the mover: leave mover out, or set mover={H}, and name {who_} in then={who_} "
                               f"(his answer or Done hands the item to them). To give the item to {who_} now, take decision out of needs and name a session as mover instead.")
        gap = owner_mover_gap(m, mod)
        if gap:
            ask_form = "ask=\"Decide: … · Recommend: … · Stakes: … · By: …\""
            if creating:      # a create takes no state and no clear_mover: only his ask, or a session as mover
                fix = (f"Put it in his state: pass needs=[\"decision\"] with {ask_form}. "
                       f"Or give the item to a session: mover=<session> (or name it in needs) and write {H}'s part in a next line that starts `{H}:`.")
            else:
                fix = (f"Put it in his state: pass step=<one line, the single thing only he does>, or needs=[\"decision\"] with {ask_form}. "
                       f"Or give the item to a session: mover=<session> (clear_mover=true, when the session in needs or the project's builder should move it) and write {H}'s part in a next line that starts `{H}:`.")
            add("owner_mover", f"{what} would be left with {H} as its mover but nothing for him to do: {gap}, so his item page shows no Your step and no ask. " + fix)
        why = ctx.mover_problem(mod.mover, project)
        if why:
            who = f"its mover, {ctx.label(mod.mover)}, {why}" if mod.mover else "it names no mover (no session in needs, and no project builder or -main agent)"
            add("mover", f"{what} is alive and {who}. An alive item's mover is {H}, a live session or the project's "
                         f"background agent: set mover=<that name> (or name the session in needs), or, when nothing can move it now, put it in a wait.")
    elif mod.state == _model.WAITING and mod.wait is not None:
        w = mod.wait
        recycle = bool(m.get("recycle"))
        drop_hint = WAIT_DROP_HINT if clean(m.get("wait_kind")) else ""      # a wait the item stores can be dropped with clear_wait=true; one the fields only read as is changed by the state
        miss: list[str] = []
        if w.kind == "time":
            if not w.until and not recycle:
                miss.append("a time wait needs its wake: hold=true with wake=YYYY-MM-DD (a verifying state's end date is its wake)")
        elif w.kind == "anchor":
            if not (w.anchor or (anchored(item) if anchored else False)):
                miss.append("an anchor wait names its anchor: wait_anchor=<url>, or an anchor scoped to the item (anchors tool)")
            if not w.event:
                miss.append("and the event it expects: wait_event=<what you expect there>")
        elif w.kind == "item":
            if not w.after:
                miss.append("an item wait names the items it waits after: after=[\"board#N\"]")
        elif w.kind == "event":
            why_ = _ew.problem(w.event)
            if why_:
                miss.append(why_ + " (wait_event=<the event>)")
        else:
            if not w.event:
                miss.append(f"a relay wait names the party or event {H} relays: wait_event=<who or what>")
        if miss:
            add("wait_input", f"{what} waits on {_wait_text(w)} but its input is missing: " + " ".join(miss) + "." + drop_hint)
        why = ctx.mover_problem(w.mover, project)
        if why:
            who = f"its post-wake mover, {ctx.label(w.mover)}, {why}" if w.mover else "it names no post-wake mover (no session in needs, and no project builder or -main agent)"
            add("post_wake", f"{what}'s wait: {who}. Set post_wake_mover=<{H}, a live session or the project's background agent> "
                             f"(when it is unset, the first session in needs, else the project's builder or -main agent, takes it)." + drop_hint)
        on_until = until_wait or bool(_wt.stored_until(m))
        stated_time = clean(m.get("wait_kind")).lower() == "time" or hold_given
        wake = "" if on_until and not (stated_time and date_given) else clean(_wt.wake_value(m))      # a wait on a date alone carries its reason as a bare wake did: wait_reason (the self-wait gate). A time wait stated as one (wait_kind=time, or hold=true in this write) carries the basis or his words when this write gives its date, as a hold's wake does, written as wake or as until; a date the server chose (a kind with no date) or one stored earlier is not rejudged
        if w.kind == "time" and wake:
            quote = str(_wt.words_of(m).get("quote") or "")
            if not (w.basis or (quote and has_wait_words(quote))):
                add("snooze", f"{what} waits on a time (wake {wake}) with no reason: a time wait carries {H}'s words (his answer on the item, or said=[{{tag: Acked-by, quote, msg}}] with a quote that "
                              f"parks, waits, says until or names a date) or a real outside date (wait_basis=\"<what happens> YYYY-MM-DD\"). With neither, a park has no reason: when the work itself needs this window (a soak, "
                              "a log or data collection, a trial week, a timer you started), add wait_basis=\"<what the window collects> ends <YYYY-MM-DD>\" (a verifying item's wake takes it too, with no hold; a hold's wake does at any length); to only check back on work you keep moving, set no date: "
                              "a date with no hold is a wait until it (outside a hand-off) and the item reads as waiting (a front agent's own date on work another session moves is refused: that result lands through stackshot).")
        if w.kind in ("anchor", "item", "relay", "event"):
            end = clean(m.get("ask_by")) or (w.backstop if w.kind != "relay" else "") or (w.until if w.kind == "relay" else "")
            if not end:
                add("no_end", f"{what}'s wait on {_wait_text(w)} has no end: set ask_by=YYYY-MM-DD, the day it comes back to someone when nothing has arrived"
                              + (" (a backstop wake does the same)" if w.kind != "relay" else "") + "." + drop_hint)
    return out, flags


def refusal(problems: list[Problem]) -> str:
    """The ToolError text for a write's problems: one sentence each."""
    if len(problems) == 1:
        return "Refused: " + problems[0].text
    return f"Refused: {len(problems)} problems. " + " ".join(f"({i}) {p.text}" for i, p in enumerate(problems, 1))


# ---------------------------------------------------------------------------------------------------------------- the report on the items already there
@dataclass
class Report:
    """What the guards would refuse on the items in the store: per guard the ids; the closed items without an outcome; the next lines that carry broad wait words; and how many
    open items rest on a default (a mover or a post-wake mover the model filled in), which a write does not refuse."""
    open: int = 0
    closed: int = 0
    ids: dict[str, list[str]] = field(default_factory=dict)
    flagged: list[str] = field(default_factory=list)
    defaulted: dict[str, int] = field(default_factory=dict)
    examples: dict[str, str] = field(default_factory=dict)

    def count(self, key: str) -> int:
        return len(self.ids.get(key, ()))


def report(items: dict[str, dict[str, Any]], ctx: Ctx | None = None, *, anchors: dict[str, list[dict[str, Any]]] | None = None, one_mover: bool = True) -> Report:
    """Run every guard over every open item, as a create would (all fields), and list the closed items that lack an outcome. `items` is {gid: item}. Existing items are
    only read."""
    ctx = ctx or Ctx()
    rep = Report()
    scoped = _ascope.scoped_map(anchors if anchors is not None else _anc.load())      # the anchors that count for each item, from every project's page, read once
    def after_open(it: dict[str, Any]) -> list[str]:
        return [g for g in _wt.after_of(it.get("metadata") or {}) if (items.get(g) or {}).get("status") == "open"]
    for gid, it in sorted(items.items(), key=lambda t: (t[0][:1], int("".join(c for c in t[0] if c.isdigit()) or 0))):
        if it.get("status") == "completed":
            rep.closed += 1
            if not clean((it.get("metadata") or {}).get("outcome")):
                rep.ids.setdefault(CLOSED_NO_OUTCOME, []).append(gid)
            continue
        if it.get("status") != "open":
            continue
        rep.open += 1
        m = it.get("metadata") or {}
        anchored = (lambda _it, _g=gid: bool(scoped.get(_g)))
        try:
            probs, flags = check(it, ctx, touched=None, gid=gid, after_open=after_open, anchored=anchored, one_mover=one_mover)
            mod = _model.derive(it, ctx.now, after_open, anchored)
        except Exception:  # noqa: BLE001  — one unreadable item never stops the report
            continue
        for p in probs:
            rep.ids.setdefault(p.key, [])
            if gid not in rep.ids[p.key]:
                rep.ids[p.key].append(gid)
                rep.examples.setdefault(p.key, f"{gid}: {p.text}")
        if flags:
            rep.flagged.append(gid)
        if mod.state == _model.ALIVE and not mod.mover_explicit:
            rep.defaulted["mover"] = rep.defaulted.get("mover", 0) + 1
        if mod.state == _model.WAITING and mod.wait is not None and not mod.wait.mover_explicit:
            rep.defaulted["post_wake_mover"] = rep.defaulted.get("post_wake_mover", 0) + 1
    return rep


def owner_mover_rows(items: dict[str, dict[str, Any]], ctx: Ctx | None = None, *, anchors: dict[str, list[dict[str, Any]]] | None = None) -> list[dict[str, str]]:
    """The open items that already have the owner_mover mismatch (the owner is the mover but the item is in no state of his): per item its id, subject, mover, state and creator
    (metadata.owner as the session is named now: `ctx.label`), plus what is missing. The dry run of the guard, read only: tools/model_guard_report.py --owner-mover."""
    ctx = ctx or Ctx()
    scoped = _ascope.scoped_map(anchors if anchors is not None else _anc.load())      # the anchors that count for each item, from every project's page, read once
    after_open = lambda it: [g for g in _wt.after_of(it.get("metadata") or {}) if (items.get(g) or {}).get("status") == "open"]
    rows: list[dict[str, str]] = []
    for gid, it in sorted(items.items(), key=lambda t: (t[0][:1], int("".join(c for c in t[0] if c.isdigit()) or 0))):
        if it.get("status") != "open":
            continue
        m = it.get("metadata") or {}
        anchored = (lambda _it, _g=gid: bool(scoped.get(_g)))
        try:
            mod = _model.derive(it, ctx.now, after_open, anchored)
            gap = owner_mover_gap(m, mod)
        except Exception:  # noqa: BLE001  — one unreadable item never stops the dry run
            continue
        if gap:
            owner = clean(m.get("owner"))
            rows.append({"id": gid, "subject": clean(it.get("subject")), "mover": mod.mover, "state": mod.today + (" (derived)" if mod.today_derived else ""),
                         "creator": ctx.label(owner) if owner else "none", "gap": gap})
    return rows


def brief_line(rep: Report) -> str:
    """One short line for the brief: `model guards would refuse on existing items: mover 3 · wait input 12 · …` ("" when nothing would be refused)."""
    parts = [f"{LABELS[k]} {rep.count(k)}" for k in GUARDS if rep.count(k)]
    if rep.count(CLOSED_NO_OUTCOME):
        parts.append(f"closed without an outcome {rep.count(CLOSED_NO_OUTCOME)}")
    return ("model guards would refuse on existing items: " + " · ".join(parts)) if parts else ""


def full_text(rep: Report, shown: Callable[[str], str] = str, with_examples: bool = True) -> str:
    """The whole report for the audit: the counts and the ids per guard, an example refusal each, what is flagged and what rests on a default."""
    lines = [f"model guards on {rep.open} open and {rep.closed} closed items (read only; nothing was refused or changed)"]
    for k in (*GUARDS, CLOSED_NO_OUTCOME):
        ids = rep.ids.get(k, [])
        label = LABELS.get(k, "closed without an outcome")
        lines.append(f"{label}: {len(ids)}" + (": " + ", ".join(shown(g) for g in ids) if ids else ""))
        if with_examples and ids and k in rep.examples:
            lines.append("  e.g. " + rep.examples[k][:300])
    lines.append(f"flagged for broad wait words in next (when, once, after, until; accepted, not refused): {len(rep.flagged)}" + (": " + ", ".join(shown(g) for g in rep.flagged) if rep.flagged else ""))
    lines.append("resting on a default (the model filled it in; a write does not refuse it): " + (", ".join(f"{k} {v}" for k, v in sorted(rep.defaulted.items())) or "none"))
    return "\n".join(lines)
