"""Scenario test for a session the project's agents map has no line for — fixture data, no live store, no network.

Covers: the rule (`anchors.off_map`): a session that no page of the project's hub lists and that is either listed on no page at all or named for the project is off the map; a session the map lists (front or
background, by its name or an old name), a visitor listed on another project's map, the owner, a server or audit label, a cloud session, a script label no fleet knows and a session sala no longer lists are not;
the reply of create, update and a message to a project page ends with a note naming the project's -main agent (the write goes through: a note, never a refusal), and a page with no agents map names the -main agent
it falls to; the daily page agent lines check carries a fourth kind of line, `session off the map`, one for each project page, next to the `no agents map` line; the replay of the page that was moved and left with no
agents map (items created by sessions named for it) is caught on both counts, its lines reach the agent the page falls to, marked for the owner, through the audit's own delivery (`audit_run.page_agent_groups`,
`compose`); a mapped session, a visitor and a completed item add no line, and a line clears once the map lists the session.

    tests/run-suite off_map        → exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="offmap-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's fleet store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r'(?m)^general_home = .*$', 'general_home = "projects/delta"', toml); assert n == 1    # a page with no agents of its own and no hub falls to the -main agent of projects/delta
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects"): (T / d).mkdir(parents=True)
MAIN, BUILD, LATE, EX3_ENG, EX3_DOCS, ECHO, STRAY, GUEST, GONE = "home-delta-main", "home-delta-builder", "home-delta-late", "home-example-three-eng", "home-example-three-docs", "home-echo-main", "home-stray", "home-delta-guest", "home-delta-gone"
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate((MAIN, BUILD, LATE, EX3_ENG, EX3_DOCS, ECHO, STRAY, GUEST), 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in U.items()}))
page = lambda **kw: {"title": "T", "name": "T", "org": "home", "tags": [], "type": "project", "session": "", "status": "active", "board": [], "board_open": 0, **kw}
REG = {"projects/delta": page(title="Delta", name="Delta", session="home-delta", role="name", agents={MAIN: "talks to the owner about the delta project", BUILD: "builds it"}, back_agents={BUILD: "builds it"}),
       "projects/delta/sub": page(title="Delta sub", name="Delta sub", hub="projects/delta"),
       "projects/echo": page(title="Echo", name="Echo", agents={ECHO: "the echo front", GUEST: "helps the echo front"}),
       "projects/example-three": page(title="Example Three", name="Example Three", org="")}                       # the moved page: a project, items, and no agents map
(T / "store/projects.json").write_text(json.dumps({"pages": REG}))
(T / "store/next-id").write_text("40"); (T / "store/anchors.json").write_text("{}")
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools")); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.anchors import anchors as A; from stackshot.tools import page_agent_report as PAR; from stackshot.audit import audit_run as AR
from stackshot.service import messaging as _messaging
from stackshot.core import instance as _core_instance
from stackshot.projects import projects as _prj
from stackshot.fleet import sessions_registry as _fleet_sessions_registry
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import create as _wt_create
from stackshot.web.tools import message as _wt_message
from stackshot.web.tools import update as _wt_update
from stackshot.service import telling
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
telling.tell_woken = lambda *a, **k: None
OWNER = _core_instance.OWNER
NOTE = "(note: "
NAMES = {u: n for n, u in U.items()}
LIVE = {MAIN, BUILD, LATE, EX3_ENG, EX3_DOCS, ECHO, STRAY, GUEST}

# ---- 1. the rule
off = lambda s, p, **kw: A.off_map(s, p, REG, NAMES, **kw)
check("a front agent the page lists is on its map", off(MAIN, "projects/delta") == "", off(MAIN, "projects/delta"))
check("a background agent the page lists is on its map", off(BUILD, "projects/delta") == "")
check("a sub-page is judged by its hub's map", off(MAIN, "projects/delta/sub") == "" and off(LATE, "projects/delta/sub") == LATE)
check("a session named for the project and listed nowhere is off the map", off(LATE, "projects/delta") == LATE, off(LATE, "projects/delta"))
check("a session listed on no page at all is off the map, whatever its name", off(STRAY, "projects/delta") == STRAY)
check("a visitor that another project's map lists is not off this map", off(ECHO, "projects/delta") == "" and off(MAIN, "projects/echo") == "")
check("a session another map lists but that is named for this project is off this map (it belongs here, the map forgot it)", off(GUEST, "projects/delta") == GUEST and off(GUEST, "projects/echo") == "", off(GUEST, "projects/delta"))
check("a page with no agents map: every unlisted session is off it", off(EX3_ENG, "projects/example-three") == EX3_ENG and off(STRAY, "projects/example-three") == STRAY)
check("the owner, an audit or server label, a cloud session and a script label are never off the map", off(OWNER, "projects/example-three") == "" and off("stackshot audit", "projects/example-three") == ""
      and off("stackshot (auto)", "projects/example-three") == "" and off("cse_0123abcd", "projects/example-three") == "" and off("nightly-script", "projects/example-three") == "", (off(OWNER, "projects/example-three"), off("nightly-script", "projects/example-three")))
check("a session sala does not list now is not off the map (it cannot act)", off(GONE, "projects/delta", live=LIVE) == "" and off(LATE, "projects/delta", live=LIVE) == LATE)
check("a project that names nothing, or a bare empty sender, gives nothing", off(LATE, "") == "" and off("", "projects/delta") == "")
check("the page key may carry .md or slashes", off(LATE, "/projects/delta.md") == LATE)

# ---- 2. the write notes
DESC = "- Goal: A thing\n- It lives here\n- Done when done"
def rd(g):
    g = str(g); g = g if not g[:1].isdigit() else "a" + g
    return json.loads((T / f"store/{g[0]}/{g[1:]}.json").read_text())
def made(r): return r.split()[1] if r.startswith("created") else ""
def mk(sender, project="projects/delta", mover=None, **kw):
    base = dict(subject="[home] an off-map test", description=DESC, project=project, sender=sender, mover=mover or sender, next=f"{mover or sender}: build it")
    base.update(kw)
    return _wt_create.stackshot_create(**base)
tail = lambda r: r.splitlines()[-1] if r else ""
r = mk(MAIN)
check("create by a session the map lists: no note", NOTE not in r and r.startswith("created"), tail(r))
r = mk(BUILD)
check("create by a listed background agent: no note", NOTE not in r and r.startswith("created"), tail(r))
r = mk(LATE)
check("create by a session named for the project and off its map: created, and the reply ends with the note naming its -main agent",
      r.startswith("created") and tail(r) == f"(note: projects/delta has no agents-map line for {LATE}. Its -main agent is {MAIN}: ask it to list you or to take this work.)", tail(r))
g_late = made(r)
check("…the write itself was not changed by it: the item is stored under the sender", rd(g_late)["metadata"].get("project") == "projects/delta" and _fleet_sessions_registry._session_label(rd(g_late)["metadata"].get("owner")) == LATE, rd(g_late)["metadata"])
r = mk(STRAY)
check("create by a session listed nowhere: the note", tail(r).startswith(f"(note: projects/delta has no agents-map line for {STRAY}."), tail(r))
r = mk(ECHO, mover=BUILD)
check("create by a visitor another map lists: no note", NOTE not in r and r.startswith("created"), tail(r))
r = mk("nightly-script", mover=BUILD)
check("create from a script label: no note", NOTE not in r, tail(r))
r = mk(EX3_ENG, project="projects/example-three")
g_ax1 = made(r)
check("the moved page with no agents map: created, the note says so and names the -main agent the page falls to (the scope's general one)",
      r.startswith("created") and tail(r) == f"(note: projects/example-three has no agents-map line for {EX3_ENG}. Its -main agent is {MAIN}: ask it to list you or to take this work.)", tail(r))
g_ax2 = made(mk(EX3_ENG, project="projects/example-three", subject="[home] a second example-three item"))
g_ax3 = made(mk(EX3_DOCS, project="projects/example-three", mover=EX3_ENG, subject="[home] a third example-three item"))
g_x3_done = made(mk(EX3_DOCS, project="projects/example-three", subject="[home] a finished example-three item"))
r = _wt_update.stackshot_update(item_id=g_late, sender=LATE, priority="p2")
check("update by the off-map session: the reply ends with the note", tail(r).startswith(f"(note: projects/delta has no agents-map line for {LATE}."), tail(r))
r = _wt_update.stackshot_update(item_id=g_late, sender=MAIN, priority="p3")
check("update by a session the map lists: no note", NOTE not in r, tail(r))
_messaging._message = lambda to, text, sender, **k: "held for the router — the router rules notice abc123"          # the delivery has its own suites: this one checks what the tool adds to its reply
r = _wt_message.stackshot_message(to="projects/delta", text="a question about the plan", sender=LATE)
check("a message to a project page from an off-map session: the note follows the reply", r.startswith("held for the router") and tail(r).startswith(f"(note: projects/delta has no agents-map line for {LATE}."), r)
r = _wt_message.stackshot_message(to="projects/delta", text="a question about the plan", sender=MAIN)
check("a message to a project page from a listed session: the reply as it was", r == "held for the router — the router rules notice abc123", r)
r = _wt_message.stackshot_message(to=MAIN, text="a question for you", sender=LATE)
check("a message to a session names no project: no note", NOTE not in r, r)
real_off_map = A.off_map
A.off_map = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("registry unreadable"))
import contextlib, io
with contextlib.redirect_stderr(io.StringIO()) as err_: r = mk(LATE)
check("a note that cannot be made leaves the reply as it was (the write still goes through)", r.startswith("created") and NOTE not in r and "off-map note" in err_.getvalue(), tail(r))
A.off_map = real_off_map
check("a bare slug names the page in the first pages dir: the rule gives the same answer as for the key", off(MAIN, "delta") == "" and off(LATE, "delta") == LATE and off(EX3_ENG, "example-three") == EX3_ENG, (off(MAIN, "delta"), off(LATE, "delta")))
r = mk(MAIN, project="delta")
check("create naming the project by a bare slug, sender listed on its map: created, no note", r.startswith("created") and NOTE not in r, tail(r))
r = mk(LATE, project="delta")
check("create naming the project by a bare slug, sender not listed: the note names the page by its key", r.startswith("created") and tail(r) == f"(note: projects/delta has no agents-map line for {LATE}. Its -main agent is {MAIN}: ask it to list you or to take this work.)", tail(r))
g_slug = made(r)
r = _wt_update.stackshot_update(item_id=g_slug, sender=MAIN, priority="p2", project="delta")
check("update naming the project by a bare slug, sender listed: no note", NOTE not in r, tail(r))
r = _wt_update.stackshot_update(item_id=g_slug, sender=LATE, priority="p3", project="delta")
check("update naming the project by a bare slug, sender not listed: the note, with the page key", tail(r).startswith(f"(note: projects/delta has no agents-map line for {LATE}."), tail(r))
real_to_key = _prj.to_key
_prj.to_key = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("page index unreadable"))
with contextlib.redirect_stderr(io.StringIO()) as err_: r = _wt_message.stackshot_message(to="projects/delta", text="a question about the plan", sender=LATE)
_prj.to_key = real_to_key
check("a message whose note raises is delivered with its reply as it was", r == "held for the router — the router rules notice abc123" and "off-map note" in err_.getvalue(), r)

# ---- 3. the audit's line, replayed on the moved page (items created above, read back from the store)
(T / f"store/{g_x3_done[0]}/{g_x3_done[1:]}.json").write_text(json.dumps({**rd(g_x3_done), "status": "completed"}))
sess = lambda live=LIVE: (lambda: (set(live), set()))
res = PAR.read(REG, sess(), None, time.time())
lines = lambda r: {(f["page"], f["line"]): f for f in r["findings"]}
L = lines(res)
check("the moved page is caught as having no agents map (the earlier check) and as having sessions its map has no line for (this one)",
      ("projects/example-three", "no agents map") in L and ("projects/example-three", "session off the map") in L, sorted(L))
f = L[("projects/example-three", "session off the map")]
check("…the line names each session with the open items it created, moves or is the contact of: a completed item adds nothing", f["name"] == f"{EX3_ENG} (3 items), {EX3_DOCS} (1 item)", f)
check("…and the text says what to do, under the audit's clip, with no separator in it", len(f["fix"]) <= 240 and " · " not in f["fix"] and "add its line" in f["fix"] and "-main" in f["fix"], f["fix"])
check("…it goes to the agent the page falls to, as the other lines do", f["to"] == MAIN and L[("projects/example-three", "no agents map")]["to"] == MAIN, (f["to"], L[("projects/example-three", "no agents map")]["to"]))
fd = L.get(("projects/delta", "session off the map")) or {}
check("the mapped page: the off-map sessions are named, the visitor and the mapped agents are not", fd.get("name") == f"{LATE} (3 items), {STRAY} (1 item)" and ECHO not in fd.get("name", "") and MAIN not in fd.get("name", ""), fd)
check("one line for each project page, nothing for a page whose items all come from its map", [k for k in L if k[1] == "session off the map"] == [("projects/delta", "session off the map"), ("projects/example-three", "session off the map")], sorted(L))
check("sala unreadable or empty: this kind is carried with the others (none)", PAR.read(REG, lambda: None, None, time.time())["findings"] == [] and PAR.read(REG, lambda: (set(), set()), None, time.time())["findings"] == [])
check("a session sala no longer lists adds no line", "home-stray" not in " ".join(x["name"] for x in PAR.read(REG, sess(LIVE - {STRAY}), None, time.time())["findings"] if x["line"] == "session off the map"))
REG2 = {**REG, "projects/example-three": page(title="Example Three", name="Example Three", org="", agents={"home-example-three-main": "keeps it", EX3_ENG: "builds it", EX3_DOCS: "writes the docs"}, back_agents={EX3_ENG: "builds it", EX3_DOCS: "writes the docs"})}
L2 = lines(PAR.read(REG2, sess(LIVE | {"home-example-three-main"}), None, time.time()))
check("once the page lists the sessions the line clears (and so does the no-agents-map line)", ("projects/example-three", "session off the map") not in L2 and ("projects/example-three", "no agents map") not in L2, sorted(L2))
REG3 = {**REG, "projects/example-three": page(title="Example Three", name="Example Three", org="", agents={"home-example-three-main": "keeps it", EX3_ENG: "builds it"}, back_agents={EX3_ENG: "builds it"})}
L3 = lines(PAR.read(REG3, sess(LIVE | {"home-example-three-main"}), None, time.time()))
check("a map that lists one of the two sessions leaves a line for the other only", L3[("projects/example-three", "session off the map")]["name"] == f"{EX3_DOCS} (1 item)", L3.get(("projects/example-three", "session off the map")))
many = [{"id": str(i), "status": "open", "updated": time.time(), "state_updated": time.time(), "metadata": {"project": "projects/example-three", "owner": f"home-example-three-{i}"}} for i in range(7)]
fm = PAR.offmap(many, REG, ({f"home-example-three-{i}" for i in range(7)}, set()), {})
check("a page with many such sessions has one line: four named, the rest counted", len(fm) == 1 and fm[0]["name"].count(" (1 item)") == 4 and fm[0]["name"].endswith(" and 3 more"), fm)

# ---- 4. the same line through the audit's delivery
env = AR.Env(roles={MAIN: {"role": "front"}, BUILD: {"role": "background"}}, registry=lambda: REG, sessions=sess(), fallback=lambda p: MAIN, builder=lambda p: BUILD)
groups = AR.page_agent_groups(res, env)
check("the lines are grouped for the agent the page falls to, a front agent: marked", list(groups) == [(MAIN, True)] and groups[(MAIN, True)]["front"] is True, {k: v["front"] for k, v in groups.items()})
check("…the group carries both kinds for the moved page and counts as a gap, so the header says what is wrong",
      any("projects/example-three · session off the map · " in ln for ln in groups[(MAIN, True)]["lines"]) and any("projects/example-three · no agents map · " in ln for ln in groups[(MAIN, True)]["lines"]) and groups[(MAIN, True)]["gaps"] >= 3, groups[(MAIN, True)]["lines"])
sent = []
env.deliver = lambda to, text, fyi=False: (sent.append((to, text, fyi)) or (True, "[200] ok"))
head = "[stackshot] Page agent lines test: need a fix"
text = AR.compose(groups[(MAIN, True)]["lines"], head, groups[(MAIN, True)]["front"])
check("the message to the -main agent starts with the owner's mark on line 1 (the rule for a front agent)", text.splitlines()[0] == f"[for {OWNER}]" and "session off the map" in text, text.splitlines()[:3])
out = []
AR.run(dry=True, now=time.time(), items={t_["gid"]: t_ for t_ in A.items()}, anchors={}, env=env, rubric="", out=out.append)
check("the daily run's dry listing shows the line with the agent it goes to", any("[page-agents] projects/example-three · session off the map" in l and f"(to {MAIN})" in l for l in out), out)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.stdout.flush()
os._exit(1 if fails else 0)
