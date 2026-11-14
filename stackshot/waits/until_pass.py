"""until_pass.py: the data change that rewrites the waits stored before `until` as `until` (until_write.py has the mapping; tools/until_migrate.py runs it).

Items stored before the until writers carry a wait in the old fields: `wake`, `ask_by` and `hold`. The writers store the same wait as one date, `until`, and a `wait_kind` where the old fields
imply one. This pass gives a stored item the form the writers would give the same wait today, through their own `fold` (until_write.py), and nothing else: it is not a second mapping.

What a stored item gets (`plan_for`; the server's `one` refuses any item whose reading would change):
  wake (+ hold)        until = the wake, the hold flag gone (a wait on the date alone, or the stored kind time); its stamp (hold_set: who set the hold, and when) stays on the item; a hold that waits on an anchor scoped to the item or on a pane recycle keeps its flag
  ask_by, wait_kind    until = the ask-by day (a relay), or the earlier of ask_by and wake (an anchor, item or event wait); the kind stays
  ask_by / wake beside an after link with no kind    until = the date, wait_kind = item (as create and update store it)
  a bare wake (no hold, no kind, no wait_basis, no after link)    kept as it is: it is a backstop (a hand-off's, or one stored before until), not a wait, and as `until` it would park the item
  an item with no old date, or one that stores an until and an old date both    left as it is (the second is listed)
  a date the old code did not act on (an ask_by the old watchers did not read: they read it only for a relay, or as the backstop of an item wait, or of an anchor or event wait they could end, so one beside no kind, a time kind, an anchor wait with no anchor or an event wait with a bad phrase was never read; or a wake with no hold on a wait the watchers did not own (no kind, an anchor wait with no anchor, an event wait with a bad phrase), which only got a notice)
                       As until the watchers act on it. A date already past is NOT migrated (it would wake the item on the next tick): it is listed as "already due" for a person to re-save with the date meant;
                       a future one is migrated and listed as "newly watched", with the day it wakes and how it was read before (never watched, or only a notice). An item with a wake and a hold is not in
                       this class: the old wake pass released it at the date, as the watchers do.
A rewritten item also gets one History line (metadata.stall.log, shown as "stackshot: ..."), which says the wait was rewritten as until; no other key changes (the other keys of `stall` stay; a `stall` that is not an object with a plain log is left alone and the item gets no line), no clock moves, nobody is told.
A hold + wake whose release differs from the old wake pass's (release_differs) is migrated and listed with the reason; an item whose reading would change, its model conflicts included, is refused.

Pure functions of a metadata dict and callbacks: no server import. `entry_for` builds the undo entry (the keys before and after), `apply_edits` the new item."""
from __future__ import annotations

import copy
import sys
import time
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.model import ids as _ids
from stackshot.model import migration as _mig
from stackshot.waits import stall as _stall
from stackshot.waits import until_write as _uw
from stackshot.waits import waiting as _wt

KEYS = ("until", "wait_kind", "wake", "ask_by", "hold", "hold_set")       # the wait keys the pass may change
ENTRY_KEYS = frozenset(KEYS)                                               # what an undo entry's before and after may name: the wait keys only (the History line is `history`, below)
ENTRY_FIELDS = frozenset(("item", "before", "after", "history", "dropped"))      # an undo entry: the wait keys as they were and as the pass left them, the History line it added, the older lines that line pushed out of the log
HISTORY_MAX = 240
LOG_KEEP = 8                                                               # stall.note keeps this many lines of a log


def clean(v: Any) -> str:
    return " ".join(str(v or "").split())


def _dated(v: Any) -> str:
    s = clean(v)
    return s if s and _wt.wake_epoch(s) is not None else ""


def old_form(meta: dict[str, Any]) -> str:
    """The old fields an item stores, in words: "wake", "hold + wake", "ask_by", "wake + ask_by" … ("" when it stores none of them)."""
    parts = [n for n, on in (("hold", bool(meta.get("hold"))), ("wake", bool(clean(meta.get("wake")))), ("ask_by", bool(clean(meta.get("ask_by"))))) if on]
    return " + ".join(parts)


HOW_NEVER = "never watched"                         # nothing read this date before (an ask_by with no kind)
HOW_NOTICE = "previously only a notice"             # the old wake pass only sent a backstop notice at this date (a wake beside an after link with no kind)


def due_why(how: str) -> str:
    return (f"already due: not migrated (its date is past and was {how}: as until the watchers would act on it at once); re-save it with the date you mean")


def plan_for(meta: dict[str, Any], keeps_hold: bool = False) -> dict[str, Any]:
    """The plan for one open item → {"edits": {key: new value, None drops}, "form": the old fields in words, "new": what the wait is stored as, "kept": why it is left (""), "listed": True when the kept item is
    to be listed for a person, "until": the date it is stored as, "source": "wake" | "ask_by" (which old field the date comes from; the old
    wake pass read `wake`, nothing read an ask_by that stood without a kind)}.
    `keeps_hold`: the hold waits on an anchor scoped to the item or on a pane recycle (the flag stays). Pure. Whether the date is one the watchers newly act on, and whether it is already due, is the server's
    to say (`one`): it needs the watched reading before and after."""
    form = old_form(meta)
    out: dict[str, Any] = {"edits": {}, "form": form, "new": "", "kept": "", "listed": False, "until": "", "source": ""}
    if not _dated(meta.get("wake")) and not _dated(meta.get("ask_by")):
        out["kept"] = "no old date stored" if not form else "no old date to fold"
        return out
    if any(isinstance(meta.get(k), str) and _dated(meta.get(k)) and meta[k].strip() != clean(meta[k]) for k in ("wake", "ask_by")):
        out.update(kept="an old date has spaces inside it (the old readers took it for no date): left as it is", listed=True)    # only a hand-edited store holds one: the writers store canonical dates
        return out
    if _wt.stored_until(meta):
        out.update(kept="an until and an old date field are both stored: left as it is", listed=True)
        return out
    if _uw.is_bare(meta):
        bare = {"wake": "a bare wake", "ask_by": "a bare ask_by", "wake + ask_by": "a bare wake and ask_by"}.get(form, "a bare date")
        out["kept"] = f"{bare} is a backstop (a hand-off's, or one stored before until), not a wait: kept as it is"
        return out
    work = copy.deepcopy(meta)
    if _wt.after_of(work) and not _uw.kind_of(work) and _uw.date_of(work):
        work["wait_kind"] = "item"                       # a date beside an after link with no kind is that wait's backstop; the writers store the kind item, and the watchers act on it from then on
    wake_before = _wt.wake_value(meta)
    hold_set = work.get("hold_set")
    u = _uw.fold(work)
    if not u:
        out["kept"] = "no date to fold"
        return out
    if (meta.get("wait_basis") or meta.get("cap_ok")) and wake_before != u:      # compared as stored, not cleaned: a reason bound to a date with spaces around it would read as bound to another date once the clean one is stored (basis_of compares as written)
        out.update(kept="a reason or an approval is bound to another date than the one the wait is stored as (or to the date with spaces around it): left as it is", listed=True)
        return out
    if keeps_hold and meta.get("hold"):
        work["hold"] = True
    if hold_set is not None:
        work["hold_set"] = hold_set                 # who set the hold and when stays on the item (the writers drop it with the hold; the pass drops no record of a person): the wait began then (audit_run.wait_since reads it)
    edits: dict[str, Any] = {}
    for k in KEYS:
        if work.get(k) != meta.get(k) and (k in work or k in meta):
            edits[k] = work.get(k)
    out["edits"] = edits
    kind = clean(work.get("wait_kind"))
    out["new"] = f"until={u}" + (f", wait_kind={kind}" if kind else "")
    wake_d = _dated(meta.get("wake"))
    out["until"] = u
    out["source"] = "wake" if wake_d and clean(wake_d) == clean(u) else "ask_by"
    return out


def release_differs(meta: dict[str, Any], is_owner: Any) -> str:
    """Words for a hold with a wake that the old wake pass released one way and the watchers release another, "" when they agree. Only a hold with a dated wake (the old wake pass's), and only the two shapes that
    differ: `needs` names the owner (the old release put the item back in the owner's lane with no new ask; the watchers give it a step for him and an ask), and a `post_wake_mover` that is not the one
    session in `needs` (the old release and its message went to `needs`; the watchers hand it to the post_wake_mover and rewrite `needs` as [it]). Past or future wake alike. `is_owner(name)`: the instance's
    owner name test (the model's)."""
    if not meta.get("hold") or not _dated(meta.get("wake")):
        return ""
    raw = meta.get("needs")
    needs = [clean(x) for x in (raw if isinstance(raw, list) else [raw]) if clean(x)]
    pwm = clean(meta.get("post_wake_mover"))
    out = []
    if any(is_owner(n) for n in needs):
        out.append("needs names the board's owner: the old wake pass put it back in his lane with no new ask, the watchers give it a step for him and an ask")
    if needs and pwm and [n.lower() for n in needs] != [pwm.lower()]:
        out.append(f"post_wake_mover {pwm} is not its needs {needs}: the old release and its message went to needs, the watchers hand it to {pwm} and rewrite needs as [{pwm}]")
    return "; ".join(out)


def history_line(plan: dict[str, Any]) -> str:
    """The History line of a rewritten wait: that it was rewritten as until, from which fields, and that nothing else changed."""
    return f"the stored wait was rewritten as {plan['new']} (it was {plan['form']}); nothing else on the item changed"[:HISTORY_MAX]


def _stall_plain(meta: dict[str, Any]) -> bool:
    """Is the item's `stall` one the pass can add its History line to without losing anything: absent, or an object whose `log` (when there is one) is a list of objects? Anything else (a hand edit) is left alone."""
    s = meta.get("stall")
    if s is None:
        return True
    if not isinstance(s, dict):
        return False
    log = s.get("log")
    return log is None or (isinstance(log, list) and all(isinstance(x, dict) for x in log))


def with_history(meta: dict[str, Any], plan: dict[str, Any], now: float) -> dict[str, Any]:
    """The plan with the History line added to its edits (the `stall` value as it will stand: the log with the new line at its end, every other key of `stall` as it was). A plan with no edits is returned as it is;
    so is one on an item whose `stall` is not an object with a plain log (nothing is written to it, the plan carries no History line, and an undo does not touch it)."""
    if not plan["edits"]:
        return plan
    if not _stall_plain(meta):
        return {**plan, "history": "", "dropped": []}
    old = _stall.log_of(meta)
    line = history_line(plan)
    log = (old + [{"at": now, "text": " ".join(line.split())[:240]}])[-LOG_KEEP:]
    stall = dict(meta["stall"]) if isinstance(meta.get("stall"), dict) else {}
    stall["log"] = log
    dropped = [x for x in old if x not in log]             # the lines the new one pushed out of the log (the log keeps LOG_KEEP): an undo puts them back
    return {**plan, "edits": {**plan["edits"], "stall": stall}, "history": line, "dropped": dropped}


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
    """The undo entry for the plan: ALL the wait keys (KEYS), changed or not, as they were and as the pass leaves them (never the History log, which later writes add to), the History line it adds and the
    older lines that pushed out. All of them, so an undo sees a later save that changed a neighbouring wait key (a kind, a hold) and leaves the item alone. Nothing in it depends on the clock, so the entry
    planned by a dry run is the one the write makes."""
    keys = list(KEYS)
    return {"before": snapshot(item, keys), "after": snapshot(apply_edits(item, plan), keys), "history": plan.get("history", ""), "dropped": plan.get("dropped", [])}


def entry_problem(side: Any) -> str:
    """Why an undo entry's side is not one this pass writes ("" = fine)."""
    if not isinstance(side, dict) or not side:
        return "an entry side is a non-empty object of the keys the pass changed"
    extra = sorted(k for k in side if k not in ENTRY_KEYS)
    return f"{', '.join(map(str, extra))} is not a key the until pass writes" if extra else ""


def reading(S: Any, gid: str, item: dict[str, Any]) -> dict[str, Any]:
    """What the item reads as, for the check that the pass changes no reading: the phase, kind of wait, mover and watched status (server._retire_reading), the board's held flag, the phase and wait kind a save
    would store, the date the wait ends on, and the model's conflicts (a new one is a difference)."""
    probe = {**copy.deepcopy(item), "gid": gid}
    seen = copy.deepcopy(probe)
    S._legacy_hold(seen); S._legacy_needs(seen)                    # as _retire_reading reads it
    return {**S._retire_reading(gid, item), "held": bool(S._rmod.is_held(probe)), "stamp": list(S._stamp_values(gid, probe)), "date": _wt.until_of(probe.get("metadata") or {}),
            "conflicts": sorted(S._model_of(seen).conflicts)}


def same(r0: dict[str, Any], r1: dict[str, Any]) -> str:
    """"" when two readings are the same, else what differs, in words."""
    diffs = [f"{k} {r0[k]} -> {r1[k]}" for k in ("pair", "mover", "held", "stamp", "date") if r0[k] != r1[k]]
    new_conflicts = [c for c in r1.get("conflicts") or [] if c not in (r0.get("conflicts") or [])]
    if new_conflicts:            # the model's own complaints about the fields (such as a wait_kind stored on an item whose state is alive): one the item did not show before is a new reading, not a rewrite
        diffs.append("conflicts: " + " | ".join(c[:160] for c in new_conflicts))
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
        with S._writes.ITEM_LOCK:
            p, data, raw, refusal = S._stamp_open(gid, shown)
            if refusal is not None:
                return refusal
            h0 = S._stamp_sha(data)
            meta = raw["metadata"]
            keeps = bool({"anchor", "recycle"} & set(S._hold_held_by(gid, meta))) if meta.get("hold") else False
            plan = plan_for(meta, keeps)
            if not plan["edits"]:
                return {"item": shown, "action": "kept" if plan["listed"] else "same", "why": plan["kept"], "form": plan["form"], "new": "", "before": {}, "after": {}, "due": False, "newly": "", "how": "", "differs": "", "sha256_before": h0}
            plan = with_history(meta, plan, time.time())
            new = apply_edits(raw, plan)
            out = {"item": shown, "form": plan["form"], "new": plan["new"], **entry_for(raw, plan), "due": False, "newly": "", "how": "", "differs": "", "sha256_before": h0}
            r0, r1 = reading(S, gid, raw), reading(S, gid, new)
            why = same(r0, r1)
            if why:
                return {**out, "action": "refused", "why": f"the item would read differently as until: {why}; left as it is"}
            # an ask_by is a date the old watchers read only for a wait they owned (a relay, an item wait, an anchor or event wait they could end) and, as the chosen date, only when no dated wake is the earlier one: so a
            # date taken from the ask_by was read exactly when the item was watched before (an anchor with no anchor, an event with a bad phrase, a kind time, no kind at all: not watched, not read)
            read_ask_by = bool(r0["watched"]) and _uw.kind_of(meta) in ("relay", "item", "anchor", "event")
            # a wake with no hold on a wait the watchers did not own (no kind, an anchor wait with no anchor, an event wait with no valid phrase) only got a backstop notice from the old wake pass; as until the
            # watchers release the item. The kind check in read_ask_by is for a kind time, which reads only its own date; nothing seen reaches it, it costs nothing and states what the old code read.
            notice = plan["source"] == "wake" and not meta.get("hold") and not r0["watched"]
            how = HOW_NOTICE if notice else HOW_NEVER if plan["source"] == "ask_by" and not read_ask_by else ""
            if how:                                     # a date the old code did not act on as the watchers will: nothing read it, or the old pass only sent a notice
                ep = _wt.wake_epoch(plan["until"])
                if ep is not None and ep <= time.time():
                    return {"item": shown, "action": "kept", "why": due_why(how), "form": plan["form"], "new": "", "before": {}, "after": {}, "due": True, "newly": "", "how": how, "differs": "", "sha256_before": h0}
                out["newly"], out["how"] = plan["until"], how
            if not r0["watched"]:                       # a wait the watchers already own releases the same way after the pass
                out["differs"] = release_differs(meta, S._model.is_owner)
            if dry:
                return {**out, "action": "would_set", "why": "the wait would be rewritten as until"}
            if not S._stamp_write(p, raw, h0, plan["edits"]):
                return {**out, "action": "moved", "why": "the item was written between the read and the replace: its write stands, and the next run rewrites it"}
        return {**out, "action": "set", "why": "rewritten as until"}
    except Exception as e:  # noqa: BLE001  — one item that fails never stops the batch
        print(f"until pass: {gid} not rewritten: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return _mig.refuse(shown, f"{e.__class__.__name__}: {str(e)[:200]}")


def _log_without(meta: dict[str, Any], history: str, dropped: list[dict[str, Any]]) -> Any:
    """The `stall` value an item has once the pass's History line is taken out of its log (the last line with that text) and the lines it pushed out are back at the front, as far as the log has room.
    Other lines stay as they are; None (drop the key) when nothing is left of the log and the key holds nothing else."""
    stall = meta.get("stall")
    log = [x for x in _stall.log_of(meta)]
    for i in range(len(log) - 1, -1, -1):
        if log[i].get("text") == history:
            del log[i]
            break
    log = (dropped + log)[-LOG_KEEP:]
    rest = {k: v for k, v in (stall.items() if isinstance(stall, dict) else []) if k != "log"}
    if not log:
        return rest or None             # the keys of `stall` other than the log stay exactly as they were; nothing else left: the key goes
    return {**rest, "log": log}


def undo_one(S: Any, w: Any) -> dict[str, Any]:
    """Put one item's wait keys back: `w` = {item, before, after} (the keys as they were, and as the pass left them; None = absent). Under the item lock, if the item holds `after` for every key it names it gets
    `before` (None drops the key) → `set`; if it already holds `before` → `same`; anything else (a later save changed a key) → `kept`, untouched. Running it again is a no-op."""
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
            if raw.get("status") != "open":          # closed since the pass: a close ended the wait and cleared its keys, and the item is left as it is, like one a later save changed
                return {**out, "action": "kept", "why": f"it was closed since the pass ({raw.get('status')}): left as it is", "now": now}
            if now == before:
                return {**out, "action": "same", "why": "it already holds the keys it had"}
            if now != after:
                return {**out, "action": "kept", "why": "it holds other values than the pass left (a later save changed them): left as it is", "now": now}
            edits = {k: before[k] for k in keys if before[k] != after[k]}         # only the keys the pass changed go back
            if history:
                edits["stall"] = _log_without(raw["metadata"], history, dropped)
            if not S._stamp_write(p, raw, h0, edits):
                return {**out, "action": "moved", "why": "the item was written between the read and the replace: its write stands"}
        return {**out, "action": "set", "why": "the keys put back"}
    except Exception as e:  # noqa: BLE001
        print(f"until pass: {gid} not put back: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return _mig.refuse(shown, f"{e.__class__.__name__}: {str(e)[:200]}")


def write_op(S: Any, spec: dict[str, Any], op: str, by: str) -> dict[str, Any]:
    """op until {items: [id, …], pass_id?, dry?} | ununtil {items: [{item, before, after}, …], pass_id?} (at most _mig.BATCH): the until pass over the open items. No begin and no hold: each item is
    worked out and written under its own lock (`one`). `dry` (until only) writes nothing and answers what each item would get. One publish at the end when anything was written. → {"op", "results": [...]}."""
    extra = [k for k in spec if k not in S._STAMP_BODY]
    if extra:
        raise ToolError(f"Refused: {op} takes op, sender, items, pass_id and dry only (got {', '.join(sorted(map(str, extra)))}): it rewrites the wait keys and nothing else")
    items = spec.get("items")
    if not isinstance(items, list) or not items or len(items) > _mig.BATCH:
        raise ToolError(f"Refused: items is a list of 1 to {_mig.BATCH} " + ("item ids" if op == "until" else "entries {item, before, after}"))
    pid = str(spec.get("pass_id") or "")
    if pid and not _mig.PASS_ID_RX.fullmatch(pid):
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
            results.append(_mig.refuse(str(it or "?"), str(e)))
            continue
        results.append(one(S, gid, dry=dry))
    if any(r["action"] == "set" for r in results):
        S._publish()
    if pid and not dry:
        S._stamp_pass_keep(pid, by, op, results)
    return {"op": op, "results": results}
