"""Scenario test for holds on a session's inbox through the client API, and for push.py sending a line to a server that is not on its box — fixture data, no live store, no network.

The rule: a fleet tool on another box cannot write the server's held-<source>.txt files, so it holds and releases through the client API (POST /client/inbox-hold, inbox-release), lists
holds (GET inbox-holds) and asks whether a line waits for a session (GET inbox-waiting). The calls write their own file, held-api-<source>.txt, which the server honours with the others (inbox.take skips a held key), a hold made by the
call expires when its time is up, and the file another tool writes (held-<source>.txt) is only read, never written; the reboot's resume's file is lifted from only by age (part 12). push.py sends through the server's `message` call when [client]
push_mode (or $ANCHOR_PUSH_MODE) says the server is not on this box, and keeps writing the local folders by default.

    tests/run-suite inbox_hold_api        → exit 0 / 1"""
import json, os, re, socket, sys, pathlib, logging, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="inboxholdapi-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet")
for k in ("STACKSHOT_URL", "ANCHOR_PUSH_MODE", "PUSH_FROM"): os.environ.pop(k, None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "secrets"): (T / d).mkdir(parents=True)
(T / "fleet/a/sessions.json").write_text("{}"); (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "store/projects.json").write_text(json.dumps({"pages": {}})); (T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
sys.path.insert(0, STACK); logging.disable(logging.CRITICAL)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))

from stackshot.core import config as cfg
from stackshot.fleet import client, inbox, inbox_holds as holds
FLAGS = T / "state/anchor-hub"
U = lambda n: f"{n:08d}-0000-4000-8000-000000000000"
SID, NAME = U(7), "site-builder"
lines = lambda f: [ln for ln in (FLAGS / f).read_text().splitlines()] if (FLAGS / f).exists() else None; AP = lambda s: lines(f"held-api-{s}.txt")      # AP: the API's own file
T0 = 1790780400.0

# ================================================================= 1. the module: hold, list, expire, release
check("fixture: the module reads the instance's anchor-hub folder", pathlib.Path(inbox.FLAGS) == FLAGS, inbox.FLAGS)
r = holds.hold([SID, NAME], ["msg", "hub"], 10, now=T0)
check("hold: the API's own files list both keys, and no file of another tool is made", AP("msg") == [SID, NAME] and AP("hub") == [SID, NAME] and lines("held-msg.txt") is None and lines("held-hub.txt") is None, (AP("msg"), AP("hub")))
check("hold: the answer names the keys and when it ends", r == {"held": {"msg": [SID, NAME], "hub": [SID, NAME]}, "expires": T0 + 600}, r)
check("hold: the server's own reader sees the hold (inbox.blocked)", inbox.blocked("msg")[2] == {SID, NAME} and inbox.blocked("hub")[2] == {SID, NAME}, inbox.blocked("msg"))
iid = inbox.put(NAME, "a line for the held pane", "msg", now=T0, sender="site-main")
check("take: a held key's line is not handed out", inbox.take({SID: NAME}, only_src="msg", now=T0 + 1) == [])
holds.release([SID, NAME], ["msg", "hub"])
tk = inbox.take({SID: NAME}, only_src="msg", now=T0 + 2)
check("release: the next take hands the line out", len(tk) == 1 and tk[0]["ids"] == [iid], tk)
inbox.ack([iid])
check("release: the API's files are empty and the times forgotten", AP("msg") == [] and not (FLAGS / holds.LEDGER_NAME).exists(), (AP("msg"), list(FLAGS.iterdir())))
check("release: a key that is not held is no error (an empty list for the kind)", holds.release(["nobody"], ["msg"]) == {"released": {"msg": []}})

# a hold of one kind only
holds.hold([NAME], ["hub"], 10, now=T0)
check("hold: one kind only touches that kind's file", AP("hub") == [NAME] and AP("msg") == [], (AP("hub"), AP("msg")))
holds.release([NAME], ["hub"])

# other keys of the file are kept, and the resume file is read as it was and never written
(FLAGS / "held-msg.txt").write_text("by-hand\n"); (FLAGS / "held-resume-msg.txt").write_text("resumed\n")
holds.hold([NAME], ["msg"], 10, now=T0)
check("hold: a key held by another tool stays in its file, the new one is in the API's", lines("held-msg.txt") == ["by-hand"] and AP("msg") == [NAME], (lines("held-msg.txt"), AP("msg")))
rows = {(r["kind"], r["key"], r["origin"]): r for r in holds.listing(now=T0 + 5)["holds"]}
check("list: the origins: api with its times, file without, resume without",
      rows[("msg", NAME, "api")]["since"] == T0 and rows[("msg", NAME, "api")]["expires"] == T0 + 600 and len(rows) == 3
      and rows[("msg", "by-hand", "file")]["expires"] is None and rows[("msg", "by-hand", "file")]["since"] is None and rows[("msg", "resumed", "resume")]["since"] is None, rows)
check("list: a key narrows it", [r["key"] for r in holds.listing(NAME)["holds"]] == [NAME], holds.listing(NAME))
check("sweep: before the time, nothing goes", holds.sweep(now=T0 + 599) == [] and AP("msg") == [NAME])
holds.hold([NAME], ["msg"], 10, now=T0 + 500)
check("hold again is a refresh: the time moves", holds.sweep(now=T0 + 700) == [] and AP("msg") == [NAME])
gone = holds.sweep(now=T0 + 500 + 601)
check("sweep: past the time the key goes from the API's file, and only that key", gone == [f"msg:{NAME}"] and AP("msg") == [] and lines("held-msg.txt") == ["by-hand"], (gone, AP("msg"), lines("held-msg.txt")))
check("sweep: the API's sweep never expires a key of another tool or of the resume file (the resume file has its own, age-bound sweep_resume, part 12)",lines("held-resume-msg.txt") == ["resumed"] and holds.sweep(now=T0 + 10**7) == [] and lines("held-msg.txt") == ["by-hand"])
holds.hold([NAME], ["msg"], 0, now=T0)
check("hold with 0 minutes: no end, never swept", holds.sweep(now=T0 + 10**7) == [] and AP("msg") == [NAME] and [r["expires"] for r in holds.listing(NAME)["holds"]] == [None] and holds.hold([NAME], ["msg"], 0, now=T0)["expires"] is None)
rel = holds.release([NAME, "by-hand"], ["msg"])
check("release: lifts the API's key only; another tool's key stays and is named in held_elsewhere", rel == {"released": {"msg": [NAME]}, "held_elsewhere": ["by-hand"]} and AP("msg") == [] and lines("held-msg.txt") == ["by-hand"] and lines("held-resume-msg.txt") == ["resumed"], (rel, lines("held-msg.txt")))
os.remove(FLAGS / "held-resume-msg.txt"); os.remove(FLAGS / "held-msg.txt")
cfg.CFG.setdefault("client", {})["inbox_hold_minutes"] = 3
r = holds.hold([NAME], ["msg"], None, now=T0)
check("hold with no minutes: the setting's", r["expires"] == T0 + 180, r)
holds.release([NAME], ["msg"]); cfg.CFG["client"].pop("inbox_hold_minutes")

# ================================================================= 2. waiting
i_msg = inbox.put(NAME, "to the name", "msg", now=T0, sender="x"); i_hub = inbox.put(SID, "to the id", "hub", now=T0, sender="x"); i_other = inbox.put("site-builder-extra", "to another", "msg", now=T0, sender="x")
w = holds.waiting([NAME])
check("waiting: a line addressed by the name counts, by kind; a line of another name and a line that only mentions it do not", (w["msg"], w["hub"], w["waiting"]) == (1, 0, True), w)
w = holds.waiting([NAME, SID])
check("waiting: the name and the transcript id together, each kind", (w["msg"], w["hub"]) == (1, 1), w)
check("waiting: nothing for a session nothing is addressed to", holds.waiting(["quiet-one"]) == {"keys": ["quiet-one"], "hub": 0, "msg": 0, "waiting": False, "held": {"hub": False, "msg": False}})
holds.hold([NAME], ["msg"], 10, now=T0)
w = holds.waiting([NAME])
check("waiting: a held line still waits, and `held` says it is held", w["msg"] == 1 and w["held"] == {"hub": False, "msg": True}, w)
holds.release([NAME], ["msg"]); inbox.ack([i_msg, i_hub, i_other])

# ================================================================= 3. refusals of the module's calls
bad = lambda body, fn=holds.api_hold: fn(body)[0]
check("api_hold: no keys, an empty key, a non-list, too many, a control character, a long one → 400",
      all(bad(b) == 400 for b in ({}, {"keys": []}, {"keys": [" "]}, {"keys": 5}, {"keys": [str(i) for i in range(21)]}, {"keys": ["a\nb"]}, {"keys": ["x" * 201]})))
check("api_hold: a kind that is not hub or msg, minutes below 0 or above a day, minutes that are no number or a bool → 400",
      all(bad({"keys": ["a"], **b}) == 400 for b in ({"kinds": ["both"]}, {"kinds": [1]}, {"minutes": -1}, {"minutes": 1441}, {"minutes": "soon"}, {"minutes": True})))
check("api_hold: a string for kinds and for keys is one", holds.api_hold({"keys": "k1", "kinds": "hub"})[0] == 200 and AP("hub") == ["k1"], AP("hub"))
holds.api_release({"keys": ["k1"]})
check("api_release: refuses what api_hold refuses", bad({"keys": []}, holds.api_release) == 400 and bad({"keys": ["a"], "kinds": ["x"]}, holds.api_release) == 400)

# ================================================================= 4. over HTTP, with a machine token
from starlette.testclient import TestClient
from stackshot.web import server
from stackshot.web import publish as _web_publish
from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
tok = open(client.mint("box-far")).read().strip()
HB = {"Authorization": "Bearer " + tok}
app = server.mcp.http_app()
with TestClient(app) as c:
    r = c.post("/client/inbox-hold", json={"keys": [SID, NAME]})
    check("http: a hold without a token is refused (401)", r.status_code == 401, r.status_code)
    check("http: …so is a read of the holds and of the waiting lines", c.get("/client/inbox-holds").status_code == 401 and c.get("/client/inbox-waiting?key=x").status_code == 401)
    r = c.post("/client/inbox-hold", json={"keys": [SID, NAME], "minutes": 5}, headers=HB)
    check("http: hold → 200 with the keys and the end", r.status_code == 200 and r.json()["held"] == {"msg": [SID, NAME], "hub": [SID, NAME]} and r.json()["expires"] > 0, (r.status_code, r.text))
    check("http: …and the API's files hold them", AP("msg") == [SID, NAME] and AP("hub") == [SID, NAME])
    r = c.get("/client/inbox-holds", headers=HB)
    check("http: list → 200 JSON, four rows made by the call", r.status_code == 200 and [x["origin"] for x in r.json()["holds"]] == ["api"] * 4, r.text)
    r = c.get(f"/client/inbox-holds?key={NAME}", headers=HB)
    check("http: list with a key → that key's two rows", r.status_code == 200 and {x["kind"] for x in r.json()["holds"]} == {"msg", "hub"} and len(r.json()["holds"]) == 2, r.text)
    j = inbox.put(NAME, "waits", "msg", now=T0, sender="x")
    r = c.get(f"/client/inbox-waiting?key={NAME},{SID}", headers=HB)
    check("http: waiting → the count by kind, and held", r.status_code == 200 and r.json()["msg"] == 1 and r.json()["hub"] == 0 and r.json()["waiting"] is True and r.json()["held"] == {"hub": True, "msg": True}, r.text)
    check("http: waiting with no key → 400", c.get("/client/inbox-waiting", headers=HB).status_code == 400 and c.get("/client/inbox-waiting?key=" + ",".join("k%d" % i for i in range(21)), headers=HB).status_code == 400)
    check("http: a bad hold body is 400 with the reason", c.post("/client/inbox-hold", json={"keys": []}, headers=HB).status_code == 400 and "keys" in c.post("/client/inbox-hold", json={"keys": []}, headers=HB).json()["error"])
    r = c.post("/client/inbox-release", json={"keys": [SID, NAME], "kinds": ["msg"]}, headers=HB)
    check("http: release one kind → 200, that file only", r.status_code == 200 and r.json() == {"released": {"msg": [SID, NAME]}} and AP("msg") == [] and AP("hub") == [SID, NAME], (r.text, AP("hub")))
    c.post("/client/inbox-release", json={"keys": [SID, NAME]}, headers=HB); inbox.ack([j])
    check("http: the verbs are in the 404 lists, so a client sees them", "inbox-hold | inbox-release" in c.post("/client/nope", json={}, headers=HB).text and "inbox-waiting" in c.get("/client/nope", headers=HB).text)

# ================================================================= 5. the minute tick sweeps
from stackshot.service import fleet_events as fe
holds.hold([NAME], ["msg"], 1)
real = holds.sweep; seen = []
holds.sweep = lambda now=None: seen.append(1) or real(now=time.time() + 3600)
try:
    fe.clients_tick()
finally:
    holds.sweep = real
check("clients_tick: the sweep runs once a minute and takes out a hold past its time", seen == [1] and AP("msg") == [], (seen, AP("msg")))

# ================================================================= 6. client.py's forms
import io, contextlib
def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = client.main(["client.py", *argv])
    return rc, out.getvalue(), err.getvalue()
check("client.py: inbox hold/release with no key → usage, exit 1", run(["post", "inbox-hold"])[0] == 1 and "usage: client.py post inbox-hold" in run(["post", "inbox-hold"])[2]
      and run(["post", "inbox-release"])[0] == 1 and run(["post", "inbox-hold", "k", "--minutes"])[0] == 1)
sent = []
real_post = client.post
client.post = lambda what, body, timeout=20.0: sent.append((what, body)) or (200, {"ok": True})
try:
    rc, out, _ = run(["post", "inbox-hold", SID, NAME, "--kind", "msg", "--minutes", "7"])
    rc2, _o, _e = run(["post", "inbox-release", NAME])
finally:
    client.post = real_post
check("client.py: post inbox-hold sends the keys, the kind and the minutes; inbox-release the keys", rc == 0 and rc2 == 0 and sent == [("inbox-hold", {"keys": [SID, NAME], "kinds": ["msg"], "minutes": "7"}), ("inbox-release", {"keys": [NAME]})], sent)
check("client.py: the two reads are known reads", "inbox-holds" in client.READS and "inbox-waiting" in client.READS)
check("client.py: the usage text names the four forms", all(x in pathlib.Path(client.__file__).read_text(encoding="utf-8") for x in ("post inbox-hold", "post inbox-release", "get inbox-holds", "get inbox-waiting")))

# ================================================================= 7. push.py: where the line goes
from stackshot.fleet import push
check("push_mode: the default is the local folders", push.server_mode() is False)
os.environ["ANCHOR_PUSH_MODE"] = "server"; check("push_mode: $ANCHOR_PUSH_MODE=server → the server", push.server_mode() is True)
os.environ["ANCHOR_PUSH_MODE"] = "local"; cfg.CFG.setdefault("client", {})["push_mode"] = "server"
check("push_mode: $ANCHOR_PUSH_MODE=local beats the setting", push.server_mode() is False)
del os.environ["ANCHOR_PUSH_MODE"]
check("push_mode: [client] push_mode = server → the server", push.server_mode() is True)
cfg.CFG["client"]["push_mode"] = "auto"
for url, want in (("http://127.0.0.1:8020", False), ("http://localhost:8020", False), (f"http://{socket.gethostname()}:8020", False), ("https://stackshot.example.com", True), ("http://192.0.2.9:8020", True)):
    os.environ["STACKSHOT_URL"] = url or " "
    check(f"push_mode auto: client URL {url!r} → {'server' if want else 'local'}", push.server_mode() is want, url)
del os.environ["STACKSHOT_URL"]; _url = cfg.CFG["client"].get("url"); cfg.CFG["client"]["url"] = ""
check("push_mode auto: no client URL at all → local", push.server_mode() is False); cfg.CFG["client"]["url"] = _url
cfg.CFG["client"]["push_mode"] = "nonsense"; push._warned[:] = ["seen"]; check("push_mode: a value that is none of the three is local", push.server_mode() is False)
cfg.CFG["client"]["push_mode"] = "server"
calls = []
def fake(status, out):
    client.message = lambda to, text, sender, **kw: calls.append((to, text, sender)) or (status, out)
real_msg = client.message
try:
    err = io.StringIO()
    for status, out, want in ((200, "delivered → work-new — arrives as a labelled [stackshot message] turn", 0), (200, "inbox → work-new — it waits in the server's inbox", 1),
                              (200, "queued → work-new — the session is not live right now", 1), (200, "held for work-new's next turn — it is handed over", 0), (200, "not passed on — a front agent", 2),
                              (400, "Refused: message longer", 2), (404, "no such", 2), (0, "URLError: refused", 4), (502, "bad gateway", 4)):
        fake(status, out); calls.clear()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = push.deliver("work-new", "a line", "builder")
        check(f"push server mode: the server's {status} {out[:14]!r} → exit {want}", rc == want and calls == [("work-new", "a line", "builder")], (rc, calls))
    fake(200, "delivered → x")
    cfg.CFG.setdefault("anchor_hub", {})["require_sender"] = True; calls.clear()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        rc = push.deliver("work-new", "no sender")
    check("push server mode: require_sender still refuses a line with no sender (exit 2), and nothing is sent", rc == 2 and calls == [], (rc, calls))
    cfg.CFG["anchor_hub"]["require_sender"] = False
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        rc = push.deliver("work-new", "a caller's line")
    check("push server mode: no sender → the calling program's name, as the local path does", rc == 0 and len(calls) == 1 and calls[0][2], calls)
    check("push server mode: nothing is queued or put in the local folders", inbox.waiting() == {} and not list((T / "state/anchor-hub").glob("queue*/*.jsonl")), (inbox.waiting(), list((T / "state").rglob("*.jsonl"))))
    check("push server mode: --flush has no queue here: exit 0", push.flush("work-new") == 0)
finally:
    client.message = real_msg
cfg.CFG["client"]["push_mode"] = "local"

# the server's own programs pin the local mode for what they start
import runpy
from stackshot import cli
seen_env = {}
real_run = runpy.run_module
runpy.run_module = lambda *a, **k: seen_env.update(mode=os.environ.get("ANCHOR_PUSH_MODE")) or {}
try:
    for prog in ("server", "minute", "anchor-hub", "audit", "audit-run", "router-live", "held"):
        os.environ.pop("ANCHOR_PUSH_MODE", None); seen_env.clear(); cli.run_program(prog, [])
        check(f"cli: `stackshot {prog}` {'sets' if prog in cli.SERVER_PROGRAMS else 'does not set'} ANCHOR_PUSH_MODE=local", seen_env.get("mode") == ("local" if prog != "held" else None), seen_env)
    check("cli: six programs are pinned, each of them tried below", len(cli.SERVER_PROGRAMS) == 6 and {"minute", "audit-run"} <= set(cli.SERVER_PROGRAMS), cli.SERVER_PROGRAMS)
    for inherited in ("server", "auto", "local"):       # a mode the server's own program inherited (a shell that exports it) never beats the pin; a program that is not the server's keeps what it inherited
        for prog in (*cli.SERVER_PROGRAMS, "held"):
            os.environ["ANCHOR_PUSH_MODE"] = inherited; seen_env.clear(); cli.run_program(prog, [])
            check(f"cli: `stackshot {prog}` with ANCHOR_PUSH_MODE={inherited} inherited starts its children in {'local' if prog != 'held' else inherited}", seen_env.get("mode") == ("local" if prog != "held" else inherited), seen_env)
finally:
    runpy.run_module = real_run; os.environ.pop("ANCHOR_PUSH_MODE", None)

# ================================================================= 8. the other tool's files: read, never written
def put_file(name, data, mtime=1_500_000_000_000_000_000):
    p = FLAGS / name; p.write_bytes(data.encode() if isinstance(data, str) else data); os.utime(p, ns=(mtime, mtime))       # an old mtime: a rewrite, even with the same bytes, shows
def snap(*names):
    return {n: ((FLAGS / n).read_bytes(), (FLAGS / n).stat().st_mtime_ns) if (FLAGS / n).exists() else None for n in names}
OTHER = ("held-msg.txt", "held-hub.txt", "held-resume-msg.txt", "held-resume-hub.txt")
put_file("held-msg.txt", "mgr-1\nmgr-2\n"); put_file("held-hub.txt", "mgr-hub\nno-newline-at-end"); put_file("held-resume-msg.txt", "res-1\n"); put_file("held-resume-hub.txt", b"res-hub\n\n  \n")
before = snap(*OTHER)
holds.hold(["mgr-1", "own-1"], ["msg", "hub"], 1, now=T0); holds.hold(["mgr-1", "res-1", "res-hub", "mgr-hub"], ["msg"], 0, now=T0 + 1); holds.hold(["own-2"], ["hub"], 2, now=T0 + 2)
check("files of another tool: a hold of the same keys leaves their bytes and mtime as they were", snap(*OTHER) == before, (snap(*OTHER), before))
holds.release(["mgr-1", "own-1", "mgr-hub"], ["msg", "hub"]); holds.hold(["own-1"], ["msg"], 1, now=T0 + 3)
check("files of another tool: a release naming their keys leaves them as they were", snap(*OTHER) == before, snap(*OTHER))
gone = holds.sweep(now=T0 + 10**4)
check("files of another tool: a sweep that expires keys leaves them as they were, and takes the API's only", snap(*OTHER) == before and sorted(gone) == ["hub:own-2", "msg:own-1"] and holds.sweep(now=T0 + 10**6) == [], (gone, snap(*OTHER)))
check("files of another tool: the API's file keeps the keys with no end that were not released", AP("msg") == ["res-1", "res-hub"] and AP("hub") == [], (AP("msg"), AP("hub")))
holds.release(["mgr-1", "res-1", "res-hub", "mgr-hub"], ["msg"])
check("files of another tool: …and after the last release too", snap(*OTHER) == before and AP("msg") == [] and not (FLAGS / holds.LEDGER_NAME).exists(), (snap(*OTHER), AP("msg")))
for n in OTHER: os.remove(FLAGS / n)

# a key in the other tool's file blocks the server's reader, and is listed; a release names it in `held_elsewhere` and leaves it
iid = inbox.put("mgr-pane", "a line for a pane another tool holds", "msg", now=T0, sender="x")
put_file("held-msg.txt", "mgr-pane\n")
check("another tool's key: blocked() holds it and take() hands nothing out", inbox.blocked("msg")[2] == {"mgr-pane"} and inbox.take({U(31): "mgr-pane"}, only_src="msg", now=T0 + 1) == [])
check("another tool's key: inbox-holds lists it with origin file", [(r["origin"], r["since"], r["expires"]) for r in holds.listing("mgr-pane")["holds"]] == [("file", None, None)], holds.listing("mgr-pane"))
check("another tool's key: waiting says it waits and is held", holds.waiting(["mgr-pane"])["held"] == {"hub": False, "msg": True} and holds.waiting(["mgr-pane"])["msg"] == 1)
rel = holds.release(["mgr-pane"], ["msg"])
check("another tool's key: release names it in held_elsewhere, removes nothing, and the line is still held", rel == {"released": {"msg": []}, "held_elsewhere": ["mgr-pane"]} and lines("held-msg.txt") == ["mgr-pane"] and inbox.take({U(31): "mgr-pane"}, only_src="msg", now=T0 + 2) == [], rel)
over = holds.api_release({"keys": ["mgr-pane", "never-held"], "kinds": ["msg", "hub"]})
check("another tool's key: held_elsewhere is a flat list of the keys, each once, in the order named; a key held nowhere is not in it", over == (200, {"released": {"msg": [], "hub": []}, "held_elsewhere": ["mgr-pane"]}), over)
put_file("held-msg.txt", "")
# a key in the API's file blocks the same reader
holds.hold(["mgr-pane"], ["msg"], 10, now=T0)
check("the API's key: blocked() and take() honor it", inbox.blocked("msg")[2] == {"mgr-pane"} and inbox.take({U(31): "mgr-pane"}, only_src="msg", now=T0 + 3) == [])
dl = inbox.deliberate(inbox.peek([iid])[0])
check("the API's key: deliberate names the API's file, not the other tool's", "held-api-msg.txt" in dl and "held-msg.txt" not in dl and "held-resume" not in dl, dl)
# both families at once: held in each, released from the API's, still held by the other tool's
put_file("held-msg.txt", "mgr-pane\n"); put_file("held-hub.txt", "")
rel = holds.release(["mgr-pane"], ["msg"])
check("both families: the release lifts the API's hold and names the key, which the other tool's file keeps holding", rel == {"released": {"msg": ["mgr-pane"]}, "held_elsewhere": ["mgr-pane"]} and AP("msg") == [] and inbox.take({U(31): "mgr-pane"}, only_src="msg", now=T0 + 4) == [], rel)
holds.hold(["mgr-pane"], ["msg"], 10, now=T0); put_file("held-msg.txt", "")
check("both families: when the other tool lifts its hold the API's still holds the line", inbox.take({U(31): "mgr-pane"}, only_src="msg", now=T0 + 5) == [] and sorted(r["origin"] for r in holds.listing("mgr-pane")["holds"]) == ["api"])
put_file("held-msg.txt", "mgr-pane\n")
dl = inbox.deliberate(inbox.peek([iid])[0])
check("both families: deliberate names both files", "held-msg.txt" in dl and "held-api-msg.txt" in dl, dl)
check("both families: a key in both is two rows in the list, one for each file", sorted(r["origin"] for r in holds.listing("mgr-pane")["holds"]) == ["api", "file"], holds.listing("mgr-pane"))
holds.release(["mgr-pane"], ["msg"]); put_file("held-msg.txt", "")
tk = inbox.take({U(31): "mgr-pane"}, only_src="msg", now=T0 + 6)
check("both families: with both lifted the line is handed out", len(tk) == 1 and tk[0]["ids"] == [iid], tk)
inbox.ack([iid]); os.remove(FLAGS / "held-msg.txt"); os.remove(FLAGS / "held-hub.txt")
# the resume file: a release never touches it, even for a key held only there
put_file("held-resume-msg.txt", "res-only\n"); b0 = snap("held-resume-msg.txt")
rel = holds.release(["res-only"], ["msg", "hub"])
check("resume file: a release naming its key leaves the file untouched, the key held, and names it", rel == {"released": {"msg": [], "hub": []}, "held_elsewhere": ["res-only"]} and snap("held-resume-msg.txt") == b0 and inbox.blocked("msg")[2] == {"res-only"}, (rel, snap("held-resume-msg.txt")))
os.remove(FLAGS / "held-resume-msg.txt")

# a stale time (a key the API's file no longer holds) is dropped by the sweep, whatever its end, and never frees another tool's key of that name
holds.hold(["gone-key", "kept-key"], ["msg"], 10, now=T0)
(FLAGS / "held-api-msg.txt").write_text("kept-key\n"); put_file("held-msg.txt", "gone-key\n"); b0 = snap("held-msg.txt")
check("stale time: a sweep before its end takes nothing out, drops the row of the key that is no longer in the file, and keeps the other", holds.sweep(now=T0 + 1) == [] and sorted(json.loads((FLAGS / holds.LEDGER_NAME).read_text())["msg"]) == ["kept-key"], (FLAGS / holds.LEDGER_NAME).read_text())
check("stale time: …the other tool's key of that name stays held, unchanged, and is listed as its own", snap("held-msg.txt") == b0 and sorted((r["origin"], r["key"]) for r in holds.listing()["holds"] if r["kind"] == "msg") == [("api", "kept-key"), ("file", "gone-key")], holds.listing())
holds.hold(["gone-key"], ["msg"], 1, now=T0); (FLAGS / "held-api-msg.txt").write_text("kept-key\n")
check("stale time: a row past its end for a key that is gone is dropped too, taking nothing out", holds.sweep(now=T0 + 10**6) == ["msg:kept-key"] and snap("held-msg.txt") == b0 and not (FLAGS / holds.LEDGER_NAME).exists(), (snap("held-msg.txt"), list(FLAGS.iterdir())))
os.remove(FLAGS / "held-msg.txt"); os.remove(FLAGS / "held-api-msg.txt")
# a key in the API's file with no time (written by hand) is listed as api with no time and never expired
(FLAGS / "held-api-hub.txt").write_text("no-time\n")
check("a key in the API's file with no row: listed as api with no time, and not taken out by the sweep that gives it a time", [(r["origin"], r["since"], r["expires"]) for r in holds.listing("no-time")["holds"]] == [("api", None, None)] and holds.sweep(now=T0 + 10**7) == [])
holds.release(["no-time"], ["hub"])

# whitespace around a key: the server's reader drops it, so does this module (`abc ` and `abc` are one key)
put_file("held-msg.txt", "abc \n\tdef\r\n  \n"); put_file("held-api-hub.txt", " ghi  \n")
check("whitespace: the server's reader reads the keys without it", inbox.blocked("msg")[2] == {"abc", "def"} and inbox.blocked("hub")[2] == {"ghi"}, (inbox.blocked("msg"), inbox.blocked("hub")))
check("whitespace: the list names the keys without it", sorted(r["key"] for r in holds.listing()["holds"]) == ["abc", "def", "ghi"], holds.listing())
check("whitespace: waiting finds them held", holds.waiting(["abc"])["held"] == {"hub": False, "msg": True} and holds.waiting(["ghi"])["held"] == {"hub": True, "msg": False})
rel = holds.release(["abc", "ghi"], ["msg", "hub"])
check("whitespace: a release of `abc` names the other tool's `abc ` and lifts the API's ` ghi `", rel == {"released": {"msg": [], "hub": ["ghi"]}, "held_elsewhere": ["abc"]} and (FLAGS / "held-api-hub.txt").read_text() == "", rel)
os.remove(FLAGS / "held-msg.txt")

# ================================================================= 9. the surviving mutants: waiting by permanent id and transcript id, held-resume and the API's file in waiting, the kind of a release, atomic writes, the threadpool
d = inbox.DIR / "msg"; d.mkdir(parents=True, exist_ok=True)
(d / "0000000000001-aaaaaa.json").write_text(json.dumps({"id": "0000000000001-aaaaaa", "ts": T0, "src": "msg", "to": "zz-addr", "uuid": "", "name": "zz-name", "pid": "perm-9", "text": "x", "from": "y"}))
w = holds.waiting(["perm-9"])
check("waiting: a line is matched by its permanent id (`pid`) alone", (w["msg"], w["hub"], w["waiting"]) == (1, 0, True), w)
check("waiting: a line is matched by its address, its transcript id or its name alone, and a non-key matches none", all(holds.waiting([k])["msg"] == (1 if k in ("zz-addr", "zz-name") else 0) for k in ("zz-addr", "zz-name", "zz")), [holds.waiting([k])["msg"] for k in ("zz-addr", "zz-name", "zz")])
os.remove(d / "0000000000001-aaaaaa.json")
dh = inbox.DIR / "hub"; dh.mkdir(parents=True, exist_ok=True)
(dh / "0000000000002-bbbbbb.json").write_text(json.dumps({"id": "0000000000002-bbbbbb", "ts": T0, "src": "hub", "to": "yy-addr", "uuid": "yy-uuid", "name": "yy-name", "pid": "", "text": "x", "from": "y"}))
w = holds.waiting(["yy-uuid"])
check("waiting: a line is matched by its transcript id (`uuid`) alone, and counted in its own kind", (w["hub"], w["msg"], w["waiting"]) == (1, 0, True) and holds.waiting(["yy"])["waiting"] is False, w)
os.remove(dh / "0000000000002-bbbbbb.json")
(FLAGS / "held-resume-hub.txt").write_text("resume-key\n")
w = holds.waiting(["resume-key"])
check("waiting: a key in the reboot's resume file is held too, for its source only", w["held"] == {"hub": True, "msg": False}, w)
(FLAGS / "held-hub.txt").write_text("plain-key\n")
check("waiting: a key in the plain file is held for its source only", holds.waiting(["plain-key"])["held"] == {"hub": True, "msg": False} and holds.waiting(["resume-key", "plain-key"])["held"] == {"hub": True, "msg": False})
(FLAGS / "held-api-msg.txt").write_text("api-key\n")
check("waiting: a key in the API's own file is held, for its source only", holds.waiting(["api-key"])["held"] == {"hub": False, "msg": True} and holds.waiting(["api-key", "plain-key"])["held"] == {"hub": True, "msg": True})
os.remove(FLAGS / "held-resume-hub.txt"); (FLAGS / "held-hub.txt").write_text(""); (FLAGS / "held-api-msg.txt").write_text("")
client.post = lambda what, body, timeout=20.0: sent.append((what, body)) or (200, {"ok": True})
sent.clear()
try:
    rc = run(["post", "inbox-release", NAME, "--kind", "hub"])[0]; rc2 = run(["post", "inbox-release", NAME, SID])[0]
finally:
    client.post = real_post
check("client.py: post inbox-release --kind sends the kind in the body, and sends none without it", rc == 0 and rc2 == 0 and sent == [("inbox-release", {"keys": [NAME], "kinds": ["hub"]}), ("inbox-release", {"keys": [NAME, SID]})], sent)
# a write is a complete new file put in place (no moment where the file is partly written): at each replace the target still has the earlier whole content and the new file the whole later one
seen_rep = []; real_rep = os.replace
def spy(src, dst, *a, **k):
    src, dst = pathlib.Path(src), pathlib.Path(dst)
    seen_rep.append((dst.name, src.name != dst.name, dst.read_text() if dst.exists() else None, src.read_text()))
    return real_rep(src, dst, *a, **k)
os.replace = spy
try:
    holds.hold(["w-1", "w-2"], ["msg"], 10, now=T0); holds.hold(["w-3"], ["msg"], 10, now=T0); holds.release(["w-1"], ["msg"])
finally:
    os.replace = real_rep
files = [(n, own, before or "", after) for n, own, before, after in seen_rep if n == "held-api-msg.txt"]
check("atomic: the API's hold file is replaced from a whole file written beside it, never written in place", [(own, before, after) for _n, own, before, after in files] == [(True, "", "w-1\nw-2\n"), (True, "w-1\nw-2\n", "w-1\nw-2\nw-3\n"), (True, "w-1\nw-2\nw-3\n", "w-2\nw-3\n")], files)
ledgers = [(own, before, after) for n, own, before, after in seen_rep if n == holds.LEDGER_NAME]
check("atomic: the times file too: each replace puts a whole, readable file in place", len(ledgers) == 3 and all(own and json.loads(after) for own, _b, after in ledgers) and all(before is None or json.loads(before) for _o, before, _a in ledgers), ledgers)
holds.release(["w-2", "w-3"], ["msg"])
# the two reads that scan files run off the event loop, as `items` does
import asyncio
on_loop = {}
def probe(name, real):
    def f(*a, **k):
        try: asyncio.get_running_loop(); on_loop[name] = True
        except RuntimeError: on_loop[name] = False
        return real(*a, **k)
    return f
real_l, real_w = holds.listing, holds.waiting
holds.listing, holds.waiting = probe("holds", real_l), probe("waiting", real_w)
try:
    c2 = TestClient(app)
    a = c2.get("/client/inbox-holds", headers=HB); b = c2.get(f"/client/inbox-waiting?key={NAME}", headers=HB)
finally:
    holds.listing, holds.waiting = real_l, real_w
check("http: inbox-holds and inbox-waiting are answered from the threadpool, not the event loop", a.status_code == 200 and b.status_code == 200 and on_loop == {"holds": False, "waiting": False}, (a.status_code, b.status_code, on_loop))

# ================================================================= 10. push.py auto: which hosts are this box
host, fqdn = socket.gethostname(), socket.getfqdn()
cfg.CFG["client"]["push_mode"] = "auto"
for url, want in (("http://0.0.0.0:8020", False), ("http://127.0.1.1:8020", False), ("http://[::1]:8020", False), ("http://[::]:8020", False), ("http://LOCALHOST:8020", False), ("http://svc.localhost:8020", False),
                  (f"http://{host.upper()}:8020", False), (f"http://{fqdn}:8020", False), (f"http://{fqdn.upper()}:8020", False), (f"http://{host.split('.')[0]}:8020", False), (f"http://{host.split('.')[0].upper()}:8020", False),
                  (f"https://{host.split('.')[0]}.other-domain.example", True), ("http://198.51.100.7:8020", True), ("http://[2001:db8::1]:8020", True), ("http://128.0.0.1:8020", True)):
    os.environ["STACKSHOT_URL"] = url
    check(f"push_mode auto: client URL {url!r} → {'server' if want else 'local'}", push.server_mode() is want, url)
del os.environ["STACKSHOT_URL"]; cfg.CFG["client"]["push_mode"] = "local"

# ================================================================= 11. the reboot's flush counts exit 0 as delivered: it flushes this box's queue whatever mode the caller's environment says
import subprocess
RQ = f"{STACK}/reboot-hooks/reboot-queue.py"
qd = FLAGS / "queue-msg"; qd.mkdir(exist_ok=True); (qd / "qkey.jsonl").write_text(json.dumps({"text": "a plain queued line", "from": "x", "ts": time.time()}) + "\n")
(T / "listed-q.txt").write_text("qkey\n")
r = subprocess.run([sys.executable, RQ, "resume", "--source", "msg", "--sessions", str(T / "listed-q.txt"), "--wait", "1"], capture_output=True, text=True, env={**os.environ, "ANCHOR_PUSH_MODE": "server"})
q = json.loads(r.stdout or "{}")
check("reboot queue: its flush runs in local mode even when the environment says server (a server-mode flush would exit 0 and count a line it did not send)", q.get("failed") == 1 and q.get("failed_sessions") == ["qkey"] and q.get("delivered") == 0 and (qd / "qkey.jsonl").exists(), (r.stdout, r.stderr[-300:]))
os.remove(qd / "qkey.jsonl")


# ================================================================= 11b. the end of a hold is the minute it names; two processes holding at once lose no key
holds.hold(["edge-a"], ["msg"], 1, now=T0)
check("sweep: one second before the end the key stays, at the end it goes", holds.sweep(now=T0 + 59.5) == [] and AP("msg") == ["edge-a"] and holds.sweep(now=T0 + 60) == ["msg:edge-a"] and AP("msg") == [])
import subprocess as _sp
WORKER = ("import sys\nfrom stackshot.fleet import inbox_holds as h\nfor i in range(25): h.hold([f'{sys.argv[1]}-{i}'], ['msg', 'hub'], 10)\n")
procs = [_sp.Popen([sys.executable, "-c", WORKER, f"w{n}"], cwd=STACK, env={**os.environ, "PYTHONPATH": STACK}) for n in range(6)]
codes = [pr.wait(120) for pr in procs]
want = {f"w{n}-{i}" for n in range(6) for i in range(25)}
check("concurrent holds from six processes: every key is in both of the API's files, and every one has its time", codes == [0] * 6 and set(AP("msg") or []) == want and set(AP("hub") or []) == want and len(json.loads((FLAGS / holds.LEDGER_NAME).read_text())["msg"]) == 150, (codes, len(AP("msg") or []), len(AP("hub") or [])))
holds.release(sorted(want), ["msg", "hub"])
check("concurrent holds: …and releasing them all leaves the files and the times empty", AP("msg") == [] and AP("hub") == [] and not (FLAGS / holds.LEDGER_NAME).exists(), (AP("msg"), AP("hub")))

# ================================================================= 12. push.py: a setting that cannot be read is local, with one warning line for the process
push._warned.clear()
def stderr_of(fn):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        got = fn()
    return got, err.getvalue()
def quiet_deliver():
    with contextlib.redirect_stdout(io.StringIO()):
        return push.deliver("x-no-such", "a line", "builder")
def warn_case(label, want_warn, setting=None, env=None, url=None):
    push._warned.clear(); cfg.CFG["client"].pop("push_mode", None); os.environ.pop("ANCHOR_PUSH_MODE", None); os.environ.pop("STACKSHOT_URL", None)
    if setting is not None: cfg.CFG["client"]["push_mode"] = setting
    if env is not None: os.environ["ANCHOR_PUSH_MODE"] = env
    if url is not None: os.environ["STACKSHOT_URL"] = url
    got, err = stderr_of(lambda: (push.server_mode(), push.server_mode(), push.server_mode()))
    n = len(err.splitlines())
    check(f"push_mode warning: {label} → local, {'one warning line on stderr for the process' if want_warn else 'no warning'}", got == (False, False, False) and n == (1 if want_warn else 0) and (not want_warn or "local" in err), (got, err))
    return err
err = warn_case("a typo in the setting", True, setting="servr")
check("push_mode warning: …it says what it found, and that the line goes to the local folders", "servr" in err and "local folders" in err and "none of local, server or auto" in err, err)
warn_case("a typo in $ANCHOR_PUSH_MODE", True, env="Autoo")
warn_case("a client URL that does not parse (auto)", True, setting="auto", url="http://[::1")
err = warn_case("a client URL with no host (auto)", True, setting="auto", url="stackshot.example.com")
check("push_mode warning: …it names the setting that failed", "client URL" in err, err)
warn_case("the default (nothing set)", False)
warn_case("local", False, setting="local"); warn_case("local in capitals and spaces", False, setting="  LOCAL ")
warn_case("auto with a loopback URL", False, setting="auto", url="http://127.0.0.1:8020")
cfg.CFG["client"]["push_mode"] = "auto"; _url2 = cfg.CFG["client"].get("url"); cfg.CFG["client"]["url"] = ""; os.environ.pop("STACKSHOT_URL", None)
push._warned.clear(); got, err = stderr_of(push.server_mode)
check("push_mode warning: auto with no client URL at all is local and says nothing", got is False and err == "", (got, err)); cfg.CFG["client"]["url"] = _url2
push._warned.clear(); cfg.CFG["client"]["push_mode"] = "server"; got, err = stderr_of(push.server_mode)
check("push_mode warning: server says nothing", got is True and err == "", (got, err))
push._warned.clear(); cfg.CFG["client"]["push_mode"] = "nope"; got, err = stderr_of(quiet_deliver)
check("push_mode warning: a delivery with a typo goes the local way, and the warning is on stderr once", err.count("none of local, server or auto") == 1, err)
cfg.CFG["client"]["push_mode"] = "local"; os.environ.pop("ANCHOR_PUSH_MODE", None); os.environ.pop("STACKSHOT_URL", None); push._warned.clear()
for _f in FLAGS.glob("queue*/*.jsonl"): _f.unlink()

# ================================================================= 13. push.py --flush in server mode, with a queue file present
pq = pathlib.Path(push.Q); pq.mkdir(parents=True, exist_ok=True)
qfile = pq / "work-flush.jsonl"; qbytes = (json.dumps({"text": "a queued line", "from": "x", "ts": time.time()}) + "\n").encode(); qfile.write_bytes(qbytes)
sent_flush = []; real_msg2 = client.message
client.message = lambda *a, **k: sent_flush.append(a) or (200, "delivered → x")
try:
    cfg.CFG["client"]["push_mode"] = "server"
    got, _e = stderr_of(lambda: push.flush("work-flush"))
    check("push --flush in server mode: exit 0, the queue file is left as it was and nothing is sent", got == 0 and qfile.read_bytes() == qbytes and sent_flush == [], (got, qfile.read_bytes(), sent_flush))
    cfg.CFG["client"]["push_mode"] = "local"
    got, _e = stderr_of(lambda: push.flush("work-flush"))
    check("push --flush in local mode works the queue (the session is not live: exit 3)", got == 3 and qfile.exists(), (got, _e))
finally:
    client.message = real_msg2; qfile.unlink(missing_ok=True); cfg.CFG["client"]["push_mode"] = "local"

# ================================================================= 14. validation edges
bad = lambda body, fn=holds.api_hold: fn(body)[0]
check("keys: a control character anywhere in a key is refused, tab and DEL included", all(bad({"keys": [f"a{c}b"]}) == 400 for c in ("\x00", "\x01", "\t", "\x1f", "\x7f")) and all(bad({"keys": [f"a{c}b"]}, holds.api_release) == 400 for c in ("\x00", "\x1f", "\x7f")))
check("keys: a space inside a key, a tilde and exactly 200 characters are accepted; 201 is not", all(bad({"keys": [k]}) == 200 for k in ("a b", "a~b", "x" * 200)) and bad({"keys": ["x" * 201]}) == 400)
holds.release(["a b", "a~b", "x" * 200], ["msg", "hub"])
check("keys: exactly 20 keys are accepted, 21 are not; a key repeated counts once", bad({"keys": [f"k{i}" for i in range(20)]}) == 200 and bad({"keys": [f"k{i}" for i in range(21)]}) == 400 and holds.api_hold({"keys": ["dup", "dup"]})[1]["held"]["msg"] == ["dup"])
holds.release([f"k{i}" for i in range(20)] + ["dup"], ["msg", "hub"])
st, o = holds.api_hold({"keys": ["edge"], "minutes": 1440}); t1 = time.time()
check("minutes: exactly 1440 is accepted and ends a day from now", st == 200 and abs(o["expires"] - (t1 + 86400)) < 5, (st, o))
check("minutes: a hair over 1440, nan and inf are refused", all(bad({"keys": ["edge"], "minutes": m}) == 400 for m in (1440.01, "nan", "inf", "-0.5")))
check("minutes: 0 and \"0\" are refused: a hold made by the call always has an end", all(holds.api_hold({"keys": ["edge"], "minutes": m})[0] == 400 for m in (0, "0")))
check("minutes: left out, null or empty is the setting's", all(abs(holds.api_hold({"keys": ["edge"], **b})[1]["expires"] - (time.time() + 600)) < 5 for b in ({}, {"minutes": None}, {"minutes": ""})))
holds.release(["edge"], ["msg", "hub"])
check("kinds: [] , null and an empty string name both sources; a name alone is that source", all(set(holds.api_hold({"keys": ["kk"], "kinds": k})[1]["held"]) == {"msg", "hub"} for k in ([], None, "")) and set(holds.api_hold({"keys": ["kk"], "kinds": "hub"})[1]["held"]) == {"hub"})
check("kinds: …and a release with [] lifts both", holds.api_release({"keys": ["kk"], "kinds": []})[1] == {"released": {"msg": ["kk"], "hub": ["kk"]}}, AP("msg"))
check("kinds: a duplicate kind counts once (a release answers with the keys it lifted, not with an empty second pass)", holds.api_hold({"keys": ["kk"], "kinds": ["msg", "msg"]})[1]["held"] == {"msg": ["kk"]} and holds.api_release({"keys": ["kk"], "kinds": ["msg", "msg"]})[1] == {"released": {"msg": ["kk"]}}, AP("msg"))
st, o = holds.api_hold({"keys": [" sp ", "sp", "\tsp"], "kinds": ["msg"]})
check("keys: whitespace around a key is dropped and the key is counted once; a release by the plain key lifts it", st == 200 and o["held"] == {"msg": ["sp"]} and AP("msg") == ["sp"] and holds.api_release({"keys": [" sp\t"]})[1]["released"]["msg"] == ["sp"] and AP("msg") == [], (o, AP("msg")))

# ================================================================= 15. held_elsewhere and both families over HTTP, and the server's push path reads the API's file
put_file("held-msg.txt", "http-other\n"); put_file("held-resume-hub.txt", "http-resume\n")
c3 = TestClient(app)
c3.post("/client/inbox-hold", json={"keys": ["http-own"], "minutes": 5}, headers=HB); c3.post("/client/inbox-hold", json={"keys": ["http-other"], "kinds": ["msg"], "minutes": 5}, headers=HB)
r = c3.post("/client/inbox-release", json={"keys": ["http-own", "http-resume", "http-other"]}, headers=HB)
check("http: release → the API's keys lifted (http-other is held by both families: it stays held), the other tool's and the resume's keys named in held_elsewhere (a flat list, in the order named)", r.status_code == 200 and r.json() == {"released": {"msg": ["http-own", "http-other"], "hub": ["http-own"]}, "held_elsewhere": ["http-resume", "http-other"]}, r.text)
r = c3.get("/client/inbox-holds", headers=HB)
check("http: list → the two other-tool keys, each with its file family", r.status_code == 200 and sorted((x["kind"], x["key"], x["origin"]) for x in r.json()["holds"]) == [("hub", "http-resume", "resume"), ("msg", "http-other", "file")], r.text)
r = c3.post("/client/inbox-release", json={"keys": ["http-resume"], "kinds": ["msg"]}, headers=HB)
check("http: a release for a kind where the key is not held names nothing", r.status_code == 200 and r.json() == {"released": {"msg": []}}, r.text)
os.remove(FLAGS / "held-msg.txt"); os.remove(FLAGS / "held-resume-hub.txt")
put_file("held-api-hub.txt", "pp-key\n")
check("push.paused: a key in the API's file keeps the queue, another key does not", push.paused("pp-key") is True and push.paused("other-key") is False, (push.paused("pp-key"), push.paused("other-key")))
put_file("held-hub.txt", "pp-2\n"); put_file("held-resume-hub.txt", "pp-3\n")
check("push.paused: …as do the other two files", push.paused("pp-2") and push.paused("pp-3") and push.paused("pp-key"))
for n in ("held-api-hub.txt", "held-hub.txt", "held-resume-hub.txt"): os.remove(FLAGS / n)
check("push.paused: nothing held, nothing paused", push.paused("pp-key") is False)


# ================================================================= 10. a hold always ends: the time is saved before the key, a lost times file is not a permanent hold, the setting is clamped, the API refuses 0 and caps the keys
def wipe():            # what this module makes in the folder (held-*, the times and their leftovers); the folder's other files are other tools'
    for f in [*FLAGS.glob("held-*"), *FLAGS.glob("holds-api.json*"), *FLAGS.glob("holds-resume.json*"),*FLAGS.glob(".*.tmp"), *FLAGS.glob("w.txt")]:
        if f.is_dir(): f.rmdir()
        else: f.unlink()
wipe()
mine = lambda: sorted(f.name for f in FLAGS.iterdir() if f.name != ".holds-api.lock" and f.name.startswith((".", "held-", "holds-", "w.txt")))
ROWS = lambda: json.loads((FLAGS / holds.LEDGER_NAME).read_text()) if (FLAGS / holds.LEDGER_NAME).exists() else {}
# the ledger cannot be written: nothing is held
(FLAGS / f".{holds.LEDGER_NAME}.tmp").mkdir()
try:
    holds.hold(["m1-a"], ["msg"], 10, now=T0); failed = None
except OSError as e:
    failed = e
check("hold: when the times cannot be saved the call fails and the key is NOT in the file (no key without an end)", failed is not None and not AP("msg") and not holds.listing()["holds"], (failed, AP("msg")))
(FLAGS / f".{holds.LEDGER_NAME}.tmp").rmdir()
holds.hold(["m1-a"], ["msg"], 10, now=T0)
check("hold: with the times writable the key and its time are both there", AP("msg") == ["m1-a"] and ROWS()["msg"]["m1-a"]["expires"] == T0 + 600)
# a times file that cannot be read (not a missing or an unparsable one) is an error, never "no times"
(FLAGS / holds.LEDGER_NAME).unlink(); (FLAGS / holds.LEDGER_NAME).mkdir()
try:
    holds.hold(["m1-b"], ["msg"], 10, now=T0); failed = None
except OSError as e:
    failed = e
check("hold: a times file that cannot be read fails the call and holds nothing new", failed is not None and AP("msg") == ["m1-a"], (failed, AP("msg")))
try:
    holds.sweep(now=T0); failed = None
except OSError as e:
    failed = e
check("sweep: …and the sweep reports it, taking nothing out", failed is not None and AP("msg") == ["m1-a"])
try:
    holds._save_ledger({"msg": {"k": {"since": T0, "expires": T0 + 1}}}); failed = None
except OSError as e:
    failed = e
check("_save_ledger: a save that fails after its temp file is made removes it", failed is not None and mine() == ["held-api-msg.txt", holds.LEDGER_NAME], mine())
(FLAGS / holds.LEDGER_NAME).rmdir(); wipe()
# a read that fails midway (an I/O error) is an error too, not "no times": the call fails and the file is as it was
holds.hold(["io-1"], ["msg"], 10, now=T0); before_led = (FLAGS / holds.LEDGER_NAME).read_text()
real_load = json.load
def _eio(*a, **k): raise OSError(5, "Input/output error")
json.load = _eio
try:
    holds.hold(["io-2"], ["msg"], 10, now=T0); failed = None
except OSError as e:
    failed = e
finally:
    json.load = real_load
check("hold: an I/O error reading the times fails the call: no key is added and the times are untouched", failed is not None and AP("msg") == ["io-1"] and (FLAGS / holds.LEDGER_NAME).read_text() == before_led and mine() == ["held-api-msg.txt", holds.LEDGER_NAME], (failed, AP("msg"), mine()))
holds.release(["io-1"], ["msg"])
# a times file that is not JSON: set aside, and every key in the files has an end again
holds.release(["m1-a"], ["msg"]); wipe()
holds.hold(["old-1", "old-2"], ["msg"], 1000, now=T0); holds.hold(["old-3"], ["hub"], 1000, now=T0)
(FLAGS / holds.LEDGER_NAME).write_text('{"msg": {"old-1": ')
holds.hold(["new-1"], ["msg"], 5, now=T0 + 1)
rows = ROWS()
check("corrupt times file + a new hold: the older keys still hold and have a time (the setting's minutes), the new one its own; the bad file is kept",
      AP("msg") == ["old-1", "old-2", "new-1"] and sorted(rows["msg"]) == ["new-1", "old-1", "old-2"] and rows["msg"]["new-1"]["expires"] == T0 + 1 + 300
      and rows["msg"]["old-1"]["expires"] == T0 + 1 + 600 and (FLAGS / (holds.LEDGER_NAME + ".bad")).read_text() == '{"msg": {"old-1": ', (rows, AP("msg")))
gone = holds.sweep(now=T0 + 1 + 601)
check("corrupt times file: none of them is permanent, the other source's key included: the sweep takes them all out", sorted(gone) == ["hub:old-3", "msg:new-1", "msg:old-1", "msg:old-2"] and AP("msg") == [] and AP("hub") == [], gone)
for bad_json in ("[1, 2]", '"x"', '{"msg": {"k": {"since": "soon"}}}', '{"msg": [1]}'):
    wipe(); (FLAGS / "held-api-msg.txt").write_text("k\n"); (FLAGS / holds.LEDGER_NAME).write_text(bad_json)
    holds.hold(["j"], ["msg"], 5, now=T0)
    check(f"a times file {bad_json!r}: set aside, the key already in the file gets a time", sorted(ROWS().get("msg", {})) == ["j", "k"] and (FLAGS / (holds.LEDGER_NAME + ".bad")).exists(), (ROWS(), list(FLAGS.iterdir())))
wipe()
# a release or a listing with a corrupt times file never leaves a key without an end either
holds.hold(["r-1"], ["msg"], 5, now=T0); (FLAGS / holds.LEDGER_NAME).write_text("not json")
check("list: a corrupt times file is read as no times, and is not moved by a read", [(r["key"], r["since"]) for r in holds.listing()["holds"]] == [("r-1", None)] and (FLAGS / holds.LEDGER_NAME).read_text() == "not json")
rel = holds.hold(["r-2"], ["msg"], 5, now=T0)
check("hold after it: both keys have a time", sorted(ROWS()["msg"]) == ["r-1", "r-2"], ROWS())
wipe()
# a key in the API's file with no time is given one by the sweep and then ends; with the setting at 0 it is left
(FLAGS / "held-api-msg.txt").write_text("orphan\n")
check("sweep: a key with no time in the API's file: not swept in the call that adopts it", holds.sweep(now=T0) == [] and ROWS()["msg"]["orphan"] == {"since": T0, "expires": T0 + 600}, ROWS())
check("sweep: …and swept when the setting's minutes have run out", holds.sweep(now=T0 + 599) == [] and holds.sweep(now=T0 + 601) == ["msg:orphan"] and AP("msg") == [] and not (FLAGS / holds.LEDGER_NAME).exists(), (AP("msg"), ROWS()))
(FLAGS / "held-api-hub.txt").write_text("orphan-2\n"); cfg.CFG.setdefault("client", {})["inbox_hold_minutes"] = 0
check("sweep: with [client] inbox_hold_minutes = 0 a key with no time is left, as before", holds.sweep(now=T0) == [] and holds.sweep(now=T0 + 10**7) == [] and AP("hub") == ["orphan-2"] and not (FLAGS / holds.LEDGER_NAME).exists())
cfg.CFG["client"].pop("inbox_hold_minutes"); wipe()
check("sweep: with nothing held it makes no file", holds.sweep(now=T0) == [] and mine() == [], mine())

# the setting is clamped
def setting(v):
    if v == "unset": cfg.CFG["client"].pop("inbox_hold_minutes", None)
    else: cfg.CFG["client"]["inbox_hold_minutes"] = v
    return holds.default_minutes()
clamp = {k: setting(v) for k, v in {"unset": "unset", "neg": -5, "word": "soon", "huge": 5000, "bool": True, "nan": float("nan"), "inf": float("inf"), "zero": 0, "str": "7", "two": 2.5, "day": 1440, "none": None}.items()}
check("default_minutes: unset, negative, a word, a bool, nan, inf, None → 10; above a day → 1440; 0 stays 0 (the operator's 'until released'); a number in a string counts",
      clamp == {"unset": 10.0, "neg": 10.0, "word": 10.0, "huge": 1440.0, "bool": 10.0, "nan": 10.0, "inf": 10.0, "zero": 0.0, "str": 7.0, "two": 2.5, "day": 1440.0, "none": 10.0}, clamp)
cfg.CFG["client"]["inbox_hold_minutes"] = -3
check("hold with no minutes and a negative setting: the default's 10 minutes, never forever", holds.hold(["c-1"], ["msg"], None, now=T0)["expires"] == T0 + 600)
cfg.CFG["client"]["inbox_hold_minutes"] = 10**6
check("hold with no minutes and a setting past a day: a day", holds.hold(["c-2"], ["msg"], None, now=T0)["expires"] == T0 + 86400)
cfg.CFG["client"].pop("inbox_hold_minutes"); holds.release(["c-1", "c-2"], ["msg"]); wipe()

# the API refuses 0 (a hold always ends), whatever its spelling; a fraction is allowed
for z in (0, 0.0, "0", "0.0", -0.0):
    code, out = holds.api_hold({"keys": ["z-key"], "minutes": z})
    check(f"api_hold: minutes {z!r} is refused with a 400 that says so", code == 400 and "0 is refused" in out["error"] and "1440" in out["error"] and AP("msg") is None, (code, out))
check("api_hold: a fraction of a minute is a hold", holds.api_hold({"keys": ["z-key"], "minutes": 0.5, "kinds": ["msg"]})[0] == 200 and ROWS()["msg"]["z-key"]["expires"] > 0)
holds.release(["z-key"], ["msg"])
check("api_hold: nan and inf are refused", all(holds.api_hold({"keys": ["z-key"], "minutes": m})[0] == 400 for m in (float("nan"), float("inf"), "nan", "inf")) and AP("msg") in (None, []))
with TestClient(app) as c4:
    r = c4.post("/client/inbox-hold", json={"keys": ["z-key"], "minutes": 0}, headers=HB)
    check("http: minutes 0 → 400, nothing held", r.status_code == 400 and "refused" in r.json()["error"] and AP("msg") in (None, []), r.text)
    check("http: a key with a line separator → 400", c4.post("/client/inbox-hold", json={"keys": ["a b"]}, headers=HB).status_code == 400)
wipe()

# the cap: 500 keys in one source's file
for i in range(25):
    code, out = holds.api_hold({"keys": [f"cap-{i}-{j}" for j in range(20)], "kinds": ["msg"], "minutes": 5})
    assert code == 200, (i, out)
check("cap: 500 keys are held in the API's msg file", len(AP("msg")) == 500, len(AP("msg")))
code, out = holds.api_hold({"keys": ["cap-over"], "kinds": ["msg"], "minutes": 5})
check("cap: the 501st key is a 400 that names the cap, and nothing is written", code == 400 and "500" in out["error"] and "cap-over" not in AP("msg") and "cap-over" not in ROWS()["msg"] and len(AP("msg")) == 500, (code, out))
check("cap: a key already held is a refresh, not a new key", holds.api_hold({"keys": ["cap-0-0", "cap-1-1"], "kinds": ["msg"], "minutes": 5})[0] == 200 and len(AP("msg")) == 500)
check("cap: a call that adds one new key among held ones is refused whole", holds.api_hold({"keys": ["cap-0-0", "cap-new"], "kinds": ["msg"], "minutes": 5})[0] == 400 and "cap-new" not in AP("msg"))
check("cap: the other source has its own count", holds.api_hold({"keys": ["cap-over"], "kinds": ["hub"], "minutes": 5})[0] == 200 and AP("hub") == ["cap-over"])
check("cap: a call for both kinds is refused whole when one is full, and writes neither", holds.api_hold({"keys": ["cap-both"], "minutes": 5})[0] == 400 and "cap-both" not in AP("hub") and "cap-both" not in AP("msg"))
holds.release(["cap-0-0"], ["msg"])
check("cap: a release makes room", holds.api_hold({"keys": ["cap-over-2"], "kinds": ["msg"], "minutes": 5})[0] == 200 and len(AP("msg")) == 500)
gone = holds.sweep(now=time.time() + 10**4)
check("cap: the sweep ends them all", len(gone) == 501 and AP("msg") == [] and AP("hub") == [], len(gone))
wipe()

# keys: anything that is not printable, and a key that cannot be written as UTF-8
for k in ("a b", "a\u0085b", "a‮b", "a​b", "a\ud800b", "\ud800", "a\x00b", "a\tb", "a b"):
    check(f"keys: {k!r} is refused with a 400", holds.api_hold({"keys": [k]})[0] == 400 and holds.api_release({"keys": [k]})[0] == 400 and not list(FLAGS.glob("*.txt")))
check("keys: ordinary names stay valid, spaces inside and non-ASCII letters included", holds.api_hold({"keys": ["site builder", "caf\u00e9-builder", "x" * 200]})[0] == 200)
holds.release(["site builder", "caf\u00e9-builder", "x" * 200], ["msg", "hub"]); wipe()
try:
    holds.hold(["fine", "\ud800"], ["msg"], 5, now=T0); failed = None
except ValueError as e:
    failed = e
check("hold: a key that cannot be encoded raises before anything is written (no file, no time, no temp file)", failed is not None and mine() == [], (failed, mine()))
try:
    holds._write(FLAGS / "w.txt", ["ok", "\ud800"]); failed = None
except UnicodeEncodeError as e:
    failed = e
check("_write: a key that cannot be encoded raises before the temp file exists, and the file is untouched", failed is not None and mine() == [], mine())
(FLAGS / "w.txt").mkdir()
try:
    holds._write(FLAGS / "w.txt", ["ok"]); failed = None
except OSError as e:
    failed = e
check("_write: a write that fails after the temp file is made removes it", failed is not None and mine() == ["w.txt"], mine())
(FLAGS / "w.txt").rmdir(); wipe()

# push.py: a delivery the server failed and a box with no token are retriable (4); a refusal of the line stays 2
real_msg = client.message
try:
    for status, out, want in ((400, "Delivery failed: the pane did not answer", 4), (401, f"no token on this machine ({client.TOKEN}): mint one on the server box and provision it", 4),
                              (400, "Refused: message longer than 20000", 2), (401, "unauthorized", 2), (404, "no such", 2), (403, "forbidden", 2), (500, "internal", 4), (0, "URLError", 4), (302, "moved", 4)):
        client.message = lambda to, text, sender, **kw: (status, out)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = push.deliver_server("work-new", "a line", "builder")
        check(f"push server mode: the server's {status} {out[:20]!r} → exit {want}", rc == want, rc)
finally:
    client.message = real_msg

# ================================================================= 12. a resume's hold cannot outlast its purpose: held-resume-<source>.txt is bound by [client] resume_hold_max_hours (default 6), through sweep_resume only
HR = "held-resume-msg.txt"; SEEN = lambda: json.loads((FLAGS / holds.RESUME_LEDGER_NAME).read_text()) if (FLAGS / holds.RESUME_LEDGER_NAME).exists() else None
H6 = 6 * 3600.0
class _Cap(logging.Handler):
    def __init__(self): super().__init__(); self.lines = []
    def emit(self, r): self.lines.append(r.getMessage())
def journal(fn):
    """The log lines of the inbox logger while fn runs (the suite switches logging off)."""
    cap = _Cap(); lg = logging.getLogger("stackshot.inbox"); lg.addHandler(cap); logging.disable(logging.NOTSET)
    try: return fn(), cap.lines
    finally: lg.removeHandler(cap); logging.disable(logging.CRITICAL)
wipe()
check("resume sweep: the default is six hours", holds.resume_max_hours() == 6.0 and holds.RESUME_MAX_HOURS == 6.0)
check("resume sweep: with nothing in the resume's files it makes no file", holds.sweep_resume(now=T0) == [] and not (FLAGS / holds.RESUME_LEDGER_NAME).exists())
put_file(HR, "r-a\nr-b\n")
check("resume sweep: a key seen for the first time starts its age, nothing is lifted", holds.sweep_resume(now=T0) == [] and SEEN() == {"msg": {"r-a": T0, "r-b": T0}} and lines(HR) == ["r-a", "r-b"], SEEN())
check("resume sweep: just under the age the key stays, its time unchanged", holds.sweep_resume(now=T0 + H6 - 1) == [] and lines(HR) == ["r-a", "r-b"] and SEEN()["msg"]["r-a"] == T0)
put_file(HR, "r-a\nr-b\nr-c\n")
holds.sweep_resume(now=T0 + H6 - 0.5)
out, jl = journal(lambda: holds.sweep_resume(now=T0 + H6))
check("resume sweep: past the age the old keys are lifted, the newer key stays, and the sweep says which", out == ["msg:r-a", "msg:r-b"] and lines(HR) == ["r-c"] and sorted(SEEN()["msg"]) == ["r-c"], (out, lines(HR), SEEN()))
check("resume sweep: a journal line names each key and its age", len(jl) == 2 and "msg:r-a" in jl[0] and "6.0 hours" in jl[0] and "msg:r-b" in jl[1] and "queued lines stay" in jl[0], jl)
check("resume sweep: the third key, first seen half a second later, is not lifted a minute later", holds.sweep_resume(now=T0 + H6 + 60) == [] and lines(HR) == ["r-c"])
out = holds.sweep_resume(now=T0 + H6 + H6)
check("resume sweep: …it goes when its own age is up, the file is left empty and the times file is removed", out == ["msg:r-c"] and lines(HR) == [] and SEEN() is None, (out, lines(HR), SEEN()))
wipe()

# only the hold goes: the queued line stays in the inbox and is handed out at the next take
iid = inbox.put(NAME, "a line a resume held", "msg", now=T0, sender="site-main")
put_file(HR, NAME + "\n"); holds.sweep_resume(now=T0)
check("resume sweep: while the key is held its line is not handed out", inbox.take({SID: NAME}, only_src="msg", now=T0 + 5) == [] and inbox.waiting("msg").get(NAME) == 1)
check("resume sweep: past the age the key is lifted and the queued line is still in the inbox", holds.sweep_resume(now=T0 + H6) == [f"msg:{NAME}"] and inbox.waiting("msg").get(NAME) == 1, inbox.waiting("msg"))
tk = inbox.take({SID: NAME}, only_src="msg", now=T0 + H6 + 1)
check("resume sweep: …and it is handed out whole at the next take, no line lost", len(tk) == 1 and tk[0]["ids"] == [iid] and "a line a resume held" in tk[0]["text"], tk)
inbox.ack([iid]); wipe()

# another tool's files are never touched, whatever their age; the API's own keys keep their own times
put_file("held-msg.txt", "mgr-1\n"); put_file("held-hub.txt", "mgr-hub\n"); put_file(HR, "r-a\n"); put_file("held-resume-hub.txt", "r-hub\n")
holds.hold(["own-1"], ["msg", "hub"], 0, now=T0)
others = ("held-msg.txt", "held-hub.txt", "held-api-msg.txt", "held-api-hub.txt", holds.LEDGER_NAME); b0 = snap(*others)
holds.sweep_resume(now=T0)
out = holds.sweep_resume(now=T0 + 10**7)
check("resume sweep: another tool's files and the API's files and times keep their bytes and mtime", snap(*others) == b0, (snap(*others), b0))
check("resume sweep: both sources' resume files are bound, each key lifted from its own", sorted(out) == ["hub:r-hub", "msg:r-a"] and lines(HR) == [] and lines("held-resume-hub.txt") == [] and AP("msg") == ["own-1"], (out, lines(HR)))
holds.release(["own-1"], ["msg", "hub"]); wipe()

# a key that left the file loses its time (a resume lifted it), and a key that comes back starts afresh
put_file(HR, "r-a\nr-b\n"); holds.sweep_resume(now=T0)
put_file(HR, "r-b\n"); holds.sweep_resume(now=T0 + 3600)
check("resume sweep: a key that left the file loses its time", SEEN() == {"msg": {"r-b": T0}}, SEEN())
put_file(HR, "r-a\nr-b\n"); out = holds.sweep_resume(now=T0 + H6)
check("resume sweep: a key that came back is a new key with a new age; the one that stayed is lifted", out == ["msg:r-b"] and lines(HR) == ["r-a"] and SEEN() == {"msg": {"r-a": T0 + H6}}, (out, lines(HR), SEEN()))
put_file(HR, ""); holds.sweep_resume(now=T0 + H6 + 1)
check("resume sweep: the times file is removed when no key is tracked", SEEN() is None, mine())
wipe()

# an unreadable times file reads as no times: nothing lifted that time, every key starts its age then
for junk in (b"not json", b"[]", b'{"msg": []}', b'{"msg": {"r-a": "soon"}}', b'{"msg": {"r-a": true}}', b"\xff\xfe"):
    put_file(HR, "r-a\n"); (FLAGS / holds.RESUME_LEDGER_NAME).write_bytes(junk)
    out, jl = journal(lambda: holds.sweep_resume(now=T0 + 10**7))
    check(f"resume sweep: a times file {junk!r} lifts nothing, the key starts its age now, the file is replaced", out == [] and lines(HR) == ["r-a"] and SEEN() == {"msg": {"r-a": T0 + 10**7}} and any("no times" in x for x in jl), (out, SEEN(), jl))
    check(f"resume sweep: …and the key goes when that new age is up {junk!r}", holds.sweep_resume(now=T0 + 10**7 + H6) == ["msg:r-a"] and SEEN() is None)
    wipe()

# a later resume holds a key afresh (it found it queued and could not verify it): the age starts again; a key it only keeps keeps its age
put_file(HR, "r-seen\nr-kept\n"); holds.sweep_resume(now=T0)
with holds.locked():
    holds.resume_restart("msg", ["r-seen"], now=T0 + 5 * 3600)
check("resume restart: a key held afresh starts its age again, a key only kept keeps the age it had", SEEN() == {"msg": {"r-seen": T0 + 5 * 3600, "r-kept": T0}}, SEEN())
out = holds.sweep_resume(now=T0 + H6 + 60)
check("resume restart: …so the kept key is lifted at six hours and the re-held one lives on", out == ["msg:r-kept"] and lines(HR) == ["r-seen"], (out, lines(HR)))
wipe()

# the real resume tool: a key it finds queued and cannot verify is held afresh and starts its age again; a key it only keeps does not
(T / "listed-none.txt").write_text("")
def resume():
    r = subprocess.run([sys.executable, RQ, "resume", "--source", "msg", "--sessions", str(T / "listed-none.txt"), "--wait", "1"], capture_output=True, text=True, env={**os.environ})
    return r.returncode, json.loads(r.stdout or "{}"), r.stderr
iid = inbox.put("held-pane", "waits for a resume", "msg", now=time.time(), sender="site-main")
rc, q, err = resume()
check("resume tool: it holds the queued unverified key and records the key's age", rc == 0 and q.get("held_sessions") == ["held-pane"] and lines(HR) == ["held-pane"] and abs(SEEN()["msg"]["held-pane"] - time.time()) < 60, (rc, q, err[-300:], SEEN()))
led = SEEN(); led["msg"]["held-pane"] = time.time() - 7 * 3600; (FLAGS / holds.RESUME_LEDGER_NAME).write_text(json.dumps(led))
rc, q, err = resume()
check("resume tool: a second resume that finds the key queued holds it afresh: its age starts again", rc == 0 and lines(HR) == ["held-pane"] and abs(SEEN()["msg"]["held-pane"] - time.time()) < 60, (rc, q, err[-300:], SEEN()))
check("resume tool: …so the sweep keeps it", holds.sweep_resume() == [] and lines(HR) == ["held-pane"])
inbox.ack([iid])
put_file(HR, "held-pane\nkept-only\n"); led = {"msg": {"held-pane": time.time() - 7 * 3600, "kept-only": time.time() - 7 * 3600}}; (FLAGS / holds.RESUME_LEDGER_NAME).write_text(json.dumps(led))
rc, q, err = resume()
check("resume tool: keys it only keeps (nothing queued, nothing verified) keep their age", rc == 0 and lines(HR) == ["held-pane", "kept-only"] and SEEN()["msg"]["held-pane"] < time.time() - 6.9 * 3600 and SEEN()["msg"]["kept-only"] < time.time() - 6.9 * 3600, (rc, q, err[-300:], lines(HR), SEEN()))
check("resume tool: …and the sweep lifts both", sorted(holds.sweep_resume()) == ["msg:held-pane", "msg:kept-only"] and lines(HR) == [] and SEEN() is None, (lines(HR), SEEN()))
check("resume tool: a later resume still behaves: with nothing held and nothing queued it writes an empty file", resume()[0] == 0 and lines(HR) == [])
wipe()

# the lock: the resume's write and the sweep's lift are one step each under the same lock, so while another holder has it neither writes anything, and both go on when it is released
import threading
LOCKF = FLAGS / ".holds-api.lock"
def at_lock(p):
    """True once the child has the lock file open (it opens it right before it waits for the lock); without /proc a short wait stands in."""
    try:
        return any(os.readlink(f"/proc/{p.pid}/fd/{fd}").endswith(".holds-api.lock") for fd in os.listdir(f"/proc/{p.pid}/fd"))
    except OSError:
        return False
def wait_blocked(p):
    end = time.time() + 60
    while time.time() < end and p.poll() is None and not at_lock(p): time.sleep(0.02)
    if not os.path.isdir("/proc"): time.sleep(3)
    time.sleep(0.3)
put_file(HR, "r-a\nr-b\n"); iid_a = inbox.put("held-pane", "waits for a resume", "msg", now=time.time(), sender="site-main")
lk = holds.locked(); lk.__enter__(); locked_now = True
p = subprocess.Popen([sys.executable, RQ, "resume", "--source", "msg", "--sessions", str(T / "listed-none.txt"), "--wait", "1"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env={**os.environ})
try:
    wait_blocked(p)
    still, mid_hold, mid_seen = p.poll() is None, lines(HR), SEEN()
    lk.__exit__(None, None, None); locked_now = False
    out, err = p.communicate(timeout=120)
finally:
    if locked_now: lk.__exit__(None, None, None)
    if p.poll() is None: p.kill(); p.wait()
check("resume tool: while another holder has the lock it writes nothing and waits", still and mid_hold == ["r-a", "r-b"] and mid_seen is None, (still, mid_hold, mid_seen))
check("resume tool: …and once the lock is released it writes the hold file and the ages", p.returncode == 0 and lines(HR) == ["held-pane", "r-a", "r-b"] and sorted(SEEN()["msg"]) == ["held-pane", "r-a", "r-b"], (p.returncode, lines(HR), SEEN(), err[-300:]))
inbox.ack([iid_a]); wipe()

put_file(HR, "r-a\n"); holds.sweep_resume(now=T0)
lk = holds.locked(); lk.__enter__(); locked_now = True; res = {}
def lift():
    try: res["out"] = holds.sweep_resume(now=T0 + H6)
    except BaseException as e: res["err"] = e
th = threading.Thread(target=lift, daemon=True); th.start()
try:
    th.join(1.5)
    alive, mid_hold, mid_seen = th.is_alive(), lines(HR), SEEN()
finally:
    if locked_now: lk.__exit__(None, None, None)
    th.join(30)
check("resume sweep: while another holder has the lock it lifts nothing and waits", alive and mid_hold == ["r-a"] and mid_seen == {"msg": {"r-a": T0}}, (alive, mid_hold, mid_seen))
check("resume sweep: …and once the lock is released it lifts the key", res.get("out") == ["msg:r-a"] and lines(HR) == [] and SEEN() is None, (res, lines(HR), SEEN()))
wipe()

# resume_restart: a key whose time is in the file but that left the hold file loses it, a key new to the file gets the time of the call
put_file(HR, "r-a\nr-b\n"); holds.sweep_resume(now=T0)
put_file(HR, "r-b\nr-c\n")
with holds.locked():
    holds.resume_restart("msg", [], now=T0 + 100)
check("resume restart: a key that left the file drops its time, a key that stayed keeps it, a new key gets the call's time", SEEN() == {"msg": {"r-b": T0, "r-c": T0 + 100}}, SEEN())
wipe()

# the lock cannot be taken (its path is a directory): the resume still writes its hold file and exits 0, with one line on stderr, and records no ages
LOCKF.unlink(missing_ok=True); LOCKF.mkdir()
try:
    iid = inbox.put("held-pane", "waits for a resume", "msg", now=time.time(), sender="site-main")
    put_file(HR, "r-a\n")
    rc, q, err = resume()
finally:
    LOCKF.rmdir()
check("resume tool: with the lock unusable it still writes the hold file and exits 0", rc == 0 and q.get("held_sessions") == ["held-pane"] and lines(HR) == ["held-pane", "r-a"], (rc, q, lines(HR), err[-300:]))
check("resume tool: …says so in one line on stderr and records no ages", err.count("without the lock") == 1 and SEEN() is None, (err[-300:], SEEN()))
inbox.ack([iid]); wipe()

# the setting
def rsetting(v):
    if v == "unset": cfg.CFG["client"].pop("resume_hold_max_hours", None)
    else: cfg.CFG["client"]["resume_hold_max_hours"] = v
    return holds.resume_max_hours()
rclamp = {k: rsetting(v) for k, v in {"unset": "unset", "neg": -1, "word": "soon", "bool": True, "nan": float("nan"), "inf": float("inf"), "zero": 0, "str": "2", "frac": 0.5, "none": None}.items()}
check("resume_max_hours: unset, negative, a word, a bool, nan, inf, None → 6; 0 stays 0 (never lifted); a number in a string counts", rclamp == {"unset": 6.0, "neg": 6.0, "word": 6.0, "bool": 6.0, "nan": 6.0, "inf": 6.0, "zero": 0.0, "str": 2.0, "frac": 0.5, "none": 6.0}, rclamp)
cfg.CFG["client"]["resume_hold_max_hours"] = 1
put_file(HR, "s-1\n"); holds.sweep_resume(now=T0)
check("resume sweep: the setting is the age (1 hour)", holds.sweep_resume(now=T0 + 3599) == [] and holds.sweep_resume(now=T0 + 3600) == ["msg:s-1"])
cfg.CFG["client"]["resume_hold_max_hours"] = 0
put_file(HR, "s-2\n"); holds.sweep_resume(now=T0)
check("resume sweep: with the setting at 0 nothing is ever lifted", holds.sweep_resume(now=T0 + 10**9) == [] and lines(HR) == ["s-2"])
cfg.CFG["client"].pop("resume_hold_max_hours"); wipe()

# the minute tick runs it, and a failure of it never stops the tick
ticks = []; real = (fe._clients.tick, fe._inbox_holds.sweep, fe._inbox_holds.sweep_resume, fe.inbox_flag_tick)
try:
    fe._clients.tick = lambda: ticks.append("clients"); fe._inbox_holds.sweep = lambda: ticks.append("sweep"); fe._inbox_holds.sweep_resume = lambda: (ticks.append("resume"), 1 / 0); fe.inbox_flag_tick = lambda: ticks.append("flag")
    with contextlib.redirect_stderr(io.StringIO()): fe.clients_tick()
finally:
    fe._clients.tick, fe._inbox_holds.sweep, fe._inbox_holds.sweep_resume, fe.inbox_flag_tick = real
check("the minute tick calls the resume sweep after the API's, and the flag pass still runs when it fails", ticks == ["clients", "sweep", "resume", "flag"], ticks)

# docs and example config
ex = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"); cf = pathlib.Path(STACK, "docs/configuration-integrations.md").read_text(encoding="utf-8")
doc = pathlib.Path(STACK, "docs/inbox-holds.md").read_text(encoding="utf-8"); puller = pathlib.Path(STACK, "docs/puller-and-inbox.md").read_text(encoding="utf-8")
check("docs: the setting and its side file are documented in the example config, the configuration page, the hold page and the puller page",
      "resume_hold_max_hours = 6" in ex and "`client.resume_hold_max_hours` | `6`" in cf and "`client.resume_hold_max_hours` | `6`" in doc and "holds-resume.json" in doc and "holds-resume.json" in puller and "resume_hold_max_hours" in puller)

# the docs say what the code does
doc = pathlib.Path(STACK, "docs/inbox-holds.md").read_text(encoding="utf-8"); puller = pathlib.Path(STACK, "docs/puller-and-inbox.md").read_text(encoding="utf-8")
check("docs: the hold page names the 0 refusal, the 500-key cap, the minute's lag, and the exact calls (message, ack) beside the scoped ones (poll, drain)",
      all(x in doc for x in ("`0` is refused", "at most 500 keys", "up to a minute", "`message`", "`ack`", "`poll` and `drain` are scoped")) and "other client calls" not in doc, doc[-900:])
check("docs: the puller page counts three hold files", "Three hold files per source" in puller and "Two hold files" not in puller and "union** of the three" in puller)
wipe()


print(("ok" if not fails else "FAILED") + f": inbox hold api scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
