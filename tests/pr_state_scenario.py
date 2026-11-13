"""Scenario test for pr_state.py, the one reader of a pull request's merged state behind server._pr_merged — fixture data, a fake GitHub on a local
port (with ETags and 304s), no live store, no network.

Covers: the reader on its own (pr_state.merged with a real ghsync client): merged, open, closed without a merge (the record carries `dead`), a refusal
(404: an error tried again at the normal pace), GitHub down (the backoff doubles from the pace and stops at the cap, or follows what GitHub asked) and a
spent budget; the pace (a second call inside it makes no request, a call after it asks again and a 304 keeps the answer); the shared store (a second
caller's own dict is filled from the first caller's read, the freshest of the caller's persisted record and the shared one wins, which is what a restart
leans on, and two threads asking for one PR at once make one request); the ledger (each read is kept under the caller tag in force: done_check, step_proof,
event_wait; a 304 is not counted). Then the server's three callers on one pull request, through their own paths (the done check pass, the event wait's early
read, the step proof's sweep): one request in a window instead of three, the next window one more, and the same return values and records as before.

    tests/run-suite pr_state        → exit 0 / 1"""
import json, os, re, sys, pathlib, threading, time, logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="prstatetest-"); T = pathlib.Path(tmp)


# ---- a fake GitHub: the pull-request read, one repo "o/r", ETags (a 304 for an unchanged PR), a delay, an outage
class Fake:
    def __init__(self):
        self.prs = {}                 # n -> "open" | "merged" | "closed" (closed without a merge)
        self.version = {}             # n -> the ETag's counter: moves when the PR's state does
        self.down = False
        self.delay = 0.0
        self.log = []                 # (path, status answered)
        self.lock = threading.Lock()
    def put(self, n, state):
        with self.lock:
            self.prs[n] = state; self.version[n] = self.version.get(n, 0) + 1
    def requests(self, n):
        return [s for p, s in self.log if p == f"/repos/o/r/pulls/{n}"]


F = Fake()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj=None, headers=None):
        body = json.dumps(obj).encode() if obj is not None else b""
        self.send_response(code); self.send_header("Content-Type", "application/json")
        for k, v in {"x-ratelimit-limit": "5000", "x-ratelimit-remaining": "4000", "x-ratelimit-resource": "core", **(headers or {})}.items(): self.send_header(k, v)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        path = urlparse(self.path).path
        if F.delay: time.sleep(F.delay)
        with F.lock:
            if self.headers.get("Authorization") != "Bearer test-token":
                F.log.append((path, 401)); return self._send(401, {"message": "bad credentials"})
            m = re.fullmatch(r"/repos/o/r/pulls/(\d+)", path)
            if F.down:
                F.log.append((path, 503)); return self._send(503, {"message": "down"})
            if not m or int(m.group(1)) not in F.prs:
                F.log.append((path, 404)); return self._send(404, {"message": "Not Found"})
            n = int(m.group(1)); st = F.prs[n]; tag = f'"v{n}-{F.version[n]}"'
            if self.headers.get("If-None-Match") == tag:
                F.log.append((path, 304)); return self._send(304, None, {"ETag": tag})
            F.log.append((path, 200))
            return self._send(200, {"number": n, "state": "open" if st == "open" else "closed", "merged": st == "merged",
                                    "merged_at": "2026-11-03T00:00:00Z" if st == "merged" else None}, {"ETag": tag})


srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
API = f"http://127.0.0.1:{srv.server_address[1]}"
(T / "github.token").write_text("test-token\n")

toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^api_url = "[^"]*"', f'api_url = "{API}"', toml); assert n == 1
toml, n = re.subn(r'(?m)^token_file = ""', f'token_file = "{tmp}/github.token"', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "state/releases", "brain/projects"): (T / d).mkdir(parents=True)
BUILDER = "00000000-0000-4000-8000-000000000001"
now0 = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({BUILDER: {"name": "home-builder", "machine": "a", "seen": now0}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-builder", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-builder": "the front"}, "back_agents": {}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\nagents:\n  home-builder: the front\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("40"); (T / "store/anchors.json").write_text("{}")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.github import ghsync as G; from stackshot.core import ghbudget as GB; from stackshot.github import pr_state as PS
EVERY = 300.0
def client(**kw): return G.GitHub("o/r", API, "test-token", pace=0.0, shared=True, **kw)
CL = client()
def read(n, now, st, cl=None, every=EVERY, cap=3600.0, tag=None):
    f = lambda repo: cl or CL
    if tag:
        with GB.tag(tag): return PS.merged(f"o/r#{n}", now, st, f, every, cap)
    return PS.merged(f"o/r#{n}", now, st, f, every, cap)

# ---- 1. the reader on its own: the states
F.put(1, "merged"); F.put(2, "open"); F.put(3, "closed")
st = {}
check("merged: (True, no error), the record kept with `seen` and no `dead`", read(1, 1000.0, st) == (True, "") and st["o/r#1"]["merged"] is True and st["o/r#1"]["seen"] == 1000.0 and "dead" not in st["o/r#1"]
      and st["o/r#1"]["next"] == 1000.0 + EVERY and st["o/r#1"]["back"] == 0.0 and st["o/r#1"]["err"] == "", st)
check("open: (False, no error), nothing marks it dead", read(2, 1000.0, st) == (False, "") and st["o/r#2"]["merged"] is False and "dead" not in st["o/r#2"], st)
check("closed without a merge: (False, no error) and the record says it can never pass", read(3, 1000.0, st) == (False, "") and st["o/r#3"].get("dead") == "its pull request was closed without being merged", st)
check("a refusal (the PR is not there): an error naming the read, tried again at the normal pace, no backoff",
      read(4, 1000.0, st)[1].startswith("GitHub refused the read (HTTP 404") and st["o/r#4"]["next"] == 1000.0 + EVERY and st["o/r#4"]["back"] == 0.0 and st["o/r#4"]["merged"] is False, st["o/r#4"])
bad = G.GitHub("o/r", API, "wrong-token", pace=0.0, shared=True)
check("a token GitHub does not accept reads as a refusal too (unreadable), not a merge", read(1, 5000.0, {}, cl=bad)[0] is False and "refused the read" in read(1, 5000.0, {}, cl=bad)[1], None)

# ---- 2. the pace, the 304 and the backoff
F.log.clear(); st = {}; CL = client()      # a client of its own: the ETag cache is the client's, so the first read here is a 200
read(2, 2000.0, st)
a = len(F.requests(2))
r1 = read(2, 2000.0 + EVERY - 1, st)
check("inside the pace a second call makes no request and answers from the record", a == 1 and len(F.requests(2)) == 1 and r1 == (False, ""), F.requests(2))
r2 = read(2, 2000.0 + EVERY, st)
check("after the pace it asks again with the ETag: GitHub answers 304 and the answer stands", F.requests(2) == [200, 304] and r2 == (False, "") and st["o/r#2"]["next"] == 2000.0 + 2 * EVERY, F.requests(2))
F.put(2, "merged")
check("…and when the PR changed meanwhile the next read sees it", read(2, 2000.0 + 2 * EVERY, st) == (True, "") and F.requests(2)[-1] == 200, F.requests(2))
F.down = True; st = {}
e1 = read(5, 3000.0, st); b1 = st["o/r#5"]["back"]
e2 = read(5, 3000.0 + 1, st); n_inside = len(F.requests(5))
c2 = read(5, 3000.0 + b1, st); b2 = st["o/r#5"]["back"]
check("GitHub down: an error saying it did not answer, backing off by the pace and not asking again inside it",
      e1[0] is False and e1[1].startswith("GitHub did not answer") and b1 == EVERY and st["o/r#5"]["next"] > 3000.0 and e2 == e1 and n_inside == 1 and len(F.requests(5)) == 2, (e1, e2, F.requests(5)))
read(5, st["o/r#5"]["next"], st); b3 = st["o/r#5"]["back"]
check("…doubling while it stays down", b2 == 2 * EVERY and b3 == 4 * EVERY, (b1, b2, b3))
for _ in range(6): read(5, st["o/r#5"]["next"], st)
check("…and stopping at the cap", st["o/r#5"]["back"] == 3600.0, st["o/r#5"])
F.down = False
check("…and the first answer after the outage clears the backoff", read(5, st["o/r#5"]["next"], st)[1].startswith("GitHub refused the read (HTTP 404") and st["o/r#5"]["back"] == 0.0, st["o/r#5"])
class Spent:
    repo_id = 0
    def repo_path(self, rest=""): return "/repos/o/r" + rest
    def request(self, *a, **k): raise G.GitHubBudget(100, 900.0)
st = {}
sp = read(1, 7000.0, st, cl=Spent())
check("a spent hourly budget is an error with GitHub's own words, held for what the ledger asked (more than the pace)",
      sp[0] is False and "hourly cap" in sp[1] and st["o/r#1"]["next"] == 7000.0 + 900.0 and st["o/r#1"]["err"] == sp[1], st)
class ById:
    repo_id = 4242; asked = []
    def repo_path(self, rest=""): return "/repositories/4242" + rest
    def request(self, method, path, **k): ById.asked.append((method, path, k.get("etag"))); return {"merged": True}
check("a client with the repository's id reads by it, and asks for the ETag", read(9, 1.0, {}, cl=ById()) == (True, "") and ById.asked == [("GET", "/repositories/4242/pulls/9", True)], ById.asked)

# ---- 3. the shared store: callers read one record
PS.reset(); F.log.clear(); F.put(6, "open")
done_st, proof_st, evw_st = {}, {}, {}
x1 = read(6, 10000.0, done_st); x2 = read(6, 10010.0, proof_st); x3 = read(6, 10020.0, evw_st)
check("three callers with three dicts of their own make one request in a window and get one answer", F.requests(6) == [200] and x1 == x2 == x3 == (False, ""), F.requests(6))
check("…each caller's own dict holds the record (it persists it and reads `dead` from it), the same for all",
      done_st["o/r#6"] == proof_st["o/r#6"] == evw_st["o/r#6"] and PS.known("o/r#6") == done_st["o/r#6"] and done_st["o/r#6"] is not proof_st["o/r#6"], (done_st, proof_st, evw_st))
check("fresh() tells a caller a read costs nothing now (its own record or the shared one), and not once the pace is over",
      PS.fresh("o/r#6", {}, 10100.0) and PS.fresh("o/r#6", done_st, 10100.0) and not PS.fresh("o/r#6", {}, 10000.0 + EVERY) and not PS.fresh("o/r#7", {}, 1.0), None)
F.put(7, "closed")
d_st = {}
read(7, 20000.0, d_st); p_st = {}
check("a closed-unmerged answer reaches every caller as `dead`", read(7, 20001.0, p_st) == (False, "") and p_st["o/r#7"].get("dead") and len(F.requests(7)) == 1, p_st)
PS.reset(); F.log.clear()
persisted = {"o/r#6": {"next": 30000.0 + 200, "back": 0.0, "err": "", "merged": False, "seen": 30000.0}}
check("after a restart (the shared store empty) the caller's persisted record still holds: no request inside its pace", read(6, 30000.0, persisted) == (False, "") and F.requests(6) == [], F.log)
read(6, 30100.0, {}); newer = {"o/r#6": {"next": 40000.0, "back": 0.0, "err": "", "merged": True, "seen": 39700.0}}
check("the fresher record wins, the caller's or the shared one", read(6, 30101.0, newer) == (True, "") and PS.known("o/r#6")["next"] == 30100.0 + EVERY and read(6, 30102.0, {}) == (False, ""), PS.known("o/r#6"))
PS.reset(); F.log.clear(); F.delay = 0.3; CL = client()
out = []; ths = [threading.Thread(target=lambda: out.append(read(6, 50000.0, {}))) for _ in range(5)]
for t in ths: t.start()
for t in ths: t.join()
F.delay = 0.0
check("five threads asking for one PR at once make one request and get the same answer", F.requests(6) == [200], F.requests(6))
check("…every thread got the answer", len(out) == 5 and all(o == (False, "") for o in out), out)
PS.reset()
for i in range(PS._KEEP + 50): PS._store(f"o/r#{100 + i}", {"next": float(i)})
check("the shared store is bounded: the oldest records go first", len(PS._SHARED) == PS._KEEP and "o/r#100" not in PS._SHARED and f"o/r#{100 + PS._KEEP + 49}" in PS._SHARED, len(PS._SHARED))
PS.reset()

# ---- 4. the ledger: the caller tag in force is the tag of the read; a 304 is none
def by(): return GB.by_caller()["reads"]
def delta(a, b, who): return b.get(who, 0) - a.get(who, 0)
F.put(8, "open"); PS.reset(); b0 = dict(by())
read(8, 60000.0, {}, tag="done_check"); b1 = dict(by())
F.put(8, "merged")
read(8, 60000.0 + EVERY, {}, tag="step_proof"); b2 = dict(by())
F.put(8, "closed")
read(8, 60000.0 + 2 * EVERY, {}, tag="event_wait"); b3 = dict(by())
read(8, 60000.0 + 3 * EVERY, {}, tag="event_wait"); b4 = dict(by())
check("each read is counted once under the tag in force (done_check, step_proof, event_wait), none under 'other'",
      delta(b0, b1, "done_check") == 1 and delta(b1, b2, "step_proof") == 1 and delta(b2, b3, "event_wait") == 1 and all(delta(b0, b3, w) == 0 for w in ("other", "ghsync", "release")), (b0, b1, b2, b3))
check("…a 304 (the PR unchanged) is not counted at all", F.requests(8)[-1] == 304 and b4 == b3, (F.requests(8), b3, b4))
check("…and the tag is gone after the call", GB.current() == "", GB.current())

# ---- 5. the server's three callers on one pull request, through their own paths
from stackshot.web import server
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
server._wt.cap_needs_owner = lambda: False
server._refuse_if_owing = lambda debtor: None
server._OWN_REPO[:] = ["example-owner/stackshot"]
server._HERE = T / "repo"
def gid(i): return f"a{i}"
def put_item(i, nxt, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "- A thing. It lives here. Done when done.", "status": "open",
                                                       "updated": now0 - 3600, "state_updated": now0 - 3600, "confirmed": now0 - 3600,
                                                       "metadata": {"owner": BUILDER, "mover": BUILDER, "project": "projects/alpha", "next": nxt, **meta}}))
PRN = 21
F.put(PRN, "open")
put_item(1, "home-builder: keep going", check=f"pr_merged o/r#{PRN}")                                              # the done check
put_item(2, f"home-builder: merge https://github.com/o/r/pull/{PRN}")                                              # the step proof (a URL counts anywhere)
PS.reset(); server._EVW_GH.clear(); server._EVW_POLLED.clear()
for f in (T / "state/checks.json", T / "state/step-proof.json"): f.unlink(missing_ok=True)
server._CHECK_LAST[0] = 0.0
F.log.clear(); b0 = dict(by()); t0 = time.time()
server._evwait_preread("event", f"pr_merged o/r#{PRN}")                                  # the event wait's early read (a request thread)
server._check_tick(t0 + 1)                                                                # the done check's pass
rows = server._sweep_proofs(dry=True, save=True)["items"]                                 # the step proof's pass (a dry one reads GitHub and keeps the answers)
reads_after_window_1 = len(F.requests(PRN))
b1 = dict(by())
check("one window, the three callers on one pull request: one request to GitHub, not three", reads_after_window_1 == 1 and F.requests(PRN) == [200], F.requests(PRN))
check("…counted once in the ledger, under the first reader's tag (event_wait)", delta(b0, b1, "event_wait") == 1 and delta(b0, b1, "done_check") == 0 and delta(b0, b1, "step_proof") == 0, (b0, b1))
chk = json.loads((T / "state/checks.json").read_text()); pf = json.loads((T / "state/step-proof.json").read_text())
check("…each caller still keeps the record in its own file (checks.json, step-proof.json) and in the event waits' memory",
      chk["github"][f"o/r#{PRN}"]["merged"] is False and pf["github"][f"o/r#{PRN}"]["merged"] is False and server._EVW_GH[f"o/r#{PRN}"]["merged"] is False, (chk, pf, server._EVW_GH))
check("…the open pull request ticks nothing and closes nothing", rows == [] and json.loads((T / "store/a/1.json").read_text())["status"] == "open", rows)
F.put(PRN, "merged"); F.log.clear(); b1 = dict(by())
t1 = PS.known(f"o/r#{PRN}")["next"] + 5                          # five seconds past the stored pace, however long the runner stalled since t0
server._CHECK_LAST[0] = 0.0
closed = server._check_tick(t1)
rows2 = server._sweep_proofs(dry=True, save=True)["items"]
check("the next window: one more request (the first caller to ask), the PR's merge seen by the done check, and the proof pass finds it without asking again",
      F.requests(PRN) == [200] and closed == [gid(1)] and any(r.get("item") == gid(2) for r in rows2), (F.requests(PRN), closed, rows2))
b2 = dict(by())
check("…and that read is counted once, under the done check", delta(b1, b2, "done_check") == 1 and delta(b1, b2, "step_proof") == 0 and delta(b1, b2, "event_wait") == 0, (b1, b2))
check("server._pr_merged is the reader's entry: same signature, same (merged, error) pair, the PR by its current name",
      server._pr_merged(f"o/r#{PRN}", t1 + 1, {}) == (True, "") and len(F.requests(PRN)) == 1, F.requests(PRN))
class _Spy:
    repo_id = 0
    def repo_path(self, rest=""): return "/repos/o/r" + rest
    def request(self, *a, **k): raise AssertionError("no read expected")
_cg = server._check_gh; server._check_gh = lambda repo: _Spy()
try:
    server._pr_merged(f"o/r#{PRN}", t1 + 2, {}); spy_ok = True
except AssertionError:
    spy_ok = False
finally:
    server._check_gh = _cg
check("server._pr_merged goes through server._check_gh at call time (a stub in its place is used) and a fresh shared record needs no client", spy_ok, None)

print(("ok" if not fails else "FAILED") + f": pr_state scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
