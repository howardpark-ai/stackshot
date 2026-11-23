"""Scenario test for who a front agent hears from: the mark on a message to one means "the person must see this", and nothing else starts a turn there
- fixture data, no live store, no network, no server.

Covers (messaging._gate_front / answer_route / asked_by / router_answer, router_live._must_see / _front_route / _act, held.py the store):
  1. The message tool, to a front agent: a marked message that needs the person is delivered; a message that is no answer to the agent's question is refused naming the project's background agent
     (a project with none: held for the next turn, no turn); a done, taken or no-action note is refused in one line, marked or not; the person's own unmarked message is refused without the mark.
  2. An answer to a question the front agent itself wrote to the sender: delivered unmarked while the person's last message to that agent is 30 minutes old or less, and at 31 minutes written onto
     the item it names, else held through the front gate. The signal for "was written to" is the message log (one row per message through the tool, `from` the agent, `to` the sender, within a day).
     A background agent's hand-back (a done, taken or no-action note, a plain status report) is never an answer: it is written onto the item it names, else refused, whatever the front agent asked it before.
  3. fyi=true and a message to a project page or a background agent are as before.
  4. The router: a pass to a front agent with no need of the person (no ruling for him, no words of his, no hand-back, no mark or needs: decision in the text, no named item waiting on a decision) goes to the
     project's background agent, unmarked, text intact, the routing log naming the new target; a project with none holds it through the front gate, unmarked, starting no turn; with each need signal it stays
     marked as before; an answer in the conversation reaches the agent unmarked, outside it is written onto the item or held; the fallback pass, an audit finding, an fyi and a page-owed notice are as before.
  5. A staged message of each kind under a temp store: nothing starts a turn at the held ones, the held store hands each over at the next turn once, two passes from one sender are two lines (the store folds
     only a repeated notice id), a full store keeps the newest, and an agent whose hook cannot fetch held lines is not given the pass: marked for the router, refused for the tool.

    tests/run-suite front_hold   -> exit 0 / 1"""
import asyncio, datetime, importlib, inspect, json, logging, os, pathlib, re, sys, threading, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="held-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                 (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'), (r'(?m)^owner = "the owner"', 'owner = "Oliver"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', 'allowed_emails = ["oliver@example.org"]'), (r'(?m)^ui_open = true', 'ui_open = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/demo-one", "state/site", "secrets", "touch", "repo", "brain/projects"): (T / d).mkdir(parents=True)
S, A, X, B, D = ("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333",
                 "44444444-4444-4444-8444-444444444444", "66666666-6666-4666-8666-666666666666")
E = "77777777-7777-4777-8777-777777777777"
C, M, DA, DB = ("88888888-8888-4888-8888-888888888888", "99999999-9999-4999-8999-999999999999", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for u, n in
                                                      ((S, "work-osprey"), (A, "work-osprey-main"), (X, "work-osprey-x"), (B, "home-beta"), (D, "work-osprey-docs"), (E, "solo-main"),
                                                                                       (C, "comp-main"), (M, "duo-main"), (DA, "duo-a"), (DB, "duo-b"))}))
AGENTS = {"work-osprey-main": "Oliver's point of contact", "work-osprey-x": "builds, merges and releases the code", "work-osprey-docs": "keeps the pages"}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {
    "title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "work-osprey", "status": "active", "board": [], "board_row": False,
    "updated": 1, "mirror": "https://example.invalid/alpha", "agents": AGENTS, "back_agents": {"work-osprey-x": AGENTS["work-osprey-x"], "work-osprey-docs": AGENTS["work-osprey-docs"]}},
    "projects/solo": {"title": "Solo", "name": "Solo", "org": "home", "tags": [], "type": "project", "session": "solo", "status": "active", "board": [], "board_row": False,
    "updated": 1, "mirror": "https://example.invalid/solo", "agents": {"solo-main": "Oliver's point of contact"}, "back_agents": {}},      # a front-only project: no background agent
    "projects/comp": {"title": "Comp", "name": "Comp", "org": "home", "tags": [], "type": "project", "session": "comp", "status": "active", "board": [], "board_row": False, "hub": "projects/alpha",
    "updated": 1, "mirror": "https://example.invalid/comp", "agents": {"comp-main": "Oliver's point of contact"}, "back_agents": {}},      # a component page of alpha with no background agent of its own
    "projects/duo": {"title": "Duo", "name": "Duo", "org": "home", "tags": [], "type": "project", "session": "duo", "status": "active", "board": [], "board_row": False,
    "updated": 1, "mirror": "https://example.invalid/duo", "agents": {"duo-main": "Oliver's point of contact", "duo-b": "tidies the notes", "duo-a": "tidies the pages"}, "back_agents": {"duo-b": "tidies the notes", "duo-a": "tidies the pages"}}}}))      # two background agents, neither builds or merges: duo-b is listed first
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n# Alpha\n\n## Current state\n\nALPHA-STATE.\n\n<!-- timeline -->\n- 2026-10-01 | old\n")
DESC = "- A thing\n- It lives here\n- Finished when it works"
now0 = time.time()
def item(i, owner=X, status="open", desc=DESC, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": desc, "status": status,
                                                       "updated": now0 - 3600, "state_updated": now0 - 3600, "confirmed": now0 - 3600,
                                                       "metadata": {"owner": owner, **({} if {"needs", "mover", "then", "hold", "after"} & set(meta) else {"mover": owner}), "project": "projects/alpha", "next": "the next step", **meta}}))      # the creator moves nothing; a fixture item that names no mover is moved by its former creator
item(1); item(2, desc=DESC + '\n- Oliver: "ship it"'); item(3); item(4, mover="work-osprey-x"); item(5, needs=["work-osprey-x"]); item(6, observers=[X], owner=A)
item(7, owner=A); item(8, after=["a9"]); item(9)
item(10, owner=A); item(11)
item(12, owner=A, after=["a9"]); item(13, owner=A); item(14, owner=A, needs=["decision"]); item(15, owner=A, status="completed")
(T / "store/next-id").write_text("100")
push_log = T / "push.log"
(T / "fakepush.py").write_text(f"import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nopen({str(push_log)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered → ' + a[0])\n")
def pushes(): return [json.loads(l) for l in push_log.read_text().splitlines()] if push_log.exists() else []
def settle(until=30):
    end = time.time() + until
    while time.time() < end and any(t is not threading.main_thread() and t.is_alive() for t in threading.enumerate()):
        time.sleep(0.02)
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

from stackshot.core import config as _cfg; from stackshot.router import routing; from stackshot.waits import held; from stackshot.fleet import client
from stackshot.router import router as _router; from stackshot.router import router_live as _live
from stackshot.web import server
from stackshot.web.routes import client_api as _rt_client
from stackshot.service import messaging as _messaging
from stackshot.service import store as _service_store
from stackshot.fleet import clients as _clients
from fastmcp.exceptions import ToolError
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import wakes as wakes_svc
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.tools import message as _wt_message
from stackshot.service import telling
from stackshot.service import handoff as handoff_svc
handoff_svc.CLI_SESSIONS = T / "cli"; (T / "cli").mkdir()
def pane(who, uuid):
    """The CLI's own registry row of a pane on this box (the front agent's), and the prompt hook's stamp of the person's last message to it: `stamp(uuid, minutes_ago)`."""
    (T / f"cli/{os.getpid()}-{who}.json").write_text(json.dumps({"pid": os.getpid(), "kind": "interactive", "sessionId": uuid, "name": who, "status": "idle", "startedAt": int((time.time() - 7200) * 1000),
                                                                  "statusUpdatedAt": int(time.time() * 1000), "updatedAt": int(time.time() * 1000)}))
def stamp(uuid, minutes_ago):
    p = T / "state/prompts" / uuid; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(f"{time.time() - minutes_ago * 60:.0f}\n")
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None; telling.PUSH = [sys.executable, str(T / "fakepush.py")]
_real_refuse = _web_page_debts._refuse_if_owing; _web_page_debts._refuse_if_owing = lambda debtor: None
_cfg.CFG["router"] = {"command": [sys.executable, "-c", "pass"], "timeout_seconds": 20, "live": True}
KEY = "projects/alpha"
MACH = "home-test"
def gate_open():
    """The rollout gate: the builder's and the page keeper's hooks have fetched held lines (held.mark_client), and the machine holds their sessions."""
    held.mark_client(X, "work-osprey-x"); held.mark_client(D, "work-osprey-docs"); held.mark_client(A, "work-osprey-main"); held.mark_client(E, "solo-main"); held.mark_client(C, "comp-main"); held.mark_client(M, "duo-main")
for u_, n_ in ((X, "work-osprey-x"), (A, "work-osprey-main"), (D, "work-osprey-docs"), (B, "home-beta"), (E, "solo-main"), (C, "comp-main"), (M, "duo-main"), (DA, "duo-a"), (DB, "duo-b")): _clients.register(MACH, {"uuid": u_, "name": n_})
gate_open()
def ids(session): return {X: ("work-osprey-x", X), A: ("work-osprey-main", A), D: ("work-osprey-docs", D), E: ("solo-main", E), B: ("home-beta", B), C: ("comp-main", C), M: ("duo-main", M), DA: ("duo-a", DA), DB: ("duo-b", DB)}[session]
def reach(session, since): return [x for x in pushes()[since:] if x[0] in ids(session)]
def hold_lines(): return [n for n in routing.read(KEY) if n.get("ruling") == "held" and str(n.get("reason", "")).startswith("held: asks nothing")]
def gone(*refs): return held.take(*refs)
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def why(fn):
    try: fn(); return ""
    except ToolError as e: return str(e)
def fresh():
    """Empty the held store and the push log between scenarios."""
    for p in held.dir_().glob("*.jsonl"): p.unlink()
    push_log.unlink(missing_ok=True)

def rec(text, hold="", kind="board", who="home-beta", **kw):
    nid = routing.record(KEY, kind=kind, to="", label="message to projects/alpha", who=who, text=text, target="for home-beta", pilot=True, live=True, hold=hold, **kw)
    _live.stash(nid, text)
    return next(n for n in routing.read(KEY) if n["id"] == nid)
cx = _router.Context()
def act(n, target, **ln):
    line = {"id": n["id"], "ruling": "passed", "target": target, "reason": "the page update is owed", "for_owner": False, "source": "code", "rule": "test", "item": "", **ln}
    return _live._act(n, KEY, KEY, line, cx, {})
def msg(*a, **k):
    try: return _messaging._message(*a, **k)
    except ToolError as e: return str(e)

def mlog(): return [json.loads(l) for l in _messaging.MSG_LOG.read_text().splitlines()] if _messaging.MSG_LOG.exists() else []
def mark(): return _messaging._FOR_OWNER


def log_row(frm, to, ago_min=1.0, text="a question?", outcome="delivered"):
    """A row of the message log: `frm` wrote to `to` `ago_min` minutes ago (the signal that a later message from `to` answers it)."""
    _messaging.MSG_LOG.parent.mkdir(parents=True, exist_ok=True)
    t = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=ago_min)).isoformat(timespec="seconds")
    with open(_messaging.MSG_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": t, "from": frm, "auth": "", "to": to, "outcome": outcome, "error": "", "text": text}, ensure_ascii=False) + "\n")
def no_log(): _messaging.MSG_LOG.unlink(missing_ok=True)
def unstamp(uuid): (T / "state/prompts" / uuid).unlink(missing_ok=True)
def act2(n, target, key=KEY, **ln):
    line = {"id": n["id"], "ruling": "passed", "target": target, "reason": "it fits", "for_owner": False, "source": "code", "rule": "test", "item": "", **ln}
    return _live._act(n, key, key, line, _router.Context(), {})
def recp(text, key=KEY, **kw):
    nid = routing.record(key, kind=kw.pop("kind", "board"), to="", label="message to " + key, who=kw.pop("who", "home-beta"), text=text, target="for home-beta", pilot=True, live=True, **kw)
    _live.stash(nid, text)
    return next(n for n in routing.read(key) if n["id"] == nid)
def pushed(text): return [x for x in pushes() if text in x[1]]
pane("work-osprey-main", A); pane("solo-main", E); pane("comp-main", C); pane("duo-main", M)
FRONT, BACK, SOLO = "work-osprey-main", "work-osprey-x", "solo-main"

# ---- 1. the message tool, to a front agent
fresh(); no_log(); unstamp(A); n0 = len(pushes())
out = msg(FRONT, "can you look at the export page when you have a minute?", "home-beta"); settle()
check("1a: a peer's message that is no answer is refused and names the project's background agent as the address", out.startswith("Refused") and "message(to='work-osprey-x'" in out and reach(A, n0) == [] and held.count(A) == 0, out)
fresh(); out = msg(FRONT, "the PR is merged, the suites pass.", BACK); settle()
check("1b: a done note from a session is refused in one line (write it on the board item or say nothing), nothing sent or held", out.startswith("Refused") and "takes no done, taken or no-action note" in out and "board item" in out and "\n" not in out and reach(A, n0) == [] and held.count(A) == 0, out)
out = msg(FRONT, mark() + "\nFYI the build is done, no action needed.", BACK); settle()
check("1c: …and so is a marked note that says nothing is needed from the person", out.startswith("Refused") and "marks only what Oliver has to do" in out and "board item" in out and held.count(A) == 0 and reach(A, n0) == [], out)
fresh(); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, mark() + "\nDecide whether the export ships on Friday.", "home-beta"); settle(); unstamp(A)      # a marked message starts a turn only while he is talking with the agent (or asked it about the item): he is, here
check("1d: a marked message that needs the person is delivered, as before", out.startswith("delivered") and len(reach(A, n0)) == 1 and reach(A, n0)[0][1].count(mark()) >= 1 and held.count(A) == 0, (out, pushes()[n0:]))
fresh(); n0 = len(pushes()); out = msg(FRONT, "go on with the export", "Oliver"); settle()
check("1e: the person's own unmarked message is refused without the mark, as before", out.startswith("Refused") and "first line" in out and reach(A, n0) == [] and held.count(A) == 0, out)
out = msg(FRONT, "it now needs: decision", BACK); settle()
check("1f: an unmarked message that says needs: decision is refused, the mark goes on its first line", out.startswith("Refused") and "first line" in out and held.count(A) == 0, out)
fresh(); n0 = len(pushes()); out = msg(SOLO, "can you look at the export page when you have a minute?", "home-beta"); settle()
row_ = [x for x in mlog() if x.get("to") == SOLO and "export page" in x.get("text", "")]
check("1g: a project with no background agent holds the peer's message through the front gate: no turn, the held store has its words, unmarked", out.startswith("held for solo-main's next turn") and reach(E, n0) == [] and held.count(E) == 1
      and "can you look at the export page" in held.take(E, SOLO) and len(row_) == 1 and row_[0]["outcome"] == "held for its next turn (front agent)", (out, row_))
fresh(); out = msg(SOLO, "the PR is merged, the suites pass.", BACK); settle()
check("1h: …a done note to it is refused all the same (no message, no held line)", out.startswith("Refused") and "takes no done" in out and held.count(E) == 0, out)
fresh(); n0 = len(pushes()); out = msg(FRONT, "can you look at the export page?", "home-beta", origin=MACH); settle()
check("1i: a script's unmarked message to a front agent with a background agent is refused naming it", out.startswith("Refused") and "work-osprey-x" in out and reach(A, n0) == [] and held.count(A) == 0, out)
_cfg.CFG["router"]["hold_notices"] = False
fresh(); out = msg(SOLO, "can you look at the export page?", "home-beta"); settle()
check("1j: with the hold switch off nothing can hold it: refused, nothing held or pushed", out.startswith("Refused") and held.count(E) == 0, out)
_cfg.CFG["router"].pop("hold_notices")

# ---- 2. an answer to the front agent's own question
no_log(); fresh(); log_row(FRONT, BACK, 5); stamp(A, 10); n0 = len(pushes())
out = msg(FRONT, "yes, the export is ready for review", BACK); settle()
check("2a: an answer to a question the agent wrote, while the person's last message to it is 10 minutes old: delivered to the agent, unmarked", out.startswith("delivered") and len(reach(A, n0)) == 1 and mark() not in reach(A, n0)[0][1] and held.count(A) == 0, (out, pushes()[n0:]))
stamp(A, 29); n0 = len(pushes()); out = msg(FRONT, "and the docs are ready as well", BACK); settle()
check("2b: …at 29 minutes it still is", out.startswith("delivered") and len(reach(A, n0)) == 1 and mark() not in reach(A, n0)[0][1], (out, pushes()[n0:]))
stamp(A, 31); n0 = len(pushes()); h0 = held.count(A); out = msg(FRONT, "and the slides are ready as well", BACK); settle()
check("2c: …the same answer at 31 minutes is not delivered: held through the front gate for the agent's next turn (it names no item), unmarked", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [] and held.count(A) == h0 + 1, (out, pushes()[n0:]))
fresh(); n0 = len(pushes()); out = msg(FRONT, "a1: the slides are ready as well", BACK); settle()
rows_ = [x for x in mlog() if "written onto" in str(x.get("outcome")) and "slides" in x.get("text", "")]
check("2d: at 31 minutes an answer that names an open item is written onto the item, not delivered or held", out.startswith("Not delivered: written onto") and reach(A, n0) == [] and held.count(A) == 0 and len(rows_) == 1, (out, rows_))
fresh(); n0 = len(pushes()); out = msg(FRONT, "a14: the slides are ready as well", BACK); settle()
check("2e: …an item that waits on the person's decision is not written onto: the answer is held", out.startswith("held for work-osprey-main's next turn") and held.count(A) == 1 and reach(A, n0) == [], out)
fresh(); unstamp(A); n0 = len(pushes()); out = msg(FRONT, "the export is ready as well", BACK); settle()
check("2f: with no stamp of his message at all the person is not in the conversation: held", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [] and held.count(A) == 1, out)
fresh(); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, "can you also review the docs page?", "work-osprey-docs"); settle()
check("2g: a sender the agent never wrote to is no answer, whatever the conversation: refused naming the background agent", out.startswith("Refused") and "message(to='work-osprey-x'" in out and reach(A, n0) == [], out)
no_log(); log_row(FRONT, "work-osprey-docs", 25 * 60); n0 = len(pushes()); out = msg(FRONT, "the docs page looks fine to me", "work-osprey-docs"); settle()
check("2h: …a question put to the sender more than a day ago is no signal either", out.startswith("Refused") and reach(A, n0) == [], out)
no_log(); log_row("work-osprey-docs", "home-beta", 5); n0 = len(pushes()); out = msg(FRONT, "the docs page reads fine", "home-beta"); settle()
check("2i: a question put by another agent of the front agent's project is not the front agent's own: no answer, whatever the conversation: refused naming the background agent", out.startswith("Refused") and "message(to='work-osprey-x'" in out and reach(A, n0) == [] and held.count(A) == 0, (out, pushes()[n0:]))
fresh(); no_log(); log_row("work-osprey-docs", BACK, 300); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, "the docs page reads fine", BACK); settle()
check("2i2: …the background agent's unmarked note after another project agent's question to it is not delivered while the person is present: held for the next turn", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [] and held.count(A) == 1, (out, pushes()[n0:]))
stamp(A, 31); fresh(); n0 = len(pushes()); out = msg(FRONT, "a1: the docs page reads fine", BACK); settle()
check("2i3: …and with the person away it is held too, not written onto the item it names (it answers no question of the front agent)", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [] and held.count(A) == 1, out)
no_log(); fresh(); log_row(FRONT, BACK, 23 * 60 + 50); log_row("work-osprey-docs", BACK, 5); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, "yes, the export is ready for review", BACK); settle()
check("2i4: the front agent's own question inside the lookback still counts when another agent asked later: delivered unmarked in the conversation", out.startswith("delivered") and len(reach(A, n0)) == 1 and mark() not in reach(A, n0)[0][1], (out, pushes()[n0:]))
no_log(); fresh(); log_row(FRONT, BACK, 24 * 60 + 10); log_row("work-osprey-docs", BACK, 5); n0 = len(pushes()); out = msg(FRONT, "yes, the export is ready for review", BACK); settle()
check("2i5: …and one put just past the lookback does not, the other agent's later question making no difference: held", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [], (out, pushes()[n0:]))
no_log(); log_row("home-beta", "work-osprey-docs", 5); n0 = len(pushes()); out = msg(FRONT, "the docs page reads fine", "work-osprey-docs"); settle()
check("2j: a question put by an agent of another project does not count", out.startswith("Refused") and reach(A, n0) == [], out)
for name, kw in (("a handover from an agent of the project that asks nothing", {"text": "please take the export task and tell me when it is done"}), ("a question whose delivery failed", {"outcome": "failed: no such session"})):
    no_log(); fresh(); log_row(FRONT, "work-osprey-docs", 5, **kw); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, "the docs page reads fine", "work-osprey-docs"); settle()
    check(f"2l: {name} is no question, so the reply is no answer: refused naming the background agent, no turn", out.startswith("Refused") and "message(to='work-osprey-x'" in out and reach(A, n0) == [] and held.count(A) == 0, (out, pushes()[n0:]))
for name, kw in (("with no question mark in its text", {"text": "the export is on your list"}), ("whose delivery failed", {"outcome": "failed: no such session"})):
    no_log(); fresh(); log_row(FRONT, BACK, 5, **kw); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, "the docs page reads fine", BACK); settle()
    check(f"2l2: the front agent's own message {name} is no question: the background agent's later note is held, not delivered", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [], (out, pushes()[n0:]))
no_log(); fresh(); log_row("work-osprey-x", "work-osprey-docs", 5, text="please take the export task and tell me when it is done"); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, "the docs page reads fine", "work-osprey-docs"); settle()
check("2m: a message from the project's builder that asks nothing makes the sender's later note no answer (the staged test of a plain note to the front agent)", out.startswith("Refused") and reach(A, n0) == [], (out, pushes()[n0:]))
no_log(); log_row(FRONT, BACK, 5); n0 = len(pushes()); out = msg(FRONT, mark() + "\nDecide whether the export ships on Friday.", BACK); settle()
check("2k: an answer that needs the person is marked and delivered whatever the conversation", out.startswith("delivered") and len(reach(A, n0)) == 1 and mark() in reach(A, n0)[0][1], (out, pushes()[n0:]))

# a background agent's hand-back is tested BEFORE the answer rule: a question the front agent put to it makes a hand-back no answer
def asked_present(minutes_ago=5):
    no_log(); fresh(); log_row(FRONT, BACK, 5); stamp(A, minutes_ago)      # the agent asked the builder a question and the person is in that conversation: the old order delivered any note the builder sent now
for name, text in (("a bare taken", "Taken."), ("a done note with a sha", "Done (010cc0d)."), ("a status that names no item", "the PR is merged, the suites pass."), ("a stopped thing", "the watch is stopped and the item is complete.")):
    asked_present(); n0 = len(pushes()); out = msg(FRONT, text, BACK); settle()
    check(f"2n: a builder's hand-back ({name}) that names no item is refused, not delivered as an answer, while the person is in the conversation", out.startswith("Refused") and "takes no done, taken or no-action note" in out and reach(A, n0) == [] and held.count(A) == 0, (out, pushes()[n0:]))
asked_present(); n0 = len(pushes()); out = msg(FRONT, "a1: Done (010cc0d), the unit is live.", BACK); settle()
rows_ = [x for x in mlog() if "written onto a1" in str(x.get("outcome"))]
check("2n2: …a hand-back that names an open item is written onto it (History line), not delivered, not held, while he is in the conversation", out.startswith("Not delivered: written onto a1") and reach(A, n0) == [] and held.count(A) == 0 and len(rows_) == 1, (out, rows_))
asked_present(); out = msg(FRONT, "a1: taken.", BACK); settle()
check("2n3: …'taken' with an item is written onto it too", out.startswith("Not delivered: written onto a1"), out)
asked_present(); n0 = len(pushes()); out = msg(FRONT, "a14: the unit is live.", BACK); settle()
check("2n4: …a hand-back on an item that waits on his decision is refused, never delivered as an answer", out.startswith("Refused") and reach(A, n0) == [] and held.count(A) == 0, (out, pushes()[n0:]))
asked_present(); n0 = len(pushes()); out = msg(FRONT, "a1: for the record, the docs page reads fine", BACK); settle()
check("2n5: …a fixed no-action phrase is a note too: written onto the item", out.startswith("Not delivered: written onto a1") and reach(A, n0) == [], (out, pushes()[n0:]))
for name, text in (("a status with a wait in it", "yes, a1 is merged; the docs page awaits review"), ("a status with a question", "a1 is merged, is the docs page next?"), ("a status with a plan", "a1 is merged and I will deploy it later"),
                   ("a plain answer", "yes, the export is ready for review"), ("a short answer that is no status shape", "no, the docs page is the other way round")):
    asked_present(); n0 = len(pushes()); out = msg(FRONT, text, BACK); settle()
    check(f"2n6: an answer that is no report ({name}) is still delivered to the agent, unmarked, while he is in the conversation", out.startswith("delivered") and len(reach(A, n0)) == 1 and mark() not in reach(A, n0)[0][1], (out, pushes()[n0:]))
asked_present(31); n0 = len(pushes()); out = msg(FRONT, "a1: is the docs page next? it awaits review", BACK); settle()
check("2n7: …and at 31 minutes one that is no report and names an item is written onto it as an answer, as before", out.startswith("Not delivered: written onto a1") and reach(A, n0) == [], (out, pushes()[n0:]))
no_log(); fresh(); log_row(FRONT, "home-beta", 5); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, "the PR is merged", "home-beta"); settle()
check("2n8: the report test is for a background agent's hand-back: a session that is no background agent keeps the old order, its answer delivered", out.startswith("delivered") and len(reach(A, n0)) == 1, (out, pushes()[n0:]))
asked_present(); n0 = len(pushes()); out = msg(FRONT, mark() + "\na1: Done (010cc0d), the unit is live and taken.", BACK); settle()
check("2n9: a marked hand-back of the same shape is written onto the item, not delivered, whatever the conversation", out.startswith("Not delivered: written onto a1") and reach(A, n0) == [] and held.count(A) == 0, (out, pushes()[n0:]))

# a fixed no-action phrase skips only the status shape: a question, an ask or trouble beside it makes the text no note, so it is an answer when the agent asked
for name, text in (("a question and an ask", "a1: FYI, should I deploy the unit now? I need your go."), ("a word of trouble", "a1: no action needed, but the deploy failed on the runner"),
                   ("an ask", "a1: for the record, please look at the docs page before it ships")):
    asked_present(); n0 = len(pushes()); out = msg(FRONT, text, BACK); settle()
    check(f"2o: a no-action phrase with {name} is no note: not written onto the item, delivered to the agent as an answer", out.startswith("delivered") and len(reach(A, n0)) == 1 and held.count(A) == 0, (out, pushes()[n0:]))
# 'taken' and 'stopped' are trouble outside their one form, and a bare answer is no report: all of these reach the agent that asked
for text in ("a1: no, it is not finished", "a1: the runner stopped", "a1: the port is taken", "a1: the permission is not removed yet", "yes, finished", "no, merged"):
    asked_present(); n0 = len(pushes()); out = msg(FRONT, text, BACK); settle()
    check(f"2p: {text!r} is not a hand-back: delivered to the agent that asked, not refused, not written onto the item", out.startswith("delivered") and len(reach(A, n0)) == 1 and held.count(A) == 0, (out, pushes()[n0:]))
asked_present(); n0 = len(pushes()); out = msg(FRONT, "a1: the watch is stopped and the item is complete.", BACK); settle()
check("2p2: …while the passive 'is stopped' with 'complete' is still a hand-back, written onto the item", out.startswith("Not delivered: written onto a1") and reach(A, n0) == [], (out, pushes()[n0:]))
# the hand-back order is for a background agent only: a peer front agent (a front role of its own) keeps the old order, its answer delivered and no hand-back test applied
for text in ("the PR is merged, the suites pass.", "Taken.", "a1: Done (010cc0d), the unit is live."):
    no_log(); fresh(); log_row(FRONT, SOLO, 5); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, text, SOLO); settle()
    check(f"2q: a peer front agent's {text!r} after a question of the agent is its answer, delivered (the old order), not refused or written onto an item", out.startswith("delivered") and len(reach(A, n0)) == 1 and held.count(A) == 0, (out, pushes()[n0:]))

# ---- 3. unchanged paths
no_log(); fresh(); n0 = len(pushes()); out = msg(FRONT, "the build is done", BACK, fyi=True); settle()
check("3a: an fyi to a front agent is held as before, with the fyi wording", out.startswith("held for work-osprey-main's next turn (fyi: it asks nothing") and reach(A, n0) == [] and held.count(A) == 1, out)
fresh(); n0 = len(pushes()); out = msg("projects/alpha", "the release is live", "home-beta"); settle()
check("3b: a message to a project page goes to the router as before, nothing to any pane", out.startswith("held for the router") and reach(A, n0) == [] and held.count(A) == 0, (out, pushes()[n0:]))
fresh(); n0 = len(pushes()); out = msg(BACK, "the PR is merged", "home-beta"); settle()
check("3c: a message to a background agent is delivered as before", out.startswith("delivered") and len(reach(X, n0)) == 1, (out, pushes()[n0:]))

# ---- 4. the router
fresh(); no_log(); unstamp(A); n0 = len(pushes()); n = recp("the release is live"); res = act2(n, FRONT)
rr = [x for x in routing.read(KEY) if x["id"] == n["id"] and x.get("ruling") == "passed"]
check("4a: a pass to a front agent with no need of the person goes to the project's background agent, unmarked, its text intact; the router log names the new target",
      res["status"] == "ruled" and res["ruling"] == "passed" and res["target"] == BACK and res["marked"] is False and len(reach(X, n0)) == 1 and "the release is live" in reach(X, n0)[0][1]
      and not reach(X, n0)[0][1].startswith(mark()) and reach(A, n0) == [] and held.count(A) == 0 and rr and BACK in str(rr[-1].get("ruled_to", "")) and "background agent" in res["reason"], rr)
for name, text, kw, mut in (("a ruling for the person", "the release is live", {"for_owner": True}, {}), ("his mark in the text", "the release is live - " + mark() + " pick a or b", {}, {}),
                            ("needs: decision in the text", "the release is live; it now needs: decision", {}, {}), ("his words on the notice", "the release is live", {}, {"words": "ship it"}),
                            ("a hand-back", "the release is live", {}, {"handback": True}), ("a named item that waits on his decision (in the text)", "the release is live, see a14", {}, {}),
                            ("a named item that waits on his decision (the ruling's item)", "the release is live", {"item": "a14"}, {}),
                            ("a fallback pass", "the release is live - " + mark() + " pick a or b", {"source": "fallback"}, {})):
    fresh(); stamp(A, 5)      # each needs him, so it starts a turn only while he is talking with the front agent (no exemption for a hand-back or a fallback: they are gated like the rest)
    n0 = len(pushes()); n = {**recp(text), **mut}; res = act2(n, FRONT, **kw); unstamp(A)
    check(f"4b: a pass with a need ({name}) stays marked and goes to the front agent while he is talking with it", res["ruling"] == "passed" and res["target"] == FRONT and res["marked"] is True and len(reach(A, n0)) == 1
          and reach(A, n0)[0][1].startswith(mark()) and reach(X, n0) == [] and held.count(A) == 0, (res, pushes()[n0:]))
    fresh(); n0 = len(pushes()); n = {**recp(text), **mut}; res = act2(n, FRONT, **kw)
    check(f"4b2: …and without him there it is not delivered to the front agent and not held for its next turn ({name})", reach(A, n0) == [] and held.count(A) == 0 and res["ruling"] in ("archived", "passed", "held") and res.get("held_for") != FRONT
          and (res["ruling"] == "archived" or res.get("target") == BACK or res.get("held_for") == BACK), (res, pushes()[n0:]))
# an audit batch finding to a front mover is a task, never a need of his: it starts no turn, even while he is talking with the agent, unless he asked the agent to tell him about the item
fresh(); stamp(A, 5); n0 = len(pushes()); n = recp("the release is live"); res = act2(n, FRONT, rule="audit-owners"); unstamp(A)
check("4b3: an audit batch finding to the front agent is archived, not delivered, not held, even while he is talking with it", res["ruling"] == "archived" and reach(A, n0) == [] and held.count(A) == 0, (res, pushes()[n0:]))
fresh(); n0 = len(pushes()); n = recp("the release is live", key="projects/solo"); res = act2(n, SOLO, key="projects/solo")
check("4c: a project with no background agent has nobody to take a pass that asks nothing: archived (a row of the digest), not delivered, not held for the front agent",
      res["status"] == "ruled" and res["ruling"] == "archived" and res["marked"] is False and reach(E, n0) == [] and held.count(E) == 0
      and any(x["id"] == n["id"] and x.get("ruling") == "archived" for x in routing.read("projects/solo")), (res, pushes()[n0:]))
fresh(); n0 = len(pushes()); n = recp("the release is live", key="projects/solo", who="work-osprey-main (aaaaaaaa…)"); res = act2(n, SOLO, key="projects/solo")
check("4c2: …but a peer front agent's word to it is the channel between them: held, unmarked, text intact: no turn, ruled held in the router log",
      res["status"] == "ruled" and res["ruling"] == "held" and res["marked"] is False and reach(E, n0) == [] and held.count(E) == 1 and "the release is live" in held.take(E, SOLO)
      and any(x["id"] == n["id"] and x.get("ruling") == "held" for x in routing.read("projects/solo")), (res, pushes()[n0:]))
fresh(); stamp(E, 5); n0 = len(pushes()); n = {**recp("the release is live; it now needs: decision", key="projects/solo")}; res = act2(n, SOLO, key="projects/solo"); unstamp(E)
check("4d: …with a need it is marked and delivered there as before", res["ruling"] == "passed" and res["marked"] is True and len(reach(E, n0)) == 1 and held.count(E) == 0, res)
no_log(); fresh(); log_row(FRONT, BACK, 5); stamp(A, 5); n0 = len(pushes()); n = recp("yes, the export is ready", kind="message", who="work-osprey-x (33333333…)"); res = act2(n, FRONT)
check("4e: an answer to the front agent's question while the person is in that conversation reaches the agent, unmarked", res["ruling"] == "passed" and res["target"] == FRONT and res["marked"] is False and len(reach(A, n0)) == 1
      and not reach(A, n0)[0][1].startswith(mark()) and "the export is ready" in reach(A, n0)[0][1], (res, pushes()[n0:]))
fresh(); stamp(A, 31); n0 = len(pushes()); n = recp("yes, the export is ready, a1", kind="message", who="work-osprey-x (33333333…)"); res = act2(n, FRONT)
check("4f: …at 31 minutes an answer that names an open item is written onto it: ruled held, nothing delivered", res["ruling"] == "held" and res["marked"] is False and reach(A, n0) == [] and held.count(A) == 0
      and any("written onto" in str(x.get("outcome")) for x in mlog()), (res, mlog()[-1:]))
fresh(); n0 = len(pushes()); n = recp("yes, the export is ready", kind="message", who="work-osprey-x (33333333…)"); res = act2(n, FRONT)
check("4g: …and one that names none is held through the front gate for the agent's next turn", res["ruling"] == "held" and reach(A, n0) == [] and held.count(A) == 1 and "the export is ready" in held.take(A, FRONT), res)
fresh(); n0 = len(pushes()); n = recp("yes, the export is ready", kind="message", who="home-beta (44444444…)"); res = act2(n, FRONT)
check("4h: a message from a sender the agent never wrote to is no answer: it goes to the background agent", res["ruling"] == "passed" and res["target"] == BACK and len(reach(X, n0)) == 1 and reach(A, n0) == [], (res, pushes()[n0:]))
no_log(); fresh(); log_row("work-osprey-docs", BACK, 300); stamp(A, 5); n0 = len(pushes()); n = recp("the docs page reads fine, a1", kind="message", who="work-osprey-x (33333333…)"); res = act2(n, FRONT)
check("4h2: a question another agent of the project put to the sender is no answer for the router either: the background agent's own word is held, nothing delivered or written onto the item", res["ruling"] == "held" and reach(A, n0) == [] and held.count(A) == 1
      and not any("written onto" in str(x.get("outcome")) for x in mlog()), (res, pushes()[n0:]))
fresh(); n0 = len(pushes()); n = recp("the release is live"); res = act2(n, BACK)
check("4i: a pass to a background agent is unmarked and delivered, as before", res["ruling"] == "passed" and res["marked"] is False and len(reach(X, n0)) == 1 and not reach(X, n0)[0][1].startswith(mark()), res)
# a pass rerouted to the background agent whose delivery keeps failing: the log names the builder, and after MAX_TRIES it falls back to the -main agent, marked (nothing is lost)
_real_deliver = _live._HOOKS["deliver"]
_live._HOOKS["deliver"] = lambda t, x: "failed: no such session" if t == BACK else _live.deliver_via([sys.executable, str(T / "fakepush.py")], t, x)
fresh(); n0 = len(pushes()); n = recp("the release is live"); prior = {}
for tries in range(_live.MAX_TRIES):
    res = _live._act(n, KEY, KEY, {"id": n["id"], "ruling": "passed", "target": FRONT, "reason": "it fits", "for_owner": False, "source": "code", "rule": "test", "item": ""}, _router.Context(), {**prior, "tries": tries})
    check(f"4m: try {tries + 1} to a failing background agent is an error that names it, and nothing reaches the front agent", res["status"] == "error" and res["target"] == BACK and reach(A, n0) == [], res)
    prior = {"status": res["status"], "target": res["target"]}
res = _live._act(n, KEY, KEY, {"id": n["id"], "ruling": "passed", "target": FRONT, "reason": "it fits", "for_owner": False, "source": "code", "rule": "test", "item": ""}, _router.Context(), {**prior, "tries": _live.MAX_TRIES})
check("4n: …after MAX_TRIES it falls back to the -main agent, which is gated like any pass: this one needs nobody, so it is archived (a row of the digest), neither delivered nor held", res["status"] == "ruled" and res["ruling"] == "archived" and res["source"] == "fallback"
      and reach(A, n0) == [] and held.count(A) == 0, (res, pushes()[n0:]))
stamp(A, 5); n = recp("the release is live - " + mark() + " pick a or b"); n0 = len(pushes())
res = _live._act(n, KEY, KEY, {"id": n["id"], "ruling": "passed", "target": FRONT, "reason": "it fits", "for_owner": False, "source": "code", "rule": "test", "item": ""}, _router.Context(), {"status": "error", "target": BACK, "tries": _live.MAX_TRIES}); unstamp(A)
check("4n2: …and one that needs him, while he is talking with the agent, is delivered there marked, the reason naming the builder (nothing is lost)", res["status"] == "ruled" and res["target"] == FRONT and res["marked"] is True and res["source"] == "fallback"
      and len(reach(A, n0)) == 1 and reach(A, n0)[0][1].startswith(mark()) and BACK in res["reason"], (res, pushes()[n0:]))
_live._HOOKS["deliver"] = _real_deliver
fresh(); n0 = len(pushes()); n = recp("the release is live"); res = act2(n, "projects/alpha")
check("4j: a pass to a page key is delivered as before, unmarked", res["ruling"] == "passed" and res["marked"] is False and any(x[0] == "projects/alpha" for x in pushes()[n0:]), (res, pushes()[n0:]))
fresh(); n0 = len(pushes()); n = recp("the release is live", hold="fyi"); res = act2(n, FRONT)
check("4k: an fyi to a front agent keeps its own path: held for the next turn", res["ruling"] == "held" and reach(A, n0) == [] and held.count(A) == 1, res)
fresh(); held.clients_file().unlink(missing_ok=True); n0 = len(pushes()); n = recp("the release is live", key="projects/solo"); res = act2(n, SOLO, key="projects/solo")
check("4l: a front agent whose hook cannot fetch held lines is not given the pass either (it needs no one, so no turn, and nothing is held for it): archived, a row of the digest", res["ruling"] == "archived" and reach(E, n0) == [] and held.count(E) == 0, (res, pushes()[n0:]))
gate_open()
_cfg.CFG["router"]["hold_notices"] = False
fresh(); n0 = len(pushes()); n = recp("the release is live"); res = act2(n, FRONT)
check("4m: with the hold switch off nothing is held, and the gate still stands: the pass that needs nobody starts no turn: archived, not delivered", res["ruling"] == "archived" and reach(A, n0) == [] and held.count(A) == 0, (res, pushes()[n0:]))
_cfg.CFG["router"].pop("hold_notices")

# ---- 5. staged under the temp store: what each held kind does at the next turn
fresh(); n0 = len(pushes()); out = msg(SOLO, "the PR is merged, the export is next", "home-beta", origin=MACH); settle()
check("5a: a script's peer message to a front-only project's pane starts no turn and is held", out.startswith("held for solo-main's next turn") and reach(E, n0) == [] and held.count(E) == 1, (out, pushes()[n0:]))
st_, body_ = _rt_client._client_post(MACH, "held", {"uuid": E, "name": SOLO})
check("5b: the turn-start hook hands it over, with the script's label and no mark, and the line stays until the hook acknowledges", st_ == 200 and "the PR is merged" in body_.get("text", "") and "a script on home-test" in body_.get("text", "")
      and mark() not in body_.get("text", "") and held.count(E) == 1, (st_, body_))
held.ack(E, ids=body_.get("ids")); st_, body_ = _rt_client._client_post(MACH, "held", {"uuid": E, "name": SOLO})
check("5c: …after the acknowledgement the next turn gets nothing", st_ == 200 and held.count(E) == 0 and not body_.get("text"), (st_, body_))
fresh(); n1 = recp("first result", key="projects/solo", who="work-osprey-main (aaaaaaaa…)"); n2 = recp("second result", key="projects/solo", who="work-osprey-main (aaaaaaaa…)"); act2(n1, SOLO, key="projects/solo"); act2(n2, SOLO, key="projects/solo")
text_ = held.take(E, SOLO)
check("5d: two passes from one sender are two lines, oldest first, none folded into the other (the store folds only a repeated notice id)", held.count(E) == 0 and 0 <= text_.find("first result") < text_.find("second result"), text_)
fresh(); n1 = recp("same notice", key="projects/solo", who="work-osprey-main (aaaaaaaa…)"); act2(n1, SOLO, key="projects/solo"); act2(n1, SOLO, key="projects/solo")
check("5e: the same notice passed twice (a ruling that failed to write) is held once", held.count(E) == 1, held.count(E))
fresh(); k_ = held.key_of(SOLO)
for i in range(held.KEEP_MAX): held.add(k_, "fyi", f"old {i}", now=time.time() - 100 + i * 0.01)
n = recp("the newest result", key="projects/solo", who="work-osprey-main (aaaaaaaa…)"); res = act2(n, SOLO, key="projects/solo"); lines_ = " ".join(r["text"] for r in held._read(held._file(k_)))
check("5f: a full store keeps the pass and drops its oldest line (the router log and the stored notice keep it)", res["ruling"] == "held" and held.count(E) == held.KEEP_MAX and "old 0" not in lines_ and "the newest result" in lines_ and _live.stashed(n["id"]) == "the newest result", res)
fresh(); held.clients_file().unlink(missing_ok=True); n0 = len(pushes()); out = msg(SOLO, "the PR is merged, the export is next", "home-beta"); settle()
check("5g: an agent whose hook cannot fetch held lines is not given the message: the reply says not passed on, nothing held or pushed, the message log keeps the words", out.startswith("not passed on") and held.count(E) == 0 and reach(E, n0) == []
      and any("the export is next" in x.get("text", "") for x in mlog()), out)
st_, body_ = _rt_client._client_post(MACH, "message", {"to": SOLO, "text": "the PR is merged, the export is next", "sender": "home-beta"}); settle()
check("5h: …a script gets a refusal (400) in that case, since it reads the status and not the sentence", st_ == 400 and held.count(E) == 0, (st_, body_))
gate_open()

# an anchor notice the front gate archived (a project with no background agent) still releases the item that waits on its anchor: the event happened, and no turn is owed for it
PRURL = "https://github.com/example/repo/pull/77"
item(20, owner=E, hold=True, wake="2099-01-01", project="projects/solo", mover=SOLO)
_wt_anchors._anchors("projects/solo", add=[PRURL], items=["a20"], who="t")
fresh(); n0 = len(pushes()); n = recp("merged", key="projects/solo", kind="anchor", who="hub", anchor=PRURL); res = act2(n, SOLO, key="projects/solo")
check("4o: an anchor notice for a front-only project's front agent that needs nothing of him starts no turn: archived, nothing delivered or held", res["ruling"] == "archived" and reach(E, n0) == [] and held.count(E) == 0, (res, pushes()[n0:]))
check("4p: …and still releases the item that waited on its anchor", not rd(20)["metadata"].get("hold"), rd(20)["metadata"])
# the same release when the GATE archives the anchor notice (it needs him, he is not talking with the agent, and no background agent moves an item it names), not the route
PRURL2 = "https://github.com/example/repo/pull/78"
item(21, owner=X, hold=True, wake="2099-01-01", mover=X)
_wt_anchors._anchors(KEY, add=[PRURL2], items=["a21"], who="t")
fresh(); unstamp(A); n0 = len(pushes()); n = recp(f"{_live._owner_mark()} merged", kind="anchor", who="hub", anchor=PRURL2); res = act2(n, FRONT); settle()
check("4p2: a pass that needs him, with he not talking with the front agent and no item named, is archived by the gate: nothing delivered, nothing held", res["ruling"] == "archived" and reach(A, n0) == [] and held.count(A) == 0, (res, pushes()[n0:]))
check("4p3: …and the gate-made archive still releases the item that waited on its anchor (the event happened)", not rd(21)["metadata"].get("hold"), rd(21)["metadata"])

# ---- 7. the review's cases: a sender that is the destination, front peers, one choice of background agent, a cut line, a closed item, one write, the need signals
COMP, DUOM, DUOA, DUOB = "comp-main", "duo-main", "duo-a", "duo-b"
no_log(); fresh(); unstamp(A); n0 = len(pushes()); out = msg(FRONT, "can you look at the export page when you have a minute?", BACK); settle()
check("7a: the background agent's own unmarked message to the front agent is held for the front agent's next turn, never refused with its own address: no turn, text intact",
      out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [] and reach(X, n0) == [] and held.count(A) == 1 and "look at the export page" in held.take(A, FRONT), out)
fresh(); n0 = len(pushes()); n = recp("can you look at the export page?", kind="message", who="work-osprey-x (33333333…)"); res = act2(n, FRONT)
check("7b: …the router does the same with a pass from the background agent: held, not sent back to its sender, unmarked, text intact", res["ruling"] == "held" and res["marked"] is False and reach(X, n0) == [] and reach(A, n0) == []
      and held.count(A) == 1 and "look at the export page" in held.take(A, FRONT), (res, pushes()[n0:]))
fresh(); n0 = len(pushes()); out = msg(FRONT, "can you look at the export page when you have a minute?", SOLO); settle()
check("7c: a front agent's message to a front peer is held for the peer's next turn (the channel between them), not refused to the builder: no turn, text intact, and the sender's reply says so",
      out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [] and reach(X, n0) == [] and held.count(A) == 1 and "look at the export page" in held.take(A, FRONT), out)
fresh(); n0 = len(pushes()); n = recp("can you look at the export page?", kind="message", who="solo-main (77777777…)"); res = act2(n, FRONT)
check("7d: …and the router holds a pass from a front agent to a front peer the same way: unmarked, no turn, not sent to the builder", res["ruling"] == "held" and res["marked"] is False and reach(X, n0) == [] and reach(A, n0) == []
      and held.count(A) == 1 and "look at the export page" in held.take(A, FRONT), (res, pushes()[n0:]))
fresh(); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, mark() + "\nDecide whether the export ships on Friday.", SOLO); settle(); unstamp(A)
check("7e: …a front agent's marked message to a peer still needs the person and is delivered", out.startswith("delivered") and len(reach(A, n0)) == 1, out)
# one choice of background agent, for the message tool and the router alike
fresh(); n0 = len(pushes()); out = msg(COMP, "can you look at the export page?", "home-beta"); settle()
check("7f: a hub component page with no background agent of its own takes its hub's, in the message tool: refused naming the hub's builder", out.startswith("Refused") and "message(to='work-osprey-x'" in out, out)
fresh(); n0 = len(pushes()); n = recp("the release is live", key="projects/comp"); res = act2(n, COMP, key="projects/comp")
check("7g: …and in the router: the pass goes to the hub's builder, unmarked", res["ruling"] == "passed" and res["target"] == BACK and res["marked"] is False and len(reach(X, n0)) == 1 and reach(C, n0) == [], (res, pushes()[n0:]))
fresh(); n0 = len(pushes()); out = msg(DUOM, "can you look at the export page?", "home-beta"); settle()
check("7h: two background agents and no builder: the message tool names the first by one order (duo-a), not the first listed", out.startswith("Refused") and "message(to='duo-a'" in out and "duo-b" not in out, out)
fresh(); n0 = len(pushes()); n = recp("the release is live", key="projects/duo"); res = act2(n, DUOM, key="projects/duo")
check("7i: …and the router names the same one", res["ruling"] == "passed" and res["target"] == DUOA and len(reach(DA, n0)) == 1 and reach(DB, n0) == [], (res, pushes()[n0:]))
# a held pass is not cut silently
fresh(); long_ = " ".join(f"word{i}" for i in range(120)); n = recp(long_, key="projects/solo", who="work-osprey-main (aaaaaaaa…)"); res = act2(n, SOLO, key="projects/solo"); text_ = held.take(E, SOLO)
check("7j: a held router pass longer than a held line is cut with a note naming the sender and the notice, the start of the text kept", res["ruling"] == "held" and long_[:80] in text_ and n["id"] in text_ and "work-osprey-main" in text_ and "cut" in text_ and text_.count("word") < 110, (res, text_))
fresh(); n = recp("the release is live", key="projects/solo", who="work-osprey-main (aaaaaaaa…)"); act2(n, SOLO, key="projects/solo"); text_ = held.take(E, SOLO)
check("7k: …a pass that fits is held whole, with no cut note", "the release is live" in text_ and "cut" not in text_ and n["id"] not in text_, text_)
# an answer for a closed item is not written onto it
no_log(); fresh(); log_row(FRONT, BACK, 5); stamp(A, 31); n0 = len(pushes()); before_ = (T / "store/a/15.json").read_text(); out = msg(FRONT, "a15: the slides are ready as well", BACK); settle()
check("7l: an answer that names only a closed item is held for the agent, not written onto the closed item", out.startswith("held for work-osprey-main's next turn") and held.count(A) == 1 and (T / "store/a/15.json").read_text() == before_ and reach(A, n0) == [], out)
fresh(); n = recp("yes, the export is ready, a15", kind="message", who="work-osprey-x (33333333…)"); res = act2(n, FRONT)
check("7m: …the router too", res["ruling"] == "held" and held.count(A) == 1 and (T / "store/a/15.json").read_text() == before_, res)
# a ruling that failed to write once writes the answer onto its item once
no_log(); fresh(); log_row(FRONT, BACK, 5); stamp(A, 31); n = recp("yes, the zebra export is ready, a1", kind="message", who="work-osprey-x (33333333…)")
_rule = routing.rule; _calls = []
def _flaky(*a, **k):
    _calls.append(1)
    if len(_calls) == 1: raise OSError("disk full")
    return _rule(*a, **k)
routing.rule = _flaky
try:
    r1 = act2(n, FRONT); r2 = act2(n, FRONT)
finally:
    routing.rule = _rule
check("7n: a ruling that failed to write and is tried again writes the answer onto its item once", r1["status"] == "error" and r2["status"] == "ruled" and len([x for x in mlog() if "written onto" in str(x.get("outcome")) and "zebra" in x.get("text", "")]) == 1, (r1["status"], r2["status"], r2.get("error"), mlog()[-2:]))
# the need signals of the tool, in a project with no background agent (where taking the check out would hold the message, not refuse it)
fresh(); n0 = len(pushes()); out = msg(SOLO, "go on with the export", "Oliver"); settle()
check("7o: the person's own unmarked message to a front agent of a front-only project is refused for its mark, not held", out.startswith("Refused") and "first line" in out and held.count(E) == 0 and reach(E, n0) == [], out)
out = msg(SOLO, "a note first\n" + mark() + " pick a or b", "home-beta"); settle()
check("7p: the mark past the first line is refused for its place, not held", out.startswith("Refused") and "first line" in out and held.count(E) == 0, out)
out = msg(SOLO, "a note first\nit now needs: decision", "home-beta"); settle()
check("7q: needs: decision past the first line is refused for its place, not held", out.startswith("Refused") and "first line" in out and held.count(E) == 0, out)
# the item a notice names, in every form the board shows it
NUM = 14; cxx = _router.Context(); cxx.index[f"board#{NUM}"] = cxx.index["a14"]
for name, text in (("an item page link", f"the release is live, see {BOARD}/items/a14"), ("a capital letter id", "the release is live, see A14"), ("a bare number", f"the release is live, see #{NUM}"),
                   ("a board id", f"the release is live, see board#{NUM}")):
    check(f"7r: a pass naming a decision item by {name} stays marked", _live._item_waits_decision({}, {}, text, cxx) is True, text)
check("7s: …and one naming an item that waits on no decision does not", _live._item_waits_decision({}, {}, f"the release is live, see {BOARD}/items/a1 and A1 and #1", cxx) is False)

# ---- 6. the text
docs = {p: (pathlib.Path(STACK) / "docs" / p).read_text() for p in ("router.md", "handoffs.md")}
tt = (pathlib.Path(STACK) / "stackshot/web/tools/text/message.md").read_text()
check("6a: docs/router.md says the router marks a pass only for a need of the person, and what goes where otherwise", "background agent" in docs["router.md"] and "_must_see" in docs["router.md"] and "is not marked" in docs["router.md"], "")
check("6b: docs/handoffs.md says the router marks a pass to a front agent only for a real need of the person", "marked only for a real need" in docs["handoffs.md"], "")
check("6c: the message tool's text says what a front agent hears and where the rest goes", "background agent" in tt and "board item" in tt, tt[:200])

fresh()
print(f"{len(ran) - len(fails)}/{len(ran)} checks passed" + ("" if not fails else f"; FAILED: {len(fails)}"))
sys.exit(1 if fails else 0)
