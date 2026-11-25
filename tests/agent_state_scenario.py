"""Scenario test for the agent state the audit reads (service/agent_state.py `POST /client/agent-state`, audit/agent_state.py, and the hourly audit's read of it, service/audit_ticks.py): the fleet's
session manager pushes which registered agents are busy and which idle, the whole fleet in one body that REPLACES the last snapshot; the server stores it in one file and the audit decides busy or idle from
it alone. Fixture items in a temporary store, no live store, no network, no model call, no message sent.

  1  the route's module: a good body is stored and answers `{ok, agents}`; the next body replaces the whole snapshot (an agent left out is gone); each refused body (not an object, another schema, no time, agents not an
     object, a bad state, `read` missing, a subagent that is no object, an empty name) answers 400 with one line and leaves the old snapshot byte for byte; a brief is kept to its first 2 KB; a standby copy and a
     file that cannot be written answer 503 and keep the old one; no temporary file is left behind; the file lives in the state folder and a push moves nothing the board's views stand on
  2  over HTTP: no token is 401, a wrong token is 401, a machine token stores (200), a refused body is 400 and the old snapshot stays, a body over the cap is 400 (read no further than the cap) and the old snapshot stays
  3  the reader: busy and idle for a fresh snapshot (the sender's own word is trusted); UNKNOWN, with a reason, for no file, a torn file, another schema, an agent the snapshot does not name, `read` false, a state that
     is unknown, a snapshot just over 15 minutes old (and idle just inside it), one dated more than five minutes ahead of the clock, a snapshot with no time; an idle agent has no subagents; the name is found in any case
     and by an alias; the pane word the hourly line reads; a hand-edited file (a time or a `since` of -Infinity, a huge integer or past the bound) reads unknown and never raises
  1b numbers and text the body cannot be stored with (a huge integer or a time past the bound in `written`, `since` or `at`, a lone surrogate in a name or a text) are 400 with a reason, never 500, the old snapshot kept and no
     temporary file left; a push whose `written` is older than the stored snapshot's is ignored (200 `ignored: older`), an equal one is accepted; the file is mode 0600; a stale temporary file of the writer's own name is swept
     on a write and nothing else is touched; 8 threads pushing at once leave the largest `written` stored whole, no reader meets a torn file; over HTTP a body of exactly 1,000,000 bytes is stored and one of 1,000,001 is 400
  4  the hourly audit on it: an idle fresh agent's item gets `audit_idle`; a busy one in a turn is verified (live state only); a subagent whose words name the item ties to it and leaves the mover's other item idle; a stale
     snapshot, a missing agent, a state not read, no file, a torn file and a subagent the sender could not read each write `audit_unknown` (nothing flagged, nothing idle-marked, nothing stamped); a busy agent that says
     neither a turn nor a subagent is unknown
  5  nothing else is read on that path: a pass opens no file under the box's own pane registry or transcript folders (which are set up here, and say the opposite of the snapshot), starts no process and opens no
     connection; the audit modules hold no ssh, process or registry code

    tests/run-suite agent_state       -> exit 0 / 1"""
import io, json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="agentstate-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
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
HOME = T / "home"; REG = HOME / ".claude/sessions"; TRANS = T / "transcripts/-home-x"                  # an isolated HOME: never the host's pane registry
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(HOME), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state", "secrets", "brain/projects", "cli"): (T / d).mkdir(parents=True)
REG.mkdir(parents=True); TRANS.mkdir(parents=True)
NAMES = ("home-front", "team-back", "home-peer", "home-peer2", "home-stew")
U = {n: f"00000000-0000-4000-8000-0000000000{i:02d}" for i, n in enumerate(NAMES, 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": "2026-01-01T00:00:00Z"}}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
ALPHA = {"home-front": "the front", "team-back": "builds, merges and releases the code"}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                  "agents": ALPHA, "back_agents": {"team-back": ALPHA["team-back"]}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: builds, merges and releases the code\n---\n\n# alpha\n\n## Current state\n\nx\n\n<!-- timeline -->\n\n## Timeline\n", encoding="utf-8")
(T / "store/next-id").write_text("1"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
MIN = 60.0
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:400]}" if got is not None else ""))
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools")); logging.disable(logging.INFO)
from stackshot.web import server, wiring
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import anchors as _wt_anchors, route as _wt_route
from stackshot.service import audit_ticks as audit_ticks_svc, agent_state as SVC, client_reads as client_reads_svc, messaging as _messaging, telling
from stackshot.audit import agent_state as AS, subagent_tie as TIE, hourly as HR
from stackshot.audit import hourly_log as HL
from stackshot.core import readonly as _ro
from stackshot.fleet import client
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
telling.PUSH = [sys.executable, "-c", "pass"]
sent = []                                                          # every message the server was asked to send: none is expected from this pass
_messaging._message = lambda to, text, sender, auth="", origin="", fyi=False: (sent.append((to, text)), "delivered to " + to)[1]
telling.tell_woken = lambda *a, **k: sent.append(("tell_woken", a))

STATE = T / "state"; FILE = STATE / "agent-state.json"
def good(agents=None, written=None, **over):
    b = {"schema": 1, "written": time.time() if written is None else written, "agents": agents if agents is not None else {}}
    b.update(over); return b
def ag(state="idle", pane="idle", read=True, subs=None, why="", since=None):
    a = {"state": state, "since": time.time() - 3600 if since is None else since, "why": why, "pane": pane, "read": read}
    if subs is not None: a["subagents"] = subs
    return a
def sub(desc="", brief="", id_="s1", **kw): return {"id": id_, "description": desc, "brief": brief, "at": time.time() - 60, **kw}
def stored(): return FILE.read_bytes() if FILE.exists() else None
def loaded(): return json.loads(FILE.read_text()) if FILE.exists() else None
def leftovers(): return sorted(p.name for p in STATE.iterdir() if p.name != FILE.name)

# ================================================================ 1. the route's module
check("1 no snapshot yet: nothing is stored, and the reader's file read says none", stored() is None and SVC.load() is None and AS.snapshot() is None)
st, out = SVC.post("box-far", good({"home-peer": ag("busy", "turn", subs=[sub("Build the thing", "x")]), "home-peer2": ag("idle", "idle")}))
snap1 = loaded()
check("1 a good body is stored and answers 200 {ok, agents: N}", (st, out) == (200, {"ok": True, "agents": 2}) and set(snap1["agents"]) == {"home-peer", "home-peer2"} and snap1["schema"] == 1 and isinstance(snap1["received"], float), (st, out, snap1))
check("1 …the file is in the state folder, nothing else is left beside it, and the reader loads it", FILE.parent == STATE and leftovers() == [] and SVC.load() == snap1 and AS.snapshot() == snap1, (leftovers(), FILE))
b1 = stored()
st, out = SVC.post("box-far", good({"home-stew": ag("idle", "shell")}))
snap2 = loaded()
check("1 the next body REPLACES the whole snapshot: an agent left out of it is gone", (st, out) == (200, {"ok": True, "agents": 1}) and set(snap2["agents"]) == {"home-stew"} and stored() != b1, (st, out, snap2))
check("1 an empty fleet is a valid body (an empty snapshot, which reads every agent unknown)", SVC.post("box-far", good({})) == (200, {"ok": True, "agents": 0}) and loaded()["agents"] == {})
SVC.post("box-far", good({"home-stew": ag("idle", "shell")}))
keep = stored()
bad = {
    "a list": [1, 2], "a string": "x", "null": None,
    "another schema": good(schema=2), "a text schema": good(schema="1"), "a true schema": good(schema=True), "no schema": {"written": 1.0, "agents": {}},
    "no time": {"schema": 1, "agents": {}}, "a time that is text": good(written="now"), "a time of zero": good(written=0), "a negative time": good(written=-5), "a true time": good(written=True), "an infinite time": good(written=float("inf")),
    "agents a list": good(agents=[]), "no agents": {"schema": 1, "written": 5.0}, "agents null": good(agents=None) | {"agents": None},
    "an empty name": good({"": ag()}), "a blank name": good({"  ": ag()}), "a name too long": good({"x" * 201: ag()}),
    "an agent that is no object": good({"a": "idle"}), "a state that is none of three": good({"a": ag("sleeping")}), "no state": good({"a": {"read": True}}),
    "read missing": good({"a": {"state": "idle"}}), "read as text": good({"a": ag(read="yes")}), "since as text": good({"a": ag(since="soon")}), "why as a number": good({"a": ag(why=5)}), "pane as a list": good({"a": ag(pane=[])}),
    "subagents not a list": good({"a": ag("busy", "turn", subs={})}), "a subagent that is no object": good({"a": ag("busy", "turn", subs=["x"])}), "a subagent brief that is no string": good({"a": ag("busy", "turn", subs=[{"brief": 3}])}),
    "a subagent time that is text": good({"a": ag("busy", "turn", subs=[{"at": "x"}])}), "a subagent flag that is text": good({"a": ag("busy", "turn", subs=[{"quiet": "yes"}])}),
}
res = {k: SVC.post("box-far", v) for k, v in bad.items()}
check("1 each refused body answers 400 with one line of reason", all(s == 400 and isinstance(o.get("error"), str) and o["error"] and "\n" not in o["error"] for s, o in res.values()), {k: v for k, v in res.items() if v[0] != 400 or not v[1].get("error")})
check("1 …and the old snapshot stays, byte for byte, with no temporary file left", stored() == keep and leftovers() == [], (leftovers(),))
SVC.post("box-far", good({"home-peer": ag("busy", "turn", subs=[sub("d" * 900, "b" * 5000, id_="i" * 500)])}))
s0 = loaded()["agents"]["home-peer"]["subagents"][0]
check("1 a brief is kept to its first 2 KB, a description and an id to their caps, and the entry stays whole", len(s0["brief"]) == SVC.BRIEF_MAX == 2048 and s0["brief"] == "b" * 2048 and len(s0["description"]) == 300 and len(s0["id"]) == 120, {k: len(str(v)) for k, v in s0.items()})
many = [sub(f"d{i}", "b", id_=f"s{i}") for i in range(SVC.SUBAGENTS_MAX + 30)]
SVC.post("box-far", good({"home-peer": ag("busy", "turn", subs=many)}))
check("1 subagents beyond the cap per agent are dropped, not refused", len(loaded()["agents"]["home-peer"]["subagents"]) == SVC.SUBAGENTS_MAX)
SVC.post("box-far", good({"home-stew": ag("idle", "shell")}))
keep = stored()
ro = _ro.is_read_only
_ro.is_read_only = lambda: True
try: st, out = SVC.post("box-far", good({"x": ag()}))
finally: _ro.is_read_only = ro
check("1 a read-only standby copy answers 503 and stores nothing", st == 503 and stored() == keep, (st, out))
real_replace = os.replace
def boom(*a, **k): raise OSError("disk full")
SVC.os.replace = boom
try: st, out = SVC.post("box-far", good({"x": ag()}))
finally: SVC.os.replace = real_replace
check("1 a file that cannot be written answers 503, the old snapshot stays and no temporary file is left", st == 503 and "could not be written" in out["error"] and stored() == keep and leftovers() == [], (st, out, leftovers()))
check("1 the size cap: a length over the cap is a refusal, a length within it, a header that is no number and none are not", SVC.too_large(SVC.MAX_BYTES + 1) != "" and SVC.too_large(str(SVC.MAX_BYTES + 1)) != "" and SVC.too_large(SVC.MAX_BYTES) == "" and SVC.too_large("abc") == "" and SVC.too_large(None) == "" and SVC.MAX_BYTES == 1_000_000)
stamp0 = client_reads_svc._board_stamp()
SVC.post("box-far", good({"home-peer": ag("busy", "turn")}))
check("1 a push moves nothing the board's views stand on (the stamp of the items view is the same before and after, and the file is outside the store and the fleet folders)",
      client_reads_svc._board_stamp() == stamp0 and T / "store" not in FILE.parents and T / "fleet" not in FILE.parents, (stamp0, client_reads_svc._board_stamp()))

# ---- 1b. a number or a text the body cannot be stored with is a 400, never a 500; the stored snapshot's order; the file's mode; a stale temporary file
import stat as _stat
SVC.post("box-far", good({"home-stew": ag("idle", "shell")}))
keep = stored()
HUGE = 10 ** 400                                                    # converting it to a float raises OverflowError
SUR = json.loads('"\\ud800"')                                       # a lone surrogate as a JSON text can spell it: it parses, and cannot be written as UTF-8
bad2 = {
    "a time that is a huge integer": good(written=HUGE), "a negative huge time": good(written=-HUGE), "a time past the bound": good(written=2e12), "a time of 1e400 (infinite when parsed)": json.loads('{"schema": 1, "written": 1e400, "agents": {}}'),
    "a since that is a huge integer": good({"a": ag(since=HUGE)}), "a since that is not finite": good({"a": ag(since=float("nan"))}), "a subagent time that is a huge integer": good({"a": ag("busy", "turn", subs=[{"at": HUGE}])}),
    "a subagent time past the bound": good({"a": ag("busy", "turn", subs=[{"at": 2e12}])}),
    "a lone surrogate in an agent name": good({SUR: ag()}), "a lone surrogate in why": good({"a": ag(why=SUR)}), "a lone surrogate in pane": good({"a": ag(pane=SUR)}),
    "a lone surrogate in a subagent id": good({"a": ag("busy", "turn", subs=[{"id": SUR}])}), "a lone surrogate in a description": good({"a": ag("busy", "turn", subs=[{"description": "x" + SUR}])}),
    "a lone surrogate in a brief": good({"a": ag("busy", "turn", subs=[{"brief": "b" + SUR + "b"}])}),
}
res2 = {k: SVC.post("box-far", v) for k, v in bad2.items()}
check("1b each of them answers 400 with one line of reason (no exception, so no 500)", all(s_ == 400 and isinstance(o.get("error"), str) and o["error"] and "\n" not in o["error"] for s_, o in res2.values()), {k: v for k, v in res2.items() if v[0] != 400})
check("1b …the old snapshot stays, byte for byte, with no temporary file left", stored() == keep and leftovers() == [], leftovers())
check("1b …a surrogate beyond a text's cap is clipped away with the rest and does not refuse the body; a valid astral character (a surrogate pair in the JSON) is kept whole",
      SVC.post("box-far", good({"a": ag(why="w" * SVC.WHY_MAX + SUR)}))[0] == 200 and SVC.post("box-far", good({"a": ag(why=json.loads('"\\ud83d\\ude00"'))}))[0] == 200 and loaded()["agents"]["a"]["why"] == "\U0001F600")
SVC.post("box-far", good({"home-stew": ag("idle", "shell")}))
oldmask = os.umask(0)
try: SVC.post("box-far", good({"home-stew": ag("idle", "shell"), "x": ag()}))
finally: os.umask(oldmask)
check("1b the snapshot file is mode 0600 (it holds the briefs of subagents), whatever the umask: a new file and a replaced one", _stat.S_IMODE(FILE.stat().st_mode) == 0o600, oct(_stat.S_IMODE(FILE.stat().st_mode)))
# the order of pushes: one snapshot, a push older than it is ignored, an equal one is accepted
T0 = time.time()
SVC.post("box-far", good({"newer": ag()}, written=T0 + 100)); keep = stored()
st_, out_ = SVC.post("box-far", good({"older": ag()}, written=T0 + 50))
check("1b a push whose `written` is older than the stored snapshot's is ignored: 200 {ok, ignored: older}, the newer snapshot kept byte for byte, no temporary file", (st_, out_) == (200, {"ok": True, "ignored": "older"}) and stored() == keep and leftovers() == [], (st_, out_))
st_, out_ = SVC.post("box-far", good({"equal": ag()}, written=T0 + 100))
check("1b …an equal `written` is accepted (it replaces), and a newer one too", (st_, out_) == (200, {"ok": True, "agents": 1}) and set(loaded()["agents"]) == {"equal"} and SVC.post("box-far", good({"later": ag()}, written=T0 + 101))[0] == 200 and set(loaded()["agents"]) == {"later"})
SVC.post("box-far", good({"ahead": ag()}, written=time.time() + 3600)); keep = stored()
st_, out_ = SVC.post("box-far", good({"now": ag()}))
check("1b …a stored snapshot dated more than five minutes ahead of the server's clock (a sender whose clock ran ahead once) shuts nobody out: a push dated now replaces it", (st_, out_) == (200, {"ok": True, "agents": 1}) and set(loaded()["agents"]) == {"now"}, (st_, out_))
FILE.write_text("{torn")
check("1b …a torn stored file is no snapshot to be older than: the push is stored", SVC.post("box-far", good({"x": ag()}, written=5.0))[0] == 200 and set(loaded()["agents"]) == {"x"})
# a stale temporary file of the writer's own name is swept on a write, and nothing else is touched
def _tmp_file(name, age_s, text="x"):
    q = STATE / name; q.write_text(text); os.utime(q, (time.time() - age_s, time.time() - age_s)); return q
stale = _tmp_file(".agent-state.json.111.222.tmp", 2 * 3600); fresh_tmp = _tmp_file(".agent-state.json.333.444.tmp", 600)
others = [_tmp_file(n, 2 * 3600) for n in (".agent-state.json.x.tmp", ".agent-state.json.1.2.tmp.bak", "agent-state.json.1.2.tmp", ".agent-state.json.1.tmp", "agent-state.json.old", ".other.5.6.tmp")]
target = _tmp_file("target-of-link.txt", 2 * 3600, "keep me"); link = STATE / ".agent-state.json.777.888.tmp"; link.symlink_to(target)
os.utime(link, (time.time() - 2 * 3600,) * 2, follow_symlinks=False)
adir = STATE / ".agent-state.json.9.9.tmp"; adir.mkdir(); os.utime(adir, (time.time() - 2 * 3600,) * 2)
SVC.post("box-far", good({"swept": ag()}, written=time.time() + 5))
check("1b a leftover temporary file of the writer's own name older than an hour is removed by the next write", not stale.exists() and set(loaded()["agents"]) == {"swept"})
check("1b …a recent one, a file of any other name, a link of that name (never followed, never removed: its target is untouched) and a folder of that name stay",
      fresh_tmp.exists() and all(q.exists() for q in others) and link.is_symlink() and target.read_text() == "keep me" and adir.is_dir(), [q.name for q in STATE.iterdir()])
for q in (fresh_tmp, target, *others): q.unlink()
link.unlink(); adir.rmdir()
check("1b …and nothing of the test is left in the state folder but the snapshot", leftovers() == [], leftovers())
FILE.unlink(missing_ok=True)      # no snapshot dated ahead is left for the checks that follow
SVC.post("box-far", good({"home-stew": ag("idle", "shell")}))
# many senders at once: the read of the stored `written` and the replace of the file are one step (the lock), so the last write is never an older one
import threading, itertools
FILE.unlink(missing_ok=True)
SVC.post("box-far", good({"seed": ag()}, written=time.time() - 60))      # a snapshot the poller can read from the first moment
PUSHES = 100; CBASE = time.time() - 30; CTR = itertools.count(1); ACCEPTED, UNREAD, ERRS, BACK = [], [], [], []; STOP = threading.Event()
def _pusher(k):
    try:
        for _ in range(PUSHES):
            w = CBASE + next(CTR) * 0.001                                # a shared counter: every push is later than the one before it, but the threads post out of order
            st_c, out_c = SVC.post("box-far", good({f"t{k}": ag()}, written=w))
            if st_c != 200: ERRS.append((st_c, out_c))
            elif "ignored" not in out_c: ACCEPTED.append((w, k))
            cur_c = SVC.load()                                           # once a push is answered, the stored `written` is that push's or a later one's, never an older one
            if cur_c is None or cur_c["written"] < w: BACK.append((w, cur_c and cur_c["written"]))
    except BaseException as e_: ERRS.append(repr(e_))
def _poller():
    last = 0.0
    while not STOP.is_set():
        cur_p = SVC.load()
        if cur_p is None: UNREAD.append(time.time())                     # a torn or missing file: a reader must see the old snapshot or the new one
        else:
            if cur_p["written"] < last: BACK.append((last, cur_p["written"]))     # the stored `written` only ever rises
            last = cur_p["written"]
workers = [threading.Thread(target=_pusher, args=(k,)) for k in range(8)]; poller = threading.Thread(target=_poller)
SWITCH = sys.getswitchinterval(); sys.setswitchinterval(1e-5)      # the threads change over often, so the window between the read and the replace is hit
try:
    poller.start()
    for w_ in workers: w_.start()
finally:
    for w_ in workers: w_.join()
    STOP.set(); poller.join(); sys.setswitchinterval(SWITCH)
top = max(ACCEPTED) if ACCEPTED else None
check("1b 8 threads pushing 100 snapshots each, `written` rising from a shared counter: no push fails, and the stored `written` is the largest accepted one (a later write is never an older snapshot), the whole snapshot of that sender",
      not ERRS and len(ACCEPTED) >= 1 and top is not None and top[0] == CBASE + 8 * PUSHES * 0.001 and loaded()["written"] == top[0] and set(loaded()["agents"]) == {f"t{top[1]}"}, (ERRS[:3], top, loaded() and loaded()["written"], len(ACCEPTED)))
check("1b …the stored `written` never went back (not seen by the poller, nor by a sender after its own answered push), no reader met a torn or missing snapshot, and only the snapshot file is left in the state folder", not BACK and not UNREAD and leftovers() == [], (BACK[:3], len(BACK), len(UNREAD), leftovers()))
FILE.unlink(missing_ok=True)
SVC.post("box-far", good({"home-stew": ag("idle", "shell")}))

# ================================================================ 2. over HTTP
from starlette.testclient import TestClient
tok = open(client.mint("box-far")).read().strip()
H = {"Authorization": "Bearer " + tok}
SVC.post("box-far", good({"home-stew": ag("idle", "shell")}))
keep = stored()
app = server.mcp.http_app()
with TestClient(app) as c:
    LEFT0 = leftovers()      # the token file the mint leaves and whatever the app's start writes in the state folder are no leftover of a push
    r = c.post("/client/agent-state", json=good({"x": ag()}))
    check("2 no token → 401, nothing stored", r.status_code == 401 and stored() == keep, (r.status_code, r.text[:80]))
    r = c.post("/client/agent-state", json=good({"x": ag()}), headers={"Authorization": "Bearer " + "x" * 43})
    check("2 a wrong token → 401, nothing stored", r.status_code == 401 and stored() == keep, (r.status_code, r.text[:80]))
    r = c.post("/client/agent-state", json=good({"home-peer": ag("busy", "turn"), "home-peer2": ag()}), headers=H)
    check("2 a machine token stores the snapshot and answers 200 {ok, agents}", r.status_code == 200 and r.json() == {"ok": True, "agents": 2} and set(loaded()["agents"]) == {"home-peer", "home-peer2"}, (r.status_code, r.text[:200]))
    keep = stored()
    r = c.post("/client/agent-state", json=good({"a": ag("sleeping")}), headers=H)
    check("2 a refused body is 400 with the reason, and the old snapshot stays", r.status_code == 400 and "state" in r.json()["error"] and stored() == keep, (r.status_code, r.text[:200]))
    r = c.post("/client/agent-state", json=[1, 2], headers=H)
    check("2 a body that is no object is 400, the old snapshot stays", r.status_code == 400 and stored() == keep, (r.status_code, r.text[:200]))
    r = c.post("/client/agent-state", content=b"not json", headers=H)
    check("2 a body that is no JSON is 400, the old snapshot stays", r.status_code == 400 and stored() == keep, (r.status_code, r.text[:200]))
    r = c.post("/client/agent-state", content=json.dumps(good({"a": ag(why="w" * (SVC.MAX_BYTES + 10))})).encode(), headers=H | {"Content-Type": "application/json"})
    check("2 a body over the cap is 400 naming the limit, and the old snapshot stays", r.status_code == 400 and str(SVC.MAX_BYTES) in r.json()["error"] and stored() == keep, (r.status_code, r.text[:200]))
    def sized(n):      # a valid body of exactly n bytes: a good snapshot padded with spaces after the JSON
        b_ = json.dumps(good({"home-peer": ag("busy", "turn")}, written=time.time() + 30)).encode(); assert len(b_) < n; return b_ + b" " * (n - len(b_))
    r = c.post("/client/agent-state", content=sized(SVC.MAX_BYTES), headers=H | {"Content-Type": "application/json"})
    check("2 a body of exactly 1,000,000 bytes is stored (200)", r.status_code == 200 and r.json() == {"ok": True, "agents": 1} and set(loaded()["agents"]) == {"home-peer"}, (r.status_code, r.text[:200]))
    keep = stored()
    r = c.post("/client/agent-state", content=sized(SVC.MAX_BYTES + 1), headers=H | {"Content-Type": "application/json"})
    check("2 …one of 1,000,001 bytes is 400 naming the limit, and the old snapshot stays", r.status_code == 400 and str(SVC.MAX_BYTES) in r.json()["error"] and stored() == keep, (r.status_code, r.text[:200]))
    def sized_chunks(n):
        b_ = sized(n)
        for i_ in range(0, n, 50_000): yield b_[i_:i_ + 50_000]
    r = c.post("/client/agent-state", content=sized_chunks(SVC.MAX_BYTES), headers=H | {"Content-Type": "application/json"})
    r2 = c.post("/client/agent-state", content=sized_chunks(SVC.MAX_BYTES + 1), headers=H | {"Content-Type": "application/json"})
    check("2 …also with no Content-Length: a chunked body of exactly 1,000,000 bytes is 200, one of 1,000,001 is 400 naming the limit", r.status_code == 200 and r2.status_code == 400 and str(SVC.MAX_BYTES) in r2.json()["error"], (r.status_code, r2.status_code, r2.text[:100]))
    keep = stored()
    huge_int = ('{"schema": 1, "written": ' + "1" + "0" * 400 + ', "agents": {}}').encode()
    r = c.post("/client/agent-state", content=huge_int, headers=H | {"Content-Type": "application/json"})
    check("2 a body whose time is a huge integer is 400 with a reason (not 500), the old snapshot stays and no temporary file is left", r.status_code == 400 and r.json().get("error") and stored() == keep and leftovers() == LEFT0, (r.status_code, r.text[:200], leftovers(), LEFT0, stored() == keep))
    lone = b'{"schema": 1, "written": 1e9, "agents": {"a": {"state": "idle", "since": 1000, "pane": "idle", "read": true, "why": "\\ud800"}}}'.replace(b"1e9", str(time.time() + 60).encode())      # valid but for the lone surrogate (a bare JSON escape)
    r = c.post("/client/agent-state", content=lone, headers=H | {"Content-Type": "application/json"})
    check("2 a body with a lone surrogate in a text is 400 with a reason (not 500), the old snapshot stays and no temporary file is left", r.status_code == 400 and r.json().get("error") and stored() == keep and leftovers() == LEFT0, (r.status_code, r.text[:200], leftovers(), LEFT0, stored() == keep))
    r = c.post("/client/agent-state", json=good({"older": ag()}, written=time.time() - 3600), headers=H)
    check("2 a push older than the stored snapshot answers 200 {ok, ignored: older} and stores nothing", r.status_code == 200 and r.json() == {"ok": True, "ignored": "older"} and stored() == keep, (r.status_code, r.text[:200]))
    keep = stored()
    def chunks():
        for _ in range(12): yield b" " * 100_000
    r = c.post("/client/agent-state", content=chunks(), headers=H | {"Content-Type": "application/json"})
    check("2 …also with no Content-Length (a chunked body is cut at the cap)", r.status_code == 400 and str(SVC.MAX_BYTES) in r.json()["error"] and stored() == keep, (r.status_code, r.text[:200]))
    r = c.post("/client/no-such-write", json={}, headers=H)
    check("2 the list of writes in a 404 names this one", r.status_code == 404 and "agent-state" in r.text, (r.status_code, r.text[:120]))
FILE.unlink(missing_ok=True)

# ================================================================ 3. the reader
NOW = time.time()
def fresh(agents, age=0.0): return {"schema": 1, "written": NOW - age, "agents": agents}
S = fresh({"home-peer": ag("busy", "turn", why="a turn is running", since=NOW - 600, subs=[sub("Build part D", "the brief", id_="s9", quiet=True)]), "home-peer2": ag("idle", "idle", subs=[sub("left over")]),
           "Team-Back": ag("busy", "turn"), "gone": ag("unknown", "", read=False, why="the pane could not be read"), "weird": ag("unknown", "", read=True, why="no sign"), "sh": ag("idle", "shell"), "zz": ag("busy", "sleeping", subs=[sub("x")])})
a = AS.state_of("home-peer", NOW, S)
check("3 a fresh snapshot: busy, with the sender's words, since, pane and the listed subagents", (a.state, a.why, a.pane, a.since) == ("busy", "a turn is running", "turn", NOW - 600) and len(a.subagents) == 1, a)
b = AS.state_of("home-peer2", NOW, S)
check("3 …idle, and an idle agent has no subagents here (whatever the entry lists is not running as the sender counts it)", (b.state, b.pane, b.subagents) == ("idle", "idle", ()), b)
check("3 the pane word the hourly line reads: busy for a pane in a turn, the pane's own word otherwise, empty when unknown", (AS.pane_of(a), AS.pane_of(b), AS.pane_of(AS.state_of("sh", NOW, S)), AS.pane_of(AS.state_of("nope", NOW, S))) == ("busy", "idle", "shell", ""))
subs = AS.subagents_of(a)
check("3 the subagents of a busy agent, as the audit ties them (words, flags)", subs == [{"id": "s9", "description": "Build part D", "brief": "the brief", "text": "Build part D\nthe brief", "at": S["agents"]["home-peer"]["subagents"][0]["at"], "quiet": True}], subs)
try: AS.subagents_of(AS.state_of("nope", NOW, S)); raised = False
except ValueError: raised = True
check("3 …none for an idle one, and asking for an unknown one raises ValueError", AS.subagents_of(b) == [] and raised)
check("3 the name is found in any case, and by an alias when the name itself is not in the snapshot", AS.state_of("team-back", NOW, S).state == "busy" and AS.state_of("HOME-PEER2", NOW, S).state == "idle"
      and AS.state_of("old-name", NOW, S, ("home-peer2",)).state == "idle" and AS.state_of("old-name", NOW, S, ("nope", "")).state == "unknown")
def why_of(name, snap, now=NOW, **kw):
    s = AS.state_of(name, now, snap, **kw); return s.state, s.why
for label, got, frag in (
        ("an agent the snapshot does not name", why_of("nobody", S), "not in"),
        ("an entry whose read is false", why_of("gone", S), "not read"),
        ("a state that is unknown", why_of("weird", S), "unknown"),
        ("no snapshot at all", why_of("home-peer", None), "no agent state"),
        ("a snapshot that is no object", why_of("home-peer", [1]), "no agent state"),
        ("a snapshot with no agents object", why_of("home-peer", {"written": NOW}), "no agent state"),
        ("a snapshot with no time", why_of("home-peer", {"agents": S["agents"]}), "no time"),
        ("a snapshot whose time is a bool", why_of("home-peer", {"written": True, "agents": S["agents"]}), "no time"),
        ("a snapshot whose time is not a number", why_of("home-peer", {"written": float("nan"), "agents": S["agents"]}), "no time"),
        ("a snapshot just over 15 minutes old", why_of("home-peer2", fresh(S["agents"], 15 * 60 + 1)), "minutes old"),
        ("a snapshot an hour old", why_of("home-peer2", fresh(S["agents"], 3600)), "minutes old"),
        ("a snapshot dated 301 s ahead of the clock", why_of("home-peer2", fresh(S["agents"], -301)), "ahead"),
        ("a day ahead", why_of("home-peer2", fresh(S["agents"], -86400)), "ahead")):
    check(f"3 UNKNOWN, never idle: {label}", got[0] == "unknown" and frag in got[1], got)
check("3 …but a snapshot 15 minutes old exactly or 899 s old is read (idle), and one dated 299 s ahead is a skew of clocks, still read", all(AS.state_of("home-peer2", NOW, fresh(S["agents"], age)).state == "idle" for age in (899, 900, -299)))
check("3 the constants are pinned: 15 minutes and 5 minutes", AS.MAX_AGE_S == 900.0 and AS.SKEW_S == 300.0)
FILE.unlink(missing_ok=True)
check("3 no file: the reader says unknown for every agent", AS.snapshot() is None and AS.state_of("home-peer", NOW)[0] == "unknown")
FILE.write_text("{torn")
check("3 a torn file reads as no snapshot, unknown", AS.snapshot() is None and AS.state_of("home-peer", NOW)[0] == "unknown")
FILE.write_text(json.dumps({"schema": 2, "written": NOW, "agents": {"home-peer2": ag()}}))
check("3 a file of another schema reads as no snapshot, unknown", AS.snapshot() is None and AS.state_of("home-peer2", NOW)[0] == "unknown")
FILE.write_text(json.dumps([1]))
check("3 a file that holds no object reads as no snapshot, unknown", AS.snapshot() is None)
# a hand-edited file: a time that is not finite, past the bound or a huge integer is no time, and reading it never raises (it reads unknown, as a snapshot with no time)
def raw_snap(written, entry=None, agent="home-peer"):
    FILE.write_text(json.dumps({"schema": 1, "written": written, "agents": {agent: entry if entry is not None else ag("busy", "turn")}}))
def reads(name="home-peer"):
    try: st_ = AS.state_of(name, NOW); return st_.state, st_.why
    except BaseException as e_: return "raised", repr(e_)
res3 = {}
for label, w in (("-Infinity", float("-inf")), ("Infinity", float("inf")), ("NaN", float("nan")), ("a huge integer", HUGE), ("a negative huge integer", -HUGE), ("past the bound", 2e12)):
    raw_snap(w); res3[label] = reads()
check("3 a `written` that is -Infinity, Infinity, NaN, a huge integer or past the bound reads unknown (no time) and never raises", all(v[0] == "unknown" and "no time" in v[1] for v in res3.values()), res3)
res3b = {}
for label, sn in (("a huge integer", HUGE), ("-Infinity", float("-inf")), ("Infinity", float("inf")), ("NaN", float("nan")), ("past the bound", 2e12), ("text", "soon")):
    raw_snap(NOW, ag("busy", "turn", since=sn)); res3b[label] = reads()
e_null = ag("busy", "turn"); e_null["since"] = None; raw_snap(NOW, e_null); res3b["null"] = reads()
check("3 a `since` that is -Infinity, a huge integer, NaN, past the bound, text or null reads unknown (that agent only) and never raises", all(v[0] == "unknown" and "since" in v[1] for v in res3b.values()), res3b)
raw_snap(NOW, ag("busy", "turn", subs=[sub("Build part D", "x", at=HUGE), {"id": "t", "description": "d", "brief": "b", "at": float("-inf")}]), "home-peer")
try: got3c = [(e_["id"], e_["at"]) for e_ in AS.subagents_of(AS.state_of("home-peer", NOW))]
except BaseException as e_: got3c = repr(e_)
check("3 a subagent whose `at` is a huge integer or -Infinity (a hand-edited file) is listed with time 0.0 and nothing raises", got3c == [("s1", 0.0), ("t", 0.0)], got3c)
check("3 …the same through the reader's own file read, and a fine snapshot beside the damaged one is read as before", (raw_snap(NOW, ag("idle", "idle")), AS.state_of("home-peer", NOW)[0])[1] == "idle")
FILE.unlink()

# ================================================================ 4. the hourly audit on it
now0 = float(int(time.time()))
def put(i, mover="home-peer", act=90, **meta):
    """An open doing item on `mover`; its last real activity was `act` minutes before now0."""
    base = {"owner": U["home-front"], "project": "projects/alpha", "next": f"{mover}: do the thing", "state": "doing", "needs": [mover], "mover": mover}
    base.update(meta); at = now0 - act * MIN
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": "open", "updated": now0 - 2 * MIN, "state_updated": at, "confirmed": now0 - 2 * MIN,
                                                       "activity": at, "written_at": at, "written_by": mover, "metadata": base}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
def lines(i): return HL.log_of(mt(i))
def BID(n): return "board" + "#" + str(n)
def clear():
    for p_ in (T / "store/a").glob("*.json"): p_.unlink()
def push(agents, age=0.0):
    FILE.unlink(missing_ok=True)      # a push older than the stored snapshot is ignored (1b): a fixture that wants a stale one starts from no file
    st_, _ = SVC.post("box-far", good(agents, written=time.time() - age)); assert st_ == 200
def run(*ids, **kw):
    """One real pass of the hourly line (no pane and no subagents given: it reads the snapshot), items 1..n of the mover."""
    clear()
    for i in ids: put(i, **kw)
    return audit_ticks_svc._hourly_tick(now=time.time())
def kinds(*ids): return [lines(i)[0]["kind"] if lines(i) else None for i in ids]
def unknown_ok(*ids): return all(lines(i) and lines(i)[0]["kind"] == "audit_unknown" and not HR.idle_marked(mt(i)) and "last_activity" not in mt(i) for i in ids)
FILE.unlink(missing_ok=True)
check("4 the hourly line is on and the snapshot is absent: the file is not there", HR.enabled() is True and not FILE.exists())

got = run(1)
check("4 NO snapshot file: the mover's item reads UNKNOWN (kind audit_unknown), not idle, and the line says nothing was verified; nothing is stamped or idle-marked", got == ["a1"] and unknown_ok(1) and "could not be read, nothing verified" in lines(1)[0]["text"], lines(1))
push({"home-peer": ag("idle", "idle"), "home-peer2": ag("idle", "idle")})
got = run(1)
check("4 an IDLE fresh agent: the item reads idle, nothing verified (kind audit_idle), is marked idle for the hand-over and stamps nothing", got == ["a1"] and kinds(1) == ["audit_idle"] and HR.idle_marked(mt(1)) and "last_activity" not in mt(1) and lines(1)[0]["text"].split(": ", 1)[1].startswith("idle, nothing verified"), lines(1))
push({"home-peer": ag("busy", "turn")})
got = run(1)
check("4 a BUSY agent in a turn, one item on it: verified by the pane alone (kind audit, `live state only`), stamped as the item's last activity", got == ["a1"] and kinds(1) == ["audit"] and lines(1)[0]["text"].endswith("verified the mover's pane is in a turn" + HR.LIVE_ONLY) and mt(1)["last_activity"]["kind"] == "audit", (lines(1), mt(1).get("last_activity")))
push({"home-peer": ag("busy", "turn", subs=[sub(f"Build {BID(1)}", "work in the worktree")])})
got = run(1, 2)
check("4 a BUSY agent with a subagent whose words name item 1: item 1 is verified (a subagent is running on it), item 2 reads idle (tied to another item), neither by the pane",
      got == ["a1", "a2"] and kinds(1, 2) == ["audit", "audit_idle"] and lines(1)[0]["text"].endswith("verified a subagent is running on it" + HR.LIVE_ONLY) and HR.idle_marked(mt(2)), [lines(1), lines(2)])
push({"home-peer": ag("busy", "turn", subs=[sub("Build part D", "no item named here")])})
got = run(1, 2)
check("4 a subagent that names no item leaves the mover's items UNKNOWN, not idle", got == ["a1", "a2"] and unknown_ok(1, 2), [lines(1), lines(2)])
push({"home-peer": ag("busy", "turn", subs=[{"id": "s", "description": "", "brief": "", "at": 0, "unreadable": True}])})
got = run(1, 2)
check("4 a subagent the sender could not read (listed with no words) leaves them UNKNOWN", got == ["a1", "a2"] and unknown_ok(1, 2), [lines(1), lines(2)])
push({"home-peer": ag("busy", "shell")})
got = run(1)
check("4 a busy agent that says neither a pane in a turn nor a subagent is UNKNOWN (fail closed on a sender that cannot say why)", got == ["a1"] and unknown_ok(1), lines(1))
push({"home-peer2": ag("idle", "idle")})
got = run(1)
check("4 an agent the fresh snapshot does not name: UNKNOWN, not idle", got == ["a1"] and unknown_ok(1), lines(1))
push({"home-peer": ag("idle", "idle", read=False, why="the pane could not be read")})
got = run(1)
check("4 an entry whose read is false: UNKNOWN even though it says idle", got == ["a1"] and unknown_ok(1), lines(1))
push({"home-peer": ag("unknown", "", read=True)})
got = run(1)
check("4 a state that is unknown: UNKNOWN", got == ["a1"] and unknown_ok(1), lines(1))
push({"home-peer": ag("idle", "idle")}, age=15 * 60 + 5)
got = run(1)
check("4 a STALE snapshot (just over 15 minutes) for an idle agent: UNKNOWN (audit_unknown), never idle; nothing flagged, nothing idle-marked", got == ["a1"] and unknown_ok(1), lines(1))
push({"home-peer": ag("busy", "turn")}, age=15 * 60 + 5)
got = run(1)
check("4 …a stale snapshot does not verify a busy pane either (no line says verified)", got == ["a1"] and unknown_ok(1), lines(1))
push({"home-peer": ag("idle", "idle")}, age=14 * 60)
got = run(1)
check("4 a snapshot 14 minutes old is read: idle", got == ["a1"] and kinds(1) == ["audit_idle"], lines(1))
FILE.write_text("{torn")
got = run(1)
check("4 a torn file: UNKNOWN", got == ["a1"] and unknown_ok(1), lines(1))
FILE.unlink()
check("4 no message was sent by any pass", sent == [], sent)

# ================================================================ 5. nothing else is read on that path
SID = U["home-peer"]
(REG / f"{os.getpid()}.json").write_text(json.dumps({"pid": os.getpid(), "sessionId": SID, "kind": "interactive", "name": "home-peer", "status": "busy", "statusUpdatedAt": int(now0 * 1000), "updatedAt": int(now0 * 1000)}))
(TRANS / f"{SID}.jsonl").write_text(json.dumps({"type": "user", "sessionId": SID, "timestamp": "2026-01-01T00:00:00Z", "message": {"role": "user", "content": f"Build {BID(1)}"}}) + "\n")
WATCH = {"on": False}; SEEN = []
def _hook(event, args):
    if not WATCH["on"]: return
    if event in ("open", "os.scandir", "os.listdir", "os.stat", "os.walk", "glob.glob"):
        p = str(args[0]) if args and isinstance(args[0], (str, bytes, os.PathLike)) else ""
        if str(REG) in p or str(T / "transcripts") in p or "/.claude/" in p or p.endswith(".jsonl"): SEEN.append((event, p))
    elif event in ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork", "os.forkpty"): SEEN.append((event, str(args)[:100]))
    elif event in ("socket.connect", "socket.getaddrinfo"): SEEN.append((event, str(args)[:100]))
sys.addaudithook(_hook)
push({"home-peer": ag("idle", "idle")})
WATCH["on"] = True
try: got = run(1)
finally: WATCH["on"] = False
check("5 a pass reads the snapshot and nothing of the box's own: the registry says the mover is busy and its transcript says a subagent runs for item 1, the snapshot says idle, and the line says idle", got == ["a1"] and kinds(1) == ["audit_idle"], (got, lines(1)))
check("5 …it opened no file under the pane registry or the transcript folders, started no process and opened no connection", SEEN == [], SEEN)
push({"home-peer": ag("busy", "turn", subs=[sub("Build part D", "nothing")])})
WATCH["on"] = True
try: got = run(1, 2)
finally: WATCH["on"] = False
check("5 …and a snapshot with a subagent that ties to nothing gives unknown even where the transcript names the item (the transcript is not read)", got == ["a1", "a2"] and unknown_ok(1, 2) and SEEN == [], (lines(1), SEEN))
src = {n: pathlib.Path(STACK, "stackshot", n).read_text(encoding="utf-8") for n in ("audit/agent_state.py", "audit/subagent_tie.py", "service/agent_state.py")}
imports = {n: re.findall(r"^\s*(?:import|from)\s+([\w.]+)", t, re.M) for n, t in src.items()}
procs = {n: re.findall(r"\b(?:subprocess|Popen|os\.system|socket\.|paramiko)\b", t) for n, t in src.items()}
check("5 the reader, the tie and the route's module import no process, socket or ssh module and call none of them", not any(m.split(".")[0] in ("subprocess", "socket", "paramiko", "pty") for ms in imports.values() for m in ms) and not any(procs.values()), (imports, procs))
audit_src = {n: pathlib.Path(STACK, "stackshot", n).read_text(encoding="utf-8") for n in ("audit/hourly.py", "audit/agent_state.py", "audit/busy_hold.py", "audit/hand_idle.py", "service/audit_ticks.py")}
check("5 the audit's modules call no transcript reader of the tie (`running`, `pending_tasks`, `read_parent`, `interrupted`): the tie keeps them for the sender of the snapshot, whose rule they are (tests/subagent_tie_scenario.py), and the audit only ties what the snapshot lists",
      all(hasattr(TIE, n) for n in ("tied", "tied_to", "names_item", "Unreadable", "running", "RUNNING_S")) and not any(re.search(r"\b(?:subagent_tie|_tie|TIE)\.(?:running|pending_tasks|read_parent|resumes|interrupted)\b", t) for t in audit_src.values()), [n for n, t in audit_src.items() if re.search(r"\b(?:subagent_tie|_tie|TIE)\.(?:running|pending_tasks|read_parent|resumes|interrupted)\b", t)])
check("5 the audit's two reads in the service are the snapshot's: `_mover_subagents` and `_agent_state` exist, and the old registry reader of a pane is not what the pass calls", callable(audit_ticks_svc._mover_subagents) and callable(audit_ticks_svc._agent_state))
for p_ in REG.glob("*.json"): p_.unlink()
clear(); FILE.unlink(missing_ok=True)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
