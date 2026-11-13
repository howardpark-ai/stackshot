"""Scenario test for the project record's entries (project_registry.py, tools/migrate_project_record.py): the record is read first and the page lines are the fallback — fixture data,
no live store, no network, no server process (the server module is imported and called in-process, on a temporary config).

Covers: the entry schema and its validation; the registry's readers (projects.py, anchors.py, pages.py, the server's registry reads and the client API's registry) returning the same
values with and without the entries that the migration writes (the current live shape); the record read first (title, name, status, hub, agents and their order, scope) with a page
line for every field an entry does not hold, and for a project that has no entry; a project with no page (no crash in any reader, the item gate accepting it and storing its id) and
one whose pointer is a link elsewhere or a page that does not resolve (still refused); former keys and former names resolving to the project, through a page move and a swap; a damaged
section answered by the pages; the migration (dry run on a copy writes nothing, apply with the undo copy written first, undo, a second pass that is a no-op, the pending agents kept by default, cleared only on request and only for a retired project);
the order of an agents map surviving a rewrite of the file.

    tests/run-suite project_registry        → exit 0 / 1"""
import hashlib, io, json, logging, os, pathlib, re, shutil, subprocess, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="prjregtest-"); T = pathlib.Path(tmp)
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
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "brain/infra", "secrets"): (T / d).mkdir(parents=True)
NAMES = ("home-sparrow", "home-sparrow-main", "home-sparrow-docs", "home-sparrow-engineer", "home-zeta", "home-zeta-main", "home-nopage-main", "home-sparrow-x")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in U.items()}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
page("projects/alpha.md", "type: project\ntitle: Alpha\ndisplay-name: home-sparrow\nagents:\n  home-sparrow-main: talks to Oliver\n  home-sparrow-docs: keeps the docs\n"
                          "  background:\n    home-sparrow-engineer: builds and merges\nstatus: active")
page("projects/alpha/sub.md", "type: project\ntitle: Sub")
page("projects/zeta.md", "type: project\ntitle: Zeta\ndisplay-name: home-zeta\nstatus: completed\naliases:\n  - projects/zed")
page("ops/zeta-tool.md", "type: note\ntitle: Zeta tool\ndisplay-name: home-zeta\nhub: projects/zeta")
page("projects/gamma.md", "type: project\ntitle: Gamma\nagents:\n  home-gamma-main: does it\nstatus: draft")
page("projects/plain-note.md", "type: note\ntitle: A note")
page("projects/old-alpha.md", "type: redirect\ntitle: moved\nredirect_to: projects/alpha")
page("projects/older-alpha.md", "type: redirect\ntitle: moved\nredirect_to: projects/old-alpha")
page("projects/old-note.md", "type: redirect\ntitle: moved\nredirect_to: ops/zeta-tool")
page("projects/lost-stub.md", "type: redirect\ntitle: moved\nredirect_to: projects/nowhere")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))
def reg(): return json.loads((T / "store/projects.json").read_text())["pages"]
REC = T / "store/project-record.json"
def recfile(): return json.loads(REC.read_text())
def sha(b): return hashlib.sha256(b).hexdigest()
TOOL = [sys.executable, f"{STACK}/stackshot/tools/migrate_project_record.py"]
def tool(*args, store=None):
    r = subprocess.run(TOOL + list(args), capture_output=True, text=True, env=os.environ, cwd=str(T))
    return r.returncode, r.stdout, r.stderr

from stackshot.projects import pages as p; from stackshot.projects import projects as prj; from stackshot.projects import project_registry as pr; from stackshot.anchors import anchors; from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.web.tools import create as _wt_create; from stackshot.model import ids as _model_ids
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
p.cmd_registry(quiet=True)
ids = {k: e["id"] for k, e in reg().items()}
A, A_SUB, Z, G = (ids[k] for k in ("projects/alpha", "projects/alpha/sub", "projects/zeta", "projects/gamma"))
prj.add_pending(A, "home-sparrow-x", {"front": True, "role": "x", "mandate_line": "a pending one"}, by="home-sparrow-main", at="2026-11-01T00:00:00Z")
prj.add_pending(Z, "home-zeta-old", {"front": False, "role": "old", "mandate_line": "a stale one"}, by="home-zeta-main", at="2026-10-01T00:00:00Z")

# What the readers say, in one value: the registry's readers of every module, the published record, the picker, the client API.
FIELDS = ("title", "type", "session", "role", "status", "hub", "agents", "back_agents", "owed_agents")
def snap():
    R = prj.registry(); AR = anchors.registry()
    lay = lambda reg_: {k: ({f: e.get(f) for f in FIELDS}, list(e.get("agents") or {}), list(e.get("back_agents") or {})) for k, e in reg_.items()}
    client = json.loads(server._client_get("registry", {})[2])["pages"]
    return {"projects": lay(R), "anchors": lay(AR), "pages": lay(p.load_registry()), "server": lay(server._registry("projects")), "client": lay(client),
            "name_lines": {k: (anchors.name_line(k, AR), anchors.hub_of(k, AR), anchors.main_of(e), anchors.front_agents(e)) for k, e in AR.items()},
            "roles": anchors.session_roles(AR, set()), "file_roles": anchors.file_roles(AR, set()), "with_pending": lay(prj.with_pending(prj.registry())),
            "agent_gap": {k: prj.agent_gap(k, e, R) for k, e in R.items()}, "build": prj.build(), "list": prj.list_projects(), "hidden": prj.list_projects(q="a"),
            "refs": {i: prj.ref(i) for i in ids.values()}}
S0 = snap()
check("baseline: the registry has the four projects and the notes, each with an id", len(ids) == 6 and all(prj.is_id(i) for i in ids.values()), ids)
check("baseline: no entries yet: the entries are empty and the registry is the pages' own", pr.entries() == {} and prj.registry() == prj.registry_raw() and "scope" not in prj.registry()["projects/alpha"])
before = REC.read_bytes()
check("baseline: a pending agent is in the record, shown as the page's owed line", "home-sparrow-x" in S0["build"]["projects"][A]["agents"] and S0["build"]["projects"][A]["agents"]["home-sparrow-x"].get("page_owed") is True)

# ---- 1. the entry schema
GOOD = {"name": "home-x", "title": "X", "type": "project", "scope": "home", "status": "active", "agents": {"b": {"front": True, "mandate_line": "m"}}, "hub": "", "page": "projects/x",
        "former_keys": ["projects/y"], "former_names": ["old"], "made": {"at": "2026-11-05T00:00:00Z", "by": "migration", "how": "migrated"}}
X = "prj_0000000a"
def bad(**ch): return {**GOOD, **ch}
def parse_err(sec, **doc):
    try: pr.parse({"projects": sec, **doc}); return ""
    except ValueError as e: return str(e)
check("schema: a complete entry parses, and a file with no section has no entries", pr.parse({"projects": {X: GOOD}}) == {X: GOOD} and pr.parse({"schema": 1, "ids": {}}) == {})
check("schema: an entry with only what it holds is valid (every field is optional)", pr.parse({"projects": {X: {}}}) == {X: {}})
for label, sec, doc in (("a status that is neither active nor archived", {X: bad(status="done")}, {}), ("retired on an active project", {X: bad(retired={"at": "t", "by": "b", "how": "made"})}, {}),
                        ("a how that is none of made, adopted, migrated", {X: bad(status="archived", retired={"at": "t", "by": "b", "how": "guessed"})}, {}),
                        ("an agent with no front flag", {X: bad(agents={"b": {"mandate_line": "m"}})}, {}), ("former_keys not a list", {X: bad(former_keys="projects/y")}, {}),
                        ("an id that is no id", {"x": GOOD}, {}), ("a name that is not a string", {X: bad(name=3)}, {}), ("a section that is not an object", [], {}),
                        ("a section schema this code does not read", {X: GOOD}, {"projects_schema": 2})):
    check(f"schema: refused, naming the problem: {label}", parse_err(sec, **doc) != "", label)

# ---- 2. the migration: a dry run on a copy writes nothing
shutil.copytree(T / "store", T / "copy-store"); (T / "copy-state").mkdir()
copy_before = {f.name: sha(f.read_bytes()) for f in (T / "copy-store").iterdir() if f.is_file()}
rc, out, err = tool("--store", str(T / "copy-store"), "--state", str(T / "copy-state"), "--brain", str(T / "brain"))
check("migration, dry run: exit 0, says nothing was written", rc == 0 and "nothing written" in err, (rc, err))
check("migration, dry run: counts — 4 projects of type project, one of them a sub-page that gets no entry; 3 entries, 2 active and 1 archived", "registry: 6 pages, 4 of type project, 1 of them sub-pages (never projects: no entry)" in out
      and "entries to write: 3; already in the record: 0; no id yet: 0" in out and "status: 2 active, 1 archived" in out, out)
check("migration, dry run: former keys from the stubs (a chain is followed) and the aliases; a stub to no live page is counted", "former keys: 3 on 2 projects" in out and "4 redirect stubs, 1 of them leading to no live page; 1 aliases" in out, out)
check("migration, dry run: the default folds the pending agent of the active project into its entry and clears the retired project's, each listed with who and when", "pending agent folded into its project and cleared: projects/alpha" in out
      and "home-sparrow-x" in out and "pending agent to clear: projects/zeta" in out and "home-zeta-old" in out and "by='home-zeta-main'" in out and "1 pending agents folded into their projects and 2 cleared" in err, (out, err))
rc, outc, errc = tool("--store", str(T / "store"), "--state", str(T / "state"), "--brain", str(T / "brain"), "--keep-pending")
check("migration, dry run with --keep-pending: both pending agents are listed as kept, none is folded or cleared", "pending agent kept (kept on request): projects/alpha" in outc and "pending agent kept (kept on request): projects/zeta" in outc
      and "pending agent to clear" not in outc and "0 pending agents folded into their projects and 0 cleared" in errc, (outc, errc))
rc, outh, errh = tool("--help")
check("migration, --help: names --keep-pending as the opt-out, and no longer says to wait for the writers", "--keep-pending" in outh and "--clear-pending" not in outh and "DO NOT RUN" not in outh, outh)
check("migration, dry run: the copy and the store are byte for byte as they were, the copy's state dir is empty", {f.name: sha(f.read_bytes()) for f in (T / "copy-store").iterdir() if f.is_file()} == copy_before
      and REC.read_bytes() == before and not any((T / "copy-state").iterdir()))
rc, out2, err2 = tool("--store", str(T / "copy-store"), "--state", str(T / "copy-state"), "--brain", str(T / "brain"), "--apply", "--keep-pending", "--run-dir", str(T / "copy-runs"))
cp = json.loads((T / "copy-store/project-record.json").read_text())
check("migration, apply on a copy: the copy gets the entries, the store the test uses does not", rc == 0 and len(cp["projects"]) == 3 and cp["projects_schema"] == 1 and "projects" not in recfile() and REC.read_bytes() == before, (rc, err2))
shutil.rmtree(T / "copy-store"); shutil.rmtree(T / "copy-state"); shutil.rmtree(T / "copy-runs")

# ---- 3. apply --keep-pending (a live-shaped pending agent: an active project, a running session): no reader's value changes
RUNS = T / "runs"
rc, out, err = tool("--apply", "--keep-pending", "--run-dir", str(RUNS))
runs = sorted(RUNS.iterdir()) if RUNS.exists() else []
check("migration, apply: exit 0, one undo folder with the undo file and the previous record file", rc == 0 and len(runs) == 1 and (runs[0] / "undo.json").exists() and (runs[0] / "project-record.before.json").exists(), (rc, err, runs))
check("migration, apply: the undo copy is the record as it was, whole", (runs[0] / "project-record.before.json").read_bytes() == before)
R1 = recfile(); E = R1["projects"]
check("migration, apply: an entry for each top-level project of type project and for nothing else (the sub-page gets none), keyed by the id the project had", set(E) == {A, Z, G} and A_SUB not in E and R1["projects_schema"] == 1 and R1["schema"] == 1, sorted(E))
check("migration, apply: the older tables are as they were (ids, marks), the pending agents kept", R1["ids"] == json.loads(before)["ids"] and R1.get("pending_agents") == json.loads(before)["pending_agents"])
check("migration, apply: alpha — page, title, name, status, hub, agents in the page's order with the background one not front", E[A]["page"] == "projects/alpha" and E[A]["title"] == "Alpha" and E[A]["name"] == "home-sparrow"
      and E[A]["status"] == "active" and E[A]["hub"] == "" and list(E[A]["agents"]) == ["home-sparrow-main", "home-sparrow-docs", "home-sparrow-engineer"]
      and [a["front"] for a in E[A]["agents"].values()] == [True, True, False] and E[A]["agents"]["home-sparrow-docs"]["mandate_line"] == "keeps the docs", E[A])
check("migration, apply: former keys from the stubs (older-alpha → old-alpha → alpha is followed) and from the alias line", E[A]["former_keys"] == ["projects/old-alpha", "projects/older-alpha"] and E[Z]["former_keys"] == ["projects/zed"]
      and E[G]["former_keys"] == [] and E[A]["former_names"] == [], (E[A]["former_keys"], E[Z]["former_keys"]))
check("migration, apply: zeta (status completed) is archived with a retired stamp; a draft page is active; made says migrated by the migration", E[Z]["status"] == "archived" and E[Z]["retired"]["how"] == "migrated"
      and E[G]["status"] == "active" and "retired" not in E[G] and E[A]["made"]["how"] == "migrated" and E[A]["made"]["by"] == "migration" and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", E[A]["made"]["at"]), (E[Z], E[G]))
check("migration, apply: a page with a display-name has the name; one with only an agents map has none (the page's own lines still answer)", "name" in E[A] and "name" in E[Z] and "name" not in E[G])
check("migration, apply: nothing of a note is migrated, and a stub that leads to a note makes no entry", ids["ops/zeta-tool"] not in E and ids["projects/plain-note"] not in E)
S1 = snap()
def differ(a, b):
    if isinstance(a, dict) and isinstance(b, dict): return [(k, differ(a.get(k), b.get(k))) for k in set(a) | set(b) if a.get(k) != b.get(k)][:2]
    return (a, b)
for k in S0: check(f"same values with the entries as without: {k}", S1[k] == S0[k], differ(S0[k], S1[k]))
LIVE = "home-sparrow-x"
check("a pending agent on an active project with a running session survives the apply in every view: roles, file roles, with_pending, the build, ref, agent gap",
      LIVE in S1["roles"] and LIVE in str(S1["file_roles"]) and LIVE in S1["with_pending"]["projects/alpha"][0]["agents"] and S1["with_pending"]["projects/alpha"][0]["owed_agents"].get(LIVE) == "x"
      and S1["build"]["projects"][A]["agents"][LIVE].get("page_owed") is True and LIVE in S1["refs"][A]["agents"] and LIVE in R1["pending_agents"][A], (S1["roles"], S1["refs"][A]["agents"]))
check("…the registry file the pages wrote was not touched, the entries are laid over it at read time", "scope" not in reg()["projects/alpha"] and "scope" in prj.registry()["projects/alpha"])

# ---- 3b. documented behaviour, pinned: once an entry exists it wins field by field, so an edit made on the page is ignored (the verbs write the record and mirror it to the page, which restores a mirrored line)
PG = T / "brain/projects/alpha.md"; page_text = PG.read_text(encoding="utf-8")
PG.write_text(page_text.replace("title: Alpha", "title: Alpha, edited on the page").replace("status: active", "status: archived").replace("  home-sparrow-docs: keeps the docs", "  home-sparrow-docs: keeps the docs\n  home-sparrow-newcomer: a new agent"), encoding="utf-8")
p.cmd_registry(quiet=True)
rawa = prj.registry_raw()["projects/alpha"]; ra = prj.registry()["projects/alpha"]
check("precondition: the page's own registry row carries the edit (title, status, a new agent)", rawa["title"] == "Alpha, edited on the page" and rawa["status"] == "archived" and "home-sparrow-newcomer" in rawa["agents"], rawa)
check("precondition: with an entry the registry ignores all three: the old title, still active, no new agent (so spawn's name-on-the-map check would refuse the newcomer and a retire on the page would leave the project live)",
      ra["title"] == "Alpha" and ra["status"] == "active" and "home-sparrow-newcomer" not in ra["agents"] and "home-sparrow-newcomer" not in anchors.registry()["projects/alpha"]["agents"]
      and prj.ref(A)["retired"] is False, ra)
PG.write_text(page_text, encoding="utf-8"); p.cmd_registry(quiet=True)
check("precondition: the page put back, the registry reads as it did before the edit", snap() == S1)

# ---- 4. undo restores the file; a second pass is a no-op
rc, out, err = tool("--undo", str(runs[0] / "undo.json"))
check("undo: the record file is byte for byte what it was before the pass", rc == 0 and REC.read_bytes() == before and "projects" not in recfile() and pr.entries() == {}, (rc, out, err))
check("undo: …and the readers answer from the pages again", snap() == S0)
rc, out, err = tool("--undo", str(runs[0] / "undo.json"))
check("undo: a second undo changes nothing", rc == 0 and REC.read_bytes() == before and "already" in out, (rc, out, err))
rc, out, err = tool("--apply", "--run-dir", str(RUNS))
runs = sorted(RUNS.iterdir()); R2 = recfile(); E2 = R2["projects"]
check("apply (the default): the entries are back; no pending agent is left in the record, the live one folded into its project's agents and the retired project's cleared", rc == 0 and len(E2) == 3 and not R2.get("pending_agents")
      and list(E2[A]["agents"]) == ["home-sparrow-main", "home-sparrow-docs", "home-sparrow-engineer", LIVE] and len(runs) == 2 and "folded 1" in out and "cleared 2" in out, (rc, err, out[-400:], R2.get("pending_agents"), list(E2[A]["agents"])))
check("apply (the default): the folded agent keeps its flag, mandate, who registered it and when; an archived project folds nothing", E2[A]["agents"][LIVE] == {"front": True, "mandate_line": "a pending one", "by": "home-sparrow-main", "at": "2026-11-01T00:00:00Z"}
      and "agents" not in E2[Z] and E2[Z]["status"] == "archived", (E2[A]["agents"].get(LIVE), E2[Z]))
undo2 = runs[-1] / "undo.json"; meta2 = json.loads(undo2.read_text())
check("apply: the undo file lists the entries written and every pending agent cleared, and the previous file is kept before the write", sorted(meta2["entries"]) == sorted(E) and sorted(c["name"] for c in meta2["pending_cleared"]) == ["home-sparrow-x", "home-zeta-old"]
      and (runs[-1] / "project-record.before.json").read_bytes() == before and meta2["after_sha256"] == sha(REC.read_bytes()), meta2)
S2 = snap()
check("apply (the default), the live-shaped fixture: a pending front agent on an active project with a running session is still a role of the project in session_roles, file_roles, with_pending, build and ref — now as a listed agent, not an owed line",
      LIVE in S2["roles"] and S2["roles"][LIVE].get("project") == "projects/alpha" and not S2["roles"][LIVE].get("page_owed") and LIVE in str(S2["file_roles"]) and LIVE in S2["with_pending"]["projects/alpha"][0]["agents"]
      and S2["build"]["projects"][A]["agents"][LIVE]["front"] is True and "page_owed" not in S2["build"]["projects"][A]["agents"][LIVE] and LIVE in S2["refs"][A]["agents"] and LIVE in S2["name_lines"]["projects/alpha"][3],
      (S2["roles"].get(LIVE), S2["refs"][A]["agents"].get(LIVE)))
check("apply (the default): every other reader value is as it was before the entries, the retired project's cleared agent is the only one gone", all(S2[k] == S0[k] for k in ("agent_gap",))
      and "home-zeta-old" in S0["build"]["projects"][Z]["agents"] and "home-zeta-old" not in S2["build"]["projects"][Z]["agents"] and S2["build"]["projects"][A]["keeper"] == S0["build"]["projects"][A]["keeper"], differ(S0["build"]["projects"][Z], S2["build"]["projects"][Z]))
after2 = REC.read_bytes()
rc, out, err = tool("--apply", "--run-dir", str(RUNS))
check("a second pass is a no-op: nothing to do, the record is untouched, no new undo folder", rc == 0 and "nothing to do" in out and REC.read_bytes() == after2 and len(sorted(RUNS.iterdir())) == 2, (rc, out, err))
rc, out, err = tool()
check("a dry run after the pass says there is nothing left to write", rc == 0 and "entries to write: 0" in out and "already in the record: 3" in out and "0 pending agents folded into their projects and 0 cleared" in err, (rc, out, err))

# ---- 5. undo after something else wrote to the record: the entries go, the other writes stay
prj.set_mark(A, on_purpose=True, by="home-sparrow-main"); prj.ensure_ids(["projects/fresh"]); fresh = prj.ensure_ids(["projects/fresh"])["projects/fresh"]
from stackshot.projects import project_verbs as _pv
LATER = _pv.create("home-later", "home")["project"]            # a project a verb made after the pass
rc, out, err = tool("--undo", str(undo2))
R3 = recfile()
check("undo, record changed since: the entries the pass made go, the one a verb made since stays, the pending agents back, the mark and the new id kept", rc == 0 and set(R3.get("projects", {})) == {LATER} and set(R3["pending_agents"]) == {A, Z} and R3["marks"][A]["on_purpose"] is True and fresh in R3["ids"]
      and "changed after the pass" in out, (rc, out, err, R3.get("pending_agents")))
check("…the pending agents are as they were", R3["pending_agents"] == json.loads(before)["pending_agents"])
rc, out, err = tool("--apply", "--run-dir", str(RUNS))
check("apply again (a third pass): its own undo folder, entries back", rc == 0 and len(sorted(RUNS.iterdir())) == 3 and len(recfile()["projects"]) == 4 and LATER in recfile()["projects"], (rc, err))

# ---- 6. the record is read first; the page is the fallback
def upd(fn): return pr.update(fn)
def entry_set(pid, **ch):
    def f(e): e[pid] = {**e[pid], **ch}
    return f
SCOPE2 = prj.scopes()[-1]
upd(entry_set(A, name="home-renamed", title="Alpha, from the record", scope=SCOPE2, hub="projects/zeta",
              agents={"home-sparrow-docs": {"front": False, "mandate_line": "docs, now background"}, "home-sparrow-main": {"front": True, "mandate_line": "main, from the record"}}))
R = prj.registry(); a = R["projects/alpha"]
check("record first: title, name (as the keeper, role name), hub, agents and the background map are the entry's", a["title"] == "Alpha, from the record" and a["session"] == "home-renamed" and a["role"] == "name" and a["hub"] == "projects/zeta"
      and a["agents"] == {"home-sparrow-docs": "docs, now background", "home-sparrow-main": "main, from the record"} and a["back_agents"] == {"home-sparrow-docs": "docs, now background"}, a)
check("record first: the agents keep the entry's order (docs before main), though sorted order is the other way", list(a["agents"]) == ["home-sparrow-docs", "home-sparrow-main"])
check("record first: the page registry file itself still says what the page says", reg()["projects/alpha"]["title"] == "Alpha" and reg()["projects/alpha"]["session"] == "home-sparrow")
rec = prj.ref(A)
check("record first: the project record (ref) — keeper, title, scope, hub, agents with their roles cut from the entry's name", rec["keeper"] == "home-renamed" and rec["title"] == "Alpha, from the record" and rec["scope"] == SCOPE2
      and rec["hub"] == "projects/zeta" and rec["agents"]["home-sparrow-docs"]["front"] is False and rec["agents"]["home-sparrow-main"]["mandate_line"] == "main, from the record", rec)
check("record first: every module's reader sees it — anchors, pages, the server's registry, the client API", anchors.registry()["projects/alpha"]["session"] == "home-renamed" and p.load_registry()["projects/alpha"]["title"] == "Alpha, from the record"
      and server._registry("projects")["projects/alpha"]["hub"] == "projects/zeta" and json.loads(server._client_get("registry", {})[2])["pages"]["projects/alpha"]["back_agents"] == {"home-sparrow-docs": "docs, now background"}
      and anchors.hub_of("projects/alpha") == "projects/zeta" and anchors.front_agents(anchors.registry()["projects/alpha"]) == ["home-sparrow-main"])
check("record first: a field the entry does not hold is the page's — the status and type of alpha", a["status"] == "active" and a["type"] == "project" and a["org"] == "" and a["updated"] == reg()["projects/alpha"]["updated"])
upd(lambda e: e[A].pop("title")); upd(lambda e: e[A].pop("agents"))
a = prj.registry()["projects/alpha"]
check("page fallback, field by field: no title in the entry → the page's title; no agents in the entry → the page's agents and background map", a["title"] == "Alpha" and list(a["agents"]) == ["home-sparrow-main", "home-sparrow-docs", "home-sparrow-engineer"]
      and a["back_agents"] == {"home-sparrow-engineer": "builds and merges"}, a)
upd(lambda e: e.pop(A))
check("page fallback, no entry: the project reads from its page lines, exactly as before", prj.registry()["projects/alpha"] == prj.registry_raw()["projects/alpha"] and prj.ref(A)["keeper"] == "home-sparrow")
upd(lambda e: e.update({A: json.loads(json.dumps(E[A]))}))
upd(entry_set(A, status="archived", retired={"at": "2026-11-05T00:00:00Z", "by": "home-sparrow-main", "how": "made"}))
check("status: an archived entry retires the project though its page says active; the word is the canonical one", prj.registry()["projects/alpha"]["status"] == "archived" and prj.ref(A)["retired"] is True and prj.ref(A)["status"] == "archived")
check("status: …and an archived entry keeps the page's own word when it already means archived (zeta: completed)", prj.registry()["projects/zeta"]["status"] == "completed" and prj.ref(Z)["retired"] is True)
upd(lambda e: (e[Z].update(status="active"), e[Z].pop("retired")))
check("status: an active entry reactivates a project whose page says completed (the word becomes active)", prj.registry()["projects/zeta"]["status"] == "active" and prj.ref(Z)["retired"] is False)
upd(lambda e: (e[A].update(status="active"), e[A].pop("retired")))
upd(entry_set(Z, status="archived", retired={"at": "2026-11-05T00:00:00Z", "by": "migration", "how": "migrated"}))
check("a sub-page has no entry and reads from its page, beside the projects that have one", A_SUB not in pr.entries() and prj.registry()["projects/alpha/sub"] == prj.registry_raw()["projects/alpha/sub"])
check("a sub-page is no project: its key resolves to the top-level project that owns it (an item filed on the sub-page belongs to that project's id), not to an id of its own",
      pr.resolve("projects/alpha/sub")["id"] == A and pr.resolve("projects/alpha/sub")["via"] == "sub_page" and pr.resolve("projects/alpha/sub/deeper/still")["id"] == A and pr.resolve("projects/alpha")["via"] == "page"
      and pr.resolve("projects/nowhere/sub") is None)
check("…and the same through a page with a hub: line (the page that is its hub owns it)", pr.resolve("ops/zeta-tool", hub_of=lambda k: "projects/zeta" if k == "ops/zeta-tool" else "")["id"] == Z)
before_mtime = REC.stat().st_mtime_ns
for _ in range(3): prj.registry(); anchors.registry(); pr.resolve(A); prj.ref(A)
check("reading writes nothing: the record file is untouched by any number of reads", REC.stat().st_mtime_ns == before_mtime)

# ---- 6b. scope: a mark set on purpose beats the entry's scope, which beats the derived one
SC = prj.scopes(); DERIVED = prj.derive_scope("projects/gamma", prj.registry_raw()["projects/gamma"], prj.registry_raw())
E_SC = next(x for x in SC if x != DERIVED); M_SC = next(x for x in SC if x not in (DERIVED, E_SC))
check("scope: with no scope in the entry and no mark, the derived scope answers", prj.ref(G)["scope"] == DERIVED, prj.ref(G))
upd(entry_set(G, scope=E_SC))
check("scope: the entry's scope beats the derived one", prj.ref(G)["scope"] == E_SC and prj.registry()["projects/gamma"]["scope"] == E_SC, prj.ref(G))
prj.set_mark(G, scope=M_SC, by="home-sparrow-main")
check("scope: a mark's scope beats the entry's (scope_set true)", prj.ref(G)["scope"] == M_SC and prj.ref(G)["scope_set"] is True, prj.ref(G))
prj.set_mark(G, scope=None, by="home-sparrow-main")
check("scope: the mark removed, the entry's scope answers again", prj.ref(G)["scope"] == E_SC)
upd(lambda e: e[G].pop("scope"))
check("scope: the entry's scope removed too, the derived scope answers again", prj.ref(G)["scope"] == DERIVED)

# ---- 7. the agents map keeps its order when the file is rewritten by anything
upd(entry_set(A, agents={"home-sparrow-z": {"front": True, "mandate_line": "z first"}, "home-sparrow-b": {"front": True, "mandate_line": "b second"}}))
prj.set_mark(G, on_purpose=True, by="home-sparrow-main")
raw = recfile()
check("order: an agents map is written in the order it holds, not sorted — and a rewrite of the file for another reason keeps it", list(raw["projects"][A]["agents"]) == ["home-sparrow-z", "home-sparrow-b"], list(raw["projects"][A]["agents"]))
check("order: the rest of the file is still sorted at every other level (the file is read by people in git)", list(raw) == sorted(raw) and list(raw["projects"]) == sorted(raw["projects"]) and list(raw["projects"][A]) == sorted(raw["projects"][A]))
upd(entry_set(A, agents=E[A]["agents"]))

# ---- 8. a project with no page
NOPAGE = "prj_0000beef"
upd(lambda e: e.update({NOPAGE: {"name": "home-nopage", "title": "No page", "type": "project", "scope": "home", "status": "active", "agents": {"home-nopage-main": {"front": True, "mandate_line": "keeps it"}},
                                 "made": {"at": "2026-11-05T00:00:00Z", "by": "home-sparrow-main", "how": "made"}}}))
keys0 = set(prj.registry())
v = pr.resolve(NOPAGE)
check("no page: resolves by its id, says it has no page, and has no page key", v and v["has_page"] is False and v["page_key"] == "" and v["page"] == "" and v["via"] == "id" and pr.page_key_of(NOPAGE) == "" and pr.pageless(NOPAGE)["id"] == NOPAGE, v)
check("no page: a project with a page is not 'pageless'", pr.pageless(A) is None and pr.pageless("prj_00000000") is None and pr.pageless("") is None)
crash = []
for label, f in (("registry", prj.registry), ("build", prj.build), ("list_projects", prj.list_projects), ("list with a query", lambda: prj.list_projects(q="nopage")), ("ref by id", lambda: prj.ref(NOPAGE)),
                 ("refs", lambda: prj.refs(NOPAGE)), ("id_to_key", lambda: prj.id_to_key(NOPAGE)), ("to_key", lambda: prj.to_key(NOPAGE)), ("with_made", lambda: prj.with_made(prj.registry())),
                 ("with_pending", lambda: prj.with_pending(prj.registry())), ("sync", lambda: prj.sync(force=True)), ("anchors.registry", anchors.registry), ("session_roles", lambda: anchors.session_roles(anchors.registry(), set())),
                 ("pilot_roots", anchors.pilot_roots), ("pages.load_registry", p.load_registry), ("server registry", lambda: server._registry("projects")), ("client registry", lambda: server._client_get("registry", {})),
                 ("registry hits", lambda: server._registry_hits("projects", NOPAGE)), ("recent_items", lambda: prj.recent_items(prj.registry()))):
    try: f()
    except Exception as ex: crash.append((label, repr(ex)))
check("no page: no reader of the registry crashes on it", not crash, crash)
check("no page: it adds no row to a registry keyed by page (it is reached by resolve), and the others are as they were", set(prj.registry()) == keys0 and prj.ref(NOPAGE) is None and prj.id_to_key(NOPAGE) == "" and server._registry_hits("projects", NOPAGE) == [])
def create(project, owner, **kw): return _wt_create.stackshot_create(subject="[home] a thing", description="- Goal: A thing\n- It lives here\n- Done when done", project=project, owner=owner, **{"next": f"{owner}: carry on", "mover": owner, **kw})
def refusal(project, owner="home-nopage-main"):
    try: create(project, owner); return ""
    except server.ToolError as ex: return str(ex)
r = create(NOPAGE, "home-nopage-main"); gid = _model_ids._norm_id(r.split()[1]); it = server._load(gid)
check("no page: an item can be filed on it — the gate does not refuse a project the record says has no page; the item stores the project's id", it["metadata"]["project"] == NOPAGE, it["metadata"])
check("no page: …and the readers of an item's project take the id as it is (no page key made of it)", anchors.project_of(it) == NOPAGE and not any("prj_" in k for k in prj.recent_items(prj.registry())), (anchors.project_of(it), prj.recent_items(prj.registry())))
check("no page: a name the record does not hold, and an id it does not hold, are still refused as before", "names no page" in refusal("projects/nowhere") and "names no page" in refusal("prj_00000000"))
upd(lambda e: e.update({"prj_0000cafe": {"name": "home-link", "page": "https://kb.example/p/1", "status": "active", "made": {"at": "t", "by": "b", "how": "made"}},
                        "prj_0000f00d": {"name": "home-ghost", "page": "projects/ghost", "status": "active", "made": {"at": "t", "by": "b", "how": "made"}}}))
lv = pr.resolve("prj_0000cafe")
check("pointer is a link elsewhere: the record says it has a page (not 'pageless'), the page key is none", lv["has_page"] is True and lv["page_key"] == "" and pr.pageless("prj_0000cafe") is None, lv)
check("pointer is a link elsewhere, or a page that does not resolve: the refusal stays (a project that has a pointer is not a project with no page)", "names no page" in refusal("prj_0000cafe") and "names no page" in refusal("prj_0000f00d"))
upd(lambda e: (e.pop("prj_0000cafe"), e.pop("prj_0000f00d")))

# ---- 9. former keys and former names
check("former key: an old page key resolves to the project, saying how", pr.resolve("projects/old-alpha")["id"] == A and pr.resolve("projects/old-alpha")["via"] == "former_key" and pr.resolve("projects/older-alpha")["id"] == A
      and pr.resolve("projects/zed")["id"] == Z)
check("former key: a bare slug through the registry's match patterns, a .md and a trailing slash", pr.resolve("old-alpha")["id"] == A and pr.resolve("projects/old-alpha.md")["id"] == A and pr.resolve("projects/old-alpha/")["id"] == A)
check("former key: a key that was never a project's, and a stub that leads nowhere, resolve to none", pr.resolve("projects/lost-stub") is None and pr.resolve("projects/never") is None and pr.resolve("") is None and pr.resolve(None) is None)
check("page key: a current page resolves to its project (via page)", pr.resolve("projects/alpha")["id"] == A and pr.resolve("projects/alpha")["via"] == "page" and pr.resolve("alpha")["id"] == A and pr.resolve(A)["page_key"] == "projects/alpha")
upd(entry_set(A, former_names=["home-sparrow-oldname"]))
check("former name: resolves to the project, and a name that is not a former one resolves to none", pr.resolve("home-sparrow-oldname")["id"] == A and pr.resolve("home-sparrow-oldname")["via"] == "former_name" and pr.resolve("home-sparrow") is None)
check("an id that names no entry resolves to none, and a view is a copy (changing it changes nothing)", pr.resolve("prj_00000000") is None and (pr.resolve(A)["agents"].clear() or True) and pr.entries()[A]["agents"])
# a page move: the id follows and the entry remembers the old key
prj.rename("projects/alpha", "projects/alpha-two")
e = recfile()["projects"][A]
check("page move (projects.rename): the entry points at the new page and lists the old key among the former keys, the older ones kept", e["page"] == "projects/alpha-two" and e["former_keys"] == ["projects/old-alpha", "projects/older-alpha", "projects/alpha"], e["former_keys"])
check("page move: the old key resolves to the project, the new one is its page, and the id names the new key", pr.resolve("projects/alpha")["id"] == A and pr.resolve("projects/alpha")["via"] == "former_key" and pr.resolve("projects/alpha-two")["via"] == "page"
      and prj.id_to_key(A) == "projects/alpha-two" and recfile()["ids"][A] == "projects/alpha-two")
prj.rename("projects/alpha-two", "projects/alpha")
e = recfile()["projects"][A]
check("page move back: the key is a page again, no longer a former key of the project", e["page"] == "projects/alpha" and "projects/alpha" not in e["former_keys"] and "projects/alpha-two" in e["former_keys"], e)
Y, W = prj.ensure_ids(["projects/yy", "projects/zz"]).values()
upd(lambda ents: ents.update({Y: {"page": "projects/yy", "status": "active", "made": {"at": "t", "by": "b", "how": "made"}}, W: {"page": "projects/zz", "status": "active", "made": {"at": "t", "by": "b", "how": "made"}}}))
prj.rename("projects/yy", "projects/zz")
ee = recfile()["projects"]
check("page move onto a key another project holds (the swap): each entry takes the other's key, each lists the key it left", ee[Y]["page"] == "projects/zz" and ee[Y]["former_keys"] == ["projects/yy"] and ee[W]["page"] == "projects/yy" and ee[W]["former_keys"] == ["projects/zz"]
      and recfile()["ids"][Y] == "projects/zz" and recfile()["ids"][W] == "projects/yy", ee[Y])
prj.rename("projects/zz", "projects/yy")
check("page move: a project with no entry moves as it did — only the id table changes", (prj.ensure_ids(["projects/mm"]), prj.rename("projects/mm", "projects/nn"), "projects" in recfile())[2] and prj.ids_by_key().get("projects/nn"))

# ---- 10. a damaged section is answered by the pages; the older tables are untouched by it
good = REC.read_bytes(); R = json.loads(good)
REC.write_text(json.dumps({**R, "projects_schema": 2}), encoding="utf-8")
err_buf = io.StringIO(); real_err = sys.stderr; sys.stderr = err_buf
try: reads = (pr.entries(), prj.registry() == prj.registry_raw(), prj.ensure_ids(["projects/alpha"])["projects/alpha"], pr.resolve(A))
finally: sys.stderr = real_err
check("damaged section (a schema this code does not read): no entries, the pages answer, the ids still work, and one line says so", reads[0] == {} and reads[1] and reads[2] == A and reads[3] is None and "the pages answer" in err_buf.getvalue(), (reads, err_buf.getvalue()))
check("…the section and its version are kept as they were by a rewrite for another reason (an older code's rewrite keeps the fields it does not know)", (prj.set_mark(G, on_purpose=True, by="x"), recfile().get("projects_schema") == 2 and set(recfile()["projects"]) == set(R["projects"]))[1])
REC.write_bytes(good); pr.entries()
REGF = T / "store/projects.json"; reg_good = REGF.read_bytes()
REGF.write_text("{ not json", encoding="utf-8")
code, ctype, body = server._client_get("registry", {})
check("client API: a registry file that does not parse is served as it always was (200, the file's text); only a missing file is 'no registry yet'", code == 200 and body == "{ not json", (code, body))
REGF.rename(T / "store/projects.gone"); code, ctype, body = server._client_get("registry", {}); (T / "store/projects.gone").rename(REGF)
check("client API: no registry file gives 503 as before", code == 503 and "no registry" in body, (code, body))
REGF.write_bytes(reg_good)
check("…a repaired file reads again", pr.entries() != {} and prj.registry()["projects/alpha"]["session"] == "home-sparrow")

print(("ok" if not fails else "FAILED") + f": project registry scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
