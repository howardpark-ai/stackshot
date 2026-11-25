"""Scenario test for: a front agent is never made an item's mover by another session — fixture data, no live store, no network.

Also covers the sibling hand-over: a live front agent of the item's project may hand an item to another live front agent of it (mover, then, post_wake_mover, agent) when the write carries the owner's words in
`said`, checked as the wake cap checks them; the value then stays as sent and the sibling is told by the hand-off notice, which states who handed it over and his quoted words. With no words (none, or words the
check refuses) the swap or refusal stays and ends with one clause on how to send them; a background agent, another project's session, a target that is no front agent of the project and a project with no builder are as before.

Covers: the server sends a front agent (a user-facing agent on a project's agents map) no hand-off notice, so create and update refuse a write that sets mover, or then
(which becomes the mover after the owner's answer), to a front agent when the sender is a different session. The refusal says the front agent gets no notice, names the
project's builder to hand build work to, and says to send a check or an answer only it can give as a message to the page key with `For <agent>,` on its first line. Allowed as before: a front agent naming itself, the
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
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-x"): (T / d).mkdir(parents=True)
MAIN, SIDE, BUILD, REVIEW, ECHO = "home-delta-main", "home-delta-desk", "home-delta-builder", "home-delta-review", "home-echo-main"
GMAIN, GDESK = "home-golf-main", "home-golf-desk"
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate((MAIN, SIDE, BUILD, REVIEW, ECHO, GMAIN, GDESK), 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in U.items()}))
page = lambda **kw: {"title": "T", "name": "T", "org": "home", "tags": [], "type": "project", "session": "", "status": "active", "board": [], "board_open": 0, **kw}
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/delta": page(title="Delta", name="Delta", agents={MAIN: "front", SIDE: "answers questions", BUILD: "builds it", REVIEW: "reviews it"},
                           back_agents={BUILD: "builds it", REVIEW: "reviews it"}),
    "projects/echo": page(title="Echo", name="Echo", agents={ECHO: "front"}),
    "projects/golf": page(title="Golf", name="Golf", agents={GMAIN: "front", GDESK: "front, answers questions"}),
    "projects/foxtrot": page(title="Foxtrot", name="Foxtrot", agents={"home-foxtrot-main": "front", "home-foxtrot-watch": "watches the clock"}, back_agents={"home-foxtrot-watch": "watches the clock"})}}))
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
from stackshot.service import update as _update_svc
from stackshot.core import instance as _core_instance
from stackshot.anchors import anchors as _anc
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.tools import create as _wt_create
from stackshot.web.tools import text as _wt_text
from stackshot.web.tools import update as _wt_update
from stackshot.service import telling
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
told = []; kinds = []      # kinds: the kind each push was told in (the hint tell_kind sets; "" is a turn)
def _tell_woken(gid, owner, note, tag="wake", **k):
    told.append((gid, owner, note, tag)); kinds.append((gid, owner, tag, getattr(telling.FRONT_HINT, "kind", "")))
telling.tell_woken = _tell_woken
DESC = "- Goal: A thing\n- It lives here\n- Done when done"
SID = _web_page_debts._session_id
OWNER = _core_instance.OWNER

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
r = _wt_create.stackshot_create(subject="[home] handed to the front", description=DESC, project="projects/delta", sender=BUILD, mover=MAIN, next=f"{BUILD}: look at it")
g = r.split()[1]
check("create: another session's front-agent mover becomes the builder, and the reply says so", r.startswith("created") and telling.holder(rd(g)) == BUILD and fixed(r, MAIN), r)
check("create: the fix is on the item: server_fixed names it", MAIN in json.dumps(rd(g)["metadata"].get("server_fixed")), rd(g)["metadata"].get("server_fixed"))
r = _wt_create.stackshot_create(subject="[home] handed to the side desk", description=DESC, project="projects/delta", sender=MAIN, mover=SIDE, next=f"{BUILD}: look at it")
check("create: one front agent handing to another front agent gets the builder too", r.startswith("created") and telling.holder(rd(r.split()[1])) == BUILD and fixed(r, SIDE), r)

r = _wt_create.stackshot_create(subject="[home] the front agent's own", description=DESC, project="projects/delta", sender=MAIN, mover=MAIN, next=f"{MAIN}: carry on")
check("create: a front agent naming itself as mover is accepted", r.startswith("created") and telling.holder(rd(r.split()[1])) == MAIN, r)
r = _wt_create.stackshot_create(subject="[home] the front agent's own by id", description=DESC, project="projects/delta", sender=U[MAIN], mover=MAIN, next=f"{MAIN}: carry on")
check("create: a front agent naming itself by name while sending by its id is accepted", r.startswith("created"), r)
r = _wt_create.stackshot_create(subject="[home] built by the builder", description=DESC, project="projects/delta", sender=MAIN, mover=BUILD, next=f"{BUILD}: build it")
check("create: a background mover set by a front agent is accepted", r.startswith("created") and telling.holder(rd(r.split()[1])) == BUILD, r)
r = _wt_create.stackshot_create(subject="[home] reviewed by the reviewer", description=DESC, project="projects/delta", sender=BUILD, mover=REVIEW, next=f"{REVIEW}: review it")
check("create: a background mover set by another background agent is accepted", r.startswith("created"), r)
r = refusal(lambda: _wt_create.stackshot_create(subject="[home] the owner decides", description=DESC, project="projects/delta", sender=BUILD, mover=OWNER, needs=["decision"],
                                            ask="Decide: a or b · Recommend: yes · Stakes: none · By: no date", then=BUILD))
check("create: the owner as mover (with his decision) is accepted", r == "", r)
r = _wt_create.stackshot_create(subject="[home] then the front", description=DESC, project="projects/delta", sender=BUILD, mover=OWNER, needs=["decision"],
                            ask="Decide: a or b · Recommend: yes · Stakes: none · By: no date", then=MAIN)
check("create: then=<front agent> by another session becomes the builder, and the reply says so", r.startswith("created") and fixed(r, MAIN, "then") and rd(r.split()[1])["metadata"].get("then") == BUILD, r)

# ---- update
put(1, mover=BUILD)
before = (T / "store/a/1.json").read_bytes()
r = _wt_update.stackshot_update(item_id="a1", sender=BUILD, mover=MAIN, next=f"{BUILD}: check it")
check("update: another session's front-agent mover becomes the builder, and the reply says so", fixed(r, MAIN) and telling.holder(rd(1)) == BUILD, r)
check("update: the fix is on the item", MAIN in json.dumps(rd(1)["metadata"].get("server_fixed")), rd(1)["metadata"].get("server_fixed"))
r = _wt_update.stackshot_update(item_id="a1", sender=BUILD, mover=MAIN)
check("update: sending the same front-agent mover again keeps it as sent, with a note", telling.holder(rd(1)) == MAIN and "kept as you sent it" in r, r)
put(1, mover=OWNER, needs=["decision"], ask="Decide: a or b - Recommend: a - Stakes: none - By: no date", then=REVIEW, state="your-call")      # a `then` stands only beside the user's own call
r = _wt_update.stackshot_update(item_id="a1", sender=BUILD, then=MAIN)
check("update: then=<front agent> by another session becomes the builder", fixed(r, MAIN, "then") and rd(1)["metadata"].get("then") == BUILD, r)
put(1, mover=BUILD)
r = refusal(lambda: _wt_update.stackshot_update(item_id="a1", sender=BUILD, mover=REVIEW))
check("update: a background mover is accepted", r == "" and telling.holder(rd(1)) == REVIEW, r)
put(2, mover=BUILD)
r = _wt_update.stackshot_update(item_id="a2", sender=MAIN, mover=MAIN, next=f"{MAIN}: take it over")
check("update: a front agent naming itself as mover is accepted", "Refused" not in r and telling.holder(rd(2)) == MAIN, r)
put(3, mover=BUILD)
r = refusal(lambda: _wt_update.stackshot_update(item_id="a3", sender=BUILD, mover=OWNER, step="press the button"))
check("update: the owner as mover is accepted", r == "", r)
put(4, mover=MAIN)
r = refusal(lambda: _wt_update.stackshot_update(item_id="a4", sender=BUILD, mover="none", next=f"{BUILD}: carry on"))
check("update: clearing the mover is not a hand to a front agent", r == "", r)

# ---- re-sending what the item already holds changes nothing hands, so it passes; an unrelated update on a front-held item passes
put(6, mover=MAIN)
r = refusal(lambda: _wt_update.stackshot_update(item_id="a6", sender=BUILD, mover=MAIN, next=f"{MAIN}: carry on"))
check("update: re-sending the item's current front-agent mover is not refused", "no hand-off notice" not in r and "Refused: " + MAIN not in r, r)
put(7, mover=MAIN)
r = refusal(lambda: _wt_update.stackshot_update(item_id="a7", sender=BUILD, next=f"{MAIN}: a note from the builder"))
check("update: a next-only update on a front-held item is not refused", "no hand-off notice" not in r, r)
put(8, mover=BUILD, then=MAIN)
r = refusal(lambda: _wt_update.stackshot_update(item_id="a8", sender=REVIEW, then=MAIN))
check("update: re-sending the item's current front-agent then is not refused", "no hand-off notice" not in r, r)

# ---- post_wake_mover is the mover once a wait ends: gated like mover and then
put(9, mover=BUILD)
r = _wt_update.stackshot_update(item_id="a9", sender=BUILD, post_wake_mover=MAIN)
check("update: post_wake_mover=<front agent> by another session becomes the builder", fixed(r, MAIN, "post_wake_mover"), r)
r = _wt_create.stackshot_create(subject="[home] wake to the front", description=DESC, project="projects/delta", sender=BUILD, mover=BUILD, post_wake_mover=MAIN, next=f"{BUILD}: wait")
check("create: post_wake_mover=<front agent> by another session becomes the builder", r.startswith("created") and fixed(r, MAIN, "post_wake_mover"), r)
r = refusal(lambda: _wt_update.stackshot_update(item_id="a9", sender=MAIN, post_wake_mover=MAIN))
check("update: a front agent naming itself as post_wake_mover is not refused here", "no hand-off notice" not in r, r)

# ---- a project with no builder: the refusal says so once, names the rule and the path to the peer, without a placeholder (the sender is a session no page lists: a session some page lists hands it through, see builderless_handover)
STRANGER = "home-stranger"
put(10, mover=SIDE, project="projects/echo")
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a10", sender=STRANGER, mover=ECHO))
check("no builder: the refusal says there is no builder, names the For <peer> path, with no placeholder and no plain message(to=<agent>) advice", msg.startswith("Refused:") and "has no builder to hand it to" in msg and "<background agent>" not in msg
      and 'with the first line "For home-echo-main, ..."' in msg and f"message(to={ECHO}" not in msg and msg.count("no builder") == 1, msg)

# ---- a project whose only background agent does not build has no builder: the refusal stands, nothing is substituted by that agent
put(11, mover=SIDE, project="projects/foxtrot")
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a11", sender=STRANGER, mover="home-foxtrot-main"))
check("a background agent that does not build is no builder: the front-only refusal, and the agent is not substituted", msg.startswith("Refused:") and "has no builder to hand it to" in msg and "home-foxtrot-watch" not in msg, msg)

# ---- a background agent only the project record holds (its page line still owed) is no builder until the page lists it: the project is front-only and the refusal is the same
from stackshot.projects import projects as _P
_PID = _P.ensure_ids(["projects/echo"])["projects/echo"]
(T / "store/project-record.json").write_text(json.dumps({"schema": 1, "ids": {_PID: "projects/echo"},
    "pending_agents": {_PID: {"home-echo-engineer": {"mandate_line": "takes the build work", "front": False, "role": "engineer"}}}}))
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a10", sender=STRANGER, mover=ECHO))
check("owed background agent: no builder yet, so the front-only refusal stands (never a substitution by an agent the page does not list)", msg.startswith("Refused:") and "has no builder to hand it to" in msg and "keep the item" not in msg and "<background agent>" not in msg, msg)
(T / "store/project-record.json").write_text(json.dumps({"schema": 1, "ids": {_PID: "projects/echo"}, "pending_agents": {}}))
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a10", sender=STRANGER, mover=ECHO))
check("owed agent gone: the same refusal", msg.startswith("Refused:") and "has no builder to hand it to" in msg, msg)

# ---- a failing roles read lets the write through (one stderr line)
import io, contextlib
_real_roles = _anc.session_roles
def _boom(*a, **k): raise RuntimeError("roles unreadable")
_anc.session_roles = _boom
errbuf = io.StringIO()
try:
    with contextlib.redirect_stderr(errbuf):
        msg = refusal(lambda: _wt_update.stackshot_update(item_id="a1", sender=BUILD, mover=MAIN, next=f"{MAIN}: check it"))
finally:
    _anc.session_roles = _real_roles
check("roles read fails: the front-mover gate lets the write through and says so on stderr", "no hand-off notice" not in msg and "front-mover gate" in errbuf.getvalue() and "roles unreadable" in errbuf.getvalue(), (msg, errbuf.getvalue()))

# ---- the server's own moves do not come through the tools' gate
put(5, mover=BUILD)
r = _update_svc._update("a5", mover=MAIN, sender=BUILD)
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
    msg = refusal(lambda: _wt_update.stackshot_update(item_id=f"a{i}", sender=REVIEW, mover=BUILD, next=f"{BUILD}: take it"))
    check(f"refused hand-off ({'recovery-asked record' if rec else 'open record'}): the refusal text comes back", msg.startswith("Refused:") and "your-call" in msg and BUILD in msg, msg)
    check(f"refused hand-off ({'recovery-asked record' if rec else 'open record'}): mover, state, needs and handoff are unchanged", shape(i) == was and was["needs"] == ["decision"], (was, shape(i)))
    check(f"refused hand-off ({'recovery-asked record' if rec else 'open record'}): the stored item is byte for byte as it was", (T / f"store/a/{i}.json").read_bytes() == raw)
# a hand-off by a line of next with no check is refused after the gates that read the needs list: the writer is not named in needs by it either
put(32, mover=REVIEW, needs=[REVIEW])
raw, was = (T / "store/a/32.json").read_bytes(), shape(32)
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a32", sender=BUILD, next=f"{BUILD}: prepare it\n{SIDE}: do the work"))
check("refused hand-off by a line of next: the refusal text comes back, nothing is stored", msg.startswith("Refused:") and "check" in msg and shape(32) == was and (T / "store/a/32.json").read_bytes() == raw, (msg, shape(32)))
# an accepted hand-off still works: the mover changes, the hand-off is recorded, and the writer is named in needs as its own save
put(33, mover=REVIEW, needs=[REVIEW])
r = refusal(lambda: _wt_update.stackshot_update(item_id="a33", sender=REVIEW, mover=BUILD, next=f"{REVIEW}: handed it over", check="item_closed a1"))
m33 = rd(33)["metadata"]
check("accepted hand-off: the mover changes and the hand-off to it is recorded", r == "" and telling.holder(rd(33)) == BUILD and (m33.get("handoff") or {}).get("to") == BUILD and (m33.get("handoff") or {}).get("from"), (r, m33))
put_his(34)
r = refusal(lambda: _wt_update.stackshot_update(item_id="a34", sender=REVIEW, mover=OWNER, then=BUILD, next=f"{OWNER}: pick one"))
check("accepted write on an item that waits on his call: stored, the writer named in needs", r == "" and REVIEW in (rd(34)["metadata"].get("needs") or []), (r, shape(34)))

# ---- the needs gate reads roles through the same helper and still refuses a front agent
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a1", sender=REVIEW, needs=[MAIN]))
check("needs: a user-facing agent is still refused there", "is a user-facing agent of" in msg and BUILD in msg, msg)

# ---- the tool text says it
form = _wt_text._MODEL_FORM
check("tool text: mover and then say a front agent is named only by itself and another session's write is refused", "a front agent (a session" in form and "only by itself" in form and "gets the project's builder instead" in form and "then=<front agent> from another session gets the builder the same way" in form, form[:800])

snap = json.loads(pathlib.Path(SCR, "tool_text.snapshot.json").read_text(encoding="utf-8"))
snap_s = json.dumps(snap)
check("tool text: the mover and then parameters of create and update carry the fix (snapshot)", snap_s.count("from another session that sets mover=<front agent> gets the project's builder instead") >= 2
      and snap_s.count("from another session that sets then=<front agent> gets the project's builder instead") >= 2, snap_s[:300])

check("tool text: post_wake_mover is named as the old name of mover, and mover carries the front-agent rule", "post_wake_mover, the old name of mover, is still read as mover" in form and "a front agent (a session" in form, form[:200])
check("tool text: update's own hand-over sentence says a front agent is not told and the builder is used", "an update from another session that sets mover or then (or post_wake_mover, the old name of mover) to a front agent gets the project's builder instead" in _wt_update._UPDATE_DESC, _wt_update._UPDATE_DESC[:200])

check("tool text: the post_wake_mover parameter of create and update carries the fix (snapshot)",
      json.dumps(json.loads(pathlib.Path(SCR, "tool_text.snapshot.json").read_text(encoding="utf-8"))).count("sets post_wake_mover=<front agent> gets the project's builder instead") >= 2)

_cdecl = _wt_create._CREATE_DESC
check("tool text: create's own description says another session's front-agent mover, then or post_wake_mover gets the builder",
      "a create from another session that sets mover or then (or post_wake_mover, the old name of mover) to a front agent gets the project's builder instead" in _cdecl, _cdecl[:300])

# ---- a front agent hands an item to a sibling front agent of its project on the owner's words (said, checked as the wake cap checks it)
import datetime as _dt
def call(fn):
    """the tool's reply, or the refusal's text when it refuses (a mutant that breaks the rule fails a check, it does not end the suite)"""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        return str(e)
M_OK, M_OLD = "aaaaaaaa-aaaa-4aaa-8aaa-000000000001", "aaaaaaaa-aaaa-4aaa-8aaa-000000000002"
QUOTE = "hand all of these to the desk agent"
stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
(T / f"transcripts/-x/{U[MAIN]}.jsonl").write_text("\n".join(json.dumps(e) for e in (
    {"type": "user", "uuid": M_OK, "timestamp": stamp, "origin": {"kind": "human"}, "message": {"role": "user", "content": f"{OWNER} here: {QUOTE}, please"}},
    {"type": "user", "uuid": M_OLD, "timestamp": "2020-01-01T00:00:00.000Z", "origin": {"kind": "human"}, "message": {"role": "user", "content": "an old order, long before the cap"}})) + "\n", encoding="utf-8")
SAID = [{"tag": "Acked-by", "quote": QUOTE, "msg": M_OK, "session": U[MAIN]}]
BADMSG = [{"tag": "Acked-by", "quote": QUOTE, "msg": "bbbbbbbb-bbbb-4bbb-8bbb-000000000009", "session": U[MAIN]}]      # no such message in the transcript: the check refuses it
OLD = [{"tag": "Acked-by", "quote": "an old order", "msg": M_OLD, "session": U[MAIN]}]      # his message, but older than the cap: no words behind a wait
POINTER = f"to hand it to {SIDE} on {OWNER}'s order, send the update again with said=[Acked-by …] quoting his words with the time"
STRANGER2 = "home-stranger"
def to(user):
    return [t for t in told if t[1] == U[user] and t[3] == "handoff"]
def kept(reply, field, front):
    return f"{field}={front} is kept as you sent it, on {OWNER}'s words in said" in reply and "(fixed:" not in reply and "was used instead" not in reply

put(50, mover=MAIN)
told.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a50", sender=MAIN, mover=SIDE, next=f"{SIDE}: take it from here", said=SAID))
m50 = rd(50)["metadata"]
check("sibling: mover=<sibling front> with the owner's words stays as sent, with a note that says so", kept(r, "mover", SIDE) and telling.holder(rd(50)) == SIDE and m50.get("mover") == SIDE, (r, m50.get("mover")))
check("sibling: nothing is substituted and no front-mover mark is left on the item", "front_mover" not in json.dumps(m50.get("server_fixed") or ""), m50.get("server_fixed"))
n50 = to(SIDE)
check("sibling: the sibling is told by the hand-off notice, which names who handed it over and quotes his words", len(n50) == 1 and f"handed to you by {MAIN}" in n50[0][2] and f"{OWNER}'s words" in n50[0][2] and QUOTE in n50[0][2], told)
check("sibling: the reply says the sibling has been told, and the hand-off record keeps his words", f"{SIDE} has been told" in r and QUOTE in str((m50.get("handoff") or {}).get("words")), (r, m50.get("handoff")))
check("sibling: his words are stored on the item as a checked said entry", any(e.get("tag") == "Acked-by" and e.get("checked") for e in (m50.get("said") or [])), m50.get("said"))

# then and post_wake_mover: kept as sent; the answer or the wake hands the item over and tells it (as for a front-only project)
put(51, mover=OWNER, needs=["decision"], ask="Decide: a or b - Recommend: a - Stakes: none - By: no date", then=REVIEW, state="your-call")
told.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a51", sender=MAIN, then=SIDE, said=SAID))
check("sibling: then=<sibling front> with the owner's words stays as sent", kept(r, "then", SIDE) and rd(51)["metadata"].get("then") == SIDE, (r, rd(51)["metadata"].get("then")))
put(52, mover=BUILD)
r = call(lambda: _wt_update.stackshot_update(item_id="a52", sender=MAIN, post_wake_mover=SIDE, said=SAID))
check("sibling: post_wake_mover=<sibling front> with the owner's words stays as sent", kept(r, "post_wake_mover", SIDE), r)

# agent= (the older form: the session named in needs)
put(53, mover=MAIN, needs=[MAIN])
told.clear()
r = refusal(lambda: _wt_update.stackshot_update(item_id="a53", sender=MAIN, agent=SIDE, next=f"{SIDE}: take it from here", said=SAID))
check("sibling: agent=<sibling front> with the owner's words is accepted and the item moves to it", r == "" and telling.holder(rd(53)) == SIDE and any(SIDE in str(x) or U[SIDE] in str(x) for x in (rd(53)["metadata"].get("needs") or [])), (r, rd(53)["metadata"].get("needs"), telling.holder(rd(53))))
check("sibling: agent=: the sibling is told, with the hand-off notice and his words", len(to(SIDE)) == 1 and QUOTE in to(SIDE)[0][2], told)
put(54, mover=MAIN, needs=[MAIN])
r = refusal(lambda: _wt_update.stackshot_update(item_id="a54", sender=MAIN, agent=SIDE, next=f"{SIDE}: take it from here"))
check("sibling: agent=<sibling front> with no words is refused as before, and the refusal ends with the one clause on how to send them", r.startswith("Refused:") and "is a user-facing agent of" in r and r.count(POINTER) == 1 and telling.holder(rd(54)) == MAIN, r)
r = refusal(lambda: _wt_update.stackshot_update(item_id="a54", sender=MAIN, agent=SIDE, next=f"{SIDE}: take it from here", said=BADMSG))
check("sibling: agent= with words the check refuses is refused, with the pointer, and the said refusal comes too", r.startswith("Refused:") and POINTER in r and "no message" in r, r)
put(55, mover=BUILD, needs=[BUILD])
r = refusal(lambda: _wt_update.stackshot_update(item_id="a55", sender=BUILD, agent=SIDE, next=f"{SIDE}: take it", said=SAID))
check("sibling: agent=<front> by a background agent is refused as before, with no pointer", r.startswith("Refused:") and "is a user-facing agent of" in r and "said=[Acked-by" not in r, r)

# a create carries the words too
told.clear()
r = call(lambda: _wt_create.stackshot_create(subject="[home] handed to the desk", description=DESC, project="projects/delta", sender=MAIN, mover=SIDE, next=f"{SIDE}: look at it", said=SAID))
g = r.split()[1]
check("sibling: a create with the owner's words keeps mover=<sibling front>, and the sibling is told with his words", r.startswith("created") and telling.holder(rd(g)) == SIDE and kept(r, "mover", SIDE) and len(to(SIDE)) == 1 and QUOTE in to(SIDE)[0][2], (r, told))
told.clear()
r = call(lambda: _wt_create.stackshot_create(subject="[home] handed to the desk, no words", description=DESC, project="projects/delta", sender=MAIN, mover=SIDE, next=f"{BUILD}: look at it"))
check("sibling: a create with no words gets the builder and the create's pointer", telling.holder(rd(r.split()[1])) == BUILD and "send the create again with said=[Acked-by …]" in r and not to(SIDE), (r, told))

# no words: today's swap, with the one clause; the clause is there for mover, then and post_wake_mover alike
put(56, mover=BUILD)
told.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a56", sender=MAIN, mover=SIDE, next=f"{BUILD}: check it"))
check("sibling, no said: mover goes to the builder as before and the note ends with the pointer", fixed(r, SIDE) and telling.holder(rd(56)) == BUILD and r.count(POINTER) == 1 and POINTER in next(ln for ln in r.splitlines() if ln.startswith("(fixed:")), r)
check("sibling, no said: nobody is told", not to(SIDE), told)
put(57, mover=OWNER, needs=["decision"], ask="Decide: a or b - Recommend: a - Stakes: none - By: no date", then=REVIEW, state="your-call")
r = call(lambda: _wt_update.stackshot_update(item_id="a57", sender=MAIN, then=SIDE))
check("sibling, no said: then goes to the builder as before, with the pointer", fixed(r, SIDE, "then") and rd(57)["metadata"].get("then") == BUILD and POINTER in r, r)
put(58, mover=BUILD)
r = call(lambda: _wt_update.stackshot_update(item_id="a58", sender=MAIN, post_wake_mover=SIDE))
check("sibling, no said: post_wake_mover goes to the builder as before, with the pointer", fixed(r, SIDE, "post_wake_mover") and POINTER in r, r)
# said the check refuses: as no said (the swap note carries the pointer; the write's own said check then refuses the write as a whole)
put(59, mover=BUILD)
was = (T / "store/a/59.json").read_bytes()
r = refusal(lambda: _wt_update.stackshot_update(item_id="a59", sender=MAIN, mover=SIDE, next=f"{BUILD}: check it", said=BADMSG))
check("sibling, said that fails the check (a message not in the transcript): the write is refused, nothing is stored, nobody is told", r.startswith("Refused:") and "no message" in r and telling.holder(rd(59)) == BUILD and not to(SIDE) and (T / "store/a/59.json").read_bytes() == was, r)
r = call(lambda: _wt_update.stackshot_update(item_id="a59", sender=MAIN, mover=SIDE, next=f"{BUILD}: check it", said=OLD))
check("sibling, words older than the cap (a checked message that is no words behind a wait): as no said, the swap and the pointer", fixed(r, SIDE) and POINTER in r and telling.holder(rd(59)) == BUILD and not to(SIDE), r)
put(68, mover=BUILD)
told.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a68", sender=MAIN, mover=SIDE, next=f"{BUILD}: check it", said=f"{OWNER} here: {QUOTE}, please"))
check("sibling, said as plain text: found in the sender's transcript by its quote, it is his checked words (the plain form is the same check)", kept(r, "mover", SIDE) and telling.holder(rd(68)) == SIDE and len(to(SIDE)) == 1, (r, told))
put(69, mover=BUILD)
told.clear()
r = refusal(lambda: _wt_update.stackshot_update(item_id="a69", sender=MAIN, mover=SIDE, next=f"{BUILD}: check it", said=f"{OWNER} here: a sentence nobody typed"))
check("sibling, said as plain text found in no transcript: not kept as sent, nobody told", "kept as you sent it, on" not in r and telling.holder(rd(69)) == BUILD and not to(SIDE), r)

# the unit: fix_front_mover with the words handed as a callable
from stackshot.service import gates as _gates
chk = [{"tag": "Acked-by", "quote": QUOTE, "checked": True, "ts": time.time(), "msg": M_OK}]
unchk = [{"tag": "Acked-by", "quote": QUOTE, "checked": False, "ts": time.time(), "msg": M_OK}]
sug = [{"tag": "Suggested-by", "quote": QUOTE, "checked": True, "ts": time.time(), "msg": M_OK}]
for label, got, want_kept in (("a checked Acked-by", chk, True), ("an unchecked one", unchk, False), ("a checked Suggested-by", sug, False), ("none", [], False)):
    v, note, fx = _gates.fix_front_mover("mover", SIDE, MAIN, "projects/delta", "", {}, lambda got=got: got)
    check(f"fix_front_mover: {label} -> " + ("kept as sent, no fix recorded" if want_kept else "swapped to the builder"), (v == SIDE and not fx) if want_kept else (v == BUILD and len(fx) == 1 and POINTER in note), (v, note, fx))
v, note, fx = _gates.fix_front_mover("mover", SIDE, MAIN, "projects/delta", "", {}, None)
check("fix_front_mover: no words handed at all is the swap", v == BUILD and POINTER in note, (v, note))

# a hand-back: a front agent that holds the item's first open named step, as the item stands before the write, is kept as sent when the sender is the item's mover or the project's builder and the front agent is live,
# and a mover is told as a turn; every other case is the swap, as before
import contextlib, io
from stackshot.model import model_guards as _mg
STEPF = "carry out whichever way the owner picks"
def pushed(user):
    return [(t, k) for t, k in zip(told, kinds) if t[1] == U[user] and t[3] == "handoff"]
put(90, mover=BUILD, next=f"{MAIN}: {STEPF}")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a90", sender=BUILD, mover=MAIN))
check("hand-back: the builder sets mover=<the front agent that holds the first open step>: kept as sent, no swap, no fix recorded", "kept as you sent it: " + MAIN in r and "(fixed:" not in r and telling.holder(rd(90)) == MAIN and not rd(90)["metadata"].get("server_fixed"), (r, rd(90)["metadata"]))
check("hand-back: the front agent is pushed once, as a turn (kind empty), the notice names the session that handed it back", len(pushed(MAIN)) == 1 and pushed(MAIN)[0][1][3] == "" and BUILD in pushed(MAIN)[0][0][2] and "has been told it is handed" in r and " back)" in r, (told, kinds, r))
r = call(lambda: _wt_update.stackshot_update(item_id="a90", sender=BUILD, mover=MAIN))
check("hand-back: sending it again changes nothing and tells nobody again", telling.holder(rd(90)) == MAIN and len(pushed(MAIN)) == 1, (r, told))
put(190, mover=REVIEW, next=f"{MAIN}: {STEPF}")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a190", sender=REVIEW, mover=MAIN))
check("hand-back: the item's own mover (a background agent that is no builder) may hand it back", telling.holder(rd(190)) == MAIN and "(fixed:" not in r and len(pushed(MAIN)) == 1, (r, told))
put(192, mover=REVIEW, next=f"{MAIN}: {STEPF}")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a192", sender=BUILD, mover=MAIN))
check("hand-back: the project's builder may hand it back although another session moves the item", telling.holder(rd(192)) == MAIN and "(fixed:" not in r and len(pushed(MAIN)) == 1, (r, told))
put(191, mover=BUILD, next=f"{MAIN}: {STEPF}")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a191", sender=REVIEW, mover=MAIN))
check("hand-back: a third session (neither the mover nor the builder) is swapped to the builder, nobody told", fixed(r, MAIN) and telling.holder(rd(191)) == BUILD and not pushed(MAIN), (r, told))
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a191", sender=REVIEW, mover=MAIN))
check("hand-back: the third session sends the same value again (the mover's no): kept as sent as on main, and the front agent is told nothing, as no hand-back held for that write", telling.holder(rd(191)) == MAIN and "kept as you sent it" in r and not pushed(MAIN), (r, told))
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a191", sender=BUILD, mover=MAIN))
check("hand-back: ...and the same value sent again by anyone changes nothing and tells nobody (the mover is already the front agent)", telling.holder(rd(191)) == MAIN and not pushed(MAIN), (r, told))
put(291, mover=REVIEW, next=f"{MAIN}: {STEPF}")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a291", sender=REVIEW, mover=MAIN))
check("hand-back: the item's own mover hands it back once: kept as sent, the front agent pushed once", telling.holder(rd(291)) == MAIN and len(pushed(MAIN)) == 1, (r, told))
r = call(lambda: _wt_update.stackshot_update(item_id="a291", sender=REVIEW, mover=MAIN))
check("hand-back: ...the second send of the hand-back is silent", len(pushed(MAIN)) == 1, (r, told))
put(91, mover=BUILD, next=f"{BUILD}: build it")
r = call(lambda: _wt_update.stackshot_update(item_id="a91", sender=BUILD, mover=MAIN))
check("an open step that is the builder's: the swap stands", fixed(r, MAIN) and telling.holder(rd(91)) == BUILD, r)
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a91", sender=BUILD, mover=MAIN))
check("the swap's second send is kept as sent as before, and the front agent that holds no step is told nothing", telling.holder(rd(91)) == MAIN and "kept as you sent it" in r and not pushed(MAIN), (r, told))
put(92, mover=BUILD, next=f"{BUILD}: build it\n{MAIN}: carry out the result")
r = call(lambda: _wt_update.stackshot_update(item_id="a92", sender=BUILD, mover=MAIN))
check("the front agent's step comes after the builder's: the swap stands", fixed(r, MAIN) and telling.holder(rd(92)) == BUILD, r)
put(95, mover=BUILD)
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a95", sender=BUILD, mover=MAIN, next=f"{MAIN}: {STEPF}", check="item_closed a1"))
check("the step is written in the same call: the front-agent step gate refuses the write, and the item keeps its mover", "opens with " + MAIN in r and telling.holder(rd(95)) == BUILD and not pushed(MAIN), (r, told))
it95 = dict(rd(95), gid="a95")
v, note, fx = _gates.fix_front_mover("mover", MAIN, BUILD, "projects/delta", "", it95["metadata"], item=it95)
check("fix_front_mover: a step the same call adds is not in the stored item, so it is not read: the swap stands", v == BUILD and len(fx) == 1, (v, note, fx))
put(96, mover=BUILD, next=f"{MAIN}: {STEPF}")
_orig_state = _mg.Ctx.session_state
_mg.Ctx.session_state = lambda self, who: "gone" if who == MAIN else _orig_state(self, who)
try:
    told.clear(); kinds.clear()
    r = call(lambda: _wt_update.stackshot_update(item_id="a96", sender=BUILD, mover=MAIN))
finally:
    _mg.Ctx.session_state = _orig_state
check("the front agent is not live: the swap stands, with the stall line, nobody told", fixed(r, MAIN) and telling.holder(rd(96)) == BUILD and not pushed(MAIN), (r, told))
put(97, mover=BUILD, next=f"{MAIN.upper()}: {STEPF}")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a97", sender=BUILD, mover=MAIN))
check("a step line in another letter case still holds the step: kept as sent and the front agent is pushed as a turn", telling.holder(rd(97)) == MAIN and "(fixed:" not in r and len(pushed(MAIN)) == 1 and pushed(MAIN)[0][1][3] == "", (r[-300:], told, kinds, rd(97)["metadata"].get("mover")))
put(98, mover=BUILD, next=f"{OWNER}: check the sheet\n{MAIN}: {STEPF}")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a98", sender=BUILD, mover=MAIN))
check("the owner's own line comes first: the front agent's step is the first one past his lines, kept as sent and pushed as a turn", telling.holder(rd(98)) == MAIN and "(fixed:" not in r and len(pushed(MAIN)) == 1 and pushed(MAIN)[0][1][3] == "", (r, told, kinds))
err = io.StringIO()
with contextlib.redirect_stderr(err):
    r = call(lambda: _wt_create.stackshot_create(subject="[home] a create has no stored step", description=DESC, project="projects/delta", sender=BUILD, mover=MAIN, next=f"{BUILD}: build it"))
check("a create has no stored item: the swap stands, and the hand-back read does not fail or print", fixed(r, MAIN) and "hand-back read" not in err.getvalue(), (r, err.getvalue()))
put(94, mover=OWNER, needs=["decision"], ask="Decide: a or b - Recommend: a - Stakes: none - By: no date", then=REVIEW, state="your-call", next=f"{MAIN}: {STEPF}")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a94", sender=BUILD, then=MAIN))
check("then=<the front agent that holds the open step> beside his call, by the builder: kept as sent, nobody told by the write (the answer tells it)", "kept as you sent it: " + MAIN in r and "(fixed:" not in r and rd(94)["metadata"].get("then") == MAIN and not pushed(MAIN), (r, rd(94)["metadata"]))
put(194, mover=OWNER, needs=["decision"], ask="Decide: a or b - Recommend: a - Stakes: none - By: no date", then=REVIEW, state="your-call", next=f"{BUILD}: build it\n{MAIN}: {STEPF}")
r = call(lambda: _wt_update.stackshot_update(item_id="a194", sender=BUILD, then=MAIN))
check("then=<the front agent> whose step comes after the builder's: swapped to the builder", fixed(r, MAIN, "then") and rd(194)["metadata"].get("then") == BUILD, (r, rd(194)["metadata"]))
put(195, mover=BUILD, next=f"{MAIN}: {STEPF}")
it = dict(rd(195), gid="a195")
v, note, fx = _gates.fix_front_mover("post_wake_mover", MAIN, BUILD, "projects/delta", "", it["metadata"], item=it)
check("fix_front_mover: post_wake_mover to the holder of the open step, by the builder, with the stored item: kept as sent", v == MAIN and not fx, (v, note, fx))
v, note, fx = _gates.fix_front_mover("post_wake_mover", MAIN, REVIEW, "projects/delta", "", it["metadata"], item=it)
check("fix_front_mover: post_wake_mover from a third session is swapped", v == BUILD and len(fx) == 1, (v, note, fx))
v, note, fx = _gates.fix_front_mover("post_wake_mover", MAIN, BUILD, "projects/delta", "", {"project": "projects/delta", "next": f"{MAIN}: {STEPF}"})
check("fix_front_mover: with no stored item handed (a create) post_wake_mover is swapped too", v == BUILD and len(fx) == 1, (v, note, fx))

# the hand-back's guards beyond the sender: a front agent that moves the item hands it to a sibling only on the owner's words; the holder is a front agent of the item's project; the write leaves the holder's step open
put(200, mover=MAIN, next=f"{SIDE}: {STEPF}")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a200", sender=MAIN, mover=SIDE))
check("hand-back: a front agent that moves the item hands it to the sibling that holds the first step with no words of the owner: swapped to the builder as on main, the sibling told nothing", fixed(r, SIDE) and telling.holder(rd(200)) == BUILD and not pushed(SIDE) and not to(SIDE), (r, told))
put(201, mover=BUILD, next=f"{ECHO}: {STEPF}")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a201", sender=BUILD, mover=ECHO))
check("hand-back: a front agent of another project named in a step of this project's item: swapped to the builder, nobody told", fixed(r, ECHO) and telling.holder(rd(201)) == BUILD and not pushed(ECHO), (r, told))
put(202, mover=BUILD, next=f"{MAIN}: {STEPF}")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a202", sender=BUILD, mover=MAIN, done=[1], next=f"{BUILD}: carry on"))
check("hand-back: the same call ticks the front agent's step done: no step is left for the notice, so the swap stands and nobody is told", fixed(r, MAIN) and telling.holder(rd(202)) == BUILD and not pushed(MAIN), (r, told, rd(202)["metadata"].get("mover")))
put(204, mover=BUILD, next=f"{MAIN}: {STEPF}")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a204", sender=BUILD, mover=MAIN, dropped=[1], next=f"{BUILD}: carry on"))
check("hand-back: the same call drops the front agent's step: the swap stands and nobody is told", fixed(r, MAIN) and telling.holder(rd(204)) == BUILD and not pushed(MAIN), (r, told, rd(204)["metadata"].get("mover")))
put(205, mover=BUILD, next=f"{MAIN}: {STEPF}")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a205", sender=BUILD, mover=MAIN, clear_next=True, next=f"{BUILD}: carry on"))
check("hand-back: the same call clears next: the swap stands and nobody is told", fixed(r, MAIN) and telling.holder(rd(205)) == BUILD and not pushed(MAIN), (r, told, rd(205)["metadata"].get("mover")))
put(206, mover=BUILD, next=f"{MAIN}: {STEPF}")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a206", sender=BUILD, mover=MAIN, status="completed", outcome="done", reason="the thing is done", outcome_text="- It is done"))
check("hand-back: the same call closes the item: a completed item has no mover, so the write is refused whole (the gate's `ends` is the unit below), the item keeps its mover and nobody is told", "has no mover" in r and telling.holder(rd(206)) == BUILD and not pushed(MAIN), (r[:200], told))
put(207, mover=BUILD, next=f"{BUILD}: build it\n{MAIN}: {STEPF}")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a207", sender=BUILD, mover=MAIN, done=[1]))
check("hand-back: the builder's own step is first as the item stands, and the call ticks it: read as the item stood, so the swap stands", fixed(r, MAIN) and telling.holder(rd(207)) == BUILD and not pushed(MAIN), (r, told))
put(208, mover=BUILD, next=f"{MAIN}: {STEPF}\n{BUILD}: build it")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a208", sender=BUILD, mover=MAIN, done=[2]))
check("hand-back: the call ticks another step than the holder's (step 2, the builder's, after it): kept as sent and the front agent is pushed as a turn", telling.holder(rd(208)) == MAIN and len(pushed(MAIN)) == 1 and pushed(MAIN)[0][1][3] == "", (r, told, kinds))
check("the update tool leaves no hand-back flag behind after a write that handed an item back", not getattr(telling.HO_STATE, "handback", None), getattr(telling.HO_STATE, "handback", None))
put(203, mover=BUILD, next=f"{BUILD}: build it", steps=[{"text": f"{MAIN}: {STEPF}", "status": "done"}, {"text": f"{BUILD}: build it", "status": "open"}])
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a203", sender=BUILD, mover=MAIN))
check("hand-back: the front agent's first named step is done and the builder's is open: the holder is the builder, so the swap stands", fixed(r, MAIN) and telling.holder(rd(203)) == BUILD and not pushed(MAIN), (r, told, rd(203)["metadata"]))
put(210, mover=BUILD, next=f"{OWNER}: check the sheet\n{MAIN}: {STEPF}")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a210", sender=BUILD, mover=MAIN, done=[2], next=f"{BUILD}: carry on"))
check("hand-back: the holder's step stands after the owner's own line (position 1), and the call ticks it by its number: the swap stands, nobody is told", fixed(r, MAIN) and telling.holder(rd(210)) == BUILD and not pushed(MAIN), (r, told))
put(211, mover=BUILD, next=f"{OWNER}: check the sheet\n{MAIN}: {STEPF}")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a211", sender=BUILD, mover=MAIN))
check("hand-back: the same item with no marks: kept as sent and the front agent is pushed once", telling.holder(rd(211)) == MAIN and len(pushed(MAIN)) == 1, (r, told))
put(212, mover=BUILD, next=f"{MAIN}: {STEPF}\n{BUILD}: build it")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a212", sender=BUILD, mover=MAIN, done=[f"{MAIN}: {STEPF}"]))
check("hand-back, a call that settles the holder's step through done as the exact text of the holder's step: the swap stands and nobody is told", fixed(r, MAIN) and telling.holder(rd(212)) == BUILD and not pushed(MAIN), (r[:300], told, rd(212)["metadata"].get("mover")))
put(213, mover=BUILD, next=f"{MAIN}: {STEPF}\n{BUILD}: build it")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a213", sender=BUILD, mover=MAIN, done="[1]"))
check("hand-back, a call that settles the holder's step through done as a JSON string: the swap stands and nobody is told", fixed(r, MAIN) and telling.holder(rd(213)) == BUILD and not pushed(MAIN), (r[:300], told, rd(213)["metadata"].get("mover")))
put(214, mover=BUILD, next=f"{MAIN}: {STEPF}\n{BUILD}: build it")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a214", sender=BUILD, mover=MAIN, dropped=[f"{MAIN}: {STEPF}"]))
check("hand-back, a call that settles the holder's step through dropped as the exact text of the holder's step: the swap stands and nobody is told", fixed(r, MAIN) and telling.holder(rd(214)) == BUILD and not pushed(MAIN), (r[:300], told, rd(214)["metadata"].get("mover")))
put(215, mover=BUILD, next=f"{MAIN}: {STEPF}\n{BUILD}: build it")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a215", sender=BUILD, mover=MAIN, done="1,2", next=f"{BUILD}: carry on"))
check("hand-back, a call that settles the holder's step through done as a comma list that holds the holder's step: the swap stands and nobody is told", fixed(r, MAIN) and telling.holder(rd(215)) == BUILD and not pushed(MAIN), (r[:300], told, rd(215)["metadata"].get("mover")))
put(216, mover=BUILD, next=f"{MAIN}: {STEPF}\n{BUILD}: build it")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a216", sender=BUILD, mover=MAIN, done="1"))
check("hand-back, a call that settles the holder's step through done as the text of a number: the swap stands and nobody is told", fixed(r, MAIN) and telling.holder(rd(216)) == BUILD and not pushed(MAIN), (r[:300], told, rd(216)["metadata"].get("mover")))
put(217, mover=BUILD, next=f"{MAIN}: {STEPF}\n{BUILD}: build it")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a217", sender=BUILD, mover=MAIN, reword={"1": f"{BUILD}: now mine"}))
check("hand-back, a call that settles the holder's step through reword of the holder's step by its position: the swap stands and nobody is told", fixed(r, MAIN) and telling.holder(rd(217)) == BUILD and not pushed(MAIN), (r[:300], told, rd(217)["metadata"].get("mover")))
put(218, mover=BUILD, next=f"{MAIN}: {STEPF}\n{BUILD}: build it")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a218", sender=BUILD, mover=MAIN, reword={f"{MAIN}: {STEPF}": f"{BUILD}: now mine"}))
check("hand-back, a call that settles the holder's step through reword of the holder's step by its exact text: the swap stands and nobody is told", fixed(r, MAIN) and telling.holder(rd(218)) == BUILD and not pushed(MAIN), (r[:300], told, rd(218)["metadata"].get("mover")))
put(219, mover=BUILD, next=f"{MAIN}: {STEPF}\n{BUILD}: build it")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a219", sender=BUILD, mover=MAIN, done=[f"{BUILD}: build it"]))
check("hand-back, done as the exact text of another step: the holder's step is left open, so it is kept as sent and the front agent is pushed once", telling.holder(rd(219)) == MAIN and "(fixed:" not in r and len(pushed(MAIN)) == 1, (r[:300], told))
put(220, mover=BUILD, next=f"{MAIN}: {STEPF}\n{BUILD}: build it")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a220", sender=BUILD, mover=MAIN, done="[2]"))
check("hand-back, done as a JSON string of another step: the holder's step is left open, so it is kept as sent and the front agent is pushed once", telling.holder(rd(220)) == MAIN and "(fixed:" not in r and len(pushed(MAIN)) == 1, (r[:300], told))
put(221, mover=BUILD, next=f"{MAIN}: {STEPF}\n{BUILD}: build it")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a221", sender=BUILD, mover=MAIN, reword={"2": f"{BUILD}: review the result"}))
check("hand-back, reword of another step: the holder's step is left open, so it is kept as sent and the front agent is pushed once", telling.holder(rd(221)) == MAIN and "(fixed:" not in r and len(pushed(MAIN)) == 1, (r[:300], told))
put(222, mover=BUILD, next=f"{MAIN}: {STEPF}\n{BUILD}: build it")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a222", sender=BUILD, mover=MAIN, done=["no such step"]))
check("hand-back, a done ref no step reads: the write is refused whole, the mover stays and nobody is told", telling.holder(rd(222)) == BUILD and not pushed(MAIN) and "no open step reads" in r, (r[:300], told))
put(223, mover=BUILD, next=f"{MAIN}: {STEPF}\n{BUILD}: build it")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a223", sender=BUILD, mover=MAIN, work={"state": "done", "agent": MAIN}))
check("hand-back, a work status done that finishes the holder's step (agent names it): no step is left for the notice, so the swap stands or the call is refused, and nobody is told", telling.holder(rd(223)) != MAIN and not pushed(MAIN), (r[:300], told, rd(223)["metadata"].get("mover")))
put(227, mover=BUILD, next=f"{MAIN}: {STEPF}\n{BUILD}: build it")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a227", sender=BUILD, mover=MAIN, work={"state": "done", "remove": True, "agent": MAIN}))
check("hand-back, a work line removed (remove: true) for the holder: it finishes no step, so the hand-back is kept as sent and the front agent is pushed once", telling.holder(rd(227)) == MAIN and "(fixed:" not in r and len(pushed(MAIN)) == 1, (r[:300], told, rd(227)["metadata"].get("mover")))
check("gates.step_marks: a work line removed (remove: true) marks no step", _gates.step_marks({"project": "projects/delta", "next": f"{MAIN}: {STEPF}\n{BUILD}: build it"}, work={"state": "done", "remove": True, "agent": MAIN}, sender=BUILD) == frozenset(), None)
# the flag: cleared at the start of every update, by the call that raises after the gate, and set by mover only
telling.HO_STATE.handback = {MAIN}
put(225, mover=BUILD, next=f"{MAIN}: {STEPF}\n{BUILD}: build it")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a225", sender=REVIEW, mover=MAIN))      # a third session: swapped (no hand-back)
telling.HO_STATE.handback = {MAIN}
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a225", sender=REVIEW, mover=MAIN))      # …and the mover's no
check("the update tool clears a flag an earlier write left behind before it reads the gate: the third session's resend tells nobody", not pushed(MAIN), (r[:200], told))
put(226, mover=BUILD, next=f"{MAIN}: {STEPF}\n{BUILD}: build it")
told.clear(); kinds.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a226", sender=BUILD, mover=MAIN, until="not a date at all"))
check("a call the gate kept as a hand-back and a later check refuses: refused, the mover stays, nobody is told", telling.holder(rd(226)) == BUILD and not pushed(MAIN), (r[:300], told))
check("…and the flag is cleared after that refusal", not getattr(telling.HO_STATE, "handback", None), getattr(telling.HO_STATE, "handback", None))
telling.HO_STATE.handback = set()
it_h = dict(rd(226), gid="a226")
m_h = it_h["metadata"]
for fld in ("then", "post_wake_mover"):
    telling.HO_STATE.handback = set()
    v_, n_, fx_ = _gates.fix_front_mover(fld, MAIN, BUILD, "projects/delta", "", m_h, item=it_h)
    check(f"fix_front_mover unit: {fld} kept as a hand-back sets no flag (the answer or the wake tells it)", v_ == MAIN and not telling.HO_STATE.handback, (v_, telling.HO_STATE.handback))
telling.HO_STATE.handback = set()
v_, n_, fx_ = _gates.fix_front_mover("mover", MAIN, BUILD, "projects/delta", "", m_h, item=it_h)
check("fix_front_mover unit: mover kept as a hand-back sets the flag", v_ == MAIN and telling.HO_STATE.handback == {MAIN}, telling.HO_STATE.handback)
telling.HO_STATE.handback = set()
# the units, with the stored item as the gate reads it
put(209, mover=BUILD, next=f"{MAIN}: {STEPF}")
it209 = dict(rd(209), gid="a209")
m209 = it209["metadata"]
def unit(sender, value=MAIN, project="projects/delta", **kw):
    return _gates.fix_front_mover("mover", value, sender, project, "", m209, item=it209, **kw)[0]
check("fix_front_mover unit: the builder hands it back: kept", unit(BUILD) == MAIN, None)
check("fix_front_mover unit: the holder's step is marked (position 0): swapped", unit(BUILD, marked=frozenset({0})) == BUILD, None)
check("fix_front_mover unit: another step is marked (position 1): kept", unit(BUILD, marked=frozenset({1})) == MAIN, None)
check("fix_front_mover unit: the write ends the item or clears next: swapped", unit(BUILD, ends=True) == BUILD, None)
check("handed_back unit: the builder, the holder a front agent of the item's project: held", _gates.handed_back(MAIN, BUILD, [BUILD], m209, it209, "projects/delta") is True, None)
check("handed_back unit: the item's project is another page than the front agent's: no hand-back", _gates.handed_back(MAIN, BUILD, [BUILD], m209, it209, "projects/echo") is False, None)
check("handed_back unit: no project: no hand-back", _gates.handed_back(MAIN, BUILD, [BUILD], m209, it209, "") is False, None)
check("fix_front_mover unit: a front agent that moves the item (the sender) hands it to the sibling that holds the step: swapped", _gates.fix_front_mover("mover", SIDE, MAIN, "projects/delta", "", {**m209, "next": f"{SIDE}: {STEPF}"}, item={**it209, "metadata": {**m209, "next": f"{SIDE}: {STEPF}", "mover": MAIN}})[0] == BUILD, None)
_orig_role = telling.front_role
telling.front_role = lambda who: None      # the roles could not be read
try:
    v_ = _gates.fix_front_mover("mover", MAIN, REVIEW, "projects/delta", "", m209, item={**it209, "metadata": {**m209, "mover": REVIEW}})[0]
finally:
    telling.front_role = _orig_role
check("fix_front_mover unit: the roles of the sender cannot be read: not read as 'no front agent', so the mover's hand-back is the swap", v_ == BUILD, v_)
v_ = _gates.fix_front_mover("mover", MAIN, REVIEW, "projects/delta", "", m209, item={**it209, "metadata": {**m209, "mover": REVIEW}})[0]
check("fix_front_mover unit: the same call with the roles readable and the sender the item's mover (no front agent): kept", v_ == MAIN, v_)
# the hand-off notice reads the gate's flag of this write, by session: a flag of another front agent tells this one nothing
it_n = dict(rd(211), gid="a211")
rec_ = (it_n["metadata"].get("handoff") or {})
told.clear(); kinds.clear()
telling.HO_STATE.told = set(); telling.HO_STATE.fresh = {"a211": (MAIN, rec_.get("at"))}; telling.HO_STATE.handback = {SIDE}
out_ = telling.handoff_notify("a211", it_n)
check("handoff_notify unit: the flag names another front agent than the one handed the item: nobody is told", out_ == "" and not pushed(MAIN), (out_, told))
telling.HO_STATE.told = set(); telling.HO_STATE.fresh = {"a211": (MAIN, rec_.get("at"))}; telling.HO_STATE.handback = {MAIN.upper()}
out_ = telling.handoff_notify("a211", it_n)
check("handoff_notify unit: the flag names this front agent (in another letter case): it is told as a turn", "has been told it is handed" in out_ and len(pushed(MAIN)) == 1, (out_, told))
it_gone = dict(it_n, metadata={**it_n["metadata"], "next": f"{BUILD}: build it", "steps": []})
told.clear(); kinds.clear()
telling.HO_STATE.told = set(); telling.HO_STATE.fresh = {"a211": (MAIN, rec_.get("at"))}; telling.HO_STATE.handback = {MAIN}
out_ = telling.handoff_notify("a211", it_gone)
check("handoff_notify unit: the flag is set but the front agent's step no longer stands after the write: nobody is told", out_ == "" and not pushed(MAIN), (out_, told))
telling.HO_STATE.handback = set()
m_two = {"project": "projects/delta", "next": f"{MAIN}: {STEPF}\n{BUILD}: build it"}
check("gates.step_marks: a number, its text, a comma list, a JSON string and the exact text of a step all read as the tool reads them (position less one)", _gates.step_marks(m_two, [1]) == frozenset({0}) and _gates.step_marks(m_two, "2") == frozenset({1}) and _gates.step_marks(m_two, "1,2") == frozenset({0, 1}) and _gates.step_marks(m_two, "[1]") == frozenset({0}) and _gates.step_marks(m_two, [f"{MAIN}: {STEPF}"]) == frozenset({0}) and _gates.step_marks(m_two, None, [f"{BUILD}: build it"]) == frozenset({1}) and _gates.step_marks(m_two) == frozenset(), None)
check("gates.step_marks: a reword names its step by position or text; a work status done is the sender's first open step (or the one named in agent)", _gates.step_marks(m_two, reword={"1": f"{BUILD}: now mine"}) == frozenset({0}) and _gates.step_marks(m_two, reword=f'{{"{BUILD}: build it": "{BUILD}: build it well"}}') == frozenset({1}) and _gates.step_marks(m_two, work={"state": "done"}, sender=BUILD) == frozenset({1}) and _gates.step_marks(m_two, work={"state": "done", "agent": MAIN}, sender=BUILD) == frozenset({0}) and _gates.step_marks(m_two, work={"text": "going on"}, sender=BUILD) == frozenset(), None)
check("gates.step_marks: a ref the tool cannot read (no such step, no such text, a bool, bad JSON for reword) is None, read by the gate as marking the holder's step", all(_gates.step_marks(m_two, **kw) is None for kw in ({"done": [9]}, {"done": ["no such step"]}, {"dropped": [True]}, {"reword": "not json"}, {"done": [0]})), None)
check("fix_front_mover unit: marks the gate cannot read (None) are the swap", unit(BUILD, marked=None) == BUILD, None)

# who may: a background agent, another project's session, a target that is no front agent of the project, a builderless project
put(60, mover=BUILD)
told.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a60", sender=REVIEW, mover=SIDE, next=f"{BUILD}: check it", said=SAID))
check("sibling, sender a background agent: swapped to the builder as before, with no pointer and nobody told", fixed(r, SIDE) and "said=[Acked-by" not in r and telling.holder(rd(60)) == BUILD and not to(SIDE), r)
put(61, mover=BUILD)
r = call(lambda: _wt_update.stackshot_update(item_id="a61", sender=ECHO, mover=SIDE, next=f"{BUILD}: check it", said=SAID))
check("sibling, sender another project's front agent: swapped to the builder as before, with no pointer and nobody told", fixed(r, SIDE) and "said=[Acked-by" not in r and telling.holder(rd(61)) == BUILD and not to(SIDE), r)
put(62, mover=BUILD)
r = call(lambda: _wt_update.stackshot_update(item_id="a62", sender=MAIN, mover=ECHO, next=f"{BUILD}: check it", said=SAID))
check("sibling, target another project's front agent: swapped to the builder as before, with no pointer", fixed(r, ECHO) and "said=[Acked-by" not in r and telling.holder(rd(62)) == BUILD, r)
put(63, mover=MAIN)
r = call(lambda: _wt_update.stackshot_update(item_id="a63", sender=MAIN, mover=BUILD, next=f"{BUILD}: build it", said=SAID))
check("sibling, target a background agent: a plain hand-off, no front-mover note", telling.holder(rd(63)) == BUILD and "kept as you sent it" not in r and "(fixed:" not in r, r)
put(64, mover=BUILD)
r = refusal(lambda: _wt_update.stackshot_update(item_id="a64", sender=STRANGER2, mover=SIDE, next=f"{BUILD}: check it", said=SAID))
check("sibling, sender no page lists: the swap as before, no pointer", "said=[Acked-by" not in r and telling.holder(rd(64)) == BUILD, r)

# a project with no builder: without words nothing changes (a listed session hands to a front agent, told by the notice, no pointer); with words the notice carries them
put(65, project="projects/golf", mover=GMAIN)
told.clear()
r = call(lambda: _wt_update.stackshot_update(item_id="a65", sender=GMAIN, mover=GDESK, next=f"{GDESK}: take it"))
check("builderless sibling, no said: kept as sent with the old note, no pointer, the sibling is told with no quoted words", "has no builder, so mover=" in r and "said=[Acked-by" not in r and telling.holder(rd(65)) == GDESK and len(to(GDESK)) == 1 and "words" not in to(GDESK)[0][2], (r, told))
put(66, project="projects/golf", mover=GMAIN)
told.clear()
(T / f"transcripts/-x/{U[GMAIN]}.jsonl").write_text(json.dumps({"type": "user", "uuid": "cccccccc-cccc-4ccc-8ccc-000000000001", "timestamp": stamp, "origin": {"kind": "human"}, "message": {"role": "user", "content": f"{OWNER} here: {QUOTE}, please"}}) + "\n", encoding="utf-8")
r = call(lambda: _wt_update.stackshot_update(item_id="a66", sender=GMAIN, mover=GDESK, next=f"{GDESK}: take it", said=[{"tag": "Acked-by", "quote": QUOTE, "msg": "cccccccc-cccc-4ccc-8ccc-000000000001", "session": U[GMAIN]}]))
check("builderless sibling, with words: kept as sent, and the notice carries his words", telling.holder(rd(66)) == GDESK and len(to(GDESK)) == 1 and QUOTE in to(GDESK)[0][2], (r, told))

# the second identical send: unchanged (kept as sent, the old note, nothing more told, no pointer)
put(67, mover=BUILD)
told.clear()
r1 = call(lambda: _wt_update.stackshot_update(item_id="a67", sender=MAIN, mover=SIDE, next=f"{BUILD}: check it"))
r2 = call(lambda: _wt_update.stackshot_update(item_id="a67", sender=MAIN, mover=SIDE, next=f"{BUILD}: check it"))
check("second identical send of a sibling front mover with no words: kept as sent with the old note and no pointer, nobody told", telling.holder(rd(67)) == SIDE and "kept as you sent it: " in r2 and "said=[Acked-by" not in r2 and not to(SIDE), (r2, told))

# an item that already carries his words from an earlier save: a later hand-off to a sibling with no words of its own save quotes none of them (the record keeps only the entries the very save added)
GSAID = [{"tag": "Acked-by", "quote": QUOTE, "msg": "cccccccc-cccc-4ccc-8ccc-000000000001", "session": U[GMAIN]}]
put(72, project="projects/golf", mover=GMAIN)
told.clear()
r1 = call(lambda: _wt_update.stackshot_update(item_id="a72", sender=GMAIN, mover=GDESK, next=f"{GDESK}: take it", said=GSAID))
check("earlier words: the first hand-off (with his words) quotes them and leaves them on the item", telling.holder(rd(72)) == GDESK and len(to(GDESK)) == 1 and QUOTE in to(GDESK)[0][2] and len(rd(72)["metadata"].get("said") or []) == 1, (r1, told))
told.clear()
r2 = call(lambda: _wt_update.stackshot_update(item_id="a72", sender=GDESK, mover=GMAIN, next=f"{GMAIN}: take it back"))
check("earlier words: a later hand-off to a sibling with no words in its own save is told with no quoted words, and its record keeps none", telling.holder(rd(72)) == GMAIN and len(to(GMAIN)) == 1 and QUOTE not in to(GMAIN)[0][2]
      and not (rd(72)["metadata"].get("handoff") or {}).get("words") and len(rd(72)["metadata"].get("said") or []) == 1, (r2, told, rd(72)["metadata"].get("handoff")))
# the same where the project has a builder: an item that carries his words from an earlier save, then two sends with no words (the first goes to the builder, the second is kept as sent, the old way: no notice, no words)
put(73, mover=BUILD, said=m50["said"])
told.clear()
r1 = call(lambda: _wt_update.stackshot_update(item_id="a73", sender=MAIN, mover=SIDE, next=f"{BUILD}: check it"))
check("earlier words: the first send with no words of its own goes to the builder, nobody is told", fixed(r1, SIDE) and telling.holder(rd(73)) == BUILD and not to(SIDE), (r1, told))
r2 = call(lambda: _wt_update.stackshot_update(item_id="a73", sender=MAIN, mover=SIDE, next=f"{BUILD}: check it"))
check("earlier words: the second identical send is kept as sent and the sibling is told none of the earlier words, nor does the record keep them",
      telling.holder(rd(73)) == SIDE and QUOTE not in " ".join(t[2] for t in to(SIDE)) and not (rd(73)["metadata"].get("handoff") or {}).get("words"), (r2, told, rd(73)["metadata"].get("handoff")))

# a create with agent=<sibling front>: the older form carries the words too, and with none the refusal ends with the pointer
told.clear()
r = call(lambda: _wt_create.stackshot_create(subject="[home] agent form with words", description=DESC, project="projects/delta", sender=MAIN, mover=MAIN, agent=SIDE, next=f"{MAIN}: look at it", said=SAID))
check("create agent=<sibling front> with the owner's words is accepted and names the sibling in needs", r.startswith("created") and any(SIDE in str(x) or U[SIDE] in str(x) for x in (rd(r.split()[1])["metadata"].get("needs") or [])), r)
r = call(lambda: _wt_create.stackshot_create(subject="[home] agent form without words", description=DESC, project="projects/delta", sender=MAIN, mover=MAIN, agent=SIDE, next=f"{MAIN}: look at it"))
check("create agent=<sibling front> with no words is refused as before, and the refusal ends with the pointer", r.startswith("Refused:") and "is a user-facing agent of" in r and "send the create again with said=[Acked-by" in r, r)
r = call(lambda: _wt_create.stackshot_create(subject="[home] agent form by a background agent", description=DESC, project="projects/delta", sender=BUILD, mover=BUILD, agent=SIDE, next=f"{BUILD}: look at it", said=SAID))
check("create agent=<sibling front> by a background agent is refused as before, with no pointer", r.startswith("Refused:") and "said=[Acked-by" not in r, r)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.stdout.flush()
os._exit(1 if fails else 0)
