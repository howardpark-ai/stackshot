"""Scenario test for the files the server and the minute runner tell each other through (stackshot/core/runner_files.py, the Runner's `wake_stamp` and `beat`, service/runner.py `wake`, `status`, `watchdog`,
`record_server_start`, waits/watchers.py's hold file, service/fleet_events.py `flag_start`): what a runner in another process needs, while the runner stays a thread of the server. A scratch instance, real
OS processes for the other side (this file, run with `child <what>`), real threads for the runner, no server running.

  1  wake      a wake is written on every `wake()` (the line differs each time, no temp file is left) · a waiting runner's wait ends within a second of a wake that ANOTHER process wrote (and does not end
               without the file) · a wake of this process ends it at once and brings one round, not two · `runner.wake()` is what `update`, an answer and the migration's end call
  2  hold      the hold of this process is in memory and the file is skipped as its own · a hold file of another live process holds `board=True` ticks and a plain tick still runs · a dead pid, a lapsed
               `until` and a `since` past the ceiling hold nothing · a holder that dies without releasing leaves a file that holds nothing · `release()` lifts this process's file and never another's
  3  status    the Runner hands its record to `beat` at the top of each loop iteration, at each tick's start and at the end of a round (pid, heartbeat, the tick running, the tick that ran last) · the server reads
               the status file when it has no runner of its own (`source` file, `running` by pid and heartbeat) and its own runner's record when it has one · a file of this process is not read back · /audit/status shows it
  4  watchdog  a stale heartbeat, or a last round past the limit with a fresh heartbeat, is told once to the builder with the tick named, and re-arms; a dead pid is told as a process that is gone; a current
               one, this process's own file and no file say nothing
  5  start     the server writes its start when it starts the runner; in the server the flag's start is its own value, and a runner that restarts alone takes the start of the running server (not its own,
               not a dead server's)
  6  torn      every reader takes a missing, empty, torn, wrongly shaped or binary file as nothing there and never raises; the Runner takes a wake file that cannot be read as no wake
  7  standby   with STACKSHOT_READ_ONLY=1 none of the four files is written (and the in-memory hold and wake still work)

    tests/run-suite runner_signals        -> exit 0 / 1"""
import contextlib, io, json, os, pathlib, re, shutil, signal, subprocess, sys, threading, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
CHILD = len(sys.argv) > 1 and sys.argv[1] == "child"
if CHILD:
    tmp = os.environ["SIGNALS_TEST_TMP"]; T = pathlib.Path(tmp)
else:
    tmp = _scratch.mkdtemp(prefix="s2-signals-"); T = pathlib.Path(tmp)
    toml = _instance.apply(_instance.base_toml())
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")
    for d in ("store/a", "fleet/a", "state", "brain/projects", "home"): (T / d).mkdir(parents=True)
    (T / "store/next-id").write_text("500"); (T / "store/anchors.json").write_text("{}")
    os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet", HOME=f"{tmp}/home", SIGNALS_TEST_TMP=tmp)
    os.environ.pop("STACKSHOT_URL", None); os.environ.pop("STACKSHOT_READ_ONLY", None)

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""), flush=True)

from stackshot.core import config as _cfg, runner as R, runner_files as F, readonly as _ro      # noqa: E402
MIN = T / "state" / "minute"


# ---------------------------------------------------------------------------- the other process
def child(kind):
    """What the second process does. It says `ready` when it is set up, then waits for a line on stdin (or for its stdin to close) before it goes on."""
    def ready(): print("ready", flush=True)
    def wait_line(): sys.stdin.readline()
    if kind == "wake":                                        # only writes the wake file, nothing else
        F.wake(); return
    if kind == "hold":                                        # begins a hold through the real function, then dies WITHOUT releasing it
        from stackshot.waits import watchers
        watchers.hold("demo-pass", 600.0, begin=True); ready(); wait_line(); os._exit(0)
    if kind == "status":                                      # a runner of its own that has run one round and reports to the status file
        r = R.Runner([R.Tick("demo_tick", lambda: None, "settle")], beat=F.status_write); r.started = time.time(); r.run_round(event=True); ready(); wait_line(); return
    if kind == "start":                                       # the server: writes its start (an hour ago) and stays up
        F.start_write(time.time() - 3600.0); ready(); wait_line(); return
    raise SystemExit(f"no such child {kind}")


if CHILD:
    child(sys.argv[2]); sys.exit(0)

from stackshot.web import server                          # noqa: E402,F401  (the wiring: hooks, and the routes)
from stackshot.service import runner as runner_svc, fleet_events as fleetev      # noqa: E402
from stackshot.waits import watchers as W                 # noqa: E402

KIDS = []
def spawn(kind, wait_ready=True):
    pr = subprocess.Popen([sys.executable, os.path.abspath(__file__), "child", kind], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=STACK); KIDS.append(pr)
    if wait_ready:
        line = pr.stdout.readline()
        if line.strip() != "ready": raise RuntimeError(f"child {kind} said {line!r}: {pr.stderr.read()[-500:]}")
    return pr

def end_kid(pr):
    """Let a waiting child go on (by its stdin) and wait for it: it ends by itself."""
    try:
        if pr.stdin and not pr.stdin.closed: pr.stdin.write("\n"); pr.stdin.flush(); pr.stdin.close()
    except OSError: pass
    try: pr.wait(timeout=20)
    except subprocess.TimeoutExpired: pr.kill(); pr.wait()
    for f in (pr.stdout, pr.stderr):
        if f and not f.closed: f.close()

def live():
    """A process that is alive and is not this one (it only sleeps); `stop_live` ends it by its pid."""
    pr = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"]); KIDS.append(pr); return pr

def stop_live(pr):
    pr.kill(); pr.wait()

def dead_pid():
    pr = subprocess.Popen([sys.executable, "-c", "pass"]); pr.wait(); return pr.pid        # a pid that has just ended (not reused within a test)

def eventually(cond, within=5.0):
    end = time.time() + within
    while time.time() < end:
        if cond(): return True
        time.sleep(0.01)
    return cond()

def clear_files():
    shutil.rmtree(MIN, ignore_errors=True)

def put(name, text):
    MIN.mkdir(parents=True, exist_ok=True); (MIN / name).write_text(text, encoding="utf-8")

def hold_file(pid, by="demo-pass", since=None, until=None):
    t = time.time(); put(F.HOLD, json.dumps({"pid": pid, "by": by, "since": t - 5 if since is None else since, "until": t + 300 if until is None else until, "written": t}))

@contextlib.contextmanager
def stderr_lines():
    buf, real = io.StringIO(), sys.stderr
    sys.stderr = buf
    try: yield buf
    finally: sys.stderr = real

def small(**kw):
    """A runner over one event tick that records its runs; its wake wait is a minute, so only a wake can bring a second round soon."""
    seen = []
    return R.Runner([R.Tick("ev", lambda: seen.append(time.time()), "settle", "event")], wake_wait=lambda: 60.0, **kw), seen


try:
    # ---- 1. the wake file
    clear_files()
    F.wake(); a = F.wake_stamp(); F.wake(); b = F.wake_stamp()
    check("1 wake: every wake writes a line, and it differs from the one before (time, pid and count)", bool(a) and bool(b) and a != b and len(a.split()) == 3 and a.split()[1] == str(os.getpid()), (a, b))
    check("1 wake: the file is replaced whole: no temp file is left beside it", [n for n in os.listdir(MIN) if n != "wake"] == [], os.listdir(MIN))
    clear_files()
    check("1 wake: no file, no line", F.wake_stamp() is None)
    F.wake()
    stopw = threading.Event(); seen_w = []
    def reader():
        while not stopw.is_set(): seen_w.append(F.wake_stamp())
    rt_ = threading.Thread(target=reader); rt_.start()
    for _ in range(1500): F.wake()
    stopw.set(); rt_.join()
    bad_w = [x for x in seen_w if x is None or len(x.split()) != 3]
    check("1 wake: the write is atomic: a reader that looks all the while (during 1500 writes) never sees an empty or cut line", len(seen_w) > 100 and not bad_w, (len(seen_w), bad_w[:3]))

    rn, seen = small(wake_stamp=F.wake_stamp)
    rn.start()
    try:
        check("1 wake file: the first event round runs at once", eventually(lambda: len(seen) == 1, 3.0), seen)
        time.sleep(0.3)
        subprocess.run([sys.executable, os.path.abspath(__file__), "child", "wake"], check=True, cwd=STACK, timeout=60, capture_output=True)
        t0 = time.time()
        check("1 wake file: a wake written by ANOTHER process ends the waiting runner's wait: a second event round runs within a second and a half", eventually(lambda: len(seen) == 2, 3.0) and time.time() - t0 < 1.5, (len(seen), time.time() - t0))
        check("1 wake file: …it is the wake file that did it (the round is the loop's, the status counts it)", rn.rounds >= 2, rn.rounds)
        time.sleep(2.2)
        check("1 wake file: …one wake, one round: the line taken at that round is not a wake again", len(seen) == 2, seen)
    finally:
        rn.stop()
    rn2, seen2 = small()                                    # the control: the same runner without the wake file does not wake for it
    rn2.start()
    try:
        eventually(lambda: len(seen2) == 1, 3.0)
        subprocess.run([sys.executable, os.path.abspath(__file__), "child", "wake"], check=True, cwd=STACK, timeout=60, capture_output=True)
        time.sleep(2.5)
        check("1 wake file: …and without a wake file given to it the runner sleeps through that write (the file is what wakes it)", len(seen2) == 1, seen2)
    finally:
        rn2.stop()

    runner_svc.WAKE_EVENT.clear()
    rn3, seen3 = small(wake_stamp=F.wake_stamp, event=runner_svc.WAKE_EVENT)
    rn3.start()
    try:
        eventually(lambda: len(seen3) == 1, 3.0); time.sleep(0.3)
        t0 = time.time(); runner_svc.wake()
        check("1 wake: a wake of this process (`runner.wake()`) ends the wait at once, by the event", eventually(lambda: len(seen3) == 2, 3.0) and time.time() - t0 < 0.8, (len(seen3), time.time() - t0))
        check("1 wake: …and it wrote the wake file too", F.wake_stamp() is not None and F.wake_stamp().split()[1] == str(os.getpid()), F.wake_stamp())
        time.sleep(2.3)
        check("1 wake: …the event and the file are one wake: exactly one round, not two", len(seen3) == 2, seen3)
    finally:
        rn3.stop()
    rn4 = runner_svc._new()
    check("1 wake: the server's runner is built over the event, the wake file and the status file", rn4.wake is runner_svc.WAKE_EVENT and rn4.wake_stamp is F.wake_stamp and rn4.beat is runner_svc._beat, (rn4.wake_stamp, rn4.beat))
    import inspect
    from stackshot.web import wiring as _wiring
    from stackshot.service import answer as _answer, migrations as _migrations
    check("1 wake: update's hook, the answer and the migration's end call `runner.wake()`, and nothing sets the event bare",
          all("WAKE_EVENT.set()" not in inspect.getsource(m) for m in (_wiring, _answer, _migrations)) and all("_runner.wake()" in inspect.getsource(m) for m in (_wiring, _answer, _migrations)))

    # ---- 2. the hold file
    clear_files(); W.release()
    W.hold("demo-pass", 600.0, begin=True)
    d = F._json(F.HOLD) or {}
    check("2 hold: the pass's hold is written to the hold file with its holder's pid, who began it, when it began and until when", d.get("pid") == os.getpid() and d.get("by") == "demo-pass" and d.get("until", 0) > time.time() + 500 and 0 < d.get("since", 0) <= time.time(), d)
    check("2 hold: this process's file is its own: read as nothing (the hold is in memory), and the hold stands", F.hold_read() is None and W.holding() and W.holder() == "demo-pass")
    W.release()
    check("2 hold: release lifts the hold and removes the file", not W.holding() and not (MIN / F.HOLD).exists(), os.listdir(MIN) if MIN.exists() else None)

    kid = live()
    try:
        hold_file(kid.pid)
        check("2 hold: a hold file of another LIVE process holds the board, and names who began it", W.holding() and W.holder() == "demo-pass" and F.hold_read()["pid"] == kid.pid, F.hold_read())
        plain, boardy = [], []
        held = R.Runner([R.Tick("plain", lambda: plain.append(1), "fleet"), R.Tick("boardy", lambda: boardy.append(1), "fleet", board=True)], holding=W.holding)
        held.run_round()
        check("2 hold: …a `board=True` tick is skipped (and counted skipped) while a plain tick still runs", plain == [1] and boardy == [] and {t["name"]: t["skipped"] for t in held.status()["ticks"]}["boardy"] == 1, (plain, boardy))
        check("2 hold: …the pause switch reads it too (watchers.paused)", W.paused() is True)
        W.release()
        check("2 hold: …release() in this process does not lift another process's hold", (MIN / F.HOLD).exists() and W.holding())
        check("2 hold: …the hold lapses at its `until` (a look after it is a look at no hold)", not W.holding(now=time.time() + 400))
        hold_file(kid.pid, until=time.time() - 1)
        check("2 hold: a file whose `until` has passed holds nothing (live pid)", not W.holding() and W.holder() == "")
        hold_file(kid.pid, since=time.time() - 4000, until=time.time() + 600)
        check("2 hold: a file whose `since` is past the ceiling holds nothing, whatever its `until` says (live pid)", not W.holding(), F.hold_read(ceiling=3600.0))
        hold_file(kid.pid)
    finally:
        stop_live(kid)
    check("2 hold: the same file, its holder now dead: holds nothing", not W.holding() and W.holder() == "" and F.hold_read() is None)
    plain, boardy = [], []
    free = R.Runner([R.Tick("plain", lambda: plain.append(1), "fleet"), R.Tick("boardy", lambda: boardy.append(1), "fleet", board=True)], holding=W.holding)
    free.run_round()
    check("2 hold: …so a `board=True` tick runs", plain == [1] and boardy == [1], (plain, boardy))
    hold_file(dead_pid())
    check("2 hold: a file of a pid that ended long ago holds nothing", not W.holding())

    clear_files()
    hk = spawn("hold")                                        # the real thing: another process begins a pass through watchers.hold and then dies without releasing it
    try:
        check("2 hold: a pass begun in another process holds this one's board, through the real `hold`", W.holding() and W.holder() == "demo-pass", F.hold_read())
        check("2 hold: …and its hold file is that process's (its pid, not this one's)", (F._json(F.HOLD) or {}).get("pid") == hk.pid != os.getpid())
    finally:
        end_kid(hk)
    check("2 hold: …the holder died without a release: the file is still there and holds nothing", (MIN / F.HOLD).exists() and not W.holding() and W.holder() == "")
    clear_files()

    # ---- 3. the status file and the heartbeat
    beats = []
    clk = [100.0]
    rb = R.Runner([R.Tick("one", lambda: None, "settle"), R.Tick("two", lambda: None, "settle")], clock=lambda: clk[0], beat=beats.append, label="runner")
    rb.started = 90.0
    rb.run_round(event=True)
    check("3 heartbeat: a tick's start and the end of a round hand the record to `beat` (2 ticks: a start each, and the round's end)", len(beats) == 3, [b["current"] for b in beats])
    check("3 heartbeat: …each carries the pid, the heartbeat (the runner's clock), the tick running, the tick that ran last and the status fields",
          all(b["pid"] == os.getpid() and b["heartbeat"] == 100.0 for b in beats) and [b["current"] for b in beats] == ["one", "two", ""] and beats[2]["last_tick"]["name"] == "two"
          and beats[2]["rounds"] == 1 and beats[2]["last_round"] == 100.0 and beats[2]["started"] == 90.0 and [t["name"] for t in beats[2]["ticks"]] == ["one", "two"] and "start" in beats[2]["last_tick"] and "end" in beats[2]["last_tick"], beats[2])
    rb2 = R.Runner([R.Tick("one", lambda: None, "settle")], beat=lambda s: (_ for _ in ()).throw(RuntimeError("beat broke")))
    with stderr_lines() as err:
        out = rb2.run_round(event=True)
    check("3 heartbeat: a `beat` that raises is a stderr line and never stops the round", out == ["one"] and "status not written: RuntimeError: beat broke" in err.getvalue(), (out, err.getvalue()))
    loops = []
    rl = R.Runner([R.Tick("one", lambda: None, "settle")], beat=loops.append, wake_wait=lambda: 60.0)
    rl.start()
    try:
        n0 = eventually(lambda: len(loops) >= 2, 3.0)
        t_first = len(loops)
        check("3 heartbeat: the loop beats at the top of each iteration (before and after its first event round: at least 3 within seconds)", n0 and t_first >= 2, len(loops))
        k = len(loops); rl.wake.set()
        check("3 heartbeat: …and again for every iteration a wake brings", eventually(lambda: len(loops) > k, 3.0), (k, len(loops)))
    finally:
        rl.stop()

    clear_files()
    rf = R.Runner([R.Tick("one", lambda: None, "settle")], beat=runner_svc._beat, label="runner"); rf.started = time.time(); rf.run_round(event=True)
    own = F.status_read(own=True)
    check("3 status file: the runner's record is written to <state>/minute/status.json (atomic: no temp file beside it)", own is not None and own["pid"] == os.getpid() and own["rounds"] == 1 and [n for n in os.listdir(MIN) if n.startswith(".")] == [], (own, os.listdir(MIN)))
    check("3 status file: a record this process wrote is not read back as another process's", F.status_read() is None)
    runner_svc.RUNNER[:] = []
    st = runner_svc.status()
    check("3 status: with no runner of its own and only its own file the server reports a runner that has not started", st.get("running") is False and st.get("rounds") == 0 and "source" not in st and len(st["ticks"]) == len(runner_svc.ticks()), st)

    sk = spawn("status")
    try:
        st = runner_svc.status()
        check("3 status: with no runner of its own the server reads the status file another process keeps: its record, `source` file, its pid, its heartbeat, `running` (pid alive, heartbeat fresh)",
              st.get("source") == "file" and st["pid"] == sk.pid and st["running"] is True and st["rounds"] == 1 and [t["name"] for t in st["ticks"]] == ["demo_tick"] and st["mode"] == "runner" and st["enabled"] is True, st)
        mine = R.Runner([R.Tick("own_tick", lambda: None, "settle")], label="runner"); runner_svc.RUNNER[:] = [mine]
        try:
            st2 = runner_svc.status()
            check("3 status: …and with a runner of its own the server reports that one, from memory (no `source`, its own tick)", "source" not in st2 and [t["name"] for t in st2["ticks"]] == ["own_tick"], st2)
        finally:
            runner_svc.RUNNER[:] = []
        from starlette.testclient import TestClient
        app = server.mcp.http_app()
        with TestClient(app, base_url="https://board.example.org") as c:
            j = c.get("/audit/status").json().get("runner") or {}
        check("3 /audit/status: shows the runner of the other process: its ticks, `source` file and `running`", j.get("source") == "file" and j.get("pid") == sk.pid and j.get("running") is True and [t["name"] for t in j.get("ticks", [])] == ["demo_tick"], j)
        snap = F.status_read(); put(F.STATUS, json.dumps({**snap, "heartbeat": time.time() - 400}))
        check("3 status: a heartbeat older than the limit shows `running` false (the process is alive)", runner_svc.status()["running"] is False and runner_svc.status()["source"] == "file", runner_svc.status())
    finally:
        end_kid(sk)
    check("3 status: …and so does a process that has ended (fresh heartbeat, dead pid)", (put(F.STATUS, json.dumps({**F.status_read(), "heartbeat": time.time()})) or True) and runner_svc.status()["running"] is False)

    # ---- 4. the watchdog over the file
    sent = []
    real_send, real_audit = fleetev.inbox_flag_send, dict(_cfg.CFG.get("audit") or {})
    fleetev.inbox_flag_send = lambda to, text: sent.append((to, text))
    _cfg.CFG["audit"] = {**real_audit, "builder": "demo-builder"}
    runner_svc.RUNNER[:] = []; runner_svc.RUNNER_STALL[0] = False
    wk = live()
    def snap_of(pid, hb_age, round_age, current="demo_tick"):
        now = time.time()
        return {"pid": pid, "heartbeat": now - hb_age, "last_round": None if round_age is None else now - round_age, "started": now - 5000, "current": current, "rounds": 7, "ticks": [], "enabled": True, "mode": "runner"}
    try:
        clear_files()
        check("4 watchdog file: no status file and no runner: nothing to say", runner_svc.watchdog() == "" and sent == [])
        put(F.STATUS, json.dumps(snap_of(wk.pid, 10, 10)))
        check("4 watchdog file: a current runner (heartbeat and last round fresh) says nothing", runner_svc.watchdog() == "" and sent == [] and runner_svc.RUNNER_STALL[0] is False)
        put(F.STATUS, json.dumps(snap_of(os.getpid(), 900, 900)))
        check("4 watchdog file: a stale file of THIS process is not another runner's: nothing to say", runner_svc.watchdog() == "" and sent == [])
        put(F.STATUS, json.dumps(snap_of(wk.pid, 420, 420)))
        with stderr_lines() as err:
            r1 = runner_svc.watchdog()
        check("4 watchdog file: a stale heartbeat is the stall report: one message to the builder naming the tick, one log line, nothing owed",
              r1 == "told" and len(sent) == 1 and sent[0][0] == "demo-builder" and "7 min" in sent[0][1] and "stuck in the tick demo_tick" in sent[0][1] and "no reply is owed" in sent[0][1]
              and err.getvalue().count("stalled") == 1 and "tick is blocking the one thread" in err.getvalue(), (r1, sent, err.getvalue()))
        with stderr_lines() as err:
            r2 = runner_svc.watchdog()
        check("4 watchdog file: …a second look while it stays stale sends and logs nothing more", r2 == "noted" and len(sent) == 1 and err.getvalue() == "", (r2, sent, err.getvalue()))
        put(F.STATUS, json.dumps(snap_of(wk.pid, 5, 5)))
        check("4 watchdog file: …a fresh heartbeat re-arms it", runner_svc.watchdog() == "" and runner_svc.RUNNER_STALL[0] is False and len(sent) == 1)
        put(F.STATUS, json.dumps(snap_of(wk.pid, 5, 400)))
        check("4 watchdog file: a fresh heartbeat but a last round past the limit (a round that never completes) is the stall too, as in the runner's own check", runner_svc.watchdog() == "told" and len(sent) == 2, sent)
        put(F.STATUS, json.dumps(snap_of(wk.pid, 5, 5))); runner_svc.watchdog()
        put(F.STATUS, json.dumps(snap_of(wk.pid, 420, 5)))
        check("4 watchdog file: a heartbeat that stopped moving is the stall even when the file's last round looks recent (the heartbeat is the proof of life)", runner_svc.watchdog() == "told" and len(sent) == 3, sent)
        put(F.STATUS, json.dumps(snap_of(wk.pid, 5, 5))); runner_svc.watchdog()
        put(F.STATUS, json.dumps(snap_of(wk.pid, 700, 700, current="")))
        runner_svc.watchdog()
        check("4 watchdog file: no tick named: the message says the loop itself is stuck", "no tick is running, so the loop itself is stuck" in sent[-1][1], sent[-1][1])
        put(F.STATUS, json.dumps(snap_of(wk.pid, 5, 5))); runner_svc.watchdog()
        put(F.STATUS, json.dumps(snap_of(dead_pid(), 420, 420)))
        sent.clear()
        with stderr_lines() as err:
            r5 = runner_svc.watchdog()
        check("4 watchdog file: a runner whose process is gone is told as that (no tick to name)", r5 == "told" and len(sent) == 1 and "its process is gone" in sent[0][1] and "stuck in the tick" not in sent[0][1] and "its process is gone" in err.getvalue(), (r5, sent, err.getvalue()))
        put(F.STATUS, json.dumps(snap_of(wk.pid, 5, 5))); runner_svc.watchdog()
        put(F.STATUS, json.dumps(snap_of(wk.pid, 5, None)))
        check("4 watchdog file: no round yet is measured from the start, as the runner's own check does", runner_svc.watchdog() == "told", sent)
        # a runner of this process wins over a file: the in-memory check is the one that runs
        mine = R.Runner([R.Tick("noop", lambda: None, "settle")], label="runner"); mine.started = time.time(); runner_svc.RUNNER[:] = [mine]; runner_svc.RUNNER_STALL[0] = False
        put(F.STATUS, json.dumps(snap_of(wk.pid, 900, 900)))
        check("4 watchdog file: with a runner of its own the watchdog looks at that one (its file of another process is not asked)", runner_svc.watchdog() == "", sent)
    finally:
        runner_svc.RUNNER[:] = []; runner_svc.RUNNER_STALL[0] = False
        fleetev.inbox_flag_send = real_send; _cfg.CFG["audit"] = real_audit
        stop_live(wk)

    # ---- 5. the server's start for the inbox flag
    clear_files()
    t_before = time.time()
    runner_svc.record_server_start()
    sd = F._json(F.START) or {}
    check("5 start: the server writes its pid and its start (the flag's value) when it starts the runner", sd.get("pid") == os.getpid() and sd.get("start") == fleetev.INBOX_FLAG_START[0], sd)
    src_sb = inspect.getsource(server._start_background)
    check("5 start: the server's start writes the start before it starts the runner", 0 <= src_sb.find("_runner.record_server_start()") < src_sb.find("_runner.start()"), src_sb[-400:])
    check("5 start: in the server with the runner inline the flag's start is its own value, and its own file is not read back", fleetev.flag_start() == fleetev.INBOX_FLAG_START[0] and F.start_read() is None)
    real_start, real_last = fleetev.INBOX_FLAG_START[0], fleetev.INBOX_FLAG_LAST[0]
    from stackshot.fleet import inbox as _inbox, clients as _clients
    real_overdue, real_mins = _inbox.new_overdue, fleetev.inbox_flag_minutes
    _inbox.new_overdue = lambda *a, **k: []; fleetev.inbox_flag_minutes = lambda: 5.0
    gate = _clients.POLL_MAX + 15
    try:
        def passes(now):
            fleetev.INBOX_FLAG_LAST[0] = 0.0; fleetev.inbox_flag_tick(now=now); return fleetev.INBOX_FLAG_LAST[0] == now          # the pass got through the gate and ran
        now = time.time()
        fleetev.INBOX_FLAG_START[0] = now - 5                  # this process's own start: five seconds ago
        check("5 start: inline, a start five seconds ago holds the first pass back (today's rule)", not passes(now))
        sv = spawn("start")                                    # the running server, started an hour ago, in another process
        try:
            check("5 start: a runner that restarts alone (its own start five seconds ago) takes the running server's start, an hour back: the first pass is not delayed again", F.start_read() is not None and now - fleetev.flag_start() > 3000 and passes(now), (fleetev.flag_start(), now))
            fleetev.INBOX_FLAG_START[0] = now - 5
            check("5 start: …whatever its own start says", passes(now))
            put(F.START, json.dumps({"pid": sv.pid, "start": now - 5}))
            check("5 start: …and when the server itself started five seconds ago the delay still holds the pass back", not passes(now))
        finally:
            end_kid(sv)
        put(F.START, json.dumps({"pid": dead_pid(), "start": now - 7200}))
        check("5 start: a start written by a server that is gone says nothing about the one that runs now: the runner's own value stands", fleetev.flag_start() == fleetev.INBOX_FLAG_START[0] and not passes(now), fleetev.flag_start())
    finally:
        _inbox.new_overdue, fleetev.inbox_flag_minutes = real_overdue, real_mins
        fleetev.INBOX_FLAG_START[0], fleetev.INBOX_FLAG_LAST[0] = real_start, real_last

    # ---- 6. a missing, empty, torn or odd file is nothing there
    BAD = ["", "{", '{"pid": 5, "until"', "[1, 2]", "null", '"text"', '{"pid": "x"}', "\u0000\u0000", "{}"]
    odd = []
    runner_svc.RUNNER[:] = []
    for text in BAD + [b"\xff\xfe\x00"]:
        clear_files()
        for name in (F.WAKE, F.HOLD, F.STATUS, F.START):
            if isinstance(text, bytes): MIN.mkdir(parents=True, exist_ok=True); (MIN / name).write_bytes(text)
            else: put(name, text)
        try:
            got = (F.hold_read(), F.status_read(), F.start_read(), W.holding(), W.holder(), runner_svc.status().get("source"), runner_svc.watchdog(), fleetev.flag_start() == fleetev.INBOX_FLAG_START[0])
            if got != (None, None, None, False, "", None, "", True): odd.append((text, got))
            F.wake_stamp()
        except Exception as e:  # noqa: BLE001
            odd.append((text, repr(e)))
    check("6 torn: a file that is empty, cut short, not an object, of the wrong shape or binary reads as nothing in every reader, and none raises", odd == [], odd)
    clear_files()
    check("6 missing: no file: every reader says nothing, `holding` is false and the status is the not-started record", F.wake_stamp() is None and F.hold_read() is None and F.status_read() is None and F.start_read() is None and not W.holding() and runner_svc.status().get("running") is False)
    put(F.WAKE, "")
    check("6 torn: an empty wake file is no line", F.wake_stamp() is None)
    boom = lambda: (_ for _ in ()).throw(OSError("no read"))
    rt, seen_t = small(wake_stamp=boom)
    rt.start()
    try:
        check("6 torn: a wake file that cannot be read is no wake: the loop runs on (one round, and it waits)", eventually(lambda: len(seen_t) == 1, 3.0), seen_t)
        time.sleep(1.5)
        check("6 torn: …and the runner is alive and has not run again", rt.thread.is_alive() and len(seen_t) == 1, seen_t)
    finally:
        rt.stop()
    rm = R.Runner([R.Tick("ev", lambda: None, "settle", "event")], wake_stamp=lambda: None)
    rm._seen = "x"
    check("6 torn: a wake line that goes missing is no wake; one that appears or changes is", rm._file_moved() is False and (setattr(rm, "wake_stamp", lambda: "y") or rm._file_moved()) is True and (setattr(rm, "_seen", "y") or rm._file_moved()) is False)

    # ---- 7. the read-only standby writes none of them
    clear_files(); W.release()
    os.environ["STACKSHOT_READ_ONLY"] = "1"; _ro._reload_for_test()
    try:
        check("7 standby: the read-only mode is on for this check", _ro.is_read_only() is True)
        runner_svc.WAKE_EVENT.clear()
        runner_svc.wake()
        W.hold("demo-pass", 600.0, begin=True)
        held_here, holder_here, event_set = W.holding(), W.holder(), runner_svc.WAKE_EVENT.is_set()
        W.release()
        runner_svc.record_server_start()
        rs = R.Runner([R.Tick("one", lambda: None, "settle")], beat=runner_svc._beat); rs.run_round(event=True)
        F.status_write({"pid": 1}); F.start_write(1.0); F.wake(); F.hold_write("x", 1.0, 2.0)
        check("7 standby: wake, hold (begin and release), the server's start, a runner's beats and the four writers write no file and make no folder", not MIN.exists() and not (T / "state" / "minute").exists(), os.listdir(MIN) if MIN.exists() else None)
        check("7 standby: …while the in-memory wake and hold work as before", held_here and holder_here == "demo-pass" and event_set, (held_here, holder_here, event_set))
    finally:
        os.environ.pop("STACKSHOT_READ_ONLY", None); _ro._reload_for_test(False)
    check("7 standby: back to normal, the writers write again", F.wake() and (MIN / F.WAKE).exists())
finally:
    for k in KIDS:
        if k.poll() is None: k.kill(); k.wait()
        for f in (k.stdin, k.stdout, k.stderr):
            try:
                if f and not f.closed: f.close()
            except OSError: pass

print(f"runner_signals: {len(ran)} checks, {len(fails)} failed")
sys.exit(1 if fails else 0)
