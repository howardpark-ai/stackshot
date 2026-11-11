"""until_pass.py: the data change that rewrites the waits stored before `until` as `until` (until_write.py has the mapping; tools/until_migrate.py runs it).

Items stored before the until writers carry a wait in the old fields: `wake`, `ask_by` and `hold`. The writers store the same wait as one date, `until`, and a `wait_kind` where the old fields
imply one. This pass gives a stored item the form the writers would give the same wait today, through their own `fold` (until_write.py), and nothing else: it is not a second mapping.

What a stored item gets (`plan_for`; the server's `one` refuses any item whose reading would change):
  wake (+ hold)        until = the wake, the hold flag and its stamp gone (a wait on the date alone, or the stored kind time); a hold that waits on an anchor scoped to the item or on a pane recycle keeps its flag
  ask_by, wait_kind    until = the ask-by day (a relay), or the earlier of ask_by and wake (an anchor, item or event wait); the kind stays
  ask_by / wake beside an after link with no kind    until = the date, wait_kind = item (as create and update store it)
  a bare wake (no hold, no kind, no wait_basis, no after link)    kept as it is: it is a backstop (a hand-off's, or one stored before until), not a wait, and as `until` it would park the item
  an item with no old date, or one that stores an until and an old date both    left as it is (the second is listed)
A rewritten item also gets one History line (metadata.stall.log, shown as "stackshot: ..."), which says the wait was rewritten as until; no other key changes, no clock moves, nobody is told.

Pure functions of a metadata dict and callbacks: no server import. `entry_for` builds the undo entry (the keys before and after), `apply_edits` the new item."""
from __future__ import annotations

import copy
import sys
import time
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.model import ids as _ids
from stackshot.waits import stall as _stall
from stackshot.waits import until_write as _uw
from stackshot.waits import waiting as _wt

KEYS = ("until", "wait_kind", "wake", "ask_by", "hold", "hold_set")       # the wait keys the pass may change
ENTRY_KEYS = frozenset((*KEYS, "stall"))                                   # what an undo entry may name (stall: the History line)
HISTORY_MAX = 240


def clean(v: Any) -> str:
    return " ".join(str(v or "").split())


def _dated(v: Any) -> str:
    s = clean(v)
    return s if s and _wt.wake_epoch(s) is not None else ""


def old_form(meta: dict[str, Any]) -> str:
    """The old fields an item stores, in words: "wake", "hold + wake", "ask_by", "wake + ask_by" … ("" when it stores none of them)."""
    parts = [n for n, on in (("hold", bool(meta.get("hold"))), ("wake", bool(clean(meta.get("wake")))), ("ask_by", bool(clean(meta.get("ask_by"))))) if on]
    return " + ".join(parts)


def plan_for(meta: dict[str, Any], keeps_hold: bool = False) -> dict[str, Any]:
    """The plan for one open item → {"edits": {key: new value, None drops}, "form": the old fields in words, "new": what the wait is stored as, "kept": why it is left (""), "listed": True when the kept item is
    to be listed for a person}. `keeps_hold`: the hold waits on an anchor scoped to the item or on a pane recycle (the flag stays). Pure."""
    form = old_form(meta)
    out: dict[str, Any] = {"edits": {}, "form": form, "new": "", "kept": "", "listed": False}
    if not _dated(meta.get("wake")) and not _dated(meta.get("ask_by")):
        out["kept"] = "no old date stored" if not form else "no old date to fold"
        return out
    if _wt.stored_until(meta):
        out.update(kept="an until and an old date field are both stored: left as it is", listed=True)
        return out
    if _uw.is_bare(meta):
        out["kept"] = "a bare date is a backstop (a hand-off's, or one stored before until), not a wait: kept as it is"
        return out
    work = copy.deepcopy(meta)
    if _wt.after_of(work) and not _uw.kind_of(work) and _uw.date_of(work):
        work["wait_kind"] = "item"                       # a date beside an after link with no kind is that wait's backstop; the writers store the kind item
    wake_before = _wt.wake_value(meta)
    hold_set = work.get("hold_set")
    u = _uw.fold(work)
    if not u:
        out["kept"] = "no date to fold"
        return out
    if (meta.get("wait_basis") or meta.get("cap_ok")) and clean(wake_before) != u:
        out.update(kept="a reason or an approval is bound to another date than the one the wait is stored as: left as it is", listed=True)
        return out
    if keeps_hold and meta.get("hold"):
        work["hold"] = True
        if hold_set is not None:
            work["hold_set"] = hold_set
    edits: dict[str, Any] = {}
    for k in KEYS:
        if work.get(k) != meta.get(k) and (k in work or k in meta):
            edits[k] = work.get(k)
    out["edits"] = edits
    kind = clean(work.get("wait_kind"))
    out["new"] = f"until={u}" + (f", wait_kind={kind}" if kind else "")
    return out


def history_line(plan: dict[str, Any]) -> str:
    """The History line of a rewritten wait: that it was rewritten as until, from which fields, and that nothing else changed."""
    return f"the stored wait was rewritten as {plan['new']} (it was {plan['form']}); nothing else on the item changed"[:HISTORY_MAX]


def with_history(meta: dict[str, Any], plan: dict[str, Any], now: float) -> dict[str, Any]:
    """The plan with the History line added to its edits (the `stall` log as it will stand). A plan with no edits is returned as it is."""
    if not plan["edits"]:
        return plan
    probe = copy.deepcopy(meta)
    _stall.note(probe, now, history_line(plan))
    return {**plan, "edits": {**plan["edits"], "stall": probe["stall"]}}


def apply_edits(item: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """A copy of the item with the plan applied."""
    out = copy.deepcopy(item)
    meta = out.setdefault("metadata", {})
    for k, v in plan["edits"].items():
        if v is None:
            meta.pop(k, None)
        else:
            meta[k] = v
    return out


def snapshot(item: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    """The values `keys` hold on the item, None = absent."""
    meta = item.get("metadata") or {}
    return {k: meta.get(k) for k in keys}


def entry_for(item: dict[str, Any], plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The undo entry's two sides for exactly the keys the plan changes."""
    keys = list(plan["edits"])
    return {"before": snapshot(item, keys), "after": snapshot(apply_edits(item, plan), keys)}


def entry_problem(side: Any) -> str:
    """Why an undo entry's side is not one this pass writes ("" = fine)."""
    if not isinstance(side, dict) or not side:
        return "an entry side is a non-empty object of the keys the pass changed"
    extra = sorted(k for k in side if k not in ENTRY_KEYS)
    return f"{', '.join(map(str, extra))} is not a key the until pass writes" if extra else ""


def reading(S: Any, gid: str, item: dict[str, Any]) -> dict[str, Any]:
    """What the item reads as, for the check that the pass changes no reading: the phase, kind of wait, mover and watched status (server._retire_reading), the board's held flag, the phase and wait kind a save
    would store, and the date the wait ends on."""
    probe = {**copy.deepcopy(item), "gid": gid}
    return {**S._retire_reading(gid, item), "held": bool(S._rmod.is_held(probe)), "stamp": list(S._stamp_values(gid, probe)), "date": _wt.until_of(probe.get("metadata") or {})}


def same(r0: dict[str, Any], r1: dict[str, Any]) -> str:
    """"" when two readings are the same, else what differs, in words."""
    diffs = [f"{k} {r0[k]} -> {r1[k]}" for k in ("pair", "mover", "held", "stamp", "date") if r0[k] != r1[k]]
    if r0["watched"] and not r1["watched"]:            # a wait the watchers did not own yet (a hold with a wake: the wake pass's) becomes theirs when it is stored as until, as a writer stores it; one they own never stops being theirs
        diffs.append(f"watched {r0['watched']} -> {r1['watched']}")
    return "; ".join(diffs)


# ---------------------------------------------------------------------------------------------------------------- the server's side: the ops `until` and `ununtil` of the migration route
# Every function takes `S`, the server module: the item lock, the file helpers and the refusal shape are the migration route's own (server.py). The pass is the stamp pass's shape (server._stamp_one): one item
# at a time under its lock, the file read and replaced whole with only the wait keys (and the History log) changed (server._stamp_write: no hand-off, no notice, no clock, no mover settled), a sha256
# check so a writer that takes no lock is never overwritten, and an undo that puts back only what the pass left.
def one(S: Any, gid: str, dry: bool = False) -> dict[str, Any]:
    """Rewrite the stored wait of one open item as `until` → {"item", "action": set | same | kept | moved | refused | would_set, "why", "form", "new", "before", "after", "sha256_before"} (before and after = the
    keys the pass changes, None = absent; the stall log is the History line). Worked out HERE, under the item lock, from the file as it stands. `same`: nothing to rewrite (no old date, or a bare date kept as a
    backstop: `why` says which); `kept`: left as it is and listed (an until beside an old date, a reason bound to another date). `refused`: the item would read differently as until (the reading check) or is
    closed. `moved`: a writer that takes no lock wrote the item between the read and the replace; its write stands. `dry`: nothing is written."""
    shown = S._gh.shown(gid)
    try:
        with S._ITEM_LOCK:
            p, data, raw, refusal = S._stamp_open(gid, shown)
            if refusal is not None:
                return refusal
            h0 = S._stamp_sha(data)
            meta = raw["metadata"]
            keeps = bool({"anchor", "recycle"} & set(S._hold_held_by(gid, meta))) if meta.get("hold") else False
            plan = plan_for(meta, keeps)
            if not plan["edits"]:
                return {"item": shown, "action": "kept" if plan["listed"] else "same", "why": plan["kept"], "form": plan["form"], "new": "", "before": {}, "after": {}, "sha256_before": h0}
            plan = with_history(meta, plan, time.time())
            new = apply_edits(raw, plan)
            out = {"item": shown, "form": plan["form"], "new": plan["new"], **entry_for(raw, plan), "sha256_before": h0}
            why = same(reading(S, gid, raw), reading(S, gid, new))
            if why:
                return {**out, "action": "refused", "why": f"the item would read differently as until: {why}; left as it is"}
            if dry:
                return {**out, "action": "would_set", "why": "the wait would be rewritten as until"}
            if not S._stamp_write(p, raw, h0, plan["edits"]):
                return {**out, "action": "moved", "why": "the item was written between the read and the replace: its write stands, and the next run rewrites it"}
        return {**out, "action": "set", "why": "rewritten as until"}
    except Exception as e:  # noqa: BLE001  — one item that fails never stops the batch
        print(f"until pass: {gid} not rewritten: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return S._migrate_refuse(shown, f"{e.__class__.__name__}: {str(e)[:200]}")


def undo_one(S: Any, w: Any) -> dict[str, Any]:
    """Put one item's wait keys back: `w` = {item, before, after} (the keys as they were, and as the pass left them; None = absent). Under the item lock, if the item holds `after` for every key it names it gets
    `before` (None drops the key) → `set`; if it already holds `before` → `same`; anything else (a later save changed a key) → `kept`, untouched. Running it again is a no-op."""
    if not isinstance(w, dict):
        return S._migrate_refuse("?", "an entry is an object {item, before, after}")
    try:
        gid = _ids._norm_id(str(w.get("item") or ""))
    except ToolError as e:
        return S._migrate_refuse(str(w.get("item") or "?"), str(e))
    shown = S._gh.shown(gid)
    extra = [k for k in w if k not in S._STAMP_ENTRY]
    if extra:
        return S._migrate_refuse(shown, f"the undo names {', '.join(sorted(map(str, extra)))}: an entry holds item, before and after only")
    before, after = w.get("before"), w.get("after")
    for side in (before, after):
        why = entry_problem(side)
        if why:
            return S._migrate_refuse(shown, why)
    if set(before) != set(after):
        return S._migrate_refuse(shown, "before and after name the same keys")
    keys = list(before)
    try:
        with S._ITEM_LOCK:
            p, data, raw, refusal = S._stamp_open(gid, shown)
            if refusal is not None:
                return refusal
            h0 = S._stamp_sha(data)
            now = snapshot(raw, keys)
            out = {"item": shown, "before": before, "after": after, "sha256_before": h0}
            if now == before:
                return {**out, "action": "same", "why": "it already holds the keys it had"}
            if now != after:
                return {**out, "action": "kept", "why": "it holds other values than the pass left (a later save changed them): left as it is", "now": now}
            if not S._stamp_write(p, raw, h0, before):
                return {**out, "action": "moved", "why": "the item was written between the read and the replace: its write stands"}
        return {**out, "action": "set", "why": "the keys put back"}
    except Exception as e:  # noqa: BLE001
        print(f"until pass: {gid} not put back: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return S._migrate_refuse(shown, f"{e.__class__.__name__}: {str(e)[:200]}")


def write_op(S: Any, spec: dict[str, Any], op: str, by: str) -> dict[str, Any]:
    """op until {items: [id, …], pass_id?, dry?} | ununtil {items: [{item, before, after}, …], pass_id?} (at most S._MIGRATE_BATCH): the until pass over the open items. No begin and no hold: each item is
    worked out and written under its own lock (`one`). `dry` (until only) writes nothing and answers what each item would get. One publish at the end when anything was written. → {"op", "results": [...]}."""
    extra = [k for k in spec if k not in S._STAMP_BODY]
    if extra:
        raise ToolError(f"Refused: {op} takes op, sender, items, pass_id and dry only (got {', '.join(sorted(map(str, extra)))}): it rewrites the wait keys and nothing else")
    items = spec.get("items")
    if not isinstance(items, list) or not items or len(items) > S._MIGRATE_BATCH:
        raise ToolError(f"Refused: items is a list of 1 to {S._MIGRATE_BATCH} " + ("item ids" if op == "until" else "entries {item, before, after}"))
    pid = str(spec.get("pass_id") or "")
    if pid and not S._PASS_ID_RX.fullmatch(pid):
        raise ToolError("Refused: pass_id is <YYYYMMDD-HHMMSS>-<6 hex>")
    dry = bool(spec.get("dry"))
    if dry and op != "until":
        raise ToolError("Refused: dry goes with until only")
    results: list[dict[str, Any]] = []
    for it in items:
        if op == "ununtil":
            results.append(undo_one(S, it))
            continue
        try:
            gid = _ids._norm_id(str(it or ""))
        except ToolError as e:
            results.append(S._migrate_refuse(str(it or "?"), str(e)))
            continue
        results.append(one(S, gid, dry=dry))
    if any(r["action"] == "set" for r in results):
        S._publish()
    if pid and not dry:
        S._stamp_pass_keep(pid, by, op, results)
    return {"op": op, "results": results}
