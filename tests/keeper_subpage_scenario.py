"""Scenario test for a sub-page's own keeper mark (`page_keepers` on the record entry of the project the page sits under) and the one-time pass that moves the sub-pages an `agent:` line keeps
into it (stackshot/projects/keeper_subpages.py): fixture data, no live store, no network, no server process (a temporary config; the page store is a plain markdown folder, the record a file of it).

    tests/run-suite keeper_subpage        → exit 0 / 1"""
import hashlib, json, logging, os, pathlib, re, subprocess, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="keepersubpage-"); T = pathlib.Path(tmp)
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
def page(rel, front):
    q = BRAIN / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")

# Neutral fixtures. forge: a project with a builder whose record marks the builder; loft: front agents only, its keeper derived; drift: a project with agents on its page and no record entry; old-one: archived.
# The sub-pages: forge/plan and forge/runner name an agent of the forge's own map; forge/notes and loft/side name an agent of the other project (cross-project keepers); forge/old and loft/ghost name
# a session no project lists and none runs under; forge/liveonly names a running session no project lists; forge/plain names nobody; forge/plan/detail names nobody and sits under forge/plan;
# drift/sub sits under a project with no record entry; solo is a top-level page with an `agent:` line; old-one/sub sits under an archived project.
page("projects/forge.md", "type: project\ntitle: Forge\nagents:\n  forge-main: talks\n  background:\n    forge-builder: builds and merges\nstatus: active")
page("projects/forge/plan.md", "type: note\ntitle: Forge plan\nagent: forge-main")
page("projects/forge/plan/detail.md", "type: note\ntitle: Forge plan detail")
page("projects/forge/runner.md", "type: note\ntitle: Forge runner\nagent: forge-builder")
page("projects/forge/notes.md", "type: note\ntitle: Forge notes\nagent: loft-main")
page("projects/forge/old.md", "type: note\ntitle: Forge old\nagent: gone-session")
page("projects/forge/liveonly.md", "type: note\ntitle: Forge live only\nagent: running-sess")
page("projects/forge/plain.md", "type: note\ntitle: Forge plain")
page("projects/loft.md", "type: project\ntitle: Loft\nagents:\n  loft-main: talks\n  loft-docs: keeps the docs\nstatus: active")
page("projects/loft/side.md", "type: note\ntitle: Loft side\nagent: forge-main")
page("projects/loft/ghost.md", "type: note\ntitle: Loft ghost\nagent: ghost-two")
page("projects/drift.md", "type: project\ntitle: Drift\nagents:\n  drift-main: talks\nstatus: active")
page("projects/drift/sub.md", "type: note\ntitle: Drift sub\nagent: loft-main")
page("projects/solo.md", "type: note\ntitle: Solo\nagent: loft-main")
page("projects/old-one.md", "type: project\ntitle: Old one\nagents:\n  old-one-main: talks\nstatus: archived")
page("projects/old-one/sub.md", "type: note\ntitle: Old sub\nagent: loft-main")
page("projects/named.md", "type: project\ntitle: Named\ndisplay-name: team-named\nstatus: active")
page("projects/named/own.md", "type: note\ntitle: Named own\ndisplay-name: team-own")

sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
REC = T / "store/project-record.json"
from stackshot.projects import pages as p; from stackshot.projects import projects as prj; from stackshot.projects import project_registry as pr; from stackshot.projects import keeper as kp
from stackshot.projects import project_restore as rs; from stackshot.projects import keeper_reads as KR
from stackshot.anchors import anchors; from stackshot.router import router_live as rl; from stackshot.service import telling
from stackshot import cli
try:
    from stackshot.projects import keeper_subpages as ks
except ImportError as e:
    ks = None; print(f"keeper_subpages is not importable: {e}")
p.cmd_registry(quiet=True)
def raw(): return json.loads((T / "store/projects.json").read_text())["pages"]
ids = {k: e["id"] for k, e in raw().items()}
def agent(front, mandate, **kw): return {"front": front, "mandate_line": mandate, **kw}
def write_record(entries):
    d = json.loads(REC.read_text()) if REC.exists() else {}
    d.update({"projects": entries, "projects_schema": 1}); REC.write_text(json.dumps(d, indent=1) + "\n", encoding="utf-8"); pr._CACHE["sig"] = None
def entry(key, **kw): return {"page": key, "status": "active", **kw}
def R(): return prj.registry()
def tree(*roots):
    out = {}
    for r in roots:
        for q in sorted(pathlib.Path(r).rglob("*")):
            if q.is_file(): out[str(q)] = hashlib.sha256(q.read_bytes()).hexdigest()
    return out
def recbytes(): return REC.read_bytes()
def tool(*args):
    r = subprocess.run([sys.executable, f"{STACK}/stackshot/projects/keeper_subpages.py", *args], capture_output=True, text=True, env=os.environ, cwd=str(T))
    return r.returncode, r.stdout, r.stderr

F, LO, DR, OLD = (ids[f"projects/{k}"] for k in ("forge", "loft", "drift", "old-one"))
ENTRIES = {
    F: entry("projects/forge", agents={"forge-main": agent(True, "talks"), "forge-builder": agent(False, "builds and merges", keeper=True)}),
    LO: entry("projects/loft", agents={"loft-main": agent(True, "talks"), "loft-docs": agent(True, "keeps the docs")}),
    OLD: entry("projects/old-one", status="archived", agents={"old-one-main": agent(True, "talks")}),
}
write_record(ENTRIES)
ORIG = recbytes()
LIVE = {"running-sess", "forge-main", "loft-main"}
RUN = T / "undo-runs"
SPACE = [T / "store", T / "brain", T / "state", T / "fleet"]
SUBS = {"projects/forge/plan": "forge-main", "projects/forge/runner": "forge-builder", "projects/forge/notes": "loft-main", "projects/loft/side": "forge-main"}
NOBODY = ["projects/forge/old", "projects/loft/ghost"]
def legacy(rg): return sorted(k for k, v in rg.items() if isinstance(v, dict) and v.get("keeper_source") == "legacy")

def snap(rg):
    """What every reader of "who keeps this page" answers, for every page and every name: the registry's session and role, the names that keep each page, the pages each name keeps (the client's and the
    server's readers), the hubs a name belongs to, the notice name, the stand-in and the item keeper of every project and sub-page, and roles.json."""
    names = sorted({n for v in rg.values() for n in kp.names_of(v)})
    out = {"rows": {k: (v.get("session"), v.get("role"), sorted(kp.names_of(v))) for k, v in rg.items()}}
    out["pages_of"] = {n: p.keeper_pages("", n) for n in names}
    out["any"] = {n: p.keepers_any([n]) for n in names}
    out["marks_of"] = {n: anchors.keeper_pages(n, rg) for n in names}
    out["hubs"] = {n: anchors.session_hubs(n, rg, {}) for n in names}
    out["notice"] = {k: anchors.notice_name(k, rg) for k in rg}
    out["stand_in"] = {k: rl.stand_in_of(k, rg) for k in rg}
    out["page_keeper"] = {k: telling.page_keeper(k, rg) for k in rg}
    out["project_keeper"] = {k: telling.project_keeper(k) for k in rg}
    out["roles"] = anchors.file_roles(rg, set())
    out["sessions"] = anchors.session_roles(rg, set())
    return out

# ---- 0. the starting point: every sub-page above is kept by its `agent:` line alone
rg0 = R(); s0 = snap(rg0)
check("start: the sub-pages an `agent:` line keeps read legacy, with the agent as their session, role agent",
      all((rg0[k]["keeper_agent"], rg0[k]["keeper_source"], rg0[k]["role"]) == (rg0[k]["session"], "legacy", "agent") for k in (*SUBS, *NOBODY, "projects/forge/liveonly", "projects/drift/sub", "projects/solo")),
      {k: (rg0[k].get("keeper_agent"), rg0[k].get("keeper_source"), rg0[k].get("role")) for k in rg0})
check("start: a sub-page under a retired project has no keeper at all, and the page that names nobody follows the forge's mark", rg0["projects/old-one/sub"]["keeper_source"] == "" and
      (rg0["projects/forge/plain"]["keeper_agent"], rg0["projects/forge/plain"]["keeper_source"]) == ("forge-builder", "mark"), (rg0["projects/old-one/sub"], rg0["projects/forge/plain"]))
LEG0 = legacy(rg0)
check("start: the legacy rows are the eleven pages a name line or an `agent:` line keeps (no row of a retired project, none under a mark)", len(LEG0) == 11 and "projects/named" in LEG0, LEG0)

# ---- 1. the record field: its shape is checked, a bad shape is the record's usual refusal
for bad_name, bad in (("not a map", ["projects/forge/plan"]), ("a value that is not a name", {"projects/forge/plan": 3}), ("an empty key", {"": "forge-main"})):
    try:
        pr.parse({pr.SECTION: {F: {**ENTRIES[F], "page_keepers": bad}}, pr.VERSION: 1}); raised = False
    except ValueError: raised = True
    check(f"parse: a page_keepers that is {bad_name} is refused like any malformed field", raised)
check("parse: a map of page keys to names (an empty name included) reads", pr.parse({pr.SECTION: {F: {**ENTRIES[F], "page_keepers": {"projects/forge/plan": "forge-main", "projects/forge/old": ""}}}, pr.VERSION: 1}) is not None)

# ---- 2. a sub-page mark laid by hand: the row, the gauge, what stays
write_record({**ENTRIES, F: {**ENTRIES[F], "page_keepers": {"projects/forge/plan": "forge-main", "projects/forge/notes": "loft-main", "projects/forge/plain": "loft-docs"}}})
rg1 = R()
check("a sub-page mark names the agent of its own map: keeper_source mark, the same session and role as the `agent:` line gave", (rg1["projects/forge/plan"]["keeper_agent"], rg1["projects/forge/plan"]["keeper_source"],
      rg1["projects/forge/plan"]["session"], rg1["projects/forge/plan"]["role"]) == ("forge-main", "mark", "forge-main", "agent"), rg1["projects/forge/plan"])
check("a sub-page mark may name an agent that is not on the project's map: loft-main keeps forge/notes", (rg1["projects/forge/notes"]["keeper_agent"], rg1["projects/forge/notes"]["keeper_source"],
      rg1["projects/forge/notes"]["session"], rg1["projects/forge/notes"]["role"]) == ("loft-main", "mark", "loft-main", "agent") and "loft-main" not in rg1["projects/forge"]["agents"], rg1["projects/forge/notes"])
check("a mark on a page that named nobody gives it a keeper of its own (role agent, the readers of such a page read it): loft-docs keeps forge/plain", (rg1["projects/forge/plain"]["session"], rg1["projects/forge/plain"]["role"],
      rg1["projects/forge/plain"]["keeper_source"]) == ("loft-docs", "agent", "mark") and p.keeper_pages("", "loft-docs") == ["projects/forge/plain"], rg1["projects/forge/plain"])
check("the page under a marked sub-page does not inherit from it, as it did not from an `agent:` page", rg1["projects/forge/plan/detail"] == rg0["projects/forge/plan/detail"], rg1["projects/forge/plan/detail"])
check("a page with no mark answers exactly as before, the `agent:` line read as ever (additive)", all(rg1[k] == rg0[k] for k in ("projects/forge/runner", "projects/forge/old", "projects/loft/side", "projects/loft/ghost", "projects/forge/liveonly", "projects/solo")), None)
check("the gauge counts a marked sub-page as not legacy: two fewer legacy rows for the two `agent:` pages marked (forge/plain was not legacy)", len(legacy(rg1)) == len(LEG0) - 2 and not {"projects/forge/plan", "projects/forge/notes"} & set(legacy(rg1)), legacy(rg1))

# ---- 3. a mark that cannot be read is ignored and said, never an error
write_record({**ENTRIES, F: {**ENTRIES[F], "page_keepers": {"projects/forge/plan": "nobody-lists-me", "projects/loft/side": "forge-main", "projects/forge/gone": "forge-main", "projects/named/own": "forge-main",
                                                                "projects/forge/plain": ""}}})
rg2 = R()
probs = rg2["projects/forge"].get("keeper_problems") or []
check("a mark naming an agent no project lists is ignored: the page's `agent:` line answers, and the project's row says so", rg2["projects/forge/plan"] == rg0["projects/forge/plan"] and any("forge/plan" in x and "nobody-lists-me" in x for x in probs), probs)
check("a mark on a page that is not under the project is ignored and said", rg2["projects/loft/side"] == rg0["projects/loft/side"] and any("projects/loft/side" in x and "no page under the project" in x for x in probs), probs)
check("a mark on a key that is no page is ignored and said", any("projects/forge/gone" in x for x in probs), probs)
check("an empty name on a page that follows the page above anyway changes nothing and says nothing", rg2["projects/forge/plain"] == rg0["projects/forge/plain"] and not any("forge/plain" in x for x in probs), probs)
check("the problem lines do not read as a mark naming an unlisted agent of the page's own map (the registry check's debt)", kp.unlisted_lines(probs) == [], probs)
write_record({**ENTRIES, LO: {**ENTRIES[LO], "page_keepers": {"projects/loft": "loft-docs"}}})
check("a mark on the project's own page is no sub-page mark: ignored", R()["projects/loft"]["keeper_source"] == "derived" and any("projects/loft" in x for x in R()["projects/loft"].get("keeper_problems") or []), R()["projects/loft"])
write_record(ENTRIES)
check("with no page_keepers the registry is what it was before", R() == rg0, None)

# ---- 4. the pass: the dry run
if ks is None:
    check("keeper_subpages is importable", False)
else:
    before = tree(*SPACE)
    dry = ks.run(live=LIVE, run_dir=RUN)
    check("dry run: not a byte of the store, the pages, the state or the fleet dir changes, and no undo file is made", tree(*SPACE) == before and not RUN.exists() and recbytes() == ORIG)
    check("dry run: written is False, nothing refused, no undo", dry["dry"] is True and dry["written"] is False and dry["refused"] == "" and dry["undo"] is None, {k: dry[k] for k in ("dry", "written", "refused", "undo")})
    c = dry["counts"]
    by = {r["key"]: r for r in dry["pages"]}
    check("dry run: the eleven legacy rows are read; the four sub-pages that name a listed agent are marked (two of them an agent of the other project), the two that name nobody are handed back, three are left",
          (c["pages"], c["mark"], c["cross_project"], c["inherit"], c["leave"]) == (9, 4, 2, 2, 3), c)
    check("dry run: each page says its agent and the action: own map, other project's map, nowhere",
          all(by[k]["action"] == "mark" and by[k]["agent"] == a for k, a in SUBS.items()) and by["projects/forge/plan"]["where"] == "own map" and by["projects/forge/notes"]["where"].startswith("map of projects/loft")
          and by["projects/loft/side"]["where"].startswith("map of projects/forge") and all(by[k]["action"] == "inherit" and by[k]["where"] == "nowhere" for k in NOBODY), by)
    check("dry run: what it leaves it says why: a top-level page, a project with no record entry, a running session no project lists",
          by["projects/solo"]["action"] == "leave" and "not a sub-page" in by["projects/solo"]["why"] and by["projects/drift/sub"]["action"] == "leave" and "no project record entry" in by["projects/drift/sub"]["why"]
          and by["projects/forge/liveonly"]["action"] == "leave" and "list it" in by["projects/forge/liveonly"]["why"], by)
    check("dry run: the name-line pages, the pages under a retired project and the marked ones are not rows", not {"projects/named", "projects/named/own", "projects/old-one/sub", "projects/forge/plain"} & set(by), sorted(by))
    text = "\n".join(dry["lines"])
    for need in ("sub-page", "agent named", "action", r"projects/forge/notes\s+loft-main\s+mark", "legacy gauge: 11 -> 5", "nothing written", "running sessions that lose a page: 0"):
        check(f"dry run text says: {need}", re.search(need, text) is not None, text)
    check("dry run: the gauge falls by the pages marked and the pages handed back to a mark above (forge/old: the forge's mark; loft/ghost: derived)", dry["effects"]["gauge"] == {"before": 11, "after": 5}, dry["effects"]["gauge"])
    check("dry run: no running session loses a page and roles.json moves for nobody", dry["effects"]["live_lose"] == [] and dry["effects"]["roles"] == [], dry["effects"])

    # ---- 5. the apply: the record only, an undo file, readers answering as before
    ok = ks.run(apply_=True, live=LIVE, run_dir=RUN, now="2026-11-01T00:00:00Z")
    check("apply: written, an undo file named, nothing refused", ok["written"] is True and ok["refused"] == "" and ok["undo"] and pathlib.Path(ok["undo"]).is_file() and any("to undo: project.py restore --undo" in l for l in ok["lines"]), ok["lines"][-3:])
    done = recbytes(); d = json.loads(done)
    check("apply: the record holds the marks on the entry of the project above each page, the dead names handed back with an empty name, and nothing else changed", d["projects"][F]["page_keepers"] == {
          "projects/forge/plan": "forge-main", "projects/forge/runner": "forge-builder", "projects/forge/notes": "loft-main", "projects/forge/old": ""} and d["projects"][LO]["page_keepers"] == {
          "projects/loft/side": "forge-main", "projects/loft/ghost": ""} and "page_keepers" not in d["projects"][OLD]
          and {k: v for k, v in d["projects"][F].items() if k != "page_keepers"} == ENTRIES[F] and {k: v for k, v in d["projects"][LO].items() if k != "page_keepers"} == ENTRIES[LO], d["projects"])
    check("apply: no page changed (the `agent:` lines stay)", all("agent:" in (BRAIN / f"{k}.md").read_text() for k in (*SUBS, *NOBODY)), None)
    rg3 = R(); s3 = snap(rg3)
    check("the gauge fell: the legacy rows are now the three left, the two name-line pages' rows, and what a name line above still names", len(legacy(rg3)) == 5 and set(legacy(rg3)) >= {"projects/solo", "projects/drift/sub", "projects/forge/liveonly"}, legacy(rg3))
    check("the legacy count fell by exactly the pages marked and the pages handed back to a keeper that is no old form", len(LEG0) - len(legacy(rg3)) == 4 + 2, (len(LEG0), len(legacy(rg3))))
    check("the marked pages say mark, and the name each reader gets is the one the `agent:` line gave", all((rg3[k]["keeper_source"], rg3[k]["keeper_agent"]) == ("mark", a) for k, a in SUBS.items()), {k: rg3[k] for k in SUBS})

    # (c) every reader answers for a marked page as it did for its `agent:` line: the same rows, names, pages per name, hubs, notices, stand-ins and item keepers
    moved = set(NOBODY)
    same = lambda a, b: {k: v for k, v in a.items() if k not in moved} == {k: v for k, v in b.items() if k not in moved}
    check("(c) the registry's session, role and the names that keep each page are the same before and after, for every page but the two handed back", same(s0["rows"], s3["rows"]), [k for k in s0["rows"] if s0["rows"][k] != s3["rows"].get(k)])
    names0 = {n for n in s0["pages_of"]}
    check("(c) the pages each name keeps (the client's `keeper_pages`) are the same, for every name but the two dead ones and the keeper that gains a handed-back page (forge-builder: forge/old)",
          all(s0["pages_of"][n] == s3["pages_of"].get(n) for n in names0 if n not in ("gone-session", "ghost-two", "forge-builder")) and s3["pages_of"]["forge-builder"] == sorted([*s0["pages_of"]["forge-builder"], "projects/forge/old"]),
          {n: (s0["pages_of"][n], s3["pages_of"].get(n)) for n in names0 if s0["pages_of"][n] != s3["pages_of"].get(n)})
    check("(c) the live sessions keep the very pages they kept (the keeper set of every running name is unchanged)", all(s0["pages_of"][n] == s3["pages_of"][n] for n in LIVE if n in s0["pages_of"]), None)
    check("(c) keepers_any, the pages a name marks (anchors.keeper_pages), and the hubs of every name are the same", all(s0[k][n] == s3[k][n] for k in ("any", "marks_of", "hubs") for n in s0[k] if n not in ("gone-session", "ghost-two")), None)
    check("(c) the notice name, the stand-in and the telling's page keeper and item keeper are the same for every page", all(s0[k][x] == s3[k][x] for k in ("notice", "stand_in", "page_keeper") for x in s0[k]), None)
    check("(c) the item keeper (telling.project_keeper) is the same for every page but the two handed back", all(s0["project_keeper"][x] == s3["project_keeper"][x] for x in s0["project_keeper"] if x not in moved), None)
    check("(c) roles.json and the sessions roles are the same", s0["roles"] == s3["roles"] and s0["sessions"] == s3["sessions"], None)
    check("(c) a marked page differs from its row before it only by the source of its keeper (`keeper_source`, `page_mark`)", all({k: v for k, v in rg3[x].items() if k not in ("keeper_source", "page_mark")}
          == {k: v for k, v in rg0[x].items() if k != "keeper_source"} for x in SUBS), {x: (rg3[x], rg0[x]) for x in SUBS})
    check("(d) every page the pass leaves reads exactly as before: the left pages, the name-line pages, the pages under a retired project and under a mark", all(rg3[k] == rg0[k] for k in rg0
          if k not in (*SUBS, *NOBODY, "projects/forge", "projects/loft")), [k for k in rg0 if rg3[k] != rg0[k] and k not in (*SUBS, *NOBODY, "projects/forge", "projects/loft")])
    old, ghost = rg3["projects/forge/old"], rg3["projects/loft/ghost"]
    check("a dead name handed back: the page follows the keeper above it (the forge's mark), the old line is the legacy name; under a project with no mark its keeper is the derived one",
          (old["session"], old["role"], old["keeper_agent"], old["keeper_source"], old["legacy_session"], old["legacy_role"]) == ("forge-builder", "inherited", "forge-builder", "mark", "gone-session", "agent")
          and (ghost["keeper_agent"], ghost["keeper_source"], ghost.get("role")) == ("loft-main", "derived", None) and "session" not in ghost and ghost["legacy_session"] == "ghost-two", (old, ghost))
    check("the item keeper of a handed-back page is the project's (telling.project_keeper), not the dead session", s3["project_keeper"]["projects/forge/old"] == "forge-builder" and s3["project_keeper"]["projects/loft/ghost"] == "loft-main",
          (s3["project_keeper"]["projects/forge/old"], s3["project_keeper"]["projects/loft/ghost"]))
    check("a handed-back page: the project's keeper gains it, and the dead name still reads it through the `agent:` line (legacy_session), as every mark's old line does: the keeper set only grows",
          "projects/forge/old" in s3["pages_of"]["forge-builder"] and s3["pages_of"].get("gone-session") == ["projects/forge/old"] and s3["pages_of"]["gone-session"] == s0["pages_of"]["gone-session"],
          (s3["pages_of"].get("gone-session"), s3["pages_of"].get("forge-builder")))

    # the published record and the gauge file
    prj.sync(force=True, path=T / "state" / "published.json"); KR.flush()
    pub = json.loads((T / "state" / "published.json").read_text())["projects"]
    pf = pub[ids["projects/forge/plan"]]
    check("the published record says mark for a marked sub-page, with the agent as its keeper", (pf["keeper_source"], pf["keeper_agent"], pf["keeper"]) == ("mark", "forge-main", "forge-main"), pf)
    fr = json.loads((T / "state" / "keeper-reads.json").read_text())
    check("the gauge file counts the legacy rows after the pass", fr["legacy"]["count"] == len(legacy(rg3)) and "projects/forge/plan" not in fr["legacy"]["keys"], fr["legacy"])

    # a second apply writes nothing; the undo puts the record back byte for byte
    mid = tree(*SPACE); undo_dirs = sorted(RUN.iterdir())
    again = ks.run(apply_=True, live=LIVE, run_dir=RUN)
    check("a second apply writes nothing: the pass finds the three left pages only, and says there is nothing to change", again["written"] is False and again["counts"]["changed"] == 0 and any("nothing to change" in l for l in again["lines"]) and tree(*SPACE) == mid
          and sorted(RUN.iterdir()) == undo_dirs, again["lines"][-3:])
    und = rs.restore_undo(ok["undo"], apply=True)
    check("undo --apply: the record is byte for byte what it was before the pass, and the registry reads as it did", recbytes() == ORIG and und.get("changed") is True and R() == rg0, und)
    ud = json.loads(pathlib.Path(ok["undo"]).read_text())
    check("the undo file is the project_restore format of a whole-record change", ud["mode"] == "record", ud)

    # ---- 6. sala's list unreadable: no plan and no write, a dry run included (a wrong "nobody runs under the name" would hand a running session's page to the keeper above it)
    import contextlib, io, shutil
    from stackshot.projects import project_verbs as pv
    from stackshot.router import page_debt
    from stackshot.tools import registry_report as rr
    IO = page_debt.PlainIO()
    pre = tree(*SPACE)
    try:
        ks.build(pr.entries(), prj.registry_raw(), None); raised = False
    except ValueError as e:
        raised = "cannot be read" in str(e)
    check("sala unreadable: building the plan refuses (a ValueError), never reads the missing list as an empty one", raised)
    for apply_ in (False, True):
        r = ks.run(apply_=apply_, live=None, run_dir=RUN)
        check(f"sala unreadable, {'apply' if apply_ else 'dry run'}: refused, no row in the plan, nothing written, no undo file",
              bool(r["refused"]) and r["pages"] == [] and r["written"] is False and r["undo"] is None and tree(*SPACE) == pre and recbytes() == ORIG, r)
    rc, out, err = tool("--run-dir", str(T / "undo-cli"))
    check("cli, sala unreadable, dry run: exit 1, the reason on stderr, no table, nothing written", rc == 1 and "cannot be read" in err and "agent named" not in out and recbytes() == ORIG, (rc, out[-200:], err[-300:]))
    rc, out, err = tool("--apply", "--run-dir", str(T / "undo-cli"), "--json")
    check("cli, sala unreadable, --apply: exit 1, the reason on stderr, no plan on stdout, nothing written, no undo folder", rc == 1 and "cannot be read" in err and out.strip() == "" and recbytes() == ORIG and not (T / "undo-cli").exists(), (rc, out[-200:], err[-300:]))

    # ---- 6b. the command line with a readable sala list (in this process, the list put in place of sala's)
    _rows0 = anchors.sala_rows
    anchors.sala_rows = lambda *a, **k: [{"name": n, "aliases": []} for n in sorted(LIVE)]
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = ks.main(["--run-dir", str(T / "undo-cli")])
        out = buf.getvalue()
        check("cli, dry run: exit 0, the table on stdout, nothing written", rc == 0 and "sub-page" in out and "agent named" in out and "projects/forge/plan" in out and "nothing written (add --apply)" in out and recbytes() == ORIG, (rc, out[-400:]))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = ks.main(["--apply", "--run-dir", str(T / "undo-cli"), "--json"])
        got = json.loads(buf.getvalue()) if buf.getvalue().strip().startswith("{") else {}
        check("cli, --apply --json: exit 0, written, an undo file", rc == 0 and got.get("written") is True and pathlib.Path(got.get("undo") or "/nope").is_file() and recbytes() != ORIG, (rc, buf.getvalue()[-300:]))
        if got.get("undo"):
            rs.restore_undo(got["undo"], apply=True)
    finally:
        anchors.sala_rows = _rows0
    check("cli: the record is back as it was after the undo", recbytes() == ORIG)
    check("cli: the program is listed (`stackshot keeper-subpages`)", cli.PROGRAMS.get("keeper-subpages", ("",))[0] == "stackshot.projects.keeper_subpages", None)

    # ---- 7. nobody loses a page by the readers that look at session and role; a wrong live set is caught; what a session gains is said
    ENTS0, RAW0 = pr.entries(), prj.registry_raw()
    wrong = ks.plan(live=set())                                # a deliberately wrong live set: nothing runs
    wby = {r["key"]: r for r in wrong["pages"]}
    check("a wrong live set (nothing running) would hand back the running session's page: the plan says inherit for it", wby["projects/forge/liveonly"]["action"] == "inherit", wby["projects/forge/liveonly"])
    eff_w = ks.effects(RAW0, ENTS0, wrong["entries"], wrong["pages"], LIVE)
    reg_b, reg_w = R(), pr.apply(RAW0, wrong["entries"])
    old_view = kp.names_of(reg_b["projects/forge/liveonly"]) - kp.names_of(reg_w["projects/forge/liveonly"])
    check("the old reading (the names that keep the page, the legacy line included) sees no loss for that handed-back page", old_view == set(), old_view)
    check("the readers of session and role do: running-sess loses the page and the project's keeper gains it (the effects name it for the true running set)",
          eff_w["live_lose"] == ["running-sess"] and eff_w["lose"].get("running-sess") == 1 and "projects/forge/liveonly" in eff_w["gain_pages"].get("forge-builder", []), eff_w)
    check("... and that wrong plan changes (session, role) of the running session's row, which the right plan never does",
          (reg_w["projects/forge/liveonly"].get("session"), reg_w["projects/forge/liveonly"].get("role")) != (reg_b["projects/forge/liveonly"].get("session"), reg_b["projects/forge/liveonly"].get("role")))
    good = ks.plan(live=LIVE)
    reg_g = pr.apply(RAW0, good["entries"])
    keys_live = [k for k, v in reg_b.items() if isinstance(v, dict) and (v.get("session") in LIVE or kp.names_of(v) & LIVE)]
    check("the right live set: every row of a running name keeps its session and role, and its item keeper",
          all((reg_g[k].get("session"), reg_g[k].get("role"), telling.page_keeper(k, reg_g)) == (reg_b[k].get("session"), reg_b[k].get("role"), telling.page_keeper(k, reg_b)) for k in keys_live) and "projects/forge/liveonly" in keys_live, keys_live)
    eg = dry["effects"]
    check("the effects count losses and gains by those readers: the two dead names lose their page, the project keepers gain them, no running name loses one",
          eg["lose"] == {"gone-session": 1, "ghost-two": 1} and eg["gain_pages"] == {"forge-builder": ["projects/forge/old"], "loft-main": ["projects/loft/ghost"]} and eg["live_lose"] == [], eg)
    check("the dry run says in plain words that a handed-back page follows the keeper above it, by design",
          any("follows the keeper above it, by design" in x for x in dry["lines"]) and any("names that gain pages: forge-builder (1: projects/forge/old)" in x for x in dry["lines"]), dry["lines"])

    # ---- 8. more fixtures: a project that lists no agent (L1), marks held on the wrong or two entries (L2), a mark under a retired project (L4), the verbs that move marks (M1)
    page("projects/flint.md", "type: project\ntitle: Flint\nagents:\n  flint-main: talks\n  flint-docs: keeps the docs\nstatus: active")
    page("projects/flint/a.md", "type: note\ntitle: Flint a\nagent: flint-docs")
    page("projects/flint/b.md", "type: note\ntitle: Flint b\nagent: flint-main")
    page("projects/flint/c.md", "type: note\ntitle: Flint c\nagent: dead-zz")
    page("projects/flint/inner.md", "type: project\ntitle: Flint inner\nagents:\n  inner-main: talks\nstatus: active")
    page("projects/flint/inner/z.md", "type: note\ntitle: Flint inner z\nagent: flint-docs")
    page("projects/lone.md", "type: project\ntitle: Lone\nagents:\n  lone-docs: keeps the docs\nstatus: active")
    page("projects/lone/a.md", "type: note\ntitle: Lone a\nagent: lone-docs")
    page("projects/bare.md", "type: project\ntitle: Bare\ndisplay-name: team-bare\nstatus: active")
    page("projects/bare/x.md", "type: note\ntitle: Bare x\nagent: dead-yy")
    page("projects/mover.md", "type: project\ntitle: Mover\nagents:\n  mover-main: talks\nstatus: active")
    page("projects/mover/a.md", "type: note\ntitle: Mover a\nagent: mover-main")
    p.cmd_registry(quiet=True)
    ids = {k: e["id"] for k, e in raw().items()}
    FL, INNER, LONE, BARE, MV = (ids[f"projects/{k}"] for k in ("flint", "flint/inner", "lone", "bare", "mover"))
    FLAGS = {"flint-main": agent(True, "talks", keeper=True), "flint-docs": agent(True, "keeps the docs")}
    def rec(**extra):
        es = {**ENTRIES, FL: entry("projects/flint", agents=FLAGS), INNER: entry("projects/flint/inner", agents={"inner-main": agent(True, "talks")}),
              LONE: entry("projects/lone", agents={"lone-docs": agent(True, "keeps the docs")}), BARE: entry("projects/bare"),
              MV: entry("projects/mover", agents={"mover-main": agent(True, "talks")})}
        for pid, fields in extra.items():
            es[pid] = {**es[pid], **fields}
        write_record(es)
    def probs(key): return [x for x in (R().get(key) or {}).get("keeper_problems") or [] if x.startswith("page keeper of ")]

    # L1: a project that lists no agent has nothing a handed-back page could follow
    rec()
    pb = ks.plan(live=LIVE); bx = {r["key"]: r for r in pb["pages"]}["projects/bare/x"]
    check("a dead name under a project that lists no agent is left, not handed back (the page would still read an old form), and says why", bx["action"] == "leave" and "lists no agent" in bx["why"], bx)
    check("... the counts take it as left and the plan holds no mark for it", "page_keepers" not in pb["entries"][BARE] and pb["counts"]["leave"] >= 1 and pb["counts"]["inherit"] == 3 and "projects/bare/x" not in [r["key"] for r in pb["pages"] if r["action"] == "inherit"], pb["counts"])
    wr = ks.run(apply_=True, live=LIVE, run_dir=RUN, now="2026-11-01T00:00:00Z")
    check("... and the gauge forecast is the gauge after the write (no page is counted as leaving it that stays)", wr["effects"]["gauge"]["after"] == len(legacy(R())) and "projects/bare/x" in legacy(R()), (wr["effects"]["gauge"], len(legacy(R()))))
    rs.restore_undo(wr["undo"], apply=True)

    # L2: a page's mark lives on the entry of the nearest project above it; a mark held anywhere else is ignored and said; a page marked twice reports the second
    rec(**{FL: {"page_keepers": {"projects/flint/inner/z": "flint-docs"}}})
    check("a mark for a page under an adopted sub-project, held on the outer project's entry, is ignored and said (the page's own line answers)",
          R()["projects/flint/inner/z"]["keeper_source"] == "legacy" and any("nearest project above it is projects/flint/inner" in x for x in probs("projects/flint")), probs("projects/flint"))
    rec(**{FL: {"page_keepers": {"projects/flint/inner/z": "flint-docs"}}, INNER: {"page_keepers": {"projects/flint/inner/z": "flint-docs"}}})
    check("the same mark on the nearest entry is read, and the outer entry's copy is still reported (never a silent win)",
          R()["projects/flint/inner/z"]["keeper_source"] == "mark" and len(probs("projects/flint")) == 1, (R()["projects/flint/inner/z"], probs("projects/flint")))
    rec(**{FL: {"page_keepers": {"projects/flint/b": "flint-main", "projects/flint/b.md": "flint-docs"}}})
    b = R()["projects/flint/b"]
    check("a page marked twice on one entry: the first rules and the second is reported as a problem",
          (b["session"], b["keeper_source"]) == ("flint-main", "mark") and any("marked twice" in x for x in probs("projects/flint")), (b, probs("projects/flint")))

    # L4: a mark under a retired project is read as everywhere (and its problems are not reported as debts, as for the other marks)
    rec(**{OLD: {"page_keepers": {"projects/old-one/sub": "loft-main"}}})
    ob = R()["projects/old-one/sub"]
    check("a mark under a retired project is read: mark, role agent, the named agent, no problem line", (ob["keeper_source"], ob["role"], ob["session"]) == ("mark", "agent", "loft-main") and probs("projects/old-one") == [], (ob, probs("projects/old-one")))

    # an ignored mark is a debt of the registry check, with the line to fix
    rec(**{FL: {"page_keepers": {"projects/flint/c": "ghost-zz", "projects/flint/a": "flint-docs"}}})
    dd = [f for f in rr.keeper_debts(pr.entries(), prj.registry_raw(), R()) if f["line"] == rr.LINE_KEEPER_PAGE]
    check("registry check: a sub-page mark that is not read is the debt keeper-page-ignored, one per project, naming the page and the way to fix it",
          len(dd) == 1 and "projects/flint/c" in dd[0]["name"] and "page_keepers" in dd[0]["fix"], dd)
    rec(**{FL: {"page_keepers": {"projects/flint/a": "flint-docs"}}})
    check("registry check: a mark that is read is no debt", [f for f in rr.keeper_debts(pr.entries(), prj.registry_raw(), R()) if f["line"] == rr.LINE_KEEPER_PAGE] == [])

    # M1: the verbs carry the marks the way the project's own mark moves
    rec(**{FL: {"page_keepers": {"projects/flint/a": "flint-docs", "projects/flint/b": "flint-main"}}, LONE: {"page_keepers": {"projects/lone/a": "lone-docs"}},
           MV: {"page_keepers": {"projects/mover/a": "mover-main"}}})
    marks = lambda pid: pr.entries()[pid].get("page_keepers")
    r = pv.agent_rename("projects/flint", "flint-docs", "flint-notes", io=IO, by="lone-session")
    p.cmd_registry(quiet=True)
    check("agent-rename: the sub-page marks that name the old name name the new one, and the page reads as marked by it",
          marks(FL) == {"projects/flint/a": "flint-notes", "projects/flint/b": "flint-main"} and r.get("page_marks") == {"renamed": ["projects/flint/a"]}
          and (R()["projects/flint/a"]["session"], R()["projects/flint/a"]["keeper_source"]) == ("flint-notes", "mark") and probs("projects/flint") == [], (marks(FL), r.get("page_marks"), probs("projects/flint")))
    r = pv.agent_retire("projects/flint", "flint-notes", io=IO, by="lone-session")
    p.cmd_registry(quiet=True)
    check("agent-retire: the sub-page marks of the leaver go where the project's mark goes (the builder, else the -main agent), and the answer says so",
          marks(FL) == {"projects/flint/a": "flint-main", "projects/flint/b": "flint-main"} and r.get("page_marks") == {"moved": ["projects/flint/a"], "to": "flint-main"}
          and R()["projects/flint/a"]["session"] == "flint-main" and probs("projects/flint") == [], (marks(FL), r.get("page_marks")))
    r = pv.agent_rename("projects/flint", "flint-main", "flint-lead", io=IO, by="lone-session")
    p.cmd_registry(quiet=True)
    check("agent-rename of the project's keeper: the project mark and every sub-page mark follow the new name",
          marks(FL) == {"projects/flint/a": "flint-lead", "projects/flint/b": "flint-lead"} and pr.entries()[FL]["agents"]["flint-lead"].get("keeper") is True and probs("projects/flint") == [], (marks(FL), r.get("page_marks")))
    r = pv.agent_retire("projects/lone", "lone-docs", io=IO, by="lone-session")
    p.cmd_registry(quiet=True)
    check("agent-retire with no agent left: the sub-page marks are removed (never left naming a retired agent), the answer and the warning say so, and the page reads from its own `agent:` line again",
          marks(LONE) is None and r.get("page_marks", {}).get("cleared") == ["projects/lone/a"] and "sub-page" in (r.get("warning") or "") and R()["projects/lone/a"]["keeper_source"] == "legacy", (marks(LONE), r))
    def runner(args):
        ph, pair = args[0], args[1]; o, n = pair.split("=")
        if ph == "copy":
            for src in [BRAIN / (o + ".md"), *sorted((BRAIN / o).rglob("*.md"))]:
                dst = BRAIN / (n + str(src.relative_to(BRAIN))[len(o):])
                dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy(src, dst)
        return 0, f"{ph} ok"
    r = pv.move_page("projects/mover", "projects/mover2", runner=runner, io=IO, by="lone-session")
    p.cmd_registry(quiet=True)
    check("move-page: the sub-page marks name the pages under the new key", marks(MV) == {"projects/mover2/a": "mover-main"} and r["moved"] is True, (marks(MV), r.get("moved")))
    m2 = R().get("projects/mover2/a") or {}
    check("move-page: the moved page reads as marked, and no problem line says a mark is ignored", (m2.get("keeper_source"), m2.get("session")) == ("mark", "mover-main") and probs("projects/mover2") == [], (m2, probs("projects/mover2")))

    # ---- 9. a session sala renamed: the page's `agent:` line names the old name; the pass maps it through the rename log and marks the page with the new name
    from stackshot.fleet import renamed_agents as ra
    def attempt(fn, *a, **k):
        """A call the code under test may not take yet (a keyword it does not know): the TypeError becomes a failing check, not a crash of the whole suite."""
        try:
            return fn(*a, **k)
        except TypeError as e:
            return {"typeerror": str(e), "pages": [], "counts": {}, "effects": {}, "lines": [], "written": False, "refused": "", "undo": None, "entries": {}}
    page("projects/rn.md", "type: project\ntitle: Rn\nagents:\n  new-ax: talks\n  new-plat: builds\n  new-eng: keeps the docs\n  new-1: talks\n  kept-old: talks\n  kept-new: talks\n  rn-main: talks\nstatus: active")
    page("projects/rn2.md", "type: project\ntitle: Rn two\nagents:\n  new-qa: talks\n  rn2-main: talks\nstatus: active")
    for k, a in (("a", "old-ax"), ("b", "old-qa"), ("c", "old-plat"), ("d", "old-eng"), ("e", "old-1"), ("f", "loop-a"), ("g", "old-nm"), ("h", "kept-old"), ("i", "plain-dead"), ("j", "rn-main")):
        page(f"projects/rn/{k}.md", f"type: note\ntitle: Rn {k}\nagent: {a}")
    p.cmd_registry(quiet=True)
    ids = {k: e["id"] for k, e in raw().items()}
    RN, RN2 = ids["projects/rn"], ids["projects/rn2"]
    write_record({**ENTRIES, RN: entry("projects/rn", agents={n: agent(True, "talks") for n in ("new-ax", "new-plat", "new-eng", "new-1", "kept-old", "kept-new", "rn-main")}),
                  RN2: entry("projects/rn2", agents={"new-qa": agent(True, "talks"), "rn2-main": agent(True, "talks")})})
    ORIG9 = recbytes()
    # sala's rows: four renames (the old name is an alias of the session that has the new one, and the `agent:` line still holds it), a name renamed that a map still lists (kept-old), and a rename onto
    # a name on no map (old-nm -> new-nm); the other sessions are listed under their names alone
    ROWS = [{"name": "new-ax", "aliases": ["old-ax"]}, {"name": "new-qa", "aliases": ["old-qa"]}, {"name": "new-plat", "aliases": ["old-plat"]}, {"name": "new-eng", "aliases": ["old-eng"]},
            {"name": "kept-new", "aliases": ["kept-old"]}, {"name": "new-nm", "aliases": ["old-nm"]}, {"name": "rn-main"}, {"name": "rn2-main"}, *({"name": n} for n in sorted(LIVE))]
    LIVE9 = set().union(*anchors.sessions_of(ROWS))
    REN = ra.renames_of(ROWS)
    check("fixture: the rename log of the rows holds the six renames, the old names being aliases and no session's name",
          REN == {"old-ax": "new-ax", "old-qa": "new-qa", "old-plat": "new-plat", "old-eng": "new-eng", "kept-old": "kept-new", "old-nm": "new-nm"}, REN)
    def rows9(r): return {x["key"]: x for x in r["pages"]}
    before = tree(*SPACE)
    d9 = attempt(ks.run, live=LIVE9, renames=REN, run_dir=RUN)
    b9 = rows9(d9)
    check("renames: the dry run writes nothing (the record, the pages, the state)", tree(*SPACE) == before and recbytes() == ORIG9, d9.get("typeerror"))
    for k, old, new, where in (("a", "old-ax", "new-ax", "own map"), ("c", "old-plat", "new-plat", "own map"), ("d", "old-eng", "new-eng", "own map"), ("b", "old-qa", "new-qa", "map of projects/rn2")):
        r = b9.get(f"projects/rn/{k}", {})
        check(f"renames: a page naming {old} is marked with {new} ({where}), and the table says it was renamed",
              r.get("action") == "mark" and r.get("agent") == new and r.get("where") == f"renamed from {old}: {where}", r or d9.get("typeerror"))
    check("renames: the table line carries the new name, the action and the old name", any(re.search(r"projects/rn/a\s+new-ax\s+mark\s+renamed from old-ax: own map", l) for l in d9["lines"]), d9["lines"])
    plan9 = attempt(ks.plan, live=LIVE9, renames=REN)
    pk9 = (plan9["entries"].get(RN) or {}).get("page_keepers") or {}
    check("renames: the plan's marks hold the new names only", pk9.get("projects/rn/a") == "new-ax" and (plan9["entries"].get(RN2) or {}).get("page_keepers") is None and "old-ax" not in json.dumps(plan9["entries"])
          and (plan9["entries"].get(RN) or {}).get("page_keepers", {}).get("projects/rn/b") == "new-qa", plan9.get("typeerror") or pk9)
    ch = rows9(attempt(ks.run, live=LIVE9 | {"mid-1"}, renames={**REN, "old-1": "mid-1", "mid-1": "new-1"}, run_dir=RUN)).get("projects/rn/e", {})
    check("renames: a chain of two renames (old-1, then mid-1) marks with the newest name and says where it started", ch.get("action") == "mark" and ch.get("agent") == "new-1" and ch.get("where") == "renamed from old-1: own map", ch)
    lp = rows9(attempt(ks.run, live=LIVE9 | {"loop-b"}, renames={**REN, "loop-a": "loop-b", "loop-b": "loop-a"}, run_dir=RUN)).get("projects/rn/f", {})
    check("renames: a loop in the log ends, and the page is left (never marked, never handed back), the reason naming the loop", lp.get("action") == "leave" and "loop" in lp.get("where", "") + lp.get("why", ""), lp)
    nm = b9.get("projects/rn/g", {})
    check("renames: a rename onto a name on no map leaves the page and names both the old and the new name", nm.get("action") == "leave" and "old-nm" in nm.get("where", "") + nm.get("why", "") and "new-nm" in nm.get("where", "") + nm.get("why", ""), nm)
    kp9 = b9.get("projects/rn/h", {})
    check("renames: a name that is a rename source and is still on a map needs no mapping: the page is marked with the name it names, as before", kp9.get("action") == "mark" and kp9.get("agent") == "kept-old" and kp9.get("where") == "own map", kp9)
    pd = b9.get("projects/rn/i", {})
    check("renames: a name that is neither on a map nor a rename source is a dead name, handed back as before", pd.get("action") == "inherit" and pd.get("where") == "nowhere", pd)
    check("renames: a page naming an agent of the map is marked as before", b9.get("projects/rn/j", {}).get("action") == "mark" and b9["projects/rn/j"]["where"] == "own map", b9.get("projects/rn/j"))
    rn_marks = [r for r in d9["pages"] if r["key"].startswith("projects/rn/") and r["action"] == "mark"]
    check("renames: the dry run counts the renamed pages as marks (four), one of them under another project's map",
          d9["counts"].get("renamed") == 4 and len(rn_marks) == 6 and sum(1 for r in rn_marks if r["where"] != "own map" and not r["where"].endswith(": own map")) == 1, (d9["counts"], [(r["key"], r["where"]) for r in rn_marks]))
    check("renames: a rename moves no page from one session to another: no running session loses a page and no old name is counted as one that loses",
          d9["effects"].get("live_lose") == [] and not {"old-ax", "old-qa", "old-plat", "old-eng"} & set(d9["effects"].get("lose", {})), d9["effects"] or d9.get("typeerror"))
    check("renames: the text says how many pages name a renamed session and that the `agent:` lines stay", any("renamed" in l and "agent:" in l and "stay" in l for l in d9["lines"]), d9["lines"])
    GAIN = {"new-ax": ["projects/rn/a"], "new-qa": ["projects/rn/b"], "new-plat": ["projects/rn/c"], "new-eng": ["projects/rn/d"]}
    check("renames: the new names of the renamed sessions are listed as gaining the pages they are now the agent of (the readers ask the name on the row)",
          all(d9["effects"]["gain_pages"].get(n) == pg and d9["effects"]["gain"].get(n) == 1 for n, pg in GAIN.items())
          and all(re.search(rf"names that gain pages:.*{n} \(1: {pg[0]}\)", "\n".join(d9["lines"])) for n, pg in GAIN.items()), (d9["effects"]["gain_pages"], [l for l in d9["lines"] if "gain pages" in l]))

    # the rename log cannot be read: no plan and nothing written, as with an unreadable list of sessions
    for apply_ in (False, True):
        r = attempt(ks.run, apply_=apply_, live=LIVE9, renames=None, run_dir=RUN)
        check(f"renames unreadable, {'apply' if apply_ else 'dry run'}: refused naming the rename log, no row, nothing written, no undo file",
              "rename" in r.get("refused", "") and r["pages"] == [] and r["written"] is False and r["undo"] is None and recbytes() == ORIG9 and tree(*SPACE) == before, r)
    try:
        ks.build(pr.entries(), prj.registry_raw(), LIVE9, None); raised = False
    except ValueError as e:
        raised = "rename" in str(e)
    except TypeError:
        raised = False
    check("renames unreadable: building the plan refuses with a ValueError naming the rename log", raised)
    _rows1, _ren1 = anchors.sala_rows, ra.renames_of
    anchors.sala_rows = lambda *a, **k: [dict(x) for x in ROWS]
    def _damaged(rows): raise RuntimeError("the rename log is damaged")
    ra.renames_of = _damaged
    try:
        for args in (["--run-dir", str(T / "undo-cli9")], ["--apply", "--run-dir", str(T / "undo-cli9"), "--json"]):
            buf, ebuf = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(ebuf):
                rc = ks.main(args)
            check(f"cli, rename log unreadable ({args[0]}): exit 1, the reason on stderr, no table on stdout, nothing written, no undo folder",
                  rc == 1 and "rename" in ebuf.getvalue() and buf.getvalue().strip() == "" and recbytes() == ORIG9 and not (T / "undo-cli9").exists(), (rc, buf.getvalue()[-200:], ebuf.getvalue()[-300:]))
    finally:
        anchors.sala_rows, ra.renames_of = _rows1, _ren1
    # sala lists sessions and no row carries an `aliases` field (an old or stripped sala): nothing could be told renamed, so the pass refuses; an empty list is read as it was
    check("rename_log: rows without any `aliases` field are no readable log; rows with the field, or no rows at all, are", ks.rename_log([{"name": "a"}, {"name": "b"}], ra.renames_of) is None
          and ks.rename_log(None, ra.renames_of) is None and ks.rename_log([], ra.renames_of) == {} and ks.rename_log([{"name": "a", "aliases": []}], ra.renames_of) == {}
          and ks.rename_log(ROWS, ra.renames_of) == REN and ks.rename_log(ROWS, _damaged) is None)
    for what, rows_, want in (("no row has an aliases field", [{"name": n} for n in sorted(LIVE9)], 1), ("an empty list", [], 0)):
        anchors.sala_rows = lambda *a, _r=rows_, **k: list(_r)
        try:
            buf, ebuf = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(ebuf):
                rc = ks.main(["--run-dir", str(T / "undo-cli9")])
        finally:
            anchors.sala_rows = _rows1
        check(f"cli, {what}: " + ("exit 1, the rename log named on stderr, no table, nothing written" if want else "read as it was: exit 0, a plan, nothing written"),
              rc == want and recbytes() == ORIG9 and ((("rename" in ebuf.getvalue()) and buf.getvalue().strip() == "") if want else "agent named" in buf.getvalue()), (rc, buf.getvalue()[-200:], ebuf.getvalue()[-300:]))

    # the apply: the new names are written and nothing else, the page's `agent:` line is not touched, the gauge falls by the right count, a second apply changes nothing
    leg_before = legacy(R())
    pages_before = {f"projects/rn/{x}": (BRAIN / f"projects/rn/{x}.md").read_bytes() for x in "abcdefghij"}
    ap9 = attempt(ks.run, apply_=True, live=LIVE9, renames=REN, run_dir=RUN, now="2026-11-01T00:00:00Z")
    check("renames: apply writes, with an undo file", ap9["written"] is True and ap9["refused"] == "" and ap9["undo"] and pathlib.Path(ap9["undo"]).is_file(), ap9.get("typeerror") or ap9["lines"][-3:])
    pk = (json.loads(recbytes())["projects"][RN].get("page_keepers") or {})
    check("renames: the record holds the new names, never an old one; the name a map still lists as it was; the dead name handed back with an empty name",
          (pk.get("projects/rn/a"), pk.get("projects/rn/b"), pk.get("projects/rn/c"), pk.get("projects/rn/d"), pk.get("projects/rn/h"), pk.get("projects/rn/i")) == ("new-ax", "new-qa", "new-plat", "new-eng", "kept-old", "")
          and not {"old-ax", "old-qa", "old-plat", "old-eng", "old-nm"} & set(pk.values()), pk)
    check("renames: not a page changed (the `agent:` lines keep the old names)", all((BRAIN / f"{k}.md").read_bytes() == v for k, v in pages_before.items()), None)
    leg_after = legacy(R())
    gone = {k for k in leg_before if k not in leg_after}
    check("renames: the gauge falls by exactly the pages marked and handed back, each renamed page is no longer legacy, and the forecast was right",
          len(leg_before) - len(leg_after) == ap9["counts"].get("mark", -1) + ap9["counts"].get("inherit", -1) > 0 and {"projects/rn/a", "projects/rn/b", "projects/rn/c", "projects/rn/d"} <= gone
          and ap9["effects"].get("gauge") == {"before": len(leg_before), "after": len(leg_after)}, (len(leg_before), len(leg_after), ap9["counts"]))
    rgr = R()
    check("renames: a renamed page reads as marked by the new name", all((rgr[f"projects/rn/{k}"]["session"], rgr[f"projects/rn/{k}"]["keeper_source"], rgr[f"projects/rn/{k}"]["role"]) == (n, "mark", "agent")
          for k, n in (("a", "new-ax"), ("b", "new-qa"), ("c", "new-plat"), ("d", "new-eng"))), {k: rgr[k] for k in rgr if k.startswith("projects/rn/")})
    check("renames: the apply's own text lists the new names that gain pages, and the readers agree: the new name keeps the page by its row, the old name no longer reads it",
          all(re.search(rf"names that gain pages:.*{n} \(1: {pg[0]}\)", "\n".join(ap9["lines"])) for n, pg in GAIN.items())
          and all(p.keeper_pages("", n) == pg for n, pg in GAIN.items()) and not any(p.keeper_pages("", o) for o in ("old-ax", "old-qa", "old-plat", "old-eng")),
          ([p.keeper_pages("", n) for n in GAIN], [p.keeper_pages("", o) for o in ("old-ax", "old-qa", "old-plat", "old-eng")]))
    check("renames: the page whose rename leads to no map stays legacy (left)", "projects/rn/g" in leg_after, leg_after)
    mid9 = tree(*SPACE); dirs9 = sorted(RUN.iterdir())
    again9 = attempt(ks.run, apply_=True, live=LIVE9, renames=REN, run_dir=RUN)
    check("renames: a second apply changes nothing: nothing to change, not a byte differs, no second undo folder", again9["written"] is False and again9["counts"].get("changed") == 0 and tree(*SPACE) == mid9 and sorted(RUN.iterdir()) == dirs9,
          again9.get("typeerror") or again9["lines"][-3:])
    if ap9["undo"]:
        rs.restore_undo(ap9["undo"], apply=True)
    check("renames: the undo puts the record back byte for byte", recbytes() == ORIG9)

if fails: print(f"FAILED: keeper subpage scenario, {len(ran)} checks, {len(fails)} failed"); sys.exit(1)
print(f"ok: keeper subpage scenario, {len(ran)} checks")
