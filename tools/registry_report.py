#!/usr/bin/env python3
"""tools/registry_report.py — the daily audit's project registry check: what is wrong with the project record and the pages it points at, each problem with the command that fixes it.

A project is defined by its entry in the project record (project_registry.py); the page it points at is a copy stackshot writes three lines of (`display-name:`, `agents:`, `status:`). The record and the
pages are written by different hands, so they drift. This lists the problems, each with the fix, and the audit sends them to the project's -main agent (page_agent_report's recipients), once a day, until
they are fixed. Read only: it changes no page, no record, and sends nothing. Stdlib plus the repo's modules, Python 3.11+. Beside tools/page_agent_report.py, which it is modeled on and shares its message with.

What it flags (one finding is {"page", "line", "name", "fix", "project"}; the line is the kind):

  page with no project          a top-level page that is `type: project`, active, and that no entry points at (nor ever did): the page is read by nobody for its agents, status or name. Fix: `tools/project.py adopt <page>`
  project's page is gone        an active entry whose page pointer names a page that is neither in the registry nor in the page store. The project is kept (items, agents and history stay on the id); only the pointer is flagged
  page lines differ             a project whose page does not mirror its entry: `display-name:`, `status:` or `agents:` read other than the record says (an edit made on the page to a mirrored line is not read), or the page lists an
                                agent the record lacks, which stops the mirror from writing the block. Fix: `tools/project.py mirror <project>` (or, for the second kind, `agent-add` first)
  agent on no live session      an agent of a project the page registry cannot show (an entry with no page of this store, so page_agent_report never reads its map), or a pending agent (listed through the form, its page line still owed)
                                that sala does not know. Fix: `tools/project.py agent-retire` (or `agent-rename` when the session was renamed). A mirrored agent of a project with a page is page_agent_report's line, not repeated here
  item id names no project      items that store a `project_id` that no entry has. Fix: re-file them to the project's page (`update` with `project`), which stores the right id
  open items on a key no project owns
                                open items whose `project` names no project (no entry points at it, owns it as a sub-page or knew it as a former key). Fix: re-file them, or adopt the page when it is a project's
  two projects on one page      two or more live (not archived) entries that point at one page. Fix: archive the stray, or give it a page of its own with `move-page`

A `parent:` line is not checked: nothing in the project registry reads it (projects.py: it makes no sub-page), so a line off the key tree is no error of the record.

Not checked when the record has no projects (an instance that has not made its record: every page would read as "no project"), or when it cannot be read. Each check that needs a source (sala's session list, the page store,
the board items) is skipped, with a note, when that source cannot be read; it never makes the others fail. The agent check follows page_agent_report's guard against a cut-short session list. A page is "gone" only when its read
came back clean (not found), not when it failed, and not when the published page registry is empty. When sala's session list cannot be read the findings have no recipient (`to` is empty) and the audit sends nothing.

  tools/registry_report.py                 the problems, one line each (page · problem · name · fix · who is told), then the counts
  tools/registry_report.py --line          the one line the audit carries
  tools/registry_report.py --json          {"checked", "note", "projects", "pages", "findings": [{page, line, name, fix, project, to}]}
  tools/registry_report.py --sessions FILE read the sessions from FILE (a copy of `sala sessions --json`) instead of calling sala

The audit calls it through `audit.py registry` and sends the findings in its daily run (audit_run.py). Exit 0."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))
import anchors as _anc  # noqa: E402
import page_agent_report as _par  # noqa: E402
import project_registry as _pr  # noqa: E402
import projects as _prj  # noqa: E402

LINE_NO_PROJECT = "page with no project"
LINE_GONE = "project's page is gone"
LINE_DRIFT = "page lines differ"
LINE_AGENT = "agent on no live session"
LINE_ID = "item id names no project"
LINE_KEY = "open items on a key no project owns"
LINE_TWO = "two projects on one page"
SHOWN = 6                # items or ids named on one line; the rest are counted


# ---------------------------------------------------------------------------- small helpers
def _norm(x: Any) -> str:
    return _pr._norm_key(x)


def _top2(key: str) -> str:
    return "/".join(key.split("/")[:2])


def _f(page: str, line: str, name: str, fix: str, project: str = "") -> dict[str, str]:
    return {"page": page, "line": line, "name": name, "fix": fix, "project": project}


def _label(pid: str, e: dict[str, Any]) -> str:
    return _pr.page_key(e) or str(e.get("name") or "") or pid


class _Reader:
    """A page store seen read only, with the text of each page it was asked for kept (`mirror` in dry mode only calls `get`)."""

    def __init__(self, get: Callable[[str], tuple[str | None, str | None]]):
        self._get = get
        self.text: dict[str, str | None] = {}
        self.failed: set[str] = set()

    def get(self, key: str) -> tuple[str | None, str | None]:
        if key in self.text:
            c = self.text[key]
            return (c, "r") if c is not None else (None, None)
        try:
            c, rev = self._get(key)
        except Exception:  # noqa: BLE001 — a page that cannot be read is not a page that is gone
            self.failed.add(key)
            self.text[key] = None
            return None, None
        self.text[key] = c if (c is not None and rev) else None
        return (c, rev) if self.text[key] is not None else (None, None)


# ---------------------------------------------------------------------------- the checks
def no_project(ents: dict, reg: dict) -> list[dict[str, str]]:
    """Active `type: project` pages that are no sub-page and that no entry points at (or ever did)."""
    cur, old = _pr.by_page(ents), _pr.by_former_key(ents)
    out = []
    for key in sorted(reg):
        e = reg[key]
        if not isinstance(e, dict) or str(e.get("type") or "").strip().lower() != "project" or not _prj.page_active(e):
            continue
        if _prj.is_sub_page(key, reg, e) or "/" in key.partition("/")[2] or key in cur or key in old:
            continue
        out.append(_f(key, LINE_NO_PROJECT, str(e.get("title") or key),
                      f"no project owns this page, so its agents map is not a record: run `tools/project.py adopt {key}` (the page is a pointer after; add `--name <name>` if its display-name: line is missing, invalid (400) or taken (409))"))
    return out


def two_on_one_page(ents: dict) -> list[dict[str, str]]:
    by: dict[str, list[str]] = {}
    for pid, e in sorted(ents.items()):
        k = _pr.page_key(e)
        if k and (e.get("status") or "active") != "archived":         # an archived project keeps its page pointer as history: it does not share the page with a live one
            by.setdefault(k, []).append(pid)
    out = []
    for k, pids in sorted(by.items()):
        if len(pids) > 1:
            who = ", ".join(f"{p} ({ents[p].get('name') or 'no name'}, {ents[p].get('status') or 'active'})" for p in pids)
            out.append(_f(k, LINE_TWO, who, f"a page belongs to one project: archive the one that is not this page's (`tools/project.py archive <id>`), or give it a page of its own (`tools/project.py move-page <id> <new key>`); {len(pids)} entries point here",
                          pids[0]))
    return out


def pages_and_drift(ents: dict, reg: dict, reader: _Reader) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """(the projects whose page is gone, the projects whose page lines differ from the entry). The page store is read for each entry that points at a page of this instance, and a page is gone only when
    the store says it is not there and the registry lacks it too (two witnesses), and its read did not fail: a read that fails says nothing."""
    import project_verbs as pv  # noqa: PLC0415 — the mirror's own comparison, so a page listed here is one the next mirror write changes
    gone: list[dict[str, str]] = []
    drift: list[dict[str, str]] = []
    for pid, e in sorted(ents.items()):
        key = _pr.page_key(e)
        if not key:
            continue
        m = pv.mirror(pid, reader, entry=e, dry=True)
        st = m["state"]
        if st == "no-page":
            if key not in reg and key not in reader.failed and (e.get("status") or "active") != "archived":
                gone.append(_f(key, LINE_GONE, str(e.get("name") or pid),
                               f"the project ({pid}) is kept with its items and agents; only its page pointer names a page that is not in the page store: restore the page there if it was deleted by mistake, "
                               f"else make it again from the template with `tools/project.py mirror {pid} --make-page`", pid))
        elif st == "would-write":
            lines = pv.mirror_drift(reader.text.get(key) or "", e)
            drift.append(_f(key, LINE_DRIFT, ", ".join(lines) or "mirrored lines",
                            f"the page does not read as the record says (an edit made on the page to a mirrored line is not read): `tools/project.py mirror {pid}` writes them again; to keep the page's version, "
                            f"change the record first (`agent-add`, `agent-retire`, `rename`, `archive`)", pid))
        elif st == "failed":
            note = str(m.get("note") or "")
            if note:
                drift.append(_f(key, LINE_DRIFT, "not writable", note[:300], pid))
    return gone, drift


def agents_not_live(ents: dict, reg: dict, pending: dict, sessions: tuple[set[str], set[str]] | None) -> tuple[list[dict[str, str]], str]:
    """(the agents sala does not know, a note when the check was not made). Entries the page registry cannot show, and every pending agent."""
    if sessions is None:
        return [], "sala's session list is not readable: agents not checked"
    names, aliases = sessions
    if not names:
        return [], "sala lists no session: agents not checked"
    known = names | aliases
    found: list[dict[str, str]] = []
    read: set[str] = set()
    for pid, e in sorted(ents.items()):
        if (e.get("status") or "active") == "archived":
            continue
        key = _pr.page_key(e)
        if key and key in reg:
            continue                           # page_agent_report reads this map through the registry
        for n in (e.get("agents") or {}):
            if _par._ID_RX.match(n):
                continue
            read.add(n)
            if n not in known:
                found.append(_f(_label(pid, e), LINE_AGENT, n,
                                f"sala has no session of this name: take it off the project's agents map with `tools/project.py agent-retire {pid} {n}` (or `agent-rename {pid} {n} <new name>` when the session was renamed)", pid))
    for pid, ag in sorted((pending or {}).items()):
        e = ents.get(pid) or {}
        if (e.get("status") or "active") == "archived":
            continue
        for n in sorted(ag):
            if _par._ID_RX.match(n):
                continue
            read.add(n)
            if n not in known:
                found.append(_f(_label(pid, e) if e else (_prj.id_to_key(pid, reg) or pid), LINE_AGENT, n,
                                f"pending agent (its page line was never written) and sala has no session of this name: drop it with `tools/project.py agent-retire {pid} {n}`", pid))
    unknown = {f["name"] for f in found}
    if len(unknown) >= _par.UNKNOWN_MIN and len(unknown) > _par.UNKNOWN_SHARE * len(read):
        return [], f"sala's session list looks partial: {len(unknown)} of {len(read)} names unknown: agents not checked"
    return found, ""


def item_findings(ents: dict, items: Any, no_proj_pages: set[str], reg: dict) -> list[dict[str, str]]:
    """The two item checks, on open items: an id that is in neither the record's entries nor its id table (item_project.derive would read it as no project), and a key nothing owns."""
    import item_project as ip  # noqa: PLC0415
    bad_ids: dict[str, list[str]] = {}
    keys: dict[str, list[str]] = {}
    known = set(ip._tables()[0])                # id → page key of the record's id table
    for gid, t in (items.items() if isinstance(items, dict) else enumerate(items or [])):
        if not isinstance(t, dict):
            continue
        if t.get("status") == "completed":
            continue
        meta = t.get("metadata") if isinstance(t.get("metadata"), dict) else {}
        shown = str(t.get("gid") or gid)
        have = str(meta.get(ip.FIELD) or "").strip()
        if _pr.is_id(have) and have not in ents and have not in known:      # an id the record's id table knows is a project that has no entry (yet), which item_project.derive reads as that project
            bad_ids.setdefault(have, []).append(shown)
            continue
        if have in ents:
            continue
        key = _norm(meta.get("project"))
        if not key or _pr.is_id(key):
            continue
        if not ip.derive(key):
            keys.setdefault(key, []).append(shown)
    out = []
    for pid, shown in sorted(bad_ids.items()):
        k = _prj.id_to_key(pid, reg)
        if k and k in no_proj_pages:
            continue                           # the page is already flagged as a page with no project
        out.append(_f(k or pid, LINE_ID, f"{pid} on {_items(shown)}",
                      "the record has no project of this id: re-file each item to its project's page (`update` with `project`), which stores the project's id; the id is not recreated from nothing", ""))
    for key, shown in sorted(keys.items()):
        if key in no_proj_pages:
            continue
        out.append(_f(key, LINE_KEY, f"{len(shown)} open item{'' if len(shown) == 1 else 's'}: {_items(shown)}",
                      f"no project owns {key}: re-file the items to their project's page (`update` with `project`); if {key} is a project's page, make it one with `tools/project.py adopt {key}`", ""))
    return out


def _items(shown: list[str]) -> str:
    s = sorted(shown, key=lambda x: (len(x), x))
    return ", ".join(s[:SHOWN]) + (f" and {len(s) - SHOWN} more" if len(s) > SHOWN else "")


# ---------------------------------------------------------------------------- the whole check
def scan(*, ents: dict, reg: dict, sessions: tuple[set[str], set[str]] | None, items: Any, pending: dict,
         page_get: Callable[[str], tuple[str | None, str | None]] | None) -> dict[str, Any]:
    """The problems of the record `ents` against the page registry `reg` (key → row, pages alone; an empty one is a registry that was not published, which checks no page as gone), the page store `page_get` (None: no
    page is read; it raises when a read fails and answers (None, None) only for a page that is not there), sala's `sessions`, the board `items` and the pending agents. → {"checked", "note", "projects", "pages", "findings"}; each finding lacks `to` (see `route`)."""
    if not ents:
        return {"checked": False, "note": "the project record has no projects", "silent": True, "projects": 0, "pages": len(reg), "findings": []}
    notes: list[str] = []
    found: list[dict[str, str]] = []
    npp = no_project(ents, reg)
    found += npp
    found += two_on_one_page(ents)
    if page_get is not None:
        reader = _Reader(page_get)
        gone, drift = pages_and_drift(ents, reg, reader)
        if not reg:
            gone = []
            notes.append("the page registry is empty: pages gone not checked")
        found += gone + drift
        if reader.failed:
            notes.append(f"{len(reader.failed)} page(s) could not be read from the page store")
    else:
        notes.append("the page store is not readable: pages and mirrors not checked")
    ag, why = agents_not_live(ents, reg, pending, sessions)
    found += ag
    if why:
        notes.append(why)
    if items is not None:
        found += item_findings(ents, items, {f["page"] for f in npp}, reg)
    else:
        notes.append("the board items could not be read: item ids and keys not checked")
    return {"checked": True, "note": "; ".join(notes), "silent": False, "projects": len(ents), "pages": len(reg), "findings": found}


def recipient(f: dict[str, str], ents: dict, ov: dict, live: set[str]) -> str:
    """The agent a finding goes to: its project's own -main agent when sala knows it, else the page's (page_agent_report.recipient: its -main, the top-level page's, the hub's, the scope's general one). "" = none is live."""
    e = ents.get(f.get("project") or "")
    if e and e.get("agents"):
        row = {"agents": {n: str(a.get("mandate_line") or "") for n, a in e["agents"].items()},
               "back_agents": {n: "" for n, a in e["agents"].items() if not a.get("front", True)}}
        m = _anc.main_of(row)
        if m and m in live:
            return m
    try:
        return _par.recipient(f["page"], ov, live)
    except Exception:  # noqa: BLE001 — a page that is no key, a registry that cannot say
        return ""


def route(res: dict[str, Any], ents: dict, ov: dict, sessions: tuple[set[str], set[str]] | None) -> dict[str, Any]:
    """`to` on every finding. When sala's list cannot be read (or lists no session) nobody can be said to be live: `to` stays empty on every finding and the result is marked `unrouted`, which the audit reads as
    "send nothing" (an empty `to` would otherwise go to the audit's -main agent)."""
    live = (sessions[0] | sessions[1]) if sessions else set()
    res["unrouted"] = not live
    for f in res["findings"]:
        f["to"] = recipient(f, ents, ov, live) if live else ""
    return res


def read(*, ents: dict | None = None, reg: dict | None = None, ov: dict | None = None, sessions: Callable[[], Any] | None = None, items: Any = None, pending: dict | None = None,
         page_get: Callable[[str], tuple[str | None, str | None]] | None = None, live_pages: bool = True) -> dict[str, Any]:
    """The whole check on live data (or on what is given). Each source is read once; one that cannot be read is a check not made, with a note, never an error. `live_pages` False leaves the page store
    unread when none is given (a caller with no server box behind it). The page store is read with `get_strict` where it has one (a read that fails raises, so it is never taken for a missing page)."""
    ents = _pr.entries() if ents is None else ents
    if not ents:
        return {"checked": False, "note": "the project record has no projects", "silent": True, "projects": 0, "pages": 0, "findings": []}
    reg = _prj.registry_raw() if reg is None else reg
    ov = (_anc.registry() if ov is None else ov)
    got = (sessions or _anc.sala_sessions)()
    if items is None:
        try:
            items = _anc.items()
        except Exception as ex:  # noqa: BLE001
            print(f"registry_report: the board items could not be read ({type(ex).__name__}: {ex})", file=sys.stderr)
    if pending is None:
        pending = _prj._pending_all()
    if page_get is None and live_pages:
        try:
            import page_debt as _pd  # noqa: PLC0415
            io = _pd.page_io()
            page_get = getattr(io, "get_strict", io.get)
        except Exception as ex:  # noqa: BLE001
            print(f"registry_report: the page store could not be opened ({type(ex).__name__}: {ex})", file=sys.stderr)
    return route(scan(ents=ents, reg=reg, sessions=got, items=items, pending=pending, page_get=page_get), ents, ov, got)


def line_of(f: dict[str, Any]) -> str:
    return f"{f['page']} · {f['line']} · {f['name']} · {f['fix']}"


def summary_line(res: dict[str, Any]) -> str:
    if not res["checked"]:
        return f"Project registry: not checked ({res['note']})"
    fs = res["findings"]
    return f"Project registry: {len(fs)} problem(s) on {len({f['page'] for f in fs})} page(s)" + (f" ({res['note']})" if res["note"] else "")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="audit.py registry", description="List what is wrong with the project record and the pages it points at, each with its fix (read only: nothing is sent or written).")
    ap.add_argument("--line", action="store_true", help="print the one line the audit carries")
    ap.add_argument("--json", action="store_true", help="print the whole report as JSON")
    ap.add_argument("--sessions", help="read the sessions from this file (a copy of `sala sessions --json`) instead of calling sala")
    a = ap.parse_args(argv)
    res = read(sessions=(lambda: _par.sessions_from_file(a.sessions)) if a.sessions else None)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    elif a.line:
        print(summary_line(res))
    else:
        for f in res["findings"]:
            print(f"{line_of(f)} · tell {f['to'] or '(no live -main agent: the audit agent)'}")
        print(summary_line(res) + (f" · {res['projects']} project(s), {res['pages']} page(s) read" if res["checked"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
