"""Scenario test for the minute set's runner (core/runner.py, service/runner.py `ticks`): one thread and one lock run the watchers' and anchor passes and the
fleet's clocks in a fixed order. Fixture data, no live store, no network, no GitHub; the only threads are the runner's own and short-lived test threads.

  1  the Runner on its own (fake clock): the ticks run in the table's order · a tick that raises is logged and recorded and never stops the next · a paced tick waits for its pace
     (one minute, counted from the end of the last paced round), an event tick for the wake event or the wake wait, and runs in every paced round, in front of the paced ticks · a held board skips the board ticks and no others · a wake wait that fails
     does not stop the round · a table with a tick twice or a bad group is refused · the status carries the last run and the last error per tick
  2  the lock and the thread (real clock): two callers of run_round never overlap a tick · start runs the first event round at once and the first paced round one pace later ·
     setting the wake event runs an event round · shutdown stops the thread, even one asleep for a minute, and a restart works · a round that raises does not end the loop
  3  the server's table: the settle events first in their order (watchers' pass, anchor pass, event waits, done check, step proof), then the hand-off tick, then the answers, then the
     fleet's clocks and the publish, then the ten-minute set (the filing pass, the dates pass, the audit lines); the For-you look runs as the dates pass; a replaced function is the one called;
     the old loops (_wake_loop, _fleet_watch, _run_fleet_ticks) and the flag (_runner_enabled, status_off) are gone
  3b the ten-minute set on its own (fake clock): it runs in the first paced round after each tenth minute, after the minute set, on the start's schedule (a late round does not shift the
     next one, a long gap does not run it twice), is skipped with the board held, and a tick of it that raises does not stop the next; the filing and dates ticks are the server's
  4  the start: the runner is always started and the old loops are not (they no longer exist); a config that still carries the retired [runner] enabled key (true, false or any
     value) starts the same way, and config.notes() says once that the key can go; the example config has no [runner] section; no clock runs twice in a round (every clock counted)
  5  the board's reads: /audit/status carries the runner (its record before the start and after, last run and last error per tick) · the migration's hold skips the board ticks
     of the server's table · the fleet publish step publishes when the fleet files moved, and not at its first look · the watchers' pass wrapper runs the pass only when a wake is due
  6  the runner's watchdog (fake clock): `Runner.stalled` is false for a current runner and true past `runner.STALL_AFTER`; the watchdog runs in a thread of its own and the publish loop runs no wake pass ·
     a current runner is told to nobody · a stalled one makes exactly one log line and one message to the builder · a second look while it stays stalled sends nothing · a completed round re-arms it · the message names the tick the runner is in

    tests/run-suite runner        → exit 0 / 1"""
import contextlib, datetime as dt, io, json, logging, os, pathlib, re, sys, threading, time, types

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="r1-runner-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"), login=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                 (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'), (r'(?m)^owner = "the owner"', 'owner = "Oliver"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', 'allowed_emails = ["oliver@example.org"]'), (r'(?m)^ui_open = true', 'ui_open = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "state/site", "secrets", "touch", "repo", "brain/projects"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text("{}")
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "store/projects.json").write_text(json.dumps({"pages": {}})); (T / "store/anchors.json").write_text("{}"); (T / "store/next-id").write_text("1")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

from stackshot.core import runner as R


class Clock:
    def __init__(self, t=1000.0): self.t = t
    def __call__(self): return self.t
    def advance(self, s): self.t += s


@contextlib.contextmanager
def stderr_lines():
    buf, real = io.StringIO(), sys.stderr
    sys.stderr = buf
    try:
        yield buf
    finally:
        sys.stderr = real


def safe_round(r, **kw):
    """run_round, except that a runner with no guard (the mutation this suite is checked against) fails the checks after it instead of crashing the suite."""
    try:
        return r.run_round(**kw)
    except Exception as e:  # noqa: BLE001
        return f"raised {e!r}"


def eventually(cond, within=5.0):
    end = time.time() + within
    while time.time() < end:
        if cond(): return True
        time.sleep(0.01)
    return cond()


# ---- 1. the Runner on its own, with a fake clock
seen: list[str] = []
def rec(name): return lambda: seen.append(name)
def table():
    return [R.Tick("w1", rec("w1"), "settle", "event"), R.Tick("w2", rec("w2"), "settle", "event"), R.Tick("s3", rec("s3"), "settle"),
            R.Tick("h", rec("h"), "handoff", board=True), R.Tick("a", rec("a"), "answers", board=True), R.Tick("f1", rec("f1"), "fleet"), R.Tick("f2", rec("f2"), "fleet", board=True)]
clk = Clock()
r = R.Runner(table(), clock=clk, wake_wait=lambda: 30.0)
out = r.run_round()
check("1 order: the first round runs every tick, in the table's order", out == ["w1", "w2", "s3", "h", "a", "f1", "f2"] and seen == out, (out, seen))
seen.clear()
check("1 …a second round at once runs nothing (no pace has passed, no wake is due)", r.run_round() == [] and seen == [], seen)
check("1 …the wake event runs the event ticks alone, in order", r.run_round(event=True) == ["w1", "w2"] and seen == ["w1", "w2"], seen)
seen.clear(); clk.advance(R.PACE - 0.1)
check("1 pace: the default pace is one minute", R.PACE == 60.0 and r.pace == 60.0 and r.status()["pace_seconds"] == 60.0, (R.PACE, r.pace))
check("1 pace: 0.1 s before the minute after the last paced round no paced tick runs (the wake wait of 30 s has ended, so the event ticks do)", r.run_round() == ["w1", "w2"] and seen == ["w1", "w2"], seen)
seen.clear(); clk.advance(0.2)       # the minute: the paced ticks are due; the wake wait (30 s from the last event round) is not, yet the event ticks come first
out = r.run_round()
check("1 pace: at the minute a paced round runs the whole table in order, the event ticks in front", out == ["w1", "w2", "s3", "h", "a", "f1", "f2"] and seen == out, out)
# a wake that comes between two minutes runs the two event ticks alone and does not move the minute; the next minute's round still starts with them, whatever the wake wait says
seen.clear(); clkm = Clock(2000.0); waits = [30.0]
rm = R.Runner(table(), clock=clkm, wake_wait=lambda: waits[0])
rm.run_round(); seen.clear(); waits[0] = 60.0; clkm.advance(25.0)
check("1 minute: a wake event 25 s into the minute runs the event ticks alone, in order", rm.run_round(event=True) == ["w1", "w2"] and seen == ["w1", "w2"], seen)
seen.clear(); clkm.advance(35.0)      # the minute is up; the wake wait set at 25 s (60 s) is not over until 85 s
out = rm.run_round()
check("1 minute: the paced round at the minute carries the event ticks although their wake wait is not over, so the passes that end a wait come first", out == ["w1", "w2", "s3", "h", "a", "f1", "f2"] and seen == out, out)
seen.clear(); clkm.advance(10.0)
check("1 nothing runs 10 s after a minute's round", rm.run_round() == [] and seen == [], seen)
seen.clear(); clkm.advance(50.0)
check("1 the next paced round comes a minute from the end of the last one, again in the table's order", rm.run_round() == ["w1", "w2", "s3", "h", "a", "f1", "f2"] and seen == ["w1", "w2", "s3", "h", "a", "f1", "f2"], seen)
# the pace is counted from the END of the last paced round (as the old sleep(20) after a round)
clk2 = Clock(); slow = []
def slow_tick(): slow.append(clk2.t); clk2.advance(5.0)
r2 = R.Runner([R.Tick("slow", slow_tick, "fleet")], clock=clk2)
r2.run_round(); clk2.advance(R.PACE - 1.0)
check("1 pace is measured from the end of the last paced round: 59 s after a 5 s round is not yet due", r2.run_round() == [], slow)
clk2.advance(1.1)
check("1 …and a minute after its end it is", r2.run_round() == ["slow"] and len(slow) == 2, slow)
# the old pace is still there for whoever builds a Runner with it (the constructor's pace is the knob; the old fleet watch's 20 s is what the flag off keeps)
clk2b = Clock(); r2b = R.Runner([R.Tick("t", rec("t"), "fleet")], clock=clk2b, pace=20.0); r2b.run_round(); clk2b.advance(19.9)
check("1 a runner built with a 20 s pace runs at 20 s, not before", r2b.run_round() == [] and (clk2b.advance(0.2) or r2b.run_round() == ["t"]))

# a tick that raises
seen.clear()
def boom(): raise RuntimeError("one item broke it")
clk3 = Clock(5000.0)
r3 = R.Runner([R.Tick("a", rec("a"), "settle"), R.Tick("b", boom, "settle"), R.Tick("c", rec("c"), "handoff"), R.Tick("d", rec("d"), "fleet")], clock=clk3)
with stderr_lines() as err:
    try:
        out3 = r3.run_round()
    except Exception as e:  # noqa: BLE001  — a runner with no guard raises here: the checks below fail rather than the suite crashing
        out3 = f"raised {e!r}"
check("1 guard: a tick that raises does not stop the ones after it", out3 == ["a", "b", "c", "d"] and seen == ["a", "c", "d"], (out3, seen))
check("1 guard: …it is logged by name with its error", "runner: b failed: RuntimeError: one item broke it" in err.getvalue(), err.getvalue())
st = {t["name"]: t for t in r3.status()["ticks"]}
check("1 status: the failing tick has its last error, the time of it, one run and one error; the others none",
      st["b"]["last_error"] == "RuntimeError: one item broke it" and st["b"]["last_error_at"] == 5000.0 and st["b"]["runs"] == 1 and st["b"]["errors"] == 1
      and all(st[n]["last_error"] is None and st[n]["errors"] == 0 and st[n]["last_run"] == 5000.0 and st[n]["runs"] == 1 for n in "acd"), st)
check("1 status: the shape (mode, enabled, pace, rounds, last round, a record per tick with its group and pace)",
      {k: r3.status()[k] for k in ("enabled", "mode", "pace_seconds", "rounds", "last_round")} == {"enabled": True, "mode": "runner", "pace_seconds": R.PACE, "rounds": 1, "last_round": 5000.0}
      and [(t["name"], t["group"], t["pace"]) for t in r3.status()["ticks"]] == [("a", "settle", "paced"), ("b", "settle", "paced"), ("c", "handoff", "paced"), ("d", "fleet", "paced")], r3.status())
clk3.advance(R.PACE + 1)
with stderr_lines():
    safe_round(r3)
st = {t["name"]: t for t in r3.status()["ticks"]}
check("1 status: the last error stays after a later clean run of the others; runs count up", st["b"]["runs"] == 2 and st["b"]["errors"] == 2 and st["a"]["runs"] == 2 and st["a"]["last_run"] == 5000.0 + R.PACE + 1, st)

# a tick that raises SystemExit or KeyboardInterrupt (not an Exception) is the same: logged, recorded, and the ones after it run
seen.clear()
def bye(): raise SystemExit("bye")
def intr(): raise KeyboardInterrupt()
r3b = R.Runner([R.Tick("a", rec("a"), "settle"), R.Tick("bye", bye, "settle"), R.Tick("c", rec("c"), "handoff"), R.Tick("intr", intr, "answers"), R.Tick("d", rec("d"), "fleet")], clock=Clock(7000.0))
with stderr_lines() as err:
    out3b = safe_round(r3b)
st3b = {t["name"]: t for t in r3b.status()["ticks"]}
check("1 guard: a tick that raises SystemExit or KeyboardInterrupt does not stop the ones after it either", out3b == ["a", "bye", "c", "intr", "d"] and seen == ["a", "c", "d"], (out3b, seen))
check("1 guard: …both are logged by name and recorded as the tick's last error", "runner: bye failed: SystemExit: bye" in err.getvalue() and "runner: intr failed: KeyboardInterrupt" in err.getvalue()
      and st3b["bye"]["last_error"] == "SystemExit: bye" and st3b["intr"]["errors"] == 1 and st3b["d"]["last_error"] is None, (err.getvalue(), st3b["bye"]))
# a slow tick is logged by name
clk8 = Clock(9000.0)
def took(n): return lambda: clk8.advance(n)
r8 = R.Runner([R.Tick("quick", took(29.0), "settle"), R.Tick("slow", took(31.0), "fleet")], clock=clk8)
with stderr_lines() as err:
    r8.run_round()
check("1 slow tick: one over 30 s is logged by name with its length; one at 29 s is not", "runner: slow took 31 s" in err.getvalue() and "quick" not in err.getvalue(), err.getvalue())

# the hold
held = [True]; seen.clear()
r4 = R.Runner(table(), holding=lambda: held[0], clock=Clock(), wake_wait=lambda: 30.0)
out4 = r4.run_round()
check("1 hold: while the board is held the board ticks are skipped and the others run, in order", out4 == ["w1", "w2", "s3", "f1"] and seen == out4, (out4, seen))
check("1 hold: …the skips are counted in the status", {t["name"]: t["skipped"] for t in r4.status()["ticks"]} == {"w1": 0, "w2": 0, "s3": 0, "h": 1, "a": 1, "f1": 0, "f2": 1}, r4.status())
r5 = R.Runner(table(), holding=lambda: (_ for _ in ()).throw(RuntimeError("no hold file")), clock=Clock())
check("1 hold: a hold that cannot be read does not stop the clocks", r5.run_round() == ["w1", "w2", "s3", "h", "a", "f1", "f2"])
# a wake wait that fails
def bad_wait(): raise ValueError("no wake")
r6 = R.Runner(table(), wake_wait=bad_wait, clock=Clock())
with stderr_lines() as err:
    out6 = r6.run_round()
check("1 a wake wait that raises is logged and does not stop the round (the old longest sleep, 60 s, is taken)", len(out6) == 7 and "wake wait not read: ValueError: no wake" in err.getvalue() and r6._wake_at == r6.clock() + R.WAKE_MAX, (out6, err.getvalue()))
r7 = R.Runner(table(), wake_wait=lambda: 0.0, clock=Clock())
r7.run_round()
check("1 a wake wait of 0 is raised to the floor (no spinning on a wake that cannot fire)", r7._wake_at == r7.clock() + R.WAKE_MIN, r7._wake_at)
for label, bad in (("a tick twice", [R.Tick("x", rec("x"), "settle"), R.Tick("x", rec("x"), "fleet")]), ("a group not in the list", [R.Tick("x", rec("x"), "nowhere")]),
                   ("a pace not in the list", [R.Tick("x", rec("x"), "fleet", "sometimes")])):
    try:
        R.Runner(bad); ok = False
    except ValueError: ok = True
    check(f"1 a table with {label} is refused", ok)

# ---- 2. the lock and the thread, real clock
active, peak, order = [0], [0], []
mx = threading.Lock()
def work(name):
    def f():
        with mx:
            active[0] += 1; peak[0] = max(peak[0], active[0]); order.append(("in", name))
        time.sleep(0.04)
        with mx:
            active[0] -= 1; order.append(("out", name))
    return f
rl = R.Runner([R.Tick("t1", work("t1"), "settle"), R.Tick("t2", work("t2"), "handoff"), R.Tick("t3", work("t3"), "fleet")], pace=0.0)
ths = [threading.Thread(target=rl.run_round, kwargs={"event": True}) for _ in range(3)]
for t_ in ths: t_.start()
for t_ in ths: t_.join(10)
check("2 lock: three callers of run_round at once never overlap a tick (the peak is one)", peak[0] == 1 and len(order) == 18, (peak, len(order)))
check("2 lock: …and each round ran its ticks together, in order (t1 t2 t3 three times)", [n for k, n in order if k == "in"] == ["t1", "t2", "t3"] * 3, order)
check("2 lock: …the lock is free afterwards", rl.lock.acquire(blocking=False) and (rl.lock.release() or True))

starts = []
ev = threading.Event()
def mk(name): return lambda: starts.append((name, time.time()))
t_start = time.time()
rt = R.Runner([R.Tick("wk", mk("wk"), "settle", "event"), R.Tick("pc", mk("pc"), "fleet")], pace=0.3, wake_wait=lambda: 60.0, event=ev)
th = rt.start()
check("2 start: one daemon thread named for the runner", th.is_alive() and th.daemon and th.name == "runner" and rt.start() is th, th)
check("2 start: the first event round runs at once, the paced tick not before its pace", eventually(lambda: [n for n, _ in starts] == ["wk"], 2) and not any(n == "pc" for n, _ in starts), starts)
check("2 start: …the paced tick comes one pace after the start", eventually(lambda: any(n == "pc" for n, _ in starts), 3) and dict(starts)["pc"] - t_start >= 0.3, starts)
n_wk = sum(1 for n, _ in starts if n == "wk")
ev.set()
check("2 wake event: setting the event runs the event tick again (and wakes the thread from its sleep)", eventually(lambda: sum(1 for n, _ in starts if n == "wk") == n_wk + 1, 2), starts)
check("2 wake event: …the paced tick is not run by it twice in a row inside its pace", sum(1 for n, _ in starts if n == "pc") <= 2, starts)
t0 = time.time()
check("2 shutdown: stop() ends the thread", rt.stop(5) is True and not th.is_alive(), th)
check("2 shutdown: …promptly, although the thread was asleep for up to a minute", time.time() - t0 < 2.0, time.time() - t0)
n_after = len(starts); time.sleep(0.5)
check("2 shutdown: …and no tick runs after it", len(starts) == n_after, (n_after, len(starts)))
check("2 shutdown: stop() again, and on a runner never started, is quiet and true", rt.stop(1) is True and R.Runner([]).stop(1) is True)
th2 = rt.start()
check("2 restart: a stopped runner starts a new thread and runs again", th2 is not th and eventually(lambda: len(starts) > n_after, 3), (n_after, len(starts)))
rt.stop(5)
check("2 restart: …and stops again", not th2.is_alive())

# a long tick: stop waits for it to finish, never cuts it off
gate = threading.Event(); done = []
def slow_long(): gate.wait(5); done.append(1)
rs = R.Runner([R.Tick("long", slow_long, "fleet", "event")], pace=60.0)
rs.start()
eventually(lambda: rs.status()["ticks"][0]["runs"] == 0 and rs.lock.locked(), 2)
t_stop = threading.Thread(target=lambda: rs.stop(5)); t_stop.start()
time.sleep(0.2)
check("2 shutdown: a tick in progress is not cut off (the thread is still there until it finishes)", rs.thread.is_alive() and done == [])
gate.set(); t_stop.join(6)
check("2 shutdown: …it finishes, then the thread ends", done == [1] and not rs.thread.is_alive())

# the loop survives a round that raises
calls = []
rr = R.Runner([R.Tick("x", lambda: calls.append(1), "fleet")], pace=0.05)
real_round = rr.run_round
def flaky(event=False):
    calls.append("round")
    if calls.count("round") == 1: raise RuntimeError("round broke")
    return real_round(event=event)
rr.run_round = flaky
with stderr_lines() as err:
    rr.start()
    ok = eventually(lambda: 1 in calls, 5)
    rr.stop(5)
check("2 a round that raises (not a tick) is logged and the loop goes on", ok and "runner: round failed: RuntimeError: round broke" in err.getvalue(), (calls, err.getvalue()))

# the thread goes on past a tick that raises SystemExit, and past a round that does; only stop() ends it
calls2 = []
def exit_tick():
    calls2.append("x")
    if calls2.count("x") == 1: raise SystemExit("a tick said exit")
rx = R.Runner([R.Tick("exit", exit_tick, "settle"), R.Tick("after", lambda: calls2.append("after"), "fleet")], pace=0.05)
with stderr_lines() as err:
    thx = rx.start()
    ok = eventually(lambda: calls2.count("after") >= 2 and calls2.count("x") >= 2, 5)
    alive = thx.is_alive()
    stopped = rx.stop(5)
check("2 a tick that raises SystemExit does not end the thread: the later ticks run, again and again, until stop()", ok and alive and stopped and not thx.is_alive() and "runner: exit failed: SystemExit: a tick said exit" in err.getvalue(), (calls2, err.getvalue()))
calls3 = []
rq = R.Runner([R.Tick("x", lambda: calls3.append(1), "fleet")], pace=0.05)
real_round3 = rq.run_round
def exiting(event=False):
    calls3.append("round")
    if calls3.count("round") == 1: raise SystemExit("round exit")
    return real_round3(event=event)
rq.run_round = exiting
with stderr_lines() as err:
    thq = rq.start()
    ok = eventually(lambda: 1 in calls3, 5)
    alive = thq.is_alive()
    stopped = rq.stop(5)
check("2 a round that raises SystemExit is logged and the loop goes on; stop() still ends it", ok and alive and stopped and "runner: round failed: SystemExit: round exit" in err.getvalue(), (calls3, err.getvalue()))
calls4 = []
rz = R.Runner([R.Tick("x", lambda: calls4.append(1), "fleet")], pace=60.0)
def stopping(event=False):
    rz._stop.set(); raise SystemExit("exit while stopping")
rz.run_round = stopping
with stderr_lines():
    thz = rz.start()
    ended = eventually(lambda: not thz.is_alive(), 5)
check("2 …and when stop() was asked at the same time, the loop ends instead of going on", ended, thz)

# ---- 3. the server's table
from stackshot.core import config as _cfg
from stackshot.web import server
from stackshot.service import handoff as handoff_svc
from stackshot.service import wakes as wakes_svc, event_waits as evwaits_svc
from stackshot.service import runner as runner_svc
from stackshot.service import stall_tick as stalltick_svc
from stackshot.web.tools import rules as _wt_rules
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.service import telling
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
ticks = runner_svc.ticks()
names = [t.name for t in ticks]
check("3 order: the settle events come first, in order: the watchers' pass, the anchor pass, the phase sweep, the event waits, the done check, the step proof",
      names[:6] == ["wake_pass", "anchor_pass", "phase_sweep", "evwait_tick", "check_tick", "proof_tick"] and {t.group for t in ticks[:6]} == {"settle"}, names)
check("3 order: …then the balancer and the hand-off tick (the balancer first, so a move at ten minutes comes before the hand-off tick's reminder), then the answers, then the fleet's clocks",
      names[6:8] == ["balance_tick", "handoff_tick"] and {t.group for t in ticks[6:8]} == {"handoff"} and names[8] == "answer_tick" and ticks[8].group == "answers"
      and {t.group for t in ticks[9:15]} == {"fleet"} and names[9:15] == ["roles_sync_safe", "clients_tick", "pilot_fallback_tick", "stall_tick", "handback_tick", "fleet_publish"], names)
check("3 order: …then the ten-minute set last: the filing pass, the dates pass, then the wake catch-up, then the audit lines and the hand-over, then the archive sweep, all paced as the ten-minute set and standing still while the board is held",
      names[15:] == ["filing_tick", "dates_tick", "wake_catchup", "silence_tick", "archive_tick"] and {t.group for t in ticks[15:]} == {"tenmin"} and {t.pace for t in ticks[15:]} == {"tenmin"} and all(t.board for t in ticks[15:]), names)
check("3 order: …the groups never go back (settle, handoff, answers, fleet, tenmin)", [R.GROUPS.index(t.group) for t in ticks] == sorted(R.GROUPS.index(t.group) for t in ticks))
check("3 pace: only the watchers' pass and the anchor pass are event ticks ; the filing, dates and audit-line passes and the wake catch-up are the ten-minute set's; every other tick is paced",
      [t.name for t in ticks if t.pace == "event"] == ["wake_pass", "anchor_pass"] and [t.name for t in ticks if t.pace == "tenmin"] == ["filing_tick", "dates_tick", "wake_catchup", "silence_tick", "archive_tick"]
      and all(t.pace == "paced" for t in ticks[2:15]))
check("3 coverage: the table is the fleet's clocks and the wake passes, the publish and the ten-minute set, nothing twice (the For-you look is the dates pass, not a tick of its own)",
      names == ["wake_pass", "anchor_pass", "phase_sweep", "evwait_tick", "check_tick", "proof_tick", "balance_tick", "handoff_tick", "answer_tick", "roles_sync_safe", "clients_tick", "pilot_fallback_tick",
                "stall_tick", "handback_tick", "fleet_publish", "filing_tick", "dates_tick", "wake_catchup", "silence_tick", "archive_tick"] and "foryou_tick" not in names, names)
check("3 gone: the wake loop, the fleet watch, the old round, the flag and the old-threads status are no longer there",
      not any(hasattr(server, n) for n in ("_wake_loop", "_fleet_watch", "_run_fleet_ticks", "_runner_enabled")) and not hasattr(R, "status_off"), [n for n in dir(server) if "fleet_watch" in n or "wake_loop" in n])
check("3 board: the clocks that read items are marked to stand still while the migration holds the board; the registry sync, the clients' tick and the publish are not",
      {t.name for t in ticks if not t.board} == {"wake_pass", "anchor_pass", "roles_sync_safe", "clients_tick", "fleet_publish"}, [(t.name, t.board) for t in ticks])

TICK_FUNCS = {"wake_pass": "wake_pass", "anchor_pass": "anchor_pass", "phase_sweep": "_phase_tick", "evwait_tick": "evwait_tick", "check_tick": "_check_tick", "proof_tick": "_proof_tick", "balance_tick": "_balance_tick", "handoff_tick": "handoff_tick",
              "answer_tick": "_answer_tick", "roles_sync_safe": "_roles_sync_safe", "clients_tick": "_clients_tick", "pilot_fallback_tick": "_pilot_fallback_tick",
              "stall_tick": "stall_tick", "handback_tick": "handback_tick", "filing_tick": "_filing_tick", "dates_tick": "_dates_tick", "wake_catchup": "minute_wake_catchup", "silence_tick": "_silence_tick", "archive_tick": "_archive_tick"}
def own(fn): return {"handoff_tick": handoff_svc, "handback_tick": telling, "fleet_stamp": runner_svc, "wake_pass": wakes_svc, "anchor_pass": wakes_svc, "minute_wake_catchup": wakes_svc, "next_wake": wakes_svc, "evwait_tick": evwaits_svc, "stall_tick": stalltick_svc}.get(fn, server)       # the owner of a function the spies set: the hand-back tick is the telling's, the fleet stamp is the runner's, the wake passes and the event wait are service/wakes.py's and service/event_waits.py's, the rest are the server's
counts: dict[str, int] = {}
order_seen: list[str] = []
saved = {}
def spy_all():
    for label, fn in TICK_FUNCS.items():
        saved[fn] = getattr(own(fn), fn)
        setattr(own(fn), fn, (lambda label=label: (counts.__setitem__(label, counts.get(label, 0) + 1), order_seen.append(label), [])[-1]))
    saved["next_wake"] = wakes_svc.next_wake
    wakes_svc.next_wake = lambda: dt.datetime(2000, 1, 1, tzinfo=server._pages.zone_now().tzinfo)       # a wake is due, so the watchers' pass runs
    saved["fleet_stamp"] = runner_svc.fleet_stamp
    runner_svc.fleet_stamp = lambda: 1.0
def unspy_all():
    for fn, f in saved.items(): setattr(own(fn), fn, f)
    saved.clear(); counts.clear(); order_seen.clear()

spy_all()
try:
    rs3 = runner_svc.make()
    rs3.run_round(event=True)
    check("3 late binding: replacing a tick function on the server (as the suites do) is what the table calls; one round runs every clock once, in order (the ten-minute set in the first round)",
          order_seen == list(TICK_FUNCS) and all(v == 1 for v in counts.values()) and len(counts) == len(TICK_FUNCS), (order_seen, counts))
finally:
    unspy_all()

# ---- 3b. the ten-minute set on its own, and the server's two ticks of it
def ten_table(): return [R.Tick("m", rec("m"), "fleet"), R.Tick("t1", rec("t1"), "tenmin", "tenmin"), R.Tick("t2", rec("t2"), "tenmin", "tenmin", board=True)]
clk3 = Clock(5000.0)
r3 = R.Runner(ten_table(), clock=clk3, ten_pace=600.0, pace=60.0, wake_wait=lambda: 60.0)
check("3b a runner driven by hand runs the ten-minute set in its first paced round, after the minute set", r3.run_round() == ["m", "t1", "t2"])
clk3.advance(60.0)
check("3b …a minute later only the minute set runs", r3.run_round() == ["m"])
for _ in range(8): clk3.advance(60.0); r3.run_round()          # 5120 … 5600
check("3b …and on the tenth minute the set runs right after the minute set", (clk3.advance(60.0), r3.run_round())[1] == ["m", "t1", "t2"], clk3.t)
check("3b …the next one is ten minutes on, not a pace after it", (clk3.advance(60.0), r3.run_round())[1] == ["m"] and r3._ten_at == 5000.0 + 1200.0, r3._ten_at)
clk3.t = 5000.0 + 1200.0 + 30.0                                 # a round 30 s late
check("3b a round 30 s late still runs the set once, and the next one is still on the tenth minute (the schedule does not slip)", r3.run_round() == ["m", "t1", "t2"] and r3._ten_at == 5000.0 + 1800.0, r3._ten_at)
clk3.t = 5000.0 + 1800.0 + 5000.0                               # asleep for most of an hour
check("3b a long gap runs the set once, not once for each tenth minute missed", r3.run_round() == ["m", "t1", "t2"] and r3.run_round() == [] and r3._ten_at > clk3.t and r3._ten_at - clk3.t <= 600.0, (r3._ten_at, clk3.t))
r3b = R.Runner(ten_table(), clock=(c3b := Clock(100.0)), ten_pace=600.0, pace=1000.0, wake_wait=lambda: 1000.0)
r3b.run_round(); c3b.advance(601.0)
check("3b a round for the wake event alone (no paced round) does not run the ten-minute set, even when it is due", "t1" not in r3b.run_round(event=True), r3b._ten_at)
r3c = R.Runner(ten_table(), clock=Clock(0.0), holding=lambda: True)
check("3b the board held: the ten-minute tick that reads items stands still, the other goes on, and the status counts it", r3c.run_round() == ["m", "t1"]
      and {t["name"]: t["skipped"] for t in r3c.status()["ticks"]}["t2"] == 1)
seen.clear()
def t1_raises(): raise RuntimeError("filing broke")
r3d = R.Runner([R.Tick("t1", t1_raises, "tenmin", "tenmin"), R.Tick("t2", rec("t2"), "tenmin", "tenmin")], clock=Clock(0.0))
with stderr_lines() as err3:
    out3d = safe_round(r3d)
check("3b a ten-minute tick that raises is logged and recorded and the next one still runs", out3d == ["t1", "t2"] and seen == ["t2"] and "runner: t1 failed: RuntimeError: filing broke" in err3.getvalue()
      and {t["name"]: t for t in r3d.status()["ticks"]}["t1"]["last_error"] == "RuntimeError: filing broke", (out3d, seen))
rs3b = R.Runner(ten_table())
rs3b.start()
check("3b start() leaves the first ten-minute set due at the first paced round (a restart never delays it), and the status carries the pace", rs3b._ten_at is None and rs3b.status()["ten_pace_seconds"] == R.TEN_PACE == 600.0, rs3b._ten_at)
rs3b.stop()
rs3b._ten_at = rs3b.clock() + 500.0                     # a runner that ran the set a short while ago …
rs3b.start()                                            # … and is started again: the set is due at its first paced round, not ten minutes on
check("3b …and after a second start() too, so restarts under ten minutes apart never starve the set", rs3b._ten_at is None, rs3b._ten_at)
rs3b.stop()
clk3f = Clock(7000.0)
r3f = R.Runner(ten_table(), clock=clk3f, ten_pace=600.0, pace=20.0, wake_wait=lambda: 1000.0)
r3f._pace_end = clk3f.t; r3f._ten_at = None             # the state start() leaves
clk3f.advance(20.0)
check("3b the first paced round after a start runs the ten-minute set, and the next one is ten minutes on", r3f.run_round() == ["m", "t1", "t2"] and r3f._ten_at == 7020.0 + 600.0, r3f._ten_at)
server._FORYOU_LAST[0] = time.time() + 1e6              # the look's own gate is shut …
server._dates_tick()                                    # … and the dates pass opens it, since the ten-minute set's pace is the gate there
check("3b the dates pass opens the For-you look's gate, so the runner's set runs it every ten minutes", server._FORYOU_LAST[0] < time.time() + 1000, server._FORYOU_LAST[0])
# the look keeps its own gate of five minutes for a caller that is not the dates pass
t0f = time.time()
server._FORYOU_LAST[0] = t0f - 299.0; server._foryou_tick(t0f)
check("3b a look 299 s ago is not repeated (the look's own gate stands) …", server._FORYOU_LAST[0] == t0f - 299.0, server._FORYOU_LAST[0])
server._foryou_tick(t0f + 2.0)
check("3b … and one 301 s ago is (the gate opens at five minutes)", server._FORYOU_LAST[0] == t0f + 2.0, server._FORYOU_LAST[0])
server._FORYOU_LAST[0] = t0f; server._foryou_tick(t0f + 1.0)
check("3b a look just made is not repeated at the next call", server._FORYOU_LAST[0] == t0f, server._FORYOU_LAST[0])
server._FORYOU_LAST[0] = t0f; server._dates_tick()
check("3b the dates pass runs the look at once whatever the look's own gate says", server._FORYOU_LAST[0] != t0f and server._FORYOU_LAST[0] >= t0f, server._FORYOU_LAST[0])
_cfg.CFG["audit"] = {**(_cfg.CFG.get("audit") or {}), "enabled": False}
check("3b the filing tick stands still while the audit is off", server._filing_tick() is None)

# ---- 4. the two modes of the start
class FakeThread:
    made: list = []
    def __init__(self, target=None, name=None, daemon=None, args=(), kwargs=None):
        self.target, self.name, self.daemon = target, name, daemon
        FakeThread.made.append(self)
    def start(self): self.started = True
    def is_alive(self): return False
    def join(self, timeout=None): pass
real_thread = threading.Thread
server._runners = types.SimpleNamespace(PERSIST=False, AUTOSTART=False, ON_CHANGE=None, restore=lambda: None)     # the CI runners page makes GitHub calls once it may start


def start_mode(runner_section):
    """_start_background with the threads faked (so none runs); `runner_section` is put into the config as the stale [runner] table (None: no such table).
    → (the names it returned, the targets started, the Runners made, the stderr)."""
    FakeThread.made.clear(); runner_svc.RUNNER[:] = []
    if runner_section is None: _cfg.CFG.pop("runner", None)
    else: _cfg.CFG["runner"] = runner_section
    threading.Thread = FakeThread
    try:
        with stderr_lines() as err:
            names_ = server._start_background()
    finally:
        threading.Thread = real_thread
    return names_, [t.target for t in FakeThread.made], list(runner_svc.RUNNER), err.getvalue()

import tomllib
example = tomllib.loads(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
check("4 config: the example config has no [runner] section, and the config the suite runs on reads none", "runner" not in example and _cfg.get("runner") is None, example.get("runner"))
check("4 config: a config without the key has no note about it", not any("[runner]" in n for n in _cfg.notes()), _cfg.notes())
for label, section in (("absent", None), ("enabled = true", {"enabled": True}), ("enabled = false", {"enabled": False}), ("enabled = \"true\"", {"enabled": "true"})):
    names_, targets, runners_, err = start_mode(section)
    check(f"4 start with {label}: one Runner is made and its loop is started, named runner, as a daemon", len(runners_) == 1 and runners_[0].loop in targets
          and any(t.target == runners_[0].loop and t.name == "runner" and t.daemon and getattr(t, "started", False) for t in FakeThread.made), (names_, runners_, [getattr(t, "__name__", t) for t in targets]))
    check(f"4 start with {label}: …the names returned are the runner, then the other loops, and no wake or fleet-watch thread",
          names_ == ["runner", "publish", "watchdog", "router", "search", "ghsync-worker", "ghsync-comments"], names_)
    check(f"4 start with {label}: …no thread more than the runner's loop and the six others is started", len(targets) == 7 and runners_[0].loop in targets, [getattr(t, "__name__", t) for t in targets])
    check(f"4 start with {label}: …the other loops are untouched: publish, watchdog, router, search, the mirror's worker and comments",
          all(f in targets for f in (runner_svc.publish_loop, runner_svc.watchdog_loop, server._router_live.loop, server._search.loop, server._gh.worker_loop, server._gh.comments_loop)), [getattr(t, "__name__", t) for t in targets])
    check(f"4 start with {label}: …no thread of the page-debt call is started: the audit run's pages stage asks the server for it", not hasattr(server, "_page_debt_loop") and not any(getattr(t, "__name__", "") == "_page_debt_loop" for t in targets), [getattr(t, "__name__", t) for t in targets])
    check(f"4 start with {label}: …the start says the runner runs, and says nothing of a mode or the flag", "stackshot: minute set: runner (one thread, one lock, paced rounds every 60 s)" in err and "old threads" not in err, err[-600:])
    if section is not None:
        check(f"4 start with {label}: …config.notes() says once that the retired key can go", len([n for n in _cfg.notes() if "[runner] enabled is retired" in n]) == 1, _cfg.notes())
names_, targets, runners_, err = start_mode({"enabled": True})
first_runner = runners_[0]
FakeThread.made.clear()
threading.Thread = FakeThread
try:
    with stderr_lines():
        server._start_background()
finally:
    threading.Thread = real_thread
check("4 a second start in the same process reuses the runner it has: one Runner, the same one, not overwritten", len(runner_svc.RUNNER) == 1 and runner_svc.RUNNER[0] is first_runner, runner_svc.RUNNER)
check("4 …the runner runs on the wake event _update sets, and over the server's table", runners_[0].wake is runner_svc.WAKE_EVENT and [t.name for t in runners_[0].ticks] == names)
check("4 …the status is the runner's (enabled, mode runner, a record for every tick)", runner_svc.status()["enabled"] is True and runner_svc.status()["mode"] == "runner"
      and len(runner_svc.status()["ticks"]) == len(names), runner_svc.status())
_cfg.CFG.pop("runner", None)

# a stale key in a file: the config module loads it and `check` exits 0 (the server start does not read the key)
import subprocess
stale = T / "stale.toml"; stale.write_text(toml + "\n[runner]\nenabled = true\n", encoding="utf-8")
cp = subprocess.run([sys.executable, "-I", f"{STACK}/stackshot/core/config.py", "check"], env={**os.environ, "STACKSHOT_CONFIG": str(stale)}, capture_output=True, text=True, timeout=60)
check("4 a file that still carries [runner] enabled = true loads and passes `config.py check`", cp.returncode == 0, (cp.returncode, cp.stdout[-300:], cp.stderr[-300:]))
cp = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import config; print('\\n'.join(config.notes()))", STACK], env={**os.environ, "STACKSHOT_CONFIG": str(stale)}, capture_output=True, text=True, timeout=60)
check("4 …and its notes (the start, doctor, a reload) carry the one line about the retired key", cp.returncode == 0 and cp.stdout.count("[runner] enabled is retired") == 1, (cp.returncode, cp.stdout[-300:], cp.stderr[-300:]))

# no tick twice: drive the runner for one round and count every clock
spy_all()
try:
    # the runner: one round of each kind, back to back
    rn = runner_svc.make()
    rn.run_round(event=True)
    rn.run_round(); rn.run_round()
    check("4 runner: a round and the calls after it inside the same pace run every clock exactly once (none twice, none dropped); the For-you look runs as the dates pass, not beside it", counts == {n: 1 for n in TICK_FUNCS}, counts)
    check("4 runner: …in the table's order (the settle events first, the hand-off, the answers, then the rest)", order_seen == list(TICK_FUNCS), order_seen)
    counts.clear(); order_seen.clear()
    # a tick that raises in the real table: the next still runs, and the status says which
    server._check_tick = lambda: (_ for _ in ()).throw(RuntimeError("check broke"))
    rb = runner_svc.make()
    with stderr_lines() as err:
        safe_round(rb, event=True)
    stb = {t["name"]: t for t in rb.status()["ticks"]}
    check("4 runner: a clock of the real table that raises does not stop the ones after it (the step proof, the hand-off, the answers and the fleet's all ran)",
          all(counts.get(n) == 1 for n in ("proof_tick", "handoff_tick", "answer_tick", "stall_tick", "handback_tick")) and "check_tick" not in counts, counts)
    check("4 runner: …its error is logged and in the status, with its time", "runner: check_tick failed: RuntimeError: check broke" in err.getvalue() and stb["check_tick"]["last_error"] == "RuntimeError: check broke"
          and stb["check_tick"]["last_error_at"] is not None and stb["proof_tick"]["last_error"] is None, (err.getvalue(), stb["check_tick"]))
finally:
    unspy_all()

# ---- 5. the board's reads, the hold, the publish step, the watchers' pass
from starlette.testclient import TestClient
app = server.mcp.http_app()
runner_svc.RUNNER[:] = []
with TestClient(app, base_url=BOARD) as c:
    try:
        j = c.get("/audit/status").json()
        jr = j.get("runner") or {}
        check("5 /audit/status: before a runner has started the record is there, enabled, not running, with no round and a record for every tick",
              jr.get("enabled") is True and jr.get("mode") == "runner" and jr.get("running") is False and jr.get("rounds") == 0 and [t["name"] for t in jr.get("ticks", [])] == names, jr)
        rst = runner_svc.make(); runner_svc.RUNNER[:] = [rst]
        spy_all()
        try:
            server._check_tick = lambda: (_ for _ in ()).throw(RuntimeError("check broke"))
            with stderr_lines():
                safe_round(rst, event=True)
        finally:
            unspy_all()
        j = c.get("/audit/status").json()["runner"]
        byname = {t["name"]: t for t in j["ticks"]}
        check("5 /audit/status: with the runner, mode runner, the pace, the rounds, and per tick the last run and the last error",
              j["enabled"] is True and j["mode"] == "runner" and j["pace_seconds"] == R.PACE and j["rounds"] == 1 and len(j["ticks"]) == len(names)
              and byname["check_tick"]["last_error"] == "RuntimeError: check broke" and byname["proof_tick"]["last_error"] is None and byname["proof_tick"]["last_run"] is not None, j)
    finally:
        runner_svc.RUNNER[:] = []

# the migration's hold, on the server's table
spy_all()
try:
    real_hold = server._watch.holding
    server._watch.holding = lambda: True
    rh = runner_svc.make()
    rh.run_round(event=True)
    check("5 hold: while the migration holds the board only the registry sync, the clients' tick and the two wake passes (which check for themselves) run",
          set(counts) == {"wake_pass", "anchor_pass", "roles_sync_safe", "clients_tick"}, counts)
finally:
    server._watch.holding = real_hold
    unspy_all()

# the publish step
published = []
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: published.append(1)
fleet_file = T / "fleet/a/machine.json"
runner_svc.MINUTE_STAMP[0] = None
runner_svc.fleet_publish()
check("5 fleet publish: its first look only takes the stamp (nothing is published)", published == [] and runner_svc.MINUTE_STAMP[0] is not None)
runner_svc.fleet_publish()
check("5 fleet publish: nothing moved, nothing published", published == [])
os.utime(fleet_file, (time.time() + 50, time.time() + 50))
runner_svc.fleet_publish(); runner_svc.fleet_publish()
check("5 fleet publish: a fleet file that moved publishes the board once", published == [1], published)
runner_svc.MINUTE_STAMP[0] = None
runner_svc.make()
check("5 fleet publish: a runner takes the stamp when it is made, so its first look publishes nothing", runner_svc.MINUTE_STAMP[0] == runner_svc.fleet_stamp() and (runner_svc.fleet_publish() or published == [1]), (published, runner_svc.MINUTE_STAMP))

# a publish that raises: tried once per change of the stamp, not every round; the stamp is never lowered
tries = []
def bad_publish(): tries.append(1); raise RuntimeError("publish broke")
server._publish = _wt_anchors._publish = _wt_route._publish = bad_publish
runner_svc.MINUTE_STAMP[0] = None
runner_svc.fleet_publish()
os.utime(fleet_file, (time.time() + 200, time.time() + 200))
errs = []
for _ in range(4):
    try: runner_svc.fleet_publish()
    except RuntimeError as e: errs.append(str(e))
check("5 fleet publish: a publish that keeps raising is tried once for one change of the stamp, not on every round after it", len(tries) == 1 and errs == ["publish broke"], (tries, errs))
high = runner_svc.MINUTE_STAMP[0]
os.utime(fleet_file, (time.time() + 100, time.time() + 100))
runner_svc.fleet_publish()
check("5 fleet publish: …the stamp is a high-water mark: an older stamp (a file replaced by an older one) does not lower it, and publishes nothing", runner_svc.MINUTE_STAMP[0] == high and len(tries) == 1, (high, runner_svc.MINUTE_STAMP, tries))
os.utime(fleet_file, (time.time() + 400, time.time() + 400))
try: runner_svc.fleet_publish()
except RuntimeError: pass
check("5 fleet publish: …and the next real change is tried once again", len(tries) == 2 and runner_svc.MINUTE_STAMP[0] > high, (tries, runner_svc.MINUTE_STAMP))
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: published.append("p")

# the watchers' pass wrapper
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: published.append("p")
woke = []; published.clear()
real_nw, real_wp, real_ap = wakes_svc.next_wake, wakes_svc.wake_pass, wakes_svc.anchor_pass
ZONE_TZ = server._pages.zone_now().tzinfo
try:
    wakes_svc.wake_pass = lambda: (woke.append("wake"), ["a1"])[1]
    wakes_svc.next_wake = lambda: None
    wakes_svc.minute_wake_pass()
    check("5 watchers' pass: no wake at all, the pass does not run", woke == [] and published == [])
    wakes_svc.next_wake = lambda: dt.datetime.now(ZONE_TZ) + dt.timedelta(hours=1)
    wakes_svc.minute_wake_pass()
    check("5 watchers' pass: a wake in an hour, the pass does not run", woke == [] and published == [])
    wakes_svc.next_wake = lambda: dt.datetime.now(ZONE_TZ) - dt.timedelta(minutes=1)
    wakes_svc.minute_wake_pass()
    check("5 watchers' pass: a wake that is due runs the pass, and the board is published for what it woke", woke == ["wake"] and published == ["p"], (woke, published))
    wakes_svc.wake_pass = lambda: []
    published.clear(); wakes_svc.minute_wake_pass()
    check("5 watchers' pass: a pass that woke nothing publishes nothing", published == [])
    wakes_svc.anchor_pass = lambda: ["a2"]
    wakes_svc.minute_anchor_pass()
    check("5 anchor pass: what it released is published", published == ["p"], published)
    wakes_svc.anchor_pass = lambda: []
    published.clear(); wakes_svc.minute_anchor_pass()
    check("5 anchor pass: nothing released, nothing published", published == [])
    wakes_svc.next_wake = lambda: None
    check("5 wake wait: no wake at all, the loop's old 60 s", wakes_svc.minute_wake_wait() == 60.0)
    wakes_svc.next_wake = lambda: dt.datetime.now(ZONE_TZ) + dt.timedelta(seconds=20)
    w = wakes_svc.minute_wake_wait()
    check("5 wake wait: a wake in 20 s, about 20 s", 18.0 < w <= 20.0, w)
    wakes_svc.next_wake = lambda: dt.datetime.now(ZONE_TZ) + dt.timedelta(hours=2)
    check("5 wake wait: a wake in hours, the 60 s cap", wakes_svc.minute_wake_wait() == 60.0)
    wakes_svc.next_wake = lambda: dt.datetime.now(ZONE_TZ) - dt.timedelta(hours=1)
    check("5 wake wait: a wake already due, 0 (the runner's floor then applies)", wakes_svc.minute_wake_wait() == 0.0)
    real_paused = server._watch.paused
    server._watch.paused = lambda: True
    check("5 wake wait: while [model] pause holds every wake, 60 s (nothing fires, so no spinning on a due wake)", wakes_svc.minute_wake_wait() == 60.0)
    server._watch.paused = real_paused
finally:
    wakes_svc.next_wake, wakes_svc.wake_pass, wakes_svc.anchor_pass = real_nw, real_wp, real_ap

# ---- 6. the runner's watchdog and the publish loop
clk6 = Clock(5000.0)
rn6 = R.Runner([R.Tick("noop", lambda: None, "settle")], clock=clk6, label="runner")
check("6 stalled: a runner never started is not stalled, however late the clock", rn6.stalled(now=clk6() + 10 * R.STALL_AFTER) is False)
rn6.started = clk6()
check("6 stalled: the limit is a named constant of 3 minutes", R.STALL_AFTER == 180.0, R.STALL_AFTER)
check("6 stalled: started and no round yet is measured from the start (current, then past the limit)", rn6.stalled(now=clk6() + 100) is False and rn6.stalled(now=clk6() + 181) is True)
clk6.advance(30); rn6.run_round(event=True)
check("6 stalled: the last completed round is what counts (exactly at the limit is current, past it stalled)",
      rn6.stalled(now=rn6.last_round + R.STALL_AFTER) is False and rn6.stalled(now=rn6.last_round + R.STALL_AFTER + 1) is True)
check("6 stalled: without an argument it reads the runner's clock", rn6.stalled() is False and (clk6.advance(240) or rn6.stalled()) is True)
rn6.run_round(event=True)
check("6 stalled: a round that completes makes it current again at once", rn6.stalled() is False)

sent6 = []
real_flag, real_audit_cfg = server._inbox_flag_send, dict(_cfg.CFG.get("audit") or {})
server._inbox_flag_send = lambda to, text: sent6.append((to, text))
_cfg.CFG["audit"] = {**real_audit_cfg, "builder": "builder-x"}
runner_svc.RUNNER[:] = [rn6]; runner_svc.RUNNER_STALL[0] = False
try:
    with stderr_lines() as err:
        r0 = runner_svc.watchdog()
    check("6 watchdog: a current runner sends nothing and logs nothing", r0 == "" and sent6 == [] and "stalled" not in err.getvalue(), (r0, sent6, err.getvalue()))
    clk6.advance(240)
    with stderr_lines() as err:
        r1 = runner_svc.watchdog()
    check("6 watchdog: stalled 4 minutes -> exactly one message to the builder and exactly one log line", r1 == "told" and len(sent6) == 1 and sent6[0][0] == "builder-x"
          and err.getvalue().count("stalled") == 1 and len(err.getvalue().strip().splitlines()) == 1, (r1, sent6, err.getvalue()))
    check("6 watchdog: ...the message says how long, asks nothing of the owner and owes no reply", "4 min" in sent6[0][1] and "no reply is owed" in sent6[0][1], sent6[0][1])
    clk6.advance(600)
    with stderr_lines() as err:
        r2 = runner_svc.watchdog()
    check("6 watchdog: a second look while it is still stalled sends no second message and logs nothing more", r2 == "noted" and len(sent6) == 1 and err.getvalue() == "", (r2, sent6, err.getvalue()))
    rn6.run_round(event=True)
    check("6 watchdog: a completed round re-arms it (no message, the episode is over)", runner_svc.watchdog() == "" and runner_svc.RUNNER_STALL[0] is False and len(sent6) == 1)
    clk6.advance(300)
    with stderr_lines() as err:
        r3 = runner_svc.watchdog()
    check("6 watchdog: a new stall after the re-arm is told again, once", r3 == "told" and len(sent6) == 2 and err.getvalue().count("stalled") == 1, (r3, sent6))
    # no builder configured: the line is logged, nobody is messaged
    rn6.run_round(event=True); runner_svc.watchdog(); clk6.advance(300)
    _cfg.CFG["audit"] = {**real_audit_cfg, "builder": ""}
    n_before = len(sent6)
    with stderr_lines() as err:
        r4 = runner_svc.watchdog()
    check("6 watchdog: with the builder unset the config default still names one (the message goes there, once)", r4 == "told" and len(sent6) == n_before + 1 and sent6[-1][0] == _cfg.audit_builder() and err.getvalue().count("stalled") == 1, (r4, sent6))
    _cfg.CFG["audit"] = {**real_audit_cfg, "builder": "builder-x"}
    runner_svc.RUNNER[:] = []
    check("6 watchdog: with no runner started it does nothing", runner_svc.watchdog() == "")

    # where the stall sits: the message names the tick that is running
    rn8 = R.Runner([R.Tick("noop", lambda: None, "settle")], clock=clk6, label="runner"); rn8.started = clk6(); rn8.run_round(event=True)
    runner_svc.RUNNER[:] = [rn8]; runner_svc.RUNNER_STALL[0] = False; sent6.clear(); rn8.current = "evwait_tick"; clk6.advance(400)
    with stderr_lines():
        runner_svc.watchdog()
    check("6 watchdog: ...the message names the tick the runner is stuck in", len(sent6) == 1 and "stuck in the tick evwait_tick" in sent6[0][1], sent6)
    seen_cur = []
    rn9 = R.Runner([R.Tick("probe", lambda: seen_cur.append(rn9.current), "settle")], clock=clk6, label="runner"); rn9.run_round(event=True)
    check("6 current: the runner names the tick it is running, and nothing between ticks", seen_cur == ["probe"] and rn9.current == "", (seen_cur, rn9.current))

    # the watchdog has its own thread: the loop function, one pass at a time, with the fake clock
    class Stop:
        def __init__(self, n): self.n, self.waits = n, []
        def wait(self, every): self.waits.append(every); self.n -= 1; return self.n < 0
    runner_svc.RUNNER[:] = [rn8]; runner_svc.RUNNER_STALL[0] = False; sent6.clear()
    stop = Stop(2)
    with stderr_lines() as err:
        runner_svc.watchdog_loop(stop)
    check("6 watchdog loop: two looks of a stalled runner, a minute apart, send one message and log one line", stop.waits == [60.0, 60.0, 60.0] and len(sent6) == 1 and err.getvalue().count("stalled") == 1, (stop.waits, sent6, err.getvalue()))
    real_wd = runner_svc.watchdog
    runner_svc.watchdog = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("wd broke"))
    try:
        with stderr_lines() as err:
            runner_svc.watchdog_loop(Stop(2))
    finally:
        runner_svc.watchdog = real_wd
    check("6 watchdog loop: a look that raises is logged and the loop goes on", err.getvalue().count("runner watchdog failed: RuntimeError: wd broke") == 2, err.getvalue())

    # the publish loop: no wake pass and no watchdog of its own (the runner's ten-minute set and the watchdog's thread do those)
    class StopLoop(BaseException): pass
    woke, pubs, sleeps = [], [], []
    real_wp7, real_pn, real_sleep = wakes_svc.wake_pass, server._publish_now, time.sleep
    wakes_svc.wake_pass = lambda *a, **k: woke.append(1) or []
    server._publish_now = _wt_rules._publish_now = lambda **k: pubs.append(k)
    sent6.clear(); runner_svc.RUNNER_STALL[0] = False
    def fake_sleep(sec):
        sleeps.append(sec)
        if len(sleeps) > 2: raise StopLoop()
    time.sleep = fake_sleep
    try:
        with stderr_lines() as err:
            try: runner_svc.publish_loop()
            except StopLoop: pass
    finally:
        time.sleep, wakes_svc.wake_pass, server._publish_now = real_sleep, real_wp7, real_pn; _wt_rules._publish_now = real_pn
    check("6 publish loop: two passes publish twice (always probing versions) and call no wake pass and no watchdog", woke == [] and sent6 == [] and len(pubs) == 2 and all(p.get("force_versions") for p in pubs), (woke, sent6, pubs))
    import inspect
    check("6 publish loop: its source holds neither the wake pass nor the watchdog", "wake_pass(" not in inspect.getsource(runner_svc.publish_loop) and "watchdog(" not in inspect.getsource(runner_svc.publish_loop))
finally:
    server._inbox_flag_send = real_flag; _cfg.CFG["audit"] = real_audit_cfg; runner_svc.RUNNER[:] = []; runner_svc.RUNNER_STALL[0] = False

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed" + ("" if not fails else f"; FAILED: {len(fails)}"))
sys.exit(1 if fails else 0)
