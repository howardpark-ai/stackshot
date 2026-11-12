"""Scenario test for the GitHub mirror and the id switch (ghsync.py) — fixture data, a fake
GitHub API on localhost, no live store, no network.

An issue carries the item's subject (its title), whether it
is open or closed (with the close reason) and its description (the body: the marker line that maps issue to item, the description, one footer link to the
item's page), and nothing else: no history comments, no labels, no typed fields, no blocked-by links, no next, ask or options in the body. A change to any
other field of an item makes no job and so no call to GitHub. The fake GitHub records every call the slim mirror must never make (F.forbidden: the labels,
the org's issue fields, an issue's field values, blocked-by, a comment or a comment edit) and the run ends by checking that the list is empty.

Covers: with [github] sync off (the default) a write sends nothing and queues nothing. The migration (ghsync.migrate, the ghmigrate.py CLI's engine): the
open items become issues #1 onward in id order, closed ones stay, each issue's body is the item's marker, description and footer, no labels, no comment; the
files move to g/<n>.json, the old ids stay as aliases (the map, _norm_id, _path, /items/<old id> → 301), after lists follow, the board renders the moved
items, replies and links write board#<n>; a second run creates nothing, a run with the map lost rebuilds it from the markers, a dry run writes nothing. The
mirror, turned on by a config reload: a create makes an issue (one POST); a change of the subject or the description patches the issue (one PATCH, no
comment); a close closes the issue as completed or not planned, a reopen reopens it; a change of next, needs, a hold or a wake, the ask and options, the due
date, a work line, a confirm, a wake pass, an after-release, an anchor release or a recycle done makes no job and no call. An outage and a rate limit leave
the jobs in the queue and nothing fails in the tool, the queue drains when GitHub is back with no second issue (the marker guard), a refusal moves the job to
failed/; the writes are paced. The merge window: the updates of an existing issue wait [github] merge_seconds and go out as one PATCH; a create,
a close and a reopening go at once; a restart keeps the pending jobs; the host's one ledger counts the writes and the reads. The id switch: a new item's id is
its issue number (g<n>, shown board#<n>). A create during an outage takes a local id (l1, l2, …), is queued, and when GitHub answers is re-keyed to its issue
number: the file moves, l<n> becomes an alias, an `after` list and an anchor scope that named it follow, the owner is told one line, and the counter
survives a restart.

The inbound half (phase 3): the owner's own comment on an item's issue (his login, no `[author: …]` header) is recorded on the item (metadata.answers: {ts,
kind comment, text, via github, url, comment_id}), told once to the owner (marked [for the owner] when it is a front agent) and to each session in its needs,
shown in the item page's History as written on GitHub, and leaves needs, status and the clocks alone. The mirror's older comments (they carry the header),
another user's, an edit of a delivered comment, history edited after the reader started and a comment on an issue no item mirrors are passed by; a re-read and
a restart deliver nothing twice; the first read starts at now; a comment the hook could not take waits for the next read; the reader thread delivers on its own;
[github] owner_login picks whose comments count; with sync off nothing is read. The item page's History is the store's git, with the mirror on or off.

The HTML board: with [github] off old ids render exactly as before; after the move an issue-numbered item is written board#<n> wherever a person reads
its id and its page is /items/<n>; /items/g<n> answers 301 there.

The body form (BODY_FORM 3) and the one-time rewrite (resync_bodies): queued only when `[github] backfill_bodies` is on (off by default), one background job per
issue whose body is stale, no comment, through the pacer, yielding to a live write that arrives meanwhile. The trailers (said=…), checked against the writer's
transcript, are stored on the item and shown on its page; they reach GitHub as nothing.

    tests/run-suite github        → exit 0 / 1"""
import calendar, hashlib, html, json, logging, os, pathlib, re, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse
BID_A = 9164
BID_B = 9165

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="ghtest-"); T = pathlib.Path(tmp)


# ---- a fake GitHub API: the endpoints the mirror and the migration use, one repo "o/r"
def iso(t): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


class Fake:
    def __init__(self):
        self.issues = {}; self.next = 1; self.comments_next = 1
        self.down = False; self.ratelimit = False; self.refuse_next = 0; self.not_modified = 0; self.secondary = False
        self.moved = False; self.moved_write = 307; self.moved_only = ""   # the repo moved: the old path answers a redirect to /repositories/1/…, a GET with 301, a write with moved_write; moved_only narrows it to paths holding that text
        self.skew = 0.0                                 # seconds added to the fake's clock: a test moves GitHub's second-granular time on without sleeping
        self.log = []                                   # (method, path, monotonic)
        self.queries = []                               # the query of each GET of the comments (phase 3)
        self.forbidden = []                             # (method, path) of every call the slim mirror must never make: labels, org fields, field values, blocked-by, a comment, a comment edit
        self.lock = threading.Lock()
    def add_comment(self, n, body, login="example-owner", at=None):
        """A comment as GitHub stores it: the mirror's (through the API) or a person's (phase 3: `login`, written `at`)."""
        t = iso((time.time() if at is None else at) + self.skew)
        c = {"id": self.comments_next, "body": body, "user": {"login": login}, "created_at": t, "updated_at": t,
             "html_url": f"https://github.example/o/r/issues/{n}#issuecomment-{self.comments_next}", "issue_url": f"https://api.github.example/repos/o/r/issues/{n}"}
        self.comments_next += 1; self.issues[n]["_comments"].append(c); return c
    def comment(self, n, body, login="example-owner", at=None):
        with self.lock: return self.add_comment(n, body, login, at)
    def edit(self, cid, body, at=None):
        """A comment edited (a person's, or the mirror's PATCH): the body changes, updated_at moves, created_at stays."""
        with self.lock: return self._edit(cid, body, at)
    def _edit(self, cid, body, at=None):
        for i in self.issues.values():
            for c in i["_comments"]:
                if c["id"] == cid:      # updated_at moves (a second at least: GitHub's clocks are second-granular, the test's edits a moment after the post)
                    c["body"] = body; c["updated_at"] = max(iso((time.time() if at is None else at) + self.skew), iso(calendar.timegm(time.strptime(c["created_at"], "%Y-%m-%dT%H:%M:%SZ")) + 1)); return c
        raise KeyError(cid)
    def delete(self, cid):
        """A comment deleted on GitHub (a person's hand): gone from the listing, a PATCH of it 404s."""
        with self.lock:
            for i in self.issues.values():
                i["_comments"] = [c for c in i["_comments"] if c["id"] != cid]

F = Fake()
REPO = "/repos/o/r"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj=None, headers=None):
        body = json.dumps(obj).encode() if obj is not None else b""
        headers = dict(headers or {})
        if code == 200 and self.command == "GET" and obj is not None:        # an ETag on every GET answer, and a 304 for a matching If-None-Match (GitHub does not count it)
            tag = '"' + hashlib.sha1(body).hexdigest() + '"'
            if self.headers.get("If-None-Match") == tag:
                F.not_modified += 1; code, body = 304, b""
            headers["ETag"] = tag
        headers.setdefault("x-ratelimit-limit", "5000"); headers.setdefault("x-ratelimit-remaining", "4000")
        headers.setdefault("x-ratelimit-used", "1000"); headers.setdefault("x-ratelimit-resource", "core"); headers.setdefault("x-ratelimit-reset", str(int(time.time()) + 600))
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        for k, v in headers.items(): self.send_header(k, v)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}
    def _issue_out(self, i):
        return {**{k: v for k, v in i.items() if k not in ("_fields", "_blocked_by")}, "id": 100000 + i["number"], "comments": len(i["_comments"]), "labels": [{"name": x} for x in i["labels"]], "html_url": f"https://github.example/o/r/issues/{i['number']}", "user": {"login": "example-owner"}}
    def _handle(self, method):
        u = urlparse(self.path); path, q = u.path, parse_qs(u.query)
        via_new = path.startswith("/repositories/1/")                                     # the repo's id-form path, where a redirect points (the repo moved)
        if via_new: path = REPO + path[len("/repositories/1"):]
        with F.lock:
            F.log.append((method, u.path, time.monotonic()))
            if F.moved and path.startswith(REPO) and not via_new and (not F.moved_only or F.moved_only in path):   # the repo moved: GitHub answers the old path with a redirect
                loc = API + "/repositories/1" + path[len(REPO):] + (f"?{u.query}" if u.query else "")
                return self._send(301 if method in ("GET", "HEAD") else F.moved_write, {"message": "Moved Permanently", "url": loc, "documentation_url": "https://docs.github.com/rest/overview/resources-in-the-rest-api#http-redirects"}, {"Location": loc})
            if path == "/rate_limit" and method == "GET":        # costs no call, answers while the limit holds
                return self._send(200, {"resources": {"core": {"limit": 5000, "remaining": 0 if F.ratelimit else 4000, "reset": int(time.time()) + 60}}})
            if F.down: return self._send(503, {"message": "down"})
            if F.secondary: return self._send(403, {"message": "You have exceeded a secondary rate limit"}, {"retry-after": "1"})   # a Retry-After answer with the core bucket full
            if F.ratelimit: return self._send(403, {"message": "API rate limit exceeded"}, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(time.time()) + 60)})
            if F.refuse_next and method in ("POST", "PATCH"):
                code, F.refuse_next = F.refuse_next, 0
                return self._send(code, {"message": "refused for the test"})
            if self.headers.get("Authorization") != "Bearer test-token": return self._send(401, {"message": "bad credentials"})
            if re.search(r"/labels|/issue-field-values|/dependencies/", path) or path.startswith("/orgs/") or (method in ("POST", "PATCH", "DELETE") and "/comments" in path):
                F.forbidden.append((method, u.path)); return self._send(404, {"message": "the slim mirror never calls this"})      # none of these is called any more
            if path == "/user" and method == "GET": return self._send(200, {"login": "example-owner", "id": 1})
            if path == REPO + "/issues/comments" and method == "GET":        # phase 3: the repo's comments updated since the cursor, oldest update first
                F.queries.append(q); since = q.get("since", [""])[0]
                page = int(q.get("page", ["1"])[0]); per = int(q.get("per_page", ["30"])[0])
                rows = sorted((c for i in F.issues.values() for c in i["_comments"] if c["updated_at"] >= since), key=lambda c: (c["updated_at"], c["id"]))
                return self._send(200, rows[(page - 1) * per: page * per])
            m = re.fullmatch(REPO + r"/issues", path)
            if m and method == "POST":
                b = self._body()
                if "labels" in b: F.forbidden.append(("POST labels", u.path))
                n = F.next; F.next += 1
                F.issues[n] = {"number": n, "title": b["title"], "body": b.get("body", ""), "labels": [], "state": "open", "state_reason": None, "created_at": iso(time.time() + F.skew), "_comments": []}
                return self._send(201, self._issue_out(F.issues[n]))
            if m and method == "GET":
                page = int(q.get("page", ["1"])[0]); per = int(q.get("per_page", ["30"])[0])
                st_q, lab_q = q.get("state", [""])[0], q.get("labels", [""])[0]      # GitHub's filters: state, and labels (every one named, comma-separated)
                rows = [self._issue_out(i) for n, i in sorted(F.issues.items(), reverse=True)
                        if (st_q in ("", "all") or i["state"] == st_q) and all(x in i["labels"] for x in lab_q.split(",") if x)]
                return self._send(200, rows[(page - 1) * per: page * per])
            m = re.fullmatch(REPO + r"/issues/(\d+)", path)
            if m:
                i = F.issues.get(int(m.group(1)))
                if not i: return self._send(404, {"message": "Not Found"})
                if method == "GET": return self._send(200, self._issue_out(i))
                if method == "PATCH":
                    b = self._body()
                    if "labels" in b: F.forbidden.append(("PATCH labels", u.path))
                    for k in ("title", "body", "state", "state_reason"):
                        if k in b: i[k] = b[k]
                    return self._send(200, self._issue_out(i))
            m = re.fullmatch(REPO + r"/issues/(\d+)/comments", path)
            if m:
                i = F.issues.get(int(m.group(1)))
                if not i: return self._send(404, {"message": "Not Found"})
                if method == "GET":                                           # phase 4: `since` on one issue's comments, the bundle's check
                    F.queries.append(q); since = q.get("since", [""])[0]
                    page = int(q.get("page", ["1"])[0]); per = int(q.get("per_page", ["30"])[0])
                    rows = [c for c in i["_comments"] if c["updated_at"] >= since]
                    return self._send(200, rows[(page - 1) * per: page * per])
            return self._send(404, {"message": f"no route {method} {path}"})
    def do_DELETE(self): self._handle("DELETE")
    def do_GET(self): self._handle("GET")
    def do_POST(self): self._handle("POST")
    def do_PATCH(self): self._handle("PATCH")


srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
API = f"http://127.0.0.1:{srv.server_address[1]}"
(T / "github.token").write_text("test-token\n")


# ---- the instance: the example config with the paths in the temp dir; [github] sync off first, the switches flipped by reload below
MERGE_S, HOURLY, READS = 0, 100000, 100000      # the config values write_toml writes; the merge-window section changes them
def write_toml(sync: bool, issue_ids: bool, backfill: bool = False):
    toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts", "{tmp}/transcripts-team"]', toml); assert n == 1   # [said] transcripts: several roots (6f)
    toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
    toml, n = re.subn(r'(?m)^board_url = "[^"]*"', 'board_url = "https://board.example.org"', toml); assert n == 1
    toml, n = re.subn(r'(?m)^sync = false', f'sync = {"true" if sync else "false"}', toml); assert n == 1
    toml, n = re.subn(r'(?m)^issue_ids = false', f'issue_ids = {"true" if issue_ids else "false"}', toml); assert n == 1
    toml, n = re.subn(r'(?m)^issues_repo = ""', 'issues_repo = "o/r"', toml); assert n == 1
    toml, n = re.subn(r'(?m)^backfill_bodies = false', f'backfill_bodies = {"true" if backfill else "false"}', toml); assert n == 1     # the slim body is not swept in unless asked
    toml, n = re.subn(r'(?m)^api_url = "[^"]*"', f'api_url = "{API}"', toml); assert n == 1
    toml, n = re.subn(r'(?m)^token_file = ""', f'token_file = "{tmp}/github.token"', toml); assert n == 1
    toml, n = re.subn(r'(?m)^min_interval_seconds = [0-9.]+', 'min_interval_seconds = 0.05', toml); assert n == 1
    toml, n = re.subn(r'(?m)^merge_seconds = [0-9.]+', f'merge_seconds = {MERGE_S}', toml); assert n == 1     # 0 = each update goes at once, as every section but the merge window's expects
    toml, n = re.subn(r'(?m)^hourly_budget = [0-9]+', f'hourly_budget = {HOURLY}', toml); assert n == 1        # the example's 250 is checked in its own section; the scenario's own writes are many
    toml, n = re.subn(r'(?m)^read_budget = [0-9]+', f'read_budget = {READS}', toml); assert n == 1
    toml, n = re.subn(r'(?m)^machine = "[^"]*"', 'machine = "boxa"', toml); assert n == 1     # [instance] machine: temporary ids read board-tmp-boxa#<n>
    toml, n = re.subn(r'(?m)^injected_marker = ""', 'injected_marker = "<!-- sala -->"', toml); assert n == 1   # [said] the fleet tool's marker, as an instance sets it (6f)
    toml, n = re.subn(r'(?m)^guards = true', 'guards = false', toml); assert n == 1      # [model] guards off: this suite is about the mirror, its ~120 writes carry plain next lines and bare holds (the write guards have their own suite: model_guards)
    toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # this suite is about the issue mirror, its writes replace next wholesale; the checklist has its own suite: checklist
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")

write_toml(sync=False, issue_ids=False)
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/s", "fleet/a", "state/anchor-hub", "brain/projects"): (T / d).mkdir(parents=True)
OWNER = "00000000-0000-4000-8000-000000000001"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-here", "status": "active", "board": [], "board_open": 0}}}))
DESC = "- A thing\n- It lives here\n- Finished when it works"
ASK = "Decide: whether to ship · Recommend: yes · Stakes: none either way · By: no date"
OPTS = [{"label": "Ship", "line": "Ship it now as it is", "recommended": True}, {"label": "Wait", "line": "Wait for the next release", "recommended": False}]
def item(L, i, status="open", **meta):
    (T / f"store/{L}/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {L}{i}", "description": DESC, "status": status,
                                                       "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                       "metadata": {"owner": OWNER, "project": "projects/alpha", **meta}}))
item("a", 1, next="do the thing", needs=["decision"], ask=ASK, options=OPTS, due="2026-10-20")
item("a", 2, status="completed", outcome="done", reason="it worked")
item("a", 3, next="the third thing", needs=["external"])
item("a", 4, status="completed", outcome="dropped", reason="not needed")
item("a", 5, hold=True, wake="2026-12-01", next="later")
item("s", 12, next="after a1 closes", after=["a1"])
(T / "store/next-id").write_text("20"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
def snap(msg): git("add", "-A"); git("commit", "-q", "--allow-empty", "-m", msg)
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
def rd(L, i): return json.loads((T / f"store/{L}/{i}.json").read_text())
STORE = T / "store"

from stackshot.web import server; from stackshot.web import render; from stackshot.github import ghsync as G; from stackshot.model import ids as _model_ids
from stackshot.core import instance as _core_instance
from stackshot.web.ui import render as ui_render
server._publish = lambda: None
server._wt.cap_needs_owner = lambda: False     # this scenario sets waits far ahead; the cap on a session's wake has its own scenario (waiting)
server._refuse_if_owing = lambda debtor: None        # the page rule is not under test here
server._tell_woken = lambda *a, **k: None            # no push.py
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except server.ToolError as e:
        check(name, all(w in str(e) for w in want), str(e))
def issue(n): return F.issues[n]
def comments(n): return [c["body"] for c in F.issues[n]["_comments"]]
def writes(): return [(m, p) for m, p, _t in F.log if m in ("POST", "PATCH")]
def qlen(): return len(G.pending())
def ghl(page): return re.findall(r'<a class="hgh" href="https://github\.com/([^"]+)"', page)   # the item page's link to its issue, beside the id
page = lambda g: ui_render.Board(str(STORE)).item_html(g)
def D(word): return f"- {word}\n- It lives here\n- Finished when it works"      # a description that differs from DESC by its first bullet: what an issue carries of an item's text
def mine(n): return [w for w in writes() if w[1] == REPO + f"/issues/{n}"]      # the writes on one issue
EPOCH_ISO = "1970-01-01T00:00:00Z"
GH = G.GitHub("o/r", API, "test-token", pace=0.05)
def _paced_sleep(w):
    """The pacer's sleep, bounded: the scenario's pace is never above 0.3 s, so a longer wait is the hour's budget spent
    (GitHub._throttle sleeps until the oldest write of the hour is an hour old), and the run fails here rather than sit for
    up to an hour (once: 500 writes against a budget of 400, cancelled at CI's time limit on every push)."""
    if w > 5:   # _throttle holds the client's lock here (and has just dropped the stamps older than an hour): read the deque, never recent_writes()
        raise RuntimeError(f"the pacer would sleep {w:.0f} s: {len(GH._writes)} writes this hour against a budget of {GH.budget}; a section widened the budget and put it back below the scenario's own writes")
    time.sleep(w)
GH.sleep = _paced_sleep
def budget_back(b):
    """The hourly budget put back after a section that widened it: what the section started from, on top of the scenario's
    own writes so far (they are never the sweep's concern), so the next paced write does not wait out the hour."""
    GH.budget = GH.recent_writes() + b

# ---- 1. the switch off: a write sends nothing, queues nothing
check("[github] sync is off by default", not G.enabled() and not G.issue_ids())
out = server._create(subject="[home] made with the mirror off", description=DESC, project="projects/alpha", owner="home-here", next="x")
gid0 = re.search(r"created (\S+)", out).group(1); snap("s21 created")
server._update(gid0, next="y", sender="home-here")
check("off: the item was created under the [ids] letter, nothing queued, nothing sent", gid0 == "s21" and qlen() == 0 and not F.log, (gid0, qlen(), F.log))
B0 = render.Board(str(STORE)); U0 = ui_render.Board(str(STORE)); h0, p0, md0 = U0.html() + "".join(U0.routing_html(k) for k in U0.proj), U0.item_html("s12"), B0.markdown()      # the item lines live on the project pages, the home rows on the board
check("off: the board writes old ids as before: a row's id a1 at /items/a1, the item page titled s12 with its after link a1, board.md **s12 · …**, no board# anywhere",
      '<a class="ir-link" href="/items/a1" target="_blank" rel="noopener"><span class="ir-id">a1</span>' in h0 and "<title>s12 · item s12</title>" in p0 and '<span class="hid">s12</span>' in p0
      and '<dt>After</dt><dd><a href="/items/a1">a1</a> <span class="dim">(open)</span>' in p0 and '<dt>Waits on</dt><dd><a href="/items/a1">a1</a> <span class="dim">(open)</span>' in p0
      and "**s12 · [home] item s12**" in md0 and "- after: [a1](#task-a-1)" in md0 and "board#" not in h0 + p0 + md0 + B0.brief(),
      (re.findall(r'<a class="ir-link"[^>]*><span class="ir-id">[^<]*</span>', h0)[:3], re.findall(r"<title>.*?</title>", p0)))
snap("s21 made")

# ---- 2. the migration: open items in id order → issues #1 onward, closed ones stay
plan = G.migrate(STORE, GH, dry_run=True)
check("dry run: the plan names every open item, in id order, and nothing is written or moved",
      plan["items"] == 5 and plan["created"] == 0 and [p.split(" ")[0] for p in plan["plan"]] == ["a1", "a3", "a5", "s12", "s21"] and not writes() and (STORE / "a/1.json").exists(), (plan, writes()))
r = G.migrate(STORE, GH, say=lambda s: None)
check("the open items became #1 onward in id order; the closed ones stayed", r["created"] == 5 and sorted(F.issues) == [1, 2, 3, 4, 5]
      and [issue(n)["title"] for n in (1, 2, 3, 4, 5)] == ["[home] item a1", "[home] item a3", "[home] item a5", "[home] item s12", "[home] made with the mirror off"]
      and (STORE / "a/2.json").exists() and (STORE / "a/4.json").exists() and not (STORE / "a/1.json").exists() and not (STORE / "s/12.json").exists(), (r, sorted(F.issues)))
b1 = issue(1)["body"]
check("the body is slim: the marker of the old id, the description, one footer line linking the item's page; no next, ask, options, owner or due",
      b1.startswith("<!-- stackshot:a1 -->\n\n" + DESC + "\n\n<sub>Mirrored from [a1](https://board.example.org/items/a1) by ") and b1.endswith("</sub>")
      and not any(w in b1 for w in ("###", "do the thing", ASK, "**owner**", "**due**", "**on hold**", "2026-12-01")), b1)
check("no labels: none on any issue, none created in the repo, and the held item's hold is not on GitHub", all(issue(n)["labels"] == [] for n in F.issues) and not F.forbidden, ([issue(n)["labels"] for n in F.issues], F.forbidden))
check("no history comment: the migration posts nothing to any issue", all(comments(n) == [] for n in F.issues) and all(m_ != "POST" or p_ == REPO + "/issues" for m_, p_ in writes()), [comments(n) for n in F.issues])
m = G.load_map(STORE)
check("the map: each new id's issue, each old id as an alias", m["issues"] == {"g1": 1, "g2": 2, "g3": 3, "g4": 4, "g5": 5}
      and m["aliases"] == {"a1": "g1", "a3": "g2", "a5": "g3", "s12": "g4", "s21": "g5"} and m["repo"] == "o/r", m)
check("the files moved to g/<n>.json with the new id", rd("g", 1)["id"] == "1" and rd("g", 1)["subject"] == "[home] item a1" and rd("g", 4)["id"] == "4", rd("g", 1))
check("the after list that named a1 now names g1", rd("g", 4)["metadata"]["after"] == ["g1"], rd("g", 4)["metadata"])
check("_norm_id: the old id, the board form, the hash form and g<n> all name the moved item", _model_ids._norm_id("a1") == "g1" and _model_ids._norm_id("board#2") == "g2"
      and _model_ids._norm_id("#3") == "g3" and _model_ids._norm_id("G4") == "g4" and _model_ids._norm_id("a2") == "a2", [_model_ids._norm_id(x) for x in ("a1", "board#2", "#3", "G4", "a2")])
refused("a bad id names the board#<n> form", lambda: _model_ids._norm_id("board5"), "board#<n>")
check("_path resolves an old id kept in a field", server._path("a1") == STORE / "g/1.json" and server._path("a2") == STORE / "a/2.json", server._path("a1"))
check("get by the old id answers with the item, shown as board#1", server.stackshot_get("a1").startswith("board#1 [open] [home] item a1"), server.stackshot_get("a1"))
check("the board renders the moved items", ui_render.Board(str(STORE)).item("g1")["subject"] == "[home] item a1" and "[home] item a1" in ui_render.Board(str(STORE)).item_html("g1"))
lk = server._link_ids
L = lambda shown, gid: f"[{shown}](https://board.example.org/items/{gid})"
check("href_id: an issue-numbered item's page is its bare number (g1 → 1); an old id keeps its own", G.href_id("g1") == "1" and G.href_id("a2") == "a2" and G.href_id("g") == "g",
      (G.href_id("g1"), G.href_id("a2")))
check("replies link board#<n> to /items/<n> and an old id to its own page; an unknown board#<n> stays plain",
      lk(f"see board#1, a1 and board#{BID_A}") == f"see {L('board#1', '1')}, {L('a1', 'a1')} and board#{BID_A}", lk(f"see board#1, a1 and board#{BID_A}"))
check("a bare store id g<n> in a reply is linked as it is shown, [board#<n>](…/items/<n>), never [g<n>]",
      lk("see g1 and board#1") == f"see {L('board#1', '1')} and {L('board#1', '1')}" and "[g1]" not in lk("g1"), lk("see g1 and board#1"))
check("…and copied back into a write it is stored plain, board#<n>", server._unlink_ids(lk("see g1")) == "see board#1", server._unlink_ids(lk("see g1")))
check("a linked board#<n> copied back into a write is stored plain, at /items/<n> and in the older /items/g<n> form",
      server._unlink_ids(f"{L('board#1', '1')}, {L('board#2', 'g2')} and {L('a2', 'a2')}") == "board#1, board#2 and a2", server._unlink_ids(f"{L('board#1', '1')}, {L('board#2', 'g2')} and {L('a2', 'a2')}"))
# the HTML board: an issue-numbered item is written #<n> on the board (board#<n> in board.md and the brief, which sessions read), and its page is /items/<n>; old ids as before
item("a", 7, status="completed", outcome="superseded", superseded_by="g1", reason="merged into the first")
d4 = rd("g", 4); d4["description"] = f"Waits on board#1 and g2; a2 was done; board#{BID_A} and board-tmp-other#1 are no items; board#4 is this one."
(STORE / "g/4.json").write_text(json.dumps(d4))
B = render.Board(str(STORE)); U = ui_render.Board(str(STORE)); hb = U.html(); h, md, p4, p7 = hb + "".join(U.routing_html(k) for k in U.proj), B.markdown(), U.item_html("g4"), U.item_html("a7")      # h: the board and the project pages (the item lines)
check("the board's rows: a moved item's id reads board#<n> and links /items/<n>; a closed old id keeps a2 at /items/a2; no g<n> label or /items/g<n> link",
      '<a class="ir-link" href="/items/1" target="_blank" rel="noopener"><span class="ir-id">#1</span> <span class="hgoal">item a1</span></a>' in h
      and 'href="/items/a2"' in h and not re.search(r'href="/items/g\d|>g\d+<', h),
      (re.findall(r'<a class="ir-link"[^>]*><span class="ir-id">[^<]*</span>', h), re.findall(r'href="/items/g\d+"', h)))
check("home notice: the label prefix for an issue-numbered id is the board's own naming (render.shown, # as the rows show it), whatever the sync, and the script holds no literal of it",
      'id="sent-notes" hidden data-hash="#"' in hb and f'id="sent-notes" hidden data-hash="{render.shown("g1")[:-1]}"' in h0 and "board#" not in ui_render._HOME_JS and "board#" not in h0, (re.findall(r'data-hash="[^"]*"', hb), re.findall(r'data-hash="[^"]*"', h0)))
check("the home rows and the parked mark: #1 links /items/1 in a row of the board, and the item that waits on it reads after #1",
      re.search(r'<a class="ir-link" href="/items/1"[^>]*><span class="ir-id">#1</span>', hb) is not None and re.search(r'<span class="hwait">After <a href="/items/1"[^>]*>#1</a></span>', hb) is not None,
      re.findall(r'<span class="hwait">.*?</span>', hb)[:6])
check("board.md and the brief write board#<n>", "**board#1 · [home] item a1**" in md and "[board#4](#task-g-4)" in md and "- after: [board#1](#task-g-1)" in md and "your move: board#1 [home] item a1" in B.brief() and "**g1 " not in md,
      (re.findall(r"\*\*[^*]*item a1\*\*", md), B.brief()))
check("the item page: title and heading board#4, the after link and the 'Waits on' line board#1 at /items/1",
      "<title>#4 · item s12</title>" in p4 and '<span class="hid">#4</span>' in p4 and '<dt>After</dt><dd><a href="/items/1">#1</a> <span class="dim">(open)</span>' in p4
      and '<dt>Waits on</dt><dd><a href="/items/1">#1</a> <span class="dim">(open)</span>' in p4, (re.findall(r"<title>.*?</title>", p4), re.findall(r"<dt>After</dt><dd>.*?</dd>", p4)))
check("free text on the item page: board#<n> and a bare g<n> link to /items/<n> written board#<n>, an old id as before; an unknown board#<n>, another machine's temporary id and the page's own id stay plain",
      re.search(r'<a href="/items/1" [^>]*>#1</a>', p4) is not None and re.search(r'<a href="/items/2" [^>]*>#2</a>', p4) is not None
      and re.search(r'<a href="/items/a2" [^>]*>a2</a>', p4) is not None and f"board#{BID_A} and board-tmp-other#1 are no items" in p4 and "; board#4 is this one" in p4,
      re.findall(r'<ul class="desc">.*?</ul>', p4))
check("superseded by an issue-numbered item: the close names board#1 and links /items/1",
      '<span class="tag t-superseded">Superseded</span>' in p7 and ' · by <a href="/items/1">#1</a>' in p7, re.findall(r'<p class="istate">.*?</p>', p7))
check("the details page lists the items a session owns as board#<n> at /items/<n>", '<a href="/items/1">#1</a>' in U.routing_html("projects/alpha"),
      re.findall(r'<span class="own">.*?</span>', U.routing_html("projects/alpha")))
from starlette.testclient import TestClient
with TestClient(server.mcp.http_app()) as c:
    r1 = c.get("/items/a1", follow_redirects=False); r2 = c.get("/items/g1"); r3 = c.get("/items/a2"); r4 = c.get("/items/g9")
    r5 = c.get("/items/1", follow_redirects=False); r6 = c.get("/items/g1", follow_redirects=False); r7 = c.get("/items/1.html", follow_redirects=False)
    r8 = c.get("/items/9", follow_redirects=False); r9 = c.get("/items/01", follow_redirects=False)
    check("/items/<old id> → 301 to the new id's page /items/<n>; /items/g<n> follows there and renders; a closed item's old page still serves; an unknown id is 404",
          r1.status_code == 301 and r1.headers["location"] == "/items/1" and r2.status_code == 200 and "[home] item a1" in r2.text and r3.status_code == 200 and r4.status_code == 404,
          (r1.status_code, r1.headers.get("location"), r2.status_code, r3.status_code, r4.status_code))
    check("/items/<n> serves the issue-numbered item; /items/g<n> and /items/<n>.html are 301 to /items/<n>; an unknown number and a padded one are 404",
          r5.status_code == 200 and "[home] item a1" in r5.text and "<title>#1 · item a1</title>" in r5.text
          and r6.status_code == 301 and r6.headers["location"] == "/items/1" and r7.status_code == 301 and r7.headers["location"] == "/items/1"
          and r8.status_code == 404 and r9.status_code == 404,
          (r5.status_code, r6.status_code, r6.headers.get("location"), r7.status_code, r7.headers.get("location"), r8.status_code, r9.status_code))
check("the issue link: with [github] sync off an item page shows none, though the map holds the item's issue",
      G.issue_of("g4", STORE) == 4 and ghl(p4) == [] and ghl(r2.text) == [] and ghl(r5.text) == [] and 'class="hgh"' not in p4, (ghl(p4), ghl(r2.text)))
n_before, w_before = F.next, len(writes())
r = G.migrate(STORE, GH, say=lambda s: None)
check("a second run sees no open item outside g/ and creates, posts and moves nothing", r["items"] == 0 and r["created"] == 0 and r["moved"] == 0 and F.next == n_before and len(writes()) == w_before, (r, F.next - n_before, len(writes()) - w_before))
(STORE / "github.json").unlink()
r = G.migrate(STORE, GH, say=lambda s: None)
m = G.load_map(STORE)
check("the map lost: a run rebuilds it from the markers and still creates nothing", r["created"] == 0 and F.next == n_before and m["issues"] == {"g1": 1, "g2": 2, "g3": 3, "g4": 4, "g5": 5}
      and m["aliases"].get("a1") == "g1" and m["aliases"].get("s21") == "g5", (r, m))
snap("migrated")

# ---- 3. the mirror on, by a config reload (no restart): the issue carries the subject, open or closed and the description, nothing else
write_toml(sync=True, issue_ids=False)
changed = server._cfg.reload()
check("a reload turns the mirror on", G.enabled() and "github.sync" in (changed or []), changed)
F.log.clear(); paced0 = len(GH._writes)                 # the pacer's stamps so far: the pace check below reads the ones from here on
out = server._create(subject="[home] made with the mirror on", description=DESC, project="projects/alpha", owner="home-here", next="first step", needs="decision", ask=ASK)
gid = re.search(r"created (\S+)", out).group(1)
check("the create is under the [ids] letter (issue_ids off) and queued one job, sent nothing yet", gid == "s22" and qlen() == 1 and not writes(), (gid, qlen(), writes()))
job = json.loads(G.pending()[0].read_text())
check("a create's job: kind created, urgent (it goes at once), no comment and no parts (the issue itself is the creation)", job["kind"] == "created" and job["gid"] == "s22" and job["urgent"] is True and "comment" not in job and "parts" not in job, job)
r = G.drain(GH, STORE, say=lambda s: None)
check("drain: one POST, the issue exists with the slim body (marker, description, footer) and no label, the map knows it, the queue is empty",
      r == {"done": 1, "left": 0, "down": ""} and F.next == 7 and writes() == [("POST", REPO + "/issues")] and issue(6)["title"] == "[home] made with the mirror on"
      and issue(6)["body"].startswith("<!-- stackshot:s22 -->\n\n" + DESC + "\n\n<sub>Mirrored from [s22](https://board.example.org/items/s22) by ")
      and not any(w in issue(6)["body"] for w in ("###", "first step", ASK)) and issue(6)["labels"] == [] and G.issue_of("s22", STORE) == 6 and not comments(6), (r, F.next, issue(6)))
p22 = ui_render.Board(str(STORE)).item_html("s22")
with TestClient(server.mcp.http_app()) as c:
    r_old = c.get("/items/s12"); r_new = c.get("/items/4")
check("the issue link: with sync on an issue-backed item's page links its issue in the sidebar, https://github.com/<issues_repo>/issues/<n>, in a new tab",
      ghl(r_new.text) == ["o/r/issues/4"] and '<dl class="sgrp"><dt>GitHub</dt><dd><a class="hgh" href="https://github.com/o/r/issues/4" target="_blank" rel="noopener"' in r_new.text
      and r_new.text.index('<aside class="iside"') < r_new.text.index('class="hgh"') < r_new.text.index("</aside>") and 'class="hgh"' not in re.findall(r"<h1>.*?</h1>", r_new.text)[0],
      (ghl(r_new.text), re.findall(r"<aside.*?</aside>", r_new.text)))
check("the issue link: a migrated item reached by its old id (/items/s12 → /items/4) links the issue its alias resolves to",
      r_old.status_code == 200 and "<title>#4 · item s12</title>" in r_old.text and ghl(r_old.text) == ["o/r/issues/4"] and G.issue_of("s12", STORE) == 4, (r_old.status_code, ghl(r_old.text)))
check("the issue link: an item kept under its old id and mirrored by the sync links its own issue", ghl(p22) == ["o/r/issues/6"], ghl(p22))
_ghc = server._cfg.CFG["github"]; _repo = _ghc["issues_repo"]; _ghc["issues_repo"] = ""
check("the issue link: with sync on but no issues_repo set an item page shows none", ghl(ui_render.Board(str(STORE)).item_html("g4")) == [] and ghl(ui_render.Board(str(STORE)).item_html("s22")) == [])
_ghc["issues_repo"] = _repo
# a change to anything the issue does not carry: stored, no job, no call at all
log0 = len(F.log)
server._update("s22", next="second step\nthird step", sender="home-here")
server._update("s22", needs="none", sender="home-here")
server._update("s22", hold=True, wake="2027-01-01", sender="home-here")
server._update("s22", clear_hold=True, sender="home-here")
server.stackshot_confirm("s22", sender="home-here")
server._update("s22", needs="decision", ask=ASK, options=OPTS, due="2026-12-24", sender="home-here")
server._update("s22", work={"text": "migrating the ids"}, sender="home-here")
m22 = rd("s", 22)["metadata"]
check("a change of next, needs, a hold and a wake, the ask and options, the due date, a step status or a confirm is stored and queues no job; GitHub is not called at all",
      m22["next"] == "second step\nthird step\nhome-here: migrating the ids" and "decision" in m22["needs"] and m22["due"] == "2026-12-24" and m22["ask"] == ASK and not m22.get("hold") and qlen() == 0 and len(F.log) == log0, (m22, qlen(), F.log[log0:]))
r = G.drain(GH, STORE, say=lambda s: None)
check("…and a drain with nothing queued sends nothing", r == {"done": 0, "left": 0, "down": ""} and len(F.log) == log0 and issue(6)["labels"] == [] and not comments(6), (r, F.log[log0:]))
server._update("s22", description=D("changed text"), sender="home-here")
job = json.loads(G.pending()[0].read_text())
check("a changed description queues one job (kind changed, not urgent)", qlen() == 1 and job["kind"] == "changed" and job["gid"] == "s22" and not job["urgent"], job)
r = G.drain(GH, STORE, say=lambda s: None)
check("…and goes out as one PATCH of the issue, the new description in the body, no comment", r["done"] == 1 and writes()[-1:] == [("PATCH", REPO + "/issues/6")] and mine(6) == [("PATCH", REPO + "/issues/6")]
      and "- changed text" in issue(6)["body"] and not comments(6) and issue(6)["labels"] == [], (r, mine(6), issue(6)["body"][:120]))
server._update("s22", subject="[home] renamed with the mirror on", sender="home-here"); G.drain(GH, STORE, say=lambda s: None)
check("a new subject is one more PATCH: the title follows, nothing else is sent", issue(6)["title"] == "[home] renamed with the mirror on" and len(mine(6)) == 2 and not comments(6), (issue(6)["title"], mine(6)))
server._update("s22", description=D("changed text"), sender="home-here")
check("the same description written again is no change of the issue: no job", qlen() == 0 and len(mine(6)) == 2, (qlen(), mine(6)))
server.stackshot_complete("s22", outcome="done", reason="it shipped", outcome_text="- Shipped and in use", sender="home-here"); job = json.loads(G.pending()[0].read_text()); G.drain(GH, STORE, say=lambda s: None)
check("a close: urgent, the issue closed as completed; its body is the description the item keeps and then an Outcome section with the outcome text, no comment, no label",
      job["urgent"] is True and issue(6)["state"] == "closed" and issue(6)["state_reason"] == "completed" and "- changed text" in issue(6)["body"]
      and "\n\n## Outcome\n\n- Shipped and in use\n\n<sub>Mirrored from" in issue(6)["body"] and issue(6)["body"].index("- changed text") < issue(6)["body"].index("## Outcome")
      and "it shipped" not in issue(6)["body"] and not comments(6) and issue(6)["labels"] == [], (job, issue(6)))
server._update("s22", status="open", next="again", sender="home-here"); job = json.loads(G.pending()[0].read_text()); G.drain(GH, STORE, say=lambda s: None)
check("a reopen is urgent too and reopens the issue; the reason of the close is not on it, and the Outcome section is gone from the body", job["urgent"] is True and issue(6)["state"] == "open" and not comments(6)
      and "## Outcome" not in issue(6)["body"] and "Shipped and in use" not in issue(6)["body"] and "- changed text" in issue(6)["body"], (job, issue(6)["state"], issue(6)["body"][:200]))
_bo = lambda st, **meta: G.body_of("s22", {"subject": "[home] x", "description": "- Kept background\n- It lives here", "status": st, "metadata": meta})
check("body_of: a closed item with an outcome text gets the Outcome section after its description; the text goes in as stored (ids already rewritten), nothing else changes",
      f"- Kept background\n- It lives here\n\n## Outcome\n\n- Ended with board#{BID_B}\n- Fine\n\n<sub>Mirrored from" in _bo("completed", outcome_text=f"- Ended with board#{BID_B}\n- Fine"), _bo("completed", outcome_text=f"- Ended with board#{BID_B}"))
check("body_of: no section for an open item (a reopen), for a close with no outcome text (stored before the field: its description is the end state) or an empty one",
      all("## Outcome" not in b for b in (_bo("open", outcome_text="- stray"), _bo("completed"), _bo("completed", outcome_text="  "))))
server.stackshot_complete("s22", outcome="dropped", reason="no longer needed", outcome_text="- Not needed after the redesign", sender="home-here"); G.drain(GH, STORE, say=lambda s: None)
check("dropped closes as not planned", issue(6)["state"] == "closed" and issue(6)["state_reason"] == "not_planned" and not comments(6), issue(6))
# the server's own act: a wake that has come releases the hold. The hold and the wake are not on the issue: nothing is sent
it = server._load("g3"); it["metadata"]["wake"] = "2020-01-01"; server._save("g3", it)
log0 = len(F.log)
woke = server._wake_pass()
G.drain(GH, STORE, say=lambda s: None)
check("the wake pass released g3 (the hold is stored away); nothing went to GitHub: no job, no comment, no label", woke and rd("g", 3)["metadata"].get("hold") is None
      and qlen() == 0 and len(F.log) == log0 and not comments(3) and issue(3)["labels"] == [], (woke, qlen(), F.log[log0:]))
# a filing-only rewrite says nothing
it = server._load("g1"); it["metadata"]["idle"] = {"poked": now}; server._save("g1", it)
check("a write that changes nothing a person would call a change (an idle mark) queues no job", qlen() == 0, G.pending())

# ---- 3b. the server's other passes (the item phase 2 prep) change fields the issue does not carry: a release from hold, an after-release, an anchor release and a recycle done send nothing; the closing item's own PATCH is the only write
def made(subject, **kw):
    out = server._create(subject=subject, description=DESC, project="projects/alpha", owner="home-here", next="x", **kw)
    g = re.search(r"created (\S+)", out).group(1); G.drain(GH, STORE, say=lambda s: None); return g, G.issue_of(g, STORE)
# the confirmed pin: an item woken without a `confirmed` field gets one, and nothing goes to GitHub
g_pin, n_pin = made("[home] held without a confirm"); server._update(g_pin, hold=True, wake="2099-01-01", sender="home-here")
f_pin = STORE / g_pin[0] / f"{g_pin[1:]}.json"; j = json.loads(f_pin.read_text()); j.pop("confirmed", None); j["metadata"]["until"] = "2020-01-01"; f_pin.write_text(json.dumps(j))
log0 = len(F.log); server._wake_pass(); G.drain(GH, STORE, say=lambda s: None)
check("a wake that also pins `confirmed` (a re-confirm) is stored and sends nothing", "confirmed" in rd(g_pin[0], int(g_pin[1:])) and rd(g_pin[0], int(g_pin[1:]))["metadata"].get("hold") is None
      and len(F.log) == log0 and not comments(n_pin), (len(F.log) - log0, comments(n_pin)))
# a release by the last `after` closing, and an item that still waits on another
g_rel, n_rel = made("[home] waits on g2", after="g2"); g_two, n_two = made("[home] waits on g1 and g2", after="g1, g2")
w_before = len(writes())
server.stackshot_complete("g2", outcome="done", reason="it is in", description="- The third thing is in", sender="home-here"); G.drain(GH, STORE, say=lambda s: None)
check("the last `after` closing releases the item (stored) and the one that still waits on another keeps its list; GitHub saw one write, the closing item's PATCH, and no comment anywhere",
      rd(g_rel[0], int(g_rel[1:]))["metadata"].get("after") is None and rd(g_two[0], int(g_two[1:]))["metadata"]["after"] == ["g1"]
      and writes()[w_before:] == [("PATCH", REPO + "/issues/2")] and issue(2)["state"] == "closed" and issue(2)["state_reason"] == "completed" and not comments(n_rel) and not comments(n_two) and not comments(2),
      (writes()[w_before:], comments(n_rel), comments(n_two)))
# an anchor release: a held item scoped to an anchor, released by its notice
g_anc, n_anc = made("[home] waits on an anchor"); server._update(g_anc, hold=True, wake="2099-01-01", sender="home-here"); G.drain(GH, STORE, say=lambda s: None)
from stackshot.anchors import anchors as _anc
ANCHOR = "https://github.com/o/other/pull/9"; ast = _anc.load(); _anc.add(ast, "projects/alpha", [ANCHOR], [g_anc], "home-here"); _anc.save(ast)
log0 = len(F.log)
rel = server._anchor_release("projects/alpha", {"kind": "anchor", "anchor": ANCHOR, "to": OWNER, "ruling": "passed", "ruled_at": time.time() + 5, "ts": time.time() + 5, "id": "n-test"}, by="home-here")
G.drain(GH, STORE, say=lambda s: None)
check("an anchor's notice releases the hold (stored); nothing is sent", rel == [g_anc] and rd(g_anc[0], int(g_anc[1:]))["metadata"].get("hold") is None and len(F.log) == log0 and not comments(n_anc), (rel, F.log[log0:]))
# a recycle done: one item waiting for it, one whose hold waited only for it
g_rc, n_rc = made("[home] waits for a recycle"); server._update(g_rc, recycle=True, sender="home-here")
g_rh, n_rh = made("[home] held for a recycle"); server._update(g_rh, recycle=True, sender="home-here"); server._update(g_rh, hold=True, sender="home-here")
G.drain(GH, STORE, say=lambda s: None); log0 = len(F.log)
r = server._recycled("testbox", "recycle", 0, "ok", []); G.drain(GH, STORE, say=lambda s: None)
check("a recycle done clears the waits and releases the held one (stored); nothing is sent", sorted(r["cleared"]) == sorted([g_rc, g_rh]) and len(F.log) == log0 and not comments(n_rc) and not comments(n_rh)
      and issue(n_rh)["labels"] == [], (r, F.log[log0:]))
check("the queue is empty after the passes", qlen() == 0, G.pending())

# ---- 3c. a tool write without a sender: refused while the mirror is on, never credited to the owner
g_ns, n_ns = made("[home] written without a sender")
f_ns = STORE / g_ns[0] / f"{g_ns[1:]}.json"; before_ns = f_ns.read_bytes(); log_ns = len(F.log)   # F.log is not cleared: the pace check below counts it
HINT = ("Refused: pass sender=<your session name or id>", "the GitHub mirror", "must name who made it")
refused("mirror on: an update without a sender is refused, with the sender hint and why", lambda: server.stackshot_update(g_ns, next="nobody's step"), *HINT)
refused("mirror on: a blank sender is no sender", lambda: server.stackshot_update(g_ns, next="nobody's step", sender="  "), *HINT)
refused("mirror on: a confirm without a sender is refused", lambda: server.stackshot_confirm(g_ns), *HINT)
refused("mirror on: a complete without a sender is refused", lambda: server.stackshot_complete(g_ns, outcome="done", reason="it is in", description="- In"), *HINT)
check("the refusals changed nothing: the file as it was, no job queued, nothing sent", f_ns.read_bytes() == before_ns and qlen() == 0 and len(F.log) == log_ns, (qlen(), F.log[log_ns:]))
check("the tool descriptions say sender is required while the mirror is on", all(server._SENDER_MIRROR.strip() in d for d in (server._UPDATE_DESC, server._COMPLETE_DESC)))
server.stackshot_update(g_ns, next="home-here: the sender's step", sender="home-here"); G.drain(GH, STORE, say=lambda s: None)
check("with a sender the update goes through (a next line is not on the issue: no job, no call)", rd(g_ns[0], int(g_ns[1:]))["metadata"]["next"] == "home-here: the sender's step" and qlen() == 0 and len(F.log) == log_ns, (qlen(), F.log[log_ns:]))
server.stackshot_confirm(g_ns, sender="home-here")
check("with a sender the confirm goes through", qlen() == 0 and len(F.log) == log_ns)
r_due = server._recycle_due("testbox", item=g_ns); G.drain(GH, STORE, say=lambda s: None)
check("the client API's recycle-due (no session sender) is not refused", r_due["items"][0]["action"] == "set" and qlen() == 0, r_due)
server.stackshot_complete(g_ns, outcome="done", reason="it is in", description="- In", sender="home-here"); G.drain(GH, STORE, say=lambda s: None)
check("with a sender the complete goes through: the issue is closed, still no comment", issue(n_ns)["state"] == "closed" and not comments(n_ns), (issue(n_ns)["state"], comments(n_ns)))
check("the mirror has posted no comment on any issue so far", all(not i["_comments"] for i in F.issues.values()), [(n_, len(i["_comments"])) for n_, i in F.issues.items() if i["_comments"]])

# ---- 3d. step statuses: a change to a step's status is not on the issue (no comment, no call); History reads it from the store's git
g_w, n_w = made("[home] with step statuses"); snap("work item"); owed_w = server._owed_load(); log_w = len(F.log)
server._update(g_w, work={"text": "migrating the ids"}, sender="home-here"); G.drain(GH, STORE, say=lambda s: None); snap("work defined")
server._update(g_w, work={"text": "PR 83 up", "state": "in progress"}, sender="home-here"); G.drain(GH, STORE, say=lambda s: None); snap("work in progress")
server._update(g_w, work={"state": "done"}, sender="home-here"); G.drain(GH, STORE, say=lambda s: None); snap("work done")
stw = [x for x in rd(g_w[0], int(g_w[1:]))["metadata"]["steps"] if x["text"].endswith("migrating the ids")]
check("a step status set, changed and marked done: one step, stored with its status, no job, no call, no comment (the issue's body and labels as they were)",
      len(stw) == 1 and stw[0]["status"] == "done" and stw[0]["tag"]["text"] == "PR 83 up" and stw[0]["tag"]["state"] == "done" and "work" not in rd(g_w[0], int(g_w[1:]))["metadata"]
      and qlen() == 0 and len(F.log) == log_w and not comments(n_w) and issue(n_w)["labels"] == [] and "### Work" not in issue(n_w)["body"], (qlen(), F.log[log_w:], stw))
bw = ui_render.Board(str(STORE)); evs, _more = bw.item_events(bw.item(g_w))
wev = [h for _t, k, h in evs if k == "work"]
check("the item page's History has one line for the step with its three status updates folded under it, from the store's git",
      len(wev) == 1 and "step done: " in wev[0] and "3 status updates" in wev[0] and "migrating the ids" in wev[0] and "PR 83 up" in wev[0], evs)
check("a step status owes no page", server._owed_load() == owed_w, server._owed_load())
refused("mirror on: a status write without a sender is refused like any other", lambda: server.stackshot_update(g_w, work="another line"), *HINT)
check("the queue is empty after the work writes, and no label, field, blocked-by or comment call has reached GitHub so far", qlen() == 0 and F.forbidden == [], (G.pending(), F.forbidden))

# ---- 4. an outage, a rate limit, a refusal, the marker guard, the pace
# A queued job is rewritten (marked tried, error noted) while another thread or process may read the queue: the rewrite goes through
# ghsync.write_atomic (a dot-named temp file in the same folder, then os.replace), so a reader never catches it half-written
# (a reader got a JSONDecodeError from the in-place write_text). The spy reads the target at the moment of the replace.
_replaced = []; _real_replace = os.replace
def _spy_replace(src, dst):
    s_, d_ = pathlib.Path(src), pathlib.Path(dst)
    try: seen = json.loads(d_.read_text(encoding="utf-8")) if d_.exists() else None
    except ValueError: seen = "TORN"
    _replaced.append((s_, d_, seen, s_.read_text(encoding="utf-8")))
    return _real_replace(src, dst)
F.down = True; n_out = F.next
out = server._update("g1", description=D("while GitHub is down"), sender="home-here")
check("the tool answers as always while GitHub is down", out.startswith("updated board#1."), out[:80])
_q0 = G.pending()[0]; os.replace = _spy_replace
try:
    r = G.drain(GH, STORE, say=lambda s: None)
finally:
    os.replace = _real_replace
job = json.loads(G.pending()[0].read_text())
_mine = [x for x in _replaced if x[1] == _q0]
check("drain stops at the outage; the job stays, marked tried", r["done"] == 0 and r["left"] == 1 and "503" in r["down"] and job["tried"] == 1, (r, job))
check("the job rewrite is atomic: a dot-named temp file in the queue folder replaces it, and the old file was whole until then",
      bool(_mine) and all(s_.parent == _q0.parent and s_.name.startswith(".") and d_ == _q0 and seen is not None and seen != "TORN" and json.loads(txt)["tried"] >= 1 for s_, d_, seen, txt in _mine)
      and not [f for f in _q0.parent.iterdir() if f.name.endswith(".tmp")], (_mine, list(_q0.parent.iterdir())))
_wa = pathlib.Path(_scratch.mkdtemp(prefix="gs-atomic-"))
_f = _wa / "job.json"; _f.write_text('{"old": true}\n', encoding="utf-8")
G.write_atomic(_f, G._job_text({"new": "é"}))
_ok = json.loads(_f.read_text(encoding="utf-8")) == {"new": "é"} and [x.name for x in _wa.iterdir()] == ["job.json"]
def _boom(src, dst): raise OSError("disk full")
os.replace = _boom
try:
    try: G.write_atomic(_f, '{"new": 2}\n'); _raised = False
    except OSError: _raised = True
finally:
    os.replace = _real_replace
check("write_atomic: the new text replaces the old whole; a write that fails leaves the old file and no temp file", _ok and _raised
      and json.loads(_f.read_text(encoding="utf-8")) == {"new": "é"} and [x.name for x in _wa.iterdir()] == ["job.json"], [x.name for x in _wa.iterdir()])
F.down = False; F.ratelimit = True
r = G.drain(GH, STORE, say=lambda s: None)
check("a rate limit is an outage too, with the reset read", r["done"] == 0 and r["left"] == 1 and "403" in r["down"], r)
F.ratelimit = False
r = G.drain(GH, STORE, say=lambda s: None)
check("GitHub back: the job drains, the body carries the update, no second issue", r == {"done": 1, "left": 0, "down": ""} and "while GitHub is down" in issue(1)["body"] and F.next == n_out, (r, F.next))
# the marker guard: a create whose answer was lost (the issue exists, the map does not know) makes no second issue
out = server._create(subject="[home] answer lost", description=DESC, project="projects/alpha", owner="home-here", next="x")
g_lost = re.search(r"created (\S+)", out).group(1)
G.drain(GH, STORE, say=lambda s: None)
n_lost = G.issue_of(g_lost, STORE)
mp = G.load_map(STORE); mp["issues"].pop(g_lost); G.save_map(mp, STORE)
server._update(g_lost, description=D("answer lost y"), sender="home-here")
p = G.pending()[0]; j = json.loads(p.read_text()); j["tried"] = 1; p.write_text(json.dumps(j))
r = G.drain(GH, STORE, say=lambda s: None)
check("a job tried before looks for its marker first: the issue is found, none made twice", r["done"] == 1 and F.next == n_lost + 1 and G.issue_of(g_lost, STORE) == n_lost and "- answer lost y" in issue(n_lost)["body"], (r, F.next, n_lost))
F.refuse_next = 422
server._update(g_lost, description=D("refused"), sender="home-here")
_replaced.clear(); os.replace = _spy_replace
try:
    r = G.drain(GH, STORE, say=lambda s: None)
finally:
    os.replace = _real_replace
failed = list(G.failed_dir().glob("*.json"))
check("a refusal moves the job to failed/ with the reason; the queue goes on", r["done"] == 0 and r["left"] == 0 and len(failed) == 1 and "422" in json.loads(failed[0].read_text())["failed"], (r, failed))
check("…and the failed copy is written atomically too (a dot-named temp file in failed/, replaced into place; none left behind)",
      [(s_.parent, s_.name.startswith("."), d_) for s_, d_, _seen, _txt in _replaced if d_.parent == G.failed_dir()] == [(G.failed_dir(), True, failed[0])]
      and not [f for f in G.failed_dir().iterdir() if f.name.endswith(".tmp")], (_replaced, list(G.failed_dir().iterdir())))
# The pace is a promise about the client's own stamps (GitHub._throttle sleeps out the interval, stamps, then the write
# leaves), so that is what the check reads. The fake's handler clock sees the stamp plus the transport (a connect, an accept, a
# thread per connection), which on a loaded box drifts by tens of ms from one write to the next: CI run 9000005 saw two
# handler stamps 0.028 apart, the pace being 0.05. One stamp per write that reached GitHub (a write that skipped the pacer
# would be a missing stamp), and never two closer than the interval.
stamps = list(GH._writes)[paced0:]
check("every write that reached GitHub went through the pacer: one stamp per POST or PATCH", len(stamps) == len(writes()), (len(stamps), len(writes())))
gaps = [b - a for a, b in zip(stamps, stamps[1:])]
check("the writes are paced: never two closer than the interval", gaps and min(gaps) >= GH.pace, (len(gaps), min(gaps) if gaps else None))
check("reads are not paced: a listing of 100 per page asked for state=all", any(m_ == "GET" and p_ == REPO + "/issues" for m_, p_, t in F.log))

# the worker thread (the server starts it at boot): a job drains on its own, without a drain() call
stop = threading.Event(); th = threading.Thread(target=G.worker_loop, args=(stop,), daemon=True); th.start()
server._update("g1", description=D("through the worker"), sender="home-here")
for _ in range(100):
    if qlen() == 0 and "through the worker" in issue(1)["body"]: break
    time.sleep(0.05)
check("the worker thread drains a job as it arrives: the issue carries the new description, no comment",
      qlen() == 0 and "- through the worker" in issue(1)["body"] and not comments(1), (qlen(), comments(1)[-1:]))
stop.set(); G._EVENT.set(); th.join(timeout=2)

# ---- 4b. the rate limit: record the headers, wait for the reset probing for room, read with ETags
check("a call's X-RateLimit headers are kept: the newest in memory and <state>/github/ratelimit.json",
      G.rate_seen().get("limit") == 5000 and G.rate_seen().get("resource") == "core" and json.loads(G._cfg.state("github", G.RATE_NAME).read_text())["core"]["limit"] == 5000, (G.rate_seen(), ))
F.ratelimit = True
server._update("g1", description=D("meets the limit"), sender="home-here")
r = G.drain(GH, STORE, say=lambda s: None)
check("a drain that meets the limit hands the reset back as retry_after (about 60 s), and the headers of the 403 are recorded",
      r["down"] and 30 < r.get("retry_after", 0) <= 61 and G.rate_seen().get("status") == 403 and G.rate_seen().get("remaining") == 0, (r, G.rate_seen()))
F.ratelimit = False
class _Room:                                     # a client whose bucket has room on the third look
    def __init__(self): self.looks = 0
    def core_left(self): self.looks += 1; return 100 if self.looks >= 3 else 0
G.RATE_PROBE_S = 0.05
rm = _Room(); t0 = time.monotonic(); waited = G.wait_rate_limit(rm, 600)
check("wait_rate_limit: a reset 10 min away is not waited out when the bucket has room earlier: resumes at the third look", rm.looks == 3 and waited < 2, (rm.looks, waited))
rm = _Room(); rm.core_left = lambda: 0; waited = G.wait_rate_limit(rm, 0.2)
check("wait_rate_limit: with no room it waits to the reset and two seconds, then returns", 2.0 <= waited < 4.0, waited)
ev = threading.Event(); ev.set(); rm = _Room(); waited = G.wait_rate_limit(rm, 600, ev)
check("wait_rate_limit: a stop event ends the wait at once", waited < 1 and rm.looks == 0, (waited, rm.looks))
check("a primary limit (remaining 0, no Retry-After, core) is marked primary in the drain's answer", r.get("primary") is True, r)
# a secondary limit (Retry-After) is not a primary one: the full time is waited whatever the core bucket says
F.ratelimit = False; F.secondary = True
sec = server._update("g1", description=D("meets a secondary limit"), sender="home-here")
r2 = G.drain(GH, STORE, say=lambda s: None)
check("a 403 with Retry-After is not primary: retry_after is GitHub's 1 s and primary False", r2.get("primary") is False and r2.get("retry_after") == 1.0, r2)
F.secondary = False
rm = _Room(); rm.looks = 5; t0 = time.monotonic(); waited = G.wait_rate_limit(rm, 0.2, None, False)
check("wait_rate_limit: not primary, plenty of core left (the probe would say 100): waits the full retry-after and two seconds and never probes", waited >= 2.2 and rm.looks == 5, (waited, rm.looks))
# a resource other than core is not primary either, and one resource's record does not overwrite another's
G._RATE["saved"] = 0.0
G.note_rate({"x-ratelimit-limit": "30", "x-ratelimit-remaining": "29", "x-ratelimit-used": "1", "x-ratelimit-reset": "1", "x-ratelimit-resource": "search"}, 200)
rf = json.loads(G._cfg.state("github", G.RATE_NAME).read_text())
check("ratelimit.json keeps a record per resource: search does not overwrite core",
      G.rate_seen("search").get("limit") == 30 and G.rate_seen("core").get("limit") == 5000 and rf["search"]["limit"] == 30 and rf["core"]["limit"] == 5000, (rf, G.rate_seen()))
try: GH.request("GET", "/nothing-found-here"); gd = None
except G.GitHubError as e: gd = e
check("a plain 404 is a GitHubError, not a GitHubDown (no primary flag to read)", gd is not None and not isinstance(gd, G.GitHubDown), gd)
# the threads survive a failing wait: the worker and the reader fall back to their backoff and stay alive
class _Boom(Exception): pass
calls_w = []
def boom_wait(*a, **k): calls_w.append((a[1], a[3] if len(a) > 3 else k.get("primary"))); raise _Boom("probe broke")
real_wait, real_drain, real_poll = G.wait_rate_limit, G.drain, G.poll_comments
G.wait_rate_limit = boom_wait
G.drain = lambda *a, **k: {"done": 0, "left": 1, "down": "403: limit", "retry_after": 5.0, "primary": True}
stop_w = threading.Event(); th_w = threading.Thread(target=G.worker_loop, args=(stop_w,), daemon=True); th_w.start(); G._EVENT.set()
for _ in range(60):
    if calls_w: break
    time.sleep(0.05)
time.sleep(0.2)
check("the worker survives a wait that raises: the thread is alive, the wait was asked with the reset and the primary flag", th_w.is_alive() and calls_w[:1] == [(5.0, True)], (th_w.is_alive(), calls_w))
stop_w.set(); G._EVENT.set(); G.drain = real_drain
def limited_poll(*a, **k): raise G.GitHubDown(403, "API rate limit exceeded", 5.0, True)
G.poll_comments = limited_poll; calls_w.clear()
stop_r = threading.Event(); th_r = threading.Thread(target=G.comments_loop, args=(stop_r,), daemon=True); th_r.start()
for _ in range(60):
    if calls_w: break
    time.sleep(0.05)
time.sleep(0.2)
check("the comments reader survives a wait that raises: the thread is alive and backs off", th_r.is_alive() and calls_w[:1] == [(5.0, True)], (th_r.is_alive(), calls_w))
stop_r.set(); th_r.join(timeout=3)
check("…and ends when told to", not th_r.is_alive())
G.wait_rate_limit, G.poll_comments = real_wait, real_poll
# the probe itself failing (a GitHubError, or a garbled answer) is a look not made, not a dead thread
class _BadProbe:
    def __init__(self): self.n = 0
    def core_left(self): self.n += 1; raise (G.GitHubError(500, "x") if self.n == 1 else ValueError("garbled"))
bp = _BadProbe(); waited = G.wait_rate_limit(bp, 0.2)
check("wait_rate_limit: a probe that raises (GitHubError, then ValueError) does not end the wait early or raise", bp.n >= 1 and 2.0 <= waited < 4.0, (bp.n, waited))
# the worker: the limit lifts early (the reset says 60 s); it drains within a probe or two, not after the reset or a backoff
G.RATE_PROBE_S = 0.2
F.ratelimit = True
stop = threading.Event(); th = threading.Thread(target=G.worker_loop, args=(stop,), daemon=True); th.start()
G._EVENT.set()
def _tried():
    # the worker rewrites the job in place (truncate, then write): a read between the two sees an empty file, so it is a look not made
    try: return bool(json.loads(G.pending()[0].read_text()).get("tried"))
    except (IndexError, ValueError, OSError): return False
for _ in range(100):
    if _tried(): break
    time.sleep(0.05)
tried = _tried()
F.ratelimit = False
for _ in range(100):
    if qlen() == 0 and "meets a secondary limit" in issue(1)["body"]: break
    time.sleep(0.05)
check("the worker meets the limit, waits probing /rate_limit, and drains as soon as the bucket has room, well before the reset it was told",
      tried and qlen() == 0 and "meets a secondary limit" in issue(1)["body"], (tried, qlen()))
stop.set(); G._EVENT.set(); th.join(timeout=3)
G.RATE_PROBE_S = 60.0
# a read with an ETag: the second asks If-None-Match, GitHub answers 304 (not counted), the first answer comes back
F.not_modified = 0
rows1 = GH.list_comments_since(EPOCH_ISO); rows2 = GH.list_comments_since(EPOCH_ISO)
check("list_comments_since sends the ETag back: the second read is a 304 answered from the kept rows", rows1 == rows2 and F.not_modified == 1 and GH.cached == 1, (F.not_modified, GH.cached))
cx = F.comment(1, "a new comment changes the listing", login="someone")
rows3 = GH.list_comments_since(EPOCH_ISO)
check("…a changed listing is a 200 with the new rows, not the kept ones", len(rows3) == len(rows1) + 1 and F.not_modified == 1, (len(rows1), len(rows3), F.not_modified))
rows3[0]["body"] = "mutated by a caller"; rows4 = GH.list_comments_since(EPOCH_ISO); F.delete(cx["id"])
check("…the kept answer is a copy: a caller changing the rows it got leaves the next (304) read whole", F.not_modified == 2 and rows4[0]["body"] != "mutated by a caller", F.not_modified)

# ---- 5. the id switch: a new item's id is its issue number
seq = (STORE / "next-id").read_text().strip()
write_toml(sync=True, issue_ids=True); server._cfg.reload()
check("a reload turns the id switch on", G.issue_ids())
F.log.clear(); nxt = F.next
out = server._create(subject="[home] numbered by GitHub", description=DESC, project="projects/alpha", owner="home-here", next="x", needs="external")
check("the create waited for the issue: the id is its number, shown board#<n>, the file under g/", out.startswith(f"created board#{nxt} —") and (STORE / f"g/{nxt}.json").exists()
      and rd("g", nxt)["id"] == str(nxt) and issue(nxt)["title"] == "[home] numbered by GitHub" and G.issue_of(f"g{nxt}", STORE) == nxt, (out[:100], F.next))
check("get takes board#<n>", server.stackshot_get(f"board#{nxt}").startswith(f"board#{nxt} [open] [home] numbered by GitHub"))
r = G.drain(GH, STORE, say=lambda s: None)
check("the queued create then only brings the body up (the marker), no comment", r["done"] == 1 and f"<!-- stackshot:g{nxt} -->" in issue(nxt)["body"] and not comments(nxt), (r, issue(nxt)["body"][:60], comments(nxt)))
check("the [ids] letter sequence was not touched", (STORE / "next-id").read_text().strip() == seq, (STORE / "next-id").read_text())
server._update(f"#{nxt}", description=D("by the bare form"), sender="home-here"); G.drain(GH, STORE, say=lambda s: None)
check("update by #<n>: the body follows, no comment", "- by the bare form" in issue(nxt)["body"] and not comments(nxt), (issue(nxt)["body"][-80:], comments(nxt)))

# ---- 6. a create during an outage (the item phase 2 prep): a local id, queued, re-keyed to its issue number when GitHub answers
check("the local letter is l by default, and l<n> reads as a local id", G.local_letter() == "l" and G.is_local("l7") and not G.is_local("g7") and not G.is_local("l"))
# the temporary id as a person reads it: the preface is the instance machine, "board-tmp-<machine>#<n>"
check("[instance] machine names the temporary form: l3 reads board-tmp-boxa#3, its page board-tmp-boxa-3; both forms read back as l3, another machine's prefix and a padded number do not",
      G.machine() == "boxa" and G.shown("l3") == "board-tmp-boxa#3" and G.href_id("l3") == "board-tmp-boxa-3" and G.norm("board-tmp-boxa#3") == "l3"
      and G.norm("BOARD-TMP-BOXA-3") == "l3" and G.norm("board-tmp-other#3") == "" and G.norm("board-tmp-local#3") == "" and G.norm("board-tmp-boxa#03") == ""
      and G.href_id("g5") == "5" and G.shown("g5") == "board#5" and G.shown("s5") == "s5" and G.href_id("s5") == "s5",
      (G.machine(), G.shown("l3"), G.href_id("l3"), G.norm("board-tmp-boxa#3"), G.norm("board-tmp-other#3")))
_inst = server._cfg.CFG["instance"]; _kept = _inst.pop("machine")
check("with [instance] machine unset a temporary id reads board-tmp-local#<n>, at /items/board-tmp-local-<n>",
      G.machine() == "local" and G.shown("l1") == "board-tmp-local#1" and G.href_id("l1") == "board-tmp-local-1" and G.norm("board-tmp-local#1") == "l1"
      and G.norm("board-tmp-boxa#1") == "", (G.machine(), G.shown("l1")))
_inst["machine"] = "Box_1"
check("a machine that is not a lowercase name of letters, digits and hyphens reads as local", G.machine() == "local" and G.shown("l1") == "board-tmp-local#1", G.machine())
_inst["machine"] = _kept
check("[instance] machine is restart-only", server._cfg._restart_only("instance.machine") is not None)
F.down = True; nxt2 = F.next
out = server._create(subject="[home] during an outage", description=DESC, project="projects/alpha", owner="home-here", next="x")
check("a create during an outage is not refused: the item is l1 in the store and board-tmp-boxa#1 in the reply (which says it is temporary), the file is under l/, the create is queued, no issue yet",
      out.startswith("created board-tmp-boxa#1 — ") and "board-tmp-boxa#1 is a temporary id" in out and "board-tmp-boxa#1 stays as an alias" in out
      and not re.search(r"(?<![\w/-])l1\b", out) and (STORE / "l/1.json").exists() and rd("l", 1)["id"] == "1" and qlen() == 1
      and json.loads(G.pending()[0].read_text())["kind"] == "created" and F.next == nxt2 and G.load_map(STORE).get("local_last") == 1, (out[:400], qlen(), F.next))
check("the create reply, as the connector sends it, links board-tmp-boxa#1 to /items/board-tmp-boxa-1",
      lk(out).startswith(f"created {L('board-tmp-boxa#1', 'board-tmp-boxa-1')} — ") and "/items/l1" not in lk(out), lk(out)[:200])
check("a bare l1 in a reply is written and linked as board-tmp-boxa#1; a written-out one copied back into a write is stored as written",
      lk("waits on l1") == f"waits on {L('board-tmp-boxa#1', 'board-tmp-boxa-1')}" and lk("see board-tmp-boxa#1") == f"see {L('board-tmp-boxa#1', 'board-tmp-boxa-1')}"
      and lk("see board-tmp-other#1") == "see board-tmp-other#1" and server._unlink_ids(f"see {L('board-tmp-boxa#1', 'board-tmp-boxa-1')}") == "see board-tmp-boxa#1",
      (lk("waits on l1"), lk("see board-tmp-other#1")))
out2 = server._create(subject="[home] waits on the first", description=DESC, project="projects/alpha", owner="home-here", next="x", after="board-tmp-boxa#1")
check("a second one is l2, and its after, given as board-tmp-boxa#1, names l1", out2.startswith("created board-tmp-boxa#2 — ") and rd("l", 2)["metadata"]["after"] == ["l1"]
      and G.load_map(STORE)["local_last"] == 2, (out2[:80], rd("l", 2)["metadata"]))
server._update("board-tmp-boxa#1", description=D("edited while down"), sender="home-here")
ast = _anc.load(); _anc.add(ast, "projects/alpha", ["https://github.com/o/other/issues/19"], ["l1"], "home-here"); _anc.save(ast)
with TestClient(server.mcp.http_app()) as c:
    r1 = c.get("/items/board-tmp-boxa-1", follow_redirects=False); r0 = c.get("/items/l1", follow_redirects=False)
    r5 = c.get("/items/board-tmp-boxa-1/", follow_redirects=False); r6 = c.get("/items/board-tmp-other-1", follow_redirects=False)
check("while temporary, the tools take board-tmp-boxa#1, board-tmp-boxa-1 and l1 alike, and update by board-tmp-boxa#1 reached it",
      all(server.stackshot_get(x).startswith("board-tmp-boxa#1 [open] [home] during an outage") for x in ("board-tmp-boxa#1", "board-tmp-boxa-1", "l1"))
      and all(_model_ids._norm_id(x) == "l1" for x in ("board-tmp-boxa#1", "board-tmp-boxa-1", "l1")) and rd("l", 1)["description"] == D("edited while down"),
      [server.stackshot_get(x)[:50] for x in ("board-tmp-boxa#1", "board-tmp-boxa-1", "l1")])
check("the issue link: a temporary item (no issue yet) shows none on its page, with sync on", G.enabled() and r1.status_code == 200 and ghl(r1.text) == [], ghl(r1.text))
check("while temporary, /items/board-tmp-boxa-1 serves the item; /items/l1 and the trailing-slash form → 301 there; another machine's prefix is 404",
      r1.status_code == 200 and "[home] during an outage" in r1.text
      and r0.status_code == 301 and r0.headers["location"] == "/items/board-tmp-boxa-1" and r5.status_code == 301 and r5.headers["location"] == "/items/board-tmp-boxa-1"
      and r6.status_code == 404, (r1.status_code, r0.status_code, r0.headers.get("location"), r5.status_code, r6.status_code))
# a notice pushed to a session names a temporary item as it is shown and links its item page (the builders called
# directly: a write here would queue a fourth job)
told = []; server._tell_woken = lambda gid, owner, note, tag="wake": told.append((gid, owner, note, tag))
it_l1 = rd("l", 1); it_l1["metadata"] = {**it_l1["metadata"], "needs": ["home-other"], "mover": "home-here"}
server._wake_notify("l1", it_l1, "woke (wake 2020-01-01)")
_pr, _fs = server._anc.pilot_root, server._front_keeper
server._anc.pilot_root = lambda p: p; server._front_keeper = lambda who, project="": (True, "home-keeper")
try:
    server._tell_owner("l1", rd("l", 1), "was completed (done: closed by another session)", "home-other")   # a front agent's item: its keeper hears the close
finally:
    server._anc.pilot_root, server._front_keeper = _pr, _fs
TMP_URL = "https://board.example.org/items/board-tmp-boxa-1"
check("a wake notice for a temporary item names board-tmp-boxa#1 and links /items/board-tmp-boxa-1; the stderr tag keeps l1",
      any(t[0] == "l1" and t[1] == "home-other" and t[2].startswith("[stackshot] board-tmp-boxa#1 woke (wake 2020-01-01), ") and re.search(re.escape(f"→ {TMP_URL}") + r"( · notice [0-9a-f]{6})?$", t[2])
          and not re.search(r"(?<![\w/-])l1\b", t[2]) for t in told), told)
check("an owner notice (a close on a front agent's item, to its keeper) for a temporary item names board-tmp-boxa#1 and links /items/board-tmp-boxa-1",
      any(t[1] == "home-keeper" and t[3] == "owner" and t[2].startswith("[stackshot] board-tmp-boxa#1 (mover home-here, a front agent) was completed (done: closed by another session) by home-other: ")
          and t[2].endswith(f"→ {TMP_URL}") for t in told), told)
server._tell_woken = lambda *a, **k: None
r = G.drain(GH, STORE, say=lambda s: None)
check("the queue waits out the outage with the three jobs", r["done"] == 0 and r["left"] == 3 and (STORE / "l/1.json").exists(), r)
told = []; server._tell_woken = lambda gid, owner, note, tag="wake": told.append((gid, owner, note, tag))
F.down = False; F.log.clear()
r = G.drain(GH, STORE, say=lambda s: None)
n1, n2 = nxt2, nxt2 + 1
m = G.load_map(STORE)
check("GitHub back: l1 became the next issue and was re-keyed to g<n>: the file moved with its id, l/1.json is gone, the map holds the issue and the alias",
      r == {"done": 3, "left": 0, "down": ""} and (STORE / f"g/{n1}.json").exists() and not (STORE / "l/1.json").exists() and rd("g", n1)["id"] == str(n1)
      and m["issues"].get(f"g{n1}") == n1 and m["aliases"].get("l1") == f"g{n1}" and "l1" not in m["issues"] and G.issue_of("l1", STORE) == n1, (r, m, sorted(os.listdir(STORE / "g"))))
check("the issue: the machine marker still says it was l1 (parseable as before), and the body carries the update made during the outage; no comment",
      f"<!-- stackshot:g{n1} (was l1) -->" in issue(n1)["body"] and G.MARK_RX.search(issue(n1)["body"]).groups() == (f"g{n1}", "l1")
      and "- edited while down" in issue(n1)["body"] and not comments(n1), (issue(n1)["body"][:80], comments(n1)))
check("l2 followed as the issue after, and its after list now names g<n>", (STORE / f"g/{n2}.json").exists() and not (STORE / "l/2.json").exists()
      and rd("g", n2)["metadata"]["after"] == [f"g{n1}"] and m["aliases"].get("l2") == f"g{n2}", (rd("g", n2)["metadata"], issue(n2)["body"][:200]))
with TestClient(server.mcp.http_app()) as c:
    r1 = c.get("/items/l1", follow_redirects=False); r2 = c.get(f"/items/g{n1}"); r3 = c.get("/items/board-tmp-boxa-1", follow_redirects=False)
check("lookups by l1, board-tmp-boxa#1 and board-tmp-boxa-1 resolve to the item: _norm_id, get (shown board#<n>), and /items/l1 and /items/board-tmp-boxa-1 → 301 to its page /items/<n>",
      all(_model_ids._norm_id(x) == f"g{n1}" and server.stackshot_get(x).startswith(f"board#{n1} [open] [home] during an outage") for x in ("l1", "board-tmp-boxa#1", "board-tmp-boxa-1"))
      and server._path("l1") == STORE / f"g/{n1}.json"
      and r1.status_code == 301 and r1.headers["location"] == f"/items/{n1}" and r3.status_code == 301 and r3.headers["location"] == f"/items/{n1}" and r2.status_code == 200,
      (r1.status_code, r1.headers.get("location"), r3.status_code, r3.headers.get("location"), r2.status_code))
check("the issue link: once re-keyed to its issue number the item's page links that issue", ghl(r2.text) == [f"o/r/issues/{n1}"], ghl(r2.text))
check("the anchor scoped to l1 now names g<n>", any(e["url"].endswith("/issues/19") and e["items"] == [f"g{n1}"] for e in _anc.load().get("projects/alpha", [])), _anc.load())
check("the owner was told the new id in one plain line, through the owner-notice path: board-tmp-boxa#1 is now board#<n>, with the new page's link",
      any(t[0] == f"g{n1}" and t[1] == OWNER and t[2].startswith(f"[stackshot] board-tmp-boxa#1 is now board#{n1} (") and "board-tmp-boxa#1 still names it" in t[2]
          and t[2].endswith(f"https://board.example.org/items/{n1}") and t[3] == "owner" for t in told) and len(told) == 2, told)
server._tell_woken = lambda *a, **k: None
out = server._create(subject="[home] after the outage", description=DESC, project="projects/alpha", owner="home-here", next="x")
check("with GitHub up a create takes its issue number straight away, no local id", out.startswith(f"created board#{nxt2 + 2} — ")
      and not list((STORE / "l").glob("*.json")) and G.load_map(STORE)["local_last"] == 2, (out[:60], list((STORE / "l").glob("*.json"))))
G.drain(GH, STORE, say=lambda s: None)
# the counter survives a restart: a fresh process allocates from the map, not from memory
sub = subprocess.run([sys.executable, "-c", f"import sys, pathlib; sys.path.insert(0, {STACK!r}); import ghsync; print(ghsync.allocate_local(pathlib.Path({str(STORE)!r})))"],
                     capture_output=True, text=True, env=os.environ, timeout=60)
check("the local counter is not reused after a restart: a fresh process hands out l3", sub.stdout.strip() == "l3" and G.load_map(STORE)["local_last"] == 3, (sub.stdout, sub.stderr[-300:]))
# a re-key a crash cut short (the map saved, the old file left behind) is finished by the next job
server._create(subject="[home] cut short", description=DESC, project="projects/alpha", owner="home-here", next="x"); G.drain(GH, STORE, say=lambda s: None)
n_cut = F.next - 1; stale = STORE / "l/9.json"; stale.write_text(json.dumps({**rd("g", n_cut), "id": "9", "updated": rd("g", n_cut)["updated"] - 100}))
mp = G.load_map(STORE); mp["aliases"]["l9"] = f"g{n_cut}"; mp["local_last"] = 9; G.save_map(mp, STORE)
G.enqueue({"ts": time.time(), "gid": "l9", "kind": "changed", "comment": "[author: home-here · x]\nnext:\n> y"}); r = G.drain(GH, STORE, say=lambda s: None)
check("a stale old file after a cut-short re-key is removed by the next job, the newer file kept", r["done"] == 1 and not stale.exists() and rd("g", n_cut)["id"] == str(n_cut)
      and F.next == n_cut + 1 and not comments(n_cut), (r, stale.exists(), F.next))

# ---- 6b. notices pushed to sessions name an issue-numbered item as it is shown, board#<n>; the stderr tag keeps g<n>
told = []; server._tell_woken = lambda gid, owner, note, tag="wake": told.append((gid, owner, note, tag))
num = lambda g: int(g[1:])
mk = lambda subject, **kw: G.norm(made(subject, **kw)[0])   # the reply says board#<n>; the store id is g<n>
# a wake: an item on hold whose wake has come
g_wk = mk("[home] held until a wake"); server._update(g_wk, hold=True, wake="2099-01-01", sender="home-here")
f_wk = STORE / g_wk[0] / f"{g_wk[1:]}.json"; j = json.loads(f_wk.read_text())      # the wake come, and a session in needs (the notice with a link)
j["metadata"].update(until="2020-01-01", needs=["home-other"], mover="home-here"); f_wk.write_text(json.dumps(j))
told.clear(); server._wake_pass(); G.drain(GH, STORE, say=lambda s: None)
check("a wake notice (a time wait ending) names the item board#<n>, links its item page (never the card anchor #task-g-<n>), and keeps g<n> for the stderr tag",
      any(t[0] == g_wk and t[2].startswith(f"[stackshot] board#{num(g_wk)} is yours now: its until 2020-01-01 came. ") and re.search(re.escape(f"→ https://board.example.org/items/{num(g_wk)}") + r"( · notice [0-9a-f]{6})?$", t[2])
          and not re.search(rf"(?<![\w/-]){g_wk}\b", t[2]) for t in told), told)
# an after-release: the last item it waited on closes
g_first = mk("[home] closes first"); g_aft = mk("[home] waits on the first", after=g_first, mover="home-other")
told.clear(); server.stackshot_complete(g_first, outcome="done", reason="it is in", description="- In", sender="home-here"); G.drain(GH, STORE, say=lambda s: None)
check("an after-release notice names both items board#<n>",
      any(t[0] == g_aft and t[2].startswith(f"[stackshot] board#{num(g_aft)} woke: board#{num(g_first)}, the last item it waited on, closed (done) by home-here")
          and not re.search(rf"(?<![\w/-])({g_aft}|{g_first})\b", t[2]) for t in told), told)
check("…and the issue has no comment: the server's note of the release is not on GitHub", not comments(G.issue_of(g_aft, STORE)) and not comments(G.issue_of(g_first, STORE)))
# an owner notice: another session closes a front agent's item, so its keeper hears it; a close by the keeper itself tells nobody
# (no item notice wakes a front agent owner used to tell it the keeper's close plainly). A move to decision tells nobody either, neither the owner nor its keeper; a non-front owner still hears it, unmarked
g_own = mk("[home] closed by its keeper")
_pr, _fs = server._anc.pilot_root, server._front_keeper
server._anc.pilot_root = lambda p: p; server._front_keeper = lambda who, project="": (True, "home-keeper")
try:
    told.clear(); server._tell_owner(g_own, server._load(g_own), "was completed (done: closed by another session)", "home-other")
    told_stew = list(told)
    told.clear(); quiet = server._tell_owner(g_own, server._load(g_own), "was completed (done: closed by the keeper)", "home-keeper")
    told_close = list(told)
    told.clear(); heard_f: list[str] = []
    quiet_d = server._tell_owner(g_own, server._load(g_own), "now needs the owner's call (ask: pick one), set", "home-other", decision=True, heard=heard_f)
    told_dec = list(told)
    server._front_keeper = lambda who, project="": (False, "")
    told.clear(); heard_n: list[str] = []
    said_n = server._tell_owner(g_own, server._load(g_own), "now needs the owner's call (ask: pick one), set", "home-other", decision=True, heard=heard_n)
    told_dec_n = list(told)
finally:
    server._anc.pilot_root, server._front_keeper = _pr, _fs
check("an owner notice (a close on a front agent's item, to its keeper) names the item board#<n>",
      any(t[1] == "home-keeper" and t[3] == "owner" and t[2] == f"[stackshot] board#{num(g_own)} (mover home-here, a front agent) was completed (done: closed by another session) by home-other: [home] closed by its keeper → https://board.example.org/items/{num(g_own)}"
          for t in told_stew), told_stew)
check("a close by the keeper itself on a front agent's item tells nobody, and the reply says the owner is not told",
      told_close == [] and quiet == "\n(its mover home-here is a front agent: not told; the board shows it)", (told_close, quiet))
check("a move to decision on a front agent's item tells nobody (neither the owner nor its keeper), and the reply says the owner is not told",
      told_dec == [] and quiet_d == "\n(its mover home-here is a front agent: not told; the board shows it)" and heard_f == [server._session_id("home-here")], (told_dec, quiet_d, heard_f))
check("a move to decision on a non-front owner's item tells the owner, unmarked, and the reply says so",
      len(told_dec_n) == 1 and told_dec_n[0][1] == server._session_id("home-here") and told_dec_n[0][3] == "owner"
      and told_dec_n[0][2].startswith(f"[stackshot] board#{num(g_own)} now needs the owner's call (ask: pick one), set by home-other: ") and server._FOR_OWNER not in told_dec_n[0][2]
      and said_n == "\n(its mover home-here has been told)" and heard_n == [server._session_id("home-here")], (told_dec_n, said_n, heard_n))
# a recycle done: two items waiting for it, one held only for it
g_r1 = mk("[home] waits for a recycle too"); server._update(g_r1, recycle=True, sender="home-here")
g_r2 = mk("[home] held for a recycle too"); server._update(g_r2, recycle=True, sender="home-here"); server._update(g_r2, hold=True, sender="home-here")
G.drain(GH, STORE, say=lambda s: None); told.clear()
server._recycled("testbox", "recycle", 0, "ok", []); G.drain(GH, STORE, say=lambda s: None)
rc = [t for t in told if t[3] == "recycle"]
b1, b2 = f"board#{num(g_r1)}", f"board#{num(g_r2)}"
check("a recycle notice names its items board#<n>, the released one too; the stderr tag keeps g<n>",
      len(rc) == 1 and rc[0][0] == f"{g_r1} and {g_r2}" and rc[0][2].startswith(f"[stackshot] the recycle you waited for has run (testbox, ")
      and f"re-read {b1} and {b2} and resume. {b2} waited only for the recycle and is released from hold." in rc[0][2]
      and not re.search(rf"(?<![\w/-])({g_r1}|{g_r2})\b", rc[0][2]), rc)

# ---- 6c. phase 3, the inbound half: the owner's own comments on GitHub reach the item and its sessions
told.clear()
g_c = mk("[home] commented on GitHub", needs="decision", ask=ASK); n_c = G.issue_of(g_c, STORE); gn = num(g_c)
f_c = STORE / g_c[0] / f"{g_c[1:]}.json"; j_c = json.loads(f_c.read_text()); j_c["metadata"]["needs"] = ["decision", "home-other"]; f_c.write_text(json.dumps(j_c))
snap("before the owner's comment")
old = F.comment(n_c, "an old word by the owner, before the reader ran", at=time.time() - 100)   # history: the owner's login, no header, before the first read
check("the reader's defaults: 60 s between reads, the owner's login unset (the token's), no state before the first read",
      G.poll_seconds() == 60.0 and G.owner_login() == "" and not G.comments_state(), (G.poll_seconds(), G.owner_login(), G.comments_state()))
_ghc = server._cfg.CFG["github"]; _ghc["poll_seconds"] = 5; p5 = G.poll_seconds(); _ghc["poll_seconds"] = "x"; px = G.poll_seconds(); _ghc.pop("poll_seconds")
check("[github] poll_seconds is floored at 15 and a bad value reads as 60", p5 == 15.0 and px == 60.0, (p5, px))
check("a comment is the owner's by the login (case apart) and the missing header; the issue number comes from its issue_url",
      G.is_owner_comment(old, "Example-Owner") and not G.is_owner_comment(old, "someone") and not G.is_owner_comment({**old, "body": "[author: x · y]\nz"}, "example-owner")
      and G.issue_number(old) == n_c and G.item_of_issue(n_c, STORE) == g_c and G.item_of_issue(900, STORE) == "", (G.issue_number(old), G.item_of_issue(n_c, STORE)))
F.log.clear(); F.queries.clear(); c0 = len(comments(n_c))
r = G.poll_comments(GH, STORE, say=lambda s: None); st = G.comments_state()
check("the first read with no cursor starts at now and delivers nothing: the old comment is not read; the state holds since, started and no seen",
      r == {"new": 0, "skipped": 0, "failed": 0, "down": ""} and st.get("since") and st.get("started") == st["since"] and st.get("seen") == [] and not told
      and "answers" not in rd(g_c[0], gn)["metadata"] and abs(G._epoch(st["since"]) - time.time()) < 5, (r, st, told))
gets = [(m_, p_) for m_, p_, _t in F.log if m_ == "GET"]
check("a read is one GET of the comments since the cursor, sorted by update, ascending, 100 a page, and GET /user once for the login; no write; nothing else is read (no local copy of the comments is seeded)",
      gets == [("GET", "/user"), ("GET", REPO + "/issues/comments")] and not writes()
      and F.queries[-1].get("since") == [st["since"]] and F.queries[-1].get("sort") == ["updated"]
      and F.queries[-1].get("direction") == ["asc"] and F.queries[-1].get("per_page") == ["100"], (gets, F.queries[-1:]))
check("the state holds the cursor, the start, the owner's login and no copy flag", st.get("login") == "example-owner" and not st.get("copied") and st.get("since") and st.get("started"), st)
c1 = F.comment(n_c, "Ship it, option 1.\nAnd thanks."); F.log.clear(); told.clear()
r = G.poll_comments(GH, STORE, say=lambda s: None); it_c = rd(g_c[0], gn); ans = it_c["metadata"].get("answers")
check("the owner's comment is recorded on the item: answers = [{ts, kind comment, text, via github, url, comment_id}], ts the comment's own time",
      r["new"] == 1 and isinstance(ans, list) and len(ans) == 1
      and ans[0] == {"ts": ans[0]["ts"], "kind": "comment", "text": "Ship it, option 1.\nAnd thanks.", "via": "github", "url": c1["html_url"], "comment_id": c1["id"]}
      and abs(ans[0]["ts"] - G._epoch(c1["created_at"])) < 1, (r, ans))
NOTE = f"[stackshot] the owner commented on board#{gn} on GitHub: Ship it, option 1. And thanks. → https://board.example.org/items/{gn}"
check("the mover (the session in its needs) alone is told, once: the text on one line, the card link, the id as shown (the creator is not told)",
      sorted(told) == [(g_c, "home-other", NOTE, "comment")], told)
check("reading only: needs, status and the clocks as they were", it_c["metadata"]["needs"] == ["decision", "home-other"] and it_c["status"] == "open"
      and it_c["updated"] == j_c["updated"] and it_c.get("confirmed") == j_c.get("confirmed"), (it_c["metadata"].get("needs"), it_c["status"]))
check("the answers-only save queues no job and the read wrote nothing: the issue has the owner's comments and nothing echoed back",
      qlen() == 0 and not writes() and comments(n_c)[c0:] == [c1["body"]], (qlen(), writes(), comments(n_c)[c0:]))
snap("the owner's comment")
p_c = ui_render.Board(str(STORE)).item_html(g_c)
check("the item page's History shows the comment as written on GitHub, linked to it, with its text (the History is the store's git: the answer is recorded on the item)",
      f'<a href="{c1["html_url"]}" target="_blank" rel="noopener">on GitHub</a>: “Ship it, option 1. And thanks.”' in p_c, re.findall(r'<li class="ev ev-[a-z]+">.*?</li>', p_c, re.S)[:3])
check("…and the old comment, written before the reader ran, is not on the page: it was never recorded (history, never delivered)", "an old word by the owner" not in p_c and len(rd(g_c[0], gn)["metadata"]["answers"]) == 1)
told.clear(); F.log.clear()
r = G.poll_comments(GH, STORE, say=lambda s: None); st = G.comments_state()
check("a second read delivers nothing twice: the id is in seen, the cursor a second before its update (never behind where it started), one GET and no second GET /user",
      r["new"] == 0 and not told and st["seen"] == [c1["id"]] and G._epoch(st["since"]) == max(G._epoch(st["started"]), G._epoch(c1["updated_at"]) - 1)
      and [(m_, p_) for m_, p_, _t in F.log] == [("GET", REPO + "/issues/comments")], (r, told, st, F.log))
sub = subprocess.run([sys.executable, "-c", f"import sys, pathlib, json; sys.path.insert(0, {STACK!r}); import ghsync as G\n"
                      f"def hook(gid, c): raise RuntimeError('delivered again: ' + gid)\n"
                      f"G.on_comment = hook; print(json.dumps(G.poll_comments(G.GitHub('o/r', {API!r}, 'test-token'), pathlib.Path({str(STORE)!r}), say=lambda s: None)))"],
                     capture_output=True, text=True, env=os.environ, timeout=60)
check("a restart (a fresh process, the state from disk) delivers nothing twice", sub.returncode == 0 and json.loads(sub.stdout.strip() or "{}") == {"new": 0, "skipped": 0, "failed": 0, "down": ""}
      and "delivered again" not in sub.stderr, (sub.stdout, sub.stderr[-300:]))
F.edit(c1["id"], "Ship it, option 1. (edited)"); told.clear()
r = G.poll_comments(GH, STORE, say=lambda s: None)
check("an edit of a delivered comment is not a new one: nothing told, the text as first written", r["new"] == 0 and not told
      and rd(g_c[0], gn)["metadata"]["answers"][0]["text"] == "Ship it, option 1.\nAnd thanks.", (r, told))
F.edit(old["id"], "history, edited after the reader started"); told.clear()
r = G.poll_comments(GH, STORE, say=lambda s: None)
check("history edited after the first read stays history: created before the reader started, never delivered", r["new"] == 0 and r["skipped"] == 0 and not told
      and len(rd(g_c[0], gn)["metadata"]["answers"]) == 1, (r, told))
F.comment(n_c, f"[author: home-here · {OWNER}]\nnext:\n> by the mirror, with the owner's account"); F.comment(n_c, "a word from someone else", login="someone-else"); told.clear()
r = G.poll_comments(GH, STORE, say=lambda s: None)
check("a comment with the [author: …] header (the mirror's, same account) and one by another user are ignored",
      r == {"new": 0, "skipped": 0, "failed": 0, "down": ""} and not told and len(rd(g_c[0], gn)["metadata"]["answers"]) == 1, (r, told))
F.issues[900] = {"number": 900, "title": "not an item", "body": "", "labels": [], "state": "open", "state_reason": None, "_comments": []}
c_u = F.comment(900, "on an issue that is no item"); told.clear()
r = G.poll_comments(GH, STORE, say=lambda s: None)
check("a comment on an issue no item mirrors is skipped once (its id in seen), nothing told", r == {"new": 0, "skipped": 1, "failed": 0, "down": ""} and not told
      and c_u["id"] in G.comments_state()["seen"], (r, told, G.comments_state()))
# the hook fails (a disk error, say): the comment waits for the next read, the cursor stays before it; then it goes once
c_r = F.comment(n_c, "taken at the second try"); told.clear(); _hook = G.on_comment
def _boom(gid, c): raise OSError("no space")
G.on_comment = _boom; r1 = G.poll_comments(GH, STORE, say=lambda s: None); st1 = G.comments_state(); G.on_comment = _hook
r2 = G.poll_comments(GH, STORE, say=lambda s: None)
check("a comment the hook could not take is left for the next read (not in seen, the cursor before it) and then goes once",
      r1["failed"] == 1 and r1["new"] == 0 and c_r["id"] not in st1["seen"] and G._epoch(st1["since"]) <= G._epoch(c_r["updated_at"])
      and r2["new"] == 1 and len(told) == 1 and all("taken at the second try" in t[2] for t in told) and rd(g_c[0], gn)["metadata"]["answers"][-1]["comment_id"] == c_r["id"], (r1, st1, r2, told))
# a front agent mover hears it marked for the owner (_FOR_OWNER)
c_f = F.comment(n_c, "yes, go ahead"); told.clear(); _fs = server._front_keeper
server._front_keeper = lambda who, project="": (True, "home-keeper")
try: r = G.poll_comments(GH, STORE, say=lambda s: None)
finally: server._front_keeper = _fs
NOTE_F = f"[stackshot] the owner commented on board#{gn} on GitHub: yes, go ahead → https://board.example.org/items/{gn}"
check("a front agent mover hears it marked [for the owner]",
      r["new"] == 1 and sorted(told) == [(g_c, "home-other", f"[for the owner] {NOTE_F}", "comment")], told)
long = ("a long word of the owner's " * 60).strip()
c_l = F.comment(n_c, long + "\n\nsecond paragraph"); told.clear(); r = G.poll_comments(GH, STORE, say=lambda s: None)
check("a long comment is clipped in the notice (one line, an ellipsis, under 800 chars) and kept whole on the item",
      r["new"] == 1 and len(told) == 1 and all(" …" in t[2] and "\n" not in t[2] and len(t[2]) < 800 for t in told)
      and rd(g_c[0], gn)["metadata"]["answers"][-1]["text"] == long + "\n\nsecond paragraph", [len(t[2]) for t in told])
# the owner's own comment on an item with no session in needs: the owner alone
g_c2 = mk("[home] commented, nobody in needs"); c_2 = F.comment(G.issue_of(g_c2, STORE), "noted"); told.clear(); r = G.poll_comments(GH, STORE, say=lambda s: None)
check("with no session in needs the owner alone is told", r["new"] == 1 and told == [(g_c2, OWNER, f"[stackshot] the owner commented on board#{num(g_c2)} on GitHub: noted → https://board.example.org/items/{num(g_c2)}", "comment")], told)
# GitHub down: the read raises GitHubDown for the loop to back off; nothing changes
F.down = True; c_d = F.comment(n_c, "while GitHub is down"); told.clear(); st_d = G.comments_state()
try: G.poll_comments(GH, STORE, say=lambda s: None); down = None
except G.GitHubDown as e: down = e
F.down = False
check("an outage raises GitHubDown out of the read; the state is untouched", down is not None and G.comments_state() == st_d and not told, (down, G.comments_state()))
# the reader's thread, as the server starts it: a comment arrives without a poll_comments call
G.MIN_POLL = 0.05; _ghc["poll_seconds"] = 0.05
stop = threading.Event(); th = threading.Thread(target=G.comments_loop, args=(stop,), daemon=True); th.start()
for _ in range(100):
    if any("while GitHub is down" in t[2] for t in told): break
    time.sleep(0.05)
stop.set(); th.join(timeout=2); _ghc.pop("poll_seconds"); G.MIN_POLL = 15.0
check("the reader thread delivers a comment on its own, once", len([t for t in told if "while GitHub is down" in t[2]]) == 1
      and sum(a["comment_id"] == c_d["id"] for a in rd(g_c[0], gn)["metadata"]["answers"]) == 1, told)
# [github] owner_login names whose comments count; the token's login then does not
_ghc["owner_login"] = "Someone-Else"
c_o = F.comment(n_c, "as the configured login", login="someone-else"); c_h = F.comment(n_c, "as the token's login, not the configured one"); told.clear()
r = G.poll_comments(GH, STORE, say=lambda s: None); _ghc.pop("owner_login")
said = lambda: sorted({t[2].split("on GitHub: ")[1].split(" →")[0] for t in told})
check("[github] owner_login names whose comments count (case apart), the earlier one by that login still at the cursor included; the token's login then does not",
      r["new"] == 2 and len(told) == 2 and said() == ["a word from someone else", "as the configured login"] and rd(g_c[0], gn)["metadata"]["answers"][-1]["comment_id"] == c_o["id"], (r, told))
told.clear(); r = G.poll_comments(GH, STORE, say=lambda s: None)
check("the setting back, the comment missed under it is read at the next poll (never delivered, still after the cursor)", r["new"] == 1 and len(told) == 1
      and all("as the token's login" in t[2] for t in told), (r, told))
n_ans = len(rd(g_c[0], gn)["metadata"]["answers"])

# ---- 6e. the body is slim, BODY_FORM 3, and the one-time rewrite goes through the paced queue, behind live writes, only when asked for
n_first, n_aft = G.issue_of(g_first, STORE), G.issue_of(g_aft, STORE)
check("ref: an issue-numbered item is #<n>, an alias resolves to its issue, an item with no issue yet keeps its shown form board-tmp-<machine>#<n> (the server's notes still use it)",
      G.ref(g_first) == f"#{n_first}" and G.ref("l1") == f"#{n1}" and G.ref("l7") == "board-tmp-boxa#7" and G.ref("a1") == "#1", (G.ref(g_first), G.ref("l1"), G.ref("l7"), G.ref("a1")))
# the body: marker, description, footer, whatever else the item holds
g_d = mk("[home] a choice for Oliver"); n_d = G.issue_of(g_d, STORE)
server._update(g_d, needs="decision", ask=ASK, options=OPTS, next="pick one", sender="home-here"); G.drain(GH, STORE, say=lambda s: None)
b_dec = issue(n_d)["body"]
check("an item that waits on his decision shows the issue nothing of it: no Ask, no Options, no Next in the body, and the change made no job", "###" not in b_dec and ASK not in b_dec and "pick one" not in b_dec and "Ship it now" not in b_dec and qlen() == 0, b_dec[-300:])
full = {"subject": "[home] full", "description": DESC, "status": "open", "metadata": {"next": "a step", "needs": ["decision", "home-other"], "ask": ASK, "options": OPTS, "hold": True, "wake": "2027-01-01", "due": "2026-10-20", "project": "projects/alpha", "owner": OWNER,
                                                                                         "draft": {"text": "a draft"}, "work": [{"text": "w", "state": "done"}]}}
bf = G.body_of("g1", full)
check("body_of: the marker, the description and the footer link, whatever else the item holds (next, ask, options, hold, wake, due, owner, draft, work)",
      bf.startswith("<!-- stackshot:g1 -->\n\n" + DESC + "\n\n<sub>Mirrored from [board#1](https://board.example.org/items/1) by ") and bf.count("\n\n") == 2 and not any(w in bf for w in ("a step", ASK, "Ship", "2027", "a draft", "###", "**")), bf)
check("body_of: an item with no description reads _none_; a closed one shows no outcome, reason or replacement",
      "\n\n_none_\n\n" in G.body_of("g1", {"subject": "x", "description": "", "status": "completed", "metadata": {"outcome": "superseded", "superseded_by": "g2", "reason": "r"}}) and "superseded" not in G.body_of("g1", {"subject": "x", "description": "", "status": "completed", "metadata": {"outcome": "superseded", "superseded_by": "g2", "reason": "r"}}))
other = {**full, "metadata": {"next": "b", "needs": [], "wake": "2028-01-01", "project": "projects/other", "owner": "someone"}}
check("mirrored(): a change of next, needs, hold, wake, ask, options, due, project or owner is no change of what the issue carries", G.mirrored(full) == G.mirrored(other), (G.mirrored(full), G.mirrored(other)))
check("…while the subject, the description, open or closed and the reason of the close each are (five different values)",
      len({G.mirrored(full), G.mirrored({**full, "subject": "[home] other"}), G.mirrored({**full, "description": "- x"}), G.mirrored({**full, "status": "completed", "metadata": {"outcome": "done"}}), G.mirrored({**full, "status": "completed", "metadata": {"outcome": "dropped"}})}) == 5)
p_ = G.on_change("g1", full, other); check("on_change: nothing is queued for a change the issue does not carry", p_ is None and qlen() == 0, p_)
p_ = G.on_change("g1", full, {**full, "description": "- x"}); jb = json.loads(p_.read_text()); p_.unlink()
check("on_change: a changed description queues a job that is not urgent; a close and a reopening are urgent; a create is", jb["kind"] == "changed" and not jb["urgent"], jb)
for before_, after_, kind_ in ((full, {**full, "status": "completed", "metadata": {"outcome": "done"}}, "changed"), ({**full, "status": "completed", "metadata": {"outcome": "done"}}, full, "changed"), (None, full, "created")):
    p_ = G.on_change("g1", before_, after_); jb = json.loads(p_.read_text()); p_.unlink()
    check(f"on_change: {kind_} {'close' if after_.get('status') == 'completed' else 'reopen' if before_ else 'create'} is urgent", jb["kind"] == kind_ and jb["urgent"] is True, jb)
check("the body form is 3 and the sweep is off by default", G.BODY_FORM == 3 and G.backfill_bodies() is False and "backfill_bodies = false" in pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"), (G.BODY_FORM, G.backfill_bodies()))
# the worker queues the sweep only when [github] backfill_bodies is on
called = []; _rs = G.resync_bodies; G.resync_bodies = lambda *a, **k: called.append(1) or 0
def run_worker_once():
    stop_ = threading.Event(); th_ = threading.Thread(target=G.worker_loop, args=(stop_,), daemon=True); th_.start(); G._EVENT.set(); time.sleep(0.6); stop_.set(); G._EVENT.set(); th_.join(timeout=3)
run_worker_once()
check("backfill_bodies off (the default): the worker never asks for the sweep", called == [], called)
write_toml(sync=True, issue_ids=True, backfill=True); server._cfg.reload(); run_worker_once()
check("[github] backfill_bodies = true: the worker asks for it (resync_bodies itself decides once per body form)", G.backfill_bodies() is True and called != [], (G.backfill_bodies(), called))
write_toml(sync=True, issue_ids=True); server._cfg.reload(); G.resync_bodies = _rs
# the one-time rewrite: every mirrored item whose body is not what it renders now gets one background job, drained paced, behind live writes
_budget0 = GH.budget; GH.budget = 100000                          # the whole scenario's writes so far never count against the sweep here; the reserve has its own case below
G.resync_bodies(STORE, say=lambda s: None, force=True); G.drain(GH, STORE, say=lambda s: None)    # whatever earlier sections left unsynced, brought up first
check("the body form is recorded once the resync queued: a second resync without force queues nothing", G.resync_bodies(STORE, say=lambda s: None) == 0 and qlen() == 0, G.pending())
syn = G._synced(); stale_ids = sorted((g for g in G.load_map(STORE)["issues"] if g in syn), key=lambda g: G.issue_of(g, STORE))[:6]
for g in stale_ids: syn[g] = "a body of the old form"
G._save_synced(syn); G._body_form_path().unlink()
c_before = {g: len(comments(G.issue_of(g, STORE))) for g in stale_ids}; F.log.clear(); paced1 = len(GH._writes)
q = G.resync_bodies(STORE, say=lambda s: None)
jobs = [json.loads(p.read_text()) for p in G.pending()]
check("the resync queues one background job per stale issue, and sends nothing by itself",
      q == len(stale_ids) and len(jobs) == q and all(p.name.startswith(G.BACKGROUND) for p in G.pending()) and all(j_["kind"] == "sync" and "comment" not in j_ for j_ in jobs)
      and not F.log, (q, [p.name for p in G.pending()], F.log))
# a live write arrives while the sweep is draining: it jumps ahead of the rest of the sweep
fired = []; _sleep = GH.sleep
def _live_once(w):
    if not fired:
        fired.append(1); server._update(g_d, description=D("a live write during the sweep"), sender="home-here")
    _sleep(w)
GH.sleep = _live_once; _pace = GH.pace; GH.pace = 0.3     # the second write of the sweep surely waits on the pacer: the live write comes in there
r1 = G.drain(GH, STORE, say=lambda s: None); GH.sleep = _sleep; GH.pace = _pace
check("a live write enqueued during the sweep stops the background run; it is first in the queue for the next drain",
      fired and r1["left"] >= 1 and not G.pending()[0].name.startswith(G.BACKGROUND) and json.loads(G.pending()[0].read_text())["gid"] == g_d, (r1, [p.name for p in G.pending()]))
r2 = G.drain(GH, STORE, say=lambda s: None)
order = [p_ for m_, p_, _t in F.log if m_ in ("POST", "PATCH")]
check("the next drain sends the live write first, then the rest of the sweep; the queue empties", qlen() == 0 and r2["down"] == "" and
      order.index(f"{REPO}/issues/{n_d}") < order.index(f"{REPO}/issues/{G.issue_of(stale_ids[-1], STORE)}"), order)
check("the sweep made one PATCH per stale issue and no comment on any of them; the bodies carry no @mention",
      sum(p_ == f"{REPO}/issues/{G.issue_of(g, STORE)}" for g in stale_ids for p_ in order) >= len(stale_ids)
      and all(len(comments(G.issue_of(g, STORE))) == c_before[g] for g in stale_ids) and all("@" not in issue(G.issue_of(g, STORE))["body"] for g in stale_ids), (order, c_before))
st2 = list(GH._writes)[paced1:]; gaps2 = [b - a for a, b in zip(st2, st2[1:])]
check("the sweep's writes went through the pacer like any other: one stamp per write, never two closer than the interval",
      len(st2) == len(order) and gaps2 and min(gaps2) >= GH.pace, (len(st2), len(order), min(gaps2) if gaps2 else None))
check("the queue is empty after the resync", qlen() == 0, G.pending())
# the hour's budget: a background job never takes the live writes' reserve; a live one still goes
syn = G._synced(); syn[stale_ids[0]] = "a body of the old form"; G._save_synced(syn)
check("a forced resync queues the one stale issue", G.resync_bodies(STORE, say=lambda s: None, force=True) == 1 and qlen() == 1, G.pending())
_budget = GH.budget; GH.budget = GH.recent_writes() + 4          # four writes left this hour: inside the reserve (a quarter of the budget, at least one)
server._update(g_d, description=D("a live write with the hour nearly spent"), sender="home-here")
r3 = G.drain(GH, STORE, say=lambda s: None)
check("with the hour's budget down to the reserve, the live write drains and the background job waits for a later tick",
      r3["left"] == 1 and G.pending()[0].name.startswith(G.BACKGROUND) and "a live write with the hour nearly spent" in issue(n_d)["body"], (r3, [p.name for p in G.pending()]))
GH.budget = _budget; r4 = G.drain(GH, STORE, say=lambda s: None)
check("the budget back, the background job drains", r4["left"] == 0 and qlen() == 0, (r4, G.pending()))
budget_back(_budget0)
# jobs an older version queued: the typed-field and label sweeps are dropped unread, a comment a job still carries is never posted
F.log.clear()
G.enqueue({"ts": time.time(), "gid": g_d, "kind": "fields"}, background=True); G.enqueue({"ts": time.time(), "gid": g_d, "kind": "labels"}, background=True)
r = G.drain(GH, STORE, say=lambda s: None)
check("a typed-field or label job an older version queued is dropped unread: no call", r["done"] == 2 and qlen() == 0 and not F.log, (r, F.log))
server._update(g_d, description=D("a legacy job"), sender="home-here")
q_ = G.pending()[0]; j_ = json.loads(q_.read_text()); j_.update(comment="[author: home-here · x]\nnext edited\n\nlegacy", parts=["next"], textonly=True, author="home-here · x"); q_.write_text(json.dumps(j_))
F.log.clear(); r = G.drain(GH, STORE, say=lambda s: None)
check("a job an older version queued with a comment still brings the issue up, with one PATCH, and posts no comment", r["done"] == 1 and mine(n_d) == [("PATCH", REPO + f"/issues/{n_d}")] and "a legacy job" in issue(n_d)["body"] and not comments(n_d), (r, mine(n_d), comments(n_d)))

# ---- 6f. the trailers: his words on an item, checked against his message's transcript
# said=[{tag, quote, msg, session}] on create, update and complete; tags Acked-by | Suggested-by | Reported-by. The message named by msg
# is found in the session's transcript on the box ([said] transcripts/*/<uuid>.jsonl): a readable transcript that fails the check refuses the
# write, an unreadable one stores the entry unchecked. The issue comment ends with "Acked-by: <owner> <link>", never the quote.
FRONT = "00000000-0000-4000-8000-000000000002"
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": time.time()},
                                                      FRONT: {"name": "home-front", "machine": "a", "seen": time.time(), "url": "https://claude.ai/code/session_front"}}))
TR = T / "transcripts"; (TR / "-home-user").mkdir(parents=True); (T / "transcripts-team" / "-home-user-other").mkdir(parents=True)   # the front pane's transcript under the second root
ZONE_HOURS = 4                                    # the instance timezone pinned above (Asia/Dubai, UTC+4, no DST)
MSG_AT = f"Tue Jun 16th {9 + ZONE_HOURS:02d}:52"      # the transcript entry's ts 2026-06-16T09:52Z, as the board shows it
def entry(uuid, text, kind="human", ps="typed", meta=False, typ="user", parts=None, ts="2026-06-16T09:52:00.000Z"):
    """One transcript line as Claude Code writes it (compact JSON): a user entry with its origin and promptSource."""
    e = {"type": typ, "uuid": uuid, "timestamp": ts, "sessionId": "x", "message": {"role": "user", "content": parts if parts is not None else text}}
    if kind is not None: e["origin"] = {"kind": kind} if kind != "peer" else {"kind": "peer", "from": "other-pane"}
    if ps is not None: e["promptSource"] = ps
    if meta: e["isMeta"] = True
    return json.dumps(e, separators=(",", ":"))
U = lambda n: f"11111111-1111-4111-8111-{n:012d}"
(TR / "-home-user" / f"{OWNER}.jsonl").write_text("\n".join([
    entry(U(1), "ok, acked-by it is", ps="queued"),                                               # Remote Control: human, queued
    entry(U(2), "do the second one too\nand the third", ps="typed"),                              # typed at the keyboard
    entry(U(3), "relayed by a peer: ok, acked-by it is", kind="peer", meta=True),                  # another pane's message
    entry(U(4), "<!-- sala -->\nHandle the queue item. Go.", ps="typed"),                        # sala typed it: the marker first
    entry(U(5), "[auto-note] Worker for the queue item. Go ahead.", ps="typed"),  # sala typed it: a prefix, no marker yet
    entry(U(6), "something meta", meta=True),                                                     # isMeta
    entry(U(7), "", parts=[{"type": "tool_result", "tool_use_id": "t", "content": "ok, acked-by it is"}], ps=None),   # a tool result
    entry(U(8), "the sala marker <!-- sala --> is mentioned here, by me", ps="typed"),            # the marker further down: his
    entry(U(9), "no promptSource at all", ps=None),                                               # an older CLI: no promptSource
    entry(U(10), "an assistant line", typ="assistant"),
    entry(U(11), "quoting it:\n<!-- sala -->\nis not the first line", ps="typed"),                # the marker quoted below the first line: his
    entry(U(12), "", parts=[{"type": "text", "text": "parts: ship it"}, {"type": "text", "text": "as it is"}], ps="queued"),   # text parts
    entry(U(13), "from the sdk", ps="sdk"),                                                       # promptSource is for the record only
    entry(U(14), "  <!-- sala -->  \nindented marker", ps="typed"),                               # the marker first, with whitespace around it
    entry(U(15), "<!-- sala --> Open notes.txt, pasted by the relay tool. Carry on.", ps="typed"),   # sala's one-line form (salamander's form)
    entry(U(16), "Open notes.txt, pasted by the relay tool. Carry on.", ps="typed"),   # before the marker: spawn's wording alone
    entry(U(17), "Page: projects/alpha Today: 2026-06-16 — curate it.", kind=None, ps="sdk"),      # a claude -p turn: no origin at all, promptSource sdk
]) + "\n")
(T / "transcripts-team" / "-home-user-other" / f"{FRONT}.jsonl").write_text(entry(U(21), "relayed: yes, go with the trailers", ps="queued", ts="2026-06-16T09:57:00.000Z") + "\n")
OWN = server.OWNER; LINK = lambda n, k: f"https://board.example.org/items/{n}#said-{k}"
said_of = lambda g: json.loads((STORE / g[0] / f"{g[1:]}.json").read_text())["metadata"].get("said") or []
g_t = mk("[home] the trailers"); n_t = G.issue_of(g_t, STORE); F.log.clear()
server._update(g_t, next="first step", sender="home-here"); G.drain(GH, STORE, say=lambda s: None); snap("before the trailers")   # a git version without his words, for section 7's fallback
# a checked Acked-by, Remote Control style (origin human, promptSource queued)
out = server._update(g_t, next="ship it", sender="home-here", said=[{"tag": "Acked-by", "quote": "ok, acked-by it is", "msg": U(1)}]); r = G.drain(GH, STORE, say=lambda s: None)
e1 = said_of(g_t)
check("a checked Acked-by (Remote Control: origin human, promptSource queued): stored with the quote, the session's uuid, the message's uuid and clock, checked, the promptSource for the record, the sender",
      len(e1) == 1 and e1[0] == {"tag": "Acked-by", "quote": "ok, acked-by it is", "session": OWNER, "msg": U(1), "ts": calendar.timegm((2026, 6, 16, 9, 52, 0)), "checked": True, "prompt_source": "queued", "by": OWNER}, e1)
check("…the reply says it was checked, against which transcript", "(said: Acked-by checked against home-here's transcript)" in out, out)
check("…his words are a change nothing of the issue carries: no job, no call, no comment", qlen() == 0 and not comments(n_t), (qlen(), comments(n_t)))
p_t = page(g_t)
check("the item page: the History line of that write carries the tag 'Acked-by <owner>' (a details element anchored said-1), the quote, the session's name, the message time in the instance timezone and 'checked' behind it; the trailer line is not in the body",
      f'<details class="said" id="said-1"><summary><span class="badge said">Acked-by {OWN}</span></summary><div class="sbody"><blockquote>ok, acked-by it is</blockquote>'
      f'<span class="smeta">{OWN} in home-here · {MSG_AT} · checked against the transcript</span></div></details>' in p_t
      and "Acked-by: " not in p_t and 'id="said-1"' in p_t and "hashchange" in p_t, re.findall(r'<details class="said".*?</details>', p_t))
check("…the entry's bullet is the next text alone", '<div class="eb">next: ship it' in p_t, re.findall(r'<div class="eb">.*?</div>', p_t, re.S))
check("get shows the entry: the tag, the session, the time, checked, the quote", f"Acked-by: {OWN} · home-here · {MSG_AT} · checked · “ok, acked-by it is”" in server.stackshot_get(g_t), server.stackshot_get(g_t))
# a typed one; whitespace aside the quote must be verbatim
server._update(g_t, sender="home-here", said=[{"tag": "Suggested-by", "quote": "do the second one too   and the third", "msg": U(2)}]); G.drain(GH, STORE, say=lambda s: None)
e2 = said_of(g_t)
check("a typed one, the quote spanning the message's line break (whitespace collapsed on both sides): checked, promptSource typed; appended after the first",
      len(e2) == 2 and e2[0] == e1[0] and e2[1]["checked"] and e2[1]["prompt_source"] == "typed" and e2[1]["tag"] == "Suggested-by", e2)
check("…a write that records his words and changes nothing else: stored, no job, no comment", qlen() == 0 and not comments(n_t), (qlen(), comments(n_t)))
check("…the page classes that line ev-said", f'<li class="ev ev-said"><div class="eh">' in page(g_t) and "Suggested-by recorded" in page(g_t), re.findall(r'<li class="ev ev-[a-z]+">', page(g_t))[:2])
# refusals: a readable transcript that fails the check refuses the write, naming the entry and the test; nothing is stored or queued
k_q, k_c = len(said_of(g_t)), len(comments(n_t))
S = lambda **kw: [{"tag": "Acked-by", "quote": "ok, acked-by it is", "msg": U(1), **kw}]
refused("a quote not in the message is refused, naming the test", lambda: server._update(g_t, sender="home-here", said=[{"tag": "Acked-by", "quote": "ok, acked-by it is not", "msg": U(1)}]),
        "Refused: said[0] (Acked-by): the quote is not in the message", "cut verbatim", U(1))
refused("a peer-origin message (another pane's relay) is refused: not his own", lambda: server._update(g_t, sender="home-here", said=[{"tag": "Acked-by", "quote": "ok, acked-by it is", "msg": U(3)}]),
        f"not {OWN}'s own", "its origin is peer, not human")
refused("an isMeta entry is refused", lambda: server._update(g_t, sender="home-here", said=[{"tag": "Acked-by", "quote": "something meta", "msg": U(6)}]), f"not {OWN}'s own", "meta entry")
refused("a message that starts with sala's marker on a line of its own is refused as injected text", lambda: server._update(g_t, sender="home-here", said=[{"tag": "Acked-by", "quote": "Go.", "msg": U(4)}]),
        "text a tool typed into the pane", "it starts with the marker '<!-- sala -->' ([said] injected_marker)")
refused("…the marker first with whitespace around it too", lambda: server._update(g_t, sender="home-here", said=[{"tag": "Acked-by", "quote": "indented marker", "msg": U(14)}]), "it starts with the marker '<!-- sala -->'")
refused("…and sala's one-line form, the marker then a space then the brief (salamander's form)", lambda: server._update(g_t, sender="home-here", said=[{"tag": "Acked-by", "quote": "Carry on.", "msg": U(15)}]),
        "it starts with the marker '<!-- sala -->'")
check("with no [said] injected_marker no marker is looked for (the stopgaps still apply)", server._said.injected("<!-- sala -->\nHandle the queue item.", (), (), "") == ""
      and server._said.injected("<!-- sala -->\nHandle the queue item.", (), (), "<!-- sala -->") != "" and server._said.injected("[auto-note] x", ("[auto-note]",), (), "") != "")
refused("an injected prefix ([said] injected_prefixes, the stopgap for messages before the marker) is refused as injected text", lambda: server._update(g_t, sender="home-here", said=[{"tag": "Reported-by", "quote": "Go ahead.", "msg": U(5)}]),
        "text a tool typed into the pane", "'[auto-note]'", "injected_prefixes")
refused("an injected phrase ([said] injected_phrases, spawn's wording, the other stopgap) anywhere in the text is refused too", lambda: server._update(g_t, sender="home-here", said=[{"tag": "Reported-by", "quote": "Carry on.", "msg": U(16)}]),
        "text a tool typed into the pane", "'pasted by the relay tool'", "injected_phrases")
refused("a claude -p turn (no origin, promptSource sdk) is refused by the origin rule: not his", lambda: server._update(g_t, sender="home-here", said=[{"tag": "Reported-by", "quote": "curate it.", "msg": U(17)}]),
        f"not {OWN}'s own", "it has no human origin")
refused("an unknown uuid is refused: no such message in the transcript", lambda: server._update(g_t, sender="home-here", said=S(msg=U(99))), f"no message {U(99)} in the transcript of home-here")
refused("a tool result is refused", lambda: server._update(g_t, sender="home-here", said=[{"tag": "Acked-by", "quote": "ok, acked-by it is", "msg": U(7)}]), f"not {OWN}'s own", "it is a tool result")
refused("an assistant entry is refused", lambda: server._update(g_t, sender="home-here", said=[{"tag": "Acked-by", "quote": "an assistant line", "msg": U(10)}]), "not a user message")
refused("an invalid tag is refused", lambda: server._update(g_t, sender="home-here", said=S(tag="Signed-off-by")), "Refused: said[0]: tag must be one of Acked-by | Suggested-by | Reported-by", "'Signed-off-by'")
refused("a missing quote is refused for every tag", lambda: server._update(g_t, sender="home-here", said=[{"tag": "Reported-by", "quote": "  ", "msg": U(1)}]), "said[0] (Reported-by): quote is required", "verbatim")
refused("a missing msg is refused", lambda: server._update(g_t, sender="home-here", said=[{"tag": "Reported-by", "quote": "x"}]), "said[0] (Reported-by): msg is required", "uuid")
refused("a msg that is not a uuid is refused", lambda: server._update(g_t, sender="home-here", said=S(msg="home-here")), "msg must be the message's uuid")
refused("an unknown key is refused", lambda: server._update(g_t, sender="home-here", said=S(text="x")), "unknown key text")
refused("said that is not a list of objects is refused with the form", lambda: server._update(g_t, sender="home-here", said="ok, acked-by it is"), "not valid JSON", "said=[{tag")
check("a refused write stored nothing, queued nothing and posted nothing", len(said_of(g_t)) == k_q and len(comments(n_t)) == k_c and qlen() == 0, (len(said_of(g_t)), len(comments(n_t)), qlen()))
# not refused: the marker mentioned further down or quoted below the first line is his; promptSource never decides
server._update(g_t, sender="home-here", said=[{"tag": "Reported-by", "quote": "is mentioned here, by me", "msg": U(8)}, {"tag": "Reported-by", "quote": "is not the first line", "msg": U(11)}]); G.drain(GH, STORE, say=lambda s: None)
check("the marker mentioned mid-text in his message, or quoted on a later line, is not injected text (only a message that STARTS with it is): both checked", [x["checked"] for x in said_of(g_t)[-2:]] == [True, True], said_of(g_t)[-2:])
server._update(g_t, sender="home-here", said=[{"tag": "Acked-by", "quote": "no promptSource at all", "msg": U(9)}, {"tag": "Acked-by", "quote": "from the sdk", "msg": U(13)},
                                             {"tag": "Suggested-by", "quote": "parts: ship it as it is", "msg": U(12)}]); G.drain(GH, STORE, say=lambda s: None)
check("promptSource is recorded for the audit only and never decides: an entry without one and an sdk one are checked like a typed one, their value as found; text parts are joined for the quote",
      [(x["checked"], x["prompt_source"]) for x in said_of(g_t)[-3:]] == [(True, ""), (True, "sdk"), (True, "queued")], said_of(g_t)[-3:])
check("the stored entries accumulate, never dropped, each at its position", len(said_of(g_t)) == 7 and said_of(g_t)[0] == e1[0] and said_of(g_t)[1] == e2[1], [x["msg"] for x in said_of(g_t)])
# a missing transcript (a cloud session, another machine): stored unchecked, never refused, shown so
out = server._update(g_t, sender="home-here", said=[{"tag": "Acked-by", "quote": "said in the cloud", "msg": U(31), "session": "cse_01ABC"}]); G.drain(GH, STORE, say=lambda s: None)
e8 = said_of(g_t)[-1]
check("a session with no transcript on this box (cse_…): stored unchecked with why, the session as given, no clock, no promptSource",
      e8["checked"] is False and e8["session"] == "cse_01ABC" and e8["ts"] == 0 and e8["prompt_source"] == "" and e8["why"] == "no transcript for this session on this box" and e8["quote"] == "said in the cloud", e8)
check("…the reply says so", "(said: Acked-by stored unchecked: no transcript for this session on this box)" in out, out)
p_t = page(g_t)
check("…and the page's tag itself reads 'Acked-by <owner> · unchecked', with why behind it",
      f'<details class="said" id="said-8"><summary><span class="badge said unchecked">Acked-by {OWN} · unchecked</span></summary><div class="sbody"><blockquote>said in the cloud</blockquote>'
      f'<span class="smeta">{OWN} in cse_01ABC · unchecked: no transcript for this session on this box</span></div></details>' in p_t,
      re.findall(r'<details class="said" id="said-8".*?</details>', p_t))   # a cloud session has no pane: its name is text, as any session's without a live pane
check("…get says unchecked", f"Acked-by: {OWN} · cse_01ABC · unchecked · “said in the cloud”" in server.stackshot_get(g_t), server.stackshot_get(g_t))
# relayed: his words reached the writer through another session; session names where he said it (a pane name, resolved to its transcript)
server._update(g_t, sender="home-here", said=[{"tag": "Acked-by", "quote": "yes, go with the trailers", "msg": U(21), "session": "home-front"}]); G.drain(GH, STORE, say=lambda s: None)
e9 = said_of(g_t)[-1]
check("relayed: session=home-front (a pane name) resolves to that pane's transcript uuid, the message is found there (under the second configured root): checked, the front session stored, the sender as by",
      e9["checked"] and e9["session"] == FRONT and e9["by"] == OWNER and e9["ts"] == calendar.timegm((2026, 6, 16, 9, 57, 0)), e9)
server._cfg.CFG["client"]["session_view"] = "https://sala.example.org/#s={name}"   # session names link to the fleet tool's view while they have a live pane
check("…the page's tag names and links the front session to its view, like other session names (no [fleet] tool_name: the title names none)", f'<span class="smeta">{OWN} in <a href="https://sala.example.org/#s=home-front" target="_blank" rel="noopener" title="open this session\'s view">home-front</a> · Tue Jun 16th {9 + ZONE_HOURS:02d}:57 · checked against the transcript</span>' in page(g_t),
      re.findall(r'<details class="said" id="said-9".*?</details>', page(g_t)))
server._cfg.CFG["client"]["session_view"] = ""
# the item page draws no Discuss button (a link to the fleet tool's side conversation), with a fleet tool's address configured or not
for sv_ in ("", "https://sala.example.org/#s={name}"):
    server._cfg.CFG["client"]["session_view"] = sv_
    pg_d = {t_: page(t_) for t_ in (g_t, "s22", "g2")}
    check(f"no Discuss button: with [client] session_view {'set' if sv_ else 'unset'}, an open item's page and a completed one draw no idiscuss link, no #side= address and no Discuss text",
          all("idiscuss" not in p_ and "#side=" not in p_ and "Discuss" not in p_ for p_ in pg_d.values()), {t_: ("idiscuss" in p_, "#side=" in p_) for t_, p_ in pg_d.items()})
server._cfg.CFG["client"]["session_view"] = ""
refused("relayed with the wrong session: the message is not in that transcript", lambda: server._update(g_t, sender="home-here", said=[{"tag": "Acked-by", "quote": "yes, go with the trailers", "msg": U(21)}]), f"no message {U(21)} in the transcript of home-here")
server._update(g_t, sender="home-here", said=[{"tag": "Acked-by", "quote": "yes, go with the trailers", "msg": U(21), "session": FRONT}]); G.drain(GH, STORE, say=lambda s: None)
check("…session given as the transcript uuid itself works the same", said_of(g_t)[-1]["checked"] and said_of(g_t)[-1]["session"] == FRONT, said_of(g_t)[-1])
server._update(g_t, sender="home-here", said=[{"tag": "Acked-by", "quote": "said on another box", "msg": U(41), "session": "home-elsewhere"}]); G.drain(GH, STORE, say=lambda s: None)
check("a session name no live pane carries (another machine): stored unchecked under the name as given", said_of(g_t)[-1]["checked"] is False and said_of(g_t)[-1]["session"] == "home-elsewhere", said_of(g_t)[-1])
# the parameter as a JSON string (a client whose cached schema sends it as text) and as one object
server._update(g_t, sender="home-here", said=json.dumps({"tag": "acked-by", "quote": "ok, acked-by it is", "msg": U(1)})); G.drain(GH, STORE, say=lambda s: None)
check("said as a JSON string of one object, the tag in any case: parsed, the tag stored in its canonical spelling", said_of(g_t)[-1]["tag"] == "Acked-by" and said_of(g_t)[-1]["checked"], said_of(g_t)[-1])
# all three tags in one write, on a create and on a complete
out = server._create(subject="[home] born with his words", description=DESC, project="projects/alpha", owner="home-here", next="x",
                     said=[{"tag": "Suggested-by", "quote": "do the second one too", "msg": U(2)}, {"tag": "Reported-by", "quote": "and the third", "msg": U(2)}, {"tag": "Acked-by", "quote": "ok, acked-by it is", "msg": U(1)}])
g_b = G.norm(re.search(r"created (\S+)", out).group(1)); n_b = G.issue_of(g_b, STORE); G.drain(GH, STORE, say=lambda s: None)
check("a create with his words: the three entries stored in order, by the owner; the reply says each was checked",
      [x["tag"] for x in said_of(g_b)] == ["Suggested-by", "Reported-by", "Acked-by"] and all(x["checked"] and x["by"] == OWNER for x in said_of(g_b)) and out.count("checked against home-here's transcript") == 3, (said_of(g_b), out))
check("…the page shows the birth line and the line with the three tags", [t for t in re.findall(r'<span class="badge said[^"]*">([^<]*)</span>', page(g_b))] == [f"Suggested-by {OWN}", f"Reported-by {OWN}", f"Acked-by {OWN}"]
      and 'class="ev ev-created"' in page(g_b), re.findall(r'<span class="badge said[^"]*">([^<]*)</span>', page(g_b)))
server.stackshot_complete(g_b, outcome="done", reason="he said so", description="- Done, as he said", sender="home-here", said=[{"tag": "Acked-by", "quote": "ok, acked-by it is", "msg": U(1)}]); G.drain(GH, STORE, say=lambda s: None)
check("a complete with his words: the entry appended after the create's three, and the issue is closed with no comment", len(said_of(g_b)) == 4 and issue(n_b)["state"] == "closed" and not comments(n_b), (len(said_of(g_b)), comments(n_b)))
snap("trailers")

# ---- 6h. the repo moved (example-owner/board → example-org/board while [github] issues_repo
# still named the old home): GitHub answers the old path with a redirect to the repo's id-form url, a GET with 301, a write with 307
# (urllib follows the GET, refuses the 307; a 301 on a write it would turn into a GET of the new url). A write so answered is neither
# a crash (that night's create: KeyError 'number') nor done (an edit recorded as synced without landing):
# it is an outage, the job waits with its temporary id, and one log line names the HTTP status and the url
import contextlib as _ctx, io as _io
G.drain(GH, STORE, say=lambda s: None)
g_mv = G.norm(made("[home] before the move")[0]); n_mv = G.issue_of(g_mv, STORE)
for bad in ({"message": "Moved Permanently", "url": f"{API}/repositories/1/issues"}, {}, [], None, {"number": "x"}):
    try: G._issue_number(bad); check("an answer with no issue number is never a number", False, bad)
    except G.GitHubDown: pass
check("an answer with the number reads as before", G._issue_number({"number": 5}) == 5)
# the edit path: the issue's PATCH is answered with a redirect
F.moved = True; F.moved_only = f"/issues/{n_mv}"; F.log.clear()
server._update(g_mv, description=D("edited while the repo moves"), sender="home-here")
err_mv = _io.StringIO()
with _ctx.redirect_stderr(err_mv):
    r_mv = G.drain(GH, STORE, say=lambda s: None)
j_mv = json.loads(G.pending()[0].read_text())
check("an edit answered with a redirect is an outage: the job stays, marked tried with the status; the issue is as it was, and the edit is not recorded as synced",
      r_mv["done"] == 0 and r_mv["left"] == 1 and "307" in r_mv["down"] and j_mv["gid"] == g_mv and j_mv.get("tried") == 1 and "307" in j_mv.get("error", "")
      and "edited while the repo moves" not in issue(n_mv)["body"], (r_mv, j_mv))
check("one log line names the HTTP status and the url of the redirected write",
      err_mv.getvalue().count("ghsync: HTTP 307") == 1
      and re.search(rf"^ghsync: HTTP 307 on PATCH {re.escape(API)}/repos/o/r/issues/{n_mv} → {re.escape(API)}/repositories/1/issues/{n_mv}; the write waits", err_mv.getvalue(), re.M) is not None,
      err_mv.getvalue())
F.moved_write = 301; F.log.clear()
r_mv2 = G.drain(GH, STORE, say=lambda s: None)
patches_mv = [i for i, (m_, _p, _t) in enumerate(F.log) if m_ == "PATCH"]
check("a write answered 301 is not turned into a GET of the new url (urllib's own way with a write): the same outage, nothing read as its answer",
      r_mv2["done"] == 0 and r_mv2["left"] == 1 and "301" in r_mv2["down"] and patches_mv and not F.log[patches_mv[-1] + 1:] and "edited while the repo moves" not in issue(n_mv)["body"], (r_mv2, F.log))
F.moved_only = ""; F.log.clear()
rp_mv = G.poll_comments(GH, STORE, say=lambda s: None)
check("the reads go on through the move: a GET follows the 301 to the new url and the read is no outage",
      not rp_mv.get("down") and ("GET", f"/repositories/1/issues/comments") in [(m_, p_) for m_, p_, _t in F.log], (rp_mv, F.log))
F.moved = False; F.moved_write = 307
r_mv3 = G.drain(GH, STORE, say=lambda s: None)
check("the repo's home known again: the edit lands once and the job is gone", r_mv3 == {"done": 1, "left": 0, "down": ""} and "edited while the repo moves" in issue(n_mv)["body"] and mine(n_mv)[-1:] == [("PATCH", REPO + f"/issues/{n_mv}")], (r_mv3, mine(n_mv)))
# the create path: the tool's create during the move
F.moved = True; nxt_mv = F.next; F.log.clear()
out_mv = server._create(subject="[home] while the repo moves", description=DESC, project="projects/alpha", owner="home-here", next="x")
l_mv = G.norm(re.search(r"created (\S+)", out_mv).group(1))
check("a create answered with a redirect is neither a crash nor a refusal: the item takes a temporary id, its create is queued, no issue is made",
      out_mv.startswith("created board-tmp-boxa#") and "is a temporary id" in out_mv and "redirected" in out_mv and l_mv.startswith("l")
      and (STORE / "l" / f"{l_mv[1:]}.json").exists() and F.next == nxt_mv and qlen() == 1, (out_mv[:300], l_mv, qlen(), F.next))
err_c = _io.StringIO()
with _ctx.redirect_stderr(err_c):
    r_c = G.drain(GH, STORE, say=lambda s: None)
j_c = json.loads(G.pending()[0].read_text())
check("the queued create meets the redirect too: the job waits, marked tried, no issue, and the log line names the create's url",
      r_c["done"] == 0 and r_c["left"] == 1 and "307" in r_c["down"] and j_c["gid"] == l_mv and j_c.get("tried", 0) >= 1 and F.next == nxt_mv
      and re.search(rf"^ghsync: HTTP 307 on POST {re.escape(API)}/repos/o/r/issues → {re.escape(API)}/repositories/1/issues;", err_c.getvalue(), re.M) is not None
      and not any(m_ != "GET" and p_.startswith("/repositories/") for m_, p_, _t in F.log), (r_c, j_c, err_c.getvalue(), F.log[-4:]))
F.moved = False; F.log.clear()
r_c2 = G.drain(GH, STORE, say=lambda s: None)
g_c2 = f"g{nxt_mv}"
check("the repo's home known again: the marker is looked for first, one issue is made, and the item is re-keyed to its number",
      r_c2 == {"done": 1, "left": 0, "down": ""} and F.next == nxt_mv + 1 and (STORE / "g" / f"{nxt_mv}.json").exists() and not (STORE / "l" / f"{l_mv[1:]}.json").exists()
      and G.load_map(STORE)["aliases"].get(l_mv) == g_c2 and f"<!-- stackshot:{g_c2} (was {l_mv}) -->" in issue(nxt_mv)["body"]
      and [(m_, p_) for m_, p_, _t in F.log if m_ == "POST" and p_ == REPO + "/issues"] == [("POST", REPO + "/issues")]
      and [(m_, p_) for m_, p_, _t in F.log].index(("GET", REPO + "/issues")) < [(m_, p_) for m_, p_, _t in F.log].index(("POST", REPO + "/issues")), (r_c2, F.next, F.log))

# ---- 7. the switches off again: with no queue an outage create is refused as in phase 1, and a server pass queues nothing
write_toml(sync=False, issue_ids=True); server._cfg.reload(); F.down = True
refused("with the mirror off there is no queue to carry the create, so an outage refuses it, with why",
        lambda: server._create(subject="[home] no queue", description=DESC, project="projects/alpha", owner="home-here", next="x"), "GitHub did not answer", "issue_ids")
F.down = False
write_toml(sync=False, issue_ids=False); server._cfg.reload(); F.log.clear()
server._update(f"g{n1}", hold=True, wake="2026-12-01", sender="home-here")
import datetime as _dt
woke = server._wake_pass(_dt.date(2027, 1, 1))
check("the issue link: the mirror turned off again, the item's page shows none", not G.enabled() and ghl(ui_render.Board(str(STORE)).item_html(f"g{n1}")) == [],
      ghl(ui_render.Board(str(STORE)).item_html(f"g{n1}")))
check("with sync off a wake pass releases the item and queues nothing, sends nothing", f"g{n1}" in woke and qlen() == 0 and not F.log, (woke, qlen(), F.log))
p_off = page(g_c)
check("with sync off the History is the store's git, as with it on: no issue read, and the owner's comment on GitHub is there from the answers on the item",
      f'on GitHub</a>: “Ship it, option 1. And thanks.”' in p_off and not F.log, (F.log, re.findall(r'<li class="ev ev-[a-z]+">.*?</li>', p_off, re.S)[:2]))
p_toff = page(g_t)
check("with sync off the git-derived History carries his words too: the line of the version that recorded them reads '<tags> recorded' with a tag per entry, the unchecked one reading so itself",
      'class="ev ev-said"' in p_toff and p_toff.count('<details class="said"') == len(said_of(g_t)) and f'<span class="badge said unchecked">Acked-by {OWN} · unchecked</span>' in p_toff
      and f'<span class="badge said">Acked-by {OWN}</span>' in p_toff and "recorded" in p_toff, (p_toff.count('<details class="said"'), len(said_of(g_t))))
F.comment(n_c, "while the mirror is off"); told.clear(); F.log.clear()
r = G.poll_comments(GH, STORE, say=lambda s: None)
check("with sync off a read reads nothing: no GET, nothing told, nothing recorded", r.get("off") and not F.log and not told and len(rd(g_c[0], gn)["metadata"]["answers"]) == n_ans, (r, F.log, told))
server._tell_woken = lambda *a, **k: None

# ---- the shown form on the way in (why did a session write the store's g<n> for an item?): every write
# that takes text writes a bare g<n> that names an item as board#<n>; code, links, unknown ids and glued tokens stay as written
gk, nk = f"g{n1}", f"board#{n1}"
check("the fixture: the referent is an issue-numbered item in the store and g999 is none", (STORE / f"g/{n1}.json").exists() and not (STORE / "g/999.json").exists())
sw = server._shown_ids
check("_shown_ids: a bare g<n> → board#<n>, also at a sentence's end, before a colon or a possessive and inside parentheses",
      sw(f"waits on {gk}. Then ({gk}), {gk}: done; {gk}'s owner") == f"waits on {nk}. Then ({nk}), {nk}: done; {nk}'s owner", sw(f"waits on {gk}. Then ({gk}), {gk}: done; {gk}'s owner"))
code_txt = f"see `{gk}` here\n```\nrun {gk}\n```\n[{gk}](https://example.org/{gk}) and https://example.org/x/{gk} and [about {gk}][r]"
check("_shown_ids: left alone inside inline code, a fenced block, a markdown link (text and url), a URL and a reference link", sw(code_txt) == code_txt, sw(code_txt))
glued = f"g999 g12abc xg12 {gk}abc x{gk} board#{gk} s27/{gk} x-{gk} {gk}-x {gk}/y {gk}.json @{gk} G{n1}"
check("_shown_ids: an unknown g999, g12abc, xg12 and every glued or path-like token stay as written", sw(glued) == glued, sw(glued))
check("_shown_ids: the other stored forms stay as they are (s<n>, l<n>, board#<n>)", sw("s21, l1 and board#1") == "s21, l1 and board#1", sw("s21, l1 and board#1"))
out = server._create(subject=f"[home] follow up {gk}", description=f"- Waits on {gk}\n- Not `{gk}`, nor g999\n- Finished when it works", project="projects/alpha",
                     owner="home-here", next=f"ping {gk} owner", ask="", needs="decision", options=[{"label": f"After {gk}", "line": f"Wait for {gk} to close", "recommended": True},
                                                                                         {"label": "Now", "line": "Go now", "recommended": False}])
gw = _model_ids._norm_id(re.search(r"created (\S+)", out).group(1)); dw = rd(gw[0], gw[1:])
check("create: g<n> in subject, description, next and the options is stored as board#<n>; code and an unknown id stay",
      dw["subject"] == f"[home] follow up {nk}" and dw["description"] == f"- Waits on {nk}\n- Not `{gk}`, nor g999\n- Finished when it works"
      and dw["metadata"]["next"] == f"ping {nk} owner" and dw["metadata"]["options"][0]["label"] == f"After {nk}" and dw["metadata"]["options"][0]["line"] == f"Wait for {nk} to close", dw)
check("create: the reply echoes the shown form, never the store id", nk in out and not re.search(rf"(?<![\w#/`-]){gk}(?![\w`])", out), out[:600])
out = server._update(gw, next=f"after {gk} closes", description=f"- Now waits on {gk}\n- It lives here\n- Done when it works", subject=f"[home] after {gk}",
                     ask=f"Decide: whether to wait on {gk} · Recommend: yes · Stakes: none either way · By: no date", work={"text": f"watch {gk}", "state": "in progress"}, sender="home-here")
dw = rd(gw[0], gw[1:])
check("update: g<n> in subject, description, next, ask and a step status is stored as board#<n>",
      dw["subject"] == f"[home] after {nk}" and dw["description"].startswith(f"- Now waits on {nk}") and dw["metadata"]["next"].startswith(f"after {nk} closes")
      and f"wait on {nk}" in dw["metadata"]["ask"] and any(x.get("tag", {}).get("text") == f"watch {nk}" for x in dw["metadata"]["steps"]), dw)
check("update: the reply shows the rewritten form", f"after {nk} closes" in out and f"after {gk}" not in out, out[:600])
out = server._update(gw, status="completed", outcome="done", reason=f"closed with {gk}", outcome_text=f"- Ended with {gk}\n- It lived here\n- It worked", sender="home-here")
dw = rd(gw[0], gw[1:])
check("complete: g<n> in the reason and in the outcome text is stored as board#<n>, and the description (stored as board#<n> on its own write) stays as it was",
      dw["metadata"]["reason"] == f"closed with {nk}" and dw["metadata"]["outcome_text"] == f"- Ended with {nk}\n- It lived here\n- It worked"
      and dw["description"].startswith(f"- Now waits on {nk}") and gk not in json.dumps(dw["metadata"]["outcome_text"]), dw)
(T / "fakepush_g.py").write_text(f"import json, sys\nopen({str(T / 'push_g.json')!r}, 'w').write(json.dumps(sys.argv[1:]))\nprint('delivered')\n")
_push, _gf, _hand = server._PUSH, server._gate_front, server._name_on_handover
server._PUSH = [sys.executable, str(T / "fakepush_g.py")]; server._gate_front = lambda *a, **k: None; server._name_on_handover = lambda *a, **k: ""
try:
    server._message("home-here", f"about {gk}, not `{gk}` nor g999", "home-other")
    env_ = json.loads((T / "push_g.json").read_text())[-1]
finally:
    server._PUSH, server._gate_front, server._name_on_handover = _push, _gf, _hand
check("message: a bare g<n> in the text is delivered as board#<n>; code and an unknown id stay", f"about {nk}, not `{gk}` nor g999" in env_, env_[:300])

# ---- the rewrite never changes what a message names (the keeper, before merge): the handover's naming reads the text as the sender
# wrote it, so a message names exactly the items it named before the rewrite (_item_refs of the original text); only delivery and
# the log carry board#<n>
_open_g = sorted((f"g{q.stem}" for q in (STORE / "g").glob("*.json") if q.stem.isdigit() and json.loads(q.read_text()).get("status") == "open"
                  and "ops-alpha-bg" not in str(json.loads(q.read_text()).get("metadata", {}).get("needs"))), key=lambda g: int(g[1:]))
(gb, gc, gd) = _open_g[:3]; nc0 = rd("g", gc[1:])["metadata"].get("needs")
check("the fixture: three open issue-numbered targets", all(g[0] == "g" and rd(g[0], g[1:])["status"] == "open" for g in (gb, gc, gd)), (gb, gc, gd))
seen_txt = []
_push, _gf, _ba, _to, _hand = server._PUSH, server._gate_front, server._back_agent, server._tell_owner, server._name_on_handover
server._PUSH = [sys.executable, str(T / "fakepush_g.py")]; server._gate_front = lambda *a, **k: None
server._back_agent = lambda who, idx=None: "ops-alpha-bg" if who == "home-here" else ""; server._tell_owner = lambda *a, **k: ""
server._name_on_handover = lambda to, text, *a, **k: (seen_txt.append(text), _hand(to, text, *a, **k))[1]
def _needs(g): return rd(g[0], g[1:])["metadata"].get("needs")
try:
    txt_b = f"Take {gb} from here."
    before_b = server._item_refs(txt_b)                       # what the naming scan finds in this text, as it ran before the change
    out_b = server._message("home-here", txt_b, "home-other")
    env_b = json.loads((T / "push_g.json").read_text())[-1]
    check("handover (a): a bare g<n> names exactly what it named before: the scan of the original text, never of the rewritten one",
          seen_txt[-1] == txt_b and before_b == [gb] and ("ops-alpha-bg" in str(_needs(gb))) == (gb in before_b), (seen_txt, before_b, _needs(gb), out_b))
    check("handover (a): the delivered text still carries board#<n>", f"Take {G.shown(gb)} from here." in env_b, env_b[:300])
    txt_c = f"Context only: `{gc}`."
    server._message("home-here", txt_c, "home-other")
    check("handover (a): a g<n> in backticks leaves the item's needs as they were, before and after", server._item_refs(txt_c) == [] and _needs(gc) == nc0, (_needs(gc), nc0))
    txt_d = f"Take {G.shown(gd)} from here."
    server._message("home-here", txt_d, "home-other")
    check("handover (b): a plain board#<n> still names the agent in the item's needs, as before", server._item_refs(txt_d) == [gd] and "ops-alpha-bg" in str(_needs(gd)), _needs(gd))
    # a release log line carries the merge queue's group number ("group g<n>", "[g<n>]"), which is not an item though g<n> is also a store id
    (ge, gf) = _open_g[3:5]; ne0 = _needs(ge)
    check("the fixture: two more open issue-numbered targets", all(g[0] == "g" and rd(g[0], g[1:])["status"] == "open" for g in (ge, gf)), (ge, gf))
    txt_e = f"PR 7 failed: required check suites failed in group {ge} [{ge}]"
    out_e = server._message("home-here", txt_e, "home-other")
    env_e = json.loads((T / "push_g.json").read_text())[-1]
    check("handover (c): a release line's merge-queue group number (group g<n>, [g<n>]) names no item, and the line is delivered as written",
          server._item_refs(txt_e) == [] and _needs(ge) == ne0 and txt_e in env_e and G.shown(ge) not in env_e, (server._item_refs(txt_e), _needs(ge), ne0, env_e[:300], out_e))
    txt_f = f"{txt_e}; take {G.shown(gf)} from here."
    server._message("home-here", txt_f, "home-other")
    check("handover (c): a board#<n> in the same text still names its item, and the group's item stays unnamed", server._item_refs(txt_f) == [gf] and "ops-alpha-bg" in str(_needs(gf)) and _needs(ge) == ne0, (server._item_refs(txt_f), _needs(gf), _needs(ge)))
    txt_g = f"PR 7 failed on its own (group {ge}, split from {gf})"
    check("handover (c): the driver's 'group g<n>, split from g<n>' form and an upper-case G name no item either, and nothing in them is rewritten",
          server._item_refs(txt_g) == [] and server._shown_ids(txt_g) == txt_g and server._item_refs(f"group {ge.upper()} [{gf.upper()}]") == [], (server._item_refs(txt_g), server._shown_ids(txt_g)))
    check("handover (c): a bare g<n>, a g<n> link and a g<n> beside a group number still name; only the two release forms are skipped",
          server._item_refs(f"take {ge}") == [ge] and server._item_refs(f"[{ge}]({_core_instance.BOARD_URL}/items/{ge[1:]})") == [ge] and server._item_refs(f"group {ge} [{ge}] and {gf}") == [gf], (server._item_refs(f"group {ge} [{ge}] and {gf}"),))
finally:
    server._PUSH, server._gate_front, server._back_agent, server._tell_owner, server._name_on_handover = _push, _gf, _ba, _to, _hand

# ---- 8. the board item: one capped queue. The updates of an existing issue are merged over [github] merge_seconds into one
# PATCH (no comment goes with it any more); a create and a close or reopening go at once; the host's one ledger
# (ghbudget.py) counts the mirror's writes and every counted read, the server's and anchor-hub's, and never a 304; a restart in the middle of a window
# keeps the pending updates.
import types; from stackshot.core import ghbudget as _gb
_ex = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
check("the shipped defaults: 250 writes an hour, 1500 counted reads, a 300 s merge window, the pace still 1.5 s",
      G.DEFAULT_BUDGET == 250 == _gb.DEFAULT_WRITES and G.DEFAULT_READ_BUDGET == 1500 == _gb.DEFAULT_READS and G.DEFAULT_MERGE == 300.0 and G.DEFAULT_PACE == 1.5
      and all(re.search(rf"(?m)^{k} = {v}\b", _ex) for k, v in (("hourly_budget", 250), ("read_budget", 1500), ("merge_seconds", 300), ("min_interval_seconds", "1.5"))),
      (G.DEFAULT_BUDGET, G.DEFAULT_READ_BUDGET, G.DEFAULT_MERGE, G.DEFAULT_PACE))
MERGE_S = 300; write_toml(sync=True, issue_ids=True); server._cfg.reload()
check("[github] merge_seconds is read live", G.merge_seconds() == 300.0, G.merge_seconds())
# three changes of the issue inside the window: held, then one PATCH of the issue with all of them, and no comment
g_m = mk("[home] merge window"); n_m = G.issue_of(g_m, STORE)
check("the fixture: the create went out at once (the issue exists, nothing waits)", n_m and qlen() == 0, (n_m, qlen()))
F.log.clear(); T0 = time.time()
server._update(g_m, description=D("first words"), sender="home-here")
server._update(g_m, next="not on the issue", hold=True, wake="2099-01-01", sender="home-here")
server._update(g_m, subject="[home] merge window renamed", sender="home-here")
server._update(g_m, description=D("second words"), sender="home-here")
jobs_m = [json.loads(q.read_text(encoding="utf-8")) for q in G.pending()]
check("only the changes the issue carries queue a job (three of the four writes; none is urgent; the timestamps are what the window is read from)",
      len(jobs_m) == 3 and not any(j.get("urgent") for j in jobs_m) and all(j["kind"] == "changed" and j["ts"] >= T0 for j in jobs_m), jobs_m)
r = G.drain(GH, STORE, say=lambda s: None, now=T0 + 100)
check("inside the window: nothing is sent for the issue, the three jobs stay on disk, the drain says so", mine(n_m) == [] and qlen() == 3 and r.get("held") == 3 and 150 < r.get("next_due", 0) < 201, (r, mine(n_m), qlen()))
r = G.drain(GH, STORE, say=lambda s: None, now=T0 + 400)
check("when the window has run out: ONE PATCH of the issue for the three jobs, carrying the latest subject and description, and no comment", r["done"] == 3 and qlen() == 0
      and mine(n_m) == [("PATCH", REPO + f"/issues/{n_m}")] and issue(n_m)["title"] == "[home] merge window renamed" and "- second words" in issue(n_m)["body"] and "first words" not in issue(n_m)["body"] and not comments(n_m),
      (r, mine(n_m), issue(n_m)["title"], comments(n_m)))
# a change and its undoing inside one window: the fingerprint says the issue is as it was, nothing is sent
g_v = mk("[home] merge revert"); n_v = G.issue_of(g_v, STORE); F.log.clear(); T1 = time.time()
server._update(g_v, description=D("temporary"), sender="home-here"); server._update(g_v, description=DESC, sender="home-here")
r = G.drain(GH, STORE, say=lambda s: None, now=T1 + 400)
check("a change and its undoing in one window: both jobs go, the issue is already as the item is, so no PATCH at all", r["done"] == 2 and qlen() == 0 and mine(n_v) == [], (r, mine(n_v)))
# a close goes at once, with what waits beside it; a reopening too
g_mc = mk("[home] merge then close"); n_mc = G.issue_of(g_mc, STORE); F.log.clear(); T2 = time.time()
server._update(g_mc, description=D("before the close"), sender="home-here")
r = G.drain(GH, STORE, say=lambda s: None, now=T2 + 5)
check("an update inside the window waits", r.get("held") == 1 and mine(n_mc) == [] and qlen() == 1, (r, mine(n_mc)))
server.stackshot_complete(g_mc, outcome="done", reason="it shipped", outcome_text="- Shipped", sender="home-here")
r = G.drain(GH, STORE, say=lambda s: None, now=T2 + 6)
check("a close goes at once, window or not, and takes the waiting update with it: the issue closed as completed, one PATCH, no comment",
      r["done"] == 2 and qlen() == 0 and issue(n_mc)["state"] == "closed" and issue(n_mc)["state_reason"] == "completed" and [w[0] for w in mine(n_mc)] == ["PATCH"] and "- before the close" in issue(n_mc)["body"] and "## Outcome\n\n- Shipped" in issue(n_mc)["body"] and not comments(n_mc), (r, mine(n_mc)))
F.log.clear(); T3 = time.time()
server._update(g_mc, status="open", next="again", sender="home-here")
r = G.drain(GH, STORE, say=lambda s: None, now=T3 + 1)
check("a reopening goes at once too: the issue open again, one PATCH, no window", r["done"] == 1 and "held" not in r and issue(n_mc)["state"] == "open" and [w[0] for w in mine(n_mc)] == ["PATCH"] and not comments(n_mc), (r, mine(n_mc)))
# a create goes at once (here the one that waited out an outage); the update made after it waits its window
F.down = True; F.log.clear()
out = server._create(subject="[home] created at once", description=DESC, project="projects/alpha", owner="home-here", next="x")
g_n = re.search(r"created (\S+)", out).group(1); T4 = time.time()
server._update(G.norm(g_n), description=D("after the create"), sender="home-here")
F.down = False; nx0 = F.next
r = G.drain(GH, STORE, say=lambda s: None, now=T4 + 10)
check("a create goes at once: the issue is made and the item re-keyed in the first drain; the update made after it waits out its window",
      F.next == nx0 + 1 and r["done"] == 1 and r.get("held") == 1 and qlen() == 1 and (STORE / f"g/{nx0}.json").exists(), (r, F.next, nx0, qlen()))
r = G.drain(GH, STORE, say=lambda s: None, now=T4 + 400)
check("…and goes when it has run out; the issue carries the new description and has no comment", r["done"] == 1 and qlen() == 0 and "- after the create" in issue(nx0)["body"] and not comments(nx0), (r, issue(nx0)["body"][:120]))
# a restart in the middle of a window: the jobs are files, the window their own timestamps. A fresh client and no memory of the first drain
g_r = mk("[home] merge restart"); n_r = G.issue_of(g_r, STORE); g_o = mk("[home] merge other issue"); n_o = G.issue_of(g_o, STORE); F.log.clear(); T5 = time.time()
server._update(g_r, description=D("pending over a restart"), sender="home-here"); server._update(g_o, description=D("an older window"), sender="home-here")
q_o = [q for q in G.pending() if json.loads(q.read_text(encoding="utf-8"))["gid"] == g_o][0]; j_o = json.loads(q_o.read_text(encoding="utf-8")); j_o["ts"] = T5 - 400; q_o.write_text(json.dumps(j_o), encoding="utf-8")
r = G.drain(GH, STORE, say=lambda s: None)
check("the issue whose window has run out goes, the other's stays (windows are per issue)", r["done"] == 1 and "an older window" in issue(n_o)["body"] and mine(n_r) == [] and qlen() == 1 and r.get("held") == 1, (r, qlen()))
pend_before = [q.name for q in G.pending()]
G._CLIENT.clear(); G._EVENT.clear(); GH3 = G.GitHub("o/r", API, "test-token", pace=0.05, shared=True); GH3.sleep = _paced_sleep      # "restart": a new client, the module's memory dropped
check("a restart in the middle of the window keeps the pending job: the same file is still there", [q.name for q in G.pending()] == pend_before and qlen() == 1, G.pending())
r = G.drain(GH3, STORE, say=lambda s: None, now=T5 + 400)
check("…and the new process sends it as one PATCH when the window is over", r["done"] == 1 and qlen() == 0 and "- pending over a restart" in issue(n_r)["body"] and not comments(n_r), (r, mine(n_r)))
# merge_seconds = 0: every update goes at once, as before
MERGE_S = 0; write_toml(sync=True, issue_ids=True); server._cfg.reload()
F.log.clear(); server._update(g_r, description=D("no window"), sender="home-here"); r = G.drain(GH, STORE, say=lambda s: None)
check("merge_seconds = 0: the update goes in the first drain", r["done"] == 1 and "held" not in r and qlen() == 0 and "- no window" in issue(n_r)["body"], (r, G.merge_seconds()))

# ---- the ledger: the writes and the counted reads, never a 304; shared with another process
g_led = mk("[home] ledger"); n_led = G.issue_of(g_led, STORE)
GR = G.GitHub("o/r", API, "test-token", pace=0.0, shared=True); r0, w0, nm0 = _gb.count("r"), _gb.count("w"), F.not_modified
GR.get_issue(n_led); GR.get_issue(n_led)
check("two plain reads are two in the ledger", _gb.count("r") == r0 + 2 and GR.reads == 2, (_gb.count("r"), r0))
GR.request("GET", f"/repos/o/r/issues/{n_led}", etag=True); GR.request("GET", f"/repos/o/r/issues/{n_led}", etag=True); GR.rate_limit()
check("a conditional read answered 304 is not counted (the first of two counts, the second is free), nor is GET /rate_limit",
      _gb.count("r") == r0 + 3 and GR.cached == 1 and F.not_modified == nm0 + 1, (_gb.count("r") - r0, GR.cached, F.not_modified - nm0))
GR.edit_issue(n_led, body="a write on the ledger")
check("a write is a write in the ledger", _gb.count("w") == w0 + 1 and _gb.count("r") == r0 + 3, (_gb.count("w") - w0, _gb.count("r") - r0))
sub = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {STACK!r}); import ghbudget as g; [g.note('r') for _ in range(3)]; g.note('w'); print(g.count('r'), g.count('w'))"],
                     capture_output=True, text=True)
check("another process (anchor-hub's way in) adds to the same ledger: its three reads and one write are counted here", sub.returncode == 0 and _gb.count("r") == r0 + 6 and _gb.count("w") == w0 + 2
      and sub.stdout.split() == [str(r0 + 6), str(w0 + 2)], (sub.stdout, sub.stderr[-300:], _gb.count("r") - r0, _gb.count("w") - w0))
st = _gb.status()
check("the status: the counts and the caps", st["reads"] == r0 + 6 and st["writes"] == w0 + 2 and st["read_cap"] == 100000 and st["write_cap"] == 100000, st)

# ---- the caller tag: each counted call is kept under who made it (ghbudget.CALLERS); no tag, an unknown one, or an older process's is "other"; the totals are untouched
def _cal(): return _gb.by_caller()
def _dc(a, b, kind, who): return b[kind].get(who, 0) - a[kind].get(who, 0)
c0, rt0, wt0 = _cal(), _gb.count("r"), _gb.count("w")
_gb.note("r", caller="step_proof"); _gb.note("r", caller="step_proof"); _gb.note("r", caller="done_check"); _gb.note("w", caller="ghsync")
_gb.note("r"); _gb.note("r", caller="no_such_caller"); _gb.note("r", caller="OTHER"); _gb.take("w", 100000, caller="release")
c1 = _cal()
check("tagged calls are counted per caller (reads and writes apart); an untagged call, an unknown tag and 'other' itself are all 'other'",
      _dc(c0, c1, "reads", "step_proof") == 2 and _dc(c0, c1, "reads", "done_check") == 1 and _dc(c0, c1, "reads", "other") == 3 and _dc(c0, c1, "writes", "ghsync") == 1
      and _dc(c0, c1, "writes", "release") == 1 and _dc(c0, c1, "reads", "ghsync") == 0, (c0, c1))
check("…the totals count every call as before (6 reads' worth of stamps plus the 2 writes), and each kind's callers add up to its total",
      _gb.count("r") == rt0 + 6 and _gb.count("w") == wt0 + 2 and sum(c1["reads"].values()) == _gb.count("r") and sum(c1["writes"].values()) == _gb.count("w"), (c1, _gb.count("r"), _gb.count("w")))
with _gb.tag("event_wait"):
    _gb.note("r"); _gb.note("r", caller="comments")      # the thread's tag for a call with none; a call naming its own keeps it
    with _gb.tag("step_proof"): _gb.note("r")            # tags nest
    _gb.note("r")
_gb.note("r")
c2 = _cal()
check("a thread's tag (with ghbudget.tag) tags the calls made inside it, nests, restores the outer one, and ends with the block",
      _dc(c1, c2, "reads", "event_wait") == 2 and _dc(c1, c2, "reads", "comments") == 1 and _dc(c1, c2, "reads", "step_proof") == 1 and _dc(c1, c2, "reads", "other") == 1 and _gb.current() == "", (c1, c2))
st2 = _gb.status(); pk = _gb.peek()
check("the status keeps its fields and gains by_caller (status and the lock-free peek alike); the side-panel line is unchanged",
      {"reads", "writes", "read_cap", "write_cap"} <= set(st2) and st2["by_caller"] == c2 and pk is not None and pk["by_caller"] == c2 and pk["reads"] == st2["reads"]
      and _gb.calls_line() == f"github calls this hour: writes {st2['writes']}/{st2['write_cap']}, reads {st2['reads']}/{st2['read_cap']}", (st2, pk))
gd_ = G.GitHub("o/r", API, "test-token", pace=0.0, shared=True, caller="ghsync"); gp_ = G.GitHub("o/r", API, "test-token", pace=0.0, shared=True)
a_ = _cal(); gp_.get_issue(n_led); gd_.get_issue(n_led); gd_.edit_issue(n_led, body="tagged write"); b_ = _cal()
with _gb.tag("done_check"): gd_.get_issue(n_led); gp_.get_issue(n_led)
gd_.request("GET", f"/repos/o/r/issues/{n_led}", caller="comments"); c_ = _cal()
check("a client's reads and writes carry its own tag (an untagged client: 'other'); a thread's tag beats the client's; a request's own caller beats both",
      _dc(a_, b_, "reads", "other") == 1 and _dc(a_, b_, "reads", "ghsync") == 1 and _dc(a_, b_, "writes", "ghsync") == 1
      and _dc(b_, c_, "reads", "done_check") == 2 and _dc(b_, c_, "reads", "comments") == 1 and _dc(b_, c_, "reads", "ghsync") == 0, (a_, b_, c_))
class _PrClient:      # the PR reader's client, as the ledger sees it: one counted read per request, kept under the thread's tag
    repo_id = 0
    def repo_path(self, rest=""): return "/repos/o/r" + rest
    def request(self, method, path, **kw): _gb.note("r"); return {"merged": True, "state": "closed", "merged_at": "2026-11-03T00:00:00Z"}
_cg_ = server._check_gh; server._check_gh = lambda repo: _PrClient()
try:
    d_a = _cal(); ok_, err_ = server._check_eval("pr_merged o/r#5", time.time(), {}); d_b = _cal()
finally:
    server._check_gh = _cg_
check("the done check's merged-PR read is kept under 'done_check' in the ledger (and the tag is gone afterwards)", ok_ is True and err_ == "" and _dc(d_a, d_b, "reads", "done_check") == 1 and _dc(d_a, d_b, "reads", "other") == 0 and _gb.current() == "", (d_a, d_b))
sub2 = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {STACK!r}); import ghbudget as g; g.note('r', caller='receivers'); g.note('r', caller='receivers'); g.note('r'); print(g.by_caller()['reads'].get('receivers', 0))"],
                      capture_output=True, text=True)
check("another process's tagged calls are in the same ledger under its tag (anchor-hub's way in: receivers)", sub2.returncode == 0 and sub2.stdout.split() == [str(_cal()["reads"].get("receivers", 0))]
      and _cal()["reads"].get("receivers", 0) - c_["reads"].get("receivers", 0) == 2, (sub2.stdout, sub2.stderr[-300:]))
# a ledger written before the tags (no "by" key) reads with every call 'other', and the next save keeps it and adds the key; a "by" in a damaged shape is no tags
led_ = G._cfg.state("github", "budget.json"); n_ = time.time()
led_.write_text(json.dumps({"w": [n_ - 5] * 2, "r": [n_ - 5] * 7}), encoding="utf-8")
check("a ledger line of the old format (w and r only) still reads: counts as before, all 'other'", _gb.count("r") == 7 and _gb.count("w") == 2 and _gb.by_caller() == {"reads": {"other": 7}, "writes": {"other": 2}}, (_gb.count("r"), _gb.by_caller()))
_gb.note("r", caller="step_proof"); on_ = json.loads(led_.read_text(encoding="utf-8"))
check("…the next write keeps the old stamps in w and r (the same meaning), adds the tagged one to both r and by, and the callers still add up",
      len(on_["r"]) == 8 and len(on_["w"]) == 2 and len(on_["by"]["r"]["step_proof"]) == 1 and on_["by"]["w"] == {} and _gb.by_caller()["reads"] == {"other": 7, "step_proof": 1}, on_)
for bad_ in ({"w": [n_], "r": [n_], "by": 5}, {"w": [n_], "r": [n_], "by": {"r": [n_], "w": {"ghsync": "x", "nonsense": [n_], "other": [n_]}}}, {"w": [n_], "r": [n_], "by": {"r": {"step_proof": [True, "x", None, n_ - 9000, n_ + 9000]}}}):
    led_.write_text(json.dumps(bad_), encoding="utf-8")
    check(f"a damaged 'by' ({str(bad_['by'])[:48]}) is no tags: the totals still read and every call is 'other'", _gb.count("r") == 1 and _gb.count("w") == 1 and _gb.by_caller() == {"reads": {"other": 1}, "writes": {"other": 1}}, _gb.by_caller())
led_.unlink()
# a ledger written by a process of the old code (it drops "by" on its save) is harmless: the stamps stay, the tags of that hour fall to 'other'
_gb.note("r", caller="step_proof"); led_.write_text(json.dumps({k_: v_ for k_, v_ in json.loads(led_.read_text(encoding="utf-8")).items() if k_ != "by"}), encoding="utf-8")
check("…a file an older process rewrote without 'by' keeps its stamps and reads them as 'other'", _gb.count("r") == 1 and _gb.by_caller()["reads"] == {"other": 1}, _gb.by_caller())
led_.unlink()
# a stamp is kept to a tenth of a second rounded DOWN: rounded up it sat ahead of the clock, and a read refused within 50 ms of the one that filled the cap was told to wait an hour and a hair
fr_ = float(int(time.time())) + 0.96          # a call at .96 s: rounding to the nearest tenth would store it at the next whole second, 0.04 s ahead
_gb.note("r", now=fr_, caller="step_proof"); fl_ = json.loads(led_.read_text(encoding="utf-8"))
check("a stamp is never saved ahead of the call's own time (the list and the caller's list alike), so the wait for room is never over an hour",
      fl_["r"] == [round(fr_ - 0.06, 1)] and fl_["by"]["r"]["step_proof"] == fl_["r"] and _gb.wait("r", 1, now=fr_) <= 3600.0 and 3599 < _gb.wait("r", 1, now=fr_ + 0.5) <= 3600.0, (fl_, _gb.wait("r", 1, now=fr_)))
led_.unlink()
# the read cap: refused over it, nothing sent; the queue's own reads are counted but never held
READS = _gb.count("r") + 1; write_toml(sync=True, issue_ids=True); server._cfg.reload()
GR.get_issue(n_led); nlog = len(F.log)
try: GR.get_issue(n_led); capped = None
except G.GitHubBudget as e: capped = e
check("over the read cap: the read is refused with the seconds to wait, as a GitHubDown with no status, and not sent", capped is not None and isinstance(capped, G.GitHubDown) and capped.status == 0
      and 3000 < capped.retry_after <= 3600 and str(capped).startswith("GitHub reads are held by the hourly cap (") and "they resume in about" in str(capped) and len(F.log) == nlog, (capped, len(F.log) - nlog, getattr(capped, "status", None), getattr(capped, "retry_after", None)))
rc = _gb.count("r"); G._UNCAPPED.on = True
try: GR.get_issue(n_led)
finally: G._UNCAPPED.on = False
check("…the reads of a write job are counted all the same, never held", _gb.count("r") == rc + 1, (_gb.count("r"), rc))
READS = 100000; write_toml(sync=True, issue_ids=True); server._cfg.reload()
# the write cap in the ledger: a client made after a restart still knows the hour
HOURLY = _gb.count("w") + 2; write_toml(sync=True, issue_ids=True); server._cfg.reload()
GW = G.GitHub("o/r", API, "test-token", pace=0.0, shared=True); slept = []
def _would_sleep(w): slept.append(w); raise RuntimeError("would sleep")
GW.sleep = _would_sleep
GW.edit_issue(n_led, title="ledger w1"); GW.edit_issue(n_led, title="ledger w2")
try: GW.edit_issue(n_led, title="ledger w3"); third = "sent"
except RuntimeError: third = "waits"
check("the write cap counts in the ledger: two writes under it go, the third waits for the hour (a client with an empty memory included)",
      third == "waits" and len(slept) == 1 and 3000 < slept[0] <= 3600 and issue(n_led)["title"] == "ledger w2" and GW.recent_writes() >= HOURLY, (third, slept, issue(n_led)["title"]))
HOURLY = 100000; write_toml(sync=True, issue_ids=True); server._cfg.reload()

# ---- the create is never refused by the read cap; the merged comment is split only by its own trailer; the span of a group; the ledger's failures
def set_caps(reads=None, writes=None, merge=None):
    global READS, HOURLY, MERGE_S
    if reads is not None: READS = reads
    if writes is not None: HOURLY = writes
    if merge is not None: MERGE_S = merge
    write_toml(sync=True, issue_ids=True); server._cfg.reload()
set_caps(reads=_gb.count("r"))
G._CLIENT.clear(); cl_ = G.client(); nlog = len(F.log)
g_sp = G.norm(made("[home] created under a spent read cap")[0]); n_sp = G.issue_of(g_sp, STORE)
check("the read cap spent: the create still returns the item's own issue number (g<n>), never a temporary id (l<n>); the slim create is one POST and reads nothing",
      g_sp.startswith("g") and not G.is_local(g_sp) and n_sp and not any(m_ == "GET" for m_, p_, _t in F.log[nlog:]), (g_sp, n_sp, F.log[nlog:nlog + 3]))
check("…and a plain read of this process is still refused over the cap", _gb.wait("r") > 0, _gb.status())
try:
    with G.uncapped(): G.client().list_issues()
    lookup = "read"
except G.GitHubBudget: lookup = "held"
check("…while a write job's own reads (the marker lookup of a create whose answer was lost) are made over the cap, never held", lookup == "read", lookup)
with G.uncapped():
    with G.uncapped(): pass
    inner = getattr(G._UNCAPPED, "on", False)
    G.drain(GH, STORE, say=lambda s: None)
    after_drain = getattr(G._UNCAPPED, "on", False)
check("uncapped() nests: leaving the inner one leaves the outer on, a drain inside it leaves it on, and the flag is off again after", inner and after_drain and not getattr(G._UNCAPPED, "on", False), (inner, after_drain))
set_caps(reads=100000)
set_caps(merge=0)

# ---- a create never waits out the hour's write budget: the budget spent by queued mirror writes, the worker waiting for room with the line held, a create answers at
# once with a temporary id; its issue is the first job of the queue, made when room appears, and the item is re-keyed to the issue's number
G._CLIENT.clear(); set_caps(writes=100000)
bk = [G.norm(made(f"[home] backlog {i}")[0]) for i in range(4)]
for g_ in bk: server._update(g_, description=D(f"edit of {g_}"), sender="home-here")
check("four updates wait in the queue as live jobs", qlen() == 4 and all(json.loads(p_.read_text())["kind"] == "changed" for p_ in G.pending()), [p_.name for p_ in G.pending()])
c0 = _gb.count("w"); set_caps(writes=c0 + 1); G._CLIENT.clear(); cl_ = G.client()      # one write left this hour
check("the server's client holds the narrowed budget", cl_.budget == c0 + 1 and cl_.shared, (cl_.budget, c0))
gate = threading.Event(); waiting_ = []
def _hold(w): waiting_.append(w); gate.wait(60)
cl_.sleep = _hold; cl_.pace = 0.0
wk = threading.Thread(target=lambda: G.drain(cl_, STORE, say=lambda s: None), daemon=True); wk.start()
for _ in range(150):
    if waiting_: break
    time.sleep(0.1)
try:
    check("the worker spent the hour's last write on the first update and now waits for room (holding the line)", bool(waiting_) and waiting_[0] > 1000 and _gb.wait("w") > 1000, (waiting_, _gb.wait("w")))
    G.CREATE_WAIT = 0.3
    posts0 = [w_ for w_ in writes() if w_ == ("POST", REPO + "/issues")]
    t0_ = time.monotonic(); out_h = server._create(subject="[home] created while the hour's writes are spent", description=DESC, project="projects/alpha", owner="home-here", next="x"); took_ = time.monotonic() - t0_
    g_tmp = G.norm(re.search(r"created (\S+)", out_h).group(1))
    check("the create answers within moments, not after the hour: a temporary id, and the reply says so and why",
          took_ < 5 and out_h.startswith("created board-tmp-boxa#") and "is a temporary id" in out_h and "taking no new write right now" in out_h and "when GitHub has room" in out_h, (took_, out_h[:300]))
    check("…the item is stored under the local letter, no issue was made, and its create is the first job of the queue, ahead of the three older updates",
          G.is_local(g_tmp) and (STORE / "l" / f"{g_tmp[1:]}.json").exists() and [w_ for w_ in writes() if w_ == ("POST", REPO + "/issues")] == posts0 and qlen() == 4
          and G.pending()[0].name.startswith(G.FIRST) and json.loads(G.pending()[0].read_text()) ["gid"] == g_tmp and json.loads(G.pending()[0].read_text())["kind"] == "created", ([p_.name for p_ in G.pending()], g_tmp))
    nlog_ = len(F.log)
    try: cl_.create_issue("x", "y", max_wait=0.2); held_ = None
    except G.GitHubBudget as e_: held_ = e_
    check("a write that may not wait is refused as GitHubBudget (a GitHubDown) with the hour's wait, and sends nothing",
          isinstance(held_, G.GitHubDown) and held_.status == 0 and held_.retry_after > 1000 and str(held_).startswith("GitHub writes are held by the hourly cap (") and len(F.log) == nlog_, (held_, len(F.log) - nlog_))
    solo = G.GitHub("o/r", API, "test-token", pace=0.0, budget=1)      # a client of its own counts its own writes
    solo.edit_issue(G.issue_of(bk[0], STORE), title="solo"); nlog_ = len(F.log)
    try: solo.request("PATCH", solo.repo_path(f"/issues/{G.issue_of(bk[0], STORE)}"), {"title": "solo 2"}, max_wait=0.2); held2 = None
    except G.GitHubBudget as e_: held2 = e_
    check("…the same for a client that counts in its own memory, and a write with no max_wait is not changed (it would wait: the worker's way)", held2 is not None and 3000 < held2.retry_after <= 3600 and len(F.log) == nlog_
          and issue(G.issue_of(bk[0], STORE))["title"] == "solo", (held2, len(F.log) - nlog_))
    _gb._txn(time.time(), lambda d: d.__setitem__("w", [t_ - 3700 for t_ in d["w"]]), True)       # the hour's writes age out: there is room
    check("the hour's room is back in the ledger", _gb.wait("w") == 0, _gb.status())
finally:
    gate.set()
wk.join(30)
cl_.sleep = time.sleep
order_ = [(m_, p_) for m_, p_, _t in F.log if m_ in ("POST", "PATCH")]
i_post = max(k for k, w_ in enumerate(order_) if w_ == ("POST", REPO + "/issues")); i_b2, i_b3 = (max(k for k, w_ in enumerate(order_) if w_ == ("PATCH", REPO + f"/issues/{G.issue_of(g_, STORE)}")) for g_ in bk[2:])
g_new = G.resolve(g_tmp); n_new = G.issue_of(g_new, STORE)
check("the waiting worker took the place that freed, then the create queued while it waited (not the rest of its list first), then the other updates; the queue is empty",
      not wk.is_alive() and qlen() == 0 and i_post < i_b2 < i_b3 and all(f"edit of {G.shown(g_)}" in issue(G.issue_of(g_, STORE))["body"] for g_ in bk), (wk.is_alive(), qlen(), i_post, i_b2, i_b3))
check("the temporary item has its issue and is re-keyed: board#<n>, the temporary id an alias, the local file gone",
      g_new.startswith("g") and n_new and issue(n_new)["title"] == "[home] created while the hour's writes are spent"
      and G.load_map(STORE)["aliases"].get(g_tmp) == g_new and not (STORE / "l" / f"{g_tmp[1:]}.json").exists() and (STORE / g_new[0] / f"{g_new[1:]}.json").exists(), (g_new, n_new))
out_ok = server._create(subject="[home] created with room again", description=DESC, project="projects/alpha", owner="home-here", next="x")
check("with room under the budget a create takes its issue number straight away", out_ok.startswith("created board#") and "temporary" not in out_ok, out_ok[:120])
G.CREATE_WAIT = 5.0; G._CLIENT.clear(); set_caps(writes=100000); G.drain(GH, STORE, say=lambda s: None)
check("CREATE_WAIT is a few seconds", G.CREATE_WAIT == 5.0)

# a bulk repair's description sync is a background job: behind every live job, never a create, never waking the worker
g_bg = bk[0]; f_bg = STORE / g_bg[0] / f"{g_bg[1:]}.json"
snap("before the close"); it_bg = json.loads(f_bg.read_text())
it_bg.update(status="completed", description="- It ended well", state_updated=time.time(), updated=time.time()); it_bg["metadata"].update(outcome="done", reason="it is in")
f_bg.write_text(json.dumps(it_bg))
rows_bg, skip_bg = server._close_description_repair(apply=True)
jobs_bg = [(p_.name, json.loads(p_.read_text())) for p_ in G.pending()]
check("the close repair restores the description and queues its sync as a background body sync: after every live job, and no create or close job",
      any(r_["gid"] == g_bg for r_ in rows_bg) and rd(g_bg[0], int(g_bg[1:]))["description"] == D(f"edit of {G.shown(g_bg)}") and jobs_bg
      and all(n_.startswith(G.BACKGROUND) and j_["kind"] == "sync" for n_, j_ in jobs_bg) and any(j_["gid"] == g_bg for _n, j_ in jobs_bg), (rows_bg, jobs_bg, skip_bg))
server._update(bk[1], description=D("a live edit behind the repair"), sender="home-here")
check("a live update queued after the repair still sorts before its sync jobs", not G.pending()[0].name.startswith(G.BACKGROUND) and json.loads(G.pending()[0].read_text())["gid"] == bk[1], [p_.name for p_ in G.pending()])
G.drain(GH, STORE, say=lambda s: None)
check("the repair's body sync reaches the issue (one PATCH), once the live job has gone", "edit of" in issue(G.issue_of(g_bg, STORE))["body"] and qlen() == 0, (qlen(), issue(G.issue_of(g_bg, STORE))["body"][:200]))
p_a = G.on_change("g1", full, {**full, "description": "- x"}, background=True); ja = json.loads(p_a.read_text()); p_a.unlink()
p_b = G.on_change("g1", full, {**full, "status": "completed", "metadata": {"outcome": "done"}}, background=True); jb_ = json.loads(p_b.read_text()); p_b.unlink()
p_c = G.on_change("l9", None, full, background=True); jc_ = json.loads(p_c.read_text()); p_c.unlink()
p_d = G.on_change("g1", None, full); jd_ = json.loads(p_d.read_text()); p_d.unlink()
check("on_change(background): a description change is a background sync; a close or a create is never one (a live job)",
      p_a.name.startswith(G.BACKGROUND) and ja["kind"] == "sync" and not p_b.name.startswith(G.BACKGROUND) and jb_["kind"] == "changed" and jb_["urgent"]
      and not p_c.name.startswith(G.BACKGROUND) and jc_["kind"] == "created", (p_a.name, p_b.name, p_c.name))
check("only the create job of a temporary item (a local id) goes first in the queue: a create whose issue was made inline (only its marker PATCH left) keeps its place in line",
      p_c.name.startswith(G.FIRST) and not p_d.name.startswith(G.FIRST) and not p_d.name.startswith(G.BACKGROUND) and jd_["kind"] == "created", (p_c.name, p_d.name))
slow = G.GitHub("o/r", API, "test-token", pace=30.0, budget=100); slow.edit_issue(G.issue_of(bk[0], STORE), title="slow"); nlog_ = len(F.log)
try: slow.request("PATCH", slow.repo_path(f"/issues/{G.issue_of(bk[0], STORE)}"), {"title": "slow 2"}, max_wait=0.3); held3 = None
except G.GitHubBudget as e_: held3 = e_
check("max_wait is one deadline over the line, the pace and the ledger: a pace longer than it refuses the write at once, nothing sent", held3 is not None and 25 < held3.retry_after <= 30 and len(F.log) == nlog_, (held3, len(F.log) - nlog_))

# the ledger's failures: a corrupt or odd file is a fresh hour, a huge one is trimmed, a folder it cannot write or a lock held too long falls back to memory without raising
led = G._cfg.state("github", "budget.json")
led.write_text("{not json at all", encoding="utf-8")
check("a corrupt ledger file reads as an empty hour", _gb.count("r") == 0 and _gb.count("w") == 0)
led.write_text(json.dumps({"w": 5, "r": {"a": 1}}), encoding="utf-8")
check("a ledger whose lists are not lists reads as empty", _gb.count("r") == 0 and _gb.count("w") == 0)
led.write_text(json.dumps({"w": [True, "x", None, 1.0, [3]], "r": [9e18, -5, time.time() + 9999]}), encoding="utf-8")
check("…stamps that are no numbers, or are outside the hour, are not counted", _gb.count("r") == 0 and _gb.count("w") == 0, (_gb.count("r"), _gb.count("w")))
set_caps(reads=10, writes=10)
now_ = time.time(); led.write_text(json.dumps({"w": [now_ - 5] * 300, "r": [now_ - i * 0.01 for i in range(1000)]}), encoding="utf-8")
_gb.note("r"); sz = json.loads(led.read_text(encoding="utf-8"))
check("a large ledger is trimmed to the newest 4 x cap stamps of each list at the next save (reads and writes alike)", len(sz["r"]) == 40 and len(sz["w"]) == 40 and sz["r"] == sorted(sz["r"]), (len(sz["r"]), len(sz["w"])))
set_caps(reads=100000, writes=100000)
led.unlink()
gdir = G._cfg.state("github"); gdir.chmod(0o500)
try:
    err_ = ""
    try: w_ = _gb.take("w", 5, caller="release"); _gb.note("r", caller="step_proof"); mem_ = ({k: list(v) for k, v in _gb._MEM.items() if k != "by"}, {k: {c: list(s) for c, s in v.items()} for k, v in _gb._MEM["by"].items()})
    except Exception as e_: err_ = repr(e_)
finally: gdir.chmod(0o700)
check("a folder the ledger cannot be written in: no exception, the call is counted in the process's memory (a take still answers 0.0)", not err_ and w_ == 0.0, (err_,))
check("…and the memory fallback keeps what the file would: a stamp in its list and under the caller's tag, a write's apart from a read's",
      not err_ and len(mem_[0]["r"]) == 1 and len(mem_[0]["w"]) == 1 and set(mem_[1]["r"]) == {"step_proof"} and set(mem_[1]["w"]) == {"release"}
      and mem_[1]["r"]["step_proof"] == mem_[0]["r"] and mem_[1]["w"]["release"] == mem_[0]["w"], (err_, mem_))
import fcntl
_lw = _gb.LOCK_WAIT_S; _gb.LOCK_WAIT_S = 0.3
fd_ = os.open(str(gdir / _gb.LOCK_NAME), os.O_RDWR | os.O_CREAT); fcntl.flock(fd_, fcntl.LOCK_EX); t0_ = time.monotonic()
try: _gb.note("r"); w2_ = _gb.wait("r", 5); err2 = ""
except Exception as e_: err2 = repr(e_); w2_ = None
finally:
    took = time.monotonic() - t0_; os.close(fd_); _gb.LOCK_WAIT_S = _lw
check("a lock held too long: the call waits at most its deadline, then uses memory, and raises nothing", not err2 and 0.25 <= took < 5, (err2, took))
led.unlink(missing_ok=True); _gb._MEM["r"].clear(); _gb._MEM["w"].clear(); _gb._MEM["by"] = {"w": {}, "r": {}}
procs_ = [subprocess.Popen([sys.executable, "-c", f"import sys; sys.path.insert(0, {STACK!r}); import ghbudget as g\nfor _ in range(40): g.note('r'); g.note('w')"]) for _ in range(6)]
rcs_ = [p_.wait(timeout=120) for p_ in procs_]
check("six processes noting 40 reads and 40 writes each, at once, add up exactly: 240 and 240, none lost to the lock", rcs_ == [0] * 6 and _gb.count("r") == 240 and _gb.count("w") == 240, (rcs_, _gb.count("r"), _gb.count("w")))

# ---- anchor-hub's reads go through the same ledger (anchorhub/github.py, the gh CLI): counted, a 304 free, the pass cut short over the cap
import stackshot.anchors.anchorhub.core as ahc; import stackshot.anchors.anchorhub.github as ghr
AN = "github:example-owner/stackshot#26"; NA = "github:example-owner/stackshot@notifications"; RP = "/repos/example-owner/stackshot"; calls = []; ghcli = {"304": False}; call_args = []; FAILS = set()
NPATH = f"{RP}/notifications?all=true&per_page=50"
def thread(updated): return {"id": "t1", "updated_at": updated, "reason": "comment", "subject": {"type": "Issue", "url": "https://api.github.com/repos/example-owner/stackshot/issues/5", "title": "a thread"}, "repository": {"id": 7}}
GHD = {"/user": {"login": "example-owner"}, f"{RP}/pulls/26": {"head": {"sha": "a" * 40, "ref": "x/y"}, "user": {"login": "example-owner"}, "base": {"repo": {"id": 7}}},
       f"{RP}/commits/{'a' * 40}/check-runs?per_page=100": {"check_runs": [{"name": "suites", "status": "completed", "conclusion": "success"}]},
       f"{RP}/issues/26": {"state": "open", "comments": 0, "updated_at": "2026-10-28T00:00:00Z", "title": "a thing", "html_url": "https://github.com/example-owner/stackshot/pull/26", "pull_request": {"merged_at": None}},
       NPATH: [thread("2026-10-28T00:00:00Z")], f"{RP}/issues/5": {"state": "open", "comments": 1, "updated_at": "2026-10-28T02:00:00Z", "title": "a thread", "html_url": "https://github.com/example-owner/stackshot/issues/5"},
       f"{RP}/issues/5/comments?since=2026-10-28T00:00:00Z&per_page=50": []}
def _fake_gh(args, capture_output=True, text=True, timeout=30):
    a = [x for x in args[2:] if x != "-i" and x != "-H" and not x.startswith("If-None-Match")]; path = a[0]; cond = "-i" in args; calls.append(path); call_args.append(list(args))
    if path in FAILS: return types.SimpleNamespace(returncode=1, stdout="", stderr="gh: Server Error (HTTP 500)")
    if cond and ghcli["304"] and "-H" in args and path != "/user": return types.SimpleNamespace(returncode=0, stdout="HTTP/2.0 304 Not Modified\n\n", stderr="")     # a 304 only for a validator that was sent
    body = json.dumps(GHD[path]); return types.SimpleNamespace(returncode=0, stdout=("HTTP/2.0 200 OK\netag: \"x\"\n\n" + body) if cond else body, stderr="")
class _Stop(Exception): pass
def _no_sleep(s): raise _Stop()
caught = []; _sub, _thr, _tim = ghr.subprocess, ghr.threading, ghr.time
ghr.subprocess = types.SimpleNamespace(run=_fake_gh, TimeoutExpired=subprocess.TimeoutExpired)
ghr.threading = types.SimpleNamespace(Thread=lambda target, daemon=True: types.SimpleNamespace(start=lambda: caught.append(target)))
ghr.time = types.SimpleNamespace(time=time.time, sleep=_no_sleep)
NK = ahc._anc.anchor_id(NA) or NA
hub = ahc.Hub(); hub.write_status = lambda: None; hub.emit = lambda ev: None; hub.bindings = {AN: {OWNER}}
warned = []
class _Cap(logging.Handler):
    def emit(self, rec): warned.append(rec.getMessage())
_caph = _Cap(level=logging.WARNING); ahc.log.addHandler(_caph)
def one_pass():
    try: caught[0]()
    except _Stop: pass
def reads(): return _gb.count("r")
def set_reads(n):
    global READS
    READS = n; write_toml(sync=True, issue_ids=True); server._cfg.reload()
try:
    a0 = reads(); ghr.run(hub)
    check("anchor-hub: the start-up read (GET /user) is in the ledger", reads() == a0 + 1 and calls == ["/user"], (reads() - a0, calls))
    one_pass()
    check("anchor-hub: a pass reads the pull request, its check runs and the issue: three counted reads in the shared ledger", reads() == a0 + 4 and len(calls) == 4, (reads() - a0, calls))
    ghcli["304"] = True; one_pass()
    check("anchor-hub: a pass whose conditional reads all answer 304 adds nothing to it", len(calls) == 7 and reads() == a0 + 4, (reads() - a0, len(calls)))
    # a comments read that fails after the issue's 200: the issue's ETag is forgotten, so the next pass reads it again instead of being told 304
    GHD[f"{RP}/issues/26"] = {**GHD[f"{RP}/issues/26"], "comments": 1, "updated_at": "2026-10-28T01:00:00Z"}
    CPATH = f"{RP}/issues/26/comments?since=2026-10-28T00:00:00Z&per_page=20"; GHD[CPATH] = [{"user": {"login": "kim"}, "body": "why?", "html_url": "https://x/c1", "created_at": "2026-10-28T01:00:00Z"}]
    FAILS.add(CPATH); ghcli["304"] = False; one_pass()
    check("anchor-hub: the issue changed and its comments read failed: the issue's ETag is dropped (the next pass reads it again)", f"{RP}/issues/26" not in hub.gh_state["etags"] and f"{RP}/issues/26" in [c for c in calls[-3:]], (list(hub.gh_state["etags"]), calls[-3:]))
    FAILS.discard(CPATH); ghcli["304"] = True; ni = len(calls); one_pass()
    iargs = [a for a in call_args[ni:] if f"{RP}/issues/26" in a]
    check("anchor-hub: …and that pass sends the issue read with no validator (a 200, not a 304), reads the comments, and keeps going", len(iargs) == 1 and "-H" not in iargs[0] and CPATH in calls[ni:], (iargs, calls[ni:]))
    # notifications: a thread whose news read fails is not marked seen (and the list's ETag is dropped); the cap spent mid-list stops the loop the same way
    hub.bindings = {AN: {OWNER}, NA: {OWNER}}; ghcli["304"] = False; one_pass()          # seeds the thread list
    seen = hub.gh_state["state"][NK]["threads"]
    check("anchor-hub: notifications seed the thread list", seen == {"t1": "2026-10-28T00:00:00Z"}, seen)
    GHD[NPATH] = [thread("2026-10-28T03:00:00Z")]; FAILS.add(f"{RP}/issues/5"); one_pass()
    check("anchor-hub: a thread whose read failed goes back to what was seen (it is news again next pass); the list's ETag is dropped", hub.gh_state["state"][NK]["threads"] == {"t1": "2026-10-28T00:00:00Z"} and NPATH not in hub.gh_state["etags"], (hub.gh_state["state"][NK], list(hub.gh_state["etags"])))
    FAILS.discard(f"{RP}/issues/5"); ghcli["304"] = True; ni = len(calls); set_reads(reads() + 1); one_pass()
    check("anchor-hub: with the cap spent in the middle of the thread list the loop stops: no thread read, the thread still unseen, no ETag kept",
          f"{RP}/issues/5" not in calls[ni:] and hub.gh_state["state"][NK]["threads"] == {"t1": "2026-10-28T00:00:00Z"} and NPATH not in hub.gh_state["etags"], (calls[ni:], hub.gh_state["state"][NK]))
    set_reads(100000); one_pass()
    check("anchor-hub: with room again the thread is read and seen", hub.gh_state["state"][NK]["threads"] == {"t1": "2026-10-28T03:00:00Z"}, hub.gh_state["state"][NK])
    # the cap spent before a pass: nothing is run, the pass is not a finished check (health False with the reason, no last_pass), one warning for the state
    hub.bindings = {AN: {OWNER}}; ghcli["304"] = False
    lp = hub.status["github"]["last_pass"]; time.sleep(0.01); set_reads(reads()); n_calls = len(calls); warned.clear(); one_pass(); one_pass()
    rcv = hub.status["receivers"]["github"]
    check("anchor-hub: with the read cap spent the pass reads nothing (the gh CLI is not run)", len(calls) == n_calls, len(calls) - n_calls)
    check("anchor-hub: …it reports health False with 'reads held by the hourly cap, resume in …' and does not set last_pass", rcv["ok"] is False and rcv["error"].startswith("reads held by the hourly cap, resume in ") and hub.status["github"]["last_pass"] == lp, (rcv, lp))
    check("anchor-hub: …and logs the cap once for the state, not once a pass", len([w for w in warned if "cut short" in w]) == 1, warned)
    set_reads(100000); one_pass()
    check("anchor-hub: with room again the pass runs, health is True and last_pass moves", hub.status["receivers"]["github"]["ok"] is True and hub.status["github"]["last_pass"] > lp, (hub.status["receivers"]["github"], lp))
    # an anchor added after the merge: the first read of a pull request that merged within the last day writes its merge line (the merge log and the event log) instead of seeding silently
    set_reads(100000); LH = 3600
    def add_pr(n, merged_ago=None, state="closed", body="", closed_ago=None, rp=RP):
        at = None if merged_ago is None else iso(time.time() - merged_ago)
        recent = None if closed_ago is None else iso(time.time() - closed_ago)      # closed unmerged a moment ago: recent closed_at and updated_at, no merged_at
        GHD[f"{rp}/pulls/{n}"] = GHD[f"{RP}/pulls/26"]
        GHD[f"{rp}/issues/{n}"] = {"state": state, "comments": 0, "updated_at": at or recent or "2026-10-28T00:00:00Z", "title": f"pr {n}", "html_url": f"https://github.com/{rp[7:]}/pull/{n}", "body": body, "closed_by": {"login": "alice"},
                                   "closed_at": at or recent, "pull_request": {"merged_at": at}}
    def lines13(n):
        m = [r for r in ahc._merges.read(0)[0] if r["n"] == n]; e = [r for r in ahc._events.read(0)[0] if r["n"] == n]
        return m, e
    def fresh_hub(ids):
        h = ahc.Hub(); h.write_status = lambda: None; told = []; h.emit = told.append; h.bindings = {(n if isinstance(n, str) else f"github:example-owner/stackshot#{n}"): {OWNER} for n in ids}; h.told = told
        del caught[:]; ghr.run(h); return h
    def pass_of(h):
        try: caught[0]()
        except _Stop: pass
    ahc._merges.path().unlink(missing_ok=True); ahc._events.path().unlink(missing_ok=True)
    add_pr(60, 2 * LH); add_pr(61, 30 * LH); add_pr(62, None, state="closed"); add_pr(63, -3 * LH); add_pr(64, None, state="open"); add_pr(65, 30)
    h13 = fresh_hub([60, 61, 62, 63, 64, 65]); pass_of(h13)
    m60, e60 = lines13(60)
    check("anchor-hub: an anchor first read on a pull request that merged 2 hours ago writes its merge line (the merge log and the event log, once)", len(m60) == 1 and len(e60) == 1 and e60[0]["kind"] == "merged" and m60[0]["repo"] == "example-owner/stackshot", (m60, e60))
    check("anchor-hub: …the event log line is stamped at the time it merged, not at the hub's now", abs(e60[0]["ts"] - (time.time() - 2 * LH)) < 5, e60)
    check("anchor-hub: …a merge 30 hours ago, a pull request closed unmerged, one still open, and a merge time in the future are silent seeds: no line, state seeded",
          all(lines13(n) == ([], []) for n in (61, 62, 63, 64)) and all(f"github:example-owner/stackshot#{n}" in h13.gh_state["state"] for n in (60, 61, 62, 63, 64)), [lines13(n) for n in (61, 62, 63, 64)])
    check("anchor-hub: a merge half a minute ago is within the window (the hub's clock may be a little behind GitHub's)", len(lines13(65)[0]) == 1, lines13(65))
    check("anchor-hub: the merge line is only recorded: the sessions of the anchor get no notice for it", h13.told == [], h13.told)
    n_m, n_e = len(ahc._merges.read(0)[0]), len(ahc._events.read(0)[0]); pass_of(h13); pass_of(h13)
    check("anchor-hub: a second pass writes nothing more", (len(ahc._merges.read(0)[0]), len(ahc._events.read(0)[0])) == (n_m, n_e), (n_m, n_e))
    h13b = fresh_hub([60, 65]); pass_of(h13b)
    check("anchor-hub: a hub that starts with nothing saved reads the anchor first again and writes no second line for the merge (the logs hold it already)", (len(ahc._merges.read(0)[0]), len(ahc._events.read(0)[0])) == (n_m, n_e), (len(ahc._merges.read(0)[0]), len(ahc._events.read(0)[0]), n_m, n_e))
    # a line that could not be written: the anchor is not seeded and its ETag is dropped, so the next pass reads the pull request again and writes it; the merge log carries the time it merged
    ahc._merges.path().unlink(missing_ok=True); ahc._events.path().unlink(missing_ok=True); add_pr(67, 2 * LH)
    real_note = ahc._merges.note; boom = [True]
    def failing_note(*a, **k):
        if boom[0]: raise OSError("disk full")
        return real_note(*a, **k)
    ahc._merges.note = failing_note
    try:
        h13d = fresh_hub([67]); pass_of(h13d); K67 = "github:example-owner/stackshot#67"
        check("anchor-hub: a merge line that could not be written leaves the anchor unseeded, its issue ETag dropped, and no line in the event log", K67 not in h13d.gh_state["state"] and f"{RP}/issues/67" not in h13d.gh_state["etags"] and lines13(67)[1] == [], (list(h13d.gh_state["state"]), list(h13d.gh_state["etags"])))
        boom[0] = False; ghcli["304"] = True; pass_of(h13d)
    finally:
        ahc._merges.note = real_note; ghcli["304"] = False
    m67, e67 = lines13(67)
    check("anchor-hub: …the next pass reads it again, writes the merge line (the merge log stamped at the time it merged) and seeds", K67 in h13d.gh_state["state"] and len(m67) == 1 and abs(m67[0]["ts"] - (time.time() - 2 * LH)) < 5 and len(e67) == 1, (m67, e67))
    # the first-read condition and the window's edges
    ahc._merges.path().unlink(missing_ok=True); ahc._events.path().unlink(missing_ok=True)
    add_pr(68, 24.5 * LH); add_pr(69, None, state="closed", closed_ago=2 * LH)
    pass_of(fresh_hub([68, 69]))
    check("anchor-hub: a merge 24.5 hours ago (the window is 24) writes neither log", lines13(68) == ([], []), lines13(68))
    check("anchor-hub: a pull request closed unmerged 2 hours ago (recent closed_at and updated_at, no merged_at) writes neither log", lines13(69) == ([], []), lines13(69))
    # a live open-to-merged transition is the ordinary merge event, exactly one line per log: the late path is the first read's alone
    add_pr(70, None, state="open"); h70 = fresh_hub([70]); h70.emit = lambda ev: ahc.Hub.log_activity(h70, ev)      # emit's own first step: the two log lines
    pass_of(h70); check("anchor-hub: an open pull request's first read writes no line", lines13(70) == ([], []), lines13(70))
    add_pr(70, 1 * LH); pass_of(h70); m70, e70 = lines13(70)
    check("anchor-hub: …and its merge, seen live, writes exactly one line in each log (the ordinary event, no late line before it)", len(m70) == 1 and len(e70) == 1, (m70, e70))
    # the same number in two repositories is two pull requests
    OP = "/repos/example-owner/other"; add_pr(73, 2 * LH); add_pr(73, 2 * LH, rp=OP)
    pass_of(fresh_hub([73, "github:example-owner/other#73"]))
    got73 = sorted(r["repo"] for r in ahc._events.read(0)[0] if r["n"] == 73); got73m = sorted(r["repo"] for r in ahc._merges.read(0)[0] if r["n"] == 73)
    check("anchor-hub: the same pull request number merged in two repositories writes a line for each in both logs", got73 == got73m == ["example-owner/other", "example-owner/stackshot"], (got73, got73m))
    # a log that can never be written costs a bounded number of reads, then the anchor is seeded without the line
    add_pr(71, 2 * LH); real_note = ahc._merges.note
    def never(*a, **k): raise OSError("read-only")
    ahc._merges.note = never
    try:
        n0 = calls.count(f"{RP}/issues/71"); h71 = fresh_hub([71])
        for _ in range(8):
            if "github:example-owner/stackshot#71" in h71.gh_state["state"]: break
            pass_of(h71)
        reads71 = calls.count(f"{RP}/issues/71") - n0      # the reads up to the seed (a seeded merged anchor is looked at once in a while after that, as any)
    finally: ahc._merges.note = real_note
    check("anchor-hub: a log that cannot be written costs at most ghr.LATE_TRIES reads of the issue, then the anchor is seeded (the late line dropped, said in a warning)",
          reads71 == ghr.LATE_TRIES and "github:example-owner/stackshot#71" in h71.gh_state["state"] and lines13(71) == ([], []) and any("dropped" in w and "late merge" in w for w in warned), (reads71, warned[-2:]))
finally:
    ghr.subprocess, ghr.threading, ghr.time = _sub, _thr, _tim
    ahc.log.removeHandler(_caph)
    set_reads(100000)

check("over the whole run no label, issue-field, blocked-by, comment or comment-edit call reached GitHub", F.forbidden == [], F.forbidden[:5])
print(("ok" if not fails else "FAILED") + f": github scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
