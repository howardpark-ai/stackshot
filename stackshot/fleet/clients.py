"""clients.py — what the server knows of machines and sessions from its own clients (the
design doc).

A session registers itself (its SessionStart hook → POST /client/register) and each machine's puller reports, with every
poll, the sessions that are live on that machine (POST /client/poll): that poll is also the machine's sign of life. The
server keeps both as its own state (<state>/clients/state.json) and materialises them in the shape every reader already
knows — <letter>/{machine,sessions}.json under <state>/clients/fleet/, the shape the fleet state had before it. config.fleet_dir()
points the readers there, so the server, the hub, the renderer, the version tracker and the pane gate read one view. The
view holds the server's own clients alone: the fleet-state store and the merge with it were removed in an earlier change (a session's
link excepted: it is the fleet tool's, see "Session links" below).

machine.json   {letter, fleet, claude, checked, master, master_session, online: {ok, since}, source[, setup, updates, stackshot]}   (below)
sessions.json  {uuid: {name, url, seen, machine[, previous_name, renamed_at, status, gone]}}   (url: the fleet tool's link, below)
The files are rewritten only when a fact changes (the times alone never do it), because a new mtime republishes the board.

Identity apart from presence (without it a pane relaunch would leave the board drawing owners as raw
transcript ids or the CLI's placeholder name, without their link). A session's
identity — name, machine, previous_name — stays on record and in the view with no time limit; only its presence
expires: a session its puller stopped reporting (or, on a machine with no puller checking in, one with no sign of life
for session_ttl_hours) is marked `gone` and stays as it was last seen. Readers tell the two apart through fleet.py
(running / present / by_name): for GRACE = online_minutes a gone session is still expected back under the same id (a pane
between its /exit and its resume); past that it is an identity record, never mistaken for a live one, and a live session
reusing its name wins. A record gone longer than session_horizon_days is forgotten, unless an open board item still
names it as owner (its uuid or its name), so the store cannot grow without bound while the board never loses an owner.
The CLI's own placeholder names (nameSource auto or collision, or a name of its shape "<os user>-<2 hex>" whatever nameSource
came with it, before a /rename) never displace a name on record.

Session links come from the fleet tool. A pane's `url` in the
view is the url the fleet tool writes for that transcript id in its own live store, [client] session_links (default "": no
links; <letter>/sessions.json for every letter there, the shape the stackshot–sala contracts fix): whatever link the tool
gives a pane, or nothing. stackshot builds no session link itself: a session with no row there, or a row with an empty url,
has no link and is named plainly, whatever its bridge does. This brings back a read of the fleet tool's store, the one an earlier change
removed with the fleet-state merge, for the links alone: names, machines and presence still come from the server's own
clients. A missing or unreadable store is logged once and gives no links.
Cloud and Cowork sessions (cse_…) are not in this view: cloud.py keeps their claude.ai links.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import logging
import os
import socket
import subprocess
import sys
import re
import threading
import time
from pathlib import Path
from typing import Any

from stackshot import paths as _paths
from stackshot.core import config as _cfg
from stackshot.fleet import liveness as _lv

DIR: Path = _cfg.state("clients")
STATE: Path = DIR / "state.json"
VIEW: Path = DIR / "fleet"
LAG_FLAG: Path = DIR / "puller-lag"   # `client.py puller-lag`'s lines, rewritten only when they change; the fleet tool's path unit starts
                                     # its watchdog on that change, so a lagging box is provisioned at once, not at the next 2-min tick
# [client] windows and the answers built on them live in liveness.py (one clock, read at use so a config reload is live at once); these names stay for the readers and tests that name them through clients:
_online = _lv.online_window                                              # a machine is online while its puller checked in within this
SESSION_LINKS_DEFAULT = ""                                               # [client] session_links unset: no fleet tool's store, no session links
POLL_MAX = 55.0                                                          # s: the longest a poll is held open (a proxy in front gives up at about a minute)
PRUNE_EVERY = 3600.0                                                   # how often _expire looks for records past the horizon (it reads the items store to do it)
_OPEN = ("open", "on_hold")                                              # item statuses that count as open (on_hold: the retired status, until the start-time migration)
PROVISIONAL = ("auto", "collision", "derived")                           # the CLI's nameSource values for a name it made up itself: "derived" is <cwd basename>-<2 hex> ("cwd-0e", "demo-5a")
PLACEHOLDER_ANY = re.compile(r"^[a-z0-9._-]+-[0-9a-f]{2}$")              # the CLI's placeholder shape when the reporting machine's OS user is not known
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_LOCK = threading.RLock()
_REJECTED: dict[str, str] = {}                                           # uuid → the placeholder last refused for it, so a refusal is logged once, not every poll

log = logging.getLogger("stackshot.clients")                             # to the server's journal (stderr), at INFO, whatever the root logger is set to
if not log.handlers:
    _h = logging.StreamHandler(sys.stderr); _h.setFormatter(logging.Formatter("clients: %(message)s"))
    log.addHandler(_h); log.setLevel(logging.INFO); log.propagate = False


def _iso(ts: float | None = None) -> str:
    return dt.datetime.fromtimestamp(time.time() if ts is None else ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_ts = _lv.ts


def _read(p: Path) -> dict[str, Any]:
    try:
        d = json.load(open(p, encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _write(p: Path, d: dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name("." + p.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, p)


class _locked:
    """One writer of state.json at a time, across threads and processes."""
    def __enter__(self):
        _LOCK.acquire()
        DIR.mkdir(parents=True, exist_ok=True)
        self.f = open(DIR / "lock", "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN); self.f.close(); _LOCK.release()
        return False


def load() -> dict[str, Any]:
    d = _read(STATE)
    d.setdefault("machines", {}); d.setdefault("sessions", {})
    return d


def puller_current() -> str:
    """puller.py's VERSION in this checkout: what every box's puller should report."""
    try:
        m = re.search(r'^VERSION\s*=\s*"([^"]+)"', open(_paths.program("fleet", "puller"), encoding="utf-8").read(), re.M)
        return m.group(1) if m else ""
    except OSError:
        return ""


_COMMIT = {"at": 0.0, "v": "", "good": "", "held": ""}
CHECKOUT = str(_paths.ROOT)     # the checkout whose commit is advertised (a test points it elsewhere)
_SHA = re.compile(r"[0-9a-f]{40}")


def _advertised_file() -> Path:
    return DIR / "advertised-commit"


def _git_out(*args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", CHECKOUT, *args], capture_output=True, text=True, timeout=10)
        return r.returncode, r.stdout.strip()
    except Exception:
        return 127, ""


def _advertise() -> str:
    """The commit every box's puller is told to follow: this checkout's HEAD only while origin/main (the ref as last fetched; no
    network call) contains it. A checkout switched to an unmerged branch for a minute would otherwise strand every box that
    followed it (their updates then refuse, diverged, once main moves on). Off main, the last commit that was advertised stays
    advertised (kept in memory and in <state>/clients/advertised-commit, so a restart does not forget it); with none, origin/main's
    own commit. One warning line per held-back HEAD. A checkout that has no origin/main ref (no remote) advertises HEAD as before."""
    rc, v = _git_out("rev-parse", "HEAD")
    if rc != 0 or not _SHA.fullmatch(v):
        return ""
    rc, _ = _git_out("rev-parse", "--verify", "--quiet", "refs/remotes/origin/main^{commit}")
    if rc == 1:                                # --verify --quiet: no such ref
        return v
    if rc != 0:                                # git could not say (a timeout is 127): the answer given so far stands
        return _COMMIT["v"] or v
    rc, _ = _git_out("merge-base", "--is-ancestor", v, "refs/remotes/origin/main")
    if rc not in (0, 1):                       # an error (128) or a timeout (127) is not "HEAD is off main": keep what was advertised, say nothing
        return _COMMIT["v"] or v
    if rc == 0:
        if _COMMIT["good"] != v:
            _COMMIT["good"] = v
            try:
                DIR.mkdir(parents=True, exist_ok=True)
                _advertised_file().write_text(v + "\n", encoding="utf-8")
            except OSError:
                pass
        _COMMIT["held"] = ""
        return v
    if not _COMMIT["good"]:
        try:
            g = _advertised_file().read_text(encoding="utf-8").strip()
        except OSError:
            g = ""
        if _SHA.fullmatch(g) and _git_out("cat-file", "-e", g + "^{commit}")[0] == 0:
            _COMMIT["good"] = g
    held = _COMMIT["good"]
    if not held:
        rc, m = _git_out("rev-parse", "refs/remotes/origin/main")
        held = m if rc == 0 and _SHA.fullmatch(m) else ""
    if _COMMIT["held"] != v:
        _COMMIT["held"] = v
        log.warning("checkout HEAD %s is not in origin/main: advertising %s instead", v[:12], held[:12] or "nothing")
    return held


def checkout_commit() -> str:
    """The commit boxes follow (_advertise: this checkout's HEAD while origin/main contains it; git asked at most every minute: a
    deploy that restarts the puller alone moves the checkout under a running server); "" when git cannot say."""
    if time.time() - _COMMIT["at"] > 60:
        try:
            v = _advertise()
        except Exception:
            v = ""
        _COMMIT.update(at=time.time(), v=v if _SHA.fullmatch(v) else "")
    return _COMMIT["v"]


_REPO = {"at": 0.0, "v": ""}
_SCP_URL = re.compile(r"(?:[^@/\\:\s]+@)?([A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]):(?![:\\]|//)(\S+)")   # git@host:owner/repo (never a drive letter)


def canonical_url(u: str) -> str:
    """A repository address as the boxes are told it: https, with no user or password (the repository is fetched anonymously), whatever form
    this checkout's origin has (`git@host:owner/repo.git`, `ssh://git@host/owner/repo`, `https://user:token@host/owner/repo`). Another
    shape (a local path, a file:// URL) stays as it is; "" for an empty or unreadable address."""
    u = str(u or "").strip()
    if not u or any(c.isspace() for c in u) or u.startswith("-"):
        return ""
    m = re.match(r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://(?P<rest>.+)", u)
    if m:
        scheme = m["scheme"].lower()
        if scheme not in ("http", "https", "ssh", "git"):
            return u if scheme == "file" else ""
        netloc, _, path = m["rest"].partition("/")
        host = netloc.rsplit("@", 1)[-1]
        if scheme in ("ssh", "git"):
            host = host.split(":", 1)[0]               # an ssh port is no https port
        return f"https://{host}/{path}" if host and path else ""
    m = _SCP_URL.fullmatch(u)
    return f"https://{m.group(1)}/{m.group(2).lstrip('/')}" if m else u


def repo_url() -> str:
    """The canonical address of the repository every box's checkout follows (puller 10): [client] repo_url when the server's config
    names one, else this checkout's origin as `canonical_url` writes it; "" when neither is known. Asked of git at most every minute."""
    cfg = str(_cfg.get("client", "repo_url", default="") or "").strip()
    if cfg:
        return canonical_url(cfg)
    if time.time() - _REPO["at"] > 60:
        rc, v = _git_out("remote", "get-url", "origin")
        _REPO.update(at=time.time(), v=canonical_url(v) if rc == 0 else "")
    return _REPO["v"]


def current(machine: str) -> dict[str, Any]:
    """What is current, in every poll's answer (puller 9, "keeping the box current"): the puller's VERSION in this checkout, this
    checkout's commit, and whether that machine's puller may update itself: [client] self_update (default true), and never the
    server box's own (its token is the hostname's, as client.py mint installs it: deploy.sh keeps that checkout). Since puller 10
    also `repo`, the repository's canonical address (repo_url; absent when unknown), which a clean, idle box takes for its origin.
    The puller reports back with its poll's facts: `stackshot`, its checkout commit (kept on the machine's record like `claude`),
    and `updates`, its attempts [{what, from, to, ok, at, reason}], which the Machines panel keeps; the card judges the checkout
    from `stackshot` against this answer's commit, not from the attempts alone."""
    on = _cfg.get("client", "self_update", default=True) is not False and machine != socket.gethostname()
    out: dict[str, Any] = {"puller": puller_current(), "stackshot": checkout_commit(), "self_update": bool(on)}
    repo = repo_url()
    if repo:
        out["repo"] = repo
    return out


def puller_lag(st: dict[str, Any] | None = None) -> list[tuple[str, str, str]]:
    """(hostname, reported, current) for every box whose puller reports a VERSION behind this checkout's, sorted by hostname
    (a box can run version 2 while the host runs version 5, when nothing provisioned it after a bump; the fleet tool's
    watchdog asks through `client.py puller-lag` and provisions them). A box that never reported a version is left out: it runs no puller
    to compare. Versions compare as numbers when both are, else any difference counts."""
    cur = puller_current()
    if not cur: return []
    out = []
    for name, m in (st or load())["machines"].items():
        rep = str(m.get("puller_version") or "")
        if not rep or rep == cur: continue
        behind = int(rep) < int(cur) if rep.isdigit() and cur.isdigit() else True
        if behind: out.append((str(m.get("fleet") or name), rep, cur))
    return sorted(out)


# ---------------------------------------------------------------------------- machines
def names_table() -> dict[str, tuple[str, str]]:
    """Lower-cased OS hostname and fleet name → (fleet name, letter), from paths.fleet_names (hostname ⇥ fleet name ⇥ letter)."""
    out: dict[str, tuple[str, str]] = {}
    try:
        for ln in open(_cfg.path("paths", "fleet_names"), encoding="utf-8"):
            c = [x.strip() for x in ln.rstrip("\n").split("\t")]
            if ln.strip() and not ln.startswith("#") and len(c) >= 3:
                out[c[0].lower()] = out[c[1].lower()] = (c[1], c[2])
    except Exception:
        pass
    return out


def _machine(st: dict[str, Any], machine: str) -> dict[str, Any]:
    """The machine's record, made on first sight. Its letter comes from the names table; a machine the table does not know
    takes the first letter nothing uses (c is the cloud's, the ids' own letter is the store's)."""
    m = st["machines"].get(machine)
    if m:
        return m
    fleet, letter = names_table().get(machine.lower(), (machine, ""))
    if not letter:
        used = {x.get("letter") for x in st["machines"].values()} | {v[1] for v in names_table().values()} | {"c", str(_cfg.get("ids", "letter") or "s")}
        letter = next((ch for ch in "abdefghijklmnopqrtuvwxyz" if ch not in used), "z")
    m = st["machines"][machine] = {"letter": letter, "fleet": fleet, "first": _iso()}
    return m


online = _lv.puller_online          # online(m, now): the machine's puller checked in within the online window


# ---------------------------------------------------------------------------- sessions
def placeholder(name: str, user: str = "", src: str = "") -> bool:
    """Whether `name` has the shape of the CLI's own placeholder: "<user>-<2 lowercase hex>" ("demo-3f"), user being the
    reporting machine's OS username (puller 4, client.py). With no user known, the generic shape counts only when the CLI
    did not call the name the user's (nameSource user), since then a real two-hex-suffixed name could not be told apart."""
    name = str(name or "").strip()
    if user:
        return re.fullmatch(re.escape(user) + r"-[0-9a-f]{2}", name) is not None
    return src != "user" and PLACEHOLDER_ANY.fullmatch(name) is not None


def _upsert(st: dict[str, Any], letter: str, rec: dict[str, Any], via: str, now: float) -> dict[str, Any] | None:
    uuid = str(rec.get("uuid") or rec.get("sessionId") or "").strip().lower()
    if not UUID.match(uuid):
        return None
    held = st["sessions"].get(uuid)
    if held and _lv.running(held) and held.get("machine") not in (None, letter):
        # a transcript id lives on one machine. While the machine that holds it is online and reported it lately, another
        # machine's claim is not taken: its token must not be able to draw that session's lines to itself.
        other = next((m for m in st["machines"].values() if m.get("letter") == held["machine"]), None)
        if other and _lv.puller_online(other, now) and _lv.reported_lately(held.get("seen"), now):
            return None
    s = st["sessions"].get(uuid) or {"registered": _iso(now)}
    name = str(rec.get("name") or "").strip()
    src = str(rec.get("name_source") or "").strip().lower()                  # the CLI's nameSource, when the client passes it on (puller 3, client.py)
    user = str(rec.get("user") or "").strip().lower()                        # the reporting machine's OS username (puller 4, client.py)
    old = str(s.get("name") or "")
    if name and old and (src in PROVISIONAL or (name != old and placeholder(name, user, src) and not placeholder(old, user, s.get("name_source") or ""))):
        # the CLI's placeholder on a relaunched pane, before the fleet tool's /rename ("demo-7a"; "demo-3f", sent with a
        # nameSource outside PROVISIONAL): the name on record stands
        if name != old and _REJECTED.get(uuid) != name:
            _REJECTED[uuid] = name
            log.info("placeholder refused: %s kept for %s, reported %r (name_source %r, user %r, via %s)", old, uuid, name, src, user, via)
        name = ""
    if name and old and name != old:
        if s.get("name_source") not in PROVISIONAL and not placeholder(old, user, s.get("name_source") or ""):
            s["previous_name"] = old; s["renamed_at"] = _iso(now)            # what the fleet tool records for a /rename (a placeholder was never the name)
        log.info("rename: %s → %s for %s (name_source %r, via %s)", old, name, uuid, src, via)
    elif name and not old:
        log.info("name: %s for %s (name_source %r, via %s)", name, uuid, src, via)
    if name:
        s["name"] = name; s["name_source"] = src
        _REJECTED.pop(uuid, None)
    s.pop("url", None); s.pop("bridged", None)                               # links come from the fleet tool's store (session_links), not the report
    for k in ("cli", "status"):
        if rec.get(k):
            s[k] = str(rec[k])
    if "stopped" in rec:                                                     # puller 7: why the pane's last turn ended in an error, "" when it did not (a hook's record has no key: left as it was)
        why = " ".join(str(rec.get("stopped") or "").split())[:200]
        if why:
            s["stopped"] = why
        else:
            s.pop("stopped", None)
    s["machine"] = letter; s["seen"] = _iso(now); s["via"] = via
    s.pop("gone", None)                                                      # reported: live again
    st["sessions"][uuid] = s
    return s


def register(machine: str, rec: dict[str, Any], now: float | None = None) -> dict[str, Any]:
    """One session says it exists (its hook). → its record; raises ValueError for a record with no transcript uuid."""
    now = time.time() if now is None else now
    with _locked():
        st = load(); m = _machine(st, machine)
        s = _upsert(st, m["letter"], rec, "hook", now)
        if s is None:
            raise ValueError("uuid = the session's transcript id (a UUID), and not one that is live on another machine")
        m["seen"] = _iso(now)
        _write(STATE, st); _materialize(st, now)
        return dict(s)


def seen(machine: str, uuid: str, now: float | None = None) -> bool:
    """A sign of life from a registered session (its Stop hook). False when the server does not know the session."""
    now = time.time() if now is None else now
    with _locked():
        st = load(); s = st["sessions"].get(str(uuid).lower())
        if not s:
            return False
        s["seen"] = _iso(now); s.pop("gone", None); _machine(st, machine)["seen"] = _iso(now)
        _write(STATE, st)
        return True


def checkin(machine: str, sessions: list[dict[str, Any]], facts: dict[str, Any] | None = None, partial: bool = False,
            now: float | None = None) -> dict[str, Any]:
    """A puller's poll: the machine is alive, and these are the sessions live on it. The list replaces what the server knew
    of that machine unless `partial` (a puller told to serve only some): a session not on it is marked gone and stays as
    last known (its identity; a pane between its /exit and its resume during a recycle comes back under the same id)."""
    now = time.time() if now is None else now
    with _locked():
        st = load(); m = _machine(st, machine)
        if not _lv.puller_online(m, now):
            m["online_since"] = _iso(now)
        m["seen"] = m["puller"] = _iso(now)
        for k in ("claude", "platform", "puller_version", "stackshot"):   # stackshot: the box's checkout commit (puller 9)
            if (facts or {}).get(k):
                m[k] = str(facts[k])
        if isinstance((facts or {}).get("updates"), list):                   # the helper's update attempts (optional; absent leaves the last list)
            m["updates"] = clean_updates(facts["updates"])
        keep = set()
        for rec in sessions or []:
            s = _upsert(st, m["letter"], rec, "puller", now)
            if s is not None:
                keep.add(str(rec.get("uuid") or rec.get("sessionId")).lower())
        keep = {u for u in keep if (st["sessions"].get(u) or {}).get("machine") == m["letter"]}
        if not partial:
            for u, s in st["sessions"].items():
                if s.get("machine") == m["letter"] and u not in keep:
                    s.setdefault("gone", _iso(now))
        _expire(st, now)
        _write(STATE, st); _materialize(st, now); flag_lag(st)
        return dict(m)


# ---------------------------------------------------------------------------- a machine's setup runs and update attempts
# A PC runs its own provisioning (at logon and daily) and reports how the run ended with `client.py setup-result` (POST
# /client/setup-result, the machine's token): the latest result is kept per machine as `setup` {at, ok, step, reason} and
# goes into the view's machine.json, so the board's Machines panel shows a failed run on that machine's column. The helper
# may also report its update attempts (its stackshot checkout's) in the poll's facts as `updates`, a list of {what, from, to, ok,
# at, reason}: kept as the last list reported, and drawn the same way when the latest attempt for a `what` failed.
STEP_MAX, REASON_MAX, UPDATES_MAX = 120, 500, 20


def _short(v: Any, n: int) -> str:
    return " ".join(str(v if v is not None else "").split())[:n]


def setup_result(machine: str, ok: bool, step: str = "", reason: str = "", now: float | None = None) -> dict[str, Any]:
    """A setup run on `machine` ended: ok, or failed at `step` for `reason`. Replaces the machine's last result. → the record.
    Raises ValueError for a failed run with no step: the board must be able to say which step failed."""
    now = time.time() if now is None else now
    step, reason = ("" if ok else _short(step, STEP_MAX)), _short(reason, REASON_MAX)   # a step names what failed: an ok run has none
    if not ok and not step:
        raise ValueError("a failed run names the step that failed (step)")
    rec = {"at": _iso(now), "ok": bool(ok), "step": step, "reason": reason}
    with _locked():
        st = load(); m = _machine(st, machine)
        m["setup"] = rec
        _write(STATE, st); _materialize(st, now)
    return dict(rec)


def clean_updates(rows: list[Any]) -> list[dict[str, Any]]:
    """The poll's facts.updates as the server keeps it: dicts only, the known fields, short strings, the last UPDATES_MAX."""
    out = []
    for r in rows:
        if not isinstance(r, dict) or not str(r.get("what") or "").strip():
            continue
        at = r.get("at")
        out.append({"what": _short(r.get("what"), 60), "from": _short(r.get("from"), 60), "to": _short(r.get("to"), 60),
                    "ok": r["ok"] if isinstance(r.get("ok"), bool) else None, "at": at if isinstance(at, (int, float)) and not isinstance(at, bool) else _short(at, 40),
                    "reason": _short(r.get("reason"), REASON_MAX)})
    return out[-UPDATES_MAX:]


def flag_lag(st: dict[str, Any] | None = None) -> bool:
    """Bring LAG_FLAG up to date with puller_lag(): rewritten only when its lines change (a poll that changes nothing leaves the
    file alone, so the path unit fires once per change), kept as an empty file when every box is current. True when it was
    written. Never raises: a flag that cannot be written leaves the fleet tool's own tick to find the box."""
    try:
        body = "".join(f"{h} {r} {c}\n" for h, r, c in puller_lag(st))
        try: old = LAG_FLAG.read_text()
        except OSError: old = None
        if old == body: return False
        tmp = LAG_FLAG.with_suffix(".tmp"); tmp.write_text(body); os.replace(tmp, LAG_FLAG)
        return True
    except Exception:
        return False


def _open_owners() -> set[str] | None:
    """The owners of the open board items, as stored (a transcript uuid or a pane name) and by owner_name, from the items
    store the server already keeps (anchors.items, imported here so this module stays free of the server side; anchors
    imports config alone). None when the store cannot be read: then nothing is pruned."""
    try:
        from stackshot.anchors import anchors
        out: set[str] = set()
        for t in anchors.items():
            if str(t.get("status") or "") not in _OPEN:
                continue
            m = t.get("metadata") or {}
            out.update(str(o) for o in (m.get("owner"), t.get("owner"), m.get("owner_name")) if o)
        from stackshot.fleet import sessions_registry as _sr                                   # an owner stored as a permanent id keeps the fleet rows of its transcripts and names
        for o in [x for x in out if _sr.is_perm_id(x)]:
            out.update(_sr.transcripts(o)); out.update(_sr.names_of(o))
        return out
    except Exception:
        return None


def _expire(st: dict[str, Any], now: float) -> None:
    """Presence expires, identity stays. A session on a machine with no puller behind it (hooks only) with no sign of life
    for TTL is marked gone, like one its puller stopped reporting (checkin). Once an hour, a record gone longer than
    HORIZON is forgotten — unless an open board item names it as owner, by uuid or by name, because the board must still
    draw that owner."""
    live = {m["letter"] for m in st["machines"].values() if _lv.puller_online(m, now)}
    for s in st["sessions"].values():
        if s.get("machine") not in live and not s.get("gone") and _lv.hook_session_expired(s.get("seen"), now):
            s["gone"] = _iso(now)
    if now - _ts(st.get("pruned")) < PRUNE_EVERY:
        return
    st["pruned"] = _iso(now)
    old = [u for u, s in st["sessions"].items() if s.get("gone") and _lv.past_horizon(s["gone"], now)]
    owners = _open_owners() if old else set()
    if owners is None:
        return
    for u in old:
        s = st["sessions"][u]
        if u not in owners and not ({s.get("name"), s.get("previous_name")} & owners):
            del st["sessions"][u]


def sessions_on(machine: str) -> dict[str, dict[str, Any]]:
    """uuid → record of the sessions the server holds for that machine (the inbox asks which keys a puller may be handed)."""
    st = load(); m = st["machines"].get(machine)
    return {u: s for u, s in st["sessions"].items() if m and s.get("machine") == m["letter"]}


# ---------------------------------------------------------------------------- session links, from the fleet tool
_LINKS: dict[str, Any] = {"dir": None, "sig": None, "map": {}}           # the last read of the fleet tool's store, kept while no file in it changes
_LINKS_WARNED: list[str] = [""]                                          # the problem last logged, so it is logged once and again only when it changes


def _links_dir() -> Path | None:
    """[client] session_links, read at use (a reload is live): None when it is set empty (no links at all)."""
    v = _cfg.get("client", "session_links")
    v = SESSION_LINKS_DEFAULT if v is None else str(v).strip()
    return Path(os.path.expanduser(v)) if v else None


def _links_warn(msg: str) -> None:
    if msg and msg != _LINKS_WARNED[0]:
        log.info("session links: %s", msg)
    _LINKS_WARNED[0] = msg


def session_links() -> dict[str, str]:
    """transcript uuid → link, from the fleet tool's store (<session_links>/<letter>/sessions.json, {uuid: {name, url, …}}):
    only rows whose url is an http(s) address (it becomes an href on the board: anything else is skipped and logged once, so
    every reader gets clean links). Keys are lowercased; look one up lowercased. Read again only when a file there changes
    (path, inode, mtime, size); a missing or unreadable store, or file, is logged once and gives no links from it. Never
    raises."""
    d = _links_dir()
    if d is None:
        _LINKS.update(dir=None, sig=None, map={}); _links_warn(""); return {}
    try:
        files = sorted(p for p in d.glob("*/sessions.json") if len(p.parent.name) == 1)
        sig = tuple((str(p), st.st_ino, st.st_mtime_ns, st.st_size) for p, st in ((p, p.stat()) for p in files))
    except OSError as e:
        files, sig = [], None; _links_warn(f"{d} not readable ({type(e).__name__}); sessions are named without a link")
    if not sig:
        if sig is not None: _links_warn(f"no <letter>/sessions.json under {d}; sessions are named without a link")
        _LINKS.update(dir=str(d), sig=None, map={}); return {}
    if _LINKS["dir"] == str(d) and _LINKS["sig"] == sig:
        return _LINKS["map"]
    out: dict[str, str] = {}; bad = []; junk = []
    for p in files:
        try:
            rows = json.load(open(p, encoding="utf-8"))
            if not isinstance(rows, dict): raise ValueError("not an object")
        except Exception:
            bad.append(p.parent.name); continue
        for u, row in rows.items():
            url = row.get("url") if isinstance(row, dict) else None
            if not isinstance(url, str) or not url.strip():
                continue
            url = url.strip()
            if not url.lower().startswith(("https://", "http://")):   # it lands in an href: a javascript: value or other junk is no link
                junk.append(f"{p.parent.name}/{str(u)[:8]}"); continue
            out.setdefault(str(u).strip().lower(), url)
    _links_warn("; ".join(x for x in (f"unreadable sessions.json under {d} for {', '.join(bad)}, its sessions named without a link" if bad else "",
                                      f"skipped {len(junk)} url(s) that are not http(s) under {d} ({', '.join(junk[:5])}), named without a link" if junk else "") if x))
    _LINKS.update(dir=str(d), sig=sig, map=out)
    return out


# ---------------------------------------------------------------------------- the view every reader uses
_VOLATILE = ("checked",)


def _same(old: dict[str, Any], new: dict[str, Any], rows: bool) -> bool:
    """Equal but for the times: a check-in alone must not look like a change of fact."""
    def strip(d):
        if rows:
            return {k: {x: y for x, y in v.items() if x != "seen"} for k, v in d.items() if isinstance(v, dict)}
        return {k: v for k, v in d.items() if k not in _VOLATILE}
    return strip(old) == strip(new)


def _view(st: dict[str, Any], now: float) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    operator = str(_cfg.get("fleet", "operator_session") or "")        # the one way to name the operator session
    out: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    links = session_links()
    for name, m in st["machines"].items():
        L = m["letter"]; on = _lv.puller_online(m, now)
        rows = {}
        for u, s in st["sessions"].items():               # the puller's list, and what the hooks registered: the machine's truth
            if s.get("machine") != L:
                continue
            r = {k: s[k] for k in ("name", "seen", "machine", "previous_name", "renamed_at", "status", "gone", "stopped") if s.get(k) is not None}
            r.setdefault("name", "")
            r["url"] = links.get(u.strip().lower(), "")       # the fleet tool's link (the map's keys are lowercased) for this transcript id, whatever the bridge does; none → the plain name
            rows[u] = r
        mj: dict[str, Any] = {"letter": L, "fleet": m.get("fleet") or name, "claude": m.get("claude") or "", "master": "", "master_session": "",
                              "checked": m.get("seen") or _iso(now)}
        if m.get("puller"):
            mj["online"] = {"ok": on, "since": m.get("online_since") if on else m["puller"]}
        for k in ("setup", "updates", "stackshot"):       # the last setup run, update attempts (setup_result, checkin) and the box's checkout commit, when reported
            if m.get(k):
                mj[k] = m[k]
        if operator:                                      # the running session of that name first, else the one gone most recently
            hit = next((u for u, s in sorted(rows.items(), key=lambda kv: (1 if kv[1].get("gone") else 0, -_ts(kv[1].get("gone")))) if s.get("name") == operator), "")
            if hit:
                mj["master"] = operator; mj["master_session"] = hit
        mj["source"] = "client"
        out[L] = (mj, rows)
    return out


def _materialize(st: dict[str, Any], now: float) -> bool:
    changed = False
    view = _view(st, now)
    for L, (mj, rows) in view.items():
        for fname, new, is_rows in (("machine.json", mj, False), ("sessions.json", rows, True)):
            p = VIEW / L / fname
            if p.exists() and _same(_read(p), new, is_rows):
                continue
            _write(p, new); changed = True
    if VIEW.is_dir():                                            # a machine that left the view (its record is gone)
        for d in VIEW.iterdir():
            if d.is_dir() and len(d.name) == 1 and d.name not in view:
                for f in d.glob("*.json"):
                    f.unlink()
                d.rmdir(); changed = True
    return changed


def tick(now: float | None = None) -> bool:
    """Bring the view up to date with time passing: a puller that stopped checking in makes its machine offline, a session
    with no sign of life for TTL is marked gone, a record past the horizon that no open item names is forgotten. Called by
    the server on its timer. → True when a fact changed."""
    now = time.time() if now is None else now
    with _locked():
        st = load(); _expire(st, now)
        _write(STATE, st)
        return _materialize(st, now)
