"""Scenario test for the project record, phase A of the permanent-id work (the design doc: stackshot keeps a project record with a permanent id) — fixture data, no live store, no network, no server
process (the server module is imported and called in-process, on a temporary config).

Covers: the permanent id (prj_<8 hex>) each page of the registry gets, minted once and the same after a restart, a registry rebuilt from
nothing, a page that went away and came back, and the server's start-time backfill; the lookup by id, full key and bare slug (and the
refusals: unknown, ambiguous); the published file <state>/projects.json (its shape, its stamp, an atomic write, no rewrite while it is fresh
and unchanged, a rewrite when a record changes and at least every few minutes, nothing written for an empty registry); the agents as records
(front and background, the role cut from the project's name, the mandate line, the old registry fields kept); `post project-agent` (the
keeper and a front agent may, a background agent, a stranger and an agent only registered here may not; the name, hub and conflict
refusals; the page line still owed, and the pending entry dropped once the page lists the name), over the server and through client.py;
and every API entry that takes a project taking its id (create, update, anchors, message, the client API's project and page-ts reads).

    tests/run-suite project_record        → exit 0 / 1"""
import contextlib, io, json, os, re, socket, subprocess, sys, pathlib, tempfile, logging, time, datetime
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="prjrectest-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "brain/infra", "secrets"): (T / d).mkdir(parents=True)
NAMES = ("home-sparrow", "home-sparrow-main", "home-sparrow-docs", "home-sparrow-engineer", "home-outsider", "home-beta", "home-sparrow-review", "home-sparrow-triage")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in U.items()}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
ALPHA = ("type: project\ntitle: Alpha\ndisplay-name: home-sparrow\nagents:\n  home-sparrow-main: talks to Oliver\n  home-sparrow-docs: keeps the docs\n"
         "  background:\n    home-sparrow-engineer: builds and merges\nstatus: active")
page("projects/alpha.md", ALPHA)
page("projects/alpha/sub.md", "type: project\ntitle: Sub")
page("ops/alpha-tool.md", "type: note\ntitle: Alpha tool\ndisplay-name: home-sparrow\nhub: projects/alpha")
page("projects/beta.md", "type: project\ntitle: Beta\ndisplay-name: home-beta\nstatus: active")
page("ops/beta.md", "type: note\ntitle: Beta ops\ndisplay-name: home-beta\nstatus: active")
page("projects/gamma.md", "type: project\ntitle: Gamma\ndisplay-name: home-gamma\nagents:\n  odd-name-review: reviews\nstatus: active")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))
ID = re.compile(r"^prj_[0-9a-f]{8}$")
def reg(): return json.loads((T / "store/projects.json").read_text())["pages"]
def idfile(): return json.loads((T / "store/project-record.json").read_text())
RECORD_FIELDS = {"id", "key", "keeper", "agents", "title", "name", "type", "hub", "scope", "scope_set", "listed", "listed_by", "sub_page", "items_30d", "status", "retired"}   # the four sala reads, then the picker's (tests/projects_picker_scenario.py)

# ---- 1. minting: the registry's pages get an id, once
import pages as p, projects as prj
p.cmd_registry(quiet=True); R = reg()
check("registry: every page has an id of the form prj_<8 hex>, all different", all(ID.match(e.get("id", "")) for e in R.values()) and len({e["id"] for e in R.values()}) == len(R) == 6, {k: e.get("id") for k, e in R.items()})
check("registry: every page carries its key as a field", all(e.get("key") == k for k, e in R.items()))
check("registry: the old fields are all still there (session, role, agents, back_agents, hub, status)", R["projects/alpha"]["session"] == "home-sparrow" and R["projects/alpha"]["role"] == "name"
      and R["projects/alpha"]["agents"] == {"home-sparrow-main": "talks to Oliver", "home-sparrow-docs": "keeps the docs", "home-sparrow-engineer": "builds and merges"}
      and R["projects/alpha"]["back_agents"] == {"home-sparrow-engineer": "builds and merges"} and R["ops/alpha-tool"]["hub"] == "projects/alpha" and R["projects/alpha"]["status"] == "active", R["projects/alpha"])
ids0 = {k: e["id"] for k, e in R.items()}
check("the id file holds id → key for every page, and it sits in the store (committed with it)", idfile()["ids"] == {i: k for k, i in ids0.items()} and idfile()["schema"] == 1, idfile())
st0 = (T / "store/project-record.json").stat().st_mtime_ns
p.cmd_registry(quiet=True)
check("a second registry build mints nothing: the same ids, the id file untouched", {k: e["id"] for k, e in reg().items()} == ids0 and (T / "store/project-record.json").stat().st_mtime_ns == st0)
# a restart: a fresh interpreter on the same config finds the same ids
code = f"import sys, json; sys.path.insert(0, {STACK!r}); import projects; print(json.dumps(projects.ensure_ids({sorted(ids0)!r} + ['projects/new-one'])))"
r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=os.environ)
out = json.loads(r.stdout) if r.returncode == 0 else {}
check("a fresh process (a restart) reads the same ids, and mints one for a key it has not seen", r.returncode == 0 and all(out[k] == ids0[k] for k in ids0) and ID.match(out.get("projects/new-one", "")), (r.stdout, r.stderr[-300:]))
new_one = out["projects/new-one"]
r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=os.environ)
check("…and that new id is the same the next time", json.loads(r.stdout)["projects/new-one"] == new_one)
(T / "store/projects.json").unlink(); p.cmd_registry(quiet=True)
check("a registry rebuilt from nothing keeps every id (the id file, not the registry, remembers)", {k: e["id"] for k, e in reg().items()} == ids0)
(T / "brain/projects/gamma.md").rename(T / "brain/projects/gamma.off"); p.cmd_registry(quiet=True)
check("a page that goes away leaves the registry but its id stays reserved in the id file", "projects/gamma" not in reg() and ids0["projects/gamma"] in idfile()["ids"])
(T / "brain/projects/gamma.off").rename(T / "brain/projects/gamma.md"); p.cmd_registry(quiet=True)
check("…and the page coming back gets the same id", reg()["projects/gamma"]["id"] == ids0["projects/gamma"])
page("projects/delta.md", "type: project\ntitle: Delta\ndisplay-name: home-delta\nstatus: active"); p.cmd_registry(quiet=True)
check("a new page gets a new id and no other id moves", ID.match(reg()["projects/delta"]["id"]) and reg()["projects/delta"]["id"] not in ids0.values()
      and all(reg()[k]["id"] == i for k, i in ids0.items()))
ids0["projects/delta"] = reg()["projects/delta"]["id"]
# the server's start-time backfill: a registry written before the ids existed
stripped = json.loads((T / "store/projects.json").read_text())
for e in stripped["pages"].values():
    for f in ("id", "key", "agent_records"): e.pop(f, None)
(T / "store/projects.json").write_text(json.dumps(stripped))
import server
server._publish = lambda: None
check("start-time backfill: stamps every page with its existing id (none minted afresh), once", server._prj.stamp_registry() is True
      and {k: e["id"] for k, e in reg().items()} == ids0 and server._prj.stamp_registry() is False, {k: e.get("id") for k, e in reg().items()})
check("the server's start runs the backfill before the first roles/projects write", "_prj.stamp_registry()" in open(f"{STACK}/server.py").read().split('def _start_background')[-1]
      and open(f"{STACK}/server.py").read().split('def _start_background')[-1].index("_prj.stamp_registry()") < open(f"{STACK}/server.py").read().split('def _start_background')[-1].index("_roles_sync_safe()"))
A_ID, B_ID, G_ID, SUB_ID, TOOL_ID = (ids0[k] for k in ("projects/alpha", "projects/beta", "projects/gamma", "projects/alpha/sub", "ops/alpha-tool"))

# ---- 2. lookup: one function, id or key
rec = prj.ref(A_ID)
check("ref(id) → the record {id, key, keeper, agents} plus the scope and listing fields", rec and set(rec) == RECORD_FIELDS and rec["key"] == "projects/alpha" and rec["id"] == A_ID and rec["keeper"] == "home-sparrow", rec)
check("ref(full key) → the same record", prj.ref("projects/alpha") == rec)
check("ref(bare slug) → the same record (a bare slug names a page in the first dir)", prj.ref("alpha") == rec)
check("project_ref is the name the design gives the lookup, in the module and in the server", prj.project_ref(A_ID) == rec and server.project_ref("alpha") == rec and server.project_ref(A_ID) == rec and server.project_ref("nope") is None)
check("ref: a trailing .md or slash is read away", prj.ref("projects/alpha.md") == rec and prj.ref("projects/alpha/") == rec)
check("ref: an ops page by its full key and by its bare slug", prj.ref("ops/alpha-tool")["id"] == TOOL_ID and prj.ref("alpha-tool")["key"] == "ops/alpha-tool")
check("ref: a sub-page has its own record and id", prj.ref("projects/alpha/sub")["id"] == SUB_ID and prj.ref(SUB_ID)["key"] == "projects/alpha/sub")
check("ref: an unknown key, an unknown id, a malformed id and an empty value → None", all(prj.ref(x) is None for x in ("projects/nowhere", "prj_00000000", "prj_zzzzzzzz", "", None, "  ")))
no_gamma = {k: v for k, v in reg().items() if k != "projects/gamma"}
check("ref: the id of a page that left the registry names nothing, and nor does its key", prj.ref(ids0["projects/gamma"], no_gamma) is None and prj.ref("projects/gamma", no_gamma) is None)
check("ref: a bare slug that names two pages gives the first in match order, and refs gives both", prj.ref("beta")["key"] == "projects/beta" and [r["key"] for r in prj.refs("beta")] == ["projects/beta", "ops/beta"])
check("to_key: an id → its key, a key stays, an unknown id stays as written", prj.to_key(A_ID) == "projects/alpha" and prj.to_key("projects/alpha") == "projects/alpha" and prj.to_key("prj_00000000") == "prj_00000000")

# ---- 3. the agents as records
ag = rec["agents"]
check("agents: {name: {front, role, mandate_line}} — a top-level entry is front, a background: entry is not", ag == {
    "home-sparrow-main": {"front": True, "role": "main", "mandate_line": "talks to Oliver"},
    "home-sparrow-docs": {"front": True, "role": "docs", "mandate_line": "keeps the docs"},
    "home-sparrow-engineer": {"front": False, "role": "engineer", "mandate_line": "builds and merges"}}, ag)
check("agents: a name that does not start with the project's name gets its last dash part as the role", prj.ref("gamma")["agents"] == {"odd-name-review": {"front": True, "role": "review", "mandate_line": "reviews"}}, prj.ref("gamma"))
check("agents: a page with no agents map has none; its keeper is still named", prj.ref("beta")["agents"] == {} and prj.ref("beta")["keeper"] == "home-beta")
check("agents: the registry holds the same records beside the old flat map", reg()["projects/alpha"]["agent_records"] == ag, reg()["projects/alpha"].get("agent_records"))

# ---- 4. the published file
PJ = T / "state/projects.json"
def pj(): return json.loads(PJ.read_text())
t0 = time.time()
real_replace, replaced = os.replace, []
os.replace = lambda a, b: (replaced.append((str(a), str(b), pathlib.Path(a).exists())), real_replace(a, b))[1]
try: w1 = server._projects_sync(now=t0)
finally: os.replace = real_replace
J = pj()
check("projects.json: written on the first call, atomically (a tmp file replaced onto it)", w1 is True and any(b == str(PJ) and ex and a.endswith(".tmp") for a, b, ex in replaced), replaced)
check("projects.json: {schema, generated, projects, by_key} and nothing else", set(J) == {"schema", "generated", "projects", "by_key"} and J["schema"] == 1, set(J))
check("projects.json: generated is a UTC stamp of the write (ISO, Z)", re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", J["generated"])
      and abs(datetime.datetime.fromisoformat(J["generated"].replace("Z", "+00:00")).timestamp() - t0) < 2, J["generated"])
check("projects.json: one record per page keyed by id, each exactly {id, key, keeper, agents} plus the scope and listing fields", set(J["projects"]) == set(ids0.values()) and all(set(r) == RECORD_FIELDS and J["projects"][r["id"]] is r for r in J["projects"].values())
      and all(i == r["id"] for i, r in J["projects"].items()), list(J["projects"].values())[:1])
check("projects.json: by_key maps every page key to its id", J["by_key"] == {k: i for k, i in ids0.items() if k in {r["key"] for r in J["projects"].values()}} and J["by_key"]["projects/alpha"] == A_ID, J["by_key"])
check("projects.json: the agents are the records (front, role, mandate_line)", J["projects"][A_ID]["agents"] == ag and J["projects"][A_ID]["keeper"] == "home-sparrow" and J["projects"][B_ID]["agents"] == {})
check("projects.json: the same content as the lookup", all(prj.ref(i) == r for i, r in J["projects"].items()))
mt = PJ.stat().st_mtime_ns
check("fresh and unchanged: not rewritten (150 s later)", server._projects_sync(now=t0 + 150) is False and PJ.stat().st_mtime_ns == mt and pj()["generated"] == J["generated"])
import runner as _runner_mod
SLOW_ROUND = 20.0       # a round of the minute set that takes this long (a slow tick ahead of the registry sync) still must not push a rewrite past the 5-minute promise
check("the refresh interval, with the fleet watch's 20-s pass and with the runner's one-minute pace and a slow round of 20 s, keeps the file no older than 5 minutes",
      prj.EVERY + 20 <= 300 and prj.EVERY + _runner_mod.PACE + SLOW_ROUND <= 300, (prj.EVERY, _runner_mod.PACE, SLOW_ROUND))
check("unchanged but older than the interval: rewritten with a new stamp and the same records", server._projects_sync(now=t0 + prj.EVERY + 1) is True
      and pj()["generated"] > J["generated"] and pj()["projects"] == J["projects"] and pj()["by_key"] == J["by_key"], (pj()["generated"], J["generated"]))
PJ.write_text(json.dumps({**pj(), "generated": "2999-01-01T00:00:00Z"}))
check("a stamp in the future (a clock set back) counts as stale: rewritten", server._projects_sync(now=t0 + 400) is True and pj()["generated"] < "2999", pj()["generated"])
PJ.write_text("not json")
check("a file that is unreadable is written again", server._projects_sync(now=t0 + 401) is True and pj()["schema"] == 1)
# a change in a page is a rewrite at once
page("projects/alpha.md", ALPHA.replace("  background:", "  home-sparrow-review: reviews the work\n  background:")); p.cmd_registry(quiet=True)
g = pj()["generated"]
check("a record that changed (a page gained an agent) is rewritten at once, however fresh the file", server._projects_sync(now=t0 + 402) is True and "home-sparrow-review" in pj()["projects"][A_ID]["agents"]
      and pj()["projects"][A_ID]["agents"]["home-sparrow-review"] == {"front": True, "role": "review", "mandate_line": "reviews the work"}, pj()["projects"][A_ID]["agents"])
check("…and the id of that project did not change", pj()["projects"][A_ID]["key"] == "projects/alpha" and pj()["by_key"]["projects/alpha"] == A_ID)
page("projects/alpha.md", ALPHA); p.cmd_registry(quiet=True); server._projects_sync(now=t0 + 403)
(T / "store/projects.json").rename(T / "store/projects.hold")
check("an empty registry writes nothing (a stale file is the reader's cue, an empty one would say there are no projects)", server._projects_sync(now=t0 + 9999) is False and pj()["projects"], pj()["generated"])
(T / "store/projects.hold").rename(T / "store/projects.json")
(T / "state/projects.json").unlink()
server._roles_sync_safe()
check("the roles pass (start, publish, the create gate, the fleet watch's 20-s tick) writes projects.json too", PJ.exists() and set(pj()["projects"]) == set(ids0.values())
      and "_projects_sync_safe(now)" in open(f"{STACK}/server.py").read().split("def _roles_sync_safe")[1].split("def _projects_sync")[0])
os.chmod(T / "state", 0o500)      # an unwritable state dir is logged, never raised: the board does not stop for it
try:
    err_real, sys.stderr = sys.stderr, io.StringIO(); server._projects_sync_safe(now=time.time() + 5000, force=True); logged = sys.stderr.getvalue()
finally: sys.stderr = err_real; os.chmod(T / "state", 0o700)
check("a write that fails is logged, not raised", "projects.json:" in logged or os.geteuid() == 0, logged)

# ---- 5. post project-agent
def post(project, name, sender, role="triage", front=True, mandate="sorts the incoming", raw=False):
    """sender: a session's name from the fixtures is sent as its transcript id (what $CLAUDE_CODE_SESSION_ID holds); raw=True sends it as written."""
    return server._client_post("box-c", "project-agent", {"project": project, "name": name, "role": role, "front": front, "mandate": mandate, "sender": sender if raw else U.get(sender, sender)})
def agents_of(pid): return prj.ref(pid)["agents"]
st, out = post(A_ID, "home-sparrow-triage", "home-sparrow")
check("the keeper may list an agent (project by id, the keeper by its transcript id): 200, listed in the record (nothing owed: the page's agents block is written from it)", st == 200 and out["page_owed"] is False and out["key"] == "projects/alpha" and out["project"] == A_ID
      and out["agent"] == {"home-sparrow-triage": {"front": True, "role": "triage", "mandate_line": "sorts the incoming"}}, (st, out))
check("…the reply says the record has it and the page follows", "in the project record" in out["note"] and out["mirror"]["state"] == "written", out.get("note"))
check("…the record has it (no page_owed), and the page now holds its line, written from the record", agents_of(A_ID)["home-sparrow-triage"] == {"front": True, "role": "triage", "mandate_line": "sorts the incoming"}
      and "home-sparrow-triage: sorts the incoming" in (T / "brain/projects/alpha.md").read_text(), agents_of(A_ID))
check("…and the published file shows it at once, with no page_owed", "page_owed" not in pj()["projects"][A_ID]["agents"]["home-sparrow-triage"] and "home-sparrow-triage" in pj()["projects"][A_ID]["agents"])
import project_registry as _prr
check("…and the entry keeps who asked and when, in the record only (no pending entry is made)", _prr.entries()[A_ID]["agents"]["home-sparrow-triage"]["by"] == U["home-sparrow"] and "at" in _prr.entries()[A_ID]["agents"]["home-sparrow-triage"]
      and "by" not in pj()["projects"][A_ID]["agents"]["home-sparrow-triage"] and "home-sparrow-triage" not in idfile()["pending_agents"].get(A_ID, {}))
st, out = post("projects/alpha", "home-sparrow-scribe", U["home-sparrow-docs"], role="scribe", front=False, mandate="writes it down")
check("a front agent may list one (by key, sender by transcript id); a background one lands under background: on the page", st == 200 and agents_of(A_ID)["home-sparrow-scribe"]["front"] is False
      and "home-sparrow-scribe" in p.split_agents(p.frontmatter_text((T / "brain/projects/alpha.md").read_text()).get("agents"))[1], (st, out))
st, out = post("alpha", "home-sparrow-late", U["home-sparrow"], role="late", mandate="by bare slug, keeper by id")
check("a bare slug works, and the keeper by transcript id", st == 200 and "home-sparrow-late" in agents_of(A_ID), (st, out))
st, out = post(A_ID, "home-sparrow-x", "home-sparrow-engineer")
check("a background agent may not: 403, naming the keeper and the front agents", st == 403 and "home-sparrow" in out["error"] and "home-sparrow-main" in out["error"] and "home-sparrow-docs" in out["error"] and "home-sparrow-x" not in agents_of(A_ID), (st, out))
st, out = post(A_ID, "home-sparrow-x", "home-outsider")
check("a stranger may not: 403", st == 403 and "home-sparrow-x" not in agents_of(A_ID), (st, out))
st, out = post(A_ID, "home-sparrow-ok", "home-sparrow-triage")
check("an agent the record lists is a listed agent like the page's own: a front one may list others (200)", st == 200 and "home-sparrow-ok" in agents_of(A_ID), (st, out))
st, out = post(A_ID, "home-sparrow-x", U["home-outsider"]); check("a stranger by transcript id: 403", st == 403)
st, out = post(A_ID, "home-sparrow-x", "no-such-session"); check("an unknown sender: 403", st == 403)
st, out = post(A_ID, "home-sparrow-x", "home-sparrow", raw=True)
check("the keeper's bare NAME is refused: a name proves nothing, the reason says to send the session id", st == 403 and "a name proves nothing" in out["error"] and "CLAUDE_CODE_SESSION_ID" in out["error"] and "home-sparrow-x" not in agents_of(A_ID), (st, out))
st, out = post(A_ID, "home-sparrow-x", "home-sparrow-docs", raw=True); check("a front agent's bare name is refused too", st == 403 and "a name proves nothing" in out["error"], (st, out))
st, out = post(A_ID, "home-sparrow-x", "00000000-0000-4000-8000-0000000000ff")
check("a transcript id the fleet does not know names nobody: 403 with that reason", st == 403 and "not a session in the fleet" in out["error"] and "home-sparrow-x" not in agents_of(A_ID), (st, out))
st, out = post(A_ID, "alpha-x", "home-sparrow"); check("a name with the project's slug but not its keeper name is refused when the name line exists", st == 400, (st, out))
st, out = post(A_ID, "home-sparrow-x", ""); check("no sender: 400", st == 400, (st, out))
st, out = post(B_ID, "home-beta-x", "home-sparrow"); check("the keeper of another project may not: 403", st == 403, (st, out))
# the first agent of a project with no entry yet: its page is read BEFORE _PROJECT_LOCK and the record's lock, so a slow page store holds up nobody else
import threading
import page_debt as _pdb
class SlowRead:
    def __init__(s, base, nap): s.b, s.nap = base, nap
    def get(s, k): r = s.b.get(k); time.sleep(s.nap); return r
    def __getattr__(s, n): return getattr(s.b, n)
NAPS = 1.5
assert B_ID not in _prr.entries(), "setup: beta has no entry yet"
server.PAGE_IO = SlowRead(_pdb.page_io(), NAPS); box = {}
th = threading.Thread(target=lambda: box.update(r=post(B_ID, "home-beta-main", "home-beta", role="main", mandate="talks")))
th.start(); time.sleep(0.2); held_up = 0.0
while th.is_alive():                                     # a second writer tries both locks all through the call: none of its page reads may sit inside either
    t1 = time.monotonic()
    with server._PROJECT_LOCK: prj.ensure_ids(["projects/alpha"])
    held_up = max(held_up, time.monotonic() - t1); time.sleep(0.1)
th.join(); server.PAGE_IO = None
check("server project-agent: the page of a project with no entry is read before _PROJECT_LOCK and the record's lock: a second writer takes both at once while the slow read runs (it waited far under the read's sleep)",
      held_up < NAPS / 3 and box["r"][0] == 200 and "home-beta-main" in prj.ref(B_ID)["agents"], (held_up, box))
st, out = post(B_ID, "home-beta-main", "home-beta", role="main", mandate="talks")
check("a project with no agents yet: its keeper lists the first one", st == 200 and prj.ref(B_ID)["agents"]["home-beta-main"]["role"] == "main", (st, out))
st, out = post("beta", "home-beta-z", "home-beta"); check("an ambiguous bare slug (projects/beta and ops/beta) is refused, asking for the key or the id", st == 400 and "ambiguous" in out["error"], (st, out))
st, out = post("projects/nowhere", "home-x", "home-sparrow"); check("an unknown project: 404", st == 404, (st, out))
st, out = post(SUB_ID, "home-sparrow-y", "home-sparrow"); check("a sub-page is refused, naming its hub page", st == 400 and "projects/alpha" in out["error"] and "hub page" in out["error"], (st, out))
st, out = post(TOOL_ID, "home-sparrow-y", "home-sparrow"); check("a page with a hub: line is refused, naming the hub", st == 400 and "projects/alpha" in out["error"], (st, out))
st, out = post(A_ID, "other-name", "home-sparrow"); check("a name that does not start with the project's name is refused (agents are <project>-<role>)", st == 400 and "home-sparrow-<role>" in out["error"], (st, out))
st, out = post(A_ID, "home alpha bad", "home-sparrow"); check("a name with spaces is refused", st == 400, (st, out))
st, out = post(A_ID, "home-sparrow-n", "home-sparrow", mandate="two\nlines"); check("a mandate with a line break is refused", st == 400, (st, out))
st, out = post(A_ID, "home-sparrow-n", "home-sparrow", role="bad role"); check("a role with a space is refused", st == 400, (st, out))
st, out = post(A_ID, "home-sparrow-n", "home-sparrow", mandate=""); check("an empty mandate is refused", st == 400, (st, out))
st, out = server._client_post("box-c", "project-agent", {"project": A_ID, "name": "home-sparrow-n", "role": "n", "mandate": "m", "sender": U["home-sparrow"]}); check("front missing: 400", st == 400, (st, out))
st, out = post(A_ID, "home-sparrow-main", "home-sparrow", role="main", mandate="talks to Oliver")
check("a name the page lists, said again as it is: 200, nothing owed, nothing changed", st == 200 and out["page_owed"] is False and "nothing changed" in out["note"] and "page_owed" not in agents_of(A_ID)["home-sparrow-main"], (st, out))
st, out = post(A_ID, "home-sparrow-main", "home-sparrow", role="main", mandate="something else")
check("a name the project lists, said differently: 409 (retire it or rename it first)", st == 409 and "already listed" in out["error"] and agents_of(A_ID)["home-sparrow-main"]["mandate_line"] == "talks to Oliver", (st, out))
st, out = post(A_ID, "home-sparrow-triage", "home-sparrow", mandate="sorts everything", role="triage")
check("a listed agent said again with another mandate is the 409 (retire it or rename it first); the record keeps the old line", st == 409 and agents_of(A_ID)["home-sparrow-triage"]["mandate_line"] == "sorts the incoming", (st, out))
# a page edit after the agent was listed is not read: the record is the authority, and the next mirror write restores the page
(T / "brain/projects/alpha.md").write_text((T / "brain/projects/alpha.md").read_text().replace("home-sparrow-triage: sorts the incoming", "home-sparrow-triage: edited on the page")); p.cmd_registry(quiet=True)
server._projects_sync(now=time.time() + 100)
check("a page edit to a mirrored line is not read: the record's mandate stays", agents_of(A_ID)["home-sparrow-triage"]["mandate_line"] == "sorts the incoming", agents_of(A_ID))
st, out = post(A_ID, "home-sparrow-after", "home-sparrow-triage", role="after", mandate="a listed front agent")
check("…and the next write to the project's agents block restores the page's line from the record", st == 200 and "home-sparrow-after" in agents_of(A_ID) and "home-sparrow-triage: sorts the incoming" in (T / "brain/projects/alpha.md").read_text()
      and "edited on the page" not in (T / "brain/projects/alpha.md").read_text(), (st, out))

# ---- 6. the HTTP API and client.py
import client
from starlette.testclient import TestClient
me = socket.gethostname(); tok = open(client.mint(me)).read().strip(); H = {"Authorization": "Bearer " + tok}
app = server.mcp.http_app()
with TestClient(app) as c:
    r = c.get("/client/project", params={"key": A_ID}); check("http: project without a token → 401", r.status_code == 401, r.status_code)
    for how, k in (("id", A_ID), ("full key", "projects/alpha"), ("bare slug", "alpha")):
        r = c.get("/client/project", params={"key": k}, headers=H)
        check(f"http: GET project by {how}", r.status_code == 200 and r.json()["id"] == A_ID and r.json()["key"] == "projects/alpha" and r.json()["agents"]["home-sparrow-main"]["role"] == "main" and r.headers["cache-control"] == "no-store", r.text[:200])
    r = c.get("/client/project", params={"key": "projects/nowhere"}, headers=H); check("http: GET project, unknown → 404", r.status_code == 404, r.text)
    r = c.get("/client/project", params={"key": "beta"}, headers=H); check("http: GET project, ambiguous slug → 400 naming both", r.status_code == 400 and "projects/beta" in r.text and "ops/beta" in r.text, r.text)
    r = c.get("/client/project", headers=H); check("http: GET project with no key → 400", r.status_code == 400, r.text)
    r = c.get("/client/page-ts", params={"key": A_ID}, headers=H); check("http: page-ts takes the project's id too", r.status_code == 200 and r.json()["key"] == "projects/alpha" and r.json()["ts"], r.text)
    r = c.get("/client/registry", headers=H); check("http: the registry served carries each page's id and key", r.json()["pages"]["projects/alpha"]["id"] == A_ID and r.json()["pages"]["projects/alpha"]["key"] == "projects/alpha")
    r = c.post("/client/project-agent", json={"project": A_ID, "name": "home-sparrow-http", "role": "http", "front": True, "mandate": "over http", "sender": U["home-sparrow"]})
    check("http: project-agent without a token → 401", r.status_code == 401 and "home-sparrow-http" not in agents_of(A_ID), r.status_code)
    r = c.post("/client/project-agent", json={"project": A_ID, "name": "home-sparrow-http", "role": "http", "front": True, "mandate": "over http", "sender": U["home-sparrow"]}, headers=H)
    check("http: project-agent with a machine token → 200 and the note", r.status_code == 200 and r.json()["page_owed"] is False and "home-sparrow-http" in agents_of(A_ID), r.text)
    r = c.post("/client/project-agent", json={"project": A_ID, "name": "home-sparrow-http2", "role": "http", "front": True, "mandate": "no", "sender": U["home-outsider"]}, headers=H)
    check("http: a refusal is 403 with the reason", r.status_code == 403 and "neither the keeper" in r.json()["error"], r.text)
    r = c.post("/client/project-agent", json={"project": A_ID}, headers=H); check("http: missing fields → 400", r.status_code == 400, r.text)
    import urllib.request, urllib.error
    class _Resp:
        def __init__(s, r): s.status = r.status_code; s._b = r.content
        def read(s): return s._b
        def __enter__(s): return s
        def __exit__(s, *a): return False
    def fake_urlopen(req, timeout=0):
        path = req.full_url.replace(client.server_url(), "")
        r = c.post(path, content=req.data, headers=dict(req.header_items())) if req.get_method() == "POST" else c.get(path, headers=dict(req.header_items()))
        if r.status_code >= 400: raise urllib.error.HTTPError(req.full_url, r.status_code, "x", {}, io.BytesIO(r.content))
        return _Resp(r)
    client.urllib.request.urlopen = fake_urlopen
    def run(*argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): rc = client.main(["client.py", *argv])
        return rc, buf.getvalue()
    rc, o = run("get", "project", A_ID); check("client.py get project <id>: the record as JSON, exit 0", rc == 0 and json.loads(o)["key"] == "projects/alpha", (rc, o[:200]))
    rc, o = run("get", "project", "projects/alpha"); check("client.py get project <key>", rc == 0 and json.loads(o)["id"] == A_ID, (rc, o[:200]))
    rc, o = run("get", "project", "alpha"); check("client.py get project <bare slug>", rc == 0 and json.loads(o)["id"] == A_ID, (rc, o[:200]))
    rc, o = run("get", "project", "projects/nowhere"); check("client.py get project, unknown: exit 1 with the status", rc == 1 and o.startswith("[404]"), (rc, o))
    st, body = client.get("page-ts", A_ID); check("client.get page-ts passes a project id", st == 200 and json.loads(body)["key"] == "projects/alpha", (st, body))
    rc, o = run("post", "project-agent", A_ID, "home-sparrow-cli", "--role", "cli", "--front", "--mandate", "added by the client", "--sender", U["home-sparrow"])
    check("client.py post project-agent: exit 0, the note printed, recorded", rc == 0 and "in the project record" in o and agents_of(A_ID)["home-sparrow-cli"] == {"front": True, "role": "cli", "mandate_line": "added by the client"}, (rc, o, agents_of(A_ID).get("home-sparrow-cli")))
    rc, o = run("post", "project-agent", "alpha", "home-sparrow-cli2", "--role", "cli", "--back", "--mandate", "background", "--sender", U["home-sparrow-docs"])
    check("client.py post project-agent --back: a background agent, the sender by transcript id", rc == 0 and agents_of(A_ID)["home-sparrow-cli2"]["front"] is False, (rc, o))
    os.environ["CLAUDE_CODE_SESSION_ID"] = U["home-sparrow"]
    rc, o = run("post", "project-agent", A_ID, "home-sparrow-env", "--role", "env", "--front", "--mandate", "sender from the environment")
    check("client.py post project-agent: with no --sender, the session is $CLAUDE_CODE_SESSION_ID", rc == 0 and "home-sparrow-env" in agents_of(A_ID), (rc, o))
    os.environ["CLAUDE_CODE_SESSION_ID"] = U["home-outsider"]
    rc, o = run("post", "project-agent", A_ID, "home-sparrow-env2", "--role", "env", "--front", "--mandate", "stranger")
    check("client.py post project-agent: a stranger's refusal is printed with its status, exit 1", rc == 1 and o.startswith("stackshot: agent not listed [403]") and "home-sparrow-env2" not in agents_of(A_ID), (rc, o))
    os.environ.pop("CLAUDE_CODE_SESSION_ID")
    rc, o = run("post", "project-agent", A_ID, "home-sparrow-env3", "--role", "env", "--front", "--mandate", "nobody asks")
    check("client.py post project-agent: no sender at all is refused before any call", rc == 1 and "--sender" in o and "home-sparrow-env3" not in agents_of(A_ID), (rc, o))
    for bad in (["post", "project-agent", A_ID, "home-sparrow-e", "--role", "e", "--mandate", "m"], ["post", "project-agent", A_ID, "home-sparrow-e", "--role", "e", "--front", "--back", "--mandate", "m", "--sender", U["home-sparrow"]],
                ["post", "project-agent", A_ID, "--role", "e", "--front", "--mandate", "m", "--sender", U["home-sparrow"]], ["post", "project-agent", A_ID, "home-sparrow-e", "--front", "--mandate", "m", "--sender", U["home-sparrow"]]):
        rc, o = run(*bad); check(f"client.py post project-agent misuse → usage, exit 1 ({' '.join(bad[3:])[:40]})", rc == 1 and "usage: client.py post project-agent" in o, (rc, o))

# ---- 7. every entry that takes a project takes its id
def create(project, owner, **kw): return server.stackshot_create(subject="[home] a thing", description="- Goal: A thing\n- It lives here\n- Done when done", project=project, owner=owner, **{"next": f"{owner}: carry on", **kw})
r = create(A_ID, "home-sparrow-main", next="home-sparrow-engineer: carry on"); gid = r.split()[1]
gid = server._norm_id(gid)
check("create: project = the id; the item stores the page's key (the replies and the store keep writing the key)", server._load(gid)["metadata"]["project"] == "projects/alpha", server._load(gid)["metadata"])
check("create: …and the item is on the project, as any key-filed item", server._anc.project_of(server._load(gid)) == "projects/alpha" and "projects/alpha" in r and A_ID not in r, r)
try: create("prj_00000000", "home-sparrow-main"); r2 = ""
except server.ToolError as e: r2 = str(e)
check("create: an id that names no page is refused as an unknown project is", "names no page" in r2, r2)
r = create("projects/beta", "home-beta", mover="home-beta"); gid2 = server._norm_id(r.split()[1])
try: out = server.stackshot_update(item_id=gid2, project=A_ID, sender="home-sparrow-main", owner="home-sparrow-main"); r3 = ""
except server.ToolError as e: r3 = str(e)
check("update: project = the id moves the item there, stored as the key", server._load(gid2)["metadata"]["project"] == "projects/alpha" and not r3, (r3, server._load(gid2)["metadata"]))
r4 = server.stackshot_anchors(project=A_ID); r5 = server.stackshot_anchors(project="projects/alpha")
check("anchors: the id lists the same as the key", r4 == r5 and r4, (r4, r5))
URL = "https://x.slack.com/archives/C0000000009"
server.stackshot_anchors(project=A_ID, add=[URL])
check("anchors: add by id lands on the page's key", [e["url"] for e in server._anc.load().get("projects/alpha", [])] == [URL] and A_ID not in server._anc.load(), server._anc.load())
server.stackshot_anchors(project=A_ID, remove=[URL])
check("anchors: remove by id", not server._anc.load().get("projects/alpha"), server._anc.load())
try: server.stackshot_anchors(project="prj_00000000"); r6 = ""
except server.ToolError as e: r6 = str(e)
check("anchors: an unknown id is refused as an unknown project is", "names no page" in r6, r6)
pushlog = T / "push.log"
(T / "fakepush.py").write_text("import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\n"
                               f"open({str(pushlog)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered → ' + a[0])\n")
server._PUSH = [sys.executable, str(T / "fakepush.py")]
r7 = server._message(A_ID, "hello alpha, by id", "home-outsider")
pushes = [json.loads(l) for l in pushlog.read_text().splitlines()] if pushlog.exists() else []
import routing
check("message: to = the project's id is held for the router as to its key (every project is the router's), delivered to no session, the keeper's name included", r7.startswith("held for the router") and not pushes, (r7, pushes[-1:]))
check("message: …and it is on the project's routing log under the key, with no recipient", any(n.get("label") == "message to projects/alpha" and n.get("live") is True and not n.get("to") for n in routing.read("projects/alpha")), routing.read("projects/alpha")[-1:])
try: server._message("prj_00000000", "x", "home-outsider"); r8 = ""
except server.ToolError as e: r8 = str(e)
check("message: an unknown id is refused like an unknown session", r8.startswith("Refused"), r8)
check("the client API: items?key= is a session's, not a project's — unchanged (a project id is no session)", server._client_get("items", {"key": "home-sparrow-main"})[0] == 200
      and json.loads(server._client_get("items", {"key": A_ID})[2])["items"] == [])
check("the client API's read list names project", "project?key=" in server._client_get("nothing", {})[2])

# ---- 8. a damaged or lost id file never re-mints (review of the first build: a torn file once minted every id afresh)
REC = T / "store/project-record.json"
good = REC.read_bytes(); all_keys = list(reg())
ids_now = {k: e["id"] for k, e in reg().items()}
def raises(f, *a):
    try: f(*a); return ""
    except ValueError as e: return str(e)
for label, bad in (("truncated (torn) JSON", good[: len(good) // 2]), ("not JSON at all", b"\x00garbage"), ("a list", b"[]"), ("ids not an object", b'{"schema": 1, "ids": [], "pending_agents": {}}'),
                   ("an id that is no id", json.dumps({**json.loads(good), "ids": {**json.loads(good)["ids"], "prj_nothex!!": "projects/x"}}).encode()),
                   ("an id with no key", json.dumps({**json.loads(good), "ids": {**json.loads(good)["ids"], "prj_0000000a": ""}}).encode()),
                   ("a pending map of the wrong shape", json.dumps({**json.loads(good), "pending_agents": {A_ID: {"x": "not an object"}}}).encode()),
                   ("a schema this code does not read", json.dumps({**json.loads(good), "schema": 2}).encode())):
    REC.write_bytes(bad)
    err = raises(prj.ensure_ids, all_keys + ["projects/never-seen"])
    check(f"id file {label}: ensure_ids raises, mints nothing, and leaves the file exactly as it was", err and REC.read_bytes() == bad, (err, REC.read_bytes()[:80]))
REC.write_bytes(good[: len(good) // 2])
check("a damaged id file: add_pending, rename and prune raise too, and write nothing", all(raises(f, *a) for f, a in ((prj.add_pending, (A_ID, "home-sparrow-zz", {"front": True, "role": "z", "mandate_line": "m"})), (prj.rename, ("projects/beta", "projects/beta2")), (prj.prune_pending, (reg(),))))
      and REC.read_bytes() == good[: len(good) // 2])
st, out = post(A_ID, "home-sparrow-zz", "home-sparrow")
check("a damaged id file: post project-agent is not accepted (nothing recorded), the server stays up", st in (400, 403, 500, 503) and REC.read_bytes() == good[: len(good) // 2], (st, out))
check("a damaged id file: the lookup still answers from the registry's own copy of the ids (key and id)", prj.ref("projects/alpha")["id"] == A_ID and prj.ref(A_ID)["key"] == "projects/alpha" and prj.to_key(B_ID) == "projects/beta")
check("a damaged id file: the published file is still written, with the same ids", server._projects_sync(now=time.time() + 5000, force=True) is True and pj()["by_key"]["projects/alpha"] == A_ID and set(pj()["projects"]) == set(ids_now.values()))
p.cmd_registry(quiet=True)
check("a damaged id file: the registry rebuild keeps every id the old registry carried (the second copy survives) and mints none", {k: e["id"] for k, e in reg().items()} == ids_now and REC.read_bytes() == good[: len(good) // 2])
err_real, sys.stderr = sys.stderr, io.StringIO()
try: stamped = prj.stamp_registry()
except ValueError: stamped = "raised"
finally: sys.stderr = err_real
check("a damaged id file: the start-time backfill raises (the server logs it) and touches nothing", stamped == "raised" and REC.read_bytes() == good[: len(good) // 2])
REC.write_bytes(good)
check("…and with the file back, everything reads as before", prj.ensure_ids(all_keys) == ids_now)
# lost file: restored from the registry's id fields
REC.unlink()
got = prj.ensure_ids(all_keys + ["projects/after-the-loss"])
check("a lost id file: the registry's own ids restore it, the old ids come back and only the unseen key is new", all(got[k] == ids_now[k] for k in all_keys) and ID.match(got["projects/after-the-loss"]) and got["projects/after-the-loss"] not in ids_now.values(), got)
check("…and the file is written again with every old id in it", {i: k for k, i in ids_now.items()}.items() <= idfile()["ids"].items(), idfile()["ids"])
REC.unlink(); p.cmd_registry(quiet=True)
check("a lost id file, then the registry rebuild: every page keeps its id", {k: e["id"] for k, e in reg().items()} == ids_now)
# pending agents survive a rewrite, and unknown top-level fields are kept
doc = json.loads(REC.read_text()); doc["note"] = "kept by a newer writer"; doc["pending_agents"] = {A_ID: {"home-sparrow-keep": {"front": True, "role": "keep", "mandate_line": "stays", "by": U["home-sparrow"]}}}
REC.write_text(json.dumps(doc)); prj.ensure_ids(["projects/fresh-one"])
check("a rewrite keeps the unknown top-level fields and the pending agents as they were", idfile().get("note") == "kept by a newer writer" and idfile()["pending_agents"][A_ID]["home-sparrow-keep"]["by"] == U["home-sparrow"], idfile())

# ---- 9. the id follows a page rename
pend_before = {"home-sparrow-keep"}
oid = prj.rename("projects/beta", "projects/beta2")
check("rename: returns the id, which now stands for the new key; the old key no longer has it", oid == B_ID and idfile()["ids"][B_ID] == "projects/beta2" and prj.to_key(B_ID) == "projects/beta2")
(T / "brain/projects/beta.md").rename(T / "brain/projects/beta2.md"); p.cmd_registry(quiet=True)
check("rename: after the page move the registry lists the new key under the OLD id, and the new key got no fresh id", reg()["projects/beta2"]["id"] == B_ID and "projects/beta" not in reg()
      and sum(1 for k in idfile()["ids"].values() if k == "projects/beta2") == 1, reg().get("projects/beta2"))
check("rename: the old id resolves to the new key, by lookup, and in the published file", prj.ref(B_ID)["key"] == "projects/beta2" and prj.ref("projects/beta2")["id"] == B_ID
      and (server._projects_sync(now=time.time() + 6000, force=True), pj()["projects"][B_ID]["key"])[1] == "projects/beta2" and pj()["by_key"]["projects/beta2"] == B_ID and "projects/beta" not in pj()["by_key"])
prj.add_pending(B_ID, "home-beta-p", {"front": True, "role": "p", "mandate_line": "m"}, by="x"); rid = prj.rename("projects/beta2", "projects/beta3")
(T / "brain/projects/beta2.md").rename(T / "brain/projects/beta3.md"); p.cmd_registry(quiet=True)
check("rename: the id's pending agents travel with it", rid == B_ID and "home-beta-p" in prj.ref(B_ID)["agents"] and prj.ref(B_ID)["key"] == "projects/beta3", prj.ref(B_ID))
check("rename: an unknown key, the same key twice and an empty key are refused", all(raises(prj.rename, a, b) for a, b in (("projects/never-heard-of", "projects/x"), ("projects/beta3", "projects/beta3"), ("", "projects/x"))))
# the copy was published before the stub: the new key already has an id of its own; the two swap, none is dropped
page("projects/swap-old.md", "type: project\ntitle: Old\ndisplay-name: home-swap\nstatus: active"); page("projects/swap-new.md", "type: project\ntitle: New\ndisplay-name: home-swap\nstatus: active"); p.cmd_registry(quiet=True)
so, sn = reg()["projects/swap-old"]["id"], reg()["projects/swap-new"]["id"]
prj.rename("projects/swap-old", "projects/swap-new")
check("rename onto a key that already has its own id: the moved page keeps the old id, the dead key takes the other, no id is dropped", idfile()["ids"][so] == "projects/swap-new" and idfile()["ids"][sn] == "projects/swap-old"
      and prj.ids_by_key()["projects/swap-new"] == so, idfile()["ids"])
(T / "brain/projects/swap-old.md").unlink(); p.cmd_registry(quiet=True)
check("…and the registry after the old page is gone: the new key is under the old id", reg()["projects/swap-new"]["id"] == so and "projects/swap-old" not in reg())
r = subprocess.run([sys.executable, f"{STACK}/projects.py", "rename", "projects/swap-new", "projects/swap-final"], capture_output=True, text=True, env=os.environ)
check("python3 projects.py rename <old> <new> moves the id (exit 0) and says so", r.returncode == 0 and so in r.stdout and idfile()["ids"][so] == "projects/swap-final", (r.stdout, r.stderr[-200:]))
r = subprocess.run([sys.executable, f"{STACK}/projects.py", "rename", "projects/no-such", "projects/x"], capture_output=True, text=True, env=os.environ)
check("…and exits non-zero with the reason for a key with no id; a wrong usage prints the usage", r.returncode != 0 and "no project id" in r.stderr
      and subprocess.run([sys.executable, f"{STACK}/projects.py"], capture_output=True, text=True, env=os.environ).returncode != 0)
# rename_page.py's stub step moves the id: the whole copy → stub run, against an in-memory gbrain
page("projects/mover.md", "type: project\ntitle: Mover\ndisplay-name: home-mover\nstatus: active"); p.cmd_registry(quiet=True)
MV = reg()["projects/mover"]["id"]
import rename_page as rp
mem = {"projects/mover": ("---\ntype: project\ntitle: Mover\ndisplay-name: home-mover\nstatus: active\nagents:\n  home-mover-main: keeps it\n---\n\n# Mover\n\n<!-- timeline -->\n\n## Timeline\n", "r1")}
def fake_gb(args, stdin=None):
    if args[:2] == ["call", "get_page"]:
        slug = json.loads(args[2])["slug"]
        return (0, json.dumps({"content": mem[slug][0], "revision": mem[slug][1]})) if slug in mem else (0, '{"error": "not found"}')
    if args[0] == "put": mem[args[1]] = (stdin, "r" + str(len(mem) + 10)); return 0, '{"ok": true}'
    return 1, "unexpected"
rp.gb = fake_gb
def run_rp(verb):
    sys.argv = ["rename_page.py", verb, "projects/mover=projects/moved"]; out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out): rp.main()
        return 0, out.getvalue()
    except SystemExit as e: return (e.code or 0), out.getvalue()
rc1, o1 = run_rp("copy"); idb = dict(idfile()["ids"])
check("rename_page copy: moves no id yet (the old page is still the page)", rc1 == 0 and idb[MV] == "projects/mover", (rc1, o1))
rc2, o2 = run_rp("stub")
check("rename_page stub: the old page becomes a stub and the project's id moves to the new key, said in the output", rc2 == 0 and "stub projects/mover → projects/moved" in o2 and f"project id {MV} now stands for projects/moved" in o2
      and idfile()["ids"][MV] == "projects/moved" and set(idfile()["ids"]) == set(idb), (rc2, o2, idfile()["ids"].get(MV)))
(T / "brain/projects/mover.md").rename(T / "brain/projects/moved.md"); p.cmd_registry(quiet=True)
check("…and the registry rebuilt after the move: the new key has the old id, no new id was minted", reg()["projects/moved"]["id"] == MV and set(idfile()["ids"]) == set(idb))
# a failure to move the id is loud (exit 1, the command to run), never silent
page("projects/mover2.md", "type: project\ntitle: Mover2\ndisplay-name: home-mover\nstatus: active")
mem["projects/mover2"] = ("---\ntype: project\ntitle: Mover2\ndisplay-name: home-mover\nstatus: active\nagents:\n  home-mover-main: keeps it\n---\n\n# Mover2\n\n<!-- timeline -->\n\n## Timeline\n", "r2")
sys.argv = ["rename_page.py", "copy", "projects/mover2=projects/moved2"]
with contextlib.redirect_stdout(io.StringIO()): 
    try: rp.main()
    except SystemExit: pass
REC.write_bytes(b"{torn")
sys.argv = ["rename_page.py", "stub", "projects/mover2=projects/moved2"]; out = io.StringIO()
try:
    with contextlib.redirect_stdout(out): rp.main()
    rc3 = 0
except SystemExit as e: rc3 = e.code or 0
check("rename_page stub: when the id cannot be moved (a damaged id file) it says so with the command to run and exits 1", rc3 == 1 and "project id of projects/mover2 not moved" in out.getvalue() and "projects.py rename projects/mover2 projects/moved2" in out.getvalue(), (rc3, out.getvalue()))
REC.write_bytes(good)

# ---- 10. post project-agent: the details the review asked for
page("projects/noname.md", "type: project\ntitle: No name line\nagents:\n  noname-main: talks\nstatus: active"); p.cmd_registry(quiet=True)
NS = reg()["projects/noname"]["id"]
check("(setup) a page with no name line has no keeper, and its listed front agent is the one who may add", prj.ref(NS)["keeper"] == "" and "noname-main" in prj.ref(NS)["agents"])
(T / "fleet/a/sessions.json").write_text(json.dumps({**{u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in U.items()}, "00000000-0000-4000-8000-0000000000aa": {"name": "noname-main", "machine": "a", "url": "", "seen": "x"}}))
NSM = "00000000-0000-4000-8000-0000000000aa"
st, out = server._client_post("box-c", "project-agent", {"project": NS, "name": "other-name", "role": "x", "front": True, "mandate": "m", "sender": NSM})
check("a page with no name line still requires <slug>-<role> (here noname-<role>)", st == 400 and "noname-<role>" in out["error"], (st, out))
st, out = server._client_post("box-c", "project-agent", {"project": NS, "name": "noname-docs", "role": "docs", "front": True, "mandate": "keeps docs", "sender": NSM})
check("…and a name that follows the slug is accepted", st == 200 and out["page_owed"] is False, (st, out))
st, out = post(A_ID, "home-sparrow-claimed", "home-sparrow", role="one", mandate="first claim")
st2, out2 = post(A_ID, "home-sparrow-claimed", "home-sparrow-docs", role="two", mandate="a different claim")
check("another session's entry is not overwritten with different values: 409 (it is already listed), the record keeps the first claim", st == 200 and st2 == 409 and "already listed" in out2["error"] and agents_of(A_ID)["home-sparrow-claimed"]["mandate_line"] == "first claim", (st2, out2))
st3, out3 = post(A_ID, "home-sparrow-claimed", "home-sparrow-docs", role="one", mandate="first claim")
check("…the same values from another session are accepted as they stand (the first claimant stays on record); another mandate is a 409 even from the first claimant", st3 == 200 and _prr.entries()[A_ID]["agents"]["home-sparrow-claimed"]["by"] == U["home-sparrow"] and post(A_ID, "home-sparrow-claimed", "home-sparrow", role="one", mandate="first claim, reworded")[0] == 409
      and agents_of(A_ID)["home-sparrow-claimed"]["mandate_line"] == "first claim", (st3, out3))
check("an agent listed through project-agent is published with front as asked and no page_owed; the docstring still says readers must check page_owed (a leftover pending agent carries it)", all("page_owed" not in a for n, a in agents_of(A_ID).items() if n in ("home-sparrow-claimed", "home-sparrow-scribe"))
      and agents_of(A_ID)["home-sparrow-scribe"]["front"] is False and "MUST check `page_owed`" in prj.__doc__, agents_of(A_ID).get("home-sparrow-scribe"))
# no temp file ever sits in the committed store
leftovers = [f.name for f in (T / "store").rglob("*") if f.is_file() and (f.name.endswith(".tmp") or ".tmp" in f.name)]
check("no temp file is left in the store after all of this", not leftovers, leftovers)
seen_tmp = []
real_replace2 = os.replace
os.replace = lambda a, b: (seen_tmp.append((str(a), str(b))), real_replace2(a, b))[1]
try: prj.ensure_ids(["projects/one-more"]); p.cmd_registry(quiet=True); prj.stamp_registry(); server._projects_sync(force=True)
finally: os.replace = real_replace2
check("every write of the id file, the registry and projects.json stages its temp file in the state dir, never in the store", seen_tmp and all(a.startswith(f"{tmp}/state/tmp/") for a, b in seen_tmp)
      and {b for a, b in seen_tmp} >= {str(REC), str(T / "store/projects.json"), str(PJ)}, seen_tmp)
real_replace3 = os.replace
def exdev(a, b):
    if str(a).startswith(f"{tmp}/state/tmp/") and str(b).startswith(f"{tmp}/store/"): raise OSError(18, "Invalid cross-device link")
    return real_replace3(a, b)
os.replace = exdev
try: prj.ensure_ids(["projects/across-devices"]); err = ""
except Exception as e: err = str(e)
finally: os.replace = real_replace3
check("across filesystems (EXDEV) the file is staged beside the target for one replace, and no temp file stays", not err and "projects/across-devices" in idfile()["ids"].values() and not [f for f in (T / "store").iterdir() if ".tmp" in f.name], (err, [f.name for f in (T / "store").iterdir()]))
# the lock is re-entrant in a thread and every writer takes it
import threading
done = []
def hold():
    with prj.locked():
        with prj.locked(): done.append("nested ok")
t = threading.Thread(target=hold); t.start(); t.join(10)
check("the lock can be taken again in the same thread (the registry rebuild holds it while ensure_ids takes it)", done == ["nested ok"] and not t.is_alive())
src = open(f"{STACK}/pages.py").read().split("def cmd_registry")[1].split("def suggestions")[0]
check("pages.cmd_registry rebuilds under the same lock and writes through write_atomic", "_prj.locked()" in src and "_prj.write_atomic(REG" in src)

# the state dir failing never stops the registry rebuild (fail-open), and write_atomic is durable and still whole
def rebuild_quiet():
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        try: rc = p.cmd_registry(quiet=True); exc = None
        except BaseException as e: rc = None; exc = e
    return rc, exc, err.getvalue()
ids_before = {k: e["id"] for k, e in reg().items()}
real_wa, real_locked = prj.write_atomic, prj.locked
def boom(*a, **k): raise OSError(28, "No space left on device")
prj.write_atomic = boom
try: rc, exc, msg = rebuild_quiet()
finally: prj.write_atomic = real_wa
check("a failing write_atomic (disk full) does not stop the registry rebuild: it is written the plain way, ids kept, one line on stderr", exc is None and rc == 0
      and {k: e["id"] for k, e in reg().items()} == ids_before and msg.count("\n") == 1 and "registry:" in msg, (rc, exc, msg))
prj.locked = boom
try: rc, exc, msg = rebuild_quiet()
finally: prj.locked = real_locked
check("a failing project lock (state dir unusable) does not stop the rebuild either: the ids come from the old registry", exc is None and rc == 0
      and {k: e["id"] for k, e in reg().items()} == ids_before and msg.count("\n") == 1, (rc, exc, msg))
if os.geteuid() != 0:
    page("projects/zeta.md", "type: project\ntitle: Zeta\ndisplay-name: home-zeta\nstatus: active")
    TD = T / "state/tmp"; TD.mkdir(parents=True, exist_ok=True); os.chmod(TD, 0o555)
    try: rc, exc, msg = rebuild_quiet()
    finally: os.chmod(TD, 0o755)
    R2 = reg()
    check("a read-only state dir (really unwritable) still rebuilds the registry: every page there, the known ids kept, the new page without one", exc is None and rc == 0 and "projects/zeta" in R2
          and all(R2[k]["id"] == i for k, i in ids_before.items()) and "id" not in R2["projects/zeta"] and msg, (rc, exc, msg, R2.get("projects/zeta")))
    (T / "brain/projects/zeta.md").unlink()
    rc, exc, msg = rebuild_quiet()
    check("…and once the state dir is writable again the next rebuild is back to normal", exc is None and "projects/zeta" not in reg() and {k: e["id"] for k, e in reg().items()} == ids_before and not msg, (exc, msg))
# write_atomic: the full file, the temp file flushed and fsynced before the replace, the directory fsync's failure ignored
body = json.dumps({"k": "v" * 5000, "ja": "日本語"}, ensure_ascii=False)
tgt = T / "store/wa-check.json"; calls = []
real_fsync, real_replace4 = os.fsync, os.replace
def spy_fsync(fd):
    calls.append(("fsync", "dir" if os.path.isdir(f"/proc/self/fd/{fd}") else "file")); real_fsync(fd)
    if calls[-1][1] == "dir": raise OSError(22, "Invalid argument")
def spy_replace(a, b): calls.append(("replace", None)); return real_replace4(a, b)
os.fsync, os.replace = spy_fsync, spy_replace
try: prj.write_atomic(tgt, body); err = ""
except Exception as e: err = repr(e)
finally: os.fsync, os.replace = real_fsync, real_replace4
check("write_atomic produces the whole file (a long, non-ASCII body), mode 0644, and no temp file stays", not err and tgt.read_text(encoding="utf-8") == body and (tgt.stat().st_mode & 0o777) == 0o644
      and not [f for f in (T / "state/tmp").iterdir() if f.name.startswith("wa-check")], (err, calls))
check("write_atomic fsyncs the temp file before the replace, then the directory, and a failing directory fsync is ignored", calls[:2] == [("fsync", "file"), ("replace", None)] and ("fsync", "dir") in calls[2:], calls)
tgt.unlink()

# ---- the board item: an agent only the record holds (page line owed) is its project's agent for `get roles` and on the board
import anchors as _A, render as _render
from ui import render as ui_render
page("projects/omega.md", "type: project\ntitle: Omega\ndisplay-name: home-omega\nagents:\n  home-omega-main: talks to Oliver\nstatus: active")
page("projects/psi.md", "type: project\ntitle: Psi\ndisplay-name: home-psi\nstatus: archived")
page("projects/chi.md", "type: project\ntitle: Chi\ndisplay-name: home-chi\nstatus: active")      # a keeper and no agents yet: it reads front until an agent is listed
p.cmd_registry(quiet=True)
OM, PSI, CHI = (reg()[f"projects/{x}"]["id"] for x in ("omega", "psi", "chi"))
prj.add_pending(OM, "home-omega-scribe", {"front": True, "role": "scribe", "mandate_line": "writes it up"}, by="fleet-web")
prj.add_pending(OM, "home-omega-bot", {"front": False, "role": "bot", "mandate_line": "sweeps nightly"}, by="fleet-web")
prj.add_pending(OM, "home-omega-main", {"front": False, "role": "main", "mandate_line": "a claim that disagrees with the page"}, by="fleet-web")   # on the page AND the record: the page wins
prj.add_pending(PSI, "home-psi-main", {"front": True, "role": "main", "mandate_line": "front agent of psi"}, by="fleet-web")                        # a retired project
prj.add_pending(CHI, "home-chi-main", {"front": True, "role": "main", "mandate_line": "front agent of chi"}, by="fleet-web")
RL = _A.session_roles()
check("roles: a record-only front agent is its project's front agent, marked page_owed", RL.get("home-omega-scribe") == {"role": "front", "project": "projects/omega", "page_owed": True}, RL.get("home-omega-scribe"))
check("roles: a record-only background agent is back, marked page_owed", RL.get("home-omega-bot") == {"role": "back", "project": "projects/omega", "page_owed": True}, RL.get("home-omega-bot"))
check("roles: a name on the page and in the record is the page's, once, with no page_owed", RL.get("home-omega-main") == {"role": "front", "project": "projects/omega"}, RL.get("home-omega-main"))
check("roles: a retired project's record agent is not listed (its keeper still is)", "home-psi-main" not in RL and RL.get("home-psi", {}).get("role") == "keeper", (RL.get("home-psi-main"), RL.get("home-psi")))
check("roles: a page's own agents carry no page_owed key (the shape is additive)", all("page_owed" not in r for n, r in RL.items() if n in ("home-sparrow-main", "home-sparrow-docs", "home-sparrow-engineer", "home-omega", "home-omega-main")), {n: RL.get(n) for n in ("home-sparrow-main", "home-omega")})
FR = _A.file_roles()
check("roles.json: the owed agent is there too, and its project's keeper stays a keeper (a user-facing agent is listed), as for a page's agent", FR.get("home-chi-main", {}).get("page_owed") is True and FR["home-chi"]["role"] == "keeper" and FR["home-omega-scribe"]["role"] == "front", (FR.get("home-chi"), FR.get("home-chi-main")))
R0 = reg(); merged = prj.with_pending(R0)
check("with_pending: the registry it was given is not changed; the copy has the owed agents, flagged in owed_agents", "owed_agents" not in R0["projects/omega"] and "home-omega-scribe" not in R0["projects/omega"]["agents"]
      and merged["projects/omega"]["owed_agents"]["home-omega-scribe"] == "scribe" and prj.with_pending(merged) == merged and "home-omega-main" not in merged["projects/omega"]["owed_agents"], merged["projects/omega"])
(T / "store/a/900.json").write_text(json.dumps({"id": 900, "subject": "[home] omega item", "status": "open", "description": "x", "created": time.time(), "updated": time.time(),
                                             "metadata": {"project": "projects/omega", "owner": "home-omega-main", "next": "home-omega-main: go"}}))      # an open item gives omega its row on board.md
bd = ui_render.Board(f"{tmp}/store")
check("board: the project's row lists a record-only agent among the agents (front) and the background list (back), the page's -main once", set(bd.agent_roles("projects/omega")[0]) == {"home-omega-main", "home-omega-scribe"}
      and set(bd.agent_roles("projects/omega")[1]) == {"home-omega-bot"}, bd.agent_roles("projects/omega"))
il = bd.index_lines("projects/omega", [])
check("board: index_lines has the owed front agent (with its mandate) and shows the page's -main first, once", [x[0].split("/", 1)[-1] for x in il] == ["home-omega-main", "home-omega-scribe"] and il[1][6] == "writes it up", il)
sh = bd.sessions_html("projects/omega")
check("board: the project page's Sessions lists all three, the background one under Background agents", sh[0] == 3 and sh[1].count("home-omega-main") == 1 and "home-omega-scribe" in sh[1] and "home-omega-bot" in sh[1]
      and sh[1].index("Background agents") < sh[1].index("home-omega-bot") and sh[1].index("home-omega-scribe") < sh[1].index("Background agents"), sh)
check("board: the record-only agent's mandate is the record's mandate_line", bd.agent_roles("projects/omega")[0]["home-omega-scribe"] == "writes it up" and bd.agent_roles("projects/omega")[0]["home-omega-main"] == "talks to Oliver")
check("board: a retired project gains no agent, and a project with none listed is a hub row once the record has an agent", not bd.is_hub("projects/psi") and bd.is_hub("projects/chi") and "home-chi-main" in bd.agent_roles("projects/chi")[0])
md = _render.Board(f"{tmp}/store").render({"full"})["full"]
check("board.md / the full render carries the record-only agent on its project's row", "home-omega-scribe" in md and "home-psi-main" not in md, md[-1500:])
prj.add_pending(OM, "home-sparrow-engineer", {"front": True, "role": "engineer", "mandate_line": "claimed as front"})      # alpha's LIVE page lists it as a background agent; omega's record claims it as front
RL2 = _A.session_roles()
check("roles: an owed FRONT claim does not beat a live page's BACKGROUND listing of the same name in another project: the page's listing wins, no page_owed", RL2.get("home-sparrow-engineer") == {"role": "back", "project": "projects/alpha"}, RL2.get("home-sparrow-engineer"))
page("projects/rho.md", "type: project\ntitle: Rho\ndisplay-name: home-rho\nagents:\n  home-rho-old: legacy\nstatus: archived"); p.cmd_registry(quiet=True)
prj.add_pending(OM, "home-rho-old", {"front": False, "role": "old", "mandate_line": "moved to omega"})
RL3 = _A.session_roles()
check("roles: a listing on a RETIRED project's page loses to an owed claim on a live project (it is attributed to the live one)", RL3.get("home-rho-old") == {"role": "back", "project": "projects/omega", "page_owed": True}, RL3.get("home-rho-old"))
check("…and the retired project's other names are untouched", RL3.get("home-rho", {}).get("role") == "keeper" and "home-psi-main" not in RL3)
MU = prj.ensure_ids(["projects/mu"])["projects/mu"]; prj.set_mark(MU, made={"title": "Mu", "name": "mu", "org": "home", "steward": "home-mu"})
check("with_made / roles: a made project (page not read yet) with no owed agent never appears in roles, though other projects have pending agents", "projects/mu" in prj.with_made(reg()) and "projects/mu" not in prj.with_pending(reg(), made=True)
      and "home-mu" not in _A.session_roles() and "home-mu" not in _A.file_roles(), {n: r for n, r in _A.session_roles().items() if r["project"] == "projects/mu"})
prj.add_pending(MU, "home-mu-main", {"front": True, "role": "main", "mandate_line": "front agent of mu"})
check("…and once it has an owed agent the agent is registered at once under it (page_owed), with its keeper", _A.session_roles().get("home-mu-main") == {"role": "front", "project": "projects/mu", "page_owed": True}
      and _A.session_roles().get("home-mu", {}).get("project") == "projects/mu", _A.session_roles().get("home-mu-main"))
page("projects/omega.md", "type: project\ntitle: Omega\ndisplay-name: home-omega\nagents:\n  home-omega-main: talks to Oliver\n  home-omega-scribe: writes it up\nstatus: active"); p.cmd_registry(quiet=True)
check("once the page lists the name, the pending claim is pruned and roles read it as the page's (no page_owed)", prj.prune_pending(reg()) >= 1 and "page_owed" not in _A.session_roles()["home-omega-scribe"], _A.session_roles().get("home-omega-scribe"))

# with_pending never raises (the server's gates call session_roles with no try around it): a record that cannot be read gives the no-record result
RECF = T / "store/project-record.json"; REC_BAK = T / "store/project-record.json.bak-n1"
real_wp = prj.with_pending; prj.with_pending = lambda reg, made=False: reg
try: baseline = _A.session_roles()
finally: prj.with_pending = real_wp
RECF.rename(REC_BAK); RECF.mkdir()
try: got, exc = _A.session_roles(), None
except Exception as e: got, exc = None, e
finally: RECF.rmdir(); REC_BAK.rename(RECF)
check("with_pending: the record path replaced by a directory (OSError) → session_roles is the no-record result, no exception", exc is None and got == baseline and "home-mu-main" not in got, exc)
check("…and the record is back and the owed agents with it", _A.session_roles().get("home-mu-main", {}).get("page_owed") is True)

# ---- a name line that names one of the page's own agents is a session, not the project's name (ops/general: keeper ops-commons-engineer)
GU = {"t-gen-engineer": "00000000-0000-4000-8000-0000000000a1", "t-gen-main": "00000000-0000-4000-8000-0000000000a2", "t-norm": "00000000-0000-4000-8000-0000000000a3"}
U.update(GU); sess = json.loads((T / "fleet/a/sessions.json").read_text()); sess.update({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in GU.items()})
(T / "fleet/a/sessions.json").write_text(json.dumps(sess))
page("projects/gen.md", "type: project\ntitle: Gen\ndisplay-name: t-gen-engineer\nagents:\n  t-gen-main: talks to Oliver\n  background:\n    t-gen-engineer: builds\nstatus: active")
page("projects/gen2.md", "type: project\ntitle: Gen2\ndisplay-name: t-gen2-engineer\nagents:\n  t-gen2-engineer: builds\nstatus: active")      # a keeper session and no -main agent
page("projects/gen3.md", "type: project\ntitle: Gen3\ndisplay-name: t-gen3-main\nagents:\n  t-gen3-main: talks to Oliver\nstatus: active")
page("projects/norm.md", "type: project\ntitle: Norm\ndisplay-name: t-norm\nagents:\n  t-norm-main: talks to Oliver\n  t-norm-engineer: builds\nstatus: active")
p.cmd_registry(quiet=True)
GEN, NORM = reg()["projects/gen"]["id"], reg()["projects/norm"]["id"]
pre = lambda k: prj._name_prefixes(k, reg()[k], reg())
check("name prefix: a name line naming one of the page's agents gives the project's name from its -main agent", pre("projects/gen") == ["t-gen"], pre("projects/gen"))
check("…with no -main agent, the keeper minus its last dash part", pre("projects/gen2") == ["t-gen2"], pre("projects/gen2"))
check("…a keeper that is the -main agent itself gives the project's name too", pre("projects/gen3") == ["t-gen3"], pre("projects/gen3"))
check("…a name line that is not one of the page's agents stays as written (the normal case)", pre("projects/norm") == ["t-norm"] and pre("projects/alpha") == ["home-sparrow"], (pre("projects/norm"), pre("projects/alpha")))
check("role_of: t-gen-engineer is the engineer of the page whose name line names it, and t-gen-main the main", prj.role_of("t-gen-engineer", pre("projects/gen")) == "engineer" and prj.role_of("t-gen-main", pre("projects/gen")) == "main")
check("agents: the records of that page carry those roles", {n: a["role"] for n, a in prj.ref(GEN)["agents"].items()} == {"t-gen-main": "main", "t-gen-engineer": "engineer"}, prj.ref(GEN)["agents"])
check("…and the keeper is still the name line", prj.ref(GEN)["keeper"] == "t-gen-engineer")
st, out = post(GEN, "t-gen-01", "t-gen-engineer", role="01", mandate="a numbered worker")
check("post project-agent: t-gen-01 is accepted on a page whose name line is the session t-gen-engineer", st == 200 and "t-gen-01" in agents_of(GEN) and agents_of(GEN)["t-gen-01"]["role"] == "01", (st, out))
st, out = post(GEN, "other-name", "t-gen-engineer")
check("…a bad name is refused naming t-gen-<role>, not t-gen-engineer-<role>", st == 400 and "t-gen-<role>" in out["error"] and "t-gen-engineer-<role>" not in out["error"], (st, out))
st, out = post(GEN, "t-gen-02", "t-gen-main", role="02", mandate="by the front agent")
check("…its -main agent may list one too", st == 200 and "t-gen-02" in agents_of(GEN), (st, out))
st, out = post(NORM, "t-norm-01", "t-norm", role="01", mandate="x")
check("a normal page (name line not an agent): the keeper lists t-norm-01 as before", st == 200 and "t-norm-01" in agents_of(NORM), (st, out))
st, out = post(NORM, "other-name", "t-norm")
check("…and the refusal still names the name line, t-norm-<role>", st == 400 and "t-norm-<role>" in out["error"], (st, out))
st, out = post(GEN, "t-norm-01", "t-gen-engineer", role="01", mandate="x")
check("a name of another project is refused on this page (400, t-gen-<role>)", st == 400 and "t-gen-<role>" in out["error"], (st, out))

# ---- the page's `display-name:` line replaced `steward:` (a leftover `steward:` line is no longer read; the registry's fields keep their names)
page("projects/dnnew.md", "type: project\ntitle: Dn new\ndisplay-name: x-proj\nagents:\n  x-proj-main: talks to Oliver\n  background:\n    x-proj-engineer: builds\nstatus: active")
page("projects/dnold.md", "type: project\ntitle: Dn old\nsteward: x-proj\nagents:\n  x-proj-main: talks to Oliver\n  background:\n    x-proj-engineer: builds\nstatus: active")
page("projects/dnboth.md", "type: project\ntitle: Dn both\nsteward: x-old\ndisplay-name: x-new\nagents:\n  x-new-main: talks to Oliver\nstatus: active")
p.cmd_registry(quiet=True)
DN = {k: reg()[k] for k in ("projects/dnnew", "projects/dnold", "projects/dnboth")}
check("display-name: the registry entries keep their field names (session, role name); a leftover `steward:` line names nobody", DN["projects/dnnew"]["role"] == DN["projects/dnboth"]["role"] == "name" and all("display-name" not in e and "display_name" not in e for e in DN.values())
      and DN["projects/dnnew"]["session"] == "x-proj" and DN["projects/dnold"]["session"] == "" and "role" not in DN["projects/dnold"], DN)
pre = lambda k: prj._name_prefixes(k, reg()[k], reg())
check("display-name: a page with only `display-name: x-proj` gives the name prefix x-proj; one with only `steward: x-proj` gives none", pre("projects/dnnew") == ["x-proj"] and pre("projects/dnold") == [], (pre("projects/dnnew"), pre("projects/dnold")))
check("display-name: …the keeper in the record", prj.ref(DN["projects/dnnew"]["id"])["keeper"] == "x-proj" and prj.ref(DN["projects/dnold"]["id"])["keeper"] == "")
check("display-name: …and role_of for its agents", [prj.role_of(n, pre("projects/dnnew")) for n in ("x-proj-main", "x-proj-engineer")] == ["main", "engineer"])
check("display-name: …and the agent records", {n: a["role"] for n, a in prj.ref(DN["projects/dnnew"]["id"])["agents"].items()} == {"x-proj-main": "main", "x-proj-engineer": "engineer"})
check("display-name: a page carrying both keys prefers `display-name:` (keeper and name prefix)", DN["projects/dnboth"]["session"] == "x-new" and pre("projects/dnboth") == ["x-new"] and prj.role_of("x-new-main", pre("projects/dnboth")) == "main", (DN["projects/dnboth"]["session"], pre("projects/dnboth")))
nf = prj.page_front("projects/dn-made", "Dn made", "home"); nm = prj.new_page("projects/dn-made", "Dn made", "home"); nfm = nm.split("\n---\n", 1)[0]
check("display-name: page_front carries it, and no `steward` key", nf["display_name"] == "home-dn-made" and "steward" not in nf, nf)
check("display-name: new_page writes `display-name: <value>` and no `steward:` line", "\ndisplay-name: home-dn-made" in nfm and not re.search(r"(?m)^steward:", nm), nfm)
page("projects/dn-made.md", nfm.removeprefix("---\n")); p.cmd_registry(quiet=True)
check("display-name: the page new_page wrote reads back as the project's keeper (role name)", (reg()["projects/dn-made"]["session"], reg()["projects/dn-made"]["role"]) == ("home-dn-made", "name"), reg()["projects/dn-made"])

print(("ok" if not fails else "FAILED") + f": project record scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
