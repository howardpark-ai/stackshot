"""client_reads.py: the reads of the client API and the item facts they carry.

What a machine's hooks read: the page registry, the brief, the rulebook, a page's freshness, the open items a session moves (`items?key=`), the open items it is the contact of or an observer on (`involved?key=`), the owner's whole Your move group (`your-move`), the open asks a message named to a session this turn (`asks-named?key=&since=`, service/ask_named.py) and what the end-of-turn check needs about the items a reply names
(`item-facts`), served to a machine that proves itself with its own token, so a client needs no checkout of the repository. `_client_get` is the one entry of the read calls (web/routes/client_api.py is the thin
surface that serves it); `_client_items`, `_client_involved` and `_client_item_facts` read the store once per call; `_wait_fields`, `_then_label_raw`, `_item_mover_model`, `_item_mover`, `_item_mover_label`, `_basis_wait_of` and
`_item_list` are the readers of an item's mover, its `then`, its wait and its list that those two (and the wake passes, the update's hand-over and the tools that probe an item) share.

A read that looks at every open item can ask for the session roles once per item (`involved`: its contact lookup; `your-move`: the queue rule's front-agent test, while the rule is on), so `_client_get` runs those two inside a pass
memo (core/passmemo.py): the roles are worked out once for the request and dropped when it ends.

A service module: it reads the store and writes nothing. What it still reaches in the surface (the rulebook text, the renderer's brief and words, the notice's ruling, the report of holds, the page's time, the board's
ids as shown, the home page's list rule and its reading of a wait's end, the queue map and the time zone) comes through `Hooks` in service/passes_hooks.py, which web/wiring.py fills (web/server.py calls it at its import). A suite that replaces one of these functions sets it on this
module (and `time` here, since this module reads its own clock).

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import socket
import threading
import time
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core import instance as _inst
from stackshot.core import passmemo as _passmemo
from stackshot.core import store as _store
from stackshot.core.store import _item_files
from stackshot.fleet import fleet as _fleet
from stackshot.fleet import inbox_holds as _inbox_holds
from stackshot.fleet import liveness as _lv
from stackshot.fleet import sessions_registry as _sr
from stackshot.github import ghsync as _gh
from stackshot.model import item_project as _ip
from stackshot.model import model as _model
from stackshot.model import queued as _queued
from stackshot.model import states as _states
from stackshot.model.ids import _GID, _norm_id
from stackshot.model.needs import _needs_of, _needs_sessions, _observers_of
from stackshot.projects import page_upstream as _page_upstream
from stackshot.projects import projects as _prj
from stackshot.projects.project_registry import ROLES, _registry, _roles_sync_safe
from stackshot.service import agents as _agents
from stackshot.service import answer_handover as _handover
from stackshot.service import ask_named as _ask_named
from stackshot.service import contacts as _contacts
from stackshot.service import foryou as _fy
from stackshot.service import gates as _gates
from stackshot.service import item_read as _item_read
from stackshot.service.passes_hooks import hooks as _hooks
from stackshot.service.projects import _agent_name, _projects_list
from stackshot.service.store import _legacy_hold, _legacy_needs, _path
from stackshot.waits import dated_wait as _dw
from stackshot.waits import waiting as _wt


NO_SUCH_READ = "no such read"       # what the client API answers (404) to a verb no branch of _client_get took; the route reads it to tell a verb it handled from a guess


def _client_get(what: str, params: dict[str, str]) -> tuple[int, str, str]:
    """One read of the client API → (status, content type, body)."""
    if what == "registry":
        try:
            return 200, "application/json", _gates.registry_text()
        except Exception:
            return 503, "text/plain", "no registry yet"
    if what == "roles":                 # roles.json as the server keeps it; written here first if it is not there yet
        if not ROLES.exists():
            _roles_sync_safe()
        try:
            return 200, "application/json", ROLES.read_text(encoding="utf-8")
        except Exception:
            return 503, "text/plain", "no roles yet"
    if what == "projects-record":       # the project record alone, the value `state-files` carries as `projects` (client.py get projects-record)
        return _client_projects_record()
    if what == "state-files":           # the files a box that does not run the server reads from its own state folder; the puller of such a box keeps copies (puller 12, [client] mirror_server_state)
        return _state_files()
    if what == "rules":
        return 200, "text/markdown; charset=utf-8", _hooks().rules_text("full")
    if what == "brief":
        return 200, "text/plain; charset=utf-8", _hooks().rmod_render(str(_store.STORE), "brief")
    if what == "project":               # phase A: one project's record by id, full key or bare slug: {id, key, keeper, agents}
        key = str(params.get("key") or "").strip()
        if not key or len(key) > 200:
            return 400, "text/plain", "key = a project: its id (prj_<8 hex>), its page key or its bare slug"
        try:
            recs = _prj.refs(key, _registry("projects"))
        except ValueError as e:         # the id file is damaged and the registry has no id for the page: nothing is minted, the reader tries again
            return 503, "text/plain", f"the project record cannot be read right now: {e}"
        if not recs:
            return 404, "text/plain", f"no project {key!r}: an id (prj_<8 hex>), a page key (projects/<slug>, infra/<slug>) or a bare slug of a page in the registry"
        if len(recs) > 1:
            return 400, "text/plain", f"{key!r} is ambiguous: it names {' and '.join(r['key'] for r in recs)}; write the full key or the id"
        return 200, "application/json", json.dumps(recs[0], ensure_ascii=False)
    if what == "projects":              # the fleet tool's New session form: the listed projects of a scope, hidden ones too when q matches (projects?scope=<s>&q=<text>)
        return _projects_list(params)
    if what == "agent-name":            # would `post project-agent` take these names as new agents of a project (agent-name?key=<project>&names=<a,b,c>): the same checks, nothing written
        return _agent_name(params)
    if what == "page-ts":
        key = _prj.to_key(str(params.get("key") or "").strip("/"))
        if key.endswith(".md"):
            key = key[:-3]
        if not re.fullmatch(_cfg.page_dirs_re() + r"/[\w./-]+", key) or ".." in key:
            return 400, "text/plain", "key = a page key, " + " or ".join(f"{d}/<slug>" for d in _cfg.page_dirs())
        ts = int(_hooks().page_ts(key))
        since = str(params.get("since") or "")
        if re.fullmatch(r"[0-9]{1,12}", since) and ts < int(since):     # the caller is about to call the page owed: an edit the copy has not pulled yet may settle that (waits a few seconds at most)
            try:
                ts = max(ts, _page_upstream.edit_ts(key, int(since), wait=_page_upstream.WAIT))
            except Exception:  # noqa: BLE001  — the local copy's answer stands
                pass
        return 200, "application/json", json.dumps({"key": key, "ts": ts or None})
    if what == "items":
        return _client_items(str(params.get("key") or ""))
    if what == "involved":              # the open items a session is the contact of or an observer on, newest write first (client.py get involved <session>)
        with _passmemo.scope():         # its contact lookup asks for the session roles once per open item: built once for the read
            return _client_involved(str(params.get("key") or ""))
    if what == "asks-named":            # the standing asks the session wrote or moves that a message which reached it since its turn began names (service/ask_named.py; the end-of-turn board question)
        return _ask_named._client_asks_named(str(params.get("key") or ""), str(params.get("since") or ""))
    if what == "item-facts":
        return _client_item_facts(str(params.get("key") or ""), str(params.get("ids") or ""))
    if what == "item-record":           # one item's stored record, as the file holds it (client.py get item-record <id>)
        return _client_item_record(str(params.get("key") or ""))
    if what == "open-records":          # the stored records of the open items a session moves or is named on (client.py get open-records <session>)
        return _client_open_records(str(params.get("key") or ""))
    if what == "anchors-record":        # the anchors map as its file holds it (client.py get anchors-record)
        return _client_anchors_record()
    if what == "answer":                # a script reads the owner's latest board answer on an item (client.py get answer board#N)
        return _handover._client_answer(str(params.get("key") or ""))
    if what == "notice":                # a script reads what the router did with a notice (client.py get notice <id>): the text get(item_id=<id>) shows
        nid = _hooks().notice_asked("notice " + str(params.get("key") or "").strip())
        if not nid:
            return 400, "text/plain", "key = a notice id: the six hex characters a message to a project returns (\"notice a1b2c3\")"
        try:
            return 200, "text/plain; charset=utf-8", _hooks().notice_report(nid)
        except ToolError as e:
            return 404, "text/plain", str(e)
    if what == "your-move":             # the owner's whole Your move group, the home page's own list with no cap (client.py get your-move)
        with _passmemo.scope():         # with the queue rule on, the group asks for the session roles once per item an agent moves: built once for the read
            return _client_your_move()
    if what == "holds":                 # the open items on hold whose hold names no reason: read only, each mover releases its own
        return 200, "text/plain; charset=utf-8", _hooks().holds_report()
    if what == "inbox-holds":           # what is held on sessions' inboxes (fleet/inbox_holds.py): {holds: [{kind, key, origin, since, expires}]}, one key's with ?key=
        return 200, "application/json", json.dumps(_inbox_holds.listing(str(params.get("key") or "").strip()), ensure_ascii=False)
    if what == "inbox-waiting":         # does a line wait for this session (?key=<name>[,<transcript id>]): {keys, hub, msg, waiting, held}; held or not it counts
        keys = [k.strip() for k in str(params.get("key") or "").split(",") if k.strip()]
        if not keys or len(keys) > 20:
            return 400, "text/plain", "key = the session's name, or its name and transcript id separated by a comma"
        return 200, "application/json", json.dumps(_inbox_holds.waiting(keys), ensure_ascii=False)
    if what == "for-you":               # the For you list: {"generated", "rows": newest first, "flags": {item: watch | mute}} (the fleet tool's items sheet reads it)
        return 200, "application/json", json.dumps(_fy.payload(_gh.shown), ensure_ascii=False)
    return 404, "text/plain", NO_SUCH_READ + ": registry | rules | brief | project?key=<id | page key | slug> | projects?scope=<" + "|".join([*_prj.scopes(), "all"]) + r">[&q=<text>] | agent-name?key=<project>&names=<a,b,c> | page-ts?key=<page key or project id> | items?key=<session> | involved?key=<session> | item-facts?key=<session>&ids=<id,…> | asks-named?key=<session>&since=<epoch> | item-record?key=<item id> | open-records?key=<session> | anchors-record | projects-record | answer?key=<item id> | notice?key=<notice id> | holds | inbox-holds[?key=<key>] | inbox-waiting?key=<name[,id]> | for-you | your-move | whoami | config | roles | state-files"


def _json_file(path: Any) -> Any:
    """A state file's JSON, None when it is absent or unreadable (a half-written file never is: the writers rename a finished one into place)."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _projects_record() -> Any:
    """The project record as published (projects.json, parsed, nothing else done to it), None when it is absent or does not read. `state-files` carries this value as `projects` and `projects-record` answers it alone."""
    return _json_file(_prj.published_path())


def _client_projects_record() -> tuple[int, str, str]:
    """`projects-record`: exactly the value `state-files` carries under `projects` (the project record, one JSON object), without the other files. 503 when the file is absent, does not read or is no object (never a smaller or empty answer)."""
    rec = _projects_record()
    if not isinstance(rec, dict):
        return 503, "text/plain", f"the project record {_UNREADABLE}"
    return 200, "application/json", json.dumps(rec, ensure_ascii=False)


def _state_files() -> tuple[int, str, str]:
    """`get state-files` -> {host, generated, projects, fleet, versions, advertised_commit}: the server's published files as a box that does not run the server needs them in its own
    state folder. `projects` is projects.json, `fleet` is {letter: {machine, sessions}} (clients/fleet/<letter>/machine.json and sessions.json, a letter only when both read), `versions` is
    site/versions.json and `advertised_commit` the text of clients/advertised-commit; one that is not there is null (or "" for the commit), never an empty stand-in. `host` is the server's
    own hostname: the puller writes nothing on the box that carries it. roles.json is `get roles`. Read only; the machine token the route checks is the gate."""
    broken = set(_fleet.sessions_unreadable())
    fleet = {L: {"machine": _fleet.read(L, "machine"), "sessions": _fleet.read(L, "sessions")} for L in _fleet.letters() if L not in broken}
    try:
        sha = _cfg.state("clients", "advertised-commit").read_text(encoding="utf-8").strip()
    except OSError:
        sha = ""
    out = {"host": socket.gethostname(), "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "projects": _projects_record(), "fleet": {L: v for L, v in fleet.items() if v["machine"]},
           "versions": _json_file(_cfg.state("site", "versions.json")), "advertised_commit": sha}
    return 200, "application/json", json.dumps(out, ensure_ascii=False)


def _wait_fields(gid: str, it: dict[str, Any], ctx: "_agents._WaitCtx") -> dict[str, Any]:
    """The wait fields on an item as the items API carries them (the web board and the fleet tool read them): mover {kind, who, via?}. The fields that
    carried a computed expected-by time stay in the answer so that a reader written against them does not break, always empty (expected_by null, wait "",
    overdue null): they go in a later release."""
    try:
        mv = dict(ctx.mover(gid, it))
    except Exception:  # noqa: BLE001  — a reading that fails never fails the list
        return {}
    if mv.get("kind") == _wt.OWNER_KIND:
        mv["kind"] = _cfg.owner_mover_kind()      # [items_api] owner_mover_kind: the word a reader of the API matches for the owner's move ("legacy" by default, or "owner")
    elif mv.get("kind") == "session":
        mv["who"] = _sr._session_label(str(mv.get("who") or "")) or str(mv.get("who") or "")
    if mv.get("via"):
        mv["via"] = _gh.shown(str(mv["via"]))
    return {"mover": mv, "expected_by": None, "wait": "", "overdue": None}


_ROLE_MOVER, _ROLE_THEN, _ROLE_NEEDS = "mover", "then", "needs"     # the values of a client items row's `roles` (pages.py words them)


_VIEW_TTL = 30.0        # s: the longest a board view is served whatever else holds. A backstop only: the files are in the stamp, the dates the rows read in `valid_until` (`_next_edge`, `_clock_edge`) and the queue map is compared at each read; no input is left to this bound
_VIEW_FRESH_NS = 200_000_000   # a file written within this long before its stamp is read could be written again with the same stamp: such a view is never kept
_VIEW_KEYS_MAX = 512    # the answers kept per view, one per asking session; a view that has this many serves the others without keeping them
_VIEW_BUILD = threading.Lock()      # one rebuild at a time: a reader that finds the view stale waits here, then looks again (a hit never takes it)
_VIEW: dict[str, "_ItemsView | None"] = {"v": None}
_EDGE_FIELDS = ("until", "wake", "ask_by")      # the metadata fields that hold a date the model, the dated-wait rule or a relay's ask-by day reads against the clock


def _board_stamp() -> tuple[frozenset, int]:
    """(what the items view stands on, the newest mtime of it in ns). The stat of every item file and every file of the store (the registry, anchors, project record: `name, mtime_ns, size, inode`),
    the fleet view's machine and session files, and the signature of the session registry as the registry's own cache holds it (`sessions_registry.signature`: the registry trusts its look at its directory for a
    second, and a view must not stand on a newer one than the reads it is built from go through). A file added, removed, rewritten or replaced reads as another stamp; a file the readers never open is not looked at.
    Never raises."""
    parts: list[tuple] = []
    newest = 0

    def files(d: Any, tag: str, keep: Any) -> list[str]:
        nonlocal newest
        subdirs: list[str] = []
        try:
            with os.scandir(d) as it:
                for e in it:
                    n = e.name
                    if n[:1] == ".":
                        continue
                    try:
                        if e.is_dir():
                            subdirs.append(n)
                            continue
                        if not keep(n):
                            continue
                        st = e.stat()
                    except OSError:         # gone between the listing and the stat: the next stamp lists it again
                        continue
                    parts.append((tag, n, st.st_mtime_ns, st.st_size, st.st_ino))
                    newest = max(newest, st.st_mtime_ns)
        except OSError:
            parts.append((tag, None))
        return subdirs

    letters = lambda names: [n for n in names if len(n) == 1 and n.isalpha()]
    for L in letters(files(_store.STORE, "store", lambda n: n.endswith(".json"))):
        files(_store.STORE / L, "store/" + L, lambda n: n.endswith(".json"))
    for L in letters(files(_fleet.FLEET_DIR, "fleet", lambda n: False)):
        files(_fleet.FLEET_DIR / L, "fleet/" + L, lambda n: n in ("machine.json", "sessions.json"))
    try:
        sig = _sr.signature()
    except Exception:  # noqa: BLE001
        sig = None
    parts.append(("registry", sig))
    for f in sig or ():
        newest = max(newest, f[2] or 0)
    return frozenset(parts), newest


def _next_edge(m: dict[str, Any], now: float, soon_s: float) -> float | None:
    """The first instant after `now` at which a date of an item (`_EDGE_FIELDS`) can change what a row of it says: the date itself, read as a wake (the start of the day or the minute) and as a due day (the end of
    the day), and `soon_s` before it, where a doing item's wake stops being far enough ahead to read as a wait (dated_wait.of and held_wait). None when the item holds no such date."""
    edge: float | None = None
    for k in _EDGE_FIELDS:
        v = m.get(k)
        if not v:
            continue
        for e in (_wt.wake_epoch(v), _wt.due_epoch(v)):
            for at in ((e, e - soon_s) if e is not None else ()):
                if at > now and (edge is None or at < edge):
                    edge = at
    return edge


def _clock_edge(now: float) -> float:
    """The first instant after `now` at which the clock alone, with no file written, changes an answer, for every input the rows read except the items' own dates: the next midnight in the instance zone (the
    dated-wait rule reads a step's day against today), the moment a session that is gone leaves the fleet's grace (its name stops resolving: fleet.by_name), and the moment the session registry stops standing in for
    a file that does not read (its `stale_until`). An item whose date cannot be read drops the view at once (in `_items_pass`: that input's own bound is now, so that board is built at every read, as the per-read path did). The queue
    map (a mover's second item quiet for an hour) has no edge here: its own cache renews it every `_QUEUE_TTL` seconds and `_ItemsView.holds` compares the view's copy with the map at each read."""
    zone = _cfg.tz()
    edge = dt.datetime.combine(dt.datetime.fromtimestamp(now, zone).date() + dt.timedelta(days=1), dt.time(), zone).timestamp()
    grace = _lv.grace()
    for r in _fleet.sessions().values():
        t = _lv.ts(r.get("gone")) if isinstance(r, dict) and r.get("gone") else 0.0
        if t and now < t + grace < edge:
            edge = t + grace
    su = _sr.load().stale_until
    if su != float("inf"):
        edge = min(edge, now + max(0.0, su - time.monotonic()))
    return edge


class _ItemsView:
    """The board read once for every asking session: per open item its parsed file and the identities of who moves it, who takes it after the answer and who its needs name (the part that asks
    nothing of the asker), the fleet's names as they were then, the queue map the rows read, and, built when a session first needs them, each item's row. `body_for(key)` is one session's answer.
    `valid_until` is the first instant the clock alone changes an answer (`_next_edge`, `_clock_edge`); the view is not served from then on."""
    __slots__ = ("stamp", "at", "nm", "ctx", "entries", "rows", "bodies", "lock", "queue", "queue_on", "cfg", "valid_until", "sc")

    def __init__(self, stamp: frozenset, at: float, nm: Any, ctx: Any, entries: list, queue: dict[str, str], queue_on: bool, valid_until: float) -> None:
        self.stamp, self.at, self.nm, self.ctx, self.entries, self.queue, self.queue_on, self.valid_until = stamp, at, nm, ctx, entries, queue, queue_on, valid_until
        self.cfg = _cfg.CFG
        self.rows: dict[str, dict[str, Any]] = {}
        self.bodies: dict[str, str] = {}
        self.lock = threading.Lock()
        self.sc: tuple[dict, dict, dict] | None = None      # the registry, id file and marks the rows' group is read from, taken at the first row

    def holds(self, stamp: frozenset, now: float) -> bool:
        """Is this view what the per-read path would answer now: the files it stands on are as they were, the running config is the one it was built under, no date it read has come, it is younger than `_VIEW_TTL`,
        and the queue map the rows read (a derived reading of the board that its own cache renews every few seconds, `_queue_map`) is the map now."""
        return (self.stamp == stamp and self.cfg is _cfg.CFG and 0 <= now - self.at < _VIEW_TTL and now < self.valid_until
                and (not self.queue_on or self.queue == _hooks().queue_map()))

    def row(self, gid: str, p: Any, it: dict[str, Any]) -> dict[str, Any]:
        """The session-free part of an item's row (everything but `roles` and `role`), built once per view."""
        r = self.rows.get(gid)
        if r is None:
            if self.sc is None:
                self.sc = _scope_ctx()
            r = self.rows[gid] = _item_row(gid, p, it, self.ctx, self.queue, self.sc)
        return r

    def selected(self, k: str) -> list[tuple[str, Any, dict[str, Any], list[str], bool]]:
        """The one rule of which open items a session is asked about: [(gid, path, item, roles, named in needs)] of every item the session moves, takes after the answer (`then`) or is named on in its needs,
        in the store's order. `items` rows and `open-records` both read it."""
        nm = self.nm
        me = {k, _anc.canonical(k, nm)}
        me |= {nm.get(x, "") for x in list(me)}
        me.discard("")
        out = []
        for gid, p, it, mover_ids, then_ids, linked_ids in self.entries:
            is_mover, is_then, linked = bool(mover_ids & me), bool(then_ids & me), bool(linked_ids & me)
            if not (is_mover or is_then or linked):
                continue
            out.append((gid, p, it, ([_ROLE_MOVER] if is_mover else []) + ([_ROLE_THEN] if is_then else []) + ([_ROLE_NEEDS] if linked else []), linked))
        return out

    def body_for(self, k: str) -> str:
        with self.lock:
            hit = self.bodies.get(k)
            if hit is not None:
                return hit
            out = [{**self.row(gid, p, it), "roles": roles, **({"role": "agent"} if linked else {})} for gid, p, it, roles, linked in self.selected(k)]
            body = json.dumps({"items": out}, ensure_ascii=False)
            if len(self.bodies) < _VIEW_KEYS_MAX:
                self.bodies[k] = body
            return body


def _items_pass(stamp: frozenset) -> _ItemsView:
    """One scan of the store for every session: each open item's file is read once, its mover, `then` and the sessions its needs name are resolved to the identities a session may be asked by, and the first instant
    a date of the board changes an answer is worked out (the item's own dates and the clock's: `_next_edge`, `_clock_edge`)."""
    nm = _anc.names()
    now = time.time()
    queue_on = _queued.enabled()
    queue = dict(_hooks().queue_map()) if queue_on else {}     # read once, as the rows are built from it (the per-read path read it at each row)
    ctx = _agents._WaitCtx(now)                # every open item has a mover, listed whatever wait it is in
    canon: dict[str, frozenset] = {}
    soon_s = _wt.dated_wait_min_hours() * 3600.0
    edge = _clock_edge(now)

    def ids(who: str) -> frozenset:
        r = canon.get(who)
        if r is None:
            r = canon[who] = frozenset({who, _anc.canonical(who, nm)})
        return r
    entries = []
    for gid, p in _item_files():
        try:
            with open(p, encoding="utf-8") as f:
                it = json.load(f)
        except Exception:
            continue
        if not isinstance(it, dict):
            continue
        _legacy_hold(it); _legacy_needs(it); _ip.read_through(it)
        if it.get("status") != "open":
            continue
        m = it.get("metadata") or {}
        try:
            e = _next_edge(m, now, soon_s)
        except Exception:  # noqa: BLE001  — a date that cannot be read drops the view at once: it is built again at the next read
            e = now
        if e is not None and e < edge:
            edge = e
        linked_ids = frozenset().union(*[ids(ag) for ag in _needs_sessions(m)])      # named in its needs
        mv_, alive_ = _item_mover_model(dict(it, gid=gid))
        mover_ids = ids(mv_) if (alive_ and mv_ and not _model.is_owner(mv_)) else frozenset()      # the item's mover, by its needs, its stored mover or the project's default (builder, else -main agent)
        th_ = _then_label_raw(dict(it, gid=gid))
        then_ids = ids(th_) if th_ else frozenset()
        if mover_ids or then_ids or linked_ids:
            entries.append((gid, p, it, mover_ids, then_ids, linked_ids))
    return _ItemsView(stamp, now, nm, ctx, entries, queue, queue_on, edge)


def _items_view() -> _ItemsView:
    """The view of the board as it stands: the kept one while it holds (`_ItemsView.holds`), else one new scan (one at a time: the readers that arrive meanwhile wait for it and take it). The stamp is read before the scan,
    so a write during the scan reads as a change at the next call. A view built from a file written within `_VIEW_FRESH_NS` of that read is served but not kept."""
    stamp, _newest = _board_stamp()
    v = _VIEW["v"]
    if v is not None and v.holds(stamp, time.time()):
        return v
    with _VIEW_BUILD:
        stamp, newest = _board_stamp()
        v = _VIEW["v"]
        if v is not None and v.holds(stamp, time.time()):
            return v
        t_ns = time.time_ns()
        v = _items_pass(stamp)
        _VIEW["v"] = v if t_ns - newest >= _VIEW_FRESH_NS else None
        return v


def _scope_ctx() -> tuple[dict, dict, dict]:
    """(the page registry as the home page holds it (the record laid over the pages, then the agents only the record holds: with_pending), key -> id, the marks by id) that an item's group is read from, taken once for a read or a view."""
    try:
        ids = _prj.ids_by_key()
    except ValueError:
        ids = {}                                   # a damaged id file: the registry's own copy of the id answers
    return _prj.with_pending(_anc.registry()), ids, _prj.marks()


def _item_scope(it: dict[str, Any], sc: tuple[dict, dict, dict]) -> str:
    """An item's group: the scope of the board row its page rolls up to (`anchors.item_scope`, shared with the text renderer's `Board.item_scope`; the home page keeps its own copy of the rule), so it is one of the names in [project_scopes] order."""
    return _anc.item_scope(it.get("metadata") or {}, *sc)


def _item_row(gid: str, p: Any, it: dict[str, Any], ctx: "_agents._WaitCtx", queue: dict[str, str] | None = None, sc: tuple[dict, dict, dict] | None = None) -> dict[str, Any]:
    """An open item's row of the items list, without the asking session's `roles` and `role`. `sc` is `_scope_ctx()`, read once by the caller that builds many rows."""
    m = it.get("metadata") or {}
    try:
        su = float(it.get("state_updated") or 0) or None
    except (TypeError, ValueError):
        su = None
    try:
        up = float(it.get("updated") or 0) or None    # any write, a filing edit too (a priority or subject edit moves only this; an ask-only write on an open item adds the decision need, a state change)
    except (TypeError, ValueError):
        up = None
    st_, st_derived = _states.of(it, lambda i_: _item_read._after_open(i_.get("metadata") or {}))     # the item's stored state, or the one derived from its fields (not sent)
    return {"gid": gid, "shown": _gh.shown(gid), "subject": str(it.get("subject") or ""), "needs": _hooks().shown_needs(_needs_of(m)),
            **({"state": st_, "state_fields": _states.carry_of(it)} if not st_derived else {}),      # only an item that stores a state carries it: the word an item reads as is not sent
            "contact": _contacts._contact_label(dict(it, gid=gid)),
            "next": str(m.get("next") or ""), "state_updated": su, "confirmed": _hooks().rmod_confirmed_at(it, p),
            "updated": up, "held": _item_read._is_parked(it) or bool(_item_read._after_open(m)) or _basis_wait_of(dict(it, gid=gid)), "list": _item_list(dict(it, gid=gid), queue), **_wait_fields(gid, it, ctx),
            "scope": _item_scope(it, sc or _scope_ctx())}


def _client_items(key: str) -> tuple[int, str, str]:
    """`items?key=<session>`: the open items a session moves, for the end-of-turn board check in
    pages.py. key = the asking session as its hook knows it: a transcript uuid, a cse_ id or a pane name. An item is its own when
    it moves (its needs, its stored mover, or the project's builder, else its -main agent when nothing names one) or takes after the answer (`then`: the creator is no
    one's), or when it names the session in its needs, with role "agent" (the key the hooks have read since an earlier change). Every row carries `roles`: the asking session's live roles on the item, from "mover", "then" and "needs" (named in it); the alive item a session moves without keeping or being named is listed too. One pass over the store serves every session (`_items_view`: kept while the files it stands on, the dates it read against the clock and the queue map are as they were, `_VIEW_TTL` seconds at most), one read of
    the fleet's names. Held items, items that wait on an open item (after) and doing items the board lists as waiting for a wake that states its reason (wait_basis) are listed with held: true (the hook skips them). Every row carries `list`: the home page's list the item is in, "your-move", "agents" or "waiting" (home.list_of), the key the fleet tool's items sheet groups by, so it shows the page's three groups; never empty (an item the page cannot place is in "agents", as there)."""
    k = str(key or "").strip()
    if not k or len(k) > 200 or any(c in k for c in "\r\n\t"):
        return 400, "text/plain", "key = the asking session: its transcript uuid, cse_ id or pane name"
    return 200, "application/json", _items_view().body_for(k)


def _back_on(item: dict[str, Any]) -> str | None:
    """The day a waiting item comes back, "YYYY-MM-DD": the end date the home page's Waiting row shows after "until" (web.home.end_of, the one reader the row and its sort use), on the item model as the board displays it.
    A stored date is a wall-clock day of the instance's own time zone, with or without a time of day, so its first ten characters are the day and nothing is converted. None when the item is not waiting, its wait ends on no date or
    the reading fails (the queue is not read: a queued item's wait has no date)."""
    try:
        end = _hooks().home_end_of(_model.view(item, _item_read._model_of(item), after_open=lambda i_: _item_read._after_open(i_.get("metadata") or {})))
    except Exception:  # noqa: BLE001  — a reading that fails gives no day, never a failed answer
        return None
    return str(end).strip()[:10] if end else None


def _client_involved(key: str) -> tuple[int, str, str]:
    """`involved?key=<session>`: the open items the session is the contact of or an observer on, whoever moves them, newest write first -> {"items": [{shown, subject, url, mover, contact, observers, list, held, until, state_updated, updated}]}.
    key = a session as `items?key=` reads it (a transcript uuid, a cse_ id, a pane name or a permanent id), matched the way that read matches a session: the key and what it resolves to (`anchors.canonical`) against the
    stored name and what that resolves to, so a renamed session is still found. An item matches when its contact (the live one: the stored contact while it is still a front agent, else the project's -main agent, as the row's
    `contact` shows it) is the session, or the session is one of its observers (`metadata.observers`); closed items never. A row carries the fields `items` rows carry under the same names and in the same format (`shown`, `subject`,
    `contact`, `list` "your-move" | "agents" | "waiting", `held`, `state_updated`, `updated`: all taken from `_item_row`, so the two reads cannot disagree), `mover` as `item-facts` gives it (the name of whoever the item model says
    moves the item now; for a waiting item who takes it when the wait ends; the owner as the model names him; "" for none: not the `mover` object of an `items` row, the older reading that still names a session for an item the owner moves),
    `url` as `your-move` gives it (the item's page under the board address, the path alone when the instance has none), `observers`, the item's observers by the name each session has now, and `until`, the day a held item comes back
    (`_back_on`; null for an item that is not held, whatever date it stores, and for a held one whose wait ends on no date). The order is the last write first (`updated`, an item that stores none
    by `state_updated`), items of one time in the store's order. No cap, as `items` has none. An unknown session is `{"items": []}`; a blank, over-long or multi-line key is 400, as for `items`. One scan of the store per call, which
    reads the same files and applies the same readers as `_items_pass`; it writes nothing."""
    k = str(key or "").strip()
    if not k or len(k) > 200 or any(c in k for c in "\r\n\t"):
        return 400, "text/plain", "key = the session: its transcript uuid, cse_ id or pane name"
    nm = _anc.names()
    now = time.time()
    me = {k, _anc.canonical(k, nm)}
    me |= {nm.get(x, "") for x in list(me)}
    me.discard("")
    canon: dict[str, frozenset] = {}

    def is_me(who: str) -> bool:
        r = canon.get(who)
        if r is None:
            r = canon[who] = frozenset({who, _anc.canonical(who, nm)})
        return bool(r & me)
    queue_on = _queued.enabled()
    queue = dict(_hooks().queue_map()) if queue_on else {}
    ctx = _agents._WaitCtx(now)
    base = _inst.BOARD_URL.rstrip("/")
    sc = _scope_ctx()
    found: list[tuple[float, dict[str, Any]]] = []
    for gid, p in _item_files():
        try:
            with open(p, encoding="utf-8") as f:
                it = json.load(f)
        except Exception:
            continue
        if not isinstance(it, dict):
            continue
        _legacy_hold(it); _legacy_needs(it); _ip.read_through(it)
        if it.get("status") != "open":
            continue
        m = it.get("metadata") or {}
        contact = _contacts._contact_of(m)
        observers = _observers_of(m)
        if not ((contact and is_me(contact)) or any(is_me(o) for o in observers)):
            continue
        r = _item_row(gid, p, it, ctx, queue, sc)
        names = list(dict.fromkeys(_sr._session_label(o) or o for o in observers))
        row = {"shown": r["shown"], "subject": r["subject"], "url": f"{base}/items/{_gh.href_id(gid)}", "mover": _item_mover_label(dict(it, gid=gid), nm), "contact": r["contact"], "observers": names,
               "list": r["list"], "held": r["held"], "until": _back_on(dict(it, gid=gid)) if r["held"] else None, "state_updated": r["state_updated"], "updated": r["updated"],
               "scope": r["scope"]}
        found.append((float(r["updated"] or r["state_updated"] or 0.0), row))
    found.sort(key=lambda t: -t[0])
    return 200, "application/json", json.dumps({"items": [row for _t, row in found]}, ensure_ascii=False)


def _client_your_move() -> tuple[int, str, str]:
    """`your-move`: every open item in the owner's Your move group, whoever the item's session mover is or whether it has one -> {"items": [{shown, subject, url, ask, updated, scope}], "group": {<language code>: <the group's name>}}, the items in the order the home page draws the
    group (the brief's first five lines are the head of the same list). The group is the renderer's own (`Board.your_move`, built on `home_pairs`, the call the home page, board.md and the brief all take their lists from), so
    this read has no selection rule of its own and cannot drift from them. `ask` is the open ask line, "" for an item with none; `updated` is the item's last write in epoch seconds; `scope` is the name of the subsection the home page draws the item in (`Board.item_scope`). No cap: the group is as long as the queue,
    and a row is a few hundred bytes. An empty group is `{"items": [], "group": {...}}`. `group` is the heading the home page draws over the list, in each language of the string table (`your_move_group`, the page's own
    lookup asked once per language); a language with no catalog on the install gets the English text, as the page does."""
    return 200, "application/json", json.dumps({"items": _hooks().rmod_your_move(str(_store.STORE)), "group": _hooks().rmod_your_move_group()}, ensure_ascii=False)


def _then_label_raw(item: dict[str, Any]) -> str:
    """The session id or name an alive item's `then` (stored, else the model's) or a waiting item's post-wake mover names; "" for none or the owner."""
    try:
        mod = _item_read._model_of(dict(item, gid=str(item.get("gid") or item.get("id") or "")))
        who = mod.then if mod.state == _model.ALIVE else ((mod.then if _model.is_owner(mod.wait.mover) else mod.wait.mover) if mod.wait else "")      # a waiting item's picker takes the role `then` (or, when he picks it up, the `then` beside him)
    except Exception:  # noqa: BLE001
        who = ""
    return "" if (not who or _model.is_owner(who)) else who


def _item_mover_model(item: dict[str, Any]) -> tuple[str, bool]:
    """(who moves the item now as _item_mover reads it, whether the item is alive): "" and False when the reading fails or the item is closed."""
    try:
        mod = _item_read._model_of(dict(item, gid=str(item.get("gid") or item.get("id") or "")))
        alive = mod.state == _model.ALIVE
        return (mod.mover if alive else (mod.wait.mover if mod.wait else "")), alive
    except Exception:  # noqa: BLE001
        return "", False


def _basis_wait_of(item: dict[str, Any]) -> bool:
    """Is the open item a doing item the board lists as waiting for a wake that states its reason (dated_wait.basis_wait)? The end-of-turn board question skips it like a held one."""
    try:
        return _dw.basis_wait(item, time.time(), lambda i_: _item_read._after_open(i_.get("metadata") or {})) is not None
    except Exception:  # noqa: BLE001
        return False


def _item_list(item: dict[str, Any], queue: dict[str, str] | None = None) -> str:
    """Which of the home page's three lists an open item is in, as the wire word: "your-move", "agents" or "waiting" (home.list_of on the model's reading). The home page's own
    rule for an item it cannot place (a failed reading, or a dead one) is Agents at work (home.classify), so the field is never empty: the items sheet groups as the page does."""
    try:
        it = dict(item, gid=str(item.get("gid") or item.get("id") or ""))
        vw = _model.view(it, _item_read._model_of(it), after_open=lambda i_: _item_read._after_open(i_.get("metadata") or {}))
        which = _hooks().home_list_of(_queued.overlay(vw, (_hooks().queue_map() if queue is None else queue).get(it["gid"], "")))     # a doing item with a far wake and every step dated is listed as waiting, and one queued behind its mover's other item
    except Exception:  # noqa: BLE001
        which = ""
    return which or _hooks().home_agents()


def _item_mover(item: dict[str, Any]) -> str:
    """Who moves the item now, as stored or derived (the model's mover, else for a waiting item who takes it when the wait ends); "" for a closed item or when the reading fails."""
    return _item_mover_model(item)[0]


def _item_mover_label(item: dict[str, Any], names: dict[str, str], who: str | None = None) -> str:
    """The mover as a person reads it; "" for a closed item or when the reading fails. `who` = the mover when the caller has read it already (_item_mover)."""
    try:
        who = _item_mover(item) if who is None else who
        if not who or _model.is_owner(who):
            return who
        return names.get(_anc.canonical(who, names), "") or _sr._session_label(who)
    except Exception:  # noqa: BLE001
        return ""


def _client_item_facts(key: str, ids: str) -> tuple[int, str, str]:
    """`item-facts?key=<session>&ids=g7,g8`: what the end-of-turn check needs about the items a reply's Board lines
    name, so it can note a line about an item the session is neither the mover nor the `then` of nor the linked agent of, or one already closed (a
    session that kept reporting on a closed item). Per known id: status, mover (the mover's name), mover_me (the asking session
    is the mover), mine (the session is its `then`), agent (the item names the session in its needs), project (its metadata.project, for the pane's
    page gate when a portal write's reply did not say it), and for a closed item its close time in words and outcome. An
    unknown id is left out."""
    k = str(key or "").strip()
    if not k or len(k) > 200 or any(c in k for c in "\r\n\t"):
        return 400, "text/plain", "key = the asking session: its transcript uuid, cse_ id or pane name"
    want = [g.strip().lower().replace("#", "") for g in str(ids or "").split(",") if g.strip()][:20]
    if not want or not all(_GID.match(g) for g in want):
        return 400, "text/plain", "ids = item ids, comma-separated (at most 20)"
    nm = _anc.names()
    me = {k, _anc.canonical(k, nm)}
    me |= {nm.get(x, "") for x in list(me)}
    me.discard("")
    out = {}
    sc = _scope_ctx()
    for g in dict.fromkeys(want):
        p = _path(g)
        try:
            with open(p, encoding="utf-8") as f:
                it = json.load(f)
        except Exception:
            continue
        if not isinstance(it, dict):
            continue
        _legacy_needs(it)
        m = it.get("metadata") or {}
        mover = _item_mover(it)
        th_ = _then_label_raw(dict(it, gid=g))
        row = {"status": str(it.get("status") or ""), "shown": _gh.shown(g),
               "mover": _item_mover_label(it, nm, mover), "mover_me": bool(mover and ({mover, _anc.canonical(mover, nm)} & me)),
               "mine": bool(th_ and ({th_, _anc.canonical(th_, nm)} & me)), "agent": any({ag, _anc.canonical(ag, nm)} & me for ag in _needs_sessions(m)),
               "project": str(m.get("project") or ""), "contact": _contacts._contact_label(it), "scope": _item_scope(it, sc)}
        if row["status"] != "open":
            try:
                ts = float(it.get("state_updated") or it.get("updated") or 0)
            except (TypeError, ValueError):
                ts = 0.0
            if ts:
                row["closed"], row["closed_words"] = ts, _hooks().rmod_when_words(dt.datetime.fromtimestamp(ts, _hooks().zone()))
            if m.get("outcome"):
                row["outcome"] = str(m["outcome"])
        out[g] = row
    return 200, "application/json", json.dumps({"items": out}, ensure_ascii=False)


_RECORDS_MAX = 300              # open-records: at most this many records in one answer
_RECORDS_BYTES = 4_000_000      # open-records and anchors-record: …and at most about this many bytes of JSON; past either, `truncated` is true and the rest is left out
_UNREADABLE = "cannot be read right now"


def _raw_record(p: Any) -> tuple[dict[str, Any] | None, str]:
    """An item file as the store holds it, parsed and nothing else done to it (no legacy read-through, nothing derived) → (record, ""), (None, "missing") when there is no such file,
    (None, "unreadable") when it is there and does not read or is no object."""
    try:
        with open(p, encoding="utf-8") as f:
            rec = json.load(f)
    except FileNotFoundError:
        return None, "missing"
    except (OSError, ValueError):
        return None, "unreadable"
    return (rec, "") if isinstance(rec, dict) else (None, "unreadable")


def _anchors_file() -> dict[str, Any] | None:
    """The anchors file parsed as it stands: {} when there is none, None when it is there and does not read or is no map (a caller answers 503 then, never a smaller answer)."""
    try:
        with open(_anc.FILE, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _row(gid: str, rec: dict[str, Any], anchors: dict[str, Any]) -> dict[str, Any]:
    """One item as the raw reads give it: `record` the file as it is; `anchors` the anchors that name this item (anchor_scope: from every project's page, each once, with `page` and `pages`; a project-wide
    anchor names no item), the one the model's own readers use."""
    meta = rec.get("metadata") if isinstance(rec.get("metadata"), dict) else {}
    scoped = [{k: v for k, v in a.items() if k != "scoped"} for a in _item_read._scoped_anchors(str(meta.get("project") or ""), gid, anchors)]
    return {"id": gid, "shown": _gh.shown(gid), "record": rec, "anchors": scoped}


def _client_item_record(key: str) -> tuple[int, str, str]:
    """`item-record?key=<item id>`: one item's stored record exactly as its file holds it (subject, status, metadata with its steps, phase, mover and wait fields), open or closed, nothing derived, with the anchors that
    name it. -> {id, shown, record, anchors}: `id` the store's id now (an old id of a migrated item is read through the alias map), `shown` how it is written for a person (board#N), `anchors` the
    entries of the anchors file scoped to the item (`[]` for none). 400 for a bad id, 404 for an id that names no item, 503 when the item's file or the anchors file is there and does not read."""
    k = str(key or "").strip()
    if not k or len(k) > 200 or any(c in k for c in "\r\n\t"):
        return 400, "text/plain", "key = an item id as shown: board#<n>, or <letter><n> for an older item"
    try:
        gid = _norm_id(k)
    except ToolError as e:
        return 400, "text/plain", str(e)
    rec, why = _raw_record(_path(gid))
    if why == "missing":
        return 404, "text/plain", f"no item {_gh.shown(gid)}"
    anchors = _anchors_file()
    if rec is None or anchors is None:
        return 503, "text/plain", f"the {'item' if rec is None else 'anchors'} file {_UNREADABLE}"
    return 200, "application/json", json.dumps(_row(gid, rec, anchors), ensure_ascii=False)


def _client_open_records(key: str) -> tuple[int, str, str]:
    """`open-records?key=<session>`: the stored records of the open items the session moves, takes after the answer or is named on in the needs of: the selection of `items?key=` (the view's `selected`), each as
    `item-record` gives it now (the file as it is, with its anchors), in one call. -> {session, total, truncated, unreadable, items: [{id, shown, record, anchors}]}; `total` is how many open items the session has
    (one that closed since the view was read is not counted), the answer holds at most `_RECORDS_MAX` of them and about `_RECORDS_BYTES` bytes, `truncated` is true when it left some out; `unreadable` lists the
    ids of items whose file stopped reading during this call (left out of `items`; a file corrupt before the call is skipped by the view and is in neither). A closed item is not listed. 503 when the anchors file does not read."""
    k = str(key or "").strip()
    if not k or len(k) > 200 or any(c in k for c in "\r\n\t"):
        return 400, "text/plain", "key = the asking session: its transcript uuid, cse_ id or pane name"
    anchors = _anchors_file()
    if anchors is None:
        return 503, "text/plain", f"the anchors file {_UNREADABLE}"
    sel = _items_view().selected(k)
    out: list[dict[str, Any]] = []
    bad: list[str] = []
    size, listed, gone = 0, 0, 0
    for gid, p, _it, _roles, _linked in sel:
        rec, why = _raw_record(p)
        if rec is None or rec.get("status") not in ("open", "on_hold"):         # on_hold: the retired status the reads still take for an open, held item
            if rec is None and why == "unreadable":
                bad.append(gid)
            else:
                gone += 1
            listed += 1
            continue
        row = _row(gid, rec, anchors)
        n = len(json.dumps(row, ensure_ascii=False))
        if len(out) >= _RECORDS_MAX or (out and size + n > _RECORDS_BYTES):
            break
        out.append(row); size += n; listed += 1
    return 200, "application/json", json.dumps({"session": k, "total": len(sel) - gone, "truncated": listed < len(sel), "unreadable": bad, "items": out}, ensure_ascii=False)


def _client_anchors_record() -> tuple[int, str, str]:
    """`anchors-record`: the anchors map as its store file holds it ({project key: [{url, items, added, by}]}), nothing derived. -> {anchors, truncated}: `anchors` is {} when the file is not there; past about `_RECORDS_BYTES`
    bytes the projects after that point are left out and `truncated` is true. 503 when the file is there and does not read."""
    data = _anchors_file()
    if data is None:
        return 503, "text/plain", f"the anchors file {_UNREADABLE}"
    out: dict[str, Any] = {}
    size, truncated = 0, False
    for page, entries in data.items():
        n = len(json.dumps(entries, ensure_ascii=False)) + len(str(page))
        if out and size + n > _RECORDS_BYTES:
            truncated = True
            break
        out[page] = entries; size += n
    return 200, "application/json", json.dumps({"anchors": out, "truncated": truncated}, ensure_ascii=False)
