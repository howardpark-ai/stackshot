"""recycle.py: the bookkeeping of a recycle: what waits for one, what one cleared and the script's request for one.

An item's `recycle` flag says its mover's pane waits for a relaunch of the machine it runs on. `_recycle_wanted_rows` is what a recycle of a machine would serve now (and `_recycle_wanted` and
`_recycle_wanted_tokens` the ids and the tokens `client.py recycle-wanted` prints); `_recycled` is the fleet tool's end-of-recycle hook (it clears the flags the recycle served, releases a hold that waited for
the recycle alone, tells the movers and the event waits); `_recycle_due` is the script's request for a recycle on an existing item; `_on_machine`, `_last_recycle` and `_note_recycle` are the fleet's names, the
test of whether a session runs on a machine and the machine's recorded last recycle (the state file `recycles.json`).

A service module: it reads the store and writes an item only through `writes.save` and the update, under the locks the caller holds. The renderer's tests of a recycle wait, its words for a time, the board's ids as
shown, the debounced publish and the time zone come through `Hooks` in service/passes_hooks.py, which web/wiring.py fills (web/server.py calls it at its import). A suite that replaces one of these functions sets it on this module (and `time`
here, since this module reads its own clock).

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core.store import _item_files
from stackshot.fleet import clients as _clients
from stackshot.fleet import sessions_registry as _sr
from stackshot.github import ghsync as _gh
from stackshot.model import holders as _holders
from stackshot.model.field_gates import _when_idle
from stackshot.model.ids import _norm_id
from stackshot.model.needs import _needs_sessions
from stackshot.service import client_reads as _client_reads
from stackshot.service import event_waits as _evwaits
from stackshot.service import fleet_events as _fleetev
from stackshot.service import item_read as _item_read
from stackshot.service import released as _relsvc
from stackshot.service import store as _svcstore
from stackshot.service import telling as _telling
from stackshot.service import update as _update_svc
from stackshot.service import writes as _writes
from stackshot.service.passes_hooks import hooks as _hooks
from stackshot.waits import event_waits as _ew


def _on_machine(machine: str):
    """→ (names, on): the fleet's names (for _anc.canonical) and a test of whether a session id runs on `machine`, by the
    fleet's live heartbeat or by the sessions the client API holds for that machine."""
    nm, idx, fleet = _anc.names(), _sr._sessions_index(), _fleetev.fleet_names()
    here = set(_clients.sessions_on(machine))
    def on(owner: str) -> bool:
        rec = idx.get(owner.lower()) or idx.get(owner)
        return (rec is not None and fleet.get(rec.get("machine"), rec.get("machine")) == machine) or owner.lower() in here
    return nm, on


def _recycles_path() -> Path:
    return _cfg.state("recycles.json")      # {machine: epoch when its last reported recycle's sweep began}


def _last_recycle(machine: str) -> float:
    try:
        return float(json.load(open(_recycles_path(), encoding="utf-8")).get(machine) or 0)
    except Exception:
        return 0.0


def _note_recycle(machine: str, started: float) -> None:
    p = _recycles_path()
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        d = {}
    d[machine] = max(float(d.get(machine) or 0), started)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(d, indent=1) + "\n", encoding="utf-8"); os.replace(tmp, p)


def _held_only_for_recycle(item: dict[str, Any]) -> bool:
    """On hold, and the pane recycle is all the hold waits for: no wake and no open after (render.held_only_for_recycle,
    the one definition, which the board's status line uses too; the open afters read from the files here). _recycled releases
    such a hold with the recycle; _recycle_wanted counts such an item, since only a recycle will ever move it."""
    return _hooks().rmod_held_only_for_recycle(item, _item_read._after_open(item.get("metadata") or {}))


def _recycle_wanted_rows(machine: str) -> list[tuple[str, dict[str, Any]]]:
    """What a recycle of `machine` would serve now, as (id, item) pairs, oldest id first: the open items that wait for a recycle, moved
    by a session on that machine, flagged after its last reported recycle began, and not on hold, or on hold for the recycle
    alone (_held_only_for_recycle: before, such an item was never counted, so no recycle ran for it and
    it sat there). Not counted: items held for something else too (a wake, an open after; the next recycle clears their flag
    anyway), movers on another machine or not live, and items the last recycle kept because it skipped their mover, so a
    session that will not relaunch cannot start a recycle loop."""
    nm, on_machine = _on_machine(machine)
    last, out = _last_recycle(machine), []
    for gid, p in _item_files():
        try:
            it = _svcstore._load(gid)
        except Exception:
            continue
        if not _hooks().rmod_waits_recycle(it) or not _hooks().rmod_recycle_due(it, _item_read._after_open(it.get("metadata") or {})):   # the board's status line uses the same test
            continue
        at = (it.get("metadata") or {}).get("recycle_at")      # (an event wait for a recycle sets no recycle flag, so it never gets here; one that also carries the flag asks for the recycle like any other item)
        at = float(at) if isinstance(at, (int, float)) else 0.0
        if (at > last or not last) and any(on_machine(_anc.canonical(w, nm)) for w in _recycle_sessions(it) if w):
            out.append((gid, it))
    return sorted(out, key=lambda r: (r[0][0], int(r[0][1:]) if r[0][1:].isdigit() else 0))


def _recycle_wanted(machine: str) -> list[str]:
    """The ids of what a recycle of `machine` would serve now (_recycle_wanted_rows has the rule), oldest first."""
    return [gid for gid, _ in _recycle_wanted_rows(machine)]


def _recycle_wait_pr(project: str, gid: str, anchors: dict[str, Any] | None = None) -> str:
    """The pull request a recycle flag on item `gid` waits for, as sala writes a change reference: "<repo>:pr<N>" (the repository's
    short name, then the number), or "" when the item has no pull request anchor. The change the flag waits for is the item's
    pull request anchor: of the project's anchors scoped to the item, those that are GitHub pull request URLs, the one added last
    (an anchor record keeps no merged or closed state, so recency stands for "the open one": a pull request is anchored when its work
    starts, and a later anchor replaces an earlier one; sala treats a merged and deployed pull request as live, so a stale pick costs nothing).
    The repository is named as the URL has it (through [github.moved]); sala holds the recycle only for a name it maps
    (itself, or one in its SALA_RECYCLE_REF_REPOS) and counts any other as live."""
    best, best_at = "", -1.0
    for e in _item_read._scoped_anchors(project, gid, anchors):
        key = _relsvc._pr_key(str(e.get("url") or ""))
        if not key:
            continue
        try:
            at = float(e.get("added") or 0)
        except (TypeError, ValueError):
            at = 0.0
        if at >= best_at:                        # a tie goes to the later entry in the store
            best, best_at = key, at
    if not best:
        return ""
    repo, _, num = best.partition("#")
    return f"{repo.rsplit('/', 1)[-1]}:pr{num}"


def _recycle_wanted_tokens(machine: str) -> list[str]:
    """What `client.py recycle-wanted` prints after its count: one token per _recycle_wanted id, `<id>[@<epoch>][~<ref>]` (the fleet tool's
    contract, 5): `@<epoch>` is the whole second the recycle flag was raised (metadata.recycle_at; left out when the item stores none) and
    `~<repo>:pr<N>` the pull request the flag waits for (_recycle_wait_pr; left out when the item has none). The order is _recycle_wanted's."""
    rows = _recycle_wanted_rows(machine)
    try:
        anchors = _anc.load()
    except Exception:
        anchors = {}
    out = []
    for gid, it in rows:
        meta = it.get("metadata") or {}
        at = meta.get("recycle_at")
        tok = gid + (f"@{int(at)}" if isinstance(at, (int, float)) and not isinstance(at, bool) and at >= 1 else "")
        ref = _recycle_wait_pr(str(meta.get("project") or ""), gid, anchors)
        out.append(tok + (f"~{ref}" if ref else ""))
    return out


def _recycle_sessions(it: dict[str, Any]) -> list[str]:
    """The sessions a recycle of an item's flag waits for (D6): its mover (by its needs, its stored mover or the project's default), the sessions named in its needs and its `then`; never the creator."""
    meta = it.get("metadata") or {}
    out = [_telling.holder(it), *_needs_sessions(meta), _client_reads._then_label_raw(it)]
    return [w for i, w in enumerate(out) if w and w not in out[:i]]


def _recycled(machine: str, kind: str = "recycle", started: float = 0.0, result: str = "ok", skipped: list[str] | None = None,
              flag_at: float = 0.0) -> dict[str, Any]:
    """The fleet tool's end-of-recycle hook (client.py recycled): the panes on `machine` (the token's)
    were relaunched by a recycle or a reboot. sala calls it once per cleared recycle flag (contract version 19, interface 4): `flag_at` is that flag's time (epoch), and the call covers every open item flagged at or before it (its
    recycle_at <= flag_at; an item flagged exactly then is covered), while an item flagged after it waits for the next flag.
    A flag clears once every live pane in its scope has relaunched since the flag's time; a pane that never goes idle is given up
    after 3 h and the flag clears partly (result = partial), that pane in `skipped`. `flag_at` is also the time recorded as the
    machine's last recycle. Without `flag_at` (an older sala) the call is what it was: the sweep began at `started` (epoch; 0 =
    now) and every item flagged before then is covered, one flagged at or after it is kept. Every open item covered, moved by a
    session on that machine, loses metadata.recycle, and its mover gets one line naming its items. Kept: items whose mover the
    recycle skipped (by name in `skipped`), items flagged after the flag (or after the sweep began), and
    items whose mover is on another machine or not live anywhere. A held item whose hold waited only for the recycle (no wake,
    no open after) is released with it (a hold names what it waits for, and that has happened); one that also waits on a
    wake or an after stays on hold. The line goes to the sessions the item's notices go to (notice_to: the sessions in
    its needs, else the page's keeper, which for a front agent mover is its keeper); a session other than the mover gets a
    line naming the mover. → {"cleared", "kept", "told"}."""
    flag_at = float(flag_at or 0)
    started = float(started or 0) or flag_at or time.time()
    nm, on_machine = _on_machine(machine)
    skip = {_anc.canonical(s, nm) for s in (skipped or []) if str(s).strip()}
    _note_recycle(machine, flag_at or started)
    when = _hooks().rmod_when_words(dt.datetime.fromtimestamp(started, _hooks().zone()))
    what = "reboot" if kind == "reboot" else "recycle"
    cleared: dict[tuple[str, str], list[tuple[str, bool]]] = {}   # (to, the front mover it is told for, else "") → its rows
    kept: list[dict[str, str]] = []
    for gid, p in _item_files():
        try:
            it = _svcstore._load(gid)
        except Exception:
            continue
        meta = dict(it.get("metadata") or {})
        if it.get("status") != "open" or not _hooks().rmod_waits_recycle(it):
            continue
        owner = _anc.canonical(_telling.holder(it), nm)
        on = on_machine(owner)
        at = meta.get("recycle_at")
        later = isinstance(at, (int, float)) and (at > flag_at if flag_at else at >= started)   # a flag's call covers its own time; started-only: flagged after the sweep began
        why = ("flagged after the recycle flag it clears" if later and flag_at else "flagged after the recycle began" if later
               else "its mover was not relaunched" if owner in skip
               else "its mover is not on " + machine if not on else "")
        if why:
            kept.append({"item": gid, "why": why}); continue
        freed = _held_only_for_recycle(it)   # the recycle was all the hold waited for
        meta.pop("recycle", None); meta.pop("recycle_at", None)
        if freed:
            meta.pop("hold", None); meta.pop("hold_set", None); meta.pop("idle", None)
            it["updated"] = it["state_updated"] = time.time()   # released like a wake: both clocks move, no page owed
        else:
            it["updated"] = time.time()      # a filing edit: the state clock and the confirm stay as they were
        it["metadata"] = meta
        _writes.save(gid, it, note=f"the {what} it waited for has run ({machine}, {when})"   # phase 2 prep: the note is the History line, written by the server
              + (": released from hold" if freed else "; still on hold, waiting on its wake or after" if _holders._is_held(it) or _item_read._date_parked(it) else ""))
        for sid, _why in _telling.notice_to(meta) or [(owner, "")]:   # the sessions in its needs, else its mover
            to = (sid, "") if sid == owner else (sid, _sr._session_label(owner) or owner)
            cleared.setdefault(to, []).append((gid, "freed" if freed else "held" if _holders._is_held(it) or _item_read._date_parked(it) else ""))
        print(f"recycle: {gid} no longer waits ({kind} on {machine})", file=sys.stderr, flush=True)
    for (to, front), rows in cleared.items():
        ids = [_gh.shown(g) for g, _ in rows]      # the notice names each item as it is shown (board#N); the stderr tag keeps the raw ids
        names = ids[0] if len(ids) == 1 else ", ".join(ids[:-1]) + " and " + ids[-1]
        held = [_gh.shown(g) for g, h in rows if h == "held"]; freed = [_gh.shown(g) for g, h in rows if h == "freed"]
        ran = f"has run ({machine}, {when}" + (", partly" if result == "partial" else "") + ")"
        if front:       # another session than the mover: it comes to it as named in needs or as the page's keeper
            its = "its" if len(ids) == 1 else "their"
            note = (f"[stackshot] the {what} {names} waited for {ran}: re-read {names}; {its} mover is {front}, and resuming is yours as the session "
                    f"named in {its} needs: resume {its} work.")
        else:
            note = f"[stackshot] the {what} you waited for {ran}: re-read {names} and resume."
        note += (f" {' and '.join(freed)} waited only for the recycle and {'is' if len(freed) == 1 else 'are'} released from hold." if freed else "")
        note += (f" {' and '.join(held)} {'stays' if len(held) == 1 else 'stay'} on hold, waiting on {'its' if len(held) == 1 else 'their'} wake or after too: clear_hold=true if it should come back now." if held else "")
        raw = [g for g, _ in rows]
        _telling.tell_woken(raw[0] if len(raw) == 1 else ", ".join(raw[:-1]) + " and " + raw[-1], to, note, tag="recycle")
    if cleared:
        _hooks().publish()
    try:                           # an event wait on a recycle (or on a fleet op of this verb) is over: its mover hears it live. The count of sessions is sala's to report (client.py event), so `many` is not matched here
        _evwaits.evwait_report(_ew.event(_ew.RECYCLE, machine=machine, result=result, what=f"a {what} finished on {machine} ({when}" + (", partly" if result == "partial" else "") + ")"))
        _evwaits.evwait_report(_ew.event(_ew.FLEET_OP, machine=machine, verb=kind if re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", str(kind or "").lower()) else "recycle", result=result,
                                 what=f"the sala {what} finished on {machine} ({when}" + (", partly" if result == "partial" else "") + ")"))
    except Exception as e:  # noqa: BLE001  — the recycle's own record is written; a wait that is not woken here is woken by its backstop
        print(f"recycle: event waits not told: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return {"cleared": sorted(g for rows in cleared.values() for g, _ in rows), "kept": kept, "told": sorted({to for to, _ in cleared})}


_RECYCLE_DUE_LOCK = threading.Lock()
def _recycle_due(machine: str, item: str = "", pr: str = "") -> dict[str, Any]:
    """`client.py recycle-due`: a script
    marks a recycle as due on an existing item, as a session would with update(recycle=true): the item named by id (`item`),
    or the open items whose anchors include the pull request `pr`. It never files an item: "do
    recycle" is not an item, the field is how a recycle is asked for. When no item
    covers the change, the caller asks the fleet tool for a recycle once the box is idle ([fleet] recycle_when_idle). Running it again changes nothing.
    → {"items": [{"item", "action": set | already, "held", "owner"}], "pr"}; refusals raise ToolError."""
    item, pr = item.strip(), pr.strip()
    if bool(item) == bool(pr):
        raise ToolError(f"Refused: name the item that waits for the recycle (--item <id>) or the pull request whose anchored items do (--pr <url>), "
                        f"one of them. recycle-due never files an item; when no item covers the change, {_when_idle()}")
    if pr:
        if not _relsvc._pr_key(pr):
            raise ToolError(f"Refused: --pr takes a GitHub pull request URL (https://github.com/<owner>/<repo>/pull/<n>) — got {pr!r}")
        gids = [g for gs in _relsvc._pr_items([pr]).values() for g in gs]
        if not gids:
            raise ToolError(f"Refused: no open item is anchored to {pr}. If an item serves it, anchor the PR to that item "
                            f"(anchors(project, add=[url], items=[id])) and run this again; if none does, {_when_idle()}")
    else:
        gids = [_norm_id(item)]
        if _svcstore._load(gids[0]).get("status") != "open":
            raise ToolError(f"Refused: {gids[0]} is completed; a recycle waits on an open item. If no open item covers the change, {_when_idle()}")
    done = []
    with _RECYCLE_DUE_LOCK:
        for g in gids:
            it = _svcstore._load(g)
            action = "already" if _hooks().rmod_waits_recycle(it) else "set"
            if action == "set":
                _update_svc._update(g, recycle=True, sender=f"a script on {machine}")   # the script's write, not the owner's (the History names it)
                it = _svcstore._load(g)
            done.append({"item": g, "action": action, "held": _holders._is_held(it) or _item_read._date_parked(it), "owner": _sr._session_label(_telling.holder(it)),
                         "needs": [_hooks().shown_ref(x) for x in _needs_sessions(it.get("metadata") or {})]})
    return {"items": done, "pr": pr}
