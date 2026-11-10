"""Scenario test for the board's session lists on roles.json's live flag — fixture data, no live store, no network, no server process (the render
module is imported and called in-process, on a temporary config).

Covers: an agent whose live flag is false is not drawn in a project page's Sessions section (a hub's agents and background agents, and a project's
single session) nor on the index; one whose flag is true is; a name roles.json does not know, and a roles.json written while sala could not be read
(no flag anywhere), hide nothing; an agent that owns an open item stays on the index whatever its flag; the agents of an archived project (its page
status is one of retired_statuses) are drawn inside a `<details>` group titled "Archived" that starts closed, on the project page, and on the index as the foldable Archived group (home's heading, count and fold);
and the project listing the picker reads is unchanged by the flag.

    tests/run-suite agent_live_view        → exit 0 / 1"""
import json, os, re, sys, pathlib, logging, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="livetest-"); T = pathlib.Path(tmp)
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
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "brain/infra", "secrets"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
NAMES = ("work-live-main", "work-live-docs", "work-live-idle", "work-live-bot", "work-live-gone", "work-solo", "work-done-main", "work-done-docs")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in U.items()}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

page("projects/live.md", "type: project\ntitle: Live proj\ndisplay-name: work-live\nagents:\n  work-live-main: talks to the owner\n  work-live-docs: keeps the docs\n  work-live-idle: has no session\n"
                         "  background:\n    work-live-bot: sweeps\n    work-live-gone: has no session either\nstatus: active")
page("projects/solo.md", "type: project\ntitle: Solo proj\ndisplay-name: work-solo\nstatus: active")
page("projects/done.md", "type: project\ntitle: Done proj\ndisplay-name: work-done\nagents:\n  work-done-main: was the contact\n  work-done-docs: kept the docs\nstatus: archived")
from stackshot.projects import pages as p; from stackshot.anchors import anchors as _A; from stackshot.projects import projects as prj
from stackshot.web.ui import render as ui_render
p.cmd_registry(quiet=True)
now = time.time()
def item(n, proj, owner):
    (T / f"store/a/{n}.json").write_text(json.dumps({"id": n, "subject": f"[home] item {n}", "status": "open", "description": "x", "created": now, "updated": now,
                                                     "metadata": {"project": proj, "owner": U[owner], "mover": U[owner]}}))
item(901, "projects/live", "work-live-main"); item(902, "projects/live", "work-live-gone")      # work-live-gone owns an open item although it has no session
item(903, "projects/solo", "work-solo"); item(904, "projects/done", "work-done-main")
ROLES = T / "state/roles.json"
def roles(flags):
    """roles.json as the server writes it, `live` as given ({name: bool or None for no flag}); None = no file."""
    if flags is None:
        ROLES.unlink(missing_ok=True); return
    ROLES.write_text(json.dumps({"generated": "2026-11-01T00:00:00Z", "sessions": {n: {"role": "front", "project": "x"} | ({} if v is None else {"live": v}) for n, v in flags.items()}}))
def board(): return ui_render.Board(f"{tmp}/store")
def text(h): return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", h))
def index_of(bd):
    return bd.projects_table()

# ---- the flag's reader
roles({"a": True, "b": False, "c": None}); check("roles_live: a boolean per name, a name with no flag left out", _A.roles_live() == {"a": True, "b": False}, _A.roles_live())
roles(None); check("roles_live: no file gives {}", _A.roles_live() == {})
ROLES.write_text("not json"); check("roles_live: a damaged file gives {}", _A.roles_live() == {})

# ---- a hub project page
LIVE = {"work-live-main": True, "work-live-docs": True, "work-live-idle": False, "work-live-bot": True, "work-live-gone": False}
roles(LIVE); bd = board(); n, h = bd.sessions_html("projects/live")
check("project page: an agent whose live flag is false is not drawn (a front and a background one)", "work-live-idle" not in h and "work-live-gone" not in h, text(h))
check("project page: an agent whose live flag is true is drawn", all(x in h for x in ("work-live-main", "work-live-docs", "work-live-bot")), text(h))
check("project page: the Sessions count is the drawn ones", n == 3, n)
check("project page: an active project has no Archived group", "Archived" not in h and "<details" not in h, h)
check("picker listing: still carries every agent of the project (the flag hides nothing there)", set(prj.ref("projects/live")["agents"]) == set(LIVE), prj.ref("projects/live")["agents"])
roles({**LIVE, "work-live-idle": True}); h2 = board().sessions_html("projects/live")[1]
check("project page: the same agent is drawn once its flag turns true", "work-live-idle" in h2, text(h2))
roles(None); n3, h3 = board().sessions_html("projects/live")
check("no roles.json: nothing is hidden", n3 == 5 and all(x in h3 for x in LIVE), (n3, text(h3)))
roles({k: None for k in LIVE}); n4, h4 = board().sessions_html("projects/live")
check("a roles.json written while sala could not be read (no flag anywhere): nothing is hidden", n4 == 5 and all(x in h4 for x in LIVE), (n4, text(h4)))
roles({"work-live-main": True}); n5, h5 = board().sessions_html("projects/live")
check("a name roles.json does not know is shown", n5 == 5, (n5, text(h5)))

# ---- a project without an agents map
roles({"work-solo": False}); n6, h6 = board().sessions_html("projects/solo")
check("single-session project: a session whose live flag is false is not drawn", n6 == 0 and "work-solo" not in h6, (n6, text(h6)))
roles({"work-solo": True}); n7, h7 = board().sessions_html("projects/solo")
check("single-session project: a session whose live flag is true is drawn", n7 == 1 and "work-solo" in h7, (n7, text(h7)))

# ---- an archived project: its agents sit in a closed "Archived" group
roles({"work-done-main": True, "work-done-docs": False}); n8, h8 = board().sessions_html("projects/done")
check("archived project page: the live agents sit inside a details group titled Archived, closed by default", n8 == 1 and h8.startswith('<details class="archived"><summary>Archived') and h8.endswith("</details>")
      and "open" not in re.match(r"<details[^>]*>", h8).group(0) and "work-done-main" in h8, text(h8))
check("archived project page: its agent with no live session is not drawn either", "work-done-docs" not in h8, text(h8))
roles(None); n9, h9 = board().sessions_html("projects/done")
check("archived project page: with no flags both agents are in the one group", n9 == 2 and h9.count("<details") == 1 and "work-done-docs" in h9 and h9.index("<summary>Archived") < h9.index("work-done-main"), text(h9))
roles({"work-done-main": False, "work-done-docs": False}); n10, h10 = board().sessions_html("projects/done")
check("archived project page: with no live agent there is no empty group", n10 == 0 and "<details" not in h10, h10)

# ---- the Projects page table
roles({**LIVE, "work-done-main": True, "work-done-docs": False}); bd = board(); sec = index_of(bd)
names = {x[0].split("/", 1)[-1] for x in bd.index_lines("projects/live", bd.by_proj.get("projects/live", []))}
check("index_lines: live agents and the owner of an open item are kept, a not-live agent that owns nothing is dropped", "work-live-main" in names and "work-live-gone" in names and "work-live-idle" not in names, names)
check("index: a not-live agent that owns nothing is absent", "work-live-idle" not in sec, text(sec)[:500])
AH = '<details class="fold sfold" data-fold="projects.archived"><summary><h3 class="iscope">Archived <span class="count">1</span></h3></summary>'
check("index: the archived project sits in one closed Archived fold (home's heading and count), after the active projects", sec.count(AH) == 1
      and sec.index(AH) < sec.index(">work-done-main<") and sec.index(">work-live-main<") < sec.index(AH) and sec.index(">work-solo<") < sec.index(AH), text(sec)[:600])
check("index: the group is not open", not re.search(r'<details class="fold sfold" data-fold="projects.archived"[^>]*\bopen', sec))
check("index: the markup stays balanced (details and tables)", sec.count("<details") == sec.count("</details>") and sec.count("<table") == sec.count("</table>"), (sec.count("<details"), sec.count("</details>"), sec.count("<table"), sec.count("</table>")))
roles(None); sec2 = index_of(board())
check("index: with no flags the unlisted-live agents show as before, and the Archived group is still there", "work-live-idle" in sec2 and sec2.count(AH) == 1, text(sec2)[:400])
(T / "store/a/904.json").unlink(); (T / "brain/projects/done.md").unlink(); p.cmd_registry(quiet=True)      # the archived project goes: its item and its page
sec3 = index_of(board())
check("index: with no archived project on it there is no Archived group", "Archived" not in sec3, text(sec3)[:300])

print(("ok" if not fails else "FAILED") + f": agent live view scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
