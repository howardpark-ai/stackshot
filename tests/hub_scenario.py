"""Scenario test for the `hub:` page key and the outside-the-hub note — fixture data, no
live store, no network.

Covers: the registry reads `hub:` (a full key, a bare slug, a sub-page key; ignored when it names the page's own project or no
page); hub_of() follows the nearest such line in a key's chain, one hop; the hubs a session belongs to; the board draws a folded
page's items on its hub's row, labelled hub / page, with the hub's keeper and agents (no "unlisted" for them, still "unlisted"
for a session from elsewhere); create, and an update that changes the owner or the project, note an owner that may not own
the item (a hub with `agents:`: only its user-facing agents, never its keeper or a background agent; a hub with none: its
keeper), naming the owner, the hub and what to do; other updates stay quiet; get shows the same line for the audit; ids and cloud sessions match; a hub with nobody named, or an owner with no known name, gives
no note; the idle pass pokes the hub's keeper. "Refile itself": an item filed outside the one hub its
owner belongs to moves there, on create and on an update that sets the owner or the project, with its History line (the mirror's
comment, the item page's line) and no page owed for it; an owner on no page or several, and a page in the owner's family, stay
as they are; the one-time pass at start moves a wrong open item, leaves a right one, and runs once.

    tests/run-suite hub        → exit 0 / 1"""
import json, os, re, sys, pathlib, tempfile, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="hubtest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), owner=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "brain/infra"): (T / d).mkdir(parents=True)
NAMES = ("falcon", "falcon-main", "falcon-anchors", "harbor-ops", "home-other", "falcon-maintainer")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
page("projects/example.md", "type: project\ntitle: Stackshot\ndisplay-name: falcon\nagents:\n  falcon-main: builds it\n  falcon-anchors: the anchors\n  background:\n    falcon-maintainer: merges and deploys\nstatus: active")
page("projects/example/queue-notes.md", "type: project\ntitle: Queue notes")
page("ops/example-hub.md", "type: note\ntitle: example-hub\ndisplay-name: falcon\nhub: projects/example")
page("ops/example-hub/roster-notes.md", "type: note\ntitle: Roster notes\nagent: falcon-main")
page("ops/bare.md", "type: note\ntitle: Bare\nhub: example")
page("ops/subkey.md", "type: note\ntitle: Subkey\nhub: projects/example/queue-notes")
page("ops/missing.md", "type: note\ntitle: Missing\ndisplay-name: home-other\nhub: projects/nowhere")
page("projects/example/self.md", "type: project\ntitle: Self\nhub: projects/example")
page("projects/other.md", "type: project\ntitle: Other\ndisplay-name: home-other\nstatus: active")
page("projects/ops.md", "type: project\ntitle: Ops\ndisplay-name: harbor-ops\nstatus: active")
page("ops/ops-tool.md", "type: note\ntitle: Ops tool\ndisplay-name: harbor-ops")
page("projects/nobody.md", "type: project\ntitle: Nobody\nstatus: active")
page("projects/cloudy.md", "type: project\ntitle: Cloudy\ndisplay-name: cse_0123456789abcdef\nstatus: active")
# a second hub that lists a front agent of projects/example and a keeper from elsewhere as background agents
page("projects/side.md", "type: project\ntitle: Side\ndisplay-name: home-side\nagents:\n  home-side-main: talks\n  background:\n    falcon-anchors: also sweeps here\n    home-other: runs the side jobs\nstatus: active")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))

# ---- 1. the registry and the rule
from stackshot.projects import pages as p
p.cmd_registry(quiet=True); R = json.loads((T / "store/projects.json").read_text())["pages"]
check("registry: `hub:` with a full key", R["ops/example-hub"].get("hub") == "projects/example", R["ops/example-hub"])
check("registry: a bare slug names a page in the first dir", R["ops/bare"].get("hub") == "projects/example", R["ops/bare"])
check("registry: a sub-page key counts as its top-level page", R["ops/subkey"].get("hub") == "projects/example", R["ops/subkey"])
check("registry: a hub that names no page is ignored", "hub" not in R["ops/missing"], R["ops/missing"])
check("registry: a hub naming the page's own project is ignored", "hub" not in R["projects/example/self"], R["projects/example/self"])
check("registry: a page without the line has no hub key", all("hub" not in R[k] for k in ("projects/example", "ops/example-hub/roster-notes", "projects/other")))
from stackshot.anchors import anchors as A
check("hub_of: a folded page and everything under it", [A.hub_of(k, R) for k in ("ops/example-hub", "ops/example-hub/roster-notes", "ops/example-hub/roster-notes/x")] == ["projects/example"] * 3)
check("hub_of: otherwise the top-level page", [A.hub_of(k, R) for k in ("projects/other", "projects/other/sub", "ops/missing", "projects/example/queue-notes")] == ["projects/other", "projects/other", "ops/missing", "projects/example"])
check("session_hubs: a keeper of a hub and of a page folded into it belongs to one hub", A.session_hubs("falcon", R) == ["projects/example"], A.session_hubs("falcon", R))
check("session_hubs: an agent, by name or id", A.session_hubs("falcon-main", R) == ["projects/example"] and A.session_hubs(U["falcon-main"], R) == ["projects/example"])
check("session_hubs: a background agent too", A.session_hubs("falcon-maintainer", R) == ["projects/example"])
check("session_hubs: harbor-ops", A.session_hubs("harbor-ops", R) == ["ops/ops-tool", "projects/ops"], A.session_hubs("harbor-ops", R))
RL = A.session_roles(R)
check("roles: keeper, front and background from the registry", (RL.get("falcon"), RL.get("falcon-main"), RL.get("falcon-maintainer"), RL.get("home-side"), RL.get("home-side-main"))
      == ({"role": "keeper", "project": "projects/example", "retired": True}, {"role": "front", "project": "projects/example"}, {"role": "back", "project": "projects/example"},
          {"role": "keeper", "project": "projects/side", "retired": True}, {"role": "front", "project": "projects/side"}), RL)   # a page with user-facing agents: its keeper is retired (the router rules every project), whether or not a pane runs under the name
check("roles: front over back — a front agent of one hub listed as background on another stays front, where it is front",
      RL.get("falcon-anchors") == {"role": "front", "project": "projects/example"}, RL.get("falcon-anchors"))
check("roles: back over keeper — a keeper elsewhere listed as background is back, on that hub",
      RL.get("home-other") == {"role": "back", "project": "projects/side"}, RL.get("home-other"))
check("roles: a keeper of several pages is placed on its projects/ page; a cloud keeper by its id; an `agent:` keeper alone has no role",
      RL.get("harbor-ops") == {"role": "keeper", "project": "projects/ops"} and RL.get("cse_0123456789abcdef") == {"role": "keeper", "project": "projects/cloudy"}
      and set(RL) == {"falcon", "falcon-main", "falcon-anchors", "falcon-maintainer", "home-other", "harbor-ops", "home-side", "home-side-main", "cse_0123456789abcdef"}, RL)
FR = A.file_roles(R)
check("roles file: the pane-named only session of an active one-session project is front there",
      FR.get("harbor-ops") == {"role": "front", "project": "projects/ops"}, FR)
check("roles file: a cloud keeper of an active one-session page stays keeper (a cse_ id is no pane)",
      FR.get("cse_0123456789abcdef") == {"role": "keeper", "project": "projects/cloudy"}, FR)
check("roles file: a keeper with user-facing agents keeps its role, though it also keepers a page with none; every other role unchanged",
      FR.get("falcon") == {"role": "keeper", "project": "projects/example", "retired": True} and FR.get("home-side") == {"role": "keeper", "project": "projects/side", "retired": True}
      and {n: r for n, r in FR.items() if n != "harbor-ops"} == {n: r for n, r in RL.items() if n != "harbor-ops"}, FR)
_bg = {"projects/bg": {"session": "home-bg", "role": "name", "agents": {"home-bg-worker": "runs"}, "back_agents": {"home-bg-worker": "runs"}, "status": "active"},
       "projects/solo": {"session": "home-solo", "role": "name", "status": "active"}, "projects/solo/sub": {"session": "home-solo-sub", "role": "agent"},
       "projects/old": {"session": "home-old", "role": "name", "status": "archived"}, "projects/gone": {"session": "home-gone", "role": "name", "status": "done"},
       "projects/chat": {"session": "cse_0123456789abcdeX", "role": "name", "status": "active"},
       "projects/both": {"session": "home-both", "role": "name", "status": "merged"}, "ops/both-tool": {"session": "home-both", "role": "name", "status": "active"}}
check("roles file: a keeper whose page lists only background agents is front too; an `agent:` keeper still has no role",
      {n: A.file_roles(_bg).get(n) for n in ("home-bg", "home-bg-worker", "home-solo", "home-solo-sub")}
      == {"home-bg": {"role": "front", "project": "projects/bg"}, "home-bg-worker": {"role": "back", "project": "projects/bg"},
          "home-solo": {"role": "front", "project": "projects/solo"}, "home-solo-sub": None}, A.file_roles(_bg))
check("roles file: a keeper of an inactive one-session page (archived, done) stays keeper, marked retired (a finished page); a cloud keeper of an active page too",
      {n: A.file_roles(_bg).get(n) for n in ("home-old", "home-gone", "cse_0123456789abcdeX")}
      == {"home-old": {"role": "keeper", "project": "projects/old", "retired": True}, "home-gone": {"role": "keeper", "project": "projects/gone", "retired": True},
          "cse_0123456789abcdeX": {"role": "keeper", "project": "projects/chat"}}, A.file_roles(_bg))
check("roles file: a keeper of an inactive page that also keepers an active one turns front",
      A.file_roles(_bg).get("home-both", {}).get("role") == "front", A.file_roles(_bg).get("home-both"))

# ---- 2. the server's note
from stackshot.service import gates
from stackshot.web import server
from stackshot.projects import project_registry as _projects_registry
server._cfg.CFG.setdefault("model", {})["guards"] = False      # this suite files items under owners the fleet does not know (the note is what it tests); the write guards have their own suite: model_guards
server._publish = lambda: None
def create(project, owner, **kw): return server.stackshot_create(subject="[home] a thing", description="- Goal: A thing\n- It lives here\n- Done when done", project=project, sender=owner, **{"next": f"{owner}: carry on", **kw})
r = create("ops/example-hub", "falcon-anchors"); fold1 = r.split()[1]
check("create: an agent of the hub, on a folded page: no note", "(note:" not in r, r)
r = create("ops/example-hub/roster-notes", "falcon-main"); fold2 = r.split()[1]
check("create: the hub's -main agent, on a sub-page of a folded page: no note", "(note:" not in r, r)
# nothing is "an item's keeper of record" any more, so no create is refused for who made it and no session gets a note about its creator
r = create("ops/example-hub/roster-notes", "falcon"); keeper_out = r.split()[1]
check("create: the keeper of a hub with agents may create an item (the creator is only a History fact)", r.startswith("created") and "(note:" not in r, r)
r = create("ops/example-hub/roster-notes", "falcon-main"); stew_out = r.split()[1]
check("get shows no creator check line, whoever made the item", "keeper of record" not in server.stackshot_get(stew_out), server.stackshot_get(stew_out))
r = create("projects/example", "falcon-maintainer")
check("create: a background agent may create an item (no refusal pointing at needs)", r.startswith("created") and "Refused" not in r and "(note:" not in r, r)
r = create("projects/ops", "harbor-ops")
check("create: a hub not yet converted (no agents:): no note", "(note:" not in r, r)
r = create("projects/example", "harbor-ops"); g_out = r.split()[1]
check("create: a session from elsewhere gets no note naming its hub: the item was created", r.startswith("created") and "(note:" not in r and server._path(g_out).exists(), r)
check("get shows no check line for it either", "keeper of record" not in server.stackshot_get(g_out), server.stackshot_get(g_out))
r = server._update(g_out, next="harbor-ops: carry on\nharbor-ops: a new step", sender="harbor-ops")
check("update: a change that is not a re-filing stays quiet", "(note:" not in r, r)
# the creator is not moved by a hand-over and moves nothing; mover= says who moves the item
_ho_was = server._cfg.CFG["model"].get("handoff"); server._cfg.CFG["model"]["handoff"] = False      # this block is about the creator staying put: the hand-off gate (a live pane) has its own suite
own_of = lambda g: server._load(g)["metadata"]["owner"]
SID = server._session_id
r = create("projects/example", "falcon-main"); h1 = r.split()[1]
r = server._update(h1, project="projects/side", mover="home-side-main", sender="falcon-main")
check("mover: a hand-over to another project's user-facing agent with project= files it there; the creator stays and nothing says keeper of record",
      server._load(h1)["metadata"]["project"] == "projects/side" and own_of(h1) == SID("falcon-main") and "refiled" not in r and "keeper of record" not in r, r)
r = create("projects/example", "falcon-main"); h2 = r.split()[1]
r = server._update(h2, mover="falcon-maintainer", sender="falcon-main")
check("mover: a background agent as mover is the mover; the creator stays", server._load(h2)["metadata"]["mover"] == "falcon-maintainer" and own_of(h2) == SID("falcon-main") and "keeper of record" not in r, r)
r = create("projects/example", "falcon-main"); h3 = r.split()[1]
r = server._update(h3, mover="falcon-anchors", sender="falcon-main")
check("mover: a plain mover change within the project leaves the creator alone", server._load(h3)["metadata"]["mover"] == "falcon-anchors" and own_of(h3) == SID("falcon-main") and "keeper of record" not in r, r)
r = server._update(h3, mover="OLIVER", project="projects/side", sender="falcon-main")
check("mover: Oliver as mover leaves the creator alone, and the project written is the project stored (no refile)", own_of(h3) == SID("falcon-main") and server._load(h3)["metadata"]["project"] == "projects/side" and server._load(h3)["metadata"]["mover"] == server._model.owner_display(), r)
facts_ = json.loads(server._client_item_facts("falcon-anchors", h1 + "," + h3)[2])["items"]
check("item-facts: says who moves each item, and whether it is the asking session (the hook's note on a Board line leaves that session's own item out)",
      facts_[h1]["mover"] == "home-side-main" and facts_[h1]["mover_me"] is False and facts_[h3]["mover"] == server._model.owner_display(), facts_)
r = server._update(h3, mover="falcon-anchors", sender="falcon-main")
facts_ = json.loads(server._client_item_facts("falcon-anchors", h3)[2])["items"][h3]
check("item-facts: the mover that is not in needs is told it moves the item", facts_["mover_me"] is True and facts_["agent"] is False, facts_)
if _ho_was is None: server._cfg.CFG["model"].pop("handoff", None)
else: server._cfg.CFG["model"]["handoff"] = _ho_was
r = server._update(g_out, project="projects/other")
check("update: re-filed under another project: it stays there, nothing refiles it to its creator's project",
      "refiled" not in r and "(note:" not in r and server._load(g_out)["metadata"]["project"] == "projects/other", r)
r = create("projects/example", "11111111-2222-4333-8444-555555555555")
check("a creator with no known name gives no note", "(note:" not in r, r)
r = create("projects/example", "outsider-pane", mover="outsider-pane")
check("a name the fleet does not know creates as before, with no note", r.startswith("created") and "(note:" not in r, r)
r = create("projects/cloudy", "cse_0123456789abcdef", owner_name="A cloud chat")
check("a cloud session may create an item", "(note:" not in r, r)
r = create("projects/nobody", "harbor-ops")
check("a hub that names nobody has nothing to check against", "(note:" not in r, r)
completed = create("projects/example", "harbor-ops").split()[1]; server._update(completed, status="completed", sender="harbor-ops", outcome="done", reason="the work landed", description="- Goal: The test item's work is in place")
check("get on a completed item shows no creator line", "keeper of record" not in server.stackshot_get(completed))
nm = A.names()
check("keeper: a folded page with no keeper of its own is kept by the hub's keeper (its builder, not the retired name-line session)", server._keeper("ops/bare", U["harbor-ops"]) == "falcon-maintainer", server._keeper("ops/bare", U["harbor-ops"]))
check("keeper: a page's own top-level keeper otherwise", server._keeper("projects/other/x", U["harbor-ops"]) == "home-other")

# ---- 2b. roles.json, the `roles` read, the sessions tool's role
import time as _t, inspect
t0 = _t.time(); RJ = T / "state/roles.json"
_rep = []; _orig_replace = os.replace
os.replace = lambda a, b: (_rep.append((str(a), str(b))), _orig_replace(a, b))[1]
w1 = _projects_registry._roles_sync(now=t0); os.replace = _orig_replace
j = json.loads(RJ.read_text())
check("roles.json: written to the state dir with a UTC Z stamp and every role, as file_roles has them", w1 and _projects_registry.ROLES == RJ and j["sessions"] == FR and j["sessions"]["harbor-ops"]["role"] == "front" and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", j["generated"]), j)
check("roles.json: atomically, a temp file beside it replaced onto it, none left behind",
      [x for x in _rep if x[1] == str(RJ)] == [(str(T / "state/.roles.json.tmp"), str(RJ))] and not (T / "state/.roles.json.tmp").exists(), _rep)
check("roles.json: unchanged and fresh → not rewritten", _projects_registry._roles_sync(now=t0 + 60) is False and json.loads(RJ.read_text()) == j)
page("projects/side.md", "type: project\ntitle: Side\ndisplay-name: home-side\nagents:\n  home-side-main: talks\n  home-side-docs: writes\n  background:\n    falcon-anchors: also sweeps here\n    home-other: runs the side jobs\nstatus: active")
p.cmd_registry(quiet=True)
check("roles.json: rewritten when the registry's roles change", _projects_registry._roles_sync(now=t0 + 120) is True
      and json.loads(RJ.read_text())["sessions"].get("home-side-docs") == {"role": "front", "project": "projects/side"}, RJ.read_text()[:300])
g1 = json.loads(RJ.read_text())["generated"]
check("roles.json: no rewrite before 30 min with nothing changed", _projects_registry._roles_sync(now=t0 + 120 + 29 * 60) is False and json.loads(RJ.read_text())["generated"] == g1)
check("roles.json: refreshed with a new stamp at 30 min though nothing changed (a reader calls a file over an hour old stale)",
      _projects_registry._roles_sync(now=t0 + 120 + 31 * 60) is True and json.loads(RJ.read_text())["generated"] != g1)
_stale = json.loads(RJ.read_text()); _stale["generated"] = "2026-01-01T00:00:00Z"; RJ.write_text(json.dumps(_stale))
server._roles_sync_safe()
check("roles.json: a stale file is refreshed by the pass the runner runs every minute (with the board held too)", json.loads(RJ.read_text())["generated"] > "2026-01-02"
      and [(t.group, t.board) for t in server._minute_ticks() if t.name == "roles_sync_safe"] == [("fleet", False)] and "_roles_sync_safe()" in inspect.getsource(server._publish_now), json.loads(RJ.read_text())["generated"])
st, ct, body = server._client_get("roles", {})
check("client read `roles`: the file as written", (st, ct) == (200, "application/json") and body == RJ.read_text() and json.loads(body)["sessions"]["home-side-main"]["role"] == "front", (st, ct, body[:200]))
from stackshot.fleet import client as _client
check("client.py knows the read", "roles" in _client.READS)
check("the server's own gates keep session_roles: a one-session project's keeper may be named in needs, takes messages unmarked, "
      "and is no front agent for its notices", gates.gate_needs_session("harbor-ops", "projects/ops", "falcon-main") == "harbor-ops"
      and server._front_keeper("harbor-ops", "projects/ops") == (False, "") and server._gate_front("harbor-ops", "a plain note", server._sessions_index()) is None)
ls = server._sessions_listing("").split("\n")
row = lambda n: next((l for l in ls if l.startswith(f"- {n} — ")), "")
check("sessions tool: each session's role and project", row("falcon-anchors").endswith(" · testbox · front agent of projects/example")
      and row("falcon").endswith(" · testbox · keeper of projects/example") and row("falcon-maintainer").endswith(" · testbox · background agent of projects/example")
      and row("home-other").endswith(" · testbox · background agent of projects/side"), [l for l in ls if l.startswith("- ")])
check("sessions tool: the only session of a one-session project reads front there, as roles.json has it; "
      "a project's real keeper still reads keeper; session_roles, which the gates read, still holds it as keeper",
      row("harbor-ops").endswith(" · testbox · front agent of projects/ops") and row("falcon").endswith(" · testbox · keeper of projects/example")
      and A.session_roles().get("harbor-ops") == {"role": "keeper", "project": "projects/ops"}, [row("harbor-ops"), A.session_roles().get("harbor-ops")])

# ---- 3. the board
from stackshot.web import render
bd = render.Board(f"{tmp}/store")
rows = set(bd.by_proj)
check("board: no row for the folded page; its items sit on the hub's row", "ops/example-hub" not in rows and "projects/example" in rows
      and {r["gid"] for r in bd.by_proj["projects/example"] if r["metadata"]["project"].startswith("ops/example-hub")} == {fold1, fold2, stew_out, keeper_out}, [(r["gid"], r["metadata"]["project"]) for r in bd.by_proj["projects/example"]])
check("board: the card labels it scope/hub/page", bd.proj_label("ops/example-hub") == "home/example/example-hub", bd.proj_label("ops/example-hub"))
bd.proj.update({"ops/gen": {"name": "gen"}, "ops/gen/sub": {}, "ops/gen/sub/deep": {}, "ops/gen/named": {"name": "Named"}})
check("board: an unnamed sub-page is labelled by its path below the row, never the row twice",
      [bd.proj_label(k) for k in ("ops/gen/sub", "ops/gen/sub/deep", "ops/gen/named", "ops/gen")] == ["ops/gen/sub", "ops/gen/sub/deep", "ops/gen/Named", "ops/gen"],
      [bd.proj_label(k) for k in ("ops/gen/sub", "ops/gen/sub/deep", "ops/gen/named", "ops/gen")])
ls = {x[0].split("/", 1)[-1]: x for x in bd._lines("projects/example", bd.by_proj["projects/example"])[1]}
check("board: the row's keeper and agents are the hub's, none flagged", ls.get("falcon", [""] * 6)[5] == "" and ls.get("falcon-anchors", [""] * 6)[5] == "" and bd.keeper_split("projects/example", [])[0][0].endswith("/falcon"), ls)
check("board: a session from elsewhere is still \"unlisted\" on the row", ls.get("outsider-pane", [""] * 6)[5] == "unlisted", ls)
check("board: the folded page's group sits in the hub's group (its anchors join the row)", "ops/example-hub" in bd.group.get("projects/example", []) and "ops/example-hub" not in bd.group, bd.group)

print(("ok" if not fails else "FAILED") + f": hub scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
