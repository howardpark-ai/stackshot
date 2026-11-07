#!/usr/bin/env python3
"""tools/page_agent_report.py — the daily audit's page agent lines check: which names on a project page's agent lines does sala no longer know, and which project page has items and no agents.

A project page names sessions in three places: the `agents:` map (user-facing and `background:` entries), a sub-page's `agent:` line and the page's `display-name:` line. Sessions get renamed and retired; the page does not follow
on its own, so a line goes on naming a session that is gone and a notice or a message to it goes nowhere. This lists those lines, each with the agent it is to go to (the page's -main agent, else the parent page's, the hub's and the
scope's general one: the router's own fallback, `anchors.fallback_main`), so the audit sends it there and that agent fixes the line or retires the name. Read only: it changes no page and sends nothing. Stdlib plus the repo's
modules, Python 3.11+. Beside tools/board_report.py, which it is modeled on.

What counts as a leftover (a page that is retired, done or moved is skipped; so is a line that holds an id and no name):
  agents line      a name of the `agents:` map (user-facing or background) or a sub-page's `agent:` that is neither a live sala session nor an alias of one (an alias is the name a live session had before a rename:
                   it folds into the live one, so the line still reaches it)
  display-name     the `display-name:` line names the project, and its agents are named `<display-name>-<suffix>`. It is a leftover when no live session is named exactly that and no live session's own name
                   starts with `<display-name>-`. An alias does not excuse it: `<display-name>-` as the start of an alias only says the old name of a session outlives the project's own name (the page was not
                   renamed when its sessions were)
  no agents        a page that is `type: project`, not a sub-page and not retired, done or moved, with no front agent on its `agents:` map (no map at all, or only `background:` entries), and no session of its own
                   (`projects.agent_gap`: a page whose `display-name:` names a live session, or one that starts with it, is a one-session page by design and is left alone), and with board items
                   open or touched in the last `projects.LISTED_DAYS` days (a sub-page's items count for the page above it): its items have no contact and nobody takes its notices. The line is `no agents map` or
                   `no front agent`, the name is the item count. A page whose only session (its name line) is named for another project (it starts with that project's name, not with the page's own) is the same gap
                   however live the session is: the line is `other project's session`, the name the session. The check reads the session list for the name line, so it is made only when the session check is
                   (a run that says "not checked" carries none). When the board items cannot be read it says so on stderr and makes none

  session off the map   a live session that created, moves or is the contact of an open item of a project, while the page's agents map (the page, its parent, its hub) has no line for it, and it is listed on no page
                   or is named for this project (`anchors.off_map`, the rule the write note uses too). One line for each project page: the name lists the sessions with their item counts. A session listed on another
                   project's map is a visitor and is not flagged. The check reads the session list, so it is made only when the session check is

When sala's session list cannot be read (no fleet store configured, no sala, a timeout, a failing call) or is empty, nothing is flagged and the report says it was not checked: every name would look stale.
A list that is cut short but not empty has the same effect on most names, so it is refused the same way: when `UNKNOWN_MIN` or more of the distinct names read are unknown and they are more than `UNKNOWN_SHARE` of all the distinct
names read, nothing is flagged and the note says the list looks partial (a real run flags a few names of a few hundred).

  tools/page_agent_report.py                 the leftovers, one line each (page · line · name · who is told · what fixes it), then the counts
  tools/page_agent_report.py --line          the one line the audit carries ("Page agent lines: 3 line(s) on 2 page(s)" / "Page agent lines: not checked (sala's session list is not readable)")
  tools/page_agent_report.py --json          {"checked", "note", "sessions", "pages", "findings": [{page, line, name, to, fix}]}
  tools/page_agent_report.py --sessions FILE read the sessions from FILE (a copy of `sala sessions --json`) instead of calling sala

The audit calls it through `audit.py page-agents` and sends the findings in its daily run (audit_run.py). Exit 0."""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))
import anchors as _anc  # noqa: E402
import projects as _prj  # noqa: E402

CATEGORY = "page agent lines"
LINE_AGENTS = "agents line"
LINE_AGENT = "agent line"
LINE_DISPLAY = "display-name"
_ID_RX = _prj.SESSION_ID_RX       # a session id is no name to look up
FIX_AGENTS = "write the session's new name on the line, or take the line off the page (retire the name)"
FIX_DISPLAY = "write the project's name that its live sessions start with, or retire the name"
LINE_NO_AGENTS = "no agents map"
LINE_NO_FRONT = "no front agent"
LINE_FOREIGN = "other project's session"
LINE_OFFMAP = "session off the map"
OFFMAP_SHOWN = 4         # sessions named on a page's line; the rest are counted
FIX_OFFMAP = "the page's agents map has no line for it, so no agent knows it works here: add its line (ask the -main agent) or move its items to a session on the map"
FIX_NO_AGENTS = "its items have no contact and nobody to take its notices; add the agents map with its -main agent (ask the scope's general -main agent if no one owns it)"

UNKNOWN_SHARE = 0.25     # more than this share of the distinct names read being unknown means sala's list is cut short, not that the pages are stale
UNKNOWN_MIN = 10         # the share applies only from this many unknown names: a handful of leftovers on a small registry is real

Sessions = tuple[set[str], set[str]]


def active(entry: dict[str, Any]) -> bool:
    """A page that is not retired, done or moved (its `status:` is none of the retired words, and its title does not start with "moved")."""
    return _prj.page_active(entry)


def is_display_name(entry: dict[str, Any]) -> bool:
    return entry.get("role") == "name" and bool(str(entry.get("session") or "").strip())


def display_ok(name: str, names: set[str], aliases: set[str]) -> bool:
    """Is a `display-name:` value known to sala: a live session named exactly so (a one-session project, which also takes an alias of it), or a live session whose own name starts with `<name>-`."""
    return _prj.session_live(name, names, aliases)


def item_counts(items: Any, reg: dict[str, dict[str, Any]], now: float | None = None) -> dict[str, dict[str, int]]:
    """key → {"open": open items, "recent": items (open or completed) touched within `projects.LISTED_DAYS` days} for the page an item names and for every page above it in the registry, or the one its
    `hub:` line names (a sub-page's items count for its project, as `projects.recent_items` has it). `items` is a list of item dicts, or a dict of them by id."""
    now = time.time() if now is None else now
    out: dict[str, dict[str, int]] = {}
    for t in (items.values() if isinstance(items, dict) else items or []):
        if not isinstance(t, dict):
            continue
        try:
            v = _anc.project_of(t).strip("/")
            ts = max(float(t.get("updated") or 0), float(t.get("state_updated") or 0))
        except (TypeError, ValueError, AttributeError):
            continue
        if v.endswith(".md"):
            v = v[:-3]
        if not v:
            continue
        parts = v.split("/")
        ks = [v] + [k for k in ("/".join(parts[:n]) for n in range(len(parts) - 1, 1, -1)) if k in reg]
        for k in list(ks):
            h = str((reg.get(k) or {}).get("hub") or "").strip() if isinstance(reg.get(k), dict) else ""
            if h and h in reg and h not in ks:
                ks.append(h)
        for k in ks:
            c = out.setdefault(k, {"open": 0, "recent": 0})
            if t.get("status") != "completed":
                c["open"] += 1
            if now - ts <= _prj.LISTED_DAYS * 86400:
                c["recent"] += 1
    return out


def agentless(key: str, e: dict[str, Any], reg: dict[str, dict[str, Any]], counts: dict[str, dict[str, int]] | None, live: Sessions | None = None) -> dict[str, str] | None:
    """The finding for a `type: project` page that `projects.agent_gap` says has no one to take its items (no front agent, and no live session of its own on its name line) and that has open or recently touched
    items; None for any other page. `live` = (names, aliases) of the live sessions (None: cannot tell, a name line counts as live)."""
    gap = _prj.agent_gap(key, e, reg, live)
    if not gap:
        return None
    c = (counts or {}).get(key) or {}
    if not c.get("open") and not c.get("recent"):
        return None
    if c.get("open"):
        n = f"{c['open']} open item{'' if c['open'] == 1 else 's'}"
    else:
        n = f"{c['recent']} item{'' if c['recent'] == 1 else 's'} touched in {_prj.LISTED_DAYS} days"
    if gap["kind"] == "foreign-name":
        return {"page": key, "line": LINE_FOREIGN, "name": gap["name"], "fix": f"{n}; named for {gap['other']}, not for this page, and on no agents map: give the page its own agents map and -main agent (ask the scope's general -main agent)"}
    return {"page": key, "line": LINE_NO_FRONT if gap["kind"] == "no-front-agent" else LINE_NO_AGENTS, "name": n, "fix": FIX_NO_AGENTS}


def offmap(items: Any, reg: dict[str, dict[str, Any]], sessions: Sessions, nm: dict[str, str] | None = None) -> list[dict[str, str]]:
    """The `session off the map` findings: for each active `type: project` page, the live sessions (`sessions` = sala's (names, aliases)) that created (`metadata.owner`), move (`metadata.mover`) or are the contact
    (`metadata.contact`) of an open item of the project and that `anchors.off_map` says its agents map has no line for. One finding for a page, the name = the sessions with their item counts (the first OFFMAP_SHOWN,
    most items first, then a count of the rest), keyed by the page that holds the map (the hub's, for a page with a `hub:` line)."""
    names, aliases = sessions
    live = names | aliases
    nm = _anc.names() if nm is None else nm
    per: dict[str, dict[str, set[str]]] = {}
    for gid, t in (items.items() if isinstance(items, dict) else enumerate(items or [])):
        if not isinstance(t, dict) or t.get("status") == "completed":
            continue
        try:
            v = _anc.project_of(t).strip("/")
        except (TypeError, AttributeError):
            continue
        v = v[:-3] if v.endswith(".md") else v
        root = "/".join(v.split("/")[:2])
        e = reg.get(root)
        if not v or not isinstance(e, dict) or str(e.get("type") or "").strip().lower() != "project" or not active(e):
            continue
        page = _anc.hub_of(root, reg)
        meta = t.get("metadata") if isinstance(t.get("metadata"), dict) else {}
        for s in {str(meta.get(k) or "").strip() for k in ("owner", "mover", "contact")} - {""}:
            who = _anc.off_map(s, root, reg, nm, live)
            if who:
                per.setdefault(page, {}).setdefault(who, set()).add(str(t.get("gid") or gid))
    out = []
    for page in sorted(per):
        ranked = sorted(per[page].items(), key=lambda kv: (-len(kv[1]), kv[0]))
        shown = [f"{w} ({len(g)} item{'' if len(g) == 1 else 's'})" for w, g in ranked[:OFFMAP_SHOWN]]
        more = len(ranked) - OFFMAP_SHOWN
        out.append({"page": page, "line": LINE_OFFMAP, "name": ", ".join(shown) + (f" and {more} more" if more > 0 else ""), "fix": FIX_OFFMAP})
    return out


def scan(reg: dict[str, dict[str, Any]], sessions: Sessions | None, counts: dict[str, dict[str, int]] | None = None, off: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """The leftovers of the registry `reg` against the live sessions `(names, aliases)` as `anchors.sala_sessions` gives them. → {"checked", "note", "sessions", "pages", "findings"}; each finding is
    {"page", "line", "name", "fix"} (the recipient is added by `route`). Nothing is flagged when `sessions` is None or has no name (the list was not read), nor when the unknown names pass the cap
    (`UNKNOWN_SHARE`, from `UNKNOWN_MIN` names): the list looks cut short. `counts` is `item_counts`' answer: with it a `type: project` page with items and no front agent is a finding too (`agentless`)."""
    if sessions is None:
        return {"checked": False, "note": "sala's session list is not readable", "sessions": 0, "pages": 0, "findings": []}
    names, aliases = sessions
    if not names:
        return {"checked": False, "note": "sala lists no session", "sessions": 0, "pages": 0, "findings": []}
    known = names | aliases
    found: list[dict[str, str]] = []
    gaps: list[dict[str, str]] = []
    seen_pages = 0
    read_names: set[str] = set()                 # every distinct name looked up, known or not
    for key in sorted(reg):
        e = reg[key] if isinstance(reg[key], dict) else {}
        if not active(e):
            continue
        seen_pages += 1
        gap = agentless(key, e, reg, counts, (names, aliases))
        if gap:
            gaps.append(gap)
        for n in dict.fromkeys(str(x) for x in (e.get("agents") or {})):
            if n and not _ID_RX.match(n):
                read_names.add(n)
            if n and not _ID_RX.match(n) and n not in known:
                found.append({"page": key, "line": LINE_AGENTS, "name": n, "fix": FIX_AGENTS})
        s = str(e.get("session") or "").strip()
        if s and not _ID_RX.match(s) and (e.get("role") == "agent" or is_display_name(e)):
            read_names.add(s)
        if e.get("role") == "agent" and s and not _ID_RX.match(s) and s not in known:
            found.append({"page": key, "line": LINE_AGENT, "name": s, "fix": FIX_AGENTS})
        if is_display_name(e) and not _ID_RX.match(s) and not display_ok(s, names, aliases):
            found.append({"page": key, "line": LINE_DISPLAY, "name": s, "fix": FIX_DISPLAY})
    unknown = {f["name"] for f in found}
    if len(unknown) >= UNKNOWN_MIN and len(unknown) > UNKNOWN_SHARE * len(read_names):
        return {"checked": False, "note": f"sala's session list looks partial: {len(unknown)} of {len(read_names)} names unknown, over {round(UNKNOWN_SHARE * 100)}%", "sessions": len(names), "pages": seen_pages, "findings": []}
    return {"checked": True, "note": "", "sessions": len(names), "pages": seen_pages, "findings": found + gaps + list(off or [])}


def recipient(page: str, reg: dict[str, dict[str, Any]], live: set[str]) -> str:
    """The agent a page's leftovers go to: its own -main agent, else the router's fallback (the top-level page's, the hub's, the scope's general one), the first of them that sala knows (a -main agent that is
    itself a leftover is no one to tell). "" when none is live: the audit then uses its own -main agent."""
    root = _anc.pilot_root(page) or "/".join(page.split("/")[:2])
    cands = [_anc.main_of(reg.get(page) or {}), _anc.main_of(reg.get(root) or {}), _anc.main_of(reg.get(_anc.hub_of(root, reg)) or {}), _anc.general_main(root, reg)[0]]
    return next((c for c in dict.fromkeys(cands) if c and c in live), "")


def route(result: dict[str, Any], reg: dict[str, dict[str, Any]], sessions: Sessions | None) -> dict[str, Any]:
    """`scan`'s result with `to` on every finding: whom its message goes to ("" = none is live)."""
    live = (sessions[0] | sessions[1]) if sessions else set()
    for f in result["findings"]:
        f["to"] = recipient(f["page"], reg, live)
    return result


def read(reg: dict[str, dict[str, Any]] | None = None, sessions: Callable[[], Sessions | None] | None = None, items: Any = None, now: float | None = None) -> dict[str, Any]:
    """The whole check on live data (or on what is given): the registry, sala's sessions and the board items read once, the findings routed. `items` (a list or a dict of item dicts) is the board's items;
    None reads the store's. Items that cannot be read give no `no agents` finding, never an error."""
    reg = _anc.registry() if reg is None else reg
    got = (sessions or _anc.sala_sessions)()
    try:
        items = _anc.items() if items is None else items
        counts = item_counts(items, reg, now)
    except Exception as ex:  # noqa: BLE001
        counts, items = {}, []
        print(f"page_agent_report: the board items could not be read ({type(ex).__name__}: {ex}); no project page is checked for items and no agents", file=sys.stderr)
    off: list[dict[str, str]] = []
    if got is not None and got[0]:
        try:
            off = offmap(items, reg, got)
        except Exception as ex:  # noqa: BLE001
            print(f"page_agent_report: sessions off the map not checked ({type(ex).__name__}: {ex})", file=sys.stderr)
    return route(scan(reg, got, counts, off), reg, got)


def line_of(f: dict[str, Any]) -> str:
    return f"{f['page']} · {f['line']} · {f['name']} · {f['fix']}"


def summary_line(res: dict[str, Any]) -> str:
    if not res["checked"]:
        return f"Page agent lines: not checked ({res['note']})"
    fs = res["findings"]
    return f"Page agent lines: {len(fs)} line(s) on {len({f['page'] for f in fs})} page(s)"


def sessions_from_file(path: str) -> Sessions | None:
    """`sala sessions --json` saved to a file → (names, aliases); None when the file does not hold the sessions list."""
    try:
        rows = json.loads(Path(path).expanduser().read_text(encoding="utf-8")).get("sessions")
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(rows, list):
        return None
    names: set[str] = set()
    aliases: set[str] = set()
    for x in rows:
        if isinstance(x, dict) and x.get("name"):
            names.add(str(x["name"]))
            aliases.update(str(a) for a in (x.get("aliases") or []) if a and isinstance(a, str))
    return names, aliases


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="audit.py page-agents", description="List the page agent lines that name a session sala no longer knows (read only: nothing is sent).")
    ap.add_argument("--line", action="store_true", help="print the one line the audit carries")
    ap.add_argument("--json", action="store_true", help="print the whole report as JSON")
    ap.add_argument("--sessions", help="read the sessions from this file (a copy of `sala sessions --json`) instead of calling sala")
    a = ap.parse_args(argv)
    res = read(sessions=(lambda: sessions_from_file(a.sessions)) if a.sessions else None)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    elif a.line:
        print(summary_line(res))
    else:
        for f in res["findings"]:
            print(f"{line_of(f)} · tell {f['to'] or '(no live -main agent: the audit agent)'}")
        print(summary_line(res) + (f" · {res['sessions']} live session(s), {res['pages']} active page(s) read" if res["checked"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
