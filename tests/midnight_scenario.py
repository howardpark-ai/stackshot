"""Scenario test for tests/_midnight.py `wait_out` - a fake clock and a fake sleep, no live store, no network, no server.

  1  A midnight of the zone that is further away than the margin: no sleep. One that is nearer: a sleep to one second past it (the clock then stands on the far side). Exactly at the margin: no sleep.
  2  The zone decides: 23:58 in Dubai is 19:58 UTC, so the same instant is a close midnight for one zone and a far one for the other; a time just past a midnight is a far one.
  3  The margin is the caller's: a wider one catches a midnight a default one lets pass.

    tests/run-suite midnight        -> exit 0 / 1"""
import datetime, os, sys, zoneinfo

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

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed" + ("" if not fails else f"; FAILED: {len(fails)}"))
sys.exit(1 if fails else 0)
