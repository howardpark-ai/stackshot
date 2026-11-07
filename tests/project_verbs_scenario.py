"""Scenario test for the project verbs (project_verbs.py, tools/project.py) and the migration's scope (tools/migrate_project_record.py): fixture data, no live store, no network, no server
process (the page store is the plain markdown folder of a temporary config; a fake runner stands in for rename_page.py).

Covers: the migration makes entries for top-level project pages only (a sub-page gets none, and what is filed on a sub-page resolves to the top-level project's id), folds the pending agents of
a live-shaped store into the entries and clears them, and writes nothing on a dry run; each verb (create, rename, move-page, archive and reopen, agent add / retire / rename) writing the record
first and the page mirror from it, the mirror's states (written, unchanged, would-write, none, no-page, failed, exists) and a failed mirror leaving the record right and `mirror()` writing it
later; a page edit to a mirrored line not read and the next mirror write restoring it; a project with no page (no page store call at all) and one whose pointer is a link elsewhere; a project with
no entry yet getting one at its first verb, its pending agents folded in; a sub-page key refused by `create` and `move_page` and resolved to the top-level project by the others; rename
keeping the id and the old name and key resolving; a failed page move changing nothing; a dry run writing nothing; concurrent writers leaving every change in the record and the page the record
describes; the CLI (tools/project.py) in a subprocess on the same temporary config.

    tests/run-suite project_verbs        → exit 0 / 1"""
import hashlib, json, logging, os, pathlib, re, shutil, subprocess, sys, threading
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="prjverbs-"); T = pathlib.Path(tmp)
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
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "brain/ops", "brain/infra", "secrets"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text("{}")
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
BRAIN = T / "brain"
def page(rel, front, body="# x\n"):
    q = BRAIN / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n" + body, encoding="utf-8")
def text(rel): return (BRAIN / (rel + ".md")).read_text(encoding="utf-8")
page("projects/alpha.md", "type: project\ntitle: Alpha\ndisplay-name: home-sparrow\nagents:\n  home-sparrow-main: talks to Oliver\n  home-sparrow-docs: keeps the docs\n"
                          "  background:\n    home-sparrow-engineer: builds and merges\nstatus: active")
page("projects/alpha/sub.md", "type: project\ntitle: Sub")
page("projects/alpha/deeper/leaf.md", "type: note\ntitle: A leaf")
page("projects/zeta.md", "type: project\ntitle: Zeta\ndisplay-name: home-zeta\nstatus: completed\naliases:\n  - projects/zed")
page("ops/zeta-tool.md", "type: note\ntitle: Zeta tool\ndisplay-name: home-zeta\nhub: projects/zeta")
page("projects/gamma.md", "type: project\ntitle: Gamma\ndisplay-name: home-gamma\nagents:\n  home-gamma-main: does it\nstatus: active")
page("projects/delta.md", "type: project\ntitle: Delta\ndisplay-name: home-delta\nstatus: active")
page("projects/plain-note.md", "type: note\ntitle: A note")
page("projects/old-gamma.md", "type: redirect\ntitle: moved\nredirect_to: projects/gamma")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
def sha(b): return hashlib.sha256(b).hexdigest()
REC = T / "store/project-record.json"
def recfile(): return json.loads(REC.read_text())
def recsha(): return sha(REC.read_bytes()) if REC.exists() else ""
def tool(script, *args):
    r = subprocess.run([sys.executable, f"{STACK}/{script}"] + list(args), capture_output=True, text=True, env=os.environ, cwd=str(T))
    return r.returncode, r.stdout, r.stderr

import pages as p, projects as prj, project_registry as pr, project_verbs as pv, page_debt
p.cmd_registry(quiet=True)
IO = page_debt.PlainIO()
def reg(): return json.loads((T / "store/projects.json").read_text())["pages"]
ids = {k: e["id"] for k, e in reg().items()}
A, Z, G, D = (ids[k] for k in ("projects/alpha", "projects/zeta", "projects/gamma", "projects/delta"))
check("setup: the pages make a registry in which the sub-page has an id of its own in the id table (the migration is what leaves it out of the record)", "projects/alpha/sub" in ids and prj.is_id(A), ids)
prj.add_pending(A, "home-sparrow-x", {"front": True, "role": "x", "mandate_line": "a pending one"}, by="home-sparrow-main", at="2026-11-01T00:00:00Z")
prj.add_pending(A, "home-sparrow-y", {"front": False, "role": "y", "mandate_line": "a background one"}, by="home-sparrow-main", at="2026-11-02T00:00:00Z")
prj.add_pending(Z, "home-zeta-old", {"front": False, "role": "old", "mandate_line": "a stale one"}, by="home-zeta-main", at="2026-10-01T00:00:00Z")
def ents(): return pr.entries()
def agents(pid): return {n: (a["front"], a["mandate_line"]) for n, a in (ents()[pid].get("agents") or {}).items()}
def fmagents(rel):
    f, b = p.split_agents(p.frontmatter_text(text(rel)).get("agents")); return list(f.items()), list(b.items())

# ---- 1. the migration: top-level pages only, the live-shaped pending fold
r0 = recsha()
rc, out, err = tool("tools/migrate_project_record.py", "--run-dir", str(T / "run"))
check("migration, dry run: exit 0, counts name the sub-page as left out, nothing written", rc == 0 and "1 of them sub-pages (never projects: no entry)" in out and "entries to write: 4" in out and recsha() == r0, (rc, out, err))
rc, out, err = tool("tools/migrate_project_record.py", "--apply", "--run-dir", str(T / "run"))
E = ents()
check("migration, apply: an entry for each top-level project page (alpha, zeta, gamma, delta) and none for the sub-page", rc == 0 and set(E) == {A, Z, G, D} and ids["projects/alpha/sub"] not in E, (rc, out, err, sorted(E)))
check("migration: the pending agents of an active project are folded after the page's own (front as asked, with who and when), and the table is cleared",
      list(agents(A)) == ["home-sparrow-main", "home-sparrow-docs", "home-sparrow-engineer", "home-sparrow-x", "home-sparrow-y"] and agents(A)["home-sparrow-x"] == (True, "a pending one") and agents(A)["home-sparrow-y"][0] is False
      and E[A]["agents"]["home-sparrow-x"].get("by") == "home-sparrow-main" and E[A]["agents"]["home-sparrow-x"].get("at") == "2026-11-01T00:00:00Z" and recfile()["pending_agents"] == {}, (agents(A), recfile()["pending_agents"]))
check("migration: an archived project's stale pending agent is not folded", "home-zeta-old" not in (E[Z].get("agents") or {}) and E[Z]["status"] == "archived", E[Z])
check("migration: the former keys (the stub and the alias) are on the entries", E[G]["former_keys"] == ["projects/old-gamma"] and E[Z]["former_keys"] == ["projects/zed"], (E[G]["former_keys"], E[Z]["former_keys"]))
SUB = "projects/alpha/sub"
check("sub-page: its key resolves to the top-level project (the id an item filed on it takes), not to an id of its own", pr.resolve(SUB)["id"] == A and pr.resolve(SUB)["via"] == "sub_page"
      and pr.resolve("projects/alpha/deeper/leaf")["id"] == A and pr.resolve("projects/nowhere/x") is None, (pr.resolve(SUB), pr.resolve("projects/alpha/deeper/leaf")))
check("sub-page: a page with a hub: line resolves to its hub's project", pr.resolve("ops/zeta-tool", hub_of=lambda k: "projects/zeta" if k == "ops/zeta-tool" else "")["id"] == Z)

# ---- 2. the mirror
check("mirror: after the migration the page lacks the folded agents, so the mirror writes them (front agents first, then the background ones under background:) and says so", pv.mirror(A, IO)["state"] == "written"
      and [n for n, _ in fmagents("projects/alpha")[0]] == ["home-sparrow-main", "home-sparrow-docs", "home-sparrow-x", "home-sparrow-engineer", "home-sparrow-y"]
      and [n for n, _ in fmagents("projects/alpha")[1]] == ["home-sparrow-engineer", "home-sparrow-y"], fmagents("projects/alpha"))
check("mirror: said again, the page already reads as the record says: unchanged, no write", pv.mirror(A, IO)["state"] == "unchanged")
check("mirror: the page's other lines and body are untouched", "title: Alpha" in text("projects/alpha") and text("projects/alpha").rstrip().endswith("# x"), text("projects/alpha"))
p.cmd_registry(quiet=True)
page("projects/alpha.md", text("projects/alpha").split("---\n")[1].replace("display-name: home-sparrow", "display-name: home-renamed-on-page").replace("status: active", "status: archived").rstrip("\n"))
p.cmd_registry(quiet=True)
check("page edit: a change to a mirrored line is not read (the entry wins): the name and status stay the record's", prj.registry()["projects/alpha"]["session"] == "home-sparrow" and prj.registry()["projects/alpha"]["status"] == "active",
      {k: prj.registry()["projects/alpha"].get(k) for k in ("session", "status")})
m = pv.mirror(A, IO)
check("page edit: the next mirror write restores the page's lines from the record", m["state"] == "written" and "display-name: home-sparrow\n" in text("projects/alpha") and "status: archived" not in text("projects/alpha"), (m, text("projects/alpha")))
class Counting:
    """A page store that counts its calls and can be told to refuse."""
    def __init__(s, base, mode="ok"): s.b, s.mode, s.calls = base, mode, []
    def get(s, k): s.calls.append(("get", k)); return s.b.get(k)
    def put(s, k, c, r):
        s.calls.append(("put", k))
        return ("refused", "no") if s.mode == "refused" else s.b.put(k, c, r)
    def create(s, k, c): s.calls.append(("create", k)); return ("refused", "no") if s.mode == "refused" else s.b.create(k, c)
    def add_timeline(s, *a, **kw): s.calls.append(("timeline", a[0])); return s.b.add_timeline(*a, **kw)

# ---- 3. create
r1 = recsha(); cio = Counting(IO)
res = pv.create("home-pl", "home", by="home-sparrow", io=cio, now="2026-11-05T01:00:00Z")
PL = res["project"]
check("create: a project with no page: an entry with the name, scope, status active and who made it; no page store call at all; mirror state none", prj.is_id(PL) and ents()[PL]["name"] == "home-pl" and "page" not in ents()[PL]
      and ents()[PL]["made"] == {"at": "2026-11-05T01:00:00Z", "by": "home-sparrow", "how": "made"} and res["mirror"]["state"] == "none" and cio.calls == [], (res, cio.calls))
check("create: …the readers find it as a project with no page", (pv.one(PL) or {}).get("pageless") is True and pr.pageless(PL)["id"] == PL and not (BRAIN / "projects/home-pl.md").exists())
res = pv.create("home-link", "home", page="https://notes.example.org/home-link", io=cio)
check("create: a pointer that is a link elsewhere: recorded as it is, no page written, mirror none", res["mirror"]["state"] == "none" and ents()[res["project"]]["page"] == "https://notes.example.org/home-link" and cio.calls == [], (res, cio.calls))
res = pv.create("home-new", "home", page="projects/newpage", make_page=True, title="New page", by="home-sparrow", io=cio, now="2026-11-05T01:05:00Z")
NEW = res["project"]
check("create: with a page and make_page the page is made from the template, then carries the name line", res["mirror"]["state"] == "written" and "display-name: home-new" in text("projects/newpage") and "## Current state" in text("projects/newpage")
      and ents()[NEW]["page"] == "projects/newpage" and recfile()["ids"][NEW] == "projects/newpage", (res["mirror"], text("projects/newpage")[:300]))
def pv_err(fn):
    try: fn(); return 0
    except pv.VerbError as e: return e.status
rb = recsha()
check("create: a name some project has (case folded) → 409, nothing written", pv_err(lambda: pv.create("HOME-NEW", "home", io=cio)) == 409 and recsha() == rb)
check("create: a page that is a project's already → 409", pv_err(lambda: pv.create("home-dup", "home", page="projects/alpha", io=cio)) == 409 and recsha() == rb)
check("create: a sub-page key (under another page) → 400, nothing written", pv_err(lambda: pv.create("home-s", "home", page=SUB, io=cio)) == 400 and recsha() == rb)
try: pv.create("home-s", "home", page=SUB, io=cio)
except pv.VerbError as e: msg = e.message
check("create: …the 400 names the sub-page, the top-level page to use, and says a sub-page is never a project", "projects/alpha/sub is a sub-page of projects/alpha" in msg and "never a project" in msg, msg)
check("create: a page under a sub-page, one that does not exist yet, is a sub-page too (400)", pv_err(lambda: pv.create("home-s2", "home", page="projects/alpha/sub/more", io=cio)) == 400)
check("create: a page with a hub: line → 400", pv_err(lambda: pv.create("home-s3", "home", page="ops/zeta-tool", io=cio)) == 400 and recsha() == rb)
check("create: a bad name or scope → 400", pv_err(lambda: pv.create("bad name", "home")) == 400 and pv_err(lambda: pv.create("home-ok", "elsewhere")) == 400)
fio = Counting(IO, "refused")
rb = recsha()
check("create: the page cannot be made (the store refuses): 502, and the project is not made (no entry, no id left behind)", pv_err(lambda: pv.create("home-fail", "home", page="projects/failpage", make_page=True, io=fio)) == 502
      and "home-fail" not in [e.get("name") for e in ents().values()] and "projects/failpage" not in recfile()["ids"].values(), fio.calls)
check("create: …and said again with a store that works it goes through", pv.create("home-fail", "home", page="projects/failpage", make_page=True, io=IO)["mirror"]["state"] == "written")

# ---- 4. agents
rb = recsha()
res = pv.agent_add(A, "home-sparrow-triage", True, "sorts the incoming", by="home-sparrow-main", io=IO, now="2026-11-05T02:00:00Z")
check("agent add: the record has the agent (with who and when) and the page's block was written from it", agents(A)["home-sparrow-triage"] == (True, "sorts the incoming") and ents()[A]["agents"]["home-sparrow-triage"]["by"] == "home-sparrow-main"
      and res["mirror"]["state"] == "written" and "home-sparrow-triage" in dict(fmagents("projects/alpha")[0]), (res["mirror"], fmagents("projects/alpha")))
check("agent add: a background agent lands under background: on the page", pv.agent_add(A, "home-sparrow-scribe", False, "writes", io=IO)["mirror"]["state"] == "written" and "home-sparrow-scribe" in dict(fmagents("projects/alpha")[1]))
res = pv.agent_add(A, "HOME-SPARROW-TRIAGE", True, "sorts   the incoming", io=IO)
check("agent add: the same agent again (name case-folded, mandate whitespace) changes nothing", res["changed"] is False and res["mirror"]["state"] == "unchanged", res)
rb = recsha()
check("agent add: another mandate for a listed name → 409 (retire or rename first), nothing written", pv_err(lambda: pv.agent_add(A, "home-sparrow-triage", True, "something else", io=IO)) == 409 and recsha() == rb)
_r = pv.agent_add(SUB, "home-sparrow-sub", True, "listed through the sub-page key", io=IO)
check("agent add: a sub-page key names the top-level project", _r["project"] == A and "home-sparrow-sub" in agents(A), (_r["project"], A, sorted(ents())))
check("agent add: no such project → 404", pv_err(lambda: pv.agent_add("projects/nowhere", "home-n-main", True, "m", io=IO)) == 404)
res = pv.agent_rename(A, "home-sparrow-triage", "home-sparrow-sorter", io=IO)
names = list(agents(A))
check("agent rename: the same place in the map, the same mandate; the page follows", res["result"] == "renamed" and names.index("home-sparrow-sorter") == names.index("home-sparrow-scribe") - 1 and agents(A)["home-sparrow-sorter"] == (True, "sorts the incoming")
      and "home-sparrow-triage" not in agents(A) and "home-sparrow-sorter" in dict(fmagents("projects/alpha")[0]) and "home-sparrow-triage" not in text("projects/alpha"), (names, res))
check("agent rename: said again it is 'already renamed'; a missing old name is 404; a taken new name is 409", pv.agent_rename(A, "home-sparrow-triage", "home-sparrow-sorter", io=IO)["result"] == "already renamed"
      and pv_err(lambda: pv.agent_rename(A, "home-sparrow-ghost", "home-sparrow-other", io=IO)) == 404 and pv_err(lambda: pv.agent_rename(A, "home-sparrow-docs", "home-sparrow-main", io=IO)) == 409)
res = pv.agent_retire(A, "home-sparrow-sorter", io=IO)
check("agent retire: the line is gone from the record and the page, a timeline line is written once", res["result"] == "line removed" and "home-sparrow-sorter" not in agents(A) and "home-sparrow-sorter" not in dict(fmagents("projects/alpha")[0])
      and text("projects/alpha").count("home-sparrow-sorter retired") == 1, (res, text("projects/alpha")[-300:]))
check("agent retire: a name that is not listed changes nothing", pv.agent_retire(A, "home-sparrow-ghost", io=IO)["result"] == "not listed")
check("agent round trip: add, retire, add again lands in the same state as the first add", (pv.agent_add(A, "home-sparrow-rt", True, "round trip", io=IO), pv.agent_retire(A, "home-sparrow-rt", io=IO), pv.agent_add(A, "home-sparrow-rt", True, "round trip", io=IO))[2]["mirror"]["state"] == "written"
      and list(agents(A))[-1] == "home-sparrow-rt" and text("projects/alpha").count("home-sparrow-rt:") == 1)

# a failing mirror: the record is right, the answer says the page is not, mirror() later writes it
bad_io = Counting(IO, "refused"); rb_text = text("projects/gamma")
res = pv.agent_add(G, "home-gamma-late", True, "added while the store is down", io=bad_io)
check("mirror failure: the record has the agent, the answer says the mirror failed (with why), the page is as it was", agents(G)["home-gamma-late"] == (True, "added while the store is down") and res["mirror"]["state"] == "failed" and res["mirror"]["note"]
      and text("projects/gamma") == rb_text, res["mirror"])
check("mirror failure: …mirror() writes it when the store is back", pv.mirror(G, IO)["state"] == "written" and "home-gamma-late" in dict(fmagents("projects/gamma")[0]))
check("mirror: a project with no page is 'none', and one whose page reads as the record says is 'unchanged'", pv.mirror(PL, IO)["state"] == "none" and pv.mirror(NEW, IO)["state"] == "unchanged")
gone = pv.create("home-gone", "home", page="projects/gone-page", io=IO)
check("mirror: …create without make_page only points at the page: state no-page, the record holds the pointer, no page made", gone["mirror"]["state"] == "no-page" and ents()[gone["project"]]["page"] == "projects/gone-page" and not (BRAIN / "projects/gone-page.md").exists(), gone["mirror"])

# ---- 4b. agent_mandate: the mandate line of a listed agent changes in the record, the page follows, and the page cannot undo it
OLD_ENG = "builds, merges and deploys"; OLD_UI = "builds the board pages"; OLD_PLAT = "builds hosting"
NEW_ENG = "builds the server; reviews each change; releases for every builder"
NEW_UI = "builds the pages and the side panel, via subagents; a reviewer reads each change; releases through demo-builder-a"
NEW_PLAT = "builds and runs hosting and CI, via subagents, no decisions; a reviewer reads each change; releases through demo-builder-a"
MP = pv.create("demo-app", "home", page="projects/demo-app", make_page=True, io=IO)["project"]
for n_, f_, m_ in (("demo-main", True, "talks to the owner"), ("demo-builder-a", False, OLD_ENG), ("demo-builder-b", False, OLD_UI), ("demo-builder-c", False, OLD_PLAT)):
    pv.agent_add(MP, n_, f_, m_, io=IO)
order0 = list(agents(MP)); who0 = {n: a.get("by") for n, a in ents()[MP]["agents"].items()}
res = pv.agent_mandate(MP, "demo-builder-a", NEW_ENG, by="demo-main", io=IO)
check("agent mandate: the record holds the new line, the side (background) and the place in the map stay, the answer names the previous line", res["changed"] is True and agents(MP)["demo-builder-a"] == (False, NEW_ENG)
      and list(agents(MP)) == order0 and res["previous"] == OLD_ENG and res["front"] is False and res["name"] == "demo-builder-a", (res, agents(MP)))
check("agent mandate: …the page's agents block was written from the record (state written), the new line under background:", res["mirror"]["state"] == "written" and dict(fmagents("projects/demo-app")[1])["demo-builder-a"] == NEW_ENG
      and dict(fmagents("projects/demo-app")[0])["demo-main"] == "talks to the owner", (res["mirror"], fmagents("projects/demo-app")))
check("agent mandate: …the other agents' lines, who listed each agent and the project's front agent are untouched", agents(MP)["demo-builder-b"] == (False, OLD_UI) and agents(MP)["demo-main"] == (True, "talks to the owner")
      and {n: a.get("by") for n, a in ents()[MP]["agents"].items()} == who0, agents(MP))
res = pv.agent_mandate(MP, "DEMO-BUILDER-B", NEW_UI, io=IO)
check("agent mandate: a name compares case-folded (the stored spelling is kept)", res["changed"] is True and res["name"] == "demo-builder-b" and agents(MP)["demo-builder-b"] == (False, NEW_UI) and "DEMO-BUILDER-B" not in agents(MP))
res = pv.agent_mandate(MP, "demo-builder-c", "  " + NEW_PLAT.replace(", via", ",\n   via") + "  ", io=IO)
check("agent mandate: a line is stored on one line with its whitespace folded", agents(MP)["demo-builder-c"] == (False, NEW_PLAT), agents(MP)["demo-builder-c"])
txt0 = text("projects/demo-app")
gio_t = txt0.replace(NEW_ENG, "the old line put back by hand")
(BRAIN / "projects/demo-app.md").write_text(gio_t, encoding="utf-8")
check("agent mandate: (setup) a hand edit of the page's line puts the old text back there", dict(fmagents("projects/demo-app")[1])["demo-builder-a"] == "the old line put back by hand")
m1 = pv.mirror(MP, IO)
check("agent mandate: a mirror write from the record restores the new line (the page cannot undo the change)", m1["state"] == "written" and text("projects/demo-app") == txt0 and agents(MP)["demo-builder-a"] == (False, NEW_ENG), (m1, text("projects/demo-app")[:500]))
pv.agent_add(MP, "demo-extra", False, "a later agent", io=IO)
check("agent mandate: a second mirror write (another verb's, and mirror() again) keeps all three new lines", pv.mirror(MP, IO)["state"] == "unchanged" and {n: l for n, l in fmagents("projects/demo-app")[1]} ==
      {"demo-builder-a": NEW_ENG, "demo-builder-b": NEW_UI, "demo-builder-c": NEW_PLAT, "demo-extra": "a later agent"}, fmagents("projects/demo-app"))
rb = recsha(); tb = text("projects/demo-app")
res = pv.agent_mandate(MP, "demo-builder-a", NEW_ENG, io=IO)
check("agent mandate: the same line again changes nothing (no write to the record, the page unchanged)", res["changed"] is False and res["mirror"]["state"] == "unchanged" and recsha() == rb and text("projects/demo-app") == tb, res)
def pv_err_msg(fn):
    try: fn(); return (0, "")
    except pv.VerbError as e: return (e.status, e.message)
st_, msg_ = pv_err_msg(lambda: pv.agent_mandate(MP, "demo-ghost", "something", io=IO))
check("agent mandate: an agent that is not listed → 404 naming it and saying to list it first with agent_add; nothing written", st_ == 404 and "demo-ghost is not listed" in msg_ and "agent_add" in msg_ and recsha() == rb and text("projects/demo-app") == tb, (st_, msg_))
for empty_ in ("", "   ", "\n\t "):
    st_, msg_ = pv_err_msg(lambda: pv.agent_mandate(MP, "demo-builder-a", empty_, io=IO))
    check(f"agent mandate: an empty line ({empty_!r}) → 400 saying the line is empty and how to remove an agent; nothing written, the old line stays", st_ == 400 and "empty" in msg_ and "agent_retire" in msg_ and recsha() == rb and agents(MP)["demo-builder-a"] == (False, NEW_ENG), (st_, msg_))
st_, msg_ = pv_err_msg(lambda: pv.agent_mandate(MP, "demo-builder-a", "uses a back\\slash", io=IO))
check("agent mandate: a line with a backslash → 400 saying to write it without; nothing written, the old line stays", st_ == 400 and "cannot contain a backslash" in msg_ and recsha() == rb and agents(MP)["demo-builder-a"] == (False, NEW_ENG), (st_, msg_))
check("agent mandate: no such project → 404",pv_err(lambda: pv.agent_mandate("projects/nowhere", "home-n-main", "m", io=IO)) == 404)
prj.add_pending(MP, "demo-pend", {"front": False, "role": "pend", "mandate_line": "pending only"}, by="x")
check("agent mandate: a pending entry only is not a listed agent (404)", pv_err(lambda: pv.agent_mandate(MP, "demo-pend", "changed", io=IO)) == 404 and recfile()["pending_agents"][MP]["demo-pend"]["mandate_line"] == "pending only")
check("agent mandate: a sub-page key names the top-level project", pv.agent_mandate(SUB, "home-sparrow-docs", "keeps the docs and the notes", io=IO)["project"] == A and agents(A)["home-sparrow-docs"] == (True, "keeps the docs and the notes"))
rb = recsha(); res = pv.agent_mandate(MP, "demo-extra", "a line that is only tried", io=IO, dry=True)
check("agent mandate: a dry run says what would change and writes nothing to the record or the page", res["dry"] is True and res["changed"] is True and recsha() == rb and text("projects/demo-app") == tb and agents(MP)["demo-extra"] == (False, "a later agent"), res)
bad_io2 = Counting(IO, "refused")
res = pv.agent_mandate(MP, "demo-extra", "changed while the store is down", io=bad_io2)
check("agent mandate: a page store that refuses: the record holds the new line, the mirror says failed, and mirror() writes it later", agents(MP)["demo-extra"] == (False, "changed while the store is down") and res["mirror"]["state"] == "failed"
      and text("projects/demo-app") == tb and pv.mirror(MP, IO)["state"] == "written" and dict(fmagents("projects/demo-app")[1])["demo-extra"] == "changed while the store is down", res["mirror"])
check("agent mandate: agent_add of another line for a listed name still refuses (409) and the text names agent_mandate", "agent_mandate" in pv_err_msg(lambda: pv.agent_add(MP, "demo-builder-a", False, "x", io=IO))[1])

# ---- 5. a project with no entry yet: its first verb makes the entry from the page, folds its pending agents
page("projects/eps.md", "type: project\ntitle: Eps\ndisplay-name: home-eps\nagents:\n  home-eps-main: talks\nstatus: active"); p.cmd_registry(quiet=True)
EPS = {k: e["id"] for k, e in reg().items()}["projects/eps"]
prj.add_pending(EPS, "home-eps-pend", {"front": True, "role": "pend", "mandate_line": "pending"}, by="home-eps-main", at="2026-11-03T00:00:00Z")
check("no entry yet: (setup) the project is not in the record's entries", EPS not in ents() and "home-eps-pend" in recfile()["pending_agents"][EPS])
res = pv.agent_add("projects/eps", "home-eps-eng", False, "builds", io=IO)
check("no entry yet: the first verb makes the entry from the page lines (migrated), folds the pending agent after the page's, clears the table, and mirrors", list(agents(EPS)) == ["home-eps-main", "home-eps-pend", "home-eps-eng"]
      and ents()[EPS]["made"]["how"] == "migrated" and EPS not in recfile()["pending_agents"] and res["mirror"]["state"] == "written", (agents(EPS), res["mirror"]))

# ---- 6. rename
prj.add_pending(Z, "home-zeta-old2", {"front": True, "role": "old2", "mandate_line": "pending under the old name"}, by="home-zeta-main")
res = pv.rename(Z, "home-zeta2", by="home-sparrow", io=IO)
check("rename: the id stays, the name changes, the old one is a former name, the pending agent under the old name is dropped, the page's name line follows with a timeline line",
      res["project"] == Z and ents()[Z]["name"] == "home-zeta2" and "home-zeta" in ents()[Z]["former_names"] and res["dropped"] == ["home-zeta-old2"] and Z not in recfile()["pending_agents"]
      and "display-name: home-zeta2" in text("projects/zeta") and "renamed from home-zeta to home-zeta2" in text("projects/zeta"), (res, text("projects/zeta")[-250:]))
check("rename: the old name still resolves to the project (former name), and so does the new one", pr.resolve("home-zeta")["id"] == Z and pv.pid_of("home-zeta") == Z and pv.pid_of("home-zeta2") == Z and pv.pid_of("HOME-ZETA2") == Z and pv.pid_of(SUB) == A and pv.pid_of("home-nothing") == "",
      (pr.resolve("home-zeta"), pv.pid_of("home-zeta2")))
rb = recsha()
check("rename: a name another project has → 409; the same name again changes nothing; a bad name → 400", pv_err(lambda: pv.rename(Z, "home-sparrow", io=IO)) == 409 and pv.rename(Z, "home-zeta2", io=IO)["changed"] is False
      and pv_err(lambda: pv.rename(Z, "no good", io=IO)) == 400)
check("rename: a sub-page key names the top-level project", pv.rename(SUB, "home-sparrow", io=IO)["changed"] is False)

# ---- 7. archive and reopen
res = pv.archive(D, by="home-sparrow", why="done for now", io=IO, now="2026-11-05T03:00:00Z")
check("archive: status archived with who, when, how and why; the page's status follows and a timeline line says so", ents()[D]["status"] == "archived" and ents()[D]["retired"] == {"at": "2026-11-05T03:00:00Z", "by": "home-sparrow", "how": "made", "why": "done for now"}
      and re.search(r"(?m)^status: (archived|closed|done)", text("projects/delta")) is not None and "archived; done for now" in text("projects/delta"), (res["mirror"], text("projects/delta")))
check("archive: said again it changes nothing", pv.archive(D, io=IO)["changed"] is False)
res = pv.reopen(D, by="home-sparrow", io=IO)
check("reopen: active again, no retired mark, the page's status follows", ents()[D]["status"] == "active" and "retired" not in ents()[D] and "status: active" in text("projects/delta") and res["mirror"]["state"] == "written", (res["mirror"], text("projects/delta")))
check("archive: a project with no page archives in the record alone", pv.archive(PL, io=Counting(IO))["mirror"]["state"] == "none" and ents()[PL]["status"] == "archived")

# ---- 8. move-page with a fake runner that does what rename_page.py does to the files
calls = []
def runner_ok(args):
    calls.append(args)
    ph, pair = args[0], args[1]; old, new = pair.split("=")
    if ph == "copy":
        (BRAIN / (new + ".md")).parent.mkdir(parents=True, exist_ok=True); shutil.copy(BRAIN / (old + ".md"), BRAIN / (new + ".md"))
    return 0, f"{ph} ok"
res = pv.move_page(G, "projects/gamma-moved", by="home-sparrow", runner=runner_ok, io=IO)
check("move-page: runs copy then stub for old=new; the pointer is the new key, the old key joins former_keys (after the stub's), the id table follows, the mirror ran at the new key",
      [c[0] for c in calls] == ["copy", "stub"] and calls[0][1] == "projects/gamma=projects/gamma-moved" and ents()[G]["page"] == "projects/gamma-moved" and ents()[G]["former_keys"] == ["projects/old-gamma", "projects/gamma"]
      and recfile()["ids"][G] == "projects/gamma-moved" and res["moved"] is True and res["mirror"]["key"] == "projects/gamma-moved" and res["mirror"]["state"] in ("unchanged", "written"), (calls, ents()[G], res["mirror"]))
check("move-page: the old key and the stub's older key resolve to the project (former keys)", pr.resolve("projects/gamma")["id"] == G and pr.resolve("projects/old-gamma")["id"] == G)
calls.clear(); rb = recsha()
res = pv.move_page(Z, "projects/zeta-new", runner=runner_ok, dry=True, io=IO)
check("move-page, dry run: only the plan step runs, nothing in the record changes", [c[0] for c in calls] == ["plan"] and res["moved"] is False and recsha() == rb, (calls, res))
calls.clear()
def runner_bad(args): calls.append(args); return 3, "boom: could not copy"
check("move-page: a failed step is a 502 naming the step; the record is not changed", pv_err(lambda: pv.move_page(Z, "projects/zeta-new", runner=runner_bad, io=IO)) == 502 and recsha() == rb and ents()[Z]["page"] == "projects/zeta")
check("move-page: onto the page of another project → 409; onto the same key → 400; a bad key → 400", pv_err(lambda: pv.move_page(Z, "projects/alpha", runner=runner_ok, io=IO)) == 409 and pv_err(lambda: pv.move_page(Z, "projects/zeta", runner=runner_ok, io=IO)) == 400
      and pv_err(lambda: pv.move_page(Z, "elsewhere/x", runner=runner_ok, io=IO)) == 400)
calls.clear()
try: pv.move_page(SUB, "projects/alpha-sub-moved", runner=runner_ok, io=IO)
except pv.VerbError as e: sub_err = (e.status, e.message)
else: sub_err = (0, "")
check("move-page: a sub-page key is refused with a 400 (a sub-page is never a project; moving it is a page move), the runner is not called, nothing changes", sub_err[0] == 400 and "sub-page of projects/alpha" in sub_err[1] and calls == [] and recsha() == rb, sub_err)
check("move-page: the project named by its top-level page moves it; a no-page project has none to move (400)", pv_err(lambda: pv.move_page(PL, "projects/pl-page", runner=runner_ok, io=IO)) == 400)

# ---- 9. a dry run writes nothing
rb, tb = recsha(), text("projects/alpha")
res = pv.agent_add(A, "home-sparrow-dry", True, "never written", io=IO, dry=True)
check("dry run: the answer is what would be written (changed, mirror would-write); the record and the page are as they were", res["changed"] is True and res["dry"] is True and res["mirror"]["state"] == "would-write" and recsha() == rb and text("projects/alpha") == tb, res["mirror"])
check("dry run: create and rename and archive write nothing either", (pv.create("home-dry", "home", page="projects/dry", make_page=True, io=IO, dry=True)["dry"], pv.rename(A, "home-sparrow-dry", io=IO, dry=True)["dry"], pv.archive(A, io=IO, dry=True)["dry"]) == (True, True, True)
      and recsha() == rb and not (BRAIN / "projects/dry.md").exists())

# ---- 10. concurrent writers
N = 8; errs = []
def worker(i):
    try: pv.agent_add(A, f"home-sparrow-w{i}", i % 2 == 0, f"worker {i}", io=IO)
    except Exception as e: errs.append(repr(e))
ths = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
[t.start() for t in ths]; [t.join() for t in ths]
res = pv.mirror(A, IO)
check("concurrent writers: every agent is in the record (one write at a time under the lock), no worker failed", not errs and all(f"home-sparrow-w{i}" in agents(A) for i in range(N)), (errs, list(agents(A))))
check("concurrent writers: the page the record describes is what is left (after a last mirror every agent is on it once, and it reads back unchanged)", all(text("projects/alpha").count(f"home-sparrow-w{i}:") == 1 for i in range(N)) and pv.mirror(A, IO)["state"] == "unchanged"
      and sorted(n for n, _ in fmagents("projects/alpha")[0]) == sorted(agents(A)), (res["state"], fmagents("projects/alpha")))
check("concurrent writers: the record file still parses and holds the entries of every project", set(recfile()["projects"]) >= {A, Z, G, D, PL, NEW, EPS}, sorted(recfile()["projects"]))

# ---- 10b. a sub-page is never a project, by id or by key, with or without a migration; a page-only agent is never deleted
SUBID = ids[SUB]
rb = recsha()
check("sub-page id: rename, archive, reopen, agent add, agent retire and move-page through the id of a sub-page are each a 400 naming the top-level page; no entry is made",
      all(pv_err(f) == 400 for f in (lambda: pv.rename(SUBID, "home-subname", io=IO), lambda: pv.archive(SUBID, io=IO), lambda: pv.reopen(SUBID, io=IO), lambda: pv.agent_add(SUBID, "home-sparrow-sx", True, "m", io=IO),
                                      lambda: pv.agent_retire(SUBID, "home-sparrow-sx", io=IO), lambda: pv.move_page(SUBID, "projects/elsewhere", runner=runner_ok, io=IO)))
      and recsha() == rb and SUBID not in ents() and not [e for e in ents().values() if e.get("page") == SUB], (SUBID in ents(), [e for e in ents().values() if e.get("page") == SUB]))
try: pv.rename(SUBID, "home-subname", io=IO)
except pv.VerbError as e: msg = e.message
check("sub-page id: …the message names the sub-page and the top-level page to use", f"{SUB} is a sub-page of projects/alpha" in msg and "name projects/alpha" in msg, msg)
check("sub-page id: pid_of refuses it too (400)", pv_err(lambda: pv.pid_of(SUBID)) == 400)
# a parent that was never migrated, and a sub-page under it
page("projects/theta.md", "type: project\ntitle: Theta\ndisplay-name: home-theta\nagents:\n  home-theta-main: talks\nstatus: active")
page("projects/theta/kid.md", "type: project\ntitle: Kid"); p.cmd_registry(quiet=True)
TH, KID = [{k: e["id"] for k, e in reg().items()}[x] for x in ("projects/theta", "projects/theta/kid")]
rb = recsha(); calls.clear()
check("no migration: a sub-page's key handed to move-page is a 400 before any entry is made; the runner is not called and the parent's page is not the one moved",
      pv_err(lambda: pv.move_page("projects/theta/kid", "projects/elsewhere", runner=runner_ok, io=IO)) == 400 and calls == [] and recsha() == rb and TH not in ents() and KID not in ents(), (calls, sorted(ents())))
check("no migration: …and through the sub-page's id the same", pv_err(lambda: pv.move_page(KID, "projects/elsewhere", runner=runner_ok, io=IO)) == 400 and calls == [] and recsha() == rb)
check("no migration: archive and reopen through a sub-page key are a 400 too (they act on the whole project); the same through the top-level page does not", pv_err(lambda: pv.archive("projects/theta/kid", io=IO)) == 400
      and pv_err(lambda: pv.reopen("projects/alpha/sub", io=IO)) == 400 and recsha() == rb and pv_err(lambda: pv.reopen("projects/theta", io=IO)) == 0)
check("a sub-page key still resolves to the top-level project for rename and agent edits (the keys are the project's)", pv.agent_add("projects/theta/kid", "home-theta-kidagent", False, "via the sub-page key", io=IO)["project"] == TH)
rb = recsha()
check("create: a key below a page that is not in the registry (no parent to find) is a 400 as well, nothing written", pv_err(lambda: pv.create("home-deep", "home", page="projects/nopar/child", io=IO)) == 400 and recsha() == rb
      and not any(e.get("name") == "home-deep" for e in ents().values()))
check("create: …and a make_page key with a slash is a 400", pv_err(lambda: pv.create("home-deep2", "home", page="projects/nopar2/child", make_page=True, io=IO)) == 400 and recsha() == rb and not (BRAIN / "projects/nopar2").exists())
calls.clear()
check("move-page: onto a key below the project's own page, or below a page that is not in the registry, or one that is another page's sub-page: 400, the runner is not called",
      all(pv_err(lambda k=k: pv.move_page(G, k, runner=runner_ok, io=IO)) == 400 for k in ("projects/alpha/gamma-moved", "projects/nopar/x", "projects/gamma-moved/deeper", "projects/alpha/sub/x")) and calls == [] and ents()[G]["page"] == "projects/gamma-moved", (calls, ents()[G]["page"]))

# a page-only agent: listed on the page since the registry was last built (it follows the pages minutes late)
page("projects/iota.md", "type: project\ntitle: Iota\ndisplay-name: home-iota\nagents:\n  home-iota-main: talks\nstatus: active")
page("projects/iota2.md", "type: project\ntitle: Iota two\ndisplay-name: home-iota2\nagents:\n  home-iota2-main: talks\nstatus: active"); p.cmd_registry(quiet=True)
IOTA, IOTA2 = (lambda m: (m["projects/iota"], m["projects/iota2"]))({k: e["id"] for k, e in reg().items()})
for rel in ("projects/iota.md", "projects/iota2.md"):
    q = BRAIN / rel; q.write_text(q.read_text().replace("  home-iota", "  home-iotaX-late: added on the page a minute ago\n  home-iota", 1).replace("home-iotaX-late", "home-iota-late" if rel.endswith("iota.md") else "home-iota2-late"), encoding="utf-8")
check("page-only agent: (setup) the page lists an agent the registry snapshot does not, and the project has no entry", "home-iota-late" in text("projects/iota") and "home-iota-late" not in (reg()["projects/iota"].get("agents") or {}) and IOTA not in ents())
res = pv.agent_add("projects/iota", "home-iota-other", True, "added by a verb", io=IO)
check("page-only agent: the first verb on a project with no entry makes the entry from the page text, so the page's agent is in it; the mirror writes both and the page keeps its line",
      list(agents(IOTA)) == ["home-iota-late", "home-iota-main", "home-iota-other"] and res["mirror"]["state"] == "written" and "home-iota-late: added on the page a minute ago" in text("projects/iota")
      and "home-iota-other" in text("projects/iota"), (list(agents(IOTA)), res["mirror"], text("projects/iota")))
res = pv.rename("projects/iota2", "home-iota2b", io=IO)
check("page-only agent: …a rename as the first verb keeps it too", "home-iota2-late" in agents(IOTA2) and "home-iota2-late" in text("projects/iota2") and "display-name: home-iota2b" in text("projects/iota2") and res["mirror"]["state"] == "written", (res["mirror"], text("projects/iota2")))
# the guard: an entry that exists, and a page edited since
q = BRAIN / "projects/iota.md"; q.write_text(q.read_text().replace("  home-iota-other:", "  home-iota-sneak: put there by hand\n  home-iota-other:", 1), encoding="utf-8")
before_t = text("projects/iota")
m = pv.mirror(IOTA, IO)
check("mirror guard: a page that lists a name the record lacks is not written: state failed, the name in the note, the page as it was", m["state"] == "failed" and "home-iota-sneak" in m["note"] and text("projects/iota") == before_t, m)
res = pv.agent_add(IOTA, "home-iota-third", True, "a verb after the hand edit", io=IO)
check("mirror guard: …a verb's own mirror stops there too (the record has its change, the answer says the page was not written, naming the line)", res["mirror"]["state"] == "failed" and "home-iota-third" in agents(IOTA) and text("projects/iota") == before_t, res["mirror"])
res = pv.agent_add(IOTA, "home-iota-sneak", True, "put there by hand", io=IO)
check("mirror guard: …listing the name in the record first lets the mirror go on, and it keeps the line", res["mirror"]["state"] == "written" and "home-iota-sneak: put there by hand" in text("projects/iota") and "home-iota-third" in text("projects/iota"), (res["mirror"], text("projects/iota")))
res = pv.agent_retire(IOTA, "home-iota-sneak", io=IO)
rn_ = pv.agent_rename(IOTA, "home-iota-third", "home-iota-fourth", io=IO)
check("mirror guard: a retire or a rename drops its own name from the page without tripping the guard", res["mirror"]["state"] == "written" and "home-iota-sneak" not in dict(fmagents("projects/iota")[0])
      and rn_["mirror"]["state"] == "written" and "home-iota-fourth" in text("projects/iota") and "home-iota-third" not in text("projects/iota"), (res["mirror"], rn_["mirror"], text("projects/iota")))

# the mirror writes the record as it is now, not the entry a slower verb saw
stale = {IOTA: json.loads(json.dumps(ents()[IOTA]))}
pv.agent_add(IOTA, "home-iota-fresh", True, "after the stale copy was taken", io=IO)
res = pv._finish(IOTA, stale, True, False, IO)
check("a verb that finishes late mirrors the record as it is, not the entry it saw: the later agent stays on the page", res["mirror"]["state"] == "unchanged" and "home-iota-fresh" in text("projects/iota"), (res["mirror"], text("projects/iota")))

# the timeline: every verb of a day makes its line
t0 = text("projects/zeta").count("renamed from")
pv.rename(Z, "home-zeta3", io=IO); pv.rename(Z, "home-zeta4", io=IO)
check("timeline: two renames on one day each leave their line on the page", text("projects/zeta").count("renamed from") == t0 + 2, text("projects/zeta")[-500:])
import time
class TL(Counting):
    def __init__(s, base): super().__init__(base); s.ids = []
    def add_timeline(s, slug, date, summary, detail, source, request_id=""): s.ids.append(request_id); return s.b.add_timeline(slug, date, summary, detail, source, request_id)
tl = TL(IO)
pv.archive(D, why="again", io=tl); time.sleep(1.1); pv.reopen(D, io=tl); time.sleep(1.1); pv.archive(D, why="again", io=tl); time.sleep(1.1); pv.reopen(D, io=tl); time.sleep(1.1)
check("timeline: archive, reopen, archive again on one day: each timeline call has a request id of its own (gbrain drops a repeated one), and the line says what it did", len(tl.ids) == 4 and len(set(tl.ids)) == 4
      and text("projects/delta").count("archived; again") >= 1, (tl.ids, text("projects/delta")[-500:]))
tl2 = TL(IO); pv.rename(Z, "home-zeta5", io=tl2); time.sleep(1.1); pv.rename(Z, "home-zeta6", io=tl2)
check("timeline: two renames on one day have two request ids", len(tl2.ids) == 2 and tl2.ids[0] != tl2.ids[1], tl2.ids)

# a stub that was written but whose id move failed
page("projects/kappa.md", "type: project\ntitle: Kappa\ndisplay-name: home-kappa\nagents:\n  home-kappa-main: talks\nstatus: active"); p.cmd_registry(quiet=True)
def runner_stub_half(args):
    calls.append(args); ph, pair = args[0], args[1]; old, new = pair.split("=")
    if ph == "copy": shutil.copy(BRAIN / (old + ".md"), BRAIN / (new + ".md")); return 0, "copy ok"
    return 1, f"stub {old} → {new}\n  FAIL project id of {old} not moved to {new} (boom); run: python3 projects.py rename {old} {new}"
calls.clear()
res = pv.move_page("projects/kappa", "projects/kappa-new", runner=runner_stub_half, io=IO)
check("move-page: a stub written but exiting 1 (the id move failed) is not an error: the record is made right, the answer carries a warning saying the page was stubbed",
      res["moved"] is True and "was stubbed" in res["warning"] and ents()[res["project"]]["page"] == "projects/kappa-new" and "projects/kappa" in ents()[res["project"]]["former_keys"] and recfile()["ids"][res["project"]] == "projects/kappa-new", res)
page("projects/lambda.md", "type: project\ntitle: Lambda\ndisplay-name: home-lambda\nagents:\n  home-lambda-main: talks\nstatus: active"); p.cmd_registry(quiet=True)
def runner_stub_refused(args):
    calls.append(args)
    if args[0] == "copy": return 0, "copy ok"
    return 1, "FAIL stub: still pointing at the old key, move these first (items: update(project=<new key>); anchors: add under the new key, remove under the old):"
try: pv.move_page("projects/lambda", "projects/lambda-new", runner=runner_stub_refused, io=IO)
except pv.VerbError as e: ve = (e.status, e.message)
else: ve = (0, "")
check("move-page: a stub that refused is a 502 saying the page was not stubbed and naming the retry with --phase stub; the entry keeps the old page", ve[0] == 502 and "was not stubbed" in ve[1] and "--phase stub" in ve[1]
      and ents()[pv.pid_of("projects/lambda")]["page"] == "projects/lambda", ve)

# ---- 10c. round 2: no page read inside a lock; former_agents expire; the guard stops only the agents block; the stub warning needs the whole stub
page("projects/slowp.md", "type: project\ntitle: Slow\ndisplay-name: home-slowp\nagents:\n  home-slowp-main: talks\nstatus: active"); p.cmd_registry(quiet=True)
SLOWP = {k: e["id"] for k, e in reg().items()}["projects/slowp"]
class Slow(Counting):
    """A page store whose read takes `nap` seconds (a gbrain read can take a minute)."""
    def __init__(s, base, nap): super().__init__(base); s.nap = nap
    def get(s, k):
        r = super().get(k); time.sleep(s.nap); return r
NAP = 3.0
slow = Slow(IO, NAP); got = {}
def first_verb(): got["res"] = pv.agent_add("projects/slowp", "home-slowp-eng", False, "builds", io=slow)
th = threading.Thread(target=first_verb); th.start()
time.sleep(0.5)                                         # the verb is now inside its slow page read
t0 = time.monotonic(); prj.ensure_ids(["projects/alpha"]); waited = time.monotonic() - t0
th.join()
check("no page read inside the record lock: a second writer (ensure_ids) is not held up by a verb's slow page read (it waited far under the read's sleep)", waited < NAP / 3, (waited, NAP))
check("no page read inside the record lock: the verb itself still made the entry from the page and mirrored", list(agents(SLOWP)) == ["home-slowp-main", "home-slowp-eng"] and got["res"]["mirror"]["state"] == "written", (agents(SLOWP), got))
# the read that failed: the answer says so, the entry is made from the registry's row, the guard keeps the page safe
class Dead(Counting):
    def get(s, k):
        if k == "projects/deadp" and not getattr(s, "armed", False): s.armed = True; raise OSError("gbrain is not answering")
        return super().get(k)
page("projects/deadp.md", "type: project\ntitle: Dead\ndisplay-name: home-deadp\nagents:\n  home-deadp-main: talks\nstatus: active"); p.cmd_registry(quiet=True)
DEADP = {k: e["id"] for k, e in reg().items()}["projects/deadp"]
q = BRAIN / "projects/deadp.md"; q.write_text(q.read_text().replace("  home-deadp-main", "  home-deadp-late: added a minute ago\n  home-deadp-main", 1), encoding="utf-8")
res = pv.agent_add("projects/deadp", "home-deadp-eng", False, "builds", io=Dead(IO))
check("a pre-read that fails: the answer carries a warning, the entry comes from the registry's row, and the mirror leaves the page's own agent line alone (guard)",
      "could not be read" in res.get("warning", "") and res["mirror"]["state"] == "failed" and "home-deadp-late" in res["mirror"]["note"] and "home-deadp-late: added a minute ago" in text("projects/deadp"), (res.get("warning"), res["mirror"]))
# the server's helper path: pre-read before _PROJECT_LOCK
import server
page("projects/srvp.md", "type: project\ntitle: Srv\ndisplay-name: home-srvp\nagents:\n  home-srvp-main: talks\nstatus: active"); p.cmd_registry(quiet=True)
pre_slow = Slow(IO, NAP); res_pre = {}
def do_pre(): res_pre["p"] = pv.preread("projects/srvp", pre_slow)
th = threading.Thread(target=do_pre); th.start(); time.sleep(0.5)
t0 = time.monotonic(); prj.ensure_ids(["projects/alpha"]); waited = time.monotonic() - t0
with server._PROJECT_LOCK: pass                       # the server's lock is free while the pre-read waits on the page store
waited2 = time.monotonic() - t0
th.join()
check("preread: reads the page before any lock: a second record writer and the server's project lock are not held up by the slow read, and it returns the page text by key",
      waited < NAP / 3 and waited2 < NAP / 3 and list(res_pre["p"]) == ["projects/srvp"] and "home-srvp-main" in res_pre["p"]["projects/srvp"], (waited, waited2, res_pre))
check("preread: a project with an entry, an unknown name and a sub-page's key read nothing", pv.preread(A, Counting(IO)) == {} and pv.preread("home-nosuch", Counting(IO)) == {} and pv.preread(SUB, Counting(IO)) == {})

# fix 1: a name leaves former_agents once a mirror has written the page without it
page("projects/rho.md", "type: project\ntitle: Rho\ndisplay-name: home-rho\nagents:\n  home-rho-main: talks\n  home-rho-gone: leaves\nstatus: active"); p.cmd_registry(quiet=True)
RHO = {k: e["id"] for k, e in reg().items()}["projects/rho"]
res = pv.agent_retire(RHO, "home-rho-gone", io=Counting(IO, "refused"))
check("former_agents: a retire whose page write was refused keeps the name in former_agents (the page still lists it, the guard needs it)", res["mirror"]["state"] == "failed" and "home-rho-gone" in ents()[RHO].get("former_agents", []) and "home-rho-gone" in text("projects/rho"), (res["mirror"], ents()[RHO]))
m = pv.mirror(RHO, IO)
check("former_agents: the next mirror writes the page without it and drops the name from former_agents", m["state"] == "written" and "home-rho-gone" not in text("projects/rho") and "former_agents" not in ents()[RHO], (m, ents()[RHO]))
res = pv.agent_rename(RHO, "home-rho-main", "home-rho-lead", io=IO)
check("former_agents: a rename that wrote the page leaves no former name behind either", res["mirror"]["state"] == "written" and "former_agents" not in ents()[RHO], ents()[RHO])
res = pv.agent_add(RHO, "home-rho-eng", False, "builds", io=IO)
q = BRAIN / "projects/rho.md"; q.write_text(q.read_text().replace("  home-rho-eng", "  home-rho-gone: back by hand\n  home-rho-eng", 1), encoding="utf-8")
m = pv.mirror(RHO, IO)
check("former_agents: once expired, the name is a stranger again: a hand edit that lists it is held by the guard", m["state"] == "failed" and "home-rho-gone" in m["note"], m)

# fix 2: the guard stops only the agents block; the name and status lines are written, the answer still says failed
page("projects/sig.md", "type: project\ntitle: Sig\ndisplay-name: home-sig\nagents:\n  home-sig-main: talks\nstatus: active"); p.cmd_registry(quiet=True)
SIG = {k: e["id"] for k, e in reg().items()}["projects/sig"]
pv.agent_add(SIG, "home-sig-eng", False, "builds", io=IO)
q = BRAIN / "projects/sig.md"; q.write_text(q.read_text().replace("  home-sig-eng", "  home-sig-hand: by hand\n  home-sig-eng", 1), encoding="utf-8")
res = pv.archive(SIG, why="paused", io=IO)
t = text("projects/sig")
check("guard: archive on a page with a hand-added agent writes the status line, leaves the agents block (the hand-added line stays), and the answer says failed naming the name",
      res["mirror"]["state"] == "failed" and "home-sig-hand" in res["mirror"]["note"] and "home-sig-hand: by hand" in t and re.search(r"(?m)^status: (archived|closed|done)", t) is not None, (res["mirror"], t))
res = pv.rename(SIG, "home-sig2", io=IO)
t = text("projects/sig")
check("guard: a rename writes the display-name line too, and still says failed naming the extra name", res["mirror"]["state"] == "failed" and "home-sig-hand" in res["mirror"]["note"] and "display-name: home-sig2" in t and "home-sig-hand: by hand" in t, (res["mirror"], t))
res = pv.agent_add(SIG, "home-sig-hand", False, "by hand", io=IO)
check("guard: listing the name with agent-add clears it: the mirror is written, and the next one finds nothing to do", res["mirror"]["state"] == "written" and pv.mirror(SIG, IO)["state"] == "unchanged", res["mirror"])

# fix 3: a stub that exited 1 is a warning only when every page of the plan was stubbed
page("projects/nu.md", "type: project\ntitle: Nu\ndisplay-name: home-nu\nagents:\n  home-nu-main: talks\nstatus: active"); page("projects/nu/kid.md", "type: note\ntitle: Kid"); p.cmd_registry(quiet=True)
def runner_children(stub_out):
    def r(args):
        calls.append(args); ph, pair = args[0], args[1]; old, new = pair.split("=")
        if ph == "copy": return 0, f"copy {old} → {new}\ncopy {old}/kid → {new}/kid"
        return 1, stub_out(old, new)
    return r
calls.clear(); rb = recsha()
top_only = runner_children(lambda o, n: f"stub {o} → {n}\n  FAIL stub {o}/kid: the gbrain call failed")
try: pv.move_page("projects/nu", "projects/nu-new", runner=top_only, io=IO)
except pv.VerbError as e: ve = (e.status, e.message)
else: ve = (0, "")
check("move-page: the top page stubbed but its child not: a 502 that says so and names the retry with --phase stub; the record is not changed", ve[0] == 502 and "not every page under it" in ve[1] and "--phase stub" in ve[1] and ents()[pv.pid_of("projects/nu")]["page"] == "projects/nu", ve)
top_only_id = runner_children(lambda o, n: f"stub {o} → {n}\n  FAIL project id of {o} not moved to {n} (boom)")
try: pv.move_page("projects/nu", "projects/nu-new", runner=top_only_id, io=IO)
except pv.VerbError as e: ve = (e.status, e.message)
else: ve = (0, "")
check("move-page: the plan listed a child and the stub output never mentions it: still a 502, even though the only FAIL line is about the id move", ve[0] == 502 and "not every page under it" in ve[1] and ents()[pv.pid_of("projects/nu")]["page"] == "projects/nu", ve)
whole = runner_children(lambda o, n: f"stub {o}/kid → {n}/kid\nstub {o} → {n}\n  FAIL project id of {o} not moved to {n} (boom)")
res = pv.move_page("projects/nu", "projects/nu-new", runner=whole, io=IO)
check("move-page: every page stubbed and the only FAIL the id move: the warning, the record made right", res["moved"] is True and "was stubbed" in res["warning"] and ents()[res["project"]]["page"] == "projects/nu-new", res)
page("projects/xi.md", "type: project\ntitle: Xi\ndisplay-name: home-xi\nstatus: active"); page("projects/xi/kid.md", "type: note\ntitle: Kid"); p.cmd_registry(quiet=True)
skipped = runner_children(lambda o, n: f"skip {o}/kid: already a redirect\nstub {o} → {n}\n  FAIL project id of {o} not moved to {n} (boom)")
res = pv.move_page("projects/xi", "projects/xi-new", runner=skipped, io=IO)
check("move-page: a child that was a redirect already counts as done", res["moved"] is True and "was stubbed" in res["warning"], res)

# ---- 11. the CLI
rc, out, err = tool("tools/project.py", "show", "home-sparrow")
check("cli: show names the project, its page and its agents", rc == 0 and A in out and "projects/alpha" in out and "home-sparrow-main" in out, (rc, out[:400], err[:300]))
rb = recsha()
rc, out, err = tool("tools/project.py", "--dry-run", "agent-add", "home-sparrow", "home-sparrow-cli", "--front", "--mandate", "added by the cli")
check("cli: --dry-run says what it would do and writes nothing", rc == 0 and recsha() == rb and "home-sparrow-cli" not in agents(A), (rc, out[:300], err[:300]))
rc, out, err = tool("tools/project.py", "agent-add", "home-sparrow", "home-sparrow-cli", "--front", "--mandate", "added by the cli")
check("cli: agent-add writes the record and the page", rc == 0 and agents(A).get("home-sparrow-cli") == (True, "added by the cli") and "home-sparrow-cli" in text("projects/alpha"), (rc, out[:300], err[:300]))
rc, out, err = tool("tools/project.py", "agent-mandate", "home-sparrow", "home-sparrow-cli", "--mandate", "changed by the cli")
check("cli: agent-mandate changes the record's line and the page follows", rc == 0 and agents(A).get("home-sparrow-cli") == (True, "changed by the cli") and "home-sparrow-cli: changed by the cli" in text("projects/alpha"), (rc, out[:300], err[:300]))
rc, out, err = tool("tools/project.py", "agent-mandate", "home-sparrow", "home-sparrow-cli", "--mandate", "  ")
check("cli: agent-mandate with an empty line exits non-zero and says it is empty", rc != 0 and "empty" in (out + err) and agents(A).get("home-sparrow-cli") == (True, "changed by the cli"), (rc, out[:300], err[:300]))
rc, out, err = tool("tools/project.py", "agent-mandate", "home-sparrow", "home-sparrow-nobody", "--mandate", "x")
check("cli: agent-mandate for an unlisted agent exits non-zero and says it is not listed", rc != 0 and "not listed" in (out + err), (rc, out[:300], err[:300]))
rc, out, err = tool("tools/project.py", "create", "home-clip", "--scope", "home")
check("cli: create with no page makes a project with no page", rc == 0 and any(e.get("name") == "home-clip" and "page" not in e for e in ents().values()), (rc, out[:300], err[:300]))
rc, out, err = tool("tools/project.py", "create", "home-clis", "--scope", "home", "--page", SUB)
check("cli: create on a sub-page key exits non-zero and says why, nothing written", rc != 0 and "sub-page" in (out + err) and not any(e.get("name") == "home-clis" for e in ents().values()), (rc, out[:300], err[:300]))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
