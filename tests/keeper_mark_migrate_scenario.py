"""Scenario test for the keeper-mark migration (stage 5 of the keeper as a mark on one agent): projects/keeper_mark.py — fixture data, no live store, no network, no server process (the page
store is the plain markdown folder of a temporary config, the record a file of it).

Covers, on crafted fixtures: a project with a builder (the mark goes on the builder), a -main agent only (on the -main agent), a one-session project (its name-line session is listed as its one front
agent, keeps its name and is marked), a project with background agents only (the name-line session loses its roles.json role: said, and `--apply` refuses until the session is named), a running old
name-line session (shown off the map), an archived project and an already marked one (untouched, byte for byte: the record's flag, and a page's own `keeper:` line), a project whose entry name serves
nothing once the mark replaced it (cleared) and one whose name is the prefix of its agents (kept), and a sub-page that keeps a stale name of its own (counted, never written). It checks that the dry run
writes nothing (every byte of the store, the pages and the state), that the summary carries the lines the pass promises, that `--apply` writes the record only and keeps an undo file that puts the
record back byte for byte, that a second apply is a no-op, that roles.json, the notice name, the stand-in and the keeper telling before and after match the design (the marked agent is the keeper,
no session loses a role but the one the fixture meant to), and the command line in a child process (a refusal exits 1, the accepted run exits 0).

    tests/run-suite keeper_mark_migrate        → exit 0 / 1"""
import hashlib, json, logging, os, pathlib, re, subprocess, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="keepermigrate-"); T = pathlib.Path(tmp)
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

# Neutral fixtures. forge: a split project with a builder and an old name line; loft: front agents only; lone-page: a one-session project; wing: background agents only (its name-line session is its only
# front session); old-one: archived; orchard: a mark in the record; ember: a mark on the page's own `keeper:` line; wren: an entry name that serves nothing; loft/own: a sub-page whose name line is the loft's old one.
page("projects/forge.md", "type: project\ntitle: Forge\ndisplay-name: team-forge\nagents:\n  team-forge-main: talks\n  team-forge-docs: keeps the docs\n  background:\n    team-forge-audit: reviews\n    team-forge-builder: builds and merges\nstatus: active")
page("projects/loft/own.md", "type: project\ntitle: Loft own\ndisplay-name: team-loft\nstatus: active")
page("projects/loft/other.md", "type: project\ntitle: Loft other\ndisplay-name: team-other\nstatus: active")
page("projects/loft/kept.md", "type: note\ntitle: Loft kept\nagent: team-loft-docs")
page("projects/forge/plain.md", "type: note\ntitle: Forge plain")
page("projects/loft.md", "type: project\ntitle: Loft\ndisplay-name: team-loft\nagents:\n  team-loft-main: talks\n  team-loft-docs: keeps the docs\nstatus: active")
page("projects/lone-page.md", "type: project\ntitle: Lone\ndisplay-name: lone-session\nstatus: active")
page("projects/lone-page/sub.md", "type: note\ntitle: Lone sub")
page("projects/wing.md", "type: project\ntitle: Wing\ndisplay-name: team-wing\nagents:\n  background:\n    team-wing-builder: builds and merges\nstatus: active")
page("projects/old-one.md", "type: project\ntitle: Old one\ndisplay-name: team-old\nagents:\n  team-old-main: talks\n  background:\n    team-old-builder: builds\nstatus: archived")
page("projects/orchard.md", "type: project\ntitle: Orchard\ndisplay-name: team-orchard\nagents:\n  team-orchard-main: talks\n  team-orchard-docs: keeps the docs\n  background:\n    team-orchard-builder: builds\nstatus: active")
page("projects/ember.md", "type: project\ntitle: Ember\ndisplay-name: team-ember\nkeeper: team-ember-docs\nagents:\n  team-ember-main: talks\n  team-ember-docs: keeps the docs\n  background:\n    team-ember-builder: builds\nstatus: active")
page("projects/wren.md", "type: project\ntitle: Wren\ndisplay-name: team-wren\nagents:\n  wren-main: talks\nstatus: active")

sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
REC = T / "store/project-record.json"
from stackshot.projects import pages as p; from stackshot.projects import projects as prj; from stackshot.projects import project_registry as pr; from stackshot.projects import keeper as kp
from stackshot.projects import keeper_mark as km; from stackshot.projects import project_restore as rs; from stackshot.projects import project_verbs as pv
from stackshot.anchors import anchors; from stackshot.router import router_live as rl; from stackshot.service import telling
from stackshot import cli
p.cmd_registry(quiet=True)
def reg(): return json.loads((T / "store/projects.json").read_text())["pages"]
ids = {k: e["id"] for k, e in reg().items()}
def agent(front, mandate, **kw): return {"front": front, "mandate_line": mandate, **kw}
def write_record(entries):
    d = json.loads(REC.read_text()) if REC.exists() else {}
    d.update({"projects": entries, "projects_schema": 1}); REC.write_text(json.dumps(d, indent=1) + "\n", encoding="utf-8"); pr._CACHE["sig"] = None
def entry(key, **kw): return {"page": key, "status": "active", **kw}
def R(): return prj.registry()
def C(r): return {k: v for k, v in (r or {}).items() if k != "live"}
def answers(key, rg):
    return {"notice": anchors.notice_name(key, rg), "stand_in": rl.stand_in(key, rg), "page_keeper": telling.page_keeper(key, rg)}
def tree(*roots):
    """Every file under the roots, as {path: sha256}: what the dry run must leave exactly as it was."""
    out = {}
    for r in roots:
        for q in sorted(pathlib.Path(r).rglob("*")):
            if q.is_file(): out[str(q)] = hashlib.sha256(q.read_bytes()).hexdigest()
    return out
def recbytes(): return REC.read_bytes()
def tool(*args):
    r = subprocess.run([sys.executable, f"{STACK}/stackshot/projects/keeper_mark.py", *args], capture_output=True, text=True, env=os.environ, cwd=str(T))
    return r.returncode, r.stdout, r.stderr

F, LO, LP, WI, OLD, ORC, EM, WR = (ids[f"projects/{k}"] for k in ("forge", "loft", "lone-page", "wing", "old-one", "orchard", "ember", "wren"))
ENTRIES = {
    F: entry("projects/forge", name="team-forge", agents={"team-forge-main": agent(True, "talks"), "team-forge-docs": agent(True, "keeps the docs"), "team-forge-audit": agent(False, "reviews"),
                                                         "team-forge-builder": agent(False, "builds and merges")}),
    LO: entry("projects/loft", name="team-loft", agents={"team-loft-main": agent(True, "talks"), "team-loft-docs": agent(True, "keeps the docs")}),
    LP: entry("projects/lone-page", name="lone-session"),
    WI: entry("projects/wing", name="team-wing", agents={"team-wing-builder": agent(False, "builds and merges")}),
    OLD: entry("projects/old-one", name="team-old", status="archived", agents={"team-old-main": agent(True, "talks"), "team-old-builder": agent(False, "builds")}),
    ORC: entry("projects/orchard", name="team-orchard", agents={"team-orchard-main": agent(True, "talks"), "team-orchard-docs": agent(True, "keeps the docs", keeper=True), "team-orchard-builder": agent(False, "builds")}),
    EM: entry("projects/ember", name="team-ember", agents={"team-ember-main": agent(True, "talks"), "team-ember-docs": agent(True, "keeps the docs"), "team-ember-builder": agent(False, "builds")}),
    WR: entry("projects/wren", name="team-wren", agents={"wren-main": agent(True, "talks")}),
}
write_record(ENTRIES)
ORIG = recbytes()
RUN = T / "undo-runs"
SPACE = [T / "store", T / "brain", T / "state", T / "fleet"]
rg0 = R(); roles0 = anchors.file_roles(rg0, set()); sess0 = anchors.session_roles(rg0, set())
A0 = {k: answers(k, rg0) for k in ("projects/forge", "projects/loft", "projects/lone-page", "projects/wing", "projects/orchard", "projects/ember", "projects/wren")}

# ---- 0. the unmarked starting point the pass is measured from
check("start: the keeper of a split project is derived (its builder), a -main-only one its -main agent, a one-session one its name line, a marked one its mark",
      all((rg0[k]["keeper_agent"], rg0[k]["keeper_source"]) == v for k, v in {"projects/forge": ("team-forge-builder", "derived"), "projects/loft": ("team-loft-main", "derived"),
          "projects/lone-page": ("lone-session", "legacy"), "projects/wing": ("team-wing-builder", "derived"), "projects/orchard": ("team-orchard-docs", "mark"),
          "projects/ember": ("team-ember-docs", "mark"), "projects/wren": ("wren-main", "derived")}.items()), {k: (rg0[k].get("keeper_agent"), rg0[k].get("keeper_source")) for k in rg0})
check("start: the name-line session of the project that lists only a background agent is its only front session (roles.json promotes it); a split project's name line is no front session",
      roles0["team-wing"]["role"] == "front" and roles0["team-forge"]["role"] == "keeper", (roles0.get("team-wing"), roles0.get("team-forge")))

# ---- 1. the dry run: the default, writes nothing at all
before = tree(*SPACE)
dry = km.run(live={"team-forge", "lone-session"}, now="2026-11-01T00:00:00Z", run_dir=RUN)
check("dry run: not a byte of the store, the pages, the state or the fleet dir changes, and no undo file is made", tree(*SPACE) == before and not RUN.exists() and recbytes() == ORIG)
check("dry run: written is False, nothing refused, no undo", dry["dry"] is True and dry["written"] is False and dry["refused"] == "" and dry["undo"] is None, {k: dry[k] for k in ("dry", "written", "refused", "undo")})
c = dry["counts"]
check("dry run counts: two on a builder (forge, wing), two on a -main agent (loft, wren), one one-session promotion, two marked already, one archived, one name cleared",
      (c["builder"], c["main"], c["promote"], c["marked"], c["archived"], c["skip"], c["names_cleared"], c["changed"]) == (2, 2, 1, 2, 1, 0, 1, 5), c)
by = {r["key"]: r for r in dry["projects"]}
check("dry run: each project says the agent marked and why",
      (by["projects/forge"]["agent"], by["projects/forge"]["kind"]) == ("team-forge-builder", "builder") and (by["projects/wing"]["agent"], by["projects/wing"]["kind"]) == ("team-wing-builder", "builder")
      and (by["projects/loft"]["agent"], by["projects/loft"]["kind"]) == ("team-loft-main", "main") and (by["projects/wren"]["agent"], by["projects/wren"]["kind"]) == ("wren-main", "main")
      and (by["projects/lone-page"]["agent"], by["projects/lone-page"]["kind"]) == ("lone-session", "one-session")
      and by["projects/orchard"]["action"] == "marked" and by["projects/ember"]["action"] == "marked" and by["projects/old-one"]["action"] == "archived" and all(r["why"] for r in dry["projects"]), by)
check("dry run: the name cleared is wren's (it is no agent and no prefix of one) and no other; the forge keeps team-forge (its agents start with it), loft too",
      [r["key"] for r in dry["projects"] if r["cleared"]] == ["projects/wren"] and by["projects/wren"]["cleared"] == "team-wren", [(r["key"], r["cleared"]) for r in dry["projects"]])
text = "\n".join(dry["lines"])
for need in ("sessions that lose a role: 1 (team-wing)", "running old name-line sessions that would show off the map: 1 (team-forge)", "projects whose gating class flips: 1",
             "marked non-builders that get held notices later: 3", "nothing written (add --apply)"):
    check(f"dry run summary says: {need}", need in text, text)
check("dry run summary lists the roles.json entry that moves and says sala stops counting it", "roles.json: team-wing: front" in text and "load_roles stops counting it" in text, text)
check("dry run summary names the marks per project", "projects/forge: mark team-forge-builder (builder" in text and "projects/lone-page: mark lone-session (one-session" in text and "name team-wren cleared" in text, text)
check("the one-session promotion is the gating flip (one-session -> front agents), the only one", [(g["key"], g["from"], g["to"]) for g in dry["effects"]["gating"]] == [("projects/lone-page", "one-session", "front agents")], dry["effects"]["gating"])
check("the marked non-builders are loft, wren and the promoted session", sorted((x["key"], x["agent"]) for x in dry["effects"]["non_builders"]) ==
      [("projects/loft", "team-loft-main"), ("projects/lone-page", "lone-session"), ("projects/wren", "wren-main")], dry["effects"]["non_builders"])
check("a mark never moves a notice: every derived keeper is the agent marked, so no split project's notices change hands (only the one-session project's, which hear as a front agent now)",
      dry["effects"]["derived_moved"] == [], dry["effects"]["derived_moved"])
check("the sub-page whose own line names the project's old name line is counted and listed; one that names another session, and one an `agent:` line keeps, are not; none is written", dry["sub_pages"]["count"] == 1 and dry["sub_pages"]["keys"] == ["projects/loft/own"], dry["sub_pages"])
check("with no sala to read (live None), every old name-line session counts as running, and the summary says so",
      "sala could not be read" in "\n".join(km.run(live=None, run_dir=RUN)["lines"]) and tree(*SPACE) == before, None)

# ---- 2. --apply refuses while a session loses a role, and writes nothing
refused = km.run(apply_=True, live={"team-forge"}, run_dir=RUN)
check("apply without naming the session: refused, record and pages untouched, no undo file", refused["refused"].startswith("refused: 1 session(s) would lose a role: team-wing") and refused["written"] is False
      and tree(*SPACE) == before and not RUN.exists(), refused["refused"])
wrong = km.run(apply_=True, accept=("team-forge",), live={"team-forge"}, run_dir=RUN)
check("apply naming another session: still refused", bool(wrong["refused"]) and wrong["written"] is False and recbytes() == ORIG, wrong["refused"])

# ---- 3. --apply with the session named: the record only
brain_before = tree(BRAIN)
ok = km.run(apply_=True, accept=("team-wing",), live={"team-forge"}, run_dir=RUN, now="2026-11-01T00:00:00Z")
check("apply: written, an undo file named, nothing refused", ok["written"] is True and ok["refused"] == "" and ok["undo"] and pathlib.Path(ok["undo"]).is_file() and any("to undo: project.py restore --undo" in l for l in ok["lines"]), ok["lines"][-3:])
check("apply writes the record only: the pages are byte for byte as they were", tree(BRAIN) == brain_before)
new = json.loads(REC.read_text())["projects"]
def flagged(pid): return [n for n, a in (new[pid].get("agents") or {}).items() if a.get("keeper") is True]
check("apply: exactly one flag on each project that had none, on the agent the dry run said", flagged(F) == ["team-forge-builder"] and flagged(LO) == ["team-loft-main"] and flagged(WI) == ["team-wing-builder"]
      and flagged(WR) == ["wren-main"] and flagged(LP) == ["lone-session"], {k: flagged(k) for k in new})
check("apply: the one-session project's session is listed as its one front agent, keeps its name, and is marked; the entry names a mandate and who and when",
      new[LP]["name"] == "lone-session" and list(new[LP]["agents"]) == ["lone-session"] and new[LP]["agents"]["lone-session"]["front"] is True and new[LP]["agents"]["lone-session"]["mandate_line"]
      and new[LP]["agents"]["lone-session"]["by"] == "keeper-mark" and new[LP]["agents"]["lone-session"]["at"] == "2026-11-01T00:00:00Z", new[LP])
check("apply: an archived project, a project marked in the record and one marked by its page are left alone, entry for entry",
      new[OLD] == ENTRIES[OLD] and new[ORC] == ENTRIES[ORC] and new[EM] == ENTRIES[EM], (new[OLD], new[ORC], new[EM]))
check("apply: the name that served nothing is cleared, and only after its project was marked; the names that are agents' prefixes stay",
      "name" not in new[WR] and flagged(WR) and new[F]["name"] == "team-forge" and new[LO]["name"] == "team-loft" and new[WI]["name"] == "team-wing", {k: v.get("name") for k, v in new.items()})
def rest(e): return {k: v for k, v in e.items() if k not in ("agents", "name")}
def lines_of(e): return {n: {k: v for k, v in a.items() if k != "keeper"} for n, a in (e.get("agents") or {}).items()}
check("apply: nothing else of an entry changes (title, page, status, the agents' order, names and mandates, apart from the flag, the one promoted entry and the cleared name)",
      all(rest(new[k_]) == rest(ENTRIES[k_]) for k_ in ENTRIES) and all(list(lines_of(new[k_])) == list(lines_of(ENTRIES[k_])) and lines_of(new[k_]) == lines_of(ENTRIES[k_]) for k_ in ENTRIES if k_ != LP), None)

# ---- 4. roles.json, the notice name, the stand-in and the keeper telling after, against the design
rg1 = R(); roles1 = anchors.file_roles(rg1, set()); sess1 = anchors.session_roles(rg1, set())
A1 = {k: answers(k, rg1) for k in A0}
MARKED = {"projects/forge": "team-forge-builder", "projects/loft": "team-loft-main", "projects/lone-page": "lone-session", "projects/wing": "team-wing-builder", "projects/orchard": "team-orchard-docs",
          "projects/ember": "team-ember-docs", "projects/wren": "wren-main"}
check("after: the marked agent is the keeper of every project (the registry's keeper_agent, source mark)", all((rg1[k]["keeper_agent"], rg1[k]["keeper_source"]) == (a, "mark") for k, a in MARKED.items()),
      {k: (rg1[k].get("keeper_agent"), rg1[k].get("keeper_source")) for k in MARKED})
check("after: notice name, stand-in and the keeper telling answer are the marked agent for each project", all(A1[k] == {"notice": a, "stand_in": a, "page_keeper": a} for k, a in MARKED.items()), A1)
check("after: no project with a front agent changes its stand-in or its keeper telling answer (the mark is what they derived); the notice address was the old name line and is the mark now",
      all(A1[k]["stand_in"] == A0[k]["stand_in"] and A1[k]["page_keeper"] == A0[k]["page_keeper"] for k in ("projects/forge", "projects/loft", "projects/wren", "projects/orchard", "projects/ember"))
      and [A0[k]["notice"] for k in ("projects/forge", "projects/loft", "projects/wren")] == ["team-forge", "team-loft", "team-wren"], (A0, A1))
check("after: the back-only project's item keeper moves from its name-line session to its builder, and the one-session project gets a stand-in (its session): both said in the summary, no other project moves",
      (A0["projects/wing"]["page_keeper"], A1["projects/wing"]["page_keeper"]) == ("team-wing", "team-wing-builder") and (A0["projects/lone-page"]["stand_in"], A1["projects/lone-page"]["stand_in"]) == ("", "lone-session")
      and sorted(x["key"] for x in dry["effects"]["notices"] if x["hands"]) == ["projects/lone-page", "projects/wing"]
      and sorted(x["key"] for x in dry["effects"]["notices"]) == ["projects/forge", "projects/loft", "projects/lone-page", "projects/wing", "projects/wren"], dry["effects"]["notices"])
check("after: the marked agent carries the keeper flag in roles.json, with the role it had; the old name lines are no session of roles.json",
      all(roles1[a].get("keeper") is True for a in MARKED.values()) and roles1["team-forge-builder"]["role"] == "back" and roles1["team-loft-main"]["role"] == "front" and roles1["lone-session"]["role"] == "front"
      and "team-forge" not in roles1 and "team-wren" not in roles1, {a: roles1.get(a) for a in list(MARKED.values()) + ["team-forge", "team-loft"]})
sala = lambda r: (r["role"], r["project"]) if r and r.get("role") in ("front", "back") and not r.get("retired") else None
lost = sorted(n for n in roles0 if sala(roles0[n]) and not sala(roles1.get(n)))
moved = sorted(n for n in set(roles0) | set(roles1) if sala(roles0.get(n)) != sala(roles1.get(n)))
check("after: the only session that loses a role is the one the fixture meant to (the back-only project's name-line session), and nothing else changes in what sala counts", lost == ["team-wing"] and moved == ["team-wing"], (lost, moved))
check("the tool said the same: sessions that lose a role = the ones read back from roles.json before and after", dry["effects"]["lose"] == lost and [x["session"] for x in dry["effects"]["roles"] if x["lane_changes"]] == moved, (dry["effects"]["lose"], lost))
check("the sessions that keep their entry keep it as it was (front stays front, back stays back, project stays)",
      all(C(roles1[n]).get("role") == C(roles0[n]).get("role") and C(roles1[n]).get("project") == C(roles0[n]).get("project") for n in roles0 if n in roles1 and sala(roles0[n])), None)
check("after: the running old name-line session (team-forge) is off the map, as the summary said", anchors.session_hubs("team-forge", rg0, {}) == ["projects/forge"] and anchors.session_hubs("team-forge", rg1, {}) == []
      and [x["session"] for x in dry["effects"]["off_map"]] == ["team-forge"], (anchors.session_hubs("team-forge", rg1, {}), dry["effects"]["off_map"]))

# ---- 5. a second apply is a no-op
mid = tree(*SPACE); undo_dirs = sorted(RUN.iterdir())
again = km.run(apply_=True, accept=("team-wing",), live={"team-forge"}, run_dir=RUN)
check("a second apply writes nothing: the record, the pages and the state are as they were, no second undo file, and it says there is nothing to change",
      again["written"] is False and again["refused"] == "" and tree(*SPACE) == mid and sorted(RUN.iterdir()) == undo_dirs and again["counts"]["changed"] == 0 and any("nothing to change" in l for l in again["lines"]), again["lines"][-3:])
check("a second dry run reports every live project as marked already, and nothing that would lose a role", km.run(live=set(), run_dir=RUN)["counts"]["marked"] == 7 and km.run(live=set(), run_dir=RUN)["effects"]["lose"] == [], None)

# ---- 6. the undo file puts the record back byte for byte (and the whole undo changes nothing else)
done = recbytes()
und = rs.restore_undo(ok["undo"], apply=False)
check("undo, dry run: says it would put the record back and writes nothing", recbytes() == done and und.get("changed") is True and "dry run" in "\n".join(und["lines"]), und)
und = rs.restore_undo(ok["undo"], apply=True)
check("undo --apply: the record is byte for byte what it was before the pass", recbytes() == ORIG and und.get("changed") is True, und)
check("... and the pass applies again on it with the same result (idempotent from the same start)", (lambda r: r["written"] and json.loads(REC.read_text())["projects"] == new)(km.run(apply_=True, accept=("team-wing",), live=set(), run_dir=RUN, now="2026-11-01T00:00:00Z")), None)
REC.write_bytes(ORIG); pr._CACHE["sig"] = None
d = json.loads(pathlib.Path(ok["undo"]).read_text())
check("the undo file is the project_restore format of a whole-record change (mode record, the file as it was kept whole, no per-project parts)", d["mode"] == "record" and d["project"] == "" and "prior" not in d and "restored" not in d
      and pathlib.Path(d["before"]).read_bytes() == ORIG and d["by"] == "keeper-mark", {k: d.get(k) for k in ("mode", "project", "by", "before")})

# ---- 7. the command line, in a child process
rc, out, err = tool()
check("cli, dry run: exit 0, the summary on stdout, nothing written", rc == 0 and "dry run: keeper marks on 8 project entries" in out and "sessions that lose a role: 1 (team-wing)" in out and recbytes() == ORIG, (rc, out[-400:], err[-300:]))
rc, out, err = tool("--apply", "--run-dir", str(T / "undo-cli"))
check("cli, --apply while a session would lose a role: exit 1, the refusal said, nothing written, no undo file", rc == 1 and "would lose a role: team-wing" in out and recbytes() == ORIG and not (T / "undo-cli").exists(), (rc, out[-400:], err[-300:]))
rc, out, err = tool("--apply", "--accept-role-loss", "team-wing", "--run-dir", str(T / "undo-cli"), "--json")
got = json.loads(out) if out.strip().startswith("{") else {}
check("cli, --apply --accept-role-loss team-wing: exit 0, written, an undo file", rc == 0 and got.get("written") is True and pathlib.Path(got.get("undo") or "/nope").is_file() and recbytes() != ORIG, (rc, out[-300:], err[-300:]))
rc, out, err = tool("--apply", "--accept-role-loss", "team-wing", "--run-dir", str(T / "undo-cli"))
check("cli, a second --apply: exit 0, nothing to change", rc == 0 and "nothing to change" in out, (rc, out[-300:]))
check("cli: the program is listed (`stackshot keeper-mark`)", "keeper-mark" in cli.PROGRAMS and cli.PROGRAMS["keeper-mark"][0] == "stackshot.projects.keeper_mark", None)

# ---- 8. a project whose page cannot take the mark is skipped and said, never half-written
write_record({**ENTRIES, LP: entry("projects/lone-page", name="cse_abc")})
r = km.run(live=set(), run_dir=RUN)
check("a one-session project whose name line is a session id is skipped with the reason, not promoted", {x["key"]: x["action"] for x in r["projects"]}["projects/lone-page"] == "skip" and "list its session by hand" in "\n".join(r["lines"]), r["lines"])

# ---- 9. the printed undo hint says what the undo is and is not
hint = " ".join(l for l in ok["lines"] if l.startswith("to undo:"))
check("the undo hint says the undo puts the whole file back, is refused (409) after a later record write, and names `restore --from-git` as the way after one",
      "restore --undo" in hint and "whole record file" in hint and "409" in hint and "later write" in hint and "restore --from-git" in hint, hint)

# ---- 10. new pages for the fixtures below (their projects live in memory only: the record on disk is not touched by sections 10 to 13)
page("projects/twin-a.md", "type: project\ntitle: Twin a\nstatus: active")
page("projects/twin-b.md", "type: project\ntitle: Twin b\nstatus: active")
page("projects/twin-c.md", "type: project\ntitle: Twin c\nstatus: active")
page("projects/held.md", "type: project\ntitle: Held\ndisplay-name: team-held\nagents:\n  lone-held: talks\nstatus: active")
page("projects/emptied.md", "type: project\ntitle: Emptied\ndisplay-name: team-emptied\nstatus: active")
page("projects/emptied2.md", "type: project\ntitle: Emptied two\ndisplay-name: team-emptied2\nstatus: active")
page("projects/marsh.md", "type: project\ntitle: Marsh\ndisplay-name: team-marsh\nagents:\n  marsh-main: talks\nstatus: active")
page("projects/marsh/notes.md", "type: note\ntitle: Marsh notes")
page("projects/dune.md", "type: project\ntitle: Dune\ndisplay-name: lone-dune\nstatus: active")
page("projects/dune/own.md", "type: project\ntitle: Dune own\ndisplay-name: lone-dune\nstatus: active")
p.cmd_registry(quiet=True)
ids9 = {k: e["id"] for k, e in reg().items()}; raw9 = prj.registry_raw()
TA, TB, TC, HE, EM1, EM2, MA, DU = (ids9[f"projects/{k}"] for k in ("twin-a", "twin-b", "twin-c", "held", "emptied", "emptied2", "marsh", "dune"))
NOW9 = "2026-11-01T00:00:00Z"

# one-session names that collide: one promotion, the other refused
_, rows9 = km.build({TA: entry("projects/twin-a", name="lone-twin"), TB: entry("projects/twin-b", name="lone-twin")}, raw9, now=NOW9)
act = {r["key"]: r for r in rows9}
check("two one-session projects with the same name: the first (by page key) is promoted, the second is skipped with the reason that another project has the agent already",
      act["projects/twin-a"]["action"] == "promote" and act["projects/twin-b"]["action"] == "skip" and "an agent of another project already" in act["projects/twin-b"]["why"], rows9)
new9, rows9 = km.build({TA: entry("projects/twin-a", name="lone-twin"), TB: entry("projects/twin-b", name="LONE-TWIN"), TC: entry("projects/twin-c", name="lone-twin")}, raw9, now=NOW9)
check("... three of them, one of the names in another case: still one promotion, and only one entry lists the session",
      sum(1 for r in rows9 if r["action"] == "promote") == 1 and sum(1 for e in new9.values() if any(str(n).casefold() == "lone-twin" for n in (e.get("agents") or {}))) == 1, rows9)
# a name an agent of another project has through that project's page (an entry with no agents field reads the page's map)
_, rows9 = km.build({HE: entry("projects/held"), TC: entry("projects/twin-c", name="lone-held")}, raw9, now=NOW9)
act = {r["key"]: r for r in rows9}
check("a one-session name that an agent listed only on another project's page already has is refused (the names taken are read from the effective lists, not only the record's)",
      act["projects/held"]["action"] == "mark" and act["projects/held"]["agent"] == "lone-held" and act["projects/twin-c"]["action"] == "skip" and "an agent of another project already" in act["projects/twin-c"]["why"], rows9)

# ---- 11. an entry that had agents (an empty map, or every agent retired) is not a one-session project: its name is the project's name
new9, rows9 = km.build({EM1: entry("projects/emptied", name="team-emptied", agents={}, former_agents=["team-emptied-main"]), EM2: entry("projects/emptied2", name="team-emptied2", former_agents=["team-emptied2-main"])}, raw9, now=NOW9)
act = {r["key"]: r for r in rows9}
check("an entry with an empty agents map (all retired), or with only former agents, and a name that is a prefix of them: skipped with a reason line, nothing promoted, the entry unchanged",
      all(act[k]["action"] == "skip" and "list the session by hand" in act[k]["why"] and "had some" in act[k]["why"] for k in ("projects/emptied", "projects/emptied2"))
      and new9[EM1] == entry("projects/emptied", name="team-emptied", agents={}, former_agents=["team-emptied-main"]), rows9)
check("... and the summary prints the skip", any("projects/emptied: skipped" in l for l in km._lines(km.summarize({EM1: entry("projects/emptied", name="team-emptied", agents={}, former_agents=["x"])}, raw9, live=set(), now=NOW9), True, set())), None)

# ---- 12. name clearing: a sub-page that only the page registry has counts; a promoted project's own session on a sub-page is no stale line
new9, rows9 = km.build({MA: entry("projects/marsh", name="team-marsh", agents={"marsh-main": agent(True, "talks")})}, raw9, now=NOW9)
check("a name that serves nothing is kept while a page of the registry that has no entry of its own hangs below the project (a sub-page may use it)",
      rows9[0]["cleared"] == "" and new9[MA].get("name") == "team-marsh", rows9)
new9, rows9 = km.build({MA: entry("projects/marsh", name="team-marsh", agents={"marsh-main": agent(True, "talks")})}, {k: v for k, v in raw9.items() if k != "projects/marsh/notes"}, now=NOW9)
check("... and cleared when nothing hangs below it (the same project without that sub-page in the registry)", rows9[0]["cleared"] == "team-marsh" and "name" not in new9[MA], rows9)
s9 = km.summarize({DU: entry("projects/dune", name="lone-dune")}, raw9, live=set(), now=NOW9)
check("a promoted one-session project's own session on its sub-page is no stale line (the session is an agent of the project now)", s9["counts"]["promote"] == 1 and s9["sub_pages"] == {"count": 0, "keys": []}, s9["sub_pages"])
s9 = km.summarize({DU: entry("projects/dune", name="lone-dune", agents={"dune-main": agent(True, "talks")})}, raw9, live=set(), now=NOW9)
check("... while a project marked on other agents still counts a sub-page that names its old session (unchanged)", s9["counts"]["mark"] == 1 and s9["sub_pages"]["keys"] == ["projects/dune/own"], s9["sub_pages"])

# ---- 13. the record changes between the plan and the write: what is printed and returned is the plan that was written
write_record(ENTRIES); ORIG13 = recbytes()
orig_plan = km.plan
def racing_plan(**kw):
    out = orig_plan(**kw)
    d = json.loads(REC.read_text()); d["projects"][F]["agents"]["team-forge-docs"]["keeper"] = True       # somebody marks the forge after the plan was read
    REC.write_text(json.dumps(d, indent=1) + "\n", encoding="utf-8"); pr._CACHE["sig"] = None
    return out
km.plan = racing_plan
try:
    rr13 = km.run(apply_=True, accept=("team-wing",), live=set(), run_dir=T / "undo-race", now=NOW9)
finally:
    km.plan = orig_plan
text13 = "\n".join(rr13["lines"]); rec13 = json.loads(REC.read_text())["projects"]
check("apply on a record that changed after the plan: written, and the forge is not marked a second time (the flag somebody put there stays the one)",
      rr13["written"] is True and [n for n, a in rec13[F]["agents"].items() if a.get("keeper") is True] == ["team-forge-docs"], rec13[F]["agents"])
check("... the printed lines and the returned counts are the plan that was written (4 changes, no line for the forge), not the one read before the lock (5)",
      rr13["counts"]["changed"] == 4 and "projects/forge: mark" not in text13 and "projects/wing: mark team-wing-builder" in text13 and "marked already" in text13, text13)
check("... and the output says the plan changed under it, and the result says so too", rr13["replanned"] is True and "the record changed between the plan and the write" in text13 and "5 changes" in text13, text13)
write_record(ENTRIES)
r13 = km.run(apply_=True, accept=("team-wing",), live=set(), run_dir=T / "undo-calm", now=NOW9)
check("an apply on a record nobody touched says nothing of the kind and is not marked replanned", r13["written"] is True and r13["replanned"] is False and "the record changed between" not in "\n".join(r13["lines"]), r13["lines"][-3:])
write_record(ENTRIES)
def racing_all(**kw):
    out = orig_plan(**kw); km.plan = orig_plan                                                                 # somebody applies the same pass after the plan was read
    km.run(apply_=True, accept=("team-wing",), live=set(), run_dir=T / "undo-race2", now=NOW9)
    return out
km.plan = racing_all
try:
    z13 = km.run(apply_=True, accept=("team-wing",), live=set(), run_dir=T / "undo-race3", now=NOW9)
finally:
    km.plan = orig_plan
tz13 = "\n".join(z13["lines"])
check("an apply whose re-plan under the lock has nothing left to do says plainly that nothing needed writing, not `the plan that was written (0 changes)`",
      z13["written"] is False and z13["replanned"] is True and "nothing needed writing any more" in tz13 and "(0 changes)" not in tz13 and "nothing to change: nothing written" in tz13, tz13)

# ---- 14. the plan made under the record's lock decides the role-loss refusal, not the plan read before it
write_record(ENTRIES)
def resolving_plan(**kw):
    out = orig_plan(**kw); km.plan = orig_plan
    d = json.loads(REC.read_text()); d["projects"][WI]["agents"]["team-wing"] = agent(True, "the session")       # another writer lists the session that would lose its role as a front agent
    REC.write_text(json.dumps(d, indent=1) + "\n", encoding="utf-8"); pr._CACHE["sig"] = None
    return out
check("fixture: the plan read before the lock says team-wing would lose a role", orig_plan(live=set(), now=NOW9)["effects"]["lose"] == ["team-wing"])
km.plan = resolving_plan
try:
    r14 = km.run(apply_=True, accept=(), live=set(), run_dir=T / "undo-resolved", now=NOW9)
finally:
    km.plan = orig_plan
check("a role loss the plan before the lock saw and another writer resolved before it: the plan under the lock decides, so the apply is written, not refused",
      r14["refused"] == "" and r14["written"] is True and r14["effects"]["lose"] == [], (r14["refused"], r14["written"], r14["effects"]["lose"]))
check("... and what it wrote is marked on the wing's builder, with the session the other writer listed kept",
      json.loads(REC.read_text())["projects"][WI]["agents"]["team-wing-builder"].get("keeper") is True and "team-wing" in json.loads(REC.read_text())["projects"][WI]["agents"], json.loads(REC.read_text())["projects"][WI]["agents"])
write_record({**ENTRIES, WI: entry("projects/wing", name="team-wing", agents={"team-wing": agent(True, "the session"), "team-wing-builder": agent(False, "builds and merges")})})
check("fixture: with the session listed as a front agent the plan before the lock loses no role", orig_plan(live=set(), now=NOW9)["effects"]["lose"] == [])
def losing_plan(**kw):
    out = orig_plan(**kw); km.plan = orig_plan
    d = json.loads(REC.read_text()); d["projects"][WI]["agents"].pop("team-wing")                              # another writer takes the session off the list after the plan was read
    REC.write_text(json.dumps(d, indent=1) + "\n", encoding="utf-8"); pr._CACHE["sig"] = None
    return out
km.plan = losing_plan
try:
    r14b = km.run(apply_=True, accept=(), live=set(), run_dir=T / "undo-lost", now=NOW9)
    left14 = recbytes()
finally:
    km.plan = orig_plan
check("a role loss that appears only under the lock is refused, nothing written, and no undo file", r14b["refused"].startswith("refused: 1 session(s) would lose a role: team-wing") and "nothing was written" in r14b["refused"]
      and r14b["written"] is False and not (T / "undo-lost").exists() and "team-wing" not in json.loads(left14)["projects"][WI]["agents"] and not any(a.get("keeper") for a in json.loads(left14)["projects"][WI]["agents"].values()), (r14b["refused"], r14b["written"]))
check("... and it is accepted when the session is named", (lambda r: r["written"] is True and r["refused"] == "")(km.run(apply_=True, accept=("team-wing",), live=set(), run_dir=T / "undo-accepted", now=NOW9)), None)

# ---- 15. a record entry with no page (or no usable key) is never promoted, marked or cleared
write_record(ENTRIES)
raw15 = prj.registry_raw()
none15 = {"x1": {"name": "lone-nopage", "status": "active"}, "x2": {"name": "team-nopage", "status": "active", "page": "", "agents": {"team-nopage-main": agent(True, "talks")}},
          "x3": {"name": "team-link", "status": "active", "page": "https://example.invalid/team-link", "agents": {"team-link-builder": agent(False, "builds")}}, "x4": {"name": "lone-blank", "status": "active", "page": "  /  "}}
new15, rows15 = km.build(none15, raw15, now=NOW9)
check("entries with no page, an empty pointer, a pointer to another knowledge base and a blank pointer are skipped with the reason, and not one is changed",
      all(r["action"] == "skip" and "no page row" in r["why"] for r in rows15) and new15 == none15 and len(rows15) == 4, rows15)
raw15b = {**raw15, "": {"session": "lone-nopage", "role": "name", "agents": {}}}
new15, rows15 = km.build(none15, raw15b, now=NOW9)
check("... also when the registry has a row filed under the empty key (an empty key matches no page)", all(r["action"] == "skip" for r in rows15) and new15 == none15, rows15)
s15 = km.summarize({**{k: v for k, v in ENTRIES.items() if k == WR}, **none15}, raw15, live=set(), now=NOW9)
check("a pageless entry beside a real one changes nothing of the real one's plan: it is marked, its name cleared, and the pageless ones count as skipped",
      s15["counts"]["skip"] == 4 and s15["counts"]["mark"] == 1 and s15["counts"]["names_cleared"] == 1, s15["counts"])

if fails: print(f"FAILED: keeper mark migrate scenario, {len(ran)} checks, {len(fails)} failed"); sys.exit(1)
print(f"ok: keeper mark migrate scenario, {len(ran)} checks")
