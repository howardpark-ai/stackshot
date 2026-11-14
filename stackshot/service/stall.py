"""stall.py: the stall pass's state, its pause and its steps.

When the session that moves a live item has no turn running for [stall] minutes (10), the stall pass moves the item on itself (the pass is service/stall_tick.py; the pure rules that say which step is
due are waits/stall.py and, with the one ladder on, waits/ladder.py). This module holds what the pass and the ladder share: the pass's state, <state>/stall.json (one entry per item, and the pass's own record of
when it first ran), the pause switch and its record, <state>/stall_pause.json, the readers of a mover and of an item's version, and the steps themselves: the notice sent once more (`stall_resend`), the cold call
(`stall_cold`, through service/handoff_cold.py) and the project's builder (`stall_builder`, through the hand-off pass's `handoff_exec`). The one ladder is service/ladder.py.

What it still reaches in server.py comes through `Hooks` in service/stall_hooks.py, looked up when it runs, so a suite that replaces one on its owner module is the one called. A suite that replaces a function or a clock
of this module sets it here (and `time` here, since this module reads its own).

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core.instance import NAME
from stackshot.fleet.sessions_registry import _session_label
from stackshot.github import ghsync as _gh
from stackshot.model.bullet_text import _clip_line
from stackshot.router import routing as _routing
from stackshot.service import handoff as _handoff
from stackshot.service import handoff_cold as _hcold
from stackshot.service import telling as _telling
from stackshot.service import writes as _writes
from stackshot.service.stall_hooks import hooks as _hooks
from stackshot.service.store import _load
from stackshot.waits import handoff as _ho
from stackshot.waits import mover_state as _mover_state
from stackshot.waits import stall as _stall


STALL_LAST = [0.0]


STALL_LOCK = threading.RLock()


def stall_on(now: float | None = None) -> bool:
    """The stall pass runs: [model] handoff is on (it moves items through the hand-off machinery) and the pass is not paused. A pause always ends on its own (as when
    a switch that is off while nothing wakes idle builders): see `stall_pause_check`."""
    return _handoff.handoff_on() and stall_pause_check(now) is None


STALL_PAUSE: dict[str, Any] = {"rec": None, "loaded": False, "said": ""}     # the pause's record (stall.pause): in memory, and in <state>/stall_pause.json so a restart keeps the clock; `said`: the refusal already logged


def stall_pause_path() -> Path:
    return _cfg.state("stall_pause.json")


def stall_pause_log_project() -> str:
    """The project page the end of a pause is logged under in the routing log: the fleet operator's ([fleet] operator_session), else none (the journal line alone)."""
    try:
        op = str(_cfg.get("fleet", "operator_session") or "").strip()
        return str((_anc.session_roles().get(op) or {}).get("project") or "") if op else ""
    except Exception:  # noqa: BLE001
        return ""


def stall_pause_check(now: float | None = None) -> float | None:
    """[stall] enabled = false and [stall] paused_until, read live: → when the pause ends (epoch) while the pass is paused, else None (the pass runs). A pause ends on its own: paused_until
    holds the pass until then, enabled = false for at most [stall] max_pause_hours (4) from when the server first saw it (a paused_until further out is cut to that too); the record of when
    it was first seen is kept in memory and in <state>/stall_pause.json (stall.pause is the decision). The start and the end of a pause are one journal line each
    (`stall: paused until <time in the instance timezone> (<why>)`, `stall: pause ended, the pass runs again`), the end also a routing-log line. Never raises: a failure runs the pass.
    An agent never switches the pass off. A pause is honored only when [stall] pause_item names a board item that carries the owner's own answer approving a pause (its option or text
    says "pause") dated within 4 hours of when the server first saw the pause (config.stall_auth, stall.authorize); one answered only after its cap starts then (event "late", one line); otherwise the pass runs and ONE journal line says why (`stall: pause refused, the pass keeps running: <why>`),
    logged once per config load (`stall_pause_reload` forgets it at a start and a reload), not per tick."""
    now = time.time() if now is None else now
    try:
        with STALL_LOCK:
            if not STALL_PAUSE["loaded"]:
                STALL_PAUSE["loaded"] = True
                try:
                    d = json.loads(stall_pause_path().read_text(encoding="utf-8"))
                    STALL_PAUSE["rec"] = d if isinstance(d, dict) and d.get("sig") and d.get("since") else None
                except Exception:  # noqa: BLE001
                    STALL_PAUSE["rec"] = None
            old = STALL_PAUSE["rec"]
            rec, end, why, ev = _stall.pause(_cfg.get("stall", "enabled", default=True), _cfg.get("stall", "paused_until", default=""), _hooks().zone(),
                                             _stall.pause_hours(_cfg.get("stall", "max_pause_hours", default=_stall.PAUSE_HOURS)), old, now,
                                             _cfg.stall_auth(_cfg.get("stall", default={})))
            if "refuse" not in ev:
                STALL_PAUSE["said"] = ""
            if rec != old:
                STALL_PAUSE["rec"] = rec
                try:
                    p = stall_pause_path()
                    if rec is None:
                        p.unlink(missing_ok=True)
                    else:
                        p.parent.mkdir(parents=True, exist_ok=True)
                        tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(rec) + "\n", encoding="utf-8"); os.replace(tmp, p)
                except Exception as e:  # noqa: BLE001
                    print(f"stall: pause state not saved: {e}", file=sys.stderr, flush=True)
            for e in ev:
                if e == "refuse":
                    if STALL_PAUSE["said"] != why:
                        STALL_PAUSE["said"] = why
                        print(f"stall: pause refused, the pass keeps running: {why}", file=sys.stderr, flush=True)
                elif e == "start" and end is not None:
                    print(f"stall: paused until {stall_when(end)} ({why})", file=sys.stderr, flush=True)
                elif e == "late" and end is not None:
                    print(f"stall: paused until {stall_when(end)} ({why}); started late: the answer came after the pause's cap, so it runs from now", file=sys.stderr, flush=True)
                elif e == "end":
                    stall_pause_ended(now)
            return end
    except Exception as e:  # noqa: BLE001
        print(f"stall: pause not checked, the pass runs: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return None


def stall_pause_reload() -> None:
    """A start or a config reload: a refusal of a pause is logged again once (one line per config load, never one per tick)."""
    STALL_PAUSE["said"] = ""


def stall_when(ts: float) -> str:
    """A time in a stall line: the instance zone, the rulebook's form: `Mon Mar 2nd 2099 09:00 UTC` (the zone's own abbreviation)."""
    t = dt.datetime.fromtimestamp(ts, _hooks().zone())
    return f"{_hooks().when_words(t)} {t:%Z}"


def stall_pause_ended(now: float) -> None:
    """The end of a pause: one journal line and one routing-log line (ruled dropped by stackshot (auto): it asks nothing of anyone). Never raises."""
    line = "stall: pause ended, the pass runs again"
    print(line, file=sys.stderr, flush=True)
    try:
        proj = stall_pause_log_project()
        if proj:
            _routing.record_auto(proj, "dropped", "stall pause ended: logged, nothing to deliver", kind="board", label="stall pause ended", who=NAME, text=line, ts=now)
    except Exception as e:  # noqa: BLE001
        print(f"stall: pause end not logged to the routing log: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


def stall_num(key: str, default: float) -> float:
    try:
        v = float(_cfg.get("stall", key, default=default))
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


def stall_minutes() -> float:
    return stall_num("minutes", _stall.MINUTES)


def stall_path() -> Path:
    return _cfg.state("stall.json")


STALL_PASS = "_pass"      # the pass's own record in stall.json (no item id starts with an underscore): {"since": when the pass first ran}


def stall_raw() -> dict[str, Any]:
    try:
        with open(stall_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def stall_write(d: dict[str, Any]) -> None:
    try:
        p = stall_path(); p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(d, indent=1) + "\n", encoding="utf-8"); os.replace(tmp, p)
    except Exception as e:  # noqa: BLE001
        print(f"stall: state not saved: {e}", file=sys.stderr, flush=True)


def stall_load() -> dict[str, dict[str, Any]]:
    """The episodes by item id (the pass's own record, `STALL_PASS`, is not one)."""
    return {k: v for k, v in stall_raw().items() if k != STALL_PASS and isinstance(v, dict)}


def stall_save(st: dict[str, dict[str, Any]]) -> None:
    """Write the episodes; the pass's own record is kept as it is on disk."""
    with STALL_LOCK:
        d = {k: v for k, v in st.items() if k != STALL_PASS}
        p = stall_raw().get(STALL_PASS)
        if isinstance(p, dict):
            d[STALL_PASS] = p
        stall_write(d)


def stall_since(now: float) -> float:
    """When the stall pass first ran on this store, written to stall.json the first time and read from it after (it survives a restart). The pass starts with an empty
    state, and an item whose pane has been idle for hours would be 'stalled' at the first tick, so every idle item got its step at once. No clock
    starts before this moment: the first step of any item is `minutes` after the pass began, at the earliest."""
    with STALL_LOCK:
        d = stall_raw()
        p = d.get(STALL_PASS)
        try:
            if isinstance(p, dict) and float(p.get("since") or 0) > 0:
                return float(p["since"])
        except (TypeError, ValueError):
            pass
        d[STALL_PASS] = {"since": now}
        stall_write(d)
        return now


def stall_background(who: str) -> bool:
    """Is `who` a background agent of some project page (role "back")? A front agent, a keeper and a session with no role are not."""
    try:
        roles = _anc.session_roles()
        name = _hooks().role_name(roles, who)
        return bool(name) and roles[name].get("role") == "back"
    except Exception:  # noqa: BLE001
        return False


def stall_mover(gid: str, item: dict[str, Any]) -> str:
    return _mover_state.mover({**item, "gid": gid}, _handoff.ho_derive)


def stall_confirm(item: dict[str, Any], mover: str) -> float:
    """The item's `confirmed` clock when the last session to write the item (the confirm tool stamps `written_by`) is its mover, else 0: another session's confirm says nothing about whether the mover
    is working, so it neither restarts the stall episode nor moves its minutes."""
    c = float(item.get("confirmed") or 0)
    return c if c and (_handoff.ho_same(item.get("written_by_id"), mover) or _handoff.ho_same(item.get("written_by"), mover)) else 0.0


def stall_ver(item: dict[str, Any]) -> list[float]:
    """The version an episode is made for: when the item was written and when its state changed. Anyone writing the item ends the episode (stall.episode); so does its mover confirming it."""
    return [float(item.get("updated") or 0), float(item.get("state_updated") or 0)]


def stall_record(item: dict[str, Any], who: str, now: float) -> dict[str, Any]:
    """The hand-off record the stall pass works on, in place: the item's open untaken one to this mover, else a new one from the server with the old one in the history (a taken record
    would make the cold call drop its answer). It runs no clock (`no_clock`: the hand-off ladder leaves it alone) and carries `stall`, which keeps the item from going back to a sender."""
    meta = item.setdefault("metadata", {})
    old = _ho.record_of(item)
    if old and _handoff.ho_same(old.get("to"), who) and not old.get("taken_at") and not old.get("recovery_at"):
        r = old
    else:
        if old:
            _ho.push_history(meta, old, now, "replaced by the stall pass")
        r = _ho.new_record(_session_label(who), _handoff.ho_ident(who), _ho.SERVER, now, tried=[t for t in ((old or {}).get("tried") or []) if t], origin=(old or {}).get("origin"),
                           steps=int((old or {}).get("steps") or 0), cold=(old or {}).get("cold"))
        meta[_ho.KEY] = r
    r["stall"], r["no_clock"] = True, True
    return r


def stall_resend(gid: str, who: str, now: float, minutes: float, lines: list[tuple[str, str, str]]) -> str:
    """Step 1: the notice goes to the mover once more (batched per recipient by the tick)."""
    with _writes.ITEM_LOCK:
        item = _load(gid)
        if item.get("status") != "open" or not _handoff.ho_same(stall_mover(gid, item), who):
            return ""
        meta = item.setdefault("metadata", {})
        # review: no item notice wakes a front agent (see _rekeyed, and _handoff.handoff_exec, which skips them via front_keeper). For a front mover this step is the History line
        # alone; the cold call and the builder, steps 2 and 3, are what cover its item.
        front = _telling.front_keeper(who, str(meta.get("project") or ""))[0]
        _stall.note(meta, now, f"{_session_label(who)} had no turn running for {minutes:g} min" + (": no notice is sent to a front agent, the next step follows" if front else ": the notice was sent to it again"))
        _writes.save(gid, item, note="stall: " + ("no notice to a front agent" if front else "the notice was sent again"))
        nxt = _clip_line((str(meta.get("next") or "").strip().splitlines() or [""])[0], 160)
        if not front:
            lines.append((who, gid, f"{_gh.shown(gid)}: {item.get('subject') or ''} ({meta.get('project') or ''})" + (f"; next: {nxt}" if nxt else "")))
    print(f"stall: {gid} {who} had no turn for {minutes:g} min: " + ("front agent, history line only" if front else "notice sent again"), file=sys.stderr, flush=True)
    return "resend"


def stall_cold(gid: str, who: str, now: float, minutes: float) -> str:
    """Step 2: the hand-off's cold call, through the machinery that already handles its answer (_hcold.handoff_cold). The record carries `stall`, so the call never asks <owner>: with no taker
    named the item goes on to the builder (step 3) at once."""
    with _writes.ITEM_LOCK:
        item = _load(gid)
        if item.get("status") != "open" or not _handoff.ho_same(stall_mover(gid, item), who):
            return ""
        _hcold.HO_COLD_THREADS[:] = [t for t in _hcold.HO_COLD_THREADS if t.is_alive()]
        if _hcold.HO_COLD_THREADS:
            return ""                  # one cold call at a time board-wide: this step waits for the next tick
        why = f"{_session_label(who)} had no turn running for {minutes:g} min since the last step"
        stall_record(item, who, now)
        _ho.mark_cold(item, _ho.Step("cold", gid, why, who), now, _handoff.ho_same, _session_label)
        _stall.note(item["metadata"], now, f"{why}: the cold call was asked who takes it")
        _writes.save(gid, item, note="stall: the cold call was asked")
        th = threading.Thread(target=_hcold.handoff_cold, args=(gid, now), daemon=True)
        _hcold.HO_COLD_THREADS.append(th)
        th.start()
    print(f"stall: {gid} {who} still no turn: cold call asked", file=sys.stderr, flush=True)
    return "cold"


def stall_builder(gid: str, who: str, now: float, minutes: float) -> str:
    """Step 3: the project's builder (section 5's first choice); none able, the last rung: the fleet's builder is asked to recover the session (`_handoff.handoff_exec`, a `recover` step), or, for a front-only project
    (anchors.front_only: no background agent on its map), the project's -main agent (`_recovery_target`)."""
    with _writes.ITEM_LOCK:
        item = _load(gid)
        if item.get("status") != "open" or not _handoff.ho_same(stall_mover(gid, item), who):
            return ""
        r = stall_record(item, who, now)
        why = f"{_session_label(who)} had no turn running for {minutes:g} min and nothing was written to it"
        st = _ho.next_step({**item, "gid": gid}, r, who, why, _handoff.handoff_env(now), gid=gid, allow_return=False, cold_ok=False)
        if st.kind == "move":
            _stall.note(item["metadata"], now, f"{why}: handed to {_session_label(st.to)}, the project's builder")
        _writes.save(gid, item, note="stall: " + ("handed to the builder" if st.kind == "move" else "nobody can take it: recovery is requested"))      # a `recover` step writes its own History line
    done = _handoff.handoff_exec([st], now, verify=False)
    print(f"stall: {gid} {who} no turn: " + (f"handed to {st.to}" if st.kind == "move" else f"nobody can take it ({st.why}); recovery requested"), file=sys.stderr, flush=True)
    return "builder" if done else ""
