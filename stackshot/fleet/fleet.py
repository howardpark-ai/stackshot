"""Where stackshot reads the session and machine state (live state moved out of git).

The directory is config.fleet_dir(): the view the server materialises from its own clients (clients.py, <state>/clients/fleet),
<letter>/machine.json and sessions.json, written atomically and only when a fact changes. The shape: machine.json {letter,
fleet, claude, checked, master, master_session, online, source}, sessions.json {transcript UUID: {name, url, seen, machine}}.
It is the shape the external fleet-state writer (the fleet tool's heartbeat) had, which stackshot read until an earlier change; the
readers never changed. One field comes from the fleet tool's store
again, a session's `url`: clients.py copies it in by transcript id from [client] session_links (unset: no links), so every
reader here gets the tool's link and builds none of its own. STACKSHOT_FLEET_DIR points them elsewhere (tests). The store in git keeps
items only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg
from stackshot.fleet import liveness as _lv

FLEET_DIR: Path = _cfg.fleet_dir()


def letters() -> list[str]:
    """Machine letters with live state, sorted."""
    if not FLEET_DIR.is_dir():
        return []
    return sorted(p.name for p in FLEET_DIR.iterdir() if p.is_dir() and len(p.name) == 1)


def read(letter: str, name: str) -> dict[str, Any]:
    """One machine's machine.json or sessions.json ({} when absent or unreadable)."""
    try:
        d = json.load(open(FLEET_DIR / letter / f"{name}.json", encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def names() -> dict[str, str]:
    """letter → fleet name: session-names.tsv first (a box with no fleet state yet), then the fleet state's own `fleet` name."""
    out: dict[str, str] = {}
    try:
        for ln in open(_cfg.path("paths", "fleet_names"), encoding="utf-8"):
            c = ln.rstrip("\n").split("\t")
            if ln.strip() and not ln.startswith("#") and len(c) >= 3:
                out[c[2].strip()] = c[1].strip()
    except Exception:
        pass
    for L in letters():
        n = read(L, "machine").get("fleet")
        if n:
            out[L] = n
    return out


def ssh_host_names() -> list[str]:
    """The names in [machines_panel] ssh_hosts, in config order, a repeat once (the list versions.ssh_hosts_read probes; a bad name there is skipped by it, not here)."""
    cfg = _cfg.get("machines_panel", "ssh_hosts") or []
    if isinstance(cfg, str):
        cfg = [cfg]
    out: list[str] = []
    for h in cfg:
        h = str(h).strip()
        if h and h not in out:
            out.append(h)
    return out


def machines_order(fleet: dict[str, str] | None = None, hosts: list[str] | None = None) -> list[str]:
    """The Machines panel's order, one name per machine: the publisher, then the other fleet machines by letter, then the
    [machines_panel] ssh_hosts that are not fleet machines, in config order. A host that is also a fleet machine is the fleet machine's one
    card, keyed by the full hostname. The Runners page and the panel's Runners section follow this order."""
    fleet = names() if fleet is None else fleet
    hosts = ssh_host_names() if hosts is None else hosts
    pub = str(_cfg.get("fleet", "publisher_letter") or "a")
    out: list[str] = []
    for L in [pub] + sorted(x for x in fleet if x != pub):
        n = fleet.get(L, L)
        if n not in out:
            out.append(n)
    for h in hosts:
        if h not in out:
            out.append(h)
    return out


# ---------------------------------------------------------------- identity and presence
# A row keeps a session's identity (name, url, machine, previous_name) as long as the server holds it; `gone` (an ISO time)
# says its puller stopped reporting it. Presence is read off that stamp, with one rule for every reader: running = not gone;
# present = running, or gone for less than GRACE (a pane being relaunched is expected back under the same transcript id);
# anything older is an identity record, there so the board still names the owner of its items and never mistaken for a
# live session (a name it carries goes to a running session first).
# One clock for all of it: liveness.py holds the definitions; these names stay so a reader (and a test) that names them through fleet resolves to the one function.
_grace = _lv.grace                  # GRACE, the same window clients.py holds a session through a relaunch (read at use: a reload is live)
dead_after = _lv.dead_after         # how long a session has to be gone before a message to it is refused as sent to a dead pane
_ts = _lv.ts
running = _lv.running               # reported by its puller or its hooks now (not marked gone)
gone_for = _lv.gone_for             # seconds since the session was last known running; 0.0 while it runs
present = _lv.present               # running, or gone for less than GRACE: a session a line can still wait for, a name still taken


def sessions() -> dict[str, dict[str, Any]]:
    """transcript uuid → row (with its machine letter) of every session the view holds, identity records included."""
    out: dict[str, dict[str, Any]] = {}
    for L in letters():
        for k, v in read(L, "sessions").items():
            if isinstance(v, dict) and k not in out:
                out[k] = {"machine": L, **v}
    return out


def by_name(rows: dict[str, dict[str, Any]] | None = None, now: float | None = None, present_only: bool = False) -> dict[str, str]:
    """name → transcript uuid: the one running session of that name (two running namesakes resolve to nobody, as before),
    else the one gone most recently — only within GRACE when `present_only` (a name only a retired session carries then
    resolves to nothing, so an item or a line is never bound to its id). A live session reusing a gone session's name wins."""
    rows = sessions() if rows is None else rows
    live: dict[str, list[str]] = {}; old: dict[str, tuple[float, str]] = {}
    for u, r in rows.items():
        n = str((r or {}).get("name") or "") if isinstance(r, dict) else ""
        if not n:
            continue
        if running(r):
            live.setdefault(n, []).append(u)
        else:
            g = gone_for(r, now)
            if present_only and g > _grace():
                continue
            if n not in old or g < old[n][0]:
                old[n] = (g, u)
    out = {n: us[0] for n, us in live.items() if len(us) == 1}
    for n, (_g, u) in old.items():
        if n not in live:
            out[n] = u
    return out
