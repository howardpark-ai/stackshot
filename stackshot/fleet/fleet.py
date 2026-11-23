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
import socket
import time
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg
from stackshot.core import filecache as _fc
from stackshot.fleet import liveness as _lv

FLEET_DIR: Path = _cfg.fleet_dir()


def letters() -> list[str]:
    """Machine letters with live state, sorted: every folder of the view, a retired box's too. The readers that find a session or a box's facts
    (session maps, the inbox, a pane's machine) read this; the readers that draw the boxes read `drawn_letters`."""
    if not FLEET_DIR.is_dir():
        return []
    return sorted(p.name for p in FLEET_DIR.iterdir() if p.is_dir() and len(p.name) == 1)


def retired_letters() -> frozenset[str]:
    """The letters [fleet] retired_letters names: boxes that are gone and are no longer drawn. A missing key, a value that is not a list (one string counts as a list of one), an
    item that is not a string and an empty one are ignored; whitespace around a letter is stripped, and the letter is compared as given (the board's letters are lower-case)."""
    cfg = _cfg.get("fleet", "retired_letters") or []
    if isinstance(cfg, str):
        cfg = [cfg]
    if not isinstance(cfg, (list, tuple)):
        return frozenset()
    return frozenset(x.strip() for x in cfg if isinstance(x, str) and x.strip())


def not_drawn() -> frozenset[str]:
    """The letters left out of every drawing: [fleet] retired_letters without the publisher's letter (the box that runs this server is never retired)."""
    out = retired_letters()
    return out - {publisher()} if out else out


def drawn_letters() -> list[str]:
    """The letters to draw as boxes (the Machines panel's cards, `names`, the versions read, the board's per-machine facts, the sessions tool's machine list): `letters` without `not_drawn`.
    The folder of a retired letter stays and is written as before: only the drawing leaves it out, so its sessions still resolve and still own their items."""
    out = not_drawn()
    return [L for L in letters() if L not in out] if out else letters()


def read(letter: str, name: str) -> dict[str, Any]:
    """One machine's machine.json or sessions.json ({} when absent or unreadable)."""
    try:
        d = json.load(open(FLEET_DIR / letter / f"{name}.json", encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def read_shared(letter: str, name: str) -> dict[str, Any]:
    """`read` for a caller that only looks: the parse is kept while the file is as it was (core/filecache.py), so a file nobody wrote is not opened and parsed again. The dict is shared: never changed by the caller."""
    try:
        d = _fc.read_json(FLEET_DIR / letter / f"{name}.json")
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def sessions_unreadable() -> list[str]:
    """The machine letters whose sessions.json cannot be read as an object (absent, torn or not JSON): `read` gives {} for each, so an index built from `read` alone is partial without saying so.
    The view writes machine.json and sessions.json together for every machine it holds (clients.py `_materialize`), so a letter with the one and not the other is a read that failed, never a machine with no sessions."""
    out: list[str] = []
    for L in letters():
        try:
            ok = isinstance(_fc.read_json(FLEET_DIR / L / "sessions.json"), dict)
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:
            out.append(L)
    return out


def names() -> dict[str, str]:
    """letter → fleet name: session-names.tsv first (a box with no fleet state yet), then the fleet state's own `fleet` name; a letter in [fleet] retired_letters (`not_drawn`) is left out of both."""
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
    gone = not_drawn()                                       # a retired box is named by neither the folder nor a row of the names table
    return {L: n for L, n in out.items() if L not in gone}


# ---------------------------------------------------------------- the box that runs this server
# The publisher is the box the server runs on: the first column of the Machines panel, always live, and the one box whose own
# versions are read from the binary. [fleet] publisher_letter, when set, names it outright (an override, as it has always been);
# unset, it is found from the OS hostname, so a server moved to another box, or failed over, carries it along.
def own_hostname() -> str:
    """The OS hostname of the box this process runs on ("" when it cannot be read)."""
    try:
        return socket.gethostname()
    except OSError:
        return ""


def _hkey(h: Any) -> str:
    """A host name as compared: lower-cased, the domain part left off (a box answers to `box-a` and `box-a.example.net`)."""
    return str(h or "").strip().lower().split(".")[0]


def _names_rows() -> list[tuple[str, str, str]] | None:
    """The rows of paths.fleet_names as (hostname, fleet name, letter); None when the file cannot be read."""
    out: list[tuple[str, str, str]] = []
    try:
        for ln in open(_cfg.path("paths", "fleet_names"), encoding="utf-8"):
            c = [x.strip() for x in ln.rstrip("\n").split("\t")]
            if ln.strip() and not ln.startswith("#") and len(c) >= 3 and c[2]:
                out.append((c[0], c[1], c[2]))
    except Exception:
        return None
    return out


def own_names() -> set[str]:
    """Every name this box answers to, compared by `_hkey`: its OS hostname and, when the fleet's names table lists it, the table's hostname and fleet name
    (the OS hostname `HOST-1` is the fleet's `box-x`). A host in [machines_panel] ssh_hosts that is one of these is read here, not over ssh."""
    me = _hkey(own_hostname())
    if not me:
        return set()
    out = {me}
    for h, f, _l in _names_rows() or []:
        if me in (_hkey(h), _hkey(f)):
            out.update((_hkey(h), _hkey(f)))
    return out


def is_own_host(host: str) -> bool:
    """Whether `host` (a name in ssh_hosts) is this box itself."""
    return _hkey(host) in own_names() if _hkey(host) else False


def publisher() -> str:
    """The key of the box that runs this server: [fleet] publisher_letter when it is set (an explicit value always wins), else found from the hostname:
    the letter of the names table's row for this box (paths.fleet_names, by OS hostname or fleet name), else the letter of the fleet machine whose name this box
    answers to, else the lower-cased hostname itself (a stable key; the panel names the card by it). Fails open: with no hostname, or a names table that cannot
    be read and no fleet machine to match, it is "a", the key every install had before the letter was derived."""
    given = str(_cfg.get("fleet", "publisher_letter") or "").strip()
    if given:
        return given
    me = own_names()
    if not me:
        return "a"
    rows = _names_rows()
    for _h, f, letter in rows or []:
        if _hkey(f) in me or _hkey(_h) in me:
            return letter
    for L in letters():
        if _hkey(read_shared(L, "machine").get("fleet")) in me:
            return L
    return "a" if rows is None else _hkey(own_hostname())


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
    pub = publisher()
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


class SessionView:
    """The session rows of every machine, indexed once for the readers that only look up a name (`anchors.names`): uuid -> name of every row, and what `by_name` needs from them, found once per change of the files
    instead of once per question. The time a row is gone since is the only thing that moves with the clock, so each gone row keeps the stamp it was gone at (parsed once), and `by_name(now)` gives, for the same rows and
    the same `now`, the answer `fleet.by_name(rows, now, present_only)` gives (the same pairs; the order of the pairs is not kept, no reader goes by it)."""
    __slots__ = ("names", "_live", "_old")

    def __init__(self, rows: dict[str, dict[str, Any]]) -> None:
        self.names: dict[str, str] = {k: str(v.get("name") or "") for k, v in rows.items()}
        live: dict[str, list[str]] = {}; gone: dict[str, list[tuple[float, str]]] = {}
        for u, r in rows.items():
            n = str((r or {}).get("name") or "") if isinstance(r, dict) else ""
            if not n:
                continue
            if running(r):
                live.setdefault(n, []).append(u)
            else:
                gone.setdefault(n, []).append((_lv.ts(r["gone"]), u))
        self._live = {n: us[0] for n, us in live.items() if len(us) == 1}      # two running namesakes resolve to nobody
        old = [(n, c, max((t for t, _u in c if t), default=float("-inf"))) for n, c in gone.items() if n not in live]       # a name a running session carries is that session's
        old.sort(key=lambda x: -x[2])                       # the most recently gone first: gone_for only falls with the stamp, so the names fall out of the grace in this order
        self._old = old

    def by_name(self, now: float | None = None, present_only: bool = False) -> dict[str, str]:
        """`by_name` over these rows: a running namesake, else the row gone most recently (the first of equal times), only within the grace when `present_only`. `now` as `gone_for` takes it (the clock when None)."""
        now = time.time() if now is None else now
        out = dict(self._live); limit = _grace()
        for n, cands, _k in self._old:
            best, bu = float("inf"), None
            for t, u in cands:
                g = float("inf") if not t else max(0.0, now - t)       # gone_for's own rule
                if bu is None or g < best:
                    best, bu = g, u
            if present_only and best > limit:
                break                                           # the names after this one were gone no later
            out[n] = bu
        return out


def view() -> SessionView:
    """The SessionView of the machines' session rows, built again only when one of their files was written (core/filecache.py `derived`; a machine that comes or goes changes the token). Shared: never changed by a caller."""
    L = letters()
    return _fc.derived("fleet.view", [FLEET_DIR / x / "sessions.json" for x in L], (str(FLEET_DIR), tuple(L)), lambda: SessionView(sessions()))
