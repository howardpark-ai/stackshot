#!/usr/bin/env python3
"""tools/compare_pair_reads.py — read-only before/after comparison of how the open items are shown: from the fields alone (the reading the board gave before the stored pair) and from the stored pair
(`phase`, `waits_on`), which is now the only source of whether an item is alive or waiting and of the kind of its wait.

  tools/compare_pair_reads.py                       the live store, as it is now
  tools/compare_pair_reads.py --store <dir>         another store directory (the folder that holds a/, b/, … and anchors.json)
  tools/compare_pair_reads.py --hours 6 --sweep     the same store read 6 hours on, then after one sweep at that clock (the sweep runs on the private copy only)
  tools/compare_pair_reads.py --json out.json       the rows as JSON too

Nothing the live board holds is written. The store (and the page registry the server reads beside it) is copied into a private scratch folder under $TMPDIR that holds a shared lock while the script runs and is
removed at the end, whatever happens; the server module is pointed at that copy through a config made from the live one with every path inside the copy, GitHub sync and git off. The live config is only read.

One row per open item: the stored pair, what the fields give, what the stored-pair reading shows (phase, kind, the list the home page puts it in) and whether the two readings agree. The totals by (phase, kind) and by list
follow, and so does a count of the items whose rows differ. Exit 0 when every open item reads the same both ways (and none is unstamped), 1 otherwise. Python 3.12 or later; it runs itself in the tests' uv
environment when fastmcp is missing."""
from __future__ import annotations

import argparse
import collections
import fcntl
import json
import os
import re
import shutil
import sys
import tempfile
import time
import tomllib
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))
import stamp_phase as SP  # noqa: E402  — load_dir, frozen, fields_only, num

LIVE_CONFIG = Path(os.environ.get("STACKSHOT_CONFIG") or "~/.config/stackshot/stackshot.toml").expanduser()
PATH_KEYS = {"repo": "repo", "store": "repo/board-data", "markdown": "repo/board.md", "brain": "brain", "state": "state", "secrets": "secrets", "project_touch": "project_touch"}      # the store lives inside the repo, as the publisher requires


def ensure_env(script: str = __file__) -> None:
    """Re-run the script `script` (default this one) in the tests' uv environment when fastmcp (which the server imports) is missing."""
    try:
        import fastmcp  # noqa: F401, PLC0415
        return
    except ImportError:
        pass
    uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
    env = dict(os.environ)
    env.setdefault("UV_PROJECT_ENVIRONMENT", str(Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "stackshot" / "test-venv"))
    if not Path(uv).exists():
        raise SystemExit("compare_pair_reads: fastmcp is missing and uv was not found: run it from the tests' environment, or install uv")
    os.execve(uv, [uv, "run", "--locked", "--project", str(HERE / "tests"), "python", str(Path(script).resolve()), *sys.argv[1:]], env)


def scratch_config(text: str, root: Path) -> str:
    """The live config text with every path of [paths] inside `root`, git and GitHub sync off. Only the keys are rewritten; every rule, label and setting stays as the live config has it."""
    for key, rel in PATH_KEYS.items():
        text, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{root}/{rel}"', text, count=1)
        if n != 1:
            raise SystemExit(f"compare_pair_reads: [paths] {key} not found in {LIVE_CONFIG}")
    text = re.sub(r"(?m)^git = true", "git = false", text)
    text = re.sub(r"(?m)^sync = true", "sync = false", text, count=1)
    return text


def make_scratch(store: Path, brain: Path | None) -> Path:
    """The private copy: store, page registry and (when there is one) the pages of the brain mirror; and the config. → its folder."""
    root = Path(tempfile.mkdtemp(prefix="comparepair-"))
    (root / "repo").mkdir()
    shutil.copytree(store, root / "repo/board-data", ignore=shutil.ignore_patterns(".git", "*.tmp", ".*"))
    for sub in ("state", "secrets", "project_touch", "fleet"):
        (root / sub).mkdir()
    (root / "repo/board.md").write_text("", encoding="utf-8")
    if brain is not None and brain.is_dir():
        shutil.copytree(brain, root / "brain", ignore=shutil.ignore_patterns(".git", "*.tmp"))
    else:
        (root / "brain").mkdir()
    (root / "stackshot.toml").write_text(scratch_config(LIVE_CONFIG.read_text(encoding="utf-8"), root), encoding="utf-8")
    return root


def rows_at(server: Any, store: Path, now: float, label: str) -> list[dict[str, Any]]:
    """One row per open item of the store at the clock `now`: the pair it stores, the reading from the fields, the reading from the stored pair, the list each puts it in."""
    items = SP.load_dir(store)
    out: list[dict[str, Any]] = []
    model = server._model
    for g in sorted((g for g, it in items.items() if it.get("status") == "open"), key=SP.num):
        it = items[g]
        probe = {**it, "gid": g}
        ao = lambda i_: server._after_open(i_.get("metadata") or {})      # noqa: E731
        with SP.frozen(now):
            mod = server._model_of(probe)
            fields = model.view(probe, mod, now, ao, check=False)
            stored = model.view(probe, mod, now, ao)
            with SP.fields_only(server):
                list_fields = server._item_list(probe)
            list_stored = server._item_list(probe)
        meta = it.get("metadata") or {}
        out.append({"item": server._gh.shown(g), "gid": g, "at": label, "stored": {"phase": meta.get("phase"), "waits_on": meta.get("waits_on")},
                    "fields": list(model.shown_pair(fields)), "shown": list(model.shown_pair(stored)), "list_fields": list_fields, "list_shown": list_stored,
                    "same": model.shown_pair(fields) == model.shown_pair(stored) and list_fields == list_stored, "unstamped": not (model.stored_phase(probe) and (model.stored_phase(probe) == model.ALIVE or model.stored_waits_on(probe)))})
    return out


def report(rows: list[dict[str, Any]], title: str) -> int:
    print(f"\n== {title}: {len(rows)} open items")
    print(f"{'item':<14}{'stored (phase/kind)':<24}{'fields (phase/kind)':<24}{'shown (phase/kind)':<24}{'list fields -> shown':<28}same")
    for r in rows:
        st = f"{r['stored']['phase'] or '-'}/{r['stored']['waits_on'] or '-'}"
        f = f"{r['fields'][0] or '-'}/{r['fields'][1] or '-'}"
        s = f"{r['shown'][0] or '-'}/{r['shown'][1] or '-'}"
        print(f"{r['item']:<14}{st:<24}{f:<24}{s:<24}{r['list_fields'] + ' -> ' + r['list_shown']:<28}{'yes' if r['same'] else 'NO'}{'  (unstamped)' if r['unstamped'] else ''}")
    by_pair = collections.Counter(tuple(r["shown"]) for r in rows)
    by_list = collections.Counter(r["list_shown"] for r in rows)
    diff = [r["item"] for r in rows if not r["same"]]
    unst = [r["item"] for r in rows if r["unstamped"]]
    print("shown by (phase, kind): " + ", ".join(f"{p or '-'}/{k or '-'} {n}" for (p, k), n in sorted(by_pair.items())))
    print("shown by list: " + ", ".join(f"{k} {n}" for k, n in sorted(by_list.items())))
    print(f"items read differently by the two readings: {len(diff)}" + (f" {diff}" if diff else ""))
    print(f"items with no usable stored pair: {len(unst)}" + (f" {unst}" if unst else ""))
    return len(diff) + len(unst)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Read-only before/after comparison of the fields reading and the stored-pair reading of the open items.")
    ap.add_argument("--store", help="a store directory to read (default: [paths] store of the live config)")
    ap.add_argument("--hours", type=float, default=0.0, help="also read the store this many hours on from now (the stored pairs are then as old as the live sweep left them)")
    ap.add_argument("--sweep", action="store_true", help="with --hours: sweep the private copy at that clock and read it again")
    ap.add_argument("--json", help="write the rows to this file")
    a = ap.parse_args(argv)
    ensure_env()
    live = tomllib.loads(LIVE_CONFIG.read_text(encoding="utf-8"))["paths"]
    store = Path(a.store or live["store"]).expanduser().resolve()
    brain = Path(live.get("brain") or "").expanduser() if live.get("brain") else None
    root = make_scratch(store, brain)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    fcntl.flock(fd, fcntl.LOCK_SH)      # systemd-tmpfiles ageing skips a folder that holds a lock
    try:
        os.environ["STACKSHOT_CONFIG"] = str(root / "stackshot.toml")
        os.environ["STACKSHOT_AUTH"] = "off"
        os.environ.pop("STACKSHOT_URL", None)
        os.environ["STACKSHOT_FLEET_DIR"] = str(root / "fleet")
        import server  # noqa: PLC0415  — after the environment points at the copy
        server._publish = lambda: None
        now = time.time()
        bad = 0
        all_rows: list[dict[str, Any]] = []
        rows = rows_at(server, root / "repo/board-data", now, "now")
        bad += report(rows, "the store now")
        all_rows += rows
        if a.hours:
            later = now + a.hours * 3600.0
            rows = rows_at(server, root / "repo/board-data", later, f"+{a.hours:g} h")
            report(rows, f"the same store {a.hours:g} h on, no sweep (informational: the live sweep restamps a pair within a minute)")
            all_rows += rows
            if a.sweep:
                with SP.frozen(later):
                    stamped = server._phase_sweep()
                rows = rows_at(server, root / "repo/board-data", later, f"+{a.hours:g} h swept")
                bad += report(rows, f"+{a.hours:g} h after one sweep on the copy ({len(stamped)} restamped)")
                all_rows += rows
        if a.json:
            Path(a.json).write_text(json.dumps(all_rows, indent=1, ensure_ascii=False), encoding="utf-8")
        print("\nresult:", "every open item reads the same both ways" if not bad else f"{bad} difference(s) to look at")
        return 1 if bad else 0
    finally:
        os.close(fd)
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
