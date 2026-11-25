"""Scenario test for the keeper of a sub-page a split made (a `split_from: <page>` line, or a `parent: <page>` line, and no `agent:` line, name line, mark or agents of its own) — fixture data, no live
store, no network, no server process (a temporary config; the page store is a plain markdown folder, the record a file of it).

Covers: a split of a hub that is itself a sub-page with a mark of its own (a hub the registry's rule for the page above never passes down), of a hub an `agent:` line keeps, of a hub the project's mark keeps, and
of a hub in another project (`parent:`); a chain of two splits and the bound on a chain (SPLIT_HOPS); a loop, a page that names itself, and a line that names no page (each reads as no line: the answer of
the page above); a page that has its own mark, name line, `agent:` line or agents keeps them; a retired project (only a mark is followed there); a target that has no keeper; the source `split`, which the
legacy gauge does not count; the pages a mark moves reading their keeper again (a mark laid on a sub-page, a project mark added); the line as the page row records it (`pages.split_line`); and that every
reader of `session` and `role` (name_line, session_hubs, notice_name, the stand-in, the page keeper, the sessions that keep a page) and the keeper-subpages dry run answer as they do for the same pages with
no split line; the pages under a page that follows another (a child and a grandchild with no line of their own, and a split of such a page) reading the target's keeper again whenever its mark is laid, moves or goes
and whenever the project's mark moves, with the published value of every row equal to a fresh read of the same registry; the readers of the old forms not counting a row that follows another page; and the hand-back
of an `agent:` page that has a split line.

    tests/run-suite keeper_split        → exit 0 / 1"""
import contextlib, io, json, logging, os, pathlib, re, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="keepersplit-"); T = pathlib.Path(tmp)
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
SPLIT_LINES = {}          # page key -> the lines of its frontmatter that name a split source (so the same fixtures can be written without them)

def make(with_lines=True):
    """Write every fixture page; `with_lines=False` writes the same pages without their split lines."""
    def pg(rel, front, split=""):
        SPLIT_LINES[rel[:-3]] = split
        q = BRAIN / rel; q.parent.mkdir(parents=True, exist_ok=True)
        q.write_text("---\n" + front + ("\n" + split if split and with_lines else "") + "\n---\n\n# x\n", encoding="utf-8")
    # forge: a project whose record marks its builder. Its hubs: hub-mark (a sub-page with a mark of its own, laid by the record), hub-agent (kept by an `agent:` line), hub-plain (names nobody: it follows the project's mark).
    pg("projects/forge.md", "type: project\ntitle: Forge\nagents:\n  forge-main: talks\n  background:\n    forge-builder: builds and merges\nstatus: active")
    pg("projects/forge/hub-mark.md", "type: note\ntitle: Hub mark")
    pg("projects/forge/hub-mark/part1.md", "type: note\ntitle: Part one", "split_from: projects/forge/hub-mark")
    pg("projects/forge/hub-agent.md", "type: note\ntitle: Hub agent\nagent: loft-main")
    pg("projects/forge/hub-agent/part1.md", "type: note\ntitle: Part one", "split_from: projects/forge/hub-agent")
    pg("projects/forge/hub-agent/part1/part2.md", "type: note\ntitle: Part two", "split_from: projects/forge/hub-agent/part1")
    pg("projects/forge/hub-plain.md", "type: note\ntitle: Hub plain")
    pg("projects/forge/hub-plain/part1.md", "type: note\ntitle: Part one", "split_from: projects/forge/hub-plain")
    pg("projects/forge/via-parent.md", "type: note\ntitle: Via parent", "parent: projects/loft/docs")
    pg("projects/forge/with-suffix.md", "type: note\ntitle: With suffix", "split_from: 'projects/forge/hub-agent.md'")
    pg("projects/forge/both.md", "type: note\ntitle: Both", "split_from: projects/forge/hub-agent\nparent: projects/forge/hub-mark")
    # a line that cannot be followed reads as no line
    pg("projects/forge/cyc-a.md", "type: note\ntitle: Cycle a", "split_from: projects/forge/cyc-b")
    pg("projects/forge/cyc-b.md", "type: note\ntitle: Cycle b", "split_from: projects/forge/cyc-a")
    pg("projects/forge/self.md", "type: note\ntitle: Self", "split_from: projects/forge/self")
    pg("projects/plain-note.md", "type: note\ntitle: A note that nobody keeps")
    pg("projects/forge/to-plain.md", "type: note\ntitle: To plain", "split_from: projects/plain-note")
    pg("projects/forge/miss.md", "type: note\ntitle: Missing", "split_from: projects/forge/nowhere")
    pg("projects/forge/bare.md", "type: note\ntitle: Bare slug", "split_from: nowhere-at-all")
    # a chain of ten splits of splits: c0 is the hub (an `agent:` line), c1..c9 each follow the one before
    pg("projects/forge/c0.md", "type: note\ntitle: c0\nagent: loft-main")
    for i in range(1, 10):
        pg(f"projects/forge/c{i}.md", f"type: note\ntitle: c{i}", f"split_from: projects/forge/c{i - 1}")
    # a page with a keeper of its own keeps it, the line or not
    pg("projects/forge/own-name.md", "type: note\ntitle: Own name\ndisplay-name: team-own", "split_from: projects/forge/hub-agent")
    pg("projects/forge/own-agent.md", "type: note\ntitle: Own agent\nagent: forge-main", "split_from: projects/forge/hub-agent")
    pg("projects/forge/own-mark.md", "type: note\ntitle: Own mark", "split_from: projects/forge/hub-agent")
    pg("projects/forge/own-agents.md", "type: note\ntitle: Own agents\nagents:\n  forge-extra: a page that lists its own agent", "split_from: projects/forge/hub-agent")
    # loft: front agents, no builder; loft/docs is kept by an `agent:` line, loft/hubless names nobody. other: a one-session project with no record entry, whose page follows loft/hubless
    pg("projects/loft.md", "type: project\ntitle: Loft\nagents:\n  loft-main: talks\n  loft-docs: keeps the docs\nstatus: active")
    pg("projects/loft/docs.md", "type: note\ntitle: Loft docs\nagent: forge-main")
    pg("projects/loft/hubless.md", "type: note\ntitle: Loft hubless")
    pg("projects/other.md", "type: project\ntitle: Other\ndisplay-name: other-session\nstatus: active")
    pg("projects/other/child.md", "type: note\ntitle: Other child", "split_from: projects/loft/hubless")
    pg("projects/other/plain.md", "type: note\ntitle: Other plain")
    # old-one: archived. kid follows a page that has no keeper there; kid2 follows a marked page of forge; kid3 follows a page kept by an `agent:` line (an old form: not followed in a retired project)
    pg("projects/old-one.md", "type: project\ntitle: Old one\nagents:\n  old-one-main: talks\nstatus: archived")
    pg("projects/old-one/sub.md", "type: note\ntitle: Old sub\nagent: loft-main")
    pg("projects/old-one/kid.md", "type: note\ntitle: Kid", "split_from: projects/old-one/sub")
    pg("projects/old-one/kid2.md", "type: note\ntitle: Kid two", "split_from: projects/forge/hub-mark")
    pg("projects/old-one/kid3.md", "type: note\ntitle: Kid three", "split_from: projects/loft/docs")

make()
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
REC = T / "store/project-record.json"
from stackshot.projects import pages as p; from stackshot.projects import projects as prj; from stackshot.projects import project_registry as pr; from stackshot.projects import keeper as kp
from stackshot.projects import keeper_subpages as ks; from stackshot.projects import keeper_reads as KR; from stackshot.projects import project_verbs as pv
from stackshot.anchors import anchors; from stackshot.router import router_live as rl; from stackshot.service import telling
p.cmd_registry(quiet=True)
def raw(): return json.loads((T / "store/projects.json").read_text())["pages"]
ids = {k: e["id"] for k, e in raw().items()}
def agent(front, mandate, **kw): return {"front": front, "mandate_line": mandate, **kw}
def write_record(entries):
    d = json.loads(REC.read_text()) if REC.exists() else {}
    d.update({"projects": entries, "projects_schema": 1}); REC.write_text(json.dumps(d, indent=1) + "\n", encoding="utf-8"); pr._CACHE["sig"] = None
def entry(key, **kw): return {"page": key, "status": "active", **kw}
def R(): return prj.registry()
def ks_of(rg, k): return (rg[k].get("keeper_agent", ""), rg[k].get("keeper_source", ""))
def legacy(rg): return sorted(k for k, v in rg.items() if isinstance(v, dict) and v.get("keeper_source") == "legacy")

F, LO, OLD = (ids[f"projects/{k}"] for k in ("forge", "loft", "old-one"))
FORGE = entry("projects/forge", agents={"forge-main": agent(True, "talks"), "forge-builder": agent(False, "builds and merges", keeper=True)},
              page_keepers={"projects/forge/hub-mark": "loft-docs", "projects/forge/own-mark": "forge-builder"})
LOFT = entry("projects/loft", agents={"loft-main": agent(True, "talks"), "loft-docs": agent(True, "keeps the docs")})
OLDE = entry("projects/old-one", status="archived", agents={"old-one-main": agent(True, "talks")})
write_record({F: FORGE, LO: LOFT, OLD: OLDE})
rg = R()
FB, LM, LD, FM = "forge-builder", "loft-main", "loft-docs", "forge-main"
def agrees(rg_, label):
    """The published record of every row of `rg_` says what keeper.fields says of the same registry (a refresh that missed a row shows here as a stale value)."""
    bad = []
    for rec in prj.build(rg_)["projects"].values():
        f = kp.fields(rec["key"], rg_); want = (f["keeper_agent"], f["keeper_source"])
        if (rec.get("keeper_agent", ""), rec.get("keeper_source", "")) != want or (rg_[rec["key"]].get("keeper_agent", ""), rg_[rec["key"]].get("keeper_source", "")) != want:
            bad.append((rec["key"], rec.get("keeper_agent"), rec.get("keeper_source"), f))
    check(f"published keeper equals a fresh read for every row ({len(rg_)} rows): {label}", not bad and len(rg_) > 8, bad[:4])
agrees(rg, "the base record")

# ---- 1. the line, as the page row records it
check("split_line: split_from wins over parent; a bare slug is a page of the first pages dir; quotes, slashes and `.md` are dropped; no line, an empty line and a list give none",
      p.split_line({"split_from": "projects/a/b", "parent": "projects/c"}) == "projects/a/b" and p.split_line({"parent": "projects/c"}) == "projects/c" and p.split_line({"split_from": "slug"}) == "projects/slug"
      and p.split_line({"split_from": "'/projects/a/b.md/'"}) == "projects/a/b" and p.split_line({}) == "" and p.split_line({"split_from": ""}) == "" and p.split_line({"split_from": ["projects/a"]}) == ""
      and p.split_line({"split_from": "  ", "parent": "projects/c"}) == "projects/c" and p.split_line(None) == "", None)
check("row: a page with the line carries it as `split_from`, normalized; a page with none has no such field",
      raw()["projects/forge/with-suffix"].get("split_from") == "projects/forge/hub-agent" and raw()["projects/forge/via-parent"].get("split_from") == "projects/loft/docs"
      and raw()["projects/forge/both"].get("split_from") == "projects/forge/hub-agent" and raw()["projects/forge/bare"].get("split_from") == "projects/nowhere-at-all"
      and not any("split_from" in raw()[k] for k in ("projects/forge", "projects/forge/hub-agent", "projects/forge/hub-plain", "projects/loft")), {k: v.get("split_from") for k, v in raw().items()})

# ---- 2. the split of each kind of hub
check("a split of a hub that has a mark of its own: the page reads the hub's mark (the page above it would give the project's)", ks_of(rg, "projects/forge/hub-mark") == (LD, "mark") and ks_of(rg, "projects/forge/hub-mark/part1") == (LD, "split"), (ks_of(rg, "projects/forge/hub-mark"), ks_of(rg, "projects/forge/hub-mark/part1")))
check("a split of a hub an `agent:` line keeps: the page reads that agent, source split", ks_of(rg, "projects/forge/hub-agent") == (LM, "legacy") and ks_of(rg, "projects/forge/hub-agent/part1") == (LM, "split"), ks_of(rg, "projects/forge/hub-agent/part1"))
check("a split of a hub the project's mark keeps: the project's keeper, source split (not mark)", ks_of(rg, "projects/forge/hub-plain") == (FB, "mark") and ks_of(rg, "projects/forge/hub-plain/part1") == (FB, "split"), ks_of(rg, "projects/forge/hub-plain/part1"))
check("a chain of two splits: the page follows the hub through the page between", ks_of(rg, "projects/forge/hub-agent/part1/part2") == (LM, "split"), ks_of(rg, "projects/forge/hub-agent/part1/part2"))
check("a `parent:` line is read like a `split_from:` line, and the hub may be in another project", ks_of(rg, "projects/forge/via-parent") == (FM, "split"), ks_of(rg, "projects/forge/via-parent"))
check("a `.md` suffix on the line is dropped; both lines on a page: split_from rules", ks_of(rg, "projects/forge/with-suffix") == (LM, "split") and ks_of(rg, "projects/forge/both") == (LM, "split"), (ks_of(rg, "projects/forge/with-suffix"), ks_of(rg, "projects/forge/both")))
check("a page with a line and no keeper of its own has no mark: it reads as an unmarked sub-page (role inherited), the registry's old fields unchanged", rg["projects/forge/hub-agent/part1"].get("role") == "inherited" and rg["projects/forge/hub-agent/part1"].get("split_from") == "projects/forge/hub-agent")

# ---- 3. a line that cannot be followed is no line
check("the shapes the docs list as reading as no line, silently: another letter case, a `#anchor`, a relative `../x`, a key without its pages dir, a YAML list (each names no page of the registry, and nothing is reported)",
      all(kp.split_target("x", {"x": {"split_from": p.split_line({"split_from": v})}, "projects/a/b": {}}) == "" for v in ("Projects/A/B", "projects/a/b#top", "../a/b", "a/b", ["projects/a/b"]))
      and kp.split_target("x", {"x": {"split_from": p.split_line({"split_from": "projects/a/b"})}, "projects/a/b": {}}) == "projects/a/b", [p.split_line({"split_from": v}) for v in ("Projects/A/B", "projects/a/b#top", "../a/b", "a/b")])
check("a loop of two pages: neither follows the other, each reads as the page above it (the project's mark)", ks_of(rg, "projects/forge/cyc-a") == (FB, "mark") and ks_of(rg, "projects/forge/cyc-b") == (FB, "mark"), (ks_of(rg, "projects/forge/cyc-a"), ks_of(rg, "projects/forge/cyc-b")))
check("a page that names itself reads as no line", ks_of(rg, "projects/forge/self") == (FB, "mark"), ks_of(rg, "projects/forge/self"))
check("a line that names no page of the registry (a full key, a bare slug) reads as no line", ks_of(rg, "projects/forge/miss") == (FB, "mark") and ks_of(rg, "projects/forge/bare") == (FB, "mark"), (ks_of(rg, "projects/forge/miss"), ks_of(rg, "projects/forge/bare")))
check("a target that has no keeper (a page nothing keeps): the line reads as no line, the page above answers", ks_of(rg, "projects/plain-note") == ("", "") and ks_of(rg, "projects/forge/to-plain") == (FB, "mark"), ks_of(rg, "projects/forge/to-plain"))
check("split_root: a loop, a self-reference and a missing page end nowhere", kp.split_root("projects/forge/cyc-a", rg) == "" and kp.split_root("projects/forge/self", rg) == "" and kp.split_root("projects/forge/miss", rg) == "" and kp.split_root("projects/forge/hub-plain", rg) == "")
check("split_root: a chain ends at the page that follows nothing", kp.split_root("projects/forge/hub-agent/part1/part2", rg) == "projects/forge/hub-agent" and kp.split_root("projects/forge/c3", rg) == "projects/forge/c0")
calls = []
real_target = kp.split_target
def counting(key, reg_):
    calls.append(key); return real_target(key, reg_)
kp.split_target = counting
try:
    kp.split_root("projects/forge/cyc-a", rg)
finally:
    kp.split_target = real_target
check("a loop is seen when it comes round, not when the bound is reached: two looks at the line for a loop of two", len(calls) == 2, calls)
check(f"the bound: a chain of {kp.SPLIT_HOPS} hops is followed to its hub, one hop more is not (that page reads as the page above it)",
      kp.SPLIT_HOPS == 8 and ks_of(rg, f"projects/forge/c{kp.SPLIT_HOPS}") == (LM, "split") and ks_of(rg, f"projects/forge/c{kp.SPLIT_HOPS + 1}") == (FB, "mark")
      and ks_of(rg, "projects/forge/c1") == (LM, "split"), (ks_of(rg, "projects/forge/c8"), ks_of(rg, "projects/forge/c9")))

# ---- 4. a page with a keeper of its own keeps it
check("a name line of its own keeps (legacy, the hub's keeper does not take it)", ks_of(rg, "projects/forge/own-name") == ("team-own", "legacy"), ks_of(rg, "projects/forge/own-name"))
check("an `agent:` line of its own keeps", ks_of(rg, "projects/forge/own-agent") == (FM, "legacy"), ks_of(rg, "projects/forge/own-agent"))
check("a mark of its own (the record's) keeps, the line or not", ks_of(rg, "projects/forge/own-mark") == (FB, "mark") and rg["projects/forge/own-mark"].get("page_mark") is True, ks_of(rg, "projects/forge/own-mark"))
check("a page that lists agents of its own is a project in its own right: the line is not followed", ks_of(rg, "projects/forge/own-agents")[1] != "split" and kp.split_target("projects/forge/own-agents", rg) == "", ks_of(rg, "projects/forge/own-agents"))
check("split_target: only a row with the line and no role of its own follows (a mark row, a page-mark row, a name or agent row and a row with agents do not)",
      kp.split_target("projects/forge/hub-agent/part1", rg) == "projects/forge/hub-agent" and all(kp.split_target(k, rg) == "" for k in ("projects/forge/own-name", "projects/forge/own-agent", "projects/forge/own-mark", "projects/forge/own-agents", "projects/forge")))
check("split_target on pure rows: no row, no field, a role mark, role agent, role name, page_mark, agents, itself, a missing page",
      kp.split_target("x", {}) == "" and kp.split_target("x", {"x": {"role": "inherited"}}) == "" and kp.split_target("x", {"x": {"role": "mark", "split_from": "y"}, "y": {}}) == ""
      and kp.split_target("x", {"x": {"role": "agent", "split_from": "y"}, "y": {}}) == "" and kp.split_target("x", {"x": {"role": "name", "split_from": "y"}, "y": {}}) == ""
      and kp.split_target("x", {"x": {"split_from": "y", "page_mark": True}, "y": {}}) == "" and kp.split_target("x", {"x": {"split_from": "y", "agents": {"a": ""}}, "y": {}}) == ""
      and kp.split_target("x", {"x": {"split_from": "x"}}) == "" and kp.split_target("x", {"x": {"split_from": "y"}}) == ""
      and kp.split_target("x", {"x": {"split_from": "y"}, "y": {}}) == "y" and kp.split_target("x", {"x": {"split_from": "y", "role": "inherited"}, "y": {}}) == "y")

# ---- 5. the gauge
leg = legacy(rg)
check("the legacy gauge does not count a page that follows another: the hubs an old form keeps are counted, the pages that were split off them are not", "projects/forge/hub-agent" in leg and "projects/other/plain" in leg and not {"projects/forge/hub-agent/part1", "projects/forge/hub-agent/part1/part2", "projects/forge/via-parent", "projects/forge/c8"} & set(leg), leg)
check("the sources a row can carry include `split`, and no row of the fixtures carries a source outside them", kp.SPLIT == "split" and kp.SPLIT in kp.SOURCES and {r.get("keeper_source", "") for r in rg.values()} <= {"", *kp.SOURCES}, {r.get("keeper_source") for r in rg.values()})
KR._STATE["gauge"] = None
prj.sync(reg=rg, path=T / "state" / "published.json", force=True)
gauge = KR._STATE["gauge"] or []
check("the gauge projects.sync publishes counts the pages an old form keeps and no page that follows another (source split)", gauge == leg and "projects/forge/hub-agent" in gauge and not any(rg[k]["keeper_source"] == "split" for k in gauge), (gauge, leg))
check("the keeper-subpages gauge (its `legacy` rows) agrees: none of them a split", ks._legacy(rg) == leg, ks._legacy(rg))

# ---- 5b. the readers of the old forms do not count a row that follows another page
def noted(): return set().union(*(v[1] for v in KR._PENDING.values())) if KR._PENDING else set()
def fresh_reads(): KR._STATE["flushed"] = time.monotonic() + 3600; KR._PENDING.clear(); KR._SEEN.clear(); KR._LAST.clear()       # no flush in the middle of the reads
SPLIT_ROWS = sorted(k for k, v in rg.items() if v.get("keeper_source") == "split" and str(v.get("session") or ""))
fresh_reads()
for k in SPLIT_ROWS: anchors.name_line(k, rg)
got_names = noted(); fresh_reads()
anchors.name_line("projects/other/plain", rg)
ctl_names = noted(); fresh_reads()
for n in sorted({str(rg[k]["session"]) for k in SPLIT_ROWS}): anchors.session_hubs(n, rg, {})
got_hubs = noted(); fresh_reads()
anchors.session_hubs("other-session", rg, {})
ctl_hubs = noted(); fresh_reads()
check("rows that follow another page have a session to read here (the fixture of the next two checks)", "projects/other/child" in SPLIT_ROWS and len(SPLIT_ROWS) > 3, SPLIT_ROWS)
check("anchors.name_line counts a row an old form keeps and no row that follows another page (source split)", ctl_names == {"projects/other/plain"} and not got_names, (ctl_names, got_names))
check("anchors.session_hubs counts a page the old form alone names and no row that follows another page (source split)", "projects/other/plain" in ctl_hubs and "projects/other/child" not in ctl_hubs and not got_hubs & set(SPLIT_ROWS), (ctl_hubs, got_hubs))
KR._STATE["flushed"] = time.monotonic()

# ---- 6. a retired project follows only a mark
check("a retired project: a page that was split off a page that has no keeper there has none", ks_of(rg, "projects/old-one/kid") == ("", ""), ks_of(rg, "projects/old-one/kid"))
check("a retired project: a page that was split off a marked page reads that mark (a mark is read even there), source split", ks_of(rg, "projects/old-one/kid2") == (LD, "split"), ks_of(rg, "projects/old-one/kid2"))
check("a retired project: a page that was split off a page an old form keeps (another project's `agent:` line) has no keeper, as a retired project's pages do", ks_of(rg, "projects/old-one/kid3") == ("", ""), ks_of(rg, "projects/old-one/kid3"))

# ---- 7. a mark that moves is read again by the pages that were split off the page
check("a project with no entry follows the keeper of the page it names across projects: loft's derived keeper first", ks_of(rg, "projects/loft/hubless") == ("loft-main", "derived") and ks_of(rg, "projects/other/child") == ("loft-main", "split") and ks_of(rg, "projects/other/plain") == ("other-session", "legacy"), (ks_of(rg, "projects/other/child"), ks_of(rg, "projects/other/plain")))
NOPK = {k: v for k, v in FORGE.items() if k != "page_keepers"}       # no sub-page mark anywhere: the page marks are not laid, so only the overlay of the entries can move the page
write_record({F: NOPK, LO: {**LOFT, "agents": {**LOFT["agents"], "loft-docs": agent(True, "keeps the docs", keeper=True)}}, OLD: OLDE})
rg2 = R(); agrees(rg2, "loft marks loft-docs")
check("loft marks loft-docs: the page it follows reads the mark, and the page that was split off it in a project with no entry reads it again", ks_of(rg2, "projects/loft/hubless") == (LD, "mark") and ks_of(rg2, "projects/other/child") == (LD, "split"), (ks_of(rg2, "projects/loft/hubless"), ks_of(rg2, "projects/other/child")))
write_record({F: {**FORGE, "page_keepers": {**FORGE["page_keepers"], "projects/forge/hub-mark": "forge-main"}}, LO: LOFT, OLD: OLDE})
rg3 = R(); agrees(rg3, "the hub's mark moves")
check("the mark of the hub moves (record, page_keepers): the page that was split off it reads the new one", ks_of(rg3, "projects/forge/hub-mark") == (FM, "mark") and ks_of(rg3, "projects/forge/hub-mark/part1") == (FM, "split") and ks_of(rg3, "projects/old-one/kid2") == (FM, "split"),
      (ks_of(rg3, "projects/forge/hub-mark/part1"), ks_of(rg3, "projects/old-one/kid2")))
write_record({F: {**FORGE, "page_keepers": {"projects/forge/own-mark": "forge-builder"}}, LO: LOFT, OLD: OLDE})
rg4 = R(); agrees(rg4, "the hub's mark taken away")
check("the hub's mark taken away: the hub follows the project's again and the page that was split off it with it (source split)", ks_of(rg4, "projects/forge/hub-mark") == (FB, "mark") and ks_of(rg4, "projects/forge/hub-mark/part1") == (FB, "split"), (ks_of(rg4, "projects/forge/hub-mark"), ks_of(rg4, "projects/forge/hub-mark/part1")))
write_record({F: FORGE, LO: LOFT, OLD: OLDE})

# ---- 8. no reader of `session` and `role` answers differently for a page with a split line
def snap(rg_):
    names = sorted({n for v in rg_.values() for n in kp.names_of(v)})
    return {"rows": {k: (v.get("session"), v.get("role"), v.get("legacy_session"), v.get("legacy_role"), sorted(kp.names_of(v)), kp.name_line(v)) for k, v in rg_.items()},
            "name_line": {k: anchors.name_line(k, rg_) for k in rg_}, "notice": {k: anchors.notice_name(k, rg_) for k in rg_}, "stand_in": {k: rl.stand_in_of(k, rg_) for k in rg_},
            "hubs": {n: anchors.session_hubs(n, rg_, {}) for n in names}, "pages_of": {n: anchors.keeper_pages(n, rg_) for n in names}, "page_keeper": {k: telling.page_keeper(k, rg_) for k in rg_},
            "roles": anchors.file_roles(rg_, set()), "sessions": anchors.session_roles(rg_, set())}
sA = snap(rg)
make(with_lines=False); p.cmd_registry(quiet=True); pr._CACHE["sig"] = None
rgB = R(); sB = snap(rgB)
check("the same pages written with no split line: the same set of pages", set(rg) == set(rgB))
check("every reader of `session` and `role` answers the same with and without the lines (name_line, notice_name, the stand-in, session_hubs, keeper_pages, the page keeper, roles, sessions)", all(sA[k] == sB[k] for k in sA), [k for k in sA if sA[k] != sB[k]])
check("only the pages with a line differ in what the keeper fields say", {k for k in rg if ks_of(rg, k) != ks_of(rgB, k)} <= {k for k, v in SPLIT_LINES.items() if v}, sorted({k for k in rg if ks_of(rg, k) != ks_of(rgB, k)}))
def bare(row): return {a: b for a, b in row.items() if a != "updated"}       # the page's write time differs between the two writes of the fixtures
check("... and the pages without a line answer the same in every field", all(bare(rg[k]) == bare(rgB[k]) for k in rg if not SPLIT_LINES.get(k)), [k for k in rg if not SPLIT_LINES.get(k) and bare(rg[k]) != bare(rgB[k])])
check("... the pages with a line carry `split_from` and nothing else more than the page without it (and the keeper fields)", all({a: b for a, b in rg[k].items() if a not in ("split_from", "keeper_agent", "keeper_source", "updated")} == {a: b for a, b in rgB[k].items() if a not in ("keeper_agent", "keeper_source", "updated")}
      for k, v in SPLIT_LINES.items() if v and k in rg), None)
LIVE = {"forge-main", "loft-main"}
SPLIT_PAGES = sorted(k for k, v in SPLIT_LINES.items() if v and "/own-" not in k)       # the pages that follow another (a page with a keeper of its own and a line stays: its row is the same either way)
for k in SPLIT_PAGES: (BRAIN / (k + ".md")).unlink()          # the same fixtures with the pages that carry a split line taken away: the dry run reads the pages that carry none
p.cmd_registry(quiet=True); pr._CACHE["sig"] = None
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    dryC = ks.run(live=LIVE, run_dir=T / "undo-c")
make(with_lines=True); p.cmd_registry(quiet=True); pr._CACHE["sig"] = None
with contextlib.redirect_stdout(buf):
    dryA = ks.run(live=LIVE, run_dir=T / "undo-a")
check("keeper-subpages dry run: the table of pages an `agent:` line keeps, its counts and its gauge are the same with the split pages there as without them (a split page has no `agent:` line to move)",
      bool(dryC["pages"]) and dryA["pages"] == dryC["pages"] and dryA["counts"] == dryC["counts"] and dryA["effects"]["gauge"] == dryC["effects"]["gauge"], (str(dryA["effects"]["gauge"]), str(dryC["effects"]["gauge"])))
moved_A = {m["key"] for m in dryA["effects"]["moved"]}; gained_A = {x for v in dryA["effects"]["gain_pages"].values() for x in v}
check("keeper-subpages dry run: what the pass moves is the same for every page that has no split line; only a page that follows another can read a moved mark (here projects/old-one/kid3, which follows the page it marks)",
      dryC["effects"]["moved"] == [m for m in dryA["effects"]["moved"] if m["key"] not in SPLIT_PAGES] and dryA["effects"]["lose"] == dryC["effects"]["lose"] and dryA["effects"]["roles"] == dryC["effects"]["roles"]
      and (moved_A | gained_A) <= set(SPLIT_PAGES) and "projects/old-one/kid3" in moved_A, (dryA["effects"]["moved"], dryC["effects"]["moved"]))
check("keeper-subpages dry run: writes nothing (the record is as it was)", json.loads(REC.read_text())["projects"] == {F: FORGE, LO: LOFT, OLD: OLDE})
check("the registry rebuilt with the lines on says what it said before", all(ks_of(R(), k) == ks_of(rg, k) for k in rg))

# ---- 9. the pages under a page that follows another read the target's keeper again whenever it moves
def page(rel, front):
    q = BRAIN / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
page("projects/q1.md", "type: project\ntitle: Q one\nagents:\n  q1-main: talks\n  q1-docs: keeps the docs\n  background:\n    q1-builder: builds and merges\nstatus: active")
page("projects/q1/t.md", "type: note\ntitle: Target")
page("projects/p1.md", "type: project\ntitle: P one\nagents:\n  p1-main: talks\nstatus: active")
page("projects/p1/h.md", "type: note\ntitle: Hub\nsplit_from: projects/q1/t")
page("projects/p1/h/x.md", "type: note\ntitle: X")
page("projects/p1/h/x/y.md", "type: note\ntitle: Y")
page("projects/p1/h2.md", "type: note\ntitle: Hub two\nsplit_from: projects/p1/h/x")          # a split of a page that is itself under a split page
page("projects/p1/h2/c.md", "type: note\ntitle: C")
page("projects/p1/h/own.md", "type: note\ntitle: Own\nagent: p1-main")                          # keeps its own, under the hub
page("projects/p1/plain.md", "type: note\ntitle: Plain")
page("projects/p1/h/own/z.md", "type: note\ntitle: Z")                                          # under a page an `agent:` line keeps, itself under the hub: the keeper above it is the hub's
page("projects/q1/t2.md", "type: note\ntitle: Target two\nagent: ghost-two")                    # a hub an `agent:` line keeps, that a hand-back can move
page("projects/p1/h3.md", "type: note\ntitle: Hub three\nsplit_from: projects/q1/t2")
page("projects/p1/h3/k.md", "type: note\ntitle: K")
page("projects/r1.md", "type: project\ntitle: R one\ndisplay-name: r1-sess\nstatus: active")      # a one-session project with no entry in the record: never a project the record changes
page("projects/r1/hub.md", "type: note\ntitle: R hub\nsplit_from: projects/q1/t")
page("projects/r1/hub/g.md", "type: note\ntitle: G")
page("projects/r1/hub/g/gg.md", "type: note\ntitle: GG")
p.cmd_registry(quiet=True); pr._CACHE["sig"] = None
ids9 = {k: e["id"] for k, e in raw().items()}
H, X, Y, H2, C9, T9 = "projects/p1/h", "projects/p1/h/x", "projects/p1/h/x/y", "projects/p1/h2", "projects/p1/h2/c", "projects/q1/t"
ZO, T2, H3, K3, R_H, R_G, R_GG = "projects/p1/h/own/z", "projects/q1/t2", "projects/p1/h3", "projects/p1/h3/k", "projects/r1/hub", "projects/r1/hub/g", "projects/r1/hub/g/gg"
UNDER = (H, X, Y, H2, C9, ZO, R_H, R_G, R_GG)          # all read the target's keeper: the hub, a child, a grandchild, a split of a child and its child, a child of a page an `agent:` line keeps, and a hub, child and grandchild of a project the record does not hold
Q1M, Q1D, Q1B = "q1-main", "q1-docs", "q1-builder"
def entries9(page_marks=None, q_mark="", p_mark=True):
    q1 = entry("projects/q1", agents={Q1M: agent(True, "talks", **({"keeper": True} if q_mark == Q1M else {})), Q1D: agent(True, "keeps the docs", **({"keeper": True} if q_mark == Q1D else {})),
                                       Q1B: agent(False, "builds and merges", **({"keeper": True} if q_mark == Q1B else {}))}, **({"page_keepers": page_marks} if page_marks else {}))
    p1 = entry("projects/p1", agents={"p1-main": agent(True, "talks", **({"keeper": True} if p_mark else {}))})
    return {ids9["projects/q1"]: q1, ids9["projects/p1"]: p1}
def settle(label, who, src_t, **kw):
    """The record with q1's page marks and q1's (or p1's) project mark as given: the pages under the hub read `who` (source split), the target `src_t`, and every published value equals a fresh read."""
    write_record(entries9(**kw))
    r = R()
    got = {k: ks_of(r, k) for k in (*UNDER, T9)}
    check(f"{label}: the hub, a child, a grandchild, a split of a child and its child, a child of an `agent:` page under it, and the same under a project the record does not hold read {who} (split), the target {src_t}", all(got[k] == (who, "split") for k in UNDER) and got[T9] == (who, src_t), got)
    agrees(r, label)
    return r
r9 = settle("before the target has a mark", Q1B, "derived")
pub9 = prj.build(r9)["projects"]
check("the published record carries the line as `split_from` (the key the row records) for a page that has one, and no such key for a page that has none (also not for a page under it)",
      pub9[ids9[H]].get("split_from") == T9 and pub9[ids9[H2]].get("split_from") == X and all("split_from" not in pub9[ids9[k]] for k in (X, Y, C9, T9, "projects/p1", "projects/p1/plain")), {k: v.get("split_from") for k, v in pub9.items()})
check("a page with an `agent:` line under the hub keeps it, and a plain page of the project is the project's", ks_of(r9, "projects/p1/h/own") == ("p1-main", "legacy") and ks_of(r9, "projects/p1/plain") == ("p1-main", "mark"), (ks_of(r9, "projects/p1/h/own"), ks_of(r9, "projects/p1/plain")))
check("the child under the hub has no line of its own and reads the keeper above it; reads_split says which pages a change of the target moves (and not the plain page, the `agent:` page or the target)",
      "split_from" not in r9[X] and r9[X].get("role") == "inherited" and kp.split_target(X, r9) == "" and all(kp.reads_split(k, r9) for k in UNDER)
      and not any(kp.reads_split(k, r9) for k in ("projects/p1/plain", "projects/p1/h/own", T9, "projects/p1", "projects/nowhere")), {k: (r9[k].get("role"), kp.reads_split(k, r9)) for k in (*UNDER, "projects/p1/plain")})
check("the pages under the hub of a project the record does not hold (no entry, no mark) are read through the page above them too", all(kp.reads_split(k, r9) for k in (R_H, R_G, R_GG, ZO)) and ks_of(r9, R_GG) == (Q1B, "split"), ks_of(r9, R_GG))
check("reads_split on pure rows: a row that follows a page; an unnamed row under one (through an unnamed row); a named row, an `agent:` row and a top-level row; an unnamed row with nothing above it; no row",
      kp.reads_split("projects/a/b", {"projects/a/b": {"split_from": "projects/z"}, "projects/z": {}})
      and kp.reads_split("projects/a/b/c/d", {"projects/a/b": {"session": "s", "role": "inherited", "split_from": "projects/z"}, "projects/z": {}, "projects/a/b/c": {"session": "s", "role": "inherited"}, "projects/a/b/c/d": {"role": "inherited"}})
      and not kp.reads_split("projects/a/b/c", {"projects/a/b": {"split_from": "projects/z", "session": "s", "role": "name"}, "projects/z": {}, "projects/a/b/c": {"role": "name"}})
      and not kp.reads_split("projects/a/b", {"projects/a/b": {"role": "inherited"}}) and not kp.reads_split("projects/a", {"projects/a": {"role": "inherited"}}) and not kp.reads_split("projects/a/b", {})
      and not kp.reads_split("projects/a/b/c", {"projects/a/b/c": {"role": "agent", "session": "s"}, "projects/a/b": {"session": "s", "role": "inherited", "split_from": "projects/z"}, "projects/z": {}})
      and not kp.reads_split("", {}) and not kp.reads_split("x", {"x": {"role": "inherited", "session": "s"}}))
settle("the target's page mark is laid after the split", Q1D, "mark", page_marks={T9: Q1D})
settle("the target's page mark moves", Q1M, "mark", page_marks={T9: Q1M})
settle("the target's page mark is removed", Q1B, "derived")
settle("the project's mark is laid on q1-docs", Q1D, "mark", q_mark=Q1D)
settle("the project's mark moves", Q1M, "mark", q_mark=Q1M)
settle("a page mark of the target and the project's mark: the page mark rules", Q1D, "mark", page_marks={T9: Q1D}, q_mark=Q1M)
settle("... the page mark goes: the project's mark answers", Q1M, "mark", q_mark=Q1M)
settle("the project's mark is removed", Q1B, "derived")
# a hub an `agent:` line keeps is handed back to the page above it (a record's hand-back): the page that was split off it, and the page under that, read the new keeper
write_record(entries9()); r9 = R(); before_hb = (ks_of(r9, T2), ks_of(r9, H3), ks_of(r9, K3))
write_record(entries9(page_marks={T2: ""})); r9 = R()
check("a hub an `agent:` line keeps, handed back: the hub reads the keeper of the project (no `agent:` answer any more), and the page that was split off it and the page under that read what it reads, as they read the `agent:` line before",
      before_hb == (("ghost-two", "legacy"), ("ghost-two", "split"), ("ghost-two", "split")) and ks_of(r9, T2) == (Q1B, "derived") and ks_of(r9, H3) == (Q1B, "split") and ks_of(r9, K3) == (Q1B, "split"), (before_hb, ks_of(r9, T2), ks_of(r9, H3), ks_of(r9, K3)))
agrees(r9, "a hand-back of the hub an `agent:` line keeps")
write_record(entries9(page_marks={T9: Q1D}, p_mark=False)); r9 = R()
check("the pages' own project has no mark: its unnamed sub-pages have no role, so only the hub follows the target (the split of a child follows the child, which reads the project's; the registry's rule for a page above it, unchanged), and every published value is a fresh read",
      ks_of(r9, H) == (Q1D, "split") and ks_of(r9, H2) == ("p1-main", "split") and all(ks_of(r9, k) == ("p1-main", "derived") for k in (X, Y, C9)) and not any(kp.reads_split(k, r9) for k in (X, Y, C9)), {k: (ks_of(r9, k), r9[k].get("role")) for k in UNDER})
agrees(r9, "the pages' own project has no mark")

# the hand-back of a page an `agent:` line keeps, that has a split line: it then follows the page the line names (a valid answer of the pass)
write_record(entries9())
page("projects/p1/ghost.md", "type: note\ntitle: Ghost\nagent: ghost-one\nsplit_from: projects/q1/t")
p.cmd_registry(quiet=True); pr._CACHE["sig"] = None
GH = "projects/p1/ghost"
new9, rows9 = ks.build(pr.entries(), prj.registry_raw(), live=set(), renames={})
row = next((r for r in rows9 if r["key"] == GH), {})
check("the pass hands back an `agent:` page that has a split line (no project lists the agent, no session runs under it): the page follows the page the line names",
      row.get("action") == "inherit" and new9[ids9["projects/p1"]].get("page_keepers", {}).get(GH) == "", (row, new9))
reg9 = pr.apply(prj.registry_raw(), new9)
check("... and that registry answers the page's keeper by the split", ks_of(reg9, GH) == (Q1B, "split") and reg9[GH].get("role") == "inherited", ks_of(reg9, GH))
check("the hand-back check accepts a page that follows the page it was split from (its keeper is not the one above it)", ks_of(reg9, GH) != ks_of(reg9, "projects/p1") and pv._page_answer_problem(GH, "", "", reg9) == "", pv._page_answer_problem(GH, "", "", reg9))
msg = pv._page_answer_problem(GH, "someone", None, reg9)
check("a mark asked for a page a split answers says the source in words: the page it was split from", "(the page it was split from)" in msg and msg.startswith(f"would answer {Q1B} ("), msg)
check("... and that word is a source's own entry: every source has its words", pv._SRC_WORDS.get("split") == "the page it was split from" and set(pv._SRC_WORDS) == set(kp.SOURCES), pv._SRC_WORDS)

if fails: print(f"FAILED: keeper split scenario, {len(ran)} checks, {len(fails)} failed"); sys.exit(1)
print(f"ok: keeper split scenario, {len(ran)} checks")
