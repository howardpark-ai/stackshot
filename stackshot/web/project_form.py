"""project_form.py: the calls of the fleet tool's New session form that make and list projects and register their agents: `get projects` (`_projects_list`), `post project` (`_new_project`),
`post project-list` (`_project_list`), `post project-agent` (`_project_agent`, `_project_agent_locked`), `post project-agent-mandate` (`_project_agent_mandate`), and the checks and the writes of
`post project-agent-rename` and `post project-agent-retire`, with what decides whether a caller is the form (`_form_call`, `_cfg_names`, `[project_agent]` form_senders and form_machines), the name rules
(`_AGENT_NAME`, `_name_clash`), the one lock the writes share (`_PROJECT_LOCK`, with `_RENAMING`, the page keys a rename or retire has in flight) and the page store they write through (`_page_io`, `PAGE_IO`).

server.py is being split into one module per area (CONTRIBUTING.md, Layout). The module decides and writes the project record; what stays in server.py of the area is the wrapper of the rename
and of the retire (`_project_agent_rename`, `_project_agent_retire`), because each ends in `_contact_after_agent`, which moves the items' contacts and is server.py's still (a module here cannot import
server.py). server.py imports each name its routes, its other areas and the suites read back from here, so `server._form_call`, `server._PROJECT_LOCK`, `server._RENAMING` and the others stay the
names they use; `_PROJECT_LOCK` and `_RENAMING` are mutated in place, never rebound, so the name on `server` and the one here are one object. `PAGE_IO` is the one name a suite sets that `_page_io`
reads: it is read and set on this module (`server._pform.PAGE_IO = ...`), and the server's own reads of the page store go through `_page_io`."""
from __future__ import annotations

import datetime as dt
import json
import re
import threading
from typing import Any

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.projects import brains as _brains
from stackshot.projects import project_archive as _archive
from stackshot.projects import project_registry as _pr
from stackshot.projects import project_verbs as _verbs
from stackshot.projects import projects as _prj
from stackshot.router import page_debt as _page_debt
from stackshot.projects.project_registry import _projects_sync_safe, _registry


_AGENT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_AGENT_ROLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}")


_FORM_SENDERS: list[str] = []     # the defaults of [project_agent] (stackshot.example.toml): no sender label, so no form call, until the instance names the New session form's label
_FORM_MACHINES: list[str] = []     # ... and of form_machines (none until the instance names the machine whose token the form is allowed from)


def _cfg_names(key: str, default: list[str]) -> list[str]:
    """[project_agent] <key> as a list of strings: the section or the key absent → `default`; a bare string counts as one name; a section or value of
    another type reads as an empty list (no form call at all, never a wider rule than the file says). Read where it is used, so a reload applies."""
    sec = _cfg.get("project_agent")
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


def _form_call(machine: str, sender: str) -> bool:
    """Is this `post project-agent` the New session form's? Only when the `sender` label is in [project_agent] form_senders AND the machine its
    token proves (`machine`, never the body) is in form_machines: a label alone is not enough, since any token holder can type it."""
    return bool(machine) and bool(sender) and sender in _cfg_names("form_senders", _FORM_SENDERS) and machine in _cfg_names("form_machines", _FORM_MACHINES)


def _name_clash(name: str, key: str, pid: str, prefixes: list[str], reg: dict[str, Any]) -> str:
    """A name belongs to one project (every path, the form's too): the 409 text when another project's page map or pending list holds `name`, or when it
    starts with the longer name prefix of another project (team-alpha-docs-main under projects/alpha belongs to a project whose name is team-alpha-docs);
    "" when the name is free for the project `key` (id `pid`). Shared by `post project-agent` and `post project-agent-rename`."""
    fold = name.casefold()
    own_pre = {x.casefold() for x in prefixes}
    longest = max((len(x) for x in prefixes if fold.startswith(x.casefold() + "-")), default=0)
    for k2, e2 in sorted(reg.items()):
        if k2 == key or not isinstance(e2, dict): continue
        if any(str(n).casefold() == fold for n in (e2.get("agents") or {})):
            return f"{name} is already an agent of {k2}: a name belongs to one project"
        for q in _prj._name_prefixes(k2, e2, reg):
            if q.casefold() not in own_pre and len(q) > longest and fold.startswith(q.casefold() + "-"):
                return f"{name} starts with {q}-, the name of {k2}: an agent of {key} cannot take it; a name belongs to one project"
    for pid2, ent in _pr.entries().items():          # the record's lists: a project whose page is gone, or never was, still holds its agents
        if pid2 != pid and any(str(n).casefold() == fold for n in (ent.get("agents") or {})):
            return f"{name} is already an agent of {_prj.id_to_key(pid2, reg) or pid2}: a name belongs to one project"
    for pid2, ag2 in _prj._pending_all().items():
        if pid2 != pid and any(str(n).casefold() == fold for n in ag2):
            return f"{name} is already registered for {_prj.id_to_key(pid2, reg) or pid2}: a name belongs to one project"
    return ""


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
        if m["state"] == "failed":
            out["note"] = f"{out.get('note', '')} The page's agents block was not updated ({m['note']}); the record holds the agent, and the next change to this project writes the page again."
        elif m["state"] == "no-page":
            out["note"] = f"{out.get('note', '')} Its page {m['key']} is not in the page store, so no page was written."
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
    project, name, role, mandate, sender = (str(body.get(k) or "").strip() for k in ("project", "name", "role", "mandate", "sender"))
    front = body.get("front")
    if not (project and name and role and mandate and sender) or not isinstance(front, bool):
        return 400, {"error": "project, name, role, mandate and sender are required, and front is true (a front agent) or false (a background agent)"}
    if not _AGENT_NAME.fullmatch(name):
        return 400, {"error": "name = the session's name: letters, digits, . _ - (at most 64), starting with a letter or digit"}
    if not _AGENT_ROLE.fullmatch(role):
        return 400, {"error": "role = the name's suffix after the project's name (main, engineer, sessions): letters, digits, . _ - (at most 32)"}
    if "\n" in mandate or "\r" in mandate or len(mandate) > 600 or _MANDATE_CONTROL.search(mandate):
        return 400, {"error": "mandate = one line of at most 600 characters, with no control characters"}
    reg = _prj.with_made(_registry("projects"))        # a project just made through `post project` is here before the pages checkout has read its page
    recs = _prj.refs(project, reg) or [r for r in [_verbs.pageless_rec(project)] if r]          # a project with no page is the record's alone
    if not recs:
        return 404, {"error": f"no project {project!r}: an id (prj_<8 hex>), a page key or a bare slug of a page in the registry"}
    if len(recs) > 1:
        return 400, {"error": f"{project!r} is ambiguous: it names {' and '.join(r['key'] for r in recs)}; write the full key or the id"}
    rec = recs[0]; key = rec["key"]; entry = reg.get(key) or {}
    top = "/".join(key.split("/")[:2]); hub = str(entry.get("hub") or "")
    if key != top or hub:
        return 400, {"error": f"{key} is not a hub page: the agents map is kept on {hub or top}; list the agent there"}
    where = key or rec["id"]                                # how an answer names the project: its page, else its id
    nm = _anc.names()
    # The label path (see the docstring). The mark's time is the last make or re-list (`at`, else `on_purpose`); the keeper counts as live only
    # when the fleet holds a present session of that name (by_name is present-only: a retired name resolves to nothing).
    mark = _prj.marks().get(rec["id"]) or {}
    owed = _prj._pending_all().get(rec["id"], {})
    on_page = [n for n, a in rec["agents"].items() if not a.get("page_owed")]
    try:
        age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.strptime(str(mark.get("at") or mark.get("on_purpose") or ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)).total_seconds()
    except ValueError:
        age = float("inf")
    keeper_live = bool(rec["keeper"]) and rec["keeper"] in getattr(nm, "by_name", {})
    first = not rec["agents"] and not keeper_live and 0 <= age <= 3600 and bool(mark.get("by")) and mark.get("by") == sender
    listed_by = (_pr.entries().get(rec["id"]) or {}).get("agents") or {}          # the agents the record lists, with who listed each (a migrated agent names nobody)
    more = not first and bool(sender) and (bool(listed_by) and all(a.get("by") == sender for a in listed_by.values()) or (not on_page and bool(owed) and all(a.get("by") == sender for a in owed.values())))
    form = _form_call(machine, sender)         # the New session form: the label AND the machine its token proves (never the body's)
    if (first or more or form) and rec["retired"]:        # a label is the form's word: a retired project takes no agent from it (the keeper's and a front agent's session ids still may)
        return 403, {"error": f"{key} is retired (page status: {rec['status']}): change the page's status first"}
    if form and not rec["listed"]:
        return 403, {"error": f"refused: {key} is hidden, not listed. List it again first with `client.py post project-list --key {key}`, then add the agent"}
    if first or more or form:
        if len(sender) > 80 or any(ord(c) < 32 or ord(c) == 127 for c in sender):
            return 400, {"error": "sender = the caller's own label: one line of at most 80 characters"}
        listed_front = []
    else:
        if not _anc.is_id(sender):
            return 403, {"error": f"refused: sender {sender!r} is a name, and a name proves nothing. Send the asking session's id: its transcript id "
                                  "($CLAUDE_CODE_SESSION_ID, which Claude Code sets in every Bash command) or a cloud session's cse_ id"}
        sname = nm.get(sender, "")
        listed_front = sorted(n for n, a in rec["agents"].items() if a["front"] and not a.get("page_owed"))
        allowed = {rec["keeper"], *listed_front}
        allowed.discard("")
        if not sname and sender not in allowed:
            return 403, {"error": f"refused: {sender!r} is not a session in the fleet's heartbeat, so it names nobody; run this from the keeper's or a front agent's own session"}
        if not ({sender, sname} & allowed):
            return 403, {"error": f"refused: session {sname or sender!r} is neither the keeper ({rec['keeper'] or 'none'}) nor a front agent of {key} "
                                  f"({', '.join(listed_front) or 'none'}); one of them lists a new agent"}
    prefixes = [rec["keeper"]] if rec.get("pageless") else (_prj._name_prefixes(key, entry, reg) or [key.split("/")[-1]])      # the name, else the page's slug: an agent is always <project>-<role>
    if not any(name.startswith(p + "-") and len(name) > len(p) + 1 for p in prefixes):
        return 400, {"error": f"{name!r} does not start with the project's name: an agent of {where} is called {prefixes[0]}-<role>"}
    new = {"front": front, "role": role, "mandate_line": mandate}
    fold = name.casefold()
    clash = _name_clash(name, key, rec["id"], prefixes, reg)
    if clash:
        return 409, {"error": clash}
    listed_name = next((n for n, a in rec["agents"].items() if n.casefold() == fold and not a.get("page_owed")), None)     # names compare case-folded
    if listed_name is not None:
        name = str(listed_name)
        cur = rec["agents"][name]
        if (cur["front"], cur["mandate_line"]) == (front, mandate):          # the role is read from the name: the one asked for is no part of "the same"
            return 200, {"project": rec["id"], "key": key, "agent": {name: cur}, "page_owed": False, "page_yaml": "", "note": f"{name} is already listed on {where}: nothing changed"}
        return 409, {"error": f"{name} is already listed on {where} as {'front' if cur['front'] else 'background'} ({cur['role']}): {cur['mandate_line'][:120]!r}; "
                              "to change its mandate line use `client.py post project-agent-mandate`; to change its side, retire it, or rename it, then list it again"}
    name = next((n for n in _prj._pending_all().get(rec["id"], {}) if str(n).casefold() == fold), name)     # a pending entry under another spelling is the same agent
    pend = _prj.pending_entry(rec["id"], name)
    if pend and pend.get("by") != sender and (pend.get("front"), pend.get("role"), pend.get("mandate_line")) != (front, role, mandate):
        return 409, {"error": f"{name} was already registered for {where} by another session ({pend.get('by') or 'unknown'}) as "
                              f"{'front' if pend.get('front') else 'background'} ({pend.get('role')}): {str(pend.get('mandate_line'))[:120]!r}; "
                              "only that session changes it"}
    try:
        res = _verbs.agent_add(rec["id"], name, front, mandate, by=sender, io=_page_io(), mirror_now=False, pages=pages if pages is not None else {})       # the record first; the page's mirror follows, outside the lock
    except _verbs.VerbError as e:
        return e.status, {"error": e.message}
    except ValueError as e:
        return 503, {"error": f"the project record cannot be read or written right now, nothing was changed: {e}"}
    _projects_sync_safe(force=True)
    has_page = bool(res["key"])
    return 200, {"project": rec["id"], "key": key, "agent": {res["name"]: new}, "page_owed": False, "page_yaml": "", "_mirror": rec["id"] if has_page else "",
                 "note": f"Listed {res['name']} on {where} in the project record" + (f"; its page {key} gets the agents line from the record." if has_page else " (the project has no page).")
                 + (f" Note: {res['warning']}." if res.get("warning") else "")}


def _project_agent_mandate(machine: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """`client.py post project-agent-mandate <project> <name> --mandate "…" [--sender <session id>]`: change the mandate line of an agent already on the project's agents map (the record,
    project_verbs.agent_mandate), then the page's `agents:` block is written from it (the mirror, after _PROJECT_LOCK is released), so a later mirror write keeps the new line: the record is the
    authority and a page edit to the line is not read. Who: the project's keeper and its front agents, as `post project-agent` (`sender` is the asking session's id, never a name; no label
    path: the New session form lists agents, it does not rewrite their lines). The agent keeps its side (front or background), its place in the map and who listed it.
    Answers: 200 {project, key, agent: {name: {front, role, mandate_line}}, previous, mirror, note} (the same line again: 200, "nothing changed") · 400 a missing field, a bad name, a backslash in the line, an empty
    or over-long mandate, a control character or a backslash in it, an ambiguous slug, a page that is not a hub · 403 a name as sender, or a session that is neither the keeper nor a front agent · 404 unknown
    project, or `name` not listed on it (list it first with `post project-agent`) · 503 the record cannot be written. A mirror that cannot be written is told in the answer: the record is right."""
    project, name, mandate, sender = (str(body.get(k) or "").strip() for k in ("project", "name", "mandate", "sender"))
    if not (project and name and sender):
        return 400, {"error": "project, name and sender are required: the project, the listed agent's name and the asking session's id; the new line goes in `mandate`"}
    if not _AGENT_NAME.fullmatch(name):
        return 400, {"error": "name = the session's name: letters, digits, . _ - (at most 64), starting with a letter or digit"}
    if not mandate:
        return 400, {"error": "mandate is empty: give the agent's new line (one line of at most 600 characters, what it does); to take the agent off the map use `post project-agent-retire`"}
    if "\n" in mandate or "\r" in mandate or len(mandate) > 600 or _MANDATE_CONTROL.search(mandate):
        return 400, {"error": "mandate = one line of at most 600 characters, with no control characters"}
    if "\\" in mandate:
        return 400, {"error": "a mandate line cannot contain a backslash; write it without (the page's agents block could not be read back with one)"}
    pages = _verbs.preread(project, _page_io())          # the page of a project with no entry yet is read BEFORE the lock, as `post project-agent` does
    with _PROJECT_LOCK:
        reg = _prj.with_made(_registry("projects"))
        recs = _prj.refs(project, reg) or [r for r in [_verbs.pageless_rec(project)] if r]
        if not recs:
            return 404, {"error": f"no project {project!r}: an id (prj_<8 hex>), a page key or a bare slug of a page in the registry"}
        if len(recs) > 1:
            return 400, {"error": f"{project!r} is ambiguous: it names {' and '.join(r['key'] for r in recs)}; write the full key or the id"}
        rec = recs[0]; key = rec["key"]; entry = reg.get(key) or {}
        top = "/".join(key.split("/")[:2]); hub = str(entry.get("hub") or "")
        if key != top or hub:
            return 400, {"error": f"{key} is not a hub page: the agents map is kept on {hub or top}; change the line there"}
        if not _anc.is_id(sender):
            return 403, {"error": f"refused: sender {sender!r} is a name, and a name proves nothing. Send the asking session's id: its transcript id "
                                  "($CLAUDE_CODE_SESSION_ID, which Claude Code sets in every Bash command) or a cloud session's cse_ id"}
        nm = _anc.names(); sname = nm.get(sender, "")
        listed_front = sorted(n for n, a in rec["agents"].items() if a["front"] and not a.get("page_owed"))
        allowed = {rec["keeper"], *listed_front}; allowed.discard("")
        if not sname and sender not in allowed:
            return 403, {"error": f"refused: {sender!r} is not a session in the fleet's heartbeat, so it names nobody; run this from the keeper's or a front agent's own session"}
        if not ({sender, sname} & allowed):
            return 403, {"error": f"refused: session {sname or sender!r} is neither the keeper ({rec['keeper'] or 'none'}) nor a front agent of {key or rec['id']} "
                                  f"({', '.join(listed_front) or 'none'}); one of them changes an agent's mandate line"}
        where = key or rec["id"]
        try:
            res = _verbs.agent_mandate(rec["id"], name, mandate, by=sender, io=_page_io(), mirror_now=False, pages=pages)
        except _verbs.VerbError as e:
            return e.status, {"error": e.message}
        except ValueError as e:
            return 503, {"error": f"the project record cannot be read or written right now, nothing was changed: {e}"}
    _projects_sync_safe(force=True)
    m = _verbs.mirror(rec["id"], _page_io()) if key else {"state": "none", "key": "", "note": ""}
    role = _prj.role_of(res["name"], [rec["keeper"]] if rec.get("pageless") else (_prj._name_prefixes(key, entry, reg) or [key.split("/")[-1]]))
    tail = (f" The page's agents block was not updated ({m['note']}); the record holds the new line, and the next change to this project writes the page again." if m["state"] == "failed" else "")
    return 200, {"project": rec["id"], "key": key, "agent": {res["name"]: {"front": res["front"], "role": role, "mandate_line": res["mandate"]}}, "previous": res["previous"], "mirror": m,
                 "note": (f"{res['name']} on {where} already has this mandate line: nothing changed." if not res["changed"] and m["state"] in ("none", "unchanged") else
                          f"{res['name']} on {where} already had this mandate line in the project record; the page {key} was written from the record." if not res["changed"] and m["state"] == "written" else
                          f"{res['name']} on {where} already has this mandate line in the project record." if not res["changed"] else
                          f"Changed the mandate line of {res['name']} on {where} in the project record" + (f"; the page {key} gets it from the record." if key else " (the project has no page).")) + tail}


_RENAME_NOT_FORM = ("refused: only the web form may rename an agent's entry on a page: `sender` must be a label in [project_agent] form_senders "
                    "and the token must be a machine in form_machines")


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
    project, old, new = (str(body.get(k) or "").strip() for k in ("project", "old", "new"))
    sender = str(body.get("sender") or "").strip() or machine
    if not (project and old and new):
        return 400, {"error": "project, old and new are required: the project, the agent's name now and its new name"}
    if _LABEL_BAD(sender):
        return 400, {"error": "sender = the caller's own label: one line of at most 80 characters"}
    if not _form_call(machine, sender):
        return 403, {"error": _RENAME_NOT_FORM}
    for nm in (old, new):
        if not _AGENT_NAME.fullmatch(nm):
            return 400, {"error": "old and new = the session's name: letters, digits, . _ - (at most 64), starting with a letter or digit"}
    if old.casefold() == new.casefold():
        return 400, {"error": "old and new are the same name (names compare case-folded): nothing to rename"}
    reg = _prj.with_made(_registry("projects"))
    recs = _prj.refs(project, reg) or [r for r in [_verbs.pageless_rec(project)] if r]          # a project with no page is the record's alone
    if not recs:
        return 404, {"error": f"no project {project!r}: an id (prj_<8 hex>), a page key or a bare slug of a page in the registry"}
    if len(recs) > 1:
        return 400, {"error": f"{project!r} is ambiguous: it names {' and '.join(r['key'] for r in recs)}; write the full key or the id"}
    rec = recs[0]; key = rec["key"]; entry = reg.get(key) or {}
    top = "/".join(key.split("/")[:2]); hub = str(entry.get("hub") or "")
    if key != top or hub:
        return 400, {"error": f"{key} is not a hub page: the agents map is kept on {hub or top}; rename the agent there"}
    prefixes = [rec["keeper"]] if rec.get("pageless") else (_prj._name_prefixes(key, entry, reg) or [key.split("/")[-1]])
    if not any(new.startswith(p + "-") and len(new) > len(p) + 1 for p in prefixes):
        return 400, {"error": f"{new!r} does not start with the project's name: an agent of {key or rec['id']} is called {prefixes[0]}-<role>"}
    clash = _name_clash(new, key, rec["id"], prefixes, reg)
    if clash:
        return 409, {"error": clash}
    return rec, old, new, prefixes, reg, sender


def _project_agent_rename_write(rec: dict[str, Any], old: str, new: str, prefixes: list[str], reg: dict[str, Any], sender: str = "") -> tuple[int, dict[str, Any]]:
    """The second half of `post project-agent-rename`, outside _PROJECT_LOCK with the page key in _RENAMING: the verb renames the entry in the project's agents map
    (the record, atomically), then writes the page's mirror lines (project_verbs.agent_rename; see _project_agent_rename_checks's docstring for the answers). A mirror that
    cannot be written is told in the answer (`mirror`, and the note): the record is right and the next change to the project writes the page again."""
    key = rec["key"]; where = key or rec["id"]
    pend = next(((n, a) for n, a in _prj._pending_all().get(rec["id"], {}).items() if str(n).casefold() == new.casefold()), None)
    if pend and not any(str(n).casefold() == old.casefold() for n in rec["agents"]):
        return 409, {"error": f"{new} is already registered for {where} as a pending agent (by {pend[1].get('by') or 'unknown'}), its page line still owed: nothing was changed; "
                              "that entry is not this call's to change"}
    try:
        res = _verbs.agent_rename(rec["id"], old, new, by=sender, io=_page_io())
    except _verbs.VerbError as e:
        return e.status, {"error": e.message}
    except ValueError as e:
        return 503, {"error": f"the project record cannot be read or written right now, nothing was changed: {e}"}
    _projects_sync_safe(force=True)
    m = res["mirror"]
    tail = ("" if m["state"] in ("none", "unchanged", "written", "would-write", "retired") else
            f" The page's agents block was not updated ({m['note']}); the record is right and the next change to this project writes the page again.")
    if res["result"] == "already renamed":
        return 200, {"project": rec["id"], "key": key, "result": "already renamed", "old": old, "new": res["new"], "front": res["front"],
                     "role": _prj.role_of(res["new"], prefixes), "mandate": res["mandate"], "mirror": m, "note": "already renamed"}
    return 200, {"project": rec["id"], "key": key, "result": "renamed", "old": res["old"], "new": new, "front": res["front"], "role": _prj.role_of(new, prefixes), "mandate": res["mandate"], "mirror": m,
                 "note": f"Renamed {res['old']} to {new} on {where}: the entry in the project's agents map is renamed in place (same place in the map, same mandate)"
                         + (f", and the page {key} follows from the record." if key else " (the project has no page).") + tail}


_RETIRE_NOT_FORM = ("refused: only the web form may retire an agent: `sender` must be a label in [project_agent] form_senders "
                    "and the token must be a machine in form_machines")


def _project_agent_retire_checks(machine: str, body: dict[str, Any]) -> Any:   # -> (status, JSON) to answer, or (rec, name, sender) to go on with
    """The gate, the names and the project of `post project-agent-retire` (see _project_agent_retire)."""
    project, name = (str(body.get(k) or "").strip() for k in ("project", "name"))
    sender = str(body.get("sender") or "").strip() or machine
    if not (project and name):
        return 400, {"error": "project and name are required: the project and the retired agent's name"}
    if _LABEL_BAD(sender):
        return 400, {"error": "sender = the caller's own label: one line of at most 80 characters"}
    if not _form_call(machine, sender):
        return 403, {"error": _RETIRE_NOT_FORM}
    if not _AGENT_NAME.fullmatch(name):
        return 400, {"error": "name = the session's name: letters, digits, . _ - (at most 64), starting with a letter or digit"}
    reg = _prj.with_made(_registry("projects"))
    recs = _prj.refs(project, reg) or [r for r in [_verbs.pageless_rec(project)] if r]          # a project with no page is the record's alone
    if not recs:
        return 404, {"error": f"no project {project!r}: an id (prj_<8 hex>), a page key or a bare slug of a page in the registry"}
    if len(recs) > 1:
        return 400, {"error": f"{project!r} is ambiguous: it names {' and '.join(r['key'] for r in recs)}; write the full key or the id"}
    rec = recs[0]; key = rec["key"]; entry = reg.get(key) or {}
    top = "/".join(key.split("/")[:2]); hub = str(entry.get("hub") or "")
    if key != top or hub:
        return 400, {"error": f"{key} is not a hub page: the agents map is kept on {hub or top}; retire the agent there"}
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
        return 503, {"error": f"the project record cannot be read or written right now, nothing was changed: {e}"}
    _projects_sync_safe(force=True)
    m = res["mirror"]
    today = dt.datetime.now(_cfg.tz()).strftime("%Y-%m-%d")
    tail = ("" if m["state"] in ("none", "unchanged", "written", "would-write", "retired") else
            f" The page's agents block was not updated ({m['note']}); the record is right and the next change to this project writes the page again.")
    if res["result"] == "not listed":
        return 200, {"project": rec["id"], "key": key, "result": "not listed", "agent": name, "page_owed": False, "mirror": m,
                     "reason": f"{name} is not on {where}'s agents map and not pending in the record: nothing to remove.", "note": f"{name} is not listed on {where}: nothing to do."}
    if res["result"] == "dropped":
        return 200, {"project": rec["id"], "key": key, "result": "dropped", "agent": res["name"], "page_owed": False, "mirror": m,
                     "note": f"{res['name']} was only pending for {where}: dropped from the record, so no page update is owed for it.", **_archive_after(io, rec, None, today, sender)}
    return 200, {"project": rec["id"], "key": key, "result": "line removed", "agent": res["name"], "front": res["front"], "page_owed": False, "mirror": m,
                 "note": f"Took {res['name']} off {where}'s agents map in the project record" + (f"; the page {key} follows from the record, with a timeline line." if key else " (the project has no page).") + tail,
                 **_archive_after(io, rec, None, today, sender)}


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
_MANDATE_CONTROL = re.compile("[\\u0000-\\u001f\\u007f-\\u009f\\ufffe\\uffff]")      # control characters: a YAML reader refuses or misreads them on the page
PAGE_IO: Any = None             # tests put an object here with get(slug) -> (content, revision) and create(slug, content) -> (state, note); None = the instance's own (page_debt.page_io: the page files, or gbrain's CLI)
_LABEL_BAD = lambda s: len(s) > 80 or any(ord(c) < 32 or ord(c) == 127 for c in s)


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
    scope = str(params.get("scope") or "").strip().lower()
    q = str(params.get("q") or "").strip()
    if scope and scope != "all" and scope not in _prj.scopes():
        return 400, "text/plain", f"scope = {' | '.join(_prj.scopes())} | all"
    if len(q) > 200 or any(ord(c) < 32 for c in q):
        return 400, "text/plain", "q = a search text of one line, at most 200 characters"
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
    if not recs:
        return None, (404, {"error": f"no project {project!r}: an id (prj_<8 hex>), a page key or a bare slug of a page in the registry"})
    if len(recs) > 1:
        return None, (400, {"error": f"{project!r} is ambiguous: it names {' and '.join(r['key'] for r in recs)}; write the full key or the id"})
    return recs[0], None


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
        return 400, {"error": "scope and a name or a page key (projects/<slug> or infra/<slug>) are required"}
    if scope not in _prj.scopes():
        return 400, {"error": f"scope = {' | '.join(_prj.scopes())}"}
    key = ""
    if page and (legacy or ("://" not in page and not re.search(r"\s", page))):          # `key` is always a page key; `page` may be a link to another knowledge base
        key = page
        dirs = _cfg.page_dirs()
        top, _, slug = key.partition("/")
        if top not in dirs or not slug or (make_page and (not _prj.SLUG_RE.fullmatch(slug) or len(slug) > 60)):
            return 400, {"error": f"key = {' or '.join(d + '/<slug>' for d in dirs)}, one level, the slug lowercase letters, digits and dashes (at most 60): got {key[:80]!r}"}
    if len(title) > 120 or any(ord(c) < 32 or c in '"\\' for c in title):
        return 400, {"error": "title = one line of at most 120 characters, with no quotation marks or backslashes (the pages checkout's reader takes the frontmatter as it stands)"}
    if _LABEL_BAD(sender):
        return 400, {"error": "sender = the caller's own label: one line of at most 80 characters"}
    if key:
        title = title or _prj.slug_title(key)
        name = name or _prj.page_front(key, title, scope)["display_name"]
    exists = f"{key} already exists: list it again with `client.py post project-list --key {key}` (a hidden project keeps its page, agents and history)"
    if key and make_page:
        try:
            reg = _prj.with_made(_registry("projects"))
        except ValueError as e:
            return 503, {"error": f"the project record cannot be read or written right now, nothing was made: {e}"}
        if key in reg or any(k.startswith(key + "/") for k in reg):
            return 409, {"error": exists}
        kb = _brains.for_key(key)       # the copy of the brain that will hold the page ([[brains]]); a second brain that cannot be read is not looked at here
        brain = _cfg.path("paths", "brain") if kb.default else kb.path
        if (kb.default or not _brains.problem(kb)) and ((brain / f"{key}.md").exists() or (brain / key).exists()):
            return 409, {"error": exists}
    try:
        res = _verbs.create(name, scope, page, make_page=make_page, title=title, by=sender, io=_page_io() if key else None)
    except _verbs.VerbError as e:
        return e.status, {"error": (e.message if e.status != 409 or not key else f"{e.message}; {exists}").replace("the page store", _page_store())}
    except ValueError as e:
        return 503, {"error": f"the project record cannot be read or written right now, nothing was made: {e}"}
    pid = res["project"]; m = res["mirror"]
    _projects_sync_safe(force=True)
    rec, bad = _one_project(pid)
    if bad: return bad
    state = "ok" if m["state"] in ("written", "unchanged") else m["state"]
    note = (f"Made {name} ({pid}) in scope {scope}: its entry is in the project record and the project is listed" + (f"; its page {key} is written through {_page_store()}." if make_page and state == "ok" else
            f"; its page is {key}." if key else "; it has no page.") + f" Add the first agent with `client.py post project-agent {pid} {name}-main --role main --front --mandate \"…\"`.")
    if make_page and state != "ok":
        note += (f" The page {key} was not made ({m['note']}); the record holds the project." if state == "retired" else
                 f" The page {key} was not made ({m['note']}); the record is right, and the next change to the project makes it.")
    return 200, {"project": rec, "created": True, "page": {"key": key, "state": state, "display_name": name}, "page_yaml": "", "mirror": m, "note": note}


def _project_list(machine: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """`client.py post project-list --key <id | key | slug> [--scope <s>] [--sender <label>]`: list a hidden project again (it keeps its page, agents
    and history; it was never deleted). Marks it listed on purpose, and sets its scope when `scope` is given. Said again it changes nothing.
    A sub-page is refused (400), with the page above it to list. → (status, {project, changed, note})."""
    project = str(body.get("key") or body.get("project") or "").strip()
    scope = str(body.get("scope") or "").strip().lower()
    sender = str(body.get("sender") or "").strip() or machine
    if not project:
        return 400, {"error": "key = the project: its id (prj_<8 hex>), its page key or its bare slug"}
    if scope and scope not in _prj.scopes():
        return 400, {"error": f"scope = {' | '.join(_prj.scopes())}"}
    if _LABEL_BAD(sender):
        return 400, {"error": "sender = the caller's own label: one line of at most 80 characters"}
    rec, bad = _one_project(project)
    if bad: return bad
    if rec["sub_page"]:
        e = _registry("projects").get(rec["key"]) or {}
        parts = rec["key"].split("/")
        up = str(e.get("hub") or "") or next(("/".join(parts[:n]) for n in range(2, len(parts)) if "/".join(parts[:n]) in _registry("projects")), "")
        return 400, {"error": f"{rec['key']} is a sub-page of {up or 'a project'} (or has a hub: line), and a sub-page is never listed: list {up or 'the project above it'}"}
    if rec["retired"]:
        return 400, {"error": f"{rec['key']} is retired (page status: {rec['status']}): change the page's status first"}
    if rec["type"] == "note":
        return 400, {"error": f"{rec['key']} is a `type: note` page, and a note is never listed; a project page has `type: project`"}
    try:
        with _PROJECT_LOCK:
            before = (_prj.marks().get(rec["id"]) or {})
            now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            changed = not before.get("on_purpose") or bool(scope and before.get("scope") != scope)
            # every call renews `at` and `by`: the first-agent window (project-agent) runs from the latest list, by the latest label
            _prj.set_mark(rec["id"], on_purpose=before.get("on_purpose") or now, at=now, by=sender, **({"scope": scope} if scope else {}))
    except ValueError as e:
        return 503, {"error": f"the project record cannot be read or written right now, nothing was changed: {e}"}
    _projects_sync_safe(force=True)
    rec, bad = _one_project(rec["id"])
    if bad: return bad
    return 200, {"project": rec, "changed": changed, "note": f"{rec['key']} is listed on purpose from now on." if changed else f"{rec['key']} was already listed on purpose: nothing changed (its first-agent window is renewed)."}
