"""Scenario test for the owner's steps on an item's checklist (rules N2, N4 and N5 of that design, for his part only) — fixture data, the tools called in-process, no live store, no network.

Covers: an item that asks him for a decision gets the open step `Oliver: <the Decide part of the ask>` from the server, written by the server (a session's update leaves it); through
create with an ask and through an update that adds the ask; a step= (the your-step state) gets `Oliver: <the step>`; a `Oliver:` line a session wrote already is adopted (no second step beside it); a changed
ask drops the old step and adds the new; his answer on the board ticks the step, done by him at the answer's time, with the picked option after an arrow (his words quoted for a text
answer), once, and a second answer adds nothing; Done on a your-step ticks it; an item stored before the server made his steps gets the step, done, with his answer; a session whose `done`
names his step while the item waits on him is refused and nothing is written, and may withdraw the ask, which drops his open step by that session (a stored your-step no call clears any more: step= sets it, a close drops it); a close settles it; the
wake pass and an idle write create and tick nothing wrongly; the stored fields stay what decides (the step follows needs, ask, the stored state and step on every save, N5).

    tests/run-suite owner_steps        → exit 0 / 1"""
import json, logging, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="oliverstepstest-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"


def write_toml():
    toml = _instance.apply(_instance.base_toml())
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                     (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'), (r'(?m)^owner = "the owner"', 'owner = "Oliver"'),
                     (r'(?m)^ui_open = true', 'ui_open = false'), (r'(?m)^sync = false', 'sync = true'), (r'(?m)^issues_repo = ""', 'issues_repo = "o/r"'),
                     (r'(?m)^api_url = "[^"]*"', 'api_url = "http://127.0.0.1:9"'), (r'(?m)^token_file = ""', f'token_file = "{tmp}/github.token"')):
        toml, n = re.subn(pat, rep, toml); assert n == 1, pat
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")


write_toml()
(T / "github.token").write_text("test-token\n")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "secrets"): (T / d).mkdir(parents=True)
OWNER = "00000000-0000-4000-8000-000000000001"
AGENT = "00000000-0000-4000-8000-000000000002"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}, AGENT: {"name": "home-agent", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-agent", "status": "active", "board": [], "board_open": 0}}}))
DESC = "- Goal: A thing, finished when it works"
ASK = "Decide: whether to ship it now · Recommend: ship · Stakes: a day either way · By: no date"
ASK2 = "Decide: whether to wait for the next release · Recommend: wait · Stakes: a week either way · By: no date"
OPTS = [{"label": "Wait", "line": "Wait for the next release", "recommended": False}, {"label": "Ship", "line": "Ship it now as it is", "recommended": True}]
STEP = "check that the box answers and say so"
D1, D2 = "whether to ship it now", "whether to wait for the next release"
def item(i, status="open", **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": DESC, "status": status,
                                                     "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                     "metadata": {"owner": OWNER, "project": "projects/alpha", "needs": ["home-agent"], "next": "home-agent: build it", **meta}}))
for i in (*range(1, 20), 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, *range(35, 40), *range(60, 74)):
    item(i)                                                       # items in the agent's hands
item(20, needs=["decision"], ask=ASK, options=OPTS)               # asked before the server made his steps: the list holds no step of his
item(21, needs=["decision"], ask=ASK, options=OPTS, next="home-agent: build it\nOliver: pick the release path")      # …with a `Oliver:` line a session wrote
item(22, state="your-step", step=STEP, needs=["home-agent"], next="home-agent: prepare the box")                         # …a your-step stored without his step on the list
CMD = "run `for p in a b; do echo $p; done` in a build-box terminal"
for i in (33, 34): item(i, state="your-step", step=CMD, next="home-agent: build it")      # a your-step whose step carries a command
(T / "store/next-id").write_text("40"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]

from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.model import steps as S; from stackshot.model import nextlines as NL; from stackshot.model import owner_steps as HS; from stackshot.web import itempage as IP; from stackshot.model import next_backfill as NB
from stackshot.web.tools import complete as _wt_complete
from stackshot.web.tools import create as _wt_create
from stackshot.web.tools import update as _wt_update
from stackshot.service import telling
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
server._refuse_if_owing = lambda debtor: None        # the page rule is not under test here
told = []
telling.tell_woken = lambda gid, owner, note, tag="wake": told.append((gid, owner, note, tag))
def refused(name, f, *want, i=None):
    was = rd(i) if i is not None else None
    try:
        out = f(); check(name, False, out)
    except server.ToolError as e:
        check(name, all(w in str(e) for w in want) and (was is None or rd(i) == was), str(e))
def upd(i, **kw): return _wt_update.stackshot_update(f"a{i}", sender="home-agent", **kw)
def st(i): return [(x["status"], x["text"]) for x in S.view(mt(i), keeper=OWNER)]
def his(i): return [(s, t) for s, t in st(i) if t.startswith("Oliver:")]
def writers(i): return dict(NL.resolve(mt(i), OWNER))
OPEN = lambda t: ("open", t)
H1, H2 = f"Oliver: {D1}", f"Oliver: {D2}"

# ---- 1. N2: an ask makes his step
r = upd(1, needs="decision", ask=ASK, options=OPTS)
check("an update that adds a decision ask: the server adds the open step `Oliver: <Decide part>` at the end of the list", his(1) == [OPEN(H1)] and st(1)[0] == OPEN("home-agent: build it"), st(1))
check("…it is a line of next too, written by the server, not by the session (a session's update never replaces it)", H1 in mt(1)["next"].splitlines() and writers(1).get(H1) == server.NAME, (mt(1), writers(1)))
check("…recorded as the server's step", mt(1).get("owner_step") == H1, mt(1))
upd(1, next="home-agent: build it, then test it")
check("a session's next write replaces its own lines and leaves his step", his(1) == [OPEN(H1)] and "home-agent: build it, then test it" in mt(1)["next"], st(1))
upd(1, description="- Goal: A thing, finished when it works\n- one more fact")
check("a write that touches neither the ask nor the next adds no second step", len(his(1)) == 1 and mt(1)["next"].count(H1) == 1, st(1))

r = _wt_create.stackshot_create(subject="[home] decide the thing", description=DESC, project="projects/alpha", needs="decision", ask=ASK, options=OPTS, next="home-agent: build it", sender="home-agent")
cid = re.match(r"created (\S+)", r).group(1)
cm = server._load(cid)["metadata"]
check("a create with an ask: his step is on the list from the first save, written by the server", [(x["status"], x["text"]) for x in S.view(cm, keeper=OWNER) if x["text"].startswith("Oliver:")] == [OPEN(H1)]
      and dict(NL.resolve(cm, OWNER)).get(H1) == server.NAME, (r, cm))

r = upd(2, step=STEP)
check("a step= (the your-step state) gets `Oliver: <the step>`", his(2) == [OPEN(f"Oliver: {STEP}")], (st(2), r))

# ---- 2. adoption: a `Oliver:` line that stands is not doubled
r = upd(3, next="home-agent: build it\nOliver: pick the release path")
r = upd(3, needs="decision", ask=ASK, options=OPTS)
check("a `Oliver:` line a session wrote about something else stays the session's: the server adds its step beside it", his(3) == [OPEN("Oliver: pick the release path"), OPEN(H1)] and mt(3).get("owner_step") == H1, st(3))
r = server._answer("a3", "Ship", "", "")
check("…and his answer ticks the server's step only; the session's line stays open", r == "decision" and his(3) == [OPEN("Oliver: pick the release path"), ("done", f"{H1} → Ship")], his(3))

# a session's line that says what the ask says is adopted: recorded as the server's step, none beside it
r = upd(18, next="home-agent: build it\nOliver: whether to ship it now")
r = upd(18, needs="decision", ask=ASK, options=OPTS)
check("a `Oliver:` line that says the same as the ask is adopted: one step, recorded as the server's", his(18) == [OPEN(H1)] and mt(18)["next"].count("Oliver:") == 1 and mt(18).get("owner_step") == H1, (st(18), mt(18)))
r = upd(18, clear_ask=True, clear_options=True, needs="home-agent")
check("…and withdrawing the ask drops the adopted line like the server's own", [s for s, _ in his(18)] == ["dropped"] and "owner_step" not in mt(18), st(18))

TQ = "Oliver: open [the pane](https://sala.example/#s=home-pane) and answer: `Run it now, or wait?`"
r = upd(25, next=f"home-agent: build it\n{TQ}")
r = upd(25, step="Answer home-pane's question in its terminal")
check("the terminal prompt's own question line is his step itself: adopted, recorded, no second step beside it", his(25) == [OPEN(TQ)] and mt(25).get("owner_step") == TQ, (st(25), mt(25)))
r = upd(25, priority="p1")
check("…and a later save leaves it as it is (no reword to the step's summary)", his(25) == [OPEN(TQ)] and mt(25).get("owner_step") == TQ, st(25))

# a session's `Oliver:` line about something else (a review request, a stale command) never blocks the server's step, is never ticked or dropped by it
r = upd(16, next="home-agent: build it\nOliver: review PR 12 when you can")
r = upd(16, needs="decision", ask=ASK, options=OPTS)
check("a session's `Oliver: review PR 12` line then an ask: the server adds its own step beside it", his(16) == [OPEN("Oliver: review PR 12 when you can"), OPEN(H1)] and mt(16).get("owner_step") == H1, st(16))
r = server._answer("a16", "Ship", "", "")
check("…his answer ticks the server's step, never the PR 12 line", r == "decision" and his(16) == [OPEN("Oliver: review PR 12 when you can"), ("done", f"{H1} → Ship")], his(16))
r = upd(17, next="home-agent: build it\nOliver: run uptime")
r = upd(17, step=STEP)
check("a stale `Oliver: run uptime` line stands: a new your-step still gets its own step beside it", his(17) == [OPEN("Oliver: run uptime"), OPEN(f"Oliver: {STEP}")] and mt(17).get("owner_step") == f"Oliver: {STEP}", st(17))
r = upd(17, done=["Oliver: run uptime"])
check("a session may tick its own `Oliver:` line while his step stands (it is not his step), and his step stays open", his(17) == [("done", "Oliver: run uptime"), OPEN(f"Oliver: {STEP}")], st(17))
refused("…while done on the server's step is still refused", lambda: upd(17, done=[f"Oliver: {STEP}"]), "only his answer", i=17)

# ---- 3. a changed ask rewords the step
r = upd(4, needs="decision", ask=ASK, options=OPTS)
check("(setup) item the item asks", his(4) == [OPEN(H1)], st(4))
r = upd(4, ask=ASK2, options=OPTS)
check("a changed ask: the old step is dropped and the new one added, in that order, once", [s for s, _ in his(4)] == ["dropped", "open"] and his(4)[0][1] == H1 and his(4)[1][1] == H2 and mt(4)["next"].count("Oliver:") == 1, st(4))
check("…the drop is the server's, with a time", mt(4)["steps"][[x["text"] for x in mt(4)["steps"]].index(H1)]["by"] == server.NAME, mt(4)["steps"])

# ---- 4. N4: his answer ticks, shown on the step
t0 = time.time()
r = server._answer("a1", "Ship", "", "")
s1 = [x for x in mt(1)["steps"] if x["text"].startswith("Oliver:")]
check("his option answer ticks his step: done by Oliver, at the answer's time, the picked label after an arrow", r == "decision" and len(s1) == 1 and s1[0]["status"] == "done" and s1[0]["by"] == "Oliver"
      and t0 - 1 <= s1[0]["at"] <= time.time() + 1 and s1[0]["text"] == f"{H1} → Ship", s1)
check("…the step has left next (next holds the open lines only), the server's record of it is gone", H1 not in mt(1)["next"] and "owner_step" not in mt(1), mt(1))
check("…and the item no longer waits on him", "decision" not in (mt(1).get("needs") or []) and "ask" not in mt(1), mt(1))
r2 = server._answer("a1", "Ship", "", "")
check("a second answer is stale and adds nothing", r2 == "stale" and rd(1) == rd(1) and len(his(1)) == 1, (r2, his(1)))
b1 = rd(1)
upd(1, next="home-agent: look at the result", dropped=["home-agent: build it, then test it"])
check("a later session write adds no step of his (the item does not wait on him)", his(1) == [("done", f"{H1} → Ship")] and rd(1)["metadata"]["steps"][-1]["status"] in ("open",), his(1))

r = upd(5, needs="decision", ask=ASK, options=OPTS)
r = server._answer("a5", "", "ship it after lunch, not before the demo today and not on a Friday either, please keep that in mind", "answer")
check("a text answer ticks the step with his words quoted after the arrow, cut at 60 characters", r == "decision" and his(5)[0][0] == "done" and re.fullmatch(rf'{re.escape(H1)} → "ship it after lunch.{{40,70}}…"', his(5)[0][1]), his(5))

r = server._answer("a20", "Wait", "", "")
check("an item that asked before the server made his steps gets the step now, done, with his answer", r == "decision" and his(20) == [("done", f"{H1} → Wait")] and mt(20)["steps"][-1]["by"] == "Oliver", (his(20), mt(20).get("steps")))

r = server._answer("a21", "Ship", "", "")
check("a `Oliver:` line a session wrote about something else, on a stored ask: his answer adds the server's step and ticks it, the session's line stays open", r == "decision" and his(21) == [OPEN("Oliver: pick the release path"), ("done", f"{H1} → Ship")], his(21))

# ---- 5. Done on a your-step
r = server._answer("a2", "", "", "done")
check("Done on a your-step ticks his step (the path that is there): done by Oliver, no arrow", r == "done" and his(2) == [("done", f"Oliver: {STEP}")] and mt(2)["steps"][-1]["by"] == "Oliver", (r, his(2)))
r = server._answer("a22", "", "", "done")
check("Done on a your-step stored before the server made his steps leaves the list as it was (nothing to tick)", r == "done" and his(22) == [] , (r, st(22)))

# ---- 5b. an answer to an ask ticks the ask's step, never the step of a your-step that stands beside it (only his Done or a note on the step does that)
r = upd(33, needs="decision", ask=ASK, options=OPTS)
HC = f"Oliver: {CMD}"
check("(setup) a your-step with a command, then an ask beside it: his step is the command's, one line", (HC in [t for _, t in his(33)]) and [s for s, t in his(33) if t == HC] == ["open"], st(33))
r = server._answer("a33", "Ship", "", "")
check("his plain answer to the ask is recorded and the ask leaves", r == "decision" and "ask" not in mt(33) and "decision" not in (mt(33).get("needs") or []), (r, mt(33)))
check("…but it does not tick the step that tells him to run the command: that line stays open, once, and the answer is its own done line",
      [(s, t) for s, t in his(33) if s == "open"] == [OPEN(HC)] and ("done", f"{H1} → Ship") in his(33) and HC not in [t for s, t in his(33) if s == "done"], his(33))
check("…the your-step stands, the recorded step is still the command's, and nothing was added a second time", mt(33).get("state") == "your-step" and mt(33).get("owner_step") == HC and mt(33)["next"].count(HC) == 1, mt(33))
upd(33, priority="p1")
check("…a later session write adds no fresh copy of it", [t for s, t in his(33) if s == "open"] == [HC], st(33))
r = server._answer("a33", "", "", "send")
check("only his Done ticks the command's step (done by him, no arrow)", r == "done" and (("done", HC) in his(33)) and not [1 for s, _ in his(33) if s == "open"], (r, his(33)))
upd(34, needs="decision", ask=ASK, options=OPTS)
r = server._answer("a34", "", "yes please, go on", "answer")
check("a free-text answer to the ask leaves the command's step open too", r == "decision" and [t for s, t in his(34) if s == "open"] == [HC], (r, his(34)))

# ---- 6. N4: a session cannot tick his step; it may withdraw
r = upd(6, needs="decision", ask=ASK, options=OPTS)
refused("a session's done naming his step while the item waits on him is refused, naming his answer and the withdrawal", lambda: upd(6, done=[2]), "only his answer", "withdraw", i=6)
refused("…by its exact text too", lambda: upd(6, done=[H1]), "only his answer", i=6)
check("…the step is still open and the ask stands", his(6) == [OPEN(H1)] and mt(6)["needs"] == ["decision"] and mt(6)["ask"] == ASK, st(6))
r = upd(6, clear_ask=True, clear_options=True, needs="home-agent")
check("withdrawing the ask drops his open step, by the session that withdrew it", [s for s, _ in his(6)] == ["dropped"] and mt(6)["steps"][-1]["by"] == "home-agent" and H1 not in mt(6)["next"] and "owner_step" not in mt(6), (st(6), mt(6)))
r = server._answer("a6", "Ship", "", "")
check("…and an answer that comes after is stale: nothing ticks", r == "stale" and [s for s, _ in his(6)] == ["dropped"], (r, his(6)))

# ---- 6b. withdrawing the ask with the clear flags (clear_ask, clear_options, clear_needs) leaves no open step of his; an answered step stays done; a replaced ask drops the old step and adds the new
r = upd(26, needs="decision", ask=ASK, options=OPTS)
r = upd(26, clear_ask=True, clear_options=True, clear_needs=True)
check("clear_ask with clear_options and clear_needs drops his open step, by the session, and the record of it goes", "ask" not in mt(26) and [s for s, _ in his(26)] == ["dropped"] and mt(26)["steps"][-1]["by"] == "home-agent"
      and H1 not in mt(26).get("next", "") and "owner_step" not in mt(26) and all(s != "open" for s, _ in his(26)), (st(26), mt(26)))
r = upd(27, needs="decision", ask=ASK, options=OPTS)
r = server._answer("a27", "Ship", "", "")
r = upd(27, clear_ask=True, clear_options=True, clear_needs=True)
check("a step he answered stays done when a later update clears the ask", his(27) == [("done", f"{H1} → Ship")], (r, st(27)))
r = upd(28, needs="decision", ask=ASK, options=OPTS)
r = upd(28, ask=ASK2, options=OPTS)
check("a replaced ask drops the old open step and adds the new one", [x for x in his(28)] == [("dropped", H1), OPEN(H2)] and mt(28).get("owner_step") == H2, st(28))
r = upd(28, clear_ask=True, clear_options=True, clear_needs=True)
check("…and clearing the ask afterwards drops the new step too", [s for s, _ in his(28)] == ["dropped", "dropped"] and "owner_step" not in mt(28), (st(28), mt(28)))
r = upd(31, needs="decision", ask=ASK, options=OPTS)
p31 = T / "store/a/31.json"; j31 = json.loads(p31.read_text()); j31["metadata"].update(after=["a2"], ask_by="2030-01-01", wait_kind="item"); p31.write_text(json.dumps(j31))      # the item now waits after another open item: it is no longer his move, yet its step of his stands open
r = upd(31, clear_ask=True, clear_options=True, clear_needs=True)
check("clearing the ask drops his open step also when the item had stopped waiting on him before (a wait on another item's close)", "ask" not in mt(31) and [s for s, _ in his(31)] == ["dropped"] and "owner_step" not in mt(31), (st(31), mt(31)))
r = upd(32, needs="decision", ask=ASK, options=OPTS)
p32 = T / "store/a/32.json"; j32 = json.loads(p32.read_text()); j32["metadata"].update(after=["a2"], ask_by="2030-01-01", wait_kind="item"); p32.write_text(json.dumps(j32))
r = upd(32, description="- Goal: A thing, finished when it works\n- another fact")
check("a stale open step of his on an item that does not wait on him is dropped by any session write, ask or no", [s for s, _ in his(32)] == ["dropped"] and "owner_step" not in mt(32), (st(32), mt(32)))
r = upd(29, needs="decision", ask=ASK, options=OPTS)
r = upd(29, clear_needs=True)
check("clear_needs that removes the decision leaves no open step of his", all(s != "open" for s, _ in his(29)) and "owner_step" not in mt(29), (st(29), mt(29)))
r = upd(30, needs="decision", ask=ASK, options=OPTS)
r = upd(30, clear_ask=True, clear_options=True, clear_needs=True, next="home-agent: build it, then test it")
check("the same withdrawal in a call that also writes next drops his step and keeps the session's line", [s for s, _ in his(30)] == ["dropped"] and "home-agent: build it, then test it" in mt(30)["next"], (st(30), mt(30)))


r = upd(7, step=STEP)
check("(setup) a your-step", his(7) == [OPEN(f"Oliver: {STEP}")], st(7))
r = upd(7, step="none")
check("withdrawing a your-step (step=\"none\": the state goes) drops his open step", [s for s, _ in his(7)] == ["dropped"] and "state" not in mt(7) and "step" not in mt(7), (his(7), mt(7)))
check("…the reply says the step is withdrawn, and the mover is no longer him", "step withdrawn" in r and mt(7).get("mover") != OWNER, (r, mt(7)))
refused("step=\"none\" on an item that stores no step is refused, nothing written", lambda: upd(7, step="none"), "stores none", i=7)

r = upd(8, step=STEP)
refused("a session's done on a your-step's Oliver line is refused as well", lambda: upd(8, done=[2]), "only his answer", i=8)

r = upd(19, needs="decision", ask=ASK, options=OPTS)
r = upd(19, done=[2], clear_ask=True, clear_options=True, needs="home-agent")
check("a done on his step in the same call that withdraws the ask is no refusal: the ask goes, no step of his stays open", "ask" not in mt(19) and "decision" not in (mt(19).get("needs") or []) and all(s != "open" for s, _ in his(19)) and "owner_step" not in mt(19), (st(19), mt(19)))

# his note on a your-step ticks the server's step with his words (step-reply)
r = upd(23, step=STEP)
r = server._answer("a23", "", "the box answers, port 22 is open", "send")
check("his note on a your-step ticks the server's step with his words after the arrow, and the record of it goes", r == "stepreply" and his(23) == [("done", f'Oliver: {STEP} → "the box answers, port 22 is open"')] and "owner_step" not in mt(23) and [x["by"] for x in mt(23)["steps"] if x["text"].startswith("Oliver:")] == ["Oliver"], (r, st(23), mt(23)))
check("…the lines the session wrote stay open for it to judge", ("open", "home-agent: build it") in st(23), st(23))

r = upd(9, needs="decision", ask=ASK, options=OPTS)
r = upd(9, dropped=[2])
check("a session may drop his step (dropped is not a tick): while the ask stands the server puts a new open step back, the list and the item agree (N5)", [s for s, _ in his(9)] == ["dropped", "open"], st(9))

# ---- 7. N5: the list follows the fields on every save, closes settle
r = upd(10, needs="decision", ask=ASK, options=OPTS)
p = T / "store/a/10.json"; j = json.loads(p.read_text()); j["metadata"].pop("steps", None); j["metadata"]["next"] = "home-agent: build it"; j["metadata"].pop("next_by", None); j["metadata"].pop("owner_step", None); p.write_text(json.dumps(j))
upd(10, description="- Goal: A thing, finished when it works\n- a second fact")
check("an item that waits on him with no step of his on its list gets one on any save (N5: the fields decide)", his(10) == [OPEN(H1)], st(10))
r = _wt_complete.stackshot_complete("a10", outcome="done", reason="shipped as asked", description="- Goal: A thing, shipped", sender="home-agent")
check("a close settles his open step (N8: done with the outcome), the server adds nothing", rd(10)["status"] == "completed" and all(x["status"] != "open" for x in S.view(mt(10), closed=True, keeper=OWNER)), S.view(mt(10), closed=True, keeper=OWNER))

# ---- 8. the router and a hold's wake create and tick nothing wrongly
import datetime as _dt
# a decision item cannot be held (the model guard refuses it), so a hold is a wait of an item in an agent's hands: no step of his before or after its wake
_w = (_dt.date.today() + _dt.timedelta(days=3)).isoformat()
r = upd(11, hold=True, wake=_w, wait_basis=f"the vendor ships the part {_w}")
b = rd(11)
check("(setup) a held item in an agent's hands has no step of his", b["metadata"].get("until") and his(11) == [], st(11))
server._wake_pass(_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=10))
a = rd(11)
check("a wake pass over a held item makes no step of his and ticks none", not a["metadata"].get("hold") and his(11) == [], (his(11), told[-1:] if told else None))
check("the router and its live pass never write an item (no save, no update call in either)", not re.search(r"\b_save\(|stackshot_update\(|update_unlocked\(|update_item\(",pathlib.Path(STACK, "stackshot/router/router.py").read_text() + pathlib.Path(STACK, "stackshot/router/router_live.py").read_text()))

# ---- 10. his name once: a text written with his name at the front and one without read the same, and a line stored with it twice still matches
SPELLINGS = [f"Oliver: {STEP}", f"oliver: {STEP}", f"OLIVER: {STEP}", f"Oliver (builder): {STEP}", f"**Oliver:** {STEP}", f"- Oliver: {STEP}", f"Oliver: Oliver: {STEP}", f"Oliver:  Oliver (lead): {STEP}", STEP]
ONE = f"Oliver: {STEP}"
check("line_of: every spelling is_named accepts (any case, a role, a marker, bold marks, the name twice) and the text without the name make one and the same line", all(HS.line_of(t) == ONE for t in SPELLINGS) and all(HS.is_named(t) for t in SPELLINGS[:-1]) and not HS.is_named(STEP), [HS.line_of(t) for t in SPELLINGS])
check("line_of: another name stays in the text, and only a leading opener of his goes", HS.line_of("home-agent: build it") == "Oliver: home-agent: build it" and HS.line_of("Oliver: ask Oliver: now") == "Oliver: ask Oliver: now", (HS.line_of("home-agent: build it"), HS.line_of("Oliver: ask Oliver: now")))
check("same_line: the name once, twice, in another case or with a role is one step; another action is not", HS.same_line(f"Oliver: Oliver: {STEP}", ONE) and HS.same_line(f"oliver (lead): {STEP}", ONE) and not HS.same_line(f"Oliver: {STEP} now", ONE) and not HS.same_line(f"home-agent: {STEP}", ONE))
for n, spelling in zip((35, 36, 37, 38, 39, 72, 73), SPELLINGS[:7]):
    r = upd(n, step=spelling)
    check(f"a step= written as {spelling!r} makes the one line `{ONE}` (the stored line, its record and next hold his name once)", his(n) == [OPEN(ONE)] and mt(n).get("owner_step") == ONE and mt(n)["next"].count("Oliver:") == 1, (st(n), mt(n)))
r = upd(60, step=STEP)
check("(setup) a step= written without his name makes the same line", his(60) == [OPEN(ONE)] and mt(60).get("owner_step") == ONE, st(60))
check("…so the shown line is the same for the text with the name and without it", [t for _, t in his(35)] == [t for _, t in his(60)], (his(35), his(60)))
ASK_NAMED = "Decide: Oliver: whether to ship it now · Recommend: ship · Stakes: a day either way · By: no date"
r = upd(61, needs="decision", ask=ASK_NAMED, options=OPTS)
check("an ask whose Decide part opens with his name makes `Oliver: <the Decide part>` once, the same line as the ask without the name", his(61) == [OPEN(H1)] and mt(61).get("owner_step") == H1, (st(61), mt(61)))
r = server._answer("a61", "Ship", "", "")
check("…and his answer ticks it with the option after the arrow", r == "decision" and his(61) == [("done", f"{H1} → Ship")], his(61))

# a step stored with his name twice (before the server stopped doubling it): later saves keep it as the one step, a session's done cannot tick it by any spelling, his answer ticks it
DBL = f"Oliver: Oliver: {STEP}"
def double(n):
    p = T / f"store/a/{n}.json"; j = json.loads(p.read_text()); m = j["metadata"]
    m["next"] = m["next"].replace(ONE, DBL); m["owner_step"] = DBL
    for x in m["steps"]: x["text"] = x["text"].replace(ONE, DBL)
    p.write_text(json.dumps(j))
for n in (62, 63, 64):
    upd(n, step=STEP); double(n)
check("(setup) the stored step reads with his name twice", his(62) == [OPEN(DBL)] and mt(62)["owner_step"] == DBL and DBL in mt(62)["next"], st(62))
upd(62, description="- Goal: A thing, finished when it works\n- one more fact")
check("a save over the step stored twice adds no second step and leaves the line as stored", his(62) == [OPEN(DBL)] and len([ln for ln in mt(62)["next"].splitlines() if ln.startswith("Oliver:")]) == 1 and mt(62)["owner_step"] == DBL, (st(62), mt(62)))
for ref in (2, DBL, ONE, STEP, f"oliver: {STEP}"):
    refused(f"a session's done by {ref!r} on the step stored twice is refused (only his answer ticks it)", lambda ref=ref: upd(62, done=[ref]), "only his answer", i=62)
r = upd(62, step=f"Oliver: {STEP}, then say so")
check("a reworded step= drops the step stored twice and adds the new one with his name once", [s for s, _ in his(62)] == ["dropped", "open"] and his(62)[1][1] == f"{ONE}, then say so" and mt(62)["owner_step"] == f"{ONE}, then say so", st(62))
r = upd(63, step="none")
check("withdrawing the step stored twice drops it", [s for s, _ in his(63)] == ["dropped"] and "owner_step" not in mt(63), (st(63), mt(63)))
r = server._answer("a64", "", "", "done")
check("Done on the step stored twice ticks that step, once, and makes none beside it", r == "done" and his(64) == [("done", DBL)] and mt(64)["steps"][-1]["by"] == "Oliver", (r, st(64)))

# a session's own line of his, stored with his name twice or once: done and dropped find it by position or exact first line, with the name, without it, or written twice
for n, line in ((65, "Oliver: Oliver: review PR 12"), (66, "Oliver: Oliver: review PR 12"), (67, "Oliver: Oliver: review PR 12"), (68, "Oliver: review PR 12"), (69, "Oliver: review PR 12"), (70, "Oliver: Oliver: review PR 12"), (71, "Oliver: review PR 12")):
    upd(n, next=f"home-agent: build it\n{line}")
check("(setup) a session's line of his is stored as it wrote it, twice or once", his(65) == [OPEN("Oliver: Oliver: review PR 12")] and his(68) == [OPEN("Oliver: review PR 12")], (his(65), his(68)))
upd(65, done=["Oliver: review PR 12"])
check("done by the line with his name once finds the line stored twice", his(65) == [("done", "Oliver: Oliver: review PR 12")] and "review PR 12" not in mt(65)["next"], (st(65), mt(65)["next"]))
upd(66, done=["review PR 12"])
check("done by the line without his name finds the line stored twice", his(66) == [("done", "Oliver: Oliver: review PR 12")], st(66))
upd(67, done=["Oliver: Oliver: review PR 12"])
check("done by the line written twice finds the line stored twice", his(67) == [("done", "Oliver: Oliver: review PR 12")], st(67))
upd(70, dropped=[2])
check("dropped by position finds the line stored twice", his(70) == [("dropped", "Oliver: Oliver: review PR 12")], st(70))
upd(68, done=["Oliver: Oliver: review PR 12"])
check("done by the line written twice finds the line stored once", his(68) == [("done", "Oliver: review PR 12")], st(68))
upd(69, dropped=["review PR 12"])
check("dropped by the line without his name finds the line stored once", his(69) == [("dropped", "Oliver: review PR 12")], st(69))
upd(71, done=["oliver (lead): review PR 12"])
check("done by the line with another case and a role finds the line stored once", his(71) == [("done", "Oliver: review PR 12")], st(71))

steps_ = [{"text": "home-agent: build it", "status": "open", "by": "", "at": 0}, {"text": "Oliver: Oliver: review PR 12", "status": "open", "by": "", "at": 0}, {"text": "Oliver: review PR 13", "status": "open", "by": "", "at": 0}]
check("steps.resolve: a ref with his name, without it, written twice, or by position finds his step", all(S.resolve(steps_, [r_], "done") == [1] for r_ in ("Oliver: review PR 12", "review PR 12", "Oliver: Oliver: review PR 12", 2, "oliver: review PR 12")) and S.resolve(steps_, ["review PR 13"], "done") == [2])
try:
    S.resolve(steps_, ["build it"], "done"); check("steps.resolve: another session's step is not found by its words without its name", False)
except S.StepError:
    check("steps.resolve: another session's step is not found by its words without its name", True)
dup_ = steps_ + [{"text": "Oliver: review PR 12", "status": "open", "by": "", "at": 0}]
try:
    S.resolve(dup_, ["review PR 12"], "done"); check("steps.resolve: a ref that fits two of his steps is refused and asks for the position", False)
except S.StepError as e_:
    check("steps.resolve: a ref that fits two of his steps is refused and asks for the position", "matches steps 2, 4" in str(e_), str(e_))
check("steps.resolve: the exact text wins over the looser reading", S.resolve(dup_, ["Oliver: review PR 12"], "done") == [3], S.resolve(dup_, ["Oliver: review PR 12"], "done"))

# how it is shown: a line stored twice reads with his name once on the item page's lists
check("the Next list's lines and the Your step block show his name once for a line stored twice", IP.next_lines("Oliver: Oliver: review PR 12", "home-agent")[0].text == "Oliver: review PR 12" and IP.next_lines("Oliver: review PR 12", "home-agent")[0].text == "Oliver: review PR 12"
      and S.strip_owner("Oliver: Oliver: review PR 12") == "review PR 12" and S.strip_owner("Oliver: review PR 12") == "review PR 12", IP.next_lines("Oliver: Oliver: review PR 12", "home-agent")[0].text)

# the fill-in of his past decisions finds a done step stored with his name twice
bf_meta = {"answers": [{"kind": "decision", "ts": 1000.0, "choice": "Ship", "text": "", "ask": ASK}],
           "steps": [{"text": f"Oliver: Oliver: {D1} → Ship", "status": "done", "by": "Oliver", "at": 9000.0}]}
add_, have_ = NB.audit(bf_meta, "open", OWNER)
bf_meta["steps"][0]["text"] = f"{H1} → Ship"
add2_, have2_ = NB.audit(bf_meta, "open", OWNER)
check("next_backfill finds a done step of his stored with his name twice or once, and adds none", add_ == [] and add2_ == [] and len(have_) == 1 and len(have2_) == 1 and have_[0]["why"].startswith("ticked by"), (add_, have_, add2_, have2_))

# ---- 9. the pure helpers
check("decide_of: the Decide part; a leading `Decide:` stripped; a watcher's ask cut at its first ` · `; plain words kept",
      HS.decide_of(ASK) == D1 and HS.decide_of("Decide:   x   · Recommend: y") == "x" and HS.decide_of("is it there yet? · wake Fri") == "is it there yet?" and HS.decide_of("") == "", HS.decide_of(ASK))
check("with_answer puts the arrow after the first line only, answer_words prefers the label", HS.with_answer("Oliver: a\n  more", "Ship") == "Oliver: a → Ship\n  more" and HS.answer_words("Ship", "x") == "Ship" and HS.answer_words("", "") == "")

print(("ok" if not fails else "FAILED") + f": owner_steps scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
