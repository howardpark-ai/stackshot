"""Scenario test for who a front agent hears from: the mark on a message to one means "the person must see this", and nothing else starts a turn there
- fixture data, no live store, no network, no server.

Covers (messaging._gate_front / answer_route / asked_by / router_answer, router_live._must_see / _front_route / _act, held.py the store):
  1. The message tool, to a front agent: a marked message that names an open item of his (needs hold decision, or his step is his) is delivered while he is there; one that names none is held for the next turn and starts none (with the hold off: refused; his own message exempt; a read that fails counts as none); a message that is no answer to the agent's question is refused naming the project's background agent
     (a project with none: held for the next turn, no turn); a done, taken or no-action note is refused in one line, marked or not; the person's own unmarked message is refused without the mark.
  2. An answer to a question the front agent itself wrote to the sender: delivered unmarked while the person's last message to that agent is 30 minutes old or less, and at 31 minutes written onto
     the item it names, else held through the front gate. The signal for "was written to" is the message log (one row per message through the tool, `from` the agent, `to` the sender, within a day) and the row's `question` mark, set by question=true: a question mark in the text is no question.
     A background agent's hand-back (a done, taken or no-action note, a plain status report) is never an answer: it is written onto the item it names, else refused, whatever the front agent asked it before.
  3. fyi=true and a message to a project page or a background agent are as before.
  4. The router: a pass to a front agent with no need of the person (no ruling for him, no words of his, no hand-back, no mark or needs: decision in the text, no named item of his; for a message a session wrote the ruling's for_owner and the text's mark are no source: only a named item of his counts) goes to the
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
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/demo-one", "state/site", "secrets", "touch", "repo", "brain/projects", "transcripts/-x"): (T / d).mkdir(parents=True)
S, A, X, B, D = ("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333",
                 "44444444-4444-4444-8444-444444444444", "66666666-6666-4666-8666-666666666666")
E = "77777777-7777-4777-8777-777777777777"
C, M, DA, DB = ("88888888-8888-4888-8888-888888888888", "99999999-9999-4999-8999-999999999999", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
TM, TS, TX = ("cccccccc-cccc-4ccc-8ccc-cccccccccccc", "dddddddd-dddd-4ddd-8ddd-dddddddddddd", "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")      # trio: two front agents and a builder
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for u, n in
                                                      ((S, "work-osprey"), (A, "work-osprey-main"), (X, "work-osprey-x"), (B, "home-beta"), (D, "work-osprey-docs"), (E, "solo-main"),
                                                                                       (C, "comp-main"), (M, "duo-main"), (DA, "duo-a"), (DB, "duo-b"), (TM, "trio-main"), (TS, "trio-side"), (TX, "trio-x"))}))
AGENTS = {"work-osprey-main": "Oliver's point of contact", "work-osprey-x": "builds, merges and releases the code", "work-osprey-docs": "keeps the pages"}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {
    "title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "work-osprey", "status": "active", "board": [], "board_row": False,
    "updated": 1, "mirror": "https://example.invalid/alpha", "agents": AGENTS, "back_agents": {"work-osprey-x": AGENTS["work-osprey-x"], "work-osprey-docs": AGENTS["work-osprey-docs"]}},
    "projects/solo": {"title": "Solo", "name": "Solo", "org": "home", "tags": [], "type": "project", "session": "solo", "status": "active", "board": [], "board_row": False,
    "updated": 1, "mirror": "https://example.invalid/solo", "agents": {"solo-main": "Oliver's point of contact"}, "back_agents": {}},      # a front-only project: no background agent
    "projects/comp": {"title": "Comp", "name": "Comp", "org": "home", "tags": [], "type": "project", "session": "comp", "status": "active", "board": [], "board_row": False, "hub": "projects/alpha",
    "updated": 1, "mirror": "https://example.invalid/comp", "agents": {"comp-main": "Oliver's point of contact"}, "back_agents": {}},      # a component page of alpha with no background agent of its own
    "projects/duo": {"title": "Duo", "name": "Duo", "org": "home", "tags": [], "type": "project", "session": "duo", "status": "active", "board": [], "board_row": False,
    "updated": 1, "mirror": "https://example.invalid/duo", "agents": {"duo-main": "Oliver's point of contact", "duo-b": "tidies the notes", "duo-a": "tidies the pages"}, "back_agents": {"duo-b": "tidies the notes", "duo-a": "tidies the pages"}},
    "projects/trio": {"title": "Trio", "name": "Trio", "org": "home", "tags": [], "type": "project", "session": "trio", "status": "active", "board": [], "board_row": False,
    "updated": 1, "mirror": "https://example.invalid/trio", "agents": {"trio-main": "Oliver's point of contact", "trio-side": "Oliver's second desk", "trio-x": "builds, merges and releases the code"},
    "back_agents": {"trio-x": "builds, merges and releases the code"}}}}))      # two background agents, neither builds or merges: duo-b is listed first
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
item(17, owner=A, status="completed", needs=["decision"])      # a closed item that still carries the need: it is nobody's to act on
item(16, owner=A, mover="Oliver", state="your-step", step="sign the export form")      # a step that is his, not a decision: the model reads him as its mover
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
from stackshot.service import front_turn as _front_turn_mod
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
_web_page_debts._owing_note = lambda debtor: ""
_cfg.CFG["router"] = {"command": [sys.executable, "-c", "pass"], "timeout_seconds": 20, "live": True}
KEY = "projects/alpha"
MACH = "home-test"
def gate_open():
    """The rollout gate: the builder's and the page keeper's hooks have fetched held lines (held.mark_client), and the machine holds their sessions."""
    held.mark_client(X, "work-osprey-x"); held.mark_client(D, "work-osprey-docs"); held.mark_client(A, "work-osprey-main"); held.mark_client(E, "solo-main"); held.mark_client(C, "comp-main"); held.mark_client(M, "duo-main"); held.mark_client(TM, "trio-main"); held.mark_client(TS, "trio-side"); held.mark_client(TX, "trio-x")
for u_, n_ in ((X, "work-osprey-x"), (A, "work-osprey-main"), (D, "work-osprey-docs"), (B, "home-beta"), (E, "solo-main"), (C, "comp-main"), (M, "duo-main"), (DA, "duo-a"), (DB, "duo-b"), (TM, "trio-main"), (TS, "trio-side"), (TX, "trio-x")): _clients.register(MACH, {"uuid": u_, "name": n_})
gate_open()
def ids(session): return {X: ("work-osprey-x", X), A: ("work-osprey-main", A), D: ("work-osprey-docs", D), E: ("solo-main", E), B: ("home-beta", B), C: ("comp-main", C), M: ("duo-main", M), DA: ("duo-a", DA), DB: ("duo-b", DB), TM: ("trio-main", TM), TS: ("trio-side", TS), TX: ("trio-x", TX)}[session]
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
def went_to(out, n0, builder_name="work-osprey-x", builder=X, front="work-osprey-main", front_id=A):
    """A message not for the person that the relay passed to the project's background agent and said so: the builder's pane got it, the front agent's pane and held store did not, the reply names both and how to reach the front agent."""
    return (out.startswith(f"Not for Oliver, so it went to {builder_name}, the project's background agent, instead of {front}") and "did not get it" in out and f"put {mark()} on the first line" in out
            and len(reach(builder, n0)) == 1 and reach(front_id, n0) == [] and held.count(front_id) == 0)
def sib_held(out, n0):
    """A message from a background agent of the project that is not the one the relay picks (the keeper of the pages): held for the front agent's next turn with no turn, and not passed across to the builder."""
    return out.startswith("held for work-osprey-main's next turn (work-osprey-docs is a background agent of projects/alpha") and reach(A, n0) == [] and reach(X, n0) == [] and held.count(A) >= 1
def held_note(out, n0, who="work-osprey-main", ref=A):
    """A done or no-action note the relay held for the front agent's next turn: no turn started, one held line, the reply says it is a note and how to have it written onto an item instead."""
    return out.startswith(f"held for {who}'s next turn (") and "no-action note" in out and "so it starts no turn" in out and "better written on the board item it concerns" in out and reach(ref, n0) == [] and held.count(ref) == 1


def log_row(frm, to, ago_min=1.0, text="a question?", outcome="delivered", question=True):
    """A row of the message log: `frm` wrote to `to` `ago_min` minutes ago; with `question` it carries the mark a front agent sets with question=true (the signal that a later message from `to` answers it)."""
    _messaging.MSG_LOG.parent.mkdir(parents=True, exist_ok=True)
    t = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=ago_min)).isoformat(timespec="seconds")
    with open(_messaging.MSG_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": t, "from": frm, "auth": "", "to": to, "outcome": outcome, "error": "", "text": text, **({"question": True} if question else {})}, ensure_ascii=False) + "\n")
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
pane("work-osprey-main", A); pane("solo-main", E); pane("comp-main", C); pane("duo-main", M); pane("trio-main", TM); pane("trio-side", TS)
FRONT, BACK, SOLO = "work-osprey-main", "work-osprey-x", "solo-main"

# ---- 1. the message tool, to a front agent
fresh(); no_log(); unstamp(A); n0 = len(pushes())
out = msg(FRONT, "can you look at the export page when you have a minute?", "home-beta"); settle()
check("1a: a peer's message that is no answer goes to the project's background agent, and the reply says so and how to reach the front agent", went_to(out, n0), out)
fresh(); out = msg(FRONT, "the PR is merged, the suites pass.", BACK); settle()
check("1b: a done note from a session is held for the front agent's next turn (no turn, nothing sent to the pane), the reply saying it is a note", held_note(out, n0), out)
fresh(); n0 = len(pushes()); out = msg(FRONT, mark() + "\nFYI the build is done, no action needed.", BACK); settle()
check("1c: …and so is a marked note that says nothing is needed from the person", out.startswith("held for work-osprey-main's next turn") and "marks only what Oliver has to do" in out and "so it starts no turn" in out and held.count(A) == 1 and reach(A, n0) == [], out)
fresh(); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, mark() + "\na14: Decide whether the export ships on Friday.", "home-beta"); settle(); unstamp(A)      # a marked message starts a turn only while he is talking with the agent (or asked it about the item): he is, here
check("1d: a marked message that needs the person is delivered, as before", out.startswith("delivered") and len(reach(A, n0)) == 1 and reach(A, n0)[0][1].count(mark()) >= 1 and held.count(A) == 0, (out, pushes()[n0:]))
# the mark must name an open item of his: needs hold decision (a14), or the step is his (a16); else the message is held for the agent's next turn, whoever sent it and whoever is there
fresh(); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, mark() + "\nDecide whether the export ships on Friday.", "home-beta"); settle()
check("1d2: a marked message that names no item, though he is talking with the agent, is held for its next turn: no turn, the reply gives the reason and what to do, the words are in the held store",
      out.startswith("held for work-osprey-main's next turn") and "must name an open item of his" in out and "names none" in out and "starts no turn" in out and "plain id" in out and "send it again" not in out
      and reach(A, n0) == [] and held.count(A) == 1 and "Decide whether the export ships on Friday" in held.take(A, FRONT), (out, pushes()[n0:]))
fresh(); n0 = len(pushes()); out = msg(FRONT, mark() + "\na1: Decide whether the export ships on Friday.", "home-beta"); settle()
check("1d3: …so is one that names only an item of an agent's own work (a1: no decision, no step of his), though he is there", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [] and held.count(A) == 1, (out, pushes()[n0:]))
fresh(); n0 = len(pushes()); out = msg(FRONT, mark() + "\na15: Decide whether the export ships on Friday.", "home-beta"); settle()
check("1d4: …and one that names a closed item (a15 needs a decision but is closed)", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [] and held.count(A) == 1, (out, pushes()[n0:]))
fresh(); n0 = len(pushes()); out = msg(FRONT, mark() + "\na17: Decide whether the export ships on Friday.", "home-beta"); settle()
check("1d4b: …and one that names a closed item that still carries needs: decision (a17): a closed item is no item of his", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [] and held.count(A) == 1, (out, pushes()[n0:]))
fresh(); n0 = len(pushes()); out = msg(FRONT, mark() + "\na16: sign the export form when you have a minute", "home-beta"); settle()
check("1d5: a marked message naming a step that is his (a16: your-step, no decision in needs) is a turn while he is talking with the agent", out.startswith("delivered") and len(reach(A, n0)) == 1 and held.count(A) == 0, (out, pushes()[n0:]))
unstamp(A); fresh(); n0 = len(pushes()); out = msg(FRONT, mark() + "\na16: sign the export form when you have a minute", "home-beta"); settle()
check("1d6: …and with him away, and no ask of his, it is refused (the item is his, but no turn is warranted), not held", out.startswith("Refused") and "starts no turn" in out and reach(A, n0) == [] and held.count(A) == 0, (out, pushes()[n0:]))
# a fixed no-action phrase counts only as the message's own statement: the word "fyi" inside a request (a delivery mode described) is no note
REQ = "a16: Please fix the delivery of the export form; sending it as an fyi so it waits for your next turn."
fresh(); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, mark() + "\n" + REQ, "home-beta"); settle(); unstamp(A)
check("1e1: a marked request that uses 'fyi' only inside a clause, naming a step of his, is delivered while he is there (not taken for a no-action note), the reply saying the word was not read as a note", out.startswith("delivered") and len(reach(A, n0)) == 1 and held.count(A) == 0
      and out.endswith("Its text uses 'fyi' inside a sentence, which is not read as saying nothing is needed from Oliver, so it was judged on the items it names."), (out, pushes()[n0:]))
for name, text in (("the word in a later clause of the request", "a16: Please sign the export form (it is an fyi in the thread, not in the form) when you have a minute."),
                   ("the word in a quoted line", "a16: Please sign the export form.\n> FYI the export is merged\nIt is the quoted line above that is stale."),
                   ("the word in a quoted phrase", 'a16: Please sign the export form; the note on it says "no action needed", which is wrong.'),
                   ("the word in a code span", "a16: Please sign the export form; the delivery mode `fyi` is what held it.")):
    fresh(); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, mark() + "\n" + text, "home-beta"); settle(); unstamp(A)
    check(f"1e2: a marked request with {name} is delivered, not taken for a note", out.startswith("delivered") and len(reach(A, n0)) == 1 and held.count(A) == 0, (out, pushes()[n0:]))
for text, phrase in (("a1: the export form is signed. FYI.", "FYI"), ("a1: the export form is signed, no action needed", "no action needed"), ("a1: FYI the export form is signed", "FYI"),
                     ("a1 for the record: the form is signed", "for the record"), ("the form is signed (FYI)\na1", "FYI"), ("a1: the form is signed\n- no decision needed", "no decision needed"),
                     ("a1: signed - nothing to decide", "nothing to decide")):      # a1 is an item of the builder's, none of his: a note that names no item of his is held (one that names a16 or a14 is a real ask, 10a)
    fresh(); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, mark() + "\n" + text, "home-beta"); settle(); unstamp(A)
    check(f"1e3: a marked no-action statement ({text!r}) is held for the next turn as a note, the reply quoting {phrase!r}, and starts no turn", out.startswith("held for work-osprey-main's next turn") and f"({phrase!r})" in out and reach(A, n0) == [] and held.count(A) == 1, (out, pushes()[n0:]))
# …unmarked: a front peer's request that uses the word is held for the next turn like any peer's message; its true note is held as a note
fresh(); n0 = len(pushes()); out = msg(FRONT, "Please fix the delivery of the export page; sending it as an fyi so it waits for your next turn.", SOLO); settle()
check("1e4: a front peer's unmarked request that uses 'fyi' inside a clause is held for the peer's next turn as any peer's message, not as a note", out.startswith("held for work-osprey-main's next turn") and "no-action note" not in out and "is a front agent, so its message" in out and held.count(A) == 1 and reach(A, n0) == [], out)
fresh(); n0 = len(pushes()); out = msg(FRONT, "the export page is fixed, no action needed.", SOLO); settle()
check("1e5: …its true no-action note is held as a note, the reply quoting the phrase", held_note(out, n0) and "('no action needed')" in out, out)
fresh(); n0 = len(pushes()); out = msg(FRONT, "can you look at the export page, sending it as an fyi so it waits", "home-beta"); settle()
check("1e6: an unmarked text that uses 'fyi' inside a clause is no note: it goes to the background agent as any non-answer", went_to(out, n0), out)
fresh(); n0 = len(pushes()); out = msg(FRONT, "FYI the export page is fixed", "home-beta"); settle()
check("1e7: …while an unmarked 'FYI the export page is fixed' is a note, held, the reply quoting 'FYI'", held_note(out, n0) and "('FYI')" in out, out)
fresh(); n0 = len(pushes()); out = msg(FRONT, "a1: Merged. FYI.", BACK); settle()
check("1e8: a background agent's hand-back that ends in the phrase is written onto the item", out.startswith("Not delivered: written onto a1") and reach(A, n0) == [], out)
fresh(); n0 = len(pushes()); out = msg(FRONT, mark() + "\na1: the build is merged. No reply needed.", BACK); settle()
check("1e9: a marked hand-back that ends in the phrase and names an item is written onto it, not refused", out.startswith("Not delivered: written onto a1") and reach(A, n0) == [] and held.count(A) == 0, out)
_own = lambda t: [m.group(0) for m in _messaging._own_no_actions(t)]
check("1e10: the phrase finder: an opening, a line start, a list dash, a comma, bracket or dash clause that ends there, and a lead item id count",
      _own("FYI the build is live") == ["FYI"] and _own("done.\nNo action needed") == ["No action needed"] and _own("done\n- for the record") == ["for the record"] and _own("done, no reply needed") == ["no reply needed"]
      and _own("done (FYI)") == ["FYI"] and _own("done " + chr(0x2014) + " FYI") == ["FYI"] and _own("a12 FYI the build is live") == ["FYI"] and _own("x" + chr(35) + "12 FYI the build is live") == ["FYI"] and _own("this is only an FYI") == ["FYI"]
      and _own("it is just for the record.") == ["for the record"] and _own("this is an fyi so it waits") == [] and _own("done; nothing to decide.") == ["nothing to decide"], "")
check("1e11: …and a phrase inside a clause, after a quote or a quote mark, in a code span, or followed on in the same clause does not",
      _own("sending it as an fyi so it waits") == [] and _own('he said "FYI the build"') == [] and _own("> FYI the build is live") == [] and _own("use `fyi` for it") == [] and _own("done, fyi it waits") == []
      and _own("the word for the record is used") == [] and _own("the answer reached it only as an fyi notice") == [], [_own(t) for t in ("sending it as an fyi so it waits", "done, fyi it waits")])
check("1e12: _without_no_action blanks only the phrases that count", _messaging._without_no_action("merged, no action needed. Sent as an fyi.") == "merged,  . Sent as an fyi.", _messaging._without_no_action("merged, no action needed. Sent as an fyi."))
fresh(); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, mark() + "\nDecide whether the export ships on Friday.", "Oliver"); settle()
check("1d7: his own marked message is exempt: delivered with no item named", out.startswith("delivered") and len(reach(A, n0)) == 1 and held.count(A) == 0, (out, pushes()[n0:]))
fresh(); n0 = len(pushes()); out = msg(FRONT, mark() + "\nDecide whether the export ships on Friday.", "deploy-watch", origin=MACH); settle()
check("1d8: a script's marked message that names no item is held like a session's: no exemption", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [] and held.count(A) == 1, (out, pushes()[n0:]))
fresh(); n0 = len(pushes()); out = msg(FRONT, mark() + "\n`a14` needs a decision on whether the export ships on Friday.", "home-beta"); settle()
check("1d9: an id in backticks names no item (the tool text says to write it plain): held, though a14 waits on his decision", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [] and held.count(A) == 1, (out, pushes()[n0:]))
_real_load_h = _front_turn_mod._load
def _boom_load(g): raise OSError("the store cannot be read")
_front_turn_mod._load = _boom_load
fresh(); n0 = len(pushes())
try: out = msg(FRONT, mark() + "\na14: Decide whether the export ships on Friday.", "home-beta"); settle()
finally: _front_turn_mod._load = _real_load_h
check("1d10: a read of the item that fails counts as no item of his: held, never delivered, though he is talking with the agent", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [] and held.count(A) == 1, (out, pushes()[n0:]))
_real_his = _front_turn_mod.his_items
def _boom_his(subject): raise RuntimeError("the reader itself failed")
_front_turn_mod.his_items = _boom_his
fresh(); n0 = len(pushes())
try: out = msg(FRONT, mark() + "\na14: Decide whether the export ships on Friday.", "home-beta"); settle()
finally: _front_turn_mod.his_items = _real_his
check("1d10b: the reader raising outright is no item of his either: held, never delivered, though he is talking with the agent", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [] and held.count(A) == 1, (out, pushes()[n0:]))
_front_turn_mod.his_items = _boom_his
fresh(); n0 = len(pushes())
try: out = msg(FRONT, mark() + "\na14: Decide whether the export ships on Friday. FYI option B costs 40 USD.", "home-beta"); settle()
finally: _front_turn_mod.his_items = _real_his
check("1d10c: …with a no-action phrase in it the reader raising still means no item of his: the phrase is not taken as left out, the note is held, never delivered as a request, and as the note it is (the hold names the phrase, not the missing item)", out.startswith("held for work-osprey-main's next turn") and "says nothing is needed from him" in out and reach(A, n0) == [] and held.count(A) == 1, (out, pushes()[n0:]))
_cfg.CFG["router"]["hold_notices"] = False
fresh(); n0 = len(pushes()); out = msg(FRONT, mark() + "\nDecide whether the export ships on Friday.", "home-beta"); settle()
check("1d11: with the hold switched off nothing can hold it: refused in one line, nothing held or pushed", out.startswith("Refused") and "must name an open item of" in out and "plain id" in out and "\n" not in out and reach(A, n0) == [] and held.count(A) == 0, (out, pushes()[n0:]))
_cfg.CFG["router"].pop("hold_notices"); unstamp(A)
fresh(); n0 = len(pushes()); out = msg(FRONT, "go on with the export", "Oliver"); settle()
check("1e: the person's own unmarked message is refused without the mark, as before", out.startswith("Refused") and "first line" in out and reach(A, n0) == [] and held.count(A) == 0, out)
out = msg(FRONT, "it now needs: decision", BACK); settle()
check("1f: an unmarked message that says needs: decision is refused, the mark goes on its first line", out.startswith("Refused") and "first line" in out and held.count(A) == 0, out)
fresh(); n0 = len(pushes()); out = msg(SOLO, "can you look at the export page when you have a minute?", "home-beta"); settle()
row_ = [x for x in mlog() if x.get("to") == SOLO and "export page" in x.get("text", "")]
check("1g: a project with no background agent holds the peer's message through the front gate: no turn, the held store has its words, unmarked", out.startswith("held for solo-main's next turn") and reach(E, n0) == [] and held.count(E) == 1
      and "can you look at the export page" in held.take(E, SOLO) and len(row_) == 1 and row_[0]["outcome"] == "held for its next turn (front agent)", (out, row_))
fresh(); out = msg(SOLO, "the PR is merged, the suites pass.", BACK); settle()
check("1h: …a done note to it is held for its next turn all the same (no message to the pane)", out.startswith("held for solo-main's next turn") and "no-action note" in out and held.count(E) == 1, out)
fresh(); n0 = len(pushes()); out = msg(FRONT, "can you look at the export page?", "home-beta", origin=MACH); settle()
check("1i: a script's unmarked message to a front agent with a background agent goes to it", went_to(out, n0), out)
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
check("2g: a sender the agent never wrote to is no answer, whatever the conversation: not delivered (a sibling background agent's message is held for the next turn, not passed across)", sib_held(out, n0), (out, pushes()[n0:]))
no_log(); log_row(FRONT, "work-osprey-docs", 25 * 60); n0 = len(pushes()); out = msg(FRONT, "the docs page looks fine to me", "work-osprey-docs"); settle()
check("2h: …a question put to the sender more than a day ago is no signal either", sib_held(out, n0), (out, pushes()[n0:]))
no_log(); fresh(); log_row("work-osprey-docs", "home-beta", 5); n0 = len(pushes()); out = msg(FRONT, "the docs page reads fine", "home-beta"); settle()
check("2i: a question put by another agent of the front agent's project is not the front agent's own: no answer, whatever the conversation: passed to the background agent", went_to(out, n0), (out, pushes()[n0:]))
fresh(); no_log(); log_row("work-osprey-docs", BACK, 300); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, "the docs page reads fine", BACK); settle()
check("2i2: …the background agent's unmarked note after another project agent's question to it is not delivered while the person is present: held for the next turn", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [] and held.count(A) == 1, (out, pushes()[n0:]))
stamp(A, 31); fresh(); n0 = len(pushes()); out = msg(FRONT, "a1: the docs page reads fine", BACK); settle()
check("2i3: …and with the person away it is held too, not written onto the item it names (it answers no question of the front agent)", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [] and held.count(A) == 1, out)
no_log(); fresh(); log_row(FRONT, BACK, 23 * 60 + 50); log_row("work-osprey-docs", BACK, 5); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, "yes, the export is ready for review", BACK); settle()
check("2i4: the front agent's own question inside the lookback still counts when another agent asked later: delivered unmarked in the conversation", out.startswith("delivered") and len(reach(A, n0)) == 1 and mark() not in reach(A, n0)[0][1], (out, pushes()[n0:]))
no_log(); fresh(); log_row(FRONT, BACK, 24 * 60 + 10); log_row("work-osprey-docs", BACK, 5); n0 = len(pushes()); out = msg(FRONT, "yes, the export is ready for review", BACK); settle()
check("2i5: …and one put just past the lookback does not, the other agent's later question making no difference: held", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [], (out, pushes()[n0:]))
fresh(); no_log(); log_row("home-beta", "work-osprey-docs", 5); n0 = len(pushes()); out = msg(FRONT, "the docs page reads fine", "work-osprey-docs"); settle()
check("2j: a question put by an agent of another project does not count", sib_held(out, n0), (out, pushes()[n0:]))
for name, kw in (("a handover from an agent of the project that asks nothing", {"text": "please take the export task and tell me when it is done", "question": False}), ("a question whose delivery failed", {"outcome": "failed: no such session"})):
    no_log(); fresh(); log_row(FRONT, "work-osprey-docs", 5, **kw); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, "the docs page reads fine", "work-osprey-docs"); settle()
    check(f"2l: {name} is no question, so the reply is no answer: not delivered, no turn at the front agent (held for the next turn)", sib_held(out, n0), (out, pushes()[n0:]))
for name, kw in (("with no question flag, a question mark in its text all the same", {"text": "is the export on your list?", "question": False}), ("whose delivery failed", {"outcome": "failed: no such session"})):
    no_log(); fresh(); log_row(FRONT, BACK, 5, **kw); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, "the docs page reads fine", BACK); settle()
    check(f"2l2: the front agent's own message {name} is no question: the background agent's later note is held, not delivered", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [], (out, pushes()[n0:]))
no_log(); fresh(); log_row("work-osprey-x", "work-osprey-docs", 5, text="please take the export task and tell me when it is done", question=False); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, "the docs page reads fine", "work-osprey-docs"); settle()
check("2m: a message from the project's builder that asks nothing makes the sender's later note no answer (the staged test of a plain note to the front agent)", sib_held(out, n0), (out, pushes()[n0:]))
no_log(); log_row(FRONT, BACK, 5); n0 = len(pushes()); out = msg(FRONT, mark() + "\na14: Decide whether the export ships on Friday.", BACK); settle()
check("2k: an answer that needs the person is marked and delivered whatever the conversation", out.startswith("delivered") and len(reach(A, n0)) == 1 and mark() in reach(A, n0)[0][1], (out, pushes()[n0:]))

# the mark makes a question, never a question mark: the message tool's question=true, written to the log row, is the one signal (asked_by)
def tool(to, text, sender, **k):
    try: return _wt_message.stackshot_message(to=to, text=text, sender=sender, **k)
    except ToolError as e: return str(e)
def age_last(minutes):
    """Move the newest row the front agent wrote to the builder back in time by `minutes` (a row written through the tool, aged)."""
    rows = [json.loads(l) for l in _messaging.MSG_LOG.read_text().splitlines()]
    row = [r for r in rows if r["from"] == FRONT and r["to"] == BACK][-1]
    row["t"] = (datetime.datetime.fromisoformat(row["t"]) - datetime.timedelta(minutes=minutes)).isoformat(timespec="seconds")
    _messaging.MSG_LOG.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
QURL = "see https://example.org/export?page=2 and Oliver's words: \"can this ship?\" for the layout"
for name, text in (("a question mark in its text", "is the export ready for review?"), ("a quoted URL and quoted words with a question mark", QURL)):
    no_log(); fresh(); n0 = len(pushes()); out = tool(BACK, text, FRONT); settle(); row = [x for x in mlog() if x.get("from") == FRONT and x.get("to") == BACK]
    check(f"2n: the message tool sends {name} without question=true: delivered, and its log row carries no question mark of the flag", out.startswith("delivered") and len(row) == 1 and "question" not in row[0], (out, row))
    stamp(A, 5); n0 = len(pushes()); h0 = held.count(A); out = msg(FRONT, "yes, the export is ready for review", BACK); settle()
    check(f"2o: …so the reply is no answer (the tool path): held for the agent's next turn, not delivered while the person is in that conversation", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [] and held.count(A) == h0 + 1, (out, pushes()[n0:]))
    fresh(); stamp(A, 5); n0 = len(pushes()); n = recp("yes, the export is ready", kind="message", who="work-osprey-x (33333333\u2026)"); res = act2(n, FRONT)
    check(f"2p: …and the router's pass of the reply is no answer either: held, never delivered to the agent", res["ruling"] == "held" and reach(A, n0) == [] and held.count(A) == 1, (res, pushes()[n0:]))
no_log(); fresh(); n0 = len(pushes()); out = tool(BACK, "is the export ready for review?", FRONT, question=True); settle(); row = [x for x in mlog() if x.get("from") == FRONT and x.get("to") == BACK]
check("2q: question=true is logged on the row of the delivered message", out.startswith("delivered") and len(row) == 1 and row[0].get("question") is True and row[0]["outcome"].startswith("delivered"), (out, row))
stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, "yes, the export is ready for review", BACK); settle()
check("2r: …and a reply to it is an answer within the day (the tool path): delivered to the agent, unmarked, while the person is in that conversation", out.startswith("delivered") and len(reach(A, n0)) == 1 and mark() not in reach(A, n0)[0][1], (out, pushes()[n0:]))
fresh(); stamp(A, 5); n0 = len(pushes()); n = recp("yes, the export is ready", kind="message", who="work-osprey-x (33333333\u2026)"); res = act2(n, FRONT)
check("2s: …and the router's pass of it (the router path)", res["ruling"] == "passed" and res["target"] == FRONT and res["marked"] is False and len(reach(A, n0)) == 1, (res, pushes()[n0:]))
age_last(23 * 60 + 50); fresh(); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, "yes, the export is ready for review", BACK); settle()
check("2t: the same marked question 23 h 50 min old still makes the reply an answer", out.startswith("delivered") and len(reach(A, n0)) == 1, (out, pushes()[n0:]))
age_last(30); fresh(); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, "yes, the export is ready for review", BACK); settle()
check("2u: …and past the day (24 h 20 min) it does not: held for the next turn, not delivered", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [], (out, pushes()[n0:]))
no_log(); fresh(); n0 = len(pushes()); out = tool(BACK, "is the export ready for review?", FRONT, question=True, fyi=True); settle()
check("2v: question=true beside fyi=true is refused in one line, nothing sent or logged", out.startswith("Refused") and "question=true and fyi=true" in out and "\n" not in out and pushes()[n0:] == [] and mlog() == [], (out, mlog()))
no_log(); fresh(); n0 = len(pushes()); out = tool(BACK, "is the export ready for review?", "Oliver", question=True); settle()
check("2w: question=true from the person himself is refused in one line, nothing sent or logged", out.startswith("Refused") and "question=true" in out and "\n" not in out and pushes()[n0:] == [] and mlog() == [], (out, mlog()))
no_log(); fresh(); n0 = len(pushes()); out = tool(BACK, "is the export ready for review?", FRONT, question=False); settle()
check("2x: question=false (the default) is as before: delivered, the row without the mark", out.startswith("delivered") and "question" not in [x for x in mlog() if x.get("to") == BACK][0], (out, mlog()))
no_log(); fresh(); n0 = len(pushes()); st_, body_ = _rt_client._client_post(MACH, "message", {"to": BACK, "text": "is the export ready for review?", "sender": FRONT, "question": True}); settle(); row = [x for x in mlog() if x.get("from") == FRONT and x.get("to") == BACK]
check("2y: a script's question (POST /client/message with question=true) is delivered and its log row carries the mark", st_ == 200 and str(body_.get("result", "")).startswith("delivered") and len(row) == 1 and row[0].get("question") is True, (st_, body_, row))
stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, "yes, the export is ready for review", BACK); settle()
check("2y1: …and a reply to it is an answer (delivered while the person is in that conversation), as for the tool's mark", out.startswith("delivered") and len(reach(A, n0)) == 1, (out, pushes()[n0:]))
no_log(); fresh(); n0 = len(pushes()); st_, body_ = _rt_client._client_post(MACH, "message", {"to": BACK, "text": "is the export ready for review?", "sender": FRONT, "question": "yes"}); settle(); row = [x for x in mlog() if x.get("from") == FRONT and x.get("to") == BACK]
check("2y2: only a body value of true marks a script's question (a string does not): the row carries no mark", st_ == 200 and len(row) == 1 and "question" not in row[0], (st_, body_, row))
no_log(); fresh(); n0 = len(pushes()); st_, body_ = _rt_client._client_post(MACH, "message", {"to": BACK, "text": "is the export ready for review?", "sender": FRONT, "question": True, "fyi": True}); settle()
check("2z: a script's question beside fyi is refused (400) with the tool's own line, nothing sent or logged", st_ == 400 and "question=true and fyi=true" in str(body_.get("error", "")) and pushes()[n0:] == [] and mlog() == [], (st_, body_, mlog()))
no_log(); fresh(); n0 = len(pushes()); st_, body_ = _rt_client._client_post(MACH, "message", {"to": BACK, "text": "is the export ready for review?", "sender": "Oliver", "question": True}); settle()
check("2z1: a script's question in the person's own name is refused (400), nothing sent or logged", st_ == 400 and "question=true" in str(body_.get("error", "")) and pushes()[n0:] == [] and mlog() == [], (st_, body_, mlog()))
no_log()

# a background agent's hand-back is tested BEFORE the answer rule: a question the front agent put to it makes a hand-back no answer
def asked_present(minutes_ago=5):
    no_log(); fresh(); log_row(FRONT, BACK, 5); stamp(A, minutes_ago)      # the agent asked the builder a question and the person is in that conversation: the old order delivered any note the builder sent now
for name, text in (("a bare taken", "Taken."), ("a done note with a sha", "Done (010cc0d)."), ("a status that names no item", "the PR is merged, the suites pass."), ("a stopped thing", "the watch is stopped and the item is complete.")):
    asked_present(); n0 = len(pushes()); out = msg(FRONT, text, BACK); settle()
    check(f"2n: a builder's hand-back ({name}) that names no item is not delivered as an answer, while the person is in the conversation: held for the next turn as a note", held_note(out, n0), (out, pushes()[n0:]))
asked_present(); n0 = len(pushes()); out = msg(FRONT, "a1: Done (010cc0d), the unit is live.", BACK); settle()
rows_ = [x for x in mlog() if "written onto a1" in str(x.get("outcome"))]
check("2n2: …a hand-back that names an open item is written onto it (History line), not delivered, not held, while he is in the conversation", out.startswith("Not delivered: written onto a1") and reach(A, n0) == [] and held.count(A) == 0 and len(rows_) == 1, (out, rows_))
asked_present(); out = msg(FRONT, "a1: taken.", BACK); settle()
check("2n3: …'taken' with an item is written onto it too", out.startswith("Not delivered: written onto a1"), out)
asked_present(); n0 = len(pushes()); out = msg(FRONT, "a14: the unit is live.", BACK); settle()
check("2n4: …a hand-back on an item that waits on his decision is held, never delivered as an answer", held_note(out, n0), (out, pushes()[n0:]))
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
# a status that says what is missing, and an opening yes or no beside a fixed phrase, are no hand-back: delivered to the agent that asked, never written onto the item
for text in ("a1: done, but nothing is live", "a1: nothing was removed", "a1: nothing merged", "a1: none deployed", "a1: no PR merged", "a1: zero merged", "a1: closed, nothing deployed",
             "a1: Done except the docs", "a1: merged, except the docs", "a1: partly done", "a1: half merged", "a1: done, but the port is in use", "a1: the suites are red",
             "a1: Yes, finished. FYI.", "a1: FYI: no, merged", "a1: for the record: yes, closed", "a1: FYI, yes, closed",
             "a1: No changes were merged.", "a1: No change landed.", "a1: Merged, no changes were deployed.", "a1: 3 of 5 merged", "a1: merged, only the docs", "a1: mostly done",
             "a1: done, the job timed out", "a1: Done, no errors, but nothing is live"):
    asked_present(); n0 = len(pushes()); out = msg(FRONT, text, BACK); settle()
    check(f"2p3: {text!r} is no hand-back: delivered to the agent that asked, not written onto the item", out.startswith("delivered") and len(reach(A, n0)) == 1 and held.count(A) == 0, (out, pushes()[n0:]))
# …and the plain reports of the same words stay hand-backs: written onto the item, no turn
for text in ("a1: No change.", "a1: No changes.", "a1: no unit changed", "a1: nothing changed", "a1: Taken.", "Taken (a1).", "a1: Taken (PR 12).", "a1: Done (abc1234).", "a1: PR 12 merged and live",
             "a1: item complete", "a1: the watch is stopped and the item is closed", "a1: FYI, the item is closed.", "a1: No-op, unchanged.",
             "a1: Done, no errors.", "a1: Merged without conflicts.", "a1: Closed without merging.", "a1: Merged, nothing to report.", "a1: Taken (PR 12 and PR 13).", "a1: Taken (PRs 12, 13 and 14)."):
    asked_present(); n0 = len(pushes()); out = msg(FRONT, text, BACK); settle()
    check(f"2p4: {text!r} is a hand-back: written onto the item, not delivered", out.startswith("Not delivered: written onto a1") and reach(A, n0) == [] and held.count(A) == 0, (out, pushes()[n0:]))
asked_present(); n0 = len(pushes()); out = msg(FRONT, "Taken.", BACK); settle()
check("2p5: a bare 'Taken.' that names no item is held as a note, as a refusal before", held_note(out, n0), (out, pushes()[n0:]))
asked_present(); n0 = len(pushes()); out = msg(FRONT, "a1: the export page reads fine, sent as an fyi", BACK); settle()
check("2p6: a background agent's text that uses 'fyi' only inside a clause is no fixed-phrase note: not written onto the item, delivered to the agent that asked", out.startswith("delivered") and len(reach(A, n0)) == 1 and held.count(A) == 0, (out, pushes()[n0:]))
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
# a message a session wrote needs him only by naming an open item of his: the model call's for_owner guess and a mark or needs: decision in its text are no source (a board or anchor notice keeps them, 4b)
for name, text, kw in (("the model call's for_owner guess alone", "the release is live", {"for_owner": True}), ("his mark in the text, no item", "the release is live - " + mark() + " pick a or b", {}),
                       ("needs: decision in the text, no item", "the release is live; it now needs: decision", {}), ("an item of an agent's own work (a1)", "the release is live, see a1", {"for_owner": True}),
                       ("the ruling's item (a14, a decision item) alone, the text naming none", "the release is live", {"item": "a14"}), ("the ruling's item (a14) alone, the text writing it in backticks", "the release is live, see `a14`", {"item": "a14"})):
    fresh(); stamp(A, 5); n0 = len(pushes()); n = recp(text, kind="message", who="home-beta (44444444…)"); res = act2(n, FRONT, **kw); unstamp(A)
    check(f"4b4: a message with {name} starts no turn though he is talking with the agent: not delivered to it, not held for it, passed to the builder unmarked; the reason says it names no open item of his",
          res["ruling"] == "passed" and res["target"] == BACK and res["marked"] is False and reach(A, n0) == [] and held.count(A) == 0 and len(reach(X, n0)) == 1 and not reach(X, n0)[0][1].startswith(mark())
          and "names no open item of his" in res["reason"], (res, pushes()[n0:]))
for name, text, kw in (("a decision item in the text", "the release is live, see a14", {}), ("a decision item in the text and as the ruling's item", "the release is live, see a14", {"item": "a14"}), ("a step that is his (a16), no decision", "the release is live, see a16", {}),
                       ("a step that is his, with no for_owner guess and no mark", "a16 is waiting for you", {})):
    fresh(); stamp(A, 5); n0 = len(pushes()); n = recp(text, kind="message", who="home-beta (44444444…)"); res = act2(n, FRONT, **kw); unstamp(A)
    check(f"4b5: a message naming an open item of his ({name}) is marked and a turn while he is talking with the agent", res["ruling"] == "passed" and res["target"] == FRONT and res["marked"] is True and len(reach(A, n0)) == 1
          and reach(A, n0)[0][1].startswith(mark()) and reach(X, n0) == [], (res, pushes()[n0:]))
    fresh(); n0 = len(pushes()); n = recp(text, kind="message", who="home-beta (44444444…)"); res = act2(n, FRONT, **kw)
    check(f"4b6: …and with him away, not delivered, not held ({name})", reach(A, n0) == [] and held.count(A) == 0 and res.get("held_for") != FRONT, (res, pushes()[n0:]))
# a message that carries his own words keeps its source
fresh(); stamp(A, 5); n0 = len(pushes()); n = {**recp("the release is live", kind="message", who="home-beta (44444444…)"), "words": "ship it"}; res = act2(n, FRONT); unstamp(A)
check("4b7: a message that carries his words keeps them as its source: marked, a turn while he is there", res["ruling"] == "passed" and res["target"] == FRONT and res["marked"] is True and len(reach(A, n0)) == 1, (res, pushes()[n0:]))
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
fresh(); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, mark() + "\na14: Decide whether the export ships on Friday.", SOLO); settle(); unstamp(A)
check("7e: …a front agent's marked message to a peer still needs the person and is delivered", out.startswith("delivered") and len(reach(A, n0)) == 1, out)
# one choice of background agent, for the message tool and the router alike
fresh(); n0 = len(pushes()); out = msg(COMP, "can you look at the export page?", "home-beta"); settle()
check("7f: a hub component page with no background agent of its own takes its hub's, in the message tool: passed to the hub's builder", went_to(out, n0, "work-osprey-x", X, "comp-main", C), out)
fresh(); n0 = len(pushes()); n = recp("the release is live", key="projects/comp"); res = act2(n, COMP, key="projects/comp")
check("7g: …and in the router: the pass goes to the hub's builder, unmarked", res["ruling"] == "passed" and res["target"] == BACK and res["marked"] is False and len(reach(X, n0)) == 1 and reach(C, n0) == [], (res, pushes()[n0:]))
fresh(); n0 = len(pushes()); out = msg(DUOM, "can you look at the export page?", "home-beta"); settle()
check("7h: two background agents and no builder: the message tool names the first by one order (duo-a), not the first listed", went_to(out, n0, "duo-a", DA, "duo-main", M) and "duo-b" not in out, out)
fresh(); n0 = len(pushes()); n = recp("the release is live", key="projects/duo"); res = act2(n, DUOM, key="projects/duo")
check("7i: …and the router names the same one", res["ruling"] == "passed" and res["target"] == DUOA and len(reach(DA, n0)) == 1 and reach(DB, n0) == [], (res, pushes()[n0:]))
# a held pass of a session's message is whole (a status line is one line cut at held.LINE_MAX; tests/held_scenario.py has the cut above held.WHOLE_MAX)
fresh(); long_ = " ".join(f"word{i}" for i in range(120)); n = recp(long_, key="projects/solo", who="work-osprey-main (aaaaaaaa…)"); res = act2(n, SOLO, key="projects/solo"); text_ = held.take(E, SOLO)
check("7j: a held router pass longer than a status line is held whole, every word of it, with no cut note", res["ruling"] == "held" and len(long_) > held.LINE_MAX and long_ in text_ and "cut" not in text_ and "left out" not in text_ and text_.count("word") == 120, (res, text_))
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
# the item a notice names, in every form the board shows it: a notice that is no session's message reads them all (and a decision only), a session's message the forms the message tool reads (and a step of his too)
NUM = 14; cxx = _router.Context(); cxx.index[f"board#{NUM}"] = cxx.index["a14"]
for name, text in (("an item page link", f"the release is live, see {BOARD}/items/a14"), ("a capital letter id", "the release is live, see A14"), ("a bare number", f"the release is live, see #{NUM}"),
                   ("a board id", f"the release is live, see board#{NUM}")):
    check(f"7r: a notice naming a decision item by {name} stays marked", _live._item_waits_decision({}, {}, text, cxx) is True, text)
check("7s: …and one naming an item that waits on no decision does not", _live._item_waits_decision({}, {}, f"the release is live, see {BOARD}/items/a1 and A1 and #1", cxx) is False)
check("7s2: a session's message reads only the forms the message tool reads: a link, a capital letter id and a board id name the item, a bare #14 (a pull request) does not",
      all(_live._item_is_his({}, {}, t, cxx) is True for t in (f"the release is live, see {BOARD}/items/a14", "the release is live, see A14", f"the release is live, see board#{NUM}"))
      and _live._item_is_his({}, {}, f"PR #{NUM} merged", cxx) is False and _live._item_is_his({}, {}, f"PR #{NUM} merged, see `a14` and \"a14\" and a14x", cxx) is False)
LN14 = {"item": "a14"}      # the ruling's `item` reads an id in backticks, in quotes and in "a14's" (router.py _TOKEN), forms the message tool's reader ignores: for a session's message it must not name the item alone
check("7s4: a session's message whose ruling carries item=a14 but whose text writes it only in backticks or in quotes names no item of his (the tool's own reader names none either)",
      all(_live._item_is_his({}, LN14, t, cxx) is False and _live._named_items({}, LN14, t, cxx, True) == [] for t in ("see `a14` for context", 'see "a14" for context', "see 'a14' for context", "see `a14`'s form", "see \"a14\" and `a14`")),
      [(t, _live._item_is_his({}, LN14, t, cxx)) for t in ("see `a14` for context", 'see "a14" for context', "see 'a14' for context")])
check("7s5: …and with the item written as a plain word (a14's too: the tool's reader takes it) the ruling's item and the text agree: it is his; a notice that is no session's message still takes the ruling's item",
      all(_live._item_is_his({}, LN14, t, cxx) is True for t in ("see a14 for context", "a14: the export", "see a14's form for context", "(a14) first")) and _live._item_waits_decision({}, LN14, "see `a14` for context", cxx) is True)
from stackshot.service import agent_names as _agent_names_h
same_ = [(t, sorted(x["gid"] for x in _live._named_items({}, {}, t, cxx, True)), sorted(_agent_names_h._item_refs(t))) for t in
         ("see A14 and a16", f"PR #{NUM} merged", "see `a14`", "the \"a14\" suite", "a14x and xa14", f"see {BOARD}/items/a16", "a14's form", "(a14) and [a16]", "a14, a16: both", "merge group g7 split from g7")]
check("7s3: …and it names the same items as the tool's own reader, text by text", all(r == g for _, r, g in same_), [x for x in same_ if x[1] != x[2]])
_real_hook = _live._HOOKS["his_items"]
def _boom_hook(ids): raise RuntimeError("the reader failed")
_live._HOOKS["his_items"] = _boom_hook
try: _boom_res = _live._item_is_his({}, {}, f"see {BOARD}/items/a14", cxx); _boom_other = _live._must_see({"kind": "board", "who": "home-beta (11111111…)"}, {}, "see A14", cxx)
finally: _live._HOOKS["his_items"] = _real_hook
check("7t: …and a reader that raises names nothing of his (fail closed); a notice that is no session's message does not read it at all (its decision test is the index's)", _boom_res is False and _boom_other is True and _live._item_is_his({}, {}, f"see {BOARD}/items/a14", cxx) is True, (_boom_res, _boom_other))
# what is a session's message, and what a notice that is none keeps: a decision of his and nothing wider (an item whose step is his, a16, is no signal for it)
SES = {"kind": "message", "who": "home-beta (11111111…)"}
check("7u: a session's message naming an item whose step is his (a16, no decision) needs him; naming one that is nobody's of his (a1) does not", _live._must_see(SES, {}, "a16: sign the export form", cxx) is True and _live._must_see(SES, {}, "a1: sign the export form", cxx) is False)
for kind_, extra_ in (("board", {}), ("anchor", {}), ("page", {}), ("message", {"words": True}), ("message", {"handback": True})):
    check(f"7v: a {kind_} notice{' with ' + next(iter(extra_)) if extra_ else ''} naming an item whose step is his (a16) and no decision keeps its decision-only reading: not marked unless a signal of its own",
          _live._must_see({**SES, "kind": kind_, **extra_}, {}, "a16: sign the export form", cxx) is bool(extra_), (kind_, extra_))
check("7v2: …and his words or a hand-back on a message make it no session's message: marked though it names no item of his (a1)", all(_live._must_see({**SES, **x_}, {}, "a1: ok", cxx) is True for x_ in ({"words": True}, {"handback": True})) and _live._must_see(SES, {}, "a1: ok", cxx) is False)
check("7w: …a notice that is no session's message naming a decision item (a14) is marked, wherever it names it from the index", all(_live._must_see({**SES, "kind": k_}, {}, "the form for a14", cxx) is True for k_ in ("board", "anchor", "page")))
check("7x: the server's own `[board]` line and the audit's message are no session's message: a16 is no signal for them, a14 (a decision) is",
      _live._must_see(SES, {}, "[board] a16 is back with you", cxx) is False and _live._must_see(SES, {}, "[board] a14 waits on you", cxx) is True
      and _live._must_see({**SES, "who": _cfg.AUDIT_SENDER}, {}, "a16: sign the export form", cxx) is False and _live._must_see({**SES, "who": _cfg.AUDIT_SENDER}, {}, "a14: sign", cxx) is True)
check("7y: his own message to a project page names no item and is still marked (his words, as at the message tool's gate); a session's is not", _live._must_see({**SES, "who": "Oliver (11111111…)"}, {}, "go on with the export", cxx) is False
      and _live._must_see({**SES, "who": "Oliver (11111111…)"}, {}, f"{mark()} go on with the export", cxx) is True and _live._must_see(SES, {}, f"{mark()} go on with the export", cxx) is False)
fresh(); stamp(A, 5); n0 = len(pushes()); n = recp(f"{mark()} pick a or b for the export", kind="message", who="Oliver (11111111…)"); res = act2(n, FRONT); settle(); unstamp(A)
check("7z: …and the router passes his own marked message to a front agent as it did, marked, a turn while he is there", res["ruling"] == "passed" and res["target"] == FRONT and res["marked"] is True and len(reach(A, n0)) == 1, (res, pushes()[n0:]))

# ---- 8. a front agent's marked message to a sibling front agent that quotes the owner's words (sibling_words): held for the sibling's next turn, not turned away to the builder
TR, TRK = "projects/trio", "projects/trio"
M_OK, M_OLD = "aaaaaaaa-aaaa-4aaa-8aaa-000000000001", "aaaaaaaa-aaaa-4aaa-8aaa-000000000002"
QUOTE = "hand the export to the second desk"
stamp_now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
(T / f"transcripts/-x/{TM}.jsonl").write_text("\n".join(json.dumps(e) for e in (
    {"type": "user", "uuid": M_OK, "timestamp": stamp_now, "origin": {"kind": "human"}, "message": {"role": "user", "content": f"Oliver here: {QUOTE}, please"}},
    {"type": "user", "uuid": M_OLD, "timestamp": "2020-01-01T00:00:00.000Z", "origin": {"kind": "human"}, "message": {"role": "user", "content": "an old order of the second desk, long before the cap"}})) + "\n", encoding="utf-8")
LINE = f'Acked-by: "{QUOTE}" (just now, session trio-main)'
WORDS = mark() + "\na14: Oliver told me to give you the export.\n" + LINE      # a14 waits on his decision: the message names an open item of his, so main's sibling rules are what decide it
NOWORDS = mark() + "\na14: Oliver told me to give you the export."
NOITEM = mark() + "\nOliver told me to give you the export.\n" + LINE      # his quoted words, but no item of his named: this branch's item rule holds it first
tres = lambda who, text, to="trio-side": msg(to, text, who)
def tlines(): return [x for x in pushes()]
for u_ in (TS, TM, TX): unstamp(u_)

fresh(); no_log(); n0 = len(pushes()); out = tres("trio-main", WORDS); settle()
check("8a: a sibling front agent's marked message quoting his words is held for the sibling's next turn, starts no turn, and the reply says so", out.startswith("held for trio-side's next turn") and reach(TS, n0) == [] and reach(TX, n0) == [] and held.count(TS) == 1, out)
check("8b: …the held line carries the message with his quoted words", QUOTE in str(held.take(TS, "trio-side")), "")
fresh(); n0 = len(pushes()); out = tres("trio-main", NOWORDS); settle()
check("8c: the same message with no quoted words is turned away as today: refused, nothing held, nothing sent", out.startswith("Refused") and held.count(TS) == 0 and reach(TS, n0) == [], out)
fresh(); n0 = len(pushes()); out = tres("trio-main", mark() + "\na14: Oliver told me to give you the export.\n" + f'Acked-by: "{QUOTE} and more he never said" (just now, session trio-main)'); settle()
check("8d: words that are not in his message in the transcript are no words: refused as today", out.startswith("Refused") and held.count(TS) == 0, out)
fresh(); n0 = len(pushes()); out = tres("trio-main", mark() + "\na14: Oliver told me to give you the export.\n" + 'Acked-by: "an old order of the second desk" (long ago, session trio-main)'); settle()
check("8e: his words older than the wake cap are no words: refused as today", out.startswith("Refused") and held.count(TS) == 0, out)
fresh(); n0 = len(pushes()); out = tres("trio-x", WORDS); settle()
check("8f: a background agent's message quoting words is unchanged: refused, nothing held", out.startswith("Refused") and held.count(TS) == 0 and reach(TS, n0) == [], out)
fresh(); n0 = len(pushes()); out = tres("solo-main", WORDS); settle()
check("8g: another project's front agent's message quoting words is unchanged: refused, nothing held", out.startswith("Refused") and held.count(TS) == 0 and reach(TS, n0) == [], out)
fresh(); n0 = len(pushes()); out = tres("trio-main", WORDS, to="trio-x"); settle()
check("8h: a message to the project's background agent is not this rule's: delivered as before, nothing held", out.startswith("delivered") and held.count(TS) == 0 and held.count(TX) == 0, out)
fresh(); stamp(TS, 5); n0 = len(pushes()); out = tres("trio-main", WORDS); settle(); unstamp(TS)
check("8i: when he is talking with the sibling now the message starts its turn as before (the front-turn rule allows it): delivered, not held", out.startswith("delivered") and len(reach(TS, n0)) == 1 and held.count(TS) == 0, out)
fresh(); n0 = len(pushes()); out = tres("trio-main", LINE.replace('Acked-by: "', 'Suggested-by: "') + "\nplease look at the export when you can."); settle()
check("8j: an unmarked message is held for a peer front as before, with or without his words (this rule changes nothing there)", out.startswith("held for trio-side's next turn") and held.count(TS) == 1, out)

# the router: a pass of the same message to the sibling
fresh(); n0 = len(pushes()); n = recp(WORDS, key=TRK, kind="message", who="trio-main (cccccccc…)"); res = act2(n, "trio-side", key=TRK)
check("8k: the router holds a sibling front agent's pass that quotes his words: ruled held, unmarked, no turn, not sent to the builder", res["ruling"] == "held" and res["marked"] is False and reach(TS, n0) == [] and reach(TX, n0) == [] and held.count(TS) == 1, (res, pushes()[n0:]))
fresh(); n0 = len(pushes()); n = recp(NOWORDS, key=TRK, kind="message", who="trio-main (cccccccc…)"); res = act2(n, "trio-side", key=TRK)
check("8l: …the same pass with no quoted words is not held: it goes to the builder or is archived as before, and the sibling gets nothing", res["ruling"] != "held" and held.count(TS) == 0 and reach(TS, n0) == [], (res, pushes()[n0:]))
fresh(); n0 = len(pushes()); n = recp(WORDS, key=TRK, kind="message", who="trio-x (eeeeeeee…)"); res = act2(n, "trio-side", key=TRK)
check("8m: …a background agent's pass quoting words is not held by this rule", res["ruling"] != "held" and held.count(TS) == 0 and reach(TS, n0) == [], (res, pushes()[n0:]))
fresh(); n0 = len(pushes()); n = recp(WORDS, key=TRK, kind="message", who="solo-main (77777777…)"); res = act2(n, "trio-side", key=TRK)
check("8n: …nor another project's front agent's", res["ruling"] != "held" and held.count(TS) == 0 and reach(TS, n0) == [], (res, pushes()[n0:]))
fresh(); n0 = len(pushes()); n = recp(WORDS.replace('Oliver told me to give you the export.', 'Oliver told me to give you the export. (a board note, not a message)'), key=TRK, kind="board", who="trio-main (cccccccc…)"); res = act2(n, "trio-side", key=TRK)
check("8o: …and a board notice is not a message: not held by this rule", res["ruling"] != "held" and held.count(TS) == 0, (res, pushes()[n0:]))
fresh(); stamp(TS, 5); n0 = len(pushes()); n = recp(WORDS, key=TRK, kind="message", who="trio-main (cccccccc…)"); res = act2(n, "trio-side", key=TRK); unstamp(TS)
check("8p: the router's counterpart of 8i: when he is talking with the sibling now, the pass that quotes his words is a turn as the message tool has it: ruled passed, marked, sent to the sibling, nothing held", res["ruling"] == "passed" and res["marked"] is True and len(reach(TS, n0)) == 1 and held.count(TS) == 0 and reach(TX, n0) == [], (res, pushes()[n0:]))
fresh(); n0 = len(pushes()); n = recp(WORDS, key=TRK, kind="message", who="trio-main (cccccccc…)"); res = act2(n, "trio-side", key=TRK)
check("8q: …and the same pass right after, with him no longer there (no presence stamp): held, as in 8k", res["ruling"] == "held" and res["marked"] is False and reach(TS, n0) == [] and held.count(TS) == 1, (res, pushes()[n0:]))

# the two rules composed (the item rule of this branch first, the sibling's quoted words after it)
fresh(); no_log(); n0 = len(pushes()); out = tres("trio-main", WORDS); settle()
check("8r: a sibling's message that quotes valid words and names an open item of his (a14) is held by the sibling rule: the reply names the quoted words as the reason, not the item rule", out.startswith("held for trio-side's next turn") and "quotes Oliver's words" in out
      and "must name an open item" not in out and reach(TS, n0) == [] and reach(TX, n0) == [] and held.count(TS) == 1, out)
fresh(); n0 = len(pushes()); out = tres("trio-main", NOITEM); settle()
check("8s: the same message naming no item of his is held by the item rule: held for the next turn, no turn, nothing to the builder, and the reply tells the sender to put his step on an item and name it by its plain id", out.startswith("held for trio-side's next turn") and "must name an open item of his" in out
      and "names none" in out and "plain id" in out and "send it again" not in out and reach(TS, n0) == [] and reach(TX, n0) == [] and held.count(TS) == 1 and QUOTE in str(held.take(TS, "trio-side")), out)
check("8s2: …the quoted words being valid, the reply says to name the item being handed over (an open item of his) by its plain id, not only to put his step on an item", "Name the item you are handing over" in out and "an open item of his" in out and "plain id" in out, out)
fresh(); n0 = len(pushes()); out = tres("trio-main", NOITEM.replace("\nOliver told", "\n`a14` Oliver told")); settle()
check("8t: …also when the item is only written in backticks (that names none), the quoted words notwithstanding", out.startswith("held for trio-side's next turn") and "must name an open item of his" in out and held.count(TS) == 1, out)
fresh(); n0 = len(pushes()); out = tres("trio-main", NOWORDS); settle()
check("8u: naming an item of his without his words is main's refusal still (the item rule is met, no turn is warranted, no words hold it): refused, nothing held", out.startswith("Refused") and held.count(TS) == 0 and reach(TS, n0) == [], out)
fresh(); stamp(TS, 5); n0 = len(pushes()); out = tres("trio-main", NOITEM); settle(); unstamp(TS)
check("8v: a quote of his words with no item named is no turn even while he is talking with the sibling (the item rule holds first): held, nothing pushed", out.startswith("held for trio-side's next turn") and reach(TS, n0) == [] and held.count(TS) == 1, out)
fresh(); n0 = len(pushes()); n = recp(WORDS, key=TRK, kind="message", who="trio-main (cccccccc…)"); res = act2(n, "trio-side", key=TRK)
check("8w: the router, an item of his named: the sibling rule holds it (ruled held, unmarked, the reason is the quoted words and does not say no item of his was named), no turn, nothing to the builder", res["ruling"] == "held" and res["marked"] is False and "quotes the owner's words" in str(res.get("reason", "")) + str(res)
      and "names no open item of his" not in str(res.get("reason", "")) and "names no open item of his" not in str(res)
      and reach(TS, n0) == [] and reach(TX, n0) == [] and held.count(TS) == 1, (res, pushes()[n0:]))
fresh(); n0 = len(pushes()); n = recp(NOITEM, key=TRK, kind="message", who="trio-main (cccccccc…)"); res = act2(n, "trio-side", key=TRK)
check("8x: the router, no item of his named: the message needs nobody, so it is a front agent's word to a peer: held unmarked, no turn, nothing to the builder", res["ruling"] == "held" and res["marked"] is False and reach(TS, n0) == [] and reach(TX, n0) == [] and held.count(TS) == 1
      and "quotes the owner's words" not in str(res), (res, pushes()[n0:]))
fresh(); n0 = len(pushes()); n = recp(NOWORDS, key=TRK, kind="message", who="trio-main (cccccccc…)"); res = act2(n, "trio-side", key=TRK)
check("8y: the router, an item of his named and no words: not held (to the builder or archived as before), the sibling gets nothing", res["ruling"] != "held" and held.count(TS) == 0 and reach(TS, n0) == [], (res, pushes()[n0:]))

# ---- 6. the text
docs = {p: (pathlib.Path(STACK) / "docs" / p).read_text() for p in ("router.md", "handoffs.md")}
tt = (pathlib.Path(STACK) / "stackshot/web/tools/text/message.md").read_text()
check("6a: docs/router.md says the router marks a pass only for a need of the person, and what goes where otherwise", "background agent" in docs["router.md"] and "_must_see" in docs["router.md"] and "is not marked" in docs["router.md"], "")
check("6b: docs/handoffs.md says the router marks a pass to a front agent only for a real need of the person", "marked only for a real need" in docs["handoffs.md"], "")
check("6d: the message tool's text says a marked message must name an open item of his and what happens when it names none", "an open item of his" in tt and "held for the agent's next turn and starts none" in tt, tt[:200])
check("6e: docs/router.md says a session's message needs him only by naming an open item of his, by the message tool's reader", "names an open item of his" in docs["router.md"] and "`front_turn.his_items`" in docs["router.md"], "")
check("6f: …that a notice that is no session's message keeps the decision-only reading, and that an item he asked the agent to tell him about counts", "does not widen to an item whose step is his" in docs["router.md"] and "(its `tell_him`)" in docs["router.md"]
      and "or whose step is his. An audit" not in docs["router.md"], "")
check("6g: the docs and the message tool's text say both rules: the item must be named (an open item of his), and a sibling front agent's quoted words (Acked-by) hold it for the next turn", "The two rules compose" in docs["handoffs.md"] and "Acked-by" in docs["handoffs.md"]
      and "an open item of his" in tt and "Acked-by" in tt and "held for its next turn" in tt, "")
check("6c: the message tool's text says what a front agent hears and where the rest goes", "background agent" in tt and "board item" in tt, tt[:200])

# ---- 7. a refused message call is logged with its target, the refusal's kind and its text (service/messaging.py Refused, core/call_log.py, web/middleware.py _RefusalLog)
import contextlib, io, types
from stackshot.core import call_log as _CL
from stackshot.web import middleware as _wmw
def call_rows(): return list(_CL.read(0, time.time() + 60))
def logged(to, text, sender, name="message", **kw):
    """A message call as the tool makes it, run through the server's refusal log → (the call log's new row, the ToolError it ended in or None). The log line on stderr is swallowed."""
    n_ = len(call_rows())
    async def nxt(ctx): return _messaging._message(to, text, sender, **kw)
    ctx = types.SimpleNamespace(message=types.SimpleNamespace(name=name, arguments={"to": to, "text": text, "sender": sender}))
    err = None
    with contextlib.redirect_stderr(io.StringIO()):
        try: asyncio.run(_wmw._RefusalLog().on_call_tool(ctx, nxt))
        except ToolError as e: err = e
    new = call_rows()[n_:]
    return (new[-1] if new else None), err
def site(name, kind, to, text, sender, **kw):
    """One refusal site: the call is refused with `kind`, and the row keeps the target as written, that kind, the sender, the refusal's own text and the message as a delivered row keeps it (a bare id written as shown)."""
    row, err = logged(to, text, sender, **kw)
    body = _service_store._shown_ids(text.strip())
    want_text = body if len(body) <= _CL.TEXT_MAX else body[:_CL.TEXT_MAX - 1].rstrip() + "…"
    check(f"7 {name}: refused as `{kind}`, the row keeps the target, the kind, the sender and the text",
          err is not None and getattr(err, "kind", "") == kind and row is not None and row["ok"] is False and row["tool"] == "message" and row.get("kind") == kind and row.get("to", "") == to.strip()[:80] and row["sender"] == sender
          and " ".join(str(err).split())[:100] == row["why"][:100] and row.get("text", "") == want_text and row["item"] == "",
          (kind, getattr(err, "kind", None), err, row))
    return row
fresh(); no_log(); unstamp(A); n0 = len(pushes())
site("no sender", "no-sender", FRONT, "a note", "")
site("no target", "no-target", "", "a note", "home-beta")
row = site("empty message", "empty-message", FRONT, "   \n ", "home-beta")
check("7 empty message: the row has no text field (nothing was said)", row is not None and "text" not in row, row)
row = site("message too long", "message-too-long", FRONT, "x" * 4100, "home-beta")
check("7 message too long: the text is kept up to the message limit and clipped with an ellipsis", row is not None and len(row["text"]) == _CL.TEXT_MAX and row["text"].endswith("…") and _CL.TEXT_MAX == 4000, row and len(row.get("text", "")))
site("question from the person", "question-from-owner", BACK, "is it done?", "Oliver", question=True)
site("question and fyi", "question-with-fyi", BACK, "is it done?", "home-beta", question=True, fyi=True)
site("page key that names no page", "unknown-page-key", "projects/nowhere", "hello there", "home-beta")
site("name no heartbeat has", "no-session", "nobody-here-at-all", "hello there", "home-beta")
site("transcript id no machine has", "unknown-transcript-id", "12345678-1234-4234-8234-123456789012", "hello there", "home-beta")
_keeper = telling.stand_in_keeper
telling.stand_in_keeper = lambda *a, **k: ""
try: site("page with no keeper", "no-keeper", KEY, "hello there", "home-beta")
finally: telling.stand_in_keeper = _keeper
# the front agent's gate, one site each
site("owner's unmarked message", "mark-not-first-line", FRONT, "a plain note from the person", "Oliver")
# the four sites that now handle the message keep their kind: the call goes through, and its row says `handled` with how (and still counts as refused when the hold is off and nothing can carry it)
def handled_site(name, kind, how, to, text, sender, **kw):
    row, err = logged(to, text, sender, **kw)
    check(f"7 {name}: handled as `{kind}` ({how}): the call went through, its row keeps the kind, the target, the sender and says `handled`",
          err is None and row is not None and row["ok"] is True and row["tool"] == "message" and row.get("kind") == kind and row.get("outcome") == "handled" and row.get("how") == how
          and row.get("to") == to and row.get("sender") == sender and "why" not in row, (kind, err, row))
    return row
fresh(); unstamp(A)
handled_site("builder's done note", "no-action-note-from-builder", "held", FRONT, "the PR is merged, the suites pass.", BACK)
handled_site("peer's done note", "no-action-note", "held", FRONT, "the PR is merged, the suites pass.", "home-beta")
handled_site("unmarked, not for the person", "unmarked-not-for-owner", "passed-on", FRONT, "can you look at the export page when you have a minute?", "home-beta")
handled_site("marked, says nothing is needed", "marked-no-action-phrase", "held", FRONT, mark() + "\nthe build is done, no action needed.", BACK)
handled_site("builder's done note naming an item", "marked-no-action-phrase", "written-on-item", FRONT, mark() + "\na1: the build is done. No action needed.", BACK)
handled_site("marked, the phrase inside a sentence", "marked-no-action-phrase", "judged-on-items", FRONT, mark() + "\nDecide whether the export ships on Friday, sending this as an fyi so it waits.", "home-beta")
# what the handling must not do: count a hold that was never filed, pass a message back to the agent that sent it, or take the person's own words for a note
held.clients_file().unlink(missing_ok=True)
row, err = logged(FRONT, "the PR is merged, the suites pass.", "home-beta")
check("7 a note whose hold could not be filed (the agent's hook cannot fetch held lines) is no handled call: it went through as `not passed on`, with no handled mark in its row", err is None and row is not None and row["ok"] is True and "outcome" not in row and "kind" not in row, row)
gate_open(); fresh(); n0 = len(pushes())
out = msg(FRONT, "can you look at the export page when you have a minute?", BACK); settle()
check("7 the project's background agent's own unmarked message to its front agent is held for the front agent's next turn, never passed back to itself", out.startswith("held for work-osprey-main's next turn") and reach(X, n0) == [] and reach(A, n0) == [] and held.count(A) == 1, out)
fresh(); unstamp(A); n0 = len(pushes())
out = msg(FRONT, mark() + "\na1: decide whether the export ships on Friday, sending this as an fyi so it waits.", "home-beta"); settle()
check("7 a marked message that uses a phrase inside a sentence is judged on the items it names, not delivered on the phrase's account: a1 is no item of his, so it is held and starts no turn, and the reply says so", out.startswith("held for work-osprey-main's next turn") and "must name an open item of his" in out and reach(A, n0) == [] and held.count(A) == 1, out)
fresh()
site("the person's own marked message that says nothing is needed", "marked-no-action-phrase", FRONT, mark() + "\nthe build is done, no action needed.", "Oliver")
_notices = _cfg.CFG["router"].get("hold_notices")
_cfg.CFG["router"]["hold_notices"] = False
try:
    site("builder's done note, hold off", "no-action-note-from-builder", FRONT, "the PR is merged, the suites pass.", BACK)
    site("peer's done note, hold off", "no-action-note", FRONT, "the PR is merged, the suites pass.", "home-beta")
    site("unmarked, not for the person, hold off and no builder to pass it to", "unmarked-not-for-owner", SOLO, "can you look at the export page when you have a minute?", "home-beta")
    site("marked, says nothing is needed, hold off", "marked-no-action-phrase", FRONT, mark() + "\nthe build is done, no action needed.", BACK)
    site("marked, no item of his, hold off", "marked-no-item-of-his", FRONT, mark() + "\nDecide whether the export ships on Friday.", "home-beta")
finally:
    if _notices is None: _cfg.CFG["router"].pop("hold_notices", None)
    else: _cfg.CFG["router"]["hold_notices"] = _notices
unstamp(A)
site("marked, names his item, no turn warranted", "marked-no-turn", FRONT, mark() + "\na16: sign the export form when you have a minute", "home-beta")
# the hold and the delivery
_front_fyi = telling.front_fyi
telling.front_fyi = lambda *a, **k: ("", "no hook")
try: site("fyi the front gate could not hold", "front-not-held", FRONT, "just so you know", "home-beta", fyi=True)
finally: telling.front_fyi = _front_fyi
_push = telling.PUSH
telling.PUSH = [sys.executable, "-c", "print('boom')"]
try: site("push that answers nothing deliverable", "delivery-failed", BACK, "hello there", "home-beta")
finally: telling.PUSH = _push
# the client route (a script's message): the same row, and a plain row for a call that went through
held.clients_file().unlink(missing_ok=True)
n_ = len(call_rows())
st_, body_ = _rt_client._client_post(MACH, "message", {"to": SOLO, "text": "the PR is merged, the export is next", "sender": "deploy-watch"})
new = call_rows()[n_:]
check("7 client route: a script's refused message is logged as the tool's is (sender, why, target, kind, text)", st_ == 400 and len(new) == 1 and new[0]["ok"] is False and new[0]["tool"] == "message" and new[0]["sender"] == "deploy-watch"
      and new[0]["kind"] == "script-fyi-not-held" and new[0]["to"] == SOLO and new[0]["text"] == "the PR is merged, the export is next" and new[0]["why"].startswith("Refused: " + SOLO), (st_, body_, new))
gate_open(); fresh()
n_ = len(call_rows())
st_, body_ = _rt_client._client_post(MACH, "message", {"to": BACK, "text": "a script reports", "sender": "deploy-watch"}); settle()
new = call_rows()[n_:]
check("7 client route: a script's message that went through is one plain row", st_ == 200 and new == [{"t": new[0]["t"], "tool": "message", "ok": True}] if new else False, (st_, body_, new))
st_, body_ = _rt_client._client_post(MACH, "message", {"to": "nobody-here-at-all", "text": "a script reports", "sender": "deploy-watch"})
new = call_rows()[n_:]
check("7 client route: …and a refusal elsewhere in the relay (no such session) is logged the same way", st_ == 400 and new[-1]["kind"] == "no-session" and new[-1]["to"] == "nobody-here-at-all" and new[-1]["text"] == "a script reports", (st_, new))
# what the log does not keep, and what a refusal from outside the relay is called
async def _plain(ctx): raise ToolError("Refused: from elsewhere")
ctx_ = types.SimpleNamespace(message=types.SimpleNamespace(name="message", arguments={"to": BACK, "text": "words", "sender": "home-beta"}))
buf_ = io.StringIO()
with contextlib.redirect_stderr(buf_):
    try: asyncio.run(_wmw._RefusalLog().on_call_tool(ctx_, _plain))
    except ToolError: pass
row = call_rows()[-1]
check("7 a refusal that is no relay site (a plain ToolError) is logged as `unclassified`, and the journal line on stderr carries no message text", row["kind"] == "unclassified" and row["text"] == "words" and "words" not in buf_.getvalue() and buf_.getvalue().startswith("refused: message item=- sender=home-beta"), (row, buf_.getvalue()))
check("7 every refusal site of the relay is a `Refused` with a kind of its own: no bare ToolError is raised in messaging.py", not re.findall(r"raise ToolError\(", pathlib.Path(STACK, "stackshot/service/messaging.py").read_text(encoding="utf-8")), None)
kinds_ = re.findall(r'raise Refused\("([a-z-]+)"', pathlib.Path(STACK, "stackshot/service/messaging.py").read_text(encoding="utf-8"))
check("7 …and no two sites share a kind", len(kinds_) == len(set(kinds_)) and len(kinds_) >= 23, kinds_)

# ---- 9. the replay: a week's front-gate refusals (57 message calls of the week before this change, kept here as neutral fixtures of the same shapes, no real names), run through the new gate and the server's own call log
# Per kind of the old refusal: K1 (15, the unmarked-message-to-a-front-agent rule that was already gone) goes through; K2 (17, unmarked, not for the person), K3 (7, a done, taken or no-action note) and K4 (2, a marked message with a no-action phrase) are handled and told;
# K5 (10, marked, names his item, no turn warranted), K6 (4, a page key that names no page) and K7 (2, an id no session has) stay refused, and the weekly count shows the first three as handled and these as refused.
from stackshot.tools import refusal_report as _RR
def replay(to, text, sender, **kw):
    """One message call through the server's refusal log → (the call log's new row, the refusal or None, the reply the sender got)."""
    n_ = len(call_rows()); box = {"reply": ""}
    async def nxt(ctx): box["reply"] = _messaging._message(to, text, sender, **kw); return box["reply"]
    ctx = types.SimpleNamespace(message=types.SimpleNamespace(name="message", arguments={"to": to, "text": text, "sender": sender}))
    err = None
    with contextlib.redirect_stderr(io.StringIO()):
        try: asyncio.run(_wmw._RefusalLog().on_call_tool(ctx, nxt))
        except ToolError as e: err = e
    new = call_rows()[n_:]
    return (new[-1] if new else None), err, box["reply"]
BUILD2, BUILD3, PEER_F = "trio-x", "duo-a", "duo-main"      # a background agent of another project, one of a third, and a front agent of another project
UNK = ("12345678-1234-4234-8234-123456789012", "87654321-4321-4321-8321-210987654321")
K1_TEXTS = ("can you look at the export page when you have a minute?", "result: the import fix is live on main. Anything else you need from this side?", "which of the two readings of the retention rule do you hold?",
            "the weekly numbers are ready, tell me where to put them", "the tool text for the audit verb now names the new flag", "thanks, taken. I will start on it after the next release",
            "heads up: the nightly job moved to 03:10, nothing breaks", "the lane check passed on both boxes, the report is in the usual place", "could you confirm the window for the migration?",
            "a short status of the release queue: two waiting, one running", "the doc fix went in, please read it when you can", "the sign-in page reads fine now")
K2_TEXTS = ("Thanks, taken: a builder is fixing the spec page and the two drop-ins, and I will tell you when they are in.", "two readings conflict, please settle between you before I build.",
            "can you ask the person whether the Friday date still holds?", "the vendor thread has a new reply, shall I answer it?", "I need a yes or no on the export format before the build starts.",
            "for your call: the cache can be cleared nightly or weekly, either is safe.", "please confirm the page names the new mover, and say if the step list is complete", "the check you asked for ran: green on both boxes.",
            "the release is waiting for a go on the migration order", "which project should the new component page hang under?", "a reminder that the retest is still open on the phone step",
            "can the front agent tell me if the colors on the card are final?", "the second reading is the one the rules support; do you agree?", "would you move the item to the builder or keep it?",
            "an answer to your question from last week: the quota is per box", "the staging box is free from noon, take it if you need it", "what do you want done with the old profile entries?")
K3_REAL = ("Closed: the old network profiles and the stale signatures are deleted on the second box. No reply needed.", "The table item you handed over is live (PR merged, suites green): the remaining choice is for the page keeper. No reply needed.")
K3_FYI = ("The answer reached the front agent only as an fyi notice, so it never opened a turn; the gap report below says where.", "Gap report: an fyi line is how the mover heard of it, and the mover had asked for a turn.",
          "Second gap report: the fyi path again, this time for a close, with the same effect on the mover.", "Third try at the same report, reworded: the notice was filed as an fyi when it asked for a decision.")
K3_PAREN = "For your call (nothing for Oliver): the inline path writes the finished mark only when the second pass ends, which it does not always do."
K4_TEXTS = (mark() + " a14: Decide whether the export ships on Friday; I describe the mechanism as an fyi that waits, which is the gap.", mark() + "\na1: the build is done. No action needed.")
K5_TEXTS = (" a16: sign the export form when you have a minute", " a14: pick one of the two options for the import", " a16: the retest has a step for you on the phone", " a14: one pick needed on the box move, with my recommendation",
            " a16: please check the new link opens the app", " a14: the cost is small, say yes or no", " a16: your step on the form is the last one", " a14: choose the order of the two releases",
            " a16: the second form needs a signature too", " a14: please pick the lane for the new sessions")
K6_KEYS = ("projects/alpha-core", "projects/alpha/core", "projects/nowhere-at-all", "projects/no-where")
ROWS = ([("K1", FRONT, t, BUILD2 if i % 4 else BUILD3, {"fyi": True} if i in (3, 7, 11) else {}) for i, t in enumerate(K1_TEXTS)]
        + [("K1", FRONT, "can you look at the vendor thread when you have a minute?", PEER_F, {}), ("K1", FRONT, "the notes page is tidy now, nothing else to say", PEER_F, {}), ("K1", FRONT, "which reading of the rule do you hold?", PEER_F, {})]
        + [("K2", FRONT, t, (BUILD2, BUILD3, "home-beta")[i % 3], {}) for i, t in enumerate(K2_TEXTS)]
        + [("K3", FRONT, t, BUILD2, {}) for t in K3_REAL] + [("K3", FRONT, t, PEER_F, {}) for t in K3_FYI] + [("K3", FRONT, K3_PAREN, BACK, {})]
        + [("K4", FRONT, K4_TEXTS[0], "home-beta", {"stamp": True}), ("K4", FRONT, K4_TEXTS[1], BACK, {})]
        + [("K5", FRONT, mark() + t, (BUILD2, BUILD3, "home-beta")[i % 3], {}) for i, t in enumerate(K5_TEXTS)]
        + [("K6", k, "the pages moved, a plain note for that project: please read the new page", BUILD2, {}) for k in K6_KEYS]
        + [("K7", u, "a reminder from the write-up check about the last turn", "write-up-check", {}) for u in UNK])
check("9 replay: the week's 57 refused message calls are here, K1 15, K2 17, K3 7, K4 2, K5 10, K6 4, K7 2", len(ROWS) == 57 and {k: sum(1 for r in ROWS if r[0] == k) for k in ("K1", "K2", "K3", "K4", "K5", "K6", "K7")} == {"K1": 15, "K2": 17, "K3": 7, "K4": 2, "K5": 10, "K6": 4, "K7": 2}, len(ROWS))
fresh(); no_log(); unstamp(A); gate_open()
out9 = {}
for kind_, to_, text_, sender_, kw_ in ROWS:
    kw_ = dict(kw_); st_ = kw_.pop("stamp", False)
    stamp(A, 1) if st_ else unstamp(A)
    n0 = len(pushes()); row_, err_, reply_ = replay(to_, text_, sender_, **kw_); settle()
    out9.setdefault(kind_, []).append((row_, err_, reply_, text_, to_, len(reach(A, n0)), len(reach(X, n0))))
unstamp(A)
ok_row = lambda r: r[0] is not None and r[1] is None and r[0]["ok"] is True
check("9 replay K1: the rule that is gone: every one of the 15 goes through now, to the project's background agent or held for the front agent's next turn, none starts a turn there and the front agent's pane got none",
      all(ok_row(r) and (r[2].startswith("Not for Oliver, so it went to work-osprey-x") or r[2].startswith("held for work-osprey-main's next turn")) and r[5] == 0 for r in out9["K1"]), [(r[2][:80], r[5]) for r in out9["K1"] if not ok_row(r)])
check("9 replay K2 (unmarked, not for the person): all 17 handled and told: passed to the project's background agent, the row says `handled`, the kind of the old refusal and `passed-on`, the reply says it did not reach the front agent and how to, and the front agent got none",
      all(ok_row(r) and r[0].get("outcome") == "handled" and r[0].get("kind") == "unmarked-not-for-owner" and r[0].get("how") == "passed-on" and r[2].startswith("Not for Oliver, so it went to work-osprey-x, the project's background agent, instead of work-osprey-main, which takes only what Oliver has to do and did not get it:")
          and r[2].endswith(f"To reach work-osprey-main, put {mark()} on the first line and name an open item of his.") and r[5] == 0 and r[6] == 1 for r in out9["K2"]), [(r[0], r[2][:100], r[5], r[6]) for r in out9["K2"] if not ok_row(r)])
real = out9["K3"][:2]; rest = out9["K3"][2:]
check("9 replay K3 (a done, taken or no-action note): the 2 real notes are handled and told: held for the front agent's next turn with no turn, the row says `handled`, the old kind and `held`, the reply says it is a note and where it is better written",
      all(ok_row(r) and r[0].get("outcome") == "handled" and r[0].get("kind") in ("no-action-note", "no-action-note-from-builder") and r[0].get("how") == "held" and r[2].startswith("held for work-osprey-main's next turn (") and "better written on the board item it concerns" in r[2] and r[5] == 0 for r in real), [(r[0], r[2][:120]) for r in real])
check("9 replay K3: …the 5 false hits (the word `fyi` inside prose, a phrase inside brackets) are no refusal any more: each goes through and the sender is told what happened (held for the next turn or passed on), no turn starts",
      all(ok_row(r) and (r[2].startswith("held for work-osprey-main's next turn") or r[2].startswith("Not for Oliver, so it went to work-osprey-x")) and r[5] == 0 for r in rest), [(r[0], r[2][:120]) for r in rest if not ok_row(r)])
k4a, k4b = out9["K4"]
check("9 replay K4 (marked, a no-action phrase): the phrase inside a sentence is no note, the message is judged on the items it names (here his open item and he is talking with the agent), delivered, the reply says why, the row says `handled` and `judged-on-items`",
      ok_row(k4a) and k4a[0].get("outcome") == "handled" and k4a[0].get("kind") == "marked-no-action-phrase" and k4a[0].get("how") == "judged-on-items" and k4a[2].startswith("delivered") and "inside a sentence, which is not read as saying nothing is needed from Oliver, so it was judged on the items it names." in k4a[2] and k4a[5] == 1, (k4a[0], k4a[2][:300]))
check("9 replay K4: …a background agent's marked report that says nothing is needed is written onto the item it names, no turn, the row says `handled` and `written-on-item`",
      ok_row(k4b) and k4b[0].get("outcome") == "handled" and k4b[0].get("kind") == "marked-no-action-phrase" and k4b[0].get("how") == "written-on-item" and k4b[2].startswith("Not delivered: written onto a1") and k4b[5] == 0, (k4b[0], k4b[2][:300]))
check("9 replay K5 (marked, his item, no turn warranted): unchanged, all 10 still refused as `marked-no-turn`, nothing delivered or held for the front agent",
      all(r[1] is not None and getattr(r[1], "kind", "") == "marked-no-turn" and r[0]["ok"] is False and r[0]["kind"] == "marked-no-turn" and "outcome" not in r[0] and r[5] == 0 for r in out9["K5"]), [(getattr(r[1], "kind", None), str(r[1])[:80]) for r in out9["K5"]])
check("9 replay K6 (a page key that names no page): unchanged, all 4 still refused as `unknown-page-key`", all(r[1] is not None and getattr(r[1], "kind", "") == "unknown-page-key" and r[0]["ok"] is False and r[0]["kind"] == "unknown-page-key" and "outcome" not in r[0] for r in out9["K6"]), [(getattr(r[1], "kind", None), str(r[1])[:80]) for r in out9["K6"]])
check("9 replay K7 (an id no session has): unchanged, both still refused as `unknown-transcript-id`", all(r[1] is not None and getattr(r[1], "kind", "") == "unknown-transcript-id" and r[0]["ok"] is False and r[0]["kind"] == "unknown-transcript-id" and "outcome" not in r[0] for r in out9["K7"]), [(getattr(r[1], "kind", None), str(r[1])[:80]) for r in out9["K7"]])
st9 = _RR.message_stats([r[0] for k in out9 for r in out9[k] if r[0] is not None])
check("9 replay: the weekly count of these 57 calls: 57 calls, 16 refused (K5 10, K6 4, K7 2), and the handled ones counted as handled and never as refused",
      st9["calls"] == 57 and st9["refused"] == 16 and dict(st9["kinds"]) == {"marked-no-turn": 10, "unknown-page-key": 4, "unknown-transcript-id": 2}
      and sum(st9["handled"].values()) >= 21 and st9["handled"][("unmarked-not-for-owner", "passed-on")] >= 17 and st9["handled"][("marked-no-action-phrase", "judged-on-items")] == 1 and st9["handled"][("marked-no-action-phrase", "written-on-item")] == 1, (st9["calls"], st9["refused"], dict(st9["kinds"]), dict(st9["handled"])))

# ---- 10. the review of this change: a real ask beside a no-action phrase, the forms of a note, the pass-on's side effects, a sibling builder, and the cases the mutants showed untested
def delivered_ask(out, n0, phrase, items=("a14",)):
    """A marked real ask that carries a no-action phrase: delivered to the front agent, the reply saying the phrase was left out because of the item of his it names."""
    return (out.startswith("delivered") and len(reach(A, n0)) == 1 and held.count(A) == 0
            and out.endswith(f"Its text also says {phrase!r}, which was left out because the message names {', '.join(items)}, an open item of Oliver's, so it was taken as a request."))
ASKS = (("10a1: a decision with an FYI after it", "a14: Decide whether the export ships on Friday. FYI option B costs 40 USD.", "FYI"),
        ("10a2: …a no-action sentence after it", "a14: Decide whether the export ships on Friday. No action needed on option C.", "No action needed"),
        ("10a3: …a phrase first, the ask after it", "a14: no decision needed from you but I need your pick between A and B", "no decision needed"),
        ("10a4: …a phrase leading the sentence of the ask", "a14: for the record, I need your decision on Friday's export.", "for the record"),
        ("10a5: …the step of his (a16) beside a phrase", "a16: sign the export form when you have a minute. No action needed on the rest.", "No action needed"))
for name_, text_, phrase_ in ASKS:
    for who_ in ("home-beta", BACK):
        fresh(); no_log(); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, mark() + "\n" + text_, who_); settle(); unstamp(A)
        check(f"{name_} ({who_}): a marked ask that names an open item of his is delivered whatever phrase it carries, the reply saying the phrase was left out", delivered_ask(out, n0, phrase_, ("a16",) if "a16" in text_ else ("a14",)), (out, pushes()[n0:]))
fresh(); stamp(A, 5); row_, err_ = logged(FRONT, mark() + "\n" + ASKS[0][1], "home-beta"); unstamp(A); settle()
check("10a6: …and the call log counts it as handled (`marked-no-action-phrase`, `judged-on-items`), not as a refusal", err_ is None and row_ is not None and row_["ok"] is True and row_.get("kind") == "marked-no-action-phrase" and row_.get("outcome") == "handled" and row_.get("how") == "judged-on-items", row_)
fresh(); unstamp(A); n0 = len(pushes()); out = msg(FRONT, mark() + "\n" + ASKS[0][1], "home-beta"); settle()
check("10a7: …with him away it is the old no-turn refusal of a marked message (the phrase makes no difference: nothing is held, nothing delivered)", out.startswith("Refused") and "starts no turn" in out and reach(A, n0) == [] and held.count(A) == 0, out)
# a marked note that names none is a note: held, with a reply that says what to do (name the item or take the phrase out), never the line about the mark it already has
fresh(); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, mark() + "\na1: Decide whether the export ships on Friday. FYI option B costs 40 USD.", "home-beta"); settle(); unstamp(A)
check("10b1: a marked message whose only item is none of his (a1), with a phrase, is held as a note, the reply saying it names no open item of his, to name one or take the phrase out, and never to put the mark on its first line",
      out.startswith("held for work-osprey-main's next turn") and "names no open item of his" in out and "take the no-action phrase out" in out and "plain id" in out and "on its first line" not in out and "send it again" not in out and reach(A, n0) == [] and held.count(A) == 1, (out, pushes()[n0:]))
fresh(); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, mark() + "\nDecide whether the export ships on Friday. FYI option B costs 40 USD.", "home-beta"); settle(); unstamp(A)
check("10b2: …and one that names no item at all", out.startswith("held for work-osprey-main's next turn") and "names no open item of his" in out and "on its first line" not in out and reach(A, n0) == [] and held.count(A) == 1, out)
fresh(); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, mark() + "\na15: Decide whether the export ships on Friday. FYI option B costs 40 USD.", "home-beta"); settle(); unstamp(A)
check("10b3: …and one that names only a closed item (a15 needs a decision but is closed): a closed item is no item of his", out.startswith("held for work-osprey-main's next turn") and held.count(A) == 1 and reach(A, n0) == [], out)
fresh(); n0 = len(pushes()); out = msg(FRONT, mark() + "\na14: Decide whether the export ships on Friday. FYI option B costs 40 USD.", "Oliver"); settle()
check("10b4: his own marked message with a phrase is refused as before (the phrase is no excuse for a note of his own)", out.startswith("Refused") and "says nothing is needed from him" in out and reach(A, n0) == [] and held.count(A) == 0, out)
fresh(); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, mark() + "\na1: Decide whether the export ships on Friday, sending this as an fyi so it waits.", "home-beta"); settle(); unstamp(A)
check("10b5: …and the phrase inside a sentence with no item of his is the old hold, with no mention of a phrase to take out", out.startswith("held for work-osprey-main's next turn") and "must name an open item of his" in out and "take the no-action phrase out" not in out, out)
_front_turn_real_his = _front_turn_mod.his_items
_front_turn_mod.his_items = _boom_his
fresh(); stamp(A, 5); n0 = len(pushes())
try: out = msg(FRONT, mark() + "\na14: Decide whether the export ships on Friday. FYI option B costs 40 USD.", "home-beta"); settle()
finally: _front_turn_mod.his_items = _front_turn_real_his; unstamp(A)
check("10b6: a reader of his items that fails counts as none: the marked note is held, never delivered on a guess", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [] and held.count(A) == 1, out)

# the forms of a note: the common ways a sender writes it, and the ones that are no note
FORMS = (("a clause after a comma, with its tail", "the build is live, no action needed from you", "no action needed"), ("a clause after a semicolon, with the owner's name", "merged; no action needed from Oliver", "no action needed"),
         ("a clause after a dash, after a bracket", "a1 (merged) " + chr(0x2014) + " no action needed from you", "no action needed"), ("a tail 'on your part'", "merged, no action needed on your part.", "no action needed"),
         ("bold", "**FYI** the build is live", "FYI"), ("emphasis and a colon", "_FYI_: the build is live", "FYI"), ("a code span", "`FYI` the build is live", "FYI"), ("a bullet", chr(0x2022) + " FYI the build is live", "FYI"),
         ("an en dash", chr(0x2013) + " FYI the build is live", "FYI"), ("a number in brackets", "(1) FYI the build is live", "FYI"), ("a number and a bracket", "1) FYI the build is live", "FYI"), ("a number and a stop", "2. no reply needed", "no reply needed"),
         ("an item id, a dash", "a12 - FYI the build is live", "FYI"), ("an item id in the form with a hash", "x" + chr(35) + "12 - FYI the build is live", "FYI"),
         ("a curly apostrophe", "it" + chr(0x2019) + "s an FYI", "FYI"), ("a second line, bold", "the build is live\n**No action needed**", "No action needed"), ("a bullet on a later line", "done\n" + chr(0x2022) + " for the record", "for the record"))
for name_, text_, phrase_ in FORMS:
    check(f"10c1: the phrase finder reads {name_} as a note ({text_!r})", _own(text_) == [phrase_], _own(text_))
for name_, text_ in (("asked", "no action needed?"), ("a question that quotes it", 'Why does the page say "no action needed" here?'), ("a question that holds it", "Is it true that no action needed from you?"), ("followed on", "the build is live, no action needed from you until Friday"),
                     ("followed on, a condition", "merged; no action needed from Oliver unless the suite fails"), ("negated", "it is not true that no action needed"), ("not done", "the export is not done, nothing is blocked"), ("a word inside another", "set my_fyi_mode and the for_the_record_flag"),
                     ("in a quote block", "> FYI the build is live"), ("inside a code span", "set the mode to `fyi` for this"), ("a curly quote", chr(0x201C) + "no action needed" + chr(0x201D)), ("inside the sentence", "the export, sent as an fyi so it waits, is late")):
    check(f"10c2: the phrase finder does not read {name_} as a note ({text_!r})", _own(text_) == [], _own(text_))
check("10c3: _without_no_action takes the tail 'from you' out with its phrase (it would read as somebody named to act), and keeps the rest", _messaging._without_no_action("merged, no action needed from you.").replace(" ", "") == "merged,.", repr(_messaging._without_no_action("merged, no action needed from you.")))
for name_, text_ in (("a clause with its tail", "a1: the build is live, no action needed from you"), ("a clause with the owner's name", "a1: merged; no action needed from Oliver"), ("bold at the start", "**FYI** a1 is merged"), ("a code span at the start", "`FYI` a1 is merged"),
                     ("a bullet", chr(0x2022) + " FYI a1 is merged"), ("a number", "(1) FYI a1 is merged"), ("a bracket and a dash", "a1 (merged) " + chr(0x2014) + " no action needed from you"), ("a curly apostrophe", "a1 is merged, it" + chr(0x2019) + "s an FYI")):
    fresh(); n0 = len(pushes()); out = msg(FRONT, mark() + "\n" + text_, BACK); settle()
    check(f"10c4: a background agent's marked report in the form of {name_} is written onto the item, not delivered: no turn", out.startswith("Not delivered: written onto a1") and reach(A, n0) == [] and held.count(A) == 0, (out, pushes()[n0:]))
    fresh(); n0 = len(pushes()); out = msg(FRONT, mark() + "\n" + text_.replace("a1", "the build"), "home-beta"); settle()
    check(f"10c5: …and a session's, naming no item, is held as a note, never a turn", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [] and held.count(A) == 1, (out, pushes()[n0:]))
for name_, text_ in (("asked", "a16: Please sign the export form. No action needed?"), ("quoted", 'a16: Please sign the export form; the page says "no action needed", which is wrong.'), ("followed on", "a16: Please sign the export form, no action needed from you until the form is open."),
                     ("not done", "a16: the export form is not done and nothing is blocked, please sign it")):
    fresh(); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, mark() + "\n" + text_, "home-beta"); settle(); unstamp(A)
    check(f"10c6: a marked ask that is no note ({name_}) is delivered, as before: it names an item of his and he is there", out.startswith("delivered") and len(reach(A, n0)) == 1 and held.count(A) == 0, (out, pushes()[n0:]))
fresh(); n0 = len(pushes()); out = msg(FRONT, "can you check whether no action needed from you is the right reading of the export page?", "home-beta"); settle()
check("10c7: an unmarked question that holds the words is no note: passed to the background agent", went_to(out, n0), out)

# the pass-on is no hand-over: it names the builder in no item's needs and tells no mover
fresh(); n0 = len(pushes()); before3 = (T / "store/a/3.json").read_text(); out = msg(FRONT, "a3 depends on the export page, can you look when you have a minute?", "home-beta"); settle()
check("10d1: a pass to the background agent of a message that names an open item does not name the agent in the item's needs, and writes nothing on the item (needs, mover and file as they were)",
      went_to(out, n0) and (T / "store/a/3.json").read_text() == before3 and "named" not in out and not rd(3)["metadata"].get("needs") and rd(3)["metadata"].get("mover") == X, (out, rd(3)["metadata"]))
check("10d2: …and nothing else was sent: the one push is the message to the builder, no notice to a mover", len(pushes()[n0:]) == 1 and pushes()[n0][0] in ids(X), pushes()[n0:])
fresh(); n0 = len(pushes()); out = msg(BACK, "a9: the export page is yours to build", "home-beta"); settle()
check("10d3: a hand-over message sent to the background agent itself still names it on the item (the pass-on is the only message that does not)", out.startswith("delivered") and "(named work-osprey-x in a9's needs" in out or "(did not name work-osprey-x in a9's needs" in out, out)
fresh(); no_log(); n0 = len(pushes()); out = msg(FRONT, "can you look at the export page?", "home-beta", question=True); settle()
row_ = [x for x in mlog() if x.get("to") == BACK and "export page" in x.get("text", "")]
check("10d4: the question mark of a sender (question=true) is kept on the pass-on's row to the builder, as on a direct message", went_to(out, n0) and len(row_) == 1 and row_[0].get("question") is True, (out, row_))

# a sibling background agent is no address for the pass: it is held for the front agent like the builder's own message
fresh(); n0 = len(pushes()); out = msg(DUOM, "can you look at the export page?", DUOB); settle()
check("10e1: a message from a background agent of the project that is not the one the relay picks (duo-b, duo-a is the pick) is held for the front agent's next turn, not passed across to its sibling",
      out.startswith("held for duo-main's next turn") and "is a background agent of projects/duo" in out and reach(DA, n0) == [] and reach(DB, n0) == [] and held.count(M) == 1, (out, pushes()[n0:]))
fresh(); n0 = len(pushes()); out = msg(DUOM, "can you look at the export page?", DUOA); settle()
check("10e2: …and the one the relay picks (duo-a) is held as before: never passed back to itself", out.startswith("held for duo-main's next turn") and "cannot go back to it" in out and reach(DA, n0) == [] and held.count(M) == 1, out)
_cfg.CFG["router"]["hold_notices"] = False
fresh(); n0 = len(pushes()); out = msg(DUOM, "can you look at the export page?", DUOB); settle()
check("10e3: with the hold off, a sibling's message is refused (nothing holds it), not passed across", out.startswith("Refused") and "not for Oliver" in out and reach(DA, n0) == [] and held.count(M) == 0, out)
fresh(); n0 = len(pushes()); out = msg(FRONT, "can you look at the export page?", BACK); settle()
check("10e4: …the background agent's own message to its front agent is refused, never passed back to itself (the guard on the sender holds with the hold off)", out.startswith("Refused") and "not for Oliver" in out and reach(X, n0) == [] and reach(A, n0) == [], (out, pushes()[n0:]))
fresh(); n0 = len(pushes()); out = msg(FRONT, "can you look at the export page when you have a minute?", "home-beta"); settle()
check("10e5: …while a message from anyone else is still passed on with the hold off (the pass needs no hold: the agent takes it)", went_to(out, n0), (out, pushes()[n0:]))
fresh(); n0 = len(pushes()); out = msg(SOLO, "can you look at the export page?", "home-beta"); settle()
check("10e6: …and with no background agent to pass it to, the hold off leaves the old refusal", out.startswith("Refused") and held.count(E) == 0, out)
_cfg.CFG["router"].pop("hold_notices")

# a pass that fails: held for the front agent (the sender's push could not go out), the old refusal when nothing can hold it; a push that timed out may have gone out, so it is not held too
_push_real = telling.PUSH
telling.PUSH = [sys.executable, "-c", "print('boom')"]
try:
    fresh(); n0 = len(pushes()); out = msg(FRONT, "can you look at the export page when you have a minute?", "home-beta"); settle()
    check("10f1: a pass whose delivery fails is held for the front agent's next turn, the reply saying the builder could not take it", out.startswith("held for work-osprey-main's next turn") and "could not take it" in out and held.count(A) == 1, out)
    row_, err_ = logged(FRONT, "can you look at the export page when you have a minute?", "home-beta")
    check("10f2: …and the call log counts it as handled (`unmarked-not-for-owner`, `held`)", err_ is None and row_ is not None and row_.get("outcome") == "handled" and row_.get("kind") == "unmarked-not-for-owner" and row_.get("how") == "held", (row_, err_))
    _cfg.CFG["router"]["hold_notices"] = False
    fresh(); out = msg(FRONT, "can you look at the export page when you have a minute?", "home-beta"); settle()
    row_, err_ = logged(FRONT, "can you look at the export page when you have a minute?", "home-beta")
    check("10f3: …with the hold off the refusal stands, as the old gate worded it (the message goes to the builder, put the mark on the first line), and it is a refusal in the log", out.startswith("Refused: work-osprey-main is a front agent") and "message(to='work-osprey-x'" in out and held.count(A) == 0
          and err_ is not None and getattr(err_, "kind", "") == "unmarked-not-for-owner" and row_["ok"] is False, (out, err_))
    _cfg.CFG["router"].pop("hold_notices")
finally:
    telling.PUSH = _push_real
_run_real = _messaging.subprocess.run
def _timeout_run(*a, **k): raise _messaging.subprocess.TimeoutExpired(a[0] if a else "push", 110)
_messaging.subprocess.run = _timeout_run
try:
    fresh(); n0 = len(pushes()); out = msg(FRONT, "can you look at the export page when you have a minute?", "home-beta"); settle()
finally:
    _messaging.subprocess.run = _run_real
check("10f4: a push that timed out may have gone out: the failure goes back to the sender as it is, and nothing is held for the front agent too (no double delivery)", out.startswith("Delivery failed: timed out") and held.count(A) == 0, out)

# the reply's notes are set off from what comes before
fresh(); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, mark() + "\n" + REQ, "home-beta"); settle(); unstamp(A)
check("10g1: a note at the end of a reply that does not end in a stop follows a full stop and a space", ". Its text uses 'fyi' inside a sentence" in out and out.endswith("so it was judged on the items it names."), out)
_body_real = _messaging._message_body
_messaging._message_body = lambda *a, **k: (_messaging._handled("marked-no-action-phrase", "judged-on-items", "A note without a stop"), "held for x's next turn.")[1]
try: out = _messaging._message(FRONT, "words", "home-beta")
finally: _messaging._message_body = _body_real
check("10g2: …a note with no full stop of its own gets one, and a reply that ends in one is followed by a space only", out == "held for x's next turn. A note without a stop.", out)

# the hold files a History line on the item a held note names
fresh(); before1 = json.dumps(rd(1)["metadata"].get("front_quiet", {})); n0 = len(pushes()); out = msg(FRONT, "a1: the zebra export build is merged, FYI.", "home-beta"); settle()
check("10h1: a held note that names an open item leaves a History line on it (the board keeps the news whether or not the pane hears it)", held_note(out, n0) and "zebra export build" in json.dumps(rd(1)["metadata"].get("front_quiet", {})) and json.dumps(rd(1)["metadata"].get("front_quiet", {})) != before1, (out, rd(1)["metadata"].get("front_quiet")))
fresh(); stamp(A, 5); n0 = len(pushes()); out = msg(FRONT, mark() + "\na1: the quokka export is merged, FYI.", "home-beta"); settle(); unstamp(A)
check("10h2: …a marked note naming an item that is none of his is held and writes its History line too", out.startswith("held for work-osprey-main's next turn") and "quokka export" in json.dumps(rd(1)["metadata"].get("front_quiet", {})), (out, rd(1)["metadata"].get("front_quiet")))

# a script's message through the real client route is counted as handled, with its sender and target, as the tool's is
held.clients_file().unlink(missing_ok=True); gate_open(); fresh(); n_ = len(call_rows())
st_, body_ = _rt_client._client_post(MACH, "message", {"to": FRONT, "text": "can you look at the export page when you have a minute?", "sender": "deploy-watch"}); settle()
new = call_rows()[n_:]
check("10i1: a script's unmarked message to a front agent, through the client route, is passed on and answers 200 with the pass-on's line", st_ == 200 and str(body_.get("result", "")).startswith("Not for Oliver, so it went to work-osprey-x"), (st_, body_))
check("10i2: …and its one row is a handled call: the sender, the target, the kind of the refusal it replaced, `handled` and `passed-on`", len(new) == 1 and new[0].get("ok") is True and new[0].get("tool") == "message" and new[0].get("sender") == "deploy-watch" and new[0].get("to") == FRONT
      and new[0].get("kind") == "unmarked-not-for-owner" and new[0].get("outcome") == "handled" and new[0].get("how") == "passed-on", new)
n_ = len(call_rows())
st_, body_ = _rt_client._client_post(MACH, "message", {"to": FRONT, "text": "the PR is merged, the suites pass.", "sender": "deploy-watch"}); settle()
new = call_rows()[n_:]
check("10i3: …a script's note is held for the front agent and counted the same way (`held`)", st_ == 200 and len(new) == 1 and new[0].get("outcome") == "handled" and new[0].get("how") == "held" and new[0].get("kind") == "no-action-note", (st_, body_, new))
fresh()

fresh()
print(f"{len(ran) - len(fails)}/{len(ran)} checks passed" + ("" if not fails else f"; FAILED: {len(fails)}"))
sys.exit(1 if fails else 0)
