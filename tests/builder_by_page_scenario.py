"""Scenario test for: a new item goes to the builder of its area — fixture data, no live store, no network.

Covers: `[handoff.builder_by_page]` maps a project page key to a background agent of the project. The DEFAULT hand-off of an item with no mover (telling.fallback_mover, which the item model
and the notices read) goes to the mapped builder when the item is filed on the mapped page or on a page under it (a prefix at a page boundary, the longest key first), and only when that
agent is listed on the item's project as a background agent; an unmapped page, a mapped agent the project does not list, and an empty, missing or malformed map all keep the first
builder, never an error. An explicit mover on a create always wins. The example config carries the table only as a comment, and the docs and create's description say so.

    tests/run-suite builder_by_page        → exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="builderbypage-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's fleet store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state", "brain/projects"): (T / d).mkdir(parents=True)
MAIN, CORE, SCREEN, OTHER, MAIN2, CORE2 = "home-delta-main", "home-delta-core", "home-delta-screens", "home-delta-other", "home-echo-main", "home-echo-core"
NAMES = (MAIN, CORE, SCREEN, OTHER, MAIN2, CORE2)
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in U.items()}))
page = lambda **kw: {"title": "T", "name": "T", "org": "home", "tags": [], "type": "project", "session": "", "status": "active", "board": [], "board_open": 0, **kw}
# delta lists two builders (CORE first, SCREEN second) and a background agent whose mandate does not build; echo lists one builder and not SCREEN
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/delta": page(title="Delta", name="Delta", agents={MAIN: "front", CORE: "builds the core", SCREEN: "builds the screens", OTHER: "answers questions"},
                           back_agents={CORE: "builds the core", SCREEN: "builds the screens", OTHER: "answers questions"}),
    "projects/delta/ui": page(title="Ui", name="Ui"), "projects/delta/ui/panel": page(title="Panel", name="Panel"),
    "projects/delta/uikit": page(title="Uikit", name="Uikit"), "projects/delta/core": page(title="Core", name="Core"),
    "projects/echo": page(title="Echo", name="Echo", agents={MAIN2: "front", CORE2: "builds it"}, back_agents={CORE2: "builds it"}),
    "projects/echo/ui": page(title="Ui", name="Ui")}}))
(T / "store/next-id").write_text("40"); (T / "store/anchors.json").write_text("{}")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))
def rd(g):
    g = str(g); g = g if not g[:1].isdigit() else "a" + g
    return json.loads((T / f"store/{g[0]}/{g[1:]}.json").read_text())

from stackshot.web import server
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.tools import create as _wt_create
from stackshot.service import telling
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
telling.tell_woken = lambda *a, **k: None
DESC = "- Goal: A thing\n- It lives here\n- Done when done"

def conf(table):
    """Set (or remove, with None) the map, as a reload would, and drop the fallback cache the board keeps for a few seconds."""
    if table is None:
        server._cfg.CFG.pop("handoff", None)
    else:
        server._cfg.CFG["handoff"] = {"builder_by_page": table}
    telling.FALLBACK_CACHE.clear()

def filed(project, n, **kw):
    """Create an item on `project` with no mover (the creator is the project's first builder) -> the session that holds it."""
    r = _wt_create.stackshot_create(subject=f"[home] filed {n}", description=DESC, project=project, sender=CORE if project.startswith("projects/delta") else CORE2,
                                next=f"{CORE if project.startswith('projects/delta') else CORE2}: look at it", **kw)
    assert r.startswith("created"), r
    return telling.holder(rd(r.split()[1]))

MAP = {"projects/delta/ui": SCREEN, "projects/echo/ui": SCREEN}

# ---- the default: no map
conf(None)
check("no [handoff] section: an item on the page goes to the first builder", filed("projects/delta/ui", 1) == CORE, filed("projects/delta/ui", 1))
conf({})
check("an empty map is today's behaviour", filed("projects/delta/ui", 2) == CORE)
for odd in ("not a table", ["projects/delta/ui"], {"projects/delta/ui": 7, "": SCREEN, 5: SCREEN}):
    conf(odd)
    check(f"a malformed map ({odd!r}) reads as empty: the first builder", filed("projects/delta/ui", 3) == CORE and server._builder_by_page() == {}, server._builder_by_page())
server._cfg.CFG["handoff"] = "not a table"; telling.FALLBACK_CACHE.clear()
check("a [handoff] that is not a table reads as empty", server._builder_by_page() == {} and telling.fallback_mover("projects/delta/ui") == CORE)

# ---- the map
conf(MAP)
check("the config reads back as the map", server._builder_by_page() == MAP, server._builder_by_page())
check("an item filed on the mapped page goes to its mapped builder", filed("projects/delta/ui", 4) == SCREEN)
check("an item filed on a sub-page of the mapped page goes to its mapped builder too", filed("projects/delta/ui/panel", 5) == SCREEN)
check("an unmapped page goes to the first builder", filed("projects/delta/core", 6) == CORE)
check("the project's own page, unmapped, goes to the first builder", filed("projects/delta", 7) == CORE)
check("a prefix is matched at a page boundary: ui is not uikit", filed("projects/delta/uikit", 8) == CORE)
check("a mapped builder the project does not list falls back to the first builder, with no error", filed("projects/echo/ui", 9) == CORE2)
check("the default mover read directly agrees", (telling.fallback_mover("projects/delta/ui/panel"), telling.fallback_mover("projects/delta/core"), telling.fallback_mover("projects/echo/ui"))
      == (SCREEN, CORE, CORE2), (telling.fallback_mover("projects/delta/ui/panel"), telling.fallback_mover("projects/delta/core"), telling.fallback_mover("projects/echo/ui")))

# the longest key wins; a key whose agent is not listed leaves the shorter one standing
conf({"projects/delta": OTHER, "projects/delta/ui": SCREEN})
check("the longest matching key wins", telling.fallback_mover("projects/delta/ui/panel") == SCREEN and telling.fallback_mover("projects/delta/core") == OTHER)
conf({"projects/delta": SCREEN, "projects/delta/ui": CORE2})
check("a longer key naming an agent the project does not list leaves the shorter key's builder", telling.fallback_mover("projects/delta/ui") == SCREEN)
conf({"projects/delta/ui/": SCREEN, " projects/delta/core ": OTHER})
check("a key's stray slashes and spaces are dropped", telling.fallback_mover("projects/delta/ui/panel") == SCREEN and telling.fallback_mover("projects/delta/core") == OTHER)
conf({"projects/delta/ui": MAIN})
check("a front agent is no builder of the project: the first builder takes the item", telling.fallback_mover("projects/delta/ui") == CORE)
conf({"projects/delta/ui": "home-ghost-core"})
check("a mapped agent no page lists falls back to the first builder", telling.fallback_mover("projects/delta/ui") == CORE)

# ---- an explicit mover wins
conf(MAP)
r = _wt_create.stackshot_create(subject="[home] named mover", description=DESC, project="projects/delta/ui", sender=CORE, mover=OTHER, next=f"{OTHER}: look at it")
check("an explicit mover on a create wins over the map", r.startswith("created") and telling.holder(rd(r.split()[1])) == OTHER, r)
r = _wt_create.stackshot_create(subject="[home] named first builder", description=DESC, project="projects/delta/ui", sender=CORE, mover=CORE, next=f"{CORE}: look at it")
check("…even when it names the project's first builder", r.startswith("created") and telling.holder(rd(r.split()[1])) == CORE, r)

# ---- the same default serves the `then` of an item that waits on a call
check("an item that waits on a call takes the mapped agent as its then when next names it", server._owner_then("projects/delta/ui", "", CORE, f"{SCREEN}: build it", []) == SCREEN)
check("…and the first builder on an unmapped page", server._owner_then("projects/delta/core", "", MAIN, f"{CORE}: build it", []) == CORE)

# ---- the shipped texts
ex = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
live = [l for l in ex.splitlines() if re.match(r"\s*\[handoff", l)]
check("the example config holds the table only as a comment", not live and "# [handoff.builder_by_page]" in ex, live)
check("the example config has no uncommented entry for it", not any(re.match(r'\s*"projects/[^"]*"\s*=', l) for l in ex.splitlines()))
import _docs
rm = _docs.page("configuration-integrations")
check("the docs say how to set it", "`handoff.builder_by_page`" in rm and "[handoff.builder_by_page]" in _docs.page("item-model") and "falls back to the first builder" in rm)
_cdecl = _wt_create._CREATE_DESC
check("create's description names the mapped builder", "for a page the instance maps to a builder, that one when the project lists it" in _cdecl, _cdecl[:200])
check("the tool-text snapshot carries it", "for a page the instance maps to a builder, that one when the project lists it" in pathlib.Path(SCR, "tool_text.snapshot.json").read_text(encoding="utf-8"))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.stdout.flush()
os._exit(1 if fails else 0)
