"""tools/migrate_work_to_steps.py — move the old `work` lines of the open items onto the steps of their checklist, with an undo copy.

An item used to carry two lists: its `next` checklist and a separate `work` list of status lines (the update tool's `work` parameter). The update tool now keeps one list: a
`work` write is the status line of the writer's open step (model/work.py), and a step marked done folds away with the others. The readers tolerate a leftover `work` field, so a release
is safe before this runs; this moves the lines that are still stored:

  * a line in progress / assigned / defined becomes the status line of its agent's first open step that has none (the agent is the line's `agent`, else the item's mover, else the first
    session its needs name, else its owner); with no such step a new open step `<agent>: <text>` is added to `next` for that agent, carrying the status;
  * a done line becomes a done step of its own (`<agent>: <text>`, by its agent, at its time, its status done), so the fold of finished steps holds what the Work list held;
  * the `work` field is removed. Nothing else on the item changes: not `updated`, `state_updated`, `confirmed`, nor the activity clock (the lines were a filing edit, and so is this).

Run it AFTER the release is deployed, never before: the code from before it drops the `tag` key (the status line) of a step when it saves the item, so the moved lines would be lost by the next save
of a server still running that code.

Only open items are moved. A closed item that still carries `work` is counted and left as it is (a record is not rewritten); the readers still read it.

    migrate_work_to_steps.py                       dry run (the default; `--dry-run` says it too): one line per item with `work`, what each line becomes, then the counts. Writes nothing.
    migrate_work_to_steps.py --apply [--run-dir D]   writes the undo file first (<run-dir>/<pass id>/undo.json, fsynced, the whole previous text of every item it will touch), then each item
                                                     (a temp file and an atomic rename), then reads each back. A second run finds no `work` field on an open item and writes nothing.
    migrate_work_to_steps.py --undo FILE           puts back every item the undo file lists whose file is still exactly what the pass wrote; one a session has saved since is left as it
                                                     is and named (`kept`); one already back as it was says `same`. Running it twice is a no-op.
    --store DIR                                    read and write this store (a COPY for a rehearsal) instead of the instance's ([paths] store)
    --json                                         the dry run's report as JSON

The server holds its items under an in-process lock and this tool does not take it: apply it at a quiet moment (no session write in the next minutes; an item a session saves between the read and
the rename is overwritten by the plan's copy, and `--undo` names it). Python 3.12 or later, standard library only beside the package.

Exit 0 · 1 when an item did not read, did not verify after its write, or the undo file did not read · 2 for wrong arguments."""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

DEFAULT_RUN = Path.home() / ".local" / "share" / "stackshot-runs" / "work-to-steps"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _dump(obj: Any) -> str:
    """An item file's text as the server writes it (server._save)."""
    return json.dumps(obj, ensure_ascii=False, indent=1)


def _read(p: Path) -> tuple[dict[str, Any] | None, str]:
    text = p.read_text(encoding="utf-8")
    try:
        obj = json.loads(text)
    except ValueError:
        return None, text
    return (obj if isinstance(obj, dict) else None), text


def plan(store: Path, now: float | None = None) -> dict[str, Any]:
    """Read the store and say what the pass would write: {"rows": [...open items to move...], "closed": [gids left alone], "unread": [paths]}. Writes nothing.
    A row: {gid, path, subject, notes, before (text), after (text), lines (count of work lines)}."""
    from stackshot.model import work as _work
    now = time.time() if now is None else now
    rows: list[dict[str, Any]] = []; closed: list[str] = []; unread: list[str] = []
    for p in sorted(store.glob("*/*.json")):
        if p.name.startswith("."):
            continue
        try:
            item, text = _read(p)
        except OSError:
            unread.append(str(p)); continue
        if item is None:
            unread.append(str(p)); continue
        meta = item.get("metadata")
        if not isinstance(meta, dict) or "work" not in meta:
            continue
        gid = f"{p.parent.name}{p.stem}"
        if str(item.get("status") or "") != "open":
            closed.append(gid); continue
        new_meta, notes = _work.fold_legacy(meta, now)
        again, _n = _work.fold_legacy(new_meta, now)
        if again != new_meta:
            raise AssertionError(f"{gid}: the fold is not idempotent")
        after = _dump({**item, "metadata": new_meta})
        rows.append({"gid": gid, "path": str(p), "subject": str(item.get("subject") or ""), "notes": notes, "lines": len(_work.legacy_lines(meta)),
                     "before": text, "after": after})
    return {"rows": rows, "closed": closed, "unread": unread}


def report(pl: dict[str, Any]) -> list[str]:
    out = []
    for r in pl["rows"]:
        out.append(f"{r['gid']}  {r['subject'][:70]}  ({r['lines']} line{'' if r['lines'] == 1 else 's'})")
        out += [f"    {n}" for n in r["notes"]] or ["    (the work field is empty: it is removed)"]
    if pl["closed"]:
        out.append(f"left as they are (closed, a record): {len(pl['closed'])}: {', '.join(pl['closed'][:20])}{' …' if len(pl['closed']) > 20 else ''}")
    if pl["unread"]:
        out.append(f"did not read: {', '.join(pl['unread'])}")
    return out


def _fsync_write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def apply(store: Path, run_dir: Path, now: float | None = None) -> tuple[int, list[str], Path | None]:
    """Write the undo file, then the items. → (exit code, lines, the undo file or None when nothing was to be written)."""
    pl = plan(store, now)
    lines = report(pl)
    if pl["unread"]:
        return 1, lines + ["nothing written: an item did not read"], None
    if not pl["rows"]:
        return 0, lines + ["nothing to move: no open item carries a `work` field"], None
    run_dir.mkdir(parents=True, exist_ok=True)
    lock = os.open(str(run_dir / ".lock"), os.O_CREAT | os.O_RDWR, 0o600)      # a second pass waits for the first; systemd-tmpfiles ageing honors a held lock
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base = run_dir / stamp; n = 1
        while base.exists():                      # two passes in one second keep two undo files
            n += 1; base = run_dir / f"{stamp}-{n}"
        base.mkdir(parents=True)
        undo = base / "undo.json"
        meta = {"tool": "migrate_work_to_steps", "store": str(store), "at": stamp,
                "items": {r["gid"]: {"path": r["path"], "before": r["before"], "before_sha": _sha(r["before"]), "after_sha": _sha(r["after"])} for r in pl["rows"]}}
        _fsync_write(undo, json.dumps(meta, indent=1, ensure_ascii=False) + "\n")           # the previous text of every item, before the first write
        bad = 0
        for r in pl["rows"]:
            p = Path(r["path"])
            try:
                if p.read_text(encoding="utf-8") != r["before"]:
                    lines.append(f"{r['gid']}: changed since it was read; not written (run the pass again)"); bad += 1
                    continue
                _fsync_write(p, r["after"])
                item, _t = _read(p)
                if item is None or "work" in (item.get("metadata") or {}):
                    lines.append(f"{r['gid']}: did not verify after its write"); bad += 1
                else:
                    lines.append(f"{r['gid']}: moved")
            except OSError as e:
                lines.append(f"{r['gid']}: {e}"); bad += 1
        lines.append(f"wrote {len(pl['rows']) - bad} of {len(pl['rows'])} items; undo file {undo}")
        return (1 if bad else 0), lines, undo
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        os.close(lock)


def undo(path: Path) -> tuple[int, list[str]]:
    """Put back the items the undo file lists, each only if its file is still what the pass wrote."""
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
        items = meta["items"]
    except (OSError, ValueError, KeyError) as e:
        return 1, [f"undo file {path}: not readable ({e})"]
    out = []; bad = 0
    for gid, e in sorted(items.items()):
        p = Path(e["path"])
        try:
            cur = p.read_text(encoding="utf-8")
        except OSError as ex:
            out.append(f"{gid}: {ex}"); bad += 1
            continue
        sha = _sha(cur)
        if sha == e["before_sha"]:
            out.append(f"{gid}: same (already as it was)")
        elif sha == e["after_sha"]:
            _fsync_write(p, e["before"]); out.append(f"{gid}: put back")
        else:
            out.append(f"{gid}: kept (saved since the pass; left as it is)")
    return (1 if bad else 0), out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Move the old `work` lines of the open items onto their steps. Dry run unless --apply; --undo puts the previous items back.")
    ap.add_argument("--apply", action="store_true", help="write the undo file, then the items")
    ap.add_argument("--dry-run", action="store_true", help="the default: report and write nothing")
    ap.add_argument("--undo", metavar="FILE", help="put back the items an undo file lists")
    ap.add_argument("--run-dir", default=str(DEFAULT_RUN), help="where --apply keeps its undo file (default %(default)s)")
    ap.add_argument("--store", metavar="DIR", help="read and write this store instead of the instance's")
    ap.add_argument("--json", action="store_true", help="the dry run's report as JSON")
    ap.add_argument("--now", type=float, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.apply and a.dry_run:
        print("--apply and --dry-run exclude each other", file=sys.stderr)
        return 2
    if a.undo and (a.apply or a.dry_run or a.json):
        print("--undo takes only --run-dir/--store", file=sys.stderr)
        return 2
    if a.undo:
        code, lines = undo(Path(a.undo))
        print("\n".join(lines), file=sys.stderr if code else sys.stdout)
        return code
    if a.store:
        store = Path(a.store).expanduser()
    else:
        from stackshot.core import config as _cfg
        store = Path(_cfg.path("paths", "store"))
    if not store.is_dir():
        print(f"the store {store} is not a folder", file=sys.stderr)
        return 1
    if a.apply:
        code, lines, _u = apply(store, Path(a.run_dir).expanduser(), a.now)
        print("\n".join(lines), file=sys.stderr if code else sys.stdout)
        return code
    pl = plan(store, a.now)
    if a.json:
        print(json.dumps({"open_items_to_move": [{k: v for k, v in r.items() if k not in ("before", "after")} for r in pl["rows"]], "closed_left_alone": pl["closed"], "unread": pl["unread"]}, indent=1, ensure_ascii=False))
    else:
        print("\n".join(report(pl)))
        print(f"dry run: {len(pl['rows'])} open item{'' if len(pl['rows']) == 1 else 's'} would be moved, {len(pl['closed'])} closed one{'' if len(pl['closed']) == 1 else 's'} left as they are; nothing written (add --apply)")
    return 1 if pl["unread"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
