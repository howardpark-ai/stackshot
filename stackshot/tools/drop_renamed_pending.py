"""tools/drop_renamed_pending.py — take named agents out of the project record's pending agents, with an undo file.

A pending agent is one registered through the New session form whose page line is still owed. When sala renamed the session, the old name stayed in its project's pending map and
read as a live agent (sala keeps the old name as an alias). The server settles these itself on every roles build (renamed_agents.sweep: an old name of a session sala lists under
a new name is dropped, or renamed when the new name is registered nowhere); this tool clears the entries that were there before that, by name, and is for a name the sweep cannot know (a session sala no longer lists at all).

    tools/drop_renamed_pending.py --name OLD [--name OLD …]            dry run (the default): per name, every project that holds it as a pending agent, the entry, and what sala says of the
                                                                       name now (an old name of <session>, a current session, or unknown). Writes nothing.
    tools/drop_renamed_pending.py --name OLD … --apply [--run-dir DIR] drops each entry from the record under the record's own lock (safe beside the
                                                                       running server) and keeps the undo file (fsynced, <run-dir>/<pass id>/undo.json, default
                                                                       ~/.local/share/stackshot-runs/pending-run), made from exactly the entries the record
                                                                       drops and written before the record is. The board and projects.json follow within a few minutes.
    tools/drop_renamed_pending.py --undo FILE                          puts every entry the undo file lists back; one a project holds again meanwhile is left as it is.

Only the pending entry of exactly the names given is touched (compared case-folded), in whichever project holds it; the project's page, its `agents:` map, other pending agents and
every other field of the record stay as they are. Running it twice is a no-op. Reads the instance named by STACKSHOT_CONFIG (the default config otherwise).
Exit 0 · 1 for a damaged record or an undo file that does not read · 2 for wrong arguments."""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[2]
DEFAULT_RUN = Path.home() / ".local" / "share" / "stackshot-runs" / "pending-run"


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


def sala_view() -> dict[str, str]:
    """What sala says of each name now, for the report only: {name: the session it is the old name of}, plus {name: ""} for a name that is a current session. {} when sala cannot be read."""
    from stackshot.anchors import anchors
    from stackshot.fleet import renamed_agents
    rows = anchors.sala_rows()
    if rows is None:
        return {}
    out = {str(x["name"]): "" for x in rows if x.get("name")}
    out.update(renamed_agents.renames_of(rows))
    return out


def plan(names: list[str]) -> list[tuple[str, str, str, dict[str, Any]]]:
    """[(project id, project key, name as stored, entry)] for every pending entry holding one of `names` (case-folded). Read only."""
    from stackshot.projects import projects
    want = {n.casefold() for n in names}
    d = projects._read()
    return [(pid, str(d["ids"].get(pid) or pid), n, dict(a)) for pid, m in sorted(d["pending_agents"].items()) for n, a in m.items() if str(n).casefold() in want]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Take named agents out of the project record's pending agents. Dry run unless --apply; --undo puts them back.")
    ap.add_argument("--name", action="append", default=[], help="an agent name to drop (repeat for each); compared case-folded")
    ap.add_argument("--apply", action="store_true", help="write the undo file, then drop the entries")
    ap.add_argument("--undo", metavar="FILE", help="put back the entries an undo file lists")
    ap.add_argument("--run-dir", default=str(DEFAULT_RUN), help="where --apply keeps its undo file (default %(default)s)")
    a = ap.parse_args(argv)
    from stackshot.projects import projects
    if a.undo:
        if a.name or a.apply:
            print("--undo takes no --name or --apply", file=sys.stderr)
            return 2
        try:
            doc = json.loads(Path(a.undo).read_text(encoding="utf-8"))
            entries = [(str(x["project"]), str(x["name"]), dict(x["entry"])) for x in doc["dropped"]]
        except (OSError, ValueError, KeyError, TypeError) as e:
            print(f"undo file {a.undo}: not readable ({e})", file=sys.stderr)
            return 1
        try:
            n = projects.restore_pending(entries)
        except ValueError as e:
            print(f"project record: {e}", file=sys.stderr)
            return 1
        print(f"put back {n} of {len(entries)} pending entr{'y' if len(entries) == 1 else 'ies'} ({len(entries) - n} already held again)")
        return 0
    if not a.name:
        print("give at least one --name", file=sys.stderr)
        return 2
    if a.apply:
        pass_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        undo = Path(a.run_dir).expanduser() / pass_id / "undo.json"

        def keep(dropped: list[tuple[str, str, dict[str, Any]]]) -> None:
            """Called by the record under its lock with exactly the entries about to go, before it writes: the undo file is made from these, never from the earlier read."""
            keys = projects._read()["ids"]
            write_atomic(undo, {"schema": 1, "made": pass_id, "names": a.name,
                                "dropped": [{"project": pid, "key": keys.get(pid, pid), "name": n, "entry": e} for pid, n, e in dropped]})
        try:
            gone = projects.drop_pending_named(a.name, before_write=keep)
        except ValueError as e:
            print(f"project record: {e}", file=sys.stderr)
            return 1
        for pid, n, e in gone:
            print(f"drop: {pid} pending {n}  front={e.get('front')} role={e.get('role')!r} by={e.get('by')!r} at={e.get('at')!r}")
        for n in sorted(n for n in a.name if n.casefold() not in {g[1].casefold() for g in gone}):
            print(f"nothing to drop: {n} is pending in no project")
        if gone:
            print(f"dropped {len(gone)} pending entr{'y' if len(gone) == 1 else 'ies'}; undo file {undo}  (python3 -m stackshot.tools.drop_renamed_pending --undo {undo}, from the checkout)", file=sys.stderr)
        return 0
    try:
        rows = plan(a.name)
    except ValueError as e:
        print(f"project record: {e}", file=sys.stderr)
        return 1
    view = sala_view()
    for pid, key, name, entry in rows:
        says = "sala cannot be read" if not view else ("a current session" if view.get(name) == "" else f"the old name of {view[name]}" if view.get(name) else "not listed by sala")
        print(f"would drop: {key} ({pid}) pending {name}  front={entry.get('front')} role={entry.get('role')!r} by={entry.get('by')!r} at={entry.get('at')!r}  [{says}]")
    for n in sorted(n for n in a.name if n.casefold() not in {r[2].casefold() for r in rows}):
        print(f"nothing to drop: {n} is pending in no project")
    print(f"dry run: {len(rows)} entr{'y' if len(rows) == 1 else 'ies'} would be dropped; nothing written (add --apply)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
