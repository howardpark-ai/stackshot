"""shared.py: the helpers of the server that more than one area reads and that keep a little state of their own, which common.py (the pure pieces) has no place for: a session's name (`_session_label`
and the heartbeat index it falls back to), an item's page (`_item_url`, with the board's URL), what shows the owner's own words on an item (`_owner_words`, `_OWNER_QUOTED`), whether an item waits on his
decision (`_waits_decision`), the debounced publish (`_publish`, `_publish_now`, `_publish_if_idle`, with the timer and the lock they share), the roles and projects files the publish rebuilds, the registry
files of the store (`_registry`), and the drop of the board's kept home (`_board_home_drop`, with the cache's dict and its generation lock).

server.py is being split into one module per area (CONTRIBUTING.md, Layout). A module of an area cannot import server.py, and server.py runs as `__main__`, so what the areas share lives here, below
both, and server.py imports each name back: `server.<name>` stays the name its callers and the suites use. The exceptions are the two names a suite sets that code in this module reads. The timer
(`_PUB_TIMER`, which `_publish` rebinds) and the board's URL (`BOARD_URL`) are read and set on this module (`server._shared._PUB_TIMER`, `server._shared.BOARD_URL`), and the server's own reads go through
it, so a patch reaches every reader and no copy of either is left on `server`. A suite that stubs `_publish` on `server` (`server._publish = ...`) reaches every caller that stays in server.py; a
module that calls `_publish` itself (foryou_events.py) is stubbed on that module (`server._fyev._publish`), and `_publish_if_idle`, which is here, on this one."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import threading
import time
from typing import Any

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core import readonly as _ro
from stackshot.fleet import fleet as _fleet
from stackshot.fleet import liveness as _lv
from stackshot.fleet import renamed_agents as _renamed
from stackshot.fleet import sessions_registry as _sr
from stackshot.github import ghsync as _gh
from stackshot.model import said as _said
from stackshot.projects import projects as _prj
from stackshot.web import publish as _pub
from stackshot.web import store as _store
from stackshot.web.common import OWNER, _needs_of

# Read once, at import: [instance] board_url is among the settings config.RESTART_ONLY keeps for the run.
BOARD_URL = str(_cfg.get("instance", "board_url") or "")


def _item_url(gid: str) -> str:
    """An item's page: <board_url>/items/<gid>, an issue-numbered one's at /items/<n>, a temporary id's at
    /items/board-tmp-<machine>-<n> (ghsync.href_id)."""
    base = BOARD_URL.rstrip("/")
    return f"{base}/items/{_gh.href_id(gid)}" if base else ""


# A close with the owner's own words on the item was told to a
# front agent mover in one line, and no other close was; that close is a row on his For you list (foryou.py),
# and the same words make an item watched there (_foryou_watched). The front agent mover is told of any close by another
# session, his words or not, in its own marked line (_tell_owner_close), beside that row. His words are on it when (1) a `said` entry is (metadata.said: his sentences
# cut from his own message, checked against his transcript), or (2) the description or the close's reason quotes him: his name and a colon
# before an opening quote mark, or his name, a comma and a weekday. The second is the loosest and deliberately
# narrow. A board answer alone does not count: answering a decision picks an option, it does not ask to hear of the close.
_OWNER_QUOTED = re.compile(rf"\b{re.escape(OWNER)}\b[^:\n]{{0,40}}:\s*[\"\u201c]|\b{re.escape(OWNER)}, (?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b")


def _owner_words(item: dict[str, Any]) -> str:
    """What shows the owner's own words (the owner's) are on the item, in the order of how certain it is: "a said entry", "quoted in
    the text"; "" when none (see _OWNER_QUOTED). A board answer alone is not his words about the close: answering a decision is
    picking an option, not asking to hear of the close."""
    meta = item.get("metadata") or {}
    if any(e["quote"] and e["tag"] in _said.TAGS for e in _said.entries_of(meta)):     # unchecked counts on purpose: a quote attached with Acked-by is still his words on record
        return "a said entry"
    if item.get("status") == "completed" and str(meta.get("outcome_text") or "").strip():      # a close keeps the description (the item's background, which may quote him for any reason): what the close wrote is its outcome text and its reason
        text = f"{meta.get('outcome_text')}\n{meta.get('reason') or ''}"
    else:
        text = f"{item.get('description') or ''}\n{meta.get('reason') or ''}"
    if _OWNER_QUOTED.search(text):
        return "quoted in the text"
    return ""


def _waits_decision(meta: dict[str, Any]) -> bool:
    """Its needs hold decision: the item is in the owner's queue, never on hold (render.is_held
    reads the lane the same way, needs_kind "call")."""
    return any(x.lower() == "decision" for x in _needs_of(meta))


def _session_label(value: str) -> str:
    """The human name for a session reference: the name the fleet tool's registry gives the session now (a stored permanent id, an old transcript id or
    an old name all read as the name in use), else the heartbeat name, else the value itself."""
    v = str(value or "")
    n = _sr.display_name(v) if v else None
    if n:
        return n
    x = _sessions_index().get(v) or {}
    return str(x.get("name") or v)


class _Index(dict):
    """The heartbeat index (transcript UUID → row) that also answers for a permanent session id: a lookup (get, [], in) by an id the registry
    holds finds the row of that session's present transcript (the running one, else the latest seen), its name the registry's. Iteration
    (items, values, keys) is the heartbeat's own and lists each session once, by transcript."""
    def _via(self, k: Any) -> dict[str, Any] | None:
        if not isinstance(k, str) or not _sr.is_perm_id(k):
            return None
        best = None
        for t in _sr.transcripts(k):
            r = dict.get(self, t)
            if r is not None and (best is None or (_lv.running(r), str(r.get("seen", ""))) >= (_lv.running(best), str(best.get("seen", "")))):
                best = r
        if best is None:
            return None
        return {**best, "name": _sr.display_name(k) or best.get("name")}
    def __missing__(self, k: Any) -> dict[str, Any]:
        r = self._via(k)
        if r is None:
            raise KeyError(k)
        return r
    def get(self, k: Any, default: Any = None) -> Any:
        return dict.get(self, k) if dict.__contains__(self, k) else (self._via(k) or default)
    def __contains__(self, k: Any) -> bool:
        return dict.__contains__(self, k) or self._via(k) is not None


def _sessions_index() -> dict[str, dict[str, Any]]:
    """transcript UUID → {name, url, seen, machine} from every machine's live heartbeat (fleet.py; out of git). A permanent session
    id looks up the same way (see _Index)."""
    out = _Index()
    for L in _fleet.letters():
        for k, v in _fleet.read(L, "sessions").items():
            if isinstance(v, dict) and not dict.__contains__(out, k): out[k] = {"machine": L, **v}
    return out


_PUB_LOCK = threading.Lock()
_PUB_TIMER: threading.Timer | None = None


def _publish_debounce() -> float:
    return float(_cfg.get("publish", "debounce_seconds", default=5))


def _publish_every() -> float:
    return float(_cfg.get("publish", "every_minutes", default=10)) * 60   # default as in the example


def _publish_now(force_versions: bool = False, host: str = "") -> str:
    if _ro.is_read_only():                  # a standby copy renders in memory when asked (_ro_board), and publishes nothing
        return "(read-only standby: nothing published)"
    try:
        return _pub.publish(force_versions=force_versions, host=host)
    except Exception as e:  # never let a publish failure surface as a tool error
        return f"(publish failed: {e})"
    finally:
        _roles_sync_safe()                  # the publish rebuilt the registry; roles.json follows it


def _publish() -> None:
    """Debounced: a burst of writes in one turn publishes once, ~5 s after the first."""
    global _PUB_TIMER
    _board_home_drop()                         # the home is drawn per request: a write is on it at the next read, not at the publish
    if _ro.is_read_only():                  # no timer is started on a standby copy
        return
    with _PUB_LOCK:
        if _PUB_TIMER is not None and _PUB_TIMER.is_alive():
            return
        _PUB_TIMER = threading.Timer(_publish_debounce(), _publish_now)
        _PUB_TIMER.daemon = True
        _PUB_TIMER.start()


def _publish_if_idle() -> bool:
    """For the Runners panel (runners.ON_CHANGE): True when a publish was scheduled; False while the debounce timer's publish is still running (it stays alive through
    the whole _publish_now, git push included, and _publish returns silently then, so a request made in that time would be lost): the panel asks again a few seconds later."""
    if _ro.is_read_only():
        return True
    with _PUB_LOCK:
        if _PUB_TIMER is not None and _PUB_TIMER.is_alive():
            return False
    _publish()
    return True


# every session's role, as a file the server keeps (<state>/roles.json) and the client API serves (`roles`), so a box's
# hooks can tell a front agent without parsing the registry. Written at start, after each registry rebuild (publish, the
# create gate's rebuild) and from the runner's fleet pass (every 60 s), when the roles changed or the file is ROLES_EVERY old: a
# reader treats a file over an hour old as stale, so a live server keeps it fresh even when nothing changes.
ROLES = _cfg.state("roles.json")
ROLES_EVERY = 30 * 60
_ROLES_LOCK = threading.Lock()


def _roles_sync(now: float | None = None) -> bool:
    """Rewrite roles.json ({"generated": <UTC ISO Z>, "sessions": anchors.file_roles()}) atomically when the roles changed or
    the file is ROLES_EVERY old. file_roles is session_roles with the pane-named keeper of an active one-session project as
    "front"; the server's own gates keep session_roles. Each entry also says whether sala lists the name as a session (`"live"`, one
    `sala sessions --json` read per build: anchors.sala_live; the field is left out when sala cannot be read), and a change in who is listed rewrites the file. An empty registry (none yet, or unreadable) writes nothing: a stale file is the reader's cue,
    an empty one would say nobody is front. → True when written."""
    now = time.time() if now is None else now
    reg = _anc.registry()
    if not reg:
        return False
    rows = _anc.sala_rows()                                # sala is read once per build; `live` on every entry, or on none when sala cannot be read
    renames = _renamed.renames_of(rows)                    # old name → new name of the sessions sala renamed: an alias reads live, but names nobody
    try:
        _renamed.sweep(renames, reg, now)                  # a pending agent under an old name is no agent: dropped (the new name is registered) or renamed (it is not), before the roles read it
    except ValueError:                                     # a damaged id file: nothing is dropped, and the roles are built from the record as it stands
        pass
    except Exception as e:  # noqa: BLE001 — a record write that failed (a full disk, a lock file): the next tick sweeps again; the roles are rebuilt now all the same
        print(f"renamed agents: the sweep failed ({e!r}); roles.json is built from the record as it stands", file=sys.stderr, flush=True)
    live = None if rows is None else set().union(*_anc.sessions_of(rows))
    sessions = _anc.file_roles(reg, live, renames)
    ids = _anc.role_ids(sessions)          # step B: beside each name its permanent id where the registry resolves it (an extra top-level key; the keys of `sessions` stay names)
    with _ROLES_LOCK:
        try:
            old = json.loads(ROLES.read_text(encoding="utf-8"))
            age = now - dt.datetime.fromisoformat(str(old["generated"]).replace("Z", "+00:00")).timestamp()
        except Exception:
            old, age = {}, float("inf")
        if old.get("sessions") == sessions and (old.get("ids") or {}) == ids and 0 <= age < ROLES_EVERY:
            return False
        gen = dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ROLES.parent.mkdir(parents=True, exist_ok=True)
        tmp = ROLES.with_name(".roles.json.tmp")
        tmp.write_text(json.dumps({"generated": gen, "sessions": sessions, **({"ids": ids} if ids else {})}, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, ROLES)
    return True


def _roles_sync_safe(now: float | None = None) -> None:
    if _ro.is_read_only():                  # roles.json and projects.json are files the standby does not write
        return
    try:
        _roles_sync(now)
    except Exception as e:
        print(f"roles.json: {e}", file=sys.stderr, flush=True)
    _projects_sync_safe(now)                # phase A: projects.json beside it, on the same calls (start, publish, the create gate's rebuild, the 20-s pass)


# phase A: the project record's published file, <state>/projects.json ({schema, generated, projects: {<id>: {id, key, keeper,
# agents}}, by_key}), kept as roles.json is: rewritten when a record changed and at least every projects.EVERY (3 min) seconds, so a
# reader treats a file over 10 minutes old as stale. Ids are minted in <store>/project-record.json (projects.py), once and for good.
PROJECTS = _cfg.state("projects.json")


def _projects_sync(now: float | None = None, force: bool = False) -> bool:
    return _prj.sync(now=now, force=force, path=PROJECTS)


def _projects_sync_safe(now: float | None = None, force: bool = False) -> None:
    try:
        _projects_sync(now, force)
    except Exception as e:
        print(f"projects.json: {e}", file=sys.stderr, flush=True)


# A registry file of the store ([registries]), read by the project areas and the client API; `projects` has the project record's entries laid over the pages' lines.
def _registry(name: str) -> dict[str, Any]:
    r = _cfg.CFG["registries"][name]
    try:
        with open(_store.STORE / f"{name}.json", encoding="utf-8") as f:
            data = json.load(f)
        data = data[r["key"]] if r.get("key") else data
        return _prj.with_record(data) if name == "projects" else data      # the project record's entries first, the page lines for the rest
    except Exception:
        return {}


# The kept home of the board's root (its cache and its renders are server.py's): the dict, the lock that numbers its generations, and the drop a publish and a write from a page make.
_BOARD_HOME: dict[str, Any] = {"at": 0.0, "html": None, "gen": 0, "drawn": 0, "failed": 0.0}
_BOARD_GEN_LOCK = threading.Lock()
_BOARD_HOME_OTHER: dict[str, dict[str, Any]] = {}      # a language other than English: its own kept home, the same keys as _BOARD_HOME (the English draw is the one above)


def _board_home_slot(lang: str = "en") -> dict[str, Any]:
    """The kept home of `lang`: _BOARD_HOME for English, else the language's own (made on first use)."""
    if lang == "en":
        return _BOARD_HOME
    with _BOARD_GEN_LOCK:
        return _BOARD_HOME_OTHER.setdefault(lang, {"at": 0.0, "html": None, "gen": 0, "drawn": 0, "failed": 0.0})


def _board_home_drop() -> None:
    """The root home is drawn again on its next read (a write happened). A render that started before the drop is not kept. A recent failed draw still holds its back-off: a write
    does not make every request draw again."""
    with _BOARD_GEN_LOCK:
        for slot in (_BOARD_HOME, *_BOARD_HOME_OTHER.values()):
            slot["gen"] += 1
            slot["at"] = 0.0
