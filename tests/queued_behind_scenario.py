"""Scenario test for a mover busy on another item (model/queued.py, `[model] queued_behind`): an open item on an agent whose mover is working on another of its items reads WAITING, queued behind that
item, not on agent. Fixture items in a temporary store, a fake clock (every reader is given its `now`), no live store, no network, no model call, no message sent.

  1  the rule (queued.queue, the pure half): a mover with ONE on-agent item changes nothing; the item with the newest activity (metadata.last_activity) stays on agent and each other item with no activity for
     more than an hour is queued behind it; one with activity in the last hour stays; a tie goes to the lower number; an item in hand that is idle itself frees them all; the hour's edges; movers are separate
     (a name in another case is the same mover); a front agent's items and the owner's are never queued
  2  the gate: `[model] queued_behind` is off by default (the example config documents `false`), only a TOML true switches it on (the string "true" and 1 do not), read at use: off, every reader is as it was
  3  the reading (queued.overlay): a waiting reading of the item kind, `after` the item it is behind, `queued` set, the mover kept; the model line says it; a reading that is not alive is returned as it was
  4  the board: the home page's lists, board.md's lists and the item page read it (a queued item is under Waiting with `Queued behind <item>`, its mover still named, On agent holds the item in hand); the
     counts follow; gate off, nothing differs; a held, a parked, a waiting and an owner's item are untouched and never count as the item in hand
  5  it ends by itself: the mover moves a queued item (it has the newest activity: it is in hand and the other returns to agent once its own hour has passed), the item it waits behind closes, or its activity
     goes idle, or the mover is left with one item
  6  the shared reading (silence.reading, which the hourly line, the idle hand-over and the stall pass use) leaves a queued item off the agents as it does a waiting one and still reads the item in hand on agent; the gate off reads both
  7  the hourly audit line (hourly.due, hourly.pass_, server._hourly_tick) writes no line on a queued item and one on the item in hand
  8  the stall pass (stalltick_svc.stall_tick) takes no step on a queued item and still takes it on the item in hand
  9  the items sheet's list word (server._item_list) says waiting for a queued item
  4b the words: board.md and the brief (the head's waiting lines and the cards) say `queued behind <item>` for a queued item, never `waiting on another item's close`; the item page and the home row say it too;
     the wait a session stored as an item wait keeps its words
  4c the front test the board and the passes use: the one the server installed is the one used; a front test that cannot answer counts as front (nothing is queued on a guess), in the queue path only; the
     server's `front_keeper` answers False on an unreadable role map by default and True when asked strictly
  4d the readers' edges: an item behind a closed one is not queued, a record dated ahead of now, the 30 s memo, a failed read is swallowed
  10 revert-proof: each rule above is mutated (the newest item no longer chosen, the hour ignored, front agents queued, the gate ignored, a reader that no longer asks) and the check that guards it must fail

    tests/run-suite queued_behind      -> exit 0 / 1"""
import contextlib, datetime, io, json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="queuedbehind-"); T = pathlib.Path(tmp)
EXAMPLE = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
toml = _instance.apply(EXAMPLE)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
toml, n = re.subn(r'(?m)^(\[audit\][^\n]*\n)enabled = false', r'\g<1>enabled = true', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
(T / "home/.claude/sessions").mkdir(parents=True)                                              # an isolated HOME: never the host's pane registry
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state", "brain/projects", "transcripts/-home-x", "cli"): (T / d).mkdir(parents=True)
NAMES = ("home-front", "team-back", "home-peer", "home-peer2", "home-peer3", "home-stew")
U = {n: f"00000000-0000-4000-8000-0000000000{i:02d}" for i, n in enumerate(NAMES, 1)}
now0 = float(int(time.time()))
if min((now0 + 4 * 3600) % 86400, 86400 - (now0 + 4 * 3600) % 86400) < 4000: now0 -= 7200      # not near a local midnight: the times stay on one day
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": "2026-01-01T00:00:00Z"}}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
ALPHA = {"home-front": "the front", "team-back": "builds, merges and releases the code"}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                  "agents": ALPHA, "back_agents": {"team-back": ALPHA["team-back"]}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: builds, merges and releases the code\n---\n\n# alpha\n\n## Current state\n\nSTATE.\n\n<!-- timeline -->\n")
(T / "store/next-id").write_text("1"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
MIN = 60.0; H = 3600.0
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools")); logging.disable(logging.INFO)
from stackshot.web import server, home
from stackshot.service import asks as asks_svc, wait_gates as wait_gates_svc, answer_handover as handover_svc
from stackshot.service import messaging as _messaging
from stackshot.fleet import sessions_registry as _fleet_sessions_registry
from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import migrations as migsvc
from stackshot.service import page_debt as pdebt_svc
from stackshot.service import fleet_events as fleetev
from stackshot.service import handoff as handoff_svc
from stackshot.service import handoff_cold as hcold_svc
from stackshot.service import checks as checks_svc, proofs as proofs_svc, released as released_svc
from stackshot.service import pane_recovery as _pane_recovery
from stackshot.service import mover_steps as _mover_steps
from stackshot.service import owner_words as _owner_words
from stackshot.service import ladder as ladder_svc, stall as stall_svc, stall_tick as stalltick_svc
from stackshot.web.tools import sessions as _wt_sessions
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.service import telling
from stackshot.web.ui import render as UI
from stackshot.web import render as MD
from stackshot.audit import hourly as HR, silence as SL, audit_run as AR, audit_checks as AC
from stackshot.audit import hourly_log as HL
from stackshot.model import queued as Q, model as MODEL
from stackshot.tools import next_report as NR
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
telling.PUSH = [sys.executable, "-c", "pass"]
class _Clock:
    """The server's `time` module for the passes below: each is given its `now`, and the saves stamp from the server's own clock."""
    t = None
    def __getattr__(self, n): return getattr(time, n)
    def time(self): return time.time() if self.t is None else self.t
CLK = _Clock(); server.time = fleetev.time = migsvc.time = pdebt_svc.time = handoff_svc.time = hcold_svc.time = checks_svc.time = proofs_svc.time = released_svc.time = asks_svc.time = wait_gates_svc.time = handover_svc.time = _pane_recovery.time = _mover_steps.time = _owner_words.time = stall_svc.time = stalltick_svc.time = CLK
_cfg.CFG["audit"]["pattern_review"] = "off"; _cfg.CFG["audit"]["mode"] = "script"
sent = []                                                          # every message the server was asked to send: none is expected here
_messaging._message = lambda to, text, sender, auth="", origin="", fyi=False: (sent.append((to, text)), "delivered to " + to)[1]
telling.tell_woken = lambda *a, **k: sent.append(("tell_woken", a))
fleetev.inbox_flag_send = lambda *a, **k: sent.append(("flag", a))
REAL = {(m, n): getattr(m, n) for m, n in ((handoff_svc, "handoff_status"), (_fleet_sessions_registry, "_sessions_index"), (handoff_svc, "_sessions_index"), (hcold_svc, "_sessions_index"))}      # the stall pass below reads the real ones
handoff_svc.handoff_status = lambda who, idx=None: ("", 0.0)
_fleet_sessions_registry._sessions_index = fleetev._sessions_index = pdebt_svc._sessions_index = _wt_sessions._sessions_index = handoff_svc._sessions_index = hcold_svc._sessions_index = proofs_svc._sessions_index = stalltick_svc._sessions_index = ladder_svc._sessions_index = lambda: {}
FRONT = {"home-front"}
REAL_HOOK = Q.front_hook()                                         # what the server installed (`front_keeper`, strict), before the fixture's own answer replaces it
Q._HOOKS["is_front"] = lambda who, project: str(who) in FRONT      # the server's `front_keeper` is replaced by the one front agent of the fixture
ROLES = {"home-front": {"role": "front"}, "team-back": {"role": "background"}, "home-peer": {"role": "background"}}
def env(): return AR.Env(roles=ROLES, fallback=lambda p: "home-front", builder=lambda p: "team-back", page_of=lambda p: ("", None), sessions=lambda: None,
                         deliver=lambda to, text, fyi=False: (True, "[200] ok"), push=lambda to, text: (True, "delivered"))
def on(): _cfg.CFG.setdefault("model", {})["queued_behind"] = True
def off(): _cfg.CFG.setdefault("model", {}).pop("queued_behind", None)
def bid(n): return NR.shown(f"a{n}")      # an item as the pass words it

def put(i, mover="home-peer", act=180, last=None, status="open", **meta):
    """An open doing item of `mover`: its silence clock (`activity`, the last write) was `act` minutes before now0, and its last_activity record (`last`, minutes before now0; None: no record) is the visible activity."""
    base = {"owner": U["home-front"], "project": "projects/alpha", "next": f"{mover}: do the thing", "state": "doing", "needs": [mover], "mover": mover}
    base.update(meta)
    if last is not None: base["last_activity"] = {"at": now0 - last * MIN, "kind": "step_done", "what": "step 1 done"}
    at = now0 - act * MIN
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status, "updated": at, "state_updated": at, "confirmed": at,
                                                       "activity": at, "written_at": at, "written_by": mover, "metadata": base}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def wipe():
    for p in (T / "store/a").glob("*.json"): p.unlink()
def items(): return NR.load_all(T / "store")
def board(at=None, md=False):
    b = (MD if md else UI).Board(str(T / "store"), now=datetime.datetime.fromtimestamp(now0 if at is None else at, datetime.timezone.utc))
    b.provision = [("home-box", True)]; b._rel_ids = set()
    return b
def lists_of(b): return {w: sorted(r["gid"] for r, _m in ps) for w, ps in b.home_lists().items()} if hasattr(b, "home_lists") else {w: sorted(r["gid"] for r, _m in ps) for w, ps in b.home_pairs().items()}

# ================================================================ 1. the rule (pure)
def c(gid, mover="m", ago=None, project="projects/alpha"): return (gid, mover, project, 0.0 if ago is None else now0 - ago * MIN)
q = lambda *cs, **kw: Q.queue(list(cs), now0, **kw)
check("1 one item for a mover changes nothing", q(c("a1", ago=200)) == {} and q(c("a1", ago=1)) == {} and q() == {})
check("1 the item with the newest activity stays on agent; each other idle for more than an hour is queued behind it", q(c("a1", ago=10), c("a2", ago=120), c("a3", ago=300)) == {"a2": "a1", "a3": "a1"})
check("1 an item with activity in the last hour stays on agent too (both are in hand)", q(c("a1", ago=10), c("a2", ago=30), c("a3", ago=120)) == {"a3": "a1"})
check("1 the newest is chosen by activity, not by number or by order", q(c("a1", ago=200), c("a5", ago=5), c("a3", ago=90)) == {"a1": "a5", "a3": "a5"} and q(c("a3", ago=90), c("a5", ago=5), c("a1", ago=200)) == {"a1": "a5", "a3": "a5"})
check("1 a tie in activity goes to the lower number (the order of the candidates is no part of it)", q(c("a9", ago=10), c("a2", ago=10), c("a4", ago=200)) == {"a4": "a2"} and q(c("a2", ago=10), c("a9", ago=10), c("a4", ago=200)) == {"a4": "a2"})
check("1 the item in hand must have had activity within the hour itself: a mover whose newest item is idle too is working on none of them", q(c("a1", ago=90), c("a2", ago=200)) == {} and q(c("a1", ago=0.0), c("a2", ago=200)) != {})
check("1 an item with no activity record (time 0) is never in hand, and is queued behind one that has", q(c("a1"), c("a2")) == {} and q(c("a1"), c("a2", ago=5)) == {"a1": "a2"})
check("1 the edges: exactly an hour idle is not queued, a second more is; the item in hand may be exactly an hour old, not a second more", q(c("a1", ago=1), c("a2", ago=60)) == {} and q(c("a1", ago=1), ("a2", "m", "p", now0 - 3600 - 1)) == {"a2": "a1"}
      and q(c("a1", ago=60), ("a2", "m", "p", now0 - 7200)) == {"a2": "a1"} and q(("a1", "m", "p", now0 - 3601), ("a2", "m", "p", now0 - 7200)) == {})
check("1 movers are separate, and a name in another case is the same mover", q(c("a1", "m1", 5), c("a2", "m2", 200), c("a3", "m1", 200), c("a4", "m2", 5)) == {"a3": "a1", "a2": "a4"} and q(c("a1", "Home-Peer", 5), c("a2", "home-peer", 200)) == {"a2": "a1"})
check("1 a front agent's items are never queued (the answer for the project of each item), and neither are the owner's or no one's",
      q(c("a1", "home-front", 5), c("a2", "home-front", 200), is_front=lambda w, p: w == "home-front") == {} and q(c("a1", "home-front", 5), c("a2", "home-front", 200), is_front=lambda w, p: False) == {"a2": "a1"}
      and q(c("a1", "Oliver", 5), c("a2", "Oliver", 200)) == {} and q(c("a1", "", 5), c("a2", "", 200)) == {})
check("1 a front test that raises leaves the items as they were", q(c("a1", ago=5), c("a2", ago=200), is_front=lambda w, p: 1 / 0) == {})
check("1 a record dated ahead of now is read as now, not as newer than every other", q(("a1", "m", "p", now0 + 10 * H), ("a2", "m", "p", now0 - 5 * MIN), ("a3", "m", "p", now0 - 2 * H)) == {"a3": "a1"} and Q.candidate("a1", {"metadata": {"last_activity": {"at": now0 - 5, "kind": "step_done", "what": "x"}}}, "m", now0)[3] == now0 - 5)
check("1 candidate: the record's time, 0 with no record or a torn one", Q.candidate("a1", {"metadata": {}}, "m", now0)[3] == 0.0 and Q.candidate("a1", {"metadata": {"last_activity": {"at": "soon", "kind": "step_done", "what": "x"}}}, "m", now0)[3] == 0.0)

# ================================================================ 2. the gate
check("2 the example config documents `queued_behind = false` in [model], and the config as loaded has it off", re.search(r"(?m)^queued_behind = false\b", EXAMPLE) is not None and Q.enabled() is False)
for label, val in (("the string true", "true"), ("1", 1), ("yes", "yes"), ("false", False)):
    _cfg.CFG.setdefault("model", {})["queued_behind"] = val
    check(f"2 {label} does not switch it on (only a TOML true does)", Q.enabled() is False)
on(); check("2 a TOML true switches it on, read at use", Q.enabled() is True); off(); check("2 …and removing it switches it off again", Q.enabled() is False)

# ================================================================ 3. the reading
alive = MODEL.derive({"status": "open", "metadata": {"state": "doing", "needs": ["home-peer"], "mover": "home-peer"}}, now0)
ov = Q.overlay(alive, "a7")
check("3 overlay: waiting, of the item kind, after the item in hand, queued, the same mover, no `then`", ov.state == MODEL.WAITING and ov.wait.kind == "item" and ov.wait.after == ("a7",) and ov.wait.queued is True and ov.wait.mover == "home-peer" and not ov.then and not ov.wait.due, ov)
check("3 …the line of get says it", MODEL.words(ov, shown=lambda g: "x" + g[1:], derived=False) == "model: waiting on the mover's other item (queued behind x7) · mover home-peer", MODEL.words(ov, shown=lambda g: "x" + g[1:], derived=False))
check("3 …a wait stored as an item wait is not a queue (queued is False)", MODEL.words(MODEL.derive({"status": "open", "metadata": {"state": "blocked", "after": ["a1"], "wait_kind": "item", "mover": "home-peer"}}, now0)).startswith("model: waiting on the close of"))
check("3 a reading that is not alive, or no item to queue behind, is returned as it was", Q.overlay(ov, "a9") is ov and Q.overlay(alive, "") is alive and Q.overlay(MODEL.Model(MODEL.DEAD), "a9").state == MODEL.DEAD)
check("3 the reason: `queued behind <item>`", Q.reason("a12", lambda g: "x" + g[1:]) == "queued behind x12")

# ================================================================ 4. the board
def fixture():
    wipe()
    put(1, act=180, last=10)                                   # in hand: visible activity ten minutes ago
    put(2, act=180, last=120)                                  # idle two hours: queued
    put(3, act=180, last=30)                                   # activity within the hour: stays on agent
    put(4, act=180, last=300)                                  # idle five hours: queued
    put(5, mover="home-peer2", act=180, last=300)              # a mover with ONE item: nothing changes
    put(6, mover="home-front", act=180, last=5); put(7, mover="home-front", act=180, last=400)     # a front agent's items: nothing changes
    put(8, act=180, last=1, hold=True, wake=time.strftime("%Y-%m-%dT%H:%M", time.gmtime(now0 + 30 * H + 4 * H)), wait_basis={"text": "the vendor ships", "wake": time.strftime("%Y-%m-%dT%H:%M", time.gmtime(now0 + 30 * H + 4 * H)), "by": "home-peer", "at": now0})      # held until a dated wake, the NEWEST activity of home-peer: it is waiting, so it is no item in hand
    put(9, mover="home-peer3", act=180, last=10); put(10, mover="home-peer3", act=180, last=200, hold=True, wake=time.strftime("%Y-%m-%dT%H:%M", time.gmtime(now0 + 30 * H + 4 * H)), wait_basis={"text": "x", "wake": time.strftime("%Y-%m-%dT%H:%M", time.gmtime(now0 + 30 * H + 4 * H)), "by": "home-peer3", "at": now0})   # a waiting item beside the one on agent
    put(11, act=180, last=500, state="parked", hold=True, wake=time.strftime("%Y-%m-%d", time.gmtime(now0 + 5 * 86400)), cap_ok=True)    # parked: untouched
    put(12, act=180, last=500, mover="Oliver", state="your-call", needs=["decision"], ask="pick one", next="Oliver: pick")             # the owner's move: untouched
fixture()
AG, WT, YM = home.AGENTS, home.WAITING, home.YOUR_MOVE
for label, md in (("the home page's Board", False), ("board.md's Board", True)):
    off(); L0 = {w: ids for w, ids in lists_of(board(md=md)).items() if w in (AG, WT, YM)}
    on(); b = board(md=md); L1 = {w: ids for w, ids in lists_of(b).items() if w in (AG, WT, YM)}; off()
    check(f"4 {label}: the gate off, the items sit as they always did (every on-agent item of home-peer on agent, the held one waiting)", {"a1", "a2", "a3", "a4"} <= set(L0[AG]) and "a8" in L0[WT] and "a2" not in L0[WT], L0)
    check(f"4 {label}: the gate on, the idle ones of the busy mover move to Waiting; the item in hand and the one with activity in the hour stay", "a2" in L1[WT] and "a4" in L1[WT] and {"a1", "a3"} <= set(L1[AG]) and not ({"a2", "a4"} & set(L1[AG])), L1)
    check(f"4 {label}: one item for its mover (a5), a front agent's two (a6, a7), the waiting ones (a8, a10), the parked one (a11) and the owner's (a12) are exactly as before",
          "a5" in L1[AG] and "a6" in L1[AG] and "a7" in L1[AG] and "a9" in L1[AG] and {"a8", "a10", "a11"} <= set(L1[WT]) and "a12" in L1[YM] and L0[YM] == L1[YM], (L0, L1))
    check(f"4 {label}: only the two idle items changed list", sorted(set(L0[AG]) - set(L1[AG])) == ["a2", "a4"] and sorted(set(L1[WT]) - set(L0[WT])) == ["a2", "a4"] and set(L1[AG]) <= set(L0[AG]), (L0, L1))
on(); b = board()
pairs = {r["gid"]: m for ps in b.home_pairs().values() for r, m in ps}
check("4 a queued item's reading is waiting on an item, after the item in hand, with its own mover (the home page names the mover on the row)", pairs["a2"].state == MODEL.WAITING and pairs["a2"].wait.kind == "item" and pairs["a2"].wait.after == ("a1",)
      and pairs["a2"].wait.queued and pairs["a2"].wait.mover == "home-peer" and pairs["a4"].wait.after == ("a1",), pairs["a2"])
rows = {r["gid"]: r for ps in b.home_pairs().values() for r, m in ps}
hrow = b.home_row(rows["a2"], pairs["a2"], WT, named=True)
check("4 its row says `Queued behind` with a link to the item in hand, never `After`, and names the mover", "Queued behind <a" in hrow and 'href="/items/a1"' in hrow and "After <a" not in hrow and "home-peer" in hrow, hrow[:900])
page = b.item_html("a2")
check("4 its item page names the item in hand, says why it waits, and shows it as waiting (the item in hand shows no such line)", 'href="/items/a1"' in page and "its mover is working on that item first" in page and "its mover is working on that item first" not in b.item_html("a1"), page[:200])
cnt = b.phase_counts()
off(); cnt0 = board().phase_counts(); on()
check("4 the counts follow the lists: open the same, two fewer on agent, two more waiting", cnt["open"] == cnt0["open"] and cnt["agents"] == cnt0["agents"] - 2 and cnt["waiting"] == cnt0["waiting"] + 2 and cnt["alive"] == cnt0["alive"] - 2, (cnt, cnt0))
check("4 a queued item's state kind is Waiting (the state pill of its row and page)", b.state_kind(rows["a2"]) == UI._ui.kind_of_list(WT) and b.state_kind(rows["a1"]) == UI._ui.kind_of_list(AG), (b.state_kind(rows["a2"]), b.state_kind(rows["a1"])))
check("4 the item in hand never reads waiting, even when the newest of two movers' items is another mover's", pairs["a1"].state == MODEL.ALIVE and pairs["a9"].state == MODEL.ALIVE)
check("4 nothing is stored: the files of the items are as the fixture wrote them (no phase, no wait, no mover change)", all(set(rd(i)["metadata"]) - {"last_activity", "state", "needs", "next", "owner", "project", "mover", "hold", "wake", "wait_basis", "cap_ok", "ask"} == set() for i in range(1, 13)), rd(2)["metadata"])

# ================================================================ 4b. the words
def home_lists_at(at=None, md=False): return {w: ids for w, ids in lists_of(board(at, md)).items() if w in (AG, WT)}
def base():
    wipe()
    put(1, act=180, last=10); put(2, act=180, last=120); put(3, act=180, last=30); put(4, mover="home-peer2", act=180, last=300)
    put(5, mover="home-front", act=180, last=5); put(6, mover="home-front", act=180, last=400)
    put(7, act=180, last=1, hold=True, wake=time.strftime("%Y-%m-%dT%H:%M", time.gmtime(now0 + 30 * H + 4 * H)), wait_basis={"text": "the vendor ships", "wake": time.strftime("%Y-%m-%dT%H:%M", time.gmtime(now0 + 30 * H + 4 * H)), "by": "home-peer", "at": now0})
class mutate:
    def __init__(self, mod, name, fn): self.mod, self.name, self.fn = mod, name, fn
    def __enter__(self): self.old = getattr(self.mod, self.name); setattr(self.mod, self.name, self.fn)
    def __exit__(self, *a): setattr(self.mod, self.name, self.old)
def two():
    wipe(); put(1, act=180, last=10); put(2, act=180, last=120)
two(); on()
for label, md in (("the home page's Board", False), ("board.md's Board", True)):
    b = board(md=md); out = b.render(("brief", "full")); brief, full = out["brief"], out["full"]; sf = (MD if md else UI).shown_full      # an item as that board writes it
    wl = [x for x in brief.splitlines() if x.lstrip().startswith("waiting:")]
    check(f"4b {label}: the brief's waiting line says `queued behind <item>` and names the item in hand", len(wl) == 1 and wl[0].rstrip().endswith(f"· queued behind {sf('a1')}") and "another item's close" not in wl[0], wl)
    meta = [x for x in full.splitlines() if x.startswith("- p2") and "queued" in x]
    check(f"4b {label}: board.md's card for the queued item says `queued behind <item>` in its meta line, and no card says `waiting on another item's close`", len(meta) == 1 and meta[0].startswith(f"- p2 · queued behind {sf('a1')}") and "waiting on another item's close" not in full, meta)
    check(f"4b {label}: the item in hand has no such words (only the queued item's card carries one)", len(meta) == 1 and full.count("queued behind") == 1 and brief.count("queued behind") == 1, (full.count("queued behind"), brief.count("queued behind")))
    off(); out0 = board(md=md).render(("brief", "full")); on()
    check(f"4b {label}: the gate off, neither text says queued (the item is on agent)", "queued behind" not in out0["brief"] and "queued behind" not in out0["full"])
b = board(); pairs = {r["gid"]: m for ps in b.home_pairs().values() for r, m in ps}; rows = {r["gid"]: r for ps in b.home_pairs().values() for r, m in ps}
check("4b the home row says `Queued behind` (once, with the link) and the item page says why", b.home_row(rows["a2"], pairs["a2"], WT, named=True).count("Queued behind") == 1 and "its mover is working on that item first" in b.item_html("a2"))
stored = MODEL.derive({"status": "open", "metadata": {"state": "blocked", "after": ["a1"], "wait_kind": "item", "mover": "home-peer"}}, now0)
check("4b wait_phrase: a queued reading says `queued behind <item>`, whatever the prefix; the item as `shown` writes it", home.wait_phrase(pairs["a2"], "on", lambda g: "x" + g[1:]) == "queued behind x1" and home.wait_phrase(pairs["a2"], "waiting on") == "queued behind a1", home.wait_phrase(pairs["a2"], "waiting on"))
check("4b …a wait a session stored as an item wait keeps its words, with the prefix; an alive reading has none", home.wait_phrase(stored, "on") == "on " + home.wait_words(stored) and home.wait_words(stored) and "queued" not in home.wait_phrase(stored, "on") and home.wait_phrase(pairs["a1"], "on") == "")
check("4b …a queued reading with no item to name still reads queued", home.wait_phrase(MODEL.Model(MODEL.WAITING, "", False, "", False, "", False, "", MODEL.Wait(kind="item", kind_explicit=False, after=(), mover="m", mover_explicit=False, due=False, queued=True), ()), "on") == "queued behind an item")
off()

# ================================================================ 4c. the front test
check("4c the board asks the front test the server installed (home.front_test is the installed one); with none installed it is the role map's, which counts an unreadable map as front",
      home.front_test() is Q.front_hook() and Q.front_hook() is not None, home.front_test())
saved = Q._HOOKS["is_front"]
Q.configure(is_front=lambda who, project: True); on(); two()
check("4c …an installed `everyone is front` answer is used by the board: nothing is queued", "a2" in home_lists_at()[AG] and not home_lists_at()[WT])
Q.configure(is_front=lambda who, project: False); two()
check("4c …and `no one is front`: the idle item is queued", "a2" in home_lists_at()[WT])
Q.configure(is_front=lambda who, project: 1 / 0); two()
check("4c …a hook that raises queues nothing", "a2" in home_lists_at()[AG] and not home_lists_at()[WT])
Q._HOOKS["is_front"] = None
fn = home.front_test()
check("4c with no hook installed the role map's front test (is_front_safe) is used", getattr(fn, "__name__", "") == "is_front_safe", fn)
Q._HOOKS["is_front"] = saved; off()
class Boom(Exception): pass
def boom(*a, **k): raise Boom("roles unreadable")
check("4c Env.is_front_safe: an unreadable role map counts as front; a front test that raises counts as front; Env.is_front (every other caller) keeps False for a test that raises",
      AR.Env(front=boom).is_front_safe("home-peer", "projects/alpha") is True and AR.Env(front_strict=boom).is_front_safe("home-peer") is True and AR.Env(front=boom).is_front("home-peer", "projects/alpha") is False)
check("4c …an answer it can read is kept: no for a background agent, yes for a front agent (the role map, the server's test, the strict test)",
      AR.Env(roles=ROLES).is_front_safe("home-peer") is False and AR.Env(roles=ROLES).is_front_safe("Home-Front") is True and AR.Env(front=lambda w, p: w == "x").is_front_safe("x") is True
      and AR.Env(front_strict=lambda w, p: False, front=lambda w, p: True).is_front_safe("x") is False)
check("4c …no roles given and no registry to read: it counts as front (the isolated HOME has none)", AR.Env().is_front_safe("home-peer") in (True, False))
base(); on()
check("4c the passes' queue asks the safe test: nothing is queued when the front test cannot answer (Env.front_strict raises), the item is queued when it says no",
      SL.queued(items(), now0, AR.Env(roles=ROLES, front_strict=boom)) == {} and SL.queued(items(), now0, AR.Env(roles=ROLES, front_strict=lambda w, p: False)) == {"a2": "a1", "a6": "a5"}, SL.queued(items(), now0, AR.Env(roles=ROLES, front_strict=lambda w, p: False)))
roles_ok = {"home-peer": {"role": "background", "project": "projects/alpha"}, "home-front": {"role": "front", "project": "projects/alpha"}}
anc_roles = _anc.session_roles
_anc.session_roles = lambda *a, **k: roles_ok
try:
    ok = (REAL_HOOK("home-peer", "projects/alpha"), REAL_HOOK("home-front", "projects/alpha"), telling.front_keeper("home-front", "projects/alpha", True), telling.front_keeper("home-peer", "projects/alpha", True))
finally: _anc.session_roles = anc_roles
check("4c the server's installed hook (strict `front_keeper`) answers from the roles: no for a background agent, yes for a front agent whatever its project", ok[:2] == (False, True) and ok[2] == (True, "") and ok[3] == (False, ""), ok)
_anc.session_roles = boom
try: bad = (REAL_HOOK("home-peer", "projects/alpha"), telling.front_keeper("home-peer", "projects/alpha"), telling.front_keeper("home-peer", "projects/alpha", True))
finally: _anc.session_roles = anc_roles
check("4c a role map that cannot be read: the installed hook says front (nothing queued); `front_keeper` keeps False for every other caller, and says (True, \"\") when asked strictly", bad == (True, (False, ""), (True, "")), bad)
check("4c …so the whole board queues nothing while the roles are unreadable, and queues as before once they read",
      (lambda: (_anc.__setattr__("session_roles", boom), Q.configure(is_front=lambda who, project: telling.front_keeper(who, project, True)[0]), two(), on(), home_lists_at())[-1])()[WT] == [], "")
_anc.session_roles = lambda *a, **k: roles_ok; two(); on(); L = home_lists_at()
check("4c …and once the roles read, the idle item of the background agent is queued again", "a2" in L[WT], L)
_anc.session_roles = anc_roles; Q._HOOKS["is_front"] = saved; off()

# ================================================================ 4d. the readers' edges
wipe(); put(1, act=180, last=5, status="completed"); put(2, act=180, last=30); put(3, act=180, last=200)
on(); qm = SL.queued(items(), now0, env())
check("4d silence.queued: a closed item is no item in hand and none queues behind it (a3 behind a2, never behind the closed a1)", qm == {"a3": "a2"}, qm)
wipe(); put(1, act=180, last=5, status="completed"); put(2, act=180, last=200)
check("4d …a mover left with one open item queues nothing", SL.queued(items(), now0, env()) == {})
off()
far = {"metadata": {"last_activity": {"at": now0 + 10 * H, "kind": "step_done", "what": "x"}}}; near = {"metadata": {"last_activity": {"at": now0 + 10 * MIN, "kind": "step_done", "what": "x"}}}
check("4d candidate: a record dated more than the skew ahead is no record (0); one a little ahead reads as now", Q.candidate("a1", far, "m", now0)[3] == 0.0 and Q.candidate("a1", near, "m", now0)[3] == now0, (Q.candidate("a1", far, "m", now0), Q.candidate("a1", near, "m", now0)))
check("4d …so a far-future record never holds an item in hand over a real one", q(("a1", "m", "p", Q.candidate("a1", far, "m", now0)[3]), c("a2", ago=5), c("a3", ago=200)) == {"a1": "a2", "a3": "a2"})
base(); on(); server._QUEUE_CACHE.update(at=0.0, map={})
m1 = server._queue_map(now0); put(3, act=180, last=1); put(2, act=180, last=300)
m2 = server._queue_map(now0 + 20); m3 = server._queue_map(now0 + 40)
check("4d _queue_map: the answer is kept for 30 seconds (the same map within it, the store read again after it)", m1 == {"a2": "a1"} and m2 is m1 and m3 != m1, (m1, m2, m3))
real_queued = SL.queued
def failing(*a, **k): raise OSError("store unreadable")
err = io.StringIO()
with mutate(SL, "queued", failing):
    server._QUEUE_CACHE.update(at=0.0, map={"a9": "a8"})
    old_err, sys.stderr = sys.stderr, err
    try: swallowed = server._queue_map(now0 + 100)
    finally: sys.stderr = old_err
check("4d a read that fails is swallowed: {} and a line on stderr, never an error to the caller; and it is not kept (the next call reads again)", swallowed == {} and "queued: not read" in err.getvalue() and server._QUEUE_CACHE["map"] == {"a9": "a8"}, (swallowed, err.getvalue()))
off(); check("4d …and with the gate off the map is {} without reading anything", server._queue_map(now0 + 200) == {})

# ================================================================ 5. it ends by itself
wipe(); put(1, act=180, last=10); put(2, act=180, last=120)
on(); check("5 setup: a2 is queued behind a1", "a2" in home_lists_at()[WT])
put(2, act=180, last=0)                                                           # the mover moves it: now it has the newest activity
L = home_lists_at()
check("5 the mover moves a2: a2 is on agent, in hand, and a1 (activity ten minutes ago, within the hour) stays on agent too", {"a1", "a2"} <= set(L[AG]) and not L[WT], L)
L = home_lists_at(now0 + 55 * MIN)
check("5 …55 minutes on, a1 has been idle for 65 minutes and a2 for 55: a1 is queued behind a2, which is in hand", "a1" in L[WT] and "a2" in L[AG], L)
put(1, act=180, last=10); put(2, act=180, last=120, status="open"); (T / "store/a/1.json").write_text(json.dumps({**rd(1), "status": "completed"}))
L = home_lists_at()
check("5 the item it waits behind closes: a2 returns to agent (one item left for its mover)", "a2" in L[AG] and not L[WT], L)
put(1, act=180, last=90); put(2, act=180, last=120)
L = home_lists_at()
check("5 the item in hand goes idle (no activity for an hour): nothing is queued, both are on agent, for the hourly line to reach", {"a1", "a2"} <= set(L[AG]) and not L[WT], L)
put(1, act=180, last=10); put(2, act=180, last=120, mover="home-peer2")
check("5 a2 is handed to another mover: it is on agent again (and alone for its new mover)", "a2" in home_lists_at()[AG])
off(); put(1, act=180, last=10); put(2, act=180, last=120)
check("5 the gate off: nothing is queued whatever the activity", "a2" in home_lists_at()[AG])

# ================================================================ 6. the shared reading
base()
def found(at=None):
    """The ids of the open items that read on agent (`silence.reading`, with the queue the passes read once per round)."""
    at = now0 if at is None else at; its = items(); line = SL.queued(its, at, env()); out = []
    for g in sorted(its, key=AC._num):
        if its[g].get("status") != "open": continue
        it, _m, ao, mv = AC._item_view(its, g)
        if SL.reading(it, mv, ao, at, line.get(g, "")) == "agent": out.append(bid(int(g[1:])))
    return out
off(); g0 = found()
on(); g1 = found()
check("6 the gate off: every on-agent item reads on agent (a1 a2 a3 a4 a5 a6); the held one does not", g0 == [bid(i) for i in (1, 2, 3, 4, 5, 6)], g0)
check("6 the gate on: the queued item (a2) does not read on agent; the item in hand, the one active in the hour, the one-item mover and the front agent's two do", g1 == [bid(i) for i in (1, 3, 4, 5, 6)], g1)
check("6 reading: a queued item is not on agent for silence.reading, an unqueued one is", SL.reading({"metadata": {"state": "doing", "needs": ["x"], "mover": "x"}, "status": "open"}, "x", lambda i: [], now0, "a1") == "" and SL.reading({"metadata": {"state": "doing", "needs": ["x"], "mover": "x"}, "status": "open"}, "x", lambda i: [], now0) == "agent")

# ================================================================ 7. the hourly audit line
def lines(i): return HL.log_of(rd(i)["metadata"])
base(); _cfg.CFG["audit"]["hourly_line"] = True
off(); got0 = [g for g, _l in HR.pass_(items(), now0, env(), None, None)]
on(); got1 = [g for g, _l in HR.pass_(items(), now0, env(), None, None)]
check("7 the gate off: a line is owed on every silent on-agent item, a2 included", got0 == ["a1", "a2", "a3", "a4", "a5", "a6"], got0)
check("7 the gate on: none on the queued item", got1 == ["a1", "a3", "a4", "a5", "a6"], got1)
check("7 due() on its own reads the queue too (a queued item is owed none; the item in hand is)", HR.due(items(), "a2", now0, env()) is None and HR.due(items(), "a1", now0, env()) is not None)
written = server._hourly_tick(now=now0, items=None, env=env(), pane=lambda who: "")
check("7 the tick writes the line on the item in hand and none on the queued one", "a1" in written and "a2" not in written and len(lines(1)) == 1 and lines(2) == [], (written, lines(1), lines(2)))
off(); wrote_off = server._hourly_tick(now=now0 + 70 * MIN, items=None, env=env(), pane=lambda who: "")
check("7 the gate off again: the line is owed on a2", "a2" in wrote_off and len(lines(2)) == 1, wrote_off)
check("7 nothing was sent to anyone", sent == [], sent)

# ================================================================ 8. the stall pass
def stall_rows():
    wipe()
    B = now0 - 900.0
    for i, last in ((1, 5), (2, 150)):
        put(i, act=15, last=last)                                                  # written at B: the first step is due ten minutes after the pane went idle
        d = rd(i); d["metadata"]["last_activity"] = {"at": now0 - 20 * MIN - last * MIN + 20 * MIN, "kind": "step_done", "what": "step 1 done"}; (T / f"store/a/{i}.json").write_text(json.dumps(d))
    return B
PUSHLOG = T / "push.log"
(T / "fakepush.py").write_text(f"import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nopen({str(PUSHLOG)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered → ' + a[0])\n")
telling.PUSH = [sys.executable, str(T / "fakepush.py")]
handoff_svc.CLI_SESSIONS = T / "cli"
for (_m, _n), _f in REAL.items(): setattr(_m, _n, _f)
_cfg.CFG["model"] = {}; _cfg.CFG["stall"] = {}
def cli_row(who, status, at): (T / f"cli/{os.getpid()}-{who}.json").write_text(json.dumps({"pid": os.getpid(), "kind": "interactive", "sessionId": U[who], "name": who, "status": status, "statusUpdatedAt": int(at * 1000), "updatedAt": int(at * 1000)}))
def stk(at, gate):
    stall_svc.STALL_LAST[0] = 0.0; server._QUEUE_CACHE.update(at=0.0, map={})
    (on if gate else off)()
    CLK.t = at
    try: return stalltick_svc.stall_tick(at)
    finally: CLK.t = None
for gate in (False, True):
    for p in (T / "state").glob("stall*.json"): p.unlink()
    B = stall_rows(); stall_svc.stall_since(B)
    (T / "cli" / f"{os.getpid()}-home-peer.json").unlink(missing_ok=True)
    cli_row("home-peer", "idle", B + 60)
    T1 = B + 60 + 10 * MIN + 1
    done = stk(T1, gate)
    check(f"8 stall pass, gate {'on' if gate else 'off'}: " + ("the notice goes to the item in hand only (a1), none on the queued item (a2)" if gate else "a notice goes on both items (a1, a2) as it always did"),
          ("a1" in done and "a2" not in done) if gate else ({"a1", "a2"} <= set(done)), done)
    if gate:
        S = __import__("stackshot.waits.stall", fromlist=["x"])
        check("8 …and the queued item has no stall log entry", not S.log_of(rd(2)["metadata"]) and S.log_of(rd(1)["metadata"]), (S.log_of(rd(2)["metadata"]), S.log_of(rd(1)["metadata"])))

# ================================================================ 9. the items sheet's list word and the server's map
@contextlib.contextmanager
def at_now0():
    """The server's clock stand-in (CLK) reads now0 while the block runs. The data above is built at now0, which the midnight guard may have moved two hours back, and `server._queue_map()` with no argument asks the server's clock for the time (CLK.t None reads the real one)."""
    was = CLK.t; CLK.t = now0
    try: yield
    finally: CLK.t = was
base(); on(); server._QUEUE_CACHE.update(at=0.0, map={})
with at_now0():
    check("9 _item_list: waiting for a queued item, agents for the item in hand and for a mover's only item", server._item_list(dict(rd(2), gid="a2")) == home.WAITING and server._item_list(dict(rd(1), gid="a1")) == home.AGENTS and server._item_list(dict(rd(4), gid="a4")) == home.AGENTS)
    check("9 _queue_map: {a2: a1} and nothing for the others", server._queue_map(now0, items()) == {"a2": "a1"}, server._queue_map(now0, items()))
    off(); check("9 …and {} with the gate off", server._queue_map(now0, items()) == {} and server._item_list(dict(rd(2), gid="a2")) == home.AGENTS)

# ================================================================ 10. revert-proof: each rule mutated, the guard must fail
def observe():
    """What the rules above promise, as a few observations over the fixture: the pure queue, the passes' scopes."""
    out = {}
    out["q"] = q(c("a1", ago=10), c("a2", ago=120), c("a3", ago=30), c("a4", ago=300))
    out["one"] = q(c("a1", ago=300))
    out["front"] = q(c("a1", "home-front", 5), c("a2", "home-front", 200), is_front=lambda w, p: w == "home-front")
    out["idle_hand"] = q(c("a1", ago=90), c("a2", ago=200))
    out["tie"] = q(c("a9", ago=10), c("a2", ago=10), c("a4", ago=200))
    on(); base()
    out["reading"] = found()
    out["hourly"] = [g for g, _l in HR.pass_(items(), now0, env(), None, None)]
    off()
    out["gate_off"] = found()
    return out
GOOD = observe()
EXPECT = {"q": {"a2": "a1", "a4": "a1"}, "one": {}, "front": {}, "idle_hand": {}, "tie": {"a4": "a2"},
          "reading": [bid(i) for i in (1, 3, 4, 5, 6)], "hourly": ["a1", "a3", "a4", "a5", "a6"], "gate_off": [bid(i) for i in (1, 2, 3, 4, 5, 6)]}
check("10 the unmutated rule gives every promised observation", GOOD == EXPECT, GOOD)
real_queue = Q.queue
def wrong_newest(cands, now, is_front=None):                       # the OLDEST item is chosen as the one in hand
    rows = [(g, m, a) for g, m, _p, a in cands]
    if len(rows) < 2: return {}
    hand = min(rows, key=lambda r: r[2]); return {g: hand[0] for g, _m, _a in rows if g != hand[0]}
def ignore_hour(cands, now, is_front=None):                        # every other item is queued, activity in the hour or not
    out = real_queue(cands, now, is_front); cs = list(cands)
    if out:
        hand = next(iter(out.values())); out.update({g: hand for g, m, _p, a in cs if g != hand and m == next(x[1] for x in cs if x[0] == hand)})
    return out
def queue_front(cands, now, is_front=None): return real_queue(cands, now, None)       # the front test is dropped
def no_idle_hand(cands, now, is_front=None):                       # an item in hand that is idle itself still queues the others
    cs = [(g, m, p, max(a, now - 1)) if i == 0 else (g, m, p, a) for i, (g, m, p, a) in enumerate(sorted(cands, key=lambda x: -x[3]))]
    return real_queue(cs, now, is_front)
def never(cands, now, is_front=None): return {}
for name, fn, key in (("the oldest item chosen as the item in hand", wrong_newest, "q"), ("the hour ignored", ignore_hour, "q"), ("front agents queued", queue_front, "front"),
                      ("an idle item in hand still queues the others", no_idle_hand, "idle_hand"), ("nothing ever queued", never, "q")):
    with mutate(Q, "queue", fn): bad = observe()
    check(f"10 mutation `{name}` is caught by the check on `{key}`" + ("" if name != "nothing ever queued" else " and the passes"), bad[key] != EXPECT[key] and (name != "nothing ever queued" or (bad["reading"] != EXPECT["reading"] and bad["hourly"] != EXPECT["hourly"])), (key, bad[key]))
with mutate(Q, "enabled", lambda: True): bad = observe()
check("10 mutation `the gate ignored (always on)` is caught: the gate-off observation changes", bad["gate_off"] != EXPECT["gate_off"], bad["gate_off"])
real_reading = SL.reading
with mutate(SL, "reading", lambda item, mover, after_open, now, behind="": real_reading(item, mover, after_open, now)): bad = observe()
check("10 mutation `the reading no longer asks the queue` is caught by the reading and hourly observations", bad["reading"] != EXPECT["reading"] and bad["hourly"] != EXPECT["hourly"], (bad["reading"], bad["hourly"]))
with mutate(Q, "overlay", lambda mod, behind: mod):
    on(); b = board(); L = {w: ids for w, ids in lists_of(b).items() if w in (AG, WT)}; off()
check("10 mutation `the board no longer applies the reading` is caught: a2 stays on agent", "a2" in L[AG], L)

with mutate(server, "_queue_map", lambda *a, **k: {}):
    B = stall_rows(); stall_svc.stall_since(B)
    for p in (T / "state").glob("stall*.json"): p.unlink()
    B = stall_rows(); stall_svc.stall_since(B); cli_row("home-peer", "idle", B + 60)
    done = stk(B + 60 + 10 * MIN + 1, True)
check("10 mutation `the stall pass no longer asks the queue` is caught: the queued item (a2) is chased", "a2" in done, done)
mine = stalltick_svc.stall_tick
print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
