"""Scenario test for page currency (board; stackshot.toml [page_gate] keeper_currency) on fixture data — a temp
brain with its own git history, no live store, no network.

Covers: who the rules apply to (every session that keeps an active page, not its agents); the Current-state excerpt (whole
when it fits, else cut at a line, an even share between pages); what makes a turn one to ask about (a notice alone does not,
a page write in a notice's turn does); the Stop hook asks nothing about pages (the end-of-turn page question retired, Oliver, Mon
Oct 12th 2026) while the page debt is still owed, said at every prompt and settled; the server's settle rule and its wording; the
end-of-turn board check: what counts as real work, touched and untouched items, the `Board: no change` lines, the client
read it uses, and its question asked early at the turn's first write.

    tests/run-suite page_currency        → exit 0 / 1"""
import json, os, re, shutil, subprocess, sys, time, pathlib, tempfile, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="page-currency-test-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), keywords=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"),
                 ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1   # the fixtures' subjects
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet")   # the session and machine state is a fixture under fleet/
os.environ.pop("KEEPER_CURRENCY", None); os.environ.pop("PROJECT_GATE_MODE", None); os.environ.pop("BOARD_CHECK_MODE", None)
S, A, B = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333"
for d in ("store/a", "fleet/a", "state", "secrets", "touch", "brain/projects"): (T / d).mkdir(parents=True)
(T / "fleet/a/sessions.json").write_text(json.dumps({S: {"name": "work-osprey", "machine": "a"}, A: {"name": "work-osprey-main", "machine": "a"}, B: {"name": "home-beta", "machine": "a"}}))
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
reg = lambda name, sess, status="active": {"title": name, "name": name, "session": sess, "status": status, "board": [], "updated": 1, "mirror": ""}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": reg("Alpha", "work-osprey"), "projects/beta": reg("Beta", "home-beta"),
                                                             "projects/gamma": reg("Gamma", "work-osprey"), "projects/old": reg("Old", "work-osprey-main", "completed")}}))
(T / "store/next-id").write_text("10")
bullets = "\n".join(f"- **Point {i}:** " + ("状態の一行 state words here " * 9).strip() + "." for i in range(1, 27))       # ≈ 8 KB of Current state, 26 bullets
def page(title, state): return f"---\ntype: project\ntitle: {title}\nsession: x\n---\n\n# {title}\n\n## Goal\n\nA goal.\n\n## Current state\n\n{state}\n\n## Decisions\n\n- none\n\n<!-- timeline -->\n\n## Timeline\n\n- **2026-01-01** | t — made\n"
for k, st in (("alpha", bullets), ("beta", "- small state."), ("gamma", bullets)): (T / f"brain/projects/{k}.md").write_text(page(k, st), encoding="utf-8")
old = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 7200))
git = lambda *a: subprocess.run(["git", "-C", str(T / "brain"), "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True, env={**os.environ, "GIT_COMMITTER_DATE": old, "GIT_AUTHOR_DATE": old})
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "pages")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))

# ---- 1. who
from stackshot.projects import pages as p
check("the rollout value", p.currency() == "keepers", p.currency())
_pg = p._cfg.CFG["page_gate"]; _saved = dict(_pg); _pg.pop("keeper_currency", None); _pg["steward_currency"] = "stewards"
check("compat dropped: the retired key steward_currency is not read (no keeper_currency = the rollout default off)", p.currency() == "off", p.currency())
from stackshot.core import config as _config
_n_old = _config.notes({"instance": {"owner": "Oliver"}, "page_gate": {"steward_currency": "stewards"}}); _n_none = _config.notes({"instance": {"owner": "Oliver"}, "page_gate": {"mode": "auto"}}); _n_nosec = _config.notes({"instance": {"owner": "Oliver"}})
check("…and config.notes says so, once, for a config with only the old key and for one with neither (the page rules are off, never silently)",
      len(_n_old) == 1 and "steward_currency is no longer read" in _n_old[0] and "keeper_currency" in _n_old[0] and len(_n_none) == 1 and "no keeper_currency" in _n_none[0] and len(_n_nosec) == 1, (_n_old, _n_none, _n_nosec))
check("…and not for a config that has keeper_currency, whatever its value", _config.notes({"instance": {"owner": "Oliver"}, "page_gate": {"keeper_currency": "off"}}) == [] and _config.notes({"instance": {"owner": "Oliver"}, "page_gate": {"keeper_currency": "stewards"}}) == [], None)
_pg["keeper_currency"] = "stewards"; check("the value \"stewards\" (a client installed by the old `client install` holds the raw copy) is read as keepers", p.currency() == "keepers", p.currency())
_pg.pop("steward_currency"); _pg["keeper_currency"] = "all"; check("keeper_currency takes its value", p.currency() == "all", p.currency()); _pg.clear(); _pg.update(_saved)
check("a keeper is in", p.in_currency(S) and p.in_currency(B))
check("an agent that keeps nothing is not", not p.in_currency(A))
check("a completed page makes no keeper", not p.keepers_any(["work-osprey-main"]))
check("an unknown session is not", not p.in_currency("99999999-9999-4999-8999-999999999999"))
os.environ["KEEPER_CURRENCY"] = "work-osprey-main"; check("a name list still works (the pilot's form)", p.in_currency(A) and not p.in_currency(S))
os.environ["KEEPER_CURRENCY"] = "off"; check("off", not p.in_currency(S)); os.environ.pop("KEEPER_CURRENCY")
check("keeper's pages", p.keeper_pages(S, "work-osprey") == ["projects/alpha", "projects/gamma"], p.keeper_pages(S, "work-osprey"))

# ---- 1b. the registry reads who keeps a page: display-name · agent · the old session key · the hub's name for a sub-page that names nobody
def fmpage(rel, front): 
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
fmpage("projects/hub.md", "type: project\ntitle: >-\n  Hub: a title with a colon in it, folded\n  over two lines\ndisplay-name: s-hub\nagents:\n  s-hub-main: 'upgrades, the curator'\n  s-hub-docs: writes the docs\ntags:\n  - one\n  - two")
fmpage("projects/hub/work.md", "type: project\ntitle: Work\nagent: s-hub-main")
fmpage("projects/hub/plain.md", "type: project\ntitle: Plain")
fmpage("projects/hub/work/deep.md", "type: project\ntitle: Deep")
fmpage("projects/hub/timeline-2026-q3.md", "type: archive\ntitle: old")
fmpage("projects/legacy.md", "type: project\ntitle: Legacy\nsession: old-name\nagents: {a-one: \"does x\", a-two: 'does y, z'}")
fmpage("projects/legacy/sub.md", "type: project\ntitle: Sub\nsession: other")
fmpage("projects/legacy/same.md", "type: project\ntitle: Same\nsession: old-name")
fmpage("ops/alone.md", "type: note\ntitle: Alone")
fmpage("projects/folded.md", "type: project\ntitle: Folded\ndisplay-name: s-f\nagents:\n  s-f-press: >-\n    drafts and ships the newsletters, keeps the mailing list,\n    and answers the subscribers\n  s-f-short: one line\n  s-f-wrap: a plain value that simply\n    wraps onto the next line\nstatus: active")
fmpage("projects/bg.md", "type: project\ntitle: Bg\ndisplay-name: s-bg\nagents:\n  s-bg-main: talks to Oliver\n  s-bg-docs: 'the docs: content, prompts'\n  background:\n    s-bg-sweep: 'sweeps the inbox, Oliver''s'\n    s-bg-watch: >-\n      watches the releases\n      and files them\n    s-bg-wrap: a plain value that\n      wraps\n  s-bg-old: 'Background: the legacy prefix, kept as written'\nstatus: active")
fmpage("projects/bgi.md", "type: project\ntitle: Bgi\ndisplay-name: s-bgi\nagents: {s-bgi-main: \"talks\", s-bgi-two: 'does y, z', background: {s-bgi-night: 'runs at night, Oliver''s', s-bgi-day: plain}}")
# the key `display-name:` replaced `steward:`; a leftover `steward:` line is no longer read
fmpage("projects/dn-new.md", "type: project\ntitle: Dn new\ndisplay-name: x-proj\nagents:\n  x-proj-main: talks\n  background:\n    x-proj-eng: builds\nstatus: active")
fmpage("projects/dn-old.md", "type: project\ntitle: Dn old\nsteward: x-proj\nagents:\n  x-proj-main: talks\n  background:\n    x-proj-eng: builds\nstatus: active")
fmpage("projects/dn-both.md", "type: project\ntitle: Dn both\nsteward: q-old\ndisplay-name: x-new\nstatus: active")
fmpage("projects/dn-both2.md", "type: project\ntitle: Dn both 2\ndisplay-name: y-new\nsteward: y-old\nstatus: active")
fmpage("projects/dn-new/sub.md", "type: project\ntitle: Sub of dn-new")
fmpage("projects/dn-quoted.md", "type: project\ntitle: Dn quoted\ndisplay-name: 'x-q'\nstatus: active")
real_reg = p.REG; p.REG = str(T / "registry-test.json"); p.cmd_registry(quiet=True); R = json.loads(open(p.REG).read())["pages"]; p.REG = real_reg
who = lambda k: (R[k].get("session"), R[k].get("role"))
check("registry: display-name: on a hub", who("projects/hub") == ("s-hub", "name"), R.get("projects/hub"))
check("registry: a folded title and a list still parse beside the new keys", R["projects/hub"]["title"].startswith("Hub: a title with a colon") and R["projects/hub"]["tags"] == ["one", "two"], R["projects/hub"])
check("registry: agents as a block map", R["projects/hub"].get("agents") == {"s-hub-main": "upgrades, the curator", "s-hub-docs": "writes the docs"}, R["projects/hub"].get("agents"))
check("registry: agent: on a sub-page", who("projects/hub/work") == ("s-hub-main", "agent"))
check("registry: a sub-page that names nobody is the hub's name-line session's", who("projects/hub/plain") == ("s-hub", "inherited"))
check("registry: …also below an agent's page: the hub's, not the agent's", who("projects/hub/work/deep") == ("s-hub", "inherited"), who("projects/hub/work/deep"))
check("registry: an archive page is no page", "projects/hub/timeline-2026-q3" not in R)
check("registry: the old session: key on a hub reads as its name", who("projects/legacy") == ("old-name", "name"))
check("registry: agents as an inline map", R["projects/legacy"].get("agents") == {"a-one": "does x", "a-two": "does y, z"}, R["projects/legacy"].get("agents"))
check("registry: the old key on a sub-page kept by someone else reads as an agent", who("projects/legacy/sub") == ("other", "agent"))
check("registry: …and by the hub's own name-line session as the name", who("projects/legacy/same") == ("old-name", "name"))
check("registry: a long mandate gbrain folded onto the next lines reads whole", R["projects/folded"].get("agents") == {"s-f-press": "drafts and ships the newsletters, keeps the mailing list, and answers the subscribers", "s-f-short": "one line", "s-f-wrap": "a plain value that simply wraps onto the next line"} and R["projects/folded"]["status"] == "active", R["projects/folded"])
BG_ALL = {"s-bg-main": "talks to Oliver", "s-bg-docs": "the docs: content, prompts", "s-bg-sweep": "sweeps the inbox, Oliver's", "s-bg-watch": "watches the releases and files them", "s-bg-wrap": "a plain value that wraps", "s-bg-old": "Background: the legacy prefix, kept as written"}
check("registry: a nested background: map → agents flat with every name, front and background, and no background key", R["projects/bg"].get("agents") == BG_ALL and R["projects/bg"]["status"] == "active", R["projects/bg"])
check("registry: back_agents = the background: sub-map plus a legacy 'background:' mandate (transitional)", R["projects/bg"].get("back_agents") == {k: BG_ALL[k] for k in ("s-bg-sweep", "s-bg-watch", "s-bg-wrap", "s-bg-old")}, R["projects/bg"].get("back_agents"))
check("registry: the nested inline form reads the same", R["projects/bgi"].get("agents") == {"s-bgi-main": "talks", "s-bgi-two": "does y, z", "s-bgi-night": "runs at night, Oliver's", "s-bgi-day": "plain"} and R["projects/bgi"].get("back_agents") == {"s-bgi-night": "runs at night, Oliver's", "s-bgi-day": "plain"}, R["projects/bgi"])
check("registry: a one-level agents: page is unchanged and has no back_agents", R["projects/hub"].get("agents") == {"s-hub-main": "upgrades, the curator", "s-hub-docs": "writes the docs"} and "back_agents" not in R["projects/hub"] and "back_agents" not in R["projects/legacy"], (R["projects/hub"], R["projects/legacy"]))
check("split_agents: anything that is not a map is nothing", p.split_agents("") == ({}, {}) and p.split_agents(None) == ({}, {}) and p.split_agents({"background": ""}) == ({}, {}), p.split_agents({"background": ""}))
fmpage("projects/quoted.md", "type: project\ntitle: Q\ndisplay-name: s-q\nagents:\n  s-q-main: 'chores and forms (a checklist); Oliver''s contact'\n  s-q-two: \"says \\\"hi\\\" twice\"\n  s-q-wrap: 'a quoted value, Oliver''s, that\n    wraps onto a second line'")
real_reg2 = p.REG; p.REG = str(T / "registry-test2.json"); p.cmd_registry(quiet=True); R2 = json.loads(open(p.REG).read())["pages"]; p.REG = real_reg2
check("registry: a page with only `display-name: x-proj` has that keeper; a page with only the old `steward: x-proj` line has none", who("projects/dn-new") == ("x-proj", "name") and who("projects/dn-old") == ("", None), (who("projects/dn-new"), who("projects/dn-old")))
check("registry: …the agents, back_agents and status are read as ever; no `display-name` key leaks into the entry", all(R["projects/dn-new"].get(k) == R["projects/dn-old"].get(k) for k in ("agents", "back_agents", "status")) and R["projects/dn-new"]["agents"] == {"x-proj-main": "talks", "x-proj-eng": "builds"} and "display-name" not in R["projects/dn-new"], R["projects/dn-new"])
check("registry: a page carrying both keys prefers `display-name:`, whichever line comes first", who("projects/dn-both") == ("x-new", "name") and who("projects/dn-both2") == ("y-new", "name"), (who("projects/dn-both"), who("projects/dn-both2")))
check("registry: a sub-page of a `display-name:` hub is inherited from it; a quoted value reads unquoted", who("projects/dn-new/sub") == ("x-proj", "inherited") and who("projects/dn-quoted") == ("x-q", "name"), (who("projects/dn-new/sub"), who("projects/dn-quoted")))
_fms = p.read_pages()[0]
check("keeper_of: display-name only; a leftover `steward:` line names nobody", p.keeper_of("projects/dn-new", _fms) == ("x-proj", "name") and p.keeper_of("projects/dn-old", _fms) == ("", "")
      and p.keeper_of("projects/dn-both", _fms) == ("x-new", "name") and p.keeper_of("projects/hub", _fms) == ("s-hub", "name"), p.keeper_of("projects/dn-both", _fms))
check("frontmatter: a hyphenated key parses as a key, and a plain key after it still does", p.frontmatter(str(T / "brain/projects/dn-both.md")).get("display-name") == "x-new" and p.frontmatter(str(T / "brain/projects/dn-both.md")).get("status") == "active")
check("registry: a quoted mandate reads without its quotes, a doubled apostrophe as one", R2["projects/quoted"].get("agents") == {"s-q-main": "chores and forms (a checklist); Oliver's contact", "s-q-two": 'says "hi" twice', "s-q-wrap": "a quoted value, Oliver's, that wraps onto a second line"}, R2["projects/quoted"].get("agents"))
(T / "brain/projects/quoted.md").unlink()
check("registry: a top-level page that names nobody has no keeper", who("ops/alone") == ("", None), who("ops/alone"))
# ---- 1c. agent-listed: no agent before it is listed, read from the project record (a project the record has no entry for yet: from its page's lines)
# The record's entries are fixtures here (`record`); a page beside one lists less than its entry, so a check passes only when the record is what answers.
RECP = T / "store/project-record.json"; _rec_orig = RECP.read_text(encoding="utf-8") if RECP.exists() else None
def record(ents, pending=None, raw=None):
    doc = {"schema": 1, "ids": {i: e["page"] for i, e in ents.items() if e.get("page")}, "projects_schema": 1, "projects": ents}
    if pending: doc["pending_agents"] = pending
    new = str(RECP) + ".new"; open(new, "w", encoding="utf-8").write(raw if raw is not None else json.dumps(doc)); os.replace(new, RECP)     # a new file each time: the reader's cache keys on the inode
ag = lambda mandate, front=True: {"front": front, "mandate_line": mandate}
E = {"prj_0000d00d": {"name": "r-a", "title": "Ra", "page": "projects/ra", "agents": {"r-a-main": ag("does the main work"), "r-a-docs": ag("writes the docs, Oliver's"), "r-a-sweep": ag("sweeps the inbox", False)}},
     "prj_0000cafe": {"name": "r-f", "title": "Rf", "page": "projects/rf", "agents": {"r-f-press": ag("drafts and ships the newsletters, keeps the mailing list, and answers the subscribers"), "r-f-short": ag("one line")}},
     "prj_0000c0de": {"name": "r-a-x", "title": "Rdeep", "page": "projects/rdeep", "agents": {"r-a-x-main": ag("deeper")}},
     "prj_0000f00d": {"name": "r-gone", "title": "Rgone", "page": "projects/rgone", "status": "archived", "agents": {"r-gone-main": ag("left")}},
     "prj_0000b001": {"name": "r-w", "title": "Rw", "page": "projects/rw", "agents": {"r-w-main": ag("talks")}},
     "prj_deadbeef": {"name": "r-p", "title": "Rp", "agents": {"r-p-main": ag("a project with no page")}},
     "prj_0000e1e1": {"name": "r-mv", "title": "Rmv", "page": "projects/rmv-new", "former_keys": ["projects/rmv-old"], "agents": {"r-mv-main": ag("moved")}},
     "prj_0000e2e2": {"name": "r-m", "title": "Rm", "page": "projects/rm", "agents": {}},
     "prj_0000e3e3": {"name": "r-m", "title": "Rm host", "page": "ops/rm-host", "agents": {}},
     "prj_0000e4e4": {"name": "r-q", "title": "Rq", "page": "projects/rq", "agents": {}},
     "prj_0000e5e5": {"name": "r-q", "title": "Rq lists", "page": "ops/rq-lists", "agents": {"r-q-main": ag("the one that lists")}}}
PEND = {"prj_0000b001": {"r-w-owed": {"front": True, "role": "owed", "mandate_line": "still owed to the page", "by": "a-label", "at": "2026-01-01T00:00:00Z"}}}
fmpage("projects/ra.md", "type: project\ntitle: Ra\ndisplay-name: r-a\nagents:\n  r-a-main: the page's own line")        # the page lists less than the record: no r-a-docs, no r-a-sweep
fmpage("projects/rw.md", "type: project\ntitle: Rw\ndisplay-name: r-w\nagents:\n  r-w-main: the page's own line\n  r-w-ghost: only the page lists it\n  r-w-owed: the page lists it, the record says it is owed")
fmpage("projects/rmv-old.md", "type: project\ntitle: Rmv old\ndisplay-name: r-mv\nagents:\n  r-mv-stale: the page at the key the project left")
fmpage("projects/rgone.md", "type: project\ntitle: Rgone\ndisplay-name: r-gone\nagents:\n  r-gone-main: the page still lists it")      # the page lists it, the record has archived the project
fmpage("projects/noname.md", "type: project\ntitle: No name\nagents:\n  noname-main: a page with no name line")
fmpage("projects/other.md", "type: project\ntitle: Other\ndisplay-name: s-hub")
fmpage("ops/hubhost.md", "type: note\ntitle: Host\ndisplay-name: s-hub")
fmpage("projects/deeper.md", "type: project\ntitle: Deeper\ndisplay-name: s-hub-main-x")
fmpage("projects/gone.md", "type: project\ntitle: Gone\ndisplay-name: s-gone\nstatus: completed")
record(E, PEND)
al = p.agent_listed
check("agent-listed: a listed agent passes with its mandate from the record", al("r-a-main") == (0, "listed on projects/ra: does the main work"), al("r-a-main"))
check("agent-listed: an agent the record lists and its page's agents: block lacks passes", al("r-a-docs") == (0, "listed on projects/ra: writes the docs, Oliver's"), al("r-a-docs"))
check("agent-listed: a name is matched case-folded, as the register does", al("R-A-Docs") == (0, "listed on projects/ra: writes the docs, Oliver's"), al("R-A-Docs"))
check("agent-listed: a folded mandate prints whole (a project with no page of this store read, its key from the record)", al("r-f-press") == (0, "listed on projects/rf: drafts and ships the newsletters, keeps the mailing list, and answers the subscribers"), al("r-f-press"))
c, line = al("r-a-new")
check("agent-listed: an unlisted name is refused, naming the project record, the project and the line to add, in one line", c == 3 and "of projects/ra " in line and "in the project record" in line and "(the project named r-a)" in line and "`r-a-new: <mandate>`" in line and "\n" not in line, (c, line))
check("agent-listed: a background agent passes with its mandate (sala spawns and renames it)", al("r-a-sweep") == (0, "listed on projects/ra: sweeps the inbox"), al("r-a-sweep"))
check("agent-listed: the reserved background key is no agent's name", al("r-a-background")[0] == 3, al("r-a-background"))
check("agent-listed: the project's own name is no agent", al("r-a") == (0, "the name of projects/ra: not an agent"), al("r-a"))
check("agent-listed: a name that extends another's is no agent of it", al("r-a-x") == (0, "the name of projects/rdeep: not an agent"), al("r-a-x"))
check("agent-listed: the longest name prefix decides", al("r-a-x-docs")[0] == 3 and "of projects/rdeep " in al("r-a-x-docs")[1] and al("r-a-x-main") == (0, "listed on projects/rdeep: deeper"), (al("r-a-x-docs"), al("r-a-x-main")))
check("agent-listed: a name under no project is free", al("someone-else") == (0, "no project page for this name: nothing to check") and al("r-abba")[0] == 0 and al("r-a-")[0] == 0, (al("someone-else"), al("r-abba"), al("r-a-")))
check("agent-listed: an archived project names no project", al("r-gone-main") == (0, "no project page for this name: nothing to check") and al("r-gone")[0] == 0 and "the name of" not in al("r-gone")[1], (al("r-gone-main"), al("r-gone")))
check("agent-listed: a page with no name line, and no entry, is no project", al("noname-extra") == (0, "no project page for this name: nothing to check") and al("noname-main")[0] == 0, (al("noname-extra"), al("noname-main")))
check("agent-listed: a project with no page at all is read from the record, and an unlisted name there is refused by its id", al("r-p-main") == (0, "listed on prj_deadbeef: a project with no page") and al("r-p-new")[0] == 3 and "of prj_deadbeef " in al("r-p-new")[1], (al("r-p-main"), al("r-p-new")))
check("agent-listed: the page a project left is no project: its agents: block answers nothing", al("r-mv-main") == (0, "listed on projects/rmv-new: moved") and al("r-mv-stale")[0] == 3 and "of projects/rmv-new " in al("r-mv-stale")[1], (al("r-mv-main"), al("r-mv-stale")))
check("agent-listed: the record wins over the page: a name only the page lists is refused, the record's mandate is the one printed", al("r-w-ghost")[0] == 3 and al("r-w-main") == (0, "listed on projects/rw: talks"), (al("r-w-ghost"), al("r-w-main")))
check("agent-listed: an agent whose page line is still owed (the record's pending list) is not listed, though its page lists it", al("r-w-owed")[0] == 3 and "of projects/rw " in al("r-w-owed")[1], al("r-w-owed"))
check("agent-listed: with no agents anywhere, the line belongs on the project whose key the name ends in, a projects/ page before another", al("r-m-main")[0] == 3 and "of projects/rm " in al("r-m-main")[1] and "(the project named r-m)" in al("r-m-main")[1], al("r-m-main"))
check("agent-listed: the line belongs on the project that already lists agents, before the one a projects/ key and its name would favor", al("r-q-new")[0] == 3 and "of ops/rq-lists " in al("r-q-new")[1] and al("r-q-main") == (0, "listed on ops/rq-lists: the one that lists"), (al("r-q-new"), al("r-q-main")))
# a project the record has no entry for yet: the entry the register derives from its page's lines, beside the projects the record holds
check("agent-listed: an unmigrated project's page lines answer (the old `session:` key names the project, an inline map counts)", fmpage("projects/legacy.md", "type: project\ntitle: Legacy\nsession: old-name\nagents: {old-name-one: \"does x\"}") or al("old-name-one") == (0, "listed on projects/legacy: does x"), al("old-name-one"))
check("agent-listed: an unmigrated project's unlisted name is refused, naming its page", al("s-hub-new")[0] == 3 and "of projects/hub " in al("s-hub-new")[1] and "(the project named s-hub)" in al("s-hub-new")[1] and al("s-bg-new")[0] == 3 and "back_agents" not in al("s-bg-new")[1], (al("s-hub-new"), al("s-bg-new")))
check("agent-listed: a name an unmigrated page extends is no agent of it, and the longest prefix decides", al("s-hub-main-x")[0] == 0 and "the name of projects/deeper" in al("s-hub-main-x")[1] and al("s-hub-main-x-docs")[0] == 3 and "of projects/deeper " in al("s-hub-main-x-docs")[1], (al("s-hub-main-x"), al("s-hub-main-x-docs")))
check("agent-listed: an unmigrated project's background agents pass, and the reserved key is no name", al("s-bg-sweep") == (0, "listed on projects/bg: sweeps the inbox, Oliver's") and al("s-bgi-night")[0] == 0 and al("s-bg-background")[0] == 3, (al("s-bg-sweep"), al("s-bgi-night"), al("s-bg-background")))
check("agent-listed: a completed page the record has no entry for names no project", al("s-gone-main")[0] == 0 and "no project" in al("s-gone-main")[1], al("s-gone-main"))
check("agent-listed: a `display-name:` page makes its project's agents listed and its name no agent", al("x-proj-main")[0] == 0 and al("x-proj-main")[1].startswith("listed on projects/dn-") and al("x-proj")[1].startswith("the name of ")
      and al("x-new-main")[0] == 3 and "of projects/dn-both " in al("x-new-main")[1] and al("q-old-main") == (0, "no project page for this name: nothing to check"), (al("x-proj-main"), al("x-proj"), al("x-new-main"), al("q-old-main")))
(T / "brain/projects/hub.md").write_text((T / "brain/projects/hub.md").read_text().replace("agents:\n  s-hub-main: 'upgrades, the curator'\n  s-hub-docs: writes the docs\n", ""), encoding="utf-8")
check("agent-listed: an unmigrated project with no agents: line anywhere, the page named is the one the project's name ends in", al("s-hub-main")[0] == 3 and "of projects/hub " in al("s-hub-main")[1], al("s-hub-main"))
fmpage("projects/fresh.md", "type: project\ntitle: Fresh\ndisplay-name: s-fresh\nagents:\n  s-fresh-main: the contact")
check("agent-listed: a line written a moment ago counts for a project with no entry (the files, not the registry)", "projects/fresh" not in R and al("s-fresh-main") == (0, "listed on projects/fresh: the contact"), al("s-fresh-main"))
RECP.unlink()
check("agent-listed: with no record file the pages answer, as before the record existed", al("s-fresh-main") == (0, "listed on projects/fresh: the contact") and al("s-fresh-docs")[0] == 3 and al("r-a-main") == (0, "listed on projects/ra: the page's own line") and al("r-a-docs")[0] == 3, (al("s-fresh-main"), al("s-fresh-docs"), al("r-a-main"), al("r-a-docs")))
record(E, PEND)
run = lambda n: subprocess.run([sys.executable, os.path.join(STACK, "stackshot/projects/pages.py"), "agent-listed", n], capture_output=True, text=True, env=os.environ)
r3, r0, r1 = run("r-a-new"), run("r-a-docs"), run("")
check("agent-listed: the command exits 3 / 0 / 1 with one line", (r3.returncode, r0.returncode, r1.returncode) == (3, 0, 1) and r3.stdout.count("\n") == 1 and r0.stdout.strip() == "listed on projects/ra: writes the docs, Oliver's", (r3.returncode, r3.stdout, r0.returncode, r0.stdout, r1.returncode))
record(E, raw="{ this is not json")
bad = al("r-a-docs"); rb = run("r-a-docs")
check("agent-listed: a record that cannot be read is 'cannot tell' (2), in one line, for every name and never a refusal", bad[0] == 2 and "project record" in bad[1] and "\n" not in bad[1] and al("someone-else")[0] == 2 and rb.returncode == 2 and rb.stdout.count("\n") == 1, (bad, rb.returncode, rb.stdout))
record(E, raw=json.dumps({"schema": 1, "ids": {}, "projects_schema": 99, "projects": {}}))
check("agent-listed: …also a record of a schema this code does not read", al("r-a-docs")[0] == 2, al("r-a-docs"))
if _rec_orig is None: RECP.unlink()
else: RECP.write_text(_rec_orig, encoding="utf-8")
for x in ("projects/other.md", "ops/hubhost.md", "projects/deeper.md", "projects/gone.md", "projects/fresh.md", "projects/ra.md", "projects/rw.md", "projects/rmv-old.md", "projects/rgone.md", "projects/noname.md"): (T / "brain" / x).unlink()
for d in ("projects/hub", "projects/legacy"): shutil.rmtree(T / "brain" / d)
for x in ("projects/hub.md", "projects/legacy.md", "ops/alone.md", "projects/folded.md", "projects/bg.md", "projects/bgi.md"): (T / "brain" / x).unlink()

# ---- 2. the excerpt
full = p.current_state("projects/alpha", 20000); lines = full.split("\n")
check("whole when it fits", "not shown" not in full and full.rstrip().endswith("Point 26:** " + ("状態の一行 state words here " * 9).strip() + "."), full[-120:])
cut = p.current_state("projects/alpha", 3000); body, note = cut.rsplit("\n", 1)
check("cut at a line", all(ln in lines for ln in body.split("\n")) and len(body.encode()) <= 3000, body[-200:])
kept = len([ln for ln in body.split("\n") if ln.startswith("- ")])
check("the note counts what is left", re.match(rf"… \({26 - kept} more line\(s\), \d+\.\d KB, not shown; the whole page: ", note) is not None, note)
one = p.excerpts(["projects/beta"], p.INJECT); check("a small page is shown whole", "- small state." in one and "not shown" not in one, one)
solo = p.excerpts(["projects/alpha"], p.INJECT); check("one page alone gets the whole budget", "Point 26" in solo and "not shown" not in solo, solo[-200:])
two = p.excerpts(["projects/alpha", "projects/gamma"], p.INJECT)
parts = two.split("### projects/gamma"); check("two pages share it evenly", len(parts) == 2 and all(3800 < len(x.encode()) < 4900 for x in parts), [len(x.encode()) for x in parts])
check("the budget holds", len(two.encode()) < p.INJECT + 400, len(two.encode()))

# ---- 3. what the turn did
def transcript(prompt, tools, final="done", lead=""):
    f = T / f"t{len(ran)}.jsonl"; ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - 60))
    rows = [{"type": "user", "timestamp": ts, "message": {"content": prompt}}]
    if lead: rows.append({"type": "assistant", "message": {"content": [{"type": "text", "text": lead}]}})
    for n, inp in tools:
        rows.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": n, "input": inp}]}})
        rows.append({"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}})
    rows.append({"type": "assistant", "message": {"content": [{"type": "text", "text": final}]}})
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n"); return str(f)
NOTICE = '[anchor] Slack #x: new message from Dana: "hi" → https://u/x'
PEER = '<cross-session-message from="uds:/x">a proposal</cross-session-message>'
GB, NO, ST = "mcp__claude_ai_GBrain-main__", "mcp__claude_ai_Notion__", "mcp__claude_ai_Stackshot__"
act = lambda prompt, tools: p.turn_activity(transcript(prompt, tools))
a = act(NOTICE, []); check("a notice alone is not a write", not a["writes"] and a["inbound"], a)
a = act(PEER, []); check("a peer message alone is not a write", not a["writes"] and a["inbound"], a)
a = act(NOTICE, [(NO + "notion-fetch", {})]); check("a notice plus a read: no write", not a["writes"] and a["why"] == [], a)
a = act(NOTICE, [(GB + "add_timeline_entry", {})]); check("a notice plus a timeline line: ask", a["writes"] and a["why"] == ["gbrain add_timeline_entry"], a)
a = act(PEER, [("SendMessage", {})]); check("a peer message plus a reply: ask", a["writes"], a)
a = act(NOTICE, [(ST + "update", {})]); check("a notice plus a board write: ask", a["writes"], a)
a = act("please update the page", [(GB + "put_page", {})]); check("Oliver's own turn: a page write alone does not ask", not a["writes"] and not a["inbound"], a)
a = act("post it", [(NO + "notion-update-page", {})]); check("Oliver's own turn: a connector write asks", a["writes"], a)
a = act(NOTICE, [(GB + "edit_page", {})]); check("a notice plus an edit_page: ask", a["writes"] and a["why"] == ["gbrain edit_page"], a)
a = act("look it up", [(GB + "search", {}), (ST + "brief", {})]); check("gbrain and board reads are nothing", not a["writes"] and a["why"] == [], a)

# ---- 4. the Stop hook asks nothing about pages (the end-of-turn page question is retired; a write-up mod covers the turn's end). The page debt is still recorded, said at every prompt while it is owed, and settled by a Current-state edit.
def stop(sid, tp):
    r = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/projects/pages.py"), "check"], input=json.dumps({"session_id": sid, "transcript_path": tp}),
                       capture_output=True, text=True, env={**os.environ, "BOARD_CHECK_MODE": "off"})
    return r.returncode, r.stderr
def nnag(sid):
    r = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/projects/pages.py"), "nag"], input=json.dumps({"session_id": sid}), capture_output=True, text=True)
    return r.stdout
TL = [(GB + "add_timeline_entry", {})]
slog = lambda: (T / "touch/keeper-log.jsonl").read_text(encoding="utf-8") if (T / "touch/keeper-log.jsonl").exists() else ""
rc, err = stop(S, transcript(NOTICE, TL))
check("stop: a keeper's notice plus a timeline line asks no page question (retired)", rc == 0 and err == "", (rc, err[:300]))
out = nnag(S); check("stop: …and keeps none for the next prompt", "About your last turn" not in out and "Current state" not in out and out.strip() == "", out[:300])
rc, err = stop(S, transcript(NOTICE, TL, "Done.\nPage: no change, this turn only relayed a display fix")); check("stop: a `Page:` line is simply text now", rc == 0 and err == "", err[:200])
rc, err = stop(S, transcript("look it up", [(NO + "notion-fetch", {})])); out = nnag(S)
check("stop: a keeper's turn that only read is not reminded at the next prompt (the reminder went with the question)", rc == 0 and "read something new" not in out and out.strip() == "", (rc, out[:300]))
check("stop: nothing about pages is logged at Stop", not any(json.loads(l)["kind"] in ("block", "note", "verdict", "reminder") for l in slog().splitlines()), slog()[-300:])
# the page debt (a board write's page, per page): recorded by touch, said by nag at every prompt while owed, never at Stop
(T / "touch" / f"{S}.json").write_text(json.dumps({"touches": {"projects/alpha": {"ts": int(time.time()), "task": "s9"}}}))
check("debt: a keeper's touched page is owed while its Current state is unedited", [k for k, _ in p.stale_touches(S, strict=True)] == ["projects/alpha"], p.load_state(S))
out = nnag(S)
check("debt: the next prompt says it", "[project-page] board item s9 changed at" in out and "`projects/alpha` has no Current-state edit since" in out, out[:300])
hm9 = p._debt_when(p.load_state(S)["touches"]["projects/alpha"])[1]
check("debt: the first fire carries the item, the time, the missing Current-state edit, how to edit the page and the clear command, in about 450 characters",
      "board item s9 changed at" in out and "has no Current-state edit since (a timeline line does not count)" in out and "commit and push. If no page change is due:" in out
      and "pages.py clear projects/alpha" in out and len(out.strip()) <= 470, (len(out.strip()), out[:600]))
out2 = nnag(S)
check("debt: the second fire of the same debt is the one line `still owed: <page> (<item>, <HH:MM>)`",
      out2.strip() == f"[project-page] still owed: projects/alpha (s9, {hm9})", out2)
check("debt: …and the third is the same line, the debt still owed", nnag(S).strip() == out2.strip() and "projects/alpha" in (p.load_state(S).get("touches") or {}))
# a different debt (the same page, a later change) prints in full again; so does another page
st_ = p.load_state(S); st_["touches"]["projects/alpha"] = {"ts": int(time.time()) + 5, "task": "s9"}; p.save_state(S, st_)
out3 = nnag(S)
check("debt: a later change to the same page is a different debt and is said in full", "board item s9 changed at" in out3 and "still owed" not in out3, out3[:300])
st_ = p.load_state(S); st_["touches"]["projects/gamma"] = {"ts": int(time.time()), "task": "s8"}; p.save_state(S, st_)
out4 = nnag(S)
check("debt: another page's debt is said in full beside the one already shown, which stays a line",
      "board item s8 changed at" in out4 and "`projects/gamma`" in out4 and "still owed: projects/alpha (s9," in out4 and out4.count("board item s9 changed at") == 0, out4[:500])
st_ = p.load_state(S); t_ = st_["touches"]["projects/alpha"]["ts"]; st_["touches"]["projects/alpha"] = {"ts": t_ + 9, "shown": t_, "shown_at": int(time.time()), "task": "s9"}; p.save_state(S, st_)
out5 = nnag(S)
check("debt: a mark left from an earlier change does not make a different change a repeat", "board item s9 changed at" in out5 and "still owed: projects/alpha" not in out5, out5[:300])
st_ = p.load_state(S); st_["touches"].pop("projects/gamma", None); t_ = st_["touches"]["projects/alpha"]["ts"]; st_["touches"]["projects/alpha"] = {"ts": t_, "shown": t_, "shown_at": int(time.time()) - p.REPEAT_SECONDS - 5, "task": "s9"}; p.save_state(S, st_)
out6 = nnag(S)
check("debt: a debt last said in full over 2 hours ago is said in full once more, then a line again", "board item s9 changed at" in out6 and "still owed" not in out6 and nnag(S).strip().startswith("[project-page] still owed: projects/alpha"), out6[:200])
check("debt: the window is 2 hours", p.REPEAT_SECONDS == 7200)
_n0 = 1_800_000_000
check("debt: the window's edge: a line at 7199 s, the full text at exactly 7200 s", p._repeat_ok({"shown_at": _n0}, _n0 + 7199) is True and p._repeat_ok({"shown_at": _n0}, _n0 + 7200) is False and p._repeat_ok({"shown_at": _n0}, _n0) is True)
check("debt: a shown_at in the future (the clock went back) is not a repeat", p._repeat_ok({"shown_at": _n0 + 5}, _n0) is False)
check("debt: a garbled shown_at (text, list, dict, none, inf, nan) never raises and is said in full",
      all(p._repeat_ok({"shown_at": bad}, _n0) is False for bad in ("abc", "", [1], {"a": 1}, None, float("inf"), float("-inf"), float("nan"), "inf", "nan")) and p._repeat_ok({}, _n0) is False)
st_ = p.load_state(S); st_["touches"].pop("projects/gamma", None); t_ = st_["touches"]["projects/alpha"]["ts"]
st_["touches"]["projects/alpha"] = {"ts": t_, "shown": t_, "shown_at": [1, 2], "task": "s9"}; p.save_state(S, st_)
out7 = nnag(S)
check("debt: a garbled shown_at in the state does not crash the nag: the debt is said in full", "board item s9 changed at" in out7 and "Traceback" not in out7, out7[:200])
# the mark is written only to the entry the debt was said for: a debt whose stamp differs from the stored entry's gets no mark
import io as _io, contextlib as _cl
st_ = p.load_state(S); t_ = int(time.time()); st_["touches"]["projects/alpha"] = {"ts": t_, "task": "s9"}; p.save_state(S, st_)
_saved_stale = p.stale_touches; _saved_in = sys.stdin
p.stale_touches = lambda sid, strict=False, skipped=None: [("projects/alpha", {"ts": t_ - 5, "task": "s9"})]
sys.stdin = _io.StringIO(json.dumps({"session_id": S}))
try:
    with _cl.redirect_stdout(_io.StringIO()): p.cmd_nag()
finally: p.stale_touches = _saved_stale; sys.stdin = _saved_in
check("debt: the mark is not written to a stored entry of another change", "shown" not in p.load_state(S)["touches"]["projects/alpha"], p.load_state(S))
st_ = p.load_state(S); st_["touches"]["projects/alpha"] = {"ts": t_, "task": "s9"}; p.save_state(S, st_)
st_ = p.load_state(S); st_["touches"].pop("projects/gamma", None); st_["touches"]["projects/alpha"] = {"ts": int(time.time()), "task": "s9"}; p.save_state(S, st_)
rc, err = stop(S, transcript(NOTICE, TL))
check("debt: the Stop hook neither says it nor holds the turn, and the debt stays", rc == 0 and err == "" and "projects/alpha" in (p.load_state(S).get("touches") or {}), (rc, err[:300], p.load_state(S)))
f = T / "brain/projects/alpha.md"; f.write_text(f.read_text(encoding="utf-8").replace("- **Point 1:**", "- **Point 1 (changed):**"), encoding="utf-8")
g = T / "brain/projects/gamma.md"; g.write_text(g.read_text(encoding="utf-8").replace("- **Point 2:**", "- **Point 2 (changed):**"), encoding="utf-8")
check("debt: a Current-state edit settles it", p.stale_touches(S, strict=True) == [] and not p.load_state(S).get("touches"), p.load_state(S))
check("debt: …and the next prompt says nothing more", "[project-page] board item" not in nnag(S))

# ---- 4b. a keeper that is spawned: no name at its session start, its pages at the first prompt after
def hook(cmd, sid):
    r = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/projects/pages.py"), cmd], input=json.dumps({"session_id": sid, "source": "startup"}), capture_output=True, text=True)
    return r.returncode, r.stdout
N = "44444444-4444-4444-8444-444444444444"
rc, out = hook("keeper", N); check("session start without a name: nothing shown", rc == 0 and out.strip() == "", out[:200])
rc, out = hook("nag", N); check("…and nothing at a prompt while it has no name", "[project-page] You" not in out, out[:200])
fs = T / "fleet/a/sessions.json"; d = json.loads(fs.read_text()); d[N] = {"name": "home-beta", "machine": "a"}; fs.write_text(json.dumps(d))
rc, out = hook("nag", N); check("named since: its pages at the next prompt (plain flavor: the pages checkout, no gbrain)", "[project-page] You (home-beta) keep 1 page(s)" in out
      and "small state" in out and "gbrain" not in out and "add_timeline_entry" not in out, out[:300])
rc, out = hook("nag", N); check("…once", "[project-page] You" not in out, out[:200])
rc, out = hook("nag", S); check("a session started before the marker existed waits for its next session start", "[project-page] You" not in out, out[:200])
rc, out = hook("keeper", S); check("session start with a name: shown there", '"additionalContext"' in out and "projects/alpha" in out, out[:200])
rc, out = hook("nag", S); check("…and not again at the prompt", "[project-page] You" not in out, out[:200])
rc, out2 = hook("steward", S); check("compat dropped: `pages.py steward` is no subcommand (usage, exit 1, nothing injected)", rc == 1 and '"additionalContext"' not in out2 and "projects/alpha" not in out2, (rc, out2[:200]))
check("…`steward_pages` is gone, and the state marks and the log carry the keeper's name", not hasattr(p, "steward_pages") and p.shown_path("x").endswith("x.shown") and p.KEEPER_LOG.endswith("keeper-log.jsonl") and not any(f.name.endswith(".steward") or f.name == "steward-log.jsonl" for f in (T / "touch").iterdir()), p.shown_path("x"))
d.pop(N); fs.write_text(json.dumps(d))

# ---- 5. the server's ledger
from stackshot.web import server
from stackshot.service import client_reads as client_reads_svc
from stackshot.web import page_debts as _pdebts
from stackshot.web import publish as _web_publish
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.tools import text as _wt_text
from stackshot.web.routes import client_api as _rt_client
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
check("server: a keeper's debt is strict, an agent's is not", _pdebts._strict(S) and _pdebts._strict(B) and not _pdebts._strict(A))
_pdebts._owed_save({"projects/beta": {B: {"ts": time.time() - 30, "item": "s1"}, A: {"ts": time.time() - 30, "item": "s2"}}})
time.sleep(1.1); b = T / "brain/projects/beta.md"
b.write_text(b.read_text(encoding="utf-8") + "- **2026-01-02** | t — a timeline line\n", encoding="utf-8")
d = _pdebts._owed_settle().get("projects/beta", {})
check("a timeline line settles the agent's debt, not the keeper's", B in d and A not in d, d)
n = _pdebts._nag(B); check("the nag says why, to a page keeper", "As a page keeper" in n and "not what is true now" in n, n)
check("…and not to a session that keeps no page", "As a page keeper" not in _pdebts._nag(A), _pdebts._nag(A))
n = _pdebts._nag(A); check("the pages-owed line marks a keeper's debt as settled only by Current state", "pages owed:" in n and "a keeper: settles on a Current-state edit" in n, n)
_pdebts._owed_save({"projects/beta": {B: {"ts": time.time() - 30, "item": "s1"}, A: {"ts": time.time() + 3600, "item": "s2"}}})
n = _pdebts._nag(B); check("…and leaves a non-keeper's debt plain", "pages owed:" in n and "a keeper:" not in n, n)
_pdebts._owed_save({"projects/beta": {B: {"ts": time.time() - 30, "item": "s1"}}})
b.write_text(b.read_text(encoding="utf-8").replace("- small state.", "- small state, now different."), encoding="utf-8")
check("a Current-state edit settles it", B not in _pdebts._owed_settle().get("projects/beta", {}))

# ---- 5b. `pages.py clear <key>` drops the caller's own debt only (a clear once wiped a keeper's
# reminder); another writer's is named and kept; --force drops every writer's, as clear did before
LEDGER = _pdebts._owed_path(); kept_ledger = LEDGER.read_text(encoding="utf-8") if LEDGER.exists() else None
def clear(*args, sid=S):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_SESSION_ID"}
    if sid: env["CLAUDE_CODE_SESSION_ID"] = sid
    r = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/projects/pages.py"), "clear", *args], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout
def owe(sids, ledger):
    for x in (S, A, B): p.save_state(x, {})
    for x in sids: (T / "touch" / f"{x}.json").write_text(json.dumps({"touches": {"projects/delta": {"ts": int(time.time()), "task": "s11"}}}))
    LEDGER.write_text(json.dumps(ledger), encoding="utf-8")
touched = lambda x: "projects/delta" in (p.load_state(x).get("touches") or {})
led = lambda: json.loads(LEDGER.read_text(encoding="utf-8"))
E = lambda: {"ts": time.time(), "item": "s11"}
owe([S], {"projects/delta": {S: E()}, "projects/beta": {B: E()}})
rc, out = clear("delta")
check("clear: only the caller owes → its reminder and its server entry go, exit 0", rc == 0 and not touched(S) and "projects/delta" not in led()
      and "cleared projects/delta for you, work-osprey (11111111): 1 session state(s), 1 server owed entry" in out and "Kept" not in out, (rc, out, led()))
check("clear: …and another page's debt is untouched", B in led().get("projects/beta", {}), led())
owe([S, B], {"projects/delta": {S: E(), B: E(), "work-osprey-main": E()}, "delta": {"work-osprey": E()}})
rc, out = clear("projects/delta")
check("clear: another writer owes → refused (exit 3), the caller's own still cleared (its id and its name, either spelling of the key)",
      rc == 3 and not touched(S) and S not in led().get("projects/delta", {}) and "delta" not in led() and "2 server owed entries" in out, (rc, out, led()))
check("clear: …the other writers' debts are kept", touched(B) and set(led().get("projects/delta", {})) == {B, "work-osprey-main"}, (p.load_state(B), led()))
check("clear: …and named, with where each is kept and how to force it",
      "Kept, not yours: projects/delta is still owed by home-beta (33333333) (session reminder, server owed entry); work-osprey-main (server owed entry)" in out
      and "pages.py clear projects/delta --force` clears every writer's" in out, out)
rc, out = clear("projects/delta", "--force", sid=B)
check("clear --force: every writer's goes, exit 0", rc == 0 and not touched(B) and "projects/delta" not in led() and "for every writer (--force)" in out and "Kept" not in out, (rc, out, led()))
owe([B], {"projects/delta": {B: E()}})
rc, out = clear("projects/delta", sid="")
check("clear: run outside a session → nothing counts as yours, every debt kept and named", rc == 3 and touched(B) and B in led().get("projects/delta", {})
      and "CLAUDE_CODE_SESSION_ID is not set" in out and "home-beta (33333333)" in out, (rc, out))
owe([B], {"projects/delta": 1700000000})
rc, out = clear("projects/delta")
check("clear: a server entry that names no writer is kept while another writer owes, and the reply says why", rc == 3 and led().get("projects/delta") == 1700000000
      and "names no writer, so it cannot be split" in out, (rc, out, led()))
owe([S], {"projects/delta": 1700000000})
rc, out = clear("projects/delta")
check("clear: …and goes when nobody else owes", rc == 0 and "projects/delta" not in led() and not touched(S), (rc, out, led()))
rc, _ = clear(); check("clear: no key → usage, exit 1", rc == 1)
r = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/projects/pages.py"), "clear"], capture_output=True, text=True)
USAGE = "clear <key> [--force] [--name=<session name>] [--id=<permanent id>]..."
check("clear: the usage line lists --name= and --id=", USAGE in r.stderr, r.stderr)
r = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/projects/pages.py"), "help"], capture_output=True, text=True)      # a word it does not know prints the text at the top
check("clear: …and so does the text at the top of pages.py", USAGE in r.stdout, r.stdout[:200])

# ---- 5c. two boxes: the sessions' box (its own state and reminders, [release] deploy_ssh naming the server host) and the server host (this fixture's
# state, where the owed list is), with a fake `ssh` between them (tests/_twobox.py: nothing connects anywhere)
import contextlib, fcntl, io, shlex, socket
import _twobox
tb = _twobox.TwoBoxes(T, STACK, T / "stackshot.toml"); tb.client_config()
K = "projects/delta"
def two(client_sids, ledger):
    for x in (S, A, B): p.save_state(x, {}); (tb.touch / f"{x}.json").unlink(missing_ok=True)
    for x in client_sids: tb.owe(K, x)
    LEDGER.write_text(json.dumps(ledger), encoding="utf-8")
two([S], {K: {S: E()}, "projects/beta": {B: E()}})
rc, out, calls = tb.clear("delta", sid=S)
check("two boxes: the reminder here and the caller's entry in the server's list both go, exit 0", rc == 0 and not tb.reminded(K, S) and K not in led() and B in led().get("projects/beta", {}), (rc, out, led()))
check("two boxes: …and the server's own result lines are printed under the host's name (nothing else it says)",
      "cleared projects/delta for you, work-osprey (11111111): 1 session state(s) on this box\n" in out and "From the server host (server-host):\n" in out
      and "cleared projects/delta for you, work-osprey (11111111): 0 session state(s), 1 server owed entry\n" in out and "0 server owed" not in out and "welcome" not in out and "Kept" not in out, out)
check("two boxes: …over one ssh call in release.sh's form, into the server's checkout, carrying the caller",
      len(calls) == 1 and calls[0][:5] == ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "server-host"] and len(calls[0]) == 6
      and calls[0][5] == f"cd ~/stackshot && python3 stackshot/projects/pages.py clear-forwarded projects/delta --session {S} --name work-osprey", calls)
two([], {K: {"work-osprey": E()}})
rc, out, _ = tb.clear(K, sid=S)
check("two boxes: an entry kept under the caller's name is the caller's, though the server cannot name the session itself", rc == 0 and K not in led(), (rc, out, led()))
two([S], {K: {S: E(), B: E()}})
rc, out, _ = tb.clear(K, sid=S)
check("two boxes: another writer's server entry is named and kept (exit 3), the caller's still goes", rc == 3 and list(led().get(K, {})) == [B] and not tb.reminded(K, S)
      and "Kept, not yours: projects/delta is still owed by " + B in out and "(server owed entry)" in out, (rc, out, led()))
check("two boxes: …and the command that clears every writer's is this box's, said once", out.count("--force` clears every writer's.") == 1
      and f"`python3 {STACK}/stackshot/projects/pages.py clear projects/delta --force`" in out, out)
two([S, B], {K: {S: E()}})
rc, out, _ = tb.clear(K, sid=S)
check("two boxes: another writer's reminder on this box alone also makes it exit 3, and it is kept", rc == 3 and tb.reminded(K, B) and not tb.reminded(K, S) and K not in led()
      and "Kept on this box, not yours: projects/delta is still owed by home-beta (33333333) (session reminder)" in out and "1 server owed entry" in out, (rc, out, led()))
two([S, B], {K: {S: E(), B: E(), "work-osprey-main": E()}})
rc, out, calls = tb.clear(K, "--force", sid=S)
check("two boxes: --force goes through, every writer's goes on both boxes, exit 0", rc == 0 and not tb.reminded(K, S) and not tb.reminded(K, B) and K not in led()
      and calls[0][5].endswith(" --force") and "for every writer (--force): 0 session state(s), 3 server owed entries" in out and "Kept" not in out, (rc, out, led(), calls))
two([S], {K: {S: E()}})
rc, out, calls = tb.clear(K, sid=S, mode="down")
stays = [x for x in out.split("\n") if x.startswith("The server's entry for ")]
check("two boxes: the server out of reach → the reminder here still goes, the server's entry stays, exit 4", rc == 4 and not tb.reminded(K, S) and S in led().get(K, {}) and len(calls) == 1, (rc, out, led()))
check("two boxes: …one plain line says so, with ssh's reason and the command to run there", len(stays) == 1 and "stays: ssh to server-host failed (ssh: connect to host" in stays[0]
      and "To clear it, run `ssh server-host " in stays[0] and "server owed entr" not in out and "From the server host" not in out, out)
rc, said, _ = tb.run(shlex.split(_twobox.given_command(out)), sid="")
check("two boxes: …and that command, run as printed, clears the caller's entry on the server", rc == 0 and K not in led() and "1 server owed entry" in said, (rc, said, led()))
for what, how, why in (("an older checkout there", {"home": tb.old_home}, "gave no result (exit 1: a checkout there that is older than this one does not take the call)"),
                       ("a run that says nothing", {"mode": "silent"}, "gave no result (exit 0)")):
    two([S], {K: {S: E()}})
    rc, out, _ = tb.clear(K, sid=S, **how)
    check(f"two boxes: {what} is no answer (exit 4, the entry stays, the reminder here goes)", rc == 4 and why in out and S in led().get(K, {}) and not tb.reminded(K, S), (rc, out, led()))
two([S], {K: {S: E()}})
t0 = time.time()
rc, out, _ = tb.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {STACK!r}); from stackshot.projects import pages as p; p.CLEAR_SSH_TIMEOUT = 1; sys.exit(p.main(['pages.py', 'clear', 'delta']))"], sid=S, mode="hang")
check("two boxes: a server that does not answer is given up on at the limit (exit 4)", rc == 4 and "no answer from server-host within 1 s" in out and time.time() - t0 < 20 and S in led().get(K, {}), (rc, out, time.time() - t0))
two([S], {K: {S: E()}})
LEDGER.write_text("not json", encoding="utf-8")
rc, out, _ = tb.clear(K, sid=S)
check("two boxes: a server that cannot rewrite its list says why (exit 4), and the file is left as it was", rc == 4 and "exit 4: clear-forwarded: the owed list could not be rewritten (JSONDecodeError)" in out
      and LEDGER.read_text(encoding="utf-8") == "not json", (rc, out))
for what, name, sets in (("no host named, [server] box = false", "nohost.toml", {"deploy_ssh": "", "box_false": True}),
                         ("a host that starts like an ssh option", "option.toml", {"deploy_ssh": f"-oProxyCommand=touch {T}/pwned-host"}),
                         ("a host word that does not resolve", "word.toml", {"deploy_ssh": "host:server"})):
    two([S], {K: {S: E()}})
    rc, out, calls = tb.clear(K, sid=S, config=tb.client_config(name, **sets))
    check(f"two boxes: {what} → no ssh call, exit 4, the command to run on the server box", rc == 4 and calls == [] and not tb.reminded(K, S) and S in led().get(K, {})
          and "[release] deploy_ssh gives this box no plain host name" in out and f"on the server box: `env CLAUDE_CODE_SESSION_ID={S} python3 ~/stackshot/stackshot/projects/pages.py clear projects/delta --name=work-osprey`" in out
          and not (T / "pwned-host").exists(), (rc, out, calls))
two([S], {K: {S: E()}})
rc, out, calls = tb.clear(K, sid=S, config=tb.client_config("self.toml", deploy_ssh=socket.gethostname()))
check("one box: deploy_ssh naming this box is the server host, so nothing is forwarded and the reply is the one-box one", rc == 0 and calls == [] and "1 session state(s), 0 server owed entries" in out and "on this box" not in out, (rc, out, calls))
two([S], {K: {S: E()}})
rc, out, calls = tb.clear(K, sid=S, server=tb.config("server-misnamed.toml", deploy_ssh=_twobox.HOST))
check("two boxes: the run on the server host never forwards again, even where its own config names another host", rc == 0 and len(calls) == 1 and K not in led(), (rc, out, calls))
for what, key in (("a key with shell words", f"projects/x; touch {T}/pwned-key #"), ("a key with a command substitution", f"projects/$(touch {T}/pwned-key)")):
    rc, out, calls = tb.clear(key, sid=S)
    check(f"two boxes: {what} is not sent (no ssh call, exit 4)", rc == 4 and calls == [] and "not a plain key" in out and not (T / "pwned-key").exists(), (rc, out, calls))
    rc, said, _ = tb.run(shlex.split(_twobox.given_command(out)))
    check(f"two boxes: …and the printed command, run as printed, hands {what} to the server as one word", rc == 0 and f"cleared {key}" in said and not (T / "pwned-key").exists(), (rc, said))
bad = f"x'; touch {T}/pwned-sid; echo '$(touch {T}/pwned-sid)"
rc, out, calls = tb.clear(K, sid=bad)
check("two boxes: a session id with shell words is not sent (no ssh call, exit 4)", rc == 4 and calls == [] and "the session id here is not a plain id" in out and not (T / "pwned-sid").exists(), (rc, out, calls))
rc, said, _ = tb.run(shlex.split(_twobox.given_command(out)))
check("two boxes: …and the printed command quotes it: nothing in it runs", not (T / "pwned-sid").exists() and "cleared projects/delta" in said, (rc, said))
names = T / "fleet/a/sessions.json"; kept_names = names.read_text(encoding="utf-8")
names.write_text(json.dumps({S: {"name": f"w$(touch {T}/pwned-name)", "machine": "a"}}))
two([], {K: {S: E()}})
rc, out, calls = tb.clear(K, sid=S)
check("two boxes: a session name that is not plain is left out of the call, which clears by the id", rc == 0 and len(calls) == 1 and "--name" not in calls[0][5] and "pwned" not in calls[0][5] and K not in led() and not (T / "pwned-name").exists(), (rc, out, calls))
names.write_text(kept_names, encoding="utf-8")
tb.owe(p.NO_PROJECT, S)
rc, out, calls = tb.clear(p.NO_PROJECT, sid=S)
check("two boxes: a debt with no page is only this box's reminder: no ssh call, exit 0", rc == 0 and calls == [] and not tb.reminded(p.NO_PROJECT, S), (rc, out, calls))
said = io.StringIO()
with contextlib.redirect_stdout(said), contextlib.redirect_stderr(said): rc = p.main(["pages.py", "clear-forwarded", K, "--other"])
check("clear-forwarded: a word it does not know is refused (exit 1), nothing cleared", rc == 1 and "not understood" in said.getvalue(), (rc, said.getvalue()))
# the command printed when the server cannot be asked carries the caller's name and permanent id: the server host, which names this session by neither, clears by them
roles = tb.state / "roles.json"; P = "44444444-4444-4444-8444-444444444444"
roles.write_text(json.dumps({"ids": {"work-osprey": P}}), encoding="utf-8")
two([S], {K: {P: E(), "work-osprey": E(), B: E()}})
rc, out, _ = tb.clear(K, sid=S, mode="down")
words = shlex.split(shlex.split(_twobox.given_command(out))[-1]) if rc == 4 else []
check("two boxes: the printed command carries the session's id, name and permanent id, and no --force", words[:1] == ["env"] and f"CLAUDE_CODE_SESSION_ID={S}" in words
      and words[-3:] == [K, "--name=work-osprey", f"--id={P}"] and "--force" not in words, (rc, out, words))
rc, said, _ = tb.run(shlex.split(_twobox.given_command(out)))
check("two boxes: …and run as printed it clears the caller's permanent-id debt, keeps the entry under the plain name (a later session may hold the name) and the other's (exit 3)",
      rc == 3 and sorted(led().get(K, {})) == sorted(["work-osprey", B]) and "1 server owed entry" in said, (rc, said, led()))
two([S], {K: {S: E()}})
rc, out, calls = tb.clear(K, sid=S)
check("two boxes: a plain permanent id goes with the call", rc == 0 and f" --id {P}" in calls[0][-1], (rc, out, calls))
roles.write_text(json.dumps({"ids": {"work-osprey": f"x$(touch {T}/pwned-id)"}}), encoding="utf-8")
two([S], {K: {S: E()}})
rc, out, calls = tb.clear(K, sid=S)
check("two boxes: a permanent id that is not plain is never sent, and the rest of the call goes", rc == 0 and len(calls) == 1 and "--id" not in calls[0][-1] and "pwned" not in calls[0][-1]
      and "--name work-osprey" in calls[0][-1] and K not in led() and not (T / "pwned-id").exists(), (rc, out, calls))
roles.unlink()
# a name with spaces is one word on the far side
names.write_text(json.dumps({S: {"name": "work osprey two", "machine": "a"}}), encoding="utf-8")
two([], {K: {"work osprey two": E()}})
rc, out, calls = tb.clear(K, sid=S)
check("two boxes: a name with spaces is sent as one word, and the debt kept under it goes", rc == 0 and "--name 'work osprey two'" in calls[0][-1] and K not in led(), (rc, out, calls, led()))
# a name that is not plain is not sent: where the server then keeps a debt, the reply says the name was left out and gives the command that clears it
odd = f"osprey's pane: $(touch {T}/pwned-odd)"
names.write_text(json.dumps({S: {"name": odd, "machine": "a"}}), encoding="utf-8")
two([], {K: {odd: E(), B: E()}})
rc, out, calls = tb.clear(K, sid=S)
told = [x for x in out.split("\n") if "is not a plain name, so it was not sent" in x]
check("two boxes: a name that is not plain is not sent, and the reply says so when the server keeps a debt (exit 3)", rc == 3 and "--name" not in calls[0][-1] and "pwned" not in calls[0][-1]
      and set(led().get(K, {})) == {odd, B} and len(told) == 1 and odd in told[0] and out.index(told[0]) < out.index("clears every writer's"), (rc, out, calls, led()))
rc, said, _ = tb.run(shlex.split(told[0][told[0].index("`") + 1:told[0].rindex("`")]) if told else ["false"])
check("two boxes: …and that command, run as printed, clears the debt under the name, keeps the other's and runs nothing in it", rc == 3 and list(led().get(K, {})) == [B] and not (T / "pwned-odd").exists(), (rc, said, led()))
two([], {K: {S: E()}})
rc, out, _ = tb.clear(K, sid=S)
check("two boxes: …and nothing is said of the name when the server kept nothing", rc == 0 and "not a plain name" not in out, (rc, out))
# a name that reads as an option never turns the printed command into --force
names.write_text(json.dumps({S: {"name": "--force", "machine": "a"}}), encoding="utf-8")
two([], {K: {"--force": E(), B: E()}})
rc, out, _ = tb.clear(K, sid=S, mode="down")
rc2, said, _ = tb.run(shlex.split(_twobox.given_command(out)))
check("two boxes: a session named like --force is carried as a name: only its own debt goes", rc == 4 and rc2 == 3 and list(led().get(K, {})) == [B], (rc, rc2, out, said, led()))
names.write_text(kept_names, encoding="utf-8")
# run by hand: the line saying no session could be told is printed once
two([], {K: {B: E()}})
rc, out, _ = tb.clear(K)
check("two boxes: run outside a session, the no-session line is said once and every debt is kept (exit 3)", rc == 3 and out.count("No session could be told") == 1 and B in led().get(K, {}), (rc, out))
# what ssh is given and what is taken from it
two([S], {K: {S: E()}})
rc, out, calls = tb.clear(K, sid=S, typed="the caller's own input\n")
check("two boxes: ssh reads nothing of the caller's standard input", rc == 0 and len(calls) == 1 and tb.read.read_text(encoding="utf-8") == "", (rc, out, tb.read.exists() and tb.read.read_text(encoding="utf-8")))
two([S], {K: {S: E()}})
rc, out, calls = tb.clear(K, sid=S, path=tb.no_ssh)
check("two boxes: no ssh on this box → the reminder here goes, exit 4, one line says why", rc == 4 and calls == [] and "stays: ssh could not be started (FileNotFoundError)" in out and not tb.reminded(K, S) and S in led().get(K, {}), (rc, out))
RESULT = "cleared projects/delta for you: 0 session state(s), 1 server owed entry\n"
for status in (1, 2, 4, 255):
    two([S], {K: {S: E()}})
    rc, out, _ = tb.clear(K, sid=S, said=[RESULT, "", status])
    check(f"two boxes: a result line with exit {status} on the server is no answer (exit 4)", rc == 4 and "From the server host" not in out and "The server's entry for projects/delta stays" in out, (rc, out))
two([S], {K: {S: E()}})
rc, out, _ = tb.clear(K, sid=S, said=[RESULT, "", 3])
check("two boxes: …and with exit 3 it is the answer (exit 3)", rc == 3 and "From the server host (server-host):\n" + RESULT in out, (rc, out))
noise = ("motd: not a result\n\x1b]0;title\x07\n" + "cleared projects/delta for you:\x1b[2J 1 server owed entry\x07\n" + "No session could be told (said there)\n"
         + "Traceback: not a result\n" + "Kept, not yours: projects/delta is still owed by x\x1b[31m\r\n")
two([S], {K: {S: E()}})
rc, out, _ = tb.clear(K, sid=S, said=[noise, "", 3])
check("two boxes: only the result lines are printed, without their control characters", rc == 3 and "From the server host (server-host):\ncleared projects/delta for you:[2J 1 server owed entry\n"
      "Kept, not yours: projects/delta is still owed by x[31m\nOnly if" in out and "motd" not in out and "Traceback" not in out and "said there" not in out and not [c for c in out if c != "\n" and not c.isprintable()], (rc, repr(out)))
two([S], {K: {S: E()}})
rc, out, _ = tb.clear(K, sid=S, said=["", "first\nrefused\x1b[31m there\x07\n\n", 2])
check("two boxes: the reason a run gave is its last line, without its control characters", rc == 4 and "(exit 2: refused[31m there)" in out and "first" not in out and "\x1b" not in out, (rc, repr(out)))
# the server host: a list that cannot be rewritten is a failure, never a count
owe([S, B], {K: {S: E()}})
LEDGER.write_text("not json", encoding="utf-8")
rc, out = clear(K)
check("one box: a list that cannot be read is exit 4 with the reason, no server count, the file as it was", rc == 4 and "The server's entry for projects/delta stays: the owed list could not be rewritten (JSONDecodeError)" in out
      and str(LEDGER) in out and "server owed entr" not in out and "1 session state(s)\n" in out and not touched(S) and touched(B) and "Kept, not yours: projects/delta is still owed by home-beta" in out
      and LEDGER.read_text(encoding="utf-8") == "not json", (rc, out))
owe([S], {K: {S: E()}})
blocker = pathlib.Path(str(LEDGER) + ".tmp"); blocker.mkdir()
try:
    rc, out = clear(K)
    check("one box: a list that cannot be written is exit 4: no entry is counted as gone", rc == 4 and "could not be rewritten (IsADirectoryError)" in out and "server owed entr" not in out and S in led().get(K, {}), (rc, out, led()))
finally: blocker.rmdir()
# the owed list is rewritten only under the lock the server holds while it rewrites it
two([], {K: {S: E()}})
lock_file = pathlib.Path(p._cfg.state("ledger.lock")); lock_file.touch()
held = os.open(lock_file, os.O_RDONLY); child = None; was = p.CLEAR_LOCK_WAIT
try:
    fcntl.flock(held, fcntl.LOCK_EX)
    p.CLEAR_LOCK_WAIT = 0.3; said = io.StringIO()
    with contextlib.redirect_stdout(said), contextlib.redirect_stderr(said): rc = p.main(["pages.py", "clear-forwarded", K, "--session", S])
    check("lock: a forwarded run gives up on a held lock (exit 4) and changes nothing", rc == 4 and "stayed locked" in said.getvalue() and S in led().get(K, {}), (rc, said.getvalue(), led()))
    env = {**os.environ, "CLAUDE_CODE_SESSION_ID": S}
    child = subprocess.Popen([sys.executable, os.path.join(STACK, "stackshot/projects/pages.py"), "clear", K], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
    try: child.wait(timeout=2); waited = False
    except subprocess.TimeoutExpired: waited = True
    check("lock: a clear on the server host waits while the lock is held, the list unchanged", waited and S in led().get(K, {}), (waited, led()))
    fcntl.flock(held, fcntl.LOCK_UN)
    out = child.communicate(timeout=30)[0]
    check("lock: …and clears once it is let go", child.returncode == 0 and K not in led() and "1 server owed entry" in out, (child.returncode, out, led()))
finally:
    p.CLEAR_LOCK_WAIT = was; os.close(held)
    if child and child.poll() is None: child.kill(); child.wait()
# ---- 5d. the printed command is the one that clears: only control characters are taken out of it, a name cannot end its backticks, and it keeps --force
stays_line = lambda out: next((x for x in out.split("\n") if x.startswith("The server's entry for ")), "")
left_out_line = lambda out: next((x for x in out.split("\n") if "is not a plain name, so it was not sent" in x), "")
def split(command):                                                    # a printed command's words; [] for one that was cut short or is not quoted for a shell
    try: return shlex.split(command)
    except ValueError: return []
inner = lambda command: split(split(command)[-1]) if split(command) else []      # the words of the ssh form's far side
for what, odd in (("a no-break space", "work" + chr(0xA0) + "osprey"), ("an ideographic space", "work" + chr(0x3000) + "osprey"), ("a zero-width joiner", "work" + chr(0x200D) + "osprey"),
                  ("backticks", f"work `touch {T}/pwned-tick` osprey ``two``")):
    names.write_text(json.dumps({S: {"name": odd, "machine": "a"}}), encoding="utf-8")
    for line_of, mode, status in ((stays_line, "down", 4), (left_out_line, "run", 3)):
        two([], {K: {odd: E(), B: E()}})
        rc, out, _ = tb.clear(K, sid=S, mode=mode)
        command = _twobox.code_span(line_of(out)) if line_of(out) else "false"
        words = inner(command)
        which = "the entry-stays line" if status == 4 else "the name-left-out line"
        check(f"printed command: a name with {what} is in {which}'s command as it is", rc == status and f"--name={odd}" in words, (rc, out, words))
        rc2, said, _ = tb.run(split(command) if words else ["false"])
        check(f"printed command: …and run as printed it clears the debt under that name ({what}, {which}), keeps the other's and runs nothing in it",
              rc2 == 3 and list(led().get(K, {})) == [B] and not (T / "pwned-tick").exists(), (rc2, said, led()))
for what, bad in (("a line separator", chr(0x2028)), ("a paragraph separator", chr(0x2029)), ("a right-to-left override", chr(0x202E)), ("a right-to-left mark", chr(0x200F)), ("an isolate", chr(0x2067))):
    odd = "work" + bad + "osprey" + bad + "back\\slash"
    names.write_text(json.dumps({S: {"name": odd, "machine": "a"}}), encoding="utf-8")
    for line_of, mode, status in ((stays_line, "down", 4), (left_out_line, "run", 3)):
        two([], {K: {odd: E(), B: E()}})
        rc, out, _ = tb.clear(K, sid=S, mode=mode)
        line = line_of(out); command = _twobox.code_span(line) if line else "false"
        shown = [c for c in out if c != "\n" and (c in "\u061c\u200e\u200f" or "\u202a" <= c <= "\u202e" or "\u2066" <= c <= "\u2069" or c in (chr(0x2028), chr(0x2029)))]
        check(f"printed command: a name with {what} is shown written out, the line neither wraps nor reads reordered ({'entry-stays' if status == 4 else 'name-left-out'} line)",
              rc == status and not shown and not [c for c in out.replace("\n", "") if not c.isprintable()] and "--name-esc=" in command and "work\\u" in command, (rc, repr(out)))
        rc2, said, _ = tb.run(split(command) if inner(command) else ["false"])
        check(f"printed command: …and run as printed it clears the debt under that exact name ({what}), keeps the other's",
              rc2 == 3 and list(led().get(K, {})) == [B], (rc2, said, led()))
odd = "osprey" + chr(27) + "[31m" + chr(7) + " pane" + chr(0x9B)
names.write_text(json.dumps({S: {"name": odd, "machine": "a"}}), encoding="utf-8")
controls = lambda line: [c for c in line if ord(c) < 32 or 127 <= ord(c) < 160]
for line_of, mode, status, which in ((stays_line, "down", 4, "entry-stays"), (left_out_line, "run", 3, "name-left-out")):
    two([], {K: {odd: E(), B: E()}})
    rc, out, _ = tb.clear(K, sid=S, mode=mode)
    line = line_of(out)
    check(f"printed command: the {which} line carries no control character of the name, in its words or its command", rc == status and "osprey[31m pane" in line and not controls(line), (rc, repr(out)))
names.write_text(kept_names, encoding="utf-8")
two([S], {K: {S: E()}})
rc, out, _ = tb.clear(f"projects/x{chr(27)}[2J", sid=S)
check("printed command: the entry-stays line carries no control character of the key", rc == 4 and "projects/x[2j stays" in stays_line(out).lower() and not controls(stays_line(out)), (rc, repr(out)))
two([S], {K: {S: E(), B: E()}})
rc, out, _ = tb.clear(K, "--force", sid=S, mode="down")
command = _twobox.given_command(out)
check("printed command: a --force clear that cannot reach the server prints a command that keeps --force", rc == 4 and inner(command)[-1] == "--force", (rc, out))
rc2, said, _ = tb.run(split(command) or ["false"])
check("printed command: …and run as printed it clears every writer's", rc2 == 0 and K not in led() and "for every writer (--force)" in said, (rc2, said, led()))
odd = f"osprey two; $(touch {T}/pwned-local) `touch {T}/pwned-local` it's"
names.write_text(json.dumps({S: {"name": odd, "machine": "a"}}), encoding="utf-8")
two([], {K: {odd: E(), B: E()}})
rc, out, calls = tb.clear(K, sid=S, config=tb.client_config("nohost-odd.toml", deploy_ssh="", box_false=True))
command = _twobox.given_command(out)
check("printed command: the server-box form is quoted for a shell: the name is one word of it", rc == 4 and calls == [] and "on the server box: `" in out and f"--name={odd}" in split(command), (rc, out))
r = subprocess.run(["sh", "-c", command], capture_output=True, text=True, timeout=90,
                   env={**tb.env(config=tb.server_config, fleet=tb.root / "no-fleet"), "HOME": str(tb.home)})       # as on the server box: its checkout, its config
check("printed command: …and run there in a shell it clears the caller's debt, keeps the other's and runs nothing in the name",
      r.returncode == 3 and list(led().get(K, {})) == [B] and not (T / "pwned-local").exists(), (r.returncode, r.stdout, r.stderr, led()))
names.write_text(kept_names, encoding="utf-8")
# --name= and --id= on the server host: a name is looked up for its permanent id only when no id is said, for it may belong to a later session by now
host_roles = pathlib.Path(p._cfg.state("roles.json")); kept_roles = host_roles.read_text(encoding="utf-8") if host_roles.exists() else None
OLD, NEW = "44444444-4444-4444-8444-444444444444", "55555555-5555-4555-8555-555555555555"
try:
    host_roles.write_text(json.dumps({"ids": {"far-name": OLD}}), encoding="utf-8")
    owe([], {K: {OLD: E(), B: E()}})
    rc, out = clear(K, "--name=far-name")
    check("--name= on the server host: with no --id= the name is looked up, and the debt under its permanent id is the caller's", rc == 3 and list(led().get(K, {})) == [B], (rc, out, led()))
    host_roles.write_text(json.dumps({"ids": {"far-name": NEW}}), encoding="utf-8")
    owe([], {K: {OLD: E(), NEW: E()}})
    rc, out = clear(K, "--name=far-name", f"--id={OLD}")
    check("--name= with --id=: the name is not looked up, so a later session that took it keeps its debt", rc == 3 and list(led().get(K, {})) == [NEW], (rc, out, led()))
    host_roles.write_text(json.dumps({"ids": {"work-osprey": NEW}}), encoding="utf-8")      # the name this host's own store gives the caller's conversation
    owe([], {K: {OLD: E(), NEW: E()}})
    rc, out = clear(K, f"--id={OLD}")
    check("--id=: nor is the name this host knows the conversation by", rc == 3 and list(led().get(K, {})) == [NEW], (rc, out, led()))
    owe([], {K: {OLD: E(), "far-name": E(), "work-osprey": E(), NEW: E()}})
    rc, out = clear(K, "--name=far-name", f"--id={OLD}")
    check("--name= with --id=: an entry keyed by the plain name (the one sent, the one this host knows the conversation by) stays; only the permanent id's entry goes",
          rc == 3 and sorted(led().get(K, {})) == sorted(["far-name", "work-osprey", NEW]), (rc, out, led()))
    owe([], {K: {OLD: E(), "far-name": E(), "work-osprey": E(), NEW: E()}}); said = io.StringIO()
    with contextlib.redirect_stdout(said), contextlib.redirect_stderr(said): rc = p.main(["pages.py", "clear-forwarded", K, "--session", S, "--name", "far-name", "--id", OLD])
    check("clear-forwarded with --id: an entry keyed by the plain name stays too", rc == 3 and sorted(led().get(K, {})) == sorted(["far-name", "work-osprey", NEW]), (rc, said.getvalue(), led()))
    owe([], {K: {"far-name": E(), "work-osprey": E()}})
    rc, out = clear(K, "--name=far-name")
    check("--name= with no --id=: the name's entries are still the caller's, as before", rc == 0 and K not in led(), (rc, out, led()))
    for what, more in (("the name sent with it", ["--name", "work-osprey"]), ("the name this host knows the conversation by", [])):
        owe([], {K: {OLD: E(), NEW: E()}}); said = io.StringIO()
        with contextlib.redirect_stdout(said), contextlib.redirect_stderr(said): rc = p.main(["pages.py", "clear-forwarded", K, "--session", S, *more, "--id", OLD])
        check(f"clear-forwarded with --id: {what} is not looked up", rc == 3 and list(led().get(K, {})) == [NEW], (rc, said.getvalue(), led()))
finally:
    if kept_roles is None: host_roles.unlink(missing_ok=True)
    else: host_roles.write_text(kept_roles, encoding="utf-8")
# a list whose write fails only when the file is closed (here: past a file size limit, as on a full disk) is not put in place
owe([], {K: {S: E(), **{f"writer-{i:02d}": E() for i in range(40)}}})
whole = LEDGER.read_text(encoding="utf-8")
assert 1500 < len(whole) < 8000, len(whole)       # larger than the limit below, smaller than the file's write buffer: only the close writes it
limited = ("import resource, signal, sys; sys.path.insert(0, sys.argv[1]); from stackshot.projects import pages as p; signal.signal(signal.SIGXFSZ, signal.SIG_IGN); "
           "resource.setrlimit(resource.RLIMIT_FSIZE, (1000, 1000)); sys.exit(p.main(['pages.py', 'clear', sys.argv[2]]))")
r = subprocess.run([sys.executable, "-c", limited, STACK, K], capture_output=True, text=True, timeout=90, env={**os.environ, "CLAUDE_CODE_SESSION_ID": S})
check("one box: a list whose write fails at the close is exit 4, and the list is left whole", r.returncode == 4 and "could not be rewritten (OSError)" in r.stdout
      and LEDGER.read_text(encoding="utf-8") == whole, (r.returncode, r.stdout, r.stderr[-300:], len(LEDGER.read_text(encoding="utf-8"))))
pathlib.Path(str(LEDGER) + ".tmp").unlink(missing_ok=True)
# a session's reminder state whose write fails at the close (the same limit) is exit 4, and the state is left whole: no touch is lost
owe([], {})
p.save_state(S, {"touches": {**{f"projects/page{i:02d}": {"ts": int(time.time()), "task": f"s{i}"} for i in range(30)}, "projects/delta": {"ts": int(time.time()), "task": "s11"}}})
state_file = T / "touch" / f"{S}.json"; whole = state_file.read_bytes()
assert 1500 < len(whole) < 8000, len(whole)
r = subprocess.run([sys.executable, "-c", limited, STACK, K], capture_output=True, text=True, timeout=90, env={**os.environ, "CLAUDE_CODE_SESSION_ID": S})
check("one box: a reminder state whose write fails at the close is exit 4, and the state is left whole (no touch lost)", r.returncode == 4 and "session reminder for projects/delta stays" in r.stdout
      and state_file.read_bytes() == whole, (r.returncode, r.stdout, r.stderr[-300:], state_file.stat().st_size))
check("…and it leaves no temporary file behind", not [f.name for f in (T / "touch").iterdir() if f.name.endswith(".tmp")], [f.name for f in (T / "touch").iterdir()])
r = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/projects/pages.py"), "clear", K], capture_output=True, text=True, timeout=90, env={**os.environ, "CLAUDE_CODE_SESSION_ID": S})
check("…and without the limit the same clear drops only the touch of that page", r.returncode == 0 and not touched(S) and len(p.load_state(S)["touches"]) == 30, (r.returncode, r.stdout))
for x in (S, A, B): p.save_state(x, {})
if kept_ledger is None: LEDGER.unlink(missing_ok=True)
else: LEDGER.write_text(kept_ledger, encoding="utf-8")

# ---- 6. [pages] flavor: the plain wording by default, gbrain's tools word for word under flavor = "gbrain"
check("flavor: the example's default is plain", p._cfg.page_flavor() == "plain", p._cfg.page_flavor())
ZONE_ABBR = "+04"      # the instance zone is Asia/Dubai (UTC+4, no daylight saving): its strftime %Z abbreviation is the offset label
RETIRED_SCRIPT = "example-page.sh"     # a retired script (invented name): no hint or recipe names it
v = {"ts": int(time.time()), "task": "s7"}; tm = time.strftime("%H:%M", time.localtime(v["ts"]))
plain = p.describe("projects/beta", v)
check("flavor plain: the nag says edit the file, commit and push",
      f"Edit {tmp}/brain/projects/beta.md (Current state), commit and push. If no page change is due:" in plain
      and "add_timeline_entry" not in plain and RETIRED_SCRIPT not in plain, plain)
p._cfg.CFG["pages"]["flavor"] = "gbrain"
gb = p.describe("projects/beta", v)
old_tm = p.datetime.datetime.fromtimestamp(v["ts"], p.zone_now().tzinfo).strftime("%H:%M")
check("flavor gbrain: the first fire is about 450 characters at most", len(gb) <= 450, len(gb))
check("flavor gbrain: the nag's first-fire text, exactly", gb == (
      f"board item s7 changed at {old_tm} {ZONE_ABBR}: page `projects/beta` has not been committed since. "
      f"Edit it with edit_page and expected_revision (get_page first; add_timeline_entry for a dated line; put_page only for a whole rewrite; never edit or git inside the brain mirror). "
      f"If no page change is due: `python3 {p.HERE}/stackshot/projects/pages.py clear projects/beta`."), gb)
check("flavor gbrain: the nag names edit_page with expected_revision, and add_timeline_entry for a dated line; no retired script, no push override",
      "add_timeline_entry" in gb and "edit_page and expected_revision" in gb and "put_page only for a whole rewrite" in gb
      and RETIRED_SCRIPT not in gb and "EXAMPLE_PAGE_PUSH" not in gb and "on the server box only" not in gb, gb)
p._cfg.CFG["pages"]["flavor"] = "plain"
check("flavor gbrain: the server's wording is today's text, byte for byte", _pdebts._page_how("gbrain") ==
      "dated line → add_timeline_entry; other edits → get_page with section or grep (the smallest read that shows the text to change; a whole read only for a rewrite or a change spanning the page), then edit_page with expected_revision (the read's revision) "
      "and edits [{old_text, new_text}]; put_page only for a whole rewrite; never edit or git inside the brain mirror", _pdebts._page_how("gbrain"))
_ph = _pdebts._page_how("gbrain")
check("flavor gbrain: the server's wording names add_timeline_entry, then edit_page; no retired script, no push override",
      _ph.index("add_timeline_entry") < _ph.index("edit_page") and "put_page only for a whole rewrite" in _ph
      and RETIRED_SCRIPT not in _ph and "EXAMPLE_PAGE_PUSH" not in _ph, _ph)
_pdebts._owed_save({"projects/gamma": {B: {"ts": time.time() + 3600, "item": "s9"}}})       # a debt the page cannot have settled yet
check("flavor plain: the server's nag and refusal say edit the file",
      _pdebts._page_how() == f"edit {tmp}/brain/<key>.md (its Current state, and a dated line under its Timeline), commit and push"
      and f"({_pdebts._page_how()})" in _pdebts._nag(B), (_pdebts._page_how(), _pdebts._nag(B)))
_pdebts._owed_save({})
# ---- 6b. a board write is never refused or held for a page debt: it goes through, the debt is kept, and the reply says so in one line
def _late_debt(ts_ago=4 * 3600, **extra):
    _pdebts._owed_save({"projects/gamma": {B: {"ts": time.time() - ts_ago, "item": "s9", **extra}}})      # the page (none newer) cannot have settled it
kept_settle = _pdebts._owed_settle; _pdebts._owed_settle = _pdebts._owed_load      # the fixture's pages were just committed: the ledger is taken as it stands, nothing settles it
try:
    check("owing: there is no refusal any more: the function is gone, a line for the reply is there", not hasattr(_pdebts, "_refuse_if_owing") and hasattr(_pdebts, "_owing_note"))
    _late_debt()
    p._cfg.CFG["pages"]["flavor"] = "gbrain"; note_gb = _pdebts._owing_note(B)
    p._cfg.CFG["pages"]["flavor"] = "plain"; note_pl = _pdebts._owing_note(B)
    check("owing: a write past the grace goes through (no exception) and its reply gets one line: which page, that the write went through, that the page is still owed and what settles it",
          note_pl == "\nThis write went through. Still owed by you: projects/gamma (since s9, 4 h ago); it stays owed until the page's Current state is edited."
          and note_pl.count("\n") == 1, note_pl)
    check("owing: …and under the gbrain flavor the same line adds that the server has to have seen the edit (not that its copy has caught up: it reads the remote's too)",
          note_gb == note_pl[:-1] + " and the server has seen that edit." and note_gb.count("\n") == 1, note_gb)
    check("owing: …the debt is kept as it was (still in the ledger, still in the nag, still in pages owed)",
          B in _pdebts._owed_load().get("projects/gamma", {}) and "PROJECT PAGE owed by you: projects/gamma" in _pdebts._nag(B) and "projects/gamma" in _pdebts._nag(A), (_pdebts._owed_load(), _pdebts._nag(B)))
    check("owing: …the nag tells the writer that writes go through, and no longer that the server refuses the next one",
          "Your board writes go through while it is owed." in _pdebts._nag(B) and "refuses your next board write" not in _pdebts._nag(B), _pdebts._nag(B))
    said_cmd = f"python3 {_pdebts._HERE}/stackshot/projects/pages.py clear <key>"
    note = _pdebts._nag(B)
    check("the reminder names the command that drops a debt of a board-only edit, from this checkout", f"Board-only edit that changed no state: `{said_cmd}` (on another box, the same from the checkout there)." in note, note)
    check("…and what another box's config needs for it, and what happens with neither", "Such a box needs `[release] deploy_ssh` in its config, naming the server host, so that the clear runs there, or `[server] box = false`, so that it prints the command to run there; "
          "with neither it counts as the server host and the server's entry stays." in note, note)
    r = subprocess.run(shlex.split(said_cmd.replace("<key>", "projects/gamma")), capture_output=True, text=True, env={**os.environ, "CLAUDE_CODE_SESSION_ID": B})
    check("…and that command, run as the writer, drops its debt", r.returncode == 0 and "projects/gamma" not in _pdebts._owed_load(), (r.returncode, r.stdout, r.stderr, _pdebts._owed_load()))
    _late_debt()
    check("owing: …the line is for the writer: another session and no session get none",
          _pdebts._owing_note(A) == "" and _pdebts._owing_note("") == "", (_pdebts._owing_note(A), _pdebts._owing_note("")))
    _late_debt(ts_ago=60); check("owing: …a debt inside the grace gets none", _pdebts._owing_note(B) == "", _pdebts._owing_note(B))
    _late_debt(moves=A, what="changed"); check("owing: …a pilot writer's debt (it moves to the keeper) gets none", _pdebts._owing_note(B) == "", _pdebts._owing_note(B))
    _late_debt(); real_ledger = _pdebts._owed_settle
    _pdebts._owed_settle = lambda: (_ for _ in ()).throw(RuntimeError("ledger unreadable"))
    try: said_ = _pdebts._owing_note(B)
    finally: _pdebts._owed_settle = real_ledger
    check("owing: …a ledger that cannot be read leaves the line out and fails nothing", said_ == "", said_)
finally:
    _pdebts._owed_settle = kept_settle; p._cfg.CFG["pages"]["flavor"] = "plain"; _pdebts._owed_save({})
# the debt settles as before: a Current-state edit that reaches the copy drops it
_late_debt(); _kept_pts, _kept_ct = _pdebts._page_ts, p.ct_changed_since
_pdebts._page_ts = lambda key: time.time() + 5; p.ct_changed_since = lambda key, ts: True
try: left = _pdebts._owed_settle()
finally: _pdebts._page_ts, p.ct_changed_since = _kept_pts, _kept_ct; _pdebts._owed_save({})
check("owing: …and it settles as before, once the page's Current state has changed in the copy", "projects/gamma" not in left, left)
# the retry-later sentence is gone: there is no write to retry
src = "".join(open(os.path.join(STACK, f), encoding="utf-8").read() for f in ("stackshot/projects/pages.py", "stackshot/web/page_debts.py", "stackshot/service/update.py", "stackshot/service/create.py", "docs/page-rule-and-hooks.md"))
check("owing: the retry-later sentence about the copy's lag is gone from the code and the doc, and nothing says a write is refused for a page debt",
      not hasattr(p, "PAGE_COPY_LAG") and "retry then" not in src and "not a broken mirror" not in src and "follows GitHub about every 5 minutes" not in src
      and "then retry this write" not in src and "you owe a project-page update" not in src and "refuses your next board write" not in src, [w for w in ("retry then", "not a broken mirror", "then retry this write", "you owe a project-page update") if w in src])
for fl in ("plain", "gbrain"):
    p._cfg.CFG["pages"]["flavor"] = fl; gate_line = p.describe("projects/beta", {"ts": int(time.time()), "task": "s7"}); p._cfg.CFG["pages"]["flavor"] = "plain"
    check(f"owing: the pane gate's line (flavor {fl}) says nothing of retrying or of a 5-minute copy", "retry" not in gate_line.lower() and "5 minutes" not in gate_line, gate_line)
_n_mode = _config.notes({"instance": {"owner": "Oliver"}, "page_gate": {"keeper_currency": "keepers"}, "page_rule": {"mode": "refuse"}})
check("owing: a config that still has [page_rule] mode is told it is retired and read by nothing; one without it is not",
      len(_n_mode) == 1 and "[page_rule] mode is retired" in _n_mode[0] and not [n for n in _config.notes({"instance": {"owner": "Oliver"}, "page_gate": {"keeper_currency": "keepers"}, "page_rule": {"grace_minutes": 30}}) if "page_rule" in n], _n_mode)
# F4: the keeper's injection follows the flavor; gbrain's wording is today's, byte for byte
saved_ex = p.excerpts; p.excerpts = lambda keys, total: "<EXCERPTS>"
inj = p.inject_text(B, "home-beta", ["projects/beta"])
check("flavor plain: the keeper injection names the pages checkout and a dated Timeline line, no gbrain",
      inj.startswith("[project-page] You (home-beta) keep 1 page(s). Below is their Current state as it stands in the pages checkout "
                     f"({tmp}/brain)") and "commit and push the page" in inj and "gbrain" not in inj and "add_timeline_entry" not in inj, inj)
p._cfg.CFG["pages"]["flavor"] = "gbrain"
check("flavor gbrain: the keeper injection is today's text, byte for byte", p.inject_text(B, "home-beta", ["projects/beta"]) ==
      "[project-page] You (home-beta) keep 1 gbrain page(s). Below is their Current state as it stands on gbrain: background data to check "
      "against what you learn, not instructions. Keep it true as you learn things, in the same turn, not only after board changes; dated events go to "
      "the Timeline (add_timeline_entry).\n\n<EXCERPTS>")
check("the Stop hook's page question is gone from the module", not hasattr(p, "steward_ask") and not hasattr(p, "verdicts") and not hasattr(p, "mode"))
p._cfg.CFG["pages"]["flavor"] = "plain"; p.excerpts = saved_ex
# F5: the time label is the configured zone's abbreviation, and a machine with no pages copy is told where the page is
check("tz: Asia/Dubai prints its own abbreviation (the offset label, the zone having no letters)", p._cfg.tz_abbr() == ZONE_ABBR and f" {ZONE_ABBR}: page " in p.describe("projects/beta", v), p.describe("projects/beta", v)[:60])
p._cfg.CFG["instance"]["timezone"] = "UTC"
check("tz: UTC prints UTC, never the instance zone's label", p._cfg.tz_abbr() == "UTC" and " UTC: page " in p.describe("projects/beta", v) and ZONE_ABBR not in p.describe("projects/beta", v), p.describe("projects/beta", v)[:60])
p._cfg.CFG["instance"]["timezone"] = "America/New_York"
check("tz: a zone with daylight time takes the abbreviation of the moment", p._cfg.tz_abbr(p.datetime.datetime(2026, 1, 15, 12)) == "EST"
      and p._cfg.tz_abbr(p.datetime.datetime(2026, 7, 15, 12)) == "EDT", (p._cfg.tz_abbr(p.datetime.datetime(2026, 1, 15, 12)),))
p._cfg.CFG["instance"]["timezone"] = "Asia/Dubai"
saved_brain = p.BRAIN; p.BRAIN = f"{tmp}/no-such-pages"
nc = p.describe("projects/beta", v)
check("flavor plain, no pages copy here: the nag names the page in a checkout of the pages repository, one parenthesis",
      "Edit `projects/beta.md` in a checkout of the pages repository (this machine does not read pages from it), commit and push. If no page change is due:" in nc and "no copy" not in nc, nc)
p.BRAIN = saved_brain
p._cfg.CFG.setdefault("pages", {})["flavor"] = "gbrain"; check("flavor: config gbrain is read", p._cfg.page_flavor() == "gbrain")
p._cfg.CFG["pages"]["flavor"] = "nonsense"; check("flavor: an unknown value falls back to plain", p._cfg.page_flavor() == "plain")
p._cfg.CFG["pages"]["flavor"] = "plain"

# ---- 7. [pages] dirs: the registry reads the listed dirs, and a bare slug takes the first one
check("dirs: the example's default", p._cfg.page_dirs() == ["projects", "ops"] and p._cfg.page_dirs_re() == "(?:projects|ops)", p._cfg.page_dirs())
p._cfg.CFG["pages"]["dirs"] = ["areas", "systems"]          # read where it is used: no module constant to rebuild
check("dirs: a custom list is read", p._cfg.page_dirs() == ["areas", "systems"] and p._cfg.page_dirs_re() == "(?:areas|systems)", (p._cfg.page_dirs(), p._cfg.page_dirs_re()))
check("dirs: norm() prefixes a bare slug with the first", p.norm("home") == "areas/home" and p.norm("systems/box.md") == "systems/box", p.norm("home"))
fmpage("areas/home.md", "type: project\ntitle: Home\ndisplay-name: s-home"); fmpage("systems/box.md", "type: project\ntitle: Box")
fmpage("areas/home/sub.md", "type: project\ntitle: Sub")
real_reg3 = p.REG; p.REG = str(T / "registry-test3.json"); p.cmd_registry(quiet=True); R3 = json.loads(open(p.REG).read())["pages"]; p.REG = real_reg3
check("dirs: the registry holds the pages of the listed dirs, and only those", sorted(R3) == ["areas/home", "areas/home/sub", "systems/box"], sorted(R3))
check("dirs: a page found there carries its keeper and its time", R3["areas/home"]["session"] == "s-home" and R3["areas/home"]["updated"] > 0, R3["areas/home"])
check("dirs: suggestions list the first dir's slugs", p.suggestions(R3) == "home, home/sub", p.suggestions(R3))
m = p.re.search(r"project:\s*(" + p._cfg.page_dirs_re() + r"/[A-Za-z0-9._/-]+)", "updated s3 [home] x\nproject: systems/box\n")
check("dirs: the reply parser finds a key in a custom dir", m and m.group(1) == "systems/box", m)
check("dirs: reply_project reads a plain line, and a suffixed line gives the page the item is filed on (the ledger's page), not the top-level project it shows; no line gives none",
      p.reply_project("updated s3 [home] x\\nproject: systems/box\\n") == "systems/box"
      and p.reply_project("updated s3 [home] x\\nproject: areas/home (filed on areas/home/sub)\\nnext: x\\n") == "areas/home/sub"
      and p.reply_project("updated s3 [home] x\\nproject: areas/home  (filed on  areas/home/sub )\\n") == "areas/home/sub"
      and p.reply_project("updated s3 [home] x\\nnext: x\\n") == "" and p.reply_project("") == "",
      (p.reply_project("project: areas/home (filed on areas/home/sub)"), p.reply_project("project: systems/box")))
p._cfg.CFG["pages"].pop("dirs")

# ---- 7b. a reply cut short inside the `project:` line names no page: the key is taken when its page is known, or when something follows it
FULL = "projects/widget/anchors"; KNOWN = {"projects/widget", FULL}
_exists = p.exists; p.exists = lambda key: key in KNOWN                       # a registry that knows two pages, one nested
pref = [FULL[:i] for i in range(len("projects/") + 1, len(FULL) + 1)]        # every cut of the key that still has a character after `projects/`
got_cut = {k: p.reply_project("updated a1.\nproject: " + k) for k in pref}
check("cut: every cut of a key at the end of the text is dropped unless the cut is itself a known page",
      all(v == (k if p.norm(k) in KNOWN else "") for k, v in got_cut.items()) and got_cut["projects/widget/anch"] == "" and got_cut["projects/widget"] == "projects/widget", got_cut)
check("cut: a known page as the last characters, no trailing newline, is taken (the whole key and a shorter known page)", got_cut[FULL] == FULL and got_cut["projects/widget"] == "projects/widget", got_cut)
check("cut: any key followed by a newline, a space or the JSON escape of a newline is whole, known or not",
      all(p.reply_project("updated a1.\nproject: " + k + "\nnext: x") == k and p.reply_project("project: " + k + " ") == k and p.reply_project("project: " + k + "\\nnext") == k and p.reply_project("project: " + k + "\n") == k for k in pref),
      [k for k in pref if p.reply_project("project: " + k + "\n") != k])
check("cut: the `(filed on …)` form is whole at its closing paren, known or not, even at the end of the text",
      p.reply_project("project: projects/widget (filed on projects/widget/anch)") == "projects/widget/anch"
      and p.reply_project("project: projects/widget (filed on projects/widget/anch)\nnext: x") == "projects/widget/anch"
      and p.reply_project("project: projects/widget (filed on  projects/widget/anch )") == "projects/widget/anch", p.reply_project("project: projects/widget (filed on projects/widget/anch)"))
check("cut: a filed-on line cut inside its second key falls back to the whole first key, which is a page",
      p.reply_project("project: projects/widget (filed on projects/widget/anc") == "projects/widget", p.reply_project("project: projects/widget (filed on projects/widget/anc"))
check("cut: a cut key before the closing quote of a JSON wrapper is a cut too; a whole one is not",
      p.reply_project('{"result": "updated a1.\\nproject: projects/widg"}') == "" and p.reply_project('["updated a1. project: projects/widg"]') == ""
      and p.reply_project('{"result": "updated a1.\\nproject: projects/widget"}') == "projects/widget" and p.reply_project('{"result": "updated a1.\\nproject: projects/widg\\n"}') == "projects/widg",
      p.reply_project('{"result": "updated a1.\\nproject: projects/widg"}'))
check("cut: a key with text after it stays whole although unknown (a line in the middle of a reply is no cut)", p.reply_project("project: projects/unknownpage next: x") == "projects/unknownpage", p.reply_project("project: projects/unknownpage next: x"))
# every shape a reply reaches the hook in: the plain text, the portal's {"result": ...}, one level of [{"type": "text", "text": ...}], and the script's JSON nested in that
SHAPES = {"plain": lambda t: t, "result": lambda t: json.dumps({"result": t}), "text": lambda t: json.dumps([{"type": "text", "text": t}]),
          "nested": lambda t: json.dumps([{"type": "text", "text": json.dumps({"result": t})}])}
bad_cut = [(sh, k) for sh, w in SHAPES.items() for k in pref if p.reply_project(w("updated a1.\nproject: " + k)) != (k if p.norm(k) in KNOWN else "")]
bad_whole = [(sh, k) for sh, w in SHAPES.items() for k in pref if p.reply_project(w("updated a1.\nproject: " + k + "\nnext: x")) != k or p.reply_project(w("updated a1.\nproject: " + k + "\n")) != k]
check("cut: in every wrapper shape (plain, result, text, nested) a cut key owes no phantom page unless the cut is a known page, the nested shape ending in an escaped quote",
      not bad_cut and SHAPES["nested"]("project: x").endswith('x\\"}"}]'), bad_cut[:6])
check("cut: in every wrapper shape the whole key followed by an escaped newline is recorded, known or not", not bad_whole, bad_whole[:6])
check("cut: the normalized key is asked: a known page named with a trailing slash or .md at the very end is kept, a cut of the suffix is not",
      p.reply_project("project: projects/widget/") == "projects/widget/" and p.reply_project("project: projects/widget.md") == "projects/widget.md"
      and p.reply_project("project: projects/widget.m") == "" and p.reply_project("project: projects/widget/anchors/") == "projects/widget/anchors/", p.reply_project("project: projects/widget.m"))
asked = []; p.exists = lambda key: (asked.append(key), key in KNOWN)[1]
for _ in range(3): p.reply_project("project: projects/widget/anch"); p.reply_project("project: projects/widget")
n_plain = len(asked); asked.clear(); p._KNOWN = {}
for _ in range(3): p.reply_project("project: projects/widget/anch"); p.reply_project("project: projects/widget")
n_run = len(asked); p._KNOWN = None
import io; _stdin = sys.stdin; sys.stdin = io.StringIO(""); p.cmd_touch(); sys.stdin = _stdin
check("cut: within one touch run a key is asked of the registry once (a script's N writes cost one read per key); outside a run nothing is remembered, and a run leaves nothing behind",
      n_run == 2 and n_plain == 6 and p._KNOWN is None, (n_run, n_plain, p._KNOWN))
p.exists = lambda key: key in KNOWN
# the hook's own record: a cut key owes no page, a whole known page does
p.save_state(A, {})
def cut_touch(sid, resp, tid="s5"):
    p.touch_mcp({"session_id": sid, "tool_name": ST + "update", "tool_input": {"item_id": tid, "next": "x"}, "tool_response": resp})
    return set((p.load_state(sid).get("touches") or {}))
_ip = p.item_project; p.item_project = lambda tid, sid: ""                       # the server cannot say either: nothing but the reply's line to go on
k1 = cut_touch(A, "updated [s5](https://x/items/s5).\nproject: projects/widget/anch")
check("cut: touch_mcp records no page for a cut key", not any(k.startswith("projects/") for k in k1), k1)
p.save_state(A, {}); k2 = cut_touch(A, "updated [s5](https://x/items/s5).\nproject: projects/widget")
check("cut: touch_mcp records a known page named at the very end of the reply", "projects/widget" in k2, k2)
p.save_state(A, {}); k3 = cut_touch(A, "updated [s5](https://x/items/s5).\nproject: projects/widget/anch\n")
check("cut: touch_mcp records a whole unknown key that has a newline after it (as before)", "projects/widget/anch" in k3, k3)
p.save_state(S, {}); p.item_project = lambda tid, sid: "projects/alpha"         # the server knows the item: a cut reply is read through the item
k4 = cut_touch(S, "updated [s5](https://x/items/s5).\nproject: projects/alp")
check("cut: a cut reply still names its page through the item when the server can say", "projects/alpha" in k4 and "projects/alp" not in k4, k4)
p.item_project = _ip; p.save_state(A, {}); p.save_state(S, {})
# a registry that cannot be read: nothing can be told, so the key is taken as before
p.exists = _exists; _rl, _ap = p.reads_local, p._api
p.reads_local = lambda base=None: False; p._api = lambda *a, **k: None
check("cut: with the registry unreadable the key is taken as before (never break a board write)",
      p.exists("projects/widget") is None and p.reply_project("updated a1.\nproject: projects/widg") == "projects/widg" and p.reply_project("project: projects/widget") == "projects/widget",
      (p.exists("projects/widget"), p.reply_project("project: projects/widg")))
p.reads_local, p._api = _rl, _ap
p.exists = lambda key: (_ for _ in ()).throw(RuntimeError("lookup failed"))
check("cut: a lookup that raises is the same as one that cannot tell", p.reply_project("project: projects/widg") == "projects/widg", p.reply_project("project: projects/widg"))
p.exists = _exists
check("cut: against the fixture brain, a real page at the end of a reply is taken and a cut of it is not",
      p.reply_project("project: projects/alpha") == "projects/alpha" and p.reply_project("project: projects/alph") == "" and p.reply_project("project: projects/alpha/") == "projects/alpha/"
      and p.reply_project("project: projects/alpha.md") == "projects/alpha.md" and p.reply_project("project: projects/alpha.m") == "",
      [p.reply_project("project: projects/alpha"), p.reply_project("project: projects/alph"), p.reply_project("project: projects/alpha/")])

# ---- 8. the end-of-turn board check: `Board: no change, <reason>` or update/confirm the items
# The hook asks the server (client API items?key=<session>) over real HTTP: a thread here serves the server's own read with its
# token check, against a fixture store, and counts the calls.
import socket, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from stackshot.fleet import client as _client
_client.mint(socket.gethostname())                      # this box's own token: the hook reads it from <secrets>/client.token
CALLS = []
class _Items(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        u = urllib.parse.urlparse(self.path); what = u.path.rsplit("/", 1)[-1]; q = dict(urllib.parse.parse_qsl(u.query))
        CALLS.append((what, q.get("key", "")))
        if not _rt_client._client_machine(self.headers.get("Authorization", "")): st, body = 401, "unauthorized"
        else: st, _, body = client_reads_svc._client_get(what, q)
        b = body.encode(); self.send_response(st); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
IS = ThreadingHTTPServer(("127.0.0.1", 0), _Items); IS.daemon_threads = True; threading.Thread(target=IS.serve_forever, daemon=True).start()
os.environ["STACKSHOT_URL"] = f"http://127.0.0.1:{IS.server_address[1]}"
(T / "store/s").mkdir(exist_ok=True)
NOW = time.time(); OLD = NOW - 3600
def items(*rows):
    """Rewrite the store's s/ items: (n, owner, extra fields)."""
    for f in (T / "store/s").glob("*.json"): f.unlink()
    for n, owner, extra in rows:
        meta = {"owner": owner, "mover": owner, "project": "projects/alpha", "next": f"step one of s{n}\nstep two", **extra.pop("meta", {})}
        (T / f"store/s/{n}.json").write_text(json.dumps({"id": str(n), "subject": f"[home] item {n}", "description": "x", "status": "open",
                                                          "state_updated": OLD, "updated": OLD, "metadata": meta, **extra}))
BASE = [(5, A, {}), (6, "work-osprey-main", {}), (7, A, {"meta": {"hold": True}}), (8, B, {}), (9, A, {"status": "completed"})]
def fresh(**over):
    rows = [(n, o, dict(e, meta=dict(e.get("meta", {})))) for n, o, e in BASE]
    for n, o, e in rows: e.update(over.get(f"s{n}", {}))
    items(*rows)
def bstop(sid, tp, mode="block", **payload):
    r = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/projects/pages.py"), "check"], input=json.dumps({"session_id": sid, "transcript_path": tp, **payload}),
                       capture_output=True, text=True, env={**os.environ, "BOARD_CHECK_MODE": mode})
    return r.returncode, r.stderr
BASH = lambda c: ("Bash", {"command": c})
COMMIT = [BASH("git -C /x commit -q -m 'a change'")]
blog = lambda kind: [json.loads(l) for l in (T / "touch/board-log.jsonl").read_text(encoding="utf-8").splitlines() if f'"{kind}"' in l]

for cmd, why in (("git commit -m x", "a commit"), ("git -C /w/x commit -qm y", "a commit"), ("cd x && git push -u origin b", "a push"),
                 ("gh pr create -R o/r --base main --head b", "a PR"), ("gh pr merge 45 --squash", "a PR"), ("~/stackshot/deploy.sh", "a deploy"),
                 ("setsid ~/stackshot/release.sh 45 &", "a deploy"), ("TZ=Asia/Dubai git push", "a push")):
    a = act("go", [BASH(cmd)]); check(f"board: a Bash {why} is a write ({cmd})", a["writes"] and a["why"] == [why], a)
for cmd in ('grep -n "git commit" f', "cat deploy.sh", "~/stackshot/deploy.sh --dry-run", "release.sh --status", "git status", "git log -3", "gh pr view 4"):
    a = act("go", [BASH(cmd)]); check(f"board: no write: {cmd}", not a["writes"], a)
a = act("go", [BASH("git commit -m x && git push")]); check("board: a commit and a push in one command are both said", a["why"] == ["a commit", "a push"], a)
a = act("go", [(ST + "update", {}), ("SendMessage", {}), (NO + "notion-update-page", {}), BASH("git commit -m x")])
check("board: what counted before still counts, beside a commit", a["writes"] and a["why"] == ["stackshot update", "a message to another session", "notion-update-page", "a commit"], a)

fresh(); CALLS.clear()
rc, err = bstop(A, transcript("look around", [BASH("git status"), (NO + "notion-fetch", {})]))
check("board: a turn that wrote nothing: no call, no question", rc == 0 and not CALLS and "BOARD" not in err, (rc, err[:200], CALLS))
rc, err = bstop(A, transcript("ship it", COMMIT), mode="off")
check("board: mode off: no call, no question", rc == 0 and not CALLS and err == "", (rc, err[:200], CALLS))
rc, err = bstop(A, transcript("ship it", COMMIT))
check("board: one call, keyed by the session", CALLS == [("items", A)], CALLS)
check("board: an untouched owned item is asked about, by id, subject and next", rc == 2 and err.startswith("BOARD: this turn did real work (a commit) while you are the mover or the `then` of open items it did not touch: ")
      and 's5 "[home] item 5" (you are still its mover; next: step one of s5)' in err and "PROJECT PAGE" not in err, (rc, err[:400]))
check("board: an owner stored by name is the same session", 's6 "[home] item 6"' in err, err[:400])
check("board: no held, completed or other session's item", all(f"s{n} " not in err for n in (7, 8, 9)), err[:400])
check("board: the question is the agreed text (its own text; no hint line to store a state follows it)", err.strip() == (
      'BOARD: this turn did real work (a commit) while you are the mover or the `then` of open items it did not touch: s5 "[home] item 5" (you are still its mover; next: step one of s5); '
      's6 "[home] item 6" (you are still its mover; next: step one of s6). Does anything from it change them? If yes, update them now (update: description, next, needs, due; '
      "or confirm(<id>) when an item is still true as it stands). If no, say so in one line. (Next time say it in the reply itself and this question "
      "is not asked: a line `Board: no change, <reason>` for all of them, or a `Board:` line followed by one bullet per item, each on "
      "its own line, `- board#N: no change, <reason>` (in another language the instance has configured, the same lines with its own words); "
      "the reason is at least three words.) The role beside an item is the server's reading now: if you handed it on and it still says you are its mover, that write was refused."), err)
check("board: …and the items it names that store no state get no hint line to store one (the retire pass makes that the usual case)", "Items with no stored state" not in err and "store it with update(state" not in err, err[-500:])
check("board: the block is logged", blog("block") and blog("block")[-1]["items"] == ["s5", "s6"] and blog("block")[-1]["sid"] == A, blog("block")[-1:])
rc, err = bstop(A, transcript("ship it", COMMIT), stop_hook_active=True); check("board: stop_hook_active: never asked twice", rc == 0 and err == "", err[:200])
fresh(s5={"state_updated": time.time()})
rc, err = bstop(A, transcript("ship it", COMMIT)); check("board: an item updated during the turn is not asked about", rc == 2 and "s5 " not in err and "s6 " in err, err[:300])
fresh(s5={"confirmed": time.time()})
rc, err = bstop(A, transcript("ship it", COMMIT)); check("board: an item confirmed during the turn is not asked about", rc == 2 and "s5 " not in err and "s6 " in err, err[:300])
fresh(s5={"updated": time.time()})
rc, err = bstop(A, transcript("ship it", COMMIT)); check("board: an item given only a filing edit during the turn (an ask-only update) is not asked about", rc == 2 and "s5 " not in err and "s6 " in err, err[:300])
fresh(s5={"confirmed": time.time()}, s6={"state_updated": time.time()})
rc, err = bstop(A, transcript("ship it", COMMIT)); check("board: every item touched: no question", rc == 0 and err == "", err[:300])
fresh()
def early_marked(tp):      # the turn's early question went out: the session's state carries the turn's start as its `early` mark
    st = p.load_state(A); st["early"] = st["early_asked"] = p.turn_activity(tp)["start"]; p.save_state(A, st); return tp
tpn = transcript("ship it", COMMIT)
rc, err = bstop(A, tpn, mode="note"); check("note: the board question does not hold the turn", rc == 0 and err == "", (rc, err[:200]))
check("note: …and is logged as a note", blog("note") and blog("note")[-1]["items"] == ["s5", "s6"], blog("note")[-1:])
out = nnag(A)
check("note: no early question was asked that turn: the next prompt says the full question, as before", out.count("[board] About your last turn: BOARD: this turn did real work (a commit)") == 1
      and "Does anything from it change them" in out and 's5 "[home] item 5"' in out and "unanswered last turn" not in out, out[:300])
check("note: …once", "[board]" not in nnag(A), "said twice")
fresh(); rc, err = bstop(A, early_marked(transcript("ship it", COMMIT)), mode="note")
out = nnag(A); check("note: the early question was asked that turn: the next prompt says it in one line", out.strip() == '[board] Board question unanswered last turn: s5 "[home] item 5", s6 "[home] item 6". Answer it in the reply.', out[:300])
check("note: …and does not repeat the full question", "BOARD: this turn did real work" not in out and "Does anything from it change them" not in out and len(out) < 200, len(out))
fresh(); rc, err = bstop(A, early_marked(transcript("ship it", COMMIT, "Pushed.\n\nBoard: no change, ok")), mode="note")
out = nnag(A); check("note: the one line keeps the rejected-lines text", out.strip().endswith("Answer it in the reply. Not accepted from your reply: «Board: no change, ok» (the reason is under three words)."), out[-300:])
_many = [{"gid": f"s{n}", "subject": f"item {n}"} for n in range(40, 50)]
_nine = [{"gid": f"s{n}", "subject": f"item {n}"} for n in range(40, 49)]
_eight = _nine[:8]
check("note: nine items are eight and `and 1 more`; eight are all named", p.board_unanswered(_nine).endswith(", and 1 more. Answer it in the reply.") and "more" not in p.board_unanswered(_eight), (p.board_unanswered(_nine), p.board_unanswered(_eight)))
check("note: the one line names at most 8 items and counts the rest", p.board_unanswered(_many).endswith(", and 2 more. Answer it in the reply.") and "s47" in p.board_unanswered(_many) and "s48" not in p.board_unanswered(_many), p.board_unanswered(_many))
rc, err = bstop(A, transcript("ship it", COMMIT), mode="note"); rc, err = bstop(A, transcript("ship it again", COMMIT), mode="note")
out = nnag(A); check("note: two turns before a prompt: both notes, oldest first", out.count("[board] About your last turn: BOARD:") == 2, out[:300])
rc, err = bstop(A, transcript("ship it", COMMIT), mode="block")
check("note: block mode still holds the turn with the full question", rc == 2 and err.startswith("BOARD: this turn did real work (a commit)") and "Does anything from it change them" in err, err[:200])
fresh()
rc, err = bstop(A, transcript("ship it", COMMIT, "Pushed.\n\nBoard: no change, the commit is unrelated to them"))
check("board: `Board: no change, <three words>` covers every item and is logged", rc == 0 and blog("verdict")[-1]["items"] == ["s5", "s6"]
      and "unrelated to them" in blog("verdict")[-1]["note"], (rc, err[:200]))
rc, err = bstop(A, transcript("ship it", COMMIT, "Pushed.\nBoard s5: no change, the commit was elsewhere"))
check("board: `Board s5: …` covers one of two; the question names only the other", rc == 2 and 's6 "[home] item 6"' in err and "s5 " not in err, err[:300])
rc, err = bstop(A, transcript("ship it", COMMIT, "Pushed.\n- **Board `S5`:** no change — the commit was elsewhere\nBoard s6: no change, nothing in it moved"))
check("board: one line per item, a list marker, bold and a backticked id are fine", rc == 0, err[:300])
rc, err = bstop(A, transcript("ship it", COMMIT, "プッシュしました。\nボード: 変更なし, このコミットは 全く 無関係です"))
check("board: the Japanese line passes", rc == 0, err[:200])
rc, err = bstop(A, transcript("ship it", COMMIT, "Pushed.\nBoard: no change")); check("board: a bare 'no change' does not pass", rc == 2, err[:120])
# a bare `[quiet]` was once accepted silently as "no change" for every item (rulebook
# ledger-hub 015dc0d, retired 015ec0d). That acceptance is gone: a reply of just `[quiet]` is an ordinary reply with no Board lines.
nb, nn = len(blog("block")), len(blog("note"))
rc, err = bstop(A, transcript("ship it", COMMIT, "[quiet]")); check("quiet: a reply of exactly [quiet] is an ordinary reply: asked", rc == 2 and err.startswith("BOARD: this turn did real work") and "s5 " in err and "s6 " in err, (rc, err[:200]))
rc, err = bstop(A, transcript("ship it", COMMIT, "  [quiet]\n")); check("quiet: [quiet] with surrounding whitespace: asked", rc == 2 and "s5 " in err and "s6 " in err, (rc, err[:200]))
rc, err = bstop(A, transcript("ship it", COMMIT), last_assistant_message="[quiet]\n"); check("quiet: [quiet] as the payload's last message: asked", rc == 2 and "s5 " in err and "s6 " in err, (rc, err[:200]))
check("quiet: …and the asks are logged as blocks", len(blog("block")) > nb, (nb, blog("block")[-1:]))
p.save_state(A, {}); rc, err = bstop(A, transcript("ship it", COMMIT, "[quiet]"), mode="note")
check("quiet: note mode: kept for the next prompt like any reply without Board lines", rc == 0 and err == "" and "[board]" in nnag(A) and len(blog("note")) > nn, (rc, err[:200], nnag(A)[:200]))
rc, err = bstop(A, transcript("ship it", COMMIT, "[quiet] done")); check("quiet: `[quiet] done` is an ordinary reply: asked", rc == 2 and err.startswith("BOARD: this turn did real work") and "s5 " in err and "s6 " in err, (rc, err[:200]))
rc, err = bstop(A, transcript("ship it", COMMIT, "Merged the PR.\n\n[quiet]")); check("quiet: [quiet] inside a longer reply: asked", rc == 2 and "s5 " in err and "s6 " in err, (rc, err[:200]))
rc, err = bstop(A, transcript("ship it", COMMIT, "Merged the PR.\n\n[quiet]\nBoard: no change, nothing here moved")); check("quiet: [quiet] beside valid Board lines: the lines count as usual", rc == 0, (rc, err[:200]))
rc, err = bstop(A, transcript("ship it", COMMIT, "Merged the PR.")); check("quiet: a reply without it: asked as before", rc == 2 and "s5 " in err and "s6 " in err, (rc, err[:200]))
rc, err = bstop(A, transcript("ship it", COMMIT, "Pushed.\nBoard: no change, unrelated work")); check("board: a two-word reason does not pass", rc == 2, err[:120])
rc, err = bstop(A, transcript("ship it", COMMIT, "Pushed.\nBoard s8: no change, not one of mine at all")); check("board: a line for an item it does not own covers nothing", rc == 2 and "s5 " in err and "s6 " in err, err[:200])
rc, err = bstop(A, transcript("ship it", COMMIT, "Pushed.", lead="Board: no change, said before the tools ran")); check("board: a line before the work is not the turn's last word", rc == 2, err[:120])
rc, err = bstop(A, transcript("ship it", COMMIT, "Pushed.\nBoard s5, `s6`: no change, the commit was elsewhere"))
check("board: several ids in one line pass", rc == 0 and blog("verdict")[-1]["items"] == ["s5", "s6"], err[:300])
rc, err = bstop(A, transcript("ship it", COMMIT, "Pushed.\nBoard [s5](https://stackshot.example/items/s5), `[s6](https://stackshot.example/items/s6)`: no change, the commit was elsewhere"))
check("board: linked ids, as replies show them since #98, pass", rc == 0 and blog("verdict")[-1]["items"] == ["s5", "s6"], err[:300])
rc, err = bstop(A, transcript("ship it", COMMIT, "Pushed.\nBoard s5 and s6: no change, ok"))
check("board: a rejected line is quoted with why after the question", rc == 2 and err.rstrip().endswith("Not accepted from your reply: «Board s5 and s6: no change, ok» (the reason is under three words)."), err[-300:])
# several items are answered with a
# `Board:` line and one bullet per item under it; each bullet counts for its own item, with the same three-word reason rule
rc, err = bstop(A, transcript("ship it", COMMIT, "Pushed.\n\nBoard:\n- s5: no change, the commit was elsewhere\n- s6: no change, nothing in it moved"))
check("bullets: a `Board:` line and one bullet per item covers each", rc == 0 and blog("verdict")[-1]["items"] == ["s5", "s6"], (rc, err[:300]))
rc, err = bstop(A, transcript("ship it", COMMIT, "Pushed.\n\n**Board:**\n\n* **s5**: no change — the commit was elsewhere\n\n• `s6`: no change, nothing in it moved"))
check("bullets: bold header, blank lines between, `*` and `•` markers, bold and backticked ids", rc == 0 and blog("verdict")[-1]["items"] == ["s5", "s6"], (rc, err[:300]))
rc, err = bstop(A, transcript("ship it", COMMIT, "プッシュしました。\n\nボード:\n- s5: 変更なし, このコミットは 全く 無関係です\n- s6: 変更なし, この 項目も そのままです"))
check("bullets: the Japanese `ボード:` header with bullets passes", rc == 0, (rc, err[:300]))
rc, err = bstop(A, transcript("ship it", COMMIT, "Pushed.\nBoard s5: no change, the commit was elsewhere\n\nBoard:\n- s6: no change, nothing in it moved"))
check("bullets: a one-line `Board s5: …` and a bullet block in one reply both count", rc == 0 and blog("verdict")[-1]["items"] == ["s5", "s6"], (rc, err[:300]))
rc, err = bstop(A, transcript("ship it", COMMIT, "Pushed.\nBoard:\n- s5: no change, the commit was elsewhere\n- s6: no change, ok"))
check("bullets: a bullet with a short reason is refused for its item only, quoted with why", rc == 2 and 's6 "[home] item 6"' in err and "s5 " not in err
      and err.rstrip().endswith("Not accepted from your reply: «- s6: no change, ok» (the reason is under three words)."), err[-400:])
rc, err = bstop(A, transcript("ship it", COMMIT, "Pushed.\nBoard:\n- s5: no change, the commit was elsewhere\nThat is all for now.\n- s6: no change, nothing in it moved"))
check("bullets: the block ends at the first line that is neither a bullet nor blank", rc == 2 and 's6 "[home] item 6"' in err and "s5 " not in err, err[:300])
rc, err = bstop(A, transcript("ship it", COMMIT, "Pushed.\nBoard:   \n\nNothing else."))
check("bullets: a bare `Board:` with no bullets covers nothing and is not quoted as a refused line", rc == 2 and "s5 " in err and "s6 " in err and "Not accepted" not in err, err[-300:])
rc, err = bstop(A, transcript("ship it", COMMIT, "Pushed.\nBoard:\n- s5: no change, the commit was elsewhere\n- s6, s8: no change, nothing in them moved"))
check("bullets: a bullet may name several ids; one this check does not ask about is ignored", rc == 0 and blog("verdict")[-1]["items"] == ["s5", "s6"], (rc, err[:300]))
fresh(s5={"state_updated": time.time()})
rc, err = bstop(A, transcript("ship it", COMMIT, "Pushed.\nBoard:\n- s5: updated, the next step names the PR\n- s6: no change, nothing in it moved"))
check("bullets: `- s5: updated, <what>` for an item the turn updated stands beside the others", rc == 0 and "Not accepted" not in err, (rc, err[:300]))
fresh()
rej_ = []; got_, _ = p.board_verdicts("Board:\n- board#5: no change, the commit was elsewhere\n- board#6: no change, too short\n\nDone.\n- board#7: no change, after the block ends", ["g5", "g6", "g7"], rej_)
check("bullets: board_verdicts reads each bullet for its own item", sorted(got_) == ["g5"] and rej_ == [("- board#6: no change, too short", "the reason is under three words")], (got_, rej_))
# the board item: items are written as shown (store g12) and board-tmp-<machine>#3 (store l3), in every
# text the check shows a session, and a Board line may name them so (#12 too), or by the store id as before
from stackshot.github import ghsync as _ghs
TMP = _ghs.local_prefix()
def gl_items(*rows):
    for d in ("g", "l"):
        (T / f"store/{d}").mkdir(exist_ok=True)
        for f in (T / f"store/{d}").glob("*.json"): f.unlink()
    for gid, owner in rows:
        (T / f"store/{gid[0]}/{gid[1:]}.json").write_text(json.dumps({"id": gid[1:], "subject": f"[home] item {gid}", "description": "x", "status": "open",
            "state_updated": OLD, "updated": OLD, "metadata": {"owner": owner, "mover": owner, "project": "projects/alpha", "next": f"step one of {gid}"}}))
fresh(); gl_items(("g12", A), ("l3", A), ("g13", B))
rc, err = bstop(A, transcript("ship it", COMMIT))
check("the question names an issue-numbered item board#<a> and a temporary one as shown, never the store id",
      rc == 2 and 'board#12 "[home] item g12" (you are still its mover; next: step one of g12)' in err and f'{TMP}#3 "[home] item l3"' in err and "g12 " not in err and "l3 " not in err
      and 's5 "[home] item 5"' in err and "board#13" not in err, err[:700])
check("…the block log keeps the store ids", blog("block")[-1]["items"] == ["g12", "l3", "s5", "s6"], blog("block")[-1:])
rc, err = bstop(A, transcript("ship it", COMMIT, f"Pushed.\nBoard board#12: no change, the commit was elsewhere\nBoard {TMP}#3: no change, nothing in it moved"))
check("`Board board#<a>: …` and `Board board-tmp-<machine>#3: …` are accepted and cover those items only", rc == 2 and "board#12 " not in err and f"{TMP}#3 " not in err
      and 's5 "[home] item 5"' in err and "Not accepted" not in err, err[:500])
rc, err = bstop(A, transcript("ship it", COMMIT, f"Pushed.\nBoard #12, `{TMP}-3`, s5 and [board#5](https://x/items/5): no change, the commit was elsewhere\nBoard S6: no change, nothing in it moved"))
check("#12, board-tmp-<machine>-3, a store id and a linked id in one line pass, normalized to the store ids", rc == 0 and blog("verdict")[-1]["items"] == ["g12", "l3", "s5", "s6"], (rc, err[:400], blog("verdict")[-1:]))
rc, err = bstop(A, transcript("ship it", COMMIT, "Pushed.\nBoard g12, l3, s5, s6: no change, the commit was elsewhere"))
check("the store ids still pass", rc == 0 and blog("verdict")[-1]["items"] == ["g12", "l3", "s5", "s6"], (rc, err[:300]))
rc, err = bstop(A, transcript("ship it", COMMIT, "Pushed.\nBoard board#12 and a draft: no change, the commit was elsewhere"))
check("a line that is not a list of ids is still refused, quoted with why", rc == 2 and "«Board board#12 and a draft: no change, the commit was elsewhere» (the part before the colon is not a list of item ids)" in err, err[-400:])
rc, err = bstop(A, transcript("ship it", COMMIT, f"Pushed.\nBoard s5: no change, the commit was elsewhere\n\nBoard:\n- [board#12](https://board.example.org/items/12): no change, the commit was elsewhere\n- `{TMP}#3`: no change, nothing in it moved\n- [s6](https://x/items/s6): no change, nothing in it moved"))
check("bullets: linked and temporary ids in bullets, beside a one-line verdict, pass as the store ids", rc == 0 and blog("verdict")[-1]["items"] == ["g12", "l3", "s5", "s6"], (rc, err[:400], blog("verdict")[-1:]))
rc, err = bstop(A, transcript("ship it", COMMIT, "Pushed.\nBoard [board#12](https://board.example.org/items/12), [s5](https://board.example.org/items/s5): no change, the commit was elsewhere"))
check("bullets: the linked one-line list still passes", rc == 2 and "board#12 " not in err and "s5 " not in err and "s6 " in err and "Not accepted" not in err, err[:400])
st_, _, body_ = client_reads_svc._client_get("items", {"key": A}); rows_ = {i["gid"]: i for i in json.loads(body_)["items"]}
check("the items read says how each item is shown", rows_["g12"]["shown"] == "board#12" and rows_["l3"]["shown"] == f"{TMP}#3" and rows_["s5"]["shown"] == "s5", rows_)
def fstop2(final):
    p.save_state(A, {}); CALLS.clear(); bstop(A, transcript("report", [], final), mode="note"); return nnag(A)
out = fstop2("Done.\nBoard board#13: no change, its owner runs it")
check("a Board line about another session's item, written as board#<n>: the note names it so, the log the store id",
      "[board] About your last turn's Board lines: board#13 is moved by home-beta; leave it out, or say why it's yours to report." in out and "g13" not in out
      and blog("foreign")[-1]["items"] == ["g13"], (out[:400], blog("foreign")[-1:]))
st_, _, body_ = client_reads_svc._client_get("item-facts", {"key": A, "ids": "g13,s5"}); f_ = json.loads(body_)["items"]
check("item-facts says how each item is shown", f_["g13"]["shown"] == "board#13" and f_["s5"]["shown"] == "s5", f_)
check("a page debt names the item that changed as shown", p.describe("projects/alpha", {"ts": int(time.time()), "task": "g12"}).startswith("board item board#12 changed")
      and p.describe("projects/alpha", {"ts": int(time.time()), "task": "s9"}).startswith("board item s9 changed"), p.describe("projects/alpha", {"ts": int(time.time()), "task": "g12"}))
gl_items(); fresh()
rc, err = bstop(A, transcript("ship it", COMMIT), last_assistant_message="Done.\nBoard: no change, the payload's own message")
check("board: the payload's last message is read first", rc == 0, err[:200])
items(*[(n, A, {}) for n in range(20, 30)])
rc, err = bstop(A, transcript("ship it", COMMIT)); check("board: at most eight are named, the rest counted", rc == 2 and "s27 " in err and "s28 " not in err and "; … and 2 more. Does anything" in err, err[:900])
fresh(); CALLS.clear()
rc, err = bstop(S, transcript("ship it", COMMIT)); check("board: a session that owns nothing open: one call, no question", rc == 0 and CALLS == [("items", S)], (rc, err[:200], CALLS))
# the item: an item whose stored
# agent is this session is asked about too, marked as such; the default keeper link (no agent stored) never draws the question
items((11, A, {"meta": {"needs": ["work-osprey"]}}), (12, A, {}))
rc, err = bstop(S, transcript("ship it", COMMIT))
check("board: an item whose needs names this session is asked about, marked so; the default keeper's is not", rc == 2
      and 's11 "[home] item 11" (next: step one of s11; it names you in its needs: close it when your step completes it, or hand it on: set mover= to whoever takes it next)' in err and "s12 " not in err, err[:600])
rc, err = bstop(A, transcript("ship it", COMMIT)); check("board: …its owner is asked as before, without the mark", rc == 2 and 's11 "[home] item 11" (you are still its mover; next: step one of s11)' in err, err[:600])
rc, err = bstop(S, transcript("ship it", COMMIT, "Done.\nBoard s11: no change, my step has not run yet")); check("board: …and the agent's verdict line settles it", rc == 0, err[:300])
# the item: a Board line about an
# item the session neither owns nor is the linked agent of, or one already closed, gets a note at the next prompt, never a block
from stackshot.web import render as _rm
items((40, B, {}), (41, A, {"status": "completed", "meta": {"outcome": "done"}}), (42, B, {"meta": {"agent": A}}), (43, B, {"meta": {"mover": A}}))
CLOSED = _rm.when_words(p.datetime.datetime.fromtimestamp(OLD, _wt_text.ZONE))
def fstop(tools, final, mode="note"):
    p.save_state(A, {}); CALLS.clear(); rc, err = bstop(A, transcript("report", tools, final), mode=mode); return rc, err, nnag(A)
rc, err, out = fstop([], "Done.\nBoard s40: no change, its owner runs it")
check("foreign: a Board line about another session's item: a note naming its owner", rc == 0 and err == ""
      and f"[board] About your last turn's Board lines: s40 is moved by home-beta; leave it out, or say why it's yours to report." in out, (rc, err[:200], out[:400]))
check("foreign: …one item-facts read, keyed by the session", ("item-facts", A) in CALLS, CALLS)
check("foreign: …logged", blog("foreign") and blog("foreign")[-1]["items"] == ["s40"], blog("foreign")[-1:])
rc, err, out = fstop([], "Done.\nBoard s40: no change, its owner runs it", mode="block")
check("foreign: block mode: still a note, never a block", rc == 0 and err == "" and "s40 is moved by" in out, (rc, err[:200], out[:300]))
rc, err, out = fstop([], "Merged.\nBoard s41: done, merged and live")
check("foreign: a Board line about a closed item of its own: when and how it ended", f"s41 was completed {CLOSED} (done)." in out and "owned by" not in out, out[:400])
rc, err, out = fstop([], "Done.\nBoard [s40](https://x/items/s40), s41: no change, nothing moved here")
check("foreign: several ids, linked: one line each", "s40 is moved by" in out and f"s41 was completed {CLOSED} (done)" in out, out[:400])
rc, err, out = fstop([], "Done.\nBoard:\n- s42: no change, my step has not run\n- s40: no change, its owner runs it")
check("foreign: a bullet about another session's item is noted like a line", "s40 is moved by home-beta" in out and "s42" not in out, out[:400])
rc, err, out = fstop([], "Done.\nBoard s43: no change, my step has not run")
check("foreign: an item this session moves (mover is the session, the keeper of record is another) is its own to report: no note", "s43" not in out and rc == 0, (rc, err[:200], out[:400]))
rc, err, out = fstop([], "Done.\nBoard s42: no change, my step has not run")
check("foreign: the item's linked agent is not noted", rc == 0 and "Board lines" not in out, out[:400])
rc, err, out = fstop([(ST + "update", {"item_id": "s40", "next": "x", "sender": A})], "Handed back.\nBoard s40: updated, my step is done")
check("foreign: a session that wrote to the item with sender= this turn is not noted, and nothing is read", "Board lines" not in out and ("item-facts", A) not in CALLS, (out[:300], CALLS))
rc, err, out = fstop([(ST + "complete", {"item_id": "s41", "outcome": "done"})], "Closed.\nBoard s41: completed, merged and live")
check("foreign: an item the turn closed itself is not noted", "About your last turn's Board lines" not in out and "s41 was" not in out, out)
rc, err, out = fstop([], "Done, nothing on the board.")
check("foreign: a reply without a Board line: no read", "Board lines" not in out and ("item-facts", A) not in CALLS, CALLS)
rc, err, out = fstop([], "Done.\nBoard s99: no change, an id nobody has")
check("foreign: an unknown id is left alone", "Board lines" not in out, out[:300])
rc, err, out = fstop([], "Done.\nBoard s40: no change, its owner runs it", mode="off")
check("foreign: board check off: nothing", "Board lines" not in out and not CALLS, (out[:200], CALLS))
st, _, body = client_reads_svc._client_get("item-facts", {"key": A, "ids": "s40,s41,s42,s99"}); f = json.loads(body)["items"]
check("foreign: item-facts says mover, then (mine), agent and the close", st == 200 and f["s40"]["mine"] is False and f["s41"]["mine"] is False
      and f["s41"]["outcome"] == "done" and f["s42"]["agent"] is True and "s99" not in f, f)
check("foreign: item-facts refuses a bad id list", client_reads_svc._client_get("item-facts", {"key": A, "ids": "x; rm"})[0] == 400)
items((10, S, {}))
(T / "touch" / f"{S}.json").write_text(json.dumps({"touches": {"projects/beta": {"ts": int(time.time()) + 1000, "task": "s9"}}}))
rc, err = bstop(S, transcript("ship it", COMMIT))
check("board: with a page debt, the Stop line is the board question alone, no page part", rc == 2 and err.startswith("BOARD: this turn did real work (a commit)")
      and 's10 "[home] item 10"' in err and "PROJECT PAGE" not in err and "board item s9" not in err and err.split("\nItems with no stored state:")[0].count("\n") <= 1, err[:400])
check("board: …the page debt stays for nag to say", "projects/beta" in (p.load_state(S).get("touches") or {}) and "[project-page] board item s9 changed" in nnag(S), p.load_state(S))
rc, err = bstop(S, transcript(NOTICE, TL + COMMIT))
check("board: a keeper's page write beside the work: the board question, no page question", rc == 2 and err.startswith("BOARD: this turn did real work (gbrain add_timeline_entry, a commit)")
      and "This turn wrote something" not in err and "Page" not in err and "### projects/" not in err, err[:400])
rc, err = bstop(S, transcript(NOTICE, TL + COMMIT), mode="note"); out = nnag(S)
check("note: the same, kept for the next prompt: the board question only", rc == 0 and err == "" and "[board] About your last turn: BOARD:" in out
      and "[project-page] About your last turn" not in out and "Page:" not in out, (rc, err[:200], out[:400]))
(T / "touch" / f"{S}.json").unlink()
# ---- 9. the end-of-turn board question asked early (the item move 3): the turn's first
# state-changing board write gets it as PostToolUse additionalContext, once per turn; the Stop check stays the fallback. The page
# part of it is no longer asked.
def touch(sid, tp, inp, bm="block", tool="update", resp=None):
    pl = {"session_id": sid, "transcript_path": tp, "tool_name": ST + tool, "tool_input": inp,
          "tool_response": resp if resp is not None else f"updated [{inp.get('item_id', 's5')}](https://x/items/{inp.get('item_id', 's5')}).\nproject: projects/alpha"}
    r = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/projects/pages.py"), "touch"], input=json.dumps(pl), capture_output=True, text=True,
                       env={**os.environ, "BOARD_CHECK_MODE": bm})
    if r.returncode != 0 or not r.stdout.strip(): return r.returncode, ""
    try: return r.returncode, json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    except Exception: return r.returncode, "UNPARSED " + r.stdout
fresh(); p.save_state(A, {}); p.save_state(S, {})
tpa = transcript("ship it", [(ST + "update", {"item_id": "s5", "next": "x"})])
rc, q = touch(A, tpa, {"item_id": "s5", "next": "go on"})
check("early: the first board write of a turn gets the board question as context, in the reply's own words",
      rc == 0 and q.startswith("[stackshot] Board question (once per turn). Items untouched this turn: ") and 's6 "[home] item 6"' in q
      and "Page" not in q and "page" not in q
      and "`Board: no change, <reason>`" in q and "s7 " not in q and "s8 " not in q, q)
check("early (quiet retired, Thu Oct 15th 2026): the question no longer advertises a [quiet] reply", "quiet" not in q.lower(), q)
check("early: the examples name items as shown, `board#N`, never a store id", "`- board#N: no change, <reason>`" in q and "Board s5" not in q, q)
check("early (bullets): the question asks for a `Board:` line and one bullet per item for several items",
      "`Board: no change, <reason>` (3+ words) for all, or a `Board:` line plus one bullet per item on its own line (`- board#N: no change, <reason>` / `- board#M: updated, <what>`)" in q
      and "If this turn changes one, update it (confirm only if still true)" in q and "Only items you move or are named in the needs of." in q, q)
check("early: bullets go under a `Board:` line, each on its own line; confirm only when still true; the still-mover note is kept",
      "a `Board:` line plus one bullet per item on its own line" in q and "confirm only if still true" in q
      and "The role beside an item is the server's reading now" in q, q)
check("early: the fixed text is under 400 characters and keeps the three-word reason and the update-or-confirm instruction",
      300 <= len(q.split(": s5")[0]) + len(q[q.index(". If this turn changes"):q.index("needs of.") + 9]) <= 400 and "(3+ words)" in q and "update it (confirm only if still true)" in q, q)
rc, q2 = touch(A, tpa, {"item_id": "s6", "next": "and on"}); check("early: once per turn: the next write in the same turn gets nothing", rc == 0 and q2 == "", q2)
time.sleep(1.1); rc, q3 = touch(A, transcript("next prompt", []), {"item_id": "s5", "next": "again"})
check("early: a later turn is asked again", q3.startswith("[stackshot]"), q3)
# the other writes a turn ends on, once the hook's matcher names them: they owe no page, but the turn's first is asked
def otouch(sid, tp, tool, inp, bm="block", resp="ok"):
    pl = {"session_id": sid, "transcript_path": tp, "tool_name": tool, "tool_input": inp, "tool_response": resp}
    r = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/projects/pages.py"), "touch"], input=json.dumps(pl), capture_output=True, text=True,
                       env={**os.environ, "BOARD_CHECK_MODE": bm})
    try: return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else ""
    except Exception: return "UNPARSED " + r.stdout
for prompt, tool, inp in (("ship", "SendMessage", {"to": "x", "message": "hi"}), ("ship", ST + "message", {"to": "x"}),
                          ("ship", ST + "anchors", {"project": "projects/alpha", "add": ["https://x"]}), ("ship", "Bash", {"command": "git -C /x commit -qm y"}),
                          ("ship", "Bash", {"command": "cd x && git push -u origin b"}), ("ship", "Bash", {"command": "gh pr create --base main"}),
                          (NOTICE, GB + "put_page", {"slug": "projects/alpha"}), (NOTICE, GB + "edit_page", {}), (NOTICE, GB + "add_timeline_entry", {}),
                          (NOTICE, GB + "capture", {})):
    p.save_state(A, {}); time.sleep(1.05)
    q = otouch(A, transcript(prompt, []), tool, inp)
    nm = tool.rsplit("__", 1)[-1] + (" " + inp["command"][:30] if tool == "Bash" else "")
    check(f"early: {nm} is asked too", q.startswith("[stackshot]") and 's6 "[home] item 6"' in q, q)
    check(f"early: {nm} owes no page itself", not (p.load_state(A).get("touches") or {}), p.load_state(A))
for prompt, tool, inp in (("ship", ST + "anchors", {"project": "projects/alpha"}), ("ship", ST + "route", {"notice": "abc123"}),
                          ("ship", GB + "put_page", {}), ("ship", GB + "add_timeline_entry", {}),
                          (NOTICE, GB + "search", {}), (NOTICE, GB + "get_page", {}), ("ship", ST + "get", {}),
                          (PEER, "Bash", {"command": "ls"}),
                          ("ship", "Bash", {"command": "ls"}), ("ship", "Bash", {"command": "git status"}), ("ship", "Read", {})):
    p.save_state(A, {}); time.sleep(1.05)
    check(f"early: not a write the Stop check counts, nothing asked: {prompt[:8]} {tool.rsplit('__', 1)[-1]} {json.dumps(inp)[:50]}", otouch(A, transcript(prompt, []), tool, inp) == "")
p.save_state(A, {}); time.sleep(1.05)
check("early: a refused or failed write asks nothing", otouch(A, transcript("ship", []), ST + "message", {"to": "x"}, resp="Refused: no such session") == ""
      and otouch(A, transcript("ship", []), "SendMessage", {}, resp={"isError": True, "content": "x"}) == "")
p.save_state(A, {}); time.sleep(1.05); tpm = transcript("talk", [])
q1 = otouch(A, tpm, "SendMessage", {}); q2 = otouch(A, tpm, ST + "message", {"to": "x"})
check("early: once per turn across kinds: a message, then another write, asked once", q1.startswith("[stackshot]") and q2 == "", (q1[:80], q2[:80]))
p.save_state(A, {})
rc, q = touch(A, transcript("ship", []), {"item_id": "s5", "priority": "p1"}); check("early: a filing edit is not a state change and asks nothing", q == "", q)
rc, q = touch(A, transcript("ship", []), {"item_id": "s5", "next": "x"}, resp="Refused: something"); check("early: a refused write asks nothing", q == "", q)
rc, q = touch(A, transcript("ship", []), {"item_id": "s5", "next": "x"}, bm="off"); check("early: the board check off: nothing asked", q == "", q)
rc, q = touch(A, transcript("ship", []), {"item_id": "s5", "next": "x"}, bm="note"); check("early: note mode asks the same, early", 's6 "[home] item 6"' in q, q)
# a call made inside a subagent carries agent_id in its hook input: it asks nothing and keeps no early mark
def atouch(sid, tp, tool, inp, resp):
    pl = {"session_id": sid, "transcript_path": tp, "tool_name": tool, "tool_input": inp, "tool_response": resp, "agent_id": "ag1", "agent_type": "general-purpose"}
    r = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/projects/pages.py"), "touch"], input=json.dumps(pl), capture_output=True, text=True,
                       env={**os.environ, "BOARD_CHECK_MODE": "block"})
    return r.returncode, r.stdout
p.save_state(A, {}); time.sleep(1.05); tps = transcript("sub work", [])
rc, out = atouch(A, tps, ST + "update", {"item_id": "s5", "next": "z"}, "updated [s5](https://x/items/s5).\nproject: projects/alpha")
check("early: a board write inside a subagent asks nothing", rc == 0 and out.strip() == "", out)
check("early: …and does not count as the turn's question (no early mark kept)", not p.load_state(A).get("early"), p.load_state(A))
p.save_state(S, {}); items((10, S, {})); time.sleep(1.05)
rc, out = atouch(S, transcript("keeper sub", []), ST + "update", {"item_id": "s10", "next": "z"}, "updated [s10](https://x/items/s10).\nproject: projects/alpha")
check("early: a subagent's board write still records the page debt, and asks nothing", out.strip() == "" and (p.load_state(S).get("touches") or {}).get("projects/alpha", {}).get("task") == "s10", (out, p.load_state(S)))
p.save_state(A, {}); fresh()
rc, out = atouch(A, tps, "SendMessage", {}, "ok")
check("early: any other write inside a subagent asks nothing and keeps no early mark", rc == 0 and out.strip() == "" and not p.load_state(A).get("early"), (out, p.load_state(A)))
p.save_state(A, {}); time.sleep(1.05); tpt = transcript("agent session", [])
pl_ = {"session_id": A, "transcript_path": tpt, "tool_name": "SendMessage", "tool_input": {}, "tool_response": "ok", "agent_type": "general-purpose"}
r_ = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/projects/pages.py"), "touch"], input=json.dumps(pl_), capture_output=True, text=True, env={**os.environ, "BOARD_CHECK_MODE": "block"})
check("early: a payload with agent_type and no agent_id (a main session started with --agent) is still asked", r_.returncode == 0 and "[stackshot] Board question" in r_.stdout, r_.stdout[:200])
p.save_state(A, {}); time.sleep(1.05); tps = transcript("sub work 2", [])
rc, q = touch(A, tps, {"item_id": "s5", "next": "z"})
check("early: the same turn's main-session write after the subagent's is still asked", q.startswith("[stackshot] Board question"), q)
# the Stop note is one line only when the early question really went out that turn: the `early` mark alone (set when nothing was asked) is not that
_url0 = os.environ["STACKSHOT_URL"]
def note_after(setup, early_url=None):
    fresh(**setup); p.save_state(A, {}); time.sleep(1.05); tpe = transcript("ship it", COMMIT)
    if early_url: os.environ["STACKSHOT_URL"] = early_url
    try: q_ = otouch(A, tpe, "Bash", {"command": "git -C /x commit -qm y"})
    finally: os.environ["STACKSHOT_URL"] = _url0
    return q_, tpe
def stop_note(tpe):
    rc_, err_ = bstop(A, tpe, mode="note"); return nnag(A)
FULL_NOTE = "[board] About your last turn: BOARD: this turn did real work"
ONE_LINE = "[board] Board question unanswered last turn: "
q_, tpe = note_after({}, early_url="http://127.0.0.1:9")
check("early-asked: the server did not answer at the early call: nothing asked, an `early` mark but no `early_asked`", q_ == "" and p.load_state(A).get("early") and not p.load_state(A).get("early_asked"), (q_, p.load_state(A)))
o_ = stop_note(tpe); check("early-asked: …so the next prompt says the full question, not the one line", FULL_NOTE in o_ and ONE_LINE not in o_, o_[:200])
items(); p.save_state(A, {}); time.sleep(1.05); tpe = transcript("ship it", COMMIT)
q_ = otouch(A, tpe, "Bash", {"command": "git -C /x commit -qm y"}); fresh()
check("early-asked: the server gave an empty item list at the early call: nothing asked, no `early_asked`", q_ == "" and p.load_state(A).get("early") and not p.load_state(A).get("early_asked"), (q_, p.load_state(A)))
o_ = stop_note(tpe); check("early-asked: …so the next prompt says the full question", FULL_NOTE in o_ and ONE_LINE not in o_, o_[:200])
fresh(s5={"confirmed": time.time() + 600}, s6={"state_updated": time.time() + 600}); p.save_state(A, {}); time.sleep(1.05); tpe = transcript("ship it", COMMIT)
q_ = otouch(A, tpe, "Bash", {"command": "git -C /x commit -qm y"}); fresh()
check("early-asked: nothing due at the early call: nothing asked, no `early_asked`", q_ == "" and p.load_state(A).get("early") and not p.load_state(A).get("early_asked"), (q_, p.load_state(A)))
o_ = stop_note(tpe); check("early-asked: …so the next prompt says the full question", FULL_NOTE in o_ and ONE_LINE not in o_, o_[:200])
fresh(); p.save_state(A, {}); time.sleep(1.05); tpe = transcript("ship it", COMMIT)
q_ = otouch(A, tpe, "Bash", {"command": "git -C /x commit -qm y"})
check("early-asked: asked: the question went out and `early_asked` is kept with the turn's start", q_.startswith("[stackshot] Board question") and p.load_state(A).get("early_asked") == p.load_state(A).get("early"), (q_[:60], p.load_state(A)))
o_ = stop_note(tpe); check("early-asked: …and then the next prompt says it in one line", o_.strip().startswith(ONE_LINE) and "BOARD: this turn" not in o_, o_[:200])
# a parallel hook saves state (a board write's page debt) while the early question waits on the server: the debt must survive, and `early_asked` is still set
fresh(); p.save_state(A, {}); time.sleep(1.05); tpr = transcript("ship it", COMMIT)
_real_owned = lambda sid: [{"gid": "s5", "subject": "[home] item 5", "state_updated": 1, "updated": 1}]; _orig_owned = p.owned_items
def _racing_owned(sid):
    r_ = _real_owned(sid); st_r = p.load_state(sid); st_r.setdefault("touches", {})["projects/racer"] = {"ts": int(time.time()), "task": "s5", "tool": "update"}; p.save_state(sid, st_r); return r_
p.owned_items = _racing_owned; _bm0 = os.environ.get("BOARD_CHECK_MODE"); os.environ["BOARD_CHECK_MODE"] = "block"
try: q_ = p.early_question({"session_id": A, "transcript_path": tpr, "tool_name": "Bash", "tool_input": {"command": "git -C /x commit -qm y"}, "tool_response": "ok"})
finally:
    p.owned_items = _orig_owned
    if _bm0 is None: os.environ.pop("BOARD_CHECK_MODE", None)
    else: os.environ["BOARD_CHECK_MODE"] = _bm0
st_ = p.load_state(A)
check("early-asked: a page debt saved by a parallel hook during the server call survives, and `early_asked` is set", q_.startswith("[stackshot] Board question") and "projects/racer" in (st_.get("touches") or {}) and st_.get("early_asked") == st_.get("early") and st_.get("early_asked"), (q_[:50], st_))
p.save_state(A, {}); fresh()
# a page keeper (S keeps alpha and gamma): the early text carries the board question and nothing about its pages, and the board
# write's page debt is still recorded
p.save_state(S, {}); items((10, S, {}))
rc, q = touch(S, transcript("keeper ships", []), {"item_id": "s10", "next": "x"}, resp="updated [s10](https://x/items/s10).\nproject: projects/alpha")
check("early: a keeper gets the board question only: no Page line, no pages it keeps, no page owed", q.startswith("[stackshot] Board question")
      and 's10 "[home] item 10"' in q and "Page" not in q and "Pages you keep" not in q and "owe `projects/alpha`" not in q, q)
check("early: the touch still records the page debt and the item id from a linked reply", (p.load_state(S).get("touches") or {}).get("projects/alpha", {}).get("task") == "s10", p.load_state(S))
rc, q = touch(S, transcript("keeper ships again", []), {"item_id": "s10", "next": "y"}, resp="updated [s10](https://x/items/s10).\nproject: projects/alpha", bm="off")
check("early: with the board check off a keeper's write asks nothing at all, and still owes its page", q == "" and "projects/alpha" in (p.load_state(S).get("touches") or {}), (q, p.load_state(S)))
tps = transcript("keeper ships", [(ST + "update", {"item_id": "s10", "next": "x"})], "Updated.\nBoard: no change, it was the item itself")
rc, err = bstop(S, tps); check("early: a reply with the Board line and no Page line: the Stop check asks nothing", rc == 0 and err == "", (rc, err[:300]))
rc, err = bstop(S, transcript("keeper ships", [(ST + "update", {"item_id": "s10", "next": "x"})], "Updated."))
check("early: without it, the Stop check is still the board fallback, with no page part", rc == 2 and err.startswith("BOARD:") and "PROJECT PAGE" not in err, (rc, err[:200]))
p.save_state(S, {})
fresh()

os.environ["STACKSHOT_URL"] = "http://127.0.0.1:9"      # nothing listens: no answer, no block
rc, err = bstop(A, transcript("ship it", COMMIT)); check("board: the server out of reach: never a block", rc == 0 and err == "", err[:200])
IS.shutdown(); os.environ.pop("STACKSHOT_URL")
a = act(NOTICE, COMMIT); check("board: a commit is a write for the board check", a["writes"] and a["why"] == ["a commit"], a)
a = act(NOTICE, TL + COMMIT); check("board: beside a page write, both are said", a["writes"] and a["why"] == ["gbrain add_timeline_entry", "a commit"], a)
git("add", "-A"); git("commit", "-q", "-m", "later")    # S's pages as they stand, committed two hours back: before Oct 12th a page write asked again
rc, err = bstop(S, transcript(NOTICE, TL + COMMIT), mode="off")
check("stop: with the board check off, a keeper's unedited pages after a page write ask nothing (no page question at all)", rc == 0 and err == "", err[:300])
check("board: config: the example's default is off", p._cfg.board_check_mode() == "off")
p._cfg.CFG["board_check"] = {"mode": "block"}; check("board: config: block is read", p._cfg.board_check_mode() == "block" and p.board_mode() == "block")
p._cfg.CFG["board_check"] = {"mode": "nonsense"}; check("board: config: an unknown value is off", p._cfg.board_check_mode() == "off")
p._cfg.CFG.pop("board_check")

# ---- 9. a `keeper:` line on the page names the keeper among the page's own agents (readers only: nothing writes it yet)
fmpage("projects/mk.md", "type: project\ntitle: Mk\ndisplay-name: m-proj\nkeeper: m-proj-docs\nagents:\n  m-proj-main: talks\n  m-proj-docs: keeps the docs\n  background:\n    m-proj-eng: builds and merges\nstatus: active")
fmpage("projects/mk/sub.md", "type: project\ntitle: Mk sub")
fmpage("projects/mk/own.md", "type: project\ntitle: Mk own\nagent: m-proj-main")
fmpage("projects/mk-bad.md", "type: project\ntitle: Mk bad\ndisplay-name: m-bad\nkeeper: m-bad-nobody\nagents:\n  m-bad-main: talks\n  background:\n    m-bad-eng: builds\nstatus: active")
fmpage("projects/mk-none.md", "type: project\ntitle: Mk none\ndisplay-name: m-none\nagents:\n  m-none-main: talks\n  background:\n    m-none-eng: builds\nstatus: active")
real_reg4 = p.REG; p.REG = str(T / "registry-test4.json"); p.cmd_registry(quiet=True); R4 = json.loads(open(p.REG).read())["pages"]; p.REG = real_reg4
who4 = lambda k: (R4[k].get("session"), R4[k].get("role"))
check("keeper line: a name on the page's map is the keeper, role mark, the name line kept as legacy_session", who4("projects/mk") == ("m-proj-docs", "mark") and R4["projects/mk"]["legacy_session"] == "m-proj" and R4["projects/mk"]["keeper_source"] == "mark", R4["projects/mk"])
check("keeper line: a sub-page that names nobody inherits it; one with its own `agent:` line keeps that agent", who4("projects/mk/sub") == ("m-proj-docs", "inherited") and who4("projects/mk/own") == ("m-proj-main", "agent"), (who4("projects/mk/sub"), who4("projects/mk/own")))
check("keeper line: a name that is no agent of the page is ignored and reported; the old name line answers", who4("projects/mk-bad") == ("m-bad", "name") and len(R4["projects/mk-bad"]["keeper_problems"]) == 1 and "legacy_session" not in R4["projects/mk-bad"], R4["projects/mk-bad"])
check("no keeper line: the old fields answer and the derived keeper is the builder", who4("projects/mk-none") == ("m-none", "name") and R4["projects/mk-none"]["keeper_agent"] == "m-none-eng" and R4["projects/mk-none"]["keeper_source"] == "derived" and not ({"legacy_session", "keeper_problems"} & set(R4["projects/mk-none"])), R4["projects/mk-none"])
check("keeper line: every page without one reads as before (the same session and role as the old keys alone)", all((R4[k].get("session"), R4[k].get("role")) == (R[k].get("session"), R[k].get("role")) for k in R if k in R4 and k not in ("projects/mk", "projects/mk/sub")))
p.cmd_registry(quiet=True)    # the registry file the keeper lookups read
check("keeper_pages / keepers_any: the marked agent keeps its page and the page's sub-pages, the old name line still does, and a derived keeper keeps nothing by it",
      p.keeper_pages(S, "m-proj-docs") == ["projects/mk", "projects/mk/sub"] and p.keeper_pages(S, "m-proj") == ["projects/mk", "projects/mk/sub"] and p.keeper_pages(S, "m-proj-main") == ["projects/mk/own"]
      and p.keepers_any(["m-proj-docs"]) and p.keepers_any(["m-proj"]) and not p.keepers_any(["m-none-eng"]), (p.keeper_pages(S, "m-proj-docs"), p.keeper_pages(S, "m-proj"), p.keeper_pages(S, "m-proj-main")))

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": page currency scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
