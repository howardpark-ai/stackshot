"""Scenario test for the shared mark on a brain, the retired copy of the record onto pages, and the read-through (brains.shared_refusal, page_debt.BrainIO,
project_verbs.mirror / copy_off, projects.fields, `projects fields`, server._owed_mark): fixture data in a scratch folder, no live store, no network, never the
real gbrain CLI (a fake one answers a read from the brain's copy and logs every call that is not a read: a write for a shared page never reaches it).

Covers: a `[[brains]]` entry marked `shared = true` (and `[gbrain] shared = true` for the default brain) makes every page-store write for its slugs (put, create, a timeline
line) refuse with a line that names the mark, leaves the page file as it was, and never calls the gbrain CLI; an unmarked brain writes as before; a project verb on a
shared page writes the record and answers mirror state "retired" with the reason, no page is made for `make_page`, and the same verb on a page of the unmarked brain still
writes the lines; `[pages] copy_project_lines = false` retires the copy on every brain with one switch (the record is right, the page is not touched; a new project's page is still made on an unshared brain with
none of the copied lines, and nothing is made on a shared brain) and turning it back on
writes the lines from the record; a page of a shared brain owes no page update (`_owed_mark` charges nothing, `_owed_settle` drops a debt charged before the mark);
config.notes names a `shared` or `copy_project_lines` that is not a boolean; `projects.fields` reads the record first and the page's lines for a project the record does
not cover (with the source of each field), keeps answering after the page's lines stop being written, resolves a sub-page to its owner and a project with no page, and the
CLI `projects fields` prints it (exit 0 found, 1 unknown).

    tests/run-suite shared_brain        -> exit 0 / 1"""
import copy, shutil, json, logging, os, pathlib, re, subprocess, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="sharedbrain-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^bin = "[^"]*"', f'bin = "{tmp}/fake-gbrain"', toml); assert n == 1
toml += f'''
[[brains]]
name = "shared-notes"
path = "{tmp}/shared"
home = "{tmp}/home-shared"
prefixes = ["projects/shr-"]
shared = true

[[brains]]
name = "own-notes"
path = "{tmp}/own"
home = "{tmp}/home-own"
slugs = ["projects/own-one"]
'''
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
CALLS = T / "gbrain-calls.jsonl"
(T / "fake-gbrain").write_text(f'''#!{sys.executable}
import json, pathlib, sys
a = sys.argv[1:]
if a[:2] == ["call", "get_page"]:     # a read answers from the brain's copy; only the calls that are not reads are logged
    slug = json.loads(a[2])["slug"]
    for root in ("shared", "own"):
        f = pathlib.Path({tmp!r}, root, slug + ".md")
        if f.exists():
            print(json.dumps({{"content": f.read_text(), "revision": "r1"}})); sys.exit(0)
    print(json.dumps({{"code": "page_not_found"}})); sys.exit(0)
open({str(CALLS)!r}, "a").write(json.dumps(a) + "\\n")
sys.exit(2)
'''); os.chmod(T / "fake-gbrain", 0o755)
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.pop("CLAUDE_CODE_SESSION_ID", None); os.environ.pop("GBRAIN_HOME", None)
for d in ("store/a", "fleet/a", "state", "brain/projects", "shared/projects", "own/projects", "secrets", "touch", "home-shared", "home-own"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text("{}")
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
def page(root, rel, front, body="# x\n"):
    q = T / root / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n" + body, encoding="utf-8")
def text(root, rel): return (T / root / (rel + ".md")).read_text(encoding="utf-8")
page("brain", "projects/alpha.md", "type: project\ntitle: Alpha\ndisplay-name: home-sparrow\nagents:\n  home-sparrow-main: talks to Pat\nstatus: active")
page("brain", "projects/alpha/sub.md", "type: project\ntitle: Sub")
page("brain", "projects/gamma.md", "type: project\ntitle: Gamma\ndisplay-name: home-gamma\nagents:\n  home-gamma-main: does it\nstatus: active")
page("brain", "projects/delta.md", "type: project\ntitle: Delta\ndisplay-name: home-delta\nstatus: active")
page("brain", "projects/epsilon.md", "type: project\ntitle: Epsilon\ndisplay-name: home-eps\nagents:\n  home-eps-main: only on the page\nstatus: active")
page("shared", "projects/shr-one.md", "type: project\ntitle: Shared one\ndisplay-name: home-shr\nagents:\n  home-shr-main: talks to Sam\nstatus: active")
page("shared", "projects/shr-two.md", "type: project\ntitle: Shared two\ndisplay-name: home-shr2\nstatus: active")
page("own", "projects/own-one.md", "type: project\ntitle: Own one\ndisplay-name: home-own\nagents:\n  home-own-main: mine\nstatus: active")
git = lambda d, *a: subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@example.com", *a], check=True, capture_output=True)
for d in ("brain", "shared", "own"):
    git(T / d, "init", "-q"); git(T / d, "add", "-A"); git(T / d, "commit", "-qm", "pages")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
def calls(): return CALLS.read_text().splitlines() if CALLS.exists() else []

from stackshot.core import config as _cfg
from stackshot.projects import brains, pages as p, projects as prj, project_registry as pr, project_verbs as pv
from stackshot.router import page_debt
p.cmd_registry(quiet=True)
IO = page_debt.page_io()
REC = T / "store/project-record.json"
def ents(): return pr.entries()
def agents(pid): return {n: (a["front"], a["mandate_line"]) for n, a in (ents()[pid].get("agents") or {}).items()}
def pid_of(key): return json.loads((T / "store/projects.json").read_text())["pages"][key]["id"]

# ---- 1. the mark and its loader
check("the mark: an entry with shared = true is shared; one without it is not; the default brain is not", brains.for_key("projects/shr-one").shared and not brains.for_key("projects/own-one").shared
      and not brains.for_key("projects/alpha").shared and not brains.default().shared, [(b.name, b.shared) for b in brains.all_brains()])
why = brains.shared_refusal("projects/shr-one")
check("the refusal names the brain and the mark, and a page of an unmarked brain has none", "shared-notes" in why and "shared = true" in why and brains.shared_refusal("projects/own-one") == "" and brains.shared_refusal("projects/alpha") == "", why)
check("the mark: a sub-page of a shared slug is shared too", brains.shared_refusal("projects/shr-one/notes") != "")
check("the page store is the brain-aware one", type(IO).__name__ == "BrainIO", type(IO).__name__)

# ---- 2. every write for a shared page refuses, and the CLI is never called
before = text("shared", "projects/shr-one")
st, msg = IO.put("projects/shr-one", before + "\nBoard line.\n", "rev")
check("put on a shared page: refused with the mark's line, the page as it was, no CLI call", st == "refused" and "shared = true" in msg and text("shared", "projects/shr-one") == before and calls() == [], (st, msg, calls()))
st, msg = IO.create("projects/shr-two/new", "---\ntitle: x\n---\n")
check("create under a shared page: refused, nothing made", st == "refused" and "shared = true" in msg and not (T / "shared/projects/shr-two/new.md").exists() and calls() == [], (st, msg, calls()))
note = IO.add_timeline("projects/shr-one", "2026-11-08", "a board line", "detail", "stackshot", "rid-1")
check("a timeline line on a shared page: refused with the mark's line, nothing written", "shared = true" in note and text("shared", "projects/shr-one") == before and calls() == [], (note, calls()))
CALLS.write_text("")
st, msg = IO.put("projects/gamma", text("brain", "projects/gamma") + "\n- a line\n", page_debt.PlainIO().get("projects/gamma")[1])
check("put on a page of the default brain still writes", st == "ok" and "- a line" in text("brain", "projects/gamma"), (st, msg))
st, msg = IO.put("projects/own-one", "x", "rev")
check("put on a page of an unmarked second brain goes to its CLI as before (the fake CLI fails: that is the CLI's refusal, not the mark's)", "shared = true" not in msg and calls() != [], (st, msg, calls()))
CALLS.write_text("")

# ---- 3. a project verb on a shared page: the record is right, the page is not touched
bytes_before = (T / "shared/projects/shr-one.md").read_bytes()
res = pv.agent_add("projects/shr-one", "home-shr-docs", True, "keeps the docs", by="home-shr-main", io=IO)
S1 = res["project"]
check("agent_add on a shared page: the record holds the agent and the old ones, the mirror state is retired and its note names the mark",
      agents(S1).get("home-shr-docs") == (True, "keeps the docs") and "home-shr-main" in agents(S1) and res["mirror"]["state"] == "retired" and "shared = true" in res["mirror"]["note"], res)
check("…the shared page is byte for byte as it was and the CLI was not called", (T / "shared/projects/shr-one.md").read_bytes() == bytes_before and calls() == [], calls())
res = pv.rename("projects/shr-one", "home-shr-renamed", io=IO)
check("rename on a shared page: the record has the new name, the page keeps its own line", ents()[S1]["name"] == "home-shr-renamed" and res["mirror"]["state"] == "retired" and "display-name: home-shr\n" in text("shared", "projects/shr-one"), res["mirror"])
res = pv.create("home-shr-new", "home", page="projects/shr-fresh", make_page=True, io=IO)
check("create with make_page for a page of a shared brain: the project is made, the page is not (retired)", res["mirror"]["state"] == "retired"
      and ents()[res["project"]]["page"] == "projects/shr-fresh" and not (T / "shared/projects/shr-fresh.md").exists() and calls() == [], (res["mirror"], calls()))
m = pv.mirror(S1, IO)
check("mirror() by hand says the same and writes nothing", m["state"] == "retired" and (T / "shared/projects/shr-one.md").read_bytes() == bytes_before, m)

# ---- 4. the control: the same verb on an unmarked page writes the lines
A = pid_of("projects/alpha")
res = pv.agent_add("projects/alpha", "home-sparrow-docs", True, "keeps the docs", by="home-sparrow-main", io=IO)
check("control: agent_add on a page of the default brain writes the page's agents block from the record", res["mirror"]["state"] == "written" and "home-sparrow-docs: keeps the docs" in text("brain", "projects/alpha"), res["mirror"])

# ---- 5. one switch retires the copy on every brain
G = pid_of("projects/gamma")
_cfg.CFG.setdefault("pages", {})["copy_project_lines"] = False
gamma_before = (T / "brain/projects/gamma.md").read_bytes()
res = pv.agent_add("projects/gamma", "home-gamma-docs", True, "keeps the docs", by="home-gamma-main", io=IO)
check("copy_project_lines = false: the record has the agent, the mirror state is retired with the switch named, the page is untouched",
      agents(G).get("home-gamma-docs") == (True, "keeps the docs") and res["mirror"]["state"] == "retired" and "copy_project_lines" in res["mirror"]["note"]
      and (T / "brain/projects/gamma.md").read_bytes() == gamma_before, (res["mirror"], text("brain", "projects/gamma")))
res = pv.agent_add("projects/alpha", "home-sparrow-eng", False, "builds", by="home-sparrow-main", io=IO)
check("…on the default brain's other page too (every brain)", res["mirror"]["state"] == "retired" and "home-sparrow-eng" not in text("brain", "projects/alpha"), res["mirror"])
check("…and a dry-run mirror of a page does not report drift either (nothing to write)", pv.mirror(G, IO, dry=True)["state"] == "retired")
# page creation does not depend on the switch: a new project's page is made on an unshared brain, with none of the copied lines written, and a shared brain gets nothing
CALLS.write_text("")
res = pv.create("home-offsw-name", "home", page="projects/offsw-one", make_page=True, io=IO)
OF = res["project"]; ofpage = (T / "brain/projects/offsw-one.md")
check("copy_project_lines = false: create with make_page makes the page on the default brain (state written, the note says the copy is retired)",
      res["mirror"]["state"] == "written" and "copy_project_lines" in res["mirror"]["note"] and ofpage.exists() and ents()[OF]["page"] == "projects/offsw-one", (res["mirror"], ofpage.exists()))
body = ofpage.read_text(encoding="utf-8") if ofpage.exists() else ""
check("…the page is the template's skeleton: its sections are there, no agents block, and the record's name is not copied onto it",
      all(h in body for h in ("## Goal", "## Current state", "## Decisions", "## Open questions", "## Open work", "## Where things are", "## Timeline")) and "agents:" not in body
      and "display-name: home-offsw-name" not in body and "status: active" in body, body[:600])
check("…and the record holds the project's own name", ents()[OF]["name"] == "home-offsw-name")
rev = ofpage.read_bytes()
res = pv.agent_add("projects/offsw-one", "home-offsw-name-main", True, "talks", by="x", io=IO)
check("…a later verb copies nothing onto it (retired), the record has the agent, the page is as it was", res["mirror"]["state"] == "retired" and "home-offsw-name-main" in agents(OF) and ofpage.read_bytes() == rev, res["mirror"])
m = pv.mirror(OF, IO, make_page=True)
check("…mirror with make_page on a page that is there changes nothing (retired)", m["state"] == "retired" and ofpage.read_bytes() == rev, m)
res = pv.create("home-offsw-two", "home", by="x", io=IO)
m = pv.mirror(res["project"], IO, make_page=True)
check("…a project with no page has none made by mirror", m["state"] == "none" and not (T / "brain/projects/home-offsw-two.md").exists(), m)
pid2 = pv.create("home-offsw-three", "home", page="projects/offsw-three", io=IO)["project"]
m = pv.mirror(pid2, IO, make_page=True, dry=True)
check("…mirror --make-page --dry-run for a pointed page that is not there says would-write and writes nothing", m["state"] == "would-write" and not (T / "brain/projects/offsw-three.md").exists(), m)
m = pv.mirror(pid2, IO)
check("…without make_page a page that is not there stays unmade (retired: the copy is off)", m["state"] == "retired" and not (T / "brain/projects/offsw-three.md").exists(), m)
m = pv.mirror(pid2, IO, make_page=True)
check("…mirror --make-page for a pointed page that is not there makes it", m["state"] == "written" and (T / "brain/projects/offsw-three.md").exists() and "agents:" not in text("brain", "projects/offsw-three"), m)
shr_before = {f.name for f in (T / "shared/projects").iterdir()}
res = pv.create("home-offsw-shr", "home", page="projects/shr-offsw", make_page=True, io=IO)
check("…on a shared brain nothing is made with the switch off either: retired, no file, no CLI call",
      res["mirror"]["state"] == "retired" and "shared = true" in res["mirror"]["note"] and {f.name for f in (T / "shared/projects").iterdir()} == shr_before and calls() == [], (res["mirror"], calls()))
_cfg.CFG.setdefault("gbrain", {})["shared"] = True
res = pv.create("home-offsw-dflt", "home", page="projects/offsw-dflt", make_page=True, io=page_debt.page_io())
_cfg.CFG["gbrain"].pop("shared")
check("…nor on the default brain when it is marked shared", res["mirror"]["state"] == "retired" and "[gbrain] shared = true" in res["mirror"]["note"] and not (T / "brain/projects/offsw-dflt.md").exists(), res["mirror"])
_cfg.CFG["pages"]["copy_project_lines"] = True
res = pv.create("home-onsw-name", "home", page="projects/onsw-one", make_page=True, io=IO)
check("control, switch on: create with make_page still makes the page and writes the record's name onto it",
      res["mirror"]["state"] == "written" and "display-name: home-onsw-name" in text("brain", "projects/onsw-one"), (res["mirror"], text("brain", "projects/onsw-one")))
m = pv.mirror(G, IO)
check("switch back on: the next mirror writes the page from the record, the agent added meanwhile included", m["state"] == "written" and "home-gamma-docs: keeps the docs" in text("brain", "projects/gamma"), (m, text("brain", "projects/gamma")))
m = pv.mirror(S1, IO)
check("…and a shared page stays retired whatever the switch says", m["state"] == "retired", m)

# ---- 6. the default brain marked shared ([gbrain] shared = true)
_cfg.CFG.setdefault("gbrain", {})["shared"] = True
io2 = page_debt.page_io()
dstate = io2.put("projects/delta", "x", "rev")
check("[gbrain] shared = true: a write for a page of the default brain is refused with the mark named", dstate[0] == "refused" and "[gbrain] shared = true" in dstate[1], dstate)
D = pid_of("projects/delta")
res = pv.agent_add("projects/delta", "home-delta-main", True, "talks", by="x", io=io2)
check("…and the verbs retire the copy there", res["mirror"]["state"] == "retired" and "agents:" not in text("brain", "projects/delta"), res["mirror"])
_cfg.CFG["gbrain"].pop("shared")
check("…and unmarking it writes again", brains.shared_refusal("projects/delta") == "" and pv.mirror(D, page_debt.page_io())["state"] == "written")

# ---- 7. a shared page owes no page update to a session
from stackshot.web import server
server._owed_mark("projects/shr-one", "agent-one", "board#N", settle="ct")
server._owed_mark("projects/own-one", "agent-one", "board#N", settle="ct")
owed = server._owed_load()
check("pages owed: nothing is charged on a page of a shared brain, a page of an unmarked brain is charged as before", "projects/shr-one" not in owed and "projects/own-one" in owed, list(owed))
owed["projects/shr-two"] = {"agent-two": {"ts": 1.0, "item": "board#N", "settle": "ct"}}; server._owed_save(owed)
left = server._owed_settle()
check("…a debt charged before the mark was set is dropped at the next settle", "projects/shr-two" not in left and "projects/shr-two" not in server._owed_load(), (list(left), list(server._owed_load())))

# ---- 8. config.notes
cfg = copy.deepcopy(_cfg.CFG)
cfg["brains"][0]["shared"] = "yes"; cfg.setdefault("gbrain", {})["shared"] = "no"; cfg.setdefault("pages", {})["copy_project_lines"] = "off"
nt = [n for n in _cfg.notes(cfg) if "shared" in n or "copy_project_lines" in n]
check("config.notes names a shared that is not a boolean (entry and default brain) and a copy_project_lines that is not", sum("[[brains]] shared-notes shared" in n for n in nt) == 1 and sum("[gbrain] shared" in n for n in nt) == 1
      and sum("copy_project_lines" in n for n in nt) == 1, nt)
check("…and a string is no mark: it is read as not shared", not brains._flag("yes") and brains._flag(True))
check("…the real config has none of those notes", not [n for n in _cfg.notes() if "shared" in n or "copy_project_lines" in n], _cfg.notes())

# ---- 9. the read-through
p.cmd_registry(quiet=True)
f = prj.fields("projects/epsilon")
check("fields: a project the record does not cover is read from its page's lines, each field marked page", f and f["source"] == "page" and f["display_name"] == "home-eps" and f["status"] == "active"
      and list(f["agents"]) == ["home-eps-main"] and f["agents"]["home-eps-main"]["front"] is True and f["main"] == "home-eps-main"
      and f["from"] == {"display_name": "page", "status": "page", "agents": "page"}, f)
fa = prj.fields("projects/alpha")
check("fields: a project with an entry is read from the record (the agent added there, marked record)", fa["source"] == "record" and fa["from"]["agents"] == "record" and "home-sparrow-docs" in fa["agents"]
      and "home-sparrow-eng" in fa["agents"] and fa["agents"]["home-sparrow-eng"]["front"] is False and fa["display_name"] == "home-sparrow", fa)
fs = prj.fields(S1)
check("fields: the shared page's project answers from the record, its renamed name and new agent included, though its page lines say the old", fs["display_name"] == "home-shr-renamed" and "home-shr-docs" in fs["agents"]
      and fs["from"]["display_name"] == "record" and "home-shr-docs" not in text("shared", "projects/shr-one"), fs)
check("fields: by id, by bare slug and by page key give one answer", prj.fields(A)["key"] == "projects/alpha" == prj.fields("alpha")["key"] == prj.fields("projects/alpha")["key"])
_cfg.CFG["pages"]["copy_project_lines"] = False
res = pv.agent_add("projects/epsilon", "home-eps-eng", False, "builds", by="home-eps-main", io=IO)
f2 = prj.fields("projects/epsilon")
check("fields: after the copy is retired a verb's change reaches the reader at once, and the page's line is still the old one", res["mirror"]["state"] == "retired" and "home-eps-eng" in f2["agents"]
      and f2["source"] == "record" and "home-eps-eng" not in text("brain", "projects/epsilon") and "home-eps-main" in f2["agents"], (f2, text("brain", "projects/epsilon")))
_cfg.CFG["pages"]["copy_project_lines"] = True
fsub = prj.fields("projects/alpha/sub")
check("fields: a sub-page names the page it belongs to as owner_key", fsub and fsub["sub_page"] is True and fsub["owner_key"] == "projects/alpha" and fa["owner_key"] == "projects/alpha", fsub)
check("fields: a project nothing names is None", prj.fields("projects/no-such-page") is None and prj.fields(A[:-1] + ("0" if A[-1] != "0" else "1")) is None)
res = pv.create("home-nopage", "home", by="x", io=IO)
fn = prj.fields(res["project"])
check("fields: a project with no page is read from the record alone", fn and fn["source"] == "record" and fn["key"] == "" and fn["display_name"] == "home-nopage" and fn["status"] == "active", fn)
allf = prj.all_fields()
keys = {r["key"] for r in allf}
check("all_fields: every page that names a project or lists an agent, and the record's pageless project", {"projects/alpha", "projects/gamma", "projects/epsilon", "projects/shr-one"} <= keys and any(r["id"] == res["project"] for r in allf), sorted(keys))

# ---- 10. the command line
def cli(*a):
    r = subprocess.run([sys.executable, f"{STACK}/stackshot/projects/projects.py", *a], capture_output=True, text=True, env=os.environ, cwd=str(T)); return r.returncode, r.stdout, r.stderr
rc, out, err = cli("fields", "projects/epsilon")
j = json.loads(out) if rc == 0 else {}
check("cli: `projects fields <key>` prints the JSON and exits 0", rc == 0 and j.get("display_name") == "home-eps" and "home-eps-eng" in j.get("agents", {}), (rc, out[:300], err[:300]))
rc, out, err = cli("fields", "projects/no-such-page")
check("cli: an unknown project exits 1 and says so on stderr, nothing on stdout", rc == 1 and out == "" and "no project" in err, (rc, out, err))
rc, out, err = cli("fields", "--all")
check("cli: --all prints a JSON list", rc == 0 and isinstance(json.loads(out), list) and len(json.loads(out)) >= 5, (rc, out[:200], err[:200]))
rc, out, err = cli("fields")
check("cli: no project is the usage, exit 1", rc == 1 and "projects fields" in err, (rc, err))

def cli_with(store, *a):
    """The same command against another store: the config with its `store` line pointed elsewhere."""
    (T / "other.toml").write_text(re.sub(r'(?m)^store = "[^"]*"', f'store = "{store}"', (T / "stackshot.toml").read_text(encoding="utf-8"), count=1), encoding="utf-8")
    r = subprocess.run([sys.executable, f"{STACK}/stackshot/projects/projects.py", *a], capture_output=True, text=True, env={**os.environ, "STACKSHOT_CONFIG": str(T / "other.toml")}, cwd=str(T)); return r.returncode, r.stdout, r.stderr
(T / "store-empty").mkdir()
rc, out, err = cli_with(T / "store-empty", "fields", "projects/epsilon")
check("cli: a registry that cannot be read here (no projects.json in the store) exits 2, nothing on stdout, and says where to run it", rc == 2 and out == "" and "no page registry" in err, (rc, out, err))
shutil.copytree(T / "store", T / "store-bad")
(T / "store-bad/project-record.json").write_text('{"projects": {"', encoding="utf-8")
rc, out, err = cli_with(T / "store-bad", "fields", "projects/epsilon")
check("cli: a corrupt project record exits 2 with the record named on stderr, nothing on stdout", rc == 2 and out == "" and "record" in err, (rc, out[:200], err[:300]))
rc, out, err = cli_with(T / "store-bad", "fields", "--all")
check("cli: --all on a corrupt record exits 2 as well", rc == 2 and out == "", (rc, out[:200], err[:300]))

# ---- 11. a page move and a router note on a shared page
RAN = []
def runner(args): RAN.append(args); return 0, "ok"
shared_two = (T / "shared/projects/shr-two.md").read_bytes()
try: pv.move_page("projects/shr-two", "projects/own-two", runner=runner, io=IO); got = None
except pv.VerbError as e: got = e
check("move_page of a page in a shared brain is refused (403) with the mark's line, no rename step runs, the page is as it was", got is not None and got.status == 403 and "shared = true" in got.message
      and RAN == [] and (T / "shared/projects/shr-two.md").read_bytes() == shared_two and calls() == [], (got and (got.status, got.message), RAN))
try: pv.move_page("projects/shr-two", "projects/own-two", runner=runner, io=IO, dry=True); got = None
except pv.VerbError as e: got = e
check("…a dry run too", got is not None and got.status == 403 and RAN == [], (got and got.message, RAN))
try: pv.move_page("projects/alpha", "projects/shr-moved", runner=runner, io=IO); got = None
except pv.VerbError as e: got = e
check("move_page onto a key of a shared brain is refused too, and the project's page pointer is unchanged", got is not None and got.status == 403 and RAN == [] and pr.page_key(ents()[A]) == "projects/alpha", (got and got.message, RAN))
mv = pv.move_page("projects/gamma", "projects/gamma-moved", runner=runner, io=IO, dry=True)
check("control: a page of the default brain still plans a move", mv["dry"] is True and RAN and RAN[0][0] == "plan", (mv, RAN))

from stackshot.router import router_live
base = {"ruling": "pass", "note": "the router learned something about the page"}
router_live._note(base, "projects/shr-one", "n1")
check("router note on a shared page: skipped quietly, no note_error, not marked noted, the ruling is as it was, nothing reached the CLI", "note_error" not in base and "noted" not in base
      and base["ruling"] == "pass" and base["note"] and calls() == [], (base, calls()))
base = {"ruling": "pass", "note": "the router learned something about the page"}
router_live._note(base, "projects/own-one", "n2")
check("control: a note on a page of an unmarked brain is still tried (the fake CLI refuses it, so it is logged as note_error)", "note_error" in base and "shared = true" not in base["note_error"] and calls() != [], (base, calls()))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
