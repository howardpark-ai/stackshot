"""tools/close_marks_backfill.py — the report of the close-marks backfill: the closed items that still show an open next step, and the marks the server's start-up pass gives them. READ ONLY.

Until an earlier change a close marked nothing: an item closed with steps still open kept them open in its checklist. Since then a close marks them, by the closer: done when the
outcome is done, dropped for any other outcome. The items closed before are marked by the SERVER, once at its start, before it serves (migrations._close_marks_pass): every closed item whose
checklist still has an open step gets those steps marked, `done` when its outcome is done, `dropped` otherwise (dropped, superseded, unrecorded, none), by "stackshot (backfill)" at the
time the item closed (its state_updated, else updated), through the server's own save path with no GitHub mirror. The server is the only writer; this tool never writes, so it can be run beside
the live server. It lists what the pass would mark (and, once the server has started with the change, finds nothing):

  tools/close_marks_backfill.py                    one line per closed item with an open step: `(done): would mark 2 steps done: 1. text; 3. text`, and a count on stderr
  tools/close_marks_backfill.py --json             the same rows as JSON
  tools/close_marks_backfill.py --config FILE      read the store of this stackshot.toml (a copy of the instance) instead of the instance's own

It imports server.py against the config (STACKSHOT_CONFIG) and asks the same function the start-up pass runs, with apply=False. Exit 0 · 2 for a config or store that is not there."""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="List the closed items with an open step and the marks the server's start-up pass gives them. Read only.")
    ap.add_argument("--json", action="store_true", help="the rows as JSON")
    ap.add_argument("--config", help="a stackshot.toml of a copy of the instance, instead of the instance's own")
    a = ap.parse_args(argv)
    if a.config:
        cfg = Path(a.config).expanduser()
        if not cfg.is_file():
            print(f"--config {cfg}: not a file", file=sys.stderr)
            return 2
        os.environ["STACKSHOT_CONFIG"] = str(cfg)
    import logging
    logging.disable(logging.INFO)
    from stackshot.web import server  # noqa: F401  — the migrations are imported through the server, as at its start
    from stackshot.service import migrations as _migrations  # noqa: PLC0415
    from stackshot.core import store as _store  # noqa: PLC0415
    if not _store.STORE.is_dir():
        print(f"store {_store.STORE}: not a folder", file=sys.stderr)
        return 2
    rows = _migrations._close_marks_pass(apply=False)
    if a.json:
        print(json.dumps([{**r, "steps": [{"position": n, "text": t} for n, t in r["steps"]]} for r in rows], indent=1, ensure_ascii=False))
    else:
        for r in rows:
            print(f"{r['item']} ({r['outcome'] or 'no outcome'}): would mark {len(r['steps'])} step{'s' if len(r['steps']) != 1 else ''} {r['status']}: "
                  + "; ".join(f"{n}. {t[:70]}" for n, t in r["steps"]))
    print(f"{len(rows)} closed item{'s' if len(rows) != 1 else ''} with open steps; nothing written (the server marks them at its start)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
