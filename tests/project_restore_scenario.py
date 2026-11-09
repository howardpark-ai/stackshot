"""Scenario test for `project.py restore` (project_restore.py, project_verbs.restore / restore_list / restore_undo): the record, or one project of it, put back from a past revision of the
store's git history. Fixture data in a scratch folder that holds a throwaway git repository (the store is a folder inside it, as the board's data repository has it): no live store, no network, no server
process, HOME and git's own config pointed into the scratch folder, so the default undo folder of the verb is there too.

Covers: `--list` (newest first, the date in the instance's zone as `Mon Nov 9th`, the project count and what changed in it); a dry run changing nothing (the record file, the repository's HEAD and
work tree, no undo folder); the restore of one project into a record that lost it, with its id row, its sub-page's id row and its mark, and the rest of the current record untouched; the same for a
project that is there but changed (the fields named); the restore of the whole record (the file as saved, the projects made since named as gone); `--before DATE`; the undo of both (whole file back when
the record is as the restore left it; part by part when something else was written since; refused when the project's own parts changed since); every refusal (a revision git does not know, an option
passed as a revision, a revision with no record file, a record that does not read at the revision, a project the revision does not hold, the page key or the name of a live project with another id, a record
being written, a store that is not in a git repository, a current record that does not read for one project) with nothing written; wrong arguments (exit 2); the CLI in a subprocess; and that nothing
outside the scratch folder was read or written as the live board (the record, the lock, the undo folder are all under it).

    tests/run-suite project_restore        → exit 0 / 1"""
import fcntl, hashlib, json, logging, os, pathlib, re, subprocess, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="prjrestore-"); T = pathlib.Path(tmp)
import _instance
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", f"{tmp}/repo"), ("store", f"{tmp}/repo/board-data"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
HOME = T / "home"; HOME.mkdir()
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(HOME), GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1",
                  GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
for k in ("XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CONFIG_HOME", "STACKSHOT_URL", "CLAUDE_CODE_SESSION_ID"):
    os.environ.pop(k, None)
for d in ("repo/board-data", "state", "brain/projects", "secrets"):
    (T / d).mkdir(parents=True)
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def sha(b): return hashlib.sha256(b).hexdigest()

from stackshot.core import config as cfg
from stackshot.projects import projects as prj, project_registry as pr, project_verbs as pv, project_restore as rs
REPO = T / "repo"; REC = REPO / "board-data" / "project-record.json"
check("setup: the record, the lock's folder and the default undo folder are all inside the scratch folder (never the live board)",
      str(prj.record_path()) == str(REC) and str(cfg.state("project-record.lock")).startswith(tmp) and str(rs.default_run_dir()).startswith(tmp)
      and str(REC).startswith(tmp), (prj.record_path(), cfg.state("project-record.lock"), rs.default_run_dir()))
UNDO_ROOT = rs.default_run_dir()

def git(*args, date=None):
    env = dict(os.environ)
    if date: env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    r = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, env=env)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()
git("init", "-q", "-b", "main")

def pid(n): return "prj_" + format(n, "08x")   # built at run time: no id-shaped literal sits in this file
A, B, C, D, S, Q = (pid(0xa00 + n) for n in range(1, 7))
X7, X8 = pid(0xa07), pid(0xa08)
def ent(name, page, agents=None, status="active", scope="home", **more):
    e = {"name": name, "title": name.title(), "type": "project", "scope": scope, "status": status, "hub": "", "page": page, "former_keys": [], "former_names": [],
         "made": {"at": "2026-11-07T17:13:52Z", "by": "migration", "how": "migrated"}}
    if agents is not None: e["agents"] = agents
    if status == "archived": e["retired"] = {"at": "2026-11-08T00:00:00Z", "by": "cli", "how": "made"}
    e.update(more); return e
def ag(**kw): return {n: {"front": f, "mandate_line": m} for n, (f, m) in kw.items()}
def put(ents, ids, marks=None, pending=None, commit=None, date=None):
    d = {"schema": 1, "ids": ids, "pending_agents": pending or {}, "marks": marks or {}, "extra": {}}
    if ents: d["extra"][pr.SECTION] = ents; d["extra"][pr.VERSION] = pr.SCHEMA
    prj._write(d)
    if commit:
        git("add", "-A"); git("commit", "-q", "-m", commit, date=date)
        return git("rev-parse", "HEAD")
def rec(): return json.loads(REC.read_text(encoding="utf-8"))
def recb(): return REC.read_bytes()
def ents_now(): return rec().get("projects", {})

# a first commit with no record file at all, then four revisions of the record (the dates are in the +09:00 zone; the instance's zone is Dubai, +04:00)
(REPO / "README").write_text("data repo\n"); git("add", "-A"); git("commit", "-q", "-m", "init", date="2026-11-01T09:00:00+09:00"); R0 = git("rev-parse", "HEAD")
alpha = ent("home-alpha", "projects/alpha", ag(**{"home-alpha-main": (True, "talks to Oliver"), "home-alpha-engineer": (False, "builds")}),
            made={"at": "2026-11-02T01:02:03Z", "by": "cli", "how": "made"})
beta = ent("home-beta", "projects/beta", ag(**{"home-beta-main": (True, "does it")}))
R1 = put({A: alpha, B: beta}, {A: "projects/alpha", B: "projects/beta", S: "projects/alpha/sub", Q: "projects/old-thing"}, {A: {"scope": "home", "on_purpose": True}},
         commit="r1", date="2026-11-05T10:00:00+09:00")
gamma = ent("home-gamma", "projects/gamma", ag(**{"home-gamma-main": (True, "does gamma")}))
alpha2 = {**alpha, "agents": {**alpha["agents"], "home-alpha-docs": {"front": True, "mandate_line": "keeps the docs"}}}
R2 = put({A: alpha2, B: beta, C: gamma}, {A: "projects/alpha", B: "projects/beta", C: "projects/gamma", S: "projects/alpha/sub", Q: "projects/old-thing"}, {A: {"scope": "home", "on_purpose": True}},
         commit="r2", date="2026-11-08T22:38:00+09:00")
gamma3 = ent("home-gamma", "projects/gamma", ag(**{"home-gamma-main": (True, "does gamma")}), status="archived")
beta3 = {**beta, "agents": {"home-beta-main": {"front": True, "mandate_line": "does it, newly worded"}}}
R3 = put({A: alpha2, B: beta3, C: gamma3}, {A: "projects/alpha", B: "projects/beta", C: "projects/gamma", S: "projects/alpha/sub", Q: "projects/old-thing"}, {A: {"scope": "home", "on_purpose": True}},
         commit="r3", date="2026-11-09T03:38:00+09:00")
# now: alpha was lost, a project made since (delta) exists, beta carries a later change, and a later commit holds the lost state
delta = ent("home-delta", "projects/delta", ag(**{"home-delta-main": (True, "new since")}))
beta4 = {**beta3, "title": "Beta, retitled"}
R4 = put({B: beta4, C: gamma3, D: delta}, {B: "projects/beta", C: "projects/gamma", D: "projects/delta", Q: "projects/old-thing"}, commit="r4", date="2026-11-09T04:00:00+09:00")
LIVE = recb()
head0 = git("rev-parse", "HEAD")

def snap():
    return (sha(recb()), git("rev-parse", "HEAD"), git("status", "--porcelain"), sorted(p.name for p in UNDO_ROOT.glob("*")) if UNDO_ROOT.exists() else None)
def refused(name, status, needle, fn):
    before = snap()
    try:
        fn(); check(name, False, "no refusal")
    except pv.VerbError as e:
        check(name, e.status == status and needle in e.message and snap() == before, (e.status, e.message, snap() == before))

# ---- 1. --list
res = pv.restore_list(10)
L = res["lines"]
check("list: the last revisions of the record file, newest first, without the commit that has no record", [r["rev"] for r in res["revisions"]] == [R4, R3, R2, R1], [r["rev"][:8] for r in res["revisions"]])
check("list: the date reads as `Mon Nov 9th` in the instance's zone (Dubai), not the commit's own +09:00 or UTC: R3 (03:38 +09:00) is Sun Nov 8th 22:38 +04", any(R3[:10] in x and "Sun Nov 8th 22:38 +04" in x for x in L), L)
check("list: R2 is Sun Nov 8th 17:38 +04 and R1 Thu Nov 5th 05:00 +04", any(R2[:10] in x and "Sun Nov 8th 17:38" in x for x in L) and any(R1[:10] in x and "Thu Nov 5th 05:00" in x for x in L), L)
check("list: the summary names the project count and what changed in it: R2 made one project, R4 lost one and made one, R1 is the first with two",
      any(R2[:10] in x and "3 projects (+1 -0 ~1)" in x for x in L) and any(R4[:10] in x and "3 projects (+1 -1 ~1)" in x for x in L) and any(R1[:10] in x and "2 projects, " in x for x in L), L)
check("list --limit 2 shows two, and starting from a revision starts there", len(pv.restore_list(2)["revisions"]) == 2 and pv.restore_list(10, rev=R2)["revisions"][0]["rev"] == R2, None)
check("list writes nothing", snap()[:3] == (sha(LIVE), head0, ""), snap())

# ---- 2. a dry run of one project changes nothing
s0 = snap()
res = pv.restore(A, rev=R3)
check("dry run, one project: says what would come back (the project, its id row, the sub-page's id row, its mark) and that nothing was written",
      res["dry"] and res["mode"] == "project" and res["project"] == A and res["added"] == [A] and res["ids"]["added"] == [A, S] and res["marks"]["added"] == [A] and res["changed"]
      and any("not in the current record, comes back" in x for x in res["lines"]) and "nothing written (add --apply)" in res["lines"][-1], res["lines"])
check("dry run: the record file, git's HEAD and work tree, and the undo folder are as they were", snap() == s0 and not UNDO_ROOT.exists(), (snap(), s0))
res = pv.restore("projects/alpha", rev=R3[:12])
check("a project is found by page key and a short sha as well", res["project"] == A, res)
res = pv.restore("home-alpha", rev=R1)
check("... by name, at an older revision (which has fewer agents)", res["project"] == A, res)
res = pv.restore(B, rev=R3)
check("dry run of a project that is there but changed since: names the field (the later title)", res["changed_projects"].get(B) == ["title: 'Beta, retitled' -> 'Home-Beta'"], res["changed_projects"])
res2 = pv.restore(B, rev=R2)
check("... and a mandate line that differs at another revision is named as such", any("mandate line changed: home-beta-main" in x for x in res2["changed_projects"].get(B, [])), res2["changed_projects"])

# ---- 3. one project into a record that lost it
res = pv.restore(A, rev=R3, apply=True, by="tester", run_dir=T / "runs", now="2026-11-09T05:00:00Z")
E = ents_now(); live = json.loads(LIVE)
check("apply, one project: the entry comes back exactly as saved, with its agents in order", E.get(A) == alpha2 and list(E[A]["agents"]) == list(alpha2["agents"]), E.get(A))
check("... its id row, its sub-page's id row and its mark come back", rec()["ids"].get(A) == "projects/alpha" and rec()["ids"].get(S) == "projects/alpha/sub" and rec()["marks"].get(A) == {"scope": "home", "on_purpose": True}, rec())
check("... and the rest of the current record is untouched (beta keeps its later title, delta is still there, the other ids stay, the old-thing row of the revision that the record has too)",
      E[B] == beta4 and E[D] == delta and E[C] == gamma3 and all(rec()["ids"].get(i) == k for i, k in live["ids"].items()), E)
check("... the undo file and the file as it was are kept in the run folder (under the scratch folder), the answer names the undo command",
      res["undo"] and res["undo"].startswith(str(T / "runs" / "20261109T050000Z")) and pathlib.Path(res["undo"]).is_file() and (T / "runs/20261109T050000Z/project-record.before.json").read_bytes() == LIVE
      and "restore --undo" in res["lines"][-1], res["lines"])
um = json.loads(pathlib.Path(res["undo"]).read_text())
check("... the undo file names the revision, the project, who and the hash of the file written", um["rev"] == R3 and um["project"] == A and um["by"] == "tester" and um["after_sha256"] == sha(recb()) and um["before_sha256"] == sha(LIVE), um)
check("... the file is the save path's own format (sorted, indented, a final newline), parses with the registry, and the save left no temp file in the store", recb().endswith(b"\n") and pr.parse(json.loads(recb())) and not list((REPO / "board-data").glob("*.tmp")) and not list((REPO / "board-data").glob(".*tmp")), None)
check("... the dry run now says the record holds it already, and a second apply writes nothing and keeps no second undo file",
      not pv.restore(A, rev=R3)["changed"] and not pv.restore(A, rev=R3, apply=True, run_dir=T / "runs")["changed"] and len(list((T / "runs").iterdir())) == 1, list((T / "runs").iterdir()))
AFTER_ONE = recb()
# undo: the record is as the restore left it, so the file comes back whole
u = pv.restore_undo(res["undo"])
check("undo, dry run: says the whole file would go back, and writes nothing", u["dry"] and u["changed"] and "put the record file back" in u["lines"][0] and recb() == AFTER_ONE, u)
u = pv.restore_undo(res["undo"], apply=True)
check("undo, apply: the record file is byte for byte what it was before the restore", recb() == LIVE and u["changed"], u)
check("undo again: nothing to do", not pv.restore_undo(res["undo"], apply=True)["changed"] and recb() == LIVE, None)

# undo when something else was written since: only the project's own parts go back
res = pv.restore(A, rev=R3, apply=True, run_dir=T / "runs", now="2026-11-09T05:01:00Z")
d = prj._read(); e = ents_now(); e[D] = {**e[D], "title": "Delta, edited later"}; d["extra"][pr.SECTION] = e; prj._write(d)
u = pv.restore_undo(res["undo"], apply=True)
check("undo after another change: takes back alpha's entry, its two id rows and its mark, and keeps the later edit of delta",
      A not in ents_now() and S not in rec()["ids"] and A not in rec()["ids"] and A not in rec().get("marks", {}) and ents_now()[D]["title"] == "Delta, edited later" and u["changed"] and "only" in u["lines"][0], (u, rec()))
res = pv.restore(A, rev=R3, apply=True, run_dir=T / "runs", now="2026-11-09T05:02:00Z")
d = prj._read(); e = ents_now(); e[A] = {**e[A], "title": "Alpha, edited later"}; d["extra"][pr.SECTION] = e; prj._write(d)
s1 = snap()
try:
    pv.restore_undo(res["undo"], apply=True); check("undo refused when the project's own entry changed since", False, "no refusal")
except pv.VerbError as e2:
    check("undo refused when the project's own entry changed since: names it, writes nothing", e2.status == 409 and f"the entry of {A} changed since" in e2.message and snap() == s1, (e2.message, snap() == s1))
put({B: beta4, C: gamma3, D: delta}, {B: "projects/beta", C: "projects/gamma", D: "projects/delta", Q: "projects/old-thing"})   # the live record again
check("... (the fixture is back to the live record)", recb() == LIVE, None)

# a project that is there and changed: restored as saved, undone whole
res = pv.restore(B, rev=R3, apply=True, run_dir=T / "runs", now="2026-11-09T05:03:00Z")
check("a project that is there: its entry becomes the saved one (the later title is gone, the other projects stay)", ents_now()[B] == beta3 and ents_now()[D] == delta and res["changed_projects"].get(B), ents_now()[B])
check("... and undo brings the later title back", pv.restore_undo(res["undo"], apply=True)["changed"] and recb() == LIVE, None)

# ---- 4. the whole record
s0 = snap()
res = pv.restore(rev=R3)
L = res["lines"]
check("dry run, whole record: says delta (made since) would be gone, alpha comes back, beta changes, and names the id and mark rows", res["mode"] == "record" and res["removed"] == [D] and res["added"] == [A] and B in res["changed_projects"]
      and any(D in x and "gone from the record" in x for x in L) and any(A in x and "comes back" in x for x in L) and any(x.startswith("ids: ") for x in L) and any(x.startswith("marks: ") for x in L), L)
check("... and writes nothing", snap() == s0, snap())
res = pv.restore(rev=R3, apply=True, run_dir=T / "runs", now="2026-11-09T05:10:00Z")
saved3 = json.loads(subprocess.run(["git", "-C", str(REPO), "show", f"{R3}:board-data/project-record.json"], capture_output=True, text=True).stdout)
check("apply, whole record: the file parses to exactly what the revision held", rec() == saved3, (sorted(rec()), sorted(saved3)))
check("... so alpha's entry, ids and mark are back, delta is gone, and the undo copy holds the file as it was", A in ents_now() and D not in ents_now() and S in rec()["ids"] and (T / "runs/20261109T051000Z/project-record.before.json").read_bytes() == LIVE, None)
u = pv.restore_undo(res["undo"], apply=True)
check("undo of the whole restore: the file is as it was, byte for byte", recb() == LIVE and u["changed"], u)
res = pv.restore(rev=R3, apply=True, run_dir=T / "runs", now="2026-11-09T05:11:00Z")
d = prj._read(); d["marks"][B] = {"scope": "home"}; prj._write(d)
s1 = snap()
try:
    pv.restore_undo(res["undo"], apply=True); check("undo of a whole restore after another write is refused", False, "no refusal")
except pv.VerbError as e2:
    check("undo of a whole restore after another write is refused, with the path of the file as it was", e2.status == 409 and "written after the restore" in e2.message and "project-record.before.json" in e2.message and snap() == s1, e2.message)
put({B: beta4, C: gamma3, D: delta}, {B: "projects/beta", C: "projects/gamma", D: "projects/delta", Q: "projects/old-thing"})
# a whole restore when the current file is damaged or missing
REC.write_text("{ not json", encoding="utf-8"); damaged = recb()
res = pv.restore(rev=R3)
check("dry run, whole record, with a damaged current file: says so and would replace it", res["changed"] and any("does not read" in x for x in res["lines"]), res["lines"])
res = pv.restore(rev=R3, apply=True, run_dir=T / "runs", now="2026-11-09T05:12:00Z")
check("apply over a damaged file: the revision's record is written and the damaged file is kept for the undo", rec() == saved3 and (T / "runs/20261109T051200Z/project-record.before.json").read_bytes() == damaged, None)
check("... undo puts the damaged file back", pv.restore_undo(res["undo"], apply=True)["changed"] and recb() == damaged, None)
REC.unlink()
res = pv.restore(rev=R3, apply=True, run_dir=T / "runs", now="2026-11-09T05:13:00Z")
check("apply with no current file: written, no before copy", rec() == saved3 and res["undo"] and not (T / "runs/20261109T051300Z/project-record.before.json").exists(), res)
check("... and its undo removes the file again", pv.restore_undo(res["undo"], apply=True)["changed"] and not REC.exists(), None)
put({B: beta4, C: gamma3, D: delta}, {B: "projects/beta", C: "projects/gamma", D: "projects/delta", Q: "projects/old-thing"})
check("(the fixture is back to the live record)", recb() == LIVE, None)

# ---- 5. --before
res = pv.restore(A, before="2026-11-08 20:00 +0900")
check("--before DATE: the last revision of the record file from before it (R1: R2 is at 22:38 +09:00)", res["rev"] == R1 and res["project"] == A, res.get("rev"))
res = pv.restore(A, before="2026-11-09 03:50 +0900")
check("... and a later date gives R3", res["rev"] == R3, res.get("rev"))

# ---- 6. refusals: nothing is written
refused("refused: a revision git does not know (404)", 404, "does not know the revision", lambda: pv.restore(A, rev="no-such-rev-0123"))
refused("refused: an option passed as a revision (400), never given to git", 400, "not a git revision", lambda: pv.restore(A, rev="--output=/tmp/x"))
refused("refused: a date before the first revision of the record (404)", 404, "no revision of", lambda: pv.restore(A, before="2026-10-01"))
refused("refused: a revision with no record file (the first commit) (404)", 404, "has no board-data/project-record.json", lambda: pv.restore(A, rev=R0))
refused("refused: no revision named, or two (400)", 400, "name one revision", lambda: pv.restore(A))
refused("refused: a project the revision does not hold, named as it is now (404)", 404, "is not a project in revision", lambda: pv.restore(D, rev=R3))
refused("refused: ... also with a page key the revision lacks", 404, "is not a project in revision", lambda: pv.restore("projects/delta", rev=R3))
# a record that does not read at a revision
bad_doc = json.loads(LIVE); bad_doc["projects"][B]["status"] = "gone"
REC.write_text(json.dumps(bad_doc), encoding="utf-8"); git("add", "-A"); git("commit", "-q", "-m", "r5 damaged entry", date="2026-11-09T05:00:00+09:00"); R5 = git("rev-parse", "HEAD")
REC.write_text("{ not json", encoding="utf-8"); git("add", "-A"); git("commit", "-q", "-m", "r6 torn", date="2026-11-09T05:01:00+09:00"); R6 = git("rev-parse", "HEAD")
REC.write_bytes(LIVE); git("add", "-A"); git("commit", "-q", "-m", "r7 live again", date="2026-11-09T05:02:00+09:00")
head1 = git("rev-parse", "HEAD")
refused("refused: a record that does not read at the revision (a torn file) (422)", 422, "does not read", lambda: pv.restore(A, rev=R6))
refused("refused: ... and one whose entry is invalid (422), the whole record too", 422, "does not read", lambda: pv.restore(rev=R5))
check("list shows those two revisions as not reading, and goes on", sum("does not read" in x for x in pv.restore_list(10)["lines"]) == 2, pv.restore_list(10)["lines"])
# a live project of another id on the same page key, or with the same name
d = prj._read(); e = ents_now(); e[Q] = ent("home-newer", "projects/alpha"); d["extra"][pr.SECTION] = e; prj._write(d)
refused("refused: the entry would sit on the page key of a live project with another id (409)", 409, "same page key projects/alpha", lambda: pv.restore(A, rev=R3, apply=True, run_dir=T / "runs"))
d = prj._read(); e = ents_now(); e[Q] = ent("home-alpha", "projects/elsewhere"); d["extra"][pr.SECTION] = e; prj._write(d)
refused("refused: ... or take the name of one (409)", 409, "same name 'home-alpha'", lambda: pv.restore(A, rev=R3, apply=True, run_dir=T / "runs"))
res = pv.restore(rev=R3)
check("the whole record has no such refusal (it replaces the table)", res["mode"] == "record" and res["changed"], res)
put({B: beta4, C: gamma3, D: delta}, {B: "projects/beta", C: "projects/gamma", D: "projects/delta", Q: "projects/old-thing"})
# the record is being written: another process holds the record's lock
lock = open(cfg.state("project-record.lock"), "w"); fcntl.flock(lock, fcntl.LOCK_EX)
rs.LOCK_WAIT = 0.3
try:
    refused("refused: the record is being written (its lock is held) (409), nothing written, no undo file", 409, "is being written", lambda: pv.restore(A, rev=R3, apply=True, run_dir=T / "runs"))
    dry = pv.restore(A, rev=R3)
    check("... a dry run does not wait for the lock", dry["dry"] and dry["changed"], dry)
finally:
    fcntl.flock(lock, fcntl.LOCK_UN); lock.close()
check("... and once the lock is free the same call goes through", pv.restore(A, rev=R3, apply=True, run_dir=T / "runs", now="2026-11-09T05:20:00Z")["changed"] and A in ents_now(), None)
put({B: beta4, C: gamma3, D: delta}, {B: "projects/beta", C: "projects/gamma", D: "projects/delta", Q: "projects/old-thing"})
# a current record that does not read, for one project
REC.write_text("{ not json", encoding="utf-8")
refused("refused: one project into a current record that does not read (422): restore the whole record instead", 422, "restore the whole record instead", lambda: pv.restore(A, rev=R3, apply=True, run_dir=T / "runs"))
REC.write_bytes(LIVE)
# a store outside any git repository
cfg.CFG["paths"]["store"] = str(T / "nogit-store"); (T / "nogit-store").mkdir()
try:
    refused("refused: a store that is not in a git repository (409)", 409, "not inside a git repository", lambda: pv.restore(A, rev=R3))
    refused("... --list too", 409, "not inside a git repository", lambda: pv.restore_list())
finally:
    cfg.CFG["paths"]["store"] = str(REPO / "board-data")
check("(the store is the repository's again)", prj.record_path() == REC, prj.record_path())

# ---- 6b. the review's findings
LIVE_IDS = {B: "projects/beta", C: "projects/gamma", D: "projects/delta", Q: "projects/old-thing"}
def live_again(commit=None):
    REC.write_bytes(LIVE)
    if commit: git("add", "-A"); git("commit", "-q", "-m", commit, date="2026-11-09T06:00:00+09:00")

# 1. --before is read in the instance's zone (Dubai, +04), not the box's, and a date git cannot read is refused
os.environ["TZ"] = "UTC"
try:
    res = pv.restore(A, before="2026-11-08 20:00")
    check("--before with no zone is the instance's (Dubai, +04): 20:00 there is 16:00 UTC, so R2 (13:38 UTC) is the last before it, though the box's zone is UTC (R3 is 18:38 UTC)", res["rev"] == R2, res["rev"][:10])
    res = pv.restore(A, before="2026-11-08 18:50 +0000")
    check("... 18:50 with its own zone (+0000) is 18:50 UTC and gives R3 (R3 is 18:38 UTC, R4 19:00 UTC)", res["rev"] == R3, res["rev"][:10])
    res = pv.restore(A, before="2026-11-08")
    check("... a date alone is its midnight in the instance's zone: Sun Nov 8th 00:00 +04 is before R2 and after R1", res["rev"] == R1, res["rev"][:10])
    check("... and the answer says how the date was read", any(x.startswith("revision picked: the last change to the record before 2026-11-08 20:00 +04") for x in pv.restore(A, before="2026-11-08 20:00")["lines"]), pv.restore(A, before="2026-11-08 20:00")["lines"])
finally:
    os.environ.pop("TZ", None)
for bad in ("banana", "2026-13-45", "yesterday", "2026-11-08 25:99", "2 days ago", "-1", ""):
    refused(f"refused: --before {bad!r} is not a date git would be told (400)" if bad else "refused: an empty --before is no revision (400)", 400, "not a date" if bad else "name one revision",
            lambda bad=bad: pv.restore(A, before=bad) if bad else pv.restore(A, before="", rev=""))
def cli(*args):
    r = subprocess.run([sys.executable, f"{STACK}/stackshot/tools/project.py", *args], capture_output=True, text=True, env=os.environ, cwd=str(T))
    return r.returncode, r.stdout, r.stderr
rc, out, err = cli("restore", "--before", "banana", "home-alpha")
check("cli: --before banana exits 1 and says it is not a date, where git alone would take the newest revision", rc == 1 and "not a date" in err and recb() == LIVE, (rc, out, err))

# 6. every git call drops the GIT_ variables that would point git away from the store's repository
decoy = T / "decoy"; decoy.mkdir()
subprocess.run(["git", "-C", str(decoy), "init", "-q", "-b", "main"], check=True, env=dict(os.environ))
(decoy / "board-data").mkdir(); (decoy / "board-data/project-record.json").write_text(json.dumps({"schema": 1, "ids": {}}))
subprocess.run(["git", "-C", str(decoy), "add", "-A"], check=True, env=dict(os.environ)); subprocess.run(["git", "-C", str(decoy), "commit", "-q", "-m", "decoy"], check=True, env=dict(os.environ))
saved_env = {k: os.environ.get(k) for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_CEILING_DIRECTORIES", "GIT_NAMESPACE", "GIT_ALTERNATE_OBJECT_DIRECTORIES")}
os.environ.update(GIT_DIR=str(decoy / ".git"), GIT_WORK_TREE=str(decoy), GIT_INDEX_FILE=str(T / "no-such-index"), GIT_OBJECT_DIRECTORY=str(T / "no-objects"),
                  GIT_CEILING_DIRECTORIES=str(T), GIT_NAMESPACE="decoy", GIT_ALTERNATE_OBJECT_DIRECTORIES=str(T / "no-alt"))
try:
    env = rs.git_env()
    check("git_env: no GIT_ variable but the two that say where git's own settings are (the test points them at nothing), and the instance's zone for TZ",
          sorted(k for k in env if k.startswith("GIT_")) == ["GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "GIT_OPTIONAL_LOCKS", "GIT_TERMINAL_PROMPT"] and env["TZ"] == "Asia/Dubai", sorted(env))
    lst = pv.restore_list(10)
    res = pv.restore(A, rev=R3)
    check("with GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE, GIT_OBJECT_DIRECTORY and GIT_CEILING_DIRECTORIES set to something else, list and restore still read the store's own repository", len(lst["revisions"]) >= 4 and res["project"] == A and res["repo"] == str(REPO), (lst["lines"][:2], res.get("repo")))
finally:
    for k, v in saved_env.items():
        if v is None: os.environ.pop(k, None)
        else: os.environ[k] = v

# 2. an order-only difference of the agents is a change, and is shown
reordered = {**alpha2, "agents": {n: alpha2["agents"][n] for n in reversed(list(alpha2["agents"]))}}
put({A: reordered, B: beta4, C: gamma3, D: delta}, {A: "projects/alpha", S: "projects/alpha/sub", **LIVE_IDS}, {A: {"scope": "home", "on_purpose": True}})
res = pv.restore(A, rev=R3)
check("a project whose agents differ only in order is a change: the dry run says so, names the order, and the first builder listed", res["changed"] and res["changed_projects"].get(A) and any("order (the first builder listed is the builder)" in x for x in res["changed_projects"][A]), res)
res = pv.restore(A, rev=R3, apply=True, run_dir=T / "runs", now="2026-11-09T06:10:00Z")
check("... apply puts the saved order back", list(ents_now()[A]["agents"]) == list(alpha2["agents"]) and res["changed"], list(ents_now()[A]["agents"]))
check("... and the same restore again is nothing to restore", not pv.restore(A, rev=R3)["changed"], None)
put({A: reordered, B: beta4, C: gamma3, D: delta}, {A: "projects/alpha", S: "projects/alpha/sub", **LIVE_IDS}, {A: {"scope": "home", "on_purpose": True}})
res = pv.restore(rev=R3)
check("the whole record sees an order-only difference too", A in res["changed_projects"] and any("order" in x for x in res["changed_projects"][A]), res["changed_projects"])
live_again()

# 3. a restored id row or former key that another live id already holds is refused
put({B: beta4, C: gamma3, D: delta}, {X7: "projects/alpha", **LIVE_IDS})
refused("refused: the entry's id row would map a page key a live id (a row with no entry) holds (409), in the dry run too", 409, "already held by the live id", lambda: pv.restore(A, rev=R3))
refused("... and with --apply, nothing written", 409, "already held by the live id", lambda: pv.restore(A, rev=R3, apply=True, run_dir=T / "runs"))
live_again()
alpha_fk = {**alpha2, "former_keys": ["projects/delta"]}
put({A: alpha_fk, B: beta3, C: gamma3}, {A: "projects/alpha", **LIVE_IDS}, commit="r8 alpha with a former key that a live project has now", date="2026-11-09T05:30:00+09:00")
R8 = git("rev-parse", "HEAD")
live_again("r9 live again")
refused("refused: a former key of the restored entry that is the page of a live project (409)", 409, "page key projects/delta", lambda: pv.restore(A, rev=R8))
put({B: beta4, C: gamma3}, {**LIVE_IDS}); d = prj._read(); d["ids"].pop(D, None); prj._write(d)
res = pv.restore(A, rev=R8)
check("... and not refused when nothing live holds that key", res["project"] == A and res["changed"], res.get("lines"))
live_again()
alpha_fk2 = {**alpha2, "former_keys": ["projects/older"]}
put({A: alpha_fk2, B: beta3, C: gamma3}, {A: "projects/alpha", **LIVE_IDS}, commit="r10 alpha with a former key that a live project has as one too", date="2026-11-09T05:40:00+09:00")
R10 = git("rev-parse", "HEAD")
REC.write_bytes(LIVE); d = prj._read(); e = ents_now(); e[D] = {**e[D], "former_keys": ["projects/older"]}; d["extra"][pr.SECTION] = e; prj._write(d)
refused("refused: ... or one that is a former key of a live project too (409)", 409, "already held by the live id", lambda: pv.restore(A, rev=R10))
live_again("r13 live again")

# 4. a restore that changes the status says so on a line of its own
res = pv.restore(C, rev=R2)
check("a restore that un-archives a project: a headline line says so, and the status field is listed", res["lines"][1].startswith("THIS UN-ARCHIVES IT") and res["changed_projects"][C] and any(x.startswith("status:") for x in res["changed_projects"][C]), res["lines"])
beta_arch = {**beta3, "status": "archived", "retired": {"at": "2026-11-09T01:00:00Z", "by": "cli", "how": "made"}}
put({B: beta_arch, C: gamma3, D: delta}, {**LIVE_IDS}, commit="r11 beta archived", date="2026-11-09T05:50:00+09:00")
R11 = git("rev-parse", "HEAD"); live_again("r12 live again")
res = pv.restore(B, rev=R11)
check("... one that retires a project says so too", res["lines"][1].startswith("THIS RETIRES IT") and res["changed"], res["lines"])
res = pv.restore(rev=R2)
check("... the whole record lists the projects it un-archives", any(x.startswith("THIS UN-ARCHIVES: ") and C in x for x in res["lines"]), res["lines"])
res = pv.restore(B, rev=R3)
check("... and a restore that leaves the status alone has no such line", not any(x.startswith("THIS ") for x in res["lines"]), res["lines"])

# 5. a crash between the record write and the note of the file's hash: the undo still takes the whole file back
real_after = rs._record_after
def boom(meta, undo_file): raise RuntimeError("crash before the hash is noted")
rs._record_after = boom
try:
    try:
        pv.restore(rev=R3, apply=True, run_dir=T / "runs", now="2026-11-09T07:00:00Z"); check("crash: the restore raises", False, "no exception")
    except RuntimeError:
        pass
finally:
    rs._record_after = real_after
UF = T / "runs/20261109T070000Z/undo.json"; um = json.loads(UF.read_text())
check("crash: the record was written and the undo file has no hash of it, but the planned fingerprint, written before the record", rec() == saved3 and um["after_sha256"] == "" and len(um["planned_fingerprint"]) == 64, um)
u = pv.restore_undo(UF)
check("crash: the undo, dry run, still sees the record as the restore's and would put the whole file back", u["changed"] and "put the record file back" in u["lines"][0] and rec() == saved3, u)
u = pv.restore_undo(UF, apply=True)
check("crash: the undo, apply, puts the file back byte for byte", recb() == LIVE, u)
rs._record_after = boom
try:
    try: pv.restore(A, rev=R3, apply=True, run_dir=T / "runs", now="2026-11-09T07:01:00Z")
    except RuntimeError: pass
finally:
    rs._record_after = real_after
UF = T / "runs/20261109T070100Z/undo.json"
d = prj._read(); d["marks"][B] = {"scope": "home"}; prj._write(d)
s1 = snap()
try:
    pv.restore_undo(UF, apply=True); check("crash: after another write the part-by-part undo of one project still works", A not in ents_now() and rec()["marks"].get(B) == {"scope": "home"}, rec())
except pv.VerbError as e2:
    check("crash: after another write the part-by-part undo of one project still works", False, e2.message)
del s1
live_again()

# ---- 6c. the second review's findings
# --before: every zone form, seconds, a zone with a gap, a zone that is no offset, a year that git or a zone's old offset would misread
for text, want, why in (("2026-11-08 18:50Z", R3, "Z is UTC: 18:50 UTC is after R3 (18:38 UTC) and before R4 (19:00 UTC)"),
                        ("2026-11-09 03:50 +09:00", R3, "a +09:00 offset with its colon: 03:50 +09:00 is 18:50 UTC"),
                        ("2026-11-09 03:59:59 +0900", R3, "seconds: one second before R4"), ("2026-11-09T04:00:00 +0900", R4, "the revision at the very second counts as before it")):
    res = pv.restore(rev="", before=text)
    check(f"--before {text!r}: {why}", res["rev"] == want, res["rev"][:10])
res = pv.restore(rev="", before="2026-11-08 20:00 +1400")
check("--before with +1400 (20:00 there is 06:00 UTC on Sun Nov 8th): R1 is the last before it", res["rev"] == R1, res["rev"][:10])
res = pv.restore(before="2026-11-08 20:00:00")
check("--before: seconds with no zone are the instance's (+04) too, and the answer's line says how it was read", res["rev"] == R2 and any(x.startswith("revision picked: the last change to the record before 2026-11-08 20:00 +04") for x in res["lines"]), res["lines"][:3])
for bad, why in (("2026-11-08 12:00 +9999", "an offset of 99 hours"), ("2026-11-08 12:00 +2400", "an offset of 24 hours"), ("2026-11-08 12:00 +1500", "an offset of 15 hours"), ("2026-11-08 12:00 +0960", "an offset of 60 minutes"),
                 ("0999-01-01", "year 999 (a zone's old offset has seconds git misreads)"), ("1969-12-31", "before 1970"), ("2100-01-01", "after 2099"), ("1970-01-01 00:00 +0900", "a moment before 1970 in UTC"),
                 ("0000-01-01", "year 0"), ("2026-02-30", "a day that does not exist")):
    refused(f"refused: --before {bad!r} ({why}): the same 400 as any date git cannot be told", 400, "not a date", lambda bad=bad: pv.restore(before=bad))
for tzname in ("Europe/Berlin", "America/New_York"):
    cfg.CFG["instance"]["timezone"] = tzname
    try:
        refused(f"refused: year 999 in {tzname} (an old local offset of 53 minutes 28 seconds) is a clean 400, never git's silent newest revision", 400, "not a date", lambda: pv.restore(before="0999-06-01 12:00"))
        refused("... and 1970-01-01 00:00 local is a moment before 1970 in UTC for a zone east of it, and a clean 404 for one west of it", 400 if tzname == "Europe/Berlin" else 404,
                "not a date" if tzname == "Europe/Berlin" else "no revision of", lambda: pv.restore(before="1970-01-01 00:00"))
    finally:
        cfg.CFG["instance"]["timezone"] = "Asia/Dubai"
cfg.CFG["instance"]["timezone"] = "America/New_York"
try:
    gap = rs.parse_before("2027-03-14 02:30")                      # 02:30 does not exist on that day in New York: the clocks go from 02:00 to 03:00
    res = pv.restore(before="2027-03-14 02:30")
    check("--before with a wall time that does not exist in the instance's zone (a DST gap): read without error, the answer's line names the moment it was read as, and the revision is a commit",
          gap.tzinfo is not None and re.fullmatch(r"[0-9a-f]{40}", res["rev"]) and any(x.startswith("revision picked: the last change to the record before 2027-03-14 03:30 EDT") for x in res["lines"]), res["lines"][:3])
    check("... and what git is told is that moment in UTC, with +0000, no zone arithmetic of its own", re.fullmatch(r"2027-03-14 0[6-8]:30:00 \+0000", rs.git_date(gap)) is not None, rs.git_date(gap))
finally:
    cfg.CFG["instance"]["timezone"] = "Asia/Dubai"
rc, out, err = cli("restore", "--before", "0999-01-01", "home-alpha")
check("cli: --before 0999-01-01 exits 1 with the 400 text and no traceback", rc == 1 and "[400]" in err and "not a date" in err and "Traceback" not in err, (rc, err))
rc, out, err = cli("restore", "--before", "2026-11-08 12:00 +9999", "home-alpha")
check("cli: --before with +9999 exits 1 with the 400 text and no traceback", rc == 1 and "[400]" in err and "not a date" in err and "Traceback" not in err, (rc, err))

# the held sub-page row is skipped, and the dry run says so
put({B: beta4, C: gamma3, D: delta}, {X8: "projects/alpha/sub", **LIVE_IDS})
res = pv.restore(A, rev=R3)
check("a sub-page id row of the revision whose key another id holds now is not restored, and the dry run's note names both ids and the key",
      res["ids"]["added"] == [A] and any(f"the id row {S} -> projects/alpha/sub of that revision is not restored: {X8} holds that key now" == n for n in res["notes"]) and any(x.startswith("note: the id row") for x in res["lines"]), (res["ids"], res["notes"]))
res = pv.restore(A, rev=R3, apply=True, run_dir=T / "runs", now="2026-11-09T08:00:00Z")
check("... and apply writes the project's own row only", rec()["ids"].get(A) == "projects/alpha" and S not in rec()["ids"] and rec()["ids"].get(X8) == "projects/alpha/sub", rec()["ids"])
live_again()

# every project whose status changes is named in the whole record's headline, and the answer carries the table
put({B: beta4, D: delta}, {B: "projects/beta", D: "projects/delta", Q: "projects/old-thing"})        # gamma lost: it is archived at R11 and R3
res = pv.restore(rev=R11)
check("whole record: a project that comes back archived and one that is retired are both named, a line for each kind",
      any(x == f"THIS BRINGS BACK ARCHIVED: {C} (home-gamma)" for x in res["lines"]) and any(x.startswith("THIS RETIRES: ") and B in x for x in res["lines"]), res["lines"][:6])
check("... and the answer's status_changes is the table: [was, now], with an empty was for the one that comes back", res["status_changes"] == {B: ["active", "archived"], C: ["", "archived"]}, res["status_changes"])
res = pv.restore(C, rev=R3)
check("one project that comes back archived: its own headline says so, and status_changes is in the answer", res["lines"][1] == "THIS BRINGS IT BACK ARCHIVED" and res["status_changes"] == {C: ["", "archived"]}, (res["lines"][:3], res.get("status_changes")))
live_again()

# a whole-record restore that crashed before it noted the hash, then a newer write: the undo refuses, and overwrites nothing
rs._record_after = boom
try:
    try: pv.restore(rev=R3, apply=True, run_dir=T / "runs", now="2026-11-09T08:10:00Z")
    except RuntimeError: pass
finally:
    rs._record_after = real_after
UF = T / "runs/20261109T081000Z/undo.json"
d = prj._read(); d["marks"][B] = {"scope": "home"}; prj._write(d)
newer = recb()
for ap in (False, True):
    try:
        pv.restore_undo(UF, apply=ap); check(f"crash then a newer write: the whole-record undo ({'apply' if ap else 'dry run'}) is refused", False, "no refusal")
    except pv.VerbError as e2:
        check(f"crash then a newer write: the whole-record undo ({'apply' if ap else 'dry run'}) is refused (409), names the file as it was, and overwrites nothing",
              e2.status == 409 and "written after the restore" in e2.message and "project-record.before.json" in e2.message and recb() == newer, (e2.status, e2.message))
live_again()

# ---- 6d. the third review's findings
# the global --dry-run contradicts --apply in every mode, --undo included
res = pv.restore(A, rev=R3, apply=True, run_dir=T / "runs", now="2026-11-09T09:00:00Z")
UF = res["undo"]; at_restore = recb()
for args, why in ((("--dry-run", "restore", "--undo", UF, "--apply"), "--undo"), (("--dry-run", "restore", "--list", "--apply"), "--list"), (("--dry-run", "restore", "--from-git", R3, "--apply"), "a restore")):
    rc, out, err = cli(*args)
    check(f"cli: the global --dry-run with --apply ({why}) exits 2 with the restore usage and writes nothing", rc == 2 and "contradict" in err and "usage: project.py restore" in err and recb() == at_restore, (rc, out, err))
rc, out, err = cli("--dry-run", "restore", "--undo", UF)
check("cli: --dry-run with --undo and no --apply is fine (a dry run of the undo) and writes nothing", rc == 0 and out.startswith("dry run: ") and recb() == at_restore, (rc, out, err))
live_again()

# an undo folder that cannot be written is a one-line message and exit 1, with the record as it was
(T / "afile").write_text("not a folder\n")
before = recb()
for run_dir in (str(T / "afile" / "sub"), "/proc/no-such-dir/x"):
    rc, out, err = cli("restore", "--from-git", R3, "home-alpha", "--apply", "--run-dir", run_dir)
    check(f"cli: --run-dir {run_dir.replace(str(T), '<scratch>')} (cannot be made) exits 1 with one line, no traceback, and the record is not written",
          rc == 1 and "could not be read or written" in err and "Traceback" not in err and len(err.strip().splitlines()) == 1 and recb() == before and A not in ents_now(), (rc, out, err))
try:
    pv.restore(A, rev=R3, apply=True, run_dir=T / "afile" / "sub", now="2026-11-09T09:10:00Z"); check("in process: an undo folder that cannot be made raises", False, "no error")
except OSError:
    check("in process: the OSError comes before the record's write: the record is as it was and there is no undo folder", recb() == before and not (T / "afile" / "sub").exists(), None)

# the offset limit is +1400, the whole way
for bad in ("+1401", "-1401", "+1459", "+14:30"):
    refused(f"refused: --before with the offset {bad} (the largest is +1400)", 400, "not a date", lambda bad=bad: pv.restore(before=f"2026-11-08 12:00 {bad}"))
check("... and +1400 and -1400 are accepted", all(pv.restore(before=f"2026-11-08 12:00 {z}")["rev"] for z in ("+1400", "-1400", "+14:00")), None)

# ---- 7. the CLI, in a subprocess
def cli(*args, check_live=True):
    r = subprocess.run([sys.executable, f"{STACK}/stackshot/tools/project.py", *args], capture_output=True, text=True, env=os.environ, cwd=str(T))
    return r.returncode, r.stdout, r.stderr
s0 = snap()
rc, out, err = cli("restore", "--list", "--limit", "3")
check("cli: --list prints three revisions with their dates and counts, exit 0", rc == 0 and len(re.findall(r"^[0-9a-f]{10}  ", out, re.M)) == 3 and "Mon Nov 9th" in out and "projects" in out and snap() == s0, (rc, out, err))
rc, out, err = cli("restore", "--from-git", R3, "home-alpha")
check("cli: a dry run of one project says so, writes nothing, exit 0", rc == 0 and out.startswith("dry run: restore home-alpha from ") and "comes back" in out and "nothing written (add --apply)" in out and snap() == s0, (rc, out, err))
rc, out, err = cli("--json", "restore", "--from-git", R3, "home-alpha")
check("cli: --json prints the whole answer", rc == 0 and json.loads(out)["added"] == [A] and json.loads(out)["dry"] is True, (rc, out[:300], err))
rc, out, err = cli("restore", "--from-git", R3, "home-alpha", "--apply", "--run-dir", str(T / "cli-runs"))
undo_path = (re.search(r"undo file (\S+)", out) or [None, ""])[1]
check("cli: --apply writes, prints the undo file and the command to take it back", rc == 0 and A in ents_now() and undo_path.startswith(str(T / "cli-runs")) and "restore --undo " in out, (rc, out, err))
rc, out, err = cli("restore", "--undo", undo_path)
check("cli: --undo without --apply is a dry run", rc == 0 and out.startswith("dry run: ") and A in ents_now(), (rc, out, err))
rc, out, err = cli("restore", "--undo", undo_path, "--apply")
check("cli: --undo --apply puts the file back", rc == 0 and recb() == LIVE, (rc, out, err))
rc, out, err = cli("restore", "--from-git", "no-such-rev-0123", "home-alpha", "--apply")
check("cli: a refusal exits 1 with the reason on stderr and writes nothing", rc == 1 and "[404]" in err and "does not know the revision" in err and recb() == LIVE, (rc, out, err))
rc, out, err = cli("restore", "--from-git", R3, "no-such-project")
check("cli: a project the revision does not hold exits 1", rc == 1 and "is not a project in revision" in err, (rc, out, err))
for args, why in ((("restore",), "no revision"), (("restore", "--from-git", R3, "--before", "2026-11-09"), "two revisions"), (("restore", "--list", "--apply"), "--list with --apply"),
                  (("restore", "--undo", "x", "--from-git", R3), "--undo with a revision"), (("--dry-run", "restore", "--from-git", R3, "--apply"), "--apply with --dry-run"),
                  (("restore", "--list", "--limit", "0"), "--limit 0")):
    rc, out, err = cli(*args)
    check(f"cli: wrong arguments ({why}) exit 2 and print the restore usage", rc == 2 and "usage: project.py restore" in err and recb() == LIVE, (rc, out, err))
rc, out, err = cli("restore", "--undo", str(T / "nothing-here.json"), "--apply")
check("cli: an undo file that is not there exits 1", rc == 1 and "not readable" in err, (rc, out, err))
rc, out, err = cli("restore", "-h")
check("cli: -h names every flag", rc == 0 and all(f in out for f in ("--from-git", "--before", "--list", "--limit", "--apply", "--undo", "--run-dir")), out)

# ---- 8. nothing outside the scratch folder, and the repository itself was only read
check("the repository's work tree is clean and its refs are the fixture's own commits (a restore made none)", git("status", "--porcelain") == "" and git("rev-list", "--count", "--all") == git("rev-list", "--count", "HEAD"), git("status", "--porcelain"))
check("no refs, stashes or reflog entries were made by a restore: the repository has its own commits only", git("rev-list", "--count", "--all") == git("rev-list", "--count", "HEAD") and git("stash", "list") == "", None)
runs = sorted(str(p) for p in (T / "runs").rglob("*")) + sorted(str(p) for p in (T / "cli-runs").rglob("*"))
check("every undo file and copy was made under the scratch folder", runs and all(r.startswith(tmp) for r in runs) and not UNDO_ROOT.exists(), runs[:3])
check("the default undo folder (under the scratch HOME) was used by nothing: every test that applied named its own run folder", not UNDO_ROOT.exists(), None)
stray = [p for p in pathlib.Path("/home").glob("*/.local/share/stackshot-runs/project-restore/*") if p.stat().st_mtime > os.stat(tmp).st_ctime]
check("no undo folder was made in any real home's stackshot-runs during this run", not stray, stray)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
