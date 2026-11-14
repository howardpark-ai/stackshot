"""tools/retire_fields_report.py — the data change that takes the stored state words and their carry fields out of the open items' storage (retire_fields.py), in three modes:

  tools/retire_fields_report.py                           DRY RUN (the default): the live store copied into a private scratch folder, the whole pass run on the copy, and what it did read back. Writes nothing live.
  tools/retire_fields_report.py --store <dir>             the dry run over another store directory
  tools/retire_fields_report.py --json out.json           the rows as JSON too
  tools/retire_fields_report.py --apply --sender <you>    the real pass, through the live server (POST /client/migrate op retire, this machine's token; [model] migration = true and the sender in
                                                          [model] migration_senders). Run by a person on deploy. It asks the server for the plan first (op retire with dry), writes the undo file
                                                          <run-dir>/<pass id>/undo.json (fsynced) BEFORE the first write, then retires in batches and records each batch's real result in the undo file.
  tools/retire_fields_report.py --undo <file> --sender <you>   puts every item back the way the undo file says (op unretire): an item that still holds what the pass left gets its old keys back; one a later
                                                          save changed is `kept` and left as it is; running it again is a no-op.

What the pass does per open item (retire_fields.py has the rules): the stored state word is dropped; party, chase and end are copied into wait_event, ask_by and wake when those are empty, then dropped; a
verifying item's proof becomes the text of a wait_basis on its wake; on an item that stores a wait_kind (the watchers read its party and a chase day) the party stays, and so does a chase with no ask_by; supplies becomes a "- Needs: …" bullet at the end of the description (held when the description would pass its limits); a verifying item's end day becomes a wake at 23:59 of that day; a party the wait_event does not name and a
chase day the ask_by does not start with stay; expected_by and expected_reason (retired already) are dropped. Agent work in hand (a stored state doing with a session as mover: its wait is read from the stored state alone), a your-step item
(its step stands on the stored state), a step with no home and a proof outside a verifying item are HELD: left as they are and listed. wait_kind stays. The server refuses (and leaves as it is) an item whose phase, kind of
wait, mover or watched status would read differently, so the pass can never change what the board shows.

The dry run prints one row per item that has something to retire (the fields it stores, the moves, whether it reads the same), the totals by field, the supplies lines the pass would add to descriptions, the items held back and
the reads that would change; it exits 1 when any would, or when a new description would break a limit (a Needs line that would is held, never written). Python 3.12 or later; it runs itself in the tests' uv environment when fastmcp is missing."""
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
import time
import tomllib
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[2]
from stackshot.tools import compare_pair_reads as CP  # noqa: E402  — the private copy and the live config
from stackshot.tools import migrate_model as MM  # noqa: E402  — LiveApplier, say
from stackshot.model import retire_fields as RF  # noqa: E402
from stackshot.tools import stamp_phase as SP  # noqa: E402  — load_dir, frozen, fields_only, write_atomic, chunks

DEFAULT_RUN = Path.home() / ".local" / "share" / "stackshot-runs" / "retire-run"
FIELDS = ("state", *RF.MOVES, "proof", "supplies", "step", *RF.DROPPED, "wait_kind")
say = MM.say


def reading(server: Any, it: dict[str, Any], gid: str, now: float) -> dict[str, Any]:
    """What the fields give for the item at the clock now (server._retire_reading: phase, kind of wait, mover, watched) and, apart, the list and the old
    state word it reads as."""
    probe = {**it, "gid": gid}
    ao = lambda i_: server._item_read._after_open(i_.get("metadata") or {})      # noqa: E731
    with SP.frozen(now), SP.fields_only(server):
        r = server._retire_reading(gid, it)
        mod = server._item_read._model_of(probe)
        return {**r, "list": server._item_list(probe), "word": mod.today}


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
        from stackshot.web import server  # noqa: PLC0415
        from stackshot.web import publish as _web_publish  # noqa: PLC0415
        from stackshot.core import config as _cfg  # noqa: PLC0415
        from stackshot.github import ghsync as _gh  # noqa: PLC0415
        _web_publish._publish = lambda: None
        d = root / "repo/board-data"
        now = time.time()
        items = SP.load_dir(d)
        opens = sorted((g for g, it in items.items() if it.get("status") == "open"), key=SP.num)
        max_lines = int(_cfg.CFG["description"].get("max_lines", 8))
        before = {g: reading(server, items[g], g, now) for g in opens}
        planned = {g: server._retire_one(g, dry=True) for g in opens}
        wrote = {g: server._retire_one(g) for g in opens}
        again = {g: server._retire_one(g) for g in opens}
        after_items = SP.load_dir(d)
        rows: list[dict[str, Any]] = []
        stores: collections.Counter[str] = collections.Counter()
        for g in opens:
            it, meta = items[g], items[g]["metadata"]
            for f in FIELDS:
                if meta.get(f) not in (None, ""):
                    stores[f] += 1
            aft = reading(server, after_items[g], g, now)
            why = server.retire_same(before[g], aft)
            same = not why and before[g]["list"] == aft["list"]
            if before[g]["list"] != aft["list"]:
                why = (why + "; " if why else "") + f"list {before[g]['list']} -> {aft['list']}"
            r, w = planned[g], wrote[g]
            rows.append({"item": _gh.shown(g), "state": meta.get("state"), "plan": r, "result": w["action"], "again": again[g]["action"], "before": before[g], "after": aft, "same": same, "why": why, "word_changes": before[g]["word"] != aft["word"],
                         "description_lines": (len(str(after_items[g].get("description") or "").strip().splitlines()), len(str(it.get("description") or "").strip().splitlines()))})
        todo = [r for r in rows if r["plan"]["action"] in ("would_set", "refused")]
        print(f"{len(opens)} open items read from {store}; the pass run on a copy of it\n")
        print(f"{'item':<14}{'state':<11}{'keys retired':<44}{'held':<12}{'result':<9}same")
        for r in rows:
            p = r["plan"]
            if p["action"] == "same" and not p.get("held"):
                continue
            keys = ",".join(k for k in (p.get("before") or {})) or "-"
            print(f"{r['item']:<14}{(r['state'] or '-'):<11}{keys[:43]:<44}{','.join(p.get('held') or []) or '-':<12}{r['result']:<9}{'yes' if r['same'] else 'NO ' + r['why']}")
        needs = [(r, r["plan"]["after"]["description"]) for r in rows if r["plan"].get("after") and r["plan"]["after"].get("description") is not None]
        over: list[str] = []
        if needs:
            max_chars = int(_cfg.CFG["description"].get("line_max", 120))
            print(f"\nlines the pass adds to descriptions (the new description's last line; its lines before -> after against the limit of {max_lines}, and its longest line against {max_chars} characters):")
            for r, text in needs:
                n1, n0 = r["description_lines"]
                longest = max((len(x) for x in text.splitlines()), default=0)
                bad = server._description_fit_why(text)
                if bad:
                    over.append(r["item"])
                print(f"  {r['item']}: {text.rstrip(chr(10)).splitlines()[-1]}   [{n0} -> {n1} lines, longest line {longest} of {max_chars} characters{', OVER THE LIMIT: ' + bad if bad else ''}]")
        n_state = stores["state"]
        print("\nitems storing each field: " + ", ".join(f"{k} {n}" for k, n in sorted(stores.items())))
        print("state words stored by word: " + ", ".join(f"{k} {n}" for k, n in sorted(collections.Counter(r["state"] for r in rows if r["state"]).items())))
        by_result = collections.Counter(r["result"] for r in rows)
        print("result of the pass on the copy: " + ", ".join(f"{k} {n}" for k, n in sorted(by_result.items())) + f"; a second pass: " + ", ".join(f"{k} {n}" for k, n in sorted(collections.Counter(r["again"] for r in rows).items())))
        held = collections.Counter(f for r in rows for f in (r["plan"].get("held") or []))
        print("held back (left as they are): " + (", ".join(f"{k} on {n} item(s)" for k, n in sorted(held.items())) or "none") + f"; wait_kind stored on {stores['wait_kind']} item(s), stays")
        diff = [r["item"] for r in rows if not r["same"]]
        words = [(r["item"], r["before"]["word"], r["after"]["word"]) for r in rows if r["word_changes"]]
        refused = [r["item"] for r in rows if r["result"] == "refused"]
        print(f"items whose phase, kind of wait, list or mover would change: {len(diff)}" + (f" {diff}" if diff else ""))
        print(f"items whose old state word (the word itself, not the phase, kind or list) would read differently: {len(words)}" + (f" {words}" if words else ""))
        print(f"items the pass refuses (it would change a reading): {len(refused)}" + (f" {refused}" if refused else ""))
        print(f"items whose new description would break a limit: {len(over)}" + (f" {over}" if over else ""))
        print(f"items the pass would write: {by_result.get('set', 0)} of {len(rows)} ({n_state} store a state word)")
        if a.json:
            Path(a.json).write_text(json.dumps(rows, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        return 1 if diff or refused or over else 0
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
    opens = sorted((g for g, it in snap.items() if it.get("status") == "open"), key=SP.num)
    say(f"{len(opens)} open items read from {store}")
    plan: list[dict[str, Any]] = []
    for ch in SP.chunks(opens):
        st, d = app.call({"op": "retire", "items": ch, "dry": True})
        if st != 200:
            say(f"the plan could not be made: [{st}] {d.get('error') if isinstance(d, dict) else d}")
            return 1
        plan += d["results"]
    todo = [(g, r) for g, r in zip(opens, plan) if r.get("action") == "would_set"]
    refused = [r["item"] for r in plan if r.get("action") == "refused"]
    say(f"{len(todo)} of {len(opens)} would be retired; {sum(1 for r in plan if r.get('action') == 'same')} nothing to retire; {len(refused)} refused" + (f" ({', '.join(refused)})" if refused else ""))
    if not todo:
        print(json.dumps({"retired": 0}))
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
        st, d = app.call({"op": "retire", "items": ch, "pass_id": pass_id})
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
    print(json.dumps({"pass_id": pass_id, "undo": str(undo_path), "results": dict(counts), "refused_in_the_plan": refused,
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
        st, d = app.call({"op": "unretire", "items": [{"item": e["item"], "before": e["before"], "after": e["after"]} for e in ch]})
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
    ap = argparse.ArgumentParser(description="Take the stored state words and carry fields out of the open items: a dry run by default; --apply and --undo go through the live server.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="the real pass through the live server (needs --sender); run by a person on deploy")
    mode.add_argument("--undo", default="", metavar="FILE", help="put back the keys the undo file of a real pass names (needs --sender)")
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
