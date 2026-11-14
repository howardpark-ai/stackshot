"""project_verbs.py — the verbs that write a project's identity: the record first, then the page mirror.

A project is defined by its entry in the project record (project_registry.py). Every write to what a project is goes through one of these verbs, so that the
record is always the one that is right and the page is a copy stackshot writes from it:

    create       a new project: name, scope, and optionally a page (made from the template only when asked to)
    adopt        a project from a page that never had one: the page is read once, the entry is written from it (`how: adopted`, with the page revision read), and from then on the page is only a pointer
    rename       the project's name: the id stays, the old name goes to `former_names`, the pending agents under the old name are dropped
    move_page    the project's page moves to another key (rename_page.py does the page half): the old key goes to `former_keys`
    archive      status archived, with who, when and how; reopen puts it back to active
    agent_add / agent_mandate / agent_retire / agent_rename   the project's agents map, with its mandate lines (agent_mandate changes the line of an agent already listed)
    restore      the record, or one project of it, put back from a past revision of the store's history in its repository (project_restore.py): a dry run unless asked to apply, with an undo file

Each verb is one atomic change of the record under the record's own lock (projects.locked: the same flock every writer of the file takes), then a write of the page mirror if
the project has a page in this instance's page store. The mirror is three lines of the page's frontmatter and nothing else: `display-name:` (the project's name), `agents:` (the
map, front agents first and a `background:` sub-map) and `status:`. It is computed from the record as it is when it is written, never from what an earlier step meant to write, so two
verbs at once leave the same page whichever writes last; a page edit by anyone else to one of the three lines is overwritten by the next mirror write. If the mirror cannot be
written the verb says so in its answer (`mirror.state` = "failed") and the record is already right: nothing is rolled back, and `mirror()` writes it again.

The copy is retired per page and everywhere: a page in a brain marked `shared` ([[brains]] shared = true, brains.shared_refusal) is never written, and `[pages] copy_project_lines = false` stops it on every brain; the
verb's answer then says `mirror.state` = "retired" with the reason, and the page store is not called. The switch retires the copied lines only: a page asked for with `make_page` is still made from the template on a brain not marked shared (`mirror.state` = "written", the template's own `display-name:` and `status:` lines, no `agents:` block), while a shared brain is never written, a new page included. The record is what readers use: `projects.fields` (python3 -m stackshot projects fields) reads it first and the page's lines
for a project the record does not hold yet.

A project with no entry yet (the migration has not run, or not reached it) gets its entry from the page lines the registry derives, with the migration's own function (`derive_entry`), at its
first verb; the project's pending agents (agents the form registered before this) are folded into the entry in the same write. A project with no page has no mirror and no page store call at all.

Every verb takes `dry=True`: the answer is what would be written (the new entry, the page text it would put as a diff summary), and nothing is written to the record or the page.
`restore` is the one verb that is a dry run unless `apply=True`, and the one that writes no page mirror: it puts the record back as it was saved, and `mirror` writes the page lines from it after.

Stdlib plus the repo's modules (config, projects, project_registry, pages, page_debt); no network, no gbrain call except through the page store the caller passes."""
from __future__ import annotations

import copy
import datetime as dt
import json
import re
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from stackshot import paths as _paths
from stackshot.core import config as _cfg
from stackshot.projects import pages as _pg
from stackshot.projects import project_registry as pr
from stackshot.projects import projects as prj

NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
MIRROR_TRIES = 3


class VerbError(Exception):
    """A verb that cannot go on: nothing was written. `status` is the HTTP-shaped code a caller (the server) answers with."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hub_page(row: Any) -> str:
    """The page a registry row's `hub:` line names ("" when it has none): a page with a hub line is a sub-page of that page."""
    return _norm_key(row.get("hub")) if isinstance(row, dict) and str(row.get("hub") or "").strip() else ""


def _norm_key(x: Any) -> str:
    return pr._norm_key(x)


# ----------------------------------------------------------------------------- the entry of a project that has none yet
def derive_entry(pid: str, key: str, row: dict, reg: dict, mark: dict | None, now: str, by: str = "migration", how: str = "migrated", former=()) -> dict:
    """The entry the registry's values for the page `key` come to: the page's title and type, the name (the page's own `display-name:` when it has one), the scope the registry derives
    (a mark set on purpose first), status `archived` when the page's status is a retired word, the agents in the order the page lists them (a `background:` agent is not front), the hub, the page key,
    `former_keys`, and `made` (and `retired` for an archived one). Reading the entry gives what reading the page gave. `agents` is left out when the page lists none (a map that was never there)."""
    mark = mark or {}
    scope = str(mark.get("scope") or "")
    if scope not in prj.scopes():
        scope = prj.derive_scope(key, row, reg)
    archived = prj.page_status(row) in prj.retired_statuses()
    ent: dict = {"title": str(row.get("title") or key), "type": str(row.get("type") or "project").strip(), "scope": scope, "status": "archived" if archived else "active", "page": key,
                 "hub": str(row.get("hub") or ""), "former_keys": list(former), "former_names": [], "made": {"at": now, "by": by, "how": how}}
    if row.get("agents"):
        ent["agents"] = seed_agents(row)
    if row.get("role") in prj._NAME_ROLES and str(row.get("session") or ""):
        ent["name"] = str(row["session"])
    if archived:
        ent["retired"] = {"at": now, "by": by, "how": how}
    return ent


def seed_agents(row: dict | None) -> dict:
    """A page registry row's agents as an entry's map: {name: {front, mandate_line}} in the page's order, a `background:` agent not front. {} for a row that lists none."""
    if not isinstance(row, dict) or not row.get("agents"):
        return {}
    back = set(row.get("back_agents") or {})
    return {str(n): {"front": str(n) not in back, "mandate_line": str(m)} for n, m in row["agents"].items()}


def fold_pending(ent: dict, pend: dict) -> list[str]:
    """Put the project's pending agents (`pend`: name → {front, mandate_line, by, at}) into the entry's agents after the ones it lists; a name the entry has already stays as it is. → the names added."""
    added = []
    for n, a in sorted(pend.items(), key=lambda kv: (str(kv[1].get("at") or ""), kv[0])):
        ag = ent.setdefault("agents", {})
        if any(x.casefold() == n.casefold() for x in ag):
            continue
        ag[n] = {"front": bool(a.get("front")), "mandate_line": str(a.get("mandate_line") or ""),
                 **({"by": str(a["by"])} if a.get("by") else {}), **({"at": str(a["at"])} if a.get("at") else {})}
        added.append(n)
    return added


# ----------------------------------------------------------------------------- the transaction
class Ctx:
    """What a verb sees inside the lock: the record file's tables (`d`, as projects._read gives them), the entries (`ents`, a copy it may change), and the pages-only registry."""

    def __init__(self, d: dict, ents: dict, now: str, by: str, pages: dict | None = None):
        self.d, self.ents, self.now, self.by = d, ents, now, by
        self.pages = pages or {}                    # page key → its text as read BEFORE the lock was taken (None: the read failed); a verb never reads the page store inside the lock
        self.warn = ""
        self._raw: dict | None = None

    @property
    def raw(self) -> dict:
        if self._raw is None:
            self._raw = prj.registry_raw()
        return self._raw

    def key_ids(self) -> dict:
        out: dict = {}
        for i, k in sorted(self.d["ids"].items()):
            out.setdefault(k, i)
        return out

    def pid_of(self, x: Any) -> str:
        """The id of the project `x` names: an id, a page key (a current one, a bare slug through [registries.projects] match, a former key) or a former name. "" when it names none."""
        x = str(x or "").strip()
        if not x:
            return ""
        if prj.is_id(x):
            if x in self.ents:
                return x
            if x in self.d["ids"]:
                self.not_sub(self.d["ids"][x])         # a sub-page has an id in the table, but is no project
                return x
            return ""
        k = _norm_key(x)
        pats = (_cfg.CFG.get("registries", {}).get("projects", {}) or {}).get("match") or ["{value}"]
        cands = list(dict.fromkeys([k] + [p.format(value=k) for p in pats]))
        cur, old, ids = pr.by_page(self.ents), pr.by_former_key(self.ents), self.key_ids()
        for c in cands:
            if c in cur:
                return cur[c]
        for c in cands:
            if c in ids and ids[c] not in self.ents and not self.owner(c):
                return ids[c]                      # a project with no entry yet is known by the id table (a sub-page has an id there, but is no project)
        for c in cands:
            if c in old:
                return old[c]
        for pid, e in sorted(self.ents.items()):
            if x and str(e.get("name") or "").casefold() == x.casefold():
                return pid
        for pid, e in sorted(self.ents.items()):
            if k and k in (e.get("former_names") or []):
                return pid
        for c in cands:                            # a sub-page is no project: it names the top-level project that owns it
            up = self.owner(c)
            if up:
                return cur.get(up) or old.get(up) or ids.get(up) or ""
        return ""

    def owner(self, key: str) -> str:
        """The top-level page that owns the sub-page `key` (the nearest page above it, or the page its `hub:` line names, and so on up to a page that has none); "" for a key that is no sub-page."""
        pages = {**pr.by_page(self.ents), **pr.by_former_key(self.ents), **self.raw}
        up, seen = "", {key}
        while True:
            nxt = pr.top_page(up or key, pages, lambda x: _hub_page(self.raw.get(x)))
            if not nxt or nxt in seen:
                return up
            up = nxt; seen.add(nxt)

    def refuse_sub_key(self, project: Any) -> None:
        """VerbError 400 when `project` is a page key of a sub-page: a verb that acts on the whole project (archive, reopen, move-page) is not done through a sub-page's key."""
        x = str(project or "").strip()
        if x and not prj.is_id(x):
            self.not_sub(_norm_key(x))

    def not_sub(self, key: str) -> None:
        """VerbError 400 when `key` is a sub-page: it names the top-level page to use instead."""
        up = self.owner(key) if key else ""
        if up:
            raise VerbError(400, f"{key} is a sub-page of {up}: a sub-page is never a project; name {up}, the project's own page")

    def fresh_row(self, key: str, row: dict) -> dict:
        """The registry row of page `key` with its agents, status and name line taken from the page text `pages` holds (read before the lock, see `preread`): the registry follows the pages
        checkout minutes late, and an entry made from a stale row would have the mirror delete an agent a session has just listed on the page. Never reads the page store: this runs inside the
        record's lock. The row as it is when the page was not pre-read; when the read failed too, `warn` says so."""
        if key not in self.pages:
            return row
        content = self.pages[key]
        if content is None:
            self.warn = f"the page {key} could not be read before the record was written, so the entry was made from the registry's copy of its lines (minutes behind); the mirror will not write over an agent line the record lacks"
            return row
        fm = _pg.frontmatter_text(content)
        row = dict(row)
        agents, back = _pg.split_agents(fm.get("agents"))
        row.pop("agents", None); row.pop("back_agents", None)
        if agents:
            row["agents"] = agents
        if back:
            row["back_agents"] = back
        row["status"] = fm.get("status") or ""
        if row.get("role") in prj._NAME_ROLES and str(fm.get("display-name") or "").strip():
            row["session"] = str(fm["display-name"]).strip()
        return row

    def entry(self, pid: str) -> dict:
        """The entry of project `pid`, made from the project's page as the page store has it now (its agents, status and name line; the registry's row for the rest) when it has none, and its pending agents
        folded in. VerbError when there is nothing to make it from, and 400 for a sub-page (it has an id in the table, but is no project)."""
        if pid in self.ents:
            return self.ents[pid]
        key = self.d["ids"].get(pid, "")
        row = self.raw.get(key) if key else None
        if not isinstance(row, dict):
            raise VerbError(404, f"{pid} is no project the record or the registry knows: nothing was changed")
        self.not_sub(key)
        row = self.fresh_row(key, row)
        ent = derive_entry(pid, key, row, self.raw, self.d["marks"].get(pid), self.now, by=self.by or "stackshot", how="migrated")
        if ent["status"] != "archived":
            fold_pending(ent, self.d["pending_agents"].get(pid) or {})
        self.d["pending_agents"].pop(pid, None)
        self.ents[pid] = ent
        return ent

    def agents(self, pid: str) -> dict:
        """The project's agents as the readers see them now: the entry's own map, else the page's lines (an entry that has no `agents` field)."""
        e = self.entry(pid)
        if "agents" in e:
            return e["agents"]
        key = pr.page_key(e)
        return seed_agents(self.raw.get(key) if key else None)


def _entryless_key(ctx: Ctx, project: Any) -> str:
    """The page key `project`'s entry would be made from, "" when it has an entry already (or none can be made)."""
    pid = ctx.pid_of(project)
    return "" if not pid or pid in ctx.ents else ctx.d["ids"].get(pid, "")


def preread(project: Any, io: Any = None) -> dict:
    """The page text a verb on `project` needs if the project has no entry yet, read here, BEFORE the record's lock (and any lock of the caller's) is taken: {page key: text}, or {key: None} when the
    read failed, or {} when the project has an entry or none can be made. The record's lock is held only for the look at the id table, never across the page store (a gbrain read can take a minute or
    two; every record writer and every client call waits on that lock). A caller that holds a lock of its own around a verb calls this first and passes the result as `pages`."""
    try:
        key = txn(lambda c: _entryless_key(c, project), dry=True)[0]
    except (VerbError, ValueError):
        return {}
    if not key:
        return {}
    try:
        if io is None:
            from stackshot.router import page_debt as _pd
            io = _pd.page_io()
        content, rev = io.get(key)
        return {key: content if (content is not None and rev) else None}
    except Exception:  # noqa: BLE001 — told in the answer's `warning`, the registry's row is the fallback
        return {key: None}


def _state(ctx: Ctx) -> str:
    return json.dumps([ctx.d["ids"], ctx.d["pending_agents"], ctx.d["marks"], ctx.ents], sort_keys=False, default=str)


def txn(fn: Callable[[Ctx], Any], by: str = "", now: str | None = None, dry: bool = False, pages: dict | None = None) -> tuple[Any, dict, bool]:
    """Run `fn(ctx)` on the record under its lock and write the result in one atomic write → (fn's answer, the entries now, whether anything changed). A dry run runs `fn` and writes nothing.
    ValueError (a damaged record) and VerbError leave the file as it was. `pages` = the page texts the verb read before this call (`preread`): nothing inside the lock reads the page store."""
    with prj.locked():
        d = prj._read()
        cur = pr.parse({pr.SECTION: d["extra"].get(pr.SECTION, {}), pr.VERSION: d["extra"].get(pr.VERSION, pr.SCHEMA)})
        ctx = Ctx(d, copy.deepcopy(cur), now or now_iso(), by, pages)
        before = _state(ctx)
        out = fn(ctx)
        if ctx.warn and isinstance(out, dict):
            out = {**out, "warning": ctx.warn}
        pr.parse({pr.SECTION: ctx.ents})
        changed = _state(ctx) != before
        if changed and not dry:
            if ctx.ents:
                d["extra"][pr.SECTION] = ctx.ents; d["extra"][pr.VERSION] = pr.SCHEMA
            else:
                d["extra"].pop(pr.SECTION, None); d["extra"].pop(pr.VERSION, None)
            prj._write(d)
        return out, ctx.ents, changed


# ----------------------------------------------------------------------------- the page mirror
def _read_strict(io: Any, key: str) -> tuple[str | None, str | None]:
    """The page store's read for a verb that must tell a page that is not there from a read that did not work: its `get_strict` (an OSError carries the real error), else its `get`
    (a store without one, such as a test's stand-in). (None, None) means the page is not there; a read that failed raises OSError, and is never told as "no page"."""
    return getattr(io, "get_strict", io.get)(key)


def _fm_end(lines: list[str]) -> int | None:
    if not lines or lines[0].strip() != "---":
        return None
    return next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)


def _set_scalar(lines: list[str], key: str, value: str) -> str:
    """Set the frontmatter line `key: value` in place (the line is replaced; a page with none gets it just before the closing `---`). → "" or why not (a key twice, a value that goes on below)."""
    end = _fm_end(lines)
    if end is None:
        return "the page has no closed frontmatter"
    hits = [i for i in range(1, end) if re.match(rf"^{re.escape(key)}:(\s|$)", lines[i])]
    if len(hits) > 1:
        return f"the page has more than one {key}: line"
    text = f"{key}: {prj._yaml_scalar(value)}"
    if hits:
        j = hits[0] + 1
        if j < end and lines[j][:1] in (" ", "\t") and lines[j].strip():
            return f"the page's {key}: line continues on the lines below it"
        lines[hits[0]] = text
    else:
        lines.insert(end, text)
    return ""


def _agents_lines(agents: dict) -> list[str]:
    out = ["agents:"]
    front = [(n, a) for n, a in agents.items() if a.get("front")]
    back = [(n, a) for n, a in agents.items() if not a.get("front")]
    out += [f"  {n}: {prj._yaml_scalar(a.get('mandate_line', ''))}" for n, a in front]
    if back:
        out += ["  background:"] + [f"    {n}: {prj._yaml_scalar(a.get('mandate_line', ''))}" for n, a in back]
    return out


def _norm_m(s: Any) -> str:
    return " ".join(str(s).split())


def _page_agents(fm: dict) -> tuple[list, list]:
    flat, back = _pg.split_agents(fm.get("agents"))
    return [(n, _norm_m(m)) for n, m in flat.items() if n not in back], [(n, _norm_m(flat[n])) for n in back]


def _want_agents(agents: dict) -> tuple[list, list]:
    return ([(n, _norm_m(a.get("mandate_line", ""))) for n, a in agents.items() if a.get("front")],
            [(n, _norm_m(a.get("mandate_line", ""))) for n, a in agents.items() if not a.get("front")])


def mirror_text(content: str, e: dict, retired: set | None = None) -> tuple[str | None, str]:
    """The page's text with its three mirrored lines set from the entry `e` → (new_text, "") or (None, why). A line that already reads as the entry says is left byte for byte as it is; only
    `display-name:` (when the entry has a name), `status:` and the `agents:` block (when the entry has an `agents` field) are ever touched, and the edited page must read back with exactly
    those values and every other field as it was, else nothing is returned."""
    retired = prj.retired_statuses() if retired is None else retired
    lines = str(content).split("\n")
    if _fm_end(lines) is None:
        return None, "the page has no closed frontmatter"
    fm0 = _pg.frontmatter_text(content)
    want: dict = {}
    if e.get("name") and str(fm0.get("display-name") or "").strip() != e["name"]:
        want["display-name"] = e["name"]
    word = pr._status_word(fm0.get("status", ""), e.get("status") or "active", retired)
    if word and word.lower() != str(fm0.get("status") or "").strip().lower():
        want["status"] = word
    for k, v in want.items():
        why = _set_scalar(lines, k, v)
        if why:
            return None, why
    if "agents" in e and _page_agents(fm0) != _want_agents(e["agents"]):
        end = _fm_end(lines)
        heads = [i for i in range(1, end) if re.match(r"^agents:(\s|$)", lines[i])]
        if len(heads) > 1:
            return None, "the page has more than one agents: key"
        block = _agents_lines(e["agents"])
        if heads:
            a = heads[0]; b = a + 1
            while b < end and (not lines[b].strip() or lines[b][:1] in (" ", "\t")):
                b += 1
            while b > a + 1 and not lines[b - 1].strip():
                b -= 1                                      # blank lines after the block are not the block's
            lines[a:b] = block
        else:
            at = end
            while at > 1 and not lines[at - 1].strip():
                at -= 1
            lines[at:at] = block
    out = "\n".join(lines)
    if out == content:
        return content, ""
    fm1 = _pg.frontmatter_text(out)
    bad = []
    if e.get("name") and str(fm1.get("display-name") or "").strip() != e["name"]:
        bad.append("display-name")
    if "status" in want and str(fm1.get("status") or "").strip() != want["status"]:
        bad.append("status")
    if "agents" in e and _page_agents(fm1) != _want_agents(e["agents"]):
        bad.append("agents")
    if bad:
        return None, f"the edited page does not read back with the record's {', '.join(bad)}: edit the page by hand"
    mirrored = {"display-name", "status", "agents"}
    if {k: v for k, v in fm0.items() if k not in mirrored} != {k: v for k, v in fm1.items() if k not in mirrored}:
        return None, "the edited page's other fields would change: edit the page by hand"
    return out, ""


def mirror_drift(content: str, e: dict, retired: set | None = None) -> list[str]:
    """Which of the three mirrored lines of the page text `content` do not read as the entry `e` says: a subset of ["display-name", "status", "agents"], in that order ([] = the page mirrors the record).
    The same comparisons `mirror_text` makes before it writes, so a page this lists is one the next mirror write changes. Never raises."""
    try:
        retired = prj.retired_statuses() if retired is None else retired
        fm = _pg.frontmatter_text(content)
        out = []
        if e.get("name") and str(fm.get("display-name") or "").strip() != e["name"]:
            out.append("display-name")
        word = pr._status_word(fm.get("status", ""), e.get("status") or "active", retired)
        if word and word.lower() != str(fm.get("status") or "").strip().lower():
            out.append("status")
        if "agents" in e and _page_agents(fm) != _want_agents(e["agents"]):
            out.append("agents")
        return out
    except Exception:  # noqa: BLE001
        return []


def _entry_now(pid: str) -> dict | None:
    e = pr.entries().get(pid)
    return copy.deepcopy(e) if isinstance(e, dict) else None


def _expire_former(pid: str, content: str) -> None:
    """A mirror has just left `content` as the page (written, or already so): the names in the entry's `former_agents` that the page no longer lists are dropped from the entry, since the guard
    needs them only until the page is rewritten. Never raises."""
    try:
        names = {n.casefold() for n in _pg.split_agents(_pg.frontmatter_text(content).get("agents"))[0]}
        gone = [x for x in (_entry_now(pid) or {}).get("former_agents") or [] if x.casefold() not in names]
        if not gone:
            return

        def work(ctx: Ctx) -> None:
            en = ctx.ents.get(pid)
            if en and en.get("former_agents"):
                keep = [x for x in en["former_agents"] if x not in gone]
                if keep:
                    en["former_agents"] = keep
                else:
                    en.pop("former_agents", None)
        txn(work)
    except Exception:  # noqa: BLE001
        pass


def shared_off(key: str) -> str:
    """"" when the page `key` is in a brain stackshot may write; else the line that says the brain is marked `shared`: nothing at all is written to it, a new page included."""
    from stackshot.projects import brains as _brains
    why = _brains.shared_refusal(key)
    return f"the page was not written: {why}" if why else ""


def switch_off() -> str:
    """"" when `[pages] copy_project_lines` is on; else the line that says the copy of the record onto pages is retired on every brain. The switch stops the copied lines only: a
    new project's page is still made (mirror, `make_page`) on a brain that is not marked shared."""
    if not _cfg.copy_project_lines():
        return "the page was not written: the copy of the record onto pages is retired ([pages] copy_project_lines = false); the record holds the project's name, status and agents"
    return ""


def copy_off(key: str) -> str:
    """"" when the copy of the record onto the page `key` is written; else why it is retired: a brain marked `shared` never gets it, and `[pages] copy_project_lines = false`
    retires it on every brain. The record is the one place the fields live then, and `projects.fields` is how a script reads them."""
    return shared_off(key) or switch_off()


def mirror(pid: str, io: Any = None, *, entry: dict | None = None, make_page: bool = False, dry: bool = False, tries: int = MIRROR_TRIES, now: float | None = None, exclusive: bool = False,
           drop: tuple = ()) -> dict:
    """Write the project's page mirror from its entry → {"state", "key", "note"}. States: "none" (the project has no page in this instance's page store: a project with no page, or a pointer
    that is a link elsewhere), "unchanged" (the page reads as the record says), "written", "would-write" (a dry run), "no-page" (the pointer names a page the store does not have, and `make_page` was
    not asked), "failed" (the page could not be edited or written; `note` says why), "exists" (`exclusive` only: the page store says the page the verb meant to make is there already; nothing was written to it), "retired" (shared_off or switch_off says why: the page is in a brain marked `shared`, or `[pages] copy_project_lines = false`; `note` names the reason; a shared brain's page store is never called, and with the switch off the store is called only for `make_page`, to read the page and make it when it is not there: a page made that way is "written" with the template's lines only, an existing page is "retired" and untouched). Never raises. The entry is the one given on the first try; on every later try, and for a write (not a dry run) in the verbs' own answers, it is read from the record again, so the last writer of either leaves the page the record describes.
    A page that lists an agent the record lacks gets its `agents:` block left as it is ("failed", the names in `note`; the name and status lines are still written): the page was edited since the record
    last said, and the write would delete that line for good. `drop` = the names the verb has just taken off the record on purpose (a retire, a rename), which the page may still list; the entry's
    `former_agents` keeps them until a mirror has left the page without them."""
    try:
        e = entry if entry is not None else _entry_now(pid)
        if not e:
            return {"state": "failed", "key": "", "note": f"{pid} has no entry in the record"}
        if not e.get("page"):
            return {"state": "none", "key": "", "note": "the project has no page"}
        key = pr.page_key(e)
        if not key:
            return {"state": "none", "key": "", "note": "its page is a link to another knowledge base: nothing is written there"}
        off = shared_off(key)                               # a shared brain gets nothing, a new page included
        if off:
            return {"state": "retired", "key": key, "note": off}
        off = switch_off()                                  # the switch retires the copied lines only: a page asked for with `make_page` is still made, with none of them written
        if off and not make_page:
            return {"state": "retired", "key": key, "note": off}
        from stackshot.router import page_debt as _pd
        if io is None:
            io = _pd.page_io()
        note = ""
        for attempt in range(1, max(1, tries) + 1):
            if attempt > 1 and not dry:
                e = _entry_now(pid) or e
            try:
                content, rev = _read_strict(io, key)
            except OSError as ex:
                return {"state": "failed", "key": key, "note": f"the page {key} could not be read, so nothing was written to it: {str(ex)[:300]}"}
            if content is None or not rev:
                if not make_page:
                    return {"state": "no-page", "key": key, "note": f"{key} is not in the page store: the record points at it and nothing was written there"}
                if dry:
                    return {"state": "would-write", "key": key, "note": f"would make {key} from the template"}
                st, msg = io.create(key, prj.new_page(key, e.get("title") or prj.slug_title(key), e.get("scope") or prj.default_scope(), now))
                if st == "exists":
                    if exclusive:
                        return {"state": "exists", "key": key, "note": f"the page store already has {key}"}
                    continue
                if st != "ok":
                    return {"state": "failed", "key": key, "note": f"the page store refused the new page {key} ({msg})" if st == "refused" else
                            f"the page store did not answer for the new page {key} ({msg}); the page may or may not have been written: ask again, and a 409 says it was"}
                if off:                                     # the switch is off: the page is the template's as made, and no copied line is written onto it
                    return {"state": "written", "key": key, "note": f"the page was made from the template; the copy of the record onto it is retired ([pages] copy_project_lines = false), so its display-name: and status: lines are the template's and no agents: block is written"}
                continue                                    # read it back and set the mirror lines on what was made
            if off:                                         # the page is there and the switch is off: nothing of the copy is written to it
                return {"state": "retired", "key": key, "note": off}
            guard = ""; ew = e
            if "agents" in e:
                listed = {n.casefold() for n in e["agents"]} | {str(n).casefold() for n in drop} | {str(n).casefold() for n in e.get("former_agents") or []}
                extra = [n for n in _pg.split_agents(_pg.frontmatter_text(content).get("agents"))[0] if n.casefold() not in listed]
                if extra:
                    guard = (f"the agents block of {key} was not written: the page lists {', '.join(extra)}, which the record does not: it was edited since the record last said, and the write would delete "
                             f"{'that line' if len(extra) == 1 else 'those lines'}; list {'it' if len(extra) == 1 else 'them'} with agent-add (the record first), then mirror again")
                    ew = {k: v for k, v in e.items() if k != "agents"}          # the name and status lines are still written
            new, why = mirror_text(content, ew)
            if new is None:
                return {"state": "failed", "key": key, "note": why + ("; " + guard if guard else "")}
            if new == content:
                if guard:
                    return {"state": "failed", "key": key, "note": guard}
                if not dry:
                    _expire_former(pid, content)
                return {"state": "unchanged", "key": key, "note": ""}
            if dry:
                return {"state": "would-write", "key": key, "note": f"{len(new.splitlines()) - len(content.splitlines()):+d} line(s) on {key}" + ("; " + guard if guard else "")}
            state, msg = _pd.put_state(io.put(key, new, rev))
            seen, _r = io.get(key)
            if seen is not None and mirror_text(seen, ew)[0] == seen and seen != content:
                if guard:
                    return {"state": "failed", "key": key, "note": guard + " (the name and status lines were written)"}
                _expire_former(pid, seen)
                return {"state": "written", "key": key, "note": ""}
            note = f"the page store {'refused' if state == 'refused' else 'got no answer to' if state == 'unknown' else 'accepted'} the page write for {key} ({msg})" + ("" if state != "ok" else " but a read back does not show it")
            if state != "refused":
                break                                       # accepted but not shown, or unknown: a second write could race the first
            e = _entry_now(pid) or e                        # the record may have moved on meanwhile: write what it says now
        return {"state": "failed", "key": key, "note": note or f"the page {key} could not be written"}
    except Exception as ex:  # noqa: BLE001 — the record is already right; the answer says the mirror is not
        return {"state": "failed", "key": "", "note": f"{type(ex).__name__}: {str(ex)[:160]}"}


def _timeline(io: Any, key: str, today: str, summary: str, by: str, tag: str) -> str:
    """One dated line on the page's timeline → "" or why not. Never raises. The request id carries the summary and the second, so a second rename, or an archive, a
    reopen and an archive again, on one day are not dropped as a repeat by gbrain's dedupe of request ids (a plain-markdown store drops a line it already has word for word)."""
    try:
        import hashlib
        at = dt.datetime.now(_cfg.tz())
        rid = f"stackshot-{tag}-{key}-{today}-{hashlib.sha1(summary.encode('utf-8')).hexdigest()[:6]}-{at.strftime('%H%M%S')}"
        return io.add_timeline(key, today, summary, f"by {by}" if by else "", "stackshot", rid) or ""
    except Exception as ex:  # noqa: BLE001
        return f"{type(ex).__name__}: {str(ex)[:120]}"


def _today() -> str:
    return dt.datetime.now(_cfg.tz()).strftime("%Y-%m-%d")


def _finish(pid: str, ents: dict, changed: bool, dry: bool, io: Any, make_page: bool = False, extra: dict | None = None, timeline: str = "", by: str = "", tag: str = "",
            mirror_now: bool = True, exclusive: bool = False, drop: tuple = (), warn: str = "") -> dict:
    """The common end of a verb: the page mirror from the entry just written, then the timeline line (when the page was changed and the verb has one). `mirror_now` False leaves the mirror to the
    caller (state "deferred"; call `mirror(pid, io)` later): a server that holds a lock across the check and the record write does not hold it across the page store."""
    e = ents.get(pid) or {}
    if not mirror_now:
        return {"project": pid, "key": pr.page_key(e), "changed": changed, "dry": dry, "entry": copy.deepcopy(e), "mirror": {"state": "deferred", "key": pr.page_key(e), "note": ""}, **(extra or {}), **({"warning": warn} if warn else {})}
    if io is None and pr.page_key(e):
        from stackshot.router import page_debt as _pd
        io = _pd.page_io()
    if e and not dry:
        e = _entry_now(pid) or e                    # the record as it is now: a verb that finished later may have changed it since this one's transaction
    m = mirror(pid, io, entry=e, make_page=make_page, dry=dry, exclusive=exclusive, drop=drop) if e else {"state": "none", "key": "", "note": ""}
    if timeline and not dry and m["state"] == "written":
        why = _timeline(io, m["key"], _today(), timeline, by, tag)
        if why:
            m = {**m, "note": (m["note"] + "; " if m["note"] else "") + f"the timeline line was not written ({why})"}
    return {"project": pid, "key": pr.page_key(e), "changed": changed, "dry": dry, "entry": copy.deepcopy(e), "mirror": m, **(extra or {}), **({"warning": warn} if warn else {})}


# ----------------------------------------------------------------------------- the verbs
def _name_taken(ctx: Ctx, name: str, pid: str, own: str = "") -> str:
    """Why `name` cannot be the name of project `pid` ("" when it can): another project's name or former name, or the name line of another project's page. `own` = the page key the project is made
    from (adopt): that page and the pages that belong to it (a sub-page that carries its project's name line) are not another project's."""
    fold = name.casefold()
    for p2, e2 in ctx.ents.items():
        if p2 != pid and (str(e2.get("name") or "").casefold() == fold or any(str(x).casefold() == fold for x in e2.get("former_names") or [])):
            return f"{name} is the name of project {p2}"
    for k2, row in ctx.raw.items():
        if isinstance(row, dict) and row.get("role") in prj._NAME_ROLES and str(row.get("session") or "").casefold() == fold and row.get("id") != pid and k2 not in ctx.ents:
            if own and (k2 == own or ctx.owner(k2) == own):
                continue
            return f"{name} is the name line of {k2}"
    return ""


def create(name: str, scope: str, page: str = "", *, make_page: bool = False, title: str = "", by: str = "", how: str = "made", io: Any = None, now: str | None = None, dry: bool = False,
           mark: bool = True, hub: str = "") -> dict:
    """Make a project: its entry in the record (a new permanent id, the name, the scope, status active, `made` = who and when). `page` is the pointer: a page key of this instance's page store, or
    any link to another knowledge base, or nothing (the default: the project has no page and none is made). With a page key and `make_page` the page is made from the template (the mirror
    creates it); without `make_page` the key is only the pointer, whether or not the page exists. `mark` also writes the listed-on-purpose mark (the form's window for a first agent). A page some
    project already points at, or a name some project has, is a 409; a sub-page (a key under another page, or a page with a `hub:` line) is a 400: only a top-level page can be a project's. → {project, key, changed, entry, mirror, created}."""
    name = " ".join(str(name or "").split())
    scope = str(scope or "").strip().lower()
    page = str(page or "").strip()
    if not NAME_RE.fullmatch(name):
        raise VerbError(400, "name = letters, digits, . _ - (at most 64), starting with a letter or digit: the prefix of the project's agents' names")
    if scope not in prj.scopes():
        raise VerbError(400, f"scope = {' | '.join(prj.scopes())}")
    key = ""
    if page:
        if "://" in page or re.search(r"\s", page):
            if make_page:
                raise VerbError(400, "a page can be made only for a page key of this instance's page store, not a link")
        else:
            key = _norm_key(page)
            top, _, slug = key.partition("/")
            if top not in _cfg.page_dirs() or not slug:
                raise VerbError(400, f"page = {' or '.join(d + '/<slug>' for d in _cfg.page_dirs())}, or a link to another knowledge base: got {page[:80]!r}")
            if make_page and (not prj.SLUG_RE.fullmatch(slug) or len(slug) > 60):
                raise VerbError(400, f"a page that is made is {' or '.join(d + '/<slug>' for d in _cfg.page_dirs())}, one level, the slug lowercase letters, digits and dashes (at most 60): got {key[:80]!r}")
            page = key
    elif make_page:
        raise VerbError(400, "make_page needs a page key")
    title = " ".join(str(title or "").split()) or (prj.slug_title(key) if key else name)
    if make_page and key:
        from stackshot.router import page_debt as _pd
        io = io if io is not None else _pd.page_io()
        try:
            made = _read_strict(io, key)[0] is not None
        except OSError as ex:
            raise VerbError(502, f"the page {key} could not be read, so it is not known whether it exists: {str(ex)[:300]}")
        if made:
            raise VerbError(409, f"{key} already exists as a page: point the project at it without make_page")
    if len(title) > 120 or any(ord(c) < 32 or c in '"\\' for c in title):
        raise VerbError(400, "title = one line of at most 120 characters, with no quotation marks or backslashes")

    def work(ctx: Ctx) -> dict:
        why = _name_taken(ctx, name, "")
        if why:
            raise VerbError(409, f"{why}: a name belongs to one project")
        pid = ""; fresh = True
        if key:
            up = ctx.owner(key)
            if up:
                raise VerbError(400, f"{key} is a sub-page of {up}: a sub-page is never a project; make the project on its top-level page ({up}), or on a page of its own")
            if "/" in key.partition("/")[2]:                     # below a page that is not in the registry (yet): still no top-level page
                raise VerbError(400, f"{key} is below another page: a project's page is {' or '.join(d + '/<slug>' for d in _cfg.page_dirs())}, one level (a page below a page is a sub-page, never a project)")
            if key in pr.by_page(ctx.ents):
                raise VerbError(409, f"{key} is already the page of a project ({pr.by_page(ctx.ents)[key]}): a page belongs to one project")
            if make_page and (key in ctx.raw or any(k.startswith(key + "/") for k in ctx.raw)):
                raise VerbError(409, f"{key} already exists as a page: point the project at it without make_page")
            row = ctx.raw.get(key)
            if isinstance(row, dict) and str(row.get("type") or "").strip().lower() == "project":
                raise VerbError(409, f"{key} is a project page that has no entry in the record yet: the migration makes its entry, a new project is not made over it")
            pid = ctx.key_ids().get(key, "")                      # an id the table reserved for this key is reused: one id per key
            fresh = not pid
            if pid and pid in ctx.ents:
                raise VerbError(409, f"{key} is already the page of a project ({pid}): a page belongs to one project")
        if not pid:
            while True:
                pid = "prj_" + secrets.token_hex(4)
                if pid not in ctx.d["ids"] and pid not in ctx.ents:
                    break
        if key:
            ctx.d["ids"][pid] = key
        ent: dict = {"name": name, "title": title, "type": "project", "scope": scope, "status": "active", "former_keys": [], "former_names": [],
                     "made": {"at": ctx.now, "by": by or "stackshot", "how": how}}
        if page:
            ent["page"] = page
        if hub:
            ent["hub"] = hub
        ctx.ents[pid] = ent
        if mark and not dry:
            m = ctx.d["marks"].setdefault(pid, {})
            m.update({"scope": scope, "on_purpose": ctx.now, "at": ctx.now, "by": by or "stackshot"})
            if key:
                f = prj.page_front(key, title, scope)
                m["made"] = {"at": ctx.now, "title": title, "name": name, "org": f["org"], "tags": f["tags"], "display_name": name}
        return {"pid": pid, "fresh": fresh}

    out, ents, changed = txn(work, by=by, now=now, dry=dry)
    res = _finish(out["pid"], ents, changed, dry, io, make_page=make_page, extra={"created": True}, by=by, exclusive=True)
    m = res["mirror"]
    if make_page and key and not dry and m["state"] in ("failed", "exists"):
        _forget_created(out["pid"], ents[out["pid"]], out["fresh"])           # a project whose page was asked for and could not be made is not made: the same call can be said again
        if m["state"] == "exists":
            raise VerbError(409, f"{key} already exists as a page: point the project at it without make_page")
        raise VerbError(502, f"{m['note']}; nothing was recorded")
    return res


def _forget_created(pid: str, made: dict, fresh: bool = True) -> None:
    """Take back the entry `create` just wrote (its id, its marks and the entry itself) when nothing has changed it since: the create's page could not be made, so there is no project."""
    def work(ctx: Ctx) -> None:
        if ctx.ents.get(pid) == made:
            del ctx.ents[pid]
            if fresh:
                ctx.d["ids"].pop(pid, None); ctx.d["marks"].pop(pid, None)
    txn(work)


def adopt(page: str, *, name: str = "", scope: str = "", by: str = "", io: Any = None, now: str | None = None, dry: bool = False) -> dict:
    """Make a project from a page that never had one: read the page once, from the page store, and write its entry from what it says (the name from its `display-name:` line, the scope the registry derives
    from it, the status, the agents map with the front and background split, the hub), with `made` = who, when, `how: adopted` and the `revision` of the page that was read. From then on the entry is
    the project and the page is only a copy the mirror writes: the page is not read for those fields again. The project's pending agents are folded into the entry, as at any first verb, and the project is listed on
    purpose (adopting is deliberate). `name` and `scope` override what the page says (a name the page gives that another project has, or none at all: the scope's name for the slug).
    Refused: a link or a key that is not a top-level page of this instance's page store (400), a sub-page, which is never a project (400), a page that is not `type: project` (400: set the type on the page first,
    then adopt), a page that does not exist (404), a page some project already points at or once had (409, naming the project), a name another project has (409). The page store is read before the record's
    lock is taken. → {project, key, changed, entry, mirror, adopted, revision}."""
    key = _norm_key(page)
    if not key or "://" in key or re.search(r"\s", key):
        raise VerbError(400, "adopt takes the key of a page of this instance's page store, not a link: " + (f"{page[:80]!r}" if page else "no page given"))
    top, _, slug = key.partition("/")
    if top not in _cfg.page_dirs() or not slug or "/" in slug:
        raise VerbError(400, f"page = {' or '.join(d + '/<slug>' for d in _cfg.page_dirs())}, one level: a page below another page is a sub-page, and a sub-page is never a project; got {key[:80]!r}")
    scope = str(scope or "").strip().lower()
    if scope and scope not in prj.scopes():
        raise VerbError(400, f"scope = {' | '.join(prj.scopes())}")
    name = " ".join(str(name or "").split())
    if name and not NAME_RE.fullmatch(name):
        raise VerbError(400, "name = letters, digits, . _ - (at most 64), starting with a letter or digit: the prefix of the project's agents' names")
    if io is None:
        from stackshot.router import page_debt as _pd
        io = _pd.page_io()
    try:
        content, rev = _read_strict(io, key)
    except OSError as ex:
        raise VerbError(502, f"the page {key} could not be read: {str(ex)[:300]}")
    if content is None or not rev:
        raise VerbError(404, f"{key} is not in the page store: there is no page to make a project from")
    fm = _pg.frontmatter_text(content)
    if str(fm.get("type") or "").strip().lower() != "project":
        raise VerbError(400, f"{key} is `type: {str(fm.get('type') or '').strip() or '(none)'}`, not `type: project`: set the page's type, then adopt it")
    own = str(fm.get("display-name") or "").strip()
    if not name and own and not NAME_RE.fullmatch(own):
        raise VerbError(400, f"the page's display-name: {own[:64]!r} is not a name an agent can be called after (letters, digits, . _ -, at most 64): change the line on the page, or give the name with --name")
    agents, back = _pg.split_agents(fm.get("agents"))
    base = {"title": str(fm.get("title") or key), "type": "project", "status": str(fm.get("status") or ""), "org": str(fm.get("org") or ""), "tags": fm.get("tags") or []}
    if own:
        base.update(session=own, role="name")
    if agents:
        base["agents"] = agents
    if back:
        base["back_agents"] = back

    def work(ctx: Ctx) -> dict:
        up = ctx.owner(key)
        if up:
            raise VerbError(400, f"{key} is a sub-page of {up}: a sub-page is never a project; adopt {up}, the project's own page")
        h = str(fm.get("hub") or "").strip().strip("'\"").strip("/")
        if h:
            h = "/".join((h if "/" in h else _cfg.page_dirs()[0] + "/" + h).split("/")[:2])
            if h != key and (h in ctx.raw or h in pr.by_page(ctx.ents)):
                raise VerbError(400, f"{key} has a `hub: {h}` line, which makes it a sub-page of {h}: a sub-page is never a project; adopt {h}")
        cur = pr.by_page(ctx.ents)
        if key in cur:
            raise VerbError(409, f"{key} is already the page of project {cur[key]}: a page belongs to one project")
        former = pr.by_former_key(ctx.ents)
        if key in former:
            raise VerbError(409, f"{key} is a former page of project {former[key]}: that project moved away from it; adopt the page it points at now")
        pid = ctx.key_ids().get(key, "")
        if pid and pid in ctx.ents:
            raise VerbError(409, f"{key} is already the page of project {pid}: a page belongs to one project")
        if not pid:
            while True:
                pid = "prj_" + secrets.token_hex(4)
                if pid not in ctx.d["ids"] and pid not in ctx.ents:
                    break
        row = base
        mark = dict(ctx.d["marks"].get(pid) or {})
        if scope:
            mark["scope"] = scope
        ent = derive_entry(pid, key, row, ctx.raw, mark, ctx.now, by=by or "stackshot", how="adopted")
        ent["made"]["revision"] = rev
        if name:
            ent["name"] = name
        elif not ent.get("name"):
            ent["name"] = prj.display_name_for(key, ent["scope"])
        why = _name_taken(ctx, ent["name"], pid, own=key)
        if why:
            raise VerbError(409, f"{why}: a name belongs to one project; give the project another with --name (the page's display-name: line follows it)")
        if ent["status"] != "archived":
            fold_pending(ent, ctx.d["pending_agents"].get(pid) or {})
        ctx.d["pending_agents"].pop(pid, None)
        ctx.d["ids"][pid] = key
        ctx.ents[pid] = ent
        if not dry:
            m = ctx.d["marks"].setdefault(pid, {})
            m.update({"on_purpose": ctx.now, "at": ctx.now, "by": by or "stackshot", **({"scope": scope} if scope else {})})
        return {"pid": pid}

    out, ents, changed = txn(work, by=by, now=now, dry=dry)
    return _finish(out["pid"], ents, changed, dry, io, extra={"adopted": True, "revision": rev}, by=by)


def rename(project: str, new_name: str, *, by: str = "", io: Any = None, now: str | None = None, dry: bool = False, pages: dict | None = None) -> dict:
    """Change the project's name: the id stays, the old name is appended to `former_names`, and the pending agents registered under the old name are dropped. The page's `display-name:` follows
    (mirror). → {project, key, changed, entry, mirror, old, new, dropped}."""
    new_name = " ".join(str(new_name or "").split())
    if not NAME_RE.fullmatch(new_name):
        raise VerbError(400, "name = letters, digits, . _ - (at most 64), starting with a letter or digit")

    def work(ctx: Ctx) -> dict:
        pid = ctx.pid_of(project)
        if not pid:
            raise VerbError(404, f"no project {project!r}: an id (prj_<8 hex>), a page key or a name")
        e = ctx.entry(pid)
        old = str(e.get("name") or "")
        if old == new_name:
            return {"pid": pid, "old": old, "dropped": []}
        why = _name_taken(ctx, new_name, pid)
        if why:
            raise VerbError(409, f"{why}: a name belongs to one project")
        fn = [x for x in e.get("former_names") or [] if x != new_name]
        if old and old not in fn:
            fn.append(old)
        e["name"] = new_name; e["former_names"] = fn
        dropped = []
        pend = ctx.d["pending_agents"].get(pid) or {}
        for n in [n for n in pend if old and str(n).casefold().startswith(old.casefold() + "-")]:
            del pend[n]; dropped.append(n)
        return {"pid": pid, "old": old, "dropped": dropped}

    pages = pages if pages is not None else preread(project, io)
    out, ents, changed = txn(work, by=by, now=now, dry=dry, pages=pages)
    old = out["old"]
    return _finish(out["pid"], ents, changed, dry, io, warn=out.get("warning", ""), extra={"old": old, "new": new_name, "dropped": out["dropped"]}, by=by,
                   timeline=f"renamed from {old} to {new_name}" if changed and old else "", tag="rename")


def archive(project: str, *, by: str = "", how: str = "made", why: str = "", io: Any = None, now: str | None = None, dry: bool = False, today: str | None = None, pages: dict | None = None) -> dict:
    """Set the project's status to archived with `retired` = who (`by`), when and how (`how` is how the record entry came to say it: "made" by a verb, "migrated", "adopted"; `why` is the
    reason in words). The page's `status:` follows (mirror), with a timeline line when the page was changed. An archived project stays archived: said again, it changes nothing. → {project, key, changed, ...}."""
    if how not in pr.HOWS:
        raise VerbError(400, f"how = {' | '.join(pr.HOWS)}")

    def work(ctx: Ctx) -> dict:
        ctx.refuse_sub_key(project)
        pid = ctx.pid_of(project)
        if not pid:
            raise VerbError(404, f"no project {project!r}: an id (prj_<8 hex>), a page key or a name")
        e = ctx.entry(pid)
        if e.get("status") == "archived":
            return {"pid": pid, "already": True}
        e["status"] = "archived"
        e["retired"] = {"at": ctx.now, "by": by or "stackshot", "how": how, **({"why": why} if why else {})}
        return {"pid": pid, "already": False}

    pages = pages if pages is not None else preread(project, io)
    out, ents, changed = txn(work, by=by, now=now, dry=dry, pages=pages)
    return _finish(out["pid"], ents, changed, dry, io, warn=out.get("warning", ""), extra={"already": out["already"]}, by=by,
                   timeline=("archived" + (f"; {why}" if why else "")) if not out["already"] else "", tag="archive")


def reopen(project: str, *, by: str = "", io: Any = None, now: str | None = None, dry: bool = False, pages: dict | None = None) -> dict:
    """The reverse of archive: status active, `retired` removed, the page's `status:` follows. Said of an active project it changes nothing."""
    def work(ctx: Ctx) -> dict:
        ctx.refuse_sub_key(project)
        pid = ctx.pid_of(project)
        if not pid:
            raise VerbError(404, f"no project {project!r}: an id (prj_<8 hex>), a page key or a name")
        e = ctx.entry(pid)
        if e.get("status") != "archived":
            return {"pid": pid}
        e["status"] = "active"; e.pop("retired", None)
        return {"pid": pid}

    pages = pages if pages is not None else preread(project, io)
    out, ents, changed = txn(work, by=by, now=now, dry=dry, pages=pages)
    return _finish(out["pid"], ents, changed, dry, io, warn=out.get("warning", ""), by=by, timeline="reopened" if changed else "", tag="reopen")


# ---- the agents map
def _find(agents: dict, name: str) -> str | None:
    return next((n for n in agents if n.casefold() == name.casefold()), None)


def _former_agent(e: dict, name: str, add: bool) -> None:
    """Note on the entry that `name` was taken off its agents map (`add`) or is listed again (not `add`); the last 50 are kept."""
    fa = [x for x in e.get("former_agents") or [] if x.casefold() != name.casefold()]
    if add:
        fa.append(name)
    if fa:
        e["former_agents"] = fa[-50:]
    else:
        e.pop("former_agents", None)


def agent_add(project: str, name: str, front: bool, mandate: str, *, by: str = "", io: Any = None, now: str | None = None, dry: bool = False, mirror_now: bool = True, pages: dict | None = None) -> dict:
    """List an agent on the project's agents map with its mandate line (`front` False = a background agent), at the end of the map. The record first, then the page's `agents:` block (mirror): there
    is no state in which the page owes a line. A name already listed with the same front flag and mandate changes nothing; with another, it is a 409. A pending entry of the same name is dropped.
    → {project, key, changed, entry, mirror, name, front, mandate}."""
    mandate = " ".join(str(mandate or "").split())

    def work(ctx: Ctx) -> dict:
        pid = ctx.pid_of(project)
        if not pid:
            raise VerbError(404, f"no project {project!r}: an id (prj_<8 hex>), a page key or a name")
        e = ctx.entry(pid)
        ag = copy.deepcopy(ctx.agents(pid))
        have = _find(ag, name)
        if have is not None:
            cur = ag[have]
            if bool(cur.get("front")) == bool(front) and _norm_m(cur.get("mandate_line", "")) == _norm_m(mandate):
                e["agents"] = ag
                return {"pid": pid, "name": have}
            raise VerbError(409, f"{have} is already listed on the project as {'front' if cur.get('front') else 'background'}: {str(cur.get('mandate_line', ''))[:120]!r}; "
                                 "to change its mandate line use agent_mandate; to change its side, retire it or rename it, then list it again")
        ag[name] = {"front": bool(front), "mandate_line": mandate, **({"by": by} if by else {}), "at": ctx.now}
        e["agents"] = ag
        _former_agent(e, name, False)
        pend = ctx.d["pending_agents"].get(pid) or {}
        for n in [n for n in pend if str(n).casefold() == name.casefold()]:
            del pend[n]
        return {"pid": pid, "name": name}

    pages = pages if pages is not None else preread(project, io)
    out, ents, changed = txn(work, by=by, now=now, dry=dry, pages=pages)
    return _finish(out["pid"], ents, changed, dry, io, warn=out.get("warning", ""), extra={"name": out["name"], "front": bool(front), "mandate": mandate}, by=by, mirror_now=mirror_now)


def agent_mandate(project: str, name: str, mandate: str, *, by: str = "", io: Any = None, now: str | None = None, dry: bool = False, mirror_now: bool = True, pages: dict | None = None) -> dict:
    """Change the mandate line of an agent already on the project's agents map: its side (front or background), its place in the map and who listed it stay as they are. The record first, then the
    page's `agents:` block (mirror), so the page cannot undo the change: a hand edit of the page is not read and the next mirror write restores the record's line. The same line again changes nothing.
    Refused: an empty line (400: the agent would have no mandate), a line with a backslash (400), a name that is not listed (404: list it with agent_add first; a pending entry only is not listed). → {project, key, changed, entry,
    mirror, name, front, mandate, previous}."""
    mandate = " ".join(str(mandate or "").split())
    if "\\" in mandate:
        raise VerbError(400, "a mandate line cannot contain a backslash; write it without (the page's agents block could not be read back with one)")
    if not mandate:
        raise VerbError(400, "the mandate line is empty: give the agent's new line in words (what it does, in one line); to take the agent off the map use agent_retire")

    def work(ctx: Ctx) -> dict:
        pid = ctx.pid_of(project)
        if not pid:
            raise VerbError(404, f"no project {project!r}: an id (prj_<8 hex>), a page key or a name")
        e = ctx.entry(pid)
        ag = copy.deepcopy(ctx.agents(pid))
        have = _find(ag, name)
        if have is None:
            raise VerbError(404, f"{name} is not listed on {pr.page_key(e) or pid}: list it first with agent_add (this verb changes the line of an agent that is on the map)")
        previous = ag[have].get("mandate_line", "")
        ag[have] = {**ag[have], "mandate_line": mandate}
        e["agents"] = ag
        return {"pid": pid, "name": have, "front": bool(ag[have].get("front")), "previous": previous}

    pages = pages if pages is not None else preread(project, io)
    out, ents, changed = txn(work, by=by, now=now, dry=dry, pages=pages)
    return _finish(out["pid"], ents, changed, dry, io, warn=out.get("warning", ""), extra={"name": out["name"], "front": out["front"], "mandate": mandate, "previous": out["previous"]}, by=by, mirror_now=mirror_now)


def agent_retire(project: str, name: str, *, by: str = "", io: Any = None, now: str | None = None, dry: bool = False, pages: dict | None = None) -> dict:
    """Take an agent off the project's agents map (and any pending entry of the name). The page's block follows (mirror), with a timeline line when the page changed. The map stays present when it
    is emptied (the project was staffed once). A name that is not listed changes nothing. → {project, key, changed, entry, mirror, result, name, front, left}, with `result` "line removed", "dropped" (it was only a pending entry) or "not listed"."""
    def work(ctx: Ctx) -> dict:
        pid = ctx.pid_of(project)
        if not pid:
            raise VerbError(404, f"no project {project!r}: an id (prj_<8 hex>), a page key or a name")
        e = ctx.entry(pid)
        ag = copy.deepcopy(ctx.agents(pid))
        have = _find(ag, name)
        pend = ctx.d["pending_agents"].get(pid) or {}
        gone = [(n, bool(pend[n].get("front", True))) for n in pend if str(n).casefold() == name.casefold()]
        for n, _f in gone:
            del pend[n]
        if have is None:
            if gone:
                return {"pid": pid, "result": "dropped", "name": gone[0][0], "front": gone[0][1], "left": len(ag)}
            return {"pid": pid, "result": "not listed", "name": name, "front": True, "left": len(ag)}
        front = bool(ag[have].get("front"))
        del ag[have]
        e["agents"] = ag
        _former_agent(e, have, True)
        return {"pid": pid, "result": "line removed", "name": have, "front": front, "left": len(ag)}

    pages = pages if pages is not None else preread(project, io)
    out, ents, changed = txn(work, by=by, now=now, dry=dry, pages=pages)
    removed = out["result"] == "line removed"
    return _finish(out["pid"], ents, changed, dry, io, warn=out.get("warning", ""), extra={k: out[k] for k in ("result", "name", "front", "left")}, by=by, drop=(out["name"],),
                   timeline=f"{out['name']} retired; its line removed from the agents map" if removed else "", tag=f"retire-{out['name']}")


def agent_rename(project: str, old: str, new: str, *, by: str = "", io: Any = None, now: str | None = None, dry: bool = False, pages: dict | None = None) -> dict:
    """Rename an agent's entry in place: the same place in the map, front or background, the same mandate. Refused (404) when `old` is not listed and `new` is not either; `old` gone and `new`
    listed is "already renamed"; both listed is a 409. → {project, key, changed, entry, mirror, result, old, new, front, mandate}."""
    def work(ctx: Ctx) -> dict:
        pid = ctx.pid_of(project)
        if not pid:
            raise VerbError(404, f"no project {project!r}: an id (prj_<8 hex>), a page key or a name")
        e = ctx.entry(pid)
        ag = ctx.agents(pid)
        o, n = _find(ag, old), _find(ag, new)
        if o is None and n is not None:
            return {"pid": pid, "result": "already renamed", "old": old, "new": n, "front": bool(ag[n].get("front")), "mandate": ag[n].get("mandate_line", "")}
        if o is None:
            raise VerbError(404, f"{old} is not listed on {pr.page_key(e) or pid}")
        if n is not None:
            raise VerbError(409, f"{new} is already listed on {pr.page_key(e) or pid}")
        e["agents"] = {(new if k == o else k): v for k, v in ag.items()}
        _former_agent(e, o, True); _former_agent(e, new, False)
        pend = ctx.d["pending_agents"].get(pid) or {}
        for x in [x for x in pend if str(x).casefold() == o.casefold()]:
            del pend[x]
        return {"pid": pid, "result": "renamed", "old": o, "new": new, "front": bool(ag[o].get("front")), "mandate": ag[o].get("mandate_line", "")}

    pages = pages if pages is not None else preread(project, io)
    out, ents, changed = txn(work, by=by, now=now, dry=dry, pages=pages)
    return _finish(out["pid"], ents, changed, dry, io, warn=out.get("warning", ""), extra={k: out[k] for k in ("result", "old", "new", "front", "mandate")}, by=by, drop=(out["old"],))


# ---- the page moves
def default_runner(args: list[str]) -> tuple[int, str]:
    """rename_page.py, run as the command it is (the gbrain CLI is on the server box) → (exit code, its output)."""
    r = subprocess.run([sys.executable, _paths.program("projects", "rename_page"), *args], capture_output=True, text=True, timeout=1800)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _stubbed(out: str, old: str) -> list[str]:
    """The pages rename_page.py's output says are stubbed or were redirects already ("stub OLD → NEW" and "skip OLD: already a redirect" lines), limited to `old` and the pages under it."""
    got = [a or b for a, b in re.findall(r"(?m)^(?:stub (\S+) \S+ \S+|skip (\S+): already a redirect)\s*$", out)]
    return [x for x in got if x == old or x.startswith(old + "/")]


def _stub_done(out: str, old: str, fulls: list) -> bool:
    """True when a stub run that exited non-zero had done the whole stub: the top page is stubbed, every line that says FAIL is about the project id move (rename_page.py's last step, which the
    record here repairs), and every page the earlier plan or copy step listed is stubbed or was a redirect already."""
    done = set(_stubbed(out, old))
    if old not in done:
        return False
    if any(ln.strip().startswith("FAIL") and not ln.strip().startswith("FAIL project id of") for ln in out.splitlines()):
        return False
    listed = {m.group(1) for ph, o in fulls if ph in ("plan", "copy") for m in re.finditer(r"(?m)^(?:plan|copy) (\S+) \S+ \S+", o)}
    return listed <= done


def move_page(project: str, new_key: str, *, by: str = "", phases: tuple = ("copy", "stub"), why: str = "", parent: str = "", no_agents_ok: bool = False,
              runner: Callable[[list[str]], tuple[int, str]] | None = None, io: Any = None, now: str | None = None, dry: bool = False, pages: dict | None = None) -> dict:
    """Move the project's page to `new_key`: runs rename_page.py for each of `phases` (plan | copy | stub; the default is copy then stub, and a stub refuses while an open item or an anchor still
    names the old key: move those, then run `phases=("stub",)`; an item that stores the project's id (metadata.project_id) is read at the new key at once, and needs no move), and when the page has moved (the stub ran) writes the record: the pointer is the new key and the old key is appended to
    `former_keys`. rename_page.py's own stub step moves the id's key and the entry's pointer in the same way; this step makes the record right whatever that step did (it does nothing twice). The page
    mirror runs at the new key. A dry run runs only `plan`. → {project, key, changed, moved, steps, mirror}; a failed step is a VerbError(502) naming the step and its output.
    A page of a brain marked `shared` (the old key or the new one) is not moved: 403, with the refusal's line (brains.shared_refusal), before any step runs, a dry run included.
    Only a project's own page moves: `project` may not be a sub-page's key, and `new_key` may not be below another page or a sub-page's (400). A stub that was written but whose id move failed
    (rename_page.py exits 1 after printing "stub OLD → NEW") is not an error: the record is made right here and the answer carries a `warning`."""
    new_key = _norm_key(new_key)
    top, _, slug = new_key.partition("/")
    if top not in _cfg.page_dirs() or not slug or "/" in slug:
        raise VerbError(400, f"new page key = {' or '.join(d + '/<slug>' for d in _cfg.page_dirs())}, one level: a project's page is never below another page")
    bad = [ph for ph in phases if ph not in ("plan", "copy", "stub")]
    if bad or not phases:
        raise VerbError(400, "phases = plan | copy | stub")
    runner = runner or default_runner

    def read(ctx: Ctx) -> dict:
        ctx.refuse_sub_key(project)             # a sub-page's key would move its parent's page: decided here, in the transaction, before any entry exists
        pid = ctx.pid_of(project)
        if not pid:
            raise VerbError(404, f"no project {project!r}: an id (prj_<8 hex>), a page key or a name")
        up = ctx.owner(new_key)
        if up:
            raise VerbError(400, f"{new_key} is a sub-page of {up}: a project's page is never a sub-page")
        e = ctx.entry(pid)                      # the entry exists before the page moves, so the move has a record to change
        old = pr.page_key(e)
        if not old:
            raise VerbError(400, f"{pid} has no page of this instance's page store to move")
        other = ctx.pid_of(new_key)
        if other and other != pid and (other in ctx.ents and pr.page_key(ctx.ents[other]) == new_key):
            raise VerbError(409, f"{new_key} is already the page of project {other}")
        from stackshot.projects import brains as _brains
        for k in (old, new_key):                # rename_page.py puts and stubs through the notes CLI: a shared brain's page is moved by its own people, never by a project verb
            why = _brains.shared_refusal(k)
            if why:
                raise VerbError(403, f"the page {k} was not moved: {why}")
        return {"pid": pid, "old": old}

    pages = pages if pages is not None else preread(project, io)
    st, _e, _c = txn(read, by=by, now=now, dry=True, pages=pages) if dry else txn(read, by=by, now=now, pages=pages)
    pid, old = st["pid"], st["old"]
    if old == new_key:
        raise VerbError(400, f"{pid}'s page is {new_key} already")
    steps = []; fulls = []; warning = ""
    for ph in (("plan",) if dry else phases):
        args = [ph, f"{old}={new_key}"] + (["--why", why] if why else []) + (["--parent", parent] if parent and ph != "stub" else []) + (["--no-agents-ok"] if no_agents_ok else [])
        rc, out = runner(args)
        steps.append({"phase": ph, "rc": rc, "output": out[-2000:]}); fulls.append((ph, out))
        if rc != 0:
            last = out.strip().splitlines()[-1][:300] if out.strip() else ""
            if ph == "stub" and _stub_done(out, old, fulls):
                warning = (f"the page {old} was stubbed (it now points to {new_key}), but rename_page.py exited {rc} after that" + (f": {last}" if last else "") +
                           "; the project's record is made right by this step, and the stub step is not to be run again (the page has changed since its copy)")
                break
            top_done = old in _stubbed(out, old)
            hint = {"stub": (f"; the page {old} was stubbed, but not every page under it (see the output): run the stub step again, it skips the stubbed ones: `project move-page {project} {new_key} --phase stub`"
                             if top_done else f"; the page {old} was not stubbed. Once what the message names is fixed, run the stub step again: `project move-page {project} {new_key} --phase stub`"),
                    "copy": "; nothing was changed, so the same call can be said again"}.get(ph, "")
            raise VerbError(502, f"rename_page.py {ph} failed (exit {rc}); the record was not changed by it" + hint + (": " + last if last else ""))
    if dry or "stub" not in phases:
        return {"project": pid, "key": old, "changed": False, "dry": dry, "moved": False, "steps": steps, "mirror": {"state": "none", "key": "", "note": "the page has not moved yet"}}

    def fix(ctx: Ctx) -> dict:
        e = ctx.entry(pid)
        cur = pr.page_key(e)
        if cur != new_key:
            e["page"] = new_key
        fk = [k for k in e.get("former_keys") or [] if _norm_key(k) != new_key]
        if old not in fk:
            fk.append(old)
        e["former_keys"] = fk
        if ctx.d["ids"].get(pid) != new_key:
            ctx.d["ids"][pid] = new_key
        return {"pid": pid}

    _o, ents, changed = txn(fix, by=by, now=now)
    warning = "; ".join(w for w in (st.get("warning"), warning) if w)
    res = _finish(pid, ents, changed, False, io, by=by, extra={"moved": True, "steps": steps, **({"warning": warning} if warning else {})})
    return res


# ----------------------------------------------------------------------------- restore from the store's history
def restore(project: str = "", *, rev: str = "", before: str = "", apply: bool = False, by: str = "", run_dir: Any = None, now: str | None = None) -> dict:
    """The record (or `project`'s entry, its id rows and its marks, merged into the current record) put back from a past revision `rev` of the store's repository, or the last one before the
    date `before`. A dry run unless `apply`: the answer says what would change and writes nothing. With `apply` the undo file is written first, then the record, through the save path and the lock
    every record writer uses. VerbError (404 no such revision or project, 409 a collision, a record being written or a store outside a repository, 422 a record that does not read), nothing written. See project_restore.py."""
    from stackshot.projects import project_restore as rs
    return rs.restore(project, rev=rev, before=before, apply=apply, by=by, run_dir=run_dir, now=now)


def restore_list(limit: int = 20, *, rev: str = "") -> dict:
    """The last `limit` revisions of the record file in the store's history, newest first, with the date and what changed in the project count."""
    from stackshot.projects import project_restore as rs
    return rs.restore_list(limit, rev=rev)


def restore_undo(path: Any, *, apply: bool = False) -> dict:
    """Take back a restore through the undo file it kept (a dry run unless `apply`)."""
    from stackshot.projects import project_restore as rs
    return rs.restore_undo(path, apply=apply)


# ----------------------------------------------------------------------------- what the server's gates read
def pageless_rec(x: Any) -> dict | None:
    """The record shape `projects.ref` gives (id, key, keeper, agents, listed, retired, ...) for a project the record says has no page, else None. `key` is "" and `pageless` is true."""
    v = pr.pageless(x)
    if not v:
        return None
    pre = [v["name"]] if v["name"] else []
    ag = {n: {"front": bool(a.get("front")), "role": prj.role_of(n, pre), "mandate_line": str(a.get("mandate_line") or "")} for n, a in v["agents"].items()}
    return {"id": v["id"], "key": "", "keeper": v["name"], "agents": ag, "title": v["title"] or v["name"], "type": v["type"], "hub": v["hub"], "scope": v["scope"] or prj.default_scope(),
            "listed": not v["archived"], "listed_by": "on_purpose", "sub_page": False, "items_30d": 0, "status": v["status"], "retired": v["archived"], "pageless": True}


def pid_of(project: Any) -> str:
    """The id of the project `project` names, the way the verbs find it (an id, a page key, a bare slug, a former key, the project's name or a former name; a sub-page key names the top-level
    project that owns it): "" when it names none; the id of a sub-page is a VerbError 400. Reads the record under its lock and writes nothing."""
    try:
        return txn(lambda c: c.pid_of(project), dry=True)[0]
    except ValueError:
        return ""


def one(project: Any) -> dict | None:
    """The record shape of the project `project` (an id, a page key, a slug) names: a project with a page by projects.refs, one with none by pageless_rec; None when it names neither."""
    try:
        recs = prj.refs(project, prj.with_made(prj.registry()))
    except ValueError:
        recs = []
    if recs:
        return recs[0]
    return pageless_rec(project)


# ----------------------------------------------------------------------------- the New session form's checks
# What the form's calls (`post project`, `post project-list`, `post project-agent` and its mandate, rename and retire, `get projects`; service/projects.py) decide before and after
# they read or write: the shape of a body, who may ask, the name rules, and the words of each refusal and each answer. Nothing here reads the record, the clock, a session or
# a page: what a rule needs comes in as an argument, and a refusal is `(status, body)`, or None when the call goes on. The reads, the lock and the writes are service/projects.py's.
AGENT_ROLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}")
MANDATE_CONTROL = re.compile("[\\u0000-\\u001f\\u007f-\\u009f\\ufffe\\uffff]")      # control characters: a YAML reader refuses or misreads them on the page
FIRST_AGENT_WINDOW = 3600       # seconds after a make or a re-list in which the label that did it may register the project's first agent
RENAME_NOT_FORM = ("refused: only the web form may rename an agent's entry on a page: `sender` must be a label in [project_agent] form_senders "
                   "and the token must be a machine in form_machines")
RETIRE_NOT_FORM = ("refused: only the web form may retire an agent: `sender` must be a label in [project_agent] form_senders "
                   "and the token must be a machine in form_machines")
_NAME_TEXT = "name = the session's name: letters, digits, . _ - (at most 64), starting with a letter or digit"
_MANDATE_TEXT = "mandate = one line of at most 600 characters, with no control characters"
_SENDER_TEXT = "sender = the caller's own label: one line of at most 80 characters"
_SESSION_ID_TEXT = ("refused: sender {sender!r} is a name, and a name proves nothing. Send the asking session's id: its transcript id "
                    "($CLAUDE_CODE_SESSION_ID, which Claude Code sets in every Bash command) or a cloud session's cse_ id")
_Refusal = tuple[int, dict[str, Any]]


def label_bad(s: str) -> bool:
    """A sender label that is not one line of at most 80 characters."""
    return len(s) > 80 or any(ord(c) < 32 or ord(c) == 127 for c in s)


def section_names(sec: Any, key: str, default: list[str]) -> list[str]:
    """`[project_agent] <key>` as a list of strings, from the section as the config holds it: the section or the key absent → `default`; a bare string counts as one
    name; a section or value of another type reads as an empty list (no form call at all, never a wider rule than the file says)."""
    if sec is None:
        return list(default)
    if not isinstance(sec, dict):
        return []
    v = sec.get(key)
    if v is None:
        return list(default)
    if isinstance(v, str):
        v = [v]
    return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []


def form_call(machine: str, sender: str, senders: list[str], machines: list[str]) -> bool:
    """Is this call the New session form's? Only when the `sender` label is in form_senders AND the machine its token proves (`machine`, never the body) is in
    form_machines: a label alone is not enough, since any token holder can type it."""
    return bool(machine) and bool(sender) and sender in senders and machine in machines


def unwritable(e: Exception, done: str = "changed") -> str:
    """The text of a 503 when the project record cannot be read or written: `done` is what was not done ("changed", "made")."""
    return f"the project record cannot be read or written right now, nothing was {done}: {e}"


def pick_project(project: str, recs: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, _Refusal | None]:
    """The one record a project reference names → (record, None), or (None, the refusal): unknown, or ambiguous between two pages."""
    if not recs:
        return None, (404, {"error": f"no project {project!r}: an id (prj_<8 hex>), a page key or a bare slug of a page in the registry"})
    if len(recs) > 1:
        return None, (400, {"error": f"{project!r} is ambiguous: it names {' and '.join(r['key'] for r in recs)}; write the full key or the id"})
    return recs[0], None


def hub_refusal(rec: dict[str, Any], entry: dict[str, Any], how: str) -> _Refusal | None:
    """The agents map lives on a hub page: a sub-page, or a page with a `hub:` line, is refused with the page to use; `how` says what to do there."""
    key = rec["key"]
    top = "/".join(key.split("/")[:2]); hub = str(entry.get("hub") or "")
    if key != top or hub:
        return 400, {"error": f"{key} is not a hub page: the agents map is kept on {hub or top}; {how}"}
    return None


def project_prefixes(rec: dict[str, Any], entry: dict[str, Any], reg: dict[str, Any]) -> list[str]:
    """The names an agent of the project may start with: the keeper's name for a project with no page, else the page's name, else the page's slug (an agent is always <project>-<role>)."""
    key = rec["key"]
    return [rec["keeper"]] if rec.get("pageless") else (prj._name_prefixes(key, entry, reg) or [key.split("/")[-1]])


def prefix_refusal(name: str, prefixes: list[str], where: str) -> _Refusal | None:
    """A name that does not start with the project's name."""
    if not any(name.startswith(p + "-") and len(name) > len(p) + 1 for p in prefixes):
        return 400, {"error": f"{name!r} does not start with the project's name: an agent of {where} is called {prefixes[0]}-<role>"}
    return None


def name_clash(name: str, key: str, pid: str, prefixes: list[str], reg: dict[str, Any], entries: dict[str, Any], pending: dict[str, Any], key_of: Callable[[str], str]) -> str:
    """A name belongs to one project (every path, the form's too): the 409 text when another project's page map or pending list holds `name`, or when it
    starts with the longer name prefix of another project (team-alpha-docs-main under projects/alpha belongs to a project whose name is team-alpha-docs);
    "" when the name is free for the project `key` (id `pid`). `entries` is the project record's entries by id, `pending` the pending agents by id, `key_of` an id's page key."""
    fold = name.casefold()
    own_pre = {x.casefold() for x in prefixes}
    longest = max((len(x) for x in prefixes if fold.startswith(x.casefold() + "-")), default=0)
    for k2, e2 in sorted(reg.items()):
        if k2 == key or not isinstance(e2, dict): continue
        if any(str(n).casefold() == fold for n in (e2.get("agents") or {})):
            return f"{name} is already an agent of {k2}: a name belongs to one project"
        for q in prj._name_prefixes(k2, e2, reg):
            if q.casefold() not in own_pre and len(q) > longest and fold.startswith(q.casefold() + "-"):
                return f"{name} starts with {q}-, the name of {k2}: an agent of {key} cannot take it; a name belongs to one project"
    for pid2, ent in entries.items():          # the record's lists: a project whose page is gone, or never was, still holds its agents
        if pid2 != pid and any(str(n).casefold() == fold for n in (ent.get("agents") or {})):
            return f"{name} is already an agent of {key_of(pid2) or pid2}: a name belongs to one project"
    for pid2, ag2 in pending.items():
        if pid2 != pid and any(str(n).casefold() == fold for n in ag2):
            return f"{name} is already registered for {key_of(pid2) or pid2}: a name belongs to one project"
    return ""


def agents_block_tail(m: dict[str, Any]) -> str:
    """What an answer adds when the page's agents block was not written (the record is right already): "" when the mirror is in a state that needs no word."""
    return ("" if m["state"] in ("none", "unchanged", "written", "would-write", "retired") else
            f" The page's agents block was not updated ({m['note']}); the record is right and the next change to this project writes the page again.")


# post project-agent ---------------------------------------------------------
def agent_fields(body: dict[str, Any]) -> tuple[tuple[str, str, str, str, str, bool] | None, _Refusal | None]:
    """The body of `post project-agent` → ((project, name, role, mandate, sender, front), None), or (None, the 400)."""
    project, name, role, mandate, sender = (str(body.get(k) or "").strip() for k in ("project", "name", "role", "mandate", "sender"))
    front = body.get("front")
    if not (project and name and role and mandate and sender) or not isinstance(front, bool):
        return None, (400, {"error": "project, name, role, mandate and sender are required, and front is true (a front agent) or false (a background agent)"})
    if not NAME_RE.fullmatch(name):
        return None, (400, {"error": _NAME_TEXT})
    if not AGENT_ROLE.fullmatch(role):
        return None, (400, {"error": "role = the name's suffix after the project's name (main, engineer, sessions): letters, digits, . _ - (at most 32)"})
    if "\n" in mandate or "\r" in mandate or len(mandate) > 600 or MANDATE_CONTROL.search(mandate):
        return None, (400, {"error": _MANDATE_TEXT})
    return (project, name, role, mandate, sender, front), None


def mark_age(mark: dict[str, Any], now: dt.datetime) -> float:
    """Seconds since the project's mark was made or renewed (`at`, else `on_purpose`) as of `now` (aware, UTC); infinite when the mark has no readable time."""
    try:
        return (now - dt.datetime.strptime(str(mark.get("at") or mark.get("on_purpose") or ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)).total_seconds()
    except ValueError:
        return float("inf")


def label_paths(rec: dict[str, Any], mark: dict[str, Any], owed: dict[str, Any], listed_by: dict[str, Any], keeper_live: bool, sender: str, age: float) -> tuple[bool, bool]:
    """The two paths of a label as sender (see service/projects.py `_project_agent_locked`) → (first, more). `owed` is the project's pending agents, `listed_by` the agents the record
    lists with who listed each, `keeper_live` whether the fleet holds a present session of the keeper's name."""
    on_page = [n for n, a in rec["agents"].items() if not a.get("page_owed")]
    first = not rec["agents"] and not keeper_live and 0 <= age <= FIRST_AGENT_WINDOW and bool(mark.get("by")) and mark.get("by") == sender
    more = not first and bool(sender) and (bool(listed_by) and all(a.get("by") == sender for a in listed_by.values()) or (not on_page and bool(owed) and all(a.get("by") == sender for a in owed.values())))
    return first, more


def front_caller_refusal(sender: str, is_id: bool, names_get: Callable[[str, str], str], rec: dict[str, Any], named: str, action: str) -> _Refusal | None:
    """A caller that is a session, not a label: `sender` must be a session id that resolves (`names_get`, the fleet's heartbeat names) to the keeper or a listed front agent of the project (`named` is
    how an answer names it); `action` is what only they may do ("lists a new agent")."""
    if not is_id:
        return 403, {"error": _SESSION_ID_TEXT.format(sender=sender)}
    sname = names_get(sender, "")
    listed_front = sorted(n for n, a in rec["agents"].items() if a["front"] and not a.get("page_owed"))
    allowed = {rec["keeper"], *listed_front}
    allowed.discard("")
    if not sname and sender not in allowed:
        return 403, {"error": f"refused: {sender!r} is not a session in the fleet's heartbeat, so it names nobody; run this from the keeper's or a front agent's own session"}
    if not ({sender, sname} & allowed):
        return 403, {"error": f"refused: session {sname or sender!r} is neither the keeper ({rec['keeper'] or 'none'}) nor a front agent of {named} "
                              f"({', '.join(listed_front) or 'none'}); one of them {action}"}
    return None


def agent_caller_refusal(rec: dict[str, Any], key: str, form: bool, first: bool, more: bool, sender: str, is_id: bool, names_get: Callable[[str, str], str]) -> _Refusal | None:
    """Who may register an agent: a label on the first-agent or further-agents path, or the New session form (`form`), or the keeper or a front agent as a session id."""
    if (first or more or form) and rec["retired"]:        # a label is the form's word: a retired project takes no agent from it (the keeper's and a front agent's session ids still may)
        return 403, {"error": f"{key} is retired (page status: {rec['status']}): change the page's status first"}
    if form and not rec["listed"]:
        return 403, {"error": f"refused: {key} is hidden, not listed. List it again first with `client.py post project-list --key {key}`, then add the agent"}
    if first or more or form:
        if label_bad(sender):
            return 400, {"error": _SENDER_TEXT}
        return None
    return front_caller_refusal(sender, is_id, names_get, rec, key, "lists a new agent")


def listed_answer(rec: dict[str, Any], key: str, where: str, name: str, front: bool, mandate: str) -> tuple[str, _Refusal | None]:
    """A name the page already lists (case-folded) → (the name as listed, the answer): the same side and mandate changes nothing (200), another is a 409; (name, None) when it is not listed."""
    fold = name.casefold()
    listed_name = next((n for n, a in rec["agents"].items() if n.casefold() == fold and not a.get("page_owed")), None)     # names compare case-folded
    if listed_name is None:
        return name, None
    name = str(listed_name)
    cur = rec["agents"][name]
    if (cur["front"], cur["mandate_line"]) == (front, mandate):          # the role is read from the name: the one asked for is no part of "the same"
        return name, (200, {"project": rec["id"], "key": key, "agent": {name: cur}, "page_owed": False, "page_yaml": "", "note": f"{name} is already listed on {where}: nothing changed"})
    return name, (409, {"error": f"{name} is already listed on {where} as {'front' if cur['front'] else 'background'} ({cur['role']}): {cur['mandate_line'][:120]!r}; "
                                 "to change its mandate line use `client.py post project-agent-mandate`; to change its side, retire it, or rename it, then list it again"})


def pending_name(pending: dict[str, Any], name: str) -> str:
    """A pending entry under another spelling is the same agent: the name as the pending list spells it, else `name`."""
    fold = name.casefold()
    return next((n for n in pending if str(n).casefold() == fold), name)


def pending_refusal(pend: dict[str, Any], sender: str, name: str, where: str, front: bool, role: str, mandate: str) -> _Refusal | None:
    """A pending entry another session registered, as something else: only that session changes it."""
    if pend and pend.get("by") != sender and (pend.get("front"), pend.get("role"), pend.get("mandate_line")) != (front, role, mandate):
        return 409, {"error": f"{name} was already registered for {where} by another session ({pend.get('by') or 'unknown'}) as "
                              f"{'front' if pend.get('front') else 'background'} ({pend.get('role')}): {str(pend.get('mandate_line'))[:120]!r}; "
                              "only that session changes it"}
    return None


def agent_added(rec: dict[str, Any], key: str, where: str, res: dict[str, Any], new: dict[str, Any]) -> _Refusal:
    """The 200 of a listed agent; `_mirror` is the project's id when its page is to get the agents line (the caller writes it after the lock and pops the key)."""
    has_page = bool(res["key"])
    return 200, {"project": rec["id"], "key": key, "agent": {res["name"]: new}, "page_owed": False, "page_yaml": "", "_mirror": rec["id"] if has_page else "",
                 "note": f"Listed {res['name']} on {where} in the project record" + (f"; its page {key} gets the agents line from the record." if has_page else " (the project has no page).")
                 + (f" Note: {res['warning']}." if res.get("warning") else "")}


def agent_mirror_tail(m: dict[str, Any]) -> str:
    """What the answer of `post project-agent` adds for a mirror that failed or has no page."""
    if m["state"] == "failed":
        return f" The page's agents block was not updated ({m['note']}); the record holds the agent, and the next change to this project writes the page again."
    if m["state"] == "no-page":
        return f" Its page {m['key']} is not in the page store, so no page was written."
    return ""


# post project-agent-mandate -------------------------------------------------
def mandate_fields(body: dict[str, Any]) -> tuple[tuple[str, str, str, str] | None, _Refusal | None]:
    """The body of `post project-agent-mandate` → ((project, name, mandate, sender), None), or (None, the 400)."""
    project, name, mandate, sender = (str(body.get(k) or "").strip() for k in ("project", "name", "mandate", "sender"))
    if not (project and name and sender):
        return None, (400, {"error": "project, name and sender are required: the project, the listed agent's name and the asking session's id; the new line goes in `mandate`"})
    if not NAME_RE.fullmatch(name):
        return None, (400, {"error": _NAME_TEXT})
    if not mandate:
        return None, (400, {"error": "mandate is empty: give the agent's new line (one line of at most 600 characters, what it does); to take the agent off the map use `post project-agent-retire`"})
    if "\n" in mandate or "\r" in mandate or len(mandate) > 600 or MANDATE_CONTROL.search(mandate):
        return None, (400, {"error": _MANDATE_TEXT})
    if "\\" in mandate:
        return None, (400, {"error": "a mandate line cannot contain a backslash; write it without (the page's agents block could not be read back with one)"})
    return (project, name, mandate, sender), None


def mandate_answer(rec: dict[str, Any], key: str, where: str, res: dict[str, Any], m: dict[str, Any], role: str) -> _Refusal:
    """The 200 of a changed (or unchanged) mandate line; `m` is the page mirror's state, `role` the agent's role read from its name."""
    tail = (f" The page's agents block was not updated ({m['note']}); the record holds the new line, and the next change to this project writes the page again." if m["state"] == "failed" else "")
    return 200, {"project": rec["id"], "key": key, "agent": {res["name"]: {"front": res["front"], "role": role, "mandate_line": res["mandate"]}}, "previous": res["previous"], "mirror": m,
                 "note": (f"{res['name']} on {where} already has this mandate line: nothing changed." if not res["changed"] and m["state"] in ("none", "unchanged") else
                          f"{res['name']} on {where} already had this mandate line in the project record; the page {key} was written from the record." if not res["changed"] and m["state"] == "written" else
                          f"{res['name']} on {where} already has this mandate line in the project record." if not res["changed"] else
                          f"Changed the mandate line of {res['name']} on {where} in the project record" + (f"; the page {key} gets it from the record." if key else " (the project has no page).")) + tail}


# post project-agent-rename and -retire -------------------------------------
def rename_fields(machine: str, body: dict[str, Any], is_form: Callable[[str, str], bool]) -> tuple[tuple[str, str, str, str] | None, _Refusal | None]:
    """The gate and the names of `post project-agent-rename` → ((project, old, new, sender), None), or (None, the refusal). `is_form` is the form-call test of the instance's config."""
    project, old, new = (str(body.get(k) or "").strip() for k in ("project", "old", "new"))
    sender = str(body.get("sender") or "").strip() or machine
    if not (project and old and new):
        return None, (400, {"error": "project, old and new are required: the project, the agent's name now and its new name"})
    if label_bad(sender):
        return None, (400, {"error": _SENDER_TEXT})
    if not is_form(machine, sender):
        return None, (403, {"error": RENAME_NOT_FORM})
    for nm in (old, new):
        if not NAME_RE.fullmatch(nm):
            return None, (400, {"error": "old and new = the session's name: letters, digits, . _ - (at most 64), starting with a letter or digit"})
    if old.casefold() == new.casefold():
        return None, (400, {"error": "old and new are the same name (names compare case-folded): nothing to rename"})
    return (project, old, new, sender), None


def rename_pending_refusal(pending: dict[str, Any], rec: dict[str, Any], where: str, old: str, new: str) -> _Refusal | None:
    """NEW is registered for the project as a pending agent whose page line is owed, and OLD is not listed: that entry is not this call's to change."""
    pend = next(((n, a) for n, a in pending.items() if str(n).casefold() == new.casefold()), None)
    if pend and not any(str(n).casefold() == old.casefold() for n in rec["agents"]):
        return 409, {"error": f"{new} is already registered for {where} as a pending agent (by {pend[1].get('by') or 'unknown'}), its page line still owed: nothing was changed; "
                              "that entry is not this call's to change"}
    return None


def rename_answer(rec: dict[str, Any], key: str, where: str, res: dict[str, Any], old: str, new: str, prefixes: list[str]) -> _Refusal:
    """The 200 of `post project-agent-rename` (renamed, or already renamed: a retry after a lost reply)."""
    m = res["mirror"]
    tail = agents_block_tail(m)
    if res["result"] == "already renamed":
        return 200, {"project": rec["id"], "key": key, "result": "already renamed", "old": old, "new": res["new"], "front": res["front"],
                     "role": prj.role_of(res["new"], prefixes), "mandate": res["mandate"], "mirror": m, "note": "already renamed"}
    return 200, {"project": rec["id"], "key": key, "result": "renamed", "old": res["old"], "new": new, "front": res["front"], "role": prj.role_of(new, prefixes), "mandate": res["mandate"], "mirror": m,
                 "note": f"Renamed {res['old']} to {new} on {where}: the entry in the project's agents map is renamed in place (same place in the map, same mandate)"
                         + (f", and the page {key} follows from the record." if key else " (the project has no page).") + tail}


def retire_fields(machine: str, body: dict[str, Any], is_form: Callable[[str, str], bool]) -> tuple[tuple[str, str, str] | None, _Refusal | None]:
    """The gate and the names of `post project-agent-retire` → ((project, name, sender), None), or (None, the refusal)."""
    project, name = (str(body.get(k) or "").strip() for k in ("project", "name"))
    sender = str(body.get("sender") or "").strip() or machine
    if not (project and name):
        return None, (400, {"error": "project and name are required: the project and the retired agent's name"})
    if label_bad(sender):
        return None, (400, {"error": _SENDER_TEXT})
    if not is_form(machine, sender):
        return None, (403, {"error": RETIRE_NOT_FORM})
    if not NAME_RE.fullmatch(name):
        return None, (400, {"error": _NAME_TEXT})
    return (project, name, sender), None


def retire_answer(rec: dict[str, Any], key: str, where: str, res: dict[str, Any], name: str, extra: dict[str, Any]) -> _Refusal:
    """The 200 of `post project-agent-retire`: nothing to remove, a pending entry dropped, or the line removed. `extra` is the archive step's answer (`{}` where none ran)."""
    m = res["mirror"]
    tail = agents_block_tail(m)
    if res["result"] == "not listed":
        return 200, {"project": rec["id"], "key": key, "result": "not listed", "agent": name, "page_owed": False, "mirror": m,
                     "reason": f"{name} is not on {where}'s agents map and not pending in the record: nothing to remove.", "note": f"{name} is not listed on {where}: nothing to do."}
    if res["result"] == "dropped":
        return 200, {"project": rec["id"], "key": key, "result": "dropped", "agent": res["name"], "page_owed": False, "mirror": m,
                     "note": f"{res['name']} was only pending for {where}: dropped from the record, so no page update is owed for it.", **extra}
    return 200, {"project": rec["id"], "key": key, "result": "line removed", "agent": res["name"], "front": res["front"], "page_owed": False, "mirror": m,
                 "note": f"Took {res['name']} off {where}'s agents map in the project record" + (f"; the page {key} follows from the record, with a timeline line." if key else " (the project has no page).") + tail,
                 **extra}


# get projects, post project and post project-list ---------------------------
def list_params(params: dict[str, str], scopes: list[str]) -> tuple[tuple[str, str] | None, tuple[int, str, str] | None]:
    """The query of `get projects` → ((scope, q), None), or (None, the 400 as (status, type, text)). `scopes` are the instance's scope names."""
    scope = str(params.get("scope") or "").strip().lower()
    q = str(params.get("q") or "").strip()
    if scope and scope != "all" and scope not in scopes:
        return None, (400, "text/plain", f"scope = {' | '.join(scopes)} | all")
    if len(q) > 200 or any(ord(c) < 32 for c in q):
        return None, (400, "text/plain", "q = a search text of one line, at most 200 characters")
    return (scope, q), None


def new_project_fields(machine: str, body: dict[str, Any], scopes: list[str], dirs: list[str]) -> tuple[dict[str, Any] | None, _Refusal | None]:
    """The body of `post project` → ({legacy, page, make_page, scope, title, name, sender, key}, None), or (None, the 400). `scopes` are the instance's scope names, `dirs` its page dirs."""
    legacy = str(body.get("key") or "").strip().strip("/")
    page = legacy or str(body.get("page") or "").strip()
    if page.endswith(".md"): page = page[:-3]
    mp = body.get("make_page")
    make_page = bool(legacy) if mp is None else bool(mp)          # the form's `key` makes its page, as it always did; a `page` pointer makes one only on request
    scope = str(body.get("scope") or "").strip().lower()
    title = " ".join(str(body.get("title") or "").split())
    name = " ".join(str(body.get("name") or "").split())
    sender = str(body.get("sender") or "").strip() or machine
    if not scope or not (page or name):
        return None, (400, {"error": "scope and a name or a page key (projects/<slug> or infra/<slug>) are required"})
    if scope not in scopes:
        return None, (400, {"error": f"scope = {' | '.join(scopes)}"})
    key = ""
    if page and (legacy or ("://" not in page and not re.search(r"\s", page))):          # `key` is always a page key; `page` may be a link to another knowledge base
        key = page
        top, _, slug = key.partition("/")
        if top not in dirs or not slug or (make_page and (not prj.SLUG_RE.fullmatch(slug) or len(slug) > 60)):
            return None, (400, {"error": f"key = {' or '.join(d + '/<slug>' for d in dirs)}, one level, the slug lowercase letters, digits and dashes (at most 60): got {key[:80]!r}"})
    if len(title) > 120 or any(ord(c) < 32 or c in '"\\' for c in title):
        return None, (400, {"error": "title = one line of at most 120 characters, with no quotation marks or backslashes (the pages checkout's reader takes the frontmatter as it stands)"})
    if label_bad(sender):
        return None, (400, {"error": _SENDER_TEXT})
    return {"legacy": legacy, "page": page, "make_page": make_page, "scope": scope, "title": title, "name": name, "sender": sender, "key": key}, None


def exists_text(key: str) -> str:
    """The 409 for a page that exists already (or has sub-pages, or some project points at it)."""
    return f"{key} already exists: list it again with `client.py post project-list --key {key}` (a hidden project keeps its page, agents and history)"


def create_refusal(status: int, message: str, key: str, exists: str, store: str) -> str:
    """The text of a refused `create` verb: a 409 on a page names `post project-list`; the page store is named as this instance calls it (`store`)."""
    return (message if status != 409 or not key else f"{message}; {exists}").replace("the page store", store)


def new_project_answer(rec: dict[str, Any], name: str, scope: str, pid: str, key: str, make_page: bool, m: dict[str, Any], store: str) -> _Refusal:
    """The 200 of `post project`: `m` is the page mirror's state, `store` what a note names as the page store."""
    state = "ok" if m["state"] in ("written", "unchanged") else m["state"]
    note = (f"Made {name} ({pid}) in scope {scope}: its entry is in the project record and the project is listed" + (f"; its page {key} is written through {store}." if make_page and state == "ok" else
            f"; its page is {key}." if key else "; it has no page.") + f" Add the first agent with `client.py post project-agent {pid} {name}-main --role main --front --mandate \"…\"`.")
    if make_page and state != "ok":
        note += (f" The page {key} was not made ({m['note']}); the record holds the project." if state == "retired" else
                 f" The page {key} was not made ({m['note']}); the record is right, and the next change to the project makes it.")
    return 200, {"project": rec, "created": True, "page": {"key": key, "state": state, "display_name": name}, "page_yaml": "", "mirror": m, "note": note}


def list_fields(machine: str, body: dict[str, Any], scopes: list[str]) -> tuple[tuple[str, str, str] | None, _Refusal | None]:
    """The body of `post project-list` → ((project, scope, sender), None), or (None, the 400)."""
    project = str(body.get("key") or body.get("project") or "").strip()
    scope = str(body.get("scope") or "").strip().lower()
    sender = str(body.get("sender") or "").strip() or machine
    if not project:
        return None, (400, {"error": "key = the project: its id (prj_<8 hex>), its page key or its bare slug"})
    if scope and scope not in scopes:
        return None, (400, {"error": f"scope = {' | '.join(scopes)}"})
    if label_bad(sender):
        return None, (400, {"error": _SENDER_TEXT})
    return (project, scope, sender), None


def list_refusal(rec: dict[str, Any], up: str) -> _Refusal | None:
    """A project that cannot be listed: a sub-page (`up` is the page above it, "" when none is found), a retired project, a note page."""
    if rec["sub_page"]:
        return 400, {"error": f"{rec['key']} is a sub-page of {up or 'a project'} (or has a hub: line), and a sub-page is never listed: list {up or 'the project above it'}"}
    if rec["retired"]:
        return 400, {"error": f"{rec['key']} is retired (page status: {rec['status']}): change the page's status first"}
    if rec["type"] == "note":
        return 400, {"error": f"{rec['key']} is a `type: note` page, and a note is never listed; a project page has `type: project`"}
    return None


def list_answer(rec: dict[str, Any], changed: bool) -> _Refusal:
    """The 200 of `post project-list`."""
    return 200, {"project": rec, "changed": changed, "note": f"{rec['key']} is listed on purpose from now on." if changed else f"{rec['key']} was already listed on purpose: nothing changed (its first-agent window is renewed)."}
