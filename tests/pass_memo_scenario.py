"""Scenario test for what one pass of the minute set works out once (core/passmemo.py, core/filecache.py) — fixture data, no live store, no network, no server socket.

A pass such as the stall pass looks at every open item, and each look asked for the session roles, the session rows of the fleet and the CLI's pane rows again, from the files, once per item. They are now
worked out once for the pass, and a file that was not written since the last look is not parsed again. The results stay what they were: the same roles, the same notices, in the same order.

  1  the roles are built once per pass: a stall pass over N open items builds them once (they were built once per item), and a second pass builds them again (the memo ends with its pass); outside a pass every call builds
  2  the session rows are read once per pass (the same count), and rebuilt when a machine's session file is written in the middle of the pass
  3  the roles memo is keyed by every file the roles read: a rewritten page registry, a rewritten project record and a changed setting are each seen by the next call of the same pass
  4  a changed item is seen in the same pass: an item written, a pane's registry row rewritten (idle to busy) and a pane whose process is gone are each read at the next look, after the roles and rows were memoized
  5  a pane's registry row is parsed once while the file is as it was; whether its process is alive is asked at every look (never kept)
  6  the file cache: a changed file is read again at the next call (by its modification time, by its size, by being replaced), an unchanged one is not; a file written a moment ago is not kept; two files with
     the same size and time are two entries; a failed read is not kept; a missing file raises as before
  7  every tick of the runner runs in a pass memo, and it ends with the tick
  8  the same results: the stall pass run three times over the same store, with the pass memo and without it, leaves the same items, the same History lines and sends the same notices

    tests/run-suite pass_memo        → exit 0 / 1"""
import builtins, contextlib, io, json, os, re, secrets, sys, pathlib, threading, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="passmemo-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/demo", "brain/projects", "transcripts/-home-x", "cli"): (T / d).mkdir(parents=True)
N = 12                                                                                  # open items, each moved by a session of its own
MOVERS = [f"home-w{i}" for i in range(N)]
NAMES = ("home-front", "team-back", "home-lead", *MOVERS)
U = {n: f"00000000-0000-4000-8000-0000000000{i:02d}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True}}))
def write_sessions(extra=None):
    rows = {u: {"name": n, "machine": "a"} for n, u in U.items()}
    rows.update(extra or {})
    (T / "fleet/a/sessions.json").write_text(json.dumps(rows))
write_sessions()
ALPHA = {"home-front": "the front", "team-back": "builds, merges and releases the code"}
def registry(agents=ALPHA, back=("team-back",), status="active"):
    return {"pages": {"projects/alpha": {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": "home-lead", "status": status, "board": [], "board_open": 0,
                                           "agents": agents, "back_agents": {k: v for k, v in agents.items() if k in back}}}}
REG = T / "store/projects.json"
REG.write_text(json.dumps(registry()))
(T / "brain/projects/alpha.md").write_text("---\ntitle: alpha\ndisplay-name: home-lead\nagents:\n  home-front: the front\n  background:\n    team-back: builds, merges and releases the code\n---\n\n# alpha\n\n## Current state\n\nthe vendor call is open.\n\n<!-- timeline -->\n"); import subprocess as _sp; [_sp.run(["git", "-C", f"{tmp}/brain", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True) for a in (("init", "-q"), ("add", "-A"), ("commit", "-q", "-m", "pages"))]      # the pages are a git checkout, as an instance's are: a debt settles on a read of it that works
(T / "store/next-id").write_text("97"); (T / "store/anchors.json").write_text("{}")
B = now0 - 900.0                                                                        # the item clocks: written then, the panes idle from a minute later
IDLE0 = B + 60.0
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, mover):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": "open", "updated": B, "state_updated": B, "confirmed": B,
                                                       "metadata": {"project": "projects/alpha", "next": f"{mover}: do the thing", "mover": mover}}))
def cli_row(who, status="idle", at=IDLE0, pid=None):
    p = T / f"cli/{os.getpid()}-{who}.json"
    p.write_text(json.dumps({"pid": pid or os.getpid(), "kind": "interactive", "sessionId": U[who], "name": who, "status": status, "statusUpdatedAt": int(at * 1000), "updatedAt": int(at * 1000)}))
    return p
def age(p, seconds=30.0, bump=0):
    """Give a file a modification time `seconds` in the past (plus `bump` ns): old enough for the file cache to keep it, and a time of our choosing."""
    t = time.time_ns() - int(seconds * 1e9) + bump
    os.utime(p, ns=(t, t))
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:300]}" if got is not None else ""))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route
from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core import runner as _runner
from stackshot.fleet import fleet as _fleet
from stackshot.fleet import sessions_registry as _sr
from stackshot.projects import projects as _prj
from stackshot.service import handoff as handoff_svc, handoff_cold as hcold_svc, stall as stall_svc, stall_tick as stalltick_svc, telling
from stackshot.service import store as _service_store
try:
    from stackshot.core import passmemo as PM
    from stackshot.core import filecache as FC
except ImportError:                                  # before the change: every check that needs them fails, by name
    PM = FC = None
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
handoff_svc.CLI_SESSIONS = T / "cli"
hcold_svc.COLD_RUNNER = lambda msg: {"status": "ok", "text": "no json at all here", "duration_s": 0.1, "usage": {}, "note": "stub"}
PUSHLOG = T / "push.log"
(T / "fakepush.py").write_text(f"import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nopen({str(PUSHLOG)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered → ' + a[0])\n")
telling.PUSH = [sys.executable, str(T / "fakepush.py")]
THREADS = []
_real_tell = telling.tell_woken
def _tell(gid, who, note, tag="wake"):
    th = _real_tell(gid, who, note, tag)
    if th: THREADS.append(th)
    return th
telling.tell_woken = _tell
def drain():
    while THREADS: THREADS.pop(0).join(30)
    while hcold_svc.HO_COLD_THREADS: hcold_svc.HO_COLD_THREADS.pop(0).join(30)
    while THREADS: THREADS.pop(0).join(30)

# ---- counters on what a pass should do once
COUNT = {"roles": 0, "unreadable": 0, "opens": {}}
_real_with_pending = _prj.with_pending
def _with_pending(*a, **kw):
    if threading.current_thread() is threading.main_thread(): COUNT["roles"] += 1          # the pass's own thread: a notice's sender thread has no pass memo and is not what is counted
    return _real_with_pending(*a, **kw)
_prj.with_pending = _with_pending                    # the roles call it once per build (anchors.session_roles / file_roles)
_real_unreadable = _fleet.sessions_unreadable
def _unreadable():
    if threading.current_thread() is threading.main_thread(): COUNT["unreadable"] += 1
    return _real_unreadable()
_fleet.sessions_unreadable = _unreadable             # the session rows call it once per build
_real_open = builtins.open
def _open(f, *a, **kw):
    if isinstance(f, (str, os.PathLike)):
        s = os.fspath(f)
        if "/cli/" in s: COUNT["opens"][s] = COUNT["opens"].get(s, 0) + 1
    return _real_open(f, *a, **kw)
builtins.open = io.open = _open                      # the CLI rows are read by open (pathlib reads through io.open)
def reset_counts(): COUNT.update(roles=0, unreadable=0, opens={})

def world():
    """The store as one stall pass finds it: N open items, each with a mover whose pane has been idle for 10 minutes by T1, a project with a builder."""
    for p in (T / "store/a").glob("*.json"): p.unlink()
    for p in (T / "state").glob("stall*.json"): p.unlink()
    for p in (T / "cli").glob("*.json"): p.unlink()
    PUSHLOG.unlink(missing_ok=True)
    REG.write_text(json.dumps(registry())); write_sessions()
    for i, m in enumerate(MOVERS, 1):
        item(i, m); age(T / f"store/a/{i}.json")
        age(cli_row(m))
    age(REG); age(T / "fleet/a/sessions.json"); age(T / "store/project-record.json") if (T / "store/project-record.json").exists() else None
    stall_svc.STALL_LAST[0] = 0.0
    stall_svc.stall_since(B)
def stall_pass(at):
    stall_svc.STALL_LAST[0] = 0.0
    out = stalltick_svc.stall_tick(at); drain()
    return out
T1 = IDLE0 + 10 * 60.0 + 1.0

# ================================================================ 1. the roles once per pass
world(); reset_counts()
got = stall_pass(T1)
check("1 roles: the pass moved items (the fixture is live: a first step went out for several of the idle movers)", len(got) >= 3 and len(PUSHLOG.read_text().splitlines()) >= 3, (got, PUSHLOG.exists()))
check(f"1 roles: a stall pass over {N} open items builds the roles once", COUNT["roles"] == 1, COUNT["roles"])
reset_counts(); stall_pass(T1 + 60.0)
check("1 roles: the next pass builds them again, once (the memo ends with its pass)", COUNT["roles"] == 1, COUNT["roles"])
reset_counts()
for _ in range(5): _anc.session_roles()
check("1 roles: outside a pass every call builds them (nothing is kept between calls)", COUNT["roles"] == 5, COUNT["roles"])
reset_counts()
with (PM.scope() if PM else contextlib.nullcontext()):
    first = _anc.session_roles()
    for _ in range(4): _anc.session_roles()
    check("1 roles: five calls in one pass build them once", COUNT["roles"] == 1, COUNT["roles"])
    first["home-front"]["role"] = "mangled"
    check("1 roles: a caller that changes what it was given does not change what the pass hands on", _anc.session_roles()["home-front"]["role"] == "front", _anc.session_roles().get("home-front"))
plain = _anc.session_roles()
with (PM.scope() if PM else contextlib.nullcontext()):
    check("1 roles: the memoized roles are the roles a plain call gives", _anc.session_roles() == plain and "team-back" in plain and plain["team-back"]["role"] == "back", plain)
reset_counts()
with (PM.scope() if PM else contextlib.nullcontext()):
    _anc.session_roles()
with (PM.scope() if PM else contextlib.nullcontext()):
    _anc.session_roles()
check("1 roles: a second pass builds them again (the memo is dropped with the first)", COUNT["roles"] == 2 and not (PM and PM.active()), COUNT["roles"])
if PM:
    try:
        with PM.scope():
            _anc.session_roles(); raise RuntimeError("a pass that fails")
    except RuntimeError:
        pass
    check("1 roles: a pass that raises still drops its memo", not PM.active())
    with PM.scope():
        with PM.scope():
            pass
        check("1 roles: a pass inside a pass is the same pass (the inner end keeps the memo)", PM.active())
else:
    check("1 roles: a pass memo exists", False, "core/passmemo.py is missing")

# ================================================================ 2. the session rows once per pass
world(); reset_counts()
stall_pass(T1)
check("2 rows: a stall pass reads the fleet's session rows once", COUNT["unreadable"] == 1, COUNT["unreadable"])
reset_counts()
with (PM.scope() if PM else contextlib.nullcontext()):
    for _ in range(6): _sr._sessions_index()
    check("2 rows: six looks in one pass build the index once", COUNT["unreadable"] == 1, COUNT["unreadable"])
    NEW = "00000000-0000-4000-8000-0000000009ff"
    check("2 rows: before the write the new session is not there", NEW not in _sr._sessions_index())
    write_sessions({NEW: {"name": "home-new", "machine": "a"}}); age(T / "fleet/a/sessions.json", 20.0)
    check("2 rows: a machine's session file written in the middle of the pass is read at the next look", (_sr._sessions_index().get(NEW) or {}).get("name") == "home-new", list(_sr._sessions_index())[-3:])
    check("2 rows: and the index was built again for it", COUNT["unreadable"] == 2, COUNT["unreadable"])

# ================================================================ 3. the roles memo is keyed by every file the roles read
world()
with (PM.scope() if PM else contextlib.nullcontext()):
    check("3 key: before the rewrite team-back is a background agent", _anc.session_roles()["team-back"]["role"] == "back")
    REG.write_text(json.dumps(registry({"home-front": "the front", "team-back": "the front too", "home-extra": "another one"}, back=()))); age(REG, 20.0)
    r = _anc.session_roles()
    check("3 key: a page registry written in the middle of the pass is read at the next call (an agent added, a role changed)", "home-extra" in r and r["team-back"]["role"] == "front", {k: v.get("role") for k, v in r.items()})
    REG.write_text(json.dumps(registry())); age(REG, 25.0)
    check("3 key: and written back, it is read again", "home-extra" not in _anc.session_roles() and _anc.session_roles()["team-back"]["role"] == "back")
    rec = T / "store/project-record.json"
    if PM:
        PID = "prj_" + secrets.token_hex(4)                                  # an id the record accepts, minted as the product mints one
        rec.write_text(json.dumps({"schema": 1, "ids": {PID: "projects/alpha"}, "pending_agents": {PID: {"home-owed": {"mandate_line": "an agent only the record holds", "role": "builder", "front": False}}}}))
        age(rec, 20.0)
    check("3 key: a project record written in the middle of the pass is read at the next call (an owed agent appears)", "home-owed" in _anc.session_roles(), list(_anc.session_roles()))
    if rec.exists(): rec.write_text(json.dumps({"schema": 1, "ids": {}, "pending_agents": {}})); age(rec, 25.0)
    check("3 key: and emptied, it is read again", "home-owed" not in _anc.session_roles(), list(_anc.session_roles()))
    was = _cfg.CFG.get("project_scopes")
    REG.write_text(json.dumps(registry({"team-back": ALPHA["team-back"]}, status="paused"))); age(REG, 15.0)      # no user-facing agent: the name line is retired only by the page's status
    base_status = _anc.session_roles()["home-lead"].get("retired")
    _cfg.CFG["project_scopes"] = {**(was or {}), "retired_statuses": ["paused"]}
    check("3 key: a changed setting (the words that retire a page) is seen at the next call", _anc.session_roles()["home-lead"].get("retired") is True and not base_status, (base_status, _anc.session_roles()["home-lead"]))
    if was is None: _cfg.CFG.pop("project_scopes", None)
    else: _cfg.CFG["project_scopes"] = was
REG.write_text(json.dumps(registry())); age(REG)
if rec.exists(): rec.unlink()

# ================================================================ 4. a change is seen in the same pass
world()
with (PM.scope() if PM else contextlib.nullcontext()):
    _anc.session_roles(); _sr._sessions_index()                                        # both memoized now
    st, at = handoff_svc.handoff_status("home-w0")
    check("4 changed: the pane reads idle at the first look", st == "idle", (st, at))
    cli_row("home-w0", "busy", at=time.time()); age(T / f"cli/{os.getpid()}-home-w0.json", 0.5)
    st2, _ = handoff_svc.handoff_status("home-w0")
    check("4 changed: its registry row rewritten in the middle of the pass (busy) is read at the next look", st2 == "busy", st2)
    gid0 = "a1"
    before = _service_store._load(gid0)
    d = json.loads((T / "store/a/1.json").read_text()); d["metadata"]["mover"] = "home-w5"; d["metadata"]["next"] = "home-w5: do the thing"
    (T / "store/a/1.json").write_text(json.dumps(d))
    after = _service_store._load(gid0)
    check("4 changed: an item written in the middle of the pass is read as written (items are never kept)", before["metadata"]["mover"] == "home-w0" and after["metadata"]["mover"] == "home-w5", (before["metadata"], after["metadata"]))
    check("4 changed: and the mover the pass derives from it is the new one", stall_svc.stall_mover(gid0, after) == "home-w5", stall_svc.stall_mover(gid0, after))
    gone = cli_row("home-w1", "idle", pid=2 ** 22 + 12345)                              # a pid that is not running
    age(gone, 20.0)
    check("4 changed: a pane whose process is gone is not a pane (liveness is asked at every look)", handoff_svc.handoff_status("home-w1")[0] == "", handoff_svc.handoff_status("home-w1"))
    live_again = cli_row("home-w1", "idle"); age(live_again, 30.0, bump=7)
    check("4 changed: and the same row with a live process is one again", handoff_svc.handoff_status("home-w1")[0] == "idle", handoff_svc.handoff_status("home-w1"))

# ================================================================ 5. a pane's row is parsed once while the file is as it was
world(); reset_counts()
row = str(T / f"cli/{os.getpid()}-home-w2.json")
for _ in range(15): handoff_svc.handoff_status("home-w2")
check("5 panes: fifteen looks at one pane open its registry row once (not once per look)", COUNT["opens"].get(row, 0) <= 1, COUNT["opens"].get(row))
check("5 panes: and every other row too", max(COUNT["opens"].values() or [0]) <= 1, sorted(COUNT["opens"].items(), key=lambda kv: -kv[1])[:2])
dead = cli_row("home-w3", "idle", pid=2 ** 22 + 23456); age(dead, 20.0)
check("5 panes: a row of a process that is not running says nothing, however often it is asked", all(handoff_svc.handoff_status("home-w3")[0] == "" for _ in range(3)))
import subprocess
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
try:
    age(cli_row("home-w4", "idle", pid=child.pid), 20.0)
    with (PM.scope() if PM else contextlib.nullcontext()):
        up = [handoff_svc.handoff_status("home-w4")[0] for _ in range(3)]
        child.terminate(); child.wait(10)                                                    # the process ends; its row file is not touched
        down = [handoff_svc.handoff_status("home-w4")[0] for _ in range(2)]
    check("5 panes: a process that ends while its row stays as it was is no pane at the next look (liveness is never kept)", up == ["idle"] * 3 and down == [""] * 2, (up, down))
finally:
    if child.poll() is None: child.kill(); child.wait(10)

# ================================================================ 6. the file cache
if FC:
    FC.forget()
    t0 = time.time_ns() - 30_000_000_000
    f2 = T / "cli" / "fc.json"; f2.write_text('{"v": 1}'); os.utime(f2, ns=(t0, t0)); COUNT["opens"] = {}                  # under cli/, where the counter looks
    r1 = [FC.read_json(f2) for _ in range(5)]
    check("6 cache: five reads of a file nobody wrote open it once", COUNT["opens"].get(str(f2)) == 1 and r1[0] == {"v": 1} and r1[0] is r1[4], COUNT["opens"])
    f2.write_text('{"v": 22}'); os.utime(f2, ns=(t0, t0))                                                                       # a different size, the same time
    check("6 cache: a file rewritten with another size and the same time is read again", FC.read_json(f2) == {"v": 22}, FC.read_json(f2))
    f2.write_text('{"v": 33}'); os.utime(f2, ns=(t0 + 5_000_000, t0 + 5_000_000))                                                # the same size, another time
    check("6 cache: a file rewritten with the same size and another time is read again", FC.read_json(f2) == {"v": 33}, FC.read_json(f2))
    tmpf = T / "cli" / "fc.json.tmp"; tmpf.write_text('{"v": 44}'); os.utime(tmpf, ns=(t0 + 5_000_000, t0 + 5_000_000)); os.replace(tmpf, f2)   # replaced: the same size and time, another file
    check("6 cache: a file replaced by another of the same size and time is read again (its inode differs)", FC.read_json(f2) == {"v": 44}, FC.read_json(f2))
    fresh = T / "cli" / "fresh.json"; fresh.write_text('{"v": 1}'); COUNT["opens"] = {}
    FC.read_json(fresh); FC.read_json(fresh)
    check("6 cache: a file written a moment ago is not kept (a clock of coarse steps could hide a second write)", COUNT["opens"].get(str(fresh)) == 2, COUNT["opens"])
    a = T / "cli" / "same-a.json"; b = T / "cli" / "same-b.json"
    a.write_text('{"w": "aaa"}'); b.write_text('{"w": "bbb"}')
    os.utime(a, ns=(t0, t0)); os.utime(b, ns=(t0, t0))
    check("6 cache: two files of the same size and time are two entries", FC.read_json(a) == {"w": "aaa"} and FC.read_json(b) == {"w": "bbb"} and FC.read_json(a) == {"w": "aaa"}, (FC.read_json(a), FC.read_json(b)))
    bad = T / "cli" / "bad.json"; bad.write_text("{not json"); os.utime(bad, ns=(t0, t0))
    try: FC.read_json(bad); raised = False
    except ValueError: raised = True
    bad.write_text('{"ok": 1}'); os.utime(bad, ns=(t0 - 1_000_000, t0 - 1_000_000))
    check("6 cache: a read that failed is not kept, and the file read after it is read", raised and FC.read_json(bad) == {"ok": 1}, raised)
    try: FC.read_json(T / "cli" / "none.json"); missing = False
    except FileNotFoundError: missing = True
    check("6 cache: a missing file raises as json.load of an open would", missing)
else:
    check("6 cache: a file cache exists", False, "core/filecache.py is missing")

# ================================================================ 7. every tick of the runner runs in a pass memo
if PM:
    seen = []
    def tick_a(): seen.append(("a", PM.active(), [_anc.session_roles() for _ in range(3)] and COUNT["roles"]))
    def tick_b(): seen.append(("b", PM.active(), [_anc.session_roles() for _ in range(3)] and COUNT["roles"]))
    def tick_boom(): raise RuntimeError("a tick that raises")
    world(); reset_counts()
    rn = _runner.Runner([_runner.Tick("a", tick_a, "fleet"), _runner.Tick("boom", tick_boom, "fleet"), _runner.Tick("b", tick_b, "fleet")], clock=lambda: 1000.0)
    with contextlib.redirect_stderr(io.StringIO()):
        rn.run_round()
    check("7 runner: each tick runs inside a pass memo, which ends with the tick (also one that raises)", [s[:2] for s in seen] == [("a", True), ("b", True)] and not PM.active(), seen)
    check("7 runner: the roles are built once per tick", [s[2] for s in seen] == [1, 2], seen)
else:
    check("7 runner: a pass memo exists", False, "core/passmemo.py is missing")

# ================================================================ 8. the same results with and without the pass memo
def norm(s): return re.sub(r"\d{2}:\d{2}", "HM", re.sub(r"\d{10}(\.\d+)?(e[+-]?\d+)?", "T", s.replace(str(T), "TMP")))
def digest(passes):
    world(); out = []
    for k in range(passes):
        out.append(sorted(stall_pass(T1 + 700.0 * k)))
    items = {p.stem: norm(p.read_text()) for p in (T / "store/a").glob("*.json")}
    pushes = sorted(norm(PUSHLOG.read_text() if PUSHLOG.exists() else "").splitlines())
    return out, items, pushes
with_memo = digest(3)
if PM:
    _real_scope = PM.scope
    PM.scope = lambda: contextlib.nullcontext()
    try: without = digest(3)
    finally: PM.scope = _real_scope
    check("8 same: the passes act on the same items, in the same order, with the memo and without it", with_memo[0] == without[0] and any(with_memo[0]), (with_memo[0], without[0]))
    check("8 same: every item and its History end the same", with_memo[1] == without[1], [k for k in with_memo[1] if with_memo[1][k] != without[1].get(k)][:3])
    check("8 same: the same notices go out, to the same sessions, with the same words", with_memo[2] == without[2] and len(with_memo[2]) >= 6, (len(with_memo[2]), len(without[2])))
else:
    check("8 same: a pass memo exists to compare with", False, "core/passmemo.py is missing")

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
