"""ladder.py — the one ladder an item climbs when the mover that holds it goes quiet.

The pure half, like stall.py (which it builds on): no server import, no clock read, no file. server.py reads the signals and acts; this module decides.

Two things used to climb their own ladders on their own records. A hand-off nobody took went down the hand-off ladder (a reminder for a background agent, the project's builder, the cold call, the
sender, then the fleet's builder asked to recover it); a mover whose pane had no turn running went down the stall ladder (the notice again, the cold call, the builder, then the fleet's builder asked).
Two orders, two records (`metadata.handoff` and the stall pass's entry), and an item could be on both. With `[ladder] enabled = true` there is one record per item (the stall pass's entry,
`<state>/stall.json`, which carries who brought the item to the ladder in `via`) and one order:

    rung 0  ask      the mover is sent the notice again (a hand-off's own notice for an untaken hand-off, the stall notice for a silent pane; a front agent only gets the History line)
    rung 1  look     `LOOK` (30) minutes after the ask, and only then, the pane is looked at: a pane with no turn running is sent the notice again; a pane with a turn running is left alone. A background
                     agent's pane is never looked at (it is nearly always busy or showing a background shell): it is sent the notice again, unless a step status of the item in progress, changed within 90
                     minutes, shows it at work on it, and a live one is asked and then handed up, not replaced (the cold call and the builder are for a mover whose pane is not live)
    main     `minutes` after the look, for a live background mover that is still silent: a notice to the project's -main agent (one per -main agent per pass, listing every item due for it), which decides whether the item needs a nudge or a different mover; the
             same notice again every `MAIN_EVERY` (4 hours) while the silence lasts. It is no step of its own (the entry stays on its rung, so the cold call and the builder stay reachable if the pane stops
             being live): the entry's `main_at` is its clock. The same notice also takes an item that is not MOVING, whatever its mover answers: with no step marked done or dropped, no state change and no merge
             for `[ladder] main_hours` (4), an alive item goes up in the same message (service/ladder.py's `ladder_stuck`, clock in model/progress.py), once per stretch of no progress
    rung 2  cold     `minutes` (10) later, still no turn and no write: one `claude -p` call names who takes it, or closes the item (it never asks the owner)
    rung 3  builder  `minutes` later (at once when the cold call named no taker): the project's builder; when none can take it, ONE message asks the fleet's builder to recover the session (a front-only project, one whose `agents:` map lists no background agent, asks its -main agent instead: `server._recovery_target`). The
                     item stays with its mover and is not put to the owner

What brings an item to the ladder is still two audits, and they stay apart: the hand-off audit (an untaken hand-off past `handoff_minutes`, a turn that ended with no write, a gone pane, two failed
pushes) enters it with `via` = "handoff", and the stall pass (a pane with no turn running for `[stall] minutes`) with `via` = "stall". An untaken hand-off to a session is the hand-off audit's
alone: the stall pass does not start it, so one item never climbs two ladders at once; and the hand-off audit leaves an item already on the ladder. The sender rung is gone: an untaken hand-off no
longer goes back to the session that handed it over.

The dates pass is a third way in, and the pane stops being one: the dates pass (a wake passed with no write since) sends its
message to the mover, and that message is the ask: `enter_quiet` writes the item's entry with `via` = "silence", on the look, its clock started when the message went. The entry is for that silence alone (`act`, the item's activity clock then):
it ends with activity on the item or a new mover (`quiet_over`), and neither a write that is no activity nor the mover's bare confirm restarts it. The stall pass does not start a ladder from a pane with no turn running; it takes the rungs of
the entries the hand-off audit and the dates pass made.

The episode, its restarts and its bounds are stall.py's (`episode`, `expired`, `spent`, `not_due`, `due_at`): any write to the item, a new mover, or the mover's own confirm (at most
`stall.RESTARTS` times) starts a new episode. On this ladder (`episode` here) an item the hand-off audit brought stays on it through such a restart, for the same mover and a hand-off still
untaken: the ask is not sent twice, and the look comes `LOOK` minutes after the last rung. A new mover, or the mover starting work on it (the hand-off is taken), ends it. The cold call is made at most
once per item in `stall.KEEP` seconds. The rungs after the ask are taken by the stall pass, so they wait while it is paused. `unwind` reads an entry back in stall.py's shorter table when the flag
is turned off in the middle of a ladder."""
from __future__ import annotations

from typing import Any

from stackshot.fleet import liveness as _lv
from stackshot.waits import stall as _stall

RUNGS = ("ask", "look", "cold", "builder")
LOOK = 30.0                  # [ladder] look_minutes: how long after the ask the pane is looked at
VIAS = ("stall", "handoff", "silence")  # who brought the item to the ladder
MAIN = "main"                # the notice to the project's -main agent for a live background mover that stays silent after the look: not one of RUNGS (the entry's step does not move)
MAIN_EVERY = 4 * 3600.0      # how often that notice is sent again while the item stays silent: a given silence reaches -main once per interval, never once per pass; also how long an item may not move (model/progress.py)
                             # before it is handed up the same way (`[ladder] main_hours`, 4: the server passes the configured value as `main_every`)


def via_of(rec: dict[str, Any] | None) -> str:
    v = (rec or {}).get("via")
    return v if v in ("handoff", "silence") else "stall"


def quiet(rec: dict[str, Any] | None) -> bool:
    """Did the dates pass bring the item? Its entry starts after the ask, which the audit's own message was."""
    return via_of(rec) == "silence"


def enter_quiet(old: dict[str, Any] | None, mover: str, ver: list[float], confirmed: float, clock: float, now: float) -> dict[str, Any]:
    """The entry for an item the dates pass brings to the ladder, once its message to the mover has gone (that message is the ask): a new episode (keeping what outlives
    one), marked `via` = "silence", on the look with its clock started at `now`. `clock` is the item's activity clock then (`silence.clock`): the entry is for that silence alone and ends when the item
    has activity (`quiet_over`), not when someone writes the item or the mover confirms it (neither is activity, so neither restarts a silence)."""
    rec = _stall.fresh(mover, ver, old, confirmed)
    rec.update(via="silence", ladder=True, act=float(clock or 0), step=RUNGS.index("look"), last=float(now))
    return rec


def quiet_over(rec: dict[str, Any], mover: str, same: Any, clock: float) -> bool:
    """Is the silence the entry was made for over: a new mover, or activity on the item since (its activity clock is later than the entry's)?"""
    return not same(rec.get("mover"), mover) or float(clock or 0) > float(rec.get("act") or 0)


def enter(old: dict[str, Any] | None, mover: str, ver: list[float], confirmed: float, *, gone: bool = False, at: float = 0.0) -> dict[str, Any]:
    """The entry for an item the hand-off audit brings to the ladder: a new episode (keeping what outlives one), marked `via` = "handoff". It is due at once (`action`); a mover whose pane
    is gone (`gone`) has no notice to read and starts at the cold call. An entry of the same mover at the same version keeps its count of the mover's confirms (`restarts`, `capped`): bringing the
    item to the ladder again does not give the mover its restarts back. `at` is the hand-off record's `at`: the entry is for that hand-off alone (`on_ladder`, `episode`)."""
    rec = _stall.fresh(mover, ver, old, confirmed)
    rec["via"] = "handoff"
    rec["ho_at"] = float(at or 0)
    rec["ladder"] = True
    if old and old.get("mover") == mover and list(old.get("ver") or []) == list(ver):
        for k in ("restarts", "capped"):
            if old.get(k):
                rec[k] = old[k]
    if gone:
        rec["gone"] = True
        rec["step"] = RUNGS.index("cold")
    return rec


def episode(rec: dict[str, Any] | None, mover: str, ver: list[float], same: Any, confirmed: float = 0.0, at: float | None = None) -> dict[str, Any]:
    """`stall.episode` for an entry the hand-off audit made: a write to the item or the mover's own confirm starts a new episode, but it stays on the ladder for the same mover (`via`, and `gone`
    for a mover whose pane is gone) and the ask already sent is not sent again: the new episode begins at the look (or at the cold call for a gone mover), counted from the last rung taken. Without
    this a write by anyone would put the item back at the ask at once, and the hand-off audit, no longer finding it on the ladder, would bring it again. A new mover is a new item for the ladder,
    and so is a hand-off the mover has taken (`at` is None: it started work on the item): that ends the ladder, as before. `at` is the `at` of the item's hand-off record while it is untaken for this mover;
    the entry is kept only for the hand-off it was made for (its `ho_at`), so a later hand-off of the item to the same mover starts a ladder of its own."""
    new = _stall.episode(rec, mover, ver, same, confirmed)
    if new is rec or not rec or at is None or float(rec.get("ho_at") or 0) != float(at or 0) or via_of(rec) != "handoff" or not same(rec.get("mover"), mover):
        return new
    new["via"] = "handoff"
    new["ho_at"] = float(at or 0)
    new["ladder"] = True
    step = int(rec.get("step") or 0)
    if rec.get("gone"):
        new["gone"] = True
        new["step"] = RUNGS.index("cold")
    elif step >= 1:
        new["step"] = 1
    if step >= 1:
        new["last"] = float(rec.get("last") or 0)
    return new


def unwind(rec: dict[str, Any] | None) -> dict[str, Any] | None:
    """An entry the one ladder wrote, read by the two old ladders (the flag turned off in the middle of a ladder): the same entry in the stall ladder's table, `stall.STEPS` (resend, cold,
    builder), which is one step shorter. The look maps to the cold call, the cold call to the builder and the builder to none: an item the ladder had on its last rung (the builder) is still
    reachable, and nothing is repeated that the ladder did. Returns the entry as it was when it carries neither `ladder` nor `via`."""
    if not rec or not (rec.get("ladder") or "via" in rec):
        return rec
    out = {k: v for k, v in rec.items() if k not in ("via", "gone", "ladder", "act")}
    step = int(out.get("step") or 0)
    out["step"] = {0: 0, 1: 1, 2: 1}.get(step, len(_stall.STEPS) - 1) if step < len(RUNGS) else len(_stall.STEPS)
    return out


def action(rec: dict[str, Any], status: str, at: float, floor: float, now: float, minutes: float, look: float = LOOK, background: bool = False, live: bool = False,
           main_every: float = MAIN_EVERY) -> str:
    """What is due now for this episode: "" (nothing), "ask", "look", "cold", "builder" or "main" (the notice to the project's -main agent: `MAIN`). `status`/`at`: the pane's registry status and when it changed; `floor`: when the item reached its mover
    (its last state change, the mover's own last confirm). Only a pane whose turn is over counts (`liveness.is_idle`: idle, or shell with a background task running); a mover whose pane is gone
    (`rec["gone"]`) has none to wait for. The ask of an item the hand-off audit entered is due the moment it enters. Each later rung waits from the later of the pane going idle, the floor and the
    previous rung: `look` (30 minutes) after the ask (the pane only has to be idle then), the others `minutes`.

    `background`: the mover is a background agent. The rungs after the ask (the look, the cold call, the builder) then wait on the clock alone, never on its pane: a background agent's pane is nearly always
    busy or showing a background shell, and that says nothing about this item (the server holds the ladder for an item whose own step status shows work in progress, `silence.subagent_running`). `live`: its pane
    is live (running now): the ladder then goes no further than the look on the mover, since the cold call and the builder replace a mover that cannot answer, and one that is live can; a live mover
    that stays silent after the look is handed up instead (`main`, see `_main_due`). The same hand-up also takes an item that is not moving, silent or not: see `model/progress.py` and the server's
    `ladder_stuck` (service/ladder.py), which is that path's second way in and shares its message. A pane that is not live goes on to both, and so does an entry marked `gone` whatever the heartbeat shows. The ask
    of a ladder a pane with no turn running brought still waits for that pane (`background` changes nothing at step 0)."""
    step = int(rec.get("step") or 0)
    if step >= len(RUNGS):
        return ""
    gone = bool(rec.get("gone"))
    name = RUNGS[step]
    if step == 0 and via_of(rec) == "handoff":
        return name               # the hand-off audit decided it is due (its clock, a turn that ended with no write): the mover is asked whatever its pane shows
    clock_only = background and step >= 1      # a background mover's later rungs are timed by the ladder's own clock
    if clock_only and live and not gone and name in ("cold", "builder"):
        return _main_due(rec, floor, now, minutes, main_every)      # a live background agent is asked, not replaced (an item the hand-off audit entered as gone, two failed pushes with no delivery, is not held by a heartbeat that still shows the pane): its silence goes to the project's -main agent instead
    if not gone and not clock_only and not _lv.is_idle(status, at):
        return ""
    start = max(0.0 if gone or clock_only or name == "look" else float(at), float(floor or 0), float(rec.get("last") or 0))      # the look is due `look` minutes after the ask, whenever the pane went idle: it only has to be idle then
    if now - start < (look if name == "look" else minutes) * 60.0:
        return ""
    if name == "cold" and rec.get("cold_at") and now - float(rec["cold_at"]) < _stall.KEEP:
        return "builder"          # the cold call was made for this item lately: on to the builder
    return name


def _main_due(rec: dict[str, Any], floor: float, now: float, minutes: float, main_every: float = MAIN_EVERY) -> str:
    """"main" when the notice to the project's -main agent is due for a live background mover that is silent after the look, else "". The first one is due `minutes` after the later of the look and the
    floor (where the cold call would have come); after it, the next is due `MAIN_EVERY` after the last (`main_at`, stamped by `advance`), or after the floor if that is later (the item reached its mover
    again), so the item reaches -main once per interval however many passes run. The interval is `main_every` (`MAIN_EVERY` unless the server passes `[ladder] main_hours`)."""
    f = float(floor or 0)
    if rec.get("main_at"):
        return MAIN if now - max(float(rec["main_at"]), f) >= main_every else ""
    return MAIN if now - max(float(rec.get("last") or 0), f) >= minutes * 60.0 else ""


def advance(rec: dict[str, Any], did: str, now: float) -> None:
    """The rung `did` has been taken: the next waits its time. The cold call is stamped for its 24-hour bound, and the notice to the -main agent (`MAIN`, not a rung: the step stays) for its repeat interval."""
    if did == MAIN:
        rec["main_at"] = now
    if did in RUNGS:
        rec["step"] = RUNGS.index(did) + 1
        rec["ladder"] = True      # the step numbers are the one ladder's (`unwind` reads them back for the old table)
    rec["last"] = now
    if did == "cold":
        rec["cold_at"] = now


def on_ladder(rec: dict[str, Any] | None, now: float, at: float | None = None) -> bool:
    """Is the item on the one ladder (an entry the hand-off audit made, still within its bounds)? The hand-off audit leaves such an item to the ladder. With `at` (the `at` of the hand-off
    record now on the item) only an entry made for that hand-off counts: a later hand-off of the item to the same mover is not the one the entry was made for."""
    return bool(rec) and via_of(rec) == "handoff" and not _stall.expired(rec, now) and (at is None or float(rec.get("ho_at") or 0) == float(at or 0))
