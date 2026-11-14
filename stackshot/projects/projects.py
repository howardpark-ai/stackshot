"""projects.py — the project record (phase A of the permanent-id work; the design doc).

A project is identified today by its gbrain page key (`projects/<slug>`, `infra/<slug>`) everywhere. This module gives every page of the
registry a permanent id, `prj_<8 hex>`, minted once and never changed, and keeps the page key, the agents map and the keeper as
fields of a record that may change (a page move becomes one field edit). Phase A is additive: items, anchors and roles still store the
key; every API entry point accepts the id or the key.

  <store>/project-record.json   {"schema": 1, "ids": {<id>: <key>}, "pending_agents": {<id>: {<name>: {front, role, mandate_line, by, at}}},
                                "marks": {<id>: {scope?, on_purpose?, made?}}}
                                the one place an id is minted and kept (committed with the store). `ids` is cumulative: an id whose page
                                has gone stays reserved, and a rename is `rename(old_key, new_key)`, one edit of its value (rename_page.py
                                calls it; so does `python3 projects.py rename <old> <new>`). A file that exists but is damaged raises and
                                is never rewritten: nothing is minted over it, and the registry's `id` fields (a second copy) answer reads
                                and restore a lost file. Every write goes under one flock and through a temp file in the state dir.
  <store>/projects.json         the page registry (pages.py); each page gets `id`, `key` and `agent_records` beside the old fields
  <state>/projects.json         the published file (sync): {"schema": 1, "generated": <ISO Z>, "projects": {<id>: {id, key, keeper,
                                agents: {<name>: {front, role, mandate_line}}}}, "by_key": {<key>: <id>}}; rewritten when it changed and
                                at least every EVERY seconds, so a reader treats a file older than 10 minutes as stale.
                                An agent in the pending table (registered before the project had an entry in the record; the migration folds it into the
                                entry and clears it, and `post project-agent` now writes the entry) whose page line is still owed is listed with `front` as
                                it was asked for AND `page_owed: true`: a reader MUST check `page_owed` before it treats the agent as the
                                page's (it is a claim by one session, not what the page says).

Scope and listing (additive to schema 1: the fleet tool reads `front`, `mandate_line`, `page_owed` and the names only, so no bump): every record also
carries `title`, `scope` (one of [project_scopes] order, e.g. team | lab | infra), `listed` (bool), `listed_by` (agents | items | on_purpose | ""), `sub_page` (bool) and
`items_30d`, plus `type` and `hub`, and `status` (the page's, lowercase) and `retired` (the status is one of [project_scopes] retired_statuses; default archived,
retired, closed, done, dropped, completed, merged): a retired project is never listed, whatever its agents, items or mark. A scope set on purpose and the "listed on purpose" mark live in the id file (`marks`, by project id, so a page move keeps them;
the page registry is rebuilt from the pages and could not hold them). Listed = a project that has agents (a pending one counts), or a board
item touched in the last LISTED_DAYS days, or a mark made on purpose (a project made through `post project`, or listed again through
`post project-list`); everything else is hidden, never deleted. A sub-page (a key with an ancestor key that is itself a page of the
registry, or a page with a `hub:` line) and a `type: note` page are never listed. A mark also keeps `at` (the last make or re-list) and `by`
(its label), which window the first agent a label may register (service/projects.py `_project_agent`). A project made through `post project` whose page the registry has not read yet is added to the registry
read here (`with_made`), so it has a record at once.

The project entries (project_registry.py, the section `projects` of the same file, keyed by the same ids): when a project has one, `registry()` lays it over the page's lines (title, type,
name, status, hub, agents, scope), so every reader of the registry sees the entry first and the page for any field the entry does not hold; with no entry a project reads as it always did.
A page move (`rename`) moves the entry's page pointer with the id.

`ref(x)` is the one lookup: an id, a full page key or a bare slug → the record, or None.
`fields(x)` (and `python3 -m stackshot projects fields <project>`) is the read-through for a script that needs a project's name, status and agents: the entry's fields first, the page's lines for a
field the entry does not hold or a project the record does not cover yet, with the source of each: no script reads those page lines itself, so the lines can stop being written (`[pages] copy_project_lines`).
Stdlib only; config.py is its one import."""
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]
import datetime, errno, fcntl, json, os, re, secrets, shutil, sys, tempfile, threading
from pathlib import Path

from stackshot.core import config as _cfg
from stackshot.projects import project_registry as _pr      # the project entries of the record: the registry reads them first, the page lines are the fallback
from stackshot.model import item_project as _iproj      # an item's project by its permanent id: the page key read through the id
from stackshot.core import readonly as _ro      # a warm standby copy writes nothing

ID_RE = re.compile(r"^prj_[0-9a-f]{8}$")
EVERY = 3 * 60                         # rewrite the published file at least this often (the promise to readers is every 5 minutes; the minute pace plus a slow round of 20 s must still fit)
SCHEMA = 1
_LOCK = threading.Lock()               # the published file's writers inside one process


def _store() -> Path: return _cfg.path("paths", "store")
def record_path() -> Path: return _store() / "project-record.json"
def registry_path() -> Path: return _store() / "projects.json"
def published_path() -> Path: return _cfg.state("projects.json")


def registry_raw() -> dict:
    """The page registry as the publisher wrote it, from the pages alone: key → entry ({} when there is none yet)."""
    try: return json.load(open(registry_path(), encoding="utf-8")).get("pages", {}) or {}
    except Exception: return {}


def with_record(reg: dict) -> dict:
    """The page registry with the project record's entries laid over it (project_registry.apply): title, type, name, status, hub, agents and scope from the entry of a
    project that has one, the page's lines for the rest. Every reader of the registry file goes through this or `registry()`, so the record is read first in one place."""
    return _pr.apply(reg)


def pageless(x) -> dict | None:
    """The view of the project `x` (an id, a key, a name) names when the record says it has no page, else None (project_registry.pageless)."""
    return _pr.pageless(x)


def registry() -> dict:
    """The page registry the readers see: the published pages (registry_raw) with the project record's entries laid over them (with_record)."""
    return with_record(registry_raw())


def is_id(x) -> bool:
    return bool(ID_RE.match(str(x or "").strip()))


# ---------------------------------------------------------------------------- writing: never through a temp file in the store
def write_atomic(path, text: str) -> None:
    """Write `text` to `path` so a reader never sees half of it: a temp file in the STATE dir (<state>/tmp), then os.replace across. The
    store is a git checkout that the publisher commits with `add -A`, so a temp file must never sit in it; only when the two dirs are on
    different filesystems (EXDEV) is the file staged beside the target, under a dot name, for the length of one replace."""
    _ro.guard("write " + str(path))
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    d = _cfg.state("tmp"); d.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text); f.flush(); os.fsync(f.fileno())      # the bytes are on disk before the name moves
        os.chmod(tmp, 0o644)
        try: os.replace(tmp, path)
        except OSError as e:
            if e.errno != errno.EXDEV: raise
            beside = path.with_name("." + path.name + ".tmp")
            try: shutil.copyfile(tmp, beside); os.replace(beside, path)
            finally:
                try: os.unlink(beside)
                except FileNotFoundError: pass
        try:   # and the rename itself: fsync the directory (cheap on Linux); a filesystem that refuses it is no reason to fail the write
            dfd = os.open(path.parent, os.O_RDONLY)
            try: os.fsync(dfd)
            finally: os.close(dfd)
        except OSError: pass
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass


_HELD = threading.local()


class _Locked:
    """The one lock around everything that reads, changes and writes the id file, and around the registry file's rewrite: across processes
    (the server, `pages.py registry`, rename_page.py, a test) by flock on a file in the state dir, never in the store, which is committed.
    Re-entrant in a thread (the registry rewrite holds it while ensure_ids takes it again); a second thread waits."""
    def __enter__(self):
        if getattr(_HELD, "n", 0): _HELD.n += 1; return self
        lk = _cfg.state("project-record.lock"); lk.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(lk, "w"); fcntl.flock(self.f, fcntl.LOCK_EX); _HELD.n = 1; _HELD.f = self.f; return self
    def __exit__(self, *a):
        _HELD.n -= 1
        if _HELD.n == 0: fcntl.flock(_HELD.f, fcntl.LOCK_UN); _HELD.f.close()


def locked(): return _Locked()


# ---------------------------------------------------------------------------- the id file
def _read() -> dict:
    """The id file, strictly: {"schema", "ids", "pending_agents", "extra"} (`extra` = every other top-level field, kept as it is on a
    rewrite). A file that is missing is an empty record; one that exists and does not parse or validate RAISES ValueError, and nothing
    is minted, dropped or written over it (a torn or damaged file once re-minted every id). The callers fail open."""
    try: raw = open(record_path(), encoding="utf-8").read()
    except FileNotFoundError: return {"schema": SCHEMA, "ids": {}, "pending_agents": {}, "marks": {}, "extra": {}}
    try: d = json.loads(raw)
    except ValueError as e: raise ValueError(f"{record_path()} does not parse ({e})") from None
    bad = lambda why: ValueError(f"{record_path()} is not a valid project record: {why}")
    if not isinstance(d, dict): raise bad("not an object")
    if d.get("schema", SCHEMA) != SCHEMA: raise bad(f"schema {d.get('schema')!r}, this code reads {SCHEMA}")
    ids = d.get("ids", {})
    if not isinstance(ids, dict): raise bad("ids is not an object")
    for i, k in ids.items():
        if not is_id(i) or not isinstance(k, str) or not k: raise bad(f"ids entry {i!r}")
    pend = d.get("pending_agents", {})
    if not isinstance(pend, dict): raise bad("pending_agents is not an object")
    for i, m in pend.items():
        if not is_id(i) or not isinstance(m, dict) or not all(isinstance(a, dict) for a in m.values()): raise bad(f"pending_agents entry {i!r}")
    mk = d.get("marks", {})
    if not isinstance(mk, dict): raise bad("marks is not an object")
    for i, m in mk.items():
        if not is_id(i) or not isinstance(m, dict): raise bad(f"marks entry {i!r}")
    return {"schema": SCHEMA, "ids": dict(ids), "pending_agents": {i: dict(m) for i, m in pend.items()}, "marks": {i: dict(m) for i, m in mk.items()},
            "extra": {k: v for k, v in d.items() if k not in ("schema", "ids", "pending_agents", "marks")}}


def _write(d: dict) -> None:
    out = {**d.get("extra", {}), "schema": SCHEMA, "ids": d["ids"], "pending_agents": {i: m for i, m in d["pending_agents"].items() if m}}
    if any(d.get("marks", {}).values()): out["marks"] = {i: m for i, m in d["marks"].items() if m}
    write_atomic(record_path(), json.dumps(_sorted_keys(out), ensure_ascii=False, indent=1) + "\n")     # sorted at every level but inside an `agents` map, which keeps its order (the first builder listed is the builder)


def _seed(d: dict) -> bool:
    """The registry's own `id` fields are a second copy of the ids: adopt each one the id file does not hold (its id unused, its key without
    an id), so a lost id file restores the old ids instead of minting new ones. The id file wins every disagreement. → True when it adopted any."""
    have = {}
    for i, k in sorted(d["ids"].items()): have.setdefault(k, i)
    n = False
    for key, e in registry().items():
        i = e.get("id") if isinstance(e, dict) else None
        if is_id(i) and i not in d["ids"] and key not in have: d["ids"][i] = key; have[key] = i; n = True
    return n


def ids_by_key() -> dict:
    """key → id, from the id file (read only; raises when the file is damaged)."""
    out = {}
    for i, k in sorted(_read()["ids"].items()): out.setdefault(k, i)
    return out


def ensure_ids(keys) -> dict:
    """key → id for every key given, minting an id for each key that has none: once, and the id is never changed or reused. A key's id is
    the first one the file holds for it, else the one the registry carries for it (a lost file is restored from that copy), else new. Writes
    the file only when something was minted or restored. Raises ValueError, minting nothing, when the id file is damaged."""
    keys = [str(k) for k in dict.fromkeys(keys) if k]
    with _Locked():
        d = _read(); changed = _seed(d); by = {}
        for i, k in sorted(d["ids"].items()): by.setdefault(k, i)
        for k in sorted(keys):
            if k in by: continue
            while True:
                i = "prj_" + secrets.token_hex(4)
                if i not in d["ids"]: break
            d["ids"][i] = k; by[k] = i; changed = True
        if changed: _write(d)
    return {k: by[k] for k in keys}


def _ids_for(keys, reg: dict) -> dict:
    """ensure_ids, except that a damaged id file is not fatal for a read: the registry's own copy of each id answers. A key with no id
    in either place re-raises (no id is minted for it)."""
    try: return ensure_ids(keys)
    except ValueError:
        out = {k: (reg.get(k) or {}).get("id") for k in keys}
        if all(is_id(i) for i in out.values()): return out
        raise


def rename(old_key: str, new_key: str) -> str:
    """A page moved: its id follows it. Edits the key the id stands for, under the lock; the id never changes. → the id. When the new key
    already has an id of its own (the copy was published before the old page was turned into a stub), the two swap keys, so the moved
    page keeps its old id, the dead key keeps the other and none is dropped, nor is a pending agent (they travel with their id).
    ValueError: the old key has no id, or the id file is damaged."""
    old_key, new_key = str(old_key).strip().strip("/"), str(new_key).strip().strip("/")
    if not old_key or not new_key or old_key == new_key: raise ValueError("rename needs two different page keys")
    with _Locked():
        d = _read(); _seed(d)
        by = {}
        for i, k in sorted(d["ids"].items()): by.setdefault(k, i)
        if old_key not in by: raise ValueError(f"{old_key} has no project id: nothing to move")
        oid = by[old_key]; nid = by.get(new_key)
        d["ids"][oid] = new_key
        if nid and nid != oid: d["ids"][nid] = old_key
        _pr.moved(d["extra"].get(_pr.SECTION), old_key, new_key, oid, nid if nid != oid else None)     # the project's entry points at the new page and remembers the old key
        _write(d)
    return oid


def id_to_key(i: str, reg: dict | None = None) -> str:
    """The page key an id names now: the id file first (when it is damaged, the registry's copy), else a registry entry that carries the
    id; "" when it names none."""
    i = str(i or "").strip()
    if not is_id(i): return ""
    k = _pr.page_key_of(i)                      # the project's own entry first
    if k: return k
    try: k = _read()["ids"].get(i, "")
    except ValueError: k = ""
    if k: return k
    for key, e in (registry() if reg is None else reg).items():
        if isinstance(e, dict) and e.get("id") == i: return key
    return ""


def to_key(x: str, reg: dict | None = None) -> str:
    """An id → its page key; anything else is returned as it was (a key stays a key, an unknown id stays unknown)."""
    x = str(x or "").strip()
    return (id_to_key(x, reg) or x) if is_id(x) else x


def pending_entry(pid: str, name: str) -> dict:
    """The agent registered under this id and name whose page line is still owed ({} when none, or when the id file is damaged)."""
    try: return dict(_read()["pending_agents"].get(pid, {}).get(name) or {})
    except ValueError: return {}


# ---------------------------------------------------------------------------- the record
_NAME_ROLES = ("name", "steward")      # the registry role of a page's own `display-name:` line; "steward" is what a registry file written before an earlier change holds


def _name_prefixes(key: str, entry: dict, reg: dict) -> list:
    """The project's name, the prefix of its agents' names (`<project>-<role>`): the `display-name:` line of the page, and of its hub's;
    a name line naming one of the page's own agents is a session, so the name comes from its `-main` agent (else that name minus its last part)."""
    out = []
    parts = key.split("/")
    for k in dict.fromkeys([key, str(entry.get("hub") or ""), "/".join(parts[:2])]):
        e = reg.get(k) if k != key else entry
        if isinstance(e, dict) and e.get("session") and e.get("role") in _NAME_ROLES:
            name = str(e["session"]); agents = [str(a) for a in (e.get("agents") if isinstance(e.get("agents"), dict) else {})]
            if name.casefold() in {a.casefold() for a in agents}:
                base = next((a[:-5] for a in agents if a.casefold().endswith("-main") and len(a) > 5 and name.casefold().startswith(a[:-5].casefold() + "-")), "")
                name = base or name.rsplit("-", 1)[0]
            out.append(name)
    return sorted(dict.fromkeys(out), key=len, reverse=True)


def role_of(name: str, prefixes) -> str:
    """The part of an agent's name after the project's name ("my-engineer" → "engineer"); with no project name to
    cut, the last dash-separated part."""
    name = str(name); p = named_for(name, prefixes)
    return name[len(p) + 1:] if p else name.rsplit("-", 1)[-1]


def agent_records(key: str, entry: dict, reg: dict) -> dict:
    """A page's `agents:` map as {name: {front, role, mandate_line}}: a top-level entry is front, a `background:` entry is not.
    The registry keeps both: `agents` (flat, every agent) and `back_agents` (the background subset)."""
    flat = entry.get("agents") if isinstance(entry.get("agents"), dict) else {}
    back = set(entry.get("back_agents") or {})
    pre = _name_prefixes(key, entry, reg)
    return {str(n): {"front": str(n) not in back, "role": role_of(n, pre), "mandate_line": str(m)} for n, m in flat.items()}


def registry_fields(key: str, entry: dict, reg: dict, pid: str) -> dict:
    """What the page registry gains for one page beside its old fields (pages.cmd_registry)."""
    return {"id": pid, "key": key, "agent_records": agent_records(key, entry, reg)}


def _pending_all() -> dict:
    """Every pending agent by id; {} when the id file is damaged (a read goes on without them, the file is untouched)."""
    try: return _read()["pending_agents"]
    except ValueError: return {}


def _record(key: str, entry: dict, reg: dict, pid: str, pending: dict, mark: dict | None = None, recent: dict | None = None, now: float | None = None) -> dict:
    """One project's record. An agent only registered here (its page line still owed) is listed with `front` as it was asked for and
    `page_owed: true`: a reader must check `page_owed` before it treats the agent as the page's (the fleet tool's spawn, the roles). The record
    also carries the project's scope and whether it is listed (listing_fields)."""
    agents = agent_records(key, entry, reg)
    for n, a in sorted((pending or {}).items()):
        if n not in agents:       # the page wins: a name the page lists is the page's
            agents[n] = {"front": bool(a.get("front")), "role": str(a.get("role") or ""), "mandate_line": str(a.get("mandate_line") or ""), "page_owed": True}
    rec = {"id": pid, "key": key, "keeper": str(entry.get("session") or ""), "agents": agents}
    rec.update(listing_fields(key, entry, reg, agents, mark, recent_items(reg, now) if recent is None else recent))
    return rec


def build(reg: dict | None = None, now: float | None = None) -> dict:
    """The published file's body without its stamp: {"projects": {<id>: record}, "by_key": {<key>: <id>}}. Mints the id of any page
    that has none. A page with no registry entry has no record, whatever its id (but a project made through `post project` whose page
    the registry has not read yet has one: with_made)."""
    reg = with_made(registry() if reg is None else reg)
    by = _ids_for(list(reg), reg)
    pend = _pending_all(); mk = marks(); recent = recent_items(reg, now)
    projects = {}
    for key, entry in sorted(reg.items()):
        if isinstance(entry, dict): projects[by[key]] = _record(key, entry, reg, by[key], pend.get(by[key], {}), mk.get(by[key]), recent)
    return {"projects": projects, "by_key": {r["key"]: i for i, r in projects.items()}}


def refs(x, reg: dict | None = None) -> list:
    """Every record an id, a full key or a bare slug can name, in match order (a bare slug may name projects/<slug> and infra/<slug>)."""
    x = str(x or "").strip().strip("/")
    if x.endswith(".md"): x = x[:-3]
    if not x: return []
    reg = with_made(registry() if reg is None else reg)
    if is_id(x):
        k = id_to_key(x, reg); keys = [k] if k in reg else []
    else:
        pats = (_cfg.CFG.get("registries", {}).get("projects", {}) or {}).get("match") or ["{value}"]
        keys = [k for k in dict.fromkeys(p.format(value=x) for p in pats) if k in reg]
    keys = [k for k in keys if isinstance(reg.get(k), dict)]
    if not keys: return []
    by = _ids_for(keys, reg); pend = _pending_all(); mk = marks(); recent = recent_items(reg)
    return [_record(k, reg[k], reg, by[k], pend.get(by[k], {}), mk.get(by[k]), recent) for k in keys]


def ref(x, reg: dict | None = None):
    """The one lookup: an id, a full page key or a bare slug → the project's record {id, key, keeper, agents}, or None. A bare slug
    that names two pages gives the first in match order (refs gives all)."""
    r = refs(x, reg)
    return r[0] if r else None


project_ref = ref       # the name the design gives it: `projects.project_ref(x)`; the save steps have the same, `mover_steps.project_ref(x)`


# ---------------------------------------------------------------------------- the read-through for scripts: the record first, the page's lines for what it does not hold
def _owner_key(key: str, reg: dict) -> str:
    """The page that names the project `key` belongs to: the page itself, then the page its `hub:` line names, then each page above it, the nearest first, whose
    own lines (or the record's entry) give the project a name. "" when none does."""
    parts = key.split("/")
    row = reg.get(key) if isinstance(reg.get(key), dict) else {}
    chain = [key, str(row.get("hub") or "").strip(), *["/".join(parts[:n]) for n in range(len(parts) - 1, 1, -1)]]
    for k in dict.fromkeys(c for c in chain if c):
        e = reg.get(k)
        if isinstance(e, dict) and e.get("role") in _NAME_ROLES and str(e.get("session") or "").strip():
            return k
    return ""


def _fields_row(key: str, rec: dict, reg: dict, entry: dict | None) -> dict:
    """One project's fields from the registry row the record is already laid over (`reg`), each with where it came from: "record" when the project's entry holds the
    field, "page" when the page's own line answers, "" when neither has it."""
    row = reg.get(key) if isinstance(reg.get(key), dict) else {}
    entry = entry or {}
    name = str(row.get("session") or "") if row.get("role") in _NAME_ROLES else ""
    agents = rec.get("agents") or {}
    src = lambda in_record, have: "record" if in_record else ("page" if have else "")
    return {"id": rec["id"], "key": key, "owner_key": _owner_key(key, reg), "sub_page": is_sub_page(key, reg, row),
            "source": "record" if entry else "page",
            "display_name": name, "status": page_status(row) or "active", "retired": bool(rec.get("retired")), "hub": str(row.get("hub") or ""),
            "agents": agents, "main": main_of(agents),
            "from": {"display_name": src(bool(entry.get("name")), bool(name)), "status": src("status" in entry, bool(row.get("status"))), "agents": src("agents" in entry, bool(agents))}}


def fields(x, reg: dict | None = None) -> dict | None:
    """What a script reads of a project, so none reads the page's `display-name:`, `status:` and `agents:` lines itself: `x` is an id, a page key or a bare slug →
    {id, key, owner_key, sub_page, source ("record" | "page"), display_name, status, retired, hub, agents {name: {front, role, mandate_line}}, main, from {display_name,
    status, agents}} or None for a project nothing names. The project record's entry is read first, and the page's lines answer for a field the entry does not hold
    (`from` says which) and for a project the record does not cover yet (`source` "page"), so nothing a reader needs is lost while the record fills. `owner_key` is the page
    that names the project the page `x` belongs to (the page itself for a project's own page). A project the record says has no page is read from the record alone."""
    reg = with_made(registry() if reg is None else reg)
    recs = refs(x, reg)
    if recs:
        rec = recs[0]
        return _fields_row(rec["key"], rec, reg, _pr.entries().get(rec["id"]))
    v = _pr.resolve(x)
    if not v or v.get("via") == "sub_page":
        return None
    e = _pr.entries().get(v["id"]) or {}
    pre = [str(v["name"])] if v.get("name") else []
    agents = {n: {"front": bool(a.get("front")), "role": role_of(n, pre), "mandate_line": str(a.get("mandate_line", ""))} for n, a in (v.get("agents") or {}).items()}
    return {"id": v["id"], "key": "", "owner_key": "", "sub_page": False, "source": "record", "display_name": str(v.get("name") or ""), "status": v.get("status") or "active",
            "retired": bool(v.get("archived")), "hub": str(v.get("hub") or ""), "agents": agents, "main": main_of(agents),
            "from": {"display_name": "record" if v.get("name") else "", "status": "record", "agents": "record" if "agents" in e else ""}}


def all_fields(reg: dict | None = None) -> list:
    """`fields` of every page of the registry that names a project or lists an agent (a sub-page that lists agents included), sorted by key; plus the record's projects that
    have no page. For a script that needs every project's names (a scan for private names)."""
    reg = with_made(registry() if reg is None else reg)
    by = _ids_for(list(reg), reg); pend = _pending_all(); mk = marks(); recent = recent_items(reg)
    ents = _pr.entries(); out = []
    for key, row in sorted(reg.items()):
        if not isinstance(row, dict) or not (row.get("agents") or row.get("role") in _NAME_ROLES):
            continue
        rec = _record(key, row, reg, by[key], pend.get(by[key], {}), mk.get(by[key]), recent)
        out.append(_fields_row(key, rec, reg, ents.get(rec["id"])))
    seen = {r["id"] for r in out}
    for pid in sorted(ents):
        if pid not in seen and not _pr.page_key(ents[pid]) and (f := fields(pid, reg)):
            out.append(f)
    return out


# ---------------------------------------------------------------------------- scope and listing (the fleet tool's "New session" form's project picker)
LISTED_DAYS = 30                       # a board item touched within this many days lists its project
_SCOPES = ["general"]                  # the default of [project_scopes] order: one scope, so a project's agents are called general-<slug>; an instance lists its own (stackshot.example.toml)
_BY_PREFIX: dict[str, str] = {}        # [project_scopes.by_prefix]: a page key's prefix -> the scope ({"infra/": "infra"}); none by default
_BY_TAG: dict[str, str] = {}           # [project_scopes.by_tag]: a page tag -> the scope; none by default
_RETIRED = ["archived", "retired", "closed", "done", "dropped", "completed", "merged"]    # the defaults of [project_scopes] retired_statuses: a page with one of these `status:` words is retired
_RECENT: dict = {}                     # (store, 30-second bucket) → the recent-items count: the 20-second pass does not read the whole store each time


def scopes() -> list:
    return [str(x) for x in (_cfg.get("project_scopes", "order") or _SCOPES)]


def retired_statuses() -> set:
    """The page `status:` words that retire a project (lowercase): [project_scopes] retired_statuses, else _RETIRED."""
    v = _cfg.get("project_scopes", "retired_statuses")
    return {str(x).strip().lower() for x in (v if isinstance(v, list) else _RETIRED)}


def page_status(entry: dict) -> str:
    """A registry entry's frontmatter `status`, lowercased and trimmed ("" when the page has none)."""
    v = entry.get("status") if isinstance(entry, dict) else ""
    return v.strip().lower() if isinstance(v, str) else ""


def default_scope() -> str:
    d = str(_cfg.get("project_scopes", "default") or "")
    return d if d in scopes() else scopes()[0]


def _own_scope(e: dict) -> str:
    """The scope a page's own frontmatter names: its `org` when that is a scope, else its first tag a scope is mapped to; "" when neither."""
    sc = scopes(); org = str(e.get("org") or "").strip().lower()
    if org in sc: return org
    tags = e.get("tags") or []
    if isinstance(tags, str): tags = [tags]
    by_tag = _cfg.get("project_scopes", "by_tag") or _BY_TAG
    for t in tags:
        s = by_tag.get(str(t).strip().lower())
        if s in sc: return s
    return ""


def _name_scope(name: str) -> str:
    """The scope a session or agent name points at by its prefix (`infra-hub` → infra, `team-alpha` → team): the scopes other than the
    default, whose names the pages follow in their display names and agents' names. "" when it names none."""
    name = str(name or "").strip().lower(); dflt = default_scope()
    return next((s for s in scopes() if s != dflt and name.startswith(s + "-")), "")


def _entry_scope(e: dict) -> str:
    """The scope one page's frontmatter points at, strongest first: an `org` that names a scope other than the default (a work page whose
    name line is an infra session stays team), then the keeper's name prefix (`display-name:` or the hub's: an `infra-…` name is infra, a
    `work-…` one work), then the `org` and tags as `_own_scope` reads them, then the prefix of the agents' names for a page with no keeper."""
    org = str(e.get("org") or "").strip().lower()
    if org in scopes() and org != default_scope(): return org
    s = _name_scope(e.get("session"))
    if s: return s
    s = _own_scope(e)
    if s: return s
    agents = e.get("agents") if isinstance(e.get("agents"), dict) else {}
    if not e.get("session"):
        found = {_name_scope(n) for n in agents} - {""}
        if len(found) == 1: return found.pop()
    return ""


def derive_scope(key: str, entry: dict, reg: dict) -> str:
    """The scope a page has when none was set on purpose: the key's prefix (infra/… → infra), else what the page's frontmatter points at
    (`_entry_scope`), then the same for the page its `hub:` line names and for the nearest page above it in the registry; else the default."""
    sc = scopes()
    if str(entry.get("scope") or "") in sc: return str(entry["scope"])     # the project record's entry names it
    for pre, s in (_cfg.get("project_scopes", "by_prefix") or _BY_PREFIX).items():
        if key.startswith(pre) and s in sc: return s
    s = _entry_scope(entry)
    if s: return s
    hub = str(entry.get("hub") or "")
    if hub and isinstance(reg.get(hub), dict):
        s = _entry_scope(reg[hub])
        if s: return s
    parts = key.split("/")
    for n in range(len(parts) - 1, 1, -1):
        up = reg.get("/".join(parts[:n]))
        if isinstance(up, dict):
            s = _entry_scope(up)
            if s: return s
    return default_scope()


def scope_of(key: str, entry: dict, reg: dict, ids: dict | None = None, marks_: dict | None = None) -> str:
    """The scope a project sits in, the one sala's sidebar and the New session form's picker use: the scope set on purpose for the page (its mark in the
    id file), else derive_scope. `ids` (key → id) and `marks_` are the id file's, read once by a caller that asks for many keys; None reads them here."""
    try:
        pid = (ids if ids is not None else ids_by_key()).get(key) or ""
        stored = str(((marks_ if marks_ is not None else marks()).get(pid or str(entry.get("id") or "")) or {}).get("scope") or "")
    except ValueError: stored = ""                       # a damaged id file: the registry's own copy of the id answers
    return stored if stored in scopes() else derive_scope(key, entry, reg)


def scoped_name(scope: str, name: str) -> str:
    """A project's name as the board shows it, with its scope in front and a plain slash between: `ops/general`, `home/general`, `work/General`. A name that
    already starts with `<scope>/` is left as it is; no scope (an instance with a single scope has nothing to tell apart) leaves the name alone. The stored
    `display-name:` line, the session names and the page keys are never touched: this is text for a person, made at display time."""
    name = str(name or "")
    if not scope or not name or name.casefold().startswith(scope.casefold() + "/"): return name
    return f"{scope}/{name}"


def label_scope(key: str, entry: dict, reg: dict, ids: dict | None = None, marks_: dict | None = None) -> str:
    """The scope word to show in front of a project's name: scope_of, or "" when the instance lists a single scope ([project_scopes] order) or the key is no page."""
    if not key or len(scopes()) < 2: return ""
    return scope_of(key, entry if isinstance(entry, dict) else {}, reg, ids, marks_)


def is_sub_page(key: str, reg: dict, entry: dict | None = None) -> bool:
    """A page that belongs to another: a key with an ancestor key that is itself a page of the registry (projects/hub/mechanics under
    projects/hub), or a page with a `hub:` line (infra/hub on projects/hub). The agents map is kept on the page above, so
    for the picker it is never a project of its own."""
    entry = reg.get(key) if entry is None else entry
    if isinstance(entry, dict) and str(entry.get("hub") or "").strip(): return True
    parts = key.split("/")
    return any("/".join(parts[:n]) in reg for n in range(len(parts) - 1, 1, -1))


_MOVED = frozenset(("moved", "superseded"))        # status words of a page that left (beside the retired_statuses)
SESSION_ID_RX = re.compile(r"^(?:cse_\w+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$", re.I)       # a session id is no name to look up


def page_active(entry: dict) -> bool:
    """A page that is not retired, done or moved: its `status:` is none of the retired words (retired_statuses) nor moved/superseded, and its title does not start with "moved"."""
    status = page_status(entry)
    return status not in retired_statuses() and status not in _MOVED and not str(entry.get("title") or "").lower().startswith("moved")


def session_live(name: str, names, aliases) -> bool:
    """Is a `display-name:` value known to sala: a live session named exactly so (or an alias of one), or a live session whose own name starts with `<name>-`."""
    return name in names or name in aliases or any(n.startswith(name + "-") for n in names)


def named_for(name: str, prefixes) -> str:
    """The project name (one of `prefixes`) an agent's `name` starts with (`<project>-<role>`, a role being left); "" when none. The test role_of cuts by."""
    return next((p for p in prefixes if name.startswith(p + "-") and len(name) > len(p) + 1), "")


def name_line(entry: dict) -> str:
    """The session a page's own `display-name:` line names ("" when the page has none, when the registry role is another (an `agent:` line, one inherited from the page above) or when the value is a session id)."""
    s = str(entry.get("session") or "").strip()
    return s if s and entry.get("role") in _NAME_ROLES and not SESSION_ID_RX.match(s) else ""


def _other_claim(key: str, entry: dict, reg: dict, name: str, longer: int) -> str:
    """The longest project name (`_name_prefixes` of a top-level, active `type: project` page other than `key` and its hub) that `name` starts with as `<project>-<role>`, when it is longer than `longer`; "" when none.
    A page that carries `name` itself as its project name (two pages sharing one session name) claims nothing: it is no prefix of it."""
    hub = str(entry.get("hub") or ""); best = ""
    for k in sorted(reg):
        e = reg[k]
        if k == key or k == hub or not isinstance(e, dict) or str(e.get("type") or "").strip().lower() != "project" or not page_active(e) or is_sub_page(k, reg, e): continue
        for p in _name_prefixes(k, e, reg):
            if name.startswith(p + "-") and len(p) > max(longer, len(best)): best = p
    return best


def _own_names(key: str, entry: dict, reg: dict, name: str) -> list:
    """The project names that are this page's own: its slug, and the project name of its agents (`_name_prefixes`, without the name line's own value, which is the very session being asked about)."""
    return [key.rsplit("/", 1)[-1]] + [p for p in _name_prefixes(key, entry, reg) if p != name]


def other_project_for(key: str, entry: dict, reg: dict, name: str) -> str:
    """The name of another project that `name` is named for ("" when none): the longest match of `name` over the top-level pages, this one included, is another page's project name and is longer than this page's own
    (`_own_names`: a name equal to the page's slug, or starting with it, is the page's own; so is a tie). A one-session page `foo-bar` next to a project `foo` is its own; the ax session, `<other>-ax` on a page `ax`, is not.
    The other page's name is the one `name` starts with `<project>-` (a name equal to it, two pages sharing one session, claims nothing)."""
    own = max((len(p) for p in _own_names(key, entry, reg, name) if name == p or name.startswith(p + "-")), default=-1)
    return _other_claim(key, entry, reg, name, own)


def session_covers(key: str, entry: dict, reg: dict, name: str, live) -> bool:
    """Does a live session answer to the name line `name`: the name or an alias of it is live (`live` = (names, aliases)), or a live session starts with `<name>-` and does not belong to a longer project name of another
    top-level page (page `foo` is not covered by the live `foo-bar-main` when `foo-bar` is a page of its own)."""
    names, aliases = live
    if name in names or name in aliases: return True
    return any(n.startswith(name + "-") and not _other_claim(key, entry, reg, n, len(name)) for n in names)


def agent_gap(key: str, entry: dict, reg: dict, live=None) -> dict | None:
    """Is this page a project with no one to take its items: `type: project`, active, no sub-page, and no front agent on its `agents:` map (agent_records)? → None when it has one, when it is something else, or when its
    one session is its own: the name line (`name_line`) names a session `session_covers` finds live in `live` = (names, aliases) of the live sessions (None = cannot tell: counts as live) and not named for another project
    (a one-session page is a page by design: a name line and no agents map). Otherwise {"kind": "no-agents-map" | "no-front-agent" | "foreign-name", "name": the name line's session or "", "other": the other project's name
    (foreign-name)}. Sub-pages are the registry's: a key under another page, or a `hub:` line (`is_sub_page`); a `parent:` line is not read by anything else here, so it makes no sub-page. One rule for the daily check and for rename_page.py."""
    if str(entry.get("type") or "").strip().lower() != "project" or not page_active(entry) or is_sub_page(key, reg, entry): return None
    recs = agent_records(key, entry, reg)
    if any(a["front"] for a in recs.values()): return None
    s = name_line(entry)
    if s:
        other = other_project_for(key, entry, reg, s)
        if other: return {"kind": "foreign-name", "name": s, "other": other}
        if live is None or session_covers(key, entry, reg, s, live): return None
    return {"kind": "no-front-agent" if recs else "no-agents-map", "name": s, "other": ""}


def marks() -> dict:
    """The marks by project id ({} when there are none, or when the id file is damaged: a read goes on without them)."""
    try: return _read()["marks"]
    except ValueError: return {}


def set_mark(pid: str, **fields) -> dict:
    """Merge fields into a project's mark (a field set to None is dropped) → the mark. Under the lock; raises ValueError for a damaged id file."""
    with _Locked():
        d = _read(); m = d["marks"].setdefault(pid, {})
        for k, v in fields.items():
            if v is None: m.pop(k, None)
            else: m[k] = v
        _write(d); return dict(m)


def with_made(reg: dict) -> dict:
    """The registry plus an entry for each project made through `post project` whose page the registry does not hold yet (the pages checkout
    reads the new page a little after gbrain wrote it): the same fields a registry entry has, from the mark. Once the page is in the registry
    its own entry is the one read. `reg` itself is not changed."""
    out = reg
    for pid, m in marks().items():
        made = m.get("made")
        if not isinstance(made, dict): continue
        key = id_to_key(pid, reg)
        if not key or key in reg: continue
        made_name = str(made.get("display_name") or made.get("steward") or "")     # a mark written before an earlier change holds it as `steward`
        if out is reg: out = dict(reg)
        out[key] = {"title": str(made.get("title") or key), "name": str(made.get("name") or ""), "org": str(made.get("org") or ""), "tags": list(made.get("tags") or []),
                    "type": "project", "session": made_name, "role": "name" if made_name else "", "status": "active", "board": [],
                    "board_row": False, "updated": 0, "mirror": "", "id": pid, "key": key, "agent_records": {}, "made": True}
        out[key] = _pr.apply({key: out[key]}).get(key, out[key])        # the project's entry in the record is read before the mark: its agents and status are the record's
    return out


def recent_items(reg: dict, now: float | None = None, days: int = LISTED_DAYS) -> dict:
    """key → how many board items (open or completed) were touched within `days` days (`updated` or `state_updated`), for the project the item
    names and for every page above it in the registry (so a sub-page's items count for its project). Read from the item files of the store."""
    import time
    now = time.time() if now is None else now
    ck = (str(_store()), int(now // 30), days, len(reg))
    hit = _RECENT.get(ck)               # one read: another thread's clear() between a test and a read would raise
    if hit is not None:
        return dict(hit)
    first = (_cfg.page_dirs() or ["projects"])[0]
    out: dict = {}
    try: dirs = sorted(d for d in _store().iterdir() if d.is_dir() and len(d.name) == 1 and d.name.isalpha())
    except OSError: dirs = []
    for d in dirs:
        for p in d.glob("*.json"):
            if p.name.startswith(".") or not p.stem.isdigit(): continue
            try: it = json.loads(p.read_text(encoding="utf-8"))
            except Exception: continue
            if not isinstance(it, dict): continue
            try:
                ts = max(float(it.get("updated") or 0), float(it.get("state_updated") or 0))
                if now - ts > days * 86400: continue
                v = str(_iproj.key_of(it.get("metadata") or {}) or "").strip().strip("/")      # metadata may be anything in a file written by hand; read through the item's project id
            except (TypeError, ValueError, AttributeError): continue
            if v.endswith(".md"): v = v[:-3]
            if not v or _pr.is_id(v): continue         # a project with no page is stored by its id: no page above it to count for
            if "/" not in v: v = first + "/" + v
            parts = v.split("/")
            ks = [v] + [k for k in ("/".join(parts[:n]) for n in range(len(parts) - 1, 1, -1)) if k in reg]
            for k in list(ks):          # a page with a hub: line counts for its hub too (it is not a project of its own)
                h = str((reg.get(k) or {}).get("hub") or "").strip() if isinstance(reg.get(k), dict) else ""
                if h and h in reg and h not in ks: ks.append(h)
            for k in ks: out[k] = out.get(k, 0) + 1
    _RECENT.clear(); _RECENT[ck] = dict(out)
    return out


def listing_fields(key: str, entry: dict, reg: dict, agents: dict, mark: dict | None, recent: dict) -> dict:
    """What a record gains for the project picker: title, name, type, hub, scope (set on purpose, else derived), scope_set, listed, listed_by
    (agents | items | on_purpose | ""), sub_page and items_30d. Listed = has agents (a pending one counts), or an item touched in the last
    LISTED_DAYS days, or marked on purpose; a sub-page (a page under another, or with a `hub:` line) and a `type: note` page never are.
    A retired project (its page `status` is one of retired_statuses) is never listed, whatever its agents, items or mark: `retired` is true
    and `status` is the page's word (lowercase, "" if none)."""
    mark = mark or {}
    status = page_status(entry); retired = status in retired_statuses()
    stored = str(mark.get("scope") or "")
    scope_set = stored in scopes()
    sub = is_sub_page(key, reg, entry)
    typ = str(entry.get("type") or "").strip().lower()
    n = int(recent.get(key, 0))
    by = "" if sub or retired or typ == "note" else "agents" if agents else "items" if n else "on_purpose" if mark.get("on_purpose") else ""
    return {"title": str(entry.get("title") or key), "name": str(entry.get("name") or ""), "type": typ, "hub": str(entry.get("hub") or ""),
            "scope": stored if scope_set else derive_scope(key, entry, reg),
            "scope_set": scope_set, "listed": bool(by), "listed_by": by, "sub_page": sub, "items_30d": n, "status": status, "retired": retired}


def main_of(agents: dict) -> str:
    """The project's main agent: the front entry whose name ends in -main ("" when none). One the page lists wins over one only registered here
    (page_owed): a pending entry is the main agent only when the page has none."""
    mains = [(bool(a.get("page_owed")), n) for n, a in sorted(agents.items()) if a.get("front") and n.endswith("-main")]
    return min(mains)[1] if mains else ""


def list_projects(scope: str = "", q: str = "", reg: dict | None = None, now: float | None = None) -> list:
    """The projects of a scope ("" or "all" = every scope) the picker shows: every listed one, then (only when `q` is given) the hidden ones whose
    key, name or title holds `q` (case-insensitive), each with `hidden: true` (a `type: note` page that project-agent would take can be one; a sub-page or a
    page with a `hub:` line is never in it, listed or not; neither is a retired project, whatever it has). Each row: id, key, title, name, type, hub, scope,
    listed, hidden, listed_by, keeper, main, agents, items_30d, status, retired (false in every row). Sorted by key, listed rows first."""
    reg = with_made(registry() if reg is None else reg)
    by = _ids_for(list(reg), reg); pend = _pending_all(); mk = marks(); recent = recent_items(reg, now)
    qq = str(q or "").strip().lower(); want = "" if scope in ("", "all") else scope
    shown, hidden = [], []
    for key, entry in sorted(reg.items()):
        if not isinstance(entry, dict): continue
        r = _record(key, entry, reg, by[key], pend.get(by[key], {}), mk.get(by[key]), recent)
        if r["sub_page"] or r["retired"] or (want and r["scope"] != want): continue
        if not r["listed"] and not (qq and any(qq in h.lower() for h in (key, r["name"], r["title"]))): continue
        row = {"id": r["id"], "key": key, "title": r["title"], "name": r["name"], "type": r["type"], "hub": r["hub"], "scope": r["scope"], "listed": r["listed"], "hidden": not r["listed"],
               "listed_by": r["listed_by"], "keeper": r["keeper"], "main": main_of(r["agents"]), "agents": r["agents"], "items_30d": r["items_30d"],
               "status": r["status"], "retired": False}
        (shown if r["listed"] else hidden).append(row)
    return shown + hidden


# ---------------------------------------------------------------------------- a new project's page
SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def display_name_for(key: str, scope: str = "") -> str:
    """The name the page's agents are called <name>-<role> after, following the scope so that derive_scope reads the scope back from the page
    alone: `<scope>-<slug>`, except that a slug already starting with `<scope>-` is its own name (projects/team-alpha with scope team → team-alpha; infra/hub with
    scope infra → infra-hub; projects/bar with scope lab → lab-bar). With no scope given, the scope [project_scopes.by_prefix] maps the key's prefix to, else the default scope."""
    slug = key.rpartition("/")[2]
    scope = scope or next((s for pre, s in (_cfg.get("project_scopes", "by_prefix") or _BY_PREFIX).items() if key.startswith(pre) and s in scopes()), default_scope())
    return slug if slug.startswith(scope + "-") else f"{scope}-{slug}"


def slug_title(key: str) -> str:
    """A readable title from the slug when none was given: "team-alpha" → "Team alpha"."""
    return key.rsplit("/", 1)[-1].replace("-", " ").capitalize()


_YAML_NOT_A_STRING = re.compile(r"""(?ix)
      y | n | yes | no | true | false | on | off | null | ~                                  # the bool and null words, any case
    | [-+]? (?: 0[xob][0-9a-f_]+ | [0-9][0-9_,]* (?:\.[0-9_]*)? (?:e[-+]?[0-9]+)? )          # integers (decimal, octal, hex, binary, with _ or ,), floats
    | \d{4}-\d{1,2}-\d{1,2} .*                                                           # a date or a timestamp, however it goes on
    """)


def _yaml_scalar(v: str) -> str:
    """A mandate as a YAML scalar that loads back as the same string: plain when plain YAML reads it as that string, else a double-quoted (JSON)
    string. Quoted: anything with a colon, hash, quote or backslash, one starting with a character YAML gives a meaning (-, ?, [, !, &, *, …),
    an empty one, and a plain one YAML would read as a bool or null (yes/no/true/false/on/off/y/n/null/~, any case), a number (integer, float,
    hex, octal, binary) or a date/timestamp (YYYY-MM-DD…)."""
    v = " ".join(str(v).split())
    plain = re.fullmatch(r"[A-Za-z0-9][^:#\"'\\]*", v) and not _YAML_NOT_A_STRING.fullmatch(v)
    return v if plain else json.dumps(v, ensure_ascii=False)


def agents_yaml(agents: dict, has_map: bool = False, has_back: bool = False) -> str:
    """The YAML for the agents of a record that are only registered here (`page_owed`), front ones as entries of the map, background ones under
    `background:` (the shape the pages carry); "" when none is owed. It covers only the owed agents, never the whole map: add these under the
    page's existing `agents:` map; do not replace it. With `has_map` (the page already has an agents map) the entries only, with no `agents:`
    header, indented to go under that map; without it the `agents:` header is included. With `has_back` (the map already has a `background:`
    sub-map) no `background:` header is written either: the background entries stay at four spaces, to be put under the page's existing
    `background:` (a second `background:` key would silently drop the page's own background agents). The mandate is quoted only when plain
    YAML would misread it (see _yaml_scalar)."""
    owed = {n: a for n, a in sorted(agents.items()) if a.get("page_owed")}
    front = [(n, a) for n, a in owed.items() if a.get("front")]; back = [(n, a) for n, a in owed.items() if not a.get("front")]
    if not owed: return ""
    out = ([] if has_map else ["agents:"]) + [f"  {n}: {_yaml_scalar(a.get('mandate_line', ''))}" for n, a in front]
    if back: out += ([] if has_back else ["  background:"]) + [f"    {n}: {_yaml_scalar(a.get('mandate_line', ''))}" for n, a in back]
    return "\n".join(out) + "\n"


def _pretty_date(d: datetime.datetime) -> str:
    n = d.day; suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{d.strftime('%a %b')} {n}{suf}"


def page_front(key: str, title: str, scope: str, now: float | None = None) -> dict:
    """The fields a new page's frontmatter carries: title, name, org (a scope that is an org; the others are the owner's, with the tag that maps
    to the scope), status, created, display-name."""
    import time
    now = time.time() if now is None else now
    orgs = _cfg.get("project_scopes", "orgs")
    orgs = [str(o) for o in orgs] if isinstance(orgs, list) else scopes()          # [project_scopes] orgs: the scopes a page names as its `org:` (every scope by default)
    org = scope if scope in orgs else default_scope()
    tags = [t for t, s in (_cfg.get("project_scopes", "by_tag") or _BY_TAG).items() if s == scope and s != org][:1]   # a scope that is no org: the default's org + the tag that maps to the scope
    return {"title": title, "name": title, "org": org, "tags": tags,
            "display_name": display_name_for(key, scope),
            "created": datetime.datetime.fromtimestamp(now, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")}


def new_page(key: str, title: str, scope: str, now: float | None = None) -> str:
    """The markdown of a new project's page: the project template (Part 2 of the page [pages] template_page names): frontmatter, Goal, Current state,
    Decisions, Open questions, Open work, the sensitive-records register, Where things are, then the timeline marker and its first line.
    The `agents:` map is left out: the project's first agent is added to the page by its keeper (the record lists it meanwhile)."""
    import time
    now = time.time() if now is None else now
    f = page_front(key, title, scope, now)
    local = datetime.datetime.fromtimestamp(now, _cfg.tz())
    iso, pretty = local.strftime("%Y-%m-%d"), _pretty_date(local)
    mirror = str(_cfg.get("gbrain", "mirror_url") or "https://github.com/example/brain/blob/main/{key}.md")
    tpage = str(_cfg.get("pages", "template_page") or "").strip().strip("/")              # [pages] template_page: the page holding the project template ("" = none named)
    from stackshot.projects import brains as _brains                                                               # the template page may sit in a second brain ([[brains]]): its own mirror
    tb = _brains.for_key(tpage) if tpage else None
    tlink = mirror.format(key=tpage) if tb is not None and tb.default else (_brains.mirror(tpage) if tb is not None else "")   # a second brain with no mirror: no link, never the default brain's
    stack = ("[[" + tpage + "]]" + (" ([GitHub](" + tlink + "))" if tlink else "")) if tpage else ""
    rules = str(_cfg.get("pages", "rules_line") or "").strip()                           # [pages] rules_line: the bullet that links the rules ("" = none)
    where = "\n".join(x for x in [rules, ("- Page template: Part 2 of " + stack + ".") if stack else ""] if x) or "- Not written yet."
    made_from = f"from the project template of {stack}" if stack else "from the project template"
    y = lambda v: json.dumps(v, ensure_ascii=False)       # a JSON string is a valid double-quoted YAML scalar
    fm = ["---", "type: project", f"title: {y(f['title'])}", f"org: {f['org']}", f"name: {y(f['name'])}", "status: active", f"created: {y(f['created'])}", f"display-name: {f['display_name']}"]
    if f["tags"]: fm += ["tags:"] + [f"  - {t}" for t in f["tags"]]
    fm.append("---")
    _tool = _cfg.fleet_tool() or "the fleet tool"             # [fleet] tool_name: the page says which tool made it
    body = f"""
# {title}

Project page = current state; timeline = history. Made through {_tool}'s New session form on {pretty} (scope: {scope}); the project's first agent fills in the sections below. A sensitive value is never written here: the register below says that the record exists, whether Claude can fetch it and where it lives.

## Goal

Not written yet: what this project is for and what done means.

## Current state (as of {iso})

- Page made {pretty}; no agent has written the state yet.

## Decisions

None yet.

## Open questions

None yet.

## Open work, in planned order

None yet.

## Sensitive records — what exists, who can fetch it, where

None recorded yet.

## Where things are

{where}

<!-- timeline -->

## Timeline
- **{iso}** | stackshot — Page made through {_tool}'s New session form (scope: {scope}) {made_from}.
"""
    return "\n".join(fm) + "\n" + body


# ---------------------------------------------------------------------------- pending agents (an agent registered here, its page line still owed)
def add_pending(pid: str, name: str, agent: dict, by: str = "", at: str = "") -> None:
    """Record an agent in the project's record only. `by` and `at` (who registered it, when) stay in the id file, not in the published one."""
    with _Locked():
        d = _read(); d["pending_agents"].setdefault(pid, {})[name] = {"front": bool(agent["front"]), "role": str(agent["role"]), "mandate_line": str(agent["mandate_line"]),
                                                                       **({"by": by} if by else {}), **({"at": at} if at else {})}
        _write(d)


def drop_pending(pid: str, name: str) -> int:
    """Drop the project's pending entry for `name` (case-folded), if there is one: the page holds the record now (a rename moved the name on the page).
    Only that project's entry, never another project's or another name. → how many were dropped (0 or 1)."""
    with _Locked():
        d = _read(); m = d["pending_agents"].get(pid) or {}
        hit = [n for n in m if str(n).casefold() == str(name).casefold()]
        for n in hit: del m[n]
        if hit: _write(d)           # _write leaves out an id whose pending map is empty
    return len(hit)


def drop_pending_named(names, before_write=None) -> list:
    """Drop the pending entry of every name in `names` (case-folded) from every project's pending map. For a name that no longer stands for a session
    (a hand repair, tools/drop_renamed_pending.py). → [(project id, name, the entry that was dropped)] in the order dropped, so a caller can record it and put it
    back (restore_pending). `before_write(dropped)`, when given, is called with that list inside the record's lock, after the entries are found and before the record
    is written: a caller that keeps an undo file writes it there from exactly what is dropped, so no entry leaves without being in it; if it raises, nothing is written."""
    want = {str(n).casefold() for n in names}
    out: list = []
    if not want: return out
    with _Locked():
        d = _read()
        for pid, m in sorted(d["pending_agents"].items()):
            for n in [n for n in m if str(n).casefold() in want]:
                out.append((pid, n, dict(m.pop(n))))
        if out:
            if before_write is not None: before_write(list(out))
            _write(d)           # _write leaves out an id whose pending map is empty
    return out


def settle_renamed_pending(renames: dict, listed, now: float, min_age: float = 600.0) -> list:
    """The pending agents whose name is the old name of a renamed session (`renames`: old name -> new name, compared case-folded), settled in one pass under the record's lock.
    An entry registered less than `min_age` seconds ago (its `at`) is skipped: a session may be registered here before sala lists it, and the next pass takes it. Otherwise,
    when the new name is registered somewhere (`listed`: the case-folded names the pages list, or any project's pending map holds), the old entry is dropped; when it is
    registered nowhere, the entry is renamed to the new name in its own project, every other field kept. → [(project id, old name, entry, "dropped" | "renamed" | "kept", new name)]
    for every entry that matched, kept ones included (too young). Nothing is written when none was dropped or renamed."""
    ren = {str(k).casefold(): str(v) for k, v in (renames or {}).items()}
    out: list = []
    if not ren: return out
    with _Locked():
        d = _read(); known = {str(x).casefold() for x in listed} | {str(n).casefold() for m in d["pending_agents"].values() for n in m}; changed = False
        for pid, m in sorted(d["pending_agents"].items()):
            for n in list(m):
                new = ren.get(str(n).casefold())
                if not new: continue
                e = dict(m[n])
                try: age = now - datetime.datetime.fromisoformat(str(e.get("at")).replace("Z", "+00:00")).timestamp()
                except ValueError: age = float("inf")       # no readable time: old enough
                if age < min_age: out.append((pid, n, e, "kept", new)); continue
                del m[n]; changed = True
                if new.casefold() in known: out.append((pid, n, e, "dropped", new))
                else: m[new] = e; known.add(new.casefold()); out.append((pid, n, e, "renamed", new))
        if changed: _write(d)
    return out


def restore_pending(entries) -> int:
    """Put back entries drop_pending_named returned, [(project id, name, entry)]; an entry whose project now holds that name (case-folded) is left as it is.
    → how many were put back."""
    n = 0
    with _Locked():
        d = _read()
        for pid, name, entry in entries:
            m = d["pending_agents"].setdefault(pid, {})
            if any(str(x).casefold() == str(name).casefold() for x in m): continue
            m[name] = dict(entry); n += 1
        if n: _write(d)
    return n


def with_pending(reg: dict, made: bool = False) -> dict:
    """The page registry plus the agents only the record holds (their page line still owed), for the readers that take agents from the registry
    (anchors.session_roles / file_roles, the board's project table). An agent made through sala's New session form showed
    under Unregistered and nowhere on the board, because those readers saw page-listed agents only. Each such name joins its page's `agents`
    (name → mandate_line) and, when it is not front, `back_agents`; `owed_agents` (name → role) lists them, so a reader can tell them from the
    page's. The page wins: a name the page lists is left as it is. A retired project (its `status`) gains nothing. A project made through
    `post project` whose page the registry has not read yet (with_made) joins the result when `made` and it has an owed agent (roles: its agents
    are registered at once), else it is skipped (the board has no row without a page). `reg` itself is not changed. It never raises: callers
    such as the server's gates have no try around session_roles, so any failure (a damaged or unreadable record, hand-edited marks) returns `reg`."""
    try:
        d = _read()
        full = with_made(reg) if made else reg; out = reg
        for pid, m in sorted(d["pending_agents"].items()):
            if not m: continue
            key = d["ids"].get(pid) or id_to_key(pid, reg); e = full.get(key)
            if not key or not isinstance(e, dict) or page_status(e) in retired_statuses(): continue
            e = dict(e); agents = dict(e.get("agents") or {}); back = dict(e.get("back_agents") or {}); owed = dict(e.get("owed_agents") or {})
            for n, a in sorted(m.items()):
                if n in agents: continue              # the page wins
                agents[n] = str(a.get("mandate_line") or ""); owed[n] = str(a.get("role") or "")
                if not a.get("front"): back[n] = agents[n]
            if not owed: continue
            if out is reg: out = dict(reg)             # not `full`: a made project with no owed agent stays out
            out[key] = {**e, "agents": agents, "owed_agents": owed, **({"back_agents": back} if back else {})}
        return out
    except Exception:  # noqa: BLE001
        return reg


def prune_pending(reg: dict | None = None) -> int:
    """Drop every pending agent the page lists now (the page is the record once it carries the line). → how many were dropped."""
    reg = registry() if reg is None else reg
    if not reg: return 0
    with _Locked():
        d = _read(); n = 0
        for pid, m in list(d["pending_agents"].items()):
            e = reg.get(d["ids"].get(pid, "")) or {}
            for name in list(m):
                if name in (e.get("agents") or {}): del m[name]; n += 1
        if n: _write(d)             # _write leaves out an id whose pending map is empty
    return n


# ---------------------------------------------------------------------------- stamping the registry, and the published file
# The registry file is written with sorted keys, so that it changes only when a page does. The two agent maps are the exception: their
# order is the page's own, because the readers that need one agent out of several take the first listed (router_live.builder: the first
# background agent whose mandate says build). Sorted, a page that lists `my-engineer` before `my-early-engineer`
# had the second one named its keeper, as "early" sorts before "engineer".
_PAGE_ORDER_KEYS = ("agents", "back_agents")


def _sorted_keys(o, keep_order: bool = False):
    if isinstance(o, dict):
        items = list(o.items()) if keep_order else sorted(o.items(), key=lambda kv: str(kv[0]))
        return {k: _sorted_keys(v, k in _PAGE_ORDER_KEYS) for k, v in items}
    if isinstance(o, list):
        return [_sorted_keys(v) for v in o]
    return o


def registry_json(doc: dict) -> str:
    """The registry file's text: keys sorted at every level except inside a page's `agents` and `back_agents`, which keep the page's order."""
    return json.dumps(_sorted_keys(doc), ensure_ascii=False, indent=1)


def stamp_registry() -> bool:
    """The one-time backfill at a server start: give the registry file's pages the `id`, `key` and `agent_records` fields they lack
    (cmd_registry writes them from then on). Atomic; the same pages, nothing else changes. → True when the file was rewritten."""
    p = registry_path()
    with _Locked():                 # the same lock as the registry's rebuild (pages.cmd_registry): neither overwrites the other's file
        try: doc = json.load(open(p, encoding="utf-8"))
        except Exception: return False
        pages = doc.get("pages") if isinstance(doc, dict) else None
        if not pages: return False
        by = ensure_ids(list(pages)); changed = False
        for key, e in pages.items():
            if not isinstance(e, dict): continue
            f = registry_fields(key, e, pages, by[key])
            if any(e.get(k) != v for k, v in f.items()): e.update(f); changed = True
        if changed: write_atomic(p, registry_json(doc))
    return changed


def _utc(now: float) -> str:
    return datetime.datetime.fromtimestamp(now, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sync(now: float | None = None, force: bool = False, reg: dict | None = None, path: Path | None = None) -> bool:
    """Rewrite the published file (atomic tmp + replace) when the records changed, when it is EVERY seconds old (or unreadable), or
    when forced. An empty registry (none yet) writes nothing: a stale file is the reader's cue, an empty one would say there are no
    projects. → True when written."""
    import time
    now = time.time() if now is None else now
    reg = registry() if reg is None else reg
    if not reg: return False
    try: prune_pending(reg)
    except ValueError: pass         # a damaged id file: nothing is pruned, and build() answers from the registry's own copy of the ids
    body = build(reg, now)
    path = published_path() if path is None else path
    with _LOCK:
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            age = now - datetime.datetime.fromisoformat(str(old["generated"]).replace("Z", "+00:00")).timestamp()
        except Exception:
            old, age = {}, float("inf")
        if not force and old.get("schema") == SCHEMA and old.get("projects") == body["projects"] and old.get("by_key") == body["by_key"] and 0 <= age < EVERY:
            return False
        write_atomic(path, json.dumps({"schema": SCHEMA, "generated": _utc(now), **body}, ensure_ascii=False, indent=1, sort_keys=True))
    return True


USAGE = ("usage: python3 -m stackshot projects rename <old page key> <new page key>\n"
         "       python3 -m stackshot projects fields <id | page key | bare slug>    one project's name, status and agents as JSON: the record first, the page's lines for what it does not hold\n"
         "       python3 -m stackshot projects fields --all                          the same for every page that names a project or lists an agent (a JSON list)\n"
         "fields exit 0 found · 1 no such project · 2 the registry or the project record cannot be read here (run it on the server box, where <store>/projects.json is)")


def main(a: list) -> int:
    """`projects rename <old> <new>`: a page was moved, its project id follows (rename_page.py does this itself). `projects fields <project> | --all`: the read-through."""
    if a[:1] in (["-h"], ["--help"]):
        print(USAGE); return 0
    if len(a) == 3 and a[0] == "rename":
        try: print(f"{rename(a[1], a[2])}: now {a[2]}")
        except ValueError as e: sys.exit(f"projects.py: {e}")
        return 0
    if len(a) == 2 and a[0] == "fields":
        if not registry_raw():
            print("projects.py fields: no page registry here (<store>/projects.json is missing or empty): run it on the server box", file=sys.stderr); return 2
        bad = _pr.record_error()
        if bad:        # the readers fall back to the pages' lines on a damaged record; a script reading the record must be told, the lines may be no longer written
            print(f"projects.py fields: the project record cannot be read: {bad}", file=sys.stderr); return 2
        try:
            out = all_fields() if a[1] == "--all" else fields(a[1])
        except ValueError as e:
            print(f"projects.py fields: the project record cannot be read: {e}", file=sys.stderr); return 2
        if out is None:
            print(f"projects.py fields: no project {a[1]!r}: an id (prj_<8 hex>), a page key or a bare slug", file=sys.stderr); return 1
        print(json.dumps(out, indent=1, ensure_ascii=False, sort_keys=True)); return 0
    print(USAGE, file=sys.stderr); return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
