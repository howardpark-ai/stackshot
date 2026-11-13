"""event_waits.py: the waits on a fleet event: an event that is reported or read ends the wait and turns the item.

An item whose mover waits on something the fleet does in the background (a pull request's release or merge, a recycle, a fleet operation, a job's run, a machine coming online) stores that wait; the server is told of the
event (`evwait_report`, `evwait_hook`) or reads it (the poll `evwait_poll`, at the done check's pace) and the watchers turn the item to its post-wake mover with what happened (`watching.watch_fire`). An open event
wait is a watched wait, so the stall pass does not run for it, and its backstop day brings the item back if the event never came. The machine anchors' pass (`machine_anchor_poll`) runs with the poll: it tells the mover
of an item a machine anchor counts for when that machine checks in again, and turns nothing.

The memory of the pull-request reads (`EVW_GH`, `EVW_SEEN`, `EVW_POLLED`, `EVW_LAST`) lives here and is read by the write gate that stays in server.py (it makes no GitHub call under the item lock, only reads what the
early read stored). The phrases and what matches them are the domain's (waits/event_waits.py); the git and GitHub readers the poll shares with the release sweep and the done check are reached through `Hooks` in
service/wake_hooks.py. Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import datetime as dt
import sys
import time
from typing import Any, Callable

from fastmcp.exceptions import ToolError

from stackshot.anchors import machine_anchor as _ma
from stackshot.core import config as _cfg
from stackshot.core import ghbudget as _gb
from stackshot.core.store import _item_files
from stackshot.fleet import clients as _clients
from stackshot.fleet import liveness as _lv
from stackshot.github import ghsync as _gh
from stackshot.model import model as _model
from stackshot.model import steps as _steps
from stackshot.service import stall as _stallsvc
from stackshot.service import telling as _telling
from stackshot.service import watching as _watching
from stackshot.service.store import _legacy_hold, _load
from stackshot.service.wake_hooks import hooks as _hooks
from stackshot.waits import event_waits as _ew
from stackshot.waits import wait_list as _wl
from stackshot.waits import watchers as _watch


# ----------------------------------------------------------------------------- waits on a fleet event (wait_kind=event; event_waits.py has the phrases)
# An item whose mover waits on something the fleet does in the background (a PR's release, a recycle, a fleet op, a job's run) stores that wait: the server is told of the event (a release's
# report, the fleet tool's end-of-recycle hook, client.py event) or reads it (a PR merged on GitHub, at the done check's pace) and turns the item to its post-wake mover with what happened. An open event wait
# is a watched wait (watchers.watches), so the stall pass does not run for it; its backstop date brings the item back if the event never came.
_EVW_EVERY = 60.0                      # seconds between catch-up passes; the runner calls it every 60 s
EVW_LAST = [0.0]
EVW_SEEN: list[Any] = [None]          # ((last-good, HEAD), the PR numbers pr_released waits name) of the last catch-up pass that found nothing due
EVW_GH: dict[str, Any] = {}           # _pr_merged's answers for the pull requests event waits name (in memory: a restart reads each once); the write gate's early read (a request thread) and the catch-up (the runner) both use it
EVW_POLLED: set[str] = set()          # the keys the catch-up read on its last pass: only these are dropped when no wait names them any more (a key the early read just stored is not the catch-up's to drop)



def evw_merge(good: str, n: int) -> tuple[str, float] | None:
    """Pull request #n's merge commit in `good` (its first-parent merges, read once per commit: _proof_git) → (sha, commit time), None when `good` holds no merge of it."""
    return _hooks().proof_git(("prs", good), lambda: _hooks().merged_prs(good)).get(n) if good else None


def evw_live_why(sha: str, good: str, head: str) -> str:
    """_released_is_live, kept by commit (_proof_git): "" when merge `sha` is passed and live."""
    return _hooks().proof_git(("live", good, head, sha), lambda: _hooks().released_is_live(sha, good, head))


def evw_boxes() -> dict[str, tuple[str, dict[str, Any]]]:
    """The machines a box_online wait may name: lower-cased hostname or fleet name → (fleet name, the machine's record in the clients state, {} while it has never checked in). The union of the names
    table (paths.fleet_names) and the machines the server holds a record of, read from files (no network)."""
    out: dict[str, tuple[str, dict[str, Any]]] = {}
    machines = _clients.load().get("machines")
    best: dict[str, tuple[str, dict[str, Any]]] = {}        # fleet name (lower-cased) → the record with the newest check-in: two records of one fleet name are one machine, and a stale one must not speak for it
    hosts: list[tuple[str, str]] = []
    for host, rec in (machines.items() if isinstance(machines, dict) else ()):        # a state that is not a table of records knows no machine
        if not isinstance(rec, dict):
            continue
        fleet = str(rec.get("fleet") or host)
        hosts.append((str(host).lower(), fleet.lower()))
        if fleet.lower() not in best or _lv.ts(rec.get("puller")) > _lv.ts(best[fleet.lower()][1].get("puller")):
            best[fleet.lower()] = (fleet, rec)
    for host, fkey in hosts:
        out[host] = out[fkey] = best[fkey]
    for key, (fleet, _letter) in _clients.names_table().items():          # a machine the table names that has not checked in yet is known, and offline
        out.setdefault(key, (fleet, out.get(fleet.lower(), (fleet, {}))[1]))
    return out


def evwait_report(ev: dict[str, Any], now: float | None = None, told: dict[str, str] | None = None) -> list[str]:
    """The server was told of (or read) an event: every open item whose stored wait is an event wait that this event ends turns to its post-wake mover, with what happened on it, and each recipient
    gets one message. A reported event (recycle, fleet op, job run) counts only when it is newer than the wait (the item's last move and `watch.set_at`: an older event is not its arrival); a pull
    request's merge or release is a state, so a wait set after it is refused at the write and one that was missed is caught up. Nothing while paused or switched off. `told` ({gid: session id}):
    the items a release's step notice (_proof_item) already told about this event; the same session is not told again by the wake. → the gids turned."""
    if not _watch.enabled() or _watch.paused():
        return []
    now = time.time() if now is None else now
    out: dict[str, list[tuple[str, dict[str, Any], str]]] = {}
    fired: list[str] = []
    for gid, _p in _item_files():
        try:
            it = _load(gid)
            m = it.get("metadata") or {}
            if _watch.stored_kind(m) == _wl.LIST and _watch.watches(it):          # a wait on a list: every open event line this event answers is marked
                hits = lambda meta: _wl.lines_for_event(meta, lambda ph: _ew.matches(_watching.event_spec(ph), ev))
                if hits(m) and not (ev.get("kind") in _ew.REPORTED and now <= _watching.watch_floor(it)) and _watching.watch_mark(gid, "event", now, out, hits, _ew.arrival(ev), ev=ev):
                    fired.append(gid)
                    print(f"event wait: {gid} turned ({_ew.arrival(ev)})", file=sys.stderr, flush=True)
                continue
            if _watch.stored_kind(m) != "event" or not _watch.watches(it):
                continue
            try:
                sp = _watching.event_spec(m.get("wait_event"))
            except _ew.EventWaitError:
                continue
            if not _ew.matches(sp, ev):
                continue
            if ev.get("kind") in _ew.REPORTED and now <= _watching.watch_floor(it):
                continue
            if _watching.watch_fire(gid, "event", now, out, {"what": _ew.arrival(ev)}, ev=ev):
                fired.append(gid)
                print(f"event wait: {gid} turned ({_ew.text(sp)})", file=sys.stderr, flush=True)
        except Exception as e:  # noqa: BLE001  — one bad item never stops the others
            print(f"event wait: {gid} not read for an event: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    for sid, rows in out.items():
        rows = [r for r in rows if (told or {}).get(r[0]) != sid]      # the release's step notice already reached this session about this item: one notice, not two
        if rows:
            _watching.watch_tell(sid, rows)
    if fired:
        _hooks().publish()
    return fired



def _evwait_pr_event(kind: str, repo: str, n: int, what: str = "") -> dict[str, Any]:
    return _ew.event(kind, f"{_cfg.canon_repo(repo)}#{n}", what=what)


def event_specs(it: dict[str, Any]) -> "list[_ew.Spec]":
    """The event specs a watched wait of this open item stands on: an event wait's one, or those of the event lines of a wait on a list that have not arrived (a line whose phrase is no event is left out).
    [] for any other wait. The pollers (a machine coming online, a pull request's merge or release) look for these."""
    m = it.get("metadata") or {}
    if not _watch.watches(it):
        return []
    k = _watch.stored_kind(m)
    if k == "event":
        return [_watching.event_spec(m.get("wait_event"))]
    out = []
    if k == _wl.LIST:
        ls = _wl.lines(m)
        for i in _wl.lines_by_kind(m, "event"):
            try:
                out.append(_watching.event_spec(ls[i]["event"]))
            except _ew.EventWaitError:
                continue
    return out


def evwait_box_poll(now: float, told: dict[str, str], turned: set[tuple[str, str]] | None = None) -> list[str]:
    """The pass for box_online waits, which are a state like a pull request's merge: each open wait whose machine is online now (its puller checked in within [client] online_minutes) turns its item to
    its post-wake mover, with the machine named (`turned`, when given, collects (gid, lower-cased fleet name) of each wait that turned: the machine anchors skip exactly those pairs). A wait set while the machine was online is refused at the write, so a wait that is open and finds its machine online means the machine came back. → the gids turned."""
    waits: list[tuple[str, "_ew.Spec"]] = []
    for gid, _p in _item_files():
        try:
            it = _load(gid)
            m = it.get("metadata") or {}
            for sp in event_specs(it):
                if sp.kind == _ew.BOX_ONLINE:
                    waits.append((gid, sp))
        except Exception:  # noqa: BLE001
            continue
    fired: list[str] = []
    for machine in sorted({sp.machine.lower() for _g, sp in waits}):
        try:
            hit = evw_boxes().get(machine)
            if hit and hit[1] and _lv.puller_online(hit[1], now):
                got = evwait_report(_ew.event(_ew.BOX_ONLINE, machine=hit[0], what=f"{hit[0]} is online again: its puller checked in"), now, told)
                fired += got
                if turned is not None:
                    turned.update((g, hit[0].lower()) for g in got)
        except Exception as e:  # noqa: BLE001  — one machine's read never stops the others
            print(f"event wait: box_online {machine} not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return fired


def evwait_poll(now: float | None = None, told: dict[str, str] | None = None) -> list[str]:
    """The catch-up pass of the event waits that are states: a machine coming online (evwait_box_poll) and the pull-request events (_evwait_poll_prs). → the gids turned."""
    if not _watch.enabled() or _watch.paused():
        return []
    now = time.time() if now is None else now
    told = _hooks().told_recent() if told is None else told
    turned: set[tuple[str, str]] = set()
    fired = evwait_box_poll(now, told, turned)
    machine_anchor_poll(now, turned)        # a notice only: no item turns, so nothing is added to the gids this returns
    return fired + _evwait_poll_prs(now, told)


def _evwait_poll_prs(now: float, told: dict[str, str]) -> list[str]:
    """The catch-up for the pull-request events, which are states: an event wait on a PR's release or merge whose event happened while the server was down or was not told (the release hook is best
    effort) turns now. pr_released reads the checkout (last-good and HEAD, as sweep-released does; a [released.repos] repository's checkout HEAD); pr_merged reads GitHub at the done check's pace (_pr_merged). → the gids turned."""
    if not _watch.enabled() or _watch.paused():
        return []
    now = time.time() if now is None else now
    told = _hooks().told_recent() if told is None else told      # the sessions a step notice reached lately about an item: the wake does not tell them again
    waits: list[tuple[str, "_ew.Spec"]] = []
    for gid, _p in _item_files():
        try:
            it = _load(gid)
            m = it.get("metadata") or {}
            for sp in event_specs(it):
                if sp.kind in _ew.PR_KINDS:
                    waits.append((gid, sp))
        except Exception:  # noqa: BLE001
            continue
    if not waits:
        for k in list(EVW_POLLED):
            EVW_GH.pop(k, None)
        EVW_POLLED.clear()
        return []
    fired: list[str] = []
    own = _cfg.canon_repo(_hooks().own_repo())
    rel: tuple[str, str] | None = None
    named = frozenset(_ew.pr_number(sp) for _g, sp in waits if sp.kind == _ew.PR_RELEASED and sp.key.rpartition("#")[0] == own)
    if named:
        try:
            rel = _hooks().released_live_base()
        except ToolError:
            rel = None
    if rel is not None and (rel, named) == EVW_SEEN[0]:      # last-good, HEAD and the PRs waited for are as the last pass left them, and nothing was due then: the git answers are the same
        rel = None
    elif rel is not None:
        EVW_SEEN[0] = (rel, named)
    seen: set[str] = set()
    for gid, sp in waits:
        try:
            n = _ew.pr_number(sp)
            repo = sp.key.rpartition("#")[0]
            if sp.kind == _ew.PR_RELEASED:
                fhit = _hooks().foreign_prs(repo)[1].get(n) if repo != own and _hooks().released_foreign(repo) is not None else None      # a [released.repos] repository: a merge in its checkout's HEAD is live
                hit = fhit or (evw_merge(rel[0], n) if rel is not None and repo == own else None)
                if fhit:
                    fired += evwait_report(_evwait_pr_event(_ew.PR_RELEASED, repo, n, f"{_hooks().pr_shown(sp.key)} is live: merged at {fhit[0][:7]} on {_stallsvc.stall_when(fhit[1])}, in the checkout"), now, told)
                elif hit and not evw_live_why(hit[0], rel[0], rel[1]):
                    sha, ct = hit
                    EVW_SEEN[0] = None
                    fired += evwait_report(_evwait_pr_event(_ew.PR_RELEASED, own, n, f"PR #{n} is live: merged at {sha[:7]} on {_stallsvc.stall_when(ct)} and passed main's full run"), now, told)
                elif not hit:                      # not merged into last-good (yet): a pull request closed without a merge never will be
                    seen.add(_hooks().check_ref(sp.key))
                    with _gb.tag("event_wait"):
                        _hooks().pr_merged(sp.key, now, EVW_GH)
                    rec = EVW_GH.get(_hooks().check_ref(sp.key)) or {}
                    if rec.get("dead"):
                        fired += evwait_report(_evwait_pr_event(_ew.PR_RELEASED, repo, n, f"{sp.key} {rec['dead']}, so it will never be released"), now, told)
                continue
            seen.add(_hooks().check_ref(sp.key))
            with _gb.tag("event_wait"):
                merged, _err = _hooks().pr_merged(sp.key, now, EVW_GH)
            rec = EVW_GH.get(_hooks().check_ref(sp.key)) or {}
            if merged:
                fired += evwait_report(_evwait_pr_event(_ew.PR_MERGED, repo, n), now, told)
            elif rec.get("dead"):
                fired += evwait_report(_evwait_pr_event(_ew.PR_MERGED, repo, n, f"{sp.key} {rec['dead']}, so it will never merge"), now, told)
        except Exception as e:  # noqa: BLE001
            print(f"event wait: {gid} {sp.kind} not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    for k in list(EVW_POLLED - seen):         # a copy, and only what an earlier pass read: the early read may be storing a key meanwhile
        EVW_GH.pop(k, None)
    EVW_POLLED.clear()
    EVW_POLLED.update(seen)
    if len(EVW_GH) > 2000:                    # keys only the early read stored (a wait written and dropped) are bounded here
        for k in list(EVW_GH):
            if k not in seen:
                EVW_GH.pop(k, None)
    return fired


def evwait_tick() -> list[str]:
    """The runner's clock for event waits (at most once a minute): the catch-up of the pull-request events."""
    now = time.time()
    if now - EVW_LAST[0] < _EVW_EVERY:
        return []
    EVW_LAST[0] = now
    return evwait_poll(now)



def machine_state(name: str, boxes: "dict[str, tuple[str, dict[str, Any]]] | None" = None) -> tuple[str, float, bool, list[str]]:
    """A machine name (fleet name or hostname) as the machine anchors read it: (the fleet name, the stamp of its latest check-in from offline (the record's `online_since`; 0 while it has never
    checked in), whether it is online now, every name a step may call it by: the fleet name and the hostnames); ("", 0, False, []) for none."""
    boxes = evw_boxes() if boxes is None else boxes
    hit = boxes.get(str(name).lower())
    if not hit:
        return "", 0.0, False, []
    fleet, rec = hit[0], hit[1] or {}
    return fleet, _lv.ts(rec.get("online_since")), bool(rec and _lv.puller_online(rec)), [k for k, (f, _r) in boxes.items() if f.lower() == fleet.lower()]


def machine_anchor_poll(now: float, skip: set[tuple[str, str]]) -> list[str]:
    """The machine anchors' pass (machine_anchor.py), run with the event waits' minute: a machine whose puller checked in again since the last notice (its record's `online_since` newer than the mark in
    state/machine-anchor.json) tells the mover of each open item a machine anchor counts for, once per check-in, in one message per mover that names the machine, the items and the step. Nothing
    turns or is saved on the item. Not told: an (item, machine) pair in `skip` (a box_online wait on that machine turned the item in this pass and told its mover; its other machines are still told), an item with its own box_online wait on that machine, an item the owner
    moves or will move when its wait ends, and, under a project-wide anchor, an item none of whose open steps names the machine. Closed items leave the scopes. The mark moves on even when nobody is told. → the gids told."""
    try:
        with _ma.LOCK:
            store = _ma.load()
            if not store:
                return []
            if _ma.prune(store, lambda g: (_hooks().load_or_none(g) or {}).get("status") == "open"):
                _ma.save(store)
        boxes = evw_boxes()
        news: dict[str, tuple[str, float]] = {}
        with _ma.LOCK:                      # the marks are read, changed and saved under the lock the anchors tool's seed() takes: a stale snapshot never overwrites a freshly raised mark
            marks, moved = _ma.seen_load(), False
            for m in sorted({e["machine"] for es in store.values() for e in es}, key=str.lower):
                fleet, since, _on, _names = machine_state(m, boxes)
                if not fleet:
                    continue
                if m.lower() not in marks:      # no mark (the state was lost): what is past is not told
                    marks[m.lower()], moved = since, True
                elif since > marks[m.lower()]:
                    news[m.lower()], marks[m.lower()], moved = (fleet, since), since, True
            if moved:
                _ma.seen_save(marks)
        if not news:
            return []
        out: dict[str, list[tuple[str, str, str, str]]] = {}      # session id → [(machine, gid, subject, step)]
        for gid, _p in _item_files():
            try:
                it = _load(gid)
                meta = it.get("metadata") or {}
                if it.get("status") != "open":
                    continue
                hits = [(k, scoped) for k, (_n, scoped) in _ma.counts(store, gid, str(meta.get("project") or "")).items() if k in news and (gid, k) not in skip]
                if not hits:
                    continue
                who, _alive = _hooks().item_mover_model(it)
                sid = _hooks().session_id(_telling.holder(it))
                if _model.is_owner(who) or not sid:
                    continue                  # the owner moves it now (alive) or takes it when its wait ends (waiting): an agent-facing notice never stands in for his queue
                own = _watching.event_spec(meta.get("wait_event")) if _watch.stored_kind(meta) == "event" else None
                steps = [_steps.first_line(s["text"])[:140] for s in _steps.view(meta, keeper=str(meta.get("owner") or "")) if s["status"] == _steps.OPEN]
                for k, scoped in hits:
                    fleet = news[k][0]
                    if own is not None and own.kind == _ew.BOX_ONLINE and machine_state(own.machine, boxes)[0].lower() == fleet.lower():
                        continue                  # its own box_online wait on this machine tells its mover when the wait ends
                    step = next((t for t in steps if _ma.names_in(t, machine_state(fleet, boxes)[3])), "")
                    if scoped or step:
                        out.setdefault(sid, []).append((fleet, gid, str(it.get("subject") or ""), step or (steps[0] if steps else "")))
            except Exception as e:  # noqa: BLE001  — one item never stops the others
                print(f"machine anchor: {gid} not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        told: list[str] = []
        for sid, rows in out.items():
            for fleet in dict.fromkeys(r[0] for r in rows):
                mine = [r for r in rows if r[0] == fleet]
                at = dt.datetime.fromtimestamp(news[fleet.lower()][1], _hooks().zone()).strftime("%H:%M %Z") if news[fleet.lower()][1] else ""
                _telling.tell_woken(",".join(r[1] for r in mine), sid, _ma.notice(fleet, at, [(_gh.shown(g), subj + (f" (step: {step})" if step else ""), _telling.notice_link(g)) for _f, g, subj, step in mine]), tag="watch")
                told += [r[1] for r in mine]
                print(f"machine anchor: {fleet} checked in: {', '.join(r[1] for r in mine)} told to {sid}", file=sys.stderr, flush=True)
        return told
    except Exception as e:  # noqa: BLE001  — a pass that fails never stops the event waits' pass
        print(f"machine anchor: pass failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return []



def evwait_hook(kind: str, repo: str, n: int, what: str = "", told: dict[str, str] | None = None) -> None:
    """A release or a merge the server just settled, told to the event waits that wait for it. A failure is a stderr line: the catch-up poll finds the wait again."""
    try:
        evwait_report(_evwait_pr_event(kind, repo, n, what), told=told)
    except Exception as e:  # noqa: BLE001
        print(f"event wait: {kind} #{n} not reported: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
