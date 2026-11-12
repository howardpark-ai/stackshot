"""item_project_pass.py — the project-id pass: `metadata.project_id` stored on every item, open or closed, and put back (item_project.py has the rules; tools/project_id_report.py runs it).

The ops `project_id` and `unproject_id` of the migration route (server._migrate_write) call `write_op`. The pass is the stamp pass's shape (server._stamp_one): one item at a time under its lock, the file read
and replaced whole with only the one key changed (server._stamp_write: no activity seed, no mover settled, no hand-off, no search or GitHub job: a stamp is not an event on the item), a sha256 check so a
writer that takes no lock is never overwritten, and an undo that puts back only what the pass left. What differs: it writes closed items too, and a file keeps its access and modification times (a legacy
closed item holds no clock of its own and the board dates it by the file's time, so a write that moved it would move the item in the Closed list).

Every function takes `S`, the server module: the lock, the file helpers and the refusal shape are the migration route's own (server.py), and this file holds only what the pass does with them."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.model import ids as _ids
from stackshot.model import item_project as _ip

KEYS = ("project_id",)                          # the one key the pass writes, and the only one it may name


def write(S: Any, p: Path, raw: dict[str, Any], h0: str, edits: dict[str, Any]) -> bool:
    """server._stamp_write, and the file keeps its access and modification times. → False when the file moved (S._stamp_commit)."""
    st = p.stat()
    done = S._stamp_write(p, raw, h0, edits)
    if done:
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
    return done


def state_ok(v: Any) -> bool:
    """A value the undo may name for project_id: None (absent) or an id."""
    return v is None or (isinstance(v, str) and _ip.pr.is_id(v))


def one(S: Any, gid: str, dry: bool = False) -> dict[str, Any]:
    """Store the permanent id of the item's project on one item, open or closed (item_project.plan: the id the stored page key derives to through the record, a sub-page's key to the id of the top-level
    project that owns it, a former key to its project's): → {"item", "action": set | same | unresolved | moved | refused | would_set, "why", "key", "status", "before", "after", "sha256_before"} (before and
    after = {project_id}, None = the key is absent). Worked out HERE, under the item lock, from the file as it stands and the record now. `same`: the item stores that id already. `unresolved`: its key names no
    project the record knows (nothing is written, the key stays: the readers keep reading it). `moved`: a writer that takes no lock wrote the item between the read and the replace; its write stands. Only
    project_id is written: `project` is never touched. `dry`: nothing is written."""
    shown = S._gh.shown(gid)
    try:
        with S._writes.ITEM_LOCK:
            p, data, raw, refusal = S._stamp_open(gid, shown, closed_ok=True)
            if refusal is not None:
                return refusal
            h0 = S._stamp_sha(data)
            meta = raw["metadata"]
            pl = _ip.plan(meta)
            before = {"project_id": meta.get("project_id")}
            out = {"item": shown, "key": pl["key"], "status": str(raw.get("status") or ""), "before": before, "after": {"project_id": pl["id"] or meta.get("project_id")}, "sha256_before": h0}
            if pl["action"] == "drop":
                out["after"] = {"project_id": None}
                if dry:
                    return {**out, "action": "would_set", "why": "the stale id would be taken out: its key is a page no project owns"}
                if not write(S, p, raw, h0, {"project_id": None}):
                    return {**out, "action": "moved", "why": "the item was written between the read and the replace: its write stands, and the next run takes the id out", "after": before}
                return {**out, "action": "set", "why": "the stale project_id taken out"}
            if pl["action"] == "none":
                return {**out, "action": "unresolved", "why": "its page key names no project the record knows: nothing stored"}
            if pl["action"] == "same":
                return {**out, "action": "same", "why": ""}
            if dry:
                return {**out, "action": "would_set", "why": "the project's id would be stored"}
            if not write(S, p, raw, h0, {"project_id": pl["id"]}):
                return {**out, "action": "moved", "why": "the item was written between the read and the replace: its write stands, and the next run stores it", "after": before}
        return {**out, "action": "set", "why": "project_id stored"}
    except Exception as e:  # noqa: BLE001  — one item that fails never stops the batch
        print(f"project id: {gid} not stored: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return S._migrate_refuse(shown, f"{e.__class__.__name__}: {str(e)[:200]}")


def undo_one(S: Any, w: Any) -> dict[str, Any]:
    """Put one item's project_id back: `w` = {item, before, after} (the key as it was, and as the pass left it; None = absent). Under the item lock, if the item holds `after` it gets `before` (a key that was
    absent is dropped) → `set`; if it already holds `before` → `same`; anything else (a later save stored another) → `kept`, untouched. Running it again is a no-op."""
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
    sides: dict[str, dict[str, Any]] = {}
    for side in ("before", "after"):
        d = w.get(side)
        if not isinstance(d, dict) or set(d) != set(KEYS):
            return S._migrate_refuse(shown, f"{side} is {{project_id}}, and names no other key")
        if not state_ok(d["project_id"]):
            return S._migrate_refuse(shown, f"{side} holds a value that is no project id")
        sides[side] = d
    try:
        with S._writes.ITEM_LOCK:
            p, data, raw, refusal = S._stamp_open(gid, shown, closed_ok=True)
            if refusal is not None:
                return refusal
            h0 = S._stamp_sha(data)
            now = {"project_id": raw["metadata"].get("project_id")}
            out = {"item": shown, "before": sides["before"], "after": sides["after"], "sha256_before": h0}
            if now == sides["before"]:
                return {**out, "action": "same", "why": "it already holds the key it had"}
            if now != sides["after"]:
                return {**out, "action": "kept", "why": "it holds another id than the pass left (a later save stored it): left as it is", "now": now}
            if not write(S, p, raw, h0, sides["before"]):
                return {**out, "action": "moved", "why": "the item was written between the read and the replace: its write stands"}
        return {**out, "action": "set", "why": "the key put back"}
    except Exception as e:  # noqa: BLE001
        print(f"project id: {gid} not put back: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return S._migrate_refuse(shown, f"{e.__class__.__name__}: {str(e)[:200]}")


def write_op(S: Any, spec: dict[str, Any], op: str, by: str) -> dict[str, Any]:
    """op project_id {items: [id, …], pass_id?, dry?} | unproject_id {items: [{item, before, after}, …], pass_id?} (at most S._MIGRATE_BATCH): the project-id pass over every item, open or closed. No begin and
    no hold: each item is worked out and written under its own lock (`one`). `dry` (project_id only) writes nothing and answers what each item would get. One publish at the end when anything was written.
    → {"op", "results": [...]}."""
    extra = [k for k in spec if k not in S._STAMP_BODY]
    if extra:
        raise ToolError(f"Refused: {op} takes op, sender, items, pass_id and dry only (got {', '.join(sorted(map(str, extra)))}): it writes the one key project_id and nothing else")
    items = spec.get("items")
    if not isinstance(items, list) or not items or len(items) > S._MIGRATE_BATCH:
        raise ToolError(f"Refused: items is a list of 1 to {S._MIGRATE_BATCH} " + ("item ids" if op == "project_id" else "entries {item, before, after}"))
    pid = str(spec.get("pass_id") or "")
    if pid and not S._PASS_ID_RX.fullmatch(pid):
        raise ToolError("Refused: pass_id is <YYYYMMDD-HHMMSS>-<6 hex>")
    dry = bool(spec.get("dry"))
    if dry and op != "project_id":
        raise ToolError("Refused: dry goes with project_id only")
    results: list[dict[str, Any]] = []
    for it in items:
        if op == "unproject_id":
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
