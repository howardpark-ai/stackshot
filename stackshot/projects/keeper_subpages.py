"""keeper_subpages.py — the one-time pass that moves the keeper of every sub-page an `agent:` line names into the mark form (a sub-page's own mark: `page_keepers` on the record entry of the project it sits under).

  stackshot keeper-subpages                 a dry run (the default): a table of every sub-page whose keeper only its `agent:` line names, and what the pass does with it; writes nothing at all
  stackshot keeper-subpages --apply         do it: the record only, in one atomic write, with an undo file (the format `project.py restore --undo` takes back)

Which pages it reads: the rows of the registry, as the readers see it (the record laid over the pages), whose role is "agent" (a sub-page an agent keeps as its own working document) and whose
`keeper_source` is "legacy" (nothing but the `agent:` line names the keeper): the rows the legacy gauge (keeper_reads.py) counts for that form. For each, in the table:

  mark      the agent the page names (or, when sala renamed that session, the name it has now: see below) is one some project lists (on the project's own map, or on another project's: a -main agent of one project often keeps pages in another): the page gets its own
            mark naming that agent, `page_keepers[<page>] = <agent>` on the record entry of the nearest project above it. When the mark names the agent the page already named, every reader of `session` and `role` answers as it did: the row keeps its role,
            and `keeper_source` is "mark" instead of "legacy", so the gauge falls by one. For a renamed session the readers do answer differently: the row's `session` becomes the new name, the new name is the one asked to keep
            the page from then on, and the old name stops reading it (an `old-x` renamed `new-x` that kept 9 pages by their `agent:` lines keeps 0 under that name, and `new-x` keeps those 9)
  inherit   the agent the page names is listed on no project's map and is no session sala lists: nobody live keeps the page, so it follows the keeper above it (`page_keepers[<page>] = ""`); the
            `agent:` line stays on the page, read as `legacy_session` and `legacy_role`. The page's keeper becomes the project's, so the project's keeper gains the page, by design (the readers that look at
            the page's agent and its item keeper stop naming the dead name; the dead name still reads the page through the old line, as with any mark)
  leave     the pass does not touch it, and says why: the page is no sub-page (a top-level page with an `agent:` line), no project record entry holds a page above it (adopt the project first),
            the agent is a running session that no project lists (list it first with `project.py agent-add`: a mark naming nobody listed is not read), or the project lists no agent, so a page handed
            back would only follow an old form again

A session sala renamed keeps its old name on the page: the `agent:` line still says it, and sala lists the old name as an alias of the session, so the pass would read it as "a running session on no
map". Before it decides an action for a page the pass maps the name through sala's rename log (`renamed_agents.renames_of`: old name to the name the session has now; a chain of renames is followed to the
newest name, with a guard against a loop). A name that a project's map lists as it stands needs no mapping. When the newest name is an agent some project lists the page is marked with the NEW name, and the table says
`renamed from <old>: own map` (or the other project's map); the `agent:` line is not touched. When the newest name is on no map the page is left, and the row names the old and the new name; a rename never hands a page back
(a name that is neither on a map nor a rename source is a dead name, as before). A loop in the log is left too.

When sala's list of running sessions cannot be read the pass makes no plan at all, a dry run included, and exits 1: "nobody runs under the name" cannot be told from "unknown", and a wrong guess hands a
running session's page to the project's keeper. The same holds when sala's rename log cannot be read, or sala lists sessions and none of the rows has an `aliases` field: an old name cannot then be told from a dead one. An empty list is read as ever.

It writes the project record and nothing else: no page (the page mirror stays off, and the `agent:` line stays as it is on every page), no roles file, no registry. The dry run reads the record, the registry
file and sala's list of running sessions, and writes no file (it takes no lock either). It is idempotent: a second run finds nothing left to mark. The apply plans again inside the record's lock and writes
that plan; its undo takes back the whole file and is refused once the record was written after the change (the printed hint names `restore --from-git` for that case).

    stackshot keeper-subpages [--apply] [--run-dir DIR] [--by WHO] [--json]"""
from __future__ import annotations

import os as _os
import sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]
import argparse
import copy
import json
import sys
from typing import Any

from stackshot.projects import keeper as _kp
from stackshot.projects import project_registry as pr
from stackshot.projects import project_verbs as pv
from stackshot.projects import projects as prj

BY = "keeper-subpages"
NO_SALA = ("sala's list of running sessions cannot be read, so the pass cannot tell an agent nobody runs from one that is running: it makes no plan and writes nothing. "
           "Run it where `sala sessions --json` works (a dry run too), then again")
NO_RENAMES = ("sala's rename log cannot be read, so the pass cannot tell a renamed session's old name from a name nobody runs under: it makes no plan and writes nothing. "
              "Run it where `sala sessions --json` works (a dry run too), then again")
NO_RENAMES_MAP: dict = {}   # the default of `renames`: no session was renamed (None says the log could not be read)
SHOW = 200                  # rows of the table in the text of a summary; the structured answer holds them all


# ----------------------------------------------------------------------------- what one page gets
def _holder(key: str, by_page: dict) -> str:
    """The id of the record entry that holds the mark of the sub-page `key`: the entry of the nearest page above it (a key of two parts or more) that has one. "" when none has."""
    parts = key.split("/")
    for n in range(len(parts) - 1, 1, -1):
        pid = by_page.get("/".join(parts[:n]))
        if pid:
            return pid
    return ""


def _maps(rows: dict, ents: dict) -> dict:
    """agent name → the page keys whose project lists it (the rows' maps, the entries laid over them, and the entries' own maps), sorted."""
    out: dict = {}
    for k, r in sorted(rows.items()):
        off = (r.get("surface_agents") or {}) if isinstance(r, dict) else {}
        for n in ((r.get("agents") or {}) if isinstance(r, dict) else {}):
            if n not in off:                                    # an agent that is not a sala session (a Slack agent) keeps no page: its name is on no map, as an unlisted one's is
                out.setdefault(str(n), set()).add(k)
    for e in ents.values():
        for n, a in (e.get("agents") or {}).items():
            if not pr.off_sala(a):
                out.setdefault(str(n), set()).add(pr.page_key(e) or "")
    return {n: sorted(x for x in ks if x) for n, ks in out.items()}


def _casefold(renames: dict) -> dict:
    """The rename log with its names case-folded (names compare case-folded, as in renamed_agents.renames_of)."""
    return {str(k).casefold(): str(v) for k, v in renames.items()}


def _follow(name: str, ren: dict) -> tuple[str, bool]:
    """(the newest name `name` was renamed to, whether the log loops) for the case-folded log `ren`: the name itself when it was never renamed. A loop ends at the first name that comes round again."""
    seen = {name.casefold()}
    cur = name
    while cur.casefold() in ren:
        cur = ren[cur.casefold()]
        if cur.casefold() in seen:
            return cur, True
        seen.add(cur.casefold())
    return cur, False


def _decide(key: str, row: dict, ents: dict, new: dict, by_page: dict, maps: dict, live: set, ren: dict) -> dict:
    """What the pass does with the sub-page `key` (its row `row` of the registry as the readers see it). `new` = the entries as the pass leaves them (changed in place when it marks or hands back).
    `ren` = the case-folded rename log: a name no map lists is mapped to the name its session has now before the page is decided. `agent` in the answer is the name the pass writes for a mark (the new name of a
    renamed session) and the name the page names otherwise."""
    agent = str(row.get("session") or "")
    out: dict = {"key": key, "agent": agent, "action": "leave", "where": "", "why": "", "holder": "", "renamed_from": "", "renamed_to": ""}
    if key.count("/") < 2:
        return {**out, "why": "not a sub-page: a top-level page that an `agent:` line keeps"}
    pid = _holder(key, by_page)
    if not pid:
        return {**out, "why": "no project record entry holds a page above it: adopt the project first, then run the pass again"}
    out["holder"] = pr.page_key(new[pid])
    top = out["holder"]
    on = maps.get(agent, [])
    name, was = agent, ""
    if not on:                                      # a name a map lists needs no mapping; any other goes through the rename log
        name, looped = _follow(agent, ren)
        if looped:
            return {**out, "where": f"rename log loops at {name}", "why": f"sala's rename log leads from {agent} round to itself, so the pass cannot tell which name the session has now: fix the log, then run the pass again"}
        if name != agent:
            was, on = agent, maps.get(name, [])
            if not on:
                return {**out, "where": f"renamed to {name}: on no map", "why": f"sala renamed the session ({agent} is now {name}) and no project lists the new name: list it (`project.py agent-add`), then run the pass again; a mark naming nobody listed is not read",
                        "renamed_to": name}
    own = top in on
    if on:
        out["where"] = ("renamed from " + was + ": " if was else "") + ("own map" if own else "map of " + ", ".join(on[:2]) + (" and more" if len(on) > 2 else ""))
        new[pid].setdefault(_kp.PAGES, {})[key] = name
        return {**out, "agent": name, "action": "mark", "renamed_from": was, "why": "an agent " + ("of the project's own map" if own else "another project lists (cross-project keeper)")}
    if agent in live:
        out["where"] = "running session, on no map"
        return {**out, "why": "a running session that no project lists: list it (`project.py agent-add`), then run the pass again; a mark naming nobody listed is not read"}
    out["where"] = "nowhere"
    new[pid].setdefault(_kp.PAGES, {})[key] = ""
    return {**out, "action": "inherit", "why": "no project lists the agent and no session runs under the name: the page follows the keeper above it"}


def build(ents: dict, raw: dict, live: set | None = None, renames: dict | None = NO_RENAMES_MAP) -> tuple[dict, list[dict]]:
    """(the entries as the pass leaves them, one table row per page the pass reads) for the entries `ents` and the page registry `raw` (the pages alone, `projects.registry_raw`). `ents` is not changed.
    The pages are read in the order of their keys, so two runs read the same record the same way. A page a mark already answers for is no row (its keeper is no longer legacy).
    `renames` = {old name: new name} from sala's rename log ({} when nothing was renamed); None = the log could not be read: refused like an unreadable list of sessions."""
    if live is None:
        raise ValueError(NO_SALA)
    if renames is None:
        raise ValueError(NO_RENAMES)
    ren = _casefold(renames)
    new = copy.deepcopy(ents)
    ov = pr.apply(raw, ents)
    by_page = pr.by_page(ents)
    maps = _maps(ov, ents)
    rows = [_decide(k, r, ents, new, by_page, maps, live, ren) for k, r in sorted(ov.items())
            if isinstance(r, dict) and r.get("role") == "agent" and r.get("keeper_source") == "legacy" and str(r.get("session") or "")]
    after = pr.apply(raw, new)
    for r in rows:                      # a page handed back follows the keeper above it only when that keeper is a mark or derived: under a project that lists no agent it would still be an old form
        if r["action"] == "inherit" and (after.get(r["key"]) or {}).get("keeper_source") not in ("mark", "derived"):
            pid = _holder(r["key"], by_page)
            del new[pid][_kp.PAGES][r["key"]]
            if not new[pid][_kp.PAGES]:
                del new[pid][_kp.PAGES]
            r.update(action="leave", why="the project lists no agent that could keep it, so there is nothing to follow: list an agent on the project first, then run the pass again")
    return new, rows


# ----------------------------------------------------------------------------- what the change moves
def _legacy(rows: dict) -> list[str]:
    return sorted(k for k, v in rows.items() if isinstance(v, dict) and v.get("keeper_source") == "legacy")


def effects(raw: dict, before: dict, after: dict, rows: list[dict], live: set | None = None, renames: dict | None = None) -> dict:
    """What the change from the entries `before` to `after` moves, read from the registry laid with each (the code the server runs):
      gauge          the legacy count (rows only an old form keeps) before and after
      moved          each page whose `session` or `role` differs, with the names that keep it before and after (`keeper.names_of`): a marked page moves nothing, a handed-back one moves to the keeper above
      lose, gain     the names that lose a page and the names that gain one (counts of pages), by what the readers that look at `session` and `role` answer: the agent of a page whose role is `agent`
                     (`page_debt.page_agent`, `pilot_keeper`, `item_read`, the first step of the item keeper), else the keeper the page follows (the row's `keeper_agent`: a mark or the derived one).
                     The old line kept as `legacy_session` does not count: those readers do not look at it. A loss is counted per session (`renames` folds an old name into the name its session has now): a page that
                     moves from a session's old name to its new one is no loss. A gain is counted per name, as the readers ask the name on the row: the new name of a renamed session gains the page
      gain_pages     the pages each name gains
      live_lose      the running sessions (`live`) that lose a page, by the same reading: none when only names no session runs under are handed back
      roles          the roles.json entries that differ (anchors.file_roles)"""
    reg0, reg1 = pr.apply(raw, before), pr.apply(raw, after)
    ren = _casefold(renames or {})

    def who(k: str, reg: dict) -> set:
        row = reg.get(k) or {}
        return {str(row.get("session") or "") if row.get("role") == "agent" else str(row.get("keeper_agent") or "")} - {""}

    def session(names: set) -> set:         # the sessions those names are: an old name counts as the session it was renamed to
        return {_follow(n, ren)[0] for n in names}
    moved, lose, gain, gain_pages = [], {}, {}, {}
    for k in sorted(set(reg0) | set(reg1)):
        a, b = reg0.get(k) or {}, reg1.get(k) or {}
        n0, n1 = who(k, reg0), who(k, reg1)
        if (a.get("session"), a.get("role")) == (b.get("session"), b.get("role")) and _kp.names_of(a) == _kp.names_of(b) and n0 == n1:
            continue
        moved.append({"key": k, "from": [a.get("session"), a.get("role")], "to": [b.get("session"), b.get("role")], "lost": sorted(n0 - n1), "gained": sorted(n1 - n0)})
        for n in session(n0) - session(n1):             # a loss is a session's: a page that moves from its old name to its new one is none
            lose[n] = lose.get(n, 0) + 1
        for n in n1 - n0:                               # a gain is a name's: the readers ask the name on the row, so the new name of a renamed session gains the page
            gain[n] = gain.get(n, 0) + 1
            gain_pages.setdefault(n, []).append(k)
    roles = []
    try:
        from stackshot.anchors import anchors as anc
        r0, r1 = anc.file_roles(reg0), anc.file_roles(reg1)
        roles = [{"session": n, "from": r0.get(n), "to": r1.get(n)} for n in sorted(set(r0) | set(r1)) if r0.get(n) != r1.get(n)]
    except Exception:  # noqa: BLE001 — the dry run reads what it can; the table above is the plan
        pass
    return {"gauge": {"before": len(_legacy(reg0)), "after": len(_legacy(reg1))}, "moved": moved, "lose": lose, "gain": gain, "gain_pages": gain_pages,
            "live_lose": sorted(n for n in lose if n in (live or set())), "roles": roles}


# ----------------------------------------------------------------------------- the plan and the apply
def plan(*, live: set | None = None, renames: dict | None = NO_RENAMES_MAP) -> dict:
    """The dry run: read the record and the registry file, decide each page, read what moves. Writes nothing and takes no lock."""
    d = prj._read()
    ents = pr.parse({pr.SECTION: d["extra"].get(pr.SECTION, {}), pr.VERSION: d["extra"].get(pr.VERSION, pr.SCHEMA)})
    return summarize(ents, prj.registry_raw(), live=live, renames=renames)


def summarize(ents: dict, raw: dict, *, live: set | None = None, renames: dict | None = NO_RENAMES_MAP) -> dict:
    new, rows = build(ents, raw, live, renames)
    counts = {a: sum(1 for r in rows if r["action"] == a) for a in ("mark", "inherit", "leave")}
    counts["pages"] = len(rows)
    counts["changed"] = counts["mark"] + counts["inherit"]
    counts["cross_project"] = sum(1 for r in rows if r["action"] == "mark" and not r["where"].endswith("own map"))
    counts["renamed"] = sum(1 for r in rows if r["action"] == "mark" and r["renamed_from"])
    return {"entries": new, "pages": rows, "counts": counts, "effects": effects(raw, ents, new, rows, live, renames)}


def _table(rows: list[dict]) -> list[str]:
    head = ("sub-page", "agent named", "action", "where the agent is listed / why")
    body = [(r["key"], r["agent"] or "-", r["action"], (r["where"] + ": " if r["where"] else "") + r["why"]) for r in rows[:SHOW]]
    w = [max(len(str(x[i])) for x in [head, *body]) for i in range(3)]
    fmt = lambda x: "  ".join(str(x[i]).ljust(w[i]) for i in range(3)) + "  " + str(x[3])
    return [fmt(head).rstrip(), *(fmt(x).rstrip() for x in body)] + ([f"... and {len(rows) - SHOW} more (all of them in --json)"] if len(rows) > SHOW else [])


def _lines(p: dict, dry: bool) -> list[str]:
    c, eff = p["counts"], p["effects"]
    out = [("dry run: " if dry else "") + f"sub-page keepers: {c['pages']} pages kept only by an `agent:` line: {c['mark']} marked ({c['cross_project']} name an agent of another project), "
           f"{c['inherit']} handed back to the keeper above, {c['leave']} left"]
    out += _table(p["pages"])
    if c["renamed"]:
        out.append(f"{c['renamed']} of the marks name a session by the name sala renamed it to (the `agent:` lines keep the old name and stay as they are; the new name is the page's agent from now on and is listed below as gaining it, the old name stops reading it, and the renamed session loses no page)")
    out.append(f"legacy gauge: {eff['gauge']['before']} -> {eff['gauge']['after']} (the rows only an old form keeps)")
    out.append(f"pages whose session or role differs: {sum(1 for m in eff['moved'] if m['from'] != m['to'])} (a marked page moves nothing, except that a renamed session's page now names the new name; a handed-back one moves to the keeper above it)")
    out.append("names that lose pages (as the readers of a page's agent and item keeper see it; a renamed session's old name counts as the session): " + (", ".join(f"{n} ({k})" for n, k in sorted(eff["lose"].items())) or "none"))
    out.append("names that gain pages: " + (", ".join(f"{n} ({k}: {', '.join(eff['gain_pages'].get(n, [])[:4])}{', ...' if k > 4 else ''})" for n, k in sorted(eff["gain"].items())) or "none"))
    if c["inherit"]:
        out.append("a page handed back follows the keeper above it, by design: a name nobody runs under keeps no page, and the project's keeper takes the page (its notices and items) from now on")
    out.append(f"running sessions that lose a page: {len(eff['live_lose'])}" + (" (" + ", ".join(eff["live_lose"]) + ")" if eff["live_lose"] else ""))
    out.append(f"roles.json entries that change: {len(eff['roles'])}")
    return out


def run(*, apply_: bool = False, live: set | None = None, renames: dict | None = NO_RENAMES_MAP, by: str = BY, run_dir: Any = None, now: str | None = None) -> dict:
    """The pass: the plan, and with `apply_` the write. → the plan (without the entries) and {dry, written, undo, replanned, lines}. The write plans again inside the record's lock, and what is
    returned and printed after a write is that plan (the one written); `replanned` is true when it differs from the plan read before the lock."""
    if live is None or renames is None:     # sala (or its rename log) could not be read: "nobody runs under the name" is then unknown, never an empty list: no plan, a dry run included
        why = NO_SALA if live is None else NO_RENAMES
        return {"dry": not apply_, "written": False, "refused": why, "undo": None, "replanned": False, "pages": [], "counts": {}, "effects": {}, "lines": [why]}
    p = plan(live=live, renames=renames)
    res = {k: v for k, v in p.items() if k != "entries"}
    res.update({"dry": not apply_, "written": False, "refused": "", "undo": None, "replanned": False})
    lines = _lines(p, not apply_)
    if not apply_:
        res["lines"] = lines + (["nothing written (add --apply)"] if p["counts"]["changed"] else ["nothing to change: no sub-page is kept only by an `agent:` line that the pass can move"])
        return res
    if not p["counts"]["changed"]:
        res["lines"] = lines + ["nothing to change: nothing written"]
        return res
    undo = {"pid": "", "run_dir": run_dir, "mode": "record"}
    got: dict = {}

    def work(ctx: pv.Ctx) -> dict:
        got["plan"] = summarize(ctx.ents, ctx.raw, live=live, renames=renames)         # the plan again, on the record as it stands under the lock: this one is written and is the one reported
        for pid, e in got["plan"]["entries"].items():
            ctx.ents[pid] = e
        return {}
    try:
        _out, _ents, changed = pv.txn(work, by=by, now=now, dry=False, undo=undo)
    except pv.VerbError as e:
        res["refused"] = e.message
        res["lines"] = lines + [e.message]
        return res
    p2 = got.get("plan") or p
    res.update({k: v for k, v in p2.items() if k != "entries"})
    lines2 = _lines(p2, False)
    res["replanned"] = lines2 != lines
    n2 = p2["counts"]["changed"]
    note = ([f"the record changed between the plan and the write: the lines above are the plan that was written ({n2} changes), and they differ from the plan read before the lock ({p['counts']['changed']} changes)"]
            if res["replanned"] else [])
    res["written"] = bool(changed)
    res["undo"] = undo.get("file")
    res["lines"] = lines2 + note + ([f"written. undo file {undo['file']}", f"to undo: project.py restore --undo {undo['file']} --apply"
                                     f" (it puts the whole record file back and is refused, 409, once the record was written after this change; after a later write use `project.py restore --from-git REV --apply`, REV from `project.py restore --list`)"]
                                    if undo.get("file") else ["nothing to change: nothing written"])
    return res


def rename_log(rows: list | None, renames_of: Any) -> dict | None:
    """The rename log of the rows of `sala sessions --json`, or None when it cannot be read: no rows (sala unreadable), `renames_of` failing, or a list of sessions in which no row carries an `aliases` field
    at all (an old or stripped sala: nothing could be told renamed, and every old name would read as a name nobody runs under). An empty list is read as it was: nobody runs, nothing was renamed."""
    if rows is None or (rows and not any(isinstance(x, dict) and "aliases" in x for x in rows)):
        return None
    try:
        return renames_of(rows)
    except Exception:  # noqa: BLE001 — a rename log that cannot be read is no empty one
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stackshot keeper-subpages", description="move the keeper of every sub-page an `agent:` line names into a mark of its own: a dry run unless --apply (the record only, with an undo file)")
    ap.add_argument("--apply", action="store_true", help="write the record (a dry run without it)")
    ap.add_argument("--run-dir", default="", help="where the undo file goes (default ~/.local/share/stackshot-runs/project-restore)")
    ap.add_argument("--by", default=BY, help="who the change is recorded as")
    ap.add_argument("--json", action="store_true", help="the structured answer")
    a = ap.parse_args(argv)
    from stackshot.anchors import anchors as anc
    from stackshot.fleet import renamed_agents as ra
    rows = anc.sala_rows()                      # sala is read once: the names and aliases that run, and the rename log, come from the same rows
    live = None if rows is None else set().union(*anc.sessions_of(rows))
    renames = rename_log(rows, ra.renames_of)
    try:
        res = run(apply_=a.apply, live=live, renames=renames, by=a.by, run_dir=a.run_dir or None)
    except (ValueError, pv.VerbError) as e:
        print(f"keeper-subpages: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    if res["refused"] in (NO_SALA, NO_RENAMES):
        print(f"keeper-subpages: {res['refused']}", file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps(res, indent=1, ensure_ascii=False, default=str))
    else:
        print("\n".join(res["lines"]))
    return 1 if res["refused"] else 0


if __name__ == "__main__":
    sys.exit(main())
