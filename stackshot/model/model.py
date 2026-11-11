"""model.py — the item model of the redesign (the design: docs/design): an item is dead, alive or waiting.

  dead      closed (completed, not planned, duplicate)
  alive     someone inside the perimeter is working: one mover (the owner, a session, or the project's background agent), and `then`, who takes it after
            the owner's answer or step
  waiting   nothing happens until something outside arrives: a time (wake), an anchor's event, another item's close (after), or news only the owner
            relays; the post-wake mover judges the arrival

This module is the data layer of that model, additive to today's fields: it reads an item and says which of the three it is, who the effective mover is
(and whether the item stored it or the model defaulted it), and the effective wait. It changes no stored field and no page. The fields it reads, all
optional and all in the item's metadata:

  goal              the end-state in one sentence (shown by get and the brief; not used to derive anything)
  mover             who moves an alive item now: the owner, a session name, or the project's background agent; on a waiting item, who picks it up when the wait ends
  then              who takes an item after the owner's answer or step: it stands only while the owner is the mover (an alive item he moves, or a waiting one he picks up), whatever is stored
  wait_kind         time | anchor | item | relay | event, what an item waits on
  wait_anchor       the anchor (URL) an anchor wait watches
  wait_event        the event expected: of the anchor (anchor wait), the party or event the owner relays (relay wait), or the fleet event an event wait watches for (event_waits.py)
  ask_by            YYYY-MM-DD, the day a relay wait turns into a question to the owner
  until             YYYY-MM-DD or YYYY-MM-DDTHH:MM, the one date a wait ends on (read as a wake is read): an open item that stores one is waiting, wait_kind or not (no kind = a wait on the date
                    alone, kind time); with a kind it is the date the wait comes back anyway (the backstop), for a relay the day it turns into a question. Read first, the legacy wake and ask_by after
  post_wake_mover   the old name of a waiting item's `mover`; while it is stored (not yet moved into `mover`) it wins over a stored `mover`
  (the wait's other inputs are fields an item already had: wake for a time, after for an item; for an anchor or an item wait a wake is its backstop)
  phase             alive | waiting, what the board SHOWS the open item as, written by every save of an open item (server._phase_stamp, the one place) and kept true as the clock moves by the
                    minute set's phase sweep (server._phase_sweep: a dated wait's wake coming within the hour, local midnight (instance timezone), an `after` item closing). The readers (view) take the alive-or-waiting
                    decision and the kind of the wait from this stored pair and from nothing else; the fields give the details of the item (its mover, the wake, the anchor), never the decision. Only
                    the writer (view with check=False) works the pair out from the fields
  waits_on          time | anchor | item | relay | event, the kind of the wait the board SHOWS a waiting open item as (shown_pair), stored beside `phase` by the same stamp (server._phase_stamp), absent for an
                    alive item and dropped by a close. It is NOT `wait_kind`: that field is a behaviour switch (a stored one hands the item to the watchers), this one is a label

Where nothing is stored, today's fields decide (design section 2: today's states map onto the three) and section 3's defaults give the mover. Pure
functions of an item and a time, no server import (it reads states.py and waiting.py, as states.py does), so the server, the renderer and the guards
of the next PR share one copy."""
from __future__ import annotations

import dataclasses
import datetime as dt
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from stackshot.model import states as _states
from stackshot.waits import waiting as _wt

DEAD, ALIVE, WAITING = "dead", "alive", "waiting"
PHASES = (ALIVE, WAITING)       # what an open item stores as `phase` (a closed item is dead and stores none)
WAIT_KINDS = ("time", "anchor", "item", "relay", "event")
WAIT_GROUP = ("wait_kind", "wait_anchor", "wait_event", "ask_by", "post_wake_mover", "until")      # what a clear of the wait drops (the wake and after have flags of their own)
MODEL_FIELDS = ("goal", "mover", "then", *WAIT_GROUP)
DROP_ON_CLOSE = ("mover", "then", *WAIT_GROUP)            # a closed item has no mover and waits on nothing; its goal stays as the record
LINE_MAX = 300
ALIVE_STATES = ("doing", "your-call", "your-step")                  # today's states that read as alive (design section 2)
WAITING_STATES = ("outside", "blocked", "parked", "verifying")                # …and as waiting
OWNER_STATES = ("your-call", "your-step")                                    # alive with the owner as the mover, whatever needs says
KIND_WORDS = {"time": "a time", "anchor": "an anchor event", "item": "another item's close", "relay": "news only {owner} relays", "event": "a fleet event"}
_KINDS_IN_NEEDS = ("decision", "external")


def clean(v: Any) -> str:
    """A field's text on one line, its whitespace collapsed."""
    return " ".join(str(v or "").split())


def owner_display() -> str:
    """The owner as the instance names him ([instance] owner), the name an owner-mover is stored and shown as."""
    return _wt._owner_name()


def is_owner(who: Any) -> bool:
    """Does `who` name the owner: the instance's owner name ([instance] owner), in any case."""
    w = clean(who).lower()
    return bool(w) and w == owner_display().lower()


def norm_who(who: Any) -> str:
    """A mover as it is stored: the owner as the instance names him, anything else (a session name or id) as written, on one line."""
    w = clean(who)
    return owner_display() if is_owner(w) else w


def pick_who(who: Any) -> str:
    """A stored mover read as the one who picks a waiting item up: like norm_who, but the literal word none (an old way of writing "no one") names nobody."""
    w = norm_who(who)
    return "" if w.lower() == "none" else w


@dataclass(frozen=True)
class Wait:
    """What a waiting item waits on. `kind` is the stored wait_kind or the one the item's fields read as; `until` is the date the wait is read to end (a wake, a verifying
    item's end, a relay's ask_by) and "" for one that ends on an event (an anchor, an item's close), `backstop` the wake that stands beside such an event (the date
    the item comes back anyway). `due` is true when that date has come (the scheduler's to act on) or, for an item wait, every item it waits after is closed."""
    kind: str
    kind_explicit: bool
    until: str = ""
    backstop: str = ""
    anchor: str = ""
    event: str = ""
    after: tuple[str, ...] = ()
    mover: str = ""            # who picks the item up when the wait ends (Model.picker): the stored post_wake_mover (the old name) if any, else the stored mover, else the default
    mover_explicit: bool = False
    by_until: bool = False     # the date above is the item's stored `until` (not a wake or an ask_by)
    due: bool = False
    basis: str = ""            # a time wait's reason: a real outside date (wait_basis text) …
    owner_words: bool = False  # … or the owner's recorded words (cap_ok)

    @property
    def post_wake_mover(self) -> str:
        """The old name of `mover` (who picks the item up when the wait ends); readers move to `mover`."""
        return self.mover

    @property
    def post_explicit(self) -> bool:
        return self.mover_explicit


@dataclass(frozen=True)
class Model:
    """The item as the model reads it. `state` is dead | alive | waiting; `today` is today's state word it came from ("" for a closed item), `today_derived` whether
    that word was derived (no stored state). For an alive item `mover` is who moves it (`mover_explicit`: stored, False = defaulted), `then` who takes it after the
    owner's answer or step (only while the owner is the mover, or picks the waiting item up; `then_explicit` likewise) and `checkback` the wake that stands on it (a wake an alive item carries, a hand-off's backstop or one stored before until: the item
    stays alive). For a waiting item `wait` says what it waits on and who picks it up when it ends (`wait.mover`, also `Model.picker`; `mover` itself stays empty while it waits). `conflicts` lists what the fields say that cannot both stand (two different
    pickers stored on a waiting item, wait fields on an alive one); the model still answers, the guards of the write path refuse them later."""
    state: str
    today: str = ""
    today_derived: bool = False
    mover: str = ""
    mover_explicit: bool = False
    then: str = ""
    then_explicit: bool = False
    checkback: str = ""
    wait: Wait | None = None
    conflicts: tuple[str, ...] = field(default_factory=tuple)

    @property
    def owner_moves(self) -> bool:
        return self.state == ALIVE and is_owner(self.mover)

    @property
    def picker(self) -> str:
        """Who takes the item after this step: on a waiting item the one who picks it up when the wait ends (the stored post_wake_mover, else the stored mover, else the default),
        `then` while the owner moves an alive one, else the mover itself. `mover` stays empty while an item waits: it is who moves it NOW."""
        if self.state == WAITING and self.wait:
            return self.wait.mover
        return self.then if self.owner_moves and self.then else self.mover

    @property
    def next_mover(self) -> str:
        return self.picker


def _first(m: dict[str, Any], key: str) -> str:
    return clean(m.get(key))


def fallback_mover(project: str) -> str:
    """The session that moves an item of `project` when nothing names one: its builder, else its -main agent (waiting.fallback_mover, which the server installs; "" when none)."""
    return clean(_wt.fallback_mover(clean(project)))


def _defaults(m: dict[str, Any], today: str) -> tuple[str, str]:
    """(the default mover, the default `then`): section 3's defaults when the writer names none. The mover is the owner when needs holds decision (or the state is his: your-call,
    your-step), else the first agent session in needs, else the project's builder, else its -main agent (fallback_mover; never the item's creator). `then` is the first agent
    session in needs, else none: an item does not remember who created it as the one that takes it after the owner."""
    kinds, sess = _states.kinds_of(m), _states.sessions_of(m)
    then = sess[0] if sess else ""
    after = then or fallback_mover(clean(m.get("project")))
    if "decision" in kinds or today in OWNER_STATES:
        return owner_display(), then
    return after, then


def owner_state(m: dict[str, Any], today: str) -> bool:
    """Is the item in a state that is the owner's move: your-call or your-step, or needs holding decision? Then he is its mover (derive's `owner_state`)."""
    return today in OWNER_STATES or "decision" in _states.kinds_of(m)


def settle(item: dict[str, Any], was_his: bool = False, after_open: Callable[[dict[str, Any]], Any] | None = None) -> dict[str, str] | None:
    """Does a STORED mover disagree with the state the item stands in on the owner's side? → None when nothing is to change, else {"mover", "then"}: the values to store ("" drops the field).
      in his state (your-call, your-step, needs decision), an agent stored as mover  → he is the mover; `then` stays if stored (an agent), else the agent that was mover
      the wait on him is over (alive in an agent's state), he stored as mover → an agent in `then` is the mover again and `then` goes, as _answer's Done does it; else only the mover goes
      a wait replaces his state (waiting), he stored as mover → the agent in `then` is the one who picks it up (mover := then, `then` goes) when no post_wake_mover is stored; with one stored, or no agent in `then`, only the mover goes
    The way back only happens for an item that stood in his state (`was_his`: the caller knows it from the version before the write, or, for the migration, from his hand-off record or
    an answer of his on the item): a mover=the owner that a writer stored on an agent's state with no such history is a conflict the model flags, not a hand-back.
    A closed item and an item with no stored mover settle nothing; an unnamed mover is the model's own default and needs no storing."""
    if item.get("status") != "open":
        return None
    m = item.get("metadata") or {}
    mover_s, then_s = norm_who(m.get("mover")), norm_who(m.get("then"))
    if not mover_s:
        return None
    mod = derive(item, None, after_open)
    if mod.state == ALIVE and owner_state(m, mod.today):
        if is_owner(mover_s):
            return None
        return {"mover": owner_display(), "then": then_s if then_s and not is_owner(then_s) else mover_s}
    if not was_his or not is_owner(mover_s) or mod.state == DEAD:
        return None
    if mod.state == ALIVE:
        if then_s and not is_owner(then_s):
            return {"mover": then_s, "then": ""}       # the hand-back, as _answer's Done does it: the agent becomes the mover and `then` goes (it would read as a conflict beside an agent mover)
        return {"mover": ""}                           # no agent in then: only the mover goes, a stored then is left as it is
    if then_s and not is_owner(then_s) and not norm_who(m.get("post_wake_mover")):
        return {"mover": then_s, "then": ""}           # a wait replaces his state: the agent he named to take it picks it up when the wait ends (when no post_wake_mover is stored to say otherwise)
    return {"mover": ""}                               # only the stale live mover goes; a stored post_wake_mover or then stays exactly as stored


def stood_his(item: dict[str, Any] | None, after_open: Callable[[dict[str, Any]], Any] | None = None) -> bool:
    """Was this item (a stored version, or None) alive and in a state that is the owner's move? False for a missing, closed or waiting one, or one that cannot be read."""
    if not item or item.get("status") != "open":
        return False
    try:
        mod = derive(item, None, after_open)
    except Exception:  # noqa: BLE001
        return False
    return mod.state == ALIVE and owner_state(item.get("metadata") or {}, mod.today)


def _epoch_passed(ep: float | None, now: float) -> bool:
    return ep is not None and ep <= now


def derive(item: dict[str, Any], now: float | None = None, after_open: Callable[[dict[str, Any]], Any] | None = None,
           anchored: Callable[[dict[str, Any]], Any] | None = None) -> Model:
    """dead | alive | waiting for an item, with its effective mover and wait. `now` is an epoch (default the clock). `after_open(item)` says which of the items it waits after are
    still open (as states.derive takes it; without it every after link counts as open); `anchored(item)` says an anchor is scoped to the item (without it an outside item
    reads as an anchor wait only when it stores a wait_anchor, else as a relay).

    Where the fields store a model value it is used; where they do not, today's state decides: your-call and your-step → alive, the owner the mover; doing → alive, the
    agent; outside → waiting on an anchor event or the owner's relay; blocked → waiting on an item's close; parked and
    verifying → waiting on a time (the wake, the end date); completed → dead. An item with no stored state reads states.derive's. A stored wait_kind makes the item waiting
    whatever today's state says (and is listed in `conflicts` when the state is an alive one)."""
    if item.get("status") == "completed":
        return Model(DEAD)
    now = time.time() if now is None else now
    m = item.get("metadata") or {}
    today, derived = _states.of(item, after_open)
    kind_set = _first(m, "wait_kind").lower()
    kind_set = kind_set if kind_set in WAIT_KINDS else ""
    su = _wt.stored_until(m)                                   # a stored until is a wait on its own: with no kind, on the date alone
    conflicts: list[str] = []
    waiting = bool(kind_set) or bool(su) or today in WAITING_STATES
    if kind_set and today in ALIVE_STATES and not (kind_set == "event" and derived):      # an event wait on an item with no stored state is the way to store one (the state it would read as is the wait's own)
        conflicts.append(f"wait_kind={kind_set} on an item whose state is {today}, which is alive: the wait wins. To drop the wait, update clear_wait=true; to keep it, park the item: update hold=true (a hold ends a stored work-in-hand state)")
    if not waiting:
        mv_d, then_d = _defaults(m, today)
        mover_s, then_s = norm_who(m.get("mover")), norm_who(m.get("then"))
        mover = mover_s or mv_d
        h_state = owner_state(m, today)
        if mover_s and (h_state or today == "doing") and is_owner(mover_s) != h_state:      # a stored mover against the state it stands in
            whose = f"{owner_display()}'s" if h_state else "an agent's"
            conflicts.append(f"mover={mover_s} on an item whose state is {today}, which is {whose} move")
        then = (then_s or then_d) if is_owner(mover) else ""         # `then` stands only while the owner is the mover; beside an agent mover a stored one is not read
        stray = [k for k in ("wait_anchor", "wait_event", "ask_by", "post_wake_mover") if _first(m, k)]
        if stray:
            conflicts.append(f"{', '.join(stray)} stored on an alive item, which waits on nothing")
        return Model(ALIVE, today, derived, mover, bool(mover_s), then, bool(then_s) and bool(then), clean(m.get("wake")), None, tuple(conflicts))
    # waiting
    if kind_set:
        kind, explicit = kind_set, True
    elif su:
        kind, explicit = "time", False
    elif today == "outside":
        kind, explicit = ("anchor" if (_first(m, "wait_anchor") or (anchored(item) if anchored else False)) else "relay"), False
    elif today == "blocked":
        kind, explicit = "item", False
    else:
        kind, explicit = "time", False
    wake, ask_by = clean(m.get("wake")), _first(m, "ask_by") or (clean(m.get("chase")) if today == "outside" else "")
    until = backstop = ""
    due = False
    if kind == "time":
        end = clean(m.get("end")) if today == "verifying" else ""
        if su:
            until, ep = su, _wt.wake_epoch(su)
        elif wake:
            until, ep = wake, _wt.wake_epoch(wake)
        else:
            until, ep = end, (_wt.due_epoch(end) if end else None)      # a verifying item's end date is its wait, like a wake
        due = _epoch_passed(ep, now)
    elif kind == "relay":
        if su:
            until = su
            due = _epoch_passed(_wt.wake_epoch(su), now)
        else:
            until = ask_by
            due = _epoch_passed(_wt.due_epoch(ask_by) if ask_by else None, now)
    else:
        backstop = su or wake
        if kind == "item":
            due = not (after_open(item) if after_open else _wt.after_of(m)) and bool(_wt.after_of(m))
    mv_d, _ = _defaults(m, today)
    mover_s, post_s = pick_who(m.get("mover")), norm_who(m.get("post_wake_mover"))
    if mover_s and post_s and mover_s != post_s:
        conflicts.append(f"mover={mover_s} and post_wake_mover={post_s} are both stored on a waiting item and differ: post_wake_mover picks it up when the wait ends, until it is moved into mover")
    picker_s = post_s or mover_s        # a stored post_wake_mover (the old name, not yet moved) wins; a mover alone is the picker
    post_d = owner_display() if kind == "relay" else mv_d       # a relay's ask-by day turns the item to him (section 4); the rest the section 3 chain
    picker = picker_s or post_d
    then_s = norm_who(m.get("then")) if is_owner(picker) else ""         # `then` stands only while he is the one who picks the item up
    wait = Wait(kind=kind, kind_explicit=explicit, until=until, backstop=backstop,
                anchor=_first(m, "wait_anchor") if kind == "anchor" else "",
                event=(_first(m, "wait_event") or (clean(m.get("party")) if today == "outside" else "")) if kind in ("anchor", "relay") else (_first(m, "wait_event") if kind == "event" else ""),
                after=tuple(_wt.after_of(m)) if kind == "item" else (), mover=picker, mover_explicit=bool(picker_s), by_until=bool(su), due=due,
                basis=_wt.basis_of(m) if kind == "time" else "", owner_words=bool(kind == "time" and (su or wake) and isinstance(m.get("cap_ok"), dict) and m["cap_ok"].get("wake") == (su or wake)))
    return Model(WAITING, today, derived, "", False, then_s, bool(then_s), "", wait, tuple(conflicts))


def view(item: dict[str, Any], mod: Model, now: float | None = None, after_open: Callable[[dict[str, Any]], Any] | None = None, check: bool = True) -> Model:
    """The model as the board DISPLAYS it. `mod` is derive's reading of the fields; this takes from the item's stored pair (`phase`, `waits_on`) whether it is alive or waiting and the kind of its wait, and keeps
    derive's details (the mover, the wake, the anchor, the post-wake mover) wherever they fit that decision. The stored pair is the only source of the decision: nothing is checked against the fields, no
    disagreement is counted, there is no switch. The sweep (server._phase_sweep) keeps the pair true to the minute, so a pair the clock has just outdated shows for up to a minute until it is restamped.

    An open item that stores no usable pair (a new one not yet saved, or a half-written pair: a phase waiting with no kind) is shown as the writer would store it, and UNSTAMPED counts the read (/audit/status);
    the next save or sweep stores the pair.

    `check` False is the writer that is about to store the pair (server._stamp_values, and the audit's own readings): it works the pair out from the fields, `_shown`, which reads a doing item whose wake is
    more than an hour out while every open step is dated for that day or later (dated_wait.py) as waiting on a time, as it does one stored as doing and put on hold with a wake more than that hour out, and one whose
    still-future wake carries a wait_basis. Doing is work in hand and carries no expected time; an item held there for days is a wait that was stored as work. `derive` itself is unchanged (the guards, the router and
    the hand-off read it as stored)."""
    if not check or mod.state == DEAD:
        return _shown(item, mod, now, after_open)
    sp, sw = stored_phase(item), stored_waits_on(item)
    if not sp or (sp == WAITING and not sw):
        UNSTAMPED["count"] += 1
        return _shown(item, mod, now, after_open)
    if sp == ALIVE:
        return mod if mod.state == ALIVE else _alive_of(item, mod)
    out = mod
    if mod.state == ALIVE:
        out = _shown(item, mod, now, after_open)
        if out.state != WAITING or out.wait is None:
            out = _wait_of(item, mod, sw)
    if out.wait is not None and out.wait.kind != sw:
        out = dataclasses.replace(out, wait=dataclasses.replace(out.wait, kind=sw, kind_explicit=False))
    return out


UNSTAMPED: dict[str, Any] = {"count": 0}      # reads of an open item that stored no usable pair (view showed it as the writer would store it)


def _alive_of(item: dict[str, Any], mod: Model) -> Model:
    """An alive reading for an item that stores `phase` alive while the fields read it as waiting (the clock or a write has since changed them and the sweep has not restamped it yet): the mover and `then` as section 3's defaults give them."""
    m = item.get("metadata") or {}
    mv_d, then_d = _defaults(m, mod.today)
    mover_s, then_s = norm_who(m.get("mover")), norm_who(m.get("then"))
    mover = mover_s or mv_d
    then = (then_s or then_d) if is_owner(mover) else ""
    return Model(ALIVE, mod.today, mod.today_derived, mover, bool(mover_s), then, bool(then_s) and bool(then), clean(m.get("wake")), None, mod.conflicts)


def _wait_of(item: dict[str, Any], mod: Model, kind: str) -> Model:
    """A waiting reading of the stored kind for an item the fields read as alive and not as a view-only wait (a stored wait the clock has outdated since the last restamp): the wake it stands on, and the mover as the post-wake mover."""
    m = item.get("metadata") or {}
    su = _wt.stored_until(m)
    wake = su or clean(m.get("wake"))
    picker_s = norm_who(m.get("post_wake_mover")) or pick_who(m.get("mover"))
    picker = picker_s or mod.mover
    wait = Wait(kind=kind, kind_explicit=False, until=wake if kind == "time" else "", backstop=wake if kind != "time" else "", by_until=bool(su),
                anchor=_first(m, "wait_anchor") if kind == "anchor" else "", event=_first(m, "wait_event") if kind in ("anchor", "relay", "event") else "",
                after=tuple(_wt.after_of(m)) if kind == "item" else (), mover=picker, mover_explicit=bool(picker_s), due=False,
                basis=_wt.basis_of(m) if kind == "time" else "")
    then = mod.then if is_owner(picker) else ""
    return Model(WAITING, mod.today, mod.today_derived, "", False, then, mod.then_explicit and bool(then), "", wait, mod.conflicts)


def _shown(item: dict[str, Any], mod: Model, now: float | None, after_open: Callable[[dict[str, Any]], Any] | None) -> Model:
    if mod.state != ALIVE or mod.today != "doing":
        return mod
    now = time.time() if now is None else now
    from stackshot.waits import dated_wait as _dw  # noqa: PLC0415  (lazy: dated_wait reads steps, which imports this module)
    dw = _dw.basis_wait(item, now, after_open) or _dw.of(item, now) or _dw.held_wait(item, now)
    if dw is None:
        return mod
    ep, basis = dw.until, _dw.basis(dw)
    until = dt.datetime.fromtimestamp(ep, _wt._cfg.tz()).strftime("%Y-%m-%dT%H:%M")
    wait = Wait(kind="time", kind_explicit=False, until=until, mover=mod.mover, mover_explicit=mod.mover_explicit, due=False, basis=basis)
    return Model(WAITING, "doing", mod.today_derived, "", False, mod.then, mod.then_explicit, "", wait, mod.conflicts)


# ---------------------------------------------------------------------------------------------------------------- the stored pair
def shown_pair(mod: Model) -> tuple[str, str]:
    """(phase, wait_kind) of a model as the board shows it: ("alive", "") for an alive item, ("waiting", <the wait's kind>) for a waiting one, ("", "") for a dead one."""
    if mod.state == WAITING and mod.wait is not None:
        return WAITING, mod.wait.kind
    return (mod.state, "") if mod.state in PHASES else ("", "")


def shown_waiting(item: dict[str, Any], now: float | None = None, after_open: Callable[[dict[str, Any]], Any] | None = None) -> bool:
    """Does the board show this item as waiting? True exactly when the phase the board draws for an open item (`view` of `derive`, the stored pair first) is waiting; an item the board shows alive ("on agent",
    or the owner's move) and a closed one are not. The one test the passes that look for a quiet item (the silence pass, the stall pass's `not_due`) use to leave a waiting item alone, so that what they skip is
    what the board shows as waiting and nothing else: a stored until (a date alone too), a hold with a wake and a wake with a wait_basis are waits, and a wake kept as a hand-off's backstop (no until) leaves the item on agent. Raises what `derive` raises for an item it cannot read."""
    if item.get("status") != "open":
        return False
    return view(item, derive(item, now, after_open), now, after_open).state == WAITING


def stored_phase(item: dict[str, Any]) -> str:
    """The phase an OPEN item stores, "" when it stores none (or a value that is not a phase, or the item is closed: a closed item is dead and stores neither phase nor wait)."""
    if item.get("status") != "open":
        return ""
    v = _first(item.get("metadata") or {}, "phase").lower()
    return v if v in PHASES else ""


def stored_waits_on(item: dict[str, Any]) -> str:
    """The waits_on an OPEN item stores ("" when none, or not one of the five kinds, or the item is closed)."""
    if item.get("status") != "open":
        return ""
    k = _first(item.get("metadata") or {}, "waits_on").lower()
    return k if k in WAIT_KINDS else ""


def stamp_values(item: dict[str, Any], shown: Model) -> tuple[str, str]:
    """(phase, waits_on) an item stores for the model the board shows (`shown`, model.view of derive): ("alive", "") for an alive open item, ("waiting", <the wait's kind>) for a waiting one, ("", "") for a closed
    item (it is dead and stores neither). "" = the key is absent. The one place the two stored values are worked out: the save's stamp (server._phase_stamp) and the stamp pass (server._stamp_one) both call it."""
    if item.get("status") != "open":
        return "", ""
    phase, kind = shown_pair(shown)
    return phase, (kind if phase == WAITING else "")


def derived_fields(mod: Model) -> list[str]:
    """The model fields the item does not store and the model filled in: what a session sets to say it itself (mover, then, wait_kind)."""
    if mod.state == ALIVE:
        return [k for k, v, e in (("mover", mod.mover, mod.mover_explicit), ("then", mod.then, mod.then_explicit)) if v and not e]
    if mod.state == WAITING and mod.wait:
        return [k for k, e in (("wait_kind", mod.wait.kind_explicit), ("post_wake_mover", mod.wait.mover_explicit)) if not e]
    return []


def words(mod: Model, label: Callable[[str], str] = str, shown: Callable[[str], str] = str, derived: bool = True) -> str:
    """The model as one plain line for get and the brief:
      model: alive · mover the owner (then my-x)
      model: waiting on a time (wake 2099-03-02) · mover my-x
      model: waiting on a time (wake 2099-03-02) · mover the owner (then my-x)
    `label` shows a session reference as people read it, `shown` an item id. A trailing `derived: mover, then` names what the item does not store (derived=False leaves it off: the brief)."""
    who = lambda w: label(w) if w and not is_owner(w) else (w or "no one")
    d = derived_fields(mod) if derived else []
    tail = f" · derived: {', '.join(d)}" if d else ""
    if mod.state == DEAD:
        return "model: dead"
    if mod.state == ALIVE:
        out = f"model: alive · mover {who(mod.mover)}" + (f" (then {who(mod.then)})" if mod.then else "")
        if mod.checkback:
            out += f" · backstop {mod.checkback}"
        return out + tail
    w = mod.wait
    if w is None:
        return "model: waiting"
    back = lambda legacy: f"until {w.backstop}" if w.by_until else legacy      # a stored `until` reads "until", the legacy wake or ask_by as it always did
    if w.kind == "time":
        what = "a time (" + ((f"until {w.until}" if w.by_until else f"wake {w.until}") if w.until else "no wake set") + ")"
    elif w.kind == "anchor":
        bits = [x for x in (w.anchor or "wait_anchor not set", w.event) if x]      # an anchor scoped to the item stands for it: "no anchor stored" said the item had none when the project's anchors held its anchor
        what = "an anchor (" + ": ".join(bits) + ("; " + back(f"backstop wake {w.backstop}") if w.backstop else "") + ")"
    elif w.kind == "item":
        what = "the close of " + (", ".join(shown(x) for x in w.after) or "no item stored") + (" (" + back(f"backstop wake {w.backstop}") + ")" if w.backstop else "")
    elif w.kind == "event":
        what = "a fleet event (" + (w.event or "wait_event not set") + ("; " + back(f"backstop {w.backstop}") if w.backstop else "") + ")"
    else:
        bits = [x for x in (w.event, (f"until {w.until}" if w.by_until else f"ask by {w.until}") if w.until else "no ask-by date") if x]
        what = f"news only {owner_display()} relays ({'; '.join(bits)})"
    return f"model: waiting on {what} · mover {who(w.mover)}" + (f" (then {who(mod.then)})" if mod.then else "") + tail


def check_fields(values: dict[str, Any]) -> list[str]:
    """What is wrong with the model fields a write passes ({field: value}, only the ones given): one phrase each, [] when all are fine. Format only: the guards that
    judge a write as a whole (an alive item names a mover, a wait names its post-wake mover and input) come with the write guards."""
    out: list[str] = []
    for k in ("goal", "mover", "then", "post_wake_mover", "wait_anchor", "wait_event"):
        v = clean(values.get(k))
        if v and len(v) > LINE_MAX:
            out.append(f"{k} is one line of at most {LINE_MAX} characters (got {len(v)})")
    k = clean(values.get("wait_kind")).lower()
    if k and k not in WAIT_KINDS:
        out.append(f"wait_kind is one of {' | '.join(WAIT_KINDS)} (got {k!r})")
    u = clean(values.get("until"))
    if u and _wt.wake_epoch(u) is None:
        out.append(f"until is YYYY-MM-DD or YYYY-MM-DDTHH:MM, a real date (got {u!r})")
    a = clean(values.get("ask_by"))
    if a:
        try:
            dt.date.fromisoformat(a)
            if len(a) != 10:
                raise ValueError
        except ValueError:
            out.append(f"ask_by is YYYY-MM-DD, a real date (got {a!r})")
    return out
