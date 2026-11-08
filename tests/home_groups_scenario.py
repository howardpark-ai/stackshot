"""Scenario test for the home page's foldable scope subsections (Board.scope_groups, Board.scope_sections and Board.home_section in ui/render.py, with ui/groups.py) — fixture data, no live store, no network, no server.

Each of the home page's four lists (Your move, On agent, Queued for release, Waiting) draws its rows in one group per scope, under the scope's name and row count (the Closed page's
h3.iscope heading), the scopes in [project_scopes] order (work, home, ops here), a row's scope the Closed page's (Board.landed_scope). Covers:

  * the order: the groups come out work, home, ops whatever order the rows were created or sorted in, in every one of the four lists;
  * the scope of a row is landed_scope's: the project's scope (its org, its key prefix), a row with no project in the default scope (home);
  * a scope with no rows in a list draws no heading; a list with no rows at all keeps its one empty line and draws no heading;
  * each list keeps its own sort inside a subsection (Your move and On agent oldest first, Waiting by end date), and the order of the home_pairs lists is untouched;
  * the count in a subsection heading is the number of its rows, and the subsection counts of a list add up to the list's own count (the list's heading, the count cards and board.md are unchanged);
  * a row whose scope is not one of the configured scopes is not dropped: it sits in a last subsection under the scope's own name;
  * which lists start open is as it was (Your move and Queued for release); a project page's lists are not grouped by scope;
  * each subsection is a native <details> (no script of its own): its summary holds the h3.iscope with the scope's name and the row count, it renders open (also inside a list that starts closed), each has its own data-fold key
    (the list and the scope, unique on the page: the live swap matches folds by it), and the page remembers no subsection's state (the home fold script reads and writes no storage).

    tests/run-suite home_groups        → exit 0 / 1"""
import datetime, json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="homescopetest-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))   # the example instance: scopes work, home, ops (default home); "ops/" is the ops scope
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "state/site", "brain/projects", "secrets", "touch"): (T / d).mkdir(parents=True)
ZONE = datetime.timezone(datetime.timedelta(hours=4))      # the pinned instance timezone, Asia/Dubai: UTC+4, no DST
NOW = datetime.datetime(2026, 10, 27, 10, 0, tzinfo=ZONE); now = NOW.timestamp()
H, D = 3600.0, 86400.0
day = lambda n: (NOW + datetime.timedelta(days=n)).strftime("%Y-%m-%d")
S1, S2 = "00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002"
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({S1: {"name": "home-front", "machine": "a", "seen": now, "url": ""}, S2: {"name": "team-back", "machine": "a", "seen": now, "url": ""}}))
def page(name, org, agents): return {"title": name.title(), "name": name.title(), "org": org, "tags": [], "type": "project", "session": agents[0], "status": "active", "board": [], "board_open": 0, "agents": {a: "builds" for a in agents}}
PAGES = {"projects/dsl": page("dsl", "work", ["home-front"]), "projects/hmp": page("hmp", "home", ["home-front"]), "ops/box": page("box", "home", ["home-front"]), "projects/odd": page("odd", "home", ["home-front"])}
(T / "store/projects.json").write_text(json.dumps({"pages": PAGES}))
for k in PAGES: (T / "brain" / (k + ".md")).parent.mkdir(parents=True, exist_ok=True); (T / "brain" / (k + ".md")).write_text(f"---\ntitle: {k}\n---\n\n# {k}\n")
(T / "store/next-id").write_text("900")
def item(i, subject, project, age, owner=S2, **meta):
    meta = {"owner": owner, "next": "team-back: do the thing", **meta}
    if meta.get("hold") and not meta.get("needs"): meta.setdefault("post_wake_mover", owner)
    if project: meta["project"] = project
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject, "description": "A fixture item.", "status": "open", "updated": now - age, "state_updated": now - age,
                                                    "confirmed": now - age, "metadata": meta}))
ASK = "Decide: ship the thing? · Recommend: yes · Stakes: low · By: Fri"
# Your move (oldest first): created ops, home, work, so the scope order cannot come from creation order; the ages put the work rows 1 day, 3 days
YM = lambda i, sj, pj, age: item(i, sj, pj, age, owner=S1, needs=["decision"], ask=ASK, next="Oliver: answer the ask")
YM(1, "[home] ym ops", "ops/box", 9 * D); YM(2, "[home] ym home old", "projects/hmp", 8 * D); YM(3, "[work] ym work young", "projects/dsl", 1 * D)
YM(4, "[work] ym work old", "projects/dsl", 5 * D); YM(5, "[home] ym no project", "", 6 * D); YM(6, "[home] ym home young", "projects/hmp", 2 * D)
# On agent: no row in ops, so no ops heading
item(10, "[home] ag home", "projects/hmp", 3 * D, needs=["team-back"]); item(11, "[work] ag work old", "projects/dsl", 4 * D, needs=["team-back"]); item(12, "[work] ag work young", "projects/dsl", 1 * D, needs=["team-back"])
# Waiting (by end date): home row ends first overall, a work row later, an ops row last
item(20, "[home] wt home", "projects/hmp", 1 * D, hold=True, wake=day(1), wait_basis={"text": "the vendor ships on " + day(1), "wake": day(1), "by": "team-back", "at": now - D}, next="team-back: review")
item(21, "[work] wt work late", "projects/dsl", 1 * D, hold=True, wake=day(9), wait_basis={"text": "the vendor ships on " + day(9), "wake": day(9), "by": "team-back", "at": now - D}, next="team-back: review")
item(22, "[work] wt work early", "projects/dsl", 1 * D, hold=True, wake=day(3), wait_basis={"text": "the vendor ships on " + day(3), "wake": day(3), "by": "team-back", "at": now - D}, next="team-back: review")
item(23, "[home] wt ops", "ops/box", 1 * D, hold=True, wake=day(5), wait_basis={"text": "the vendor ships on " + day(5), "wake": day(5), "by": "team-back", "at": now - D}, next="team-back: review")
# Queued for release (empty until a pull request is queued, below): two agent items, one work and one ops
item(30, "[work] rel work", "projects/dsl", 2 * D, needs=["team-back"]); item(31, "[home] rel ops", "ops/box", 3 * D, needs=["team-back"])
# the unknown-scope row
item(40, "[home] odd one", "projects/odd", 6 * D, needs=["team-back"])

fails, ran = [], []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
logging.disable(logging.INFO)
from stackshot.web.ui import render
from stackshot.web import home

def board(queued=()):
    b = render.Board(str(T / "store"), now=NOW)
    b.provision = [("home-box", True)]
    b._rel_ids = set(queued)                  # the release queue is the script's, not under test: the ids that sit in Queued for release
    return b
def section(h, sid):
    i = h.find(f'<section id="{sid}">'); return h[i:h.find("</section>", i)] if i >= 0 else ""
def tree(sec):
    """[(scope, count, [item ids])] of one list's subsections, in page order."""
    return [(m.group(1), int(m.group(2)), re.findall(r'id="task-a-(\d+)"', m.group(3)))
            for m in re.finditer(r'<details class="fold sfold hscope" data-fold="[^"]+" open><summary><h3 class="iscope">(.*?) <span class="count">(\d+)</span></h3></summary>(.*?)</ul></details>', sec, re.S)]
def ids(sec): return re.findall(r'<li class="irow hrow" id="task-a-(\d+)" data-st="[a-z]+">', sec)
def heads(sec): return re.findall(r'<h3 class="iscope">(.*?) <span', sec)
def list_count(sec): return int(re.search(r'<h2>[^<]*<span class="count">(\d+)</span></h2>', sec).group(1))

b = board(queued={"a30", "a31"}); h = b.html()
YMs, AWs, RLs, WLs = (section(h, s) for s in ("your-move", "agents-at-work", "queued-release", "waiting-list"))
check("setup: the four lists hold what the fixtures say", sorted(ids(YMs)) == ["1", "2", "3", "4", "5", "6"] and sorted(ids(WLs)) == ["20", "21", "22", "23"], (ids(YMs), ids(WLs)))

# ---- the order, and the scope of each row ----
check("Your move: the subsections come work, home, ops (not the rows' creation or age order); home holds the project hmp and the row with no project (the default scope), ops the ops/ page",
      [t[0] for t in tree(YMs)] == ["work", "home", "ops"] and {t[0]: set(t[2]) for t in tree(YMs)} == {"work": {"3", "4"}, "home": {"2", "5", "6"}, "ops": {"1"}}, tree(YMs))
check("Waiting: work, home, ops", [t[0] for t in tree(WLs)] == ["work", "home", "ops"], tree(WLs))
check("the order is the config's order, read as the Closed page reads it (projects.scopes), not a list in the render code", __import__("stackshot.projects.projects", fromlist=["_"]).scopes() == ["work", "home", "ops"])

# ---- the empty cases ----
check("On agent: a scope with no row draws no heading (no ops here); the others come in order", tree(AWs) and [t[0] for t in tree(AWs)] == ["work", "home"] and heads(AWs) == ["work", "home"], tree(AWs))
check("Queued for release: work then ops, no home heading", [t[0] for t in tree(RLs)] == ["work", "ops"] and heads(RLs) == ["work", "ops"], tree(RLs))
check("the release rows left On agent (the two lists are disjoint, the rows are in one of them)", not (set(ids(RLs)) & set(ids(AWs))) and set(ids(RLs)) == {"30", "31"}, (ids(RLs), ids(AWs)))
e = board(); e.rows = []; e._lists = None
EH = e.html()
check("a list with no rows keeps its one empty line and draws no heading", all('<p class="empty">' in section(EH, s) and "<h3" not in section(EH, s) for s in ("your-move", "agents-at-work", "queued-release", "waiting-list"))
      and 'nothing waits on you' in section(EH, "your-move") and 'no release is queued' in section(EH, "queued-release"), [section(EH, s)[:200] for s in ("your-move", "queued-release")])
check("a list with no rows has its count 0 in its heading", all(list_count(section(EH, s)) == 0 for s in ("your-move", "agents-at-work", "queued-release", "waiting-list")))
check("a list with rows has no empty line", all('class="empty"' not in s for s in (YMs, AWs, RLs, WLs)))

# ---- the sort inside a subsection ----
check("Your move keeps oldest first inside a subsection: work 4 (5 days) before 3 (1 day); home 2 (8 days), 5 (6 days), 6 (2 days)",
      dict((t[0], t[2]) for t in tree(YMs)) == {"work": ["4", "3"], "home": ["2", "5", "6"], "ops": ["1"]}, tree(YMs))
check("On agent keeps oldest first: work 11 (4 days) before 12 (1 day)", dict((t[0], t[2]) for t in tree(AWs))["work"] == ["11", "12"], tree(AWs))
check("Waiting keeps the end-date order inside a subsection: work 22 (in 3 days) before 21 (in 9 days)", dict((t[0], t[2]) for t in tree(WLs))["work"] == ["22", "21"], tree(WLs))
lists = b.home_lists()
flat = lambda sec: [i for _s, _n, g in tree(sec) for i in g]
check("the lists themselves are untouched: home_pairs keeps its sort across scopes (Your move 1, 2, 5, 4, 6, 3 by age), and the page holds the same rows in its subsections",
      [r["gid"] for r, _m in lists[home.YOUR_MOVE]] == ["a1", "a2", "a5", "a4", "a6", "a3"] and sorted(flat(YMs)) == sorted(i for i in ids(YMs)), [r["gid"] for r, _m in lists[home.YOUR_MOVE]])

# ---- the counts ----
check("a subsection's count is its row count, in every list", all(n == len(g) for sec in (YMs, AWs, RLs, WLs) for _s, n, g in tree(sec)), [tree(s) for s in (YMs, AWs, RLs, WLs)])
check("the subsection counts add up to the list's count in its heading, and every row is in exactly one subsection",
      all(sum(n for _s, n, _g in tree(sec)) == list_count(sec) == len(ids(sec)) == len(set(ids(sec))) == len(flat(sec)) for sec in (YMs, AWs, RLs, WLs)), [(list_count(s), len(ids(s))) for s in (YMs, AWs, RLs, WLs)])
check("the count cards are as before: Your move 6, On agent 4 (10, 11, 12 and the item 40 of the unknown-scope test), Queued for release 2, Waiting 4",
      [list_count(s) for s in (YMs, AWs, RLs, WLs)] == [6, 4, 2, 4] and re.findall(r'<a class="hcard[^"]*" href="[^"]+"[^>]*><b>(\d+)</b>', h)[:4] == ["6", "4", "2", "4"], re.findall(r'<b>(\d+)</b>', h))
check("the heading text form is the Closed page's: the scope name, a space, the row count in span.count, in an h3.iscope",
      '<h3 class="iscope">work <span class="count">2</span></h3>' in YMs and '<h3 class="iscope">ops <span class="count">1</span></h3>' in YMs)

# ---- the subject tag stays hidden ----
check("the rows still hide the [work] / [home] subject tag (Board.bare)", "[work]" not in h.split('<main')[1].split("</main>")[0] and "[home]" not in h.split('<main')[1].split("</main>")[0])

# ---- a scope that is not configured ----
u = board(queued={"a30", "a31"}); orig = u.landed_scope
u.landed_scope = lambda k: ("legacy", 3) if k == "projects/odd" else orig(k)      # a page whose scope is no longer one of [project_scopes] (rank = len(order))
UH = u.html(); UAW = section(UH, "agents-at-work")
check("an unknown scope's row is not dropped: it sits in a last subsection under the scope's own name, after the configured ones",
      [t[0] for t in tree(UAW)] == ["work", "home", "legacy"] and dict((t[0], t[2]) for t in tree(UAW))["legacy"] == ["40"] and "40" not in [i for t in tree(UAW)[:2] for i in t[2]], tree(UAW))
check("the unknown scope's rows count in the list's count and the heading carries its count", list_count(UAW) == 4 == sum(n for _s, n, _g in tree(UAW)) and '<h3 class="iscope">legacy <span class="count">1</span></h3>' in UAW)
u.landed_scope = lambda k: {"projects/odd": ("zeta", 3), "projects/hmp": ("alpha", 3)}.get(k) or orig(k)
check("two unknown scopes come last, by name, after the configured ones", [s_ for s_, _g in u.scope_groups(u.home_lists()[home.AGENTS], row=lambda p: p[0])] == ["work", "alpha", "zeta"], [s_ for s_, _g in u.scope_groups(u.home_lists()[home.AGENTS], row=lambda p: p[0])])

# ---- folds ----
folds = re.findall(r'<details class="fold" data-fold="([^"]+)"( open)?>', h)
check("which lists start open is as it was: Your move and Queued for release open, On agent and Waiting closed",
      {f for f, o in folds if o and f in ("your-move", "agents-at-work", "queued-release", "waiting-list")} == {"your-move", "queued-release"}, folds)

# ---- the subsections fold ----
subs = re.findall(r'<details class="fold sfold hscope" data-fold="([^"]+)"( open)?><summary>', h)
check("every subsection is a details.fold with the h3.iscope in its summary, one per (list, scope) shown: 3 + 2 + 2 + 3 = 10 here",
      len(subs) == 10 == h.count('class="fold sfold hscope"') == h.count('<summary><h3 class="iscope">'), subs)
check("each subsection renders open, also those inside On agent and Waiting, which start closed", all(o for _f, o in subs) and len(subs) == 10, subs)
check("the subsections' data-fold keys are unique on the page and name the list and the scope (home.<list>.<scope>)",
      len({f for f, _o in subs}) == len(subs) and {f for f, _o in subs} >= {"home.your-move.work", "home.agents-at-work.home", "home.queued-release.ops", "home.waiting-list.work"}, [f for f, _o in subs])
check("no subsection key is a section id or one of the old stored keys the home fold script removes", not ({f for f, _o in subs} & {f for f, _o in folds}) and not any(f in render._HOME_OLD_FOLD_KEYS for f, _o in subs))
check("the rows sit in a ul.ir-rows right after the summary (the project page's list shape), and the old div.hscope is gone", '</summary><ul class="ir-rows">' in YMs and 'class="hscope"' not in h)
check("the home fold script stores nothing for a subsection (it reads and writes no localStorage state), so a fold lasts only until the page is reloaded",
      "setItem" not in render._HOME_FOLD_JS and "getItem" not in render._HOME_FOLD_JS)

# ---- the project page is not grouped ----
PI = b.project_items("projects/dsl")[2]
check("a project page's lists carry no scope subsections (their h3.iscope is the list's own name)", 'hscope' not in PI and "data-fold=\"project.items.your-move\"" in PI, PI[:300])

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
