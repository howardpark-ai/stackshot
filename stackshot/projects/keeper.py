"""keeper.py — a project's keeper as a mark on one of its agents (the readers, and the pure helpers the verbs and the audit's keeper debts use: nothing here writes a mark).

The keeper is the agent that keeps a project's pages current and hears the notices that fall to the project. It is a duty of one agent of the project, not
a separate name. Three places can mark it:

    the project record      an agent entry of a project's `agents` may carry `"keeper": true` (at most one per project: a second flag is ignored and reported)
    the page                one optional flat frontmatter line `keeper: <agent name>`, beside `display-name:` (never inside the `agents:` map, so `split_agents`
                            is unchanged). It counts only when the name is an agent on that page's own `agents:` map; otherwise it is ignored and reported
    a sub-page's own mark   the entry of the project the sub-page sits under may hold `"page_keepers": {<sub-page key>: <agent name>}` (project_registry.apply lays it). The agent need not be on
                            that project's map: any agent a project lists will do (a mark naming nobody listed is ignored and reported). An empty name hands the page back to the keeper above it

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

An unnamed sub-page inherits the keeper of the nearest page above it, as it always did. A sub-page with its own mark keeps the registry role it had ("agent": a page an agent keeps as its own working
document, which is the role every reader of such a page reads) and its row says `page_mark: true`, so `fields` answers "mark" for it; the sub-pages under it do not inherit from it, as they never did
from an `agent:` page.

The verbs (project_verbs.py) write the mark: `agent_add` marks a project's first agent, `agent_retire` and `agent_rename` move it, `keeper` moves it on purpose. `successor` names the agent a
retired keeper's mark moves to, and `problems_of` reads what is wrong with a mark (registry_report.keeper_debts turns it into the four debts the registry check carries).

Stdlib only at load; router_live and anchors (and projects, for the retired words) are imported lazily inside the functions that derive or read the status, never at load."""
from __future__ import annotations

import re
import sys

KEY = "keeper"                  # the page's flat line, and the record's flag on an agent entry
PAGES = "page_keepers"          # the record entry's map of the sub-pages under it that carry a mark of their own: {sub-page key: agent name, or "" for "follows the keeper above"}
PAGE_MARK = "page_mark"         # the registry row's flag: its keeper (`session`, role "agent") was named by such a mark, not by the page's `agent:` line
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


def marked(key: str, reg: dict, _seen: tuple = ()) -> str:
    """The agent the page `key` marks as its keeper, or inherits as a mark from the page above it ("" when no mark reaches it): a row whose role is "mark", or a sub-page that only inherits one.
    Reads the rows' own fields and nothing else, so it can run while the registry is being built (router_live.stand_in_of calls it)."""
    row = reg.get(key) if isinstance(reg, dict) else None
    if not isinstance(row, dict):
        return ""
    who = str(row.get("session") or "")
    if row.get("role") == MARK and who:
        return who
    if row.get("role") == "inherited" and key not in _seen:
        up = above(key, reg)
        if up:
            return marked(up, reg, _seen + (key,))
    return ""


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
      1. a mark (the row's own, the one a sub-page inherits, or a sub-page's own mark of the record: `page_mark`): "mark";
      2. a retired project with no mark: no keeper, two empty strings (it has no agent to derive and its name line is no keeper any more);
      3. an unnamed sub-page: the keeper of the page above it; a sub-page an agent keeps (`agent:`): that agent, "legacy";
      4. a page that has its own name line (`display-name:`) and lists no agent of its own (a sub-page or a hub-linked page that names itself): that name, "legacy". Such a page
         is its own keeper by its old line, and the hub's builder does not take it over;
      5. otherwise the derived keeper of a project that lists agents (its own, or its hub's): "derived";
      6. otherwise the session the old fields name: "legacy". A row with none has two empty strings."""
    row = reg.get(key) if isinstance(reg.get(key), dict) else {}
    role = str(row.get("role") or ""); who = str(row.get("session") or "")
    if (role == MARK or row.get(PAGE_MARK) is True) and who:
        return {"keeper_agent": who, "keeper_source": "mark"}
    up = above(key, reg) if role == "inherited" and key not in _seen else ""
    above_got = fields(up, reg, _seen + (key,)) if up else None      # an unnamed sub-page takes the mark above it, in a retired project too (a mark is read even there)
    if above_got and above_got["keeper_source"] == "mark":
        return above_got
    if retired(key, reg):
        return {"keeper_agent": "", "keeper_source": ""}
    if above_got:
        return above_got
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


# ----------------------------------------------------------------------------- what the verbs and the debts need
def successor(agents) -> str:
    """The agent a keeper mark moves to when its agent leaves `agents` ({name: {front, mandate_line}}, the record's map as it is without the leaver): the project's builder (the first background agent whose mandate says
    it builds, anchors.BUILDER, class 0 "build" before class 1), else its -main agent (the front agent whose name ends in -main, else the first front agent: anchors.main_of); "" when neither exists (no agent, or
    background agents that build nothing). The same two steps, in the same order, as the derivation of an unmarked project (derive), read from the entry's own map. Never raises."""
    try:
        if not isinstance(agents, dict):
            return ""
        from stackshot.anchors import anchors as _anc
        back = {str(n): str(a.get("mandate_line") or "") for n, a in agents.items() if isinstance(a, dict) and not a.get("front", True)}
        hits = [(0 if re.search(r"\bbuild", m, re.I) else 1, i, k) for i, (k, m) in enumerate(back.items()) if _anc.BUILDER.search(m)]
        if hits:
            return min(hits)[2]
        front = [str(n) for n, a in agents.items() if isinstance(a, dict) and a.get("front", True)]
        return next((n for n in front if n.endswith("-main")), front[0] if front else "")
    except Exception:  # noqa: BLE001
        return ""


def effective_mark(agents, page_row=None) -> str:
    """The agent a project marks as its keeper, as the overlay lays it: the record's flagged agent, else the agent the page's own `keeper:` line names when that agent is on `agents` ("" when none). `page_row` = the
    project's raw page row (a page-only registry row, with role "mark" when the line names a listed agent of the page)."""
    got, _p = record_mark(agents)
    if got:
        return got
    pm = row_mark(page_row)
    return pm if pm and isinstance(agents, dict) and pm in agents else ""


def unlisted_lines(problems) -> list:
    """The lines of a page row's `keeper_problems` that say a `keeper:` line names an agent the page does not list (page_mark's own words)."""
    return [str(x) for x in (problems or []) if "names no agent" in str(x)]


def problems_of(agents, page_row=None, former=()) -> list:
    """(kind, text) for each way the mark of one project is wrong, kinds as registry_report names them:
      keeper-not-listed   a mark names an agent the record does not list (a page `keeper:` line the record's map lacks, or the page's own map lacks), or a flag that is neither true nor false
      keeper-two-marks    two agents flagged in the record, or the page's `keeper:` line and the record's flag name different agents
      keeper-retired      the mark (a page's line the record no longer lists, or a flag) names an agent in the entry's `former_agents`: it was taken off the map on purpose, and the mark still names it
    `agents` = the record's map, `page_row` = the project's raw page row, `former` = the entry's `former_agents`. [] for a project with no mark and no problem. Never raises."""
    out: list = []
    try:
        former_l = {str(x).casefold() for x in (former or ())}
        got, probs = record_mark(agents)
        for t in probs:
            out.append(("keeper-two-marks" if "also flagged" in t else "keeper-not-listed", t))
        pm = row_mark(page_row)
        listed = agents if isinstance(agents, dict) else {}
        if pm and pm not in listed:
            kind = "keeper-retired" if pm.casefold() in former_l else "keeper-not-listed"
            out.append((kind, f"the page's `keeper: {pm}` names an agent the project record does not list"))
        for t in unlisted_lines((page_row or {}).get("keeper_problems") if isinstance(page_row, dict) else None):
            m = re.search(r"`keeper: (.+?)` names no agent", t)
            out.append(("keeper-retired" if m and m.group(1).strip().casefold() in former_l else "keeper-not-listed", t))
        if got and pm and pm in listed and pm != got:
            out.append(("keeper-two-marks", f"the record flags {got} as the keeper, and the page's `keeper:` line names {pm}; the record's flag rules"))
        if got and got.casefold() in former_l:
            out.append(("keeper-retired", f"{got} is flagged as the keeper, and the record says it was retired from the project's agents"))
    except Exception:  # noqa: BLE001
        pass
    return out
