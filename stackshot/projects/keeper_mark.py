"""keeper_mark.py — the one-time pass that puts the keeper mark on every live project of the project record (the migration of a project's keeper from a name line to a mark on one of its agents).

  stackshot keeper-mark                                  a dry run (the default): what the pass would do, every session whose role or notices would move; writes nothing at all
  stackshot keeper-mark --apply [--accept-role-loss S …]   do it: the record only, in one atomic write, with an undo file (the format `project.py restore --undo` takes back)

What it does to each project entry of the record:
  an archived project                          left as it is
  a project that is marked already             left as it is (the record's flag, or the page's own `keeper:` line): a mark is never replaced
  a project that lists agents                  `keeper: true` goes on its builder (the first background agent whose mandate builds: keeper.successor), else on its -main agent, else on its
                                               first front agent: the agent the router and the telling already hand its items to when nothing is marked, so for a project with a front agent no item or router pass changes hands
  a one-session project (no agents listed, a   its session is listed as its one front agent, keeps its name, and is marked
  name-line session)
  the old name line                            the entry's `name` is the project's name, the prefix of its agents' names, and stays; it is cleared only when it serves nothing (no agent of the
                                               project is it or starts with it, no page is filed under the project that could use it, and the page's own line agrees), and only after the mark replaced it

The pass writes the project record and nothing else: no page (the page mirror stays off; pages in a brain that is not stackshot's own are never written), no roles file, no registry. The dry run reads the record, the
registry file and sala's list of running sessions, and writes no file (it takes no lock either). Its summary says, per project, the agent marked and why, the name cleared, and then what moves for sessions:
the roles.json entries that change (anchors.file_roles read before and after), the sessions whose entry sala's load_roles would count differently ("sessions that lose a role"), the running old name-line sessions that
would be off the map, the projects whose gating class flips (a one-session project's session becomes a front agent), the projects whose items or router passes go to a different agent (a project with background agents only, a one-session project), the notice addresses that change, and the marked agents that are not builders.

`--apply` refuses (exit 1, nothing written) while a session would lose a role, unless each such session is named with `--accept-role-loss`: the usual remedy is to list that session as a front agent of its project first.
It is idempotent: a second run finds every project marked and writes nothing. The apply plans again inside the record's lock and reports that plan (the one written), saying so when it differs from the plan read before the lock;
its undo takes back the whole file and is refused once the record was written after the change (the printed hint names `restore --from-git` for that case).

    stackshot keeper-mark [--apply] [--accept-role-loss SESSION …] [--run-dir DIR] [--by WHO] [--json]"""
from __future__ import annotations

import os as _os
import sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]
import argparse
import copy
import json
import re
import sys
from typing import Any

from stackshot.projects import keeper as _kp
from stackshot.projects import project_registry as pr
from stackshot.projects import project_verbs as pv
from stackshot.projects import projects as prj

BY = "keeper-mark"
MANDATE = "the project's one session: talks to the user and keeps the project's pages current"      # the mandate line of a one-session project's session, when it is listed as its one agent
SHOW = 60                                                                                              # lines of one kind in the text of a summary; the structured answer holds them all


# ----------------------------------------------------------------------------- what one project gets
def _name_line(e: dict, row: dict | None) -> str:
    """The session the project's old name line names: the entry's `name`, else the page's own `display-name:` line ("" when none)."""
    if str(e.get("name") or "").strip():
        return str(e["name"]).strip()
    s, rl = _kp.name_line(row or {})
    return str(s) if s and rl in prj._NAME_ROLES else ""


def _stale(name: str, ag: dict, ents: dict, e: dict, key: str, row: dict | None, raw: dict | None = None) -> bool:
    """Does the entry's `name` serve nothing once the mark replaced it as the keeper: no agent of the project is it or starts with it, no other project is its hub or has its page below it (their agents
    may be named from it), no page of the registry `raw` (a sub-page with no entry of its own too) is below the project or has it as its hub, and the page's own name line, when there is one, says the same?"""
    n = name.casefold()
    if any(str(a).casefold() == n or str(a).casefold().startswith(n + "-") for a in ag):
        return False
    for o in ents.values():
        if o is e:
            continue
        ok = pr.page_key(o)
        if pr._norm_key(o.get("hub")) == key or (ok and ok.startswith(key + "/")):
            return False
    for k2, o2 in (raw or {}).items():
        if k2 != key and isinstance(o2, dict) and (k2.startswith(key + "/") or pr._norm_key(o2.get("hub")) == key):
            return False
    s, rl = _kp.name_line(row or {})
    return not (s and rl in prj._NAME_ROLES and str(s).casefold() != n)


def _decide(pid: str, e: dict, ents: dict, raw: dict, taken: set, by: str, now: str) -> dict:
    """What the pass does to the entry `e` (changed in place when it marks). → the project's line of the plan: {id, key, action, ...}; action is `archived`, `marked` (already), `skip` (with `why`), `mark`
    (the agent, `kind` builder or main, `why`) or `promote` (a one-session project's session listed and marked)."""
    key = pr.page_key(e)
    out: dict = {"id": pid, "key": key, "name": str(e.get("name") or ""), "action": "", "agent": "", "kind": "", "why": "", "cleared": "", "front": False}
    if e.get("status") == "archived":
        return {**out, "action": "archived", "why": "an archived project is left alone"}
    row = raw.get(key) if key else None
    if not isinstance(row, dict):
        return {**out, "action": "skip", "why": "the project has no page row in the registry (a mark on a project with no page is not read)"}
    ag = e["agents"] if isinstance(e.get("agents"), dict) else pv.seed_agents(row)      # an entry with no agents field reads the page's own map, as the verbs do
    held = _kp.effective_mark(ag, row)
    if held:
        return {**out, "action": "marked", "agent": held, "why": "already marked (" + ("the record's flag" if _kp.record_mark(ag)[0] else "the page's `keeper:` line") + "): left as it is"}
    if ag:
        target = _kp.successor(ag)
        if not target:
            return {**out, "action": "skip", "why": "it lists agents but none can take the mark (no builder and no front agent): mark one with `project.py keeper`"}
        front = bool(ag[target].get("front", True))
        main = next((n for n in ag if str(n).endswith("-main") and ag[n].get("front", True)), "")
        kind = "builder" if not front else "main"
        why = ("its builder (the first background agent whose mandate builds)" if not front else
               ("no builder: its -main agent" if target == main else "no builder and no -main agent: its first front agent"))
        agents = copy.deepcopy(ag)
        pv._set_mark(agents, target)
        e["agents"] = agents
        out.update(action="mark", agent=target, kind=kind, why=why, front=front)
    else:
        who = _name_line(e, row)
        if not who:
            return {**out, "action": "skip", "why": "it lists no agent and its page names no session: nothing to list or mark"}
        if "agents" in e or e.get("former_agents"):       # agents were listed once (an empty map, or every agent retired): the name is the project's name and the prefix of those agents, not a live session
            return {**out, "action": "skip", "why": f"it lists no agent now but had some (an empty or fully retired agents map), so its name {who} is the project's name, not a session: list the session by hand (`project.py agent-add`) and mark it"}
        if who.startswith("cse_") or re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", who):
            return {**out, "action": "skip", "why": f"its name line {who} is a session id, not a name: list its session by hand (`project.py agent-add`) and mark it"}
        if who.casefold() in taken:
            return {**out, "action": "skip", "why": f"its name line {who} is an agent of another project already: list the session where it belongs, then mark it"}
        taken.add(who.casefold())                           # at once: the next project of this pass with the same name is refused, not promoted a second time
        e["agents"] = {who: {"front": True, "mandate_line": MANDATE, "by": by, "at": now, _kp.KEY: True}}
        out.update(action="promote", agent=who, kind="one-session", front=True, why="a one-session project: its name-line session is listed as its one front agent, keeps its name and is marked")
        ag = e["agents"]
    nm = str(e.get("name") or "")
    if nm and _stale(nm, ag, ents, e, key, row, raw):
        e.pop("name", None)
        out["cleared"] = nm
    return out


def build(ents: dict, raw: dict, *, by: str = BY, now: str = "") -> tuple[dict, list[dict]]:
    """(the entries as the pass leaves them, one plan line per entry) for the entries `ents` and the page registry `raw` (the pages alone, `projects.registry_raw`). `ents` is not changed. The entries are read in the
    order of their page keys, so two runs read the same record the same way."""
    new = copy.deepcopy(ents)
    taken: set = set()
    for e in new.values():          # every agent name some project lists, as the readers see the lists: the record's map, else the project's own page's map (an entry with no agents field)
        k = pr.page_key(e)
        taken.update(str(n).casefold() for n in (e["agents"] if isinstance(e.get("agents"), dict) else pv.seed_agents(raw.get(k) if k else None)))
    rows = [_decide(pid, e, new, raw, taken, by, now) for pid, e in sorted(new.items(), key=lambda kv: (pr.page_key(kv[1]), kv[0]))]
    return new, rows


# ----------------------------------------------------------------------------- what the change moves for sessions
def _sala_view(r: dict | None) -> tuple | None:
    """What sala's load_roles reads of a roles.json entry: (role, project) for a front or back entry that is not retired, else nothing (the old `keeper` role and a retired entry are not counted)."""
    if isinstance(r, dict) and r.get("role") in ("front", "back") and r.get("retired") is not True:
        return (r["role"], r.get("project") or None)
    return None


def _shown(r: dict | None) -> str:
    if not r:
        return "none"
    return f"{r.get('role')}" + (" (retired)" if r.get("retired") else "") + (" +keeper" if r.get("keeper") else "") + (f" of {r['project']}" if r.get("project") else "")


def _class(key: str, reg: dict) -> str:
    from stackshot.anchors import anchors as anc
    if not anc.has_front(key, reg):
        return "one-session" if not (reg.get(key) or {}).get("agents") else "background agents only"
    return "front agents"


def _recipient(key: str, reg: dict) -> str:
    """Who an item's notices fall to for the project, read from `reg`: the same walk the telling's page keeper makes (a marked agent; else the stand-in of a project that lists a user-facing agent; else the
    name line of the pilot root, of the hub, of the top page), written here from the anchors and the router's own readers so this domain module imports nothing from the service layer."""
    from stackshot.anchors import anchors as anc
    from stackshot.router import router_live as rl
    try:
        marked = rl.marked_in(key, reg)
        if marked:
            return str(marked)
        if anc.has_front(key, reg):
            return str(rl.stand_in(key, reg) or "")
        root = anc.pilot_root(key)
        return str((anc.name_line(root, reg) if root else "") or anc.name_line(anc.hub_of(key, reg), reg) or anc.name_line("/".join(str(key).split("/")[:2]), reg) or "")
    except Exception:  # noqa: BLE001
        return rl.stand_in_of(key, reg)


def effects(raw: dict, before: dict, after: dict, rows: list[dict], live: set | None = None) -> dict:
    """What the change from the entries `before` to `after` moves, read from the registry the entries are laid over (`raw`) before and after, by the code the server runs:
      roles          each roles.json entry that differs (anchors.file_roles), with what sala's load_roles would count before and after, and `lost` when it counted the session and no longer does
      lose           the sessions that lose a role (counted before, not after)
      off_map        the running old name-line sessions (`live`; every session an old name line names when sala could not be read) that no page of any project lists after: they would show off the map
      gating         the projects whose class flips (one-session, front agents, background agents only)
      notices        the projects whose notice address (anchors.notice_name), item keeper (telling.page_keeper) or router stand-in differs before and after; `hands` is true when the keeper or the stand-in is another agent
      derived_moved  the marks that are not the keeper the project derived before (so its notices change hands)
      non_builders   the marked agents that are not builders (a front agent: held notices reach it later than they reached a builder)"""
    from stackshot.anchors import anchors as anc
    from stackshot.router import router_live as rl
    reg0, reg1 = pr.apply(raw, before), pr.apply(raw, after)
    r0, r1 = anc.file_roles(reg0), anc.file_roles(reg1)
    roles = []
    for n in sorted(set(r0) | set(r1)):
        a, b = r0.get(n), r1.get(n)
        if (_shown(a), (a or {}).get("keeper")) == (_shown(b), (b or {}).get("keeper")):
            continue
        sa, sb = _sala_view(a), _sala_view(b)
        roles.append({"session": n, "from": _shown(a), "to": _shown(b), "sala_from": sa, "sala_to": sb, "lost": sa is not None and sb is None, "lane_changes": sa != sb})
    lose = [x["session"] for x in roles if x["lost"]]
    changed = [r for r in rows if r["action"] in ("mark", "promote")]
    old_names = {s for s in ({str(e.get("session") or "") for e in reg0.values() if isinstance(e, dict)}) if s}
    running = set(old_names) if live is None else {n for n in live if n}
    off = []
    for s in sorted(running):
        h0, h1 = anc.session_hubs(s, reg0, {}), anc.session_hubs(s, reg1, {})
        if h0 and not h1:
            off.append({"session": s, "was_on": h0})
    gating, notices, derived_moved = [], [], []
    for r in changed:
        k = r["key"]
        c0, c1 = _class(k, reg0), _class(k, reg1)
        if c0 != c1:
            gating.append({"key": k, "from": c0, "to": c1, "agent": r["agent"]})
        n0, n1 = anc.notice_name(k, reg0, [k]), anc.notice_name(k, reg1, [k])
        p0, p1 = _recipient(k, reg0), _recipient(k, reg1)
        s0, s1 = rl.stand_in_of(k, reg0), rl.stand_in_of(k, reg1)
        if (n0, p0, s0) != (n1, p1, s1):
            notices.append({"key": k, "notice_name": [n0, n1], "item_keeper": [p0, p1], "stand_in": [s0, s1], "hands": (p0, s0) != (p1, s1)})
        f0 = _kp.fields(k, reg0)
        if f0.get("keeper_source") == "derived" and f0.get("keeper_agent") != r["agent"]:
            derived_moved.append({"key": k, "derived": f0.get("keeper_agent"), "marked": r["agent"]})
    non_builders = [{"key": r["key"], "agent": r["agent"]} for r in changed if r["front"]]
    return {"roles": roles, "lose": lose, "off_map": off, "off_map_assumed": live is None, "gating": gating, "notices": notices, "derived_moved": derived_moved, "non_builders": non_builders}


def sub_page_lines(raw: dict, rows: list[dict], after: dict | None = None) -> dict:
    """The sub-pages of the projects the pass marks whose own `display-name:` line still names the project's old name line (a session the mark replaced, and no agent of the project): the page lines that go
    stale. A session that is an agent of the project after the pass (`after`: page key → the agents map the pass leaves; the page's own map for a project that is not in it) is no stale line: the session a
    promoted one-session project lists is not counted. A sub-page's `agent:` line is its own keeper, still true, and is not counted. Page lines are never written by this pass: they are listed so someone can edit them by hand, where it matters."""
    old = {r["key"]: (r["name"] or _kp.name_line(raw.get(r["key"]) or {})[0]) for r in rows if r["action"] in ("mark", "promote")}
    own = []
    for k, row in sorted(raw.items()):
        t = "/".join(k.split("/")[:2])
        if t not in old or k == t or not isinstance(row, dict):
            continue
        if row.get("role") == "name" and row.get("session") and row["session"] == old[t] and row["session"] not in ((after or {}).get(t) if t in (after or {}) else ((raw.get(t) or {}).get("agents") or {})):
            own.append(k)
    return {"count": len(own), "keys": own}


# ----------------------------------------------------------------------------- the plan and the apply
def plan(*, live: set | None = None, by: str = BY, now: str = "") -> dict:
    """The dry run: read the record and the registry file, decide each project, read what moves. Writes nothing and takes no lock."""
    d = prj._read()
    ents = pr.parse({pr.SECTION: d["extra"].get(pr.SECTION, {}), pr.VERSION: d["extra"].get(pr.VERSION, pr.SCHEMA)})
    return summarize(ents, prj.registry_raw(), live=live, by=by, now=now)


def summarize(ents: dict, raw: dict, *, live: set | None = None, by: str = BY, now: str = "") -> dict:
    new, rows = build(ents, raw, by=by, now=now or pv.now_iso())
    eff = effects(raw, ents, new, rows, live)
    counts = {a: sum(1 for r in rows if r["action"] == a) for a in ("mark", "promote", "marked", "archived", "skip")}
    counts["builder"] = sum(1 for r in rows if r["action"] == "mark" and r["kind"] == "builder")
    counts["main"] = sum(1 for r in rows if r["action"] == "mark" and r["kind"] == "main")
    counts["names_cleared"] = sum(1 for r in rows if r["cleared"])
    counts["changed"] = counts["mark"] + counts["promote"]
    return {"entries": new, "projects": rows, "counts": counts, "effects": eff, "sub_pages": sub_page_lines(raw, rows, {pr.page_key(e): e["agents"] for e in new.values() if pr.page_key(e) and isinstance(e.get("agents"), dict)})}


def _lines(p: dict, dry: bool, accept: set) -> list[str]:
    c, eff = p["counts"], p["effects"]
    out = [("dry run: " if dry else "") + f"keeper marks on {len(p['projects'])} project entries: {c['mark']} marked ({c['builder']} on a builder, {c['main']} on a -main or front agent), {c['promote']} one-session promotions, "
           f"{c['marked']} marked already, {c['archived']} archived, {c['skip']} skipped, {c['names_cleared']} names cleared"]
    for r in p["projects"]:
        if r["action"] in ("mark", "promote"):
            out.append(f"  {r['key']}: mark {r['agent']} ({r['kind']}; {r['why']})" + (f"; name {r['cleared']} cleared (it served nothing once the mark replaced it)" if r["cleared"] else ""))
        elif r["action"] in ("skip",):
            out.append(f"  {r['key'] or r['id']}: skipped, {r['why']}")
    out.append(f"sessions that lose a role: {len(eff['lose'])}" + (" (" + ", ".join(eff["lose"]) + ")" if eff["lose"] else ""))
    for x in eff["roles"][:SHOW]:
        out.append(f"  roles.json: {x['session']}: {x['from']} -> {x['to']}" + (" (sala's load_roles stops counting it)" if x["lost"] else (" (sala's load_roles reads it differently)" if x["lane_changes"] else "")))
    if len(eff["roles"]) > SHOW:
        out.append(f"  ... and {len(eff['roles']) - SHOW} more roles.json entries")
    if not eff["roles"]:
        out.append("  roles.json: no session's entry moves")
    out.append(f"running old name-line sessions that would show off the map: {len(eff['off_map'])}" + (" (sala could not be read: every session an old name line names is counted as running)" if eff["off_map_assumed"] else "")
               + (" (" + ", ".join(x["session"] for x in eff["off_map"]) + ")" if eff["off_map"] else ""))
    out.append(f"projects whose gating class flips: {len(eff['gating'])}" + (" (one-session projects, intended: " + ", ".join(f"{g['key']} {g['from']} -> {g['to']}" for g in eff["gating"]) + ")" if eff["gating"] else ""))
    hands = [x for x in eff["notices"] if x["hands"]]
    out.append(f"projects whose items or router passes go to a different agent: {len(hands)}")
    for x in hands[:SHOW]:
        out.append(f"  {x['key']}: items {x['item_keeper'][0] or 'none'} -> {x['item_keeper'][1] or 'none'}; stand-in {x['stand_in'][0] or 'none'} -> {x['stand_in'][1] or 'none'}")
    out.append(f"notice addresses that change (the old name line gives way to the marked agent): {len(eff['notices'])}" + (" (listed in --json)" if eff["notices"] else ""))
    out.append(f"marks that are not the keeper derived before: {len(eff['derived_moved'])}" + (" (" + ", ".join(f"{x['key']}: {x['derived']} -> {x['marked']}" for x in eff["derived_moved"]) + ")" if eff["derived_moved"] else ""))
    out.append(f"marked non-builders that get held notices later: {len(eff['non_builders'])}" + (" (" + ", ".join(f"{x['agent']} of {x['key']}" for x in eff["non_builders"]) + ")" if eff["non_builders"] else "")
               + ("; a marked front agent hears a held notice later than a builder did" if eff["non_builders"] else ""))
    sp = p["sub_pages"]
    out.append(f"sub-pages whose own line still names the old name line of a project marked now: {sp['count']}" + (" (" + ", ".join(sp["keys"][:SHOW]) + ")" if sp["keys"] else "")
               + " (page lines are never written by this pass; edit one by hand where it matters)")
    return out


def run(*, apply_: bool = False, accept: tuple = (), live: set | None = None, by: str = BY, run_dir: Any = None, now: str | None = None) -> dict:
    """The pass: the plan, and with `apply_` the write. → the plan (without the entries) and {dry, written, refused, undo, replanned, lines}. A refusal (a session that loses a role and is not accepted) writes nothing.
    The write plans again inside the record's lock, and what is returned and printed after a write is that plan (the one written); `replanned` is true when it differs from the plan read before the lock."""
    p = plan(live=live, by=by, now=now or "")
    acc = set(accept)
    lose = p["effects"]["lose"]
    res = {k: v for k, v in p.items() if k != "entries"}
    res.update({"dry": not apply_, "written": False, "refused": "", "undo": None, "replanned": False})
    lines = _lines(p, not apply_, acc)
    unaccepted = [n for n in lose if n not in acc]
    if apply_ and unaccepted:
        res["refused"] = (f"refused: {len(unaccepted)} session(s) would lose a role: {', '.join(unaccepted)}. List each as a front agent of its project first, or name it with --accept-role-loss; nothing was written")
        res["lines"] = lines + [res["refused"]]
        return res
    if not apply_:
        res["lines"] = lines + (["nothing written (add --apply)"] if p["counts"]["changed"] else ["nothing to change: every project is marked, archived or skipped"])
        return res
    if not p["counts"]["changed"]:
        res["lines"] = lines + ["nothing to change: nothing written"]
        return res
    undo = {"pid": "", "run_dir": run_dir, "mode": "record"}
    got: dict = {}

    def work(ctx: pv.Ctx) -> dict:
        p2 = summarize(ctx.ents, ctx.raw, live=live, by=ctx.by or BY, now=ctx.now)       # the plan again, on the record as it stands under the lock: this one is written, and is the one that is reported
        left = [n for n in p2["effects"]["lose"] if n not in acc]
        if left:
            raise pv.VerbError(409, f"the record changed while the pass was planned: {', '.join(left)} would now lose a role; nothing was written")
        for pid, e in p2["entries"].items():
            ctx.ents[pid] = e
        got["plan"] = p2
        return {}
    try:
        _out, _ents, changed = pv.txn(work, by=by, now=now, dry=False, undo=undo)
    except pv.VerbError as e:
        res["refused"] = e.message
        res["lines"] = lines + [e.message]
        return res
    p2 = got.get("plan") or p
    res.update({k: v for k, v in p2.items() if k != "entries"})                    # what is returned and printed is the plan that was written, not the one read before the lock
    lines2 = _lines(p2, False, acc)
    res["replanned"] = lines2 != lines
    n2 = p2["counts"]["changed"]
    note = ([f"the record changed between the plan and the write: nothing needed writing any more (the plan read before the lock had {p['counts']['changed']} changes)" if not n2 else
             f"the record changed between the plan and the write: the lines above are the plan that was written ({n2} changes), and they differ from the plan read before the lock ({p['counts']['changed']} changes)"]
            if res["replanned"] else [])
    res["written"] = bool(changed)
    res["undo"] = undo.get("file")
    res["lines"] = lines2 + note + ([f"written. undo file {undo['file']}", f"to undo: project.py restore --undo {undo['file']} --apply"
                                     f" (it puts the whole record file back and is refused, 409, once the record was written after this change; after a later write use `project.py restore --from-git REV --apply`, REV from `project.py restore --list`)"]
                                    if undo.get("file") else ["nothing to change: nothing written"])
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stackshot keeper-mark", description="put the keeper mark on every live project of the project record: a dry run unless --apply (the record only, with an undo file)")
    ap.add_argument("--apply", action="store_true", help="write the record (a dry run without it)")
    ap.add_argument("--accept-role-loss", action="append", default=[], metavar="SESSION", help="a session that loses a role and is allowed to (repeat for each; --apply refuses while one is not named)")
    ap.add_argument("--run-dir", default="", help="where the undo file goes (default ~/.local/share/stackshot-runs/project-restore)")
    ap.add_argument("--by", default=BY, help="who the written agents entries name")
    ap.add_argument("--json", action="store_true", help="the structured answer")
    a = ap.parse_args(argv)
    from stackshot.anchors import anchors as anc
    try:
        res = run(apply_=a.apply, accept=tuple(a.accept_role_loss), live=anc.sala_live(), by=a.by, run_dir=a.run_dir or None)
    except (ValueError, pv.VerbError) as e:
        print(f"keeper-mark: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps(res, indent=1, ensure_ascii=False, default=str))
    else:
        print("\n".join(res["lines"]))
    return 1 if res["refused"] else 0


if __name__ == "__main__":
    sys.exit(main())
