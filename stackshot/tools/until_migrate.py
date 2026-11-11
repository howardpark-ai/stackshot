"""tools/until_migrate.py — the one-time data change that rewrites the waits stored before `until` as `until` (the rules are stackshot/waits/until_pass.py, the mapping is until_write.fold), in three modes:

  tools/until_migrate.py                              DRY RUN (the default): the live store copied into a private scratch folder, the whole pass run on the copy twice, and what it did read back: one block per
                                                      item with the wait keys it stores now and the ones it would store, the History line, then the totals. Writes nothing live; asks no server.
  tools/until_migrate.py --store <dir>                the dry run over another store directory
  tools/until_migrate.py --json out.json              the rows as JSON too
  tools/until_migrate.py --apply --sender <you>       the real pass, through the live server (POST /client/migrate op until, this machine's token; [model] migration = true and the sender in
                                                      [model] migration_senders). It asks the server for the plan first (op until with dry), then writes, BEFORE the first write, a backup of every item it
                                                      will touch (the item's file, byte for byte: <run-dir>/<pass id>/items/<id>.json) and the undo file <run-dir>/<pass id>/undo.json (fsynced), then rewrites in
                                                      batches and records each batch's real result in the undo file. The default run directory is ~/.local/share/stackshot-runs/until-run.
  tools/until_migrate.py --undo <undo.json> --sender <you>   puts every item's wait keys back the way the undo file says (op ununtil): an item that still holds what the pass left gets its old keys back; one a
                                                      later save changed is `kept` and left as it is; running it again is a no-op.

What the pass does per open item: it gives a wait stored in the old fields (wake, ask_by, hold) the form the writers store the same wait in today, through their own fold: `until` (and `wait_kind` where the old
fields imply one: an after link beside a date is an item wait), no old field, and one History line saying the wait was rewritten as until. A bare wake (no hold, no kind, no wait_basis, no after link) is a backstop,
not a wait, and stays as it is; so does an item with no old date. The server refuses (and leaves as it is) an item whose phase, kind of wait, mover, watched status, hold, stored phase or end date would read
differently. No item is closed or woken, nobody is told, no clock moves, nothing but the wait keys and the History line changes (the file is replaced whole under the item lock, with a sha256 check, as the stamp and
retire passes do). Running it twice changes nothing the second time.

Exit 0 · 1 when the dry run's second pass would still change something, or when a real write could not be made. Python 3.12 or later; it runs itself in the tests' uv environment when fastmcp is missing."""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import argparse
import collections
import datetime as dt
import fcntl
import json
import os
import shutil
import sys
import tomllib
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[2]
from stackshot.tools import compare_pair_reads as CP  # noqa: E402  — the private copy and the live config
from stackshot.tools import migrate_model as MM  # noqa: E402  — LiveApplier, say
from stackshot.tools import stamp_phase as SP  # noqa: E402  — load_dir, write_atomic, chunks, new_pass_id
# stackshot.waits.until_pass is imported inside dry_run, after the scratch config is set: it loads stackshot.core.config, which reads the config file once at import, so a top-level import would
# leave the server (and the pass) on the LIVE store paths.

DEFAULT_RUN = Path.home() / ".local" / "share" / "stackshot-runs" / "until-run"
say = MM.say


def show(d: dict[str, Any]) -> str:
    return json.dumps(d, ensure_ascii=False, sort_keys=True)


def refused_note(date: str) -> str:
    return (f"a refused item keeps its old fields untouched (such as a hold beside an open after item or one held by needs external: anything that would read differently as until): they are still read as before; "
            f"the next write that touches its wait stores it as until, and a person re-saves it with update(until=...) before {date}, when the old parameters wake, ask_by and hold stop being accepted in writes")


def alias_date() -> str:
    from stackshot.core import config as _cfg  # noqa: PLC0415
    return str(_cfg.get("model", "wait_alias_until", default="2026-11-25") or "2026-11-25")


def history_of(row: dict[str, Any]) -> str:
    return str((row or {}).get("history") or "")


def print_row(r: dict[str, Any]) -> None:
    keys = list(r.get("after") or {})
    print(f"{r['item']}  {r.get('form') or '-'}  ->  {r.get('new') or '-'}   [{r['action']}]")
    print(f"    old: {show({k: (r.get('before') or {}).get(k) for k in keys})}")
    print(f"    new: {show({k: (r.get('after') or {}).get(k) for k in keys})}")
    if history_of(r):
        print(f"    History line: stackshot: {history_of(r)}")
    if r["action"] in ("refused", "kept"):
        print(f"    why: {r.get('why')}")


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
        if "stackshot.core.config" in sys.modules:
            raise SystemExit("until_migrate: the config was loaded before the scratch copy was made; refusing to run the pass (it would write the live store)")
        from stackshot.web import server  # noqa: PLC0415
        from stackshot.waits import until_pass as UP  # noqa: PLC0415
        if not Path(server._path("g1")).resolve().is_relative_to(root.resolve()):
            raise SystemExit("until_migrate: the server does not resolve items inside the scratch copy; refusing to run the pass")
        server._publish = lambda: None
        d = root / "repo/board-data"
        items = SP.load_dir(d)
        opens = sorted((g for g, it in items.items() if it.get("status") == "open"), key=SP.num)
        planned = {g: UP.one(server, g, dry=True) for g in opens}
        wrote = {g: UP.one(server, g) for g in opens}
        again = {g: UP.one(server, g) for g in opens}
        rows = [{**planned[g], "result": wrote[g]["action"], "again": again[g]["action"]} for g in opens]
        todo = [r for r in rows if r["action"] in ("would_set", "refused", "kept")]
        print(f"{len(opens)} open items read from {store}; the pass run on a copy of it\n")
        for r in todo:
            print_row(r)
        by_result = collections.Counter(r["result"] for r in rows)
        forms = collections.Counter(r["form"] for r in rows if r["action"] == "would_set")
        kept = collections.Counter(r["why"] for r in rows if r["action"] == "same" and r["why"])
        print("\nitems to rewrite by their old fields: " + (", ".join(f"{k} {n}" for k, n in sorted(forms.items())) or "none"))
        print("left as they are: " + (", ".join(f"{n} x {k}" for k, n in sorted(kept.items())) or "none"))
        print("result of the pass on the copy: " + ", ".join(f"{k} {n}" for k, n in sorted(by_result.items())) + "; a second pass: " + ", ".join(f"{k} {n}" for k, n in sorted(collections.Counter(r["again"] for r in rows).items())))
        refused = [r["item"] for r in rows if r["action"] == "refused"]
        listed = [r["item"] for r in rows if r["action"] == "kept"]
        print(f"items the pass refuses (they would read differently as until): {len(refused)}" + (f" {refused}" if refused else ""))
        if refused:
            print(f"  {refused_note(alias_date())}")
        print(f"items kept and listed for a person: {len(listed)}" + (f" {listed}" if listed else ""))
        print(f"items the pass would write: {by_result.get('set', 0)} of {len(rows)}")
        if a.json:
            Path(a.json).write_text(json.dumps(rows, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        return 1 if any(r["again"] == "set" for r in rows) else 0
    finally:
        if fd is not None:
            os.close(fd)
        if root is not None:
            shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------------------------------------------- the real pass and its undo
def apply(a: argparse.Namespace, app: Any = None) -> int:
    """The real pass. `app` (tests only) answers app.call(body) → (status, answer) in place of the live server."""
    from stackshot.core import config as _cfg
    store = _cfg.path("paths", "store")
    run_dir = Path(a.run_dir).expanduser()
    app = app or MM.LiveApplier(a.sender)
    snap = SP.load_dir(store)
    cands = sorted((g for g, it in snap.items() if it.get("status") == "open" and any(k in (it.get("metadata") or {}) for k in ("wake", "ask_by"))), key=SP.num)
    say(f"{len(cands)} open items store a wake or an ask_by, of {len(snap)} items read from {store}")
    for f in unfinished(run_dir):
        say(f"an earlier pass did not finish recording: {f} has entries with no result; this run does not cover them. --undo {f} puts back what that pass wrote")
    plan: list[dict[str, Any]] = []
    for ch in SP.chunks(cands):
        st, d = app.call({"op": "until", "items": ch, "dry": True})
        if st != 200:
            say(f"the plan could not be made: [{st}] {d.get('error') if isinstance(d, dict) else d}")
            return 1
        plan += d["results"]
    todo = [(g, r) for g, r in zip(cands, plan) if r.get("action") == "would_set"]
    refused = [r["item"] for r in plan if r.get("action") == "refused"]
    say(f"{len(todo)} of {len(cands)} would be rewritten; {sum(1 for r in plan if r.get('action') == 'same')} left as they are; {sum(1 for r in plan if r.get('action') == 'kept')} kept and listed; {len(refused)} refused" + (f" ({', '.join(refused)})" if refused else ""))
    if refused:
        say(refused_note(alias_date()))
    if not todo:
        print(json.dumps({"rewritten": 0}))
        return 1 if refused else 0
    pass_id = SP.new_pass_id()
    base = run_dir / pass_id
    (base / "items").mkdir(parents=True, exist_ok=True)
    for g, r in todo:
        src = store / g[0] / f"{g[1:]}.json"
        shutil.copy2(src, base / "items" / f"{g}.json")          # the item's file, byte for byte, before the first write
    say(f"backup of {len(todo)} items written: {base / 'items'}")
    undo_path = base / "undo.json"
    undo = {"pass_id": pass_id, "by": a.sender, "when": dt.datetime.now(_cfg.tz()).strftime("%a %b %d %H:%M %Z"), "store": str(store), "backup": str(base / "items"),
            "items": [{"item": g, "shown": r["item"], "before": r["before"], "after": r["after"], "history": r.get("history", ""), "dropped": r.get("dropped", []), "sha256_before": r["sha256_before"], "result": None} for g, r in todo]}
    SP.write_atomic(undo_path, undo)      # on disk, whole, before the first write
    say(f"undo file written: {undo_path}")
    entries = {e["item"]: e for e in undo["items"]}
    counts: collections.Counter[str] = collections.Counter()
    for ch in SP.chunks([g for g, _ in todo]):
        st, d = app.call({"op": "until", "items": ch, "pass_id": pass_id})
        if st != 200:
            say(f"a batch was refused as a whole: [{st}] {d.get('error') if isinstance(d, dict) else d}")
            counts["batch refused"] += len(ch)
            continue
        for g, r in zip(ch, d["results"]):
            counts[r["action"]] += 1
            e = entries[g]
            e["result"] = r["action"]
            if r["action"] in ("set", "same"):
                e["before"], e["after"], e["history"], e["dropped"], e["sha256_before"] = r["before"], r["after"], r.get("history", ""), r.get("dropped", []), r["sha256_before"]
        SP.write_atomic(undo_path, undo)      # the real result of each item, kept as it comes
    print(json.dumps({"pass_id": pass_id, "undo": str(undo_path), "backup": str(base / "items"), "results": dict(counts), "refused_in_the_plan": refused,
                      "moved_run_again_for_these": [e["shown"] for e in entries.values() if e.get("result") == "moved"]}, indent=1))
    return 1 if counts.get("refused") or counts.get("batch refused") or refused else 0


def resolve_unrecorded(rec: dict[str, Any]) -> int:
    """An entry whose result is still None is one the run died on, between the server writing its batch and the script recording the answer. The server keeps every batch's real results in its pass record
    (<state>/migration/<pass id>.json): for such an entry the record's action and keys are taken in place of the planned ones, in memory. An entry the record does not name (the run died before the server's
    write, or no record is here) keeps its planned values, which the undo checks against the item as it stands: the item holds `before` (nothing to put back) or `after` (put back). → how many were resolved."""
    pend = [e for e in rec["items"] if e.get("result") is None]
    if not pend:
        return 0
    try:
        from stackshot.core import config as _cfg
        srv = json.loads(_cfg.state("migration", f"{rec.get('pass_id')}.json").read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001  — no record, or one that does not read: the planned values stand
        say(f"{len(pend)} entries have no recorded result and the server's pass record could not be read ({e.__class__.__name__}): their planned values are used")
        return 0
    by_shown = {r.get("item"): r for r in srv.get("items") or [] if isinstance(r, dict)}
    n = 0
    for e in pend:
        r = by_shown.get(e.get("shown"))
        if not r or r.get("action") not in ("set", "same", "moved", "refused"):
            continue
        e["result"] = r["action"]
        if r["action"] in ("set", "same"):
            e["before"], e["after"], e["history"], e["dropped"] = r["before"], r["after"], r.get("history", e.get("history", "")), r.get("dropped", e.get("dropped", []))
        n += 1
    say(f"{len(pend)} entries had no recorded result: {n} taken from the server's pass record, {len(pend) - n} keep their planned values")
    return n


def unfinished(run_dir: Path) -> list[Path]:
    """The undo files of earlier passes in the run directory that have an entry with no recorded result (a run that died): each is still undoable, and a new run does not cover its items."""
    out: list[Path] = []
    for f in sorted(run_dir.glob("*/undo.json")) if run_dir.is_dir() else []:
        try:
            if any(e.get("result") is None for e in json.loads(f.read_text(encoding="utf-8")).get("items", [])):
                out.append(f)
        except (OSError, ValueError):
            continue
    return out


def undo(a: argparse.Namespace, app: Any = None) -> int:
    rec = json.loads(Path(a.undo).expanduser().read_text(encoding="utf-8"))
    resolve_unrecorded(rec)
    todo = [e for e in rec["items"] if e.get("result") not in ("moved", "refused", "same")]
    say(f"{len(todo)} of {len(rec['items'])} entries to put back (pass {rec.get('pass_id')})")
    app = app or MM.LiveApplier(a.sender)
    counts: collections.Counter[str] = collections.Counter()
    kept: list[str] = []
    for ch in SP.chunks(todo):
        st, d = app.call({"op": "ununtil", "items": [{"item": e["item"], "before": e["before"], "after": e["after"], "history": e.get("history", ""), "dropped": e.get("dropped", [])} for e in ch]})
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
    ap = argparse.ArgumentParser(description="Rewrite the waits stored as wake, ask_by and hold as until: a dry run by default; --apply and --undo go through the live server.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="the real pass through the live server (needs --sender)")
    mode.add_argument("--undo", default="", metavar="FILE", help="put back the keys the undo file of a real pass names (needs --sender)")
    ap.add_argument("--store", help="the dry run: a store directory to read (default: [paths] store of the live config)")
    ap.add_argument("--json", help="the dry run: write the rows to this file")
    ap.add_argument("--sender", default="", help="the session that runs the pass (one of [model] migration_senders); needed with --apply and --undo")
    ap.add_argument("--run-dir", default=str(DEFAULT_RUN), help="the real pass: where the backup and the undo file are kept (<run-dir>/<pass id>/)")
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
