"""Scenario test: the old name of a session sala renamed stops drawing on the Projects page.

sala keeps the old name of a renamed session as an alias, and the roles file's `live` flag counts aliases, so an agent still held under the old name (a pending agent in the
project record, its page line owed, or a stale line on a page) read as a running agent beside the new name. The old name stops drawing; the new name draws only when a page lists it or
a project's pending map holds it (an old pending entry whose new name is registered nowhere is renamed to it). Covered:

  1  renames_of: an alias that is no session's name and belongs to one session is an old name; a name some session carries now is never one; an alias two sessions claim is left
     alone, however the names are cased; no rows (sala unreadable) give nothing
  2  a rename inside a project: the old name's pending entry goes at the next roles build, the project's other pending agent stays, and the Projects page (table and page) never
     draws the old name, whether the project is a live or an archived one; the new name is drawn because its page lists it
  3  a move between projects: the old project's pending entry for the old name goes, the new project's own pending entry for the new name stays, the Projects page shows the new name
     under the new project and nothing under the old
  4  a name sala lists as a current session, or sala unreadable: nothing is dropped
  5  a page that still lists the old name (nobody edited its line): roles.json carries `renamed_to` for it and the Projects page leaves it out, drawing the new name
  2c a rename cycle (a to b, b to a) leaves the current name's entry and drops the other
  2d a record write that fails (OSError) is logged and the roles are still rebuilt; the next tick settles the entry
  2b a pending entry whose new name is registered nowhere is renamed to it, every field kept, and then draws; an entry registered under ten minutes ago is skipped and the next sweep
     takes it; every drop and rename is logged with the entry's fields and the new name
  6  the repair tool: dry run writes nothing, --apply writes the undo file first and drops exactly the names given, a second --apply is a no-op, --undo puts them back; the undo
     file lists exactly what the record dropped, an entry added after the tool's first read included

A fake `sala` script stands in for the real one (STACKSHOT_SALA); fixture pages, no network.    tests/run-suite renamed_agent_old_name        → exit 0 / 1"""
import contextlib, importlib.util, io, json, os, re, sys, pathlib, logging, stat, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="renamedagent-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), owner=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "brain/infra", "secrets", "bin", "runs", "links"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text("{}")
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")

# the fake sala: mode and the sessions (name + aliases) come from files beside it
FAKE = T / "bin/sala"
FAKE.write_text(f"""#!/usr/bin/env python3
import json, sys
d = {str(T / "bin")!r}
if open(d + "/mode").read().strip() == "fail": sys.exit(3)
rows = json.load(open(d + "/rows.json"))
print(json.dumps({{"schema": 1, "sessions": [{{"id": "id-" + n, "name": n, "state": "live", "aliases": al}} for n, al in rows]}}))
""", encoding="utf-8")
FAKE.chmod(FAKE.stat().st_mode | stat.S_IXUSR)
def sala(rows, mode="ok"):
    (T / "bin/mode").write_text(mode); (T / "bin/rows.json").write_text(json.dumps(rows))
os.environ["STACKSHOT_SALA"] = str(FAKE)

def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
page("projects/ren.md", "type: project\ntitle: Ren proj\ndisplay-name: home-ren\nagents:\n  home-ren-main: talks to the owner\nstatus: active")
page("projects/src.md", "type: project\ntitle: Src proj\ndisplay-name: home-src\nagents:\n  home-src-main: talks to the owner\nstatus: active")
page("projects/dst.md", "type: project\ntitle: Dst proj\ndisplay-name: home-dst\nagents:\n  home-dst-main: talks to the owner\nstatus: active")
page("projects/stale.md", "type: project\ntitle: Stale proj\ndisplay-name: home-stale\nagents:\n  home-stale-main: talks to the owner\n  home-stale-old: the line nobody edited\nstatus: active")
page("projects/arch.md", "type: project\ntitle: Arch proj\ndisplay-name: home-arch\nagents:\n  home-arch-main: was the contact\nstatus: archived")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
from stackshot.projects import pages as p; from stackshot.anchors import anchors as A; from stackshot.projects import projects as prj; from stackshot.fleet import renamed_agents as RA
from stackshot.fleet import clients as C
C._links_dir = lambda: T / "links"               # a configured fleet store: the reader may run the fake sala
from stackshot.web import server
from stackshot.web.ui import render as ui_render
p.cmd_registry(quiet=True)
text = lambda h: re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", h))
def pid(key): return prj.ref(key)["id"]
def pending(key=None):
    d = json.loads((T / "store/project-record.json").read_text()).get("pending_agents", {})
    return {k: set(d.get(pid(k), {})) for k in (key,)}[key] if key else {n for m in d.values() for n in m}
def board(): return ui_render.Board(f"{tmp}/store")
def shown(key, name):
    return any(x[0].split("/", 1)[-1] == name for x in board().project_agents(key)[1])
RJ = T / "state/roles.json"

# ---- 1. renames_of
R1 = [{"name": "home-a-main", "aliases": ["home-a-old", "home-a-older"]}, {"name": "home-b-main", "aliases": ["home-a-old2", "home-b-main"]}, {"name": "home-c-main", "aliases": ["home-a-main"]},
      {"name": "home-d-main", "aliases": ["home-shared"]}, {"name": "home-e-main", "aliases": ["home-shared"]}, {"name": "home-f-main"}, {"name": "", "aliases": ["home-nameless"]}, "junk"]
check("1: an alias no session carries as its name is an old name of its session; one session lists it", RA.renames_of(R1).get("home-a-old") == "home-a-main" and RA.renames_of(R1).get("home-a-older") == "home-a-main", RA.renames_of(R1))
check("1: …a name some session carries now is never an old name (an alias of another session, or a session's own name listed as its alias)", "home-a-main" not in RA.renames_of(R1) and "home-b-main" not in RA.renames_of(R1), RA.renames_of(R1))
check("1: …an alias two sessions claim is left alone; a row with no name or no aliases, and a row that is no object, add nothing", set(RA.renames_of(R1)) == {"home-a-old", "home-a-older", "home-a-old2"}, RA.renames_of(R1))
R1c = [{"name": "Home-X-Main", "aliases": ["home-x-old", "HOME-Y-MAIN"]}, {"name": "home-y-main", "aliases": []}, {"name": "home-z-a", "aliases": ["Home-Z-Old"]}, {"name": "home-z-b", "aliases": ["home-z-old"]}]
check("1: …names compare case-folded: an alias spelled differently from a session's name is still that name, and an alias two sessions claim in different spellings is left alone",
      RA.renames_of(R1c) == {"home-x-old": "Home-X-Main"}, RA.renames_of(R1c))
check("1: …no rows (sala unreadable) give nothing", RA.renames_of(None) == {} and RA.renames_of([]) == {})

# ---- the fixture: pending agents in the record
add = lambda key, name, front=True: prj.add_pending(pid(key), name, {"front": front, "role": name.split("-")[-1], "mandate_line": "m"}, by="fleet-web", at="2026-11-01T00:00:00Z")
add("projects/ren", "home-ren-old"); add("projects/ren", "home-ren-extra", False); add("projects/ren", "home-ren-reused")
add("projects/src", "home-src-moved"); add("projects/dst", "home-dst-moved")
check("(setup) the record holds the pending agents", pending() == {"home-ren-old", "home-ren-extra", "home-ren-reused", "home-src-moved", "home-dst-moved"}, pending())

# ---- the bug as it stood: the old names read live, so the Projects page drew them
SALA_ROWS = [["home-ren-main", ["home-ren-old"]], ["home-ren-extra", []], ["home-ren-reused", []], ["home-other-main", ["home-ren-reused"]], ["home-src-main", []],
             ["home-dst-main", []], ["home-dst-moved", ["home-src-moved"]], ["home-stale-main", ["home-stale-old"]], ["home-arch-main", []]]
sala(SALA_ROWS)
reg = A.registry()
old_style = A.file_roles(reg, A.sala_live())            # roles as they were built before: no renames
RJ.write_text(json.dumps({"generated": "2026-11-01T00:00:00Z", "sessions": old_style}))
check("(bug) the old name reads live in roles.json, and the Projects page draws it beside the new name",
      old_style["home-ren-old"].get("live") is True and shown("projects/ren", "home-ren-old") and shown("projects/ren", "home-ren-main") and shown("projects/src", "home-src-moved"), old_style.get("home-ren-old"))

# ---- 4a. sala unreadable: nothing is dropped
sala(SALA_ROWS, mode="fail"); before = (T / "store/project-record.json").read_bytes()
server._roles_sync(now=time.time())
check("4: sala unreadable → no old name is known, the record is untouched", (T / "store/project-record.json").read_bytes() == before and "renamed_to" not in RJ.read_text(), pending())
sala(SALA_ROWS)

# ---- 2/3/4/5. one roles build
check("(setup) the roles build writes roles.json", server._roles_sync(now=time.time()) is True)
S = json.loads(RJ.read_text())["sessions"]
check("2: a rename inside a project: the old name's pending entry is gone from the record, the project's other pending agents stay", pending("projects/ren") == {"home-ren-extra", "home-ren-reused"}, pending("projects/ren"))
check("3: a move between projects: the old project's pending entry for the old name is gone, the new project's own pending entry stays", pending("projects/src") == set() and pending("projects/dst") == {"home-dst-moved"}, (pending("projects/src"), pending("projects/dst")))
check("4: a name some session carries now stays pending although another session lists it as an alias", "home-ren-reused" in pending("projects/ren"))
check("2: the old names are no longer entries of roles.json (nothing owes a page line for them)", "home-ren-old" not in S and "home-src-moved" not in S, sorted(S))
check("2: …the new names are", "home-ren-main" in S and S["home-dst-moved"].get("page_owed") is True, S.get("home-dst-moved"))
check("5: a page that still lists the old name: its entry carries renamed_to, the others none", S["home-stale-old"].get("renamed_to") == "home-stale-main" and S["home-stale-old"].get("live") is True
      and sum("renamed_to" in e for e in S.values()) == 1 and A.roles_renamed() == {"home-stale-old": "home-stale-main"}, (S.get("home-stale-old"), A.roles_renamed()))
check("5: …the Projects page leaves it out and draws the new name", not shown("projects/stale", "home-stale-old") and shown("projects/stale", "home-stale-main"))
check("2: the Projects page draws the new name and not the old, in a project", shown("projects/ren", "home-ren-main") and not shown("projects/ren", "home-ren-old") and shown("projects/ren", "home-ren-extra"))
check("3: …after a move, the new name under the new project and nothing under the old", shown("projects/dst", "home-dst-moved") and shown("projects/dst", "home-dst-main") and not shown("projects/src", "home-src-moved") and shown("projects/src", "home-src-main"))
bd = board(); table = text(bd.projects_table()); whole = text(bd.projects_html())
check("2/3/5: the old names are nowhere in the Projects page's table or its page", not any(n in table or n in whole for n in ("home-ren-old", "home-src-moved", "home-stale-old")), [n for n in ("home-ren-old", "home-src-moved", "home-stale-old") if n in whole])
check("2: …and the new names are", all(n in table for n in ("home-ren-main", "home-dst-moved", "home-stale-main")), table[:500])
check("2: the archived project is untouched (its agent is still there for the page that lists it)", "home-arch-main" in whole)
c0 = (T / "store/project-record.json").read_bytes()
check("2: a second build changes nothing in the record", (server._roles_sync(now=time.time() + 1), (T / "store/project-record.json").read_bytes() == c0)[1])

# ---- an alias of a session that moves out of an archived project: still never drawn
add("projects/arch", "home-arch-old", False)
sala(SALA_ROWS[:-1] + [["home-arch-main", ["home-arch-old"]]]); server._roles_sync(now=time.time() + 2)
check("2: …an old name pending in an archived project goes too, and is not drawn there", "home-arch-old" not in pending("projects/arch") and "home-arch-old" not in text(board().projects_html()), pending("projects/arch"))

# ---- 2b. a new name registered nowhere: renamed in place; a young entry: skipped; every change logged
iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
def mk(key, name, at, front=False): prj.add_pending(pid(key), name, {"front": front, "role": "orph", "mandate_line": "the mandate of " + name}, by="fleet-web", at=at)
ROWS = [list(r) for r in SALA_ROWS[:-1]] + [["home-arch-main", ["home-arch-old"]]]
def alias(session, old): next(r for r in ROWS if r[0] == session)[1].append(old)
mk("projects/ren", "home-ren-orph-old", "2026-11-01T00:00:00Z", front=True); ROWS.append(["home-ren-orph-new", ["home-ren-orph-old"]])
mk("projects/ren", "home-ren-old2", "2026-11-01T00:00:00Z"); alias("home-ren-main", "home-ren-old2")
mk("projects/src", "home-src-young", iso(time.time() - 30)); alias("home-src-main", "home-src-young")
sala(ROWS); LOG = []; t0 = time.time()
done = RA.sweep(RA.renames_of(A.sala_rows()), A.registry(), t0, LOG.append)
rec = json.loads((T / "store/project-record.json").read_text())["pending_agents"][pid("projects/ren")]
check("2b: the new name is registered nowhere → the entry is renamed to it in its own project, role, front, mandate, by and at kept", "home-ren-orph-old" not in rec and rec.get("home-ren-orph-new") ==
      {"front": True, "role": "orph", "mandate_line": "the mandate of home-ren-orph-old", "by": "fleet-web", "at": "2026-11-01T00:00:00Z"}, rec)
check("2b: …an old name whose new name a page lists is dropped, not renamed", "home-ren-old2" not in rec and "home-ren-main" not in rec)
check("2b: …an entry registered under ten minutes ago is skipped (still pending under the old name)", "home-src-young" in pending("projects/src"), pending("projects/src"))
check("2b: every drop and rename is logged with the old and new name, the verb and the entry's fields; the skipped one is not", len(LOG) == 2
      and any("'home-ren-orph-old' -> 'home-ren-orph-new'" in l and "renamed" in l and "mandate_line='the mandate of home-ren-orph-old'" in l and "by='fleet-web'" in l and "at='2026-11-01T00:00:00Z'" in l and "front=True" in l and "role='orph'" in l for l in LOG)
      and any("'home-ren-old2' -> 'home-ren-main'" in l and "dropped" in l for l in LOG) and not any("young" in l for l in LOG), LOG)
server._roles_sync(now=t0 + 5)
check("2b: the renamed entry draws on the Projects page under the new name and the old one does not", shown("projects/ren", "home-ren-orph-new") and not shown("projects/ren", "home-ren-orph-old"))
LOG2 = []; RA.sweep(RA.renames_of(A.sala_rows()), A.registry(), t0 + 300, LOG2.append)
check("2b: the same entry at five minutes is still skipped", "home-src-young" in pending("projects/src") and not LOG2, (pending("projects/src"), LOG2))
RA.sweep(RA.renames_of(A.sala_rows()), A.registry(), t0 + 700, LOG2.append)
check("2b: …and at over ten minutes the next sweep takes it", "home-src-young" not in pending("projects/src") and len(LOG2) == 1 and "'home-src-young' -> 'home-src-main'" in LOG2[0], (pending("projects/src"), LOG2))
mk("projects/ren", "home-ren-old3", "2026-11-01T00:00:00Z"); alias("home-ren-main", "home-ren-old3"); sala(ROWS)
errbuf = io.StringIO()
with contextlib.redirect_stderr(errbuf): server._roles_sync(now=t0 + 710)
check("2b: the roles build logs a drop on the server's standard error", "renamed agent 'home-ren-old3' -> 'home-ren-main'" in errbuf.getvalue() and "home-ren-old3" not in pending("projects/ren"), errbuf.getvalue())
mk("projects/ren", "home-ren-two-a", "2026-11-01T00:00:00Z"); mk("projects/src", "home-src-two-b", "2026-11-01T00:00:00Z"); ROWS.append(["home-two-new", ["home-ren-two-a", "home-src-two-b"]]); sala(ROWS)
RA.sweep(RA.renames_of(A.sala_rows()), A.registry(), t0 + 720, LOG2.append)
check("2b: two old names of one session, the new name registered nowhere: the first is renamed, the second finds it registered and is dropped (one entry of the new name)",
      sum("home-two-new" in pending(k) for k in ("projects/ren", "projects/src")) == 1 and not ({"home-ren-two-a", "home-src-two-b"} & pending()), pending())

# ---- 2c. a rename cycle (a to b, then b to a): the session is named a again, b is only an old name
mk("projects/ren", "home-ren-cyc-a", "2026-11-01T00:00:00Z"); mk("projects/ren", "home-ren-cyc-b", "2026-11-01T00:00:00Z")
ROWS.append(["home-ren-cyc-a", ["home-ren-cyc-b", "home-ren-cyc-a"]]); sala(ROWS)
check("2c: a cycle: the session's own name listed as its alias is no old name, the other name is", RA.renames_of(A.sala_rows()).get("home-ren-cyc-b") == "home-ren-cyc-a" and "home-ren-cyc-a" not in RA.renames_of(A.sala_rows()), RA.renames_of(A.sala_rows()))
RA.sweep(RA.renames_of(A.sala_rows()), A.registry(), t0 + 730, LOG2.append)
check("2c: …the pending entry under the current name stays, the one under the other name goes (the current name is registered)", {"home-ren-cyc-a", "home-ren-cyc-b"} & pending("projects/ren") == {"home-ren-cyc-a"}, pending("projects/ren"))

# ---- 2d. a failing record write does not stop the roles rebuild
mk("projects/ren", "home-ren-wfail-old", "2026-11-01T00:00:00Z"); ROWS.append(["home-ren-wfail-new", ["home-ren-wfail-old"]]); sala(ROWS)
RJ.unlink(missing_ok=True); rec_before = (T / "store/project-record.json").read_bytes(); real_write = prj._write
def bad_write(d): raise OSError(28, "No space left on device")
prj._write = bad_write; errbuf = io.StringIO()
try:
    with contextlib.redirect_stderr(errbuf): wrote = server._roles_sync(now=t0 + 800)
finally: prj._write = real_write
check("2d: the record write raises OSError: roles.json is still rebuilt (written, with the new session in it), the failure is logged, the record is untouched",
      wrote is True and RJ.exists() and "home-ren-wfail-new" not in json.loads(RJ.read_text())["sessions"] and "home-ren-main" in json.loads(RJ.read_text())["sessions"]
      and "sweep failed" in errbuf.getvalue() and "No space left" in errbuf.getvalue() and (T / "store/project-record.json").read_bytes() == rec_before, (wrote, errbuf.getvalue()))
server._roles_sync(now=t0 + 860)
check("2d: …and the next tick, with the write working again, settles the entry", "home-ren-wfail-old" not in pending("projects/ren") and "home-ren-wfail-new" in pending("projects/ren"), pending("projects/ren"))

# ---- 6. the repair tool
spec = importlib.util.spec_from_file_location("drop_renamed_pending", pathlib.Path(STACK, "stackshot/tools/drop_renamed_pending.py")); tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = tool.main(list(argv))
    return rc, out.getvalue(), err.getvalue()
add("projects/ren", "home-ren-gone1"); add("projects/src", "home-ren-gone2", False); add("projects/dst", "home-dst-keep")
base = (T / "store/project-record.json").read_bytes(); P0 = pending()
rc, out, err = run("--name", "home-ren-gone1", "--name", "HOME-REN-GONE2", "--name", "home-no-such")
check("6: dry run: exit 0, names every entry it would drop with its project, the unknown name said, nothing written, no run folder", rc == 0 and out.count("would drop:") == 2 and "projects/ren" in out and "projects/src" in out
      and "home-no-such is pending in no project" in out and "nothing written" in err and (T / "store/project-record.json").read_bytes() == base and not any((T / "runs").iterdir()), (rc, out, err))
check("6: --apply with no --name or --undo with a name is refused", run("--apply")[0] == 2 and run("--undo", "x", "--name", "a")[0] == 2)
rc, out, err = run("--name", "home-ren-gone1", "--name", "home-ren-gone2", "--apply", "--run-dir", str(T / "runs"))
undos = sorted((T / "runs").glob("*/undo.json"))
check("6: --apply drops exactly those two (case-folded), leaves every other pending agent, and keeps an undo file naming both with their entries", rc == 0 and pending() == P0 - {"home-ren-gone1", "home-ren-gone2"} and len(undos) == 1
      and {(x["key"], x["name"]) for x in json.loads(undos[0].read_text())["dropped"]} == {("projects/ren", "home-ren-gone1"), ("projects/src", "home-ren-gone2")}
      and all(x["entry"]["by"] == "fleet-web" for x in json.loads(undos[0].read_text())["dropped"]), (rc, out, err, pending()))
after = (T / "store/project-record.json").read_bytes()
rc, out, err = run("--name", "home-ren-gone1", "--name", "home-ren-gone2", "--apply", "--run-dir", str(T / "runs"))
check("6: a second --apply is a no-op: nothing to drop, no second undo file, the record as it was", rc == 0 and out.count("nothing to drop") == 2 and len(list((T / "runs").glob("*/undo.json"))) == 1 and (T / "store/project-record.json").read_bytes() == after, (rc, out))
rc, out, err = run("--undo", str(undos[0]))
check("6: --undo puts both entries back, each in its own project, with the fields it had", rc == 0 and pending() == P0 and "home-ren-gone1" in pending("projects/ren") and "home-ren-gone2" in pending("projects/src")
      and json.loads((T / "store/project-record.json").read_text())["pending_agents"][pid("projects/src")]["home-ren-gone2"]["front"] is False, (rc, out, pending()))
rc, out, err = run("--undo", str(undos[0]))
check("6: …a second --undo puts nothing back", rc == 0 and out.startswith("put back 0 of 2"), out)
real_drop = prj.drop_pending_named
def racing(names, before_write=None):
    add("projects/dst", "home-dst-late")            # an entry that appears after the tool's first read, before the record drops
    return real_drop(names, before_write)
prj.drop_pending_named = racing
try: rc, out, err = run("--name", "home-ren-gone1", "--name", "home-dst-late", "--apply", "--run-dir", str(T / "runs"))
finally: prj.drop_pending_named = real_drop
undo2 = sorted((T / "runs").glob("*/undo.json"))[-1]; listed = {(x["key"], x["name"]) for x in json.loads(undo2.read_text())["dropped"]}
check("6: the undo file is made from what the record dropped: an entry that appeared after the first read is dropped and in it", rc == 0 and listed == {("projects/ren", "home-ren-gone1"), ("projects/dst", "home-dst-late")}
      and "home-dst-late" not in pending("projects/dst") and "home-dst-late" in out, (rc, out, listed))
rc, out, err = run("--undo", str(undo2))
check("6: …and --undo puts the late entry back too", rc == 0 and "home-dst-late" in pending("projects/dst") and "home-ren-gone1" in pending("projects/ren"), (rc, out))
check("6: an undo file that does not read is exit 1", run("--undo", str(T / "no-such-file"))[0] == 1)

print(("ok" if not fails else "FAILED") + f": renamed agent old name scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
