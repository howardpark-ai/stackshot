"""stamp.py: the stamp of the stored phase and waits_on, the sweep that keeps it true, and the project-id pass.

Every save of an open item stores two keys beside its fields (`_phase_stamp`, called from `writes.save`'s steps): `metadata.phase` (alive | waiting) and, for a waiting item, `metadata.waits_on` (time | anchor | item |
relay | event): what the board shows the item as. The stamp pass (`_stamp_one`, `_stamp_write_op`, `_unstamp_one`) writes those two keys on the items already there and puts them back; `_phase_sweep` keeps them true as
the clock moves (the minute set's `phase_sweep` tick and a config reload). The project-id pass (`_pid_one`, `_unpid_one`, `_pid_write_op`) is the stamp pass's shape for `metadata.project_id`; its rules are in
model/item_project_pass.py, which reads the file helpers of this module (`_stamp_open`, `_stamp_sha`, `_stamp_write`, `_stamp_pass_keep`) off the `S` it is given.

`PassHost` is that `S` for the three passes written against the server module (model/item_project_pass.py, model/last_activity_pass.py, waits/until_pass.py): a name they read is looked up when it is read, on the owners
the host is given (this module, service/retire_passes.py, web/server.py), so a suite that replaces one on its owner reaches the passes.

The publish is the surface's, reached through `Hooks` in service/passes_hooks.py, looked up when it runs. A suite that replaces a function or the clock of the pass sets it here (and `time` here, since this module
reads its own).

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core import readonly as _ro
from stackshot.core.store import _item_files
from stackshot.github import ghsync as _gh
from stackshot.model import item_project_pass as _ipp
from stackshot.model import migration as _mig
from stackshot.model import model as _model
from stackshot.model.ids import _norm_id
from stackshot.service import item_read as _item_read
from stackshot.service import migrations as _migrations
from stackshot.service import store as _svcstore
from stackshot.service import writes as _writes
from stackshot.service.passes_hooks import hooks as _hooks
from stackshot.service.store import _legacy_hold, _legacy_needs, _path


class _Publish:
    """`S._pubmod._publish()` of the passes written against the server module: the publish is the surface's, looked up when it runs."""

    @staticmethod
    def _publish() -> Any:
        return _hooks().publish()


_pubmod = _Publish          # what `_ipp` reads off this module as its `S`


class PassHost:
    """The `S` of model/last_activity_pass.py and waits/until_pass.py (they read the stamp helpers, the retire reading and the server's own names off it): a name is looked up on each owner in turn when it is read."""

    def __init__(self, *owners: Any) -> None:
        self._owners = owners

    def __getattr__(self, name: str) -> Any:
        for m in self._owners:
            if hasattr(m, name):
                return getattr(m, name)
        raise AttributeError(name)


def _stamp_values(gid: str, item: dict[str, Any]) -> tuple[str, str]:
    """(phase, waits_on) of an item as the board shows it now: the one reading (model.view of model.derive, so a held or dated or wait_basis doing item is waiting) worked out by model.stamp_values,
    "" = the key is absent. Both the save's stamp (_phase_stamp) and the stamp pass (_stamp_one) take it from here."""
    probe = {**item, "gid": gid}
    shown = _model.view(probe, _item_read._model_of(probe), after_open=lambda i_: _item_read._after_open(i_.get("metadata") or {}), check=False)
    return _model.stamp_values(probe, shown)


def _phase_stamp(gid: str, item: dict[str, Any]) -> None:
    """Store the phase of an open item (metadata.phase: alive | waiting) and, for a waiting one, the kind of its wait (metadata.waits_on: time | anchor | item | relay | event), worked out from its fields by the one
    reading the board shows today (model.view of model.derive, so a held or dated or wait_basis doing item is waiting), in the one place every save passes (`writes.save`). A closed item is dead and stores neither; an alive
    one stores no waits_on. Nothing else is written: the older fields are stored exactly as the write left them, and the stored values are what the readers take the decision from (model.view reads
    nothing else; the sweep keeps them true). A failure here never fails a write.
    The wait_kind is not added: a stored wait_kind hands an item to the watchers (watchers.watches) and, on a doing item, makes derive read a conflict, so adding one to an item that stores none would change what
    the board does with it. An item that already stores one keeps it, and the waits_on beside it agrees with it."""
    meta = item.get("metadata")
    if not isinstance(meta, dict):
        return
    if item.get("status") != "open":
        meta.pop("phase", None)
        meta.pop("waits_on", None)
        return
    try:
        phase, waits_on = _stamp_values(gid, item)
        for key, val in (("phase", phase), ("waits_on", waits_on)):
            if val:
                meta[key] = val
            else:
                meta.pop(key, None)
    except Exception as e:  # noqa: BLE001  — the phase is groundwork for a later pass; a write is never refused for it
        print(f"phase: {gid} not stamped: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------------------------------------------- the stamp pass: phase and waits_on on the open items
_STAMP_KEYS = ("phase", "waits_on")                  # the two keys the stamp pass writes, and the only ones it may name
_STAMP_BODY = frozenset({"op", "sender", "items", "pass_id", "dry"})
_STAMP_ENTRY = frozenset({"item", "before", "after", "sha256_before"})


def _stamp_sha(data: bytes) -> str:
    import hashlib  # noqa: PLC0415
    return hashlib.sha256(data).hexdigest()


def _stamp_pair(meta: dict[str, Any]) -> dict[str, Any]:
    """The two stamped keys as an item stores them: the value, None = the key is absent."""
    return {k: meta.get(k) for k in _STAMP_KEYS}


def _stamp_commit(p: Path, tmp: Path, h0: str) -> bool:
    """The last step of a stamp: the file is read once more and replaced only if it is the bytes the stamp was worked out from (`h0`, their sha256). A writer that does not take the item lock (the old wake pass
    reads and saves without it) may have written the item since; its change is never overwritten: the temporary file is dropped and False comes back (the answer is `moved`, the next run stamps it)."""
    try:
        now = _stamp_sha(p.read_bytes())
    except OSError:
        now = ""
    if now != h0:
        tmp.unlink(missing_ok=True)
        return False
    os.replace(tmp, p)
    return True


def _stamp_write(p: Path, raw: dict[str, Any], h0: str, edits: dict[str, Any]) -> bool:
    """Write `raw` (the item as its file holds it) with the two stamped keys set to `edits` (None drops a key): nothing else in the file changes, and none of `writes.save`'s other work is done (no activity seed, no mover
    settled, no hand-off record, no for-you or landed row, no search or GitHub job: a stamp is not an event on the item). The metadata keeps its order; a new key goes last. → False when the file moved (_stamp_commit)."""
    _ro.guard("item write")
    meta = raw["metadata"]
    for k, v in edits.items():
        if v is None:
            meta.pop(k, None)
        else:
            meta[k] = v
    tmp = p.with_name(f".{p.name}.stamp.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=1)
        return _stamp_commit(p, tmp, h0)
    finally:
        tmp.unlink(missing_ok=True)


def _stamp_open(gid: str, shown: str, closed_ok: bool = False) -> tuple[Path, bytes, dict[str, Any], dict[str, Any] | None]:
    """(the file, its bytes, the item as the file holds it, None) for an open item, or (…, a refusal) for one that is missing, closed or damaged (`closed_ok`: a closed item is returned like an open one: the
    project-id pass writes every item). Read under the item lock by the caller."""
    p = _path(gid)
    if not p.exists():
        return p, b"", {}, _mig.refuse(shown, "no such item")
    data = p.read_bytes()
    try:
        raw = json.loads(data)
    except ValueError:
        return p, data, {}, _mig.refuse(shown, "the item file does not read")
    if not isinstance(raw, dict) or not isinstance(raw.get("metadata"), dict):
        return p, data, {}, _mig.refuse(shown, "the item has no metadata")
    if raw.get("status") != "open" and not closed_ok:
        return p, data, raw, _mig.refuse(shown, f"closed: the item is {raw.get('status')}, and a closed item is left as it is")
    return p, data, raw, None


def _stamp_one(gid: str, dry: bool = False) -> dict[str, Any]:
    """Stamp one open item with the phase and the wait's kind the board shows it as now (metadata.phase, metadata.waits_on): → {"item", "action": set | same | moved | refused, "why", "before", "after", "sha256_before"}
    (before and after = {phase, waits_on}, None = the key is absent). The values are worked out HERE, under the item lock, from the item's fields as they stand and the clock now (never carried from a plan, so none
    is stale), by the same reading as every save's stamp (_stamp_values). `same`: the item already stores them, nothing is written. `moved`: a writer that takes no lock wrote the item between the read and
    the replace (_stamp_commit); its write stands. `refused`: a closed or missing item. Only the two keys are written (_stamp_write); `wait_kind` is never touched.
    `dry`: nothing is written, and an item that would be stamped answers `would_set` (the plan the script shows before it writes)."""
    shown = _gh.shown(gid)
    try:
        with _writes.ITEM_LOCK:
            p, data, raw, refusal = _stamp_open(gid, shown)
            if refusal is not None:
                return refusal
            h0 = _stamp_sha(data)
            norm = json.loads(data)
            _legacy_hold(norm)
            _legacy_needs(norm)
            phase, waits_on = _stamp_values(gid, norm)
            before, after = _stamp_pair(raw["metadata"]), {"phase": phase or None, "waits_on": waits_on or None}
            out = {"item": shown, "before": before, "after": after, "sha256_before": h0}
            if before == after:
                return {**out, "action": "same", "why": ""}
            if dry:
                return {**out, "action": "would_set", "why": "phase and waits_on would be stamped"}
            if not _stamp_write(p, raw, h0, after):
                return {**out, "action": "moved", "why": "the item was written between the read and the replace: its write stands, and the next run stamps it", "after": before}
        return {**out, "action": "set", "why": "phase and waits_on stamped"}
    except Exception as e:  # noqa: BLE001  — one item that fails never stops the batch
        print(f"stamp: {gid} not stamped: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return _mig.refuse(shown, f"{e.__class__.__name__}: {str(e)[:200]}")


_PHASE_SWEEP: dict[str, Any] = {"runs": 0, "swept": 0, "stamped": 0, "moved": 0, "refused": 0, "disagreements": 0, "last_run": None, "last_stamped": None, "last_ms": None}
_PHASE_SWEEP_LOCK = threading.Lock()                 # the counters only: the tick (runner thread) and a config reload (the loop's thread) may both sweep


def _phase_sweep() -> list[str]:
    """Keep the stored phase and waits_on true as the clock moves: recompute every open item's pair (_stamp_values: the reading the board shows, at the clock now) WITHOUT the item lock, compare it with what the
    item stores, and call _stamp_one only for a difference. _stamp_one works the pair out again under the item lock and re-checks the file bytes before it replaces them, so the write is the stamp pass's own: the two
    keys only (no `updated`, no `written_by`, no activity or hand-off record, no For you row, no GitHub job, no notice, no History line). The edges a stored value falls behind at are in the PR3 design: a dated
    wait's wake coming within [waiting] dated_wait_min_hours, a wait_basis wake, the instance's midnight for a dated step, an `after` item closing for an item with no stored state, an anchor scoped to the project, a change
    of config. A writer that took no lock between the read and the replace makes the answer `moved`: its write stands, and the next sweep stamps it. A warm standby copy sweeps nothing and writes nothing.
    → the ids stamped (the caller publishes when there are any). Counters: _PHASE_SWEEP, `phase_sweep` in GET /audit/status."""
    if _ro.is_read_only():
        return []
    t0 = time.time()
    swept = diff = moved = refused = 0
    stamped: list[str] = []
    for gid, _p in _item_files():
        try:
            it = _svcstore._load(gid)
        except Exception:  # noqa: BLE001  — a file that vanished or does not read is left to the pass that owns it
            continue
        meta = it.get("metadata")
        if it.get("status") != "open" or not isinstance(meta, dict):
            continue
        swept += 1
        try:
            phase, waits_on = _stamp_values(gid, it)
        except Exception as e:  # noqa: BLE001  — one item that fails never stops the sweep
            print(f"phase sweep: {gid} not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
            continue
        have = _stamp_pair(meta)
        if have == {"phase": phase or None, "waits_on": waits_on or None}:
            continue
        diff += 1
        res = _stamp_one(gid)
        if res["action"] == "set":
            stamped.append(gid)
            print(f"phase sweep: {gid} stamped {have['phase'] or '-'}/{have['waits_on'] or '-'} -> {res['after']['phase'] or '-'}/{res['after']['waits_on'] or '-'}", file=sys.stderr, flush=True)
        elif res["action"] == "moved":
            moved += 1
        elif res["action"] == "refused":
            refused += 1
    with _PHASE_SWEEP_LOCK:
        s = _PHASE_SWEEP
        s["runs"] += 1; s["swept"] = swept; s["stamped"] += len(stamped); s["moved"] += moved; s["refused"] += refused; s["disagreements"] += diff
        s["last_run"] = t0; s["last_ms"] = round((time.time() - t0) * 1000.0, 1)
        if stamped:
            s["last_stamped"] = t0
    return stamped


def _phase_tick() -> list[str]:
    """The runner's phase sweep (right after the anchor pass): _phase_sweep, and one publish when it stamped something (the pattern of the wake pass). Nothing shown changes, so the publish is only the board's own
    refresh of what it holds."""
    done = _phase_sweep()
    if done:
        _hooks().publish()
    return done


def _phase_sweep_status() -> dict[str, Any]:
    """The sweep's record for `GET /audit/status`: `runs`, `swept` (open items looked at in the last run), `stamped`, `moved` and `refused` (since the start), `disagreements` (stored pairs found different from the
    reading, since the start; each one a stamp or a `moved`), `last_run` and `last_stamped` (epoch seconds, None = none yet) and `last_ms`, with `unstamped_reads`: model.UNSTAMPED, the reads of an open item that stored no usable pair."""
    with _PHASE_SWEEP_LOCK:
        return {**_PHASE_SWEEP, "unstamped_reads": _model.UNSTAMPED["count"]}


def _stamp_state(v: Any, key: str) -> bool:
    """A value the undo may name for a stamped key: None (absent) or a word that key may hold."""
    return v is None or (isinstance(v, str) and v in (_model.PHASES if key == "phase" else _model.WAIT_KINDS))


def _unstamp_one(w: Any) -> dict[str, Any]:
    """Put one item's two stamped keys back: `w` = {item, before, after} (the keys as they were, and as the stamp left them; None = absent). Under the item lock, if the item holds `after` it gets `before` (a key
    that was absent is dropped) → `set`; if it already holds `before` → `same`; if it holds anything else (a later save restamped it) → `kept`, untouched. A closed item → `refused`. Running it again is a no-op."""
    if not isinstance(w, dict):
        return _mig.refuse("?", "an entry is an object {item, before, after}")
    try:
        gid = _norm_id(str(w.get("item") or ""))
    except ToolError as e:
        return _mig.refuse(str(w.get("item") or "?"), str(e))
    shown = _gh.shown(gid)
    extra = [k for k in w if k not in _STAMP_ENTRY]
    if extra:
        return _mig.refuse(shown, f"the undo names {', '.join(sorted(map(str, extra)))}: an entry holds item, before and after only")
    sides: dict[str, dict[str, Any]] = {}
    for side in ("before", "after"):
        d = w.get(side)
        if not isinstance(d, dict) or set(d) != set(_STAMP_KEYS):
            return _mig.refuse(shown, f"{side} is {{phase, waits_on}}, and names no other key")
        if not all(_stamp_state(d[k], k) for k in _STAMP_KEYS):
            return _mig.refuse(shown, f"{side} holds a value no stamp writes")
        sides[side] = d
    try:
        with _writes.ITEM_LOCK:
            p, data, raw, refusal = _stamp_open(gid, shown)
            if refusal is not None:
                return refusal
            h0 = _stamp_sha(data)
            now = _stamp_pair(raw["metadata"])
            out = {"item": shown, "before": sides["before"], "after": sides["after"], "sha256_before": h0}
            if now == sides["before"]:
                return {**out, "action": "same", "why": "it already holds the keys it had"}
            if now != sides["after"]:
                return {**out, "action": "kept", "why": "it holds other values than the stamp left (a later save restamped it): left as it is", "now": now}
            if not _stamp_write(p, raw, h0, sides["before"]):
                return {**out, "action": "moved", "why": "the item was written between the read and the replace: its write stands"}
        return {**out, "action": "set", "why": "the keys put back"}
    except Exception as e:  # noqa: BLE001
        print(f"stamp: {gid} not put back: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return _mig.refuse(shown, f"{e.__class__.__name__}: {str(e)[:200]}")


def _stamp_pass_keep(pass_id: str, by: str, op: str, results: list[dict[str, Any]]) -> None:
    """The results of a stamp or an undo batch, kept in the pass record (<state>/migration/<pass id>.json) beside the script's own undo file. A record that cannot be kept is logged, never fatal."""
    try:
        with _migrations.MIG_PASS_LOCK:
            try:
                rec = _migrations.pass_load(pass_id)
            except ToolError:
                rec = {"pass_id": pass_id, "by": by, "kind": "stamp", "begun": time.time(), "ended": None, "owners": {}, "items": [], "undone": []}
            rec.setdefault("items" if op in ("stamp", "retire", "project_id", "until", "lastact") else "undone", []).extend(results)
            _migrations.pass_save(rec)
    except Exception as e:  # noqa: BLE001
        print(f"stamp: the results of pass {pass_id} not kept: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


def _stamp_write_op(spec: dict[str, Any], op: str, by: str) -> dict[str, Any]:
    """op stamp {items: [id, …], pass_id?, dry?} | unstamp {items: [{item, before, after}, …], pass_id?} (at most _mig.BATCH): the stamp pass. No begin and no hold: each item is worked out and written under its own lock
    (_stamp_one), so a session's update takes its turn and nothing is planned that could go stale. `dry` (stamp only) writes nothing and answers what each item would get. One publish at the end when anything was written.
    → {"op", "results": [...]}."""
    extra = [k for k in spec if k not in _STAMP_BODY]
    if extra:
        raise ToolError(f"Refused: {op} takes op, sender, items and pass_id only (got {', '.join(sorted(map(str, extra)))}): it writes the two keys phase and waits_on and nothing else")
    items = spec.get("items")
    if not isinstance(items, list) or not items or len(items) > _mig.BATCH:
        raise ToolError(f"Refused: items is a list of 1 to {_mig.BATCH} " + ("item ids" if op == "stamp" else "entries {item, before, after}"))
    pid = str(spec.get("pass_id") or "")
    if pid and not _mig.PASS_ID_RX.fullmatch(pid):
        raise ToolError("Refused: pass_id is <YYYYMMDD-HHMMSS>-<6 hex>")
    dry = bool(spec.get("dry"))
    if dry and op != "stamp":
        raise ToolError("Refused: dry goes with stamp only")
    results: list[dict[str, Any]] = []
    for it in items:
        if op == "unstamp":
            results.append(_unstamp_one(it))
            continue
        try:
            gid = _norm_id(str(it or ""))
        except ToolError as e:
            results.append(_mig.refuse(str(it or "?"), str(e)))
            continue
        results.append(_stamp_one(gid, dry=dry))
    if any(r["action"] == "set" for r in results):
        _hooks().publish()
    if pid and not dry:
        _stamp_pass_keep(pid, by, op, results)
    return {"op": op, "results": results}


# ---------------------------------------------------------------------------------------------------------------- the project-id pass: metadata.project_id on every item (item_project_pass.py)
def _pid_one(gid: str, dry: bool = False) -> dict[str, Any]:
    """The project-id pass on one item (item_project_pass.one)."""
    return _ipp.one(sys.modules[__name__], gid, dry)


def _unpid_one(w: Any) -> dict[str, Any]:
    """The project-id pass's undo on one entry (item_project_pass.undo_one)."""
    return _ipp.undo_one(sys.modules[__name__], w)


def _pid_write_op(spec: dict[str, Any], op: str, by: str) -> dict[str, Any]:
    """The ops project_id and unproject_id of the migration route (item_project_pass.write_op)."""
    return _ipp.write_op(sys.modules[__name__], spec, op, by)

