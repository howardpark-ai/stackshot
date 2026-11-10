"""Scenario test for items by project id: an item stores the permanent id of its project (metadata.project_id), and every reader that groups, filters or labels items by project reads the page through it
(item_project.py, the project-id pass server._pid_one / _unpid_one, the project_id and unproject_id ops of the migration route, tools/project_id_report.py) — fixture data, no live store written, no
network, no server socket.

A page key is not permanent: a project's page moves and is renamed. The project record holds, per project, the page it points at and the keys the page had before, and now an item holds the project's id.
The id is the TOP-LEVEL project's: a sub-page is no project, so an item filed on a sub-page (its plain detail link, stored as before) stores the id of the project that owns the sub-page.

  1  resolver                derive(): a page key, a former key, a bare slug, a sub-page's key, a page with a `hub:` line, a project's own id → the id of the top-level project; an unknown key → ""
  2  key_of                  the page key an item reads as: its stored key when the id adds nothing, the project's current page after a move or rename, a sub-page's own key kept, a stale id never over a key another project owns
  3  plan_and_dry            the pass's plan names each item's id; a dry run writes nothing
  4  pass_writes_one_key     every item, open or closed, gets project_id and no other key changes (no clock, no `project`); an item naming no known project is left byte for byte
  5  idempotent              a second pass writes nothing and rewrites no file
  6  readers_same            the board's markdown and brief and the server's brief, and every open item's project key, are the same before and after the pass
  7  moved_page_keeps_items  after the record moves a page (the old key a former key), stored items read at the new page in every reader (anchors, both render modules, the project counts) with no write to them; an
                            item with no id reads as it stored; moving again follows
  8  write_paths             a save sets the id from the key; update(project=…) re-files and the id follows; a sub-page's key keeps the top-level id; an id that names no project is left
  9  undo_roundtrip          apply then undo gives the same values in every file; twice is a no-op; an id a later save changed is `kept`
  10 gate                    refused with [model] migration off, for a sender or a machine outside the lists, for a body naming another key, for an undo entry naming a key the pass does not write
  11 script                  tools/project_id_report.py: --apply asks for the plan first and writes the undo file before the first write; --undo puts the files back; the dry run over a copy writes nothing and exits 0
  12 top_level_display       an item's PROJECT, where it is shown, grouped or counted, is the top-level project (item_project.project_of / top_of / line_of): a sub-page's item and a hub page's item read as the project that
                            owns the page, a top-level item and one naming no project as stored, a renamed or moved project at its page now, with a stored id or without one; board.md (both render modules), the item page,
                            get and brief show it, while the item's detail link and every reader that needs the PAGE (key_of, anchors, proj_key, the board row) keep the page it is filed on; a read writes nothing

    tests/run-suite item_project        → exit 0 / 1"""
import argparse, contextlib, io, json, logging, os, pathlib, re, subprocess, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="itemprj-"); T = pathlib.Path(tmp)


def mk_toml(root):
    """A config whose every path is inside `root`, with no GitHub mirror and no commit."""
    t = _instance.apply(_instance.base_toml(), owner=True)
    t = t.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in t
    for key, val in (("repo", root), ("store", f"{root}/store"), ("markdown", f"{root}/board.md"), ("brain", f"{root}/brain"),
                     ("state", f"{root}/state"), ("secrets", f"{root}/secrets"), ("project_touch", f"{root}/touch"), ("rules", f"{root}/RULES.md"), ("timezone", "Asia/Dubai")):
        t, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', t); assert n == 1, key
    t, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', t); assert n == 1
    t, n = re.subn(r'(?m)^git = true', 'git = false', t, count=1); assert n == 1
    t, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{root}/no-such-root", "{root}/transcripts"]', t); assert n == 1
    t, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", t); assert n == 1
    return t


(T / "stackshot.toml").write_text(mk_toml(tmp), encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects", "brain/ops", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-sparrow", "home-sparrow-main", "home-sparrow-engineer", "home-beta", "home-beta-main", "home-gamma", "home-gamma-main")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = 1_790_000_000.0                                          # a fixed clock: the board's text reads the time, and the suite must not straddle a minute or a midnight
DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in U.items()}))
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")


def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")


page("projects/alpha.md", "type: project\ntitle: Alpha\ndisplay-name: home-sparrow\nagents:\n  home-sparrow-main: talks to Oliver\n  background:\n    home-sparrow-engineer: builds\nstatus: active")
page("projects/alpha/sub.md", "type: project\ntitle: Sub")
page("ops/alpha-tool.md", "type: note\ntitle: Alpha tool\ndisplay-name: home-sparrow\nhub: projects/alpha")
page("projects/beta.md", "type: project\ntitle: Beta\ndisplay-name: home-beta\nagents:\n  home-beta-main: talks to Oliver\nstatus: active")
page("projects/gamma.md", "type: project\ntitle: Gamma\ndisplay-name: home-gamma\nagents:\n  home-gamma-main: talks to Oliver\nstatus: active")
page("projects/gamma2.md", "type: project\ntitle: Gamma moved again\ndisplay-name: home-gamma\nagents:\n  home-gamma-main: talks to Oliver\nstatus: active")
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools")); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

from stackshot.projects import pages as pg; from stackshot.projects import project_registry as PR; from stackshot.model import item_project as IP
from stackshot.web import server; from stackshot.anchors import anchors as ANC; from stackshot.web import render as R1; from stackshot.projects import projects as PRJ; from stackshot.tools import stamp_phase as SP; from stackshot.tools import project_id_report as RR
from stackshot.web.ui import render as R2
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
server._tell_woken = lambda gid, owner, note, tag="wake": None
server._front_sender = lambda who: False
CFGM = server._cfg.CFG.setdefault("model", {})
CFGM.update(guards=True, watchers=True, pause=False, one_mover=True, handoff=True, switchover=False, migration=False)
pg.cmd_registry(quiet=True)                                     # mints the ids of the pages above and writes <store>/project-record.json
REG = json.loads((T / "store/projects.json").read_text())["pages"]
ID = {k: e["id"] for k, e in REG.items()}
A, B, G, G2, SUB, TOOL = (ID[k] for k in ("projects/alpha", "projects/beta", "projects/gamma", "projects/gamma2", "projects/alpha/sub", "ops/alpha-tool"))
PL = "prj_0a0b0c0d"                                             # a project with no page: an entry of the record and nothing else
REC = T / "store/project-record.json"
def record(): return json.loads(REC.read_text())
def write_record(d): REC.write_text(json.dumps(d, indent=1))
d0 = record()
d0.setdefault("projects", {})[PL] = {"name": "Loose", "type": "project", "status": "active"}
d0["projects"][G] = {"name": "Gamma", "type": "project", "status": "active", "page": "projects/gamma", "former_keys": ["projects/old-gamma"]}      # gamma's page was projects/old-gamma
write_record(d0)
DESC = "- A thing\n- It lives here\n- Done when done"


def put(i, project, status="open", letter="g", **meta):
    base = {"owner": U["home-sparrow-main"], "next": "home-sparrow-engineer: do the thing"}
    if project is not None: base["project"] = project
    base.update(meta)
    su = now0 - 10 * DAY
    with open(T / f"store/{letter}/{i}.json", "w", encoding="utf-8") as f:
        json.dump({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status, "updated": su, "state_updated": su, "confirmed": su, "metadata": base}, f, ensure_ascii=False, indent=1)
def raw(i, letter="g"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
def mt(i): return raw(i)["metadata"]
def bytes_of(i): return (T / f"store/g/{i}.json").read_bytes()
def snapshot(): return {p.name: p.read_bytes() for p in sorted((T / "store/g").glob("*.json"))}
def values(snap): return {k: json.loads(v) for k, v in snap.items()}


CASES = {1: ("projects/alpha", "open"), 2: ("projects/alpha/sub", "open"), 3: ("ops/alpha-tool", "open"), 4: ("projects/beta", "open"), 5: ("projects/old-gamma", "completed"),
         6: ("alpha", "open"), 7: ("projects/nowhere", "open"), 8: (PL, "open"), 9: ("projects/beta", "open"), 10: ("projects/alpha", "open"), 11: ("projects/beta", "completed")}
for i, (k, st) in CASES.items():
    put(i, k, status=st, **({"project_id": A} if i in (9, 10) else {}))          # 9 stores another project's id (a stale one); 10 stores its own
OPEN = [i for i, (_k, st) in CASES.items() if st == "open"]
EXPECT = {1: A, 2: A, 3: A, 4: B, 5: G, 6: A, 8: PL, 9: B, 11: B}              # 7 names no project; 10 stores A already

# ---- 1. the resolver
IP_D = IP.derive
check("1 a page key, a former key, a bare slug and a project's own id each give the top-level project's id", (IP_D("projects/alpha"), IP_D("projects/old-gamma"), IP_D("alpha"), IP_D(A), IP_D(PL)) == (A, G, A, A, PL), [IP_D(x) for x in ("projects/alpha", "projects/old-gamma", "alpha", A, PL)])
check("1 …a sub-page's key and a page with a hub: line give the project that owns them, not their own id", IP_D("projects/alpha/sub") == A and IP_D("ops/alpha-tool") == A and SUB != A and TOOL != A, (IP_D("projects/alpha/sub"), IP_D("ops/alpha-tool")))
check("1 …a key that names no project, and an id nothing knows, give nothing", IP_D("projects/nowhere") == "" and IP_D("prj_deadbeef") == "" and IP_D("") == "" and IP_D(None) == "", None)

# ---- 2. the key an item reads as
K = lambda **m: IP.key_of(m)
check("2 an item with no id reads as it stored", K(project="projects/alpha") == "projects/alpha" and K(project="projects/nowhere") == "projects/nowhere" and K(project="alpha") == "alpha", None)
check("2 …one whose id names the page it stores, or a sub-page of it, or a page that hangs off it by hub:, reads as it stored (the plain detail link)", K(project="projects/alpha", project_id=A) == "projects/alpha"
      and K(project="projects/alpha/sub", project_id=A) == "projects/alpha/sub" and K(project="ops/alpha-tool", project_id=A) == "ops/alpha-tool", None)
check("2 …a former key of the project reads as the project's page now; an item with an id and no key reads as the page", K(project="projects/old-gamma", project_id=G) == "projects/gamma" and K(project_id=G) == "projects/gamma", (K(project="projects/old-gamma", project_id=G), K(project_id=G)))
check("2 …a stale id never wins over a key another project owns; an id nothing knows leaves the key; a pageless project's id is its own key", K(project="projects/beta", project_id=A) == "projects/beta"
      and K(project="projects/beta", project_id="prj_deadbeef") == "projects/beta" and K(project=PL, project_id=PL) == PL, None)
meta_ = {"project": "projects/old-gamma", "project_id": G}
IP.read_through({"metadata": meta_})
check("2 read_through changes the in-memory dict only, and a file is never written by a read", meta_["project"] == "projects/gamma" and mt(5)["project"] == "projects/old-gamma", None)

# ---- 3. the plan and the dry run
snap0 = snapshot()
for i in CASES: os.utime(T / f"store/g/{i}.json", (now0 - 40 * DAY - i, now0 - 40 * DAY - i))          # a time of its own on each file
MT0 = {i: os.stat(T / f"store/g/{i}.json").st_mtime_ns for i in CASES}
res = {i: server._pid_one(f"g{i}", dry=True) for i in CASES}
check("3 the plan: an id for each item that names a project, `same` for the one that stores its own, `unresolved` for the one that names none",
      all(res[i]["action"] == "would_set" and res[i]["after"] == {"project_id": EXPECT[i]} for i in EXPECT) and res[10]["action"] == "same" and res[7]["action"] == "unresolved", {i: (r["action"], r["after"]) for i, r in res.items()})
check("3 …a closed item is planned like an open one, and the plan carries the file's hash", res[5]["action"] == "would_set" and res[11]["status"] == "completed" and all(len(r["sha256_before"]) == 64 for r in res.values()), res[5])
check("3 …a dry run writes nothing", snapshot() == snap0, None)

# ---- 6 (before). what the readers show, before the pass
def reads(open_only=True):
    out = {}
    with SP.frozen(now0):
        out["server brief"] = server.stackshot_brief()
        for tag, mod in (("render.py", R1), ("ui/render.py", R2)):
            B_ = mod.Board(str(T / "store"))
            out[tag + " md"] = B_.markdown()
            out[tag + " brief"] = B_.brief()
    its = {i: server._load(f"g{i}") for i in OPEN}
    out["keys"] = json.dumps({i: [ANC.project_of(it), R1.proj_key(it), R2.proj_key(it)] for i, it in its.items()}, sort_keys=True)
    return out
before_reads = reads()
check("6 the fixture is shown by the readers: a brief and a board with the open items in them", len(before_reads["server brief"]) > 200 and len(before_reads["render.py md"]) > 200 and "projects/alpha" in before_reads["keys"], before_reads["server brief"][:300])

# ---- 4. the pass writes one key
CFGM["migration"] = False
wrote = {i: server._pid_one(f"g{i}") for i in CASES}
snap1 = snapshot()
check("4 every item but the one naming no project got its id, open or closed", all(wrote[i]["action"] == "set" and mt(i).get("project_id") == EXPECT[i] for i in EXPECT) and wrote[10]["action"] == "same" and wrote[7]["action"] == "unresolved", {i: (r["action"], mt(i).get("project_id")) for i, r in wrote.items()})
def minus(d, k): return {a: b for a, b in d.items() if a != k}
check("4 …nothing else in a file changed: not `project`, not a clock, not any other metadata key",
      all(minus(raw(i)["metadata"], "project_id") == minus(json.loads(snap0[f"{i}.json"])["metadata"], "project_id") and minus(raw(i), "metadata") == minus(json.loads(snap0[f"{i}.json"]), "metadata") for i in CASES), None)
check("4 …the id is the last key of the metadata (a new key goes last), and the file is written in the form the server writes it", all(list(mt(i))[-1] == "project_id" for i in EXPECT if i not in (9,)), {i: list(mt(i)) for i in (1, 5)})
check("4 …every file keeps its modification time (a legacy closed item is dated by it)", all(os.stat(T / f"store/g/{i}.json").st_mtime_ns == MT0[i] for i in CASES), None)
check("4 …an item naming no known project, and one that already stored its id, are left byte for byte", snap1["7.json"] == snap0["7.json"] and snap1["10.json"] == snap0["10.json"], None)
check("4 …a stale id (a beta item that stored alpha's) was replaced by the id of the key", mt(9)["project_id"] == B and mt(9)["project"] == "projects/beta", mt(9))
check("4 …a sub-page's item stores the top-level project's id and keeps its sub-page as its key", mt(2)["project_id"] == A and mt(2)["project"] == "projects/alpha/sub" and mt(3)["project_id"] == A and mt(3)["project"] == "ops/alpha-tool", (mt(2), mt(3)))

# ---- 5. idempotent
again = {i: server._pid_one(f"g{i}") for i in CASES}
check("5 a second pass writes nothing: every item is `same` or `unresolved`, and no file is rewritten", {r["action"] for r in again.values()} == {"same", "unresolved"} and snapshot() == snap1, {i: r["action"] for i, r in again.items()})

# ---- 6 (after). the readers show the same
after_reads = reads()
for name in before_reads:
    check(f"6 {name} is the same before and after the pass", before_reads[name] == after_reads[name], [(a, b) for a, b in zip(before_reads[name].splitlines(), after_reads[name].splitlines()) if a != b][:3])

# ---- 7. a page that moves keeps its items
put(12, "projects/old-gamma"); server._pid_one("g12")
b12 = bytes_of(12)
put(13, "projects/old-gamma")                                         # an open item the pass has not reached: no id
check("7 a stored item on a former key reads at the page now, in the anchors, both render modules and the project counts, with no write", ANC.project_of(server._load("g12")) == "projects/gamma"
      and R1.proj_key(server._load("g12")) == "projects/gamma" and R2.proj_key(server._load("g12")) == "projects/gamma" and bytes_of(12) == b12, (ANC.project_of(server._load("g12")), mt(12)))
RC = PRJ.recent_items(server._registry("projects"), now=now0)
check("7 …the project counts see the stored items under the page now; only the item with no id is still counted under the former key", RC.get("projects/gamma", 0) == 2 and RC.get("projects/old-gamma", 0) == 1, RC)
check("7 …an item with no id reads as it stored (the pass has not reached it)", ANC.project_of(server._load("g13")) == "projects/old-gamma", ANC.project_of(server._load("g13")))
d1 = record(); d1["projects"][G]["page"] = "projects/gamma2"; d1["projects"][G]["former_keys"] = ["projects/old-gamma", "projects/gamma"]; write_record(d1)
check("7 the record moves the page again and the stored items follow, the former key and the first page both", ANC.project_of(server._load("g12")) == "projects/gamma2" and ANC.project_of({"metadata": {"project": "projects/gamma", "project_id": G}}) == "projects/gamma2"
      and R2.proj_key(server._load("g12")) == "projects/gamma2" and bytes_of(12) == b12, ANC.project_of(server._load("g12")))
d1["projects"][G]["page"] = "projects/gamma"; d1["projects"][G]["former_keys"] = ["projects/old-gamma"]; write_record(d1)

# ---- 8. the write paths
it = server._load("g1"); it["metadata"]["project"] = "projects/beta"; server._save("g1", it)
check("8 a save of an item re-filed under another project sets that project's id", mt(1)["project"] == "projects/beta" and mt(1)["project_id"] == B, mt(1))
it = server._load("g1"); it["metadata"]["project"] = "projects/alpha/sub"; server._save("g1", it)
check("8 …a sub-page's key sets the id of the project that owns it and stays the stored key", mt(1)["project"] == "projects/alpha/sub" and mt(1)["project_id"] == A, mt(1))
it = server._load("g7"); it["metadata"]["subject_note"] = "x"; server._save("g7", it)
check("8 …a key that names no project leaves the item without an id (nothing is made up)", "project_id" not in mt(7), mt(7))
m12 = dict(mt(12)); it = server._load("g12"); server._save("g12", it)
check("8 …a save of an item whose page moved stores the page now, the id stays, and the move is no re-file (no refile record, the contact and mover as they were)",
      mt(12)["project"] == "projects/gamma" and mt(12)["project_id"] == G and "refiled" not in mt(12) and mt(12).get("contact") == m12.get("contact") and mt(12).get("mover") == m12.get("mover"), (m12, mt(12)))
r_ = server.stackshot_update("g4", sender="home-sparrow-main", project="projects/alpha")
check("8 update(project=…) re-files the item and the id follows it", mt(4)["project"] == "projects/alpha" and mt(4)["project_id"] == A, (mt(4), str(r_)[:200]))
r_ = server.stackshot_create(subject="[home] a new item", description="- Goal: a new item exists\n- It lives here\n- Done when done", project="projects/beta", sender="home-beta-main", next="home-beta-main: look at it")
gid_new = re.search(r"\b(g\d+|board#\d+)\b", str(r_)); new_m = None
for p_ in sorted((T / "store").glob("*/*.json")):
    d_ = json.loads(p_.read_text()) if p_.stem.isdigit() else {}
    if d_.get("subject") == "[home] a new item": new_m = d_["metadata"]
check("8 create stores the project's id beside the key", new_m is not None and new_m.get("project") == "projects/beta" and new_m.get("project_id") == B, (new_m, str(r_)[:200]))

# ---- 8b. a re-file to a registered page the record has no project for
REC_KEEP = record()
d2 = record(); d2["ids"].pop(B, None); d2.get("projects", {}).pop(B, None); write_record(d2)           # beta stays a page of the registry, and the record no longer knows it
check("8b the fixture: beta is a page, and no project of the record owns it", "projects/beta" in IP._pages() and IP.derive("projects/beta") == "" and IP.derive("projects/alpha") == A, (IP.derive("projects/beta"), IP.derive("projects/alpha")))
check("8b …the item to re-file stores alpha's id", mt(4)["project"] == "projects/alpha" and mt(4)["project_id"] == A, mt(4))
r_ = server.stackshot_update("g4", sender="home-sparrow-main", project="projects/beta")
check("8b (a) update(project=…) to such a page takes the old project's id out of the file", mt(4)["project"] == "projects/beta" and "project_id" not in mt(4), (mt(4), str(r_)[:200]))
check("8b (a) …and the item reads as its new key, through key_of and the anchors, not as the project it left", IP.key_of(mt(4)) == "projects/beta" and ANC.project_of(server._load("g4")) == "projects/beta"
      and R1.proj_key(server._load("g4")) == "projects/beta" and R2.proj_key(server._load("g4")) == "projects/beta", (IP.key_of(mt(4)), ANC.project_of(server._load("g4"))))
put(14, "projects/beta", project_id=A)                                                            # a file a build without the fix left: beta's key, alpha's id
check("8b …a file that already holds the stale id reads as its key too (a page that exists and no project owns wins over the id)", IP.key_of(mt(14)) == "projects/beta" and ANC.project_of(server._load("g14")) == "projects/beta", (IP.key_of(mt(14)), ANC.project_of(server._load("g14"))))
check("8b …a page that moved (its old key is no page, and no project owns it) still follows the id", IP.key_of({"project": "projects/old-alpha", "project_id": A}) == "projects/alpha", IP.key_of({"project": "projects/old-alpha", "project_id": A}))
b14 = bytes_of(14)
r14 = server._pid_one("g14", dry=True)
check("8b (b) the pass reports a stale id as one it would take out: after shows no id, before shows the old one, and a dry run writes nothing",
      r14["action"] == "would_set" and r14["before"] == {"project_id": A} and r14["after"] == {"project_id": None} and bytes_of(14) == b14, r14)
r14 = server._pid_one("g14")
check("8b (b) …the pass takes the stale id out, writes that one key, and keeps the file's time", r14["action"] == "set" and r14["after"] == {"project_id": None} and "project_id" not in mt(14)
      and minus(mt(14), "project_id") == minus(json.loads(b14)["metadata"], "project_id"), r14)
check("8b (b) …a second pass writes nothing, and an item that stores no id is `unresolved` with no id after", server._pid_one("g14")["action"] == "unresolved" and server._pid_one("g14")["after"] == {"project_id": None}
      and server._pid_one("g4")["after"] == {"project_id": None}, server._pid_one("g14"))
u14 = server._unpid_one({"item": r14["item"], "before": r14["before"], "after": r14["after"]})
check("8b (b) …undo puts the id back as it was (byte for byte), and a second undo is a no-op", u14["action"] == "set" and bytes_of(14) == b14 and server._unpid_one({"item": r14["item"], "before": r14["before"], "after": r14["after"]})["action"] == "same", u14)
(T / "store/g/14.json").unlink(missing_ok=True)
write_record(REC_KEEP)
check("8b the record is back as it was", IP.derive("projects/beta") == B, IP.derive("projects/beta"))
ids_seen = []
for tgt in ("projects/gamma", "projects/alpha", "projects/beta"):
    server.stackshot_update("g4", sender="home-sparrow-main", project=tgt); ids_seen.append((mt(4)["project"], mt(4).get("project_id")))
check("8b (c) a re-file between recorded projects swaps the id each time", ids_seen == [("projects/gamma", G), ("projects/alpha", A), ("projects/beta", B)], ids_seen)

# ---- 9. undo
for i in CASES: put(i, CASES[i][0], status=CASES[i][1], **({"project_id": A} if i in (9, 10) else {}))
for i in (12, 13): (T / f"store/g/{i}.json").unlink(missing_ok=True)
snapU = snapshot()
CFGM["migration"] = True
SENDER = "falcon-engineer"
call = lambda machine="box-a", **body: server._client_post(machine, "migrate", {"sender": SENDER, **body})
st_, d_ = call(op="project_id", items=[f"g{i}" for i in CASES], pass_id="20260101-000000-abcdef")
undo_entries = [{"item": r["item"], "before": r["before"], "after": r["after"]} for r in d_["results"] if r["action"] == "set"]
check("9 the route stores the ids and answers, per item, the key before and after", st_ == 200 and len(undo_entries) == len(EXPECT), (st_, d_["results"][:2] if st_ == 200 else d_))
check("9 …every file now holds its id", all(mt(i).get("project_id") == EXPECT[i] for i in EXPECT), None)
(T / "store/g/1.json").write_text(json.dumps({**raw(1), "metadata": {**mt(1), "project_id": B}}, ensure_ascii=False, indent=1))      # a later save stored another id than the pass left
st_, d_ = call(op="unproject_id", items=undo_entries)
acts = {r["item"]: r["action"] for r in d_["results"]}
check("9 undo takes the id out of every file the pass wrote, and an id a later save changed is `kept`", st_ == 200 and acts.get("board#1", acts.get("g1")) == "kept" and sum(1 for a in acts.values() if a == "set") == len(EXPECT) - 1, acts)
check("9 …every other file is as it was before the pass (the `kept` one stays as the save left it)", all(json.loads(snapshot()[f"{i}.json"]) == json.loads(snapU[f"{i}.json"]) for i in CASES if i != 1), None)
st_, d_ = call(op="unproject_id", items=undo_entries)
check("9 …a second undo changes nothing", st_ == 200 and {r["action"] for r in d_["results"]} <= {"same", "kept"}, {r["item"]: r["action"] for r in d_["results"]})
for i in CASES: put(i, CASES[i][0], status=CASES[i][1], **({"project_id": A} if i in (9, 10) else {}))

# ---- 10. the gate
b7 = bytes_of(7); b4 = bytes_of(4)
CFGM["migration"] = False
st_, d_ = call(op="project_id", items=["g4"])
check("10 the route is refused while [model] migration is off", st_ == 403 and bytes_of(4) == b4, (st_, d_))
CFGM["migration"] = True
st_, d_ = call(op="project_id", items=["g4"], sender="somebody-else")
check("10 …and for a sender outside [model] migration_senders", st_ == 403 and bytes_of(4) == b4, (st_, d_))
st_, d_ = call(machine="home-evil", op="project_id", items=["g4"])
check("10 …and for a token from a machine outside migration_machines", st_ == 403 and bytes_of(4) == b4, (st_, d_))
st_, d_ = call(op="project_id", items=["g4"], writes=[{"item": "g4", "set": {"mover": "x"}}])
check("10 …a body naming a key of its own is refused whole", st_ == 400 and "takes op, sender, items" in d_["error"] and bytes_of(4) == b4, (st_, d_))
st_, d_ = call(op="unproject_id", items=[{"item": "g4", "before": {"mover": None}, "after": {"mover": "x"}}])
check("10 …an undo entry naming a key the pass does not write is refused", d_["results"][0]["action"] == "refused", d_)
st_, d_ = call(op="unproject_id", items=[{"item": "g4", "before": {"project_id": None}, "after": {"project_id": "not-an-id"}}])
check("10 …and one that names a value that is no project id", d_["results"][0]["action"] == "refused", d_)
st_, d_ = call(op="unproject_id", items=["g4"], dry=True)
check("10 …dry goes with project_id only; an empty list is refused; an unknown item and a malformed id are refused one by one", st_ == 400 and call(op="project_id", items=[])[0] == 400
      and [r["action"] for r in call(op="project_id", items=["g9999", "nonsense"])[1]["results"]] == ["refused", "refused"], (st_, d_))
st_, d_ = call(op="project_id", items=["g7"])
check("10 …an item that names no project answers `unresolved` and stays byte for byte", d_["results"][0]["action"] == "unresolved" and bytes_of(7) == b7, d_)
CFGM["migration"] = False

# ---- 11. the script
class DirectApp:
    """The live server's route, called in this process (what LiveApplier does over HTTP)."""
    def __init__(self): self.log = []
    def call(self, body):
        self.log.append(body["op"] + ("-dry" if body.get("dry") else ""))
        return server._client_post("box-a", "migrate", {**body, "sender": SENDER})
CFGM["migration"] = True
RUN = pathlib.Path(_scratch.mkdtemp(prefix="itemprj-run-"))
args = argparse.Namespace(sender=SENDER, run_dir=str(RUN), undo="")
snapS0 = snapshot()
def cli(fn, app=None, **kw):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = fn(argparse.Namespace(**{**vars(args), **kw}), app or DirectApp())
    try: return rc, json.loads(out.getvalue())
    except ValueError: return rc, out.getvalue()
app = DirectApp()
orig_write = SP.write_atomic
seen_undo = []
def spy(path, obj):
    if str(path).endswith("undo.json") and not seen_undo and not any(r.get("result") for r in obj["items"]):
        seen_undo.append((len([f for f in snapshot() if snapshot()[f] != snapS0[f]]), len(obj["items"])))      # files already written when the undo file first lands
    return orig_write(path, obj)
SP.write_atomic = spy
rc1, out1 = cli(RR.apply, app=app)
SP.write_atomic = orig_write
undo_file = pathlib.Path(out1["undo"]) if isinstance(out1, dict) else pathlib.Path("/nonexistent")
check("11 apply asks for the plan first (a dry call), writes the undo file, ends well", rc1 == 0 and app.log[0] == "project_id-dry" and "project_id" in app.log and undo_file.is_file() and out1["results"].get("set") == len(EXPECT), (rc1, out1, app.log))
check("11 …the undo file is written whole before the first file changes", seen_undo and seen_undo[0][0] == 0 and seen_undo[0][1] == len(EXPECT), seen_undo)
uj = json.loads(undo_file.read_text()) if undo_file.is_file() else {"items": []}
check("11 …it names each item with its key before and after and the real result", {"pass_id", "by", "when", "store", "items"} <= set(uj) and all({"item", "before", "after", "sha256_before", "result"} <= set(e) and e["result"] == "set" for e in uj["items"]), uj["items"][:1])
check("11 …the ids are stored, and the unresolved item is reported and untouched", all(mt(i).get("project_id") == EXPECT[i] for i in EXPECT) and "project_id" not in mt(7) and out1["unresolved"], out1)
rc2, out2 = cli(RR.apply)
check("11 a second apply stores nothing", rc2 == 0 and out2.get("stored") == 0, (rc2, out2))
rc3, out3 = cli(RR.undo, undo=str(undo_file))
check("11 --undo puts every file back value for value", rc3 == 0 and values(snapshot()) == values(snapS0) and out3["results"] == {"set": len(EXPECT)}, (rc3, out3))
rc4, out4 = cli(RR.undo, undo=str(undo_file))
check("11 …twice is a no-op", rc4 == 0 and values(snapshot()) == values(snapS0) and set(out4["results"]) == {"same"}, (rc4, out4))
check("11 --apply and --undo need --sender", subprocess.run([sys.executable, os.path.join(STACK, "stackshot/tools/project_id_report.py"), "--apply"], capture_output=True, text=True).returncode != 0 and subprocess.run([sys.executable, os.path.join(STACK, "stackshot/tools/project_id_report.py"), "--undo", "x.json"], capture_output=True, text=True).returncode != 0, None)
CFGM["migration"] = False
snapD = snapshot()
p = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/tools/project_id_report.py"), "--store", str(T / "store")], capture_output=True, text=True, env={**os.environ, "STACKSHOT_CONFIG": f"{tmp}/stackshot.toml"})
check("11 the dry run over a copy writes nothing live, prints the totals and the readers' comparison, and exits 0", p.returncode == 0 and snapshot() == snapD and "items the pass would write" in p.stdout
      and "readers that show the open items differently before and after: 0" in p.stdout, (p.returncode, p.stdout[-900:], p.stderr[-600:]))

# ---- 12. an item's project reads as the top-level project; the page it is filed on stays its detail link
REC12 = record()
for i, k in {20: "projects/alpha/sub", 21: "projects/alpha", 22: "ops/alpha-tool", 23: "projects/beta", 24: "projects/nowhere", 25: "projects/old-gamma"}.items(): put(i, k)
server._pid_one("g20"); server._pid_one("g25")                                    # these two store their id; the others store none
PO = lambda **m: IP.project_of(m)
check("12 a sub-page's item reads as the project that owns the page, with a stored id and without one", PO(project="projects/alpha/sub", project_id=A) == "projects/alpha" and PO(project="projects/alpha/sub") == "projects/alpha", (PO(project="projects/alpha/sub", project_id=A), PO(project="projects/alpha/sub")))
check("12 …a page with a hub: line reads as its hub's project", PO(project="ops/alpha-tool") == "projects/alpha" and PO(project="ops/alpha-tool", project_id=A) == "projects/alpha", PO(project="ops/alpha-tool"))
check("12 …a top-level item reads as it stored (the string as written, a trailing .md too), with an id and without one", PO(project="projects/alpha") == "projects/alpha" and PO(project="projects/alpha", project_id=A) == "projects/alpha"
      and PO(project="projects/alpha.md") == "projects/alpha.md" and PO(project="projects/beta") == "projects/beta", (PO(project="projects/alpha.md"), PO(project="projects/beta")))
check("12 …a key that names no project reads as stored, and so does an empty one, a metadata with no project and a value that is no dict", PO(project="projects/nowhere") == "projects/nowhere" and PO(project="projects/nowhere", project_id="prj_deadbeef") == "projects/nowhere"
      and PO(project="") == "" and PO() == "" and IP.project_of(None) == "" and IP.top_of("") == "" and IP.top_of("projects/nowhere") == "projects/nowhere", None)
check("12 …a stale id never wins over a page another project owns, a pageless project's id is its own key, and an id alone reads as its project's page", PO(project="projects/beta", project_id=A) == "projects/beta" and PO(project=PL, project_id=PL) == PL and PO(project_id=A) == "projects/alpha", None)
check("12 …an item filed on a former key reads as the project's page now, with its id and without it", PO(project="projects/old-gamma", project_id=G) == "projects/gamma" and PO(project="projects/old-gamma") == "projects/gamma"
      and IP.project_of(server._load("g25")["metadata"]) == "projects/gamma", (PO(project="projects/old-gamma", project_id=G), PO(project="projects/old-gamma")))
d12 = record(); d12["projects"][G]["page"] = "projects/gamma2"; d12["projects"][G]["former_keys"] = ["projects/old-gamma", "projects/gamma"]; write_record(d12)
check("12 …and follows the page when the record moves it again (a renamed project), the stored item too", PO(project="projects/old-gamma", project_id=G) == "projects/gamma2" and PO(project="projects/old-gamma") == "projects/gamma2"
      and IP.project_of(server._load("g25")["metadata"]) == "projects/gamma2", (PO(project="projects/old-gamma"), IP.project_of(server._load("g25")["metadata"])))
write_record(REC12)
check("12 line_of: the top-level key and `(filed on <page>)` for an item on a sub-page or a hub page; the stored value as it was for any other; a project alone is its key",
      IP.line_of({"project": "projects/alpha/sub"}) == "projects/alpha (filed on projects/alpha/sub)" and IP.line_of({"project": "ops/alpha-tool"}) == "projects/alpha (filed on ops/alpha-tool)"
      and IP.line_of({"project": "projects/alpha"}) == "projects/alpha" and IP.line_of({"project": "projects/nowhere"}) == "projects/nowhere" and IP.line_of({"project_id": A}) == "projects/alpha"
      and IP.line_of({}) == "" and IP.line_of(None) == "", IP.line_of({"project": "projects/alpha/sub"}))
check("12 …line_of never prints a false `filed on`: a former key with no id, a former key with its id, a legacy bare slug and an id that moved the page read as the project alone or as stored; a sub-page's id still gives the page it is filed on",
      IP.line_of({"project": "projects/old-gamma"}) == "projects/gamma" and IP.line_of({"project": "projects/old-gamma", "project_id": G}) == "projects/gamma" and IP.line_of({"project": "alpha"}) == "projects/alpha"
      and IP.line_of({"project": "projects/old-alpha", "project_id": A}) == "projects/alpha" and IP.line_of({"project": "projects/alpha/sub", "project_id": A}) == "projects/alpha (filed on projects/alpha/sub)",
      [IP.line_of(m_) for m_ in ({"project": "projects/old-gamma"}, {"project": "projects/old-gamma", "project_id": G}, {"project": "alpha"}, {"project": "projects/old-alpha", "project_id": A})])
check("12 the same project from the key alone and from the whole metadata (with its id), for every fixture item", all(PO(project=mt(i)["project"]) == IP.project_of(mt(i)) for i in (20, 21, 22, 23, 24, 25)), [(i, PO(project=mt(i)["project"]), IP.project_of(mt(i))) for i in (20, 21, 22, 23, 24, 25)])

snap12 = snapshot()
with SP.frozen(now0):
    bd = {tag: mod.Board(str(T / "store")) for tag, mod in (("render.py", R1), ("ui/render.py", R2))}
    mds = {tag: b_.markdown() for tag, b_ in bd.items()}
    brief12, get20, get21 = server.stackshot_brief(), server.stackshot_get("g20"), server.stackshot_get("g21")
    page20, page21, page22 = (bd["ui/render.py"].item_html(f"g{i}") for i in (20, 21, 22))
def card(md, n):
    i = md.find(f"[home] item {n}**")
    if i < 0: return ""
    j = md.find('<a id="', i)
    return md[i: j if j > 0 else len(md)]
def pline(c):
    m_ = re.search(r"^- project: (.*)$", c, re.M)
    return m_.group(1) if m_ else None
def label(line):
    m_ = re.match(r"\[?`?([^\]`\s)]+)", line or "")
    return m_.group(1) if m_ else None
for tag in bd:
    L = {n: pline(card(mds[tag], n)) for n in (20, 21, 22, 23, 24)}
    check(f"12 {tag} board.md: a sub-page's item and a hub page's item show the top-level project; a top-level item, one on another project and one naming no project show their key",
          [label(L[n]) for n in (20, 21, 22, 23, 24)] == ["projects/alpha", "projects/alpha", "projects/alpha", "projects/beta", "projects/nowhere"], L)
    link = lambda n: (L[n] or "").split("](", 1)[1].rstrip(")") if "](" in (L[n] or "") else ""
    check(f"12 {tag} board.md: the link is the mirror of the page the item is filed on (the project's own page when the filed page has none), as it was for an item on the top page",
          link(20) == (bd[tag].proj_mirror("projects/alpha/sub") or bd[tag].proj_mirror("projects/alpha")) and link(22) == (bd[tag].proj_mirror("ops/alpha-tool") or bd[tag].proj_mirror("projects/alpha"))
          and link(21) == bd[tag].proj_mirror("projects/alpha"), (L, bd[tag].proj_mirror("projects/alpha/sub")))
check("12 get and brief: `project:` is the top-level key with `(filed on <page>)` for a sub-page or hub page; a top-level item's line is as it was",
      "\nproject: projects/alpha (filed on projects/alpha/sub)" in "\n" + get20 and "\nproject: projects/alpha\n" in "\n" + get21 + "\n"
      and "project: projects/alpha (filed on projects/alpha/sub)" in brief12 and "project: projects/alpha (filed on ops/alpha-tool)" in brief12 and "project: projects/beta\n" in brief12 + "\n", (get20[:300], get21[:300]))
dd = lambda h: (re.search(r"<dt>Project</dt><dd>(.*?)</dd>", h, re.S) or re.search("(x)", "x")).group(1)
lab_top = bd["ui/render.py"].proj_label("projects/alpha")
check("12 the item page's Project line names the top-level project and links the page the item is filed on; a top-level item's line is unchanged",
      f">{lab_top}</a>" in dd(page20) and 'projects/alpha/sub"' in dd(page20) and f">{lab_top}</a>" in dd(page22) and 'ops/alpha-tool"' in dd(page22)
      and f">{lab_top}</a>" in dd(page21) and 'projects/alpha"' in dd(page21) and "alpha/sub" not in re.sub(r"<[^>]*>", "", dd(page20)), (lab_top, dd(page20), dd(page21), dd(page22)))
it20, it22 = server._load("g20"), server._load("g22")
check("12 the readers that need the PAGE keep it: key_of, proj_key (both modules), anchors.project_of and the board row read the page the item is filed on",
      IP.key_of(it20["metadata"]) == "projects/alpha/sub" and R1.proj_key(it20) == "projects/alpha/sub" and R2.proj_key(it20) == "projects/alpha/sub" and ANC.project_of(it20) == "projects/alpha/sub"
      and R1.proj_key(it22) == "ops/alpha-tool" and R2.proj_key(it22) == "ops/alpha-tool" and ANC.project_of(it22) == "ops/alpha-tool"
      and R1.proj_top(it20) == "projects/alpha" and R2.proj_top(it20) == "projects/alpha" and R1.proj_top(it22) == "projects/alpha" and R2.proj_top(it22) == "projects/alpha"
      and bd["ui/render.py"].row_of(R2.proj_key(it20)) == "projects/alpha" and bd["ui/render.py"].row_of(R2.proj_key(it22)) == "projects/alpha",
      (ANC.project_of(it20), R2.proj_key(it22), R2.proj_top(it20)))
check("12 a read writes nothing: the files are as they were after the boards, the brief, the gets and the item pages", snapshot() == snap12, None)
with SP.frozen(now0):
    mds2 = {tag: mod.Board(str(T / "store")).markdown() for tag, mod in (("render.py", R1), ("ui/render.py", R2))}
check("12 …and a second render shows the same", mds2 == mds, None)
for i in (20, 21, 22, 23, 24, 25): (T / f"store/g/{i}.json").unlink(missing_ok=True)

print(f"ok: item project scenario, {len(ran)} checks" if not fails else f"FAILED: {len(fails)} of {len(ran)}")
sys.exit(1 if fails else 0)
