"""watchers.py — the waits' watchers of the item model (the design: docs/design, section 4 and the pause line of section 5).

A waiting item names what it waits on (model.py: wait_kind time | item | anchor | relay | event), and this module says when that wait is over and what the item turns into. The pure
half lives here: the readings (which items the watchers own, which are due, on what cause), the text of each arrival, the relay's fixed ask and its options, the chases, the
reading of the owner's answer to those asks, the date he gives. The server (server.py, the `_watch_*` functions) reads and writes the items, sends the messages and calls these.

  The watchers act ONLY on an item with a stored wait_kind. Every other item keeps today's wake pass and `after` release
  until the step 4 migration, so no item is moved by two mechanisms (`watches` is the gate those read). That pass reads an ask_by only beside a relay or event kind, so a waiting item whose one date is an
  ask_by with no wait_kind is woken by nothing (`nothing_wakes`): the audit reports it (wait_end.py) and the brief lists it.

  time    the wake passes → alive, the post-wake mover
  item    the last `after` item closes → alive, the post-wake mover; the backstop (ask_by, else the wake) passes first → alive, the post-wake mover, with the note that the item
          it waited on is still open
  anchor  the anchor module delivers a notice for the anchor → alive, the post-wake mover, the notice's gist on the item (the mover judges a false hit); the backstop passes
          first → alive, the post-wake mover, "the anchor stayed silent"
  event   the server is told of the fleet event the wait names (event_waits.py: a PR merged or released, a recycle, a fleet op's result, a job's run) → alive, the post-wake mover, with what
          happened; the backstop passes first → alive, the post-wake mover, "the event did not come". The stall pass does not run for it (a waiting item has no mover to nag)
  relay   the ask-by day comes → alive with the owner as mover, a ready question: Q_RELAY, with what is waited for after it on its own, and three choices: it happened / wait 1 more week / stop waiting (any other wait is a note in the box)
  list    several waits of any of the kinds above at once (waits/wait_list.py): each line is marked when it arrives, and the item comes back when every line has (`all`) or the first has (`any`) → alive,
          the post-wake mover, with what arrived and what did not; the backstop day passing first → the same (an open relay line then asks the owner, as a relay's ask-by day does). No chases on a list

  Chases (a relay or anchor wait): a follow-up an older item logged is only read (no call logs one now). With two on the item, the wait's next end (the ask-by day or the
  backstop) brings the item to the owner as the "stop waiting?" question (Q_DROP, the same three choices) instead of the usual arrival. Reading taken: "after two chases with no reply"
  is judged when the wait comes due, since only then has the last chase had its time to be answered.

[model] pause = true holds every transition here (and the wake pass beside them); when it turns false the due ones fire in one pass, one message per recipient."""
from __future__ import annotations

import datetime as dt
import re
import time
from typing import Any, Callable

from stackshot.core import config as _cfg
from stackshot.core import datewords as _datewords
from stackshot.core import runner_files as _files
from stackshot.model import ask_leaves as _ask_leaves
from stackshot.model import bullet_text as _bt
from stackshot.model import owner_steps as _owner_steps
from stackshot.waits import event_waits as _ew
from stackshot.model import model as _model
from stackshot.model import step_proof as _sp
from stackshot.model import steps as _steps
from stackshot.waits import wait_list as _wl
from stackshot.waits import waiting as _wt

CHASE_KINDS = ("relay", "anchor")          # the waits a chase goes with
CHASES_MAX = 2                             # this many chases, no arrival: the next end of the wait asks the owner whether to stop waiting
DROP_ON_CLOSE = ("chases", "woke", "watch")
ARRIVED = "It happened: continue the work"      # the three buttons of every question a due wait asks: a label says what a pick does without the question beside it (and stays within render.OPTION_LABEL_MAX)
WEEK = "Wait 1 more week: next check in a week"      # the new end date is a week from the day he picks it
DROP = "Stop waiting: close the item"
WEEK_DAYS = 7
_ASK_HEAD = "Decide: "
_OPT_MARK = " · Options: "
CHOICES = (ARRIVED, WEEK, DROP)
TAIL = " / ".join(CHOICES)      # the options part of every question, in the order of the buttons; any other wait is a note in the box, which the post-wake mover reads
# The question is a whole short sentence that holds none of the item's text; what is waited for follows it on its own (EVENT_LEAD), whatever shape that text has. Stored in English (a session reads
# it, and a button's label is the identity of a pick); a page draws it from the string table (web/wait_words.py, through read_question and option_kind).
Q_RELAY = "Has what this item is waiting for happened?"
Q_DROP = "No news after {n} follow-ups. Stop waiting?"
EVENT_LEAD = " Waiting for: "
EVENT_CLIP = 200                           # the longest event text a question carries (cut at a word, never inside a link)
# what each button does, one line each (within render.OPTION_LINE_MAX); the stored options need one, a page draws the label alone, which says it (wait_words.line)
LINE_ARRIVED = "The wait is over: the item goes to the session that takes it next."
LINE_WEEK = "The item keeps waiting and this question comes back in a week."
LINE_DROP = "It is no longer wanted: the item closes as not planned."


# ---------------------------------------------------------------------------------------------------------------- the switches
_HOLD: dict[str, Any] = {"until": 0.0, "by": "", "since": 0.0}      # the migration's own pause: held in the server process (and written to the hold file for a runner in another process), never in the config file, and it lapses by itself
HOLD_CEILING_S = 3600.0        # the most one pass may hold the board, from its `begin`, however often it renews: a pass that runs past this lapses


def hold(by: str, seconds: float, now: float | None = None, begin: bool = False) -> None:
    """The migration pass holds the board-wide pause for `seconds` more (each batch of the pass renews it, so a pass that dies lets the board go on after a few minutes, never for good, and never
    past HOLD_CEILING_S after its `begin`, whatever renews it). `begin` starts the pass and its ceiling; a renewal keeps the ceiling it began with. A restart of the server drops it. It stands
    beside `[model] pause`: the config switch is the operator's, this one is the pass's, and lifting this never lifts that. The hold is also written to the hold file (core/runner_files.py: its holder's pid, `by`,
    `since` and `until`), so a runner in another process keeps its board ticks off too; that file lapses by itself as the hold does (its holder's pid gone, `until` passed, or `since` more than HOLD_CEILING_S ago)."""
    t = time.time() if now is None else now
    if begin or not _HOLD["since"]:
        _HOLD["since"] = t
    _HOLD["until"] = min(t + float(seconds), float(_HOLD["since"]) + HOLD_CEILING_S)
    _HOLD["by"] = str(by or "migration")
    _files.hold_write(_HOLD["by"], float(_HOLD["since"]), float(_HOLD["until"]))


def release() -> None:
    _HOLD["until"], _HOLD["by"], _HOLD["since"] = 0.0, "", 0.0
    _files.hold_clear()


def _file_hold(now: float | None) -> dict[str, Any] | None:
    """The hold another process keeps in the hold file while it is up; None for none, a stale one, or this process's own (that one is in `_HOLD`). One stat when there is no file."""
    return _files.hold_read(now, HOLD_CEILING_S)


def holding(now: float | None = None) -> bool:
    """Is the migration's hold up: the pass is running in this process, or (by its hold file) in another?"""
    t = time.time() if now is None else now
    return t < float(_HOLD["until"]) or _file_hold(t) is not None


def holder() -> str:
    """Who began the pass that holds the board now ("" when none holds it): the only caller whose apply or end the route takes."""
    if time.time() < float(_HOLD["until"]):
        return str(_HOLD["by"])
    fh = _file_hold(None)
    return str(fh["by"]) if fh else ""


def paused() -> bool:
    """[model] pause (default false): the board-wide pause switch, or the migration pass's hold. While true no wait ends, no wake fires (the wake pass reads it too) and no hand-off clock runs; the due ones fire when it turns false."""
    return bool(_cfg.get("model", "pause", default=False)) or holding()


def stored_kind(meta: dict[str, Any]) -> str:
    """The wait_kind an item stores ("" when none or not one of the six); an item that stores an `until` and no kind waits on the date alone, so it reads "time". A stored `list` is a kind
    only while the list holds (waits/wait_list.py): one that does not is ignored, as the model ignores it, and the item reads as it would without it."""
    k = _model.clean((meta or {}).get("wait_kind")).lower()
    if k == _wl.LIST and not _wl.valid(meta or {}):
        k = ""
    if k in _model.WAIT_KINDS:
        return k
    return "time" if _wt.stored_until(meta or {}) else ""


def time_epoch(meta: dict[str, Any]) -> float | None:
    """When a time wait ends: its `until`, else its wake, else (a verifying item) its end date, the end of that day."""
    su = _wt.stored_until(meta)
    ep = day_epoch(su) if su else day_epoch(meta.get("wake"))
    if ep is None and not su and meta.get("state") == "verifying" and meta.get("end"):
        ep = _wt.due_epoch(meta.get("end"))
    return ep


def can_end(meta: dict[str, Any]) -> bool:
    """Can some watcher end this stored wait: a time wait needs a wake (or a verifying end date), a relay its ask-by day, an item wait its `after` or a backstop date, an anchor wait the
    anchor it watches, an event wait its event phrase and a backstop date. A wait no watcher can end stays with today's mechanisms."""
    k = stored_kind(meta)
    if k == "time":
        return time_epoch(meta) is not None
    if k == "relay":
        return day_epoch(relay_day(meta)) is not None
    if k == "item":
        return bool(_wt.after_of(meta)) or backstop_epoch(meta) is not None
    if k == "anchor":
        return bool(_model.clean(meta.get("wait_anchor")))
    if k == "event":
        return not _ew.problem(meta.get("wait_event")) and backstop_epoch(meta) is not None      # an event that may never come needs a day it comes back anyway; without one the nag keeps the item
    if k == _wl.LIST:
        return True                                  # the backstop day is required of a list, so the list always has an end
    return False


def watches(item: dict[str, Any]) -> bool:
    """Does this module own the item's wait: the item is open, it stores a wait_kind and a watcher can end that wait. The wake pass and the `after` release
    skip such an item; one whose wait no watcher can end (a time wait with no date, an anchor wait with no anchor) keeps today's mechanisms."""
    return item.get("status") == "open" and can_end(item.get("metadata") or {})


# ---------------------------------------------------------------------------------------------------------------- when a wait is over
BACKOFF = 600.0        # an item whose turn failed is left alone this long (metadata.watch.failed_at)


def failed_at(meta: dict[str, Any]) -> float:
    """When the item's last turn failed (epoch seconds), 0.0 for none. A torn note (no number, a bool, a negative, a non-finite or a moment no date can show: the bound an arrival time has) is no failure: the
    back-off moments that read it (`next_moment`, the wake pass) draw dates from it, and one bad value must not stop them for every other item."""
    w = (meta or {}).get("watch")
    try:
        v = w.get("failed_at") if isinstance(w, dict) else None
        at = 0.0 if v is None or isinstance(v, bool) else float(v)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return at if 0 < at <= _wl.ARRIVED_AT_MAX else 0.0      # (nan, inf and -inf fail the comparison)


def day_epoch(value: Any) -> float | None:
    """A stored date (YYYY-MM-DD, or with THH:MM) as the moment it falls due: the start of that day in the instance timezone, so the ask-by day brings the question on that day."""
    return _wt.wake_epoch(value)


def relay_day(meta: dict[str, Any]) -> Any:
    """The day a relay wait turns into a question: its `until`, else its ask_by (as stored)."""
    return _wt.stored_until(meta) or meta.get("ask_by")


def backstop_epoch(meta: dict[str, Any]) -> float | None:
    """The date an item, anchor or event wait comes back anyway: its `until`, else the earlier of its ask_by and its wake, None when it has none."""
    su = _wt.stored_until(meta)
    if su:
        return day_epoch(su)
    eps = [e for e in (day_epoch(meta.get("ask_by")), day_epoch(meta.get("wake"))) if e is not None]
    return min(eps) if eps else None


def dead_ask_by(meta: dict[str, Any], now: float) -> bool:
    """Is the item's ask_by a day that has passed and that nothing acts on: it stores no wait_kind and no until, so no watcher and no wake pass reads it. A write that gives the item a wait drops
    it: kept, it would stand as that wait's date and end the wait as it is stored."""
    ep = day_epoch((meta or {}).get("ask_by"))
    return ep is not None and ep <= now and not stored_kind(meta)


def nothing_wakes(meta: dict[str, Any], open_after: bool, scoped_anchor: Callable[[], Any], old_off: bool = False) -> bool:
    """Is a waiting item (the caller has read it so) one that nothing will wake? No watcher can end its wait (can_end) and the old wake pass has no date for it (waiting.wake_value: its until, else its wake, else the
    ask_by of a stored relay or event kind), and nothing else ends it either: an open `after` (`open_after`: that close releases it), a pane recycle, a done check, an open step the proof pass ticks, or, for a held
    item, an anchor scoped to it (`scoped_anchor`: its notice releases the hold). `old_off`: the old wake pass and its `after` release stand down for every item no watcher watches (item_read._old_wait_off), so
    neither its date nor its `after` counts."""
    m = meta or {}
    if can_end(m) or m.get("recycle") or _model.clean(m.get("check")):
        return False
    if not old_off and (open_after or day_epoch(_wt.wake_value(m)) is not None):
        return False
    proofs = m.get("step_proof") if isinstance(m.get("step_proof"), dict) else {}
    if any(s["status"] == _steps.OPEN and _sp.has_proof(s["text"], proofs, _steps.key) for s in _steps.view(m)):
        return False
    return not (m.get("hold") and scoped_anchor())


def next_moment(meta: dict[str, Any]) -> float | None:
    """The moment the scheduler next has to look at this wait (a wake, a relay's ask-by, a backstop), None for none: the runner sleeps until the earliest. An item whose last turn failed
    is looked at again BACKOFF after the failure, not at once."""
    k = stored_kind(meta)
    ep = time_epoch(meta) if k == "time" else day_epoch(relay_day(meta)) if k == "relay" else backstop_epoch(meta) if k in ("item", "anchor", "event") else _wl.next_moment(meta) if k == _wl.LIST else None
    fa = failed_at(meta)
    if ep is not None and fa and ep <= fa + BACKOFF:
        ep = fa + BACKOFF
    return ep


def due(item: dict[str, Any], now: float, after_open: list[str] | None = None) -> str:
    """Why this item's wait is over by the clock, "" when it is not: time (the wake passed), item (every `after` item is closed: the catch-up of the close event), backstop (an
    item or anchor wait ran out its date), relay (the ask-by day came). An anchor's arrival is an event (the anchor module), not a date, so it is not here. An item whose last turn failed
    is not due for BACKOFF seconds. `after_open` = the `after` items still open (the server reads them)."""
    meta = item.get("metadata") or {}
    k = stored_kind(meta)
    fa = failed_at(meta)
    if fa and now < fa + BACKOFF:
        return ""
    if k == "time":
        ep = time_epoch(meta)
        return "time" if ep is not None and ep <= now else ""
    if k == "relay":
        ep = day_epoch(relay_day(meta))
        return "relay" if ep is not None and ep <= now else ""
    if k == _wl.LIST:                      # the group is over by what has arrived (the cause is the kind of the line that completed it), or the backstop day has come first
        if _wl.done(meta):
            return _wl.completing_kind(meta)
        ep = backstop_epoch(meta)
        return "backstop" if ep is not None and ep <= now else ""
    if k == "item":
        if _wt.after_of(meta) and not (after_open or []):
            return "item"
    if k in ("item", "anchor", "event"):
        ep = backstop_epoch(meta)
        if ep is not None and ep <= now:
            return "backstop"
    return ""


def chases_of(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """The chases logged on the item, oldest first: [{at, by, note}]."""
    v = (meta or {}).get("chases")
    return [c for c in v if isinstance(c, dict)] if isinstance(v, list) else []


def chased_out(meta: dict[str, Any]) -> bool:
    """A relay or anchor wait with CHASES_MAX chases on it: its next end asks whether to stop waiting."""
    return stored_kind(meta) in CHASE_KINDS and len(chases_of(meta)) >= CHASES_MAX


# ---------------------------------------------------------------------------------------------------------------- the asks
def subject_of(meta: dict[str, Any], clip: int = 110) -> str:
    """What a relay or an anchor wait is for, as the ask names it: "<party>'s <event>" when the item stores a party that the event does not already name, else the event."""
    event = _model.clean(meta.get("wait_event")) or (_wl.relay_event(meta) if _wl.stored(meta) else "") or "the news"      # a list's open relay line is what the owner is asked about at the backstop day
    party = _model.clean(meta.get("party"))
    text = f"{party}'s {event}" if party and party.lower() not in event.lower() else event
    return text if len(text) <= clip else text[:clip].rstrip() + "…"


def event_of(meta: dict[str, Any]) -> str:
    """What the question shows as waited for, on its own after the question: the wait's event (a list's open relay line), "<party>: <event>" when the item stores a party the event does not already
    name; "" when the item names none."""
    event = _model.clean(meta.get("wait_event")) or (_wl.relay_event(meta) if _wl.stored(meta) else "")      # a list's open relay line is what the owner is asked about at the backstop day
    if not event:
        return ""
    party = _model.clean(meta.get("party"))
    return _event_line(f"{party}: {event}" if party and party.lower() not in event.lower() else event)


def _event_line(text: str) -> str:
    """An event as a question carries it: one line with no middle dot (the ask's own separator), cut at a whole word within EVENT_CLIP and never inside a link."""
    t = " ".join(str(text).replace("\u00b7", "-").split())
    return t if len(t) <= EVENT_CLIP else _bt.cut_words(t, EVENT_CLIP) or t[:EVENT_CLIP - 1].rstrip() + "…"


def waited_for(event: str) -> str:
    """The tail of a server sentence that names what was waited for: the event in its own brackets, never inside the sentence; "" for none."""
    return f" (waiting for: {event})" if event else ""


def _ask_head(question: str, event: str) -> str:
    return _ASK_HEAD + question + (EVENT_LEAD + event if event else "")


def relay_ask(meta: dict[str, Any]) -> str:
    """The relay question, fixed (the design doc): "Decide: <Q_RELAY> Waiting for: <event> · Options: <TAIL>"."""
    return f"{_ask_head(Q_RELAY, event_of(meta))}{_OPT_MARK}{TAIL}"


def drop_ask(meta: dict[str, Any]) -> str:
    """The question an item chased twice comes with: "Decide: <Q_DROP> Waiting for: <event> · Options: <TAIL>"."""
    return f"{_ask_head(Q_DROP.format(n=len(chases_of(meta))), event_of(meta))}{_OPT_MARK}{TAIL}"


def _question_rx(template: str) -> "re.Pattern[str]":
    body = re.escape(template).replace(re.escape("{n}"), r"(?P<n>\d+)").replace(re.escape("{note}"), r"(?P<note>.*?)")
    return re.compile(r"(?:Decide: )?" + body + r"(?:" + re.escape(EVENT_LEAD) + r"(?P<event>.*))?", re.S)


_QUESTIONS = tuple((kind, _question_rx(t)) for kind, t in (("relay", Q_RELAY), ("drop", Q_DROP)))


def read_question(text: Any) -> dict[str, str] | None:
    """The parts of a question the server wrote, for a page that draws it in its reader's language: {kind: relay | drop, event, n} ("" for a part it has none of). `text` is the
    whole ask line, or its Decide part as the owner's step carries it. None for any other text."""
    head = str(text or "").split(_OPT_MARK)[0].strip()
    for kind, rx in _QUESTIONS:
        m = rx.fullmatch(head)
        if m:
            got = m.groupdict()
            return {"kind": kind, **{k: str(got.get(k) or "") for k in ("event", "n")}}
    return None


# the wording an earlier version stored, which an open question, or a page drawn before the release, still carries
_OLD_LABELS = {"arrived": ARRIVED, "drop": DROP}
_OLD_HEADS = (
    ("relay", re.compile(r"Decide: has (?P<event>.*) arrived\?", re.S)),
    ("drop", re.compile(r"Decide: drop it\? (?P<event>.*) did not arrive after (?P<n>\d+) chases", re.S)),
    ("back", re.compile("Decide: when should (?P<event>.*?) come back\\? (?:I kept your note \\(\u201c(?P<note>.*)\u201d\\) but could not read a date from it|I kept your answer but it holds no date[^.]*)"
                        "\\. Pick a day, or write a date in the box", re.S)),      # the question put back after a date no one could read: no button needs a date now, so it is asked again as the plain question
)


def new_label(label: str) -> str:
    """A button's label as it reads today: an earlier version's label becomes its successor, any other text is itself."""
    return _OLD_LABELS.get(label, label)


def option_kind(label: str) -> str:
    """Which button of a watcher ask `label` is: arrived | week | drop, "" for none of them. An earlier version's label is not one."""
    return {ARRIVED: "arrived", WEEK: "week", DROP: "drop"}.get(label, "")


def current_choice(meta: dict[str, Any], choice: str) -> str:
    """A posted choice named as the item's buttons name it now: the label (bare, or "B · <label>") a button had before it was reworded becomes its new one, when the item offers that one and not
    the posted one. Anything else comes back as it is."""
    if not asked_of(meta):
        return choice
    labels = [o.get("label") for o in meta.get("options") or [] if isinstance(o, dict)]
    m = re.fullmatch(r"([A-Z] \u00b7 )?(.*)", choice, re.S)
    lead, name = (m[1] or "", m[2]) if m else ("", choice)
    return lead + new_label(name) if name not in labels and new_label(name) in labels else choice


def _reworded_head(meta: dict[str, Any], head: str) -> str:
    """Today's head for a question head an earlier version stored, "" when `head` is none of those. What is waited for comes from the wait's own fields (kept under watch.was while the item is the
    owner's), else from the words the old head carried."""
    for kind, rx in _OLD_HEADS:
        m = rx.fullmatch(head)
        if not m:
            continue
        got = m.groupdict()
        w = meta.get("watch") if isinstance(meta.get("watch"), dict) else {}
        was = w.get("was") if isinstance(w.get("was"), dict) else {}
        old = str(got.get("event") or "")
        event = event_of({**was, **{k: meta[k] for k in ("party", "wait_event") if meta.get(k)}}) or ("" if old == "the news" else _event_line(old))
        if kind == "drop" or (kind == "back" and asked_of(meta) == "dropit"):
            question = Q_DROP.format(n=got.get("n") or len(chases_of(meta)))
        else:
            question = Q_RELAY
        return _ask_head(question, event)
    return ""


def is_watcher_ask(ask: Any) -> bool:
    """Is this ask one of the two above (they carry no Recommend, Stakes or By, so the ask shape of render.parse_ask does not read them: the ask check lets them stand)."""
    t = str(ask or "")
    return t.startswith(_ASK_HEAD) and _OPT_MARK in t and " · Recommend: " not in t


def options(today: dt.date | None = None) -> list[dict[str, Any]]:
    """The buttons of every question a due wait asks, in the shape of an option the owner's page offers (label, line, recommended): it happened, one more week, stop waiting. None is marked recommended (the
    page draws no badge: options_of lets a watcher ask carry none). The week's end is counted when it is picked (answer_effect), not stored."""
    return [{"label": ARRIVED, "line": LINE_ARRIVED, "recommended": False},
            {"label": WEEK, "line": LINE_WEEK, "recommended": False},
            {"label": DROP, "line": LINE_DROP, "recommended": False}]


def has_current_buttons(meta: dict[str, Any]) -> bool:
    """Does the stored question carry exactly today's three buttons? A question an earlier version put (a typed date, three days, "keep waiting") does not."""
    return [o.get("label") for o in meta.get("options") or [] if isinstance(o, dict)] == list(CHOICES)


def refreshed(meta: dict[str, Any], today: dt.date | None = None) -> tuple[str, list[dict[str, Any]]] | None:
    """The stored relay or "stop waiting?" question of an open item, in today's shape: (ask, options), or None when it needs nothing (no watcher ask on it, or its words and its three buttons are today's, so a second
    look changes nothing). A question an earlier version worded is worded again (the question put back after an unreadable date becomes the plain one); one with other buttons gets the three."""
    asked = asked_of(meta)
    if not asked:
        return None
    head = str(meta.get("ask") or "").split(_OPT_MARK)[0]
    reworded = _reworded_head(meta, head)
    if not reworded and has_current_buttons(meta) and str(meta.get("ask") or "").endswith(_OPT_MARK + TAIL):
        return None
    return (reworded or head) + _OPT_MARK + TAIL, options()


def apply_refresh(meta: dict[str, Any], today: dt.date | None = None) -> bool:
    """`refreshed` written onto the item's metadata (False: nothing to do), with what goes with a new wording: the server's step on the owner's checklist says the new question where it stood (never dropped and
    added, so nothing is asked anew), the arrival note stops splicing the event into a sentence, and the question as it read before is kept (watch.reworded), so that a page drawn before still names the
    question it showed (a button it had that is gone is then a late pick, which the answer path keeps as a note)."""
    new = refreshed(meta, today)
    if new is None:
        return False
    old_ask, old_options = str(meta.get("ask") or ""), meta.get("options")
    renamed = bool(_reworded_head(meta, old_ask.split(_OPT_MARK)[0]))
    meta["ask"], meta["options"] = new
    w = {k: v for k, v in meta["watch"].items() if k != "reworded"}
    w["reworded"] = {"ask": old_ask, "options": old_options, "to": new[0]}
    meta["watch"] = w
    if renamed:
        rec = meta.get(_ask_leaves.REC)
        if isinstance(rec, dict) and " ".join(str(rec.get("text") or "").split()) == " ".join(old_ask.split()):
            meta[_ask_leaves.REC] = {**rec, "text": " ".join(new[0].split())}      # the same question since the same moment
        _owner_steps.reword(meta, _owner_steps.decide_of(new[0]), str(meta.get("owner") or ""))
        woke = meta.get("woke")
        m = re.fullmatch(r".* is due: (its ask-by day \S+ came)", str(woke.get("what") or ""), re.S) if isinstance(woke, dict) else None
        if m:
            meta["woke"] = {**woke, "what": m[1]}
    return True


def before_rewording(meta: dict[str, Any]) -> dict[str, Any] | None:
    """The item's metadata with the question as it read before apply_refresh worded it again, while the question that stands is that rewording; None otherwise. The answer path takes a form that carries its reference."""
    w = meta.get("watch")
    r = w.get("reworded") if isinstance(w, dict) else None
    if not isinstance(r, dict) or not asked_of(meta) or r.get("to") != meta.get("ask"):
        return None
    return {**meta, "ask": r.get("ask"), "options": r.get("options")}


def day_words(day: dt.date, today: dt.date | None = None) -> str:
    """A day as a person reads it: "Tue Nov 17th", with the year when it is not the current one (`today`'s, when given; core/datewords)."""
    return _datewords.day_words(day, today)


# ---------------------------------------------------------------------------------------------------------------- the wait that turned (the record of what to put back)
WAS_FIELDS = ("wait_kind", "wait_anchor", "wait_event", "mover", "then", "post_wake_mover", "ask_by", "wake", "until", "after", "party", "needs", "waits", "wait_mode")      # waits and wait_mode: a list put back on "not yet" keeps its lines and what had arrived


def was_picker(was: dict[str, Any] | None) -> str:
    """Who picks the item up when the wait ends, as a `was` snapshot (metadata.watch.was) holds it: a snapshot written by older code stores the legacy key, a newer one `mover`; "" when it names nobody."""
    return _model.stored_picker(was or {})


def ends_on_the_date(meta: dict[str, Any], mod: "_model.Model") -> bool:
    """A wait on a date alone (no wait_kind) ends with its date (`end_date`: needs and the mover stay as stored, except when the item passes to the builder, watching.py `watch_fire`) rather than turning to its picker (`turn_alive`: the picker has it, needs is the picker).
    With `external` in needs the item goes back to others at its date, as it always did, whichever mover is stored: only the old post_wake_mover key turns it. Without `external`, a picker stored under
    either key (`mod.wait.mover_explicit`) turns it, the one place a stored mover alone now ends a wait the way the old key did. The one reader of this: the migration pass (waits/mover_pass.py) and the
    watchers' wake (service/watching.py `watch_fire`) cannot read it two ways."""
    if str(meta.get("wait_kind") or "").strip():
        return False
    if "external" in [str(n).strip().lower() for n in _wt.needs_of(meta)]:
        return not str(meta.get(_model.LEGACY_PICKER_KEY) or "").strip()
    return not mod.wait.mover_explicit


def _picker_as_mover(was: dict[str, Any]) -> dict[str, Any]:
    """A `was` snapshot with the picker stored as `mover`, whichever key the item (or an older snapshot) held it under: the legacy key, which wins while stored, is folded into `mover` and goes."""
    legacy = _model.norm_who(was.get(_model.LEGACY_PICKER_KEY))
    if not legacy or legacy.lower() == "none":      # nothing stored, or the word none under the old key (a session of that name there, nobody under `mover`): kept as stored
        return was
    return {**{k: v for k, v in was.items() if k != _model.LEGACY_PICKER_KEY}, "mover": legacy}


def remember(meta: dict[str, Any], asked: str, now: float) -> None:
    """The item is about to turn to the owner for a watcher ask: keep the wait's fields (what to put back on "not yet" or "keep waiting") and which ask is up, under metadata.watch."""
    was = _picker_as_mover({k: meta[k] for k in WAS_FIELDS if meta.get(k) not in (None, "", [])})
    w = dict(meta.get("watch") or {}) if isinstance(meta.get("watch"), dict) else {}
    w.update({"asked": asked, "was": was, "at": now})
    w.pop("reworded", None)      # a new question: no page drawn before it stands for it
    meta["watch"] = w


def asked_of(meta: dict[str, Any]) -> str:
    """Which watcher ask is up on the item: relay | dropit | "" (none)."""
    w = meta.get("watch")
    a = str(w.get("asked") or "") if isinstance(w, dict) else ""
    return a if a in ("relay", "dropit") and is_watcher_ask(meta.get("ask")) else ""


def restore_wait(meta: dict[str, Any], date: str, reset_chases: bool, now: float = 0.0) -> None:
    """Put the wait back on the item with a new end date (the owner's "not yet" or "keep waiting"): its fields as they were, the end moved to `date` (a relay's ask-by, the backstop of an
    anchor wait: its ask_by, the old wake dropped). A moved date resets the backstop and (reset_chases) the chases, a new round; a notice older than `now` is not the wait's arrival."""
    w = meta.get("watch") if isinstance(meta.get("watch"), dict) else {}
    was = _picker_as_mover(dict(w.get("was") or {}))      # a snapshot an older version wrote holds the picker under the legacy key: it is put back as `mover`
    by_until = "until" in was                      # a wait that stood on a stored `until` gets its new end there; one on ask_by gets it there, as it always did
    for k in ("wake", "ask_by", "until"):
        meta.pop(k, None)
    meta.pop(_model.LEGACY_PICKER_KEY, None)      # the picker comes back as `mover`; an old key still on the item would win it
    for k, v in was.items():
        if k not in ("wake", "ask_by", "until"):
            meta[k] = v
    meta["until" if by_until else "ask_by"] = date
    if reset_chases:
        meta.pop("chases", None)
    meta["watch"] = {k: v for k, v in w.items() if k not in ("asked", "was", "failed_at", "reworded")}
    if now:
        meta["watch"]["set_at"] = now


# ---------------------------------------------------------------------------------------------------------------- the arrival
LIVE_DROP = ("hold", "hold_set", "wake", "until", "wait_basis", "watch_reason", "waiting", "wait_failed", "idle", "after", "recycle", "recycle_at", *_model.WAIT_GROUP, _model.LEGACY_PICKER_KEY)      # what the end of a wait clears (watch_reason: a front agent's reason for watching belonged to this wake, as the old wake pass dropped it)


def end_wait(meta: dict[str, Any]) -> None:
    """A wait ends (the watcher's arrival, the owner's Done on a step): what LIVE_DROP lists goes, and the owner's words for the wake go with the wake. A cap_ok record from an
    earlier version that still holds a `due` key keeps that key as it was: nothing writes one now, and nothing here depends on it."""
    for k in LIVE_DROP:
        meta.pop(k, None)
    if isinstance(meta.get("cap_ok"), dict):
        co = {k: v for k, v in meta["cap_ok"].items() if k not in ("wake", "by", "quote", "source")}
        if co.get("due"):
            meta["cap_ok"] = co
        else:
            meta.pop("cap_ok", None)


def turn_alive(meta: dict[str, Any], mover: str, what: str, now: float) -> None:
    """The wait is over and the item is an agent's: the hold, the wake, `after` and the wait's fields go, the mover is the post-wake mover (also the one session in needs, so every
    reader of needs sees the same mover), and the arrival is recorded once (`woke`: what arrived and who has it)."""
    end_wait(meta)
    meta["mover"] = mover
    meta.pop("then", None)
    meta["needs"] = [mover]
    meta["woke"] = {"what": what, "to": mover, "at": now}
    if isinstance(meta.get("watch"), dict):
        meta["watch"] = {k: v for k, v in meta["watch"].items() if k not in ("asked", "was", "failed_at", "reworded")}
        if not meta["watch"]:
            meta.pop("watch")


DATE_DROP = ("hold", "hold_set", "wake", "until", "wait_basis", "watch_reason", "waiting", "wait_failed", "idle", "waits", "wait_mode", _model.SERVER_END_KEY)      # what the end of a wait on the date alone clears (the two of a list that did not hold, with it)


def end_date(meta: dict[str, Any], what: str, to: str, now: float) -> None:
    """A wait on a date alone (no wait_kind) ends: the date and what stood on it go and the arrival is recorded; `needs`, an open `after` link, a pane recycle and the mover stay as stored (the caller sets mover and needs first when the item passes to the builder), so an
    item that waited with needs=external goes back to others, and no date passing takes a link the item still waits on."""
    for k in DATE_DROP:
        meta.pop(k, None)
    if isinstance(meta.get("cap_ok"), dict):
        co = {k: v for k, v in meta["cap_ok"].items() if k not in ("wake", "by", "quote", "source")}
        if co.get("due"):
            meta["cap_ok"] = co
        else:
            meta.pop("cap_ok", None)
    meta["woke"] = {"what": what, "to": to, "at": now}
    if isinstance(meta.get("watch"), dict):
        meta["watch"] = {k: v for k, v in meta["watch"].items() if k not in ("asked", "was", "failed_at", "reworded")}
        if not meta["watch"]:
            meta.pop("watch")


def turn_to_owner(meta: dict[str, Any], then: str, ask: str, options: list[dict[str, Any]], what: str, now: float, picker: str = "") -> None:
    """The wait is over and the item is the owner's move: needs is decision alone (a second mover in needs is refused by the guards; the one who takes it after him is `then`, the post-wake
    mover), the ask and its options up. On a board of several members the question goes to the member who picks the wait up (`picker`, else the one the item names: model.wake_member), stored as
    the `mover`, never to whoever the list names first."""
    who = _model.wake_member(meta, picker)      # read before the stored mover goes
    for k in LIVE_DROP:
        meta.pop(k, None)
    meta.pop("mover", None)
    if then:
        meta["then"] = then
    else:
        meta.pop("then", None)
    meta["needs"] = ["decision"]
    meta["ask"], meta["options"] = ask, options
    if who:
        meta["mover"] = who
    meta["woke"] = {"what": what, "to": who or _model.owner_display(), "at": now}


def woke_line(meta: dict[str, Any], label=str) -> str:
    """get's `woke: <what arrived> → <mover>` ("" when the item has no arrival on record)."""
    w = meta.get("woke")
    if not isinstance(w, dict) or not w.get("what"):
        return ""
    to = str(w.get("to") or "")
    return f"woke: {w['what']} → {label(to) if to and not _model.is_owner(to) else to or 'no one'}"


def chases_line(meta: dict[str, Any], label=str) -> str:
    """get's `chases: n` with the last one's note and who logged it ("" when none)."""
    rows = chases_of(meta)
    if not rows:
        return ""
    last = rows[-1]
    return f"chases: {len(rows)} (last by {label(str(last.get('by') or ''))}: {last.get('note') or ''})"


def world_line(gid_shown: str, subject: str, meta: dict[str, Any]) -> str:
    """One line of the brief's "waiting on the world": the item, what it waits on, its ask-by date, its chases."""
    n = len(chases_of(meta))
    return f"- {gid_shown} {subject}: {subject_of(meta)}, ask by {_model.clean(relay_day(meta)) or 'no date'}" + (f", chased {n}x" if n else "")


# ---------------------------------------------------------------------------------------------------------------- the owner's answer
_NUM_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
_REL_SPAN = re.compile(r"\b(?:in\s+)?(?:(?P<more>another)|(?P<n>\d{1,3}|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)(?P<mo>\s+more)?)\s+(?P<unit>day|week|fortnight|month)s?\b(?!\s+(?:ago|before|earlier))")


def _add_months(day: dt.date, months: int) -> dt.date:
    """`day` moved by whole months, the day of the month cut to the last day of a shorter month (Jan 31st + 1 month = Feb 28th)."""
    y, m = divmod(day.year * 12 + day.month - 1 + months, 12)
    first = dt.date(y, m + 1, 1)
    nxt = dt.date(y + (m == 11), (m + 1) % 12 + 1, 1)
    return first.replace(day=min(day.day, (nxt - first).days))


_REL_CUES = r"(?:for|after|wait|give it|ask again|ask me|remind me|check back|park(?: it)?|again|snooze(?: it)?|until)"
_REL_FILLER = r"(?:ok|okay|yes|sure|please|just|maybe|then|hmm|well|so|and|let'?s)"
_REL_TAIL = re.compile(r"\s*(?:ago|already|report|before|earlier)\b")


def _rel_span(m, today: dt.date, base: dt.date | None) -> dt.date | None:
    n = 1 if m["more"] else (int(m["n"]) if m["n"].isdigit() else _NUM_WORDS[m["n"]])
    start = base if (m["more"] or m["mo"]) and base and base > today else today
    if m["unit"] == "month":
        return _add_months(start, n)
    return start + dt.timedelta(days=n * {"day": 1, "week": 7, "fortnight": 14}[m["unit"]])


def _end_of_month(today: dt.date) -> dt.date:
    last = _add_months(today.replace(day=1), 1) - dt.timedelta(days=1)
    return last if last > today else _add_months(today.replace(day=1), 2) - dt.timedelta(days=1)


_REL_TABLE = (
    (_REL_SPAN, _rel_span),
    (re.compile(r"\bend of (?:the |this )?week\b"), lambda m, t, b: t + dt.timedelta(days=(4 - t.weekday()) % 7 or 7)),      # this week's Friday; on a Friday or after, the next one
    (re.compile(r"\bend of (?:the |this )?month\b"), lambda m, t, b: _end_of_month(t)),
    (re.compile(r"\bafter the weekend\b"), lambda m, t, b: t + dt.timedelta(days=7 - t.weekday())),
    (re.compile(r"\bnext month\b"), lambda m, t, b: _add_months(t, 1)),
)


def _relative_date(low: str, today: dt.date, base: dt.date | None) -> dt.date | None:
    """The small table of relative phrases (no model), read only when no older reader found a date: a span of days, weeks or months ("a week", "one more week", "another week", "two weeks", "in 3 days",
    "a fortnight", "a month from now", "in a month"), "next month", "end of the week" (the Friday), "end of the month" (its last day), "after the weekend" (the Monday). The older readers read "the day after tomorrow" (two days).
    A span counts from today; "more" and "another" count from `base` (the date the wait already ends on) when it is after today, else from today.
    Only a note that is mostly a date phrase reads: the phrase is the whole note, or at its start (after a word like please or ok), or comes right after a cue word (for, after, wait, give it, ask again, ask me, remind me,
    check back, park it, snooze it, again, until; "in a week" is a phrase like any other, not a cue), is not part of a hyphenated word, and is not followed by ago, already, report, before or earlier; a bare "a day" or "one day" is the idiom, not a span. Of
    several phrases the first in the text counts. None when no phrase passes."""
    found = [(m.start(), m.end(), d) for rx, fn in _REL_TABLE for m in rx.finditer(low) if (d := fn(m, today, base))]
    for start, end, d in sorted(found):
        lead = " ".join(re.sub(r"[^\w\s']", " ", low[:start]).split())
        filler = re.fullmatch(r"(?:" + _REL_FILLER + r"\s*)*", lead) is not None
        cued = re.search(r"(?:^|\s)" + _REL_CUES + r"$", lead) is not None      # a cue word right before the phrase, whatever came before it ("in N units" has no cue of its own: it stands where any phrase may)
        if not (filler or cued):
            continue
        if low[start - 1:start] == "-" or low[end:end + 1] == "-" or _REL_TAIL.match(low[end:]):
            continue
        if re.fullmatch(r"(?:a|an|one) day", low[start:end]) and not cued:
            continue
        return d
    return None


def parse_date(text: Any, today: dt.date | None = None, base: dt.date | None = None) -> str:
    """The date the owner gave, as YYYY-MM-DD ("" when none can be read, or it is not after today). Reads 2099-03-09, Mar 9th, Mon Mar 9th, 9 Mar, 9th March, tomorrow, next week, in 3 days, in 2 weeks, a weekday name (the next one, "next Monday" too); a month and day without a year is the next one to come. The small table of relative phrases (_relative_date: one more week, a week, two weeks, next month, a month, end of the week or month, after the weekend), read last, reads too; `base` is the date a wait already ends on, which "one more week" counts from. The instance's own words ([keywords.dates]: a month and a day number
    followed by month_suffix and day_suffix, a day number alone, N days or weeks later, tomorrow, the day after tomorrow, next week) read the same."""
    today = today or dt.date.today()
    t = str(text or "")
    low = t.lower()
    best: dt.date | None = None
    mo_s, dy_s, wk_s, lat_s = (_cfg.kw_alt("dates", k) for k in ("month_suffix", "day_suffix", "week_suffix", "later_words"))      # the instance's own date words, "" for none

    def nxt(month: int, day: int) -> dt.date | None:
        for year in (today.year, today.year + 1):
            try:
                cand = dt.date(year, month, day)
            except ValueError:
                continue
            if cand > today:
                return cand
        return None
    m = re.search(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", t)
    if m:
        try:
            best = dt.date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            best = None
    months = "jan feb mar apr may jun jul aug sep oct nov dec".split()
    mon = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    if best is None:
        m = re.search(rf"(\d{{1,2}})\s*(?:{mo_s})\s*(\d{{1,2}})\s*(?:{dy_s})", t, re.I) if mo_s and dy_s else None
        if m:
            best = nxt(int(m[1]), int(m[2]))
    if best is None:
        m = re.search(rf"\b{mon}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", low)
        md = None
        if m:
            md = (months.index(m[1][:3]) + 1, int(m[2]))
        else:
            m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{mon}\b", low)
            if m:
                md = (months.index(m[2][:3]) + 1, int(m[1]))
        if md:
            best = nxt(*md)
    if best is None:
        m = re.search(rf"(?<!\d)(\d{{1,2}})\s*(?:{dy_s})(?!\s*(?:{lat_s}))" if lat_s else rf"(?<!\d)(\d{{1,2}})\s*(?:{dy_s})", t, re.I) if dy_s else None
        if m:
            y, mo = today.year, today.month
            for _ in range(3):
                try:
                    cand = dt.date(y, mo, int(m[1]))
                except ValueError:
                    cand = None
                if cand and cand > today:
                    best = cand
                    break
                y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    if best is None:
        units = "|".join(x for x in (dy_s, wk_s) if x)
        m = re.search(r"\bin\s+(\d{1,3})\s+(day|week)s?\b", low) or (re.search(rf"(\d{{1,3}})\s*({units})\s*(?:{lat_s})", t, re.I) if units and lat_s else None)
        if m:
            best = today + dt.timedelta(days=int(m[1]) * (7 if (m[2].lower() == "week" or (wk_s and re.fullmatch(wk_s, m[2], re.I))) else 1))
        elif (a_ := _cfg.kw_alt("dates", "day_after_tomorrow")) and re.search(a_, t, re.I):
            best = today + dt.timedelta(days=2)
        elif re.search(r"\bday after tomorrow\b", low):
            best = today + dt.timedelta(days=2)
        elif re.search(r"\btomorrow\b" + _cfg.kw_pipe(_cfg.kw_alt("dates", "tomorrow")), low):
            best = today + dt.timedelta(days=1)
        elif re.search(r"\bnext week\b" + _cfg.kw_pipe(_cfg.kw_alt("dates", "next_week")), low):
            best = today + dt.timedelta(days=7)
    if best is None:
        days = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
        m = re.search(r"\b(mon|tue|wed|thu|fri|sat|sun)(?:day|sday|nesday|rsday|urday)?\b", low)
        if m:
            ahead = (days.index(m[1]) - today.weekday()) % 7 or 7
            best = today + dt.timedelta(days=ahead)
    if best is None:      # no older reader found a date: the table of relative phrases (only a note that is mostly a date phrase)
        best = _relative_date(low, today, base)
    return best.isoformat() if best is not None and best > today else ""


def answer_effect(meta: dict[str, Any], choice: str, text: str, today: dt.date | None = None) -> dict[str, str]:
    """What the owner's pick on a watcher ask does: {"do": arrived | wait | drop | words | "", "date": the new end date for a wait}. "" = the pick is not one of this ask's buttons.
    arrived → the item goes to its post-wake mover; wait (one more week) → the wait is put back with its end a week from today; drop → close as not planned;
    words = an answer in the box with no button (any other wait is such a note): it is never read as arrived or as drop, the item goes to its post-wake mover with his words and the record of the wait, and the mover judges."""
    asked = asked_of(meta)
    if not asked:
        return {"do": ""}
    c = new_label(str(choice or "").strip())      # a button as an earlier version named it still counts
    if not c:                              # an answer in the box with no button: his words, which the post-wake mover reads
        return {"do": "words", "text": str(text or "").strip()}
    if c == ARRIVED:
        return {"do": "arrived"}
    if c == DROP:
        return {"do": "drop"}
    if c == WEEK:      # a week from the day he picks it: the question may have stood for days, and a day that has passed is no end
        return {"do": "wait", "date": ((today or dt.date.today()) + dt.timedelta(days=WEEK_DAYS)).isoformat()}
    return {"do": ""}


# ---------------------------------------------------------------------------------------------------------------- the words of an arrival
def what_time(wake: str) -> str:
    return f"its wake {wake} came"


def what_until(date: str) -> str:
    return f"its until {date} came"


def what_item(closed: str, how: str) -> str:
    return f"{closed}, the last item it waited on, {how}"


def what_item_backstop(date: str, still_open: list[str]) -> str:
    return f"its backstop {date} came and {', '.join(still_open) or 'the item it waited on'} {'is' if len(still_open) < 2 else 'are'} still open"


def what_anchor(url: str, gist: str, how: str) -> str:
    g = _model.clean(gist)
    return f"a notice from {url} {how}" + (f": {g[:200]}" if g else "")


def what_anchor_silent(url: str, date: str) -> str:
    return f"the anchor stayed silent: {url} had no notice by {date}"


def what_event(ev: dict[str, Any]) -> str:
    """An event wait's arrival: what the server was told (event_waits.arrival)."""
    return _ew.arrival(ev)


def what_event_silent(phrase: Any, date: str) -> str:
    return f"the event did not come: {_ew.words(phrase)} was not reported by {date}"


def what_list(meta: dict[str, Any], cause: str, shown=str) -> str:
    """A list's arrival: what the list's end says, from the record of what arrived (read before the wait's fields are dropped), the form the message to the mover and the History carry:
    "all 3 arrived: a; b; c", "any of 3 arrived: a; not needed: b; c", "backstop day 2026-11-20: arrived a; b; still open: c; d" (waits/wait_list.outcome_text)."""
    return _wl.outcome_text(meta, cause, shown)


def message(rows: list[tuple[str, str, str, str]]) -> str:
    """One message to one recipient, rows = [(item shown, what arrived, subject, link)]. One item alone is one line; several are a count and one line each."""
    if len(rows) == 1:
        g, what, subj, link = rows[0]
        return f"[stackshot] {g} is yours now: {what}. {subj} → {link}"
    out = [f"[stackshot] {len(rows)} items are yours now, their waits ended:"]
    out += [f"- {g}: {what}. {subj} → {link}" for g, what, subj, link in rows]
    return "\n".join(out)


def anchor_hit(event: Any, text: Any, auto: bool) -> bool:
    """Does this notice count as the awaited event. Any notice that reaches the server for the anchor does, and the post-wake mover judges a false hit; one exception: a routine line the
    anchor module logged and ruled itself (the fleet's own PR: a push, CI passing, an open) does not end a wait for a merge, a close or a landing, which needs a line that says so."""
    if not auto:
        return True
    if re.search(r"merg|clos|land|done|resolv|finish|complet", _model.clean(event).lower()):
        return bool(re.search(r"merg|clos", _model.clean(text).lower()))
    return True
