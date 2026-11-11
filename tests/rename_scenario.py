"""Scenario test for rename_page.py's page read (`get`, 2026-10-06) — fixture output, no gbrain CLI, no database.

`gb()` returns the CLI's stdout and stderr in one string, and since gbrain 0.60.81.0 was released the CLI prints an upgrade
notice on stderr, after the JSON. Also the project-without-agents check of a move (`agents_gap`, `plan`/`copy` WARN, `stub` refusal, `--no-agents-ok`), on a fake gbrain that keeps pages in a dict. Covers: `gbrain call get_page` output with the notice after the object, before it, or
absent still reads as the page's content and revision; output with no object, a broken object, or an object without
content reads as unreadable (None, None).

    tests/run-suite rename        → exit 0 / 1"""
import json, os, pathlib, re, sys, tempfile
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="renametest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("store", f"{tmp}/store")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "store").mkdir(); (T / "brain").mkdir()
os.environ["STACKSHOT_CONFIG"] = f"{tmp}/stackshot.toml"
sys.path.insert(0, STACK)
fails = []; ran = []
def check(name, ok, detail=""):
    ran.append(name)
    if not ok: fails.append(name); print(f"FAIL {name}\n     {str(detail)[:400]}")

from stackshot.projects import rename_page as rp
PAGE = {"content": "---\ntitle: X\n---\n\nbody {not json}\n", "revision": "abc123"}
OBJ = json.dumps(PAGE, indent=2)
NOTICE = "UPGRADE_AVAILABLE 0.60.69.0 0.60.81.0\ngbrain 0.60.69.0 -> 0.60.81.0 available. Run: gbrain self-upgrade\n"
def read(out):
    rp.gb = lambda args, stdin=None: (0, out)
    return rp.get("projects/x")
want = (PAGE["content"], PAGE["revision"])
check("the upgrade notice after the JSON: content and revision", read(OBJ + "\n" + NOTICE) == want, read(OBJ + "\n" + NOTICE))
check("the upgrade notice before the JSON: content and revision", read(NOTICE + OBJ + "\n") == want, read(NOTICE + OBJ + "\n"))
check("the JSON alone: content and revision", read(OBJ) == want, read(OBJ))
check("no JSON in the output: unreadable", read(NOTICE) == (None, None), read(NOTICE))
check("a cut-off object: unreadable", read(OBJ[:-5] + "\n" + NOTICE) == (None, None), read(OBJ[:-5]))
check("an error object: unreadable", read('{"error": "page not found"}\n' + NOTICE) == (None, None))

# ---- a move that leaves a project page with no agent (the `projects/example/example-three` → `projects/example-three` replay)
import contextlib, io
(T / "store" / "projects.json").write_text(json.dumps({"pages": {"projects/harbor": {"title": "Harbor", "type": "project", "agents": {"harbor-main": "x"}},
                                                                 "projects/meadow": {"title": "Meadow", "type": "project", "session": "ibis-meadow", "role": "name", "agents": {"ibis-meadow-main": "x"}},
                                                                 "projects/foo": {"title": "Foo", "type": "project", "session": "foo", "role": "name", "agents": {"foo-main": "x"}},
                                                                 "projects/quarry-core": {"title": "Quarry core", "type": "project", "session": "quarry-core", "role": "name", "agents": {"quarry-core-main": "x"}},
                                                                 "projects/shared-alpha": {"title": "Shared Alpha", "type": "project", "session": "quartz-shared", "role": "name"}}}))   # the registry: a page a sub-page can stand under, and a project whose name other sessions carry
PAGES = {}; PUTS = []; REV = [0]
def fake_gb(args, stdin=None, slug=None):
    """The pages of a fake brain: `call get_page` reads one, `put` writes one (a new revision each time)."""
    if args[0] == "call":
        p = PAGES.get(json.loads(args[2])["slug"])
        return (0, json.dumps({"content": p[0], "revision": p[1]})) if p else (1, '{"error": "page not found"}')
    if args[0] == "put":
        REV[0] += 1; PAGES[args[1]] = [stdin, f"rev{REV[0]:04d}"]; PUTS.append(args[1]); return 0, "{}"
    return 2, "unknown call"
rp.gb = fake_gb
def mk(slug, typ="project", extra="", agents=""):
    PAGES[slug] = [f"---\ntitle: {slug}\ntype: {typ}\n{extra}{agents}---\n\n# {slug}\n\nbody\n", f"seed{len(PAGES):04d}"]
def mv(*argv):
    """rename_page.main() on argv → (exit code, its output)."""
    out = io.StringIO(); sys.argv = ["rename_page.py", *argv]
    with contextlib.redirect_stdout(out):
        try: rp.main(); rc = 0
        except SystemExit as e: rc = e.code if isinstance(e.code, int) else 1
    return rc, out.getvalue()
is_redirect = lambda slug: "type: redirect" in PAGES[slug][0]
EX3 = "---\ntitle: example-three\ntype: project\n---\n\n# example-three\n\nbody\n"
AGENTS = "agents:\n  example-three-main: keeps the project\n"

def gap(text, new="projects/example-three", old=None):
    g = rp.agents_gap(text, new, old)
    return "" if g is None else g[0] + " | " + g[1]
rp._live_sessions = lambda: None            # sala unreadable (the suite has no fleet store): a name line counts as live until a check says otherwise
check("agents_gap: a top-level project page with no agents map is a gap", "no agents map" in gap(EX3), gap(EX3))
check("agents_gap: …a page with only background agents too", "only background agents" in gap(EX3.replace("---\n\n#", "agents:\n  background:\n    example-three-builder: builds\n---\n\n#", 1)), gap(EX3.replace("---\n\n#", "agents:\n  background:\n    example-three-builder: builds\n---\n\n#", 1)))
check("agents_gap: a front agent (a -main one) clears it", gap(EX3.replace("---\n\n#", AGENTS + "---\n\n#", 1)) == "", gap(EX3.replace("---\n\n#", AGENTS + "---\n\n#", 1)))
check("agents_gap: any front agent clears it, a -main name or not", gap(EX3.replace("---\n\n#", "agents:\n  example-three-lead: leads\n---\n\n#", 1)) == "")
check("agents_gap: a note, an untyped page and a retired project are no gap", gap(EX3.replace("type: project", "type: note")) == "" and gap(EX3.replace("type: project\n", "")) == "" and gap(EX3.replace("type: project", "type: Project\nstatus: Archived")) == "")
check("agents_gap: the type is read case-insensitively", "no agents map" in gap(EX3.replace("type: project", "type: Project")), gap(EX3.replace("type: project", "type: Project")))
check("agents_gap: a sub-page (an ancestor page in the registry, or a hub: line) is no gap", gap(EX3, "projects/harbor/example-three") == "" and gap(EX3.replace("---\n\n#", "hub: projects/harbor\n---\n\n#", 1)) == "")
check("agents_gap: a parent: line makes no sub-page (the registry does not read it, so neither does the daily check)", "no agents map" in gap(EX3.replace("---\n\n#", "parent: projects/harbor\n---\n\n#", 1)))
check("agents_gap: moved and superseded pages are skipped like retired ones", gap(EX3.replace("type: project", "type: project\nstatus: moved")) == "" and gap(EX3.replace("type: project", "type: project\nstatus: superseded")) == "" and gap(EX3.replace("title: example-three", "title: moved to elsewhere")) == "")
# a one-session page: a name line, no agents map
SOLO = EX3.replace("---\n\n#", "display-name: example-three-solo\n---\n\n#", 1)
def live(*names): rp._live_sessions = lambda: (set(names), set())
live("example-three-solo")
check("agents_gap: a one-session page whose name line is a live session is no gap", gap(SOLO) == "", gap(SOLO))
live("example-three-solo-builder")
check("agents_gap: …a live session that starts with the name line counts too", gap(SOLO) == "", gap(SOLO))
live("someone-else")
check("agents_gap: a name line that names no live session is a gap, and says the session is not live", "example-three-solo that is not live" in gap(SOLO) and "add the agents map" in gap(SOLO), gap(SOLO))
rp._live_sessions = lambda: None
check("agents_gap: sala unreadable: the name line counts as live", gap(SOLO) == "")
check("agents_gap: a session id on the name line is no name: not a one-session page even with liveness unknown", "no agents map" in gap(EX3.replace("---\n\n#", "display-name: 00000000-0000-4000-8000-000000000051\n---\n\n#", 1)))
check("agents_gap: an agent: line is no name line (that page is not a one-session page)", "no agents map" in gap(EX3.replace("---\n\n#", "agent: example-three-solo\n---\n\n#", 1)))
# the example-three case: the name line's session belongs to another project (ibis-meadow), whatever its liveness
FOREIGN = EX3.replace("---\n\n#", "display-name: ibis-meadow-example-three\n---\n\n#", 1)
live("ibis-meadow-example-three")
check("agents_gap: a live session named for another project is a gap: the example-three case, said in the words of the finding", "projects/example-three's only session ibis-meadow-example-three is named for ibis-meadow, not for this page, and no agents map lists it" in gap(FOREIGN) and "its own agents map and -main agent" in gap(FOREIGN) and "general -main agent" in gap(FOREIGN), gap(FOREIGN))
rp._live_sessions = lambda: None
check("agents_gap: …also when liveness is unknown", "named for ibis-meadow" in gap(FOREIGN), gap(FOREIGN))
check("agents_gap: …but not when the page has a front agent of its own", gap(FOREIGN.replace("---\n\n#", AGENTS + "---\n\n#", 1)) == "")
check("agents_gap: a name line that is the other project's own name is not named for it", gap(EX3.replace("---\n\n#", "display-name: ibis-meadow\n---\n\n#", 1)) == "")
# sibling-prefix shapes: a one-session page whose name extends another project's name is its own when the name is (or starts with) its own slug; a prefix-matched session of a longer sibling covers nothing
def named(name, new, extra=""): return EX3.replace("---\n\n#", f"display-name: {name}\n{extra}---\n\n#", 1)
live("foo-bar")
check("agents_gap: a one-session page `foo-bar` next to a project `foo` is its own, not named for it", gap(named("foo-bar", "projects/foo-bar"), "projects/foo-bar") == "", gap(named("foo-bar", "projects/foo-bar"), "projects/foo-bar"))
live("ibis-meadow-example-three")
check("agents_gap: …a page `ibis-meadow-example-three` with that name next to `ibis-meadow` too (the own-slug case of the example-three shape)", gap(named("ibis-meadow-example-three", "projects/ibis-meadow-example-three"), "projects/ibis-meadow-example-three") == "", gap(named("ibis-meadow-example-three", "projects/ibis-meadow-example-three"), "projects/ibis-meadow-example-three"))
live("foo-bar-engineer")
check("agents_gap: a background-only page `foo-bar` whose keeper is `foo-bar-engineer` is its own", gap(named("foo-bar-engineer", "projects/foo-bar", "agents:\n  background:\n    foo-bar-builder: builds\n"), "projects/foo-bar") == "", gap(named("foo-bar-engineer", "projects/foo-bar", "agents:\n  background:\n    foo-bar-builder: builds\n"), "projects/foo-bar"))
live("quartz-shared")
check("agents_gap: two pages sharing one session name do not flag each other", gap(named("quartz-shared", "projects/shared-b"), "projects/shared-b") == "", gap(named("quartz-shared", "projects/shared-b"), "projects/shared-b"))
live("quarry-core-engineer")
check("agents_gap: a page `quarry` is not covered by the live `quarry-core-engineer` when `quarry-core` is a page of its own", "name line session quarry that is not live" in gap(named("quarry", "projects/quarry"), "projects/quarry"), gap(named("quarry", "projects/quarry"), "projects/quarry"))
live("quarry")
check("agents_gap: …an exact live name still covers it", gap(named("quarry", "projects/quarry"), "projects/quarry") == "")
live("quarry-other-main")
check("agents_gap: …and so does a live session that belongs to no longer project name", gap(named("quarry", "projects/quarry"), "projects/quarry") == "")
rp._live_sessions = lambda: None
check("agents_gap: a page that was no project at the old slug says the type changed", "type: note at the old slug" in gap(EX3, old=EX3.replace("type: project", "type: note")), gap(EX3, old=EX3.replace("type: project", "type: note")))
check("agents_gap: a page with no frontmatter is no gap, not an error", gap("no frontmatter here") == "")

# the example-three case: copy warns, stub refuses and changes nothing, then agents on the destination page let it through
mk("projects/example/example-three")
rc, out = mv("copy", "projects/example/example-three=projects/example-three")
check("copy to a project page with no agents: done, with a WARN naming the page and the fix", rc == 0 and "WARN" in out and "projects/example-three" in out and "agents map" in out and "projects/example-three" in PAGES and "reads back identical" in out, (rc, out))
puts = len(PUTS)
rc, out = mv("stub", "projects/example/example-three=projects/example-three")
check("stub is refused for it: FAIL naming the page and saying to add the agents map, exit 1", rc == 1 and "FAIL stub" in out and "projects/example-three" in out and "agents map" in out and "-main" in out and "stub again" in out, (rc, out))
check("…and nothing changed: no write, the old page is no redirect", len(PUTS) == puts and not is_redirect("projects/example/example-three"), (PUTS, PAGES["projects/example/example-three"][0][:80]))
PAGES["projects/example-three"][0] = PAGES["projects/example-three"][0].replace("aliases:", AGENTS + "aliases:", 1)       # the keeper adds the agents map on the destination page
check("the premise of the fix: the keeper's edit put the agents map in the destination", "example-three-main" in PAGES["projects/example-three"][0], PAGES["projects/example-three"][0])
rc, out = mv("stub", "projects/example/example-three=projects/example-three")
check("with the agents map on the destination, stub goes through", rc == 0 and "stub projects/example/example-three" in out and is_redirect("projects/example/example-three"), (rc, out))

# the opt-out
mk("projects/example/solo")
rc, out = mv("copy", "projects/example/solo=projects/solo", "--no-agents-ok")
check("--no-agents-ok: copy prints no WARN", rc == 0 and "WARN" not in out and "projects/solo" in PAGES, (rc, out))
rc, out = mv("stub", "projects/example/solo=projects/solo", "--no-agents-ok")
check("--no-agents-ok: stub goes through on a project page with no agents", rc == 0 and is_redirect("projects/example/solo"), (rc, out))

# the cases the check leaves alone
mk("projects/example/mech")
rc, out = mv("copy", "projects/example/mech=projects/harbor/mech"); rc2, out2 = mv("stub", "projects/example/mech=projects/harbor/mech")
check("a move to a sub-page is unchanged: no WARN, stub goes through", rc == 0 and rc2 == 0 and "WARN" not in out and is_redirect("projects/example/mech"), (out, out2))
mk("projects/example/under")
rc, out = mv("copy", "projects/example/under=projects/under", "--parent", "projects/harbor"); rc2, out2 = mv("stub", "projects/example/under=projects/under")
check("a move with --parent is no sub-page for the registry: WARN, and stub is refused", rc == 0 and "WARN" in out and "parent: projects/harbor" in PAGES["projects/under"][0] and rc2 == 1 and not is_redirect("projects/example/under"), (out, out2))
mk("projects/example/memo", typ="note")
rc, out = mv("copy", "projects/example/memo=projects/memo"); rc2, out2 = mv("stub", "projects/example/memo=projects/memo")
check("a move of a note is unchanged", rc == 0 and rc2 == 0 and "WARN" not in out and is_redirect("projects/example/memo"), (out, out2))
mk("projects/example/old", extra="status: archived\n")
rc, out = mv("copy", "projects/example/old=projects/old"); rc2, out2 = mv("stub", "projects/example/old=projects/old")
check("a move of a retired project is unchanged", rc == 0 and rc2 == 0 and "WARN" not in out and is_redirect("projects/example/old"), (out, out2))
mk("projects/example/staffed", agents=AGENTS)
rc, out = mv("copy", "projects/example/staffed=projects/staffed"); rc2, out2 = mv("stub", "projects/example/staffed=projects/staffed")
check("a project page that lists a front agent moves as before", rc == 0 and rc2 == 0 and "WARN" not in out and is_redirect("projects/example/staffed"), (out, out2))

# a one-session page (a name line naming a live session, no agents map) moves as before; the example-three shape (its name line belongs to another project) is warned about and refused
live("example-three-solo")
mk("projects/example/solo2", extra="display-name: example-three-solo\n")
rc, out = mv("copy", "projects/example/solo2=projects/solo2"); rc2, out2 = mv("stub", "projects/example/solo2=projects/solo2")
check("a one-session page with a live session of its own name moves as before: no WARN, stub goes through", rc == 0 and rc2 == 0 and "WARN" not in out and is_redirect("projects/example/solo2"), (out, out2))
mk("projects/example/example-three2", extra="display-name: ibis-meadow-example-three\n")
live("ibis-meadow-example-three")
rc, out = mv("copy", "projects/example/example-three2=projects/work-example-three"); puts = len(PUTS)
rc2, out2 = mv("stub", "projects/example/example-three2=projects/work-example-three")
check("the example-three shape: copy warns that the page's only session is named for another project", rc == 0 and "WARN" in out and "ibis-meadow-example-three is named for ibis-meadow, not for this page" in out, out)
check("…stub is refused with that message, naming the fix, and changes nothing", rc2 == 1 and "FAIL stub" in out2 and "named for ibis-meadow" in out2 and "its own agents map and -main agent" in out2 and len(PUTS) == puts and not is_redirect("projects/example/example-three2"), (rc2, out2))
rc3, out3 = mv("stub", "projects/example/example-three2=projects/work-example-three", "--no-agents-ok")
check("…--no-agents-ok lets it through", rc3 == 0 and is_redirect("projects/example/example-three2"), (rc3, out3))
live("someone-else")
mk("projects/example/lone", extra="display-name: lone-name\n")
rc, out = mv("copy", "projects/example/lone=projects/lone"); rc2, out2 = mv("stub", "projects/example/lone=projects/lone")
check("a name line that names no live session: WARN at copy, stub refused (no session of its own)", rc == 0 and "WARN" in out and "lone-name that is not live" in out and rc2 == 1 and not is_redirect("projects/example/lone"), (out, out2))
rp._live_sessions = lambda: None

# a type change: a note at the old slug that is a project by the time of stub
mk("projects/example/promo", typ="note")
rc, out = mv("copy", "projects/example/promo=projects/promo")
PAGES["projects/promo"][0] = PAGES["projects/promo"][0].replace("type: note", "type: project", 1)
rc2, out2 = mv("stub", "projects/example/promo=projects/promo")
check("a page that was a note and is a project at the destination: stub is refused, and says the type changed", rc == 0 and "WARN" not in out and rc2 == 1 and "type: note at the old slug" in out2 and not is_redirect("projects/example/promo"), (out, rc2, out2))

# two pages in one stub: the refusal of one stops both (nothing half done)
mk("projects/example/pa"); mk("projects/example/pb")
mv("copy", "projects/example/pa=projects/pa", "projects/example/pb=projects/pb", "--no-agents-ok")
PAGES["projects/pb"][0] = PAGES["projects/pb"][0].replace("aliases:", AGENTS + "aliases:", 1)
rc, out = mv("stub", "projects/example/pb=projects/pb", "projects/example/pa=projects/pa")
check("a refusal for one of two pages stubs neither", rc == 1 and "projects/pa" in out and not is_redirect("projects/example/pb") and not is_redirect("projects/example/pa"), (rc, out))
puts = len(PUTS)
rc, out = mv("plan", "projects/example/pa=projects/pa")
check("plan warns too and writes no page", rc == 0 and "WARN" in out and len(PUTS) == puts, (rc, out))

# no page registry here (empty or missing): one note, no WARN and no refusal, whatever the page is (a would-be sub-page cannot be told from a project)
REGF = T / "store" / "projects.json"; saved = REGF.read_text()
for label, body in (("empty", json.dumps({"pages": {}})), ("missing", None)):
    if body is None: REGF.unlink()
    else: REGF.write_text(body)
    mk(f"projects/example/n{label}")
    rc, out = mv("copy", f"projects/example/n{label}=projects/n{label}"); rc2, out2 = mv("stub", f"projects/example/n{label}=projects/n{label}")
    check(f"a {label} registry: copy prints one note and no WARN, stub goes through", rc == 0 and out.count("note: the page registry is not readable") == 1 and "WARN" not in out and rc2 == 0 and is_redirect(f"projects/example/n{label}"), (out, rc2, out2))
# a run that is refused prints only its refusal: the note comes only where the agents check would run
REGF.write_text(json.dumps({"pages": {}}))
rc, out = mv("copy", "projects/example/absent=projects/absent")
check("an empty registry, an unreadable page: only its FAIL line, no note", rc == 1 and "unreadable" in out and "note:" not in out, (rc, out))
rc, out = mv("plan", "projects/example/absent=projects/absent", "--no-agents-ok")
check("--no-agents-ok never prints the note", "note:" not in out, out)
REGF.write_text(saved)
mk("projects/example/nreg")
rc, out = mv("copy", "projects/example/nreg=projects/nreg")
check("with the registry back the same page is warned about, with no note", "WARN" in out and "note: the page registry" not in out, out)

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": rename scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
