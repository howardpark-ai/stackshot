"""Scenario test for a project with no builder: an answered step of the owner goes to the session the item's next open step names, and any session some project page lists may hand an item of
that project to one of its front agents — fixture data (English stand-in text), no live store, no network.

Covers: (1) the incident: in a project whose page lists only front agents (a general -main agent and a second front agent), an item on hold with a wake, whose post_wake_mover is the -main agent,
whose contact and next open step are the second front agent's, waits on the owner's step; once he answers it the item lands on the second front agent (the step's owner line), not on -main; with no
such step the item's stored contact takes it; with neither, -main keeps it as before; a project that has a builder still hands the answer to its builder; a stored `then` still wins.
(2) one front agent's `mover=` to another front agent of the same builderless project is accepted, with a note, and the target is told by a notice; the refusal stays for a session no page lists,
for a target that is not a front agent of the item's own project, and (as a substitution by the builder) for a project that has one.
(3) the sender need not belong to the project: a front agent or a background agent of another project hands an item of the builderless project to its front agent through `mover=`, the target
is told, and the reply says so; a project with a builder still substitutes it; a target that is another project's front agent, a session no page lists as the sender, a retired sender or target,
and a project with a builder substitutes it for `then` / `post_wake_mover` as before.
(4) `then=` and `post_wake_mover=` take the same exception as `mover=`: a listed session names a front agent of a front-only project in them, nothing tells the target by a hand-off notice (the owner's answer or the wake
moves the item), and the refusals (an unlisted sender, another project's front agent) are the same as for `mover=`.
(5) one predicate: a project is front-only exactly when it has no builder, so a project whose only background agent does not build, and a sub-page with a map of its own under a hub that has a builder, take the
same path as the project they belong to; the refusals of a front-only project name the working path (the page key with `For <peer>,` on the first line; mover= for a hand-over), and the needs refusal says what to do instead.

    tests/run-suite builderless_handover        → exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="builderless-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
assert 'session_links = ""' in toml   # the example config names no fleet store of the host
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "brain/projects"): (T / d).mkdir(parents=True)
SMAIN, SDESK, DMAIN, DDESK, DBUILD, EMAIN, LONER = ("home-sigma-main", "home-sigma-desk", "home-delta-main", "home-delta-desk", "home-delta-builder", "home-echo-main", "home-loner")
QMAIN, QDESK, QWATCH, DSIDE = ("home-quiet-main", "home-quiet-desk", "home-quiet-watch", "home-delta-side")
TAMAIN, TADESK, TBMAIN, TBDESK, SHARED = ("home-twa-main", "home-twa-desk", "home-twb-main", "home-twb-desk", "home-shared-builder")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate((SMAIN, SDESK, DMAIN, DDESK, DBUILD, EMAIN, LONER, QMAIN, QDESK, QWATCH, DSIDE, TAMAIN, TADESK, TBMAIN, TBDESK, SHARED), 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in U.items()}))
page = lambda **kw: {"title": "T", "name": "T", "org": "home", "tags": [], "type": "project", "session": "", "status": "active", "board": [], "board_open": 0, **kw}
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/sigma": page(title="Sigma", name="Sigma", agents={SMAIN: "front", SDESK: "front, answers the owner's questions"}),
    "projects/delta": page(title="Delta", name="Delta", agents={DMAIN: "front", DDESK: "front, answers questions", DBUILD: "builds it"}, back_agents={DBUILD: "builds it"}),
    "projects/sigma/sub": page(title="Sigma sub", name="Sigma sub"),
    "projects/echo": page(title="Echo", name="Echo", agents={EMAIN: "front"}),
    "projects/quiet": page(title="Quiet", name="Quiet", agents={QMAIN: "front", QDESK: "front, answers questions", QWATCH: "watches the clock"}, back_agents={QWATCH: "watches the clock"}),
    "projects/delta/desk": page(title="Delta desk", name="Delta desk", agents={DSIDE: "front for the desk page"}),
    "projects/twa": page(title="Twa", name="Twa", agents={TAMAIN: "front", TADESK: "front, answers questions", SHARED: "builds things"}, back_agents={SHARED: "builds things"}),
    "projects/twb": page(title="Twb", name="Twb", agents={TBMAIN: "front", TBDESK: "front, answers questions", SHARED: "builds things"}, back_agents={SHARED: "builds things"})}}))
(T / "store/next-id").write_text("40"); (T / "store/anchors.json").write_text("{}")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
def rd(g):
    g = str(g); g = g if not g[:1].isdigit() else "a" + g
    return json.loads((T / f"store/{g[0]}/{g[1:]}.json").read_text())
now0 = time.time()
def put(i, project="projects/sigma", **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "- A thing\n- It lives here\n- Done when done", "status": "open",
        "updated": now0 - 60, "state_updated": now0 - 60, "confirmed": now0 - 60, "metadata": {"owner": SMAIN, "project": project, **meta}}))

from stackshot.web import server
from stackshot.service import answer as answer_svc
from stackshot.core import instance as _core_instance
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.tools import create as _wt_create
from stackshot.web.tools import update as _wt_update
from stackshot.service import telling
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
told = []
telling.tell_woken = lambda gid, owner, note, tag="wake", **k: told.append((gid, owner, note, tag))
OWNER = _core_instance.OWNER
DESC = "- Goal: A thing\n- It lives here\n- Done when done"
STEP = "run the one line in a terminal"
WAKE = time.strftime("%Y-%m-%d", time.gmtime(now0 + 5 * 86400))      # a few days out
def call(fn):
    """the tool's reply, or the refusal's text when it refuses"""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        return str(e)
def refusal(fn):
    try:
        return fn() and ""
    except Exception as e:  # noqa: BLE001
        return str(e)
def held(i):
    return telling.holder(rd(i))
def put_step(i, project="projects/sigma", next_text=None, post=SMAIN, **meta):
    """the incident: on hold with a wake, post_wake_mover = the general -main agent, waiting on the owner's step"""
    put(i, project=project, state="your-step", step=STEP, hold=True, wake=WAKE, wait_kind="time", post_wake_mover=post,
        next=next_text if next_text is not None else f"{OWNER}: {STEP}\n{SDESK}: check the result and carry on", **meta)

# ---- 1. the answer to the owner's step
put_step(1, contact=SDESK)
told.clear()
res = answer_svc._answer("a1", "", "", "send"); m = rd(1)["metadata"]
check("1.1 the incident: the answered step goes to the session the next open step names, not to -main", res == "done" and held(1) == SDESK and m.get("mover") == SDESK, (res, held(1), m.get("mover")))
check("1.2 the wait and the owner's step are over, and the session is told it is its item now", "wait_kind" not in m and not m.get("hold") and "state" not in m and any(t[1] == U[SDESK] and "It goes to" not in t[2] and "yours now" in t[2] for t in told), (m, told))
check("1.3 -main is not the mover", held(1) != SMAIN and SMAIN not in json.dumps(m.get("needs") or []), m.get("needs"))

put_step(2, contact=SDESK, next_text=f"{OWNER}: {STEP}")      # no other step: the stored contact
res = answer_svc._answer("a2", "", "", "send")
check("1.4 with no further named step, the item's stored contact takes it", res == "done" and held(2) == SDESK, (res, held(2)))

put_step(3, next_text=f"{OWNER}: {STEP}")      # neither a step nor a contact: -main keeps it as before
res = answer_svc._answer("a3", "", "", "send")
check("1.5 with neither a next step nor a contact, -main takes it as before", res == "done" and held(3) == SMAIN, (res, held(3)))

put_step(4, contact=SDESK, next_text=f"{OWNER}: {STEP}\n{LONER}: unknown session step")
res = answer_svc._answer("a4", "", "", "send")
check("1.6 a next step that names no usable session falls to the contact", res == "done" and held(4) == SDESK, (res, held(4)))

put_step(5, then=SDESK, next_text=f"{OWNER}: {STEP}\n{SMAIN}: carry on", contact=SMAIN)
res = answer_svc._answer("a5", "", "", "send")
check("1.7 a stored `then` still wins over the step and the contact", res == "done" and held(5) == SDESK, (res, held(5)))

put_step(6, project="projects/delta", post=DMAIN, contact=DDESK, next_text=f"{OWNER}: {STEP}\ncheck the result")
res = answer_svc._answer("a6", "", "", "send")
check("1.8 a project that has a builder hands the answer to its builder, as before (no step after his names a session)", res == "done" and held(6) == DBUILD, (res, held(6)))
put_step(70, project="projects/delta", post=DMAIN, contact=DDESK, next_text=f"{OWNER}: {STEP}\n{DDESK}: check the result")
res = answer_svc._answer("a70", "", "", "send")
check("1.8b ...but a front agent that holds the next open named step takes it, builder or not: it is the one to act on his answer (the builder stays out)", res == "done" and held(70) == DDESK, (res, held(70)))

put_step(7, next_text=f"{OWNER}: {STEP}\n{OWNER}: and then sign it\n{SDESK}: finish")      # the owner's own later line is skipped
res = answer_svc._answer("a7", "", "", "send")
check("1.9 another line of the owner's is not an owner of the answer: the first named session step is", res == "done" and held(7) == SDESK, (res, held(7)))

put_step(8, contact=SDESK)
res = answer_svc._answer("a8", "", "which box do I run it on?", "send")
check("1.10 his note on the step (not a Done) goes the same way", res == "stepreply" and held(8) == SDESK, (res, held(8)))

# a step line does no more than mover= would: only a live front agent of the item's own project is named
put_step(20, contact=SDESK, next_text=f"{OWNER}: {STEP}\n{EMAIN}: review it")      # another project's front agent
res = answer_svc._answer("a20", "", "", "send")
check("1.11 a next step naming another project's front agent falls to the contact", res == "done" and held(20) == SDESK, (res, held(20)))
put_step(21, next_text=f"{OWNER}: {STEP}\n{EMAIN}: review it")      # ... and with no contact, to the old fallback
res = answer_svc._answer("a21", "", "", "send")
check("1.12 with no contact it falls to -main, not to another project's front agent", res == "done" and held(21) == SMAIN, (res, held(21)))
put_step(22, next_text=f"{OWNER}: {STEP}\n{DBUILD}: take it over")      # another project's builder
res = answer_svc._answer("a22", "", "", "send")
check("1.13 a next step naming another project's builder is not followed either", res == "done" and held(22) == SMAIN, (res, held(22)))
put_step(23, contact=EMAIN, next_text=f"{OWNER}: {STEP}")      # a contact that is another project's front agent is not followed
res = answer_svc._answer("a23", "", "", "send")
check("1.14 a stored contact that is another project's front agent is not followed", res == "done" and held(23) == SMAIN, (res, held(23)))
put_step(24, project="projects/sigma/sub", contact=SDESK, next_text=f"{OWNER}: {STEP}\n{SDESK}: finish")      # a page under the project counts as the project
res = answer_svc._answer("a24", "", "", "send")
check("1.15 an item filed under a page of the project follows its front agent's step", res == "done" and held(24) == SDESK, (res, held(24)))

# ---- 2. one front agent hands an item to another front agent of the same project with no builder
put(10, mover=SMAIN)
told.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a10", sender=SMAIN, mover=SDESK, next=f"{SDESK}: take it from here"))
check("2.1 a front agent's mover= to another front agent of the same builderless project is accepted", "Refused" not in r and held(10) == SDESK and rd(10)["metadata"].get("mover") == SDESK, (r, held(10)))
check("2.2 the reply says so, and the target is told by a notice", "no builder" in r and SDESK in r and any(t[1] == U[SDESK] and t[3] == "handoff" for t in told), (r, told))
check("2.3 nothing is substituted: no server_fixed mark for the front-mover rule", "front_mover" not in json.dumps(rd(10)["metadata"].get("server_fixed") or ""), rd(10)["metadata"].get("server_fixed"))

# the target can now hold and wake the item itself (it is the mover)
r = refusal(lambda: _wt_update.stackshot_update(item_id="a10", sender=SDESK, hold=True, wake=WAKE))
check("2.4 the target, now the mover, may hold the item with a wake", "front agent does not watch" not in r, r)

told.clear()
r = call(lambda: _wt_create.stackshot_create(subject="[home] handed to the other front agent", description=DESC, project="projects/sigma", sender=SMAIN, mover=SDESK, next=f"{SDESK}: take it from here"))
check("2.5 a create does the same", r.startswith("created") and held(r.split()[1]) == SDESK, r)

put(11, mover=SMAIN)
told.clear()
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a11", sender=EMAIN, mover=SDESK, next=f"{SDESK}: take it"))
check("2.6 a front agent of another project may hand it too (the sender need only be a session a page lists), and the target is told", msg == "" and held(11) == SDESK and any(t[1] == U[SDESK] and t[3] == "handoff" for t in told), (msg, held(11), told))

put(12, mover=SMAIN)
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a12", sender=LONER, mover=SDESK, next=f"{SDESK}: take it"))
check("2.7 a session no page lists is still refused", msg.startswith("Refused:") and "has no builder to hand it to" in msg and held(12) == SMAIN, (msg, held(12)))

put(13, project="projects/delta", mover=DMAIN)
r = call(lambda: _wt_update.stackshot_update(item_id="a13", sender=DMAIN, mover=DDESK, next=f"{DBUILD}: take it"))
check("2.8 in a project with a builder the builder is substituted, as before", f"mover={DBUILD}, the project's builder, was used instead" in r and held(13) == DBUILD, (r, held(13)))

put(14, project="projects/echo", mover=LONER)
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a14", sender=SMAIN, mover=EMAIN, next=f"{EMAIN}: take it"))
check("2.9 a front agent of one project may hand an item of a builderless project to that project's front agent (the item's project decides)", msg == "" and held(14) == EMAIN, (msg, held(14)))

put(15, mover=SMAIN)
r = refusal(lambda: _wt_update.stackshot_update(item_id="a15", sender=SMAIN, mover=SMAIN, next=f"{SMAIN}: carry on"))
check("2.10 a front agent naming itself stays accepted", r == "" and held(15) == SMAIN, (r, held(15)))

put(16, project="projects/echo", mover=LONER)
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a16", sender=SMAIN, mover=SDESK, next=f"{SDESK}: take it"))
check("2.11 two front agents of one project may not hand an item filed under another project", msg.startswith("Refused:") and held(16) == LONER, (msg, held(16)))
put(17, project="projects/sigma/sub", mover=SMAIN)
r = call(lambda: _wt_update.stackshot_update(item_id="a17", sender=SMAIN, mover=SDESK, next=f"{SDESK}: take it from here"))
check("2.12 an item filed under a page of their project passes", "Refused" not in r and held(17) == SDESK, (r, held(17)))

# ---- 3. the sender need not belong to the project: any session some project page lists
put(40, mover=SMAIN)
told.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a40", sender=DMAIN, mover=SDESK, next=f"{SDESK}: take it from here"))
check("3.1 a front agent of another project hands an item of a builderless project to its front agent", "Refused" not in r and held(40) == SDESK and rd(40)["metadata"].get("mover") == SDESK, (r, held(40)))
check("3.2 the reply says there is no builder and the target is told by a hand-off notice", "no builder" in r and "is told it is handed" in r and any(t[1] == U[SDESK] and t[3] == "handoff" for t in told), (r, told))
check("3.3 nothing is substituted: no server_fixed mark", "front_mover" not in json.dumps(rd(40)["metadata"].get("server_fixed") or ""), rd(40)["metadata"].get("server_fixed"))
put(41, mover=SDESK)
told.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a41", sender=DBUILD, mover=SMAIN, next=f"{SMAIN}: take it from here", check="item_closed a1"))
check("3.4 a background agent of another project does the same, and the target is told", "Refused" not in r and held(41) == SMAIN and any(t[1] == U[SMAIN] and t[3] == "handoff" for t in told), (r, held(41), told))
told.clear()
r = call(lambda: _wt_create.stackshot_create(subject="[home] handed from another project", description=DESC, project="projects/sigma", sender=DBUILD, mover=SDESK, next=f"{SDESK}: take it from here"))
check("3.5 a create does the same", r.startswith("created") and held(r.split()[1]) == SDESK and any(t[1] == U[SDESK] and t[3] == "handoff" for t in told), (r, told))
put(42, mover=DBUILD, project="projects/sigma/sub")
r = call(lambda: _wt_update.stackshot_update(item_id="a42", sender=DBUILD, mover=SDESK, next=f"{SDESK}: take it", check="item_closed a1"))
check("3.6 an item filed under a page of the project counts as the project's", "Refused" not in r and held(42) == SDESK, (r, held(42)))
put(43, project="projects/delta", mover=DBUILD)
told.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a43", sender=SMAIN, mover=DDESK, next=f"{DBUILD}: take it"))
check("3.7 the target of a project that has a builder is still substituted by the builder, whoever sends it", f"mover={DBUILD}, the project's builder, was used instead" in r and held(43) == DBUILD and not any(t[1] in (U[DMAIN], U[DDESK]) for t in told), (r, held(43), told))
put(44, mover=SMAIN)
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a44", sender=DBUILD, mover=EMAIN, next=f"{EMAIN}: take it"))
check("3.8 a front agent of another project than the item's is refused as the target, and the refusal names the rule", msg.startswith("Refused:") and "has no builder to hand it to" in msg and "this call was refused because home-echo-main is not a live front agent of projects/sigma." in msg
      and 'message(to=\'projects/echo\') with the first line "For home-echo-main, ..."' in msg
      and "no hand-off notice" not in msg and "gets no notice" not in msg and held(44) == SMAIN, (msg, held(44)))
put(45, project="projects/echo", mover=EMAIN)
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a45", sender=DBUILD, mover=SDESK, next=f"{SDESK}: take it"))
check("3.9 the same from the other side: an item of one project cannot be pointed at a front agent of another", msg.startswith("Refused:") and held(45) == EMAIN, (msg, held(45)))
put(46, project="projects/echo", mover=SMAIN)
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a46", sender=LONER, mover=EMAIN, next=f"{EMAIN}: take it"))
check("3.10 a sender no page lists is refused whatever the target", msg.startswith("Refused:") and "this call was refused because home-loner is not a session any project page lists." in msg
      and "no hand-off notice" not in msg and "gets no notice" not in msg and held(46) == SMAIN, (msg, held(46)))
from stackshot.anchors import anchors as _anc_t
_real_roles = _anc_t.session_roles
_anc_t.session_roles = lambda *a, **k: {n: ({**r, "retired": True} if n == DDESK else r) for n, r in _real_roles(*a, **k).items()}
try:
    put(50, mover=SMAIN)
    msg = refusal(lambda: _wt_update.stackshot_update(item_id="a50", sender=DDESK, mover=SDESK, next=f"{SDESK}: take it"))
finally:
    _anc_t.session_roles = _real_roles
check("3.10b a retired sender is named as retired, not as unlisted, and the refusal does not say the front agent gets no notice",
      msg.startswith("Refused:") and "this call was refused because home-delta-desk is retired." in msg and "not a session any project page lists" not in msg
      and "no hand-off notice" not in msg and "gets no notice" not in msg and held(50) == SMAIN, (msg, held(50)))
put(47, mover=SMAIN)
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a47", sender=OWNER, mover=SDESK, next=f"{SDESK}: take it"))
check("3.11 the owner's own name as sender is no session a page lists: refused", msg.startswith("Refused:") and held(47) == SMAIN, (msg, held(47)))
ASK = "Decide: a or b - Recommend: a - Stakes: none - By: no date"
# ---- 4. then= and post_wake_mover= take the same exception as mover=
put(48, mover=OWNER, needs=["decision"], ask=ASK, then=SMAIN, state="your-call")
told.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a48", sender=DBUILD, then=SDESK))
check("4.1 then=<front agent> from a listed session of another project is accepted in a front-only project, and the note says nobody is told by this write", "Refused" not in r and rd(48)["metadata"].get("then") == SDESK
      and "then=home-sigma-desk is not replaced by one" in r and "if the item keeps it" in r and "stays as sent" not in r, (r, rd(48)["metadata"].get("then")))
check("4.2 …no hand-off notice goes to the front agent and no hand-off is recorded for it", not any(t[3] == "handoff" for t in told) and "handoff" not in rd(48)["metadata"] and rd(48)["metadata"].get("mover") == OWNER, (told, rd(48)["metadata"]))
put(51, mover=OWNER, needs=["decision"], ask=ASK, then=SMAIN, state="your-call")
r = call(lambda: _wt_update.stackshot_update(item_id="a51", sender=SMAIN, then=SDESK))
check("4.3 …the same from a front agent of the item's own project", "Refused" not in r and rd(51)["metadata"].get("then") == SDESK, (r, rd(51)["metadata"].get("then")))
put(52, mover=OWNER, needs=["decision"], ask=ASK, then=SMAIN, state="your-call")
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a52", sender=LONER, then=SDESK))
check("4.4 then=<front agent> from a session no page lists is refused, naming that half and the For <peer> path", msg.startswith("Refused:") and "this call was refused because home-loner is not a session any project page lists." in msg
      and "then=home-sigma-desk names" in msg and "For home-sigma-desk" in msg and rd(52)["metadata"].get("then") == SMAIN, (msg, rd(52)["metadata"].get("then")))
put(53, mover=OWNER, needs=["decision"], ask=ASK, then=SMAIN, state="your-call")
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a53", sender=DBUILD, then=EMAIN))
check("4.5 then=<another project's front agent> is refused, as mover= is", msg.startswith("Refused:") and "this call was refused because home-echo-main is not a live front agent of projects/sigma." in msg and rd(53)["metadata"].get("then") == SMAIN, (msg, rd(53)["metadata"].get("then")))
put_step(54)
told.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a54", sender=DBUILD, post_wake_mover=SDESK, wait_basis=f"the vendor's reply is due {WAKE}"))
check("4.6 post_wake_mover=<front agent> (the old name of mover) on a waiting item is accepted the same way and stored as the picker, with no hand-off notice", "Refused" not in r and "post_wake_mover=home-sigma-desk is not replaced by one" in r and "stays as sent" not in r
      and rd(54)["metadata"].get("mover") == SDESK and not any(t[3] == "handoff" for t in told), (r, rd(54)["metadata"].get("mover"), told))
put_step(55)
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a55", sender=LONER, post_wake_mover=SDESK, wait_basis=f"the vendor's reply is due {WAKE}"))
check("4.7 …and refused from a session no page lists, as mover= is", msg.startswith("Refused:") and "this call was refused because home-loner is not a session any project page lists." in msg and rd(55)["metadata"].get("post_wake_mover") == SMAIN, (msg, rd(55)["metadata"]))
put_step(56)
r = call(lambda: _wt_update.stackshot_update(item_id="a56", sender=DBUILD, mover=SDESK, post_wake_mover=SDESK, wait_basis=f"the vendor's reply is due {WAKE}"))
check("4.8 mover= and post_wake_mover= naming the same front agent together behave as mover= alone: one hand-over", "Refused" not in r and rd(56)["metadata"].get("mover") == SDESK, (r, rd(56)["metadata"].get("mover")))
put(57, mover=SMAIN)
told.clear()
r = call(lambda: _wt_create.stackshot_create(subject="[home] then names the other front agent", description=DESC, project="projects/sigma", sender=DBUILD, mover=DBUILD, then=SDESK, next=f"{DBUILD}: take it"))
check("4.9 a create with an agent as mover takes then=<front agent> through the gate, and the item then drops it: the reply says it is dropped and never also that it stays as sent", r.startswith("created") and "then dropped" in r
      and "stays as sent" not in r and "Refused" not in r, r[-700:])
r = call(lambda: _wt_create.stackshot_create(subject="[home] the owner moves it, then the other front agent", description=DESC, project="projects/sigma", sender=DBUILD, mover=OWNER, needs="decision", ask="Decide: whether to approve it · Recommend: yes · Stakes: none · By: no date", then=SDESK, next=f"{OWNER}: decide"))
check("4.9b …with the owner as mover the then stands, and the note is the conditional one", r.startswith("created") and "then=home-sigma-desk is not replaced by one" in r and "then dropped" not in r and "stays as sent" not in r, r)
put(58, project="projects/delta", mover=OWNER, needs=["decision"], ask=ASK, then=DBUILD, state="your-call")
r = call(lambda: _wt_update.stackshot_update(item_id="a58", sender=SMAIN, then=DDESK))
check("4.10 in a project that has a builder then=<front agent> is replaced by the builder, as before", f"then={DBUILD}, the project's builder, was used instead" in r and rd(58)["metadata"].get("then") == DBUILD, (r, rd(58)["metadata"].get("then")))
put_step(59, project="projects/delta", post=DMAIN)
r = call(lambda: _wt_update.stackshot_update(item_id="a59", sender=SMAIN, post_wake_mover=DDESK, wait_basis=f"the vendor's reply is due {WAKE}"))
check("4.11 …and so is post_wake_mover=<front agent>", f"post_wake_mover={DBUILD}, the project's builder, was used instead" in r and rd(59)["metadata"].get("mover") == DBUILD, (r, rd(59)["metadata"].get("mover")))

# ---- 5. one predicate: front-only = no builder
put(60, project="projects/quiet", mover=QMAIN)
told.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a60", sender=QMAIN, mover=QDESK, next=f"{QDESK}: take it from here"))
check("5.1 a project whose only background agent does not build is front-only: a peer's mover= passes, with no builder substituted, and the peer is told", "Refused" not in r and held(60) == QDESK and "no builder" in r
      and "front_mover" not in json.dumps(rd(60)["metadata"].get("server_fixed") or "") and any(t[1] == U[QDESK] and t[3] == "handoff" for t in told), (r, held(60), told))
put(61, project="projects/quiet", mover=OWNER, needs=["decision"], ask=ASK, then=QMAIN, state="your-call")
r = call(lambda: _wt_update.stackshot_update(item_id="a61", sender=QMAIN, then=QDESK))
check("5.2 …then= too", "Refused" not in r and rd(61)["metadata"].get("then") == QDESK, (r, rd(61)["metadata"].get("then")))
from stackshot.anchors import anchors as _anc_p
from stackshot.service import handoff as _handoff_p
check("5.3 front_only is exactly 'no builder' on every project of the fixture (handoff_builder is the same answer)", all(_anc_p.front_only(k) == (not _handoff_p.handoff_builder(k)) for k in
      ("projects/sigma", "projects/delta", "projects/delta/desk", "projects/sigma/sub", "projects/echo", "projects/quiet", "projects/ghost", "")), None)
check("5.4 …a background agent with another mandate is no builder; a sub-page with a map of its own under a hub that has a builder has one", _anc_p.front_only("projects/quiet") is True and _anc_p.front_only("projects/delta/desk") is False
      and _anc_p.front_only("projects/delta") is False and _anc_p.front_only("projects/sigma/sub") is True, None)
put(62, project="projects/delta/desk", mover=DMAIN)
r = call(lambda: _wt_update.stackshot_update(item_id="a62", sender=DMAIN, mover=DSIDE, next=f"{DBUILD}: take it"))
check("5.5 an item under a sub-page with its own front map and a builder above it takes the builder's path: the front agent is replaced by the builder (the exception needs no builder)", f"mover={DBUILD}, the project's builder, was used instead" in r and held(62) == DBUILD, (r, held(62)))
# a builder listed on the pages of two hubs is the builder of both: neither is front-only, and a peer's mover= on either is replaced by it, as before
check("5.5b a builder shared by two hubs: front_only is False for both", _anc_p.front_only("projects/twa") is False and _anc_p.front_only("projects/twb") is False and _handoff_p.handoff_builder("projects/twb") == [SHARED], None)
for n_, proj_, a_, b_ in ((65, "projects/twa", TAMAIN, TADESK), (66, "projects/twb", TBMAIN, TBDESK)):
    put(n_, project=proj_, mover=a_)
    r = call(lambda: _wt_update.stackshot_update(item_id=f"a{n_}", sender=a_, mover=b_, next=f"{SHARED}: take it"))
    check(f"5.5c a peer's mover= on {proj_} is replaced by the shared builder", f"mover={SHARED}, the project's builder, was used instead" in r and held(n_) == SHARED, (r, held(n_)))
put(63, mover=SMAIN)
msg = call(lambda: _wt_update.stackshot_update(item_id="a63", sender=SMAIN, needs=[SDESK]))
check("5.6 needs=[<same-project front agent>] in a front-only project is refused with the working path: mover=<peer> to hand it over, or its own item with after=", msg.startswith("Refused:") and f"set mover={SDESK}" in msg
      and "after=" in msg and "no background agent named" not in msg, msg)
put(64, project="projects/delta", mover=DBUILD)
msg = call(lambda: _wt_update.stackshot_update(item_id="a64", sender=DBUILD, needs=[DDESK]))
check("5.7 …in a project that has a builder the refusal is the old one, naming the builder", msg.startswith("Refused:") and f"For projects/delta: {DBUILD}" in msg and "set mover=" not in msg, msg)

# the pure test (builderless.handover_allowed): rows of the session roles; a retired row is no session, a target must be a live front agent of the item's project
from stackshot.waits import builderless as _bl
front = lambda proj, **k: {"role": "front", "project": proj, **k}
back = lambda proj, **k: {"role": "back", "project": proj, **k}
keeper = lambda proj, **k: {"role": "keeper", "project": proj, **k}
H = _bl.handover_allowed
check("3.14 pure: a front or a background agent of any project hands an item of a front-only project to its front agent", H(front("projects/delta"), front("projects/sigma"), True, "projects/sigma") and H(back("projects/delta"), front("projects/sigma"), True, "projects/sigma"))
check("3.15 pure: a one-session project's own session counts as a row; a retired row does not, as sender or as target", H(keeper("projects/lone"), front("projects/sigma"), True, "projects/sigma")
      and not H(keeper("projects/lone", retired=True), front("projects/sigma"), True, "projects/sigma") and not H(front("projects/delta"), front("projects/sigma", retired=True), True, "projects/sigma"))
check("3.16 pure: no row for the sender, a project that is not front-only, a target that is not a front agent or is another project's: no", not H(None, front("projects/sigma"), True, "projects/sigma") and not H(front("projects/delta"), front("projects/sigma"), False, "projects/sigma")
      and not H(front("projects/delta"), back("projects/sigma"), True, "projects/sigma") and not H(front("projects/delta"), front("projects/echo"), True, "projects/sigma") and not H(front("projects/delta"), None, True, "projects/sigma"))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.stdout.flush()
os._exit(1 if fails else 0)
