"""Scenario test for the verbs that write the keeper mark (stage 3 of the keeper as a mark on one agent) — fixture data, no live store, no network, no server process (the page store is the plain
markdown folder of a temporary config).

Covers: `agent_add` marking a project's first agent (and no later one, and never a second mark on a project that has one, a mark held by the page's own `keeper:` line included); `agent_rename` of
the marked agent making the mark follow the new name (also when only the page held it), and of an unmarked agent leaving the mark where it is; `agent_retire` of the marked agent moving the mark to
the builder, else the -main agent, else clearing it with a problem line, and of an unmarked agent leaving it; the `keeper` verb (a dry run by default that writes nothing and names the old mark, the
new mark and the sessions whose roles move; `--apply` writing the record and an undo file that `restore --undo` takes back; the refusals: an agent the record does not list, a retired project, a
sub-page key; an agent that is the keeper already; a record with two flags coming out with one); the CLI in a child process; and the four keeper debts of the registry check (keeper-not-listed,
keeper-two-marks, keeper-retired, keeper-not-derived), each with its test, off by default and on with `[registry_audit] keeper_debts = true`; and that with no mark anywhere the verbs leave every
published field as it was; and the `page_keeper` verb (a sub-page's own mark, set on the entry of the project above it: nine pages at once, pages under different projects, one bad key refusing the
whole call, the same mark again, handing a page back, an unlisted or non-sala agent, a retired project, a project's own page, the undo file, a dry run, the readers, the CLI; the new record read
back against the registry's own answer, stored keys read as the registry reads them, the pre-read of a project with no entry, the call that changes nothing, a project inside another's page, a key that only starts like another's).

    tests/run-suite keeper_verbs        → exit 0 / 1"""
import hashlib, json, logging, os, pathlib, re, shutil, subprocess, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="keeperverbs-"); T = pathlib.Path(tmp)
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
for d in ("store/a", "fleet/a", "state/cache", "brain/projects", "secrets"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"})); (T / "fleet/a/sessions.json").write_text("{}")
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
BRAIN = T / "brain"
def page(rel, front, body="# x\n"):
    q = BRAIN / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n" + body, encoding="utf-8")
def text(rel): return (BRAIN / (rel + ".md")).read_text(encoding="utf-8")

# Neutral fixtures. forge: a split project (agents, a builder, no mark); hollow: a project with no agent yet; ember: a mark held by the page's own `keeper:` line; solo: a one-session project;
# nobuild: a front agent and a background agent that builds nothing; old: a retired project; wide: two front agents and a builder, for the rename and retire rules.
page("projects/forge.md", "type: project\ntitle: Forge\ndisplay-name: team-forge\nagents:\n  team-forge-main: talks\n  team-forge-docs: keeps the docs\n  background:\n    team-forge-audit: reviews\n    team-forge-builder: builds and merges\nstatus: active")
page("projects/forge/sub.md", "type: note\ntitle: Forge sub")
page("projects/hollow.md", "type: project\ntitle: Hollow\ndisplay-name: team-hollow\nstatus: active")
page("projects/ember.md", "type: project\ntitle: Ember\ndisplay-name: team-ember\nkeeper: team-ember-main\nagents:\n  team-ember-main: talks\n  team-ember-docs: keeps the docs\n  background:\n    team-ember-builder: builds\nstatus: active")
page("projects/solo.md", "type: project\ntitle: Solo\ndisplay-name: lone-session\nstatus: active")
page("projects/nobuild.md", "type: project\ntitle: Nobuild\ndisplay-name: team-nobuild\nagents:\n  team-nobuild-main: talks\n  background:\n    team-nobuild-watch: watches the weather\nstatus: active")
page("projects/old.md", "type: project\ntitle: Old\ndisplay-name: team-old\nagents:\n  team-old-main: talks\nstatus: archived")
page("projects/wide.md", "type: project\ntitle: Wide\ndisplay-name: team-wide\nagents:\n  team-wide-front: talks\n  team-wide-main: also talks\n  background:\n    team-wide-builder: builds and merges\nstatus: active")
page("projects/ember2.md", "type: project\ntitle: Ember two\ndisplay-name: team-ember2\nkeeper: team-ember2-main\nagents:\n  team-ember2-main: talks\n  team-ember2-docs: keeps the docs\nstatus: active")
page("projects/loner.md", "type: project\ntitle: Loner\ndisplay-name: lone-two\nstatus: active")
page("projects/loner2.md", "type: project\ntitle: Loner two\ndisplay-name: lone-three\nstatus: active")
page("projects/nameless.md", "type: project\ntitle: Nameless\nstatus: active")
page("projects/old3.md", "type: project\ntitle: Old three\ndisplay-name: team-old3\nstatus: archived")
page("projects/gone.md", "type: project\ntitle: Gone\ndisplay-name: team-gone\nagents:\n  team-gone-main: talks\n  team-gone-docs: docs\nstatus: active")
# sub-pages for the `page_keeper` verb: forge/p1..p9 (p1 and p2 are kept by an `agent:` line, the others name nobody), pages under two more projects, a sub-page that has a name line of its own, one with a `keeper:` line of
# its own, a page that reaches the forge only through a `hub:` line, and a page under a retired project
for i in range(1, 10): page(f"projects/forge/p{i}.md", "type: note\ntitle: Forge page " + str(i) + ("\nagent: team-forge-audit" if i < 3 else ""))
page("projects/forge/sub/deep.md", "type: note\ntitle: Forge deep")
page("projects/forge/named.md", "type: note\ntitle: Forge named\ndisplay-name: team-forge-named")
page("projects/forge/own.md", "type: note\ntitle: Forge own\nkeeper: team-own-x\nagents:\n  team-own-x: talks")
page("projects/hubby.md", "type: note\ntitle: Hubby\nhub: projects/forge")
page("projects/wide/w1.md", "type: note\ntitle: Wide one"); page("projects/wide/w2.md", "type: note\ntitle: Wide two")
page("projects/gone/g1.md", "type: note\ntitle: Gone one")
page("projects/old/o1.md", "type: note\ntitle: Old one")

sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
REC = T / "store/project-record.json"
def recfile(): return json.loads(REC.read_text()) if REC.exists() else {}
def recsha(): return hashlib.sha256(REC.read_bytes()).hexdigest() if REC.exists() else ""
def tool(script, *args):
    r = subprocess.run([sys.executable, f"{STACK}/{script}"] + list(args), capture_output=True, text=True, env=os.environ, cwd=str(T))
    return r.returncode, r.stdout, r.stderr

from stackshot.projects import pages as p; from stackshot.projects import projects as prj; from stackshot.projects import project_registry as pr; from stackshot.projects import project_verbs as pv
from stackshot.projects import keeper as kp; from stackshot.router import page_debt; from stackshot.anchors import anchors; from stackshot.tools import registry_report as rr
from stackshot.core import config as cfg
p.cmd_registry(quiet=True)
IO = page_debt.PlainIO()
def R(): return prj.registry()
def reg(): return json.loads((T / "store/projects.json").read_text())["pages"]
ids = {k: e["id"] for k, e in reg().items()}
LONER, LONER2, OLD3 = (ids[f"projects/{k}"] for k in ("loner", "loner2", "old3"))
FORGE, HOLLOW, EMBER, SOLO, NOBUILD, OLD, WIDE, GONE, EMBER2 = (ids[f"projects/{k}"] for k in ("forge", "hollow", "ember", "solo", "nobuild", "old", "wide", "gone", "ember2"))
def ents(): return pr.entries()
def flags(pid): return [n for n, a in ((ents().get(pid) or {}).get("agents") or {}).items() if a.get("keeper") is True]
def refresh(): p.cmd_registry(quiet=True)
def fields_of(key): refresh(); r = R()[key]; return r["keeper_agent"], r["keeper_source"]
def mirror_lines(rel): return [x for x in text(rel).split("\n") if x.startswith("keeper")]

# ---- 0. with no mark anywhere, nothing the verbs have not touched changes: every project answers as before
A0 = {k: fields_of(k) for k in ("projects/forge", "projects/hollow", "projects/solo", "projects/nobuild", "projects/old", "projects/wide", "projects/gone")}
check("no mark: the derived keepers are the builder, the -main agent or the one-session name, and a retired project has none",
      A0["projects/forge"] == ("team-forge-builder", "derived") and A0["projects/nobuild"] == ("team-nobuild-main", "derived") and A0["projects/solo"] == ("lone-session", "legacy") and A0["projects/old"] == ("", "")
      and A0["projects/wide"] == ("team-wide-builder", "derived") and fields_of("projects/ember") == ("team-ember-main", "mark"), A0)
check("no mark: no record exists and a dry run of `keeper` writes nothing", not REC.exists() or "projects" not in recfile() or not recfile().get("projects"))

# ---- 1. agent_add marks the first agent
r = pv.agent_add("projects/hollow", "team-hollow-main", True, "talks to the user", io=IO, by="lone-session")
check("agent_add: the first agent of a project with none is marked (the flag on its entry, the answer says so)", flags(HOLLOW) == ["team-hollow-main"] and r.get("keeper_marked") == "team-hollow-main" and ents()[HOLLOW]["agents"]["team-hollow-main"]["keeper"] is True, (r, ents()[HOLLOW]))
check("... the registry reads it as the mark and the page mirror carries no keeper line (the mirror writes three lines only)", fields_of("projects/hollow") == ("team-hollow-main", "mark") and mirror_lines("projects/hollow") == [] and "team-hollow-main" in text("projects/hollow"), (fields_of("projects/hollow"), text("projects/hollow")))
r = pv.agent_add("projects/hollow", "team-hollow-docs", True, "keeps the docs", io=IO, by="lone-session")
r2 = pv.agent_add("projects/hollow", "team-hollow-builder", False, "builds and merges", io=IO, by="lone-session")
check("agent_add: a later agent, front or background, is not marked and the first stays the mark", flags(HOLLOW) == ["team-hollow-main"] and "keeper_marked" not in r and "keeper_marked" not in r2, (flags(HOLLOW), r, r2))
r = pv.agent_add("projects/hollow", "team-hollow-main", True, "talks to the user", io=IO, by="lone-session")
check("agent_add: the same agent again changes nothing and marks nothing more", r["changed"] is False and flags(HOLLOW) == ["team-hollow-main"], r)
r = pv.agent_add("projects/forge", "team-forge-extra", True, "one more", io=IO, by="lone-session")
check("agent_add: a project that lists agents and has no mark does not get one on a later agent (no mark appears from adding)", flags(FORGE) == [] and "keeper_marked" not in r and fields_of("projects/forge") == ("team-forge-builder", "derived"), (flags(FORGE), r))
r = pv.agent_add("projects/ember", "team-ember-extra", False, "extra", io=IO, by="lone-session")
check("agent_add: a project whose page holds the mark never gets a second one", flags(EMBER) == [] and fields_of("projects/ember") == ("team-ember-main", "mark") and "keeper_marked" not in r, (flags(EMBER), r))
r = pv.agent_add("projects/solo", "lone-session", True, "the one session", io=IO, by="lone-session")
check("agent_add: the one session of a one-session project listed as its first agent is marked", flags(SOLO) == ["lone-session"] and fields_of("projects/solo") == ("lone-session", "mark"), (flags(SOLO), r))
r = pv.agent_add("projects/hollow", "team-hollow-other", True, "dry", io=IO, dry=True)
check("agent_add, dry run: a first agent would be marked in the answer and nothing is written", r["dry"] is True and "team-hollow-other" not in (ents()[HOLLOW]["agents"]), r)

# ---- 2. agent_rename: the mark follows the new name
r = pv.agent_rename("projects/hollow", "team-hollow-main", "team-hollow-lead", io=IO, by="lone-session")
check("agent_rename of the marked agent: the flag is on the new name, on no other, and the answer says where it went", flags(HOLLOW) == ["team-hollow-lead"] and r["keeper"] == {"from": "team-hollow-main", "to": "team-hollow-lead"}, (flags(HOLLOW), r.get("keeper")))
check("... the registry's keeper is the new name, source mark", fields_of("projects/hollow") == ("team-hollow-lead", "mark"), (fields_of("projects/hollow"), ents()[HOLLOW]))
r = pv.agent_rename("projects/hollow", "team-hollow-docs", "team-hollow-notes", io=IO, by="lone-session")
check("agent_rename of an agent that is not marked: the mark stays where it was and the answer names no keeper move", flags(HOLLOW) == ["team-hollow-lead"] and "keeper" not in r, (flags(HOLLOW), r))
r = pv.agent_rename("projects/ember", "team-ember-main", "team-ember-lead", io=IO, by="lone-session")
check("agent_rename of the agent only the page marks: the record gets the flag on the new name (the record wins; the page's own line still names the old name and is for whoever edits the page to change)",
      flags(EMBER) == ["team-ember-lead"] and r["keeper"]["to"] == "team-ember-lead" and fields_of("projects/ember") == ("team-ember-lead", "mark"), (flags(EMBER), r.get("keeper"), fields_of("projects/ember")))
r = pv.agent_rename("projects/forge", "team-forge-audit", "team-forge-review", io=IO, by="lone-session")
check("agent_rename in a project with no mark: no mark appears", flags(FORGE) == [] and "keeper" not in r, (flags(FORGE), r))

# ---- 3. agent_retire: the mark moves to the builder, else the -main agent, else clears
for ag in ("team-wide-front", "team-wide-main"):         # a record entry first (the first verb on the project makes it), then a mark on a front agent
    pass
pv.keeper("projects/wide", "team-wide-front", apply=True, io=IO, by="lone-session", run_dir=T / "undo-wide")
check("setup: the wide project's mark is on its first front agent", flags(WIDE) == ["team-wide-front"], flags(WIDE))
r = pv.agent_retire("projects/wide", "team-wide-main", io=IO, by="lone-session")
check("agent_retire of an agent that is not the marked one: the mark stays", flags(WIDE) == ["team-wide-front"] and "keeper" not in r, (flags(WIDE), r))
pv.agent_add("projects/wide", "team-wide-main", True, "also talks", io=IO, by="lone-session")
r = pv.agent_retire("projects/wide", "team-wide-front", io=IO, by="lone-session")
check("agent_retire of the marked agent: the mark goes to the project's builder (before its -main agent)", flags(WIDE) == ["team-wide-builder"] and r["keeper"] == {"from": "team-wide-front", "to": "team-wide-builder"} and "warning" not in r, (flags(WIDE), r.get("keeper"), r.get("warning")))
check("... never left naming the retired agent: the registry's keeper is the builder, source mark, and no problem line", fields_of("projects/wide") == ("team-wide-builder", "mark") and "keeper_problems" not in R()["projects/wide"], R()["projects/wide"])
pv.keeper("projects/gone", "team-gone-docs", apply=True, io=IO, by="lone-session", run_dir=T / "undo-gone")
r = pv.agent_retire("projects/gone", "team-gone-docs", io=IO, by="lone-session")
check("agent_retire of the marked agent in a project with no builder: the mark goes to its -main agent", flags(GONE) == ["team-gone-main"] and r["keeper"]["to"] == "team-gone-main", (flags(GONE), r.get("keeper")))
pv.keeper("projects/nobuild", "team-nobuild-watch", apply=True, io=IO, by="lone-session", run_dir=T / "undo-nobuild")
r = pv.agent_retire("projects/nobuild", "team-nobuild-main", io=IO, by="lone-session")
check("agent_retire of an unmarked agent: the mark stays (the background agent that watches is the mark)", flags(NOBUILD) == ["team-nobuild-watch"] and "keeper" not in r, (flags(NOBUILD), r))
pv.keeper("projects/nobuild", "team-nobuild-watch", apply=True, io=IO, by="lone-session", run_dir=T / "undo-nobuild")
pv.agent_add("projects/nobuild", "team-nobuild-main", True, "talks", io=IO, by="lone-session")
pv.keeper("projects/nobuild", "team-nobuild-main", apply=True, io=IO, by="lone-session", run_dir=T / "undo-nobuild")
r = pv.agent_retire("projects/nobuild", "team-nobuild-main", io=IO, by="lone-session")
check("agent_retire of the marked agent with no builder and no front agent left: the mark is cleared and a problem line says so (the answer's warning and its keeper)",
      flags(NOBUILD) == [] and r["keeper"]["to"] == "" and "no agent is left to take the mark" in r["keeper"]["problem"] and "no agent is left" in r["warning"], (flags(NOBUILD), r.get("keeper"), r.get("warning")))
check("... the record then names no retired agent: no flag on the map and the retired agent is no agent of the project", all("keeper" not in a for a in ents()[NOBUILD]["agents"].values()) and "team-nobuild-main" not in ents()[NOBUILD]["agents"], ents()[NOBUILD])
r = pv.agent_retire("projects/hollow", "team-hollow-lead", io=IO, by="lone-session", dry=True)
check("agent_retire, dry run: the answer says where the mark would go and the record is untouched", flags(HOLLOW) == ["team-hollow-lead"] and r["keeper"]["to"] == "team-hollow-builder" and r["dry"] is True, (flags(HOLLOW), r.get("keeper")))
r = pv.agent_retire("projects/hollow", "team-hollow-lead", io=IO, by="lone-session")
check("agent_retire: with a background builder and a notes agent left the mark goes to the builder", flags(HOLLOW) == ["team-hollow-builder"], (flags(HOLLOW), r.get("keeper")))
r = pv.agent_retire("projects/hollow", "team-hollow-nobody", io=IO, by="lone-session")
check("agent_retire of a name that is not listed changes nothing and moves no mark", r["result"] == "not listed" and flags(HOLLOW) == ["team-hollow-builder"], r)

# ---- 3b. the answer names the session that stops being the keeper, and what it loses
r = pv.agent_add("projects/loner", "lone-two-main", True, "talks to the user", io=IO, by="lone-session", dry=True)
W = r.get("warning", "")
check("agent_add, dry run, first agent of a project whose name-line session is its keeper: the answer names the session that stops being the keeper and what it loses (roles.json entry, notices, the 403)",
      r["dry"] is True and flags(LONER) == [] and "lone-two stops being the keeper of projects/loner" in W and "its roles.json entry goes from" in W and "notices for the project are addressed to lone-two-main" in W
      and "refused (403, the agent marked keeper: lone-two-main)" in W and "project.py keeper projects/loner lone-two" in W, (r.get("warning"), r.get("lines")))
r = pv.agent_add("projects/loner", "lone-two-main", True, "talks to the user", io=IO, by="lone-session")
W = r.get("warning", "")
check("agent_add, applied: the same words, and the `lines` print the roles.json entries that move as the keeper verb prints them (the demoted session's entry goes, the new keeper's comes)",
      flags(LONER) == ["lone-two-main"] and "lone-two stops being the keeper of projects/loner" in W and r["lines"][0] == f"keeper of {LONER}: lone-two (the name line) -> lone-two-main (the mark)"
      and any(x.startswith("roles.json: lone-two: ") and x.endswith(" -> None") for x in r["lines"]) and any(x.startswith("roles.json: lone-two-main: None -> ") and "'keeper': True" in x for x in r["lines"]), (W, r["lines"]))
r = pv.agent_add("projects/loner2", "lone-three-builder", False, "builds and merges", io=IO, by="lone-session")
check("agent_add, a first agent that is a background agent: the same words (the builder is the keeper and the talking session loses the standing)", flags(LONER2) == ["lone-three-builder"] and "lone-three stops being the keeper of projects/loner2" in r.get("warning", ""), r.get("warning"))
r = pv.agent_add("projects/loner", "lone-two-docs", True, "keeps the docs", io=IO, by="lone-session")
check("agent_add, a later agent: no keeper words in the answer", "warning" not in r and "lines" not in r and "keeper_marked" not in r, r)
r = pv.agent_add("projects/solo", "lone-session", True, "the one session", io=IO, by="lone-session")
check("agent_add, the first agent is the name-line session itself (already listed, nothing changes): no demotion words", "stops being the keeper" not in r.get("warning", ""), r.get("warning"))
r = pv.agent_retire("projects/loner", "lone-two-main", io=IO, by="lone-session")
check("agent_retire of the marked agent: the answer says where the mark goes and prints the roles.json entries that move",
      r["keeper"]["to"] in ("lone-two-docs",) and r["lines"][0].startswith(f"keeper of {LONER}: lone-two-main (the mark) -> lone-two-docs (the mark)") and any(x.startswith("roles.json: ") for x in r["lines"][1:]), (r.get("keeper"), r.get("lines")))
r = pv.agent_retire("projects/loner2", "lone-three-builder", io=IO, by="lone-session")
check("agent_retire of the only marked agent of a project with a name line: the warning says the name line is its keeper again (not that the project has none)",
      r["keeper"]["to"] == "" and "lone-three is its keeper again" in r["keeper"]["problem"] and "the project has no keeper agent" not in r["keeper"]["problem"] and "lone-three is its keeper again" in r["warning"]
      and r["lines"][0] == f"keeper of {LONER2}: lone-three-builder (the mark) -> lone-three (the name line)", (r.get("keeper"), r.get("lines"), r.get("warning")))
pv.agent_add("projects/nameless", "team-nameless-main", True, "talks", io=IO, by="lone-session")
r = pv.agent_retire("projects/nameless", "team-nameless-main", io=IO, by="lone-session")
check("... and a project with no name line says it has no keeper agent, as before", r["keeper"]["to"] == "" and "the project has no keeper agent until one is listed and marked" in r["keeper"]["problem"] and "is its keeper again" not in r["keeper"]["problem"], r.get("keeper"))

# a retired project: the verbs change the agent list and leave the mark alone, with the `keeper` verb's line
RETIRED_LINE = "is a retired project: its keeper is not moved (reopen it first)"
r = pv.agent_add("projects/old3", "team-old3-main", True, "talks", io=IO, by="lone-session")
check("agent_add on a retired project's first agent: listed, not marked, and the answer carries the keeper verb's refusal line", flags(OLD3) == [] and "team-old3-main" in ents()[OLD3]["agents"] and RETIRED_LINE in r.get("warning", "") and "keeper_marked" not in r, (flags(OLD3), r.get("warning")))
pv.agent_add("projects/old", "team-old-docs", True, "keeps the docs", io=IO, by="lone-session")
d = recfile(); d["projects"][OLD]["agents"]["team-old-main"]["keeper"] = True; REC.write_text(json.dumps(d), encoding="utf-8"); pr._CACHE["sig"] = None
r = pv.agent_rename("projects/old", "team-old-main", "team-old-lead", io=IO, by="lone-session")
check("agent_rename of the marked agent of a retired project: renamed, no mark move reported, the answer carries the refusal line", "team-old-lead" in ents()[OLD]["agents"] and "keeper" not in r and RETIRED_LINE in r.get("warning", ""), (r.get("keeper"), r.get("warning")))
r = pv.agent_retire("projects/old", "team-old-lead", io=IO, by="lone-session")
check("agent_retire of the marked agent of a retired project: the agent leaves, no successor is marked, the answer carries the refusal line",
      "team-old-lead" not in ents()[OLD]["agents"] and flags(OLD) == [] and "keeper" not in r and "lines" not in r and RETIRED_LINE in r.get("warning", ""), (flags(OLD), r.get("keeper"), r.get("warning")))
r = pv.agent_retire("projects/old", "team-old-docs", io=IO, by="lone-session")
check("agent_retire of an agent that is not the marked one in a retired project: no refusal line", RETIRED_LINE not in r.get("warning", ""), r.get("warning"))

# ---- 4. the keeper verb
before = recsha()
r = pv.keeper("projects/forge", "team-forge-main", io=IO, by="lone-session")
check("keeper: a dry run by default writes nothing (the record file is the same bytes, no undo file)", recsha() == before and r["dry"] is True and r["undo"] is None and flags(FORGE) == [], (r, flags(FORGE)))
check("... it names the old keeper (derived: the builder), the new mark and the sessions whose roles move",
      r["old"] == "" and r["new"] == "team-forge-main" and any(m["session"] == "team-forge-main" and m["to"] and m["to"].get("keeper") is True for m in r["roles"]) and any("team-forge-builder" in x or "team-forge-main" in x for x in r["lines"])
      and r["lines"][0].startswith("dry run:") and "nothing written (add --apply)" in r["lines"][-1], (r["old"], r["new"], r["roles"], r["lines"]))
undo_dir = T / "undo-forge"
r = pv.keeper("projects/forge", "team-forge-main", apply=True, io=IO, by="lone-session", run_dir=undo_dir)
check("keeper --apply: the flag is on the one agent and on no other, the answer names the undo file and it exists", flags(FORGE) == ["team-forge-main"] and r["changed"] is True and r["undo"] and pathlib.Path(r["undo"]).is_file(), (flags(FORGE), r.get("undo")))
check("... the registry reads it as the mark; roles.json (file_roles) carries it", fields_of("projects/forge") == ("team-forge-main", "mark") and anchors.file_roles(R(), set())["team-forge-main"].get("keeper") is True, fields_of("projects/forge"))
sha_after = recsha()
u = pv.restore_undo(r["undo"], apply=False)
check("... `restore --undo` is a dry run by default and says what it would do", u["dry"] is True and u["changed"] is True and recsha() == sha_after, u)
u = pv.restore_undo(r["undo"], apply=True)
check("... `restore --undo --apply` takes the change back: the record has no flag on the forge again", u["changed"] is True and flags(FORGE) == [] and fields_of("projects/forge") == ("team-forge-builder", "derived"), (u, flags(FORGE)))
r = pv.keeper("projects/forge", "team-forge-docs", apply=True, io=IO, by="lone-session", run_dir=undo_dir)
r = pv.keeper("projects/forge", "team-forge-builder", apply=True, io=IO, by="lone-session", run_dir=undo_dir)
check("keeper: it moves the mark (never adds one): after two moves one agent carries the flag", flags(FORGE) == ["team-forge-builder"] and r["old"] == "team-forge-docs" and r["new"] == "team-forge-builder", (flags(FORGE), r["old"], r["new"]))
r = pv.keeper("projects/forge", "team-forge-builder", io=IO, by="lone-session")
check("keeper: an agent that is the mark already: nothing to change, no roles move", r["same"] is True and r["changed"] is False and r["roles"] == [], r)
r = pv.keeper("projects/forge", "TEAM-FORGE-MAIN", io=IO, by="lone-session")
check("keeper: the agent name is matched without case", r["new"] == "team-forge-main", r)
for what, call, status in (("an agent the record does not list", lambda: pv.keeper("projects/forge", "team-forge-nobody", apply=True, io=IO, run_dir=undo_dir), 404),
                           ("a retired project", lambda: pv.keeper("projects/old", "team-old-main", apply=True, io=IO, run_dir=undo_dir), 409),
                           ("a sub-page's key", lambda: pv.keeper("projects/forge/sub", "team-forge-main", apply=True, io=IO, run_dir=undo_dir), 400),
                           ("a project nobody knows", lambda: pv.keeper("projects/nowhere", "team-forge-main", apply=True, io=IO, run_dir=undo_dir), 404)):
    sha0 = recsha()
    try:
        call(); got = None
    except pv.VerbError as e:
        got = e.status
    check(f"keeper: {what} is refused ({status}) and nothing is written", got == status and recsha() == sha0, (got, status))
d = recfile(); ag = d["projects"][FORGE]["agents"]; ag["team-forge-main"]["keeper"] = True; REC.write_text(json.dumps(d), encoding="utf-8"); pr._CACHE["sig"] = None
check("setup: a record with two flags reads one mark and a problem line", len(flags(FORGE)) == 2 and fields_of("projects/forge")[1] == "mark" and len(R()["projects/forge"]["keeper_problems"]) == 1, (flags(FORGE), R()["projects/forge"].get("keeper_problems")))
r = pv.keeper("projects/forge", "team-forge-docs", apply=True, io=IO, by="lone-session", run_dir=undo_dir)
check("keeper: a record with two flags comes out with exactly one, on the agent asked for", flags(FORGE) == ["team-forge-docs"] and "keeper_problems" not in (refresh() or R()["projects/forge"]), (flags(FORGE), R()["projects/forge"].get("keeper_problems")))
d = recfile(); ag = d["projects"][FORGE]["agents"]
for n in ag: ag[n].pop("keeper", None)
ag["team-forge-main"]["keeper"] = True; ag["team-forge-docs"]["keeper"] = True; REC.write_text(json.dumps(d), encoding="utf-8"); pr._CACHE["sig"] = None
r = pv.keeper("projects/forge", "team-forge-main", io=IO, by="lone-session")
check("keeper, a record with two flags, asked for the agent that is the effective mark: the answer says it repairs two marks to one (kept X, cleared Y), not `X -> X`",
      r["lines"][0] == f"dry run: keeper of {FORGE}: repaired 2 marks to one (kept team-forge-main, cleared team-forge-docs)" and "-> team-forge-main (the mark)" not in r["lines"][0], r["lines"])
r = pv.keeper("projects/forge", "team-forge-main", apply=True, io=IO, by="lone-session", run_dir=undo_dir)
check("... applied: one flag is left, on the agent kept, and the line says so", flags(FORGE) == ["team-forge-main"] and r["lines"][0] == f"keeper of {FORGE}: repaired 2 marks to one (kept team-forge-main, cleared team-forge-docs)" and r["changed"] is True, (flags(FORGE), r["lines"]))
# a malformed flag on ANOTHER agent (not true, not false) is no mark to the reader, and the verb still repairs it: asked for the agent that is the mark already, it must not answer `already the keeper`
d = recfile(); ag = d["projects"][FORGE]["agents"]
for n in ag: ag[n].pop("keeper", None)
ag["team-forge-main"]["keeper"] = True; ag["team-forge-docs"]["keeper"] = "yes"; REC.write_text(json.dumps(d), encoding="utf-8"); pr._CACHE["sig"] = None
r = pv.keeper("projects/forge", "team-forge-main", io=IO, by="lone-session")
check("keeper, a malformed flag on another agent, asked for the agent that is the mark: not `already the keeper`; a dry run says it repairs the flag (kept X, cleared Y) and writes nothing",
      r["same"] is False and r["lines"][0] == f"dry run: keeper of {FORGE}: repaired 2 marks to one (kept team-forge-main, cleared team-forge-docs)" and recfile()["projects"][FORGE]["agents"]["team-forge-docs"]["keeper"] == "yes", r["lines"])
r = pv.keeper("projects/forge", "team-forge-main", apply=True, io=IO, by="lone-session", run_dir=undo_dir)
check("... applied: the malformed flag is gone, one flag is left on the mark, and the registry reads no problem line any more",
      flags(FORGE) == ["team-forge-main"] and "keeper" not in recfile()["projects"][FORGE]["agents"]["team-forge-docs"] and r["changed"] is True and "keeper_problems" not in (refresh() or R()["projects/forge"]), (flags(FORGE), r["lines"]))
r = pv.keeper("projects/forge", "team-forge-main", apply=True, io=IO, by="lone-session", run_dir=undo_dir)
check("... and a second ask is the plain `already the keeper`, nothing written", r["same"] is True and r["changed"] is False and r["lines"] == [f"team-forge-main is the keeper of {FORGE} already; nothing to change"], r["lines"])
r = pv.keeper("projects/ember2", "team-ember2-docs", apply=True, io=IO, by="lone-session", run_dir=undo_dir)
check("keeper: a project whose page names another agent in its own `keeper:` line gets the record's flag and a warning that the page line is for whoever edits the page to change (the record wins)",
      flags(EMBER2) == ["team-ember2-docs"] and "keeper:" in r.get("warning", "") and fields_of("projects/ember2") == ("team-ember2-docs", "mark") and r["old"] == "team-ember2-main", (flags(EMBER2), r.get("warning"), r["old"], fields_of("projects/ember2")))
check("keeper: the page's mirror lines are not changed by a keeper move (the page keeps its own `keeper:` line and writes none)", "keeper: team-ember2-main" in text("projects/ember2") and "keeper: true" not in text("projects/ember2"), text("projects/ember2"))
# the keeper verb writes the record only: a page whose mirrored lines drifted from the record (a mandate edited by hand) is left byte for byte as it is, and no timeline line is added to it
FP = BRAIN / "projects/forge.md"; fp_orig = FP.read_bytes()
FP.write_text(FP.read_text(encoding="utf-8").replace("keeps the docs", "keeps the docs and the notes", 1), encoding="utf-8"); fp_drift = FP.read_bytes()
r = pv.keeper("projects/forge", "team-forge-builder", apply=True, io=IO, by="lone-session", run_dir=undo_dir)
check("keeper --apply writes the record only: the drifted mirrored line on the page is not rewritten, no timeline line is added, and the answer's mirror says skipped",
      r["changed"] is True and flags(FORGE) == ["team-forge-builder"] and FP.read_bytes() == fp_drift and r["mirror"]["state"] == "skipped" and "record only" in r["mirror"]["note"], (r["mirror"], FP.read_text(encoding="utf-8")))
r = pv.keeper("projects/forge", "team-forge-main", io=IO, by="lone-session")
check("keeper, a dry run: the page is not touched and the mirror says skipped too", FP.read_bytes() == fp_drift and r["dry"] is True and r["mirror"]["state"] == "skipped", r["mirror"])
rc, out, err = tool("stackshot/tools/project.py", "keeper", "projects/forge", "team-forge-docs", "--apply", "--run-dir", str(T / "undo-drift"))
check("cli keeper --apply: the same, in a child process (the page's bytes are the drifted ones, the record has the mark)", rc == 0 and FP.read_bytes() == fp_drift and flags(FORGE) == ["team-forge-docs"], (rc, out, err))
FP.write_bytes(fp_orig); pv.keeper("projects/forge", "team-forge-main", apply=True, io=IO, by="lone-session", run_dir=undo_dir)      # back to the mark the sections below read
dbt =rr.keeper_debts(ents(), reg(), R())
check("debts: that page line and the record's flag name different agents, which the check names as keeper-two-marks", [f["line"] for f in dbt if f["page"] == "projects/ember2"] == ["keeper-two-marks"], dbt)

# ---- 5. the CLI
sha0 = recsha()
rc, out, err = tool("stackshot/tools/project.py", "keeper", "projects/wide", "team-wide-main")
check("cli keeper: a dry run (no --apply): exit 0, says dry run, writes nothing", rc == 0 and "dry run" in out and recsha() == sha0, (rc, out, err))
rc, out, err = tool("stackshot/tools/project.py", "--dry-run", "keeper", "projects/wide", "team-wide-main", "--apply")
check("cli keeper: --apply with --dry-run contradict (exit 2)", rc == 2 and "contradict" in err and recsha() == sha0, (rc, err))
rc, out, err = tool("stackshot/tools/project.py", "keeper", "projects/wide", "team-wide-nobody", "--apply")
check("cli keeper: an agent the record does not list: exit 1, the 404 on stderr, nothing written", rc == 1 and "[404]" in err and recsha() == sha0, (rc, err))
rc, out, err = tool("stackshot/tools/project.py", "keeper", "projects/wide", "team-wide-main", "--apply", "--run-dir", str(T / "undo-cli"))
check("cli keeper --apply: exit 0, the record carries the flag, the undo command is printed", rc == 0 and flags(WIDE) == ["team-wide-main"] and "restore --undo" in out, (rc, out, err, flags(WIDE)))
undo_file = re.search(r"--undo (\S+)", out).group(1)
rc, out, err = tool("stackshot/tools/project.py", "restore", "--undo", undo_file, "--apply")
check("cli: the printed undo command takes it back", rc == 0 and flags(WIDE) == ["team-wide-builder"], (rc, out, err, flags(WIDE)))

# ---- 5b. page_keeper: a sub-page's own mark
PK = [f"projects/forge/p{i}" for i in range(1, 10)]
def pmarks(pid): return dict((ents().get(pid) or {}).get("page_keepers") or {})
def brain_tree(): return {str(q): hashlib.sha256(q.read_bytes()).hexdigest() for q in sorted(BRAIN.rglob("*")) if q.is_file()}
def status_of(call):
    try: call(); return None, ""
    except pv.VerbError as e: return e.status, e.message
pv.agent_add("projects/hollow", "team-hollow-slack", True, "answers the chat app", surface="slack", io=IO, by="lone-session")     # an agent that is listed and is no sala session
pv.keeper("projects/forge", "team-forge-builder", apply=True, io=IO, by="lone-session", run_dir=T / "undo-pk-setup")
check("page_keeper setup: before any mark the forge's pages answer as their own lines say (p1 by its `agent:` line, the rest by the project's keeper) and the forge has no page marks",
      fields_of("projects/forge/p1") == ("team-forge-audit", "legacy") and fields_of("projects/forge/p5") == ("team-forge-builder", "mark") and pmarks(FORGE) == {}, (fields_of("projects/forge/p1"), fields_of("projects/forge/p5"), pmarks(FORGE)))
sha0, tree0 = recsha(), brain_tree(); pkdir = T / "undo-pk-dry"
r = pv.page_keeper(PK, "team-forge-docs", io=IO, by="lone-session", run_dir=pkdir)
check("page_keeper: a dry run (the default) writes nothing: the record is the same bytes, no undo file or folder, no page is touched", recsha() == sha0 and brain_tree() == tree0 and r["dry"] is True and r["undo"] is None and not pkdir.exists() and pmarks(FORGE) == {}, (r, pmarks(FORGE)))
check("... it names, for each of the nine pages, the keeper before and after, and says `dry run` and `nothing written (add --apply)`",
      len(r["pages"]) == 9 and all(x["new"] == "team-forge-docs" and x["new_source"] == "mark" and x["same"] is False for x in r["pages"]) and r["pages"][0]["old"] == "team-forge-audit" and r["pages"][0]["old_source"] == "legacy"
      and r["pages"][4]["old"] == "team-forge-builder" and r["lines"][0] == f"dry run: keeper of {PK[0]}: team-forge-audit (the name line) -> team-forge-docs (the mark)" and r["lines"][-1] == "nothing written (add --apply)" and r["same"] is False, (r["lines"], r["pages"][:2]))
r = pv.page_keeper(PK, "team-forge-docs", apply=True, io=IO, by="lone-session", run_dir=T / "undo-pk")
check("page_keeper --apply: nine pages marked in one write, on the one entry that holds them; the answer names the undo file and it exists",
      r["changed"] is True and r["dry"] is False and pmarks(FORGE) == {k: "team-forge-docs" for k in PK} and r["undo"] and pathlib.Path(r["undo"]).is_file() and [x["project"] for x in r["projects"]] == [FORGE], (r.get("undo"), pmarks(FORGE)))
check("... the record only: no page is written (the bytes of every page are the same) and the mirror answers skipped", brain_tree() == tree0 and r["mirror"]["state"] == "skipped" and "record only" in r["mirror"]["note"], r["mirror"])
check("... a reader answers the new mark for each page (keeper.fields, the registry row and keeper.names_of): the agent, source mark, page_mark true",
      all(fields_of(k) == ("team-forge-docs", "mark") and kp.fields(k, R()) == {"keeper_agent": "team-forge-docs", "keeper_source": "mark"} and "team-forge-docs" in kp.names_of(R()[k]) and R()[k]["page_mark"] is True for k in PK), [fields_of(k) for k in PK])
check("... and the pages the call did not name are as they were (the project's own mark, a page that is not marked)", fields_of("projects/forge") == ("team-forge-builder", "mark") and fields_of("projects/forge/sub") == ("team-forge-builder", "mark") and "page_mark" not in R()["projects/forge/sub"], (fields_of("projects/forge"), fields_of("projects/forge/sub")))
sha_applied = recsha()
u = pv.restore_undo(r["undo"], apply=True)
check("... `restore --undo --apply` takes it back: the record is the same bytes as before the call, and the pages answer as they did", u["changed"] is True and recsha() == sha0 and pmarks(FORGE) == {} and fields_of(PK[0]) == ("team-forge-audit", "legacy") and fields_of(PK[4]) == ("team-forge-builder", "mark"), (u, pmarks(FORGE)))
r = pv.page_keeper(PK, "TEAM-FORGE-DOCS", apply=True, io=IO, by="lone-session", run_dir=T / "undo-pk")
check("page_keeper: the agent name is matched without case and written as it is listed", pmarks(FORGE) == {k: "team-forge-docs" for k in PK} and r["name"] == "team-forge-docs" and recsha() == sha_applied, (pmarks(FORGE), r["name"]))

# the same mark again changes nothing; a call that is part change, part the same
sha1 = recsha(); nodir = T / "undo-pk-same"
r = pv.page_keeper([PK[0], PK[1]], "team-forge-docs", apply=True, io=IO, by="lone-session", run_dir=nodir)
check("page_keeper: pages that have the mark already change nothing: no write (same bytes), no undo file, every page says same, and the lines say so",
      r["changed"] is False and r["same"] is True and r["undo"] is None and recsha() == sha1 and not nodir.exists() and all(x["same"] for x in r["pages"])
      and r["lines"] == [f"{PK[0]}: team-forge-docs is its keeper mark already; nothing to change", f"{PK[1]}: team-forge-docs is its keeper mark already; nothing to change"], (r["lines"], r["changed"]))
r = pv.page_keeper([PK[0], "projects/forge/sub/deep"], "team-forge-docs", apply=True, io=IO, by="lone-session", run_dir=T / "undo-pk-part")
check("... a call with one page that has the mark and one that has not: the one is `same`, the other is marked, and only the other moves",
      r["changed"] is True and [x["same"] for x in r["pages"]] == [True, False] and pmarks(FORGE)["projects/forge/sub/deep"] == "team-forge-docs" and fields_of("projects/forge/sub/deep") == ("team-forge-docs", "mark"), (r["pages"], pmarks(FORGE)))
pv.page_keeper(["projects/forge/sub/deep"], "", apply=True, io=IO, by="lone-session", run_dir=T / "undo-pk-part")

# pages under different projects: each mark is held on the entry of its own project, and the change is one write
mixed = [PK[0], "projects/wide/w1", "projects/gone/g1", "projects/wide/w2"]
sha2 = recsha()
r = pv.page_keeper(mixed, "team-forge-main", apply=True, io=IO, by="lone-session", run_dir=T / "undo-pk-mixed")
check("page_keeper, pages under different projects: each mark is on the entry of the project above its page, all in one write",
      pmarks(WIDE) == {"projects/wide/w1": "team-forge-main", "projects/wide/w2": "team-forge-main"} and pmarks(GONE) == {"projects/gone/g1": "team-forge-main"} and pmarks(FORGE)[PK[0]] == "team-forge-main"
      and sorted(x["project"] for x in r["projects"]) == sorted([FORGE, WIDE, GONE]) and [x["project"] for x in r["pages"]] == [FORGE, WIDE, GONE, WIDE], (pmarks(WIDE), pmarks(GONE), r["projects"]))
check("... an agent of another project keeps the page (a cross-project keeper) and every page reads it as its mark", all(fields_of(k) == ("team-forge-main", "mark") for k in (PK[0], "projects/wide/w1", "projects/gone/g1")), [fields_of(k) for k in mixed])
umeta = json.loads(pathlib.Path(r["undo"]).read_text(encoding="utf-8"))
check("... the undo file of a call that moves several entries is a whole-record one (mode record, no single project)", (umeta.get("mode"), umeta.get("project")) == ("record", ""), umeta.get("mode"))
u = pv.restore_undo(r["undo"], apply=True)
check("... one undo file takes the three entries back whole: the record is the same bytes as before the call", u["changed"] is True and recsha() == sha2 and pmarks(WIDE) == {} and pmarks(GONE) == {} and pmarks(FORGE)[PK[1]] == "team-forge-docs", (u, pmarks(WIDE)))

# one bad key refuses the whole call and nothing is written (the good keys before and after it too)
for n, (what, keys, agent_, status, word) in enumerate((
        ("a key that is no page", [PK[2], "projects/forge/nowhere", PK[3]], "team-forge-main", 404, "projects/forge/nowhere"),
        ("a project nobody knows", [PK[2], "projects/nowhere/x"], "team-forge-main", 404, "projects/nowhere/x"),
        ("a project's own page (top level), which names `keeper`", [PK[2], "projects/wide"], "team-forge-main", 400, "`keeper`"),
        ("a page with a name line of its own", [PK[2], "projects/forge/named"], "team-forge-main", 400, "projects/forge/named has a project name line (`display-name:`) of its own"),
        ("a page with a `keeper:` line of its own", [PK[2], "projects/forge/own"], "team-forge-main", 400, "projects/forge/own has a `keeper:` line of its own, which rules; edit the page"),
        ("a page that reaches the forge only through a `hub:` line", [PK[2], "projects/hubby"], "team-forge-main", 400, "hub:"),
        ("a page of a retired project", [PK[2], "projects/old/o1"], "team-forge-main", 409, "retired project"),
        ("an agent no project lists", [PK[2], PK[3]], "team-forge-nobody", 404, "team-forge-nobody"),
        ("an agent that is no sala session", [PK[2], PK[3]], "team-hollow-slack", 400, "not a sala session"),
        ("no key at all", [], "team-forge-main", 400, "at least one"),
        ("an agent that is no text", [PK[2]], None, 400, "agent ="))):
    sha_b, tree_b, bad_dir = recsha(), brain_tree(), T / f"undo-pk-bad-{n}"
    st, msg = status_of(lambda: pv.page_keeper(keys, agent_, apply=True, io=IO, run_dir=bad_dir))
    check(f"page_keeper: {what} is refused ({status}), naming it, and nothing is written (no key of the call is marked, no undo file)", st == status and word in msg and recsha() == sha_b and brain_tree() == tree_b and not bad_dir.exists(), (st, msg))
st, msg = status_of(lambda: pv.page_keeper([PK[2], "projects/nowhere/x"], "team-forge-main", io=IO))
check("... a dry run refuses a bad key just as an apply does", st == 404, (st, msg))
st, msg = status_of(lambda: pv.page_keeper([PK[2]], "team-forge-nobody", apply=True, io=IO, run_dir=T / "undo-pk-bad"))
check("... the 404 for an agent no project lists names the agents that are listed, and leaves out the one that is no sala session", "team-forge-main" in msg and "team-forge-docs" in msg and "team-hollow-slack" not in msg, msg)
check("... the refusals left the forge's marks as the earlier calls made them", pmarks(FORGE) == {k: "team-forge-docs" for k in PK}, pmarks(FORGE))

# an empty name hands the page back to the keeper above it
r = pv.page_keeper([PK[0], PK[4]], "", apply=True, io=IO, by="lone-session", run_dir=T / "undo-pk-back")
check("page_keeper with an empty name: a page an `agent:` line keeps is handed back (its mark is an empty name, it follows the keeper above it), a page with no such line just loses its mark",
      pmarks(FORGE)[PK[0]] == "" and PK[4] not in pmarks(FORGE) and r["changed"] is True and [x["new_mark"] for x in r["pages"]] == ["", None], (pmarks(FORGE), [x["new_mark"] for x in r["pages"]]))
check("... the readers: the pages follow the project's keeper, p5 as any unmarked page, p1 by the mark above it (role inherited)",
      fields_of(PK[4]) == ("team-forge-builder", "mark") and fields_of(PK[0]) == ("team-forge-builder", "mark") and R()[PK[0]]["role"] == "inherited" and R()[PK[0]].get("page_mark") is not True, (fields_of(PK[0]), R()[PK[0]]))
check("... the answer's lines say who keeps each page before and after", r["lines"][0] == f"keeper of {PK[0]}: team-forge-docs (the mark) -> team-forge-builder (the mark)", r["lines"])
sha4 = recsha()
r = pv.page_keeper([PK[0], PK[4], "projects/forge/sub"], "", apply=True, io=IO, by="lone-session", run_dir=T / "undo-pk-back")
check("... handing back again, and handing back a page that never had a mark, change nothing", r["changed"] is False and r["same"] is True and recsha() == sha4 and r["undo"] is None, (r["lines"], r["changed"]))
pv.restore_undo(pv.page_keeper([PK[0]], "team-forge-docs", apply=True, io=IO, run_dir=T / "undo-pk-back")["undo"], apply=True)
check("... and the undo of a mark set after a hand-back puts the hand-back back", pmarks(FORGE)[PK[0]] == "" and recsha() == sha4, pmarks(FORGE))

# a project's own page, and a retired project's page, for an agent that exists
st, msg = status_of(lambda: pv.page_keeper(["projects/old/o1"], "team-old-docs", apply=True, io=IO, run_dir=T / "undo-pk-old"))
check("page_keeper: a retired project's page is refused (409) even for an agent it lists, and the answer says to reopen", st == 409 and "reopen" in msg, (st, msg))
st, msg = status_of(lambda: pv.page_keeper(["projects/forge"], "team-forge-main", io=IO))
check("page_keeper: the project's own page is a 400 that names `keeper`, a dry run too", st == 400 and "`keeper`" in msg, (st, msg))

# the CLI
sha5 = recsha()
rc, out, err = tool("stackshot/tools/project.py", "page-keeper", PK[5], PK[6], "--agent", "team-forge-main")
check("cli page-keeper: a dry run (no --apply): exit 0, says dry run, names each page, writes nothing", rc == 0 and "dry run" in out and PK[5] in out and PK[6] in out and recsha() == sha5, (rc, out, err))
rc, out, err = tool("stackshot/tools/project.py", "--dry-run", "page-keeper", PK[5], "--agent", "team-forge-main", "--apply")
check("cli page-keeper: --apply with --dry-run contradict (exit 2)", rc == 2 and "contradict" in err and recsha() == sha5, (rc, err))
rc, out, err = tool("stackshot/tools/project.py", "page-keeper", PK[5])
check("cli page-keeper: an agent or --hand-back is needed (exit 2), and so is only one of them", rc == 2 and recsha() == sha5 and tool("stackshot/tools/project.py", "page-keeper", PK[5], "--agent", "x", "--hand-back")[0] == 2, (rc, err))
rc, out, err = tool("stackshot/tools/project.py", "page-keeper", PK[5], "projects/forge/nowhere", "--agent", "team-forge-main", "--apply")
check("cli page-keeper: a bad key among good ones: exit 1, the 404 on stderr, nothing written", rc == 1 and "[404]" in err and recsha() == sha5, (rc, err))
rc, out, err = tool("stackshot/tools/project.py", "page-keeper", PK[5], PK[6], "--agent", "team-forge-main", "--apply", "--run-dir", str(T / "undo-pk-cli"))
check("cli page-keeper --apply: exit 0, both pages carry the mark, the undo command is printed", rc == 0 and pmarks(FORGE).get(PK[5]) == "team-forge-main" and pmarks(FORGE).get(PK[6]) == "team-forge-main" and "restore --undo" in out, (rc, out, err))
rc, out, err = tool("stackshot/tools/project.py", "restore", "--undo", re.search(r"--undo (\S+)", out).group(1), "--apply")
check("cli: the printed undo command takes it back", rc == 0 and recsha() == sha5, (rc, out, err))
rc, out, err = tool("stackshot/tools/project.py", "--json", "page-keeper", "projects/forge/sub", "--hand-back")
check("cli page-keeper --hand-back --json: a dry run of a page with no mark of its own: the whole answer as JSON, the page says same", rc == 0 and json.loads(out)["pages"][0]["same"] is True and json.loads(out)["mirror"]["state"] == "skipped", (rc, out[:300], err))
# ---- 5c. page_keeper: the registry's own answer is what counts (the new record is read back), stored keys are read as the registry reads them, the pre-read, the call that changes nothing
ents_before = set(ents())
def put_record(fn):
    d = recfile(); fn(d); REC.write_text(json.dumps(d), encoding="utf-8"); pr._CACHE["sig"] = None; refresh()
def set_marks(pid, marks):
    def f(d):
        if marks: d["projects"][pid]["page_keepers"] = dict(marks)
        else: d["projects"][pid].pop("page_keepers", None)
    put_record(f)
def attempt(call):
    try: return call(), None, ""
    except pv.VerbError as e: return None, e.status, e.message
class CountIO(page_debt.PlainIO):
    """The plain page store, noting each page it is asked for."""
    def __init__(self): self.gets = []
    def get(self, slug): self.gets.append(slug); return super().get(slug)
# fixtures, made here and taken away at the end of the section: nest (a project that has no entry yet) with a project of its own inside its page (nest/inner) and a page under each; foo and foo-bar (a page whose
# key starts with foo's but is no page under it: it has a `hub:` line); ghosty (an entry whose page is not in the registry, with pages under it)
page("projects/nest.md", "type: project\ntitle: Nest\ndisplay-name: team-nest\nagents:\n  team-nest-main: talks\nstatus: active")
page("projects/nest/y.md", "type: note\ntitle: Nest y"); page("projects/nest/inner.md", "type: note\ntitle: Nest inner"); page("projects/nest/inner/x.md", "type: note\ntitle: Nest inner x")
page("projects/foo.md", "type: project\ntitle: Foo\ndisplay-name: team-foo\nagents:\n  team-foo-main: talks\nstatus: active"); page("projects/foo/z.md", "type: note\ntitle: Foo z")
page("projects/foo-bar.md", "type: note\ntitle: Foo bar\nhub: projects/foo"); page("projects/foo-bar/x.md", "type: note\ntitle: Foo bar x")
page("projects/ghosty/g1.md", "type: note\ntitle: Ghost one"); page("projects/ghosty/g2.md", "type: note\ntitle: Ghost two\nagent: team-forge-main")
refresh()
NEST, INNER = reg()["projects/nest"]["id"], reg()["projects/nest/inner"]["id"]; GHOST = "prj_" + "9a1c4e72"
def add_ents(d):
    d["projects"][INNER] = {"page": "projects/nest/inner", "status": "active", "name": "team-inner", "agents": {"team-inner-main": {"front": True, "mandate_line": "talks"}}}
    d["projects"][GHOST] = {"page": "projects/ghosty", "status": "active", "name": "team-ghosty", "agents": {"team-ghosty-main": {"front": True, "mandate_line": "talks"}}}
put_record(add_ents)
check("5c setup: nest has no entry, the project inside its page has one, and the ghost's page is not in the registry while its sub-pages are",
      NEST not in ents() and INNER in ents() and "projects/ghosty" not in reg() and "projects/ghosty/g1" in reg() and "projects/foo-bar/x" in reg(), (NEST in ents(), INNER in ents(), sorted(k for k in reg() if "ghost" in k)))

# a call that changes nothing, under a project that has no entry yet: nothing is written and no entry is made
sha_c = recsha(); nd = T / "undo-pk-noop"
r = pv.page_keeper(["projects/nest/y"], "", apply=True, io=IO, by="lone-session", run_dir=nd)
check("page_keeper, nothing to change under a project with no entry yet: changed false, no write (same bytes), no undo file or folder, no entry made, the lines say so, and the answer still names the project",
      r["changed"] is False and r["same"] is True and r["undo"] is None and recsha() == sha_c and not nd.exists() and NEST not in ents() and r["lines"] == ["projects/nest/y: it follows the keeper above it already; nothing to change"]
      and r["project"] == NEST and r["key"] == "projects/nest", (r["changed"], r["undo"], r["lines"], r["project"]))
# the page of a project that has no entry yet is read before the lock, once, whatever the call says about it
cio = CountIO()
r = pv.page_keeper(["projects/nest/y"], "team-forge-main", apply=True, io=cio, by="lone-session", run_dir=T / "undo-pk-nest")
check("page_keeper under a project with no entry yet: its page is read once before the record is written (the pre-read), and the entry made from it holds the mark and its agents",
      cio.gets == ["projects/nest"] and pmarks(NEST) == {"projects/nest/y": "team-forge-main"} and "team-nest-main" in ents()[NEST].get("agents", {}) and r["changed"] is True, (cio.gets, pmarks(NEST)))

# a project inside the page of another: the nearest project holds the mark
r, st, msg = attempt(lambda: pv.page_keeper(["projects/nest/inner/x"], "team-forge-main", apply=True, io=IO, by="lone-session", run_dir=T / "undo-pk-inner"))
check("page_keeper, a page under a project that sits inside another's page: the mark is held on the entry of the nearest project (the inner one), not the topmost, and the registry reads it",
      st is None and pmarks(INNER) == {"projects/nest/inner/x": "team-forge-main"} and "projects/nest/inner/x" not in pmarks(NEST) and r["pages"][0]["project"] == INNER and r["pages"][0]["holder"] == "projects/nest/inner"
      and fields_of("projects/nest/inner/x") == ("team-forge-main", "mark"), (st, msg, pmarks(INNER), pmarks(NEST)))
r, st, msg = attempt(lambda: pv.page_keeper(["projects/nest/y", "projects/nest/inner/x"], "", io=IO))
check("... and a call over a page of each holds each on its own entry (the outer project's page: the outer entry)", st is None and [x["project"] for x in r["pages"]] == [NEST, INNER], (st, msg))

# a page whose key starts with a project's key but sits under another page: the whole-segment prefix decides
sha_c = recsha(); fb = T / "undo-pk-foobar"
r, st, msg = attempt(lambda: pv.page_keeper(["projects/foo-bar/x"], "team-forge-main", apply=True, io=IO, run_dir=fb))
check("page_keeper: a page under `projects/foo-bar` is not held by `projects/foo` (a whole-segment prefix, not a string one): it reaches foo by a `hub:` line, so it is refused for that, and nothing is written",
      st == 400 and "hub:" in msg and recsha() == sha_c and not fb.exists(), (st, msg))
r, st, msg = attempt(lambda: pv.page_keeper(["projects/foo/z"], "team-forge-main", io=IO))
check("... while a page under `projects/foo` is held by foo", st is None and r["pages"][0]["holder"] == "projects/foo", (st, msg))

# a mark the registry would not read is refused before anything is written
sha_c = recsha(); gd = T / "undo-pk-ghost"
for what, keys, who, word in (("a set", ["projects/ghosty/g1"], "team-forge-docs", "not team-forge-docs (the mark)"), ("a hand-back of a page an `agent:` line keeps", ["projects/ghosty/g2"], "", "not the keeper above it"),
                              ("a set among pages that are fine", [PK[2], "projects/ghosty/g1", PK[3]], "team-forge-docs", "not team-forge-docs (the mark)")):
    for apply_ in (True, False):
        r, st, msg = attempt(lambda: pv.page_keeper(keys, who, apply=apply_, io=IO, run_dir=gd))
        check(f"page_keeper: {what} on a page whose entry's page is not in the registry is refused (400, {'--apply' if apply_ else 'a dry run'}): the page is named, the answer says what the registry gives instead and why, nothing is written, no undo file",
              st == 400 and "projects/ghosty/g" in msg and "the registry would answer" in msg and word in msg and "projects/ghosty is no page the registry holds" in msg and "nothing was changed" in msg and recsha() == sha_c and not gd.exists(), (st, msg))
r, st, msg = attempt(lambda: pv.page_keeper(["projects/ghosty/g2"], "team-forge-main", apply=True, io=IO, run_dir=gd))
check("... a set of the agent that the page's own `agent:` line names already is refused too: the page answers that agent by its name line, not by the mark",
      st == 400 and "would answer team-forge-main (the name line) for it, not team-forge-main (the mark)" in msg and recsha() == sha_c and not gd.exists(), (st, msg))
r, st, msg = attempt(lambda: pv.page_keeper(["projects/ghosty/g1"], "", apply=True, io=IO, run_dir=gd))
check("... a hand-back of a page that has no mark and no `agent:` line has nothing to take back, and is no refusal", st is None and r["same"] is True and r["changed"] is False and recsha() == sha_c, (st, msg))

# stored keys are read the way the registry reads them: a slash at the end or `.md` is the page
K8, K9 = PK[7], PK[8]
set_marks(FORGE, {K8 + "/": "team-forge-docs"})
check("5c setup: a mark stored under a key with a slash at its end is read as the page's mark", fields_of(K8) == ("team-forge-docs", "mark"), fields_of(K8))
sha_c = recsha()
r = pv.page_keeper([K8], "", io=IO)
check("page_keeper --hand-back of a page whose mark is stored under a key with a slash: it sees that mark (not `nothing to change`), says the keeper goes from the mark to the project's, and a dry run writes nothing",
      r["same"] is False and r["changed"] is True and r["pages"][0]["old"] == "team-forge-docs" and r["pages"][0]["old_source"] == "mark" and r["pages"][0]["old_mark"] == "team-forge-docs" and r["pages"][0]["new_source"] == "mark" and r["pages"][0]["new"] == "team-forge-builder"
      and recsha() == sha_c, (r["lines"], r["pages"]))
r = pv.page_keeper([K8], "", apply=True, io=IO, by="lone-session", run_dir=T / "undo-pk-slash")
check("... applied: every stored key of the page is gone and the page answers the project's keeper", pmarks(FORGE) == {} and fields_of(K8) == ("team-forge-builder", "mark") and "page_mark" not in R()[K8] and r["undo"] and pathlib.Path(r["undo"]).is_file(), (pmarks(FORGE), fields_of(K8)))
set_marks(FORGE, {K8 + "/": "team-forge-docs", K8 + ".md": "team-forge-main", K8: "team-forge-docs", K9: "team-forge-docs"})
check("5c setup: a page marked under three spellings is read as marked twice (the first key rules, the others are ignored and said on the project's row)",
      fields_of(K8) == ("team-forge-docs", "mark") and len([x for x in R()["projects/forge"].get("keeper_problems", []) if "marked twice" in x]) == 2, R()["projects/forge"].get("keeper_problems"))
r = pv.page_keeper([K8], "team-forge-main", apply=True, io=IO, by="lone-session", run_dir=T / "undo-pk-three")
check("page_keeper: a set removes every other stored key of the page and writes one under the page's key (the other page's mark stays as it was), so the registry reads no `marked twice`",
      pmarks(FORGE) == {K8: "team-forge-main", K9: "team-forge-docs"} and fields_of(K8) == ("team-forge-main", "mark") and not [x for x in R()["projects/forge"].get("keeper_problems", []) if "marked twice" in x], (pmarks(FORGE), R()["projects/forge"].get("keeper_problems")))
set_marks(FORGE, {K8 + "/": "team-forge-docs"})
r = pv.page_keeper([K8], "team-forge-docs", apply=True, io=IO, by="lone-session", run_dir=T / "undo-pk-rekey")
check("page_keeper: the same agent under a key that is not the page's key is a change (the key is rewritten), and the call after it changes nothing",
      r["changed"] is True and r["pages"][0]["same"] is False and pmarks(FORGE) == {K8: "team-forge-docs"} and pv.page_keeper([K8], "team-forge-docs", apply=True, io=IO, run_dir=T / "undo-pk-rekey2")["changed"] is False, (pmarks(FORGE), r["lines"]))
set_marks(FORGE, {K8: "team-forge-docs", K8 + "/": "team-forge-docs"})
r = pv.page_keeper([K8], "team-forge-docs", apply=True, io=IO, by="lone-session", run_dir=T / "undo-pk-dup")
check("page_keeper: a stray second key of a page that has the mark already is taken away (not `same`)", r["changed"] is True and pmarks(FORGE) == {K8: "team-forge-docs"}, (pmarks(FORGE), r["lines"]))
set_marks(FORGE, {PK[7]: "team-forge-docs", PK[2]: "team-forge-docs", K9: "team-forge-docs"})
pv.page_keeper([PK[2]], "team-forge-main", apply=True, io=IO, by="lone-session", run_dir=T / "undo-pk-order")
check("page_keeper: a mark stored under the page's own key is overwritten, and the marks of the other pages are as they were", pmarks(FORGE) == {PK[7]: "team-forge-docs", PK[2]: "team-forge-main", K9: "team-forge-docs"}, pmarks(FORGE))
set_marks(FORGE, {})

# a key named twice, or in another spelling, is one page
sha_c = recsha()
r = pv.page_keeper([K8, K8, K8 + "/", K8 + ".md", "  " + K8 + "  "], "team-forge-docs", io=IO)
check("page_keeper: a key named twice, or as `KEY/`, `KEY.md` or with spaces round it, is one page: one row, one line", [x["key"] for x in r["pages"]] == [K8] and len([ln for ln in r["lines"] if ln.startswith("dry run: keeper of")]) == 1, (r["pages"], r["lines"]))
r = pv.page_keeper([K8 + "/", K8 + ".md"], "team-forge-docs", apply=True, io=IO, by="lone-session", run_dir=T / "undo-pk-spell")
check("... and a page named only as `KEY/` or `KEY.md` is marked under its own key", pmarks(FORGE) == {K8: "team-forge-docs"} and len(r["pages"]) == 1, (pmarks(FORGE), r["pages"]))
set_marks(FORGE, {})

# the registry check says where a mark that is not read can be mended, and where it cannot
set_marks(FORGE, {PK[2]: "team-nobody-listed"})
dd = [f for f in rr.keeper_debts(pr.entries(), prj.registry_raw(), R()) if f["line"] == rr.LINE_KEEPER_PAGE]
check("registry check: the fix text of an ignored page mark names `page-keeper` (set and hand back) for a mark on the right holder, and says a mark on a page that no longer exists, or on another entry, is for whoever maintains the record to edit",
      len(dd) == 1 and "`tools/project.py page-keeper <page> --agent <agent>`" in dd[0]["fix"] and "`--hand-back` removes it" in dd[0]["fix"] and "no longer exists" in dd[0]["fix"] and "whoever maintains the record" in dd[0]["fix"]
      and "nearest above it" in dd[0]["fix"], dd)
set_marks(FORGE, {})

# the command line refuses an empty agent name
sha_c = recsha()
for bad in ("", "   "):
    rc, out, err = tool("stackshot/tools/project.py", "page-keeper", PK[5], "--agent", bad, "--apply")
    check(f"cli page-keeper: --agent {bad!r} is refused (exit 2) and names `--hand-back`, and nothing is written", rc == 2 and "--hand-back" in err and recsha() == sha_c, (rc, out, err))
rc, out, err = tool("stackshot/tools/project.py", "page-keeper", PK[5], "--hand-back")
check("cli page-keeper: --hand-back is the way (a page with no mark has nothing to hand back)", rc == 0 and "nothing to change" in out and recsha() == sha_c, (rc, out, err))

# take the fixtures away
def drop_ents(d):
    for pid in [x for x in d["projects"] if x not in ents_before]: del d["projects"][pid]
put_record(drop_ents)
for rel in ("projects/nest", "projects/foo", "projects/foo-bar", "projects/ghosty"):
    shutil.rmtree(BRAIN / rel, ignore_errors=True); (BRAIN / (rel + ".md")).unlink(missing_ok=True)
refresh()

# leave the forge as the sections below read it: no page marks, and the project's mark where it was
d = recfile()
for pid in (FORGE, WIDE, GONE): d["projects"][pid].pop("page_keepers", None)
REC.write_text(json.dumps(d), encoding="utf-8"); pr._CACHE["sig"] = None
pv.keeper("projects/forge", "team-forge-main", apply=True, io=IO, by="lone-session", run_dir=T / "undo-pk-setup")

# ---- 6. the four debts of the registry check
def ent(agents, former=(), **kw): return {"page": kw.pop("page", "projects/debtx"), "status": "active", "name": "team-debtx", "agents": agents, "former_agents": list(former), **kw}
def ag(*names, mark=(), back=()):
    return {n: {"front": n not in back, "mandate_line": "builds" if n in back else "talks", **({"keeper": True} if n in mark else {})} for n in names}
def kinds(es, rg): return sorted({(f["line"], f["page"]) for f in rr.keeper_debts(es, rg, R())})
row = lambda **kw: {"type": "project", "role": "name", "session": "team-debtx", **kw}
none_ = kinds({"prj_debtx": ent(ag("team-debtx-main", "team-debtx-docs", mark=["team-debtx-main"]))}, {"projects/debtx": row(agents={"team-debtx-main": "", "team-debtx-docs": ""})})
check("debts: a healthy mark (one flag, a listed agent) is no debt", none_ == [], none_)
two = rr.keeper_debts({"prj_debtx": ent(ag("team-debtx-main", "team-debtx-docs", mark=["team-debtx-main", "team-debtx-docs"]))}, {"projects/debtx": row(agents={"team-debtx-main": "", "team-debtx-docs": ""})}, R())
check("keeper-two-marks: two flagged agents in the record, with the fix `keeper`", [f["line"] for f in two] == ["keeper-two-marks"] and "tools/project.py keeper prj_debtx" in two[0]["fix"], two)
two_b = rr.keeper_debts({"prj_debtx": ent(ag("team-debtx-main", "team-debtx-docs", mark=["team-debtx-main"]))}, {"projects/debtx": row(role="mark", session="team-debtx-docs", agents={"team-debtx-main": "", "team-debtx-docs": ""})}, R())
check("keeper-two-marks: the record's flag and the page's `keeper:` line name different agents", [f["line"] for f in two_b] == ["keeper-two-marks"], two_b)
nl = rr.keeper_debts({"prj_debtx": ent(ag("team-debtx-main"))}, {"projects/debtx": row(role="mark", session="team-debtx-docs", agents={"team-debtx-main": ""}, keeper_problems=["`keeper: team-debtx-docs` names no agent on the page's `agents:` map; ignored"])}, R())
check("keeper-not-listed: the page's `keeper:` line names an agent the record does not list", [f["line"] for f in nl if f["line"] == "keeper-not-listed"] == ["keeper-not-listed"], nl)
check("keeper-not-listed: a stale page `keeper:` line is fixed by editing or removing the line, never by the keeper verb (which writes the record's flag only)",
      "edit the page's `keeper:` line" in nl[0]["fix"] and "remove the line" in nl[0]["fix"] and "tools/project.py keeper prj_debtx" not in nl[0]["fix"], nl)
bad = rr.keeper_debts({"prj_debtx": ent({"team-debtx-main": {"front": True, "mandate_line": "talks", "keeper": "yes"}})}, {"projects/debtx": row(agents={"team-debtx-main": ""})}, R())
check("keeper-not-listed: a flag that is neither true nor false is reported (and is no mark)", [f["line"] for f in bad if f["line"] == "keeper-not-listed"] == ["keeper-not-listed"], bad)
rt = rr.keeper_debts({"prj_debtx": ent(ag("team-debtx-docs", "team-debtx-gone", mark=["team-debtx-gone"]), former=["team-debtx-gone"])}, {"projects/debtx": row(agents={"team-debtx-docs": "", "team-debtx-gone": ""})}, R())
check("keeper-retired: a flag on an agent the entry lists as retired", [f["line"] for f in rt] == ["keeper-retired"], rt)
check("... a flag (a malformed one, a retired one) keeps the verb as its fix: only a page's own line is edited by hand", "tools/project.py keeper prj_debtx" in bad[0]["fix"] and "tools/project.py keeper prj_debtx" in rt[0]["fix"], (bad[0]["fix"], rt[0]["fix"]))
rt2 = rr.keeper_debts({"prj_debtx": ent(ag("team-debtx-docs"), former=["team-debtx-gone"])}, {"projects/debtx": row(agents={"team-debtx-docs": ""}, keeper_problems=["`keeper: team-debtx-gone` names no agent on the page's `agents:` map; ignored"])}, R())
check("keeper-retired: the page's `keeper:` line names an agent the record retired", [f["line"] for f in rt2] == ["keeper-retired"], rt2)
nd = rr.keeper_debts({"prj_debtx": ent(ag("team-debtx-w", back=["team-debtx-w"]))}, {"projects/debtx": row(agents={"team-debtx-w": "watches"}, back_agents={"team-debtx-w": ""})}, {"projects/debtx": {"keeper_agent": "", "keeper_source": ""}})
check("keeper-not-derived: agents listed, no mark, and no keeper to derive", [f["line"] for f in nd] == ["keeper-not-derived"], nd)
nd2 = rr.keeper_debts({"prj_debtx": ent(ag("team-debtx-w", back=["team-debtx-w"]))}, {"projects/debtx": row(agents={"team-debtx-w": "watches"}, back_agents={"team-debtx-w": ""})}, {"projects/debtx": {"keeper_agent": "team-debtx-w", "keeper_source": "derived"}})
check("keeper-not-derived: not reported when the derivation names a keeper", nd2 == [], nd2)
arch = rr.keeper_debts({"prj_debtx": ent(ag("team-debtx-main", "team-debtx-docs", mark=["team-debtx-main", "team-debtx-docs"]), status="archived")}, {"projects/debtx": row(agents={"team-debtx-main": "", "team-debtx-docs": ""})}, R())
check("debts: a retired project is not reported", arch == [], arch)
LIVE = sorted((f["page"], f["line"]) for f in rr.keeper_debts(ents(), reg(), R()))
check("debts: after the verbs, the only debts are the two page lines that name another agent than the record's mark (a page-held mark whose agent was renamed, and a record flag over a page line)",
      LIVE == [("projects/ember", "keeper-not-listed"), ("projects/ember2", "keeper-two-marks")], LIVE)
es = {"prj_debtx": ent(ag("team-debtx-main", "team-debtx-docs", mark=["team-debtx-main", "team-debtx-docs"]))}; rg1 = {"projects/debtx": row(agents={"team-debtx-main": "", "team-debtx-docs": ""})}
off = rr.scan(ents=es, reg=rg1, sessions=None, items=None, pending={}, page_get=None)
on = rr.scan(ents=es, reg=rg1, sessions=None, items=None, pending={}, page_get=None, debts=True, ov=R())
check("debts are off by default: the scan reports none unless `[registry_audit] keeper_debts` is true (or debts=True)", cfg.registry_keeper_debts() is False and not [f for f in off["findings"] if f["line"].startswith("keeper-")] and [f["line"] for f in on["findings"] if f["line"].startswith("keeper-")] == ["keeper-two-marks"], (off["findings"], on["findings"]))
# the key missing from the config (an instance whose toml predates it: the config is one file with no defaults merged in): every path reads false
_saved = cfg.CFG.get("registry_audit", {}).pop("keeper_debts", "<absent>")
try:
    miss_scan = rr.scan(ents=es, reg=rg1, sessions=None, items=None, pending={}, page_get=None, ov=R())
    miss_read = rr.read(ents=es, reg=rg1, ov=R(), sessions=lambda: None, items=[], pending={}, page_get=lambda k: (None, None))
    check("debts: with the key missing from the config the flag reads false, and neither the scan nor the check (the audit run, the registry_report command and the page-debt call all go through them) reports a keeper debt",
          _saved is not None and cfg.registry_keeper_debts() is False and not [f for f in miss_scan["findings"] if f["line"].startswith("keeper-")] and not [f for f in miss_read["findings"] if f["line"].startswith("keeper-")],
          (_saved, cfg.registry_keeper_debts(), miss_scan["findings"], miss_read["findings"]))
    cfg.CFG.setdefault("registry_audit", {})["keeper_debts"] = "yes"
    check("debts: a value that is not the boolean true (a string) reads false", cfg.registry_keeper_debts() is False)
finally:
    cfg.CFG.setdefault("registry_audit", {}).pop("keeper_debts", None)
    if _saved != "<absent>": cfg.CFG["registry_audit"]["keeper_debts"] = _saved
tt = (T / "stackshot.toml").read_text(); assert tt.count("keeper_debts = false") == 1
(T / "stackshot.toml").write_text(tt.replace("keeper_debts = false", "keeper_debts = true"), encoding="utf-8"); cfg.reload()
on2 = rr.scan(ents=es, reg=rg1, sessions=None, items=None, pending={}, page_get=None, ov=R())
check("debts: with `keeper_debts = true` in the config the scan reports them", cfg.registry_keeper_debts() is True and [f["line"] for f in on2["findings"] if f["line"].startswith("keeper-")] == ["keeper-two-marks"], (cfg.registry_keeper_debts(), on2["findings"]))

if fails: print(f"FAILED: keeper verbs scenario, {len(ran)} checks, {len(fails)} failed"); sys.exit(1)
print(f"ok: keeper verbs scenario, {len(ran)} checks")
