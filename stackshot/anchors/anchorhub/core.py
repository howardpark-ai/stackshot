"""anchorhub.core — the hub every receiver reports to (split out of anchor-hub.py in an earlier change).

A receiver is a module with run(hub): it watches one kind of source and reports each change with hub.event(anchor, summary, kind),
which the hub turns into one Event — the single shape a change has from here on, whatever its source — and routes to the sessions
bound to that anchor. The rest of a receiver's contract is what it registers on the hub:
  hub.resolvers[kind]   fn(anchor id) → {title, url, seen}     how the board names an anchor and when it last changed;
                        {…, unreadable: why} when the source itself says the hub may not read it (a refusal, never a network error)
  hub.savers[name]      fn() → its read position                saved each minute and at stop, restored from hub.saved[name]
  hub.catchups[name]    fn(since epoch) → notices caught up     a reboot's resume
  hub.hooks[route]      fn(headers, body) → (status, text)      a vendor's webhook, which usually puts (kind, key) on hub.triggers
  hub.health(name, ok, err)                                     the result of a real check, shown on the board
An anchor in [anchor_hub] direct (anchor id → one session; read at each event, so a config reload applies it) skips all of
the routing below: each event goes at once, whole, to that session alone (the direct lane). The value "none" makes the
anchor log only: each event is written to the routing log and delivered to nobody.
A summary may carry `etype`, the event's type at its source (GH_TYPES for GitHub): a routine event on the fleet's own pull
request ([pilot] own_repos; routine_own) is logged for a pilot project, ruled by stackshot (auto), not delivered.
Delivery goes through push.py (inbox socket; queued when the session is not live or the hub is paused for a reboot)."""
import json, os, sys, glob, time, math, random, threading, subprocess, logging, queue, tempfile
import urllib.error
from dataclasses import dataclass, field, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime

from stackshot import paths as _paths
STACKSHOT = str(_paths.ROOT)
from stackshot.core import readonly as _ro   # STACKSHOT_READ_ONLY: the hub does nothing on a standby copy; anchor-hub.py never gets here then, these guards are the backstop
from stackshot.core import config as _cfg   # stackshot.toml: the paths and identities of this instance
from stackshot.core import interp as _interp   # a missing interpreter (its uv environment deleted) never stops a delivery
from stackshot.anchors import anchors as _anc  # the project-anchors store + bindings (shared with the stackshot server)
from stackshot.anchors import merge_log as _merges  # the pull requests seen merging, for the server's progress clock (one line each, no read of its own)
from stackshot.anchors import event_log as _events  # the other activity seen on pull requests (CI results, comments by people, reviews, merges), for the server's last-activity record
from stackshot.router import routing as _routing  # the routing log: every delivered notice, and the ruling on it (the pilot)
try: from stackshot.router import router_live as _live          # the router's live mode: holds a pilot notice for the router instead of delivering it to the keeper
except Exception: _live = None            # anchor-hub never fails to start for it: no router, the notice is delivered as ever
try: from stackshot.router import router as _router_rules       # the router's own test of a text that names the owner (send_burst)
except Exception: _router_rules = None
MIRROR = str(_cfg.path("paths", "store"))
PUSH = [sys.executable, _paths.program("fleet", "push")]   # the delivery script (push.py)
ADIR = str(_cfg.state("anchor-hub"))            # status, cursors, queues, ctl, pause flags — the hub's own state
EXTRA = f"{ADIR}/extra.json"
STATUS = f"{ADIR}/status.json"
CURSORS = f"{ADIR}/cursors.json"   # every receiver's read position, saved each minute and at stop, restored at start
CTL = f"{ADIR}/ctl"                # requests from anchor-hub-hook (catch-up, persist) — <id>.req.json → <id>.res.json
PAUSED = f"{ADIR}/paused-hub.json" # present = push.py queues this hub's notices instead of delivering them
UNBOUND = f"{ADIR}/unbound.log"
ENVF = str(_cfg.secrets("anchor-hub", "env"))
ZONE = _cfg.tz()
DEBOUNCE = 60          # s: collapse events on one (anchor, session) into one notice
DIRECT_CLIP = 4000     # chars: a direct notice carries the whole text up to this (a one-line notice clips at 140 or 300)
LOG_ONLY = "none"      # [anchor_hub] direct value: the anchor's events are logged, never delivered
LOG_ONLY_REASON = "direct: log only"
def log_only(session: str) -> bool:
    """A direct entry whose value is "none" (any case): log only. Never a session name, never canonicalised or looked up."""
    return str(session).strip().lower() == LOG_ONLY
def direct() -> dict[str, str]:
    """[anchor_hub] direct: anchor id → the one session its events go to, at once and whole, past the bindings, the keeper,
    the mention filters and the debounce (for a single-session chat channel).
    The value "none" (LOG_ONLY) makes the anchor log only (emit_direct): kept here as any non-empty value is, never resolved.
    Read at each event, as slack.self_channels() reads its key, so a config reload (SIGHUP) applies it without a restart."""
    v = _cfg.get("anchor_hub", "direct") or {}
    if not isinstance(v, dict): return {}
    return {(_anc.anchor_id(str(k).strip()) or str(k).strip()): str(x).strip() for k, x in v.items() if str(k).strip() and str(x).strip()}   # a GitHub key by its current name ([github.moved]), as the events are keyed
# The fleet's own PR events (the turn rule's third build): on a repository listed
# in [pilot] own_repos (by owner/repo, owner/*, or the repository's numeric ID, Event.repo_id), a pull request opened, merged, closed or given new commits, and CI passing again, is routine. For a
# project in the pilot it is logged and not delivered: a routing-log line with no recipient, marked log_only and ruled
# `merged` by stackshot (auto) at once, which stays on the project's routing page and which still
# releases an item held on the anchor (the server's _anchor_pass). Decided by the event's type at its source (Event.etype),
# never by its text, since the owner and the sessions share one GitHub account. A comment, a review, a review comment, failing
# CI, a reopen, an unclassified event, an event on any other repository, a route outside the pilot and a session bound by
# extra.json are delivered as before.
GH_TYPES = ("pr_opened", "pr_reopened", "pr_synchronize", "pr_merged", "pr_closed", "issue_reopened", "issue_closed",
            "ci_passed", "ci_failed", "ci_activity", "comment", "review", "review_comment")
ROUTINE = frozenset({"pr_opened", "pr_synchronize", "pr_merged", "pr_closed", "ci_passed"})
def own_repos() -> list[str]:
    """[pilot] own_repos: the fleet's own GitHub repositories, each entry "owner/repo", "owner/*" (every repository of that owner) or a numeric
    repository ID (an int or a digit string; the form that survives a transfer to another owner, since GitHub keeps the ID); names lower-cased,
    an ID kept as digits. A list, or one comma- or whitespace-separated string. Empty (the default) = none, and every event is delivered as
    before. Read at each event, so a config reload (SIGHUP) applies it without a restart."""
    v = _cfg.get("pilot", "own_repos") or []
    if isinstance(v, str): v = v.replace(",", " ").split()
    return [str(x).strip().lower() for x in v if not isinstance(x, bool) and str(x).strip()] if isinstance(v, (list, tuple, str)) else []
def repo_of(anchor: str) -> str:
    """github:<owner/repo>#<n> · github:<owner/repo>@notifications · github:<owner/repo>@releases → "owner/repo", lower-cased; "" for
    any other anchor."""
    a = str(anchor or "")
    if not a.startswith("github:"): return ""
    return _cfg.canon_repo(a[7:].split("#", 1)[0].split("@", 1)[0])    # through [github.moved]: an old and a new name of one repository are one
def is_own(repo: str, own: list[str] | None = None, repo_id: object = None) -> bool:
    """Is the repository one of [pilot] own_repos? An ID entry matches repo_id (the event's repository.id, Event.repo_id), whatever the owner's
    name now is; an "owner/repo" or "owner/*" entry matches the name. An event without an ID (repo_id empty) matches by name only."""
    repo = _cfg.canon_repo(repo)       # [github.moved]: both sides below go through the table, so an old-name entry matches a new-name repository and back
    own = own_repos() if own is None else own
    rid = str(repo_id).strip() if repo_id not in (None, "", 0, False) else ""
    if rid and rid in own: return True
    if "/" not in repo: return False
    names = _cfg.repo_aliases(repo)
    return any(_cfg.canon_repo(o) == repo or (o.endswith("/*") and any(n.split("/", 1)[0] == o[:-2] for n in names)) for o in own)
def _repo_id(v: object) -> int:
    """A repository ID from a payload: a positive int or digit string, else 0 (none)."""
    if isinstance(v, bool): return 0
    try: n = int(v)    # type: ignore[arg-type]
    except (TypeError, ValueError): return 0
    return n if n > 0 else 0
def routine_own(ev: "Event") -> str:
    """A routine event on the fleet's own pull request → the reason its log line gives; "" = deliver it as before. Every type
    the event reports must be routine (a merge with a comment beside it is delivered), its repository must be in
    [pilot] own_repos (by the event's repository ID when it carries one and the list has that ID, else by name)."""
    types = [t for t in str(ev.etype or "").split("+") if t]
    if not types or any(t not in ROUTINE for t in types): return ""
    repo = repo_of(ev.anchor)
    if not repo or not is_own(repo, repo_id=ev.repo_id): return ""
    return f"log-only: {', '.join(types)} on {repo}, the fleet's own repository ([pilot] own_repos); kept on the routing page"
def _quiet() -> dict[str, int]: return {str(k): int(v) for k, v in (_cfg.get("anchor_hub", "quiet") or {}).items()}   # QUIET: kind → seconds of silence before the follow-up goes out
def _quiet_max() -> int: return int(_cfg.get("anchor_hub", "quiet_max_hold") or 10800)                      # QUIET_MAX, s: a burst that never goes quiet still reports this often
RESCAN = 60            # s: fallback bindings rescan + queue flush cadence (inotify is the primary trigger)
RETRY = (60, 21600)    # s: an anchor the hub cannot read is asked for again after 60 s, then at doubling intervals up to 6 h
HEALTH = 1800          # s; cursor health poll for every push-covered source (catches a dead channel, replays misses)
HOOK_URL = str(_cfg.get("anchor_hub", "hook_url") or "")
HOOK_PORT = int(_cfg.get("anchor_hub", "hook_port") or 8010)
WATCHES = f"{ADIR}/watches.json"
log = logging.getLogger("anchor-hub")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def write_atomic(path: str, text: str):
    """Replace `path` with `text` so that a reader sees the old file or the new one, whole, and two writers never share a temp file:
    the text goes to a temp file of its own name in the same folder (so os.replace stays on one filesystem), is flushed to disk, then
    renamed over the target. A failure removes the temp file and leaves the old file as it was. (A fixed `<path>.tmp` shared by the
    threads of the hub let one thread's rename take the file another was about to rename: FileNotFoundError, in the GitHub poll thread.)"""
    folder = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text); f.flush(); os.fsync(f.fileno())
        try: mode = os.stat(path).st_mode & 0o777           # mkstemp makes the file private (0600): keep the mode the file had, 0644 for a first write
        except OSError: mode = 0o644
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise

def guarded_loop(hub: "Hub", name: str, step, every=None, retry: float = 1.0, sleep=None, pause_first: bool = False):
    """The loop of a receiver's thread: step() once per pass until hub.stopping is set. An exception inside a pass is logged (the receiver's
    name, the exception and the line it came from, then the full traceback) and the loop goes on after `retry` seconds; one failed pass never
    ends a receiver. Only the stop signal ends the loop. `every()` → seconds to wait after a pass that went well (None: the pass waits by
    itself, as a receiver that blocks on its trigger queue does). `sleep(seconds)` defaults to hub.stopping.wait, which a stop cuts short.
    pause_first waits before the first pass, as a watcher that checks once a minute does."""
    sleep = sleep or hub.stopping.wait
    if pause_first and not hub.stopping.is_set() and every: sleep(every())
    while not hub.stopping.is_set():
        try:
            step(); pause = every() if every else 0
        except Exception as e:
            tb = e.__traceback__
            while tb is not None and tb.tb_next is not None: tb = tb.tb_next
            where = f"{os.path.basename(tb.tb_frame.f_code.co_filename)}:{tb.tb_lineno}" if tb is not None else "?"
            log.error("receiver %s: a pass of its loop failed (%s: %s at %s); going on in %s s", name, type(e).__name__, str(e)[:160], where, retry, exc_info=True)
            pause = retry
        if pause: sleep(pause)


def now_iso(): return datetime.now(ZONE).strftime("%Y-%m-%d %H:%M:%S")
def now_iso_at(ts: float) -> str: return datetime.fromtimestamp(ts, ZONE).strftime("%Y-%m-%d %H:%M:%S")
def _ts(iso: str | None) -> float:
    try: return datetime.fromisoformat((iso or "").replace("Z", "+00:00")).timestamp()
    except Exception: return 0.0

def read_env() -> dict:
    """The hub's secrets file as a dict (KEY=value lines); empty when the file is missing."""
    if not os.path.exists(ENVF): return {}
    return dict(l.split("=", 1) for l in open(ENVF).read().splitlines() if "=" in l and not l.startswith("#"))

def watches_load():
    try: return json.load(open(WATCHES))
    except Exception: return {}
def watches_save(w): json.dump(w, open(WATCHES, "w"), indent=1)


@dataclass
class Event:
    """One change on one anchor: what every receiver hands the hub, whatever its source."""
    anchor: str            # anchors.anchor_id form — slack:<channel> · notion:<page or database> · drive:<file or folder> · gmail:<thread> | gmail:q:<terms> · github:<repo>#<n> | <repo>@releases | <repo>@notifications
    kind: str              # slack · slack-edit · gmail · drive · notion · notion-edit · github · github-state · github-release
    title: str             # the anchor's own name at its source, without its type: "#team-news" · "DM <person>" · "\"<page, file or subject>\"" · "<repo>#<n> \"<issue>\""
    who: str               # who did it: a person, a login, "CI"
    text: str              # what happened, one line
    url: str               # where to read it
    ts: object = None      # the source's own timestamp
    body: str = ""         # further text a #mention filter may match (a release's notes)
    full: str = ""         # the whole text, newlines kept (Slack): what a direct notice carries; empty → the one-line notice
    meta: dict = field(default_factory=dict)   # the source's own ids: Slack {ts, thread_ts (a thread reply only), caught_up}
    etype: str = ""        # what happened, by type at the source, for a decision by type (never by the text): GitHub sets one of
                           # GH_TYPES, several joined with "+" when one notice reports several (a merge and a comment); "" = unclassified
    repo_id: int = 0       # GitHub only: the repository's numeric ID (repository.id), which a transfer to another owner does not change; 0 = the
                           # source's payload did not carry it, and [pilot] own_repos then matches by owner/name only
    head: str = ""         # GitHub pull request only: its head branch (head.ref), "" when unknown; the router passes a notice on a builder's PR to the builder
    author: str = ""       # GitHub pull request only: its author's login, "" when unknown

    @property
    def type(self) -> str:
        """What kind of anchor it is, from its id: Slack · Notion · Gmail · Drive · GitHub."""
        return _anc.kind_of(self.anchor)

    @property
    def label(self) -> str:
        """How a notice names the anchor: type and title together ("Slack #team-news"). Composed here and nowhere else."""
        return f"{self.type} {self.title}"

_LEAD = {"slack": "new message from ", "slack-edit": "EDITED message from ", "gmail": "new mail from ", "drive": "", "notion": "comment by ",
         "notion-edit": "", "github": "comment by ", "github-state": "", "github-release": ""}
_PLAIN = ("drive", "notion-edit", "github-state", "github-release")     # "<who> <did what>", not "<who>: \"<text>\""
def notice(ev: Event) -> str:
    """The one-line notice a session receives for an event."""
    body = f" {ev.text}" if ev.kind in _PLAIN else f": \"{ev.text}\""
    return f"[anchor] {ev.label}: {_LEAD[ev.kind]}{ev.who}{body} → {ev.url}"
def follow_up(p: dict) -> str:
    """The collapsed notice for the events that followed the first one: within DEBOUNCE s for most kinds; for a kind with a quiet
    window (QUIET, e.g. Drive) once the anchor has been quiet that long, naming the span the changes covered."""
    ev = p["last"]; since = datetime.fromtimestamp(p["first"], ZONE).strftime("%H:%M")
    if _quiet().get(p.get("kind") or ""):
        until = datetime.fromtimestamp(p["last_at"], ZONE).strftime("%H:%M")
        return f"[anchor] {p['label']}: {p['count']} more between {since} and {until} {_cfg.tz_abbr()}, last from {ev.who}: \"{ev.text}\" → {ev.url}"
    return f"[anchor] {p['label']}: {p['count']} more since {since} {_cfg.tz_abbr()}, last from {ev.who}: \"{ev.text}\" → {ev.url}"
def direct_notice(ev: Event) -> str:
    """The notice of a direct anchor: the usual header with the source's ids, then the whole text on the lines below,
    clipped at DIRECT_CLIP chars with the one-line notices' marker. An event with no full text or ids (a receiver that
    sets neither) gets the one-line notice."""
    m = ev.meta or {}
    if not ev.full and not m: return notice(ev)
    ids = " · ".join(f"{k} {m[k]}" for k in ("ts", "thread_ts") if m.get(k))
    head = f"[anchor] {ev.label}: {_LEAD[ev.kind]}{ev.who}" + (" (caught up)" if m.get("caught_up") else "") + (f" ({ids})" if ids else "") + f" → {ev.url}"
    t = ev.full or ""
    if len(t) > DIRECT_CLIP:
        t = t[:DIRECT_CLIP] + f" [… truncated, {len(t):,} chars" + (f" — fetch message ts {m['ts']}]" if m.get("ts") else "]")
    return head + ("\n" + t if t else "")


_FILTERS: dict[tuple[str, str], str] = {}   # (anchor, session) → text that must appear in the event (URL fragment #mention=…)
_ROUTES: dict[str, list[dict]] = {}         # anchor → [{project, session, target, pilot, filter}] (anchors.routes): which project a delivery is for
def load_bindings() -> dict[str, set[str]]:
    """anchor id → sessions. Anchors belong to projects (board-data/anchors.json); the sessions are
    derived: the project's keeper (its page's session) + the movers of the open items in the anchor's scope — or, for a
    project in the pilot, the keeper alone (anchors.routes)."""
    rs = _anc.routes()
    _ROUTES.clear(); _ROUTES.update(rs)
    b: dict[str, set[str]] = {}; _FILTERS.clear()
    for a, lst in rs.items():
        for r in lst:
            b.setdefault(a, set()).add(r["session"])
            if r["filter"]: _FILTERS[(a, r["session"])] = r["filter"]
    if os.path.exists(EXTRA):
        try:
            for url, sessions in json.load(open(EXTRA)).items():
                a = _anc.anchor_id(url)
                if a: b.setdefault(a, set()).update(_anc.canonical(x) for x in sessions)   # one identity per pane
        except Exception as e: log.warning("extra.json unreadable: %s", e)
    return b

# ---------- state ----------
def _jsonable(x):
    """Sets and tuples → lists, recursively (cursor persistence)."""
    if isinstance(x, dict): return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (set, frozenset)): return sorted(_jsonable(v) for v in x)
    if isinstance(x, (list, tuple)): return [_jsonable(v) for v in x]
    return x


class Hub:
    def __init__(self):
        self.bindings: dict[str, set[str]] = {}
        self.pending: dict[tuple[str, str], dict] = {}   # (anchor, session) → {first, count, label, last: the newest Event}
        self.lock = threading.Lock()
        self.stopping = threading.Event()      # set when a clean stop begins: the receivers' loops end then, and not before
        self._status_io = threading.Lock()     # one status.json write at a time (its text is made and replaced inside it, so the newest text is the file's)
        self.savers: dict[str, object] = {}    # receiver → fn() returning its read position
        self.catchups: dict[str, object] = {}  # receiver → fn(since_epoch) returning the number of notices it caught up
        self.inflight = 0                      # deliveries running right now (a clean stop waits for them)
        try: self.saved = json.load(open(CURSORS))
        except Exception: self.saved = {}
        self.resolvers: dict[str, object] = {}   # kind → fn(anchor_id) → {"label": …, "url": …}
        self.triggers: "queue.Queue[tuple[str, str]]" = queue.Queue()   # (kind, key) → "go look now"
        self.hooks: dict[str, object] = {}       # route → handler(headers, body) → (status, text)
        self.retrying: dict[str, dict] = {}      # route → {receiver, next, refused}: the owner's start is being retried, so the route answers 503, not 404
        self.push = {}                            # per-source push state (channels, expiries, misses) → status.json
        self.status = {"started": now_iso(), "bindings": 0, "slack": {"connected": False},
                       "anchors": {}, "last_notice": None, "notices": 0}
        # Last-change times survive a restart (the board shows a quiet anchor as "quiet <age>", which needs
        # to know since when). history_since = when this unbroken record began; the first run that kept it carried its own start.
        try: prev = json.load(open(STATUS))
        except Exception: prev = {}
        self.status["history_since"] = prev.get("history_since") or prev.get("started") or self.status["started"]
        # …and so does an anchor the hub cannot read, whole: its warning went out once and its next try has a time
        self.status["anchors"] = {k: (dict(v) if v.get("unreadable") else {"last": v["last"]})
                                  for k, v in (prev.get("anchors") or {}).items() if v.get("last") or v.get("unreadable")}
        os.makedirs(f"{ADIR}/queue", exist_ok=True)

    def rescan(self):
        b = load_bindings()
        now = time.time()
        with self.lock:
            if b.keys() != self.bindings.keys(): log.info("bindings: %d anchors %s", len(b), sorted(b))
            self.bindings = b
            self.status["bindings"] = len(b)
            for k in [k for k in self.status["anchors"] if k not in b]: del self.status["anchors"][k]   # the record is for watched anchors only
            def due(a):         # never named yet (or named before type and title were kept apart) · unreadable and its next try has come
                st = self.status["anchors"].get(a, {}); u = st.get("unreadable")
                return now >= float(u.get("next") or 0) if u else not st.get("title")
            todo = [a for a in b if due(a)]
        warn, clear = [], []
        for a in todo:
            kind = a.split(":", 1)[0]; fn = self.resolvers.get(kind)
            info = {"url": ""}
            if fn:
                try: info = fn(a)
                except Exception as e: log.warning("resolve %s: %s", a, str(e)[:120])
            why = info.pop("unreadable", None)
            title = str(info.get("title") or "")
            info.update({"type": _anc.kind_of(a), "title": title, "label": f"{_anc.kind_of(a)} {title}" if title else a})   # unresolved: its id, tried again next time
            # A resolver also reports "seen": the source's own last activity by someone other than the owner (the instance timezone, the live
            # notices' self-suppression rule) — or, when nobody else has touched it, its last activity at all (an issue he
            # opened that has no reply yet) — so the board shows a real age from the first sight on, not the hub's start.
            # The later of it and the carried-over last change wins.
            seen = info.pop("seen", None)
            with self.lock:
                st = self.status["anchors"].setdefault(a, {"last": None}); u = st.get("unreadable")
                if not info.get("url") and st.get("url"): info.pop("url", None)     # a failed read does not blank a link already known
                st.update(info)
                if seen and (not st.get("last") or seen > st["last"]): st["last"] = seen
                # An anchor the source refuses (a thread in a mailbox the
                # hub has no token for): asked again a minute later; still refused → one warning
                # to the project's keeper, then ever rarer tries, so a source is not asked every pass for what it will not give.
                if why:
                    u = u or {"since": now_iso(), "tries": 0}
                    u["why"] = why; u["tries"] += 1; u["next"] = now + min(RETRY[1], RETRY[0] * 2 ** (u["tries"] - 1))
                    if u["tries"] >= 2 and not u.get("warned"): u["warned"] = now_iso(); warn.append((a, why))
                    st["unreadable"] = u
                elif u and title:
                    del st["unreadable"]
                    if u.get("warned"): clear.append((a, st["label"]))
                elif u: u["next"] = now + RETRY[0]         # neither read nor refused (the network, the service): once more next pass
        for a, why in warn: self.warn_unreadable(a, f"anchor-hub cannot read it: {why}. No notice will come from it until that changes. "
                                                    "Fix the access or the link, then remove the anchor and add it again to have it checked at once; or remove it")
        for a, label in clear: self.warn_unreadable(a, f"anchor-hub can read it now ({label}); the earlier warning no longer holds")
        self.flush_queues()
        self.write_status()

    def warn_unreadable(self, anchor: str, text: str):
        """One notice per project the anchor belongs to, to that project's keeper (the sessions bound to it when the page
        names none), recorded in the routing log like any notice."""
        store = _anc.load()
        for project in sorted({r["project"] for r in _ROUTES.get(anchor, [])}):
            rs = [r for r in _ROUTES[anchor] if r["project"] == project]
            url = next((e.get("url") for e in store.get(project, []) if _anc.anchor_id(_anc.split_fragment(e.get("url", ""))[0]) == anchor), anchor)
            stew = _anc.canonical(_anc.name_line(project) or "")
            for s in ([stew] if stew else sorted({r["session"] for r in rs})):
                r = next((x for x in rs if x["session"] == s), rs[0])
                line = f"[anchor] {_anc.kind_of(anchor)} anchor of {project}: {text} → {url}"
                held = r["pilot"] and self.holds(project, s)         # live router: recorded for the router to rule, not delivered to the keeper
                try:
                    nid = _routing.record(project, kind="anchor", to="" if held else s, label=f"{_anc.kind_of(anchor)} anchor", who="anchor-hub", text=text.split(". ")[0], url=url if str(url).startswith("http") else "",
                                          target=r["target"], pilot=r["pilot"], anchor=anchor, live=bool(held))
                    if held: _live.stash(nid, line); continue
                    if r["pilot"]: line += f" — {r['target']} · notice {nid}"
                except Exception as e: log.warning("routing log %s: %s", project, str(e)[:120])
                self.deliver(anchor, s, line)

    def flush_queues(self):
        """Retry every queue: anchor-hub's own (queue/) and stackshot's messages (queue-msg/). push.py refuses while that
        source is paused for a reboot (exit 5), so a paused queue simply waits."""
        for src, d in (("hub", "queue"), ("msg", "queue-msg")):
            for qf in glob.glob(f"{ADIR}/{d}/*.jsonl"):
                name = os.path.basename(qf)[:-6]
                r = subprocess.run([*_interp.resilient(PUSH), "--flush", name], capture_output=True, text=True, env={**os.environ, "ANCHOR_PUSH_SOURCE": src})
                if r.returncode == 0 and r.stdout.strip(): log.info(r.stdout.strip())

    def event(self, anchor: str, summary: dict, kind: str = "slack"):
        """A receiver's report: summary = {title, who, text, url, ts[, body]} — the anchor's own title, never its type."""
        self.emit(Event(anchor=anchor, kind=kind, title=summary["title"], who=summary["who"], text=summary["text"],
                        url=summary["url"], ts=summary.get("ts"), body=summary.get("body") or "",
                        full=summary.get("full") or "", meta=dict(summary.get("meta") or {}), etype=str(summary.get("etype") or ""),
                        repo_id=_repo_id(summary.get("repo_id")), head=str(summary.get("head_ref") or ""), author=str(summary.get("author") or "")))

    def emit(self, ev: "Event"):
        """Route one event to the sessions bound to its anchor. The first event on (anchor, session) is delivered at once;
        further events are collapsed into one follow-up notice: after DEBOUNCE s for most kinds, after QUIET[kind] s of
        silence for a kind that comes in editing sessions (Drive), at the latest QUIET_MAX s after the first.
        An anchor in [anchor_hub] direct takes the direct lane instead (emit_direct).
        A routine event on the fleet's own pull request (routine_own) is logged instead of delivered to a session whose every
        route for the anchor is in the pilot (log_routine): no notice, nothing held for a follow-up."""
        try: _merges.note(ev.anchor, ev.url, ev.etype, (ev.meta or {}).get("refs"), time.time())      # first, before any lane: a merge is recorded whatever happens to its notice
        except Exception as e: log.warning("merge log: %s", str(e)[:120])
        try: _events.note(ev.anchor, ev.url, ev.etype, ev.who, (ev.meta or {}).get("refs"), time.time())      # the same funnel, the same rule: recorded whatever happens to the notice, from what the event already holds
        except Exception as e: log.warning("event log: %s", str(e)[:120])
        to = direct().get(ev.anchor)
        if to: return self.emit_direct(ev, to)
        why = routine_own(ev)
        deliver, logged = [], []
        with self.lock:
            sessions = self.bindings.get(ev.anchor)
            if sessions: self._seen(ev)
            if not sessions:
                with open(UNBOUND, "a") as f: f.write(f"{now_iso()} {ev.anchor} {ev.label} {ev.who}\n")
                return
            for s in sessions:
                flt = _FILTERS.get((ev.anchor, s))
                if flt and flt.lower() not in f"{ev.text} {ev.who} {ev.body}".lower():
                    log.info("%s → %s: skipped, no mention of %r", ev.anchor, s, flt); continue
                if why:
                    rs = [r for r in _ROUTES.get(ev.anchor, []) if r["session"] == s]
                    if rs and all(r["pilot"] for r in rs): logged.append((s, rs)); continue
                p = self.pending.get((ev.anchor, s))
                if p is None:
                    self.pending[(ev.anchor, s)] = {"first": time.time(), "last_at": time.time(), "count": 0, "label": ev.label, "last": ev, "kind": ev.kind, "etypes": [], "whos": [], "texts": []}
                    deliver.append((s, notice(ev)))
                else:
                    p["count"] += 1; p["last"] = ev; p["last_at"] = time.time()
                    p.setdefault("etypes", []).append(ev.etype); p.setdefault("whos", []).append(ev.who); p.setdefault("texts", []).append(ev.text)
        for s, rs in logged: self.log_routine(ev, s, rs, why)
        for s, text in deliver: self.send(ev.anchor, s, text, ev, ev.text)

    def log_routine(self, ev: "Event", session: str, routes: list[dict], why: str):
        """A routine event on the fleet's own PR (the turn rule's third build): one line per project
        the route serves, with no recipient, marked log_only, the reason `why`, and ruled `merged` by stackshot (auto) at once
        (routing.record_auto). It stays on the routing page; a held item scoped to the anchor is released by the
        server's minute pass, as a `merged` ruling would release it. A log line that cannot be written is delivered as
        before (send), never lost."""
        for r in routes:
            try:
                nid = _routing.record_auto(r["project"], "merged", self._why_for(r["project"], why), kind="anchor", label=ev.label, who=ev.who,
                                           text=f"{ev.title}: {ev.who} {ev.text}", url=ev.url, target=r["target"], pilot=True, anchor=ev.anchor)
                log.info("%s: %s, not delivered (%s, notice %s)", ev.anchor, ev.etype, r["project"], nid)
            except Exception as e:
                log.warning("routing log %s: %s; delivering instead", r["project"], str(e)[:120])
                self.send(ev.anchor, session, notice(ev), ev, ev.text); return

    def _seen(self, ev: "Event"):
        """The board's record of a watched anchor's last change (the caller holds the lock)."""
        st = self.status["anchors"].setdefault(ev.anchor, {}); st.update({"last": now_iso(), "type": ev.type, "title": ev.title, "label": ev.label})
        if st.get("unreadable"): st["unreadable"]["next"] = 0          # an event from it: it can be read after all, the next pass confirms

    def emit_direct(self, ev: "Event", session: str):
        """The direct lane: one notice per event, at once, to the one session [anchor_hub] direct names, whole
        (direct_notice). The derived bindings and the pilot's addressee, the mention filters and the debounce/quiet windows do not
        apply, and nothing is held in self.pending. The notice goes in the routing log of every project the anchor belongs to,
        with target "direct" and pilot False, so there is nothing to rule on and it carries no notice id. The direct
        config wins over the projects': an anchor bound to no project at all is still delivered (there is no log to write).
        The value "none" (LOG_ONLY) takes the same path to the log and stops there: see log_direct."""
        if log_only(session): return self.log_direct(ev)
        to = _anc.canonical(session)          # one identity per pane, as the bindings name it (a live pane's name → its uuid)
        with self.lock:
            if ev.anchor in self.bindings: self._seen(ev)
        for project in sorted({r["project"] for r in _ROUTES.get(ev.anchor, [])}):
            try: _routing.record(project, kind="anchor", to=to, label=ev.label, who=ev.who, text=ev.text, url=ev.url,
                                 target="direct", pilot=False, anchor=ev.anchor)
            except Exception as e: log.warning("routing log %s: %s", project, str(e)[:120])
        self.deliver(ev.anchor, to, direct_notice(ev))

    def log_direct(self, ev: "Event"):
        """A log-only direct anchor ([anchor_hub] direct value "none"; a script-driven upgrade's
        release events must wake no session). The event is written to the routing log of every project the
        anchor belongs to, with no recipient (to ""), target "direct", pilot False and the reason LOG_ONLY_REASON, and goes
        no further: nothing is delivered, nothing is held in self.pending (so no follow-up), no ruling is owed,
        and a line with no recipient releases no item that waits on the anchor (server._anchor_release)."""
        with self.lock:
            if ev.anchor in self.bindings: self._seen(ev)
        projects = sorted({r["project"] for r in _ROUTES.get(ev.anchor, [])})
        for project in projects:
            try: _routing.record(project, kind="anchor", to="", label=ev.label, who=ev.who, text=ev.text, url=ev.url,
                                 target="direct", pilot=False, anchor=ev.anchor, reason=LOG_ONLY_REASON)
            except Exception as e: log.warning("routing log %s: %s", project, str(e)[:120])
        log.info("%s: %s, not delivered (%s)", ev.anchor, LOG_ONLY_REASON, ", ".join(projects) or "bound to no project")

    def tick(self):
        due = []
        with self.lock:
            now = time.time()
            for k, p in list(self.pending.items()):
                win = _quiet().get(p.get("kind") or "", 0)
                ripe = (now - p["last_at"] >= win or now - p["first"] >= _quiet_max()) if win else (now - p["first"] >= DEBOUNCE)
                if ripe: due.append((k, p)); del self.pending[k]
        for (anchor, session), p in due:
            if p["count"]: self.send_burst(anchor, session, p)

    def send_burst(self, anchor: str, session: str, p: dict):
        """The follow-up for the events that came after the first one: delivered and recorded as one notice, but it keeps what the router
        decides by. Its event type is the types of the whole burst joined with "+" in order of appearance (an unclassified event reads `other`), its
        sender the senders joined with ", ", and its recorded gist carries any earlier text of the burst that names the owner or is for him
        (router.names_owner), so that a comment folded behind a CI result is never read as a CI notice and a word to the owner is not lost."""
        ev, gist = p["last"], f"{p['count']} more, the last: {p['last'].text}"
        try:
            if anchor.startswith("github:"):      # only GitHub types its events; other sources' follow-ups are recorded as before
                types = list(dict.fromkeys((t or "other") for t in (p.get("etypes") or [ev.etype])))
                whos = list(dict.fromkeys(w for w in (p.get("whos") or [ev.who]) if w))
                rt = _router_rules
                extra = [t for t in (p.get("texts") or [])[:-1] if t and rt and rt.names_owner(t)]
                if extra:      # a word that names <owner>: the gist leads with it (the record cuts the text at 300 characters), and the type leaves the build-side whitelist whatever is cut
                    gist = f"{p['count']} more, earlier: " + " | ".join(extra) + f" | the last: {ev.text}"
                    if "other" not in types: types.append("other")
                ev = replace(ev, etype="+".join(types), who=", ".join(whos) or ev.who)
        except Exception as e:      # the follow-up is never lost for the router's sake: sent as before
            log.warning("burst %s: %s; sent as before", anchor, str(e)[:120]); ev, gist = p["last"], f"{p['count']} more, the last: {p['last'].text}"
        self.send(anchor, session, follow_up(p), ev, gist)

    def persist(self) -> str:
        """Write every receiver's read position to CURSORS (atomic). Returns the time it was saved."""
        out = {"saved": now_iso()}
        for name, fn in list(self.savers.items()):
            try: out[name] = _jsonable(fn())
            except Exception as e: log.warning("persist %s: %s", name, str(e)[:120])
        write_atomic(CURSORS, json.dumps(out, ensure_ascii=False))
        return out["saved"]

    def shutdown(self):
        """SIGTERM (a clean stop): let running deliveries finish, hand pending follow-ups to push.py (queued if paused),
        save every read position and the status, then exit."""
        self.stopping.set()
        log.info("stopping: %d delivery(ies) in flight", self.inflight)
        t0 = time.time()
        while self.inflight and time.time() - t0 < 25: time.sleep(0.2)
        with self.lock: due = [(k, p) for k, p in self.pending.items() if p["count"]]; self.pending.clear()
        for (anchor, session), p in due: self.send_burst(anchor, session, p)
        saved = self.persist()
        with self.lock: self.status["stopped"] = now_iso()
        self.write_status()
        log.info("stopped cleanly: read positions saved %s, %d follow-up(s) handed over", saved, len(due))

    def send(self, anchor: str, session: str, text: str, ev: "Event", gist: str):
        """Record the notice in the routing log of every project this (anchor, session) serves, then deliver it. For a
        project in the pilot the text also says whom the notice is for and carries the id the ruling is made on."""
        tags, held, kept = [], [], 0
        for r in _ROUTES.get(anchor, []):
            if r["session"] != session: continue
            live = r["pilot"] and self.holds(r["project"], session)      # live router: the router rules it, the keeper is not told
            try:
                nid = _routing.record(r["project"], kind="anchor", to="" if live else session, label=ev.label, who=ev.who, text=gist, url=ev.url,
                                      target=r["target"], pilot=r["pilot"], anchor=anchor, live=bool(live), head=getattr(ev, "head", ""), author=getattr(ev, "author", ""), etype=getattr(ev, "etype", ""))
            except Exception as e: log.warning("routing log %s: %s", r["project"], str(e)[:120]); kept += 1; continue
            if live: held.append(nid); _live.stash(nid, text); continue
            kept += 1
            if r["pilot"]: tags.append(f"{r['target']} · notice {nid}")
        if held and not kept:
            log.info("%s → %s: held for the router (%s), not delivered", anchor, session, ", ".join(held)); return
        self.deliver(anchor, session, text + (" — " + "; ".join(tags) if tags else ""))

    @staticmethod
    def _why_for(project: str, why: str) -> str:
        """The reason of a log-only line: it stays on the project's routing page (there is no digest to list it in)."""
        return why

    @staticmethod
    def holds(project: str, session: str) -> bool:
        """Is this notice the router's to rule (router_live.holds: a live project, the keeper as the recipient)? False when the
        router module is not there."""
        try: return bool(_live and _live.holds(project, session))
        except Exception: return False

    def deliver(self, anchor: str, session: str, text: str):
        _ro.guard("anchor-hub delivery")
        with self.lock: self.inflight += 1
        try: r = subprocess.run([*_interp.resilient(PUSH), "--from", "anchor-hub", session, text], capture_output=True, text=True)
        finally:
            with self.lock: self.inflight -= 1
        log.info("%s | %s", r.stdout.strip() or r.stderr.strip(), text[:100])
        with self.lock:
            self.status["notices"] += 1
            self.status["last_notice"] = {"at": now_iso(), "session": session, "anchor": anchor, "result": r.stdout.strip()}
        self.write_status()

    def hook_server(self):
        hub = self
        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0); body = self.rfile.read(n) if n else b""
                route = self.path.split("?")[0]; retry_after = None
                # Both read under one lock: a receiver registers its hook first and clears hub.retrying after, so a request that sees
                # no hook is guaranteed to see the route still marked, and never falls through to 404 at the moment of recovery.
                with hub.lock: fn = hub.hooks.get(route); wait = hub.retrying.get(route) if fn is None else None
                if wait:
                    # The receiver that owns this route has not started yet and its start is being retried: "try again later", not
                    # "no such hook" (a 404 is how a sender learns to give up on a subscription; a 503 makes Google retry). One log
                    # line per outage and route; the count of the rest goes out with the recovery line.
                    with hub.lock: wait["refused"] += 1; first = wait["refused"] == 1; left = wait["next"] - time.time(); retry_after = max(1, math.ceil(left if left > 0 else wait["step"]))   # an attempt running now: the current step
                    code, text = 503, f"{wait['receiver']} is starting, try again"
                    if first: log.warning("hook %s → %s %s (the rest of this outage is counted, not logged)", self.path, code, text)
                else:
                    if fn is None: code, text = 404, "no such hook"
                    else:
                        try: code, text = fn(self.headers, body)
                        except Exception as e: code, text = 500, "error"; log.warning("hook %s: %s", self.path, str(e)[:160])
                    if code >= 400: log.warning("hook %s → %s %s", self.path, code, text)
                    else: log.info("hook %s ← accepted (%s)", self.path, text)
                self.send_response(code); self.send_header("Content-Type", "text/plain")
                if retry_after is not None: self.send_header("Retry-After", str(retry_after))
                self.end_headers(); self.wfile.write(text.encode())
            def do_GET(self):
                self.send_response(200); self.end_headers(); self.wfile.write(b"anchor-hub hooks\n")
            def log_message(self, *a): pass
        srv = ThreadingHTTPServer(("127.0.0.1", HOOK_PORT), H); srv.daemon_threads = True
        self.hook_srv = srv
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        log.info("hooks: listening on 127.0.0.1:%d (%s)", HOOK_PORT, HOOK_URL)

    def health(self, name: str, ok: bool, err: str | None = None):
        """A receiver reports the result of a real check (a fixed 10-min stamp said nothing more than the
        signal under it): Slack its live socket (1 min) and 30-min catch-up, GitHub each poll pass (1 min), Google and Notion
        their 30-min re-read of the change feed. `checked` on the board is that moment."""
        with self.lock:
            r = self.status.setdefault("receivers", {})
            r[name] = {"ok": bool(ok), "error": None if ok else (err or "check failed"), "checked": now_iso()}
            self.status["receivers_ok"] = all(v.get("ok") for v in r.values())
            (self.status.get("hold") or {}).pop(name, None)       # a check ends any announced wait
        self.write_status()

    def hold(self, name: str, seconds: float):
        """A receiver announces that it will report no check for `seconds` (its first pass after a start, a wait after GitHub refuses calls): the board counts
        its age from the end of the wait (receiver_health.stale_age). The next hub.health() of the receiver clears it. A failed status write is
        logged, never raised: the announcement must not stop the wait it announces."""
        with self.lock: self.status.setdefault("hold", {})[name] = time.time() + seconds
        try: self.write_status()
        except Exception as e: log.warning("receiver %s: hold not written: %s", name, str(e)[:120])

    def write_status(self):
        _ro.guard("anchor-hub status write")
        try: pz = json.load(open(PAUSED))
        except Exception: pz = None
        with self._status_io:      # called from every receiver's thread at once: the text is made and put in place under one lock, each write whole
            with self.lock:
                self.status["push"] = self.push; self.status["paused"] = pz
                text = json.dumps(self.status, indent=1, ensure_ascii=False)
            write_atomic(STATUS, text)


# ---------- receivers that fail at start ----------
class Transient(Exception):
    """Raised by a receiver whose start failed on the network or the service (DNS down, a timeout): waiting can fix it."""
class Permanent(Exception):
    """Raised by a receiver whose start cannot succeed by waiting (a missing or refused credential). Same as any exception
    that is not transient(): logged at ERROR, the receiver stays off, as it always did."""

RECEIVER_RETRY = (5.0, 300.0)    # s: a receiver whose start failed on the network is tried again after 5 s, then at doubling intervals up to 5 min
_TRANSIENT_CLASSES = {"TransportError", "ServerNotFoundError", "HttpLib2Error", "Timeout", "ConnectionError"}   # google-auth, httplib2, requests (by name: the libraries load lazily)
_TRANSIENT_SLACK = {"ratelimited", "service_unavailable", "fatal_error", "internal_error", "request_timeout"}
def transient(e: BaseException) -> bool:
    """True when a failed start is the network's or the service's trouble, so that waiting can fix it: a Transient; an OSError
    (DNS, a refused or reset connection, a timeout: URLError, socket.gaierror, TimeoutError, requests' errors) other than a
    missing or unreadable file, and not an HTTP error answer (urllib's HTTPError: only a 408, 429 or 5xx counts); google-auth's TransportError, httplib2's errors; an HTTP 408, 429 or 5xx from Google; a Slack
    rate limit or outage. Everything else (a missing key, a refused or revoked token, a bad file, a bug) is final: waiting does
    not change it, and a retry of a bug would repeat whatever the start did before it failed."""
    if isinstance(e, Transient): return True
    if isinstance(e, Permanent): return False
    if isinstance(e, urllib.error.HTTPError): return e.code in (408, 429) or e.code >= 500      # an HTTPError is a URLError and so an OSError: a 401 is the credential, not the network
    if isinstance(e, OSError): return not isinstance(e, (FileNotFoundError, PermissionError, IsADirectoryError, NotADirectoryError))
    if any(c.__name__ in _TRANSIENT_CLASSES for c in type(e).__mro__): return True
    status = getattr(getattr(e, "resp", None), "status", None)                  # googleapiclient.errors.HttpError
    if status is not None:
        try: return int(status) in (408, 429) or int(status) >= 500
        except (TypeError, ValueError): return False
    if type(e).__name__ == "SlackApiError":                                      # slack_sdk.errors.SlackApiError
        resp = getattr(e, "response", None)
        try: return resp.get("error") in _TRANSIENT_SLACK or int(getattr(resp, "status_code", 0) or 0) >= 500
        except Exception: return False
    return False

def _receiver_state(hub: Hub, name: str, ok: bool, error: str | None, **extra):
    with hub.lock:
        hub.status.setdefault("receivers", {})[name] = {"ok": ok, "error": error, **extra, "checked": now_iso()}
        hub.status["receivers_ok"] = all(v.get("ok") for v in hub.status["receivers"].values())

def start_receiver(hub: Hub, name: str, fn, ready, routes=(), backoff=RECEIVER_RETRY, stop: "threading.Event | None" = None):
    """Start one receiver, fn(hub), and record ok or failed in status.json["receivers"] (the board and the health poll read it).

    The first try runs here, in order, as it always did: the resolvers are registered before the first rescan. A failure that is
    the network's (transient(); for instance a box booted before its DNS was up, so the receivers failed in their first
    seconds and would stay off) is retried on a background thread, with capped exponential backoff and
    jitter, until the receiver is ready. The other receivers and the HTTP server never wait for it, and its `routes` answer 503
    with a Retry-After meanwhile (hub.retrying), never 404. A failure for any other reason, or a start that returns without being
    ready (no token, no credentials: the receiver logs why itself), is final, logged at ERROR, as before. One log line per
    attempt: WARNING for a failure that is being retried, INFO for the recovery. Returns the retry thread, or None.
    `stop` ends the retry loop early (the tests; the service itself just exits)."""
    _ro.guard("start a receiver")
    def attempt() -> "tuple[bool, str | None, bool]":                           # → (ready, error, worth another try)
        try: fn(hub)
        except Exception as e: return False, (str(e).strip().replace("\n", " ") or type(e).__name__)[:300], transient(e)
        return bool(ready()), None, False
    with hub.lock:
        for r in routes: hub.retrying[r] = {"receiver": name, "next": time.time(), "step": backoff[0], "refused": 0}
    def settle(ok, err, tries, t0):
        with hub.lock: refused = sum(hub.retrying.pop(r, {}).get("refused", 0) for r in routes)
        _receiver_state(hub, name, ok, None if ok else (err or "did not report ready"))
        if ok and tries == 1: log.info("receiver %s: ready", name)
        elif ok: log.info("receiver %s: ready after %d tries, %.1f s%s", name, tries, time.time() - t0, f"; {refused} hook request(s) answered 503 meanwhile" if refused else "")
        else: log.error("receiver %s: FAILED — %s%s", name, err or "did not report ready", f" (try {tries}; not retried)" if tries > 1 else "")
    t0 = time.time(); ok, err, retry = attempt()
    if ok or not retry: settle(ok, err, 1, t0); return None
    first, cap = backoff; stop = stop or threading.Event()
    def loop(err):
        tries = 1
        while True:
            delay = min(cap, first * 2 ** (tries - 1)); wait = delay / 2 + random.uniform(0, delay / 2)   # jitter below the cap, never above it
            with hub.lock:
                for r in routes:
                    if r in hub.retrying: hub.retrying[r].update(next=time.time() + wait, step=wait)
            _receiver_state(hub, name, False, err, retrying=True, tries=tries, next_try=now_iso_at(time.time() + wait))
            log.warning("receiver %s: start failed (try %d: %s), trying again in %.1f s", name, tries, err, wait)
            try: hub.write_status()
            except Exception: pass
            if stop.wait(wait): return
            tries += 1; ok, err, retry = attempt()
            if ok or not retry:
                settle(ok, err, tries, t0)
                try: hub.write_status()
                except Exception: pass
                return
    th = threading.Thread(target=loop, args=(err,), name=f"receiver-{name}", daemon=True); th.start()
    return th
