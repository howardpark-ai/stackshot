"""Scenario test for: a front agent is never made an item's mover by another session — fixture data, no live store, no network.

Covers: the server sends a front agent (a user-facing agent on a project's agents map) no hand-off notice, so create and update refuse a write that sets mover, or then
(which becomes the mover after the owner's answer), to a front agent when the sender is a different session. The refusal says the front agent gets no notice, names the
project's builder to hand build work to, and says to message the front agent for a check or an answer only it can give. Allowed as before: a front agent naming itself, the
owner as mover, a background agent, and the server's own moves (they do not come through the tools). The needs gate, which reads roles the same way, still refuses a front agent.

    tests/run-suite front_mover        → exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="frontmover-"); T = pathlib.Path(tmp)
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
MAIN, SIDE, BUILD, REVIEW, ECHO = "home-delta-main", "home-delta-desk", "home-delta-builder", "home-delta-review", "home-echo-main"
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate((MAIN, SIDE, BUILD, REVIEW, ECHO), 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in U.items()}))
page = lambda **kw: {"title": "T", "name": "T", "org": "home", "tags": [], "type": "project", "session": "", "status": "active", "board": [], "board_open": 0, **kw}
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/delta": page(title="Delta", name="Delta", agents={MAIN: "front", SIDE: "answers questions", BUILD: "builds it", REVIEW: "reviews it"},
                           back_agents={BUILD: "builds it", REVIEW: "reviews it"}),
    "projects/echo": page(title="Echo", name="Echo", agents={ECHO: "front"})}}))
(T / "store/next-id").write_text("40"); (T / "store/anchors.json").write_text("{}")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))
def rd(g):
    g = str(g); g = g if not g[:1].isdigit() else "a" + g
    return json.loads((T / f"store/{g[0]}/{g[1:]}.json").read_text())
now0 = time.time()
def put(i, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "- A thing\n- It lives here\n- Done when done", "status": "open",
        "updated": now0 - 60, "state_updated": now0 - 60, "confirmed": now0 - 60, "metadata": {"owner": BUILD, "project": "projects/delta", **meta}}))

from stackshot.web import server
from stackshot.service import telling
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
telling.tell_woken = lambda *a, **k: None
DESC = "- Goal: A thing\n- It lives here\n- Done when done"
SID = server._session_id
OWNER = server.OWNER

def refusal(fn):
    try:
        return fn() and ""
    except Exception as e:  # noqa: BLE001
        return str(e)

def fixed(reply, front, field="mover"):
    """the reply says the front agent was replaced by the builder, and how to keep it"""
    return (f"{field}={front} is a user-facing agent" in reply and f"{field}={BUILD}, the project's builder, was used instead" in reply
            and f"send {field}={front} again" in reply)

# ---- create
r = server.stackshot_create(subject="[home] handed to the front", description=DESC, project="projects/delta", sender=BUILD, mover=MAIN, next=f"{BUILD}: look at it")
g = r.split()[1]
check("create: another session's front-agent mover becomes the builder, and the reply says so", r.startswith("created") and telling.holder(rd(g)) == BUILD and fixed(r, MAIN), r)
check("create: the fix is on the item: server_fixed names it", MAIN in json.dumps(rd(g)["metadata"].get("server_fixed")), rd(g)["metadata"].get("server_fixed"))
r = server.stackshot_create(subject="[home] handed to the side desk", description=DESC, project="projects/delta", sender=MAIN, mover=SIDE, next=f"{BUILD}: look at it")
check("create: one front agent handing to another front agent gets the builder too", r.startswith("created") and telling.holder(rd(r.split()[1])) == BUILD and fixed(r, SIDE), r)

r = server.stackshot_create(subject="[home] the front agent's own", description=DESC, project="projects/delta", sender=MAIN, mover=MAIN, next=f"{MAIN}: carry on")
check("create: a front agent naming itself as mover is accepted", r.startswith("created") and telling.holder(rd(r.split()[1])) == MAIN, r)
r = server.stackshot_create(subject="[home] the front agent's own by id", description=DESC, project="projects/delta", sender=U[MAIN], mover=MAIN, next=f"{MAIN}: carry on")
check("create: a front agent naming itself by name while sending by its id is accepted", r.startswith("created"), r)
r = server.stackshot_create(subject="[home] built by the builder", description=DESC, project="projects/delta", sender=MAIN, mover=BUILD, next=f"{BUILD}: build it")
check("create: a background mover set by a front agent is accepted", r.startswith("created") and telling.holder(rd(r.split()[1])) == BUILD, r)
r = server.stackshot_create(subject="[home] reviewed by the reviewer", description=DESC, project="projects/delta", sender=BUILD, mover=REVIEW, next=f"{REVIEW}: review it")
check("create: a background mover set by another background agent is accepted", r.startswith("created"), r)
r = refusal(lambda: server.stackshot_create(subject="[home] the owner decides", description=DESC, project="projects/delta", sender=BUILD, mover=OWNER, needs=["decision"],
                                            ask="Decide: a or b · Recommend: yes · Stakes: none · By: no date", then=BUILD))
check("create: the owner as mover (with his decision) is accepted", r == "", r)
r = server.stackshot_create(subject="[home] then the front", description=DESC, project="projects/delta", sender=BUILD, mover=OWNER, needs=["decision"],
                            ask="Decide: a or b · Recommend: yes · Stakes: none · By: no date", then=MAIN)
check("create: then=<front agent> by another session becomes the builder, and the reply says so", r.startswith("created") and fixed(r, MAIN, "then") and rd(r.split()[1])["metadata"].get("then") == BUILD, r)

# ---- update
put(1, mover=BUILD)
before = (T / "store/a/1.json").read_bytes()
r = server.stackshot_update(item_id="a1", sender=BUILD, mover=MAIN, next=f"{BUILD}: check it")
check("update: another session's front-agent mover becomes the builder, and the reply says so", fixed(r, MAIN) and telling.holder(rd(1)) == BUILD, r)
check("update: the fix is on the item", MAIN in json.dumps(rd(1)["metadata"].get("server_fixed")), rd(1)["metadata"].get("server_fixed"))
r = server.stackshot_update(item_id="a1", sender=BUILD, mover=MAIN)
check("update: sending the same front-agent mover again keeps it as sent, with a note", telling.holder(rd(1)) == MAIN and "kept as you sent it" in r, r)
put(1, mover=BUILD)
r = server.stackshot_update(item_id="a1", sender=BUILD, then=MAIN)
check("update: then=<front agent> by another session becomes the builder", fixed(r, MAIN, "then") and rd(1)["metadata"].get("then") == BUILD, r)
r = refusal(lambda: server.stackshot_update(item_id="a1", sender=BUILD, mover=REVIEW))
check("update: a background mover is accepted", r == "" and telling.holder(rd(1)) == REVIEW, r)
put(2, mover=BUILD)
r = server.stackshot_update(item_id="a2", sender=MAIN, mover=MAIN, next=f"{MAIN}: take it over")
check("update: a front agent naming itself as mover is accepted", "Refused" not in r and telling.holder(rd(2)) == MAIN, r)
put(3, mover=BUILD)
r = refusal(lambda: server.stackshot_update(item_id="a3", sender=BUILD, mover=OWNER, step="press the button"))
check("update: the owner as mover is accepted", r == "", r)
put(4, mover=MAIN)
r = refusal(lambda: server.stackshot_update(item_id="a4", sender=BUILD, mover="none", next=f"{BUILD}: carry on"))
check("update: clearing the mover is not a hand to a front agent", r == "", r)

# ---- re-sending what the item already holds changes nothing hands, so it passes; an unrelated update on a front-held item passes
put(6, mover=MAIN)
r = refusal(lambda: server.stackshot_update(item_id="a6", sender=BUILD, mover=MAIN, next=f"{MAIN}: carry on"))
check("update: re-sending the item's current front-agent mover is not refused", "no hand-off notice" not in r and "Refused: " + MAIN not in r, r)
put(7, mover=MAIN)
r = refusal(lambda: server.stackshot_update(item_id="a7", sender=BUILD, next=f"{MAIN}: a note from the builder"))
check("update: a next-only update on a front-held item is not refused", "no hand-off notice" not in r, r)
put(8, mover=BUILD, then=MAIN)
r = refusal(lambda: server.stackshot_update(item_id="a8", sender=REVIEW, then=MAIN))
check("update: re-sending the item's current front-agent then is not refused", "no hand-off notice" not in r, r)

# ---- post_wake_mover is the mover once a wait ends: gated like mover and then
put(9, mover=BUILD)
r = server.stackshot_update(item_id="a9", sender=BUILD, post_wake_mover=MAIN)
check("update: post_wake_mover=<front agent> by another session becomes the builder", fixed(r, MAIN, "post_wake_mover"), r)
r = server.stackshot_create(subject="[home] wake to the front", description=DESC, project="projects/delta", sender=BUILD, mover=BUILD, post_wake_mover=MAIN, next=f"{BUILD}: wait")
check("create: post_wake_mover=<front agent> by another session becomes the builder", r.startswith("created") and fixed(r, MAIN, "post_wake_mover"), r)
r = refusal(lambda: server.stackshot_update(item_id="a9", sender=MAIN, post_wake_mover=MAIN))
check("update: a front agent naming itself as post_wake_mover is not refused here", "no hand-off notice" not in r, r)

# ---- a project with no builder and no background agent: the refusal says so once, without a placeholder
put(10, mover=SIDE, project="projects/echo")
msg = refusal(lambda: server.stackshot_update(item_id="a10", sender=SIDE, mover=ECHO))
check("no builder: the refusal says there is no builder or background agent, with no placeholder", msg.startswith("Refused:") and "no builder and no background agent" in msg and "<background agent>" not in msg
      and msg.count("background agent") == 1 and "builder, " not in msg, msg)

# ---- a background agent only the project record holds (its page line still owed): the project is not front-only, but no builder is listed yet; the refusal says the page does not list it yet
from stackshot.projects import projects as _P
_PID = _P.ensure_ids(["projects/echo"])["projects/echo"]
(T / "store/project-record.json").write_text(json.dumps({"schema": 1, "ids": {_PID: "projects/echo"},
    "pending_agents": {_PID: {"home-echo-engineer": {"mandate_line": "takes the build work", "front": False, "role": "engineer"}}}}))
msg = refusal(lambda: server.stackshot_update(item_id="a10", sender=SIDE, mover=ECHO))
check("owed background agent: the refusal says it is not on the page yet, never that there is none", msg.startswith("Refused:") and "not on its page yet" in msg and "no builder and no background agent" not in msg
      and "keep the item with its current mover" in msg and "<background agent>" not in msg, msg)
(T / "store/project-record.json").write_text(json.dumps({"schema": 1, "ids": {_PID: "projects/echo"}, "pending_agents": {}}))
msg = refusal(lambda: server.stackshot_update(item_id="a10", sender=SIDE, mover=ECHO))
check("owed agent gone: the plain refusal is back", msg.startswith("Refused:") and "no builder and no background agent" in msg, msg)

# ---- a failing roles read lets the write through (one stderr line)
import io, contextlib
_real_roles = server._anc.session_roles
def _boom(*a, **k): raise RuntimeError("roles unreadable")
server._anc.session_roles = _boom
errbuf = io.StringIO()
try:
    with contextlib.redirect_stderr(errbuf):
        msg = refusal(lambda: server.stackshot_update(item_id="a1", sender=BUILD, mover=MAIN, next=f"{MAIN}: check it"))
finally:
    server._anc.session_roles = _real_roles
check("roles read fails: the front-mover gate lets the write through and says so on stderr", "no hand-off notice" not in msg and "front-mover gate" in errbuf.getvalue() and "roles unreadable" in errbuf.getvalue(), (msg, errbuf.getvalue()))

# ---- the server's own moves do not come through the tools' gate
put(5, mover=BUILD)
r = server._update("a5", mover=MAIN, sender=BUILD)
check("server-side move (the internal update) is not refused by the tool gate", "Refused" not in r and telling.holder(rd(5)) == MAIN, r)

# ---- a refused hand-off is a no-op on the item: mover, state, needs and the hand-off record stay as before the call, and the refusal text still comes back
ASK = "Decide: a or b - Recommend: a - Stakes: none - By: no date"
def put_his(i, **meta):
    put(i, mover=OWNER, needs=["decision"], ask=ASK, then=BUILD, state="your-call",
        handoff={"to": OWNER, "from": REVIEW, "at": now0 - 30, "no_clock": True, "delivered_at": None, "taken_at": None, **meta.pop("record", {})}, **meta)
def shape(i):
    m = rd(i)["metadata"]
    return {k: m.get(k) for k in ("mover", "state", "needs", "handoff", "then", "ask")}
# a session that is not yet named in needs hands an item that waits on his call to a background agent: refused (the agent goes in then); the writer is not named in needs by a write that failed
for i, rec in ((30, {}), (31, {"recovery_at": now0 - 20, "recovery_reason": "nobody can take it"})):
    put_his(i, record=rec)
    raw, was = (T / f"store/a/{i}.json").read_bytes(), shape(i)
    msg = refusal(lambda: server.stackshot_update(item_id=f"a{i}", sender=REVIEW, mover=BUILD, next=f"{BUILD}: take it"))
    check(f"refused hand-off ({'recovery-asked record' if rec else 'open record'}): the refusal text comes back", msg.startswith("Refused:") and "your-call" in msg and BUILD in msg, msg)
    check(f"refused hand-off ({'recovery-asked record' if rec else 'open record'}): mover, state, needs and handoff are unchanged", shape(i) == was and was["needs"] == ["decision"], (was, shape(i)))
    check(f"refused hand-off ({'recovery-asked record' if rec else 'open record'}): the stored item is byte for byte as it was", (T / f"store/a/{i}.json").read_bytes() == raw)
# a hand-off by a line of next with no check is refused after the gates that read the needs list: the writer is not named in needs by it either
put(32, mover=REVIEW, needs=[REVIEW])
raw, was = (T / "store/a/32.json").read_bytes(), shape(32)
msg = refusal(lambda: server.stackshot_update(item_id="a32", sender=BUILD, next=f"{BUILD}: prepare it\n{SIDE}: do the work"))
check("refused hand-off by a line of next: the refusal text comes back, nothing is stored", msg.startswith("Refused:") and "check" in msg and shape(32) == was and (T / "store/a/32.json").read_bytes() == raw, (msg, shape(32)))
# an accepted hand-off still works: the mover changes, the hand-off is recorded, and the writer is named in needs as its own save
put(33, mover=REVIEW, needs=[REVIEW])
r = refusal(lambda: server.stackshot_update(item_id="a33", sender=REVIEW, mover=BUILD, next=f"{REVIEW}: handed it over", check="item_closed a1"))
m33 = rd(33)["metadata"]
check("accepted hand-off: the mover changes and the hand-off to it is recorded", r == "" and telling.holder(rd(33)) == BUILD and (m33.get("handoff") or {}).get("to") == BUILD and (m33.get("handoff") or {}).get("from"), (r, m33))
put_his(34)
r = refusal(lambda: server.stackshot_update(item_id="a34", sender=REVIEW, mover=OWNER, then=BUILD, next=f"{OWNER}: pick one"))
check("accepted write on an item that waits on his call: stored, the writer named in needs", r == "" and REVIEW in (rd(34)["metadata"].get("needs") or []), (r, shape(34)))

# ---- the needs gate reads roles through the same helper and still refuses a front agent
msg = refusal(lambda: server.stackshot_update(item_id="a1", sender=REVIEW, needs=[MAIN]))
check("needs: a user-facing agent is still refused there", "is a user-facing agent of" in msg and BUILD in msg, msg)

# ---- the tool text says it
form = server._MODEL_FORM
check("tool text: mover and then say a front agent is named only by itself and another session's write is refused", "a front agent (a session" in form and "only by itself" in form and "gets the project's builder instead" in form and "then=<front agent> from another session gets the builder the same way" in form, form[:800])

snap = json.loads(pathlib.Path(SCR, "tool_text.snapshot.json").read_text(encoding="utf-8"))
snap_s = json.dumps(snap)
check("tool text: the mover and then parameters of create and update carry the fix (snapshot)", snap_s.count("from another session that sets mover=<front agent> gets the project's builder instead") >= 2
      and snap_s.count("from another session that sets then=<front agent> gets the project's builder instead") >= 2, snap_s[:300])

check("tool text: post_wake_mover says a front agent only by itself", "post_wake_mover=<who moves it when the wait ends; a front agent only by itself" in form, form[:200])
check("tool text: update's own hand-over sentence says a front agent is not told and the builder is used", "an update from another session that sets mover, then or post_wake_mover to a front agent gets the project's builder instead" in server._UPDATE_DESC, server._UPDATE_DESC[:200])

check("tool text: the post_wake_mover parameter of create and update carries the fix (snapshot)",
      json.dumps(json.loads(pathlib.Path(SCR, "tool_text.snapshot.json").read_text(encoding="utf-8"))).count("sets post_wake_mover=<front agent> gets the project's builder instead") >= 2)

_cdecl = server._CREATE_DESC
check("tool text: create's own description says another session's front-agent mover, then or post_wake_mover gets the builder",
      "a create from another session that sets mover, then or post_wake_mover to a front agent gets the project's builder instead" in _cdecl, _cdecl[:300])

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.stdout.flush()
os._exit(1 if fails else 0)
