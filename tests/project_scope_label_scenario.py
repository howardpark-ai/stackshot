"""Scenario test for a project's scope in its board name — fixture data, no live store, no network.

Covers: projects.scoped_name (scope, a slash, the name; a name that has the scope already is left alone; no scope leaves the name); projects.label_scope ("" for a
single-scope instance, an empty key); both Boards (render.py's text board, ui/render.py's pages) show `<scope>/<name>` for a project (`home/ledger`, `ops/ledger`,
`work/Ledger`: the same name on three scopes reads apart), `<scope>/<row>/<path below the row>` for an unnamed sub-page (`ops/hubkit/sharing/sub-host`, plain slashes) and
`<scope>/<row>/<name>` for a named one; a scope set on purpose (a mark in the id file) wins over the derived one; the Projects page links the scoped name; a single-scope
instance shows the plain name. What is stored is never touched: the page's `display-name:` line, the registry's `session` (the prefix of its agents' session names), the keys.

    tests/run-suite project_scope_label        → exit 0 / 1"""
import json, os, re, sys, pathlib, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="scopelabel-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"), owner=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
import re as _re
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = _re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/example-hub", "brain/projects", "brain/ops"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"})); (T / "fleet/a/sessions.json").write_text("{}")
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
# the same name "ledger" on three scopes, as one brain can have it; a project whose scope the session prefix gives; its unnamed and named sub-pages
page("projects/ledger.md", "type: project\ntitle: Personal ledger\norg: home\nname: ledger\ndisplay-name: home-ledger\nstatus: active")
page("ops/ledger.md", "type: project\ntitle: Fleet ledger\norg: home\nname: ledger\ndisplay-name: ops-ledger\nstatus: active")
page("ops/ledger/tide-tables.md", "type: note\ntitle: Tide tables page\nname: Tide tables")
page("projects/work-ledger.md", "type: project\ntitle: Work ledger\norg: work\nname: Ledger\ndisplay-name: work-ledger\nstatus: active")
page("projects/hubkit.md", "type: project\ntitle: hubkit\norg: home\nname: hubkit\ndisplay-name: ops-hubkit\nstatus: active")
page("projects/hubkit/sharing.md", "type: project\ntitle: Sharing")
page("projects/hubkit/sharing/sub-host.md", "type: project\ntitle: Sub host")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))

import projects as prj, pages as p
# ---- 1. the pure parts
check("scoped_name: scope, a slash, the name", prj.scoped_name("ops", "ledger") == "ops/ledger" and prj.scoped_name("work", "Ledger") == "work/Ledger")
check("scoped_name: a name that has the scope already, no scope and no name are left alone",
      prj.scoped_name("ops", "ops/ledger") == "ops/ledger" and prj.scoped_name("", "ledger") == "ledger" and prj.scoped_name("ops", "") == "")
check("label_scope: an empty key has none", prj.label_scope("", {}, {}) == "")

# ---- 2. the boards
p.cmd_registry(quiet=True); R = json.loads((T / "store/projects.json").read_text())["pages"]
import render, ui.render as r2
store = str(T / "store")
def labels(Bd):
    bd = Bd(store)
    return bd, {k: bd.proj_label(k) for k in ("projects/ledger", "ops/ledger", "projects/work-ledger", "projects/hubkit", "projects/hubkit/sharing/sub-host", "ops/ledger/tide-tables")}
want = {"projects/ledger": "home/ledger", "ops/ledger": "ops/ledger", "projects/work-ledger": "work/Ledger", "projects/hubkit": "ops/hubkit",
        "projects/hubkit/sharing/sub-host": "ops/hubkit/sharing/sub-host", "ops/ledger/tide-tables": "ops/ledger/Tide tables"}
for mod, Bd in (("render.py", render.Board), ("ui/render.py", r2.Board)):
    bd, got = labels(Bd)
    check(f"{mod}: the same name on three scopes reads apart; a sub-page keeps its path or name behind the project's, with plain slashes", got == want, got)
    check(f"{mod}: proj_title is the scoped name, proj_name the bare one", bd.proj_title("projects/hubkit") == "ops/hubkit" and bd.proj_name("projects/hubkit") == "hubkit"
          and bd.proj_title("") == "no project" and bd.label_scope("projects/not-a-page") == "", (bd.proj_title("projects/hubkit"), bd.proj_title("")))
    check(f"{mod}: no label puts a space around its slashes", all(" / " not in v for v in got.values()), got)

# ---- 3. what is stored stays
check("the registry's session (the prefix of the agents' session names) and the page's display-name line are as written",
      R["projects/hubkit"].get("session") == "ops-hubkit" and R["projects/ledger"].get("session") == "home-ledger" and R["ops/ledger"].get("session") == "ops-ledger"
      and "display-name: ops-hubkit" in (T / "brain/projects/hubkit.md").read_text(), (R["projects/hubkit"].get("session"), R["projects/ledger"].get("session")))

# ---- 4. the Projects page, the project page and the landed scope
bd = r2.Board(store)
tbl = bd.projects_table()
check("the Projects page links each project by its scoped name", all(f">{n}</a>" in tbl for n in ("home/ledger", "ops/ledger", "work/Ledger", "ops/hubkit")), re.findall(r'class="proj">(.*?)</td>', tbl)[:6])
check("landed_scope reads the same scope the label does", bd.landed_scope("projects/hubkit")[0] == "ops" and bd.landed_scope("projects/ledger")[0] == "home", (bd.landed_scope("projects/hubkit"), bd.landed_scope("projects/ledger")))

# ---- 5. a scope set on purpose wins over the derived one
pid = prj.ids_by_key()["projects/ledger"]; prj.set_mark(pid, scope="work")
check("a scope set on purpose (a mark in the id file) is the label's scope", r2.Board(store).proj_label("projects/ledger") == "work/ledger" and render.Board(store).proj_label("projects/ledger") == "work/ledger",
      r2.Board(store).proj_label("projects/ledger"))
prj.set_mark(pid, scope=None)

# ---- 6. a single-scope instance shows the plain name
_scopes = prj.scopes
prj.scopes = lambda: ["only"]
try:
    b1, b2 = r2.Board(store), render.Board(store)
    check("an instance with one scope shows the plain names", b1.proj_label("projects/hubkit/sharing/sub-host") == "hubkit/sharing/sub-host" and b2.proj_title("ops/ledger") == "ledger"
          and b1.proj_label("ops/ledger/tide-tables") == "ledger/Tide tables", (b1.proj_label("projects/hubkit/sharing/sub-host"), b2.proj_title("ops/ledger")))
finally: prj.scopes = _scopes

if fails: print(f"FAILED: project scope label scenario, {len(ran)} checks, {len(fails)} failed"); sys.exit(1)
print(f"ok: project scope label scenario, {len(ran)} checks")
