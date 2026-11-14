"""tools/stamp_phase.py — the one-time stamp of the stored phase and the kind of its wait on the open items already in the store.

Every save of an open item stores two keys beside its fields (`server._phase_stamp`): `metadata.phase` (alive | waiting, what the board SHOWS the item as) and, for a waiting one, `metadata.waits_on`
(time | anchor | item | relay | event, the kind of the wait it shows). An item nobody has saved since gets them here. The server works the two values out AT WRITE TIME, under the item's lock, from the item's
fields as they stand (`server._stamp_one`), so nothing planned can be stale; it writes those two keys and nothing else: no `updated`, no writer, no activity clock, no hand-off record, no For you row,
no GitHub job, and `wait_kind` is never touched (a stored `wait_kind` hands an item to the watchers; `waits_on` is only a label). A closed item is left as it is. No begin and no hold: a session's
update takes its turn at the item's lock. Run it at a quiet time, away from the `edge` rows below.

  tools/stamp_phase.py --dry-run --store <copy>   the whole pass on a COPY of the store (a directory with its own stackshot.toml, the same as tools/migrate_model.py takes): the server module is imported
                                                  against the copy and, to prove what the stamp changes, applies it to a private scratch copy of the items that is removed again, so <copy> itself is never
                                                  written. Writes the report (markdown and JSON) to --report-dir: one row per open item (item | old display | stored before | shown now | stored after | watches
                                                  before=after | change), the totals by (phase, kind), the items that store a `wait_kind` (exceptions first) and three proof lines: display diff, `watches` diff and files
                                                  changed outside the two keys, all of which must read 0. `change`: add (nothing stored) · fix (a stored value the fields now disagree with) · same · edge (an add or a fix whose
                                                  wait ends within 24 hours: it may flip soon, which is expected). --expect-waiting time=18,relay=11 compares the waiting-by-kind counts with a figure you name.
  tools/stamp_phase.py --apply --sender <you>     the real pass, through the live server (POST /client/migrate op stamp, this machine's token; [model] migration = true on the server, the operator's switch). It asks
                                                  for the plan first (op stamp with dry), writes the undo file <run-dir>/<pass id>/undo.json (fsynced) BEFORE the first write, stamps in batches, and keeps each
                                                  batch's real result in the undo file. A file a session saved after our stamp is told apart (its updated, written_at or bytes no longer
                                                  what the stamp left): it is printed as informational and never fails the run; only a file the stamp itself changed outside the two keys does. A second run answers `same` for every item and writes nothing, except an item that crossed a clock edge. Run it only on the owner's word.
  tools/stamp_phase.py --undo <file> --sender <you>   puts every item back the way the undo file says (op unstamp): an item that still holds what the stamp left gets its old keys back (a key that was absent is
                                                  dropped), one that already holds them answers `same`, and one a later save restamped answers `kept` and is left as it is. Running it twice is a no-op. An entry the run died on
                                                  (no recorded result) takes its real keys from the server's pass record, not the planned ones.

Exit 0 · 1 when a proof line reads other than 0, an item was refused, or a batch could not be made. Python 3.12 or later; the dry run runs itself in the tests' uv environment when fastmcp is missing
(run it as `uv run --no-project python -m stackshot.tools.stamp_phase …` from the checkout)."""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import argparse
import collections
import contextlib
import datetime as dt
import fcntl
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[2]
from stackshot.tools import migrate_model as MM  # noqa: E402  — the migration script's pieces: the copy guard, the appliers, the report table
DEFAULT_REPORTS = Path.home() / ".local" / "share" / "stackshot-runs" / "stamp-dryrun"
DEFAULT_RUN = Path.home() / ".local" / "share" / "stackshot-runs" / "stamp-run"
BATCH = 40
KEYS = ("phase", "waits_on")
EDGE_S = 24 * 3600.0
say = MM.say


def ensure_env() -> None:
    """Re-run this script in the tests' uv environment when fastmcp (which the server imports) is missing, as the other dry-run tools do."""
    try:
        import fastmcp  # noqa: F401, PLC0415
        return
    except ImportError:
        pass
    uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
    env = dict(os.environ)
    env.setdefault("UV_PROJECT_ENVIRONMENT", str(Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "stackshot" / "test-venv"))
    if not Path(uv).exists():
        raise SystemExit("stamp_phase: fastmcp is missing and uv was not found: run it from the tests' environment, or install uv")
    os.execve(uv, [uv, "run", "--locked", "--project", str(HERE), "--only-group", "tests", "python", str(Path(__file__).resolve()), *sys.argv[1:]], env)


# ---------------------------------------------------------------------------------------------------------------- reading a store
def num(gid: str) -> int:
    return int(re.sub(r"\D", "", gid) or 0)


def load_dir(store: Path, shas: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """Every item file of a store directory as parsed JSON, by id. Read only. `shas`, when given, is filled with the sha256 of each file's bytes (the hash the server takes of the same bytes)."""
    import hashlib
    out: dict[str, dict[str, Any]] = {}
    for p in sorted(store.glob("*/*.json")):
        gid = p.parent.name + p.stem
        if not re.fullmatch(r"[a-z]\d+", gid):
            continue
        try:
            data = p.read_bytes()
            d = json.loads(data)
        except (OSError, ValueError):
            continue
        if isinstance(d, dict):
            out[gid] = d
            if shas is not None:
                shas[gid] = hashlib.sha256(data).hexdigest()
    return out


def load_some(store: Path, gids: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Just these items of a store directory: ({id: parsed JSON}, {id: sha256 of the file's bytes}). Read only; an id whose file is missing or does not read is left out."""
    import hashlib
    items: dict[str, dict[str, Any]] = {}
    shas: dict[str, str] = {}
    for g in gids:
        try:
            data = (store / g[0] / f"{g[1:]}.json").read_bytes()
            d = json.loads(data)
        except (OSError, ValueError):
            continue
        if isinstance(d, dict):
            items[g], shas[g] = d, hashlib.sha256(data).hexdigest()
    return items, shas


def save_marks(it: dict[str, Any]) -> tuple[Any, Any]:
    """What a session's save moves and the stamp never does."""
    return it.get("updated"), it.get("written_at")


def tree_hash(store: Path) -> dict[str, str]:
    import hashlib
    return {str(p.relative_to(store)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(store.rglob("*")) if p.is_file() and ".git" not in p.parts}


def pair(it: dict[str, Any]) -> dict[str, Any]:
    m = it.get("metadata") if isinstance(it.get("metadata"), dict) else {}
    return {k: m.get(k) for k in KEYS}


def without_keys(it: dict[str, Any]) -> dict[str, Any]:
    """The item with the two stamped keys left out: what the stamp must leave exactly as it was."""
    out = dict(it)
    if isinstance(out.get("metadata"), dict):
        out["metadata"] = {k: v for k, v in out["metadata"].items() if k not in KEYS}
    return out


def files_outside(before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]) -> list[str]:
    """The ids whose file differs in anything but the two keys (an item missing on either side counts)."""
    return sorted((g for g in {*before, *after} if g not in before or g not in after or without_keys(before[g]) != without_keys(after[g])), key=num)


def write_atomic(path: Path, obj: Any) -> None:
    """The file written whole and fsynced, then moved into place, and the folder fsynced: what is on disk when this returns is complete."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(obj, indent=1, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def classify(before: dict[str, Any], after: dict[str, Any], edge: bool) -> str:
    """add · fix · same · edge: same when nothing differs; add when every key that differs was absent; fix when a stored value differs (stale or half-stamped); edge when an add or a fix ends soon."""
    diff = [k for k in KEYS if before.get(k) != after.get(k)]
    if not diff:
        return "same"
    kind = "fix" if any(before.get(k) is not None for k in diff) else "add"
    return "edge" if edge else kind


def chunks(xs: list[Any], n: int = BATCH) -> list[list[Any]]:
    return [xs[i:i + n] for i in range(0, len(xs), n)]


# ---------------------------------------------------------------------------------------------------------------- the dry run
@contextlib.contextmanager
def frozen(now: float) -> Any:
    """Hold `time.time` at `now` inside the block. The board's text reads the clock itself (the wait's floor, the past-due mark, `stale N d`), and the server functions `display_of` calls take no `now`: the
    before and after passes of the proof run a few seconds apart, so a minute or an hour edge between them would show as a change the stamp never made. One frozen clock for both passes keeps the proof exact."""
    real = time.time
    time.time = lambda: now
    try:
        yield
    finally:
        time.time = real


@contextlib.contextmanager
def fields_only(server: Any) -> Any:
    """Every reader works the alive-or-waiting decision out from the item's fields alone (model.view patched to the writer's reading): what the board showed before the pair was stored, and what a stamp must leave on show."""
    from stackshot.model import model as _model  # noqa: PLC0415
    real = _model.view
    _model.view = lambda item, mod, now=None, after_open=None, check=True: _model._shown(item, mod, now, after_open)
    try:
        yield
    finally:
        _model.view = real


def display_of(server: Any, it: dict[str, Any], gid: str, stored: bool = False) -> dict[str, Any]:
    """Everything the board shows of an item that the stamp must leave alone, and whether the watchers own it: the 7-state word and wait the model shows, the list word, the model line, get's text and the brief's block.
    `stored` False: as the stamp proof has always read it (the fields alone, the writer's reading). True: as the readers show it now (the stored pair decides alive or waiting and the kind of the wait)."""
    from stackshot.model import model as _model  # noqa: PLC0415
    probe = {**it, "gid": gid}
    mod = _model.view(probe, server._item_read._model_of(probe), after_open=lambda i_: server._item_read._after_open(i_.get("metadata") or {}), check=stored)
    return {"today": mod.today or "", "state": mod.state, "kind": mod.wait.kind if mod.wait else "", "until": mod.wait.until if mod.wait else "", "backstop": mod.wait.backstop if mod.wait else "",
            "conflicts": list(mod.conflicts), "list": server._item_list(probe), "model": server._tool_notes._model_lines(probe, short=True), "fmt": server._tool_get._fmt(probe), "brief": server._tool_get._fmt(probe, brief=True)}


def ends_within(mod_until: str, backstop: str, tz: Any, now: float) -> bool:
    for v in (mod_until, backstop):
        v = str(v or "").strip()
        if not v:
            continue
        try:
            d = dt.datetime.fromisoformat(v) if "T" in v or " " in v else dt.datetime.combine(dt.date.fromisoformat(v[:10]), dt.time(0, 0))
        except ValueError:
            continue
        if d.tzinfo is None:
            d = d.replace(tzinfo=tz)
        if d.timestamp() <= now + EDGE_S:
            return True
    return False


def dry_run(a: argparse.Namespace) -> int:
    ensure_env()      # first: it may start this process again, and the copy's config must not be taken for the live one on the second start
    copy_dir = MM.point_at_copy(a.store)
    from stackshot.core import config as _cfg
    from stackshot.core import store as _store  # noqa: PLC0415
    from stackshot.github import ghsync as _gh  # noqa: PLC0415
    from stackshot.model import model as _model  # noqa: PLC0415
    from stackshot.waits import watchers as _watch  # noqa: PLC0415
    app = MM.DryApplier(a.sender or "dry-run")
    server = app.server
    store = _cfg.path("paths", "store")
    tz = _cfg.tz()
    now = time.time()
    items = load_dir(store)
    hashes0 = tree_hash(store)
    opens = sorted((g for g, it in items.items() if it.get("status") == "open"), key=num)
    closed_stale = sorted((g for g, it in items.items() if it.get("status") != "open" and any(k in (it.get("metadata") or {}) for k in KEYS)), key=num)
    say(f"{len(opens)} open and {len(items) - len(opens)} closed items read from {store}")

    # ---- the plan: what the server would stamp now (nothing written)
    plan: dict[str, dict[str, Any]] = {}
    for ch in chunks(opens):
        st, d = app.call({"op": "stamp", "items": ch, "dry": True})
        if st != 200:
            raise SystemExit(f"the plan could not be made: [{st}] {d.get('error') if isinstance(d, dict) else d}")
        plan.update(zip(ch, d["results"]))
    with frozen(now), fields_only(server):      # one clock for the before and the after pass; the stamp between them runs on the real one. Before: what the fields give; after: what the stored pair gives
        disp0 = {g: display_of(server, items[g], g) for g in opens}
        watch0 = {g: bool(_watch.watches(items[g])) for g in opens}

    # ---- the stamp on a private scratch copy of the items (removed again), to prove what it changes
    scratch = Path(tempfile.mkdtemp(prefix="stampdry-"))
    fd = os.open(scratch, os.O_RDONLY | os.O_DIRECTORY)
    fcntl.flock(fd, fcntl.LOCK_SH)      # systemd-tmpfiles ageing skips a folder that holds a lock
    real_store = _store.STORE
    results: list[dict[str, Any]] = []
    try:
        shutil.copytree(store, scratch / "store", ignore=shutil.ignore_patterns(".git", "*.tmp"))
        _store.STORE = scratch / "store"
        for ch in chunks(opens):
            st, d = app.call({"op": "stamp", "items": ch})
            if st != 200:
                raise SystemExit(f"the stamp on the scratch copy was refused: [{st}] {d.get('error') if isinstance(d, dict) else d}")
            results += d["results"]
        after_items = load_dir(scratch / "store")
        with frozen(now):
            disp1 = {g: display_of(server, after_items[g], g) for g in opens}
            watch1 = {g: bool(_watch.watches(after_items[g])) for g in opens}
        outside = files_outside(items, after_items)
    finally:
        _store.STORE = real_store
        os.close(fd)
        shutil.rmtree(scratch, ignore_errors=True)

    # ---- the table
    rows: list[dict[str, Any]] = []
    for g in opens:
        it = items[g]
        r = plan[g]
        mod_wait_until = disp0[g]["until"]
        edge = ends_within(mod_wait_until, disp0[g]["backstop"], tz, now) if disp0[g]["state"] == _model.WAITING else False
        before_p, now_p = pair(it), r.get("after") or {}
        row = {"item": _gh.shown(g), "gid": g, "old_state": disp0[g]["today"], "old_list": disp0[g]["list"],
               "before": before_p, "wait_kind": (it.get("metadata") or {}).get("wait_kind"), "shown": now_p, "after": pair(after_items[g]),
               "watches": [watch0[g], watch1[g]], "change": classify(before_p, now_p, edge), "action": r.get("action"), "ends": mod_wait_until}
        rows.append(row)
    by_pk = collections.Counter((r["shown"].get("phase") or "-", r["shown"].get("waits_on") or "-") for r in rows)
    by_change = collections.Counter(r["change"] for r in rows)
    stored_wk = [r for r in rows if r["wait_kind"]]
    wk_bad = [r for r in stored_wk if r["after"].get("waits_on") != r["wait_kind"]]
    proofs = {"display_diff": [r["item"] for r in rows if disp0[r["gid"]] != disp1[r["gid"]]],
              "watches_diff": [r["item"] for r in rows if watch0[r["gid"]] != watch1[r["gid"]]],
              "files_outside_the_two_keys": [_gh.shown(g) for g in outside],
              "store_written_by_the_dry_run": sorted(k for k in {*hashes0, *tree_hash(store)} if hashes0.get(k) != tree_hash(store).get(k))}
    detail = {r["item"]: {k: [disp0[r["gid"]][k], disp1[r["gid"]][k]] for k in disp0[r["gid"]] if disp0[r["gid"]][k] != disp1[r["gid"]][k]} for r in rows if disp0[r["gid"]] != disp1[r["gid"]]}
    waiting_by_kind = {k: v for (p, k), v in sorted(by_pk.items()) if p == "waiting"}
    expect_line = ""
    if a.expect_waiting:
        want = {k.strip(): int(v) for k, v in (x.split("=") for x in a.expect_waiting.split(",") if x.strip())}
        expect_line = f"waiting by kind {waiting_by_kind} against the figure named {want}: " + ("equal" if waiting_by_kind == want else "DIFFERENT")
    by_action = collections.Counter(r.get("action") for r in results)
    rep = {"mode": "dry run on a copy", "when": dt.datetime.now(tz).strftime("%a %b %d %H:%M %Z"), "store": str(store), "counts": {"open": len(opens), "closed": len(items) - len(opens),
           "closed_with_a_stale_stamp": len(closed_stale), "applied_to_scratch": by_action.get("set", 0), "same": by_action.get("same", 0), "moved": by_action.get("moved", 0),
           "refused": by_action.get("refused", 0)},
           "by_phase_and_kind": {f"{p}/{k}": v for (p, k), v in sorted(by_pk.items())}, "waiting_by_kind": waiting_by_kind, "by_change": dict(by_change), "expect": expect_line,
           "stored_wait_kind": [{"item": r["item"], "wait_kind": r["wait_kind"], "waits_on_after": r["after"].get("waits_on")} for r in stored_wk], "stored_wait_kind_exceptions": [r["item"] for r in wk_bad],
           "closed_with_a_stale_stamp": [_gh.shown(g) for g in closed_stale], "proofs": proofs, "display_diff_detail": detail, "rows": rows}
    d = Path(a.report_dir).expanduser()
    jp, mp = write_report(rep, d, dt.datetime.now(tz).strftime("%Y-%m-%d"))
    say(f"report: {jp} and {mp}")
    bad = bool(proofs["display_diff"] or proofs["watches_diff"] or proofs["files_outside_the_two_keys"] or proofs["store_written_by_the_dry_run"] or wk_bad or by_action.get("refused", 0))
    print(json.dumps({"report": str(mp), "json": str(jp), "counts": rep["counts"], "by_change": rep["by_change"], "waiting_by_kind": waiting_by_kind,
                      "proofs": {k: len(v) for k, v in proofs.items()}}, indent=1))
    return 1 if bad else 0


def cell(p: dict[str, Any]) -> str:
    return f"{p.get('phase') or '-'} / {p.get('waits_on') or '-'}"


def write_report(rep: dict[str, Any], d: Path, stamp: str) -> tuple[Path, Path]:
    d.mkdir(parents=True, exist_ok=True)
    jp, mp = d / f"{stamp}-stamp-dryrun.json", d / f"{stamp}-stamp-dryrun.md"
    jp.write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    c, pr = rep["counts"], rep["proofs"]
    lines = [f"# Stamp of the stored phase and wait kind, {rep['mode']}, {rep['when']}", "",
             f"{c['open']} open items, {c['closed']} closed ({c['closed_with_a_stale_stamp']} closed carry a stamp, counted and left). Applied on a scratch copy: {c['applied_to_scratch']} stamped, "
             f"{c['same']} already so, {c['moved']} moved, {c['refused']} refused.", "",
             "## Proof", "", f"- display diff: {len(pr['display_diff'])}" + (f" ({', '.join(pr['display_diff'][:10])})" if pr["display_diff"] else ""),
             f"- watches diff: {len(pr['watches_diff'])}" + (f" ({', '.join(pr['watches_diff'][:10])})" if pr["watches_diff"] else ""),
             f"- files changed outside the two keys: {len(pr['files_outside_the_two_keys'])}" + (f" ({', '.join(pr['files_outside_the_two_keys'][:10])})" if pr["files_outside_the_two_keys"] else ""),
             f"- store written by this dry run: {len(pr['store_written_by_the_dry_run'])}", "",
             "## Totals", "", MM.md_table([[k, str(v)] for k, v in rep["by_phase_and_kind"].items()], ["shown now (phase / kind)", "items"]), "",
             MM.md_table([[k, str(v)] for k, v in sorted(rep["by_change"].items())], ["change", "items"]), ""]
    if rep["expect"]:
        lines += [rep["expect"], ""]
    lines += ["## Items that store a wait_kind (exceptions first)", ""]
    exc = set(rep["stored_wait_kind_exceptions"])
    skw = sorted(rep["stored_wait_kind"], key=lambda x: (x["item"] not in exc, num(x["item"])))
    lines += [MM.md_table([[x["item"], x["wait_kind"], x["waits_on_after"] or "-", "EXCEPTION" if x["item"] in exc else "equal"] for x in skw], ["item", "wait_kind", "waits_on after", ""]) if skw else "none", ""]
    if rep["closed_with_a_stale_stamp"]:
        lines += ["## Closed items that carry a stamp (counted, not changed; their next save drops it)", "", ", ".join(rep["closed_with_a_stale_stamp"]), ""]
    head = ["item", "old display (state, list)", "stored before (phase / waits_on / wait_kind)", "shown now (phase / kind)", "stored after", "watches before=after", "change"]
    body = [[r["item"], f"{r['old_state'] or '-'}, {r['old_list']}", f"{cell(r['before'])} / {r['wait_kind'] or '-'}", cell(r["shown"]), cell(r["after"]),
             f"{'yes' if r['watches'][0] else 'no'}={'yes' if r['watches'][1] else 'no'}", r["change"] + (f" (ends {r['ends']})" if r["change"] == "edge" else "")] for r in rep["rows"]]
    lines += ["## Every open item", "", MM.md_table(body, head), ""]
    mp.write_text("\n".join(lines), encoding="utf-8")
    return jp, mp


# ---------------------------------------------------------------------------------------------------------------- the real pass and its undo
def new_pass_id() -> str:
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{os.urandom(3).hex()}"


def apply(a: argparse.Namespace, app: Any = None) -> int:
    """The real pass. `app` (tests only) answers app.call(body) → (status, answer) in place of the live server."""
    from stackshot.core import config as _cfg
    store = _cfg.path("paths", "store")
    run_dir = Path(a.run_dir).expanduser()
    app = app or MM.LiveApplier(a.sender)
    snap_sha: dict[str, str] = {}
    snap = load_dir(store, snap_sha)
    opens = sorted((g for g, it in snap.items() if it.get("status") == "open"), key=num)
    say(f"{len(opens)} open items read from {store}")
    plan: list[dict[str, Any]] = []
    for ch in chunks(opens):
        st, d = app.call({"op": "stamp", "items": ch, "dry": True})
        if st != 200:
            say(f"the plan could not be made: [{st}] {d.get('error') if isinstance(d, dict) else d}")
            return 1
        plan += d["results"]
    todo = [(g, r) for g, r in zip(opens, plan) if r.get("action") == "would_set"]
    say(f"{len(todo)} of {len(opens)} would be stamped; {sum(1 for r in plan if r.get('action') == 'same')} already so; {sum(1 for r in plan if r.get('action') == 'refused')} refused")
    if not todo:
        print(json.dumps({"stamped": 0, "same": sum(1 for r in plan if r.get("action") == "same")}))
        return 0
    pass_id = new_pass_id()
    undo_path = run_dir / pass_id / "undo.json"
    undo = {"pass_id": pass_id, "by": a.sender, "when": dt.datetime.now(_cfg.tz()).strftime("%a %b %d %H:%M %Z"), "store": str(store),
            "items": [{"item": g, "shown": r["item"], "before": r["before"], "after": r["after"], "sha256_before": r["sha256_before"], "result": None} for g, r in todo]}
    write_atomic(undo_path, undo)      # on disk, whole, before the first write
    say(f"undo file written: {undo_path}")
    entries = {e["item"]: e for e in undo["items"]}
    counts: collections.Counter[str] = collections.Counter()
    written: list[str] = []
    stamped: dict[str, dict[str, Any]] = {}
    for ch in chunks([g for g, _ in todo]):
        st, d = app.call({"op": "stamp", "items": ch, "pass_id": pass_id})
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
            if r["action"] == "set":
                written.append(g)
        write_atomic(undo_path, undo)      # the real result of each item, kept as it comes
        # the file as our stamp left it, read right after the batch: a later session save on it is told apart from a fault of the stamp below
        done = [g for g, r in zip(ch, d["results"]) if r["action"] == "set"]
        got, got_sha = load_some(store, done)
        for g in done:
            if g in got:
                stamped[g] = {"sha": got_sha[g], "marks": save_marks(got[g])}
    after_sha: dict[str, str] = {}
    after = load_dir(store, after_sha)
    raced = [g for g in written if entries[g]["sha256_before"] != snap_sha.get(g)]
    # a session saved the item after our stamp: its updated / written_at or its bytes are no longer what the stamp left. Informational, never a failure.
    later = [g for g in written if g not in raced and (g not in stamped or stamped[g]["marks"] != save_marks(snap[g]) or after_sha.get(g) != stamped[g]["sha"])]
    outside = [g for g in written if g not in raced and g not in later and without_keys(snap[g]) != without_keys(after.get(g, {}))]
    if later:
        say(f"informational, not a failure: {len(later)} item(s) saved by a session after our stamp, so their files differ from the stamp's: {', '.join(entries[g]['shown'] for g in later)}")
    print(json.dumps({"pass_id": pass_id, "undo": str(undo_path), "results": dict(counts), "written": len(written), "written_after_a_session_wrote_them_since_the_plan_read": len(raced),
                      "saved_by_a_session_since_our_stamp": [entries[g]["shown"] for g in later],
                      "files_changed_outside_the_two_keys": len(outside), "moved_run_again_for_these": [e["shown"] for e in entries.values() if e.get("result") == "moved"]}, indent=1))
    return 1 if counts.get("refused") or counts.get("batch refused") or outside else 0


def resolve_unrecorded(rec: dict[str, Any]) -> int:
    """An entry whose result is still None is one the run died on, between the server writing its batch and write_atomic recording it: its `after` is the planned one, and the real stamp may differ (a clock
    edge between the plan and the write). The server keeps every batch's real results in the pass record (<state>/migration/<pass id>.json, op stamp with a pass_id): for such an entry the record's result
    (action, before, after) is taken in its place, in memory. An entry the record does not name (the run died before the server's write, or no record is here) keeps its planned values. → how many entries were resolved."""
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
            e["before"], e["after"] = r["before"], r["after"]
        n += 1
    say(f"{len(pend)} entries had no recorded result: {n} taken from the server's pass record, {len(pend) - n} keep their planned values")
    return n


def undo(a: argparse.Namespace, app: Any = None) -> int:
    rec = json.loads(Path(a.undo).expanduser().read_text(encoding="utf-8"))
    resolve_unrecorded(rec)
    todo = [e for e in rec["items"] if e.get("result") not in ("moved", "refused", "same")]
    say(f"{len(todo)} of {len(rec['items'])} entries to put back (pass {rec.get('pass_id')})")
    app = app or MM.LiveApplier(a.sender)
    counts: collections.Counter[str] = collections.Counter()
    kept: list[str] = []
    for ch in chunks(todo):
        st, d = app.call({"op": "unstamp", "items": [{"item": e["item"], "before": e["before"], "after": e["after"]} for e in ch]})
        if st != 200:
            say(f"a batch was refused as a whole: [{st}] {d.get('error') if isinstance(d, dict) else d}")
            counts["batch refused"] += len(ch)
            continue
        for e, r in zip(ch, d["results"]):
            counts[r["action"]] += 1
            if r["action"] == "kept":
                kept.append(e.get("shown") or e["item"])
    print(json.dumps({"results": dict(counts), "kept_because_a_later_save_restamped_them": kept}, indent=1))
    return 1 if counts.get("refused") or counts.get("batch refused") else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Stamp the stored phase and the kind of its wait on the open items: the server works the two values out and writes them.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="the whole pass on a copy of the store (--store); nothing live and not even the copy is written")
    mode.add_argument("--apply", action="store_true", help="the real pass through the live server (needs --sender); only on the owner's word")
    mode.add_argument("--undo", default="", metavar="FILE", help="put back the keys the undo file of a real pass names (needs --sender)")
    ap.add_argument("--store", default="", help="with --dry-run: the copy's directory (it holds its own stackshot.toml)")
    ap.add_argument("--sender", default="", help="the session that runs the pass (one of [model] migration_senders); needed with --apply and --undo")
    ap.add_argument("--report-dir", default=str(DEFAULT_REPORTS))
    ap.add_argument("--run-dir", default=str(DEFAULT_RUN), help="the real pass: where the undo file is kept (<run-dir>/<pass id>/undo.json)")
    ap.add_argument("--expect-waiting", default="", help="with --dry-run: waiting-by-kind counts to compare with, e.g. time=3,relay=2,item=1,anchor=1")
    a = ap.parse_args(argv)
    if (a.apply or a.undo) and not a.sender.strip():
        ap.error("--apply and --undo need --sender <the session that runs the pass>")
    if a.dry_run:
        if not a.store:
            ap.error("--dry-run needs --store <a copy of the store>")
        return dry_run(a)
    if a.apply:
        return apply(a)
    return undo(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
