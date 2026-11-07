"""handoff.py — the hand-off machinery of the item model (the design: docs/design, sections 3 and 5, and
its build plan, step 2).

An alive item has one mover. When a write changes the effective mover (model.derive before and after) to a session other than the writer, the item records a HAND-OFF:

  metadata.handoff = {to, to_id, from, at, delivered_at, taken_at, ...}

  to / to_id     the new mover, as the registry names it now, and its permanent or transcript id when known
  from           the writer (name), or the server's own label when the server moved it
  at             when the write happened (epoch seconds)
  delivered_at   when the new mover's session was actually told (a push that came back "delivered"); None until known
  taken_at       when the new mover first started work on the item (`started`: a step marked done, a work line in progress or done, the item closed; an anchor scoped to it counts through `plan`); None until then. A note, a confirm, a queue or wait line leaves it None
  resent_at      when the notice was sent a second time because the mover's pane was relaunched after the first one; the clock restarts from the re-send, and it happens once
  no_clock       true when the new mover is the owner (he never times out; his list shows the age) and on every record the server made itself (a wake, an event wake, a release of `after`, the stall pass): the
                 10-minute take clock runs only on a session's hand-off, and the timing of a woken mover stays with the stall pass, which leaves a busy pane alone
  attempts       pushes tried (one retry, then the fallback of section 5); queued: a push that waits (the machine is away, a reboot pause): neither delivered nor failed
  tried          the sessions this item has already been handed to on the way down section 5; origin: the first sender (the last fallback is a return to it)
  cold           {at, state: running | done | failed, answer}: the cold call of section 5 has been asked about this item
  recovery_at    when the ladder, with nobody left to hand the item to, asked the fleet's builder to recover the session (recovery_reason says why): once per record, so a pass that sees it again sends nothing; the
                 mover writing to the item, or the record ending (the item handed on), starts a new episode
  events         the last few lines about what the server did with it ({at, text}), shown on the item

The record stays after it is taken (history); a newer hand-off moves the old one into metadata.handoff_history (the last three).

The clock (section 3: guards first; a short clock only for a delivered hand-off not yet started; return to
the sender last): a delivered hand-off not taken within [model] handoff_minutes goes down section 5, and so does one whose recipient's turn ended with no write to the item (the
CLI registry's busy to idle or shell, read by the caller). Section 5, in order: the project's builder (the background agent whose mandate says build, else maintain, merge or engineer: router_live.builder's pick), the cold `claude -p` call (cold_call.py), the sender (the last fallback; never the owner, a script or the server), and when none of these can take it the item is
handed to the fleet's builder as a recovery request (`recover`: the item stays with its mover and the request is one message). A turn that ends in a relaunch is no answer: when the mover's pane was relaunched (a new process) after the notice was delivered and before it wrote, the notice died with the old process, so
the ladder does not move: the notice is sent again once, to the pane that is back, and the clock restarts from the re-send (`resend`); a second loss goes down the ladder as above. A mover whose session is gone goes down the same ladder without the sender. The owner and a front agent (a session he talks to: an item notice never wakes one) are exempt from the clock and the turn-end rule.

A hand-off to a background agent (a session `Env.remind` resolves, fail closed) that is not taken within `handoff_minutes` of its delivery gets ONE reminder to that session first (`remind`: "start
its subagent alongside the current work"): for such an agent the turn-end rule does not hurry the reminder, the clock alone does. Only when it is still not taken after another `handoff_minutes`
does the ladder go on (again the clock alone). An anchor scoped to the item and added at or after the hand-off (`Env.anchored`) counts as taken, for every mover: a pull request in flight is a
build started; an older anchor (an earlier pull request, one added before the hand-over) says nothing about this hand-off.

This module is pure: it reads items and an Env (the clock, the config, the session checks the server answers) and says what to do (`plan`); the server does it and sends the
messages, one per recipient however many items it fires (`batch`)."""
from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import model as _model
import steps as _steps

KEY = "handoff"
HISTORY = "handoff_history"
HISTORY_KEEP = 3
EVENTS_KEEP = 6
MAX_STEPS = 6                  # moves down section 5 for one item before the fleet's builder is asked instead: no ping-pong
MINUTES = 10.0                 # [model] handoff_minutes
IDLE_GRACE = 20.0              # seconds a recipient must have been idle, after the delivery, for its turn to count as ended with no write (a queued message starts the next turn at once)
GONE_DAYS = 14.0               # a gone mover is looked for on items written within this many days; older ones are the migration's (step 4)
COLD_STALE = 600.0             # seconds after which a cold call that never reported is read as failed
SERVER = "stackshot"           # the label of the server's own moves
COLD = "cold-call"             # the label of the cold call's writes


def clean(v: Any) -> str:
    return " ".join(str(v or "").split())


def default_same(a: Any, b: Any) -> bool:
    """Two session references are one session: the same text in any case, or both the owner. The server passes a stronger one (names, ids and the registry)."""
    a, b = clean(a), clean(b)
    return bool(a and b) and (a.casefold() == b.casefold() or (_model.is_owner(a) and _model.is_owner(b)))


def record_of(item: dict[str, Any] | None) -> dict[str, Any] | None:
    r = ((item or {}).get("metadata") or {}).get(KEY)
    return r if isinstance(r, dict) and r.get("to") else None


def mover_of(item: dict[str, Any] | None, derive: Callable[[dict[str, Any]], "_model.Model"], strict: bool = False) -> str | None:
    """The effective mover of an open alive item ("" for a closed one, a waiting one, or a reading that fails). With `strict` a reading that fails is None, not "": a caller that would end
    or make a record must not take "could not read it" for "has no mover"."""
    if not item or item.get("status") != "open":
        return ""
    try:
        mod = derive(item)
    except Exception:  # noqa: BLE001
        return None if strict else ""
    return clean(mod.mover) if mod.state == _model.ALIVE else ""


def is_script(name: str) -> bool:
    """A script's label ("<sender> via a script on <machine>": cap-words jobs, a migration; "a script on <machine>": the recycle's; "<sender> (a script on
    <machine>)": create and message): its write is no session's, so it hands nothing over and takes nothing."""
    return "a script on " in clean(name)


def _is_system(name: str) -> bool:
    """The server's own label, the cold call's, or a script's: never a session an item goes to or comes back to."""
    return clean(name).casefold() in (SERVER.casefold(), COLD) or is_script(name)


def is_session_name(name: str) -> bool:
    """Can `name` be a session a hand-off goes to or comes back to: not the owner, the server, the cold call or a script's label."""
    n = clean(name)
    return bool(n) and not _model.is_owner(n) and not _is_system(n)


def _add_event(r: dict[str, Any], now: float, text: str) -> None:
    ev = [e for e in (r.get("events") or []) if isinstance(e, dict)]
    ev.append({"at": now, "text": clean(text)[:240]})
    r["events"] = ev[-EVENTS_KEEP:]


add_event = _add_event


# ---------------------------------------------------------------------------------------------------------------- recording
def detect(before: dict[str, Any] | None, after: dict[str, Any], writer: str, writer_id: str, derive: Callable[[dict[str, Any]], "_model.Model"],
           same: Callable[[Any, Any], bool] = default_same) -> str:
    """The session (or the owner) an alive item has just been handed to by this write: the effective mover after it, when it differs from the one before and the writer is not
    that mover itself. "" when the write hands nothing over (no writer: the server's own bookkeeping; a self-naming; the same mover; an item that is not alive after it)."""
    if not (clean(writer) or clean(writer_id)):
        return ""
    m1 = mover_of(after, derive)
    if not m1:
        return ""
    m0 = mover_of(before, derive)
    if m0 and same(m0, m1):
        return ""
    if same(m1, writer) or (clean(writer_id) and same(m1, writer_id)):
        return ""
    return m1


def started(before: dict[str, Any] | None, item: dict[str, Any]) -> str:
    """Why the write that produced `item` out of `before` shows the work started, "" when it shows none. Only what no wording can fake counts: the item closed (open before, not after), a step
    marked done (the checklist's own mark, steps.changes), or a work line (metadata.work) new or moved to `in progress` or `done`. A note, a confirm, a reword of next or description, a hold or a wake,
    a step dropped or a new step, a wait, a timeline line: none of them says work began, so none counts. (An anchor scoped to the item counts through `plan`'s `Env.anchored`, not here.)"""
    if not isinstance(before, dict) or not isinstance(item, dict):
        return ""
    if before.get("status") == "open" and item.get("status") != "open":
        return "closed the item"
    bm, am = before.get("metadata") or {}, item.get("metadata") or {}
    if any(kind == _steps.DONE for kind, _ in _steps.changes(bm, am)):
        return "marked a step done"
    def lines(m: dict[str, Any]) -> set[tuple[str, str, str]]:
        return {(str(w.get("id") or ""), clean(w.get("text")), str(w.get("state") or "")) for w in (m.get("work") or []) if isinstance(w, dict) and w.get("state") in ("in progress", "done")}
    if lines(am) - lines(bm):
        return "set a work line in progress or done"
    return ""


def touch(item: dict[str, Any], name: str, wid: str, now: float, same: Callable[[Any, Any], bool] = default_same, before: dict[str, Any] | None = None) -> bool:
    """The writer touches the item: when it is the mover the last hand-off named, the hand-off is not yet taken and this write shows the work started (`started`: a write out of `before`), it is
    taken now. A write that shows none (a note, a confirm, a queue or wait line) leaves it not taken and the clock running; any write of the mover still ends a recovery request (the session is alive). → True when it was taken."""
    r = record_of(item)
    if not r or r.get("taken_at"):
        return False
    if not ((clean(name) and same(r.get("to"), name)) or (clean(wid) and (same(r.get("to_id"), wid) or same(r.get("to"), wid)))):
        return False
    if r.get("recovery_at"):   # the fleet's builder was asked to recover the session, and now its mover has written to the item: the session is alive, so the request is over (taken or not)
        r.pop("recovery_at", None)
        r.pop("recovery_reason", None)
        _add_event(r, now, f"{clean(name) or clean(wid)} wrote to it: the recovery request is over")
    if not started(before, item):
        return False
    r["taken_at"] = now
    r.pop("stall", None)       # the stall episode ends when its mover takes the item (the flag only keeps an untaken record from going back to a sender)
    return True


def pending_his(item: dict[str, Any] | None) -> dict[str, Any] | None:
    """The hand-off record of an open item when it went to the owner and nobody has taken it yet (so `get` still reads "handed to the owner, not yet taken"), else None."""
    r = record_of(item)
    if not r or (item or {}).get("status") != "open" or r.get("taken_at") or not _model.is_owner(r.get("to")):
        return None
    return r


def answered(item: dict[str, Any], now: float, why: str, at: float | None = None) -> bool:
    """The owner's hand-off is over: his answer, his step or his comment came, or the item left his hands (a session relayed his answer, a state change). He is no session that "takes" an
    item by writing to it, so nothing else ever closed the record, and it read "handed to the owner, not yet taken" for good. The record stays as history, taken at `at` (default now), with
    the reason as its last event. → True when it changed."""
    r = pending_his(item)
    if r is None:
        return False
    r["taken_at"] = float(at if at is not None else now)
    _add_event(r, now, why)
    return True


def _push_history(meta: dict[str, Any], old: dict[str, Any], now: float, why: str) -> None:
    old = dict(old)
    old.setdefault("ended_at", now)
    old.setdefault("ended", clean(why))
    hist = [h for h in (meta.get(HISTORY) or []) if isinstance(h, dict)]
    hist.append(old)
    meta[HISTORY] = hist[-HISTORY_KEEP:]


push_history = _push_history


def new_record(to: str, to_id: str, frm: str, now: float, **extra: Any) -> dict[str, Any]:
    r: dict[str, Any] = {"to": clean(to), "to_id": clean(to_id), "from": clean(frm), "at": now, "delivered_at": None, "taken_at": None}
    if _model.is_owner(to):
        r["no_clock"] = True
    r.update({k: v for k, v in extra.items() if v not in (None, "", [], False)})
    if not r["to_id"]:
        r.pop("to_id")
    return r


def apply(item: dict[str, Any], before: dict[str, Any] | None, name: str, wid: str, now: float, derive: Callable[[dict[str, Any]], "_model.Model"],
          same: Callable[[Any, Any], bool] = default_same, label: Callable[[str], str] = str, ident: Callable[[str], str] = str) -> dict[str, Any] | None:
    """A real write (a session's, the owner's answer, a script's; never the server's own save) has produced `item` out of `before`: first the writer touches the item (the
    hand-off it was named in is taken), then a mover change makes a new record, the old one moving into the history. The item is changed in place. → the new record, or None.
    A write by the server's own labels (the cold call) keeps the way down section 5 already walked: `tried`, `cold`, `origin`."""
    touch(item, name, wid, now, same, before)
    to = detect(before, item, name, wid, derive, same)
    if not to:
        return None
    meta = item.setdefault("metadata", {})
    old = record_of(item)
    frm = clean(name) or clean(wid)
    carry: dict[str, Any] = {}
    if old and not old.get("taken_at") and _is_system(name):
        carry = {"tried": [*(old.get("tried") or []), old.get("to")], "origin": old.get("origin") or old.get("from"), "cold": old.get("cold"), "steps": int(old.get("steps") or 0) + 1}
    r = new_record(label(to), ident(to), frm, now, **carry)
    if old:
        _push_history(meta, old, now, "handed on" + ("" if old.get("taken_at") else ", not taken"))
    meta[KEY] = r
    return r


def is_open(r: dict[str, Any] | None) -> bool:
    """An open record: one nobody has taken yet (one with a recovery request included: nobody could). A taken record is history, whoever the mover is now."""
    return bool(r) and not r.get("taken_at")


def follows(r: dict[str, Any] | None, mover: str, same: Callable[[Any, Any], bool] = default_same) -> bool:
    """Does the record name `mover` (by name or by id)?"""
    return bool(r) and bool(clean(mover)) and (same(r.get("to"), mover) or same(r.get("to_id"), mover))


def _kept(item: dict[str, Any], r: dict[str, Any] | None) -> bool:
    """A record the invariant leaves alone: one with a recovery request, of an open item (the ladder's own mark: nobody could take it, the fleet's builder was asked; the mover's write clears it). `follow` ends it
    all the same when a save of the server's own moves the item on to another session."""
    return bool(r) and bool(r.get("recovery_at")) and item.get("status") == "open"


def stale(item: dict[str, Any], mover: str, same: Callable[[Any, Any], bool] = default_same) -> bool:
    """The one invariant of the record: an item has no OPEN record whose `to` differs from its effective mover (`mover` = "" for a closed item, a waiting one, one with no mover)."""
    r = record_of(item)
    return is_open(r) and not follows(r, mover, same) and not _kept(item, r)


def follow(item: dict[str, Any], before_mover: str, mover: str, now: float, *, frm: str = "", record: bool = False, same: Callable[[Any, Any], bool] = default_same,
           label: Callable[[str], str] = str, ident: Callable[[str], str] = str) -> str:
    """The record follows the effective mover, whatever changed it (a session's write is `apply`'s; this is every save, the server's own included). The item is changed in place.
      - an OPEN record that names someone other than `mover` is stale (one with a recovery request, of an open item, is left, _kept, unless the server's own save moves the item on to another session: then it ends as "handed on" and the new mover gets a record): it goes to the history ("handed on, not taken", or that the item closed or has no mover) and the item keeps none;
      - with `record` (the save was the server's own: no session's write, so `apply` made none) and a `mover` that differs from `before_mover` and is not
        already named by an OPEN record (a taken record to the same name does not count: that session took the item, so a wake that hands it back is a new hand-off), a new record names the
        mover, from `frm`, the old record (a taken one too) moving into the history. The new record is `no_clock`: the take clock (`_due`) never runs on a server-made record, so a woken mover
        is timed by the stall pass alone.
    A script's save passes record=False: it hands nothing over, but it must not leave a record that names the mover it took the item from.
    → "recorded" (a new record), "ended" (a stale one ended), "" (nothing changed)."""
    meta = item.setdefault("metadata", {})
    out = ""
    r = record_of(item)
    moved = bool(record and mover and clean(frm)) and not (clean(before_mover) and same(before_mover, mover))      # the server's own save moved the item on to a session
    kept = _kept(item, r) and not (moved and not follows(r, mover, same))      # a record with a recovery request stays, unless the server moves the item away from the one it names: stall would stay silent for the new mover
    if is_open(r) and not follows(r, mover, same) and not kept:
        why = ("handed on" if r.get("recovery_at") else "handed on, not taken") if mover else ("the item closed" if item.get("status") != "open" else "the item no longer has a mover")
        _push_history(meta, r, now, why)
        meta.pop(KEY, None)
        r, out = None, "ended"
    if moved and not kept and not (is_open(r) and follows(r, mover, same)):
        if r:
            _push_history(meta, r, now, "handed on")
        meta[KEY] = new_record(label(mover), ident(mover), frm, now, no_clock=True)
        out = "recorded"
    return out


# ---------------------------------------------------------------------------------------------------------------- delivery bookkeeping
def _matches(r: dict[str, Any], who: str, same: Callable[[Any, Any], bool]) -> bool:
    return bool(clean(who)) and (same(r.get("to"), who) or same(r.get("to_id"), who))


def delivered(item: dict[str, Any], who: str, now: float, same: Callable[[Any, Any], bool] = default_same) -> bool:
    """A push to `who` about this item came back delivered: the open hand-off to it is delivered now (only the first time counts). → True when it changed."""
    r = record_of(item)
    if not r or r.get("delivered_at") or r.get("taken_at") or not _matches(r, who, same):
        return False
    r["delivered_at"] = now
    r.pop("queued", None)
    r.pop("queued_at", None)
    return True


def queued(item: dict[str, Any], who: str, outcome: str, now: float, same: Callable[[Any, Any], bool] = default_same) -> bool:
    """A push that waits (the line is in the inbox for its machine, the pane is not reachable now, a reboot's pause): neither delivered nor failed. The clock starts when the line is
    read (the puller's ack, `delivered`), else `[model] handoff_inbox_grace_minutes` after it was queued (`queued_at`)."""
    r = record_of(item)
    if not r or r.get("delivered_at") or not _matches(r, who, same) or r.get("queued") == clean(outcome)[:60]:
        return False
    r["queued"] = clean(outcome)[:60]
    r.setdefault("queued_at", now)
    return True


def failed(item: dict[str, Any], who: str, why: str, now: float, same: Callable[[Any, Any], bool] = default_same) -> str:
    """A push to `who` failed. → "retry" the first time (the caller sends it once more), "fallback" the second (the item goes down section 5, the sender told on the item), "" when
    the hand-off is no longer this one's."""
    r = record_of(item)
    if not r or r.get("delivered_at") or r.get("taken_at") or r.get("recovery_at") or not _matches(r, who, same):
        return ""
    r["attempts"] = int(r.get("attempts") or 0) + 1
    _add_event(r, now, f"a push to {r.get('to')} failed ({clean(why)[:120] or 'no reason'})" + ("; sent once more" if r["attempts"] == 1 else ""))
    return "retry" if r["attempts"] == 1 else "fallback"


# ---------------------------------------------------------------------------------------------------------------- the pass
@dataclass
class Env:
    """What a pass reads that is not in the items. Every callable may be slow and is called once per name (the pass memoises)."""
    now: float
    derive: Callable[[dict[str, Any]], "_model.Model"]
    same: Callable[[Any, Any], bool] = default_same
    minutes: float = MINUTES
    idle_grace: float = IDLE_GRACE
    gone_days: float = GONE_DAYS
    cold_call: bool = True
    inbox_grace: float = 10.0                                                # minutes after a line was queued (the inbox, a paused or unreachable pane) that it counts as read, when no ack is seen
    pane: Callable[[str], str] = lambda who: ""                              # "" when the session may have a live pane, else why not (the message tool's dead-pane rule)
    status: Callable[[str], tuple[str, float]] = lambda who: ("", 0.0)       # (busy | idle | shell | "", when the status last changed, epoch s) from the CLI's registry
    started: Callable[[str], float] = lambda who: 0.0                        # when the session's live process started (epoch s; 0.0 when unknown) from the CLI's registry: a start after the delivery is a relaunch
    background: Callable[[str], list[str]] = lambda project: []              # the project's builder alone (a list of one, or none)
    exempt: Callable[[dict[str, Any], str], bool] = lambda item, who: False  # a front agent: never clocked
    anchored: Callable[[str, dict[str, Any]], bool] = lambda gid, item: False  # an anchor scoped to the item and added at or after the hand-off: a build in flight, counted as taken (the server reads the anchors once per pass)
    remind: Callable[[dict[str, Any], str], str] = lambda item, who: ""      # (item, mover) -> the session id to remind when the mover is a live background agent, else "" (fail closed: nothing is pushed to anything else)
    is_front: Callable[[str, str], bool] = lambda who, project: False       # (session, project) -> a front agent of that project: an automatic return never goes to one
    label: Callable[[str], str] = str
    cover_all: bool = False                                                  # [model] switchover: an item with no hand-off record is covered too (a gone mover is looked for on every open alive item)
    ladder: bool = False                                                     # [ladder] enabled: a due hand-off enters the one ladder (ladder.py) instead of walking section 5 here; no reminder, no return to the sender
    laddered: Callable[[str, str, float], bool] = lambda gid, who, at: False            # (gid, mover, the hand-off record's `at`) -> the item is on the one ladder for that mover and that hand-off already: the ladder has it, this pass leaves it


@dataclass
class Step:
    """What the pass does with one item: `move` it to `to` (via redirect | return), make the `cold` call, ask the fleet's builder to `recover` it, `resend` the notice to `frm` (its pane was relaunched
    after the delivery) or `remind` `frm` (a background agent that did not take it; `to` is the session id the reminder goes to); `why` is the sentence the item and the messages carry."""
    kind: str                # move | cold | recover | resend | remind | enter (the one ladder takes the item: `via` is "gone" for a mover whose pane is gone, which starts at the cold call); a move's `via` is redirect | return | orphan (the audit's hand-over to the closest live agent, successor.py)
    gid: str
    why: str
    frm: str = ""            # the session that did not take it (or is gone)
    to: str = ""
    via: str = ""
    sender: str = ""         # who handed it to `frm` (told, one line, when it is a session)
    why_short: str = ""


def _minutes_text(m: float) -> str:
    return f"{m:g} min"


def clock_start(r: dict[str, Any], env: Env) -> float:
    """When the clock of an open hand-off started (0.0 when it has not): the delivery, else the queue time plus the inbox grace for a line that waits and whose ack was not seen."""
    d = r.get("delivered_at")
    if d:
        return float(d)
    q = r.get("queued_at")
    return float(q) + env.inbox_grace * 60 if q else 0.0


def relaunched(r: dict[str, Any], env: Env, who: str) -> str:
    """Why the notice of this open, untaken hand-off must be sent again ("" when it need not): it was delivered, the mover's pane was relaunched since (the registry shows a live
    process that started after the delivery), and the notice was not sent a second time already. The relaunch ends the turn that held the notice, so "idle with no write"
    is not the mover's answer. Once only: a second loss goes down section 5."""
    d = r.get("delivered_at")
    if not d or r.get("resent_at"):
        return ""
    s = env.started(who)
    if not s or s <= float(d):
        return ""
    return f"{env.label(who)}'s pane was relaunched after the notice"


def _due(r: dict[str, Any], env: Env, who: str) -> str:
    """Why this open, untaken hand-off is due now ("" when it is not): two failed pushes, the clock, or the recipient's turn that ended with no write."""
    start = clock_start(r, env)
    if not start:
        if int(r.get("attempts") or 0) >= 2 and not r.get("queued_at"):
            return f"a push to {env.label(who)} failed twice"
        return ""
    if env.now < start:
        return ""
    if env.now - start >= env.minutes * 60:
        return f"{env.label(who)} did not take it in {_minutes_text(env.minutes)}" + (" after a reminder" if r.get("reminded_at") else "")
    if r.get("reminded_at"):
        return ""                      # after the reminder the clock alone counts: a pane that answers the reminder with a turn that writes nothing has not taken it either, but it gets the whole time
    st, at = env.status(who)
    if st in ("idle", "shell") and at and at > start and env.now - at >= env.idle_grace:      # `shell` is a pane whose turn is over with a background Bash task running
        return f"{env.label(who)}'s turn ended with no write to it"
    return ""


def next_step(item: dict[str, Any], r: dict[str, Any] | None, old: str, why: str, env: Env, *, gid: str = "", allow_return: bool = True, cold_ok: bool = True) -> Step:
    """Section 5, in order, for an item whose mover `old` cannot or did not take it: the project's builder when not yet tried and with a pane; the cold call, once; the sender
    (`allow_return`, and not the owner, a script or the server); else a `recover` step. `r` is the open record (None when the item has none)."""
    meta = item.get("metadata") or {}
    allow_return = allow_return and not (r or {}).get("stall") and not env.ladder      # the stall pass moves an item on from a mover with no turn; it never sends it back to a sender, and neither does the one ladder
    tried = [clean(x) for x in [*((r or {}).get("tried") or []), old] if clean(x)]
    is_tried = lambda n: any(env.same(n, t) for t in tried)
    sender = clean((r or {}).get("from"))
    origin = clean((r or {}).get("origin") or sender)
    if int((r or {}).get("steps") or 0) < MAX_STEPS:
        for name in env.background(clean(meta.get("project"))):
            if is_session_name(name) and not is_tried(name) and not env.pane(name):
                return Step("move", gid, why, old, name, "redirect", sender if is_session_name(sender) else "")
        cold = (r or {}).get("cold") if isinstance((r or {}).get("cold"), dict) else None
        if env.cold_call and cold_ok and not cold:
            return Step("cold", gid, why, old, sender=sender if is_session_name(sender) else "")
        if allow_return and is_session_name(origin) and not is_tried(origin) and not env.is_front(origin, clean(meta.get("project"))) and not env.pane(origin):
            return Step("move", gid, why, old, origin, "return", origin)
    reasons = [why]
    if not env.background(clean(meta.get("project"))):
        reasons.append("the project lists no builder")
    if allow_return and is_session_name(origin) and not is_tried(origin) and not env.is_front(origin, clean(meta.get("project"))) and env.pane(origin):
        reasons.append(f"its sender {env.label(origin)} cannot take it back ({env.pane(origin)})")
    return Step("recover", gid, "; ".join(reasons), old, sender=sender if is_session_name(sender) else "")


def _enter(gid: str, who: str, why: str, env: Env, gone: bool = True) -> Step:
    """The step that brings an item to the one ladder (`env.ladder`): a due hand-off asks the mover again first; a mover whose pane is gone, or whose pushes failed, has nothing to ask and starts at the cold call."""
    return Step("enter", gid, why, who, via="gone" if gone else "")


def plan(items: dict[str, dict[str, Any]], env: Env) -> list[Step]:
    """What the pass does now, over the open items (`items` {gid: item}). Pure: nothing is changed. Only an item with a hand-off record made by this machinery is looked at (an item
    from before the deploy is the migration's, step 4: see `gone_unrecorded`; with `env.cover_all`, the [model] switchover, an item with no record is looked at for its gone mover too), alive, with a session as its mover and that mover the record's:
      - the mover's session is gone (the dead-pane rule), on an item written within `gone_days`: down section 5 without the sender; or
      - the hand-off was delivered (or queued, plus the inbox grace) and not taken in `minutes`, or the mover's turn ended with no write, or two pushes failed: down section 5, the
        sender last.
    Not looked at: the owner as mover (never times out), a hand-off already taken, one with a cold call running, one whose recovery was already asked; a front agent's item is exempt from the
    clock and the turn end, not from the gone mover.
    With `env.ladder` ([ladder] enabled) none of those walks section 5 here: each one is an `enter` step, which brings the item to the one ladder (ladder.py), and an item already on it is left alone."""
    out: list[Step] = []
    memo_pane: dict[str, str] = {}
    pane = lambda who: memo_pane.setdefault(who, env.pane(who))
    env2 = Env(**{**env.__dict__, "pane": pane})
    for gid, item in items.items():
        if item.get("status") != "open":
            continue
        who = mover_of(item, env.derive)
        if not who or _model.is_owner(who):
            continue
        r = record_of(item)
        if not (r and (env.same(r.get("to"), who) or env.same(r.get("to_id"), who))):
            if env.cover_all and is_session_name(who) and not (r and r.get("recovery_at")):      # no record of this mover: only its gone pane is looked for (no clock runs without a delivery)
                why_gone = pane(who)
                updated = float(item.get("updated") or 0)
                if why_gone and not (env.gone_days and updated and env.now - updated > env.gone_days * 86400) and not (env.ladder and env.laddered(gid, who, 0.0)):
                    out.append(_enter(gid, who, f"{env.label(who)} is gone ({why_gone})", env2) if env.ladder else next_step(item, None, who, f"{env.label(who)} is gone ({why_gone})", env2, gid=gid, allow_return=False))
            continue
        if r.get("recovery_at"):
            continue
        if isinstance(r.get("cold"), dict) and r["cold"].get("state") == "running" and env.now - float(r["cold"].get("at") or 0) < COLD_STALE:
            continue
        if env.ladder and env.laddered(gid, who, float(r.get("at") or 0)):
            continue                   # the one ladder has it (ladder.py): it takes the rungs from here, whatever this pass would add
        why_gone = pane(who)
        if why_gone:
            updated = float(item.get("updated") or 0)
            if env.gone_days and updated and env.now - updated > env.gone_days * 86400:
                continue
            out.append(_enter(gid, who, f"{env.label(who)} is gone ({why_gone})", env2) if env.ladder else next_step(item, r, who, f"{env.label(who)} is gone ({why_gone})", env2, gid=gid, allow_return=False))
            continue
        if r.get("taken_at") or r.get("no_clock") or env.exempt(item, who):
            continue
        gone = relaunched(r, env, who)
        due = "" if gone else _due(r, env, who)
        if not (gone or due) or env.anchored(gid, item):      # an anchor scoped to the item and added since the hand-off is a build started: taken (looked at only for an item that would act)
            continue
        start = clock_start(r, env)
        if env.ladder and not gone:
            out.append(_enter(gid, who, due, env2, gone=int(r.get("attempts") or 0) >= 2 and not r.get("delivered_at")))      # the one ladder: the mover is asked again first (the ask), then the pane is looked at after the look time, the cold call, the builder; two failed pushes mean the ask cannot reach it, so it starts at the cold call
            continue
        if due and not gone and not r.get("reminded_at") and start and env.now - start < env.minutes * 60 and env.remind(item, who):
            continue                   # due only by the turn-end rule: a background agent that will be reminded waits for the clock, so the reminder's "in N minutes" is true
        if gone:
            out.append(Step("resend", gid, gone, who, who))
            continue
        if not r.get("reminded_at") and start:
            sid = env.remind(item, who)
            if sid:
                out.append(Step("remind", gid, due, who, sid))
                continue
        out.append(next_step(item, r, who, due, env2, gid=gid))
    return out


def gone_unrecorded(items: dict[str, dict[str, Any]], env: Env) -> list[str]:
    """The open alive items whose session mover has no pane and that carry no hand-off record of that mover: items from before the machinery. They are only counted (the brief's
    "mover gone: n"); moving them is the migration's (step 4)."""
    out: list[str] = []
    memo: dict[str, str] = {}
    for gid, item in items.items():
        if item.get("status") != "open":
            continue
        who = mover_of(item, env.derive)
        if not who or _model.is_owner(who) or not is_session_name(who):
            continue
        r = record_of(item)
        if r and (env.same(r.get("to"), who) or env.same(r.get("to_id"), who)):
            continue
        if memo.setdefault(who, env.pane(who)):
            out.append(gid)
    return out


# ---------------------------------------------------------------------------------------------------------------- the successor record
def successor(item: dict[str, Any], step: Step, to_id: str, now: float, label: Callable[[str], str] = str) -> dict[str, Any]:
    """Execute a `move` on the item in place: the old record (or none) goes to the history, a new record names `to`, from the server, carrying the way walked so far, and `needs`/
    `mover` are the caller's to set. → the new record."""
    meta = item.setdefault("metadata", {})
    old = record_of(item) or {}
    ended = f"{step.why}" + (f"; went to {label(step.to)}" if step.to else "")
    if old:
        _push_history(meta, old, now, ended)
    tried = [*(old.get("tried") or []), step.frm] if step.frm else list(old.get("tried") or [])
    r = new_record(label(step.to), to_id, SERVER, now, tried=[t for t in tried if clean(t)], origin=old.get("origin") or old.get("from") or step.sender, cold=old.get("cold"),
                   steps=int(old.get("steps") or 0) + 1, via=step.via, reason=step.why, redirected_from=step.frm, stall=old.get("stall"))
    _add_event(r, now, f"{step.why}: " + ("returned to its sender" if step.via == "return" else "handed to the closest live agent" if step.via == "orphan" else "handed to the project's builder"))
    meta[KEY] = r
    return r


def resend(item: dict[str, Any], step: Step, now: float, tz: dt.tzinfo | None = None, started: float = 0.0) -> dict[str, Any] | None:
    """Execute a `resend` on the item in place: the record says the notice is sent again (once), the delivery is forgotten so the clock restarts from the re-send's own delivery, and the
    failed-push count starts over. The record is marked queued now (`queued` = "resent", `queued_at`), so when the push result never comes back (a restart between this save and the
    push's report) `clock_start` falls back to now plus the inbox grace and the hand-off still times out. The caller sends the notice. → the record, or None when the item has no open record."""
    r = record_of(item)
    if r is None:
        return None
    old = r.get("delivered_at")
    r["resent_at"] = now
    if old:
        r["resent_after"] = old
    r["delivered_at"] = None
    r["queued"] = "resent"
    r["queued_at"] = now
    r["attempts"] = 0
    when = f" at {_hhmm(started, now, tz)}" if started else ""
    _add_event(r, now, f"{step.why}{when}: the notice was sent again, and the clock restarts from it")
    return r


def remind(item: dict[str, Any], step: Step, now: float) -> dict[str, Any] | None:
    """Execute a `remind` on the item in place: the record says its mover was reminded (once), the delivery is forgotten so the clock restarts from the reminder's own delivery, and the
    failed-push count starts over. As in `resend`, the record is marked queued now, so when the push result never comes back the hand-off still times out (now plus the inbox grace). The
    caller sends the reminder. → the record, or None when the item has no open record or its mover was reminded already."""
    r = record_of(item)
    if r is None or r.get("reminded_at"):
        return None
    r["reminded_at"] = now
    r["delivered_at"] = None
    r["queued"] = "reminded"
    r["queued_at"] = now
    r["attempts"] = 0
    _add_event(r, now, f"{step.why}: its mover was reminded, and the clock restarts from the reminder")
    return r


def _record_for(item: dict[str, Any], who: str, now: float, same: Callable[[Any, Any], bool], label: Callable[[str], str]) -> dict[str, Any]:
    """The open record of the hand-off to `who`, or a new one (an item with no record, or one whose record names another mover: a gone mover that never had a hand-off)."""
    meta = item.setdefault("metadata", {})
    r = record_of(item)
    if r is not None and (same(r.get("to"), who) or same(r.get("to_id"), who)):
        return r
    if r is not None:
        _push_history(meta, r, now, "replaced")
    r = new_record(label(who), "", SERVER, now)
    meta[KEY] = r
    return r


def mark_recovery(item: dict[str, Any], step: Step, now: float, same: Callable[[Any, Any], bool] = default_same, label: Callable[[str], str] = str) -> dict[str, Any] | None:
    """Execute a `recover`: the record (made when the item had none, for a gone mover) says the fleet's builder was asked, with the reason. Once per record: a record that carries the request
    already is left as it is and None comes back, so the caller sends nothing (the episode is the record's life; the mover's write or the item's hand-on ends it). → the record, or None."""
    r = _record_for(item, step.frm, now, same, label)
    if r.get("recovery_at"):
        return None
    r["recovery_at"] = now
    r["recovery_reason"] = clean(step.why)[:300]
    _add_event(r, now, f"nobody could take it, the fleet's builder was asked: {step.why}")
    return r


def mark_cold(item: dict[str, Any], step: Step, now: float, same: Callable[[Any, Any], bool] = default_same, label: Callable[[str], str] = str) -> dict[str, Any]:
    """Record that the cold call is running for this item (and make a record for an item with none: a gone mover)."""
    r = _record_for(item, step.frm, now, same, label)
    r.setdefault("reason", step.why)
    r["cold"] = {"at": now, "state": "running"}
    _add_event(r, now, f"{step.why}: the cold call was asked")
    return r


def end_cold(item: dict[str, Any], state: str, now: float, text: str, cold_at: float | None = None) -> None:
    """The cold call came back (state done) or could not (failed): the record says so, and the pass goes on down section 5 from there. With `cold_at` (the call's own stamp) only the
    record that call was asked about is written."""
    r = cold_target(item, cold_at)
    if r is not None:
        r["cold"] = {**(r.get("cold") if isinstance(r.get("cold"), dict) else {}), "state": state, "ended_at": now}
        _add_event(r, now, text)


def _is_call(r: dict[str, Any] | None, cold_at: float | None) -> bool:
    """Is `r` the record the cold call stamped `cold_at` was asked about (always, when no stamp is given)?"""
    return cold_at is None or (bool(r) and isinstance(r.get("cold"), dict) and r["cold"].get("at") == cold_at)


def cold_target(item: dict[str, Any], cold_at: float | None = None) -> dict[str, Any] | None:
    """The record a cold call's outcome is written on: the item's own, or, when the call's own answer closed the item (the close moved the record into the history, `follow`), the history
    entry of the record that held the call. With `cold_at` (the call's own stamp, as `_handoff_fallback` takes it) a record that is not the one the call was asked about is left alone."""
    r = record_of(item)
    if r is not None or item.get("status") == "open":
        return r if _is_call(r, cold_at) else None
    hist = (item.get("metadata") or {}).get("handoff_history")
    last = hist[-1] if isinstance(hist, list) and hist and isinstance(hist[-1], dict) else None
    ok = last is not None and isinstance(last.get("cold"), dict) and last.get("cold", {}).get("state") != "done" and not last.get("taken_at")
    return last if ok and _is_call(last, cold_at) else None


# ---------------------------------------------------------------------------------------------------------------- messages, batched
def batch(moves: list[tuple[str, str, str]]) -> dict[str, list[str]]:
    """Group (recipient, gid, line) by recipient: one message per recipient listing its items, however many fired in a pass. → {recipient: [lines]} in first-seen order."""
    out: dict[str, list[str]] = {}
    for who, _gid, line in moves:
        out.setdefault(who, []).append(line)
    return out


def message(lines: list[str], head_one: str, head_many: str, tail: str = "") -> str:
    """One message: head and the line when there is one item, a heading and a list when there are several; `tail` ends it."""
    if len(lines) == 1:
        return f"{head_one} {lines[0]}{tail}"
    return head_many.format(n=len(lines)) + "\n" + "\n".join("- " + ln for ln in lines) + tail


# ---------------------------------------------------------------------------------------------------------------- display
def _hhmm(ts: float, now: float, tz: dt.tzinfo | None) -> str:
    d = dt.datetime.fromtimestamp(ts, tz)
    n = dt.datetime.fromtimestamp(now, tz)
    if d.date() == n.date():
        return d.strftime("%H:%M")
    day = d.day
    suf = "th" if 10 <= day % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{d.strftime('%a %b')} {day}{suf} {d.strftime('%H:%M')}"


def pending(item: dict[str, Any]) -> bool:
    """An open hand-off to a session (or the owner) that nobody has taken yet and that the model shows: not one whose recovery was asked."""
    r = record_of(item)
    return bool(item.get("status") == "open" and r and not r.get("taken_at") and not r.get("recovery_at"))


def awaiting_session(item: dict[str, Any], mover: Any = None, same: Callable[[Any, Any], bool] | None = None) -> bool:
    """A hand-off to a session that has not taken it yet: `pending`, but never one to the owner (his record has no clock, `no_clock`: he is no session that "takes" an item, and his
    list shows the age instead). With `mover` the record must be addressed to that mover (compared with `same`, default: names equal ignoring case). The home page's Agents row and the
    item page's "handed over, not yet taken" both ask this, so the two cannot drift apart."""
    r = record_of(item)
    if not r or not pending(item) or r.get("no_clock") or _model.is_owner(r.get("to")):
        return False
    if mover is None:
        return True
    return (same or (lambda a, b: _model.clean(a).lower() == _model.clean(b).lower()))(r.get("to"), mover)


def words(item: dict[str, Any], now: float, tz: dt.tzinfo | None = None, label: Callable[[str], str] = str, minutes: float = MINUTES) -> list[str]:
    """The hand-off lines of `get`: what happened to the item's last hand-off, in the instance's timezone.
      handed to X, not yet taken (since 14:02)
      handed to X, taken 14:05
      returned to Y: X did not take it in 10 min
      handed to Z (X did not take it in 10 min), not yet taken (since 14:12)
      nobody could take it, the fleet's builder was asked to recover it (X is gone; the project lists no builder)
    then the server's own lines about it (a failed push, a move), newest last."""
    r = record_of(item)
    if not r or item.get("status") != "open":
        return []
    to = label(r.get("to") or "") if not _model.is_owner(r.get("to")) else _model.owner_display()
    since = _hhmm(float(r.get("at") or now), now, tz)
    reason = clean(r.get("reason"))
    out: list[str] = []
    if r.get("recovery_at"):
        out.append(f"handoff: nobody could take it, the fleet's builder was asked to recover it ({clean(r.get('recovery_reason')) or 'no reason recorded'})")
    elif r.get("via") == "return":
        tail = f"taken {_hhmm(float(r['taken_at']), now, tz)}" if r.get("taken_at") else f"not yet taken (since {since})"
        out.append(f"handoff: returned to {to}: {reason or 'it was not taken'}, {tail}")
    else:
        head = f"handed to {to}" + (f" ({reason})" if r.get("via") == "redirect" and reason else "")
        tail = f"taken {_hhmm(float(r['taken_at']), now, tz)}" if r.get("taken_at") else f"not yet taken (since {since})"
        out.append(f"handoff: {head}, {tail}")
    for e in (r.get("events") or [])[-3:]:
        if isinstance(e, dict) and e.get("text"):
            out.append(f"  {_hhmm(float(e.get('at') or now), now, tz)} {e['text']}")
    return out


def brief_lines(items: dict[str, dict[str, Any]], now: float, tz: dt.tzinfo | None = None, shown: Callable[[str], str] = str, label: Callable[[str], str] = str,
                exempt: Callable[[dict[str, Any], str], bool] = lambda item, who: False, limit: int = 6) -> list[str]:
    """The brief's short line: the hand-offs to a session not yet taken (not the owner's)."""
    waiting = []
    for gid, it in items.items():
        r = record_of(it)
        if not r or it.get("status") != "open":
            continue
        who = clean(r.get("to"))
        if r.get("recovery_at"):
            continue
        if not r.get("taken_at") and not _model.is_owner(who) and not exempt(it, who):
            waiting.append(f"{shown(gid)} → {label(who)} (since {_hhmm(float(r.get('at') or now), now, tz)}" + ("" if r.get("delivered_at") else ", not delivered") + ")")
    out = []
    if waiting:
        out.append("handed over, not yet taken: " + " · ".join(waiting[:limit]) + (f" · +{len(waiting) - limit} more" if len(waiting) > limit else ""))
    return out
