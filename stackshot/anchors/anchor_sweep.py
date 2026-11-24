"""anchor_sweep.py: anchors that clean up after themselves. Five rules end an anchor without anyone removing it; each is a small function of its own, and `sweep` applies them to the whole store.

  1. items   An item closes (completed, dropped, superseded): it no longer keeps an anchor alive. An anchor entry scoped to items, none of which is open any more, is removed, whatever its
             kind. A project-wide entry (no item scope) is never touched by this rule. An item whose file is gone counts as closed (stat says "not there": FileNotFoundError or NotADirectoryError, nothing else); one that cannot be read or looked at (a
             permission, an input error, a symlink loop) counts as unknown, and an unknown item keeps the entry: so does a store that holds no item at all, an item folder that is missing, and an id that may be
             an old alias while the alias map cannot be read. Each of those is a line on stderr.
  2. quiet   A GitHub issue or pull request that is merged or closed is removed from its page 14 days after its last activity: what the anchors reader saved as its `updated` time (a comment,
             a reopening, a label: anything that moves the issue's `updated_at`) or the time the entry was added (or added again: anchors.add renews it), whichever is later. A reopened one is no longer closed, so it stays.
  3. repo    A GitHub anchor on a repository that is archived, or on an issue or pull request GitHub no longer has (its read has answered "not found" for a day, while another anchor of the same
             repository was read fine, so a token that lost its access to a repository is not taken for a deleted issue), is removed, item-scoped entries too. Only what the reader saved says so:
             nothing is asked of GitHub here, and the reader must have looked at the anchor itself after it marked the repository or the issue.
  4. page    A page that is closed or archived (its status is one of [project_scopes] retired_statuses) takes its anchors with it.
  5. unreadable  An anchor the anchors service has not been able to read for [anchor_hub] unreadable_days days (7 when unset) is removed. The service starts that clock itself (`unreadable.at` in its status
             file, anchors/anchorhub/core.py) only after the anchor was refused on two reads at least five minutes apart, and clears it the moment the anchor reads again; its keeper was told when it started. Only what the
             status file says counts, and only while that file is young (15 minutes): a status that is old, missing or unreadable removes nothing. An entry younger than those days since it was added (or added again) stays, and so does one an open item waits on (the sparing below).
             It acts on an anchor of any kind the service reads, not on GitHub's alone.
             When at least 5 anchors are unreadable in one status read and they are more than half of all the anchors it reports on (a revoked or expired token does that), it removes nothing in that tick and says so once in the routing log.

Rules 2 and 3 read the anchors reader's saved position (its cursors file, key "github", with "github_repos" for what the reader learned of a repository), through `Reader`. They act only
while that file is young and the reader has looked at the anchor lately (a reader that is down knows nothing new), and they spare an anchor an open item waits on: its `wait_anchor`, an open anchor
line of a wait on a list, in any form of the same issue or pull request (`anchor_key`, the comparison of service/watching.anchor_key), and an anchor scoped to a parked open item. Where the position is missing or old they remove nothing. An item file that cannot be parsed may hold a wait nobody can read: the sweep then takes every anchor for in use, and rules 2, 3 and 5 remove nothing, until the file is readable.

Every removal is written to the routing log of the page that held the entry (a log-only line ruled `archived` by `stackshot (auto)`), and the line carries the call that puts the anchor back:
anchors(project=..., add=[...], items=[...]). A call too long for the log's 300 characters is kept whole in <paths.state>/anchor-removed.jsonl, which also holds every removal's line, and the log line says so.
Only the entries a rule ended are removed (an entry with the same url that no rule ended stays), under the anchors lock, from a store read again under it. `sweep(now)` is idempotent (a second run finds
nothing), is the one function every caller uses (the events below and the ten-minute tick), and takes `rules` to run only some of them, `items` to end only the entries scoped to those items, and `limit` to
remove at most so many entries in one call (the tick's `[anchor_hub] sweep_per_tick`: a large first removal is spread over ticks).

Called from: an item's close (`on_close`: rule 1, for the entries scoped to the item that closed, in the reply of the close), an item's reopening (`reopen_note`: the restore lines of what its close ended), a
project's archiving (project_verbs.archive: rule 4) and its reopening (`page_reopen_note`), and the minute runner's ten-minute set (`sweep_tick`: all five, at most `sweep_per_tick` entries).
Stdlib, anchors.py, anchor_scope.py, router/routing.py, github/ghsync.py and fleet/inbox.py (the reader's state folder) only; the waits of the open items are read through waits/wait_list.py and waits/waiting.py
at the first question."""
from __future__ import annotations

import errno
import json
import os
import re
import stat
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterable

from stackshot.anchors import anchor_scope as _ascope
from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.fleet import inbox as _inbox   # FLAGS: the folder the anchors reader keeps its saved state in
from stackshot.github import ghsync as _gh
from stackshot.router import routing as _routing

QUIET_DAYS = 14                      # a merged or closed GitHub anchor goes after this many days without activity
QUIET_S = QUIET_DAYS * 86400
GONE_S = 86400                       # a read of an issue that was found once must have answered "not found" this long before the entry goes
FRESH_S = 6 * 3600                   # the reader's saved position, and its last look at an anchor, must be this young for rules 2 and 3 to act
PER_TICK = 50                        # the most entries one tick of the ten-minute set removes ([anchor_hub] sweep_per_tick)
STATUS_FRESH_S = 900                 # the reader's status file must be this young for rule 5 to act (the reader writes it every minute)
MASS_MIN = 5                         # rule 5 holds back everything in a tick where at least this many anchors are unreadable...
MASS_SHARE = 0.5                     # ...and they are more than this share of all the anchors the reader reports on: a revoked or expired token (or a fault of the service) makes every GitHub anchor unreadable at once, and removing a whole list a week later for a fault that is not the anchors' would lose them all
unreadable_days = _anc.unreadable_days    # [anchor_hub] unreadable_days: 7 when the setting is absent, no whole number or below 1
LINE_MAX = 300                       # what the routing log keeps of a line's text (routing.record)
REMOVED = "anchor-removed.jsonl"     # in <paths.state>: one line per removed entry, whole
REOPEN_DAYS = 30                     # how far back a reopening looks for the lines of what its close ended
RULES = ("items", "quiet", "repo", "pages", "unreadable")
AUTO = _routing.AUTO_RULER


# ---------- what the reader knows ----------
@dataclass(frozen=True)
class Reading:
    """What the anchors reader keeps for one anchor. Every field is None (or empty) when the reader says nothing: a rule that needs a field acts only on one that is there.
    `status` is the anchor's own entry of the reader's status file (its status file, "anchors"), the one place its health is kept: a rule about unreadable anchors
    reads `status["unreadable"]` ({since, why, warned, next}) from here."""
    anchor: str
    known: bool = False                  # the reader holds a saved state for it
    finished: bool = False               # a GitHub issue or pull request that is closed or merged
    updated: float | None = None         # when it last changed on GitHub (its `updated_at`), as the reader last saw it
    looked: float | None = None          # when the reader last finished a look at it
    gone_since: float | None = None      # when its read first answered "not found", after it had been read once and another anchor of its repository was read fine
    archived_since: float | None = None  # when the reader first saw its repository archived
    status: dict[str, Any] = field(default_factory=dict)
    unreadable_since: float | None = None   # when the reader's two reads, minutes apart, both refused it (status["unreadable"]["at"]); None while it reads or the clock has not started
    unreadable_why: str = ""             # the one line it said why


def _epoch(v: Any) -> float | None:
    """A GitHub time (2026-10-28T01:00:00Z) or a number of seconds as seconds, None for anything else."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None
    try:
        return datetime.fromisoformat(str(v or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _repo_of(aid: str) -> str:
    """The lower-case owner/name of a github:<owner/repo>(#<n>|@releases|@notifications) anchor id, "" for any other."""
    if not aid.startswith("github:"):
        return ""
    rest = aid[7:]
    return rest[:min((j for j in (rest.find("#"), rest.find("@")) if j >= 0), default=len(rest))].lower()


class Reader:
    """A read-only view of what the anchors reader saved: its position file's "github" part (the state of each issue and pull request anchor, and when each was last looked at) and "github_repos"
    (the repositories it saw archived, the anchors it found gone), and its status file. Built from the files (`Reader.load`) or from dicts (a test's). Reads nothing from GitHub."""

    def __init__(self, cursors: Any = None, saved_at: float | None = None, status: Any = None, status_at: float | None = None):
        cur = cursors if isinstance(cursors, dict) else {}
        gh = cur.get("github") if isinstance(cur.get("github"), dict) else {}
        extra = cur.get("github_repos") if isinstance(cur.get("github_repos"), dict) else {}
        canon = lambda k: _anc.anchor_id(str(k)) or str(k)        # the saved keys are the reader's own spelling: a [github.moved] name is read as its current one
        self.saved_at = saved_at
        self.status_at = status_at
        self._state = {canon(k): v for k, v in (gh.get("state") or {}).items() if isinstance(v, dict)} if isinstance(gh.get("state"), dict) else {}
        self._looked = {canon(k): _epoch(v) for k, v in (gh.get("looked") or {}).items()} if isinstance(gh.get("looked"), dict) else {}
        self._gone = {canon(k): _epoch(v) for k, v in (extra.get("gone") or {}).items()} if isinstance(extra.get("gone"), dict) else {}
        self._archived = {str(k).lower(): _epoch(v) for k, v in (extra.get("archived") or {}).items()} if isinstance(extra.get("archived"), dict) else {}
        self._status = status.get("anchors") if isinstance(status, dict) and isinstance(status.get("anchors"), dict) else {}

    @classmethod
    def load(cls) -> "Reader":
        """The reader's files as they are now; a file that is missing or cannot be read is an empty record, and `saved_at` None (no rule trusts it)."""
        def read(name: str) -> tuple[Any, float | None]:
            p = _inbox.FLAGS / name
            try:
                with open(p, encoding="utf-8") as f:
                    return json.load(f), p.stat().st_mtime
            except (OSError, ValueError):
                return None, None
        cursors, at = read("cursors.json")
        status, sat = read("status.json")
        return cls(cursors, at, status, sat)

    def fresh(self, now: float) -> bool:
        """Is the saved position young enough to be believed?"""
        return self.saved_at is not None and 0 <= now - self.saved_at <= FRESH_S

    def status_fresh(self, now: float) -> bool:
        """Is the status file young enough to be believed (rule 5)? One that is missing, cannot be read or is older than STATUS_FRESH_S is not."""
        return self.status_at is not None and 0 <= now - self.status_at <= STATUS_FRESH_S

    def unreadable_counts(self) -> tuple[int, int]:
        """(anchors whose removal clock runs, all anchors the status file reports on), as that one status read says."""
        bad = 0
        for sx in self._status.values():
            ux = sx.get("unreadable") if isinstance(sx, dict) else None
            if isinstance(ux, dict) and _epoch(ux.get("at")) and " ".join(str(ux.get("why") or "").split()):
                bad += 1
        return bad, len(self._status)

    def reading(self, anchor: str) -> Reading:
        st = self._state.get(anchor)
        st = st if isinstance(st, dict) else {}
        done = st.get("state") == "closed" and "#" in anchor
        repo = _repo_of(anchor)
        sx = self._status.get(anchor)
        ux = sx.get("unreadable") if isinstance(sx, dict) else None
        return Reading(anchor=anchor, known=bool(st), finished=done, updated=_epoch(st.get("updated")),
                       looked=self._looked.get(anchor), gone_since=self._gone.get(anchor), archived_since=self._archived.get(repo) if repo else None,
                       status=dict(sx) if isinstance(sx, dict) else {},
                       unreadable_since=_epoch(ux.get("at")) if isinstance(ux, dict) else None, unreadable_why=" ".join(str(ux.get("why") or "").split())[:200] if isinstance(ux, dict) else "")


def _looked_after(r: Reading, mark: float, now: float) -> bool:
    """Did the reader finish a look at this anchor after `mark` (when it marked the repository or the issue) and lately? A mark the reader has not looked at the anchor since is not about this anchor yet."""
    return bool(r.looked) and r.looked >= mark and 0 <= now - r.looked <= FRESH_S


# ---------- the items an entry names ----------
def _alias_map() -> tuple[dict[str, Any] | None, str]:
    """(the store's alias map {old id: id now}, "") · ({}, "") when there is no map (nothing was ever re-keyed) · (None, why) when the map is there and cannot be read: an id missing from the store may then be an old one."""
    p = _anc.STORE / _gh.MAP_NAME
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, ""
    except OSError as e:
        return None, f"{_gh.MAP_NAME} cannot be read ({e.__class__.__name__})"
    try:
        m = json.loads(text)
    except ValueError:
        return None, f"{_gh.MAP_NAME} cannot be parsed"
    al = m.get("aliases") if isinstance(m, dict) else None
    if not isinstance(m, dict) or (al is not None and not isinstance(al, dict)):
        return None, f"{_gh.MAP_NAME} is not a map"
    return al or {}, ""


def _stat(p: Any) -> "os.stat_result | None":
    """stat(p), or None when it is not there (FileNotFoundError, NotADirectoryError: nothing is at that path). Any other error (a permission, an input error, a symlink loop, a stale handle) is raised: Path.exists
    and Path.is_dir answer False to every one of those, which reads an item that could not be looked at as an item that is gone."""
    try:
        return os.stat(p)
    except (FileNotFoundError, NotADirectoryError):
        return None


def _store_has_items() -> bool:
    """Does any letter folder of the store hold an item file? A store folder or letter folder that is not there holds none; an error that is not "not there" is raised (the caller reads it as unknown)."""
    try:
        letters = sorted(os.listdir(_anc.STORE))
    except (FileNotFoundError, NotADirectoryError):
        return False
    for n in letters:
        if len(n) != 1 or not n.isalpha():
            continue
        try:
            names = os.listdir(_anc.STORE / n)
        except (FileNotFoundError, NotADirectoryError):
            continue
        if any(x.endswith(".json") and not x.startswith(".") and x not in ("machine.json", "sessions.json") for x in names):
            return True
    return False


def item_state(gid: str) -> tuple[str, str]:
    """("open" | "closed" | "unknown", why) · "closed": the item completed, or it has no file in a store that holds items and whose alias map is readable · "unknown": the file cannot be read, the item's folder is missing,
    the folder or the file cannot be looked at (a permission, an input error, a symlink loop: only "not there" says an item is gone), the store holds no item at all (which says nothing of this one), or the id is
    not in the store and the alias map that could say it was re-keyed cannot be read. A rule never ends an entry on "unknown"."""
    g = str(gid or "").strip()
    if len(g) < 2:
        return "unknown", f"{g!r} is no item id"
    aliases, why = _alias_map()
    if aliases is None:
        if (_anc.STORE / g[:1] / f"{g[1:]}.json").is_file():
            aliases = {}                  # the file is there under this very id: no alias can change what it says
        else:
            return "unknown", f"{g} is not in the store and {why}, so it may be an old id"
    g = str(aliases.get(g) or g)
    d = _anc.STORE / g[:1]
    f = d / f"{g[1:]}.json"
    try:
        sd = _stat(d)
        if sd is None or not stat.S_ISDIR(sd.st_mode):
            return "unknown", f"the store has no folder {g[:1]}/ for {g}"
        if _stat(f) is None:
            return ("closed", "") if _store_has_items() else ("unknown", f"the store holds no item at all, so {g} having no file says nothing")
    except OSError as e:
        return "unknown", f"{g}'s file or folder cannot be looked at ({e.__class__.__name__}, {errno.errorcode.get(e.errno or 0, e.errno)})"
    try:
        with open(f, encoding="utf-8") as fh:
            t = json.load(fh)
    except (OSError, ValueError) as e:
        return "unknown", f"{g}'s file cannot be read ({e.__class__.__name__})"
    if not isinstance(t, dict):
        return "unknown", f"{g}'s file is not an item"
    return ("closed", "") if t.get("status") == "completed" else ("open", "")


def item_status(gid: str) -> str:
    """"open" · "closed" · "unknown": item_state without its reason."""
    return item_state(gid)[0]


_SAID: set[str] = set()


def _status_fn(say: bool = True) -> Callable[[str], str]:
    """item_status with one answer per id for the sweep that asks, and (with `say`) one stderr line the first time this process finds an item unknown (the entries scoped to it are kept)."""
    cache: dict[str, str] = {}

    def status(g: str) -> str:
        if g not in cache:
            st, why = item_state(g)
            cache[g] = st
            if say and st == "unknown" and g not in _SAID:
                _SAID.add(g)
                print(f"anchor sweep: item {g} read as unknown, so the anchors scoped to it are kept: {why}", file=sys.stderr, flush=True)
        return cache[g]
    return status


def _shown(gids: Iterable[str]) -> list[str]:
    return [_gh.shown(g) for g in gids]


def _open_ids(entry: dict[str, Any], status: Callable[[str], str]) -> list[str]:
    return [g for g in entry.get("items") or [] if status(g) == "open"]


def restore_call(page: str, entry: dict[str, Any], status: Callable[[str], str] = item_status) -> str:
    """The anchors call that puts a removed entry back: its url, scoped to those of its items that are open (a completed item cannot be named: such an entry comes back project-wide; an item that is not open for any other reason, an unreadable one included, is left out of
    the call too, and the entry's scope is then narrower than it was: the call is a restore of the anchor, and the log line names the items it was scoped to)."""
    items = _shown(_open_ids(entry, status))
    return f"anchors(project={json.dumps(page)}, add={json.dumps([entry['url']])}" + (f", items={json.dumps(items)}" if items else "") + ")"


# ---------- the four rules: each answers which entries of the store it ends, with the reason ----------
@dataclass(frozen=True)
class Hit:
    page: str
    entry: dict[str, Any]
    rule: str
    why: str
    idx: int = -1                        # the entry's place among the page's clean entries: two entries with one url are two hits, never one


def _entries(store: Any) -> Iterable[tuple[str, int, dict[str, Any]]]:
    for page in (sorted(str(k) for k in store) if isinstance(store, dict) else []):
        for i, e in enumerate(_ascope.clean_entries(store.get(page))):
            yield page, i, e


def rule_items(store: Any, status: Callable[[str], str] = item_status, only: Iterable[str] | None = None) -> list[Hit]:
    """Rule 1: an entry scoped to items, every one of them closed. `status(gid)` → open | closed | unknown; one item that is unknown, or open, keeps the entry. With `only`, just the entries whose scope
    names one of those items (the ones the close of that item ended): an entry of long-closed items that nothing touched stays for the tick."""
    want = {_gh.resolve(str(g)) for g in only} if only is not None else None
    hits = []
    for page, i, e in _entries(store):
        scope = e["items"] or []
        if want is not None and not any(_gh.resolve(g) in want for g in scope):
            continue
        if scope and all(status(g) == "closed" for g in scope):
            hits.append(Hit(page, e, "items", f"every item it was scoped to is closed ({', '.join(_shown(scope))})", i))
    return hits


def rule_quiet(store: Any, reader: Reader, now: float, spared: Callable[[str, dict[str, Any]], bool] = lambda p, e: False) -> list[Hit]:
    """Rule 2: a GitHub issue or pull request entry whose issue the reader saved as closed (merged or not), 14 days after the later of its last activity and the entry's own `added`. Acts only on a young
    position that the reader looked at this anchor in lately."""
    hits = []
    if not reader.fresh(now):
        return hits
    for page, i, e in _entries(store):
        aid = _anc.anchor_id(_anc.split_fragment(e["url"])[0]) or ""
        if not aid.startswith("github:") or "#" not in aid:
            continue
        r = reader.reading(aid)
        if not (r.finished and r.updated and r.looked and 0 <= now - r.looked <= FRESH_S):
            continue
        since = max(r.updated, e["added"] or 0.0)
        if now - since >= QUIET_S and not spared(page, e):
            hits.append(Hit(page, e, "quiet", f"merged or closed with no activity for {int((now - since) // 86400)} days (the rule is {QUIET_DAYS})", i))
    return hits


def rule_repo(store: Any, reader: Reader, now: float, spared: Callable[[str, dict[str, Any]], bool] = lambda p, e: False) -> list[Hit]:
    """Rule 3: a GitHub entry (an issue or pull request, a releases feed, a notifications feed) on a repository the reader saw archived, or an issue or pull request entry whose read has answered
    "not found" for GONE_S after the reader had read it once. Acts only on a young position, and only on an anchor the reader finished a look at after the mark it acts on."""
    hits = []
    if not reader.fresh(now):
        return hits
    for page, i, e in _entries(store):
        aid = _anc.anchor_id(_anc.split_fragment(e["url"])[0]) or ""
        if not aid.startswith("github:"):
            continue
        r = reader.reading(aid)
        if r.archived_since and _looked_after(r, r.archived_since, now):
            if not spared(page, e):
                hits.append(Hit(page, e, "repo", f"its repository {_repo_of(aid)} is archived (seen by the anchors reader {_ago(now - r.archived_since)} ago)", i))
        elif "#" in aid and r.known and r.gone_since and now - r.gone_since >= GONE_S and _looked_after(r, r.gone_since, now):
            if not spared(page, e):
                hits.append(Hit(page, e, "repo", f"GitHub has answered \"not found\" for it for {_ago(now - r.gone_since)} (a deleted issue or pull request)", i))
    return hits


def rule_unreadable(store: Any, reader: Reader, now: float, spared: Callable[[str, dict[str, Any]], bool] = lambda p, e: False, days: int | None = None,
                    held: list[Hit] | None = None) -> list[Hit]:
    """Rule 5: an entry the reader has not been able to read for `days` days ([anchor_hub] unreadable_days), counted from `unreadable.at` in the reader's status, which the reader sets only after two refused reads minutes
    apart and takes away when the anchor reads. Acts only on a young status file; an entry added (or added again) less than `days` days ago stays, and so does one an open item waits on.
    When the unreadable anchors of that one status read are MASS_MIN or more and more than MASS_SHARE of all it reports on, nothing is removed: the hits are put in `held` (when given) for the caller to say so."""
    hits = []
    if not reader.status_fresh(now):
        return hits
    span = (unreadable_days() if days is None else int(days)) * 86400
    for page, i, e in _entries(store):
        aid = _anc.anchor_id(_anc.split_fragment(e["url"])[0]) or ""
        r = reader.reading(aid) if aid else None
        if r is None or not r.unreadable_since or not r.unreadable_why or now - r.unreadable_since < span:
            continue
        if e["added"] and now - e["added"] < span:
            continue
        if not spared(page, e):
            hits.append(Hit(page, e, "unreadable", f"unreadable for {int((now - r.unreadable_since) // 86400)} days: {r.unreadable_why}", i))
    bad, total = reader.unreadable_counts()
    if hits and bad >= MASS_MIN and bad > total * MASS_SHARE:
        if held is not None:
            held.extend(hits)
        return []
    return hits


def rule_pages(store: Any, reg: dict[str, Any]) -> list[Hit]:
    """Rule 4: every entry of a page whose status is a retired one. A page the registry does not list is left alone (a registry that could not be read lists nothing)."""
    from stackshot.projects import projects as _prj
    retired = _prj.retired_statuses()
    hits = []
    for page, i, e in _entries(store):
        row = reg.get(page) if isinstance(reg, dict) else None
        if isinstance(row, dict) and _prj.page_status(row) in retired:
            hits.append(Hit(page, e, "pages", f"its page {page} is {_prj.page_status(row)}", i))
    return hits


def _ago(s: float) -> str:
    d = int(s // 86400)
    return f"{d} days" if d >= 1 else f"{int(s // 3600)} hours"


# ---------- the sweep ----------
def anchor_key(url: str) -> str:
    """An anchor's URL or id → the id the anchors reader keys it by, a #mention fragment left out; a shape it does not know stays as given. The same function as service/watching.anchor_key, which the waits compare
    anchors with (this package sits below the service layer and does not import it; tests/anchor_sweep_scenario.py checks that the two agree)."""
    u = str(url or "").strip()
    try:
        return _anc.anchor_id(_anc.split_fragment(u)[0]) or u
    except Exception:  # noqa: BLE001
        return u


def _waiters() -> Callable[[str, dict[str, Any]], bool]:
    """A test `(page, entry) -> bool`: is the anchor in use by an open item (of any project)? Three things are: its `wait_anchor`, an open anchor line of a wait on a list (both compared as the waits compare an
    anchor, `anchor_key`: the issue and the pull request of one number, /files, a #mention fragment and the github:owner/repo#n form are one anchor), and an entry scoped to a parked open item (one with
    `hold`). The items are read once, at the first question; an item that cannot be read as a wait spares everything (an anchor is kept when it is not known to be unused)."""
    state: dict[str, Any] = {}

    def read() -> None:
        from stackshot.waits import wait_list as _wl
        from stackshot.waits import waiting as _wt
        keys: set[str] = set()
        held: set[str] = set()
        unsure = False
        try:
            found, failed = _anc.items_read()
        except Exception as e:  # noqa: BLE001
            found, failed, unsure = [], [], True
            print(f"anchor sweep: the items were not read, every anchor is spared this time: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        if failed:                     # an item file that cannot be parsed may hold a wait: its anchor is not known to be unused
            unsure = True
            key = "unparsed:" + ",".join(failed)
            if key not in _SAID:       # one line the first time this process meets this set of files, as the unknown items are told
                _SAID.add(key)
                print(f"anchor sweep: {len(failed)} item file(s) could not be read ({', '.join(failed[:5])}{', ...' if len(failed) > 5 else ''}), so rules 2, 3 and 5 remove nothing while that holds", file=sys.stderr, flush=True)
        for t in found:
            if t.get("status") == "completed":
                continue
            try:
                m = t.get("metadata") if isinstance(t.get("metadata"), dict) else {}
                if m.get("wait_anchor"):
                    keys.add(anchor_key(str(m["wait_anchor"])))
                ls = _wl.lines(m)
                keys.update(anchor_key(str(ls[i]["anchor"])) for i in _wl.lines_by_kind(m, "anchor"))
                if _wt.is_held(t):
                    held.add(_gh.resolve(str(t["gid"])))
            except Exception as e:  # noqa: BLE001
                unsure = True
                print(f"anchor sweep: wait of {t.get('gid')} not read, every anchor is spared this time: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        state.update(keys=keys, held=held, unsure=unsure)

    def waiting(page: str, e: dict[str, Any]) -> bool:
        if not state:
            read()
        if state["unsure"]:
            return True
        return anchor_key(e["url"]) in state["keys"] or any(_gh.resolve(g) in state["held"] for g in e["items"] or [])
    return waiting


def per_tick() -> int:
    """[anchor_hub] sweep_per_tick: the most entries one tick of the ten-minute set removes; 50 when the setting is absent, no whole number or below 1."""
    v = _cfg.get("anchor_hub", "sweep_per_tick", default=PER_TICK)
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 1 else PER_TICK


def sweep(now: float | None = None, *, rules: Iterable[str] = RULES, reader: Reader | None = None, reg: dict[str, Any] | None = None, items: Iterable[str] | None = None,
          limit: int | None = None) -> list[dict[str, Any]]:
    """Apply the rules to every anchor entry, remove what they end and log each removal → one dict per removed entry ({page, url, items, rule, why, restore}). Idempotent: what a sweep removed is
    gone from the next one's store. Nothing is removed from a store that cannot be read as a whole. The hits are found on a read of the store; the removal reads it again under the anchors lock
    (anchors.LOCK, across processes) and removes an entry only if it is still the one that was judged, so an anchor added, changed or removed by another writer meanwhile is never lost or brought back.
    `reader` and `reg` (the page registry) are read from their files when not given; a rule whose facts are missing removes nothing. `items`: rule 1 ends only entries scoped to one of those items.
    `limit`: at most that many entries are removed (the first in the order of the rules and the pages); the rest are judged again by the next call."""
    now = time.time() if now is None else float(now)
    rules = tuple(rules)
    status = _status_fn()
    rd = (reader or Reader.load()) if ("quiet" in rules or "repo" in rules or "unreadable" in rules) else None
    rg = (_anc.registry() if reg is None else reg) if "pages" in rules else None
    store = _anc.load()
    if not store:
        return []
    hits: list[Hit] = []
    waiting = _waiters()
    if "items" in rules:
        hits += rule_items(store, status, items)
    if rd is not None and "quiet" in rules:
        hits += rule_quiet(store, rd, now, waiting)
    if rd is not None and "repo" in rules:
        hits += rule_repo(store, rd, now, waiting)
    if rg and "pages" in rules:
        hits += rule_pages(store, rg)
    if rd is not None and "unreadable" in rules:
        held: list[Hit] = []
        hits += rule_unreadable(store, rd, now, waiting, held=held)
        if held:
            _say_held(held, rd.unreadable_counts())
    mine, seen = [], set()
    for h in hits:
        if (h.page, h.idx) in seen:
            continue
        seen.add((h.page, h.idx))
        mine.append(h)
    if limit is not None:
        mine = mine[:max(0, int(limit))]
    if not mine:
        return []
    out = _remove(mine, _status_fn(say=False))      # the restore calls only name the items still open: an item read as unknown there is no news (the rule that judged the entry said it)
    for o in out:
        _log(o)
    return out


def _remove(hits: list[Hit], status: Callable[[str], str]) -> list[dict[str, Any]]:
    """Remove the hits' entries from the store as it is now, under the anchors lock, and save once. An entry that is no longer at its place or no longer what was judged is left (the next sweep judges it again)."""
    calls = {(h.page, h.idx): restore_call(h.page, h.entry, status) for h in hits}      # reads item files: before the lock is taken
    out: list[dict[str, Any]] = []
    with _anc.LOCK:
        store = _anc.load()
        if not store:
            return []
        for page in sorted({h.page for h in hits}):
            raw = store.get(page)
            if not isinstance(raw, list):
                continue
            want = {h.idx: h for h in hits if h.page == page}
            keep, k = [], -1
            for r in raw:
                c = _ascope.clean_entries([r])
                if c:
                    k += 1
                    h = want.get(k)
                    if h is not None and c[0] == h.entry:
                        out.append({"page": page, "url": h.entry["url"], "items": list(h.entry["items"] or []), "rule": h.rule, "why": h.why, "restore": calls[(page, k)]})
                        continue
                keep.append(r)
            if len(keep) != len(raw):
                store[page] = keep
        if not out:
            return []
        _anc.save(store)
    return out


def _record(o: dict[str, Any]) -> str:
    """The removal as one whole line of <paths.state>/anchor-removed.jsonl → the file's path, "" when it could not be written (a stderr line says so)."""
    try:
        p = _cfg.state(REMOVED)
        os.makedirs(p.parent, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": time.time(), **o}, ensure_ascii=False) + "\n")
        return str(p)
    except Exception as e:  # noqa: BLE001
        print(f"anchor sweep: record of {o['url']} not written: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return ""


def _say_held(held: list[Hit], counts: tuple[int, int]) -> None:
    """One line, once for the run, on the routing log of the page of the first entry rule 5 held back: why nothing was removed. Never raises."""
    try:
        bad, total = counts
        why = f"anchor removal held back: {bad} of {total} anchors cannot be read at once (a revoked or expired token looks like this), so rule 5 removed nothing; {len(held)} entries were due"
        _routing.record_auto(held[0].page, "archived", why, kind="anchor", label="anchor removal held back", who=AUTO, text=why)
    except Exception as e:  # noqa: BLE001
        print(f"anchor sweep: log line for the held-back removals not written: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


def _log(o: dict[str, Any]) -> None:
    """One log-only line on the routing log of the page that held the entry: what went, why, and the call that puts it back, whole, or where the whole call is when it does not fit in the log's 300
    characters. Never raises: the removal is saved, a line that could not be written is a stderr line."""
    try:
        where = _record(o)
        text = f"restore: {o['restore']}"
        if len(" ".join(text.split())) > LINE_MAX:
            text = f"restore: the call is too long for this line, it is whole in {where}" if where else text
        scope = (" · scoped to " + ", ".join(_shown(o["items"]))) if o["items"] else ""
        _routing.record_auto(o["page"], "archived", f"anchor removed ({o['rule']}){scope}: {o['why']}", kind="anchor", label=f"anchor removed ({o['rule']})", who=AUTO,
                             text=text, url=o["url"] if o["url"].startswith("http") else "", anchor=_anc.anchor_id(_anc.split_fragment(o["url"])[0]) or "")
    except Exception as e:  # noqa: BLE001
        print(f"anchor sweep: log line for {o['url']} not written: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


# ---------- the callers ----------
def close_note(removed: list[dict[str, Any]]) -> str:
    """The lines a close's reply ends with when the close ended anchors: each removed url, its page and the call that puts it back."""
    if not removed:
        return ""
    return ("\nanchors ended with this close (no open item left in their scope), each logged on its project's routing log:\n"
            + "\n".join(f"- {o['url']} ({o['page']}); restore: {o['restore']}" for o in removed))


def on_close(gid: str, publish: Callable[[], Any] | None = None) -> str:
    """After item `gid` closed: rule 1 for the entries scoped to it, the removed anchors told as the lines of the close's reply. Never raises: a close is not failed by its anchors."""
    try:
        removed = sweep(rules=("items",), items=[gid])
        if removed and publish:
            publish()
        return close_note(removed)
    except Exception as e:  # noqa: BLE001
        print(f"anchor sweep: after a close: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return ""


def on_page_change() -> list[dict[str, Any]]:
    """After a project was archived: rule 4 over the store. Never raises."""
    try:
        return sweep(rules=("pages",))
    except Exception as e:  # noqa: BLE001
        print(f"anchor sweep: after a page change: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return []


def sweep_tick() -> list[dict[str, Any]]:
    """The ten-minute set's step: every rule over the store, at most [anchor_hub] sweep_per_tick entries (the rest next tick)."""
    return sweep(limit=per_tick())


def _removed_lines(page: str, label: str, since: float) -> list[dict[str, Any]]:
    try:
        return [n for n in _routing.read(page, since=since) if n.get("kind") == "anchor" and str(n.get("label") or "") == label]
    except Exception as e:  # noqa: BLE001
        print(f"anchor sweep: routing log of {page} not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return []


def _url_of(n: dict[str, Any]) -> str:
    """The url of a removal line: its own field, else the first url of the restore call in its text."""
    if n.get("url"):
        return str(n["url"])
    t = str(n.get("text") or "")
    i = t.find("add=")
    try:
        v, _ = json.JSONDecoder().raw_decode(t[i + 4:]) if i >= 0 else ([], 0)
    except ValueError:
        return ""
    return str(v[0]) if isinstance(v, list) and v and isinstance(v[0], str) else ""


def reopen_note(gid: str, project: str) -> str:
    """The line a reopening's reply ends with when the close that ended this item's anchors left restore lines on its project's routing log (the last REOPEN_DAYS days): the item's anchors do not come back by
    themselves, and each line has the call that puts one back, scoped to the item again. "" when there is none. Never raises."""
    try:
        shown = _gh.shown(gid)
        mine = re.compile(r"(?<![\w#-])" + re.escape(shown) + r"(?!\d)")
        urls = [u for n in _removed_lines(project, "anchor removed (items)", time.time() - REOPEN_DAYS * 86400) if mine.search(str(n.get("reason") or "")) and (u := _url_of(n))]
        urls = list(dict.fromkeys(urls))
        if not urls:
            return ""
        calls = [f"anchors(project={json.dumps(project)}, add={json.dumps([u])}, items={json.dumps([shown])})" for u in urls[:5]]
        return (f"\nanchors that ended when {shown} closed are not back on {project} (each is an 'anchor removed' line on its routing log, with its restore call); put one back scoped to {shown} again with: "
                + "; ".join(calls) + (f"; {len(urls) - 5} more on the log" if len(urls) > 5 else ""))
    except Exception as e:  # noqa: BLE001
        print(f"anchor sweep: after a reopening: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return ""


def page_reopen_note(page: str) -> str:
    """The line a project's reopening carries when its archiving ended anchors that are still on its routing log (the last REOPEN_DAYS days): how many, and where their restore calls are. "" when none. Never raises."""
    try:
        urls = list(dict.fromkeys(u for n in _removed_lines(page, "anchor removed (pages)", time.time() - REOPEN_DAYS * 86400) if (u := _url_of(n))))
        if not urls:
            return ""
        return (f"{len(urls)} anchor{'s' if len(urls) != 1 else ''} ended when {page} was archived and are not back; each is an 'anchor removed' line on its routing log with the call that puts it back, "
                f"anchors(project={json.dumps(page)}, add=[<url>]), e.g. {json.dumps(urls[0])}")
    except Exception as e:  # noqa: BLE001
        print(f"anchor sweep: after a page reopening: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return ""
