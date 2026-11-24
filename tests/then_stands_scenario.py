"""Scenario test for: `then` stands only while the user moves the item — fixture data, no live store, no network, no server socket.

`then` is the session that takes an item after the user's answer or step. A write stores it only while the user is the alive mover (or the picker of a waiting item); anywhere else it is data nobody reads,
so the write drops it and the reply says so ("then dropped: it stands only while <the user> moves the item; to hand it on, set mover=<session>"), never a refusal. A stored `then` that is no longer
read is dropped by the next save of that item, on any path. `clear_then` and then="none" clear it as before. A waiting item whose picker is an agent keeps the agent as its `mover`, so the wake and the
`after` release find it with no stored `then`. Covered:

  1  model           stray_then and settle's third result ({"then": ""}) for an alive agent mover, a user mover, a wait an agent picks up and a wait the user picks up
  2  create          an agent's item drops `then` with the note; the user's item (a decision) keeps it
  3  update          an update on an agent's item drops `then` (named alone, or beside a mover the write sets) with the note
  4  the user's step  a write that gives the user a step or a decision keeps `then`; a write that moves the item off the user drops it
  5  user picker     a waiting item the user picks up keeps `then` through a save, and the wake's turn to the user hands it on (turn_to_owner)
  6  agent picker    a waiting item an agent picks up drops it
  7  no stored then  the wake pass, the watchers' time wait and the `after` release find the agent with no stored `then`
  8  clears          clear_then and then="none" still clear it
  9  notice words    then_part names `, then <agent>` beside the user and `, mover <agent>` for an agent that picks a wait up, and never the notice's own recipient
  10 edges           [model] guards = false, a hand-back that drops nothing, a filing-only write, the wake notice's recipient, the retired [model] watchers key

    tests/run-suite then_stands        → exit 0 / 1"""
import json, logging, os, pathlib, re, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="thenstands-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"), owner=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[zed] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
toml, n = re.subn(r'(?m)^(\[audit\][^\n]*\n)enabled = false', r'\g<1>enabled = true', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
(T / "home/.claude/sessions").mkdir(parents=True)
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "brain/projects", "transcripts/-zed"): (T / d).mkdir(parents=True)
NAMES = ("zed-stew", "zed-back", "zed-helper", "zed-front")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/zedwork": {"title": "Zedwork", "name": "Zedwork", "org": "zed", "tags": [], "type": "project",
                                                                                   "session": "zed-stew", "status": "active", "board": [], "board_open": 0,
                                                                                   "agents": {"zed-front": "the front", "zed-back": "the back", "zed-helper": "the helper"},
                                                                                   "back_agents": {"zed-back": "the back", "zed-helper": "the helper"}}}}))
(T / "brain/projects/zedwork.md").write_text("---\ntitle: Zedwork\ndisplay-name: zed-stew\nagents:\n  zed-front: the front\n  background:\n    zed-back: the back\n    zed-helper: the helper\n---\n\n# Zedwork\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, status="open", subject=None, store="a", **meta):
    su = now0 - 10 * DAY
    (T / f"store/{store}/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[zed] item {i}", "description": DESC, "status": status,
                                                             "updated": su, "state_updated": su, "confirmed": su,
                                                             "metadata": {"owner": U["zed-front"], "project": "projects/zedwork", "next": "zed-back: do the thing", **meta}}))
def rd(i, store="a"): return json.loads((T / f"store/{store}/{i}.json").read_text())
def mt(i, store="a"): return rd(i, store)["metadata"]
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.web.tools import create as _wt_create; from stackshot.web.tools import update as _wt_update; from stackshot.model import model; from stackshot.waits import waiting, watchers as wk
from stackshot.model import cold_call as cold
from stackshot.model import holders as _holders
from stackshot.model import migration as M
from stackshot.audit import audit_run as AR
from stackshot.core import config as _cfg
from stackshot.service import store as _service_store
from stackshot.service import update as _update_svc
from stackshot.service import migrations as migsvc
from stackshot.service import watching as watching_svc
from stackshot.service import wakes as wakes_svc
from stackshot.service import event_waits as evwaits_svc
from stackshot.service import telling
from stackshot.service import answer_handover as handover_svc
from stackshot.service import wait_gates as wait_gates_svc, released as released_svc
from stackshot.service import wait_fixes as _wait_fixes_svc
from stackshot.fleet import liveness as LV
from stackshot.web import home
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
SENT = []
telling.tell_woken = lambda gid, owner, note, tag="wake": SENT.append((gid, owner, note, tag))
telling.front_sender = lambda who: False
released_svc._own_repo = lambda: "acme/widgets"
wait_gates_svc._evwait_preread = lambda kind, phrase: None
evwaits_svc.evw_boxes = lambda: {}
LV.puller_online = lambda rec: bool(rec)
(T / "state").mkdir(parents=True, exist_ok=True); (T / "state/waiting.json").write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
CFG = _cfg.CFG.setdefault("model", {}); CFG.update(guards=True, pause=False)
ZONE_HOURS = 4
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_HOURS * 3600))
BACK, HELP, FRONT = "zed-back", "zed-helper", "zed-front"
OWN = model.owner_display()
LEG = model.LEGACY_PICKER_KEY
FUT = day(5)

def its(**meta): return {"status": "open", "metadata": {"project": "projects/zedwork", **meta}}
from stackshot.core import instance as _core_instance
OWNER =_core_instance.OWNER
GOAL = "- Goal: A thing\n- It lives here\n- Done when done"
NOTE = f"then dropped: it stands only while {OWNER} moves the item; to hand it on, set mover=<session>"
ASK = "Decide: whether to ship it \u00b7 Recommend: yes \u00b7 Stakes: none \u00b7 By: no date"
SET_AT = now0 - 5000.0
def upd(n, **kw): return _wt_update.stackshot_update(item_id=f"a{n}", sender=BACK, **kw)
def rdg(g):
    g = str(g)
    return json.loads((T / f"store/{g[0]}/{g[1:]}.json").read_text())
def made(r): return r.split()[1]
def told_to(n, who): return any(x[0] == f"a{n}" and x[1] in (who, U[who]) for x in SENT)
def user_item(n, **meta):
    """an item at the user's decision, an agent stored as `then`"""
    item(n, needs=["decision"], ask=ASK, state="your-call", next=f"{OWN}: pick one", **{"then": HELP, **meta})

# ================================================================ 1. the model
agent = its(mover=BACK, then=HELP)
check("1 an alive agent mover with a then: the then is stray, settle drops it alone", model.stray_then(agent) and model.settle(agent) == {"then": ""}, model.settle(agent))
check("1 the user as alive mover keeps it: not stray, settle says nothing", not model.stray_then(its(mover=OWN, then=HELP, needs=["decision"], ask=ASK)) and model.settle(its(mover=OWN, then=HELP, needs=["decision"], ask=ASK)) is None, None)
check("1 an agent picking up a wait: stray", model.stray_then(its(mover=HELP, then=BACK, wait_kind="time", hold=True, wake=FUT, needs=[HELP])), None)
check("1 the user picking up a wait: not stray", not model.stray_then(its(mover=OWN, then=HELP, wait_kind="time", hold=True, wake=FUT, needs=[BACK])), None)
check("1 a closed item is never stray", not model.stray_then({"status": "completed", "metadata": {"project": "projects/zedwork", "mover": BACK, "then": HELP}}) and model.settle({"status": "completed", "metadata": {"mover": BACK, "then": HELP}}) is None, None)
_old = its(mover=OWN, then=HELP, wait_kind="time", hold=True, wake=FUT, needs=[BACK], **{LEG: BACK})
check("1 a mover change that leaves an agent picker takes the stray then with it", model.settle(_old, True, None, True) == {"mover": "", "then": ""}, model.settle(_old, True, None, True))
check("1 no then, nothing to drop",not model.stray_then(its(mover=BACK)) and model.settle(its(mover=BACK)) is None, None)

# ================================================================ 2. create
r = _wt_create.stackshot_create(subject="[zed] an agent's item with a then", description=GOAL, project="projects/zedwork", sender=BACK, mover=HELP, next=f"{HELP}: build it", then=BACK)
m_ = rdg(made(r))["metadata"]
check("2 create, an agent as mover and a then: created, then dropped, the reply says so", r.startswith("created") and NOTE in r and "then" not in m_ and m_.get("mover") == HELP, (r, m_))
r = _wt_create.stackshot_create(subject="[zed] the default mover with a then", description=GOAL, project="projects/zedwork", sender=BACK, next=f"{HELP}: build it", then=BACK)
m_ = rdg(made(r))["metadata"]
check("2 create, no mover named (an agent moves it by default) and a then: dropped with the note", r.startswith("created") and NOTE in r and "then" not in m_, (r, m_))
r = _wt_create.stackshot_create(subject="[zed] the user's decision", description=GOAL, project="projects/zedwork", sender=BACK, mover=OWN, needs=["decision"], ask=ASK, then=HELP)
m_ = rdg(made(r))["metadata"]
check("2 create, the user as mover at a decision: the then stays, no note", r.startswith("created") and NOTE not in r and m_.get("then") == HELP, (r, m_))
r = _wt_create.stackshot_create(subject="[zed] an agent's item, no then", description=GOAL, project="projects/zedwork", sender=BACK, mover=HELP, next=f"{HELP}: build it")
check("2 create with no then: no note", r.startswith("created") and NOTE not in r, r)

# ================================================================ 3. update on an agent's item
item(20, mover=BACK)
r = upd(20, then=HELP)
check("3 update, a then alone on an agent's item: dropped, the reply says so", NOTE in r and "then" not in mt(20) and mt(20).get("mover") == BACK, (r, mt(20)))
item(21, mover=HELP)
r = upd(21, mover=BACK, then=HELP, next=f"{BACK}: take it")
check("3 update, a mover the write names and a then beside it: the mover is stored, the then dropped with the note", NOTE in r and mt(21).get("mover") == BACK and "then" not in mt(21), (r, mt(21)))
item(22, mover=BACK, then=HELP)
r = upd(22, next=f"{BACK}: carry on")
check("3 update, a stored then that stands beside an agent (a write about something else): the save drops it", "then" not in mt(22) and mt(22).get("mover") == BACK, (r, mt(22)))
item(23)
r = upd(23, then=HELP)
check("3 update, an item with no mover stored (the default mover is an agent): a then is dropped", NOTE in r and "then" not in mt(23), (r, mt(23)))
item(24, mover=BACK)
r = upd(24, next=f"{BACK}: carry on")
check("3 update, nothing about then: no note", NOTE not in r, r)
from stackshot.service import writes as _writes_svc
item(25, mover=BACK, then=HELP)
_writes_svc.save("a25", rd(25))
check("3 any other save (a server's own write) drops a stored then that stands beside an agent", "then" not in mt(25) and mt(25).get("mover") == BACK, mt(25))
item(26, mover=OWN, then=HELP, needs=["decision"], ask=ASK, state="your-call", next=f"{OWN}: pick one")
_writes_svc.save("a26", rd(26))
check("3 …and keeps the one beside the user", mt(26).get("then") == HELP, mt(26))

# ================================================================ 4. the user's step keeps it; moving the item off him drops it
item(30, mover=BACK)
r = upd(30, mover=OWN, step="press the button", then=HELP)
check("4 a write that gives the user a step keeps the then, no note", NOTE not in r and mt(30).get("then") == HELP and mt(30).get("mover") == OWN, (r, mt(30)))
r = upd(30, mover=BACK, step="none", next=f"{BACK}: carry on")
check("4 …a write that moves the item back to an agent drops it (the mover was his, the then goes with it)", "then" not in mt(30) and mt(30).get("mover") in (BACK, None), (r, mt(30)))
user_item(31)
r = upd(31, then=BACK)
check("4 a decision item: a new then is kept, no note", NOTE not in r and mt(31).get("then") == BACK, (r, mt(31)))
item(32, mover=BACK)
r = upd(32, needs=["decision"], ask=ASK, then=HELP)
check("4 a write that turns an agent's item into the user's decision keeps the then", NOTE not in r and mt(32).get("then") == HELP and "decision" in (mt(32).get("needs") or []), (r, mt(32)))
user_item(33)
r = upd(33, clear_needs=True, clear_next=True, next=f"{BACK}: carry on")
check("4 a write that takes the item off the user's decision: the then is the mover again and is gone, no stray left", "then" not in mt(33) and mt(33).get("mover") in (HELP, None), (r, mt(33)))
item(34, mover=OWN, then=HELP, next=f"{OWN}: press the button")
r = upd(34, mover=BACK, clear_next=True, next=f"{BACK}: carry on")
check("4 a write that sets an agent as mover on the user's step item drops the then with it", "then" not in mt(34) and mt(34).get("mover") == BACK, (r, mt(34)))

# ================================================================ 5. a waiting item the user picks up keeps the then
UW = dict(wait_kind="time", hold=True, needs=[BACK], watch={"set_at": SET_AT})
item(40, mover=OWN, then=HELP, wake=FUT, **UW)
check("5 the user as the wait's picker: not stray", not model.stray_then(rd(40)) and model.derive(rd(40), now0).wait.mover == OWN, model.derive(rd(40), now0))
r = upd(40, next=f"{BACK}: wait for it")
check("5 a save on the waiting item keeps the then, no note", NOTE not in r and mt(40).get("then") == HELP and mt(40).get("mover") == OWN, (r, mt(40)))
item(41, mover=OWN, then=HELP, wake=day(-1), **UW)
SENT.clear(); watching_svc.watch_pass()
m_ = mt(41)
check("5 the wake turns it to the user (turn_to_owner): his decision is up, the stored then is the one who takes it after him", m_.get("needs") == ["decision"] and m_.get("then") == HELP and "mover" not in m_ and "hold" not in m_ and "wait_kind" not in m_, m_)
check("5 …and the arrival is owed to the user, not to the then", (m_.get("woke") or {}).get("to") == OWN and not told_to(41, HELP), (m_.get("woke"), SENT))
_out = {}
item(42, mover=OWN, then=HELP, wake=day(-1), **UW)
watching_svc.watch_fire("a42", "time", now0, _out)
check("5 watch_fire on it: the same turn", mt(42).get("then") == HELP and mt(42).get("needs") == ["decision"], (mt(42), _out))

# ================================================================ 6. a waiting item an agent picks up drops it
AW = dict(wait_kind="time", hold=True, watch={"set_at": SET_AT})
item(50, mover=HELP, then=BACK, wake=FUT, needs=[HELP], **{k: v for k, v in AW.items()})
check("6 an agent as the wait's picker: stray, settle drops the then alone", model.stray_then(rd(50)) and model.settle(rd(50)) == {"then": ""}, model.settle(rd(50)))
r = upd(50, next=f"{HELP}: wait for it")
check("6 a save on the waiting item drops it, the picker stays", "then" not in mt(50) and mt(50).get("mover") == HELP and mt(50).get("wait_kind") == "time", (r, mt(50)))
item(51, mover=HELP, wake=FUT, needs=[HELP], **AW)
r = upd(51, then=BACK, wait_basis=f"a soak ends {FUT}")
check("6 a then written on it is dropped with the note", NOTE in r and "then" not in mt(51), (r, mt(51)))
item(52, mover=OWN, then=HELP, wake=FUT, **UW)
r = upd(52, mover=BACK, next=f"{BACK}: take it over", wait_basis=f"a soak ends {FUT}")
check("6 a write that makes an agent the picker takes the then with it", "then" not in mt(52) and mt(52).get("mover") == BACK, (r, mt(52)))

# ================================================================ 7. the wake and the after release find the agent with no stored then
item(60, mover=HELP, wake=day(-1), needs=[HELP], **AW)
SENT.clear(); watching_svc.watch_pass()
m_ = mt(60)
check("7 the watchers' time wait ends: the picker moves it, nothing stored as then, and it is told", m_.get("mover") == HELP and "then" not in m_ and "wait_kind" not in m_ and "hold" not in m_ and told_to(60, HELP), (m_, SENT))
item(61, hold=True, wake=day(-1), mover=HELP)
SENT.clear(); woke = wakes_svc.wake_pass()
m_ = mt(61)
check("7 the wake pass on an old hold: the stored agent mover moves it, no then needed", "hold" not in m_ and "wake" not in m_ and m_.get("mover") == HELP and "then" not in m_ and model.derive(rd(61), now0).mover == HELP, (m_, woke))
item(63, hold=True, after=["a64"], mover=HELP, needs=[HELP])
item(64, mover=BACK)
_p = rd(64); _p["status"] = "completed"; _p["outcome"] = "done"; (T / "store/a/64.json").write_text(json.dumps(_p))
SENT.clear(); wakes_svc.release_after("a64", "done", "", BACK)
m_ = mt(63)
check("7 the after release: the stored picker moves it, no then, and it is told", "hold" not in m_ and "after" not in m_ and m_.get("mover") == HELP and "then" not in m_ and model.derive(rd(63), now0).mover == HELP and told_to(63, HELP), (m_, SENT))
item(65, hold=True, wake=day(-1), mover=OWN, then=HELP)
SENT.clear(); wakes_svc.wake_pass()
check("7 a stored legacy shape (the user as mover beside a then, hold due) is no longer rewritten into a picker by the wake: the mover and the then stay as stored, for the migration", mt(65).get("mover") == OWN and mt(65).get("then") == HELP and "hold" not in mt(65), (mt(65), SENT))

# ================================================================ 8. clear_then and then="none"
user_item(70)
r = upd(70, clear_then=True)
check("8 clear_then on a decision item: the then goes, no note", "then" not in mt(70) and NOTE not in r, (r, mt(70)))
user_item(71)
r = upd(71, then="none")
check('8 then="none" on a decision item: the then goes, no note', "then" not in mt(71) and NOTE not in r, (r, mt(71)))
item(72, mover=BACK, then=HELP)
r = upd(72, then="none")
check('8 then="none" on an agent item that stores a stray then: gone, no note', "then" not in mt(72) and NOTE not in r, (r, mt(72)))
item(73, mover=BACK, then=HELP)
r = upd(73, clear_then=True)
check("8 clear_then on an agent item that stores a stray then: gone, no note", "then" not in mt(73) and NOTE not in r, (r, mt(73)))
r = _wt_create.stackshot_create(subject="[zed] then none on create", description=GOAL, project="projects/zedwork", sender=BACK, mover=HELP, next=f"{HELP}: build it", then="none")
check('8 create with then="none": created, nothing stored, no note', r.startswith("created") and NOTE not in r and "then" not in rdg(made(r))["metadata"], r)

# ================================================================ 9. the notice's words
def _g(**meta): return {**its(**meta), "gid": "a999"}
alive_user = _g(mover=OWN, then=HELP, needs=["decision"], ask=ASK)
agent_pick = _g(mover=HELP, wake=FUT, needs=[HELP], **AW)
user_pick = _g(mover=OWN, then=HELP, wake=FUT, **UW)
check("9 an alive item the user moves: `, then <agent>`, as before", telling.then_part(alive_user) == f", then {HELP}", telling.then_part(alive_user))
check("9 a wait the user picks up: `, then <agent>`, as before", telling.then_part(user_pick) == f", then {HELP}", telling.then_part(user_pick))
check("9 a wait an agent picks up: `, mover <agent>`, no longer `, then <agent>`", telling.then_part(agent_pick) == f", mover {HELP}" and telling.then_label(agent_pick) == HELP, (telling.then_part(agent_pick), telling.then_label(agent_pick)))
check("9 the notice's own recipient is not named again", telling.then_part(agent_pick, to=HELP) == "" and telling.then_part(alive_user, to=HELP) == "" and telling.then_part(agent_pick, to=BACK) == f", mover {HELP}", telling.then_part(agent_pick, to=HELP))
check("9 an agent's alive item names no then", telling.then_part(_g(mover=BACK)) == "" and telling.then_part(_g(mover=BACK, then=HELP)) == "", telling.then_part(_g(mover=BACK, then=HELP)))

# ================================================================ 10. the edges: guards off, a hand-back, a filing write, the wake notice, the retired switch
CFG.update(guards=False)
try:
    item(90, mover=BACK)
    r = upd(90, then=HELP)
finally:
    CFG.update(guards=True)
check("10 [model] guards = false: a then on an agent's item is left as written, no note", NOTE not in r and mt(90).get("then") == HELP, (r, mt(90)))
item(91, mover=OWN, then=HELP, needs=["decision"], ask=ASK, state="your-call", next=f"{OWN}: pick one")
r = upd(91, clear_needs=True, clear_next=True, next=f"{HELP}: carry on")
check("10 a hand-back whose then becomes the mover: the mover line says so, nothing else was dropped, so the reply carries no `then dropped` note", NOTE not in r and "then" not in mt(91) and mt(91).get("mover") == HELP, (r, mt(91)))
item(92, mover=BACK, then=HELP)
r = upd(92, priority="p1")
check("10 a filing-only write (a priority) leaves an already stored stray then as it is, with no note: the next real write or save drops it", NOTE not in r and mt(92).get("then") == HELP, (r, mt(92)))
r = upd(92, next=f"{BACK}: carry on")
check("10 …and the next write that is not a filing write drops it", "then" not in mt(92), (r, mt(92)))
user_item(93)      # the user's decision, HELP stored as the then
SENT.clear(); wakes_svc.wake_tell(U[HELP], [("a93", rd(93), "woke", "as the one who takes it after him", False)])
_txt = " ".join(x[2] for x in SENT)
check("10 the wake notice to the session named in then does not name it again (`to=` is the recipient)", len(SENT) == 1 and f", then {HELP}" not in _txt and "a93" in _txt, SENT)
SENT.clear(); wakes_svc.wake_tell(U[BACK], [("a93", rd(93), "woke", "as the keeper", False)])
_txt = " ".join(x[2] for x in SENT)
check("10 …while a notice to another session names it", len(SENT) == 1 and f", then {HELP}" in _txt, SENT)
_held, _recs = [], []
_rl, _rt = wakes_svc._router_live, wakes_svc._routing
_real = (_rl.holds, _rl.stash, _rt.record)
_rl.holds = lambda project, session, *a, **k: True; _rl.stash = lambda nid, text: _held.append(text); _rt.record = lambda *a, **k: (_recs.append(k.get("text", "")) or "n1")
try:
    wakes_svc.wake_tell(U[HELP], [("a93", rd(93), "woke", "as the keeper", False)])
    _own = (list(_recs), list(_held)); _recs.clear(); _held.clear()
    wakes_svc.wake_tell(U[BACK], [("a93", rd(93), "woke", "as the keeper", False)])
finally:
    _rl.holds, _rl.stash, _rt.record = _real
check("10 the notice held for the router does not name its own recipient either, and names the then to another session", len(_own[0]) == 1 and f", then {HELP}" not in _own[0][0] and f", then {HELP}" not in _own[1][0]
      and len(_recs) == 1 and f", then {HELP}" in _recs[0] and f", then {HELP}" in _held[0], (_own, _recs, _held))
import subprocess
stale = T / "stale.toml"; stale.write_text(re.sub(r"(?m)^\[model\]", "[model]\nwatchers = false", toml, count=1), encoding="utf-8")
cp = subprocess.run([sys.executable, "-I", f"{STACK}/stackshot/core/config.py", "check"], env={**os.environ, "STACKSHOT_CONFIG": str(stale)}, capture_output=True, text=True, timeout=60)
check("10 a file that still carries [model] watchers = false loads and passes `config.py check`", cp.returncode == 0, (cp.returncode, cp.stdout[-300:], cp.stderr[-300:]))
cp = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); from stackshot.core import config; print('\\n'.join(config.notes()))", STACK], env={**os.environ, "STACKSHOT_CONFIG": str(stale)}, capture_output=True, text=True, timeout=60)
check("10 …and its notes carry the one line about the retired key", cp.returncode == 0 and cp.stdout.count("[model] watchers is retired") == 1, (cp.returncode, cp.stdout[-300:], cp.stderr[-300:]))
check("10 …while a file without it carries none", "watchers is retired" not in "\n".join(_cfg.notes({"model": {"guards": True}})), None)

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": then stands scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
