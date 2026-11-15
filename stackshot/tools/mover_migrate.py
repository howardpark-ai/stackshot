"""tools/mover_migrate.py — the one-time data change that stores the picker of a waiting item as `mover` (the rules are stackshot/waits/mover_pass.py), in three modes:

  tools/mover_migrate.py                              DRY RUN (the default): the live store copied into a private scratch folder (with the fleet view beside it, so a `then` is judged live as the server judges it),
                                                      the whole pass run on the copy twice, and what it did read back: one block per item with the picker keys it stores now and the ones it would store, the History
                                                      line, then the totals. Writes nothing live; asks no server.
  tools/mover_migrate.py --store <dir>                the dry run over another store directory
  tools/mover_migrate.py --json out.json              the rows as JSON too
  tools/mover_migrate.py --apply --sender <you>       the real pass, through the live server (POST /client/migrate op mover, this machine's token; [model] migration = true and the sender in
                                                      [model] migration_senders). It asks the server for the plan first (op mover with dry), then writes, BEFORE the first write, a backup of every item it
                                                      will touch (the item's file, byte for byte: <run-dir>/<pass id>/items/<id>.json) and the undo file <run-dir>/<pass id>/undo.json (fsynced), then moves the
                                                      pickers in batches and records each batch's real result in the undo file. The default run directory is ~/.local/share/stackshot-runs/mover-run.
  tools/mover_migrate.py --undo <undo.json> --sender <you>   puts every item's picker keys back the way the undo file says (op unmover): an item that still holds what the pass left gets its old keys back;
                                                      one a later save changed is `kept` and left as it is; running it again is a no-op.

What the pass does per open item: it stores the picker of a waiting item as `mover` and drops the old key `post_wake_mover`, drops a `then` nothing reads, and turns a `then` that stood in for a picker into the picker;
the same for the snapshot of a turned wait (metadata.watch.was); one History line says so. The server refuses (and leaves as it is) an item whose phase, kind of wait, picker, `then` standing, needs, watched status or
end date would read differently. No item is closed or woken, nobody is told, no clock moves, nothing but the picker keys, the snapshot and the History line changes (the file is replaced whole under the item lock, with a
sha256 check, as the stamp, retire and until passes do). Running it twice changes nothing the second time. Nothing is removed from the code: the old key is still read.

Live run, in order: set `[model] migration = true` in the config for the run window only; run the dry run and read it; --apply --sender <you>; read the result back (the totals, then the dry run again: it lists nothing to
write); set `[model] migration = false`; keep the undo file.

Exit codes: 0 done (apply) or nothing to change (dry run) · 1 a failure (the plan could not be made, a batch was refused as a whole or got no answer, an item could not be written, the plan differs from the one shown, another
--apply or --undo holds the run directory, or the dry run's second pass would still change something) · 3 the pass was applied and some items were left as they are (refused, listed, or closed between the plan and the write):
not a failure, a person has items to look at. The apply prints the listed items before it writes, plans again right before the first write, and refuses to write when the lists changed since (or differ from the dry run's
--json given with --plan) unless --allow-changed-plan. Python 3.12 or later; it runs itself in the tests' uv environment when fastmcp is missing."""
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

from stackshot.tools import compare_pair_reads as CP  # noqa: E402  — the private copy and the live config
from stackshot.tools import migrate_model as MM  # noqa: E402  — LiveApplier, say
from stackshot.tools import stamp_phase as SP  # noqa: E402  — load_dir, write_atomic, chunks, new_pass_id
from stackshot.tools import until_migrate as UM  # noqa: E402  — the run folder's lock, pruning and undo-file helpers are the until pass's, shared
# stackshot.waits.mover_pass is imported inside dry_run, after the scratch config is set: it loads stackshot.core.config, which reads the config file once at import, so a top-level import would
# leave the server (and the pass) on the LIVE store paths.

DEFAULT_RUN = Path.home() / ".local" / "share" / "stackshot-runs" / "mover-run"
say = MM.say
show = UM.show
EXIT_LEFT_OVER = UM.EXIT_LEFT_OVER
RunLocked = UM.RunLocked
run_lock = UM.run_lock
PASS_DIR_RX = UM.PASS_DIR_RX
PRUNE_DAYS, PRUNE_KEEP = UM.PRUNE_DAYS, UM.PRUNE_KEEP
read_undo, resolve_unrecorded, unfinished, prune_runs = UM.read_undo, UM.resolve_unrecorded, UM.unfinished, UM.prune_runs
KST = UM.KST
LEGACY = "post_wake_mover"          # the stored key (model.LEGACY_PICKER_KEY; not imported: the model loads the config, which the dry run must not do before it switches to its copy)


def signature(rows: list[dict[str, Any]]) -> list[list[Any]]:
    """What a person was shown to decide on: the listed rows (their notes), the items refused and the stand-ins, sorted. A plan that differs from the one shown is not applied without --allow-changed-plan."""
    return sorted([r["item"], r.get("action") in ("refused", "kept"), r.get("standin") or "", list(r.get("notes") or [])] for r in rows
                  if r.get("notes") or r.get("standin") or r.get("action") == "refused")


def say_listed(rows: list[dict[str, Any]]) -> None:
    listed = [r for r in rows if r.get("notes")]
    stand = [r for r in rows if r.get("standin") and r.get("action") in ("would_set", "set")]
    say(f"listed: {len(listed)} items carry a pair of names that differ, a word none, an old key on an item that waits on nothing stored or on an outside party's date-only wait" + (f" ({'; '.join(r['item'] + ': ' + ' / '.join(r['notes']) for r in listed)})" if listed else ""))
    say(f"stand-ins: {len(stand)} items get the picker a stored `then` stood in for" + (f" ({', '.join(r['item'] + ' -> ' + r['standin'] for r in stand)})" if stand else ""))


def print_row(r: dict[str, Any]) -> None:
    keys = [k for k, v in (r.get("after") or {}).items() if v != (r.get("before") or {}).get(k)]      # the keys the pass changes (an entry carries all the picker keys)
    print(f"{r['item']}  {r.get('form') or '-'}  ->  {r.get('new') or '-'}   [{r['action']}]")
    print(f"    old: {show({k: (r.get('before') or {}).get(k) for k in keys})}")
    print(f"    new: {show({k: (r.get('after') or {}).get(k) for k in keys})}")
    if r.get("history"):
        print(f"    History line: stackshot: {r['history']}")
    for n in r.get("notes") or []:
        print(f"    listed: {n}")
    if r.get("standin") and r["action"] in ("would_set", "set"):
        print(f"    stand-in: the `then` {r['standin']} becomes the picker; a wait on a date alone turns to it at its date instead of ending on the date")
    if r["action"] in ("refused", "kept"):
        print(f"    why: {r.get('why')}")


def dry_run(a: argparse.Namespace) -> int:
    CP.ensure_env(__file__)
    live = tomllib.loads(CP.LIVE_CONFIG.read_text(encoding="utf-8"))["paths"]
    store = Path(a.store or live["store"]).expanduser().resolve()
    brain = Path(live.get("brain") or "").expanduser() if live.get("brain") else None
    live_fleet = Path(os.environ.get("STACKSHOT_FLEET_DIR") or Path(live.get("state") or "~/.local/state/stackshot").expanduser() / "clients" / "fleet")
    root: Path | None = None
    fd: int | None = None
    try:
        root = CP.make_scratch(store, brain)
        if live_fleet.is_dir():                      # the fleet view is read-only data the server's own judgement of a live session needs; the copy keeps the dry run off the live one
            shutil.copytree(live_fleet, root / "fleet", dirs_exist_ok=True, ignore=shutil.ignore_patterns("*.tmp", ".*"))
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        fcntl.flock(fd, fcntl.LOCK_SH)
        os.environ["STACKSHOT_CONFIG"] = str(root / "stackshot.toml")
        os.environ["STACKSHOT_AUTH"] = "off"
        os.environ.pop("STACKSHOT_URL", None)
        os.environ["STACKSHOT_FLEET_DIR"] = str(root / "fleet")
        if "stackshot.core.config" in sys.modules:
            raise SystemExit("mover_migrate: the config was loaded before the scratch copy was made; refusing to run the pass (it would write the live store)")
        from stackshot.web import server  # noqa: PLC0415
        from stackshot.web import publish as _web_publish  # noqa: PLC0415
        from stackshot.service import store as _service_store  # noqa: PLC0415
        from stackshot.service import answer_handover as _answer_handover  # noqa: PLC0415
        from stackshot.waits import mover_pass as MP  # noqa: PLC0415
        from stackshot.service import retire_passes as _retire_passes  # noqa: PLC0415
        from stackshot.service import stamp as _stamp  # noqa: PLC0415
        from stackshot.web import wiring as _wiring  # noqa: PLC0415
        if not Path(_service_store._path("g1")).resolve().is_relative_to(root.resolve()):
            raise SystemExit("mover_migrate: the server does not resolve items inside the scratch copy; refusing to run the pass")
        _web_publish._publish = lambda: None
        d = root / "repo/board-data"
        items = SP.load_dir(d)
        opens = sorted((g for g, it in items.items() if it.get("status") == "open"), key=SP.num)
        host = _stamp.PassHost(server, _stamp, _retire_passes, _wiring.PASS_NAMES)
        live_then = _answer_handover._then_live
        planned = {g: MP.one(host, g, live_then, dry=True) for g in opens}
        wrote = {g: MP.one(host, g, live_then) for g in opens}
        again = {g: MP.one(host, g, live_then) for g in opens}
        rows = [{**planned[g], "result": wrote[g]["action"], "again": again[g]["action"]} for g in opens]
        todo = [r for r in rows if r["action"] in ("would_set", "refused", "kept")]
        print(f"{len(opens)} open items read from {store}; the pass run on a copy of it\n")
        for r in todo:
            print_row(r)
        by_result = collections.Counter(r["result"] for r in rows)
        forms = collections.Counter(r["form"] for r in rows if r["action"] == "would_set")
        kept = collections.Counter(r["why"] for r in rows if r["action"] == "same" and r["why"])
        print("\nitems to change by their stored form: " + (", ".join(f"{k} {n}" for k, n in sorted(forms.items())) or "none"))
        print("left as they are: " + (", ".join(f"{n} x {k}" for k, n in sorted(kept.items())) or "none"))
        print("result of the pass on the copy: " + ", ".join(f"{k} {n}" for k, n in sorted(by_result.items())) + "; a second pass: " + ", ".join(f"{k} {n}" for k, n in sorted(collections.Counter(r["again"] for r in rows).items())))
        refused = [r["item"] for r in rows if r["action"] == "refused"]
        listed = [r["item"] for r in rows if r["action"] == "kept"]
        print(f"items the pass refuses (they would read differently with the picker stored as mover): {len(refused)}" + (f" {refused}" if refused else ""))
        print(f"items kept and listed for a person: {len(listed)}" + (f" {listed}" if listed else ""))
        say_listed(rows)
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
    """The real pass, under the run directory's lock. `app` (tests only) answers app.call(body) → (status, answer) in place of the live server."""
    run_dir = Path(a.run_dir).expanduser()
    try:
        with run_lock(run_dir):
            return _apply(a, app)
    except RunLocked:
        say(f"another --apply or --undo is running on {run_dir} (it holds the run directory's lock): nothing is done; run this again when it has ended")
        return 1


def _carries(it: dict[str, Any]) -> bool:
    """Does an item store a key the pass may move: the old picker key, a `then`, or a snapshot of a turned wait."""
    meta = it.get("metadata") or {}
    w = meta.get("watch")
    return LEGACY in meta or "then" in meta or (isinstance(w, dict) and isinstance(w.get("was"), dict))


def _apply(a: argparse.Namespace, app: Any = None) -> int:
    from stackshot.core import config as _cfg
    store = _cfg.path("paths", "store")
    run_dir = Path(a.run_dir).expanduser()
    gone = prune_runs(run_dir, store)
    if gone:
        say(f"removed {len(gone)} pass folders older than {PRUNE_DAYS} days (the newest {PRUNE_KEEP} are always kept): {', '.join(gone)}")
    app = app or MM.LiveApplier(a.sender)
    def candidates() -> list[str]:
        snap = SP.load_dir(store)
        return sorted((g for g, it in snap.items() if it.get("status") == "open" and _carries(it)), key=SP.num)
    cands = candidates()
    say(f"{len(cands)} open items store an old picker key, a `then` or a snapshot of a turned wait, read from {store}")
    for f in unfinished(run_dir):
        say(f"an earlier pass did not finish recording its results ({f}): its entries with no result are not known to have been written. Undoing it alone also reverts items a later --apply wrote, "
            f"so undo the later pass files first, then this one: --undo {f}")
    def make_plan() -> list[dict[str, Any]] | None:
        nonlocal cands
        cands = candidates()                  # read again each time: an item may have changed since the last plan
        out: list[dict[str, Any]] = []
        for ch in SP.chunks(cands):
            st, d = app.call({"op": "mover", "items": ch, "dry": True})
            if st != 200:
                say(f"the plan could not be made: [{st}] {d.get('error') if isinstance(d, dict) else d}")
                return None
            out += d["results"]
        return out
    plan = make_plan()
    if plan is None:
        return 1
    todo = [(g, r) for g, r in zip(cands, plan) if r.get("action") == "would_set"]
    refused = [r["item"] for r in plan if r.get("action") == "refused"]
    listed = [r["item"] for r in plan if r.get("action") == "kept"]
    say(f"{len(todo)} of {len(cands)} would be changed; {sum(1 for r in plan if r.get('action') == 'same')} left as they are; {len(listed)} kept and listed; {len(refused)} refused" + (f" ({', '.join(refused)})" if refused else ""))
    say_listed(plan)
    seen_plan = getattr(a, "plan", "")
    if seen_plan:
        shown = json.loads(Path(seen_plan).expanduser().read_text(encoding="utf-8"))
        if signature(shown) != signature(plan) and not getattr(a, "allow_changed_plan", False):
            say("the listed items differ from the dry run in --plan; nothing is written. Run the dry run again, or pass --allow-changed-plan to apply this plan")
            return 1
    if todo:
        again = make_plan()           # right before the write: an item may have changed since the plan was made
        if again is None:
            return 1
        if signature(again) != signature(plan) and not getattr(a, "allow_changed_plan", False):
            say("the listed items changed while the plan was being read; nothing is written. Run it again, or pass --allow-changed-plan")
            return 1
        plan = again
        todo = [(g, r) for g, r in zip(cands, plan) if r.get("action") == "would_set"]
        refused = [r["item"] for r in plan if r.get("action") == "refused"]
        listed = [r["item"] for r in plan if r.get("action") == "kept"]
    left_over = sorted({*refused, *listed})
    if not todo:
        print(json.dumps({"changed": 0, "left_over": left_over}))
        if left_over:
            say(f"nothing to change; {len(left_over)} items are left as they are (refused or listed): exit {EXIT_LEFT_OVER}")
        return EXIT_LEFT_OVER if left_over else 0
    pass_id = SP.new_pass_id()
    base = run_dir / pass_id
    (base / "items").mkdir(parents=True, exist_ok=True)
    for g, r in todo:
        src = store / g[0] / f"{g[1:]}.json"
        shutil.copy2(src, base / "items" / f"{g}.json")          # the item's file, byte for byte, before the first write
    say(f"backup of {len(todo)} items written: {base / 'items'}")
    undo_path = base / "undo.json"
    undo = {"pass_id": pass_id, "by": a.sender, "when": UM.kst_stamp(), "store": str(store), "backup": str(base / "items"),
            "items": [{"item": g, "shown": r["item"], "before": r["before"], "after": r["after"], "history": r.get("history", ""), "dropped": r.get("dropped", []), "sha256_before": r["sha256_before"], "result": None} for g, r in todo]}
    SP.write_atomic(undo_path, undo)      # on disk, whole, before the first write
    say(f"undo file written: {undo_path}")
    entries = {e["item"]: e for e in undo["items"]}
    counts: collections.Counter[str] = collections.Counter()
    closed_now: list[str] = []
    for ch in SP.chunks([g for g, _ in todo]):
        st, d = app.call({"op": "mover", "items": ch, "pass_id": pass_id})
        if st != 200:
            why = d.get('error') if isinstance(d, dict) else d
            if 400 <= st < 500:
                say(f"a batch was refused as a whole: [{st}] {why}")
                counts["batch refused"] += len(ch)
                for g in ch:
                    entries[g]["result"] = "batch refused"            # a 4xx answer is the route's refusal of the whole batch before any write: the entry is final, not an unrecorded one
            else:
                say(f"a batch got no answer that says what it wrote: [{st}] {why}")      # 0 (no answer, a timeout) or a 5xx can come after the server wrote some of it: the entries keep no result, so the file is named unfinished
                counts["batch unanswered"] += len(ch)
            SP.write_atomic(undo_path, undo)
            continue
        for g, r in zip(ch, d["results"]):
            e = entries[g]
            if r["action"] == "refused" and str(r.get("why") or "").startswith("closed"):
                counts["closed since the plan"] += 1                # a session closed it between the plan and the write: the item is done, not a failure of the pass
                e["result"] = "refused"
                closed_now.append(e["shown"])
                continue
            counts[r["action"]] += 1
            e["result"] = r["action"]
            if r["action"] in ("set", "same"):
                e["before"], e["after"], e["history"], e["dropped"], e["sha256_before"] = r["before"], r["after"], r.get("history", ""), r.get("dropped", []), r["sha256_before"]
        SP.write_atomic(undo_path, undo)      # the real result of each item, kept as it comes
    print(json.dumps({"pass_id": pass_id, "undo": str(undo_path), "backup": str(base / "items"), "results": dict(counts), "refused_in_the_plan": refused, "listed_in_the_plan": listed,
                      "moved_run_again_for_these": [e["shown"] for e in entries.values() if e.get("result") == "moved"], "left_by_the_write": [e["shown"] for e in entries.values() if e.get("result") == "kept"],
                      "closed_since_the_plan": closed_now}, indent=1))
    moved = [e["shown"] for e in entries.values() if e.get("result") == "moved"]
    skipped = [e["shown"] for e in entries.values() if e.get("result") == "kept"]
    if counts.get("refused") or counts.get("batch refused") or counts.get("batch unanswered"):
        say("the pass could not write every item it planned (the answers are above): a failure, exit 1")
        return 1
    left_over = sorted({*refused, *listed, *moved, *skipped, *closed_now})
    if left_over:
        say(f"applied with items left over: {counts.get('set', 0)} items changed, {len(left_over)} left as they are (refused, listed, closed since the plan, or written by someone else meanwhile): exit {EXIT_LEFT_OVER}, not a failure"
            + (f"; left by the write itself: {skipped}" if skipped else "") + (f"; closed since the plan: {closed_now}" if closed_now else ""))
        return EXIT_LEFT_OVER
    return 0


def undo(a: argparse.Namespace, app: Any = None) -> int:
    """Put the keys of an undo file back. The file is read first (a path that is none, or a file that is no undo file, is a clean error and creates nothing); the run directory's lock is taken only when the
    file lives where a pass puts it, <run-dir>/<pass id>/undo.json, so a typo never makes a directory or a `.lock` of its own."""
    undo_path = Path(a.undo).expanduser()
    try:
        read_undo(undo_path)
    except (OSError, ValueError, RecursionError) as e:
        say(f"cannot use {undo_path} as an undo file ({e.__class__.__name__}: {str(e)[:120]}): nothing is done")
        return 1
    real = undo_path.resolve()
    if real.name != "undo.json" or not PASS_DIR_RX.fullmatch(real.parent.name):
        say(f"{undo_path} is not at <run-dir>/<pass id>/undo.json, so no run directory's lock is taken: make sure no other --apply or --undo is running")
        return _undo(a, app)
    run_dir = real.parent.parent
    try:
        with run_lock(run_dir):
            return _undo(a, app)
    except RunLocked:
        say(f"another --apply or --undo is running on {run_dir} (it holds the run directory's lock): nothing is done; run this again when it has ended")
        return 1


def _undo(a: argparse.Namespace, app: Any = None) -> int:
    rec = read_undo(Path(a.undo).expanduser())
    resolve_unrecorded(rec)
    if any(e.get("result") is None for e in rec["items"]):
        say("some entries have no recorded result: they are put back from their planned values, which also reverts an item a LATER pass wrote; undo the later pass files first, then this one")
    todo = [e for e in rec["items"] if e.get("result") not in ("moved", "refused", "same", "batch refused")]
    say(f"{len(todo)} of {len(rec['items'])} entries to put back (pass {rec.get('pass_id')})")
    app = app or MM.LiveApplier(a.sender)
    counts: collections.Counter[str] = collections.Counter()
    kept: list[str] = []
    closed: list[str] = []
    for ch in SP.chunks(todo):
        st, d = app.call({"op": "unmover", "items": [{"item": e["item"], "before": e["before"], "after": e["after"], "history": e.get("history", ""), "dropped": e.get("dropped", [])} for e in ch]})
        if st != 200:
            say(f"a batch was refused as a whole: [{st}] {d.get('error') if isinstance(d, dict) else d}")
            counts["batch refused"] += len(ch)
            continue
        for e, r in zip(ch, d["results"]):
            counts[r["action"]] += 1
            if r["action"] == "kept":
                (closed if str(r.get("why") or "").startswith("it was closed") else kept).append(e.get("shown") or e["item"])
    unfinished_n = sum(counts.get(k, 0) for k in ("refused", "batch refused", "moved"))      # an item not put back and not final: a later run still has work, so the file is not marked undone
    if not unfinished_n:
        rec["undone"] = dt.datetime.now(KST).strftime("%Y%m%d-%H%M%S KST")        # recorded in the pass file, so a later --apply stops naming it as unfinished
        SP.write_atomic(Path(a.undo).expanduser(), rec)
    else:
        say(f"{unfinished_n} items were not put back (refused, written by someone else meanwhile, or a batch refused): the undo file is not marked undone; run --undo again")
    print(json.dumps({"results": dict(counts), "kept_because_a_later_save_changed_them": kept, "kept_because_closed_since_the_pass": closed}, indent=1))
    return 1 if counts.get("refused") or counts.get("batch refused") else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Store the picker of a waiting item as mover (and drop the old key post_wake_mover): a dry run by default; --apply and --undo go through the live server.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="the real pass through the live server (needs --sender)")
    mode.add_argument("--undo", default="", metavar="FILE", help="put back the keys the undo file of a real pass names (needs --sender)")
    ap.add_argument("--store", help="the dry run: a store directory to read (default: [paths] store of the live config)")
    ap.add_argument("--json", help="the dry run: write the rows to this file")
    ap.add_argument("--plan", default="", metavar="FILE", help="--apply: the dry run's --json file; the listed items must be the ones it showed")
    ap.add_argument("--allow-changed-plan", action="store_true", help="--apply: apply even when the listed items differ from the dry run or from the plan read a moment before")
    ap.add_argument("--sender", default="", help="the session that runs the pass (one of [model] migration_senders); needed with --apply and --undo")
    ap.add_argument("--run-dir", default=str(DEFAULT_RUN), help="the real pass: where the backup and the undo file are kept (<run-dir>/<pass id>/)")
    a = ap.parse_args(argv)
    if (a.apply or a.undo) and not a.sender.strip():
        ap.error("--apply and --undo need --sender <the session that runs the pass>")
    if (a.apply or a.undo) and a.store:
        ap.error("--store is for the dry run only: --apply and --undo work on the live server's store, so the option would be ignored; leave it out")
    if a.apply:
        return apply(a)
    if a.undo:
        return undo(a)
    return dry_run(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
