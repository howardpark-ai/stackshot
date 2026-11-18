"""Scenario test for the keeper as a mark on one agent (readers only: nothing writes a mark yet) — fixture data, no live store, no network, no server process.

Covers: the record's flag (`"keeper": true` on one agent entry; a second flag and a flag that is not a boolean are ignored and reported, never a crash) and the page's flat
`keeper: <agent>` line (it counts only when the name is an agent of that page's map; otherwise it is ignored and reported); the order pages.keeper_of reads (the page's line, then
the record's flag, then the old keys exactly as before) and that the record wins where both exist; the derived keeper with no mark (the builder, else the -main agent; a one-session
page keeps its name line); an unnamed sub-page inheriting the keeper of the page above it, a mark included; the registry row and the published record (`keeper_agent`,
`keeper_source`, `legacy_session`, `keeper: true` on the marked agent's record, `keeper_problems`); that a page with no mark answers every old field exactly as it did; that a
mark moves neither the project's name nor any session's role; the sessions that keep a page by the mark, the old fields and a sub-page's `agent:`; and that the project's
name prefix reads a one-session project whose session does not start with its page's slug.

    tests/run-suite keeper_mark        → exit 0 / 1"""
import json, os, re, sys, pathlib, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="keepermark-"); T = pathlib.Path(tmp)
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

# Neutral fixtures. orchard: a page mark on a front agent; ghost: a page mark naming nobody; forge: a builder; loft: a -main agent only; lone-page: a one-session project
# whose session does not start with the page's slug.
page("projects/orchard.md", "type: project\ntitle: Orchard\ndisplay-name: team-orchard\nkeeper: team-orchard-docs\nagents:\n  team-orchard-main: talks to the owner\n  team-orchard-docs: keeps the docs\n"
                            "  background:\n    team-orchard-builder: builds and merges\nstatus: active")
page("projects/orchard/notes.md", "type: note\ntitle: Orchard notes")
page("projects/orchard/deeper/more.md", "type: note\ntitle: Orchard more")
page("projects/orchard/owned.md", "type: project\ntitle: Owned\nagent: team-orchard-main")
page("projects/ghost.md", "type: project\ntitle: Ghost\ndisplay-name: team-ghost\nkeeper: team-ghost-nobody\nagents:\n  team-ghost-main: talks\n  background:\n    team-ghost-builder: builds\nstatus: active")
page("projects/forge.md", "type: project\ntitle: Forge\ndisplay-name: team-forge\nagents:\n  team-forge-main: talks\n  team-forge-docs: keeps the docs\n  background:\n    team-forge-audit: reviews\n    team-forge-builder: builds and merges\n"
                          "    team-forge-second: builds too\nstatus: active")
page("projects/forge/sub.md", "type: project\ntitle: Forge sub")
page("projects/satellite.md", "type: project\ntitle: Satellite\nhub: projects/forge")                 # names nobody, lists no agent: falls to its hub's builder
page("projects/forge/named.md", "type: project\ntitle: Forge named\ndisplay-name: team-other")         # a sub-page with a name line of its own
page("projects/hubbed.md", "type: project\ntitle: Hubbed\ndisplay-name: team-hubbed\nhub: projects/forge")   # a hub-linked page with a name line of its own
page("projects/old-one.md", "type: project\ntitle: Old one\ndisplay-name: team-old\nagents:\n  team-old-main: talks\n  background:\n    team-old-builder: builds\nstatus: archived")
page("projects/scoped.md", "type: project\ntitle: Scoped\ndisplay-name: home-scp\nagents:\n  home-scp-main: talks\n  work-scp-docs: keeps the docs\nstatus: active")
page("projects/loft.md", "type: project\ntitle: Loft\ndisplay-name: team-loft\nagents:\n  team-loft-main: talks\nstatus: active")
page("projects/lone-page.md", "type: project\ntitle: Lone\ndisplay-name: lone-session\nstatus: active")
page("projects/lone-page/sub.md", "type: note\ntitle: Lone sub")
page("projects/plain-note.md", "type: note\ntitle: A note")
page("projects/nameless.md", "type: project\ntitle: Nameless\nagents:\n  team-nameless-main: talks\nstatus: active")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
def reg(): return json.loads((T / "store/projects.json").read_text())["pages"]
REC = T / "store/project-record.json"
from stackshot.projects import pages as p; from stackshot.projects import projects as prj; from stackshot.projects import project_registry as pr; from stackshot.projects import keeper as kp
from stackshot.anchors import anchors

# ---- 1. the two readers of a mark, on their own
check("record_mark: no flag, no mark", kp.record_mark({"a": {"front": True}, "b": {"front": False, "keeper": False}}) == ("", []) and kp.record_mark({}) == ("", []) and kp.record_mark(None) == ("", []))
check("record_mark: one flag is the mark", kp.record_mark({"a": {"front": True}, "b": {"front": False, "keeper": True}}) == ("b", []))
m, probs = kp.record_mark({"a": {"keeper": True}, "b": {"keeper": True}, "c": {"keeper": True}})
check("record_mark: a second flag is ignored and reported (the first listed stays the mark), once for each extra", m == "a" and len(probs) == 2 and "b" in probs[0] and "c" in probs[1], (m, probs))
m, probs = kp.record_mark({"a": {"keeper": "yes"}, "b": {"keeper": True}})
check("record_mark: a flag that is neither true nor false is a problem, never a crash, and does not become the mark", m == "b" and len(probs) == 1 and "a" in probs[0], (m, probs))
for v in (0, 0.0, "", "no", [], {}, 1, "yes"):
    m, probs = kp.record_mark({"a": {"keeper": v}})
    check(f"record_mark: a flag of {v!r} is not true or false: no mark, one problem line", m == "" and len(probs) == 1, (m, probs))
check("record_mark: only None and False count as unset (no problem), and a missing key", kp.record_mark({"a": {"keeper": None}, "b": {"keeper": False}, "c": {}}) == ("", []))
check("record_mark: garbage in the agents map never raises", kp.record_mark({"a": 5, "b": [1], "c": None}) == ("", []) and kp.record_mark("text") == ("", []))
check("page_mark: a name on the map is the mark", kp.page_mark({"keeper": "x-main"}, {"x-main": "m"}) == ("x-main", []))
m, probs = kp.page_mark({"keeper": "x-ghost"}, {"x-main": "m"})
check("page_mark: a name not on the map is ignored and reported", m == "" and len(probs) == 1 and "x-ghost" in probs[0], (m, probs))
check("page_mark: no line, an empty line and a value that is not one name give no mark (the last one is reported)",
      kp.page_mark({}, {"a": ""}) == ("", []) and kp.page_mark({"keeper": ""}, {"a": ""}) == ("", []) and kp.page_mark({"keeper": ["a", "b"]}, {"a": ""})[0] == ""
      and len(kp.page_mark({"keeper": ["a", "b"]}, {"a": ""})[1]) == 1 and kp.page_mark({"keeper": "a"}, None)[0] == "")

# ---- 2. keeper_of: the page's line first, the old keys as before
fms, rels, skipped = p.read_pages_ex()
check("the fixture pages read", {"projects/orchard", "projects/orchard/notes", "projects/forge", "projects/lone-page"} <= set(fms), sorted(fms))
check("keeper_of: a `keeper:` line naming an agent of the page's map is the mark, role mark", p.keeper_of("projects/orchard", fms) == ("team-orchard-docs", "mark"), p.keeper_of("projects/orchard", fms))
check("keeper_of(marks=False): the old keys alone, the project's name line as it was", p.keeper_of("projects/orchard", fms, marks=False) == ("team-orchard", "name"))
check("keeper_of: an unnamed sub-page inherits the mark (role inherited), at any depth", p.keeper_of("projects/orchard/notes", fms) == ("team-orchard-docs", "inherited") and p.keeper_of("projects/orchard/deeper/more", fms) == ("team-orchard-docs", "inherited"))
check("keeper_of(marks=False): the same sub-pages inherit the project's name, as before", p.keeper_of("projects/orchard/notes", fms, marks=False) == ("team-orchard", "inherited"))
check("keeper_of: a sub-page's own `agent:` line stays its keeper, the mark above it or not", p.keeper_of("projects/orchard/owned", fms) == ("team-orchard-main", "agent"))
check("keeper_of: a `keeper:` line naming nobody on the map is ignored: the name line answers, and the problem is said",
      p.keeper_of("projects/ghost", fms) == ("team-ghost", "name") and len(p.keeper_problems("projects/ghost", fms)) == 1 and "team-ghost-nobody" in p.keeper_problems("projects/ghost", fms)[0] and p.keeper_problems("projects/forge", fms) == [])
check("keeper_of: a page with no line answers as before (the name line; a one-session page; nothing)", p.keeper_of("projects/forge", fms) == ("team-forge", "name") and p.keeper_of("projects/lone-page", fms) == ("lone-session", "name")
      and p.keeper_of("projects/plain-note", fms) == ("", "") and p.keeper_of("projects/nameless", fms) == ("", ""))
check("split_agents is unchanged by the line: the map has no `keeper` agent", set(p.split_agents(fms["projects/orchard"].get("agents"))[0]) == {"team-orchard-main", "team-orchard-docs", "team-orchard-builder"})
check("agent_listed still finds the project by its name line, not by the marked agent", p.agent_listed("team-orchard-docs", fms)[0] == 0 and p.agent_listed("team-orchard-newcomer", fms)[0] == 3, (p.agent_listed("team-orchard-docs", fms), p.agent_listed("team-orchard-newcomer", fms)))

# ---- 3. the registry row
p.cmd_registry(quiet=True); R = reg()
ids = {k: e["id"] for k, e in R.items()}
OLD_KEYS = {"title", "name", "org", "tags", "type", "session", "status", "board", "board_row", "updated", "mirror", "id", "key", "agent_records"}
row = R["projects/orchard"]
check("row, page mark: session is the marked agent, role mark, and the old name line sits beside it", row["session"] == "team-orchard-docs" and row["role"] == "mark" and row["legacy_session"] == "team-orchard" and row["legacy_role"] == "name", row)
check("row, page mark: keeper_agent is the marked agent, source mark; the agent's record carries `keeper: true` and no other agent does",
      row["keeper_agent"] == "team-orchard-docs" and row["keeper_source"] == "mark" and row["agent_records"]["team-orchard-docs"].get("keeper") is True
      and not any("keeper" in r for n, r in row["agent_records"].items() if n != "team-orchard-docs"), row)
sub = R["projects/orchard/notes"]
check("row, sub-page under a mark: the same agent, role inherited, the old inherited name in legacy_session; keeper_agent follows",
      sub["session"] == "team-orchard-docs" and sub["role"] == "inherited" and sub["legacy_session"] == "team-orchard" and sub["keeper_agent"] == "team-orchard-docs" and sub["keeper_source"] == "mark", sub)
check("row, a sub-page's own `agent:` line: that agent, source legacy, no legacy_session (the mark does not touch it)", R["projects/orchard/owned"]["session"] == "team-orchard-main" and R["projects/orchard/owned"]["role"] == "agent"
      and R["projects/orchard/owned"]["keeper_source"] == "legacy" and R["projects/orchard/owned"]["keeper_agent"] == "team-orchard-main" and "legacy_session" not in R["projects/orchard/owned"])
row = R["projects/ghost"]
check("row, a mark naming nobody: ignored, the old fields answer, derived keeper is the builder, the problem is on the row",
      row["session"] == "team-ghost" and row["role"] == "name" and "legacy_session" not in row and row["keeper_agent"] == "team-ghost-builder" and row["keeper_source"] == "derived" and len(row["keeper_problems"]) == 1, row)
row = R["projects/forge"]
check("row, no mark, a builder: the derived keeper is the first builder (a background agent whose mandate says build), the old fields untouched",
      row["keeper_agent"] == "team-forge-builder" and row["keeper_source"] == "derived" and row["session"] == "team-forge" and row["role"] == "name" and not ({"legacy_session", "legacy_role", "keeper_problems"} & set(row)), row)
check("row, no mark, only a -main agent: the derived keeper is the -main agent", R["projects/loft"]["keeper_agent"] == "team-loft-main" and R["projects/loft"]["keeper_source"] == "derived")
check("row, no mark, no name line, a -main agent: derived too, and `session` stays empty", R["projects/nameless"]["keeper_agent"] == "team-nameless-main" and R["projects/nameless"]["keeper_source"] == "derived" and R["projects/nameless"]["session"] == "")
check("row, a one-session page: its session is the keeper, source legacy (no agent is listed to derive from), and so is a sub-page under it",
      R["projects/lone-page"]["keeper_agent"] == "lone-session" and R["projects/lone-page"]["keeper_source"] == "legacy" and R["projects/lone-page/sub"]["keeper_agent"] == "lone-session" and R["projects/lone-page/sub"]["keeper_source"] == "legacy")
check("row, an unnamed sub-page under a project with a builder inherits the derived keeper", R["projects/forge/sub"]["keeper_agent"] == "team-forge-builder" and R["projects/forge/sub"]["keeper_source"] == "derived", R["projects/forge/sub"])
check("row, a sub-page with a name line of its own, and a hub-linked page with one: the old line stays the keeper (legacy), the hub's builder does not take them over",
      (R["projects/forge/named"]["keeper_agent"], R["projects/forge/named"]["keeper_source"]) == ("team-other", "legacy") and (R["projects/hubbed"]["keeper_agent"], R["projects/hubbed"]["keeper_source"]) == ("team-hubbed", "legacy"),
      (R["projects/forge/named"], R["projects/hubbed"]))
check("row, a page that names nobody and lists no agent, linked to a hub that has a builder: the hub's derived keeper", (R["projects/satellite"]["keeper_agent"], R["projects/satellite"]["keeper_source"]) == ("team-forge-builder", "derived"), R["projects/satellite"])
check("row, a retired (archived) project with agents and no mark: no keeper, both fields empty; its old fields are as they were (session team-old, role name)",
      (R["projects/old-one"]["keeper_agent"], R["projects/old-one"]["keeper_source"]) == ("", "") and (R["projects/old-one"]["session"], R["projects/old-one"]["role"]) == ("team-old", "name"), R["projects/old-one"])
check("row, a page nothing keeps: both fields are empty strings", R["projects/plain-note"]["keeper_agent"] == "" and R["projects/plain-note"]["keeper_source"] == "")
unmarked = [k for k in R if k not in ("projects/orchard", "projects/orchard/notes", "projects/orchard/deeper/more", "projects/ghost")]
check("no mark: every row has exactly the old fields (the page's own, the id, the key, the agent records) plus the two new ones, and no legacy, problem or keeper flag",
      all(set(R[k]) - {"role", "hub", "agents", "back_agents", "lead_agents"} == OLD_KEYS | {"keeper_agent", "keeper_source"} and not ({"legacy_session", "legacy_role", "keeper_problems"} & set(R[k]))
          and not any("keeper" in r for r in R[k]["agent_records"].values()) for k in unmarked), [k for k in unmarked if set(R[k]) - {"role", "hub", "agents", "back_agents", "lead_agents"} != OLD_KEYS | {"keeper_agent", "keeper_source"}])
EXPECT = {"projects/forge": ("team-forge", "name"), "projects/loft": ("team-loft", "name"), "projects/lone-page": ("lone-session", "name"), "projects/lone-page/sub": ("lone-session", "inherited"),
          "projects/forge/sub": ("team-forge", "inherited"), "projects/ghost": ("team-ghost", "name"), "projects/orchard/owned": ("team-orchard-main", "agent"), "projects/nameless": ("", ""),
          "projects/plain-note": ("", ""), "projects/forge/named": ("team-other", "name"), "projects/hubbed": ("team-hubbed", "name"), "projects/satellite": ("", ""), "projects/old-one": ("team-old", "name")}
check("no mark: session and role are the values the old fields give (fixed expectations, written out)", all((R[k].get("session", ""), R[k].get("role", "")) == v for k, v in EXPECT.items()),
      {k: (R[k].get("session", ""), R[k].get("role", "")) for k in EXPECT})
check("no mark: and agrees with keeper_of(marks=False) on every page", all((R[k].get("session", ""), R[k].get("role", "")) == p.keeper_of(k, fms, marks=False) for k in unmarked))

# the start-time backfill: a registry file written before the keeper fields gets them, once
doc = json.loads((T / "store/projects.json").read_text()); want = {k: {f: e[f] for f in ("keeper_agent", "keeper_source")} for k, e in doc["pages"].items()}
for e in doc["pages"].values(): e.pop("keeper_agent", None); e.pop("keeper_source", None)
(T / "store/projects.json").write_text(json.dumps(doc), encoding="utf-8")
check("stamp_registry: a file with no keeper fields is rewritten once, and every page gets the fields cmd_registry gives it", prj.stamp_registry() is True and {k: {f: e[f] for f in ("keeper_agent", "keeper_source")} for k, e in reg().items()} == want)
check("stamp_registry: the second call changes nothing", prj.stamp_registry() is False)

# ---- 4. what keeps a page
check("keepers_any / keeper_pages: the marked agent keeps the page and the pages under it", p.keepers_any(["team-orchard-docs"]) and p.keeper_pages("x", "team-orchard-docs") == ["projects/orchard", "projects/orchard/deeper/more", "projects/orchard/notes"], p.keeper_pages("x", "team-orchard-docs"))
check("… the old name line keeps them too (the old rule), and a sub-page's `agent:` keeps its page by itself",
      p.keepers_any(["team-orchard"]) and p.keeper_pages("x", "team-orchard") == ["projects/orchard", "projects/orchard/deeper/more", "projects/orchard/notes"] and p.keeper_pages("x", "team-orchard-main") == ["projects/orchard/owned"], p.keeper_pages("x", "team-orchard-main"))
check("… a derived keeper keeps nothing by it (a builder is told what moved, it does not keep every page): no change for a page with no mark", not p.keepers_any(["team-forge-builder"]) and p.keeper_pages("x", "team-forge-builder") == [] and p.keeper_pages("x", "team-forge") == ["projects/forge", "projects/forge/sub"])
check("… a session that keeps nothing is not a keeper", not p.keepers_any(["team-nobody"]))

# ---- 5. the project record: the flag, laid over the registry
def agent(front, mandate, **kw): return {"front": front, "mandate_line": mandate, **kw}
def write_record(entries):
    d = json.loads(REC.read_text()) if REC.exists() else {}
    d.update({"projects": entries, "projects_schema": 1}); REC.write_text(json.dumps(d), encoding="utf-8"); pr._CACHE["sig"] = None
def entry(key, **kw): return {"page": key, "status": "active", **kw}
F, L, O, G = (ids[k] for k in ("projects/forge", "projects/loft", "projects/orchard", "projects/ghost"))
S_roles0 = anchors.session_roles(prj.registry(), set()); F_roles0 = anchors.file_roles(prj.registry(), set()); name0 = {k: prj.fields(k)["display_name"] for k in ("projects/forge", "projects/loft", "projects/orchard", "projects/lone-page")}
write_record({F: entry("projects/forge", name="team-forge", agents={"team-forge-main": agent(True, "talks"), "team-forge-docs": agent(True, "keeps the docs", keeper=True),
                                                                   "team-forge-audit": agent(False, "reviews"), "team-forge-builder": agent(False, "builds and merges", keeper=True)}),
              L: entry("projects/loft", name="team-loft", agents={"team-loft-main": agent(True, "talks", keeper="yes")}),
              O: entry("projects/orchard", name="team-orchard", agents={"team-orchard-main": agent(True, "talks to the owner", keeper=True), "team-orchard-docs": agent(True, "keeps the docs"),
                                                                       "team-orchard-builder": agent(False, "builds and merges")})})
check("the record parses with the flag on agent entries (a flag is no schema error: the entries still read)", set(pr.entries()) == {F, L, O}, pr.record_error())
RR = prj.registry()
row = RR["projects/forge"]
check("record, two flags: the first flagged agent is the mark, the second is ignored and reported", row["session"] == "team-forge-docs" and row["role"] == "mark" and row["keeper_agent"] == "team-forge-docs" and row["keeper_source"] == "mark"
      and row["legacy_session"] == "team-forge" and row["legacy_role"] == "name" and len(row["keeper_problems"]) == 1 and "team-forge-builder" in row["keeper_problems"][0], row)
check("record, the marked agent's record carries `keeper: true`, and only it", [n for n, r in row["agent_records"].items() if r.get("keeper")] == ["team-forge-docs"], row["agent_records"])
check("record, a sub-page under the marked page takes the mark (role inherited, old value in legacy_session)", RR["projects/forge/sub"]["session"] == "team-forge-docs" and RR["projects/forge/sub"]["role"] == "inherited"
      and RR["projects/forge/sub"]["legacy_session"] == "team-forge" and RR["projects/forge/sub"]["keeper_agent"] == "team-forge-docs" and RR["projects/forge/sub"]["keeper_source"] == "mark", RR["projects/forge/sub"])
row = RR["projects/loft"]
check("record, a flag that is not a boolean: no mark, reported, the name overlay and the derived keeper as without it", row["session"] == "team-loft" and row["role"] == "name" and row["keeper_agent"] == "team-loft-main" and row["keeper_source"] == "derived"
      and len(row["keeper_problems"]) == 1 and "legacy_session" not in row, row)
row = RR["projects/orchard"]
check("record + page, both mark: the record's flag wins (it is laid over the page's row, as every record field is); the page's name line is still the legacy value", row["session"] == "team-orchard-main" and row["role"] == "mark"
      and row["keeper_agent"] == "team-orchard-main" and row["legacy_session"] == "team-orchard" and RR["projects/orchard/notes"]["session"] == "team-orchard-main" and RR["projects/orchard/notes"]["keeper_agent"] == "team-orchard-main"
      and RR["projects/orchard/deeper/more"]["session"] == "team-orchard-main", (row, RR["projects/orchard/notes"]))
check("record + page: the page's own `agent:` sub-page keeps its agent", RR["projects/orchard/owned"]["session"] == "team-orchard-main" and RR["projects/orchard/owned"]["role"] == "agent")
check("record, an entry that flags nobody leaves the page's mark in force", (write_record({O: entry("projects/orchard", name="team-orchard", agents={"team-orchard-main": agent(True, "talks to the owner"), "team-orchard-docs": agent(True, "keeps the docs"),
                                                                                                                                                  "team-orchard-builder": agent(False, "builds and merges")})}), prj.registry()["projects/orchard"]["session"] == "team-orchard-docs")[1])
check("record, an entry whose agents no longer list the page's marked agent: the old lines answer again, sub-pages too",
      (write_record({O: entry("projects/orchard", name="team-orchard", agents={"team-orchard-main": agent(True, "talks to the owner")})}),
       prj.registry()["projects/orchard"]["session"] == "team-orchard" and prj.registry()["projects/orchard"]["role"] == "name" and "legacy_session" not in prj.registry()["projects/orchard"]
       and prj.registry()["projects/orchard/notes"]["session"] == "team-orchard" and "legacy_session" not in prj.registry()["projects/orchard/notes"])[1], prj.registry()["projects/orchard"])
write_record({F: entry("projects/forge", name="team-forge", agents={"team-forge-main": agent(True, "talks"), "team-forge-docs": agent(True, "keeps the docs", keeper=True), "team-forge-audit": agent(False, "reviews"),
                                                                   "team-forge-builder": agent(False, "builds and merges")}),
              L: entry("projects/loft", name="team-loft", agents={"team-loft-main": agent(True, "talks")}), G: entry("projects/ghost", name="team-ghost", agents={"team-ghost-main": agent(True, "talks"), "team-ghost-builder": agent(False, "builds")})})
RR = prj.registry()

# ---- 6. the published record
B = prj.build()["projects"]
rec = B[F]
check("published, a mark: keeper and keeper_agent are the marked agent, source mark, the agent's record carries `keeper: true`, and legacy_session holds the old value",
      rec["keeper"] == "team-forge-docs" and rec["keeper_agent"] == "team-forge-docs" and rec["keeper_source"] == "mark" and rec["legacy_session"] == "team-forge"
      and [n for n, a in rec["agents"].items() if a.get("keeper")] == ["team-forge-docs"] and rec["agents"]["team-forge-docs"]["role"] == "docs", rec)
check("published, the project's name and prefix stay the name line: the agents' roles are cut from it, and fields() says the same display name as without the mark",
      rec["agents"]["team-forge-builder"]["role"] == "builder" and rec["agents"]["team-forge-main"]["role"] == "main" and prj.fields("projects/forge")["display_name"] == "team-forge" == name0["projects/forge"], (rec["agents"], prj.fields("projects/forge")["display_name"]))
check("published, a sub-page under the mark: its keeper is the marked agent too", B[ids["projects/forge/sub"]]["keeper"] == "team-forge-docs" and B[ids["projects/forge/sub"]]["keeper_source"] == "mark")
rec = B[G]
check("published, a project whose page mark names nobody: keeper keeps its value, keeper_agent is derived, no flag on any agent, no legacy_session, the ignored mark is reported",
      rec["keeper"] == "team-ghost" and rec["keeper_agent"] == "team-ghost-builder" and rec["keeper_source"] == "derived" and not any("keeper" in a for a in rec["agents"].values()) and "legacy_session" not in rec and len(rec["keeper_problems"]) == 1, rec)
check("published, a one-session project: keeper_agent is its session, source legacy", B[ids["projects/lone-page"]]["keeper_agent"] == "lone-session" and B[ids["projects/lone-page"]]["keeper_source"] == "legacy" and B[ids["projects/lone-page"]]["keeper"] == "lone-session")
check("published, a project the registry file holds no fields for yet (a file from before the keeper fields) is read now: same answer",
      (lambda r0: prj._record("projects/ghost", {k: v for k, v in r0.items() if k not in ("keeper_agent", "keeper_source")}, {**prj.registry(), "projects/ghost": {k: v for k, v in r0.items() if k not in ("keeper_agent", "keeper_source")}}, G, {})["keeper_agent"])(prj.registry()["projects/ghost"]) == "team-ghost-builder")

# ---- 7. a mark moves nothing else: the project's name, the roles
write_record({F: entry("projects/forge", name="team-forge2", agents={"team-forge-main": agent(True, "talks"), "team-forge-docs": agent(True, "keeps the docs"), "team-forge-audit": agent(False, "reviews"),
                                                                    "team-forge-builder": agent(False, "builds and merges")}),
              L: entry("projects/loft", name="team-loft", agents={"team-loft-main": agent(True, "talks")})})
S_unmarked = anchors.session_roles(prj.registry(), set()); F_unmarked = anchors.file_roles(prj.registry(), set())
check("section 7's fixture: the record's name (team-forge2) differs from the page's display-name (team-forge), and the page's name is no name line any more", prj.registry()["projects/forge"]["session"] == "team-forge2" and "team-forge" not in S_unmarked and "team-forge2" in S_unmarked, sorted(S_unmarked))
write_record({F: entry("projects/forge", name="team-forge2", agents={"team-forge-main": agent(True, "talks"), "team-forge-docs": agent(True, "keeps the docs", keeper=True), "team-forge-audit": agent(False, "reviews"),
                                                                    "team-forge-builder": agent(False, "builds and merges")}),
              L: entry("projects/loft", name="team-loft", agents={"team-loft-main": agent(True, "talks", keeper=True)})})
check("a record mark: the sub-page keeps what it was beside the marked agent, session and role, so no name line is offered for it", prj.registry()["projects/forge/sub"]["legacy_session"] == "team-forge"
      and prj.registry()["projects/forge/sub"]["legacy_role"] == "inherited" and prj.registry()["projects/forge/sub"]["session"] == "team-forge-docs", prj.registry()["projects/forge/sub"])
check("a mark changes no session's role: session_roles and file_roles (roles.json) are the same with the mark as without it", anchors.session_roles(prj.registry(), set()) == S_unmarked and anchors.file_roles(prj.registry(), set()) == F_unmarked)
check("… and the project's name: fields() reads the name line the mark took the place of (here the record's, which differs from the page's)", prj.fields("projects/forge")["display_name"] == "team-forge2" and prj.fields("projects/loft")["display_name"] == "team-loft" and prj.fields("projects/forge")["main"] == "team-forge-main")
check("… a project's scope and the agent_gap test read the same (a marked front agent is not a gap)", prj.agent_gap("projects/forge", prj.registry()["projects/forge"], prj.registry()) is None)

# a mark moves no scope: the marked agent's own prefix (work-) is not the project's
cfgps = prj._cfg.CFG.get("project_scopes", "absent"); prj._cfg.CFG["project_scopes"] = {"order": ["home", "work"], "default": "home"}
SC = ids["projects/scoped"]
try:
    write_record({SC: entry("projects/scoped", name="home-scp", agents={"home-scp-main": agent(True, "talks"), "work-scp-docs": agent(True, "keeps the docs")})})
    reg0 = prj.registry(); sc0 = (prj.derive_scope("projects/scoped", reg0["projects/scoped"], reg0), prj.build()["projects"][SC]["scope"])
    write_record({SC: entry("projects/scoped", name="home-scp", agents={"home-scp-main": agent(True, "talks"), "work-scp-docs": agent(True, "keeps the docs", keeper=True)})})
    reg1 = prj.registry(); sc1 = (prj.derive_scope("projects/scoped", reg1["projects/scoped"], reg1), prj.build()["projects"][SC]["scope"])
    check("a mark moves no scope: the marked agent (work-scp-docs) has another scope's prefix, and derive_scope and the published scope are what they were without the mark", reg1["projects/scoped"]["session"] == "work-scp-docs"
          and sc0 == ("home", "home") and sc1 == sc0, (sc0, sc1))
finally:
    if cfgps == "absent": prj._cfg.CFG.pop("project_scopes", None)
    else: prj._cfg.CFG["project_scopes"] = cfgps
    page("projects/scoped.md", "type: project\ntitle: Scoped\ndisplay-name: home-scp\nagents:\n  home-scp-main: talks\n  work-scp-docs: keeps the docs\nstatus: active"); p.cmd_registry(quiet=True)

# a record change that changes a hub's agents reaches the pages that fall to it (the registry file holds their old derived keeper)
SAT = "projects/satellite"
check("hub: the registry file holds the satellite's derived keeper from the hub's builder", reg()[SAT]["keeper_agent"] == "team-forge-builder")
write_record({F: entry("projects/forge", name="team-forge2", agents={"team-forge-main": agent(True, "talks"), "team-forge-docs": agent(True, "keeps the docs")})})
check("hub: the record drops the hub's builder: the satellite's derived keeper follows the hub's -main agent without a registry rebuild", (prj.registry()[SAT]["keeper_agent"], prj.registry()[SAT]["keeper_source"]) == ("team-forge-main", "derived") and reg()[SAT]["keeper_agent"] == "team-forge-builder", prj.registry()[SAT])
write_record({})
check("hub: the record gone, the satellite is back on the hub's builder", prj.registry()[SAT]["keeper_agent"] == "team-forge-builder")

# a mark on a project with no page is not read: it is reported
NOPAGE = prj.ensure_ids(["projects/no-page-at-all"])["projects/no-page-at-all"]       # an id the code mints: a record key whose entry names no page
write_record({NOPAGE: {"status": "active", "name": "team-pageless", "agents": {"team-pageless-main": agent(True, "talks", keeper=True)}}})
pl = prj.fields(NOPAGE)
check("a mark on a record with no page: reported as a problem line, nothing crashes, and the agent's record is as listed", pl and len(pl.get("keeper_problems", [])) == 1 and "team-pageless-main" in pl["agents"], pl)
write_record({NOPAGE: {"status": "active", "name": "team-pageless", "agents": {"team-pageless-main": agent(True, "talks")}}})
check("… and a pageless record with no flag carries no problem", "keeper_problems" not in prj.fields(NOPAGE))
write_record({})

# apply reads nothing but the rows it is given: the registry file readers raise while it lays a marked record over a registry
import contextlib, io
write_record({F: entry("projects/forge", name="team-forge2", agents={"team-forge-main": agent(True, "talks"), "team-forge-docs": agent(True, "keeps the docs", keeper=True), "team-forge-builder": agent(False, "builds")})})
raw = prj.registry_raw(); saved = (anchors.registry, anchors.pilot_roots, p.load_registry)
def _trap(*a, **k): raise AssertionError("apply read the registry file")
anchors.registry = anchors.pilot_roots = p.load_registry = _trap
buf = io.StringIO()
try:
    with contextlib.redirect_stderr(buf): laid = pr.apply(raw)
finally:
    anchors.registry, anchors.pilot_roots, p.load_registry = saved
check("apply: no read of the registry file (the readers raise): the marked record is laid and the derived keepers are computed from the rows", laid["projects/forge"]["keeper_source"] == "mark" and laid[SAT]["keeper_source"] == "derived"
      and "not laid" not in buf.getvalue() and "no derived keeper" not in buf.getvalue(), (buf.getvalue()[:300], laid["projects/forge"].get("keeper_source"), laid[SAT].get("keeper_source")))
write_record({})

# ---- 8. the project's name prefix of a one-session project (its session need not start with the page's slug)
write_record({})
lone = prj.registry()["projects/lone-page"]
check("name prefix: a one-session page whose session does not start with its slug (lone-session on projects/lone-page) has its session as the project's name", prj._name_prefixes("projects/lone-page", lone, prj.registry()) == ["lone-session"], prj._name_prefixes("projects/lone-page", lone, prj.registry()))
check("… and an agent named for it is that project's agent (role cut from the name)", prj.role_of("lone-session-helper", prj._name_prefixes("projects/lone-page", lone, prj.registry())) == "helper")
sole = {**lone, "agents": {"lone-session": "its one session"}}
check("… listed as its own one front agent (the stage-5 shape), the name line is a session: the project name is the session's name minus its last part, as for any name line naming an agent",
      prj._name_prefixes("projects/lone-page", sole, {"projects/lone-page": sole}) == ["lone"], prj._name_prefixes("projects/lone-page", sole, {"projects/lone-page": sole}))
write_record({prj.ensure_ids(["projects/lone-page"])["projects/lone-page"]: entry("projects/lone-page", name="lone-session", agents={"lone-session": agent(True, "its one session", keeper=True)})})
lr = prj.registry()["projects/lone-page"]
check("… the one-session project made explicit (its session listed as the front agent and marked): the mark names it, the name line is in legacy_session, and its keeper is that session",
      lr["session"] == "lone-session" and lr["role"] == "mark" and lr["legacy_session"] == "lone-session" and lr["keeper_agent"] == "lone-session" and lr["keeper_source"] == "mark" and prj.name_line(lr) == "lone-session", lr)

# ---- 9. nothing here raises on a damaged record
REC.write_text("{not json", encoding="utf-8"); pr._CACHE["sig"] = None
check("a record that cannot be read: the pages answer, and the marks of the pages still apply", prj.registry()["projects/orchard"]["session"] == "team-orchard-docs" and prj.registry()["projects/forge"]["session"] == "team-forge")

if fails: print(f"FAILED: keeper mark scenario, {len(ran)} checks, {len(fails)} failed"); sys.exit(1)
print(f"ok: keeper mark scenario, {len(ran)} checks")
