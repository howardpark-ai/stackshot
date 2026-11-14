"""page_debt.py: the page-debt call, the audit run's pages stage.

The 30-minute move of a page debt to the keeper (`pilot_fallback_tick`) becomes one thin call per page per audit run ([router] page_debt, router/page_debt.py): it is given the items of the debts that moved and
the page's Current state and proposes the smallest edit. Shadow (the default): the proposal is only logged, <state>/router/page_debt.jsonl, and the old relay (held for the router while it is live, else the keeper's)
stays as it is. Live ([router] page_debt_shadow = false): the edit is applied with a revision-checked put and the debts settled; what cannot be applied (the call said "cannot", an answer that does not parse, a
failed or slow call, an old_text that does not match, a refused put, a put that timed out and whose read back shows no edit) goes to the agent that keeps the page (its own `agent:`), else the project's builder, else
its -main agent, as a page-update notice in the words of today's relay, and the debt is theirs from then on. A put that timed out is read back first: a page that shows the edit counts as written.

`page_debt_pass` is the pass `POST /client/page-debt` asks for; the route stays in web/server.py. The ledger of the debts, the grace minutes, the session ids and the page agents of a project are still the surface's:
they come through `Hooks` in service/passes_hooks.py, looked up when the pass runs. A suite that replaces a function or the clock of the pass sets it here (and `time` here, since this module reads its own).

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import datetime as dt
import sys
import threading
import time
from typing import Any

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core.instance import OWNER
from stackshot.fleet import liveness as _lv
from stackshot.fleet import sessions_registry as _sr
from stackshot.fleet.sessions_registry import _sessions_index
from stackshot.github import ghsync as _gh
from stackshot.model import said as _said
from stackshot.model.needs import _needs_of
from stackshot.projects import brains as _brains
from stackshot.router import page_debt as _page_debt
from stackshot.router import router_live as _router_live
from stackshot.router import routing as _routing
from stackshot.service import store as _svcstore
from stackshot.service import telling as _telling
from stackshot.service.passes_hooks import hooks as _hooks
from stackshot.service.store import _load

_FOR_OWNER = f"[for {OWNER}]"      # the mark a message to a front agent carries on its first line ("[for <owner>]" on the owner's instance), as server.py holds it


PAGE_DEBT_LOCK = threading.Lock()


def clean_line(s: Any, n: int = 200) -> str:
    return " ".join(str(s or "").split())[:n]


def page_debt_item(gid: str, what: str) -> dict[str, Any]:
    """An item as the call is shown it: subject, state, description, next, needs, ask, outcome and the last few `said` lines."""
    try:
        it = _load(gid)
    except Exception:
        return {"id": _gh.shown(gid), "change": what, "subject": "(the item could not be read)"}
    meta = it.get("metadata") or {}
    said = [f"{e['tag']}: {' '.join(e['quote'].split())[:240]}" for e in _said.entries_of(meta)[-5:] if e.get("quote")]
    row = {"id": _gh.shown(gid), "subject": str(it.get("subject") or "")[:200], "status": str(it.get("status") or ""), "change": what,
           "description": str(it.get("description") or "")[:800], "next": str(meta.get("next") or "")[:600], "needs": _hooks().shown_needs(_needs_of(meta)),
           "ask": str(meta.get("ask") or "")[:300], "outcome": str(meta.get("outcome") or ""), "reason": str(meta.get("reason") or "")[:300], "said": said}
    return {k: v for k, v in row.items() if v not in ("", [], None)}


def page_debt_forget(key: str, moved: dict[str, dict[str, Any]], keeper: str = "", now: float = 0.0) -> None:
    """Drop the moved debts the call took (each only while it is still the entry it read); `keeper` set = the debt becomes that agent's."""
    with _hooks().owed_lock():
        d = _hooks().owed_load(); last = ""; settle = ""
        for o, e in moved.items():
            cur = d.get(key, {}).get(o)
            if cur and cur.get("ts") == e.get("ts"):
                del d[key][o]
            last = str(e.get("item") or last)
            settle = "ct" if "ct" in (e.get("settle"), settle) else str(e.get("settle") or settle)
        if key in d and not d[key]:
            del d[key]
        if keeper:
            d.setdefault(key, {})[keeper] = {"ts": now or time.time(), "item": last, **({"settle": settle} if settle else {})}
        _hooks().owed_save(d)


def page_agent(key: str) -> str:
    """The agent that keeps the page `key` as its own working document: the registry's entry for the page, when its frontmatter names an
    `agent:` (pages.keeper_of: role "agent", the entry's `session`; anchors.registry), and that session is live (a heartbeat in the fleet's
    sessions index, by name or id, not marked gone; project_keeper reads the same entry for the item notices). A project page names a `display-name:` and
    a sub-page that names nobody belongs to its keeper, so neither has one → "" ."""
    try:
        e = _anc.registry().get(str(key or "").strip().strip("/")) or {}
        name = str(e.get("session") or "").strip()
        if e.get("role") != "agent" or not name:
            return ""
        sid = _hooks().session_id(name)
        idx = _sessions_index()
        return name if any(_lv.running(r) and (k == sid or str(r.get("name") or "") == name) for k, r in idx.items()) else ""
    except Exception:
        return ""


def page_debt_fallback(key: str, moved: dict[str, dict[str, Any]], debts: list[tuple[str, str, str]], why: str, now: float) -> str:
    """The debts the call did not settle go, in one message with the rows as today's relay writes them, to the agent that keeps the page
    (page_agent: the page's own `agent:`, when live), else the project's builder (a background agent whose mandate builds), else its -main
    agent (anchors.fallback_main: its project's, else the scope's general -main agent); with none of them the debts stay moved, for the next audit run's call.
    The [for <owner>] mark is on the message only when that agent is a front one (a -main or other top-level `agents:` entry,
    whose pane takes a peer's message only with it); a background agent gets the plain text. → who was told."""
    own = page_agent(key)
    main = _hooks().main_agent(key)
    builder = _hooks().builder_agent(key)
    keeper = own or builder or main
    if not keeper:
        return ""         # nobody can take them: they stay moved, and the next audit run's call tries again
    front = _telling.front_keeper(own, key)[0] if own else (not builder and bool(main))      # the -main agent is front by construction; a builder and the keeper fallback are not
    rows = []
    for gid, what, writer in debts:
        try:
            item = _load(gid)
        except Exception:
            item = {}
        rows.append((key, gid, item, what, writer))
    n = len(rows); s, are, them = ("s", "are", "them") if n != 1 else ("", "is", "it")
    head = ((_FOR_OWNER + " ") if front else "") + (
            f"[board] {n} page update{s} on {key} {are} yours to write: the writer{s} left {them} undone past {_hooks().grace_min()} min and the "
            f"audit's page call could not write {them} ({clean_line(why, 200)}). "
            + ("Write the Current state: you keep this page." if own else "Write the Current state, or hand it to the agent that keeps the page."))
    if keeper and rows:
        for nid in _telling.pilot_relay_many(keeper, rows, head=head):
            if own or builder or main:      # the notices went to the page's agent, the builder or the -main agent, which has no `route`: ruled passed at once, so nothing is left unruled
                try:
                    _routing.rule(nid, "passed", to=keeper, by=_routing.AUTO_RULER,
                                  reason="the audit's page call could not write the page update: passed to " + ("the agent that keeps the page" if own else "the builder" if builder else "the -main agent"))
                except Exception:
                    pass
    page_debt_forget(key, moved, keeper, now)
    return keeper


PAGE_DEBT_READ_WHAT = "the audit's page call skips its pages this run"


def page_debt_project(key: str, moved: dict[str, dict[str, Any]], now: float, mode: str, runner: Any = None, io: Any = None) -> str:
    """One page's debts, one call. → the result: proposed · would_fall_back (shadow) · applied · fallback (live)."""
    live = mode == "live"
    debts: list[tuple[str, str, str]] = []
    for o, e in moved.items():
        for x in (e.get("debts") or [{"item": e.get("item") or "", "what": "changed", "writer": o}]):
            t = (str(x.get("item") or ""), str(x.get("what") or "changed"), str(x.get("writer") or o))
            if t not in debts:
                debts.append(t)
    items = [page_debt_item(g, w) for g, w, _ in debts]
    line: dict[str, Any] = {"ts": now, "project": key, "mode": mode, "call": "", "items": [_gh.shown(g) for g, _w, _o in debts], "status": "none",
                            "proposal": None, "applies": None, "result": "", "why": "", "to": "", "usage": {}, "cost_usd": None, "duration_s": 0.0}
    gb = io if io is not None else (_page_debt.page_io() if live else None)
    content, rev = (gb.get(key) if live else (_page_debt.read_mirror(key), None))
    why, res, edits, new = "", None, None, None
    kb = _brains.for_key(key)
    if (content is None or (live and not rev)) and not kb.default:
        # a second brain's copy or gbrain CLI did not give the page: skipped for this run, said once, never a fallback to an agent
        first = _brains.warn_once(kb, "the page " + key + " could not be read" + (" through its gbrain CLI" if live else " from its local copy"),
                                  PAGE_DEBT_READ_WHAT, channel=PAGE_DEBT_READ_WHAT + " " + key)   # a channel per page: another page reading fine is no recovery of this one
        if first:       # the call retries at each audit run while the outage lasts: one log line per outage, not one per run
            line.update(result="skipped", why=f"second brain {kb.name}: the page could not be read")
            _page_debt.log(line)
        return "skipped"
    if content is None or (live and not rev):
        why = "the page could not be read"
    else:
        if not kb.default:
            _brains.clear(kb, PAGE_DEBT_READ_WHAT + " " + key)     # this page reads again: with no read of the brain failing, one line says it is back
        res = _page_debt.call(key, items, content, runner)
        line.update(call=res["call"], status=res["status"], proposal=res["proposal"], usage=res["usage"], cost_usd=res["cost_usd"], duration_s=res["duration_s"])
        why = res["why"]
        if res["kind"] == "edits":
            new, bad = _page_debt.apply_edits(content, res["proposal"]["edits"])
            if new is None:
                why = bad
            else:
                edits = res["proposal"]["edits"]
    line["applies"] = edits is not None
    if not live:
        line.update(result="proposed" if edits is not None else "would_fall_back", why="" if edits is not None else why)
        _page_debt.log(line)
        return line["result"]
    if edits is not None:
        state, msg = _page_debt.put_state(gb.put(key, new, rev))
        if state == "refused":      # an explicit refusal (a stale revision, an error from gbrain): the page was not written, nothing to read back
            line["applies"], why = False, "the page write was refused: " + msg
        else:
            # "ok" = gbrain said so; "unknown" = the put timed out or failed in a way that leaves it open whether it landed: either way the page
            # is read back, and only a page that shows the edit counts as written
            back, _rev2 = gb.get(key)
            if back is not None and _page_debt.verify(back, edits):
                page_debt_forget(key, moved)
                line.update(result="applied", why="the page write got no answer (" + msg + "), but a read back shows the edit: taken as written" if state == "unknown" else "")
                _page_debt.log(line)
                return "applied"
            line["applies"] = False
            why = ("the page write got no answer (" + msg + ") and a read back does not show the edit: check the page" if state == "unknown"
                   else "the page was written, but a read back does not show the edit: check the page")
    line.update(result="fallback", why=why, to=page_debt_fallback(key, moved, debts, why, now))
    _page_debt.log(line)
    return "fallback"


def page_debt_pass(now: float | None = None, runner: Any = None, io: Any = None, run: str = "", deadline: float | None = None) -> dict[str, int]:
    """The pass the audit run's pages stage asks for (POST /client/page-debt): every page with debts that moved to its keeper and are still
    unsettled gets one call. `run` names the audit run (its start stamp): a mark per page, run and mode, in <state>/router/page_debt_day.json,
    is written before the call, so a page is called once per run, a crash never repeats it within the run, and switching shadow to live calls
    again; a pass with no `run` marks by the local day. `deadline` (an epoch) is the end of the run's time budget: no page is begun after it, and
    the pages left get no mark, so the next run calls them. A page whose call raises is counted as `error` and the pass goes on to the next.
    → {pages, left, <result>: n}; {} when [router] page_debt is off (nothing runs)."""
    if not _page_debt.enabled():
        _brains.clear_unvisited(PAGE_DEBT_READ_WHAT + " ", set())     # nothing reads any more: no page holds a brain in an outage
        return {}
    now = time.time() if now is None else now
    local = dt.datetime.fromtimestamp(now, _cfg.tz())
    out: dict[str, int] = {"pages": 0}
    with PAGE_DEBT_LOCK:
        mode = _page_debt.mode(); mark = f"{run or f'{local:%Y-%m-%d}'}:{mode}"
        days = _page_debt.read_days()
        d = _hooks().owed_readable(_hooks().owed_settle())
        # a page whose debts are settled, renamed or gone is not visited again, so it can never report that it reads: drop its failing read
        _brains.clear_unvisited(PAGE_DEBT_READ_WHAT + " ", {k for k, v in d.items() if any(e.get("moved") for e in v.values())})
        for key in sorted(d):
            moved = {o: e for o, e in d[key].items() if e.get("moved")}
            if not moved or days.get(key) == mark:
                continue
            if deadline is not None and time.time() >= deadline:      # the run's time is spent: this page waits for the next run
                out["left"] = out.get("left", 0) + 1
                continue
            prev = days.get(key)
            days[key] = mark
            _page_debt.write_days(days)
            out["pages"] += 1
            try:
                r = page_debt_project(key, moved, now, mode, runner, io)
            except Exception as e:  # noqa: BLE001 — one page's failure is that page's: the mark stays (no repeat in this run), the pass goes on
                print(f"page-debt call for {key} failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
                r = "error"
            out[r] = out.get(r, 0) + 1
            if r == "skipped":      # a second brain's page could not be read (its CLI failed): no mark for this run, so the next run tries again
                if prev is None:
                    days.pop(key, None)
                else:
                    days[key] = prev
                _page_debt.write_days(days)
    return out


def _pilot_fallback_tick(now: float | None = None) -> int:
    """a writer's pilot debt still unsettled past [page_rule] grace_minutes moves to the keeper: re-marked to the keeper,
    dropped from the writer, and the keeper gets the board notice saying who left it undone. The turn rule's fourth build:
    the debts that move to one keeper in the same tick go in one message (pilot_relay_many); one alone
    keeps its old text. Batching never waits: a debt moves at the first tick past the grace, as before, with whatever else
    is due for that keeper in that tick. → how many moved."""
    now = time.time() if now is None else now
    with _hooks().owed_lock():
        d = _hooks().owed_load()
        if not any(e.get("moves") for os_ in d.values() for e in os_.values()):
            return 0
        d = _hooks().owed_settle(); grace = _hooks().grace_min() * 60; due = []
        for key, os_ in d.items():
            if _hooks().owed_brain_skip(key):       # a second brain that cannot be read: its debts wait where they are for this run
                continue
            for o, e in list(os_.items()):
                if e.get("moves") and now - float(e.get("ts", 0)) > grace:
                    due.append((key, o, e)); del os_[o]
        if not due:
            return 0
        for key, o, e in due:
            stew = str(e["moves"]); prev = d.get(key, {}).get(stew) or {}
            settle = "ct" if "ct" in (e.get("settle"), prev.get("settle")) else str(e.get("settle") or "")
            # `moved` and `debts` (step 3b): the debts that moved here, each with its item, what changed and who left it undone, which the
            # page-debt call (page_debt.page_debt_pass) reads; the keeper's own later debt (_owed_mark) overwrites the entry and so ends the mark
            debts = [*(prev.get("debts") or []), {"item": e.get("item") or "", "what": str(e.get("what") or "changed"), "writer": o}] if prev.get("moved") else \
                    [{"item": e.get("item") or "", "what": str(e.get("what") or "changed"), "writer": o}]
            d.setdefault(key, {})[stew] = {"ts": now, "item": e.get("item") or "", **({"settle": settle} if settle else {}), "moved": True, "debts": debts}
        _hooks().owed_save(d)
    if _page_debt.live():     # step 3b, live: the 30-minute relay to the keeper is the page-debt call's now (page_debt.page_debt_pass)
        return len(due)
    out: dict[str, list[tuple[str, str, dict[str, Any], str, str]]] = {}     # keeper → [(project, gid, item, what, writer)], in the order due
    for key, o, e in due:
        gid = str(e.get("item") or "")
        try:
            item = _svcstore._load(gid)
        except Exception:
            item = {}
        if not _telling.front_keeper(str(e["moves"]), key)[0] or _router_live.holds(key, str(e["moves"])):     # a front agent gets no page-owed notice (as pilot_relay), unless it is only the address of a nameless page's notices: the router's
            out.setdefault(str(e["moves"]), []).append((key, gid, item, str(e.get("what") or "changed"), o))
    for stew, rows in out.items():
        if len(rows) == 1:
            key, gid, item, what, o = rows[0]
            _telling.pilot_relay(key, gid, item, what, o, stew, tail=f"{_sr._session_label(o)} left its page update undone past {_hooks().grace_min()} min, so it is yours as its keeper")
        else:
            _telling.pilot_relay_many(stew, rows)
    return len(due)
