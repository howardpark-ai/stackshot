"""keeper.py — a project's keeper as a mark on one of its agents (readers only: nothing here writes a mark).

The keeper is the agent that keeps a project's pages current and hears the notices that fall to the project. It is a duty of one agent of the project, not
a separate name. Two places can mark it:

    the project record      an agent entry of a project's `agents` may carry `"keeper": true` (at most one per project: a second flag is ignored and reported)
    the page                one optional flat frontmatter line `keeper: <agent name>`, beside `display-name:` (never inside the `agents:` map, so `split_agents`
                            is unchanged). It counts only when the name is an agent on that page's own `agents:` map; otherwise it is ignored and reported

With no mark, the keeper is derived by the rule the router already uses for a project's notices (router_live.stand_in): the project's builder (a background agent whose
mandate says it builds), else its -main agent (anchors.fallback_main). A page that lists no agent of its own, or of its hub, has no derived keeper: the session its
old fields name (a one-session page's name line, a sub-page's `agent:`) stays the keeper, as before. So does a page with a `display-name:` line of its own and no agents of
its own (a sub-page or a hub-linked page that names itself): derivation reaches only the pages that name nobody or list agents themselves. A retired project (archived,
done, closed ...) with no mark has no keeper at all: both fields are empty.

What a registry row gains (pages.cmd_registry; project_registry.apply lays the record over it):

    keeper_agent      the keeper agent: the marked agent, else the derived one, else the session the old fields name ("" when none)
    keeper_source     "mark" | "derived" | "legacy" ("" when there is no keeper): legacy = no mark, and the old fields (`display-name:`, `agent:`) name the keeper
    keeper_problems   (only when there are some) one line for each mark that was ignored
    session, role     with a mark: the marked agent and the role "mark" (a sub-page under it: the same agent, role "inherited"); `legacy_session` and `legacy_role`
                      then hold what they were. With no mark both keep exactly the value the page's old fields give

An unnamed sub-page inherits the keeper of the nearest page above it, as it always did.

Stdlib only at load; router_live and anchors (and projects, for the retired words) are imported lazily inside the functions that derive or read the status, never at load."""
from __future__ import annotations

import sys

KEY = "keeper"                  # the page's flat line, and the record's flag on an agent entry
MARK = "mark"                   # the registry role of a row whose `session` is the agent its page (or its record entry) marks
SOURCES = ("mark", "derived", "legacy")
_UNMARKED = ("agent", "inherited")      # registry roles that are not a page's own name line


def record_mark(agents) -> tuple[str, list]:
    """(the marked agent, problems) of a project record entry's `agents` ({name: {front, mandate_line, keeper?}}). The first agent listed with `keeper: true` is the
    mark; a second flag, and a flag that is neither true nor false, are ignored and each gives one problem line. Never raises."""
    name, problems = "", []
    if not isinstance(agents, dict):
        return "", []
    for n, a in agents.items():
        if not isinstance(a, dict) or KEY not in a or a[KEY] is None or a[KEY] is False:      # `is`: 0, 0.0, "" and "no" equal False or are falsy, and are problems
            continue
        if a[KEY] is not True:
            problems.append(f"agent {n}: `keeper` is {a[KEY]!r}, not true or false; ignored")
        elif name:
            problems.append(f"agent {n} is also flagged keeper; only the first flagged agent, {name}, is the keeper, so this flag is ignored")
        else:
            name = str(n)
    return name, problems


def page_mark(fm, listed) -> tuple[str, list]:
    """(the marked agent, problems) of a page's frontmatter `fm`: its `keeper:` line, when the name is one of `listed` (the page's own flat agents map). A line that names
    no agent of the page, or is not one name, is ignored and gives one problem line; no line gives ("", []). Never raises."""
    v = fm.get(KEY) if isinstance(fm, dict) else None
    if v is None:
        return "", []
    if not isinstance(v, str):
        return "", ["`keeper:` is not one agent name; ignored"]
    v = v.strip()
    if not v:
        return "", []
    if v not in (listed or {}):
        return "", [f"`keeper: {v}` names no agent on the page's `agents:` map; ignored"]
    return v, []


def row_mark(row) -> str:
    """The agent a registry row itself marks ("" when none): its `session` when its role is "mark" and the agent is on the row's `agents`. A sub-page that only inherits a mark has role "inherited" and marks nothing."""
    if not isinstance(row, dict) or row.get("role") != MARK:
        return ""
    s = str(row.get("session") or "")
    return s if s and s in (row.get("agents") or {}) else ""


def names_of(row) -> set:
    """Every session name a registry row counts as its keeper by an old or a new rule: the `session` (the mark, else the page's own name line or `agent:`), and the `legacy_session` a mark
    took the place of. What a session keeps (pages.keeper_pages, keepers_any) is read from this."""
    if not isinstance(row, dict):
        return set()
    return {s for s in (str(row.get("session") or ""), str(row.get("legacy_session") or "")) if s}


def name_line(row) -> tuple[str, str]:
    """(session, role) of a registry row as its old fields give them: with a mark on it, the `legacy_session` and `legacy_role` the mark took the place of; else the row's own two."""
    if not isinstance(row, dict):
        return "", ""
    if "legacy_session" in row or "legacy_role" in row or row.get("role") == MARK:
        return str(row.get("legacy_session") or ""), str(row.get("legacy_role") or "")
    return str(row.get("session") or ""), str(row.get("role") or "")


def above(key: str, reg: dict) -> str:
    """The page an unnamed sub-page `key` inherits its keeper from: the nearest page above it in `reg` with a keeper that is not an `agent:` line (pages._hub_keeper's rule, read from the registry's rows)."""
    parts = key.split("/")
    for i in range(len(parts) - 1, 1, -1):
        p = "/".join(parts[:i])
        r = reg.get(p)
        if isinstance(r, dict) and str(r.get("session") or "") and r.get("role") != "agent":
            return p
    return ""


def _lists_agents(key: str, reg: dict) -> bool:
    """Does the project's page, or its hub's, list an agent (router_live.agent_root: the page that serves this key)? A one-session page does not: its keeper is its name line."""
    from stackshot.router import router_live as _rl
    root = "/".join(key.strip("/").split("/")[:2])
    r = reg.get(_rl.agent_root(root, reg)) or {}
    return bool(r.get("agents"))


def derive(key: str, reg: dict) -> str:
    """The project's derived keeper: its builder, else its -main agent (router_live.stand_in_of, the rule the router and telling use for its notices); "" when the project lists no agent
    (a one-session page) or when no session can be named. Never raises."""
    try:
        if not _lists_agents(key, reg):
            return ""
        from stackshot.router import router_live as _rl
        return _rl.stand_in_of(key, reg)
    except Exception as e:  # noqa: BLE001 — the registry's rebuild never stops for a keeper it cannot derive
        print(f"keeper: no derived keeper for {key} ({type(e).__name__}: {e})", file=sys.stderr, flush=True)
        return ""


def retired(key: str, reg: dict) -> bool:
    """Is the project the page `key` belongs to retired (its top-level page's `status:` is one of [project_scopes] retired_statuses: archived, done, closed ...)?"""
    top = reg.get("/".join(key.split("/")[:2]))
    if not isinstance(top, dict):
        return False
    from stackshot.projects import projects as _p
    return _p.page_status(top) in _p.retired_statuses()


def fields(key: str, reg: dict, _seen: tuple = ()) -> dict:
    """{"keeper_agent", "keeper_source"} of the page `key` of the registry `reg` (rows as pages.cmd_registry and project_registry.apply leave them), by the order:
      1. a mark (the row's own, or the one a sub-page inherits): "mark";
      2. a retired project with no mark: no keeper, two empty strings (it has no agent to derive and its name line is no keeper any more);
      3. an unnamed sub-page: the keeper of the page above it; a sub-page an agent keeps (`agent:`): that agent, "legacy";
      4. a page that has its own name line (`display-name:`) and lists no agent of its own (a sub-page or a hub-linked page that names itself): that name, "legacy". Such a page
         is its own keeper by its old line, and the hub's builder does not take it over;
      5. otherwise the derived keeper of a project that lists agents (its own, or its hub's): "derived";
      6. otherwise the session the old fields name: "legacy". A row with none has two empty strings."""
    row = reg.get(key) if isinstance(reg.get(key), dict) else {}
    role = str(row.get("role") or ""); who = str(row.get("session") or "")
    if role == MARK and who:
        return {"keeper_agent": who, "keeper_source": "mark"}
    if retired(key, reg):
        return {"keeper_agent": "", "keeper_source": ""}
    if role == "inherited" and key not in _seen:
        up = above(key, reg)
        if up:
            return fields(up, reg, _seen + (key,))
    if role == "agent" and who:                        # a sub-page an agent keeps as its own working document: that agent, as before
        return {"keeper_agent": who, "keeper_source": "legacy"}
    if role == "name" and who and not row.get("agents"):     # its own name line and no agents of its own: the old line stays (the page does not fall to its hub's builder)
        return {"keeper_agent": who, "keeper_source": "legacy"}
    got = derive(key, reg)
    if got:
        return {"keeper_agent": got, "keeper_source": "derived"}
    if who:
        return {"keeper_agent": who, "keeper_source": "legacy"}
    return {"keeper_agent": "", "keeper_source": ""}
