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

The registry as the server reads it, and the two files it keeps (the helpers that more than one part of the server reads):

    _registry(name)       a registry file of the store ([registries]); `projects` has the record's entries laid over the pages' lines
    _roles_sync()         <state>/roles.json, every session's role, rewritten when the roles changed or the file is ROLES_EVERY old (`_roles_sync_safe` also keeps projects.json)
    _projects_sync()      <state>/projects.json, the project record's published file

Stdlib only; config.py, readonly.py and store.py (core/) are its imports at load (projects.py, anchors.py and renamed_agents.py are imported inside the functions that need them, since they import this module)."""
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
        from stackshot.projects import projects as _p
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
