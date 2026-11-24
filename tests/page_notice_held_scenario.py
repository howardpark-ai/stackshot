"""Scenario test for the hold decision of a page's notice when the session registry cannot be read for a moment — fixture data, no live store, no network, no server process
(the hub's send is called in-process, delivery is stubbed, the registry is a fixture file in a temporary directory, never the host's).

A page's notices are the router's to rule: the hub holds one for the router (`Hub.send`, router_live.holds) when the session the route names is the page's notice address.
The route names the session by its permanent id (anchors.routes puts every address through anchors.canonical), and `holds` puts the route's session and the page's
notice address through the same canonical form again. While the registry reads empty (the copy of it on a server box being replaced, a torn read) the two sides were
put through different rules: the route's permanent id stayed an id, the page's name became the name's transcript id, the two differed, and the notice went straight
to the session instead of being held.

Covers: a notice on a page whose route names the keeper by its permanent id is held for the router, with the registry readable and with it gone; the same notice through
a burst's follow-up and through the unreadable-anchor warning; a route that names another session (a builder) is delivered to it with the registry gone as with it
readable; a route whose keeper was replaced on the page since the routes were made (the page names another session now) is not held, with the registry gone as with it readable.

    tests/run-suite page_notice_held        → exit 0 / 1"""
import json, os, re, sys, pathlib, logging, types
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="pnheld-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = ""', f'session_links = "{tmp}/sala"', 1); assert f'session_links = "{tmp}/sala"' in toml   # the fixture registry, never the host's store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
for d in ("store/a", "fleet/a", "brain/projects", "sala/a"): (T / d).mkdir(parents=True)
SALA = T / "sala/a/session-registry.json"

def uid(n): return f"00000000-0000-4000-8000-{n:012d}"
PERM = {"main": uid(101), "builder": uid(102), "other": uid(103)}          # the permanent ids
TRANS = {"main": uid(201), "builder": uid(202), "other": uid(203)}         # the transcripts the panes run now
NAME = {"main": "alpha-main", "builder": "alpha-builder", "other": "beta-main"}
def row(k):
    return {"id": PERM[k], "name": NAME[k], "aliases": [], "project": None, "project_key": None, "role": None, "lane": "max", "model": "opus", "effort": "medium", "pane": NAME[k],
            "cwd": "/work/dir", "state": "live", "created": "2026-10-21T21:00:00Z", "retired_at": None, "transcripts": [{"id": TRANS[k], "machine": "a", "at": "2026-10-21T21:00:00Z", "why": "import"}]}
def put_registry():
    tmp_ = SALA.with_name(".r.tmp"); tmp_.write_text(json.dumps({"schema": 1, "machine": "a", "written": "2026-10-22T07:00:00Z", "sessions": {PERM[k]: row(k) for k in PERM}}), encoding="utf-8"); os.replace(tmp_, SALA)
def drop_registry(): SALA.unlink(missing_ok=True)      # what a reader sees while another process replaces the copy of it
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True}}))
(T / "fleet/a/sessions.json").write_text(json.dumps({TRANS[k]: {"name": NAME[k], "machine": "a", "url": "", "seen": "2026-10-22T07:00:00Z"} for k in TRANS}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
page("projects/alpha.md", "type: project\ntitle: Alpha\ndisplay-name: alpha-main\nagents:\n  alpha-main: talks to the owner\n  background:\n    alpha-builder: builds and merges\nstatus: active")
page("projects/beta.md", "type: project\ntitle: Beta\ndisplay-name: beta-main\nstatus: active")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

from stackshot.projects import pages as p
p.cmd_registry(quiet=True)
from stackshot.fleet import sessions_registry as sr
from stackshot.anchors import anchors as A
from stackshot.router import routing
from stackshot.router import router_live as live
from stackshot.anchors.anchorhub import core
sr.TTL = 0          # the directory is looked at on every call here: the test removes and rewrites the registry at once (production trusts a look for a second)
put_registry(); sr.reset()

hub = core.Hub(); out = []
hub.deliver = lambda anchor, session, text: out.append((anchor, session, text)); hub.write_status = lambda: None
ev = types.SimpleNamespace(label="Slack anchor", who="Dana", url="https://u/1", text="a notice", etype="", head="", author="")
def route(session, project="projects/alpha"): return [{"project": project, "session": session, "target": "project-wide", "pilot": True, "filter": ""}]
def sent(anchor, session, project="projects/alpha", routes=None):
    """One notice through Hub.send; (the deliveries it made, the routing line it wrote)."""
    out.clear(); core._ROUTES.clear(); core._ROUTES[anchor] = routes or route(session, project)
    hub.send(anchor, session, f"[anchor] a notice on {anchor}", ev, "a notice")
    return list(out), routing.read(project)[-1]

check("the page's notice address is the name line, the route names it by its permanent id", A.notice_name("projects/alpha") == "alpha-main" and A.canonical("alpha-main") == PERM["main"], A.canonical("alpha-main"))
d, n = sent("slack:C0000000001", PERM["main"])
check("registry readable: the keeper's notice is held for the router, delivered to nobody", d == [] and n["live"] is True and n["to"] == "", (d, n))
check("registry readable: holds() agrees", live.holds("projects/alpha", PERM["main"]) is True)

drop_registry(); sr.reset()
check("the registry reads empty now (no row resolves)", not sr.available() and sr.resolve("alpha-main") is None)
check("registry gone: holds() still says the keeper's permanent id is the page's notice address", live.holds("projects/alpha", PERM["main"]) is True)
d, n = sent("slack:C0000000002", PERM["main"])
check("registry gone: the keeper's notice is held for the router, delivered to nobody", d == [] and n["live"] is True and n["to"] == "", (d, n))
d, n = sent("slack:C0000000003", PERM["main"])
check("registry gone: held again for the next notice (nothing is learned from the first)", d == [] and n["live"] is True and n["to"] == "", (d, n))

# the follow-up of a burst and the warning that an anchor cannot be read take the same decision
core._ROUTES.clear(); core._ROUTES["slack:C0000000004"] = route(PERM["main"]); out.clear()
hub.send_burst("slack:C0000000004", PERM["main"], {"count": 2, "last": ev, "kind": "slack", "etypes": [], "whos": [], "texts": [], "label": "Slack anchor", "first": 0, "last_at": 0})
n = routing.read("projects/alpha")[-1]
check("registry gone: a burst's follow-up is held for the router too", out == [] and n["live"] is True and n["to"] == "", (out, n))

# a session that is not the page's notice address is delivered to, as ever
put_registry(); sr.reset(); live.holds("projects/alpha", PERM["main"]); live.holds("projects/alpha", PERM["builder"]); live.holds("projects/beta", PERM["other"])     # one good read: the registry's names are known
check("registry readable: the builder is delivered to", sent("slack:C0000000005", PERM["builder"], routes=[{"project": "projects/alpha", "session": PERM["builder"], "target": "", "pilot": False, "filter": ""}])[0][0][1] == PERM["builder"])
check("registry readable: a pilot route that names the builder is not held (the builder is not the notice address)", live.holds("projects/alpha", PERM["builder"]) is False)
drop_registry(); sr.reset()
d, n = sent("slack:C0000000006", PERM["builder"], routes=[{"project": "projects/alpha", "session": PERM["builder"], "target": "", "pilot": True, "filter": ""}])
check("registry gone: a pilot route that names the builder is delivered to the builder, not held", [x[1] for x in d] == [PERM["builder"]] and not n.get("live"), (d, n))
check("registry gone: another page's keeper is not this page's notice address", live.holds("projects/alpha", PERM["other"]) is False and live.holds("projects/beta", PERM["other"]) is True)

# the page names another keeper than the one the routes were made for
put_registry(); sr.reset(); live.holds("projects/alpha", PERM["main"])
page("projects/alpha.md", "type: project\ntitle: Alpha\ndisplay-name: beta-main\nstatus: active"); p.cmd_registry(quiet=True)
check("registry readable: a route made for the old keeper is no longer the notice address", A.notice_name("projects/alpha") == "beta-main" and live.holds("projects/alpha", PERM["main"]) is False)
drop_registry(); sr.reset()
check("registry gone: the same", live.holds("projects/alpha", PERM["main"]) is False and live.holds("projects/alpha", PERM["other"]) is True)

print(("ok" if not fails else "FAILED") + f": page_notice_held scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
