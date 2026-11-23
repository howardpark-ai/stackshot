"""Scenario test for the audit's delivery of a finding to a front agent: a front agent's turn starts only for what is the person's, so a finding goes to it marked for him only when its item waits on him
(a decision or a step of his: audit_run.waits_on_person). Fixture items, messages replaced by recorders, no live store, no network, no model call.

  1  waits_on_person: an item that needs his decision or is his step: True; an item a session moves, one that waits on a time, a closed one: False; no items, an id that names none, an item the model cannot read: None
  2  a finding that goes to the -main agent marked for him (a finding with no project addressed to a front agent): marked while its item waits on him, held for the agent's next turn (an fyi, no mark, one note for
     each finding) when it does not; without the pass's items it is marked as before; a held note the agent cannot be given (and no project to fall back on) is tried again at the next run
  3  the chase of an unmoved finding by a front-only project's -main agent (level 1) and the second level (level 2) are the same: marked for an item that waits on him, held for any other (a held note the agent cannot be given goes to the project's page key, unmarked)
  4  the fallback of a mover that cannot be reached: the -main agent marked for an item that waits on him (as before), the page key unmarked for one that does not
  5  the passes give their items to the delivery: a filing pass finding about an item no one waits on is held, not marked

    tests/run-suite audit_front_turn        -> exit 0 / 1"""
import datetime as dt, json, os, pathlib, re, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="auditfront-"); T = pathlib.Path(tmp)
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools"))

toml = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                 ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml, count=1); assert n == 1
for key, val in (("agent", "falcon-audit"), ("builder", "falcon-engineer"), ("main", "falcon-main")):
    toml, n = re.subn(rf"(?m)^{key} = \"my-[a-z]+\"", f"{key} = \"{val}\"", toml); assert n == 1, key
toml, n = re.subn(r'(?m)^(\[audit\][^\n]*\n)enabled = false', r'\g<1>enabled = true', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "home/.claude/sessions").mkdir(parents=True)                                              # an isolated HOME: the pane registry is a folder of ours
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "brain/projects", "fleet/a", "state"): (T / d).mkdir(parents=True)
(T / "store/anchors.json").write_text("{}"); (T / "store/projects.json").write_text(json.dumps({"pages": {}})); (T / "store/next-id").write_text("1")
(T / "fleet/a/sessions.json").write_text("{}"); (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))

from stackshot.core import config as _cfg; from stackshot.audit import audit_checks as AC; from stackshot.audit import audit_run as AR
H = 3600; now = time.time()
OWNER = "00000000-0000-4000-8000-000000000001"
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

ROLES = {"demo-main": {"role": "front"}, "demo-builder": {"role": "background"}}
sent = []
def deliver(to, text, fyi=False): sent.append((to, text, fyi)); return True, "[200] ok"
def env(front_only=False, **kw):
    kw.setdefault("pages", lambda run, deadline: {"enabled": False, "mode": "", "counts": {}})
    return AR.Env(roles=ROLES, fallback=kw.pop("fallback", lambda p: "demo-main"), builder=kw.pop("builder", lambda p: "demo-builder"), page_of=lambda p: ("", None), front_only=lambda p: front_only,
                  deliver=kw.pop("deliver", deliver), sessions=lambda: None, **kw)
shown = lambda n: "board" + chr(35) + str(n)      # an item as the audit shows it, built here so no id-shaped literal sits in the file
def item(i, status="open", **meta):
    return f"a{i}", {"id": str(i), "subject": f"[home] item {i}", "description": "- A thing, finished when it works", "status": status, "updated": now - H, "state_updated": now - H, "confirmed": now - H,
                     "metadata": {"owner": OWNER, "project": "projects/demo", **meta}}
ITEMS = dict([
    item(9101, mover="Oliver", needs=["decision"], ask="Decide: ship it?"),                       # waits on his decision
    item(9102, mover="Oliver", state="your-step", next="Oliver: sign the form"),                  # his step
    item(9103, mover="demo-builder", state="doing", needs=["demo-builder"], next="demo-builder: build it"),      # a session moves it
    item(9104, mover="demo-builder", state="parked", hold=True, wake="2099-01-01"),               # it waits on a time
    item(9105, status="completed", mover="demo-builder"),                                           # closed
    item(9106, mover="demo-builder", state="doing", needs=["demo-builder"], next="demo-builder: build it"),
])
def finding(category, i, to="demo-main", mover="demo-builder", project="", detail="the step names a wait it does not file"):
    return {"id": shown(i), "project": project, "owner": mover, "mover": mover, "category": category, "detail": detail, "fix": "file the wait", "source": "code", **({"to": to} if to else {})}
def send(fs, items=ITEMS, **kw):
    sent.clear()
    return AR.deliver_findings(env(**kw), fs, "Filing check 2099-03-03 10:00 UTC", items)
msgs = lambda: [(to, t.startswith("[for Oliver]"), fy) for to, t, fy in sent]
by_shown = {shown(i): f"a{i}" for i in (9101, 9102, 9103, 9104, 9105, 9106)}
W = lambda i, items=ITEMS: AR.waits_on_person({"id": shown(i)}, items, by_shown, now)

# ---- 1. the reading
check("1 an item that needs his decision waits on him", W(9101) is True, W(9101))
check("1 …and so does one that is his step", W(9102) is True, W(9102))
check("1 an item a session moves waits on nothing of his", W(9103) is False, W(9103))
check("1 …and neither does one that waits on a time", W(9104) is False, W(9104))
check("1 …nor a closed one", W(9105) is False, W(9105))
check("1 no items given: it cannot be told", AR.waits_on_person({"id": shown(9101)}, None, by_shown, now) is None)
check("1 an id that names no item of the pass: it cannot be told", W(9999) is None, W(9999))
bad = dict(ITEMS); bad["a9106"] = "not an item"
check("1 an item that is no record the model can read: it cannot be told", W(9106, bad) is None, W(9106, bad))

# ---- 2. the main route: a finding with no project, addressed to a front agent, goes to its -main agent marked for him
send([finding("wait-end", 9101)])
check("2 its item waits on his decision: marked for him, one message to the -main agent, not an fyi", msgs() == [("demo-main", True, False)], sent)
send([finding("wait-end", 9102)])
check("2 …and on his step: marked", msgs() == [("demo-main", True, False)], sent)
_o = send([finding("wait-end", 9103)])
check("2 its item waits on nothing of his (a session moves it): held for the -main agent, an fyi, no mark, and counted as reached", msgs() == [("demo-main", False, True)] and len(_o[1]) == 1, (sent, _o[1]))
check("2 …the held note carries the finding under its label line", sent[0][1].splitlines()[0] == "[stackshot] Filing check 2099-03-03 10:00 UTC:" and shown(9103) + " · wait-end · the step names a wait it does not file" in sent[0][1], sent)
send([finding("wait-end", 9104)])
check("2 an item that waits on a time: held", msgs() == [("demo-main", False, True)], sent)
send([finding("wait-end", 9103), finding("wait-end", 9106)])
check("2 two such findings are two held notes, one finding each", msgs() == [("demo-main", False, True)] * 2 and all(t.count("board#") == 1 for _to, t, _f in sent), sent)
send([finding("wait-end", 9101), finding("wait-end", 9103)])
check("2 one that waits on him and one that does not: the first marked (one message), the second held (another)", sorted(msgs()) == sorted([("demo-main", True, False), ("demo-main", False, True)]), sent)
send([finding("wait-end", 9103)], items=None)
check("2 without the pass's items nothing can be told: marked as before", msgs() == [("demo-main", True, False)], sent)
send([finding("wait-end", 9999)])
check("2 an id that names no item of the pass: marked as before", msgs() == [("demo-main", True, False)], sent)
refuse = lambda to, t, fy=False: (sent.append((to, t, fy)), (False, "[400] Refused: demo-main is a front agent whose hook cannot fetch held lines") if to == "demo-main" else (True, "[200] ok"))[1]
_o = send([finding("wait-end", 9103)], deliver=refuse)
check("2 a held note the agent cannot be given, with no project to fall back on: not counted as reached (it is tried again at the next run), nothing marked", [(to, m) for to, m, _f in msgs()] == [("demo-main", False)] and _o[1] == [], (sent, _o[1]))
recs = send([finding("wait-end", 9103)])[0]
check("2 the record of the send says it was held", [m.get("kind") for m in recs] == ["held"], recs)

# ---- 3. a front-only project: the chase of an unmoved finding (level 1) and the second level (level 2)
def lvl(f, n): f["escalate"] = n; f["tries"] = 5; return f
send([lvl(finding("wait-end", 9101, to="demo-builder", project="projects/demo"), 1)], front_only=True)
check("3 level 1: a front-only project's -main agent chases it, marked, for an item that waits on him", msgs() == [("demo-main", True, False)], sent)
_o = send([lvl(finding("wait-end", 9103, to="demo-builder", project="projects/demo"), 1)], front_only=True)
check("3 level 1 for an item that waits on nothing of his: held for the -main agent, unmarked; it counts as reached at level 1", msgs() == [("demo-main", False, True)] and [f.get("lvl") for f in _o[1]] == [1], (sent, _o[1]))
send([lvl(finding("wait-end", 9101, to="demo-builder", project="projects/demo"), 2)])
check("3 level 2: the -main agent, marked, for an item that waits on him", msgs() == [("demo-main", True, False)], sent)
_o = send([lvl(finding("wait-end", 9103, to="demo-builder", project="projects/demo"), 2)])
check("3 level 2 for an item that waits on nothing of his: held for the -main agent, unmarked; it counts as reached at level 2", msgs() == [("demo-main", False, True)] and [f.get("lvl") for f in _o[1]] == [2], (sent, _o[1]))
send([lvl(finding("wait-end", 9103, to="demo-other", mover="demo-other", project="projects/demo"), 1)])
check("3 level 1 in a project with a builder is the builder's, never a front agent's: unchanged, one unmarked message to the builder", msgs() == [("demo-builder", False, False)], sent)
_o = send([lvl(finding("wait-end", 9103, to="demo-builder", project="projects/demo"), 1)], front_only=True, deliver=refuse)
check("3 a level 1 held note the front agent cannot be given goes unmarked to the project's page key and counts as reached", [(to, m) for to, m, _f in msgs()] == [("demo-main", False), ("projects/demo", False)] and [f.get("lvl") for f in _o[1]] == [1], (sent, _o[1]))

# ---- 4. the fallback of a mover that cannot be reached
def builder_down(to, text, fyi=False):
    sent.append((to, text, fyi))
    return (False, "[404] no such session") if to == "demo-builder" else (True, "[200] ok")
_o = send([finding("wait-end", 9101, to="demo-builder", project="projects/demo")], deliver=builder_down)
check("4 an item that waits on him: the builder cannot be reached, the -main agent is told, marked, as before", [(to, m) for to, m, _f in msgs()] == [("demo-builder", False), ("demo-main", True)] and len(_o[1]) == 1, (sent, _o[1]))
_o = send([finding("wait-end", 9103, to="demo-builder", project="projects/demo")], deliver=builder_down)
check("4 an item that waits on nothing of his: the page key takes it, unmarked, never the -main agent marked; it counts as reached", [(to, m) for to, m, _f in msgs()] == [("demo-builder", False), ("projects/demo", False)] and len(_o[1]) == 1, (sent, _o[1]))

# ---- 5. the passes give their items to the delivery
def clear_state():
    for p in (T / "state/audit").glob("*.json"): p.unlink()
    sent.clear()
ZONE = dt.timezone(dt.timedelta(hours=4))                                                   # the instance timezone pinned above (Asia/Dubai, UTC+4, no DST)
local = lambda ts: dt.datetime.fromtimestamp(ts, ZONE).strftime("%Y-%m-%d %H:%M")
def written(pairs, ago):
    for _k, d in pairs: d["updated"] = d["written_at"] = now - ago * H; d["written_by"] = "demo-main"
    return dict(pairs)
front_moves = written([item(9401, mover="demo-main", state="doing", needs=["demo-main"], project="", next="demo-main: waiting for the build")], 1)
clear_state()
res = AR.filing_pass(now=now, items=front_moves, anchors={}, env=env(), dry=False)
check("5 the filing pass: a finding about an item its front agent moves, with no project, would go marked for him; it waits on nothing of his, so it is held for the -main agent", res.get("findings", 0) >= 1 and msgs() == [("demo-main", False, True)], (res, sent))
late = written([item(9402, mover="demo-main", state="doing", needs=["demo-main"], project="", next="demo-main: build it", wake=local(now - 2 * H))], 3)
clear_state()
res = AR.dates_pass(now=now, items=late, anchors={}, env=env(), dry=False)
check("5 the dates pass: a past wake on such an item (`stale`) is held the same way, not marked", res.get("findings", 0) == 1 and msgs() == [("demo-main", False, True)], (res, sent))
import inspect
from stackshot.audit import wait_loops as WL
check("5 the daily run gives its items to the delivery", 'deliver_findings(env, fresh, f"Board audit {label}", items)' in inspect.getsource(AR._run))
check("5 the wait-loop pass gives its items to the delivery", ', full) if fresh else' in inspect.getsource(WL))


for p in (T / "state/audit").glob("*.json"): p.unlink()
print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
