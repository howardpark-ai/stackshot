"""Scenario test for the surface of a project's agent (project_registry.py `surface`, project_verbs.agent_add, the `post project-agent` verb and client, anchors.front_agents / session_roles, the router's
and the audit's recipient pickers, keeper.successor, waits/successor.py): fixture data (fake names such as demo-slack), no live store, no network, no server process (the page store is the plain markdown
folder of a temporary config).

Covers: the record's agent entry with and without a surface (absent, "sala", "slack", a value that is none of them refused in words by the reader and by the writer); a stored "sala" written as absent, so a
sala agent's entry is what it always was; a slack agent refused as the keeper (the first agent of a project, the `keeper` verb), as a mover (a background agent), as -main (listing it, renaming one to it);
roles.json and projects.json (and the registry's rows) carrying the surface for a slack agent only; front_agents, main_of, the keeper's and the successor's pickers, the router's agents and the audit's
-main skipping a slack agent while another front agent of the same project is still found, and a slack agent still a front agent for the gates (roles.json says `front`); a record that names no
surface reading exactly as before; the `post project-agent` call end to end (the service on a temporary store, and the client's argument handling), with the role word `slack`; the sessions tool
saying `slack agent`.

    tests/run-suite agent_surface        → exit 0 / 1"""
import json, logging, os, pathlib, re, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="agentsurf-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
for d in ("store/a", "fleet/a", "state/demo-one", "brain/projects", "brain/infra", "secrets"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text("{}")
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
BRAIN = T / "brain"
def page(rel, front, body="# x\n"):
    q = BRAIN / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n" + body, encoding="utf-8")
def text(rel): return (BRAIN / (rel + ".md")).read_text(encoding="utf-8")
page("projects/demo.md", "type: project\ntitle: Demo\ndisplay-name: demo\nagents:\n  demo-main: talks to the user\n  demo-docs: keeps the docs\n  background:\n    demo-builder: builds and merges\nstatus: active")
page("projects/empty.md", "type: project\ntitle: Empty\ndisplay-name: demo-empty\nstatus: active")
page("projects/mixed.md", "type: project\ntitle: Mixed\ndisplay-name: demo-mixed\nagents:\n  demo-mixed-docs: keeps the docs\n  background:\n    demo-mixed-builder: builds and merges\nstatus: active")
page("projects/wm.md", "type: project\ntitle: Wm\ndisplay-name: wm\nagents:\n  wm-main: talks to the user\n  wm-docs: keeps the docs\n  background:\n    wm-builder: builds and merges\nstatus: active")
page("projects/wm/notes.md", "type: note\ntitle: Notes\nagent: wm-chat")
page("projects/wm/log.md", "type: note\ntitle: Log")
page("projects/rb.md", "type: project\ntitle: Rb\ndisplay-name: rb\nstatus: active")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.core import config as _cfg
from stackshot.projects import pages as p; from stackshot.projects import projects as prj; from stackshot.projects import project_registry as pr; from stackshot.projects import project_verbs as pv
from stackshot.projects import keeper as _kp; from stackshot.router import page_debt
from stackshot.anchors import anchors; from stackshot.router import router, router_live; from stackshot.waits import successor as wsucc
from stackshot.audit import audit_run
from stackshot.web import server
from stackshot.web.tools import sessions as sessions_tool
from stackshot.service import projects as _psvc; from stackshot.web.routes import client_api as _rt_client
from stackshot.fleet import client
p.cmd_registry(quiet=True)
IO = page_debt.PlainIO(); _psvc.PAGE_IO = IO
def reg(): return json.loads((T / "store/projects.json").read_text())["pages"]
ids = {k: e["id"] for k, e in reg().items()}
D, E, M = ids["projects/demo"], ids["projects/empty"], ids["projects/mixed"]
WM, RB = ids["projects/wm"], ids["projects/rb"]
REC = T / "store/project-record.json"
def recfile(): return json.loads(REC.read_text())
def entry(pid): return pr.entries()[pid]
def row(key="projects/demo"): return anchors.registry()[key]
def pv_err(fn):
    try: fn(); return 0
    except pv.VerbError as e: return e.status
def pv_msg(fn):
    try: fn(); return ""
    except pv.VerbError as e: return e.message
def prec(key="projects/demo"): return prj.build()["projects"][ids[key]]

# ---- 1. the record: an agent entry with and without a surface
GOOD = {"name": "demo", "agents": {"demo-main": {"front": True, "mandate_line": "m", "keeper": True}, "demo-docs": {"front": True, "mandate_line": "d"}}}
X = "".join(["pr", "j", chr(95), format(0xfade, "08x")])  # built from parts: the id shape is fixed, the value is made up
def parse_err(agents):
    try: pr.parse({"projects": {X: {**GOOD, "agents": agents}}}); return ""
    except ValueError as e: return str(e)
base = {"demo-main": {"front": True, "mandate_line": "m", "keeper": True}}
check("record: an entry with no surface, with the surface sala and with the surface slack is valid", all(parse_err({**base, "demo-chat": {"front": True, "mandate_line": "c", **s}}) == "" for s in ({}, {"surface": "sala"}, {"surface": "slack"})))
msg = parse_err({**base, "demo-chat": {"front": True, "mandate_line": "c", "surface": "carrier-pigeon"}})
check("record: a surface that is none of sala and slack is refused, in words, naming the agent and the two surfaces", "demo-chat" in msg and "carrier-pigeon" in msg and "a surface is sala or slack" in msg, msg)
check("record: a slack agent that is a background agent is refused (a mover is never a slack agent)", "background agent" in parse_err({**base, "demo-chat": {"front": False, "mandate_line": "c", "surface": "slack"}}))
check("record: a slack agent that is the keeper is refused", "keeper" in parse_err({"demo-chat": {"front": True, "mandate_line": "c", "surface": "slack", "keeper": True}}))
check("record: a slack agent named -main is refused", "-main" in parse_err({**base, "demo-x-main": {"front": True, "mandate_line": "c", "surface": "slack"}}))
check("record: a surface that is no text is refused too", parse_err({**base, "demo-chat": {"front": True, "mandate_line": "c", "surface": ["slack"]}}) != "")
check("record: surface_of reads absent as sala, and off_sala is true for slack only", pr.surface_of({"front": True}) == "sala" and pr.surface_of({"surface": "slack"}) == "slack" and pr.off_sala({"surface": "slack"}) and not pr.off_sala({"surface": "sala"}) and not pr.off_sala({}) and not pr.off_sala(None))

# ---- 2. the verb: a slack agent is listed, a sala one is what it always was
check("verb: the first listing creates the project's entry from its page, with no surface on any agent", pv.agent_add(D, "demo-plain", True, "a sala agent", io=IO)["changed"] and all("surface" not in a for a in entry(D)["agents"].values()), entry(D)["agents"])
r_sala = pv.agent_add(D, "demo-explicit", True, "says sala", surface="sala", io=IO, by="demo-main")
r_none = pv.agent_add(D, "demo-implicit", True, "says nothing", io=IO, by="demo-main")
check("verb: surface sala is written as absent: the entry has the keys an agent listed with no surface has", set(entry(D)["agents"]["demo-explicit"]) == set(entry(D)["agents"]["demo-implicit"]) == {"front", "mandate_line", "by", "at"}, entry(D)["agents"])
check("verb: …and the answer does not say a surface", "surface" not in r_sala and "surface" not in r_none)
before = REC.read_bytes()
r = pv.agent_add(D, "demo-slack", True, "answers his Slack messages", surface="slack", io=IO, by="demo-main")
check("verb: a slack agent is listed with its surface on its entry, front, and not the keeper", entry(D)["agents"]["demo-slack"]["surface"] == "slack" and entry(D)["agents"]["demo-slack"]["front"] is True
      and "keeper" not in entry(D)["agents"]["demo-slack"] and r["surface"] == "slack" and r["changed"], entry(D)["agents"]["demo-slack"])
check("verb: …the page's agents block lists it as a front agent (the page has no surface line)", r["mirror"]["state"] == "written" and "demo-slack" in text("projects/demo") and "surface" not in text("projects/demo"), text("projects/demo"))
check("verb: said again as it is, it changes nothing", not pv.agent_add(D, "demo-slack", True, "answers his Slack messages", surface="slack", io=IO)["changed"])
check("verb: the same name listed with another surface (sala) is a 409 that names the surface", pv_err(lambda: pv.agent_add(D, "demo-slack", True, "answers his Slack messages", io=IO)) == 409
      and "slack" in pv_msg(lambda: pv.agent_add(D, "demo-slack", True, "answers his Slack messages", io=IO)))
rec0 = REC.read_bytes()
check("verb: a surface that is none of them is a 400 in words, nothing written", pv_err(lambda: pv.agent_add(D, "demo-pigeon", True, "x", surface="carrier-pigeon", io=IO)) == 400
      and pv_msg(lambda: pv.agent_add(D, "demo-pigeon", True, "x", surface="carrier-pigeon", io=IO)).startswith("surface 'carrier-pigeon' is not known; a surface is sala or slack") and REC.read_bytes() == rec0)
check("verb: a slack agent as a background agent (a mover) is refused", pv_err(lambda: pv.agent_add(D, "demo-slack-bg", False, "x", surface="slack", io=IO)) == 400 and "front agent" in pv_msg(lambda: pv.agent_add(D, "demo-slack-bg", False, "x", surface="slack", io=IO)) and REC.read_bytes() == rec0)
check("verb: a slack agent named -main is refused", pv_err(lambda: pv.agent_add(D, "demo-x-main", True, "x", surface="slack", io=IO)) == 400 and "-main" in pv_msg(lambda: pv.agent_add(D, "demo-x-main", True, "x", surface="slack", io=IO)) and REC.read_bytes() == rec0)
check("verb: a slack agent as the first agent of a project (it would be the keeper) is refused, and the project stays without agents", pv_err(lambda: pv.agent_add(E, "demo-empty-slack", True, "x", surface="slack", io=IO)) == 400
      and "keeper" in pv_msg(lambda: pv.agent_add(E, "demo-empty-slack", True, "x", surface="slack", io=IO)) and not (entry(E).get("agents") if E in pr.entries() else {}) and REC.read_bytes() == rec0)
check("verb: a sala agent first, then a slack one: the keeper is the sala agent", pv.agent_add(E, "demo-empty-main", True, "the project's agent", io=IO)["keeper_marked"] == "demo-empty-main"
      and pv.agent_add(E, "demo-empty-slack", True, "answers", surface="slack", io=IO)["changed"] and entry(E)["agents"]["demo-empty-main"].get("keeper") is True and "keeper" not in entry(E)["agents"]["demo-empty-slack"])
rec0 = REC.read_bytes()
check("verb: the keeper mark is never moved to a slack agent (the keeper verb, a dry run or not)", pv_err(lambda: pv.keeper(D, "demo-slack", apply=True, io=IO)) == 400 and "keeper is a sala session" in pv_msg(lambda: pv.keeper(D, "demo-slack", apply=True, io=IO)) and REC.read_bytes() == rec0)
check("verb: a slack agent is not renamed -main (400), and another name keeps the surface", pv_err(lambda: pv.agent_rename(D, "demo-slack", "demo-z-main", io=IO)) == 400
      and pv.agent_rename(D, "demo-slack", "demo-chat", io=IO)["result"] == "renamed" and entry(D)["agents"]["demo-chat"]["surface"] == "slack" and "demo-slack" not in entry(D)["agents"])
check("verb: the mandate of a slack agent changes and its surface stays", pv.agent_mandate(D, "demo-chat", "answers his Slack app messages", io=IO)["changed"] and entry(D)["agents"]["demo-chat"]["surface"] == "slack")

# ---- 3. the derived files and the registry's rows
check("rows: the registry row names its non-sala agents, and only them", row()["surface_agents"] == {"demo-chat": "slack"} and "surface_agents" not in row("projects/mixed"), row().get("surface_agents"))
PR = prec()
check("projects.json: a slack agent's record carries the surface, a sala agent's has none", PR["agents"]["demo-chat"]["surface"] == "slack" and PR["agents"]["demo-chat"]["front"] is True
      and all("surface" not in a for n, a in PR["agents"].items() if n != "demo-chat"), PR["agents"])
check("projects.json: the keeper and the main of the project are the sala agents", PR["keeper"] != "demo-chat" and prj.main_of(PR["agents"]) == "demo-main", (PR["keeper"], prj.main_of(PR["agents"])))
FR = anchors.file_roles(anchors.registry(), set())
check("roles.json: a slack agent is a front agent with the surface slack", {k: v for k, v in FR["demo-chat"].items() if k != "live"} == {"role": "front", "project": "projects/demo", "surface": "slack"}, FR["demo-chat"])
check("roles.json: a sala agent has no surface field, as before", "surface" not in FR["demo-main"] and "surface" not in FR["demo-docs"] and "surface" not in FR["demo-builder"] and FR["demo-main"]["role"] == "front", FR["demo-main"])
check("roles.json: the same through session_roles (the server's own gates)", anchors.session_roles(anchors.registry(), set())["demo-chat"]["surface"] == "slack" and anchors.session_roles(anchors.registry(), set())["demo-chat"]["role"] == "front")
check("roles.json: written to the file with the surface for the slack agent only", (pr._roles_sync(now=1.0e9) or True) and json.loads((T / "state/roles.json").read_text())["sessions"]["demo-chat"].get("surface") == "slack"
      and "surface" not in json.loads((T / "state/roles.json").read_text())["sessions"]["demo-main"])
prj.sync(force=True); PJ = json.loads(pr.PROJECTS.read_text())["projects"][D]
check("projects.json: the published file has it too", PJ["agents"]["demo-chat"]["surface"] == "slack" and "surface" not in PJ["agents"]["demo-main"], PJ["agents"])

# ---- 4. the pickers skip a slack agent, and another front agent of the project is still found
R = row()
check("front_agents: leaves a slack agent out, the other front agents stay in the page's order", anchors.front_agents(R) == ["demo-main", "demo-docs", "demo-plain", "demo-explicit", "demo-implicit"], anchors.front_agents(R))
check("main_of: the -main agent, not a slack agent", anchors.main_of(R) == "demo-main" and anchors.main_of({"agents": {"demo-chat": "c", "demo-docs": "d"}, "surface_agents": {"demo-chat": "slack"}}) == "demo-docs")
check("main_of: a project whose only front agent is a slack agent has none (the page's hub or the scope's general one answers)", anchors.main_of({"agents": {"demo-chat": "c"}, "surface_agents": {"demo-chat": "slack"}}) == ""
      and anchors.front_agents({"agents": {"demo-chat": "c"}, "surface_agents": {"demo-chat": "slack"}}) == [])
check("keeper.successor: a slack agent never takes the mark; the -main agent, else the first sala front agent, does", _kp.successor({"demo-chat": {"front": True, "mandate_line": "c", "surface": "slack"}, "demo-docs": {"front": True, "mandate_line": "d"}}) == "demo-docs"
      and _kp.successor({"demo-chat": {"front": True, "mandate_line": "c", "surface": "slack"}}) == "" and _kp.successor({"demo-chat": {"front": True, "mandate_line": "c", "surface": "slack"}, "demo-x-main": {"front": True, "mandate_line": "m"}}) == "demo-x-main")
check("successor: the hand-over list of the page names the slack agent nowhere, the sala front agents stay, in order", [n for n, _k in wsucc.agents_of(R)] == ["demo-main", "demo-docs", "demo-plain", "demo-explicit", "demo-implicit", "demo-builder"], wsucc.agents_of(R))
check("successor: a page whose only listed front agent is a slack agent lists no front agent", wsucc.agents_of({"agents": {"demo-chat": "c", "demo-b": "builds"}, "back_agents": {"demo-b": "builds"}, "surface_agents": {"demo-chat": "slack"}}) == [("demo-b", "back")])
cx = router.Context(); fr, bk = cx.agents("projects/demo")
check("router: the recipients of a notice are the sala front agents and the background agents, never the slack agent", "demo-chat" not in fr and set(fr) >= {"demo-main", "demo-docs"} and set(bk) == {"demo-builder"} and cx.main_agent("projects/demo") == "demo-main", (fr, bk))
fl, bl = router_live._agents_of("projects/demo", anchors.registry())
check("router_live: the same for the live router's agents of a project", "demo-chat" not in fl and "demo-main" in fl and set(bl) == {"demo-builder"}, (fl, bl))
genv = audit_run.Env(); genv.fallback = None
check("audit: the project's -main agent (the recipient of a finding) is a sala agent, and so is the fallback of a project", genv.main_of("projects/demo") == "demo-main" and anchors.fallback_main("projects/demo") == "demo-main", genv.main_of("projects/demo"))
check("audit: an item's contact and its front agents never offer the slack agent", "demo-chat" not in __import__("stackshot.model.contact", fromlist=["fronts"]).fronts("projects/demo") and "demo-main" in __import__("stackshot.model.contact", fromlist=["fronts"]).fronts("projects/demo"))
check("gates: a slack agent is still a front agent for the gates that guard one (roles.json says front, retired is not set)", FR["demo-chat"]["role"] == "front" and not FR["demo-chat"].get("retired"))
# a project whose only front agent besides its slack agent is gone: the project falls to its hub's or the scope's -main agent, as one with no front agent does
check("a project with a slack agent and a builder only: the front agents of its page are empty and nobody is the slack agent's -main", (lambda e: anchors.front_agents(e) == [] and anchors.main_of(e) == "")(
      {"agents": {"demo-mixed-chat": "c", "demo-mixed-builder": "builds"}, "back_agents": {"demo-mixed-builder": "builds"}, "surface_agents": {"demo-mixed-chat": "slack"}}))

# ---- 4b. a page line never makes a slack agent the keeper (the page's `keeper:` line, a sub-page's `agent:` line, a sub-page mark in the record)
from stackshot.tools import registry_report as rreport
from stackshot.projects import keeper_subpages as ksub
check("page keeper: setup: the slack agent is listed through the verb", pv.agent_add(WM, "wm-chat", True, "answers", surface="slack", io=IO)["changed"] and entry(WM)["agents"]["wm-chat"]["surface"] == "slack")
pt = text("projects/wm"); page("projects/wm.md", pt.split("---\n")[1].rstrip("\n") + "\nkeeper: wm-chat", pt.split("---\n", 2)[2].lstrip("\n"))
pr.update(lambda e: [a.pop("keeper", None) for a in e[WM]["agents"].values()])       # the page's line alone names the keeper: no flag in the record
p.cmd_registry(quiet=True)
WR = anchors.registry()["projects/wm"]; WRAW = prj.registry_raw()["projects/wm"]
check("page keeper: setup: the page's own line names the agent the record lists as a slack agent, and no record flag is left", WRAW.get("role") == "mark" and WRAW.get("session") == "wm-chat" and not _kp.record_mark(entry(WM)["agents"])[0], (WRAW.get("role"), WRAW.get("session")))
check("page keeper: effective_mark skips the slack agent as it skips a name the record does not list", _kp.effective_mark(entry(WM)["agents"], WRAW) == "", _kp.effective_mark(entry(WM)["agents"], WRAW))
check("page keeper: the registry row is not marked, and its keeper_problems say a slack agent cannot be the keeper", WR.get("role") != "mark" and WR.get("session") != "wm-chat" and any("slack agent" in x and "wm-chat" in x for x in WR.get("keeper_problems") or []), (WR.get("role"), WR.get("session"), WR.get("keeper_problems")))
check("page keeper: keeper.fields, the notice name and the router's stand-in are not the slack agent", _kp.fields("projects/wm", anchors.registry())["keeper_agent"] != "wm-chat" and anchors.notice_name("projects/wm") != "wm-chat"
      and router_live.stand_in_of("projects/wm", anchors.registry()) != "wm-chat", (_kp.fields("projects/wm", anchors.registry()), anchors.notice_name("projects/wm"), router_live.stand_in_of("projects/wm", anchors.registry())))
WFR = anchors.file_roles(anchors.registry(), set())["wm-chat"]
check("page keeper: roles.json never gives the slack agent keeper true, and it stays a front agent", "keeper" not in WFR and WFR["role"] == "front" and "keeper" not in anchors.session_roles(anchors.registry(), set())["wm-chat"], WFR)
check("page keeper: the published record does not name it as the keeper either", prec("projects/wm")["keeper"] != "wm-chat" and not prec("projects/wm")["agents"]["wm-chat"].get("keeper"), prec("projects/wm")["keeper"])
check("page keeper: the registry check's debts say so in the line the existing skip uses (keeper-not-listed)", any(k == "keeper-not-listed" and "wm-chat" in t for k, t in _kp.problems_of(entry(WM)["agents"], WRAW)), _kp.problems_of(entry(WM)["agents"], WRAW))
SUBK = "projects/wm/notes"
dec = [r for r in ksub.build(pr.entries(), prj.registry_raw(), live=set(), renames={})[1] if r["key"] == SUBK]
check("sub-page agent line: the page's `agent:` line names the slack agent, and the pass decides it as it decides a name no project lists: the page follows the keeper above", prj.registry_raw()[SUBK].get("session") == "wm-chat" and dec and dec[0]["action"] == "inherit", dec)
pr.update(lambda e: e[WM].setdefault(_kp.PAGES, {}).update({"projects/wm/log": "wm-chat"}))
LG = anchors.registry()["projects/wm/log"]
check("sub-page mark: a page_keepers mark naming the slack agent is ignored and said on the project's row; the sub-page's keeper is not the slack agent", LG.get("session") != "wm-chat" and not LG.get(_kp.PAGE_MARK)
      and any("projects/wm/log" in x and "Slack agent" in x for x in anchors.registry()["projects/wm"].get("keeper_problems") or []), (LG.get("session"), anchors.registry()["projects/wm"].get("keeper_problems")))
pr.update(lambda e: e[WM].pop(_kp.PAGES, None))

# ---- 4c. the registry check's recipient, the hub sessions, project.main_of and the roles file's "real" test; a project with no page
pv.agent_add(RB, "rb-builder", False, "builds and merges", io=IO); pv.agent_add(RB, "rb-chat", True, "answers", surface="slack", io=IO); pv.agent_add(RB, "rb-ui", True, "the ui", io=IO)
LIVE = {"rb-builder", "rb-chat", "rb-ui"}; FND = {"project": RB, "page": "projects/rb"}
check("registry check: the recipient of a finding is the project's sala front agent, not the slack agent listed before it", rreport.recipient(FND, pr.entries(), anchors.registry(), LIVE) == "rb-ui", rreport.recipient(FND, pr.entries(), anchors.registry(), LIVE))
pv.agent_retire(RB, "rb-ui", io=IO)
check("registry check: with the sala front agent retired the slack agent is still nobody's recipient (the page's recipient answers)", rreport.recipient(FND, pr.entries(), anchors.registry(), LIVE) != "rb-chat", rreport.recipient(FND, pr.entries(), anchors.registry(), LIVE))
from stackshot.service import item_read as _item_read
_hub = _item_read._hub_sessions("projects/demo")
check("hub sessions: an item's front agents leave out the slack agent and keep the sala ones", "demo-chat" not in _hub[3] and "demo-main" in _hub[3] and "demo-builder" in _hub[2], _hub)
check("projects.main_of: a slack agent is skipped, the project's -main agent is the answer", prj.main_of({"demo-a-main": {"front": True, "surface": "slack"}, "demo-main": {"front": True}}) == "demo-main"
      and prj.main_of({"demo-a-main": {"front": True, "surface": "slack"}}) == "", prj.main_of({"demo-a-main": {"front": True, "surface": "slack"}, "demo-main": {"front": True}}))
ONLY = {"projects/solo": {"session": "solo", "role": "name", "status": "active", "agents": {"solo-chat": "answers"}, "back_agents": {}, "surface_agents": {"solo-chat": "slack"}}}
check("roles file: a page whose only listed front agent is a slack agent has no user-facing agent, so its name-line session is the one session of a one-session project (front)", anchors.file_roles(ONLY, set()).get("solo", {}).get("role") == "front", anchors.file_roles(ONLY, set()).get("solo"))
PL = pv.create("demo-pl", "home", by="demo-form", io=IO)["project"]
pv.agent_add(PL, "demo-pl-main", True, "the project's agent", io=IO)
check("page-less project: pageless_rec keeps the surface of a slack agent and no other agent has one", pv.agent_add(PL, "demo-pl-chat", True, "answers", surface="slack", io=IO)["changed"] and pv.pageless_rec(PL)["agents"]["demo-pl-chat"].get("surface") == "slack"
      and "surface" not in pv.pageless_rec(PL)["agents"]["demo-pl-main"], pv.pageless_rec(PL)["agents"])

# ---- 5. a record that names no surface reads exactly as before
check("before: a project that lists no slack agent has no surface field anywhere (row, roles.json, projects.json)", "surface_agents" not in row("projects/mixed") and all("surface" not in v for k, v in FR.items() if v["project"] == "projects/mixed")
      and all("surface" not in a for a in prec("projects/mixed")["agents"].values()))
pv.agent_add(M, "demo-mixed-extra", True, "one more", io=IO)
check("before: a record with sala agents only has entries of the old shape and the old rows", all(set(a) <= {"front", "mandate_line", "by", "at", "keeper"} for a in entry(M)["agents"].values()) and "surface_agents" not in row("projects/mixed")
      and anchors.front_agents(row("projects/mixed")) == ["demo-mixed-docs", "demo-mixed-extra"] and anchors.main_of(row("projects/mixed")) == "demo-mixed-docs")
# a hand-written old record: no surface anywhere, written by an earlier version
old = {"agents": {"demo-main": {"front": True, "mandate_line": "m", "keeper": True}, "demo-docs": {"front": False, "mandate_line": "d"}}}
check("before: an old record parses, and its keeper and main are what they were", pr.parse({"projects": {X: {**GOOD, **old}}})[X]["agents"]["demo-main"] == old["agents"]["demo-main"] and _kp.successor(old["agents"]) == "demo-main")
check("before: a stored sala is read as no surface", row("projects/demo") is not None and _kp.off_sala({"front": True, "surface": "sala"}) is False)

# ---- 6. the call: `post project-agent` on a temporary store
_cfg.CFG["project_agent"] = {"form_senders": ["demo-form"], "form_machines": ["box-a"]}
def call(project, name, role, front, mandate="answers", **extra): return _rt_client._client_post("box-a", "project-agent", {"project": project, "name": name, "role": role, "front": front, "mandate": mandate, "sender": "demo-form", **extra})
st, out = call("projects/mixed", "demo-mixed-slack", "slack", True)
check("call: the role slack lists a front agent with the surface slack (no surface needed)", st == 200 and out["agent"]["demo-mixed-slack"]["surface"] == "slack" and entry(M)["agents"]["demo-mixed-slack"]["surface"] == "slack", (st, out))
st, out = call("projects/mixed", "demo-mixed-chat2", "dm", True, surface="slack")
check("call: any role with the surface slack lists one", st == 200 and entry(M)["agents"]["demo-mixed-chat2"]["surface"] == "slack" and "surface slack" in out["note"], (st, out))
st, out = call("projects/mixed", "demo-mixed-same", "docs", True, surface="sala")
check("call: the surface sala is the default, never stored", st == 200 and "surface" not in entry(M)["agents"]["demo-mixed-same"] and "surface" not in out["agent"]["demo-mixed-same"], (st, out))
rec1 = REC.read_bytes()
for label, args, want in (("a surface that is none of them", ("demo-mixed-p", "p", True, "x"), "carrier-pigeon"), ):
    st, out = call("projects/mixed", args[0], args[1], args[2], surface=want)
    check(f"call: {label} is a 400 in words", st == 400 and out["error"].startswith("surface 'carrier-pigeon' is not known; a surface is sala or slack") and REC.read_bytes() == rec1, (st, out))
st, out = call("projects/mixed", "demo-mixed-slack2", "slack", False)
check("call: the role slack as a background agent is a 400", st == 400 and "front agent" in out["error"] and REC.read_bytes() == rec1, (st, out))
st, out = call("projects/mixed", "demo-mixed-slack3", "slack", True, surface="sala")
check("call: the role slack with the surface sala is a 400 (they say two things)", st == 400 and REC.read_bytes() == rec1, (st, out))
st, out = call("projects/mixed", "demo-mixed-main", "main", True, surface="slack")
check("call: a slack agent named -main is a 400", st == 400 and "-main" in out["error"] and REC.read_bytes() == rec1, (st, out))
st, out = call("projects/mixed", "demo-mixed-slack", "slack", True)
check("call: said again as it stands it changes nothing (200)", st == 200 and "nothing changed" in out["note"], (st, out))
st, out = call("projects/mixed", "demo-mixed-slack", "docs", True, mandate="answers", surface="sala")
check("call: the same name with another surface is a 409", st == 409 and "slack" in out["error"], (st, out))
st, out = call("projects/mixed", "demo-mixed-up", "Slack", True)
check("call: the role `Slack` is the role word too (never a sala agent that is merely called Slack)", st == 200 and entry(M)["agents"]["demo-mixed-up"].get("surface") == "slack", (st, out))
st, out = call("projects/mixed", "demo-mixed-up2", "slack", False)
check("call: …and with the side back it is refused as the role slack is", st == 400 and "demo-mixed-up2" not in entry(M)["agents"], (st, out))
st, out = call(PL, "demo-pl-chat2", "slack", True)
st2, out2 = call(PL, "demo-pl-chat2", "slack", True)
check("call: on a project with no page the same slack agent listed twice is a 200 the second time, nothing changed (a lost answer retried does not fail)", st == 200 and st2 == 200 and "nothing changed" in out2["note"] and entry(PL)["agents"]["demo-pl-chat2"]["surface"] == "slack", (st, out, st2, out2))
st, out = call("projects/mixed", "demo-mixed-surf", "surf", True, surface=3)
check("call: a surface that is no text is a 400", st == 400, (st, out))
# the client: its arguments become the body
sent = []
client.post = lambda what, body, timeout=20.0: (sent.append((what, body)) or _rt_client._client_post("box-a", what, body))
os.environ["CLAUDE_CODE_SESSION_ID"] = "demo-form"
rc = client.project_agent(["projects/mixed", "demo-mixed-cli", "--role", "slack", "--front", "--surface", "slack", "--mandate", "answers from the client"])
check("client: --surface slack goes in the body, and the agent is listed", rc == 0 and sent[-1][1]["surface"] == "slack" and sent[-1][1]["front"] is True and entry(M)["agents"]["demo-mixed-cli"]["surface"] == "slack", (rc, sent[-1:]))
rc = client.project_agent(["projects/mixed", "demo-mixed-cli2", "--role", "slack", "--mandate", "answers, side left out"])
check("client: the role slack alone is a front agent on the surface slack", rc == 0 and sent[-1][1]["front"] is True and "surface" not in sent[-1][1] and entry(M)["agents"]["demo-mixed-cli2"]["surface"] == "slack", (rc, sent[-1:]))
rc = client.project_agent(["projects/mixed", "demo-mixed-cli3", "--role", "docs", "--front", "--mandate", "no surface asked"])
check("client: no --surface sends none, as before", rc == 0 and "surface" not in sent[-1][1] and "surface" not in entry(M)["agents"]["demo-mixed-cli3"], (rc, sent[-1:]))
rc = client.project_agent(["projects/mixed", "demo-mixed-cli4", "--role", "slack", "--back", "--surface", "slack", "--mandate", "wrong"])
check("client: a slack agent with --back is refused by the server (exit 1)", rc == 1 and "demo-mixed-cli4" not in entry(M)["agents"], rc)
rc = client.project_agent(["projects/mixed", "demo-mixed-cli5", "--role", "slack", "--front", "--surface", "carrier-pigeon", "--mandate", "wrong"])
check("client: a surface that is unknown is refused by the server (exit 1)", rc == 1 and "demo-mixed-cli5" not in entry(M)["agents"], rc)
rc = client.project_agent(["projects/mixed", "demo-mixed-cli6", "--role", "docs", "--mandate", "no side"])
check("client: another role with no --front or --back is still the usage (exit 1)", rc == 1)
rc = client.project_agent(["projects/mixed", "demo-mixed-cli7", "--role", "slack", "--front", "--surface"])
check("client: --surface with no value is refused (exit 1)", rc == 1)
os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
check("client: the usage text names --surface", "--surface" in client.PROJECT_AGENT_USAGE)

# ---- 7. what he sees: the sessions tool says slack
FR = anchors.file_roles(anchors.registry(), set())
_idx = {"s1": {"name": "demo-chat", "machine": "a", "url": "https://link.test/n/a12", "seen": "x"}, "s2": {"name": "demo-docs", "machine": "a", "url": "", "seen": "x"}}
sessions_tool._sessions_index = lambda: _idx
sessions_tool._lv.running = lambda v: True
sessions_tool._machine_states = lambda: {"a": "live"}
sessions_tool._fleet_names = lambda: {"a": "box-a"}
listing = sessions_tool._sessions_listing()
check("sessions tool: a slack agent's role reads `slack agent`, a sala front agent's `front agent`", "demo-chat — https://link.test/n/a12 · box-a · slack agent of projects/demo" in listing and "demo-docs —" in listing and "· front agent of projects/demo" in listing, listing)

check("tool text: the sessions tool's text lists the role `slack agent` it returns", "slack agent" in open(f"{STACK}/stackshot/web/tools/text/sessions.md", encoding="utf-8").read())

# ---- 8. the CLI shows the surface
import subprocess
r = subprocess.run([sys.executable, f"{STACK}/stackshot/tools/project.py", "show", "projects/demo"], capture_output=True, text=True, env=os.environ, cwd=str(T))
check("project.py show: a slack agent's line starts with slack, the others with front and back", re.search(r"(?m)^  slack  demo-chat:", r.stdout) and re.search(r"(?m)^  front  demo-main:", r.stdout) and re.search(r"(?m)^  back   demo-builder:", r.stdout), (r.stdout, r.stderr))
r = subprocess.run([sys.executable, f"{STACK}/stackshot/tools/project.py", "agent-add", "projects/mixed", "demo-mixed-tool", "--front", "--surface", "slack", "--mandate", "from the tool"], capture_output=True, text=True, env=os.environ, cwd=str(T))
check("project.py agent-add: --surface slack lists a slack agent", r.returncode == 0 and entry(M)["agents"]["demo-mixed-tool"]["surface"] == "slack", (r.stdout, r.stderr))

print(f"{len(ran) - len(fails)}/{len(ran)} passed")
sys.exit(1 if fails else 0)
