"""Scenario test for the client API, step (a) of the client contract (board batch 5) — fixture data, no live store, no network.

Covers: minting a machine token (the server keeps its hash, the token lands in a 0600 file and nowhere else); who the server
takes a token for; the reads (registry, rules, brief, page-ts, and items for the board check of), whoami and config; refusals; the same over HTTP in-process; a held poll that the server's shutdown cancels answers 200 with no deliveries (the item follow-up); the puller's CLI version probe starts no window on Windows; owner_name follows an owner change.

    tests/run-suite client        → exit 0 / 1"""
import hashlib, json, os, re, socket, stat, sys, pathlib, tempfile, logging, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="clienttest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1   # the fixtures' subjects
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)   # the session and machine state is a fixture under fleet/
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects"): (T / d).mkdir(parents=True)
(T / "fleet/a/sessions.json").write_text("{}"); (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "sparrow", "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": ""}}}))
(T / "store/a/1.json").write_text(json.dumps({"id": "1", "subject": "[home] item 1", "description": "A thing. It lives here. Done when done.", "status": "open", "metadata": {"owner": "sparrow", "project": "projects/alpha"}}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:400]}" if got is not None else ""))

# ---- 1. minting
from stackshot.fleet import client
path = client.mint("box-far"); tok = open(path).read().strip()
d = json.loads((T / "secrets/clients.json").read_text())
check("the server keeps the token's hash, not the token", d["box-far"]["sha256"] == hashlib.sha256(tok.encode()).hexdigest() and tok not in (T / "secrets/clients.json").read_text(), d)
check("the token file is private", stat.S_IMODE(os.stat(path).st_mode) == 0o600 and stat.S_IMODE(os.stat(T / "secrets/clients.json").st_mode) == 0o600, oct(os.stat(path).st_mode))
check("a remote machine's token is not installed here", not (T / "secrets/client.token").exists())
me = socket.gethostname(); mine = open(client.mint(me)).read().strip()
check("the server box's own token is installed with the local address", (T / "secrets/client.token").read_text().strip() == mine and (T / "secrets/client.url").read_text().startswith("http://127.0.0.1:"), (T / "secrets/client.url").read_text())
try: client.mint("bad name/../x"); check("a machine name with a path in it is refused", False)
except ValueError: check("a machine name with a path in it is refused", True)
old = tok; tok = open(client.mint("box-far")).read().strip(); check("minting again replaces the token", tok != old)

# ---- 2. whom the server takes a token for
from stackshot.web import server
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.tools import brief as _wt_brief
from stackshot.web.tools import complete as _wt_complete
from stackshot.web.tools import get as _wt_get
from stackshot.web.tools import update as _wt_update
from stackshot.web.routes import client_api as _rt_client
from stackshot.waits import waiting as _WT  # the wait is stored as one date, until: these read it as the old fields were read
hd_ = lambda m: bool(m.get("hold") or _WT.stored_until(m))
wk_ = lambda m: _WT.wake_value(m)
ab_ = lambda m: _WT.stored_until(m) or m.get("ask_by")
from stackshot.core import store as _core_store
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
check("a valid token names its machine", _rt_client._client_machine("Bearer " + tok) == "box-far" and _rt_client._client_machine("bearer " + mine) == me)
check("a replaced token is dead", _rt_client._client_machine("Bearer " + old) == "")
for bad in ("", "Bearer ", "Bearer short", "Basic " + tok, tok, "Bearer " + tok + "x"):
    check(f"refused: {bad[:14]!r}", _rt_client._client_machine(bad) == "", bad[:20])
client.revoke("box-far"); check("a revoked machine is refused", _rt_client._client_machine("Bearer " + tok) == "" and not os.path.exists(path))
tok = open(client.mint("box-far")).read().strip()

# ---- 3. the reads
st, ct, body = server._client_get("registry", {}); check("registry: the page registry as stored", st == 200 and "projects/alpha" in json.loads(body)["pages"], body[:120])
st, ct, body = server._client_get("brief", {}); check("brief: what a session start prints", st == 200 and body.startswith("Board: 1 open"), body[:120])
st, ct, body = server._client_get("rules", {}); check("rules: the rulebook", st == 200 and len(body) > 500 and ct.startswith("text/markdown"), (st, len(body)))
st, ct, body = server._client_get("page-ts", {"key": "projects/alpha"}); check("page-ts: a page's last change", st == 200 and json.loads(body)["ts"] and json.loads(body)["key"] == "projects/alpha", body)
st, ct, body = server._client_get("page-ts", {"key": "projects/alpha.md"}); check("page-ts: a trailing .md is fine", st == 200 and json.loads(body)["key"] == "projects/alpha", body)
st, ct, body = server._client_get("page-ts", {"key": "projects/none"}); check("page-ts: a page that does not exist has no time", st == 200 and json.loads(body)["ts"] is None, body)
# 2026-10-16: page-ts for a page that is not in the mirror used to ask the server's own client API from inside the server (pages._api →
# client.get over the loopback): the event loop could not answer that request until its 6 s timeout ran out, so every request waited.
# The server never makes that call; a spy on client.get stands in for the loopback (the real one stalls the loop until its timeout).
from stackshot.projects import pages as _pg_self
_calls = []; _real_get = client.get; client.get = lambda *a, **k: (_calls.append(a), (0, ""))[1]
_unreach = len(_pg_self.UNREACHABLE)
try:
    st, ct, body = server._client_get("page-ts", {"key": "projects/none"})
    check("page-ts for a missing page makes no call to the server itself", _calls == [] and len(_pg_self.UNREACHABLE) == _unreach and _pg_self.LOCAL_ONLY, (_calls, _pg_self.LOCAL_ONLY))
    check("pages._api answers nothing in the server process", _pg_self._api("page-ts", "projects/none") is None and _calls == [], _calls)
finally: client.get = _real_get
for bad in ("", "../etc/passwd", "projects/../../x", "inbox/thing"):
    st, ct, body = server._client_get("page-ts", {"key": bad}); check(f"page-ts refuses {bad!r}", st == 400, (st, body))
st, ct, body = server._client_get("secrets", {}); check("an unknown read is 404", st == 404, (st, body))

# ---- 3b. the hold record, the unexplained-holds report and the new holds in the briefings (the part that shipped):
# hold=true behaves as before (no gate); a hold records who set it and when; the report lists a hold when nothing holds it NOW, whatever was stored as its reason;
# the holds set in the last 24 hours go to board.md's head, the brief tool and the session-start brief; a malformed record never breaks any of them
import time as _t
def mk(i, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] hold fixture {i}", "description": "A thing. It lives here. Done when done.", "status": meta.pop("status", "open"),
                                                       "updated": _t.time() - 60, "state_updated": _t.time() - 60, "confirmed": _t.time() - 60,
                                                       "metadata": {"owner": "sparrow", "project": "projects/alpha", "next": "do the thing", **meta}}))
def rdm(i): return json.loads((T / f"store/a/{i}.json").read_text())["metadata"]
def upd(i, **kw):
    try: return _wt_update.stackshot_update(item_id=f"a{i}", sender="sparrow", **kw), ""
    except server.ToolError as e: return "", str(e)
WK = (server._pages.zone_now() + server.dt.timedelta(days=5)).strftime("%Y-%m-%d")
BAS = "visit on " + (server._pages.zone_now() + server.dt.timedelta(days=9)).strftime("%Y-%m-%d")      # a time wait carries a reason
for i in range(2, 12): mk(i)
mk(20)                                                             # an item that others wait on
res, err = upd(2, hold=True, recycle=True)
check("hold=true behaves as before: a session's hold for a pane recycle is accepted", not err and server._is_held(server._load("a2")), (err, rdm(2)))
hs = rdm(2).get("hold_set") or {}
check("…and records who set it and when, nothing more (the reason is the wait_basis, not in the hold record)", set(hs) == {"at", "by"} and hs["by"] == "sparrow" and abs(hs["at"] - _t.time()) < 60, hs)
check("get shows who set the hold and when", "hold: set by sparrow " in _wt_get.stackshot_get("a2"), _wt_get.stackshot_get("a2"))
upd(2, clear_hold=True)
check("clear_hold releases it and drops the record", not server._is_held(server._load("a2")) and "hold_set" not in rdm(2), rdm(2))
res, err = upd(3, hold=True)
check("a hold with no wake and nothing holding it is still refused as an indefinite park (the rule of main)", err.startswith("Refused: a hold names what it waits for; an unconditional or indefinite park is refused."), err)
check("the update tool's text no longer invites a session to park its own item: no \"without asking\", no \"park it to the date\", no \"nearest date to check\"",
      not any(x in _wt_update._UPDATE_DESC for x in ("without asking", "park it to the date", "an owner parks its own item", "nearest date to check")) and "A session does not park to defer work it could do now" in _wt_update._UPDATE_DESC,
      _wt_update._UPDATE_DESC[:200])
# the server's own holds are untouched: the board button records the board as the setter
mk(12)
server._update("a12", hold=True, recycle=True, sender="sparrow")
check("the core write (what the server's own paths use) holds as before", server._is_held(server._load("a12")), rdm(12))

# the report: read only, a hold nothing holds now
_sa = server._scoped_anchors; server._scoped_anchors = lambda proj, gid: [{"url": "https://github.com/example-owner/stackshot/pull/9", "items": [gid]}] if gid == "a10" else _sa(proj, gid)
mk(13, hold=True, wake="2026-11-19")                                              # stored before the record, nothing holds it: listed
mk(14, hold=True, wake="2026-11-20", hold_set={"at": _t.time() - 7200, "by": "sparrow"})                    # recorded, nothing holds it: listed
mk(15, hold=True, wake="2026-11-21", hold_set={"at": _t.time() - 7200, "by": "sparrow", "why": ["said"]})   # a stored reason is never trusted: listed
mk(16, hold=True, wake="2026-11-22", after=["a20"])                               # an open after holds it
mk(17, hold=True, wake="2026-11-23", recycle=True)                                # a recycle holds it
mk(18, hold=True, wake="2026-11-24", needs=["external"])                          # an outside party holds it
mk(10, hold=True, wake="2026-11-25")                                              # an anchor scoped to it holds it (patched above)
mk(19, status="completed", hold=True)                                             # closed: never listed
mk(21, hold=True, wake="2026-11-26", hold_set={"at": "garbage", "by": "sparrow"}); mk(22, hold=True, wake="2026-11-27", hold_set="oops")   # malformed records
before = {f.name: f.read_text() for f in (T / "store/a").glob("*.json")}
try: rows = server._holds_unexplained(); rep = server._holds_report()
finally: server._scoped_anchors = _sa
gids = [r["gid"] for r in rows]
check("the report lists a hold nothing holds now (stored before the record, recorded, or with a stored reason), and none that an after, a recycle, needs external or an anchor holds",
      {"a13", "a14", "a15"} <= set(gids) and not {"a16", "a17", "a18", "a10", "a19", "a1", "a2"} & set(gids), gids)
check("a malformed record (a value that is no number, a record that is no object) breaks nothing and reads as no record", {"a21", "a22"} <= set(gids)
      and all(r["at"] == 0 for r in rows if r["gid"] in ("a21", "a22", "a13")) and next(r for r in rows if r["gid"] == "a22")["by"] == "", [r for r in rows if r["gid"] in ("a21", "a22")])
row = next(r for r in rows if r["gid"] == "a14"); old = next(r for r in rows if r["gid"] == "a13")
check("each row has the owner, the wake, who set it and when; a hold from before the record says so", row["owner"] and wk_(row) == "2026-11-20" and row["by"] == "sparrow" and row["at"] > 0
      and old["by"] == "" and old["at"] == 0 and wk_(old) == "2026-11-19", (row, old))
check("the printed report: one line per item with mover, wake, setter and time", "a14 · mover sparrow · wake 2026-11-20 · set by sparrow (" in rep and "a13 · mover sparrow · wake 2026-11-19 · set by unknown (before the record)" in rep
      and "a16 ·" not in rep and "update clear_hold=true" in rep, rep)
check("the report writes nothing: every item file is as it was", before == {f.name: f.read_text() for f in (T / "store/a").glob("*.json")})
st, ct, body = server._client_get("holds", {}); check("the client API serves it as holds", st == 200 and "a14 · mover sparrow · wake 2026-11-20" in body and "a16 ·" not in body and ct.startswith("text/plain"), (st, body[:120]))
_cg = client.get; client.get = lambda what, *a, **k: (200, server._client_get(what, {})[2]); _o = sys.stdout; sys.stdout = __import__("io").StringIO()
try: rc = client.main(["client.py", "holds"]); printed = sys.stdout.getvalue()
finally: sys.stdout = _o; client.get = _cg
check("client.py holds prints the report and exits 0", rc == 0 and "a14 · mover sparrow" in printed and printed.endswith("\n"), (rc, printed[:200]))
client.get = lambda what, *a, **k: (401, "no token"); _o = sys.stdout; sys.stdout = __import__("io").StringIO()
try: rc = client.main(["client.py", "holds"])
finally: sys.stdout = _o; client.get = _cg
check("client.py holds exits 1 when the server is not reached", rc == 1)

# a time that fromtimestamp cannot take (a milliseconds epoch, 1e300, a numeric string) is no record: nothing raises anywhere, the item reads as a hold from before the record
BAD = {30: 1e12, 31: 1.76e12, 32: 1e300, 33: "1e12", 34: float("inf"), 35: -5, 36: 4102444801}
for n, v in BAD.items(): mk(n, hold=True, wake="2026-11-28", hold_set={"at": v, "by": "sparrow"})
mk(37, hold=True, wake="2026-11-29", hold_set={"at": _t.time() - 60, "by": "sparrow\n## injected heading\r\n- [a1](#x) fake"})
md_ = server._rmod.render(str(_core_store.STORE), "full"); br_ = server._rmod.render(str(_core_store.STORE), "brief"); rows_ = server._holds_unexplained(); rep_ = server._holds_report()
check("a hold time outside 0 < t < year 2100 (1e12, 1.76e12, 1e300, \"1e12\", inf, negative, 2100+1 s) reads as no record: board.md, the brief, the report, get and an update all work, the item listed as before the record",
      all(server._rmod.hold_at({"metadata": {"hold_set": {"at": v}}}) == 0.0 for v in BAD.values()) and all(f"a{n} · mover sparrow · wake 2026-11-28 · set by sparrow (before the record)" in rep_ for n in BAD)
      and all(next(r for r in rows_ if r["gid"] == f"a{n}")["at"] == 0 for n in BAD) and all(_wt_get.stackshot_get(f"a{n}") for n in BAD) and not upd(30, next="sparrow: the step that comes now", dropped=[1])[1]
      and server._rmod.hold_at({"metadata": {"hold_set": {"at": _t.time() - 5}}}) > 0, (rep_[:300], rows_[:2]))
mk(38, hold=True, recycle=True, hold_set={"at": 1790000000.0, "by": "home-first"}); upd(38, hold=True)      # a hold with a date folds into until and keeps no record; one that waits on an item or a recycle keeps its flag and record
check("hold=true passed again on an item already held keeps the original record (who and when)", rdm(38)["hold_set"] == {"at": 1790000000.0, "by": "home-first"}, rdm(38))
mk(39, hold=True, recycle=True); upd(39, hold=True)
check("…but a hold with no record gets one when a session passes hold=true on it", set(rdm(39).get("hold_set") or {}) == {"at", "by"}, rdm(39))
check("a hold_set.by with newlines is collapsed to one line before it reaches board.md, the report or get: no line is injected",
      "## injected heading" not in "\n".join(l for l in md_.splitlines() if l.startswith("## ") or l.startswith("- [a1]")) and "set by sparrow ## injected heading - [a1](#x) fake" in br_.replace("\n", " ") + md_
      and server._rmod.hold_by({"metadata": {"hold_set": {"by": "x\ny" + "z" * 200}}}) == "x y" + "z" * 77 and "\n## injected" not in rep_ and "\n## injected" not in _wt_get.stackshot_get("a37"), (md_[md_.find("a37"):][:200],))
# a hold's record goes when the hold ends: by the wake pass, by an after closing, by a release
mk(40, hold=True, wake=(server._pages.zone_now() - server.dt.timedelta(days=1)).strftime("%Y-%m-%d"), hold_set={"at": _t.time() - 3600, "by": "sparrow"})
server._wake_pass()
check("the wake pass that releases a hold drops its record too", not server._is_held(server._load("a40")) and "hold_set" not in rdm(40) and "hold" not in rdm(40), rdm(40))
mk(41, hold=True, wake=WK, after=["a42"], hold_set={"at": _t.time() - 3600, "by": "sparrow"}); mk(42)
check("while its after item is open, nothing is unexplained about the hold", "a41" not in [r["gid"] for r in server._holds_unexplained()])
_wt_complete.stackshot_complete("a42", sender="sparrow", outcome="done", reason="finished", description="- Finished: the thing is done")
check("an after item closing releases the hold and drops its record", not server._is_held(server._load("a41")) and "hold_set" not in rdm(41) and "hold" not in rdm(41) and "after" not in rdm(41), rdm(41))
mk(43, hold=True, wake=WK, after=["a44"]); mk(44, status="completed"); mk(45, hold=True, wake=WK, after=["a46"])
check("a held item whose after item is already closed, or missing, is listed as unexplained: nothing open holds it",
      {"a43", "a45"} <= {r["gid"] for r in server._holds_unexplained()}, [r["gid"] for r in server._holds_unexplained()])

# the briefing data: the holds set in the last 24 hours (board.md's head, the brief tool, the session-start brief); a malformed record breaks none
for i in (3, 4, 5): mk(i)
mk(3, hold=True, wake=WK, hold_set={"at": _t.time() - 60, "by": "sparrow"})                      # new, nothing holds it
mk(4, hold=True, wake=WK, after=["a20"], hold_set={"at": _t.time() - 60, "by": "sparrow"})       # new, an open after holds it
mk(23, hold=True, wake="2026-11-24", hold_set={"at": _t.time() - 3 * 86400, "by": "sparrow"})   # set three days ago: not new
md = server._rmod.render(str(_core_store.STORE), "full"); br = server._rmod.render(str(_core_store.STORE), "brief")
sect = md[md.find("## New holds"):md.find("Shared by every")]
check("board.md has a section of the holds set in the last 24 hours, each with its owner, setter, wake and what holds it",
      "## New holds (last 24 hours)" in md and re.search(r"- \[a3\]\(#task-a-3\) · mover `[^`]*` · set by sparrow .* · wake .* · nothing holds it now", sect)
      and re.search(r"\[a4\].* · held by after a20", sect), sect)
check("…and not one set three days ago, one stored before the record, a malformed record or an item that is not held",
      all(f"[a{n}](#task-a-{n})" not in sect for n in (23, 13, 21, 22, 19, 1, 30, 31, 32, 33)), sect)
check("the session-start brief lists them too", "  new hold (24 h): a3 [home] hold fixture 3" in br and "nothing holds it now" in br and "held by after a20" in br and "a23" not in br, br)
(T / "board.md").write_text(md, encoding="utf-8")
head = _wt_brief.stackshot_brief()
check("the brief tool's head carries the section (it reads board.md up to the first lane)", head.find("## New holds") != -1 and head.find("## New holds") < head.find("All open items in full"), head[:300])
check("a hold_set whose time is no number never raises in the renderer or in get", server._rmod.hold_at({"metadata": {"hold_set": {"at": "x"}}}) == 0.0 and server._rmod.hold_at({"metadata": {"hold_set": {"at": float("nan")}}}) == 0.0
      and "hold: set by sparrow" in _wt_get.stackshot_get("a21") and _wt_get.stackshot_get("a22"), _wt_get.stackshot_get("a21"))
server._update("a3", clear_hold=True, sender="sparrow")
check("a released hold is no longer new", "[a3]" not in server._rmod.render(str(_core_store.STORE), "full").split("Shared by every")[0].split("## New holds")[-1])
for i in range(2, 50): (T / f"store/a/{i}.json").unlink(missing_ok=True)

# ---- 4. over HTTP, in-process
from starlette.testclient import TestClient
app = server.mcp.http_app()
with TestClient(app) as c:
    r = c.get("/client/registry"); check("http: no token → 401", r.status_code == 401, r.status_code)
    r = c.get("/client/registry", headers={"Authorization": "Bearer " + "x" * 43}); check("http: a wrong token → 401", r.status_code == 401, r.status_code)
    H = {"Authorization": "Bearer " + tok}
    r = c.get("/client/whoami", headers=H); check("http: whoami names the machine", r.status_code == 200 and r.json() == {"machine": "box-far"}, r.text)
    r = c.get("/client/registry", headers=H); check("http: registry", r.status_code == 200 and "projects/alpha" in r.json()["pages"] and r.headers["cache-control"] == "no-store", r.text[:100])
    r = c.get("/client/page-ts", params={"key": "projects/alpha"}, headers=H); check("http: page-ts", r.status_code == 200 and r.json()["ts"], r.text)
    r = c.get("/client/brief", headers=H); check("http: brief", r.status_code == 200 and r.text.startswith("Board: 1 open"), r.text[:80])
    r = c.get("/client/holds", headers=H); check("http: holds → the report (nothing on hold without a reason here)", r.status_code == 200 and r.text == "no open item is on hold without something holding it\n" and r.headers["cache-control"] == "no-store", r.text[:100])
    r = c.get("/client/holds"); check("http: holds without a token → 401", r.status_code == 401, r.status_code)
    r = c.get("/client/nothing", headers=H); check("http: unknown read → 404", r.status_code == 404, r.status_code)
    r = c.get("/client/config"); check("http: config without a token → 401", r.status_code == 401, r.status_code)
    r = c.get("/client/config", headers=H); cj = r.json() if r.status_code == 200 else {}
    check("http: config — the instance's non-secret settings a client's hooks need", r.status_code == 200 and r.headers["cache-control"] == "no-store"
          and cj["instance"]["timezone"] == "Asia/Dubai" and cj["pages"] == {"flavor": "plain", "dirs": ["projects", "ops"]} and cj["paths"] == {"brain": f"{tmp}/brain"}
          and cj["subject"]["prefixes"] == ["[work] ", "[home] "] and cj["page_gate"] == {"keeper_currency": "keepers"} and cj["server"] == {"path": "/mcp"}
          and cj["board_check"] == {"mode": "off"}
          and set(cj) == {"instance", "pages", "paths", "subject", "page_gate", "board_check", "gbrain", "server"}, r.text[:400])
    check("http: config carries no secret and no secrets path", "secret" not in r.text.lower() and "token" not in r.text.lower() and f"{tmp}/secrets" not in r.text
          and "allowed_emails" not in r.text, r.text[:400])
    # the client's own fetch, against the same app
    import urllib.request, io
    class _Resp:
        def __init__(s, r): s.status = r.status_code; s._b = r.content
        def read(s): return s._b
        def __enter__(s): return s
        def __exit__(s, *a): return False
    def fake_urlopen(req, timeout=0):
        r = c.get(req.full_url.replace(client.server_url(), ""), headers=dict(req.header_items()))
        if r.status_code >= 400:
            import urllib.error; raise urllib.error.HTTPError(req.full_url, r.status_code, "x", {}, io.BytesIO(r.content))
        return _Resp(r)
    client.urllib.request.urlopen = fake_urlopen
    st, body = client.get("whoami"); check("client.get uses this machine's token", st == 200 and json.loads(body)["machine"] == me, (st, body))
    st, body = client.get("page-ts", "projects/alpha"); check("client.get passes the key", st == 200 and json.loads(body)["key"] == "projects/alpha", (st, body))
    # the write verb: a script's message, over HTTP and through client.py
    sent = []
    server._message = lambda to, text, sender, auth="", origin="": (sent.append((to, text, sender, auth, origin)), "delivered → x — arrives as a labelled [stackshot message] turn")[1] if sender else (_ for _ in ()).throw(server.ToolError("Refused: sender is required"))
    r = c.post("/client/message", json={"to": "projects/alpha", "text": "hello", "sender": "nightly-job"}); check("http: a message without a token → 401", r.status_code == 401 and not sent, r.status_code)
    r = c.post("/client/message", json={"to": "projects/alpha", "text": "hello", "sender": "nightly-job"}, headers=H)
    check("http: a message with a machine token goes through the message path, marked with the machine", r.status_code == 200 and r.json()["result"].startswith("delivered") and sent == [("projects/alpha", "hello", "nightly-job", "machine:box-far", "box-far")], (r.text, sent))
    r = c.post("/client/message", json={"to": "projects/alpha", "text": "hello"}, headers=H); check("http: a refusal comes back as 400 with the reason", r.status_code == 400 and "sender is required" in r.json()["error"], r.text)
    r = c.post("/client/message", content=b"not json", headers=H); check("http: a body that is not JSON → 400", r.status_code == 400, r.text)
    r = c.get("/client/message", headers=H); check("http: the message path does not answer a GET as a read", r.status_code == 404, r.status_code)
    def fake_urlopen2(req, timeout=0):
        r = c.post(req.full_url.replace(client.server_url(), ""), content=req.data, headers=dict(req.header_items())) if req.get_method() == "POST" else c.get(req.full_url.replace(client.server_url(), ""), headers=dict(req.header_items()))
        if r.status_code >= 400:
            import urllib.error; raise urllib.error.HTTPError(req.full_url, r.status_code, "x", {}, io.BytesIO(r.content))
        return _Resp(r)
    client.urllib.request.urlopen = fake_urlopen2
    st, body = client.message("projects/alpha", "from the client", "size-watch"); check("client.message sends with this machine's token and returns the server's answer", st == 200 and body.startswith("delivered") and sent[-1] == ("projects/alpha", "from the client", "size-watch", f"machine:{me}", me), (st, body, sent[-1]))
    st, body = client.message("projects/alpha", "x", ""); check("client.message hands back a refusal's reason", st == 400 and "sender is required" in body, (st, body))
    check("client.py message needs a label", client.main(["client.py", "message", "projects/alpha", "hi"]) == 1 and client.main(["client.py", "message", "projects/alpha", "hi", "--sender", "nightly-job"]) == 0 and sent[-1][1:3] == ("hi", "nightly-job"), sent[-1])
    # ---- a SendMessage handover a box's hook reports (pages.py touch → POST /client/handover) names the background agent
    _reg46, _a1 = (T / "store/projects.json").read_text(), (T / "store/a/1.json").read_text()
    rg = json.loads(_reg46); rg["pages"]["projects/alpha"].update(agents={"sparrow-main": "front", "sparrow-bg": "back"}, back_agents={"sparrow-bg": "back"}); (T / "store/projects.json").write_text(json.dumps(rg))
    M = "dddddddd-4444-4444-8444-444444444444"; (T / "fleet/a/sessions.json").write_text(json.dumps({M: {"name": "sparrow-main", "machine": "a", "url": "", "seen": "x"}}))
    m1 = lambda: json.loads((T / "store/a/1.json").read_text())["metadata"]
    r = c.post("/client/handover", json={"to": "sparrow-bg", "text": "a1 is yours", "sender": "sparrow-main"}); check("http: a handover without a token → 401", r.status_code == 401 and "needs" not in m1(), r.status_code)
    r = c.post("/client/handover", json={"to": "sparrow-bg", "text": "a1 is yours"}, headers=H); check("http: a handover without a sender → 400", r.status_code == 400 and "sender" in r.json()["error"], r.text)
    r = c.post("/client/handover", json={"to": "sparrow-bg", "text": "please take a1: the build", "sender": "sparrow-main"}, headers=H)
    check("http: a handover to a background agent names it in the item's needs, with the path in the record", r.status_code == 200 and m1().get("needs") == ["sparrow-bg"]
          and r.json() == {"result": "(named sparrow-bg in a1's needs: handover message from sparrow-main (SendMessage on box-far))"}, (r.text, m1()))
    (T / "store/a/1.json").write_text(_a1)
    r = c.post("/client/handover", json={"to": "sparrow-main", "text": "a1 is yours", "sender": "sparrow-bg"}, headers=H)
    check("http: a handover to a front agent names nobody, an empty result", r.status_code == 200 and r.json() == {"result": ""} and "needs" not in m1(), r.text)
    # the hook side: pages.py touch on a SendMessage payload posts the handover through client.post (this machine's token) and hands the server's line to the hook
    import io as _io; from stackshot.projects import pages
    pl = {"tool_name": "SendMessage", "session_id": M, "tool_input": {"to": "sparrow-bg", "message": "take a1 please"}, "tool_response": "Message sent"}
    out = pages.handover(pl)
    check("pages.py: a SendMessage to a background agent that names an item is reported with the sender's name, and the server's line comes back",
          out == f"[stackshot] (named sparrow-bg in a1's needs: handover message from sparrow-main (SendMessage on {me}))" and m1().get("needs") == ["sparrow-bg"], (out, m1()))
    calls = []; _post = client.post; client.post = lambda *a, **k: (calls.append(a), _post(*a, **k))[1]
    try:
        check("pages.py: a message that names no item makes no call", pages.handover({**pl, "tool_input": {"to": "sparrow-bg", "message": "no id here, just words"}}) == "" and not calls, calls)
        check("pages.py: a message that names an item but goes to a front agent makes the call and gets nothing back", pages.handover({**pl, "tool_input": {"to": "sparrow-main", "message": "a1 again"}}) == "" and len(calls) == 1, calls)
    finally: client.post = _post
    (T / "store/a/1.json").write_text(_a1)
    _in, _out = sys.stdin, sys.stdout; sys.stdin, sys.stdout = _io.StringIO(json.dumps(pl)), _io.StringIO()
    try: pages.cmd_touch(); printed = sys.stdout.getvalue()
    finally: sys.stdin, sys.stdout = _in, _out
    check("pages.py touch: the hook entry prints the server's line as one additionalContext", json.loads(printed or "{}") == {"hookSpecificOutput": {"hookEventName": "PostToolUse",
          "additionalContext": f"[stackshot] (named sparrow-bg in a1's needs: handover message from sparrow-main (SendMessage on {me}))"}} and m1().get("needs") == ["sparrow-bg"], printed)
    (T / "store/a/1.json").write_text(_a1); (T / "store/projects.json").write_text(_reg46); (T / "fleet/a/sessions.json").write_text("{}")
    os.remove(T / "secrets/client.token"); st, body = client.get("registry"); check("client.get without a token says how to get one", st == 401 and "mint" in body, (st, body))

# ---- 5. a held poll when the server stops (the item follow-up): uvicorn cancels the handler once its graceful shutdown times out;
# the puller gets an empty answer (200), not a 500 and a traceback in the server's log
import asyncio
from starlette.requests import Request
async def _held_poll_cancelled():
    body = json.dumps({"sessions": [], "wait": 30}).encode()
    async def receive(): return {"type": "http.request", "body": body, "more_body": False}
    req = Request({"type": "http", "method": "POST", "path": "/client/poll", "query_string": b"", "path_params": {"what": "poll"},
                   "headers": [(b"authorization", ("Bearer " + tok).encode()), (b"content-type", b"application/json")]}, receive)
    t = asyncio.create_task(_rt_client.client_write(req))
    await asyncio.sleep(1.5); held = not t.done()
    t.cancel()
    try: return held, await t
    except asyncio.CancelledError: return held, None
held, resp = asyncio.run(_held_poll_cancelled())
_pb = json.loads(resp.body) if resp is not None else {}
check("poll: a held poll cancelled by the server's shutdown answers 200 with no deliveries (and what is current, puller 9, and the repo address, puller 10)", held and resp is not None and resp.status_code == 200
      and _pb.get("deliveries") == [] and _pb.get("machine") == "box-far" and {"puller", "stackshot", "self_update"} <= set(_pb.get("current") or {}) <= {"puller", "stackshot", "self_update", "repo"}, (held, resp and resp.status_code, resp and resp.body))

# ---- 6. the puller's CLI version probe starts no window on Windows (2026-10-05): pythonw has no console, so a console child
# would get a fresh one, which Windows 11 shows as a terminal flashing every ten minutes
import subprocess; from stackshot.fleet import puller
seen = []
class _Out: stdout = "2.1.288 (Claude Code)"
def _fake_run(args, **kw): seen.append(kw); return _Out()
_run, _win, _ver = puller.subprocess.run, puller.WINDOWS, dict(puller._VER)
try:
    puller.subprocess.run = _fake_run
    for win in (True, False):
        puller.WINDOWS = win
        puller._VER = {"at": 0.0, "v": ""}; seen.clear(); v = puller.cli_version([])
        if win:
            check("puller: on Windows the version probe runs with CREATE_NO_WINDOW and no stdin", seen and seen[0].get("creationflags") == 0x08000000 and seen[0].get("stdin") is subprocess.DEVNULL, seen)
        else:
            check("puller: elsewhere the version probe sets no creationflags, and no stdin", seen and "creationflags" not in seen[0] and seen[0].get("stdin") is subprocess.DEVNULL, seen)
        check(f"puller: the probe's answer is the version ({'windows' if win else 'linux'})", v == "2.1.288", v)
    # an update swaps the binary: the version is asked again at once, not after the 10-min wait
    puller.WINDOWS = False; _sig = puller._cli_sig
    try:
        puller._cli_sig = lambda: ("/x/claude", 1, 1); puller._VER = {"at": 0.0, "v": "", "sig": None}; puller.cli_version([]); seen.clear()
        puller.cli_version([]); check("puller: same binary within 10 min → no new probe", not seen, seen)
        puller._cli_sig = lambda: ("/x/claude", 2, 2); _Out.stdout = "2.1.289 (Claude Code)"; v = puller.cli_version([])
        check("puller: the binary changed → probed again at once, new version reported", len(seen) == 1 and v == "2.1.289", (seen, v))
        puller._cli_sig = lambda: None; seen.clear(); puller.cli_version([])
        check("puller: binary not found → no probe until the 10 min pass", not seen, seen)
    finally:
        puller._cli_sig = _sig
finally:
    puller.subprocess.run, puller.WINDOWS, puller._VER = _run, _win, _ver

# ---- 6b. the router's own `claude -p` call is not a session: the CLI registers it (cwd = <tmp>/stackshot-router-XXXX, made by
# router.run_call with config.ROUTER_CWD_PREFIX; router_scenario checks the call's cwd), and the puller must not report it
import tempfile as _tf; from stackshot.core import config as _cfgm
_reg = T / "registry"; _reg.mkdir()
def _rec(n, sid, cwd):
    (_reg / f"{n}.json").write_text(json.dumps({"sessionId": sid, "name": n, "pid": os.getpid(), "messagingSocketPath": "/x/sock", "cwd": cwd, "updatedAt": 1}))
_tmpdir = _tf.gettempdir()
_rec("router", "11111111-1111-4111-8111-111111111111", os.path.join(_tmpdir, _cfgm.ROUTER_CWD_PREFIX + "ab12cd"))
_rec("normal", "22222222-2222-4222-8222-222222222222", "/home/user")
_rec("lookalike-elsewhere", "33333333-3333-4333-8333-333333333333", "/srv/" + _cfgm.ROUTER_CWD_PREFIX + "ab12cd")
_rec("other-in-tmp", "44444444-4444-4444-8444-444444444444", os.path.join(_tmpdir, "something-else"))
_rec("no-cwd", "55555555-5555-4555-8555-555555555555", "")
_names = sorted(r["name"] for r in puller.sessions(str(_reg)))
check("puller: a record in <tmp>/stackshot-router-* is skipped, every other record is kept", _names == ["lookalike-elsewhere", "no-cwd", "normal", "other-in-tmp"], _names)
check("puller: the shared prefix is the one the router's temporary directory has", _cfgm.ROUTER_CWD_PREFIX == "stackshot-router-")

# ---- 7. items?key=<session>: the open items a session owns, for the end-of-turn board check
U, V = "aaaaaaaa-1111-4111-8111-111111111111", "bbbbbbbb-2222-4222-8222-222222222222"
(T / "fleet/a/sessions.json").write_text(json.dumps({U: {"name": "sparrow", "machine": "a"}, V: {"name": "home-other", "machine": "a"}}))
def item(n, owner, status="open", **extra):
    meta = {"owner": owner, "project": "projects/alpha", **extra.pop("meta", {})}
    if not ({"needs", "mover", "then", "hold", "after"} & set(meta)): meta["mover"] = owner      # the creator moves nothing; the fixture's items are moved by their former creator
    (T / f"store/a/{n}.json").write_text(json.dumps({"id": str(n), "subject": f"[home] item {n}", "description": "x", "status": status, "metadata": meta, **extra}))
item(2, U, state_updated=100.0, confirmed=200.0, updated=300.0, meta={"needs": "decision", "then": U, "next": "first\nsecond"})
item(3, U, "on_hold")                                       # the retired status, not yet migrated: open and held
item(4, U, meta={"hold": True, "mover": U})
item(5, U, "completed"); item(6, V); item(7, "cse_0123456789abcdef", meta={"owner_name": "sparrow", "mover": "sparrow"})
gids = lambda body: [x["gid"] for x in json.loads(body)["items"]]
st, ct, body = server._client_get("items", {"key": U})
check("items: by the transcript uuid, the session's open items only (an owner stored by name, a held one, one by owner_name)",
      st == 200 and ct == "application/json" and gids(body) == ["a1", "a2", "a3", "a4", "a7"], (st, body[:400]))
st, ct, body2 = server._client_get("items", {"key": "sparrow"}); check("items: by the pane name, the same", st == 200 and gids(body2) == gids(body), body2[:300])
st, ct, body3 = server._client_get("items", {"key": V}); check("items: another session sees only its own", st == 200 and gids(body3) == ["a6"], body3[:300])
st, ct, body4 = server._client_get("items", {"key": "nobody-at-all"}); check("items: a session that owns nothing: an empty list", st == 200 and json.loads(body4) == {"items": []}, body4)
x = {i["gid"]: i for i in json.loads(body)["items"]}
eb2, od2 = x["a2"].pop("expected_by"), x["a2"].pop("overdue")      # kept as keys, always empty (they go in a later release)
check("items: the fields", x["a2"] == {"gid": "a2", "shown": "a2", "subject": "[home] item 2", "needs": ["decision"], "contact": "", "next": "first\nsecond", "state_updated": 100.0, "confirmed": 200.0, "updated": 300.0, "held": False, "list": "your-move",
      "mover": {"kind": server._cfg.owner_mover_kind(), "who": server.OWNER}, "wait": "", "roles": ["then"]}, x["a2"])   # roles = the asking session's live roles (the owner's item, Oliver moves it: keeper only); the stored item state (derived here); the one rule's fields (waiting.py): whose move, by when
check("items: expected_by and overdue stay as keys and are always empty (no expected time is computed), wait is the empty string", eb2 is None and od2 is None and x["a2"]["wait"] == "" and all(i["expected_by"] is None for i in json.loads(body)["items"]), (eb2, od2))
check("items: held, from metadata.hold and from the retired status", x["a3"]["held"] and x["a4"]["held"] and not x["a1"]["held"], (x["a3"], x["a4"]))
check("items: an older file without the clocks: state_updated and updated null, confirmed from its fallback", x["a1"]["state_updated"] is None and x["a1"]["updated"] is None and x["a1"]["confirmed"] > 0, x["a1"])
for bad in ("", "a\nb", "x" * 201):
    st, ct, b = server._client_get("items", {"key": bad}); check(f"items refuses the key {bad[:6]!r}", st == 400, (st, b))
with TestClient(app) as c:
    r = c.get("/client/items", params={"key": U}); check("http: items without a token → 401", r.status_code == 401, r.status_code)
    r = c.get("/client/items", params={"key": U}, headers={"Authorization": "Bearer " + "y" * 43}); check("http: items with a wrong token → 401", r.status_code == 401, r.status_code)
    r = c.get("/client/items", params={"key": U}, headers=H)
    check("http: items with the machine's token", r.status_code == 200 and [i["gid"] for i in r.json()["items"]] == ["a1", "a2", "a3", "a4", "a7"] and r.headers["cache-control"] == "no-store", r.text[:200])
check("client.py knows the read", "items" in client.READS)

# ---- 7b. every row carries `list`, the home page's list the item is in (home.list_of), so the fleet tool's items sheet groups as the page does
X = "dddddddd-4444-4444-8444-444444444444"
(T / "fleet/a/sessions.json").write_text(json.dumps({U: {"name": "sparrow", "machine": "a"}, V: {"name": "home-other", "machine": "a"}, X: {"name": "home-lister", "machine": "a"}}))
item(21, X, meta={"needs": "decision", "then": X, "next": "home-lister: carry on"})                    # Oliver moves it: Your move
item(22, X)                                                                                           # an agent (X) moves it: Agents at work
item(23, X, meta={"wait_kind": "time", "wake": "2030-01-01", "then": X, "post_wake_mover": X})       # waiting on a time, X takes it after: Waiting
rows = {i["gid"]: i for i in json.loads(server._client_get("items", {"key": X})[2])["items"]}
check("items: list is your-move for an item Oliver moves, agents for one an agent moves, waiting for a wait",
      (rows.get("a21") or {}).get("list") == "your-move" and (rows.get("a22") or {}).get("list") == "agents" and (rows.get("a23") or {}).get("list") == "waiting",
      {g: r.get("list") for g, r in rows.items()})
check("items: every row of the list is one of the three words", rows and all(r.get("list") in ("your-move", "agents", "waiting") for r in rows.values()), {g: r.get("list") for g, r in rows.items()})
check("items: list is the home page's own reading of the item (home.list_of on the model)",
      all(r["list"] == server._home.list_of(server._model_of(dict(json.loads((T / f"store/a/{g[1:]}.json").read_text()), gid=g))) for g, r in rows.items()), rows)
for n in (21, 22, 23): (T / f"store/a/{n}.json").unlink()        # the later sections count the fixture's items
(T / "fleet/a/sessions.json").write_text(json.dumps({U: {"name": "sparrow", "machine": "a"}, V: {"name": "home-other", "machine": "a"}}))

# ---- 8. owner_name follows an owner change: update(owner=…) without owner_name left the old owner's
# name on the item, and the old owner's board check (items?key=, by owner or owner_name) kept asking about what it handed over
W = "cccccccc-3333-4333-8333-333333333333"                  # a uuid the fleet does not know
md = lambda n: json.loads((T / f"store/a/{n}.json").read_text())["metadata"]
item(8, V, meta={"owner_name": "home-other"}); item(9, V, meta={"owner_name": "home-other"})
server._update("a8", owner=U, sender="home-other"); m = md(8)
check("owner change: to a known session's uuid without owner_name, owner_name becomes the name the fleet knows", m["owner"] == U and m["owner_name"] == "sparrow", m)
st, ct, b = server._client_get("items", {"key": V}); st2, ct2, b2 = server._client_get("items", {"key": "home-other"})
check("owner change: the board check follows the mover, not the creator: the session that moves the item still lists it, by uuid or by name", "a8" in gids(b) and "a8" in gids(b2), (b[:300], b2[:300]))
st, ct, b = server._client_get("items", {"key": U}); check("owner change: …and the session named as creator now lists nothing for it", "a8" not in gids(b), b[:300])
server._update("a8", owner="home-other", sender="sparrow"); m = md(8)
check("owner change: to a pane name, stored as its uuid and the name as owner_name", m["owner"] == V and m["owner_name"] == "home-other", m)
_ho_was = dict(server._cfg.CFG.get("model") or {}); server._cfg.CFG["model"] = {**_ho_was, "handoff": False}      # this one check needs a session no pane of which exists: the hand-off's send-time guard (handoff suite) would refuse it
server._update("a8", owner=W, sender="home-other"); m = md(8)
check("owner change: to a uuid the fleet does not know, the old owner_name goes", m["owner"] == W and "owner_name" not in m, m)
server._update("a9", owner="home-retired", sender="home-other"); m = md(9)
server._cfg.CFG["model"] = _ho_was
check("owner change: to a name no live session carries, stored as given and as owner_name", m["owner"] == "home-retired" and m["owner_name"] == "home-retired", m)
server._update("a8", owner=U, owner_name="X", sender="home-other"); m = md(8)
check("owner change with owner_name: the given name is kept", m["owner"] == U and m["owner_name"] == "X", m)
server._update("a7", owner="cse_0123456789abcdef", sender="sparrow"); m = md(7)
check("owner re-passed unchanged without owner_name: the name it carries stays (a chat's name is only its owner_name)", m["owner_name"] == "sparrow", m)

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": client scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
