"""sessions.py: the `sessions` tool: the sessions of the fleet, by machine and role."""
from __future__ import annotations

import datetime as dt
import json

from stackshot.anchors import anchors as _anc
from stackshot.core import cloud as _cloud, config as _cfg
from stackshot.core.instance import OWNER
from stackshot.fleet import clients as _clients, fleet as _fleet, liveness as _lv, sessions_registry as _sr
from stackshot.fleet.sessions_registry import _sessions_index
from stackshot.service import telling as _telling
from stackshot.web.auth import oauth as _oauth
from stackshot.web.tools.text import ZONE, _FOR_OWNER, _lead

_fleet_names = None      # set by register: the server's own, looked up at each call


OPERATOR = str(_cfg.get("fleet", "operator_label") or "operator session")


def _machine_states() -> dict[str, str]:
    """letter → "live" | "offline since …", as the board shows it (pack-notes.sh, refreshed on every publish)."""
    try:
        pk = json.load(open(_cfg.state("site", "versions.json"), encoding="utf-8")).get("packages") or []
        return dict(next((p.get("machine_state") or {} for p in pk if isinstance(p.get("machines"), dict)), {}))
    except Exception:
        return {}


def stackshot_sessions(name: str = "") -> str:
    _oauth._who()
    return _sessions_listing(name.strip().lower())


_ROLE_LABEL = {_anc.NAME_ROLE: "keeper", "front": "front agent", "back": "background agent"}


def _sessions_listing(q: str = "", now: float | None = None) -> str:
    """The sessions tool's answer. A session the view holds as gone is listed while it is still expected back (gone for less
    than the grace, "not running now") or while an open board item names it as mover ("not running", kept for its items);
    a retired session nobody's item names is left out, though its identity stays in the view for the board (the owner
    identity apart from presence). `now` is for tests."""
    states = _machine_states()
    names = _fleet_names()
    out = ["Machines:"]
    for L in _fleet.letters():
        st = states.get(L) or "state unknown"
        m = _fleet.read(L, "machine")
        line = f"- {names[L]}: {'online' if st == 'live' else st} · Claude Code {m.get('claude') or '?'}"
        if m.get("master") or m.get("master_session"):
            # the operator ([fleet] operator_session: the session that runs the fleet; the former fleet master is retired): a cloud or Cowork session relays a recycle /
            # CLI-update cue to it with message(to=<name>) — it cannot ssh — and finds it here, and the operator queues it as a
            # fleet operation through the fleet tool; live = the session is running on that box right now. The machine keys
            # (master, master_session) keep their names.
            row = _fleet.read(L, "sessions").get(str(m.get("master_session") or "")) or {}
            nm = m.get("master") or row.get("name") or str(m.get("master_session"))[:8]
            live = _lv.idle_live(row)    # a gone row is held as last known through a relaunch, not running now
            line += f" · {OPERATOR}: {nm} ({'live, ' + (row.get('url') or 'no link now') if live else 'not running'})"
        out.append(line)
    try:
        roles = _anc.file_roles()                    # each session's role and the project it holds it in, as roles.json has it: a one-session project's only session reads front; the gates keep session_roles()
    except Exception:
        roles = {}
    def role(*keys: str) -> str:
        r = next((roles[k] for k in keys if k in roles), None)
        return f" · {_ROLE_LABEL.get(r['role'], r['role'])} of {r['project']}" if r else ""
    rows = []
    seen = set(); owners = set()                     # cloud movers of open items are listed; pane movers of open items keep a gone session listed
    for t in _anc.items():
        m = t.get("metadata") or {}
        if t.get("status") not in ("open", "on_hold"): continue
        o = _telling.holder({**t, "status": "open"})
        owners.update(x for x in (o, str(m.get("owner_name") or "")) if x)
        if not o.startswith("cse_") or o in seen: continue
        seen.add(o); ci = _cloud.info(o); nm = ci["title"] or m.get("owner_name") or o
        if not q or q in nm.lower():
            rows.append((nm.lower(), f"- {nm} — {ci['url']} · {'claude.ai chat' if ci['chat'] else 'cloud'}{role(o, str(nm))}"))
    for o in [x for x in owners if _sr.is_perm_id(x)]:        # a mover stored as a permanent id is its session's transcripts and names too
        owners.update(_sr.transcripts(o)); owners.update(_sr.names_of(o))
    for sid, v in _sessions_index().items():
        if not v.get("name") or (q and q not in v["name"].lower()):
            continue
        if _lv.running(v):
            tag = ""
        elif _lv.present(v, now):                 # gone for less than the grace: a pane being relaunched, or just retired
            tag = " · not running now (relaunching, or retired; shown as last known)"
        elif sid in owners or v["name"] in owners:   # an identity record the board still needs: say so, with its last sign of life
            tag = f" · not running (last seen {dt.datetime.fromtimestamp(_clients._ts(v.get('seen')), ZONE):%m-%d %H:%M %Z}; kept as the mover of open items)"
        else:
            continue
        rows.append((v["name"].lower(), f"- {v['name']} — {v.get('url') or '(no link now)'} · {names.get(v.get('machine', ''), v.get('machine', ''))}{role(v['name'], sid)}{tag}"))
    out.append(f"Sessions ({len(rows)}):")
    out += [r for _, r in sorted(rows)]
    return "\n".join(out)


def register(mcp, *, fleet_names) -> None:
    """Adds the tool of this module to `mcp`, and takes the server's callables the bodies use."""
    global _fleet_names
    _fleet_names = fleet_names
    mcp.tool(name="sessions", description=_lead(f"{OWNER}'s Claude sessions and machines, from the live fleet state on the server box — for a session that cannot read it itself (on another machine, in the cloud, in Cowork). Each session: its name, its link (for a pane, the URL the fleet tool's store gives it, where one is configured; for a cloud or Cowork session, its claude.ai link; link a session by it; empty = no link, name it plainly), its machine, and its role where a project page names it (front agent or background agent of <project>; a front agent takes a message only with {_FOR_OWNER} on its first line). Each machine: online or offline, its Claude Code CLI version, and on the box that runs it the {OPERATOR} (the session a recycle or CLI-update cue goes to — from a cloud or Cowork session, relay the cue with message(to=<that name>)), live or not running. Cloud and Cowork sessions are listed when they own an open board item. name: optional case-insensitive filter on session names."))(stackshot_sessions)
