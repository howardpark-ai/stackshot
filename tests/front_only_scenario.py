"""Scenario test for the front-only test of a project (anchors.front_only) - fixture data (English stand-in names), no live store, no network, no server socket.

A project is front-only when its `agents:` map lists no `background:` agent. The map is the page's own; a page with no map of its own reads its hub's. No new field: adding a background
agent to the map is all that switches a project over.

  1  pure, on a registry given in hand: a map with background entries is not front-only (one, several); a map without is (one -main only; a -main and a second front agent); a background agent
     whose mandate says nothing about building still makes the project not front-only
  2  pure: a sub-page with no map reads its hub's (hub without a background agent: front-only; hub with one: not), a page with a `hub:` line reads that hub, a sub-page with a map of its own decides
     alone (front agents only under a hub that has a background agent: front-only; a background agent under a hub of front agents only: not)
  3  pure: adding a builder flips it (the same registry with one `back_agents` entry added, and back again when it is removed), also for a sub-page that reads the hub's map
  4  pure: an empty or missing page: a key the registry does not hold, an empty key, a registry with no pages, a page with an empty map and a hub without one, an entry with no fields: all front-only
  5  the default registry: with no registry given the test reads the page registry file, and the agents only the project record holds (their page line still owed) count as its agents, so a
     background agent made through the New session form switches the project over before its page line lands
  6  agreement with the older tests on the common shapes: on every project of that fixture the server's hand-off builder / first background agent test (the one `_project_builders` was) says "no builder"
     exactly when front_only says True, and the two server rules that use front_only (the answer's target and the front agents' hand-over) behave as before for a front-only project and a project with a builder
  7  the shapes where the two differ, pinned as the intended results: a sub-page with its own front-only map under a hub with a builder, a sub-page whose `hub:` line points at a page with no map while its
     top-level page lists a builder, a front-only hub whose builder sits on a member page, a background agent only the project record holds

    tests/run-suite front_only        -> exit 0 / 1"""
import json, os, re, sys, pathlib, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="front-only-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
assert 'session_links = ""' in toml   # the example config names no fleet store of the host
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet", HOME=tmp); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "brain/projects"): (T / d).mkdir(parents=True)

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.anchors import anchors as A  # noqa: E402

page = lambda **kw: {"title": "T", "name": "T", "org": "home", "tags": [], "type": "project", "session": "", "status": "active", "board": [], "board_open": 0, **kw}

# ---------------------------------------------------------------- 1. the map decides
REG = {
    "projects/solo": page(agents={"home-solo-main": "front"}),
    "projects/pair": page(agents={"home-pair-main": "front", "home-pair-desk": "front, answers questions"}),
    "projects/built": page(agents={"home-built-main": "front", "home-built-engineer": "builds it"}, back_agents={"home-built-engineer": "builds it"}),
    "projects/crowd": page(agents={"home-crowd-main": "front", "home-crowd-tests": "runs the suites", "home-crowd-engineer": "builds it"},
                           back_agents={"home-crowd-tests": "runs the suites", "home-crowd-engineer": "builds it"}),
    "projects/quiet": page(agents={"home-quiet-main": "front", "home-quiet-watch": "watches the clock"}, back_agents={"home-quiet-watch": "watches the clock"}),
    "projects/backonly": page(agents={"home-backonly-engineer": "builds it"}, back_agents={"home-backonly-engineer": "builds it"}),
}
check("1 a map with one background entry is not front-only", A.front_only("projects/built", REG) is False)
check("1 a map with several background entries is not front-only", A.front_only("projects/crowd", REG) is False)
check("1 a map of one -main agent only is front-only", A.front_only("projects/solo", REG) is True)
check("1 a -main agent and a second front agent is front-only", A.front_only("projects/pair", REG) is True)
check("1 a background agent whose mandate lacks the build words still makes it not front-only", A.front_only("projects/quiet", REG) is False)
check("1 a map of background agents alone is not front-only", A.front_only("projects/backonly", REG) is False)
check("1 slashes round the key do not matter", A.front_only("/projects/built/", REG) is False and A.front_only("projects/solo/", REG) is True)

# ---------------------------------------------------------------- 2. a page with no map reads its hub's
REG2 = {
    **REG,
    "projects/solo/notes": page(type="note", role="inherited"),                          # a sub-page: no map of its own, no hub line -> the top-level page
    "projects/built/notes": page(type="note", role="inherited"),
    "projects/built/deep/notes": page(type="note", role="inherited"),                    # two levels down: still the top-level page
    "projects/aside": page(hub="projects/built"),                                       # a page with a `hub:` line and no map -> that hub
    "projects/aside2": page(hub="projects/solo"),
    "projects/solo/desk": page(agents={"home-solo-desk": "front"}),                      # a map of its own, front agents only, under a hub of front agents
    "projects/built/desk": page(agents={"home-built-desk": "front"}),                    # a map of its own, front agents only, under a hub that has a builder: its own map decides
    "projects/solo/crew": page(agents={"home-solo-crew": "builds the crew's work"}, back_agents={"home-solo-crew": "builds the crew's work"}),   # a background agent under a hub of front agents
}
check("2 a sub-page with no map under a hub of front agents is front-only", A.front_only("projects/solo/notes", REG2) is True)
check("2 a sub-page with no map under a hub that has a background agent is not front-only", A.front_only("projects/built/notes", REG2) is False)
check("2 the same two levels down", A.front_only("projects/built/deep/notes", REG2) is False)
check("2 a page with a `hub:` line and no map reads that hub", A.front_only("projects/aside", REG2) is False and A.front_only("projects/aside2", REG2) is True)
check("2 a sub-page with its own map of front agents decides alone: front-only although its hub has a background agent", A.front_only("projects/built/desk", REG2) is True)
check("2 a sub-page with its own background agent is not front-only although its hub lists front agents only", A.front_only("projects/solo/crew", REG2) is False)
check("2 slashes round a sub-page key do not matter (a sub-page's own map, its hub's map, its own background agent)",
      A.front_only("/projects/built/desk/", REG2) is True and A.front_only("/projects/built/notes/", REG2) is False and A.front_only("/projects/solo/crew/", REG2) is False
      and A.front_only("//projects/solo/notes//", REG2) is True)

# ---------------------------------------------------------------- 3. adding a builder flips it
def with_builder(reg, key, name="home-new-engineer", mandate="takes build work"):
    e = dict(reg[key]); e["agents"] = {**e["agents"], name: mandate}; e["back_agents"] = {**(e.get("back_agents") or {}), name: mandate}
    return {**reg, key: e}
def without(reg, key, name):
    e = dict(reg[key]); e["agents"] = {k: v for k, v in e["agents"].items() if k != name}; e["back_agents"] = {k: v for k, v in (e.get("back_agents") or {}).items() if k != name}
    if not e["back_agents"]: e.pop("back_agents")
    return {**reg, key: e}
R3 = with_builder(REG2, "projects/solo")
check("3 adding a builder to a front-only map switches the project over", A.front_only("projects/solo", REG2) is True and A.front_only("projects/solo", R3) is False)
check("3 ...and a sub-page that reads the hub's map follows", A.front_only("projects/solo/notes", REG2) is True and A.front_only("projects/solo/notes", R3) is False)
check("3 ...a sub-page with a map of its own does not", A.front_only("projects/solo/desk", R3) is True)
R3b = without(R3, "projects/solo", "home-new-engineer")
check("3 taking the builder out again switches it back", A.front_only("projects/solo", R3b) is True and A.front_only("projects/solo/notes", R3b) is True)
R3c = without(REG2, "projects/crowd", "home-crowd-engineer")
check("3 one of two background agents removed: still not front-only; both removed: front-only", A.front_only("projects/crowd", R3c) is False and A.front_only("projects/crowd", without(R3c, "projects/crowd", "home-crowd-tests")) is True)
check("3 the registry given is not changed", REG2["projects/solo"]["agents"] == {"home-solo-main": "front"} and "back_agents" not in REG2["projects/solo"])

# ---------------------------------------------------------------- 4. an empty or missing page
check("4 a key the registry does not hold is front-only", A.front_only("projects/ghost", REG2) is True)
check("4 a sub-page of a page the registry does not hold is front-only", A.front_only("projects/ghost/notes", REG2) is True)
check("4 an empty key, a blank key and None are front-only", A.front_only("", REG2) is True and A.front_only("  ", REG2) is True and A.front_only(None, REG2) is True)
check("4 a registry with no pages is front-only", A.front_only("projects/built", {}) is True)
check("4 a page with an empty map and a hub without one is front-only", A.front_only("projects/e", {"projects/e": page(agents={}), "projects/hub0": page(agents={"x-main": "front"})}) is True)
check("4 a page with an empty map reads its hub's", A.front_only("projects/e", {"projects/e": page(agents={}, hub="projects/hub1"), "projects/hub1": page(agents={"x-main": "front", "x-eng": "builds"}, back_agents={"x-eng": "builds"})}) is False)
check("4 a page entry with no fields at all is front-only", A.front_only("projects/odd", {"projects/odd": {}}) is True)

# ---------------------------------------------------------------- 5. the default registry: the page registry file, plus the agents only the record holds
from stackshot.projects import projects as P  # noqa: E402
PID = P.ensure_ids(["projects/solo"])["projects/solo"]      # the record mints the id
(T / "store/projects.json").write_text(json.dumps({"pages": {k: v for k, v in REG2.items()}}))
check("5 with no registry given the test reads the page registry file", A.front_only("projects/solo") is True and A.front_only("projects/built") is False and A.front_only("projects/built/notes") is False)
(T / "store/project-record.json").write_text(json.dumps({"schema": 1, "ids": {PID: "projects/solo"},
    "pending_agents": {PID: {"home-solo-engineer": {"mandate_line": "takes the build work", "front": False, "role": "engineer"}}}}))
check("5 a background agent only the project record holds (page line still owed) switches the project over", A.front_only("projects/solo") is False and A.front_only("projects/solo/notes") is False)
(T / "store/project-record.json").write_text(json.dumps({"schema": 1, "ids": {PID: "projects/solo"},
    "pending_agents": {PID: {"home-solo-friend": {"mandate_line": "answers questions", "front": True, "role": "front"}}}}))
check("5 a front agent only the record holds does not", A.front_only("projects/solo") is True)
(T / "store/project-record.json").write_text("{ not json")
check("5 a damaged record reads as no pending agent (the page registry alone decides)", A.front_only("projects/solo") is True and A.front_only("projects/built") is False)
(T / "store/project-record.json").unlink()
(T / "store/projects.json").write_text("{ not json")
check("5 a damaged page registry file reads as no pages: front-only", A.front_only("projects/built") is True)
(T / "store/projects.json").write_text(json.dumps({"pages": {k: v for k, v in REG2.items()}}))

# ---------------------------------------------------------------- 6. agreement with the older tests, and the two server rules
from stackshot.web import server  # noqa: E402
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
SMAIN, SDESK, DMAIN, DDESK, DBUILD = ("home-sigma-main", "home-sigma-desk", "home-delta-main", "home-delta-desk", "home-delta-builder")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate((SMAIN, SDESK, DMAIN, DDESK, DBUILD), 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in U.items()}))
SHAPES = {
    "projects/sigma": page(title="Sigma", name="Sigma", agents={SMAIN: "front", SDESK: "front, answers the owner's questions"}),
    "projects/delta": page(title="Delta", name="Delta", agents={DMAIN: "front", DDESK: "front, answers questions", DBUILD: "builds it"}, back_agents={DBUILD: "builds it"}),
    "projects/sigma/sub": page(title="Sigma sub", name="Sigma sub"),
    "projects/delta/sub": page(title="Delta sub", name="Delta sub"),
    "projects/echo": page(title="Echo", name="Echo", agents={"home-echo-main": "front"}),
    "projects/lone": page(title="Lone", name="Lone"),
}
(T / "store/projects.json").write_text(json.dumps({"pages": SHAPES}))
old_no_builder = lambda p: not (server._handoff_builder(p) or server._hub_sessions(p)[2][:1])      # what server._project_builders was
rows = {p: (A.front_only(p), old_no_builder(p)) for p in SHAPES}
check("6 on every fixture project front_only agrees with the older hand-off builder / first background agent test", all(a == b for a, b in rows.values()), rows)
check("6 the fixture holds both kinds of project", {a for a, _ in rows.values()} == {True, False}, rows)

server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
nm = server._anc.names()
roles = server._anc.session_roles()
fp = lambda sender, key, project: server._front_pair_ok(sender, key, project)
check("6 front agents of a front-only project may hand an item to each other", fp(SMAIN, SDESK, "projects/sigma") is True and fp(SDESK, SMAIN, "projects/sigma/sub") is True, roles.get(SMAIN))
check("6 ...not in a project that has a builder", fp(DMAIN, DDESK, "projects/delta") is False and fp(DMAIN, DDESK, "projects/delta/sub") is False)
check("6 ...not across projects, and not from a session no page lists", fp(SMAIN, DDESK, "projects/sigma") is False and fp("home-nobody", SDESK, "projects/sigma") is False)
meta = lambda **k: {"owner": SMAIN, "contact": SDESK, "project": "projects/sigma", **k}
check("6 the answer of a front-only project goes to its contact", server._builderless_answer_to(meta(), "projects/sigma") == SDESK, server._builderless_answer_to(meta(), "projects/sigma"))
check("6 ...a project with a builder keeps the old fallback", server._builderless_answer_to(meta(project="projects/delta", contact=DDESK), "projects/delta") == "")
check("6 ...an empty project keeps it too", server._builderless_answer_to(meta(), "") == "")

# ---------------------------------------------------------------- 7. where front_only and the older test differ, pinned as the intended results
# (a) a background agent whose mandate lacks the build words; (b) a sub-page with a map of front agents under a hub that lists a background agent; (c) a sub-page whose `hub:` line points at a page
# with no map, while its top-level page lists a background agent; (d) a hub whose own map is front-only, with a background agent on a member page that names it as its hub; (e) a background agent
# only the project record holds (its page line still owed)
SHAPES7 = {
    "projects/qa": page(title="Qa", name="Qa", agents={"home-qa-main": "front", "home-qa-watch": "watches the clock"}, back_agents={"home-qa-watch": "watches the clock"}),
    "projects/qb": page(title="Qb", name="Qb", agents={"home-qb-main": "front", "home-qb-eng": "builds it"}, back_agents={"home-qb-eng": "builds it"}),
    "projects/qb/desk": page(title="Qb desk", name="Qb desk", agents={"home-qb-desk": "front"}),
    "projects/qa2": page(title="Qa2", name="Qa2", agents={"home-qa2-main": "front", "home-qa2-eng": "builds it"}, back_agents={"home-qa2-eng": "builds it"}),
    "projects/qa2/s/t": page(title="Qa2 t", name="Qa2 t", hub="projects/qc"),
    "projects/qc": page(title="Qc", name="Qc"),
    "projects/qd": page(title="Qd", name="Qd", agents={"home-qd-main": "front"}),
    "projects/qd-member": page(title="Qd member", name="Qd member", hub="projects/qd", agents={"home-qd-member-main": "front", "home-qd-member-eng": "builds it"}, back_agents={"home-qd-member-eng": "builds it"}),
    "projects/qe": page(title="Qe", name="Qe", agents={"home-qe-main": "front"}),
}
(T / "store/projects.json").write_text(json.dumps({"pages": SHAPES7}))
old7 = {p: old_no_builder(p) for p in SHAPES7}
new7 = {p: A.front_only(p) for p in SHAPES7}
check("7a a background agent whose mandate lacks the build words: not front-only, and the older hand-off test finds a background agent too", new7["projects/qa"] is False and old7["projects/qa"] is False, (new7, old7))
check("7b a sub-page with its own map of front agents under a hub that lists a builder: front-only now (its own map decides), the older union found a builder",
      new7["projects/qb/desk"] is True and old7["projects/qb/desk"] is False and new7["projects/qb"] is False, (new7, old7))
check("7c a sub-page whose `hub:` line points at a page with no map, under a top-level page that lists a builder: front-only now (the hub's map is read), the older union found the builder",
      new7["projects/qa2/s/t"] is True and old7["projects/qa2/s/t"] is False and new7["projects/qc"] is True and new7["projects/qa2"] is False, (new7, old7))
check("7d a hub with a front-only map and a builder on a member page that names it as its hub: front-only now (the hub's own map), the older test found the member's builder; the member itself is not",
      new7["projects/qd"] is True and old7["projects/qd"] is False and new7["projects/qd-member"] is False, (new7, old7))
check("7 the shapes outside (b), (c), (d) and (e) agree with the older test", all(new7[p] == old7[p] for p in ("projects/qa", "projects/qb", "projects/qa2", "projects/qc", "projects/qd-member")), (new7, old7))
QE = P.ensure_ids(["projects/qe"])["projects/qe"]
(T / "store/project-record.json").write_text(json.dumps({"schema": 1, "ids": {QE: "projects/qe"},
    "pending_agents": {QE: {"home-qe-engineer": {"mandate_line": "takes the build work", "front": False, "role": "engineer"}}}}))
check("7e a background agent only the project record holds (page line owed): not front-only; the older test found no builder (it read the page registry alone)",
      A.front_only("projects/qe") is False and old_no_builder("projects/qe") is True, (A.front_only("projects/qe"), old_no_builder("projects/qe")))

if fails:
    print(f"\n{len(fails)} of {len(ran)} checks failed"); sys.exit(1)
print(f"ok: front_only scenario, {len(ran)} checks")
