"""Scenario test for the Projects page's Archived fold — fixture data, no live store, no network, no server process (the render module is imported and called
in-process, on a temporary config).

Covers: the archived projects (a page status in retired_statuses) sit in one foldable group named Archived, drawn as home's scope subsections are (a native
`<details class="fold sfold">` whose summary holds `h3.iscope` with the name and the count of its projects, a data-fold key), closed on load, after the active projects,
with the projects listed by scope inside; the count is the number of archived projects over every scope; a page with no archived project draws no group; a scope
whose projects are all archived keeps its side-panel anchor inside the group, and the page opens the fold on a hash (the home fold script is on the page); the word
"finished" is gone from the Projects page's table, the side panel's hover text (`N active, M archived`) and the project page's group of agents, which says Archived;
and a project whose last agent is retired shows in the group once its page says archived.

    tests/run-suite archive_fold_view        → exit 0 / 1"""
import json, os, re, sys, pathlib, logging, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="archgrp-"); T = pathlib.Path(tmp)
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
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "brain/infra", "secrets"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

page("projects/w-live.md", "type: project\ntitle: Work live\norg: work\ndisplay-name: work-wlive\nagents:\n  work-wlive-main: talks\nstatus: active")
page("projects/w-old.md", "type: project\ntitle: Work old\norg: work\ndisplay-name: work-wold\nstatus: archived")
page("projects/h-live.md", "type: project\ntitle: Home live\norg: home\ndisplay-name: home-hlive\nagents:\n  home-hlive-main: talks\nstatus: active")
page("projects/h-old.md", "type: project\ntitle: Home old\norg: home\ndisplay-name: home-hold\nstatus: done")
page("projects/o-old.md", "type: project\ntitle: Infra old\ntags:\n  - infra\ndisplay-name: zeta-zold\nstatus: Archived")
from stackshot.projects import pages as p
from stackshot.web.ui import render as ui_render
p.cmd_registry(quiet=True)
def board(): return ui_render.Board(f"{tmp}/store")
def text(h): return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", h))
OPEN = re.compile(r'<details class="fold sfold" data-fold="projects.archived"( open)?>')
HEAD = '<summary><h3 class="iscope">Archived <span class="count">3</span></h3></summary>'

# ---- the group
bd = board(); tab = bd.projects_table()
m = OPEN.search(tab)
check("Archived: one foldable group, drawn with home's fold markup (details.fold.sfold, a data-fold key) and closed on load", len(OPEN.findall(tab)) == 1 and m and not m.group(1), tab[:300])
check("Archived: the heading is home's: h3.iscope with the name and the count of the archived projects over every scope (3: work, home and infra)", HEAD in tab, text(tab)[:400])
check("Archived: it follows the active table and holds the archived projects, by scope", tab.index("w-live") < tab.index(HEAD) < tab.index("w-old") and tab.index("w-old") < tab.index("h-old") < tab.index("o-old")
      and tab.index("h-live") < tab.index(HEAD), text(tab))
check("Archived: the old closed 'finished' details and its lowercase summary are gone from the table", "finished" not in tab and '<details class="finished"' not in tab)
check("Archived: the markup stays balanced (details, tables)", tab.count("<details") == tab.count("</details>") == 1 and tab.count("<table") == tab.count("</table>") == 2, (tab.count("<details"), tab.count("<table")))
from stackshot.web.ui import groups as _grp
check("Archived: the same helper draws home's scope subsections (groups.fold) and this group (groups.fold_block); a subsection is still open with its hscope class",
      _grp.fold("k", "work", ["<li>x</li>"]).startswith('<details class="fold sfold hscope" data-fold="k" open><summary><h3 class="iscope">work <span class="count">1</span></h3></summary>')
      and _grp.fold_block("k", "Archived", 2, "", opened=False, cls="fold sfold") == '<details class="fold sfold" data-fold="k"><summary><h3 class="iscope">Archived <span class="count">2</span></h3></summary></details>')
check("Archived: the infra scope has only an archived project, so its anchor (the side panel's link) sits inside the group", tab.index('id="' + bd.scope_anchor("infra") + '"') > tab.index(HEAD)
      and tab.index('id="' + bd.scope_anchor("work") + '"') < tab.index(HEAD), text(tab))

# ---- the page and the side panel
html = board().projects_html()
check("Projects page: it carries the Archived heading and the home fold script (a hash into the closed group opens it)", HEAD in html and "go(location.hash,false)" in html and html.count('data-fold="projects.archived"') == 1)
panel = board().panel_blocks()["projects-panel"]
check("side panel: a scope's hover text says 'N active, M archived' (the word 'finished' is gone)", 'title="1 active, 1 archived"' in panel and "finished" not in panel, text(panel))
check("side panel: a scope with only archived projects says '0 active, 1 archived'", 'title="0 active, 1 archived"' in panel, text(panel))

# ---- the project page
page("projects/w-old.md", "type: project\ntitle: Work old\norg: work\ndisplay-name: work-wold\nagents:\n  work-wold-main: was the contact\nstatus: archived")
p.cmd_registry(quiet=True)
n, h = board().sessions_html("projects/w-old")
check("project page: an archived project's agents sit in a closed group titled Archived (not 'finished')", n == 1 and h.startswith('<details class="archived"><summary>Archived</summary>') and "finished" not in h and not re.match(r"<details[^>]*\bopen", h), h[:200])

# ---- no archived project → no group; a project archived after its last agent retired joins the group
for rel in ("projects/w-old.md", "projects/h-old.md", "projects/o-old.md"): (T / "brain" / rel).unlink()
p.cmd_registry(quiet=True)
tab2 = board().projects_table()
check("Archived: with no archived project there is no group", "Archived" not in tab2 and "<details" not in tab2 and "w-live" in tab2, text(tab2))
page("projects/w-live.md", "type: project\ntitle: Work live\norg: work\ndisplay-name: work-wlive\nagents:\nstatus: archived")      # its last agent retired and the page archived (project_archive.py)
p.cmd_registry(quiet=True)
tab3 = board().projects_table()
check("Archived: a project whose last agent was retired and whose page says archived is in the group, count 1", '<h3 class="iscope">Archived <span class="count">1</span></h3>' in tab3 and tab3.index("w-live") > tab3.index("Archived"), text(tab3))

print(("ok" if not fails else "FAILED") + f": archive fold view scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
