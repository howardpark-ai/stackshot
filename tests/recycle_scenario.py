"""Scenario test for the waits-for-recycle field — fixture data, no live store, no network.

Covers: update(recycle=true) sets metadata.recycle with the moment it was set, owes no page and leaves the state clock alone;
get shows it; recycle with clear_recycle, and recycle on a completed item, are refused; clear_recycle and a completion take it
off; sala's end-of-recycle report (the client write `recycled`) clears it on the open items it covered and tells each owner
once, keeps it on items flagged after the sweep began, on items whose owner sala skipped and on items owned on another
machine, and clears a held item without releasing it; recycle-due, a script's way to mark a recycle as due on an existing item (by id, or the open items anchored to a pull
request; it never files one, after), and create refusing an item that only asks for a recycle; release.sh --recycle; recycle-wanted, the count sala's watchdog asks for (not held, or held for the recycle alone; not passed over by the last recycle); a second
recycled report for the same start time (sala retrying a skipped pane) clearing what the first kept; the same over HTTP in-process; client.py recycled reads the
fleet tool's variables under [client] recycle_env_prefix (none when it is unset) and never fails. The instance names its fleet tool the way the example fleet does
([fleet] tool_name "sala", recycle_when_idle "sala recycle --when-idle"); with those keys unset no text names a tool or a command, and release.sh's
idle request runs nothing.

    tests/run-suite recycle        → exit 0 / 1"""
import json, os, re, sys, pathlib, subprocess, tempfile, time, logging, io, contextlib
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="recycletest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "unset.toml").write_text(toml, encoding="utf-8")                  # the fleet keys at the example's values (unset), for release.sh's idle request below
for key, val in (("tool_name", "sala"), ("recycle_when_idle", "sala recycle --when-idle"), ("recycle_env_prefix", "SALA_RECYCLE_")):   # the example fleet tool
    toml, n = re.subn(rf'(?m)^{key} = ""', f'{key} = "{val}"', toml); assert n == 1, key
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "fleet/b", "state/anchor-hub", "brain/projects"): (T / d).mkdir(parents=True)
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(("home-here", "home-skipped", "home-away", "home-held"), 1)}
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/b/machine.json").write_text(json.dumps({"letter": "b", "fleet": "otherbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({U[n]: {"name": n, "machine": "a", "seen": now} for n in ("home-here", "home-skipped", "home-held")}))
(T / "fleet/b/sessions.json").write_text(json.dumps({U["home-away"]: {"name": "home-away", "machine": "b", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-here", "status": "active", "board": [], "board_open": 0}}}))
def say(i):
    """Oliver's words on item i, newer than its last move: a time wait carries them, the wake being too far for a wait_basis"""
    d = json.loads((T / f"store/a/{i}.json").read_text())
    d["metadata"].setdefault("answers", []).append({"ts": time.time() + 1, "kind": "comment", "text": "park it until the new year", "via": "board"})
    (T / f"store/a/{i}.json").write_text(json.dumps(d))
def item(i, owner, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "A thing. It lives here. Done when done.",
                                                       "status": "open", "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                       "metadata": {"owner": U[owner], **({} if {"needs", "mover", "then", "hold", "after"} & set(meta) else {"mover": U[owner]}), "project": "projects/alpha", **meta}}))
for i, o in ((1, "home-here"), (2, "home-here"), (3, "home-skipped"), (4, "home-away"), (5, "home-held"), (6, "home-here"), (7, "home-here")):
    item(i, o)
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:400]}" if got is not None else ""))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())

from stackshot.web import server
from stackshot.service import recycle as recycle_svc
from stackshot.service import update as _update_svc
from stackshot.waits import waiting as _wt
from stackshot.core import config as _cfg
from fastmcp.exceptions import ToolError
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.model import field_gates as _fg
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.tools import complete as _wt_complete
from stackshot.web.tools import create as _wt_create
from stackshot.web.tools import get as _wt_get
from stackshot.web.tools import update as _wt_update
from stackshot.web.auth import oauth as _oauth
from stackshot.service import telling
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_wt.cap_needs_owner = lambda: False     # this scenario sets waits far ahead; the cap on a session's wake has its own scenario (waiting)
told = []
telling.tell_woken = lambda gid, owner, note, tag="wake": told.append((tag, owner, note))
owed = lambda: json.dumps(_web_page_debts._owed_load())

# ---- 1. setting, showing, refusing, clearing
out = _update_svc._update("a1", recycle=True)
m = rd(1)["metadata"]
check("recycle=true sets the field and when", m.get("recycle") is True and isinstance(m.get("recycle_at"), float) and m["recycle_at"] >= now, m)
check("it is a filing edit: the state clock and the confirm stay", rd(1)["state_updated"] == now - 3600 and rd(1)["confirmed"] == now - 3600, rd(1))
check("it owes no page", "a1" not in owed(), owed())
check("the update's reply shows it", "recycle: waits for a pane recycle (since " in out, out)
check("get shows it", "recycle: waits for a pane recycle" in _wt_get.stackshot_get("a1"))
for kw, name in (({"recycle": True, "clear_recycle": True}, "recycle with clear_recycle is refused"),):
    try: _update_svc._update("a1", **kw); check(name, False)
    except ToolError: check(name, True)
_update_svc._update("a7", recycle=True); _update_svc._update("a7", clear_recycle=True)
check("clear_recycle takes it off", "recycle" not in rd(7)["metadata"] and "recycle_at" not in rd(7)["metadata"], rd(7)["metadata"])
_update_svc._update("a6", recycle=True); _wt_complete.stackshot_complete("a6", outcome="done", reason="the work landed", description="- The test item's work is in place")
check("a completion takes it off", rd(6)["status"] == "completed" and "recycle" not in rd(6)["metadata"], rd(6)["metadata"])
try: _update_svc._update("a6", recycle=True); check("a completed item cannot wait for a recycle", False)
except ToolError: check("a completed item cannot wait for a recycle", True)
check("get no longer shows it on a cleared item", "recycle:" not in _wt_get.stackshot_get("a7"))

# ---- 2. sala reports a recycle
for i in (2, 3, 4): _update_svc._update(f"a{i}", recycle=True)
_update_svc._update("a5", recycle=True); _update_svc._update("a5", hold=True)
started = time.time(); time.sleep(0.01)
_update_svc._update("a2", recycle=True)            # flagged again after the sweep began: the recycle does not cover it
told.clear()
r = recycle_svc._recycled("testbox", "recycle", started, "partial", ["home-skipped"])
check("cleared: the item flagged before, owned here", "a1" in r["cleared"] and "recycle" not in rd(1)["metadata"], r)
check("cleared: the held item, whose hold waited only for the recycle, is released with it", "a5" in r["cleared"] and "recycle" not in rd(5)["metadata"] and "hold" not in rd(5)["metadata"], rd(5)["metadata"])
kept = {k["item"]: k["why"] for k in r["kept"]}
check("kept: flagged after the recycle began", kept.get("a2") == "flagged after the recycle began" and rd(2)["metadata"].get("recycle") is True, r)
check("kept: its owner was skipped", kept.get("a3") == "its mover was not relaunched" and rd(3)["metadata"].get("recycle") is True, r)
check("kept: its owner is on another machine", kept.get("a4", "").startswith("its mover is not on") and rd(4)["metadata"].get("recycle") is True, r)
check("one line per target, tagged: each item's mover is told of its own item (the keeper stands in for no one)", sorted(o for _, o, _ in told) == sorted([U["home-here"], U["home-held"]]) and all(t == "recycle" for t, _, _ in told), told)
here = next(n for _, o, n in told if o == U["home-here"] and "a1" in n); held = next(n for _, o, n in told if o == U["home-held"] and "a5" in n)
check("the owner's line names its item and says resume", "recycle you waited for has run (testbox" in here and "re-read a1 and resume" in here and ", partly" in here, here)
check("the mover's line for the held item says the hold went with the recycle", "re-read a5 and resume" in held and "a5 waited only for the recycle and is released from hold." in held, held)
check("the recycle clears without a state change", rd(1)["state_updated"] == now - 3600, rd(1))
check("wanted: only the item flagged after the last recycle began (the skipped owner's item is not)", recycle_svc._recycle_wanted("testbox") == ["a2"], recycle_svc._recycle_wanted("testbox"))
say(5); _update_svc._update("a5", hold=True, wake="2099-01-02"); _update_svc._update("a5", recycle=True)            # held again (with a wake), and flagged again
check("wanted: a held item is not counted", recycle_svc._recycle_wanted("testbox") == ["a2"], recycle_svc._recycle_wanted("testbox"))
check("wanted: a machine with no recycle on record counts its owners' items", recycle_svc._recycle_wanted("otherbox") == ["a4"], recycle_svc._recycle_wanted("otherbox"))
told.clear()
r = recycle_svc._recycled("otherbox", "reboot", 0, "ok", [])
check("a reboot on the other machine clears its owner's item (started 0 = now); the line goes to the page's keeper, naming the owner", r["cleared"] == ["a4"]
      and told[0][1] == U["home-away"] and "the reboot you waited for has run (otherbox" in told[0][2] and "re-read a4 and resume" in told[0][2], (r, told))

# ---- 3. over HTTP, with the machine's token
from stackshot.fleet import client
tok = open(client.mint("testbox")).read().strip()
from starlette.testclient import TestClient
app = server.mcp.http_app()
with TestClient(app) as c:
    h = {"Authorization": "Bearer " + tok}
    res = c.post("/client/recycled", json={"kind": "recycle", "started": time.time() + 5, "result": "ok", "skipped": "home-skipped"}, headers=h)
    check("POST /client/recycled answers its counts", res.status_code == 200 and "a2" in res.json()["cleared"] and any(k["item"] == "a3" for k in res.json()["kept"]), res.text)
    res = c.post("/client/recycled", json={"kind": "restart"}, headers=h)
    check("an unknown kind is refused", res.status_code == 400, res.text)
    res = c.get("/client/recycle-wanted", headers=h)
    check("GET /client/recycle-wanted answers \"<count> <ids>\"", res.status_code == 200 and res.text == "0", res.text)
    recycle_svc._last_recycle = lambda m: 0.0; _update_svc._update("a1", recycle=True)
    res = c.get("/client/recycle-wanted", headers=h)
    check("and lists the ids after the count, each with the second its recycle was asked for", res.status_code == 200
          and res.text == f"2 a1@{int(rd(1)['metadata']['recycle_at'])} a3@{int(rd(3)['metadata']['recycle_at'])}", res.text)
    res = c.get("/client/puller-lag", headers=h)
    check("GET /client/puller-lag answers 200 with plain lines (here: none or some)", res.status_code == 200 and all(len(l.split()) == 3 for l in res.text.splitlines()), res.text)
    res = c.post("/client/recycled", json={"kind": "recycle"})
    check("no token, no write", res.status_code == 401, res.text)

# ---- 4. the client verb sala's hook runs
client.get = lambda what, key="", timeout=10.0: (200, "2 a1@1700000000~salamander:pr4 a3\n") if what == "recycle-wanted" else (404, "")
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = client.main(["client.py", "recycle-wanted"])
check("client.py recycle-wanted prints the count and the tokens as the server sent them", rc == 0 and buf.getvalue() == "2 a1@1700000000~salamander:pr4 a3\n", buf.getvalue())
# puller-lag: sala's watchdog provisions the boxes whose puller is behind
from stackshot.fleet import clients as _cl
_st = {"machines": {"box-c": {"fleet": "box-c", "puller_version": "2"}, "box-e": {"fleet": "box-e", "puller_version": "3"},
                    "box-a": {"fleet": "box-a", "puller_version": _cl.puller_current()}, "home-new": {"fleet": "home-new"},
                    "home-ahead": {"fleet": "home-ahead", "puller_version": "99"}}, "sessions": {}}
check("puller-lag: the boxes behind puller.py's VERSION, by hostname; current, ahead and never-reported boxes left out",
      _cl.puller_lag(_st) == [("box-c", "2", _cl.puller_current()), ("box-e", "3", _cl.puller_current())], _cl.puller_lag(_st))
_cl.LAG_FLAG = pathlib.Path(_scratch.mkdtemp()) / "puller-lag"
check("flag: first write lists the lagging boxes", _cl.flag_lag(_st) and _cl.LAG_FLAG.read_text() == f"box-c 2 {_cl.puller_current()}\nbox-e 3 {_cl.puller_current()}\n", _cl.LAG_FLAG.read_text())
check("flag: unchanged lines → the file is not rewritten (the path unit fires once per change)", not _cl.flag_lag(_st))
_st["machines"]["box-c"]["puller_version"] = _cl.puller_current()
check("flag: a box catches up → rewritten without it", _cl.flag_lag(_st) and _cl.LAG_FLAG.read_text() == f"box-e 3 {_cl.puller_current()}\n", _cl.LAG_FLAG.read_text())
_st["machines"]["box-e"]["puller_version"] = _cl.puller_current()
check("flag: every box current → an empty file, still there", _cl.flag_lag(_st) and _cl.LAG_FLAG.exists() and _cl.LAG_FLAG.read_text() == "")
client.get = lambda what, key="", timeout=10.0: (200, "box-c 2 5\nbox-e 3 5\n") if what == "puller-lag" else (404, "")
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = client.main(["client.py", "puller-lag"])
check("client.py puller-lag prints one line per box", rc == 0 and buf.getvalue() == "box-c 2 5\nbox-e 3 5\n", buf.getvalue())
client.get = lambda what, key="", timeout=10.0: (200, "")
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = client.main(["client.py", "puller-lag"])
check("every box current: prints nothing, exit 0", rc == 0 and buf.getvalue() == "", repr(buf.getvalue()))
client.get = lambda *a, **k: (0, "URLError: refused")
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = client.main(["client.py", "puller-lag"])
check("puller-lag: an unreachable server prints nothing and exits 0", rc == 0 and buf.getvalue() == "", buf.getvalue())
client.get = lambda *a, **k: (0, "URLError: refused")
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = client.main(["client.py", "recycle-wanted"])
check("an unreachable server prints nothing and exits 0", rc == 0 and buf.getvalue() == "", buf.getvalue())
sent = []
client.post = lambda what, body, timeout=20.0: (sent.append((what, body)), (200, {"cleared": ["a9"], "kept": [{"item": "a8", "why": "its mover was not relaunched"}], "told": []}))[1]
os.environ.update(SALA_RECYCLE_KIND="reboot", SALA_RECYCLE_STARTED="1760000000", SALA_RECYCLE_RESULT="partial", SALA_RECYCLE_SKIPPED="home-a home-b")
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = client.main(["client.py", "recycled"])
check("client.py recycled reads sala's variables", rc == 0 and sent[-1] == ("recycled", {"kind": "reboot", "started": 1760000000.0, "result": "partial", "skipped": ["home-a", "home-b"]}), sent)
check("and prints one line", buf.getvalue().count("\n") == 1 and "1 item(s) no longer wait" in buf.getvalue() and "a8: its mover was not relaunched" in buf.getvalue(), buf.getvalue())
with contextlib.redirect_stdout(io.StringIO()): client.main(["client.py", "recycled", "--kind", "recycle", "--since", "5"])
check("flags override the variables", sent[-1][1]["kind"] == "recycle" and sent[-1][1]["started"] == 5.0, sent[-1])
os.environ["SALA_RECYCLE_FLAG_AT"] = "1760000123.5"       # sala's per-flag call (contract 19): the flag's time rides along
with contextlib.redirect_stdout(io.StringIO()): client.main(["client.py", "recycled"])
check("client.py recycled sends flag_at from SALA_RECYCLE_FLAG_AT", sent[-1] == ("recycled", {"kind": "reboot", "started": 1760000000.0, "result": "partial",
      "skipped": ["home-a", "home-b"], "flag_at": 1760000123.5}), sent[-1])
with contextlib.redirect_stdout(io.StringIO()): client.main(["client.py", "recycled", "--flag-at", "77"])
check("--flag-at overrides the variable", sent[-1][1].get("flag_at") == 77.0, sent[-1])
os.environ["SALA_RECYCLE_FLAG_AT"] = "not a time"
with contextlib.redirect_stdout(io.StringIO()): client.main(["client.py", "recycled"])
check("a FLAG_AT that is no number is left out, like an unset one", "flag_at" not in sent[-1][1] and sent[-1][1]["started"] == 1760000000.0, sent[-1])
del os.environ["SALA_RECYCLE_FLAG_AT"]
with contextlib.redirect_stdout(io.StringIO()): client.main(["client.py", "recycled"])
check("client.py recycled omits flag_at when SALA_RECYCLE_FLAG_AT is unset (an older sala)", "flag_at" not in sent[-1][1], sent[-1])
client._cfg.CFG["client"]["recycle_env_prefix"] = ""
with contextlib.redirect_stdout(io.StringIO()): client.main(["client.py", "recycled"])
check("[client] recycle_env_prefix unset: the variables are not read, the defaults stand", sent[-1] == ("recycled", {"kind": "recycle", "started": 0.0, "result": "ok", "skipped": []}), sent[-1])
client._cfg.CFG["client"]["recycle_env_prefix"] = "SALA_RECYCLE_"
client.post = lambda *a, **k: (0, "URLError: refused")
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = client.main(["client.py", "recycled"])
check("an unreachable server still exits 0, with one line", rc == 0 and "recycle not reported [0]" in buf.getvalue(), buf.getvalue())
def boom(*a, **k): raise RuntimeError("x")
client.post = boom
with contextlib.redirect_stdout(io.StringIO()): rc = client.main(["client.py", "recycled"])
check("an exception still exits 0", rc == 0)

# ---- 5. recycle-due: a script marks a recycle as due on an existing item,
# by id or through the pull request it is anchored to, and never files one (and it is not an item)
def _no_identity(): raise ToolError("Refused: unknown identity is not allowed on this board")
_oauth._who = _no_identity                         # as with auth on and no signed-in caller: the client path must not need one
nfiles = lambda: len(list((T / "store").glob("?/*.json")))
item(8, "home-here"); item(9, "home-skipped")
PR = "https://github.com/example-owner/stackshot/pull/11"
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": PR, "items": ["a8", "a9"], "added": 1, "by": "t"},
                                                                     {"url": "https://github.com/example-owner/stackshot/pull/12", "items": None, "added": 1, "by": "t"}]}))
_update_svc._update("a1", clear_recycle=True)
with TestClient(app) as c:
    h = {"Authorization": "Bearer " + tok}
    n0 = nfiles()
    res = c.post("/client/recycle-due", json={"pr": PR + "/files"}, headers=h)
    d = res.json() if res.status_code == 200 else {}
    check("--pr: the open items anchored to the PR wait for a recycle, with no signed-in caller", res.status_code == 200
          and [(x["item"], x["action"]) for x in d.get("items", [])] == [("a8", "set"), ("a9", "set")]
          and rd(8)["metadata"].get("recycle") is True and rd(9)["metadata"].get("recycle") is True, res.text)
    check("--pr: the owners come back", [x["owner"] for x in d.get("items", [])] == ["home-here", "home-skipped"], d)
    res = c.post("/client/recycle-due", json={"pr": PR}, headers=h)
    check("--pr again: already, nothing changes", [x["action"] for x in res.json().get("items", [])] == ["already", "already"], res.text)
    say(9); _update_svc._update("a9", hold=True, wake="2099-01-02"); _update_svc._update("a9", clear_recycle=True)
    res = c.post("/client/recycle-due", json={"pr": PR}, headers=h)
    check("--pr: a held item is marked and reported as held", [(x["item"], x["action"], x["held"]) for x in res.json().get("items", [])] == [("a8", "already", False), ("a9", "set", True)], res.text)
    at_before = rd(1)["state_updated"]
    res = c.post("/client/recycle-due", json={"item": "A1"}, headers=h)
    check("--item: that item waits for a recycle, leaving the state clock", res.status_code == 200 and res.json()["items"][0]["item"] == "a1"
          and res.json()["items"][0]["action"] == "set" and rd(1)["metadata"].get("recycle") is True and rd(1)["state_updated"] == at_before, res.text)
    for body, name, want in (({"pr": "https://github.com/example-owner/stackshot/pull/12"}, "a PR anchored only project-wide", "sala recycle --when-idle"),
                             ({"pr": "https://github.com/example-owner/stackshot/pull/14"}, "a PR no item is anchored to", "no open item is anchored to"),
                             ({"pr": "https://example.com/x"}, "a --pr that is not a PR URL", "GitHub pull request URL"),
                             ({"item": "a6"}, "a completed item", "is completed"),
                             ({"item": "a1", "pr": PR}, "both --item and --pr", "one of them"),
                             ({}, "neither", "never files an item"),
                             ({"page": "projects/alpha", "owner": "home-here", "subject": "[home] Load the new plugin skills on box-a"}, "the old filing form", "never files an item")):
        res = c.post("/client/recycle-due", json=body, headers=h)
        check(f"refused: {name}", res.status_code == 400 and res.json().get("error", "").startswith("Refused") and want in res.json().get("error", ""), res.text)
    check("recycle-due never filed an item", nfiles() == n0, nfiles() - n0)
    res = c.post("/client/recycle-due", json={"item": "a1"})
    check("no token, no write", res.status_code == 401, res.text)
for name, call in (("create", lambda: _wt_create.stackshot_create(subject="[home] y", description="- A thing", project="projects/alpha", owner="home-here")),
                   ("update", lambda: _wt_update.stackshot_update("a1", next="x")), ("complete", lambda: _wt_complete.stackshot_complete("a1", outcome="done", reason="the work landed", description="- The test item's work is in place"))):
    try: call(); check(f"the {name} tool still checks the identity", False)
    except ToolError as e: check(f"the {name} tool still checks the identity", "unknown identity" in str(e), str(e))

# ---- 5b. create refuses an item that only asks for a recycle (after); update's recycle parameter says where a recycle goes
_web_page_debts._refuse_if_owing = lambda debtor: None
for subj in ("[home] Relaunch every pane so the connector's new parameters load", "[home] Recycle the sessions on box-a",
             "[home] Restart all panes after the plugin update", "[home] Load the new skills: re-launch the Claude sessions"):
    try: _wt_create._create(subject=subj, description="- A thing", project="projects/alpha", owner="home-here"); check(f"create refuses {subj!r}", False)
    except ToolError as e: check(f"create refuses {subj!r}, naming both paths", "update(<item>, recycle=true)" in str(e) and "sala recycle --when-idle" in str(e), str(e))
n1 = nfiles()
_wt_create._create(subject="[home] Fix the restart logic of the puller", description="- A thing", project="projects/alpha", owner="home-here")
check("a task that only mentions a restart is created", nfiles() == n1 + 1)
check("update's description says a recycle goes on the item the change serves, else to sala", "never an item of its own" in _wt_update._UPDATE_DESC and "sala recycle --when-idle" in _wt_update._UPDATE_DESC)
check("update's description says the flag goes on only once the change is installed, never before, with the early-flag example",
      "set it only once the change it waits for is installed (merged and deployed, or provisioned), never before" in _wt_update._UPDATE_DESC
      and "a flag set before the provision recycled the box too early" in _wt_update._UPDATE_DESC)
check("update's description names the board's status line and that sala runs the recycle, not the old notice",
      "Pane recycle pending for … (sala runs it)" in _wt_update._UPDATE_DESC and "sala runs a flagged recycle itself" in _wt_update._UPDATE_DESC and "Pane recycle needed" not in _wt_update._UPDATE_DESC)
_ut = next(t for t in __import__("asyncio").run(server.mcp.list_tools()) if t.name == "update")
check("the update tool as served carries the same guidance", "never before" in (_ut.description or "") and "(sala runs it)" in (_ut.description or ""), (_ut.description or "")[:200])
_cfg.CFG["fleet"].update(tool_name="", recycle_when_idle="")      # no fleet tool: nothing named, no command suggested
try: _wt_create._create(subject="[home] Recycle the sessions on box-a", description="- A thing", project="projects/alpha", owner="home-here"); check("with no fleet tool, create still refuses a recycle item", False)
except ToolError as e: check("with no fleet tool, create still refuses a recycle item and names no tool or command", "update(<item>, recycle=true)" in str(e) and "sala" not in str(e) and "next recycle" in str(e), str(e))
check("with no fleet tool the prose says 'the fleet tool'", _fg._fleet_tool() == "the fleet tool" and _fg._when_idle().startswith("leave it for the next recycle"), (_fg._fleet_tool(), _fg._when_idle()))
_cfg.CFG["fleet"].update(tool_name="sala", recycle_when_idle="sala recycle --when-idle")

# ---- 6. the client verb
sent = []
client.post = lambda what, body, timeout=30.0: (sent.append((what, body)), (200, {"items": [{"item": "s12", "action": "set", "held": False, "owner": "home-here"},
                                                                                         {"item": "s13", "action": "already", "held": True, "owner": "home-away"}], "pr": PR}))[1]
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = client.main(["client.py", "recycle-due", "--pr", PR])
check("client.py recycle-due --pr posts the PR", rc == 0 and sent[-1] == ("recycle-due", {"pr": PR}), sent)
check("and prints one line per item, held ones said", buf.getvalue() == (f"stackshot: s12 (mover home-here, anchored to {PR}) now waits for a recycle\n"
      f"stackshot: s13 (mover home-away, anchored to {PR}) already waits for a recycle — but it is on hold, so the watchdog does not count it until it wakes\n"), buf.getvalue())
with contextlib.redirect_stdout(io.StringIO()): rc = client.main(["client.py", "recycle-due", "--item", "s12"])
check("client.py recycle-due --item posts the id", rc == 0 and sent[-1] == ("recycle-due", {"item": "s12"}), sent)
n_sent = len(sent)
for argv, name in ((["ops/x", "--owner", "home-here", "--subject", "[home] Load it"], "the old filing form"), ([], "nothing"), (["--item", "s1", "--pr", PR], "both")):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): rc = client.main(["client.py", "recycle-due", *argv])
    check(f"usage, exit 1, nothing sent: {name}", rc == 1 and len(sent) == n_sent and "sala recycle --when-idle" in buf.getvalue(), buf.getvalue())
client._cfg.CFG["fleet"]["recycle_when_idle"] = ""
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = client.main(["client.py", "recycle-due"])
check("usage with no idle-recycle command: no command suggested", rc == 1 and "sala" not in buf.getvalue() and buf.getvalue().startswith("usage: client.py recycle-due"), buf.getvalue())
client._cfg.CFG["fleet"]["recycle_when_idle"] = "sala recycle --when-idle"
client.post = lambda what, body, timeout=30.0: (400, {"error": "Refused: no open item is anchored to …"})
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = client.main(["client.py", "recycle-due", "--pr", PR])
check("a refusal exits 1 and says why", rc == 1 and "recycle not marked [400] Refused" in buf.getvalue(), buf.getvalue())

# ---- 6b. recycle-wanted counts an item held for the recycle alone (before, every held item was skipped, so sala never
# recycled for one and it sat there); one held for a wake or an open after as well stays out. (_last_recycle is patched to 0 since section 3.)
for i in range(20, 28): item(i, "home-skipped" if i >= 26 else "home-here")
_update_svc._update("a20", recycle=True); _update_svc._update("a20", hold=True)                                   # held for the recycle alone
_update_svc._update("a21", recycle=True); say(21); _update_svc._update("a21", hold=True, wake="2099-01-02")                 # and a wake
_update_svc._update("a22", recycle=True); _update_svc._update("a22", after=["a25"], ask_by="2099-01-02"); _update_svc._update("a22", hold=True)   # and an open after
_update_svc._update("a23", recycle=True)                                                                     # not held
check("6b setup: a20 is held for the recycle alone, a21 has a wake, a22 an open after", recycle_svc._held_only_for_recycle(rd(20)) and not recycle_svc._held_only_for_recycle(rd(21))
      and not recycle_svc._held_only_for_recycle(rd(22)) and rd(21)["metadata"].get("until") and rd(22)["metadata"].get("after") == ["a25"] and rd(22)["metadata"].get("until"),
      [rd(i)["metadata"] for i in (20, 21, 22)])
w = recycle_svc._recycle_wanted("testbox")
check("wanted: an item held only for the recycle is listed", "a20" in w, w)
check("wanted: an item held for a wake as well is not listed", "a21" not in w, w)
check("wanted: an item held for an open after as well is not listed", "a22" not in w, w)
check("wanted: an unheld flagged item is listed, as before", "a23" in w, w)
it25 = rd(25); it25["status"] = "completed"; (T / "store/a/25.json").write_text(json.dumps(it25))
it22 = rd(22); [it22["metadata"].pop(k, None) for k in ("until", "wait_kind", "after")]; (T / "store/a/22.json").write_text(json.dumps(it22))      # what the release does when its after closes: the wait ends, the date and kind go
check("wanted: once its after closes and the wait ends, a22 waits for the recycle alone and is listed", "a22" in recycle_svc._recycle_wanted("testbox"), recycle_svc._recycle_wanted("testbox"))
with TestClient(app) as c:
    h = {"Authorization": "Bearer " + tok}
    res = c.get("/client/recycle-wanted", headers=h)
    check("GET /client/recycle-wanted lists the recycle-only held item too, in the same \"<count> <ids>\" form",
          res.status_code == 200 and {"a20", "a22", "a23"} <= {t.split("@")[0] for t in res.text.split()[1:]} and "a21" not in {t.split("@")[0] for t in res.text.split()} and res.text.split()[0] == str(len(res.text.split()) - 1), res.text)

# ---- 6c. sala retries a skipped pane and reports `recycled` again with the ORIGINAL start time: the second report is accepted and
# clears (and releases from a recycle-only hold) what the first kept
    _update_svc._update("a26", recycle=True); _update_svc._update("a27", recycle=True); _update_svc._update("a27", hold=True)
    S = time.time() + 30          # after the flags, and after section 3's report (now + 5), so it is the machine's latest start
    res1 = c.post("/client/recycled", json={"kind": "recycle", "started": S, "result": "partial", "skipped": "home-skipped"}, headers=h)
    k1 = {k["item"]: k["why"] for k in res1.json().get("kept", [])} if res1.status_code == 200 else {}
    check("retry: the first report keeps the skipped owner's items, flag and hold in place", res1.status_code == 200
          and k1.get("a26") == k1.get("a27") == "its mover was not relaunched" and rd(26)["metadata"].get("recycle") is True
          and rd(27)["metadata"].get("recycle") is True and rd(27)["metadata"].get("hold") is True, (res1.text, rd(27)["metadata"]))
    check("retry: and clears the unheld and recycle-only held items it covered, releasing the hold", {"a20", "a23"} <= set(res1.json().get("cleared", []))
          and "recycle" not in rd(20)["metadata"] and "hold" not in rd(20)["metadata"], (res1.text, rd(20)["metadata"]))
    told.clear()
    res2 = c.post("/client/recycled", json={"kind": "recycle", "started": S, "result": "ok", "skipped": []}, headers=h)
    check("retry: a second report for the same start time is accepted", res2.status_code == 200, res2.text)
    check("retry: it clears the items the first one kept", {"a26", "a27"} <= set(res2.json().get("cleared", [])) and "recycle" not in rd(26)["metadata"]
          and "recycle" not in rd(27)["metadata"], (res2.text, rd(26)["metadata"], rd(27)["metadata"]))
    check("retry: the item held only for the recycle is released from hold", "hold" not in rd(27)["metadata"] and any("a27" in n and "released from hold" in n for _, _, n in told), (rd(27)["metadata"], told))
    check("retry: the recorded start of the machine's last recycle stays the original", json.load(open(recycle_svc._recycles_path())).get("testbox") == S, open(recycle_svc._recycles_path()).read())
    res3 = c.post("/client/recycled", json={"kind": "recycle", "started": S, "result": "ok", "skipped": []}, headers=h)
    check("retry: a third report changes nothing and still answers", res3.status_code == 200 and not ({"a26", "a27"} & set(res3.json().get("cleared", []))), res3.text)

# ---- 6d. sala calls `recycled` once per cleared recycle flag with that flag's time (flag_at; contract 19, interface 4):
# the call covers the items flagged at or before it, an item flagged after it waits for its own flag, and a partial result keeps the skipped keeper's item
F = time.time() + 100          # the flag's time; later than every report above, so it is the machine's latest
for i, o, at in ((30, "home-here", F - 10), (31, "home-here", F), (32, "home-here", F + 1), (33, "home-skipped", F - 5), (34, "home-away", F - 5)):
    item(i, o, recycle=True, recycle_at=at)
told.clear()
r = recycle_svc._recycled("testbox", "recycle", F, "partial", ["home-skipped"], flag_at=F)
kept = {k["item"]: k["why"] for k in r["kept"]}
check("flag_at: an item flagged before the flag is cleared", "a30" in r["cleared"] and "recycle" not in rd(30)["metadata"] and "recycle_at" not in rd(30)["metadata"], r)
check("flag_at: an item flagged exactly at the flag's time is covered by it, and cleared", "a31" in r["cleared"] and "recycle" not in rd(31)["metadata"], r)
check("flag_at: an item flagged after the flag is kept, flag in place", kept.get("a32") == "flagged after the recycle flag it clears" and rd(32)["metadata"].get("recycle") is True
      and rd(32)["metadata"].get("recycle_at") == F + 1, (r, rd(32)["metadata"]))
check("flag_at, partial: the skipped keeper's item is kept", kept.get("a33") == "its mover was not relaunched" and rd(33)["metadata"].get("recycle") is True, r)
check("flag_at: an item whose keeper is on another machine is kept", kept.get("a34", "").startswith("its mover is not on") and rd(34)["metadata"].get("recycle") is True, r)
check("flag_at: the owner's line names the cleared items, partly", any(o == U["home-here"] and "a30" in n and "a31" in n and "a32" not in n and ", partly" in n for _, o, n in told), told)
check("flag_at: it is the time recorded as the machine's last recycle", json.load(open(recycle_svc._recycles_path())).get("testbox") == F, open(recycle_svc._recycles_path()).read())
recycle_svc._last_recycle = lambda m: json.load(open(recycle_svc._recycles_path())).get(m, 0.0)     # the real one back (6b patched it to 0), to see _recycle_wanted with the recorded flag time
w = recycle_svc._recycle_wanted("testbox")
check("wanted under flag_at: the item flagged after the recorded flag time is listed; the ones at or before it are not", "a32" in w and "a30" not in w and "a31" not in w and "a33" not in w, w)
told.clear()
r = recycle_svc._recycled("testbox", "recycle", F, "ok", [], flag_at=F)
check("flag_at: the retry with the skipped pane back clears its keeper's item, and still keeps the one flagged after", "a33" in r["cleared"] and "recycle" not in rd(33)["metadata"]
      and {k["item"] for k in r["kept"]} >= {"a32"} and "a32" not in r["cleared"], r)
r = recycle_svc._recycled("testbox", "recycle", F + 1, "ok", [], flag_at=F + 1)
check("flag_at: the next flag's call clears the item flagged at that later time", "a32" in r["cleared"] and "recycle" not in rd(32)["metadata"], r)
check("flag_at: a call for an earlier flag does not move the recorded time back", (recycle_svc._note_recycle("testbox", F - 50), json.load(open(recycle_svc._recycles_path())).get("testbox"))[1] == F + 1)
# over HTTP: flag_at in the body, and refused when it is no number; started absent, flag_at stands for it
for i, o, at in ((35, "home-here", F + 20), (36, "home-here", F + 21)):
    item(i, o, recycle=True, recycle_at=at)
with TestClient(app) as c:
    h = {"Authorization": "Bearer " + tok}
    res = c.post("/client/recycled", json={"kind": "recycle", "result": "ok", "skipped": [], "flag_at": F + 20}, headers=h)
    check("POST /client/recycled takes flag_at: covers a35, keeps a36", res.status_code == 200 and "a35" in res.json()["cleared"] and "a36" not in res.json()["cleared"]
          and any(k["item"] == "a36" for k in res.json()["kept"]) and rd(36)["metadata"].get("recycle") is True, res.text)
    res = c.post("/client/recycled", json={"kind": "recycle", "flag_at": "soon"}, headers=h)
    check("a flag_at that is no epoch is refused", res.status_code == 400, res.text)
# an older sala: started only, nothing changes (an item flagged at or after started is kept, the rest are cleared)
S2 = F + 200
for i, o, at in ((37, "home-here", S2 - 1), (38, "home-here", S2), (39, "home-here", S2 + 1)):
    item(i, o, recycle=True, recycle_at=at)
r = recycle_svc._recycled("testbox", "recycle", S2, "ok", [])
kept = {k["item"]: k["why"] for k in r["kept"]}
check("started only (an older sala): flagged before started is cleared", "a37" in r["cleared"] and "recycle" not in rd(37)["metadata"], r)
check("started only: flagged at started or after is kept, 'flagged after the recycle began' as before", kept.get("a38") == kept.get("a39") == "flagged after the recycle began"
      and rd(38)["metadata"].get("recycle") is True and rd(39)["metadata"].get("recycle") is True, r)
check("started only: started is the time recorded", json.load(open(recycle_svc._recycles_path())).get("testbox") == S2, open(recycle_svc._recycles_path()).read())

# ---- 6d. recycle-wanted prints each id as <id>[@<epoch>][~<repo>:pr<N>]: the second the recycle was asked for, and the pull request anchored to the item
# (the latest of its pull request anchors; an issue, a project-wide anchor and a bare id add nothing). The count token and the order stay what they were.
_anc_path = T / "store/anchors.json"; _anc_before = _anc_path.read_text()
for i in range(40, 44): item(i, "home-here")
_B = int(time.time()) + 3600                 # after every recycle reported above, so none covers these
for i, at in ((40, _B + 0.75), (41, _B + 1.5), (42, _B + 2.25)):
    d = rd(i); d["metadata"].update(recycle=True, recycle_at=at); (T / f"store/a/{i}.json").write_text(json.dumps(d))
d = rd(43); d["metadata"]["recycle"] = True; (T / "store/a/43.json").write_text(json.dumps(d))                 # flagged with no time stored
_pr = "https://github.com/example-owner/{}/pull/{}"
_store = json.loads(_anc_before)
_store.setdefault("projects/alpha", []).extend([
    {"url": _pr.format("salamander", 4), "items": ["a40"], "added": 5, "by": "t"},                                   # one pull request anchor
    {"url": _pr.format("stackshot", 7), "items": ["a42"], "added": 5, "by": "t"},                                    # two, the later one counts
    {"url": _pr.format("stackshot", 9) + "/files", "items": ["a42"], "added": 9, "by": "t"},
    {"url": "https://github.com/example-owner/stackshot/issues/15", "items": ["a42"], "added": 20, "by": "t"},       # an issue is no pull request
    {"url": _pr.format("stackshot", 13), "items": None, "added": 30, "by": "t"},                                     # a project-wide anchor is the project's, not the item's
])
_anc_path.write_text(json.dumps(_store))
_rows = recycle_svc._recycle_wanted("testbox"); _toks = recycle_svc._recycle_wanted_tokens("testbox")
_mine = {t.split("@")[0].split("~")[0]: t for t in _toks if t.split("@")[0].split("~")[0] in {"a40", "a41", "a42", "a43"}}
check("tokens: a recycle time and a pull request anchor print as <id>@<epoch>~<repo>:pr<N>, the epoch whole seconds", _mine.get("a40") == f"a40@{_B}~salamander:pr4", _mine)
check("tokens: no pull request anchor prints the @ suffix alone", _mine.get("a41") == f"a41@{_B + 1}", _mine)
check("tokens: of several pull request anchors the latest added counts, an issue or a project-wide anchor does not", _mine.get("a42") == f"a42@{_B + 2}~stackshot:pr9", _mine)
_last0, recycle_svc._last_recycle = recycle_svc._last_recycle, (lambda m: 0.0)            # a machine with no recycle on record counts an item whose flag stored no time
try:
    _bare = [t for t in recycle_svc._recycle_wanted_tokens("testbox") if t.startswith("a43")]
finally:
    recycle_svc._last_recycle = _last0
check("tokens: an item with no recycle time stored and no anchor stays a bare id", _bare == ["a43"], _bare)
check("tokens: the same items in the same order as _recycle_wanted, and nothing dropped", [re.split(r"[@~]", t)[0] for t in _toks] == _rows, (_toks, _rows))
with TestClient(app) as c:
    res = c.get("/client/recycle-wanted", headers={"Authorization": "Bearer " + tok})
    _parts = res.text.split()
    check("GET /client/recycle-wanted: the first token is still the count of the tokens after it, the tokens are the server's", res.status_code == 200
          and _parts[0] == str(len(_parts) - 1) == str(len(_rows)) and _parts[1:] == _toks, res.text)
_anc_path.write_text(_anc_before)

# ---- 7. release.sh --recycle: flags the PR's anchored items after a green deploy, sala's idle recycle when none (after)
rel = pathlib.Path(STACK, "release.sh").read_text(encoding="utf-8")
check("release.sh parses", subprocess.run(["bash", "-n", os.path.join(STACK, "release.sh")]).returncode == 0)
check("release.sh --recycle: recycle-due --pr for the PR, then the fleet tool's idle recycle as the fallback, never a new item; no tool named in it",
      'client.py recycle-due --pr "$url"' in rel and "elif idle_recycle " in rel and "recycle-due projects" not in rel and "--subject" not in rel and not re.search(r"\bsala\b", rel))   # the fleet tool; `salamander ci-runs` is the CI-run reader, another tool
_fn = re.search(r"(?ms)^idle_recycle\(\) \{.*?^\}", rel).group(0)
_fake = T / "fake-fleet"; _fake.write_text(f'#!/bin/sh\nprintf "%s|" "$@" > "{tmp}/fake-fleet.args"\n'); _fake.chmod(0o755)
def _idle(cfg):
    r = subprocess.run(["bash", "-c", _fn + '\nidle_recycle "release: stackshot PR #16: a title" && echo asked || echo none'], cwd=STACK, capture_output=True, text=True,
                       env={**os.environ, "STACKSHOT_CONFIG": str(cfg), "PATH": "/usr/local/bin:/usr/bin:/bin"})
    return r.stdout.strip()
check("release.sh's idle request with [fleet] recycle_when_idle unset: nothing run", _idle(T / "unset.toml") == "none" and not (T / "fake-fleet.args").exists())
check("…with a command whose program is not installed (sala absent from PATH): nothing run, no error", _idle(T / "stackshot.toml") == "none")
(T / "fake.toml").write_text(re.sub(r'(?m)^recycle_when_idle = ""', f'recycle_when_idle = "{_fake} recycle --when-idle"', (T / "unset.toml").read_text()))
check("…with one set: it runs, the reason appended as one argument", _idle(T / "fake.toml") == "asked"
      and (T / "fake-fleet.args").read_text() == "recycle|--when-idle|release: stackshot PR #16: a title|", (T / "fake-fleet.args").read_text() if (T / "fake-fleet.args").exists() else "")
check("release.sh refuses an unknown second argument", subprocess.run([os.path.join(STACK, "release.sh"), "5", "--bogus"], capture_output=True).returncode == 2)

print(f"{len(ran) - len(fails)}/{len(ran)} passed" + (f" — FAILED: {', '.join(fails)}" if fails else ""))
sys.exit(1 if fails else 0)
