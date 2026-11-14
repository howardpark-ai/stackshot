"""Scenario test for holding notices that ask nothing of a background agent
- fixture data, no live store, no network, no server.

Covers (held.py is the store and the decision; telling.hold_notice and router_live._hold_kind are the two places that ask it):
  1. The store: a line is added and handed over once, oldest first, one line each, with a "+N more" tail past the cap (the rest comes at the next turn); an old line
     is dropped; the files are the state, so a reload of the module (a restart of the server) loses nothing; a session is found by its transcript id or its name.
  2. The decision (held.decide) on a table: only a known kind to a background agent, with no Oliver words and no ask; the switch [router] hold_notices turns it off.
  3. Each held kind from the server's own senders to a BACKGROUND agent (the builder) is not pushed and is logged "held: asks nothing (kind)": a completion
     (closed), a change to an item it neither moves nor is named on (changed), a close seen by an observer, a wake that leaves an item still after an open item
     (queue), a page-owed notice and a batch of them (page-owed). And what still wakes it, pushed as before: a completion with Oliver's words, a reopen, a change
     to an item it moves or is named on, a wake that puts the item back in its lane, a hand-off, a naming in needs, a page-debt fallback, a message not marked
     fyi, an fyi that carries [for Oliver], an fyi from Oliver.
  4. A front agent is unchanged: the same senders deliver to it (or tell nobody) as before, and an fyi to a front agent is refused or delivered by the same rules.
  5. The router: a pass to a background agent of a notice recorded with `hold` (page-owed, fyi) is held and ruled held with the reason (the audit's batch is not: the board item, a finding is a task and wakes its mover); the same
     pass to a front agent, a notice with Oliver's words, a ruling for Oliver, and a notice with no hold mark are delivered as before.
  6. The message tool's `fyi`: to a background agent held (the reply says so; the agent is named in no item's needs), to a project recorded with the mark, to a front
     agent unchanged; the parameter is on the tool and the text says what it does.
  7. The hand-over at a turn start: the client endpoint (POST /client/held) returns the text once, a waking notice does not take the held lines with it, the lines wait
     until a turn start, a front agent's session gets nothing, and client.held_for reads the endpoint.

    tests/run-suite held        → exit 0 / 1"""
import importlib, inspect, json, logging, os, pathlib, re, sys, threading, time

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
for d in ("store/a", "fleet/a", "state/anchor-hub", "state/site", "secrets", "touch", "repo", "brain/projects"): (T / d).mkdir(parents=True)
S, A, X, B, D = ("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333",
                 "44444444-4444-4444-8444-444444444444", "66666666-6666-4666-8666-666666666666")
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for u, n in
                                                      ((S, "work-osprey"), (A, "work-osprey-main"), (X, "work-osprey-x"), (B, "home-beta"), (D, "work-osprey-docs"))}))
AGENTS = {"work-osprey-main": "Oliver's point of contact", "work-osprey-x": "builds, merges and releases the code", "work-osprey-docs": "keeps the pages"}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {
    "title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "work-osprey", "status": "active", "board": [], "board_row": False,
    "updated": 1, "mirror": "https://example.invalid/alpha", "agents": AGENTS, "back_agents": {"work-osprey-x": AGENTS["work-osprey-x"], "work-osprey-docs": AGENTS["work-osprey-docs"]}}}}))
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
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import wakes as wakes_svc
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.tools import message as _wt_message
from stackshot.service import telling
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None; telling.PUSH = [sys.executable, str(T / "fakepush.py")]
_web_page_debts._refuse_if_owing = lambda debtor: None
_cfg.CFG["router"] = {"command": [sys.executable, "-c", "pass"], "timeout_seconds": 20, "live": True}
KEY = "projects/alpha"
MACH = "home-test"
def gate_open():
    """The rollout gate: the builder's and the page keeper's hooks have fetched held lines (held.mark_client), and the machine holds their sessions."""
    held.mark_client(X, "work-osprey-x"); held.mark_client(D, "work-osprey-docs")
for u_, n_ in ((X, "work-osprey-x"), (A, "work-osprey-main"), (D, "work-osprey-docs"), (B, "home-beta")): server._clients.register(MACH, {"uuid": u_, "name": n_})
gate_open()
def ids(session): return {X: ("work-osprey-x", X), A: ("work-osprey-main", A), D: ("work-osprey-docs", D)}[session]
def reach(session, since): return [x for x in pushes()[since:] if x[0] in ids(session)]
def hold_lines(): return [n for n in routing.read(KEY) if n.get("ruling") == "held" and str(n.get("reason", "")).startswith("held: asks nothing")]
def gone(*refs): return held.take(*refs)
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def why(fn):
    try: fn(); return ""
    except server.ToolError as e: return str(e)
def fresh():
    """Empty the held store and the push log between scenarios."""
    for p in held.dir_().glob("*.jsonl"): p.unlink()
    push_log.unlink(missing_ok=True)

# ---- 1. the store
fresh()
k = held.key_of("work-osprey-x")
t0 = 1_000_000_000.0
for i in range(12): held.add(k, "closed", f"line {i}", sender="s", now=t0 + i)
text = held.take(X, "work-osprey-x", now=t0 + 20)
lines = text.splitlines()
check("1a: twelve lines held, the first hand-over shows eight, oldest first, and the tail says how many wait for the next turn", len(lines) == 1 + 8 + 1 and "line 0" in lines[1] and "line 7" in lines[8] and "+4 more" in lines[-1], text)
check("1b: the header counts all twelve and says they asked nothing and come once", lines[0].startswith("[stackshot] 12 notices held for you") and "once" in lines[0], lines[0])
text2 = held.take(X, "work-osprey-x", now=t0 + 21)
check("1c: the next turn start gets the other four, with no tail, and nothing is repeated", "line 8" in text2 and "line 11" in text2 and "line 7" not in text2 and "more" not in text2.splitlines()[-1], text2)
check("1d: and the turn after that gets nothing", held.take(X, "work-osprey-x") == "" and held.count(X, "work-osprey-x") == 0)
held.add(k, "closed", "an old one", now=t0)
check("1e: a line older than seven days is dropped, never handed over", held.take(X, now=t0 + 8 * 86400) == "")
held.add(k, "fyi", "survives a restart", now=time.time())
held_mod = importlib.reload(held)          # a restart of the server loads the module afresh; the files are the state
check("1f: a reload of the module (a restart) loses nothing: the line is still held, found by transcript id alone", held_mod.count(X) == 1 and "survives a restart" in held_mod.take(X))
held = held_mod
for i in range(held.KEEP_MAX + 5): held.add(k, "closed", f"n{i}", now=t0 + i)
check("1g: a session keeps at most KEEP_MAX lines; the oldest go", held.count(X) == held.KEEP_MAX and {r["text"] for r in held._read(held._file(k))} == {f"n{i}" for i in range(5, held.KEEP_MAX + 5)}, held.count(X))
fresh()
held.add(held.key_of(X), "closed", "found by uuid", now=time.time())
check("1h: a session filed by its id is found by its name and the other way", "found by uuid" in held.take("", "work-osprey-x"))
held.add(held.key_of("work-osprey-x"), "closed", "x" * 600, now=time.time())
check("1i: a line is one line and is cut at LINE_MAX", len(held.take(X).splitlines()[1]) < held.LINE_MAX + 60)
held.add(k, "closed", "two\nlines  and   spaces", now=time.time())
check("1j: whitespace and newlines are folded to one line", "two lines and spaces" in held.take(X))
check("1k: the same router notice id added twice is held once (a retried ruling)", held.add(k, "page-owed", "p", nid="n1") and held.add(k, "page-owed", "p", nid="n1") and held.count(X) == 1)
fresh()

# ---- 2. the decision
D_ = lambda kind, **kw: held.decide(kind, **{"is_background": True, **kw})
check("2a: a known kind to a background agent that asks nothing is held", all(D_(kd) == kd for kd in held.KINDS))
check("2b: a front agent, an unknown kind, an empty kind are delivered", D_("closed", is_background=False) == "" and D_("wake") == "" and D_("") == "")
check("2c: Oliver's words, an ask, the owner as sender, and the marks [for Oliver] and needs: decision deliver", D_("closed", owner_words=True) == "" and D_("changed", asks=True) == ""
      and D_("fyi", sender_is_owner=True) == "" and D_("closed", text="[for Oliver] look") == "" and D_("closed", text="it now needs: decision") == "")
_cfg.CFG["router"]["hold_notices"] = False
check("2d: [router] hold_notices = false delivers everything", D_("closed") == "")
_cfg.CFG["router"].pop("hold_notices")
check("2e: …and the default is on", D_("closed") == "closed")

# ---- 3. the server's senders to a BACKGROUND agent (the builder, work-osprey-x)
def sent_to(who, since): return reach(who, since)
def logged(kind): return [n for n in hold_lines() if n.get("reason") == f"held: asks nothing ({kind})"]
# closed: a plain completion of an item the builder owns, by another session
fresh(); n0 = len(pushes()); h0 = len(hold_lines()); it = server._load("a1")
out = telling.tell_owner("a1", it, "was completed (done)", B, close=True); settle()
check("3a: a completion of the builder's item by another session is not pushed to it", reach(X, n0) == [], pushes()[n0:])
check("…it is held, one line, for its next turn", held.count(X) == 1 and "item 1" in held.take(X), held.count(X))
check("…and the routing log says held: asks nothing (closed), logged by the server (not delivered to anyone)", len(logged("closed")) == 1 and logged("closed")[0].get("to", "") == "" and logged("closed")[0].get("ruled_by") == routing.AUTO_RULER, hold_lines())
fresh(); n0 = len(pushes()); it = server._load("a2")
telling.tell_owner("a2", it, "was completed (done)", B, close=True); settle()
check("3b negative: the same completion with Oliver's words on the item (Oliver: \"ship it\") is pushed to the builder as before", len(reach(X, n0)) == 1 and held.count(X) == 0, (pushes()[n0:], held.count(X)))
fresh(); n0 = len(pushes()); it = server._load("a1")
telling.tell_owner("a1", it, "was reopened (next: more work)", B); settle()
check("3c negative: a reopen is pushed (it asks the builder to look at the item again)", len(reach(X, n0)) == 1 and held.count(X) == 0, pushes()[n0:])
fresh(); n0 = len(pushes()); it = server._load("a1")
telling.tell_owner("a1", it, "now names work-osprey-docs in its needs too, handed over", B); settle()
check("3d negative: a notice that is neither a completion nor a change (a naming in needs told to the owner) is pushed", len(reach(X, n0)) == 1 and held.count(X) == 0, pushes()[n0:])

# changed: another session set next on an item the builder owns but does not move, and on one it moves, and on one it is named on
def changed(gid, **after):
    it_ = server._load(gid); before = dict(it_["metadata"]); it_["metadata"] = {**before, "next": "home-beta: a new line"}
    return telling.tell_owner_change(gid, it_, before, B, False, False, False, False)
fresh(); n0 = len(pushes()); telling.OWNER_HEARD.clear()
item(3, hold=True, wake="2099-01-01", hold_set={"by": "t", "at": now0}, then=X)          # the builder holds it (it comes to the builder after the wait) but does not move it
changed("a3"); settle()
check("3e: another session's change to next on an item the builder owns and does not move is held (changed), not pushed", reach(X, n0) == [] and held.count(X) == 1 and len(logged("changed")) >= 1, (pushes()[n0:], held.count(X)))
for gid, what in (("a4", "an item it moves"), ("a5", "an item it is named on in needs")):
    fresh(); n0 = len(pushes()); telling.OWNER_HEARD.clear()
    changed(gid); settle()
    check(f"3f negative: the same change to {what} is pushed (it may be an instruction)", len(reach(X, n0)) == 1 and held.count(X) == 0, (gid, pushes()[n0:], held.count(X)))
fresh(); n0 = len(pushes()); telling.OWNER_HEARD.clear(); it = server._load("a1"); before = dict(it["metadata"]); it["metadata"] = {**before, "outcome": "done"}; it["status"] = "completed"
telling.tell_owner_change("a1", it, before, B, True, False, False, False); settle()
check("3g: a close by another session told through the change notice is held (closed)", reach(X, n0) == [] and held.count(X) == 1, (pushes()[n0:], held.count(X)))
fresh(); n0 = len(pushes()); telling.OWNER_HEARD.clear(); it = server._load("a1"); before = dict(it["metadata"])
telling.tell_owner_change("a1", it, before, B, False, False, False, True); settle()
check("3h negative: a reopen told through the change notice is pushed", len(reach(X, n0)) == 1 and held.count(X) == 0, pushes()[n0:])

# an observer's close
fresh(); n0 = len(pushes()); it = server._load("a6")
telling.tell_observers("a6", it, "was completed (done)", B); settle()
check("3i: a background observer's completion notice is held (closed)", reach(X, n0) == [] and held.count(X) == 1, (pushes()[n0:], held.count(X)))
fresh(); n0 = len(pushes()); it = server._load("a6")
telling.tell_observers("a6", it, "was reopened (next: again)", B); settle()
check("3j negative: …and a reopen is pushed to it", len(reach(X, n0)) == 1, pushes()[n0:])

# queue: a wake that leaves the item still after an open item
item(8, after=["a9"], owner=X)
fresh(); n0 = len(pushes()); it = server._load("a8")
wakes_svc.wake_tell(X, [("a8", it, "woke (wake 10-29)", "as its keeper of record", False)]); settle()
check("3k: a wake that leaves the builder's item still after an open item (its place in the queue) is held (queue), not pushed", reach(X, n0) == [] and held.count(X) == 1 and len(logged("queue")) == 1, (pushes()[n0:], held.count(X)))
fresh(); n0 = len(pushes()); it = server._load("a1")
wakes_svc.wake_tell(X, [("a1", it, "woke (wake 10-29)", "as its keeper of record", False)]); settle()
check("3l negative: a wake that puts the item back in its lane is pushed", len(reach(X, n0)) == 1 and held.count(X) == 0, (pushes()[n0:], held.count(X)))
fresh(); n0 = len(pushes()); it = server._load("a8")
wakes_svc.wake_tell(X, [("a8", it, "reminder", "as its keeper of record", True)]); settle()
check("3m negative: a reminder (an active item the owner is asked to close or refresh) is pushed even when the item has an after", len(reach(X, n0)) == 1, pushes()[n0:])

# page-owed: the keeper that is a background agent
fresh(); n0 = len(pushes()); it = server._load("a1")
out = telling.pilot_relay(KEY, "a1", it, "completed (done)", B, "work-osprey-docs", "agent"); settle()
check("3n: a page-owed notice that hands the debt to the keeper ('the page update is yours as its agent') is an ask: delivered to the background keeper, not held",
      len(reach(D, n0)) == 1 and held.count(D) == 0 and not logged("page-owed"), (out, pushes()[n0:], held.count(D)))
fresh(); n0 = len(pushes()); it = server._load("a1")
out = telling.pilot_relay(KEY, "a1", it, "completed (done)", B, "work-osprey-docs", "name", tail="home-beta left its page update undone past 30 min, so it is yours as its keeper"); settle()
check("3n2: …and so is the fallback after the writer left it undone ('…so it is yours as its keeper'): delivered", len(reach(D, n0)) == 1 and held.count(D) == 0, (pushes()[n0:], held.count(D)))
fresh(); n0 = len(pushes()); it = server._load("a1")
out = telling.pilot_relay(KEY, "a1", it, "completed (done)", B, "work-osprey-docs", "agent",
                          tail="no page update is owed by you (home-beta writes it); this notice is for the anchors scoped to board#1"); settle()
check("3n3: a page-owed notice that owes the keeper nothing (the anchors tail) is held (page-owed), and the writer's reply says it reads it at its next turn",
      reach(D, n0) == [] and held.count(D) == 1 and len(logged("page-owed")) == 1 and "next turn" in out, (out, pushes()[n0:], held.count(D)))
fresh(); n0 = len(pushes())
rows = [(KEY, "a1", server._load("a1"), "completed (done)", B), (KEY, "a3", server._load("a3"), "changed (next)", B)]
ids_ = telling.pilot_relay_many("work-osprey-docs", rows); settle()
check("3o: a batch of page debts moved to a background keeper ('…so it is yours as its keeper') is delivered, one message, nothing held", len(reach(D, n0)) == 1 and held.count(D) == 0, (pushes()[n0:], held.count(D)))
fresh(); n0 = len(pushes())
telling.pilot_relay_many("work-osprey-docs", rows, head="[board] the page debt call could not apply an edit"); settle()
check("3p negative: the page-debt fallback, which names its recipient, is pushed", len(reach(D, n0)) == 1 and held.count(D) == 0, (pushes()[n0:], held.count(D)))

# what still wakes it
fresh(); n0 = len(pushes()); it = server._load("a1")
telling.tell_needed("a1", it, [X], B); settle()
check("3q negative: a naming in needs wakes the builder", len(reach(X, n0)) == 1 and held.count(X) == 0, pushes()[n0:])
fresh(); n0 = len(pushes()); th = telling.tell_woken("a1", X, "[stackshot] a1 handed to you", tag="handoff"); settle()
check("3r negative: a hand-off notice (no hold kind) is pushed", len(reach(X, n0)) == 1 and held.count(X) == 0, pushes()[n0:])
fresh(); n0 = len(pushes()); th = telling.tell_or_hold("a1", X, "[stackshot] a1 closed by home-beta", "closed", tag="owner"); settle()
check("3s: the one decision point holds a kind the sender names (tag owner, hold closed) and returns no thread", th is None and reach(X, n0) == [] and held.count(X) == 1)
fresh(); n0 = len(pushes()); th = telling.tell_or_hold("a1", X, "[stackshot] a1 closed by home-beta [for Oliver] look", "closed", tag="owner"); settle()
check("3t negative: …unless the text carries [for Oliver]", len(reach(X, n0)) == 1 and held.count(X) == 0)
fresh(); n0 = len(pushes()); th = telling.tell_or_hold("a1", X, "[stackshot] a1 closed", "not-a-kind", tag="owner"); settle()
check("3u negative: …or the kind is not one it knows (unsure delivers)", len(reach(X, n0)) == 1 and held.count(X) == 0)
_cfg.CFG["router"]["hold_notices"] = False
fresh(); n0 = len(pushes()); it = server._load("a1"); telling.tell_owner("a1", it, "was completed (done)", B, close=True); settle()
_cfg.CFG["router"].pop("hold_notices")
check("3v: with [router] hold_notices = false the completion is pushed as before", len(reach(X, n0)) == 1 and held.count(X) == 0, pushes()[n0:])

# a close whose outcome is not done tells a builder to stop: delivered
for what_ in ("was completed (dropped)", "was completed (superseded by board#2)"):
    fresh(); n0 = len(pushes()); it = server._load("a1")
    telling.tell_owner("a1", it, what_, B, close=True); settle()
    check(f"3w negative: {what_} is pushed to the builder that owns the item (it must stop), not held", len(reach(X, n0)) == 1 and held.count(X) == 0, (pushes()[n0:], held.count(X)))
fresh(); n0 = len(pushes()); it = server._load("a6")
telling.tell_observers("a6", it, "was completed (dropped)", B); settle()
check("3x negative: …and a dropped item is pushed to a background observer too", len(reach(X, n0)) == 1 and held.count(X) == 0, (pushes()[n0:], held.count(X)))
fresh(); n0 = len(pushes()); telling.OWNER_HEARD.clear(); it = server._load("a1"); before = dict(it["metadata"]); it["metadata"] = {**before, "outcome": "dropped"}; it["status"] = "completed"
telling.tell_owner_change("a1", it, before, B, True, False, False, False); settle()
check("3y negative: a drop told through the change notice is pushed", len(reach(X, n0)) == 1 and held.count(X) == 0, (pushes()[n0:], held.count(X)))

# the rollout gate: a session whose hook has not fetched held lines (an old checkout, a cloud session, no turn since the update) gets everything as today
os.unlink(held.clients_file())
check("3z: can_fetch is false for a session never seen asking, and for a cloud session id", not held.can_fetch(X) and not held.can_fetch("work-osprey-x") and not held.can_fetch("cse_0123456789abcdef"))
fresh(); n0 = len(pushes()); it = server._load("a1")
telling.tell_owner("a1", it, "was completed (done)", B, close=True); settle()
check("3z1 gate: a completion to a background agent whose hook does not fetch held lines is pushed as today, nothing is stranded", len(reach(X, n0)) == 1 and held.count(X) == 0, (pushes()[n0:], held.count(X)))
fresh(); n0 = len(pushes()); out = server._message("work-osprey-x", "the PR is merged, nothing to do", "home-beta", fyi=True); settle()
check("3z2 gate: an fyi to it is delivered as an ordinary message", out.startswith("delivered") and len(reach(X, n0)) == 1 and held.count(X) == 0, out)
check("3z3 gate: held.decide with a target that cannot fetch delivers; without a target it decides on the kind alone", held.decide("closed", is_background=True, target="work-osprey-x") == "" and held.decide("closed", is_background=True) == "closed")
gate_open()
check("3z4 gate: once its hook has asked, can_fetch is true by transcript id and by name", held.can_fetch(X) and held.can_fetch("work-osprey-x") and not held.can_fetch(A))
check("3z5 gate: a mark older than CLIENT_DAYS no longer counts", held.can_fetch(X, now=time.time() + (held.CLIENT_DAYS + 1) * 86400) is False)
gate_open()

# ---- 4. a FRONT agent is unchanged
fresh(); n0 = len(pushes()); it = server._load("a7")
out = telling.tell_owner("a7", it, "was completed (done)", B, close=True); settle()
check("4a: a completion of a front agent's item tells nobody and holds nothing, as before", reach(A, n0) == [] and "front agent" in out and held.count(A) == 0, out)
check("…(and the front agent's id has no held line)", held.count(A, "work-osprey-main") == 0)
fresh(); n0 = len(pushes()); it = server._load("a7")
for kind in ("closed", "changed", "queue", "page-owed", "fyi"):
    check(f"4b: hold_notice never holds a notice to a front agent (kind {kind})", telling.hold_notice(A, "text", kind) is False)
check("4c: …and holds nothing for a session that no page lists", telling.hold_notice(B, "text", "closed") is False and held.count(B) == 0)
check("4d: a front agent that keeps the page gets no page-owed notice from pilot_relay, as before (and nothing is held)", telling.pilot_relay(KEY, "a7", it, "completed (done)", B, "work-osprey-main", "name") == "" and held.count(A) == 0)

# ---- 5. the router
def notice(nid, text, hold="", **kw):
    n = {"id": nid, "ts": time.time(), "kind": "board", "label": "board board#1", "who": "home-beta", "to": "", "target": "for home-beta", "pilot": True, "live": True, "text": text, "url": "", "anchor": "", **kw}
    if hold: n["hold"] = hold
    return n
def rec(text, hold="", **kw):
    nid = routing.record(KEY, kind="board", to="", label="board board#1", who="home-beta", text=text, target="for home-beta", pilot=True, live=True, hold=hold, **kw)
    _live.stash(nid, text)
    return next(n for n in routing.read(KEY) if n["id"] == nid)
cx = _router.Context()
def act(n, target, **ln):
    line = {"id": n["id"], "ruling": "passed", "target": target, "reason": "the page update is owed", "for_owner": False, "source": "code", "rule": "test", "item": "", **ln}
    return _live._act(n, KEY, KEY, line, cx, {})
fresh(); n0 = len(pushes()); n = rec("[board] board#1 completed (done) by home-beta — [home] item 1 (projects/alpha) — the page update is owed", hold="page-owed")
res = act(n, "work-osprey-docs")
rr = next(x for x in routing.read(KEY) if x["id"] == n["id"])
check("5a: the router passes a notice recorded with hold=page-owed to a background agent: held, not delivered, ruled held with the reason", reach(D, n0) == [] and held.count(D) == 1
      and res["status"] == "ruled" and res["ruling"] == "held" and rr.get("ruling") == "held" and rr.get("reason") == "held: asks nothing (page-owed)" and rr.get("ruled_by") == _live.BY, (res, rr, pushes()[n0:]))
check("…the stored line is the notice's text, one line", "page update is owed" in held.take(D, "work-osprey-docs"))
fresh(); n0 = len(pushes()); n = rec("[board] board#1 completed (done) by home-beta — the page update is owed", hold="page-owed"); res = act(n, "work-osprey-main")
check("5b negative: the same notice passed to a FRONT agent is delivered, marked, as before", len(reach(A, n0)) == 1 and res["ruling"] == "passed" and held.count(A) == 0, (res, pushes()[n0:]))
fresh(); n0 = len(pushes()); n = rec("[board] board#1 completed — [for Oliver] look at the page", hold="page-owed"); res = act(n, "work-osprey-docs")
check("5c negative: a notice with Oliver's mark is delivered whatever the hold says", len(reach(D, n0)) == 1 and res["ruling"] == "passed" and held.count(D) == 0, res)
fresh(); n0 = len(pushes()); n = rec("[board] board#1 completed", hold="page-owed"); res = act(n, "work-osprey-docs", for_owner=True)
check("5d negative: a ruling marked for Oliver is delivered", len(reach(D, n0)) == 1 and res["ruling"] == "passed", res)
fresh(); n0 = len(pushes()); n = rec("[board] board#1 handed back to you"); res = act(n, "work-osprey-x")
check("5e negative: a notice with no hold mark and no audit rule (any other pass) is delivered as now", len(reach(X, n0)) == 1 and res["ruling"] == "passed" and held.count(X) == 0, res)
fresh(); n0 = len(pushes()); n = rec("a hand-back to its owner", hold="page-owed", handback=True); res = act(n, "work-osprey-x")
check("5f negative: a hand-back (an item given back to its owner) is never held, whatever the mark", len(reach(X, n0)) == 1 and res["ruling"] == "passed", res)
# the audit's batch: one line per item, split by owner
body = "[stackshot] Audit of Thu Oct 29th: 2 findings\na1 · stale · no update for 9 days\na10 · stale · no update for 12 days"
fresh(); n0 = len(pushes())
nid_ = routing.record(KEY, kind="message", to="", label="message to projects/alpha", who="falcon-audit", text=body, target="project-wide", pilot=True, live=True); _live.stash(nid_, body)
n = next(x for x in routing.read(KEY) if x["id"] == nid_)
cx = _router.Context()
ln = _router.audit_rule(KEY, n, KEY, cx)
check("5g: the audit's batch finding is split by item keeper of record (the rule audit-owners)", ln and ln.get("rule") == "audit-owners" and set(ln["split"]) == {"work-osprey-x", "work-osprey-main"}, ln)
if ln:
    res = _live._act(n, KEY, KEY, ln, cx, {})
    check("5h: the lines for the background keeper are delivered at once, like those for the front keeper (a finding is a task, never held)", held.count(X) == 0 and len(reach(X, n0)) == 1 and len(reach(A, n0)) == 1 and res["ruling"] == "passed", (res, pushes()[n0:], held.count(X)))
    fresh(); n0 = len(pushes()); nid2 = routing.record(KEY, kind="message", to="", label="message to projects/alpha", who="falcon-audit", text=body, target="project-wide", pilot=True, live=True)
    _live.stash(nid2, body); n2 = next(x for x in routing.read(KEY) if x["id"] == nid2)
    only = {**ln, "id": nid2, "target": "work-osprey-x", "split": {"work-osprey-x": ["a1"]}}
    res = _live._act(n2, KEY, KEY, only, cx, {})
    rr = next(x for x in routing.read(KEY) if x["id"] == nid2)
    check("5i: a batch whose every keeper is background is delivered to it and ruled passed, not held", res["ruling"] == "passed" and rr.get("ruling") == "passed" and rr.get("ruled_to") == "work-osprey-x" and len(reach(X, n0)) == 1 and held.count(X) == 0, (res, rr))
    fresh(); n0 = len(pushes()); nid3 = routing.record(KEY, kind="message", to="", label="message to projects/alpha", who="falcon-audit", text=body, target="project-wide", pilot=True, live=True, hold="fyi")
    _live.stash(nid3, body); n3 = next(x for x in routing.read(KEY) if x["id"] == nid3)
    res = _live._act(n3, KEY, KEY, {**ln, "id": nid3}, cx, {})
    check("5j: an audit batch whose sender marked it fyi is still delivered to the background keeper: a finding is a task", len(reach(X, n0)) == 1 and held.count(X) == 0 and res["ruling"] == "passed", (res, pushes()[n0:], held.count(X)))

# ---- 6. the message tool's fyi
check("6a: the message tool takes fyi (default false) and its text says what it does", "fyi" in inspect.signature(_wt_message.stackshot_message).parameters
      and inspect.signature(_wt_message.stackshot_message).parameters["fyi"].default is False)
desc = next(t for t in server.mcp._tool_manager._tools.values() if t.name == "message").description if hasattr(server.mcp, "_tool_manager") else ""
check("…the description names fyi and its effect on a background agent, a project and a front agent", not desc or ("fyi=true" in desc and "next turn" in desc and "front agent it changes nothing" in desc), desc[-400:])
fresh(); n0 = len(pushes()); out = server._message("work-osprey-x", "the PR is merged, nothing to do", "home-beta", fyi=True); settle()
check("6b: an fyi to a background agent is held: the reply says so, nothing is pushed, the line waits", out.startswith("held for work-osprey-x's next turn") and reach(X, n0) == [] and held.count(X) == 1 and len(logged("fyi")) == 1, (out, pushes()[n0:]))
check("…and the message log records it as an fyi that was not delivered", any(json.loads(l).get("fyi") and "held" in json.loads(l)["outcome"] for l in server.MSG_LOG.read_text().splitlines()))
fresh(); n0 = len(pushes()); out = server._message("work-osprey-x", "the PR is merged, nothing to do", "home-beta"); settle()
check("6c negative: the same message without fyi is delivered", out.startswith("delivered") and len(reach(X, n0)) == 1 and held.count(X) == 0, out)
fresh(); n0 = len(pushes()); out = server._message("work-osprey-x", "[for Oliver] the PR is merged, a decision for you", "home-beta", fyi=True); settle()
check("6d negative: an fyi that carries [for Oliver] is delivered", out.startswith("delivered") and len(reach(X, n0)) == 1 and held.count(X) == 0, out)
fresh(); n0 = len(pushes()); out = server._message("work-osprey-x", "go on with a1", "Oliver", fyi=True); settle()
check("6e negative: an fyi from Oliver himself is an ordinary message", out.startswith("delivered") and len(reach(X, n0)) >= 1 and held.count(X) == 0, out)
item(11); fresh(); n0 = len(pushes()); out = server._message("work-osprey-x", "FYI done with a11", "home-beta", fyi=True); settle()
check("6f: an fyi names the builder in no item's needs (it asked nothing), where the same words without fyi do", out.startswith("held") and "work-osprey-x" not in str(rd(11)["metadata"].get("needs")) and "named" not in out, out)
fresh(); out = server._message("work-osprey-x", "done with a11", "home-beta"); settle()
check("…(the control: without fyi the plain item id names it)", "work-osprey-x" in str(rd(11)["metadata"].get("needs")), rd(11)["metadata"])
fresh(); n0 = len(pushes()); out = why(lambda: server._message("work-osprey-main", "the PR is merged", "home-beta", fyi=True))
check("6g: an fyi to a FRONT agent without the mark is refused by the same gate as without the flag", out.startswith("Refused") and "front agent" in out and reach(A, n0) == [], out)
fresh(); n0 = len(pushes()); out = server._message("work-osprey-main", "[for Oliver] pick a or b", "home-beta", fyi=True); settle()
check("6h: …and a marked one is delivered to it as it would be without the flag", out.startswith("delivered") and len(reach(A, n0)) == 1 and held.count(A) == 0, out)
fresh(); n0 = len(pushes()); out = server._message(KEY, "the release is live", "home-beta", fyi=True)
nn = [x for x in routing.read(KEY) if x.get("kind") == "message" and x.get("text", "").endswith("the release is live")]
check("6i: an fyi to a project is recorded with the mark for the router (and is held for the router as any message to a project)", out.startswith("held for the router") and nn and nn[-1].get("hold") == "fyi" and reach(X, n0) == [], (out, nn))
res = act(nn[-1], "work-osprey-x", rule="message-item")
check("6j: the router, passing it to a background agent, holds it (fyi)", res["ruling"] == "held" and held.count(X) == 1 and len(logged("fyi")) >= 1, res)
fresh(); n0 = len(pushes()); res = act(nn[-1], "work-osprey-main", rule="message-item")
check("6k negative: …and passing it to a front agent delivers it as today", res["ruling"] == "passed" and len(reach(A, n0)) == 1 and held.count(A) == 0, res)
fresh(); out = server._message(KEY, "the release is live", "home-beta"); nn2 = [x for x in routing.read(KEY) if x.get("kind") == "message" and x.get("text", "").endswith("the release is live")][-1]
check("6l: a message to a project without fyi carries no mark", "hold" not in nn2, nn2)

# ---- 7. the hand-over at a turn start
fresh()
held.add(held.key_of(X), "closed", "board#1 closed by home-beta", sender="home-beta", now=time.time() - 120)
held.add(held.key_of(X), "page-owed", "board#3 page update owed", sender="home-beta", now=time.time() - 60)
n0 = len(pushes()); telling.tell_woken("a1", X, "[stackshot] a1 is yours now", tag="handoff"); settle()
check("7a: a waking notice is pushed as now and takes none of the held lines with it (they wait for the turn start)", len(reach(X, n0)) == 1 and "held for you" not in json.dumps(pushes()[n0:]) and held.count(X) == 2)
st, body_ = server._client_post(MACH, "held", {"uuid": X, "name": "work-osprey-x"})
txt = body_.get("text", ""); ids7 = body_.get("ids", [])
check("7b: the client endpoint hands them over at the turn start, oldest first, one line each, with the kind, and the ids to acknowledge",
      st == 200 and txt.count("\n- ") == 2 and txt.index("board#1 closed") < txt.index("board#3 page") and " · closed · " in txt and " · page-owed · " in txt and len(ids7) == 2, (st, body_))
st, body_ = server._client_post(MACH, "held", {"uuid": X, "name": "work-osprey-x"})
check("7c: a second ask inside the lease is not handed the same lines again, and they are not lost yet (still stored until acknowledged)", st == 200 and body_ == {"text": "", "ids": []} and held.count(X) == 2, (body_, held.count(X)))
st, body_ = server._client_post(MACH, "held", {"uuid": X, "ack": ids7})
check("7c2: the acknowledgement removes exactly those lines", st == 200 and body_ == {"removed": 2} and held.count(X) == 0, (body_, held.count(X)))
st, body_ = server._client_post(MACH, "held", {"uuid": A, "name": "work-osprey-main"})
check("7d: a front agent's session gets nothing (nothing is ever held for it)", st == 200 and body_ == {"text": "", "ids": []}, body_)
st, body_ = server._client_post(MACH, "held", {"uuid": "nope", "name": ""})
check("7e: a body without a transcript id is refused", st == 400, (st, body_))
held.add(held.key_of(X), "fyi", "kept across a restart", sender="home-beta", now=time.time())
held = importlib.reload(held)
st, body_ = server._client_post(MACH, "held", {"uuid": X, "name": "work-osprey-x"})
check("7f: a held line survives a restart of the server (the module reloaded; the files are the state)", "kept across a restart" in body_.get("text", ""), body_)
held.ack(X, ids=body_.get("ids"))
held.add(held.key_of(X), "closed", "via the client", sender="home-beta", now=time.time())
_real_post = client.post
client.post = lambda what, body, timeout=20.0: server._client_post(MACH, what, body)
try:
    got, gids = client.held_for(X, "work-osprey-x"); again = client.held_for(X, "work-osprey-x"); none = client.held_for("", "")
    acked = client.held_ack(X, gids)
finally:
    client.post = _real_post
check("7g: client.held_for (what the UserPromptSubmit hook prints) reads the endpoint once and answers empty with no session id; held_ack removes what it printed",
      "via the client" in got and len(gids) == 1 and again == ("", []) and none == ("", []) and acked and held.count(X) == 0, (got, gids, again, none, acked))
client.post = lambda what, body, timeout=20.0: (0, "unreachable")
try: down = client.held_for(X, "work-osprey-x"); down_ack = client.held_ack(X, ["abc"])
finally: client.post = _real_post
check("7h: …and empty when the server cannot be reached (a hook never fails a session)", down == ("", []) and down_ack is False)
with open(os.path.join(STACK, "stackshot/projects/pages.py"), encoding="utf-8") as f: nag = f.read().split("def cmd_nag", 1)[1].split("def cmd_check", 1)[0]
check("7i: the UserPromptSubmit hook every client install wires (pages.py nag) asks for the held lines, prints them, then acknowledges the ids", "held_for(sid, name)" in nag and "print(held" in nag and "held_ack(sid, ids)" in nag
      and nag.index("print(held") < nag.index("held_ack("))
check("7i2: …and does not ask when the server was already found unreachable in this run (UNREACHABLE)", "if not UNREACHABLE" in nag)

# at least once: a line the hook never acknowledged is offered again after its lease
fresh(); t1 = time.time() - 1000
held.add(held.key_of(X), "closed", "offered twice", now=t1)
tx1, id1 = held.lease(X, now=t1 + 1)
tx2, id2 = held.lease(X, now=t1 + 2)
tx3, id3 = held.lease(X, now=t1 + 1 + held.LEASE + 1)
check("7j: a leased line is not offered again inside the lease, is offered again once the lease runs out unacknowledged (at least once), and is stored until then",
      "offered twice" in tx1 and tx2 == "" and id2 == [] and "offered twice" in tx3 and id3 == id1 and held.count(X) == 1, (tx1, tx2, tx3, id1, id3))
check("7k: an acknowledgement removes it for good; an unknown id, or one of another session, removes nothing", held.ack(A, ids=id3) == 0 and held.count(X) == 1 and held.ack(X, ids=["nope"]) == 0 and held.ack(X, ids=id3) == 1 and held.count(X) == 0)
fresh()
for i in range(10): held.add(held.key_of(X), "closed", f"m{i}", now=t1 + i)
tx, idsA = held.lease(X, now=t1 + 20)
tx_b, idsB = held.lease(X, now=t1 + 21)
check("7l: the lines past the cap are not leased: the next ask gets them, and a leased line is not counted among the '+N more'", len(idsA) == 8 and "+2 more" in tx and len(idsB) == 2 and "m8" in tx_b and "more" not in tx_b.splitlines()[-1], (tx, tx_b))
held.ack(X, ids=idsA + idsB)
check("7m: take() is lease and acknowledge in one step (each line once)", (held.add(held.key_of(X), "fyi", "once", now=t1) and "once" in held.take(X, now=t1 + 1)) and held.take(X, now=t1 + 2) == "" and held.count(X) == 0)

# the endpoint checks the session as drain does: the machine must hold it, and the name is the server's record
fresh(); held.add(held.key_of(X), "closed", "for the builder", now=time.time()); held.add(held.key_of(D), "closed", "for the page keeper", now=time.time())
st, body_ = server._client_post(MACH, "held", {"uuid": X, "name": "work-osprey-docs"})
check("7n security: the name in the request is ignored: the session's lines are found by the server's record of it (a forged name draws the page keeper's lines to nobody)",
      st == 200 and "for the builder" in body_["text"] and "for the page keeper" not in body_["text"], body_)
held.ack(X, ids=body_["ids"])
st, body_ = server._client_post("home-other", "held", {"uuid": D, "name": "work-osprey-docs"})
check("7o security: another machine's token gets nothing for a session the server holds for home-test", st == 200 and body_ == {"text": "", "ids": []} and held.count(D) == 1, (st, body_))
st, body_ = server._client_post("home-other", "held", {"uuid": D, "ack": []})
st2, body2_ = server._client_post("home-other", "held", {"uuid": D, "ack": [r["id"] for r in held._read(held._file(held.key_of(D)))]})
check("7p security: …nor can it acknowledge (remove) them", held.count(D) == 1 and body2_ == {"text": "", "ids": []}, (body_, body2_, held.count(D)))
st, body_ = server._client_post(MACH, "held", {"uuid": "99999999-9999-4999-8999-999999999999", "name": "work-osprey-x"})
check("7q security: a transcript id the server does not hold for the machine gets nothing, and is not registered by the call", body_ == {"text": "", "ids": []} and "99999999-9999-4999-8999-999999999999" not in server._clients.sessions_on(MACH), body_)
st, body_ = server._client_post(MACH, "held", {"uuid": D, "ack": "all"})
check("7r: a malformed ack is refused", st == 400, (st, body_))

# the owner's mark comes from the instance, and a drop leaves a trace
saved_owner = _cfg.CFG.get("instance", {}).get("owner")
_cfg.CFG.setdefault("instance", {})["owner"] = "Alice"
check("7s: the owner's mark is the instance's ([for Alice]), not a fixed name", held.decide("closed", is_background=True, text="[for Alice] look") == "" and held.decide("closed", is_background=True, text="[for Oliver] look") == "closed")
_cfg.CFG["instance"]["owner"] = saved_owner
fresh()
import io, contextlib
err = io.StringIO()
with contextlib.redirect_stderr(err):
    for i in range(held.KEEP_MAX + 3): held.add(held.key_of(X), "closed", f"c{i}", now=time.time())
    held.add(held.key_of(D), "closed", "old", now=time.time() - 8 * 86400)
    held.lease(D, now=time.time())
check("7t: lines dropped by the cap or by age leave a stderr line", "1 notice for" in err.getvalue() and "more than" in err.getvalue() and "dropped unread: older than 7 days" in err.getvalue(), err.getvalue())
fresh()
old = held._file("retired-session"); old.write_text(json.dumps({"id": "z", "ts": time.time() - 30 * 86400, "kind": "closed", "text": "never read"}) + "\n", encoding="utf-8")
os.utime(old, (time.time() - 30 * 86400, time.time() - 30 * 86400))
with contextlib.redirect_stderr(io.StringIO()): held.add(held.key_of(X), "closed", "a new one", now=time.time())
check("7u: a retired session's file (untouched for KEEP_DAYS) is removed when anything is added", not old.exists() and held.count(X) == 1)

# the digest leaves out what is held for an agent
fresh()
nA = rec("[board] board#1 plain held by the router"); routing.rule(nA["id"], "held", reason="a router hold", by=_live.BY)
nB = rec("[board] board#1 completed (done) — page update", hold="page-owed"); resB = act(nB, "work-osprey-docs")
lnA = {"id": nA["id"], "project": KEY, "key": KEY, "status": "ruled", "ruling": "held", "ts": time.time()}
lnB = {**resB, "id": nB["id"], "project": KEY, "key": KEY, "ts": time.time()}
rows_, _q, _pp = _live._digest_items(KEY, time.time(), {nA["id"]: lnA, nB["id"]: lnB}, {"sent": {}})
check("7v: the digest lists a notice the router held for itself and leaves out one held for an agent's next turn (held_for), which would reach the agent twice",
      [r[1]["id"] for r in rows_] == [nA["id"]] and lnB.get("held_for") == "work-osprey-docs", ([r[1]["id"] for r in rows_], lnB))
fresh(); nid3 = routing.record(KEY, kind="message", to="", label="message to projects/alpha", who="falcon-audit", text=body, target="project-wide", pilot=True, live=True); _live.stash(nid3, body)
n3 = next(x for x in routing.read(KEY) if x["id"] == nid3)
res3 = _live._act(n3, KEY, KEY, {**ln, "id": nid3, "target": "work-osprey-x", "split": {"work-osprey-x": ["a1"]}}, cx, {})
rows3, _q, _pp = _live._digest_items(KEY, time.time(), {nid3: {**res3, "project": KEY, "key": KEY, "ts": time.time()}}, {"sent": {}})
check("7w: an audit finding is a task: delivered at once, nothing held for the agent (no held_for), and the digest does not list a passed notice", res3.get("held_for") is None and not res3.get("held_for") and res3.get("ruling") == "passed" and held.count(X) == 0 and rows3 == [], (res3, rows3))

fresh()
print(f"{len(ran) - len(fails)}/{len(ran)} checks passed" + ("" if not fails else f"; FAILED: {len(fails)}"))
sys.exit(1 if fails else 0)
