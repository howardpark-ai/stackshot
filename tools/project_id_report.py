#!/usr/bin/env python3
"""tools/project_id_report.py — the data change that stores each item's project by its permanent id (item_project.py: `metadata.project_id`), in three modes:

  tools/project_id_report.py                           DRY RUN (the default): the live store copied into a private scratch folder, the whole pass run on the copy, and what the readers show before and after read back. Writes nothing live.
  tools/project_id_report.py --store <dir>             the dry run over another store directory (it holds the item folders, project-record.json and projects.json)
  tools/project_id_report.py --json out.json           the rows as JSON too
  tools/project_id_report.py --apply --sender <you>    the real pass, through the live server (POST /client/migrate op project_id, this machine's token; [model] migration = true and the sender in
                                                       [model] migration_senders). Run by a person on deploy. It asks the server for the plan first (op project_id with dry), writes the undo file
                                                       <run-dir>/<pass id>/undo.json (fsynced) BEFORE the first write, then stores the ids in batches and records each batch's real result in the undo file.
  tools/project_id_report.py --undo <file> --sender <you>   puts every item back the way the undo file says (op unproject_id): an item that still holds what the pass left loses the key; one a later save
                                                       changed is `kept` and left as it is; running it again is a no-op.

What the pass does per item, open or closed: it stores `metadata.project_id`, the permanent id (prj_<8 hex>) of the TOP-LEVEL project the item's page key names (a sub-page's key to the id of the project that owns it, a former
key of a page that moved or was renamed to the id of its project). Nothing else in the file changes: `project` stays as it is, no clock moves, and none of a save's other work is done. An item whose key names no project
the record knows is left as it is and listed (`unresolved`); the readers keep reading its key. An item that stores its id already is `same`, so a second run writes nothing.

The dry run prints the totals by result, the keys the record does not know, how many items each project has, and the readers' output before and after on the copy: the board's markdown, its brief and the server's brief,
frozen at one clock, which must be identical for the open items (it exits 1 when they are not, or when the server refuses an item). Python 3.12 or later; it runs itself in the tests' uv environment when fastmcp is missing."""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import fcntl
import json
import os
import shutil
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))
import compare_pair_reads as CP  # noqa: E402  — the private copy and the live config
import migrate_model as MM  # noqa: E402  — LiveApplier, say
import stamp_phase as SP  # noqa: E402  — load_dir, frozen, write_atomic, chunks, new_pass_id, num

DEFAULT_RUN = Path.home() / ".local" / "share" / "stackshot-runs" / "project-id-run"
say = MM.say


def readers(server: Any, store: Path, now: float) -> dict[str, str]:
    """What the readers show of the store at the clock `now`: the board's markdown and brief, the server's brief, the project key each reader takes for every open item (anchors.project_of: the page), and the project each shows for it (item_project.project_of: the top-level project)."""
    import anchors as _anc  # noqa: PLC0415
    import render as _render  # noqa: PLC0415
    out: dict[str, str] = {}
    with SP.frozen(now):
        b = _render.Board(str(store))
        out["board.md"] = b.markdown()
        out["board brief"] = b.brief()
        out["server brief"] = server.stackshot_brief()
    items = SP.load_dir(store)
    out["keys"] = json.dumps({g: _anc.project_of(server._load(g) or {}) for g, it in sorted(items.items(), key=lambda kv: SP.num(kv[0])) if it.get("status") == "open"}, sort_keys=True)
    out["projects shown"] = json.dumps({g: server._ip.project_of((server._load(g) or {}).get("metadata") or {}) for g, it in sorted(items.items(), key=lambda kv: SP.num(kv[0])) if it.get("status") == "open"}, sort_keys=True)      # the top-level project every reader that shows an item's project writes (item_project.project_of)
    return out


def dry_run(a: argparse.Namespace) -> int:
    CP.ensure_env(__file__)
    live = tomllib.loads(CP.LIVE_CONFIG.read_text(encoding="utf-8"))["paths"]
    store = Path(a.store or live["store"]).expanduser().resolve()
    brain = Path(live.get("brain") or "").expanduser() if live.get("brain") else None
    root: Path | None = None
    fd: int | None = None
    try:
        root = CP.make_scratch(store, brain)
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        fcntl.flock(fd, fcntl.LOCK_SH)
        os.environ["STACKSHOT_CONFIG"] = str(root / "stackshot.toml")
        os.environ["STACKSHOT_AUTH"] = "off"
        os.environ.pop("STACKSHOT_URL", None)
        os.environ["STACKSHOT_FLEET_DIR"] = str(root / "fleet")
        import server  # noqa: PLC0415
        server._publish = lambda: None
        d = root / "repo/board-data"
        now = time.time()
        items = SP.load_dir(d)
        ids = sorted(items, key=SP.num)
        opens = [g for g in ids if items[g].get("status") == "open"]
        before = readers(server, d, now)
        planned = {g: server._pid_one(g, dry=True) for g in ids}
        wrote = {g: server._pid_one(g) for g in ids}
        again = {g: server._pid_one(g) for g in ids}
        after_items = SP.load_dir(d)
        after = readers(server, d, now)
        by_plan = collections.Counter(r["action"] for r in planned.values())
        by_result = collections.Counter(r["action"] for r in wrote.values())
        print(f"{len(ids)} items read from {store} ({len(opens)} open, {len(ids) - len(opens)} closed); the pass run on a copy of it\n")
        print("the plan:   " + ", ".join(f"{k} {n}" for k, n in sorted(by_plan.items())))
        print("the pass:   " + ", ".join(f"{k} {n}" for k, n in sorted(by_result.items())) + "; a second pass: " + ", ".join(f"{k} {n}" for k, n in sorted(collections.Counter(r["action"] for r in again.values()).items())))
        unresolved = [r for g, r in sorted(wrote.items(), key=lambda kv: SP.num(kv[0])) if r["action"] == "unresolved"]
        if unresolved:
            print(f"\nitems whose page key names no project the record knows ({len(unresolved)}); they keep their key, nothing is stored:")
            for k, n in sorted(collections.Counter(r["key"] or "(none)" for r in unresolved).items()):
                print(f"  {k}  x{n}")
        stored = {g: (it.get("metadata") or {}).get("project_id") for g, it in after_items.items()}
        per = collections.Counter(v for v in stored.values() if v)
        print(f"\nitems with a project id after the pass: {sum(per.values())} of {len(ids)}, over {len(per)} projects; the largest: " + ", ".join(f"{k} {n}" for k, n in per.most_common(5)))
        open_unstamped = [server._gh.shown(g) for g in opens if not stored.get(g)]
        print(f"open items with no id after the pass: {len(open_unstamped)}" + (f" {open_unstamped}" if open_unstamped else ""))
        moved = []
        for g in ids:
            mb, ma = (items[g].get("metadata") or {}), (after_items[g].get("metadata") or {})
            if {k: v for k, v in mb.items() if k != "project_id"} != {k: v for k, v in ma.items() if k != "project_id"}:
                moved.append(server._gh.shown(g))
        print(f"items whose file differs from the original in more than the one key project_id: {len(moved)}" + (f" {moved}" if moved else ""))
        key_before = {g: str((items[g].get("metadata") or {}).get("project") or "") for g in ids}
        key_after = {g: server._ip.key_of((after_items[g].get("metadata") or {})) for g in ids}
        shifted = [(server._gh.shown(g), key_before[g], key_after[g]) for g in ids if key_before[g] != key_after[g]]
        shifted_open = [(server._gh.shown(g), key_before[g], key_after[g]) for g in opens if key_before[g] != key_after[g]]
        print(f"items whose project key reads differently after the pass: {len(shifted)} ({len(shifted_open)} open)" + "".join(f"\n  {s}: {b} -> {c}" for s, b, c in shifted))
        diff = [k for k in before if before[k] != after[k]]
        print(f"readers that show the open items differently before and after: {len(diff)}" + (f" {diff}" if diff else ""))
        for k in diff:
            lines = [(x, y) for x, y in zip(before[k].splitlines(), after[k].splitlines()) if x != y]
            print(f"  {k}: {len(before[k].splitlines())} -> {len(after[k].splitlines())} lines; first differences:")
            for x, y in lines[:6]:
                print(f"    - {x[:200]}\n    + {y[:200]}")
        refused = [r["item"] for r in wrote.values() if r["action"] == "refused"]
        print(f"items the server refuses: {len(refused)}" + (f" {refused}" if refused else ""))
        print(f"items the pass would write: {by_result.get('set', 0)} of {len(ids)}")
        if a.json:
            Path(a.json).write_text(json.dumps([{**wrote[g], "plan": planned[g]["action"], "again": again[g]["action"]} for g in ids], indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        return 1 if diff or refused or moved or shifted_open else 0
    finally:
        if fd is not None:
            os.close(fd)
        if root is not None:
            shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------------------------------------------- the real pass and its undo
def apply(a: argparse.Namespace, app: Any = None) -> int:
    """The real pass. `app` (tests only) answers app.call(body) → (status, answer) in place of the live server."""
    import config as _cfg
    store = _cfg.path("paths", "store")
    run_dir = Path(a.run_dir).expanduser()
    app = app or MM.LiveApplier(a.sender)
    snap = SP.load_dir(store)
    ids = sorted(snap, key=SP.num)
    say(f"{len(ids)} items read from {store}")
    plan: list[dict[str, Any]] = []
    for ch in SP.chunks(ids):
        st, d = app.call({"op": "project_id", "items": ch, "dry": True})
        if st != 200:
            say(f"the plan could not be made: [{st}] {d.get('error') if isinstance(d, dict) else d}")
            return 1
        plan += d["results"]
    todo = [(g, r) for g, r in zip(ids, plan) if r.get("action") == "would_set"]
    refused = [r["item"] for r in plan if r.get("action") == "refused"]
    unresolved = [r["item"] for r in plan if r.get("action") == "unresolved"]
    say(f"{len(todo)} of {len(ids)} would store an id; {sum(1 for r in plan if r.get('action') == 'same')} already do; {len(unresolved)} name no project the record knows; {len(refused)} refused" + (f" ({', '.join(refused)})" if refused else ""))
    if not todo:
        print(json.dumps({"stored": 0, "unresolved": unresolved}))
        return 1 if refused else 0
    pass_id = SP.new_pass_id()
    undo_path = run_dir / pass_id / "undo.json"
    undo = {"pass_id": pass_id, "by": a.sender, "when": dt.datetime.now(_cfg.tz()).strftime("%a %b %d %H:%M %Z"), "store": str(store),
            "items": [{"item": g, "shown": r["item"], "before": r["before"], "after": r["after"], "sha256_before": r["sha256_before"], "result": None} for g, r in todo]}
    SP.write_atomic(undo_path, undo)      # on disk, whole, before the first write
    say(f"undo file written: {undo_path}")
    entries = {e["item"]: e for e in undo["items"]}
    counts: collections.Counter[str] = collections.Counter()
    for ch in SP.chunks([g for g, _ in todo]):
        st, d = app.call({"op": "project_id", "items": ch, "pass_id": pass_id})
        if st != 200:
            say(f"a batch was refused as a whole: [{st}] {d.get('error') if isinstance(d, dict) else d}")
            counts["batch refused"] += len(ch)
            continue
        for g, r in zip(ch, d["results"]):
            counts[r["action"]] += 1
            e = entries[g]
            e["result"] = r["action"]
            if r["action"] in ("set", "same"):
                e["before"], e["after"], e["sha256_before"] = r["before"], r["after"], r["sha256_before"]
        SP.write_atomic(undo_path, undo)      # the real result of each item, kept as it comes
    print(json.dumps({"pass_id": pass_id, "undo": str(undo_path), "results": dict(counts), "refused_in_the_plan": refused, "unresolved": unresolved,
                      "moved_run_again_for_these": [e["shown"] for e in entries.values() if e.get("result") == "moved"]}, indent=1))
    return 1 if counts.get("refused") or counts.get("batch refused") or refused else 0


def undo(a: argparse.Namespace, app: Any = None) -> int:
    rec = json.loads(Path(a.undo).expanduser().read_text(encoding="utf-8"))
    todo = [e for e in rec["items"] if e.get("result") not in ("moved", "refused", "same")]
    say(f"{len(todo)} of {len(rec['items'])} entries to put back (pass {rec.get('pass_id')})")
    app = app or MM.LiveApplier(a.sender)
    counts: collections.Counter[str] = collections.Counter()
    kept: list[str] = []
    for ch in SP.chunks(todo):
        st, d = app.call({"op": "unproject_id", "items": [{"item": e["item"], "before": e["before"], "after": e["after"]} for e in ch]})
        if st != 200:
            say(f"a batch was refused as a whole: [{st}] {d.get('error') if isinstance(d, dict) else d}")
            counts["batch refused"] += len(ch)
            continue
        for e, r in zip(ch, d["results"]):
            counts[r["action"]] += 1
            if r["action"] == "kept":
                kept.append(e.get("shown") or e["item"])
    print(json.dumps({"results": dict(counts), "kept_because_a_later_save_changed_them": kept}, indent=1))
    return 1 if counts.get("refused") or counts.get("batch refused") else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Store each item's project by its permanent id: a dry run by default; --apply and --undo go through the live server.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="the real pass through the live server (needs --sender); run by a person on deploy")
    mode.add_argument("--undo", default="", metavar="FILE", help="take out the ids the undo file of a real pass names (needs --sender)")
    ap.add_argument("--store", help="the dry run: a store directory to read (default: [paths] store of the live config)")
    ap.add_argument("--json", help="the dry run: write the rows to this file")
    ap.add_argument("--sender", default="", help="the session that runs the pass (one of [model] migration_senders); needed with --apply and --undo")
    ap.add_argument("--run-dir", default=str(DEFAULT_RUN), help="the real pass: where the undo file is kept (<run-dir>/<pass id>/undo.json)")
    a = ap.parse_args(argv)
    if (a.apply or a.undo) and not a.sender.strip():
        ap.error("--apply and --undo need --sender <the session that runs the pass>")
    if a.apply:
        return apply(a)
    if a.undo:
        return undo(a)
    return dry_run(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
