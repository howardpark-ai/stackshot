"""front_pickup.py: an idle front agent with an open step of its own on an item it moves gets its turn started, once an hour per item.

Part of the rule that no item an agent moves goes more than an hour without an update (audit/hourly.py is the line side, audit/hand_idle.py the hand-over of an idle builder's item, audit/busy_tell.py the tell of a long busy
stretch, audit/front_handon.py the hand-on of a front agent's own step to a free background agent). An item whose first open step is the front agent's own can sit for as long as the agent has no turn: nothing wakes a front agent for its own
step (a hold or an until of its own is refused it, and a notice about the item only starts a turn while the owner is there). The hand-on is the first answer: it gives the item to a free background agent of the project. This pick-up is its FALLBACK: it
starts the front agent's own turn for an item the hand-on did not move, because no background agent of the project was free or the project has none (an item the hand-on acted on at the same tick is in `skip`, never both). This module decides which front
agent to start; the server sends (`audit_ticks._front_pickup_tick`, run from the ten-minute audit tick after the idle hand-over and the hand-on and before the busy-stretch tell). It rides `[audit] hourly_line` (no key of its own: with the hourly
line off it stands still).

  eligible(items, gid, now, front, idle, present, same, skip, marks)   the row of `due` without its two once-an-hour records (`marks` None): the test the hand-on reads an item by too
  due(items, gid, now, front, idle, present, same, marks, skip)   {"mover", "project", "steps", "more"} when the agent's turn is to be started for the item now, else None
  due_all(...)                                                  [(gid, row)] of every such item, in id order; reads only; an item that cannot be read is left out and its reason goes to `errors`
  pick(rows, same)                                              the rows a tick sends: the first item of each agent, at most `MAX_TURNS_PER_TICK`
  words(row, lead)                                              the one line the agent is sent
  read_marks() / write_marks() / mark() / unmark() / prune()      `<paths.state>/front-pickup.json`, the once-an-hour record (`marked_recently`)

An item is picked up when ALL of these hold (a read that fails is "no", never "yes": every test below is fail closed):

  - it is open and on an agent as the board shows it (`silence.reading`): a session moves it, its state is not the owner's move and the board does not show it waiting; so a hold, a park, an `until` or a wake, an open `after`, an anchor wait or any
    other stored wait is left alone, and so is an item whose needs holds a decision; the item model reads it alive with a session mover, never the owner;
  - the mover is a front agent of the item's own project (the role map: role front, not retired, the item's project) and the item's FIRST open step names it as its opener (`steps.opener`): the leading run of its own open steps is the work in
    hand. A first open step that is the owner's (a step naming him, or naming nobody) or another session's is a wait on that person, and nothing is started; a later step of another person does not matter, it is behind the agent's own. Bare
    sub-steps belong to the line above them and are not read;
  - the agent is idle: the fleet's last agent-state snapshot (audit/agent_state.py) says so, fresh, read, state `idle` and the pane word `idle` (`audit_ticks._pane_idle`: a pane that reads `shell` or `sleeping` takes a line into a queue, not a turn).
    Busy, unknown, stale and missing all start nothing;
  - the owner is not in that conversation: his last prompt in that pane is older than `[presence] minutes` (service/front_turn.py `present`, read for the pane by its session id in the fleet's index so that a pane on another box counts; a stamp dated
    ahead of the clock is present), and the stamp folder and the index could be read, the index whole (a partial index, a machine whose sessions.json could not be read, starts nothing);
  - the item has been quiet for `QUIET` (`hourly.EVERY`, 45 minutes, the same figure as the first hourly line: `silence.clock`), so the turn is started on the first ten-minute tick past it, inside the hour;
  - it was not started for in the last `GAP` (an hour): the record `<paths.state>/front-pickup.json` {schema, marks: {item id: the epoch second the turn was started for}}. A mark dated more than an hour ahead of the clock is torn and counts for nothing.
    The busy-stretch tell's own record (`metadata.busy_tell.at`) counts the same way: an item that tell named to the agent in the last hour is not nudged again by this. A delivery that fails (a dead pane, a push that returns nothing) turns the mark
    into a half-hour backoff (`FAIL_BACKOFF`), so a push that keeps failing is tried every half hour, not every ten minutes. A record that cannot be read for now (an OSError) is not a torn one: it stays, nothing is started that tick.

One action per item per tick, and which wins. The hand-on (`front_handon`) wins over this: an item it acted on this tick is in `skip`. The idle hand-over (`hand_idle.due`) wins over this too: an item it hands on this tick is not picked up (it leaves its mover; it cannot be due for a front agent with a step of its own open
anyway, `hand_idle._front_step_open`, so the two never meet unless the mover's step list changed between two reads). The busy-stretch tell (`busy_tell.due`) wins too: it is the older rule, it tells the same front agent about the same item in
the same words of asking, and one message per item per tick is all there is; the pick-up looks again on the next tick, when the tell is on the item (`metadata.busy_tell`) and the agent has likely taken a turn. A background agent's own open
step stays with the hand-over and the ladders: this module reads front agents only. One turn per agent per tick (a second item of the same agent waits for the next tick: by then the agent is in a turn and not idle, so it is not started again while
it works), and at most `MAX_TURNS_PER_TICK` turns in one tick, so a backlog after a long stop (or the first tick after the snapshot starts to arrive) does not flood the panes; the rest follow, ten minutes apart.

Pure but for the one marks file: stdlib plus the repo's modules."""
from __future__ import annotations

import json
import math
import os
import threading
from pathlib import Path
from typing import Any, Callable, Iterable

from stackshot.audit import audit_checks as _ac
from stackshot.audit import busy_tell as _bt
from stackshot.audit import hourly as _hourly
from stackshot.audit import silence as _silence
from stackshot.core import config as _cfg
from stackshot.model import model as _model
from stackshot.model import steps as _steps
from stackshot.model.needs import _waits_decision
from stackshot.waits import waiting as _wt

FILE = "front-pickup.json"          # in <paths.state>
SCHEMA = 1
GAP = 3600.0                        # a turn is started for an item at most once in this long
FAIL_BACKOFF = 1800.0               # after a delivery that failed the item is tried again this long after, not at the next tick
QUIET = _hourly.EVERY              # the item has had no real activity for this long: the first hourly line's own threshold (45 minutes)
MAX_TURNS_PER_TICK = 3              # turns started in one ten-minute tick (an agent counts once): the rest wait for the next tick
STEPS_SHOWN = 3                     # the agent's open steps the line names; the rest are a count
STEP_CLIP = 90                      # characters of a step's first line the message quotes
_LOCK = threading.Lock()            # the marks file is read, changed and written whole: one writer at a time in this process


class Unreadable(Exception):
    """The marks file exists and cannot be read as a record: nothing is started this tick."""


# ---------------------------------------------------------------------------------------------------------------- the record
def path() -> Path:
    return _cfg.state(FILE)


def _number(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def read_marks() -> dict[str, float]:
    """{item id: the epoch second a turn was started for it}; {} when there is no file yet. A value that is no number is dropped (a torn value is no mark). Raises `Unreadable` for a file that is no JSON, no text or no
    record of this schema: the caller starts nothing and sets the file aside. An OSError (a read that failed for now: a busy disk, a permission) is NOT a torn record: it propagates as it is, the caller starts nothing this
    tick and the file stays where it is."""
    p = path()
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except UnicodeDecodeError as e:
        raise Unreadable(f"{p.name} is no text") from e
    try:
        d = json.loads(raw)
    except (ValueError, RecursionError) as e:
        raise Unreadable(f"{p.name} is no JSON") from e
    if not isinstance(d, dict) or d.get("schema") != SCHEMA or not isinstance(d.get("marks"), dict):
        raise Unreadable(f"{p.name} is no record of schema {SCHEMA}")
    return {str(k): n for k, v in d["marks"].items() if (n := _number(v)) is not None}


def write_marks(marks: dict[str, float]) -> None:
    """The record whole to a temporary file beside it, then renamed over it (a reader sees the old record or the new one, never half of one); the temporary file is removed on a failure. Raises OSError."""
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps({"schema": SCHEMA, "marks": marks}, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)


def set_aside() -> None:
    """A record that cannot be read is moved to `<file>.torn` so the next tick starts a clean one (at worst an item is started for once more); the one line that says so is the caller's."""
    p = path()
    try:
        os.replace(p, p.with_name(p.name + ".torn"))
    except OSError:
        pass


def marked_recently(marks: dict[str, float], gid: str, now: float) -> bool:
    """Was a turn started for the item within `GAP`? A mark dated more than `GAP` ahead of `now` is torn (a clock set far ahead once would otherwise hide the item until real time caught up)."""
    at = _number(marks.get(gid))
    return at is not None and at <= now + GAP and now - at < GAP


def told_lately(meta: dict[str, Any], now: float) -> bool:
    """Did the busy-stretch tell (audit/busy_tell.py) tell the item's agent within `GAP`? Its record is `metadata.busy_tell.at`; the two rules nudge one item at most once an hour between them."""
    rec = meta.get(_bt.KEY)
    at = _number(rec.get("at")) if isinstance(rec, dict) else None
    return at is not None and at <= now + GAP and now - at < GAP


def prune(marks: dict[str, float], items: dict[str, dict[str, Any]], now: float) -> dict[str, float]:
    """The marks that still matter: those within `GAP` (a mark dated ahead is read by `marked_recently`) of an item that is open or that this tick's list does not hold. A closed item's mark and an expired one go; an item
    merely missing from the list (one that could not be read this tick) keeps its mark until it expires, so a read that failed once does not let the item be started for twice in an hour."""
    return {g: at for g, at in marks.items() if marked_recently(marks, g, now) and (g not in items or items[g].get("status") == "open")}


def mark(gid: str, now: float, items: dict[str, dict[str, Any]] | None = None) -> None:
    """Record that a turn is being started for the item now (before anything is sent: a send that fails takes it back with `unmark`), pruning the others. Raises Unreadable or OSError: the caller sends nothing."""
    with _LOCK:
        marks = read_marks()
        if items is not None:
            marks = prune(marks, items, now)
        marks[gid] = now
        write_marks(marks)


def unmark(gid: str, stamp: float) -> bool:
    """Take the mark back after a delivery that failed, but only the one written at `stamp` (another pass may have written a later one) → True when it was changed. The item is not tried again at the next tick: the mark
    becomes a short one that blocks for `FAIL_BACKOFF` from `stamp` (a mark dated `GAP - FAIL_BACKOFF` before it), so a push that keeps failing is tried every half hour, not every ten minutes. Never raises."""
    try:
        with _LOCK:
            marks = read_marks()
            if _number(marks.get(gid)) != stamp:
                return False
            marks[gid] = stamp - GAP + FAIL_BACKOFF
            write_marks(marks)
            return True
    except (Unreadable, OSError):
        return False


# ---------------------------------------------------------------------------------------------------------------- the decision
def open_steps(meta: dict[str, Any]) -> list[str]:
    """The texts of the item's open steps in order, a bare sub-step left out (it is part of the line above, as `audit_checks.first_open_step` reads it)."""
    return [s["text"] for s in _steps.view(meta, keeper=str(meta.get("owner") or "")) if s["status"] == _steps.OPEN and not _steps.is_bare(s["text"])]


def own_run(meta: dict[str, Any], mover: str, same: Callable[[Any, Any], bool]) -> list[str]:
    """The leading run of the item's open steps that open with `mover`: [] when the first open step is anyone else's, the owner's (a step that names nobody counts as his, as `steps.is_his` reads it) or nobody's."""
    out: list[str] = []
    for text in open_steps(meta):
        nm = _steps.opener(text)
        if not nm or _model.is_owner(nm) or not same(nm, mover):
            break
        out.append(text)
    return out


def due(items: dict[str, dict[str, Any]], gid: str, now: float, front: Callable[[Any, str], bool], idle: Callable[[str], bool], present: Callable[[str], bool],
        same: Callable[[Any, Any], bool], marks: dict[str, float], skip: Iterable[str] = ()) -> dict[str, Any] | None:
    """The row of the open item `gid` when its mover's turn is to be started now (see the module doc), else None: {"mover", "project", "steps" (the texts of the agent's leading open steps), "more" (how many of them are not named)}.
    `front(name, project)` says whether `name` is a front agent of the project, `idle(name)` whether the agent-state snapshot says it is idle, `present(name)` whether the owner is in that conversation; each is fail closed here: one that raises
    reads as "no start". `marks` is the record (`read_marks`), `skip` the items another pass acts on this tick."""
    return eligible(items, gid, now, front, idle, present, same, skip, marks)


def eligible(items: dict[str, dict[str, Any]], gid: str, now: float, front: Callable[[Any, str], bool], idle: Callable[[str], bool], present: Callable[[str], bool],
             same: Callable[[Any, Any], bool], skip: Iterable[str] = (), marks: dict[str, float] | None = None) -> dict[str, Any] | None:
    """`due` without the once-an-hour records when `marks` is None: the row of the open item `gid` when it is an idle front agent's, its leading open step is its own, nobody is in that conversation and the item is quiet. The hand-on
    (audit/front_handon.py) reads an item by this same test, so the two passes never disagree about whether the agent is idle and the step its own. With `marks` given, the item must also not have been started for in the last hour
    and not have been told by the busy-stretch tell in it."""
    item = items.get(gid) or {}
    if item.get("status") != "open" or gid in set(skip):
        return None
    it, meta, after_open, mover = _ac._item_view(items, gid)
    if _ac._no_session(mover) or _model.is_owner(mover):
        return None
    if _silence.reading(it, mover, after_open, now) != "agent" or _wt.is_held(it) or _waits_decision(meta):
        return None      # not on an agent as the board shows it (a hold, a park, an until, an open after, an anchor or other wait, the owner's move), or it waits on a decision of his
    mod = _model.derive(it, now, after_open)
    if mod.state != _model.ALIVE or mod.owner_moves or not same(mod.mover, mover):
        return None
    project = str(meta.get("project") or "")
    steps = own_run(meta, mover, same)
    if not steps:
        return None      # the first open step is the owner's, another session's or nobody's, or there is none: a wait on that person, not the agent's work
    last = _silence.clock(it, mover)
    if not (last > 0 and now - last >= QUIET) or (marks is not None and (marked_recently(marks, gid, now) or told_lately(meta, now))):
        return None
    try:
        if not (front(mover, project) and idle(mover)) or present(mover):
            return None
    except Exception:  # noqa: BLE001  — a role map, a snapshot or a presence stamp that cannot be read starts nothing
        return None
    return {"mover": mover, "project": project, "steps": steps[:STEPS_SHOWN], "more": max(len(steps) - STEPS_SHOWN, 0)}


def due_all(items: dict[str, dict[str, Any]], now: float, front: Callable[[Any, str], bool], idle: Callable[[str], bool], present: Callable[[str], bool],
            same: Callable[[Any, Any], bool], marks: dict[str, float], skip: Iterable[str] = (), errors: list[str] | None = None) -> list[tuple[str, dict[str, Any]]]:
    """[(gid, row)] of every item whose agent's turn is to be started now, in id order; reads only. An item that cannot be read is left out, and `errors` (when given) gets one line for it."""
    out: list[tuple[str, dict[str, Any]]] = []
    skip = set(skip)
    for gid in sorted(items, key=_ac._num):
        if items[gid].get("status") != "open":
            continue
        try:
            row = due(items, gid, now, front, idle, present, same, marks, skip)
        except Exception as e:  # noqa: BLE001  — one item never stops the others
            if errors is not None:
                errors.append(f"{gid} not read: {e.__class__.__name__}: {e}")
            continue
        if row is not None:
            out.append((gid, row))
    return out


def pick(rows: list[tuple[str, dict[str, Any]]], same: Callable[[Any, Any], bool]) -> list[tuple[str, dict[str, Any]]]:
    """The rows a tick sends, in id order: the first item of each agent (a second item of the same agent waits for the next tick, when the agent is in a turn), at most `MAX_TURNS_PER_TICK`."""
    out: list[tuple[str, dict[str, Any]]] = []
    for gid, row in rows:
        if len(out) >= MAX_TURNS_PER_TICK:
            break
        if any(same(r["mover"], row["mover"]) for _g, r in out):
            continue
        out.append((gid, row))
    return out


def _clip(text: str) -> str:
    one = " ".join(_steps.strip_opener(_steps.first_line(text)).split())
    return one if len(one) <= STEP_CLIP else one[: STEP_CLIP - 1].rstrip() + "…"


def words(row: dict[str, Any], lead: str) -> str:
    """The one line the agent is sent about the item: what it is (`lead`, the item as the notices name it), that it is the agent's own and idle, its open steps by their first line, and what is asked (take it, or say what blocks it)."""
    shown = "; ".join(f'"{_clip(t)}"' for t in row["steps"]) + (f" (and {row['more']} more)" if row["more"] else "")
    n = len(row["steps"]) + row["more"]
    return f"{lead}: you are idle and {'an open step is' if n == 1 else f'{n} open steps are'} yours: {shown}. Take {'it' if n == 1 else 'them'}, or write what blocks {'it' if n == 1 else 'them'}"
