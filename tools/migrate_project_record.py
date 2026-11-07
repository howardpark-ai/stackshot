#!/usr/bin/env python3
"""tools/migrate_project_record.py — turn the projects the registry derives from pages into entries of the project record, with an undo copy.

Until now a project existed because a page of type `project` did, and the registry was derived from that page's lines. The record (`project-record.json`, section
`projects`, project_registry.py) holds a project on its own; this tool writes one entry for each `type: project` page the registry derives (top-level pages only: a sub-page, a key under another page or a page with a `hub:` line, is never a project), with the
values the registry derives today, so that reading the entries first changes nothing a reader sees.

    tools/migrate_project_record.py                           dry run (the default): what would be written, in counts and names. Writes nothing.
    tools/migrate_project_record.py --apply [--run-dir DIR]   writes the undo copy of the record file first (fsynced, <run-dir>/<pass id>/), then the entries, in one atomic write
                                                              under the record's own lock (safe beside the running server).
    tools/migrate_project_record.py --undo FILE               restores the record file the pass kept (FILE = its undo.json).

An entry (see project_registry.py): the page's title and type, the name (the page's own `display-name:` when it has one), the scope the registry derives for it (a mark
set on purpose first), status `archived` when the page's status is a retired word (else active), the agents in the order the page lists them (a `background:` agent is not
front), the hub, the page key as `page`, `former_keys` from the redirect stubs that lead to the page and from the `aliases:` lines of the page, and `made` (and `retired`, for an
archived one) = {at: the run's time, by: "migration", how: "migrated"}.

The pending agents the record holds (agents registered through the New session form whose page line is still owed) are folded into the agents of their project's entry (after the
ones the page lists; an archived project does not keep one) and cleared from the pending table in the same write, so a session that runs under such a name is still a role of its
project; a pending agent of a project that has no entry stays pending. `--keep-pending` does neither. The undo copy holds them either way. Running it twice is a no-op: a project that
has an entry is not rewritten (except that former keys it lacks are added), and a second pass with nothing to add, update or clear writes nothing and keeps no undo copy.

    --store DIR  --brain DIR  --state DIR     read and write those instead of the instance's (a copy of the store for a dry run; --state keeps the lock and the temp files of
                                              a run on a copy out of the live state dir)

`--undo` puts the saved file back when the record is still the one this pass wrote. When something else has written to the record since (a new id, a mark, a pending agent), it
removes the entries and puts back the pending agents instead, and leaves every other change in the file.

Exit 0 · 1 for a record or an undo file that does not read, or a registry with no id for a project · 2 for wrong arguments."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
DEFAULT_RUN = Path.home() / ".local" / "share" / "stackshot-runs" / "record-migration"
BY = "migration"


def _norm(v: Any, first: str) -> str:
    v = str(v or "").strip().strip("'\"").strip("/")
    if v.endswith(".md"):
        v = v[:-3]
    return v if not v or "/" in v else first + "/" + v


def former_keys(bases: list[Path], dirs: list[str]) -> tuple[dict, dict]:
    """(former, report): former = {page key: sorted list of the keys that lead to it}, from the redirect stubs (`type: redirect`, `redirect_to:`; a chain of stubs is followed to
    the live page) and from the `aliases:` lines of the pages; report = counts of what was read. Reads the page files; a key that no live page ends is left out."""
    import pages
    first = dirs[0]
    pages_: set = set(); redirects: dict = {}; aliases: dict = {}
    for base in bases:
        for sub in dirs:
            for f in sorted((base / sub).glob("**/*.md")):
                key = f.relative_to(base).as_posix()[:-3]
                if key.endswith("/README"):
                    continue
                fm = pages.frontmatter(str(f))
                typ = str(fm.get("type") or "").strip().lower()
                if typ == "archive":
                    continue
                if typ == "redirect":
                    to = _norm(fm.get("redirect_to"), first)
                    if to:
                        redirects[key] = to
                    continue
                pages_.add(key)
                a = fm.get("aliases")
                for x in ([a] if isinstance(a, str) else a if isinstance(a, list) else []):
                    x = _norm(x, first)
                    if x and x != key:
                        aliases.setdefault(x, key)
    former: dict = {}; dead = 0
    for old, to in redirects.items():
        seen = {old}
        while to in redirects and to not in seen:
            seen.add(to); to = redirects[to]
        if to in pages_ and to != old:
            former.setdefault(to, set()).add(old)
        else:
            dead += 1
    for old, page in aliases.items():
        if old in pages_:
            continue                    # an alias that is a live page again is a page, not a former key
        former.setdefault(page, set()).add(old)
    return {k: sorted(v) for k, v in former.items()}, {"stubs": len(redirects), "stubs_without_live_page": dead, "aliases": len(aliases)}


def plan(reg: dict, ids: dict, ents: dict, pending: dict, marks: dict, former: dict, now: str, keep_pending: bool = False) -> dict:
    """What a pass would do: {"add": {id: entry}, "update": {id: {field: value}}, "already": n, "no_id": [keys], "pending": [(id, name, entry)] to clear, "folded": [(id, name)], "kept": [(id, name, entry, why)] left pending, "subpages": [keys] of the type-project pages left out}. Only top-level pages get an entry. Reads nothing but its arguments.
    `reg` is the registry from the pages alone (projects.registry_raw), `ids` = the record's id table (id → page key). The entries are the ones project_verbs.derive_entry makes (a project's first
    verb makes its entry with the same function, so a project the migration reaches later reads the same).

    The pending agents of a project that has an entry (made now or before) are folded into its agents, after the ones the page lists, when the project is active, and cleared from the pending table either way
    (a project that is archived does not keep an agent that was only waiting for a page line); a pending agent of a project with no entry stays where it is. `--keep-pending` does neither. A project that already has
    an entry is not rewritten, except that the former keys the stubs and aliases give and the entry lacks are added (a project whose entry a verb made before this pass has none)."""
    import copy
    import project_registry as pr
    import project_verbs as pv
    import projects as prj
    by_page = pr.by_page(ents)
    by_key: dict = {}
    for i, k in sorted(ids.items()):
        by_key.setdefault(k, i)
    add: dict = {}; update: dict = {}; already = 0; no_id: list = []; subpages: list = []
    for key, e in sorted(reg.items()):
        if not isinstance(e, dict) or str(e.get("type") or "").strip().lower() != "project":
            continue
        if prj.is_sub_page(key, reg, e):
            subpages.append(key); continue                    # a sub-page is never a project: it gets no entry, and its items belong to the top-level project
        pid = e.get("id") if prj.is_id(e.get("id")) else by_key.get(key)
        if not prj.is_id(pid):
            no_id.append(key); continue
        if pid in ents or key in by_page:
            already += 1
            epid = pid if pid in ents else by_page[key]
            miss = [k for k in former.get(key, []) if k not in (ents[epid].get("former_keys") or [])]
            if miss:
                update.setdefault(epid, {})["former_keys"] = list(ents[epid].get("former_keys") or []) + miss
            continue
        add[pid] = pv.derive_entry(pid, key, e, reg, marks.get(pid), now, by=BY, how="migrated", former=former.get(key, []))
    clear: list = []; folded: list = []; kept: list = []
    if keep_pending:
        kept = [(pid, n, dict(a), "kept on request") for pid, m in sorted(pending.items()) for n, a in sorted(m.items())]
    else:
        for pid, m in sorted(pending.items()):
            ent = add.get(pid) or ents.get(pid)
            if ent is None or not m:
                kept += [(pid, n, dict(a), "the project has no entry") for n, a in sorted(m.items())]
                continue                                  # no entry to fold into (a note page, an id with no page): the pending agent stays
            if ent.get("status") != "archived":
                if pid in add:
                    names = pv.fold_pending(ent, m)
                else:
                    own = ent.get("agents") if "agents" in ent else pv.seed_agents(reg.get(pr.page_key(ent)))
                    tmp = {"agents": copy.deepcopy(own)}
                    names = pv.fold_pending(tmp, m)
                    if names:
                        update.setdefault(pid, {})["agents"] = tmp["agents"]
                folded += [(pid, n) for n in names]
            clear += [(pid, n, dict(a)) for n, a in sorted(m.items())]
    return {"add": add, "update": update, "already": already, "no_id": no_id, "pending": clear, "folded": folded, "kept": kept, "subpages": subpages}


def report(p: dict, reg: dict, rep: dict, ids: dict) -> list[str]:
    import collections
    import projects as prj
    add = p["add"]; keys = {e["page"]: pid for pid, e in add.items()}
    typed = sum(1 for e in reg.values() if isinstance(e, dict) and str(e.get("type") or "").strip().lower() == "project")
    out = [f"registry: {len(reg)} pages, {typed} of type project, {len(p.get('subpages', []))} of them sub-pages (never projects: no entry)",
           f"entries to write: {len(add)}; already in the record: {p['already']}; no id yet: {len(p['no_id'])}",
           f"  status: {sum(1 for e in add.values() if e['status'] == 'active')} active, {sum(1 for e in add.values() if e['status'] == 'archived')} archived",
           f"  with agents: {sum(1 for e in add.values() if e.get('agents'))}, with a name: {sum(1 for e in add.values() if e.get('name'))}, with a hub: {sum(1 for e in add.values() if e['hub'])}",
           f"  former keys: {sum(len(e['former_keys']) for e in add.values())} on {sum(1 for e in add.values() if e['former_keys'])} projects "
           f"(read: {rep['stubs']} redirect stubs, {rep['stubs_without_live_page']} of them leading to no live page; {rep['aliases']} aliases)",
           "  scopes: " + ", ".join(f"{s} {n}" for s, n in sorted(collections.Counter(e["scope"] for e in add.values()).items()))]
    out += [f"  no id yet (rebuild the registry first): {k}" for k in p["no_id"]]
    page_of = ids                                  # the id table: id → page key
    folded = set(p.get("folded", []))
    out += [f"pending agent {'folded into its project and cleared' if (pid, n) in folded else 'to clear'}: {page_of.get(pid, pid)} ({pid}) {n}  front={a.get('front')} by={a.get('by')!r} at={a.get('at')!r}" for pid, n, a in p["pending"]]
    out += [f"pending agent kept ({why}): {page_of.get(pid, pid)} ({pid}) {n}  front={a.get('front')} by={a.get('by')!r} at={a.get('at')!r}" for pid, n, a, why in p["kept"]]
    if p.get("update"):
        out.append(f"entries to update: {len(p['update'])} ({sum(1 for u in p['update'].values() if 'former_keys' in u)} get former keys, {sum(1 for u in p['update'].values() if 'agents' in u)} get pending agents)")
    return out


def _sha(text: str | None) -> str:
    return "" if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _write_json(path: Path, obj: Any) -> None:
    import projects as prj
    prj.write_atomic(path, json.dumps(obj, indent=1, ensure_ascii=False) + "\n")


def apply(run_dir: Path, keep_pending: bool, bases: list[Path], dirs: list[str], now: str) -> tuple[int, list[str], Path | None]:
    """Make the plan and write it under the record's lock: the undo copy first, then the one write. → (exit code, lines, the undo file or None when nothing was written)."""
    import project_registry as pr
    import projects as prj
    former, rep = former_keys(bases, dirs)
    with prj.locked():
        d = prj._read()
        ents = pr.parse({pr.SECTION: d["extra"].get(pr.SECTION, {}), pr.VERSION: d["extra"].get(pr.VERSION, pr.SCHEMA)})
        reg = prj.registry_raw()
        p = plan(reg, d["ids"], ents, d["pending_agents"], d["marks"], former, now, keep_pending)
        lines = report(p, reg, rep, d["ids"])
        if p["no_id"]:
            return 1, lines + ["refused: some projects have no id yet; nothing written"], None
        if not p["add"] and not p["pending"] and not p["update"]:
            return 0, lines + ["nothing to do; nothing written"], None
        pass_id = now.replace("-", "").replace(":", "")
        base = run_dir.expanduser() / pass_id
        n = 1
        while base.exists():                    # two passes in one second keep two undo copies
            n += 1; base = run_dir.expanduser() / f"{pass_id}-{n}"
        before = _read_text(prj.record_path())
        if before is not None:
            prj.write_atomic(base / "project-record.before.json", before)       # the previous file, whole, before the first write
        meta = {"schema": 1, "made": pass_id, "record": str(prj.record_path()), "before": str(base / "project-record.before.json") if before is not None else "",
                "before_sha256": _sha(before), "entries": sorted(p["add"]), "pending_cleared": [{"project": pid, "name": n, "entry": a} for pid, n, a in p["pending"]],
                "after_sha256": ""}
        undo = base / "undo.json"
        _write_json(undo, meta)
        merged = {**ents, **p["add"]}
        for pid, u in p["update"].items():
            merged[pid] = {**merged[pid], **u}
        d["extra"][pr.SECTION] = merged; d["extra"][pr.VERSION] = pr.SCHEMA
        if p["pending"]:
            for pid, n, _a in p["pending"]:
                (d["pending_agents"].get(pid) or {}).pop(n, None)
        prj._write(d)
        meta["after_sha256"] = _sha(_read_text(prj.record_path()))
        _write_json(undo, meta)
    return 0, lines + [f"wrote {len(p['add'])} entries, updated {len(p['update'])}, folded {len(p['folded'])} and cleared {len(p['pending'])} pending agents; undo file {undo}"], undo


def undo(path: Path) -> tuple[int, list[str]]:
    import project_registry as pr
    import projects as prj
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
        rec = Path(meta["record"]); saved = meta.get("before") or ""; want = meta.get("after_sha256") or ""; cleared = list(meta.get("pending_cleared") or [])
    except (OSError, ValueError, KeyError, TypeError) as e:
        return 1, [f"undo file {path}: not readable ({e})"]
    with prj.locked():
        now_text = _read_text(rec)
        if saved:
            before = _read_text(Path(saved))
            if before is None:
                return 1, [f"the saved record file {saved} is missing; nothing changed"]
            if now_text == before:
                return 0, ["the record is the saved file already; nothing to do"]
            if want and _sha(now_text) == want:
                prj.write_atomic(rec, before)
                return 0, [f"restored the record file as it was before the pass ({saved})"]
        elif now_text is None:
            return 0, ["the record file is not there; nothing to do"]
        elif want and _sha(now_text) == want:
            rec.unlink()
            return 0, ["the record file did not exist before the pass: removed"]
        d = prj._read()
        made = {str(x) for x in meta.get("entries") or []}
        sec = d["extra"].get(pr.SECTION) or {}
        gone = sorted(x for x in sec if x in made)                  # only the entries this pass made: one a later verb made stays
        for x in gone:
            del sec[x]
        if sec:
            d["extra"][pr.SECTION] = sec
        else:
            d["extra"].pop(pr.SECTION, None); d["extra"].pop(pr.VERSION, None)
        back = 0
        for c in cleared:
            if str(c["project"]) not in gone:
                continue                                           # its project keeps its entry (the agent was folded into it): not listed twice
            m = d["pending_agents"].setdefault(str(c["project"]), {})
            if not any(str(x).casefold() == str(c["name"]).casefold() for x in m):
                m[str(c["name"])] = dict(c["entry"]); back += 1
        prj._write(d)
    return 0, [f"the record changed after the pass: removed the {len(gone)} entries this pass made ({len(sec)} others, made since, stay) and put back {back} pending agents; everything else in the file is as it is now"]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Write the project record's entries from the pages the registry derives. Dry run unless --apply; --undo restores the previous file.")
    ap.add_argument("--apply", action="store_true", help="write the undo copy, then the entries")
    ap.add_argument("--undo", metavar="FILE", help="restore from an undo file a pass kept")
    ap.add_argument("--keep-pending", action="store_true", help="leave the record's pending agents (the default clears them)")
    ap.add_argument("--run-dir", default=str(DEFAULT_RUN), help="where --apply keeps its undo copy (default %(default)s)")
    ap.add_argument("--store", metavar="DIR", help="read and write this store instead of the instance's")
    ap.add_argument("--brain", metavar="DIR", help="read the pages' redirect stubs and aliases here instead of the instance's checkout")
    ap.add_argument("--state", metavar="DIR", help="keep the lock and temp files here instead of the instance's state dir")
    ap.add_argument("--now", metavar="ISO", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.undo and (a.apply or a.keep_pending):
        print("--undo takes no --apply or --keep-pending", file=sys.stderr)
        return 2
    import config as _cfg
    for key, val in (("store", a.store), ("brain", a.brain), ("state", a.state)):
        if val:
            _cfg.CFG.setdefault("paths", {})[key] = str(Path(val).expanduser())
    import projects as prj
    try:
        if a.undo:
            code, lines = undo(Path(a.undo))
            print("\n".join(lines), file=sys.stderr if code else sys.stdout)
            return code
        now = a.now or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        bases = [Path(_cfg.path("paths", "brain"))]
        try:
            import brains
            bases += [Path(b.path) for b in brains.all_brains() if not b.default and Path(b.path).is_dir()]
        except Exception:  # noqa: BLE001
            pass
        dirs = _cfg.page_dirs()
        if a.apply:
            code, lines, _u = apply(Path(a.run_dir), a.keep_pending, bases, dirs, now)
            print("\n".join(lines), file=sys.stderr if code else sys.stdout)
            return code
        reg = prj.registry_raw()
        if not reg:
            print("the page registry is empty or missing; nothing to migrate", file=sys.stderr)
            return 1
        d = prj._read()
        import project_registry as pr
        ents = pr.parse({pr.SECTION: d["extra"].get(pr.SECTION, {}), pr.VERSION: d["extra"].get(pr.VERSION, pr.SCHEMA)})
        former, rep = former_keys(bases, dirs)
        p = plan(reg, d["ids"], ents, d["pending_agents"], d["marks"], former, now, a.keep_pending)
        print("\n".join(report(p, reg, rep, d["ids"])))
        print(f"dry run: {len(p['add'])} entries would be written, {len(p['update'])} updated, {len(p['folded'])} pending agents folded into their projects and {len(p['pending'])} cleared; nothing written (add --apply)", file=sys.stderr)
        return 1 if p["no_id"] else 0
    except ValueError as e:
        print(f"project record: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
