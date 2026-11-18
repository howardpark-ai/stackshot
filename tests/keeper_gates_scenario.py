"""Scenario test for the keeper mark in the gates, telling, router and roles (stage 2 of the keeper as a mark on one agent) — fixture data, no live store, no network, no server process.

Covers: that with no mark anywhere every result is what it was before (the roles files, the name the notices are addressed to, the router's stand-in, the keeper telling answers, the
sessions tool's labels), written out as fixed values; that a mark on a front agent that is not the builder, a mark on the builder, a one-session project that lists its session as a front agent
with a mark, a retired project with a mark, and the sub-pages under a mark each change who a notice falls to and what the roles files carry (the project's name line is no session, the marked
agent carries `keeper: true`); and the carried findings of the first stage's reviews, each with its test: a retired project's sub-page follows its marked parent; a status or hub change of the
record reads the keeper of the pages under it again; a sub-page with a name line and agents of its own derives from its own agents; an unnamed sub-page of a project with agents and no name line
takes the record's mark; a parent's mark does not reclassify a child's old `session:` line; a mark whose agent the record removed is reported.

    tests/run-suite keeper_gates       → exit 0 / 1
    ONLY_UNMARKED=1 skips the marked sections (the unmarked ones must pass on the code before this stage too)"""
import json, os, re, sys, pathlib, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="keepergates-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.pop("CLAUDE_CODE_SESSION_ID", None); os.environ.pop("KEEPER_CURRENCY", None)
for d in ("store/a", "fleet/a", "state/cache", "brain/projects", "secrets"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"})); (T / "fleet/a/sessions.json").write_text("{}")
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")

ONLY_UNMARKED = bool(os.environ.get("ONLY_UNMARKED"))

# Neutral fixtures. forge: a split project (agents, a builder, no mark); lone-page: a one-session project; old-one: a retired project; ember: a page mark with a child whose old `session:` line names the
# project; nameless: agents and no name line, with sub-pages; own: a sub-page of forge with a name line and agents of its own; orchard: a page mark on a front agent.
page("projects/forge.md", "type: project\ntitle: Forge\ndisplay-name: team-forge\nagents:\n  team-forge-main: talks\n  team-forge-docs: keeps the docs\n  background:\n    team-forge-audit: reviews\n    team-forge-builder: builds and merges\nstatus: active")
page("projects/forge/sub.md", "type: project\ntitle: Forge sub")
page("projects/forge/sub/deep.md", "type: note\ntitle: Forge deep")
page("projects/forge/own.md", "type: project\ntitle: Forge own\ndisplay-name: team-own\nagents:\n  team-own-main: talks\n  background:\n    team-own-builder: builds\nstatus: active")
page("projects/forge/owned.md", "type: project\ntitle: Forge owned\nagent: team-forge-docs")
page("projects/satellite.md", "type: project\ntitle: Satellite\nhub: projects/forge")
page("projects/satellite/note.md", "type: note\ntitle: Satellite note")
page("projects/named-sat.md", "type: project\ntitle: Named satellite\ndisplay-name: lone-satellite\nhub: projects/forge")
page("projects/loft.md", "type: project\ntitle: Loft\ndisplay-name: team-loft\nagents:\n  team-loft-main: talks\nstatus: active")
page("projects/lone-page.md", "type: project\ntitle: Lone\ndisplay-name: lone-session\nstatus: active")
page("projects/lone-page/sub.md", "type: note\ntitle: Lone sub")
page("projects/old-one.md", "type: project\ntitle: Old one\ndisplay-name: team-old\nagents:\n  team-old-main: talks\n  background:\n    team-old-builder: builds\nstatus: archived")
page("projects/old-one/sub.md", "type: note\ntitle: Old one sub")
page("projects/old-one/sub/deep.md", "type: note\ntitle: Old one deep")
page("projects/ember.md", "type: project\ntitle: Ember\ndisplay-name: team-ember\nkeeper: team-ember-main\nagents:\n  team-ember-main: talks\n  background:\n    team-ember-builder: builds\nstatus: active")
page("projects/ember/legacy.md", "type: project\ntitle: Ember legacy\nsession: team-ember")
page("projects/ember/legacy/deep.md", "type: note\ntitle: Ember deep")
page("projects/ember/plain.md", "type: note\ntitle: Ember plain")
page("projects/nameless.md", "type: project\ntitle: Nameless\nagents:\n  team-nameless-main: talks\n  team-nameless-docs: keeps the docs\nstatus: active")
page("projects/nameless/note.md", "type: note\ntitle: Nameless note")
page("projects/nameless/note/deep.md", "type: note\ntitle: Nameless deep")
page("projects/orchard.md", "type: project\ntitle: Orchard\ndisplay-name: team-orchard\nkeeper: team-orchard-docs\nagents:\n  team-orchard-main: talks\n  team-orchard-docs: keeps the docs\n  background:\n    team-orchard-builder: builds\nstatus: active")
page("projects/orchard/notes.md", "type: note\ntitle: Orchard notes")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
REC = T / "store/project-record.json"
from stackshot.projects import pages as p; from stackshot.projects import projects as prj; from stackshot.projects import project_registry as pr; from stackshot.projects import keeper as kp
from stackshot.anchors import anchors; from stackshot.router import router_live as rl
from stackshot.service import telling
from stackshot.web import server      # installs the telling's hooks (web/wiring.py), as front_quiet does
if ONLY_UNMARKED:      # the page's own mark of the ember and orchard fixtures is a mark: this run leaves them out of the pages
    for rel in ("projects/ember.md", "projects/orchard.md"):
        txt = (T / "brain" / rel).read_text(); (T / "brain" / rel).write_text(re.sub(r"keeper: [^\n]+\n", "", txt))
p.cmd_registry(quiet=True)
def reg(): return json.loads((T / "store/projects.json").read_text())["pages"]
ids = {k: e["id"] for k, e in reg().items()}
def agent(front, mandate, **kw): return {"front": front, "mandate_line": mandate, **kw}
def write_record(entries):
    d = json.loads(REC.read_text()) if REC.exists() else {}
    d.update({"projects": entries, "projects_schema": 1}); REC.write_text(json.dumps(d), encoding="utf-8"); pr._CACHE["sig"] = None
def entry(key, **kw): return {"page": key, "status": "active", **kw}
def R(): return prj.registry()
def C(r): return {k: v for k, v in (r or {}).items() if k != "live"}      # a role entry without its liveness (the fixture has no running sessions)
def answers(key, rg=None):
    """What a project answers: the name its notices are addressed to, its stand-in, the keeper telling answers, and whether the router rules a notice to its keeper."""
    rg = R() if rg is None else rg
    return {"notice": anchors.notice_name(key, rg), "stand_in": rl.stand_in(key, rg), "page_keeper": telling.page_keeper(key, rg), "holds_notice": rl.holds(key, anchors.notice_name(key, rg))}

# ---- 1. no mark anywhere: every result is what it was (fixed values, written out; this section passes on the code before this stage)
UM = [k for k in ("projects/forge", "projects/forge/sub", "projects/forge/sub/deep", "projects/loft", "projects/lone-page", "projects/lone-page/sub", "projects/old-one", "projects/nameless", "projects/nameless/note")]
if ONLY_UNMARKED:
    UM += ["projects/ember", "projects/ember/legacy", "projects/ember/legacy/deep", "projects/orchard", "projects/orchard/notes"]
rg = R()
A = {k: answers(k, rg) for k in UM}
check("unmarked, split project: notices are addressed to the name line (held for the router), the stand-in is the builder, telling answers the builder",
      A["projects/forge"] == {"notice": "team-forge", "stand_in": "team-forge-builder", "page_keeper": "team-forge-builder", "holds_notice": True}, A["projects/forge"])
check("unmarked, a sub-page and a deeper one answer as their project", A["projects/forge/sub"] == A["projects/forge"] and A["projects/forge/sub/deep"] == A["projects/forge"])
check("unmarked, a -main agent only: the stand-in and the keeper are the -main agent", A["projects/loft"] == {"notice": "team-loft", "stand_in": "team-loft-main", "page_keeper": "team-loft-main", "holds_notice": True}, A["projects/loft"])
check("unmarked, a one-session project: its session is the name the notices are addressed to and the keeper, and a sub-page follows",
      A["projects/lone-page"]["notice"] == "lone-session" and A["projects/lone-page"]["page_keeper"] == "lone-session" and A["projects/lone-page/sub"]["page_keeper"] == "lone-session", A["projects/lone-page"])
check("unmarked, no name line: the notices go to the -main agent", A["projects/nameless"]["notice"] == "team-nameless-main" and A["projects/nameless"]["page_keeper"] == "team-nameless-main", A["projects/nameless"])
S0 = anchors.session_roles(rg, set()); F0 = anchors.file_roles(rg, set())
check("unmarked, roles: the name line of a split project is a retired keeper entry, the agents are front or back, nobody carries a keeper flag",
      C(S0["team-forge"]) == {"role": "keeper", "project": "projects/forge", "retired": True} and S0["team-forge-builder"]["role"] == "back" and S0["team-forge-main"]["role"] == "front" and not any("keeper" in r for r in S0.values() if r["project"] not in ("projects/ember", "projects/orchard")), S0["team-forge"])
check("unmarked, roles.json: a one-session project's session reads front (the file's promotion) and keeper in session_roles", F0["lone-session"]["role"] == "front" and S0["lone-session"]["role"] == "keeper" and "retired" not in S0["lone-session"], (F0["lone-session"], S0["lone-session"]))
check("unmarked, no entry carries the keeper flag (the sessions tool's `and keeper` label never shows)", not any("keeper" in r for r in S0.values() if r["project"] not in ("projects/ember", "projects/orchard")) and not any("keeper" in r for r in F0.values() if r["project"] not in ("projects/ember", "projects/orchard")), [(k, r) for k, r in S0.items() if "keeper" in r])
check("unmarked, front_keeper: a front agent is front and tells the stand-in; the project's own name line is not front", telling.front_keeper("team-forge-main", "projects/forge") == (True, "team-forge-builder") and telling.front_keeper("team-forge", "projects/forge")[0] is False,
      (telling.front_keeper("team-forge-main", "projects/forge"), telling.front_keeper("team-forge", "projects/forge")))
check("unmarked, the retired project: no keeper agent, roles keep its name line retired, notices still go to its name line", R()["projects/old-one"]["keeper_agent"] == "" and S0["team-old"].get("retired") is True and A["projects/old-one"]["notice"] == "team-old", (A["projects/old-one"], S0["team-old"]))
if ONLY_UNMARKED:
    check("unmarked, a page's `keeper:` line left out: the project's old name line answers", A["projects/ember"]["notice"] == "team-ember" and A["projects/orchard"]["notice"] == "team-orchard", (A["projects/ember"], A["projects/orchard"]))
    print(f"ok: keeper gates scenario (unmarked only), {len(ran)} checks" if not fails else f"FAILED: {len(fails)} of {len(ran)}")
    sys.exit(1 if fails else 0)

# ---- 2. a mark on a front agent that is not the builder (the record's flag on team-forge-docs)
F = ids["projects/forge"]
FORGE = {"team-forge-main": agent(True, "talks"), "team-forge-docs": agent(True, "keeps the docs"), "team-forge-audit": agent(False, "reviews"), "team-forge-builder": agent(False, "builds and merges")}
def forge(mark=None, **kw):
    ag = {n: dict(a) for n, a in FORGE.items()}
    if mark: ag[mark]["keeper"] = True
    return entry("projects/forge", name="team-forge", agents=ag, **kw)
write_record({F: forge("team-forge-docs")})
rg = R()
M = answers("projects/forge", rg)
check("mark on a front agent that is not the builder: notices are addressed to it, the stand-in and the keeper telling answers are it (the builder is not), and the router rules a notice to it",
      M == {"notice": "team-forge-docs", "stand_in": "team-forge-docs", "page_keeper": "team-forge-docs", "holds_notice": True}, M)
check("… the sub-pages under the mark answer the same, at any depth", answers("projects/forge/sub", rg) == M and answers("projects/forge/sub/deep", rg) == M, (answers("projects/forge/sub", rg), answers("projects/forge/sub/deep", rg)))
check("… the keeper agent field of the pages, with the mark as its source", rg["projects/forge"]["keeper_agent"] == "team-forge-docs" and rg["projects/forge/sub/deep"]["keeper_agent"] == "team-forge-docs" and rg["projects/forge/sub"]["keeper_source"] == "mark")
check("… a sub-page an agent keeps (`agent:`) still names that agent as its keeper, and a page that falls to this one by its `hub:` line answers the mark as its stand-in",
      telling.project_keeper("projects/forge/owned") == "team-forge-docs" and answers("projects/satellite", rg)["stand_in"] == "team-forge-docs", (telling.project_keeper("projects/forge/owned"), answers("projects/satellite", rg)))
S = anchors.session_roles(rg, set()); Fr = anchors.file_roles(rg, set())
check("roles: the marked agent keeps its role (front) and carries `keeper: true`; the project's name line is no session any more; no other agent is flagged",
      C(S["team-forge-docs"]) == {"role": "front", "project": "projects/forge", "keeper": True} and "team-forge" not in S and "team-forge" not in Fr
      and [n for n, r in S.items() if r.get("keeper") and r["project"] == "projects/forge"] == ["team-forge-docs"] and S["team-forge-builder"] == S0["team-forge-builder"] and S["team-forge-main"] == S0["team-forge-main"], {k: v for k, v in S.items() if "forge" in k})
check("roles.json (file_roles) carries the same entries as session_roles for a marked project", Fr["team-forge-docs"] == S["team-forge-docs"] and Fr["team-forge-builder"] == S["team-forge-builder"])
check("front_keeper: the marked front agent is front and tells nobody about its own (it is the keeper); the other front agent tells it", telling.front_keeper("team-forge-docs", "projects/forge") == (True, "") and telling.front_keeper("team-forge-main", "projects/forge") == (True, "team-forge-docs"),
      (telling.front_keeper("team-forge-docs", "projects/forge"), telling.front_keeper("team-forge-main", "projects/forge")))
check("keeper_words: the marked agent is `the keeper of` its project, by its roles entry", telling.keeper_words("projects/forge", "team-forge-docs") == "the keeper of projects/forge", telling.keeper_words("projects/forge", "team-forge-docs"))
from stackshot.web.tools import sessions as ws
ws_roles = anchors.file_roles(rg, set())
check("the sessions tool labels a marked agent `front agent and keeper of`, other agents as before", ws._ROLE_LABEL["front"] == "front agent" and ws_roles["team-forge-docs"].get("keeper") is True)

# ---- 3. a mark on the builder
write_record({F: forge("team-forge-builder")})
rg = R(); M = answers("projects/forge", rg); S = anchors.session_roles(rg, set())
check("mark on the builder: notices are addressed to the builder (the name line is no longer the address), the stand-in and the keeper are the builder, keeper_source is mark",
      M == {"notice": "team-forge-builder", "stand_in": "team-forge-builder", "page_keeper": "team-forge-builder", "holds_notice": True} and rg["projects/forge"]["keeper_source"] == "mark", M)
check("… roles: the builder stays back and carries `keeper: true`, the name line is gone", C(S["team-forge-builder"]) == {"role": "back", "project": "projects/forge", "keeper": True} and "team-forge" not in S)
check("… a builder keeper is not front (front_keeper), and a front agent tells it", telling.front_keeper("team-forge-builder", "projects/forge")[0] is False and telling.front_keeper("team-forge-main", "projects/forge") == (True, "team-forge-builder"))

# ---- 4. a one-session project listed as a front agent with a mark
LONE = ids["projects/lone-page"]
write_record({LONE: entry("projects/lone-page", name="lone-session", agents={"lone-session": agent(True, "its one session", keeper=True)})})
rg = R(); M = answers("projects/lone-page", rg); S = anchors.session_roles(rg, set()); Fr = anchors.file_roles(rg, set())
check("one-session project, its session listed as the front agent and marked: the notices, the stand-in and the keeper are that session, and a sub-page follows",
      M == {"notice": "lone-session", "stand_in": "lone-session", "page_keeper": "lone-session", "holds_notice": True} and answers("projects/lone-page/sub", rg) == M, M)
check("… roles: one entry, a front agent with the keeper flag, in session_roles and in roles.json alike (no promotion needed: the file and the gates agree)",
      C(S["lone-session"]) == {"role": "front", "project": "projects/lone-page", "keeper": True} and Fr["lone-session"] == S["lone-session"], (S.get("lone-session"), Fr.get("lone-session")))
check("… front_keeper: the session is front (the gates now see what the file says)", telling.front_keeper("lone-session", "projects/lone-page") == (True, ""), (telling.front_keeper("lone-session", "projects/lone-page"), anchors.session_roles().get("lone-session")))

# ---- 5. a retired project with a mark (finding: a sub-page of a retired MARKED project follows its parent; and the unnamed one of it)
OLD = ids["projects/old-one"]
write_record({OLD: entry("projects/old-one", name="team-old", status="archived", agents={"team-old-main": agent(True, "talks"), "team-old-builder": agent(False, "builds", keeper=True)})})
rg = R()
check("retired marked project: the row, its sub-page and the page under that all keep the mark (a mark is read in a retired project, and a sub-page follows its parent)",
      all((rg[k]["keeper_agent"], rg[k]["keeper_source"]) == ("team-old-builder", "mark") for k in ("projects/old-one", "projects/old-one/sub", "projects/old-one/sub/deep")), {k: (rg[k].get("keeper_agent"), rg[k].get("keeper_source")) for k in rg if "old-one" in k})
write_record({OLD: entry("projects/old-one", name="team-old", status="archived", agents={"team-old-main": agent(True, "talks"), "team-old-builder": agent(False, "builds")})})
rg = R()
check("retired project, no mark: no keeper for the row and for the sub-pages under it (as before)", all((rg[k]["keeper_agent"], rg[k]["keeper_source"]) == ("", "") for k in ("projects/old-one", "projects/old-one/sub", "projects/old-one/sub/deep")))
check("retired marked project: the name line is no session, and no role carries `retired` for a marked agent; the marked builder is a back agent with the flag",
      (write_record({OLD: entry("projects/old-one", name="team-old", status="archived", agents={"team-old-main": agent(True, "talks"), "team-old-builder": agent(False, "builds", keeper=True)})}),
       C(anchors.session_roles(R(), set()).get("team-old-builder")) == {"role": "back", "project": "projects/old-one", "keeper": True} and "team-old" not in anchors.session_roles(R(), set()))[1])

# ---- 6. a status or hub change of the record reads the keeper of the pages under it again (also while the page's own lines still say what they said: the mirror has not been written)
write_record({F: forge(status="archived")})
rg = R()
check("record archives a project (the page still says active): its sub-pages have no keeper, the pages that fall to it by `hub:` too", all((rg[k]["keeper_agent"], rg[k]["keeper_source"]) == ("", "") for k in ("projects/forge", "projects/forge/sub", "projects/forge/sub/deep")),
      {k: (rg[k].get("keeper_agent"), rg[k].get("keeper_source"), rg[k].get("status")) for k in rg if "forge" in k})
write_record({F: forge()})
rg = R()
check("record un-archives it again: the sub-pages derive their keeper once more", all((rg[k]["keeper_agent"], rg[k]["keeper_source"]) == ("team-forge-builder", "derived") for k in ("projects/forge/sub", "projects/forge/sub/deep")))
SAT = ids["projects/satellite"]
write_record({SAT: entry("projects/satellite", name="", hub="projects/loft")})
rg = R()
check("record re-hubs a page (hub only): the sub-page under it reads the new hub's -main agent, not the old hub's builder", (rg["projects/satellite/note"]["keeper_agent"], rg["projects/satellite/note"]["keeper_source"]) == ("team-loft-main", "derived")
      and reg()["projects/satellite/note"]["keeper_agent"] == "team-forge-builder", (rg["projects/satellite/note"], reg()["projects/satellite/note"]["keeper_agent"]))
write_record({})

# ---- 7. known limit (docs/projects.md): a sub-page with a name line and agents of its own is still given the top project's derived keeper, as before the keeper mark; its own agents are not read for the field
rg = R()
check("known limit: a sub-page with its own name line and own agents keeps the top project's derived keeper in keeper_agent (as before the keeper mark), the same agent the gates answer for it",
      (rg["projects/forge/own"]["keeper_agent"], rg["projects/forge/own"]["keeper_source"]) == ("team-forge-builder", "derived") and rl.stand_in("projects/forge/own", rg) == "team-forge-builder", rg["projects/forge/own"])

# ---- 8. an unnamed sub-page of a project with agents and no name line takes the record's mark
NL = ids["projects/nameless"]
write_record({NL: entry("projects/nameless", agents={"team-nameless-main": agent(True, "talks"), "team-nameless-docs": agent(True, "keeps the docs", keeper=True)})})
rg = R()
check("record mark on a project with agents and no name line: the unnamed sub-pages take it, at any depth, with the old (empty) value kept",
      all((rg[k]["session"], rg[k]["role"], rg[k]["keeper_agent"], rg[k]["keeper_source"]) == ("team-nameless-docs", "inherited", "team-nameless-docs", "mark") for k in ("projects/nameless/note", "projects/nameless/note/deep"))
      and answers("projects/nameless/note", rg)["stand_in"] == "team-nameless-docs", {k: rg[k] for k in rg if "nameless/" in k})
write_record({NL: entry("projects/nameless", agents={"team-nameless-main": agent(True, "talks"), "team-nameless-docs": agent(True, "keeps the docs")})})
rg = R()
check("… and the mark gone from the record, they are what they were: no session, no role, the derived keeper",
      all(("session" not in rg[k] or rg[k]["session"] == "") and "role" not in rg[k] and "legacy_role" not in rg[k] and (rg[k]["keeper_agent"], rg[k]["keeper_source"]) == ("team-nameless-main", "derived") for k in ("projects/nameless/note", "projects/nameless/note/deep")),
      {k: rg[k] for k in rg if "nameless/" in k})
write_record({})

# ---- 9. a parent's mark does not reclassify a child's old `session:` line
fms, _rels, _sk = p.read_pages_ex()
EM = {k: p.keeper_of(k, fms) for k in ("projects/ember", "projects/ember/legacy", "projects/ember/legacy/deep", "projects/ember/plain")}
OLDKEYS = {k: p.keeper_of(k, fms, marks=False) for k in EM}
check("page mark above, a child with `session:` naming the project: the child keeps its line as a name line (role name), as without the mark", EM["projects/ember/legacy"] == ("team-ember", "name") == OLDKEYS["projects/ember/legacy"], EM["projects/ember/legacy"])
check("… the page under that child inherits the child's line, not the mark above (the child named its own keeper); a plain unnamed sibling takes the mark",
      EM["projects/ember/legacy/deep"] == ("team-ember", "inherited") == OLDKEYS["projects/ember/legacy/deep"] and EM["projects/ember/plain"] == ("team-ember-main", "inherited") and EM["projects/ember"] == ("team-ember-main", "mark"), EM)

# ---- 10. a mark whose agent the record removed publishes why the page's visible line was ignored
OR = ids["projects/orchard"]
check("page mark, record untouched: the mark is read, nothing reported", R()["projects/orchard"]["keeper_agent"] == "team-orchard-docs" and "keeper_problems" not in R()["projects/orchard"])
write_record({OR: entry("projects/orchard", name="team-orchard", agents={"team-orchard-main": agent(True, "talks"), "team-orchard-builder": agent(False, "builds")})})
rg = R(); B = prj.build()["projects"]
check("record removes the agent the page marks: the old lines answer, the row and the published record say the visible `keeper:` line was ignored, naming it and why",
      rg["projects/orchard"]["session"] == "team-orchard" and rg["projects/orchard"]["keeper_source"] == "derived" and len(rg["projects/orchard"].get("keeper_problems", [])) == 1 and "team-orchard-docs" in rg["projects/orchard"]["keeper_problems"][0]
      and "record" in rg["projects/orchard"]["keeper_problems"][0] and len(B[OR].get("keeper_problems", [])) == 1, (rg["projects/orchard"], B[OR].get("keeper_problems")))
write_record({})

# ---- 12. a page that falls to a marked hub: notice_name, stand_in, page_keeper and keeper_agent all name the hub's mark (page and sub-page)
write_record({F: forge("team-forge-docs")})
rg = R()
A12 = {k: answers(k, rg) for k in ("projects/satellite", "projects/satellite/note")}
check("hub-linked page of a marked project (and its sub-page): notice_name, stand_in and page_keeper are the hub's marked agent, and the router rules a notice to it",
      all(a == {"notice": "team-forge-docs", "stand_in": "team-forge-docs", "page_keeper": "team-forge-docs", "holds_notice": True} for a in A12.values()), A12)
check("… and the registry says the same (keeper_agent, source mark)", all(rg[k]["keeper_agent"] == "team-forge-docs" for k in ("projects/satellite", "projects/satellite/note")), {k: (rg[k]["keeper_agent"], rg[k]["keeper_source"]) for k in ("projects/satellite", "projects/satellite/note")})
write_record({})
rg = R()
check("… no mark: the satellite's notices go to the hub's -main agent and its stand-in is the hub's builder, as before",
      anchors.notice_name("projects/satellite", rg) == "team-forge-main" and rl.stand_in("projects/satellite", rg) == "team-forge-builder", (anchors.notice_name("projects/satellite", rg), rl.stand_in("projects/satellite", rg)))

# ---- 13. the page debts the audit's call could not write go to the marked agent first
from stackshot.service import page_debt as pdebt
sent = []
_relay, _rule, _forget = pdebt._telling.pilot_relay_many, pdebt._routing.rule, pdebt.page_debt_forget
pdebt._telling.pilot_relay_many = lambda keeper, rows, head="": (sent.append((keeper, head)) or ["n1"]); pdebt._routing.rule = lambda nid, how, **kw: None
pdebt.page_debt_forget = lambda *a, **k: None
try:
    to0 = pdebt.page_debt_fallback("projects/forge", {}, [("a1", "changed", "someone")], "the call failed", 0.0)
    write_record({F: forge("team-forge-docs")})
    to1 = pdebt.page_debt_fallback("projects/forge", {}, [("a1", "changed", "someone")], "the call failed", 0.0)
    write_record({F: forge("team-forge-builder")})
    to2 = pdebt.page_debt_fallback("projects/forge", {}, [("a1", "changed", "someone")], "the call failed", 0.0)
finally:
    pdebt._telling.pilot_relay_many, pdebt._routing.rule, pdebt.page_debt_forget = _relay, _rule, _forget
    write_record({})
check("page debt fallback: no mark → the builder (as before); a mark on a front agent that is not the builder → that agent, told as a front agent that keeps the page; a mark on the builder → the builder",
      (to0, to1, to2) == ("team-forge-builder", "team-forge-docs", "team-forge-builder") and [k for k, _h in sent] == ["team-forge-builder", "team-forge-docs", "team-forge-builder"]
      and "you keep this page" not in sent[0][1] and "you keep this page" in sent[1][1] and sent[1][1].startswith("[for ") and not sent[0][1].startswith("[for "), (to0, to1, to2, sent))

# ---- 14. the keeper flag follows the agent over all its projects
L = ids["projects/loft"]
write_record({F: forge(), L: entry("projects/loft", name="team-loft", agents={"team-loft-main": agent(True, "talks", keeper=True), "team-forge-docs": agent(True, "also a front agent of the loft")})})
S14 = anchors.session_roles(R(), set())
check("an agent that keeps the loft carries the flag, and an agent whose role elsewhere is front only does not", S14["team-loft-main"].get("keeper") is True and S14["team-forge-docs"].get("keeper") is not True, (S14["team-loft-main"], S14["team-forge-docs"]))
write_record({F: forge(), L: entry("projects/loft", name="team-loft", agents={"team-loft-main": agent(True, "talks"), "team-forge-docs": agent(True, "also keeps the loft docs", keeper=True)})})
S14 = anchors.session_roles(R(), set())
check("an agent that is the marked keeper of the loft and a front agent of the forge (its best role on the forge) still carries the flag, and its project stays the best one", S14["team-forge-docs"].get("keeper") is True and S14["team-forge-docs"]["project"] == "projects/forge", S14["team-forge-docs"])
write_record({F: forge("team-forge-docs"), L: entry("projects/loft", name="team-loft", agents={"team-loft-main": agent(True, "talks"), "team-forge-docs": agent(True, "also keeps the loft docs", keeper=True)})})
S14 = anchors.session_roles(R(), set())
check("an agent that is the marked keeper of two projects carries the flag on its one entry", S14["team-forge-docs"].get("keeper") is True and [n for n, r in S14.items() if r.get("keeper") and "forge" in n or "loft" in n and r.get("keeper")] == ["team-forge-docs"], {n: r for n, r in S14.items() if r.get("keeper")})
write_record({})

# ---- 11. the readers of a page's name line see the project's name for a marked page, not the marked agent
write_record({F: forge("team-forge-docs")})
import types
check("a name-line reader (project_verbs: the name an entry made from a marked page gets) reads the line the mark took the place of",
      prj.name_line(R()["projects/forge"]) == "team-forge" and anchors.name_line("projects/forge", R()) == "team-forge-docs")
write_record({})

# ---- 15. carried from the stage 2 reviews (S3-a, S3-b, S3-c)
# S3-a: a hub-linked page with its OWN display-name and no agents keeps its own line as its keeper (as keeper.fields reads it); the hub's mark does not take it over, and the unnamed satellite still follows the hub
write_record({F: forge("team-forge-docs")})
rg = R()
check("S3-a: a named satellite of a marked hub: the notices go to its own name line and the registry agrees (legacy, its own line), where an unnamed satellite follows the hub's mark",
      anchors.notice_name("projects/named-sat", rg) == "lone-satellite" and (rg["projects/named-sat"]["keeper_agent"], rg["projects/named-sat"]["keeper_source"]) == ("lone-satellite", "legacy")
      and anchors.notice_name("projects/satellite", rg) == "team-forge-docs", (anchors.notice_name("projects/named-sat", rg), rg["projects/named-sat"].get("keeper_agent"), anchors.notice_name("projects/satellite", rg)))
write_record({})
rg = R()
check("S3-a: with no mark the named satellite answers as it did (its own line)", anchors.notice_name("projects/named-sat", rg) == "lone-satellite", anchors.notice_name("projects/named-sat", rg))
# S3-b: an agent marked by one project alone is described as the keeper of that project, not of the project where its best role is
write_record({F: forge(), L: entry("projects/loft", name="team-loft", agents={"team-loft-main": agent(True, "talks"), "team-forge-docs": agent(True, "also keeps the loft docs", keeper=True)})})
rg = R()
check("S3-b: the pages that mark an agent are named by keeper_pages (the loft, though the agent's best role is on the forge)",
      anchors.keeper_pages("team-forge-docs", rg) == ["projects/loft"] and anchors.session_roles(rg, set())["team-forge-docs"]["project"] == "projects/forge", (anchors.keeper_pages("team-forge-docs", rg), anchors.session_roles(rg, set())["team-forge-docs"]))
check("S3-b: telling.keeper_words names the loft for it, not the forge where its best role is",
      telling.keeper_words("projects/forge", "team-forge-docs") == "the keeper of projects/loft", telling.keeper_words("projects/forge", "team-forge-docs"))
# ... and the sessions tool's own label says both: the project of its best role and the project it keeps
from stackshot.web.tools import sessions as _wts
(T / "fleet/a/sessions.json").write_text(json.dumps({"00000000-0000-4000-8000-000000000001": {"name": "team-forge-docs", "machine": "a"}, "00000000-0000-4000-8000-000000000002": {"name": "team-loft-main", "machine": "a"},
                                                     "00000000-0000-4000-8000-000000000003": {"name": "team-forge-main", "machine": "a"}}))
if _wts._fleet_names is None: _wts._fleet_names = lambda: {"a": "testbox"}
ls = _wts._sessions_listing("").split("\n"); rowof = lambda n: next((x for x in ls if x.startswith(f"- {n} — ")), "")
check("S3-b: the sessions tool says front agent of the forge, and keeper of the loft, for an agent marked on another project than its best role; a plain agent reads as before",
      rowof("team-forge-docs").endswith(" · front agent of projects/forge, and keeper of projects/loft") and rowof("team-forge-main").endswith(" · front agent of projects/forge"), [x for x in ls if x.startswith("- ")])
write_record({F: forge("team-forge-docs")})
ls = _wts._sessions_listing("").split("\n")
check("S3-b: the sessions tool keeps its one-project wording when the agent keeps the project its best role is on (front agent and keeper of the forge)",
      next((x for x in ls if x.startswith("- team-forge-docs — ")), "").endswith(" · front agent and keeper of projects/forge"), [x for x in ls if x.startswith("- ")])
write_record({})
# S3-c: the entry made from a marked page, and the name check, read the page's name line (the line the mark took the place of), never the marked agent
from stackshot.projects import project_verbs as pv
orow = prj.registry_raw()["projects/orchard"]
check("S3-c: a page that marks an agent in its own `keeper:` line has role mark, the marked agent as its session and its old name line as legacy_session",
      orow["role"] == "mark" and orow["session"] == "team-orchard-docs" and orow["legacy_session"] == "team-orchard", orow)
ent_o = pv.derive_entry(ids["projects/orchard"], "projects/orchard", orow, prj.registry_raw(), None, "2026-11-01T00:00:00Z")
check("S3-c: derive_entry names the project by the page's name line, not by the marked agent", ent_o.get("name") == "team-orchard", ent_o)
ctx = pv.Ctx(json.loads(REC.read_text()) if REC.exists() else {}, {}, "2026-11-01T00:00:00Z", "")
nt = pv._name_taken(ctx, "team-orchard", ids["projects/loft"]); nt2 = pv._name_taken(ctx, "team-orchard-docs", ids["projects/loft"])
check("S3-c: the name check treats a marked page's name line as taken by that page, and the marked agent's name as no name line",
      "name line of projects/orchard" in nt and nt2 == "", (nt, nt2))

if fails: print(f"FAILED: keeper gates scenario, {len(ran)} checks, {len(fails)} failed"); sys.exit(1)
print(f"ok: keeper gates scenario, {len(ran)} checks")
