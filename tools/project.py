#!/usr/bin/env python3
"""tools/project.py — the verbs that write a project's identity (project_verbs.py): the record first, then the page's mirror lines.

    tools/project.py create NAME --scope S [--page KEY|LINK] [--make-page] [--title T]    a new project; with no --page it has no page and none is made
    tools/project.py adopt PAGE [--name N] [--scope S]                                    a project from a page that never had one: reads the page once, writes the entry (how: adopted); the page is a pointer after
    tools/project.py rename PROJECT NEW_NAME                                              the name changes, the id stays, the old name goes to former_names
    tools/project.py move-page PROJECT NEW_KEY [--phase plan|copy|stub ...] [--why W]    runs rename_page.py (copy, then stub), then the record: the pointer is the new key, the old key a former key
    tools/project.py archive PROJECT [--why W]                                            status archived (by, at, how); the page's status: line follows
    tools/project.py reopen PROJECT                                                       status active again
    tools/project.py agent-add PROJECT NAME (--front | --back) --mandate "one line"        the agent on the project's agents map, then the page's agents: block
    tools/project.py agent-mandate PROJECT NAME --mandate "one line"                      the mandate line of an agent already on the map changed (record first, then the page's agents: block)
    tools/project.py agent-retire PROJECT NAME                                            the agent off the map; the archive rule is applied (no agent and no open item archives)
    tools/project.py agent-rename PROJECT OLD NEW                                         the entry renamed in place
    tools/project.py mirror PROJECT [--make-page]                                         writes the page's three mirror lines (display-name:, agents:, status:) from the record again
    tools/project.py show PROJECT                                                         the project's entry and what the registry reads of it

PROJECT is an id (prj_<8 hex>), a page key, a bare slug, the project's name or a former name. A sub-page is never a project: its key names the top-level project that owns it for rename and the agent
verbs, and is refused (400) by archive, reopen and move-page, which act on the whole project; the id of a sub-page is refused by every verb. Every verb is one atomic change of the record under the record's own lock (safe beside the running
server), then a write of the page's mirror through the instance's page store when the project has a page there; a mirror that fails is reported and the record is right already.
A page edit made by hand to one of the three mirrored lines is overwritten by the next mirror write.

    --dry-run             what would be written (the new entry, the page change in lines), and nothing is written to the record or the page
    --by LABEL            who the record names as the actor (default: `cli`)
    --json                the verb's whole answer as JSON
    --store DIR  --brain DIR  --state DIR     read and write those instead of the instance's: a COPY of the store and the pages for a dry run or a rehearsal (--state keeps the lock and
                                              temp files out of the live state dir). move-page does not run rename_page.py under these options, which read the instance's own config.

Exit 0 done (or nothing to do) · 1 refused or not done, the reason on stderr · 2 wrong arguments. A mirror that failed is exit 0 with the failure on stderr and in the answer: the record is right."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="project.py", description=__doc__.split("\n")[0])
    ap.add_argument("--store", metavar="DIR"); ap.add_argument("--brain", metavar="DIR"); ap.add_argument("--state", metavar="DIR")
    ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--json", action="store_true"); ap.add_argument("--by", default="cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create"); c.add_argument("name"); c.add_argument("--scope", required=True); c.add_argument("--page", default=""); c.add_argument("--make-page", action="store_true"); c.add_argument("--title", default="")
    ad = sub.add_parser("adopt"); ad.add_argument("page"); ad.add_argument("--name", default=""); ad.add_argument("--scope", default="")
    r = sub.add_parser("rename"); r.add_argument("project"); r.add_argument("new_name")
    m = sub.add_parser("move-page"); m.add_argument("project"); m.add_argument("new_key"); m.add_argument("--phase", action="append", choices=["plan", "copy", "stub"]); m.add_argument("--why", default="")
    m.add_argument("--parent", default=""); m.add_argument("--no-agents-ok", action="store_true")
    a = sub.add_parser("archive"); a.add_argument("project"); a.add_argument("--why", default="")
    o = sub.add_parser("reopen"); o.add_argument("project")
    aa = sub.add_parser("agent-add"); aa.add_argument("project"); aa.add_argument("name"); g = aa.add_mutually_exclusive_group(required=True)
    g.add_argument("--front", action="store_true"); g.add_argument("--back", action="store_true"); aa.add_argument("--mandate", required=True)
    am = sub.add_parser("agent-mandate"); am.add_argument("project"); am.add_argument("name"); am.add_argument("--mandate", required=True)
    ar = sub.add_parser("agent-retire"); ar.add_argument("project"); ar.add_argument("name")
    an = sub.add_parser("agent-rename"); an.add_argument("project"); an.add_argument("old"); an.add_argument("new")
    mi = sub.add_parser("mirror"); mi.add_argument("project"); mi.add_argument("--make-page", action="store_true")
    sh = sub.add_parser("show"); sh.add_argument("project")
    return ap


def _copy_runner(args: list[str]) -> tuple[int, str]:
    if args and args[0] == "plan":
        return 0, "plan not run: --store/--brain/--state point at a copy, and rename_page.py reads the instance's own config"
    return 1, "rename_page.py is not run under --store/--brain/--state: it reads the instance's own config, not the copy"


def run(a: argparse.Namespace) -> dict:
    import project_verbs as pv
    import page_debt
    io = None
    if a.cmd in ("create", "adopt", "rename", "archive", "reopen", "agent-add", "agent-mandate", "agent-retire", "agent-rename", "mirror", "move-page"):
        io = page_debt.page_io()
    kw = {"by": a.by, "io": io}
    dry = {"dry": a.dry_run}
    if a.cmd == "create":
        return pv.create(a.name, a.scope, a.page, make_page=a.make_page, title=a.title, **kw, **dry)
    if a.cmd == "adopt":
        return pv.adopt(a.page, name=a.name, scope=a.scope, **kw, **dry)
    if a.cmd == "rename":
        return pv.rename(a.project, a.new_name, **kw, **dry)
    if a.cmd == "move-page":
        runner = _copy_runner if (a.store or a.brain or a.state) else None
        return pv.move_page(a.project, a.new_key, phases=tuple(a.phase) if a.phase else ("copy", "stub"), why=a.why, parent=a.parent, no_agents_ok=a.no_agents_ok, runner=runner, **kw, **dry)
    if a.cmd == "archive":
        return pv.archive(a.project, why=a.why, **kw, **dry)
    if a.cmd == "reopen":
        return pv.reopen(a.project, **kw, **dry)
    if a.cmd == "agent-add":
        return pv.agent_add(a.project, a.name, a.front, a.mandate, **kw, **dry)
    if a.cmd == "agent-mandate":
        return pv.agent_mandate(a.project, a.name, a.mandate, **kw, **dry)
    if a.cmd == "agent-retire":
        res = pv.agent_retire(a.project, a.name, **kw, **dry)
        if not a.dry_run and res["result"] in ("line removed", "dropped"):
            import datetime as dt
            import config as _cfg
            import project_archive as arc
            import projects as prj
            pid = res["project"]
            left = len(prj._pending_all().get(pid, {}))
            today = dt.datetime.now(_cfg.tz()).strftime("%Y-%m-%d")
            res["archive"] = arc.after_retire(io, {"id": pid, "key": res["key"] or pid}, None, today, a.by, left, prj.with_made(prj.registry()))
        return res
    if a.cmd == "agent-rename":
        return pv.agent_rename(a.project, a.old, a.new, **kw, **dry)
    if a.cmd == "mirror":
        pid = pv.one(a.project)
        if not pid:
            raise pv.VerbError(404, f"no project {a.project!r}")
        return {"project": pid["id"], "mirror": pv.mirror(pid["id"], io, make_page=a.make_page, dry=a.dry_run)}
    if a.cmd == "show":
        import project_registry as pr
        pid = pv.pid_of(a.project)
        v = pr.resolve(pid) if pid else None
        rec = pv.one(pid) if pid else None
        if v is None and rec is None:
            raise pv.VerbError(404, f"no project {a.project!r}")
        return {"entry": v, "record": rec}
    raise pv.VerbError(400, f"unknown command {a.cmd}")


def main(argv: list[str]) -> int:
    ap = _parser()
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    import config as _cfg
    for key, val in (("store", a.store), ("brain", a.brain), ("state", a.state)):
        if val:
            _cfg.CFG.setdefault("paths", {})[key] = str(Path(val).expanduser())
    import project_verbs as pv
    try:
        res = run(a)
    except pv.VerbError as e:
        print(f"project {a.cmd}: [{e.status}] {e.message}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"project {a.cmd}: the record cannot be read or written: {e}", file=sys.stderr)
        return 1
    m = res.get("mirror") or {}
    if res.get("warning"):
        print(f"project {a.cmd}: {res['warning']}", file=sys.stderr)
    if m.get("state") == "failed":
        print(f"project {a.cmd}: the record is right, but the page was not written: {m.get('note')}", file=sys.stderr)
    if a.json:
        print(json.dumps(res, indent=1, ensure_ascii=False, default=str))
    elif a.cmd == "show":
        v, rec = res.get("entry") or {}, res.get("record") or {}
        print(f"{v.get('id') or rec.get('id')}  name {v.get('name') or rec.get('keeper') or '-'}  status {v.get('status') or rec.get('status') or '-'}  scope {v.get('scope') or rec.get('scope') or '-'}")
        print(f"page {v.get('page') or rec.get('key') or '-'}" + (f"  (found by {v['via']})" if v.get("via") else ""))
        for n, ag in (v.get("agents") or rec.get("agents") or {}).items():
            print(f"  {'front' if ag.get('front') else 'back '}  {n}: {ag.get('mandate_line', '')}")
    else:
        head = f"{'dry run: ' if res.get('dry') else ''}{a.cmd} {res.get('project') or ''}".strip()
        if "changed" in res:
            head += " — " + ("changed" if res["changed"] else "nothing to change")
        if m:
            head += f"; page {m.get('key') or '-'}: {m.get('state')}" + (f" ({m['note']})" if m.get("note") else "")
        print(head)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
