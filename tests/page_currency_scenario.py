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
# ---- 1c. agent-listed: no agent before its `agents:` line (sala asks before a spawn or a rename); read from the files, not the registry
fmpage("projects/other.md", "type: project\ntitle: Other\ndisplay-name: s-hub")
fmpage("ops/hubhost.md", "type: note\ntitle: Host\ndisplay-name: s-hub")
fmpage("projects/deeper.md", "type: project\ntitle: Deeper\ndisplay-name: s-hub-main-x")
fmpage("projects/gone.md", "type: project\ntitle: Gone\ndisplay-name: s-gone\nstatus: completed")
al = p.agent_listed
check("agent-listed: a listed agent passes with its mandate", al("s-hub-main") == (0, "listed on projects/hub: upgrades, the curator"), al("s-hub-main"))
check("agent-listed: a folded mandate counts and prints whole", al("s-f-press") == (0, "listed on projects/folded: drafts and ships the newsletters, keeps the mailing list, and answers the subscribers"), al("s-f-press"))
check("agent-listed: an inline map counts (the old session: key names the project)", fmpage("projects/legacy.md", "type: project\ntitle: Legacy\nsession: old-name\nagents: {old-name-one: \"does x\"}") or al("old-name-one")[0] == 0, al("old-name-one"))
c, line = al("s-hub-new")
check("agent-listed: an unlisted name is refused, naming the page that lists agents and the line to add", c == 3 and "on projects/hub " in line and "`s-hub-new: <mandate>`" in line and "`display-name:` line is s-hub" in line, (c, line))
check("agent-listed: a background agent passes with its mandate (sala spawns and renames it)", al("s-bg-sweep") == (0, "listed on projects/bg: sweeps the inbox, Oliver's") and al("s-bg-watch") == (0, "listed on projects/bg: watches the releases and files them"), (al("s-bg-sweep"), al("s-bg-watch")))
check("agent-listed: a background agent in the inline form, and a front one beside it, pass", al("s-bgi-night")[0] == 0 and al("s-bgi-main") == (0, "listed on projects/bgi: talks"), (al("s-bgi-night"), al("s-bgi-main")))
check("agent-listed: the reserved background key is no agent's name", al("s-bg-background")[0] == 3, al("s-bg-background"))
c, line = al("s-bg-new")
check("agent-listed: an unlisted name beside a background: map is refused, naming the agents: line", c == 3 and "is not under `agents:` on projects/bg " in line and "back_agents" not in line and "`s-bg-new: <mandate>`" in line, (c, line))
check("agent-listed: the project's own name is no agent", al("s-hub")[0] == 0 and al("s-hub")[1].startswith("the name of "), al("s-hub"))
check("agent-listed: a name that extends another's is no agent of it", al("s-hub-main-x")[0] == 0 and "the name of projects/deeper" in al("s-hub-main-x")[1], al("s-hub-main-x"))
check("agent-listed: the longest name prefix decides", al("s-hub-main-x-docs")[0] == 3 and "on projects/deeper " in al("s-hub-main-x-docs")[1], al("s-hub-main-x-docs"))
check("agent-listed: a name under no project is free", al("someone-else") == (0, "no project page for this name: nothing to check") and al("s-hubbub")[0] == 0 and al("s-hub-")[0] == 0, (al("someone-else"), al("s-hubbub"), al("s-hub-")))
check("agent-listed: a completed page names no project", al("s-gone-main")[0] == 0, al("s-gone-main"))
check("agent-listed: a `display-name:` page makes its project's agents listed and its name no agent", al("x-proj-main")[0] == 0 and al("x-proj-main")[1].startswith("listed on projects/dn-") and al("x-proj")[1].startswith("the name of ")
      and al("x-new-main")[0] == 3 and "on projects/dn-both " in al("x-new-main")[1] and al("q-old-main") == (0, "no project page for this name: nothing to check"), (al("x-proj-main"), al("x-proj"), al("x-new-main"), al("q-old-main")))
(T / "brain/projects/hub.md").write_text((T / "brain/projects/hub.md").read_text().replace("agents:\n  s-hub-main: 'upgrades, the curator'\n  s-hub-docs: writes the docs\n", ""), encoding="utf-8")
check("agent-listed: with no agents: line anywhere, the page named is the one the project's name ends in", al("s-hub-main")[0] == 3 and "on projects/hub " in al("s-hub-main")[1], al("s-hub-main"))
fmpage("projects/fresh.md", "type: project\ntitle: Fresh\ndisplay-name: s-fresh\nagents:\n  s-fresh-main: the contact")
check("agent-listed: a line written a moment ago counts (files, not the registry)", "projects/fresh" not in R and al("s-fresh-main") == (0, "listed on projects/fresh: the contact"), al("s-fresh-main"))
run = lambda n: subprocess.run([sys.executable, os.path.join(STACK, "stackshot/projects/pages.py"), "agent-listed", n], capture_output=True, text=True, env=os.environ)
r3, r0, r1 = run("s-fresh-docs"), run("s-fresh-main"), run("")
check("agent-listed: the command exits 3 / 0 / 1 with one line", (r3.returncode, r0.returncode, r1.returncode) == (3, 0, 1) and r3.stdout.count("\n") == 1 and r0.stdout.strip() == "listed on projects/fresh: the contact", (r3.returncode, r3.stdout, r0.returncode, r0.stdout, r1.returncode))
for x in ("projects/other.md", "ops/hubhost.md", "projects/deeper.md", "projects/gone.md", "projects/fresh.md"): (T / "brain" / x).unlink()
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
check("debt: …and again at the following prompt while it is owed", "[project-page] board item s9 changed at" in nnag(S))
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
server._publish = lambda: None
check("server: a keeper's debt is strict, an agent's is not", server._strict(S) and server._strict(B) and not server._strict(A))
server._owed_save({"projects/beta": {B: {"ts": time.time() - 30, "item": "s1"}, A: {"ts": time.time() - 30, "item": "s2"}}})
time.sleep(1.1); b = T / "brain/projects/beta.md"
b.write_text(b.read_text(encoding="utf-8") + "- **2026-01-02** | t — a timeline line\n", encoding="utf-8")
d = server._owed_settle().get("projects/beta", {})
check("a timeline line settles the agent's debt, not the keeper's", B in d and A not in d, d)
n = server._nag(B); check("the nag says why, to a page keeper", "As a page keeper" in n and "not what is true now" in n, n)
check("…and not to a session that keeps no page", "As a page keeper" not in server._nag(A), server._nag(A))
n = server._nag(A); check("the pages-owed line marks a keeper's debt as settled only by Current state", "pages owed:" in n and "a keeper: settles on a Current-state edit" in n, n)
server._owed_save({"projects/beta": {B: {"ts": time.time() - 30, "item": "s1"}, A: {"ts": time.time() + 3600, "item": "s2"}}})
n = server._nag(B); check("…and leaves a non-keeper's debt plain", "pages owed:" in n and "a keeper:" not in n, n)
server._owed_save({"projects/beta": {B: {"ts": time.time() - 30, "item": "s1"}}})
b.write_text(b.read_text(encoding="utf-8").replace("- small state.", "- small state, now different."), encoding="utf-8")
check("a Current-state edit settles it", B not in server._owed_settle().get("projects/beta", {}))

# ---- 5b. `pages.py clear <key>` drops the caller's own debt only (a clear once wiped a keeper's
# reminder); another writer's is named and kept; --force drops every writer's, as clear did before
LEDGER = server._owed_path(); kept_ledger = LEDGER.read_text(encoding="utf-8") if LEDGER.exists() else None
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
      f"— update the page (edit {tmp}/brain/projects/beta.md (its Current state, and a dated line under its Timeline), commit and push). Only if" in plain
      and "add_timeline_entry" not in plain and RETIRED_SCRIPT not in plain, plain)
p._cfg.CFG["pages"]["flavor"] = "gbrain"
gb = p.describe("projects/beta", v)
old_tm = p.datetime.datetime.fromtimestamp(v["ts"], p.zone_now().tzinfo).strftime("%H:%M")
check("flavor gbrain: the nag is today's text, byte for byte", gb == (
      f"board item s7 changed at {old_tm} {ZONE_ABBR} but the project page `projects/beta` has not been committed since — update the page "
      f"(a dated line: the gbrain connector's add_timeline_entry; any other edit: get_page with section or grep (the smallest read that shows the text to change; a whole read only for a rewrite or a change spanning the page), then edit_page "
      f"with expected_revision (the read's revision) and edits [{{old_text, new_text}}]; put_page only for a whole rewrite; "
      f"never edit or git inside the brain mirror). "
      f"Only if the board edit needed no page change: `python3 {p.HERE}/stackshot/projects/pages.py clear projects/beta`."), gb)
check("flavor gbrain: the nag names add_timeline_entry, then edit_page, and put_page only for a whole rewrite; no retired script, no push override",
      gb.index("add_timeline_entry") < gb.index("edit_page")
      and "put_page only for a whole rewrite" in gb and "with expected_revision" in gb
      and RETIRED_SCRIPT not in gb and "EXAMPLE_PAGE_PUSH" not in gb and "on the server box only" not in gb, gb)
p._cfg.CFG["pages"]["flavor"] = "plain"
check("flavor gbrain: the server's wording is today's text, byte for byte", server._page_how("gbrain") ==
      "dated line → add_timeline_entry; other edits → get_page with section or grep (the smallest read that shows the text to change; a whole read only for a rewrite or a change spanning the page), then edit_page with expected_revision (the read's revision) "
      "and edits [{old_text, new_text}]; put_page only for a whole rewrite; never edit or git inside the brain mirror", server._page_how("gbrain"))
_ph = server._page_how("gbrain")
check("flavor gbrain: the server's wording names add_timeline_entry, then edit_page; no retired script, no push override",
      _ph.index("add_timeline_entry") < _ph.index("edit_page") and "put_page only for a whole rewrite" in _ph
      and RETIRED_SCRIPT not in _ph and "EXAMPLE_PAGE_PUSH" not in _ph, _ph)
server._owed_save({"projects/gamma": {B: {"ts": time.time() + 3600, "item": "s9"}}})       # a debt the page cannot have settled yet
check("flavor plain: the server's nag and refusal say edit the file",
      server._page_how() == f"edit {tmp}/brain/<key>.md (its Current state, and a dated line under its Timeline), commit and push"
      and f"({server._page_how()})" in server._nag(B), (server._page_how(), server._nag(B)))
server._owed_save({})
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
check("tz: Asia/Dubai prints its own abbreviation (the offset label, the zone having no letters)", p._cfg.tz_abbr() == ZONE_ABBR and f" {ZONE_ABBR} but " in p.describe("projects/beta", v), p.describe("projects/beta", v)[:60])
p._cfg.CFG["instance"]["timezone"] = "UTC"
check("tz: UTC prints UTC, never the instance zone's label", p._cfg.tz_abbr() == "UTC" and " UTC but " in p.describe("projects/beta", v) and ZONE_ABBR not in p.describe("projects/beta", v), p.describe("projects/beta", v)[:60])
p._cfg.CFG["instance"]["timezone"] = "America/New_York"
check("tz: a zone with daylight time takes the abbreviation of the moment", p._cfg.tz_abbr(p.datetime.datetime(2026, 1, 15, 12)) == "EST"
      and p._cfg.tz_abbr(p.datetime.datetime(2026, 7, 15, 12)) == "EDT", (p._cfg.tz_abbr(p.datetime.datetime(2026, 1, 15, 12)),))
p._cfg.CFG["instance"]["timezone"] = "Asia/Dubai"
saved_brain = p.BRAIN; p.BRAIN = f"{tmp}/no-such-pages"
nc = p.describe("projects/beta", v)
check("flavor plain, no pages copy here: the nag names the page in a checkout of the pages repository, one parenthesis",
      "— update the page (edit the page `projects/beta.md` in a checkout of the pages repository, which this machine has none of: its Current state, "
      "and a dated line under its Timeline; commit and push). Only if" in nc and "no copy" not in nc, nc)
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
        if not server._client_machine(self.headers.get("Authorization", "")): st, body = 401, "unauthorized"
        else: st, _, body = server._client_get(what, q)
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
rc, err = bstop(A, transcript("ship it", COMMIT), mode="note"); check("note: the board question does not hold the turn", rc == 0 and err == "", (rc, err[:200]))
check("note: …and is logged as a note", blog("note") and blog("note")[-1]["items"] == ["s5", "s6"], blog("note")[-1:])
out = nnag(A); check("note: the next prompt says the board question, about the last turn", out.count("[board] About your last turn: BOARD: this turn did real work (a commit)") == 1 and 's5 "[home] item 5"' in out, out[:300])
check("note: …once", "[board]" not in nnag(A), "said twice")
rc, err = bstop(A, transcript("ship it", COMMIT), mode="note"); rc, err = bstop(A, transcript("ship it again", COMMIT), mode="note")
out = nnag(A); check("note: two turns before a prompt: both questions, oldest first", out.count("[board] About your last turn") == 2, out[:300])
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
st_, _, body_ = server._client_get("items", {"key": A}); rows_ = {i["gid"]: i for i in json.loads(body_)["items"]}
check("the items read says how each item is shown", rows_["g12"]["shown"] == "board#12" and rows_["l3"]["shown"] == f"{TMP}#3" and rows_["s5"]["shown"] == "s5", rows_)
def fstop2(final):
    p.save_state(A, {}); CALLS.clear(); bstop(A, transcript("report", [], final), mode="note"); return nnag(A)
out = fstop2("Done.\nBoard board#13: no change, its owner runs it")
check("a Board line about another session's item, written as board#<n>: the note names it so, the log the store id",
      "[board] About your last turn's Board lines: board#13 is moved by home-beta; leave it out, or say why it's yours to report." in out and "g13" not in out
      and blog("foreign")[-1]["items"] == ["g13"], (out[:400], blog("foreign")[-1:]))
st_, _, body_ = server._client_get("item-facts", {"key": A, "ids": "g13,s5"}); f_ = json.loads(body_)["items"]
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
CLOSED = _rm.when_words(p.datetime.datetime.fromtimestamp(OLD, server.ZONE))
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
st, _, body = server._client_get("item-facts", {"key": A, "ids": "s40,s41,s42,s99"}); f = json.loads(body)["items"]
check("foreign: item-facts says mover, then (mine), agent and the close", st == 200 and f["s40"]["mine"] is False and f["s41"]["mine"] is False
      and f["s41"]["outcome"] == "done" and f["s42"]["agent"] is True and "s99" not in f, f)
check("foreign: item-facts refuses a bad id list", server._client_get("item-facts", {"key": A, "ids": "x; rm"})[0] == 400)
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
      rc == 0 and q.startswith("[stackshot] The end-of-turn board question, asked now so it costs no second reply (once per turn): Your other open items") and 's6 "[home] item 6"' in q
      and "Page" not in q and "page" not in q
      and "`Board: no change, <reason>`" in q and "s7 " not in q and "s8 " not in q, q)
check("early (quiet retired, Thu Oct 15th 2026): the question no longer advertises a [quiet] reply", "quiet" not in q.lower(), q)
check("early: the examples name items as shown, `Board board#5: …`", "`Board board#N: no change, <reason>`" in q and "Board s5" not in q, q)
check("early (bullets): the question asks for a `Board:` line and one bullet per item for several items",
      "a `Board:` line followed by one bullet per item, each on its own line: `- board#N: no change, <reason>` (or `- board#M: updated, <what>`)" in q
      and "In another language the instance has configured the same lines read with its own words" in q, q)
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
# a page keeper (S keeps alpha and gamma): the early text carries the board question and nothing about its pages, and the board
# write's page debt is still recorded
p.save_state(S, {}); items((10, S, {}))
rc, q = touch(S, transcript("keeper ships", []), {"item_id": "s10", "next": "x"}, resp="updated [s10](https://x/items/s10).\nproject: projects/alpha")
check("early: a keeper gets the board question only: no Page line, no pages it keeps, no page owed", q.startswith("[stackshot] The end-of-turn board question")
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

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": page currency scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
