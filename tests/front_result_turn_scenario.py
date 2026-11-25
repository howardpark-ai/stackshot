"""Scenario test for the result turn: a message from a session a listed front agent handed work to starts the agent's turn, however late it arrives
- fixture data, no live store, no network, no server.

`[front] result_turn_agents` (empty by default) lists front agents; for one of them a message by name (the message tool, `messaging._gate_front` -> `result_turn`) or a router pass to it (`router_live._front_result_turn`, hook `front_result`
-> `messaging.router_result`) from a session it handed work to is delivered as a turn, with the person there or away, marked or not, past the builder-report and status-shape holds, as a line of kind `exempt` (the pane's digest never files it).
Handed work = the agent wrote to that session within `[front] result_turn_hours` (any message that reached it), or the message names an open item the session moves that the agent made (owner) or is the contact of.

Covers:
  0. The three keys: defaults (no agent, 24 hours, 6 an hour), a value of the wrong kind reads as the default and `config.notes` names it.
  1. (a) The message tool, a row of the log from the agent to the sender: a status-shaped message from it is a turn with the person away, and while he is there, marked or not, to a builder and to any other session, the line pushed with the kind exempt and the log row marked `result_turn`;
     a row older than the window, a row that was held (reached nobody) or none is no hand-over; with no agent listed the same messages are held as before.
  2. (b) No row: the message names an open item the sender moves (mover, or in needs) that the agent made or is the contact of; an item of nobody's, one the sender does not move, a closed one, is no hand-over.
  3. (c) A stranger, a script, a peer front agent, the person, an agent not in the list, `fyi=true` (marked or not): not a turn.
  4. (d) The cap: at most `result_turn_cap_per_hour` turns per sender and agent in an hour, the next one held as before with a log line; another sender is not held by it; a row older than an hour does not count; 0 turns the case off.
  5. (e) The router: a pass of such a message to the listed agent is delivered, unmarked, kind exempt, with the person away or there; the same refusals; the cap; a retry counts once; a pass to an agent not listed is ruled as before.
  6. (f) The digest of queued lines (`messaging.digest_fyi`) never files a result turn: the kind the push carried is exempt.
  7. (g) With no agent listed (the default) none of it applies: the existing suites front_hold, front_turn and front_quiet run unchanged.

    tests/run-suite front_result_turn   -> exit 0 / 1"""
import asyncio, datetime, importlib, inspect, json, logging, os, pathlib, re, sys, threading, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="resultturn-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml = _instance.set_person(toml)
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                 (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'),
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
item(30, owner=A, needs=["decision"], project="projects/trio")      # an open item of his in another project (trio): a front agent of alpha never writes onto it
item(31, owner=A, needs=["decision"], project="projects/trio")      # a second one, for the trio front agents' own writes
(T / "store/next-id").write_text("100")
push_log = T / "push.log"
kind_log = T / "kinds.log"
(T / "fakepush.py").write_text(f"import sys, json, os\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nopen({str(push_log)!r}, 'a').write(json.dumps(a) + '\\n')\nopen({str(kind_log)!r}, 'a').write(os.environ.get('ANCHOR_PUSH_KIND', '') + '\\n')\nprint('delivered → ' + a[0])\n")
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
def qlog(i):
    """The History lines written onto an item (metadata.front_quiet.log), oldest first: what a write of a message onto the item leaves on it."""
    return [x["text"] for x in ((rd(i)["metadata"].get("front_quiet") or {}).get("log") or [])]
def history(i):
    """The item's History as the board shows it, from two stubbed revisions (the item before its front_quiet log and as it is now): the lines the board prints as `stackshot: <line>`."""
    from stackshot.web.ui import render as ui_render
    now_ = rd(i)
    before = json.loads(json.dumps(now_)); before["metadata"].pop("front_quiet", None)
    bd = ui_render.Board(str(T / "store")); row = bd.item(f"a{i}")
    bd.item_versions = lambda r: [(now0 - 500, before), (now0 - 400, now_)]
    evs, _more = bd.item_events(row)
    return [x[2] for x in evs if x[1] == "front"]
def why(fn):
    try: fn(); return ""
    except ToolError as e: return str(e)
def fresh():
    """Empty the held store and the push log between scenarios."""
    for p in held.dir_().glob("*.jsonl"): p.unlink()
    push_log.unlink(missing_ok=True); kind_log.unlink(missing_ok=True)

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

import io, contextlib
from stackshot.core import config as _config
KINDS = lambda: [l for l in kind_log.read_text().split("\n")[:-1]] if kind_log.exists() else []
def listed(*names, **kw):
    """Set `[front]` as an instance would: the listed agents, and any other key."""
    if names or kw: _cfg.CFG["front"] = {"result_turn_agents": list(names), **kw}
    else: _cfg.CFG.pop("front", None)
def reached(session, n0): return reach(session, n0)
def result_rows(): return [d for d in mlog() if d.get("result_turn") is True]
DOCS = "work-osprey-docs"; STRANGER = "home-beta"; TRIOX = "trio-x"; TRIOM = "trio-main"
STATUS = "the PR is merged, the suites pass."
def delivered_turn(out, n0, ref=A, kinds_from=0):
    """The message went through as a turn: the reply says delivered, one push to the agent, nothing held for it, the line pushed with the kind exempt."""
    got = reach(ref, n0)
    return out.startswith("delivered") and len(got) == 1 and held.count(ref) == 0 and KINDS()[-1:] == ["exempt"]
def not_a_turn(n0, ref=A): return reach(ref, n0) == []
fresh(); no_log(); unstamp(A)

# ---- 0. the keys
listed()
check("0a: no [front] table: no agent is listed, 24 hours, 6 an hour", _front_turn_mod.result_turn_agents() == [] and _front_turn_mod.result_turn_hours() == 24.0 and _front_turn_mod.result_turn_cap_per_hour() == 6, None)
listed(FRONT, "  Other-Agent ", 5, "", result_turn_hours=2, result_turn_cap_per_hour=3)
check("0b: the keys are read: names case-folded and trimmed (a name that is no string or is empty left out), hours, cap", _front_turn_mod.result_turn_agents() == [FRONT, "other-agent"] and _front_turn_mod.result_turn_hours() == 2.0 and _front_turn_mod.result_turn_cap_per_hour() == 3,
      (_front_turn_mod.result_turn_agents(), _front_turn_mod.result_turn_hours(), _front_turn_mod.result_turn_cap_per_hour()))
listed(result_turn_hours=-1, result_turn_cap_per_hour=-2); _cfg.CFG["front"]["result_turn_agents"] = "work-osprey-main"
check("0c: a value of the wrong kind reads as the default (no agent for a string, 24 hours, 6)", _front_turn_mod.result_turn_agents() == [] and _front_turn_mod.result_turn_hours() == 24.0 and _front_turn_mod.result_turn_cap_per_hour() == 6, None)
bad = _config.notes({**_cfg.CFG})
check("0d: …and each is named in the config notes", sum(1 for x in bad if x.startswith("[front] ")) == 3 and any("result_turn_agents" in x for x in bad) and any("result_turn_hours" in x for x in bad) and any("result_turn_cap_per_hour" in x for x in bad), bad)
listed(FRONT, result_turn_hours=24, result_turn_cap_per_hour=6)
check("0e: a good table has no note", not [x for x in _config.notes({**_cfg.CFG}) if x.startswith("[front] ")], None)
listed(); fresh()

# ---- 1. (a) the agent wrote to the sender
for who_, ref_ in (("a builder", BACK), ("another session", STRANGER)):
    for presence in ("away", "there"):
        for marked in (False, True):
            fresh(); no_log(); listed(FRONT); log_row(FRONT, ref_, 60, "go and build the export", question=False)
            (stamp(A, 5) if presence == "there" else unstamp(A)); n0 = len(pushes())
            out = msg(FRONT, (mark() + "\n" if marked else "") + STATUS, ref_); settle(); unstamp(A)
            check(f"1a: a status-shaped message from {who_} the agent wrote to an hour ago is a turn with the person {presence}{', marked' if marked else ''}", delivered_turn(out, n0) and len(result_rows()) == 1 and result_rows()[0]["from"] == ref_, (out, pushes()[n0:], KINDS()))
fresh(); no_log(); listed(FRONT); log_row(FRONT, BACK, 60, "a plain handover", question=False); n0 = len(pushes()); out = msg(FRONT, "can you look at the export page?", BACK); settle()
check("1a2: a question put to the agent by the sender is a turn too: any message of the sender counts, not only a status", delivered_turn(out, n0), (out, pushes()[n0:]))
fresh(); no_log(); listed(FRONT); log_row(FRONT, BACK, 60, "a question?", question=True); n0 = len(pushes()); out = msg(FRONT, STATUS, BACK); settle()
check("1a3: …a row with the question mark counts as any row (it is a turn with the person away, where an answer is held)", delivered_turn(out, n0), (out, pushes()[n0:]))
# the controls: no key, the same messages as before
fresh(); no_log(); listed(); log_row(FRONT, BACK, 60, "go and build the export", question=False); n0 = len(pushes()); out = msg(FRONT, STATUS, BACK); settle()
check("1b: with no agent listed (the default) the same message is held as a note, as before: no turn, nothing pushed, nothing logged as a result turn", held_note(out, n0) and result_rows() == [], (out, pushes()[n0:]))
fresh(); no_log(); listed("someone-else"); log_row(FRONT, BACK, 60, "go and build the export", question=False); n0 = len(pushes()); out = msg(FRONT, STATUS, BACK); settle()
check("1b2: …and with another agent listed", held_note(out, n0) and result_rows() == [], (out, pushes()[n0:]))
fresh(); no_log(); listed(FRONT); log_row(FRONT, BACK, 25 * 60, "go and build the export", question=False); n0 = len(pushes()); out = msg(FRONT, STATUS, BACK); settle()
check("1c: a row older than result_turn_hours (24) is no hand-over", held_note(out, n0) and result_rows() == [], (out, pushes()[n0:]))
listed(FRONT, result_turn_hours=48); n0 = len(pushes()); fresh(); out = msg(FRONT, STATUS, BACK); settle()
check("1c2: …until the window is widened to 48 hours", delivered_turn(out, n0), (out, pushes()[n0:]))
fresh(); no_log(); listed(FRONT); log_row(FRONT, BACK, 60, "go and build the export", question=False, outcome="held for its next turn (front agent)"); n0 = len(pushes()); out = msg(FRONT, STATUS, BACK); settle()
check("1d: a row of a message that was held (it reached nobody) is no hand-over", held_note(out, n0) and result_rows() == [], (out, pushes()[n0:]))
fresh(); no_log(); listed(FRONT); log_row(DOCS, BACK, 60, "go and build the export", question=False); n0 = len(pushes()); out = msg(FRONT, STATUS, BACK); settle()
check("1e: a row from another agent of the project to the sender is no hand-over from this one", held_note(out, n0) and result_rows() == [], (out, pushes()[n0:]))
fresh(); no_log(); listed(FRONT); log_row(FRONT, DOCS, 60, "go and build the export", question=False); n0 = len(pushes()); out = msg(FRONT, STATUS, BACK); settle()
check("1e2: …nor a row from the agent to another session", held_note(out, n0), (out, pushes()[n0:]))

# ---- 2. (b) an item the sender moves that the agent made or is the contact of, no row
item(50, owner=A, mover=BACK); item(51, owner=D, contact=FRONT, needs=[BACK]); item(52, owner=D, mover=BACK); item(53, owner=A, mover=DOCS); item(54, owner=A, mover=BACK, status="completed")
item(55, owner=A, mover=BACK, needs=["decision"]); item(56, owner=A, needs=[BACK, DOCS]); item(57, owner=A, mover=BACK)
for name_, text_, want_ in (("an item the agent made, the sender its mover", "a50: the build is merged, the suites pass.", True), ("an item the agent is the contact of, the sender in its needs", "a51: the build is merged, the suites pass.", True),
                             ("an item the agent made, the sender one of two in its needs", "a56: the build is merged, the suites pass.", True),
                             ("an item neither made by the agent nor with it as contact", "a52: the build is merged, the suites pass.", False), ("an item the sender does not move", "a53: the build is merged, the suites pass.", False),
                             ("a closed item", "a54: the build is merged, the suites pass.", False), ("no item named", "the build is merged, the suites pass.", False)):
    fresh(); no_log(); listed(FRONT); unstamp(A); n0 = len(pushes()); out = msg(FRONT, text_, BACK); settle()
    check(f"2a: {name_}: {'a turn, no row needed' if want_ else 'no hand-over, held as before'}", (delivered_turn(out, n0) if want_ else (not_a_turn(n0) and result_rows() == [])), (out, pushes()[n0:]))
fresh(); no_log(); listed(FRONT); log_row(FRONT, BACK, 60, "go", question=False); item(58, owner=A, mover=BACK); n0 = len(pushes()); out = msg(FRONT, "a58: the build is merged, the suites pass.", BACK); settle()
check("2b: an item of the old kind (a message of the agent) and one of the new count the same: still one turn", delivered_turn(out, n0), (out, pushes()[n0:]))
fresh(); no_log(); listed(); n0 = len(pushes()); out = msg(FRONT, "a50: the build is merged, the suites pass.", BACK); settle()
check("2c: with no agent listed the message naming the item is written onto it, not delivered, as before (the item is the agent's, no turn warranted)", not_a_turn(n0) and result_rows() == [], (out, pushes()[n0:]))

# ---- 3. (c) what is no hand-over, and what is never a turn
fresh(); no_log(); listed(FRONT); n0 = len(pushes()); out = msg(FRONT, "can you look at the export page?", STRANGER); settle()
check("3a: a stranger (no row, no item): not a turn; its message goes to the background agent as before", went_to(out, n0) and result_rows() == [], (out, pushes()[n0:]))
fresh(); no_log(); listed(FRONT); log_row(FRONT, "deploy-watch", 60, "hello", question=False); n0 = len(pushes()); out = msg(FRONT, STATUS, "deploy-watch", origin=MACH); settle()
check("3b: a script is no session: a row to a name that matches does not make it one; not a turn", not_a_turn(n0) and result_rows() == [], (out, pushes()[n0:]))
fresh(); no_log(); listed(FRONT); log_row(FRONT, SOLO, 60, "hello", question=False); n0 = len(pushes()); out = msg(FRONT, STATUS, SOLO); settle()
check("3c: a peer front agent is the channel between front agents: held for the next turn, no turn, though the agent wrote to it", not_a_turn(n0) and result_rows() == [] and held.count(A) == 1, (out, pushes()[n0:]))
fresh(); no_log(); listed(FRONT); log_row(FRONT, BACK, 60, "go", question=False); n0 = len(pushes()); out = msg(FRONT, STATUS, BACK, fyi=True); settle()
check("3d: fyi=true is never a turn: held for the next turn as an fyi", out.startswith("held for work-osprey-main's next turn (fyi") and not_a_turn(n0) and held.count(A) == 1 and result_rows() == [], (out, pushes()[n0:]))
fresh(); no_log(); listed(FRONT); log_row(FRONT, BACK, 60, "go", question=False); n0 = len(pushes()); out = msg(FRONT, mark() + "\n" + STATUS, BACK, fyi=True); settle()
check("3d2: …a marked fyi too (the mark names no item of his, so it is held)", not_a_turn(n0) and result_rows() == [], (out, pushes()[n0:]))
fresh(); no_log(); listed(FRONT); n0 = len(pushes()); out = msg(FRONT, "a50: the build is merged, the suites pass.", "Oliver"); settle()
check("3e: the person's own message is no result turn (an unmarked one is refused for the mark as before)", out.startswith("Refused") and not_a_turn(n0) and result_rows() == [], (out, pushes()[n0:]))
fresh(); no_log(); listed(FRONT); log_row(TRIOM, TRIOX, 60, "go", question=False); n0 = len(pushes()); out = msg(TRIOM, STATUS, TRIOX); settle()
check("3f: an agent that is not in the list is ruled as before, though it wrote to the sender: held as a note", not_a_turn(n0, TM) and result_rows() == [] and held.count(TM) == 1, (out, pushes()[n0:]))
fresh(); no_log(); listed(FRONT); log_row(FRONT, BACK, 60, "go", question=False); n0 = len(pushes()); out = msg(FRONT, STATUS, FRONT); settle()
check("3g: the agent's own message to itself is no result turn", result_rows() == [], (out, pushes()[n0:]))
fresh(); no_log(); listed(FRONT); log_row(FRONT, BACK, 60, "go", question=False); n0 = len(pushes()); out = msg(DOCS, STATUS, BACK); settle()
check("3h: a message to a background agent is as before: the gate is the front agent's", len(reach(D, n0)) == 1 and result_rows() == [], (out, pushes()[n0:]))

# ---- 4. (d) the cap
fresh(); no_log(); listed(FRONT); log_row(FRONT, BACK, 60, "go", question=False); log_row(FRONT, DOCS, 60, "go", question=False); n0 = len(pushes()); outs = []
for i in range(7):
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf): outs.append(msg(FRONT, f"the PR {i + 1} is merged, the suites pass.", BACK)); settle()
    if i == 5: n6 = len(pushes())
    if i == 6: err7 = buf.getvalue()
check("4a: the first six turn, the seventh in the hour is held as a note, as without the key: six pushes, one held line", all(o.startswith("delivered") for o in outs[:6]) and held_note(outs[6], n6) and len(reach(A, n0)) == 6 and len(result_rows()) == 6, (outs, len(reach(A, n0))))
check("4b: …and a log line says the cap held it", "result_turn_cap_per_hour" in err7 and BACK in err7, err7)
held.take(A, FRONT); n1 = len(pushes()); out = msg(FRONT, "the PR 9 is merged, the suites pass.", DOCS); settle()
check("4c: another sender is not held by it", delivered_turn(out, n1), (out, pushes()[n1:]))
fresh(); no_log(); listed(FRONT); log_row(FRONT, BACK, 60, "go", question=False)
old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=61)).isoformat(timespec="seconds")
with open(_messaging.MSG_LOG, "a", encoding="utf-8") as f:
    for i in range(6): f.write(json.dumps({"t": old, "from": BACK, "auth": "", "to": FRONT, "outcome": "delivered → x", "error": "", "text": "old", "result_turn": True}) + "\n")
n0 = len(pushes()); out = msg(FRONT, STATUS, BACK); settle()
check("4d: turns of more than an hour ago do not count", delivered_turn(out, n0), (out, pushes()[n0:]))
fresh(); no_log(); listed(FRONT, result_turn_cap_per_hour=2); log_row(FRONT, BACK, 60, "go", question=False); n0 = len(pushes()); outs = [msg(FRONT, f"the PR {i} is merged, the suites pass.", BACK) for i in range(3)]; settle()
check("4e: the cap is the key's: two turns, the third held", [o.startswith("delivered") for o in outs] == [True, True, False] and len(reach(A, n0)) == 2, outs)
fresh(); no_log(); listed(FRONT, result_turn_cap_per_hour=0); log_row(FRONT, BACK, 60, "go", question=False); n0 = len(pushes()); out = msg(FRONT, STATUS, BACK); settle()
check("4f: a cap of 0 turns the case off", held_note(out, n0) and result_rows() == [], (out, pushes()[n0:]))

# ---- 5. (e) the router
WHO_X = "work-osprey-x (33333333…)"; WHO_B = "home-beta (44444444…)"; WHO_SOLO = "solo-main (77777777…)"
for presence in ("away", "there"):
    fresh(); no_log(); listed(FRONT); log_row(FRONT, BACK, 60, "go", question=False); (stamp(A, 5) if presence == "there" else unstamp(A)); n0 = len(pushes())
    n = recp(STATUS, kind="message", who=WHO_X); res = act2(n, FRONT); unstamp(A)
    check(f"5a: a pass of a result to the listed agent, person {presence}: delivered, unmarked, kind exempt, the reason says why", res["status"] == "ruled" and res["ruling"] == "passed" and res["target"] == FRONT and res["marked"] is False and len(reach(A, n0)) == 1
          and not reach(A, n0)[0][1].startswith(mark()) and KINDS()[-1:] == ["exempt"] and "handed over" in res["reason"], (res, pushes()[n0:], KINDS()))
fresh(); no_log(); listed(); log_row(FRONT, BACK, 60, "go", question=False); unstamp(A); n0 = len(pushes()); n = recp(STATUS, kind="message", who=WHO_X); res = act2(n, FRONT)
check("5b: with no agent listed the same pass is held for the agent's next turn, as before", res["ruling"] == "held" and reach(A, n0) == [] and held.count(A) == 1 and KINDS() == [], (res, pushes()[n0:]))
fresh(); no_log(); listed(FRONT); unstamp(A); n0 = len(pushes()); n = recp("a50: the build is merged, the suites pass.", kind="message", who=WHO_X); res = act2(n, FRONT)
check("5c: no row, an item the sender moves and the agent made: a turn", res["ruling"] == "passed" and res["target"] == FRONT and len(reach(A, n0)) == 1 and KINDS()[-1:] == ["exempt"], (res, pushes()[n0:]))
fresh(); no_log(); listed(FRONT); unstamp(A); n0 = len(pushes()); n = recp("a54: the build is merged, the suites pass.", kind="message", who=WHO_X); res = act2(n, FRONT)
check("5c2: …a closed item is not", reach(A, n0) == [] and KINDS() == [], (res, pushes()[n0:], KINDS()))
fresh(); no_log(); listed(FRONT); log_row(FRONT, STRANGER, 60, "go", question=False); unstamp(A); n0 = len(pushes()); n = recp("the export page is fixed", kind="message", who=WHO_B); res = act2(n, FRONT)
check("5d: a session the agent wrote to that is no builder is a turn too", res["ruling"] == "passed" and res["target"] == FRONT and len(reach(A, n0)) == 1, (res, pushes()[n0:]))
fresh(); no_log(); listed(FRONT); unstamp(A); n0 = len(pushes()); n = recp("yes, the export is ready", kind="message", who=WHO_B); res = act2(n, FRONT)
check("5e: a stranger is ruled as before: to the background agent", res["ruling"] == "passed" and res["target"] == BACK and reach(A, n0) == [] and len(reach(X, n0)) == 1 and KINDS()[-1:] != ["exempt"], (res, pushes()[n0:]))
fresh(); no_log(); listed(FRONT); log_row(FRONT, SOLO, 60, "go", question=False); unstamp(A); n0 = len(pushes()); n = recp(STATUS, kind="message", who=WHO_SOLO); res = act2(n, FRONT)
check("5f: a peer front agent is held for the agent's next turn, as before", res["ruling"] == "held" and reach(A, n0) == [] and held.count(A) == 1, (res, pushes()[n0:]))
fresh(); no_log(); listed(FRONT); log_row(FRONT, BACK, 60, "go", question=False); unstamp(A); n0 = len(pushes()); n = recp(STATUS, kind="message", who=WHO_X, hold="fyi"); res = act2(n, FRONT)
check("5g: an fyi notice is not a turn", reach(A, n0) == [] and res["ruling"] != "passed", (res, pushes()[n0:]))
fresh(); no_log(); listed(FRONT); log_row(FRONT, BACK, 60, "go", question=False); unstamp(A); n0 = len(pushes()); n = recp(STATUS, kind="message", who="work-osprey-x (a script on home-test)"); res = act2(n, FRONT)
check("5h: a script's pass is no turn", reach(A, n0) == [], (res, pushes()[n0:]))
fresh(); no_log(); listed(FRONT); log_row(FRONT, BACK, 60, "go", question=False); unstamp(A); n0 = len(pushes()); outs = []
for i in range(7):
    n = recp(f"the PR {i + 1} is merged, the suites pass.", kind="message", who=WHO_X); outs.append(act2(n, FRONT))
check("5i: the cap holds for the router too: six passes are turns, the seventh is held for the next turn", [o["ruling"] for o in outs] == ["passed"] * 6 + ["held"] and len(reach(A, n0)) == 6 and held.count(A) == 1, ([o["ruling"] for o in outs], len(reach(A, n0))))
fresh(); no_log(); listed(FRONT); log_row(FRONT, BACK, 60, "go", question=False); n = recp(STATUS, kind="message", who=WHO_X)
r1 = _messaging.router_result(FRONT, WHO_X, STATUS, n["id"]); r2 = _messaging.router_result(FRONT, WHO_X, STATUS, n["id"])
check("5j: a notice the router tries again counts once toward the cap", r1 is True and r2 is True and len([d for d in mlog() if d.get("nid") == n["id"]]) == 1, mlog()[-2:])
fresh(); no_log(); listed(FRONT); log_row(TRIOM, TRIOX, 60, "go", question=False); unstamp(TM); n0 = len(pushes()); n = recp(STATUS, kind="message", who="trio-x (eeeeeeee…)", key="projects/trio")
res = act2(n, TRIOM, key="projects/trio")
check("5k: a pass to an agent that is not listed is ruled as before", res["ruling"] != "passed" or reach(TM, n0) == [], (res, pushes()[n0:]))

# ---- 6. (f) the digest never files a result turn
fresh(); no_log(); listed(FRONT); log_row(FRONT, BACK, 60, "go", question=False); unstamp(A); n0 = len(pushes()); out = msg(FRONT, STATUS, BACK); settle()
sent_kind = KINDS()[-1:] and KINDS()[-1]
line = "[stackshot message] from work-osprey-x: " + STATUS
check("6a: the message tool pushed the turn with the kind exempt", sent_kind == "exempt", KINDS())
check("6b: a digest of that line (the pane was busy) is handed out as a turn, not filed as an fyi", _messaging.digest_fyi(FRONT, [line], [sent_kind]) == [] and held.count(A) == 0, held.count(A))
fresh(); check("6c: control: the same line with no kind (an ordinary message) is filed as an fyi, starting no turn", _messaging.digest_fyi(FRONT, [line], [""]) == [0] and held.count(A) == 1, held.count(A))
fresh(); no_log(); listed(FRONT); log_row(FRONT, BACK, 60, "go", question=False); unstamp(A); n0 = len(pushes()); n = recp(STATUS, kind="message", who=WHO_X); act2(n, FRONT)
check("6d: the router's push carried the kind exempt too, so its digest never files it", KINDS()[-1:] == ["exempt"] and _messaging.digest_fyi(FRONT, [line], KINDS()[-1:]) == [], KINDS())
fresh(); no_log(); listed()

fresh(); no_log()
print(f"{len(ran) - len(fails)}/{len(ran)} checks passed" + ("" if not fails else f"; FAILED: {len(fails)}"))
sys.exit(1 if fails else 0)
