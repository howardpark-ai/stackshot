"""tools/nested_steps_report.py — the dry run of the nested-steps repair: the open items whose long step was split into flat lines of next, and the lists the server's start-up pass puts under their lead-in line. READ ONLY.

A long step once split into one flat line per action, the lead-in that ends with a colon and each item of its list included. Now such a list is one line with its items as indented `- ` lines under it, ticked as one step.
The items split the old way are put into that shape by the SERVER, once at its start, before it serves (migrations._nested_steps_pass; model/nested_repair.py says which lines count and the one guess it makes), through
the server's own save path: the clocks stay, no issue mirror job is made, nobody is told, and a second start finds nothing to do. The server is the only writer; this tool never writes, so it can be run beside the
live server, or on a copy of an instance's store. It lists what the pass would do:

  tools/nested_steps_report.py                     one line per list: `<item>: "Do these in order:" takes 3 lines as sub-lines (stay: …)`, and the count on stderr
  tools/nested_steps_report.py --json              the same rows as JSON
  tools/nested_steps_report.py --config FILE       read the store of this stackshot.toml (a copy of the instance) instead of the instance's own

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
    ap = argparse.ArgumentParser(description="List the lists of split steps the server's start-up pass would put under their lead-in line. Read only.")
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
    rows = _migrations._nested_steps_pass(apply=False)
    if a.json:
        print(json.dumps(rows, indent=1, ensure_ascii=False))
    else:
        for r in rows:
            print(f"{r['item']}: \"{r['lead'][:70]}\" takes {len(r['items'])} line{'s' if len(r['items']) != 1 else ''} as sub-lines: " + "; ".join(x[:50] for x in r["items"])
                  + (f" (stay as lines: {'; '.join(x[:50] for x in r['left'])})" if r["left"] else ""))
    print(f"{len(rows)} list{'s' if len(rows) != 1 else ''} to nest; nothing written (the server nests them at its start)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
