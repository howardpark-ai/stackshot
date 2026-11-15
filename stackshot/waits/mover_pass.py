"""mover_pass.py: the data change that stores the picker of a waiting item as `mover` and nothing else (tools/mover_migrate.py runs it).

Items stored before the one-mover change carry the picker (who picks a waiting item up when its wait ends) under the old key `post_wake_mover`, and may carry a `then` that nothing reads any more. The writers
store the picker as `mover` and read both keys (model.stored_picker: the old key wins while it is stored); this pass moves the stored picker of the open items to `mover` and proves that every item reads the
same afterwards. It removes no reader: the old key is still read, and still written by a caller that names it.

What a stored item gets (`plan_for`; the server's `one` refuses any item whose reading would change):
  the old key, set, beside a wait_kind or an until    `mover` = the old key, the old key gone. When `mover` holds the same name the key just goes; when it holds another name the old key won the reading, so `mover` takes it and the
                       item is listed (the row says which name each key held)
  the old key, blank                               the key goes
  the old key, set, and the item stores no wait_kind and no until    left as it is and listed (the old code read it only as a stray: nothing to move)
  the old key, set, on a wait on a date alone with `external` in needs    left as it is and listed (only the old key turns such a wait at its date; as `mover` it would end on the date)
  the old key holding the word none                left as it is and listed (the word names nobody under `mover`, a session of that name under the old key)
  a `then` nothing reads (an alive item whose mover is a session, a waiting one whose picker is a session)    dropped, and listed when it names someone else than the picker
  a `then` that stands in for a picker (a waiting item with no stored picker, no session in needs, and a `then` that is a live session)    `mover` = the `then`, the `then` gone: the picker the old hand-over meant
  a `then` beside the owner's own move, or a picker that is the owner    stays: it is read
  the same for the snapshot of a turned wait (metadata.watch.was)
A changed item also gets one History line (metadata.stall.log, shown as "stackshot: ..."); no other key changes, no clock moves, nobody is told.

Pure functions of a metadata dict and callbacks: no server import. `entry_for` builds the undo entry (the keys before and after), `apply_edits` the new item. The log helpers of waits/until_pass.py are the shared ones."""
from __future__ import annotations

import copy
import sys
import time
from typing import Any, Callable

from fastmcp.exceptions import ToolError

from stackshot.model import ids as _ids
from stackshot.model import migration as _mig
from stackshot.model import model as _model
from stackshot.model.needs import _needs_kinds, _needs_of, _needs_sessions
from stackshot.waits import stall as _stall
from stackshot.waits import until_pass as _up
from stackshot.waits import until_write as _uw
from stackshot.waits import waiting as _wt
from stackshot.waits import watchers as _watch

LEGACY = _model.LEGACY_PICKER_KEY
KEYS = ("mover", "then", LEGACY, "watch")                       # the keys the pass may change (watch: only its `was` snapshot)
ENTRY_KEYS = frozenset(KEYS)                                    # what an undo entry's before and after may name
ENTRY_FIELDS = _up.ENTRY_FIELDS                                 # item, before, after, history, dropped
HISTORY_MAX = _up.HISTORY_MAX
THEN_LIVE = Callable[[str, dict[str, Any]], bool]


def _who(v: Any) -> str:
    return _model.norm_who(v)


def _same_name(a: str, b: str) -> bool:
    return a.lower() == b.lower()


def _was_plan(meta: dict[str, Any]) -> tuple[Any, list[str], list[str]]:
    """The new value of `watch` (None = nothing to change), the forms (words) and the rows to list, for the snapshot of a turned wait (metadata.watch.was): the old key folded into `mover` as the watchers fold it
    (watchers._picker_as_mover), and a `then` nothing reads dropped (the snapshot puts it back on the item with the wait: beside a session's pick it is unread there too)."""
    w = meta.get("watch")
    was = w.get("was") if isinstance(w, dict) else None
    if not isinstance(was, dict):
        return None, [], []
    new = dict(was)
    forms: list[str] = []
    notes: list[str] = []
    if LEGACY in new:
        legacy = _who(new[LEGACY])
        if not legacy:
            new.pop(LEGACY)
            forms.append("watch.was: blank old key dropped")
        elif legacy.lower() == "none":
            notes.append("watch.was holds the word none under the old key: left as it is")
            return None, [], notes
        else:
            mover = _model.pick_who(new.get("mover"))
            if mover and mover != legacy:
                notes.append(f"watch.was: mover {mover} and the old key {legacy} differ: the old key won the reading, so it is stored as mover")
            new.pop(LEGACY)
            new["mover"] = legacy
            forms.append(f"watch.was: old key {legacy} -> mover")
    then = _who(new.get("then")) if "then" in new else ""
    picker = _watch.was_picker(new)
    if "then" in new and picker and not _model.is_owner(picker):
        if then and not _same_name(then, picker):
            notes.append(f"watch.was: then {then} dropped, the picker {picker} stands")
        new.pop("then")
        forms.append("watch.was: unread then dropped")
    if new == was:
        return None, [], notes
    return {**w, "was": new}, forms, notes


def plan_for(meta: dict[str, Any], mod: Any, then_live: THEN_LIVE) -> dict[str, Any]:
    """The plan for one open item → {"edits": {key: new value, None drops}, "form": the changes in words, "new": what the picker is stored as, "listed": True when the item is to be listed, "notes": the rows to list,
    "standin": the session a `then` that stood in for a picker moves to ("" when none)}.
    `mod`: the model's reading of the item (model.derive, the old hold and needs forms applied as the readers apply them); `then_live(then, meta)`: whether a `then` names a session that can take the item now
    (service/answer_handover._then_live). Pure."""
    out: dict[str, Any] = {"edits": {}, "form": "", "new": "", "listed": False, "notes": [], "standin": ""}
    edits: dict[str, Any] = {}
    forms: list[str] = []
    notes: list[str] = out["notes"]
    legacy_stored = LEGACY in meta
    legacy = _who(meta.get(LEGACY))
    top_ok = True                                               # the top-level keys may be changed (False: the old key stays and its item is listed)
    if legacy_stored and not legacy:
        edits[LEGACY] = None
        forms.append("blank old key dropped")
    elif legacy.lower() == "none" and legacy_stored:
        notes.append("the old key holds the word none: it names a session of that name, `mover` would read as no one: left as it is")
        top_ok = False
    elif legacy_stored and not _uw.kind_of(meta) and not _wt.stored_until(meta):
        notes.append("the old key is stored on an item that waits on nothing stored (no wait_kind, no until): left as it is")
        top_ok = False
    elif legacy_stored and "external" in _needs_kinds(meta) and not str(meta.get("wait_kind") or "").strip():
        notes.append(f"the old key {legacy} is stored on a wait on a date alone with `external` in needs: only the old key turns it at its date, as `mover` it would end on its date: left as it is")
        top_ok = False
    elif legacy_stored:
        mover = _model.pick_who(meta.get("mover"))
        edits[LEGACY] = None
        if mover != legacy:
            edits["mover"] = legacy
            if mover:
                notes.append(f"mover {mover} and the old key {legacy} differ: the old key won the reading, so it is stored as mover")
        forms.append(f"old key {legacy} -> mover")
    if top_ok and "then" in meta:
        then = _who(meta.get("then"))
        state = getattr(mod, "state", "")
        if state == _model.ALIVE:
            if not _model.is_owner(mod.mover):
                edits["then"] = None                              # beside a session's move a stored then is not read
                forms.append("unread then dropped")
                if then and not _same_name(then, mod.mover):
                    notes.append(f"then {then} dropped, the mover {mod.mover} stands")
        elif state == _model.WAITING and mod.wait is not None:
            picker = mod.wait.mover
            if _model.is_owner(picker):
                pass                                                # read: it stands after his answer
            elif (not mod.wait.mover_explicit and then and not _model.is_owner(then) and "external" not in _needs_kinds(meta)
                  and not _needs_sessions(meta) and then_live(then, meta)):
                edits["mover"] = then                             # it stood in for a picker: the picker the old hand-over meant
                edits["then"] = None
                out["standin"] = then
                forms.append(f"then {then} -> mover (it stood in for the picker)")
            else:
                edits["then"] = None
                forms.append("unread then dropped")
                if then and not _same_name(then, picker):
                    notes.append(f"then {then} dropped, the picker {picker} stands")
    watch, was_forms, was_notes = _was_plan(meta) if top_ok else (None, [], [])
    if watch is not None:
        edits["watch"] = watch
    forms += was_forms
    notes += was_notes
    out["edits"] = {k: v for k, v in edits.items() if (v is None and k in meta) or (v is not None and meta.get(k) != v)}
    out["form"] = "; ".join(forms)
    out["listed"] = bool(notes)
    if "mover" in out["edits"] or LEGACY in out["edits"]:
        out["new"] = f"mover={out['edits'].get('mover', _model.pick_who(meta.get('mover')))}"
    elif out["edits"]:
        out["new"] = "no picker change"
    return out


def history_line(plan: dict[str, Any]) -> str:
    """The History line of a changed item: that the stored picker was moved to `mover` (which changes), and that nothing else changed."""
    return f"the stored picker was moved to mover ({plan['form']}); nothing else on the item changed"[:HISTORY_MAX]


def with_history(meta: dict[str, Any], plan: dict[str, Any], now: float) -> dict[str, Any]:
    """The plan with the History line added (until_pass.with_history, with this pass's line)."""
    if not plan["edits"]:
        return plan
    if not _up._stall_plain(meta):
        return {**plan, "history": "", "dropped": []}
    old = _stall.log_of(meta)
    line = history_line(plan)
    log = (old + [{"at": now, "text": " ".join(line.split())[:240]}])[-_up.LOG_KEEP:]
    stall = dict(meta["stall"]) if isinstance(meta.get("stall"), dict) else {}
    stall["log"] = log
    dropped = [x for x in old if x not in log]
    return {**plan, "edits": {**plan["edits"], "stall": stall}, "history": line, "dropped": dropped}


apply_edits = _up.apply_edits
snapshot = _up.snapshot


def entry_problem(side: Any) -> str:
    """Why an undo entry's side is not one this pass writes ("" = fine): it names only the keys this pass writes."""
    if not isinstance(side, dict) or not side:
        return "an entry side is a non-empty object of the keys the pass changed"
    extra = sorted(k for k in side if k not in ENTRY_KEYS)
    return f"{', '.join(map(str, extra))} is not a key the mover pass writes" if extra else ""


def entry_for(item: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """The undo entry for the plan: the three picker keys, changed or not, and `watch` when the plan edits it, as they were and as the pass leaves them (never the History log, which later writes add to), the History
    line it adds and the older lines that pushed out. All of them, so an undo sees a later save that changed a neighbouring key and leaves the item alone."""
    keys = [k for k in KEYS if k != "watch" or "watch" in plan["edits"]]
    return {"before": snapshot(item, keys), "after": snapshot(apply_edits(item, plan), keys), "history": plan.get("history", ""), "dropped": plan.get("dropped", [])}


# ---------------------------------------------------------------------------------------------------------------- the reading the pass keeps
def prepared(S: Any, gid: str, item: dict[str, Any]) -> tuple[dict[str, Any], Any]:
    """The item as the readers see it (the old hold and needs forms applied) and the model's reading of it."""
    seen = {**copy.deepcopy(item), "gid": gid}
    S._legacy_hold(seen)
    S._legacy_needs(seen)
    return seen, S._item_read._model_of(seen)


def _restored(S: Any, gid: str, seen: dict[str, Any]) -> Any:
    """Who picks the item up, and its `then`, when the owner's "not yet" puts the turned wait back (watchers.restore_wait on a copy), None for an item with no snapshot."""
    w = (seen.get("metadata") or {}).get("watch")
    if not isinstance(w, dict) or not isinstance(w.get("was"), dict) or not w["was"]:
        return None
    back = copy.deepcopy(seen)
    _watch.restore_wait(back["metadata"], "2099-01-01", False)
    mod = S._item_read._model_of(back)
    waiting = mod.state == _model.WAITING and mod.wait is not None
    return [mod.wait.mover if waiting else mod.mover, mod.then]


def reading(S: Any, gid: str, item: dict[str, Any]) -> dict[str, Any]:
    """What the item reads as, for the check that the pass changes no reading: everything the until pass keeps (phase, kind of wait, mover, watched, held, stamp, date, conflicts), and the picker (the model's and
    the shown one), `then`, needs, whether a wait on a date alone ends with its date, and who picks the item up when a turned wait is put back."""
    seen, mod = prepared(S, gid, item)
    shown = _model.view(seen, mod, after_open=lambda i_: S._item_read._after_open(i_.get("metadata") or {}))
    waiting = mod.state == _model.WAITING and mod.wait is not None
    return {**_up.reading(S, gid, item), "picker": [mod.picker, shown.picker], "then": [mod.then, mod.then_explicit], "needs": list(_needs_of(seen.get("metadata") or {})),
            "ends": bool(_watch.ends_on_the_date(seen.get("metadata") or {}, mod)) if waiting else None, "restored": _restored(S, gid, seen)}


def same(r0: dict[str, Any], r1: dict[str, Any], standin: str = "") -> str:
    """"" when two readings are the same, else what differs, in words. `standin`: the session a `then` that stood in for a picker moved to: the picker then reads as it, and a wait on a date alone then turns to it at
    its date (`ends`), and nothing else may differ."""
    diffs = [_up.same(r0, r1)] if _up.same(r0, r1) else []
    keys = ["picker", "then", "needs", "restored"] + ([] if standin else ["ends"])
    for k in keys:
        if r0[k] == r1[k]:
            continue
        if standin and k == "picker" and r1[k] == [standin, standin]:
            continue
        diffs.append(f"{k} {r0[k]} -> {r1[k]}")
    return "; ".join(diffs)


# ---------------------------------------------------------------------------------------------------------------- the server's side: the ops `mover` and `unmover` of the migration route
# Every function takes `S`, the server module (the running server passes `stamp.PassHost`): the item lock, the file helpers and the refusal shape are the migration route's own. The pass is the until pass's shape:
# one item at a time under its lock, the file read and replaced whole with only the picker keys (and the History log) changed (stamp._stamp_write), a sha256 check so a writer that takes no lock is never
# overwritten, and an undo that puts back only what the pass left.
def one(S: Any, gid: str, then_live: THEN_LIVE, dry: bool = False) -> dict[str, Any]:
    """Store the picker of one open item as `mover` → {"item", "action": set | same | kept | moved | refused | would_set, "why", "form", "new", "notes", "before", "after", "sha256_before"} (before and after = the keys
    the pass changes, None = absent; the stall log is the History line). Worked out HERE, under the item lock, from the file as it stands. `same`: nothing to change; `kept`: nothing changed and the item is listed
    (`notes` says why). `refused`: the item would read differently (the reading check) or is closed. `moved`: a writer that takes no lock wrote the item between the read and the replace; its write stands.
    `dry`: nothing is written."""
    shown = S._gh.shown(gid)
    try:
        with S._writes.ITEM_LOCK:
            p, data, raw, refusal = S._stamp_open(gid, shown)
            if refusal is not None:
                return refusal
            h0 = S._stamp_sha(data)
            meta = raw["metadata"]
            _seen, mod = prepared(S, gid, raw)
            plan = plan_for(meta, mod, then_live)
            base = {"item": shown, "form": plan["form"], "new": plan["new"], "notes": plan["notes"], "standin": plan["standin"], "sha256_before": h0}
            if not plan["edits"]:
                return {**base, "action": "kept" if plan["listed"] else "same", "why": "; ".join(plan["notes"]) or "no stored picker to move", "before": {}, "after": {}}
            plan = with_history(meta, plan, time.time())
            new = apply_edits(raw, plan)
            out = {**base, **entry_for(raw, plan)}
            why = same(reading(S, gid, raw), reading(S, gid, new), plan["standin"])
            if why:
                return {**out, "action": "refused", "why": f"the item would read differently with its picker stored as mover: {why}; left as it is"}
            if dry:
                return {**out, "action": "would_set", "why": "the picker would be stored as mover"}
            if not S._stamp_write(p, raw, h0, plan["edits"]):
                return {**out, "action": "moved", "why": "the item was written between the read and the replace: its write stands, and the next run moves it"}
        return {**out, "action": "set", "why": "the picker stored as mover"}
    except Exception as e:  # noqa: BLE001  — one item that fails never stops the batch
        print(f"mover pass: {gid} not moved: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return _mig.refuse(shown, f"{e.__class__.__name__}: {str(e)[:200]}")


def undo_one(S: Any, w: Any) -> dict[str, Any]:
    """Put one item's picker keys back: `w` = {item, before, after, history, dropped} (the keys as they were, and as the pass left them; None = absent). Under the item lock, if the item holds `after` for every
    key it names it gets `before` (None drops the key) → `set`; if it already holds `before` → `same`; anything else (a later save changed a key, or the item is closed) → `kept`, untouched. Running it again is a no-op."""
    if not isinstance(w, dict):
        return _mig.refuse("?", "an entry is an object {item, before, after}")
    try:
        gid = _ids._norm_id(str(w.get("item") or ""))
    except ToolError as e:
        return _mig.refuse(str(w.get("item") or "?"), str(e))
    shown = S._gh.shown(gid)
    extra = [k for k in w if k not in ENTRY_FIELDS]
    if extra:
        return _mig.refuse(shown, f"the undo names {', '.join(sorted(map(str, extra)))}: an entry holds item, before, after, history and dropped only")
    history, dropped = w.get("history") or "", w.get("dropped") or []
    if not isinstance(history, str) or not isinstance(dropped, list) or not all(isinstance(x, dict) for x in dropped):
        return _mig.refuse(shown, "history is the line the pass added (text) and dropped a list of log lines")
    before, after = w.get("before"), w.get("after")
    for side in (before, after):
        why = entry_problem(side)
        if why:
            return _mig.refuse(shown, why)
    if set(before) != set(after):
        return _mig.refuse(shown, "before and after name the same keys")
    keys = list(before)
    try:
        with S._writes.ITEM_LOCK:
            p, data, raw, refusal = S._stamp_open(gid, shown, closed_ok=True)
            if refusal is not None:
                return refusal
            h0 = S._stamp_sha(data)
            now = snapshot(raw, keys)
            out = {"item": shown, "before": before, "after": after, "history": history, "dropped": dropped, "sha256_before": h0}
            if raw.get("status") != "open":
                return {**out, "action": "kept", "why": f"it was closed since the pass ({raw.get('status')}): left as it is", "now": now}
            if now == before:
                return {**out, "action": "same", "why": "it already holds the keys it had"}
            if now != after:
                return {**out, "action": "kept", "why": "it holds other values than the pass left (a later save changed them): left as it is", "now": now}
            edits = {k: before[k] for k in keys if before[k] != after[k]}
            if history:
                edits["stall"] = _up._log_without(raw["metadata"], history, dropped)
            if not S._stamp_write(p, raw, h0, edits):
                return {**out, "action": "moved", "why": "the item was written between the read and the replace: its write stands"}
        return {**out, "action": "set", "why": "the keys put back"}
    except Exception as e:  # noqa: BLE001
        print(f"mover pass: {gid} not put back: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return _mig.refuse(shown, f"{e.__class__.__name__}: {str(e)[:200]}")


def write_op(S: Any, spec: dict[str, Any], op: str, by: str, then_live: THEN_LIVE) -> dict[str, Any]:
    """op mover {items: [id, …], pass_id?, dry?} | unmover {items: [{item, before, after, history, dropped}, …], pass_id?} (at most _mig.BATCH): the mover pass over the open items. No begin and no hold: each item is
    worked out and written under its own lock (`one`). `dry` (mover only) writes nothing and answers what each item would get. One publish at the end when anything was written. → {"op", "results": [...]}."""
    extra = [k for k in spec if k not in S._STAMP_BODY]
    if extra:
        raise ToolError(f"Refused: {op} takes op, sender, items, pass_id and dry only (got {', '.join(sorted(map(str, extra)))}): it moves the picker keys and nothing else")
    items = spec.get("items")
    if not isinstance(items, list) or not items or len(items) > _mig.BATCH:
        raise ToolError(f"Refused: items is a list of 1 to {_mig.BATCH} " + ("item ids" if op == "mover" else "entries {item, before, after}"))
    pid = str(spec.get("pass_id") or "")
    if pid and not _mig.PASS_ID_RX.fullmatch(pid):
        raise ToolError("Refused: pass_id is <YYYYMMDD-HHMMSS>-<6 hex>")
    dry = bool(spec.get("dry"))
    if dry and op != "mover":
        raise ToolError("Refused: dry goes with mover only")
    results: list[dict[str, Any]] = []
    for it in items:
        if op == "unmover":
            results.append(undo_one(S, it))
            continue
        try:
            gid = _ids._norm_id(str(it or ""))
        except ToolError as e:
            results.append(_mig.refuse(str(it or "?"), str(e)))
            continue
        results.append(one(S, gid, then_live, dry=dry))
    if any(r["action"] == "set" for r in results):
        S._pubmod._publish()
    if pid and not dry:
        S._stamp_pass_keep(pid, by, op, results)
    return {"op": op, "results": results}
