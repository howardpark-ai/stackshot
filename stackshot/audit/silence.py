"""silence.py: the ten-minute silence pass: has an item on an agent had no real activity for 45 minutes?

One pass that replaces the daily run's two silence rules (the stale check's 12-hour half and the board report's idle-on-agent, 6 hours) with an item-centered clock: `activity.at`, the time of the
item's last real activity (a step done or added, a state change, a new next step or description, the owner's answer, a message written onto the item, an event on one of its anchors). An audit's own write
and a bare confirm do not move it, so the pass's message cannot reset the clock it reads and a "still on it" confirm cannot keep an item fresh.

  findings(items, now, env)             → (findings, idle-pass entries): the open items that are silent
  silence_pass(...)                     the findings and what each owes: sent once per silence episode, to the mover, as the daily run sends a `stale` finding
  read_silence()                        the pass's record, `<state>/audit/silence.json`
  uncovered(items, now, env, skip)      the backstop: items on an agent, silent for 2 hours, that have no finding (a defect of the pass; the server checks hourly and tells the builder)

An item is silent when it is open, on an agent as the board shows it (`on_agent`: a session is its mover, its state is not the owner's move, and the board's own phase, `model.shown_waiting`, is not waiting) and has had no activity for `LIMIT`
seconds. What the board shows as waiting is left alone (a hold with a dated wake, an open `after` item, a stored wait: a release, a CI run or any other event, a relay, an outside party, a wake that carries a wait_basis); a wake without
one is a reminder and leaves the item on agent, so it is checked like any other. An item with a hand-off to a back agent that nobody took yet is left alone too (the hand-off audit's: it clocks that hand-off, so one item never climbs two ladders at once); a hand-off to a front agent is checked here, because that audit never clocks one. An item whose record the board's model cannot read is on an agent as the board lists it, and is checked with a finding that says so. The dates pass finds the same `stale` finding on an item whose wake has passed; each pass counts the other's sends, so one message goes out per episode. The count starts at the later of the item's last activity and
the moment it left a hold, a wait or an after link (those releases carry no writer, so the activity clock does not move for them). Silence is judged per item, never per pane: the mover's pane being busy (a builder directing subagents is nearly always busy) says nothing about one item,
so the pass does not read the pane and a busy pane hides no silent item. What counts as activity on the item is the clock's (a write, a message, an event on an anchor, a pull request's review or CI
run); a subagent's work that writes nothing to the item is not activity, so a builder keeps a long job visible by writing it onto the item (a step status, an update). One signal is read beyond the
clock: an item whose mover is its project's builder and which has a step with a status in progress (`subagent_running`, last changed within `SUBAGENT_S`, 90 minutes) has a build subagent running on it and
counts as taken, however long since its last write (the server's `skip` decides it, `server._silence_skip`). A builder's item with no such line and no event in 45 minutes is silent whatever its pane shows. Whether a session is idle is the stall pass's job and only the
rungs that need an idle pane (the ladder's look, cold call and builder steps of a front agent or a session no page lists as a background agent) wait for one; a background agent's rungs go by this step status alone (`server._stall_tick`). The pass asks one view before it sends: an item the stall ladder is already on is left alone (`skip`, given by the server).

A finding is the daily run's `stale` finding in the daily run's wording (the same category, evidence line and fix, the time given in minutes), so the two see one finding by `audit_run.finding_key`.
It goes to the recipient the daily run's finding goes to (`deliver_findings`: the mover, else the project's -main agent), once per silence episode: an episode ends when the item has activity again, and the
pass's send stamp (kept in its record, also for an item whose finding went away without any activity) is compared with the item's activity, not with its last write. With `[ladder] enabled` and `[ladder] silence` the server hands the pass `entered`: a fresh finding that reached someone also puts the item on the one ladder (ladder.py), its message being the ask. Nothing is sent or written while a
daily run is in progress (the pass stands still, like the filing and dates passes), and with `dry`. Stdlib plus the repo's modules."""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Any

from stackshot.model import activity as _act  # noqa: E402
from stackshot.audit import audit as _audit  # noqa: E402
from stackshot.audit import audit_checks as _ac  # noqa: E402
from stackshot.audit import audit_run as _ar  # noqa: E402
from stackshot.core import config as _cfg  # noqa: E402
from stackshot.audit import front_step as _fs  # noqa: E402
from stackshot.waits import handoff as _ho  # noqa: E402
from stackshot.model import model as _model  # noqa: E402
from stackshot.model import states as _states  # noqa: E402
from stackshot.model import work as _work  # noqa: E402
from stackshot.waits import waiting as _wt  # noqa: E402

LIMIT = 45 * 60.0          # seconds without activity on an item on an agent before it is found silent
BACKSTOP_S = 2 * 3600.0   # an item on an agent silent this long with no finding is a defect of the pass (`uncovered`)
SUBAGENT_S = 90 * 60.0    # a step status in progress counts as a running build subagent for this long after it was last changed (a pane recycle stops subagents and leaves the line behind)
FILE = "silence.json"
STAMP_KEYS = ("id", "project", "owner", "category", "mover", "detail", "source", "sent", "sending_from", "run_started")


def _path() -> Path:
    return _audit.state_dir() / FILE


def read_silence() -> dict[str, Any]:
    """The pass's record (`<paths.state>/audit/silence.json`), shaped like the filing pass's: `started`, `repeats`, `findings` with their `sent` stamps, and `carried`, the stamps of findings that went away with no
    activity on their item. {} when none."""
    try:
        d = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def minutes(secs: float) -> str:
    """A span for the evidence line: minutes up to four hours, past that hours and minutes ("30 hours 5 minutes")."""
    m = int(secs // 60)
    if m < 240:
        return f"{m} minutes"
    h, r = divmod(m, 60)
    return f"{h} hours" + (f" {r} minute{'s' if r != 1 else ''}" if r else "")


def _step_mover(item: dict[str, Any], mover: str) -> tuple[dict[str, Any], str]:
    """(the item's metadata, its first open step) for the front-step record's checks."""
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return meta, _ac.first_open_step(meta) or ""


def clock(item: dict[str, Any], mover: str = "") -> float:
    """Where the item's silence is counted from: its last activity, or the moment it left a hold, a wait or an after link if that is later. Those releases are saved by the server with no writer, which
    the activity clock counts as bookkeeping, so an item parked for a day would be found silent the round it wakes; its 45 minutes start when it is due again. A step the front-step rule moved to `mover`
    counts from the move too (front_step.landed_at): the server's move is no activity, and the mover is given its 45 minutes from the moment the step became its own."""
    try:
        left = float(item.get("state_updated") or 0)
    except (TypeError, ValueError):
        left = 0.0
    meta, step = _step_mover(item, mover)
    return max(_act.at(item), left, _fs.landed_at(meta, step, mover, _act.at(item)) or 0.0)


def _overdue(item: dict[str, Any], meta: dict[str, Any], mover: str, now: float) -> bool:
    """Is the item's first open step already overdue with no date of its own (front_step.overdue)? Then a wake does not cover it."""
    _, step = _step_mover(item, mover)
    return _fs.overdue(meta, step, mover, dt.datetime.fromtimestamp(now, _cfg.tz()).date(), _act.at(item))


def reading(item: dict[str, Any], mover: str, after_open: Any, now: float) -> str:
    """How the board stands toward the open item: "agent" (it shows the item on an agent), "unreadable" (the board's model raises on the item, and `home.classify` puts such an item on an agent rather than drop it),
    or "" (not on an agent: the mover is no session, the state is the owner's move, or the board shows it waiting)."""
    try:
        if _ac._no_session(mover) or _states.of(item, after_open)[0] in _model.OWNER_STATES:
            return ""
        return "" if _model.shown_waiting(item, now, after_open) else "agent"
    except Exception:  # noqa: BLE001
        return "" if _ac._no_session(mover) else "unreadable"


def on_agent(item: dict[str, Any], mover: str, after_open: Any, now: float) -> bool:
    """Is the open item on an agent as the board shows it? Its mover is a session, its state is not the owner's move, and the board does not show it waiting (`model.shown_waiting`, the board's own phase): a wake
    alone is a reminder and leaves an item on agent, while a wake with a wait_basis, a hold with a dated wake, an open `after` link and a stored wait (a release, a CI run, an event, a relay, an outside party) are
    waits. The scope of the silence rule and of the backstop (`uncovered`) alike. An item the model cannot read is on an agent here too, as the board lists it (`reading`)."""
    return bool(reading(item, mover, after_open, now))


def silent(item: dict[str, Any], meta: dict[str, Any], mover: str, after_open: Any, now: float, front: Any = None) -> str:
    """Why the item is silent ("" when it is not): "no write for N minutes and no date of its own", the daily run's stale wording with the time in minutes. An item that is not on an agent as the board shows it
    (`on_agent`) is left alone, and so is an untaken hand-off to a back agent (the hand-off audit clocks it). A hand-off to a front agent is checked here: that audit never clocks one (`front(mover, project)` → True
    for a front agent; None reads none as front)."""
    state = reading(item, mover, after_open, now)
    if not state:
        return ""
    if _ho.awaiting_session(item) and not (front is not None and front(mover, str(meta.get("project") or ""))):
        return ""
    last = clock(item, mover)
    if last > 0 and now - last > LIMIT:
        if state == "unreadable":
            return f"no write for {minutes(now - last)} and a record the board's model cannot read (write the item so its fields read)"
        what = "no date of its own"
        if _wt.wake_value(meta):      # a stored until counts as a wake
            # a wake alone is a reminder and the board shows the item on agent; it covers neither the silence nor a step that is already overdue and names no date of its own
            wake = _wt.wake_epoch(_wt.wake_value(meta))
            if wake is not None and wake <= now:      # a passed wake, with a wait_basis or without (the dates pass words the same case "past its wake"): holding with that wake would not help, a new date or a wait would
                what = "a wake that has passed (write the item, set a new date or a wait, or reword the step)"
            else:
                what = ("a wake that does not cover the step in hand" if _overdue(item, meta, mover, now) else "a wake that only reminds and does not park the item") + " (write the item, hold it with the wake and a wait_basis, store a wait, date the step or reword it)"
        return f"no write for {minutes(now - last)} and {what}"
    return ""


def subagent_running(item: dict[str, Any], now: float, mover: str = "", same: Any = None) -> bool:
    """Is a build subagent running on this item, by the item's own step statuses? A status in progress, last changed within `SUBAGENT_S`, is a build subagent the mover started on it. The server asks
    this only of an item whose mover is the project's builder (`skip`); a status that is only defined or assigned, a done one, and one older than the bound are not a subagent running.
    With `mover` given (the stall pass's hold of a background agent's ladder), only a status on a step that opens with that session's name counts, `same(a, b)` saying whether two names are one session: a stale status
    another agent left in progress says nothing about the mover being chased. The agent of a status is the session its step opens with."""
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    own = (lambda l: bool(same(l["agent"], mover)) if same else str(l["agent"]).casefold() == str(mover).casefold()) if mover else (lambda l: True)
    return any(0 < now - l["ts"] <= SUBAGENT_S for l in _work.in_progress(meta) if l["ts"] > 0 and own(l))


def findings(items: dict[str, dict[str, Any]], now: float, env: Any = None, skip: Any = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(findings, idle-pass entries) of the silence rule over the open items; reads only. As in the daily run, an item the server's idle pass poked (and its mover has not confirmed since) is an
    idle-pass entry, no finding. `skip(gid, item, mover)` → True leaves a silent item alone (the server passes the stall pass's view: an item its ladder is already on, never the state of a pane); a skip that cannot answer
    (it raises) leaves the item alone too."""
    from stackshot.tools import board_report as _br  # noqa: PLC0415
    from stackshot.tools import next_report as _nr  # noqa: PLC0415
    out: list[dict[str, Any]] = []
    passes: list[dict[str, Any]] = []
    _br.install_fallback()
    front = (env if hasattr(env, "is_front") else _ar.Env()).is_front
    for gid in sorted(items, key=_ac._num):
        if items[gid].get("status") != "open":
            continue
        it, meta, after_open, mover = _ac._item_view(items, gid)
        s = silent(it, meta, mover, after_open, now, front)
        if not s:
            continue
        if skip is not None:
            try:
                if skip(gid, it, mover):
                    continue
            except Exception:  # noqa: BLE001  (fail open: a view that cannot be read leaves the item alone, nothing is sent)
                continue
        entry = {"id": _nr.shown(gid), "project": str(meta.get("project") or ""), "owner": mover, "mover": mover, "category": "stale", "detail": s, "fix": _ac.FIX["stale"], "source": "code"}
        if _ac.idle_pass(it):
            passes.append({k: entry[k] for k in ("id", "project", "mover", "category", "detail")})
        else:
            out.append(entry)
    return out, passes


def uncovered(items: dict[str, dict[str, Any]], now: float, env: Any = None, skip: Any = None) -> list[dict[str, Any]]:
    """The backstop of the rule (hourly, `server._silence_backstop`): the open items on an agent as the board shows them (`on_agent`) that have been silent for more than `BACKSTOP_S` and that the rule has no finding for.
    Each such item is a defect of the pass itself: an exemption it carries that the board does not show as a wait. Judged from the board's phase and the activity clock alone, not through `silent`, so an exemption added
    there is caught here. Covered are an item with a finding or an idle-pass entry (`findings`) and one `skip` leaves to another chaser (the stall ladder, a build subagent running). → [{id, mover, project, silent}],
    `silent` the seconds without activity; reads only."""
    from stackshot.tools import next_report as _nr  # noqa: PLC0415
    found, passes = findings(items, now, env, skip)
    covered = {f["id"] for f in found} | {p["id"] for p in passes}
    out: list[dict[str, Any]] = []
    for gid in sorted(items, key=_ac._num):
        if items[gid].get("status") != "open":
            continue
        it, meta, after_open, mover = _ac._item_view(items, gid)
        if not on_agent(it, mover, after_open, now):
            continue
        last = clock(it, mover)
        if not (last > 0 and now - last > BACKSTOP_S) or _nr.shown(gid) in covered:
            continue
        if skip is not None:
            try:
                if skip(gid, it, mover):
                    continue
            except Exception:  # noqa: BLE001  (as in `findings`: a view that cannot be read leaves the item alone)
                continue
        out.append({"id": _nr.shown(gid), "mover": mover, "project": str(meta.get("project") or ""), "silent": now - last})
    return out


def sent_record() -> dict[str, Any] | None:
    """The pass's record shaped for `audit_run.merged_sent`: the findings it stands on and the stamps it carries, so the dates pass (which finds the same `stale` finding on an item whose wake has passed)
    counts what this pass already sent. None when the pass has no record."""
    prior = read_silence()
    return {"started": prior.get("started"), "repeats": 0, "findings": [*(prior.get("findings") or []), *(prior.get("carried") or [])]} if prior else None


def _split(found: list[dict[str, Any]], items: dict[str, dict[str, Any]], before: dict[tuple[str, str, str], tuple[float, float | None, float | None]],
           by_shown: dict[str, str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(repeats, fresh) as `audit_run.split_sent` splits them, with the item's activity in place of its last write: a finding sent before whose item has had no activity since goes back onto its old stamps."""
    return _ar.split_sent(found, items, before, by_shown, last=lambda it, f: clock(it, str(f.get("mover") or "")))


def silence_pass(*, now: float | None = None, items: dict[str, dict[str, Any]] | None = None, store: Path | None = None, env: Any = None, dry: bool = False, skip: Any = None,
                 entered: Any = None) -> dict[str, Any]:
    """The silence rule over the open items, and what a finding owes (see the module doc); `skip` as in `findings`. `entered(gid, mover, now, detail)`, when given (the server gives it with
    `[ladder] silence` on), is called once for each fresh finding that reached someone, after its message: that message is the ask of the one ladder, and the call puts the item on the ladder at its next
    rung. A finding sent in an earlier episode (a repeat) is not entered, so switching the ladder on does not start every item that is already silent at once; one that raises is logged and the rest go on.
    → {"skipped": why} or {"open", "findings", "fresh", "repeats", "idle_pass", "sent"}."""
    from stackshot.tools import next_report as _nr  # noqa: PLC0415
    now = time.time() if now is None else now
    env = env or _ar.Env()
    if not dry and _audit.running(now) is not None:
        return {"skipped": "a daily run is in progress"}
    items = items if items is not None else _nr.load_all(store)
    found, passes = findings(items, now, env, skip)
    n_open = sum(1 for it in items.values() if it.get("status") == "open")
    by_shown = {_nr.shown(g): g for g in items}
    recs = _audit.runs(limit=5)
    latest = next((r for r in recs if r.get("finished") is not None and not r.get("error")), None)
    before = _ar.merged_sent(latest, sent_record(), _ar.read_dates() or None)      # the dates pass's sends count too: a passed wake is a `stale` finding of both passes, sent once
    repeats, fresh = _split(found, items, before, by_shown)
    res = {"open": n_open, "findings": len(found), "fresh": len(fresh), "repeats": len(repeats), "idle_pass": len(passes), "sent": []}
    if dry:
        return {**res, "dry": True, "detail": found, "idle_pass_detail": passes}
    sent, reached_fs, sending_from = _ar.deliver_findings(env, fresh, f"Silence check {_ar._stamp(now)}") if fresh else ([], [], env.clock())
    end = max(env.clock(), now)
    sending_from = max(sending_from, now)
    for f in reached_fs:
        f["sent"], f["sending_from"], f["run_started"] = end, sending_from, now
        if entered is not None and by_shown.get(f["id"]):
            try:
                entered(by_shown[f["id"]], f.get("mover") or "", now, f.get("detail") or "")
            except Exception as e:  # noqa: BLE001  — the message went; the item simply is not on the ladder, and the next silence episode may bring it
                print(f"silence: {f['id']} not put on the ladder: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    now_keys = {_ar.finding_key(f) for f in found}
    carried: list[dict[str, Any]] = []      # a stamp whose finding went away with no activity on its item (a wait filed and lifted): the episode goes on, so the stamp stays
    for k, (sent_at, sf, rs) in before.items():
        gid = by_shown.get(k[0])
        if k[1] == "stale" and k not in now_keys and gid and items[gid].get("status") == "open" and not _ar.written_since_run(clock(items[gid], str(_ac._item_view(items, gid)[3] or "")), rs, sf, sent_at):
            carried.append({"id": k[0], "category": "stale", "sent": sent_at, "sending_from": sf, "run_started": rs})
    rec = {"started": now, "finished": end, "items_read": n_open, "repeats": len(repeats), "idle_pass": passes, "messages": sent, "carried": carried,
           "findings": [{k: f[k] for k in STAMP_KEYS if k in f} for f in found]}
    _ar.write_pass_record(_path(), rec)
    return {**res, "sent": sent}
