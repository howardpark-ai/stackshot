"""Scenario test for "keeping the box current" (the PC's helper is its one service, and it keeps its checkout current). Fixture data only: a temp config, a fake origin and a box's checkout as temp git
repositories, a fake `claude` on the PATH that answers `--version` only, a fake registry; no network, and never a real update
of anything.

Covers: the poll's answer carries `current` (the server's puller VERSION, its checkout commit, self_update on for a client
box, off for the server box's own token and with [client] self_update = false); the poll's facts carry the box's commit
(kept on the machine's record) and its attempts in the shape the Machines panel keeps (what, from, to, ok a bool, at an ISO
time, reason) and the server keeps them as sent (the card that draws them is another change's); what is behind (an older commit; a
checkout ahead of the server is left alone); idle (a live session or a claude process defers, logged once); the checkout
update (fetch and fast-forward of the whole checkout, then a restart; a dirty or diverged checkout refused; a commit that
does not compile refused; a fetch that fails reported); the backoff (once, then 1 h, 4 h, daily; a new target at once); the
report (the last 10 attempts); the restart (main's RELOAD after an update on both platforms, whatever the VERSION and the
hold-back between reloads, run in the same process by the entry point; the loop's hand-over); --dry-run; the box's own veto. The Claude CLI is never touched: the PC's own provisioning updates it, not the puller.

    tests/run-suite update        → exit 0 / 1"""
import contextlib, io, json, os, re, runpy, socket, stat, subprocess, sys, pathlib, tempfile, logging, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="updatetest-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("fleet_names", f"{tmp}/names.tsv"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
assert re.search(r"(?m)^self_update = true\b", toml)                     # the example's default: on
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off")
for k in ("STACKSHOT_FLEET_DIR", "STACKSHOT_URL", "BOARD_MCP_AUTH"): os.environ.pop(k, None)
ME = socket.gethostname()
for d in ("store/a", "state/anchor-hub", "state/site", "secrets", "brain/projects", "reg", "bin"): (T / d).mkdir(parents=True)
(T / "names.tsv").write_text(f"# hostname\tfleet\tletter\n{ME}\ttestbox\ta\nWIN-BOX\tbox-far\tb\n")
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-sparrow", "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": ""}}}))
(T / "store/a/1.json").write_text(json.dumps({"id": "1", "subject": "[home] item 1", "description": "A thing. It lives here. Done when done.", "status": "open", "metadata": {"owner": "home-sparrow", "project": "projects/alpha"}}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\nname: Alpha\n---\n\n# Alpha\n")
sys.path.insert(0, STACK); logging.disable(logging.WARNING)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))
rd = lambda p: json.loads(pathlib.Path(p).read_text())

# ---- the fixtures: an origin with commits, the box's clone of it, a fake claude on the PATH
GITENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x", "GIT_CONFIG_NOSYSTEM": "1"}
def git(cwd, *a) -> str:
    r = subprocess.run(["git", "-C", str(cwd), *a], capture_output=True, text=True, env=GITENV)
    assert r.returncode == 0, (a, r.stderr)
    return r.stdout.strip()
ORIGIN, BOX = T / "origin", T / "box"
def commit(msg: str, **files) -> str:
    for name, text in files.items(): (ORIGIN / name).parent.mkdir(parents=True, exist_ok=True); (ORIGIN / name).write_text(text)
    git(ORIGIN, "add", "-A"); git(ORIGIN, "commit", "-q", "-m", msg); return git(ORIGIN, "rev-parse", "HEAD")
git(T, "init", "-q", "-b", "main", str(ORIGIN))
A = commit("first", **{"puller.py": 'VERSION = "6"\n', "client.py": "x = 1\n", "config.py": "y = 1\n", "said.py": "z = 1\n", "README.md": "one\n", "pages.py": "x = 1\n", "client/hooks/client.sh": "echo 1\n"})
git(T, "clone", "-q", str(ORIGIN), str(BOX))
VFILE = T / "claude-version"; VFILE.write_text("2.9.9")
exe = T / "bin/claude"
exe.write_text(f'#!/bin/sh\nV="$(cat {VFILE})"\ncase "$1" in\n  --version) echo "$V (Claude Code)";;\n'
               f'  *) exit 2;;\nesac\n')   # answers --version only: the CLI version the puller reports; the puller never updates the CLI
exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
os.environ["PATH"] = str(T / "bin") + os.pathsep + os.environ.get("PATH", "")
REG = str(T / "reg")

import client, clients as cl, puller, versions as ver
import server
server._publish = lambda: None
puller.CHECKOUT = str(BOX)
REAL_CP = puller._claude_process
puller._claude_process = lambda: ""             # this host may well run claude processes; the fake box is idle unless a check says otherwise
probe = lambda: (puller._VER.update(at=0.0), puller.cli_version([]))[1]
head = lambda: (puller._HEAD.update(at=0.0), puller.head())[1]
def quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf): out = fn(*a, **k)
    return out, buf.getvalue()
check("the fake CLI answers its version and the box is at the first commit", probe() == "2.9.9" and head() == A, (probe(), head(), A))

# ============================================================= 1. the poll's answer: what is current, and the facts the server keeps
tok = open(client.mint("box-far")).read().strip(); mine = open(client.mint(ME)).read().strip()
(T / "secrets/client.token").write_text(tok + "\n")             # this process polls as the client box box-far, not as the server box
SRV = T / "server-checkout"                                     # the server's checkout: a fixture repository, HEAD on main as last fetched (the real one may be on a PR branch)
git(T, "init", "-q", "-b", "main", str(SRV)); (SRV / "f.txt").write_text("one\n"); git(SRV, "add", "-A"); git(SRV, "commit", "-q", "-m", "server one")
MINE = git(SRV, "rev-parse", "HEAD"); git(SRV, "update-ref", "refs/remotes/origin/main", MINE)
cl.CHECKOUT = str(SRV)
check("clients.checkout_commit: the server's checkout commit, cached a minute", cl.checkout_commit() == MINE and cl._COMMIT["v"] == MINE, (cl.checkout_commit(), MINE))
cur = cl.current("box-far")
check("current: the puller's VERSION, the server's commit, self_update on for a client box; nothing about the CLI", cur == {"puller": puller.VERSION, "stackshot": MINE, "self_update": True}, cur)
check("current: never for the server box's own token", cl.current(ME)["self_update"] is False, cl.current(ME))
import config as _cfg
_cfg.CFG["client"]["self_update"] = False
check("current: [client] self_update = false in the server's config switches every box off", cl.current("box-far")["self_update"] is False, cl.current("box-far"))
_cfg.CFG["client"]["self_update"] = True
from starlette.testclient import TestClient
app = server.mcp.http_app()
SHA = "a" * 40
with TestClient(app) as c:
    H = {"Authorization": "Bearer " + tok}
    r = c.post("/client/poll", json={"sessions": [], "facts": {"claude": "2.9.9", "platform": "win32", "puller_version": "6", "stackshot": SHA}, "wait": 0}, headers=H)
    d = r.json() if r.status_code == 200 else {}
    check("http: the poll's answer carries current beside the deliveries", r.status_code == 200 and d.get("deliveries") == [] and d.get("machine") == "box-far"
          and d.get("current") == {"puller": puller.VERSION, "stackshot": MINE, "self_update": True}, r.text[:300])
    m = cl.load()["machines"]["box-far"]
    check("checkin: the box's checkout commit is kept on the machine's record like its CLI version", m.get("stackshot") == SHA and m.get("claude") == "2.9.9", m)
    r = c.post("/client/poll", json={"sessions": [], "facts": {"claude": "2.9.9"}, "wait": 0}, headers=H)
    check("checkin: a poll without it leaves it as it was", cl.load()["machines"]["box-far"].get("stackshot") == SHA)
    r = c.post("/client/poll", json={"sessions": [], "wait": 0}, headers={"Authorization": "Bearer " + mine})
    check("http: the server box's own poll is told not to update itself", r.status_code == 200 and r.json()["current"]["self_update"] is False, r.text[:200])

    # ---- the puller end to end: its poll carries the box's commit and its attempts (the shape the Machines panel keeps), and
    # keeps the answer for keep_current
    import urllib.request, urllib.error
    class _Resp:
        def __init__(s, r): s.status = r.status_code; s._b = r.content
        def read(s): return s._b
        def __enter__(s): return s
        def __exit__(s, *a): return False
    sent = []
    def fake_urlopen(req, timeout=0):
        path = req.full_url.replace(client.server_url(), "")
        if req.get_method() == "POST": sent.append((path, json.loads(req.data)))
        r = c.post(path, content=req.data, headers=dict(req.header_items())) if req.get_method() == "POST" else c.get(path, headers=dict(req.header_items()))
        if r.status_code >= 400: raise urllib.error.HTTPError(req.full_url, r.status_code, "x", {}, io.BytesIO(r.content))
        return _Resp(r)
    client.urllib.request.urlopen = fake_urlopen
    puller._STATE = {"attempts": [{"what": "stackshot checkout", "from": "c" * 12, "to": "b" * 12, "ok": True, "at": "2026-10-15T00:00:00Z", "reason": ""},
                                  {"what": "stackshot checkout", "from": "b" * 12, "to": A[:12], "ok": False, "at": "2026-10-15T00:01:00Z", "reason": "git fetch: no route to host"}], "tried": {}}
    rc, out = quiet(puller.once, REG, None, 0)
    body = sent[-1][1] if sent and sent[-1][0] == "/client/poll" else {}
    f = body.get("facts") or {}
    check("puller: its poll's facts carry the box's checkout commit and its attempts as kept (what, from, to, ok a bool, at an ISO time, reason), beside the older facts",
          rc == 0 and f.get("stackshot") == A and f.get("updates") == puller._STATE["attempts"] and f.get("puller_version") == puller.VERSION and f.get("claude") == "2.9.9"
          and all(isinstance(u["ok"], bool) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", u["at"]) and set(u) == {"what", "from", "to", "ok", "at", "reason"} for u in f["updates"]), (rc, out, f))
    check("puller: the server kept the commit, and the puller what the server says is current", cl.load()["machines"]["box-far"].get("stackshot") == A and puller._LAST["current"] == cur, (cl.load()["machines"]["box-far"].get("stackshot"), puller._LAST["current"]))
    check("…and the attempts as sent, in the shape the Machines panel keeps (clients.clean_updates)", cl.load()["machines"]["box-far"].get("updates") == puller._STATE["attempts"], cl.load()["machines"]["box-far"].get("updates"))
    puller._STATE = None

# ============================================================= 2. what is behind
CUR = lambda sha, on=True: {"puller": "6", "stackshot": sha, "self_update": on}
B = commit("the docs, a page and a hook, not the puller", **{"README.md": "two\n", "pages.py": "x = 2\n", "client/hooks/client.sh": "echo 2\n"})
check("plan: an older checkout is behind", puller.plan(CUR(B), []) == [("stackshot checkout", A, B)], puller.plan(CUR(B), []))
check("plan: a checkout at the server's commit: nothing", puller.plan(CUR(A), []) == [], puller.plan(CUR(A), []))
check("plan: no answer, no plan", puller.plan({"stackshot": ""}, []) == [] and puller.plan({}, []) == [])
check("plan: the CLI is never the puller's to update, whatever the server's answer carries", puller.plan({**CUR(A), "claude": "9.9.9"}, []) == [])

# ============================================================= 3. idle
(T / "reg/1.json").write_text(json.dumps({"pid": os.getpid(), "sessionId": "00000020-0000-4000-8000-000000000000", "name": "home-local", "version": "2.9.9", "messagingSocketPath": "/x", "updatedAt": 5}))
live = puller.sessions(REG)
check("busy: a live session in the registry", puller.busy(live) == "1 live session(s): home-local", puller.busy(live))
puller._claude_process = lambda: "a claude process is running"
check("busy: a claude process the registry does not list", puller.busy([]) == "a claude process is running")
puller._claude_process = lambda: ""
check("idle: no session, no process", puller.busy([]) == "")
rc, out = quiet(puller.keep_current, CUR(B), live)
rc2, out2 = quiet(puller.keep_current, CUR(B), live)
check("keep_current: a busy box defers the update, logged once, nothing touched", rc is None and rc2 is None and out.count("waiting, 1 live session(s): home-local") == 1 and out2 == ""
      and head() == A and puller.attempts() == [], (out, out2))
os.remove(T / "reg/1.json")
rc, out = quiet(puller.keep_current, CUR(B, on=False), [])
check("keep_current: the server's answer says off: nothing, said once", rc is None and "keeping this box current: off" in out and head() == A and puller.attempts() == [], out)
_cfg.CFG["client"]["self_update"] = False; puller._SAID.pop("mode", None)
rc, out = quiet(puller.keep_current, CUR(B), [])
check("keep_current: the box's own config says off: its veto", rc is None and "keeping this box current: off" in out and head() == A, out)
_cfg.CFG["client"]["self_update"] = True

# ============================================================= 4. the update, idle: the whole checkout
rc, out = quiet(puller.keep_current, CUR(B), [])
at = puller.attempts()
check("idle and behind: the whole checkout fast-forwarded, then a reload (a docs-only change too: the code the puller runs is the checkout's); the CLI untouched",
      rc == puller.RELOAD and probe() == "2.9.9" and head() == B and [(a["what"], a["from"], a["to"], a["ok"], a["reason"]) for a in at] == [("stackshot checkout", A[:12], B[:12], True, "")]
      and all(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", a["at"]) for a in at) and f"update stackshot checkout {A[:12]} → {B[:12]}: ok" in out, (rc, out, at, probe(), head()))
check("…the whole checkout moved with it: the docs, pages.py, the hooks", (BOX / "README.md").read_text() == "two\n" and (BOX / "pages.py").read_text() == "x = 2\n" and (BOX / "client/hooks/client.sh").read_text() == "echo 2\n", sorted(p.name for p in BOX.iterdir()))
st = rd(T / "state/puller-updates.json")
check("the attempts and the tries are kept on the box (the attempt names the commits short, the try the target in full)",
      st["attempts"] == at and st["tried"] == {"stackshot checkout": {"to": B, "at": st["tried"]["stackshot checkout"]["at"], "n": 1}}, st)
C = commit("the puller itself", **{"puller.py": 'VERSION = "7"\n'})
rc, out = quiet(puller.keep_current, CUR(C), [])
check("a change to puller.py: fast-forwarded, and the puller asks for a reload", rc == puller.RELOAD and head() == C and puller.attempts()[-1]["ok"] is True, (rc, out, head()))
rc, out = quiet(puller.keep_current, CUR(C), [])
check("at the server's commit: nothing more", rc is None and out == "" and len(puller.attempts()) == 2, (rc, out))

# ---- refusals
D = commit("more docs", **{"README.md": "three\n"})
(BOX / "README.md").write_text("edited on the box\n")
rc, out = quiet(puller.keep_current, CUR(D), [])
check("a checkout with local changes is refused, reported", rc is None and head() == C and puller.attempts()[-1]["ok"] is False and puller.attempts()[-1]["reason"] == "local changes in the checkout", (out, puller.attempts()[-1]))
git(BOX, "checkout", "--", "README.md")
rc, out = quiet(puller.keep_current, CUR(D), [])
check("…and tried again only after the backoff (1 h)", rc is None and head() == C and len(puller.attempts()) == 3 and out == "", (out, len(puller.attempts())))
puller._STATE["tried"]["stackshot checkout"]["at"] -= 3601
rc, out = quiet(puller.keep_current, CUR(D), [])
check("after the backoff: fast-forwarded", rc == puller.RELOAD and head() == D and puller.attempts()[-1]["ok"] is True, (out, head()))
(BOX / "local.txt").write_text("mine\n"); git(BOX, "add", "local.txt"); git(BOX, "commit", "-q", "-m", "a local commit"); L = git(BOX, "rev-parse", "HEAD")
E = commit("after the local one", **{"README.md": "four\n"})
(BOX / "README.md").write_text("edited on the box\n")
rc, out = quiet(puller.keep_current, CUR(E), [])
check("a diverged checkout with a local edit is refused, reported; no rollback branch is made for a move that did not happen", rc is None and head() == L and puller.attempts()[-1]["reason"] == "local changes in the checkout"
      and git(BOX, "branch", "--list", "legacy-*") == "", (out, puller.attempts()[-1]))
git(BOX, "reset", "-q", "--hard", D); puller._STATE["tried"].pop("stackshot checkout", None); head()   # (the checkout moved by hand: the 5-min cache of HEAD is refreshed here)
rc, out = quiet(puller.keep_current, CUR(D), [])
check("a checkout put back at the server's commit by hand: nothing to update; the diverged failure is answered by one ok attempt, so the panel stops drawing it", rc is None and head() == D
      and puller.attempts()[-1]["ok"] is True and puller.attempts()[-1]["reason"] == "already at the server's commit" and puller.attempts()[-2]["reason"] == "local changes in the checkout", (rc, out, puller.attempts()[-2:]))
rc, out = quiet(puller.keep_current, CUR(D), [])
check("…and a second poll there records nothing", rc is None and out == "" and puller.attempts()[-1]["reason"] == "already at the server's commit" and puller.attempts()[-2]["reason"] == "local changes in the checkout", (out, puller.attempts()[-2:]))
rc, out = quiet(puller.keep_current, CUR(E), [])
check("back on the server's line: fast-forwarded", rc == puller.RELOAD and head() == E and puller.attempts()[-1]["ok"] is True, (out, head()))
F = commit("broken", **{"puller.py": 'def (:\n'})
rc, out = quiet(puller.keep_current, CUR(F), [])
check("a commit whose puller.py does not compile: refused before the tree is touched (HEAD stays), the failure reported, no reload",
      rc is None and head() == E and puller.attempts()[-1]["ok"] is False and puller.attempts()[-1]["reason"] == "puller.py does not compile at " + F[:12]
      and git(BOX, "status", "--porcelain", "--untracked-files=no") == "", (out, puller.attempts()[-1], head()))
G = commit("fixed", **{"puller.py": 'VERSION = "8"\n'})
rc, out = quiet(puller.keep_current, CUR(G), [])
check("the fix: fast-forwarded and a reload", rc == puller.RELOAD and head() == G and puller.attempts()[-1]["ok"] is True, (out, head()))
Hc = commit("fetch will fail", **{"README.md": "five\n"})
git(BOX, "remote", "set-url", "origin", str(T / "nowhere"))
rc, out = quiet(puller.keep_current, CUR(Hc), [])
check("a fetch that fails is reported with git's reason, the checkout untouched", rc is None and head() == G and puller.attempts()[-1]["reason"].startswith("git fetch: "), (out, puller.attempts()[-1]))
git(BOX, "remote", "set-url", "origin", str(ORIGIN))
rc, out = quiet(puller.keep_current, CUR(Hc), [])
check("…backed off", out == "" and head() == G)
puller._STATE["tried"]["stackshot checkout"]["at"] -= 3601
rc, out = quiet(puller.keep_current, CUR(Hc), [])
check("…then fast-forwarded", rc == puller.RELOAD and head() == Hc and puller.attempts()[-1]["ok"] is True, (out, head()))
rc, out = quiet(puller.keep_current, CUR(G), [])
rc2, out2 = quiet(puller.keep_current, CUR(G), [])
check("a server behind the box (its commit an ancestor): nothing to do, said once, no attempt", rc is None and rc2 is None and "nothing to do, this checkout is ahead" in out and out2 == ""
      and head() == Hc and puller.attempts()[-1]["to"] == Hc[:12] and G in puller._AHEAD, (out, out2))
check("a commit origin does not have is reported", puller._update_checkout("f" * 40)[:2] == (False, "the server's commit ffffffffffff is not on origin"), puller._update_checkout("f" * 40))

check("ten attempts so far, oldest first", len(puller.attempts()) == 10 and puller.attempts()[0]["to"] == C[:12] and puller.attempts()[0]["at"] <= puller.attempts()[-1]["at"], [a["to"] for a in puller.attempts()])
J = commit("the eleventh", **{"README.md": "seven\n"})
rc, out = quiet(puller.keep_current, CUR(J), [])
check("a new target commit is tried at once, and the report holds the last 10 attempts: the oldest dropped", rc == puller.RELOAD and head() == J and len(puller.attempts()) == 10
      and len(puller._STATE["attempts"]) == 10 and puller.attempts()[-1]["to"] == J[:12] and puller.attempts()[0]["to"] == D[:12], [a["to"] for a in puller.attempts()])
Hc = J   # the checkout's commit from here on

# ---- the backoff schedule
puller._STATE["tried"]["stackshot checkout"] = {"to": "t" * 12, "at": time.time(), "n": 1}
check("backoff: a target tried once waits an hour", puller._due("stackshot checkout", "t" * 12) is False and puller._due("stackshot checkout", "u" * 12) is True)
puller._STATE["tried"]["stackshot checkout"]["at"] -= 3601; check("…then is due", puller._due("stackshot checkout", "t" * 12) is True)
puller._STATE["tried"]["stackshot checkout"].update(n=2, at=time.time() - 3601); check("backoff: twice → 4 h", puller._due("stackshot checkout", "t" * 12) is False)
puller._STATE["tried"]["stackshot checkout"]["at"] -= 14400; check("…then due", puller._due("stackshot checkout", "t" * 12) is True)
puller._STATE["tried"]["stackshot checkout"].update(n=7, at=time.time() - 14401); check("backoff: from the third try, daily", puller._due("stackshot checkout", "t" * 12) is False)
puller._STATE["tried"]["stackshot checkout"]["at"] -= 86400; check("…then due", puller._due("stackshot checkout", "t" * 12) is True)
puller._STATE["tried"].pop("stackshot checkout")

# ============================================================= 5. the restart: main's own RELOAD, on both platforms
# (no exec, no second mechanism: the entry point runs the new puller.py in this same process, so a user unit or a scheduled task
# and its repetition trigger see nothing)
check("there is no second restart path: the update asks for the reload main already has", not hasattr(puller, "_restart") and not hasattr(puller, "_rerun") and not hasattr(puller, "RESTART"))
_once, _keep, _win = puller.once, puller.keep_current, puller.WINDOWS
puller.once = lambda reg, only, wait, dry=False: 0
puller.keep_current = lambda current, recs, dry=False, recheck=None: puller.RELOAD
try:
    for win in (False, True):
        puller.WINDOWS = win
        rc, out = quiet(puller.main, ["puller.py", "--registry", REG, "--wait", "0"])
        check(f"main ({'Windows' if win else 'Linux'}): after a poll, an update that moved the checkout ends the loop with RELOAD, to be run in this process",
              rc == puller.RELOAD and "polling" in out and "the checkout was updated, reloading" in out, (rc, out))
    # not held back by RELOAD_MIN_GAP, and no VERSION change needed (the update's own backoff is what bounds it)
    os.environ[puller._RELOAD_AT_ENV] = str(time.time())
    rc, out = quiet(puller.main, ["puller.py", "--registry", REG, "--wait", "0"])
    check("…also right after another reload, and with the VERSION unchanged", rc == puller.RELOAD and puller.disk_version() == puller.VERSION, (rc, out))
    os.environ.pop(puller._RELOAD_AT_ENV, None)
finally:
    puller.once, puller.keep_current, puller.WINDOWS = _once, _keep, _win
_fresh = puller._fresh; ran_fresh = []
puller._fresh = lambda here=None: (ran_fresh.append(1), {"main": lambda argv: 7})[1]
try:
    rc, out = quiet(puller._entry, ["puller.py"], lambda argv: puller.RELOAD)
    check("the entry point: main's RELOAD runs the checkout's puller.py afresh in this process, and its exit code is the process's", rc == 7 and ran_fresh == [1], (rc, out))
finally:
    puller._fresh = _fresh; os.environ.pop(puller._RELOAD_AT_ENV, None)

# ============================================================= 5b. the review's findings
Hc = head()
clean = lambda: git(BOX, "status", "--porcelain", "--untracked-files=no") == ""

# ---- the target is compiled from git before anything is touched: every file the puller runs from, and what those import
K1 = commit("client.py broken", **{"client.py": "def (:\n"})
rc, out = quiet(puller.keep_current, CUR(K1), [])
check("a broken client.py in the target: refused, HEAD untouched, nothing of it on disk", rc is None and head() == Hc and clean() and (BOX / "client.py").read_text() == "x = 1\n"
      and puller.attempts()[-1]["reason"] == "client.py does not compile at " + K1[:12] and puller.attempts()[-1]["ok"] is False, (out, puller.attempts()[-1]))
K2 = commit("client fixed, and puller.py imports a new module that is broken", **{"client.py": "x = 2\n", "puller.py": 'VERSION = "8"\nimport helper_mod\n', "helper_mod.py": "def (:\n"})
rc, out = quiet(puller.keep_current, CUR(K2), [])
check("a module the puller imports (not one of the four files) that does not compile: refused too", rc is None and head() == Hc and clean() and not (BOX / "helper_mod.py").exists()
      and puller.attempts()[-1]["reason"] == "helper_mod.py does not compile at " + K2[:12], (out, puller.attempts()[-1]))
git(ORIGIN, "rm", "-q", "said.py"); K3 = commit("helper fixed, said.py gone", **{"helper_mod.py": "z = 1\n"})
rc, out = quiet(puller.keep_current, CUR(K3), [])
check("a file the puller runs from that is missing in the target: refused", rc is None and head() == Hc and clean() and puller.attempts()[-1]["reason"] == "said.py is missing at " + K3[:12], (out, puller.attempts()[-1]))
K4 = commit("said.py back", **{"said.py": "z = 1\n"})
rc, out = quiet(puller.keep_current, CUR(K4), [])
check("…and a good target after the broken ones (a new target is tried at once) lands, with its new import", rc == puller.RELOAD and head() == K4 and clean() and (BOX / "helper_mod.py").read_text() == "z = 1\n", (rc, out, head()))
Hc = K4
# the check after the merge, on the tree as it is: a failure there rolls the merge back
_tc = puller._target_compiles; puller._target_compiles = lambda to: ""
K5 = commit("slips past the pre-check", **{"config.py": "def (:\n"})
rc, out = quiet(puller.keep_current, CUR(K5), [])
puller._target_compiles = _tc
check("a tree that does not compile after the merge (the pre-check let it by) is put back at the old HEAD, the failure reported", rc is None and head() == Hc and clean() and (BOX / "config.py").read_text() == "y = 1\n"
      and puller.attempts()[-1]["reason"] == "config.py does not compile at " + K5[:12], (out, head(), puller.attempts()[-1]))
K6 = commit("config fixed", **{"config.py": "y = 2\n"}); rc, out = quiet(puller.keep_current, CUR(K6), [])
check("…and the next target lands", rc == puller.RELOAD and head() == K6 and clean(), (rc, out)); Hc = K6

# ---- a merge that fails midway leaves the checkout at the old HEAD, clean, with git's own error line as the reason
K7 = commit("adds a file", **{"newfile.txt": "from origin\n"})
(BOX / "newfile.txt").write_text("untracked on the box\n")
rc, out = quiet(puller.keep_current, CUR(K7), [])
check("an untracked file in the way: the merge fails, the checkout is as it was, git's error line is the reason", rc is None and head() == Hc and clean() and (BOX / "newfile.txt").read_text() == "untracked on the box\n"
      and puller.attempts()[-1]["ok"] is False and puller.attempts()[-1]["reason"].startswith("git merge --ff-only: error: ") and "untracked" in puller.attempts()[-1]["reason"], (out, puller.attempts()[-1]))
(BOX / "newfile.txt").unlink()
_g = puller._git
def half_merge(args, timeout=60, **kw):
    if args and args[0] == "merge":            # the merge moves HEAD and the files, then fails (a locked file, a virus scanner)
        _g(args, timeout, **kw); (BOX / "README.md").write_text("half done\n"); (BOX / "pages.py").write_text("half done\n")
        return 1, "", "error: unable to unlink old 'pages.py': Permission denied"
    return _g(args, timeout, **kw)
puller._git = half_merge
puller._STATE["tried"].pop("stackshot checkout", None)
rc, out = quiet(puller.keep_current, CUR(K7), [])
puller._git = _g
check("a merge that fails after it moved HEAD and wrote files: back at the old HEAD on its branch (reset --keep), the reason recorded, the file that was being written is still the box's own edit, never reset away",
      rc is None and head() == Hc and (BOX / "README.md").read_text() == "half done\n" and not (BOX / "newfile.txt").exists()
      and puller.attempts()[-1]["reason"] == "git merge --ff-only: error: unable to unlink old 'pages.py': Permission denied" and git(BOX, "rev-parse", "--abbrev-ref", "HEAD") == "main", (out, head(), puller.attempts()[-1]))
git(BOX, "checkout", "--", "README.md", "pages.py")      # (whoever edited them puts them back)
puller._STATE["tried"].pop("stackshot checkout", None)
rc, out = quiet(puller.keep_current, CUR(K7), [])
check("…and the next attempt lands", rc == puller.RELOAD and head() == K7 and clean(), (rc, out)); Hc = K7

# ---- busy again right before the merge: nothing done, nothing recorded as a failure
K8 = commit("another docs change", **{"README.md": "eight\n"})
n_before = len(puller.attempts())
(T / "reg/1.json").write_text(json.dumps({"pid": os.getpid(), "sessionId": "00000020-0000-4000-8000-000000000000", "name": "home-local", "messagingSocketPath": "/x", "updatedAt": 5}))
rc, out = quiet(puller.keep_current, CUR(K8), [], recheck=lambda: puller.sessions(REG))
check("a session that started while the update was being prepared: no merge, no attempt recorded, said", rc is None and head() == Hc and len(puller.attempts()) == n_before and "became busy before the merge" in out
      and "1 live session(s): home-local" in out and len(rd(T / "state/puller-updates.json")["attempts"]) == n_before, (rc, out))
os.remove(T / "reg/1.json")
asked = []
puller._claude_process = lambda: (asked.append(1), "a claude process is running (pid 7)" if len(asked) > 1 else "")[1]   # idle at the first look, a claude -p by the second
rc, out = quiet(puller.keep_current, CUR(K8), [], recheck=lambda: puller.sessions(REG))
puller._claude_process = lambda: ""
check("a claude process that started in that time: the same", rc is None and head() == Hc and len(puller.attempts()) == n_before and len(asked) == 2 and "a claude process is running (pid 7)" in out, (rc, out, asked))
rc, out = quiet(puller.keep_current, CUR(K8), [], recheck=lambda: puller.sessions(REG))
check("…and the next poll, idle, updates it (the busy abort did not use up the target)", rc == puller.RELOAD and head() == K8, (rc, out)); Hc = K8

# ---- a rollback that git refuses (a file it must change has a local edit) leaves HEAD where it is, keeps the edit, says so
K9 = commit("adds file2", **{"file2.txt": "from origin\n"})
def half_merge2(args, timeout=60, **kw):
    if args and args[0] == "merge":
        _g(args, timeout, **kw); (BOX / "file2.txt").write_text("someone's edit\n")
        return 1, "", "error: unable to unlink old 'pages.py': Permission denied"
    return _g(args, timeout, **kw)
puller._git = half_merge2
rc, out = quiet(puller.keep_current, CUR(K9), [])
puller._git = _g
check("a rollback git refuses (the file it would change has a local edit): nothing is reset hard, the edit stays, the refusal is in the reason", rc is None and (BOX / "file2.txt").read_text() == "someone's edit\n"
      and puller.attempts()[-1]["ok"] is False and puller.attempts()[-1]["reason"].startswith("git merge --ff-only: error: unable to unlink") and "; rollback refused: " in puller.attempts()[-1]["reason"], (out, puller.attempts()[-1]))
git(BOX, "checkout", "--", "file2.txt"); Hc = head()

# ---- the claude process check: the CLI's own processes, not Claude Desktop's; a tool that fails means busy
import types
_run = subprocess.run; _cli = puller._cli_paths
CLI = r"C:\Users\x\.local\bin\claude.exe"; DESK = r"C:\Users\x\AppData\Local\AnthropicClaude\app-1.2\claude.exe"
def fake_run(answers):
    """subprocess.run stand-in: answers[0] for the first call, answers[1] for the next …; an Exception is raised."""
    calls = []
    def run(cmd, *a, **k):
        calls.append(cmd); r = answers[min(len(calls), len(answers)) - 1]
        if isinstance(r, Exception): raise r
        return types.SimpleNamespace(returncode=r[0], stdout=r[1], stderr="")
    run.calls = calls
    return run
def cp(answers, win=True, cli=(CLI,), skip=()):
    subprocess.run = fake_run(answers); puller.WINDOWS = win; puller._cli_paths = lambda: {puller._pk(x) for x in cli}
    _rp = puller._router_pids; puller._router_pids = lambda: set(skip)
    _ld = puller._local_dir; puller._local_dir = lambda: puller._pk(r"C:\Users\x\.local")
    try: return REAL_CP(), subprocess.run.calls
    finally: subprocess.run = _run; puller.WINDOWS = False; puller._cli_paths = _cli; puller._router_pids = _rp; puller._local_dir = _ld
j = lambda *rows: json.dumps([{"ProcessId": pid, "ExecutablePath": path} for pid, path in rows])
r, calls = cp([(0, j((100, DESK)))])
check("Windows: Claude Desktop's claude.exe alone is not a claude process (the box is idle)", r == "" and "Get-CimInstance" in " ".join(calls[0]) and "Win32_Process" in " ".join(calls[0]), (r, calls))
r, _ = cp([(0, j((100, DESK), (200, CLI)))])
check("Windows: the CLI's own process is (its pid in the reason)", r == "a claude process is running (pid 200)", r)
r, _ = cp([(0, json.dumps({"ProcessId": 200, "ExecutablePath": CLI}))])
check("Windows: PowerShell's single object (not an array) reads the same", r == "a claude process is running (pid 200)", r)
r, _ = cp([(0, "")])
check("Windows: no claude.exe at all: idle", r == "", r)
r, _ = cp([(0, "null")])
check("Windows: PowerShell's null for nothing: idle, not an error", r == "", r)
LOCAL = r"C:\Users\x\.local\share\claude\versions\2.1.5\claude.exe"
r, _ = cp([(0, j((100, DESK), (400, LOCAL)))])
check("Windows: a claude.exe under ~/.local (a CLI image renamed by an in-place update) counts, Desktop still does not", r == "a claude process is running (pid 400)", r)
r, _ = cp([(0, j((300, CLI)))], skip={300})
check("Windows: the router's own claude -p call is skipped, as sessions() skips it", r == "", r)
r, _ = cp([(0, j((100, "")))])
check("Windows: a process whose path cannot be read counts (it could be the CLI)", r.startswith("a claude process is running (pid 100)"), r)
r, _ = cp([(0, j((100, DESK)))], cli=())
check("Windows: no CLI found to compare with: every claude.exe counts, and the reason says Desktop cannot be told apart", r.startswith("a claude process is running (pid 100)") and "Claude Desktop" in r, r)
wmic = lambda *rows: "\r\nNode,ExecutablePath,ProcessId\r\n" + "".join(f"PC,{path},{pid}\r\n" for pid, path in rows)
r, calls = cp([(1, ""), (0, wmic((100, DESK)))])
check("Windows: PowerShell failing, wmic answers (Desktop alone: idle)", r == "" and calls[1][0] == "wmic", (r, calls))
r, _ = cp([FileNotFoundError("powershell"), (0, wmic((100, DESK), (200, CLI)))])
check("Windows: PowerShell missing, wmic sees the CLI", r == "a claude process is running (pid 200)", r)
r, _ = cp([(1, ""), (1, "")])
check("Windows: neither tool answers: busy, with the reason (fail closed)", r == "cannot tell whether a claude process runs (powershell exit 1; wmic exit 1)", r)
r, _ = cp([subprocess.TimeoutExpired("powershell", 40), OSError("no wmic")])
check("Windows: a timeout and a missing wmic: busy", r.startswith("cannot tell whether a claude process runs ("), r)
r, calls = cp([(1, "")], win=False)
check("Linux: pgrep finds none (rc 1): idle", r == "" and calls[0][:2] == ["pgrep", "-x"], (r, calls))
r, _ = cp([(0, "123\n")], win=False)
check("Linux: pgrep finds one: busy", r == "a claude process is running (pid 123)", r)
r, _ = cp([(0, "123\n")], win=False, skip={123})
check("Linux: …unless it is the router's call", r == "", r)
r, _ = cp([(2, "")], win=False)
check("Linux: pgrep failing (rc 2): busy, not idle", r == "cannot tell whether a claude process runs (pgrep exit 2)", r)
r, _ = cp([FileNotFoundError("pgrep")], win=False)
check("Linux: no pgrep: busy, not idle", r.startswith("cannot tell whether a claude process runs (FileNotFoundError"), r)
rtr = pathlib.Path(tempfile.gettempdir()) / (puller._cfg.ROUTER_CWD_PREFIX + "p189"); rtr.mkdir(exist_ok=True); _scratch.track(rtr)   # a failing check before the rmdir below leaves it otherwise
(T / "reg/2.json").write_text(json.dumps({"pid": 4242, "sessionId": "00000021-0000-4000-8000-000000000000", "cwd": str(rtr), "messagingSocketPath": "/x"}))
(T / "reg/3.json").write_text(json.dumps({"pid": 4243, "sessionId": "00000022-0000-4000-8000-000000000000", "cwd": str(T), "messagingSocketPath": "/x"}))
puller._REG["dir"] = REG
check("the router's own pids come from the registry, as sessions() skips them", puller._router_pids() == {4242}, puller._router_pids())
puller._REG["dir"] = None; os.remove(T / "reg/2.json"); os.remove(T / "reg/3.json"); rtr.rmdir()
puller._claude_process = lambda: "cannot tell whether a claude process runs (pgrep exit 2)"
rc, out = quiet(puller.keep_current, CUR(commit("x", **{"README.md": "nine\n"})), [])
rc2, out2 = quiet(puller.keep_current, CUR(git(ORIGIN, "rev-parse", "HEAD")), [])
puller._claude_process = lambda: ""
check("a box that cannot tell is not moved, and says why once", rc is None and rc2 is None and head() == Hc and out.count("waiting, cannot tell whether a claude process runs (pgrep exit 2)") == 1 and out2 == "", (out, out2))
Hn = git(ORIGIN, "rev-parse", "HEAD")

# ---- a reload that does not load: the old code goes on, the failure is recorded, the files are marked
bad_dir = T / "badreload"; bad_dir.mkdir()
(bad_dir / "puller.py").write_text("import module_that_is_not_there_p189\n")
_real_fresh = puller._fresh; puller._RELOAD_FAIL_PAUSE = 0.0
puller._fresh = lambda here=None: _real_fresh(str(bad_dir))
seq = []; first = lambda argv: (seq.append(1), puller.RELOAD if len(seq) == 1 else 0)[1]
mods = {n: m for n, m in sys.modules.items() if n in ("client", "config", "said")}
rc, out = quiet(puller._entry, ["puller.py"], first)
at = rd(T / "state/puller-updates.json")["attempts"]
check("an import error at load (compile() passes it): the old code resumes instead of the process exiting", rc == 0 and len(seq) == 2 and "failed to load" in out and "module_that_is_not_there_p189" in out, (rc, seq, out[-400:]))
check("…recorded as a failed attempt, reason \"reload failed\", in puller-updates.json", at[-1]["ok"] is False and at[-1]["reason"].startswith("reload failed: ModuleNotFoundError") and at[-1]["what"] == "stackshot checkout", at[-1])
check("…the modules of the old code are still the ones in sys.modules", all(sys.modules.get(n) is m for n, m in mods.items()), [n for n, m in mods.items() if sys.modules.get(n) is not m])
os.environ.pop(puller._RELOAD_AT_ENV, None)
check("…and those files are marked: not a reload target again, while the files stay as they are", os.environ.get(puller._BAD_RELOAD_ENV) == puller._digest(puller.HERE) and puller.reload_due("1", puller.HERE, time.time() + 9999) is False)
_m = os.environ.pop(puller._BAD_RELOAD_ENV)
check("…and unmarked, the same files are due (the mark is what holds it back)", puller.reload_due("1", puller.HERE, time.time() + 9999) is True)
def crash(argv): raise RuntimeError("NameError-like crash at start")
puller._fresh = lambda here=None: {"main": crash}
seq.clear(); rc, out = quiet(puller._entry, ["puller.py"], first)
check("a reloaded main() that raises at once is the same case: logged, recorded, the old code resumes", rc == 0 and len(seq) == 2 and rd(T / "state/puller-updates.json")["attempts"][-1]["reason"].startswith("reload failed: RuntimeError"), (rc, seq, out[-300:]))
puller._RELOAD_CRASH_S = 0.0; seq.clear()
os.environ.pop(puller._BAD_RELOAD_ENV, None)      # (the files marked by the case above)
rc, out = quiet(puller._entry, ["puller.py"], first)
check("…but one that ran for a while before it raised ends the run with 1, as any crash does", rc == 1 and len(seq) == 1, (rc, seq))
puller._RELOAD_CRASH_S = 60.0; puller._fresh = _real_fresh; os.environ.pop(puller._BAD_RELOAD_ENV, None); os.environ.pop(puller._RELOAD_AT_ENV, None); puller._STATE = None
Hc = head()

# ---- the state file cannot be written: the update still reloads
_ss = puller._save_state
def broken_save(): raise OSError("disk full")
puller._save_state = broken_save
Kx = commit("one more", **{"README.md": "ten\n"})
rc, out = quiet(puller.keep_current, CUR(Kx), [])
puller._save_state = _ss
check("_record: a state file that cannot be saved is logged, and the update still answers RELOAD", rc == puller.RELOAD and head() == Kx and "could not save" in out and "disk full" in out, (rc, out)); Hc = Kx

# ---- a RELOAD asked for again while the files are still the marked ones (a pages.py-only commit after the failure): no exit, no second load
puller._fresh = lambda here=None: (loads.append(1), _real_fresh(str(bad_dir)))[1]
loads = []; seq = []
first3 = lambda argv: (seq.append(1), [puller.RELOAD, puller.RELOAD, 0][len(seq) - 1])[1]
os.environ.pop(puller._BAD_RELOAD_ENV, None); os.environ.pop(puller._RELOAD_AT_ENV, None); puller._GATED.discard(puller._BAD_RELOAD_ENV + "-entry")
rc, out = quiet(puller._entry, ["puller.py"], first3)
check("a reload that failed to load, then a RELOAD again for the same files: the old code goes on (never exit 1, which would restart the supervisor onto the broken file), nothing loaded twice, said once",
      rc == 0 and len(seq) == 3 and len(loads) == 1 and out.count("a reload was asked for, but these files failed to load before") == 1, (rc, seq, loads, out[-300:]))
puller._fresh = _real_fresh; os.environ.pop(puller._BAD_RELOAD_ENV, None); os.environ.pop(puller._RELOAD_AT_ENV, None); puller._STATE = None

# ---- the mark covers the modules the puller imports: fixing one lifts it, an unrelated file does not
dg = T / "digestdir"; dg.mkdir()
for n_, t_ in (("puller.py", 'VERSION = "9"\nimport helper_mod\n'), ("client.py", "a = 1\n"), ("config.py", "b = 1\n"), ("said.py", "c = 1\n"), ("helper_mod.py", "def (:\n"), ("pages.py", "p = 1\n")):
    (dg / n_).write_text(t_)
d1 = puller._digest(str(dg)); (dg / "pages.py").write_text("p = 2\n")
check("digest: a file nobody imports (pages.py) does not change it", puller._digest(str(dg)) == d1)
os.environ[puller._BAD_RELOAD_ENV] = d1; os.environ.pop(puller._RELOAD_AT_ENV, None)
qr, _ = quiet(puller.reload_due, "1", str(dg), time.time() + 9999)
check("…so the marked files are not a reload target", qr is False)
(dg / "helper_mod.py").write_text("h = 1\n")
check("digest: a fix to an imported module (helper_mod.py) changes it, and the mark no longer holds", puller._digest(str(dg)) != d1 and puller.reload_due("1", str(dg), time.time() + 9999) is True)
os.environ.pop(puller._BAD_RELOAD_ENV, None)

# ---- two reloads in a row, the second fails: its record survives the first reload's code recording after it
fresh_ns = runpy.run_path(os.path.join(STACK, "puller.py"), run_name="puller_first_reload")
fresh_ns = fresh_ns["_record"].__globals__      # run_path returns a copy; the functions' own globals are the module's, as in a real reload (_fresh()["main"].__globals__)
fresh_ns["_CALLS"] = []
exec('''def m1(argv):
    _CALLS.append(1)
    if len(_CALLS) == 1:
        _record("stackshot checkout", "a" * 12, "b" * 12, True, "")
        return RELOAD
    _record("stackshot checkout", "b" * 12, "c" * 12, True, "")
    return 0
''', fresh_ns)
puller._STATE = None; fresh_ns["_STATE"] = None
loads2 = []
def fresh_twice(here=None):
    loads2.append(1)
    if len(loads2) == 1: return {"main": fresh_ns["m1"]}
    raise ImportError("the second reload does not load")
puller._fresh = fresh_twice; os.environ.pop(puller._RELOAD_AT_ENV, None)
rc, out = quiet(puller._entry, ["puller.py"], lambda argv: puller.RELOAD)
tail3 = [(a["from"], a["to"], a["ok"], a["reason"][:13]) for a in rd(T / "state/puller-updates.json")["attempts"][-3:]]
check("two reloads in a row, the second failing: the failure is recorded and the next record of the code that goes on does not overwrite it",
      rc == 0 and tail3 == [("a" * 12, "b" * 12, True, ""), (tail3[1][0], tail3[1][1], False, "reload failed"), ("b" * 12, "c" * 12, True, "")], (rc, tail3, out[-300:]))
puller._fresh = _real_fresh; os.environ.pop(puller._BAD_RELOAD_ENV, None); os.environ.pop(puller._RELOAD_AT_ENV, None); puller._STATE = None

# ---- a box in its backoff does not run the process check on every poll
Hb = commit("one for the backoff", **{"README.md": "eleven\n"})
puller._state()["tried"]["stackshot checkout"] = {"to": Hb, "at": time.time(), "n": 1}
asked = []
puller._claude_process = lambda: (asked.append(1), "")[1]
rc, out = quiet(puller.keep_current, CUR(Hb), [])
puller._claude_process = lambda: ""
check("backoff: busy() is not asked while the target waits out its backoff", rc is None and asked == [] and head() == Hc, (rc, asked))
puller._state()["tried"].pop("stackshot checkout")

# ---- the server's commit goes to git only as a full sha
check("plan: anything but 40 lowercase hex from the server is no plan (it would be a git argument)", all(puller.plan({"stackshot": v}, []) == [] for v in ("--upload-pack=x", "A" * 40, "1234", "a" * 39, "a" * 41, " " + "a" * 40)))

# ---- head() that cannot tell says why, once
puller.CHECKOUT = str(T / "notarepo"); (T / "notarepo").mkdir(); puller._HEAD["at"] = 0.0; puller._SAID.pop("head", None)
head1, o1 = quiet(puller.head); puller._HEAD["at"] = 0.0
head2, o2 = quiet(puller.head)
puller.CHECKOUT = str(BOX); puller._HEAD["at"] = 0.0
check("head(): not a git checkout → \"\", with the reason logged once", head1 == "" and head2 == "" and "cannot tell this checkout's commit (fatal: not a git repository" in o1 and o2 == "", (head1, o1, o2))
check("…and back to a commit when it can", head() == Hc and "head" not in puller._SAID)

# ---- git never prompts: not for a terminal, not for Git Credential Manager
envs = []
subprocess.run = lambda cmd, *a, **k: (envs.append(k.get("env") or {}), types.SimpleNamespace(returncode=0, stdout="", stderr=""))[1]
try: puller._git(["status"])
finally: subprocess.run = _run
check("git runs with GIT_TERMINAL_PROMPT=0 and GCM_INTERACTIVE=never", envs and envs[0].get("GIT_TERMINAL_PROMPT") == "0" and envs[0].get("GCM_INTERACTIVE") == "never", envs)
Hc = head()

# ============================================================= 6. --dry-run: the verdict, nothing done
I = commit("one more", **{"README.md": "six\n"})
puller._LAST["current"] = CUR(I)
rc, out = quiet(puller.keep_current, puller._LAST["current"], [], dry=True)
check("dry run, idle: says what it would update now, does nothing", rc is None and out == f"would update stackshot checkout {Hc[:12]} → {I[:12]} now (the box is idle)\n" and head() == Hc, out)
(T / "reg/1.json").write_text(json.dumps({"pid": os.getpid(), "sessionId": "00000020-0000-4000-8000-000000000000", "name": "home-local", "messagingSocketPath": "/x", "updatedAt": 5}))
rc, out = quiet(puller.keep_current, puller._LAST["current"], puller.sessions(REG), dry=True)
check("dry run, busy: says why not", f"would update stackshot checkout {Hc[:12]} → {I[:12]}, but not now: 1 live session(s): home-local" in out, out)
os.remove(T / "reg/1.json")
puller._STATE["tried"]["stackshot checkout"] = {"to": I, "at": time.time(), "n": 1}
rc, out = quiet(puller.keep_current, puller._LAST["current"], [], dry=True)
check("dry run: a target in its backoff says so", f"would update stackshot checkout {Hc[:12]} → {I[:12]} now (the box is idle) (waiting out the backoff after an earlier try)" in out, out)
puller._STATE["tried"].pop("stackshot checkout")
with TestClient(app) as c:
    puller._SAID.pop("mode", None)
    rc, out = quiet(puller.main, ["puller.py", "--dry-run", "--registry", REG])
    check("puller.py --dry-run: one poll, then the update verdict against what the server said", rc == 0 and "claude" not in out
          and f"would update stackshot checkout {Hc[:12]} → {MINE[:12]}" in out and "keeping this box current: on" in out, (rc, out))
# a server with no current (an older server): nothing, no error
rc, out = quiet(puller.keep_current, None, [])
check("an answer without current (an older server): nothing", rc is None and out == "")

# ============================================================= 7. only main is advertised, and a box stranded off main is put back
# ---- server: clients.checkout_commit advertises HEAD only while origin/main contains it
warned = []; _w = cl.log.warning; cl.log.warning = lambda msg, *a: warned.append(msg % a)
def advertised() -> str:
    cl._COMMIT["at"] = 0.0
    return cl.checkout_commit()
try:
    cl._COMMIT.update(at=0.0, v="", good="", held=""); (cl.DIR / "advertised-commit").unlink(missing_ok=True)
    check("server: a HEAD that origin/main contains is advertised, and remembered on disk", advertised() == MINE and cl._COMMIT["good"] == MINE
          and (cl.DIR / "advertised-commit").read_text().strip() == MINE and warned == [], (advertised(), warned))
    (SRV / "f.txt").write_text("pr\n"); git(SRV, "commit", "-q", "-am", "an unmerged branch"); PRC = git(SRV, "rev-parse", "HEAD")
    got = [advertised() for _ in range(3)]
    check("server: a HEAD that origin/main does not contain is held back: the last advertised commit stays, with one warning line (not one per request)",
          got == [MINE] * 3 and len(warned) == 1 and PRC[:12] in warned[0] and MINE[:12] in warned[0], (got, warned))
    cl._COMMIT.update(good="")                                  # a restart: nothing in memory, the file remembers
    check("server: after a restart the held-back HEAD still advertises the last good commit from disk", advertised() == MINE, advertised())
    cl._COMMIT.update(good="", held=""); (cl.DIR / "advertised-commit").unlink()
    check("server: with no last good commit, origin/main's own commit is advertised", advertised() == MINE and cl._COMMIT["good"] == "", (advertised(),))
    git(SRV, "update-ref", "refs/remotes/origin/main", PRC)    # the branch is merged (fetched)
    check("server: once origin/main contains HEAD it is advertised again", advertised() == PRC and cl._COMMIT["good"] == PRC and cl._COMMIT["held"] == "", (advertised(), cl._COMMIT))
    (SRV / "f.txt").write_text("behind\n"); git(SRV, "commit", "-q", "-am", "more"); git(SRV, "update-ref", "refs/remotes/origin/main", git(SRV, "rev-parse", "HEAD"))
    git(SRV, "reset", "-q", "--hard", PRC)
    check("server: a HEAD behind origin/main (an ordinary lag) is advertised", advertised() == PRC, advertised())
finally:
    cl.log.warning = _w; cl.CHECKOUT = str(SRV)

# ---- puller: a clean box stranded on a commit it followed that main does not contain goes back to the server's commit
def box_to(sha):
    """Fixture setup only: put the box on `sha` as someone's hand would (not the puller), the puller's HEAD cache refreshed."""
    git(BOX, "fetch", "-q", "origin"); git(BOX, "reset", "-q", "--hard", sha); head()
def fresh_record():
    puller._STATE["tried"].pop("stackshot checkout", None)
git(ORIGIN, "checkout", "-q", "main")
R0 = commit("r0", **{"README.md": "r0\n"}); box_to(R0); fresh_record()
git(ORIGIN, "checkout", "-q", "-b", "pr1"); X = commit("pr1 only", **{"README.md": "pr1\n"})
rc, out = quiet(puller.keep_current, CUR(X), [])        # the server advertised an unmerged branch for a minute: the box follows
check("stranded: the box followed the advertised commit (the first half)", rc == puller.RELOAD and head() == X and X in puller._state()["moved"], (out, head()))
git(ORIGIN, "checkout", "-q", "main"); M1 = commit("main moves on", **{"README.md": "m1\n"})
rc, out = quiet(puller.keep_current, CUR(M1), [])
at = puller.attempts()[-1]
check("stranded: a clean box that sits on a commit it followed itself, not in origin/main, is put back on the advertised commit, and reloads",
      rc == puller.RELOAD and head() == M1 and (BOX / "README.md").read_text() == "m1\n" and git(BOX, "status", "--porcelain", "--untracked-files=no") == "", (rc, out, head()))
check("stranded: the recovery is in the update record: an ok attempt saying so, and the recovered list", at["ok"] is True and at["from"] == X[:12] and at["to"] == M1[:12]
      and at["reason"].startswith("recovered: left " + X[:12]) and rd(T / "state/puller-updates.json")["recovered"][-1]["from"] == X and M1 in rd(T / "state/puller-updates.json")["moved"], (at, rd(T / "state/puller-updates.json")))

# a dirty box is refused (tracked edit), and so is one whose untracked file is in the way of the move
fresh_record(); git(ORIGIN, "checkout", "-q", "-b", "pr2"); Y = commit("pr2 only", **{"README.md": "pr2\n"})
rc, out = quiet(puller.keep_current, CUR(Y), [])
git(ORIGIN, "checkout", "-q", "main"); M2 = commit("main again", **{"README.md": "m2\n", "clash.txt": "from main\n"})
(BOX / "README.md").write_text("edited on the box\n"); fresh_record()
rc, out = quiet(puller.keep_current, CUR(M2), [])
check("stranded: a dirty box is refused, HEAD and the edit stay", rc is None and head() == Y and (BOX / "README.md").read_text() == "edited on the box\n"
      and puller.attempts()[-1]["ok"] is False and puller.attempts()[-1]["reason"] == "local changes in the checkout", (out, puller.attempts()[-1], head()))
git(BOX, "checkout", "--", "README.md"); (BOX / "clash.txt").write_text("mine, untracked\n"); fresh_record()
rc, out = quiet(puller.keep_current, CUR(M2), [])
check("stranded: an untracked file that the move would overwrite is refused by git, nothing lost, HEAD stays", rc is None and head() == Y and (BOX / "clash.txt").read_text() == "mine, untracked\n"
      and puller.attempts()[-1]["ok"] is False and puller.attempts()[-1]["reason"].startswith("git reset --keep: "), (out, puller.attempts()[-1], head()))
(BOX / "clash.txt").unlink(); fresh_record()
rc, out = quiet(puller.keep_current, CUR(M2), [])
check("stranded: the same box recovers once the edit and the file are gone", rc == puller.RELOAD and head() == M2, (out, head()))

# a HEAD the puller did not move to (no record of it) is moved all the same: the rollback branch is what keeps it
git(ORIGIN, "checkout", "-q", "-b", "pr3"); Z = commit("pr3 only", **{"README.md": "pr3\n"})
git(ORIGIN, "checkout", "-q", "main"); M3 = commit("main third", **{"README.md": "m3\n"})
box_to(Z); fresh_record()
check("stranded: Z is no commit the puller moved to", Z not in puller._state()["moved"] and all(a["to"] != Z[:12] for a in puller._state()["attempts"]))
rc, out = quiet(puller.keep_current, CUR(M3), [])
check("stranded: a HEAD the puller did not move to (a branch put there by hand) is moved too, after its rollback branch is saved at it", rc == puller.RELOAD and head() == M3
      and puller.attempts()[-1]["ok"] is True and puller.attempts()[-1]["reason"] == f"recovered: left {Z[:12]}, which is not in origin/main (saved as legacy-{Z[:12]})"
      and git(BOX, "rev-parse", f"legacy-{Z[:12]}") == Z, (out, puller.attempts()[-1], head()))
git(ORIGIN, "checkout", "-q", "main")

# ---- this shape: the box's HEAD descends from the advertised commit (the server went back to main), is off main, and recovers
fresh_record(); box_to(M3); M4 = commit("main four", **{"README.md": "m4\n"})
rc, out = quiet(puller.keep_current, CUR(M4), [])
git(ORIGIN, "checkout", "-q", "-b", "pr4"); X4 = commit("pr4 on top of main four", **{"README.md": "pr4\n"})
fresh_record(); rc, out = quiet(puller.keep_current, CUR(X4), [])
check("case: the box followed a branch built on top of main", head() == X4 and X4 in puller._state()["moved"] and puller._git(["merge-base", "--is-ancestor", M4, X4])[0] == 0, (out, head()))
git(ORIGIN, "checkout", "-q", "main"); puller._AHEAD.discard(M4); fresh_record()
rc, out = quiet(puller.keep_current, CUR(M4), [])
check("case: HEAD descends from the advertised commit and is off main: it is put back (not left as 'ahead of the server'), and M4 is not cached as ahead",
      rc == puller.RELOAD and head() == M4 and puller.attempts()[-1]["reason"].startswith("recovered: left " + X4[:12]) and M4 not in puller._AHEAD, (rc, out, head(), puller.attempts()[-1]))

# ---- an old-format record (no "moved" list) is matched through the short `to` of an ok attempt, and only an ok one
M5 = commit("main five", **{"README.md": "m5\n"}); git(ORIGIN, "checkout", "-q", "-b", "pr5"); X5 = commit("pr5 only", **{"README.md": "pr5\n"})
git(ORIGIN, "checkout", "-q", "main"); M6 = commit("main six", **{"README.md": "m6\n"})
box_to(X5); fresh_record(); moved_now = puller._state().pop("moved"); stamp = "2026-11-02T00:00:00Z"
puller._state()["attempts"].append({"what": "stackshot checkout", "from": M5[:12], "to": X5[:12], "ok": False, "reason": "x", "at": stamp})
rc, out = quiet(puller.keep_current, CUR(M6), [])
check("old record: a failed attempt at the commit is no reason to refuse (the record does not matter any more): recovered", rc == puller.RELOAD and head() == M6 and puller.attempts()[-1]["reason"].startswith("recovered"), (out, puller.attempts()[-1]))
box_to(X5)
puller._state()["attempts"].append({"what": "stackshot checkout", "from": M5[:12], "to": X5[:12], "ok": True, "reason": "", "at": stamp}); fresh_record()
rc, out = quiet(puller.keep_current, CUR(M6), [])
check("old record: an ok attempt naming the commit short (a record from before 'moved'): recovered too", rc == puller.RELOAD and head() == M6
      and puller.attempts()[-1]["reason"].startswith("recovered"), (out, head(), puller.attempts()[-1]))

# ---- a fetch failure on the ahead-and-in-main path is silent: no fetch, no failed attempt
M7 = commit("main seven", **{"README.md": "m7\n"}); M8 = commit("main eight", **{"README.md": "m8\n"})
fresh_record(); rc, out = quiet(puller.keep_current, CUR(M8), [])
git(BOX, "remote", "set-url", "origin", str(T / "nowhere")); n_before = len(puller.attempts()); calls = []
def spy(args, timeout=60, **kw):
    calls.append(list(args)); return _g(args, timeout, **kw)
puller._git = spy; puller._AHEAD.discard(M7); fresh_record()
rc, out = quiet(puller.keep_current, CUR(M7), [])
puller._git = _g
check("ahead and in main (the remote unreachable): nothing to do, silent, no fetch, no failed attempt, cached as ahead",
      rc is None and "FAILED" not in out and "fetch" not in out.replace("nothing to do", "") and not any(c[0] == "fetch" for c in calls) and len(puller.attempts()) == n_before and M7 in puller._AHEAD, (out, calls, len(puller.attempts()), n_before))
git(BOX, "remote", "set-url", "origin", str(ORIGIN))

# ---- "could not tell" (a fetch that failed, an rc other than 0 or 1, a timeout): a failed attempt, never cached as ahead, retried by the backoff
git(ORIGIN, "checkout", "-q", "-b", "pr8"); X8 = commit("pr8 on top of main eight", **{"README.md": "pr8\n"}); git(ORIGIN, "checkout", "-q", "main")
fresh_record(); rc, out = quiet(puller.keep_current, CUR(X8), [])
puller._AHEAD.discard(M8); git(BOX, "remote", "set-url", "origin", str(T / "nowhere")); fresh_record()
rc, out = quiet(puller.keep_current, CUR(M8), [])
check("unknown: the local ref says off main and the fetch fails: 'could not tell', HEAD stays, not cached as ahead",
      rc is None and head() == X8 and puller.attempts()[-1]["ok"] is False and puller.attempts()[-1]["reason"].startswith("could not tell") and "git fetch" in puller.attempts()[-1]["reason"]
      and M8 not in puller._AHEAD, (out, puller.attempts()[-1], head()))
git(BOX, "remote", "set-url", "origin", str(ORIGIN))
for bad_rc in (128, 124):
    def rc_git(args, timeout=60, bad_rc=bad_rc, **kw):
        if args[:2] == ["merge-base", "--is-ancestor"] and args[3] == "refs/remotes/origin/main":
            return bad_rc, "", ""
        return _g(args, timeout, **kw)
    puller._git = rc_git; fresh_record()
    rc, out = quiet(puller.keep_current, CUR(M8), [])
    puller._git = _g
    check(f"unknown: merge-base answering rc {bad_rc} is neither yes nor no: 'could not tell', HEAD stays, not cached as ahead",
          rc is None and head() == X8 and puller.attempts()[-1]["reason"].startswith("could not tell") and f"git exit {bad_rc}" in puller.attempts()[-1]["reason"] and M8 not in puller._AHEAD,
          (out, puller.attempts()[-1], head()))
fresh_record(); rc, out = quiet(puller.keep_current, CUR(M8), [])
check("unknown: the backoff over and git answering again, the box recovers", rc == puller.RELOAD and head() == M8 and puller.attempts()[-1]["reason"].startswith("recovered"), (out, head(), puller.attempts()[-1]))

# ---- the cap on the commits kept as the puller's own
puller._state()["moved"] = []
fakes = [f"{i:040x}" for i in range(1, 26)]
for f in fakes: quiet(puller._record, "stackshot checkout", "a" * 40, f, True, "")
quiet(puller._record, "stackshot checkout", "a" * 40, fakes[10], True, "")        # recorded again: moves to the end, no duplicate
mv = puller._state()["moved"]
check("moved: capped at _MOVED_KEEP, oldest dropped, a repeat moves to the end without a duplicate", len(mv) == puller._MOVED_KEEP == 20 and mv[-1] == fakes[10] and len(set(mv)) == 20
      and fakes[0] not in mv and fakes[-1] in mv and rd(T / "state/puller-updates.json")["moved"] == mv, (len(mv), mv[-2:]))
quiet(puller._record, "stackshot checkout", "a" * 40, "b" * 40, False, "failed")
check("moved: a failed attempt adds nothing", "b" * 40 not in puller._state()["moved"])

# ---- a checkout that reached the server's commit another way (swapped, put there by hand) stops reporting an older failure
from ui import render as _render
box_to(M8); puller._state()["moved"] = []; fresh_record()
OLD = "1" * 40                                                   # the commit the server advertised when the attempt failed
puller._state()["attempts"] += [{"what": "stackshot checkout", "from": "2" * 12, "to": OLD[:12], "ok": False, "reason": f"the server's commit {OLD[:12]} is not on origin", "at": "2026-11-01T00:00:00Z"},
                                {"what": "claude cli", "from": "2.0.0", "to": "2.1.0", "ok": False, "reason": "the installer failed", "at": "2026-11-01T00:01:00Z"}]
shown = lambda: sorted((u["what"], u["reason"]) for u in _render.machine_alerts({"updates": puller.attempts()})[1])
snap = lambda: json.dumps(puller.attempts())              # the report is capped at 10, so a count says nothing: compare the lists
check("settle: before, the panel draws both failures", [w for w, _ in shown()] == ["claude cli", "stackshot checkout"], shown())
was = list(puller.attempts())
rc, out = quiet(puller.keep_current, CUR(M8), [])
at = puller.attempts()[-1]
check("settle: HEAD already at the server's commit and the latest checkout attempt a failure: one ok attempt is recorded (from = to), nothing is updated, no reload",
      rc is None and puller.attempts()[:-1] == was[1:] and (at["what"], at["from"], at["to"], at["ok"], at["reason"]) == ("stackshot checkout", M8[:12], M8[:12], True, "already at the server's commit")
      and head() == M8 and f"update stackshot checkout {M8[:12]} → {M8[:12]}: ok" in out, (rc, out, at))
check("settle: the panel no longer draws the checkout's failure, and the other `what`'s failure stays (it is not the checkout's)", shown() == [("claude cli", "the installer failed")], shown())
check("settle: it is kept on the box and reported as sent (the server's clean_updates keeps the shape)", rd(T / "state/puller-updates.json")["attempts"][-1] == at and cl.clean_updates(puller.attempts())[-1]["ok"] is True)
check("settle: it is no commit the puller moved to, and leaves no try behind", M8 not in puller._state()["moved"] and "stackshot checkout" not in puller._state()["tried"], puller._state())
was = snap(); disk = (T / "state/puller-updates.json").read_text()
rc, out = quiet(puller.keep_current, CUR(M8), [])
rc2, out2 = quiet(puller.keep_current, CUR(M8, on=False), [])
check("settle: the next polls record nothing more (also with updates off)", rc is None and rc2 is None and "update " not in out + out2 and snap() == was and (T / "state/puller-updates.json").read_text() == disk, (out, out2))
puller._state()["attempts"].append({"what": "stackshot checkout", "from": "3" * 12, "to": OLD[:12], "ok": False, "reason": "again", "at": "2026-11-02T00:00:00Z"}); was = snap()
rc, out = quiet(puller.keep_current, CUR(M8), [], True)
check("settle: a --dry-run records nothing", snap() == was and puller.attempts()[-1]["ok"] is False, (out, puller.attempts()[-1]))
rc, out = quiet(puller.keep_current, CUR(M8), [])
check("settle: a later failure at an older target settles again, once", puller.attempts()[-2]["reason"] == "again" and puller.attempts()[-1]["reason"] == puller._REACHED, puller.attempts()[-2:])

# a failure for a target not reached yet stays
P1 = commit("p1", **{"README.md": "p1\n"})
# the finding is no claim that the puller moved the box: a HEAD off main whose only ok attempt is the "already there" one is not the puller's own
git(ORIGIN, "checkout", "-q", "-b", "pr9"); X9 = commit("pr9 only", **{"README.md": "pr9\n"}); git(ORIGIN, "checkout", "-q", "main")
box_to(X9); puller._state()["moved"] = []; puller._state()["attempts"] = [{"what": "stackshot checkout", "from": X9[:12], "to": X9[:12], "ok": True, "reason": puller._REACHED, "at": "2026-11-02T00:00:00Z"}]
check("settle: a commit reached another way, off main, is moved off like any other (the record of how the box got there does not matter)", puller._stranded(P1)[0] == "yes", puller._stranded(P1))
puller._state()["attempts"][0]["reason"] = ""
check("settle: …an ordinary ok attempt at it makes no difference", puller._stranded(P1)[0] == "yes", puller._stranded(P1))
box_to(M8); puller._state()["attempts"] = []; puller._state()["moved"] = []; fresh_record()
puller._state()["attempts"] += [{"what": "claude cli", "from": "2.0.0", "to": "2.1.0", "ok": False, "reason": "the installer failed", "at": "2026-11-01T00:01:00Z"}]
puller._state()["attempts"].append({"what": "stackshot checkout", "from": M8[:12], "to": P1[:12], "ok": False, "reason": "local changes in the checkout", "at": "2026-11-03T00:00:00Z"})
puller._state()["tried"]["stackshot checkout"] = {"to": P1, "at": time.time(), "n": 1}; was = snap()
rc, out = quiet(puller.keep_current, CUR(P1), [])
check("settle: a failure for a target not reached (HEAD is behind it, in its backoff) stays the latest, nothing recorded",
      rc is None and out == "" and snap() == was and puller.attempts()[-1]["ok"] is False and [w for w, _ in shown()] == ["claude cli", "stackshot checkout"], (out, puller.attempts()[-1]))
puller._state()["tried"].pop("stackshot checkout"); puller._state()["attempts"] = [a for a in puller.attempts() if a["to"] != OLD[:12] and a["reason"] != "local changes in the checkout"]
puller._state()["attempts"] += [{"what": "stackshot checkout", "from": M8[:12], "to": P1[:12], "ok": False, "reason": "local changes in the checkout", "at": "2026-11-03T00:00:00Z"}]
rc, out = quiet(puller.keep_current, CUR(P1), [])
check("settle: the same failure with the backoff over: the box is updated to the target, and that ok attempt (a real one, from M8 to P1) is the latest",
      rc == puller.RELOAD and head() == P1 and puller.attempts()[-1]["ok"] is True and puller.attempts()[-1]["from"] == M8[:12] and puller.attempts()[-1]["to"] == P1[:12] and puller.attempts()[-1]["reason"] == "" and P1 in puller._state()["moved"], (rc, out, puller.attempts()[-1]))
box_to(M8)

# a failed reload at the server's commit is a real failure: it stays
quiet(puller._record, "stackshot checkout", M8[:12], M8, False, f"{puller._RELOAD_FAILED}: ImportError: x")
n_before = len(puller.attempts()); rc, out = quiet(puller.keep_current, CUR(M8), [])
check("settle: a failed reload (the code at HEAD does not load) is not cleared by being at the server's commit", rc is None and len(puller.attempts()) == n_before and puller.attempts()[-1]["reason"].startswith("reload failed") and out == "", (out, puller.attempts()[-1]))

# a reload that failed on an OLDER commit than HEAD is as stale as any other failure: it settles
puller._state()["attempts"] = [{"what": "stackshot checkout", "from": "4" * 12, "to": OLD[:12], "ok": False, "reason": f"{puller._RELOAD_FAILED}: ImportError: y", "at": "2026-11-01T00:00:00Z"}]
rc, out = quiet(puller.keep_current, CUR(M8), [])
check("settle: a failed reload whose target is an older commit than HEAD is settled (only a reload of HEAD itself stands)", len(puller.attempts()) == 2 and puller.attempts()[-1]["reason"] == puller._REACHED and shown() == [], puller.attempts())

# the first settle with the box's updates off, and with the box busy: it only corrects what is reported
stale = {"what": "stackshot checkout", "from": "5" * 12, "to": OLD[:12], "ok": False, "reason": "local changes in the checkout", "at": "2026-11-01T00:00:00Z"}
for label, cur_, recs_ in (("updates off", CUR(M8, on=False), []), ("the box busy", CUR(M8), puller.sessions(REG) or [{"sessionId": "x", "name": "busy-one"}])):
    puller._state()["attempts"] = [dict(stale)]
    rc, out = quiet(puller.keep_current, cur_, recs_)
    check(f"settle: the first settle also happens with {label}", rc is None and puller.attempts()[-1]["reason"] == puller._REACHED and puller.attempts()[-1]["ok"] is True and shown() == [], (out, puller.attempts()))

# a commit that does not compile put on the box by hand: the refusal ("does not compile at ...") is still true, it stays
git(ORIGIN, "checkout", "-q", "-b", "prA"); KA = commit("puller.py broken", **{"puller.py": "def (:\n"}); git(ORIGIN, "checkout", "-q", "main")
puller._state()["attempts"] = [{"what": "stackshot checkout", "from": M8[:12], "to": KA[:12], "ok": False, "reason": f"puller.py does not compile at {KA[:12]}", "at": "2026-11-01T00:00:00Z"}]
box_to(KA); was = snap()
rc, out = quiet(puller.keep_current, CUR(KA), [])
check("settle (A): a broken commit checked out by hand (the server advertises it, the refusal says puller.py does not compile at it) stays red",
      rc is None and snap() == was and out == "" and [w for w, _ in shown()] == ["stackshot checkout"], (out, puller.attempts()))
git(ORIGIN, "checkout", "-q", "-b", "prB"); KB = commit("helper_mod broken", **{"helper_mod.py": "def (:\n"}); git(ORIGIN, "checkout", "-q", "main")
puller._state()["attempts"] = [{"what": "stackshot checkout", "from": M8[:12], "to": KB[:12], "ok": False, "reason": f"helper_mod.py does not compile at {KB[:12]}; rollback refused: error: x", "at": "2026-11-01T00:00:00Z"}]
box_to(KB); was = snap()
rc, out = quiet(puller.keep_current, CUR(KB), [])
check("settle (B): a refused rollback leaves HEAD on a tree that does not compile: the failure stays red", rc is None and snap() == was and out == "" and [w for w, _ in shown()] == ["stackshot checkout"], (out, puller.attempts()))
box_to(M8); fresh_record()
# HEAD is read again before the record: a checkout moved by the compile check's time is not recorded as at the server's commit
puller._state()["attempts"] = [dict(stale)]; real_compiles = puller._compiles
def moving(here):                                   # a bare reset, no head() call: the puller's 5-minute cache of HEAD stays at the old commit, as after a real move
    git(BOX, "reset", "-q", "--hard", KA); return ""
head(); puller._compiles = moving; was = snap()
rc, out = quiet(puller.keep_current, CUR(M8), [])
puller._compiles = real_compiles
check("settle: HEAD moved while the compile check ran: it is not recorded as at the server's commit (the box, now off main, is moved by the update, which says so)",
      puller.attempts()[0]["ok"] is False and all(a["reason"] != puller._REACHED for a in puller.attempts()) and puller.attempts()[-1]["reason"].startswith("recovered: left " + KA[:12]), (out, puller.attempts()))
box_to(M8); fresh_record()

# no attempt at all, or an ok one: nothing; other `what`s alone: nothing for the checkout
puller._state()["attempts"] = [{"what": "claude cli", "from": "2.0.0", "to": "2.1.0", "ok": False, "reason": "the installer failed", "at": "2026-11-01T00:01:00Z"}]; puller._state()["tried"].clear()
rc, out = quiet(puller.keep_current, CUR(M8), [])
check("settle: a failed attempt of another `what` alone is untouched, and nothing is recorded for the checkout", rc is None and out == "" and [a["what"] for a in puller.attempts()] == ["claude cli"] and puller.attempts()[0]["ok"] is False, puller.attempts())
puller._state()["attempts"] = []
rc, out = quiet(puller.keep_current, CUR(M8), [])
check("settle: a box that has no attempt records nothing", rc is None and out == "" and puller.attempts() == [])

# ---- server: git answering something other than yes or no, and a damaged advertised-commit file
warned = []; _w = cl.log.warning; cl.log.warning = lambda msg, *a: warned.append(msg % a); _real = cl._git_out
try:
    git(SRV, "reset", "-q", "--hard", "refs/remotes/origin/main"); (SRV / "f.txt").write_text("off\n"); git(SRV, "commit", "-q", "-am", "off main again"); OFF = git(SRV, "rev-parse", "HEAD")
    MAIN = git(SRV, "rev-parse", "refs/remotes/origin/main")
    for bad_rc in (128, 127):
        def fake_git(*a, bad_rc=bad_rc):
            return (bad_rc, "") if a[0] == "merge-base" else _real(*a)
        cl._git_out = fake_git
        cl._COMMIT.update(at=0.0, v=MAIN, good="", held=""); warned.clear()
        check(f"server: merge-base answering rc {bad_rc} is not 'off main': the previous answer is kept, nothing logged", advertised() == MAIN and warned == [] and cl._COMMIT["held"] == "", (advertised(), warned))
        cl._COMMIT.update(at=0.0, v="")
        check(f"server: rc {bad_rc} and no previous answer: HEAD is advertised, nothing logged", advertised() == OFF and warned == [], (advertised(), warned))
    def ref_git(*a):
        return (127, "") if a[0] == "rev-parse" and "--verify" in a else _real(*a)
    cl._git_out = ref_git; cl._COMMIT.update(at=0.0, v=MAIN, good="", held=""); warned.clear()
    check("server: the origin/main ref check timing out keeps the previous answer, nothing logged", advertised() == MAIN and warned == [], (advertised(), warned))
    cl._git_out = _real; (cl.DIR / "advertised-commit").unlink(missing_ok=True); cl._COMMIT.update(good="")
    check("server: with git answering again the off-main HEAD is held back as before (one warning)", advertised() == MAIN and len(warned) == 1, (advertised(), warned))
    for label, text in (("garbage", "not a commit\n"), ("an object that is gone", "d" * 40 + "\n"), ("empty", ""), ("binary", "\x00\x01\x02")):
        (cl.DIR / "advertised-commit").write_text(text, encoding="utf-8"); cl._COMMIT.update(at=0.0, v="", good="", held=""); warned.clear()
        check(f"server: an advertised-commit file with {label} is ignored: origin/main's own commit is advertised, a warning logged", advertised() == MAIN and cl._COMMIT["good"] == "" and len(warned) == 1, (advertised(), cl._COMMIT, warned))
finally:
    cl._git_out = _real; cl.log.warning = _w

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": update scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
