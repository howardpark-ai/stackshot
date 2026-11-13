"""handoff_cold.py: the cold call of the hand-off ladder.

An item whose hand-off nobody took, or that went quiet, can be put to a fresh `claude -p` call: the item and its page's Current state go in, and the answer is one of three, hand to <session>, close with <outcome> or
ask the owner. This module builds the call, runs it in a thread of its own (`handoff_cold`, started by `handoff.handoff_exec`), validates the answer and writes it through the update path as the author `cold-call`.
The stall ladder's cold call is the same call with a narrower offer (hand to a session or close, never ask the owner): `stall_cold_kept` ends it when the answer names the mover the item already has, and
`stall_cold_no_taker` when it names no one. A write the server refuses is made once more (`handoff_write`); refused twice, the fleet's builder is asked to recover the session (`handoff_recover`).

`COLD_RUNNER` is where a test puts a callable that answers in place of a real call, and `HO_COLD_THREADS` holds the calls started (one at a time board-wide; a test joins them). What the call still reaches in
server.py (the update write, the gates and limits a close is held to, the stall pass's state) comes through `Hooks` in service/handoff_hooks.py.

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import sys
import threading
import time
from typing import Any, Callable

from fastmcp.exceptions import ToolError

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core.instance import OWNER
from stackshot.fleet.sessions_registry import _sessions_index
from stackshot.github import ghsync as _gh
from stackshot.model import cold_call as _cold
from stackshot.model import model as _model
from stackshot.model.bullet_text import _clip_line
from stackshot.model.needs import _needs_kinds
from stackshot.projects import pages as _pages
from stackshot.router import page_debt as _page_debt
from stackshot.router import router as _router
from stackshot.service import handoff as _handoff
from stackshot.service import telling as _telling
from stackshot.service import writes as _writes
from stackshot.service.handoff_hooks import hooks as _hooks
from stackshot.service.store import _load, _shown_ids
from stackshot.waits import handoff as _ho
from stackshot.waits import ladder as _ladder
from stackshot.waits import stall as _stall


HO_COLD_THREADS: list[threading.Thread] = []       # the cold calls started (a test joins them)
COLD_RUNNER: Any = None           # a test puts a callable here: runner(message) -> router.run_call's result dict; None = a real `claude -p`


# ---- the cold call
def handoff_agents(project: str) -> list[dict[str, str]]:
    """The sessions the cold call may hand to: the project's background agents (its hub's page), each with its mandate and whether it has a pane. a front agent is not
    offered; the call's answer is an automatic move, and none goes to a front agent (the ladder then tries the builder, else the fleet's builder is asked to recover the session)."""
    out: list[dict[str, str]] = []
    try:
        reg = _anc.registry()
        roles = _anc.session_roles(reg)
        hub = _anc.hub_of(project, reg)
        idx = _sessions_index()
        for n, r in roles.items():
            if r.get("role") != "back" or _anc.hub_of(r.get("project", ""), reg) != hub or r.get("retired"):
                continue
            mand = str(((reg.get(r.get("project", "")) or {}).get("agents") or {}).get(n) or "")
            out.append({"name": n, "role": "background" if r.get("role") == "back" else "front", "mandate": mand, "live": "" if _handoff.handoff_pane(n, idx) else "yes"})
    except Exception:  # noqa: BLE001
        pass
    return out


def handoff_page_state(project: str) -> str:
    try:
        content, _rev = _hooks().page_io().get(project)
        span = _page_debt.section_span(content or "")
        if span:
            return (content or "")[span[0]:span[1]].strip()
    except Exception:  # noqa: BLE001
        pass
    try:
        return _pages.current_state(project, cap=3000) or ""
    except Exception:  # noqa: BLE001
        return ""


def handoff_cold(gid: str, cold_at: float) -> None:
    """One cold call for one item (a thread of its own): the item and its page's Current state go to `claude -p`, which answers hand to <session> | close with <outcome> | ask
    the owner; the answer is validated and written through the update path as the author `cold-call`. A call that fails ends the cold step and the item goes on down section 5 (the sender, then
    the fleet's builder is asked); an answer the write refuses is written once more (`handoff_write`, each refusal in the journal), and refused twice the fleet's builder is asked, with the refusal text
    (`handoff_recover`), and the item is not returned to its sender. The call takes minutes: before its write the item is read again under the lock and the answer is dropped, quietly (a log
    line), unless the item is still open with the same hand-off record (the cold call's own stamp, `cold_at`, unchanged), not taken, and with the same mover.
    The stall ladder's cold call (the record carries `stall`) never asks <owner>: it is offered hand_to and close only (cold_call.STALL_RUBRIC), an ask_owner, a none, an answer
    it could not give or a write the item refused is never written, and `stall_cold_no_taker` sends the item on to the builder. Never raises."""
    try:
        with _writes.ITEM_LOCK:
            item = _load(gid)
        meta = item.get("metadata") or {}
        rec0 = _ho.record_of(item) or {}
        mover0 = str(rec0.get("to") or "")
        exclude = [x for x in (mover0, rec0.get("from"), rec0.get("origin"), *(rec0.get("tried") or [])) if x and not _model.is_owner(x)]
        stall = bool(rec0.get("stall"))      # the stall ladder's cold call (step 2): it offers hand_to and close only and never asks the owner; no taker → the builder (step 3)
        project = str(meta.get("project") or "")
        agents = handoff_agents(project)
        msg = _cold.build_message(_gh.shown(gid), item, handoff_page_state(project), agents, _cfg.tz(), time.time(), OWNER)
        status, ans, note, res = _cold.run(msg, COLD_RUNNER, stall=stall)
        try:
            _router._append(_router.calls_path(), {"call": "", "kind": "cold_call", "ts": time.time(), "project": project, "item": gid, "status": status, "model": _router.model(),
                                                   "duration_s": res.get("duration_s"), "usage": res.get("usage") or {}, "cost_usd": res.get("cost_usd"), "note": _clip_line(note, 200)})
        except Exception:  # noqa: BLE001  — the log is an extra
            pass
        kept: dict[str, Any] | None = None      # the stall call named the session that already moves the item: it stays with it, and the ladder does not go on to the builder and the owner
        if stall and ans is not None and _cold.names_mover(ans, mover0, _handoff.ho_same):
            kept, ans = ans, None
        if ans is not None:
            ans, note = _cold.validate(ans, {a["name"] for a in agents if a.get("live")}, _handoff.ho_same, exclude,
                                       desc_limits=_hooks().description_limits() if _hooks().bullets_on() else None, gate=(lambda t: _hooks().gate_description(t, "outcome_text")) if _hooks().bullets_on() else None, stall=stall)
        with _writes.ITEM_LOCK:               # the check and the write are one step: nothing writes the item between them
            cur = _load(gid)
            r = _ho.record_of(cur)
            why = ""
            if cur.get("status") != "open":
                why = "it is no longer open"
            elif not r or not isinstance(r.get("cold"), dict) or r["cold"].get("at") != cold_at:
                why = "its hand-off record is no longer the one the call was asked about"
            elif r.get("taken_at"):
                why = "its mover took it meanwhile"
            elif not _handoff.ho_same(r.get("to"), mover0):
                why = "its mover changed"
            if why:
                print(f"handoff: {gid} the cold call's answer was dropped: {why}", file=sys.stderr, flush=True)
                if r and isinstance(r.get("cold"), dict) and r["cold"].get("at") == cold_at:
                    handoff_cold_end(gid, "done", f"the cold call's answer was dropped: {why}", cold_at)
                return
            if kept is not None:
                stall_cold_kept(gid, cold_at, mover0, str(kept.get("reason") or ""))
                return
            if stall and (ans is None or ans["action"] == "none"):
                stall_cold_no_taker(gid, cold_at, note if ans is None else str(ans.get("reason") or ""), failed=ans is None)      # an ask_owner, a none or no usable answer is never written: the builder is next
                return
            if ans is None:
                handoff_cold_end(gid, "failed", f"the cold call gave no usable answer: {note}", cold_at)
                _handoff.handoff_fallback(gid, f"the cold call gave no usable answer ({_clip_line(note, 100)})", cold_ok=False)
                return
            def write() -> None:                         # one attempt, built from the item as it stands now (a retry re-reads it), not as the call began
                cur = _load(gid)
                cmeta = cur.get("metadata") or {}
                if ans["action"] == "hand_to":
                    kinds = [k for k in _needs_kinds(cmeta) if k != "decision"]
                    to_front = _telling.front_keeper(ans["to"], str(cmeta.get("project") or ""))[0]      # a user-facing agent is never named in needs (only a mover): the item goes to it by mover=
                    _hooks().update(gid, needs=[*kinds] if to_front else [*kinds, ans["to"]], sender=_ho.COLD, **({"mover": ans["to"]} if (cmeta.get("mover") or to_front) else {}),
                            **({"clear_needs": True} if to_front and not kinds else {}))      # a stored doing or verifying state stands on a session in needs, and a front agent is never named there: the write drops the state (_state_apply) and the item reads as derived
                elif ans["action"] == "close":
                    _hooks().update(gid, status="completed", outcome=ans["outcome"], reason=_hooks().fit(_shown_ids(ans["reason"]), _hooks().close_reason_max()), outcome_text=ans["outcome_text"], sender=_ho.COLD)     # the model's reason is cut to the limit after its ids are expanded (g7 to board#N, which _update does), never refused
                else:
                    _hooks().update(gid, needs=["decision"], ask=ans["ask"], options=ans["options"], next=f"{OWNER}: answer the ask on the item", clear_next=True, sender=_ho.COLD,    # his item's next is this line alone, as before: the server's own write wipes the others
                            **({"clear_mover": True} if cmeta.get("mover") else {}))      # a stored mover would stay the mover beside decision
            refused, how = handoff_write(gid, f"the cold call's {ans['action']}", write)
            if refused:                                  # refused twice, or an error inside the write: the item is not returned to its sender over a write stackshot's own ladder could not make; the fleet's builder is asked, with the text
                why = f"the cold call's answer ({ans['action']}) {how}: {_clip_line(refused, 160)}"
                if stall:                                # the stall ladder's next step is the builder; the owner is asked only when it cannot take the item either
                    stall_cold_no_taker(gid, cold_at, why, failed=True)
                    return
                handoff_cold_end(gid, "failed", why, cold_at)
                handoff_recover(gid, why)
                return
            handoff_cold_end(gid, "done", f"the cold call: {ans['action']}" + (f" {ans.get('to') or ans.get('outcome') or ''}" if ans["action"] != "ask_owner" else f" ({OWNER})")
                              + (f": {ans['reason']}" if ans.get("reason") else ""), cold_at)
    except Exception as e:  # noqa: BLE001
        print(f"handoff: cold call for {gid} failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        try:
            handoff_cold_end(gid, "failed", f"the cold call failed: {e.__class__.__name__}", cold_at)
            _handoff.handoff_fallback(gid, "the cold call failed", cold_ok=False, cold_at=cold_at)
        except Exception:  # noqa: BLE001
            pass


def stall_cold_kept(gid: str, cold_at: float, mover: str, reason: str) -> None:
    """the stall ladder's cold call named the session that already moves the item as the right one: the item stays with it. Nothing is handed on, the builder is not asked and the owner is not
    asked about (an idle pane is not a lost item: the mover may be waiting on something, and the call has judged the item its own). The cold step ends, the History line says so, the episode is marked
    `kept` (stall.spent: the pass leaves the item alone for a day, or until anyone writes or confirms it), and the mover is told once, with how to store a wait the server watches. Never raises."""
    try:
        now = time.time()
        why = _clip_line(reason, 140)
        with _writes.ITEM_LOCK:
            item = _load(gid)
            r = _ho.record_of(item)
            if item.get("status") != "open" or not r or not isinstance(r.get("cold"), dict) or r["cold"].get("at") != cold_at:
                return
            _ho.end_cold(item, "done", now, "the cold call named its mover as the one to keep it" + (f": {why}" if why else ""))
            meta = item.setdefault("metadata", {})
            _stall.note(meta, now, "the cold call named its mover as the one to keep it" + (f" ({why})" if why else "") + ": left with it")
            _writes.save(gid, item, note="stall: the cold call kept it with its mover")
            ver, conf = _hooks().stall_ver(item), _hooks().stall_confirm(item, mover)
            untaken = float(r.get("at") or 0) if r and not r.get("taken_at") else None
            project = str(meta.get("project") or "")
            subject = str(item.get("subject") or "")
        with _hooks().stall_lock():
            st = _hooks().stall_load()
            rec = _ladder.episode(st.get(gid), mover, ver, _handoff.ho_same, conf, untaken)      # on the one ladder it stays there (`via`), and the ask is not sent again
            rec["kept"] = now
            st[gid] = rec
            _hooks().stall_save(st)
        if not _telling.front_keeper(mover, project)[0]:          # no item notice wakes a front agent
            _telling.tell_woken(gid, _hooks().session_id(mover) or mover,
                        f"[stackshot] {_gh.shown(gid)} \"{subject}\" is still yours: a fresh session read it and judged you the right one" + (f" ({why})" if why else "") + ". "
                        "If you are waiting on something to happen (a release, a PR's merge, a recycle or fleet op, a job's run), store the wait so the server watches it and the item stops reading as idle: "
                        "update(wait_kind=\"event\", wait_event=\"<the event>\", ask_by=<the day it comes back anyway>, post_wake_mover=<who takes it then>). Otherwise work it, hand it on or close it. "
                        f"→ {_telling.notice_link(gid)}", tag="stall")
        print(f"stall: {gid} cold call named its mover {mover} as the right owner: left with it", file=sys.stderr, flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"stall: {gid} cold call's keep step failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


def stall_cold_no_taker(gid: str, cold_at: float, why: str, failed: bool) -> None:
    """the stall ladder's cold call (step 2) named no taker: it answered ask_owner or none, gave no usable answer, or its write was refused. Nothing is written to the item's
    needs, ask or mover, and the owner is not asked; the cold step ends and the item goes on to the project's builder (step 3) at once (`handoff_fallback`, which for a stall record never
    returns it to a sender), and to the fleet's builder as a recovery request (step 4) only if the project's builder cannot take it. A History line (metadata.stall.log) and a journal line say so. Never raises."""
    try:
        now = time.time()
        reason = _clip_line(why, 120)
        with _writes.ITEM_LOCK:
            item = _load(gid)
            r = _ho.record_of(item)
            if item.get("status") != "open" or not r or not isinstance(r.get("cold"), dict) or r["cold"].get("at") != cold_at:
                return
            _ho.end_cold(item, "failed" if failed else "done", now, "the cold call named no taker" + (f": {reason}" if reason else ""))
            _stall.note(item.setdefault("metadata", {}), now, "the cold call named no taker" + (f" ({reason})" if reason else "") + ": to the builder")
            _writes.save(gid, item, note="stall: the cold call named no taker")
        print(f"stall: {gid} cold call named no taker: to the builder", file=sys.stderr, flush=True)
        _handoff.handoff_fallback(gid, "the cold call named no taker", cold_ok=False, cold_at=cold_at)
    except Exception as e:  # noqa: BLE001
        print(f"stall: {gid} cold call's no-taker step failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


def handoff_write(gid: str, what: str, write: "Callable[[], None]") -> tuple[str, str]:
    """a write of stackshot's own ladder (the cold call's answer through `_update`) the server refuses is tried once more, `write` rebuilding it from a fresh read. Each refusal is
    logged to the journal (stderr) with its text. Any other error inside the write (a bug, a store failure) is not tried again: it is logged, and reported the same way, so the fleet's
    builder is asked with its text and the item is not sent back to its sender. → ("", "") when a write went through, else (the text of the last refusal or error, "was refused twice" | "failed with an error")."""
    err = ""
    for n in (1, 2):
        try:
            write()
            return "", ""
        except ToolError as e:
            err = str(e) or "refused"
            print(f"handoff: {gid} {what} refused (attempt {n} of 2): {_clip_line(err, 300)}", file=sys.stderr, flush=True)
        except Exception as e:  # noqa: BLE001
            err = f"{e.__class__.__name__}: {e}"
            print(f"handoff: {gid} {what} failed on attempt {n} of 2: {_clip_line(err, 300)}", file=sys.stderr, flush=True)
            return err, "failed with an error"
    return err, "was refused twice"


def handoff_recover(gid: str, why: str) -> None:
    """The last rung for an item whose cold call's answer the write refused: the fleet's builder is asked to recover the session (`handoff_exec` does it for a `recover` step), once for the
    record; not when the item was taken since, or the request was made already. Never raises."""
    try:
        now = time.time()
        with _writes.ITEM_LOCK:
            item = _load(gid)
            r = _ho.record_of(item)
            if item.get("status") != "open" or not r or r.get("taken_at") or r.get("recovery_at"):
                return
            frm = str(r.get("to") or "")
        _handoff.handoff_exec([_ho.Step("recover", gid, why, frm)], now, verify=False)
    except Exception as e:  # noqa: BLE001
        print(f"handoff: {gid} fleet recovery not asked: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


def handoff_cold_end(gid: str, state: str, text: str, cold_at: float | None = None) -> None:
    """The cold call's outcome on its record. With `cold_at` (the call's own stamp) only the record the call was asked about is written, as handoff_fallback does."""
    with _writes.ITEM_LOCK:
        item = _load(gid)
        if _ho.cold_target(item, cold_at) is not None:
            _ho.end_cold(item, state, time.time(), text, cold_at)
            _writes.save(gid, item, note=text if state == "failed" else "")
