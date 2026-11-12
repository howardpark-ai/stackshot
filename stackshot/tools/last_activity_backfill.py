"""tools/last_activity_backfill.py — the one-time data change that fills `metadata.last_activity` for the open items that have no record yet, from the History they already hold (the rules are
stackshot/model/last_activity_pass.py), in three modes shaped like tools/until_migrate.py:

  tools/last_activity_backfill.py                              DRY RUN (the default): the live store copied into a private scratch folder (its git is read from the live store, read only), the whole pass run on the copy twice, and what it
                                                               did read back: one block per open item that would get a record (the time, the kind and the words), the items refused with the reason, then the totals. Writes nothing live; asks no server.
  tools/last_activity_backfill.py --store <dir>                the dry run over another store directory
  tools/last_activity_backfill.py --json out.json              the rows as JSON too
  tools/last_activity_backfill.py --apply --sender <you>       the real pass, through the live server (POST /client/migrate op lastact, this machine's token; [model] migration = true and the sender in
                                                               [model] migration_senders). It asks the server for the plan first (op lastact with dry), then writes, BEFORE the first write, a backup of every item it will touch (the item's file,
                                                               byte for byte: <run-dir>/<pass id>/items/<id>.json) and the undo file <run-dir>/<pass id>/undo.json (fsynced), then writes in batches and records each batch's real result in the undo
                                                               file. The default run directory is ~/.local/share/stackshot-runs/last-activity-run.
  tools/last_activity_backfill.py --undo <undo.json> --sender <you>   puts every item's record back the way the undo file says (op unlastact): an item that still holds what the pass wrote gets its old value back (the key
                                                               goes when it had none); one a later save or event changed is `kept` and left as it is; running it again is a no-op. Read first: the file is checked before anything is sent.

What the pass does per open item with no record: it works out the newest visible activity from the item's History (the store's git versions of its file, replayed through the very function a save goes through;
the merge and event logs of the hub, tied as the live pass ties them) and stores it in `metadata.last_activity`, and writes nothing else: no clock, no mover, no needs, no state, no step, no History line, nobody told. The
file is replaced whole under the item lock, with a sha256 check, as the stamp and until passes do. An item that already has a record is left as it is. A record is never dated after the clock. An item whose History cannot
be read (the refused class: the store outside git, a version missing or torn, a time ahead of the clock by more than an hour) is refused and listed with the reason, and left as it is: the time is not guessed. Running it twice
changes nothing the second time. The plan a person was shown includes each item's time and kind: --apply asks the server for the plan again, and when an item's time (or the set of items) differs from the dry run's --plan, or
from the plan read a moment before, nothing is written. The time written is worked out once more under the item lock, so an event landing in that last moment is in the undo file's `after`. When the hub's logs of pull
request events cannot be read, the dry run prints a warning in its summary and --apply refuses: without them an item is filled from its History alone.

Exit codes. 0: --apply wrote every item it planned and no item is left as it is (or there was nothing to fill and none is left as it is); the dry run finished and its second pass on the copy would change nothing (it exits 0
whether or not it lists items to fill, refused or kept, so read what it prints; the hub's logs not reading is a warning there, not an exit code); --undo put every entry back or found it already as it should be. 1: a failure (the plan
could not be made, a batch was refused as a whole or got no answer, an item could not be written, the plan differs from the one shown (the items, their times or the refused ones), the hub's logs of pull request events or the anchors cannot
be read, another --apply or --undo holds the run directory, the undo file cannot be used or an entry or batch of it was refused, or the dry run could not make its copy or its second pass would still change something).
3: --apply only, not a failure: some items are left as they are and a person has them to look at (refused, kept because their History holds no activity, written by someone else meanwhile, or closed between the plan and the write);
also when there was nothing to fill. The apply prints the refused list before it writes. An item file that git saw deleted and added back is a refused item: git lists the deleting commit for it, no version of the file stands at that commit, so its History cannot be read
(the time is not guessed). Python 3.12 or later; it runs itself in the tests' uv environment when fastmcp is missing."""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import argparse
import collections
import datetime as dt
import json
import os
import shutil
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

from stackshot.tools import compare_pair_reads as CP  # noqa: E402  — the private copy and the live config
from stackshot.tools import migrate_model as MM  # noqa: E402  — LiveApplier, say
from stackshot.tools import stamp_phase as SP  # noqa: E402  — load_dir, write_atomic, chunks, new_pass_id
from stackshot.tools import until_migrate as UM  # noqa: E402  — the run directory's lock, the undo file's reading and its unfinished entries, the pruning, the KST stamp: one copy of them

DEFAULT_RUN = Path.home() / ".local" / "share" / "stackshot-runs" / "last-activity-run"
say = MM.say
EXIT_LEFT_OVER = UM.EXIT_LEFT_OVER      # the pass was applied and some items were left as they are: not a failure, but a person has items to look at
KEY = "last_activity"
CLASS_HISTORY = "unreadable_history"      # last_activity_pass.CLASS_HISTORY (not imported: the pass loads the config, which the dry run must not do before it switches to its copy)


def show(d: Any) -> str:
    return json.dumps(d, ensure_ascii=False, sort_keys=True)


def when(at: Any) -> str:
    """A record's time in the rulebook's form, in the owner's zone: "Thu Nov 12th 15:30 KST"."""
    try:
        t = dt.datetime.fromtimestamp(float(at), UM.KST)
    except (TypeError, ValueError, OverflowError, OSError):
        return str(at)
    return f"{UM.human_date(t.strftime('%Y-%m-%dT%H:%M'))} KST"


def print_row(r: dict[str, Any]) -> None:
    print(f"{r['item']}  [{r['action']}]  " + (f"{r.get('kind')}: {r.get('what')}  at {when(r.get('at'))}" if r.get("at") else r.get("why", "")))
    if r["action"] in ("refused", "kept"):
        print(f"    why: {r.get('why')}")


def refused_lines(rows: list[dict[str, Any]]) -> list[str]:
    """"<item>: <why>" for each item of the refused class (its History cannot be read or is ahead of the clock)."""
    return [f"{r['item']}: {r.get('why')}" for r in rows if r.get("class") == CLASS_HISTORY]


def say_refused(rows: list[dict[str, Any]]) -> None:
    lines = refused_lines(rows)
    say(f"refused class (the History cannot be read, or holds a time ahead of the clock): {len(lines)} items are left as they are, no time is guessed for them" + (f" ({'; '.join(lines)})" if lines else ""))


def signature(rows: list[dict[str, Any]]) -> list[list[Any]]:
    """What a person was shown to decide on: the items that would be filled, each with the time it would get (and its kind), and the refused ones, sorted. A pull request event or a save that arrives meanwhile moves a
    time, and that is a plan that differs from the one shown: it is not applied without --allow-changed-plan. The one time left out is a clamped one (`clamped`: a version a little ahead of the clock reads as
    now, so it moves with the clock by itself). The time written is worked out once more under the item lock (an event landing in that last moment is in the undo file's `after`, which records what was written)."""
    return sorted([r["item"], "would_set" if r.get("action") in ("would_set", "set") else r.get("action"), r.get("class") or "",
                   ("now" if r.get("clamped") else r.get("at")) if r.get("action") in ("would_set", "set") else None,
                   r.get("kind") if r.get("action") in ("would_set", "set") else None] for r in rows if r.get("action") in ("would_set", "set") or r.get("class"))


def dry_run(a: argparse.Namespace) -> int:
    CP.ensure_env(__file__)
    live_cfg = tomllib.loads(CP.LIVE_CONFIG.read_text(encoding="utf-8"))
    live = live_cfg["paths"]
    store = Path(a.store or live["store"]).expanduser().resolve()
    brain = Path(live.get("brain") or "").expanduser() if live.get("brain") else None
    live_state = Path(live.get("state") or "~/.local/state/stackshot").expanduser()
    root: Path | None = None
    fd: int | None = None
    try:
        root = CP.make_scratch(store, brain)
        for log in ("merges.jsonl", "events.jsonl"):      # the hub's two logs are read too (they tie pull request events to items); copied, never written
            if (live_state / log).is_file():
                shutil.copy2(live_state / log, root / "state" / log)
        import fcntl  # noqa: PLC0415
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        fcntl.flock(fd, fcntl.LOCK_SH)
        os.environ["STACKSHOT_CONFIG"] = str(root / "stackshot.toml")
        os.environ["STACKSHOT_AUTH"] = "off"
        os.environ.pop("STACKSHOT_URL", None)
        os.environ["STACKSHOT_FLEET_DIR"] = str(root / "fleet")
        if "stackshot.core.config" in sys.modules:
            raise SystemExit("last_activity_backfill: the config was loaded before the scratch copy was made; refusing to run the pass (it would write the live store)")
        from stackshot.web import server  # noqa: PLC0415
        from stackshot.model import last_activity_pass as LP  # noqa: PLC0415
        if not Path(server._path("g1")).resolve().is_relative_to(root.resolve()):
            raise SystemExit("last_activity_backfill: the server does not resolve items inside the scratch copy; refusing to run the pass")
        server._publish = lambda: None
        d = root / "repo/board-data"
        items = SP.load_dir(d)
        opens = sorted((g for g, it in items.items() if it.get("status") == "open"), key=SP.num)
        now = time.time()
        tied, tie_problem = LP.ties(server, now)
        planned = {g: LP.one(server, g, dry=True, tied=tied, now=now, git_store=store) for g in opens}
        wrote = {g: LP.one(server, g, tied=tied, now=now, git_store=store) for g in opens}
        again = {g: LP.one(server, g, tied=tied, now=now, git_store=store) for g in opens}
        rows = [{**planned[g], "result": wrote[g]["action"], "again": again[g]["action"]} for g in opens]
        print(f"{len(opens)} open items read from {store}; the pass run on a copy of it (the History read from its git)\n")
        if tie_problem:
            print(f"WARNING: the hub's logs of pull request events were not read ({tie_problem}): the records below are worked out from the History alone, and --apply refuses until the logs read\n")
        for r in rows:
            if r["action"] in ("would_set", "refused", "kept"):
                print_row(r)
        by_action = collections.Counter(r["action"] for r in rows)
        by_result = collections.Counter(r["result"] for r in rows)
        print(f"\nopen items: {len(rows)}; with a record already (left as they are): {by_action.get('same', 0)}; to fill: {by_action.get('would_set', 0)}; refused: {by_action.get('refused', 0)}; kept: {by_action.get('kept', 0)}")
        print("result of the pass on the copy: " + ", ".join(f"{k} {n}" for k, n in sorted(by_result.items())) + "; a second pass: " + ", ".join(f"{k} {n}" for k, n in sorted(collections.Counter(r["again"] for r in rows).items())))
        refused = refused_lines(rows)
        print(f"items of the refused class (the History cannot be read, or holds a time ahead of the clock; no time is guessed): {len(refused)}" + (f" {refused}" if refused else ""))
        other = [f"{r['item']}: {r['why']}" for r in rows if r["action"] == "refused" and r.get("class") != CLASS_HISTORY]
        print(f"items refused for another reason (closed since, damaged file): {len(other)}" + (f" {other}" if other else ""))
        kept = [r["item"] for r in rows if r["action"] == "kept"]
        print(f"items kept and listed (no activity in their History): {len(kept)}" + (f" {kept}" if kept else ""))
        kinds = collections.Counter(r.get("kind") for r in rows if r["action"] == "would_set")
        print("kinds of the records to write: " + (", ".join(f"{k} {n}" for k, n in sorted(kinds.items())) or "none"))
        print(f"items the pass would write: {by_result.get('set', 0)} of {len(rows)}")
        print("hub's logs of pull request events: " + (f"WARNING, not read ({tie_problem}); --apply refuses until they read" if tie_problem else "read"))
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
        with UM.run_lock(run_dir):
            return _apply(a, app)
    except UM.RunLocked:
        say(f"another --apply or --undo is running on {run_dir} (it holds the run directory's lock): nothing is done; run this again when it has ended")
        return 1


def _apply(a: argparse.Namespace, app: Any = None) -> int:
    from stackshot.core import config as _cfg
    store = _cfg.path("paths", "store")
    run_dir = Path(a.run_dir).expanduser()
    gone = UM.prune_runs(run_dir, store)
    if gone:
        say(f"removed {len(gone)} pass folders older than {UM.PRUNE_DAYS} days (the newest {UM.PRUNE_KEEP} are always kept): {', '.join(gone)}")
    app = app or MM.LiveApplier(a.sender)

    def candidates() -> list[str]:
        snap = SP.load_dir(store)
        return sorted((g for g, it in snap.items() if it.get("status") == "open"), key=SP.num)      # the server says which of them have a record (`same`)
    cands = candidates()
    say(f"{len(cands)} open items read from {store}")
    for f in UM.unfinished(run_dir):
        say(f"an earlier pass did not finish recording its results ({f}): its entries with no result are not known to have been written. Undoing it alone also reverts items a later --apply wrote, "
            f"so undo the later pass files first, then this one: --undo {f}")

    def make_plan() -> list[dict[str, Any]] | None:
        nonlocal cands
        cands = candidates()                  # read again each time: an item may have changed since the last plan
        out: list[dict[str, Any]] = []
        for ch in SP.chunks(cands):
            st, d = app.call({"op": "lastact", "items": ch, "dry": True})
            if st != 200:
                say(f"the plan could not be made: [{st}] {d.get('error') if isinstance(d, dict) else d}")
                return None
            if d.get("ties_problem"):
                say(f"the plan is refused: the hub's logs of pull request events could not be read ({d['ties_problem']}). Without them an item is filled from its History alone and a newer event would be left out of its record. Nothing is written; run it again when they read")
                return None
            out += d["results"]
        return out
    plan = make_plan()
    if plan is None:
        return 1
    todo = [(g, r) for g, r in zip(cands, plan) if r.get("action") == "would_set"]
    refused = [r["item"] for r in plan if r.get("action") == "refused"]
    listed = [r["item"] for r in plan if r.get("action") == "kept"]
    say(f"{len(todo)} of {len(cands)} would be filled; {sum(1 for r in plan if r.get('action') == 'same')} already have a record; {len(listed)} kept and listed; {len(refused)} refused" + (f" ({', '.join(refused)})" if refused else ""))
    say_refused(plan)
    seen_plan = getattr(a, "plan", "")
    if seen_plan:
        shown = json.loads(Path(seen_plan).expanduser().read_text(encoding="utf-8"))
        if signature(shown) != signature(plan) and not getattr(a, "allow_changed_plan", False):
            say("the items to fill, the times they would get or the refused ones differ from the dry run in --plan; nothing is written. Run the dry run again, or pass --allow-changed-plan to apply this plan")
            return 1
    if todo:
        again = make_plan()           # right before the write: an item may have changed since the plan was made
        if again is None:
            return 1
        if signature(again) != signature(plan) and not getattr(a, "allow_changed_plan", False):
            say("the items to fill, the times they would get or the refused ones changed while the plan was being read; nothing is written. Run it again, or pass --allow-changed-plan")
            return 1
        plan = again
        todo = [(g, r) for g, r in zip(cands, plan) if r.get("action") == "would_set"]
        refused = [r["item"] for r in plan if r.get("action") == "refused"]
        listed = [r["item"] for r in plan if r.get("action") == "kept"]
    left_over = sorted({*refused, *listed})
    if not todo:
        print(json.dumps({"filled": 0, "left_over": left_over}))
        if left_over:
            say(f"nothing to fill; {len(left_over)} items are left as they are (refused or kept): exit {EXIT_LEFT_OVER}")
        return EXIT_LEFT_OVER if left_over else 0
    pass_id = SP.new_pass_id()
    base = run_dir / pass_id
    (base / "items").mkdir(parents=True, exist_ok=True)
    for g, r in todo:
        src = store / g[0] / f"{g[1:]}.json"
        shutil.copy2(src, base / "items" / f"{g}.json")          # the item's file, byte for byte, before the first write
    say(f"backup of {len(todo)} items written: {base / 'items'}")
    undo_path = base / "undo.json"
    undo = {"pass_id": pass_id, "by": a.sender, "when": UM.kst_stamp(), "store": str(store), "backup": str(base / "items"), "kind": "last_activity",
            "items": [{"item": g, "shown": r["item"], "before": r["before"], "after": r["after"], "history": "", "dropped": [], "sha256_before": r["sha256_before"], "result": None} for g, r in todo]}
    SP.write_atomic(undo_path, undo)      # on disk, whole, before the first write
    say(f"undo file written: {undo_path}")
    entries = {e["item"]: e for e in undo["items"]}
    counts: collections.Counter[str] = collections.Counter()
    closed_now: list[str] = []
    for ch in SP.chunks([g for g, _ in todo]):
        st, d = app.call({"op": "lastact", "items": ch, "pass_id": pass_id})
        if st != 200:
            why = d.get('error') if isinstance(d, dict) else d
            if 400 <= st < 500:
                say(f"a batch was refused as a whole: [{st}] {why}")
                counts["batch refused"] += len(ch)
                for g in ch:
                    entries[g]["result"] = "batch refused"            # a 4xx answer is the route's refusal of the whole batch before any write: the entry is final
            else:
                say(f"a batch got no answer that says what it wrote: [{st}] {why}")      # 0 or a 5xx can come after the server wrote some of it: the entries keep no result, so the file is named unfinished and an undo reads the server's pass record
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
                e["before"], e["after"], e["sha256_before"] = r["before"], r["after"], r["sha256_before"]
        SP.write_atomic(undo_path, undo)      # the real result of each item, kept as it comes
    print(json.dumps({"pass_id": pass_id, "undo": str(undo_path), "backup": str(base / "items"), "results": dict(counts), "refused_in_the_plan": refused, "listed_in_the_plan": listed,
                      "moved_run_again_for_these": [e["shown"] for e in entries.values() if e.get("result") == "moved"], "closed_since_the_plan": closed_now}, indent=1))
    moved = [e["shown"] for e in entries.values() if e.get("result") == "moved"]
    if counts.get("refused") or counts.get("batch refused") or counts.get("batch unanswered"):
        say("the pass did not get every item it planned written, or never heard how a batch went (the answers are above; the items of a batch with no answer may have been written, and --undo reads the server's pass record for them): a failure, exit 1")
        return 1
    left_over = sorted({*refused, *listed, *moved, *closed_now})
    if left_over:
        say(f"applied with items left over: {counts.get('set', 0)} items filled, {len(left_over)} left as they are (refused, kept, closed since the plan, or written by someone else meanwhile): exit {EXIT_LEFT_OVER}, not a failure")
        return EXIT_LEFT_OVER
    return 0


def undo(a: argparse.Namespace, app: Any = None) -> int:
    """Put the records of an undo file back. The file is read first (a path that is none, or a file that is no undo file, is a clean error and creates nothing); the run directory's lock is taken only when the
    file lives where a pass puts it, <run-dir>/<pass id>/undo.json, so a typo never makes a directory or a `.lock` of its own."""
    undo_path = Path(a.undo).expanduser()
    try:
        UM.read_undo(undo_path)
    except (OSError, ValueError, RecursionError) as e:
        say(f"cannot use {undo_path} as an undo file ({e.__class__.__name__}: {str(e)[:120]}): nothing is done")
        return 1
    real = undo_path.resolve()
    if real.name != "undo.json" or not UM.PASS_DIR_RX.fullmatch(real.parent.name):
        say(f"{undo_path} is not at <run-dir>/<pass id>/undo.json, so no run directory's lock is taken: make sure no other --apply or --undo is running")
        return _undo(a, app)
    run_dir = real.parent.parent
    try:
        with UM.run_lock(run_dir):
            return _undo(a, app)
    except UM.RunLocked:
        say(f"another --apply or --undo is running on {run_dir} (it holds the run directory's lock): nothing is done; run this again when it has ended")
        return 1


def _undo(a: argparse.Namespace, app: Any = None) -> int:
    rec = UM.read_undo(Path(a.undo).expanduser())
    if rec.get("undone"):
        say(f"pass {rec.get('pass_id')} was already put back ({rec['undone']}): nothing is done")
        return 0
    UM.resolve_unrecorded(rec)
    if any(e.get("result") is None for e in rec["items"]):
        say("some entries have no recorded result: they are put back from their planned values, which also reverts an item a LATER pass wrote; undo the later pass files first, then this one")
    todo = [e for e in rec["items"] if e.get("result") not in ("moved", "refused", "same", "batch refused")]
    say(f"{len(todo)} of {len(rec['items'])} entries to put back (pass {rec.get('pass_id')})")
    app = app or MM.LiveApplier(a.sender)
    counts: collections.Counter[str] = collections.Counter()
    kept: list[str] = []
    closed: list[str] = []
    for ch in SP.chunks(todo):
        st, d = app.call({"op": "unlastact", "items": [{"item": e["item"], "before": e["before"], "after": e["after"], "history": "", "dropped": []} for e in ch]})
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
        rec["undone"] = dt.datetime.now(UM.KST).strftime("%Y%m%d-%H%M%S KST")        # recorded in the pass file (Asia/Seoul, the zone named), so a later --apply stops naming it as unfinished
        SP.write_atomic(Path(a.undo).expanduser(), rec)
    else:
        say(f"{unfinished_n} items were not put back (refused, written by someone else meanwhile, or a batch refused): the undo file is not marked undone; run --undo again")
    print(json.dumps({"results": dict(counts), "kept_because_a_later_save_changed_them": kept, "kept_because_closed_since_the_pass": closed}, indent=1))
    return 1 if counts.get("refused") or counts.get("batch refused") else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Fill metadata.last_activity for the open items that have none, from their History: a dry run by default; --apply and --undo go through the live server.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="the real pass through the live server (needs --sender)")
    mode.add_argument("--undo", default="", metavar="FILE", help="put back the records the undo file of a real pass names (needs --sender)")
    ap.add_argument("--store", help="the dry run: a store directory to read (default: [paths] store of the live config)")
    ap.add_argument("--json", help="the dry run: write the rows to this file")
    ap.add_argument("--plan", default="", metavar="FILE", help="--apply: the dry run's --json file; the items to fill, the times they would get and the refused ones must be the ones it showed")
    ap.add_argument("--allow-changed-plan", action="store_true", help="--apply: apply even when the items to fill, their times or the refused ones differ from the dry run or from the plan read a moment before")
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
