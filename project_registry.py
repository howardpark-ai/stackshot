"""project_registry.py — the projects of the project record: one entry per permanent project id, and the one place the registry's readers resolve a project.

A project is defined on its own. Its entry in `<store>/project-record.json` (the section `projects`, keyed by the permanent id `prj_<8 hex>`) holds what the
project is; the knowledge-base page it points at is one optional field of it. The page's own lines (`display-name:`, `agents:`, `status:`, `hub:`) are what the
registry was derived from until now; with an entry, the entry is read first and the page line is the fallback. A project with no entry is read exactly as before.

An entry (every field optional unless said):

    name           the project's name, the prefix of its agents' names (`<name>-<role>`)
    title, type    what the registry shows ("project")
    scope          one of [project_scopes] order
    status         "active" | "archived" (default active)
    agents         {agent name: {"front": bool, "mandate_line": str}} in the order the project lists them (the first builder listed is the builder)
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

Stdlib only; config.py is its one import at load (projects.py is imported inside the functions that need it, since it imports this module)."""
from __future__ import annotations

import copy
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

import config as _cfg

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
    import projects as _p
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
    if e.get("name"):
        new["session"] = e["name"]; new["role"] = "name"
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


def apply(reg: dict) -> dict:
    """The page registry with the project entries laid over it: for each entry whose page pointer is a key of `reg`, the entry's fields replace the page's (see
    the module text), a field the entry does not hold stays the page's. `reg` itself is never changed; with no entries (or none that differs) it is returned as it is.
    A project with no page has no row in a registry keyed by page: it is reached by resolve(). Never raises."""
    try:
        ents = entries()
        if not ents or not isinstance(reg, dict) or not reg:
            return reg
        retired = _retired_words()
        out: dict | None = None; changed = []
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
        if out is None:
            return reg
        import projects as _p
        for k in changed:
            if "agent_records" in out[k]:                  # the records name each agent's role from the project's name: after every entry is laid
                out[k]["agent_records"] = _p.agent_records(k, out[k], out)
        return out
    except Exception as e:  # noqa: BLE001
        print(f"project record: the entries are not laid over the registry ({type(e).__name__}: {e})", file=sys.stderr, flush=True)
        return reg


# ---------------------------------------------------------------------------- writing
def update(fn) -> dict:
    """Change the entries under the record's lock: `fn(entries)` mutates a copy, which is validated and written (atomically, with the rest of the file as it is).
    → the entries now. Raises ValueError when the file or the section is damaged, or `fn` leaves an invalid entry: nothing is written then."""
    import projects as _p
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
