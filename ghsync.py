"""ghsync.py — the board's GitHub mirror, slimmed by an earlier change.

The local store stays the working copy the board renders from and the queue reads; GitHub Issues in [github] issues_repo is the
mirror and gives the items their numbers. Every item write goes through the server, which calls on_change() after the file is saved;
nothing here is on the write path. The hook puts one job in a queue on disk (<state>/github/queue/) when something the issue carries
changed, and a worker drains it in order, paced well under GitHub's limits (one write every [github] min_interval_seconds, at most
hourly_budget an hour). A GitHub outage leaves the jobs where they are and the worker tries again later; a refusal moves the job to
failed/ with the reason.

What an issue carries (the store's files are pushed to a repository
by publish.py and are the backup, and the mirror is write-mostly): the item's subject (the title), open or closed
(with the close reason), and its description (the body: the marker below, the description, for a closed item with an outcome text an "## Outcome" section holding it, one footer line linking the item's page).
Nothing else is on GitHub any more: no history comments, no labels (`on hold` included), no typed issue fields (owner, needs, project,
priority, due, wake), no blocked-by links, and no Next, Ask, Options, Draft or property line in the body. The History on the item
page is the store's git (render.Board.item_log), never the issue. A change to a field the issue does not carry makes no job and so no call
(mirrored(), on_change). What older versions wrote stays on GitHub as it is: nothing is deleted or cleaned up.

Nothing is sent unless [github] sync = true (the default is false: a deploy of this module changes nothing live). The
id switch, [github] issue_ids, is a second switch: with it on a new item's id is its issue number, kept as <letter><n> in
the store (`g7` under g/7.json) and shown as (shown()); norm() reads board#N, #7 and g7 as that id. The
map (<store>/github.json) holds each item's issue number and each migrated item's old id as an alias (resolve()).

migrate() is the move itself (a one-time migration; ghmigrate.py is its CLI): the open items, in id order, become
issues #1 onward, the files move to the issue letter, and the old ids stay as aliases. A second run creates nothing: the map, and the
marker each issue body carries (marker()), say what exists. It posts no history comment any more.

Phase 2 prep: with issue_ids on, a create during a GitHub outage is
not refused: the item takes a local id under [github] local_letter (l1, l2, …; the counter `local_last` lives in the map and
no number is reused), its create job waits in the queue, and when GitHub answers the worker creates the issue and re-keys the
item to its number (rekey(): the same move as the migration, the old id kept as an alias, the `after` lists that named it
rewritten) and tells the server through on_rekey, which tells the item's mover.

A temporary id is written for a person as board-tmp-<machine>#<n> (the preface is the machine name instead of "board"; <machine> is [instance] machine, default
"local"), so that it is never taken for an issue number; its page is /items/board-tmp-<machine>-<n>
(href_id()). The store keeps l<n>; norm() reads both written forms as that id, and l<n> itself is always accepted.

Phase 3, the inbound half: the owner's own comments on an issue reach the item and its sessions, kept
for an emergency. The reader (comments_loop(), a thread beside the worker's) polls the repo's comments every [github] poll_seconds
(default 60: one GET an hour per minute, far under GitHub's 5,000; a webhook would need a public path through the access proxy and a
secret) with `since` at its cursor. A comment is the owner's when its user is [github] owner_login (default: the login the
mirror's token belongs to, GET /user; the server writes with the owner's own account) and its body carries no `[author: …]`
header (is_owner_comment()): the header is what told the mirror's old comments from his. The issue number maps to the item
through the map (item_of_issue()), and the server's hook (on_comment) records the comment on the item (metadata.answers, via github)
and tells its mover and the sessions in its needs. The cursor and the ids delivered live in <state>/github/comments.json
(comments_state()): a restart delivers nothing twice, an edit of a delivered comment is not a new one, and the first run starts at
"now", so the history before the deploy is never delivered. Reading only: a comment clears no needs, changes no status and owes no
page. The reader keeps no copy of the comments (it did until an earlier change, for a History drawn from the issue).

One capped queue: the host has one GitHub token and 5,000 REST calls an hour on it, so
(1) the updates of an issue that already exists wait [github] merge_seconds (300) in the queue, counted from the oldest, and go out together
as one PATCH of the issue (the fingerprint skip already made it one); a create and a close or reopening go at once, taking whatever waits
for the same issue with them (drain, _merge_group, _merge_due); the window is read off the jobs' own timestamps, which live on disk, so a restart
loses none; (2) every call of the server's clients is in the host's one hourly ledger (ghbudget.py, a locked file under <state>/github that
anchor-hub shares for its `gh api` reads): writes under [github] hourly_budget (250), counted reads under read_budget (1500), a 304 never.

The body form (BODY_FORM, 3 since an earlier change) says which body an issue was last written with; resync_bodies() can bring every stale issue up once on the
background lane, but runs by itself only with [github] backfill_bodies on (default off): an issue takes the slim body the next time it changes.
"""
from __future__ import annotations

import calendar
import collections
import contextlib
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as _cfg  # noqa: E402
import option_labels as _ol  # noqa: E402  — the letter an option's label repeats from its badge, dropped on read
import readonly as _ro  # noqa: E402  — a warm standby copy makes no GitHub write
import ghbudget as _gb   # noqa: E402  — the hourly ledger of GitHub calls shared with the other readers of the host's token

API_DEFAULT = "https://api.github.com"
MAP_NAME = "github.json"            # in the store, committed with it by the publisher
DEFAULT_LETTER = "g"
DEFAULT_LOCAL_LETTER = "l"          # the store letter of an item created while GitHub was down (phase 2 prep): temporary, re-keyed on recovery
DEFAULT_MACHINE = "local"           # [instance] machine unset: a temporary id reads board-tmp-local#<n>
DEFAULT_PACE = 1.5                  # s between two writes: well under GitHub's secondary limit of about 80 content writes a minute
DEFAULT_BUDGET = _gb.DEFAULT_WRITES  # writes an hour: 250 (was 400)
DEFAULT_READ_BUDGET = _gb.DEFAULT_READS   # counted reads an hour, all readers of the token together (ghbudget.py); a 304 is not counted
DEFAULT_MERGE = 300.0               # s: the updates of one existing issue are held this long and go out as one PATCH
DEFAULT_POLL = 60.0                 # s between two reads of the repo's comments (phase 3): 60 GETs an hour, far under GitHub's 5,000
MIN_POLL = 15.0                     # the floor of [github] poll_seconds: a tighter loop would read 240 an hour for nothing
COMMENTS_NAME = "comments.json"     # <state>/github/comments.json: the reader's cursor and the ids it has delivered (phase 3)
SEEN_MAX = 5000                     # the delivered ids kept (the newest): an edit of one older than that would read as new
RATE_NAME = "ratelimit.json"        # <state>/github/ratelimit.json: the newest X-RateLimit headers any call here saw, for the next time a limit is hit and nobody knows which bucket
RATE_LOW = 500                      # one log line (instance timezone) when a call sees fewer than this many left, once per window
RATE_PROBE_S = 60.0                 # while a rate limit holds, GET /rate_limit (it costs no call) this often, to resume the moment the bucket has room again
RATE_RESUME_MIN = 50                # ...and resume when that many calls are left


# ----------------------------------------------------------------------------- config ([github])
def _flag(v: Any) -> bool:
    return v is True or str(v).strip().lower() in ("true", "1", "yes")


def enabled() -> bool:
    """[github] sync: true = every item change is mirrored to an issue in issues_repo through the queue; false (default) = nothing is sent."""
    return _flag(_cfg.get("github", "sync"))


def issue_ids() -> bool:
    """[github] issue_ids: true = a new item's id is its issue number (board#N); false (default) = the [ids] letter sequence."""
    return _flag(_cfg.get("github", "issue_ids"))


def repo() -> str:
    return str(_cfg.get("github", "issues_repo") or "").strip().strip("/")


def repo_id() -> int:
    """[github] issues_repo_id: GitHub's numeric id of the issues repo, a positive integer (or a digit string); 0 = not set (empty, missing
    or not a positive integer). When set, every REST call for the issues repo goes to /repositories/<id>/..., which a transfer to another owner
    does not change (GitHub follows a 301 on a read but not on a write); issues_repo still names the repo for display and the issue links."""
    v = _cfg.get("github", "issues_repo_id")
    if isinstance(v, bool):
        return 0
    if isinstance(v, int):
        return v if v > 0 else 0
    t = str(v or "").strip()
    return int(t) if t.isdigit() and int(t) > 0 else 0


def api_url() -> str:
    return str(_cfg.get("github", "api_url") or API_DEFAULT).rstrip("/")


def letter() -> str:
    """[github] issues_letter: the store letter of issue-numbered items (g/<n>.json); one lowercase letter, default g."""
    v = str(_cfg.get("github", "issues_letter") or DEFAULT_LETTER).strip().lower()
    return v if len(v) == 1 and v.isalpha() else DEFAULT_LETTER


def local_letter() -> str:
    """[github] local_letter: the store letter of an item created while GitHub was down (l/<n>.json, id l<n>), temporary
    until the worker re-keys it to its issue number; one lowercase letter, default l."""
    v = str(_cfg.get("github", "local_letter") or DEFAULT_LOCAL_LETTER).strip().lower()
    return v if len(v) == 1 and v.isalpha() else DEFAULT_LOCAL_LETTER


_MACHINE_RX = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?")


def machine() -> str:
    """[instance] machine: the name of the box the server runs on ("main-box"), written into a temporary id.
    Lowercase letters, digits and hyphens only; unset, or anything else, reads as "local". Restart-only."""
    v = str(_cfg.get("instance", "machine") or "").strip()
    return v if _MACHINE_RX.fullmatch(v) else DEFAULT_MACHINE


def local_prefix() -> str:
    """board-tmp-<machine>: what a temporary id is written with, before #<n> (shown) or -<n> (its page address, href_id)."""
    return f"board-tmp-{machine()}"


def is_local(gid: str) -> bool:
    """A temporary local id (l<n>): one the worker re-keys when GitHub answers."""
    g = str(gid or "")
    return len(g) > 1 and g[0] == local_letter() and g[1:].isdigit()


def pace_s() -> float:
    try:
        return max(0.0, float(_cfg.get("github", "min_interval_seconds", default=DEFAULT_PACE)))
    except (TypeError, ValueError):
        return DEFAULT_PACE


def hourly_budget() -> int:
    """[github] hourly_budget: the writes an hour (default 250)."""
    try:
        return max(1, int(_cfg.get("github", "hourly_budget", default=DEFAULT_BUDGET)))
    except (TypeError, ValueError):
        return DEFAULT_BUDGET


def read_budget() -> int:
    """[github] read_budget: the counted GitHub reads an hour (the server's and anchor-hub's together, ghbudget.py). Live."""
    return _gb.read_cap()


def merge_seconds() -> float:
    """[github] merge_seconds: how long the updates of an existing issue wait to go out as one PATCH (default 300; 0 = each
    update goes at once, as before an earlier change). A create and a close or reopen never wait. Live."""
    try:
        return max(0.0, float(_cfg.get("github", "merge_seconds", default=DEFAULT_MERGE)))
    except (TypeError, ValueError):
        return DEFAULT_MERGE


def poll_seconds() -> float:
    """[github] poll_seconds: how often the reader asks the repo for new comments (phase 3); default 60, never under MIN_POLL. Live."""
    try:
        return max(MIN_POLL, float(_cfg.get("github", "poll_seconds", default=DEFAULT_POLL)))
    except (TypeError, ValueError):
        return DEFAULT_POLL


def owner_login() -> str:
    """[github] owner_login: the GitHub login the owner comments from (phase 3); "" (the default) = the login the mirror's token
    belongs to (GitHub.login()), the account the server writes with. Live."""
    return str(_cfg.get("github", "owner_login") or "").strip()


def board_url() -> str:
    return str(_cfg.get("instance", "board_url") or "").rstrip("/")


def backfill_bodies() -> bool:
    """[github] backfill_bodies: true (with sync on) = when BODY_FORM is above the one recorded, every mirrored issue whose body differs from what the item renders now is
    rewritten once, paced, on the background lane (resync_bodies). false (the default): an issue takes the slim body the next time its subject, state or
    description changes. Live."""
    return _flag(_cfg.get("github", "backfill_bodies"))


_TOKEN: list[str] = []


def token(token_file: str = "") -> str:
    """The token the mirror writes with: [github] token_file (one line) when set, else the gh CLI's login (`gh auth token`,
    the account every session on the box already uses). Cached for the process; '' when neither answers."""
    tf = token_file or str(_cfg.get("github", "token_file") or "").strip()
    if tf:
        try:
            return Path(os.path.expanduser(tf)).read_text(encoding="utf-8").strip().splitlines()[0].strip()
        except (OSError, IndexError):
            return ""
    if _TOKEN:
        return _TOKEN[0]
    try:
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=20)
        t = r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        t = ""
    if t:
        _TOKEN.append(t)
    return t


# ----------------------------------------------------------------------------- the map (<store>/github.json)
def store_dir() -> Path:
    return _cfg.path("paths", "store")


_MAP_CACHE: dict[str, Any] = {"path": None, "mtime": None, "map": None}
_MAP_LOCK = threading.Lock()


def _empty_map() -> dict[str, Any]:
    return {"repo": "", "issues": {}, "aliases": {}}


def load_map(store: Path | None = None) -> dict[str, Any]:
    """{"repo": owner/name, "issues": {gid: issue number}, "aliases": {old gid: gid}, "local_last": the highest local number
    given out (phase 2 prep; absent before the first)}; cached by the file's mtime."""
    p = (store or store_dir()) / MAP_NAME
    with _MAP_LOCK:
        try:
            mt = p.stat().st_mtime_ns
        except OSError:
            return _empty_map()
        if _MAP_CACHE["path"] == p and _MAP_CACHE["mtime"] == mt and _MAP_CACHE["map"] is not None:
            return _MAP_CACHE["map"]
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return _empty_map()
        if not isinstance(m, dict):
            m = _empty_map()
        m.setdefault("repo", ""); m.setdefault("issues", {}); m.setdefault("aliases", {})
        _MAP_CACHE.update(path=p, mtime=mt, map=m)
        return m


def save_map(m: dict[str, Any], store: Path | None = None) -> None:
    p = (store or store_dir()) / MAP_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp")
    tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    with _MAP_LOCK:
        _MAP_CACHE.update(path=None, mtime=None, map=None)


def issue_of(gid: str, store: Path | None = None) -> int:
    """The issue number mirroring `gid` (an alias resolved), 0 when it has none yet."""
    m = load_map(store)
    g = str(m["aliases"].get(gid) or gid)
    try:
        return int(m["issues"].get(g) or 0)
    except (TypeError, ValueError):
        return 0


def resolve(gid: str, store: Path | None = None) -> str:
    """A migrated item's old id → its id now; any other id as it is."""
    return str(load_map(store)["aliases"].get(gid) or gid)


def item_of_issue(n: int, store: Path | None = None) -> str:
    """The id of the item issue n mirrors (the id now, never an alias), '' when no item has that issue (phase 3: a comment on
    such an issue is skipped)."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ""
    for g, k in load_map(store)["issues"].items():
        try:
            if int(k) == n:
                return str(g)
        except (TypeError, ValueError):
            continue
    return ""


def record_issue(gid: str, n: int, store: Path | None = None, was: str = "") -> None:
    """The map: `gid` mirrors issue n; `was` (the id the item had before a move) becomes its alias and leaves the issues."""
    m = dict(load_map(store)); m["issues"] = dict(m["issues"]); m["aliases"] = dict(m["aliases"])
    m["issues"][gid] = int(n)
    if was and was != gid:
        m["aliases"][was] = gid
        m["issues"].pop(was, None)
    if not m.get("repo"):
        m["repo"] = repo()
    save_map(m, store)


_LOCAL_LOCK = threading.Lock()


def allocate_local(store: Path | None = None) -> str:
    """A temporary id for an item created while GitHub is down (phase 2 prep): the next number under [github] local_letter,
    never one given out before. The counter is `local_last` in the map, written (atomically) before the id is returned, so a
    crash between the two burns the number rather than reusing it; it is seeded from the map's aliases and the files under
    the letter as well, so a map lost and rebuilt from the repo (reconcile) still never hands out an old number."""
    store = store or store_dir(); L = local_letter()
    with _LOCAL_LOCK:
        m = dict(load_map(store))
        try:
            last = int(m.get("local_last") or 0)
        except (TypeError, ValueError):
            last = 0
        for k in m["aliases"]:
            if len(k) > 1 and k[0] == L and k[1:].isdigit():
                last = max(last, int(k[1:]))
        d = store / L
        if d.is_dir():
            for p in d.glob("*.json"):
                if not p.name.startswith(".") and p.stem.isdigit():
                    last = max(last, int(p.stem))
        m["local_last"] = last + 1
        save_map(m, store)
        return f"{L}{last + 1}"


_BOARD_ID = re.compile(r"^(?:board)?#([1-9]\d*)$")


_NUM = re.compile(r"[1-9]\d*")


def norm(text: str) -> str:
    """#7 (and board#N is not a form) → g7; board-tmp-<machine>#3 and board-tmp-<machine>-3 → l3, for this
    server's own [instance] machine only (another machine's prefix is not a form); anything else → ''."""
    t = str(text or "").strip().lower()
    m = _BOARD_ID.match(t)
    if m:
        return f"{letter()}{m.group(1)}"
    p = local_prefix()
    if len(t) > len(p) + 1 and t.startswith(p) and t[len(p)] in "#-" and _NUM.fullmatch(t[len(p) + 1:]):
        return f"{local_letter()}{t[len(p) + 1:]}"
    return ""


def shown(gid: str) -> str:
    """How an id is written for a person: board#N for an issue-numbered item, board-tmp-<machine>#3 for a temporary one
    (created while GitHub was down), the id itself for the others."""
    g = str(gid or "")
    if is_local(g):
        return f"{local_prefix()}#{g[1:]}"
    return f"board#{g[1:]}" if len(g) > 1 and g[0] == letter() and g[1:].isdigit() else g


def ref(gid: str, store: Path | None = None) -> str:
    """How text written for GitHub names another item: #N, its issue number, which GitHub links natively; an item
    with no issue yet (a temporary one, or an old id never mirrored) keeps its shown form, board-tmp-<machine>#3. The board, the pages
    and the notices a session reads keep board#N (shown()). Since an earlier change the mirror writes no text of that kind (the body is the
    description alone), so only the server's `note` lines, which no longer reach GitHub, still use it."""
    g = resolve(str(gid or ""), store)
    n = issue_of(g, store)
    return f"#{n}" if n else shown(g)


def href_id(gid: str) -> str:
    """The id in an item's page address, /items/<href_id>: the bare number for an issue-numbered item (g7 → 7, its page
    /items/<n>, as the item is written board#N), board-tmp-<machine>-3 for a temporary id, the id itself for the others (the
    server answers /items/g7 and /items/l3 with a redirect to it)."""
    g = str(gid or "")
    if is_local(g):
        return f"{local_prefix()}-{g[1:]}"
    return g[1:] if len(g) > 1 and g[0] == letter() and g[1:].isdigit() else g


# ----------------------------------------------------------------------------- the GitHub client
class GitHubError(Exception):
    """A refusal (4xx that is not a rate limit): the job is wrong, trying again will not help."""
    def __init__(self, status: int, text: str):
        super().__init__(f"HTTP {status}: {text}" if status else text)
        self.status, self.text = status, text


class GitHubDown(GitHubError):
    """GitHub did not answer, or answered 5xx, 429 or a rate limit: try later."""
    def __init__(self, status: int, text: str, retry_after: float = 0.0, primary: bool = False):
        super().__init__(status, text)
        self.retry_after = retry_after
        self.primary = primary      # a primary limit of the core bucket (x-ratelimit-remaining 0, no Retry-After): the bucket may have room again before the reset; a secondary limit or another resource waits out what GitHub said


class GitHubBudget(GitHubDown):
    """The hourly cap is spent (ghbudget.py: [github] read_budget for a read, hourly_budget for a write): this call was not sent. `retry_after` is
    the seconds until the ledger has room. Status 0, so a caller that waits out a rate limit (status 403 or 429) does not mistake it for one; the reader
    thread and the merged-PR check already back off by retry_after on any GitHubDown. A write raises it only when its caller asked not to wait
    (`max_wait`: a create answering a person); the queue worker's writes wait for room instead."""
    def __init__(self, cap: int, retry_after: float, what: str = "reads"):
        super().__init__(0, f"GitHub {what} are held by the hourly cap ({cap}); they resume in {_gb.held_words(retry_after)}", retry_after)


def _issue_number(r: Any) -> int:
    """The issue number in a create's answer. GitHubDown when the answer carries none (a redirect's body, an empty answer):
    nothing says an issue was made, so the create waits (a temporary id, the job in the queue) rather than crash on the
    missing key or pass as done.
    (for instance when [github] issues_repo names a repo that has moved)."""
    try:
        n = int(r.get("number") or 0) if isinstance(r, dict) else 0
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        raise GitHubDown(0, f"the create was answered without an issue number ({str(r)[:160]})")
    return n


_UNCAPPED = threading.local()      # set while the queue's worker drains and while an item's issue is allocated: the reads a write makes (the marker lookup) count but are never held by the read cap


@contextlib.contextmanager
def uncapped() -> Iterator[None]:
    """The reads made inside are counted in the ledger but never refused by the read cap (they belong to a write that must not fail on it: a create
    that would fall back to a temporary id, a drain). Saves and restores the flag as it was, so one inside another leaves the outer on."""
    was = getattr(_UNCAPPED, "on", False)
    _UNCAPPED.on = True
    try:
        yield
    finally:
        _UNCAPPED.on = was


_RATE: dict[str, Any] = {"saved": 0.0, "window": {}, "last": {}}      # last: resource -> its newest record
_RATE_LOCK = threading.Lock()
_NEVER = threading.Event()


def rate_seen(resource: str = "core") -> dict[str, Any]:
    """The newest X-RateLimit headers any call in this process saw for a resource (core, graphql, search...): {limit, remaining, used, reset, resource, at, status}; {} before the first."""
    with _RATE_LOCK:
        return dict(_RATE["last"].get(resource) or {})


def note_rate(hdr: Any, status: int = 0, say: Callable[[str], None] | None = None) -> None:
    """Keep what a response says about the rate limit (nothing recorded it, so a limit once could not be traced to a bucket).
    The headers go to <state>/github/ratelimit.json (at most twice a minute, and at once on a 403 or 429), and one line goes to the log, in the instance timezone, the
    first time a window is seen under RATE_LOW calls. Never raises."""
    try:
        def h(k: str) -> str:
            return str(hdr.get(k) or "") if hdr is not None else ""
        if not h("x-ratelimit-limit"):
            return
        rec = {"limit": int(h("x-ratelimit-limit") or 0), "remaining": int(h("x-ratelimit-remaining") or 0), "used": int(h("x-ratelimit-used") or 0),
               "reset": int(h("x-ratelimit-reset") or 0), "resource": h("x-ratelimit-resource"), "at": int(time.time()), "status": int(status)}
        res = rec["resource"] = rec["resource"] or "core"
        with _RATE_LOCK:
            _RATE["last"][res] = rec
            due = time.time() - float(_RATE["saved"]) >= 30.0 or status in (403, 429)
            low = bool(rec["remaining"] < RATE_LOW and rec["reset"] and _RATE["window"].get(res) != rec["reset"])
            if due:
                _RATE["saved"] = time.time()
            if low:
                _RATE["window"][res] = rec["reset"]
            if due:                                           # one file, one record per resource, written under the lock with a name of its own
                p = _cfg.state("github", RATE_NAME)
                p.parent.mkdir(parents=True, exist_ok=True)
                tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
                tmp.write_text(json.dumps(_RATE["last"]) + "\n", encoding="utf-8")
                os.replace(tmp, p)
        if low:
            reset_at = time.strftime("%H:%M", time.gmtime(rec["reset"]))
            (say or (lambda m: print(m, file=sys.stderr, flush=True)))(
                f"ghsync: GitHub {rec['resource'] or 'core'} limit: {rec['remaining']} of {rec['limit']} calls left, resets {reset_at} UTC")
    except Exception:  # noqa: BLE001  -- a record of the limit never breaks a call
        pass


def wait_rate_limit(gh: "GitHub", retry_after: float, stop: threading.Event | None = None, primary: bool = True) -> float:
    """A rate limit holds (a 403 or 429 with GitHub's reset in `retry_after` s): wait for it, but ask GET /rate_limit (which costs no call) every RATE_PROBE_S
    for room, so the queue drains the moment the bucket has RATE_RESUME_MIN calls again, early or at the reset, and never a backoff later (the
    worker used to double its wait to 10 min whatever GitHub said). `primary` False (a Retry-After answer, a secondary limit, a resource other than core):
    the full time is waited, the core bucket having room says nothing about it. A probe that fails for any reason is a look not made. -> the seconds waited."""
    t0 = time.monotonic()
    end = t0 + max(0.0, float(retry_after)) + 2.0
    ev = stop or _NEVER
    while time.monotonic() < end:
        if ev.wait(min(RATE_PROBE_S, max(0.5, end - time.monotonic()))):
            break
        if time.monotonic() >= end:
            break
        if not primary:
            continue
        try:
            if gh.core_left() >= RATE_RESUME_MIN:
                break
        except Exception:  # noqa: BLE001  -- a GitHubError or a bad answer: no look this time, the wait goes on
            continue
    return time.monotonic() - t0


class _WriteRedirects(urllib.request.HTTPRedirectHandler):
    """urllib's redirect handler follows a GET on its own, turns a POST answered 301, 302 or 303 into a GET of the new url (a
    comment's POST would come back as the issue's comment list) and refuses a 307 or 308 on a write. Here no write follows a
    redirect at all: the 3xx comes back as the answer, and request() treats it as GitHub not answering (the repo moved and
    [github] issues_repo still names its old home), so the job waits in the queue instead of passing as
    done. A GET still follows, so the reads go on through the move."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        if req.get_method() not in ("GET", "HEAD"):
            raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_WriteRedirects)


class GitHub:
    """A thin REST client for one repo: urllib, a token, and the pace of its writes. `shared` (the server's clients, client() and the PR checks')
    puts every call on the host's hourly ledger (ghbudget.py): a write waits for room under hourly_budget, a read is refused over read_budget, a
    304 is not counted; a client made directly (the migration CLI, a test) keeps its own in-memory count of writes and counts no reads."""

    def __init__(self, repo_: str, api: str = "", token_: str = "", pace: float | None = None, budget: int | None = None, shared: bool = False,
                 repo_id_: int = 0, caller: str = ""):
        self.caller = caller      # the ledger tag of this client's calls when neither the request nor its thread names one (ghbudget.CALLERS); "" is "other"
        self.repo = repo_
        self.repo_id = int(repo_id_) if isinstance(repo_id_, int) and not isinstance(repo_id_, bool) and repo_id_ > 0 else 0
        self.api = (api or api_url()).rstrip("/")
        self._token = token_
        self.pace = pace_s() if pace is None else max(0.0, float(pace))
        self.budget = hourly_budget() if budget is None else max(1, int(budget))
        self.shared = bool(shared)
        self._writes: collections.deque[float] = collections.deque()
        self._lock = threading.Lock()
        self._login: str | None = None
        self.writes = 0          # content writes made, for a report
        self._etags: dict[str, tuple[str, Any]] = {}   # url -> (ETag, the answer): for the reads asked with etag=True; guarded by _elock
        self._elock = threading.Lock()
        self.cached = 0          # reads answered 304 from those
        self.reads = 0           # counted reads made (a 304 is none), for a report
        self.sleep: Callable[[float], None] = time.sleep

    def tok(self) -> str:
        return self._token or token()

    def login(self) -> str:
        """The login the token belongs to (GET /user), asked once per client; '' when GitHub refused it (the next call asks
        again). GitHubDown propagates: the caller treats it as an outage."""
        if self._login is None:
            try:
                r = self.request("GET", "/user")
            except GitHubDown:
                raise
            except GitHubError:
                return ""
            lg = str((r or {}).get("login") or "").strip() if isinstance(r, dict) else ""
            if not lg:
                return ""
            self._login = lg
        return self._login

    def recent_writes(self) -> int:
        """The writes this client made in the last hour (what hourly_budget counts); for a shared client the larger of that and the host's
        ledger (a restart forgets the first, not the second)."""
        with self._lock:
            now = time.monotonic()
            n = sum(1 for t in self._writes if now - t <= 3600)
        return max(n, _gb.count(_gb.WRITE)) if self.shared else n

    def _throttle(self, max_wait: float | None = None, caller: str = "") -> None:
        """Take the place for one write, sleeping until the pace and the hour's budget allow it. With `max_wait` (seconds) the call never waits longer: a
        write that would have to (the budget spent, or another write holding the line for room) raises GitHubBudget at once with the seconds until
        there is room, and takes no place. `max_wait` is one deadline for the whole call: the line, the pace and the ledger together."""
        deadline = None if max_wait is None else time.monotonic() + max_wait
        if max_wait is None:
            self._lock.acquire()
        elif not self._lock.acquire(timeout=max_wait):
            raise GitHubBudget(self.budget, max(self._room_in(), max_wait), "writes")    # another write is waiting its turn for room
        try:
            now = time.monotonic()
            while self._writes and now - self._writes[0] > 3600:
                self._writes.popleft()
            wait = 0.0
            if len(self._writes) >= self.budget:
                wait = max(wait, self._writes[0] + 3600 - now)
            if self._writes:
                wait = max(wait, self._writes[-1] + self.pace - now)
            if max_wait is not None:
                if self.shared:
                    wait = max(wait, _gb.wait(_gb.WRITE, self.budget))
                if wait > deadline - now:
                    raise GitHubBudget(self.budget, wait, "writes")
            if wait > 0:
                self.sleep(wait)
            if self.shared:                                  # the host's ledger: the write is taken when there is room (a restart, or another client, may have spent the hour)
                while True:
                    lw = _gb.take(_gb.WRITE, self.budget, caller=caller)
                    if lw <= 0:
                        break
                    if deadline is not None and lw > deadline - time.monotonic():      # another process took the room between the look above and now
                        raise GitHubBudget(self.budget, lw, "writes")
                    self.sleep(lw)
            self._writes.append(time.monotonic())
            self.writes += 1
        finally:
            self._lock.release()

    def _room_in(self) -> float:
        """Seconds until the hour's budget has room for one more write, by the host's ledger when the client is shared, else by its own count; no lock is taken."""
        if self.shared:
            return _gb.wait(_gb.WRITE, self.budget)
        try:
            mine = list(self._writes)
        except RuntimeError:                                 # the deque changed under the copy: no estimate
            return 0.0
        return max(0.0, mine[-self.budget] + 3600 - time.monotonic()) if len(mine) >= self.budget else 0.0

    def repo_path(self, rest: str = "") -> str:
        """The REST path of the client's repo with `rest` after it: /repositories/<id><rest> when the repo's numeric id is set
        ([github] issues_repo_id: it survives a transfer, and a write is not redirected), else /repos/<owner>/<name><rest>."""
        return (f"/repositories/{self.repo_id}" if self.repo_id else f"/repos/{self.repo}") + rest

    def request(self, method: str, path: str, body: Any = None, params: dict[str, Any] | None = None, etag: bool = False, max_wait: float | None = None, caller: str = "") -> Any:
        """One call. `max_wait` (a write): the most seconds the write may wait for its place under the pace and the hour's budget; over it GitHubBudget is
        raised and nothing is sent. `etag` (a GET read again and again): the last answer's
        ETag goes out as If-None-Match and a 304, which GitHub does not count against the 5,000 an hour, gives the last
        answer back; the answers are kept in this client, for the process. `caller` (ghbudget.CALLERS): who asked, kept with the call in the host's
        ledger; none given, the thread's tag (`with ghbudget.tag(...)`), else the client's own, else "other"."""
        who = caller or _gb.current() or self.caller
        url = self.api + path + (("?" + urllib.parse.urlencode(params)) if params else "")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "stackshot-ghsync"}
        t = self.tok()
        if t:
            headers["Authorization"] = f"Bearer {t}"
        if data is not None:
            headers["Content-Type"] = "application/json"
        is_write = method in ("POST", "PATCH", "PUT", "DELETE")
        if is_write:
            _ro.guard("GitHub write")
        counts_read = self.shared and not is_write and path != "/rate_limit"      # GET /rate_limit costs GitHub nothing: never counted
        if is_write:
            self._throttle(max_wait, who)
        elif counts_read and not getattr(_UNCAPPED, "on", False):
            held = _gb.wait(_gb.READ, read_budget())
            if held > 0:
                raise GitHubBudget(read_budget(), held)
        with self._elock:
            known = self._etags.get(url) if etag and method == "GET" else None
        if known:
            headers["If-None-Match"] = known[0]
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with _OPENER.open(req, timeout=30) as r:
                status, raw, hdr = r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            status, raw, hdr = e.code, e.read(), e.headers
        except (urllib.error.URLError, OSError) as e:          # no network, a refused connection, a timeout
            raise GitHubDown(0, f"{type(e).__name__}: {e}") from e
        text = raw.decode("utf-8", "replace")
        note_rate(hdr, status)
        if status == 304 and known:                             # unchanged since the ETag: the kept answer, free (and not in the ledger)
            self.cached += 1
            return copy.deepcopy(known[1])
        if counts_read:                                         # any other answer GitHub counted against the token
            self.reads += 1
            _gb.note(_gb.READ, caller=who)
        if 300 <= status < 400:                                 # a redirect not followed (a write: the repo moved; a GET with no Location): no answer to act on
            loc = str(hdr.get("location") or "")
            print(f"ghsync: HTTP {status} on {method} {url}" + (f" → {loc}" if loc else "") + f"; the write waits (does [github] issues_repo = {self.repo} name the repo's current home? or set [github] issues_repo_id to the repo's numeric id, which a move does not change)",
                  file=sys.stderr, flush=True)
            raise GitHubDown(status, f"redirected ({method} {path}" + (f" → {loc}" if loc else "") + "); the repo may have moved")
        if status == 429 or status >= 500 or (status == 403 and (hdr.get("x-ratelimit-remaining") == "0" or hdr.get("retry-after")
                                                                   or "rate limit" in text.lower())):
            ra = 0.0
            try:
                ra = float(hdr.get("retry-after") or 0)
            except ValueError:
                ra = 0.0
            if not ra and hdr.get("x-ratelimit-reset"):
                try:
                    ra = max(0.0, float(hdr.get("x-ratelimit-reset")) - time.time())
                except ValueError:
                    ra = 0.0
            primary = status in (403, 429) and hdr.get("x-ratelimit-remaining") == "0" and not hdr.get("retry-after") and (hdr.get("x-ratelimit-resource") or "core") == "core"
            raise GitHubDown(status, text[:300], ra, primary)
        if status >= 400:
            raise GitHubError(status, text[:300])
        if not text.strip():
            return {}
        try:
            out = json.loads(text)
        except ValueError:
            return {}
        if etag and method == "GET" and hdr.get("etag"):
            with self._elock:
                self._etags[url] = (str(hdr.get("etag")), copy.deepcopy(out))
                if len(self._etags) > 200:                      # a bound: the oldest kept answer goes
                    self._etags.pop(next(iter(self._etags)))
        return out

    def rate_limit(self) -> dict[str, Any]:
        """GET /rate_limit: the buckets as GitHub counts them now. This call costs nothing against them."""
        r = self.request("GET", "/rate_limit")
        return r if isinstance(r, dict) else {}

    def core_left(self) -> int:
        """The calls left in the core bucket (GitHubDown propagates)."""
        return int(((self.rate_limit().get("resources") or {}).get("core") or {}).get("remaining") or 0)

    # issues
    def create_issue(self, title: str, body: str, max_wait: float | None = None) -> dict[str, Any]:
        return self.request("POST", self.repo_path("/issues"), {"title": title, "body": body}, max_wait=max_wait)

    def edit_issue(self, n: int, **fields: Any) -> dict[str, Any]:
        return self.request("PATCH", self.repo_path(f"/issues/{n}"), fields)

    def get_issue(self, n: int) -> dict[str, Any]:
        return self.request("GET", self.repo_path(f"/issues/{n}"))

    def list_issues(self) -> list[dict[str, Any]]:
        """Every issue of the repo (pull requests, which share the counter, left out)."""
        out: list[dict[str, Any]] = []
        page = 1
        while True:
            rows = self.request("GET", self.repo_path("/issues"), params={"state": "all", "per_page": 100, "page": page}) or []
            out += [r for r in rows if isinstance(r, dict) and not r.get("pull_request")]
            if len(rows) < 100:
                return out
            page += 1

    def list_comments_since(self, since: str) -> list[dict[str, Any]]:
        """The repo's issue comments updated at `since` (ISO 8601 UTC) or after, oldest update first, 100 a page, every page
        (phase 3: one GET a poll in the common case). Reads are not paced."""
        out: list[dict[str, Any]] = []
        page = 1
        while True:
            rows = self.request("GET", self.repo_path("/issues/comments"), etag=page == 1, caller="comments",
                                params={"since": since, "sort": "updated", "direction": "asc", "per_page": 100, "page": page}) or []
            out += [r for r in rows if isinstance(r, dict)]
            if len(rows) < 100:
                return out
            page += 1


_CLIENT: dict[str, GitHub] = {}


def known_login() -> str:
    """The login the owner writes on GitHub as, without asking GitHub (the router's test of a notice that is the owner's own): [github] owner_login,
    else the login the token of a client of this process already read (GET /user, cached on the client), else ''."""
    lg = owner_login()
    return lg or next((c._login for c in _CLIENT.values() if c._login), "")


def client() -> GitHub:
    """The process's one client for [github] issues_repo (one pace for the worker and the id allocator together)."""
    key = f"{api_url()} {repo()} {repo_id()}"
    c = _CLIENT.get(key)
    if c is None:
        c = _CLIENT[key] = GitHub(repo(), api_url(), shared=True, repo_id_=repo_id(), caller="ghsync")
    return c


# ----------------------------------------------------------------------------- what an item looks like on GitHub
# Slim mirror: an issue carries the item's subject (the title), whether it is open or
# closed, and its description (the body). Nothing else of the item is on GitHub: no labels, no typed fields, no blocked-by, no history
# comments. The store's files are the backup (publish.py pushes them), the History is the store's git.
MARK_RX = re.compile(r"<!-- stackshot:([a-z]\d+)(?: \(was ([a-z]\d+)\))? -->")


def marker(gid: str, was: str = "") -> str:
    return f"<!-- stackshot:{gid}" + (f" (was {was})" if was and was != gid else "") + " -->"


def title_of(item: dict[str, Any]) -> str:
    return str(item.get("subject") or "").strip()[:250] or "(no subject)"


def state_of(item: dict[str, Any]) -> tuple[str, str]:
    """→ ("open", "") or ("closed", "completed" | "not_planned"). `unrecorded` (the migration's back-fill of an item closed before the model) maps to plain `completed`: GitHub closes an issue as completed
    when no reason is given, so the mapping changes nothing on an issue that is already closed."""
    if item.get("status") != "completed":
        return "open", ""
    oc = str((item.get("metadata") or {}).get("outcome") or "")
    return "closed", ("not_planned" if oc in ("dropped", "superseded") else "completed")


def description_of(item: dict[str, Any]) -> str:
    return str(item.get("description") or "").strip()


def outcome_section(item: dict[str, Any]) -> str:
    """A closed item's outcome text as the issue body's last section, "## Outcome" and the text: how it ended, under the description it kept. "" for an open item (a reopen removes
    the section) and for a close with no outcome text (one stored before the field existed: its body already carries the end state it was closed with)."""
    if item.get("status") != "completed":
        return ""
    text = str((item.get("metadata") or {}).get("outcome_text") or "").strip()
    return f"## Outcome\n\n{text}" if text else ""


def body_text(item: dict[str, Any]) -> str:
    """The item's description, and for a closed item with an outcome text the Outcome section after it."""
    return "\n\n".join(x for x in (description_of(item), outcome_section(item)) if x)


def mirrored(item: dict[str, Any] | None) -> tuple[str, str, str, str]:
    """What the issue carries of an item: (title, state, close reason, description). A change to anything else of the item makes no GitHub call."""
    if item is None:
        return ("", "", "", "")
    return (title_of(item), *state_of(item), body_text(item))


def body_of(gid: str, item: dict[str, Any], names: dict[str, str] | None = None, was: str = "") -> str:
    """The issue body (BODY_FORM 3): the marker ghsync maps issue ↔ item by, the item's description (a closed item with an outcome text: then an "## Outcome" section with it),
    and one footer line linking the item's page. Nothing else: not the next line, the ask, the options, the draft or a property line. `names` is kept for the callers that pass it."""
    desc = body_text(item)
    bu = board_url()
    link = f"[{shown(gid)}]({bu}/items/{href_id(gid)})" if bu else shown(gid)
    return "\n\n".join([marker(gid, was), desc or "_none_",
                        f"<sub>Mirrored from {link} by {str(_cfg.get('instance', 'name') or 'stackshot')}; the item is written through it, not here.</sub>"])


# ----------------------------------------------------------------------------- the comments' header (the reader tells the mirror's old comments from the owner's)
AUTHOR_RX = re.compile(r"^\[author: (?P<name>[^\n\]]*?) · (?P<id>[^\n\]]*)\]", re.M)


def parse_header(text: str) -> tuple[str, str] | None:
    """The author of a comment → (name, id) from its `[author: <name> · <session id>]` first line, None when it carries none. The mirror used to post a comment per change under such a
    header (until an earlier change); the ones already on GitHub stay, and the reader still passes them by (is_owner_comment): a comment without one is the owner's."""
    m = AUTHOR_RX.match(str(text or "").lstrip())
    return (m.group("name").strip(), m.group("id").strip()) if m else None


def _options_text(opts: Any) -> str:
    """The options as plain lines, "- Ship (recommended): Ship it now" (the item page's History says an options edit with them)."""
    rows = [o for o in (opts if isinstance(opts, list) else []) if isinstance(o, dict)]
    labels = [str(o.get("label") or "").strip() for o in rows]
    if isinstance(opts, list) and len(rows) == len(opts):      # a list of options only: the labels as a card shows them (the letter its badge draws is dropped, option_labels.py)
        labels = [lb or chr(65 + i) for i, lb in enumerate(_ol.strip_letters(labels))]
    return "\n".join(f"- {lb}" + (" (recommended)" if o.get("recommended") else "") + f": {str(o.get('line') or '').strip()}" for lb, o in zip(labels, rows))


def refile_words(frm: str, to: str) -> str:
    """The History line of a refile: the server moved an item filed under
    another project than its creator's to the creator's."""
    return f"refiled from {frm or 'none'} to {to} (its creator's project)"


def refile_line(pm: dict[str, Any] | None, m: dict[str, Any]) -> str:
    """The refile this version records (metadata.refiled = {from, to}, set by the write that moved it) → its History line;
    "" when this version was not refiled. `pm` is the metadata before (None for a create); a write that asked for a third
    project, overruled by the rule, says both."""
    rf = m.get("refiled")
    if not isinstance(rf, dict) or not rf.get("to") or rf.get("to") != m.get("project"):
        return ""
    if pm is not None and ((pm.get("project") or "") == (m.get("project") or "") or pm.get("refiled") == rf):
        return ""
    frm, to = str(rf.get("from") or ""), str(rf["to"])
    if pm is not None and frm != (pm.get("project") or ""):
        return f"project: {pm.get('project') or 'none'} → {to} (filed under {frm}, refiled to its creator's project)"
    return refile_words(frm, to)


# ----------------------------------------------------------------------------- the queue (<state>/github/queue/*.json)
_EVENT = threading.Event()      # set by enqueue: the worker drains now rather than at its next tick
_SEQ = [0]
_SEQ_LOCK = threading.Lock()


def queue_dir() -> Path:
    return _cfg.state("github", "queue")


def failed_dir() -> Path:
    return _cfg.state("github", "failed")


def write_atomic(p: Path, text: str) -> None:
    """Rewrite a file another thread or process may be reading (a queued job, a failed job) so that a reader sees the old text or the new,
    never half: the text goes to a dot-named temp file of this thread in the same folder (pending() skips a dot name), then os.replace.
    A write that fails leaves the old file as it was and no temp file behind."""
    _ro.guard("write " + str(p))
    tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, p)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _job_text(job: dict[str, Any]) -> str:
    return json.dumps(job, ensure_ascii=False) + "\n"


BACKGROUND = "~"                # the name prefix of a background job (resync_bodies): sorts after every live job, so a live write never waits behind a sweep
RESYNC_KINDS = ("sync",)        # the background kind (resync_bodies): never creates an issue
OBSOLETE_KINDS = ("fields", "labels")   # background jobs an older version queued (typed fields, label sweep): dropped unread, no call
LIVE_RESERVE = 100              # writes of the hourly budget (at most a quarter of it) a background job never takes: the live jobs (a close, a temporary item's issue) never wait out the hour behind a sweep
FIRST = "!"                     # the name prefix of the create job of a temporary item: sorts before every other job, so the item gets its issue at the first place that frees, ahead of the updates queued before it


def enqueue(job: dict[str, Any], background: bool = False) -> Path:
    """A job onto the queue, named by its time so the worker drains in order. The create job of a temporary item (a local id, no issue yet) is named under FIRST, ahead of every other job. A background job
    (background=True: a body resync, a bulk repair's description sync) is named under BACKGROUND, after every live job, and does not wake the worker by itself."""
    d = queue_dir(); d.mkdir(parents=True, exist_ok=True)
    with _SEQ_LOCK:
        _SEQ[0] += 1
        lead = BACKGROUND if background else FIRST if job.get("kind") == "created" and is_local(str(job.get("gid") or "")) else ""
        p = d / f"{lead}{time.time():017.6f}-{os.getpid()}-{_SEQ[0]:06d}.json"
    tmp = p.with_name(f".{p.name}.tmp")
    tmp.write_text(json.dumps(job, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    if not background:
        _EVENT.set()
    return p


# The form of the issue body (body_of). Bumped whenever body_of changes what it writes for items already mirrored, so that
# resync_bodies can bring every such issue up once, through the queue. 2: the ask and options only while the item still needs
# his decision, another item named #N. 3: the slim body, the marker, the description and the footer link only.
# The sweep is not run by itself (backfill_bodies, default off): an issue takes the slim body the next time its
# subject, state or description changes, so a large sweep costs no write they would not cost anyway.
BODY_FORM = 3
BODY_FORM_NAME = "body_form.json"   # <state>/github/body_form.json: {"form": the BODY_FORM the last resync queued for}


def _body_form_path() -> Path:
    return _cfg.state("github", BODY_FORM_NAME)


def resync_bodies(store: Path | None = None, say: Callable[[str], None] | None = None, force: bool = False) -> int:
    """The one-time rewrite after body_of changed (BODY_FORM above what <state>/github/body_form.json records; `force` runs
    it regardless): every mirrored item whose issue, as last synced, differs from what it renders now (the fingerprint in
    synced.json, missing for an item never synced since the migration) gets one background job of kind "sync". The worker
    drains it like any job, so it is paced by the client (min_interval_seconds between two writes, hourly_budget an hour):
    one PATCH of the issue (title, body, state), and none at all when the fingerprint matches by then. Background jobs drain after every live one, yield to a live write that arrives meanwhile, and
    stop short of the last quarter of the hourly budget (LIVE_RESERVE at most), left to live writes. The form is recorded once queued, so a restart
    queues nothing twice. → the jobs queued (0 with the mirror off)."""
    say = say or (lambda s: print(f"ghsync: {s}", file=sys.stderr, flush=True))
    if not enabled() or not repo():
        return 0
    fp_path = _body_form_path()
    if not force:
        try:
            if int(json.loads(fp_path.read_text(encoding="utf-8")).get("form") or 0) >= BODY_FORM:
                return 0
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    store = store or store_dir()
    m = load_map(store)
    aliases = {v: k for k, v in m["aliases"].items()}
    synced, names = _synced(), _names()
    def num(kv: tuple[str, Any]) -> int:
        try:
            return int(kv[1])
        except (TypeError, ValueError):
            return 0
    queued_n = 0
    for gid, n in sorted(m["issues"].items(), key=num):
        if not num((gid, n)):
            continue
        item = _load_item(store, gid)
        if item is None:
            continue
        state, reason = state_of(item)
        if synced.get(gid) == _fingerprint(title_of(item), body_of(gid, item, names, aliases.get(gid, "")), state, reason):
            continue
        enqueue({"ts": time.time(), "gid": gid, "kind": "sync"}, background=True)
        queued_n += 1
    fp_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = fp_path.with_name(f".{fp_path.name}.tmp")
    tmp.write_text(json.dumps({"form": BODY_FORM, "queued": queued_n, "at": time.time()}) + "\n", encoding="utf-8")
    os.replace(tmp, fp_path)
    if queued_n:
        say(f"body form {BODY_FORM}: {queued_n} issue(s) queued for a paced body rewrite")
        _EVENT.set()
    return queued_n


def pending() -> list[Path]:
    d = queue_dir()
    return sorted(p for p in d.glob("*.json") if not p.name.startswith(".")) if d.is_dir() else []


def on_change(gid: str, before: dict[str, Any] | None, after: dict[str, Any], background: bool = False) -> Path | None:
    """The server's hook after a save: with the mirror on, one job for the queue when the issue would differ: a create, or a change of what the issue carries
    (mirrored(): the subject, open or closed, the description). None when the mirror is off or nothing of that changed: a change to any other field makes no
    job and so no GitHub call at all. The issue is brought up to the item as it stands at drain time; a create and a close or reopen go out at
    once (a new item needs its board#N; a closed issue must read closed), every other update of an existing issue waits out [github] merge_seconds with the
    rest of its window (drain), so the issue gets one PATCH for them all. `background` (a bulk repair rewriting many items' descriptions, which nobody waits
    on): a change that leaves the item open or closed as it was is a body sync queued under BACKGROUND, after every live job and inside the reserve a live
    write keeps; it never creates an issue."""
    if not enabled():
        return None
    created = before is None
    if not created and mirrored(before) == mirrored(after):
        return None
    if background and not created and state_of(before)[0] == state_of(after)[0]:
        return enqueue({"ts": time.time(), "gid": gid, "kind": "sync"}, background=True)
    urgent = created or state_of(before)[0] != state_of(after)[0]
    return enqueue({"ts": time.time(), "gid": gid, "kind": "created" if created else "changed", "urgent": urgent})


def _synced_path() -> Path:
    return _cfg.state("github", "synced.json")


def _synced() -> dict[str, str]:
    try:
        return json.loads(_synced_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_synced(d: dict[str, str]) -> None:
    p = _synced_path(); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp"); tmp.write_text(json.dumps(d), encoding="utf-8"); os.replace(tmp, p)


def _fingerprint(title: str, body: str, state: str, reason: str) -> str:
    return hashlib.sha1(json.dumps([title, body, state, reason], ensure_ascii=False).encode("utf-8")).hexdigest()


def _item_file(store: Path, gid: str) -> Path:
    return store / gid[0] / f"{gid[1:]}.json"


def _load_item(store: Path, gid: str) -> dict[str, Any] | None:
    p = _item_file(store, gid)
    if not p.exists():
        return None
    try:
        it = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return it if isinstance(it, dict) else None


def find_by_marker(gh: GitHub, gid: str) -> int:
    """The issue whose body carries the marker of `gid` (as the id now, or as the old id), 0 when none: the guard against
    a second issue when a create's answer was lost."""
    for i in gh.list_issues():
        m = MARK_RX.search(str(i.get("body") or ""))
        if m and gid in (m.group(1), m.group(2)):
            return int(i["number"])
    return 0


def sync_issue(gh: GitHub, store: Path, gid: str, item: dict[str, Any], n: int, names: dict[str, str] | None, synced: dict[str, str], was: str = "",
               say: Callable[[str], None] | None = None) -> bool:
    """Bring issue n up to the item: title, body and state, in one PATCH, only when they differ from the last sync (the fingerprint in
    <state>/github/synced.json). → True when a write was made."""
    title, body = title_of(item), body_of(gid, item, names, was)
    state, reason = state_of(item)
    fp = _fingerprint(title, body, state, reason)
    if synced.get(gid) == fp:
        return False
    fields: dict[str, Any] = {"title": title, "body": body, "state": state}
    if state == "closed":
        fields["state_reason"] = reason
    gh.edit_issue(n, **fields)
    synced[gid] = fp
    _save_synced(synced)
    return True


def _names() -> dict[str, str]:
    try:
        import anchors as _anc
        return dict(_anc.names())
    except Exception:  # noqa: BLE001
        return {}


def note_repo(store: Path | None = None, say: Callable[[str], None] | None = None) -> bool:
    """The map's `repo` note brought to [github] issues_repo when the two differ (the org move: the config names the new repo,
    and the server writes the note, never a hand edit in the store). Nothing reads the note back; the publisher commits it.
    → True when it was rewritten."""
    store = store or store_dir()
    r = repo()
    m = load_map(store)
    if not r or not m["issues"] or m.get("repo") == r:
        return False
    was = m.get("repo") or ""
    m = dict(m); m["repo"] = r
    save_map(m, store)
    (say or (lambda s: print(f"ghsync: {s}", file=sys.stderr, flush=True)))(f"the map's repo note: {was or '(none)'} → {r}")
    return True


on_rekey: Callable[[str, str, dict[str, Any]], None] | None = None
"""The server's hook for a re-key (phase 2 prep): called by the worker as on_rekey(old id, new id, item) once a local item has
taken its issue number, so the server can tell the owner. A failure in it is logged and the job goes on."""


def _merge_group(p: Path, job: dict[str, Any], gid: str, store: Path, jobs: list[tuple[Path, dict[str, Any]]]) -> list[tuple[Path, dict[str, Any]]]:
    """The jobs that go out with `p` as one write: `p` and every later live "changed" job on the same item, in queue order; `jobs` is the queue as the drain
    read it. A background job, a create and a job of another item are not in it. One sync of the issue serves them all (the issue is brought up to the item as it is)."""
    out = [(p, job)]
    for q, j in jobs:
        if q.name <= p.name or q.name.startswith(BACKGROUND) or j.get("kind") != "changed" or not q.exists() or resolve(str(j.get("gid") or ""), store) != gid:
            continue
        out.append((q, j))
    return out


def _merge_due(group: list[tuple[Path, dict[str, Any]]], now: float, window: float) -> float:
    """0.0 when the group goes out now (a job in it is urgent: a close or reopen; or the window, counted from its oldest job, has run out; or the window is
    off), else the seconds until it does. The window is on the jobs' own clocks, kept on disk, so a restart changes nothing about it."""
    if window <= 0 or any(j.get("urgent") for _q, j in group):
        return 0.0
    try:
        start = min(float(j.get("ts") or now) for _q, j in group)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, start + window - now)


def _mark_tried(p: Path, job: dict[str, Any]) -> None:
    """The job on disk says a create is under way: a process that dies with the answer in flight looks for the marker first
    when it comes back (find_by_marker), so a lost answer never makes two issues."""
    try:
        job["tried"] = max(1, int(job.get("tried") or 0))
        write_atomic(p, _job_text(job))
    except (OSError, TypeError, ValueError):
        pass


def drain(gh: GitHub | None = None, store: Path | None = None, limit: int = 0, say: Callable[[str], None] | None = None, now: float | None = None) -> dict[str, Any]:
    """Work the queue in order: for each job, the item's issue (created when it has none; a job tried before first looks for
    its marker, so a lost answer never makes two), a local item re-keyed to its issue number (rekey), then the issue brought
    up to the item (sync_issue: one PATCH of title, body and state, none when the fingerprint says it is already so).
    Stops at the first sign GitHub is down (the job stays, marked tried) → {"done": n, "left": m, "down": "<why>" | ""}. A job
    GitHub refuses, or whose item is gone, moves to failed/ with the reason.

    The merge window ([github] merge_seconds, `now` = the clock the window is read against): the "changed" jobs of an item that already
    has an issue wait until the oldest of them is merge_seconds old, then go out together as one sync of the issue. A create, and a group with a
    close or a reopening in it, go at once. The window is read off the jobs' own timestamps on disk, so a restart in the middle loses nothing and a job
    already older than the window goes at the first drain. A job an older version queued carries a comment and its parts; they are ignored (no
    comment is posted any more).
    → with jobs waiting out their window it also says {"held": how many, "next_due": the seconds to the first window's end}."""
    say = say or (lambda s: print(f"ghsync: {s}", file=sys.stderr, flush=True))
    with uncapped():                                     # the reads a job makes (the marker) count, but the read cap never holds a write
        return _drain_jobs(gh or client(), store or store_dir(), limit, say, time.time() if now is None else now)


def _drain_jobs(gh: GitHub, store: Path, limit: int, say: Callable[[str], None], now: float) -> dict[str, Any]:
    done, down, limited, primary = 0, "", 0.0, False
    names: dict[str, str] | None = None
    synced = _synced()
    window = merge_seconds()
    held, next_due = 0, 0.0
    queue_now: list[tuple[Path, dict[str, Any]]] = []     # the live jobs as read at the start: the merge groups are made from it
    if window > 0:
        for q in pending():
            if q.name.startswith(BACKGROUND):
                continue
            try:
                queue_now.append((q, json.loads(q.read_text(encoding="utf-8"))))
            except (OSError, ValueError):
                continue
    _EVENT.clear()                                       # a live job enqueued from here on sets it again: a background run yields to it
    todo, seen = pending(), set()
    while todo:
        fresh = [q for q in pending() if q.name.startswith(FIRST) and q.name not in seen]      # a temporary item's create queued while this drain waits for room goes next, not after the rest of the list
        if fresh:
            todo = fresh + [q for q in todo if q not in fresh]
        p = todo.pop(0); seen.add(p.name)
        if limit and done >= limit:
            break
        if not p.exists():                               # folded into an earlier job's sync
            continue
        if p.name.startswith(BACKGROUND) and (_EVENT.is_set() or gh.recent_writes() >= gh.budget - min(LIVE_RESERVE, gh.budget // 4)):
            break                                        # a live write arrived during a background run (the next drain takes it first), or the
                                                         # hour's budget is down to the live writes' reserve (the worker's next tick tries again)
        try:
            job = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _fail(p, "unreadable job"); continue
        if job.get("kind") in OBSOLETE_KINDS:            # a typed-field or label job of an older version: those writes are gone, no call
            p.unlink(missing_ok=True); done += 1
            continue
        raw = str(job.get("gid") or "")
        gid = resolve(raw, store)
        item = _load_item(store, gid)
        if not gid or item is None:
            _fail(p, f"no item {gid or raw} in the store"); continue
        if names is None:
            names = _names()
        try:
            n = issue_of(gid, store)
            if not n and job.get("tried"):
                n = find_by_marker(gh, gid)
                if n:
                    record_issue(gid, n, store)
            was = next((k for k, v in load_map(store)["aliases"].items() if v == gid), "")
            if not n and job.get("kind") in RESYNC_KINDS:   # a body resync never creates an issue: the item's own create job does
                p.unlink(missing_ok=True); done += 1
                continue
            group: list[tuple[Path, dict[str, Any]]] | None = None
            if n and window > 0 and job.get("kind") == "changed" and not p.name.startswith(BACKGROUND):
                group = _merge_group(p, job, gid, store, queue_now)
                wait_s = _merge_due(group, now, window)
                if wait_s > 0:                           # the window is still open: the job stays on disk, for this drain and for a restart
                    held += 1
                    next_due = wait_s if not next_due else min(next_due, wait_s)
                    continue
            if not n:
                _mark_tried(p, job)
                r = gh.create_issue(title_of(item), body_of(gid, item, names, was))
                n = _issue_number(r)                     # no number in the answer: GitHubDown, the job stays (tried: the marker is looked for next time)
                record_issue(gid, n, store)
                synced[gid] = _fingerprint(title_of(item), body_of(gid, item, names, was), "open", "")
                _save_synced(synced)
                say(f"{gid} → {gh.repo}#{n} created")
            if is_local(raw):            # phase 2 prep: an item created while GitHub was down takes its issue number now (or a re-key a crash cut short is finished)
                fresh = gid == raw
                if fresh or _item_file(store, raw).exists():
                    gid = rekey(store, raw, n)
                    item = _load_item(store, gid) or item
                was = raw
                if synced.pop(raw, None) is not None:
                    _save_synced(synced)
                if fresh:
                    say(f"{raw} → {gid} ({gh.repo}#{n}); {raw} stays as an alias")
                    if on_rekey is not None:
                        try:
                            on_rekey(raw, gid, item)
                        except Exception as e:  # noqa: BLE001
                            say(f"{raw} → {gid}: the server's re-key hook failed ({e})")
            sync_issue(gh, store, gid, item, n, names, synced, was, say)
            taken = [q for q, _j in group] if group else [p]
            for q in taken:
                q.unlink(missing_ok=True)
            done += len(taken)
        except GitHubDown as e:
            down = str(e); limited = float(e.retry_after) if e.status in (403, 429) else 0.0; primary = bool(e.primary)
            try:
                job["tried"] = int(job.get("tried") or 0) + 1; job["error"] = down[:300]
                write_atomic(p, _job_text(job))
            except OSError:
                pass
            say(f"GitHub is not answering ({down[:120]}); {len(pending())} job(s) wait")
            break
        except GitHubError as e:
            _fail(p, str(e)); say(f"{gid}: GitHub refused the job ({e}); moved to failed/")
    return {"done": done, "left": len(pending()), "down": down, **({"held": held, "next_due": next_due} if held else {}), **({"retry_after": limited, "primary": primary} if down and limited else {})}


def _fail(p: Path, why: str) -> None:
    d = failed_dir(); d.mkdir(parents=True, exist_ok=True)
    try:
        job = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        job = {"raw": p.name}
    job["failed"] = why[:500]; job["failed_at"] = time.time()
    write_atomic(d / p.name, _job_text(job))
    p.unlink(missing_ok=True)


def worker_loop(stop: threading.Event | None = None) -> None:
    """The server's worker thread: drain whenever a job arrives or every 30 s; after a sign that GitHub is down, wait with
    backoff (30 s, doubling to 10 min, or what GitHub asked for) before the next try. Started only with the mirror on."""
    back = 30.0
    while not (stop and stop.is_set()):
        _EVENT.wait(timeout=30.0); _EVENT.clear()
        if not enabled() or not repo():
            continue
        try:
            note_repo()                                  # the org move: the map's repo note follows [github] issues_repo
        except Exception as e:  # noqa: BLE001
            print(f"ghsync: the map's repo note not written: {e}", file=sys.stderr, flush=True)
        if backfill_bodies():
            try:
                resync_bodies()                          # once per BODY_FORM, only when [github] backfill_bodies is on: background jobs, drained after the live ones
            except Exception as e:  # noqa: BLE001
                print(f"ghsync: body resync not queued: {e}", file=sys.stderr, flush=True)
        try:
            r = drain()
        except Exception as e:  # noqa: BLE001  — the worker never dies
            print(f"ghsync: drain failed: {e}", file=sys.stderr, flush=True); r = {"down": str(e)}
        waited = False
        if r.get("retry_after"):                          # a rate limit with GitHub's reset: wait for the bucket (probing it for free), then drain at once
            try:
                wait_rate_limit(client(), float(r["retry_after"]), stop, bool(r.get("primary"))); back = 30.0; _EVENT.set(); waited = True   # …and the next pass starts at once
            except Exception as e:  # noqa: BLE001  -- the worker never dies: the plain backoff below
                print(f"ghsync: waiting for the rate limit failed: {e}", file=sys.stderr, flush=True)
        if waited:
            pass
        elif r.get("down"):
            time.sleep(back); back = min(back * 2, 600.0)
        else:
            back = 30.0


# ----------------------------------------------------------------------------- the reader (phase 3): the owner's comments come in
on_comment: Callable[[str, dict[str, Any]], bool] | None = None
"""The server's hook for the owner's own comment on an item's issue (phase 3): on_comment(gid, comment), comment =
{"id": the comment's id, "text": its body, "url": its html_url, "ts": when it was written (epoch), "login": whose, "issue": n}.
→ True when the item took it (recorded, its sessions told), False when there is no such item (the comment is skipped for
good). An exception leaves the comment for the next read (the cursor stays before it)."""


def _comments_path() -> Path:
    return _cfg.state("github", COMMENTS_NAME)


def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _epoch(s: Any) -> float:
    """An ISO 8601 UTC stamp as GitHub writes it (2099-03-12T03:00:00Z) → epoch seconds; 0.0 for anything else."""
    try:
        return float(calendar.timegm(time.strptime(str(s or "")[:19], "%Y-%m-%dT%H:%M:%S")))
    except (TypeError, ValueError, OverflowError):
        return 0.0


def comments_state() -> dict[str, Any]:
    """The reader's state: {"since": the cursor the next read asks for (ISO 8601 UTC), "started": when the reader first ran
    (a comment created before it is history, never delivered, however late it is edited), "seen": [the ids of the owner's
    comments delivered or skipped, the newest SEEN_MAX], "login": whose comments read as the owner's}; {} before the first run
    (the next read starts at "now"). A "copied" key an older version wrote is left alone and unread."""
    try:
        d = json.loads(_comments_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) and d.get("since") else {}


def _save_comments_state(d: dict[str, Any]) -> None:
    p = _comments_path(); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp"); tmp.write_text(json.dumps(d, ensure_ascii=False) + "\n", encoding="utf-8"); os.replace(tmp, p)


def is_owner_comment(c: dict[str, Any], login: str) -> bool:
    """A comment the owner wrote by hand: by `login` (GitHub logins are case-insensitive) and with no `[author: …]` header,
    which the mirror's own comments carry although they are written with the same account."""
    u = c.get("user") if isinstance(c.get("user"), dict) else {}
    return bool(login) and str(u.get("login") or "").lower() == login.lower() and parse_header(str(c.get("body") or "")) is None


_ISSUE_URL = re.compile(r"/issues/(\d+)/?$")


def issue_number(c: dict[str, Any]) -> int:
    m = _ISSUE_URL.search(str(c.get("issue_url") or ""))
    return int(m.group(1)) if m else 0


def poll_comments(gh: GitHub | None = None, store: Path | None = None, say: Callable[[str], None] | None = None, now: float | None = None) -> dict[str, Any]:
    """One read of the repo's comments (phase 3): the ones updated since the cursor, of which the owner's own (is_owner_comment)
    on an issue that mirrors an item (item_of_issue), not delivered before (the seen ids) and written after the reader first ran,
    go to the server's hook (on_comment), in the order GitHub lists them. Then the cursor moves to a second before the newest
    update read (GitHub's `since` is at second granularity; a comment read twice is in seen) and never past a comment the hook
    could not take. With the mirror off nothing is read → {"off": True, …}. GitHubDown propagates (the loop backs off).
    → {"new": delivered, "skipped": the owner's comments passed by, "failed": left for the next read, "down": ""}."""
    say = say or (lambda s: print(f"ghsync: {s}", file=sys.stderr, flush=True))
    out: dict[str, Any] = {"new": 0, "skipped": 0, "failed": 0, "down": ""}
    if not enabled() or not repo():
        return {**out, "off": True}
    store = store or store_dir(); gh = gh or client()
    t0 = time.time() if now is None else now
    st = comments_state()
    if not st:
        st = {"since": _iso(t0), "started": _iso(t0), "seen": []}
        _save_comments_state(st)
        say(f"comments: reading from {st['since']} on; what came before is history, never delivered")
    login = owner_login() or gh.login()
    if not login:
        say("comments: whose comments to read is unknown ([github] owner_login is unset and GitHub refused GET /user); nothing read")
        return out
    if on_comment is None:                           # a process with no server in it (a CLI): the comments are the server's to take
        say("comments: no hook to take them (not the server); nothing read")
        return out
    dirty = False
    if st.get("login") != login:                     # whose comments read as the owner's (the reader's login, not a header)
        st["login"] = login; dirty = True
    rows = gh.list_comments_since(str(st["since"]))
    seen = {int(x) for x in (st.get("seen") or []) if str(x).isdigit()}
    seen0 = set(seen)
    started = _epoch(st.get("started")) or _epoch(st["since"])
    old_since = _epoch(st["since"]); latest = old_since; failed: list[float] = []
    for c in rows:
        try:
            cid = int(c.get("id") or 0)
        except (TypeError, ValueError):
            cid = 0
        up = _epoch(c.get("updated_at")); latest = max(latest, up)
        if not cid or cid in seen or not is_owner_comment(c, login) or _epoch(c.get("created_at")) < started:
            continue                                 # the mirror's own, another user's, a delivered one edited, or history edited late
        n = issue_number(c); gid = item_of_issue(n, store) if n else ""
        if not gid:
            seen.add(cid); out["skipped"] += 1
            say(f"comments: {login}'s comment {cid} on #{n or '?'} skipped: no item mirrors that issue"); continue
        comment = {"id": cid, "text": str(c.get("body") or "").strip(), "url": str(c.get("html_url") or ""),
                   "ts": _epoch(c.get("created_at")) or t0, "login": login, "issue": n}
        try:
            took = bool(on_comment(gid, comment)) if on_comment is not None else False
        except Exception as e:  # noqa: BLE001  — the next read tries it again
            failed.append(up); say(f"comments: {gid} did not take {login}'s comment {cid} ({type(e).__name__}: {e}); again at the next read"); continue
        seen.add(cid)
        if took:
            out["new"] += 1; say(f"comments: {gid} ← {login}'s comment {cid} on #{n}")
        else:
            out["skipped"] += 1
    out["failed"] = len(failed)
    since = max(old_since, (min(failed) if failed else latest) - 1)
    kept = sorted(seen)[-SEEN_MAX:]
    if dirty or since != old_since or set(kept) != seen0:
        _save_comments_state({**st, "since": _iso(since), "started": st.get("started") or st["since"], "seen": kept})
    return out


def comments_loop(stop: threading.Event | None = None) -> None:
    """The reader's thread (phase 3), started with the server beside the worker's: one read right away, then one every [github]
    poll_seconds; while the mirror is off it only waits (a reload can turn it on). After a sign that GitHub is down it waits
    what GitHub asked for (retry-after, the rate limit's reset) or a backoff doubling to 10 min, whichever is longer. Never dies."""
    back = 0.0
    while not (stop and stop.is_set()):
        wait = poll_seconds()
        if enabled() and repo():
            try:
                poll_comments(); back = 0.0
            except GitHubDown as e:
                if e.status in (403, 429) and e.retry_after:
                    print(f"ghsync: comments: GitHub's rate limit holds ({str(e)[:120]}); waiting for it (resets in {e.retry_after:.0f} s)", file=sys.stderr, flush=True)
                    try:
                        wait_rate_limit(client(), e.retry_after, stop, e.primary); back = 0.0; continue
                    except Exception as e2:  # noqa: BLE001  -- the reader never dies: the plain backoff below
                        print(f"ghsync: comments: waiting for the rate limit failed: {e2}", file=sys.stderr, flush=True)
                back = min(max(back * 2, wait), 600.0)
                wait = max(wait, back, e.retry_after)
                print(f"ghsync: comments: " + (str(e)[:160] if isinstance(e, GitHubBudget) else f"GitHub is not answering ({str(e)[:120]})") + f"; next read in {wait:.0f} s", file=sys.stderr, flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"ghsync: comments: read failed: {e}", file=sys.stderr, flush=True)
        (stop or _NEVER).wait(wait)


# ----------------------------------------------------------------------------- the id switch: a new item's id is its issue number
CREATE_WAIT = 5.0               # seconds a create answering a person waits for its issue's place under the pace and the hour's budget; past it the item takes a temporary id


def allocate(item: dict[str, Any], names: dict[str, str] | None = None, store: Path | None = None, gh: GitHub | None = None, max_wait: float | None = None) -> int:
    """Create the issue a new item is numbered after (the body without a marker: the id is not known until the number is),
    record it in the map and → the number. Raises GitHubDown / GitHubError: the caller refuses the create, with why. `max_wait`: the most seconds the
    write may wait for its place under the pace and the hour's budget (CREATE_WAIT for a create a person waits on); over it GitHubBudget, a GitHubDown,
    is raised and no issue is made."""
    gh = gh or client()
    r = gh.create_issue(title_of(item), body_of("", item, names), max_wait=max_wait)
    n = _issue_number(r)                                 # no number in the answer: GitHubDown, the caller falls back to a temporary id and queues the create
    record_issue(f"{letter()}{n}", n, store)
    return n


# ----------------------------------------------------------------------------- the migration (phase 2 runs it once; ghmigrate.py)
def _gid_key(gid: str) -> tuple[str, int]:
    return gid[0], int(gid[1:])


def open_items(store: Path) -> list[tuple[str, Path, dict[str, Any]]]:
    """The open items of the store (on hold included) in id order, the issue letter's own left out."""
    out = []
    for d in sorted(store.iterdir()):
        if not (d.is_dir() and len(d.name) == 1 and d.name.isalpha()) or d.name == letter():
            continue
        for p in d.glob("*.json"):
            if p.name.startswith(".") or not p.stem.isdigit():
                continue
            try:
                it = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(it, dict) and it.get("status") in ("open", "on_hold"):
                out.append((f"{d.name}{p.stem}", p, it))
    return sorted(out, key=lambda t: _gid_key(t[0]))


def migrate(store: Path, gh: GitHub, dry_run: bool = False, limit: int = 0, say: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Move the open items onto GitHub: in id order each becomes the repo's next issue (title, body with the marker of its
    old id), the file moves to <letter>/<n>.json with the new id, the old id goes into the map as an alias, and the `after`
    lists of the other open items follow. Idempotent: an item the map or an issue's marker already names is skipped (its
    file moved if a run stopped between the two). No history comment is posted (the History is the store's git).
    dry_run: the plan only (reads, no writes, no moves). → counts, and the plan as lines."""
    say = say or (lambda s: print(s, flush=True))
    m = load_map(store)
    known: dict[str, int] = {}
    for old, new in m["aliases"].items():
        if new in m["issues"]:
            known[old] = int(m["issues"][new])
    issues = gh.list_issues()
    for i in issues:                                 # the repo's own word: a map lost or behind still makes no second issue
        mk = MARK_RX.search(str(i.get("body") or ""))
        if mk:
            for g in (mk.group(1), mk.group(2)):
                if g and g not in known:
                    known[g] = int(i["number"])
    L = letter()
    if not dry_run:
        reconcile(store, issues, L)
    items = open_items(store)
    out: dict[str, Any] = {"items": len(items), "created": 0, "skipped": 0, "moved": 0, "plan": []}
    names = _names()
    for old, p, it in items:
        if limit and out["created"] >= limit:
            break
        n = known.get(old)
        if n:
            new = f"{L}{n}"
            out["skipped"] += 1
            out["plan"].append(f"{old} = #{n} (already)")
            if dry_run:
                continue
            if resolve(old, store) == old and p.exists():        # the issue exists but the file never moved (a run that stopped)
                _move(store, old, new, n, p, it); out["moved"] += 1
            continue
        out["plan"].append(f"{old} → the next issue")
        if dry_run:
            say(f"{old}: would become the next issue, its file moved"); continue
        r = gh.create_issue(title_of(it), body_of(old, it, names))
        n = _issue_number(r); new = f"{L}{n}"
        known[old] = n
        out["created"] += 1
        say(f"{old} → {gh.repo}#{n}")
        _move(store, old, new, n, p, it); out["moved"] += 1
    return out


def reconcile(store: Path, issues: list[dict[str, Any]], L: str = "") -> int:
    """The map brought up to the repo: every issue whose marker names an item the store holds (under the issue letter, or
    not moved yet) is recorded, with the old id as the alias the marker says. → how many entries were written. A map lost
    or behind is rebuilt this way from the repo alone."""
    L = L or letter(); n_written = 0
    for i in issues:
        mk = MARK_RX.search(str(i.get("body") or ""))
        if not mk:
            continue
        try:
            n = int(i["number"])
        except (KeyError, TypeError, ValueError):
            continue
        g1, was = mk.group(1), mk.group(2) or ""
        new = f"{L}{n}"
        m = load_map(store)
        if _item_file(store, new).exists():
            old = was or (g1 if g1 != new else "")
            if int(m["issues"].get(new) or 0) != n or (old and m["aliases"].get(old) != new):
                record_issue(new, n, store, was=old); n_written += 1
        elif _item_file(store, g1).exists() and int(m["issues"].get(g1) or 0) != n:
            record_issue(g1, n, store); n_written += 1
    return n_written


def rekey(store: Path, old: str, n: int) -> str:
    """Phase 2 prep: the item created while GitHub was down (`old`, a local id) takes issue n's id: the same move as the
    migration's (_move: file, map, aliases, `after` lists and anchors), so `old` resolves to it and /items/<old> redirects
    exactly as a migrated id does. Idempotent: a re-key a crash cut short is finished by the next call. → the new id."""
    new = f"{letter()}{n}"
    _move(store, old, new, n, _item_file(store, old), {})
    return new


def _updated(it: dict[str, Any] | None) -> float:
    try:
        return float((it or {}).get("updated") or 0)
    except (TypeError, ValueError):
        return 0.0


def _write_item(q: Path, it: dict[str, Any]) -> None:
    q.parent.mkdir(parents=True, exist_ok=True)
    tmp = q.with_name(f".{q.name}.tmp")
    tmp.write_text(json.dumps(it, ensure_ascii=False, indent=1), encoding="utf-8"); os.replace(tmp, q)


def _move(store: Path, old: str, new: str, n: int, p: Path, it: dict[str, Any]) -> None:
    """The item from id `old` (file p) to id `new` (issue n): the file under the new id, the map (new mirrors n, old its
    alias), the old file gone, then the `after` lists and anchor scopes that named it. In that order, so that a crash at
    any point leaves a state the next call completes: before the map is saved the old file is still the item (a write
    lands there and the copy is taken again); once saved, every id lookup resolves to the new file, and the old one, if
    still there, is only removed. When both files exist the newer one by `updated` wins, so a write that reached the old
    file while the move was under way (the one race the worker cannot lock out of the server's threads) is kept, and a
    stale old copy never overwrites the new file. The publisher's next commit records the rename."""
    q = _item_file(store, new)
    def read(f: Path) -> dict[str, Any] | None:
        try:
            x = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return x if isinstance(x, dict) else None
    def take(cur: dict[str, Any]) -> None:
        cur = dict(cur); cur["id"] = str(n); _write_item(q, cur)
    cur = read(p) if p.exists() else (dict(it) if it else None)   # as it is now: an earlier move may have rewritten its after list
    have = read(q) if q.exists() else None
    if cur is not None and (have is None or _updated(cur) > _updated(have)):
        take(cur)
    elif have is None:
        raise GitHubError(0, f"{old}: nothing to move (no file under {old} or {new})")
    record_issue(new, n, store, was=old)
    for _ in range(3):                      # the old file: removed, after a last look (a write that reached it while the move ran is taken first)
        late = read(p) if p.exists() else None
        if late is not None and _updated(late) > _updated(read(q)):
            take(late)
        p.unlink(missing_ok=True)
        if not p.exists():
            break
    for d in store.iterdir():
        if not (d.is_dir() and len(d.name) == 1 and d.name.isalpha()):
            continue
        for f in d.glob("*.json"):
            if f.name.startswith("."):
                continue
            x = read(f)
            meta = x.get("metadata") if x else None
            if not isinstance(meta, dict) or x.get("status") == "completed" or not isinstance(meta.get("after"), list) or old not in meta["after"]:
                continue
            meta["after"] = [new if g == old else g for g in meta["after"]]
            _write_item(f, x)
    _move_anchors(store, old, new)


def _move_anchors(store: Path, old: str, new: str) -> int:
    """An anchor scoped to the item (<store>/anchors.json, items: [ids]) follows its id. → entries rewritten."""
    f = store / "anchors.json"
    if not f.exists():
        return 0
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if not isinstance(d, dict):
        return 0
    k = 0
    for entries in d.values():
        for e in entries if isinstance(entries, list) else []:
            if isinstance(e, dict) and isinstance(e.get("items"), list) and old in e["items"]:
                e["items"] = sorted({new if g == old else g for g in e["items"]}); k += 1
    if k:
        tmp = f.with_name(f".{f.name}.tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8"); os.replace(tmp, f)
    return k
