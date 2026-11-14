"""handoff.py: the hand-off record, its delivery, the minute pass, the gone-mover hand-over and the display.

An alive item has one mover. A write that changes the effective mover to a session other than the writer records a hand-off on the item (metadata.handoff, waits/handoff.py): who it went to, from whom, when, when it
was delivered (a push that came back "delivered": `telling.tell_woken` reports to `handoff_pushed`), and when the new mover first started work on it (a write showing it: `handoff.started`; `writes.save` reports to
`handoff_on_save`). A delivered hand-off not taken in [model] handoff_minutes, one whose recipient's turn ended with no write to it, and a mover whose pane is gone go down section 5 (`handoff_tick`): the project's
background agent, the cold call (service/handoff_cold.py), the sender, then a recovery request to the fleet's builder; a background agent that is the mover is reminded once first (handoff.remind), and an anchor scoped to
the item counts as taken. [model] handoff = false turns all of it off; [model] pause = true holds the tick, and what is due fires in one batch, one message per recipient, when it is turned off again. The send-time guard
(gates.gate_handoff) refuses a hand-off to a session with no pane.

This module holds, in the order of the file: the switches and the readers of a session's pane, the project's background agents and the pass's environment; the recording of every real write (`handoff_on_save`,
`handoff_his_over`, `handoff_follow` and the one-off repair); the delivery of every push about an item; the pass itself (`handoff_tick`, `handoff_exec` and the audit's hand-over of the items left with a gone
session); and the display (`handoff_lines` for get, `handoff_brief` for the brief).

The record is written through service/writes.py and the notices go through service/telling.py: the domain (waits/handoff.py) decides, the service writes. What the pass still reaches in server.py comes through `Hooks` in
service/handoff_hooks.py, looked up when it runs, so a suite that replaces one on server.py is the one called. A suite that replaces a function of this module sets it here, the cold call's names on
service/handoff_cold.py.

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import threading
import time
from typing import Any, Callable

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core import instance as _inst
from stackshot.core.instance import OWNER
from stackshot.core.store import _item_files
from stackshot.fleet import fleet as _fleet
from stackshot.fleet import liveness as _lv
from stackshot.fleet import sessions_registry as _sr
from stackshot.fleet.sessions_registry import _session_label, _sessions_index
from stackshot.github import ghsync as _gh
from stackshot.model import item_project as _ip
from stackshot.model import model as _model
from stackshot.model.bullet_text import _clip_line
from stackshot.model.ids import _GID
from stackshot.model.needs import _NEEDS_KINDS, _canon_needs, _needs_of, _needs_store
from stackshot.projects import projects as _prj
from stackshot.router import router as _router
from stackshot.service import handoff_cold as _hcold
from stackshot.service import telling as _telling
from stackshot.service import writes as _writes
from stackshot.service.handoff_hooks import hooks as _hooks
from stackshot.service.store import _legacy_hold, _legacy_needs, _load
from stackshot.waits import handoff as _ho
from stackshot.waits import stall as _stall
from stackshot.waits import successor as _succ
from stackshot.waits import watchers as _watch


CLI_SESSIONS = Path.home() / ".claude" / "sessions"    # the CLI's own registry of its panes on this box (push.py reads it too): status busy | idle | shell and when it changed


def handoff_on() -> bool:
    """[model] handoff (default true): the hand-off machinery. false: no record is written, no clock runs, no gone mover is looked for, no hand-off is refused for a dead pane."""
    return bool(_cfg.get("model", "handoff", default=True))


def handoff_paused() -> bool:
    """[model] pause (default false): the board-wide pause switch (design section 5): the clock and the gone-mover pass do nothing while it is true. The key is SHARED with the
    watchers (they own it and document it in stackshot.example.toml; this reads it with the same reader, `_cfg.get("model", "pause")`)."""
    return _watch.paused()          # the config's switch, or the migration's pass holding the board (`migrate_write` in service/migrations.py)


def cold_call_on() -> bool:
    return bool(_cfg.get("model", "cold_call", default=True))


def handoff_num(key: str, default: float) -> float:
    try:
        v = float(_cfg.get("model", key, default=default))
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


def ho_same(a: Any, b: Any) -> bool:
    """Two references are one session: the same text, the same registry session, or the same canonical id (as the guards resolve sessions); the owner only with himself."""
    a, b = str(a or "").strip(), str(b or "").strip()
    if not a or not b:
        return False
    if a.casefold() == b.casefold():
        return True
    if _model.is_owner(a) or _model.is_owner(b):
        return _model.is_owner(a) and _model.is_owner(b)
    try:
        s = _sr.same(a, b)
        if s is not None:
            return bool(s)
    except Exception:  # noqa: BLE001
        pass
    return _hooks().session_id(a) == _hooks().session_id(b)


def ho_ident(who: str) -> str:
    """The id a hand-off keeps beside the name it shows: the session's transcript or permanent id when it has one."""
    i = _hooks().session_id(str(who or ""))
    return i if _anc.is_id(i) else ""


def ho_derive(item: dict[str, Any]) -> "_model.Model":
    return _hooks().model_of(item)


def handoff_pane(who: str, idx: dict[str, Any] | None = None) -> str:
    """"" when `who` may have a live pane, else why not in words: the message tool's dead-recipient rule (_dead_recipient and _pane_dead: a retired session, or one whose
    every row has been gone longer than [client] dead_after_minutes on a machine that is online), plus a session no heartbeat row holds at all (a message to it is refused too).
    The owner and a cloud session (cse_ …) have none to check."""
    w = str(who or "").strip()
    if not w or _model.is_owner(w) or w.startswith("cse_"):
        return ""
    idx = _sessions_index() if idx is None else idx
    names = {x for x in (w, _session_label(w)) if x}
    rows = [r for r in idx.values() if isinstance(r, dict) and r.get("name") in names]
    byid = idx.get(w)
    if isinstance(byid, dict) and not any(byid is r for r in rows):
        rows.append(byid)
    if not rows or not any(_lv.running(r) for r in rows):
        try:
            reg_row = _sr.row(w)
        except Exception:  # noqa: BLE001
            reg_row = None
        try:
            roles = _anc.session_roles()
            held = _hooks().role_name(roles, w)
        except Exception:  # noqa: BLE001
            roles, held = {}, ""
        if (reg_row and reg_row.get("state") != "live") or (held and roles[held].get("retired")):
            return "a retired session, its pane gone"
    if not rows:
        return "no pane of it is in the heartbeat"
    whys = [_lv.pane_dead(r) for r in rows]
    return whys[0] if all(whys) else ""


def handoff_registered(who: str, idx: dict[str, Any] | None = None) -> bool:
    """Is there a row in the CLI's registry on this box for the session `who`, of any kind and of a live process (`liveness.registered`)? The names and ids are `handoff_pane_row`'s."""
    w = str(who or "").strip()
    idx = _sessions_index() if idx is None else idx
    names = {x for x in (w, _session_label(w)) if x}
    ids = {w, _hooks().session_id(w)} | {k for k, r in dict.items(idx) if isinstance(r, dict) and r.get("name") in names}
    return _lv.registered(names, ids, CLI_SESSIONS)


def handoff_pane_row(who: str, idx: dict[str, Any] | None = None) -> tuple[float, dict[str, Any]] | None:
    """(the epoch second its status last changed, the row) of a pane on this box, from the CLI's own registry (~/.claude/sessions/<pid>.json; push.py reads the same): None for a
    session this box does not run. Only an interactive pane's row counts (`kind` == "interactive": a headless `claude -p` of the same session is no pane that holds a notice), its
    process must be alive, and the most recently updated row wins. The one place both `handoff_status` and `handoff_started` read, so the two never disagree about which row is the pane."""
    w = str(who or "").strip()
    idx = _sessions_index() if idx is None else idx
    names = {x for x in (w, _session_label(w)) if x}
    ids = {w, _hooks().session_id(w)} | {k for k, r in dict.items(idx) if isinstance(r, dict) and r.get("name") in names}
    return _lv.pane_row(names, ids, CLI_SESSIONS)       # the shared engine reads the registry; CLI_SESSIONS is read at call time


def handoff_status(who: str, idx: dict[str, Any] | None = None) -> tuple[str, float]:
    """(busy | idle | shell | "", the epoch second its status last changed) of a pane on this box, from the row `handoff_pane_row` picks: "" for a session this box does not run."""
    return _lv.status(handoff_pane_row(who, idx))


def handoff_started(who: str, idx: dict[str, Any] | None = None) -> float:
    """The epoch second the live process of a pane on this box started (`startedAt` in the row `handoff_pane_row` picks, the same row `handoff_status` reads): a relaunch, a resume or
    a recycle is a new process, so a start after a hand-off's delivery means the pane that was told is gone. 0.0 for a session this box does not run, a row without the
    field, or no live process: there the hand-off goes on as before."""
    best = handoff_pane_row(who, idx)
    try:
        return float(best[1].get("startedAt") or 0) / 1000.0 if best else 0.0
    except (TypeError, ValueError):
        return 0.0


def handoff_background(project: str) -> list[str]:
    """The project's background agents, the one to hand to first first (the send-time guard names one): the builder before the rest, the page's order within each."""
    return [n for _a, _b, n in handoff_ranked(project)]


def handoff_ranked(project: str) -> list[tuple[int, int, str]]:
    """(class, order, name) of the project's background agents, best first: those of the page whose hub is the project's (the guards' own reading, model_guards.Ctx.background_of);
    class 0 a mandate that says build, 1 one that says maintain, merge or engineer, 2 the rest. The builder is the first of class 0 or 1."""
    try:
        reg = _anc.registry()
        roles = _anc.session_roles(reg)
        hub = _anc.hub_of(project, reg)
        out = []
        for i, (n, r) in enumerate(roles.items()):
            if r.get("role") != "back" or _anc.hub_of(r.get("project", ""), reg) != hub:
                continue
            mand = str(((reg.get(r.get("project", "")) or {}).get("agents") or {}).get(n) or "")
            out.append((0 if re.search(r"\bbuild", mand, re.I) else 1 if _router._BUILDER.search(mand) else 2, i, n))
        return sorted(out)
    except Exception:  # noqa: BLE001
        return []


def handoff_builder(project: str) -> list[str]:
    """Where a hand-off nobody took falls first: the project's BUILDER alone (router_live.builder's pick: the background agent whose mandate says build, else maintain, merge or
    engineer, the page's order within each; not every background agent on the page). A list of one, or none."""
    ranked = handoff_ranked(project)
    return [ranked[0][2]] if ranked and ranked[0][0] < 2 else []


def handoff_exempt(item: dict[str, Any], who: str) -> bool:
    """Never clocked: a front agent (a session the owner talks to: no item notice wakes one, so nothing was delivered to start a clock)."""
    m = item.get("metadata") or {}
    return _telling.front_keeper(who, str(m.get("project") or ""))[0]


def handoff_reminder_target(who: str, roles: dict[str, Any] | None) -> str:
    """The session id a reminder goes to, or "" (fail closed): only a live session that the registry or the fleet resolves and that `roles` lists with a background role (`back`) and not
    retired. Not a front agent, a page's name-line session (the one session of a one-session project is the one the user talks to), an unknown name, and nothing at all when the roles
    could not be read or anything here raises."""
    try:
        if not roles or not who or not _ho.is_session_name(who) or _model.is_owner(who):
            return ""
        sid = _hooks().session_id(who)
        if not (_anc.is_id(sid) or _sr.resolve(sid)):
            return ""
        entry = roles.get(_hooks().role_name(roles, who)) or {}
        return sid if entry.get("role") == "back" and not entry.get("retired") else ""
    except Exception:  # noqa: BLE001
        return ""


def handoff_env(now: float) -> "_ho.Env":
    idx = _sessions_index()          # read once for the pass
    cells: dict[str, Any] = {}       # read at most once per pass, and only when an item would act: the anchors, the role map
    reminded: dict[str, str] = {}

    def anchored(gid: str, item: dict[str, Any]) -> bool:
        try:
            if "anchors" not in cells:
                try:
                    cells["anchors"] = _anc.load()
                except Exception:  # noqa: BLE001
                    cells["anchors"] = {}                       # unreadable: nothing counts as anchored, the clock runs as before
            at = float((_ho.record_of(item) or {}).get("at") or 0)      # an anchor older than the hand-off (an earlier pull request, one added before the hand-over) says nothing about it
            return any(float(e.get("added") or 0) >= at for e in _hooks().scoped_anchors(str((item.get("metadata") or {}).get("project") or ""), gid, cells["anchors"]))
        except Exception:  # noqa: BLE001
            return False

    def remind(item: dict[str, Any], who: str) -> str:
        if who not in reminded:
            if "roles" not in cells:
                try:
                    cells["roles"] = _anc.session_roles()
                except Exception:  # noqa: BLE001
                    cells["roles"] = None
            reminded[who] = handoff_reminder_target(who, cells["roles"])
        return reminded[who]
    return _ho.Env(now=now, derive=ho_derive, same=ho_same, minutes=handoff_minutes(), idle_grace=handoff_num("handoff_idle_seconds", _ho.IDLE_GRACE),
                   gone_days=handoff_num("handoff_gone_days", _ho.GONE_DAYS), cold_call=cold_call_on(), pane=lambda w: handoff_pane(w, idx),
                   inbox_grace=handoff_num("handoff_inbox_grace_minutes", 10.0), status=lambda w: handoff_status(w, idx), started=lambda w: handoff_started(w, idx), background=handoff_builder,
                   exempt=handoff_exempt, label=_session_label, cover_all=_hooks().switchover_on(), is_front=lambda w, _p: _telling.front_sender(w), anchored=anchored, remind=remind,
                   ladder=_hooks().ladder_on(), laddered=lambda g, w, at: _hooks().laddered(g, w, now, at))


def handoff_minutes() -> float:
    return handoff_num("handoff_minutes", _ho.MINUTES)


# ---- recording: every real write
def handoff_on_save(gid: str, before: dict[str, Any] | None, item: dict[str, Any], writer: str, author: tuple[str, str] | None) -> None:
    """Called by `writes.save` right after the writer is stamped: the writer touches the item (a hand-off to it is taken), and a change of the effective mover to someone else makes a
    hand-off record. Not for the server's own saves (no writer). Never fails a write."""
    if not handoff_on() or author or not writer or _ho.is_script(writer):
        return      # the server's own save; the owner's board answer (author: _answer_tick covers it); a script's write (cap-words): no session's, so no hand-off
    try:
        _telling.HO_STATE.told = set()
        name, wid = str(item.get("written_by") or ""), str(item.get("written_by_id") or "")
        derive = lambda it: ho_derive({**it, "gid": gid})
        r = _ho.apply(item, before, name, wid, time.time(), derive, ho_same, _session_label, ho_ident)
        fresh = getattr(_telling.HO_STATE, "fresh", None)
        if fresh is None:
            fresh = _telling.HO_STATE.fresh = {}
        fresh.pop(gid, None)
        if r:
            fresh[gid] = (str(r.get("to")), r.get("at"))
    except Exception as e:  # noqa: BLE001  — the record is an extra: a write is never failed by it
        print(f"handoff: {gid} not recorded: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


def handoff_his_over(gid: str, item: dict[str, Any], author: tuple[str, str] | None = None, quiet: bool = False) -> bool:
    """a hand-off to the owner is taken by no write of his own (he writes through the board, whose save carries `author`, or a session relays his answer), so it read "handed to the owner,
    not yet taken" after he had answered. Called by `writes.save` for every save, right after the hand-off record of the write: his answer on the board ends it, and so does any save that leaves the item
    not his to move (the mover is no longer he, or the item waits, or is closed): the record stays as history, taken then, with the reason. A save that just handed the item to him
    (a new record, or he still the mover) leaves it. Never fails a write. → True when it ended one."""
    try:
        if not handoff_on() or _ho.pending_his(item) is None or (quiet and not author):      # a write that only files or only confirms ends nothing
            return False
        if author and author[1] == "board":
            why = f"{OWNER} answered on the board"
        else:
            mod = _hooks().model_of({**item, "gid": gid})
            if mod.state == _model.ALIVE and _model.is_owner(mod.mover):
                return False
            why = f"it is no longer {OWNER}'s to move"
        return _ho.answered(item, time.time(), why)
    except Exception as e:  # noqa: BLE001  — the record is an extra: a write is never failed by it
        print(f"handoff: {gid} his hand-off not ended: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return False


def handoff_follow(gid: str, before: dict[str, Any] | None, item: dict[str, Any], writer: str, author: tuple[str, str] | None, quiet: bool = False) -> str:
    """Called by `writes.save` for every save, after the session's own hand-off record (handoff_on_save) and the owner's (handoff_his_over): the hand-off record follows the item's effective
    mover, whatever path changed it. The invariant: an item has no OPEN record (nobody has taken it) whose `to` differs from its mover, so a record never names a mover the item left.
    A save of the server's own (no writer, no author: a wake that makes the post-wake mover the mover, an event wake, the stall pass, a release of `after`) that changes the mover to
    someone else makes a new record to the new mover, from the server. The record is `no_clock` (the 10-minute take clock runs only on a session's hand-off; a woken mover is timed by the
    stall pass) and is not delivered until a notice reaches the mover (handoff_pushed): one to a front agent, one held, or one that goes to a session in needs other than the mover marks nothing.
    It makes none when the item came
    from the owner's state (a hand-back after his answer is taken, not handed), nor to the owner (his is the session's write or his answer). The owner's answer on the board, a script's save (cap-words, the migration), a close,
    a wait that leaves no mover and a session's write that makes itself the mover hand nothing over: they end a record that names the mover the item left. A write that only files or
    confirms ends nothing.
    Never fails a write. → "recorded" | "ended" | ""."""
    if not handoff_on() or (quiet and not author):
        return ""
    try:
        derive = lambda it: ho_derive({**it, "gid": gid})
        m1 = _ho.mover_of(item, derive, strict=True)
        if m1 is None:      # the model could not read the item: a failed reading is not "no mover", so no record is ended or made
            print(f"handoff: {gid} record left as it is: its mover could not be read", file=sys.stderr, flush=True)
            return ""
        if before:      # `before` is the file as stored, `item` was loaded through the legacy readers: read both the same way
            before = json.loads(json.dumps(before))
            _legacy_hold(before); _legacy_needs(before)
        m0 = _ho.mover_of(before, derive, strict=True) if before else ""
        # own: the server's own save (the owner's answer and a hand-back from his state, m0 the owner, hand nothing to anyone: they end a stale record and make none); an unreadable `before`
        # is no known mover, so nothing is made new from it (a stale record still ends)
        own = not (writer or author) and m0 is not None
        m0 = m0 or ""
        return _ho.follow(item, m0, m1, time.time(), frm=_ho.SERVER, record=own and before is not None and not _model.is_owner(m0) and not _model.is_owner(m1),
                          same=ho_same, label=_session_label, ident=ho_ident)
    except Exception as e:  # noqa: BLE001  — the record is an extra: a write is never failed by it
        print(f"handoff: {gid} record not followed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return ""


def handoff_repair(apply: bool = False, now: float | None = None) -> list[dict[str, Any]]:
    """The one-off repair of the records written before the record followed the mover (tools/handoff_repair.py runs it): every stored item, open or closed, whose OPEN hand-off record
    names someone other than the item's effective mover (handoff.stale) has the record ended into its history ("handed on, not taken", or why the item has no mover), as handoff_follow
    does on the next save. Nothing is made new: no notice was ever sent to the mover the item holds now, so a fresh record would only show a hand-off that never happened. Dry by default
    (reads, writes nothing); `apply` saves each repaired item as the server's own save, under the item lock. → one row per item: {gid, shown, status, record_to, record_from, record_at,
    delivered, mover, ended}."""
    now = time.time() if now is None else now
    rows: list[dict[str, Any]] = []
    for gid, p in _item_files():
        try:
            row = handoff_repair_one(gid, p, apply, now)
        except Exception as e:  # noqa: BLE001  — one item never stops the repair
            print(f"handoff: {gid} record not repaired: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
            continue
        if row is not None:
            rows.append(row)
    return rows


def handoff_repair_one(gid: str, p: Any, apply: bool, now: float) -> dict[str, Any] | None:
    """One item of handoff_repair. → its row, None when its record is fine (or it has none or cannot be read)."""
    try:
        with open(p, encoding="utf-8") as f:
            it = json.load(f)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(it, dict) or _ho.record_of(it) is None:
        return None
    with _writes.ITEM_LOCK:
        if apply:      # the item as stored now, under the lock
            with open(p, encoding="utf-8") as f:
                it = json.load(f)
        calc = json.loads(json.dumps(it))      # the legacy forms (a retired hold status, an old needs) are read as the model reads them, and never written back by this
        _legacy_hold(calc); _legacy_needs(calc)
        mover = _ho.mover_of(calc, lambda i_: ho_derive({**i_, "gid": gid}), strict=True)
        if mover is None:      # a failed reading is not "no mover": the record is kept
            print(f"handoff: {gid} record kept: its mover could not be read", file=sys.stderr, flush=True)
            return None
        if not _ho.stale(calc, mover, ho_same):
            return None
        r = dict(_ho.record_of(calc) or {})
        row = {"gid": gid, "shown": _gh.shown(gid), "status": it.get("status"), "record_to": r.get("to"), "record_from": r.get("from"), "record_at": r.get("at"),
               "delivered": bool(r.get("delivered_at")), "recovery": bool(r.get("recovery_at")), "mover": mover, "ended": ""}
        if apply:
            row["ended"] = _ho.follow(it, "", mover, now, same=ho_same, label=_session_label, ident=ho_ident)
            _writes.save(gid, it, note="hand-off record repaired: it named a mover the item no longer has", mirror=False, ctx=_writes.QUIET)      # a repair writes the history of the record and nothing else: no mover is settled, no other record ended
        return row


def handoff_repair_pass() -> int:
    """Once per start, before any thread starts and before the wake pass (idempotent, so every start runs it; a store with no stale record writes nothing): the repair of handoff_repair,
    applied. It runs after the migrations that change a mover (`migrate_owner_mover` in service/migrations.py, _mover_backfill_pass), whose quiet saves leave a record they find naming another mover. Skipped while
    [model] handoff is false. One stderr line with the count. → the number of items repaired."""
    if not handoff_on():
        return 0
    rows = handoff_repair(apply=True)
    if rows:
        print(f"migrate: hand-off records: {len(rows)} open record(s) that named someone but the item's mover ended into the history "
              f"({sum(1 for r in rows if r['status'] != 'open')} of closed items, {sum(1 for r in rows if r['status'] == 'open' and not r['mover'])} of open items with no mover)", file=sys.stderr, flush=True)
    return len(rows)


def handoff_told_text(to: str, text: str, outcome: str, err: str = "", link_only: bool = False) -> None:
    """A push to `to` whose text names items (a message, a router pass, a page-owed relay) came back `outcome`: an open hand-off of any of those items to `to` is delivered, or waits
    in the inbox (handoff_pushed). Only a push that reached the inbox or the pane counts here; a failed one is the notice senders' own (tell_woken retries and falls back).
    `link_only`: the text must carry the item's own notice link (notice_link), not just cite its id. The router's push and the keeper's batch pass it: a batch cites other items in a subject,
    and a citation is no notice of that item; a message a session sends on purpose does not (a session names the item it means). Never raises."""
    try:
        if not str(outcome or "").startswith(("delivered", "queued", "inbox")) or not to:
            return
        gids = [g for g in _hooks().item_refs(text) if (_ho.record_of(_hooks().load_or_none(g)) or {}).get("to")]
        if link_only:
            gids = [g for g in gids if re.search(re.escape(_telling.notice_link(g)) + r"(?![\w])", str(text or ""))]
        if gids:
            handoff_pushed(",".join(gids), to, outcome, err)
    except Exception as e:  # noqa: BLE001
        print(f"handoff: delivery of a push to {to} not recorded: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


def handoff_text(gid: str, item: dict[str, Any], r: dict[str, Any], again: bool = False) -> str:
    """The notice a hand-off sends. `again`: the second one, after the pane was relaunched before the item was written to; it says so. A record whose mover was reminded
    (`reminded_at`) words it as the reminder: the item was handed over, no work on it has started, start its subagent alongside the current work."""
    meta = item.get("metadata") or {}
    nxt = _clip_line((str(meta.get("next") or "").strip().splitlines() or [""])[0], 160)
    by = str(r.get("from") or "a session")
    if float(r.get("reminded_at") or 0) > float(r.get("resent_at") or 0):      # the later of the two is what this notice is (a reminder's retry stays a reminder; a resend after it is a resend)
        return (f"[stackshot] reminder: {_gh.shown(gid)} was handed to you by {by} and no work on it has started in {handoff_minutes():g} min: {item.get('subject') or ''} ({meta.get('project') or ''})"
                + (f"; next: {nxt}" if nxt else "")
                + f". Start its subagent alongside the current work (or hand it back, sender={by!r}); starting work on it (a step marked done, a step status in progress) counts as taking it; a note does not. → {_telling.notice_link(gid)}")
    return (f"[stackshot] {_gh.shown(gid)} is handed to you by {by}" + (" (sent again: your pane restarted before the item was written to)" if again else "")
            + f": {item.get('subject') or ''} ({meta.get('project') or ''})" + (f"; next: {nxt}" if nxt else "")
            + f". Do your part and close it or hand it back (sender={by!r}); starting work on it (a step marked done, a step status in progress) counts as taking it; a note does not. → {_telling.notice_link(gid)}")


def front_handed_by_peer(rec: dict[str, Any], to: str, project: str) -> bool:
    """Is the hand-off `rec` (to the front agent `to`) one front agent made to another of a front-only project (anchors.front_only; the case gates.fix_front_mover lets through)?"""
    try:
        _roles, key = _hooks().role_of(to)
        return bool(key) and _hooks().front_pair_ok(str(rec.get("from") or ""), key, project)
    except Exception:  # noqa: BLE001
        return False


# ---- delivery: every push about an item
def handoff_pushed(gids: str, owner: str, outcome: str, why: str = "") -> None:
    """Called by tell_woken when a push to `owner` about these items is over: `outcome` is push.py's last line (delivered … | queued … | inbox …), or "failed". A delivered push
    makes the open hand-off to that session delivered now (its clock starts); one that waits (`inbox`, `queued`: the machine is away, the pane is not reachable now, a reboot's pause)
    is neither delivered nor failed: the puller's ack makes it delivered (handoff_acked), else the clock starts [model] handoff_inbox_grace_minutes after it was queued; only a
    refusal or an error is a failure: sent once more, and a second failure sends the item down section 5 with the sender told on the item. Never raises."""
    if not handoff_on():
        return
    for g in [x for x in re.split(r"[,\s]+", str(gids or "")) if _GID.match(x)]:
        try:
            act = ""
            with _writes.ITEM_LOCK:
                it = _load(g)
                r = _ho.record_of(it)
                if it.get("status") != "open" or not r or r.get("recovery_at"):
                    continue
                now = time.time()
                if outcome.startswith("delivered"):
                    changed = _ho.delivered(it, owner, now, ho_same)
                elif outcome.startswith(("inbox", "queued")):      # waiting, not failed: the line is in the inbox for its machine, the pane is not reachable now (queued), or a reboot's pause holds it
                    changed = _ho.queued(it, owner, outcome, now, ho_same)
                    if changed:
                        _HO_QUEUED[g] = str((_ho.record_of(it) or {}).get("to") or owner)
                else:
                    act = _ho.failed(it, owner, why or outcome, now, ho_same)
                    changed = bool(act)
                if changed:
                    _writes.save(g, it)
            if act == "retry":
                rec = _ho.record_of(it) or {}
                _telling.tell_woken(g, owner, handoff_text(g, it, rec, again=bool(rec.get("resent_at"))), tag="handoff")      # a notice sent again stays worded as one when its push is tried once more
            elif act == "fallback":
                handoff_fallback(g, f"a push to {_session_label(owner)} failed twice ({_clip_line(why or outcome, 100)})")
        except Exception as e:  # noqa: BLE001
            print(f"handoff: {g} push result not recorded: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


_HO_QUEUED: dict[str, str] = {}      # gid → the session its hand-off notice waits for (set when a push is queued; read by handoff_acked; a restart empties it, and the inbox grace covers that)


def handoff_acked(lines: list[dict[str, Any]]) -> None:
    """The puller confirmed these inbox lines (the /inbox/ack route reads them before they go). A line to the session a queued hand-off went to, that names the item (the id the
    item is shown with), whatever its phrasing (the hand-off notice, a needs-based "now needs you", a page-owed relay), was read by its machine: the hand-off is delivered now.
    The server sees the ack here and only here. Race: an ack can come before the push's own "inbox" outcome is recorded (the line is put, the puller takes and acks it, then push.py
    prints); the hand-off is then marked queued after the ack and the inbox grace covers it. Never raises."""
    try:
        if not handoff_on() or not _HO_QUEUED:
            return
        hits = [(str(it.get("name") or ""), str(it.get("uuid") or ""), str(it.get("text") or "")) for it in lines if it.get("src") == "msg"]
        for gid, to in list(_HO_QUEUED.items()):
            it = _load(gid)
            r = _ho.record_of(it)
            if it.get("status") != "open" or not r or r.get("delivered_at") or not r.get("queued") or not ho_same(r.get("to"), to):
                _HO_QUEUED.pop(gid, None)
                continue
            pat = re.compile(rf"(?<![\w#]){re.escape(_gh.shown(gid))}(?!\d)")
            if any((ho_same(r.get("to"), n) or (u and ho_same(r.get("to_id"), u))) and pat.search(t) for n, u, t in hits):
                _HO_QUEUED.pop(gid, None)
                handoff_pushed(gid, str(r.get("to")), "delivered (acked by its machine)")
    except Exception as e:  # noqa: BLE001
        print(f"handoff: ack not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


# ---- the pass: the clock, the turn end, the gone mover
def handoff_tick(now: float | None = None, only: "set[str] | list[str] | None" = None) -> list[str]:
    """The periodic pass (the runner calls it every 60 s): every open item that is alive with a session as its mover, looked at by handoff.plan, and what is due is done:
    a delivered hand-off not taken in [model] handoff_minutes, one whose recipient's turn ended with no write, a mover whose pane is gone; and a mover whose pane was relaunched after the
    notice is sent the notice again, once, instead. Nothing while [model] pause is true.
    `only` limits the pass to those items (a test, a rerun). → the gids moved, handed to the fleet's builder as a recovery request, sent to the cold call or sent the notice again."""
    if not handoff_on() or handoff_paused():
        return []
    now = time.time() if now is None else now
    items: dict[str, dict[str, Any]] = {}
    for gid, p in _item_files():
        try:
            with open(p, encoding="utf-8") as f:
                it = json.load(f)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(it, dict) and it.get("status") == "open" and (only is None or gid in only):
            _legacy_hold(it); _legacy_needs(it); _ip.read_through(it)
            it["gid"] = gid
            items[gid] = it
    env = handoff_env(now)            # one env for the plan and for the steps' re-check: the anchors and the role map are read once a tick
    return handoff_exec(_ho.plan(items, env), now, env=env)


ORPHAN_CEILING = 10        # more orphans than this, or than a quarter of the open items, is read as a partial view of the fleet (a machine's rows missing): reported, nothing moved
ORPHAN_MAX = 40            # open items one audit hand-over moves; the rest wait for the next run (a partial heartbeat must not move the board in one pass)


def orphan_handover(apply: bool = False, now: float | None = None) -> dict[str, Any]:
    """The audit's check of open items left with a session that is gone (successor.py), and its fix: each such item goes to the closest live agent, through the write path of the minute hand-off pass
    (`handoff_exec` → `handoff_write_move`: the new mover heads `needs`, an alive item gets the hand-off record, the History line reads `handed to X: <who> is gone (...); closest live agent: ...`, the new mover is told,
    one message per recipient). Dry by default: reads, writes nothing, tells nobody. Only open items; an item the owner moves or waits on is never listed; one with no live successor stays and is listed under `left`.
    Idempotent: the mover a hand-over names is live, so the next call finds the item whole. Each move is checked again under the item lock (the item must still be open with the mover it was found with).
    Stands still, `checked` false, while [audit] orphan_handover is "off" or the fleet's heartbeat is empty (every name would look gone), and moves nothing in "report" (the shipped default). A partial view of the fleet is not taken for gone sessions:
    a mover on a machine whose machine.json cannot be read, or with no row while a machine's session list is empty or unreadable, is not read as gone, and more orphans than ORPHAN_CEILING or than a quarter of the open items is answered with
    `ceiling` true and the list, and nothing moved. An alive item goes to a background agent first (successor.pick: the minute pass sends a front agent no notice); a held item is not listed. → {checked, mode, applied, read, found, moved: [{id,
    project, from, to, tier, why}], left: [{id, project, from, why}], skipped, over_cap, note}."""
    now = time.time() if now is None else now
    mode = _cfg.audit_orphan_handover()
    out: dict[str, Any] = {"checked": False, "mode": mode, "applied": False, "read": 0, "found": 0, "moved": [], "left": [], "skipped": 0, "over_cap": 0, "note": "", "ceiling": False}
    if mode == "off":
        out["note"] = "[audit] orphan_handover is off"
        return out
    idx = _sessions_index()
    if not idx:
        out["note"] = "the fleet's heartbeat is empty: every session would look gone, nothing was checked"
        return out
    letters = _fleet.letters()
    unread = {L for L in letters if not _fleet.read(L, "machine")}          # a machine whose machine.json cannot be read: its panes cannot be told gone from unseen
    partial = unread | {L for L in letters if not _fleet.read(L, "sessions")}      # …and one whose session list is empty or unreadable: a mover on it has no row, which proves nothing
    items: dict[str, dict[str, Any]] = {}
    for gid, p in _item_files():
        try:
            with open(p, encoding="utf-8") as f:
                it = json.load(f)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(it, dict) and it.get("status") == "open":
            _legacy_hold(it); _legacy_needs(it)
            it["gid"] = gid
            items[gid] = it
    reg = _prj.with_pending(_anc.registry(), made=True)       # an agent made through the New session form counts as its project's agent, as session_roles has it
    def gone(who: str) -> str:
        why = handoff_pane(who, idx)
        if not why:
            return ""
        names = {x for x in (str(who).strip(), _session_label(who)) if x}
        mine = [r for r in idx.values() if isinstance(r, dict) and r.get("name") in names]
        if any(r.get("machine") in unread for r in mine):
            return ""                                                          # on a machine the view cannot read: not known to be gone
        if not mine and partial and why == "no pane of it is in the heartbeat":
            return ""                                                          # no row, while a machine's view is partial: it may be on that machine
        return why
    rows = _succ.plan(items, reg, ho_derive, gone, _session_label, back_of=handoff_background)
    out.update(checked=True, read=len(items), found=len(rows))
    if len(rows) > ORPHAN_CEILING or len(rows) > len(items) // 4:
        out.update(ceiling=True, moved=[{"id": _gh.shown(r["gid"]), "project": r["project"], "from": _session_label(r["from"]) if r["from"] else "", "to": r["to"], "tier": r["tier"], "why": r["why"]} for r in rows if r["to"]][:ORPHAN_MAX],
                   left=[{"id": _gh.shown(r["gid"]), "project": r["project"], "from": _session_label(r["from"]) if r["from"] else "", "why": r["why"]} for r in rows if not r["to"]],
                   note=f"{len(rows)} of {len(items)} open items read as left with a gone session (more than {ORPHAN_CEILING}, or more than a quarter): that is a partial view of the fleet more likely than that many gone sessions, so nothing was moved")
        return out
    todo = [r for r in rows if r["to"]]
    out["left"] = [{"id": _gh.shown(r["gid"]), "project": r["project"], "from": _session_label(r["from"]) if r["from"] else "", "why": r["why"]} for r in rows if not r["to"]]
    out["over_cap"] = max(0, len(todo) - ORPHAN_MAX)
    todo = todo[:ORPHAN_MAX]
    row = lambda r: {"id": _gh.shown(r["gid"]), "project": r["project"], "from": _session_label(r["from"]) if r["from"] else "", "to": r["to"], "tier": r["tier"], "why": r["why"]}
    if not apply or mode != "apply":
        out["moved"] = [row(r) for r in todo]
        if apply:
            out["note"] = f"[audit] orphan_handover is {mode}: nothing was moved; set it to apply under [audit] to hand these over"
        return out
    by_gid = {r["gid"]: r for r in todo}
    steps = [_ho.Step("move", r["gid"], r["why"], r["from"], r["to"], via="orphan") for r in todo]

    def still(item: dict[str, Any], st: "_ho.Step") -> bool:
        r = by_gid[st.gid]
        state, who = _succ.record_of(item, ho_derive)
        return state == r["state"] and (ho_same(who, r["from"]) if r["from"] else not who)

    done = handoff_exec(steps, now, verify=False, recheck=still)
    out.update(applied=True, moved=[row(by_gid[g]) for g in done], skipped=len(todo) - len(done))
    return out


def handoff_fallback(gid: str, why: str, cold_ok: bool = True, cold_at: float | None = None) -> list[str]:
    """An item that has a hand-off record and cannot go on (a push failed twice, the cold call failed): the next step of section 5 now, not at the next pass. Not when its mover has
    taken it since, or (`cold_at`: the cold call's own stamp) when the record is no longer the one that call was asked about."""
    now = time.time()
    with _writes.ITEM_LOCK:
        item = _load(gid)
        r = _ho.record_of(item)
        if item.get("status") != "open" or not r or r.get("taken_at") or r.get("recovery_at"):
            return []
        if cold_at is not None and not (isinstance(r.get("cold"), dict) and r["cold"].get("at") == cold_at):
            return []
        if r.get("reason") and r["reason"] not in why:
            why = f"{r['reason']}; {why}"
        if _hooks().ladder_on() and not r.get("stall"):      # the one ladder: two failed pushes mean the ask cannot reach the mover, so the item starts at the cold call
            st = _ho.Step("enter", gid, why, str(r.get("to") or ""), via="gone")
        else:
            st = _ho.next_step({**item, "gid": gid}, r, str(r.get("to") or ""), why, handoff_env(now), gid=gid, cold_ok=cold_ok)
    return handoff_exec([st], now, verify=False)


def handoff_write_move(item: dict[str, Any], st: "_ho.Step", now: float) -> None:
    """The item-side write of a `move` step, shared by the minute pass (the builder or the sender takes an item nobody took) and the audit's hand-over to the closest live agent (`via` == "orphan"): the new mover
    heads `needs` (a stored mover that named the old one follows; for the audit's hand-over, `via` == "orphan", so do `then` and a post-wake mover, which the minute pass has never touched), and an alive item gets the hand-off record, from the server, with the way walked so far. A waiting item has no mover to record
    a hand-off for: it takes the new session in `needs` (its post-wake mover by default) and keeps no record. The caller saves with the History line. The item is changed in place."""
    alive = st.via != "orphan" or _hooks().model_of({**item, "gid": st.gid}).state == _model.ALIVE       # read before the fields change
    meta = dict(item.get("metadata") or {})
    keep = [x for x in _needs_of(meta) if x.lower() in _NEEDS_KINDS or not (ho_same(x, st.frm) or ho_same(x, st.to))]
    _needs_store(meta, _canon_needs([st.to, *keep]))
    for key in (("mover", "then", _model.LEGACY_PICKER_KEY) if st.via == "orphan" else ("mover",)):      # the minute pass has only ever followed the stored mover; the audit's hand-over also follows `then` and a post-wake mover
        if meta.get(key) and st.frm and ho_same(meta[key], st.frm):
            meta[key] = st.to
    item["metadata"] = meta
    if alive:
        _ho.successor(item, st, ho_ident(st.to), now, _session_label)
    if st.via == "orphan":
        _stall.note(item["metadata"], now, f"handed to {_session_label(st.to)}: {st.why}")      # the History line with the reason (a mover change alone shows only the names; a waiting item has no record to carry it)


def handoff_exec(steps: "list[_ho.Step]", now: float, verify: bool = True, env: "_ho.Env | None" = None,
                  recheck: "Callable[[dict[str, Any], _ho.Step], bool] | None" = None) -> list[str]:
    """Do the steps of a pass, each under the item lock on a fresh read (verify: the plan must still hold on it), then tell, one message per recipient listing its items.
    `env`: the pass's own (the tick passes the one it planned with), else a new one. `recheck(item, step)`: the caller's own look at the fresh item, under the lock; False skips the step (the audit's hand-over
    checks that the item still has the mover it found)."""
    env = env or handoff_env(now)
    to_new: list[tuple[str, str, str]] = []          # (recipient, gid, the item's line)
    to_sender: list[tuple[str, str, str]] = []       # (sender, gid, the line)
    to_again: list[tuple[str, str, str]] = []        # (gid, the mover, the notice) of a hand-off sent again after a relaunch
    to_remind: list[tuple[str, str, str, str]] = []  # (gid, the session id, the item's line, the reminder alone) of a hand-off a background agent did not take
    to_recover: list[tuple[str, dict[str, Any], str, str, str, "tuple[str, str, bool]"]] = []   # (gid, the item, the quiet session, why, what was tried, the recipient chosen once) of an item nobody could take: the fleet's builder, or a front-only project's -main agent, is asked
    entered: list[tuple[str, str, dict[str, Any]]] = []   # (gid, the mover, its entry) of an item the one ladder took: its first rung is taken after the loop
    done: list[str] = []
    cold_started = False
    for st in steps:
        try:
            with _writes.ITEM_LOCK:
                item = _load(st.gid)
                if item.get("status") != "open":
                    continue
                if recheck is not None and not recheck({**item, "gid": st.gid}, st):
                    continue
                if verify:
                    fresh = _ho.plan({st.gid: {**item, "gid": st.gid}}, env)
                    if not fresh or fresh[0].kind != st.kind or not ho_same(fresh[0].frm, st.frm):
                        continue
                    st = fresh[0]
                if st.kind == "recover":
                    # nobody is left to hand the item to: the item stays with its mover and the fleet's builder (a front-only project's -main agent) is asked once for this record (mark_recovery returns None for one asked already)
                    target = _hooks().recovery_target(str((item.get("metadata") or {}).get("project") or ""), st.frm)      # once, on the raw session: the record, the wording of `tried` and the send all follow it
                    r = _ho.mark_recovery(item, st, now, ho_same, _session_label, asked=_hooks().recovery_role()[target[1]])
                    if r is None:
                        continue
                    quiet = _session_label(st.frm) or st.frm
                    nobuilder = target[2]      # a front-only project has no builder to have tried, whoever is asked
                    tried = (("the stall pass sent the notice again and asked a fresh session who takes it" if nobuilder else "the stall pass sent the notice again, asked a fresh session who takes it and tried the project's builder") if r.get("stall")
                             else "the hand-off ladder tried " + ("a fresh session's call and the sender" if nobuilder else "the project's builder, a fresh session's call and the sender"))
                    _writes.save(st.gid, item, note=f"nobody could take it: recovery requested ({st.why})")      # the mark (recovery_at) is written BEFORE the send, on purpose: a failed send is not retried every pass (metadata.undelivered records it, the audit's unmoved digest is the backstop); the send writes the History line
                    to_recover.append((st.gid, dict(item), quiet, st.why, tried, target))
                elif st.kind == "enter":
                    # the one ladder takes the item (ladder.py): its entry is written now, the first rung is taken below once the item lock is let go
                    rec = _hooks().ladder_enter(item, st, now)
                    if rec is None:
                        continue
                    entered.append((st.gid, st.frm, rec))
                elif st.kind == "resend":
                    # the mover's pane was relaunched after the notice reached it, so the notice died with the old process: no move down section 5, the notice goes out once more
                    r = _ho.resend(item, st, now, _cfg.tz(), env.started(st.frm))
                    if r is None:
                        continue
                    _writes.save(st.gid, item, note=f"{st.why}: the notice was sent again, and the clock restarts from it")
                    to_again.append((st.gid, st.frm, handoff_text(st.gid, item, r, again=True)))
                elif st.kind == "remind":
                    # a background agent that did not take it is reminded once, ahead of the ladder; the clock restarts from the reminder's delivery
                    r = _ho.remind(item, st, now)
                    if r is None or not st.to:
                        continue
                    _writes.save(st.gid, item, note=f"{st.why}: its mover was reminded, and the clock restarts from the reminder")
                    to_remind.append((st.gid, st.to, f"{_gh.shown(st.gid)} {item.get('subject') or ''} ({(item.get('metadata') or {}).get('project') or ''}): handed to you by {r.get('from') or 'a session'}",
                                      handoff_text(st.gid, item, r)))
                elif st.kind == "cold":
                    _hcold.HO_COLD_THREADS[:] = [t for t in _hcold.HO_COLD_THREADS if t.is_alive()]
                    if _hcold.HO_COLD_THREADS or cold_started:
                        continue               # one cold call at a time board-wide, one started per pass: this item is planned again at the next tick
                    cold_started = True
                    r = _ho.mark_cold(item, st, now, ho_same, _session_label)
                    _writes.save(st.gid, item, note=f"{st.why}: the cold call was asked")
                    th = threading.Thread(target=_hcold.handoff_cold, args=(st.gid, now), daemon=True)
                    _hcold.HO_COLD_THREADS.append(th)
                    th.start()
                else:
                    handoff_write_move(item, st, now)
                    _writes.save(st.gid, item, note=f"handed to {_session_label(st.to)}: {st.why}")
                    subject, project = str(item.get("subject") or ""), str((item.get("metadata") or {}).get("project") or "")
                    to_new.append((st.to, st.gid, f"{_gh.shown(st.gid)} {subject} ({project}): {st.why}" + ("; it comes back to you as its sender" if st.via == "return" else "")))
                    if st.sender and not ho_same(st.sender, st.to):
                        to_sender.append((st.sender, st.gid, f"{_gh.shown(st.gid)} {subject}: {st.why}; it went to {_session_label(st.to)}"))
                done.append(st.gid)
        except Exception as e:  # noqa: BLE001  — one item's failure never stops the rest of the pass
            print(f"handoff: {st.gid} step {st.kind} failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    for gid, who, rec in entered:
        _hooks().ladder_first(gid, who, rec, now)
    for gid, it, quiet, why, tried, target in to_recover:
        _hooks().recovery_tell(gid, it, quiet, why, tried, tag="handoff", now=now, target=target)
    for gid, who, text in to_again:
        try:
            _telling.tell_woken(gid, _hooks().session_id(who) or who, text, tag="handoff")      # its push result makes the record delivered (or queued), which starts the clock again
        except Exception as e:  # noqa: BLE001
            print(f"handoff: {gid} resend not sent: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    for sid, lines in _ho.batch([(w, g, ln) for g, w, ln, _t in to_remind]).items():      # one message per recipient, however many of its items fired
        gs = [g for g, w, _l, _t in to_remind if w == sid]
        text = next(t for g, w, _l, t in to_remind if g == gs[0]) if len(gs) == 1 else _ho.message(
            lines, "", f"[stackshot] reminder: {{n}} items were handed to you and nothing has been written to them in {handoff_minutes():g} min:",
            f"\nStart their subagents alongside the current work (or hand them back); starting work on an item (a step marked done, a step status in progress) counts as taking it; a note does not. → {_inst.BOARD_URL}")
        try:
            _telling.tell_woken(",".join(gs), sid, text, tag="handoff")      # its push result makes each record delivered (or queued), which starts the clock again; a failed push is retried once per item, then the ladder goes on
        except Exception as e:  # noqa: BLE001
            print(f"handoff: {','.join(gs)} reminder not sent: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    for who, lines in _ho.batch(to_new).items():
        gids = ",".join(g for w, g, _l in to_new if w == who)
        if _telling.front_keeper(who, "")[0]:
            continue                                 # a front agent is never pushed to unmarked: the board shows it
        tail = " Do your part and close it or hand it back; starting work on it (a step marked done, a step status in progress) counts as taking it; a note does not. → " + (_telling.notice_link(gids) if len(lines) == 1 else f"{_inst.BOARD_URL}")
        _telling.tell_woken(gids, _hooks().session_id(who) or who, _ho.message(lines, "[stackshot] it came to you:", "[stackshot] {n} items came to you, the sessions they were handed to did not take them:", tail),
                    tag="handoff")
    for who, lines in _ho.batch(to_sender).items():
        if _telling.front_keeper(who, "")[0] or _model.is_owner(who):
            continue
        _telling.tell_woken(",".join(g for w, g, _l in to_sender if w == who), _hooks().session_id(who) or who,
                    _ho.message(lines, "[stackshot] a hand-off of yours was not taken:", "[stackshot] {n} hand-offs of yours were not taken:"), tag="handoff")
    if done:
        _hooks().publish()
    return done


# ---- display
def handoff_lines(item: dict[str, Any]) -> list[str]:
    """get's hand-off lines (handoff.words), in the instance's timezone. [] when the item has none or the machinery is off."""
    try:
        return _ho.words(item, time.time(), _cfg.tz(), _session_label, handoff_minutes()) if handoff_on() else []
    except Exception as e:  # noqa: BLE001
        print(f"handoff: {item.get('gid') or item.get('id')} not shown: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return []


def handoff_brief() -> str:
    """The brief's short lines: the hand-offs not yet taken and (a count only) the items from before the machinery whose mover has no pane: moving
    those is the migration's, so they are reported and never touched ("" when none)."""
    if not handoff_on():
        return ""
    try:
        all_open: dict[str, dict[str, Any]] = {}
        for gid, p in _item_files():
            with open(p, encoding="utf-8") as f:
                it = json.load(f)
            if it.get("status") == "open":
                _ip.read_through(it)
                it["gid"] = gid
                all_open[gid] = it
        env = handoff_env(time.time())
        lines = _ho.brief_lines({g: it for g, it in all_open.items() if _ho.record_of(it)}, time.time(), _cfg.tz(), _gh.shown, _session_label, handoff_exempt)
        gone = _ho.gone_unrecorded(all_open, env)
        if gone:
            lines.append(f"mover gone: {len(gone)} item{'' if len(gone) == 1 else 's'} whose mover has no pane " + ("(no hand-off record: the hand-off pass takes them at its next tick)" if _hooks().switchover_on()
                         else "(from before the hand-off machinery; the migration moves them, nothing does now)"))
        if _hooks().switchover_on():           # step 4: an old wait (a hold, an after) no watcher owns waits on the old pass only (switchover_fallback), or on nothing
            loose = [g for g, it in all_open.items() if ((it.get("metadata") or {}).get("hold") or _hooks().after_open(it.get("metadata") or {})) and not _watch.watches(it)]
            if loose:
                lines.append(f"waits no watcher owns: {len(loose)} item{'' if len(loose) == 1 else 's'} ({', '.join(_gh.shown(g) for g in loose[:6])}{', ...' if len(loose) > 6 else ''}) "
                             + ("end by the old wake pass until set by hand" if not _hooks().old_wait_off() else "end only when their mover writes: set the wait's input or end by hand"))
        if handoff_paused():          # a held clock says what it holds: this is what fires, in one batch, when [model] pause is turned off
            n = len(_ho.plan(all_open, env))
            lines.append(f"hand-off clock paused ({'the migration pass holds the board' if _watch.holding() else '[model] pause = true'}): {n} item{'' if n == 1 else 's'} would fire now" + ("" if n else ", none due"))
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        print(f"handoff: brief not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return ""
