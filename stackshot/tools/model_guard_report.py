"""tools/model_guard_report.py — what the item model's write guards (model_guards.py) would refuse on the items already in the store. Read only: it
changes no item, refuses nothing and needs no server. Stdlib only, Python 3.11+.

  tools/model_guard_report.py             the whole report: per guard the count and the item ids, an example refusal each, what carries broad wait words, what rests on a default
  tools/model_guard_report.py --line      the one line the brief carries ("model guards would refuse on existing items: mover 3 · wait input 12 · …")
  tools/model_guard_report.py --json      the same as JSON ({"open", "closed", "guards": {key: [ids]}, "flagged", "defaulted"})
  tools/model_guard_report.py --owner-mover   the dry run (the older flag spelling still works) of the guard that refuses the owner as mover with no step or ask: the open items that already have it, one line each:
                                          id, subject, mover, state, creator, what is missing (--json: a list of those records)
  tools/model_guard_report.py --store DIR      read the items from DIR (a copy of the store) instead of [paths] store; combines with the flags above

The audit calls it for the full list (the brief has the counts). The config is the usual one ($STACKSHOT_CONFIG or ~/.config/stackshot/stackshot.toml): the store, the session
registry and the fleet heartbeats are read from the paths it names. Exit 0."""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[2]
from stackshot.core import config as _cfg  # noqa: E402
from stackshot.model import model_guards as _mg  # noqa: E402


def load_all(store: Path | None = None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for p in sorted((store or _cfg.path("paths", "store")).glob("*/*.json")):
        gid = p.parent.name + p.stem
        if not re.fullmatch(r"[a-z]\d+", gid):
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict):
            out[gid] = d
    return out


def _label(ref: str) -> str:
    """A session reference as the registry names it now, else as stored."""
    try:
        from stackshot.fleet import sessions_registry as _sr
        return _sr.display_name(ref) or ref
    except Exception:  # noqa: BLE001
        return ref


def shown(gid: str) -> str:
    return f"board#{gid[1:]}" if re.fullmatch(r"[a-z]\d+", gid) else gid


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="What the model's write guards would refuse on the existing items (read only).")
    ap.add_argument("--line", action="store_true", help="the one line of counts the brief carries")
    ap.add_argument("--json", action="store_true", help="the report as JSON")
    ap.add_argument("--owner-mover", dest="owner_mover", action="store_true", help="list the open items whose mover is the owner while they are in no state of his (no step, no ask)")
    ap.add_argument("--store", help="read the items from this folder (a copy of the store) instead of [paths] store")
    a = ap.parse_args(argv)
    store = Path(a.store).expanduser() if a.store else None
    if store is not None and not store.is_dir():
        print(f"--store {store}: not a folder", file=sys.stderr)
        return 2
    items = load_all(store)
    anchors = None                  # a copy of the store brings its own anchors; without --store the live ones are read
    if store is not None:
        try:
            anchors = json.loads((store / "anchors.json").read_text(encoding="utf-8")) if (store / "anchors.json").is_file() else {}
        except (OSError, ValueError):
            anchors = {}
        anchors = anchors if isinstance(anchors, dict) else {}
    if a.owner_mover:
        ctx = _mg.Ctx(shown=shown)
        ctx.label = _label
        rows = _mg.owner_mover_rows(items, ctx, anchors=anchors)
        if a.json:
            print(json.dumps(rows, indent=1, sort_keys=True, ensure_ascii=False))
        else:
            print(f"{len(rows)} open item(s) with the owner as mover and no step or ask (of {sum(1 for i in items.values() if i.get('status') == 'open')} open; read only)")
            for r in rows:
                print(f"{shown(r['id'])} | {r['subject']} | mover {r['mover']} | state {r['state']} | created by {r['creator']} | {r['gap']}")
        return 0
    rep = _mg.report(items, _mg.Ctx(shown=shown), anchors=anchors, one_mover=bool(_cfg.get("model", "one_mover", default=True)))
    if a.json:
        print(json.dumps({"open": rep.open, "closed": rep.closed, "guards": rep.ids, "flagged": rep.flagged, "defaulted": rep.defaulted}, indent=1, sort_keys=True))
    elif a.line:
        print(_mg.brief_line(rep) or "model guards would refuse nothing on the existing items")
    else:
        print(_mg.full_text(rep, shown))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
