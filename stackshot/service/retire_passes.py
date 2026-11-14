"""retire_passes.py: the retire pass: the stored state words and carry fields taken out of the open items (model/retire_fields.py has the plan and the undo entry; tools/retire_fields_report.py runs it).

`_retire_one` works one item out under the item lock and writes it like a stamp (`_stamp_write` of service/stamp.py: nothing else in the file changes, no event on the item); `_unretire_one` puts the keys back;
`_retire_write_op` is the ops retire and unretire of the migration route (service/migrations.py `migrate_write`). `_retire_reading` is the reading the pass compares before and after, and waits/until_pass.py reads it
too, through the host of service/stamp.py.

The stamp helpers are called on service/stamp.py's module and the publish comes through `Hooks` in service/passes_hooks.py, both looked up when they run. A suite that replaces a function or the clock of the pass
sets it on the module that owns it (and `time` here, since this module reads its own).

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import json
import sys
import time
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.github import ghsync as _gh
from stackshot.model import bullet_text as _bt
from stackshot.model import migration as _mig
from stackshot.model import model as _model
from stackshot.model import retire_fields as _retire
from stackshot.model.field_gates import _bullets_on, _description_limits
from stackshot.model.ids import _norm_id
from stackshot.service import item_read as _item_read
from stackshot.service import stamp as _stamp_svc
from stackshot.service import writes as _writes
from stackshot.service.passes_hooks import hooks as _hooks
from stackshot.service.store import _legacy_hold, _legacy_needs
from stackshot.waits import waiting as _wt
from stackshot.waits import watchers as _watch


# ---------------------------------------------------------------------------------------------------------------- the retire pass: the stored state words and carry fields out of the open items (retire_fields.py)
_RETIRE_BODY = frozenset({"op", "sender", "items", "pass_id", "dry"})


def _description_fit_why(desc: str) -> str:
    """"" when a description is within the limits of a write ([description] max_lines non-blank lines, each a `- ` bullet of at most line_max characters), else what breaks (the retire pass holds a Needs bullet that would)."""
    max_lines, line_max = _description_limits()
    bad = _bt.judge(desc, max_lines, line_max) if _bullets_on() else (("lines", "", n) if (n := len([ln for ln in desc.splitlines() if ln.strip()])) > max_lines else None)
    if not bad:
        return ""
    kind, _ln, n = bad
    return f"{n} lines, the limit is {max_lines}" if kind == "lines" else "a line that is not a `- ` bullet" if kind == "marker" else f"a bullet of {n} characters, the limit is {line_max}"


def _retire_reading(gid: str, item: dict[str, Any]) -> dict[str, Any]:
    """What the fields give for an item now: {"pair": (phase, kind of the wait), "mover": the mover of an alive one, "watched": whether the watchers own its wait}. The pass writes an item only when this is the same before and after (retire_same)."""
    probe = {**json.loads(json.dumps(item)), "gid": gid}
    _legacy_hold(probe)
    _legacy_needs(probe)
    shown = _model.view(probe, _item_read._model_of(probe), after_open=lambda i_: _item_read._after_open(i_.get("metadata") or {}), check=False)
    return {"pair": list(_model.shown_pair(shown)), "mover": shown.mover if shown.state == _model.ALIVE else "", "watched": bool(_watch.watches(probe))}


def retire_same(r0: dict[str, Any], r1: dict[str, Any]) -> str:
    """"" when two readings are the same, else what differs, in words."""
    return "; ".join(f"{k} {r0[k]} -> {r1[k]}" for k in ("pair", "mover", "watched") if r0[k] != r1[k])


def _retire_holds(item: dict[str, Any]) -> bool:
    """Is the item left whole by the retire pass: agent work in hand (the stored state doing with a session as mover, waiting.doing_agent). Its wait is read from the stored state alone, so without the word the reading check
    below might refuse it; this holds it first and lists it."""
    return _wt.doing_agent(item)


def _retire_one(gid: str, dry: bool = False) -> dict[str, Any]:
    """Take the stored state word and the carry fields out of one open item (retire_fields.plan_for): → {"item", "action": set | same | moved | refused | would_set, "why", "before", "after", "held", "sha256_before"}
    (before and after = the keys the plan touches as the item holds them, None = absent; `description` is the top-level field). Worked out HERE under the item lock from the file as it stands, written like a stamp
    (_stamp_write: nothing else in the file changes, no event on the item). An item whose phase, kind of wait, mover or watched status would read differently is `refused` and left as it is. `same`: nothing to retire.
    `moved`: a writer that takes no lock wrote the item between the read and the replace; its write stands. `dry`: nothing is written (`would_set`)."""
    shown = _gh.shown(gid)
    try:
        with _writes.ITEM_LOCK:
            p, data, raw, refusal = _stamp_svc._stamp_open(gid, shown)
            if refusal is not None:
                return refusal
            h0 = _stamp_svc._stamp_sha(data)
            if _retire_holds(raw):         # agent work in hand: left whole
                return {"item": shown, "action": "same", "why": "held whole: the stored state doing stands (without it the item's wait would read differently)", "held": ["state"], "sha256_before": h0}
            plan = _retire.plan_for(raw["metadata"], str(raw.get("description") or ""), time.time(), _description_fit_why)
            held = [f for f, _w in plan["held"]]
            if not plan["edits"] and plan["description"] is None:
                return {"item": shown, "action": "same", "why": "nothing to retire" + (f" (held: {', '.join(held)})" if held else ""), "held": held, "sha256_before": h0}
            new = _retire.apply_edits(raw, plan)
            out = {"item": shown, **_retire.entry_for(raw, plan), "held": held, "sha256_before": h0}
            why = retire_same(_retire_reading(gid, raw), _retire_reading(gid, new))
            if why:
                return {**out, "action": "refused", "why": f"the item would read differently: {why}; left as it is"}
            if dry:
                return {**out, "action": "would_set", "why": "the stored state word and carry fields would be taken out"}
            if not _stamp_svc._stamp_write(p, new, h0, {}):
                return {**out, "action": "moved", "why": "the item was written between the read and the replace: its write stands, and the next run retires it"}
        return {**out, "action": "set", "why": "retired"}
    except Exception as e:  # noqa: BLE001  — one item that fails never stops the batch
        print(f"retire: {gid} not retired: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return _mig.refuse(shown, f"{e.__class__.__name__}: {str(e)[:200]}")


def _unretire_one(w: Any) -> dict[str, Any]:
    """Put one item's retired keys back: `w` = {item, before, after} (retire_fields.entry_for). Under the item lock, if the item holds `after` for every key it names it gets `before` (None drops the key) → `set`; if it
    already holds `before` → `same`; anything else (a later save changed a key) → `kept`, untouched. A closed item → `refused`. Running it again is a no-op."""
    if not isinstance(w, dict):
        return _mig.refuse("?", "an entry is an object {item, before, after}")
    try:
        gid = _norm_id(str(w.get("item") or ""))
    except ToolError as e:
        return _mig.refuse(str(w.get("item") or "?"), str(e))
    shown = _gh.shown(gid)
    extra = [k for k in w if k not in _stamp_svc._STAMP_ENTRY]
    if extra:
        return _mig.refuse(shown, f"the undo names {', '.join(sorted(map(str, extra)))}: an entry holds item, before and after only")
    before, after = w.get("before"), w.get("after")
    for side in (before, after):
        why = _retire.entry_problem(side)
        if why:
            return _mig.refuse(shown, why)
    if set(before) != set(after):
        return _mig.refuse(shown, "before and after name the same keys")
    keys = list(before)
    try:
        with _writes.ITEM_LOCK:
            p, data, raw, refusal = _stamp_svc._stamp_open(gid, shown)
            if refusal is not None:
                return refusal
            h0 = _stamp_svc._stamp_sha(data)
            now = _retire.snapshot(raw, keys)
            out = {"item": shown, "before": before, "after": after, "sha256_before": h0}
            if now == before:
                return {**out, "action": "same", "why": "it already holds the keys it had"}
            if now != after:
                return {**out, "action": "kept", "why": "it holds other values than the retire left (a later save changed them): left as it is", "now": now}
            for k, v in before.items():
                if k == "description":
                    raw["description"] = v if v is not None else ""
                elif v is None:
                    raw["metadata"].pop(k, None)
                else:
                    raw["metadata"][k] = v
            if not _stamp_svc._stamp_write(p, raw, h0, {}):
                return {**out, "action": "moved", "why": "the item was written between the read and the replace: its write stands"}
        return {**out, "action": "set", "why": "the keys put back"}
    except Exception as e:  # noqa: BLE001
        print(f"retire: {gid} not put back: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return _mig.refuse(shown, f"{e.__class__.__name__}: {str(e)[:200]}")


def _retire_write_op(spec: dict[str, Any], op: str, by: str) -> dict[str, Any]:
    """op retire {items: [id, …], pass_id?, dry?} | unretire {items: [{item, before, after}, …], pass_id?} (at most _mig.BATCH): the retire pass. No begin and no hold: each item is worked out and written under its
    own lock (_retire_one). `dry` (retire only) writes nothing and answers what each item would get. One publish at the end when anything was written. → {"op", "results": [...]}."""
    extra = [k for k in spec if k not in _RETIRE_BODY]
    if extra:
        raise ToolError(f"Refused: {op} takes op, sender, items, pass_id and dry only (got {', '.join(sorted(map(str, extra)))})")
    items = spec.get("items")
    if not isinstance(items, list) or not items or len(items) > _mig.BATCH:
        raise ToolError(f"Refused: items is a list of 1 to {_mig.BATCH} " + ("item ids" if op == "retire" else "entries {item, before, after}"))
    pid = str(spec.get("pass_id") or "")
    if pid and not _mig.PASS_ID_RX.fullmatch(pid):
        raise ToolError("Refused: pass_id is <YYYYMMDD-HHMMSS>-<6 hex>")
    dry = bool(spec.get("dry"))
    if dry and op != "retire":
        raise ToolError("Refused: dry goes with retire only")
    results: list[dict[str, Any]] = []
    for it in items:
        if op == "unretire":
            results.append(_unretire_one(it))
            continue
        try:
            gid = _norm_id(str(it or ""))
        except ToolError as e:
            results.append(_mig.refuse(str(it or "?"), str(e)))
            continue
        results.append(_retire_one(gid, dry=dry))
    if any(r["action"] == "set" for r in results):
        _hooks().publish()
    if pid and not dry:
        _stamp_svc._stamp_pass_keep(pid, by, op, results)
    return {"op": op, "results": results}
