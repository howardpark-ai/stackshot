"""Scenario test for "a close marks the item's open next steps" (no closed item shows an open next step) — fixture data, no live store, no network, no server socket.

Before a close marked nothing: the steps still open stayed open on the closed item's checklist. Now:
  1  a close with outcome done marks every step still open DONE, by the closer, at the time of the close; dropped and superseded mark them DROPPED; steps marked in the same call keep their marks
     (done=[…] / dropped=[…] with the close win for their steps); steps already marked are untouched
  2  the server's own closes (a done check, the owner's "drop" on a watcher ask) mark the open steps the same way (done / dropped), by the server
  3  reopening is unchanged: the marks stay, the steps an OLD close left open are dropped, the new next is the open step; a closed item's checklist still refuses a mark
  4  the text agents learn it from (complete and update) says it
  5  the backfill: the server's start-up pass (server._close_marks_pass, once before it serves) marks the open steps of the items closed before (done for outcome done, dropped otherwise) by "stackshot (backfill)" at the item's close time,
     changes nothing else in the store, logs one line, and a second start does nothing; tools/close_marks_backfill.py is its read-only report (dry run, --json, no --apply, no --live)

    tests/run-suite close_marks        → exit 0 / 1"""
import json, logging, os, pathlib, re, subprocess, sys, time
BID_A = 9183
BID_B = 9184
BID_C = 9185
BID_D = 9186
BID_E = 9187
BID_F = 9188

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="closemarks-"); T = pathlib.Path(tmp)      # removed (and flock-held while the suite runs) by _scratch, pass or fail
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time(); DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
def proj(session, agents, back):
    return {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": session, "status": "active", "board": [], "board_open": 0, "agents": agents, "back_agents": back}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": proj("home-stew", {"home-front": "the front", "team-back": "the back"}, {"team-back": "the back"})}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
NEW = "- The thing works now\n- It lives here\n- Finished when it ships"
L3 = "home-front: build it\nhome-front: test it\nteam-back: tell the keeper"
def item(i, status="open", letter="g", close_at=None, **meta):
    base = {"owner": U["home-front"], "project": "projects/alpha", "next": L3}
    base.update(meta); base = {k: v for k, v in base.items() if v is not None}
    su = close_at or now0 - 10 * DAY
    (T / f"store/{letter}/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status,
                                                              "updated": su, "state_updated": su, "confirmed": su, "metadata": base}))
def rd(i, letter="g"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
def raw(i, letter="g"): return (T / f"store/{letter}/{i}.json").read_text()
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:1200]}" if got is not None else ""))
def sts(i): return [(x["status"], x.get("by") or "") for x in rd(i)["metadata"].get("steps") or []]
def kinds(i): return [k for k, _ in sts(i)]
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.model import steps as S
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
told: list = []
server._tell_woken = lambda gid, owner, note, tag="wake", result=None: told.append((gid, owner, note, tag))
server._tell_check_closed = lambda gid, item, label: []
def close(i, outcome="done", sup="", **kw):
    return server._update(f"board#{i}", status="completed", outcome=outcome, reason="it ended", description=NEW, superseded_by=sup, sender="home-front", **kw)
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except server.ToolError as e:
        check(name, all(w in str(e) for w in want), str(e))

# ================================================================ 1. a close marks the open steps
for i in (1, 2, 3, 4, 5, 6, 7, 8): item(i)
t0 = time.time()
close(1, "done")
check("close done: next is gone, every step is done, by the closer, at the time of the close", "next" not in rd(1)["metadata"] and kinds(1) == ["done"] * 3 and {b for _, b in sts(1)} == {"home-front"}
      and all(t0 - 1 <= x["at"] <= time.time() + 1 for x in rd(1)["metadata"]["steps"]), rd(1)["metadata"])
check("close done: no step of the closed item is open (view, as get and the page read it)", all(x["status"] != S.OPEN for x in S.view(rd(1)["metadata"], closed=True)), None)
close(2, "dropped")
check("close dropped: every step is dropped, by the closer", kinds(2) == ["dropped"] * 3 and {b for _, b in sts(2)} == {"home-front"}, sts(2))
close(3, "superseded", sup="board#1")
check("close superseded: every step is dropped, by the closer", kinds(3) == ["dropped"] * 3 and {b for _, b in sts(3)} == {"home-front"}, sts(3))
server._update("board#4", status="completed", outcome="dropped", reason="it ended", description=NEW, sender="home-front", done=[1])
check("a mark passed with the close wins for its step: done=[1] with outcome dropped → done, dropped, dropped", kinds(4) == ["done", "dropped", "dropped"], sts(4))
server._update("board#5", status="completed", outcome="done", reason="it ended", description=NEW, sender="home-front", dropped=["home-front: test it"])
check("a mark passed with the close wins for its step: dropped=[text] with outcome done → done, dropped, done", kinds(5) == ["done", "dropped", "done"], sts(5))
server._update("board#6", sender="home-front", done=[1])                       # one step done earlier, by update: the close leaves it as it is, marks the rest
at6 = rd(6)["metadata"]["steps"][0]["at"]
close(6, "dropped")
check("a step marked before the close is untouched (by, at, status); the others follow the outcome", kinds(6) == ["done", "dropped", "dropped"] and rd(6)["metadata"]["steps"][0]["at"] == at6, rd(6)["metadata"]["steps"])
g1 = server._fmt({**rd(1), "gid": "g1"})
check("get on the closed item lists a checklist with no open step", "checklist:" in g1 and "[open" not in g1 and "[done · home-front" in g1, g1[-400:])
item(8, next="home-front: one", steps=[{"text": "home-front: gone", "status": "open"}, {"text": "home-front: one", "status": "open"}])
close(8, "done")
check("a stored open step whose line already left next reads dropped (view), the one in next follows the outcome: dropped, done", kinds(8) == ["dropped", "done"], sts(8))

item(9); item(12)
mb9, mb12 = rd(9)["metadata"], rd(12)["metadata"]
server._update("board#9", status="completed", outcome="done", reason="it ended", description=NEW, sender="home-front", dropped=[2])
close(12, "done")
check("History and the mirror's comment (steps.changes): the mark a close puts by itself is no event, a step marked the other way in the same call is",
      S.changes(mb12, rd(12)["metadata"], True) == [] and S.changes(mb9, rd(9)["metadata"], True) == [("dropped", "home-front: test it")], (S.changes(mb12, rd(12)["metadata"], True), S.changes(mb9, rd(9)["metadata"], True)))

# ================================================================ 2. the server's own closes
item(10); item(11)
server._check_close("g10", rd(10), "a done check", time.time())
check("a done check's close marks the open steps done, by the server", kinds(10) == ["done"] * 3 and {b for _, b in sts(10)} == {server.NAME} and rd(10)["metadata"]["outcome"] == "done", sts(10))
it11 = rd(11); server._watch_close(it11, "dropped on his answer", time.time())
check("a watcher ask's drop marks the open steps dropped, by the server", [x["status"] for x in it11["metadata"]["steps"]] == ["dropped"] * 3 and it11["metadata"]["outcome"] == "dropped", it11["metadata"])

# ================================================================ 3. reopening and the closed item's checklist
refused("a mark on a closed item is refused: reopen it first", lambda: server._update("board#1", sender="home-front", done=[1]), "closed", "reopen")
check("…and the refusal wrote nothing", kinds(1) == ["done"] * 3, sts(1))
server._update("board#1", status="open", next="home-front: a fresh start", sender="home-front")
check("reopening: the marks the close made stay, the new next is the one open step", [x["status"] for x in S.view(rd(1)["metadata"])] == ["done"] * 3 + ["open"], rd(1)["metadata"])
item(9187, status="completed", outcome="dropped", reason="old", steps=[{"text": "home-front: old one", "status": "open"}, {"text": "home-front: old two", "status": "done", "by": "home-front", "at": now0 - 100}], next=None)
server._update(f"board#{BID_E}", status="open", next="home-front: back again", sender="home-front")
check("reopening an OLD close (steps left open) is unchanged: the steps left open are dropped, the new next is the open step",
      [x["status"] for x in S.view(rd(9187)["metadata"])] == ["dropped", "done", "open"], rd(9187)["metadata"])

# ================================================================ 4. the text
desc_ = {t.name: t.description for t in __import__("asyncio").run(server.mcp.list_tools())}
check("text: complete and update say a close marks the open steps, done or dropped by the outcome", all("marks every step" in desc_[n] and "dropped" in desc_[n] for n in ("complete", "update"))
      and "marks nothing" not in desc_["update"] + desc_["complete"] + desc_["get"], [n for n in ("complete", "update") if "marks every step" not in desc_[n]])

# ================================================================ 5. the backfill tool
CLOSE = now0 - 3 * DAY
OLD = lambda *t: [{"text": x, "status": "open"} for x in t]
item(9186, status="completed", close_at=CLOSE, outcome="done", reason="x", next=None, steps=[{"text": "home-front: shipped", "status": "done", "by": "home-front", "at": CLOSE - 60}, *OLD("home-front: A left open", "team-back: B left open")])
item(9183, status="completed", close_at=CLOSE, outcome="dropped", reason="x", next=None, steps=OLD("home-front: C left open"))
item(9188, status="completed", close_at=CLOSE, outcome="superseded", superseded_by=f"board#{BID_D}", reason="x", next=None, steps=OLD("home-front: D left open"))
item(9184, status="completed", close_at=CLOSE, next=None, steps=OLD("home-front: E left open, an old close with no outcome"))
item(34, status="completed", close_at=CLOSE, outcome="done", reason="x", next=None, steps=[{"text": "home-front: all marked", "status": "done", "by": "home-front", "at": CLOSE}])
item(35, status="completed", close_at=CLOSE, outcome="done", reason="x", next=None)                      # no steps at all
item(36, close_at=CLOSE, next="home-front: an open item", steps=OLD("home-front: an open item"))               # open: not the tool's
def snapshot(): return {p.name: p.read_text() for p in (T / "store/g").glob("*.json")}
before = snapshot()
tool = os.path.join(STACK, "stackshot/tools/close_marks_backfill.py"); cfg = f"{tmp}/stackshot.toml"
def run(*a):
    return subprocess.run([sys.executable, tool, *a], capture_output=True, text=True, env={**os.environ}, timeout=300)
# the earlier sections left their closed items in this store: the tool lists only what still has an open step, which is the fixtures above
d = run("--config", cfg)
lines = [l for l in d.stdout.splitlines() if l.strip()]
byitem = {l.split(" ")[0]: l for l in lines}
check("dry run: exit 0, one line for each closed item with an open step and no other", d.returncode == 0 and sorted(byitem) == sorted([f"board#{BID_D}", f"board#{BID_A}", f"board#{BID_F}", f"board#{BID_B}"]), (d.returncode, d.stdout, d.stderr[-400:]))
check("dry run: each line has the outcome, the mark and the steps", "(done)" in byitem.get(f"board#{BID_D}", "") and "would mark 2 steps done" in byitem[f"board#{BID_D}"] and "2. home-front: A left open" in byitem[f"board#{BID_D}"] and "3. team-back: B left open" in byitem[f"board#{BID_D}"]
      and "(dropped)" in byitem.get(f"board#{BID_A}", "") and "would mark 1 step dropped" in byitem[f"board#{BID_A}"] and "(superseded)" in byitem.get(f"board#{BID_F}", "") and "dropped" in byitem[f"board#{BID_F}"]
      and "(no outcome)" in byitem.get(f"board#{BID_B}", "") and "dropped" in byitem[f"board#{BID_B}"], d.stdout)
check("dry run: writes nothing", before == snapshot(), None)
dj = run("--config", cfg, "--json")
rows = json.loads(dj.stdout) if dj.returncode == 0 else []
check("dry run: --json is the rows", [r["item"] for r in rows] == [f"board#{BID_A}", f"board#{BID_B}", f"board#{BID_D}", f"board#{BID_F}"] and rows[2]["status"] == "done" and rows[0]["status"] == "dropped"
      and rows[2]["steps"] == [{"position": 2, "text": "home-front: A left open"}, {"position": 3, "text": "team-back: B left open"}], dj.stdout[:600])
check("the tool has no --apply and no --live any more: the server is the only writer", run("--apply").returncode == 2 and run("--live").returncode == 2 and before == snapshot(), None)
nc = run("--config", f"{tmp}/no-such.toml")
check("a config that is not there is an error", nc.returncode == 2 and "not a file" in nc.stderr, (nc.returncode, nc.stderr))
# the server's start-up pass (__main__ runs it once before it serves): in-process here, its log line on stderr
import io, contextlib
def start_pass():
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        got = server._close_marks_pass()
    return got, buf.getvalue()
got, log = start_pass()
check("start-up pass: marks the four items, and logs one line with the counts", [r["item"] for r in got] == [f"board#{BID_A}", f"board#{BID_B}", f"board#{BID_D}", f"board#{BID_F}"] and sum(1 for l in log.splitlines() if "migrate: close marks:" in l) == 1
      and "4 closed item(s)" in log and "5 open step(s)" in log and "2 done, 3 dropped" in log, (got, log[-600:]))
BY = "stackshot (backfill)"
s9032, s9020, s9037, s9030 = (rd(i)["metadata"]["steps"] for i in (9186, 9183, 9188, 9184))
check("start-up pass: outcome done → the open steps done, the done one untouched; by the backfill, at the item's close time",
      [x["status"] for x in s9032] == ["done", "done", "done"] and s9032[0]["by"] == "home-front" and s9032[0]["at"] == CLOSE - 60 and all(x["by"] == BY and x["at"] == CLOSE for x in s9032[1:]), s9032)
check("start-up pass: outcome dropped, superseded and none → dropped", [x["status"] for x in s9020 + s9037 + s9030] == ["dropped"] * 3 and all(x["by"] == BY and x["at"] == CLOSE for x in s9020 + s9037 + s9030), (s9020, s9037, s9030))
def no_steps(d_):
    d_ = json.loads(json.dumps(d_)); d_["metadata"].pop("steps", None); d_.pop("activity", None); return d_      # the item's activity clock (activity.py) is compared apart, below
check("start-up pass: nothing else in the file changed (same fields, same clocks)", all(no_steps(rd(i)) == no_steps(json.loads(before[f"{i}.json"])) for i in (9186, 9183, 9188, 9184)),
      [(i, no_steps(rd(i)), no_steps(json.loads(before[f"{i}.json"]))) for i in (9186, 9183, 9188, 9184) if no_steps(rd(i)) != no_steps(json.loads(before[f"{i}.json"]))])
check("start-up pass: the activity clock an item from before the field gains at its first save is its last update, not the pass's time",
      all(rd(i).get("activity") == max(json.loads(before[f"{i}.json"])["updated"], json.loads(before[f"{i}.json"])["state_updated"]) for i in (9186, 9183, 9188, 9184)), [(i, rd(i).get("activity")) for i in (9186, 9183, 9188, 9184)])
check("start-up pass: the items with no open step and the open item are as they were", all(raw(i) == before[f"{i}.json"] for i in (34, 35, 36)), None)
check("start-up pass: nothing else in the store changed (every other file byte for byte, no file added)", all(snapshot()[n] == before[n] for n in before if n not in ("9186.json", "9183.json", "9188.json", "9184.json")) and set(snapshot()) == set(before), None)
after_apply = snapshot()
again = run("--config", cfg)
check("a dry run after it finds nothing", again.returncode == 0 and not again.stdout.strip() and "0 closed items" in again.stderr, (again.stdout, again.stderr))
got2, log2 = start_pass()
check("a second start is idempotent: it marks nothing, writes no file and logs nothing", got2 == [] and "close marks" not in log2 and after_apply == snapshot(), (got2, log2[-300:]))
item(9185, status="completed", close_at=CLOSE, outcome="done", reason="x", next=None, steps=OLD("home-front: F left open, found by a later start"))
got3, _ = start_pass()
check("a later start marks an item closed meanwhile with an open step, and only it", [r["item"] for r in got3] == [f"board#{BID_C}"] and kinds(9185) == ["done"], got3)
g9186 = server._fmt({**rd(9186), "gid": "g9186"})
check("get on a backfilled item shows no open step", "checklist:" in g9186 and "[open" not in g9186, g9186[-400:])

print(("ok" if not fails else "FAILED") + f": close marks scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
