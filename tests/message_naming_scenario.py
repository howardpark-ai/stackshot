"""Scenario test for what a message that names an item does to the item's needs (the server's naming of a background agent on a handover) — fixture data, no live store, no network, no server
process (the server module is imported and called in-process, on a temporary config; the pages are fixture files in a temporary directory; the push to a session is faked).

A message to a background agent that names an open item names the agent in the item's needs (the reply says so). It must never leave the item with two movers: an item has one mover, a second session in
needs is refused by the model guards (`needs names more than one mover`) on the next write of the mover, and the mover would have to reset needs by hand. A background agent of the item's own project is never
counted as a second mover by the guards, so it is still named; any other agent is named only when no other session that the guards count already moves the item (and never beside decision). When the agent is
not named the reply says why in one line and says how to hand the item over (update, mover=<agent>), and the item is exactly as it was.

Covers: the trap as it was found (the mover is another project's background agent, or a front agent, and the message goes to a third agent: the mover's next write is refused after the naming and passes now); an
item with no session in needs and the project's own background agents, named as before, with the mover's next write passing; the decision case; `[model] one_mover = false`; an agent already named, a closed item,
a listed never_named agent and a message that names no item (no line, as before); a message that names two items (one named, one not); the SendMessage route (POST /client/handover) and the message tool
(`_message`) carrying the same line; a waiting item; the way the line points (update, mover=<agent>) working; the tool text saying it.

    tests/run-suite message_naming        → exit 0 / 1"""
import contextlib, datetime, io, json, os, re, sys, pathlib, logging, threading, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="msgnamingtest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = ""', f'session_links = "{tmp}/sala"', 1); assert f'session_links = "{tmp}/sala"' in toml   # the fixture registry, never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml, count=1); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
for d in ("store/a", "fleet/a", "sala/a", "brain/projects", "secrets", "state"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
SEEN = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")

def uid(n): return f"00000000-0000-4000-8000-{n:012d}"
NAMES = {"build": "home-sparrow-builder", "notes": "home-sparrow-notes", "main": "home-sparrow-main", "bbuild": "home-beta-builder", "bmain": "home-beta-main", "gbuild": "home-gamma-builder", "dbg": "home-delta-builder"}
S = {k: uid(101 + i) for i, k in enumerate(NAMES)}
PROJ = {"build": "projects/alpha", "notes": "projects/alpha", "main": "projects/alpha", "bbuild": "projects/beta", "bmain": "projects/beta", "gbuild": "projects/gamma", "dbg": "projects/delta"}
def row(key):
    return {"id": S[key], "name": NAMES[key], "aliases": [], "project": None, "project_key": PROJ[key], "role": None, "lane": "max", "model": "opus", "effort": "medium", "pane": NAMES[key],
            "cwd": "/work", "state": "live", "created": "2026-10-21T21:00:00Z", "retired_at": None, "transcripts": [{"id": uid(300 + i), "machine": "a", "at": "2026-10-21T21:00:00Z", "why": "import"} for i in [list(NAMES).index(key)]]}
(T / "sala/a/session-registry.json").write_text(json.dumps({"schema": 1, "machine": "a", "written": "2026-10-22T07:00:00Z", "sessions": {S[k]: row(k) for k in NAMES}}), encoding="utf-8")
(T / "fleet/a/sessions.json").write_text(json.dumps({S[k]: {"name": NAMES[k], "machine": "a", "url": "", "seen": SEEN} for k in NAMES}))      # the heartbeat: every session is live, so the message tool delivers
def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8"); os.utime(q, (time.time() - 8 * 3600, time.time() - 8 * 3600))
page("projects/alpha.md", "type: project\ntitle: Alpha\ndisplay-name: home-sparrow\nagents:\n  home-sparrow-main: talks to Oliver\n  background:\n    home-sparrow-builder: builds\n    home-sparrow-notes: keeps the notes\nstatus: active")
page("projects/beta.md", "type: project\ntitle: Beta\ndisplay-name: home-beta\nagents:\n  home-beta-main: talks to Oliver\n  background:\n    home-beta-builder: builds\nstatus: active")
page("projects/gamma.md", "type: project\ntitle: Gamma\ndisplay-name: home-gamma\nagents:\n  home-gamma-main: talks to Oliver\n  background:\n    home-gamma-builder: builds\nstatus: active")
page("projects/delta.md", "type: project\ntitle: Delta\ndisplay-name: home-delta\nagents:\n  home-delta-main: talks to Oliver\n  background:\n    home-delta-builder: builds\nstatus: active")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

from stackshot.projects import pages as p
p.cmd_registry(quiet=True)
from stackshot.fleet import sessions_registry as sr
sr.TTL = 0
from stackshot.web import server; from stackshot.fleet import client
import subprocess
from stackshot.core import config as _cfg
from stackshot.web import publish as _web_publish
from stackshot.web.tools import message as _wt_message
_web_publish._publish = lambda: None
pushed = []                           # every push to a session the server would make: [to, note]
_orig_run = subprocess.run
def _fake_run(cmd, *a, **kw):
    if isinstance(cmd, list) and any(str(x).endswith("push.py") for x in cmd):
        pushed.append(list(cmd)[-2:]); return subprocess.CompletedProcess(cmd, 0, "delivered\n", "")
    return _orig_run(cmd, *a, **kw)
subprocess.run = _fake_run
def settle():
    for t in threading.enumerate():
        if t is not threading.current_thread() and t.daemon and t.is_alive(): t.join(3)

now0 = time.time(); DAY = 86400.0
def day(n): return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=n)).strftime("%Y-%m-%d")
BUILD, NOTES, MAIN, BBUILD, GBUILD, DBUILD = (NAMES[k] for k in ("build", "notes", "main", "bbuild", "gbuild", "dbg"))
def item(i, status="open", project="projects/alpha", **meta):
    su = now0 - 10 * DAY
    base = {"owner": S["main"], "project": project, "next": f"{BUILD}: do the thing"}
    base.update(meta)
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "- A thing\n- It lives here\n- Done when done", "status": status,
                                                    "updated": su, "state_updated": su, "confirmed": su, "metadata": base}))
def mt(i): return json.loads((T / f"store/a/{i}.json").read_text())["metadata"]
def needs(i):
    """The names in the item's needs as the board shows them (the store keeps a session by its id)."""
    v = mt(i).get("needs")
    return [x if x in ("decision", "external") else sr._session_label(x) for x in v] if isinstance(v, list) else v
def set_cfg(**kw): _cfg.CFG["model"] = {"rebullet_machines": ["box-a"], **kw}      # the example-owner instance lists box-a (tests/_instance.py); a suite that sets [model] whole keeps it
set_cfg()
def send(to, text, sender=MAIN): return server._name_on_handover(to, text, sender)
def write_ok(i, sender, **kw):
    """The mover's next write on the item: (True, "") when it lands, (False, the refusal) when it is refused."""
    try:
        server._update(f"a{i}", sender=sender, **kw); return True, ""
    except Exception as e:  # noqa: BLE001
        return False, str(e)
REFUSAL = "needs names more than one mover"

# ---- 1. the trap as it was found: the mover is not a background agent of the item's project, and the message goes to another background agent
item(1, needs=[BBUILD])                       # an item of alpha that another project's background agent moves
out = send(GBUILD, "a1 is yours: build it")
check("1 another project's background agent moves the item, a message to a third agent that names it: the third is not named, and the item is as it was", needs(1) == [BBUILD] and "named" not in out.split("did not")[0], (needs(1), out))
check("1 …the reply says so in one line: who moves the item, why, and the way to hand it over", out.startswith(f"\n(did not name {GBUILD} in a1's needs: {BBUILD} already moves it, and an item has one mover") and f"update(mover={GBUILD})" in out and out.count("\n") == 1, out)
ok, why = write_ok(1, BBUILD, wake=day(3))
check("1 …and the mover's next write passes (it was refused with 'needs names more than one mover' once the third agent was named)", ok, why)
check("1 …the needs are still the mover alone after that write", needs(1) == [BBUILD], needs(1))

item(2, needs=[MAIN])                         # a front agent moves it
out = send(BBUILD, "please take a2")
check("2 a front agent moves the item: a message to another project's background agent names nobody", needs(2) == [MAIN] and "did not name" in out, (needs(2), out))
ok, why = write_ok(2, MAIN, wake=day(3))
check("2 …the front agent's next write passes", ok, why)

item(3, needs=[MAIN, BBUILD])                 # a second mover already stored (an older item): the one more agent is refused the same way
out = send(GBUILD, "a3: go")
check("3 an item that already names two movers is not given a third", needs(3) == [MAIN, BBUILD] and "did not name" in out, (needs(3), out))

item(4, needs=[MAIN, BBUILD])                 # an item that already holds two movers still takes the project's own background agent (the guards never count it)
out = send(NOTES, "a4: the notes")
check("4 an item that already holds two movers: a background agent of its project is still named (it changes nothing the guards count)", needs(4) == [MAIN, BBUILD, NOTES] and "(named " in out, (needs(4), out))
item(5, needs=[], mover=MAIN)                 # a stored mover, nothing in needs
out = send(GBUILD, "a5 is yours: build it")
check("5 a stored mover with nothing in needs: another project's background agent is not named (the stored mover moves it)", not needs(5) and f"{MAIN} already moves it" in out and "did not name" in out, (needs(5), out))
item(6, needs=[], mover=S["main"])            # the same, stored by its id
out = send(GBUILD, "a6 is yours: build it")
check("6 …a stored mover kept by its id reads the same, by its name", not needs(6) and f"{MAIN} already moves it" in out, (needs(6), out))
item(7, needs=[], mover=BUILD)                # a stored mover that is the project's own background agent is no clash
out = send(GBUILD, "a7 is yours: build it")
check("7 a stored mover that is a background agent of the project: another project's agent is named, as before", needs(7) == [GBUILD] and "(named " in out, (needs(7), out))
item(8, needs=[], mover=MAIN)
out = send(NOTES, "a8: the notes")
check("8 a stored mover and a background agent of the item's project: named", needs(8) == [NOTES] and "(named " in out, (needs(8), out))

# ---- 2. the cases that still name, as before
item(10, needs=[])                            # no session in needs (the project's builder moves it by default), a message to the project's own background agent
out = send(NOTES, "a10 is yours: write the notes")
check("10 no session in needs, a message to a background agent of the project: named, as before, with the reply line", needs(10) == [NOTES] and out.startswith(f"\n(named {NOTES} in a10's needs: handover message from {MAIN}"), (needs(10), out))
check("10 …the mover's write passes", write_ok(10, NOTES, wake=day(3))[0])
item(11, needs=[BUILD])
out = send(NOTES, "a11: and the notes")
check("11 the builder moves it: a message to the project's other background agent names it too (two background agents of a project are no second mover)", needs(11) == [BUILD, NOTES] and "(named " in out, (needs(11), out))
check("11 …and the builder's next write passes", write_ok(11, BUILD, wake=day(3))[0])
item(12, needs=[BBUILD])
out = send(NOTES, "a12: the notes")
check("12 another project's background agent moves it: a message to a background agent of the item's project still names it (the guards never count it as a second mover)", needs(12) == [BBUILD, NOTES] and "(named " in out, (needs(12), out))
check("12 …and the mover's next write passes", write_ok(12, BBUILD, wake=day(3))[0])
item(13, needs=[])
out = send(GBUILD, "a13: take it")
check("13 no session in needs: another project's background agent that is handed the item is named, the one mover (the way a hand-over to it always worked)", needs(13) == [GBUILD] and "(named " in out, (needs(13), out))
check("13 …and its next write passes", write_ok(13, GBUILD, wake=day(3))[0])

# ---- 3. decision
ASK = "Decide: ship it · Recommend: yes · Stakes: low · By: no date"
item(20, needs=["decision"], ask=ASK)
out = send(GBUILD, "a20: heads up")
check("20 on his call (needs decision): another project's background agent is not named beside it (decision plus a session is a second mover)", needs(20) == ["decision"] and "did not name" in out and "needs decision" in out, (needs(20), out))
item(21, needs=["decision"], ask=ASK)
out = send(NOTES, "a21: heads up")
check("21 on his call: a background agent of the item's project is named beside it, as before", needs(21) == ["decision", NOTES] and "(named " in out, (needs(21), out))
check("21 …and a later write by a front agent passes", write_ok(21, MAIN, wake=day(3))[0])

# ---- 4. the switch
set_cfg(one_mover=False)
item(30, needs=[BBUILD])
out = send(GBUILD, "a30: go")
check("30 [model] one_mover = false: the guards allow two movers, so the agent is named", needs(30) == [BBUILD, GBUILD] and "(named " in out, (needs(30), out))
item(31, needs=[BBUILD])
set_cfg(guards=False)
out = send(GBUILD, "a31: go")
check("31 [model] guards = false: nothing refuses two movers, so the agent is named", needs(31) == [BBUILD, GBUILD] and "(named " in out, (needs(31), out))
set_cfg()
item(32, needs=[S["bbuild"]])                 # the store keeps a session in needs by its id: the line shows its name
out = send(GBUILD, "a32: go")
check("32 a mover stored by its id: the line names it by its name, and the item is as it was", f"{BBUILD} already moves it" in out and needs(32) == [BBUILD] and mt(32)["needs"] == [S["bbuild"]], (out, mt(32)))

# ---- 5. no line where there was none
item(40, needs=[BBUILD, NOTES])
check("40 an agent already named: no line, as before", send(NOTES, "a40 again") == "" and needs(40) == [BBUILD, NOTES])
item(41, status="completed", needs=[BBUILD])
check("41 a closed item: no line, as before", send(GBUILD, "a41 is done") == "" and needs(41) == [BBUILD])
item(42, needs=[BBUILD])
_cfg.CFG.setdefault("pilot", {})["never_named"] = [GBUILD]
check("42 an agent listed in [pilot] never_named: no line, nothing named", send(GBUILD, "a42 release please") == "" and needs(42) == [BBUILD])
_cfg.CFG["pilot"]["never_named"] = []
check("43 a message that names no item: no line", send(GBUILD, "just words, no id here") == "")
check("44 an id in backticks names nothing: no line", send(GBUILD, "see `a42` for context") == "" and needs(42) == [BBUILD])
check("45 a front agent as the recipient: nothing (only background agents are named)", send(MAIN, "a42 is yours", sender=GBUILD) == "" and needs(42) == [BBUILD])

# ---- 6. two items in one message: one is named, one is not, and the reply says both
item(50, needs=[]); item(51, needs=[BBUILD])
out = send(GBUILD, "a50 and a51 are yours")
check("50 a message that names two items names the agent on the one it can and says so about the other", needs(50) == [GBUILD] and needs(51) == [BBUILD] and "(named " in out and "did not name" in out and "a51" in out and "a50's needs" in out, (needs(50), needs(51), out))

# ---- 7. a waiting item
item(60, needs=[BBUILD], wait_kind="time", wake=day(5), wait_basis="the soak ends " + day(5))
out = send(GBUILD, "a60: look at it")
check("60 a waiting item with a mover in needs is not given a second one", needs(60) == [BBUILD] and "did not name" in out, (needs(60), out))
ok, why = write_ok(60, BBUILD, next=f"{BBUILD}: check the soak")
check("60 …and the mover's write on it passes", ok, why)

# ---- 8. the other routes carry the same line
item(70, needs=[BBUILD])
st, res = server._client_post("testbox", "handover", {"to": GBUILD, "text": "SendMessage about a70", "sender": MAIN})
check("70 the SendMessage route (POST /client/handover): the same line, nothing named", st == 200 and "did not name" in res["result"] and f"update(mover={GBUILD})" in res["result"] and needs(70) == [BBUILD], (st, res, needs(70)))
item(71, needs=[])
st, res = server._client_post("testbox", "handover", {"to": GBUILD, "text": "SendMessage about a71", "sender": MAIN})
check("71 …and where it can name, the line it always had", st == 200 and res["result"].startswith(f"(named {GBUILD} in a71's needs: handover message from {MAIN} (SendMessage on testbox))") and needs(71) == [GBUILD], (st, res))
item(72, needs=[BBUILD])
settle(); pushed.clear()
out = server._message(GBUILD, "a72: build the export", MAIN)
check("72 the message tool: delivered, and the reply ends with the line", out.startswith("delivered") and "did not name" in out and needs(72) == [BBUILD] and len([x for x in pushed if x[0] == GBUILD and "a72: build" in x[1]]) == 1, (out, needs(72), pushed))
item(73, needs=[])
out = server._message(GBUILD, "a73: build the export", MAIN)
check("73 the message tool where it names: the reply says named, as before", out.startswith("delivered") and f"(named {GBUILD} in a73's needs" in out and needs(73) == [GBUILD], (out, needs(73)))

# ---- 9. the way the line points works: the sender hands the item over with update(mover=<agent>)
item(80, needs=[BBUILD])
send(GBUILD, "a80 is yours")
r = server._update("a80", sender=MAIN, mover=GBUILD, needs=[GBUILD], next=f"{GBUILD}: build it", clear_next=True)
check("80 …handing the item over by update(mover=…) works, and the item is the new mover's alone", "Refused" not in str(r) and needs(80) == [GBUILD], (r, needs(80)))

# ---- 9b. a stored mover that is the agent being named, or the legacy word `none`, is no second mover
item(100, needs=[], mover=GBUILD)             # the stored mover is the agent the message goes to
out = send(GBUILD, "a100 is yours: build it")
check("100 the stored mover is the agent being named: it is named, with no \"already moves it\" line", needs(100) == [GBUILD] and "(named " in out and "did not name" not in out, (needs(100), out))
item(101, needs=[], mover=S["gbuild"])        # the same, stored by its id
out = send(GBUILD, "a101 is yours: build it")
check("101 the stored mover is the agent being named, stored by its id: named", needs(101) == [GBUILD] and "did not name" not in out, (needs(101), out))
item(102, needs=[], mover="none")             # the legacy literal: nobody moves it
out = send(GBUILD, "a102 is yours: build it")
check("102 a stored mover of the legacy word `none` is nobody: the agent is named", needs(102) == [GBUILD] and "did not name" not in out and "none already moves" not in out, (needs(102), out))
item(103, needs=[], mover=MAIN)               # control: another session stored as the mover still declines
out = send(GBUILD, "a103 is yours: build it")
check("103 control: another session stored as the mover still declines", not needs(103) and f"{MAIN} already moves it" in out, (needs(103), out))

# ---- 10. the tool text and the notes say it
check("90 the message tool's text says the naming can be declined for a second mover and what to do then", "second mover" in _wt_message._message_desc() and "update(mover=<agent>)" in _wt_message._message_desc(), _wt_message._message_desc()[:300])
src = (pathlib.Path(STACK) / "docs" / "overview.md").read_text(encoding="utf-8")
check("91 the overview says it", "never leaves the item with a second mover" in src and "update(mover=<agent>)" in src, None)

settle()
if fails:
    print(f"\n{len(fails)} of {len(ran)} checks FAILED"); sys.exit(1)
print(f"ok: {len(ran)} checks"); sys.exit(0)
