"""Scenario test for the puller's mirror of the server's state files (puller 12, `[client] mirror_server_state`): fixture data, a throwaway HTTP server on
the loopback that answers like the client API (the real `get roles` and `get state-files` reads of the service), no live store, no network.

Covers: the server's `state-files` read (the files as published, a fleet letter only when both its files read, a missing file as null, the server's host, the read
is a client read); the mirror (roles.json as the server's own text, projects.json, the fleet view, versions.json and the advertised commit written under the names and
shapes the readers open, no temporary file left); off by default (nothing fetched, nothing written); roles.json rewritten at every pass, so its age is read fresh; a fetch that
fails (HTTP error, not JSON, not an object) or answers empty or misshapen leaves the old file, each file on its own, and is logged once until it works again; the server's own box
(its host in the answer, or a loopback address) is never written to, and a failover standby that holds a copy of the server's secrets file mirrors all the same; a file that reads the same is not rewritten (roles.json is);
a letter or a commit with a trailing newline is refused; the write is a temporary file renamed over the file (a failing rename leaves the old file and no
temporary); a letter that left the server's view goes after two fetches in a row without it (one torn read keeps it), each folder on its own (an error on one does not stop the rest, a foreign file keeps its folder), except when the view came empty; a letter that is a path is ignored; the minimum gap between two passes; a failure inside
the mirror never reaches the poll loop; the --once branch mirrors after a poll the server answered, when the setting is on, and writes nothing with --dry-run; a plain file where a letter folder is expected does not stop the pass; an empty view clears the removal counters.

    tests/run-suite puller_mirror        → exit 0 / 1"""
import contextlib, http.server, io, json, os, re, socket, sys, threading, pathlib, logging, urllib.parse
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="mirrortest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
assert 'session_links = ""' in toml                  # no session links store of the host
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^mirror_server_state = false\b', 'mirror_server_state = true', toml); assert n == 1   # the example's default is off; this box asks for it
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off")
for k in ("STACKSHOT_FLEET_DIR", "STACKSHOT_URL", "BOARD_MCP_AUTH"): os.environ.pop(k, None)
for d in ("store/a", "state/site", "state/clients/fleet/a", "state/clients/fleet/b", "state/clients/fleet/c", "secrets", "brain/projects", "agent"): (T / d).mkdir(parents=True)
(T / "store/projects.json").write_text(json.dumps({"pages": {}})); (T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
(T / "secrets/client.token").write_text("tok-for-the-test\n")
logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))
SHA = "0123456789abcdef0123456789abcdef01234567"
S, A = T / "state", T / "agent"                      # the server's state folder (a fixture) and the client box's
def wr(p, v): p.parent.mkdir(parents=True, exist_ok=True); p.write_text(v if isinstance(v, str) else json.dumps(v, indent=1, sort_keys=True), encoding="utf-8")
rd = lambda p: json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
ROLES = {"generated": "2030-01-01T00:00:00Z", "sessions": {"box-main": {"role": "front", "project": "projects/alpha", "live": True}}}
PROJECTS = {"schema": 1, "generated": "2030-01-01T00:00:00Z", "projects": {"p-e1": {"id": "p-e1", "key": "projects/alpha", "keeper": "box-main", "agents": {}}}, "by_key": {"projects/alpha": "p-e1"}}
VERSIONS = {"generated": "2030-01-01T00:00:00Z", "packages": [{"name": "claude", "latest": "9.9.9"}]}
MA = {"letter": "a", "fleet": "box-far", "claude": "9.9.9", "checked": "2030-01-01T00:00:00Z"}
SA = {"cse_e1": {"name": "box-main", "seen": "2030-01-01T00:00:00Z", "machine": "a", "status": "idle", "url": ""}}
def fill_server():
    wr(S / "roles.json", ROLES); wr(S / "projects.json", PROJECTS); wr(S / "site/versions.json", VERSIONS); wr(S / "clients/advertised-commit", SHA + "\n")
    wr(S / "clients/fleet/a/machine.json", MA); wr(S / "clients/fleet/a/sessions.json", SA)
    wr(S / "clients/fleet/b/machine.json", {**MA, "letter": "b", "fleet": "box-near"}); wr(S / "clients/fleet/b/sessions.json", {})
    wr(S / "clients/fleet/c/machine.json", {**MA, "letter": "c"}); wr(S / "clients/fleet/c/sessions.json", "{ torn")      # a letter whose sessions.json does not read: left out, never half sent
fill_server()

from stackshot.fleet import client, puller
from stackshot.service import client_reads as svc

# ---- 1. the server's read
st, ct, body = svc._client_get("state-files", {}); sf = json.loads(body)
check("state-files: a client read, answered 200 JSON", st == 200 and ct == "application/json" and "state-files" in client.READS, (st, ct))
check("state-files: the server's own host, for the box that carries the server to know itself", sf["host"] == socket.gethostname(), sf.get("host"))
check("state-files: projects.json, versions.json and the commit as published", sf["projects"] == PROJECTS and sf["versions"] == VERSIONS and sf["advertised_commit"] == SHA, sf)
check("state-files: the fleet view, a letter only when both its files read", sorted(sf["fleet"]) == ["a", "b"] and sf["fleet"]["a"] == {"machine": MA, "sessions": SA} and sf["fleet"]["b"]["sessions"] == {}, sf["fleet"].keys())
(S / "site/versions.json").rename(S / "site/versions.off"); (S / "clients/advertised-commit").unlink(); (S / "projects.json").write_text("{ torn")
sf2 = json.loads(svc._client_get("state-files", {})[2])
check("state-files: a file that is missing or torn is null (an empty string for the commit), not an empty stand-in", sf2["versions"] is None and sf2["advertised_commit"] == "" and sf2["projects"] is None, sf2)
(S / "site/versions.off").rename(S / "site/versions.json"); fill_server()
check("get state-files is listed in the client's usage", "roles | state-files" in pathlib.Path(STACK, "stackshot/fleet/client.py").read_text(encoding="utf-8"))

# ---- the throwaway server: the real reads of the service behind a loopback port, or an answer the test sets
OVER = {}; HITS = []
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        u = urllib.parse.urlsplit(self.path); what = u.path.rsplit("/", 1)[-1]
        HITS.append((what, self.headers.get("Authorization")))
        if what in OVER:
            o = OVER[what]
            st, ctype, body = o() if callable(o) else o
        else:
            st, ctype, body = svc._client_get(what, dict(urllib.parse.parse_qsl(u.query)))
        b = body.encode(); self.send_response(st); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["STACKSHOT_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
REAL_LOOPBACK = puller._loopback
puller._loopback = lambda url: False                  # the throwaway server is on the loopback, so the test says this address is a far one; section 7 puts the real check back
puller._own_host = lambda: "agents-box"               # not the host the fixture server answers with
def run(root=A):
    """One pass of the mirror as the loop makes it (the gap and the logged-once notes reset first, except where a check keeps them) → (answer, stdout, stderr)."""
    puller._MIRROR["at"] = 0.0
    o, e = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(o), contextlib.redirect_stderr(e):
        r = puller.mirror_state(root)
    return r, o.getvalue(), e.getvalue()
def fresh():
    puller._MIRROR.update(at=0.0, bad=set(), note=set(), gone={}); OVER.clear(); HITS.clear()
FILES = ["roles.json", "projects.json", "site/versions.json", "clients/advertised-commit", "clients/fleet/a/machine.json", "clients/fleet/a/sessions.json", "clients/fleet/b/machine.json", "clients/fleet/b/sessions.json"]
def snapshot(root=A): return {f: (pathlib.Path(root) / f).read_text(encoding="utf-8") if (pathlib.Path(root) / f).exists() else None for f in FILES}
try:
    # ---- 2. the mirror writes what the readers open
    fresh(); r, out, err = run()
    check("the mirror: one pass answers done", r == "done", (r, out, err))
    check("the mirror: roles.json is the server's own text, and every request carried the machine token", (A / "roles.json").read_text() == (S / "roles.json").read_text() and all(a == "Bearer tok-for-the-test" for _, a in HITS) and {w for w, _ in HITS} == {"state-files", "roles"}, HITS)
    check("the mirror: projects.json, versions.json and the advertised commit", rd(A / "projects.json") == PROJECTS and rd(A / "site/versions.json") == VERSIONS and (A / "clients/advertised-commit").read_text() == SHA + "\n")
    check("the mirror: the fleet view, both files of each letter and none of a letter that did not read", rd(A / "clients/fleet/a/machine.json") == MA and rd(A / "clients/fleet/a/sessions.json") == SA and rd(A / "clients/fleet/b/sessions.json") == {} and not (A / "clients/fleet/c").exists())
    left = [str(p) for p in A.rglob("*") if p.is_file() and p.name.endswith(".tmp")]
    check("the mirror: no temporary file is left", not left, left)
    rj = json.loads((A / "roles.json").read_text())
    check("the mirror: roles.json reads as a reader reads it (generated, sessions)", isinstance(rj["sessions"], dict) and rj["generated"] == ROLES["generated"] and "box-main" in rj["sessions"])
    check("the mirror: a quiet pass logs nothing", err == "" and out == "", (out, err))

    # ---- 3. off by default
    fresh(); import shutil; shutil.rmtree(A); A.mkdir()
    puller._cfg.CFG["client"]["mirror_server_state"] = False
    r, out, err = run(); on = puller._cfg.CFG["client"]; on["mirror_server_state"] = True
    check("off: the answer says so, nothing is fetched and nothing is written", r == "off" and not HITS and not any(A.iterdir()), (r, HITS))
    saved = on.pop("mirror_server_state"); r, *_ = run(); on["mirror_server_state"] = saved
    check("off: a config with no such key is off (the default)", r == "off" and not HITS, (r, HITS))
    check("off: the example config ships it as false", re.search(r"(?m)^mirror_server_state = false\b", pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")) is not None)

    # ---- 4. the age a reader checks: roles.json is written at every pass
    fresh(); run(); old = A / "roles.json"; os.utime(old, (1_000_000, 1_000_000))
    r, *_ = run()
    check("roles.json is rewritten at every pass, though nothing in it changed (its mtime is fresh)", r == "done" and old.stat().st_mtime > 1_000_000 + 3600, old.stat().st_mtime)
    wr(S / "roles.json", {**ROLES, "generated": "2030-01-01T00:05:00Z"}); run()
    check("roles.json carries the server's own `generated`, not the time of the copy", rd(old)["generated"] == "2030-01-01T00:05:00Z"); wr(S / "roles.json", ROLES)

    # ---- 5. a read that fails leaves the old files, and says so once
    fresh(); run(); before = snapshot()
    OVER["state-files"] = (500, "text/plain", "boom")
    r, out, err = run()
    check("a failing state-files read: the answer is failed, no file changes", r == "failed" and snapshot() == before, (r, err))
    check("a failing read is logged once, naming the source and that the copy is kept", err.count("state-files not fetched") == 1 and "kept" in err, err)
    r, out, err = run()
    check("the same failure on the next pass is not logged again", r == "failed" and err == "" and snapshot() == before, err)
    OVER.clear(); r, out, err = run()
    check("the read works again: the files are written and one line says so", r == "done" and "state-files fetched again" in out and err == "", (r, out, err))
    for bad_answer, why in (((200, "text/plain", "not json"), "not JSON"), ((200, "application/json", "[1, 2]"), "not an object"), ((0, "", ""), "")):
        fresh(); run(); before = snapshot()
        if bad_answer[0] == 0: srv_port = os.environ["STACKSHOT_URL"]; os.environ["STACKSHOT_URL"] = "http://127.0.0.1:1"; r, out, err = run(); os.environ["STACKSHOT_URL"] = srv_port
        else: OVER["state-files"] = bad_answer; r, out, err = run()
        check(f"state-files answered {bad_answer[:1] + (bad_answer[2][:12],)}: the old files stay", r == "failed" and snapshot() == before and "kept" in err, (r, err))
    fresh(); run(); before = snapshot(); OVER["roles"] = (503, "text/plain", "no roles yet"); wr(S / "projects.json", {**PROJECTS, "generated": "2030-01-01T00:09:00Z"})
    r, out, err = run()
    check("roles failing alone: roles.json stays, the other files are brought up to date", r == "failed" and (A / "roles.json").read_text() == before["roles.json"] and rd(A / "projects.json")["generated"] == "2030-01-01T00:09:00Z" and err.count("roles not fetched") == 1, (r, err))
    wr(S / "projects.json", PROJECTS)

    # ---- 6. an answer that is empty or misshapen is not written
    fresh(); run(); before = snapshot()
    OVER["roles"] = (200, "application/json", json.dumps({"generated": "2030-01-01T00:00:00Z", "sessions": {}}))
    OVER["state-files"] = (200, "application/json", json.dumps({"host": "far-server", "projects": {"schema": 1, "generated": "x", "projects": {}}, "versions": {}, "advertised_commit": "main",
                                                                "fleet": {"a": {"machine": {}, "sessions": {}}, "b": {"machine": {"letter": "b"}, "sessions": []}, "../x": {"machine": {"a": 1}, "sessions": {}}}}))
    r, out, err = run()
    check("empty or misshapen: roles.json, projects.json, versions.json, the commit and the fleet files all stay", snapshot() == before, [k for k, v in snapshot().items() if v != before[k]])
    check("empty or misshapen: a letter that is a path is never written", not (A.parent / "x").exists() and not (A / "clients/fleet/../x").resolve().exists() and sorted(p.name for p in (A / "clients/fleet").iterdir()) == ["a", "b"], os.listdir(A / "clients/fleet"))
    check("empty or misshapen roles are logged as a failure of roles", "roles not fetched" in err, err)
    fresh(); run(); OVER["state-files"] = (200, "application/json", json.dumps({"projects": PROJECTS})); before = snapshot(); wr(S / "roles.json", {**ROLES, "generated": "2030-01-01T00:07:00Z"}); n = len(HITS)
    r, out, err = run()
    check("an answer that names no host is not trusted: nothing is written, roles not even asked for", r == "failed" and snapshot() == before and [w for w, _ in HITS[n:]] == ["state-files"] and "no host" in err, (r, err, HITS[n:]))
    wr(S / "roles.json", ROLES)

    # ---- 7. the box that is the server
    fresh(); shutil.rmtree(A); A.mkdir(); wr(A / "roles.json", {"generated": "2001-01-01T00:00:00Z", "sessions": {"mine": {"role": "front"}}}); before = snapshot()
    puller._own_host = lambda: socket.gethostname().upper() + ".example.net"          # the same host, the domain and the case apart
    r, out, err = run()
    check("this box is the server (its host in the answer): nothing written, roles not fetched, said once", r == "local" and snapshot() == before and {w for w, _ in HITS} == {"state-files"} and err.count("this box is the server") == 1, (r, HITS, err))
    r, out, err = run()
    check("the same note is not repeated on the next pass", r == "local" and err == "")
    puller._own_host = lambda: "agents-box"; puller._loopback = REAL_LOOPBACK
    fresh()
    r, out, err = run()
    check("a loopback server address: nothing fetched, nothing written", r == "local" and not HITS and snapshot() == before and "own" in err, (r, HITS, err))
    for u, want in (("http://localhost:8020", True), ("http://[::1]:8020", True), ("http://127.0.0.2:8020", True), ("https://stack.example.com", False), ("http://198.51.100.9:8020", False)):
        check(f"the loopback test: {u}", puller._loopback(u) is want)
    puller._loopback = lambda url: False

    # ---- 8. the write is a rename
    fresh(); shutil.rmtree(A); A.mkdir(); run(); before = snapshot(); real = os.replace; seen = []
    wr(S / "projects.json", {**PROJECTS, "generated": "2030-01-01T00:11:00Z"})
    def spy(src, dst):
        seen.append((os.path.dirname(src) == os.path.dirname(dst), pathlib.Path(dst).read_text(encoding="utf-8") if os.path.exists(dst) else None, json.loads(pathlib.Path(src).read_text(encoding="utf-8")) if str(dst).endswith("projects.json") else None))
        return real(src, dst)
    puller.os.replace = spy
    try: run()
    finally: puller.os.replace = real
    pj = [x for x in seen if x[2] is not None]
    check("the write: a temporary file in the same folder, whole when it is renamed, the old file whole until then (only the changed file and roles.json are written)", len(seen) == 2 and all(x[0] for x in seen) and pj and pj[0][2]["generated"] == "2030-01-01T00:11:00Z" and json.loads(pj[0][1])["generated"] == "2030-01-01T00:00:00Z", seen[:2])
    wr(S / "projects.json", {**PROJECTS, "generated": "2030-01-01T00:12:00Z"}); before = snapshot()
    def boom(src, dst):
        if str(dst).endswith("projects.json"): raise OSError(28, "No space left on device")
        return real(src, dst)
    puller.os.replace = boom
    try: r, out, err = run()
    finally: puller.os.replace = real
    check("a rename that fails: the old file stays whole, no temporary is left, the others are still written, said once", r == "failed" and snapshot()["projects.json"] == before["projects.json"] and not list(A.rglob("*.tmp")) and err.count("projects.json not fetched") == 1 and "No space" in err, (r, err))
    wr(S / "projects.json", PROJECTS)

    # ---- 9. a letter that left the view
    fresh(); run(); wr(A / "clients/fleet/z/machine.json", MA); wr(A / "clients/fleet/z/sessions.json", {}); wr(A / "clients/fleet/zz/machine.json", MA)
    run()
    check("a one-letter machine missing from one fetch only is kept (one pass can be a torn read on the server)", (A / "clients/fleet/z/machine.json").exists())
    run()
    check("a one-letter machine missing from two fetches in a row is removed, with its files", not (A / "clients/fleet/z").exists() and (A / "clients/fleet/a/machine.json").exists())
    check("a folder that is not a letter is left alone", (A / "clients/fleet/zz/machine.json").exists())
    fresh(); run(); wr(S / "clients/fleet/c/sessions.json", {}); run()                 # c is whole now: it is mirrored
    check("two-pass removal: the letter is mirrored while it reads", (A / "clients/fleet/c/machine.json").exists())
    wr(S / "clients/fleet/c/sessions.json", "{ torn"); run()
    check("two-pass removal: a torn read on the server for one pass leaves the local folder", (A / "clients/fleet/c/machine.json").exists())
    wr(S / "clients/fleet/c/sessions.json", {}); run(); wr(S / "clients/fleet/c/sessions.json", "{ torn"); run()
    check("two-pass removal: a read that came back in between starts the count again", (A / "clients/fleet/c/machine.json").exists() and puller._MIRROR["gone"] == {"c": 1}, puller._MIRROR["gone"])
    run()
    check("two-pass removal: torn in two fetches in a row, the folder goes", not (A / "clients/fleet/c").exists() and puller._MIRROR["gone"] == {}, puller._MIRROR["gone"])
    wr(S / "clients/fleet/c/sessions.json", "{ torn")
    # the sweep goes on after an error, and a leftover that is no mirrored file keeps its folder
    fresh(); run()
    for L in "yzw": wr(A / "clients/fleet" / L / "machine.json", MA); wr(A / "clients/fleet" / L / "sessions.json", {})
    (A / "clients/fleet/w/notes.txt").write_text("kept"); (A / "clients/fleet/z/.sessions.json.4242.tmp").write_text("{")
    run(); real_unlink = os.unlink
    def flaky(path, *a, **k):
        if os.sep + "y" + os.sep in str(path): raise OSError(13, "Permission denied")
        return real_unlink(path, *a, **k)
    puller.os.unlink = flaky
    try: r, out, err = run(); r2, out2, err2 = run()
    finally: puller.os.unlink = real_unlink
    check("the sweep goes on after an OSError on one folder: the others are removed, the failing one stays, said once", (A / "clients/fleet/y/machine.json").exists() and not (A / "clients/fleet/z").exists() and err.count("clients/fleet/y not removed") == 1 and "Permission denied" in err, (err, os.listdir(A / "clients/fleet")))
    check("a leftover file that is no mirrored file keeps its folder, the mirrored files in it go", (A / "clients/fleet/w/notes.txt").exists() and not (A / "clients/fleet/w/machine.json").exists() and (A / "clients/fleet/a/machine.json").exists(), os.listdir(A / "clients/fleet/w"))
    check("the same failure on the next pass is not logged again", err2 == "" and (A / "clients/fleet/y/machine.json").exists(), err2)
    fresh(); run(); before = snapshot()
    for L in "abc": shutil.rmtree(S / "clients/fleet" / L)
    r, out, err = run(); r, out, err = run()
    check("a view that came empty removes nothing, however many passes", snapshot() == before and (A / "clients/fleet/a").exists(), (r, err))
    for L, doc in (("a", (MA, SA)), ("b", ({**MA, "letter": "b", "fleet": "box-near"}, {})), ("c", ({**MA, "letter": "c"}, "{ torn"))): wr(S / "clients/fleet" / L / "machine.json", doc[0]); wr(S / "clients/fleet" / L / "sessions.json", doc[1])

    # ---- 9a. a file that reads the same is not rewritten
    fresh(); shutil.rmtree(A); A.mkdir(); run()
    for f in FILES: os.utime(A / f, (1_000_000, 1_000_000))
    r, *_ = run()
    fresh_roles = (A / "roles.json").stat().st_mtime > 1_000_000 + 3600
    kept = [f for f in FILES if f != "roles.json" and (A / f).stat().st_mtime == 1_000_000]
    check("an unchanged file is not rewritten (its mtime stays), roles.json is", r == "done" and fresh_roles and len(kept) == len(FILES) - 1, (r, kept))
    wr(S / "projects.json", {**PROJECTS, "generated": "2030-01-01T00:13:00Z"}); run()
    check("a file whose text changed is rewritten, the unchanged ones still are not", rd(A / "projects.json")["generated"] == "2030-01-01T00:13:00Z" and (A / "site/versions.json").stat().st_mtime == 1_000_000)
    wr(S / "projects.json", PROJECTS)

    # ---- 9b. a letter or a commit with a trailing newline is no letter, no commit
    fresh(); shutil.rmtree(A); A.mkdir(); run(); before = snapshot()
    good = json.loads(svc._client_get("state-files", {})[2])
    good["fleet"]["a\n"] = good["fleet"]["a"]; good["advertised_commit"] = "f" * 40 + "\n";
    OVER["state-files"] = (200, "application/json", json.dumps(good))
    r, out, err = run()
    check("a letter with a trailing newline is ignored (no folder for it)", sorted(p.name for p in (A / "clients/fleet").iterdir()) == ["a", "b"], os.listdir(A / "clients/fleet"))
    check("a commit with a trailing newline is not written (the old one stays)", (A / "clients/advertised-commit").read_text() == SHA + "\n", (A / "clients/advertised-commit").read_text())

    # ---- 9c. a copy of the server's secrets file on the box decides nothing: a failover standby keeps one and still mirrors
    fresh(); shutil.rmtree(A); A.mkdir(); wr(A / "roles.json", {"generated": "2001-01-01T00:00:00Z", "sessions": {"mine": {"role": "front"}}})
    check("the secrets file the test plants is the one the client names", client.CLIENTS == str(T / "secrets/clients.json"), client.CLIENTS)
    (T / "secrets/clients.json").write_text("{}")
    try:
        r, out, err = run()
        check("a copy of clients.json, a server address that is not loopback and an answer naming another host: the box mirrors", r == "done" and rd(A / "roles.json") == ROLES and rd(A / "projects.json") == PROJECTS and (A / "clients/fleet/a/machine.json").exists(), (r, err))
        check("a copy of clients.json says nothing about a local server", "secrets file" not in err and "secrets file" not in out, (out, err))
        before = snapshot(); fresh(); puller._own_host = lambda: socket.gethostname().upper() + ".example.net"
        r, out, err = run()
        check("a copy of clients.json and the answer names this box's own host: nothing written", r == "local" and snapshot() == before and err.count("this box is the server") == 1, (r, err))
        puller._own_host = lambda: "agents-box"; puller._loopback = REAL_LOOPBACK; fresh()
        r, out, err = run()
        check("a copy of clients.json and a loopback server address: nothing fetched, nothing written", r == "local" and not HITS and snapshot() == before, (r, HITS, err))
    finally:
        (T / "secrets/clients.json").unlink(); puller._own_host = lambda: "agents-box"; puller._loopback = lambda url: False
    fresh(); r, *_ = run()
    check("without that file the same box mirrors", r == "done" and rd(A / "roles.json") == ROLES)

    # ---- 9d. a plain file where a letter folder is expected: skipped, the pass goes on, no traceback
    fresh(); shutil.rmtree(A); A.mkdir(); run(); (A / "clients/fleet/q").write_text("not a folder"); (A / "clients/fleet/qq").write_text("x")
    for n in (1, 2, 3):
        r, out, err = run()
        check(f"a plain file among the letter folders (pass {n}): the pass is done, nothing said, the file is left", r == "done" and err == "" and (A / "clients/fleet/q").read_text() == "not a folder" and (A / "clients/fleet/a/machine.json").exists(), (r, err))
    check("a plain file among the letter folders is not counted for removal", "q" not in puller._MIRROR["gone"] and "qq" not in puller._MIRROR["gone"], puller._MIRROR["gone"])
    shutil.rmtree(A / "clients/fleet/b"); (A / "clients/fleet/b").write_text("a file where the view has a letter")
    r, out, err = run(); r2, out2, err2 = run()
    check("a plain file where a letter of the view belongs: that letter fails, logged once, the other files are still written, nothing raised", r == "failed" and err.count("clients/fleet/b/") >= 1 and err2 == "" and rd(A / "roles.json") == ROLES and (A / "clients/fleet/a/machine.json").exists(), (r, err, err2))
    (A / "clients/fleet/b").unlink()

    # ---- 9e. an empty view clears the removal counters, so a later pass does not take it as the second miss
    fresh(); shutil.rmtree(A); A.mkdir(); run(); wr(A / "clients/fleet/z/machine.json", MA); run()
    check("a letter missing from one fetch is counted once", puller._MIRROR["gone"] == {"z": 1}, puller._MIRROR["gone"])
    for L in "abc": shutil.rmtree(S / "clients/fleet" / L)
    try:
        run()
        check("a view that came empty clears the counters and removes nothing", puller._MIRROR["gone"] == {} and (A / "clients/fleet/z/machine.json").exists(), puller._MIRROR["gone"])
    finally:
        for L, doc in (("a", (MA, SA)), ("b", ({**MA, "letter": "b", "fleet": "box-near"}, {})), ("c", ({**MA, "letter": "c"}, "{ torn"))): wr(S / "clients/fleet" / L / "machine.json", doc[0]); wr(S / "clients/fleet" / L / "sessions.json", doc[1])
    run()
    check("after the empty view the count starts again from one (the letter is not removed at the first miss)", puller._MIRROR["gone"] == {"z": 1} and (A / "clients/fleet/z/machine.json").exists(), puller._MIRROR["gone"])

    # ---- 10. the gap, the default folder, the loop
    fresh(); run(); n = len(HITS); puller._MIRROR["at"] = 0.0; import time
    o, e = io.StringIO(), io.StringIO()
    r1 = puller.mirror_state(A, now=1000.0); r2 = puller.mirror_state(A, now=1000.0 + puller.MIRROR_MIN_GAP - 1); r3 = puller.mirror_state(A, now=1000.0 + puller.MIRROR_MIN_GAP + 1)
    check("two passes closer than MIRROR_MIN_GAP: the second waits, no request is made for it", (r1, r2, r3) == ("done", "wait", "done") and len(HITS) - n == 4, (r1, r2, r3, len(HITS) - n))
    fresh(); shutil.rmtree(A); A.mkdir(); real_state = puller._cfg.state; puller._cfg.state = lambda *p: A.joinpath(*p)
    try: r, *_ = run(None)
    finally: puller._cfg.state = real_state
    check("with no folder given, the box's own [paths] state is the one written", r == "done" and (A / "roles.json").exists() and (A / "clients/fleet/a/machine.json").exists())
    real_ms = puller.mirror_state
    def raiser(*a, **k): raise RuntimeError("disk on fire")
    puller.mirror_state = raiser; fresh(); o, e = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(o), contextlib.redirect_stderr(e): r = puller._mirror_safe()
    finally: puller.mirror_state = real_ms
    check("a failure inside the mirror never reaches the poll loop (logged, the pass fails)", r == "failed" and "disk on fire" in e.getvalue())
    src = pathlib.Path(STACK, "stackshot/fleet/puller.py").read_text(encoding="utf-8")
    check("the loop mirrors after every poll the server answered", re.search(r"if rc != 2:\n\s+_mirror_safe\(\)", src) is not None)
    # the --once branch mirrors after a poll the server answered, when the setting is on
    calls = []; real_once, real_safe, real_cfg_state = puller.once, puller._mirror_safe, puller._cfg.state
    puller._mirror_safe = lambda: calls.append(1) or "done"
    try:
        for rc, want in ((0, 1), (1, 1), (2, 0)):
            calls.clear(); puller.once = lambda *a, rc=rc, **k: rc
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()): got = puller.main(["puller.py", "--once", "--registry", str(T / "reg")])
            check(f"--once: a poll that returned {rc} {'mirrors' if want else 'does not mirror'}", got == rc and len(calls) == want, (got, calls))
        puller._mirror_safe = real_safe; puller._cfg.state = lambda *p: A.joinpath(*p); puller.once = lambda *a, **k: 0
        fresh(); shutil.rmtree(A); A.mkdir()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()): puller.main(["puller.py", "--once", "--registry", str(T / "reg")])
        check("--once with the setting on: the files of the server are written to the box's state folder", (A / "roles.json").exists() and (A / "clients/fleet/a/machine.json").exists())
        fresh(); shutil.rmtree(A); A.mkdir(); puller._cfg.CFG["client"]["mirror_server_state"] = False
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()): puller.main(["puller.py", "--once", "--registry", str(T / "reg")])
        puller._cfg.CFG["client"]["mirror_server_state"] = True
        check("--once with the setting off: nothing is fetched, nothing written", not HITS and not any(A.iterdir()), HITS)
        fresh(); shutil.rmtree(A); A.mkdir(); real_keep, real_sess = puller.keep_current, puller.sessions
        puller.keep_current = lambda *a, **k: 0; puller.sessions = lambda *a, **k: []
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()): got = puller.main(["puller.py", "--once", "--dry-run", "--registry", str(T / "reg")])
        finally: puller.keep_current, puller.sessions = real_keep, real_sess
        check("--once with --dry-run: nothing is fetched and no file is written, though the setting is on", got == 0 and not HITS and not any(A.iterdir()), (got, HITS))
    finally: puller.once, puller._mirror_safe, puller._cfg.state = real_once, real_safe, real_cfg_state
    check("the puller's version moved, so running pullers reload", int(puller.VERSION) >= 12, puller.VERSION)
finally:
    srv.shutdown(); srv.server_close()

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
