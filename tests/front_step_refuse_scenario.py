"""Scenario test for: a step that opens with a front agent is refused on an item another session moves — fixture data, no live store, no network.

A front agent (a user-facing agent on a project's agents map) gets no work notice and its own reminder wakes are refused, so a step it is given (or gives itself) on an item another session
moves can never fire. The create and update tools refuse a NEW or reworded open step of that kind (service/gates.py gate_front_step); the refusal says who to give the step to or message instead.

  1  create: a front agent's step on an item a background agent moves is refused (the refusal quotes the step, names the agent, its project, the mover and the way out), whoever writes it; nothing is stored
  2  allowed: the item's own mover as opener (the front agent's own item), a background agent as opener, an item nobody moves, an owner-moved item, a step that names no one
  3  update: a new step, an added line of next and a reworded step that open with a front agent are refused and the item stays byte for byte; a reword to a background agent and a done mark pass
  4  a step already held by a front agent is not judged again: an unrelated write, a rewrite of next that keeps the line, a re-sent line and a rebullet pass
  5  not judged: the server's own writes (the internal update), a script's sender, a failing roles read (one stderr line)
  6  front_step.held and month_count: the one test the gate and the monthly count share; the count's numbers (closed in 30 days, closed by someone else, open ones the gate would refuse now)

    tests/run-suite front_step_refuse        → exit 0 / 1"""
import contextlib, io, json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="frontrefuse-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's fleet store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects"): (T / d).mkdir(parents=True)
MAIN, SIDE, BUILD, REVIEW = "home-delta-main", "home-delta-desk", "home-delta-builder", "home-delta-review"
ECHO, PEER, OTHER = "home-echo-main", "home-echo-desk", "home-golf-main"      # echo: a front-only project of two front agents; golf: another front-only project
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate((MAIN, SIDE, BUILD, REVIEW, ECHO, PEER, OTHER), 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in U.items()}))
page = lambda **kw: {"title": "T", "name": "T", "org": "home", "tags": [], "type": "project", "session": "", "status": "active", "board": [], "board_open": 0, **kw}
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/delta": page(title="Delta", name="Delta", agents={MAIN: "front", SIDE: "answers questions", BUILD: "builds it", REVIEW: "reviews it"},
                           back_agents={BUILD: "builds it", REVIEW: "reviews it"}),
    "projects/echo": page(title="Echo", name="Echo", agents={ECHO: "front", PEER: "answers questions"}),
    "projects/golf": page(title="Golf", name="Golf", agents={OTHER: "front"}),
    "projects/solo": page(title="Solo", name="Solo")}}))
(T / "store/next-id").write_text("40"); (T / "store/anchors.json").write_text("{}")
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools")); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
def rd(g):
    g = str(g); g = g if not g[:1].isdigit() else "a" + g
    return json.loads((T / f"store/{g[0]}/{g[1:]}.json").read_text())
def raw(i): return (T / f"store/a/{i}.json").read_bytes()
now0 = time.time()
def put(i, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "- A thing\n- It lives here\n- Done when done", "status": "open",
        "updated": now0 - 60, "state_updated": now0 - 60, "confirmed": now0 - 60, "metadata": {"owner": BUILD, "project": "projects/delta", **meta}}))

from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.audit import front_step as FS; from stackshot.model import steps as ST; from stackshot.audit import audit_run as AR
from stackshot.service import client_reads as client_reads_svc
from stackshot.service import update as _update_svc
from stackshot.core import instance as _core_instance
from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import create as _wt_create
from stackshot.web.tools import update as _wt_update
from stackshot.service import telling
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
telling.tell_woken = lambda *a, **k: None
DESC = "- Goal: A thing\n- It lives here\n- Done when done"
OWNER = _core_instance.OWNER

def refusal(fn):
    try:
        return fn() and ""
    except Exception as e:  # noqa: BLE001
        return str(e)
def refused(msg): return msg.startswith("Refused:") and "opens with" in msg and "no work notice" in msg
def stored_next(i): return rd(i)["metadata"].get("next") or ""

# ---- 1. create: refused, whoever writes the step
msg = refusal(lambda: _wt_create.stackshot_create(subject="[home] waits on the handback", description=DESC, project="projects/delta", sender=MAIN, mover=BUILD, needs=[BUILD],
                                              next=f"{BUILD}: build it\n{MAIN}: after the handback, check it"))
check("1 create: a front agent's own step on an item a background agent moves is refused", refused(msg) and f'"{MAIN}: after the handback, check it"' in msg and f"{MAIN}, a user-facing agent of projects/delta" in msg, msg)
check("1 …the refusal names the mover and the way out: give the step to the mover or message it", f"{BUILD} moves the item" in msg and f'open it with "{BUILD}:"' in msg and f'message to projects/delta whose first line starts "For {MAIN},"' in msg and "send " not in msg, msg)
check("1 …and no item is stored", not (T / "store/a/40.json").exists() and not (T / "store/a/41.json").exists(), sorted(os.listdir(T / "store/a")))
msg = refusal(lambda: _wt_create.stackshot_create(subject="[home] the builder gives the front a step", description=DESC, project="projects/delta", sender=BUILD, mover=BUILD, needs=[BUILD],
                                              next=f"{MAIN}: confirm the wording\n{BUILD}: then build it"))
check("1 create: the mover writing a front agent's step on its own item is refused too, told to keep the step and message the front agent", refused(msg) and f"Keep the step with {BUILD}, hand {MAIN} the item with mover={MAIN}" in msg and f'starts "For {MAIN},"' in msg and "and message " not in msg, msg)
msg = refusal(lambda: _wt_create.stackshot_create(subject="[home] a second front agent", description=DESC, project="projects/delta", sender=REVIEW, mover=BUILD, needs=[BUILD], next=f"{SIDE}: look at it\n{BUILD}: then build it"))
check("1 create: another front agent's step is refused the same way", refused(msg) and SIDE in msg, msg)

# ---- 2. allowed
r = _wt_create.stackshot_create(subject="[home] the front agent's own item", description=DESC, project="projects/delta", sender=MAIN, mover=MAIN, next=f"{MAIN}: carry on\n{MAIN}: then close")
check("2 create: the item's own mover as the opener of its steps is accepted", r.startswith("created"), r)
r = _wt_create.stackshot_create(subject="[home] a background agent's step", description=DESC, project="projects/delta", sender=MAIN, mover=BUILD, needs=[BUILD], next=f"{REVIEW}: review it\n{BUILD}: then build it")
check("2 create: a background agent's step on another session's item is accepted", r.startswith("created"), r)
r = refusal(lambda: _wt_create.stackshot_create(subject="[home] the owner's call", description=DESC, project="projects/delta", sender=BUILD, mover=OWNER, needs=["decision"],
                                            ask="Decide: a or b · Recommend: yes · Stakes: none · By: no date", then=BUILD))
check("2 create: an item the owner moves, with a front agent's next on it, is not judged as a session's (control: the owner's own create passes)", r == "", r)
put(9, mover=BUILD, needs=[BUILD], next=f"{BUILD}: the item a check can name")
put(1, project="projects/solo", needs=[], next=f"{MAIN}: look at the page")           # a project with no builder and no -main agent: nobody moves the item
r = refusal(lambda: _wt_update.stackshot_update(item_id="a1", sender=SIDE, next=f"{MAIN}: look at the page\n{MAIN}: and the other page"))
check("2 update: a front agent's new step on an item nobody moves is accepted", r == "" and "other page" in stored_next(1), (r, client_reads_svc._item_mover(rd(1))))

# ---- 3. update
put(2, mover=BUILD, needs=[BUILD], next=f"{BUILD}: build it")
was = raw(2)
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a2", sender=MAIN, next=f"{BUILD}: build it\n{MAIN}: after the handback, look at it"))
check("3 update: a front agent adding its own step to an item a background agent moves is refused", refused(msg) and "after the handback" in msg and f"{BUILD} moves " in msg, msg)
check("3 …and the item is byte for byte as it was", raw(2) == was)
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a2", sender=BUILD, next=f"{BUILD}: build it\n{SIDE}: check the wording", check="item_closed a1"))
check("3 update: a builder adding a front agent's step is refused", refused(msg) and SIDE in msg and raw(2) == was, msg)
put(3, mover=BUILD, needs=[BUILD], next=f"{BUILD}: build it\n{BUILD}: then test it")
was = raw(3)
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a3", sender=BUILD, reword={"2": f"{MAIN}: then test it"}))
check("3 update: reword of an open step to one that opens with a front agent is refused", refused(msg) and "then test it" in msg and raw(3) == was, msg)
r = refusal(lambda: _wt_update.stackshot_update(item_id="a3", sender=BUILD, reword={"2": f"{REVIEW}: then test it"}))
check("3 update: reword of an open step to a background agent is accepted", r == "" and f"{REVIEW}: then test it" in stored_next(3), (r, stored_next(3)))
r = refusal(lambda: _wt_update.stackshot_update(item_id="a3", sender=BUILD, done=[1]))
check("3 update: marking a step done is not judged", r == "" and stored_next(3) == f"{REVIEW}: then test it", (r, stored_next(3)))

# ---- 4. what a front agent already holds is not judged again
put(4, mover=BUILD, needs=[BUILD], next=f"{BUILD}: build it\n{MAIN}: look at it once built")
r = refusal(lambda: _wt_update.stackshot_update(item_id="a4", sender=BUILD, priority="p2"))
check("4 an unrelated write to an item that carries a front agent's step passes", r == "" and rd(4)["metadata"]["priority"] == "p2", r)
r = refusal(lambda: _wt_update.stackshot_update(item_id="a4", sender=BUILD, next=f"{BUILD}: build it\n{MAIN}: look at it once built\n{BUILD}: then close it"))
check("4 a new line of the builder's own next beside the held front step passes", r == "" and stored_next(4).endswith(f"{BUILD}: then close it"), (r, stored_next(4)))
r = refusal(lambda: _wt_update.stackshot_update(item_id="a4", sender=BUILD, next=f"- {BUILD}: build it\n- **{MAIN}:** look at it once built\n- {BUILD}: then close it"))
check("4 the same lines re-sent with list markers and bold marks are the same steps", r == "", r)
r = refusal(lambda: _wt_update.stackshot_update(item_id="a4", sender=BUILD, dropped=[3], next=f"{BUILD}: build it\n{MAIN}: look at it once built", check="item_closed a9"))
check("4 dropping a line while the held front step stays passes", r == "", r)

# ---- 5. not judged: the server's own write, a script, a failing roles read
put(5, mover=BUILD, needs=[BUILD], next=f"{BUILD}: build it")
r = _update_svc._update("a5", next=f"{BUILD}: build it\n{MAIN}: look at it", sender=BUILD, check="item_closed a1")
check("5 the server's internal update is not judged by the tool gate", "Refused" not in r and MAIN in stored_next(5), r)
put(6, mover=BUILD, needs=[BUILD], next=f"{BUILD}: build it")
real_roles = _anc.session_roles
def boom(*a, **k): raise RuntimeError("roles unreadable")
_anc.session_roles = boom
errbuf = io.StringIO()
try:
    with contextlib.redirect_stderr(errbuf):
        msg = refusal(lambda: _wt_update.stackshot_update(item_id="a6", sender=BUILD, next=f"{BUILD}: build it\n{MAIN}: look at it", check="item_closed a1"))
finally:
    _anc.session_roles = real_roles
check("5 a failing roles read lets the write through and says so once on stderr", "no work notice" not in msg and "front-step gate" in errbuf.getvalue() and "roles unreadable" in errbuf.getvalue(), (msg, errbuf.getvalue()[:300]))
put(8, mover=BUILD, needs=[BUILD], next=f"{BUILD}: build it")
def retired_build(*a, **k): return {**real_roles(*a, **k), BUILD: {**real_roles(*a, **k)[BUILD], "retired": True}}
_anc.session_roles = retired_build
try:
    msg = refusal(lambda: _wt_update.stackshot_update(item_id="a8", sender=MAIN, next=f"{BUILD}: build it\n{MAIN}: look at it", check="item_closed a1"))
finally:
    _anc.session_roles = real_roles
check("5 a mover that is retired (not running) leaves a front agent's step allowed", "no work notice" not in msg and msg == "" and MAIN in stored_next(8), (msg, stored_next(8)))
guards_was = _cfg.CFG.setdefault("model", {}).get("guards")
_cfg.CFG["model"]["guards"] = False
try:
    put(7, mover=BUILD, needs=[BUILD], next=f"{BUILD}: build it")
    msg = refusal(lambda: _wt_update.stackshot_update(item_id="a7", sender=BUILD, next=f"{BUILD}: build it\n{MAIN}: look at it", check="item_closed a1"))
finally:
    if guards_was is None: _cfg.CFG["model"].pop("guards", None)
    else: _cfg.CFG["model"]["guards"] = guards_was
check("5 [model] guards = false switches the check off with the other write guards", "no work notice" not in msg, msg)

# ---- 6. the shared test and the monthly count
same = lambda a, b: a.lower() == b.lower()
isf = lambda n: n in (MAIN, SIDE)
check("6 held: a front agent's step on a session-moved item is held; its own mover, the owner, nobody, an outside party and a background agent are not",
      FS.held(f"{MAIN}: x", BUILD, isf, same) == MAIN and not FS.held(f"{MAIN}: x", MAIN, isf, same) and not FS.held(f"{OWNER}: x", BUILD, isf, same) and not FS.held(f"{MAIN}: x", "", isf, same)
      and not FS.held(f"{MAIN}: x", OWNER, isf, same) and not FS.held(f"{MAIN}: x", "an outside party", isf, same) and not FS.held(f"{REVIEW}: x", BUILD, isf, same) and not FS.held("a step with no opener", BUILD, isf, same))
ROLES = {MAIN: {"role": "front", "project": "projects/delta"}, SIDE: {"role": "front"}, BUILD: {"role": "background"}, REVIEW: {"role": "background"}, "old-front": {"role": "front", "retired": True}}
DAY = 86400.0
def stp(text, status, by="", at=0): return {"text": text, "status": status, "by": by, "at": at}
def citem(status, mover, steps, nxt=""):
    meta = {"owner": BUILD, "project": "projects/delta", "mover": mover, "needs": [mover] if mover not in (OWNER, "") else [], "steps": steps}
    if nxt: meta["next"] = nxt
    return {"status": status, "subject": "[home] x", "description": DESC, "metadata": meta, "updated": now0, "state_updated": now0}
items = {
    "c1": citem("completed", BUILD, [stp(f"{MAIN}: a", "done", BUILD, now0 - 2 * DAY), stp(f"{MAIN}: b", "done", MAIN, now0 - 3 * DAY), stp(f"{MAIN}: c", "dropped", REVIEW, now0 - 10 * DAY),
                                      stp(f"{MAIN}: old", "done", BUILD, now0 - 40 * DAY), stp(f"{REVIEW}: d", "done", BUILD, now0 - 1 * DAY), stp(f"{OWNER}: e", "done", BUILD, now0 - DAY),
                                      stp(f"{SIDE}: f", "done", "stackshot (backfill)", now0 - DAY), stp(f"{SIDE}: g", "done", "", now0 - DAY)]),
    "c2": citem("open", BUILD, [stp(f"{MAIN}: open one", "open"), stp(f"{BUILD}: open two", "open"), stp(f"{SIDE}: closed", "done", REVIEW, now0 - DAY)], nxt=f"{MAIN}: open one\n{BUILD}: open two"),
    "c3": citem("open", MAIN, [stp(f"{MAIN}: its own", "open")], nxt=f"{MAIN}: its own"),
    "c4": citem("open", OWNER, [stp(f"{MAIN}: his item", "open")], nxt=f"{MAIN}: his item"),
}
c = FS.month_count(items, ROLES, now0)
check("6 month_count: closed in the last 30 days is the front agents' closed steps (a 40-day-old one, a background agent's and the owner's are left out)", c["closed"] == 6, c)
check("6 …by_other counts those a session other than the front agent closed (a server mark and an unsigned close are no session; a front agent's own close is not 'someone else')", c["by_other"] == 3, c)
check("6 …open counts the open steps the gate would refuse now: the front step on a session-moved item, not the front agent's own item, not the owner's", c["open"] == 1 and c["ids"] == ["c2"], c)
line = AR.front_step_count([], items, AR.Env(roles=ROLES, fallback=lambda p: MAIN, builder=lambda p: BUILD), now0)
month = time.strftime("%Y-%m", time.localtime(now0))
check("6 front_step_count: the first run of a month returns the count with its month and the summary line", line[0] and line[0]["month"] == month and "3 of 6 closed by someone else" in line[1] and "1 open step(s)" in line[1], line)
again = AR.front_step_count([{"front_step_count": line[0]}], items, AR.Env(roles=ROLES, fallback=lambda p: MAIN, builder=lambda p: BUILD), now0)
check("6 …a month a record already holds one for is not counted again", again == (None, ""), again)

# ---- 7. a front-only project: a step that opens with a live front peer of the item's own project passes (the step hand-over moves the item to it); every other front agent is still refused, with the working paths named
r = _wt_create.stackshot_create(subject="[home] a peer's step", description=DESC, project="projects/echo", sender=ECHO, mover=ECHO, next=f"{ECHO}: draft it\n{PEER}: check it")
check("7 create: in a front-only project a live front peer's step on an item another front agent moves is accepted", r.startswith("created"), r)
put(60, project="projects/echo", owner=ECHO, mover=ECHO, needs=[], next=f"{ECHO}: draft it")
r = refusal(lambda: _wt_update.stackshot_update(item_id="a60", sender=ECHO, next=f"{ECHO}: draft it\n{PEER}: check it"))
check("7 update: …and a new line of next opening with the peer is accepted too", r == "" and PEER in stored_next(60), (r, stored_next(60)))
r = refusal(lambda: _wt_update.stackshot_update(item_id="a60", sender=ECHO, reword={"2": f"{PEER}: look again"}))
check("7 update: …and a reword of the second step to the peer", r == "" and stored_next(60).endswith(f"{PEER}: look again"), (r, stored_next(60)))
# a peer's step needs an open step in front of it: the step hand-over follows a done step, so as the first open step nothing would ever move the item
was = raw(60)
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a60", sender=ECHO, reword={"1": f"{PEER}: draft it"}))
check("7 update: a reword that makes the peer's step the first open step is refused, naming the ways out, and the item is untouched",
      refused(msg) and "Put an open step before it" in msg and f"mover={PEER}" in msg and f'starts "For {PEER},"' in msg and raw(60) == was, msg)
before_n = len(os.listdir(T / "store/a"))
msg = refusal(lambda: _wt_create.stackshot_create(subject="[home] a peer first", description=DESC, project="projects/echo", sender=ECHO, mover=ECHO, next=f"{PEER}: check first\n{ECHO}: then publish"))
check("7 create: the peer's step as the first open step is refused (nothing would move the item to it) and nothing is stored", refused(msg) and "Put an open step before it" in msg and len(os.listdir(T / "store/a")) == before_n, msg)
# front_only is read only for a live front agent of the item's own project: a failing read touches that case alone
real_fo = _anc.front_only
def fo_boom(*a, **k): raise RuntimeError("registry unreadable")
put(65, project="projects/echo", owner=ECHO, mover=ECHO, needs=[], next=f"{ECHO}: draft it")
_anc.front_only = fo_boom
try:
    msg_other = refusal(lambda: _wt_update.stackshot_update(item_id="a65", sender=ECHO, next=f"{ECHO}: draft it\n{OTHER}: check it"))
    msg_peer = refusal(lambda: _wt_update.stackshot_update(item_id="a65", sender=ECHO, next=f"{ECHO}: draft it\n{PEER}: check it"))
finally:
    _anc.front_only = real_fo
check("7 a failing front_only read: another project's front agent is still refused (the read is not made for it), and so is the peer (the old behavior)", refused(msg_other) and refused(msg_peer), (msg_other, msg_peer))
put(61, project="projects/echo", owner=ECHO, mover=ECHO, needs=[], next=f"{ECHO}: draft it")
was = raw(61)
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a61", sender=ECHO, next=f"{ECHO}: draft it\n{OTHER}: check it"))
check("7 a front agent of another project is refused, even in a front-only project, and the item is untouched", refused(msg) and f"{OTHER}, a user-facing agent of projects/golf" in msg and raw(61) == was, msg)
check("7 …the tail names the ways that work (the hand-over and the `For <agent>,` line to the agent's page), not a plain message to the front agent",
      f"Keep the step with {ECHO}, hand {OTHER} the item with mover={OTHER}" in msg and f'ask {OTHER} with a message to projects/golf whose first line starts "For {OTHER},"' in msg and "and message " not in msg and "send " not in msg, msg)
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a61", sender=BUILD, next=f"{ECHO}: draft it\n{OTHER}: check it", check="item_closed a1"))
check("7 …and a sender who is not the mover is told to give the step to the mover or to ask through the page", refused(msg) and f'open it with "{ECHO}:"' in msg and f'starts "For {OTHER},"' in msg and "send " not in msg, msg)
def retired_peer(*a, **k): return {**real_roles(*a, **k), PEER: {**real_roles(*a, **k)[PEER], "retired": True}}
_anc.session_roles = retired_peer
try:
    msg = refusal(lambda: _wt_update.stackshot_update(item_id="a61", sender=ECHO, next=f"{ECHO}: draft it\n{PEER}: check it", check="item_closed a1"))
finally:
    _anc.session_roles = real_roles
check("7 a retired peer is no peer: the gate does what it did before for a retired opener (it judges live front agents only, so this gate does not refuse the step)", msg == "" and f"{PEER}: check it" in stored_next(61), msg)
put(62, project="projects/delta", owner=BUILD, mover=BUILD, needs=[BUILD], next=f"{BUILD}: build it")
was = raw(62)
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a62", sender=BUILD, next=f"{BUILD}: build it\n{SIDE}: check it", check="item_closed a1"))
check("7 a project with a background agent is unchanged: a front agent of the same project is refused, with the new tail", refused(msg) and f"{SIDE}, a user-facing agent of projects/delta" in msg and f'starts "For {SIDE},"' in msg and raw(62) == was, msg)
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a62", sender=MAIN, next=f"{BUILD}: build it\n{SIDE}: check it", check="item_closed a1"))
check("7 …whoever writes it", refused(msg) and f'open it with "{BUILD}:"' in msg and raw(62) == was, msg)
isf7 = lambda n: n in (ECHO, PEER)
check("7 held: the shared test still holds a front agent's step on a session-moved item; the peer exemption is the gate's and the count's own (front_step.is_peer)",
      FS.held(f"{PEER}: x", ECHO, isf7, same) == PEER)
rows7 = {ECHO: {"role": "front", "project": "projects/echo"}, PEER: {"role": "front", "project": "projects/echo"}, OTHER: {"role": "front", "project": "projects/golf"}, "gone": {"role": "front", "project": "projects/echo", "retired": True}}
it7 = {"metadata": {"project": "projects/echo"}}; fo7 = lambda p: p == "projects/echo"
check("7 is_peer: a live front agent of the item's project in a front-only project; not another project's, a retired one, a project with a builder, no test given or one that fails",
      FS.is_peer(PEER, it7, rows7, fo7) and not FS.is_peer(OTHER, it7, rows7, fo7) and not FS.is_peer("gone", it7, rows7, fo7) and not FS.is_peer(PEER, it7, rows7, lambda p: False)
      and not FS.is_peer(PEER, it7, rows7, None) and not FS.is_peer(PEER, {"metadata": {}}, rows7, fo7) and not FS.is_peer(PEER, it7, rows7, lambda p: 1 / 0))
fell = {"metadata": {"project": "projects/echo", "handover": {"step": FS.step_hash(f"{PEER}: x"), "kind": "fallback", "to": PEER}}}
check("7 is_peer: a step the hand-over fell back on (the peer was down) is no peer's step, so the reword applies again; another step of the item, or a moved record, still is one",
      not FS.is_peer(PEER, fell, rows7, fo7, f"{PEER}: x") and FS.is_peer(PEER, fell, rows7, fo7, f"{PEER}: y") and FS.is_peer(PEER, fell, rows7, fo7)
      and FS.is_peer(PEER, {"metadata": {**fell["metadata"], "handover": {**fell["metadata"]["handover"], "kind": "moved"}}}, rows7, fo7, f"{PEER}: x"))
calls7 = []
FS.is_peer(OTHER, it7, rows7, lambda p: calls7.append(p) or True); FS.is_peer("gone", it7, rows7, lambda p: calls7.append(p) or True)
check("7 is_peer reads the project only for a live front agent of the item's own project (not another project's, not a retired one)", calls7 == [], calls7)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.stdout.flush()
os._exit(1 if fails else 0)
