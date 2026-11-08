"""project_archive.py — a project is archived when it has no agent and no open item.

Two moments, one rule (the state: the project's page lists no agent, none is pending in the project record, and no open item is the project's):

1. The retire. Sala retires a session and tells stackshot through `post project-agent-retire` (server._project_agent_retire), which takes the agent off the
   project's agents map in the record (project_verbs.agent_retire; the page's block follows as a mirror). `after_retire` then looks at the project: no agent
   left and no open item → the project is archived by the verb (project_verbs.archive: the record's status first, then the page's `status:` line). No agent
   left but open items → the project is put on the wait list (`<state>/archive-wait.json`, key → {since, by}; the key is the project's id when it has no
   page) and stays as it is. A verb that cannot run puts it on the same list, so the sweep tries again. A project whose record has no agents field at all was
   never staffed and is never archived this way.
2. The sweep. `sweep` (server._archive_tick, the ten-minute set) looks at the projects on the wait list only: the open items are counted once for all of
   them, and a project with none left is archived, whether its items were completed or handed to another project. A project that has an agent
   again (or a pending one), that is archived already, or that is gone leaves the list without a write. A write that fails stays
   on the list for the next sweep. So the rule holds whichever event came last, and a repeat does nothing: a project on no list is never touched, which is
   why a project that never had an agent is not archived by a sweep.

The open items of a project are the ones of its own page, of the pages under it and of the pages that name it as their hub (an item on hold counts as open).
A project whose status already is archived (for one with no entry in the record yet: whose page's `status:` is a retired word, the registry's retired_statuses) is left alone.
When "archived" is not among the configured retired_statuses the page would not move to the Projects page's Archived group, so nothing is written and the answer says why.
A retire that found the agent on no list ("not listed") never archives: the project's agent set did not change.

`tools/archive_empty_projects.py` lists the projects that meet the rule now (dry run; `--apply` archives them).

The page store is the caller's: an object with get(slug) -> (text, revision), put(slug, text, revision) and add_timeline(...), as server._page_io() gives."""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg
from stackshot.model import item_project as _iproj
from stackshot.router import page_debt as _page_debt
from stackshot.projects import pages as _pages
from stackshot.projects import project_registry as _pr
from stackshot.projects import project_verbs as _verbs
from stackshot.projects import projects as _prj
from stackshot.core import readonly as _ro

STATUS = "archived"


def open_items_by_key(keys, reg: dict | None = None) -> dict[str, list[str]]:
    """{key: the ids (letter + number) of its open items} for each of `keys`, from one read of the store: every item that is not completed whose
    `metadata.project` is the page, a page under it or a page that names it as its hub (the same reach as projects.recent_items, which lists a project by
    the items it has)."""
    reg = _prj.registry() if reg is None else reg
    want = set(keys); out: dict[str, list[str]] = {k: [] for k in want}
    first = (_cfg.page_dirs() or ["projects"])[0]
    try: dirs = sorted(d for d in _prj._store().iterdir() if d.is_dir() and len(d.name) == 1 and d.name.isalpha())
    except OSError: dirs = []
    for d in dirs:
        for p in d.glob("*.json"):
            if p.name.startswith(".") or not p.stem.isdigit(): continue
            try: it = json.loads(p.read_text(encoding="utf-8"))
            except Exception: continue
            if not isinstance(it, dict) or it.get("status") == "completed": continue
            try: v = str(_iproj.key_of(it.get("metadata") or {}) or "").strip().strip("/")      # read through the item's project id
            except AttributeError: continue
            if v.endswith(".md"): v = v[:-3]
            if not v: continue
            if "/" not in v and not _prj.is_id(v): v = first + "/" + v      # a bare slug is a page of the first dir; a project's id (a project with no page) is its own key
            parts = v.split("/")
            ks = [v] + [k for k in ("/".join(parts[:n]) for n in range(len(parts) - 1, 1, -1)) if k in reg]
            for k in list(ks):          # a page with a hub: line counts for its hub too
                h = str((reg.get(k) or {}).get("hub") or "").strip() if isinstance(reg.get(k), dict) else ""
                if h and h in reg and h not in ks: ks.append(h)
            for k in ks:
                if k in want: out[k].append(f"{d.name}{p.stem}")
    return {k: sorted(v, key=lambda g: (g[0], int(g[1:]))) for k, v in out.items()}


def open_items(key: str, reg: dict | None = None) -> list[str]:
    """The ids of the open items of project `key` (open_items_by_key for one)."""
    return open_items_by_key([key], reg)[key]


def set_status(content: str, status: str = STATUS) -> tuple[str | None, str]:
    """A page's text with its frontmatter `status:` set to `status`, and nothing else → (new_text, "") or (None, why). The `status:` line is replaced in
    place; a page with none gets the line just before the frontmatter's closing `---`. Refused (None, why) when the page has no closed frontmatter, has
    the key more than once, or the edited page does not read back with that status and every other field as it was."""
    lines = str(content).split("\n")
    if not lines or lines[0].strip() != "---": return None, "the page has no frontmatter"
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None: return None, "the page's frontmatter is not closed"
    hits = [i for i in range(1, end) if re.match(r"^status:(\s|$)", lines[i])]
    if len(hits) > 1: return None, "the page has more than one status: line"
    if hits:
        j = hits[0] + 1         # a status value that goes on over the lines below it (a folded scalar) would leave its tail behind
        if j < end and lines[j][:1] in (" ", "\t") and lines[j].strip(): return None, "the page's status: line continues on the lines below it"
        lines[hits[0]] = f"status: {status}"
    else:
        lines.insert(end, f"status: {status}")
    out = "\n".join(lines)
    fm0, fm1 = _pages.frontmatter_text(content), _pages.frontmatter_text(out)
    if str(fm1.get("status") or "").strip().lower() != status or {k: v for k, v in fm0.items() if k != "status"} != {k: v for k, v in fm1.items() if k != "status"}:
        return None, "the edited page does not read back as the same page with only its status changed"
    return out, ""


def verdict(content: str, pending_left: int, items: list[str], need_map: bool = True) -> tuple[str, str]:
    """What the rule says of a project now → (word, why). `content` is its page, `pending_left` the agents still pending for it in stackshot's record, `items` its
    open items (open_items). The words: "archive" (no agent, no open item) · "wait" (no agent, open items: it archives when none is left) · "staffed" (the page
    lists an agent or one is pending) · "never" (the page has no agents: key at all, so it was never staffed and a retire or a pending-only drop does not archive it; `need_map` False, for
    the dry-run tool's --all, skips this) · "done" (the page's status already is a retired word) · "unset" ('archived' is not among the retired_statuses)."""
    fm = _pages.frontmatter_text(content)
    status = str(fm.get("status") or "").strip().lower()
    if status in _prj.retired_statuses(): return "done", f"already {status}"
    if STATUS not in _prj.retired_statuses(): return "unset", f"'{STATUS}' is not among the configured retired_statuses, so the page would not move to the Archived group"
    if need_map and "agents" not in fm: return "never", "the page never had an agents: map"
    flat, _back = _pages.split_agents(fm.get("agents"))
    if flat: return "staffed", f"{len(flat)} agent(s) on the page"
    if pending_left: return "staffed", f"{pending_left} agent(s) pending"
    if items: return "wait", f"{len(items)} open item(s): " + ", ".join(items[:5]) + (" …" if len(items) > 5 else "")
    return "archive", ""


def verdict_record(view: dict, pending_left: int, items: list[str], need_map: bool = True) -> tuple[str, str]:
    """`verdict` for a project the record holds: `view` is its project_registry view. The same words. "never" is a record with no agents field at all (the project was never staffed)."""
    if view["archived"]: return "done", "already archived"
    if STATUS not in _prj.retired_statuses(): return "unset", f"'{STATUS}' is not among the configured retired_statuses, so the page would not move to the Archived group"
    if need_map and "agents" not in (_pr.entries().get(view["id"]) or {}): return "never", "the project never had an agents map"
    if view["agents"]: return "staffed", f"{len(view['agents'])} agent(s) on the project"
    if pending_left: return "staffed", f"{pending_left} agent(s) pending"
    if items: return "wait", f"{len(items)} open item(s): " + ", ".join(items[:5]) + (" …" if len(items) > 5 else "")
    return "archive", ""


def archive_page(io: Any, key: str, today: str, sender: str, why: str = "its last agent was retired") -> tuple[bool, str]:
    """Archive the project whose page is `key` (or whose id it is): the record's status first, then the page's `status:` line and a timeline line, through the project verb
    (project_verbs.archive) → (True, "") or (False, why not). The record is right as soon as the verb returns; a page that could not be written is told in the note, with the project
    archived all the same (the page is written again by the next verb on the project). Never raises for a store that refuses; the caller's retire has already succeeded, so a failure
    here is told in the answer, not an error of the call."""
    try:
        res = _verbs.archive(key, by=sender, how="made", why=why, io=io)
    except _verbs.VerbError as e:
        return False, e.message
    m = res["mirror"]
    if m["state"] == "failed": return True, f"the record says archived, but the page was not updated ({m['note']})"
    if m["state"] == "no-page": return True, f"the record says archived; its page {m['key']} is not in the page store"
    return True, ""


# ----------------------------------------------------------------------------- the wait list
_LOCK = threading.Lock()


def wait_path() -> Path: return _cfg.state("archive-wait.json")


def waiting() -> dict[str, dict]:
    """The wait list: {project page key: {"since": date, "by": who}} of the projects that have no agent and wait for their open items to go ({} when none)."""
    try: d = json.loads(wait_path().read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}
    return {str(k): (v if isinstance(v, dict) else {}) for k, v in d.items()} if isinstance(d, dict) else {}


def _write_wait(d: dict) -> None:
    _ro.guard("archive wait list")
    p = wait_path(); p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".archive-wait-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f: json.dump(d, f, indent=1, sort_keys=True)
        os.replace(tmp, p)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def _change_wait(add: dict | None = None, drop: tuple | list = ()) -> None:
    with _LOCK:
        d = waiting(); before = json.dumps(d, sort_keys=True)
        for k in drop: d.pop(k, None)
        for k, v in (add or {}).items(): d.setdefault(k, v)
        if json.dumps(d, sort_keys=True) != before: _write_wait(d)


# ----------------------------------------------------------------------------- the two moments
def after_retire(io: Any, rec: dict, content: str | None, today: str, sender: str, pending_left: int, reg: dict | None = None) -> dict:
    """What `post project-agent-retire` does once an agent is off the project's agents map → {"archived": bool, "archive_note": str}. The rule is applied to the record (the retire has made the
    project's entry): archived at once, or put on the wait list while open items remain. `content` (the page as the retire's read back showed it) is no longer needed and is ignored."""
    pid = rec["id"]; key = rec.get("key") or pid
    view = _pr.resolve(pid)
    if view is None: return {"archived": False, "archive_note": "not checked for archiving: the project is not in the record"}
    word, why = verdict_record(view, pending_left, open_items(key, reg))
    if word == "wait":
        _change_wait(add={key: {"since": today, "by": sender}})
        return {"archived": False, "archive_note": f"not archived yet: {why}; it is archived once none is left"}
    if word != "archive": return {"archived": False, "archive_note": f"not archived: {why}"}
    done, note = archive_page(io, pid, today, sender)
    if not done:        # the verb could not run: the sweep tries again (the project still meets the rule, so it is archived then, or leaves the list if that changed)
        _change_wait(add={key: {"since": today, "by": sender}})
        return {"archived": False, "archive_note": f"not archived yet: {note}; the ten-minute sweep tries again"}
    _change_wait(drop=[key])
    return {"archived": True, "archive_note": f"{key} archived: its last agent was retired and it has no open item" + (f" ({note})" if note else "")}


def sweep(io: Any, today: str, reg: dict, pending: dict | None = None) -> list[tuple[str, str]]:
    """One pass over the wait list → [(project key, what happened)]. The open items of all the waiting projects are counted in one read; a project with
    none left is archived (the record read again first: the rule is applied to the project as it is now), one with an agent again, or archived or gone,
    leaves the list, one still holding items stays. Idempotent: a second pass over the same state does nothing. `pending` is the record's pending agents by
    project id (projects._pending_all()). A project with no entry in the record yet (on the list from before the record held projects) is judged by its page, as it was,
    and archived through the same verb."""
    wait = waiting()
    if not wait: return []
    pending = _prj._pending_all() if pending is None else pending
    items = open_items_by_key(list(wait), reg); out: list[tuple[str, str]] = []
    for key, w in sorted(wait.items()):
        view = _pr.resolve(key)
        if view is not None:
            word, why = verdict_record(view, len(pending.get(view["id"], {})), items.get(key, []))
        else:
            entry = reg.get(key)
            if not isinstance(entry, dict):
                _change_wait(drop=[key]); out.append((key, "left the list: no such page")); continue
            content, rev = io.get(key)
            if content is None or not rev:
                out.append((key, "page not read: kept")); continue
            word, why = verdict(content, len(pending.get(entry.get("id") or "", {})), items.get(key, []))
        if word == "wait": out.append((key, f"waits: {why}")); continue
        if word != "archive":
            _change_wait(drop=[key]); out.append((key, f"left the list: {why}")); continue
        done, note = archive_page(io, key, today, str(w.get("by") or "stackshot"), "its last agent was retired and its open items are gone")
        if not done: out.append((key, f"not archived: {note}: kept")); continue
        _change_wait(drop=[key]); out.append((key, "archived" + (f" ({note})" if note else "")))
    return out
