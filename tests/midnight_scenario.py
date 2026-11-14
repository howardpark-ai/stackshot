"""Scenario test for tests/_midnight.py `wait_out` - a fake clock and a fake sleep, no live store, no network, no server.

  1  A midnight of the zone that is further away than the margin: no sleep. One that is nearer: a sleep to one second past it (the clock then stands on the far side). Exactly at the margin: no sleep.
  2  The zone decides: 23:58 in Dubai is 19:58 UTC, so the same instant is a close midnight for one zone and a far one for the other; a time just past a midnight is a far one.
  3  The margin is the caller's: a wider one catches a midnight a default one lets pass.
  4  The wiring: each suite that guards itself (GUARDED) calls `wait_out` once, as a statement at the top of the file, before its first read of the clock, with the zone the suite itself
     pins as the instance timezone (read from its own `("timezone", ...)` pin, never typed here). The checker is shown a suite without the call, with the call nested, after a clock
     read, with another zone, with two pins, and with no clock read at all.

    tests/run-suite midnight        -> exit 0 / 1"""
import ast, datetime, os, sys, zoneinfo

SCR = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, SCR)
import _midnight

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

class Clock:
    """What `time` is to the helper: a clock that stands where it is told and a sleep that moves it."""
    def __init__(self, at): self.now = at; self.slept = []
    def time(self): return self.now
    def sleep(self, s): self.slept.append(s); self.now += s

def at(zone, y, mo, d, h, mi, s=0): return datetime.datetime(y, mo, d, h, mi, s, tzinfo=zoneinfo.ZoneInfo(zone)).timestamp()
def run(zone, ts, **kw):
    clk = Clock(ts); real = _midnight.time; _midnight.time = clk
    try: got = _midnight.wait_out(zone, **kw)
    finally: _midnight.time = real
    return got, clk

got, clk = run("Asia/Dubai", at("Asia/Dubai", 2026, 11, 14, 12, 0))
check("1 noon: no sleep", got == 0.0 and clk.slept == [], (got, clk.slept))
got, clk = run("Asia/Dubai", at("Asia/Dubai", 2026, 11, 14, 23, 50))
check("1 ten minutes before midnight: no sleep (the margin is 180 s)", got == 0.0 and clk.slept == [], (got, clk.slept))
got, clk = run("Asia/Dubai", at("Asia/Dubai", 2026, 11, 14, 23, 57))
check("1 exactly 180 s before: no sleep", got == 0.0 and clk.slept == [], (got, clk.slept))
got, clk = run("Asia/Dubai", at("Asia/Dubai", 2026, 11, 14, 23, 57, 1))
check("1 179 s before: sleeps to one second past midnight", abs(got - 180.0) < 1e-6 and len(clk.slept) == 1 and abs(clk.now - at("Asia/Dubai", 2026, 11, 15, 0, 0, 1)) < 1e-6, (got, clk.slept))
got, clk = run("Asia/Dubai", at("Asia/Dubai", 2026, 11, 14, 23, 59, 58))
check("1 two seconds before: sleeps three seconds, to 00:00:01", abs(got - 3.0) < 1e-6 and abs(clk.now - at("Asia/Dubai", 2026, 11, 15, 0, 0, 1)) < 1e-6, (got, clk.slept))
got, clk = run("Asia/Dubai", at("Asia/Dubai", 2026, 11, 15, 0, 0, 5))
check("1 just past a midnight: no sleep", got == 0.0 and clk.slept == [], (got, clk.slept))
check("1 the sleep leaves a second call with nothing to do", run("Asia/Dubai", clk.now)[0] == 0.0, clk.now)

t = at("Asia/Dubai", 2026, 11, 14, 23, 58)
check("2 the same instant: a close midnight in Dubai", run("Asia/Dubai", t)[0] > 0.0)
check("2 …and a far one in UTC (19:58)", run("UTC", t)[0] == 0.0)
check("2 UTC's own 23:59:30 is close in UTC and far in Dubai (03:59)", run("UTC", at("UTC", 2026, 11, 14, 23, 59, 30))[0] > 0.0 and run("Asia/Dubai", at("UTC", 2026, 11, 14, 23, 59, 30))[0] == 0.0)

check("3 a wider margin catches a midnight the default lets pass (ten minutes out, margin 15 minutes)", run("Asia/Dubai", at("Asia/Dubai", 2026, 11, 14, 23, 50), within=900.0)[0] > 0.0)
check("3 …a narrower one lets a close one pass (60 s out, margin 30 s)", run("Asia/Dubai", at("Asia/Dubai", 2026, 11, 14, 23, 59), within=30.0)[0] == 0.0)

# ================================================================ 4. the wiring of each guarded suite
GUARDED = ("cap_words", "waiting", "until_write", "agent_due", "event_wait", "state_checks",
           "wait_list_write", "date_only_wait", "box_online_wait", "handoff", "state", "migration", "until_migrate")
def clock_read(node):
    """a call that reads the clock: time.time(), datetime's now()/today()/utcnow(), zone_now(), and time.gmtime()/localtime()/strftime(fmt) with no time given"""
    if not isinstance(node, ast.Call): return False
    f = node.func
    if isinstance(f, ast.Name): return f.id == "zone_now"
    if not isinstance(f, ast.Attribute): return False
    if f.attr in ("now", "today", "utcnow", "zone_now"): return True
    if isinstance(f.value, ast.Name) and f.value.id == "time":
        return f.attr == "time" or (f.attr in ("gmtime", "localtime") and not node.args) or (f.attr == "strftime" and len(node.args) < 2)
    return False
def wiring(src):
    """→ "" when the suite's source guards itself properly, else why not: one `_midnight.wait_out(<zone>)` statement at the top level, before the first clock read in the file, with <zone> the string the suite pins as `timezone`"""
    tree = ast.parse(src)
    pins = [n.elts[1].value for n in ast.walk(tree) if isinstance(n, ast.Tuple) and len(n.elts) == 2 and isinstance(n.elts[0], ast.Constant) and n.elts[0].value == "timezone"
            and isinstance(n.elts[1], ast.Constant) and isinstance(n.elts[1].value, str)]
    if len(pins) != 1: return f"the suite pins the timezone {len(pins)} times as a (\"timezone\", \"<zone>\") pair, not once: {pins}"
    is_call = lambda n: isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "wait_out" and isinstance(n.func.value, ast.Name) and n.func.value.id == "_midnight"
    anywhere = [n for n in ast.walk(tree) if is_call(n)]
    top = [st.value for st in tree.body if isinstance(st, ast.Expr) and is_call(st.value)]
    if len(anywhere) != 1 or len(top) != 1: return f"_midnight.wait_out is called {len(anywhere)} times, {len(top)} of them as a top-level statement: want one, at the top"
    call = top[0]
    if len(call.args) != 1 or call.keywords or not (isinstance(call.args[0], ast.Constant) and call.args[0].value == pins[0]):
        return f"wait_out is given {ast.unparse(call.args[0]) if call.args else 'nothing'}{' and keywords' if call.keywords else ''}, not the pinned zone {pins[0]!r}"
    reads = sorted((n.lineno, n.col_offset) for n in ast.walk(tree) if clock_read(n))
    if not reads: return "the suite reads no clock the checker can see: nothing to guard, or a read it does not know"
    if (call.lineno, call.col_offset) > reads[0]: return f"wait_out stands on line {call.lineno}, after the first read of the clock on line {reads[0][0]}"
    return ""

def suite(pin='("timezone", "Asia/Dubai")', guard='_midnight.wait_out("Asia/Dubai")', clock="now0 = time.time()", before=""):
    """a miniature suite: the pin, an optional statement before the guard, the guard, the first clock read"""
    return "\n".join(["import _scratch, _instance, _midnight", f"for key, val in (('repo', tmp), {pin}): pass", before, guard, clock, ""])
check("4 the checker: a suite wired as it should be passes", wiring(suite()) == "", wiring(suite()))
check("4 …without the call it fails", "0 times" in wiring(suite(guard="")), wiring(suite(guard="")))
check("4 …with another zone it fails, whichever way round (the call changed, the pin changed)",
      "not the pinned zone" in wiring(suite(guard='_midnight.wait_out("UTC")')) and "not the pinned zone" in wiring(suite(pin='("timezone", "UTC")')), None)
check("4 …with the zone from a name it fails (it must be the pinned string itself)", "not the pinned zone" in wiring(suite(guard="_midnight.wait_out(ZONE)")), None)
check("4 …with the guard after the clock read it fails (time.time, datetime now, zone_now, time.gmtime())",
      all("after the first read" in wiring(suite(before=b)) for b in ("x = time.time()", "x = dt.datetime.now(z)", "x = server._pages.zone_now()", "x = time.gmtime()", "x = time.strftime('%Y')")), None)
check("4 …a time.strftime of a time already in hand is no read of the clock", wiring(suite(before="x = time.strftime('%Y', t)")) == "", None)
check("4 …nested (an `if`, a function) it fails", all("top-level" in wiring(suite(guard=g)) for g in ('if False: _midnight.wait_out("Asia/Dubai")', 'def f(): _midnight.wait_out("Asia/Dubai")')), None)
check("4 …called twice it fails", "2 times" in wiring(suite(before='_midnight.wait_out("Asia/Dubai")')), None)
check("4 …with no pin, or two, it fails", "0 times" in wiring(suite(pin='("tz", "Asia/Dubai")')) and "2 times" in wiring(suite(before='x = [("timezone", "UTC")]')), None)
check("4 …with no clock read it can see it fails (a guard with nothing to guard is a guard nobody checks)", "no clock" in wiring(suite(clock="now0 = 1")), None)
for name in GUARDED:
    why = wiring(open(os.path.join(SCR, f"{name}_scenario.py"), encoding="utf-8").read())
    check(f"4 {name}: waits out a midnight before its first clock read, with the zone it pins", why == "", why)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed" + ("" if not fails else f"; FAILED: {len(fails)}"))
sys.exit(1 if fails else 0)
