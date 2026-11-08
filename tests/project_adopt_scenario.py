"""Scenario test for `adopt` (project_verbs.adopt, tools/project.py adopt): fixture pages, no live store, no network, no server process (the page store is the plain markdown folder of a temporary config).

Covers: a dry run writes nothing; adopting a top-level `type: project` page that has no project makes the entry from the page (the name from its display-name: line, the scope the registry derives, the status,
the agents with the front and background split, the page key) with `made` = who, when, `how: adopted` and the revision of the page that was read; the id the id table already had is kept; the pending agents are
folded in and cleared; the project is listed on purpose; the mirror finds a page that already says it right and leaves its bytes alone; afterwards a page edit to a mirrored line is not read (the entry wins);
a completed page gives an archived entry; a page with no display-name line gets the scope's name for the slug and the mirror writes the line; --name and --scope override; refused: a second adopt of the same page
(409), a former page of another project (409), a name another project has (409), a sub-page, a page below a sub-page, a page with a hub: line, a link, no page, a key outside the page dirs, a page that is not
type project, a bad display-name, a bad scope or name (400), a missing page (404); and the CLI in a subprocess on the same temporary config.

    tests/run-suite project_adopt        -> exit 0 / 1"""
import hashlib, json, logging, os, pathlib, re, subprocess, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="prjadopt-"); T = pathlib.Path(tmp)
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
page("projects/zeta.md", "type: project\ntitle: Zeta\ndisplay-name: home-zeta\nstatus: completed")
page("ops/zeta-tool.md", "type: project\ntitle: Zeta tool\ndisplay-name: home-zeta-tool\nhub: projects/zeta")
page("projects/gamma.md", "type: project\ntitle: Gamma\ndisplay-name: home-gamma\nagents:\n  home-gamma-main: does it\nstatus: active")
page("projects/noname.md", "type: project\ntitle: No name\nstatus: active")
page("projects/badname.md", "type: project\ntitle: Bad name\ndisplay-name: has a space!\nstatus: active")
page("projects/plain-note.md", "type: note\ntitle: A note")
page("projects/moved.md", "type: project\ntitle: Moved\ndisplay-name: home-moved\nstatus: active")
page("projects/prior.md", "type: project\ntitle: Prior\ndisplay-name: home-prior\nstatus: active")
page("projects/twice.md", "type: project\ntitle: Twice\ndisplay-name: home-twice\nstatus: active")
page("projects/cli-one.md", "type: project\ntitle: Cli one\ndisplay-name: home-cli-one\nstatus: active")
page("projects/cli-two.md", "type: project\ntitle: Cli two\ndisplay-name: home-cli-two\nstatus: active")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
def sha(b): return hashlib.sha256(b).hexdigest()
REC = T / "store/project-record.json"
def recfile(): return json.loads(REC.read_text()) if REC.exists() else {}
def recsha(): return sha(REC.read_bytes()) if REC.exists() else ""
def tool(script, *args):
    r = subprocess.run([sys.executable, f"{STACK}/{script}"] + list(args), capture_output=True, text=True, env=os.environ, cwd=str(T))
    return r.returncode, r.stdout, r.stderr

from stackshot.projects import pages as p; from stackshot.projects import projects as prj; from stackshot.projects import project_registry as pr; from stackshot.projects import project_verbs as pv; from stackshot.router import page_debt
p.cmd_registry(quiet=True)
IO = page_debt.PlainIO()
def pv_err(fn):
    try: fn(); return 0, ""
    except pv.VerbError as e: return e.status, e.message
def ents(): return pr.entries()
def pagebytes(rel): return (BRAIN / (rel + ".md")).read_bytes()
def idtable(): return {k: e["id"] for k, e in json.loads((T / "store/projects.json").read_text())["pages"].items()}
AID = idtable().get("projects/alpha", "")
check("setup: the pages make a registry with ids, and the record has no project yet", prj.is_id(AID) and not ents(), (AID, ents()))
prj.add_pending(AID, "home-sparrow-x", {"front": True, "role": "x", "mandate_line": "a pending one"}, by="home-sparrow-main", at="2026-11-01T00:00:00Z")

# ---- 1. a dry run writes nothing
r0, b0 = recsha(), pagebytes("projects/alpha")
res = pv.adopt("projects/alpha", by="home-sparrow-main", io=IO, now="2026-11-06T01:00:00Z", dry=True)
check("dry run: says what it would make (the entry, adopted) and writes neither the record nor the page", res.get("adopted") is True and res["entry"]["name"] == "home-sparrow" and recsha() == r0
      and pagebytes("projects/alpha") == b0 and not ents(), res)

# ---- 2. adopt a page with agents, a name and a pending agent
res = pv.adopt("projects/alpha", by="home-sparrow-main", io=IO, now="2026-11-06T01:00:00Z")
E = ents(); pid = res["project"]; e = E.get(pid) or {}
check("adopt: the entry exists under the id the id table had for the page", pid == AID and e, (res, sorted(E)))
check("adopt: name from the display-name: line, a scope the registry derives, status active, the page as the pointer",
      e.get("name") == "home-sparrow" and e.get("scope") in prj.scopes() and e.get("status") == "active" and e.get("page") == "projects/alpha", e)
check("adopt: made = who, when, how adopted, and the revision of the page that was read", (e.get("made") or {}).get("by") == "home-sparrow-main" and e["made"].get("at") == "2026-11-06T01:00:00Z"
      and e["made"].get("how") == "adopted" and e["made"].get("revision") == res["revision"] and res["revision"], e.get("made"))
names = list((e.get("agents") or {}))
check("adopt: the page's agents are in the entry, the background one marked as such, and the pending agent is folded in after them",
      names[:3] == ["home-sparrow-main", "home-sparrow-docs", "home-sparrow-engineer"] and "home-sparrow-x" in names
      and e["agents"]["home-sparrow-engineer"]["front"] is False and e["agents"]["home-sparrow-main"]["front"] is True and e["agents"]["home-sparrow-x"]["front"] is True, e.get("agents"))
check("adopt: the pending table is cleared for the project and the id table maps the id to the page", AID not in (recfile().get("pending_agents") or {}) and recfile()["ids"][AID] == "projects/alpha",
      recfile().get("pending_agents"))
check("adopt: the project is listed on purpose (the mark carries who and when)", recfile()["marks"][AID].get("on_purpose") == "2026-11-06T01:00:00Z" and recfile()["marks"][AID].get("by") == "home-sparrow-main",
      recfile().get("marks"))
check("adopt: the mirror ran: the folded agent is on the page now and the name line is as it was", res["mirror"]["state"] == "written" and "home-sparrow-x" in pagebytes("projects/alpha").decode()
      and "display-name: home-sparrow\n" in pagebytes("projects/alpha").decode(), res["mirror"])
st, msg = pv_err(lambda: pv.adopt("projects/alpha", io=IO))
check("adopt: said again on the same page: 409 naming the project", st == 409 and AID in msg, (st, msg))
p.cmd_registry(quiet=True)
page("projects/alpha.md", text("projects/alpha").split("---\n")[1].replace("display-name: home-sparrow", "display-name: home-edited").rstrip("\n"))
p.cmd_registry(quiet=True)
check("after adopt: a page edit to a mirrored line is not read, the entry wins", prj.registry()["projects/alpha"]["session"] == "home-sparrow", prj.registry()["projects/alpha"].get("session"))

# ---- 3. a page that already says what the entry says is left byte for byte
b1 = pagebytes("projects/gamma")
res = pv.adopt("projects/gamma", by="home-sparrow-main", io=IO, now="2026-11-06T02:00:00Z")
check("adopt: a page whose lines already read as the entry says is not rewritten (mirror unchanged, same bytes)", res["mirror"]["state"] == "unchanged" and pagebytes("projects/gamma") == b1, res["mirror"])

# ---- 4. a completed page, a page with no name line
res = pv.adopt("projects/zeta", by="home-sparrow-main", io=IO, now="2026-11-06T02:10:00Z")
ez = ents()[res["project"]]
check("adopt: a completed page gives an archived entry that says it was retired by adoption", ez.get("status") == "archived" and (ez.get("retired") or {}).get("how") == "adopted", ez)
res = pv.adopt("projects/noname", by="home-sparrow-main", io=IO, now="2026-11-06T02:20:00Z")
en = ents()[res["project"]]
check("adopt: a page with no display-name: line gets the scope's name for its slug, and the mirror writes the line",
      en.get("name") and en["name"] == prj.display_name_for("projects/noname", en["scope"]) and f"display-name: {en['name']}" in pagebytes("projects/noname").decode() and res["mirror"]["state"] == "written",
      (en.get("name"), res["mirror"]))

# ---- 5. refusals and overrides
page("projects/clash.md", "type: project\ntitle: Clash\ndisplay-name: HOME-SPARROW\nstatus: active"); p.cmd_registry(quiet=True)   # the name line of a project already made
rb = recsha()
st, msg = pv_err(lambda: pv.adopt("projects/clash", io=IO))
check("refused: a name another project has (case folded) is a 409 that names the way out (--name), nothing written", st == 409 and "--name" in msg and recsha() == rb, (st, msg))
res = pv.adopt("projects/clash", name="home-clash", scope="work", by="home-sparrow-main", io=IO, now="2026-11-06T02:30:00Z")
ec = ents()[res["project"]]
check("--name and --scope override the page: the entry carries them and the mirror puts the name on the page",
      ec["name"] == "home-clash" and ec["scope"] == "work" and "display-name: home-clash" in pagebytes("projects/clash").decode(), (ec, res["mirror"]))
rb = recsha()
st, msg = pv_err(lambda: pv.adopt("projects/alpha/sub", io=IO))
check("refused: a sub-page (400, says so), a page below a sub-page (400)", st == 400 and "sub-page" in msg and pv_err(lambda: pv.adopt("projects/alpha/deeper/leaf", io=IO))[0] == 400 and recsha() == rb, (st, msg))
check("refused: a page with a hub: line that makes it a sub-page (400)", pv_err(lambda: pv.adopt("ops/zeta-tool", io=IO))[0] == 400 and recsha() == rb, pv_err(lambda: pv.adopt("ops/zeta-tool", io=IO)))
check("refused: a link (400), no page (400), a key outside the page dirs (400)", pv_err(lambda: pv.adopt("https://notes.example.org/x", io=IO))[0] == 400 and pv_err(lambda: pv.adopt("", io=IO))[0] == 400
      and pv_err(lambda: pv.adopt("elsewhere/page", io=IO))[0] == 400 and recsha() == rb)
st, msg = pv_err(lambda: pv.adopt("projects/plain-note", io=IO))
check("refused: a page that is not type project (400, says what to set), a missing page (404)", st == 400 and "type: project" in msg and pv_err(lambda: pv.adopt("projects/nowhere", io=IO))[0] == 404 and recsha() == rb, (st, msg))
check("refused: a display-name that is no agent prefix (400) unless --name is given", pv_err(lambda: pv.adopt("projects/badname", io=IO))[0] == 400 and recsha() == rb)
check("refused: a bad scope and a bad --name (400)", pv_err(lambda: pv.adopt("projects/badname", name="home-ok", scope="nowhere", io=IO))[0] == 400
      and pv_err(lambda: pv.adopt("projects/badname", name="bad name", io=IO))[0] == 400 and recsha() == rb)
made = pv.adopt("projects/prior", by="home-sparrow-main", io=IO, now="2026-11-06T02:40:00Z")["project"]
check("refused: a page a project already points at (409)", pv_err(lambda: pv.adopt("projects/prior", io=IO))[0] == 409)
pr.update(lambda E_: E_[made].setdefault("former_keys", []).append("projects/moved"))
st, msg = pv_err(lambda: pv.adopt("projects/moved", io=IO))
check("refused: a page that is a former page of another project (409), and it says so", st == 409 and "former page" in msg, (st, msg))
ok = pv.adopt("projects/twice", by="home-sparrow-main", io=IO, now="2026-11-06T03:00:00Z")
check("adopt: after the refusals an ordinary page still adopts", ok["adopted"] is True and ents()[ok["project"]]["name"] == "home-twice", ok)

# ---- 6. the CLI
rb = recsha()
rc, out, err = tool("stackshot/tools/project.py", "--dry-run", "adopt", "projects/cli-one")
check("cli: --dry-run adopt says what it would do and writes nothing", rc == 0 and recsha() == rb and "dry run: adopt prj_" in out and "projects/cli-one" in out, (rc, out[:300], err[:300]))
rc, out, err = tool("stackshot/tools/project.py", "adopt", "projects/cli-one")
check("cli: adopt makes the project", rc == 0 and any(v.get("name") == "home-cli-one" and (v.get("made") or {}).get("how") == "adopted" for v in ents().values()), (rc, out[:300], err[:300]))
rc, out, err = tool("stackshot/tools/project.py", "adopt", "projects/cli-one")
check("cli: adopt again exits non-zero and says the page is a project's already", rc != 0 and "already" in (out + err), (rc, out[:300], err[:300]))
rc, out, err = tool("stackshot/tools/project.py", "adopt", "projects/cli-two", "--name", "home-cli-renamed", "--scope", "work")
check("cli: --name and --scope reach the entry", rc == 0 and any(v.get("name") == "home-cli-renamed" and v.get("scope") == "work" for v in ents().values()), (rc, out[:300], err[:300]))
rc, out, err = tool("stackshot/tools/project.py", "adopt", "projects/alpha/sub")
check("cli: a sub-page exits non-zero and says why", rc != 0 and "sub-page" in (out + err), (rc, out[:300], err[:300]))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
