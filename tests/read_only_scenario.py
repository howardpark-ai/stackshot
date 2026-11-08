"""Scenario test for the read-only mode of a warm standby copy: STACKSHOT_READ_ONLY=1 in the environment at start. Fixture data, the
HTTP routes through Starlette's test client, anchor-hub as a real child process on an ephemeral port; no live store, no network.

Covers: the switch (env at start: unset, 0, 1; one is_read_only()); the reads that keep working (get, brief, sessions, rules, anchors that only lists;
the home page, an item page and search served from the copy, with the banner); every write tool refused with the one sentence, and the data unchanged;
every web write (each POST route, GET and POST on /audit/now) answered 503 with that sentence; the lowest layers raising when called directly (item write,
id allocation, anchors store, project registry, publish, a file write or a git write under the instance's directories); no thread started and
nothing written when the server starts (_start_background); /healthz (first line ok, then the read-only line with the data age from `.synced-at`) and
/healthz?format=json, in both modes; the live instance (switch off) unchanged. anchor-hub: with the switch on it starts no receiver and no poller,
writes no state, and its hook port answers every request 503 `standby (STACKSHOT_READ_ONLY)`. At the end every directory of the instance is
byte-for-byte what the fixture left, and the state directory was never made.

    tests/run-suite read_only        → exit 0 / 1"""
import asyncio, atexit, hashlib, http.client, json, logging, os, pathlib, re, socket, subprocess, sys, threading, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
BOARD = "https://board.example.org"

if len(sys.argv) > 2 and sys.argv[1] == "--normal-child":
    # A normal start (STACKSHOT_READ_ONLY unset) in a process of its own, over the folder the parent made: what the live instance is at start. Prints one JSON line.
    root = sys.argv[2]
    os.environ.pop("STACKSHOT_READ_ONLY", None); os.environ.pop("STACKSHOT_URL", None)
    os.environ.update(STACKSHOT_CONFIG=f"{root}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{root}/fleet")
    sys.path.insert(0, STACK); logging.disable(logging.CRITICAL)
    import readonly, server
    from starlette.testclient import TestClient
    app = server.mcp.http_app()
    routes = {}
    for r in app.routes:
        if hasattr(getattr(r, "endpoint", None), "__wrapped__"): routes.setdefault(r.path, set()).update(r.methods)
    out = {"ro": readonly.is_read_only(), "hooked": readonly._HOOKED, "routes": {k: sorted(v) for k, v in routes.items()}}
    with TestClient(app, base_url=BOARD) as c:
        h = c.get("/")
        out["home"] = [h.status_code, h.text]
        hz = c.get("/healthz"); out["healthz"] = hz.text
        out["json"] = c.get("/healthz?format=json").json()
        pg = c.get("/items/a1"); out["item"] = [pg.status_code, "ro-banner" in pg.text]
        out["post"] = c.post("/items/a1/answer", data={"choice": "Ship"}, headers={"Origin": BOARD}).status_code
    print(json.dumps(out))
    sys.exit(0)

tmp = _scratch.mkdtemp(prefix="rotest-"); T = pathlib.Path(tmp)


def write_toml(name, hook_port=None, root=None):
    root = root or tmp
    toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
    for key, val in (("repo", f"{root}/inst"), ("store", f"{root}/inst/store"), ("markdown", f"{root}/inst/board.md"), ("brain", f"{root}/brain"),
                     ("state", f"{root}/state"), ("secrets", f"{root}/secrets"), ("project_touch", f"{root}/touch"), ("rules", f"{root}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                     (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'), (r'(?m)^owner = "the owner"', 'owner = "Oliver"')):
        toml, n = re.subn(pat, rep, toml); assert n == 1, pat
    if hook_port:
        toml, n = re.subn(r'(?m)^hook_port = \d+', f'hook_port = {hook_port}', toml); assert n == 1, "hook_port"
    pathlib.Path(root, name).write_text(toml, encoding="utf-8")


write_toml("stackshot.toml")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet", STACKSHOT_READ_ONLY="1")
os.environ.pop("STACKSHOT_URL", None)
# the state directory (and repo, touch) are NOT made: a standby makes no directory, and reading must tolerate their absence
for d in ("inst/store/a", "fleet/a", "brain/projects", "secrets"): (T / d).mkdir(parents=True)
now = time.time()
OWNER = "00000000-0000-4000-8000-000000000001"
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}}))
(T / "inst/store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-here", "agents": {}, "back_agents": {}, "status": "active", "board": [], "board_open": 0}}}))
(T / "inst/store/a/1.json").write_text(json.dumps({"id": "1", "subject": "[home] the standby test item", "description": "- A thing.\n- It lives here.\n- Done when it works.", "status": "open",
                                              "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                              "metadata": {"owner": OWNER, "project": "projects/alpha", "next": "home-here: do the next step"}}))
(T / "inst/store/next-id").write_text("10"); (T / "inst/store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
# the copy job's marker: the newest thing in the store's top level is `.synced-at`, 90 s old; everything else is 10 minutes old
OLD = now - 600
for p in [T / "inst/store", *(T / "inst/store").iterdir(), *(T / "inst/store/a").iterdir()]: os.utime(p, (OLD, OLD))
(T / "inst/store/.synced-at").write_text("")
os.utime(T / "inst/store/.synced-at", (now - 90, now - 90)); os.utime(T / "inst/store", (OLD, OLD))
sys.path.insert(0, STACK); logging.disable(logging.CRITICAL)
fails = []; ran = []


def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))


def tree(*roots):
    """{relative path: sha256 or 'dir'} of everything under the roots (a missing root is {}): what a write would change"""
    out = {}
    for r in roots:
        r = pathlib.Path(r)
        if not r.exists(): out[str(r)] = "absent"; continue
        for p in sorted([r, *r.rglob("*")]):
            out[str(p)] = "dir" if p.is_dir() else hashlib.sha256(p.read_bytes()).hexdigest()
    return out


ROOTS = [T / d for d in ("inst", "state", "brain", "touch", "secrets")]
before = tree(*ROOTS)
threads_before = {t.name for t in threading.enumerate()}

import readonly
import server
atexit.register(lambda: readonly._reload_for_test(False))        # runs before _scratch's clean-up: the backstop must be off when the folders are removed
REFUSAL = "stackshot here is a read-only standby copy (STACKSHOT_READ_ONLY); writes go to the live board."

# ---- 1. the switch
check("the refusal sentence is the one the brief names", readonly.REFUSAL == REFUSAL, readonly.REFUSAL)
check("STACKSHOT_READ_ONLY=1 at start: read-only, read once, in one place", readonly.is_read_only() is True and server._ro is readonly)
for val, want in (("0", False), ("", False), ("true", False), ("yes", False), ("on", False), (" 1 ", False), ("1", True)):
    os.environ["STACKSHOT_READ_ONLY"] = val
    check(f"STACKSHOT_READ_ONLY={val!r}: {'read-only (only the value 1 turns it on)' if want else 'normal'}", readonly._reload_for_test() is want and readonly.is_read_only() is want)
os.environ.pop("STACKSHOT_READ_ONLY", None)
check("unset: normal", readonly._reload_for_test() is False)
os.environ["STACKSHOT_READ_ONLY"] = "1"; readonly._reload_for_test()
check("the server started with no state directory made and no thread of its own", not (T / "state").exists() and {t.name for t in threading.enumerate()} == threads_before,
      sorted({t.name for t in threading.enumerate()} - threads_before))

# ---- 2. the tools
from fastmcp import Client


async def call(name, args):
    async with Client(server.mcp) as c:
        r = await c.session.call_tool(name, args)
        return bool(r.is_error), "".join(getattr(x, "text", "") for x in r.content)


def run(tool, **args): return asyncio.run(call(tool, args))


for tool, args in (("get", {"item_id": "a1"}), ("brief", {}), ("sessions", {}), ("rules", {}), ("anchors", {"project": "projects/alpha"})):
    err, text = run(tool, **args)
    check(f"read tool {tool}: works on the standby", not err and REFUSAL not in text and len(text) > 5, text[:300])
err, text = run("get", item_id="a1")
check("get shows the copy's item", "standby test item" in text, text[:300])
WRITES = (("create", {"subject": "[home] a new one", "description": "- x\n- y\n- Done when z.", "project": "projects/alpha", "sender": "home-here"}),
          ("update", {"item_id": "a1", "sender": "home-here", "next": "home-here: another step"}),
          ("complete", {"item_id": "a1", "outcome": "done", "reason": "x", "sender": "home-here"}),
          ("confirm", {"item_id": "a1", "sender": "home-here"}),
          ("message", {"to": "home-here", "text": "hello", "sender": "home-here"}),
          ("route", {"notice": "0a1b2c", "ruling": "dropped", "reason": "x", "sender": "home-here"}),
          ("bump_versions", {}),
          ("anchors", {"project": "projects/alpha", "add": ["https://github.com/o/r/issues/9"]}),
          ("anchors", {"project": "projects/alpha", "remove": ["https://github.com/o/r/issues/9"]}))
for tool, args in WRITES:
    err, text = run(tool, **args)
    check(f"write tool {tool}{' ' + ','.join(k for k in args if k in ('add', 'remove')) if tool == 'anchors' else ''}: refused with the one sentence", err and REFUSAL in text, text[:300])
check("after every refused write tool the data is byte-for-byte as the fixture left it", tree(*ROOTS) == before, [k for k in tree(*ROOTS) if tree(*ROOTS)[k] != before.get(k)][:5])

# ---- 3. the lowest layers, called directly
import anchors as anc_mod, projects as proj_mod, publish as pub_mod, ghsync


def raises(name, f):
    try:
        f(); check(name, False, "no exception")
    except readonly.ReadOnlyError as e:
        check(name, REFUSAL in str(e), str(e))
    except Exception as e:  # noqa: BLE001
        check(name, False, f"{type(e).__name__}: {e}")


raises("server._save (the item write) raises", lambda: server._save("a1", {"id": "1", "subject": "x"}))
raises("server._next_id (id allocation) raises", lambda: server._next_id())
raises("anchors.save raises", lambda: anc_mod.save({}))
raises("projects.write_atomic raises", lambda: proj_mod.write_atomic(T / "inst/store/projects.json", "{}"))
raises("publish.publish raises", lambda: pub_mod.publish())
raises("ghsync.write_atomic raises", lambda: ghsync.write_atomic(T / "state/x.json", "{}"))
raises("a file opened for writing under the store raises (the audit backstop)", lambda: open(T / "inst/store/new.json", "w"))
raises("a file opened for writing under the state directory raises", lambda: open(T / "state/new.json", "w"))
raises("a rename under the brain raises", lambda: os.rename(T / "brain/projects/alpha.md", T / "brain/projects/beta.md"))
raises("a removal under the store raises", lambda: os.remove(T / "inst/store/next-id"))
raises("a git commit in the store raises before it is spawned", lambda: subprocess.run(["git", "-C", str(T / "inst/store"), "commit", "-m", "x"]))
raises("a git push raises before it is spawned", lambda: subprocess.run(["git", "-C", str(T / "inst/store"), "push"]))
try:
    (T / "scratch-outside.txt").write_text("outside the instance's directories: allowed")
    check("a file outside the instance's directories is not the backstop's business", True)
except Exception as e:  # noqa: BLE001
    check("a file outside the instance's directories is not the backstop's business", False, e)
check("the server's _publish and _publish_now do nothing", server._publish() is None and "read-only" in server._publish_now() and not (T / "state").exists())

# ---- 4. start-up: nothing starts
started = server._start_background()
check("_start_background starts nothing: no name returned, no thread more", started == [] and {t.name for t in threading.enumerate()} == threads_before,
      (started, sorted({t.name for t in threading.enumerate()} - threads_before)))

# ---- 5. the web
from starlette.testclient import TestClient
app = server.mcp.http_app()
post_routes = sorted({(r.path, tuple(sorted(r.methods))) for r in app.routes if hasattr(r, "methods") and hasattr(getattr(r, "endpoint", None), "__wrapped__")})
with TestClient(app, base_url=BOARD) as c:
    home = c.get("/")
    check("the home page is served from the copy, in memory (no <state>/site file), with the banner", home.status_code == 200 and "ro-banner" in home.text
          and "Read-only standby copy" in home.text and "data as of" in home.text and "standby test item" in home.text, (home.status_code, home.text[:200]))
    page = c.get("/items/a1")
    check("an item page is served, with the banner", page.status_code == 200 and "ro-banner" in page.text and "standby test item" in page.text, (page.status_code, page.text[:200]))
    check("the banner is above the page's content, under <body>", re.search(r"<body[^>]*>\s*<div class=\"ro-banner\"", page.text) is not None, page.text[:400])
    check("the home page's render-stamp and board.md are served too", c.get("/render-stamp").status_code == 200 and "standby test item" in c.get("/board.md").text)
    s = c.get("/search?q=standby")
    note = re.search(r'class="se-summary"[^>]*>(.*?)</div>', s.text)
    check("search works on the copy (an index in memory, no file): the item is found", s.status_code == 200 and note is not None and note.group(1).startswith("<b>1 match</b> for") and "standby test item" in s.text.replace("<mark>", "").replace("</mark>", ""), (s.status_code, note and note.group(1)))
    check("search page carries the banner", "ro-banner" in s.text, s.text[s.text.find("<body"):][:300])
    au = c.get("/audits")
    check("the Audits page is served from the copy with the banner (its Audit now buttons post to /audit/now, which the standby refuses 503)", au.status_code == 200 and "ro-banner" in au.text and "<h1>Audits</h1>" in au.text, (au.status_code, au.text[:200]))
    r = c.get("/runners")
    check("the Runners page, which reads GitHub and the other machines, is refused 503 on the standby", r.status_code == 503 and "STACKSHOT_READ_ONLY" in r.text, (r.status_code, r.text[:200]))
    # every custom route, found from the route table itself, with every write method
    check("the sweep finds the custom routes (the wrapper is on all of them)", len(post_routes) >= 20, len(post_routes))
    bad = []
    for path, methods in post_routes:
        url = re.sub(r"\{[^}]*\}", "a1", path)
        for m in ("POST", "PUT", "PATCH", "DELETE"):
            resp = c.request(m, url, data={"token": "x", "choice": "Ship"}, headers={"Origin": BOARD})
            if not (resp.status_code == 503 and REFUSAL in resp.text): bad.append((m, path, resp.status_code, resp.text[:80]))
    check("every custom route answers POST, PUT, PATCH and DELETE 503 with the one sentence (never 405, never its handler)", not bad, bad[:5])
    for path in ("/items/a1/answer", "/items/a1/watch", "/for-you/seen", "/landed/clear", "/landed/unclear", "/landed/seen", "/client/for-you/seen", "/client/items/a1/watch", "/audit/now"):
        resp = c.post(path, data={"token": "x"}, headers={"Origin": BOARD})
        check(f"POST {path}: 503 with the one sentence", resp.status_code == 503 and REFUSAL in resp.text, (resp.status_code, resp.text[:120]))
    resp = c.get("/audit/now")
    check("GET /audit/now (it starts a run) is refused too", resp.status_code == 503 and REFUSAL in resp.text, (resp.status_code, resp.text[:200]))
    # health
    hz = c.get("/healthz")
    lines = hz.text.splitlines()
    check("/healthz: the first line stays ok", hz.status_code == 200 and lines[0] == "ok", hz.text)
    m = re.fullmatch(r"read-only: yes; data age: (\d+)s", lines[-1]) if len(lines) > 1 else None
    check("/healthz: a read-only line with the data age, which `.synced-at` sets (90 s old)", m is not None and 85 <= int(m.group(1)) <= 140, hz.text)
    hj = c.get("/healthz?format=json").json()
    check("/healthz?format=json: ok, read_only true, data_age_s, commit", hj["ok"] is True and hj["read_only"] is True and isinstance(hj["data_age_s"], int) and 85 <= hj["data_age_s"] <= 140
          and "commit" in hj and (hj["commit"] is None or re.fullmatch(r"[0-9a-f]{12}", hj["commit"])), hj)
    check("/healthz.json answers the same", c.get("/healthz.json").json()["read_only"] is True)
    check("the health answers are public (no sign-in)", "healthz" in server._UI_PUBLIC and "healthz.json" in server._UI_PUBLIC)

    # the data age
    check("data age is None for a store that cannot be read", readonly.data_age(T / "no-such-store") is None and "unknown" in readonly.healthz_line(T / "no-such-store"))

    # nothing of the above wrote anything
    after = tree(*ROOTS)
    check("after the whole web sweep every directory is as the fixture left it, and the state directory was never made",
          after == before and not (T / "state").exists(), [k for k in after if after[k] != before.get(k)][:5])


# ---- 7. anchor-hub on the standby
def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); return s.getsockname()[1]


def ask(port, method="GET", path="/", body=None, tries=1):
    last = None
    for _ in range(tries):
        try:
            cx = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            cx.request(method, path, body=body, headers={"Content-Length": str(len(body))} if body else {})
            r = cx.getresponse(); data = r.read().decode(); out = (r.status, data, r.getheader("Retry-After")); cx.close(); return out
        except OSError as e:
            last = e; time.sleep(0.25)
    return (0, f"no answer: {last}", None)


srv = readonly.standby_hook_server(0)
try:
    port = srv.server_address[1]
    for m, path, body in (("GET", "/", None), ("GET", "/anything/at/all", None), ("POST", "/hook/slack", b'{"x": 1}'), ("PUT", "/", b"y"), ("DELETE", "/", None)):
        st, data, ra = ask(port, m, path, body)
        check(f"standby hook server: {m} {path} -> 503 `standby (STACKSHOT_READ_ONLY)`", st == 503 and data == "standby (STACKSHOT_READ_ONLY)" and ra == "60", (st, data, ra))
    st, data, _ = ask(port, "HEAD", "/")
    check("standby hook server: HEAD -> 503 and no body", st == 503 and data == "")
finally:
    srv.shutdown(); srv.server_close()

hub_port = free_port()
write_toml("hub.toml", hub_port)
env = {k: v for k, v in os.environ.items() if k not in ("STACKSHOT_URL",)}
env.update(STACKSHOT_READ_ONLY="1", STACKSHOT_CONFIG=f"{tmp}/hub.toml", HOME=tmp, PYTHONDONTWRITEBYTECODE="1")
hub_before = tree(*ROOTS)
errf = open(T / "hub.err", "w")
proc = subprocess.Popen([sys.executable, os.path.join(STACK, "anchor-hub.py")], env=env, cwd=tmp, stdout=subprocess.DEVNULL, stderr=errf)
try:
    st, data, ra = ask(hub_port, "GET", "/", tries=80)
    check("anchor-hub with the switch on: the hook port answers GET 503 `standby (STACKSHOT_READ_ONLY)`", st == 503 and data == "standby (STACKSHOT_READ_ONLY)", (st, data))
    st2, data2, _ = ask(hub_port, "POST", "/hook/google", b"{}")
    st3, data3, _ = ask(hub_port, "GET", "/health")
    check("anchor-hub standby: a webhook POST and any other path answer 503 too", (st2, data2, st3, data3) == (503, "standby (STACKSHOT_READ_ONLY)", 503, "standby (STACKSHOT_READ_ONLY)"), (st2, data2, st3, data3))
    time.sleep(1.0)
    nthreads = len(os.listdir(f"/proc/{proc.pid}/task"))
    check("anchor-hub standby: no receiver or poller thread (main, the server and one request thread at most)", nthreads <= 4, nthreads)
    check("anchor-hub standby is still running (it holds the port until stopped)", proc.poll() is None)
    errf.flush()
    err_text = (T / "hub.err").read_text()
    check("anchor-hub standby says so on stderr, and starts no receiver", "read-only standby" in err_text and "receiver slack" not in err_text and "receiver google" not in err_text
          and "Traceback" not in err_text, err_text[:600])
    check("anchor-hub standby wrote no state: the state directory (the hub's status, queues and cursors) was never made, nothing of the board data changed",
          not (T / "state").exists() and tree(*ROOTS) == hub_before, [k for k in tree(*ROOTS) if tree(*ROOTS)[k] != hub_before.get(k)][:5])
finally:
    proc.terminate()
    try: proc.wait(timeout=15)
    except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=10)
    errf.close()
check("anchor-hub standby stops cleanly on SIGTERM", proc.returncode == 0, proc.returncode)

# the hub's own guards, behind anchor-hub.py's early exit: a delivery, a status write and a receiver start raise on the standby
import anchorhub.core as hub_core
raises("Hub.deliver raises on the standby", lambda: hub_core.Hub.deliver(None, "github:o/r#1", "home-here", "text"))
raises("Hub.write_status raises on the standby", lambda: hub_core.Hub.write_status(None))
raises("start_receiver raises on the standby", lambda: hub_core.start_receiver(None, "slack", lambda *_: None, lambda: True))
check("…and none of them wrote anything", not (T / "state").exists() and tree(*ROOTS) == before)

# ---- end
final = tree(*ROOTS)
check("at the very end every directory of the instance is what the fixture left", final == before and not (T / "state").exists(), [k for k in final if final[k] != before.get(k)][:5])
# ---- 6. the live instance (switch off) is as it was (last: the live instance may make its own directories)
readonly._reload_for_test(False)
with TestClient(app, base_url=BOARD) as c:
    hz = c.get("/healthz")
    check("normal mode: /healthz is plain `ok` (no read-only line)", hz.status_code == 200 and hz.text.splitlines()[0] == "ok" and "read-only" not in hz.text, hz.text)
    hj = c.get("/healthz?format=json").json()
    check("normal mode: /healthz?format=json says read_only false", hj["ok"] is True and hj["read_only"] is False, hj)
    resp = c.post("/items/a1/answer", data={"choice": "Ship"}, headers={"Origin": BOARD})
    check("normal mode: a POST reaches its handler (not the standby's 503)", REFUSAL not in resp.text and resp.status_code != 503, (resp.status_code, resp.text[:200]))
    pg = c.get("/items/a1")
    check("normal mode: a page carries no banner", pg.status_code == 200 and "ro-banner" not in pg.text)
err, text = run("anchors", project="projects/alpha")
check("normal mode: the tool middleware lets a call through (a listing works)", not err and REFUSAL not in text, text[:200])

# ---- 6b. a normal start, in a process of its own: STACKSHOT_READ_ONLY unset, so nothing of the switch was ever applied (the flip above reuses a read-only start)
import ast, shutil
N = T / "normal"
for d in ("fleet", "brain", "secrets"): (N / d).mkdir(parents=True, exist_ok=True)
shutil.copytree(T / "inst", N / "inst"); shutil.copytree(T / "fleet", N / "fleet", dirs_exist_ok=True); shutil.copytree(T / "brain", N / "brain", dirs_exist_ok=True)
shutil.copy(T / "RULES.md", N / "RULES.md")
write_toml("stackshot.toml", root=str(N))
src = pathlib.Path(STACK, "server.py").read_text(encoding="utf-8")
declared = {}
for path, m in re.findall(r'(?m)^@mcp\.custom_route\("([^"]+)",\s*methods=(\[[^\]]*\]|\w+)\)', src):
    if not m.startswith("["):
        m = re.search(rf'(?m)^{m} = (\[.*\])\s*$', src).group(1)
    declared.setdefault(path, set()).update(ast.literal_eval(m))
expected = {k: sorted(v | ({"HEAD"} if "GET" in v else set())) for k, v in declared.items()}      # Starlette adds HEAD to a GET route
cenv = {k: v for k, v in os.environ.items() if k not in ("STACKSHOT_READ_ONLY", "STACKSHOT_URL")}
cenv.update(HOME=str(N), PYTHONDONTWRITEBYTECODE="1")
cerr = open(T / "normal.err", "w")
cp = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--normal-child", str(N)], env=cenv, cwd=str(N), stdout=subprocess.PIPE, stderr=cerr, text=True)
try:
    cout, _ = cp.communicate(timeout=240)
except subprocess.TimeoutExpired:
    cp.kill(); cout, _ = cp.communicate()
finally:
    cerr.close()
try: nm = json.loads(cout.strip().splitlines()[-1])
except Exception: nm = None
check("a normal start in its own process runs (exit 0, one JSON line)", cp.returncode == 0 and nm is not None, (cp.returncode, (T / "normal.err").read_text()[-600:]))
if nm:
    check("a normal start: the switch is off and the file-write backstop was never installed (readonly._HOOKED is False)", nm["ro"] is False and nm["hooked"] is False, (nm["ro"], nm["hooked"]))
    check("the sweep reads the declared methods of at least 20 routes from the decorators", len(declared) >= 20, len(declared))
    check("a normal start: every custom route's methods are what its decorator declared (nothing widened)", nm["routes"] == expected,
          {k: (nm["routes"].get(k), expected.get(k)) for k in set(nm["routes"]) | set(expected) if nm["routes"].get(k) != expected.get(k)})
    check("a normal start: `/` is GET and HEAD only, `/items/{key}/answer` is POST only", nm["routes"].get("/") == ["GET", "HEAD"] and nm["routes"].get("/items/{key}/answer") == ["POST"],
          (nm["routes"].get("/"), nm["routes"].get("/items/{key}/answer")))
    check("a normal start: `/` returns the home page with no banner", nm["home"][0] == 200 and "standby test item" in nm["home"][1] and "ro-banner" not in nm["home"][1], nm["home"][0])
    check("a normal start: /healthz is plain `ok` and the json says read_only false", nm["healthz"].strip() == "ok" and nm["json"].get("read_only") is False, (nm["healthz"], nm["json"]))
    check("a normal start: an item page has no banner and a POST reaches its handler (not 503)", nm["item"] == [200, False] and nm["post"] != 503, (nm["item"], nm["post"]))
readonly._reload_for_test(False)
print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
