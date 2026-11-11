"""Scenario test for the project picker behind sala's "New session" form: a scope on every project, a listed/hidden mark, the calls that list
the projects of a scope (with a search over the hidden ones), make a new project with its gbrain page, list a hidden one again, and add the
form's agent through the existing `post project-agent` — fixture data, no live store, no network, no server process, no gbrain (the page
write is a fake; the server module is imported and called in-process, on a temporary config).

Covers: the scope derived from the key, the page's org, its tags, its hub and the page above it (and a scope set on purpose winning, and
surviving a rebuilt registry and a project's page move); the listed rules (agents, a board item touched in the last 30 days, a mark made on
purpose, none of these = hidden; a sub-page never, whatever it has; the items of a sub-page counting for its project; a pending agent
counting); list by scope with and without a search (key, name and title, case-insensitive, hidden marked, sub-pages left out, a bad scope
refused); a new project (the gbrain write called once with the project template, the page parsed by the registry's own reader, the record
listed and in the list at once, the registry later reading the page without a second record, scope and org/tag in the frontmatter); its
refusals (an existing registry entry, page file or gbrain page, a key outside the page dirs, a sub-path, a bad slug, a bad scope, a refused
and an unanswered gbrain write that record nothing, a damaged id file that writes no page); re-listing a hidden project (scope too, said
again changing nothing, a sub-page and unknown and ambiguous refused); `post project-agent` on a project just made (the first agent from a
label, then the keeper/front rule again) and on a hidden project (a pending agent lists it); the published projects.json carrying the new
fields beside the old; the same over the HTTP client API and client.py; and a retired project (page status archived, retired, closed, done or
dropped, or the config's set): never listed or found by a search whatever its items, agents or on-purpose mark, `status` and `retired` on every
row and record, a re-list refused (400), a label's project-agent refused (403) while the keeper's session id still works, pages with status
active, none or another word unaffected; and `post project-agent-retire`: an agent on the page loses its line (front, background, a wrapped mandate, an inline map; the page put with the revision it
was read at, a refused put read again and tried once more, a second refusal a 502) and the page gets a timeline line, a pending agent is dropped, an agent
on no page answers 200 'not listed', a lost, ghost or refused write is an error the caller sees, a timeline line that cannot be written is told,
the form gate (a label AND a machine), bad names, an unknown project, a page gbrain does not give, over HTTP and client.py; and the retire lines an
earlier release kept on the ledger are dropped; and the archiving that follows a retire (project_archive.py): the last agent retired with no open item archives the page (status line, two puts, a timeline line),
open items (a sub-page's too) put the project on the wait list and the ten-minute sweep archives it once none is left (completed or handed away), a pending agent or an agent back keeps it staffed, a page already done
or with no status line, a failed status write that does not fail the retire, and the dry-run tool tools/archive_empty_projects.py.

    tests/run-suite projects_picker        → exit 0 / 1"""
import contextlib, io, json, os, re, socket, sys, pathlib, tempfile, logging, time, datetime
BID_A = 9157
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="pickertest-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"), gbrain=True)
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
NAMES = ("home-sparrow", "home-sparrow-main", "home-sparrow-docs", "home-outsider", "ops-tool", "home-fresh", "home-mand", "home-mand-main")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({**{u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in U.items()},
    "00000000-0000-4000-8000-0000000000ff": {"name": "home-kappa", "machine": "a", "url": "", "seen": "x", "gone": "2020-01-01T00:00:00Z"}}))   # kappa's keeper: retired long ago
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
NOW = time.time(); DAY = 86400
_n = [100]
def item(project, days_ago, status="completed"):
    """An item file in the store, touched `days_ago` days ago."""
    _n[0] += 1; ts = NOW - days_ago * DAY
    (T / f"store/a/{_n[0]}.json").write_text(json.dumps({"id": str(_n[0]), "subject": "[home] x", "status": status, "metadata": {"project": project}, "updated": ts, "state_updated": ts - 5}))
def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
page("projects/alpha.md", "type: project\ntitle: Alpha\norg: home\ndisplay-name: home-sparrow\nagents:\n  home-sparrow-main: talks to Oliver\n  home-sparrow-docs: keeps the docs\nstatus: active")
page("projects/alpha/sub.md", "type: project\ntitle: Sub of alpha\norg: work")                  # a sub-page: its org is not its project's
page("projects/alpha/sub/deep.md", "type: note\ntitle: Deeper")
page("ops/tool.md", "type: project\ntitle: A tool box\ndisplay-name: ops-tool")                         # ops by its key, hidden: no agents, no items
page("ops/gadget.md", "type: project\ntitle: Gadget\ndisplay-name: ops-gadget")                         # ops, an item 5 days old → listed
page("projects/delta.md", "type: project\ntitle: Delta\norg: work\ndisplay-name: home-delta")            # work, its one item 45 days old → hidden
page("projects/epsilon.md", "type: project\ntitle: Epsilon\norg: WORK\ndisplay-name: home-epsilon")      # work (org read without case), an item 10 days old → listed
page("projects/zeta.md", "type: project\ntitle: Zeta\nname: Zeta room\ntags:\n  - ops\ndisplay-name: home-zeta")   # no org, a tag that maps to ops → ops, hidden
page("projects/eta.md", "type: project\ntitle: Eta\norg: home\ntags:\n  - ops\ndisplay-name: home-eta")   # org home beats the ops tag
page("projects/theta.md", "type: project\ntitle: Theta\nhub: projects/epsilon\ndisplay-name: home-theta")  # no org of its own: its hub's → work
page("projects/iota.md", "type: project\ntitle: Paper order\nname: Printer room\ndisplay-name: home-iota")   # nothing to derive from → the default, home
page("ops/work-thing.md", "type: project\ntitle: Sample thing\norg: work\ndisplay-name: ops-sample-thing")   # an ops/ key wins over org work
page("projects/old-edge.md", "type: project\ntitle: Old edge\ndisplay-name: home-old-edge")                # an item 29.9 days old → listed
page("projects/older-edge.md", "type: project\ntitle: Older edge\ndisplay-name: home-older-edge")          # an item 30.1 days old → hidden
page("projects/subonly.md", "type: project\ntitle: Subonly\ndisplay-name: home-subonly")                   # its sub-page has the item
page("projects/subonly/notes.md", "type: note\ntitle: Notes")
page("ops/notebook.md", "type: note\ntitle: Notebook of odds\ndisplay-name: ops-notebook")                 # a note: never listed, whatever it has
page("projects/kappa.md", "type: project\ntitle: Kappa\ndisplay-name: home-kappa")                                   # an agentless project to list again
page("projects/live-keeper.md", "type: project\ntitle: Live keeper\ndisplay-name: home-fresh")                      # agentless, but its keeper is a session present in the fleet
# the cases of the scope rule modelled on live pages (their frontmatter shape): an ops- keeper beats org home and the tags; org work beats an ops- keeper
page("projects/example.md", "type: project\ntitle: Example\norg: home\ndisplay-name: ops-falcon\ntags:\n  - hub\n  - tooling\n  - ops\n  - idea")
page("projects/reef.md", "type: project\ntitle: Reef\norg: home\ndisplay-name: ops-kestrel\ntags:\n  - notes\n  - ops")
page("projects/quarry.md", "type: project\ntitle: Quarry\norg: home\ndisplay-name: ops-plover\ntags:\n  - tooling\n  - home\n  - ops\n  - quarry")
page("projects/summit.md", "type: project\ntitle: Summit\norg: home\nhub: projects/example\ndisplay-name: ops-falcon\ntags:\n  - ops\n  - summit")
page("ops/front-desk.md", "type: project\ntitle: Front desk ops\norg: home\ndisplay-name: ops-front-desk\ntags:\n  - ops")
page("projects/lantern.md", "type: project\ntitle: Lantern workshop\norg: work\nhub: ops/front-desk\ndisplay-name: ops-front-desk\ntags:\n  - work")
page("projects/noname.md", "type: project\ntitle: No keeper\nagents:\n  ops-noname-main: m")      # no keeper: the prefix of its agents' names points at ops
item("projects/alpha/sub", 2); item("ops/gadget", 5); item("projects/delta", 45); item("projects/epsilon", 10, status="open")
item("projects/old-edge", 29.9); item("projects/older-edge", 30.1); item("projects/subonly/notes", 1); item("zeta", 40)   # a bare slug names projects/<slug>
item("projects/theta", 3); item("ops/notebook", 2)   # theta has a hub: its item counts for the hub (epsilon); the note is never listed
for n, bad in enumerate(({"metadata": "oops", "updated": NOW}, {"metadata": {"project": ["x"]}, "updated": "not a number"}, {"metadata": None}, ["not", "a", "dict"])):   # items nobody wrote by the book
    (T / f"store/a/{900 + n}.json").write_text(json.dumps(bad))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))
ID = re.compile(r"^prj_[0-9a-f]{8}$")
from stackshot.projects import pages as p; from stackshot.projects import projects as prj
p.cmd_registry(quiet=True)
from stackshot.web import server
from stackshot.projects import project_registry as _projects_registry
server._publish = lambda: None
def reg(): return json.loads((T / "store/projects.json").read_text())["pages"]
def idfile(): return json.loads((T / "store/project-record.json").read_text())
def pj(): return json.loads((T / "state/projects.json").read_text())
def fresh(): prj._RECENT.clear()
def lst(scope="", q=""):
    fresh(); st, ctype, body = server._client_get("projects", {"scope": scope, "q": q})
    return st, (json.loads(body) if ctype == "application/json" else body)
def keys(scope="", q=""):
    st, d = lst(scope, q); return [r["key"] for r in d["projects"]] if st == 200 else d
def rec(x): fresh(); return prj.ref(x)

# ---- 1. scope: derived, then set on purpose
S = {k: rec(k)["scope"] for k in reg()}
check("scope: an ops/ key is ops (whatever its org says); an org that names a scope other than home is that scope, without case",
      S["ops/tool"] == "ops" and S["ops/gadget"] == "ops" and S["ops/work-thing"] == "ops" and S["projects/delta"] == "work" and S["projects/epsilon"] == "work"
      and S["projects/alpha"] == "home", S)
check("scope: the four model pages (org home, an ops- keeper, ops among the tags) are ops: example, reef, quarry and summit (keeper ops-falcon, hub example)",
      all(S[k] == "ops" for k in ("projects/example", "projects/reef", "projects/quarry", "projects/summit")), {k: S[k] for k in ("projects/example", "projects/reef", "projects/quarry", "projects/summit")})
check("scope: org work beats an ops- name: the lantern page (org work, name ops-front-desk, hub ops/front-desk) is work; the hub page itself is ops", S["projects/lantern"] == "work" and S["ops/front-desk"] == "ops", (S["projects/lantern"], S["ops/front-desk"]))
check("scope: org home with an ops tag and a keeper that says nothing stays home (eta); a page with no keeper takes the scope its agents' names point at (noname → ops)", S["projects/eta"] == "home" and S["projects/noname"] == "ops", (S["projects/eta"], S["projects/noname"]))
check("scope: a tag that maps to a scope counts when the page has no org; no org and no tag takes its hub's, else the default (home)",
      S["projects/zeta"] == "ops" and S["projects/theta"] == "work" and S["projects/iota"] == "home" and S["projects/old-edge"] == "home", S)
check("scope: a keeper or session name points at its scope by prefix (ops- → ops, work- → work; home- and the rest none)", prj._name_scope("ops-plover") == "ops" and prj._name_scope("WORK-lab") == "work"
      and prj._name_scope("home-eta") == "" and prj._name_scope("") == "" and prj._name_scope("infrastructure") == "")
check("scope: a sub-page that names no scope takes the page above it, and one with an org of its own keeps it", S["projects/alpha/sub/deep"] == "work" and S["projects/alpha/sub"] == "work" and S["projects/subonly/notes"] == "home", S)
check("scope: every record says whether the scope was set on purpose (no)", all(rec(k)["scope_set"] is False for k in reg()))
check("scope: the defaults are in the config's section and the code alike", prj.scopes() == ["work", "home", "ops"] and prj.default_scope() == "home" and prj.derive_scope("ops/x", {}, {}) == "ops")
A = rec("projects/alpha")["id"]; IOTA = rec("projects/iota")["id"]
prj.set_mark(IOTA, scope="work")
check("scope: one set on purpose wins over the derived one, and the record says so", rec("projects/iota")["scope"] == "work" and rec("projects/iota")["scope_set"] is True)
p.cmd_registry(quiet=True); (T / "store/projects.json").unlink(); p.cmd_registry(quiet=True)
check("scope: …and survives a registry rebuilt from nothing (it lives in the id file, not in the registry)", rec("projects/iota")["scope"] == "work" and rec("projects/iota")["id"] == IOTA
      and idfile()["marks"][IOTA]["scope"] == "work" and "marks" not in json.dumps(reg()), idfile())
prj.set_mark(IOTA, scope=None)
check("scope: a mark field set to None is dropped, and the derived scope is back; an empty mark is not written", rec("projects/iota")["scope"] == "home" and "marks" not in idfile(), idfile())
prj.set_mark(IOTA, scope="ops"); prj.rename("projects/iota", "projects/iota2")
check("scope: a mark follows its project's id when the page moves (rename)", idfile()["ids"][IOTA] == "projects/iota2" and idfile()["marks"][IOTA]["scope"] == "ops")
prj.rename("projects/iota2", "projects/iota"); prj.set_mark(IOTA, scope=None)
try: prj.set_mark("prj_ffffffff", scope="bogus-but-stored"); prj.set_mark("prj_ffffffff", scope=None); ok = True
except Exception as e: ok = repr(e)
check("scope: set_mark works on an id the file holds no key for (a stale mark is harmless)", ok is True, ok)

# ---- 2. listed or hidden
def by(k): return rec(k)
check("listed: a project with agents on its page is listed, by agents", by("projects/alpha")["listed"] and by("projects/alpha")["listed_by"] == "agents")
check("listed: an item touched within 30 days lists its project, by items (open or completed; a bare slug names projects/<slug>)", by("ops/gadget")["listed_by"] == "items" and by("projects/epsilon")["listed_by"] == "items"
      and by("projects/old-edge")["listed"] and by("projects/old-edge")["items_30d"] == 1)
check("listed: an item older than 30 days does not (45 days, 30.1 days, 40 days by a bare slug)", not by("projects/delta")["listed"] and not by("projects/older-edge")["listed"] and not by("projects/zeta")["listed"]
      and by("projects/delta")["listed_by"] == "", (by("projects/delta"), by("projects/older-edge")))
check("listed: with none of these a project is hidden", all(not by(k)["listed"] and by(k)["listed_by"] == "" for k in ("ops/tool", "projects/eta", "projects/theta", "projects/iota", "ops/work-thing")))
check("listed: a sub-page never is, though it has an item; its items count for the project above it", by("projects/alpha/sub")["sub_page"] is True and not by("projects/alpha/sub")["listed"]
      and by("projects/alpha/sub")["items_30d"] == 1 and by("projects/subonly")["listed_by"] == "items" and by("projects/subonly")["items_30d"] == 1 and by("projects/alpha")["items_30d"] == 1
      and not by("projects/subonly/notes")["listed"] and not by("projects/alpha/sub/deep")["listed"] and by("projects/alpha/sub/deep")["sub_page"] is True)
check("listed: a page with a hub: line is a sub-page for this purpose (theta, summit, lantern), never listed; its item counts for its hub (epsilon has its own and theta's)",
      all(by(k)["sub_page"] and not by(k)["listed"] for k in ("projects/theta", "projects/summit", "projects/lantern")) and not any(by(k)["sub_page"] for k in ("projects/alpha", "ops/tool", "projects/example"))
      and by("projects/theta")["hub"] == "projects/epsilon" and by("projects/epsilon")["items_30d"] == 2 and by("projects/theta")["items_30d"] == 1, (by("projects/theta"), by("projects/epsilon")["items_30d"]))
check("listed: a type: note page never is, though it has an item (the row says type note); a project page says type project", by("ops/notebook")["type"] == "note" and by("ops/notebook")["items_30d"] == 1 and not by("ops/notebook")["listed"]
      and by("ops/notebook")["listed_by"] == "" and by("projects/alpha")["type"] == "project" and by("projects/alpha")["hub"] == "")
prj.add_pending(by("ops/notebook")["id"], "ops-notebook-main", {"front": True, "role": "main", "mandate_line": "m"}, by="x", at="y")
check("listed: …nor with a pending agent", not by("ops/notebook")["listed"], by("ops/notebook"))
d = idfile(); d["pending_agents"] = {}; (T / "store/project-record.json").write_text(json.dumps(d))
check("listed: bad item files (metadata that is a string, a project that is a list, an updated that is not a number, null metadata, a list) are skipped, not fatal", prj.recent_items(reg(), NOW) is not None
      and (fresh(), prj.recent_items(reg(), NOW))[1].get("projects/alpha/sub") == 1)
check("listed: the rule is the page registry's (is_sub_page: an ancestor key that is itself a page)", prj.is_sub_page("a/b/c", {"a/b": {}}) and not prj.is_sub_page("a/b", {"a/b": {}}) and not prj.is_sub_page("a/b/c", {"a/x": {}}))
prj.set_mark(by("projects/iota")["id"], on_purpose="2026-03-13T00:00:00Z")
check("listed: a mark made on purpose lists a project, by on_purpose; agents and items win the label", by("projects/iota")["listed_by"] == "on_purpose" and by("projects/alpha")["listed_by"] == "agents")
prj.set_mark(by("projects/alpha/sub")["id"], on_purpose="2026-03-13T00:00:00Z")
check("listed: …but not a sub-page, marked or not", not by("projects/alpha/sub")["listed"])
prj.set_mark(by("projects/alpha/sub")["id"], on_purpose=None); prj.set_mark(by("projects/iota")["id"], on_purpose=None)
check("listed: the mark taken away, the project is hidden again (nothing was deleted)", not by("projects/iota")["listed"] and "projects/iota" in reg())
prj.add_pending(by("ops/tool")["id"], "ops-tool-main", {"front": True, "role": "main", "mandate_line": "m"}, by="x", at="y")
check("listed: an agent only registered (its page line owed) counts: the project is listed, by agents", by("ops/tool")["listed_by"] == "agents" and by("ops/tool")["agents"]["ops-tool-main"]["page_owed"] is True)
d = idfile(); d["pending_agents"] = {}; (T / "store/project-record.json").write_text(json.dumps(d))
check("listed: …and hidden when it is gone", not by("ops/tool")["listed"])

# ---- 3. list by scope, with and without a search
st, d = lst("home")
check("list: scope home without a search → the listed projects of home only, each with the fields the form needs",
      st == 200 and [r["key"] for r in d["projects"]] == ["projects/alpha", "projects/old-edge", "projects/subonly"] and d["scope"] == "home" and d["q"] == "" and d["scopes"] == ["work", "home", "ops"]
      and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", d["generated"])
      and set(d["projects"][0]) == {"id", "key", "title", "name", "type", "hub", "scope", "listed", "hidden", "listed_by", "keeper", "main", "agents", "items_30d", "status", "retired"}, (st, [r["key"] for r in d["projects"]]))
a = d["projects"][0]
check("list: a row is the record: id, title, scope, listed true / hidden false, keeper, main agent, agents with front / role / mandate_line", ID.match(a["id"]) and a["title"] == "Alpha" and a["scope"] == "home"
      and a["listed"] is True and a["hidden"] is False and a["keeper"] == "home-sparrow" and a["main"] == "home-sparrow-main"
      and a["agents"]["home-sparrow-docs"] == {"front": True, "role": "docs", "mandate_line": "keeps the docs"}, a)
check("list: scope ops → gadget only; scope work → epsilon only (a hidden work page is not shown); no sub-page anywhere",
      keys("ops") == ["ops/gadget", "projects/noname"] and keys("work") == ["projects/epsilon"] and not any(k in keys("all") for k in ("projects/alpha/sub", "projects/subonly/notes")), (keys("ops"), keys("work")))
check("list: no scope or 'all' → every listed project, whatever its scope, by key", keys() == keys("all") == sorted(["projects/alpha", "projects/old-edge", "projects/subonly", "ops/gadget", "projects/epsilon", "projects/noname"]), keys())
st, d = lst("home", "room")
check("list: a search adds the hidden projects of the scope that match by name (not the other scopes') and marks them hidden; the listed ones stay, first",
      st == 200 and [r["key"] for r in d["projects"]] == ["projects/alpha", "projects/old-edge", "projects/subonly", "projects/iota"] and keys("ops", "ROOM") == ["ops/gadget", "projects/noname", "projects/zeta"], (keys("home", "room"), keys("ops", "ROOM")))
z = [r for r in lst("ops", "room")[1]["projects"] if r["key"] == "projects/zeta"][0]
check("list: …the hidden row says hidden true, listed false, listed_by empty, with its scope and title", z["hidden"] is True and z["listed"] is False and z["listed_by"] == "" and z["scope"] == "ops" and z["title"] == "Zeta" and z["name"] == "Zeta room", z)
check("list: a search matches the page's title (case-insensitive) → iota by 'PAPER'; and its key → 'iot'; and the name → 'printer ro'", "projects/iota" in keys("home", "PAPER") and "projects/iota" in keys("home", "iot")
      and "projects/iota" in keys("home", "printer ro") and "projects/iota" not in keys("home", "zzz") and "projects/iota" not in keys("home"), keys("home", "PAPER"))
check("list: a search for a hidden project in another scope does not show it (zeta is ops)", "projects/zeta" not in keys("home", "zeta") and "projects/zeta" in keys("ops", "zeta") and "projects/zeta" in keys("all", "zeta"))
check("list: a search shows a type: note page that project-agent would take (hidden, with its type) but never a page with a hub: line (theta, summit, lantern)",
      "ops/notebook" in keys("all", "notebook") and [r for r in lst("all", "notebook")[1]["projects"] if r["key"] == "ops/notebook"][0]["type"] == "note" and [r for r in lst("all", "notebook")[1]["projects"] if r["key"] == "ops/notebook"][0]["hidden"] is True
      and not any(k in keys("all", n) for k, n in (("projects/theta", "theta"), ("projects/summit", "summit"), ("projects/lantern", "lantern"))), keys("all", "notebook"))
check("list: a search never shows a sub-page (alpha/sub matches 'sub', subonly is listed anyway)", "projects/alpha/sub" not in keys("all", "sub") and "projects/alpha/sub/deep" not in keys("all", "deep") and "projects/subonly" in keys("all", "sub"))
check("list: listed rows come before hidden matches, each group by key", keys("all", "e")[:6] == sorted(keys("all")) and all(r["hidden"] for r in lst("all", "e")[1]["projects"][6:]))
st, body = lst("nowhere")
check("list: a scope that does not exist is a 400 naming the scopes, not an empty list", st == 400 and "work | home | ops | all" in body, (st, body))
st, body = lst("home", "x" * 201); check("list: a search over 200 characters is a 400", st == 400, (st, body))
check("list: the records carry nothing a reader of the old shape needs removed (id, key, keeper, agents)", all({"id", "key", "keeper", "agents"} <= set(r) for r in lst("all")[1]["projects"]))

# ---- 4. a new project
class FakeIO:
    def __init__(s): s.pages = {}; s.revs = {}; s.creates = []; s.gets = []; s.puts = []; s.timeline = []; s.mode = "ok"; s.put_mode = "ok"
    def get(s, slug): s.gets.append(slug); return (s.pages[slug], f"r{s.revs.get(slug, 1)}") if slug in s.pages else (None, None)
    def create(s, slug, content):
        s.creates.append((slug, content))
        if s.mode == "refused": return "refused", "page already exists"
        if s.mode == "unknown": return "unknown", "the put timed out"
        if s.mode == "exists": return "exists", '{"error":"revision_required"}'
        s.pages[slug] = content; return "ok", "{}"
    def put(s, slug, content, rev):
        s.puts.append((slug, rev))
        if s.put_mode == "refused": return "refused", "gbrain said no"
        if s.put_mode == "unknown": return "unknown", "no answer"
        if slug not in s.pages or rev != f"r{s.revs.get(slug, 1)}": return "refused", "the page changed since it was read"
        s.pages[slug] = content; s.revs[slug] = s.revs.get(slug, 1) + 1; return "ok", ""
    def add_timeline(s, slug, date, summary, detail, source, request_id=""): s.timeline.append((slug, summary)); return ""
gio = FakeIO(); server._pform.PAGE_IO = gio
def mk(key, scope, title="", sender="fleet-web", **kw): return server._client_post("box-c", "project", {"key": key, "scope": scope, "title": title, "sender": sender, **kw})
st, out = mk("projects/new-one", "work", "New one")
r = out.get("project", {})
check("new project: 200, created, the page written once through gbrain at that key", st == 200 and out["created"] is True and out["page"] == {"key": "projects/new-one", "state": "ok", "display_name": "work-new-one"}
      and [c[0] for c in gio.creates] == ["projects/new-one"], (st, out))
body = gio.creates[0][1]
fm, rest = body[4:].split("\n---\n", 1)
check("new project: the page is the template of projects/example (Part 2): frontmatter, then Goal, Current state, Decisions, Open questions, Open work, Sensitive records, Where things are, the timeline marker, Timeline",
      body.startswith("---\ntype: project\n") and [m for m in re.findall(r"(?m)^(##? .*)$", rest)] == ["# New one", "## Goal", "## Current state (as of " + datetime.datetime.now(prj._cfg.tz()).strftime("%Y-%m-%d") + ")", "## Decisions",
      "## Open questions", "## Open work, in planned order", "## Sensitive records — what exists, who can fetch it, where", "## Where things are", "## Timeline"]
      and rest.index("<!-- timeline -->") < rest.index("## Timeline") and re.search(r"(?m)^- \*\*\d{4}-\d\d-\d\d\*\* \| stackshot — Page made", rest), rest[:1500])
check("new project: the frontmatter holds type, title, org (the scope), name, status, created, display-name by the naming convention, no agents map and no tags", 'title: "New one"' in fm and "org: work" in fm and "status: active" in fm
      and "display-name: work-new-one" in fm and "steward:" not in fm and "agents" not in fm and "tags" not in fm and re.search(r"created: \"\d{4}-\d\d-\d\dT[\d:.]+Z\"", fm), fm)
check("new project: the template links the rulebook and the template page the way pages do ([[slug]] then its GitHub link)", "[[projects/example]] ([GitHub](" in rest and "RULES_EXAMPLE.md" in rest)
check("new project: the record is listed on purpose in the scope asked, with the title, the id, a keeper as keeper, no agents", r["key"] == "projects/new-one" and ID.match(r["id"]) and r["scope"] == "work" and r["scope_set"] is True
      and r["listed"] is True and r["listed_by"] == "on_purpose" and r["title"] == "New one" and r["keeper"] == "work-new-one" and r["agents"] == {} and r["sub_page"] is False, r)
NEW = r["id"]
check("new project: the id file holds the id, the key and the marks (scope, on_purpose, who, what was made); nothing else changed", idfile()["ids"][NEW] == "projects/new-one"
      and idfile()["marks"][NEW]["scope"] == "work" and idfile()["marks"][NEW]["by"] == "fleet-web" and idfile()["marks"][NEW]["on_purpose"].endswith("Z") and idfile()["marks"][NEW]["made"]["display_name"] == "work-new-one", idfile()["marks"].get(NEW))
check("new project: it is in the list at once, before the registry has read its page (the registry does not hold it)", "projects/new-one" not in reg() and "projects/new-one" in keys("work")
      and "projects/new-one" not in keys("home"), (keys("work"), "projects/new-one" in reg()))
check("new project: …and in the published file at once, with its scope and listing", pj()["projects"][NEW]["scope"] == "work" and pj()["projects"][NEW]["listed"] is True and pj()["by_key"]["projects/new-one"] == NEW)
check("new project: the lookup by id, key and bare slug finds it", rec(NEW)["key"] == rec("projects/new-one")["key"] == rec("new-one")["key"] == "projects/new-one")
# the registry's own reader on the page written, the way the publisher will read it after gbrain's mirror has it
(T / "brain/projects/new-one.md").write_text(body, encoding="utf-8"); p.cmd_registry(quiet=True)
e = reg()["projects/new-one"]
check("new project: the registry's reader parses the page: title, org work, keeper as keeper, status active, the same id", e["title"] == "New one" and e["org"] == "work" and e["session"] == "work-new-one" and e["role"] == "name"
      and e["status"] == "active" and e["id"] == NEW and not e.get("agents"), e)
check("new project: once the registry has the page there is one record, not two, with the same id; the scope set stays", [r["key"] for r in lst("all")[1]["projects"]].count("projects/new-one") == 1
      and rec("projects/new-one")["id"] == NEW and rec(NEW)["listed_by"] == "on_purpose" and rec(NEW)["scope_set"] is True)
(T / "brain/projects/new-one.md").unlink(); p.cmd_registry(quiet=True)
check("new project: …and a registry that no longer has the page (not read yet) still has it from the mark", "projects/new-one" not in reg() and rec(NEW) is not None and not prj.with_made({})["projects/new-one"].get("agent_records"))

st, out = mk("ops/new-tool", "ops", "")
body2 = gio.creates[-1][1]
check("new project: an ops key and scope with no title → the title from the slug, name ops-<slug>, org home with the ops tag", st == 200 and out["project"]["title"] == "New tool" and out["page"]["display_name"] == "ops-new-tool"
      and "org: home" in body2 and "tags:\n  - ops" in body2 and out["project"]["scope"] == "ops", (st, out, body2[:300]))
st, out = mk("projects/new-infra", "ops", "A new ops project")
body3 = gio.creates[-1][1]
check("new project: the keeper follows the scope: ops → ops-<slug> (a projects/ key too), org home with the ops tag; home → home-<slug>; a slug already starting with the scope is its own name",
      st == 200 and out["page"]["display_name"] == "ops-new-infra" and "display-name: ops-new-infra" in body3 and out["page"]["display_name"] == "ops-new-infra" and "org: home" in body3 and "tags:\n  - ops" in body3 and prj.display_name_for("projects/work-site", "work") == "work-site"
      and prj.display_name_for("ops/ops-x", "ops") == "ops-x" and prj.display_name_for("projects/bar", "home") == "home-bar" and prj.display_name_for("projects/bar", "work") == "work-bar" and prj.display_name_for("ops/foo") == "ops-foo"
      and prj.display_name_for("projects/foo") == "home-foo", (st, out))
st, out = mk("projects/work-new-lab", "work", "Sample new lab")
check("new project: a projects/work-… slug is its own keeper name (work-new-lab)", st == 200 and out["page"]["display_name"] == "work-new-lab" and "display-name: work-new-lab" in gio.creates[-1][1], (st, out))
st, out = mk("projects/new-home", "home", "Oliver's plan: a colon, an apostrophe & more")
check("new project: a title with a colon and an apostrophe is kept intact in the frontmatter (a JSON string is a valid YAML scalar) and the registry's reader gets it back", st == 200
      and 'title: "Oliver\'s plan: a colon, an apostrophe & more"' in gio.creates[-1][1], gio.creates[-1][1][:200])
(T / "brain/projects/new-home.md").write_text(gio.creates[-1][1], encoding="utf-8"); p.cmd_registry(quiet=True)
for k_, sc_ in (("projects/new-one", "work"), ("projects/new-infra", "ops"), ("projects/new-home", "home"), ("ops/new-tool", "ops"), ("projects/work-new-lab", "work")):
    q_ = [c for c in gio.creates if c[0] == k_][-1][1]; (T / "brain" / (k_ + ".md")).write_text(q_, encoding="utf-8")
p.cmd_registry(quiet=True)
check("new project: the scope is read back from the page alone, with no mark (work, ops by tag and keeper, home, an ops/ key, a work- slug)",
      all(prj.derive_scope(k_, reg()[k_], reg()) == sc_ for k_, sc_ in (("projects/new-one", "work"), ("projects/new-infra", "ops"), ("projects/new-home", "home"), ("ops/new-tool", "ops"), ("projects/work-new-lab", "work"))),
      {k_: prj.derive_scope(k_, reg()[k_], reg()) for k_ in ("projects/new-one", "projects/new-infra", "projects/new-home", "ops/new-tool", "projects/work-new-lab")})
for k_ in ("projects/new-one", "projects/new-infra", "ops/new-tool", "projects/work-new-lab"): (T / "brain" / (k_ + ".md")).unlink()
check("…title read back by the registry", reg()["projects/new-home"]["title"] == "Oliver's plan: a colon, an apostrophe & more", reg()["projects/new-home"]["title"])
(T / "brain/projects/new-home.md").unlink(); p.cmd_registry(quiet=True)

n0, ids_before = len(gio.creates), dict(idfile()["ids"])
def refused(label, st_want, key, scope="home", frag="", **kw):
    st, out = mk(key, scope, **kw)
    check(f"new project refusal: {label} → {st_want}, no page written, nothing recorded", st == st_want and (frag in out.get("error", "")) and len(gio.creates) == n0 and idfile()["ids"] == ids_before, (st, out))
refused("a key whose registry entry exists", 409, "projects/alpha", frag="post project-list")
refused("a key with sub-pages in the registry", 409, "projects/subonly", frag="already exists")
(T / "brain/projects/onbrain.md").write_text("---\ntitle: x\n---\n"); (T / "brain/ops/dironly").mkdir()
refused("a page file already in the pages checkout, not yet in the registry", 409, "projects/onbrain", frag="already exists")
refused("a directory of sub-pages already in the pages checkout", 409, "ops/dironly", frag="already exists")
gio.pages["projects/ingbrain"] = "---\ntitle: x\n---\n"
refused("a page gbrain already has (the mirror has not got it yet)", 409, "projects/ingbrain", frag="already exists")
refused("a key outside the page dirs", 400, "people/someone", frag="projects/<slug> or ops/<slug>")
refused("a key with a sub-path (a sub-page is never listed)", 400, "projects/alpha/newsub", frag="one level")
refused("a slug with capitals", 400, "projects/Bad", frag="lowercase")
refused("a slug with a space or dots", 400, "projects/a b", frag="lowercase"); refused("a bare slug", 400, "justaslug", frag="projects/<slug>")
refused("an empty slug", 400, "projects/", frag="lowercase"); refused("a slug of dashes", 400, "projects/-a--b-", frag="lowercase")
refused("a scope that does not exist", 400, "projects/fine", scope="elsewhere", frag="work | home | ops")
refused("no scope", 400, "projects/fine", scope="", frag="required")
refused("a title with a quotation mark", 400, "projects/fine", title='say "hi"', frag="title")
refused("a title with a control character", 400, "projects/fine", title="a\x01b", frag="title")
refused("a sender label with a control character", 400, "projects/fine", sender="a\nb", frag="sender")
check("new project refusal: no key at all → 400", mk("", "home")[0] == 400 and len(gio.creates) == n0)
gio.mode = "refused"; st, out = mk("projects/rejected", "home", "R")
check("new project: gbrain refusing the write → 502 saying so, and no id, no mark, no record", st == 502 and "gbrain refused" in out["error"] and "page already exists" in out["error"] and "projects/rejected" not in idfile()["ids"].values()
      and rec("projects/rejected") is None, (st, out))
gio.mode = "unknown"; st, out = mk("projects/silent", "home", "S")
check("new project: gbrain not answering → 502 (the page may exist: ask again), nothing recorded", st == 502 and "may or may not" in out["error"] and "projects/silent" not in idfile()["ids"].values() and rec("projects/silent") is None, (st, out))
gio.mode = "ok"
good = (T / "store/project-record.json").read_text(); (T / "store/project-record.json").write_text("{not json"); n1 = len(gio.creates)
st, out = mk("projects/while-broken", "home", "W")
check("new project: a damaged id file → 503 before any page is written", st == 503 and len(gio.creates) == n1 and "nothing was made" in out["error"], (st, out))
(T / "store/project-record.json").write_text(good)
st, out = mk("projects/new-one", "work", "again")
check("new project: made twice → the second is a 409 pointing at post project-list (the page is never replaced)", st == 409 and "post project-list" in out["error"] and len([c for c in gio.creates if c[0] == "projects/new-one"]) == 1, (st, out))

gio.mode = "exists"; nx = len(gio.creates); st, out = mk("projects/raced", "home", "R")
check("new project: gbrain answering that the page exists (revision_required) is a 409 pointing at post project-list, not a 502; nothing recorded", st == 409 and "post project-list" in out["error"] and len(gio.creates) == nx + 1
      and "projects/raced" not in idfile()["ids"].values() and rec("projects/raced") is None, (st, out))
gio.mode = "ok"
from stackshot.router import page_debt; from stackshot.projects import rename_page
real_gb = rename_page.gb
def gbio(ans):
    rename_page.gb = lambda args, stdin=None: ans
    try: return page_debt.GbrainIO().create("projects/x", "page")
    finally: rename_page.gb = real_gb
check("GbrainIO.create: a clean answer is ok; revision_required (rc 0 or 1) is exists; any other error or a non-zero exit is refused; a timeout, a kill and a failure are unknown",
      gbio((0, '{"status":"ok"}'))[0] == "ok" and gbio((1, '{"error":"revision_required"}'))[0] == "exists" and gbio((0, '{"error": "revision_required", "fix": {}}'))[0] == "exists"
      and gbio((0, '{"error": "bad"}'))[0] == "refused" and gbio((2, "boom"))[0] == "refused" and gbio((-9, ""))[0] == "unknown", [gbio((0, '{"status":"ok"}')), gbio((1, '{"error":"revision_required"}'))])
def gbraise(exc):
    def f(args, stdin=None): raise exc
    rename_page.gb = f
    try: return page_debt.GbrainIO().create("projects/x", "page")[0]
    finally: rename_page.gb = real_gb
import subprocess
check("GbrainIO.create: a timeout and an unexpected failure are unknown, not refusals", gbraise(subprocess.TimeoutExpired("gbrain", 1)) == "unknown" and gbraise(OSError("no gbrain")) == "unknown")
check("GbrainIO.create: it writes with no --expected-revision (gbrain's way of creating), the slug and the page on stdin", (lambda calls: (setattr(rename_page, "gb", lambda args, stdin=None: (calls.append((args, stdin)), (0, "{}"))[1]),
      page_debt.GbrainIO().create("projects/x", "PAGE"), setattr(rename_page, "gb", real_gb), calls)[-1])([]) == [(["put", "projects/x"], "PAGE")])
st, out = mk("projects/yaml-check", "home", "Yaml check")
check("new project: the reply carries page_yaml, empty until an agent is registered (project-agent's reply fills it)", st == 200 and out["page_yaml"] == "" and "page_yaml" in out, (st, out))

# ---- 5. list a hidden project again
def relist(key, **kw): return server._client_post("box-c", "project-list", {"key": key, **kw})
H = rec("projects/eta")["id"]
check("re-list: before, eta is hidden but found by a search", "projects/eta" not in keys("home") and "projects/eta" in keys("home", "eta"))
nc = len(gio.creates); st, out = relist("projects/eta", sender="fleet-web")
check("re-list: 200, changed, the record listed by on_purpose, its page and agents untouched", st == 200 and out["changed"] is True and out["project"]["listed"] and out["project"]["listed_by"] == "on_purpose" and out["project"]["id"] == H
      and idfile()["marks"][H]["by"] == "fleet-web" and "projects/eta" in keys("home") and len(gio.creates) == nc, (st, out))
check("re-list: …listed in its scope from then on, with no search", "projects/eta" in keys("home") and pj()["projects"][H]["listed"] is True)
before = {k: v for k, v in idfile()["marks"][H].items() if k != "at"}; st, out = relist(H, sender="fleet-web")
check("re-list: said again (by id) → 200, changed false, the mark as it was but for the renewed time", st == 200 and out["changed"] is False and {k: v for k, v in idfile()["marks"][H].items() if k != "at"} == before and "nothing changed" in out["note"], (st, out))
K = rec("projects/kappa")["id"]
st, out = relist("kappa", scope="ops", sender="fleet-web")
check("re-list: by bare slug with a scope → listed and the scope set on purpose (kappa was home)", st == 200 and out["project"]["scope"] == "ops" and out["project"]["scope_set"] is True and "projects/kappa" in keys("ops"), (st, out))
st, out = relist("projects/kappa", scope="work", sender="fleet-web")
check("re-list: a new scope on a listed project → changed, the scope moved", st == 200 and out["changed"] is True and out["project"]["scope"] == "work", (st, out))
st, out = relist("projects/alpha/sub")
check("re-list: a sub-page → 400 naming the project above it, nothing marked", st == 400 and "projects/alpha" in out["error"] and "never listed" in out["error"] and not (idfile().get("marks", {}).get(rec("projects/alpha/sub")["id"])), (st, out))
check("re-list: a sub-page two levels down names its project too", relist("projects/alpha/sub/deep")[0] == 400 and "projects/alpha" in relist("projects/alpha/sub/deep")[1]["error"])
st, out = relist("projects/theta")
check("re-list: a page with a hub: line → 400 naming its hub, nothing marked; a type: note page → 400, nothing marked", st == 400 and "projects/epsilon" in out["error"] and not idfile().get("marks", {}).get(rec("projects/theta")["id"])
      and relist("ops/notebook")[0] == 400 and "note" in relist("ops/notebook")[1]["error"] and not idfile().get("marks", {}).get(rec("ops/notebook")["id"]), (st, out))
check("re-list: an unknown project → 404; no key → 400; a bad scope → 400", relist("projects/nowhere")[0] == 404 and relist("")[0] == 400 and relist("projects/eta", scope="elsewhere")[0] == 400)
page("ops/iota.md", "type: project\ntitle: Iota ops\ndisplay-name: ops-iota"); p.cmd_registry(quiet=True); fresh()
st, out = relist("iota"); check("re-list: an ambiguous slug → 400 naming both pages; the full key works", st == 400 and "projects/iota" in out["error"] and "ops/iota" in out["error"] and relist("ops/iota")[0] == 200, (st, out))
st, out = relist("projects/eta", sender="a\nb"); check("re-list: a sender label with a control character → 400", st == 400)
good = (T / "store/project-record.json").read_text(); (T / "store/project-record.json").write_text("{not json")
st, out = relist("projects/delta"); check("re-list: a damaged id file → 503, nothing changed", st == 503 and "nothing was changed" in out["error"], (st, out))
(T / "store/project-record.json").write_text(good)
check("re-list: …and the file is as it was", idfile() == json.loads(good) and not idfile().get("marks", {}).get(rec("projects/delta")["id"]))

# ---- 6. project-agent: the form's agent (the record first, the page's agents block written from it)
from stackshot.projects import project_verbs as pverbs; from stackshot.projects import pages as _pg
def pa(project, name, sender, role="main", front=True, mandate="the main agent"): return server._client_post("box-c", "project-agent", {"project": project, "name": name, "role": role, "front": front, "mandate": mandate, "sender": sender})
def page_agents(key): return _pg.split_agents(_pg.frontmatter_text(gio.pages[key]).get("agents"))
locked_seen = []; real_add = pverbs.agent_add
def spy_add(*a, **k): locked_seen.append(server._PROJECT_LOCK.locked()); return real_add(*a, **k)
pverbs.agent_add = spy_add
st, out = pa(NEW, "work-new-one-main", "fleet-web")
check("project-agent: a project just made takes its first agent from the label that made it (the form has no session): 200, listed in the record, no page line owed", st == 200 and out["page_owed"] is False and out["project"] == NEW
      and pverbs.pr.entries()[NEW]["agents"]["work-new-one-main"]["by"] == "fleet-web" and not idfile().get("pending_agents", {}).get(NEW), (st, out))
check("project-agent: …the record is written under the project lock (two parallel first-agent calls cannot both pass), the page after it, outside the lock", locked_seen == [True] and out["mirror"]["state"] == "written", (locked_seen, out.get("mirror")))
check("project-agent: …the page's agents block is written from the record (nothing is owed: page_yaml is empty)", out["page_yaml"] == "" and page_agents("projects/new-one") == ({"work-new-one-main": "the main agent"}, {}), (out.get("page_yaml"), page_agents("projects/new-one")))
r = rec(NEW)
check("project-agent: …it shows in the record and the list: front, role, mandate_line, no page_owed; the project is listed by agents now and its main agent is named",
      r["agents"] == {"work-new-one-main": {"front": True, "role": "main", "mandate_line": "the main agent"}} and r["listed_by"] == "agents"
      and [x for x in lst("work")[1]["projects"] if x["key"] == "projects/new-one"][0]["main"] == "work-new-one-main"
      and "page_owed" not in pj()["projects"][NEW]["agents"]["work-new-one-main"], r)
st, out = pa(NEW, "work-new-one-second", "fleet-web", role="second", front=False, mandate="b: with a colon")
check("project-agent: while every agent was listed by that same label, the label may add more (a background one: the page gets it under background:, a mandate with a colon quoted)", st == 200
      and "work-new-one-second" in rec(NEW)["agents"] and page_agents("projects/new-one") == ({"work-new-one-main": "the main agent", "work-new-one-second": "b: with a colon"}, {"work-new-one-second": "b: with a colon"}), (out, page_agents("projects/new-one")))
st, out = pa(NEW, "work-new-one-other", "other-label", role="other")
check("project-agent: …another label may not (403), and a stranger's session id is refused as ever; a name still proves nothing", st == 403 and "work-new-one-other" not in rec(NEW)["agents"]
      and pa(NEW, "work-new-one-other", U["home-outsider"], role="other")[0] == 403 and pa(NEW, "work-new-one-third", "work-new-one-main", role="third")[0] == 403)
st, out = pa(NEW, "work-new-one-main", "fleet-web")
check("project-agent: said again as it stands → 200, nothing new, the page unchanged", st == 200 and "nothing changed" in out["note"] and list(rec(NEW)["agents"]) == ["work-new-one-main", "work-new-one-second"], (st, out))
st, out = pa(NEW, "work-new-one-main", "fleet-web", mandate="another mandate")
check("project-agent: the same name with another mandate is a 409 (retire it or rename it first); the record keeps the old line", st == 409 and rec(NEW)["agents"]["work-new-one-main"]["mandate_line"] == "the main agent", (st, out))
pverbs.agent_add(NEW, "work-new-one-keeper", True, "listed by a session", by="some-session", io=gio)
st, out = pa(NEW, "work-new-one-late", "fleet-web", role="late")
check("project-agent: once an agent that this label did not list is on the project the label is no longer enough: only the old rule (403)", st == 403 and "work-new-one-late" not in rec(NEW)["agents"], (st, out))
pverbs.agent_retire(NEW, "work-new-one-keeper", by="some-session", io=gio)
page_text_before = gio.pages["projects/new-one"]
gio.pages["projects/new-one"] = page_text_before.replace("work-new-one-main: the main agent", "work-new-one-main: edited by hand").replace("status: active", "status: archived")
pverbs.mirror(NEW, gio)
check("a page edit to a mirrored line is overwritten by the next mirror write (the agents mandate and the status line come from the record again)", page_agents("projects/new-one")[0]["work-new-one-main"] == "the main agent"
      and "status: active" in gio.pages["projects/new-one"], gio.pages["projects/new-one"][:300])
st, out = pa("projects/new-home", "home-new-home-main", "fleet-web")
check("project-agent: a project made but not yet in the registry takes the agent too (by key; the name must start with the keeper name)", st == 200 and "home-new-home-main" in rec("projects/new-home")["agents"], (st, out))
st, out = pa(IOTA, "home-iota-main", "fleet-web")
check("project-agent: a hidden project never listed on purpose has no such exception: a label is a name, 403", st == 403 and "name" in out["error"], (st, out))
relist("projects/iota", sender="fleet-web"); st, out = pa(IOTA, "home-iota-main", "fleet-web")
check("project-agent: …listed again on purpose, it takes its first agent from the label that listed it, and the list shows the agent (a page the page store does not have is told, and not written)", st == 200 and "page_owed" not in rec(IOTA)["agents"]["home-iota-main"]
      and out["mirror"]["state"] == "no-page" and "not in the page store" in out["note"], (st, out))
relist("projects/kappa", sender="fleet-web"); st, out = pa("projects/kappa", "home-kappa-main", "another-form")
check("project-agent: a label other than the one that made or listed it is refused (kappa listed by fleet-web, asked by another-form)", st == 403 and "home-kappa-main" not in rec("projects/kappa")["agents"], (st, out))
st, out = pa("projects/kappa", "home-kappa-main", "fleet-web")
check("project-agent: …the right label gets it", st == 200 and "home-kappa-main" in rec("projects/kappa")["agents"], (st, out))
K2 = rec("projects/older-edge")["id"]; relist("projects/older-edge", sender="fleet-web")
old_t = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=61)).strftime("%Y-%m-%dT%H:%M:%SZ"); prj.set_mark(K2, at=old_t, on_purpose=old_t)
st, out = pa("projects/older-edge", "home-older-edge-main", "fleet-web")
check("project-agent: a mark older than an hour is refused (61 minutes), the label being the right one", st == 403 and "home-older-edge-main" not in rec("projects/older-edge")["agents"], (st, out))
fresh_t = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=59)).strftime("%Y-%m-%dT%H:%M:%SZ"); prj.set_mark(K2, at=fresh_t)
check("project-agent: …59 minutes is still inside the window", pa("projects/older-edge", "home-older-edge-main", "fleet-web")[0] == 200)
relist("projects/live-keeper", sender="fleet-web"); st, out = pa("projects/live-keeper", "home-fresh-main", "fleet-web")
check("project-agent: an agentless project whose keeper IS a present session (home-fresh) refuses the label exception, however fresh the list: the keeper's own id may", st == 403 and "home-fresh-main" not in rec("projects/live-keeper")["agents"]
      and pa("projects/live-keeper", "home-fresh-main", U["home-fresh"])[0] == 200, (st, out))
check("project-agent: the keeper's liveness is the fleet's present-only lookup: kappa's keeper home-kappa is a retired session in the fleet's identity records (its name is in names(), but by_name has no present holder), and the label still got in above",
      "home-kappa" in set(server._anc.names().values()) and "home-kappa" not in server._anc.names().by_name and "home-fresh" in server._anc.names().by_name)
st, out = pa("projects/delta", "home-delta-main", "fleet-web")
check("project-agent: a hidden project never listed (delta) still refuses a label; its keeper's session may list one, which lists the project by agents",
      st == 403 and rec("projects/delta")["listed"] is False, (st, out))
st, out = pa("ops/tool", "ops-tool-main", U["ops-tool"])
check("project-agent: the keeper's session id lists an agent on a hidden project (ops/tool): the project becomes listed, by agents", st == 200 and rec("ops/tool")["listed_by"] == "agents" and "ops/tool" in keys("ops"), (st, out))
check("project-agent: the agent is in the published file with no page line owed, and the registry file the pages wrote does not hold it", "page_owed" not in pj()["projects"][rec("ops/tool")["id"]]["agents"]["ops-tool-main"] and "agents" not in reg()["ops/tool"])
pverbs.agent_add = real_add
page("ops/tool.md", "type: project\ntitle: A tool box\ndisplay-name: ops-tool\nagents:\n  ops-tool-other: a page edit"); p.cmd_registry(quiet=True)
_projects_registry._projects_sync(now=NOW + 1, force=True)
check("project-agent: …a page edit made after the project has its entry is not read: the record's agents stay (the entry wins), the page's own line is not an agent", list(rec("ops/tool")["agents"]) == ["ops-tool-main"] and rec("ops/tool")["listed_by"] == "agents", rec("ops/tool")["agents"])

# ---- 6c. post project-agent-mandate: the keeper or a front agent changes a listed agent's mandate line; the record first, the page from it, and the page cannot undo it
st, out = mk("projects/mand", "home")
MD = out.get("project", {}).get("id", "")
OLD_B = "builds, via subagents"
NEW_B = "builds the server; reviews each change; releases for every builder"
st1, _o = pa("projects/mand", "home-mand-main", U["home-mand"])
st2, _o = pa("projects/mand", "home-mand-builder", U["home-mand"], role="builder", front=False, mandate=OLD_B)
def pam(project, name, sender, mandate=NEW_B): return server._client_post("box-c", "project-agent-mandate", {"project": project, "name": name, "mandate": mandate, "sender": sender})
check("agent mandate: (setup) a project with a front agent and a background builder, both on the page", st == 200 and st1 == 200 and st2 == 200 and page_agents("projects/mand") == ({"home-mand-main": "the main agent", "home-mand-builder": OLD_B}, {"home-mand-builder": OLD_B}), page_agents("projects/mand"))
st, out = pam("projects/mand", "home-mand-builder", "home-mand-main")
check("agent mandate: a name as sender proves nothing -> 403, the old line stays", st == 403 and "name" in out["error"] and rec(MD)["agents"]["home-mand-builder"]["mandate_line"] == OLD_B, (st, out))
st, out = pam("projects/mand", "home-mand-builder", U["home-outsider"])
check("agent mandate: a session that is neither the keeper nor a front agent -> 403 naming the rule, the old line stays", st == 403 and "keeper" in out["error"] and "front agent" in out["error"] and rec(MD)["agents"]["home-mand-builder"]["mandate_line"] == OLD_B and page_agents("projects/mand")[1]["home-mand-builder"] == OLD_B, (st, out))
st, out = pam("projects/mand", "home-mand-builder", U["home-mand"])
check("agent mandate: the keeper's session id changes the line -> 200; the record holds it, the side and role stay, the answer carries the previous line", st == 200 and rec(MD)["agents"]["home-mand-builder"] == {"front": False, "role": "builder", "mandate_line": NEW_B}
      and out["previous"] == OLD_B and out["agent"] == {"home-mand-builder": {"front": False, "role": "builder", "mandate_line": NEW_B}}, (st, out))
check("agent mandate: ...the page's agents block was written from the record (the new line under background:, the front agent's line untouched)", out["mirror"]["state"] == "written" and page_agents("projects/mand") == ({"home-mand-main": "the main agent", "home-mand-builder": NEW_B}, {"home-mand-builder": NEW_B}), (out["mirror"], page_agents("projects/mand")))
st3, _o = pa("projects/mand", "home-mand-extra", U["home-mand"], role="extra", front=False, mandate="another")
check("agent mandate: a later mirror write (the next agent added) does not undo it", st3 == 200 and page_agents("projects/mand")[1]["home-mand-builder"] == NEW_B and rec(MD)["agents"]["home-mand-builder"]["mandate_line"] == NEW_B, (st3, page_agents("projects/mand")))
n_puts = len(gio.puts)
st, out = pam("projects/mand", "home-mand-builder", U["home-mand"])
check("agent mandate: the same line again -> 200 'nothing changed', no page write", st == 200 and "nothing changed" in out["note"] and len(gio.puts) == n_puts, (st, out))
gio.pages["projects/mand"] = gio.pages["projects/mand"].replace(NEW_B, "edited on the page by hand")
st, out = pam("projects/mand", "home-mand-builder", U["home-mand"])
check("agent mandate: the same line again while the page is out of step -> 200, the page is written from the record, and the note does not say nothing changed", st == 200 and out["mirror"]["state"] == "written" and "nothing changed" not in out["note"]
      and page_agents("projects/mand")[1]["home-mand-builder"] == NEW_B, (st, out))
st, out = pam("projects/mand", "home-mand-builder", U["home-mand-main"], mandate="  builds   the server;  reviews each change;  releases for every builder  ")
check("agent mandate: a front agent's own session id may change a line; the answer carries the stored, whitespace-folded line, not the raw input", st == 200 and out["agent"]["home-mand-builder"]["mandate_line"] == rec(MD)["agents"]["home-mand-builder"]["mandate_line"]
      and "  " not in out["agent"]["home-mand-builder"]["mandate_line"] and " " not in out["agent"]["home-mand-builder"]["mandate_line"] and out["agent"]["home-mand-builder"]["mandate_line"] == NEW_B, (st, out))
st, out = pam("projects/mand", "home-mand-builder", U["home-mand-main"], mandate="uses a back\\slash")
check("agent mandate: a line with a backslash -> 400 saying to write it without; the line stays and the page still reads", st == 400 and "cannot contain a backslash" in out["error"] and rec(MD)["agents"]["home-mand-builder"]["mandate_line"] == NEW_B and page_agents("projects/mand")[1]["home-mand-builder"] == NEW_B, (st, out))
st, out = pam("projects/mand", "home-mand-main", "00000000-0000-4000-8000-0000000000ee")
check("agent mandate: an id that is no session of the fleet -> 403 saying it names nobody", st == 403 and "heartbeat" in out["error"], (st, out))
st, out = pam("projects/mand", "home-mand-ghost", U["home-mand"])
check("agent mandate: an agent that is not listed -> 404 naming it and pointing at agent_add; nothing written", st == 404 and "home-mand-ghost is not listed" in out["error"] and "agent_add" in out["error"] and "home-mand-ghost" not in rec(MD)["agents"], (st, out))
for bad_ in ("", "   ", "a\nb", "x" * 601):
    st, out = pam("projects/mand", "home-mand-builder", U["home-mand"], mandate=bad_)
    check(f"agent mandate: a bad line ({bad_[:8]!r}) -> 400 with a text that says what to change; the line stays", st == 400 and ("empty" in out["error"] or "one line" in out["error"]) and rec(MD)["agents"]["home-mand-builder"]["mandate_line"] == NEW_B, (st, out))
check("agent mandate: no such project -> 404; a missing sender -> 400", pam("projects/nowhere", "home-x-main", U["home-mand"])[0] == 404 and server._client_post("box-c", "project-agent-mandate", {"project": "projects/mand", "name": "home-mand-builder", "mandate": NEW_B})[0] == 400)
st, out = pa("projects/mand", "home-mand-builder", U["home-mand"], role="builder", front=False, mandate="something else")
check("agent mandate: project-agent with another line for a listed name is still a 409, and the text now names project-agent-mandate", st == 409 and "project-agent-mandate" in out["error"], (st, out))

# ---- 6a. the form call: a trusted label AND a trusted machine (the token's, never the body's) may add a pending agent to any LISTED project
page("projects/lambda.md", "type: project\ntitle: Lambda\norg: home\ndisplay-name: home-lambda\nagents:\n  home-lambda-main: talks to Oliver"); p.cmd_registry(quiet=True)
L = rec("projects/lambda")["id"]
def fpa(machine, project, name, sender, role="helper", front=False, mandate="a helper for the form"): return server._client_post(machine, "project-agent", {"project": project, "name": name, "role": role, "front": front, "mandate": mandate, "sender": sender})
def lam_pending():
    """The agents the form (or any label) listed on lambda: the record's agents that carry a `by` (the page's own line is the one without)."""
    return {n: a for n, a in (pverbs.pr.entries().get(L, {}).get("agents") or {}).items() if a.get("by")}
CFG0 = server._cfg.CFG.get("project_agent", "absent")
check("form call: the example config carries the section with the defaults (no sender label: the instance names its form's), and the code's defaults are neutral (no sender, no machine)",
      CFG0 == {"form_senders": [], "form_machines": ["box-a"]} and server._FORM_SENDERS == [] and server._FORM_MACHINES == [], CFG0)
server._cfg.CFG["project_agent"] = {"form_senders": ["fleet-web"], "form_machines": ["box-a"]}   # the instance's own config: it names its form's label
check("form call: the setup is a listed project that has agents (and no session's id is involved)", rec("projects/lambda")["listed"] is True and "home-lambda-main" in rec("projects/lambda")["agents"], rec("projects/lambda"))
st, out = fpa("box-a", "projects/lambda", "home-lambda-helper", "fleet-web")
check("form call: fleet-web from box-a on a listed project WITH agents → 200, listed in the record by the label (no page line owed: the page is written from the record)", st == 200 and out["page_owed"] is False
      and lam_pending()["home-lambda-helper"]["by"] == "fleet-web" and "page_owed" not in rec("projects/lambda")["agents"]["home-lambda-helper"], (st, out))
check("form call: …the reply carries no page_yaml (nothing is owed) and says the record has it", out["page_yaml"] == "" and "project record" in out["note"], out)
check("form call: …the page's own agent is untouched", rec("projects/lambda")["agents"]["home-lambda-main"] == {"front": True, "role": "main", "mandate_line": "talks to Oliver"}, rec("projects/lambda")["agents"])
st, out = fpa("box-c", "projects/lambda", "home-lambda-other", "fleet-web")
check("form call: the same label from a machine that is not in form_machines is refused as before (403: a name proves nothing)", st == 403 and "name" in out["error"] and "home-lambda-other" not in lam_pending(), (st, out))
st, out = fpa("box-a", "projects/lambda", "home-lambda-other", "another-form")
check("form call: a different label from the allowed machine is refused as before (403)", st == 403 and "name" in out["error"] and "home-lambda-other" not in lam_pending(), (st, out))
st, out = fpa("", "projects/lambda", "home-lambda-other", "fleet-web")
check("form call: …and a call with no machine proven is no form call", st == 403 and "home-lambda-other" not in lam_pending(), (st, out))
st, out = fpa("box-a", "projects/lambda", "home-lambda-other", "fleet-web", role="x" * 40)
check("form call: …the existing validation still applies (a role of 40 characters is a 400), and so does the project-name prefix (a name not starting home-lambda- is a 400)",
      st == 400 and fpa("box-a", "projects/lambda", "home-other-helper", "fleet-web")[0] == 400 and fpa("box-a", "projects/lambda", "home-lambda-", "fleet-web")[0] == 400
      and fpa("box-a", "projects/lambda", "home-lambda-x", "fleet-web", mandate="a\nb")[0] == 400 and set(lam_pending()) == {"home-lambda-helper"}, (st, out, lam_pending()))
st, out = fpa("box-a", "projects/delta", "home-delta-helper", "fleet-web")
check("form call: a hidden project is a 403 that says to list it again first, and nothing is recorded", st == 403 and "post project-list" in out["error"] and "home-delta-helper" not in rec("projects/delta")["agents"]
      and rec("projects/delta")["listed"] is False, (st, out))
st, out = fpa("box-a", "ops/notebook", "ops-notebook-helper", "fleet-web")
check("form call: a note page (never listed) is the same 403", st == 403 and "post project-list" in out["error"], (st, out))
st, out = fpa("box-a", "projects/theta", "home-theta-helper", "fleet-web")
check("form call: a page with a hub: line stays the 400 that names the hub page (the agents map is kept there)", st == 400 and "projects/epsilon" in out["error"], (st, out))
st, out = fpa("box-a", "projects/lambda", "home-lambda-main", "fleet-web", role="main", front=True, mandate="talks to Oliver")
check("form call: a name already on the page's map, said as the page has it → 200 \"already listed\", nothing changed", st == 200 and "already listed" in out["note"] and out["page_owed"] is False
      and "home-lambda-main" not in lam_pending(), (st, out))
st, out = fpa("box-a", "projects/lambda", "home-lambda-main", "fleet-web", role="main", front=False, mandate="something else")
check("form call: …a name on the page said differently is the existing 409 (the page is the authority); the page's agent is never edited and no pending copy is made", st == 409
      and rec("projects/lambda")["agents"]["home-lambda-main"]["mandate_line"] == "talks to Oliver" and "home-lambda-main" not in lam_pending(), (st, out))
pverbs.agent_add("projects/lambda", "home-lambda-seed", False, "the seed", by="someone-else", io=gio)
st, out = fpa("box-a", "projects/lambda", "home-lambda-seed", "fleet-web", role="seed", mandate="the form's idea of it")
check("form call: a name already listed by another sender, asked differently → the 409 (retire or rename it first), and that sender's entry is not changed", st == 409 and "already listed" in out["error"]
      and lam_pending()["home-lambda-seed"]["by"] == "someone-else" and lam_pending()["home-lambda-seed"]["mandate_line"] == "the seed", (st, out, lam_pending()))
st, out = fpa("box-a", "projects/lambda", "home-lambda-seed", "fleet-web", role="seed", mandate="the seed")
check("form call: …asked exactly as it stands → 200 \"already listed\", the first claimant stays on record", st == 200 and "already listed" in out["note"] and lam_pending()["home-lambda-seed"]["by"] == "someone-else", (st, out))
st, out = fpa("box-a", "projects/lambda", "home-lambda-helper", "fleet-web")
check("form call: the form's own agent said again → 200 \"already listed\" (idempotent)", st == 200 and "already listed" in out["note"] and lam_pending()["home-lambda-helper"]["by"] == "fleet-web", (st, out))
# a name belongs to one project (every path), names compare case-folded, a page's main beats a pending one, a body's machine counts for nothing
page("projects/lambda-docs.md", "type: project\ntitle: Lambda docs\norg: home\ndisplay-name: home-lambda-docs\nagents:\n  home-lambda-docs-main: the docs project's main"); page("projects/mu.md", "type: project\ntitle: Mu\norg: home\ndisplay-name: home-mu\nagents:\n  home-mu-main: m\n  home-lambda-Shared: a name Mu holds"); page("projects/alpha-docs.md", "type: project\ntitle: Alpha docs\norg: home\ndisplay-name: home-sparrow-docs\nagents:\n  home-sparrow-docs-main: m")
p.cmd_registry(quiet=True); MU = rec("projects/mu")["id"]
for nm_, why in (("home-lambda-docs-main", "an agent the longer-named project lists"), ("home-lambda-docs-extra", "a name under the longer keeper prefix, listed nowhere yet"), ("home-lambda-docs-x-y", "a deeper name under it")):
    st, out = fpa("box-a", "projects/lambda", nm_, "fleet-web")
    check(f"name owner: a form call on lambda cannot take {nm_!r} ({why}): 409, nothing recorded", st == 409 and "one project" in out["error"] and nm_ not in lam_pending(), (st, out))
st, out = fpa("box-a", "projects/lambda", "home-lambda-shared", "fleet-web")
check("name owner: a name another project's page map holds is a 409 (compared case-folded: Mu holds home-lambda-Shared)", st == 409 and "projects/mu" in out["error"] and "home-lambda-shared" not in lam_pending(), (st, out))
st, out = fpa("box-a", "projects/lambda", "home-lambda-SHARED", "fleet-web")
check("name owner: …in any case", st == 409 and "home-lambda-SHARED" not in lam_pending(), (st, out))
pverbs.agent_add("projects/mu", "home-lambda-pend", False, "mu's pending", by="someone-else", io=gio)
st, out = fpa("box-a", "projects/lambda", "home-lambda-PEND", "fleet-web")
check("name owner: a name another project has pending is a 409 too (case-folded)", st == 409 and "projects/mu" in out["error"] and "home-lambda-PEND" not in lam_pending() and "home-lambda-pend" not in lam_pending(), (st, out))
st, out = pa("projects/alpha", "home-sparrow-docs-main", U["home-sparrow-main"], role="docs-main")
st2, out2 = pa("projects/alpha", "home-sparrow-docs-extra", U["home-sparrow-main"], role="docs-extra")
check("name owner: the rule is every path's: the front agent's own session id gets the same 409 for another project's name and for a longer keeper prefix",
      st == 409 and st2 == 409 and "home-sparrow-docs-main" not in rec("projects/alpha")["agents"] and "home-sparrow-docs-extra" not in rec("projects/alpha")["agents"], (st, out, st2, out2))
st, out = pa("projects/alpha-docs", "home-sparrow-docs-fine", U["home-sparrow-main"], role="fine")
check("name owner: …while the longer-named project itself is not blocked by its own prefix (it is refused here only for the session not being its agent, 403, not 409)", st == 403, (st, out))
st, out = fpa("box-a", "projects/lambda-docs", "home-lambda-docs-fine", "fleet-web")
check("name owner: …a form call on the longer-named project takes a name under its own prefix (200)", st == 200 and "home-lambda-docs-fine" in rec("projects/lambda-docs")["agents"], (st, out))
st, out = fpa("box-a", "projects/lambda", "home-lambda-docsx", "fleet-web")
check("name owner: a prefix is only a prefix before the dash: home-lambda-docsx is no name of lambda-docs (200 on lambda)", st == 200 and "home-lambda-docsx" in lam_pending(), (st, out))
st, out = fpa("box-a", "projects/lambda", "home-lambda-main", "fleet-web", role="main", front=True, mandate="talks to Oliver")
st2, out2 = fpa("box-a", "projects/lambda", "home-lambda-MAIN", "fleet-web", role="main", front=True, mandate="talks to Oliver")
check("case-fold: a name on the page in another case, said as the page has it → 200 \"already listed\" under the page's spelling, no pending copy", st2 == 200 and "already listed" in out2["note"] and list(out2["agent"]) == ["home-lambda-main"]
      and not [n for n in lam_pending() if n.casefold() == "home-lambda-main"], (st2, out2))
st, out = fpa("box-a", "projects/lambda", "home-lambda-MAIN", "fleet-web", role="main", front=False, mandate="something else")
check("case-fold: …said differently, the 409 (the page is the authority)", st == 409 and "already listed" in out["error"] and not [n for n in lam_pending() if n.casefold() == "home-lambda-main"], (st, out))
st, out = fpa("box-a", "projects/lambda", "home-lambda-SEED", "fleet-web", role="seed", mandate="the form's idea of it")
check("case-fold: another sender's agent in another case, asked differently → the 409, and the entry is as it was", st == 409 and "already listed" in out["error"] and "home-lambda-SEED" not in lam_pending()
      and lam_pending()["home-lambda-seed"]["mandate_line"] == "the seed", (st, out))
st, out = fpa("box-a", "projects/lambda", "home-lambda-SEED", "fleet-web", role="seed", mandate="the seed")
check("case-fold: …as it stands → 200 \"already listed\", the first claimant stays and no second spelling is added", st == 200 and "already listed" in out["note"] and lam_pending()["home-lambda-seed"]["by"] == "someone-else"
      and "home-lambda-SEED" not in lam_pending(), (st, out))
st, out = fpa("box-a", "projects/lambda", "home-lambda-HELPER", "fleet-web", mandate="a different mandate, from the same sender")
check("case-fold: the same sender again in another case with another mandate is the 409 too (retire it first), and there is still one spelling", st == 409 and [n for n in lam_pending() if n.casefold() == "home-lambda-helper"] == ["home-lambda-helper"]
      and lam_pending()["home-lambda-helper"]["mandate_line"] == "a helper for the form", (st, out, lam_pending()))
st, out = fpa("box-a", "projects/lambda", "home-lambda-aaa-main", "fleet-web", role="aaa-main", front=True, mandate="a pending front main")
row = [x for x in lst("home")[1]["projects"] if x["key"] == "projects/lambda"][0]
check("main: a second front -main listed in the record is an agent like any other: of two, the first by name is the main (the project's list says which)", st == 200 and row["main"] == "home-lambda-aaa-main" and "home-lambda-main" in row["agents"], (st, row["main"]))
check("main_of: the page's front -main beats a page_owed one whatever the order; a pending one is main only when the page has none; background and non-main never",
      prj.main_of({"a-main": {"front": True, "page_owed": True}, "z-main": {"front": True}}) == "z-main" and prj.main_of({"a-main": {"front": True, "page_owed": True}}) == "a-main"
      and prj.main_of({"a-main": {"front": True, "page_owed": True}, "b-main": {"front": True, "page_owed": True}}) == "a-main"
      and prj.main_of({"a-main": {"front": False}, "b-x": {"front": True}}) == "" and prj.main_of({}) == "")
st, out = fpa("box-c", "projects/lambda", "home-lambda-body", "fleet-web")
st2, out2 = server._client_post("box-c", "project-agent", {"project": "projects/lambda", "name": "home-lambda-body", "role": "helper", "front": False, "mandate": "m", "sender": "fleet-web", "machine": "box-a"})
check("form call: a body that carries a machine field makes no form call (the token's machine decides): 403, nothing recorded", st2 == 403 and "home-lambda-body" not in lam_pending(), (st2, out2))
PJ1 = (T / "state/projects.json").read_bytes()
fpa("box-a", "projects/delta", "home-delta-helper", "fleet-web"); fpa("box-a", "projects/lambda", "home-lambda-docs-main", "fleet-web"); fpa("box-a", "projects/lambda", "home-lambda-SEED", "fleet-web", role="seed", mandate="other")
fpa("box-c", "projects/lambda", "home-lambda-body", "fleet-web"); fpa("box-a", "projects/lambda", "home-lambda-body", "nobody")
check("form call: refused form calls (hidden, name owned by another project, 409 on another sender's pending, wrong machine, wrong label) leave the published projects.json byte for byte as it was",
      (T / "state/projects.json").read_bytes() == PJ1)
# the config: absent section → the defaults; a changed section → the file's lists; a malformed value → nobody
server._cfg.CFG["project_agent"] = "x"
check("form call: a section that is not a table (project_agent = \"x\") switches form calls off, it does not fall back to the defaults", fpa("box-a", "projects/lambda", "home-lambda-notable", "fleet-web")[0] == 403 and "home-lambda-notable" not in lam_pending()
      and server._form_call("box-a", "fleet-web") is False)
server._cfg.CFG["project_agent"] = ["fleet-web"]
check("form call: …a list as the section too", server._form_call("box-a", "fleet-web") is False)
server._cfg.CFG["project_agent"] = {"form_machines": ["box-a"]}
check("form call: a table that sets one key keeps the other's default (no sender label: no form call)", server._form_call("box-a", "fleet-web") is False and server._form_call("box-c", "fleet-web") is False)
server._cfg.CFG["project_agent"] = {"form_senders": ["fleet-web"]}
check("form call: …and the senders alone keep the default machines (none since the code names no machine), so the form calls nobody", server._form_call("box-a", "fleet-web") is False and server._form_call("box-c", "fleet-web") is False)
server._cfg.CFG.pop("project_agent", None)
st, out = fpa("box-a", "projects/lambda", "home-lambda-nocfg", "fleet-web")
check("form call: with the config section absent the defaults apply (no sender label: fleet-web on box-a → 403), and the defaults refuse anyone else too", st == 403 and "home-lambda-nocfg" not in lam_pending()
      and fpa("box-c", "projects/lambda", "home-lambda-nocfg2", "fleet-web")[0] == 403 and fpa("box-a", "projects/lambda", "home-lambda-nocfg2", "other-form")[0] == 403, (st, out))
server._cfg.CFG["project_agent"] = {"form_senders": ["other-form"], "form_machines": ["box-c", "box-e"]}
check("form call: the section as the file sets it: its senders on its machines (200); the default sender/machine pair no longer is (403)",
      fpa("box-e", "projects/lambda", "home-lambda-cfg1", "other-form")[0] == 200 and fpa("box-c", "projects/lambda", "home-lambda-cfg2", "other-form")[0] == 200
      and fpa("box-a", "projects/lambda", "home-lambda-cfg3", "fleet-web")[0] == 403 and fpa("box-a", "projects/lambda", "home-lambda-cfg3", "other-form")[0] == 403
      and fpa("box-c", "projects/lambda", "home-lambda-cfg3", "fleet-web")[0] == 403, lam_pending())
server._cfg.CFG["project_agent"] = {"form_senders": "fleet-web", "form_machines": "box-a"}
check("form call: a bare string in the file counts as one name", fpa("box-a", "projects/lambda", "home-lambda-str", "fleet-web")[0] == 200)
server._cfg.CFG["project_agent"] = {"form_senders": 5, "form_machines": {"box-a": 1}}
check("form call: a value of the wrong type means nobody (never a wider rule than the file says)", fpa("box-a", "projects/lambda", "home-lambda-bad", "fleet-web")[0] == 403 and "home-lambda-bad" not in lam_pending())
server._cfg.CFG["project_agent"] = {"form_senders": [], "form_machines": ["box-a"]}
check("form call: an empty list switches the form call off", fpa("box-a", "projects/lambda", "home-lambda-off", "fleet-web")[0] == 403 and "home-lambda-off" not in lam_pending())
server._cfg.CFG["project_agent"] = {"form_senders": ["fleet-web"], "form_machines": ["box-a"]}   # back to the instance's own config, which the rest of the test runs on
check("form call: the old rules are unchanged beside it: a keeper's or front agent's own session id still works on a listed project with agents, a stranger's still 403",
      pa("projects/alpha", "home-sparrow-formcheck", U["home-sparrow-main"], role="formcheck")[0] == 200 and pa("projects/alpha", "home-sparrow-formcheck2", U["home-outsider"], role="formcheck2")[0] == 403, None)
with prj._Locked(): d_ = prj._read(); d_["pending_agents"].pop(L, None); d_["pending_agents"].pop(MU, None); d_["pending_agents"].pop(rec("projects/lambda-docs")["id"], None); d_["pending_agents"].get(A, {}).pop("home-sparrow-formcheck", None); prj._write(d_)   # leave the later sections their fixtures
for f_ in ("lambda", "lambda-docs", "mu", "alpha-docs"): (T / f"brain/projects/{f_}.md").unlink()
p.cmd_registry(quiet=True)

# ---- 6b. page_yaml: the mandate quoted so that it loads back as the same string, and only the owed entries, with or without the page's map
import yaml
MANDATES = (["yes", "no", "true", "false", "on", "off", "y", "n", "null", "~"] + [w.upper() for w in ("yes", "no", "true", "false", "on", "off", "y", "n", "null")]
            + ["Yes", "No", "True", "False", "On", "Off", "Y", "N", "Null", "nULL"]
            + ["123", "0", "007", "017", "-5", "+7", "1_000", "1,000", "3.14", "1.", "1e3", "1.5E+3", "0x1F", "0X1f", "0o17", "0b101", "12"]
            + ["2026-03-13", "2026-1-5", "2026-03-13 10:00:00", "2026-03-13T10:00:00Z", "2026-03-13T10:00:00.5+04:00", "2026-03-13 notes"]
            + ["", "talks to Oliver", "keeps the docs", "b: with a colon", "- a dash", "? maybe", "a # b", 'say "hi"', "it's", "back\\slash", "日本語 mandate", "yes please", "2026 plan",
               "on call", "null pointer", "no", "  spaced   out  ", "[a, b]", "{a: b}", "!tag", "&anchor", "*alias", "@at", "`tick`", "%percent", "=", "<<", "a: b: c", "1 2 3"])
bad_rt = []
for m_ in MANDATES:
    want = " ".join(m_.split())          # a mandate is one line: runs of white space are one space
    try: got = yaml.safe_load("k: " + prj._yaml_scalar(m_))["k"]
    except Exception as e_: got = f"{type(e_).__name__}: {e_}"
    if got != want or not isinstance(got, str): bad_rt.append((m_, prj._yaml_scalar(m_), got))
check(f"yaml scalar: {len(MANDATES)} mandates (bool/null words in any case, integers, floats, hex/octal/binary, dates and timestamps, and the odd ones) each load back through PyYAML as the same string", not bad_rt, bad_rt)
check("yaml scalar: …a plain mandate stays plain, one YAML would misread is double-quoted", prj._yaml_scalar("talks to Oliver") == "talks to Oliver" and prj._yaml_scalar("yes please") == "yes please"
      and prj._yaml_scalar("yes") == '"yes"' and prj._yaml_scalar("Off") == '"Off"' and prj._yaml_scalar("~") == '"~"' and prj._yaml_scalar("1e3") == '"1e3"' and prj._yaml_scalar("0x1F") == '"0x1F"'
      and prj._yaml_scalar("2026-03-13") == '"2026-03-13"' and prj._yaml_scalar("2026 plan") == "2026 plan" and prj._yaml_scalar("") == '""')
ag_ = {"home-x-main": {"front": True, "page_owed": True, "mandate_line": "yes"}, "home-x-bg": {"front": False, "page_owed": True, "mandate_line": "2026-03-13"},
       "home-x-on-page": {"front": True, "mandate_line": "already listed"}}
check("agents_yaml: the whole block (with the header) round-trips through PyYAML, background entries under background:, an agent already on the page left out",
      yaml.safe_load(prj.agents_yaml(ag_)) == {"agents": {"home-x-main": "yes", "background": {"home-x-bg": "2026-03-13"}}} and prj.agents_yaml(ag_).startswith("agents:\n"), prj.agents_yaml(ag_))
check("agents_yaml: has_map → the entries only, no header, indented to go under the page's map; pasted under an existing map it round-trips and keeps the page's own entries",
      prj.agents_yaml(ag_, has_map=True) == '  home-x-main: "yes"\n  background:\n    home-x-bg: "2026-03-13"\n'
      and yaml.safe_load("agents:\n  home-x-page: m\n" + prj.agents_yaml(ag_, has_map=True)) == {"agents": {"home-x-page": "m", "home-x-main": "yes", "background": {"home-x-bg": "2026-03-13"}}}
      and prj.agents_yaml({"a": {"front": True, "mandate_line": "m"}}, has_map=True) == "" and prj.agents_yaml({}) == "", prj.agents_yaml(ag_, has_map=True))
# the page's agents block is written from the record: a mandate YAML would misread is quoted there, and loads back as the same string
st, out = pa(NEW, "work-new-one-yes", "fleet-web", role="yes", front=True, mandate="yes")
st2, out2 = pa(NEW, "work-new-one-bg", "fleet-web", role="bg", front=False, mandate="2026-03-13")
st3, out3 = pa(NEW, "work-new-one-on", "fleet-web", role="on", front=False, mandate="on")
pg_ = page_agents("projects/new-one")
check("project-agent: the mirror quotes what YAML would misread (yes, a date, on): the page loads back the same strings, background ones under background:, and the reply owes nothing",
      st == 200 and st2 == 200 and st3 == 200 and out["page_yaml"] == "" and pg_[0].get("work-new-one-yes") == "yes" and pg_[0].get("work-new-one-bg") == "2026-03-13" and pg_[0].get("work-new-one-on") == "on"
      and pg_[1] == {"work-new-one-second": "b: with a colon", "work-new-one-bg": "2026-03-13", "work-new-one-on": "on"}, (st, st2, st3, pg_))
st, out = pa(NEW, "work-new-one-yes", "fleet-web", role="yes", front=True, mandate="yes")
check("project-agent: …said again as it stands, nothing changes (200, \"already listed\"), and the page is as it was", st == 200 and "already listed" in out["note"] and page_agents("projects/new-one") == pg_, (st, out))
# a mandate with a control character is refused (400) beside the newline check, nothing recorded
bad_ctl = []
for i_, ch_ in enumerate(("\x00", "\x07", "\t", "\x1b", "\x1f", "\x7f", "\x80", "\x85", "\x9f", "￾", "￿")):
    st, out = pa("projects/alpha", f"home-sparrow-ctl{i_}", U["home-sparrow-main"], role=f"ctl{i_}", mandate=f"a{ch_}b")
    if not (st == 400 and "control characters" in out["error"] and f"home-sparrow-ctl{i_}" not in rec("projects/alpha")["agents"]): bad_ctl.append((hex(ord(ch_)), st, out))
check("project-agent: a mandate with a control character (U+0000-U+001F, U+007F-U+009F, U+FFFE, U+FFFF; 11 samples) is a 400 and nothing is recorded", not bad_ctl, bad_ctl)
st, out = pa("projects/alpha", "home-sparrow-ja", U["home-sparrow-main"], role="ja", mandate="日本語 mandate, café ünï")
check("project-agent: …while non-ASCII text above U+009F is fine (200), and so is the edge just outside the ranges (U+00A0, U+0020)", st == 200
      and pa("projects/alpha", "home-sparrow-edge", U["home-sparrow-main"], role="edge", mandate="a b c")[0] == 200, (st, out))
# a page whose agents map already has a background: sub-map: no second background: header, the note says where the entries go
def merge_into(page_yaml, page_text):
    """What the person does with page_yaml: the 2-space entries go under agents:, the 4-space ones under the page's one background:."""
    lines = page_yaml.splitlines(); front_l = [l for l in lines if l.startswith("  ") and not l.startswith("    ")]; back_l = [l for l in lines if l.startswith("    ")]
    head, _, tail = page_text.partition("  background:\n")
    return head + "".join(l + "\n" for l in front_l) + "  background:\n" + tail + "".join(l + "\n" for l in back_l)
PG = "agents:\n  home-page-main: m\n  background:\n    home-page-old: o\n"
ag2 = {"home-x-main": {"front": True, "page_owed": True, "mandate_line": "yes"}, "home-x-bg": {"front": False, "page_owed": True, "mandate_line": "2026-03-13"}}
y_ = prj.agents_yaml(ag2, has_map=True, has_back=True)
check("agents_yaml: has_map and has_back → no `background:` header, the background entries at four spaces; merged into the page's YAML (front under agents:, background under its one background:) it round-trips and keeps the page's own background agent",
      "background" not in y_ and y_ == '  home-x-main: "yes"\n    home-x-bg: "2026-03-13"\n' and merge_into(y_, PG).count("background:") == 1
      and yaml.safe_load(merge_into(y_, PG)) == {"agents": {"home-page-main": "m", "home-x-main": "yes", "background": {"home-page-old": "o", "home-x-bg": "2026-03-13"}}}, (y_, merge_into(y_, PG)))
check("agents_yaml: …a background entry alone is the four-space line only; has_back without any owed agent is empty; without has_back the header is still written",
      prj.agents_yaml({"home-x-bg": ag2["home-x-bg"]}, has_map=True, has_back=True) == '    home-x-bg: "2026-03-13"\n' and prj.agents_yaml({}, has_map=True, has_back=True) == ""
      and prj.agents_yaml(ag2, has_map=True) == '  home-x-main: "yes"\n  background:\n    home-x-bg: "2026-03-13"\n')

# ---- 6c. a slow gbrain write holds nobody else up, and a make of the same key cannot overlap (the record is written first, under the lock; the page after it, outside)
import threading
class BlockIO(FakeIO):
    """A fake gbrain whose create blocks (on an Event) for the slugs in `block`."""
    def __init__(s, block): super().__init__(); s.block = set(block); s.started = []; s.entered = threading.Event(); s.gate = threading.Event()
    def create(s, slug, content):
        s.started.append(slug)
        if slug in s.block: s.entered.set(); s.gate.wait(30)
        return super().create(slug, content)
def in_thread(fn, *a, **k):
    box = {}
    def run():
        t0 = time.time()
        try: box["r"] = fn(*a, **k)
        except BaseException as e_: box["exc"] = e_
        box["took"] = time.time() - t0
    t = threading.Thread(target=run, daemon=True); t.start(); return t, box
blk = BlockIO({"projects/slow-one"}); server._pform.PAGE_IO = blk
t1, b1 = in_thread(mk, "projects/slow-one", "home", "Slow one", "fleet-web")
try:
    entered = blk.entered.wait(10)
    check("slow gbrain: the first make is inside gbrain's create (the Event is held)", entered and t1.is_alive() and blk.started == ["projects/slow-one"], blk.started)
    check("slow gbrain: the project is in the record already (the record comes first) and the lock itself is free", rec("projects/slow-one") is not None and not server._PROJECT_LOCK.locked(), server._PROJECT_LOCK.locked())
    t2, b2 = in_thread(pa, "projects/alpha", "home-sparrow-quick", U["home-sparrow-main"], role="quick", mandate="quick one"); t2.join(5)
    check("slow gbrain: a project-agent call on another project completes at once while the make waits on gbrain (200, well under the clients' 30 s)", not t2.is_alive() and b2["r"][0] == 200 and b2["took"] < 3 and t1.is_alive(), (b2, t1.is_alive()))
    t3, b3 = in_thread(relist, "projects/eta", sender="fleet-web"); t3.join(5)
    check("slow gbrain: …and so does a project-list", not t3.is_alive() and b3["r"][0] == 200 and b3["took"] < 3 and t1.is_alive(), (b3, t1.is_alive()))
    t4, b4 = in_thread(mk, "projects/slow-two", "home", "Slow two", "fleet-web"); t4.join(5)
    check("slow gbrain: …and a make of a different key (its gbrain is not slow) finishes 200 meanwhile", not t4.is_alive() and b4["r"][0] == 200 and b4["took"] < 3 and t1.is_alive(), (b4, t1.is_alive()))
    t5, b5 = in_thread(mk, "projects/slow-one", "home", "Slow one again", "other-label"); t5.join(5)
    check("slow gbrain: a second make of the same key during the first → 409, at once, and no second gbrain write",
          not t5.is_alive() and b5["r"][0] == 409 and b5["took"] < 3 and blk.started.count("projects/slow-one") == 1, (b5, blk.started))
finally:
    blk.gate.set()
t1.join(10)
check("slow gbrain: once gbrain answers the first make completes 200, the project is recorded and listed",
      not t1.is_alive() and b1["r"][0] == 200 and b1["r"][1]["project"]["key"] == "projects/slow-one" and rec("projects/slow-one") is not None and "projects/slow-one" in keys("home"),
      b1)
st, out = mk("projects/slow-one", "home", "Slow one third")
check("slow gbrain: …and a later make of the key is the ordinary 409 'already exists' (post project-list)", st == 409 and "already exists" in out["error"], (st, out))
class RaisingIO(FakeIO):
    def create(s, slug, content): raise RuntimeError("gbrain exploded")
server._pform.PAGE_IO = RaisingIO()
st, out = mk("projects/boom", "home", "Boom")
check("slow gbrain: a gbrain call that raises is a 502 (the mirror never raises), and nothing is recorded", st == 502 and rec("projects/boom") is None and "projects/boom" not in idfile()["ids"].values(), (st, out))
server._pform.PAGE_IO = gio
st, out = mk("projects/boom", "home", "Boom")
check("slow gbrain: …and the same make said again goes through (the failed one left nothing behind)", st == 200 and rec("projects/boom") is not None, (st, out))
server._pform.PAGE_IO = gio

# ---- 6d. post project-agent-rename: the agent renamed in the project record (its place and mandate kept), the page's agents block written from the record
class RenameIO:
    """A fake gbrain with revisions: get(slug) -> (content, "r<n>"), put(slug, content, rev) -> (state, note). `mode` sets what a put does."""
    def __init__(s): s.pages = {}; s.revs = {}; s.gets = []; s.puts = []; s.mode = "ok"; s.get_none = False; s.hook = None; s.timeline = []; s.tl_fail = ""
    def add_timeline(s, slug, date, summary, detail, source, request_id=""):         # the page store's timeline write: "" when added, else why not
        if s.tl_fail: return s.tl_fail
        s.timeline.append((slug, date, summary, detail, source, request_id)); return ""
    def seed(s, slug, content): s.pages[slug] = content; s.revs[slug] = 1
    def get(s, slug):
        s.gets.append(slug)
        if s.get_none or slug not in s.pages: return None, None
        return s.pages[slug], f"r{s.revs[slug]}"
    def put(s, slug, content, rev):
        s.puts.append((slug, rev))
        if s.hook: s.hook(slug)
        if rev != f"r{s.revs[slug]}": return "refused", '{"error":"stale revision"}'
        if s.mode == "refused": return "refused", "gbrain said no"
        if s.mode == "lost": return "unknown", "the put timed out"                  # never landed
        if s.mode == "ghost": return "ok", "{}"                                      # said ok, wrote nothing
        s.pages[slug] = content; s.revs[slug] += 1
        return ("unknown", "the put timed out after the write") if s.mode == "landed" else ("ok", "{}")
rio = RenameIO()
def ren_page(rel, front):
    page(rel + ".md", front); rio.seed(rel, (T / "brain" / (rel + ".md")).read_text(encoding="utf-8"))
REN_FRONT = ('type: project\ntitle: Ren\norg: home\ndisplay-name: home-ren\nagents:\n  home-ren-main: talks to Oliver\n  home-ren-engineer: builds it\n  background:\n'
             '    home-ren-curator: "keeps the pages: all of them"\n    home-ren-watch: watches\nstatus: active')
ren_page("projects/ren", REN_FRONT)
ren_page("projects/ren-inl", 'type: project\ntitle: Ren inline\norg: home\ndisplay-name: home-ren-inl\nagents: {home-ren-inl-main: "talks", background: {home-ren-inl-bg: "in the back"}}\nstatus: active')
ren_page("projects/ren-quo", "type: project\ntitle: Ren quoted\norg: home\ndisplay-name: home-ren-quo\nagents:\n  \"home-ren-quo-main\": talks\n  'home-ren-quo-eng': builds\nstatus: active")
ren_page("projects/ren-cli", REN_FRONT.replace("home-ren", "home-rcli").replace("Ren", "Rcli"))
ren_page("projects/ren-http", REN_FRONT.replace("home-ren", "home-rhttp").replace("Ren", "Rhttp"))
p.cmd_registry(quiet=True); fresh()
server._pform.PAGE_IO = rio
server._cfg.CFG["project_agent"] = {"form_senders": ["fleet-web"], "form_machines": ["box-a"]}
def rn(project, old, new, sender="fleet-web", machine="box-a", **kw):
    b = {"project": project, "old": old, "new": new, **kw}
    if sender is not None: b["sender"] = sender
    return server._client_post(machine, "project-agent-rename", b)
def agents_of(slug):
    f, b = p.split_agents(p.frontmatter_text(rio.pages[slug]).get("agents")); return list(f.items()), list(b.items())
def rec_agents(pid): return [(n, a["mandate_line"]) for n, a in (pverbs.pr.entries().get(pid, {}).get("agents") or {}).items()]
REN = rec("projects/ren")["id"]
text0 = rio.pages["projects/ren"]; ag0, bg0 = agents_of("projects/ren")
check("rename: (setup) the page has two front agents and two background ones, read the way the registry reads it", [n for n, _ in ag0] == ["home-ren-main", "home-ren-engineer", "home-ren-curator", "home-ren-watch"] and [n for n, _ in bg0] == ["home-ren-curator", "home-ren-watch"], (ag0, bg0))

# the happy paths: a front entry, then a background one
st, out = rn("projects/ren", "home-ren-engineer", "home-ren-builder")
ag1, bg1 = agents_of("projects/ren")
check("rename: a front entry → 200 'renamed', the reply names the old and new name, front true, and the mandate it kept", st == 200 and out["result"] == "renamed" and out["old"] == "home-ren-engineer" and out["new"] == "home-ren-builder"
      and out["front"] is True and out["role"] == "builder" and out["mandate"] == "builds it" and out["key"] == "projects/ren" and out["project"] == REN, (st, out))
check("rename: …the record is renamed in place (same place in the map, same mandate) and the page's block was written from it (one put, at the revision read)",
      rec_agents(REN) == [(("home-ren-builder" if n == "home-ren-engineer" else n), m) for n, m in ag0] and out["mirror"]["state"] == "written" and rio.puts == [("projects/ren", "r1")]
      and ag1 == [(("home-ren-builder" if n == "home-ren-engineer" else n), m) for n, m in ag0] and bg1 == bg0, (rec_agents(REN), out["mirror"], rio.puts, ag1, bg1))
st, out = rn("projects/ren", "home-ren-watch", "home-ren-watcher")
ag2, bg2 = agents_of("projects/ren")
check("rename: a background entry → 200 'renamed', front false, and it stays under background: with the others (the quoted mandate with a colon intact)", st == 200 and out["result"] == "renamed" and out["front"] is False and out["mandate"] == "watches"
      and [n for n, _ in bg2] == ["home-ren-curator", "home-ren-watcher"] and dict(bg2)["home-ren-curator"] == "keeps the pages: all of them"
      and [n for n, _ in ag2] == ["home-ren-main", "home-ren-builder", "home-ren-curator", "home-ren-watcher"], (st, out, ag2, bg2))
st, out = rn("projects/ren", "HOME-REN-MAIN", "home-ren-lead")
check("rename: OLD is matched case-folded, and the record's own spelling is renamed", st == 200 and out["old"] == "home-ren-main" and agents_of("projects/ren")[0][0] == ("home-ren-lead", "talks to Oliver"), (st, out))
check("rename: the project may be named by its id, its page key or its bare slug", rn(REN, "home-ren-lead", "home-ren-boss")[0] == 200 and rn("ren", "home-ren-boss", "home-ren-main")[0] == 200 and agents_of("projects/ren")[0][0][0] == "home-ren-main")
text3 = rio.pages["projects/ren"]; rec3 = rec_agents(REN); nputs = len(rio.puts)

# refusals: each changes nothing
def nothing_changed(label): return rio.pages["projects/ren"] == text3 and rec_agents(REN) == rec3 and len(rio.puts) == nputs
st, out = rn("projects/ren", "home-ren-main", "home-ren-builder")
check("rename: NEW already listed and OLD still listed → 409 'already listed', nothing changed", st == 409 and "home-ren-builder is already listed" in out["error"] and nothing_changed("409"), (st, out))
st, out = rn("projects/ren", "home-ren-main", "home-ren-BUILDER")
check("rename: …NEW is matched case-folded too", st == 409 and "already listed" in out["error"] and nothing_changed("409 case"), (st, out))
st, out = rn("projects/ren", "home-ren-ghost", "home-ren-newbie")
check("rename: OLD not listed (and NEW not either) → 404 '<OLD> is not listed', nothing changed", st == 404 and "home-ren-ghost is not listed" in out["error"] and nothing_changed("404"), (st, out))
st, out = rn("projects/ren", "home-ren-engineer", "home-ren-builder")
check("rename: the retry after a lost reply (OLD gone, NEW listed) → 200 'already renamed', front/back reported, nothing written", st == 200 and out["result"] == "already renamed" and out["note"] == "already renamed" and out["new"] == "home-ren-builder"
      and out["front"] is True and out["role"] == "builder" and out["mandate"] == "builds it" and nothing_changed("retry"), (st, out))
st, out = rn("projects/ren", "home-ren-watch", "home-ren-watcher")
check("rename: …a background entry's retry is the same 200, front false", st == 200 and out["result"] == "already renamed" and out["front"] is False and out["role"] == "watcher" and out["mandate"] == "watches" and nothing_changed("retry bg"), (st, out))
# who may call
gets_before = len(rio.gets)
bad = [rn("projects/ren", "home-ren-main", "home-ren-chief", sender="other-label"), rn("projects/ren", "home-ren-main", "home-ren-chief", sender=None),
       rn("projects/ren", "home-ren-main", "home-ren-chief", sender="box-a"), rn("projects/ren", "home-ren-main", "home-ren-chief", sender=U["home-sparrow-main"]), rn("projects/ren", "home-ren-main", "home-ren-chief", sender="")]
check("rename: a sender that is no form label (a stranger's label, none, the machine's name, a session id, empty) → 403, the same text each time, before the page is read", all(s == 403 and o == {"error": server._RENAME_NOT_FORM} for s, o in bad)
      and len(rio.gets) == gets_before and nothing_changed("not form"), bad)
bad = [rn("projects/ren", "home-ren-main", "home-ren-chief", machine=m) for m in ("box-c", "box-e", "")]
check("rename: the form's label from a machine that is not in form_machines (or with no machine proven) → 403, nothing changed", all(s == 403 and o == {"error": server._RENAME_NOT_FORM} for s, o in bad)
      and len(rio.gets) == gets_before and nothing_changed("wrong machine"), bad)
server._cfg.CFG["project_agent"] = {"form_senders": [], "form_machines": ["box-a"]}
check("rename: with no form label in the config (the defaults) nobody may, the form's label included", rn("projects/ren", "home-ren-main", "home-ren-chief")[0] == 403 and nothing_changed("no labels"))
server._cfg.CFG["project_agent"] = {"form_senders": ["fleet-web"], "form_machines": ["box-a"]}
# bad names, unknown project, other kinds of page
cases = [("a bad new name", rn("projects/ren", "home-ren-main", "home ren chief")), ("a bad old name", rn("projects/ren", "home ren main", "home-ren-chief")), ("a 65-character name", rn("projects/ren", "home-ren-main", "home-ren-" + "x" * 58)),
         ("a name not starting with the project's", rn("projects/ren", "home-ren-main", "home-other-chief")), ("the bare prefix", rn("projects/ren", "home-ren-main", "home-ren-")),
         ("the same name", rn("projects/ren", "home-ren-main", "home-ren-main")), ("the same name in other case", rn("projects/ren", "home-ren-main", "HOME-REN-MAIN")),
         ("no project", rn("", "home-ren-main", "home-ren-chief")), ("no old", rn("projects/ren", "", "home-ren-chief")), ("a sender of 81 characters", rn("projects/ren", "home-ren-main", "home-ren-chief", sender="x" * 81)),
         ("a hub: page", rn("projects/theta", "home-theta-main", "home-theta-chief")), ("a sub-page", rn("projects/alpha/sub", "home-sparrow-sub-main", "home-sparrow-sub-chief"))]
check("rename: bad names, a missing field, the bare prefix, OLD = NEW, a long sender and a hub: or sub-page are 400s, nothing changed", all(s == 400 for _, (s, o) in cases) and nothing_changed("400"), [(n, s, o) for n, (s, o) in cases if s != 400])
check("rename: …the 400 for a page with a hub: line names the hub page", "projects/epsilon" in dict(cases)["a hub: page"][1]["error"], dict(cases)["a hub: page"])
st, out = rn("projects/nope", "home-nope-main", "home-nope-chief"); st2, out2 = rn("prj_00000000", "home-nope-main", "home-nope-chief")
check("rename: an unknown project is a 404 as project-agent says it (and not the 'not listed' text)", st == st2 == 404 and out["error"].startswith("no project 'projects/nope'") and out2["error"].startswith("no project 'prj_00000000'") and nothing_changed("unknown"), (out, out2))
# a name that belongs to another project
pverbs.agent_add("projects/lambda", "home-ren-stolen", True, "m", by="fleet-web", io=gio)
st, out = rn("projects/ren", "home-ren-main", "home-ren-stolen")
check("rename: a NEW that another project's record lists → 409 'a name belongs to one project' (as project-agent), nothing changed", st == 409 and "one project" in out["error"] and nothing_changed("stolen"), (st, out))
pverbs.agent_retire("projects/lambda", "home-ren-stolen", by="fleet-web", io=gio)
st, out = rn("projects/ren", "home-ren-main", "home-lambda-main")
check("rename: …and a name that starts with another project's name is the 400 (it must start with this project's)", st == 400, (st, out))
# page shapes: the block is written from the record, whatever shape the page had
ti = rio.pages["projects/ren-inl"]
st, out = rn("projects/ren-inl", "home-ren-inl-bg", "home-ren-inl-back"); st2, out2 = rn("projects/ren-inl", "home-ren-inl-main", "home-ren-inl-lead")
check("rename: a page with an inline agents: {…} map (also an inline background: {…}) is rewritten from the record: the same agents, the renamed ones, order and values kept", st == st2 == 200 and out["front"] is False and out2["front"] is True
      and agents_of("projects/ren-inl") == ([("home-ren-inl-lead", "talks"), ("home-ren-inl-back", "in the back")], [("home-ren-inl-back", "in the back")]), (st, out, st2, out2, rio.pages["projects/ren-inl"]))
st, out = rn("projects/ren-quo", "home-ren-quo-main", "home-ren-quo-lead"); st2, out2 = rn("projects/ren-quo", "home-ren-quo-eng", "home-ren-quo-builder")
check("rename: a page whose keys were written in quotes is rewritten the same way", st == st2 == 200 and agents_of("projects/ren-quo") == ([("home-ren-quo-lead", "talks"), ("home-ren-quo-builder", "builds")], []), (st, st2, rio.pages["projects/ren-quo"]))
# pages.rename_agent on its own: refusals
check("pages.rename_agent: a page with no frontmatter, no agents map, or an unclosed frontmatter is refused, not guessed at", p.rename_agent("# x\n", "a", "b")[0] is None and p.rename_agent("---\ntitle: x\n---\n", "a", "b")[0] is None
      and p.rename_agent("---\nagents:\n  a: x\n", "a", "b")[0] is None)
check("pages.rename_agent: a name that is only in a mandate text, or not in the map, is not renamed", p.rename_agent("---\nagents:\n  a: see b: c\n---\n", "b", "d")[0] is None and p.rename_agent("---\nagents:\n  a: x\nowner: b\n---\n", "b", "d")[0] is None)
check("pages.rename_agent: a longer name that starts with OLD is not touched (home-x-eng vs home-x-engineer)", p.rename_agent("---\nagents:\n  home-x-engineer: a\n  home-x-eng: b\n---\nbody home-x-eng: c\n", "home-x-eng", "home-x-dev")[0]
      == "---\nagents:\n  home-x-engineer: a\n  home-x-dev: b\n---\nbody home-x-eng: c\n")
# gbrain trouble: the record is right whatever the page store says; the mirror says what it could not do, and the next mirror writes the page
def heal():
    rio.mode = "ok"; rio.hook = None; rio.get_none = False; r_ = pverbs.mirror(REN, rio); return r_
tr = rio.pages["projects/ren"]; nputs_tr = len(rio.puts)
rio.get_none = True; st, out = rn("projects/ren", "home-ren-main", "home-ren-m1"); rio.get_none = False
check("rename: a page the page store does not give → 200, the record renamed, the mirror 'no-page' (told in the note), the page untouched, nothing written", st == 200 and out["mirror"]["state"] == "no-page" and "not in the page store" in out["note"]
      and rio.pages["projects/ren"] == tr and len(rio.puts) == nputs_tr and rec_agents(REN)[0][0] == "home-ren-m1", (st, out))
check("rename: …and the next mirror writes the page from the record", heal()["state"] == "written" and agents_of("projects/ren")[0][0][0] == "home-ren-m1")
for i_, mode in enumerate(("refused", "lost", "ghost")):
    rio.mode = mode; st, out = rn("projects/ren", f"home-ren-m{i_ + 1}", f"home-ren-m{i_ + 2}"); rio.mode = "ok"
    check(f"rename: a put that is {mode} → 200, the record renamed, the mirror not 'written', the page unchanged", st == 200 and out["mirror"]["state"] != "written" and rec_agents(REN)[0][0] == f"home-ren-m{i_ + 2}"
          and agents_of("projects/ren")[0][0][0] == f"home-ren-m{i_ + 1}", (st, out["mirror"], agents_of("projects/ren")[0][:1]))
    heal()
check("rename: …each healed by the next mirror: the page equals the record", agents_of("projects/ren")[0] == rec_agents(REN) and rec_agents(REN)[0][0] == "home-ren-m4", (agents_of("projects/ren")[0], rec_agents(REN)))
rio.mode = "landed"; st, out = rn("projects/ren", "home-ren-m4", "home-ren-m5"); rio.mode = "ok"
check("rename: a put that times out after it wrote is taken as written when the read back shows it", st == 200 and out["mirror"]["state"] in ("written", "unchanged") and agents_of("projects/ren")[0][0][0] == "home-ren-m5", (st, out["mirror"]))
once_ = []
def one_shot_writer(slug):         # the page changes between the read and the put, once
    if not once_: once_.append(1); rio.pages[slug] = rio.pages[slug] + "\n- a line another session added\n"; rio.revs[slug] += 1
rio.hook = one_shot_writer
st, out = rn("projects/ren", "home-ren-m5", "home-ren-main"); rio.hook = None
check("rename: a page that changed between the read and the put (a stale revision) → the mirror reads it again and tries once more: 200, written, the other writer's change kept, the rename on the page",
      st == 200 and out["mirror"]["state"] == "written" and rio.pages["projects/ren"].endswith("- a line another session added\n") and agents_of("projects/ren")[0][0][0] == "home-ren-main", (st, out["mirror"]))

# concurrency: the record under the project lock, the page after it; the page key in flight while the page store works
entered, gate = threading.Event(), threading.Event(); first = []; seen_in_put = []
def hold(slug):
    seen_in_put.append((slug, server._PROJECT_LOCK.locked(), set(server._RENAMING)))
    if not first: first.append(1); entered.set(); gate.wait(30)
rio.hook = hold
tA, bA = in_thread(rn, "projects/ren", "home-ren-main", "home-ren-alpha")
try:
    ok1 = entered.wait(10)
    check("rename concurrency: while the first rename is inside the page store's put the page key is in flight and the project lock is free", ok1 and tA.is_alive() and seen_in_put == [("projects/ren", False, {"projects/ren"})] and not server._PROJECT_LOCK.locked(), (ok1, seen_in_put))
    tB, bB = in_thread(rn, "projects/ren", "home-ren-alpha", "home-ren-beta"); tB.join(5)
    check("rename concurrency: a second rename of the same page → 409 'a rename of <page> is in progress; try again' at once, and nothing of it is written",
          not tB.is_alive() and bB["r"] == (409, {"error": "a rename of projects/ren is in progress; try again"}) and bB["took"] < 3 and tA.is_alive() and len(seen_in_put) == 1, (bB, seen_in_put))
    tD, bD = in_thread(fpa, "box-a", "projects/ren", "home-ren-quick", "fleet-web"); tD.join(5)
    tE, bE = in_thread(relist, "projects/ren", sender="fleet-web"); tE.join(5)
    check("rename concurrency: a project-agent call and a project-list call on that project, made while the rename sits inside the put, return at once (200, well under the clients' 30 s)",
          not tD.is_alive() and not tE.is_alive() and bD["r"][0] == 200 and bE["r"][0] == 200 and bD["took"] < 3 and bE["took"] < 3 and tA.is_alive(), (bD, bE))
    tF, bF = in_thread(rn, "projects/ren-quo", "home-ren-quo-lead", "home-ren-quo-head"); tF.join(5)
    check("rename concurrency: a rename on another page is not held up by it (200)", not tF.is_alive() and bF["r"][0] == 200 and tA.is_alive(), bF)
finally:
    gate.set()
tA.join(15)
check("rename concurrency: the first one then completes 200 renamed, the key leaves the in-flight set, and the page holds the rename AND the agent added meanwhile (the mirror is recomputed from the record when its put is refused)",
      not tA.is_alive() and bA["r"][0] == 200 and bA["r"][1]["result"] == "renamed" and server._RENAMING == set()
      and "home-ren-alpha" in dict(agents_of("projects/ren")[0]) and "home-ren-quick" in dict(agents_of("projects/ren")[0]) and agents_of("projects/ren")[0][:1] == rec_agents(REN)[:1], (bA, server._RENAMING, agents_of("projects/ren")[0]))
st, out = rn("projects/ren", "home-ren-main", "home-ren-alpha")
check("rename concurrency: …and the retry of the refused one is the ordinary 200 'already renamed'", st == 200 and out["result"] == "already renamed", (st, out))
pverbs.agent_retire(REN, "home-ren-quick", by="fleet-web", io=rio)
class RaisingGet(RenameIO):
    def get(s, slug): raise RuntimeError("gbrain exploded")
server._pform.PAGE_IO = RaisingGet()
st, out = rn("projects/ren", "home-ren-alpha", "home-ren-omega")
check("rename concurrency: a page store call that raises is told (mirror 'failed'), the record is renamed, and the page key is released (a later rename is not stuck on 'in progress')", st == 200 and out["mirror"]["state"] == "failed" and server._RENAMING == set()
      and rec_agents(REN)[0][0] == "home-ren-omega", (st, out))
server._pform.PAGE_IO = rio
check("rename concurrency: …and the next one goes through and writes the page again", rn("projects/ren", "home-ren-omega", "home-ren-final")[0] == 200 and server._RENAMING == set() and agents_of("projects/ren")[0][0][0] == "home-ren-final")
st, out = rn("projects/ren", "home-ren-omega", "home-ren-final")
check("rename: 'already renamed' also carries NEW's front, role and mandate, so the caller can see it is the entry it expects", st == 200 and out["result"] == "already renamed" and out["role"] == "final" and out["mandate"] == "talks to Oliver" and out["front"] is True, (st, out))
server._pform.PAGE_IO = gio

# ---- 6e. post project-agent-retire: sala retired a session; the record drops the agent, the page's agents block follows with a timeline line there (or a leftover pending entry is dropped)
import copy as _copy
CFG_PA_6E = _copy.deepcopy(server._cfg.CFG.get("project_agent", None))      # put back at the end of the section
server._pform.PAGE_IO = rio
server._cfg.CFG["project_agent"] = {"form_senders": ["fleet-web", "sala-retire"], "form_machines": ["box-a"]}
ren_page("projects/rtr", REN_FRONT.replace("home-ren", "home-rtr").replace("Ren", "Rtr"))
ren_page("projects/rtr-solo", "type: project\ntitle: Rtr solo\norg: home\ndisplay-name: home-rts\nagents:\n  home-rts-main: talks\n  background:\n    home-rts-bg: in the back\nstatus: active")
ren_page("projects/rtr-fold", "type: project\ntitle: Rtr fold\norg: home\ndisplay-name: home-rtf\nagents:\n  home-rtf-main: talks\n  home-rtf-engineer: >-\n    builds it,\n\n    all of it\n  home-rtf-ops: runs it\n  background:\n    home-rtf-bg: in the back\nstatus: active")
ren_page("projects/rtr-inl", 'type: project\ntitle: Rtr inline\norg: home\ndisplay-name: home-rti\nagents: {home-rti-main: "talks, a lot", home-rti-eng: builds, background: {home-rti-bg: "in the back"}}\nstatus: active')
p.cmd_registry(quiet=True); fresh()
RT = rec("projects/rtr")["id"]; RTS = rec("projects/rtr-solo")["id"]
def rt(project, name, sender="sala-retire", machine="box-a", **kw):
    b = {"project": project, "name": name, **kw}
    if sender is not None: b["sender"] = sender
    return server._client_post(machine, "project-agent-retire", b)
def today(): return server.dt.datetime.now(server._cfg.tz()).strftime("%Y-%m-%d")
def tl(key="projects/rtr"): return [(t[1], t[2], t[3], t[4]) for t in rio.timeline if t[0] == key]
ag0, bg0 = agents_of("projects/rtr")
check("retire: (setup) the page has two front agents and two background ones, and no timeline line was added yet", [n for n, _ in ag0] == ["home-rtr-main", "home-rtr-engineer", "home-rtr-curator", "home-rtr-watch"] and [n for n, _ in bg0] == ["home-rtr-curator", "home-rtr-watch"] and not tl(), (ag0, bg0))

# a front entry: gone from the record, the page's block follows, the timeline line is added
lock_seen = []; real_get = rio.get
rio.get = lambda slug: (lock_seen.append(server._PROJECT_LOCK.locked()), real_get(slug))[1]
rio.puts.clear(); rio.gets.clear()
try: st, out = rt("projects/rtr", "home-rtr-engineer")
finally: rio.get = real_get
ag1, bg1 = agents_of("projects/rtr")
check("retire: an agent on the project's agents map (front) → 200 'line removed', the answer names it, front true, page_owed false", st == 200 and out["result"] == "line removed" and out["agent"] == "home-rtr-engineer" and out["front"] is True
      and out["page_owed"] is False and out["key"] == "projects/rtr" and out["project"] == RT and "Took home-rtr-engineer off projects/rtr's agents map" in out["note"], (st, out))
check("retire: …gone from the record and from the page's block, order, split and mandates of the others kept; the page was written once at the revision read, outside the project lock",
      "home-rtr-engineer" not in dict(rec_agents(RT)) and ag1 == [(n, m) for n, m in ag0 if n != "home-rtr-engineer"] and bg1 == bg0 and rio.puts == [("projects/rtr", "r1")] and lock_seen and not any(lock_seen), (rec_agents(RT), ag1, bg1, rio.puts, lock_seen))
check("retire: …one timeline line, dated today in the instance timezone, source stackshot, saying who was retired and that its line was removed",
      tl() == [(today(), "home-rtr-engineer retired; its line removed from the agents map", "by sala-retire", "stackshot")] and [t for t in rio.timeline if t[0] == "projects/rtr"][0][5].startswith("stackshot-retire-home-rtr-engineer-projects/rtr-"), rio.timeline)
# a background entry (the name matched case-folded, any form label may call)
st, out = rt("projects/rtr", "HOME-RTR-WATCH", sender="fleet-web")
ag2, bg2 = agents_of("projects/rtr")
check("retire: a background agent (any case, another form label) → 200, the record's own spelling reported, front false", st == 200 and out["result"] == "line removed" and out["agent"] == "home-rtr-watch" and out["front"] is False, (st, out))
check("retire: …only its entry is gone, the background: key stays with its other entry, the quoted mandate with a colon is untouched; the timeline line carries the label",
      [n for n, _ in bg2] == ["home-rtr-curator"] and dict(bg2)["home-rtr-curator"] == "keeps the pages: all of them"
      and tl()[-1] == (today(), "home-rtr-watch retired; its line removed from the agents map", "by fleet-web", "stackshot") and len(tl()) == 2, (bg2, tl()))
check("retire: …the project may be named by its id, its page key or its bare slug", rt(RT, "home-rtr-curator")[0] == 200 and rt("rtr", "home-rtr-main")[0] == 200 and agents_of("projects/rtr") == ([], []) and rec_agents(RT) == [], agents_of("projects/rtr"))
# said again: the agent is on no list
rio.puts.clear(); n_tl = len(rio.timeline); text_before = rio.pages["projects/rtr"]
st, out = rt("projects/rtr", "home-rtr-engineer")
check("retire: said again (a lost reply, a repeat) → 200 'not listed' with a reason, no page written, no second timeline line", st == 200 and out["result"] == "not listed" and out["agent"] == "home-rtr-engineer" and out["page_owed"] is False
      and "not on projects/rtr's agents map" in out["reason"] and not rio.puts and len(rio.timeline) == n_tl and rio.pages["projects/rtr"] == text_before, (st, out, rio.puts))
check("retire: …a name that never was on any list is the same answer", rt("projects/rtr", "home-rtr-ghost")[1]["result"] == "not listed" and not rio.puts and len(rio.timeline) == n_tl)

check("retire: …the last agent gone, the project with no open item is archived (the rule of the last retire)", pverbs.pr.entries()[RT]["status"] == "archived", pverbs.pr.entries()[RT])
pverbs.reopen(RT, by="fleet-web", io=rio)
# a leftover pending entry (the record before its migration): dropped, no page written; alongside a listed agent it is left alone
for n_, f_ in (("home-rtr-pend", False), ("home-rtr-pend2", True)): prj.add_pending(RT, n_, {"front": f_, "role": "pend", "mandate_line": "m"}, by="fleet-web", at="2026-03-13T00:00:00Z")
rio.puts.clear(); n_tl = len(rio.timeline); text_before = rio.pages["projects/rtr"]
st, out = rt("projects/rtr", "HOME-RTR-PEND")
pend_now = set(idfile().get("pending_agents", {}).get(RT, {}))
check("retire: a leftover pending agent (any case) → 200 'dropped', its entry is removed, the other stays, page_owed false, no page written, no timeline line", st == 200 and out["result"] == "dropped" and out["agent"] == "home-rtr-pend" and out["page_owed"] is False
      and "was only pending for projects/rtr" in out["note"] and pend_now == {"home-rtr-pend2"} and not rio.puts and len(rio.timeline) == n_tl and rio.pages["projects/rtr"] == text_before, (st, out, pend_now))
with prj._Locked():
    d_ = prj._read(); d_["pending_agents"].pop(RT, None); prj._write(d_)

# the shapes of a page: a wrapped mandate goes with its entry; the last background entry; an inline map
st, out = rt("projects/rtr-fold", "home-rtf-engineer")
check("retire: an entry with a folded mandate over several lines goes with all of them; the neighbours stay", st == 200
      and agents_of("projects/rtr-fold") == ([("home-rtf-main", "talks"), ("home-rtf-ops", "runs it"), ("home-rtf-bg", "in the back")], [("home-rtf-bg", "in the back")]), (st, out, rio.pages["projects/rtr-fold"]))
st, out = rt(RTS, "home-rts-bg")
check("retire: the only background entry → 200, the front agent stays, the page still reads", st == 200 and out["front"] is False and agents_of("projects/rtr-solo") == ([("home-rts-main", "talks")], []), (st, out, rio.pages["projects/rtr-solo"]))
st, out = rt("projects/rtr-inl", "home-rti-bg"); st2, out2 = rt("projects/rtr-inl", "home-rti-main")
check("retire: an inline agents: {…} map (a quoted mandate with a comma, an inline background: {…}) loses just the entry", st == st2 == 200 and out["front"] is False and out2["front"] is True
      and agents_of("projects/rtr-inl") == ([("home-rti-eng", "builds")], []), (st, out, st2, out2, rio.pages["projects/rtr-inl"]))

# a revision that moved on between the read and the put: the mirror reads again and tries once more
ren_page("projects/rtr", REN_FRONT.replace("home-ren", "home-rtr").replace("Ren", "Rtr"))
pverbs.agent_add("projects/rtr", "home-rtr-main", True, "talks to Oliver", by="fleet-web", io=rio)
for n_, m_ in (("home-rtr-engineer", "builds it"), ("home-rtr-curator", "keeps"), ("home-rtr-watch", "watches")): pverbs.agent_add("projects/rtr", n_, True, m_, by="fleet-web", io=rio)
rio.puts.clear(); rio.gets.clear(); n_tl = len(rio.timeline)
other = []
def other_writer(slug, times=1):
    if len(other) < times:
        other.append(1); rio.pages[slug] = rio.pages[slug] + "\n- a line another session added\n"; rio.revs[slug] += 1
rio.hook = other_writer
try: st, out = rt("projects/rtr", "home-rtr-engineer")
finally: rio.hook = None
check("retire: a put refused for a stale revision, then the mirror re-reads and tries again → 200 'line removed', written; the other writer's change kept, the line gone, one timeline line",
      st == 200 and out["result"] == "line removed" and out["mirror"]["state"] == "written" and rio.pages["projects/rtr"].endswith("- a line another session added\n") and "home-rtr-engineer" not in rio.pages["projects/rtr"]
      and len(rio.timeline) == n_tl + 1 and len(rio.puts) == 2 and rio.puts[0][1] != rio.puts[-1][1], (st, out, rio.puts, len(rio.timeline) - n_tl))
# …a page that keeps moving: the record is right, the mirror says it failed, and the next change writes the page
rio.puts.clear(); n_tl = len(rio.timeline)
def always_other(slug): rio.pages[slug] = rio.pages[slug] + "\n- again\n"; rio.revs[slug] += 1
rio.hook = always_other
try: st, out = rt("projects/rtr", "home-rtr-curator")
finally: rio.hook = None
check("retire: a page that moves on at every try → 200, the record dropped the agent, the mirror 'failed' (told in the note), no timeline line", st == 200 and out["mirror"]["state"] == "failed" and "was not updated" in out["note"]
      and "home-rtr-curator" not in dict(rec_agents(RT)) and "home-rtr-curator:" in rio.pages["projects/rtr"] and len(rio.timeline) == n_tl, (st, out))
check("retire: …the next mirror writes the page from the record", pverbs.mirror(RT, rio)["state"] == "written" and "home-rtr-curator" not in rio.pages["projects/rtr"].split("---")[1])
# gbrain trouble
rio.puts.clear(); n_tl = len(rio.timeline); tr_ = rio.pages["projects/rtr"]
rio.get_none = True
try: st, out = rt("projects/rtr", "home-rtr-watch")
finally: rio.get_none = False
check("retire: a page the page store does not give → 200, the record dropped the agent, the mirror 'no-page', nothing written, no timeline line", st == 200 and out["mirror"]["state"] == "no-page" and rio.pages["projects/rtr"] == tr_ and not rio.puts and len(rio.timeline) == n_tl, (st, out))
pverbs.mirror(RT, rio)
n_tl = len(rio.timeline); pverbs.agent_add("projects/rtr", "home-rtr-tl", True, "t", by="fleet-web", io=rio); n_tl = len(rio.timeline); rio.tl_fail = "gbrain said no to the timeline"
try: st, out = rt("projects/rtr", "home-rtr-tl")
finally: rio.tl_fail = ""
check("retire: the page written but the timeline line refused → 200, the mirror says the timeline line was not written; the record and the page hold the removal", st == 200 and "the timeline line was not written" in out["mirror"]["note"]
      and "home-rtr-tl" not in rio.pages["projects/rtr"] and len(rio.timeline) == n_tl, (st, out))
# in flight: the page key is held while the page store works, the project lock is not
pverbs.agent_add("projects/rtr", "home-rtr-fl", True, "t", by="fleet-web", io=rio)
seen_put = []
rio.hook = lambda slug: seen_put.append((server._PROJECT_LOCK.locked(), set(server._RENAMING)))
try: rt("projects/rtr", "home-rtr-fl")
finally: rio.hook = None
check("retire: while the page store holds the put the page key is in flight and the project lock is free; both are released after", seen_put == [(False, {"projects/rtr"})] and server._RENAMING == set() and not server._PROJECT_LOCK.locked(), (seen_put, server._RENAMING))
server._RENAMING.add("projects/rtr"); rio.puts.clear()
try: st, out = rt("projects/rtr", "home-rtr-main")
finally: server._RENAMING.discard("projects/rtr")
check("retire: while a rename or retire of the page is in flight → 409 'in progress; try again', nothing changed", st == 409 and out == {"error": "a rename or retire of projects/rtr is in progress; try again"} and not rio.puts and "home-rtr-main" in dict(rec_agents(RT)), (st, out))

# refusals, each changes nothing
rt_text3 = rio.pages["projects/rtr"]; rt_rec3 = rec_agents(RT); rio.puts.clear(); n_tl = len(rio.timeline)
def rt_same(): return rio.pages["projects/rtr"] == rt_text3 and not rio.puts and len(rio.timeline) == n_tl and rec_agents(RT) == rt_rec3
st, out = rt("projects/nope", "home-nope-main"); st2, out2 = rt("prj_00000000", "home-nope-main")
check("retire: an unknown project is a 404 as project-agent says it", st == st2 == 404 and out["error"].startswith("no project 'projects/nope'") and out2["error"].startswith("no project 'prj_00000000'") and rt_same(), (st, out, st2, out2))
cases = [("a bad name", rt("projects/rtr", "home rtr main")), ("a 65-character name", rt("projects/rtr", "h" * 65)), ("no project", rt("", "home-rtr-main")), ("no name", rt("projects/rtr", "")),
         ("a sender of 81 characters", rt("projects/rtr", "home-rtr-main", sender="x" * 81)), ("a hub: page", rt("projects/theta", "home-theta-main")), ("a sub-page", rt("projects/alpha/sub", "home-sparrow-sub-main"))]
check("retire: a bad name, a missing field, a long sender and a hub: or sub-page are 400s, nothing changed", all(s == 400 for _, (s, o) in cases) and rt_same(), [(n, s, o) for n, (s, o) in cases if s != 400])
check("retire: …the 400 for a page with a hub: line names the hub page", "projects/epsilon" in dict(cases)["a hub: page"][1]["error"], dict(cases)["a hub: page"])
gets_rt = len(rio.gets)
bad = [rt("projects/rtr", "home-rtr-main", sender="other-label"), rt("projects/rtr", "home-rtr-main", sender=None), rt("projects/rtr", "home-rtr-main", sender="box-a"),
       rt("projects/rtr", "home-rtr-main", sender=U["home-sparrow-main"]), rt("projects/rtr", "home-rtr-main", sender="")]
check("retire: a sender that is no form label (a stranger's label, none, the machine's name, a session id, empty) → 403, the same text each time, before the page is read", all(s == 403 and o == {"error": server._RETIRE_NOT_FORM} for s, o in bad)
      and len(rio.gets) == gets_rt and rt_same(), bad)
bad = [rt("projects/rtr", "home-rtr-main", machine=m) for m in ("box-c", "box-e", "")]
check("retire: the form's label from a machine that is not in form_machines (or none proven) → 403, nothing changed", all(s == 403 and o == {"error": server._RETIRE_NOT_FORM} for s, o in bad) and len(rio.gets) == gets_rt and rt_same(), bad)
server._cfg.CFG["project_agent"] = {"form_senders": ["fleet-web"], "form_machines": ["box-a"]}
st, out = rt("projects/rtr", "home-rtr-main")
check("retire: a label that is not in form_senders (sala-retire missing from the config) → 403, so the live config must name sala-retire", st == 403 and out == {"error": server._RETIRE_NOT_FORM} and rt_same(), (st, out))
server._cfg.CFG["project_agent"] = {"form_senders": [], "form_machines": ["box-a"]}
check("retire: with no form label in the config (the defaults) nobody may", rt("projects/rtr", "home-rtr-main", sender="fleet-web")[0] == 403 and rt_same())
server._cfg.CFG["project_agent"] = {"form_senders": ["fleet-web", "sala-retire"], "form_machines": ["box-a"]}

# pages.remove_agent on its own
check("pages.remove_agent: a page with no frontmatter, no agents map, or an unclosed frontmatter is refused, not guessed at", p.remove_agent("# x\n", "a")[0] is None and p.remove_agent("---\ntitle: x\n---\n", "a")[0] is None
      and p.remove_agent("---\nagents:\n  a: x\n", "a")[0] is None)
check("pages.remove_agent: a name only in a mandate text, in another field or not in the map is not removed", p.remove_agent("---\nagents:\n  a: see b: c\n---\n", "b")[0] is None and p.remove_agent("---\nagents:\n  a: x\nowner: b\n---\n", "b")[0] is None)
check("pages.remove_agent: a longer name that starts with the name is not touched (home-x-eng vs home-x-engineer), nor the body", p.remove_agent("---\nagents:\n  home-x-engineer: a\n  home-x-eng: b\n---\nbody home-x-eng: c\n", "home-x-eng")[0]
      == "---\nagents:\n  home-x-engineer: a\n---\nbody home-x-eng: c\n")
check("pages.remove_agent: the entry after a wrapped one, a quoted key and the field after the map are kept as they were", p.remove_agent("---\nagents:\n  \"a\": x\n    wrapped\n  b: y\nowner: z\n---\nbody\n", "a")[0] == "---\nagents:\n  b: y\nowner: z\n---\nbody\n")
if CFG_PA_6E is None: server._cfg.CFG.pop("project_agent", None)
else: server._cfg.CFG["project_agent"] = CFG_PA_6E
server._pform.PAGE_IO = gio

# the retire lines an earlier release kept on the ledger: gone, a debt on the same entry stays
real_page_ts = server._pdebts._page_ts
try:
    server._owed_save({"projects/rtr": {"home-old-keeper": {"ts": time.time(), "item": "", "retired_only": True, "retired": [{"name": "home-rtr-x", "line": "x", "ts": time.time(), "seen": True}]},
                                        "home-debtor": {"ts": time.time(), "item": f"board#{BID_A}", "retired": [{"name": "home-rtr-y", "line": "y", "ts": time.time(), "seen": True}]}}})
    server._pdebts._page_ts = lambda key: 0.0              # the page did not change since: the debt stays
    left = server._owed_settle()
finally:
    server._pdebts._page_ts = real_page_ts
check("retire: a leftover retire-lines-only entry on the ledger is dropped at the next settle, and the line on an entry that also owes a debt goes with the debt kept", set(left.get("projects/rtr", {})) == {"home-debtor"} and "retired" not in left["projects/rtr"]["home-debtor"]
      and left["projects/rtr"]["home-debtor"]["item"] == f"board#{BID_A}" and "AGENTS RETIRED" not in server._nag("home-debtor"), left)
d_ = server._owed_load(); d_.pop("projects/rtr", None); server._owed_save(d_)
check("retire: (cleanup) the ledger holds nothing for the test page", not server._owed_load().get("projects/rtr"), server._owed_load())

# ---- 7. the published file and the id file
J = pj()
check("projects.json: still schema 1 with the same four top-level fields (sala reads front / mandate_line / page_owed and the names; the new fields are additive)", J["schema"] == 1 and set(J) == {"schema", "generated", "projects", "by_key"}
      and all({"id", "key", "keeper", "agents"} <= set(r) for r in J["projects"].values()), set(J))
check("projects.json: every record has scope (one of the three), listed, listed_by, sub_page, items_30d, title", all(r["scope"] in ("work", "home", "ops") and isinstance(r["listed"], bool) and isinstance(r["sub_page"], bool)
      and isinstance(r["items_30d"], int) and "title" in r and r["listed_by"] in ("agents", "items", "on_purpose", "") for r in J["projects"].values()))
check("projects.json: the counts the PR reports are computable from it (6 sub-pages, never listed)", sum(r["sub_page"] for r in J["projects"].values()) == 6 and not any(r["sub_page"] and r["listed"] for r in J["projects"].values()),
      sum(r["sub_page"] for r in J["projects"].values()))
d = idfile(); old = {k: v for k, v in d.items() if k != "marks"}
(T / "store/project-record.json").write_text(json.dumps(old))
check("id file: one written before the marks existed (no marks field) reads fine; nothing is listed on purpose then", prj.marks() == {} and rec("projects/alpha")["listed"] and not rec("projects/eta")["listed"])
d["marks"] = ["not", "an", "object"]; (T / "store/project-record.json").write_text(json.dumps(d))
try: prj._read(); err = ""
except ValueError as e: err = str(e)
check("id file: marks that are not an object are a damaged file (raises, nothing rewritten); a read of the marks goes on with none", "marks is not an object" in err and prj.marks() == {})
d["marks"] = {"not-an-id": {}}; (T / "store/project-record.json").write_text(json.dumps(d))
try: prj._read(); err = ""
except ValueError as e: err = str(e)
check("id file: a mark under something that is not a project id is a damaged file too", "marks entry" in err, err)
d["marks"] = {}; d["future_field"] = {"kept": True}; (T / "store/project-record.json").write_text(json.dumps(d)); prj.set_mark(A, on_purpose="2026-03-13T00:00:00Z")
check("id file: a field this code does not know is kept on a rewrite (extra), as before", idfile().get("future_field") == {"kept": True} and idfile()["marks"][A]["on_purpose"], idfile())
prj.set_mark(A, on_purpose=None)

# ---- 8. the HTTP API and client.py
import copy; from stackshot.fleet import client
_NOCFG = object(); CFG_PA_8 = copy.deepcopy(server._cfg.CFG.get("project_agent", _NOCFG))      # the section's own config, put back by the rename checks' finally
from starlette.testclient import TestClient
me = socket.gethostname(); tok = open(client.mint(me)).read().strip(); HD = {"Authorization": "Bearer " + tok}
app = server.mcp.http_app()
with TestClient(app) as c:
    r = c.get("/client/projects", params={"scope": "home"}); check("http: GET projects without a token → 401", r.status_code == 401, r.status_code)
    r = c.get("/client/projects", params={"scope": "home", "q": "room"}, headers=HD)
    check("http: GET projects → JSON, no-store, the listed rows of home", r.status_code == 200 and r.headers["cache-control"] == "no-store" and r.json()["scope"] == "home" and "projects/alpha" in [x["key"] for x in r.json()["projects"]], r.text[:300])
    r = c.get("/client/projects", params={"scope": "nope"}, headers=HD); check("http: GET projects, a bad scope → 400", r.status_code == 400, r.text)
    r = c.post("/client/project", json={"key": "projects/over-http", "scope": "home", "title": "Over http"}); check("http: POST project without a token → 401, nothing written", r.status_code == 401 and not any(k[0] == "projects/over-http" for k in gio.creates))
    r = c.post("/client/project", json={"key": "projects/over-http", "scope": "home", "title": "Over http", "sender": "fleet-web"}, headers=HD)
    check("http: POST project with the machine token → 200, the project listed, the page written", r.status_code == 200 and r.json()["project"]["listed"] is True and any(k[0] == "projects/over-http" for k in gio.creates), r.text[:300])
    r = c.post("/client/project", json={"key": "projects/over-http", "scope": "home"}, headers=HD); check("http: POST project again → 409", r.status_code == 409 and "project-list" in r.json()["error"], r.text)
    r = c.post("/client/project", json={"key": "people/x", "scope": "home"}, headers=HD); check("http: POST project, a bad key → 400", r.status_code == 400, r.text)
    r = c.post("/client/project-list", json={"key": "projects/delta"}, headers=HD); check("http: POST project-list → 200, listed", r.status_code == 200 and r.json()["project"]["listed"] is True and "projects/delta" in keys("work"), r.text[:300])
    r = c.post("/client/project-list", json={}, headers=HD); check("http: POST project-list with no key → 400", r.status_code == 400, r.text)
    r = c.post("/client/nothing", json={}, headers=HD); check("http: the unknown-write list names the new writes", "project | project-list" in r.json()["error"])
    import urllib.request, urllib.error
    class _Resp:
        def __init__(s, r): s.status = r.status_code; s._b = r.content
        def read(s): return s._b
        def __enter__(s): return s
        def __exit__(s, *a): return False
    def fake_urlopen(req, timeout=0):
        path = req.full_url.replace(client.server_url(), "")
        r = c.post(path, content=req.data, headers=dict(req.header_items())) if req.get_method() == "POST" else c.get(path, headers=dict(req.header_items()))
        if r.status_code >= 400: raise urllib.error.HTTPError(req.full_url, r.status_code, "x", {}, io.BytesIO(r.content))
        return _Resp(r)
    client.urllib.request.urlopen = fake_urlopen
    def run(*argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): rc = client.main(["client.py", *argv])
        return rc, out.getvalue(), err.getvalue()
    rc, o, e = run("get", "projects", "--scope", "ops")
    check("client.py get projects --scope: the JSON on stdout, exit 0", rc == 0 and json.loads(o)["scope"] == "ops" and "ops/gadget" in [x["key"] for x in json.loads(o)["projects"]], (rc, o[:200], e))
    rc, o, e = run("get", "projects", "--scope", "ops", "--q", "room")
    check("client.py get projects --q: the hidden matches too", rc == 0 and any(x["key"] == "projects/zeta" and x["hidden"] for x in json.loads(o)["projects"]), (rc, o[:200], e))
    rc, o, e = run("get", "projects", "--scope", "nope"); check("client.py get projects, a bad scope: exit 1, the reason on stderr, nothing on stdout", rc == 1 and not o and "[400]" in e, (rc, o, e))
    for bad in (["get", "projects"], ["get", "projects", "--scope"], ["get", "projects", "--scope", "home", "extra"]):
        rc, o, e = run(*bad); check(f"client.py get projects misuse → usage on stderr, exit 1 ({' '.join(bad[2:])})", rc == 1 and not o and "usage: client.py get projects" in e or "needs a value" in e, (rc, o, e))
    seen_to = []; real_post = client.post
    client.post = lambda what, body, timeout=20.0: (seen_to.append((what, timeout)), real_post(what, body, timeout))[1]
    rc, o, e = run("post", "project", "--key", "projects/by-cli", "--scope", "ops", "--title", "By the CLI", "--sender", "fleet-web")
    client.post = real_post
    check("client.py post project waits up to 300 s for the gbrain write", seen_to == [("project", 300.0)], seen_to)
    d = json.loads(o) if o.strip() else {}
    check("client.py post project: the server's JSON on stdout, exit 0, the page written", rc == 0 and d["created"] is True and d["project"]["scope"] == "ops" and d["project"]["title"] == "By the CLI" and any(k[0] == "projects/by-cli" for k in gio.creates), (rc, o[:300], e))
    rc, o, e = run("post", "project", "--key", "projects/by-cli", "--scope", "ops"); check("client.py post project, an existing key: exit 1, the 409 on stderr", rc == 1 and not o and "[409]" in e and "post project-list" in e, (rc, o, e))
    for bad in (["post", "project", "--scope", "home"], ["post", "project", "--key", "projects/x"], ["post", "project", "--key", "projects/x", "--scope", "home", "stray"], ["post", "project", "--key"]):
        rc, o, e = run(*bad); check(f"client.py post project misuse → usage on stderr, exit 1 ({' '.join(bad[2:])})", rc == 1 and not o and ("usage: client.py post project " in e or "needs a value" in e), (rc, o, e))
    rc, o, e = run("post", "project-list", "--key", "projects/older-edge", "--scope", "home")
    check("client.py post project-list: the JSON, exit 0, the project listed", rc == 0 and json.loads(o)["changed"] is True and "projects/older-edge" in keys("home"), (rc, o[:300], e))
    rc, o, e = run("post", "project-list", "--key", "projects/alpha/sub"); check("client.py post project-list, a sub-page: exit 1, the 400 on stderr", rc == 1 and not o and "[400]" in e, (rc, o, e))
    rc, o, e = run("post", "project-list"); check("client.py post project-list misuse → usage, exit 1", rc == 1 and "usage: client.py post project-list" in e, (rc, o, e))
    rc, o, e = run("post", "project-agent", "projects/by-cli", "ops-by-cli-main", "--role", "main", "--front", "--mandate", "the form's agent", "--sender", "fleet-web")
    check("client.py post project-agent on the project just made: a label as the sender, exit 0, the note printed", rc == 0 and "in the project record" in o and rec("projects/by-cli")["agents"]["ops-by-cli-main"]["front"] is True, (rc, o, e))
    rc, o, e = run("get", "projects", "--scope", "ops"); mine = [x for x in json.loads(o)["projects"] if x["key"] == "projects/by-cli"]
    check("client.py: …and the list shows the project with that agent, front, as main", len(mine) == 1 and mine[0]["main"] == "ops-by-cli-main" and "page_owed" not in mine[0]["agents"]["ops-by-cli-main"] and mine[0]["listed_by"] == "agents", mine)
    check("client.py: get projects is one of the reads", "projects" in client.READS)
    # post project-agent-rename over HTTP and through client.py (the token's machine is this one: let it be a form machine for the checks, then put the config back)
    server._cfg.CFG["project_agent"] = {"form_senders": ["fleet-web"], "form_machines": [me]}; server._pform.PAGE_IO = rio
    try:
        r = c.post("/client/project-agent-rename", json={"project": "projects/ren-http", "old": "home-rhttp-engineer", "new": "home-rhttp-builder", "sender": "fleet-web"})
        check("http: POST project-agent-rename without a token → 401, nothing written", r.status_code == 401 and "home-rhttp-builder" not in rio.pages["projects/ren-http"], r.status_code)
        r = c.post("/client/project-agent-rename", json={"project": "projects/ren-http", "old": "home-rhttp-engineer", "new": "home-rhttp-builder", "sender": "fleet-web"}, headers=HD)
        check("http: POST project-agent-rename with the machine token and the form's label → 200 renamed, the page changed", r.status_code == 200 and r.json()["result"] == "renamed" and "  home-rhttp-builder: builds it" in rio.pages["projects/ren-http"], r.text[:300])
        r = c.post("/client/project-agent-rename", json={"project": "projects/ren-http", "old": "home-rhttp-main", "new": "home-rhttp-builder", "sender": "fleet-web"}, headers=HD)
        check("http: …NEW already listed → 409 with the exact text", r.status_code == 409 and r.json() == {"error": "home-rhttp-builder is already listed on projects/ren-http"}, r.text)
        r = c.post("/client/project-agent-rename", json={"project": "projects/ren-http", "old": "home-rhttp-main", "new": "home-rhttp-chief", "sender": "someone"}, headers=HD)
        check("http: …a label that is not the form's → 403", r.status_code == 403 and "home-rhttp-chief" not in rio.pages["projects/ren-http"], r.text)
        seen_rn = []; real_post_rn = client.post
        client.post = lambda what, body, timeout=20.0: (seen_rn.append((what, timeout)), real_post_rn(what, body, timeout))[1]
        try: rc, o, e = run("post", "project-agent-rename", "projects/ren-cli", "home-rcli-engineer", "home-rcli-builder", "--sender", "fleet-web")
        finally: client.post = real_post_rn
        check("client.py post project-agent-rename waits up to 300 s (gbrain reads, writes and reads back), as post project does", seen_rn == [("project-agent-rename", 300.0)], seen_rn)
        d = json.loads(o) if o.strip() else {}
        check("client.py post project-agent-rename: the server's JSON on stdout, exit 0, the page changed in place", rc == 0 and d["result"] == "renamed" and d["old"] == "home-rcli-engineer" and d["new"] == "home-rcli-builder"
              and "  home-rcli-builder: builds it\n" in rio.pages["projects/ren-cli"] and "home-rcli-engineer" not in rio.pages["projects/ren-cli"], (rc, o, e))
        rc, o, e = run("post", "project-agent-rename", "projects/ren-cli", "home-rcli-engineer", "home-rcli-builder", "--sender", "fleet-web")
        check("client.py: …said again (the lost-reply retry) → exit 0 and 'already renamed' on stdout", rc == 0 and json.loads(o)["result"] == "already renamed" and json.loads(o)["note"] == "already renamed", (rc, o, e))
        rc, o, e = run("post", "project-agent-rename", "projects/ren-cli", "home-rcli-main", "home-rcli-builder", "--sender", "fleet-web")
        check("client.py: …NEW already listed → exit 1, nothing on stdout, the 409 and its text on stderr", rc == 1 and not o and "[409]" in e and "home-rcli-builder is already listed on projects/ren-cli" in e, (rc, o, e))
        rc, o, e = run("post", "project-agent-rename", "projects/ren-cli", "home-rcli-ghost", "home-rcli-newbie", "--sender", "fleet-web")
        check("client.py: …OLD not listed → exit 1, the 404 and its text on stderr", rc == 1 and not o and "[404]" in e and "home-rcli-ghost is not listed on projects/ren-cli" in e, (rc, o, e))
        rc, o, e = run("post", "project-agent-rename", "projects/ren-cli", "home-rcli-main", "home-rcli-chief")
        check("client.py: …with no --sender the caller is the machine, which is no form label → exit 1, 403 on stderr, nothing changed", rc == 1 and not o and "[403]" in e and "home-rcli-chief" not in rio.pages["projects/ren-cli"], (rc, o, e))
        for bad in (["post", "project-agent-rename"], ["post", "project-agent-rename", "projects/ren-cli", "a"], ["post", "project-agent-rename", "projects/ren-cli", "a", "b", "c"],
                    ["post", "project-agent-rename", "projects/ren-cli", "a", "b", "--sender"], ["post", "project-agent-rename", "--sender", "x", "a", "b"]):
            rc, o, e = run(*bad); check(f"client.py post project-agent-rename misuse → usage on stderr, exit 1 ({' '.join(bad[2:])})", rc == 1 and not o and "usage: client.py post project-agent-rename <project> <OLD> <NEW> [--sender <label>]" in e, (rc, o, e))
        # post project-agent-retire, the same way: the form's label (sala-retire); the page's line removed, the timeline line added
        server._cfg.CFG["project_agent"] = {"form_senders": ["fleet-web", "sala-retire"], "form_machines": [me]}
        RH = rec("projects/ren-http")["id"]; prj.add_pending(RH, "home-rhttp-pend", {"front": False, "role": "pend", "mandate_line": "m"}, by="fleet-web", at="2026-03-13T00:00:00Z")
        rh_puts = len(rio.puts); rh_tl = len(rio.timeline)
        r = c.post("/client/project-agent-retire", json={"project": "projects/ren-http", "name": "home-rhttp-pend", "sender": "sala-retire"})
        check("http: POST project-agent-retire without a token → 401, the pending agent stays", r.status_code == 401 and "home-rhttp-pend" in idfile().get("pending_agents", {}).get(RH, {}), r.status_code)
        r = c.post("/client/project-agent-retire", json={"project": "projects/ren-http", "name": "home-rhttp-pend", "sender": "sala-retire"}, headers=HD)
        check("http: …with the machine token and the label → 200 dropped, the pending entry gone, no page written", r.status_code == 200 and r.json()["result"] == "dropped" and "home-rhttp-pend" not in idfile().get("pending_agents", {}).get(RH, {})
              and len(rio.puts) == rh_puts and len(rio.timeline) == rh_tl, r.text[:300])
        r = c.post("/client/project-agent-retire", json={"project": "projects/ren-http", "name": "home-rhttp-pend", "sender": "sala-retire"}, headers=HD)
        check("http: …said again → 200 'not listed' with a reason, nothing changed", r.status_code == 200 and r.json()["result"] == "not listed" and "reason" in r.json() and len(rio.puts) == rh_puts, r.text)
        r = c.post("/client/project-agent-retire", json={"project": "projects/ren-http", "name": "home-rhttp-main", "sender": "sala-retire"}, headers=HD)
        check("http: …an agent on the page → 200 line removed, the page written once, a timeline line added", r.status_code == 200 and r.json()["result"] == "line removed" and "home-rhttp-main:" not in rio.pages["projects/ren-http"]
              and len(rio.puts) == rh_puts + 1 and len(rio.timeline) == rh_tl + 1 and rio.timeline[-1][0] == "projects/ren-http", r.text[:300])
        r = c.post("/client/project-agent-retire", json={"project": "projects/ren-http", "name": "home-rhttp-curator", "sender": "someone"}, headers=HD)
        check("http: …a label that is not the form's → 403", r.status_code == 403 and "home-rhttp-curator:" in rio.pages["projects/ren-http"], r.text)
        seen_rt = []; real_post_rt = client.post
        client.post = lambda what, body, timeout=20.0: (seen_rt.append((what, timeout)), real_post_rt(what, body, timeout))[1]
        try: rc, o, e = run("post", "project-agent-retire", "projects/ren-cli", "home-rcli-main", "--sender", "sala-retire")
        finally: client.post = real_post_rt
        d = json.loads(o) if o.strip() else {}
        check("client.py post project-agent-retire: the server's JSON on stdout, exit 0, 'line removed', the line gone from the page, the timeout long enough for gbrain's read, write, read back and timeline line",
              rc == 0 and d.get("result") == "line removed" and d.get("agent") == "home-rcli-main" and seen_rt == [("project-agent-retire", 300.0)] and "home-rcli-main:" not in rio.pages["projects/ren-cli"], (rc, o, e, seen_rt))
        RC = rec("projects/ren-cli")["id"]; prj.add_pending(RC, "home-rcli-pend", {"front": True, "role": "pend", "mandate_line": "m"}, by="fleet-web", at="2026-03-13T00:00:00Z")
        rc, o, e = run("post", "project-agent-retire", "projects/ren-cli", "home-rcli-pend", "--sender", "sala-retire")
        check("client.py: …a pending agent → exit 0, 'dropped' (200) on stdout", rc == 0 and json.loads(o)["result"] == "dropped" and "home-rcli-pend" not in idfile().get("pending_agents", {}).get(RC, {}), (rc, o, e))
        rc, o, e = run("post", "project-agent-retire", "projects/ren-cli", "home-rcli-pend", "--sender", "sala-retire")
        check("client.py: …said again → exit 0, 'not listed' (200) and its reason on stdout", rc == 0 and json.loads(o)["result"] == "not listed" and "reason" in json.loads(o), (rc, o, e))
        rc, o, e = run("post", "project-agent-retire", "projects/ren-cli", "home-rcli-curator")
        check("client.py: …with no --sender the caller is the machine, which is no form label → exit 1, 403 on stderr", rc == 1 and not o and "[403]" in e and "home-rcli-curator:" in rio.pages["projects/ren-cli"], (rc, o, e))
        rio.get_none = True
        try: rc, o, e = run("post", "project-agent-retire", "projects/ren-cli", "home-rcli-curator", "--sender", "sala-retire")
        finally: rio.get_none = False
        check("client.py: …a page the page store does not give → exit 0, the record's answer on stdout with the mirror 'no-page' (the record is right, the page is not written)", rc == 0 and json.loads(o)["mirror"]["state"] == "no-page", (rc, o, e))
        for bad in (["post", "project-agent-retire"], ["post", "project-agent-retire", "projects/ren-cli"], ["post", "project-agent-retire", "projects/ren-cli", "a", "b"],
                    ["post", "project-agent-retire", "projects/ren-cli", "a", "--sender"], ["post", "project-agent-retire", "--sender", "x", "a"]):
            rc, o, e = run(*bad); check(f"client.py post project-agent-retire misuse → usage on stderr, exit 1 ({' '.join(bad[2:])})", rc == 1 and not o and "usage: client.py post project-agent-retire <project> <name> [--sender <label>]" in e, (rc, o, e))
        with prj._Locked():
            d_ = prj._read(); [d_["pending_agents"].get(k, {}).pop(n, None) for k, n in ((RH, "home-rhttp-pend"), (RC, "home-rcli-pend"))]; prj._write(d_)
    finally:
        server._pform.PAGE_IO = gio
        if CFG_PA_8 is _NOCFG: server._cfg.CFG.pop("project_agent", None)
        else: server._cfg.CFG["project_agent"] = copy.deepcopy(CFG_PA_8)

# ---- 9. a retired project (the page's status is archived, retired, closed, done or dropped): never listed, not re-listed, no label adds an agent
page("projects/ark.md", "type: project\ntitle: Sunset ark\nname: Sunset ark\nstatus: archived\ndisplay-name: home-ark")                       # recent items, archived
page("projects/ret-agents.md", "type: project\ntitle: Retired with agents\nstatus: Retired\ndisplay-name: home-ret-agents\nagents:\n  home-ret-agents-main: was the main agent")   # status read without case
page("projects/ret-marked.md", "type: project\ntitle: Dropped but marked\nstatus: dropped\ndisplay-name: home-ret-marked")                # an on-purpose mark on a retired page
page("projects/ret-keeper.md", "type: project\ntitle: Closed with a live keeper\nstatus: closed\ndisplay-name: home-fresh")               # its keeper is a present session
page("projects/ret-done.md", "type: project\ntitle: Done one\nstatus: done\ndisplay-name: home-ret-done")
page("projects/live-active.md", "type: project\ntitle: Live active\nstatus: active\ndisplay-name: home-live-active")                      # status active, an item → listed
page("projects/live-nostatus.md", "type: project\ntitle: Live nostatus\ndisplay-name: home-live-nostatus")                                # no status, an item → listed
page("projects/live-paused.md", "type: project\ntitle: Live paused\nstatus: paused\ndisplay-name: home-live-paused")                      # not in the default set, an item → listed
page("projects/act-marked.md", "type: project\ntitle: Active marked\nstatus: active\ndisplay-name: home-act-marked")                     # the control of the label path
for k in ("ark", "ret-done", "live-active", "live-nostatus", "live-paused"): item("projects/" + k, 2)
p.cmd_registry(quiet=True); fresh()
check("retired: the registry carries the page's status as the page has it", reg()["projects/ark"]["status"] == "archived" and reg()["projects/ret-agents"]["status"] == "Retired" and reg()["projects/live-nostatus"]["status"] == "", {k: reg()[k]["status"] for k in ("projects/ark", "projects/ret-agents")})
R = {k: rec("projects/" + k) for k in ("ark", "ret-agents", "ret-marked", "ret-keeper", "ret-done", "live-active", "live-nostatus", "live-paused")}
check("retired: the record carries status (lowercase, \"\" if none) and retired", R["ark"]["status"] == "archived" and R["ark"]["retired"] is True and R["ret-agents"]["status"] == "retired" and R["ret-agents"]["retired"] is True
      and R["live-nostatus"]["status"] == "" and R["live-nostatus"]["retired"] is False and R["live-active"]["status"] == "active" and R["live-active"]["retired"] is False and R["live-paused"]["retired"] is False, {k: (v["status"], v["retired"]) for k, v in R.items()})
check("retired: an archived page with an item touched 2 days ago is not listed, and is no search match (key, name, title)", R["ark"]["items_30d"] == 1 and R["ark"]["listed"] is False and R["ark"]["listed_by"] == ""
      and not any("projects/ark" in keys(s, q) for s in ("", "home", "all") for q in ("", "ark", "sunset", "Sunset ark")), (R["ark"], keys("", "sunset")))
check("retired: a retired page with agents (its status in capitals) is not listed, its agents are still in its record, and a search does not find it", R["ret-agents"]["listed"] is False and "home-ret-agents-main" in R["ret-agents"]["agents"]
      and "projects/ret-agents" not in keys("") and "projects/ret-agents" not in keys("", "retired with"), R["ret-agents"])
check("retired: …nor are done and closed pages (an item, a live keeper)", "projects/ret-done" not in keys("") and "projects/ret-keeper" not in keys("", "closed") and R["ret-done"]["listed"] is False)
page("projects/ret-completed.md", "type: project\ntitle: Completed one\nstatus: completed\ndisplay-name: home-ret-completed")
page("projects/ret-merged.md", "type: project\ntitle: Merged one\nstatus: merged\ndisplay-name: home-ret-merged\nagents:\n  home-ret-merged-main: m")
item("projects/ret-completed", 3); item("projects/ret-merged", 3); p.cmd_registry(quiet=True); fresh()
check("retired: a completed page with a recent item is not listed and no search match; retired true, status completed", rec("projects/ret-completed")["retired"] is True and rec("projects/ret-completed")["status"] == "completed"
      and rec("projects/ret-completed")["listed"] is False and not any("projects/ret-completed" in keys(s, q) for s in ("", "home") for q in ("", "completed one", "ret-completed")), keys("", "completed one"))
check("retired: a merged page with an item and an agent is not listed and no search match; retired true, status merged", rec("projects/ret-merged")["retired"] is True and rec("projects/ret-merged")["status"] == "merged"
      and rec("projects/ret-merged")["listed"] is False and not any("projects/ret-merged" in keys(s, q) for s in ("", "home") for q in ("", "merged one", "ret-merged")), keys("", "merged one"))
check("retired: …and a re-list of either is refused (400)", relist("projects/ret-completed")[0] == 400 and relist("projects/ret-merged")[0] == 400)
M = R["ret-marked"]["id"]; prj.set_mark(M, on_purpose="2026-03-13T00:00:00Z", at="2026-03-13T00:00:00Z", by="fleet-web"); fresh()
check("retired: an on-purpose mark on a dropped page is ignored: not listed, no search match", rec("projects/ret-marked")["listed"] is False and rec("projects/ret-marked")["listed_by"] == "" and "projects/ret-marked" not in keys("", "dropped")
      and "projects/ret-marked" not in keys("home"), rec("projects/ret-marked"))
check("retired: pages with status active, none or a word outside the set (paused) are unaffected: listed by their item", all(R[k]["listed"] and R[k]["listed_by"] == "items" for k in ("live-active", "live-nostatus", "live-paused"))
      and all("projects/" + k in keys("home") for k in ("live-active", "live-nostatus", "live-paused")), keys("home"))
st, d = lst("")
rows = {r["key"]: r for r in d["projects"]}
check("retired: every row of get projects carries retired (false) and status; a retired project is in none", st == 200 and all(r["retired"] is False and isinstance(r["status"], str) for r in d["projects"])
      and not any(k in rows for k in ("projects/ark", "projects/ret-agents", "projects/ret-marked", "projects/ret-keeper", "projects/ret-done"))
      and rows["projects/live-active"]["status"] == "active" and rows["projects/live-nostatus"]["status"] == "", [(r["key"], r["status"]) for r in d["projects"]][:6])
st, ctype, body = server._client_get("project", {"key": "projects/ark"}); one = json.loads(body)
check("retired: get project still answers for a retired project, with retired true and its status", st == 200 and one["retired"] is True and one["status"] == "archived" and one["listed"] is False, (st, body[:200]))
_projects_registry._projects_sync(now=NOW + 2, force=True)
check("retired: the published file carries both fields", pj()["projects"][R["ark"]["id"]]["retired"] is True and pj()["projects"][R["live-active"]["id"]]["status"] == "active")
# re-list refused
marks_before = dict(idfile()["marks"].get(R["ark"]["id"]) or {})
st, out = relist("projects/ark", sender="fleet-web")
check("retired: post project-list on an archived project → 400 'retired (page status: archived): change the page's status first', nothing marked", st == 400 and "retired (page status: archived): change the page's status first" in out["error"]
      and (idfile()["marks"].get(R["ark"]["id"]) or {}) == marks_before and rec("projects/ark")["listed"] is False, (st, out))
st, out = relist("projects/ret-agents", scope="ops"); check("retired: …by the page's status in capitals too (reported lowercase), and with a scope", st == 400 and "(page status: retired)" in out["error"] and not (idfile()["marks"].get(R["ret-agents"]["id"]) or {}).get("scope"), (st, out))
check("retired: …by a bare slug too", relist("ret-done")[0] == 400)
# project-agent
now_t = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
prj.set_mark(M, on_purpose=now_t, at=now_t, by="fleet-web"); fresh()
st, out = pa("projects/ret-marked", "home-ret-marked-main", "fleet-web")
check("retired: a form-call (label) project-agent on a dropped project with a fresh mark by that label → 403 retired, nothing recorded", st == 403 and "retired (page status: dropped)" in out["error"] and "home-ret-marked-main" not in rec("projects/ret-marked")["agents"], (st, out))
AM = rec("projects/act-marked")["id"]; prj.set_mark(AM, on_purpose=now_t, at=now_t, by="fleet-web"); fresh()
st, out = pa("projects/act-marked", "home-act-marked-main", "fleet-web")
check("retired: …the same call on an active page is as before (200, recorded)", st == 200 and "home-act-marked-main" in rec("projects/act-marked")["agents"], (st, out))
prj.add_pending(M, "home-ret-marked-old", {"front": True, "role": "old", "mandate_line": "m"}, by="fleet-web", at=now_t); fresh()
st, out = pa("projects/ret-marked", "home-ret-marked-more", "fleet-web", role="more")
check("retired: …a label adding a further agent to a retired project's pending agents → 403 too", st == 403 and "retired" in out["error"] and "home-ret-marked-more" not in rec("projects/ret-marked")["agents"], (st, out))
PJR = (T / "state/projects.json").read_bytes(); PEND_R = json.dumps(idfile().get("pending_agents", {}), sort_keys=True)
st, out = fpa("box-a", "projects/ark", "home-ark-helper", "fleet-web"); st2, out2 = fpa("box-a", "projects/ret-agents", "home-ret-agents-helper", "fleet-web")
check("retired: a form call (fleet-web, box-a token) adding an agent to an archived project, and to a retired one that has agents → 403 retired, before any write", st == 403 and st2 == 403
      and "retired (page status: archived)" in out["error"] and "retired (page status: retired)" in out2["error"] and "home-ark-helper" not in rec("projects/ark")["agents"] and "home-ret-agents-helper" not in rec("projects/ret-agents")["agents"]
      and json.dumps(idfile().get("pending_agents", {}), sort_keys=True) == PEND_R and (T / "state/projects.json").read_bytes() == PJR, (st, out, st2, out2))
st, out = pa("projects/ret-keeper", "home-fresh-retired-main", U["home-fresh"], role="retired-main")   # not home-fresh-main: that name is live-keeper's (a name belongs to one project)
check("retired: the keeper's own session id still lists an agent on a retired project, as today", st == 200 and "home-fresh-retired-main" in rec("projects/ret-keeper")["agents"], (st, out))
# the config's set
cfgps = prj._cfg.CFG.setdefault("project_scopes", {}); had = cfgps.get("retired_statuses", "absent")
check("retired: the default set is archived, retired, closed, done, dropped, completed, merged (in code and in stackshot.example.toml)", prj.retired_statuses() == {"archived", "retired", "closed", "done", "dropped", "completed", "merged"} == set(prj._RETIRED)
      and had == ["archived", "retired", "closed", "done", "dropped", "completed", "merged"], (prj.retired_statuses(), had))
cfgps["retired_statuses"] = ["Paused"]; fresh()
check("retired: [project_scopes] retired_statuses overrides the set (case-free): paused retires, archived is an ordinary status then", "projects/live-paused" not in keys("home") and rec("projects/live-paused")["retired"] is True
      and rec("projects/ark")["retired"] is False and relist("projects/ark", sender="fleet-web")[0] == 200 and "projects/ark" in keys("home"), keys("home"))
cfgps["retired_statuses"] = []; fresh()
check("retired: an empty set retires nothing", rec("projects/ret-done")["retired"] is False and "projects/ret-done" in keys("home"), keys("home"))
del cfgps["retired_statuses"]; fresh()
check("retired: with the key absent the defaults apply", prj.retired_statuses() == set(prj._RETIRED) and rec("projects/live-paused")["retired"] is False)
cfgps["retired_statuses"] = had; fresh()

server._pform.PAGE_IO = rio
CFG_PA_6F = _copy.deepcopy(server._cfg.CFG.get("project_agent", None))
server._cfg.CFG["project_agent"] = {"form_senders": ["fleet-web", "sala-retire"], "form_machines": ["box-a"]}

# ---- 6f. archive on the last retire: a project with no agent and no open item is archived; one with open items waits on a list and is archived by the sweep once none is left
from stackshot.projects import project_archive as ARC
AWAIT = pathlib.Path(server._cfg.state("archive-wait.json"))
def wait_keys(): return set(json.loads(AWAIT.read_text())) if AWAIT.exists() else set()
def status_of(slug): return str(p.frontmatter_text(rio.pages[slug]).get("status") or "")
def arc_page(slug, agents, status="active", extra=""):
    ags = "".join(f"  {a}: does a part\n" for a in agents)
    ren_page(slug, f"type: project\ntitle: {slug.split('/')[-1]}\norg: home\ndisplay-name: home-{slug.split('/')[-1]}\nagents:\n{ags.rstrip()}" + (f"\nstatus: {status}" if status else "") + extra)
def open_item(project, status="open"):
    item(project, 1, status=status); return _n[0]
def item_file(n): return T / f"store/a/{n}.json"
def tl_texts(key): return [t[2] for t in rio.timeline if t[0] == key]
arc_page("projects/arc-one", ["home-arc-one-main"])
arc_page("projects/arc-two", ["home-arc-two-main"])
arc_page("projects/arc-pair", ["home-arc-pair-main", "home-arc-pair-docs"])
arc_page("projects/arc-pend", ["home-arc-pend-main"])
arc_page("projects/arc-back", ["home-arc-back-main"])
arc_page("projects/arc-done", ["home-arc-done-main"], status="done")
arc_page("projects/arc-nostat", ["home-arc-nostat-main"], status="")
arc_page("projects/arc-hub", ["home-arc-hub-main"])
page("projects/arc-hub/notes.md", "type: note\ntitle: Notes of the hub")
p.cmd_registry(quiet=True); fresh()
ARC_IDS = {k: rec("projects/" + k)["id"] for k in ("arc-pend",)}

# (1) the last agent, no open item → archived at once: the status line changed in place, one put more, two timeline lines
rio.puts.clear(); rio.timeline.clear(); t_one0 = rio.pages["projects/arc-one"]
st, out = rt("projects/arc-one", "home-arc-one-main")
t_one1 = rio.pages["projects/arc-one"]
check("archive: the last agent retired, no open item → 200 'line removed' and archived true, the answer says so", st == 200 and out["result"] == "line removed" and out["archived"] is True and "archived" in out["archive_note"], (st, out))
check("archive: …the page's status is archived, its agents map is empty, and only the agent's line and the status line differ from before",
      status_of("projects/arc-one") == "archived" and agents_of("projects/arc-one") == ([], []) and [l for l in t_one0.split("\n") if l not in t_one1.split("\n")] == ["  home-arc-one-main: does a part", "status: active"]
      and [l for l in t_one1.split("\n") if l not in t_one0.split("\n")] == ["status: archived"], (t_one1,))
check("archive: …two puts (the retire's with r1, the status with r2), and a timeline line for each: the retire and the archiving, the second by the sender",
      rio.puts == [("projects/arc-one", "r1"), ("projects/arc-one", "r2")] and tl_texts("projects/arc-one") == ["home-arc-one-main retired; its line removed from the agents map", "archived; its last agent was retired"]
      and rio.timeline[1][3] == "by sala-retire" and rio.timeline[1][4] == "stackshot", (rio.puts, rio.timeline))
check("archive: …nothing is waiting", wait_keys() == set(), wait_keys())
(T / "brain/projects/arc-one.md").write_text(rio.pages["projects/arc-one"], encoding="utf-8"); p.cmd_registry(quiet=True); fresh()      # the pages checkout catches up
check("archive: …the registry reads the page as archived and the Projects page's rule (Board.finished) puts it in the Archived group", reg()["projects/arc-one"]["status"] == "archived" and prj.ref("projects/arc-one")["retired"] is True)
rio.puts.clear(); n_tl = len(rio.timeline)
st, out = rt("projects/arc-one", "home-arc-one-main")
check("archive: said again → 200 'not listed', no archive keys, nothing written (a repeat does nothing)", st == 200 and out["result"] == "not listed" and "archived" not in out and not rio.puts and len(rio.timeline) == n_tl, (st, out))

# (2) agents left → not archived, and nothing waits; the last one → archived
st, out = rt("projects/arc-pair", "home-arc-pair-docs")
check("archive: one agent of two retired → not archived ('1 agent(s) on the page'), the page's status stays active, nothing waits", st == 200 and out["archived"] is False and "1 agent(s) on the project" in out["archive_note"]
      and status_of("projects/arc-pair") == "active" and wait_keys() == set(), (st, out))
st, out = rt("projects/arc-pair", "home-arc-pair-main")
check("archive: …the second (last) one retired → archived", st == 200 and out["archived"] is True and status_of("projects/arc-pair") == "archived", (st, out))

# (3) open items → stays active and waits; the sweep leaves it while any item is left, archives it when none is
i1, i2 = open_item("projects/arc-two"), open_item("projects/arc-two", status="open")
rio.puts.clear(); rio.timeline.clear()
st, out = rt("projects/arc-two", "home-arc-two-main")
check("archive: the last agent retired with 2 open items → 200 'line removed', archived false, the note names the items and says it follows once none is left", st == 200 and out["archived"] is False
      and "2 open item(s)" in out["archive_note"] and f"a{i1}" in out["archive_note"] and "once none is left" in out["archive_note"], (st, out))
check("archive: …the page's status stays active (only the retire's own put), the project is on the wait list", status_of("projects/arc-two") == "active" and len(rio.puts) == 1 and wait_keys() == {"projects/arc-two"}
      and json.loads(AWAIT.read_text())["projects/arc-two"]["by"] == "sala-retire", (rio.puts, wait_keys()))
rio.puts.clear(); gets0 = len(rio.gets)
res = server._archive_tick()
check("archive sweep: both items still open → the project waits, nothing is written", res == [("projects/arc-two", res[0][1])] and res[0][1].startswith("waits: 2 open item(s)") and not rio.puts and wait_keys() == {"projects/arc-two"}, res)
d1 = json.loads(item_file(i1).read_text()); d1["status"] = "completed"; item_file(i1).write_text(json.dumps(d1))
res = server._archive_tick()
check("archive sweep: one item completed, one left → still waiting", res[0][1].startswith("waits: 1 open item(s)") and not rio.puts and status_of("projects/arc-two") == "active", res)
d2 = json.loads(item_file(i2).read_text()); d2["metadata"]["project"] = "projects/alpha"; item_file(i2).write_text(json.dumps(d2))
res = server._archive_tick()
check("archive sweep: the other item handed to another project → the next sweep archives the project (status archived, a timeline line, off the wait list)", res == [("projects/arc-two", "archived")] and status_of("projects/arc-two") == "archived"
      and wait_keys() == set() and tl_texts("projects/arc-two")[-1] == "archived; its last agent was retired and its open items are gone", (res, tl_texts("projects/arc-two")))
rio.puts.clear(); gets1 = len(rio.gets); n_tl = len(rio.timeline)
check("archive sweep: a sweep over the same state again does nothing: no read, no write, no timeline line", server._archive_tick() == [] and not rio.puts and len(rio.gets) == gets1 and len(rio.timeline) == n_tl)

# (4) a sub-page's open item counts for its project; a pending agent keeps it staffed; an agent back on the page takes it off the list
i3 = open_item("projects/arc-hub/notes")
st, out = rt("projects/arc-hub", "home-arc-hub-main")
check("archive: an open item on a sub-page counts for its project → waits", out["archived"] is False and f"a{i3}" in out["archive_note"] and "projects/arc-hub" in wait_keys() and status_of("projects/arc-hub") == "active", (st, out))
pverbs.agent_add("projects/arc-pend", "home-arc-pend-new", False, "m", by="fleet-web", io=rio)
st, out = rt("projects/arc-pend", "home-arc-pend-main")
check("archive: another agent the record lists keeps the project staffed → not archived, nothing waits for it", out["archived"] is False and "1 agent(s) on the project" in out["archive_note"] and "projects/arc-pend" not in wait_keys()
      and status_of("projects/arc-pend") == "active", (st, out))
st, out = rt("projects/arc-pend", "home-arc-pend-new")
check("archive: …retiring that one leaves none → archived", st == 200 and out["result"] == "line removed" and out["archived"] is True and status_of("projects/arc-pend") == "archived", (st, out))
i4 = open_item("projects/arc-back")
rt("projects/arc-back", "home-arc-back-main")
pverbs.agent_add("projects/arc-back", "home-arc-back-new", True, "back again", by="fleet-web", io=rio)
d4 = json.loads(item_file(i4).read_text()); d4["status"] = "completed"; item_file(i4).write_text(json.dumps(d4)); rio.puts.clear()
res = server._archive_tick()
check("archive sweep: a project that has an agent again leaves the list without a write, whatever its items", ("projects/arc-back", "left the list: 1 agent(s) on the project") in res and not rio.puts and "projects/arc-back" not in wait_keys()
      and status_of("projects/arc-back") == "active", res)

# (5) a page already retired by hand, a page with no status line, a failed write
st, out = rt("projects/arc-done", "home-arc-done-main")
check("archive: a page whose status is already a retired word (done) is left as it is → archived false 'already done'", out["archived"] is False and "already" in out["archive_note"], (st, out))
st, out = rt("projects/arc-nostat", "home-arc-nostat-main")
check("archive: a page with no status line gets one, just before the frontmatter's closing line", out["archived"] is True and rio.pages["projects/arc-nostat"].split("\n")[:8] == ["---", "type: project", "title: arc-nostat", "org: home", "display-name: home-arc-nostat", "agents:", "status: archived", "---"],
      rio.pages["projects/arc-nostat"][:200])
arc_page("projects/arc-fail", ["home-arc-fail-main"]); p.cmd_registry(quiet=True); fresh()
rio.puts.clear(); rio.hook = lambda slug: setattr(rio, "mode", "refused") if slug == "projects/arc-fail" and len(rio.puts) == 2 else None
st, out = rt("projects/arc-fail", "home-arc-fail-main"); rio.hook = None; rio.mode = "ok"
check("archive: a status write that the page store refuses never fails the retire: 200 'line removed', archived true in the record, the page's status line not yet written", st == 200 and out["result"] == "line removed" and out["archived"] is True
      and pverbs.pr.entries()[rec("projects/arc-fail")["id"]]["status"] == "archived" and status_of("projects/arc-fail") == "active" and agents_of("projects/arc-fail") == ([], []), (st, out, status_of("projects/arc-fail")))
check("archive: …the next mirror writes the status line from the record", pverbs.mirror(rec("projects/arc-fail")["id"], rio)["state"] == "written" and status_of("projects/arc-fail") == "archived")
# a page that never had an agents: key is never archived by a retire of a name it does not list
ren_page("projects/arc-nomap", "type: project\ntitle: arc-nomap\norg: home\ndisplay-name: home-arc-nomap\nstatus: active"); p.cmd_registry(quiet=True); fresh()
rio.puts.clear(); n_tl = len(rio.timeline)
st, out = rt("projects/arc-nomap", "home-arc-nomap-main")
check("archive: a retire of a name on a project that was never staffed → 'not listed', archived false or absent, nothing written, not on the wait list, status active",
      st == 200 and out["result"] == "not listed" and not out.get("archived") and not rio.puts and len(rio.timeline) == n_tl
      and "projects/arc-nomap" not in wait_keys() and status_of("projects/arc-nomap") == "active", (st, out))

# the pieces on their own
ss = ARC.set_status
check("project_archive.set_status: the status line is replaced in place; a missing one is added before the closing line; every other byte stays", ss("---\ntitle: x\nstatus: active\nowner: y\n---\nbody\n")[0] == "---\ntitle: x\nstatus: archived\nowner: y\n---\nbody\n"
      and ss("---\ntitle: x\n---\nbody status: z\n")[0] == "---\ntitle: x\nstatus: archived\n---\nbody status: z\n")
check("project_archive.set_status: no frontmatter, an unclosed one, two status lines and a status that goes on over a second line are refused, not guessed at", ss("# x\n")[0] is None and ss("---\ntitle: x\n")[0] is None
      and ss("---\nstatus: a\nstatus: b\n---\n")[0] is None and ss("---\nstatus: >-\n  active\n---\n")[0] is None)
real_rs = prj.retired_statuses
try:
    prj.retired_statuses = lambda: {"done", "dropped"}
    check("project_archive.verdict: when 'archived' is not among the configured retired_statuses nothing is written ('unset')", ARC.verdict("---\nagents:\nstatus: active\n---\n", 0, [])[0] == "unset")
finally:
    prj.retired_statuses = real_rs
check("project_archive.verdict: staffed beats waiting (agents on the page and open items: 'staffed'), an empty map and no items archives, a page that never had an agents: key is 'never' (archived only when the tool is asked for --all)",
      ARC.verdict("---\nagents:\n  a-main: x\n---\n", 0, ["a1"])[0] == "staffed" and ARC.verdict("---\nagents:\n  background:\nstatus: active\n---\n", 0, [])[0] == "archive"
      and ARC.verdict("---\ntitle: t\n---\n", 0, [])[0] == "never" and ARC.verdict("---\ntitle: t\n---\n", 0, [], need_map=False)[0] == "archive" and ARC.verdict("---\ntitle: t\n---\n", 0, ["a1"], need_map=False)[0] == "wait")
check("archive: (end) only the project whose sub-page still holds an open item is waiting", wait_keys() == {"projects/arc-hub"}, wait_keys())

# the dry-run tool: projects the rule covers that nothing archived
import importlib.util as _ilu, io as _io, contextlib as _ctx
_spec = _ilu.spec_from_file_location("archive_empty_projects", os.path.join(STACK, "stackshot/tools/archive_empty_projects.py")); AEP = _ilu.module_from_spec(_spec); _spec.loader.exec_module(AEP)
ren_page("projects/arc-late", "type: project\ntitle: arc-late\norg: home\ndisplay-name: home-arc-late\nagents:\n  background:\nstatus: active")          # an emptied map, no item: nothing archived it
ren_page("projects/arc-late-items", "type: project\ntitle: arc-late-items\norg: home\ndisplay-name: home-arc-late-items\nagents:\nstatus: active")      # an emptied map, an open item
ren_page("projects/arc-never", "type: project\ntitle: arc-never\norg: home\ndisplay-name: home-arc-never\nstatus: active")                                  # never had an agents map
ren_page("projects/arc-staffed", "type: project\ntitle: arc-staffed\norg: home\ndisplay-name: home-arc-staffed\nagents:\n  home-arc-staffed-main: talks\nstatus: active")
p.cmd_registry(quiet=True); fresh()
i5 = open_item("projects/arc-late-items")
real_io, real_pio = AEP._page_debt.page_io, AEP._page_debt.page_io
AEP._page_debt.page_io = lambda: rio
try:
    arch, wait, unread = AEP.candidates(rio, prj.registry(), ["projects/arc-late", "projects/arc-late-items", "projects/arc-never", "projects/arc-staffed"], False)
    check("tool: an emptied agents map with no open item is a candidate to archive, one with open items is a waiting one, a staffed page and a page that never had an agents map are neither",
          [r["key"] for r in arch] == ["projects/arc-late"] and [(r["key"], r["items"]) for r in wait] == [("projects/arc-late-items", [f"a{i5}"])] and not unread, (arch, wait, unread))
    arch2, _w2, _u2 = AEP.candidates(rio, prj.registry(), ["projects/arc-never"], True)
    check("tool: --all lists a page that never had an agents map too", [r["key"] for r in arch2] == ["projects/arc-never"], arch2)
    rio.puts.clear(); buf = _io.StringIO()
    with _ctx.redirect_stdout(buf): rc = AEP.main(["projects/arc-late", "projects/arc-late-items"])
    check("tool: the dry run prints the candidates and changes nothing (no put, no wait list entry)", rc == 0 and "archive  projects/arc-late\n" in buf.getvalue() and "wait     projects/arc-late-items" in buf.getvalue()
          and "dry run" in buf.getvalue() and not rio.puts and "projects/arc-late-items" not in wait_keys() and status_of("projects/arc-late") == "active", (rc, buf.getvalue()))
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf): rc = AEP.main(["projects/arc-late", "projects/arc-late-items", "--apply"])
    check("tool: --apply archives the first (one put, status archived) and puts the second on the wait list", rc == 0 and status_of("projects/arc-late") == "archived" and len(rio.puts) == 1 and status_of("projects/arc-late-items") == "active"
          and "projects/arc-late-items" in wait_keys(), (rc, buf.getvalue(), rio.puts, wait_keys()))
    d5 = json.loads(item_file(i5).read_text()); d5["status"] = "completed"; item_file(i5).write_text(json.dumps(d5))
    res = dict(server._archive_tick())
    check("tool: …and the sweep then archives the waiting one once its item is completed", res.get("projects/arc-late-items") == "archived" and status_of("projects/arc-late-items") == "archived", res)
finally:
    AEP._page_debt.page_io = real_pio

if CFG_PA_6F is None: server._cfg.CFG.pop("project_agent", None)
else: server._cfg.CFG["project_agent"] = CFG_PA_6F
server._pform.PAGE_IO = gio


print(("ok" if not fails else "FAILED") + f": projects picker scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
