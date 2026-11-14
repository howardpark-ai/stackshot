"""service/projects.py: the calls of the fleet tool's New session form that make and list projects and register their agents: `get projects` (`_projects_list`), `post project` (`_new_project`),
`post project-list` (`_project_list`), `post project-agent` (`_project_agent`, `_project_agent_locked`), `post project-agent-mandate` (`_project_agent_mandate`), and the reads and the writes of
`post project-agent-rename` and `post project-agent-retire`, with what reads the config to decide whether a caller is the form (`_form_call`, `_cfg_names`, `[project_agent]` form_senders and form_machines),
the one lock the writes share (`_PROJECT_LOCK`, with `_RENAMING`, the page keys a rename or retire has in flight) and the page store they write through (`_page_io`, `PAGE_IO`).

The rules are not here: the shape of each body, who may ask, the name rules and the words of every refusal and answer are in projects/project_verbs.py (the section "the New session form's checks"), which reads
nothing. This module reads the project record, the registry, the fleet's session names, the config and the clock, hands them to those rules, and writes: the record and the page's mirror through the verbs of
projects/project_verbs.py, the project files (projects.json) after each write. The wrappers of the rename and of the retire (`_project_agent_rename`, `_project_agent_retire`) are here too: each takes
`_PROJECT_LOCK` and `_RENAMING`, runs the checks, then the write outside the lock and ends in `_contact_after_agent` (service/contacts.py), which moves the items' contacts. `_PROJECT_LOCK` and
`_RENAMING` are mutated in place, never rebound. `PAGE_IO` is the one name a suite sets that `_page_io` reads: it is read and set on this module (`projects_svc.PAGE_IO = ...`), and the server's own reads of
the page store go through `_page_io`."""
from __future__ import annotations

import datetime as dt
import json
import threading
from typing import Any

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.projects import brains as _brains
from stackshot.projects import project_archive as _archive
from stackshot.projects import project_registry as _pr
from stackshot.projects import project_verbs as _verbs
from stackshot.projects import projects as _prj
from stackshot.projects.project_registry import _projects_sync_safe, _registry
from stackshot.router import page_debt as _page_debt
from stackshot.service import contacts as _contacts


_FORM_SENDERS: list[str] = []     # the defaults of [project_agent] (stackshot.example.toml): no sender label, so no form call, until the instance names the New session form's label
_FORM_MACHINES: list[str] = []     # ... and of form_machines (none until the instance names the machine whose token the form is allowed from)


def _cfg_names(key: str, default: list[str]) -> list[str]:
    """[project_agent] <key> as a list of strings (see project_verbs.section_names). Read where it is used, so a reload applies."""
    return _verbs.section_names(_cfg.get("project_agent"), key, default)


def _form_call(machine: str, sender: str) -> bool:
    """Is this `post project-agent` the New session form's? Only when the `sender` label is in [project_agent] form_senders AND the machine its
    token proves (`machine`, never the body) is in form_machines: a label alone is not enough, since any token holder can type it."""
    return _verbs.form_call(machine, sender, _cfg_names("form_senders", _FORM_SENDERS), _cfg_names("form_machines", _FORM_MACHINES))


def _name_clash(name: str, key: str, pid: str, prefixes: list[str], reg: dict[str, Any]) -> str:
    """A name belongs to one project (every path, the form's too): the 409 text, or "" when the name is free for the project `key` (id `pid`) (project_verbs.name_clash,
    given the record's entries, the pending agents and the id-to-key lookup). Shared by `post project-agent` and `post project-agent-rename`."""
    return _verbs.name_clash(name, key, pid, prefixes, reg, _pr.entries(), _prj._pending_all(), lambda pid2: _prj.id_to_key(pid2, reg))


def _recs_of(project: str, reg: dict[str, Any]) -> list[dict[str, Any]]:
    """The records a project reference names: the pages' (an id, a page key or a bare slug), else the one a project with no page is."""
    return _prj.refs(project, reg) or [r for r in [_verbs.pageless_rec(project)] if r]


def _project_agent(machine: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """The whole of `post project-agent` under _PROJECT_LOCK, so that the check of who may register and the write of the pending agent are one
    step: two parallel first-agent calls cannot both pass (see _project_agent_locked). The record is written under the lock; the page's mirror lines are written after it
    (a slow page store stalls nobody), and a mirror that fails is told in the answer, the record being right already."""
    pages = _verbs.preread(str(body.get("project") or "").strip(), _page_io())          # the page of a project with no entry yet is read BEFORE the lock: no page-store call waits inside _PROJECT_LOCK
    with _PROJECT_LOCK:
        status, out = _project_agent_locked(machine, body, pages)
    pid = out.pop("_mirror", "") if isinstance(out, dict) else ""
    if pid:
        m = _verbs.mirror(pid, _page_io())
        out["mirror"] = m
        tail = _verbs.agent_mirror_tail(m)
        if tail:
            out["note"] = f"{out.get('note', '')}{tail}"
    return status, out


def _project_agent_locked(machine: str, body: dict[str, Any], pages: dict | None = None) -> tuple[int, dict[str, Any]]:
    """`client.py post project-agent <project> <name> --role R (--front|--back) --mandate "…"`: list an agent in a
    project's record. Allowed to the project's keeper and to its front agents, as the record lists them (an agent a leftover pending
    entry holds, its page line still owed, does not count). `sender` must be the asking session's id, a transcript id (what
    $CLAUDE_CODE_SESSION_ID holds) or a cse_ id, never a bare name: a name anyone can type; an id has to resolve through the fleet's
    heartbeat to a name that is the keeper or a listed front agent (a cloud session whose own cse_ id is the keeper or the listed name
    matches as it is). The token proves the machine and the id is the session's own word: that is as far as the client API can tell
    who asks. The record is the authority: the agent is written to the project's agents map in <store>/project-record.json
    (project_verbs.agent_add; a project with no entry yet gets one from its page first, its pending agents folded in), and the page's `agents:` block is
    written from the record (the mirror, after _PROJECT_LOCK is released). No line is left owing, so the reply carries `page_owed` false and an empty `page_yaml`,
    and a `mirror` {state, key, note}. A page edit to a listed agent is not read; the next mirror write restores the page. A name already listed with the same side
    and mandate changes nothing; with another it is a 409 (retire or rename it first).
    The agents map lives on a hub page, so a sub-page, or a page with a `hub:` line, is refused with the page to use.
    Two exceptions, for the fleet tool's New session form (which has no session), both by a label as sender, never a name anyone can type for a session:
    (1) the first agent of a project made or listed again on purpose (`post project`, `post project-list`): the project lists no agent, its
    keeper is no present session (the fleet's present-only lookup, not the retired names), the mark was made or renewed within the last hour
    and its `by` is the sender; (2) further agents while every agent of the project is one a leftover pending entry holds and all were
    registered by that same label. Once the page carries an agents map only the keeper and a front agent may, with one more exception:
    (3) a form call (_form_call: `sender` in [project_agent] form_senders AND the token's machine in form_machines; defaults: no sender label, no machine)
    may register a new pending agent on any LISTED project, whether or not it has agents (a hidden project, or a note page, is a 403 telling the
    caller to list it again first with `post project-list`). Every other check still applies: validation, the project-name prefix, a name already
    on the page ("already listed"), a name already pending by another sender (409). A form call never edits or removes an agent that is on the page
    and never changes another sender's pending agent. The same label from another machine, or another label from the form's machine, gets the rules above.
    A name belongs to one project, on every path: a name that is already an agent of another project (its page map or its pending list), or that starts
    with the longer name prefix of another project (team-alpha-docs-main under projects/alpha, when projects/alpha-docs is named team-alpha-docs), is a
    409. Names compare case-folded here and for "already listed" and the pending 409. A non-table `[project_agent]` section switches form calls off.
    The reply carries `page_yaml` (empty: the
    page is written from the record, so there is nothing for the form to show), `page_owed` false, the `mirror` and a `note` that says the record has the agent.
    """
    fields, bad = _verbs.agent_fields(body)
    if bad: return bad
    project, name, role, mandate, sender, front = fields
    reg = _prj.with_made(_registry("projects"))        # a project just made through `post project` is here before the pages checkout has read its page
    rec, bad = _verbs.pick_project(project, _recs_of(project, reg))
    if bad: return bad
    key = rec["key"]; entry = reg.get(key) or {}
    bad = _verbs.hub_refusal(rec, entry, "list the agent there")
    if bad: return bad
    where = key or rec["id"]                                # how an answer names the project: its page, else its id
    nm = _anc.names()
    # The label path (see the docstring). The mark's time is the last make or re-list (`at`, else `on_purpose`); the keeper counts as live only
    # when the fleet holds a present session of that name (by_name is present-only: a retired name resolves to nothing).
    mark = _prj.marks().get(rec["id"]) or {}
    owed = _prj._pending_all().get(rec["id"], {})
    age = _verbs.mark_age(mark, dt.datetime.now(dt.timezone.utc))
    keeper_live = bool(rec["keeper"]) and rec["keeper"] in getattr(nm, "by_name", {})
    listed_by = (_pr.entries().get(rec["id"]) or {}).get("agents") or {}          # the agents the record lists, with who listed each (a migrated agent names nobody)
    first, more = _verbs.label_paths(rec, mark, owed, listed_by, keeper_live, sender, age)
    form = _form_call(machine, sender)         # the New session form: the label AND the machine its token proves (never the body's)
    bad = _verbs.agent_caller_refusal(rec, key, form, first, more, sender, _anc.is_id(sender), nm.get)
    if bad: return bad
    prefixes = _verbs.project_prefixes(rec, entry, reg)      # the name, else the page's slug: an agent is always <project>-<role>
    bad = _verbs.prefix_refusal(name, prefixes, where)
    if bad: return bad
    new = {"front": front, "role": role, "mandate_line": mandate}
    clash = _name_clash(name, key, rec["id"], prefixes, reg)
    if clash:
        return 409, {"error": clash}
    name, bad = _verbs.listed_answer(rec, key, where, name, front, mandate)
    if bad: return bad
    name = _verbs.pending_name(_prj._pending_all().get(rec["id"], {}), name)     # a pending entry under another spelling is the same agent
    pend = _prj.pending_entry(rec["id"], name)
    bad = _verbs.pending_refusal(pend, sender, name, where, front, role, mandate)
    if bad: return bad
    try:
        res = _verbs.agent_add(rec["id"], name, front, mandate, by=sender, io=_page_io(), mirror_now=False, pages=pages if pages is not None else {})       # the record first; the page's mirror follows, outside the lock
    except _verbs.VerbError as e:
        return e.status, {"error": e.message}
    except ValueError as e:
        return 503, {"error": _verbs.unwritable(e)}
    _projects_sync_safe(force=True)
    return _verbs.agent_added(rec, key, where, res, new)


def _project_agent_mandate(machine: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """`client.py post project-agent-mandate <project> <name> --mandate "…" [--sender <session id>]`: change the mandate line of an agent already on the project's agents map (the record,
    project_verbs.agent_mandate), then the page's `agents:` block is written from it (the mirror, after _PROJECT_LOCK is released), so a later mirror write keeps the new line: the record is the
    authority and a page edit to the line is not read. Who: the project's keeper and its front agents, as `post project-agent` (`sender` is the asking session's id, never a name; no label
    path: the New session form lists agents, it does not rewrite their lines). The agent keeps its side (front or background), its place in the map and who listed it.
    Answers: 200 {project, key, agent: {name: {front, role, mandate_line}}, previous, mirror, note} (the same line again: 200, "nothing changed") · 400 a missing field, a bad name, a backslash in the line, an empty
    or over-long mandate, a control character or a backslash in it, an ambiguous slug, a page that is not a hub · 403 a name as sender, or a session that is neither the keeper nor a front agent · 404 unknown
    project, or `name` not listed on it (list it first with `post project-agent`) · 503 the record cannot be written. A mirror that cannot be written is told in the answer: the record is right."""
    fields, bad = _verbs.mandate_fields(body)
    if bad: return bad
    project, name, mandate, sender = fields
    pages = _verbs.preread(project, _page_io())          # the page of a project with no entry yet is read BEFORE the lock, as `post project-agent` does
    with _PROJECT_LOCK:
        reg = _prj.with_made(_registry("projects"))
        rec, bad = _verbs.pick_project(project, _recs_of(project, reg))
        if bad: return bad
        key = rec["key"]; entry = reg.get(key) or {}
        bad = _verbs.hub_refusal(rec, entry, "change the line there")
        if bad: return bad
        where = key or rec["id"]
        bad = _verbs.front_caller_refusal(sender, _anc.is_id(sender), _anc.names().get, rec, where, "changes an agent's mandate line")
        if bad: return bad
        try:
            res = _verbs.agent_mandate(rec["id"], name, mandate, by=sender, io=_page_io(), mirror_now=False, pages=pages)
        except _verbs.VerbError as e:
            return e.status, {"error": e.message}
        except ValueError as e:
            return 503, {"error": _verbs.unwritable(e)}
    _projects_sync_safe(force=True)
    m = _verbs.mirror(rec["id"], _page_io()) if key else {"state": "none", "key": "", "note": ""}
    role = _prj.role_of(res["name"], _verbs.project_prefixes(rec, entry, reg))
    return _verbs.mandate_answer(rec, key, where, res, m, role)


_RENAMING: set[str] = set()     # page keys a `post project-agent-rename` is working on right now (its gbrain calls run outside the lock); read and changed under _PROJECT_LOCK only


def _project_agent_rename_checks(machine: str, body: dict[str, Any]) -> Any:   # -> (status, JSON) to answer, or (rec, old, new, prefixes, reg) to go on with
    """`client.py post project-agent-rename <project> <OLD> <NEW> [--sender <label>]`: rename an agent's entry in the `agents:` map of the project's
    record, in place (project_verbs.agent_rename), and the page's block follows from it. A session's own rename is the fleet tool's; this keeps the project in step with it.
    Who: the New session form's caller only (_form_call: `sender` in [project_agent] form_senders AND the token's machine in form_machines), else 403.
    The record is changed first, atomically (the entry's place in the map, front or `background:` and the mandate stay as they are; a pending entry of the old name is
    dropped), then the page's mirror lines are written from it: the page is read from the page store with its revision and put back with that revision (a
    stale one is refused and read again), then read back. A mirror that cannot be written is told in the answer; the record is right already and the next
    change to the project writes the page again.
    Answers: 200 {result: "renamed", ...} · 200 {result: "already renamed", note: "already renamed"} when OLD is no longer listed and NEW is (a
    retry after a lost reply: there is no stored OLD to compare, so that is taken as done) · 409 "<NEW> is already listed on <page>" while OLD is
    still listed too · 404 "<OLD> is not listed on <page>" · 409 for a NEW that belongs to another project (as project-agent) or is registered here
    as a pending agent whose page line is owed · 400 a bad body, name or hub page, OLD and NEW the same name · 403 not the form · 404 unknown
    project · 422 the page's agents block is in a shape that cannot be edited in place · 502 gbrain did not give the page, refused the write or
    the read back does not show it · 409 "a rename of <page> is in progress; try again" while another rename of the same page is inside gbrain. Every refusal
    changes nothing. Pending agents and other agents are never touched; no session is renamed."""
    fields, bad = _verbs.rename_fields(machine, body, _form_call)
    if bad: return bad
    project, old, new, sender = fields
    reg = _prj.with_made(_registry("projects"))
    rec, bad = _verbs.pick_project(project, _recs_of(project, reg))
    if bad: return bad
    key = rec["key"]; entry = reg.get(key) or {}
    bad = _verbs.hub_refusal(rec, entry, "rename the agent there")
    if bad: return bad
    prefixes = _verbs.project_prefixes(rec, entry, reg)
    bad = _verbs.prefix_refusal(new, prefixes, key or rec["id"])
    if bad: return bad
    clash = _name_clash(new, key, rec["id"], prefixes, reg)
    if clash:
        return 409, {"error": clash}
    return rec, old, new, prefixes, reg, sender


def _project_agent_rename_write(rec: dict[str, Any], old: str, new: str, prefixes: list[str], reg: dict[str, Any], sender: str = "") -> tuple[int, dict[str, Any]]:
    """The second half of `post project-agent-rename`, outside _PROJECT_LOCK with the page key in _RENAMING: the verb renames the entry in the project's agents map
    (the record, atomically), then writes the page's mirror lines (project_verbs.agent_rename; see _project_agent_rename_checks's docstring for the answers). A mirror that
    cannot be written is told in the answer (`mirror`, and the note): the record is right and the next change to the project writes the page again."""
    key = rec["key"]; where = key or rec["id"]
    bad = _verbs.rename_pending_refusal(_prj._pending_all().get(rec["id"], {}), rec, where, old, new)
    if bad: return bad
    try:
        res = _verbs.agent_rename(rec["id"], old, new, by=sender, io=_page_io())
    except _verbs.VerbError as e:
        return e.status, {"error": e.message}
    except ValueError as e:
        return 503, {"error": _verbs.unwritable(e)}
    _projects_sync_safe(force=True)
    return _verbs.rename_answer(rec, key, where, res, old, new, prefixes)


def _project_agent_retire_checks(machine: str, body: dict[str, Any]) -> Any:   # -> (status, JSON) to answer, or (rec, name, sender) to go on with
    """The gate, the names and the project of `post project-agent-retire` (see _project_agent_retire)."""
    fields, bad = _verbs.retire_fields(machine, body, _form_call)
    if bad: return bad
    project, name, sender = fields
    reg = _prj.with_made(_registry("projects"))
    rec, bad = _verbs.pick_project(project, _recs_of(project, reg))
    if bad: return bad
    bad = _verbs.hub_refusal(rec, reg.get(rec["key"]) or {}, "retire the agent there")
    if bad: return bad
    return rec, name, sender


def _project_agent_retire_write(rec: dict[str, Any], name: str, sender: str) -> tuple[int, dict[str, Any]]:
    """The second half of `post project-agent-retire`, outside _PROJECT_LOCK with the page key in _RENAMING: the verb takes the agent off the project's agents map (the record,
    atomically; a pending entry of the name goes with it), then writes the page's mirror lines and the timeline line (project_verbs.agent_retire), and the archive rule is applied
    (see _project_agent_retire). A mirror that cannot be written is told in the answer: the record is right already."""
    key = rec["key"]; where = key or rec["id"]
    io = _page_io()
    try:
        res = _verbs.agent_retire(rec["id"], name, by=sender, io=io)
    except _verbs.VerbError as e:
        return e.status, {"error": e.message}
    except ValueError as e:
        return 503, {"error": _verbs.unwritable(e)}
    _projects_sync_safe(force=True)
    today = dt.datetime.now(_cfg.tz()).strftime("%Y-%m-%d")
    extra = {} if res["result"] == "not listed" else _archive_after(io, rec, None, today, sender)
    return _verbs.retire_answer(rec, key, where, res, name, extra)


def _archive_after(io: Any, rec: dict[str, Any], content: str | None, today: str, sender: str) -> dict[str, Any]:
    """The last step of `post project-agent-retire` for an agent that was on the page or pending: when the project has no agent left and no open item its
    page is archived (project_archive.after_retire) → {"archived", "archive_note"} for the answer. A failure here never fails the retire, which has
    already been written: it is told in the note."""
    try:
        left = len(_prj._pending_all().get(rec["id"], {}))
        return _archive.after_retire(io, rec, content, today, sender, left, _prj.with_made(_registry("projects")))
    except Exception as e:  # noqa: BLE001 — the retire is done; tools/archive_empty_projects.py finds a project this step missed
        return {"archived": False, "archive_note": f"not archived: {type(e).__name__}: {str(e)[:120]}"}


# ----------------------------------------------------------------------------- the project picker (the fleet tool's "New session" form)
# `get projects` lists the projects of a scope, `post project` makes a new one with its page, `post project-list` lists a hidden one again,
# and `post project-agent` (above) adds the form's new agent. Scope, listed/hidden and the rest are projects.py's; a scope set on purpose and
# the "listed on purpose" mark live in <store>/project-record.json (the page registry is rebuilt from the pages and could not keep them).
_PROJECT_LOCK = threading.Lock()
PAGE_IO: Any = None             # tests put an object here with get(slug) -> (content, revision) and create(slug, content) -> (state, note); None = the instance's own (page_debt.page_io: the page files, or gbrain's CLI)


def _page_io() -> Any:
    return PAGE_IO if PAGE_IO is not None else _page_debt.page_io()


def _page_store() -> str:
    """Who a refusal names as the page store: gbrain, or the pages checkout under `[pages] flavor = "plain"`."""
    return "gbrain" if _cfg.page_flavor() == "gbrain" else "the pages checkout"


def _projects_list(params: dict[str, str]) -> tuple[int, str, str]:
    """`get projects?scope=<scope name|all>[&q=<text>]` (the New session form): the listed projects of the scope, then, only with `q`, the
    hidden ones whose key, name or title holds it (case-insensitive), marked `hidden: true`. A sub-page and a retired project are never in it. →
    {"scope", "q", "generated", "scopes", "projects": [{id, key, title, name, scope, listed, hidden, listed_by, keeper, main, agents, items_30d, status, retired}]}.
    A bad scope is a 400, so a typo is not read as "no projects"."""
    parsed, bad = _verbs.list_params(params, _prj.scopes())
    if bad: return bad
    scope, q = parsed
    try:
        rows = _prj.list_projects(scope, q, _registry("projects"))
    except ValueError as e:         # the id file is damaged and a page has no id in the registry: nothing is minted, the reader tries again
        return 503, "text/plain", f"the project record cannot be read right now: {e}"
    out = {"scope": scope or "all", "q": q, "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "scopes": _prj.scopes(), "projects": rows}
    return 200, "application/json", json.dumps(out, ensure_ascii=False)


def _one_project(project: str) -> tuple[dict[str, Any] | None, tuple[int, dict[str, Any]] | None]:
    """A project named by id, key or bare slug → (its record, None), or (None, the refusal)."""
    try:
        recs = _prj.refs(project, _registry("projects"))
    except ValueError as e:
        return None, (503, {"error": f"the project record cannot be read right now, nothing was changed: {e}"})
    recs = recs or [r for r in [_verbs.pageless_rec(project)] if r]          # a project with no page is the record's alone
    return _verbs.pick_project(project, recs)


def _new_project(machine: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """`client.py post project --scope <s> [--name <n>] [--key <page dir>/<slug>] [--page <key or link>] [--make-page] [--title <t>] [--sender <label>]`: make a project
    (project_verbs.create): its entry in the project record first (a new permanent id, the name, the scope, listed on purpose), then, when the project has a page of this
    instance's page store, the page's lines. The page is optional: with neither `key` nor `page` the project has no page and none is made. `key` is the form's own parameter
    (a project page, made from the template of projects/example, Part 2, unless `make_page` is false); `page` is a pointer (a page key of this instance, or a link to another
    knowledge base) that makes a page only with `make_page` true. The name is `name`, else the page's slug (the prefix of the project's agents' names). A page that already
    exists (or has sub-pages, or some project points at it) is a 409 that names `post project-list`; a key outside the page dirs, with a sub-path or a slug that is not lowercase
    letters, digits and dashes (when a page is made) is a 400. The record is right as soon as the call returns: a page that could not be written is told in `page.state` and the
    note, and the project's next change writes it again. The first agent is added with `post project-agent` (allowed on a project made this way until it has one).
    → (status, {project, created, page, note})."""
    f, bad = _verbs.new_project_fields(machine, body, _prj.scopes(), _cfg.page_dirs())
    if bad: return bad
    make_page, scope, title, name, sender, key = f["make_page"], f["scope"], f["title"], f["name"], f["sender"], f["key"]
    page = f["page"]
    if key:
        title = title or _prj.slug_title(key)
        name = name or _prj.page_front(key, title, scope)["display_name"]
    exists = _verbs.exists_text(key)
    if key and make_page:
        try:
            reg = _prj.with_made(_registry("projects"))
        except ValueError as e:
            return 503, {"error": _verbs.unwritable(e, "made")}
        if key in reg or any(k.startswith(key + "/") for k in reg):
            return 409, {"error": exists}
        kb = _brains.for_key(key)       # the copy of the brain that will hold the page ([[brains]]); a second brain that cannot be read is not looked at here
        brain = _cfg.path("paths", "brain") if kb.default else kb.path
        if (kb.default or not _brains.problem(kb)) and ((brain / f"{key}.md").exists() or (brain / key).exists()):
            return 409, {"error": exists}
    try:
        res = _verbs.create(name, scope, page, make_page=make_page, title=title, by=sender, io=_page_io() if key else None)
    except _verbs.VerbError as e:
        return e.status, {"error": _verbs.create_refusal(e.status, e.message, key, exists, _page_store())}
    except ValueError as e:
        return 503, {"error": _verbs.unwritable(e, "made")}
    pid = res["project"]; m = res["mirror"]
    _projects_sync_safe(force=True)
    rec, bad = _one_project(pid)
    if bad: return bad
    return _verbs.new_project_answer(rec, name, scope, pid, key, make_page, m, _page_store())


def _project_list(machine: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """`client.py post project-list --key <id | key | slug> [--scope <s>] [--sender <label>]`: list a hidden project again (it keeps its page, agents
    and history; it was never deleted). Marks it listed on purpose, and sets its scope when `scope` is given. Said again it changes nothing.
    A sub-page is refused (400), with the page above it to list. → (status, {project, changed, note})."""
    fields, bad = _verbs.list_fields(machine, body, _prj.scopes())
    if bad: return bad
    project, scope, sender = fields
    rec, bad = _one_project(project)
    if bad: return bad
    up = ""
    if rec["sub_page"]:
        e = _registry("projects").get(rec["key"]) or {}
        parts = rec["key"].split("/")
        up = str(e.get("hub") or "") or next(("/".join(parts[:n]) for n in range(2, len(parts)) if "/".join(parts[:n]) in _registry("projects")), "")
    bad = _verbs.list_refusal(rec, up)
    if bad: return bad
    try:
        with _PROJECT_LOCK:
            before = (_prj.marks().get(rec["id"]) or {})
            now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            changed = not before.get("on_purpose") or bool(scope and before.get("scope") != scope)
            # every call renews `at` and `by`: the first-agent window (project-agent) runs from the latest list, by the latest label
            _prj.set_mark(rec["id"], on_purpose=before.get("on_purpose") or now, at=now, by=sender, **({"scope": scope} if scope else {}))
    except ValueError as e:
        return 503, {"error": _verbs.unwritable(e)}
    _projects_sync_safe(force=True)
    rec, bad = _one_project(rec["id"])
    if bad: return bad
    return _verbs.list_answer(rec, changed)


def _project_agent_rename(machine: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """`post project-agent-rename`, in the shape of `post project`: _PROJECT_LOCK is held only for the quick checks (the gate, the names, the project, the
    name clash with other projects) and to put the page key in _RENAMING; the gbrain read, the edit, the put and the read back run outside it, so a slow
    gbrain never stalls `post project-agent` or `post project-list` (whose clients give up at 30 s). A second rename of the same page while one is in
    flight is a 409 "in progress", which changes nothing. The key leaves _RENAMING in a finally. A writer outside stackshot is caught by the put's
    expected revision."""
    with _PROJECT_LOCK:
        pre = _project_agent_rename_checks(machine, body)
        if isinstance(pre[0], int):
            return pre
        busy = pre[0]["key"] or pre[0]["id"]
        if busy in _RENAMING:
            return 409, {"error": f"a rename of {busy} is in progress; try again"}
        _RENAMING.add(busy)
    try:
        return _contacts._contact_after_agent(_project_agent_rename_write(*pre), "rename", pre[1], pre[2])
    finally:
        with _PROJECT_LOCK:
            _RENAMING.discard(busy)


def _project_agent_retire(machine: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """`client.py post project-agent-retire <project> <name> [--sender <label>]`: sala retired a session, so stackshot takes the agent off its project:
    its line is removed from the project's agents map in the record (a pending entry of the name goes with it), and the page's `agents:` block follows from the record, with a timeline line on the page.
    Who: the New session form's caller only, as `post project-agent-rename` (_form_call: `sender` in [project_agent] form_senders AND the token's
    machine in form_machines), else 403. Like the rename, the record is changed first and the page's block is written from it (put at the revision it was read at, never forced, read
    back); then the timeline line is added (page_debt's page store: gbrain's `add_timeline_entry`, dated today in the instance timezone, source "stackshot").
    A refused put (a revision that moved on) is read again and tried again; a page that still cannot be written is told in the answer, the record being right. The quick checks and the key in _RENAMING are under _PROJECT_LOCK; the gbrain calls run
    outside it, so a slow gbrain stalls nobody else, and a second retire or rename of the same page meanwhile is a 409 "in progress".
    Answers: 200 {result: "line removed"} the agent was on the page's `agents:` map (front or `background:`) and its line is gone (a pending entry for
    the same name is dropped with it) · 200 {result: "dropped"} the agent was only pending here (its page line still owed): the pending entry is removed,
    no page is written · 200 {result: "not listed"} it is on no page of the project and not pending: nothing to do (a repeat after a lost reply, or a
    session that never had a line), with the reason · 404 unknown project · 400 a bad body, name or sender, an ambiguous slug, a page that is not a hub
    · 403 not the form · 409 a rename or retire of the page is in progress; try again · 422 the agents block is in a shape that cannot be edited in place
    · 502 gbrain did not give the page, refused the write twice or the read back does not show the removal, or the line is removed but the timeline line
    could not be written (the error says which; the page holds the removal)."""
    with _PROJECT_LOCK:
        pre = _project_agent_retire_checks(machine, body)
        if isinstance(pre[0], int):
            return pre
        busy = pre[0]["key"] or pre[0]["id"]
        if busy in _RENAMING:
            return 409, {"error": f"a rename or retire of {busy} is in progress; try again"}
        _RENAMING.add(busy)
    try:
        return _contacts._contact_after_agent(_project_agent_retire_write(*pre), "retire", pre[1])
    finally:
        with _PROJECT_LOCK:
            _RENAMING.discard(busy)
