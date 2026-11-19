"""project_registry.py — the projects of the project record: one entry per permanent project id, and the one place the registry's readers resolve a project.

A project is defined on its own. Its entry in `<store>/project-record.json` (the section `projects`, keyed by the permanent id `prj_<8 hex>`) holds what the
project is; the knowledge-base page it points at is one optional field of it. The page's own lines (`display-name:`, `agents:`, `status:`, `hub:`) are what the
registry was derived from until now; with an entry, the entry is read first and the page line is the fallback. A project with no entry is read exactly as before.

An entry (every field optional unless said):

    name           the project's name, the prefix of its agents' names (`<name>-<role>`)
    title, type    what the registry shows ("project")
    scope          one of [project_scopes] order
    status         "active" | "archived" (default active)
    agents         {agent name: {"front": bool, "mandate_line": str, "keeper": true}} in the order the project lists them (the first builder listed is the builder). `keeper: true` marks the
                   project's keeper: at most one agent of the entry carries it (a second flag is ignored and reported, never an error); with none the keeper is derived (keeper.py)
    page_keepers   {sub-page key: agent name}: the sub-pages under this project's page that carry a keeper mark of their own (keeper.py). The agent need not be on this project's map, only listed by some
                   project; a name nobody lists, or a key that is no page under the project, is ignored and reported on this project's row (`keeper_problems`), never an error. An empty name hands the
                   page back to the page above it (its keeper follows that page's)
    hub            the page key of the project this one belongs to ("" = none)
    page           the pointer to the project's knowledge-base page: a page key of this instance's page store, or any link to another knowledge base; absent = the project has none
    former_keys    page keys the project's page had before ("projects/old-name"), so a stored key still finds the project
    former_names   names the project had before
    former_agents  names of agents a retire or a rename took off the agents map (the page may list them until its mirror is written; the mirror does not take that for a line added by hand)
    made, retired  {"at": ISO time, "by": who, "how": "made" | "adopted" | "migrated"}; `retired` only once the status is archived. `made.revision` (adopted only) is the revision of the page the entry was read from

The section is versioned (`projects_schema`, 1) and sits beside the older tables of the file (`ids`, `pending_agents`, `marks`) whose schema stays 1: a code that
does not know the section keeps it untouched when it rewrites the file (projects.py `_read` keeps every other top-level field).

The read path, in one place:

    entries()       every entry by id, read from the file when it changed; {} when there is none or the section is damaged (the readers then fall back to the pages)
    resolve(x)      an id, a page key (a current page or one of a project's former keys), a bare slug or a former name → the project's view, or None
    page_key_of(i)  the page key of the project with id i, "" when it has none (or none that is a key)
    pageless(x)     the view of a project the record says has no page, else None
    apply(reg)      the page registry with the entries laid over it (title, type, name → session/role, status, hub, agents, scope), page lines where an entry has no field

The registry as the server reads it, and the two files it keeps (the helpers that more than one part of the server reads):

    _registry(name)       a registry file of the store ([registries]); `projects` has the record's entries laid over the pages' lines
    _roles_sync()         <state>/roles.json, every session's role, rewritten when the roles changed or the file is ROLES_EVERY old (`_roles_sync_safe` also keeps projects.json)
    _projects_sync()      <state>/projects.json, the project record's published file

Stdlib only at load: config.py, readonly.py, store.py (core/) and keeper.py (itself stdlib only at load) are its imports. projects.py, anchors.py and renamed_agents.py are imported inside the functions that need them, since they import this module;
so is the router (router_live, with the anchors and routing modules it reads): keeper.derive imports it lazily, the first time a row's keeper is derived (apply, for the rows an entry changes), never at load."""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from stackshot.core import config as _cfg
from stackshot.core import readonly as _ro
from stackshot.core import store as _store
from stackshot.projects import keeper as _kp         # the keeper as a mark on one agent: stdlib only at load (its router import is lazy, in keeper.derive)

SCHEMA = 1
SECTION = "projects"                  # the top-level field of project-record.json that holds the entries
VERSION = "projects_schema"           # …and the field that holds their schema
ID_RE = re.compile(r"^prj_[0-9a-f]{8}$")
STATUSES = ("active", "archived")
HOWS = ("made", "adopted", "migrated")
_STR_FIELDS = ("name", "title", "type", "scope", "hub", "page")


def is_id(x: Any) -> bool:
    return bool(ID_RE.match(str(x or "").strip()))


def record_path() -> Path:
    return _cfg.path("paths", "store") / "project-record.json"


# ---------------------------------------------------------------------------- reading
def parse(doc: Any) -> dict:
    """The entries of a parsed record file ({id: entry}); {} when it has no such section. Raises ValueError, naming the first problem, when the section
    or one entry is not valid: a reader then falls back to the pages, and nothing is written over it."""
    if not isinstance(doc, dict):
        raise ValueError("the record is not an object")
    if doc.get(VERSION, SCHEMA) != SCHEMA:
        raise ValueError(f"{VERSION} {doc.get(VERSION)!r}, this code reads {SCHEMA}")
    sec = doc.get(SECTION, {})
    if not isinstance(sec, dict):
        raise ValueError(f"{SECTION} is not an object")
    for i, e in sec.items():
        bad = lambda why, i=i: ValueError(f"{SECTION} entry {i!r}: {why}")
        if not is_id(i) or not isinstance(e, dict):
            raise bad("not an id with an object")
        for f in _STR_FIELDS:
            if f in e and not isinstance(e[f], str):
                raise bad(f"{f} is not a string")
        if e.get("status", "active") not in STATUSES:
            raise bad(f"status {e.get('status')!r}")
        if "agents" in e:
            ag = e["agents"]
            if not isinstance(ag, dict) or not all(isinstance(n, str) and n and isinstance(a, dict) and isinstance(a.get("front"), bool)
                                                   and isinstance(a.get("mandate_line", ""), str) for n, a in ag.items()):
                raise bad("agents")
        for f in ("former_keys", "former_names", "former_agents"):
            if f in e and not (isinstance(e[f], list) and all(isinstance(x, str) and x for x in e[f])):
                raise bad(f"{f} is not a list of strings")
        if _kp.PAGES in e and not (isinstance(e[_kp.PAGES], dict) and all(isinstance(k, str) and k and isinstance(v, str) for k, v in e[_kp.PAGES].items())):
            raise bad(f"{_kp.PAGES} is not a map of page keys to agent names")
        for f in ("made", "retired"):
            if f in e:
                m = e[f]
                if not (isinstance(m, dict) and isinstance(m.get("at"), str) and isinstance(m.get("by"), str) and m.get("how") in HOWS):
                    raise bad(f"{f} needs at, by and how ({'|'.join(HOWS)})")
        if "retired" in e and e.get("status") != "archived":
            raise bad("retired is set on a project that is not archived")
    return sec


_CACHE: dict = {"sig": None, "entries": {}}
_WARNED: set = set()


def _sig(p: Path) -> Any:
    try:
        st = os.stat(p)
        return (str(p), st.st_mtime_ns, st.st_size, st.st_ino)
    except OSError:
        return (str(p), None)


def record_error() -> str:
    """"" when the record file is missing or reads (entries() would answer from it), else why it cannot be read. entries() hides this on purpose (the readers fall back to the
    pages); a caller that must not take the pages' lines for the record's, such as `projects fields` for a script, asks here first."""
    try:
        parse(json.loads(record_path().read_text(encoding="utf-8")))
    except FileNotFoundError:
        return ""
    except (OSError, ValueError) as e:
        return f"{record_path()} cannot be read ({e})"
    return ""


def entries() -> dict:
    """Every entry by id ({} when the file has none, is missing, or cannot be read: the readers fall back to the pages). Parsed again only when the file changed.
    The dict is shared: a caller never changes it (resolve and apply hand out copies)."""
    p = record_path(); sig = _sig(p)
    if _CACHE["sig"] == sig:
        return _CACHE["entries"]
    ents: dict = {}
    try:
        ents = parse(json.loads(p.read_text(encoding="utf-8")))
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        if sig not in _WARNED:
            _WARNED.add(sig)
            print(f"project record: the project entries are not read, the pages answer ({e})", file=sys.stderr, flush=True)
    _CACHE.update(sig=sig, entries=ents)
    return ents


def page_key(e: dict | None) -> str:
    """An entry's page pointer as a key of this instance's page store ("" when absent, or when it is a link to another knowledge base)."""
    v = str((e or {}).get("page") or "").strip().strip("/")
    if v.endswith(".md"):
        v = v[:-3]
    return "" if (not v or "://" in v or re.search(r"\s", v)) else v


def _norm_key(x: Any) -> str:
    x = str(x or "").strip().strip("/")
    return x[:-3] if x.endswith(".md") else x


def view(pid: str, e: dict, via: str = "") -> dict:
    """The read model of one project: what every reader asks of it, so none reads the entry's fields itself. `has_page` is whether the record says the project
    has a page at all (a pointer that is a link elsewhere counts); `page_key` is that pointer as a key of this instance's page store, "" when it is not one."""
    return {"id": pid, "name": e.get("name", ""), "title": e.get("title", ""), "type": e.get("type") or "project", "scope": e.get("scope", ""),
            "status": e.get("status") or "active", "archived": (e.get("status") or "active") == "archived", "hub": e.get("hub", ""),
            "page": e.get("page", ""), "page_key": page_key(e), "has_page": bool(e.get("page")),
            "agents": copy.deepcopy(e.get("agents") or {}), "former_keys": list(e.get("former_keys") or []), "former_names": list(e.get("former_names") or []),
            "made": copy.deepcopy(e.get("made")), "retired": copy.deepcopy(e.get("retired")), "via": via}


def by_page(ents: dict | None = None) -> dict:
    """page key → id for the entries whose pointer is a key."""
    out: dict = {}
    for pid, e in sorted((entries() if ents is None else ents).items()):
        k = page_key(e)
        if k:
            out.setdefault(k, pid)
    return out


def by_former_key(ents: dict | None = None) -> dict:
    """a former page key → id (the first project listing it; a key that is a current page is that page's)."""
    out: dict = {}
    for pid, e in sorted((entries() if ents is None else ents).items()):
        for k in e.get("former_keys") or []:
            out.setdefault(_norm_key(k), pid)
    return out


def top_page(key: str, pages: dict, hub_of: Callable[[str], str] | None = None) -> str:
    """The page that owns the sub-page `key`: the nearest ancestor key that `pages` (a mapping with that key) holds, or the page a `hub:` line names (`hub_of(key)`). "" for a key that is no sub-page."""
    h = hub_of(key) if hub_of else ""
    if h:
        return h
    parts = key.split("/")
    for n in range(len(parts) - 1, 1, -1):
        up = "/".join(parts[:n])
        if up in pages:
            return up
    return ""


def resolve(x: Any, hub_of: Callable[[str], str] | None = None) -> dict | None:
    """The one lookup: an id, a page key, a bare slug (matched through [registries.projects] match, as projects.ref does), a former page key or a former
    name → the project's view (`via` says which), or None. A project with no page resolves by its id and its names only. A sub-page (a key under a project's page, or a page that
    `hub_of(key)` sends to one) is never a project: it resolves to the top-level project that owns it (`via` "sub_page"). Reads the entries; never the pages."""
    x = str(x or "").strip()
    ents = entries()
    if not x or not ents:
        return None
    if is_id(x):
        return view(x, ents[x], "id") if x in ents else None
    k = _norm_key(x)
    pats = (_cfg.CFG.get("registries", {}).get("projects", {}) or {}).get("match") or ["{value}"]
    cands = list(dict.fromkeys([k] + [p.format(value=k) for p in pats]))
    cur, old = by_page(ents), by_former_key(ents)
    for c in cands:
        if c in cur:
            return view(cur[c], ents[cur[c]], "page")
    for c in cands:
        if c in old:
            return view(old[c], ents[old[c]], "former_key")
    for pid, e in sorted(ents.items()):
        if k and k in (e.get("former_names") or []):
            return view(pid, e, "former_name")
    for c in cands:
        up = top_page(c, {**cur, **old}, hub_of)
        if up:
            return view((cur.get(up) or old[up]), ents[cur.get(up) or old[up]], "sub_page")
    return None


def page_key_of(pid: str) -> str:
    """The page key of the project with this id, "" when there is no such project or it has none."""
    e = entries().get(str(pid or "").strip())
    return page_key(e) if e else ""


def pageless(x: Any) -> dict | None:
    """The view of the project `x` names when the record says it has no page (no pointer at all); None for any other case, a pointer that does not resolve included."""
    v = resolve(x)
    return v if v and not v["has_page"] else None


# ---------------------------------------------------------------------------- the overlay
def _retired_words() -> set:
    from stackshot.projects import projects as _p
    return _p.retired_statuses()


def _status_word(cur_word: str, status: str, retired: set) -> str:
    """The registry `status:` word for an entry's status: the page's own word when it already means the same (closed, done and archived all mean archived), else
    the canonical one."""
    cur = str(cur_word or "").strip()
    if status == "archived":
        return cur if cur.lower() in retired else ("archived" if "archived" in retired or not retired else sorted(retired)[0])
    return cur if cur.lower() not in retired else "active"


def _overlay(cur: dict, e: dict, retired: set) -> dict:
    new = dict(cur)
    for f in ("title", "type", "scope"):
        if e.get(f):
            new[f] = e[f]
    under = _kp.name_line(cur)                                   # what the page's own lines give the row (with a page mark on it, what the mark took the place of)
    if e.get("name"):
        under = (e["name"], "name")
    mark, problems = _kp.record_mark(e.get("agents")) if "agents" in e else ("", [])
    listed = e["agents"] if "agents" in e else (cur.get("agents") or {})
    page_mark = _kp.row_mark(cur)
    if page_mark and page_mark not in listed:                    # the record removed the agent the page marks: the visible `keeper:` line is not read, and the row says why
        problems = [*problems, f"`keeper: {page_mark}` on the page names an agent the project record does not list; the record's agents rule, so the line is ignored"]
    mark = mark or (page_mark if page_mark in listed else "")    # the record's flag first, else the mark the page's own `keeper:` line gave
    if mark:                                                     # the marked agent is the row's keeper; the old name line stays beside it
        new["session"] = mark; new["role"] = _kp.MARK
        for k, v in (("legacy_session", under[0]), ("legacy_role", under[1])):
            if v:
                new[k] = v
            else:
                new.pop(k, None)
    else:
        if e.get("name"):
            new["session"] = e["name"]; new["role"] = "name"
        elif cur.get("role") == _kp.MARK:                        # a page mark whose agent the record no longer lists: the old lines answer again
            new["session"] = under[0]
            if under[1]:
                new["role"] = under[1]
            else:
                new.pop("role", None)
        if e.get("name") or cur.get("role") == _kp.MARK:
            new.pop("legacy_session", None); new.pop("legacy_role", None)
    if problems:
        new["keeper_problems"] = [*(cur.get("keeper_problems") or []), *problems]
    if "status" in e:
        new["status"] = _status_word(cur.get("status", ""), e["status"], retired)
    if "hub" in e:
        if e["hub"]:
            new["hub"] = e["hub"]
        else:
            new.pop("hub", None)
    if "agents" in e:
        ag = {n: str(a.get("mandate_line", "")) for n, a in e["agents"].items()}
        back = {n: ag[n] for n, a in e["agents"].items() if not a.get("front", True)}
        for k, v in (("agents", ag), ("back_agents", back)):
            if v:
                new[k] = v
            else:
                new.pop(k, None)
    return new


def _differs(a: dict, b: dict) -> bool:
    return a != b or any(list(a.get(k) or {}) != list(b.get(k) or {}) for k in ("agents", "back_agents"))


def _top(key: str) -> str:
    return "/".join(key.split("/")[:2])


def _inherit_marks(out: dict, tops: set) -> None:
    """The sub-pages under the pages of `tops` that take a mark from above (an unnamed one: role "inherited", or no role and no session at all, which is what a project with agents and no
    `display-name:` leaves its sub-pages) take it as their `session` with the role "inherited" (`legacy_session` and `legacy_role` keep what they were), and one that no longer has a mark
    above it takes its old value back. Rows are copied before they change."""
    for k in sorted(out, key=lambda x: x.count("/")):
        row = out[k]
        if _top(k) not in tops or not isinstance(row, dict):
            continue
        had = "legacy_role" in row or "legacy_session" in row
        unnamed = row.get("role") == "inherited" or (not row.get("role") and not row.get("session"))
        if not unnamed and not had:
            continue
        up = _kp.above(k, out); m = ""
        while up and not m:
            r = out[up]
            m = str(r.get("session") or "") if r.get("role") == _kp.MARK else ""
            up = _kp.above(up, out) if r.get("role") == "inherited" and not m else ""
        was_role = str(row.get("legacy_role") if had else row.get("role") or "")      # the role the row had before it took a mark ("" for a row nothing kept)
        old = str((row.get("legacy_session") if had else row.get("session")) or "")
        if m and unnamed and (row.get("session") != m or not had):
            row = out[k] = dict(row); row["session"] = m; row["role"] = "inherited"
            row["legacy_role"] = was_role                # what the row was: a name-line reader (keeper.name_line) must not take its old session for a name line of its own
            if old:
                row["legacy_session"] = old
        elif not m and had and "legacy_role" in row and row.get("role") == "inherited":
            row = out[k] = dict(row); row["session"] = old; row.pop("legacy_session", None); row.pop("legacy_role", None)
            if was_role:
                row["role"] = was_role
            else:
                row.pop("role", None)


def _listed_agents(rows: dict, ents: dict) -> set:
    """Every agent name some project lists: on the agents map of a row of `rows` (the entries are laid over it) or of an entry of `ents`."""
    out: set = set()
    for src in (*rows.values(), *ents.values()):
        if isinstance(src, dict) and isinstance(src.get("agents"), dict):
            out.update(str(n) for n in src["agents"])
    return out


def _lay_page_keepers(base: dict, ents: dict) -> dict:
    """The registry `base` with the sub-page marks of the entries laid over it (`page_keepers`, keeper.py). A sub-page whose name is an agent some project lists keeps the role it had and gets
    `session` = that agent and `page_mark: true`: a reader of `session` and `role` answers as it did for the page's `agent:` line, and `keeper.fields` says "mark". The sub-pages under it do
    not inherit from it (a page an agent keeps never passed its keeper down). An empty name makes the page follow the keeper above it: role "inherited", `session` that keeper's, the old
    `agent:` line kept as `legacy_session` and `legacy_role`. A mark that cannot be read (a key that is no page under the project, a page with a name line or a `keeper:` line of its own, a name no
    project lists) is ignored and said on the project's row (`keeper_problems`): the page's own lines answer, as before. Rows are copied before they change; `base` itself is never changed."""
    jobs = [(e, page_key(e)) for _pid, e in sorted(ents.items()) if isinstance(e.get(_kp.PAGES), dict) and e[_kp.PAGES] and page_key(e) in base]
    if not jobs:
        return base
    out = dict(base); said: dict = {}; marked: list = []; handed: list = []; known: set | None = None; claimed: dict = {}
    tops = sorted({page_key(x) for x in ents.values() if page_key(x)})
    for e, top in jobs:
        for raw_key, who in sorted(e[_kp.PAGES].items()):
            k = _norm_key(raw_key); row = out.get(k); why = ""
            near = max((t for t in tops if k.startswith(t + "/")), key=len, default="")
            if not k.startswith(top + "/") or not isinstance(row, dict):
                why = "is no page under the project"
            elif near != top:
                why = f"is held on the entry of {top}, but the nearest project above it is {near} (a page's mark lives on that entry)"
            elif k in claimed:
                why = f"is marked twice (the entry of {claimed[k]} holds a mark for it too, and that one rules)"
            elif row.get("role") == "name":
                why = "has a project name line (`display-name:`) of its own, which a keeper mark does not replace"
            elif row.get("role") == _kp.MARK:
                why = "has a `keeper:` line of its own, which rules"
            elif who:
                known = _listed_agents(out, ents) if known is None else known
                if who not in known:
                    why = f"{who} is not an agent any project lists"
            elif row.get("role") != "agent":
                continue                                   # nothing to hand back: the page follows the page above it already
            if why:
                said.setdefault(top, []).append(f"page keeper of {k}: {why}; ignored, the page's own lines answer")
                continue
            new = out[k] = dict(row); claimed[k] = top
            if who:
                new["session"] = who; new["role"] = "agent"; new[_kp.PAGE_MARK] = True
                new.pop("legacy_session", None); new.pop("legacy_role", None)
                marked.append(k)
            else:
                new["legacy_session"] = str(row.get("session") or ""); new["legacy_role"] = "agent"; new["role"] = "inherited"
                handed.append(k)
    for k in sorted(handed, key=lambda x: x.count("/")):    # the nearest page above that keeps its own keeper, read after the marks and the pages handed back above it
        up = _kp.above(k, out); s = str((out[up].get("session") if up else "") or "")
        if s:
            out[k]["session"] = s
        else:
            out[k].pop("session", None); out[k].pop("role", None)
    for top, lines in said.items():
        out[top] = dict(out[top]); out[top]["keeper_problems"] = [*(out[top].get("keeper_problems") or []), *lines]
    for k in [*marked, *handed]:
        if "keeper_source" in out[k]:
            out[k].update(_kp.fields(k, out))
    return out


def page_marks_naming(ents: dict, name: str) -> list:
    """[(entry id, page key)] of every sub-page mark in `ents` that names the agent `name` (case-folded), sorted."""
    n = str(name or "").casefold()
    return sorted((pid, k) for pid, e in ents.items() if isinstance(e.get(_kp.PAGES), dict) for k, v in e[_kp.PAGES].items() if n and str(v).casefold() == n)


def rename_page_marks(ents: dict, old: str, new: str) -> list:
    """Rewrite every sub-page mark of `ents` that names the agent `old` so that it names `new`, in place; → the page keys. The caller decides that `old` is gone (see agent_gone)."""
    done = []
    for pid, k in page_marks_naming(ents, old):
        ents[pid][_kp.PAGES][k] = new; done.append(k)
    return done


def clear_page_marks(ents: dict, name: str) -> list:
    """Remove every sub-page mark of `ents` that names the agent `name`, in place; → the page keys (those pages are read from their own `agent:` lines again)."""
    done = []
    for pid, k in page_marks_naming(ents, name):
        del ents[pid][_kp.PAGES][k]; done.append(k)
        if not ents[pid][_kp.PAGES]:
            del ents[pid][_kp.PAGES]
    return done


def rekey_page_marks(e: dict, old: str, new: str) -> list:
    """The project's page moved from `old` to `new`: the marks of the entry `e` for the pages under `old` now name the same pages under `new`, in place; → the new keys."""
    m = e.get(_kp.PAGES)
    if not isinstance(m, dict):
        return []
    done = []
    for k in sorted(m):
        nk = _norm_key(k)
        if nk.startswith(old + "/"):
            m[new + nk[len(old):]] = m.pop(k); done.append(new + nk[len(old):])
    return done


def agent_gone(raw: dict, ents: dict, name: str) -> bool:
    """Whether no project lists the agent `name` any more, read from the pages `raw` with the entries `ents` laid over them (the page lines of a project with an entry are the entry's)."""
    n = str(name or "").casefold()
    return n not in {x.casefold() for x in _listed_agents(apply(raw, ents), ents)}


def apply(reg: dict, ents: dict | None = None) -> dict:
    """The page registry with the project entries laid over it: for each entry whose page pointer is a key of `reg`, the entry's fields replace the page's (see
    the module text), a field the entry does not hold stays the page's. `reg` itself is never changed; with no entries (or none that differs) it is returned as it is.
    A project with no page has no row in a registry keyed by page: it is reached by resolve(). The keeper follows the entry: a flagged agent is the row's keeper and the
    sub-pages under it inherit it; `keeper_agent` and `keeper_source` are read again for the pages an entry changes (and, when it changes a project's agents or marks one,
    for the whole project). `ents` = the entries to lay (default: the record's own, `entries()`): a verb's dry run lays the entries a change would write, to read what it would do. Never raises."""
    try:
        ents = entries() if ents is None else ents
        if not ents or not isinstance(reg, dict) or not reg:
            return reg
        retired = _retired_words()
        out: dict | None = None; changed = []; tops = set()
        for pid, e in sorted(ents.items()):
            k = page_key(e); cur = reg.get(k) if k else None
            if not isinstance(cur, dict):
                continue
            new = _overlay(cur, e, retired)
            if not _differs(new, cur):
                continue
            if out is None:
                out = dict(reg)
            out[k] = new; changed.append(k)
            if (_kp.MARK in (cur.get("role"), new.get("role")) or "legacy_session" in cur or "legacy_session" in new
                    or cur.get("status") != new.get("status") or cur.get("hub") != new.get("hub")      # a retired or re-hubbed project: the pages under it read their keeper again
                    or list((cur.get("agents") or {}).items()) != list((new.get("agents") or {}).items())
                    or list((cur.get("back_agents") or {}).items()) != list((new.get("back_agents") or {}).items())):
                tops.add(_top(k))
        if out is None:
            return _lay_page_keepers(reg, ents)
        from stackshot.projects import projects as _p
        _inherit_marks(out, tops)
        for k in changed:
            if "agent_records" in out[k]:                  # the records name each agent's role from the project's name: after every entry is laid
                out[k]["agent_records"] = _p.agent_records(k, out[k], out)
        hubbed = [x for x in out if _top(x) not in tops and x not in changed and isinstance(out.get(_top(x)), dict)       # a page that names no agents and falls to its hub's: its derived keeper follows the hub's agents
                  and _top(str(out[_top(x)].get("hub") or "")) in tops]
        for k in [*changed, *(x for x in out if _top(x) in tops and x not in changed), *hubbed]:
            if "keeper_source" in out[k]:                  # a registry file written before the keeper fields has none to refresh: the published record reads them itself
                if out[k] is reg.get(k):
                    out[k] = dict(out[k])
                out[k].update(_kp.fields(k, out))
        return _lay_page_keepers(out, ents)
    except Exception as e:  # noqa: BLE001
        print(f"project record: the entries are not laid over the registry ({type(e).__name__}: {e})", file=sys.stderr, flush=True)
        return reg


# ---------------------------------------------------------------------------- writing
def update(fn) -> dict:
    """Change the entries under the record's lock: `fn(entries)` mutates a copy, which is validated and written (atomically, with the rest of the file as it is).
    → the entries now. Raises ValueError when the file or the section is damaged, or `fn` leaves an invalid entry: nothing is written then."""
    from stackshot.projects import projects as _p
    with _p.locked():
        d = _p._read()
        cur = parse({SECTION: d["extra"].get(SECTION, {}), VERSION: d["extra"].get(VERSION, SCHEMA)})
        new = copy.deepcopy(cur)
        fn(new)
        parse({SECTION: new})
        if json.dumps(new) == json.dumps(cur):       # not sorted: the agents' order is part of an entry
            return new
        if new:
            d["extra"][SECTION] = new; d["extra"][VERSION] = SCHEMA
        else:
            d["extra"].pop(SECTION, None); d["extra"].pop(VERSION, None)
        _p._write(d)
    return new


def moved(section: Any, old_key: str, new_key: str, oid: str, nid: str | None = None) -> None:
    """A page moved (projects.rename): in the raw section `section`, the project `oid` now points at `new_key` and lists `old_key` among its former keys; when the new key was
    held by another project `nid` (the swap), that one takes `old_key`. An entry whose pointer is not the key it was moving from is left alone. No-op for anything that is not
    a section of entries."""
    if not isinstance(section, dict):
        return
    for pid, was, now in ((oid, old_key, new_key), (nid, new_key, old_key)):
        e = section.get(pid) if pid else None
        if not isinstance(e, dict) or page_key(e) != was:
            continue
        e["page"] = now
        fk = [k for k in (e.get("former_keys") or []) if _norm_key(k) != now]
        if was not in fk:
            fk.append(was)
        e["former_keys"] = fk


# ---------------------------------------------------------------------------- the registry as the server reads it, and the files it publishes
# A registry file of the store ([registries]), read by the project areas and the client API; `projects` has the project record's entries laid over the pages' lines.
def _registry(name: str) -> dict[str, Any]:
    from stackshot.projects import projects as _prj      # projects.py imports this module
    r = _cfg.CFG["registries"][name]
    try:
        with open(_store.STORE / f"{name}.json", encoding="utf-8") as f:
            data = json.load(f)
        data = data[r["key"]] if r.get("key") else data
        return _prj.with_record(data) if name == "projects" else data      # the project record's entries first, the page lines for the rest
    except Exception:
        return {}


# every session's role, as a file the server keeps (<state>/roles.json) and the client API serves (`roles`), so a box's
# hooks can tell a front agent without parsing the registry. Written at start, after each registry rebuild (publish, the
# create gate's rebuild) and from the runner's fleet pass (every 60 s), when the roles changed or the file is ROLES_EVERY old: a
# reader treats a file over an hour old as stale, so a live server keeps it fresh even when nothing changes.
ROLES = _cfg.state("roles.json")
ROLES_EVERY = 30 * 60
_ROLES_LOCK = threading.Lock()


def _roles_sync(now: float | None = None) -> bool:
    """Rewrite roles.json ({"generated": <UTC ISO Z>, "sessions": anchors.file_roles()}) atomically when the roles changed or
    the file is ROLES_EVERY old. file_roles is session_roles with the pane-named keeper of an active one-session project as
    "front"; the server's own gates keep session_roles. Each entry also says whether sala lists the name as a session (`"live"`, one
    `sala sessions --json` read per build: anchors.sala_live; the field is left out when sala cannot be read), and a change in who is listed rewrites the file. An empty registry (none yet, or unreadable) writes nothing: a stale file is the reader's cue,
    an empty one would say nobody is front. → True when written."""
    from stackshot.anchors import anchors as _anc        # anchors.py imports this module
    from stackshot.fleet import renamed_agents as _renamed      # renamed_agents.py imports projects.py
    now = time.time() if now is None else now
    reg = _anc.registry()
    if not reg:
        return False
    rows = _anc.sala_rows()                                # sala is read once per build; `live` on every entry, or on none when sala cannot be read
    renames = _renamed.renames_of(rows)                    # old name → new name of the sessions sala renamed: an alias reads live, but names nobody
    try:
        _renamed.sweep(renames, reg, now)                  # a pending agent under an old name is no agent: dropped (the new name is registered) or renamed (it is not), before the roles read it
    except ValueError:                                     # a damaged id file: nothing is dropped, and the roles are built from the record as it stands
        pass
    except Exception as e:  # noqa: BLE001 — a record write that failed (a full disk, a lock file): the next tick sweeps again; the roles are rebuilt now all the same
        print(f"renamed agents: the sweep failed ({e!r}); roles.json is built from the record as it stands", file=sys.stderr, flush=True)
    live = None if rows is None else set().union(*_anc.sessions_of(rows))
    sessions = _anc.file_roles(reg, live, renames)
    ids = _anc.role_ids(sessions)          # step B: beside each name its permanent id where the registry resolves it (an extra top-level key; the keys of `sessions` stay names)
    with _ROLES_LOCK:
        try:
            old = json.loads(ROLES.read_text(encoding="utf-8"))
            age = now - dt.datetime.fromisoformat(str(old["generated"]).replace("Z", "+00:00")).timestamp()
        except Exception:
            old, age = {}, float("inf")
        if old.get("sessions") == sessions and (old.get("ids") or {}) == ids and 0 <= age < ROLES_EVERY:
            return False
        gen = dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ROLES.parent.mkdir(parents=True, exist_ok=True)
        tmp = ROLES.with_name(".roles.json.tmp")
        tmp.write_text(json.dumps({"generated": gen, "sessions": sessions, **({"ids": ids} if ids else {})}, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, ROLES)
    return True


def _roles_sync_safe(now: float | None = None) -> None:
    if _ro.is_read_only():                  # roles.json and projects.json are files the standby does not write
        return
    try:
        _roles_sync(now)
    except Exception as e:
        print(f"roles.json: {e}", file=sys.stderr, flush=True)
    _projects_sync_safe(now)                # phase A: projects.json beside it, on the same calls (start, publish, the create gate's rebuild, the 20-s pass)


# phase A: the project record's published file, <state>/projects.json ({schema, generated, projects: {<id>: {id, key, keeper,
# agents}}, by_key}), kept as roles.json is: rewritten when a record changed and at least every projects.EVERY (3 min) seconds, so a
# reader treats a file over 10 minutes old as stale. Ids are minted in <store>/project-record.json (projects.py), once and for good.
PROJECTS = _cfg.state("projects.json")


def _projects_sync(now: float | None = None, force: bool = False) -> bool:
    from stackshot.projects import projects as _prj      # projects.py imports this module
    return _prj.sync(now=now, force=force, path=PROJECTS)


def _projects_sync_safe(now: float | None = None, force: bool = False) -> None:
    try:
        _projects_sync(now, force)
    except Exception as e:
        print(f"projects.json: {e}", file=sys.stderr, flush=True)
