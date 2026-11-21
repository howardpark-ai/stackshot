"""Scenario test for `stackshot minute`, the minute set's runner as a process of its own (stackshot/web/minute.py, `[runner] process`, the runner's lock in core/runner_files.py, service/runner.py `start`, `status`,
`watchdog`): a scratch instance, a throwaway state folder and free ports, real OS processes for the server and for `stackshot minute` (started as `python -m stackshot minute`), no network, no live store.

  1  setting   `[runner] process` defaults to "inline" (absent, and in the example config), "unit" is read, any other value reads as "inline" with a note · it is restart-only: a reload keeps the running value and lists it as pending
  2  lock      `runner.lock` in `<state>/minute/`: taken without waiting, kept for the life of the process, a second take in the process is the same hold · a second process is refused and told the holder's pid · the lock is
               freed by `lock_release` (and the file emptied) and by the holder's death (SIGKILL by its pid) · the read-only standby takes none and writes no file · an unusable lock file is an "error" state, never a raise · close-on-exec
  3  start     the server's start: inline takes the lock BEFORE any thread starts and then starts the runner · a second start in the process reuses it · "unit" starts no runner, takes no lock and says so · inline with the lock held
               by another process starts no runner, says so on one stderr line with the holder's pid, and still starts the publish loop and the watchdog · the setting is read once per start · `_start_background` in the "unit" mode
               starts every other loop · the standby takes no lock
  4  honesty   `status()` says `minute runner not running (...)` when this process has no runner and no live process beats the status file (unit; lock held elsewhere; a dead pid; a stale heartbeat) and says nothing while one does ·
               the watchdog tells the builder once, after the server's own start has had `runner.STALL_AFTER` seconds, naming the cause, and re-arms on a heartbeat
  5  module    `healthz_url`, `server_ready` (200 and `ok` only), `wait_ready` (no look after a stop, a line at the first look) · `run` builds the server's runner (same table, wake file, status file) over the server's wiring, starts
               that one thread and none of the server's, runs none of the start-time passes, and starts nothing when it is stopped before the server is up · the module does not import the server at its top
  6  process   real processes. Refusals leave the instance's folders as they were: the setting inline (exit 3), the standby (4), no config outside the production checkout (2), an unusable lock file (6) · `--help`, and the
               program is listed by `stackshot --help` · a "unit" server alone: no runner, no lock, the status says so · `stackshot minute` against it: it takes the lock, beats the status file the server reads (`source` file,
               `running`), a second one is refused with exit 5 naming the first's pid while the first goes on · a wake written by the server's side ends the child's wait · SIGHUP reloads (and a broken file is kept out) · the
               holder killed by its pid frees the lock and a new one starts and beats · SIGTERM stops it cleanly (exit 0, lock free) · an inline server takes the lock and beats, a `minute` started against it (settings that
               disagree) is refused with exit 5 while the server keeps serving · an inline server that finds the lock held by another process starts, serves and reports the runner as not running with the holder's pid · the child
               started before the server waits (lock taken, no beat), is stopped cleanly while it waits, and beats once the server is up

    tests/run-suite minute        -> exit 0 / 1"""
import contextlib, errno, fcntl, io, json, os, pathlib, re, signal, socket, subprocess, sys, threading, time, urllib.request
import http.server
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
CHILD = len(sys.argv) > 1 and sys.argv[1] == "child"
if CHILD:
    tmp = os.environ["MINUTE_TEST_TMP"]; T = pathlib.Path(tmp)
else:
    tmp = _scratch.mkdtemp(prefix="s3-minute-"); T = pathlib.Path(tmp)
    toml = _instance.apply(_instance.base_toml())
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    for pat, rep in ((r"(?m)^git = true", "git = false"), (r"(?m)^latest_lookups = true", "latest_lookups = false"), (r"(?m)^debounce_seconds = 5", "debounce_seconds = 1"),
                     (r"(?m)^panel = true", "panel = false"), (r"(?m)^every_minutes = 10", "every_minutes = 1440")):      # a server of this suite never reads GitHub, and its timer publish never lands
        toml, n = re.subn(pat, rep, toml); assert n == 1, pat
    BASE = toml
    (T / "stackshot.toml").write_text(BASE, encoding="utf-8")
    for d in ("store/a", "fleet/a", "state", "secrets", "touch", "brain/projects", "home"): (T / d).mkdir(parents=True)
    (T / "store/next-id").write_text("500"); (T / "store/anchors.json").write_text("{}"); (T / "store/projects.json").write_text(json.dumps({"pages": {}})); (T / "RULES.md").write_text("# rules\n", encoding="utf-8")
    (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"})); (T / "fleet/a/sessions.json").write_text("{}")
    os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet", HOME=f"{tmp}/home", MINUTE_TEST_TMP=tmp)
    os.environ.pop("STACKSHOT_URL", None); os.environ.pop("STACKSHOT_READ_ONLY", None)

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""), flush=True)

from stackshot.core import config as _cfg, runner as R, runner_files as F, readonly as _ro      # noqa: E402
MIN = T / "state" / "minute"


# ---------------------------------------------------------------------------- the other process of the lock checks
def child(kind):
    """`lock`: takes the runner's lock, says `ready <pid>`, holds it until a line (or the end) of stdin. `try`: takes it once and says what it got as one JSON line."""
    if kind == "lock":
        got = F.lock_take()
        print(json.dumps({"state": got.state, "pid": os.getpid()}), flush=True)
        sys.stdin.readline()
        return
    if kind == "try":
        got = F.lock_take()
        print(json.dumps({"state": got.state, "pid": got.pid, "why": got.why}), flush=True)
        return
    raise SystemExit(f"no such child {kind}")


if CHILD:
    child(sys.argv[2]); sys.exit(0)

KIDS = []
def spawn_lock():
    pr = subprocess.Popen([sys.executable, os.path.abspath(__file__), "child", "lock"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=STACK); KIDS.append(pr)
    got = json.loads(pr.stdout.readline() or "{}")
    if got.get("state") != "taken": raise RuntimeError(f"the lock child got {got}: {pr.stderr.read()[-400:]}")
    return pr

def try_in_child():
    try: cp = subprocess.run([sys.executable, os.path.abspath(__file__), "child", "try"], capture_output=True, text=True, cwd=STACK, timeout=20)
    except subprocess.TimeoutExpired: return {"error": "the child waited for the lock: it must refuse at once"}      # a lock that blocks instead of refusing fails the checks, never hangs the suite
    return json.loads(cp.stdout.strip().splitlines()[-1]) if cp.stdout.strip() else {"error": cp.stderr[-400:]}

def end_kid(pr, hard=False):
    """Let a holding child go (stdin closed) and wait for it; hard: kill it by its pid (the holder that dies without letting go)."""
    try:
        if hard: pr.kill()
        elif pr.stdin and not pr.stdin.closed: pr.stdin.write("\n"); pr.stdin.flush(); pr.stdin.close()
    except OSError: pass
    try: pr.wait(timeout=20)
    except subprocess.TimeoutExpired: pr.kill(); pr.wait()
    for f in (pr.stdin, pr.stdout, pr.stderr):
        try:
            if f and not f.closed: f.close()
        except OSError: pass

@contextlib.contextmanager
def alarm(secs=15):
    """A call that blocks (a lock taken without LOCK_NB) is ended with TimeoutError after `secs`, so the check fails and the suite goes on."""
    def boom(*_): raise TimeoutError(f"blocked for {secs} s")
    old = signal.signal(signal.SIGALRM, boom); signal.alarm(secs)
    try: yield
    finally: signal.alarm(0); signal.signal(signal.SIGALRM, old)

def eventually(cond, within=5.0, step=0.05):
    end = time.time() + within
    while time.time() < end:
        if cond(): return True
        time.sleep(step)
    return cond()

@contextlib.contextmanager
def stderr_lines():
    buf, real = io.StringIO(), sys.stderr
    sys.stderr = buf
    try: yield buf
    finally: sys.stderr = real

def put(name, text):
    MIN.mkdir(parents=True, exist_ok=True); (MIN / name).write_text(text, encoding="utf-8")

def wipe():
    import shutil
    shutil.rmtree(MIN, ignore_errors=True)

def lock_text():
    try: return (MIN / F.LOCK).read_text(encoding="utf-8")
    except OSError: return None


from stackshot.web import server                          # noqa: E402,F401  (the wiring: hooks, and the routes)
from stackshot.web import minute as M                     # noqa: E402
from stackshot.service import runner as runner_svc, fleet_events as fleetev, wakes as _wakes, migrations as _migrations, stamp as _stamp_svc     # noqa: E402
from stackshot.web import publish as _pubmod, runners as _runners, search as _search     # noqa: E402
from stackshot.router import router_live as _router_live  # noqa: E402
from stackshot.github import ghsync as _gh                # noqa: E402


try:
    # ---- 1. the setting
    import tomllib
    example = tomllib.loads(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
    check("1 setting: the example config has `[runner] process = \"inline\"`", (example.get("runner") or {}).get("process") == "inline", example.get("runner"))
    check("1 setting: the config this suite runs on reads \"inline\" through `runner_process()`", _cfg.get("runner", "process") == "inline" and _cfg.runner_process() == "inline")
    real_runner_cfg = _cfg.CFG.get("runner")
    odd = {}
    for label, val in (("absent", None), ("unit", {"process": "unit"}), ("Unit with spaces", {"process": " Unit "}), ("inline", {"process": "inline"}), ("other word", {"process": "daemon"}), ("empty", {"process": ""}),
                       ("a number", {"process": 3}), ("a list", {"process": ["unit"]}), ("a retired key only", {"enabled": True})):
        if val is None: _cfg.CFG.pop("runner", None)
        else: _cfg.CFG["runner"] = val
        odd[label] = _cfg.runner_process()
    check("1 setting: no key reads \"inline\"; \"unit\" (any case, with spaces) reads \"unit\"; anything else reads \"inline\"",
          odd == {"absent": "inline", "unit": "unit", "Unit with spaces": "unit", "inline": "inline", "other word": "inline", "empty": "inline", "a number": "inline", "a list": "inline", "a retired key only": "inline"}, odd)
    _cfg.CFG["runner"] = {"process": "daemon"}
    n_bad = [n for n in _cfg.notes() if "[runner] process" in n]
    _cfg.CFG["runner"] = {"process": "unit"}; n_ok = [n for n in _cfg.notes() if "[runner] process" in n]
    _cfg.CFG["runner"] = {"process": ""}; n_empty = [n for n in _cfg.notes() if "[runner] process" in n]
    check("1 setting: a value that is neither says so once in config.notes(); \"unit\" says nothing", len(n_bad) == 1 and "'daemon'" in n_bad[0] and "inline" in n_bad[0] and n_ok == [], (n_bad, n_ok, n_empty))
    if real_runner_cfg is None: _cfg.CFG.pop("runner", None)
    else: _cfg.CFG["runner"] = real_runner_cfg
    check("1 setting: it is restart-only: `runner.process` is in RESTART_ONLY", "runner.process" in _cfg.RESTART_ONLY and _cfg._restart_only("runner.process") is not None)
    real_path_text = (T / "stackshot.toml").read_text(encoding="utf-8")
    (T / "stackshot.toml").write_text(re.sub(r'(?m)^process = "inline"', 'process = "unit"', real_path_text, count=1), encoding="utf-8")
    with stderr_lines() as err:
        changed = _cfg.reload()
    check("1 setting: a reload that changes it keeps the running value (\"inline\"), lists it as pending and says it waits for a restart",
          changed == [] and _cfg.runner_process() == "inline" and "runner.process" in _cfg.PENDING and "runner.process changed: takes effect at the next restart" in err.getvalue(), (changed, _cfg.PENDING, err.getvalue()))
    (T / "stackshot.toml").write_text(real_path_text, encoding="utf-8")
    with stderr_lines():
        _cfg.reload()
    check("1 setting: …and back to the file's value nothing is pending", "runner.process" not in _cfg.PENDING and _cfg.runner_process() == "inline", _cfg.PENDING)
    check("1 setting: the configuration reference and the example config say what it does", "`runner.process`" in pathlib.Path(STACK, "docs/configuration.md").read_text(encoding="utf-8")
          and "stackshot minute" in pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))

    # ---- 2. the lock
    wipe()
    got = F.lock_take()
    check("2 lock: taken in a free state folder: state taken, this process's pid, the file `<state>/minute/runner.lock` holds the pid", got.state == "taken" and got.pid == os.getpid() and (lock_text() or "").strip() == str(os.getpid()) and F.lock_held_here(), (got, lock_text()))
    check("2 lock: a second take in the process is the same hold (taken again, one descriptor)", (lambda fd: F.lock_take().state == "taken" and F._LOCK_FD[0] == fd)(F._LOCK_FD[0]))
    check("2 lock: the descriptor is close-on-exec (no child process of the holder keeps the lock after it)", bool(fcntl.fcntl(F._LOCK_FD[0], fcntl.F_GETFD) & fcntl.FD_CLOEXEC))
    r = try_in_child()
    check("2 lock: ANOTHER process is refused without waiting: state held, and it is told the holder's pid", r.get("state") == "held" and r.get("pid") == os.getpid(), r)
    check("2 lock: …a refusal is the lock's own: the holder still holds, its file still names it", F.lock_held_here() and (lock_text() or "").strip() == str(os.getpid()))
    check("2 lock: release lets go: true the first time, false the second; the file is empty and this process no longer holds", F.lock_release() is True and F.lock_release() is False and lock_text() == "" and not F.lock_held_here(), lock_text())
    r = try_in_child()
    check("2 lock: …and another process can take it now", r.get("state") == "taken", r)
    hold = spawn_lock()
    pid_h = hold.pid
    t0 = time.time()
    try:
        with alarm(10): got = F.lock_take()
    except TimeoutError as e: got = F.Lock("error", None, str(e))
    check("2 lock: this process is refused while another holds it, at once (no wait), and told that holder's pid", got.state == "held" and got.pid == pid_h and time.time() - t0 < 2.0 and not F.lock_held_here(), (got, time.time() - t0))
    end_kid(hold, hard=True)
    check("2 lock: the holder was killed by its pid, and the lock is free: its file still names a dead pid, and this process takes it", (lock_text() or "").strip() == str(pid_h) and F.lock_take().state == "taken" and (lock_text() or "").strip() == str(os.getpid()), lock_text())
    F.lock_release()
    wipe(); (T / "state" / "minute").write_text("not a folder", encoding="utf-8")
    got = F.lock_take()
    check("2 lock: a lock file that cannot be had (the folder's place is taken by a file) is state error with the reason, and nothing raises; nothing is held", got.state == "error" and got.why and not F.lock_held_here(), got)
    (T / "state" / "minute").unlink()
    wipe()
    os.environ["STACKSHOT_READ_ONLY"] = "1"; _ro._reload_for_test()
    try:
        got = F.lock_take()
        check("2 lock: the read-only standby takes none: state standby, no file, no folder, nothing held", got.state == "standby" and not MIN.exists() and not F.lock_held_here(), (got, MIN.exists()))
    finally:
        os.environ.pop("STACKSHOT_READ_ONLY", None); _ro._reload_for_test(False)

    # ---- 3. the start of the server's runner
    class FakeThread:
        made: list = []
        def __init__(self, target=None, name=None, daemon=None, args=(), kwargs=None):
            self.target, self.name, self.daemon = target, name, daemon
            FakeThread.made.append(self)
        def start(self): self.started = True
        def is_alive(self): return False
        def join(self, timeout=None): pass
    real_thread = threading.Thread
    real_mode = _cfg.CFG.get("runner")

    def start_with(setting, fn=None):
        """`runner.start()` with every thread faked. → (names, the Runners made, targets started, stderr)."""
        FakeThread.made.clear(); runner_svc.RUNNER[:] = []
        if setting is None: _cfg.CFG.pop("runner", None)
        else: _cfg.CFG["runner"] = {"process": setting}
        threading.Thread = FakeThread
        try:
            with stderr_lines() as err:
                try:
                    with alarm(15): names_ = (fn or runner_svc.start)()
                except TimeoutError: names_ = ["start blocked"]
        finally:
            threading.Thread = real_thread
        return names_, list(runner_svc.RUNNER), [t.target for t in FakeThread.made], err.getvalue()

    wipe(); F.lock_release()
    seen_at_take = []
    real_take = F.lock_take
    def spy_take():
        seen_at_take.append((len(FakeThread.made), len(runner_svc.RUNNER)))      # what exists at the moment the lock is asked for
        return real_take()
    F.lock_take = spy_take
    try:
        names_, rs, targets, err = start_with("inline")
    finally:
        F.lock_take = real_take
    check("3 start inline: the lock is taken BEFORE any thread starts and before the runner is made", seen_at_take == [(0, 0)], seen_at_take)
    check("3 start inline: …then the runner thread, the publish loop and the watchdog start, as before, and this process holds the lock", names_ == ["runner", "publish", "watchdog"] and len(rs) == 1 and rs[0].loop in targets and F.lock_held_here(), (names_, targets))
    check("3 start inline: …the start line is the one it always said, and nothing is said of a lock", "stackshot: minute set: runner (one thread, one lock, paced rounds every 60 s)" in err and "lock" not in err.replace("one lock", ""), err)
    check("3 start inline: …no absence is recorded and the status is the runner's own, from memory", runner_svc.MODE[0] == "inline" and runner_svc.ABSENT[0] == "" and "message" not in runner_svc.status() and "source" not in runner_svc.status())
    first = rs[0]
    names2, rs2, targets2, err2 = start_with("inline", fn=lambda: (runner_svc.RUNNER.append(first), runner_svc.start())[1])
    check("3 start inline: a second start in the same process takes the same hold again (never refused by itself) and reuses its runner", names2[0] == "runner" and len(rs2) == 1 and rs2[0] is first and "not started" not in err2, (names2, err2))
    F.lock_release(); wipe()

    calls = []
    real_rp = _cfg.runner_process
    _cfg.runner_process = lambda: (calls.append(1), real_rp())[1]
    try:
        start_with("inline"); n_inline = len(calls); F.lock_release()
    finally:
        _cfg.runner_process = real_rp
    check("3 start: the setting is read once per start", n_inline == 1, n_inline)
    wipe()

    names_, rs, targets, err = start_with("unit")
    check("3 start unit: no runner thread and no runner made; the publish loop and the watchdog still start", names_ == ["publish", "watchdog"] and rs == [] and not any(getattr(t, "__name__", "") == "loop" for t in targets)
          and runner_svc.publish_loop in targets and runner_svc.watchdog_loop in targets, (names_, rs, targets))
    check("3 start unit: no lock is taken and no file is written; the start says on one line that the runner runs in its own process", not F.lock_held_here() and not MIN.exists() and err.count("\n") == 1
          and 'runner not started here: [runner] process = "unit"' in err and "stackshot minute" in err, (err, MIN.exists()))
    st = runner_svc.status()
    check("3 start unit: the status says `minute runner not running`, names the setting, and reports no runner running", st["running"] is False and str(st.get("message", "")).startswith("minute runner not running (runs in its own process: [runner] process = \"unit\"")
          and runner_svc.MODE[0] == "unit", st.get("message"))

    hold = spawn_lock()
    names_, rs, targets, err = start_with("inline")
    check("3 start, lock held by another process: no runner thread, no runner made, one stderr line with the holder's pid, and the server does not fail", rs == [] and not F.lock_held_here() and err.count("\n") == 1
          and f"runner not started: lock held by pid {hold.pid}" in err and "goes on without one" in err, (err, rs))
    check("3 start, lock held by another process: …the publish loop and the watchdog start all the same", names_ == ["publish", "watchdog"] and runner_svc.publish_loop in targets and runner_svc.watchdog_loop in targets, (names_, targets))
    check("3 start, lock held by another process: …and the status says `minute runner not running (lock held by pid N)`", runner_svc.status().get("message") == f"minute runner not running (lock held by pid {hold.pid})" and runner_svc.status()["running"] is False, runner_svc.status().get("message"))
    end_kid(hold)
    names_, rs, targets, err = start_with("inline")
    check("3 start: once the holder has let go a start takes the lock and runs the runner, and the absence is forgotten", names_[0] == "runner" and len(rs) == 1 and runner_svc.ABSENT[0] == "" and "message" not in runner_svc.status(), (names_, err))
    F.lock_release(); wipe()

    # ---- 3b. the start's other branches: a real STARTED time, an unusable lock file, the pid the lock names, and the retry of a server that found the lock held
    sent3 = []; real_send3 = fleetev.inbox_flag_send; fleetev.inbox_flag_send = lambda to, text: sent3.append((to, text))
    real_aud3 = dict(_cfg.CFG.get("audit") or {}); _cfg.CFG["audit"] = {**real_aud3, "builder": "demo-builder"}
    try:
        t_a = time.time(); start_with("unit"); t_b = time.time()
        started_at = runner_svc.STARTED[0]
        w3 = runner_svc.watchdog()
    finally:
        fleetev.inbox_flag_send = real_send3; _cfg.CFG["audit"] = real_aud3
    check("3 start: STARTED is the wall clock of the start (a real time: the watchdog's startup grace counts from it)", started_at is not None and t_a <= started_at <= t_b, (t_a, started_at, t_b))
    check("3 start: …so a watchdog look just after a start tells the builder nothing (the grace of the start has not run out)", w3 == "" and sent3 == [], (w3, sent3))
    wipe()

    def unusable(label, make):
        wipe(); make()
        names_u, rs_u, targets_u, err_u = start_with("inline")
        check(f"3 start inline, lock UNUSABLE ({label}): the runner still starts, without the lock, and says so; the server does not wait for a lock it cannot have",
              names_u[:1] == ["runner"] and len(rs_u) == 1 and rs_u[0].loop in targets_u and not F.lock_held_here() and runner_svc.WAITING[0] is False
              and "the runner lock was not had" in err_u and "starts without it" in err_u and "message" not in runner_svc.status(), (names_u, err_u))
        F.lock_release(); wipe()
    unusable("the minute folder's place is a file", lambda: (T / "state" / "minute").write_text("not a folder", encoding="utf-8"))
    (T / "state" / "minute").unlink()
    unusable("a directory in the lock file's place", lambda: ((MIN.mkdir(parents=True, exist_ok=True)), (MIN / F.LOCK).mkdir()))
    if os.geteuid() != 0:
        def ro_dir():
            MIN.mkdir(parents=True, exist_ok=True); os.chmod(MIN, 0o555)
        try: unusable("a folder that cannot be written to", ro_dir)
        finally:
            try: os.chmod(MIN, 0o755)
            except OSError: pass
            wipe()

    hold = spawn_lock()
    dead3 = subprocess.Popen([sys.executable, "-c", "pass"]); dead3.wait()
    (MIN / F.LOCK).write_text(f"{dead3.pid}\n", encoding="utf-8")        # the lock is still the holder's (a flock); the file now names a process that is gone
    got = F.lock_take()
    check("2 lock: the pid a refusal names is a LIVE one: a file that names a process that is gone gives state held with no pid, never the dead pid", got.state == "held" and got.pid is None, got)
    check("2 lock: …`lock_holder()` is the same look without taking the lock: nobody for a dead pid, the holder when the file names it, nobody for this process's own pid",
          F.lock_holder() is None and ((MIN / F.LOCK).write_text(f"{hold.pid}\n", encoding="utf-8") or F.lock_holder() == hold.pid) and ((MIN / F.LOCK).write_text(f"{os.getpid()}\n", encoding="utf-8") or F.lock_holder() is None))
    end_kid(hold); wipe()
    check("2 lock: …and no file at all names nobody", F.lock_holder() is None)

    hold = spawn_lock()
    start_with("inline")
    msg_held = runner_svc.status().get("message")
    check("3 retry: while the holder lives a look takes nothing: `held`, no runner, and the status names that holder", runner_svc.WAITING[0] is True and runner_svc.retry_lock() == "held" and runner_svc.RUNNER == []
          and msg_held == f"minute runner not running (lock held by pid {hold.pid})", (msg_held, runner_svc.RUNNER))
    end_kid(hold, hard=True)
    msg_free = runner_svc.status().get("message", "")
    check("3 retry: the holder is gone (killed by its pid) and its pid is still in the file: the status no longer names it, it says the lock is free", str(hold.pid) not in msg_free and "the lock is free" in msg_free and runner_svc.RUNNER == [], msg_free)
    FakeThread.made.clear(); threading.Thread = FakeThread
    try:
        with stderr_lines() as err_r:
            r1 = runner_svc.retry_lock(); r2 = runner_svc.retry_lock()
    finally:
        threading.Thread = real_thread
    loops_started = [t for t in FakeThread.made if runner_svc.RUNNER and t.target == runner_svc.RUNNER[0].loop]
    check("3 retry: the next look takes the lock and starts the runner by the start's path: `started`, one Runner, its thread started once, this process holds the lock, and the log says so",
          r1 == "started" and len(runner_svc.RUNNER) == 1 and len(loops_started) == 1 and F.lock_held_here() and "the runner lock is free now; this server took it and starts the runner" in err_r.getvalue()
          and "minute set: runner (one thread, one lock" in err_r.getvalue(), (r1, err_r.getvalue()))
    check("3 retry: …a second look starts nothing more (one start, never two): empty, still one thread", r2 == "" and len(loops_started) == 1 and err_r.getvalue().count("runner lock is free now") == 1, (r2, len(loops_started)))
    check("3 retry: …and the `not running` message is gone", runner_svc.WAITING[0] is False and runner_svc.absent() == "" and "message" not in runner_svc.status(), runner_svc.status())
    F.lock_release(); runner_svc.RUNNER[:] = []; wipe()
    start_with("unit")
    check("3 retry: a \"unit\" server never retries and takes no lock: empty, no lock file", runner_svc.retry_lock() == "" and not (MIN / F.LOCK).exists() and not F.lock_held_here(), os.listdir(MIN) if MIN.exists() else None)
    wipe()

    # the watchdog's own loop makes the retry (no new thread): a holder that lets go is followed by a runner within the loop's next look
    hold = spawn_lock()
    start_with("inline")
    real_make3 = runner_svc.make
    small3 = R.Runner([R.Tick("ev", lambda: None, "settle", "event")], wake_wait=lambda: 60.0)
    runner_svc.make = lambda: small3
    stopw3 = threading.Event(); lt3 = threading.Thread(target=runner_svc.watchdog_loop, args=(stopw3, 0.1)); lt3.start()
    try:
        time.sleep(0.6)
        held_ok = runner_svc.RUNNER == [] and not F.lock_held_here()
        end_kid(hold)
        came = eventually(lambda: runner_svc.RUNNER == [small3] and small3.thread is not None, 6.0)
        check("3 retry: the watchdog's loop retries by itself: nothing while the holder lives, and the runner starts within its next looks once the holder lets go", held_ok and came and F.lock_held_here(), (held_ok, came))
    finally:
        stopw3.set(); lt3.join(10); small3.stop(5.0); runner_svc.make = real_make3
        runner_svc.RUNNER[:] = []; F.lock_release(); wipe()

    # the whole server start in the "unit" mode (the start-time passes and the other loops are the server's)
    real_runners = (_runners.PERSIST, _runners.AUTOSTART, _runners.ON_CHANGE, _runners.restore)
    _runners.restore = lambda: None
    try:
        names_, rs, targets, err = start_with("unit", fn=server._start_background)
    finally:
        _runners.PERSIST, _runners.AUTOSTART, _runners.ON_CHANGE, _runners.restore = real_runners
    check("3 server unit: `_start_background` returns the other loops and no runner: publish, watchdog, router, search, the mirror's worker and comments", names_ == ["publish", "watchdog", "router", "search", "ghsync-worker", "ghsync-comments"]
          and rs == [] and all(f in targets for f in (runner_svc.publish_loop, runner_svc.watchdog_loop, _router_live.loop, _search.loop, _gh.worker_loop, _gh.comments_loop)), (names_, [getattr(t, "__name__", t) for t in targets]))
    check("3 server unit: …no lock file was made", not (MIN / F.LOCK).exists(), os.listdir(MIN) if MIN.exists() else None)
    os.environ["STACKSHOT_READ_ONLY"] = "1"; _ro._reload_for_test()
    try:
        wipe(); FakeThread.made.clear()
        threading.Thread = FakeThread
        try:
            with stderr_lines():
                names_ = server._start_background()
        finally:
            threading.Thread = real_thread
        check("3 server standby: `_start_background` starts nothing and takes no lock", names_ == [] and not FakeThread.made and not MIN.exists() and not F.lock_held_here(), (names_, MIN.exists()))
    finally:
        os.environ.pop("STACKSHOT_READ_ONLY", None); _ro._reload_for_test(False)
    if real_mode is None: _cfg.CFG.pop("runner", None)
    else: _cfg.CFG["runner"] = real_mode
    runner_svc.RUNNER[:] = []; runner_svc.MODE[0] = ""; runner_svc.ABSENT[0] = ""; runner_svc.STARTED[0] = None; runner_svc.WAITING[0] = False

    # ---- 4. the status and the watchdog when this process has no runner
    sent = []
    real_send, real_audit = fleetev.inbox_flag_send, dict(_cfg.CFG.get("audit") or {})
    fleetev.inbox_flag_send = lambda to, text: sent.append((to, text))
    _cfg.CFG["audit"] = {**real_audit, "builder": "demo-builder"}
    runner_svc.RUNNER[:] = []; runner_svc.RUNNER_STALL[0] = False
    wk = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"]); KIDS.append(wk)
    def snap_of(pid, hb_age, round_age, current="demo_tick"):
        now = time.time()
        return {"pid": pid, "heartbeat": now - hb_age, "last_round": None if round_age is None else now - round_age, "started": now - 5000, "current": current, "rounds": 7, "ticks": [], "enabled": True, "mode": "runner"}
    try:
        wipe()
        runner_svc.ABSENT[0], runner_svc.STARTED[0] = "", None
        check("4 honesty: a process that never started a runner of its own and finds no file says nothing and has no message (as before)", runner_svc.watchdog() == "" and sent == [] and "message" not in runner_svc.status())
        runner_svc.ABSENT[0], runner_svc.STARTED[0] = 'runs in its own process: [runner] process = "unit"; start `stackshot minute`', time.time() - 10
        check("4 honesty: a \"unit\" server just started, no file yet: the status says not running with the reason; the watchdog gives the child its time to start", str(runner_svc.status().get("message", "")).startswith("minute runner not running (runs in its own process") and runner_svc.watchdog() == "" and sent == [])
        runner_svc.STARTED[0] = time.time() - 400
        with stderr_lines() as err:
            r1 = runner_svc.watchdog()
        check("4 honesty: …past that time with no process having reported, the stall report goes once to the builder naming the cause (no process has reported since this server started), with a stderr line and nothing owed",
              r1 == "told" and len(sent) == 1 and sent[0][0] == "demo-builder" and "no process has reported since this server started" in sent[0][1] and "minute runner is not running" in sent[0][1] and "no reply is owed" in sent[0][1]
              and "stuck in the tick" not in sent[0][1] and err.getvalue().count("stalled") == 1, (r1, sent, err.getvalue()))
        check("4 honesty: …a second look sends and logs nothing more", runner_svc.watchdog() == "noted" and len(sent) == 1)
        put(F.STATUS, json.dumps(snap_of(wk.pid, 5, 5)))
        st = runner_svc.status()
        check("4 honesty: a live process that beats the file is the runner: running, source file, and no `minute runner not running` message", st["running"] is True and st["source"] == "file" and st["pid"] == wk.pid and "message" not in st, st)
        check("4 honesty: …and its fresh heartbeat re-arms the watchdog", runner_svc.watchdog() == "" and runner_svc.RUNNER_STALL[0] is False and len(sent) == 1)
        put(F.STATUS, json.dumps(snap_of(wk.pid, 420, 420)))
        runner_svc.STARTED[0] = time.time() - 400
        st = runner_svc.status()
        check("4 honesty: a stale heartbeat reads not running and the message gives the age of the last heartbeat", st["running"] is False and "minute runner not running" in str(st.get("message", "")) and "its last heartbeat was 4" in st.get("message", ""), st.get("message"))
        check("4 honesty: …and the watchdog tells the builder the stall as a stalled runner (the tick it was in), once", runner_svc.watchdog() == "told" and len(sent) == 2 and "stuck in the tick demo_tick" in sent[1][1], sent[-1])
        put(F.STATUS, json.dumps(snap_of(wk.pid, 5, 5))); runner_svc.watchdog()
        dead = subprocess.Popen([sys.executable, "-c", "pass"]); dead.wait()
        put(F.STATUS, json.dumps(snap_of(dead.pid, 2, 2)))
        check("4 honesty: a fresh heartbeat of a pid that is gone is not running, and the message says that pid is gone", runner_svc.status()["running"] is False and f"pid {dead.pid} is gone" in str(runner_svc.status().get("message", "")), runner_svc.status().get("message"))
        put(F.STATUS, json.dumps(snap_of(dead.pid, 900, 900)))
        runner_svc.STARTED[0] = time.time() - 20
        sent.clear(); runner_svc.RUNNER_STALL[0] = False
        check("4 honesty: a file the last runner left, seen by a server that has just started, is no stall yet (the new child may still be coming up)", runner_svc.watchdog() == "" and sent == [])
        runner_svc.STARTED[0] = time.time() - 400
        check("4 honesty: …a minute later it is, and the message says its process is gone", runner_svc.watchdog() == "told" and "its process is gone" in sent[0][1], sent)
        wipe()
        runner_svc.ABSENT[0], runner_svc.STARTED[0], runner_svc.RUNNER_STALL[0] = f"lock held by pid {wk.pid}", time.time() - 400, False
        sent.clear()
        check("4 honesty: an inline server that found the lock held, and sees no heartbeat at all, reports it the same way, with the reason", runner_svc.watchdog() == "told" and f"lock held by pid {wk.pid}" in sent[0][1], sent)
    finally:
        fleetev.inbox_flag_send = real_send; _cfg.CFG["audit"] = real_audit
        runner_svc.ABSENT[0], runner_svc.STARTED[0], runner_svc.RUNNER_STALL[0] = "", None, False
        wk.kill(); wk.wait()
        wipe()

    # ---- 5. the module
    class Health(http.server.BaseHTTPRequestHandler):
        answer = (200, b"ok\n")
        def do_GET(self):
            code, body = Health.answer
            self.send_response(code); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def log_message(self, *a): pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Health); hp = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True); th.start()
    try:
        url = f"http://127.0.0.1:{hp}/healthz"
        check("5 module: `server_ready` is true for 200 and a body that starts with `ok` (the second line of a standby's body is fine)", M.server_ready(url) and (setattr(Health, "answer", (200, b"ok\nread-only: yes; data age: 3s")) or M.server_ready(url)))
        Health.answer = (503, b"ok\n"); a503 = M.server_ready(url)
        Health.answer = (200, b"starting\n"); anok = M.server_ready(url)
        Health.answer = (200, b""); aempty = M.server_ready(url)
        check("5 module: …false for 503, for a 200 that is not `ok`, for an empty body, for a refused connection and for a timeout, and never raises", not a503 and not anok and not aempty and M.server_ready("http://127.0.0.1:1/healthz", 1.0) is False
              and M.server_ready("not a url") is False, (a503, anok, aempty))
        Health.answer = (200, b"ok\n")
        said = []; stop = threading.Event(); stop.set()
        looks = []
        real_ready = M.server_ready
        M.server_ready = lambda u, timeout=M.READY_TIMEOUT: (looks.append(u), real_ready(u, timeout))[1]
        try:
            res = M.wait_ready(stop, url, 0.05, said.append)
            check("5 module: `wait_ready` with the stop already set makes no look and says False", res is False and looks == [] and said == [], (res, looks, said))
            stop2 = threading.Event(); Health.answer = (503, b"no")
            flip = threading.Timer(0.6, lambda: setattr(Health, "answer", (200, b"ok\n"))); flip.start()
            t0 = time.time(); said = []; res = M.wait_ready(stop2, url, 0.05, said.append, every=30.0); flip.join()
            check("5 module: …it waits while the server is not up (looks again and again), returns True when it answers, and says one waiting line, not one per look", res is True and time.time() - t0 >= 0.5 and len(looks) >= 5 and len(said) == 1 and url in said[0], (res, len(looks), said))
            stop3 = threading.Event(); Health.answer = (503, b"no"); threading.Timer(0.4, stop3.set).start(); said = []
            check("5 module: …a stop during the wait ends it with False", M.wait_ready(stop3, url, 0.05, said.append) is False)
        finally:
            M.server_ready = real_ready
    finally:
        srv.shutdown(); srv.server_close()
    cases = {("127.0.0.1", 8020): "http://127.0.0.1:8020/healthz", ("0.0.0.0", 9): "http://127.0.0.1:9/healthz", ("::", 9): "http://[::1]:9/healthz", ("::1", 9): "http://[::1]:9/healthz", ("myhost", 7): "http://myhost:7/healthz"}
    real_srv = dict(_cfg.CFG["server"]); got_urls = {}
    for (h, p), want in cases.items():
        _cfg.CFG["server"] = {**real_srv, "host": h, "port": p}; got_urls[(h, p)] = M.healthz_url()
    _cfg.CFG["server"] = real_srv
    check("5 module: `healthz_url` is the server's own host and port (a wildcard host through the loopback address)", got_urls == cases, got_urls)

    import ast
    top = [n for n in ast.parse(pathlib.Path(STACK, "stackshot/web/minute.py").read_text(encoding="utf-8")).body if isinstance(n, (ast.Import, ast.ImportFrom))]
    top_mods = sorted({(n.module or "") if isinstance(n, ast.ImportFrom) else a.name for n in top for a in (n.names if isinstance(n, ast.Import) else [None])})
    check("5 module: the module's top-level imports are the standard library, paths and core only: the server is imported inside `run`, after the refusals, so a refused start touches nothing", all(not m.startswith("stackshot") or m.startswith(("stackshot.core", "stackshot.paths", "stackshot")) and "web" not in m and "service" not in m for m in top_mods)
          and not any("server" in m for m in top_mods), top_mods)

    # `run` with the threads faked: what it starts and what it does not
    starts = []
    spied = []
    for mod, name in ((_migrations, "migrate_holds"), (_migrations, "migrate_needs"), (_migrations, "_session_ids_pass"), (_migrations, "_mover_backfill_pass"), (_migrations, "_close_marks_pass"), (_migrations, "_retire_rank_pass"),
                        (_wakes, "wake_pass"), (_stamp_svc, "_phase_tick"), (_pubmod, "_publish"), (runner_svc, "record_server_start")):
        spied.append((mod, name, getattr(mod, name))); setattr(mod, name, (lambda n: lambda *a, **k: starts.append(n))(name))
    real_wait = M.wait_ready
    try:
        runner_svc.RUNNER[:] = []; FakeThread.made.clear(); threading.Thread = FakeThread
        stop, hup = threading.Event(), threading.Event(); stop.set()
        M.wait_ready = lambda *a, **k: True
        with stderr_lines() as err:
            rc = M.run(stop, hup, 0.01, 1.0)
        threading.Thread = real_thread
        rn = runner_svc.RUNNER[0] if runner_svc.RUNNER else None
        check("5 run: with the server up it builds the server's runner (the same table, the wake file, the status file, the wake event) and starts that one thread and no other", rc == 0 and rn is not None and [t.name for t in rn.ticks] == [t.name for t in runner_svc.ticks()]
              and rn.wake_stamp is F.wake_stamp and rn.beat is runner_svc._beat and [t.target for t in FakeThread.made] == [rn.loop] and FakeThread.made[0].name == "runner", (rc, [t.target for t in FakeThread.made]))
        check("5 run: …none of the server's other threads (publish, watchdog, router, search, the mirror) starts and none of the start-time passes runs", starts == [] and runner_svc.publish_loop not in [t.target for t in FakeThread.made], starts)
        check("5 run: …the hook tables are installed (the server's wiring was imported as a module: nothing started by it)", runner_svc._hooks_ is not None and "stackshot.web.server" in sys.modules and sys.modules["stackshot.web.server"].__name__ == "stackshot.web.server")
        check("5 run: …it says it runs and that it stopped, and a stop ends it with 0", "stackshot minute: runner (pid" in err.getvalue() and "stackshot minute: stopped" in err.getvalue())
        stop_late = threading.Event(); guard = threading.Timer(4.0, stop_late.set); guard.start()      # a run that ignores the readiness wait would loop until stopped: the suite fails it, never hangs on it
        runner_svc.RUNNER[:] = []; FakeThread.made.clear(); threading.Thread = FakeThread
        M.wait_ready = lambda *a, **k: False
        try:
            with stderr_lines() as err:
                rc = M.run(stop_late, threading.Event(), 0.01, 1.0)
        finally:
            guard.cancel()
        threading.Thread = real_thread
        check("5 run: stopped before the server is up: no runner is made, no thread starts, exit 0 and one line says so", rc == 0 and not runner_svc.RUNNER and not FakeThread.made and "stopped before the server was up" in err.getvalue(), (rc, err.getvalue()))
    finally:
        threading.Thread = real_thread; M.wait_ready = real_wait
        for mod, name, fn in spied: setattr(mod, name, fn)
        runner_svc.RUNNER[:] = []
    # a runner whose tick never ends: the stop waits `stop_wait` for it, then abandons it and says so, never forever
    gate = threading.Event()
    stuck = R.Runner([R.Tick("stuck", lambda: gate.wait(60), "settle", "event")], wake_wait=lambda: 60.0)
    runner_svc.RUNNER[:] = [stuck]
    stop_s = threading.Event(); real_wait5 = M.wait_ready; M.wait_ready = lambda *a, **k: True
    tm = threading.Timer(1.5, stop_s.set); tm.start(); t0s = time.time(); rc_s = None; err_s = ""
    try:
        with stderr_lines() as err:
            try:
                with alarm(25): rc_s = M.run(stop_s, threading.Event(), 0.01, 1.0)
            except TimeoutError: rc_s = "blocked: the stop waited for a tick that never ends"
        err_s = err.getvalue()
    finally:
        tm.cancel(); gate.set(); M.wait_ready = real_wait5; stuck.stop(5.0); runner_svc.RUNNER[:] = []
    check("5 run: a tick that never ends: the stop waits `stop_wait` (1 s) for it, then abandons it and says so, exit 0, and never waits forever", rc_s == 0 and "abandoned" in err_s and time.time() - t0s < 12, (rc_s, err_s[-300:], time.time() - t0s))
    reloads = []
    real_reload = _cfg.reload
    _cfg.reload = lambda: (reloads.append(1), None)[1]
    try:
        with stderr_lines() as err: M.reload_config()
    finally:
        _cfg.reload = real_reload
    check("5 module: `reload_config` re-reads the config and says when it failed (nothing changed)", reloads == [1] and "config reload: failed, nothing changed" in err.getvalue(), err.getvalue())
    real_reload = _cfg.reload
    _cfg.reload = lambda: ["pages.flavor"]
    try:
        with stderr_lines() as err: M.reload_config()
    finally:
        _cfg.reload = real_reload
    check("5 module: …and which live settings changed when it worked", "config reload: pages.flavor" in err.getvalue(), err.getvalue())

    # ---- 6. real processes
    def free_port():
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0)); return s.getsockname()[1]
    def conf(process, port, name=None):
        """A config file over this suite's state folder with its own `[runner] process` and server port."""
        c = BASE
        for pat, rep in ((r'(?m)^process = "inline"', f'process = "{process}"'), (r"(?m)^port = 8020", f"port = {port}")):
            c, n = re.subn(pat, rep, c, count=1); assert n == 1, pat
        p = T / (name or f"conf-{process}-{port}.toml"); p.write_text(c, encoding="utf-8"); return p
    PROCS = []; ERRS = {}
    def env_of(cf, **extra):
        e = {**os.environ, "STACKSHOT_CONFIG": str(cf), "STACKSHOT_AUTH": "off", "STACKSHOT_FLEET_DIR": f"{tmp}/fleet", "HOME": f"{tmp}/home", "PYTHONUNBUFFERED": "1"}
        e.pop("STACKSHOT_READ_ONLY", None); e.update(extra); return e
    def launch(args, cf, label, **extra):
        ef = open(T / f"{label}.err", "w+"); ERRS[label] = ef
        pr = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=ef, cwd=STACK, env=env_of(cf, **extra)); PROCS.append(pr); pr.label = label; return pr
    def server_proc(cf, label): return launch([sys.executable, os.path.join(STACK, "stackshot/web/server.py")], cf, label)
    def minute_proc(cf, label, *args, **extra): return launch([sys.executable, "-m", "stackshot", "minute", *args], cf, label, **extra)
    def err_of(label):
        ef = ERRS[label]; ef.seek(0); return ef.read()
    def up(port, pr, timeout=90.0):
        end = time.time() + timeout
        while time.time() < end:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as r:
                    if r.status == 200: return True
            except Exception:
                if pr.poll() is not None: return False
                time.sleep(0.3)
        return False
    def status_of(port):
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/audit/status", timeout=20) as r:
            return json.loads(r.read().decode("utf-8")).get("runner") or {}
    def beat():
        try: return json.loads((MIN / F.STATUS).read_text(encoding="utf-8"))
        except (OSError, ValueError): return None
    def beats_by(pid, within=60.0):
        return eventually(lambda: (beat() or {}).get("pid") == pid, within, 0.2)
    def stop_proc(pr, sig=signal.SIGTERM, wait=30.0):
        if pr.poll() is None:
            pr.send_signal(sig)
            try: pr.wait(wait)
            except subprocess.TimeoutExpired: pr.kill(); pr.wait()
        return pr.returncode
    def tree(root):
        return sorted(str(p.relative_to(root)) for p in pathlib.Path(root).rglob("*")) if pathlib.Path(root).exists() else None

    try:
        # -- refusals leave the instance as it was: a fixture root of its own (no store, no state: a start that reached the store would make them)
        FX = T / "fx"; FX.mkdir()
        fx_conf = BASE
        for key in ("repo", "store", "markdown", "brain", "state", "secrets", "project_touch", "rules"):
            fx_conf = re.sub(rf'(?m)^{key} = "[^"]*"', f'{key} = "{FX}/{key}"', fx_conf, count=1)
        (FX / "fx.toml").write_text(re.sub(r'(?m)^process = "inline"', 'process = "unit"', fx_conf, count=1), encoding="utf-8")
        (FX / "fx-inline.toml").write_text(fx_conf, encoding="utf-8")
        before = tree(FX)
        mp = minute_proc(FX / "fx-inline.toml", "refuse-inline"); rc = mp.wait(60)
        e = err_of("refuse-inline")
        check("6 refuse: the setting is \"inline\": exit 3, one line saying the server runs the runner, nothing written or made, no traceback", rc == 3 and e.count("\n") == 1 and 'is "inline"' in e and "server runs the minute set's runner itself" in e and "Traceback" not in e and tree(FX) == before, (rc, e[-400:], tree(FX)))
        for bad, opt in (("0", "--ready-poll"), ("-1", "--ready-poll"), ("nan", "--ready-poll"), ("-1", "--stop-wait")):
            mp = minute_proc(FX / "fx.toml", f"bad-{opt}-{bad}", opt, bad)
            try: rc = mp.wait(30)
            except subprocess.TimeoutExpired: mp.kill(); rc = mp.wait(30)
            e = err_of(f"bad-{opt}-{bad}")
            check(f"6 refuse: `{opt} {bad}` is refused with exit 1 and one line naming the option (it is not clamped, and nothing is started, locked or written)", rc == 1 and e.count("\n") == 1 and opt in e and "Traceback" not in e and tree(FX) == before, (rc, e[-300:], tree(FX)))
        mp = minute_proc(FX / "fx.toml", "refuse-standby", STACKSHOT_READ_ONLY="1"); rc = mp.wait(60)
        e = err_of("refuse-standby")
        check("6 refuse: a read-only standby: exit 4, one line, nothing written or made", rc == 4 and e.count("\n") == 1 and "read-only standby" in e and "Traceback" not in e and tree(FX) == before, (rc, e[-400:], tree(FX)))
        env_d = {k: v for k, v in env_of(FX / "fx.toml").items() if k not in ("STACKSHOT_CONFIG", "BOARD_MCP_CONFIG")}
        ef = open(T / "refuse-conf.err", "w+"); ERRS["refuse-conf"] = ef
        mp = subprocess.Popen([sys.executable, "-m", "stackshot", "minute"], stdout=subprocess.DEVNULL, stderr=ef, cwd=STACK, env=env_d); PROCS.append(mp); rc = mp.wait(60)
        e = err_of("refuse-conf")
        check("6 refuse: no config named and this checkout is not the production one: exit 2, one line, nothing touched", rc == 2 and "STACKSHOT_CONFIG is unset" in e and "nothing was touched" in e and "Traceback" not in e and tree(FX) == before, (rc, e[-400:]))
        (FX / "state").mkdir(); (FX / "state" / "minute").write_text("a file where the folder goes")
        mp = minute_proc(FX / "fx.toml", "refuse-lockerr"); rc = mp.wait(60)
        e = err_of("refuse-lockerr")
        check("6 refuse: a lock file that cannot be had: exit 6, one line with the reason, no traceback", rc == 6 and e.count("\n") == 1 and "could not be had" in e and "Traceback" not in e, (rc, e[-400:]))
        mp = minute_proc(FX / "fx.toml", "help", "--help"); rc = mp.wait(60); e = err_of("help")
        helpout = subprocess.run([sys.executable, "-m", "stackshot", "minute", "--help"], capture_output=True, text=True, cwd=STACK, timeout=60, env=env_of(FX / "fx.toml"))
        cp = subprocess.run([sys.executable, "-m", "stackshot", "--help"], capture_output=True, text=True, cwd=STACK, timeout=60, env=env_of(FX / "fx.toml"))
        check("6 cli: `stackshot minute --help` prints its usage under that name and exits 0; `stackshot --help` lists the program", rc == 0 and helpout.returncode == 0 and "usage: stackshot minute" in helpout.stdout and "--stop-wait" in helpout.stdout, (rc, helpout.stdout[-300:], helpout.stderr[-300:]))
        check("6 cli: …`stackshot --help` lists `minute` with its description", cp.returncode == 0 and re.search(r"(?m)^  minute\s+the minute set's runner", cp.stdout) is not None, cp.stdout[-600:])

        # -- a "unit" server alone
        P1 = free_port(); cu = conf("unit", P1); ci = conf("inline", P1)
        wipe()
        sv = server_proc(cu, "srv-unit")
        check("6 unit server: comes up and answers /healthz", up(P1, sv), err_of("srv-unit")[-800:])
        st = status_of(P1)
        check("6 unit server: /audit/status reports `minute runner not running (...)` with the reason and running false", st.get("running") is False and str(st.get("message", "")).startswith("minute runner not running (runs in its own process"), st)
        check("6 unit server: no lock file and no status file: the server runs no runner and beats nothing", not (MIN / F.LOCK).exists() and not (MIN / F.STATUS).exists(), os.listdir(MIN) if MIN.exists() else None)
        e = err_of("srv-unit")
        check("6 unit server: its start line says the runner is not started here, and no runner line", 'runner not started here: [runner] process = "unit"' in e and "minute set: runner (one thread" not in e and "Traceback" not in e, e[-800:])

        # -- the process against it
        m1 = minute_proc(cu, "min1")
        check("6 minute: with the server up it takes the lock and beats the status file as its own (pid, a heartbeat of this minute)", beats_by(m1.pid) and abs(time.time() - beat()["heartbeat"]) < 30 and (lock_text() or "").strip() == str(m1.pid), (err_of("min1")[-800:], beat(), lock_text()))
        eventually(lambda: (beat() or {}).get("rounds", 0) >= 1, 30.0, 0.2)       # the first beat is the round's start: its first round's ticks have run once the count is 1
        b = beat()
        check("6 minute: …the record has the server's table (every tick of the minute set) and its event ticks have run without error (the hook tables are in place)", [t["name"] for t in b["ticks"]] == [t.name for t in runner_svc.ticks()]
              and all(t["runs"] >= 1 and t["last_error"] is None for t in b["ticks"] if t["name"] in ("wake_pass", "anchor_pass")), b["ticks"][:2])
        ok_st = eventually(lambda: status_of(P1).get("running") is True, 10)
        st = status_of(P1)
        check("6 minute: the server reads it: /audit/status has source file, the child's pid, running true and no `minute runner not running` message", ok_st and st.get("source") == "file" and st.get("pid") == m1.pid and "message" not in st, st)
        e1 = err_of("min1")
        check("6 minute: it said it ran (one runner line) and waited for nobody (the server was up): no waiting line, no traceback", "stackshot minute: runner (pid" in e1 and "waiting for the server" not in e1 and "Traceback" not in e1, e1[-600:])
        m2 = minute_proc(cu, "min2"); rc = m2.wait(120); e2 = err_of("min2")
        check("6 minute: a second one is refused: exit 5, one line naming the first's pid, no traceback", rc == 5 and e2.count("\n") == 1 and f"held by pid {m1.pid}" in e2 and "exactly one process runs the runner" in e2 and "Traceback" not in e2, (rc, e2[-500:]))
        time.sleep(1.5)
        hb_moves = time.time() - beat()["heartbeat"] < R.STALL_AFTER
        check("6 minute: …the first goes on (its pid still holds the lock and its heartbeat is current) and the server still serves", m1.poll() is None and (lock_text() or "").strip() == str(m1.pid) and beat()["pid"] == m1.pid and hb_moves and up(P1, sv, 5),
              (m1.poll(), lock_text(), beat(), hb_moves, err_of("min1")[-300:]))
        r0 = beat()["rounds"]
        F.wake()
        check("6 minute: a wake written on the server's side (the wake file) ends the child's wait: another round within seconds, though the pace is a minute", eventually(lambda: beat()["rounds"] > r0, 8.0, 0.2), (r0, beat()["rounds"]))
        # SIGHUP
        base_c = cu.read_text(encoding="utf-8")
        cu.write_text(re.sub(r'(?m)^flavor = "plain"', 'flavor = "gbrain"', base_c, count=1), encoding="utf-8"); m1.send_signal(signal.SIGHUP)
        check("6 minute SIGHUP: the config is re-read: the changed live setting is logged, the process is the same and still beats", eventually(lambda: "config reload: pages.flavor" in err_of("min1"), 20.0) and m1.poll() is None, err_of("min1")[-500:])
        cu.write_text(base_c.replace("[server]", "[server", 1), encoding="utf-8"); m1.send_signal(signal.SIGHUP)
        check("6 minute SIGHUP: a broken file is logged and the running config kept; the process goes on", eventually(lambda: "config reload: failed, nothing changed" in err_of("min1"), 20.0) and m1.poll() is None)
        cu.write_text(base_c, encoding="utf-8"); m1.send_signal(signal.SIGHUP)
        eventually(lambda: err_of("min1").count("config reload:") >= 5, 10.0)
        # the holder dies
        pid1 = m1.pid; m1.kill(); m1.wait(30)
        check("6 minute: the holder killed by its pid leaves its pid in the file and no lock: the server shows the runner not running with that pid gone", (lock_text() or "").strip() == str(pid1) and eventually(lambda: status_of(P1).get("running") is False, 10.0)
              and f"pid {pid1} is gone" in status_of(P1).get("message", ""), (lock_text(), status_of(P1)))
        m3 = minute_proc(cu, "min3")
        check("6 minute: …and a new one starts at once: it takes the lock and beats", beats_by(m3.pid) and (lock_text() or "").strip() == str(m3.pid), (err_of("min3")[-600:], lock_text()))
        check("6 minute: …and the server reads it again: running true, the new pid", eventually(lambda: status_of(P1).get("running") is True and status_of(P1).get("pid") == m3.pid, 10.0), status_of(P1))
        rc = stop_proc(m3); e3 = err_of("min3")
        check("6 minute SIGTERM: it stops cleanly: exit 0, `stopped` said, no traceback", rc == 0 and "stackshot minute: stopped" in e3 and "Traceback" not in e3, (rc, e3[-500:]))
        check("6 minute SIGTERM: …the lock is free (its file is empty and another process takes it)", lock_text() == "" and try_in_child().get("state") == "taken", (lock_text(), try_in_child()))
        check("6 minute SIGTERM: …and the server reports the runner as not running (the pid is gone)", eventually(lambda: status_of(P1).get("running") is False and "minute runner not running" in status_of(P1).get("message", ""), 10.0), status_of(P1))
        stop_proc(sv)
        check("6 unit server: no traceback in its log across all of it", "Traceback" not in err_of("srv-unit"), err_of("srv-unit")[-1000:])

        # -- an inline server takes the lock; a minute against it (settings that disagree) is refused
        wipe(); P2 = free_port(); ci2 = conf("inline", P2); cu2 = conf("unit", P2)
        sv2 = server_proc(ci2, "srv-inline")
        check("6 inline server: comes up", up(P2, sv2), err_of("srv-inline")[-800:])
        check("6 inline server: it holds the lock (its file names it) and beats the status file as its own", (lock_text() or "").strip() == str(sv2.pid) and beats_by(sv2.pid, 30.0), (lock_text(), beat()))
        st = status_of(P2)
        check("6 inline server: /audit/status is the runner's own record from memory: running, no source, no message", st.get("running") is True and "source" not in st and "message" not in st, st)
        m4 = minute_proc(cu2, "min4"); rc = m4.wait(120); e4 = err_of("min4")
        check("6 inline server + minute: the process is refused with exit 5, naming the server's pid, while the server keeps serving and keeps the lock", rc == 5 and f"held by pid {sv2.pid}" in e4 and "Traceback" not in e4 and sv2.poll() is None and up(P2, sv2, 10) and (lock_text() or "").strip() == str(sv2.pid), (rc, e4[-500:], lock_text()))
        check("6 inline server + minute: …and the server's runner goes on beating", eventually(lambda: (beat() or {}).get("pid") == sv2.pid and abs(time.time() - beat()["heartbeat"]) < 10, 10.0), beat())
        stop_proc(sv2)
        check("6 inline server: a SIGTERM ends it with no traceback", "Traceback" not in err_of("srv-inline"), err_of("srv-inline")[-800:])

        # -- an inline server that finds the lock taken by another process
        wipe(); P3 = free_port(); ci3 = conf("inline", P3)
        holder = spawn_lock()
        sv3 = server_proc(ci3, "srv-held")
        check("6 server, lock held: it starts and serves (it does not fail over the lock)", up(P3, sv3) and sv3.poll() is None, err_of("srv-held")[-800:])
        st = status_of(P3); e = err_of("srv-held")
        check("6 server, lock held: it says on one stderr line that it starts no runner, with the holder's pid", e.count("runner not started: lock held by pid") == 1 and f"lock held by pid {holder.pid}" in e, e[-800:])
        check("6 server, lock held: /audit/status says `minute runner not running (lock held by pid N)` and running false; the server wrote no status file", st.get("running") is False and st.get("message") == f"minute runner not running (lock held by pid {holder.pid})" and not (MIN / F.STATUS).exists(), (st, os.listdir(MIN)))
        check("6 server, lock held: the holder's lock is untouched (its file still names it)", (lock_text() or "").strip() == str(holder.pid), lock_text())
        end_kid(holder)
        took = eventually(lambda: status_of(P3).get("running") is True and "message" not in status_of(P3), 130.0, 2.0)
        st = status_of(P3) if took else {}
        check("6 server, lock held: once the holder lets go the server takes the lock by its watchdog's next look (within a minute or two) and starts the runner: the status is the runner's own (running, no `not running` message), the lock file names the server, and the log says so",
              took and "message" not in st and "source" not in st and (lock_text() or "").strip() == str(sv3.pid) and "the runner lock is free now; this server took it and starts the runner" in err_of("srv-held"), (st, lock_text(), err_of("srv-held")[-500:]))
        stop_proc(sv3)
        check("6 server, lock held: no traceback in its log", "Traceback" not in err_of("srv-held"), err_of("srv-held")[-800:])

        # -- the child that starts before the server
        wipe(); P4 = free_port(); cu4 = conf("unit", P4)
        mw = minute_proc(cu4, "min-wait", "--ready-poll", "0.5")
        check("6 minute: started before the server it waits: alive, the lock is its own (taken before the wait), a waiting line names the server's /healthz, and no status file is written", eventually(lambda: "waiting for the server at" in err_of("min-wait"), 60.0)
              and mw.poll() is None and (lock_text() or "").strip() == str(mw.pid) and not (MIN / F.STATUS).exists() and f"http://127.0.0.1:{P4}/healthz" in err_of("min-wait"), (err_of("min-wait")[-500:], os.listdir(MIN) if MIN.exists() else None))
        time.sleep(2.0)
        check("6 minute: …and it still has beaten nothing after seconds of waiting", mw.poll() is None and not (MIN / F.STATUS).exists())
        mw_b = minute_proc(cu4, "min-wait-b", "--ready-poll", "0.5")
        try: rc_b = mw_b.wait(30)
        except subprocess.TimeoutExpired: rc_b = None; stop_proc(mw_b)
        check("6 minute: the lock is taken BEFORE the readiness wait: a second minute started while the first still waits for the server is refused at once (exit 5, naming the first's pid), not after the server is up",
              rc_b == 5 and f"held by pid {mw.pid}" in err_of("min-wait-b") and mw.poll() is None, (rc_b, err_of("min-wait-b")[-300:]))
        rc = stop_proc(mw); e = err_of("min-wait")
        check("6 minute: a SIGTERM while it waits stops it cleanly: exit 0, `stopped before the server was up`, no runner started, the lock free", rc == 0 and "stopped before the server was up" in e and "Traceback" not in e and lock_text() == "" and not (MIN / F.STATUS).exists(), (rc, e[-400:], lock_text()))
        mw2 = minute_proc(cu4, "min-wait2", "--ready-poll", "0.5")
        eventually(lambda: "waiting for the server at" in err_of("min-wait2"), 60.0)
        sv4 = server_proc(cu4, "srv-late")
        check("6 minute: when the server comes up the waiting child starts its runner and beats", up(P4, sv4) and beats_by(mw2.pid, 60.0), (err_of("min-wait2")[-500:], err_of("srv-late")[-500:], beat()))
        check("6 minute: …and the server reads that child's record", eventually(lambda: status_of(P4).get("running") is True and status_of(P4).get("pid") == mw2.pid and status_of(P4).get("source") == "file", 10.0), status_of(P4))
        stop_proc(mw2); stop_proc(sv4)
    finally:
        for pr in PROCS:
            if pr.poll() is None:
                pr.kill()
                try: pr.wait(20)
                except subprocess.TimeoutExpired: pass
        for ef in ERRS.values():
            try: ef.close()
            except OSError: pass
finally:
    for k in KIDS:
        if k.poll() is None: k.kill(); k.wait()
        for f in (k.stdin, k.stdout, k.stderr):
            try:
                if f and not f.closed: f.close()
            except OSError: pass
    F.lock_release()

print(f"minute: {len(ran)} checks, {len(fails)} failed")
sys.exit(1 if fails else 0)
