"""successor.py: open items left behind by a session that is gone reach their closest live successor.

When a project's last agent is retired (or any session that moves an open item goes), the item must not sit with a mover nobody can reach. The audit finds those items
(`orphans`) and hands each one to the closest live agent (`pick`); this module only decides, the server writes (server._orphan_handover, through the hand-off path of the
minute pass) and the audit run reports (audit_run.orphan_stage). Pure functions of items and the registry: no server import, no clock, no write, so the same call gives the same
answer twice and a second run finds nothing left to do.

  agents_of(entry)                         a registry page's agents as (name, kind) pairs, closest first: its -main (kind "main"), its other front agents ("front"), its background agents, builder first
                                           ("back"); a page with a name line and no front agent has that one session as its front agent
  pick(project, reg, live, ...)            → Pick(name, reason, tier) | None: the closest LIVE session for an item of `project`, by closeness, the first that is live:
                                           1. own      the project's own agents (the page that lists any: the item's page, else the nearest page above it): -main, other front, background
                                           2. parent   the pages above that one, nearest first: their -main, then their other front agents
                                           3. hub      the hub page named by a `hub:` line: the same
                                           4. scope    the scope's general -main agent (anchors.general_main)
                                           None when nothing is live: the item stays and is reported, never given to a guess
                                           An ALIVE item tries the project's background agents first (tier "back": the builder, then the others): the minute pass sends no notice to a front agent
                                           and never chases one, so a front agent takes an alive item only when no background agent is live (Pick.front, and the History line says so)
  orphans(items, derive, gone)             the open items whose session of record is gone: an alive item's mover, a waiting item's post-wake mover; never an item a human moves
  plan(items, reg, derive, gone, ...)      orphans(), each with its pick: a row {gid, project, state, from, gone, to, reason, why} with `to` "" when nothing is live

A session of record is "gone" when `gone(name)` answers a reason (the server's dead-pane rule); an item whose mover cannot be named at all is an orphan when its project has no live agent.
The owner (a human) is never a session of record to move: an item he moves, or waits on him, is left alone, and neither is a name that is no session (handoff.is_session_name: the server's, the cold call's, a script's label).
A HELD item (metadata.hold) is left alone: it waits on its wake. A parked item (no hold flag) whose post-wake mover is gone is moved. Stdlib plus anchors.py, handoff.py and model.py."""
from __future__ import annotations

import re
from typing import Any, Callable, NamedTuple

from stackshot.anchors import anchors as _anc
from stackshot.waits import handoff as _ho
from stackshot.model import model as _model

_BUILD = re.compile(r"\bbuild", re.I)
_MAINTAIN = re.compile(r"\b(?:builds?|builder|building|maintain\w*|merg\w*|engineer\w*)\b", re.I)      # router._BUILDER's words: the mandate that makes a background agent a builder


class Pick(NamedTuple):
    name: str            # the successor, as the registry spells it
    reason: str          # "closest because …": the sentence the item's History carries
    tier: str            # back | own | parent | hub | scope
    front: bool = False  # a user-facing agent: the minute pass pushes no notice to one, so its History line says so and the board shows the item


def agents_of(entry: dict[str, Any] | None) -> list[tuple[str, str]]:
    """The agents a registry page lists as (name, kind), closest first: the -main agent ("main"), the other user-facing agents in the page's order ("front"), then the background agents, a builder before the rest
    ("back"). A page that lists no user-facing agent but has a `display-name:` line (a one-session project) has that session as its front agent ("main"). A name-line session of a page that has user-facing
    agents is retired and not listed."""
    e = entry if isinstance(entry, dict) else {}
    front = _anc.front_agents(e)
    main = _anc.main_of(e)
    back = [str(k) for k in (e.get("back_agents") or {}) if str(k) not in front]
    mandate = lambda n: str((e.get("agents") or {}).get(n) or "")
    ranked = sorted(enumerate(back), key=lambda ib: (0 if _BUILD.search(mandate(ib[1])) else 1 if _MAINTAIN.search(mandate(ib[1])) else 2, ib[0]))
    out: list[tuple[str, str]] = ([(main, "main")] if main else []) + [(n, "front") for n in front if n != main] + [(ib[1], "back") for ib in ranked]
    one = str(e.get("session") or "").strip() if e.get("role") in ("name", "steward") else ""
    if not front and one and not _anc.is_id(one) and all(n != one for n, _k in out):
        out.insert(0, (one, "main"))
    return out


def _chain(project: str, reg: dict[str, dict[str, Any]]) -> list[str]:
    """The page keys from the item's page up to the top-level project page that the registry holds, nearest first (`projects/a/b/c` → c, b, a)."""
    parts = str(project or "").strip().strip("/").split("/")
    keys = ["/".join(parts[:n]) for n in range(len(parts), 1, -1)]
    return [k for k in keys if isinstance(reg.get(k), dict)]


_KIND_WORDS = {"main": "-main agent", "front": "front agent", "back": "background agent"}
FRONT_NOTE = " (a front agent: no notice is sent to one, the item shows on the board)"


def pick(project: str, reg: dict[str, dict[str, Any]], live: Callable[[str], bool], general: Callable[[str, dict[str, dict[str, Any]]], tuple[str, str]] | None = None,
         alive: bool = False, back_of: Callable[[str], list[str]] | None = None) -> Pick | None:
    """The closest live session for an item of `project`, or None when no candidate is live. `live(name)` says whether a session can take work now; `general(project, reg)` → (agent, page) is the scope's
    general -main agent (default anchors.general_main). The order is the module's table; the first live candidate wins, so the same registry and liveness always give the same session.
    `alive` (the item has a mover who works it): a user-facing agent is never sent a notice by the minute pass and never chased, so a mover who is a front agent would not hear of the item. The project's
    background agents come first (`back_of(project)`: the builder, then the others; default: the background agents of the item's page and the pages above it, the page's order, builder first), and a front
    agent takes the item only when no background agent is live; its Pick has `front` set and its reason says so. A waiting item's post-wake mover judges an arrival and is not pushed to either way, so
    its order is the table's."""
    reg = reg or {}
    chain = _chain(project, reg)
    if alive:
        backs = list(back_of(project)) if back_of else [n for k in chain for n, kd in agents_of(reg[k]) if kd == "back"]
        for name in dict.fromkeys(backs):
            if live(name):
                return Pick(name, f"closest live agent: the project's background agent {name} (an item with a mover goes to a session that is told of it)", "back")
    note = FRONT_NOTE if alive else ""
    own_key = next((k for k in chain if agents_of(reg[k])), "")
    if own_key:
        for name, kind in agents_of(reg[own_key]):
            if live(name):
                fr = kind != "back"
                return Pick(name, f"closest live agent: the project's own {_KIND_WORDS[kind]} {name}" + (f" (listed on {own_key})" if own_key != chain[0] else "") + (note if fr else ""), "own", fr and alive)
    for k in chain[chain.index(own_key) + 1 if own_key else 0:]:
        for name, kind in agents_of(reg[k]):
            if kind != "back" and live(name):
                return Pick(name, f"no live agent of the project itself; closest live agent: the parent project {k}'s {_KIND_WORDS[kind]} {name}" + note, "parent", alive)
    hub = _anc.hub_of(project, reg)
    if hub and hub not in chain and isinstance(reg.get(hub), dict):
        for name, kind in agents_of(reg[hub]):
            if kind != "back" and live(name):
                return Pick(name, f"no live agent of the project or its parents; closest live agent: the hub {hub}'s {_KIND_WORDS[kind]} {name}" + note, "hub", alive)
    try:
        name, page = (general or _anc.general_main)(project, reg)
    except Exception:  # noqa: BLE001
        name, page = "", ""
    if name and live(name):
        return Pick(name, f"no live agent of the project, its parents or its hub; closest live agent: the scope's general -main agent {name}" + (f" ({page})" if page else "") + note, "scope", alive)
    return None


def record_of(item: dict[str, Any], derive: Callable[[dict[str, Any]], Any]) -> tuple[str, str]:
    """(the item's state of record, the session it names) for an open item: ("alive", its effective mover) or ("waiting", the one who picks it up when the wait ends); ("", "") for a closed item, a HELD item (metadata.hold: it
    waits on a wake, and the server returns it then; a parked item, which waits with no hold flag, is not held and its gone post-wake mover is replaced) or one that cannot be read. The session may be "" (nobody
    can be named) or the owner."""
    if not isinstance(item, dict) or item.get("status") != "open":
        return "", ""
    if (item.get("metadata") or {}).get("hold"):
        return "", ""             # a held item waits on its wake (the server releases it then); whoever it is held for is judged when it comes back, not now
    try:
        mod = derive(item)
    except Exception:  # noqa: BLE001
        return "", ""
    if mod.state == _model.ALIVE:
        return "alive", str(mod.mover or "").strip()
    if mod.state == _model.WAITING and mod.wait is not None:
        return "waiting", str(mod.wait.mover or "").strip()
    return "", ""


def orphans(items: dict[str, dict[str, Any]], derive: Callable[[dict[str, Any]], Any], gone: Callable[[str], str],
            no_agent: Callable[[str], bool] = lambda project: False) -> list[dict[str, Any]]:
    """The open items whose session of record cannot take them: {gid, project, state: alive | waiting, from: the session ("" when none is named), gone: why, in words}. `gone(name)` → "" when the session may be
    live, else the reason; `no_agent(project)` says the project has no live agent (an item with no named session is an orphan only then). Never an item the owner moves or waits on; sorted by item."""
    out: list[dict[str, Any]] = []
    for gid in sorted(items):
        it = items[gid]
        state, who = record_of(it, derive)
        if not state or (who and (_model.is_owner(who) or not _ho.is_session_name(who))):
            continue                  # never the owner's, and never a name that is no session (the server's, the cold call's or a script's label)
        project = _anc.project_of(it)
        if who:
            why = gone(who)
            if not why:
                continue
        elif no_agent(project):
            why = "no session is named for it and its project has no live agent"
        else:
            continue
        out.append({"gid": gid, "project": project, "state": state, "from": who, "gone": why})
    return out


def plan(items: dict[str, dict[str, Any]], reg: dict[str, dict[str, Any]], derive: Callable[[dict[str, Any]], Any], gone: Callable[[str], str],
         label: Callable[[str], str] = str, general: Callable[[str, dict[str, dict[str, Any]]], tuple[str, str]] | None = None,
         back_of: Callable[[str], list[str]] | None = None) -> list[dict[str, Any]]:
    """Each orphan with its successor: the orphan's row plus `to` (the session, "" when nothing is live), `tier`, `reason` and `why`, the sentence the item's History carries
    (`<session> is gone (<why>); closest live agent: …`). The candidates are asked for liveness once each."""
    memo: dict[str, bool] = {}

    def live(name: str) -> bool:
        if name not in memo:
            memo[name] = not gone(name)
        return memo[name]

    def no_agent(project: str) -> bool:
        return not any(live(n) for k in _chain(project, reg) for n, _kd in agents_of(reg[k]))

    rows = orphans(items, derive, gone, no_agent)
    picks: dict[tuple[str, bool], Pick | None] = {}
    for r in rows:
        key = (r["project"], r["state"] == "alive")
        if key not in picks:
            picks[key] = pick(r["project"], reg, live, general, alive=key[1], back_of=back_of)
        p = picks[key]
        who = label(r["from"]) if r["from"] else ""
        r.update(to=p.name if p else "", tier=p.tier if p else "", front=bool(p and p.front), reason=p.reason if p else "no live agent of the project, its parents, its hub or its scope",
                 why=((f"{who} is gone ({r['gone']})" if who else r["gone"]) + (f"; {p.reason}" if p else "; no live successor was found")))
    return rows
