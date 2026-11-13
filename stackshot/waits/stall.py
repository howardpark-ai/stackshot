"""stall.py — the stall pass: when the session that moves a live item has no turn running for 10 minutes, stackshot moves the item on itself.

The pure half: no server import, no clock read, no file. server.py reads the signal and acts; this module decides.

The signal is the CLI's registry, read by service/handoff.py `handoff_status`: a live pane's `status` (busy | idle | shell) and when it last changed (`statusUpdatedAt`). "No turn running for N minutes" is
`status` idle or shell and the status changed N minutes ago or more. `shell` is what the CLI writes for a pane whose turn is over but which has a `run_in_background` Bash task still running
(`co === "idle" && tasks ? "shell" : co`): the turn is over, so it counts as idle. A background subagent keeps the pane `busy`, which is left alone. A pane the registry does not show on this box
gives ("", 0.0): nothing can be told, and the item is left alone.

One episode per item and mover. It ends (the entry starts over) when anyone writes the item (its `updated` or `state_updated` moves), its mover confirms it (the mover's own `confirmed` moves: the episode keeps it in `conf`; another session's confirm moves nothing, and after `RESTARTS` confirms in a row the ladder carries on) or its mover changes. Inside an episode each step
waits `minutes` of idle time counted from the later of the pane going idle, the item reaching its mover, and the previous step; a pane that starts a turn goes busy and, back to idle,
has a later `statusUpdatedAt`, so a turn starting restarts the count.

    step 0  -> `resend`   the notice goes to the mover once more
    step 1  -> `cold`     one `claude -p` call (the hand-off's cold call) names who takes it, or closes the item; it never asks the owner (an ask_owner, none or unusable answer is not written,
                          and the item goes on to the builder at once). An answer that names the session already moving the item keeps it there (`kept`): the mover is told once, the builder is not asked,
                          the owner is not asked, and the pass leaves the item alone for `KEEP` (spent)
    step 2  -> `builder`  the project's builder; none able, the last rung: ONE message to the fleet's builder (the project's -main agent for a front-only project: no background agent on its map) naming the item and the quiet session, asking it to take the fix through its usual path (the
                          hand-off record carries the request, so the pass sends it once per record, and a History line says so). The item stays with its mover; it does not go to the owner

The cold call is made at most once per item in `KEEP` seconds (it bounds a ping-pong between two sessions that each hand the item back).

An item is looked at only when its work is due now (`not_due`): an item the board shows as waiting (a hold with a dated wake, an `after` link to an open item, a stored wait, a wake that carries a wait_basis) or that is the owner's
or an outsider's move is left alone, whatever the mover's role, and any record the pass kept for it is dropped, so the clock starts when the item becomes due. A date alone is a wait until it (outside a hand-off), so the item reads as waiting and is left alone; only a wake kept as a hand-off's backstop leaves the item on agent and holds nothing off.

A pause of the whole pass always ends on its own (a pause once outlasted its window and nothing woke idle builders): `[stall] paused_until`
(an ISO-8601 time with an offset) holds the pass until then, and `enabled = false` holds it for at most `max_pause_hours` (4) from when the server first saw it; a paused_until further out than
that is cut to it too, and no cap is longer than `PAUSE_MAX_HOURS` (24). `pause` is the pure decision; the server keeps its record (`since`) in memory and in `<state>/stall_pause.json`, so a restart does
not reset the clock.

An agent never switches the pass off. The server honors a pause only
when `[stall] pause_item` names a board item that carries the owner's own answer approving a pause (`metadata.answers`: written only by his board login or his GitHub comment, never by a session's
`update`; the chosen option or the comment says "pause", any case) dated no earlier than `ANSWER_HOURS` (4) before the server first saw the pause (`authorize`). An unrelated answer of his on the item
does not count. A pause refused and answered only after its cap has passed starts when the answer is honored (a new clock, still at most 24 h), with one journal line saying it started late. Any other pause is refused: the pass keeps running, one journal line says why (once per config load), and doctor, the
server's start and a reload show it too (config.stall_notes).

What an agent does when the pass takes a wrong step on an item (a notice it should not have sent, a hand-off or a close it should not have made, a recovery request it should not have made):

1. Undo the step on the item, with `update`. What can be undone: a hand-off or a close (`cold`, `builder`): set `mover` and `next` back (a closed item: `status=open` with a new `next`); a recovery request
   (`recover`: a message to the fleet's builder, or a front-only project's -main agent, the item untouched): nothing on the item to undo; the line in `metadata.stall.log` stays as the record. What cannot be undone: the
   notice already sent (`resend`), the recovery message and the cold call's text; all are harmless and need nothing.
2. Fix the cause through a normal PR to stackshot (hand it to example-engineer): the step was wrong because `not_due`, `action` or the registry signal read the item wrong, and that is code.
3. If wrong steps reach the owner before the fix lands, ask the owner for a pause that ends by itself: he answers on a board item, and `pause_item` names it. An agent never sets `enabled = false` on its
   own: the server refuses it."""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable

from stackshot.core import config as _cfg
from stackshot.fleet import liveness as _lv
from stackshot.model import model as _model
from stackshot.model import states as _states
from stackshot.waits import waiting as _wt

MINUTES = 10.0          # [stall] minutes: how long a mover's pane may have no turn running before a step is taken
EVERY = 20.0            # [stall] every_seconds: how often the pass runs (the runner ticks every 60 s, so a smaller value runs at every tick)
MAX_PER_TICK = 5        # [stall] max_per_tick: how many first steps (the notice again) one tick takes; the rest follow on the next ticks (a deploy finds many long-idle panes)
KEEP = 86400.0         # the cold call is made once per item in this long
PAUSE_HOURS = 4.0       # [stall] max_pause_hours: the longest a pause (enabled = false, or a paused_until) holds the pass, counted from when the server first saw it
PAUSE_MAX_HOURS = 24.0  # no setting makes a pause longer than this: max_pause_hours and a paused_until further out are cut to it
ANSWER_HOURS = 4.0      # The owner's answer on [stall] pause_item may be this old, at most, when the server first saw the pause
STEPS = ("resend", "cold", "builder")
CARRY = ("cold_at", "tried")      # what outlives an episode
RESTARTS = 3            # the mover's confirms that start an item's episode over, at most; after them a confirm moves nothing and the ladder carries on (a mover that only confirms cannot hold the ladder off for good)


def not_due(item: dict[str, Any], now: float, after_open: Callable[[dict[str, Any]], Any] | None = None) -> str:
    """Why the item's work is not due now ("" when it is, and the pass may look at it). The board's own phase decides what waits: an item the board shows as waiting (`model.shown_waiting`: a hold with a dated wake, an
    `after` link to an item still open, a stored wait, a wake that carries a wait_basis, the states parked, blocked, outside and verifying) is left alone, and nothing else is. A wake kept as a hand-off's backstop (no until) leaves the
    item on agent, so it does not hold the pass off; a wake that has passed is due as before. Not on an agent at all are an item in the owner's move (the states your-call and your-step, a need of `decision`) and one that
    waits on an outsider (a need of `external`): those are the owner's and the outsider's lanes on the board, never an agent's work. A doing item carries no expected time, so a quiet mover is due at once."""
    if item.get("status") != "open":
        return "closed"
    m = item.get("metadata") or {}
    try:
        mod = _model.view(item, _model.derive(item, now, after_open), now, after_open)
    except Exception:  # noqa: BLE001  (an item the model cannot read is not looked at)
        return "not readable"
    if mod.state == _model.WAITING:
        return f"the board shows it waiting ({mod.wait.kind if mod.wait else 'unknown'})"
    kinds = _states.kinds_of(m)
    if "decision" in kinds or _states.of(item, after_open)[0] in _model.OWNER_STATES:
        return "waiting on the owner"
    if "external" in kinds:
        return "waiting on someone outside"
    return ""


def due_at(item: dict[str, Any], now: float | None = None) -> float:
    """When the item's work fell due: its wake once it has passed (0.0 when it has none, or it is still ahead). The pass counts a mover's idle time from then, as it counts from the item's arrival, so
    an item whose wake has just passed gets the minutes before its first step, not an instant one on the pane's age alone. With no `now` the wake is returned whenever it is set."""
    m = item.get("metadata") or {}
    wake = _wt.wake_epoch(_wt.wake_value(m)) if _wt.wake_value(m) else None      # a stored until is read as a wake is
    if wake is not None and now is not None and wake > now:
        return 0.0
    return wake or 0.0


def fresh(mover: str, ver: list[float], old: dict[str, Any] | None = None, confirmed: float = 0.0) -> dict[str, Any]:
    """A new episode for `mover` on an item at version `ver` ([updated, state_updated]) and confirmed at `confirmed`, keeping what outlives an episode."""
    rec: dict[str, Any] = {"mover": mover, "ver": list(ver), "conf": float(confirmed or 0), "step": 0, "last": 0.0}
    for k in CARRY:
        if old and old.get(k):
            rec[k] = old[k]
    return rec


def episode(rec: dict[str, Any] | None, mover: str, ver: list[float], same: Any, confirmed: float = 0.0) -> dict[str, Any]:
    """The entry for the item now: the same episode while its mover, version and confirm are the ones it was made for, else a new one (carrying `CARRY`). `confirmed` is the confirm of the item's
    mover only (the caller passes 0 for another session's confirm, which says nothing about whether the mover is working). The mover confirming the item (a later `confirmed`) ends the episode: the
    confirm says the item is still being worked, so the minutes start over; but at most `RESTARTS` times in a row (`restarts` counts them; any write to the item or a new mover starts the count over),
    after that the confirm is adopted and the ladder carries on. An entry written before the confirm was recorded adopts the one the item has."""
    if rec and same(rec.get("mover"), mover) and list(rec.get("ver") or []) == list(ver):
        if "conf" not in rec:
            rec["conf"] = float(confirmed or 0)
            return rec
        if float(rec["conf"] or 0) == float(confirmed or 0):
            return rec
        if float(confirmed or 0) < float(rec["conf"] or 0):
            return rec                        # not the mover's confirm (0), or an older one: the mover's last confirm, kept in `conf`, stands
        n = int(rec.get("restarts") or 0)
        if n >= RESTARTS:
            rec["conf"] = float(confirmed or 0)
            rec["capped"] = True              # the confirm no longer counts toward the minutes either (the server's floor)
            return rec
        new = fresh(mover, ver, rec, confirmed)
        new["restarts"] = n + 1
        return new
    return fresh(mover, ver, rec, confirmed)


def action(rec: dict[str, Any], status: str, at: float, floor: float, now: float, minutes: float) -> str:
    """What is due now for this episode: "" (nothing), "resend", "cold" or "builder". `status`/`at`: the pane's registry status and when it changed; `floor`: when the item reached its mover
    (its last state change), so an item that just arrived at a long-idle pane is not stalled on the pane's age alone. Only a pane whose turn is over counts: `idle`, or `shell` (turn over,
    a background Bash task still running: the CLI's registry writes `shell` instead of `idle` then). `busy` is a turn running (a background subagent included), "" is unknown."""
    if not _lv.is_idle(status, at):          # liveness.py's idle test, also the audit's
        return ""
    step = int(rec.get("step") or 0)
    if step >= len(STEPS):
        return ""
    start = max(float(at), float(floor or 0), float(rec.get("last") or 0))
    if now - start < minutes * 60.0:
        return ""
    name = STEPS[step]
    if name == "cold" and rec.get("cold_at") and now - float(rec["cold_at"]) < KEEP:
        return "builder"          # the cold call was made for this item lately: on to the builder
    return name


def advance(rec: dict[str, Any], did: str, now: float) -> None:
    """The step `did` has been taken: the next waits `minutes` more. The cold call is stamped for its 24-hour bound."""
    rec["step"] = STEPS.index(did) + 1 if did in STEPS else rec.get("step", 0)
    rec["last"] = now
    if did == "cold":
        rec["cold_at"] = now


def expired(rec: dict[str, Any], now: float) -> bool:
    """An entry nothing in it still matters for: every stamp it carries is older than `KEEP`."""
    stamps = [float(rec.get(k) or 0) for k in ("cold_at", "kept", "last")]
    return all(now - s >= KEEP for s in stamps)


def spent(rec: dict[str, Any] | None, now: float) -> bool:
    """The cold call kept the item with its mover lately: the pass leaves it alone for `KEEP` (any write or a confirm
    starts a new episode, which has no mark)."""
    return bool(rec and rec.get("kept") and now - float(rec["kept"]) < KEEP)


def log_of(meta: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The steps written on an item (metadata.stall.log), oldest first."""
    s = (meta or {}).get("stall")
    return [x for x in ((s or {}).get("log") or []) if isinstance(x, dict)] if isinstance(s, dict) else []


def note(meta: dict[str, Any], now: float, text: str, keep: int = 8) -> None:
    """Write a step onto the item's metadata (History shows each new entry as a line)."""
    log = log_of(meta)
    log.append({"at": now, "text": " ".join(str(text).split())[:240]})
    meta["stall"] = {"log": log[-keep:]}


def new_entries(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The log entries `after` has that `before` did not (History: one line each)."""
    seen = {(x.get("at"), x.get("text")) for x in log_of(before)}
    return [x for x in log_of(after) if (x.get("at"), x.get("text")) not in seen]


def parse_until(raw: Any, tz: Any = None) -> float | None:
    """`[stall] paused_until` as an epoch: an ISO-8601 time with an offset ("2099-03-14T21:00+00:00"). One without an offset is read in `tz` (the instance zone) when given. None when unset or unreadable."""
    if raw in (None, ""):
        return None
    try:
        t = dt.datetime.fromisoformat(str(raw).strip())
        if t.tzinfo is None:
            if tz is None:
                return None
            t = t.replace(tzinfo=tz)
        return t.timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def pause_hours(raw: Any) -> float:
    """`[stall] max_pause_hours` (default PAUSE_HOURS; a value that is not a positive number is the default; never above PAUSE_MAX_HOURS)."""
    try:
        v = float(raw)
        return min(v, PAUSE_MAX_HOURS) if v > 0 else PAUSE_HOURS
    except (TypeError, ValueError):
        return PAUSE_HOURS


def authorize(item: str, answers: list[dict[str, Any]] | None, since: float, hours: float = ANSWER_HOURS) -> str:
    """is a pause of the pass the owner's? -> "" when it is, else why not (one sentence, for the journal and doctor). `item` is `[stall] pause_item` as written; `answers` the item's
    `metadata.answers` (render.answers_of: only his board login and his GitHub comment write them), or None when no such item exists; `since` is when the server first saw the pause. His
    answer counts when it is dated no earlier than `hours` before `since` (one given after counts too: he may answer the item once the pause is asked for)."""
    shown = str(item or "").strip()
    if not shown:
        return f"[stall] pause_item names no board item with {_cfg.owner()}'s answer approving a pause (ask him on a board item, then name it there)"
    if answers is None:
        return f"[stall] pause_item {shown} is not a board item the server can read"
    floor = float(since) - hours * 3600.0

    def stamp(a: Any) -> float:
        try:
            return float(a.get("ts") or 0) if isinstance(a, dict) else 0.0
        except (TypeError, ValueError):
            return 0.0

    def approves(a: Any) -> bool:       # the answer says "pause": the chosen option (label, line) or the comment's body
        if not isinstance(a, dict):
            return False
        return "pause" in " ".join(str(a.get(k) or "") for k in ("choice", "choice_line", "text")).lower()
    if not any(stamp(a) > 0 and stamp(a) >= floor and approves(a) for a in answers):
        return (f"[stall] pause_item {shown} carries no answer of {_cfg.owner()}'s approving a pause (one that says \"pause\") from the {hours:g} hours before the pause was first seen")
    return ""


def pause(enabled: Any, raw_until: Any, tz: Any, cap_hours: float, rec: dict[str, Any] | None, now: float,
          auth: Callable[[float], str] | None = None) -> tuple[dict[str, Any] | None, float | None, str, list[str]]:
    """The pause of the whole pass, and that it ends. → (record to keep, end epoch while paused else None, why, events). `rec` is the record kept so far ({sig, since, ended}); `events` are
    "start" (or "late": started when the answer came after the pause's cap, its clock restarted then), "end" and "refuse": the first three are logged once, "refuse" comes each time the pause is refused (the caller logs it once per load). A `raw_until` that is not a time is ignored
    (config.stall_notes says so). `auth(since)` (`authorize`) -> "" or why the pause is not the owner's: then nothing is paused (end None, why = the reason), the record keeps `since` and
    is marked `refused`, and his answer may still come: the same record is judged again on the next call. None (a caller with no rule) honors every pause.

    Paused: `enabled` false, or `raw_until` a time still ahead. It holds until the earlier of that time and `cap_hours` after `since`, the moment the server first saw this pause (a changed setting
    is a new pause, seen then; the same setting after a restart keeps its `since`). After that the pass runs again whatever the file still says, and the record stays (`ended`) so the same
    setting does not start a pause again; it goes when the setting no longer asks for one."""
    until = parse_until(raw_until, tz)
    off = not bool(enabled)
    sig = f"{int(not off)}|{'' if raw_until in (None, '') else raw_until}"
    ev: list[str] = []
    if not (off or (until is not None and until > now)):
        return None, None, "", (["end"] if rec and not rec.get("ended") and not rec.get("refused") else [])
    new = not rec or rec.get("sig") != sig
    if new:
        rec = {"sig": sig, "since": now}
    assert rec is not None
    since = float(rec.get("since") or now)
    reason = auth(since) if auth else ""
    if reason:
        return (rec if rec.get("refused") else {**rec, "refused": True}), None, reason, ["refuse"]
    cap_hours = min(cap_hours, PAUSE_MAX_HOURS)
    late = False
    if rec.get("refused"):                  # it was refused and is the owner's now: it starts now, its clock from when it was first seen
        rec = {k: v for k, v in rec.items() if k != "refused"}
        new = True
        if now >= since + cap_hours * 3600.0:       # his answer came after the pause's whole cap: the clock restarts now (the pause runs from the moment it is honored, still capped)
            rec = {**rec, "since": now}
            since, late = now, True
    capped = since + cap_hours * 3600.0
    if until is not None and until <= capped:
        end, why = until, "paused_until"
    else:
        end, why = capped, (f"paused_until, capped at {cap_hours:g} h" if until is not None else f"enabled=false, capped at {cap_hours:g} h")
    if now >= end:
        if not rec.get("ended"):
            rec = {**rec, "ended": True}
            if not new:
                ev.append("end")
        return rec, None, why, ev
    if new:
        ev.append("late" if late else "start")
    return rec, end, why, ev
