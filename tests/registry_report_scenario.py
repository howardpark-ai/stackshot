"""Scenario test for the daily audit's project registry check (tools/registry_report.py, `audit.py registry`, the registry stage of audit_run.py) — made-up pages, record, sessions and items; no live store, no network,
no server process (the page store is the plain markdown folder of a temporary config).

Covers: an empty project record is not checked at all and is silent (an instance that has not made its record would read every page as "no project"); a fixture store whose record was made by `adopt` and `create` then
broken one way at a time: a `type: project` page that no entry points at is flagged with the `adopt` command (and `--name`) as its fix, and a completed page, a note, a sub-page and a former page of a project are not;
a project whose page is gone from the store is flagged (not an archived one, not one whose read failed through the store's own getter, not one the registry still has, nothing when the published registry is empty); the
page stores' `get_strict` (a file or a gbrain call that fails raises, only a clean "not found" is no page); a page whose mirrored lines were edited (display-name, status, an agent the record lacks) is flagged with `mirror` as
its fix, and says which lines; a project with no page of this store whose agents sala does not know, and a pending agent sala does not know, are flagged with `agent-retire`, while an agent of a project with a page is
page_agent_report's line and not repeated, and a cut-short session list checks none; open items on a project id that is in neither the entries nor the id table (an id the id table knows, and a completed item, are not), and
open items on a key no project owns (a key a project owns as a sub-page or a former key is not, a no-project page's items are one line, not two); two live entries on one page (not when one is archived). No `parent:` check
(nothing in the registry reads the line). Each finding goes to its project's -main agent when sala knows it, else the page's fallbacks, and to nobody (the result is `unrouted`) when sala's list cannot be read. A source that
cannot be read (sala, the page store, the items) skips only its checks and says so. The CLI in a subprocess, `--line`, `--json` and the listing agree. The audit's run has its section in tests/audit_run_scenario.py.

    tests/run-suite registry_report        -> exit 0 / 1"""
import hashlib, json, logging, os, pathlib, re, subprocess, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="rgreport-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
(T / "home").mkdir()
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet", HOME=str(T / "home")); os.environ.pop("STACKSHOT_URL", None)
os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "brain/ops", "brain/infra", "secrets"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text("{}")
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
BRAIN = T / "brain"
def page(rel, front, body="# x\n"):
    q = BRAIN / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n" + body, encoding="utf-8")
def text(rel): return (BRAIN / (rel + ".md")).read_text(encoding="utf-8")
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools")); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def tool(script, *args):
    r = subprocess.run([sys.executable, f"{STACK}/{script}"] + list(args), capture_output=True, text=True, env=os.environ, cwd=str(T))
    return r.returncode, r.stdout, r.stderr

# ---- the pages: nothing is a project yet
page("projects/alpha.md", "type: project\ntitle: Alpha\ndisplay-name: home-sparrow\nagents:\n  home-sparrow-main: talks to Oliver\n  home-sparrow-docs: keeps the docs\n"
                          "  background:\n    home-sparrow-engineer: builds and merges\nstatus: active")
page("projects/beta.md", "type: project\ntitle: Beta\ndisplay-name: home-beta\nagents:\n  home-beta-main: does it\nstatus: active")      # never adopted
page("projects/beta/sub.md", "type: project\ntitle: Beta sub\nparent: projects/beta")
page("projects/done.md", "type: project\ntitle: Done\ndisplay-name: home-done\nstatus: completed")                                        # retired, never adopted
page("projects/plain-note.md", "type: note\ntitle: A note")
page("projects/drifty.md", "type: project\ntitle: Drifty\ndisplay-name: home-drifty\nagents:\n  home-drifty-main: does it\nstatus: active")
page("projects/extra.md", "type: project\ntitle: Extra\ndisplay-name: home-extra\nagents:\n  home-extra-main: does it\nstatus: active")
page("projects/vanish.md", "type: project\ntitle: Vanish\ndisplay-name: home-vanish\nagents:\n  home-vanish-main: does it\nstatus: active")
page("projects/arch.md", "type: project\ntitle: Arch\ndisplay-name: home-arch\nstatus: completed")
page("projects/twin.md", "type: project\ntitle: Twin\ndisplay-name: home-twin\nstatus: active")
page("projects/alpha/okchild.md", "type: note\ntitle: Child\nparent: projects/alpha")

from stackshot.projects import pages as p; from stackshot.projects import projects as prj; from stackshot.projects import project_registry as pr; from stackshot.projects import project_verbs as pv; from stackshot.router import page_debt; from stackshot.anchors import anchors as anc
from stackshot.tools import registry_report as rr
p.cmd_registry(quiet=True)
IO = page_debt.PlainIO()
def ents(): return pr.entries()
def reg(): return prj.registry_raw()
LIVE = ({"home-sparrow-main", "home-sparrow-docs", "home-sparrow-engineer", "home-beta-main", "home-drifty-main", "home-extra-main", "home-vanish-main", "home-pl-main"}, set())
def getter(key): return IO.get(key)
def run(**kw):
    a = dict(ents=ents(), reg=reg(), sessions=LIVE, items=[], pending={}, page_get=getter)
    a.update(kw); return rr.scan(**a)
def pv_err_read(fn):
    try: fn(); return False
    except OSError: return True
def by(res, line): return [f for f in res["findings"] if f["line"] == line]
def pages_of(res, line): return sorted(f["page"] for f in by(res, line))

# ---- 1. an empty record is not checked, and is silent
res = run()
check("empty record: not checked, silent, no finding (every page would read as a page with no project)", res["checked"] is False and res.get("silent") is True and res["findings"] == [], res)
check("empty record: read() says the same on the live sources", rr.read(sessions=lambda: LIVE, items=[], pending={})["silent"] is True)

# ---- 2. the record is made: alpha, drifty, extra, vanish, arch, twin adopted; a project with no page
for k, n in (("alpha", "home-sparrow"), ("drifty", "home-drifty"), ("extra", "home-extra"), ("vanish", "home-vanish"), ("arch", "home-arch"), ("twin", "home-twin")):
    pv.adopt(f"projects/{k}", by="home-sparrow-main", io=IO, now="2026-11-06T01:00:00Z")
ID = {e["name"]: pid for pid, e in ents().items()}
PL = pv.create("home-pl", "home", by="home-sparrow-main", io=IO, now="2026-11-06T01:10:00Z")["project"]
pv.agent_add(PL, "home-pl-main", True, "talks to Oliver", by="home-sparrow-main", io=IO, now="2026-11-06T01:11:00Z")
pv.agent_add(PL, "home-pl-gone", False, "was renamed", by="home-sparrow-main", io=IO, now="2026-11-06T01:12:00Z")
p.cmd_registry(quiet=True)
res = run()
check("a clean store: the record is checked; the only problems are the ones built in below (nothing about alpha, which mirrors its entry)", res["checked"] is True and res["projects"] == len(ents())
      and not [f for f in res["findings"] if f["page"] == "projects/alpha"], res["findings"])

# ---- 3. a page with no project
npp = by(res, rr.LINE_NO_PROJECT)
check("no project: an active type-project page no entry points at is flagged, with the adopt command as the fix", [f["page"] for f in npp] == ["projects/beta"] and "tools/project.py adopt projects/beta" in npp[0]["fix"], npp)
check("no project: the fix names --name for a page whose name line is missing, invalid or taken", "--name" in npp[0]["fix"], npp[0]["fix"])
check("no project: …not a completed page, a note, a sub-page, nor a page that has an entry", all(f["page"] not in ("projects/done", "projects/plain-note", "projects/beta/sub", "projects/alpha") for f in npp))
pr.update(lambda E: E[ID["home-twin"]].setdefault("former_keys", []).append("projects/beta"))
check("no project: a page that is a project's former page is not flagged either (it has a history)", by(run(), rr.LINE_NO_PROJECT) == [])
pr.update(lambda E: E[ID["home-twin"]]["former_keys"].remove("projects/beta"))
check("no project: …and back again once it is not", pages_of(run(), rr.LINE_NO_PROJECT) == ["projects/beta"])

# ---- 4. page lines that differ
check("drift: a store that mirrors its record has none", by(run(), rr.LINE_DRIFT) == [], by(run(), rr.LINE_DRIFT))
page("projects/drifty.md", text("projects/drifty").split("---\n")[1].replace("display-name: home-drifty", "display-name: home-drift-edit").replace("status: active", "status: paused").rstrip("\n"))
p.cmd_registry(quiet=True)
dr = by(run(), rr.LINE_DRIFT)
check("drift: an edit to a mirrored line is flagged on that page, naming the lines, with mirror as the fix and the project", [f["page"] for f in dr] == ["projects/drifty"] and "display-name" in dr[0]["name"]
      and f"tools/project.py mirror {ID['home-drifty']}" in dr[0]["fix"] and dr[0]["project"] == ID["home-drifty"], dr)
check("drift: …the check wrote nothing (the page keeps the edit)", "home-drift-edit" in text("projects/drifty"))
pv.mirror(ID["home-drifty"], IO)
check("drift: after the mirror writes the record's lines again, it is gone", by(run(), rr.LINE_DRIFT) == [])
page("projects/extra.md", text("projects/extra").split("---\n")[1].replace("  home-extra-main: does it\n", "  home-extra-main: does it\n  home-extra-added: an agent only the page knows\n").rstrip("\n"))
p.cmd_registry(quiet=True)
ex = by(run(), rr.LINE_DRIFT)
check("drift: an agent the page lists and the record lacks is flagged on that page (the mirror cannot write the block)", [f["page"] for f in ex] == ["projects/extra"], ex)
page("projects/extra.md", text("projects/extra").split("---\n")[1].replace("  home-extra-added: an agent only the page knows\n", "").rstrip("\n"))
p.cmd_registry(quiet=True)

# ---- 5. a project whose page is gone
os.remove(BRAIN / "projects/vanish.md"); p.cmd_registry(quiet=True)
gone = by(run(), rr.LINE_GONE)
check("gone: a project whose page is in neither the registry nor the page store is flagged, with its id and how to restore or make the page", [f["page"] for f in gone] == ["projects/vanish"] and gone[0]["project"] == ID["home-vanish"]
      and "mirror" in gone[0]["fix"] and "--make-page" in gone[0]["fix"], gone)
os.remove(BRAIN / "projects/arch.md"); p.cmd_registry(quiet=True)
check("gone: an archived project's missing page is not a problem", "projects/arch" not in pages_of(run(), rr.LINE_GONE), pages_of(run(), rr.LINE_GONE))
def failing(key):
    if key == "projects/vanish": raise OSError("the store could not be reached")
    return IO.get(key)
res_f = run(page_get=failing)
check("gone: a page whose read fails is not gone (a read that fails says nothing), and the note says a page could not be read", "projects/vanish" not in pages_of(res_f, rr.LINE_GONE) and "could not be read" in res_f["note"], (pages_of(res_f, rr.LINE_GONE), res_f["note"]))
ghost = {**reg(), "projects/vanish": {"type": "project", "status": "active", "title": "Vanish"}}
check("gone: a page the registry still has is not gone (a registry that lags is one witness, not two)", "projects/vanish" not in pages_of(run(reg=ghost), rr.LINE_GONE))
res_n = run(page_get=None)
check("page store unreadable: pages and mirrors are skipped with a note, the other checks still run", not by(res_n, rr.LINE_GONE) and not by(res_n, rr.LINE_DRIFT) and "page store is not readable" in res_n["note"] and by(res_n, rr.LINE_NO_PROJECT), res_n["note"])

# ---- 5b. a read that fails, and a registry that was not published
ok_p = BRAIN / "projects/unreadable.md"; ok_p.mkdir(parents=True, exist_ok=True)       # a directory where the file should be: the read fails, the page is not "missing"
check("page store: get_strict says (None, None) for a page that is not there and raises for a read that failed", IO.get_strict("projects/never-was") == (None, None) and pv_err_read(lambda: IO.get_strict("projects/unreadable")))
ok_p.rmdir()
import json as _json; from stackshot.projects import rename_page as _rpg
_real_gb = _rpg.gb
def _fake_gb(answer, rc=0):
    return lambda args, stdin=None, slug=None: (rc, answer)
try:
    _rpg.gb = _fake_gb(_json.dumps({"content": "---\ntype: project\n---\n", "revision": "r1"}))
    ok_c = page_debt.GbrainIO().get_strict("projects/x")
    _rpg.gb = _fake_gb(_json.dumps({"error": "page_not_found", "message": "Page not found: projects/x"}), 1)
    ok_n = page_debt.GbrainIO().get_strict("projects/x")
    bad = []
    for ans, rc in (("", 1), ("gbrain: connection refused", 1), (_json.dumps({"error": "database is locked"}), 1), ("not json at all", 0)):
        _rpg.gb = _fake_gb(ans, rc)
        bad.append(pv_err_read(lambda: page_debt.GbrainIO().get_strict("projects/x")))
    def _boom(args, stdin=None, slug=None): raise subprocess.TimeoutExpired("gbrain", 1)
    _rpg.gb = _boom
    bad.append(pv_err_read(lambda: page_debt.GbrainIO().get_strict("projects/x")))
finally:
    _rpg.gb = _real_gb
check("gbrain store: get_strict gives the page, and (None, None) only for a clean 'not found'; an empty answer, a refused connection, any other error, text that is no JSON and a timeout raise (the old get read them all as no page)",
      ok_c[1] == "r1" and ok_n == (None, None) and all(bad), (ok_c, ok_n, bad))
(BRAIN / "projects/vanish.md").mkdir()           # a directory where the page file should be
res_u = run(page_get=page_debt.PlainIO().get_strict)
(BRAIN / "projects/vanish.md").rmdir()
check("gone: a page whose read fails through the store's own getter is not gone (the failure is recorded) and the note says so", "projects/vanish" not in pages_of(res_u, rr.LINE_GONE) and "could not be read" in res_u["note"], (pages_of(res_u, rr.LINE_GONE), res_u["note"]))
res_e = run(reg={})
check("gone: with an empty published registry no page is gone (nothing says the pages exist, or do not), and the note says so", not by(res_e, rr.LINE_GONE) and "page registry is empty" in res_e["note"], res_e["note"])

# ---- 6. agents on no live session
ag = by(run(), rr.LINE_AGENT)
check("agents: an agent of a project with no page of this store that sala does not know is flagged with agent-retire (and agent-rename), named by the project's name; the live one is not",
      [(f["name"], f["page"]) for f in ag] == [("home-pl-gone", "home-pl")] and f"agent-retire {PL} home-pl-gone" in ag[0]["fix"] and "agent-rename" in ag[0]["fix"] and ag[0]["project"] == PL, ag)
prj.add_pending(ID["home-sparrow"], "home-sparrow-wait", {"front": False, "role": "w", "mandate_line": "pending"}, by="home-sparrow-main", at="2026-11-05T00:00:00Z")
ag2 = by(run(pending=prj._pending_all()), rr.LINE_AGENT)
check("agents: a pending agent sala does not know is flagged, with its agent-retire fix and the 'page line was never written' reason", any(f["name"] == "home-sparrow-wait" and "pending agent" in f["fix"] and "agent-retire" in f["fix"] for f in ag2), ag2)
check("agents: …a mirrored agent of a project with a page is page_agent_report's line, not repeated here", not any(f["name"] in ("home-extra-main", "home-vanish-main", "home-sparrow-docs") for f in ag2) and not any(f["name"].startswith("home-drifty") for f in ag2))
live2 = (LIVE[0] | {"home-pl-gone", "home-sparrow-wait"}, set())
check("agents: sessions sala lists (or an alias of one) are known", by(run(sessions=live2, pending=prj._pending_all()), rr.LINE_AGENT) == [])
res_a = run(sessions=(LIVE[0], {"home-pl-gone"}))
check("agents: an alias counts as known", "home-pl-gone" not in {f["name"] for f in by(res_a, rr.LINE_AGENT)})
res_s = run(sessions=None); res_e = run(sessions=(set(), set()))
check("agents: sala's list unreadable or empty: no agent is checked, the note says so, the other checks still run", not by(res_s, rr.LINE_AGENT) and "not readable" in res_s["note"] and not by(res_e, rr.LINE_AGENT) and "lists no session" in res_e["note"] and by(res_s, rr.LINE_NO_PROJECT))
big = {f"home-pl-agent{i}": {"front": False, "mandate_line": "x", "role": "x"} for i in range(12)}
pr.update(lambda E: E[PL]["agents"].update(big))
res_p = run(sessions=({"home-pl-main", "home-pl-gone", "home-sparrow-main"}, set()))
check("agents: a session list that does not know most names is cut short: no agent is flagged and the note says so (page_agent_report's guard)", not by(res_p, rr.LINE_AGENT) and "looks partial" in res_p["note"], (res_p["note"], len(by(res_p, rr.LINE_AGENT))))
pr.update(lambda E: [E[PL]["agents"].pop(n) for n in big])

# ---- 7. items
LONELY = "prj_0000a10e"
_d = json.loads((T / "store/project-record.json").read_text()); _d["ids"][LONELY] = "projects/lonely"; (T / "store/project-record.json").write_text(json.dumps(_d))   # an id in the id table with no entry
IT = [
    {"gid": "1", "status": "open", "metadata": {"project": "projects/alpha", "project_id": ID["home-sparrow"]}},
    {"gid": "2", "status": "open", "metadata": {"project": "projects/old", "project_id": "prj_0000d00d"}},
    {"gid": "3", "status": "open", "metadata": {"project": "projects/old", "project_id": "prj_0000d00d"}},
    {"gid": "4", "status": "open", "metadata": {"project": "projects/nobody"}},
    {"gid": "5", "status": "completed", "metadata": {"project": "projects/nobody-either"}},
    {"gid": "6", "status": "open", "metadata": {"project": "projects/alpha/okchild"}},
    {"gid": "7", "status": "open", "metadata": {"project": "projects/beta"}},
    {"gid": "8", "status": "open", "metadata": {"project": "projects/nobody"}},
    {"gid": "9", "status": "open", "metadata": {"project": "projects/lonely", "project_id": LONELY}},
    {"gid": "10", "status": "completed", "metadata": {"project": "projects/old", "project_id": "prj_0000d00d"}},
]
res_i = run(items=IT)
idf, keyf = by(res_i, rr.LINE_ID), by(res_i, rr.LINE_KEY)
check("items: an id the record's id table knows (a project with no entry) is no problem, and a completed item with an unknown id is none either: only the two open items on prj_0000d00d are named", len(idf) == 1 and idf[0]["name"] == "prj_0000d00d on 2, 3", idf)
check("items: items that store a project id no entry has are one line, naming the id and the items, with re-file as the fix", len(idf) == 1 and "prj_0000d00d" in idf[0]["name"] and "2" in idf[0]["name"] and "3" in idf[0]["name"] and "update" in idf[0]["fix"], idf)
check("items: open items on a key no project owns are one line per key with their count; a completed item, a sub-page of a project and a no-project page's items (that page has its own line) are not", [f["page"] for f in keyf] == ["projects/nobody"]
      and "2 open items" in keyf[0]["name"] and "adopt projects/nobody" in keyf[0]["fix"], keyf)
check("items: …the board items unreadable skips only the item checks, with a note", not by(run(items=None), rr.LINE_ID) and "items could not be read" in run(items=None)["note"])

# ---- 8. two projects on one page
pr.update(lambda E: E.__setitem__("prj_0000c0de", {**json.loads(json.dumps(E[ID["home-twin"]])), "name": "home-twin-two"}))
two = by(run(), rr.LINE_TWO)
check("two on one page: two entries that point at one page are one line naming both, with archive or move-page as the fix", len(two) == 1 and two[0]["page"] == "projects/twin" and "prj_0000c0de" in two[0]["name"] and ID["home-twin"] in two[0]["name"]
      and "archive" in two[0]["fix"] and "move-page" in two[0]["fix"], two)
pr.update(lambda E: E["prj_0000c0de"].update(status="archived"))
check("two on one page: …but not when one of the two is archived (it keeps the pointer as history)", by(run(), rr.LINE_TWO) == [])
pr.update(lambda E: E.pop("prj_0000c0de"))
check("two on one page: …and none once the stray is gone", by(run(), rr.LINE_TWO) == [])

# ---- 10. who is told
OV = anc.registry()
def routed(live, **kw):
    res = run(sessions=(live, set()), **kw)
    return {(f["line"], f["page"]): f["to"] for f in rr.route(res, ents(), OV, (live, set()))["findings"]}, res
to, _ = routed(LIVE[0] | {"home-pl-gone"}, items=IT)
check("routing: a finding on a project goes to that project's -main agent when sala knows it", to.get((rr.LINE_GONE, "projects/vanish")) == "home-vanish-main", to)
check("routing: a page with no project goes to its own -main agent (page_agent_report's route)", to.get((rr.LINE_NO_PROJECT, "projects/beta")) == "home-beta-main", to)
to2, _ = routed(LIVE[0] - {"home-vanish-main"}, items=IT)
check("routing: a project whose -main agent sala does not know goes to a fallback sala knows, or to nobody (the audit then uses its own -main agent), never to the gone name", to2.get((rr.LINE_GONE, "projects/vanish")) in ("",) + tuple(LIVE[0]) and to2.get((rr.LINE_GONE, "projects/vanish")) != "home-vanish-main", to2)
to3, _ = routed(LIVE[0])
check("routing: a project with no page tells its own front agent when sala knows it", to3.get((rr.LINE_AGENT, "home-pl")) == "home-pl-main", to3)

res_un = rr.route(run(sessions=None, items=IT), ents(), OV, None)
res_em = rr.route(run(sessions=(set(), set()), items=IT), ents(), OV, (set(), set()))
check("routing: when sala's list cannot be read, or lists no session, nobody is known to be live: every finding has an empty recipient and the result is marked unrouted (the audit sends nothing)",
      res_un["findings"] and res_un["unrouted"] is True and all(f["to"] == "" for f in res_un["findings"]) and res_em["unrouted"] is True and all(f["to"] == "" for f in res_em["findings"]), (res_un["unrouted"], res_em["unrouted"]))
check("routing: …with a list sala gave, the result is not unrouted", rr.route(run(items=IT), ents(), OV, LIVE)["unrouted"] is False)
res_rd = rr.read(ents=ents(), reg=reg(), ov=OV, sessions=lambda: None, items=IT, pending={}, page_get=getter)
check("read: sala unreadable gives the findings with no recipient and the not-checked note for the agents only", res_rd["unrouted"] is True and res_rd["findings"] and "not readable" in res_rd["note"] and by(res_rd, rr.LINE_NO_PROJECT), res_rd["note"])

# ---- 11. the lines the audit carries
res_c = run(items=IT)
check("summary line: the count of problems and pages, and the note when there is one", rr.summary_line(res_c).startswith("Project registry: ") and f"{len(res_c['findings'])} problem(s)" in rr.summary_line(res_c))
check("summary line: a check that was not made says so", rr.summary_line({"checked": False, "note": "the project record has no projects", "findings": []}) == "Project registry: not checked (the project record has no projects)")
check("line_of: page · problem · name · fix", rr.line_of(res_c["findings"][0]).count(" · ") == 3)

# ---- 12. the CLI: audit.py registry, in a subprocess on the same store
SESS = T / "sessions.json"
SESS.write_text(json.dumps({"schema": 1, "sessions": [{"name": n, "aliases": [], "state": "live"} for n in sorted(LIVE[0])]}))
rec_before = (T / "store/project-record.json").read_bytes()
rc, out, err = tool("stackshot/audit/audit.py", "registry", "--sessions", str(SESS))
check("cli: the listing has one line per problem, with whom it goes to, then the counts; exit 0", rc == 0 and "projects/beta · page with no project · " in out and "tools/project.py adopt projects/beta" in out
      and "Project registry: " in out.splitlines()[-1] and " · tell " in out, (rc, out[:600], err[:300]))
rc, out2, err = tool("stackshot/audit/audit.py", "registry", "--line", "--sessions", str(SESS))
check("cli: --line is the one line the audit carries", rc == 0 and out2.startswith("Project registry: ") and len(out2.strip().splitlines()) == 1, (rc, out2, err[:300]))
rc, out3, err = tool("stackshot/audit/audit.py", "registry", "--json", "--sessions", str(SESS))
try: js = json.loads(out3)
except ValueError: js = {}
check("cli: --json is the whole report, and it agrees with the line", rc == 0 and js.get("checked") is True and f"{len(js['findings'])} problem(s)" in out2 and all("to" in f and "fix" in f for f in js["findings"]), (rc, out3[:300], err[:300]))
check("cli: it is read only: the record is as it was", (T / "store/project-record.json").read_bytes() == rec_before)
rc, out4, err = tool("stackshot/audit/audit.py", "registry", "--sessions", str(T / "no-such-file.json"))
check("cli: a sessions file that cannot be read is a check not made for the agents (a note), not a failure", rc == 0 and "Project registry: " in out4, (rc, out4[:300], err[:300]))
rc, out5, err = tool("stackshot/audit/audit.py", "nonsense")
check("cli: audit.py's usage names the registry verb", rc == 2 and "registry [--line|--json]" in err, (rc, err[:300]))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
