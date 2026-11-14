"""migrations.py: the start-up migrations and the passes of the migration route.

Two groups. The start-up migrations (`migrate_needs`, `migrate_owner_mover`, `migrate_holds`) run once per server start, before it serves: each rewrites the open items stored in an older form, keeps their
clocks as they were and says one line per item on standard error. The migration route's passes are what `POST /client/migrate` applies (the route itself stays in web/server.py, behind `migration_gate`): the
plan is made by tools/migrate_model.py and model/migration.py, and this is where it is applied, so the server stays the one writer. Each planned write is a filing edit made under the item lock through
`writes.save`, author `migration`; while a pass runs the server holds the board-wide pause (`watchers.hold`), and `end` lifts it and runs one wake pass.

What they still reach in server.py (the item model's readers, the write path's flags, the stamp, retire and project-id passes the route dispatches to, the publish, the outcomes and the time zone) comes through
`Hooks` in service/passes_hooks.py, looked up when they run. A suite that replaces a function or the clock of the passes sets it here (and `time` here, since this module reads its own).

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core import config as _cfg
from stackshot.core.instance import OWNER
from stackshot.core.store import _item_files
from stackshot.fleet.sessions_registry import _session_label
from stackshot.github import ghsync as _gh
from stackshot.model import last_activity_pass as _lact_pass
from stackshot.model import migration as _mig
from stackshot.model import model as _model
from stackshot.model import model_guards as _mg
from stackshot.model import next_backfill as _nbf
from stackshot.model import nextlines as _nl
from stackshot.model.bullet_text import _clip_line
from stackshot.model.ids import _norm_id
from stackshot.model.needs import _needs_of
from stackshot.service import gates as _gates
from stackshot.service import handoff as _handoff
from stackshot.service import runner as _runner
from stackshot.service import telling as _telling
from stackshot.service import wakes as _wakes
from stackshot.service import writes as _writes
from stackshot.service.passes_hooks import hooks as _hooks
from stackshot.service.store import _legacy_hold, _legacy_needs, _load, _path
from stackshot.waits import handoff as _ho
from stackshot.waits import until_pass as _until_pass
from stackshot.waits import waiting as _wt
from stackshot.waits import watchers as _watch


# ----------------------------------------------------------------------------- the start-up migrations (once per start, before the server serves)
def migrate_needs() -> list[str]:
    """Once, at server start: every open item stored with needs as a word, or with a linked agent (metadata.agent), is
    rewritten: needs a list, the agent in it. Idempotent (an item already in the new form is left alone); `updated` and
    `state_updated` stay as they were, as migrate_holds leaves them. One stderr line per item. → the gids rewritten."""
    out = []
    for gid, p in _item_files():
        try:
            with open(p, encoding="utf-8") as f:
                it = json.load(f)
        except Exception:
            continue
        if it.get("status") != "open" or not _legacy_needs(it):
            continue
        _writes.save(gid, it)
        out.append(gid)
        print(f"migrate: {gid} needs → {it['metadata'].get('needs') or []} (the linked agent, if any, moved into it), clocks unchanged — {it.get('subject')}",
              file=sys.stderr, flush=True)
    return out


def migrate_owner_mover() -> list[str]:
    """Once per start (idempotent, so every start runs it): the rules of _settle_mover_on_save and _handoff.handoff_his_over applied to the items stored before them. An open item that waits on
    him with a session stored as its mover gets him as mover and the session in `then`; one that stores him as mover while no longer in his state, with an answer of his newer than the change of mover to him
    (his hand-off record's time; else the item's last write) as the proof he let it go, gets its `then` agent back as mover (an older answer followed by a deliberate mover=the owner is left); a hand-off record to him that nobody took is ended when an answer of his is on the item after it (a board answer, a comment, a Done) or when the
    item is no longer his to move (some kept a stale hand-over marker after he answered). `updated` and the clocks stay as they were.
    One stderr line per item; nothing is posted to GitHub (mirror off). [model] guards = false skips the mover part, [model] handoff = false the record part. → the gids rewritten."""
    out = []
    after = lambda i_: _hooks().after_open(i_.get("metadata") or {})
    for gid, p in _item_files():
        try:
            with open(p, encoding="utf-8") as f:
                it = json.load(f)
        except Exception:
            continue
        if it.get("status") != "open" or not isinstance(it.get("metadata"), dict):
            continue
        did: list[str] = []
        try:
            if _hooks().model_guards_on():
                rec_ = _ho.record_of(it)
                # the proof that he held it and has let go: an answer of his NEWER than the change of mover to him (his hand-off record's time; with no record, the item's last write, a second before it).
                # An old answer followed by a mover=the owner a writer set later is a deliberate hand-over, not a hand-back to make.
                since = float(rec_.get("at") or 0) if rec_ and _model.is_owner(rec_.get("to")) else float(it.get("updated") or 0) - 1
                his = any(isinstance(a, dict) and float(a.get("ts") or 0) >= since for a in (it["metadata"].get("answers") or []))
                ch = _model.settle(it, his, after)
                if ch:
                    was_mover = _model.norm_who(it["metadata"].get("mover"))
                    _hooks().settle_apply(it["metadata"], ch)
                    did.append(f"mover {was_mover} → {ch['mover'] or 'default'}" + (f", then {ch['then']}" if ch.get("then") else ""))
            r = _ho.pending_his(it) if _handoff.handoff_on() else None
            if r is not None:
                answers = [float(a.get("ts") or 0) for a in (it["metadata"].get("answers") or []) if isinstance(a, dict) and float(a.get("ts") or 0) >= float(r.get("at") or 0)]
                if answers:
                    _ho.answered(it, time.time(), f"{OWNER}'s answer was already on the item", at=min(answers))
                    did.append("his hand-off ended (answered)")
                else:
                    mod = _hooks().model_of({**it, "gid": gid})
                    if not (mod.state == _model.ALIVE and _model.is_owner(mod.mover)):
                        _ho.answered(it, time.time(), f"it is no longer {OWNER}'s to move")
                        did.append("his hand-off ended (not his to move)")
        except Exception as e:  # noqa: BLE001  — one unreadable item never stops the start
            print(f"migrate: {gid} his mover not settled: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
            continue
        if not did:
            continue
        _writes.save(gid, it, mirror=False)         # a start-up pass posts nothing to GitHub (no comment per migrated item)
        out.append(gid)
        print(f"migrate: {gid} {'; '.join(did)}, clocks unchanged — {it.get('subject')}", file=sys.stderr, flush=True)
    return out


def migrate_holds() -> list[str]:
    """Once, at server start: every stored item with the retired status "on_hold" becomes status open + metadata.hold (its
    wake kept). `updated` and `state_updated` stay as they were: a migration is not a state change, and the renderer orders
    by the item clock. One stderr line per item. → the gids rewritten."""
    out = []
    for gid, p in _item_files():
        try:
            with open(p, encoding="utf-8") as f:
                it = json.load(f)
        except Exception:
            continue
        if not _legacy_hold(it):
            continue
        _writes.save(gid, it)
        out.append(gid)
        print(f"migrate: {gid} status on_hold → open + metadata.hold (wake {it['metadata'].get('wake') or 'none'}), clocks unchanged — {it.get('subject')}",
              file=sys.stderr, flush=True)
    return out


# ----------------------------------------------------------------------------- the migration onto the item model (migration.py, tools/migrate_model.py)
# tools/migrate_model.py PLANS (the items, the guards' residue, the cold call's reads); this is where the plan is APPLIED, so the server stays the one writer: POST /client/migrate, the
# machine token's route like /client/state. Each planned write is a filing edit made under the item lock through `writes.save`, author `migration`, so the History,
# the search and the For you list update as for any write, and no clock moves. It is not `_update`: it records no hand-off (the author is a script's), tells nobody (no needs notice, no
# page debt) and sends nothing. While the pass runs the server holds the board-wide pause itself (watchers.hold: in this process, renewed by every batch, gone after a few minutes if the
# script dies), so no wake fires, no wait ends, no hand-off clock runs and the checks and the For you ticks stand still; `end` lifts it and runs one wake pass, so
# what came due fires in one batch, one message per recipient. A write the guards refuse is reported as refused and not forced; an item that moved since it was planned is reported as moved.
def migration_outcomes() -> tuple[str, ...]:
    """What a back-filled close may carry: the outcomes of the surface, and `unrecorded`, which this pass writes only (gates.gate_close refuses it on every new close)."""
    return (*_hooks().outcomes(), "unrecorded")
MIGRATE_HOLD_S = 600.0       # each begin / apply renews the pass's hold for this long, and never past watchers.HOLD_CEILING_S (an hour) from its begin
MIGRATE_SENDERS: list[str] = []     # the default of [model] migration_senders: no session runs the pass until the instance names them
MIGRATE_MACHINES: list[str] = []                                                        # ... and of migration_machines (none until the instance names them): the machines whose token may


def migration_on() -> bool:
    """[model] migration (default false): the route of the migration pass answers only while this is true. The operator turns it on for the run and off after."""
    return bool(_cfg.get("model", "migration", default=False))


def model_names(key: str, default: list[str]) -> list[str]:
    v = _cfg.get("model", key, default=default)
    if isinstance(v, str):
        v = [v]
    return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []


MIGRATE_OFF = ("refused: the migration route is off ([model] migration = false). It is turned on for the run and off after, by the operator; the script cannot")
MIGRATE_NOT_YOU = ("refused: only the sessions in [model] migration_senders may run the migration pass, from a machine in migration_machines: `sender` must be one of them "
                    "and the token must be that machine's")


def migration_gate(machine: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]] | None:
    """The gate of POST /client/migrate, before anything is read: 403 while [model] migration is off, 403 for a sender not in [model] migration_senders or a token whose machine is not in
    migration_machines (a label alone proves nothing: any token holder can type it; the For you form's rule). None when the call may go on."""
    if not migration_on():
        return 403, {"error": MIGRATE_OFF}
    sender = " ".join(str(body.get("sender") or "").split())
    if not sender or sender not in model_names("migration_senders", MIGRATE_SENDERS) or not machine or machine not in model_names("migration_machines", MIGRATE_MACHINES):
        return 403, {"error": MIGRATE_NOT_YOU}
    return None


def migrate_sig(gid: str, item: dict[str, Any]) -> list[int]:
    """What an answer or a comment changes without moving `updated`: [the item's answers, 0] (migration.activity_sig). The owner's comment on GitHub is an answer on the item (via github), so the second place is kept at 0 since the mirror stopped copying the issue's comments. A write is planned on it and checked against it again under the item lock."""
    return _mig.activity_sig(item, 0)


def migrate_backfill(gid: str, shown: str, w: dict[str, Any]) -> dict[str, Any]:
    """The write `{item, backfill: "owner_steps", expect, expect_sig}`: the done steps of his past decisions, worked out HERE from the item's own saved answers (next_backfill.apply); the caller
    sends no text, so nothing typed is ever stored. An open item only; the same `expect` and `expect_sig` checks as any migration write, so an item written or answered since it was planned is `moved`. Nothing
    to add → `already`, so a second run changes nothing. A filing edit as the others: `updated`, the state clock and the confirm stay, and the author is `migration`."""
    if w.get("backfill") != "owner_steps":
        return _mig.refuse(shown, "backfill = owner_steps is the only fill-in there is")
    try:
        exp = float(w["expect"])
        if isinstance(w["expect"], bool) or not math.isfinite(exp):
            raise ValueError("not finite")
    except (KeyError, TypeError, ValueError):
        return _mig.refuse(shown, "expect is required: the item's `updated` when it was planned (a finite number), so a write over a change made since is never made")
    sig = w.get("expect_sig")
    if not (isinstance(sig, list) and len(sig) == 2 and all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in sig)):
        return _mig.refuse(shown, "expect_sig is required: [how many answers the item held, 0] when it was planned, so an answer made since is never overwritten")
    try:
        with _writes.ITEM_LOCK:
            item = _load(gid)
            if item.get("status") != "open":
                return _mig.refuse(shown, f"the item is {item.get('status')}: a closed item is left as it is")
            if abs(float(item.get("updated") or 0) - exp) > 1e-6:
                return {"item": shown, "action": "moved", "why": "the item was written since it was planned: planned again, never overwritten"}
            if migrate_sig(gid, item) != sig:
                return {"item": shown, "action": "moved", "why": "an answer or a comment arrived on the item since it was planned (neither moves `updated`): planned again, never overwritten"}
            meta = json.loads(json.dumps(item.get("metadata") or {}, default=str))
            added = _nbf.apply(meta, _nbf.plan(meta, "open", str(meta.get("owner") or "")), str(meta.get("owner") or ""))
            if not added:
                return {"item": shown, "action": "already", "why": ""}
            item["metadata"] = meta
            note = f"his past decisions filled in as done steps ({added})"
            _writes.save(gid, item, note=note, author=(_mig.AUTHOR, _mig.AUTHOR), mirror=bool(_gh.issue_of(gid)))
        return {"item": shown, "action": "set", "why": note, "added": added}
    except ToolError as e:
        return _mig.refuse(shown, str(e))
    except Exception as e:  # noqa: BLE001  — one write that fails never stops the batch
        print(f"migrate: {gid} backfill not written: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return _mig.refuse(shown, f"{e.__class__.__name__}: {str(e)[:200]}")


def migrate_one(w: dict[str, Any]) -> dict[str, Any]:
    """One planned write → {"item", "action": set | already | moved | refused, "why"}. `w` = {item, set, drop, expect, kind, note}; `expect` (the item's `updated` when it was planned, 0 for an item that has none) is required: a write
    with none is refused, and one that no longer matches is `moved`. An open item takes the fields of migration.OPEN_SET_FIELDS, a closed one only its outcome (OUTCOME_FIELDS)."""
    if not isinstance(w, dict):
        return _mig.refuse("?", "a write is an object")
    try:
        gid = _norm_id(str(w.get("item") or ""))
    except ToolError as e:
        return _mig.refuse(str(w.get("item") or "?"), str(e))
    shown = _gh.shown(gid)
    if w.get("backfill"):
        return migrate_backfill(gid, shown, w)
    sets, drops = w.get("set") or {}, w.get("drop") or []
    if not isinstance(sets, dict) or not isinstance(drops, list):
        return _mig.refuse(shown, "set is an object and drop a list")
    bad = [k for k in sets if k not in _mig.SET_FIELDS] + [k for k in drops if k not in _mig.DROP_FIELDS]
    if bad:
        return _mig.refuse(shown, f"the migration may not set or drop {', '.join(sorted(set(map(str, bad))))}")
    try:
        exp = float(w["expect"])           # 0 is what an item with no `updated` is planned with; absent, not a number, NaN or infinite is no expectation at all (NaN compares as equal to nothing, so it would skip the check)
        if isinstance(w["expect"], bool) or not math.isfinite(exp):
            raise ValueError("not finite")
    except (KeyError, TypeError, ValueError):
        return _mig.refuse(shown, "expect is required: the item's `updated` when it was planned (a finite number), so a write over a change made since is never made")
    sig = w.get("expect_sig")
    if not (isinstance(sig, list) and len(sig) == 2 and all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in sig)):
        return _mig.refuse(shown, "expect_sig is required: [how many answers the item held, 0] when it was planned, so an answer made since is never overwritten")
    note = _clip_line(str(w.get("note") or w.get("kind") or "migrated onto the item model"), 300)
    sets = dict(sets)
    try:
        with _writes.ITEM_LOCK:
            item = _load(gid)
            if abs(float(item.get("updated") or 0) - exp) > 1e-6:
                return {"item": shown, "action": "moved", "why": "the item was written since it was planned: planned again, never overwritten"}
            if migrate_sig(gid, item) != sig:
                return {"item": shown, "action": "moved", "why": "an answer or a comment arrived on the item since it was planned (neither moves `updated`): planned again, never overwritten"}
            was = json.dumps(item.get("metadata") or {}, sort_keys=True, default=str)
            meta = json.loads(was)
            if item.get("status") == "completed":
                extra = [k for k in (*sets, *drops) if k not in _mig.OUTCOME_FIELDS]
                if extra or meta.get("outcome") or str(sets.get("outcome") or "") not in migration_outcomes():
                    return {"item": shown, "action": "already" if meta.get("outcome") and not extra else "refused",
                            "why": "it already has an outcome" if meta.get("outcome") and not extra else "a closed item takes an outcome (done | dropped | superseded | unrecorded), its reason and superseded_by only"}
                sup = str(sets.get("superseded_by") or "")
                if (sets["outcome"] == "superseded") != bool(sup):
                    return _mig.refuse(shown, "superseded_by goes with outcome superseded, and only with it")
                if sup:
                    try:
                        sets["superseded_by"] = sup = _norm_id(sup)
                    except ToolError as e:
                        return _mig.refuse(shown, str(e))
                    if sup == gid or not _path(sup).exists():
                        return _mig.refuse(shown, "an item is not its own duplicate, and the item it duplicates must exist")
                if "reason" in sets:
                    sets["reason"] = _clip_line(" ".join(str(sets["reason"]).split()), 300)         # one line
                for k in drops:
                    meta.pop(k, None)
                meta.update(sets)
            else:
                if item.get("status") != "open":
                    return _mig.refuse(shown, f"the item is {item.get('status')}")
                late = [k for k in (*sets, *drops) if k in _mig.OUTCOME_FIELDS]
                if late:
                    return _mig.refuse(shown, f"an open item takes no {', '.join(sorted(set(late)))}: an outcome is a closed item's")
                probs = _model.check_fields({k: v for k, v in sets.items() if k in _model.MODEL_FIELDS})
                if "needs" in sets and not (isinstance(sets["needs"], list) and len(sets["needs"]) == 1 and isinstance(sets["needs"][0], str) and sets["needs"][0].strip()):
                    probs.append("needs is the one session that moves the item now")
                if probs:
                    return _mig.refuse(shown, "; ".join(probs))
                for k in drops:
                    meta.pop(k, None)
                meta.update({k: v for k, v in sets.items() if k not in ("cap_ok", "wait_basis")})
                if "next" in sets or "next" in drops:
                    _nl.carry(json.loads(was), meta, str(meta.get("owner") or ""))      # the lines it named keep their writers (by position), else the keeper's
                if "cap_ok" in sets:        # his words are copied from the item's own stored answers, here: a value the caller sends is never taken as it comes
                    cand = {**item, "metadata": meta}
                    entry = _mig.park_quote(cand, time.time())
                    if not entry:
                        return _mig.refuse(shown, "no stored words of his stand behind this item's wake: cap_ok is copied from his answer on the item, never typed")
                    meta["cap_ok"] = _mig.cap_ok_from(cand, entry)
                if "wait_basis" in sets:
                    wb = sets["wait_basis"]
                    wake_now = str(meta.get("wake") or "")
                    prob = ""
                    if not (isinstance(wb, dict) and set(wb) <= {"text", "wake", "by", "at"} and _model.clean(wb.get("text")) and wb.get("by") == _mig.AUTHOR and str(wb.get("wake") or "") == wake_now):
                        prob = "wait_basis is {text, wake, by: migration, at} and its wake is the item's wake"
                    else:
                        try:
                            prob = _wt.basis_problem(str(wb["text"]), dt.date.fromisoformat(wake_now[:10]))
                        except ValueError:
                            prob = "its wake is no date"
                    if prob:
                        return _mig.refuse(shown, f"wait_basis refused: {prob}")
                    meta["wait_basis"] = {"text": _clip_line(" ".join(str(wb["text"]).split()), 300), "wake": wake_now, "by": _mig.AUTHOR, "at": wb.get("at")}
                if json.dumps(meta, sort_keys=True, default=str) != was:
                    item_was = {**item, "metadata": json.loads(was)}
                    _hooks().watch_on_write(gid, item_was, meta, {}, set(), "", False)       # a wait newly stored stamps its time (an older notice is not its arrival)
                    w_new = meta.get("watch") if isinstance(meta.get("watch"), dict) else {}
                    w_old = (item_was["metadata"].get("watch") or {}) if isinstance(item_was["metadata"].get("watch"), dict) else {}
                    if _watch.stored_kind(meta) == "anchor" and w_new.get("set_at") and w_new.get("set_at") != w_old.get("set_at"):
                        # a migrated anchor wait counts what the anchor log holds since the item's last move: the notices from before the pass are its arrivals, not lost to a stamp of now
                        w_new["set_at"] = float(item.get("state_updated") or item.get("updated") or 0) or w_new["set_at"]
                    touched = set(sets) | set(drops)
                    if touched & (set(_model.MODEL_FIELDS) | {"wake", "hold", "after"}):
                        touched |= _mg.STATE_FIELDS                                          # what defines the state: its invariants are judged whole, as an update that sets them would
                    item_now = {**item, "metadata": meta}
                    _gates.gate_model(item_now, touched, gid, needs=_needs_of(meta), hold=bool(meta.get("hold")), strict=True, windows_text="", defers_text="")
            if json.dumps(meta, sort_keys=True, default=str) == was:
                return {"item": shown, "action": "already", "why": ""}
            item["metadata"] = meta                    # a filing edit: `updated`, the state clock and the confirm stay where they were
            _writes.save(gid, item, note=note, author=(_mig.AUTHOR, _mig.AUTHOR), mirror=bool(_gh.issue_of(gid)))     # an item with no issue is never mirrored: a job for it would create one
        return {"item": shown, "action": "set", "why": note}
    except ToolError as e:
        return _mig.refuse(shown, str(e))
    except Exception as e:  # noqa: BLE001  — one write that fails never stops the batch
        print(f"migrate: {gid} not written: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return _mig.refuse(shown, f"{e.__class__.__name__}: {str(e)[:200]}")


WAKE_HEAD = "[stackshot] The item model migration pass finished."
WAKE_FIELD_KEYS = ("wait_anchor", "wait_event", "after", "wake", "ask_by", "post_wake_mover", "waits", "wait_mode")


WAKE_KINDS = frozenset({"wait_input", "no_end", "post_wake", "default_end", "anchor_seen"})
DATE_RX = re.compile(r"\d{4}-\d{2}-\d{2}")


def date_only(v: Any) -> str:
    """The day (YYYY-MM-DD) a value starts with, else "": a date is the only thing a row's `default` may carry into a text."""
    v = str(v or "").strip()[:10]
    return v if DATE_RX.fullmatch(v) else ""


def migrate_wake_row(gid: str, item: dict[str, Any], hint: dict[str, Any]) -> "_mig.Residue | None":
    """The residue row for one item, derived HERE from the item as it is stored. The row a caller hands in (the plan's, or rows.json's after a crash) is only a hint of which item to look at and what
    kind of row to build: nothing it says goes into a text. The kind must be one of WAKE_KINDS; the fields are those the hint names that are in WAKE_FIELD_KEYS and are still unset on the item;
    a default_end row is built from the stored ask_by (a date) and stands only when the hint's default is that same day; an anchor_seen row from the stored anchor wait and a notice count (a number);
    a wait_anchor row's note of the anchors scoped to the item from the anchors file. → None when the row no longer stands."""
    meta = item.get("metadata") or {}
    kind = str(hint.get("kind") or "")
    if kind not in WAKE_KINDS:
        return None
    if kind == "default_end":
        stored = date_only(meta.get("ask_by"))
        return _mig.Residue(gid, kind, "", False, ("ask_by",), stored) if stored and date_only(hint.get("default")) == stored else None
    if kind == "anchor_seen":
        url = " ".join(str(meta.get("wait_anchor") or "").split())[:300]
        try:
            n = max(1, min(int(str(hint.get("default") or "1")), 999))
        except ValueError:
            n = 1
        if str(meta.get("wait_kind") or "").lower() != "anchor" or not url or url not in str(hint.get("why") or ""):       # the hint's own words are only compared (is it about the anchor the item stores?), never copied
            return None
        return _mig.Residue(gid, kind, _mig.anchor_seen_why(url, n), False, (), str(n))
    hint_fields = hint.get("fields") if isinstance(hint.get("fields"), list) else []
    fields = tuple(f for f in dict.fromkeys(str(x) for x in hint_fields) if f in WAKE_FIELD_KEYS and not meta.get(f))
    if not fields:
        return None
    default = date_only(hint.get("default")) if "ask_by" in fields else ""
    why = ""
    if fields == ("wait_anchor",):
        urls = [" ".join(str(e.get("url") or "").split())[:200] for e in _hooks().scoped_anchors(str(meta.get("project") or ""), gid) if e.get("url")]
        if len(urls) > 1:
            why = f"{len(urls)} anchors are scoped to it ({', '.join(urls)}) and none could be picked from its text"
    return _mig.Residue(gid, kind, why, True, fields, default)


def migrate_wake(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The wake at the end of the pass: the residue that needs a person's field, per mover, one message each with the exact field. `rows` = migration.Residue.as_dict() of the items with a field to
    set (or a default ask_by to replace, or notices already on an anchor): each is only a hint of an item and a kind, and every row of the text is derived here from the item as stored
    (migrate_wake_row), so a row handed in carries no text of its own into a message. The mover is who the item's own notices go
    to first (its mover, or the keeper of a front agent's page; _wakes.reminder_to). Nothing is sent here: the pass writes the texts down for a person to read, and `send_wake` sends them.
    → {mover's label: {"sid", "gids", "text"}}; an item with nobody to tell is listed under "nobody" (with no sid)."""
    by_owner: dict[str, dict[str, Any]] = {}
    for r in rows:
        try:
            gid = _norm_id(str(r.get("item") or ""))
            item = _load(gid)
        except ToolError:
            continue
        if item.get("status") != "open":
            continue
        meta = item.get("metadata") or {}
        res = migrate_wake_row(gid, item, r)
        if res is None:
            continue
        who = _wakes.reminder_to(meta)
        sid, label = (who[0][0], _session_label(who[0][0])) if who else ("", "nobody")
        e = by_owner.setdefault(label, {"sid": sid, "hand": {}, "lines": [], "gids": [], "subject": {}})
        e["subject"][gid] = str(item.get("subject") or "")
        if gid not in e["gids"]:
            e["gids"].append(gid)
        if res.kind in ("default_end", "anchor_seen"):
            e["lines"].append(res)                      # a default to replace and the notices already on an anchor are each their own line
        elif gid in e["hand"]:                          # an item's missing fields (its input and its end) are one line, not two
            cur = e["hand"][gid]
            cur.fields = tuple(dict.fromkeys([*cur.fields, *res.fields]))
            cur.default = cur.default or res.default
            cur.why = cur.why if cur.kind == "wait_input" else res.why
            cur.kind = "wait_input" if "wait_input" in (cur.kind, res.kind) else cur.kind
        else:
            e["hand"][gid] = res
    out: dict[str, dict[str, Any]] = {}
    for label, e in by_owner.items():
        lines = [_mig.wake_row(_gh.shown(r.gid), e["subject"][r.gid], r) for r in [*e["hand"].values(), *e["lines"]]]
        out[label] = {"sid": e["sid"], "gids": list(e["gids"]), "text": _mig.wake_text(label, lines, len(e["gids"]))}
    return out


MIG_PASS = {"id": "", "by": ""}         # the pass the board-wide hold belongs to (begin sets it; a restart loses it with the hold)
MIG_PASS_LOCK = threading.Lock()


def pass_path(pass_id: str) -> Path:
    """<state>/migration/<pass id>.json: what a pass stored on the server, out of the item store: {pass_id, by, begun, ended, owners: {label: {sid, gids, text, sent}}}."""
    if not _mig.PASS_ID_RX.fullmatch(str(pass_id or "")):
        raise ToolError("Refused: pass_id is the id `begin` returned")
    return _cfg.state("migration", f"{pass_id}.json")


def pass_load(pass_id: str) -> dict[str, Any]:
    try:
        d = json.loads(pass_path(pass_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = None
    if not isinstance(d, dict):
        raise ToolError(f"Refused: no pass {pass_id} is stored on this server")
    return d


def pass_save(rec: dict[str, Any]) -> None:
    p = pass_path(str(rec.get("pass_id") or ""))
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp")
    tmp.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def owners_view(rec: dict[str, Any]) -> dict[str, Any]:
    return {k: {"sid": v.get("sid", ""), "gids": v.get("gids", []), "text": v.get("text", ""), "sent": v.get("sent")} for k, v in (rec.get("owners") or {}).items()}


def migrate_wake_text(spec: dict[str, Any]) -> dict[str, Any]:
    """op wake_text {pass_id, rows?}: the per-owner texts a pass stored at its `end` (with whether each was sent), for a person to read. A pass whose `end` never came back (the script died, the answer was lost)
    has none yet: with the `rows` the script wrote down before it called `end`, the texts are built now, from the items as stored, and kept; that waits until the pass no longer holds the board."""
    pid = str(spec.get("pass_id") or "")
    with MIG_PASS_LOCK:
        rec = pass_load(pid)
        if rec.get("owners") is None:
            rows = spec.get("rows")
            if not isinstance(rows, list):
                raise ToolError(f"Refused: pass {pid} has no stored texts: its `end` did not complete; send the rows the script wrote down before it (rows) to build them")
            if MIG_PASS["id"] == pid and _watch.holding():
                raise ToolError(f"Refused: pass {pid} still holds the board; end it first (or wait for its hold to lapse)")
            rows = [r for r in rows if isinstance(r, dict) and (r.get("fields") or r.get("kind") == "anchor_seen")]
            rec["owners"] = {k: {**v, "sent": None} for k, v in (migrate_wake(rows) if rows else {}).items()}
            rec["ended"] = rec.get("ended") or time.time()
            rec["rebuilt"] = True
            pass_save(rec)
        return {"op": "wake_text", "pass_id": pid, "owners": owners_view(rec)}


def migrate_send_wake(spec: dict[str, Any], by: str) -> dict[str, Any]:
    """op send_wake {pass_id, owner, note?}: one owner's stored text, after a person has read it: the text the server generated and stored at the pass's `end` plus an optional note of one line (at most
    200 characters), sent to the session the items' own notices go to (each item must still be open with that session among them, _wakes.reminder_to). The send is marked on the server before it goes, and an
    owner already marked is refused: a pass tells an owner once. Free text is never sent."""
    pid, label = str(spec.get("pass_id") or ""), str(spec.get("owner") or "")
    note = spec.get("note")
    if note not in (None, ""):
        if not isinstance(note, str) or "\n" in note or "\r" in note or len(note) > 200:
            raise ToolError("Refused: note is one line of at most 200 characters")
        note = note.strip()
    with MIG_PASS_LOCK:
        rec = pass_load(pid)
        ent = (rec.get("owners") or {}).get(label)
        if not isinstance(ent, dict):
            raise ToolError(f"Refused: pass {pid} stored no text for {label!r}")
        if ent.get("sent"):
            raise ToolError(f"Refused: the text for {label} of pass {pid} was already sent ({ent['sent'].get('at') if isinstance(ent['sent'], dict) else ent['sent']})")
        sid, gids = str(ent.get("sid") or ""), [str(g) for g in ent.get("gids") or []]
        if not sid or not gids:
            raise ToolError(f"Refused: {label} has nobody to send to")
        for gid in gids:
            item = _load(_norm_id(gid))
            if item.get("status") != "open":
                raise ToolError(f"Refused: {_gh.shown(gid)} is not open")
            if sid not in [x for x, _w in _wakes.reminder_to(item.get("metadata") or {})]:
                raise ToolError(f"Refused: {_gh.shown(gid)}'s own notices do not go to that session")
        text = str(ent.get("text") or "") + (f"\n\nNote from {by.split(' via ')[0]}: {note}" if note else "")
        ent["sent"] = {"at": dt.datetime.now(_hooks().zone()).isoformat(timespec="seconds"), "by": by, "note": note or ""}
        pass_save(rec)            # marked before it goes: a second caller meanwhile is refused; a failure below clears the mark
        outcome: dict[str, Any] = {}
        th = _telling.tell_woken(",".join(_norm_id(g) for g in gids), sid, text, tag="migration", result=outcome)
        if th is not None:
            th.join(timeout=120)
        if not outcome.get("ok"):
            why = str(outcome.get("why") or ("no answer from the push within 120 s: it may still arrive, so look before sending again" if th is not None else "nobody to send to"))
            ent["sent"] = None
            pass_save(rec)
            print(f"migrate: the residue wake for {label} (pass {pid}) NOT delivered: {why}", file=sys.stderr, flush=True)
            return {"op": "send_wake", "pass_id": pid, "owner": label, "sent": False, "why": why, "items": len(gids)}
    print(f"migrate: the residue wake for {label} (pass {pid}) delivered ({len(gids)} item(s))", file=sys.stderr, flush=True)
    return {"op": "send_wake", "pass_id": pid, "owner": label, "sent": True, "items": len(gids), "at": ent["sent"]["at"]}


def migrate_write(spec: dict[str, Any], machine: str) -> dict[str, Any]:
    """POST /client/migrate (the machine token's, behind migration_gate): `op` = begin | apply | end, and `sender` = the session that runs the pass.
      stamp / unstamp   the stamp pass (tools/stamp_phase.py): metadata.phase and metadata.waits_on written on the open items, and put back; no begin, no hold, nothing else written (_stamp_write_op)
      retire / unretire the retire pass (tools/retire_fields_report.py --apply / --undo): the stored state words and carry fields taken out of the open items, each moved to its home, and put back (_retire_write_op)
      until / ununtil   the until pass (tools/until_migrate.py --apply / --undo): the waits stored as wake, ask_by and hold rewritten as `until` (until_pass.py), one History line each, and put back (until_pass.write_op)
      lastact / unlastact the last-activity pass (tools/last_activity_backfill.py --apply / --undo): metadata.last_activity filled from the History for the open items that have none, nothing else written, and put back (last_activity_pass.write_op)
      project_id / unproject_id the project-id pass (tools/project_id_report.py --apply / --undo): the permanent id of the item's project stored on every item, open or closed, and put back (_pid_write_op)
      begin   holds the board-wide pause for the pass (for at most an hour, whatever renews it) and says what the server's switches are ({guards, pause, switchover, handoff, held}); the pass stops
              when the guards are off, since it must be judged by them; a second caller's begin while another's pass holds the board is refused
      apply   `writes` (at most _mig.BATCH): each applied through the normal save path, author `migration`, judged by the guards; only the caller that began the pass; the hold is renewed → {"results": [...]}
      end     only the caller that began the pass: lifts the hold (never the config's own `[model] pause`) and runs one wake pass, so what came due fires in one batch; `residue` (the plan's rows with a
              field to set) is turned into one text per owner, the exact field per item, kept on the server under the pass's id (<state>/migration/<id>.json), and NOT sent
              → {"pass_id", "fired": [...], "wake": {owner: text}, "wake_detail": {owner: {sid, gids, text}}, "held": bool}
      wake_text  {pass_id, rows?}: the stored texts and which were sent; with `rows` it builds them for a pass whose `end` never completed (the route's gate applies, no pass need be held)
      send_wake  {pass_id, owner, note?}: that owner's stored text plus the note (one line, 200 characters), sent once, marked on the server; no other text goes out
    Refusals raise ToolError (the route answers 400)."""
    by = _hooks().script_sender(spec, machine)
    _hooks().sender_not_owner(str(spec.get("sender") or ""))
    op = str(spec.get("op") or "apply")
    state = lambda: {"guards": _hooks().model_guards_on(), "pause": bool(_cfg.get("model", "pause", default=False)), "switchover": _hooks().switchover_on(), "handoff": _handoff.handoff_on(),
                     "watchers": _watch.enabled(), "held": _watch.holding(), "by": by}
    if op not in ("begin", "apply", "end", "wake_text", "send_wake", "stamp", "unstamp", "retire", "unretire", "project_id", "unproject_id", "until", "ununtil", "lastact", "unlastact"):
        raise ToolError("Refused: op = begin | apply | end | wake_text | send_wake | stamp | unstamp | retire | unretire | project_id | unproject_id | until | ununtil | lastact | unlastact")
    if op in ("stamp", "unstamp"):
        return _hooks().stamp_write_op(spec, op, by)
    if op in ("retire", "unretire"):
        return _hooks().retire_write_op(spec, op, by)
    if op in ("project_id", "unproject_id"):
        return _hooks().pid_write_op(spec, op, by)
    if op in ("until", "ununtil"):
        return _until_pass.write_op(_hooks().server_module(), spec, op, by)
    if op in ("lastact", "unlastact"):
        return _lact_pass.write_op(_hooks().server_module(), spec, op, by)
    if op == "wake_text":
        return migrate_wake_text(spec)
    if op == "send_wake":
        return migrate_send_wake(spec, by)
    holder = _watch.holder()
    if op == "begin":
        if not _hooks().model_guards_on():
            raise ToolError("Refused: [model] guards is false; the migration is judged by the guards and does not run without them")
        if holder and holder != by:
            raise ToolError(f"Refused: a pass begun by {holder} holds the board; it ends with its `end`, or lapses within an hour of its begin")
        _watch.hold(by, MIGRATE_HOLD_S, begin=True)
        pass_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{os.urandom(3).hex()}"
        MIG_PASS.update(id=pass_id, by=by)
        pass_save({"pass_id": pass_id, "by": by, "begun": time.time(), "ended": None, "owners": None})
        print(f"migrate: pass {pass_id} begun by {by}; the board-wide pause is held (an hour at most)", file=sys.stderr, flush=True)
        return {"op": op, "pass_id": pass_id, **state()}
    if not holder:
        raise ToolError("Refused: begin the pass first (op=begin): the writes go in with the board-wide pause held, and a hold lapses an hour after its begin")
    if holder != by:
        raise ToolError(f"Refused: the pass was begun by {holder}; only that caller applies its writes or ends it")
    if op == "end":
        pass_id = MIG_PASS["id"] if MIG_PASS["by"] == by else ""
        _watch.release()
        fired: list[str] = []
        try:
            fired = list(_wakes.wake_pass())
        except Exception as e:  # noqa: BLE001
            print(f"migrate: the wake pass after the pass failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        _runner.WAKE_EVENT.set()
        rows = [r for r in (spec.get("residue") or []) if isinstance(r, dict) and (r.get("fields") or r.get("kind") == "anchor_seen")]
        detail = migrate_wake(rows) if rows else {}
        if pass_id:
            with MIG_PASS_LOCK:
                try:
                    rec = pass_load(pass_id)
                    rec["owners"] = {k: {**v, "sent": None} for k, v in detail.items()}
                    rec["ended"] = time.time()
                    pass_save(rec)
                except ToolError as e:
                    print(f"migrate: the texts of pass {pass_id} could not be kept: {e}", file=sys.stderr, flush=True)
        print(f"migrate: pass {pass_id} ended by {by}; the pause lifted, {len(fired)} item(s) fired in one pass, {len(detail)} owner text(s) kept for a person to read (none sent)", file=sys.stderr, flush=True)
        return {"op": op, "pass_id": pass_id, "fired": [_gh.shown(g) for g in fired], "wake": {k: v["text"] for k, v in detail.items()}, "wake_detail": detail, **state()}
    if not _hooks().model_guards_on():
        raise ToolError("Refused: [model] guards is false; the migration is judged by the guards and does not run without them")
    ws = spec.get("writes")
    if not isinstance(ws, list) or not ws or len(ws) > _mig.BATCH:
        raise ToolError(f"Refused: writes is a list of 1 to {_mig.BATCH} planned writes")
    _watch.hold(by, MIGRATE_HOLD_S)
    results = [migrate_one(w) for w in ws]
    if any(r["action"] == "set" for r in results):
        _hooks().publish()
    return {"op": op, "results": results, "held": _watch.holding()}
