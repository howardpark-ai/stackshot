"""tools/archive_empty_projects.py — which projects have no agent and no open item, and so should be archived (project_archive.py); dry run unless --apply.

The retire that sala sends archives a project at the moment its last agent goes (or, with open items left, the ten-minute sweep does when the last item
leaves). This finds the projects that rule covers but that nothing archived: a project whose last agent was retired before the rule existed, one whose status
write failed. It reads each top-level project page through the page store (gbrain, or the pages checkout), so it sees the page as it is, not as the registry
last read it.

A project is listed when it is `type: project`, not a sub-page, not retired, done or moved already, and its page HAS an `agents:` key with no agent in it (a
page that never had an agents map is not a candidate: it was never staffed; `--all` lists those too), no agent is pending for it in the project record, and:

  archive    it has no open item (its own, its sub-pages', or a page that names it as its hub; on hold counts as open): its page's `status:` should become archived
  wait       it has open items: it stays active until none is left (with --apply it goes on the sweep's wait list, <state>/archive-wait.json)

  tools/archive_empty_projects.py              the candidates, one line each, then the counts; changes nothing
  tools/archive_empty_projects.py --json       {"archive": [...], "wait": [...]} with the open item ids
  tools/archive_empty_projects.py --apply      archive the "archive" ones (one put with the revision read, a read back, a timeline line each) and put the "wait" ones on the wait list
  tools/archive_empty_projects.py --all        also the pages that have no `agents:` key at all
  tools/archive_empty_projects.py KEY ...      only these project pages (full keys, e.g. projects/foo)

Stdlib plus the repo's modules, Python 3.11+. Exit 0; 1 when --apply could not write a page."""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import argparse
import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
from stackshot.core import config as _cfg  # noqa: E402
from stackshot.router import page_debt as _page_debt  # noqa: E402
from stackshot.projects import pages as _pages  # noqa: E402
from stackshot.projects import project_archive as _arc  # noqa: E402
from stackshot.projects import project_registry as _pr  # noqa: E402
from stackshot.projects import projects as _prj  # noqa: E402


def candidates(io, reg: dict, only: list[str], every: bool) -> tuple[list[dict], list[dict], list[str]]:
    """(the "archive" rows, the "wait" rows, the pages that could not be read), each row {"key", "items"}."""
    pending = _prj._pending_all()
    keys = sorted(k for k, e in reg.items() if isinstance(e, dict) and str(e.get("type") or "").strip().lower() == "project"
                  and not _prj.is_sub_page(k, reg, e) and (not only or k in only))
    items = _arc.open_items_by_key(keys, reg)
    arch, wait, unread = [], [], []
    for k in keys:
        view = _pr.resolve(k)
        if view is not None:                    # the project has an entry in the record: the record says whether it has an agent, not the page's copy
            word, _why = _arc.verdict_record(view, len(pending.get(view["id"], {})), items.get(k, []), need_map=not every)
        else:
            content, rev = io.get(k)
            if content is None or not rev:
                unread.append(k); continue
            word, _why = _arc.verdict(content, len(pending.get((reg[k] or {}).get("id") or "", {})), items.get(k, []), need_map=not every)
        if word == "archive": arch.append({"key": k, "items": []})
        elif word == "wait": wait.append({"key": k, "items": items.get(k, [])})
    return arch, wait, unread


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("keys", nargs="*", help="only these project pages")
    ap.add_argument("--apply", action="store_true", help="archive the projects that qualify (default: list only)")
    ap.add_argument("--all", action="store_true", help="also pages with no agents: key")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    reg = _prj.registry()
    io = _page_debt.page_io()
    arch, wait, unread = candidates(io, reg, a.keys, a.all)
    bad = 0
    today = datetime.datetime.now(_cfg.tz()).strftime("%Y-%m-%d")
    results: dict[str, str] = {}
    if a.apply:
        for r in arch:
            done, note = _arc.archive_page(io, r["key"], today, "archive_empty_projects", "it has no agent and no open item")
            results[r["key"]] = "archived" + (f" ({note})" if note else "") if done else f"NOT archived: {note}"
            bad += 0 if done else 1
        if wait:
            _arc._change_wait(add={r["key"]: {"since": today, "by": "archive_empty_projects"} for r in wait})
            for r in wait: results[r["key"]] = "on the wait list"
    if a.json:
        print(json.dumps({"archive": arch, "wait": wait, "unread": unread, "applied": results}, indent=1)); return 1 if bad else 0
    for r in arch: print(f"archive  {r['key']}" + (f"  → {results[r['key']]}" if r["key"] in results else ""))
    for r in wait: print(f"wait     {r['key']}  open items: {', '.join(r['items'][:8])}{' …' if len(r['items']) > 8 else ''}" + (f"  → {results[r['key']]}" if r["key"] in results else ""))
    for k in unread: print(f"unread   {k}  (the page store did not give the page)")
    print(f"{len(arch)} to archive, {len(wait)} waiting for open items, {len(unread)} unread" + ("" if a.apply else "  (dry run: --apply writes)"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
