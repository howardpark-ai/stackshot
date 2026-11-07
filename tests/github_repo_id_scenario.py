"""Scenario test for [github] issues_repo_id (ghsync.py): the issues repo addressed by its numeric id. Fixture data, a fake GitHub
API on localhost, no live store, no network.

GitHub follows a 301 on a read but not on a write, so a write addressed by name (/repos/<owner>/<name>/...) stops when the repo
changes owner; /repositories/<id>/... does not, since the id survives a transfer. Covers: the key's accessor (a positive integer or
digit string; empty, missing, zero, negative, a word or a bool = not set). With the id set, every call the mirror makes for the
issues repo goes to /repositories/<id>/...: the id allocator's create, the queue worker's edit and close, the issue and list reads,
the comment reader, and a merged-PR check on the issues repo; a write lands while the name's path answers a redirect. With it unset,
every one of those calls goes to /repos/<owner>/<name>/... exactly as before, and a redirected write's log line names issues_repo_id
as the fix. Either way the item page's issue link and the map's repo note use issues_repo (the name).

    tests/run-suite github_repo_id        → exit 0 / 1"""
import json, os, pathlib, re, subprocess, sys, threading, time, io, contextlib, logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="ghid-"); T = pathlib.Path(tmp)

NAME = "example-org/example-board"; RID = 4242
BY_NAME = f"/repos/{NAME}"; BY_ID = f"/repositories/{RID}"


# ---- a fake GitHub: one repo, served under its name and its id alike; `moved` makes the name's path answer a redirect to the id's
class Fake:
    def __init__(self):
        self.issues = {}; self.next = 1; self.comments = []; self.moved = False
        self.log = []                                   # (method, path)
        self.lock = threading.Lock()

F = Fake()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj=None, headers=None):
        body = json.dumps(obj).encode() if obj is not None else b""
        self.send_response(code); self.send_header("Content-Type", "application/json")
        for k, v in {"x-ratelimit-limit": "5000", "x-ratelimit-remaining": "4000", "x-ratelimit-resource": "core", **(headers or {})}.items(): self.send_header(k, v)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}
    def _out(self, i): return {**i, "html_url": f"https://github.example/{NAME}/issues/{i['number']}"}
    def _handle(self, method):
        u = urlparse(self.path); full = u.path
        with F.lock:
            F.log.append((method, full))
            if self.headers.get("Authorization") != "Bearer test-token": return self._send(401, {"message": "bad credentials"})
            if full == "/user": return self._send(200, {"login": "example-owner", "id": 1})
            if full == "/rate_limit": return self._send(200, {"resources": {"core": {"limit": 5000, "remaining": 4000, "reset": int(time.time()) + 60}}})
            if full.startswith(BY_NAME + "/"):
                if F.moved:                             # the repo changed owner: the old name's path answers a redirect (a GET 301, a write 307)
                    loc = API + BY_ID + full[len(BY_NAME):]
                    return self._send(301 if method == "GET" else 307, {"message": "Moved Permanently", "url": loc}, {"Location": loc})
                rest = full[len(BY_NAME):]
            elif full.startswith(BY_ID + "/"):
                rest = full[len(BY_ID):]
            else:
                return self._send(404, {"message": f"no route {method} {full}"})
            if rest == "/issues/comments" and method == "GET": return self._send(200, F.comments)
            if rest == "/issues" and method == "POST":
                b = self._body(); n = F.next; F.next += 1
                F.issues[n] = {"number": n, "title": b["title"], "body": b.get("body", ""), "state": "open", "state_reason": None}
                return self._send(201, self._out(F.issues[n]))
            if rest == "/issues" and method == "GET": return self._send(200, [self._out(i) for i in F.issues.values()])
            m = re.fullmatch(r"/issues/(\d+)", rest)
            if m and int(m.group(1)) in F.issues:
                i = F.issues[int(m.group(1))]
                if method == "PATCH":
                    b = self._body()
                    for k in ("title", "body", "state", "state_reason"):
                        if k in b: i[k] = b[k]
                return self._send(200, self._out(i))
            m = re.fullmatch(r"/pulls/(\d+)", rest)
            if m and method == "GET": return self._send(200, {"number": int(m.group(1)), "state": "open", "merged": False})
            return self._send(404, {"message": f"no route {method} {full}"})
    def do_GET(self): self._handle("GET")
    def do_POST(self): self._handle("POST")
    def do_PATCH(self): self._handle("PATCH")


srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
API = f"http://127.0.0.1:{srv.server_address[1]}"
(T / "github.token").write_text("test-token\n")


# ---- the instance: the example config with the paths in the temp dir, the mirror on, issue numbers as ids
def write_toml(rid: str):
    toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    for pat, val in ((r'^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'),
                     (r'^board_url = "[^"]*"', 'board_url = "https://board.example.org"'),
                     (r'^sync = false', 'sync = true'),
                     (r'^issue_ids = false', 'issue_ids = true'),
                     (r'^issues_repo = ""', f'issues_repo = "{NAME}"'),
                     (r'^issues_repo_id = ""', f'issues_repo_id = {rid}'),
                     (r'^api_url = "[^"]*"', f'api_url = "{API}"'),
                     (r'^token_file = ""', f'token_file = "{tmp}/github.token"'),
                     (r'^min_interval_seconds = [0-9.]+', 'min_interval_seconds = 0'),
                     (r'^merge_seconds = [0-9.]+', 'merge_seconds = 0'),
                     (r'^hourly_budget = [0-9]+', 'hourly_budget = 100000'),
                     (r'^read_budget = [0-9]+', 'read_budget = 100000'),
                     (r'^guards = true', 'guards = false'),
                     (r'^require_marks = true', 'require_marks = false')):
        toml, n = re.subn("(?m)" + pat, val, toml); assert n == 1, pat
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")

write_toml(str(RID))
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects"): (T / d).mkdir(parents=True)
OWNER = "00000000-0000-4000-8000-000000000001"; now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-here", "status": "active", "board": [], "board_open": 0}}}))
(T / "store/next-id").write_text("1"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
STORE = T / "store"
DESC = "- A thing\n- It lives here\n- Finished when it works"

import server, ghsync as G
from ui import render as ui_render
server._publish = lambda: None
server._wt.cap_needs_owner = lambda: False
server._refuse_if_owing = lambda debtor: None
server._tell_woken = lambda *a, **k: None
GHC = server._cfg.CFG["github"]


def repo_calls():
    """The logged calls that name the repo (the token's /user and /rate_limit name none)."""
    return [(m, p) for m, p in F.log if p not in ("/user", "/rate_limit")]


def round_trip(label):
    """Every kind of call the mirror makes for the issues repo, through the server's own paths and the process's client:
    a create (the id allocator), an edit and a close (the queue worker), the issue and list reads, the comment reader, a merged-PR check.
    → (the item's id, its issue number)."""
    out = server._create(subject=f"[home] {label}", description=DESC, project="projects/alpha", owner="home-here", next="x")
    gid = G.norm(re.search(r"created (\S+)", out).group(1)); n = G.issue_of(gid, STORE)
    server._update(gid, description=f"- {label}, edited\n- It lives here\n- Finished when it works", sender="home-here")
    r1 = G.drain(None, STORE, say=lambda s: None); edited = "edited" in F.issues.get(n, {}).get("body", "")
    server.stackshot_complete(gid, outcome="done", reason="it worked", description="- Done", sender="home-here")
    r2 = G.drain(None, STORE, say=lambda s: None)
    G.client().get_issue(n); G.client().list_issues()
    rp = G.poll_comments(None, STORE, say=lambda s: None)
    merged, err = server._pr_merged(f"{NAME}#{n}", time.time(), {})
    check(f"{label}: the create took issue #{n}, the edit and the close landed, the reads answered", n > 0 and r1["done"] >= 1 and r1["left"] == 0 and edited and r2["done"] == 1 and not rp.get("down")
          and F.issues[n]["state"] == "closed" and not merged and not err, (out[:200], n, r1, r2, rp, err))
    return gid, n


def kinds(calls):
    """What each call was, the issue number taken out: ("POST", "/issues"), ("PATCH", "/issues/N"), …"""
    return sorted({(m, re.sub(r"/\d+$", "/N", re.sub(r"^/(?:repos/[^/]+/[^/]+|repositories/\d+)", "", p))) for m, p in calls})


EXPECTED = sorted({("POST", "/issues"), ("PATCH", "/issues/N"), ("GET", "/issues/N"), ("GET", "/issues"), ("GET", "/issues/comments"), ("GET", "/pulls/N")})

# ---- 1. the accessor
for v, want in ((RID, RID), (str(RID), RID), (f" {RID} ", RID), ("", 0), (None, 0), (0, 0), (-3, 0), ("-3", 0), ("abc", 0), (True, 0), ("4.5", 0)):
    GHC["issues_repo_id"] = v
    check(f"issues_repo_id = {v!r} reads as {want}", G.repo_id() == want, G.repo_id())
GHC.pop("issues_repo_id")
check("issues_repo_id missing reads as not set", G.repo_id() == 0)
GHC["issues_repo_id"] = RID
check("the client's path helper: the id's path when set, the name's otherwise",
      G.GitHub(NAME, API, "t", repo_id_=RID).repo_path("/issues") == f"{BY_ID}/issues" and G.GitHub(NAME, API, "t").repo_path("/issues") == f"{BY_NAME}/issues"
      and G.GitHub(NAME, API, "t", repo_id_=0).repo_path() == BY_NAME, None)

# ---- 2. the id set: every call for the issues repo goes to /repositories/<id>/...
server._cfg.reload()
check("the config sets the id and the name", G.repo_id() == RID and G.repo() == NAME and G.enabled() and G.issue_ids(), (G.repo_id(), G.repo()))
F.log.clear()
gid_a, n_a = round_trip("made with the id set")
calls = repo_calls()
check("with the id set every call for the issues repo, a read or a write, goes to /repositories/<id>/...",
      calls and all(p.startswith(BY_ID + "/") for _m, p in calls) and not any(p.startswith("/repos/") for _m, p in F.log), calls)
check("…and those calls are the create, the edit and close, the issue and list reads, the comment reader and the PR check", kinds(calls) == EXPECTED, kinds(calls))
link = ui_render.issue_url(gid_a, STORE)
check("the item page's issue link still uses the name", link == f"https://github.com/{NAME}/issues/{n_a}" and f'href="{link}"' in ui_render.Board(str(STORE)).item_html(gid_a), link)
G.note_repo(STORE, say=lambda s: None)
check("the map's repo note is the name", G.load_map(STORE).get("repo") == NAME, G.load_map(STORE).get("repo"))
# the repo changes owner: the name's path answers a redirect, the writes by id go on
F.moved = True; F.log.clear()
gid_m, n_m = round_trip("made after the move")
check("after a move the writes land by id: no call met the redirect", all(p.startswith(BY_ID + "/") for _m, p in repo_calls()) and F.issues[n_m]["state"] == "closed", repo_calls())
F.moved = False

# ---- 3. the id unset: every call goes to /repos/<owner>/<name>/..., as before
write_toml('""'); server._cfg.reload()
check("the config's empty id is not set", G.repo_id() == 0 and G.repo() == NAME, G.repo_id())
F.log.clear()
gid_b, n_b = round_trip("made with the id unset")
calls = repo_calls()
check("with the id unset every call for the issues repo goes to /repos/<owner>/<name>/..., as before",
      calls and all(p.startswith(BY_NAME + "/") for _m, p in calls) and not any(p.startswith("/repositories/") for _m, p in F.log), calls)
check("…the same calls as with the id set", kinds(calls) == EXPECTED, kinds(calls))
link = ui_render.issue_url(gid_b, STORE)
check("the item page's issue link uses the name", link == f"https://github.com/{NAME}/issues/{n_b}" and f'href="{link}"' in ui_render.Board(str(STORE)).item_html(gid_b), link)
# the repo changes owner with no id set: a write waits, and the log line names issues_repo_id as the fix
F.moved = True
server._update(gid_b, description="- edited while the repo moves", sender="home-here")
err = io.StringIO()
with contextlib.redirect_stderr(err):
    r = G.drain(None, STORE, say=lambda s: None)
check("with no id set a write after a move waits, and its log line names issues_repo and issues_repo_id",
      r["done"] == 0 and r["left"] == 1 and "307" in r["down"] and f"does [github] issues_repo = {NAME}" in err.getvalue() and "[github] issues_repo_id" in err.getvalue(), (r, err.getvalue()))
F.moved = False
r = G.drain(None, STORE, say=lambda s: None)
check("the redirect gone, the waiting write lands", r["done"] == 1 and "edited while the repo moves" in F.issues[n_b]["body"], r)

print(("ok" if not fails else "FAILED") + f": github repo id scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
