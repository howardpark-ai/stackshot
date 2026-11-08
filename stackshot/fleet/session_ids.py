"""session_ids.py — the one-shot migration to permanent session ids.

  python3 session_ids.py migrate --dry-run     read-only: say what would change and what would stay, change nothing
  python3 session_ids.py migrate --request     ask the server to apply it at its next start (writes the request file, nothing else)
  python3 session_ids.py rollback <undo file>  ask the server to put an applied migration back at its next start (same request file)

What it rewrites, where the fleet tool's registry (sessions_registry.py) resolves the stored value to ONE session: on the OPEN items in the store,
metadata.owner, the session entries of metadata.needs, and metadata.observers → the permanent id. decision and external stay as words; a needs
entry that becomes a second spelling of a session already listed is dropped (the first stays). A closed item is the record of its time and is
never touched. owner_name, the clocks and every other field stay as they are. roles.json is not part of it: the server's own roles sync writes
its `ids` map. The inbox hold lists (held-*.txt, release-*.txt) are the fleet tool's files and are not touched either: stackshot reads them in either
form (inbox.py, push.py) and never writes a permanent id into them.

Who writes: never this CLI. The apply runs INSIDE the server, at its start and before it serves a request (server.py _session_ids_pass), when
`<state>/session-ids-migrate.request` exists. The server consumes the file (also when the registry cannot be read at that start: nothing is done,
and the request is made again once it reads), applies before it starts any writer thread or serves a request, so nothing else writes an item
meanwhile (not every writer takes the item lock, so the lock is not what makes it safe), saves each item through its usual save, and writes
`<state>/session-ids-undo-<UTC time>.json` (gid, field, old, new) BEFORE the first item is touched. A failure is logged and the start goes on.
A rollback is a request too (its file names the undo file): the server puts each field back to its old value where the field still holds the
new one (an item changed since is left, and said so). Doing both through the server keeps one writer of the store and no cross-process race.

A value the registry cannot resolve (a cloud session, a name two sessions carry, a person, an id it does not list) is kept as it is, and the
summary says why. Running it again changes nothing.

Stdlib only; it reads the same configuration as the server and is refused outside the production checkout without $STACKSHOT_CONFIG,
as the server is, so a stray run never touches the live store."""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import copy
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

from stackshot import paths as _paths
from stackshot.core import config as _cfg  # noqa: E402
from stackshot.projects import projects as _prj  # noqa: E402  — write_atomic: a temp file in the state dir, never in the store (the store is a git checkout)
from stackshot.fleet import sessions_registry as _sr  # noqa: E402

PRODUCTION_CHECKOUT = "~/stackshot"
REQUEST = "session-ids-migrate.request"       # in the state dir: "apply", or "rollback <undo file>" (one line)
UNDO = "session-ids-undo-{ts}.json"
_KINDS = ("decision", "external")


def _refuse_unconfigured() -> None:
    if os.environ.get("STACKSHOT_CONFIG") or os.environ.get("BOARD_MCP_CONFIG"):
        return
    here = _paths.ROOT
    if here != Path(os.path.expanduser(PRODUCTION_CHECKOUT)).resolve():
        sys.exit(f"session_ids.py: STACKSHOT_CONFIG is unset and {here} is not the production checkout; set it to the config of the store to migrate. Nothing was touched.")


def request_path() -> Path:
    return _cfg.state(REQUEST)


def _items(store: Path) -> list[tuple[str, Path]]:
    out = []
    for d in sorted(store.iterdir()) if store.is_dir() else []:
        if not (d.is_dir() and len(d.name) == 1 and d.name.isalpha()):
            continue
        for p in sorted(d.glob("*.json")):
            if not p.name.startswith(".") and p.stem.isdigit():
                out.append((f"{d.name}{p.stem}", p))
    return out


def _ref(v: Any, rep: dict, where: str, gid: str) -> Any:
    """One stored reference → what it should be; records the reason it stays when the registry cannot say."""
    s = str(v or "").strip()
    if not s or s.lower() in _KINDS:
        return v
    sid, why = _sr.explain(s)
    if sid is None:
        rep["kept"].append((gid, where, s, why))
        return v
    if sid == s:
        rep["same"] += 1
        return v
    return sid


def plan_item(gid: str, it: Any, rep: dict) -> dict[str, Any] | None:
    """The metadata fields of one item that the migration would change → {field: (old, new)}, or None for a closed or odd item. `it` is not changed.
    Open means status open or the legacy on_hold; a closed item is counted and left."""
    if not isinstance(it, dict):
        return None
    if it.get("status") not in ("open", "on_hold"):
        rep["closed"] += 1                                     # the record of its time
        return None
    meta = it.get("metadata")
    if not isinstance(meta, dict):
        return None
    out: dict[str, Any] = {}
    if str(meta.get("owner") or "").strip():
        new = _ref(meta["owner"], rep, "owner", gid)
        if new != meta["owner"]:
            out["owner"] = (meta["owner"], new)
    needs = meta.get("needs")
    if isinstance(needs, list):
        new_l: list = []
        for x in needs:
            y = _ref(x, rep, "needs", gid)
            if str(y).strip().lower() in _KINDS or y not in new_l:
                new_l.append(y)
        if new_l != needs:
            out["needs"] = (list(needs), new_l)
    elif needs not in (None, "", []):
        rep["kept"].append((gid, "needs", repr(needs), "the old one-word form (the server rewrites it at start)"))
    obs = meta.get("observers")
    if isinstance(obs, list):
        new_o: list = []
        for x in obs:
            y = _ref(x, rep, "observers", gid)
            if y not in new_o:
                new_o.append(y)
        if new_o != obs:
            out["observers"] = (list(obs), new_o)
    return out or None


def new_report() -> dict:
    return {"changed": [], "kept": [], "same": 0, "closed": 0, "written": 0, "skipped": [], "errors": [], "undo": ""}


def scan(store: Path | None = None, rep: dict | None = None) -> dict:
    """Read-only pass over the store: the report with `changed` = [(gid, field, old, new)] and `kept` = [(gid, field, value, why)]."""
    rep = rep if rep is not None else new_report()
    if not _sr.available():
        rep["errors"].append(("-", "no session registry is readable under [client] session_links: nothing to resolve against"))
        return rep
    for gid, p in _items(store or _cfg.path("paths", "store")):
        try:
            it = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            rep["errors"].append((gid, f"unreadable: {e}")); continue
        for field, (old, new) in (plan_item(gid, it, rep) or {}).items():
            rep["changed"].append((gid, field, old, new))
    return rep


def write_undo(rows: list[tuple[str, str, Any, Any]], now: dt.datetime | None = None) -> Path:
    """The undo file, written whole before any item is touched: <state>/session-ids-undo-<UTC time>.json = {schema, at, changes: [{gid, field, old, new}]}."""
    now = now or dt.datetime.now(dt.timezone.utc)
    p = _cfg.state(UNDO.format(ts=now.strftime("%Y%m%dT%H%M%SZ")))
    _prj.write_atomic(p, json.dumps({"schema": 1, "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                     "changes": [{"gid": g, "field": f, "old": o, "new": n} for g, f, o, n in rows]}, ensure_ascii=False, indent=1))
    return p


def apply_to(it: dict, field: str, old: Any, new: Any) -> bool:
    """Set metadata[field] = new on `it` (in memory) when it still holds `old`; → True when changed."""
    meta = it.get("metadata")
    if not isinstance(meta, dict) or meta.get(field) != old:
        return False
    meta[field] = copy.deepcopy(new)
    return True


def read_request() -> tuple[str, str]:
    """The request file → ("apply", "") | ("rollback", <undo file>) | ("", "") for none or one that does not read. Does not consume it."""
    try:
        line = (request_path().read_text(encoding="utf-8").strip().splitlines() or [""])[0].strip()
    except OSError:
        return "", ""
    if line == "apply":
        return "apply", ""
    if line.startswith("rollback ") and line[9:].strip():
        return "rollback", line[9:].strip()
    return "", ""


def summary(rep: dict, apply: bool = False) -> str:
    out = []
    for gid, field, was, now in rep["changed"]:
        out.append(f"{'changed' if apply else 'would change'}: {gid} {field}: {was} → {now}")
    for gid, field, v, why in rep["kept"]:
        out.append(f"kept: {gid} {field}: {v} — {why}")
    for gid, field, why in rep["skipped"]:
        out.append(f"skipped: {gid} {field}: {why}")
    for gid, why in rep["errors"]:
        out.append(f"error: {gid}: {why}")
    out.append(f"{'applied' if apply else 'dry run (nothing written)'}: {len(rep['changed'])} field(s) to change in open items, {len(rep['kept'])} kept, "
               f"{rep['same']} already permanent ids, {rep['closed']} closed item(s) untouched, {rep['written']} item file(s) written"
               + (f", undo file {rep['undo']}" if rep.get("undo") else ""))
    return "\n".join(out)


def main(a: list[str]) -> int:
    if len(a) == 2 and a[0] == "migrate" and a[1] == "--dry-run":
        _refuse_unconfigured()
        r = scan()
        print(summary(r))
        return 1 if r["errors"] else 0
    if len(a) == 2 and a[0] == "migrate" and a[1] == "--request":
        _refuse_unconfigured()
        _prj.write_atomic(request_path(), "apply\n")
        print(f"requested: the server applies the migration at its next start and writes {_cfg.state(UNDO.format(ts='<UTC time>'))}; "
              f"undo with: python3 session_ids.py rollback <that file>")
        return 0
    if len(a) == 2 and a[0] == "rollback":
        _refuse_unconfigured()
        undo = Path(a[1]).expanduser().resolve()
        try:
            d = json.loads(undo.read_text(encoding="utf-8"))
            assert d.get("schema") == 1 and isinstance(d.get("changes"), list)
        except Exception as e:  # noqa: BLE001
            sys.exit(f"session_ids.py: {undo} is not an undo file ({e.__class__.__name__}). Nothing was requested.")
        _prj.write_atomic(request_path(), f"rollback {undo}\n")
        print(f"requested: the server puts back the {len(d['changes'])} change(s) of {undo.name} at its next start")
        return 0
    sys.exit("usage: python3 session_ids.py migrate --dry-run | migrate --request | rollback <undo file>")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
