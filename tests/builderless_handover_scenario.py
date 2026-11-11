"""Scenario test for a project with no builder: an answered step of the owner goes to the session the item's next open step names, and one front agent may hand an item to another front
agent of the same project — fixture data (English stand-in text), no live store, no network.

Covers: (1) the incident: in a project whose page lists only front agents (a general -main agent and a second front agent), an item on hold with a wake, whose post_wake_mover is the -main agent,
whose contact and next open step are the second front agent's, waits on the owner's step; once he answers it the item lands on the second front agent (the step's owner line), not on -main; with no
such step the item's stored contact takes it; with neither, -main keeps it as before; a project that has a builder still hands the answer to its builder; a stored `then` still wins.
(2) one front agent's `mover=` to another front agent of the same builderless project is accepted, with a note, and the target is told by a notice; the refusal stays for a front agent of
another project, for a session no page lists, and (as a substitution by the builder) for a project that has one.

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
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate((SMAIN, SDESK, DMAIN, DDESK, DBUILD, EMAIN, LONER), 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in U.items()}))
page = lambda **kw: {"title": "T", "name": "T", "org": "home", "tags": [], "type": "project", "session": "", "status": "active", "board": [], "board_open": 0, **kw}
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/sigma": page(title="Sigma", name="Sigma", agents={SMAIN: "front", SDESK: "front, answers the owner's questions"}),
    "projects/delta": page(title="Delta", name="Delta", agents={DMAIN: "front", DDESK: "front, answers questions", DBUILD: "builds it"}, back_agents={DBUILD: "builds it"}),
    "projects/sigma/sub": page(title="Sigma sub", name="Sigma sub"),
    "projects/echo": page(title="Echo", name="Echo", agents={EMAIN: "front"})}}))
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
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
told = []
server._tell_woken = lambda gid, owner, note, tag="wake", **k: told.append((gid, owner, note, tag))
OWNER = server.OWNER
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
    return server._holder(rd(i))
def put_step(i, project="projects/sigma", next_text=None, post=SMAIN, **meta):
    """the incident: on hold with a wake, post_wake_mover = the general -main agent, waiting on the owner's step"""
    put(i, project=project, state="your-step", step=STEP, hold=True, wake=WAKE, wait_kind="time", post_wake_mover=post,
        next=next_text if next_text is not None else f"{OWNER}: {STEP}\n{SDESK}: check the result and carry on", **meta)

# ---- 1. the answer to the owner's step
put_step(1, contact=SDESK)
told.clear()
res = server._answer("a1", "", "", "send"); m = rd(1)["metadata"]
check("1.1 the incident: the answered step goes to the session the next open step names, not to -main", res == "done" and held(1) == SDESK and m.get("mover") == SDESK, (res, held(1), m.get("mover")))
check("1.2 the wait and the owner's step are over, and the session is told it is its item now", "wait_kind" not in m and not m.get("hold") and "state" not in m and any(t[1] == U[SDESK] and "It goes to" not in t[2] and "yours now" in t[2] for t in told), (m, told))
check("1.3 -main is not the mover", held(1) != SMAIN and SMAIN not in json.dumps(m.get("needs") or []), m.get("needs"))

put_step(2, contact=SDESK, next_text=f"{OWNER}: {STEP}")      # no other step: the stored contact
res = server._answer("a2", "", "", "send")
check("1.4 with no further named step, the item's stored contact takes it", res == "done" and held(2) == SDESK, (res, held(2)))

put_step(3, next_text=f"{OWNER}: {STEP}")      # neither a step nor a contact: -main keeps it as before
res = server._answer("a3", "", "", "send")
check("1.5 with neither a next step nor a contact, -main takes it as before", res == "done" and held(3) == SMAIN, (res, held(3)))

put_step(4, contact=SDESK, next_text=f"{OWNER}: {STEP}\n{LONER}: unknown session step")
res = server._answer("a4", "", "", "send")
check("1.6 a next step that names no usable session falls to the contact", res == "done" and held(4) == SDESK, (res, held(4)))

put_step(5, then=SDESK, next_text=f"{OWNER}: {STEP}\n{SMAIN}: carry on", contact=SMAIN)
res = server._answer("a5", "", "", "send")
check("1.7 a stored `then` still wins over the step and the contact", res == "done" and held(5) == SDESK, (res, held(5)))

put_step(6, project="projects/delta", post=DMAIN, contact=DDESK, next_text=f"{OWNER}: {STEP}\n{DDESK}: check the result")
res = server._answer("a6", "", "", "send")
check("1.8 a project that has a builder hands the answer to its builder, as before", res == "done" and held(6) == DBUILD, (res, held(6)))

put_step(7, next_text=f"{OWNER}: {STEP}\n{OWNER}: and then sign it\n{SDESK}: finish")      # the owner's own later line is skipped
res = server._answer("a7", "", "", "send")
check("1.9 another line of the owner's is not an owner of the answer: the first named session step is", res == "done" and held(7) == SDESK, (res, held(7)))

put_step(8, contact=SDESK)
res = server._answer("a8", "", "which box do I run it on?", "send")
check("1.10 his note on the step (not a Done) goes the same way", res == "stepreply" and held(8) == SDESK, (res, held(8)))

# a step line does no more than mover= would: only a live front agent of the item's own project is named
put_step(20, contact=SDESK, next_text=f"{OWNER}: {STEP}\n{EMAIN}: review it")      # another project's front agent
res = server._answer("a20", "", "", "send")
check("1.11 a next step naming another project's front agent falls to the contact", res == "done" and held(20) == SDESK, (res, held(20)))
put_step(21, next_text=f"{OWNER}: {STEP}\n{EMAIN}: review it")      # ... and with no contact, to the old fallback
res = server._answer("a21", "", "", "send")
check("1.12 with no contact it falls to -main, not to another project's front agent", res == "done" and held(21) == SMAIN, (res, held(21)))
put_step(22, next_text=f"{OWNER}: {STEP}\n{DBUILD}: take it over")      # another project's builder
res = server._answer("a22", "", "", "send")
check("1.13 a next step naming another project's builder is not followed either", res == "done" and held(22) == SMAIN, (res, held(22)))
put_step(23, contact=EMAIN, next_text=f"{OWNER}: {STEP}")      # a contact that is another project's front agent is not followed
res = server._answer("a23", "", "", "send")
check("1.14 a stored contact that is another project's front agent is not followed", res == "done" and held(23) == SMAIN, (res, held(23)))
put_step(24, project="projects/sigma/sub", contact=SDESK, next_text=f"{OWNER}: {STEP}\n{SDESK}: finish")      # a page under the project counts as the project
res = server._answer("a24", "", "", "send")
check("1.15 an item filed under a page of the project follows its front agent's step", res == "done" and held(24) == SDESK, (res, held(24)))

# ---- 2. one front agent hands an item to another front agent of the same project with no builder
put(10, mover=SMAIN)
told.clear()
r = call(lambda: server.stackshot_update(item_id="a10", sender=SMAIN, mover=SDESK, next=f"{SDESK}: take it from here"))
check("2.1 a front agent's mover= to another front agent of the same builderless project is accepted", "Refused" not in r and held(10) == SDESK and rd(10)["metadata"].get("mover") == SDESK, (r, held(10)))
check("2.2 the reply says so, and the target is told by a notice", "no builder" in r and SDESK in r and any(t[1] == U[SDESK] and t[3] == "handoff" for t in told), (r, told))
check("2.3 nothing is substituted: no server_fixed mark for the front-mover rule", "front_mover" not in json.dumps(rd(10)["metadata"].get("server_fixed") or ""), rd(10)["metadata"].get("server_fixed"))

# the target can now hold and wake the item itself (it is the mover)
r = refusal(lambda: server.stackshot_update(item_id="a10", sender=SDESK, hold=True, wake=WAKE, wait_reason="waiting for the vendor's reply to arrive, due on the wake day"))
check("2.4 the target, now the mover, may hold the item with a wake", "front agent does not watch" not in r, r)

told.clear()
r = call(lambda: server.stackshot_create(subject="[home] handed to the other front agent", description=DESC, project="projects/sigma", sender=SMAIN, mover=SDESK, next=f"{SDESK}: take it from here"))
check("2.5 a create does the same", r.startswith("created") and held(r.split()[1]) == SDESK, r)

put(11, mover=SMAIN)
msg = refusal(lambda: server.stackshot_update(item_id="a11", sender=EMAIN, mover=SDESK, next=f"{SDESK}: take it"))
check("2.6 a front agent of another project is still refused", msg.startswith("Refused:") and "no builder and no background agent" in msg and held(11) == SMAIN, (msg, held(11)))

put(12, mover=SMAIN)
msg = refusal(lambda: server.stackshot_update(item_id="a12", sender=LONER, mover=SDESK, next=f"{SDESK}: take it"))
check("2.7 a session no page lists is still refused", msg.startswith("Refused:") and "no builder and no background agent" in msg and held(12) == SMAIN, (msg, held(12)))

put(13, project="projects/delta", mover=DMAIN)
r = call(lambda: server.stackshot_update(item_id="a13", sender=DMAIN, mover=DDESK, next=f"{DBUILD}: take it"))
check("2.8 in a project with a builder the builder is substituted, as before", f"mover={DBUILD}, the project's builder, was used instead" in r and held(13) == DBUILD, (r, held(13)))

put(14, project="projects/echo", mover=LONER)
msg = refusal(lambda: server.stackshot_update(item_id="a14", sender=SMAIN, mover=EMAIN, next=f"{EMAIN}: take it"))
check("2.9 a front agent of one project handing an item of another to that project's front agent is refused too", msg.startswith("Refused:") and held(14) == LONER, (msg, held(14)))

put(15, mover=SMAIN)
r = refusal(lambda: server.stackshot_update(item_id="a15", sender=SMAIN, mover=SMAIN, next=f"{SMAIN}: carry on"))
check("2.10 a front agent naming itself stays accepted", r == "" and held(15) == SMAIN, (r, held(15)))

put(16, project="projects/echo", mover=LONER)
msg = refusal(lambda: server.stackshot_update(item_id="a16", sender=SMAIN, mover=SDESK, next=f"{SDESK}: take it"))
check("2.11 two front agents of one project may not hand an item filed under another project", msg.startswith("Refused:") and held(16) == LONER, (msg, held(16)))
put(17, project="projects/sigma/sub", mover=SMAIN)
r = call(lambda: server.stackshot_update(item_id="a17", sender=SMAIN, mover=SDESK, next=f"{SDESK}: take it from here"))
check("2.12 an item filed under a page of their project passes", "Refused" not in r and held(17) == SDESK, (r, held(17)))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.stdout.flush()
os._exit(1 if fails else 0)
