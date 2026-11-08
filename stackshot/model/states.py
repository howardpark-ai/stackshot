"""states.py — an open item's stored `state` (metadata.state), what each state must carry, and the state derived for an item that has none.

An open item now stores alive or waiting directly (the item model, model.py), and no call sets or clears a state word any more: the inputs state, clear_state, party, chase, end and proof of update are
retired (retired_inputs.py, which refuses a call that passes one). This module stays as the reader of what older items still store: a stored state word and the fields a state carried, validated, derived and worded
as before. The only writers left are update(step=...) (stores your-step) and update(supplies=...) (stores blocked); a write that leaves an item unable to stand in its stored state drops the word (server._state_apply).

The seven words, as an older item stored them:

  doing      next; needs names an agent session. It carries no expected time: an agent's own work shows how long it has run, and a wait on a date is a park (parked)
  your-call  needs holds decision, and an ask line
  your-step  step: one line (a summary; what the owner runs is in the lines of next that start with his name, step_commands.py), of the single thing only the owner does
  outside    needs holds external, party (who, free text) and chase (YYYY-MM-DD, the day to chase)
  blocked    after names an item, and supplies: one line, what that item's output gives this one
  parked     on hold with a wake date (a wake alone is a reminder, never a park), and either the owner's recorded words for it (cap_ok) or a wait_basis
  verifying  proof (one line: what proves it works) and end (YYYY-MM-DD, today to 30 days out, when the checking ends); needs names an agent session.
             The end date stands as the item's wait, like a wake (waiting.py reads it): no separate wake, no idle nudge before it

A closed item keeps status completed and its outcome and has no state: a close drops the state and its carry fields. The carry fields the
states add are step, party, chase, supplies, proof and end (expected_by and expected_reason, which a doing item once carried, stay in CARRY_FIELDS only so that a write drops a stored one); the others (next, ask, after, wake, cap_ok, wait_basis, needs) are
fields the item already had. Pure functions of an item and a date: no server import, so the server and the renderer
share one copy."""
from __future__ import annotations

import datetime as dt
import re
import time
from typing import Any, Callable

from stackshot.core import config as _cfg
from stackshot.model import step_commands as _sc
from stackshot.waits import waiting as _wt

STATES = ("doing", "your-call", "your-step", "outside", "blocked", "parked", "verifying")
CARRY = {"doing": (), "your-call": (), "your-step": ("step",), "outside": ("party", "chase"),
         "blocked": ("supplies",), "parked": (), "verifying": ("proof", "end")}
CARRY_FIELDS = ("expected_by", "expected_reason", "step", "party", "chase", "supplies", "proof", "end")      # the fields states add to metadata; a state change drops the ones its state does not own (expected_by and expected_reason: no state owns them now, so a write that touches the state drops a stored one)
RETIRED_FIELDS = ("expected_by", "expected_reason")      # a doing item no longer carries an expected time: a write that passes one is accepted, nothing is stored, and the reply says so
RETIRED_INPUT_FIELDS = ("party", "chase", "end", "proof")      # the fields of inputs no call passes any more (retired_inputs.py): an item an older write left one on keeps it, and the readers still take it (model.derive, watchers, the item page); no write drops one
DATE_FIELDS = ("chase", "end")
DAY_S = 86400.0
VERIFYING_MAX_DAYS = 30
AGENT_STATES = ("doing", "blocked", "verifying")      # the states whose move is an agent's
REPARK_MAX = 3                                                   # the third re-park in a row, with nothing else changed, goes to the owner instead
CLOSE_EXTRA = ("next_stale", "repark", "draft", "step_proof")   # bookkeeping of the state checks, the draft (draft.py) and the steps' proofs (step_proof.py), that go with a close
LINE_MAX = 300
STEP_MAX, STEP_LINES, STEP_LINE_MAX = 3000, 20, 500      # a step that is a numbered list or holds a fenced block: this many characters in all, lines in all, characters on a line outside a fenced block
STANDS_ON = {"doing": ("needs", "next"), "your-call": ("needs", "ask"), "your-step": (), "outside": ("needs",),
             "blocked": ("after",), "parked": ("wake", "hold", "wait_basis"), "verifying": ("needs",)}    # the fields a stored state stands on besides its own carry fields: a write that touches none of them cannot unseat it
LEGACY_STATES = {"queued": "doing"}        # a stored state no longer written: it loads as the state shown (a builder starts every item handed to it, so there is no waiting-in-line state any more)
DROP_ON_CLOSE = ("state", *CARRY_FIELDS)
_KINDS = ("decision", "external")
_DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def clean(v: Any) -> str:
    """A carry field's text on one line, its whitespace collapsed."""
    return " ".join(str(v or "").split())


def step_text(v: Any) -> str:
    """The step as it is stored. A step with a numbered line (`1.`, `2)` at the start of a line) or a fenced block keeps its lines (blank lines outside a fenced block dropped, the spaces inside a
    line collapsed, a fenced block's text left as written); any other step is one line, its whitespace collapsed, as ever."""
    t = str(v or "").replace("\r\n", "\n").replace("\r", "\n")
    if not _sc.structured(t):
        return clean(t)
    out: list[str] = []
    fence = ""
    for ln in t.split("\n"):
        s = ln.rstrip()
        if fence:
            out.append(s)
            if s.strip() and set(s.strip()) == {fence[0]} and len(s.strip()) >= len(fence):
                fence = ""
        elif _sc.FENCE_RX.match(s):
            fence = _sc.FENCE_RX.match(s).group(1)
            out.append(s)
        elif s.strip():
            lead = s[:len(s) - len(s.lstrip())]
            out.append(lead + " ".join(s.split()))
    return "\n".join(out).strip("\n")


def step_problem(v: Any) -> str:
    """Why this step text (as step_text stores it) is too long ("" = fine): a one-line step is at most LINE_MAX characters; a numbered or fenced one at most STEP_MAX in all, STEP_LINES lines, and
    STEP_LINE_MAX on a line outside a fenced block."""
    t = step_text(v)
    if not _sc.structured(t):
        return f"step at most {LINE_MAX} characters on one line ({len(t)} now); it is a summary, and what the owner runs goes in lines of next that start with his name" if len(t) > LINE_MAX else ""
    if len(t) > STEP_MAX:
        return f"step at most {STEP_MAX} characters ({len(t)} now)"
    if len(t.split("\n")) > STEP_LINES:
        return f"step at most {STEP_LINES} lines ({len(t.split(chr(10)))} now)"
    fence = ""
    for ln in t.split("\n"):
        if fence:
            if ln.strip() and set(ln.strip()) == {fence[0]} and len(ln.strip()) >= len(fence):
                fence = ""
        elif _sc.FENCE_RX.match(ln):
            fence = _sc.FENCE_RX.match(ln).group(1)
        elif len(ln) > STEP_LINE_MAX:
            return f"step at most {STEP_LINE_MAX} characters on a line outside a fenced block (a line of {len(ln)}; put a long command in a ``` block)"
    return ""


def carry_text(field: str, v: Any) -> str:
    """A carry field's text as it is stored: the step keeps its numbered lines (step_text), every other field is one line."""
    if field == "step":
        return step_text(v)
    return clean(v)


def sessions_of(m: dict[str, Any]) -> list[str]:
    """The agent sessions in needs (whatever is not a kind); the first one is the builder."""
    return [x for x in _wt.needs_of(m) if x.lower() not in _KINDS]


def kinds_of(m: dict[str, Any]) -> list[str]:
    return [x.lower() for x in _wt.needs_of(m) if x.lower() in _KINDS]


def stored(item: dict[str, Any]) -> str:
    """The state stored on an open item, "" when it has none (or a value that is not a state)."""
    if item.get("status") == "completed":
        return ""
    v = (item.get("metadata") or {}).get("state")
    v = LEGACY_STATES.get(v, v) if isinstance(v, str) else v
    return v if isinstance(v, str) and v in STATES else ""


def _wake_with_words(m: dict[str, Any]) -> bool:
    return bool(m.get("wake")) and _wt.cap_words(m, "wake")


def derive(item: dict[str, Any], after_open: Callable[[dict[str, Any]], Any] | None = None) -> str:
    """The state of an open item that has none stored, from its fields; "" for a closed item. In this order:
      needs holds decision                      → your-call
      needs holds external                      → outside
      on hold with a wake and the owner's words
        (cap_ok) or a wait_basis for it         → parked
      on hold otherwise (no after link)         → parked too: a hold is a park; the carry fields it lacks show in the migration's dry run
      after names an item that is still open    → blocked   (after_open(item) → the open ones; without it, any after link counts)
      otherwise                                 → doing
    `item` is an item dict (status, metadata)."""
    if item.get("status") == "completed":
        return ""
    m = item.get("metadata") or {}
    kinds = kinds_of(m)
    if "decision" in kinds:
        return "your-call"
    if "external" in kinds:
        return "outside"
    held = _wt.is_held(item)
    if held and _wake_with_words(m):
        return "parked"
    ao = _wt.after_of(m)
    if ao and (after_open(item) if after_open else True):
        return "blocked"
    if held:
        return "parked"
    return "doing"


def of(item: dict[str, Any], after_open: Callable[[dict[str, Any]], Any] | None = None) -> tuple[str, bool]:
    """(state, derived?) of an item: the stored state, else the derived one. ("", False) for a closed item."""
    if item.get("status") == "completed":
        return "", False
    s = stored(item)
    return (s, False) if s else (derive(item, after_open), True)


def words(item: dict[str, Any], after_open: Callable[[dict[str, Any]], Any] | None = None) -> str:
    """"state: doing" for an item that STORES a state; "" for a closed item and for one that stores none (the word it reads as is not shown: the model line says alive or waiting, and who moves it)."""
    s, d = of(item, after_open)
    return f"state: {s}" if s and not d else ""


def carry_of(item: dict[str, Any]) -> dict[str, str]:
    """The carry fields a stored state holds, {field: text}."""
    m = item.get("metadata") or {}
    return {k: carry_text(k, m[k]) for k in CARRY.get(stored(item), ()) if carry_text(k, m.get(k))}


def _date_problem(field: str, v: str, today: dt.date, check: bool) -> str:
    """Why `v` cannot be the date in `field` ("" = fine). A date is a real YYYY-MM-DD; when it is being set (check) also today or later ."""
    if not _DATE_RX.match(v):
        return f"{field}=YYYY-MM-DD (a real date; got {v!r})"
    try:
        d = dt.date.fromisoformat(v)
    except ValueError:
        return f"{field}=YYYY-MM-DD (a real calendar date; got {v!r})"
    if check and d < today:
        return f"{field}=YYYY-MM-DD (today or later; {v} is past)"
    if check and field == "end" and d > today + dt.timedelta(days=VERIFYING_MAX_DAYS):
        return f"end=YYYY-MM-DD ({today.isoformat()} to {(today + dt.timedelta(days=VERIFYING_MAX_DAYS)).isoformat()}: at most {VERIFYING_MAX_DAYS} days from today; {v} is further out)"
    return ""


def problems(meta: dict[str, Any], state: str, today: dt.date, *, check_dates: bool = True) -> list[str]:
    """What the item (its metadata, as it would be stored) still lacks for `state`: one phrase per missing or wrong thing, each naming the field to add
    ([] = it carries all it must). check_dates: judge the dates against today (a new date being set); False reads only that they are real dates (a write
    that leaves the date alone, which has since lapsed, is not refused for it). A doing item lacks only a next and an agent session: it carries no time."""
    out: list[str] = []
    sess, kinds = sessions_of(meta), kinds_of(meta)

    def need_agent(why: str) -> None:
        if not sess:
            out.append(f"needs naming an agent session (needs=[\"<session>\"]); {why}")

    def text(field: str, what: str) -> None:
        v = carry_text(field, meta.get(field))
        if not v:
            out.append(f"{field}=<{what}>")
        elif field == "step":
            if step_problem(v):
                out.append(step_problem(v))
        elif len(v) > LINE_MAX:
            out.append(f"{field} at most {LINE_MAX} characters on one line ({len(v)} now)")

    def date(field: str) -> None:
        v = clean(meta.get(field))
        if not v:
            span = {"end": VERIFYING_MAX_DAYS}.get(field)
            out.append(f"{field}=YYYY-MM-DD" + (f" (today to {(today + dt.timedelta(days=span)).isoformat()}, at most {span} days from today)" if span else ""))
            return
        p = _date_problem(field, v, today, check_dates)
        if p:
            out.append(p)

    if state == "doing":
        need_agent("doing is a session at work")
        if not clean(meta.get("next")):
            out.append("next=<the next concrete action>")
    elif state == "your-call":
        if "decision" not in kinds:
            out.append("needs including \"decision\"")
        if not clean(meta.get("ask")):
            out.append("ask=<the ask line>")
    elif state == "your-step":
        text("step", "one line, no command, of the single thing only the owner does; what he runs goes in lines of next that start with his name")
    elif state == "outside":
        if "external" not in kinds:
            out.append("needs including \"external\"")
        text("party", "who is waited on")
        date("chase")
    elif state == "blocked":
        if not _wt.after_of(meta):
            out.append("after=[\"board#N\"] (the item it waits on)")
        text("supplies", "one line: what that item's output gives this one")
    elif state == "parked":
        if not meta.get("wake"):
            out.append("wake=YYYY-MM-DD")
        if not _wt.is_held({"status": "open", "metadata": meta}):
            out.append("hold=true (a wake alone is a reminder, never a park)")
        if not (meta.get("wake") and _wt.cap_words(meta, "wake")):
            out.append("the owner's words for the wake (said=[...], which records cap_ok) or wait_basis=\"<what happens> YYYY-MM-DD\"")
    elif state == "verifying":
        need_agent("verifying is a session checking its work")
        text("proof", "one line: what proves it works")
        date("end")
    return out


# ---------------------------------------------------------------- the state checks: pure helpers
_MARK_RX = re.compile(r"^\s*(?:[-*+•]|\d+[.)])?\s*")
# A who-takes-it opener of the owner's step is config.owner_opener_rx(): `<owner>:`, `<alias>:`, `you:`, `<owner> to …`; never `the owner's`, `ACME-1` or "the owner approved …" (the names are [instance] owner and owner_aliases)


def next_names_owner(next_text: Any, owner: str = "") -> str:
    """Whose step the first line of `next` is when it is the owner's: the owner's name ([instance] owner) when it opens with `<owner>:`, an alias (`AE:`), `you:` or "<owner> to …" / "<alias> to …",
    `owner` (when given and not the default "the owner") when it opens with that, "" when it opens with anyone else or is empty. A list marker before the name is skipped."""
    for raw in str(next_text or "").splitlines():
        ln = _MARK_RX.sub("", raw)
        if not ln.strip():
            continue
        if _cfg.owner_opener_rx().match(ln):
            return owner if owner and owner != "the owner" else _cfg.owner()
        if owner and owner != "the owner" and re.match(rf"{re.escape(owner)}(?:\s*:|\s+to\b)", ln, re.I):
            return owner
        return ""
    return ""


_MONTHS = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}
_ISO_DATE_RX = re.compile(r"(?<![\d-])(\d{4})-(\d{2})-(\d{2})(?![\d-])")
_MD_RX = re.compile(r"\b((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\.?,?\s+)?(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+"
                    r"(\d{1,2})(st|nd|rd|th)?\b(?:,?\s+(20\d{2})\b)?")
_URL_RX = re.compile(r"\]\([^)\s]*\)|https?://\S+")
_PATH_RX = re.compile(r"\S*/\S*|\S+\.(?:md|py|json|toml|txt|sh|ya?ml|html?|js|ts|log|csv|lock)\b")      # a path or a file name: its date-like parts are not dates
_BARE_OK_RX = re.compile(r"\s*(?:$|[,.;:)\]]|[-\u2013\u2014]|(?:at|by|before|until|and|or|to|through)\b|\d{1,2}:\d{2})", re.M)      # what may follow a day with no ordinal, weekday or year: "May 5 items" is a count
YEARLESS_ROLL_DAYS = 90         # a yearless date more than this many days past is read as next year's


def named_dates(text: Any, today: dt.date) -> list[tuple[str, dt.date]]:
    """The dates a next names, [(as written, the date)], in the order they appear: YYYY-MM-DD, and "Mar 26th" / "March 26" / "Thu Mar 26th" (a capitalised month name
    and a day). A day with no ordinal, weekday or year must end the phrase or be followed by a punctuation mark, a time or a word like at/by/until ("May 5 items" and "Mar 12 tests"
    are counts). A date written without a year is taken in this year, or in the next when this year's would be more than YEARLESS_ROLL_DAYS (90) past. A link's URL, a path
    and a file name are cut out first. Not real calendar dates are skipped."""
    t = _PATH_RX.sub(" ", _URL_RX.sub(" ", str(text or "")))
    out: list[tuple[int, str, dt.date]] = []
    for m in _ISO_DATE_RX.finditer(t):
        try:
            out.append((m.start(), m.group(0), dt.date(int(m[1]), int(m[2]), int(m[3]))))
        except ValueError:
            continue
    for m in _MD_RX.finditer(t):
        if not (m[1] or m[4] or m[5]) and not _BARE_OK_RX.match(t[m.end():]):
            continue
        mon, day = _MONTHS[m[2][:3]], int(m[3])
        try:
            d = dt.date(int(m[5]), mon, day) if m[5] else dt.date(today.year, mon, day)
            if not m[5] and (today - d).days > YEARLESS_ROLL_DAYS:
                d = dt.date(today.year + 1, mon, day)
        except ValueError:
            continue
        out.append((m.start(), m.group(0), d))
    return [(w, d) for _, w, d in sorted(out)]


def passed_dates(text: Any, today: dt.date) -> list[tuple[str, dt.date]]:
    """The dates a next names that have passed (before today), as named_dates gives them."""
    return [(w, d) for w, d in named_dates(text, today) if d < today]
